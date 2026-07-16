"""
Celery tasks for package operations
"""
from celery import shared_task
from django.conf import settings
import logging
import os

from backend.core.spec_generator import SpecFileGenerator
from backend.core.pypi_client import PyPIClient

logger = logging.getLogger(__name__)


def _normalize_source0_to_pypi_macro(spec_content: str, package) -> tuple[str, bool]:
    """
    Normalize Source0 to use %{pypi_source <name>} when Source0 is a literal
    PyPI tarball path/name. Returns (content, changed).
    """
    import re

    content = spec_content or ""
    pypi_name = (getattr(package, 'python_name', '') or getattr(package, 'name', '') or '').strip()
    if not content or not pypi_name:
        return content, False

    m = re.search(r'^Source0:\s*(.+)$', content, flags=re.MULTILINE)
    if not m:
        return content, False

    source_expr = m.group(1).strip()
    if source_expr.startswith('%{pypi_source'):
        desired = f'Source0:        %{{pypi_source {pypi_name}}}'
        new_content = re.sub(r'^Source0:\s*.+$', desired, content, flags=re.MULTILINE, count=1)
        return new_content, new_content != content

    # Convert only clearly PyPI-style literal source definitions.
    is_pypi_literal = (
        ('%{version}' in source_expr and re.search(r'\.tar\.(gz|bz2|xz)|\.zip', source_expr))
        or 'pythonhosted.org' in source_expr
        or '/packages/' in source_expr
    )
    if not is_pypi_literal:
        return content, False

    desired = f'Source0:        %{{pypi_source {pypi_name}}}'
    new_content = re.sub(r'^Source0:\s*.+$', desired, content, flags=re.MULTILINE, count=1)
    return new_content, new_content != content


def _ensure_spec_source0_macro(package, spec_revision, reason: str = 'runtime'):
    """
    Ensure the provided spec revision uses %{pypi_source ...} in Source0.
    If normalized, persist a new SpecFileRevision and return it.
    """
    from backend.apps.packages.models import SpecFileRevision

    if not spec_revision:
        return spec_revision

    normalized_content, changed = _normalize_source0_to_pypi_macro(spec_revision.content, package)
    if not changed:
        return spec_revision

    new_rev = SpecFileRevision.objects.create(
        package=package,
        content=normalized_content,
        commit_message=f'Auto-normalized Source0 to %{{pypi_source ...}} ({reason})',
    )
    log_package(package.id, 'info', 'Auto-normalized Source0 to pypi_source macro')
    logger.info(f"Auto-normalized Source0 for {package.name} (rev {spec_revision.id} -> {new_rev.id})")
    return new_rev


def _extract_extras_from_pypi_info(info: dict) -> dict[str, list[str]]:
    """
    Build a normalized extras->dependencies mapping from PyPI JSON metadata.
    """
    import re

    extras_data: dict[str, list[str]] = {}

    provides_extra = info.get('provides_extra') or []
    for extra in provides_extra:
        extra_name = (extra or '').strip().lower()
        if extra_name:
            extras_data.setdefault(extra_name, [])

    requires_dist = info.get('requires_dist') or []
    for req in requires_dist:
        if not req:
            continue
        extra_names = re.findall(r"extra\s*==\s*['\"]([^'\"]+)['\"]", req, flags=re.IGNORECASE)
        if not extra_names:
            continue

        dep = req.split(';', 1)[0].strip()
        if not dep:
            continue

        for extra_name in extra_names:
            normalized_extra = (extra_name or '').strip().lower()
            if not normalized_extra:
                continue
            extras_data.setdefault(normalized_extra, [])
            if dep not in extras_data[normalized_extra]:
                extras_data[normalized_extra].append(dep)

    return extras_data


def send_package_update(package_id: int):
    """Send WebSocket update for a package"""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        from backend.apps.packages.models import Package
        
        package = Package.objects.get(id=package_id)
        channel_layer = get_channel_layer()
        
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'project_{package.project_id}',
                {
                    'type': 'package_update',
                    'package': {
                        'id': package.id,
                        'name': package.name,
                        'version': package.version,
                        'status': package.status,
                        'status_message': package.status_message,
                        'package_type': package.package_type,
                        'build_order': package.build_order,
                        'has_spec': package.spec_revisions.exists(),
                        'source_fetched': package.source_fetched,
                        'source_path': package.source_path,
                        'build_status': package.build_status,
                        'build_started_at': package.build_started_at.isoformat() if package.build_started_at else None,
                        'build_completed_at': package.build_completed_at.isoformat() if package.build_completed_at else None,
                        'build_error_message': package.build_error_message,
                        'analyzed_errors': package.analyzed_errors or [],
                        'srpm_path': package.srpm_path,
                        'rpm_path': package.rpm_path,
                        'waiting_for_dep_names': [
                            dep.depends_on.name
                            for dep in package.dependencies.select_related('depends_on').all()
                            if dep.depends_on
                            and dep.depends_on.build_status not in ('completed', 'not_required')
                        ] if package.build_status == 'waiting_for_deps' else [],
                    }
                }
            )
    except Exception as e:
        logger.warning(f"Failed to send WebSocket update for package {package_id}: {e}")


def log_package(package_id: int, level: str, message: str):
    """
    Create a log entry for a package
    
    Args:
        package_id: ID of the package
        level: Log level (debug, info, warning, error)
        message: Log message
    """
    from backend.apps.packages.models import PackageLog
    
    try:
        PackageLog.objects.create(
            package_id=package_id,
            level=level,
            message=message
        )
    except Exception as e:
        logger.error(f"Failed to create package log: {e}")


@shared_task(bind=True, max_retries=3)
def generate_spec_file_task(self, package_id: int, force: bool = False, auto_build: bool = False, auto_fetch: bool = True):
    """
    Generate RPM spec file for a package
    
    Args:
        package_id: ID of the package
        force: Force regeneration even if spec file exists
        auto_build: If True, queue a build task after successful spec generation (or after fetch if auto_fetch is also True)
        auto_fetch: If True (default), automatically fetch sources after spec generation
    """
    from backend.apps.builds.concurrency import limiter
    
    try:
        # Acquire job slot with concurrency limiting
        with limiter.try_acquire(f"spec_{package_id}"):
            from backend.apps.packages.models import Package, SpecFileRevision
            from backend.apps.projects.tasks import log_project
            
            package = Package.objects.get(id=package_id)
            
            # Check if spec file already exists
            if not force and SpecFileRevision.objects.filter(package=package).exists():
                logger.info(f"Spec file already exists for package {package_id}")
                log_package(package_id, 'info', "Spec file already exists, skipping generation")
                return
            
            log_project(package.project_id, 'debug', f"Generating spec file for {package.name}...")
            log_package(package_id, 'info', f"Starting spec file generation...")
            
            # Get project's Python version
            python_version = package.project.python_version if package.project else "3.11"
            
            # Initialize generators
            spec_gen = SpecFileGenerator()
            pypi_client = PyPIClient()
            
            # Fetch metadata from PyPI
            log_package(package_id, 'debug', f"Fetching metadata from PyPI...")
            pkg_info = pypi_client.get_package_info(package.name, package.version or None)
            
            if not pkg_info:
                log_project(package.project_id, 'warning', f"Could not fetch metadata for {package.name} from PyPI")
                log_package(package_id, 'error', "Could not fetch metadata from PyPI")
                logger.error(f"Could not fetch metadata for package {package.name}")
                return
            
            # Update package information
            if not package.version and pkg_info.version:
                package.version = pkg_info.version
                package.save()
                log_package(package_id, 'debug', f"Updated package version to {pkg_info.version}")
            
            # Store the canonical Python package name from PyPI tarball (may differ from normalized RPM name)
            # Extract from source tarball filename as PyPI metadata name may use hyphens while tarball uses underscores
            if not package.python_name and pkg_info.source_url:
                import os
                import re
                tarball_name = os.path.basename(pkg_info.source_url)
                # Extract package name from tarball: package_name-version.tar.gz
                match = re.match(r'^(.+?)-(\d+.*?)\.tar\.gz$', tarball_name)
                if match:
                    python_name = match.group(1)
                    package.python_name = python_name
                    package.save(update_fields=['python_name'])
                    log_package(package_id, 'debug', f"Stored Python package name from tarball: {python_name}")
                else:
                    log_package(package_id, 'warning', f"Could not parse tarball name: {tarball_name}")

            # Detect build system (only if not already set by user)
            build_system = package.build_system if package.build_system != 'unknown' else 'unknown'
            if build_system == 'unknown':
                log_package(package_id, 'debug', "Detecting build system from PyPI...")
                build_system = pypi_client.detect_build_system(package.name, pkg_info.version)
                package.build_system = build_system
                package.save(update_fields=['build_system'])
                log_package(package_id, 'info', f"Detected build system: {build_system}")
            else:
                log_package(package_id, 'debug', f"Using stored build system: {build_system}")
            
            # Generate spec file with project's Python version
            log_package(package_id, 'debug', f"Generating RPM spec file for version {pkg_info.version} with Python {python_version} (build system: {build_system})...")
            spec_content = spec_gen.generate_spec(
                package_name=package.name,
                version=pkg_info.version,
                python_version=python_version,
                build_system=build_system,
                python_name=package.python_name,
                pypi_metadata={'info': pkg_info.__dict__, 'urls': []}
            )
            
            if not spec_content:
                log_project(package.project_id, 'error', f"Failed to generate spec file for {package.name}")
                log_package(package_id, 'error', "Failed to generate spec file content")
                logger.error(f"Failed to generate spec file for package {package_id}")
                return
            
            # Create spec file revision
            SpecFileRevision.objects.create(
                package=package,
                content=spec_content,
                commit_message=f"Initial spec file generated from PyPI metadata for version {pkg_info.version}",
                created_by=None  # System generated
            )
            
            # Update package status to ready
            package.status = 'ready'
            package.status_message = f"Spec file generated for version {pkg_info.version}"
            package.save()
            
            # Send WebSocket update
            send_package_update(package_id)
            
            log_project(package.project_id, 'debug', f"Spec file generated for {package.name} v{pkg_info.version}")
            log_package(package_id, 'info', f"Spec file successfully generated for version {pkg_info.version}")
            logger.info(f"Generated spec file for package {package_id}")
            
            # Automatically sync extras from PyPI after spec generation
            log_package(package_id, 'debug', f"Syncing package extras from PyPI...")
            try:
                sync_package_extras_task.delay(package_id)
                log_package(package_id, 'debug', f"Extras sync task queued")
            except Exception as sync_error:
                logger.warning(f"Failed to queue extras sync for package {package_id}: {sync_error}")
                # Don't fail the entire task if extras sync fails

            # Auto-fetch sources unless they are already present
            if auto_fetch and not package.source_fetched:
                try:
                    fetch_package_source_task.delay(package_id, auto_build=auto_build)
                    log_package(package_id, 'info', 'Spec generated; automatically fetching sources...')
                    logger.info(f"Auto-queued source fetch for package {package_id}")
                except Exception as fetch_err:
                    logger.warning(f"Failed to auto-queue fetch for package {package_id}: {fetch_err}")
            elif auto_build:
                # Sources already fetched — queue build directly
                try:
                    build_single_package_task.apply_async(args=[package_id], countdown=5)
                    log_package(package_id, 'info', 'Spec generated; build queued automatically')
                    logger.info(f"Auto-queued build for new dependency package {package_id}")
                except Exception as build_err:
                    logger.warning(f"Failed to auto-queue build for package {package_id}: {build_err}")
    
    except TimeoutError as e:
        # Could not acquire job slot
        log_package(package_id, 'warning', f"Waiting for available job slot: {str(e)}")
        logger.warning(f"Spec generation {package_id} could not acquire slot: {e}")
        # Retry the task
        raise self.retry(exc=e, countdown=60)
    
    except Exception as e:
        log_package(package_id, 'error', f"Error during spec generation: {str(e)}")
        logger.error(f"Error generating spec file for package {package_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def update_package_metadata_task(self, package_id: int):
    """
    Update package metadata from PyPI
    
    Args:
        package_id: ID of the package
    """
    try:
        from backend.apps.packages.models import Package
        
        package = Package.objects.get(id=package_id)
        
        # Fetch latest metadata
        pypi_client = PyPIClient()
        pkg_info = pypi_client.get_package_info(package.name)
        
        if not pkg_info:
            logger.error(f"Could not fetch metadata for package {package.name}")
            return
        
        # Update package fields
        package.latest_version = pkg_info.version
        package.description = pkg_info.summary
        package.license = pkg_info.license
        package.homepage = pkg_info.home_page
        package.save()
        
        logger.info(f"Updated metadata for package {package_id}")
    
    except Exception as e:
        logger.error(f"Error updating metadata for package {package_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def sync_package_extras_task(self, package_id: int):
    """
    Sync package extras from PyPI metadata
    
    Fetches the package metadata from PyPI and creates/updates PackageExtra
    records for each extra defined in the package (e.g., requests[security]).
    
    Args:
        package_id: ID of the package
    """
    try:
        from backend.apps.packages.models import Package, PackageExtra
        import requests
        
        package = Package.objects.get(id=package_id)
        log_package(package_id, 'info', f"Syncing extras from PyPI...")
        
        # Fetch metadata from PyPI JSON API
        pypi_url = f"https://pypi.org/pypi/{package.name}/json"
        if package.version:
            pypi_url = f"https://pypi.org/pypi/{package.name}/{package.version}/json"
        
        response = requests.get(pypi_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Extract extras from provides_extra and requires_dist markers.
        info = data.get('info', {})
        extras_data = _extract_extras_from_pypi_info(info)
        
        # Create or update PackageExtra records
        created_count = 0
        updated_count = 0
        
        for extra_name, dependencies in extras_data.items():
            deps_str = ', '.join(dependencies) if dependencies else ''
            
            extra, created = PackageExtra.objects.get_or_create(
                package=package,
                name=extra_name,
                defaults={'dependencies': deps_str}
            )
            
            if created:
                created_count += 1
                log_package(package_id, 'debug', f"Created extra: {extra_name}")
            else:
                # Update dependencies if changed
                if extra.dependencies != deps_str:
                    extra.dependencies = deps_str
                    extra.save()
                    updated_count += 1
                    log_package(package_id, 'debug', f"Updated extra: {extra_name}")
        
        # Remove extras that no longer exist in PyPI
        existing_extras = PackageExtra.objects.filter(package=package)
        deleted_count = 0
        for extra in existing_extras:
            if extra.name not in extras_data:
                extra.delete()
                deleted_count += 1
                log_package(package_id, 'debug', f"Removed extra: {extra.name}")

        cleanup = None
        if created_count > 0 or deleted_count > 0:
            from backend.apps.packages.artifact_cleanup import (
                wipe_package_artifacts_for_rebuild,
                reset_package_build_state,
            )
            from backend.apps.projects.tasks import resolve_dependencies_task

            cleanup = wipe_package_artifacts_for_rebuild(package, reason='sync-extras-added-removed')
            reset_package_build_state(package)

            # Regenerate spec and re-resolve project dependencies when extra set changes.
            generate_spec_file_task.delay(package.id, force=True)
            resolve_dependencies_task.delay(package.project.id)
        
        log_message = f"Synced extras: {created_count} created, {updated_count} updated, {deleted_count} removed"
        log_package(package_id, 'info', log_message)
        logger.info(f"Package {package_id}: {log_message}")
        
        return {
            'created': created_count,
            'updated': updated_count,
            'deleted': deleted_count,
            'total': len(extras_data),
            'cleanup': cleanup,
        }
    
    except requests.RequestException as e:
        log_package(package_id, 'error', f"Failed to fetch PyPI metadata: {str(e)}")
        logger.error(f"Error fetching PyPI metadata for package {package_id}: {e}")
        raise self.retry(exc=e, countdown=60)
    
    except Exception as e:
        log_package(package_id, 'error', f"Error syncing extras: {str(e)}")
        logger.error(f"Error syncing extras for package {package_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True)
def scan_packages_for_missing_extras_task(self, project_id: int | None = None):
    """
    Scan packages and queue extras sync for packages missing one or more extras
    compared to PyPI metadata.

    This task is intended to run periodically from Celery beat.
    """
    from backend.apps.packages.models import Package, PackageExtra
    import requests

    timeout = int(settings.REQPM.get('EXTRAS_SCAN_REQUEST_TIMEOUT', 8))
    max_requeues = int(settings.REQPM.get('EXTRAS_SCAN_MAX_REQUEUES', 0))

    packages_qs = Package.objects.all().only('id', 'name', 'version', 'project_id')
    if project_id is not None:
        packages_qs = packages_qs.filter(project_id=project_id)

    packages = list(packages_qs)
    if not packages:
        return {
            'scanned': 0,
            'with_remote_extras': 0,
            'missing_extras': 0,
            'queued_syncs': 0,
            'errors': 0,
        }

    package_ids = [p.id for p in packages]
    local_extras_map: dict[int, set[str]] = {}
    for pkg_id, extra_name in PackageExtra.objects.filter(
        package_id__in=package_ids
    ).values_list('package_id', 'name'):
        local_extras_map.setdefault(pkg_id, set()).add((extra_name or '').strip().lower())

    scanned = 0
    with_remote_extras = 0
    missing_extras = 0
    queued_syncs = 0
    errors = 0

    for package in packages:
        scanned += 1
        urls = []
        if package.version:
            urls.append(f'https://pypi.org/pypi/{package.name}/{package.version}/json')
        urls.append(f'https://pypi.org/pypi/{package.name}/json')

        info = None
        for url in urls:
            try:
                response = requests.get(url, timeout=timeout)
                if response.status_code == 200:
                    info = response.json().get('info', {})
                    break
            except Exception:
                continue

        if info is None:
            errors += 1
            continue

        remote_extras = set(_extract_extras_from_pypi_info(info).keys())
        if not remote_extras:
            continue

        with_remote_extras += 1
        local_extras = local_extras_map.get(package.id, set())
        if remote_extras.issubset(local_extras):
            continue

        missing_extras += 1
        sync_package_extras_task.delay(package.id)
        queued_syncs += 1

        if max_requeues > 0 and queued_syncs >= max_requeues:
            logger.info(
                f"Extras scan reached EXTRAS_SCAN_MAX_REQUEUES={max_requeues}; stopping early"
            )
            break

    logger.info(
        "Extras scan complete: "
        f"scanned={scanned}, with_remote_extras={with_remote_extras}, "
        f"missing_extras={missing_extras}, queued_syncs={queued_syncs}, errors={errors}"
    )
    return {
        'scanned': scanned,
        'with_remote_extras': with_remote_extras,
        'missing_extras': missing_extras,
        'queued_syncs': queued_syncs,
        'errors': errors,
        'project_id': project_id,
    }


@shared_task
def generate_all_spec_files_task(project_id: int):
    """
    Generate spec files for all packages in a project
    
    Args:
        project_id: ID of the project
    """
    from backend.apps.packages.models import Package
    from backend.apps.projects.models import ProjectLog
    
    packages = Package.objects.filter(project_id=project_id)
    
    ProjectLog.objects.create(
        project_id=project_id,
        level='info',
        message=f"Starting spec file generation for {packages.count()} packages"
    )
    
    for package in packages:
        # Force regeneration to update existing specs; don't auto-fetch (sources already present)
        generate_spec_file_task.delay(package.id, force=True, auto_fetch=False)
    
    logger.info(f"Triggered spec file generation for {packages.count()} packages in project {project_id}")


@shared_task
def check_package_updates_task(project_id: int):
    """
    Check for updates to packages in a project
    
    Args:
        project_id: ID of the project
    """
    from backend.apps.packages.models import Package
    
    packages = Package.objects.filter(project_id=project_id)
    
    pypi_client = PyPIClient()
    updates_found = 0
    
    for package in packages:
        latest_version = pypi_client.get_latest_version(package.name)
        
        if latest_version and latest_version != package.version:
            package.latest_version = latest_version
            package.save()
            updates_found += 1
            logger.info(f"Update available for {package.name}: {package.version} -> {latest_version}")
    
    logger.info(f"Found {updates_found} package updates for project {project_id}")
    return updates_found


@shared_task(bind=True, name='fetch_package_source_task')
def fetch_package_source_task(self, package_id: int, auto_build: bool = False):
    """
    Fetch source files for a package
    
    Args:
        package_id: ID of the package
        auto_build: If True, queue a build task after successful source fetch
    """
    from backend.apps.builds.concurrency import limiter
    from backend.apps.packages.models import Package, SpecFileRevision
    from backend.apps.projects.tasks import log_project
    from django.conf import settings
    from pathlib import Path
    from backend.plugins.builders.mock import MockBuilder
    
    try:
        # Acquire job slot with concurrency limiting
        with limiter.try_acquire(f"fetch_{package_id}"):
            package = Package.objects.get(id=package_id)
            
            # Check if spec file exists
            spec_revision = SpecFileRevision.objects.filter(
                package=package
            ).order_by('-created_at').first()
            
            if not spec_revision:
                log_package(package_id, 'error', "No spec file found, generate one first")
                logger.error(f"No spec file for package {package_id}")
                return

            spec_revision = _ensure_spec_source0_macro(package, spec_revision, reason='source-fetch')
            
            log_project(package.project_id, 'debug', f"Fetching sources for {package.name}...")
            log_package(package_id, 'info', f"Starting source fetching...")
            
            # Prepare directory for sources
            sources_dir = Path(settings.REQPM['BUILD_DIR']) / 'sources' / package.name
            sources_dir.mkdir(parents=True, exist_ok=True)
            
            # Write spec file temporarily
            spec_file = sources_dir / f"{package.name}.spec"
            spec_file.write_text(spec_revision.content)
            
            # Initialize builder and fetch sources
            builder = MockBuilder(settings)
            
            log_package(package_id, 'debug', f"Fetching sources from spec file...")
            fetch_result = builder.fetch_sources(
                spec_file=str(spec_file),
                sources_dir=str(sources_dir)
            )
            
            if fetch_result.success:
                log_project(package.project_id, 'debug', f"Sources fetched for {package.name}")
                log_package(package_id, 'info', f"Sources successfully fetched")
                logger.info(f"Sources fetched for package {package_id}")

                # Persist fetch timestamp so source_fetched returns True from the DB
                from django.utils import timezone as _tz
                package.sources_fetched_at = _tz.now()
                package.save(update_fields=['sources_fetched_at'])

                # Send WebSocket update to refresh UI with new source status
                send_package_update(package_id)

                if auto_build:
                    try:
                        build_single_package_task.delay(package_id)
                        log_package(package_id, 'info', 'Sources fetched; build queued automatically')
                        logger.info(f"Auto-queued build after fetch for package {package_id}")
                    except Exception as build_err:
                        logger.warning(f"Failed to auto-queue build after fetch for package {package_id}: {build_err}")
            else:
                log_project(package.project_id, 'error', f"Failed to fetch sources for {package.name}: {fetch_result.error_message}")
                log_package(package_id, 'error', f"Source fetching failed: {fetch_result.error_message}")
                logger.error(f"Source fetching failed for package {package_id}: {fetch_result.error_message}")
    
    except TimeoutError as e:
        # Could not acquire job slot
        log_package(package_id, 'warning', f"Waiting for available job slot: {str(e)}")
        logger.warning(f"Source fetch {package_id} could not acquire slot: {e}")
        # Retry the task
        raise self.retry(exc=e, countdown=60)
        
    except Package.DoesNotExist:
        logger.error(f"Package {package_id} not found")
    except Exception as e:
        logger.exception(f"Error fetching sources for package {package_id}: {e}")
        log_package(package_id, 'error', f"Error fetching sources: {str(e)}")


@shared_task(bind=True, max_retries=3)
def build_single_package_task(self, package_id: int):
    """
    Build a single package and update its build status
    
    Args:
        package_id: ID of the package to build
    """
    from backend.apps.builds.concurrency import limiter
    from backend.plugins.builders import get_builder
    from backend.core.error_analyzer import BuildErrorAnalyzer
    from pathlib import Path
    import shutil
    from django.utils import timezone
    
    try:
        # Non-blocking slot acquisition — don't tie up the Celery worker waiting
        with limiter.try_acquire(f"build_package_{package_id}"):
            from backend.apps.packages.models import Package, SpecFileRevision
            from backend.apps.projects.tasks import log_project
            
            package = Package.objects.get(id=package_id)
            project = package.project
            rhel_version = project.rhel_version
            
            # Update status to pending
            package.build_status = 'pending'
            package.build_started_at = None
            package.build_completed_at = None
            package.build_log = ''
            package.build_error_message = ''
            package.build_dependency_repo_url = ''
            package.srpm_path = ''
            package.rpm_path = ''
            package.save()
            send_package_update(package_id)
            
            log_project(project.id, 'info', f"Starting build for {package.name} (RHEL {rhel_version})...")
            log_package(package_id, 'info', f"Starting build for RHEL {rhel_version}...")
            
            # Update status to building
            package.build_status = 'building'
            package.build_started_at = timezone.now()
            package.save()
            send_package_update(package_id)
            
            # Get builder
            builder = get_builder('mock')
            
            if not builder or not builder.is_available():
                package.build_status = 'failed'
                package.build_completed_at = timezone.now()
                package.build_error_message = (
                    "Mock builder is not available. "
                    "Mock is required for building RPM packages. "
                    "Please install Mock: sudo dnf install mock && sudo usermod -a -G mock $USER\n"
                    "See docs/MOCK_SETUP.md for complete setup instructions."
                )
                package.save()
                send_package_update(package_id)
                log_project(project.id, 'error', f"Build failed for {package.name}: Mock not available")
                log_package(package_id, 'error', "Mock builder not available")
                logger.error(f"Mock builder not available for package {package_id}")
                return
            
            # Get spec file
            spec_revision = SpecFileRevision.objects.filter(
                package=package
            ).order_by('-created_at').first()
            
            if not spec_revision:
                package.build_status = 'failed'
                package.build_completed_at = timezone.now()
                package.build_error_message = "No spec file found"
                package.save()
                send_package_update(package_id)
                log_project(project.id, 'error', f"Build failed for {package.name}: No spec file")
                log_package(package_id, 'error', "No spec file found")
                logger.error(f"No spec file for package {package_id}")
                return

            spec_revision = _ensure_spec_source0_macro(package, spec_revision, reason='build-start')
            
            # Prepare build directory
            build_dir = Path(settings.REQPM['BUILD_DIR']) / 'package_builds' / str(package_id)
            build_dir.mkdir(parents=True, exist_ok=True)

            # Delete any stale log files from a previous build so the live consumer
            # doesn't re-stream old content on this fresh build.
            _delete_build_log_files(build_dir)

            spec_file = build_dir / f"{package.name}.spec"
            
            # Copy sources from project source directory to build directory
            # NOTE: skip .spec files — the authoritative spec comes from SpecFileRevision,
            # and any stale .spec in the sources dir must not overwrite it.
            sources_dir = Path(settings.REQPM['BUILD_DIR']) / 'sources' / package.name
            
            if not sources_dir.exists():
                logger.warning(f"Sources not found for {package.name} at {sources_dir}; creating and fetching")
                log_package(package_id, 'warning', "Sources not found locally; fetching from spec")
                sources_dir.mkdir(parents=True, exist_ok=True)
                try:
                    temp_spec = sources_dir / f"{package.name}.spec"
                    temp_spec.write_text(spec_revision.content)
                    fetch_result = builder.fetch_sources(
                        spec_file=str(temp_spec),
                        sources_dir=str(sources_dir),
                    )
                    if not fetch_result.success:
                        package.build_status = 'failed'
                        package.build_completed_at = timezone.now()
                        package.build_error_message = (
                            f"Failed to fetch sources for missing source directory: {fetch_result.error_message}"
                        )
                        package.save()
                        send_package_update(package_id)
                        log_project(project.id, 'error', f"Build failed for {package.name}: Source fetch failed")
                        log_package(package_id, 'error', f"Source fetch failed: {fetch_result.error_message}")
                        logger.error(f"Source fetch failed for {package.name}: {fetch_result.error_message}")
                        return
                except Exception as fetch_exc:
                    package.build_status = 'failed'
                    package.build_completed_at = timezone.now()
                    package.build_error_message = f"Failed to fetch sources for missing source directory: {fetch_exc}"
                    package.save()
                    send_package_update(package_id)
                    log_project(project.id, 'error', f"Build failed for {package.name}: Source fetch raised exception")
                    log_package(package_id, 'error', f"Source fetch exception: {fetch_exc}")
                    logger.error(f"Source fetch exception for {package.name}: {fetch_exc}")
                    return
            
            # Copy all source files to build directory (excluding .spec files).
            # Then ensure SourceN filenames expected by the spec are present as aliases.
            # This avoids failures where fetched source filenames (often normalized by PyPI)
            # differ from the tarball name referenced by Source0 in the spec.
            logger.info(f"Copying sources for {package.name} from {sources_dir} to {build_dir}")
            import re
            try:
                archive_suffixes = ('.tar.gz', '.tar.bz2', '.tar.xz', '.zip', '.tgz', '.whl')

                def _copy_sources_and_create_aliases() -> list[Path]:
                    copied = []
                    for source_file in sources_dir.glob('*'):
                        if source_file.is_file() and source_file.suffix != '.spec':
                            dest_path = build_dir / source_file.name
                            shutil.copy2(source_file, dest_path)
                            copied.append(dest_path)
                            logger.debug(f"Copied {source_file.name}")

                    # Derive expected SourceN filenames from spec content.
                    expected_source_names = []
                    for line in spec_revision.content.splitlines():
                        m = re.match(r'^Source\d*:\s*(.+)$', line.strip())
                        if not m:
                            continue
                        source_expr = m.group(1).strip()

                        # Handle %{pypi_source pkg-name}
                        pypi_m = re.search(r'%\{pypi_source\s+([^}\s]+)\}', source_expr)
                        if pypi_m:
                            pypi_name = pypi_m.group(1).strip()
                            expected_source_names.append(f"{pypi_name}-{package.version}.tar.gz")
                            continue

                        # Ignore unsupported macros we cannot expand reliably.
                        if source_expr.startswith('%{'):
                            continue

                        # Plain path or URL basename.
                        source_token = source_expr.split()[0]
                        source_token = source_token.split('?', 1)[0].split('#', 1)[0]
                        expected_source_names.append(Path(source_token).name)

                    # Ensure expected source filenames exist by creating aliases when needed.
                    if expected_source_names:
                        tar_candidates = [p for p in copied if p.name.endswith(archive_suffixes)]
                        for expected in dict.fromkeys(expected_source_names):
                            expected_path = build_dir / expected
                            if expected_path.exists():
                                continue

                            # Only alias archives whose filename contains the current package
                            # version.  Using a wrong-version archive as an alias would create
                            # a mismatched tarball (e.g. docutils-0.22.4 aliased as
                            # docutils-0.23.tar.gz) causing %setup to fail because the
                            # extracted directory name won't match what the spec expects.
                            preferred = [p for p in tar_candidates if package.version in p.name]
                            candidate = preferred[0] if preferred else None
                            if candidate:
                                shutil.copy2(candidate, expected_path)
                                logger.info(f"Created source alias: {candidate.name} -> {expected}")
                                log_package(package_id, 'debug', f"Created source alias: {candidate.name} -> {expected}")
                                copied.append(expected_path)

                    return copied, list(dict.fromkeys(expected_source_names))

                copied_sources, expected_names = _copy_sources_and_create_aliases()
                missing_expected = [n for n in expected_names if not (build_dir / n).exists()]
                if missing_expected or not any(p.name.endswith(archive_suffixes) for p in copied_sources):
                    # Some failed packages have an existing sources directory but no
                    # source archives in it (or only stale wrong-version archives);
                    # fetch the correct version directly from SourceN spec entries.
                    reason = f"missing expected archives: {missing_expected}" if missing_expected else "no source archives found"
                    log_package(package_id, 'warning', f"Sources stale or missing ({reason}); fetching from spec")
                    temp_spec = sources_dir / f"{package.name}.spec"
                    temp_spec.write_text(spec_revision.content)
                    fetch_result = builder.fetch_sources(
                        spec_file=str(temp_spec),
                        sources_dir=str(sources_dir),
                    )
                    if not fetch_result.success:
                        raise RuntimeError(fetch_result.error_message or "Source fetch failed")

                    copied_sources, _ = _copy_sources_and_create_aliases()
                    if not any(p.name.endswith(archive_suffixes) for p in copied_sources):
                        raise RuntimeError("No source archives found after source fetch")

            except Exception as e:
                package.build_status = 'failed'
                package.build_completed_at = timezone.now()
                package.build_error_message = f"Failed to copy sources: {str(e)}"
                package.save()
                send_package_update(package_id)
                log_project(project.id, 'error', f"Build failed for {package.name}: Failed to copy sources")
                log_package(package_id, 'error', f"Failed to copy sources: {str(e)}")
                logger.error(f"Failed to copy sources for {package.name}: {e}")
                return
            
            # Write spec file AFTER copying sources so it is never overwritten by a
            # stale .spec that may exist in the sources directory.
            spec_file.write_text(spec_revision.content)
            logger.info(f"Wrote spec file: {spec_file} (revision {spec_revision.id})")
            
            # Auto-derive mock config from RHEL version
            target = f"rhel-{rhel_version}-x86_64"
            
            logger.info(f"Building {package.name} with Mock config: {target}")
            
            # Validate target
            if not builder.validate_target(target):
                package.build_status = 'failed'
                package.build_completed_at = timezone.now()
                package.build_error_message = f"Invalid build target: {target}"
                package.save()
                send_package_update(package_id)
                log_project(project.id, 'error', f"Build failed for {package.name}: Invalid target {target}")
                log_package(package_id, 'error', f"Invalid build target: {target}")
                logger.error(f"Invalid target {target} for package {package_id}")
                return
            
            # Build SRPM first
            logger.info(f"Building SRPM for {package.name}")
            log_package(package_id, 'info', "Building SRPM...")
            
            srpm_result = builder.build_srpm(
                spec_file=str(spec_file),
                sources_dir=str(build_dir),
                output_dir=str(build_dir / 'SRPMS'),
                target=target
            )
            
            if not srpm_result.success:
                # Check if this is a directory mismatch error that can be auto-fixed
                if _detect_and_fix_directory_mismatch(package_id, srpm_result.log_output or ''):
                    # Spec file was regenerated, retry the build
                    logger.info(f"Retrying build for {package.name} after fixing directory mismatch")
                    log_package(package_id, 'info', 'Retrying build with regenerated spec file...')
                    
                    # Clear build log and old disk log files before retry
                    package.build_log = ''
                    package.save()
                    _delete_build_log_files(build_dir)
                    
                    # Re-fetch the package and spec
                    package.refresh_from_db()
                    spec_revision = SpecFileRevision.objects.filter(
                        package=package
                    ).order_by('-created_at').first()
                    
                    if spec_revision:
                        spec_revision = _ensure_spec_source0_macro(package, spec_revision, reason='build-retry-srpm')
                        # Write the new spec file
                        spec_file = build_dir / f"{package.name}.spec"
                        spec_file.write_text(spec_revision.content)
                        logger.info(f"Updated spec file for {package.name}")
                        
                        # Retry SRPM build with new spec
                        logger.info(f"Retrying SRPM build for {package.name}")
                        log_package(package_id, 'info', "Rebuilding SRPM with fixed spec...")
                        
                        srpm_result = builder.build_srpm(
                            spec_file=str(spec_file),
                            sources_dir=str(build_dir),
                            output_dir=str(build_dir / 'SRPMS'),
                            target=target
                        )
                        
                        # If it still fails after retry, fall through to normal error handling
                        if not srpm_result.success:
                            logger.warning(f"SRPM build still failed after directory mismatch fix for {package.name}")
                
                # If still failing (or wasn't a directory mismatch), handle as normal error
                if not srpm_result.success:
                    package.build_completed_at = timezone.now()
                    package.build_error_message = f"SRPM build failed: {srpm_result.error_message}"
                    package.build_log = srpm_result.log_output
                    package.build_root_log = srpm_result.root_log_output
                    # Analyze build log for structured errors (combine build.log + root.log)
                    try:
                        analyzer = BuildErrorAnalyzer()
                        combined_log = (srpm_result.log_output or '') + '\n' + (srpm_result.root_log_output or '')
                        errors = analyzer.analyze(combined_log)
                        package.analyzed_errors = [
                            {'category': e.category, 'message': e.message, 'suggestion': e.suggestion, 'items': e.items}
                            for e in errors
                        ]
                    except Exception as analyze_err:
                        logger.warning(f"Error analyzing build log for {package.name}: {analyze_err}")
                        package.analyzed_errors = []
                    # Use specific status if missing packages were detected
                    missing_cats = {'Missing Packages', 'Missing Dependencies', 'Missing Python Modules', 'Missing Header Files', 'Missing Rust/Cargo', 'Missing Python Wheel', 'Missing GCC'}
                    if any(e.get('category') in missing_cats for e in package.analyzed_errors):
                        package.build_status = _resolve_missing_dep_status(package, project)
                        # Auto-add missing dependencies to transitive dependency list
                        try:
                            auto_add_missing_dependencies(package_id)
                        except Exception as auto_add_err:
                            logger.warning(f"Error auto-adding dependencies for {package.name}: {auto_add_err}")
                    else:
                        package.build_status = 'failed'
                    package.save()
                    send_package_update(package_id)
                    log_project(project.id, 'error', f"Build failed for {package.name}: SRPM build failed")
                    log_package(package_id, 'error', f"SRPM build failed: {srpm_result.error_message}")
                    logger.error(f"SRPM build failed for {package.name}: {srpm_result.error_message}")
                    return
            
            # Build RPM
            logger.info(f"Building RPM for {package.name}")
            log_package(package_id, 'info', "Building RPM...")

            # Ensure all already-built packages in this project are available
            # as build dependencies by pointing mock at the project-local repo.
            try:
                local_repo_dir = _update_project_local_repo(project.id, [], rhel_version=rhel_version)
            except Exception as e:
                logger.warning(f"Could not prepare project local repo for {package.name}: {e}")
                local_repo_dir = None

            if local_repo_dir and Path(local_repo_dir).exists():
                package.build_dependency_repo_url = f"file://{Path(local_repo_dir).resolve()}"
            else:
                package.build_dependency_repo_url = ''
            package.save(update_fields=['build_dependency_repo_url'])
            send_package_update(package_id)

            arch = 'x86_64'
            rpm_result = builder.build_rpm(
                srpm_path=srpm_result.srpm_path,
                output_dir=str(build_dir / 'RPMS'),
                target=target,
                arch=arch,
                unique_ext=f"pkg{package_id}",
                local_repo_dir=local_repo_dir,
                project_id=project.id,
            )
            
            # Fixer loop — keep applying rule-based and AI fixes until the build
            # succeeds, no fixer applies, or SRPM reconstruction fails.
            # _ai_fix_count tracks AI attempts this rebuild; AI's own max_attempts
            # setting caps how many AI revisions are created per build run.
            _ai_fix_count = 0
            _fix_attempt = 0
            _MAX_FIX_ATTEMPTS = 10  # safety cap
            while not rpm_result.success and _fix_attempt < _MAX_FIX_ATTEMPTS:
                if not _has_fixable_build_signals(rpm_result.log_output or '', rpm_result.root_log_output or ''):
                    logger.warning(
                        f"Skipping auto-fix loop for {package.name}: logs do not contain fixable failure signals"
                    )
                    break

                fixed = False
                if _detect_and_fix_directory_mismatch(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_missing_build_files(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_unpackaged_files(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_missing_files_section_paths(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_invalid_buildrequires(
                    package_id,
                    (rpm_result.log_output or '') + '\n' + (rpm_result.root_log_output or ''),
                ):
                    fixed = True
                elif _detect_and_fix_missing_distinfo_glob(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_wrong_module_glob(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_missing_header_files(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_noarch_sitearch_mismatch(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_pyproject_save_files_auto(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_sitearch_files_entry(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_duplicate_files_and_empty_debugsource(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_spec_errors(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_self_buildrequires(package_id, rpm_result.log_output or '',
                                                        rpm_result.root_log_output or ''):
                    fixed = True
                elif _detect_and_fix_bad_setuptools_requires(package_id, rpm_result.log_output or '',
                                                             rpm_result.root_log_output or ''):
                    fixed = True
                elif _detect_and_fix_no_pip_in_chroot(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_pyproject_buildrequires_no_runtime(
                    package_id,
                    (rpm_result.log_output or '') + '\n' + (rpm_result.root_log_output or ''),
                ):
                    fixed = True
                elif _detect_and_fix_extras_in_buildrequires(
                    package_id,
                    (rpm_result.log_output or '') + '\n' + (rpm_result.root_log_output or ''),
                    rpm_result.root_log_output or '',
                ):
                    fixed = True
                elif _detect_and_fix_vcs_version_failure(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_platformdirs_version_tuple(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_rustc_version_mismatch(
                    package_id,
                    (rpm_result.log_output or '') + '\n' + (rpm_result.root_log_output or ''),
                ):
                    fixed = True
                elif _detect_and_fix_missing_cc_linker(package_id, rpm_result.log_output or ''):
                    fixed = True
                # Last resort: AI-assisted fix (only if enabled in settings)
                elif _detect_and_fix_with_ai(package_id, rpm_result.log_output or '',
                                             rpm_result.root_log_output or '', _ai_fix_count):
                    fixed = True
                    _ai_fix_count += 1

                if not fixed:
                    break

                _fix_attempt += 1
                logger.info(f"Retrying build for {package.name} after auto-fix (attempt {_fix_attempt})")
                log_package(package_id, 'info', f'Retrying full build with regenerated spec file (attempt {_fix_attempt})...')

                # Clear build log and old disk log files before retry
                package.build_log = ''
                package.save()
                _delete_build_log_files(build_dir)

                # Re-fetch the package and spec
                package.refresh_from_db()
                spec_revision = SpecFileRevision.objects.filter(
                    package=package
                ).order_by('-created_at').first()

                if not spec_revision:
                    break

                spec_revision = _ensure_spec_source0_macro(package, spec_revision, reason='build-retry-loop')

                # Write the new spec file
                spec_file = build_dir / f"{package.name}.spec"
                spec_file.write_text(spec_revision.content)
                logger.info(f"Updated spec file for {package.name}")

                if 'BUILD_SUBDIR' in spec_revision.content:
                    logger.info(f"✓ Spec has BUILD_SUBDIR subdirectory search logic")
                    log_package(package_id, 'info', 'Using spec with subdirectory search logic')
                else:
                    logger.warning(f"✗ Spec does NOT have BUILD_SUBDIR logic!")
                    log_package(package_id, 'warning', 'Spec missing subdirectory search logic')

                logger.info(f"Rebuilding SRPM for {package.name} from {spec_file}")
                log_package(package_id, 'info', "Rebuilding SRPM with fixed spec...")
                srpm_result = builder.build_srpm(
                    spec_file=str(spec_file),
                    sources_dir=str(build_dir),
                    output_dir=str(build_dir / 'SRPMS'),
                    target=target
                )

                if not srpm_result.success:
                    logger.warning(f"SRPM rebuild failed after auto-fix for {package.name}")
                    rpm_result.success = False
                    break

                logger.info(f"Rebuilding RPM for {package.name}")
                log_package(package_id, 'info', "Rebuilding RPM...")
                rpm_result = builder.build_rpm(
                    srpm_path=srpm_result.srpm_path,
                    output_dir=str(build_dir / 'RPMS'),
                    target=target,
                    arch=arch,
                    unique_ext=f"pkg{package_id}",
                    local_repo_dir=local_repo_dir,
                    project_id=project.id,
                )
                if not rpm_result.success:
                    logger.warning(f"RPM build still failed after auto-fix attempt {_fix_attempt} for {package.name}")

            # If still failing after all fix attempts, handle as normal error
            if not rpm_result.success:
                package.build_completed_at = timezone.now()
                package.build_error_message = f"RPM build failed: {rpm_result.error_message}"
                package.build_log = rpm_result.log_output
                package.build_root_log = rpm_result.root_log_output
                # Analyze build log for structured errors (combine build.log + root.log)
                try:
                    analyzer = BuildErrorAnalyzer()
                    combined_log = (rpm_result.log_output or '') + '\n' + (rpm_result.root_log_output or '')
                    errors = analyzer.analyze(combined_log)
                    package.analyzed_errors = [
                        {'category': e.category, 'message': e.message, 'suggestion': e.suggestion, 'items': e.items}
                        for e in errors
                    ]
                except Exception as analyze_err:
                    logger.warning(f"Error analyzing build log for {package.name}: {analyze_err}")
                    package.analyzed_errors = []
                # Use specific status if missing packages were detected
                missing_cats = {'Missing Packages', 'Missing Dependencies', 'Missing Python Modules', 'Missing Header Files', 'Missing Rust/Cargo', 'Missing Python Wheel', 'Missing GCC'}
                if any(e.get('category') in missing_cats for e in package.analyzed_errors):
                    package.build_status = _resolve_missing_dep_status(package, project)
                    # Auto-add missing dependencies to transitive dependency list
                    try:
                        auto_add_missing_dependencies(package_id)
                    except Exception as auto_add_err:
                        logger.warning(f"Error auto-adding dependencies for {package.name}: {auto_add_err}")
                else:
                    package.build_status = 'failed'
                package.save()
                send_package_update(package_id)
                log_project(project.id, 'error', f"Build failed for {package.name}: RPM build failed")
                log_package(package_id, 'error', f"RPM build failed: {rpm_result.error_message}")
                logger.error(f"RPM build failed for {package.name}: {rpm_result.error_message}")
                return
            
            # Update package with success
            # Prefer the main package RPM over debug/debugsource/debuginfo as
            # rpm_path — this is the path used for local-repo hydration.
            def _pick_main_rpm(paths):
                """Return the first non-debug, non-src RPM; fall back to paths[0]."""
                from pathlib import Path as _Path
                main = [p for p in paths
                        if not any(x in _Path(p).name
                                   for x in ('debuginfo', 'debugsource', 'debug-'))]
                return (sorted(main) or sorted(paths) or [None])[0]

            rpm_file = _pick_main_rpm(rpm_result.rpm_paths) if rpm_result.rpm_paths else None
            package.build_status = 'completed'
            package.build_completed_at = timezone.now()
            package.build_log = rpm_result.log_output
            package.srpm_path = srpm_result.srpm_path
            package.rpm_path = rpm_file
            # Analyze build log for warnings/issues even on success
            try:
                analyzer = BuildErrorAnalyzer()
                errors = analyzer.analyze(rpm_result.log_output or '')
                package.analyzed_errors = [
                    {'category': e.category, 'message': e.message, 'suggestion': e.suggestion, 'items': e.items}
                    for e in errors
                ]
            except Exception as analyze_err:
                logger.warning(f"Error analyzing build log for {package.name}: {analyze_err}")
                package.analyzed_errors = []
            package.save()
            send_package_update(package_id)

            # Add newly built RPMs to the project-local repo so subsequent
            # builds in the same project can depend on them.
            try:
                _update_project_local_repo(project.id, rpm_result.rpm_paths or [], rhel_version=rhel_version)
                log_package(package_id, 'info', "RPMs added to project local repo")
            except Exception as e:
                logger.warning(f"Could not update project local repo after build of {package.name}: {e}")

            log_project(project.id, 'info', f"Build completed for {package.name}")
            log_package(package_id, 'info', f"Build completed successfully")
            logger.info(f"Build completed for package {package_id}: {rpm_file}")
            
            # Check if any packages waiting for this dependency can now build
            trigger_waiting_builds(package_id)
    
    except TimeoutError as e:
        # No build slot available — set to pending and retry later
        # This frees the Celery worker immediately instead of blocking
        try:
            from backend.apps.packages.models import Package
            pkg = Package.objects.get(id=package_id)
            if pkg.build_status not in ['pending', 'waiting_for_deps']:
                pkg.build_status = 'pending'
                pkg.save()
                send_package_update(package_id)
        except Exception:
            pass
        log_package(package_id, 'info', f"Waiting for available build slot...")
        logger.info(f"Build {package_id}: no slot available, retrying in 15s")
        raise self.retry(exc=e, countdown=15, max_retries=None)
    
    except Package.DoesNotExist:
        logger.error(f"Package {package_id} not found")
    except Exception as e:
        logger.exception(f"Error building package {package_id}: {e}")
        try:
            package = Package.objects.get(id=package_id)
            package.build_status = 'failed'
            package.build_completed_at = timezone.now()
            package.build_error_message = f"Unexpected error: {str(e)}"
            package.save()
            send_package_update(package_id)
            log_package(package_id, 'error', f"Build error: {str(e)}")
        except:
            pass


def _delete_build_log_files(build_dir):
    """Delete old disk log files before a retry so the consumer doesn't re-stream stale content."""
    for log_name in ('build.log', 'root.log', 'state.log'):
        for sub in ('RPMS', 'SRPMS', ''):
            log_path = (build_dir / sub / log_name) if sub else (build_dir / log_name)
            if log_path.exists():
                try:
                    log_path.unlink()
                    logger.info(f"Deleted stale log file before retry: {log_path}")
                except Exception as e:
                    logger.warning(f"Could not delete {log_path}: {e}")


def _detect_and_fix_directory_mismatch(package_id: int, build_log: str):
    """
    Detect if build failed due to directory name mismatch (cd: <dir>: No such file).
    This happens when PyPI normalizes package names (hyphens/dots to underscores) but
    spec file still expects original name.
    
    If detected, regenerates the spec file with corrected directory name and returns True.
    Returns False if not a directory mismatch error or fix failed.
    """
    import re
    import importlib
    from backend.apps.packages.models import Package, SpecFileRevision
    import backend.core.spec_generator as spec_gen_module
    
    # Force reload to pick up any code changes
    importlib.reload(spec_gen_module)
    
    logger.info(f"Checking for directory mismatch in package {package_id}")
    
    # Check if this is a directory mismatch error
    # Pattern matches: "cd: <dirname>: No such file" or "line X: cd: <dirname>: No such file"
    match = re.search(r'cd:\s+([^:]+):\s+No such file', build_log)
    if not match:
        logger.info(f"No directory mismatch detected for package {package_id}")
        return False
    
    expected_dir = match.group(1)
    logger.info(f"Detected directory mismatch for package {package_id}: expected '{expected_dir}'")
    log_package(package_id, 'info', f'Detected directory mismatch: expected {expected_dir}')
    
    try:
        package = Package.objects.get(id=package_id)
        
        # Directory mismatch detected - regenerate spec with fallback logic
        # This handles both old specs (with %autosetup) and ensures new specs have fallback
        logger.info(f"Regenerating spec file for {package.name} to fix directory mismatch...")
        log_package(package_id, 'info', 'Regenerating spec file to fix directory mismatch...')
        
        # Regenerate spec file synchronously using SpecFileGenerator
        generator = spec_gen_module.SpecFileGenerator()
        new_spec_content = generator.generate_spec(
            package_name=package.name,
            version=package.version,
            python_name=package.python_name
        )
        
        if new_spec_content:
            # Create a new spec revision
            new_revision = SpecFileRevision.objects.create(
                package=package,
                content=new_spec_content,
                commit_message='Auto-regenerated to fix directory name mismatch with fallback logic'
            )
            logger.info(f"Successfully regenerated spec file for {package.name}")
            log_package(package_id, 'info', 'Auto-regenerated spec with directory fallback logic')
            return True
        else:
            logger.warning(f"Failed to generate new spec content for {package.name}")
            return False
        
    except Exception as e:
        logger.error(f"Error in directory mismatch detection/fix for package {package_id}: {e}")
        log_package(package_id, 'error', f'Error in auto-fix: {e}')
        return False


def _detect_and_fix_missing_build_files(package_id: int, build_log: str):
    """
    Detect if build failed because pyproject.toml/setup.py weren't found in the expected location.
    This happens when build files are in a subdirectory of the extracted tarball.
    
    If detected, regenerates the spec file with subdirectory search logic and returns True.
    Returns False if not this error type or fix failed.
    """
    import re
    import importlib
    from backend.apps.packages.models import Package, SpecFileRevision
    import backend.core.spec_generator as spec_gen_module
    
    # Force reload to pick up any code changes
    importlib.reload(spec_gen_module)
    
    logger.info(f"Checking for missing build files in package {package_id}")
    
    # Check if this is a missing build files error
    # Pattern matches: "Neither pyproject.toml nor setup.py found"
    if 'Neither pyproject.toml nor setup.py found' not in build_log:
        logger.info(f"No missing build files error detected for package {package_id}")
        return False
    
    logger.info(f"Detected missing build files for package {package_id}")
    log_package(package_id, 'info', 'Detected missing build files (may be in subdirectory)')
    
    try:
        package = Package.objects.get(id=package_id)
        
        # Regenerate spec with subdirectory search logic
        logger.info(f"Regenerating spec file for {package.name} with build file search...")
        log_package(package_id, 'info', 'Regenerating spec to handle nested build files...')
        
        # Regenerate spec file synchronously using SpecFileGenerator
        generator = spec_gen_module.SpecFileGenerator()
        new_spec_content = generator.generate_spec(
            package_name=package.name,
            version=package.version,
            python_name=package.python_name
        )
        
        if new_spec_content:
            # Create a new spec revision
            new_revision = SpecFileRevision.objects.create(
                package=package,
                content=new_spec_content,
                commit_message='Auto-regenerated to handle build files in subdirectories'
            )
            logger.info(f"Successfully regenerated spec file for {package.name}")
            log_package(package_id, 'info', 'Auto-regenerated spec with subdirectory build file search')
            return True
        else:
            logger.warning(f"Failed to generate new spec content for {package.name}")
            return False
        
    except Exception as e:
        logger.error(f"Error in missing build files detection/fix for package {package_id}: {e}")
        log_package(package_id, 'error', f'Error in auto-fix: {e}')
        return False


def _detect_and_fix_unpackaged_files(package_id: int, build_log: str):
    """
    Detect if build failed because some installed files were not included in %files section.
    This commonly happens when packages install scripts to /usr/bin or other system directories.
    
    If detected, regenerates the spec file with additional files in %files section and returns True.
    Returns False if not this error type or fix failed.
    """
    import re
    import importlib
    from backend.apps.packages.models import Package, SpecFileRevision
    
    logger.info(f"Checking for unpackaged files in package {package_id}")
    
    # Check if this is an unpackaged files error (case-insensitive, handles "build.log - " prefix)
    if not re.search(r'installed \(but unpackaged\) file\(s\) found:', build_log, re.IGNORECASE):
        logger.info(f"No unpackaged files error detected for package {package_id}")
        return False
    
    logger.info(f"Detected unpackaged files error for package {package_id}")
    log_package(package_id, 'info', 'Detected unpackaged files error')
    
    # Strip "filename.log - " prefix used in merged log format (e.g. "build.log - content")
    _prefix_re = re.compile(r'^[\w.-]+\.log\s*-\s*')
    def _strip_prefix(line):
        m = _prefix_re.match(line)
        return line[m.end():] if m else line
    
    try:
        # Extract the unpackaged file paths from the log
        # Pattern: After "Installed (but unpackaged) file(s) found:", there are indented file paths
        unpackaged_files = []
        lines = build_log.split('\n')
        in_unpackaged_section = False
        
        for line in lines:
            stripped_line = _strip_prefix(line)
            if re.search(r'installed \(but unpackaged\) file\(s\) found:', stripped_line, re.IGNORECASE):
                in_unpackaged_section = True
                continue
            
            if in_unpackaged_section:
                # Unpackaged files are indented (may have "build.log -     /path" format)
                raw_stripped = stripped_line.strip()
                if raw_stripped and raw_stripped.startswith('/'):
                    unpackaged_files.append(raw_stripped)
                    logger.info(f"Found unpackaged file: {raw_stripped}")
                elif raw_stripped and not raw_stripped.startswith('/'):
                    # Any non-empty, non-path line ends the unpackaged files section
                    break
        
        if not unpackaged_files:
            logger.warning("Unpackaged files error detected but couldn't extract file paths")
            return False

        # Deduplicate while preserving order
        unpackaged_files = list(dict.fromkeys(unpackaged_files))

        logger.info(f"Found {len(unpackaged_files)} unpackaged file(s): {unpackaged_files}")
        log_package(package_id, 'info', f'Found {len(unpackaged_files)} unpackaged file(s)')
        
        package = Package.objects.get(id=package_id)
        
        # Get the current spec file
        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        
        if not current_spec:
            logger.warning(f"No spec file found for package {package_id}")
            return False
        
        # Modify the %files section to include the unpackaged files
        spec_content = current_spec.content

        # If the spec uses %pyproject_save_files +auto, all site-packages files
        # are already covered by %{pyproject_files} via the RECORD.
        # If it uses %pyproject_save_files <module_name> (not +auto), the explicit
        # module glob may not catch sibling packages installed by the same dist
        # (e.g. setuptools also installs pkg_resources and _distutils_hack).
        # In that case we extract the top-level module names from unpackaged paths
        # and add them to the %pyproject_save_files line.
        pyproject_save_line = ''
        if '%pyproject_save_files' in spec_content:
            m_ps = re.search(r'%pyproject_save_files[^\n]*', spec_content)
            if m_ps:
                pyproject_save_line = m_ps.group(0)
        uses_pyproject_save_auto = '%pyproject_save_files' in spec_content and '+auto' in pyproject_save_line
        uses_pyproject_save_named = '%pyproject_save_files' in spec_content and not uses_pyproject_save_auto

        # Already-listed module names in %pyproject_save_files (for de-dup)
        existing_save_modules = set()
        if uses_pyproject_save_named and pyproject_save_line:
            for token in pyproject_save_line.split()[1:]:   # skip the macro name itself
                existing_save_modules.add(token)

        # Convert file paths to RPM macros where applicable
        # Also collect top-level site-packages module names that are missing from save_files
        files_to_add = []
        missing_save_modules = []        # new module names to inject into %pyproject_save_files
        sitelib_pth_files = []           # loose .pth files in site-packages (not modules)
        _seen_missing_modules = set()
        unpkgd_sitelib_rels = []         # sitelib-relative paths missed by +auto (namespace pkgs)

        _sitelib_re = re.compile(r'^/usr/lib/python[^/]+/site-packages/')

        for file_path in unpackaged_files:
            if file_path.startswith('/usr/bin/'):
                script_name = file_path[len('/usr/bin/'):]
                files_to_add.append(f'%{{_bindir}}/{script_name}')

            elif _sitelib_re.match(file_path) and uses_pyproject_save_auto:
                # +auto uses the wheel RECORD to detect packages.  Namespace
                # packages (e.g. coherent/licensed/) live 2 levels deep: the
                # top-level namespace dir has no __init__.py and isn't in the
                # RECORD, so +auto misses them.  Collect for directory-level
                # processing below instead of silently skipping.
                rel = _sitelib_re.sub('', file_path)
                unpkgd_sitelib_rels.append(rel)
                logger.info(f"Queuing sitelib path missed by +auto: {file_path}")

            elif _sitelib_re.match(file_path) and uses_pyproject_save_named:
                # Named save_files — extract the top-level module/package to add
                rel = _sitelib_re.sub('', file_path)    # strip /usr/lib/pythonX.Y/site-packages/
                top = rel.split('/')[0]                  # first path component
                if top.endswith('.pth'):
                    # Loose .pth file — needs explicit %files entry
                    sitelib_pth_files.append(file_path)
                elif top not in existing_save_modules and top not in _seen_missing_modules:
                    missing_save_modules.append(top)
                    _seen_missing_modules.add(top)
                    logger.info(f"Will add module '{top}' to %pyproject_save_files for {package_id}")
                # else: already listed or already queued

            elif file_path.startswith('/usr/lib/'):
                files_to_add.append(file_path)

            elif file_path.startswith('/usr/share/'):
                rel_path = file_path[len('/usr/share/'):]
                files_to_add.append(f'%{{_datadir}}/{rel_path}')

            else:
                files_to_add.append(file_path)

        # Add explicit entries for loose .pth files to %files
        files_to_add.extend(sitelib_pth_files)

        # Process sitelib paths missed by +auto (namespace packages).
        # Group by top-level component, then find the minimal directory entry:
        # - If all files under a top-level namespace share a single 2nd-level
        #   directory (e.g. coherent/licensed/*), use that as the entry so we
        #   don't grab the entire namespace (coherent/) — that could conflict
        #   with other coherent.* packages.
        # - Otherwise fall back to the top-level directory.
        if unpkgd_sitelib_rels:
            from collections import defaultdict
            by_top: dict = defaultdict(set)
            for rel in unpkgd_sitelib_rels:
                parts = [p for p in rel.split('/') if p]
                if not parts:
                    continue
                top = parts[0]
                level2 = parts[1] if len(parts) > 1 else None
                by_top[top].add(level2)

            for top, level2_set in by_top.items():
                if top.endswith('.dist-info') or top.endswith('.pth'):
                    # dist-info and .pth files are already handled by +auto/pyproject_files
                    continue
                # Real sub-directories at level 2 (no extension, not __pycache__)
                real_dirs = {
                    p for p in level2_set
                    if p and '.' not in p and not p.startswith('__')
                }
                if len(real_dirs) == 1:
                    sub = real_dirs.pop()
                    entry = f'%{{python3_sitelib}}/{top}/{sub}/'
                else:
                    entry = f'%{{python3_sitelib}}/{top}/'
                if entry not in files_to_add:
                    files_to_add.append(entry)
                    logger.info(f"Adding namespace dir to %%files for +auto package: {entry}")

        # If named %pyproject_save_files misses some site-packages siblings,
        # add the missing module names to the %pyproject_save_files line.
        if missing_save_modules and uses_pyproject_save_named:
            logger.info(f"Adding missing modules to %pyproject_save_files: {missing_save_modules}")
            log_package(package_id, 'info',
                        f'Adding missing modules to %%pyproject_save_files: {missing_save_modules}')
            new_save_line = pyproject_save_line + ' ' + ' '.join(missing_save_modules)
            new_spec_content = spec_content.replace(pyproject_save_line, new_save_line, 1)
            # Also add any loose .pth files to %files if needed
            if sitelib_pth_files:
                pth_entries = '\n'.join(sitelib_pth_files)
                files_pattern_inner = r'(%files\s+-f\s+%\{pyproject_files\})'
                if re.search(files_pattern_inner, new_spec_content):
                    new_spec_content = re.sub(
                        files_pattern_inner,
                        f'%files -f %{{pyproject_files}}\n{pth_entries}',
                        new_spec_content,
                    )
            package = Package.objects.get(id=package_id)
            SpecFileRevision.objects.create(
                package=package,
                content=new_spec_content,
                commit_message=f'Auto-fixed: Added {missing_save_modules} to %%pyproject_save_files'
            )
            logger.info(f"Updated %%pyproject_save_files with missing modules for {package.name}")
            return True
        
        # Find and replace the %files section
        # Current: %files -f %{pyproject_files}
        # New: %files -f %{pyproject_files}\n<additional files>
        files_pattern = r'(%files\s+-f\s+%\{pyproject_files\})'

        if not files_to_add:
            logger.info(f"All unpackaged files already covered or handled for {package_id}")
            return False

        if re.search(files_pattern, spec_content):
            # Add the unpackaged files after the %files line
            additional_files = '\n'.join(files_to_add)
            new_files_section = f'%files -f %{{pyproject_files}}\n{additional_files}'
            new_spec_content = re.sub(
                files_pattern,
                new_files_section,
                spec_content
            )
            
            logger.info(f"Updated %files section with {len(files_to_add)} additional file(s)")
            log_package(package_id, 'info', f'Adding {len(files_to_add)} file(s) to %files section')
            
            # Create a new spec revision with the modified content
            new_revision = SpecFileRevision.objects.create(
                package=package,
                content=new_spec_content,
                commit_message=f'Auto-fixed: Added {len(files_to_add)} unpackaged file(s) to %files section'
            )
            logger.info(f"Successfully updated spec file for {package.name}")
            log_package(package_id, 'info', 'Auto-regenerated spec with additional files in %files section')
            return True
        else:
            logger.warning(f"Could not find %files section pattern in spec for {package.name}")
            return False
        
    except Exception as e:
        logger.error(f"Error in unpackaged files detection/fix for package {package_id}: {e}")
        log_package(package_id, 'error', f'Error in auto-fix: {e}')
        return False


def _detect_and_fix_spec_errors(package_id: int, build_log: str) -> bool:
    """
    General-purpose catch-all: run the build log through SpecFixer.apply_fixes()
    and create a new spec revision if any AUTO_FIXABLE_CATEGORIES errors are found
    and the fixer makes at least one change.

    Covers categories not handled by the more specific detectors above:
    - Invalid Pyproject License
    - Architecture Mismatch (noarch binary)
    - Ambiguous Python Shebang
    - Empty Debug Info
    - Missing GCC (gcc missing)
    - Missing G++ Compiler

    Returns True when a new spec revision was created.
    """
    from backend.apps.packages.models import Package, SpecFileRevision
    from backend.core.error_analyzer import BuildErrorAnalyzer
    from backend.core.spec_fixer import SpecFixer, AUTO_FIXABLE_CATEGORIES

    # Quick guard: at least one fixable keyword must appear in the log before
    # paying the cost of a full analysis + DB round-trip.
    _FAST_KEYWORDS = [
        'invalid pyproject.toml config',
        'arch dependent binaries in noarch',
        'ambiguous python shebang',
        'empty debuginfo',
        'empty %files file',
        "command 'gcc' failed",
        "FileNotFoundError.*'g\\+\\+'",
    ]
    if not any(kw.lower() in build_log.lower() for kw in [
        'invalid pyproject.toml config',
        'arch dependent binaries in noarch',
        'ambiguous python shebang',
        'empty debuginfo',
        "command 'gcc' failed",
        "command 'g++' failed",
        'filenotfounderror',
    ]):
        return False

    try:
        package = Package.objects.get(id=package_id)

        analyzer = BuildErrorAnalyzer()
        errors = analyzer.analyze(build_log)
        fixable = [
            {'category': e.category, 'items': e.items, 'message': e.message, 'suggestion': e.suggestion}
            for e in errors
            if e.category in AUTO_FIXABLE_CATEGORIES
            # Skip categories handled by dedicated detectors
            and e.category not in (
                'Missing Header Files',
                'Missing Packages',
                'Missing Dependencies',
                'Missing Python Modules',
                'Missing Python Wheel',
                'Unpackaged Files',
                'Wrong Module Glob',
                'Missing Setup.py',
            )
        ]
        if not fixable:
            return False

        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        fixer = SpecFixer()
        new_spec, applied = fixer.apply_fixes(current_spec.content, fixable)
        if not applied:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_spec,
            commit_message=f'Auto-fix: {"; ".join(applied)}'
        )
        log_package(package_id, 'info', f'Auto-fixed spec: {"; ".join(applied)}')
        logger.info(f'Auto-fixed spec errors for {package.name}: {applied}')
        return True

    except Exception as e:
        logger.error(f'Error in _detect_and_fix_spec_errors for {package_id}: {e}')
        return False


def _detect_and_fix_wrong_module_glob(package_id: int, build_log: str) -> bool:
    """
    Detect the 'Globs did not match any module: <name>' error from
    pyproject_save_files and fix the spec by replacing the bad glob with +auto.

    This happens for namespace packages (e.g. poetry-core installs as
    poetry/core/ not poetry_core/) where the dist-info name doesn't match
    the actual installed module directory.

    Returns True if the fix was applied, False otherwise.
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision
    from backend.core.spec_fixer import SpecFixer

    _GLOB_ERRORS = (
        'Globs did not match any module',
        'Attempted to use a namespaced package with . in the glob',
        'At least one module glob needs to be provided to %pyproject_save_files',
    )
    if not any(s in build_log for s in _GLOB_ERRORS):
        return False

    logger.info(f"Detected wrong module glob error for package {package_id}")
    log_package(package_id, 'info', 'Detected wrong %pyproject_save_files glob — will try with +auto')

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()

        if not current_spec:
            logger.warning(f"No spec file found for package {package_id}")
            return False

        fixer = SpecFixer()
        recent_specs = list(
            SpecFileRevision.objects.filter(package=package)
            .order_by('-created_at')
            .values_list('content', flat=True)[:8]
        )

        # Parse the failing module glob directly from build log lines such as:
        # "Globs did not match any module: awx_plugins_interfaces"
        matched_items = [
            m.strip()
            for m in re.findall(r'Globs did not match any module:\s*([^\n]+)', build_log)
            if m.strip()
        ]
        # Ignore templated/garbage placeholders sometimes emitted in logs.
        matched_items = [
            m for m in matched_items
            if '{' not in m and '}' not in m and '"' not in m and "'" not in m
        ]
        seen = set()
        matched_items = [i for i in matched_items if not (i in seen or seen.add(i))]

        new_spec, fixes = fixer._fix_wrong_module_glob(current_spec.content, matched_items)

        # Infer an actual module root from build output so +auto still has a
        # module glob (required by pyproject_save_files on newer RPM macros).
        module_roots = re.findall(
            r"(?:copying\s+build/lib/|adding\s+')([A-Za-z_][A-Za-z0-9_]*)(?:/|\.py)",
            build_log,
        )
        module_root = None
        if module_roots:
            # Keep first-seen order, then prefer the most frequent root.
            counts = {}
            for r in module_roots:
                counts[r] = counts.get(r, 0) + 1
            module_root = max(counts, key=counts.get)

        bad_globs = {m.lower() for m in matched_items}

        def _candidate_variants(raw: str) -> list[str]:
            raw = (raw or '').strip()
            base = re.sub(r'[-.]', '_', raw).strip()
            if not base:
                return []

            variants = [base]
            lowered = base.lower()
            if lowered != base:
                variants.append(lowered)

            stripped = re.sub(r'^python3?_', '', base, flags=re.IGNORECASE)
            if stripped and stripped != base:
                variants.append(stripped)
                stripped_lower = stripped.lower()
                if stripped_lower != stripped:
                    variants.append(stripped_lower)

            for suffix in ('_py', '_api', '_sdk', '_client', '_core'):
                if stripped.endswith(suffix):
                    shorter = stripped[:-len(suffix)]
                    if shorter:
                        variants.append(shorter)
                        shorter_lower = shorter.lower()
                        if shorter_lower != shorter:
                            variants.append(shorter_lower)

            parts = [p for p in stripped.split('_') if p]
            if len(parts) >= 2:
                variants.append('_'.join(parts[:2]))
            if len(parts) >= 1:
                variants.append(parts[0])

            # Common import-name aliases where dist/rpm naming differs from
            # import module casing or top-level package.
            alias_map = {
                'pyopenssl': 'OpenSSL',
                'openssl': 'OpenSSL',
                'poetry_core': 'poetry',
            }
            alias_key = lowered
            if alias_key in alias_map:
                variants.append(alias_map[alias_key])

            seen_local = set()
            cleaned = []
            for cand in variants:
                if not cand or cand in seen_local:
                    continue
                seen_local.add(cand)
                if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', cand):
                    continue
                if cand in ('build', 'python', 'python3'):
                    continue
                cleaned.append(cand)
            return cleaned

        if not module_root:
            # Fallback for logs that only show pyproject_save_files errors and
            # don't include module copy lines. Prefer a conservative top-level
            # module guess derived from package/dist naming.
            normalized_pkg = re.sub(r'[-.]', '_', (package.name or '')).lower()
            dotted_pkg_top = None
            if package.name and '.' in package.name:
                dotted_pkg_top = package.name.split('.', 1)[0].strip().lower()
            dist_from_specifier = None
            m = re.search(r'specifier=([A-Za-z0-9_.-]+)==', build_log)
            if m:
                dist_from_specifier = re.sub(r'[-.]', '_', m.group(1)).lower()

            raw_candidates = []
            raw_candidates.extend(matched_items)
            raw_candidates.extend([
                package.python_name or '',
                package.name or '',
                dotted_pkg_top or '',
                dist_from_specifier or '',
                normalized_pkg or '',
            ])

            expanded_candidates = []
            seen_expanded = set()
            for raw in raw_candidates:
                for cand in _candidate_variants(raw):
                    if cand in seen_expanded:
                        continue
                    seen_expanded.add(cand)
                    expanded_candidates.append(cand)

            for c in expanded_candidates:
                if c not in bad_globs:
                    module_root = c
                    break

        missing_module_glob_only = 'At least one module glob needs to be provided to %pyproject_save_files' in build_log

        # In this environment, bare +auto is rejected by pyproject_save_files.
        # Convert any +auto form to a concrete module glob when we can infer one.
        if '%pyproject_save_files +auto' in new_spec:
            fallback_candidates = []
            for raw in (
                *matched_items,
                module_root or '',
                package.python_name or '',
                package.name or '',
            ):
                fallback_candidates.extend(_candidate_variants(raw))

            forced_root = None
            for cand in fallback_candidates:
                if not cand:
                    continue
                if cand.lower() in bad_globs:
                    continue
                if re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', cand):
                    forced_root = cand
                    break

            if forced_root:
                converted_spec, n = re.subn(
                    r'^\s*%pyproject_save_files\s+\+auto(?:\s+[^\n\s]+)?\s*$',
                    f'%pyproject_save_files {forced_root}',
                    new_spec,
                    flags=re.MULTILINE,
                    count=1,
                )
                if n:
                    new_spec = converted_spec
                    if missing_module_glob_only:
                        fixes.append(f'Replaced %pyproject_save_files +auto with module glob: {forced_root}')
                    else:
                        fixes.append(f'Normalized %pyproject_save_files +auto to module glob for this build env: {forced_root}')

        # Avoid creating duplicate revisions when the final content is unchanged.
        if new_spec == current_spec.content:
            logger.info(f"Wrong module glob fixer produced no net spec changes for {package.name}")
            return False

        # Guard against a ping-pong loop where this fixer alternates between
        # two previously tried %pyproject_save_files forms.
        if new_spec in recent_specs[1:]:
            logger.warning(
                f"Wrong module glob fixer refusing to recreate a recent spec state for {package.name}"
            )
            log_package(
                package_id,
                'warning',
                'Detected %pyproject_save_files auto-fix loop; refusing to recreate a recent spec revision',
            )
            return False

        if not fixes:
            logger.warning(f"Wrong module glob detected but no spec change was required for {package.name}")
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_spec,
            commit_message=f'Auto-fixed: replaced bad %pyproject_save_files glob with +auto ({"; ".join(fixes)})'
        )
        log_package(package_id, 'info', f'Auto-fixed spec: {"; ".join(fixes)}')
        return True

    except Exception as e:
        logger.error(f"Error in wrong_module_glob fix for package {package_id}: {e}")
        return False


def _detect_and_fix_missing_files_section_paths(package_id: int, build_log: str) -> bool:
    """
    Detect RPM failures caused by literal file entries in %files that do not
    exist in the buildroot, and remove those stale entries from the spec.

    This covers cases like:
    - /usr/bin/string_utils
    - %{_bindir}/string_utils
    - .../debugsourcefiles.list accidentally emitted into %files
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision

    missing_paths = [
        m.strip()
        for m in re.findall(r'error:\s+File not found:\s+([^\n]+)', build_log, flags=re.IGNORECASE)
        if m.strip()
    ]
    if not missing_paths:
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(package=package).order_by('-created_at').first()
        if not current_spec:
            return False

        spec_lines = current_spec.content.splitlines()
        removal_targets = set()

        for path in missing_paths:
            removal_targets.add(path)
            if path.startswith('/usr/bin/'):
                removal_targets.add(f'%{{_bindir}}/{path.split("/usr/bin/", 1)[1]}')
            if 'debugsourcefiles.list' in path:
                for line in spec_lines:
                    if 'debugsourcefiles.list' in line:
                        removal_targets.add(line.strip())

        new_lines = []
        removed_lines = []
        for line in spec_lines:
            stripped = line.strip()
            if stripped in removal_targets:
                removed_lines.append(stripped)
                continue
            new_lines.append(line)

        if not removed_lines:
            return False

        new_spec = '\n'.join(new_lines).rstrip() + '\n'
        SpecFileRevision.objects.create(
            package=package,
            content=new_spec,
            commit_message='Auto-fixed: removed stale literal %files entries for missing paths',
        )
        log_package(package_id, 'info', f'Auto-fixed spec: removed stale %files entries: {removed_lines[:6]}')
        logger.info(f"Removed stale %%files entries for {package.name}: {removed_lines}")
        return True

    except Exception as e:
        logger.error(f"Error in missing_files_section_paths fix for package {package_id}: {e}")
        return False


def _detect_and_fix_invalid_buildrequires(package_id: int, build_log: str) -> bool:
    """
    Detect invalid BuildRequires entries that come from malformed dependency
    normalization, such as extras/self-deps/alias names:
    - python3dist(aiohttp[speedups]) -> python3dist(aiohttp)
    - python3dist(protobuf-devel) -> python3dist(protobuf)
    - python3dist(yaml) while building pyyaml -> remove self-dependency
    - BuildRequires: zope while building zope-interface -> remove self-dependency
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision
    from backend.core.error_analyzer import BuildErrorAnalyzer

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(package=package).order_by('-created_at').first()
        if not current_spec:
            return False

        analyzer = BuildErrorAnalyzer()
        errors = analyzer.analyze(build_log or '')
        missing_items = []
        for error in errors:
            if error.category in {'Missing Packages', 'Missing Dependencies'}:
                missing_items.extend(error.items or [])
        if not missing_items:
            return False

        content = current_spec.content
        changed = False
        applied = []

        def _replacement_for_item(item: str) -> str | None:
            import re

            bad_aliases = {
                'python3-python3dist',
                'python3dist',
                'python3-venv',
            }
            if (item or '').strip().lower() in bad_aliases:
                return ''

            # Normalize mixed-case distro python package aliases from logs,
            # e.g. python3-PyJWT -> BuildRequires: python3-pyjwt
            m = re.match(r'^python3?-([A-Za-z0-9._+\-\[\],]+)$', (item or '').strip())
            if m:
                base = re.sub(r'\[[^\]]*\]', '', m.group(1)).replace('_', '-').lower()
                if not base:
                    return None
                if base.endswith('-devel'):
                    base = base[:-6]
                    if not base:
                        return None
                if base == 'pyjwt-crypto':
                    base = 'pyjwt'
                if base == 'openssl':
                    return 'BuildRequires: openssl-devel'
                return f'BuildRequires: python3-{base}'

            normalized = _normalize_dep_names(item)
            if not normalized:
                return None
            if _is_self_dependency_item(package, item):
                return ''
            if item.lower().startswith('python3dist('):
                for cand in normalized:
                    base = cand.lower()
                    if base.startswith('python3-'):
                        base = base[8:]
                    if re.match(r'^[a-z0-9._+-]+$', base):
                        return f'BuildRequires: python3dist({base})'

            # Plain package tokens from PyPI metadata can appear without the
            # python3- prefix (e.g. "pbs-installer") and fail in builddep.
            # Normalize them to python3-* while avoiding known system packages.
            plain_item = (item or '').strip().lower()
            if re.match(r'^[a-z0-9][a-z0-9._+-]*$', plain_item) and not plain_item.startswith(('python3-', 'python-')):
                system_like = {
                    'gcc', 'gcc-c++', 'g++', 'cargo', 'rust', 'rustc', 'rust-toolset',
                    'openssl-devel', 'python-devel', 'pyproject-rpm-macros', 'cmake', 'make',
                }
                if plain_item not in system_like:
                    base = normalized[0].lower()
                    if base.startswith('python3-'):
                        base = base[8:]
                    elif base.startswith('python-'):
                        base = base[7:]
                    if re.match(r'^[a-z0-9._+-]+$', base):
                        return f'BuildRequires: python3-{base}'
            return None

        for item in missing_items:
            item = (item or '').strip()
            if not item:
                continue

            replacement = _replacement_for_item(item)
            if replacement is None:
                continue

            line_pattern = re.compile(
                r'^\s*BuildRequires:\s*' + re.escape(item) + r'\s*$\n?',
                flags=re.MULTILINE | re.IGNORECASE,
            )
            if not re.search(line_pattern, content):
                # Also handle plain-name BuildRequires lines like "BuildRequires: zope"
                bare_item = re.sub(r'^python3dist\(([^)]+)\).*$', r'\1', item, flags=re.IGNORECASE)
                line_pattern = re.compile(
                    r'^\s*BuildRequires:\s*' + re.escape(bare_item) + r'\s*$\n?',
                    flags=re.MULTILINE | re.IGNORECASE,
                )
                if not re.search(line_pattern, content):
                    continue

            if replacement == '':
                content = re.sub(line_pattern, '', content)
                applied.append(f'Removed invalid self BuildRequires: {item}')
                changed = True
                continue

            if replacement in content:
                content = re.sub(line_pattern, '', content)
                applied.append(f'Removed duplicate invalid BuildRequires: {item}')
                changed = True
                continue

            content, count = re.subn(line_pattern, replacement + '\n', content, count=1)
            if count:
                applied.append(f'Replaced invalid BuildRequires: {item} -> {replacement}')
                changed = True

        if not changed or content == current_spec.content:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=content,
            commit_message='Auto-fixed: normalized invalid BuildRequires aliases/self-dependencies',
        )
        log_package(package_id, 'info', f'Auto-fixed spec: {'; '.join(applied)}')
        logger.info(f"Normalized invalid BuildRequires for {package.name}: {applied}")
        return True

    except Exception as e:
        logger.error(f"Error in invalid_buildrequires fix for package {package_id}: {e}")
        return False


def _detect_and_fix_missing_distinfo_glob(package_id: int, build_log: str) -> bool:
    """
    Detect failures where the pyproject_save_files helper script attempts to
    touch a non-expanded *.dist-info/INSTALLER path and switch to +auto.
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision

    if '*.dist-info/INSTALLER' not in (build_log or ''):
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(package=package).order_by('-created_at').first()
        if not current_spec:
            return False

        new_spec, count = re.subn(
            r'^%pyproject_save_files\s+(?!\+auto)([^\n]+)$',
            '%pyproject_save_files +auto',
            current_spec.content,
            flags=re.MULTILINE,
            count=1,
        )
        if not count or new_spec == current_spec.content:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_spec,
            commit_message='Auto-fixed: switched %pyproject_save_files to +auto after missing dist-info glob failure',
        )
        log_package(package_id, 'info', 'Auto-fixed spec: switched %pyproject_save_files to +auto')
        return True

    except Exception as e:
        logger.error(f"Error in missing_distinfo_glob fix for package {package_id}: {e}")
        return False


def _lookup_devel_package_via_mock(target: str, item: str) -> str | None:
    """
    Query the mock chroot's dnf to find which RPM package provides a header
    file or pkg-config library.  Uses the shared bootstrap chroot with
    --no-clean so no fresh chroot initialisation is required.

    item may be a bare header filename ('ffi.h') or a pkg-config name ('libffi').
    Returns the provider package name, or None if the lookup fails / times out.
    """
    import shutil as _shutil
    import subprocess as _subprocess

    mock_bin = _shutil.which('mock') or '/usr/bin/mock'
    if not os.path.exists(mock_bin):
        return None

    # Build the dnf whatprovides expression
    if item.endswith('.h'):
        query = f'*/{item}'
    else:
        # pkg-config provides — RPM dependency syntax
        query = f'pkgconfig({item})'

    if os.geteuid() != 0:
        cmd = ['sudo', '-n', mock_bin]
    else:
        cmd = [mock_bin]
    cmd += [
        '-r', target, '--no-clean', '--shell',
        f'dnf repoquery --whatprovides "{query}" --qf "%{{name}}" 2>/dev/null'
        f' | grep -v "^$" | head -1'
    ]

    try:
        env = os.environ.copy()
        env.update({'LANG': 'en_US.UTF-8', 'LC_ALL': 'en_US.UTF-8'})
        result = _subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
        if result.returncode == 0 and result.stdout.strip():
            # Filter out mock INFO/WARNING lines
            lines = [
                l.strip() for l in result.stdout.split('\n')
                if l.strip() and not l.startswith('INFO') and not l.startswith('WARNING')
            ]
            if lines:
                pkg = lines[0]
                # Sanity-check: must look like an RPM package name
                if re.match(r'^[a-zA-Z][a-zA-Z0-9._+-]+$', pkg):
                    return pkg
    except Exception as e:
        logger.debug(f"mock dnf lookup for {item!r} failed: {e}")
    return None


def _detect_and_fix_missing_header_files(package_id: int, build_log: str) -> bool:
    """
    Detect 'Missing Header Files' errors (missing headers or pkg-config libraries)
    and add the corresponding -devel packages as BuildRequires in the spec.

    Uses a static HEADER_TO_DEVEL map for the most common libraries; falls back
    to a dnf repoquery lookup inside the mock chroot for unknown items.

    Returns True when a new spec revision was created (triggers a rebuild).
    """
    from backend.apps.packages.models import Package, SpecFileRevision
    from backend.core.error_analyzer import BuildErrorAnalyzer
    from backend.core.spec_fixer import SpecFixer, HEADER_TO_DEVEL

    try:
        package = Package.objects.get(id=package_id)

        analyzer = BuildErrorAnalyzer()
        errors = analyzer.analyze(build_log)
        header_errors = [e for e in errors if e.category == 'Missing Header Files']
        if not header_errors:
            return False

        all_items = []
        for e in header_errors:
            all_items.extend(e.items)
        if not all_items:
            return False

        # De-duplicate while preserving order
        seen_items: set = set()
        unique_items = [i for i in all_items if not (i in seen_items or seen_items.add(i))]

        packages_to_add = []
        unknown = []
        for item in unique_items:
            pkg = HEADER_TO_DEVEL.get(item)
            if pkg:
                packages_to_add.append(pkg)
            else:
                unknown.append(item)

        # For items not in the static map, try a live mock lookup
        if unknown:
            target = f"rhel-{package.project.rhel_version}-x86_64"
            for item in unknown:
                pkg = _lookup_devel_package_via_mock(target, item)
                if pkg:
                    logger.info(f"mock dnf resolved {item!r} \u2192 {pkg!r} for {package.name}")
                    packages_to_add.append(pkg)
                else:
                    logger.debug(f"No devel package found for header/pc: {item!r}")

        if not packages_to_add:
            logger.info(f"No devel packages mapped for {package.name}'s missing headers: {unique_items}")
            return False

        # De-duplicate
        seen_pkgs: set = set()
        packages_to_add = [p for p in packages_to_add if not (p in seen_pkgs or seen_pkgs.add(p))]

        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        fixer = SpecFixer()
        new_spec, applied = fixer._add_buildrequires_items(current_spec.content, packages_to_add)
        if not applied:
            logger.info(f"All devel packages already present in spec for {package.name}")
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_spec,
            commit_message=f'Auto-fix: add missing devel packages ({"; ".join(applied)})'
        )
        log_package(package_id, 'info', f'Auto-fixed spec: {"; ".join(applied)}')
        logger.info(f"Fixed missing devel packages for {package.name}: {applied}")
        return True

    except Exception as e:
        logger.error(f"Error in _detect_and_fix_missing_header_files for {package_id}: {e}")
        return False


def _detect_and_fix_self_buildrequires(package_id: int, build_log: str, root_log: str = '') -> bool:
    """
    Detect when a package lists itself as a BuildRequires (self-dependency).
    This happens when PyPI metadata incorrectly includes the package as its own
    runtime/build dependency and pyp2spec blindly copies it into the spec.
    Removes the offending BuildRequires line and saves a new spec revision.
    Returns True when a fix was applied.
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision

    combined = (build_log or '') + '\n' + (root_log or '')
    matches = re.findall(
        r"No matching package to install: ['\"]?python3?dist\(([^)]+)\)['\"]?",
        combined,
        re.IGNORECASE,
    )
    if not matches:
        return False

    try:
        package = Package.objects.get(id=package_id)

        def _norm(name: str) -> str:
            return re.sub(r'[-.]', '_', name).lower()

        pkg_norm = _norm(package.name)
        # Strip common RPM prefix so python3-awx-foo and awx_foo both match
        pkg_dist = re.sub(r'^python3?_', '', pkg_norm)

        self_refs = [
            m for m in matches
            if _norm(m) in (pkg_dist, pkg_norm)
        ]
        if not self_refs:
            return False

        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        new_spec = current_spec.content
        for ref in self_refs:
            new_spec = re.sub(
                rf'^BuildRequires:\s+python3?dist\({re.escape(ref)}\)[^\n]*\n',
                '',
                new_spec,
                flags=re.MULTILINE | re.IGNORECASE,
            )

        if new_spec == current_spec.content:
            logger.info(f'Self-dep BuildRequires not found in spec for {package.name}')
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_spec,
            commit_message=f'Auto-fix: removed self-referential BuildRequires ({", ".join(self_refs)})',
        )
        log_package(package_id, 'info',
                    f'Auto-fixed: removed self-referential BuildRequires ({", ".join(self_refs)})')
        logger.info(f'Fixed self-referential BuildRequires for {package.name}: {self_refs}')
        return True

    except Exception as e:
        logger.error(f'Error in _detect_and_fix_self_buildrequires for {package_id}: {e}')
        return False


def _detect_and_fix_bad_setuptools_requires(package_id: int, build_log: str, root_log: str = '') -> bool:
    """
    Fix malformed setuptools-related BuildRequires lines such as:
      - BuildRequires: python3dist(setuptools-devel)
      - BuildRequires: setuptools (when python3dist(setuptools) already exists)
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision

    combined = (build_log or '') + '\n' + (root_log or '')
    if not re.search(r"python3dist\(setuptools-devel\)|No matching package to install: ['\"]?setuptools['\"]?", combined, re.I):
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(package=package).order_by('-created_at').first()
        if not current_spec:
            return False

        new_spec = current_spec.content
        fixes = []

        patched = re.sub(
            r'^\s*BuildRequires:\s+python3dist\(setuptools-devel\)[^\n]*\s*$\n?',
            '',
            new_spec,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        if patched != new_spec:
            new_spec = patched
            fixes.append('Removed invalid BuildRequires: python3dist(setuptools-devel)')

        if 'BuildRequires: python3dist(setuptools)' in new_spec:
            patched = re.sub(
                r'^\s*BuildRequires:\s+setuptools\b[^\n]*\s*$\n?',
                '',
                new_spec,
                flags=re.MULTILINE | re.IGNORECASE,
            )
            if patched != new_spec:
                new_spec = patched
                fixes.append('Removed redundant BuildRequires: setuptools')

        if new_spec == current_spec.content or not fixes:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_spec,
            commit_message=f"Auto-fixed setuptools requirements ({'; '.join(fixes)})",
        )
        log_package(package_id, 'info', f"Auto-fixed spec: {'; '.join(fixes)}")
        logger.info(f"Fixed setuptools BuildRequires for {package.name}: {fixes}")
        return True

    except Exception as e:
        logger.error(f"Error in _detect_and_fix_bad_setuptools_requires for {package_id}: {e}")
        return False


def _detect_and_fix_no_pip_in_chroot(package_id: int, build_log: str) -> bool:
    """
    When %pyproject_wheel fails with 'No module named pip' or 'No module named
    wheel', the chroot is missing pip/wheel because %generate_buildrequires was
    not present in the spec.  Fix: add the section so mock installs the tools.
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision

    combined = build_log or ''
    if 'No module named pip' not in combined and 'No module named wheel' not in combined:
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        content = current_spec.content

        if '%pyproject_buildrequires' in content:
            # Already present — different underlying problem, don't loop.
            return False

        if '%generate_buildrequires' in content:
            new_content = re.sub(
                r'^(%generate_buildrequires\b)',
                r'\1\n%pyproject_buildrequires',
                content,
                flags=re.MULTILINE,
                count=1,
            )
        else:
            new_content = re.sub(
                r'^(%build\b)',
                r'%generate_buildrequires\n%pyproject_buildrequires\n\n\1',
                content,
                flags=re.MULTILINE,
                count=1,
            )

        if new_content == content:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_content,
            commit_message='Auto-fix: add %generate_buildrequires so pip/wheel are installed in chroot',
        )
        log_package(package_id, 'info', 'Auto-fixed: added %generate_buildrequires %pyproject_buildrequires')
        logger.info(f'Fixed missing %generate_buildrequires for {package.name}')
        return True

    except Exception as e:
        logger.error(f'Error in _detect_and_fix_no_pip_in_chroot for {package_id}: {e}')
        return False


def _detect_and_fix_pyproject_buildrequires_no_runtime(package_id: int, build_log: str) -> bool:
    """
    Some backends cannot provide runtime metadata during %generate_buildrequires,
    causing failures like:
      "The build backend cannot provide build metadata ... use -R flag ..."

    Fix: ensure %pyproject_buildrequires includes -R.
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision

    combined = build_log or ''
    if 'build backend cannot provide build metadata' not in combined:
        return False
    if '%generate_buildrequires' not in combined and '%pyproject_buildrequires' not in combined:
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        content = current_spec.content
        lines = content.splitlines()
        changed = False

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith('%pyproject_buildrequires'):
                continue
            if re.search(r'(^|\s)-R(\s|$)', line):
                continue
            lines[i] = f"{line.rstrip()} -R"
            changed = True

        new_content = '\n'.join(lines)
        if content.endswith('\n'):
            new_content += '\n'

        if not changed and '%generate_buildrequires' in content and '%pyproject_buildrequires' not in content:
            new_content = re.sub(
                r'^(%generate_buildrequires\b)',
                r'\1\n%pyproject_buildrequires -R',
                content,
                flags=re.MULTILINE,
                count=1,
            )
            changed = (new_content != content)

        if not changed:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_content,
            commit_message='Auto-fix: add -R to %pyproject_buildrequires for pre-build metadata backend failure',
        )
        log_package(package_id, 'info', 'Auto-fixed: added -R to %pyproject_buildrequires')
        logger.info(f'Fixed pyproject buildrequires runtime metadata failure for {package.name}')
        return True

    except Exception as e:
        logger.error(f'Error in _detect_and_fix_pyproject_buildrequires_no_runtime for {package_id}: {e}')
        return False


def _detect_and_fix_extras_in_buildrequires(package_id: int, build_log: str, root_log: str = '') -> bool:
    """
    Fix BuildRequires entries that use PEP 508 extras bracket notation, which
    RPM does not support (e.g. python3-pyjwt[crypto] or python3dist(twisted[tls])).
        Triggers when mock reports a missing package whose name contains brackets,
        including solver messages like:
            "nothing provides requested (python3dist(pyjwt[crypto]) < 3~~ with ...)"
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision

    combined = (build_log or '') + '\n' + (root_log or '')
    if not re.search(r'\[[a-zA-Z0-9_,\s]+\]', combined):
        return False
    if not re.search(
        r"(?:No matching package to install|cannot install|Failed to install|nothing provides requested|Problem:\s*nothing provides)[^\\n]*\[[a-zA-Z0-9_,]+\]",
        combined,
        re.IGNORECASE,
    ):
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        content = current_spec.content
        # Strip bracket extras from every BuildRequires line:
        #   python3-pyjwt[crypto]          → python3-pyjwt
        #   python3dist(twisted[tls])      → python3dist(twisted)
        new_content, count = re.subn(
            r'^(BuildRequires:[^\[#\n]+?)\[[^\]]+\](\)?)',
            r'\1\2',
            content,
            flags=re.MULTILINE,
        )

        # If the extras requirement is being generated dynamically by
        # %pyproject_buildrequires (not present as a static BuildRequires line),
        # switch to -R so runtime extras are not pulled into builddep solving.
        if (not count or new_content == content) and '%pyproject_buildrequires' in content:
            lines = content.splitlines()
            changed_runtime = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped.startswith('%pyproject_buildrequires'):
                    continue
                if re.search(r'(^|\s)-R(\s|$)', line):
                    continue
                lines[i] = f"{line.rstrip()} -R"
                changed_runtime = True

            if changed_runtime:
                new_content = '\n'.join(lines)
                if content.endswith('\n'):
                    new_content += '\n'
                SpecFileRevision.objects.create(
                    package=package,
                    content=new_content,
                    commit_message='Auto-fix: set %pyproject_buildrequires -R for extras-only python3dist solver failure',
                )
                log_package(package_id, 'info', 'Auto-fixed: set %pyproject_buildrequires -R to avoid extras-only solver requirements')
                logger.info(f'Set %pyproject_buildrequires -R for extras solver failure in {package.name}')
                return True

        if not count or new_content == content:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_content,
            commit_message=f'Auto-fix: stripped extras brackets from {count} BuildRequires line(s)',
        )
        log_package(package_id, 'info',
                    f'Auto-fixed: stripped bracket extras from {count} BuildRequires line(s)')
        logger.info(f'Stripped bracket extras from BuildRequires for {package.name} ({count} lines)')
        return True

    except Exception as e:
        logger.error(f'Error in _detect_and_fix_extras_in_buildrequires for {package_id}: {e}')
        return False


def _detect_and_fix_vcs_version_failure(package_id: int, build_log: str) -> bool:
    """
    Detect failures caused by VCS-based versioning (hatch-vcs, setuptools-scm)
    when git is not available in the mock chroot, and ensure
    SETUPTOOLS_SCM_PRETEND_VERSION is set before both %pyproject_buildrequires
    and %pyproject_wheel so the version is resolved from the spec %{version} tag.
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision

    _VCS_MARKERS = [
        'setuptools_scm',
        'setuptools-scm',
        'hatch_vcs',
        'hatch-vcs',
        'LookupError: setuptools-scm was unable to detect version',
        'could not detect version for',
        'version-control system not found',
        'subprocess.CalledProcessError.*git',
    ]
    combined = build_log or ''
    if not any(m.lower() in combined.lower() for m in _VCS_MARKERS):
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        content = current_spec.content
        fixes = []

        if '%pyproject_wheel' in content and 'SETUPTOOLS_SCM_PRETEND_VERSION' not in content:
            content = re.sub(
                r'^(%pyproject_wheel\b)',
                r'SETUPTOOLS_SCM_PRETEND_VERSION=%{version} \1',
                content,
                flags=re.MULTILINE,
                count=1,
            )
            fixes.append('set SETUPTOOLS_SCM_PRETEND_VERSION before %pyproject_wheel')

        if '%pyproject_buildrequires' in content and 'SETUPTOOLS_SCM_PRETEND_VERSION' not in content:
            content = re.sub(
                r'^(%pyproject_buildrequires\b)',
                r'SETUPTOOLS_SCM_PRETEND_VERSION=%{version} \1',
                content,
                flags=re.MULTILINE,
                count=1,
            )
            fixes.append('set SETUPTOOLS_SCM_PRETEND_VERSION before %pyproject_buildrequires')

        if not fixes or content == current_spec.content:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=content,
            commit_message=f'Auto-fix: VCS version workaround ({"; ".join(fixes)})',
        )
        log_package(package_id, 'info', f'Auto-fixed VCS version: {"; ".join(fixes)}')
        logger.info(f'Fixed VCS version failure for {package.name}: {fixes}')
        return True

    except Exception as e:
        logger.error(f'Error in _detect_and_fix_vcs_version_failure for {package_id}: {e}')
        return False


def _detect_and_fix_platformdirs_version_tuple(package_id: int, build_log: str) -> bool:
    """
    Detect platformdirs.version symbol import failures and refresh the shim.

    Recent platformdirs expects __version_tuple__/__version_info__ from
    platformdirs.version. Older reqpm shim revisions only defined __version__,
    so this re-runs SpecFixer with a synthetic Missing Python Modules signal
    to rewrite the shim block idempotently.
    """
    from backend.apps.packages.models import Package, SpecFileRevision
    from backend.core.spec_fixer import SpecFixer

    combined = build_log or ''
    if (
        "cannot import name '__version_tuple__' from 'platformdirs.version'" not in combined
        and "cannot import name '__version_info__' from 'platformdirs.version'" not in combined
    ):
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        fixer = SpecFixer()
        new_content, fixes = fixer.apply_fixes(
            current_spec.content,
            [{'category': 'Missing Python Modules', 'items': ['platformdirs.version']}],
        )

        if new_content == current_spec.content:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_content,
            commit_message='Auto-fix: refresh platformdirs.version shim (__version_tuple__/__version_info__)',
        )
        fix_msg = '; '.join(fixes) if fixes else 'refreshed platformdirs.version shim symbols'
        log_package(package_id, 'info', f'Auto-fixed platformdirs.version shim: {fix_msg}')
        logger.info(f'Fixed platformdirs.version symbol import failure for {package.name}: {fix_msg}')
        return True
    except Exception as e:
        logger.error(f'Error in _detect_and_fix_platformdirs_version_tuple for {package_id}: {e}')
        return False


def _detect_and_fix_missing_cc_linker(package_id: int, build_log: str) -> bool:
    """
    Detect Rust failures where linker `cc` is missing and add toolchain deps.

    This usually requires gcc in mock, and cargo/rustc for maturin-backed
    pyproject builds.
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision
    from backend.core.spec_fixer import SpecFixer

    combined = build_log or ''
    cc_missing = (
        re.search(r"linker\s+`?cc`?\s+not\s+found", combined, re.IGNORECASE)
        or re.search(r"linker\s+cc\s+not\s+found", combined, re.IGNORECASE)
        or ('linker `cc`' in combined and 'No such file or directory' in combined)
    )
    if not cc_missing:
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        fixer = SpecFixer()
        new_content, fixes = fixer._add_buildrequires_items(
            current_spec.content,
            ['gcc', 'rustc', 'cargo'],
        )
        if new_content == current_spec.content:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_content,
            commit_message='Auto-fix: add gcc/rustc/cargo for missing cc linker',
        )
        fix_msg = '; '.join(fixes) if fixes else 'added gcc/rustc/cargo BuildRequires'
        log_package(package_id, 'info', f'Auto-fixed missing linker cc: {fix_msg}')
        logger.info(f'Fixed missing cc linker for {package.name}: {fix_msg}')
        return True
    except Exception as e:
        logger.error(f'Error in _detect_and_fix_missing_cc_linker for {package_id}: {e}')
        return False


def _detect_and_fix_rustc_version_mismatch(package_id: int, build_log: str) -> bool:
    """
    Detect cargo/maturin failures caused by distro rustc being too old, e.g.:
      "error: rustc 1.92.0 is not supported ... requires rustc 1.94.0"

    Fix strategy:
    - Remove distro BuildRequires for rust/cargo/rustc variants from spec.
    - Let the builder's custom rustup-based toolchain provisioning drive
      rust/cargo versions during retry.
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision

    text = build_log or ''
    if 'is not supported by the following packages' not in text or 'requires rustc' not in text:
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        content = current_spec.content

        # Remove explicit distro rust toolchain dependencies so they don't
        # force-install older RHEL versions when we need a newer custom one.
        patterns = [
            r'^\s*BuildRequires\s*:\s*(?:python3dist\()?(?:rustc|rust|cargo|rust-std-static)(?:\))?[^\n]*\n?',
            r'^\s*BuildRequires\s*:\s*rust-toolset[^\n]*\n?',
        ]

        new_content = content
        removed = 0
        for pat in patterns:
            new_content, n = re.subn(pat, '', new_content, flags=re.MULTILINE | re.IGNORECASE)
            removed += n

        if removed == 0 or new_content == content:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_content,
            commit_message='Auto-fix: remove distro rust/cargo BuildRequires for rustc version mismatch',
        )
        log_package(
            package_id,
            'info',
            f'Auto-fixed rust toolchain mismatch: removed {removed} distro rust/cargo BuildRequires line(s)',
        )
        logger.info(
            f'Fixed rustc version mismatch for {package.name}: removed {removed} distro BuildRequires line(s)'
        )
        return True

    except Exception as e:
        logger.error(f'Error in _detect_and_fix_rustc_version_mismatch for {package_id}: {e}')
        return False


def _detect_and_fix_noarch_sitearch_mismatch(package_id: int, build_log: str) -> bool:
    """
    Fix packages incorrectly marked noarch when install paths resolve to sitearch.

    Symptom in build log:
    - Processing files: ...noarch
    - Directory not found: .../usr/lib/pythonX.Y/site-packages/<module>
    while content is actually in /usr/lib64/pythonX.Y/site-packages.
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision

    combined = build_log or ''
    has_noarch_processing = bool(re.search(r'Processing files: .*\.noarch\b', combined))
    has_missing_lib_path = bool(
        re.search(r'Directory not found: .*?/usr/lib/python\d+\.\d+/site-packages/', combined)
    )
    has_sitearch_path = '/usr/lib64/python' in combined

    if not (has_noarch_processing and has_missing_lib_path and has_sitearch_path):
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        new_content, count = re.subn(
            r'^BuildArch:\s*noarch\s*\n',
            '',
            current_spec.content,
            flags=re.MULTILINE,
        )
        if count == 0 or new_content == current_spec.content:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_content,
            commit_message='Auto-fix: remove BuildArch noarch for sitearch Python/Rust package',
        )
        log_package(package_id, 'info', 'Auto-fixed BuildArch: removed noarch for sitearch install paths')
        logger.info(f'Fixed noarch/sitearch mismatch for {package.name}: removed BuildArch noarch')
        return True
    except Exception as e:
        logger.error(f'Error in _detect_and_fix_noarch_sitearch_mismatch for {package_id}: {e}')
        return False


def _detect_and_fix_pyproject_save_files_auto(package_id: int, build_log: str) -> bool:
    """
    Fix pyproject file list generation when module paths differ between sitelib/sitearch.

    Symptom:
    - Directory not found: .../usr/lib/pythonX.Y/site-packages/<module>
    while package files are recorded under /usr/lib64/... during %pyproject_save_files.
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision

    combined = build_log or ''
    has_missing_sitelib_module = bool(
        re.search(r'Directory not found: .*?/usr/lib/python\d+\.\d+/site-packages/maturin\b', combined)
    )
    has_sitearch_activity = '/usr/lib64/python' in combined
    if not (has_missing_sitelib_module and has_sitearch_activity):
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        if '%pyproject_save_files +auto' in current_spec.content:
            return False

        new_content, count = re.subn(
            r'^%pyproject_save_files\s+[^\n]+$\n?',
            '%pyproject_save_files +auto\n',
            current_spec.content,
            count=1,
            flags=re.MULTILINE,
        )
        if count == 0 or new_content == current_spec.content:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_content,
            commit_message='Auto-fix: switch %pyproject_save_files to +auto for sitearch mismatch',
        )
        log_package(package_id, 'info', 'Auto-fixed %pyproject_save_files: switched to +auto')
        logger.info(f'Fixed pyproject_save_files mismatch for {package.name}: switched to +auto')
        return True
    except Exception as e:
        logger.error(f'Error in _detect_and_fix_pyproject_save_files_auto for {package_id}: {e}')
        return False


def _detect_and_fix_sitearch_files_entry(package_id: int, build_log: str) -> bool:
    """
    Fix explicit %files sitelib entries when package installs into sitearch.

    Also normalize accidental "%pyproject_save_files +auto <module>" back to
    "%pyproject_save_files +auto".
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision

    combined = build_log or ''
    if not re.search(r'Directory not found: .*?/usr/lib/python\d+\.\d+/site-packages/maturin\b', combined):
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        content = current_spec.content
        changed = False

        normalized, n1 = re.subn(
            r'^(%pyproject_save_files\s+\+auto)\s+[^\n]+$',
            r'\1',
            content,
            flags=re.MULTILINE,
        )
        if n1:
            content = normalized
            changed = True

        updated, n2 = re.subn(
            r'^\s*%\{python3_sitelib\}/maturin/\s*$',
            '%{python3_sitearch}/maturin/',
            content,
            flags=re.MULTILINE,
        )
        if n2:
            content = updated
            changed = True

        if not changed or content == current_spec.content:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=content,
            commit_message='Auto-fix: use sitearch files entry for maturin and normalize +auto save_files',
        )
        log_package(package_id, 'info', 'Auto-fixed %files path to %{python3_sitearch}/maturin and normalized %pyproject_save_files +auto')
        logger.info(f'Fixed sitearch files entry for {package.name}')
        return True
    except Exception as e:
        logger.error(f'Error in _detect_and_fix_sitearch_files_entry for {package_id}: {e}')
        return False


def _detect_and_fix_duplicate_files_and_empty_debugsource(package_id: int, build_log: str) -> bool:
    """
    Fix packaging-stage failures for duplicated file entries and empty debugsource.

    Typical symptoms:
    - "File listed twice: .../site-packages/maturin/..."
    - "error: Empty %files file .../debugsourcefiles.list"
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision

    combined = build_log or ''
    has_dup = 'File listed twice:' in combined
    has_empty_debugsource = 'Empty %files file' in combined and 'debugsourcefiles.list' in combined
    if not (has_dup or has_empty_debugsource):
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        content = current_spec.content
        fixes = []

        # When using "%files -f %{pyproject_files}", explicit maturin module dir
        # duplicates entries produced by pyproject_save_files.
        content2, n_rm = re.subn(
            r'^\s*%\{python3_(?:sitelib|sitearch)\}/maturin/\s*\n',
            '',
            content,
            flags=re.MULTILINE,
        )
        if n_rm:
            content = content2
            fixes.append('removed explicit %{python3_site*}/maturin/ files entry')

        # Some runs produce an empty debugsourcefiles.list for this package.
        if has_empty_debugsource and '%global debug_package %{nil}' not in content:
            if re.search(r'^Name:\s+', content, flags=re.MULTILINE):
                content = re.sub(
                    r'^(Name:\s+.*\n)',
                    r'%global debug_package %{nil}\n\1',
                    content,
                    count=1,
                    flags=re.MULTILINE,
                )
            else:
                content = '%global debug_package %{nil}\n' + content
            fixes.append('disabled debug package generation for empty debugsourcefiles.list')

        if content == current_spec.content or not fixes:
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=content,
            commit_message=f'Auto-fix: packaging duplicates/debugsource ({"; ".join(fixes)})',
        )
        log_package(package_id, 'info', f'Auto-fixed packaging issue: {"; ".join(fixes)}')
        logger.info(f'Fixed packaging duplicate/debugsource issue for {package.name}: {fixes}')
        return True
    except Exception as e:
        logger.error(f'Error in _detect_and_fix_duplicate_files_and_empty_debugsource for {package_id}: {e}')
        return False


def _detect_and_fix_with_ai(package_id: int, build_log: str, root_log: str = '', ai_attempt: int = 0) -> bool:
    """
    Last-resort fixer: ask the configured LLM (see settings.REQPM['AI_FIXER'])
    to propose structured fix actions for an unrecognized build failure.
    Returns True if a new spec revision was created (caller retries build).
    No-op when AI_FIXER is disabled.
    """
    try:
        from backend.core.ai_fixer import (
            AISlotTimeoutError,
            attempt_ai_fix,
            get_config,
            get_slot_wait_timeout,
            is_enabled,
        )
        if not is_enabled():
            return False
        cfg = get_config()
        wait_timeout = get_slot_wait_timeout(cfg)
        log_package(
            package_id,
            'info',
            f'Rule-based fixers exhausted, trying AI fixer (waiting for slot up to {wait_timeout}s)...',
        )
        result = attempt_ai_fix(package_id, build_log, root_log, ai_attempt=ai_attempt)
        send_package_update(package_id)
        if result:
            log_package(package_id, 'info', 'AI fixer proposed a spec fix, retrying build')
        else:
            log_package(package_id, 'info', 'AI fixer could not propose a fix')
        return result
    except AISlotTimeoutError as e:
        # Fail fast: skip AI and let the caller finalize the current failed build
        # using already collected/analyzed logs.
        log_package(package_id, 'warning', f'{e}. Failing fast with current analyzed errors.')
        logger.warning(f"AI fixer slot wait timeout for package {package_id}: {e}")
        return False
    except Exception as e:
        logger.warning(f"Error in _detect_and_fix_with_ai for {package_id}: {e}")
        return False


def _has_fixable_build_signals(build_log: str, root_log: str) -> bool:
    """
    Return True only when logs contain recognizable RPM/spec failure signals.

    This prevents running rule/AI fixers against incomplete logs from
    infrastructure-level failures where no package-level fix can be inferred.
    """
    text = f"{build_log or ''}\n{root_log or ''}"
    if not text.strip():
        return False

    markers = [
        'RPM build errors',
        'Bad exit status',
        'Executing(%generate_buildrequires)',
        'Executing(%build)',
        'Executing(%install)',
        'Traceback (most recent call last):',
        'ModuleNotFoundError:',
        'ImportError:',
        'PermissionError:',
        'error:',
    ]
    return any(m in text for m in markers)


def _update_project_local_repo(project_id: int, rpm_paths: list, rhel_version: int = None) -> str:
    """
    Copy newly built RPMs into a per-project, per-RHEL-version local DNF repo
    and run createrepo_c so subsequent builds within the same project can depend
    on them.

    RPMs are stored under build_artifacts/projects/<id>/el<N>/  (e.g. el10).
    This avoids mixing el9 and el10 packages which would cause ABI conflicts
    when mock tries to satisfy BuildRequires inside the target chroot.

    If rhel_version is given explicitly, all RPMs go into that folder and the
    function returns its path.  If not given, each RPM is auto-routed to the
    folder matching its own .elN. suffix and the function returns the 'common'
    fallback directory (callers that need a specific path should pass rhel_version).

    Returns the absolute path to the versioned repo directory for rhel_version
    (or 'common' when rhel_version is None).
    """
    import re
    import shutil
    import subprocess
    import hashlib
    from pathlib import Path
    from django.conf import settings
    from backend.apps.packages.models import Package

    base = Path(settings.REQPM['BUILD_DIR']) / 'projects' / str(project_id)

    def _repo_dir_for_version(ver):
        label = f'el{ver}' if ver else 'common'
        d = base / label
        d.mkdir(parents=True, exist_ok=True)
        return d

    dirs_to_update = set()

    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()

    # Always include all completed project package RPMs so dependency resolution
    # is stable across restarts/cleanups and not tied only to the latest build.
    hydrated_rpm_paths = []
    completed_qs = Package.objects.filter(project_id=project_id, build_status='completed').exclude(rpm_path__isnull=True).exclude(rpm_path='')
    for pkg in completed_qs.only('rpm_path'):
        if pkg.rpm_path and Path(pkg.rpm_path).exists():
            if rhel_version is None or re.search(rf'\.el{int(rhel_version)}[._]', Path(pkg.rpm_path).name):
                hydrated_rpm_paths.append(pkg.rpm_path)
                # Also include all sibling RPMs in the same build output directory
                # (e.g. the main package + debuginfo + debugsource all live together).
                # This ensures the main package is not missed when rpm_path accidentally
                # points to a debug sub-package.
                sibling_dir = Path(pkg.rpm_path).parent
                for sib in sibling_dir.glob('*.rpm'):
                    sib_str = str(sib)
                    if sib_str not in hydrated_rpm_paths:
                        if rhel_version is None or re.search(rf'\.el{int(rhel_version)}[._]', sib.name):
                            hydrated_rpm_paths.append(sib_str)

    all_rpm_paths = list(rpm_paths or []) + hydrated_rpm_paths

    for rpm_path in all_rpm_paths:
        if not rpm_path or not Path(rpm_path).exists():
            continue

        # Determine which folder this RPM belongs in.
        if rhel_version is not None:
            target_ver = rhel_version
        else:
            m = re.search(r'\.el(\d+)\.', Path(rpm_path).name)
            target_ver = int(m.group(1)) if m else None

        repo_dir = _repo_dir_for_version(target_ver)
        dest = repo_dir / Path(rpm_path).name
        if not dest.exists():
            shutil.copy2(rpm_path, dest)
            label = f'el{target_ver}' if target_ver else 'common'
            logger.info(f"Copied {Path(rpm_path).name} into project {project_id}/{label} local repo")
        else:
            # Same NEVR can be rebuilt with different content; replace stale repo
            # artifact when checksums differ so downstream builds use the latest RPM.
            try:
                src_hash = _sha256(Path(rpm_path))
                dst_hash = _sha256(dest)
            except Exception as e:
                logger.warning(f"Checksum compare failed for {Path(rpm_path).name}: {e}; forcing overwrite")
                src_hash = None
                dst_hash = None

            if src_hash != dst_hash:
                shutil.copy2(rpm_path, dest)
                label = f'el{target_ver}' if target_ver else 'common'
                logger.info(f"Replaced stale {Path(rpm_path).name} in project {project_id}/{label} local repo")
        dirs_to_update.add(repo_dir)

    # Ensure the target version directory always exists (even when no RPMs given)
    primary_dir = _repo_dir_for_version(rhel_version)
    dirs_to_update.add(primary_dir)

    # Rebuild repo metadata for every affected directory
    for repo_dir in dirs_to_update:
        try:
            result = subprocess.run(
                ['createrepo_c', '--update', str(repo_dir)],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                logger.warning(f"createrepo_c failed for {repo_dir}: {result.stderr}")
        except Exception as e:
            logger.warning(f"createrepo_c exception for {repo_dir}: {e}")

    return str(primary_dir)


def _normalize_dep_names(item: str):
    """
    Normalize a single rpm dep string to a list of candidate package names.
    E.g. 'python3dist(requests) >= 2.0' -> ['python3-requests', 'requests']
    E.g. '(python3dist(flit-core) < 4~~ with ...)' -> ['python3-flit-core', 'flit-core']
    """
    import re

    def _strip_extras(name: str) -> str:
        # Convert dist names like "pyjwt[crypto]" to "pyjwt".
        return re.sub(r'\[[^\]]*\]', '', (name or '')).strip()

    # Common python3dist() names that do not match the PyPI project name directly.
    alias_map = {
        'yaml': 'pyyaml',
        'setuptools-rust': 'setuptools_rust',
        '_cffi_backend': 'cffi',
        'versioneer': 'versioneer',
        'pathfix': 'pathfix-python',
    }

    # Strip whitespace and unwrap only true outer grouping parentheses.
    # Do not strip all ')' blindly, or python3dist(foo) becomes malformed.
    item = (item or '').strip()
    if not item:
        return []

    # Ignore malformed/noise tokens captured from logs.
    if item.lower() in {'python3dist', 'python3?dist', 'dist'}:
        return []

    # Handle file-path style dependency hints from RPM output.
    if item.startswith('/usr/bin/pathfix'):
        return ['pathfix', 'pathfix-python']

    if item.startswith('(') and item.endswith(')'):
        item = item[1:-1].strip()
    # Strip version constraints (handle 'with' keyword for complex constraints)
    item = re.split(r'\s+(with|[><=!])', item)[0].strip()

    # Known extras that should resolve to a concrete base package.
    # Example: versioneer[toml] -> versioneer
    extras_alias_map = {
        'versioneer[toml]': 'versioneer',
        'aiohttp[speedups]': 'aiohttp',
        'pyjwt[crypto]': 'pyjwt',
    }

    # Direct dependency aliases observed in build logs where the provides name
    # differs from the project package name.
    direct_dep_aliases = {
        'protobuf-devel': 'protobuf',
        'zope': 'zope-interface',
        'rds-py': 'rpds-py',
        'rds_py': 'rpds_py',
    }
    # python3dist(foo-bar) or python3dist(foo_bar)
    m = re.match(r'python3?dist\(([^)]+)\)', item, re.IGNORECASE)
    if m:
        raw = m.group(1).strip().lower()
        raw = direct_dep_aliases.get(raw, raw)
        base = extras_alias_map.get(raw, _strip_extras(raw))
        pkg_name = base.replace('_', '-').lower()
        aliases = [pkg_name]
        if pkg_name in alias_map:
            aliases.append(alias_map[pkg_name])
        out = []
        seen = set()
        for name in aliases:
            for cand in (f'python3-{name}', name):
                if cand not in seen:
                    seen.add(cand)
                    out.append(cand)
        return out
    # python3(foo)
    m = re.match(r'python3?\(([^)]+)\)', item, re.IGNORECASE)
    if m:
        raw = m.group(1).strip().lower()
        raw = direct_dep_aliases.get(raw, raw)
        base = extras_alias_map.get(raw, _strip_extras(raw))
        pkg_name = base.replace('_', '-').lower()
        aliases = [pkg_name]
        if pkg_name in alias_map:
            aliases.append(alias_map[pkg_name])
        out = []
        seen = set()
        for name in aliases:
            for cand in (f'python3-{name}', name):
                if cand not in seen:
                    seen.add(cand)
                    out.append(cand)
        return out
    # Already a plain name
    plain_raw = item.strip().lower()
    plain_raw = direct_dep_aliases.get(plain_raw, plain_raw)
    plain = extras_alias_map.get(plain_raw, _strip_extras(plain_raw))
    # Treat distro-style python package names as aliases for the base project
    # name so mixed-case tokens like python3-PyJWT map to pyjwt.
    if plain.startswith('python3-'):
        plain = plain[8:]
    elif plain.startswith('python-'):
        plain = plain[7:]
    plain_dash = plain.replace('_', '-').lower()
    aliases = [plain_dash]
    if plain_dash in alias_map:
        aliases.append(alias_map[plain_dash])
    out = []
    seen = set()
    for name in aliases:
        for cand in (name, name.replace('-', '_')):
            if cand and cand not in seen:
                seen.add(cand)
                out.append(cand)
    # Plain package tokens can include distro prefixes (e.g. python3-maturin).
    # Add de-prefixed variants so they match project package names (maturin).
    deprefixed = []
    for cand in list(out):
        if cand.startswith('python3-'):
            deprefixed.append(cand[8:])
        elif cand.startswith('python-'):
            deprefixed.append(cand[7:])
    for cand in deprefixed:
        for variant in (cand, cand.replace('-', '_')):
            if variant and variant not in seen:
                seen.add(variant)
                out.append(variant)
    # For dotted module paths (e.g. 'platformdirs.version'), also add the
    # top-level module name as a candidate package name so that completing
    # 'python3-platformdirs' resolves a blocker of 'platformdirs.version'.
    if '.' in plain_dash:
        root = plain_dash.split('.')[0]
        for cand in (root, f'python3-{root}'):
            if cand and cand not in seen:
                seen.add(cand)
                out.append(cand)
    return out


def _is_self_dependency_item(package, item: str) -> bool:
    """
    Return True if a missing-dependency item refers to the package itself
    (e.g. python3dist(coherent.licensed) while building coherent.licensed).
    """
    import re

    def _norm(s: str) -> str:
        return re.sub(r'[-.]', '_', (s or '').strip().lower())

    package_aliases = set()
    for raw in (getattr(package, 'name', ''), getattr(package, 'python_name', '')):
        n = _norm(raw)
        if not n:
            continue
        package_aliases.add(n)
        package_aliases.add(re.sub(r'^python3?_', '', n))

    for cand in _normalize_dep_names(item):
        c = _norm(cand)
        if c in package_aliases or re.sub(r'^python3?_', '', c) in package_aliases:
            return True
    return False


def _find_project_packages_for_items(project, missing_items):
    """
    Given a list of missing dep item strings, return Package objects in the
    same project whose names match (case-insensitive).
    """
    from backend.apps.packages.models import Package
    from django.db.models import Q

    candidate_names = set()
    for item in missing_items:
        for name in _normalize_dep_names(item):
            candidate_names.add(name.lower())

    if not candidate_names:
        return []

    q = Q()
    for name in candidate_names:
        q |= Q(name__iexact=name)
    return list(Package.objects.filter(project=project).filter(q))


def _satisfies_dep_version_constraint(item: str, package_version: str) -> bool:
    """
    Return True if package_version satisfies version constraints embedded in a
    missing dependency item string (if any).
    """
    import re

    # No explicit comparator means no version constraint.
    spec_parts = re.findall(r'(<=|>=|==|!=|<|>)\s*([A-Za-z0-9][A-Za-z0-9_.+-]*)', item or '')
    if not spec_parts:
        return True

    spec = ','.join(f'{op}{ver}' for op, ver in spec_parts)
    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version, InvalidVersion

        return Version(str(package_version)) in SpecifierSet(spec)
    except Exception:
        # Be conservative: if we cannot evaluate the constraint, do not mark it resolved.
        return False


def _extract_required_extras(item: str) -> set[str]:
    """
    Extract required extras from a missing dependency token.

    Examples:
      python3dist(pyjwt[crypto]) -> {'crypto'}
      python3-PyJWT[crypto,speedups] -> {'crypto', 'speedups'}
    """
    import re

    text = (item or '').strip()
    if not text:
        return set()

    m = re.search(r'python3?dist\(([^)]+)\)', text, re.IGNORECASE)
    if m:
        text = m.group(1)
    else:
        m = re.search(r'python3?\(([^)]+)\)', text, re.IGNORECASE)
        if m:
            text = m.group(1)

    m = re.search(r'\[([^\]]+)\]', text)
    if not m:
        return set()

    return {
        e.strip().lower()
        for e in m.group(1).split(',')
        if e and e.strip()
    }


def _has_required_extras_enabled(pkg, required_extras: set[str], cache: dict[int, set[str]] | None = None) -> bool:
    """Return True when pkg has all required extras enabled."""
    if not required_extras:
        return True

    enabled = None
    if cache is not None:
        enabled = cache.get(pkg.id)

    if enabled is None:
        enabled = {
            name.strip().lower()
            for name in pkg.extras.filter(enabled=True).values_list('name', flat=True)
            if name
        }
        if cache is not None:
            cache[pkg.id] = enabled

    return required_extras.issubset(enabled)


def _enable_required_dependency_extras_and_rebuild(blocked_package, unresolved_items, matched_packages) -> int:
    """
    For unresolved missing items that map to known project packages and require
    extras, enable those extras on dependency packages and queue rebuilds.

    Returns the number of dependency packages queued for rebuild.
    """
    from backend.apps.packages.artifact_cleanup import (
        wipe_package_artifacts_for_rebuild,
        reset_package_build_state,
    )
    from backend.apps.packages.models import PackageDependency

    dep_runtime_reqs = {
        d.depends_on_id: (d.version_constraint or '')
        for d in PackageDependency.objects.filter(package=blocked_package).exclude(depends_on_id__isnull=True)
    }

    pypi_req_cache = {}

    def _infer_required_extras(dep_pkg, item: str) -> set[str]:
        import re

        required = _extract_required_extras(item)
        if required:
            return required

        # Preferred source: stored runtime requirement from dependency resolver
        # (includes extras markers such as pyjwt[crypto]).
        rel_req = dep_runtime_reqs.get(dep_pkg.id, '')
        required = _extract_required_extras(rel_req)
        if required:
            return required

        # Fallback: inspect current package runtime deps from PyPI metadata.
        try:
            reqs = pypi_req_cache.get('runtime_reqs')
            if reqs is None:
                pkg_info = PyPIClient().get_package_info(
                    blocked_package.python_name or blocked_package.name,
                    blocked_package.version or None,
                )
                reqs = list(pkg_info.runtime_dependencies) if pkg_info else []
                pypi_req_cache['runtime_reqs'] = reqs

            for req in reqs:
                req_extras = _extract_required_extras(req)
                if not req_extras:
                    continue
                # Requirement strings may attach version constraints without
                # whitespace (e.g. PyJWT[crypto]<3,>=1.0.0). Extract only the
                # leading dependency token before normalization.
                req_name_token = (req or '').split(';', 1)[0].strip()
                m = re.match(r'^([A-Za-z0-9_.+-]+(?:\[[^\]]+\])?)', req_name_token)
                if m:
                    req_name_token = m.group(1)

                if dep_pkg.name.lower() in {n.lower() for n in _normalize_dep_names(req_name_token)}:
                    return req_extras
        except Exception as e:
            logger.debug(f"Could not infer required extras for {blocked_package.name}->{dep_pkg.name}: {e}")

        return set()

    dep_required: dict[int, set[str]] = {}
    dep_by_id = {p.id: p for p in matched_packages if p.id != blocked_package.id}

    for item in unresolved_items:
        candidates = {n.lower() for n in _normalize_dep_names(item)}
        for dep in dep_by_id.values():
            if dep.name.lower() in candidates:
                required_extras = _infer_required_extras(dep, item)
                if not required_extras:
                    continue
                dep_required.setdefault(dep.id, set()).update(required_extras)

    queued = 0
    for dep_id, req_extras in dep_required.items():
        dep = dep_by_id.get(dep_id)
        if not dep:
            continue

        enabled = {
            name.strip().lower()
            for name in dep.extras.filter(enabled=True).values_list('name', flat=True)
            if name
        }
        missing = sorted(req_extras - enabled)
        if not missing:
            continue

        toggled = []
        unresolved_extra_defs = []
        for ex in missing:
            extra_obj = dep.extras.filter(name__iexact=ex).first()
            if not extra_obj:
                unresolved_extra_defs.append(ex)
                continue
            if not extra_obj.enabled:
                extra_obj.enabled = True
                extra_obj.save(update_fields=['enabled'])
                toggled.append(extra_obj.name)

        if unresolved_extra_defs:
            # Refresh extras metadata and try again on next monitor cycle.
            sync_package_extras_task.delay(dep.id)
            log_package(
                blocked_package.id,
                'info',
                f"Dependency {dep.name} is missing extras metadata for: {', '.join(unresolved_extra_defs)}; queued extras sync",
            )

        if toggled:
            cleanup = wipe_package_artifacts_for_rebuild(dep, reason='auto-enable-required-extras')
            reset_package_build_state(dep)
            send_package_update(dep.id)
            generate_spec_file_task.delay(dep.id, force=True, auto_build=True)
            queued += 1

            log_package(
                blocked_package.id,
                'info',
                f"Enabled extras on dependency {dep.name}: {', '.join(sorted({t.lower() for t in toggled}))}; queued rebuild",
            )
            log_package(
                dep.id,
                'info',
                f"Auto-enabled extras due to dependent {blocked_package.name}: {', '.join(sorted({t.lower() for t in toggled}))}; cleanup={cleanup}",
            )

    return queued


def _analyze_missing_item_resolution(package, project, missing_items):
    """
    Analyze missing dependency items and classify unresolved items into:
    - unresolved_with_project_match: item maps to project packages, but none satisfy
      completion/RHEL/version constraints yet.
    - unresolved_without_project_match: item does not map to any project package.
    """
    matched = _find_project_packages_for_items(project, missing_items)

    unresolved_with_project_match = []
    unresolved_without_project_match = []
    enabled_extras_cache: dict[int, set[str]] = {}

    for item in missing_items:
        candidates = {n.lower() for n in _normalize_dep_names(item)}
        item_matches = [
            p for p in matched
            if p.id != package.id and p.name.lower() in candidates
        ]

        if not item_matches:
            unresolved_without_project_match.append(item)
            continue

        satisfied = any(
            p.build_status in ('completed', 'not_required')
            and _built_for_rhel(p, project.rhel_version)
            and _satisfies_dep_version_constraint(item, p.version)
            and _has_required_extras_enabled(p, _extract_required_extras(item), enabled_extras_cache)
            for p in item_matches
        )
        if not satisfied:
            unresolved_with_project_match.append(item)

    return {
        'matched': matched,
        'unresolved_with_project_match': unresolved_with_project_match,
        'unresolved_without_project_match': unresolved_without_project_match,
    }


def _built_for_rhel(pkg, rhel_version) -> bool:
    """
    Check whether a 'completed' package was actually built for the given RHEL
    version. When a project's rhel_version changes (e.g. 9 -> 10), previously
    built packages keep build_status='completed' but their RPMs only exist in
    the old el<N> repo, so dependent builds fail with missing packages.
    Detected via the dist tag in the RPM filename (e.g. '.el9.noarch.rpm').
    """
    import re
    if not rhel_version:
        return True
    rpm_name = os.path.basename(pkg.rpm_path or '')
    if not rpm_name:
        return True  # Can't verify — assume OK
    m = re.search(r'\.el(\d+)[._]', rpm_name)
    if not m:
        return True
    return int(m.group(1)) == int(rhel_version)


def _resolve_missing_dep_status(package, project):
    """
    Decide between 'dep_build_pending' and 'missing_packages' based on whether
    the missing deps are already known packages in the project (just not yet built).
    Returns the appropriate build_status string.
    """
    missing_cats = {
        'Missing Packages', 'Missing Dependencies', 'Missing Python Modules',
        'Missing Header Files', 'Missing Rust/Cargo', 'Missing Python Wheel', 'Missing GCC'
    }
    missing_items = []
    for e in (package.analyzed_errors or []):
        if e.get('category') in missing_cats:
            missing_items.extend(e.get('items', []))

    # Ignore self-referential dependency items (python3dist(this-package)).
    filtered_items = [i for i in missing_items if not _is_self_dependency_item(package, i)]
    if len(filtered_items) != len(missing_items):
        logger.info(
            f"Ignoring {len(missing_items) - len(filtered_items)} self-dependency item(s) "
            f"for {package.name}"
        )

    if not filtered_items:
        log_package(package.id, 'info',
            'Only self-referential missing dependencies were detected; not treating as missing packages')
        return 'failed'

    resolution = _analyze_missing_item_resolution(package, project, filtered_items)
    matched = resolution['matched']
    # If any of the missing deps exist in the project as unbuilt packages → dep_build_pending
    unbuilt_matches = [p for p in matched if p.build_status not in ('completed', 'not_required') and p.id != package.id]

    # Packages marked 'completed' but built for a different RHEL version are
    # stale (e.g. project switched from RHEL 9 to 10) — requeue them.
    stale_matches = [
        p for p in matched
        if p.build_status == 'completed' and p.id != package.id
        and not _built_for_rhel(p, project.rhel_version)
    ]
    for p in stale_matches:
        log_package(p.id, 'info',
            f"Rebuild queued: previously built for a different RHEL version, "
            f"project now targets RHEL {project.rhel_version}")
        p.build_status = 'pending'
        p.save(update_fields=['build_status'])
        build_single_package_task.delay(p.id)

    unresolved_with_project = resolution['unresolved_with_project_match']
    unresolved_without_project = resolution['unresolved_without_project_match']

    # If blockers map to project packages but required extras are not enabled,
    # auto-enable extras on those dependency packages and queue rebuilds.
    if unresolved_with_project and not unresolved_without_project:
        extras_queued = _enable_required_dependency_extras_and_rebuild(
            package,
            unresolved_with_project,
            matched,
        )
        if extras_queued:
            log_package(
                package.id,
                'info',
                f'Queued {extras_queued} dependency package(s) for rebuild with required extras enabled',
            )

    # If every unresolved item maps to project packages, keep package in
    # dep_build_pending. If any unresolved item has no project match, treat as
    # missing_packages to avoid endless auto-retry loops.
    if unresolved_with_project and not unresolved_without_project:
        if unbuilt_matches or stale_matches:
            names = ', '.join(p.name for p in unbuilt_matches + stale_matches)
            log_package(package.id, 'info',
                f"Missing deps found as unbuilt project packages: {names} — waiting for them")
        else:
            names = ', '.join(sorted({p.name for p in matched if p.id != package.id}))
            log_package(package.id, 'info',
                f"Missing deps map to existing project packages: {names} — marked as dependency-pending")
        return 'dep_build_pending'

    if not unresolved_with_project and not unresolved_without_project:
        log_package(package.id, 'info',
            'Missing dependency analyzer items are already satisfied; leaving status as failed')
        return 'failed'

    return 'missing_packages'


def auto_add_missing_dependencies(package_id: int):
    """
    Automatically add missing dependencies to the project's transitive dependency list.
    
    When a build fails due to missing packages/dependencies, this function:
    1. Extracts missing package names from analyzed_errors
    2. Normalizes them to Python package names
    3. Checks if they already exist in the project (direct or transitive)
    4. For new packages, fetches info from PyPI and adds them as transitive dependencies
    5. Records dependency relationship (which package depends on which)
    
    Args:
        package_id: ID of the package that failed with missing dependencies
    """
    from backend.apps.packages.models import Package, PackageDependency
    from backend.core.pypi_client import PyPIClient
    from backend.apps.projects.tasks import log_project
    
    try:
        package = Package.objects.select_related('project').get(id=package_id)
        project = package.project
        
        # Categories that indicate missing packages/dependencies
        missing_cats = {
            'Missing Packages', 'Missing Dependencies', 'Missing Python Modules',
            'Missing Header Files', 'Missing Rust/Cargo', 'Missing Python Wheel', 'Missing GCC'
        }
        
        # Extract all missing items from analyzed errors
        missing_items = []
        for error in (package.analyzed_errors or []):
            if error.get('category') in missing_cats:
                items = error.get('items', [])
                missing_items.extend(items)
        
        if not missing_items:
            logger.debug(f"No missing dependencies found for package {package.name}")
            return

        # Drop self-referential items so we never auto-add the package itself.
        missing_items = [i for i in missing_items if not _is_self_dependency_item(package, i)]
        if not missing_items:
            logger.info(f"Only self-referential missing deps for {package.name}; nothing to auto-add")
            return
        
        logger.info(f"Found {len(missing_items)} missing items for {package.name}: {missing_items}")
        log_package(package_id, 'info', f"Analyzing {len(missing_items)} missing dependencies...")
        
        # Normalize dependency names to Python package names
        candidate_packages = set()
        for item in missing_items:
            normalized_names = _normalize_dep_names(item)
            for name in normalized_names:
                # Extract base package name (remove python3- prefix, handle special cases)
                clean_name = name.lower()
                if clean_name.startswith('python3-'):
                    clean_name = clean_name[8:]  # Remove 'python3-' prefix
                elif clean_name.startswith('python-'):
                    clean_name = clean_name[7:]  # Remove 'python-' prefix
                
                # Skip system packages that aren't Python packages
                skip_packages = {
                    'gcc', 'gcc-c++', 'g++', 'cargo', 'rust', 'wheel',
                    'setuptools', 'pip', 'mock', 'rpm-build'
                }
                if clean_name not in skip_packages:
                    candidate_packages.add(clean_name)
        
        if not candidate_packages:
            logger.debug(f"No Python packages to add (only system packages)")
            return
        
        # Check which packages already exist in the project
        existing_packages = Package.objects.filter(
            project=project,
            name__in=[name.replace('_', '-') for name in candidate_packages] + list(candidate_packages)
        ).values_list('name', flat=True)
        existing_names_lower = {name.lower().replace('-', '_') for name in existing_packages}
        
        # Add missing packages that don't exist
        pypi_client = PyPIClient()
        added_count = 0
        failed_count = 0
        
        for pkg_name in candidate_packages:
            # Normalize package name for comparison (use underscore as canonical)
            normalized = pkg_name.replace('-', '_')
            
            if normalized in existing_names_lower:
                # Package exists - still create dependency relationship
                existing_pkg = Package.objects.filter(
                    project=project,
                    name__iexact=normalized.replace('_', '-')
                ).first()
                if not existing_pkg:
                    existing_pkg = Package.objects.filter(
                        project=project,
                        name__iexact=normalized
                    ).first()
                
                if existing_pkg:
                    # Create dependency relationship if it doesn't exist
                    PackageDependency.objects.get_or_create(
                        package=package,
                        depends_on=existing_pkg,
                        defaults={'dependency_type': PackageDependency.DependencyType.BUILD}
                    )
                    # If the dependency exists but has not been built yet,
                    # queue it so the blocked package can progress.
                    if existing_pkg.id != package.id and existing_pkg.build_status in {
                        'not_built', 'failed', 'missing_packages', 'dep_build_pending'
                    }:
                        existing_pkg.build_status = 'pending'
                        existing_pkg.save(update_fields=['build_status'])
                        send_package_update(existing_pkg.id)
                        build_single_package_task.delay(existing_pkg.id)
                        log_package(
                            package_id,
                            'info',
                            f"Queued existing dependency for build: {existing_pkg.name}"
                        )
                    logger.debug(f"Package {pkg_name} already exists, created dependency relationship")
                continue
            
            # Try to fetch package info from PyPI
            try:
                # PyPI typically uses hyphens in package names
                pypi_name = pkg_name.replace('_', '-')
                pkg_info = pypi_client.get_package_info(pypi_name)
                
                if not pkg_info:
                    # Try with underscores if hyphens failed
                    if '_' not in pkg_name and '-' in pkg_name:
                        pypi_name = pkg_name.replace('-', '_')
                        pkg_info = pypi_client.get_package_info(pypi_name)
                
                if pkg_info:
                    # Normalize package name to prevent duplicates (case-insensitive)
                    normalized_name = pkg_info.name.lower()
                    
                    # Check if package already exists (case-insensitive check)
                    existing = Package.objects.filter(
                        project=project,
                        name=normalized_name
                    ).first()
                    
                    if existing:
                        # Package exists - create dependency relationship
                        PackageDependency.objects.get_or_create(
                            package=package,
                            depends_on=existing,
                            defaults={'dependency_type': PackageDependency.DependencyType.BUILD}
                        )
                        if existing.id != package.id and existing.build_status in {
                            'not_built', 'failed', 'missing_packages', 'dep_build_pending'
                        }:
                            existing.build_status = 'pending'
                            existing.save(update_fields=['build_status'])
                            send_package_update(existing.id)
                            build_single_package_task.delay(existing.id)
                            log_package(
                                package_id,
                                'info',
                                f"Queued existing dependency for build: {existing.name}"
                            )
                        logger.debug(f"Package {normalized_name} already exists, created dependency relationship")
                        continue
                    
                    # Create new transitive dependency
                    new_package = Package.objects.create(
                        project=project,
                        name=normalized_name,
                        python_name=pkg_info.name,
                        version=pkg_info.version,
                        package_type='dependency',
                        is_direct_dependency=False,
                        summary=pkg_info.summary[:500] if pkg_info.summary else '',
                        description=pkg_info.description[:1000] if pkg_info.description else '',
                        homepage=pkg_info.home_page[:500] if pkg_info.home_page else '',
                        license=pkg_info.license[:100] if pkg_info.license else '',
                    )
                    
                    # Record dependency relationship (package depends on new_package)
                    PackageDependency.objects.get_or_create(
                        package=package,
                        depends_on=new_package,
                        defaults={'dependency_type': PackageDependency.DependencyType.BUILD}
                    )
                    
                    added_count += 1
                    logger.info(f"Auto-added transitive dependency: {normalized_name} v{pkg_info.version} for {package.name}")
                    log_package(package_id, 'info', f"Auto-added missing dependency: {normalized_name}")
                    
                    # Trigger spec generation for the new package, then auto-build it
                    from backend.apps.packages.tasks import generate_spec_file_task
                    generate_spec_file_task.delay(new_package.id, force=False, auto_build=True)
                else:
                    failed_count += 1
                    logger.warning(f"Could not find package {pkg_name} on PyPI")
                    
            except Exception as e:
                failed_count += 1
                logger.warning(f"Error adding package {pkg_name}: {e}")
        
        if added_count > 0:
            log_project(project.id, 'info', 
                f"Auto-added {added_count} missing dependencies as transitive deps for {package.name}")
            logger.info(f"Auto-added {added_count} packages, {failed_count} failed for package {package.name}")
            # New packages were added to project scope. Re-check packages stuck
            # in missing_packages so they can move to dep_build_pending/pending.
            refresh_missing_packages_state_task.delay(project.id)
        elif failed_count > 0:
            log_package(package_id, 'warning', 
                f"Could not auto-add {failed_count} missing dependencies (not found on PyPI or system packages)")
    
    except Package.DoesNotExist:
        logger.error(f"Package {package_id} not found in auto_add_missing_dependencies")
    except Exception as e:
        logger.exception(f"Error in auto_add_missing_dependencies for package {package_id}: {e}")


def trigger_waiting_builds(completed_package_id: int):
    """
    After a package build completes, check if any packages in waiting_for_deps
    or dep_build_pending state now have all their dependencies satisfied and can be built.
    """
    from backend.apps.packages.models import Package
    
    try:
        completed_pkg = Package.objects.get(id=completed_package_id)
        
        # --- Handle waiting_for_deps (explicit PackageDependency links) ---
        waiting_pkgs = Package.objects.filter(
            build_status='waiting_for_deps',
            dependencies__depends_on=completed_pkg
        ).distinct()
        
        for pkg in waiting_pkgs:
            # Check if ALL dependencies are now satisfied
            unbuilt = []
            for dep in pkg.dependencies.all():
                dep_pkg = dep.depends_on
                if dep_pkg and dep_pkg.build_status not in ['completed', 'not_required']:
                    unbuilt.append(dep_pkg.name)
            
            if not unbuilt:
                # All deps ready — trigger the build
                logger.info(f"All deps satisfied for {pkg.name} (id={pkg.id}), triggering build")
                log_package(pkg.id, 'info', f"All dependencies are now built, starting build...")
                build_single_package_task.delay(pkg.id)
            else:
                logger.debug(f"{pkg.name} still waiting for: {unbuilt}")

        # --- Handle dependency-blocked packages inferred from analyzed missing deps ---
        # Include both dep_build_pending and missing_packages. A package may have
        # been marked missing_packages even though the blocker already exists in
        # project scope; when that blocker completes, wake it up here.
        dep_pending_pkgs = Package.objects.filter(
            project=completed_pkg.project,
            build_status__in=['dep_build_pending', 'missing_packages'],
        ).exclude(id=completed_pkg.id)

        for pkg in dep_pending_pkgs:
            missing_cats = {
                'Missing Packages', 'Missing Dependencies', 'Missing Python Modules',
                'Missing Header Files', 'Missing Rust/Cargo', 'Missing Python Wheel', 'Missing GCC'
            }
            missing_items = []
            for e in (pkg.analyzed_errors or []):
                if e.get('category') in missing_cats:
                    missing_items.extend(e.get('items', []))

            # Ignore self-referential dependency items.
            missing_items = [i for i in missing_items if not _is_self_dependency_item(pkg, i)]
            if not missing_items:
                continue

            # Check if the completed package name is one of the blockers
            blocker_names = set()
            for item in missing_items:
                for name in _normalize_dep_names(item):
                    blocker_names.add(name.lower())
            if completed_pkg.name.lower() not in blocker_names:
                continue  # Not related to this package

            # Re-evaluate all blockers; only wake when every missing item is resolved.
            resolution = _analyze_missing_item_resolution(pkg, completed_pkg.project, missing_items)
            unresolved_items = (
                resolution['unresolved_with_project_match']
                + resolution['unresolved_without_project_match']
            )
            if not unresolved_items:
                logger.info(f"All dependency blockers resolved for {pkg.name}, triggering build")
                log_package(pkg.id, 'info',
                    f"{completed_pkg.name} is now built — all blockers resolved, starting build...")
                pkg.build_status = 'pending'
                pkg.save()
                send_package_update(pkg.id)
                build_single_package_task.delay(pkg.id)
            else:
                remaining = ', '.join(unresolved_items)
                logger.debug(f"{pkg.name} still waiting for dependency blockers: {remaining}")

    except Package.DoesNotExist:
        logger.error(f"Package {completed_package_id} not found in trigger_waiting_builds")
    except Exception as e:
        logger.exception(f"Error in trigger_waiting_builds for {completed_package_id}: {e}")


@shared_task
def refresh_missing_packages_state_task(project_id: int):
    """
    Re-evaluate packages currently in missing_packages when project packages change.

    This is invoked when new packages are added so blocked packages can transition
    promptly instead of waiting for periodic monitors.
    """
    from backend.apps.projects.models import Project
    from backend.apps.packages.models import Package

    try:
        project = Project.objects.get(id=project_id)
        blocked_qs = Package.objects.filter(
            project=project,
            build_status__in=['missing_packages', 'failed'],
        )

        moved_to_dep_pending = 0
        moved_to_pending = 0

        for pkg in blocked_qs:
            missing_cats = {
                'Missing Packages', 'Missing Dependencies', 'Missing Python Modules',
                'Missing Header Files', 'Missing Rust/Cargo', 'Missing Python Wheel', 'Missing GCC'
            }
            missing_items = []
            for e in (pkg.analyzed_errors or []):
                if e.get('category') in missing_cats:
                    missing_items.extend(e.get('items', []))

            missing_items = [i for i in missing_items if not _is_self_dependency_item(pkg, i)]
            if not missing_items:
                continue

            # Re-evaluate using the same resolver that classifies missing deps.
            target_status = _resolve_missing_dep_status(pkg, project)

            if target_status == 'dep_build_pending' and pkg.build_status != 'dep_build_pending':
                pkg.build_status = 'dep_build_pending'
                pkg.save(update_fields=['build_status'])
                send_package_update(pkg.id)
                moved_to_dep_pending += 1
                log_package(pkg.id, 'info',
                    'Re-evaluated failed missing-deps state after package updates; marked dependency-pending')
                continue

            if target_status == 'missing_packages' and pkg.build_status != 'missing_packages':
                pkg.build_status = 'missing_packages'
                pkg.save(update_fields=['build_status'])
                send_package_update(pkg.id)
                log_package(pkg.id, 'info',
                    'Re-evaluated failed state and marked as missing packages')
                continue

            resolution = _analyze_missing_item_resolution(pkg, project, missing_items)
            unresolved_with_project = resolution['unresolved_with_project_match']
            unresolved_without_project = resolution['unresolved_without_project_match']

            if unresolved_with_project and not unresolved_without_project:
                if pkg.build_status != 'dep_build_pending':
                    pkg.build_status = 'dep_build_pending'
                    pkg.save(update_fields=['build_status'])
                    send_package_update(pkg.id)
                    moved_to_dep_pending += 1
                    log_package(pkg.id, 'info',
                        'Discovered project-matching missing deps after package add; marked dependency-pending')
                continue

            if not unresolved_with_project and not unresolved_without_project:
                pkg.build_status = 'pending'
                pkg.save(update_fields=['build_status'])
                send_package_update(pkg.id)
                build_single_package_task.delay(pkg.id)
                moved_to_pending += 1
                log_package(pkg.id, 'info',
                    'Previously missing deps are now available after package add; queued build')

        if moved_to_dep_pending or moved_to_pending:
            logger.info(
                f"refresh_missing_packages_state_task({project_id}): "
                f"dep_build_pending={moved_to_dep_pending}, pending={moved_to_pending}"
            )
        return {
            'project_id': project_id,
            'dep_build_pending': moved_to_dep_pending,
            'pending': moved_to_pending,
        }

    except Project.DoesNotExist:
        logger.error(f"Project {project_id} not found in refresh_missing_packages_state_task")
    except Exception as e:
        logger.exception(f"Error in refresh_missing_packages_state_task for {project_id}: {e}")


@shared_task(bind=True, max_retries=3)
def fix_and_rebuild_task(self, package_id: int):
    """
    Apply automated spec fixes for known error categories, then trigger a build.
    If no auto-fixable errors are found the build is triggered anyway (re-try).
    """
    from django.utils import timezone
    from backend.apps.packages.models import Package, SpecFileRevision
    from backend.core.spec_fixer import SpecFixer, has_auto_fix

    try:
        package = Package.objects.select_related('project').get(id=package_id)

        spec_revision = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()

        if not spec_revision:
            log_package(package_id, 'error', 'No spec file found — cannot apply fixes')
            return

        send_package_update(package_id)
        errors = package.analyzed_errors or []

        if has_auto_fix(errors):
            fixer = SpecFixer()
            new_content, fixes_applied = fixer.apply_fixes(spec_revision.content, errors)

            if fixes_applied:
                SpecFileRevision.objects.create(package=package, content=new_content)
                for fix in fixes_applied:
                    log_package(package_id, 'info', f'Auto-fix applied: {fix}')
                log_package(package_id, 'info',
                    f'{len(fixes_applied)} fix(es) applied — triggering rebuild')
            else:
                log_package(package_id, 'info',
                    'Auto-fix ran but made no changes — triggering rebuild anyway')
        else:
            log_package(package_id, 'info',
                'No auto-fixable errors found — triggering rebuild')

        # Always finish by triggering the actual build
        build_single_package_task.delay(package_id)

    except Package.DoesNotExist:
        logger.error(f'Package {package_id} not found in fix_and_rebuild_task')
    except Exception as e:
        logger.exception(f'Error in fix_and_rebuild_task for {package_id}: {e}')
        try:
            pkg = Package.objects.get(id=package_id)
            pkg.build_status = 'failed'
            pkg.build_completed_at = timezone.now()
            pkg.build_error_message = f'Fix & rebuild error: {e}'
            pkg.save()
            send_package_update(package_id)
        except Exception:
            pass

