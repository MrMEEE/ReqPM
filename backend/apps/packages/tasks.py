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
def generate_spec_file_task(self, package_id: int, force: bool = False):
    """
    Generate RPM spec file for a package
    
    Args:
        package_id: ID of the package
        force: Force regeneration even if spec file exists
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
        
        # Extract extras from provides_extra or requires_dist
        extras_data = {}
        info = data.get('info', {})
        
        # Method 1: provides_extra field (most reliable)
        provides_extra = info.get('provides_extra', [])
        for extra in provides_extra:
            extras_data[extra] = []
        
        # Method 2: Parse from requires_dist
        requires_dist = info.get('requires_dist', [])
        if requires_dist:
            for req in requires_dist:
                # Format: "package (>=version) ; extra == 'extra_name'"
                if 'extra ==' in req:
                    # Extract extra name
                    extra_part = req.split('extra ==')[1].strip()
                    extra_name = extra_part.strip('"').strip("'").split(')')[0].strip()
                    
                    # Extract dependency (before the semicolon)
                    dep = req.split(';')[0].strip()
                    
                    if extra_name not in extras_data:
                        extras_data[extra_name] = []
                    extras_data[extra_name].append(dep)
        
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
        
        log_message = f"Synced extras: {created_count} created, {updated_count} updated, {deleted_count} removed"
        log_package(package_id, 'info', log_message)
        logger.info(f"Package {package_id}: {log_message}")
        
        return {
            'created': created_count,
            'updated': updated_count,
            'deleted': deleted_count,
            'total': len(extras_data)
        }
    
    except requests.RequestException as e:
        log_package(package_id, 'error', f"Failed to fetch PyPI metadata: {str(e)}")
        logger.error(f"Error fetching PyPI metadata for package {package_id}: {e}")
        raise self.retry(exc=e, countdown=60)
    
    except Exception as e:
        log_package(package_id, 'error', f"Error syncing extras: {str(e)}")
        logger.error(f"Error syncing extras for package {package_id}: {e}")
        raise self.retry(exc=e, countdown=60)


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
        # Force regeneration to update existing specs
        generate_spec_file_task.delay(package.id, force=True)
    
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
def fetch_package_source_task(self, package_id: int):
    """
    Fetch source files for a package
    
    Args:
        package_id: ID of the package
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
                
                # Send WebSocket update to refresh UI with new source status
                send_package_update(package_id)
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
                package.build_status = 'failed'
                package.build_completed_at = timezone.now()
                package.build_error_message = f"Source directory not found: {sources_dir}. Sources must be fetched at project level before building."
                package.save()
                send_package_update(package_id)
                log_project(project.id, 'error', f"Build failed for {package.name}: Sources not found")
                log_package(package_id, 'error', "Sources not found")
                logger.error(f"Sources not found for {package.name} at {sources_dir}")
                return
            
            # Copy all source files to build directory (excluding .spec files)
            # Fix filename mismatches for PyPI packages during copy
            # PyPI downloads use normalized names (lowercase, underscores) but spec files
            # may reference the original package name (CamelCase, hyphens)
            # HOWEVER: For packages with dots or hyphens in the name, DON'T rename the tarball
            # because PyPI normalizes both the tarball AND directory names to underscores,
            # and renaming the tarball causes RPM spec macros to expect wrong directory names.
            logger.info(f"Copying sources for {package.name} from {sources_dir} to {build_dir}")
            import re
            try:
                # Check if package name has dots or hyphens - if so, don't rename tarballs
                has_special_chars = '.' in package.python_name or '-' in package.python_name
                
                for source_file in sources_dir.glob('*'):
                    if source_file.is_file() and source_file.suffix != '.spec':
                        # Check if this is a tarball that needs renaming
                        match = re.match(r'^(.+?)-(\d+.*?)\.tar\.gz$', source_file.name)
                        if match and source_file.suffix == '.gz' and not has_special_chars:
                            # Only rename if package name has NO dots or hyphens
                            tarball_pkg_name = match.group(1)
                            tarball_version = match.group(2)
                            
                            # If the tarball name doesn't match package.name, rename it during copy
                            if tarball_pkg_name != package.name:
                                expected_name = f"{package.name}-{tarball_version}.tar.gz"
                                dest_path = build_dir / expected_name
                                shutil.copy2(source_file, dest_path)
                                logger.info(f"Copied and renamed: {source_file.name} -> {expected_name}")
                                log_package(package_id, 'debug', f"Renamed source file: {source_file.name} -> {expected_name}")
                            else:
                                # Name matches, just copy
                                shutil.copy2(source_file, build_dir)
                                logger.debug(f"Copied {source_file.name}")
                        else:
                            # Not a tarball, doesn't match pattern, or package has dots/hyphens - just copy as-is
                            shutil.copy2(source_file, build_dir)
                            if has_special_chars and '.tar.gz' in source_file.name:
                                logger.info(f"Copied {source_file.name} without renaming (package has dots/hyphens)")
                                log_package(package_id, 'debug', f"Kept original filename: {source_file.name}")
                            else:
                                logger.debug(f"Copied {source_file.name}")
                            
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

            arch = 'x86_64'
            rpm_result = builder.build_rpm(
                srpm_path=srpm_result.srpm_path,
                output_dir=str(build_dir / 'RPMS'),
                target=target,
                arch=arch,
                unique_ext=f"pkg{package_id}",
                local_repo_dir=local_repo_dir,
            )
            
            # Fixer loop — keep applying rule-based and AI fixes until the build
            # succeeds, no fixer applies, or SRPM reconstruction fails.
            # _ai_fix_count tracks AI attempts this rebuild; AI's own max_attempts
            # setting caps how many AI revisions are created per build run.
            _ai_fix_count = 0
            _fix_attempt = 0
            _MAX_FIX_ATTEMPTS = 10  # safety cap
            while not rpm_result.success and _fix_attempt < _MAX_FIX_ATTEMPTS:
                fixed = False
                if _detect_and_fix_directory_mismatch(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_missing_build_files(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_unpackaged_files(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_wrong_module_glob(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_missing_header_files(package_id, rpm_result.log_output or ''):
                    fixed = True
                elif _detect_and_fix_spec_errors(package_id, rpm_result.log_output or ''):
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
            rpm_file = rpm_result.rpm_paths[0] if rpm_result.rpm_paths else None
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
    pyproject_save_files and fix the spec by replacing the bad glob with *.

    This happens for namespace packages (e.g. poetry-core installs as
    poetry/core/ not poetry_core/) where the dist-info name doesn't match
    the actual installed module directory.

    Returns True if the fix was applied, False otherwise.
    """
    import re
    from backend.apps.packages.models import Package, SpecFileRevision
    from backend.core.error_analyzer import BuildErrorAnalyzer
    from backend.core.spec_fixer import SpecFixer

    _GLOB_ERRORS = (
        'Globs did not match any module',
        'Attempted to use a namespaced package with . in the glob',
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

        analyzer = BuildErrorAnalyzer()
        errors = analyzer.analyze(build_log)
        fixer = SpecFixer()
        error_dicts = [
            {'category': e.category, 'items': e.items, 'message': e.message, 'suggestion': e.suggestion}
            for e in errors
        ]
        new_spec, fixes = fixer.apply_fixes(current_spec.content, error_dicts)

        if not fixes:
            logger.warning(f"SpecFixer produced no fixes for wrong module glob on {package.name}")
            return False

        SpecFileRevision.objects.create(
            package=package,
            content=new_spec,
            commit_message=f'Auto-fixed: replaced bad %pyproject_save_files glob with * ({"; ".join(fixes)})'
        )
        log_package(package_id, 'info', f'Auto-fixed spec: {"; ".join(fixes)}')
        return True

    except Exception as e:
        logger.error(f"Error in wrong_module_glob fix for package {package_id}: {e}")
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


def _detect_and_fix_with_ai(package_id: int, build_log: str, root_log: str = '', ai_attempt: int = 0) -> bool:
    """
    Last-resort fixer: ask the configured LLM (see settings.REQPM['AI_FIXER'])
    to propose structured fix actions for an unrecognized build failure.
    Returns True if a new spec revision was created (caller retries build).
    No-op when AI_FIXER is disabled.
    """
    try:
        from backend.core.ai_fixer import attempt_ai_fix, is_enabled
        if not is_enabled():
            return False
        log_package(package_id, 'info', 'Rule-based fixers exhausted, trying AI fixer...')
        result = attempt_ai_fix(package_id, build_log, root_log, ai_attempt=ai_attempt)
        send_package_update(package_id)
        if result:
            log_package(package_id, 'info', 'AI fixer proposed a spec fix, retrying build')
        else:
            log_package(package_id, 'info', 'AI fixer could not propose a fix')
        return result
    except Exception as e:
        logger.warning(f"Error in _detect_and_fix_with_ai for {package_id}: {e}")
        return False


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
    from pathlib import Path
    from django.conf import settings

    base = Path(settings.REQPM['BUILD_DIR']) / 'projects' / str(project_id)

    def _repo_dir_for_version(ver):
        label = f'el{ver}' if ver else 'common'
        d = base / label
        d.mkdir(parents=True, exist_ok=True)
        return d

    dirs_to_update = set()

    for rpm_path in (rpm_paths or []):
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
    # Strip leading/trailing parentheses and whitespace
    item = item.strip().strip('()')
    # Strip version constraints (handle 'with' keyword for complex constraints)
    item = re.split(r'\s+(with|[><=!])', item)[0].strip()
    # python3dist(foo-bar) or python3dist(foo_bar)
    m = re.match(r'python3?dist\(([^)]+)\)', item, re.IGNORECASE)
    if m:
        pkg_name = m.group(1).replace('_', '-').lower()
        return [f'python3-{pkg_name}', pkg_name]
    # python3(foo)
    m = re.match(r'python3?\(([^)]+)\)', item, re.IGNORECASE)
    if m:
        pkg_name = m.group(1).replace('_', '-').lower()
        return [f'python3-{pkg_name}', pkg_name]
    # Already a plain name
    return [item.strip(), item.strip().replace('_', '-')]


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

    if not missing_items:
        return 'missing_packages'

    matched = _find_project_packages_for_items(project, missing_items)
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

    if unbuilt_matches or stale_matches:
        names = ', '.join(p.name for p in unbuilt_matches + stale_matches)
        log_package(package.id, 'info',
            f"Missing deps found as unbuilt project packages: {names} — waiting for them")
        return 'dep_build_pending'

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
                    
                    # Trigger spec generation for the new package
                    from backend.apps.packages.tasks import generate_spec_file_task
                    generate_spec_file_task.delay(new_package.id, force=False)
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

        # --- Handle dep_build_pending (missing dep items matched to project packages) ---
        dep_pending_pkgs = Package.objects.filter(
            project=completed_pkg.project,
            build_status='dep_build_pending',
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

            if not missing_items:
                continue

            # Check if the completed package name is one of the blockers
            blocker_names = set()
            for item in missing_items:
                for name in _normalize_dep_names(item):
                    blocker_names.add(name.lower())
            if completed_pkg.name.lower() not in blocker_names:
                continue  # Not related to this package

            # Re-evaluate all blockers
            matched = _find_project_packages_for_items(completed_pkg.project, missing_items)
            unresolved = [
                p for p in matched
                if p.build_status not in ('completed', 'not_required') and p.id != pkg.id
            ]
            if not unresolved:
                logger.info(f"All dep_build_pending blockers resolved for {pkg.name}, triggering build")
                log_package(pkg.id, 'info',
                    f"{completed_pkg.name} is now built — all blockers resolved, starting build...")
                pkg.build_status = 'pending'
                pkg.save()
                send_package_update(pkg.id)
                build_single_package_task.delay(pkg.id)
            else:
                remaining = ', '.join(p.name for p in unresolved)
                logger.debug(f"{pkg.name} dep_build_pending still waiting for: {remaining}")

    except Package.DoesNotExist:
        logger.error(f"Package {completed_package_id} not found in trigger_waiting_builds")
    except Exception as e:
        logger.exception(f"Error in trigger_waiting_builds for {completed_package_id}: {e}")


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

