"""
Celery tasks for package operations
"""
from celery import shared_task
from django.conf import settings
import logging

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
            
            # Generate spec file with project's Python version
            log_package(package_id, 'debug', f"Generating RPM spec file for version {pkg_info.version} with Python {python_version}...")
            spec_content = spec_gen.generate_spec(
                package_name=package.name,
                version=pkg_info.version,
                python_version=python_version,
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
            
            # Write spec file
            spec_file = build_dir / f"{package.name}.spec"
            spec_file.write_text(spec_revision.content)
            
            # Copy sources from project source directory to build directory
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
            
            # Copy all source files to build directory
            logger.info(f"Copying sources for {package.name} from {sources_dir} to {build_dir}")
            try:
                for source_file in sources_dir.glob('*'):
                    if source_file.is_file():
                        shutil.copy2(source_file, build_dir)
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
                package.build_status = 'failed'
                package.build_completed_at = timezone.now()
                package.build_error_message = f"SRPM build failed: {srpm_result.error_message}"
                package.build_log = srpm_result.log_output
                # Analyze build log for structured errors
                try:
                    analyzer = BuildErrorAnalyzer()
                    errors = analyzer.analyze(srpm_result.log_output or '')
                    package.analyzed_errors = [
                        {'category': e.category, 'message': e.message, 'suggestion': e.suggestion, 'items': e.items}
                        for e in errors
                    ]
                except Exception as analyze_err:
                    logger.warning(f"Error analyzing build log for {package.name}: {analyze_err}")
                    package.analyzed_errors = []
                package.save()
                send_package_update(package_id)
                log_project(project.id, 'error', f"Build failed for {package.name}: SRPM build failed")
                log_package(package_id, 'error', f"SRPM build failed: {srpm_result.error_message}")
                logger.error(f"SRPM build failed for {package.name}: {srpm_result.error_message}")
                return
            
            # Build RPM
            logger.info(f"Building RPM for {package.name}")
            log_package(package_id, 'info', "Building RPM...")
            
            arch = 'x86_64'
            rpm_result = builder.build_rpm(
                srpm_path=srpm_result.srpm_path,
                output_dir=str(build_dir / 'RPMS'),
                target=target,
                arch=arch,
                unique_ext=f"pkg{package_id}"
            )
            
            if not rpm_result.success:
                package.build_status = 'failed'
                package.build_completed_at = timezone.now()
                package.build_error_message = f"RPM build failed: {rpm_result.error_message}"
                package.build_log = rpm_result.log_output
                # Analyze build log for structured errors
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


def trigger_waiting_builds(completed_package_id: int):
    """
    After a package build completes, check if any packages in waiting_for_deps
    state now have all their dependencies satisfied and can be built.
    """
    from backend.apps.packages.models import Package
    
    try:
        completed_pkg = Package.objects.get(id=completed_package_id)
        
        # Find packages that depend on the completed one and are waiting
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
    except Package.DoesNotExist:
        logger.error(f"Package {completed_package_id} not found in trigger_waiting_builds")
    except Exception as e:
        logger.exception(f"Error in trigger_waiting_builds for {completed_package_id}: {e}")

