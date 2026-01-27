"""
Celery tasks for package operations
"""
from celery import shared_task
from django.conf import settings
import logging

from backend.core.spec_generator import SpecFileGenerator
from backend.core.pypi_client import PyPIClient

logger = logging.getLogger(__name__)


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
    try:
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
