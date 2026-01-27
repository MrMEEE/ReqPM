"""
Celery tasks for repository operations
"""
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from pathlib import Path
import logging

from backend.plugins.repositories import get_repository_manager

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def create_repository_task(self, repository_id: int):
    """
    Create a new YUM/DNF repository
    
    Args:
        repository_id: ID of the repository
    """
    try:
        from backend.apps.repositories.models import Repository
        
        repository = Repository.objects.get(id=repository_id)
        
        # Get repository manager
        repo_manager = get_repository_manager('createrepo')
        
        if not repo_manager or not repo_manager.is_available():
            logger.error("Repository manager not available")
            return
        
        # Ensure repository directory exists
        repo_path = Path(repository.repo_path)
        repo_path.mkdir(parents=True, exist_ok=True)
        
        # Create repository
        success, error = repo_manager.create_repository(
            repo_path=str(repo_path),
            description=repository.description or f"Repository for {repository.project.name}"
        )
        
        if not success:
            logger.error(f"Failed to create repository {repository_id}: {error}")
            return
        
        # Update repository metadata
        update_repository_metadata_task.delay(repository_id)
        
        logger.info(f"Created repository {repository_id}")
    
    except Exception as e:
        logger.error(f"Error creating repository {repository_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def add_package_to_repository_task(self, repository_id: int, package_build_id: int):
    """
    Add a built package to a repository
    
    Args:
        repository_id: ID of the repository
        package_build_id: ID of the PackageBuild
    """
    try:
        from backend.apps.repositories.models import Repository, RepositoryPackage
        from backend.apps.packages.models import PackageBuild
        
        repository = Repository.objects.get(id=repository_id)
        package_build = PackageBuild.objects.get(id=package_build_id)
        
        # Get repository manager
        repo_manager = get_repository_manager('createrepo')
        
        if not repo_manager or not repo_manager.is_available():
            logger.error("Repository manager not available")
            return
        
        # Add package to repository
        success, error = repo_manager.add_package(
            repo_path=repository.repo_path,
            package_path=package_build.rpm_file
        )
        
        if not success:
            logger.error(f"Failed to add package to repository {repository_id}: {error}")
            return
        
        # Create RepositoryPackage record
        RepositoryPackage.objects.create(
            repository=repository,
            package_build=package_build,
            added_at=timezone.now()
        )
        
        logger.info(f"Added package {package_build.package.name} to repository {repository_id}")
        
        # Update repository metadata
        update_repository_metadata_task.delay(repository_id)
    
    except Exception as e:
        logger.error(f"Error adding package to repository {repository_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def remove_package_from_repository_task(self, repository_id: int, package_name: str):
    """
    Remove a package from a repository
    
    Args:
        repository_id: ID of the repository
        package_name: Name of the package RPM file
    """
    try:
        from backend.apps.repositories.models import Repository, RepositoryPackage
        
        repository = Repository.objects.get(id=repository_id)
        
        # Get repository manager
        repo_manager = get_repository_manager('createrepo')
        
        if not repo_manager or not repo_manager.is_available():
            logger.error("Repository manager not available")
            return
        
        # Remove package from repository
        success, error = repo_manager.remove_package(
            repo_path=repository.repo_path,
            package_name=package_name
        )
        
        if not success:
            logger.error(f"Failed to remove package from repository {repository_id}: {error}")
            return
        
        # Remove RepositoryPackage record
        RepositoryPackage.objects.filter(
            repository=repository,
            package_build__rpm_file__contains=package_name
        ).delete()
        
        logger.info(f"Removed package {package_name} from repository {repository_id}")
        
        # Update repository metadata
        update_repository_metadata_task.delay(repository_id)
    
    except Exception as e:
        logger.error(f"Error removing package from repository {repository_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def update_repository_metadata_task(self, repository_id: int):
    """
    Update repository metadata
    
    Args:
        repository_id: ID of the repository
    """
    try:
        from backend.apps.repositories.models import Repository, RepositoryMetadata
        
        repository = Repository.objects.get(id=repository_id)
        
        # Get repository manager
        repo_manager = get_repository_manager('createrepo')
        
        if not repo_manager or not repo_manager.is_available():
            logger.error("Repository manager not available")
            return
        
        # Get repository info
        repo_info = repo_manager.get_repository_info(repository.repo_path)
        
        if not repo_info:
            logger.error(f"Could not get info for repository {repository_id}")
            return
        
        # Update or create metadata record
        metadata, created = RepositoryMetadata.objects.update_or_create(
            repository=repository,
            defaults={
                'package_count': repo_info.package_count,
                'last_updated': repo_info.last_updated,
                'revision': repo_info.revision or '',
                'checksum': repo_info.checksum or ''
            }
        )
        
        logger.info(f"Updated metadata for repository {repository_id}")
    
    except Exception as e:
        logger.error(f"Error updating metadata for repository {repository_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def publish_build_to_repository_task(self, build_job_id: int, repository_id: int):
    """
    Publish all successful builds from a build job to a repository
    
    Args:
        build_job_id: ID of the build job
        repository_id: ID of the repository
    """
    try:
        from backend.apps.builds.models import BuildJob, BuildQueue
        
        build_job = BuildJob.objects.get(id=build_job_id)
        
        # Get all successful builds
        successful_builds = BuildQueue.objects.filter(
            build_job=build_job,
            status='completed'
        ).select_related('package')
        
        if not successful_builds.exists():
            logger.warning(f"No successful builds found for build job {build_job_id}")
            return
        
        # Add each package to repository
        for build in successful_builds:
            # Get the PackageBuild record
            from backend.apps.packages.models import PackageBuild
            
            package_build = PackageBuild.objects.filter(
                package=build.package,
                rhel_version=build.rhel_version
            ).order_by('-built_at').first()
            
            if package_build:
                add_package_to_repository_task.delay(repository_id, package_build.id)
        
        logger.info(f"Publishing {successful_builds.count()} packages from build job {build_job_id} to repository {repository_id}")
    
    except Exception as e:
        logger.error(f"Error publishing build job {build_job_id} to repository: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def sign_repository_task(self, repository_id: int, gpg_key_id: str):
    """
    Sign repository packages with GPG key
    
    Args:
        repository_id: ID of the repository
        gpg_key_id: GPG key ID to use for signing
    """
    try:
        from backend.apps.repositories.models import Repository
        
        repository = Repository.objects.get(id=repository_id)
        
        # Get repository manager
        repo_manager = get_repository_manager('createrepo')
        
        if not repo_manager or not repo_manager.is_available():
            logger.error("Repository manager not available")
            return
        
        # Sign repository
        success, error = repo_manager.sign_repository(
            repo_path=repository.repo_path,
            gpg_key_id=gpg_key_id
        )
        
        if not success:
            logger.error(f"Failed to sign repository {repository_id}: {error}")
            return
        
        repository.gpg_key_id = gpg_key_id
        repository.save()
        
        logger.info(f"Signed repository {repository_id} with key {gpg_key_id}")
    
    except Exception as e:
        logger.error(f"Error signing repository {repository_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task
def sync_all_repositories_task():
    """
    Update metadata for all active repositories
    """
    from backend.apps.repositories.models import Repository
    
    repositories = Repository.objects.all()
    
    for repository in repositories:
        update_repository_metadata_task.delay(repository.id)
    
    logger.info(f"Triggered metadata sync for {repositories.count()} repositories")
