"""
Celery tasks for build operations
"""
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from pathlib import Path
import logging

from backend.plugins.builders import get_builder
from backend.plugins.builders.base import BuildResult
from backend.apps.builds.concurrency import limiter

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def build_package_task(self, build_queue_id: int):
    """
    Build a single package
    
    Args:
        build_queue_id: ID of the BuildQueue entry
    """
    try:
        from backend.apps.builds.models import BuildQueue, BuildJob
        from backend.apps.packages.models import PackageBuild, SpecFileRevision
        
        queue_item = BuildQueue.objects.get(id=build_queue_id)
        
        # Acquire build slot with concurrency limiting
        try:
            with limiter.acquire(f"build_{build_queue_id}", timeout=300):  # Wait up to 5 min for slot
                # Clear previous build logs and errors
                queue_item.status = 'building'
                queue_item.started_at = timezone.now()
                queue_item.build_log = ''
                queue_item.error_message = ''
                queue_item.analyzed_errors = []
                queue_item.save()
                
                package = queue_item.package
                build_job = queue_item.build_job
                rhel_version = queue_item.rhel_version
                
                # Get builder
                builder = get_builder('mock')
                
                if not builder or not builder.is_available():
                    queue_item.status = 'failed'
                    queue_item.error_message = (
                        "Mock builder is not available. "
                        "Mock is required for building RPM packages. "
                        "Please install Mock: sudo dnf install mock && sudo usermod -a -G mock $USER\n"
                        "See docs/MOCK_SETUP.md for complete setup instructions."
                    )
                    queue_item.save()
                    logger.error(f"Mock builder not available for build {build_queue_id}")
                    return
                
                # Get spec file
                spec_revision = SpecFileRevision.objects.filter(
                    package=package
                ).order_by('-created_at').first()
                
                if not spec_revision:
                    queue_item.status = 'failed'
                    queue_item.error_message = "No spec file found"
                    queue_item.save()
                    logger.error(f"No spec file for package {package.id}")
                    return
                
                # Prepare build directory
                build_dir = Path(settings.REQPM['BUILD_DIR']) / str(build_job.id) / package.name
                build_dir.mkdir(parents=True, exist_ok=True)
                
                # Write spec file
                spec_file = build_dir / f"{package.name}.spec"
                spec_file.write_text(spec_revision.content)
                
                # Fetch sources using spectool
                logger.info(f"Fetching sources for {package.name}")
                fetch_result = builder.fetch_sources(
                    spec_file=str(spec_file),
                    sources_dir=str(build_dir)
                )
                
                if not fetch_result.success:
                    queue_item.status = 'failed'
                    queue_item.error_message = f"Source fetching failed: {fetch_result.error_message}"
                    queue_item.build_log = fetch_result.log_output
                    queue_item.analyze_build_log()
                    queue_item.save()
                    
                    # Log to package logs
                    from backend.apps.packages.tasks import log_package
                    log_package(package.id, 'error', f"Build failed for RHEL {rhel_version}: Source fetching failed")
                    
                    logger.error(f"Source fetching failed for {package.name}: {fetch_result.error_message}")
                    return
                
                # Auto-derive mock config from RHEL version
                target = f"rhel-{rhel_version}-x86_64"
                
                logger.info(f"Building {package.name} with Mock config: {target}")
                
                # Validate target
                if not builder.validate_target(target):
                    queue_item.status = 'failed'
                    queue_item.error_message = f"Invalid build target: {target}"
                    queue_item.save()
                    logger.error(f"Invalid target {target} for build {build_queue_id}")
                    return
                
                # Build SRPM first
                logger.info(f"Building SRPM for {package.name}")
                srpm_result = builder.build_srpm(
                    spec_file=str(spec_file),
                    sources_dir=str(build_dir),
                    output_dir=str(build_dir / 'SRPMS'),
                    target=target
                )
                
                if not srpm_result.success:
                    queue_item.status = 'failed'
                    queue_item.error_message = f"SRPM build failed: {srpm_result.error_message}"
                    queue_item.build_log = srpm_result.log_output
                    queue_item.analyze_build_log()
                    queue_item.save()
                    
                    # Log to package logs
                    from backend.apps.packages.tasks import log_package
                    log_package(package.id, 'error', f"Build failed for RHEL {rhel_version}: SRPM build failed")
                    
                    logger.error(f"SRPM build failed for {package.name}: {srpm_result.error_message}")
                    return
                
                # Build RPM
                logger.info(f"Building RPM for {package.name}")
                arch = 'x86_64'
                rpm_result = builder.build_rpm(
                    srpm_path=srpm_result.srpm_path,
                    output_dir=str(build_dir / 'RPMS'),
                    target=target,
                    arch=arch,
                    unique_ext=f"build{build_queue_id}"
                )
                
                if not rpm_result.success:
                    queue_item.status = 'failed'
                    queue_item.error_message = f"RPM build failed: {rpm_result.error_message}"
                    queue_item.build_log = rpm_result.log_output
                    queue_item.analyze_build_log()
                    queue_item.save()
                    
                    # Log to package logs
                    from backend.apps.packages.tasks import log_package
                    log_package(package.id, 'error', f"Build failed for RHEL {rhel_version}: RPM build failed")
                    
                    logger.error(f"RPM build failed for {package.name}: {rpm_result.error_message}")
                    return
                
                # Create or update PackageBuild record
                rpm_file = rpm_result.rpm_paths[0] if rpm_result.rpm_paths else None
                
                # Determine mock config from target
                mock_config = target
                
                package_build, created = PackageBuild.objects.update_or_create(
                    package=package,
                    rhel_version=rhel_version,
                    architecture=arch,
                    defaults={
                        'mock_config': mock_config,
                        'srpm_path': srpm_result.srpm_path,
                        'rpm_paths': rpm_result.rpm_paths if rpm_result.rpm_paths else [],
                        'build_log': rpm_result.log_output,
                        'status': 'completed',
                        'completed_at': timezone.now()
                    }
                )
                
                # Update queue item
                queue_item.status = 'completed'
                queue_item.completed_at = timezone.now()
                queue_item.build_log = rpm_result.log_output
                queue_item.srpm_path = srpm_result.srpm_path
                queue_item.rpm_path = rpm_file
                queue_item.save()
                
                # Log success to package logs
                from backend.apps.packages.tasks import log_package
                log_package(package.id, 'info', f"Build succeeded for RHEL {rhel_version}")
                
                logger.info(f"Successfully built package {package.name} for {rhel_version}")
                
                # Check if all packages in build job are complete
                check_build_job_completion.delay(build_job.id)
        
        except TimeoutError as e:
            # Could not acquire build slot
            queue_item.status = 'failed'
            queue_item.error_message = str(e)
            queue_item.save()
            logger.warning(f"Build {build_queue_id} could not acquire slot: {e}")
            return
    
    except Exception as e:
        from backend.apps.builds.models import BuildQueue
        queue_item = BuildQueue.objects.get(id=build_queue_id)
        queue_item.status = 'failed'
        queue_item.error_message = str(e)
        queue_item.save()
        logger.error(f"Error building package {build_queue_id}: {e}")
        raise self.retry(exc=e, countdown=60)
        queue_item.error_message = str(e)
        queue_item.save()
        logger.error(f"Error building package {build_queue_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def create_build_job_task(self, project_id: int, rhel_versions: list, triggered_by_id: int = None):
    """
    Create a build job for a project
    
    Args:
        project_id: ID of the project
        rhel_versions: List of RHEL versions to build for
        triggered_by_id: ID of user who triggered the build
    """
    try:
        from backend.apps.builds.models import BuildJob, BuildQueue
        from backend.apps.packages.models import Package
        from backend.apps.projects.models import Project
        from backend.apps.users.models import User
        
        project = Project.objects.get(id=project_id)
        triggered_by = User.objects.get(id=triggered_by_id) if triggered_by_id else None
        
        # Create build job
        build_job = BuildJob.objects.create(
            project=project,
            rhel_versions=rhel_versions,
            triggered_by=triggered_by,
            status='pending'
        )
        
        # Get all packages ordered by build_order
        packages = Package.objects.filter(
            project=project
        ).order_by('build_order', 'name')
        
        # Create build queue items
        total_builds = 0
        for package in packages:
            for rhel_version in rhel_versions:
                BuildQueue.objects.create(
                    build_job=build_job,
                    package=package,
                    rhel_version=rhel_version,
                    status='pending'
                )
                total_builds += 1
        
        build_job.total_packages = len(packages)
        build_job.save()
        
        logger.info(f"Created build job {build_job.id} with {total_builds} builds")
        
        # Start building
        process_build_queue.delay(build_job.id)
    
    except Exception as e:
        logger.error(f"Error creating build job for project {project_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task
def process_build_queue(build_job_id: int):
    """
    Process build queue for a build job
    
    Args:
        build_job_id: ID of the build job
    """
    from backend.apps.builds.models import BuildJob, BuildQueue
    
    try:
        build_job = BuildJob.objects.get(id=build_job_id)
        build_job.status = 'building'
        build_job.started_at = timezone.now()
        build_job.save()
        
        # Get pending builds ordered by package build_order
        pending_builds = BuildQueue.objects.filter(
            build_job=build_job,
            status='pending'
        ).select_related('package').order_by('package__build_order', 'package__name')
        
        # Start builds for packages at the lowest build order level
        # This allows building independent packages in parallel
        if pending_builds.exists():
            min_order = pending_builds.first().package.build_order
            builds_to_start = pending_builds.filter(package__build_order=min_order)
            
            for build in builds_to_start:
                build_package_task.delay(build.id)
            
            logger.info(f"Started {builds_to_start.count()} builds for build job {build_job_id}")
    
    except Exception as e:
        logger.error(f"Error processing build queue for job {build_job_id}: {e}")


@shared_task
def check_build_job_completion(build_job_id: int):
    """
    Check if a build job is complete
    
    Args:
        build_job_id: ID of the build job
    """
    from backend.apps.builds.models import BuildJob, BuildQueue
    
    try:
        build_job = BuildJob.objects.get(id=build_job_id)
        
        # Get build statistics
        total = BuildQueue.objects.filter(build_job=build_job).count()
        completed = BuildQueue.objects.filter(build_job=build_job, status='completed').count()
        failed = BuildQueue.objects.filter(build_job=build_job, status='failed').count()
        pending = BuildQueue.objects.filter(build_job=build_job, status='pending').count()
        building = BuildQueue.objects.filter(build_job=build_job, status='building').count()
        
        # Update progress
        if total > 0:
            build_job.built_packages = completed
            build_job.failed_packages = failed
            build_job.progress = int((completed + failed) / total * 100)
            build_job.save()
        
        # Check if all builds are done
        if pending == 0 and building == 0:
            if failed > 0:
                build_job.status = 'failed'
            else:
                build_job.status = 'completed'
            
            build_job.completed_at = timezone.now()
            build_job.save()
            
            logger.info(f"Build job {build_job_id} completed: {completed} successful, {failed} failed")
        else:
            # Continue processing queue
            process_build_queue.delay(build_job_id)
    
    except Exception as e:
        logger.error(f"Error checking completion for build job {build_job_id}: {e}")


@shared_task
def cleanup_old_builds_task(days: int = 30):
    """
    Clean up old build artifacts
    
    Args:
        days: Remove builds older than this many days
    """
    from datetime import timedelta
    from backend.apps.builds.models import BuildJob
    import shutil
    
    cutoff_date = timezone.now() - timedelta(days=days)
    old_builds = BuildJob.objects.filter(
        completed_at__lt=cutoff_date,
        status__in=['completed', 'failed']
    )
    
    for build_job in old_builds:
        # Clean up build directory
        build_dir = Path(settings.REQPM['BUILD_DIR']) / str(build_job.id)
        if build_dir.exists():
            shutil.rmtree(build_dir)
            logger.info(f"Cleaned up build directory for job {build_job.id}")
    
    logger.info(f"Cleaned up {old_builds.count()} old build jobs")


@shared_task
def monitor_pending_builds():
    """
    Monitor and trigger pending builds that haven't started.
    This task runs periodically to ensure no builds get stuck in pending state.
    """
    from backend.apps.builds.models import BuildQueue
    from celery import current_app
    
    # Get all pending builds that have been pending for more than 30 seconds
    # (to avoid triggering builds that were just created)
    from datetime import timedelta
    threshold_time = timezone.now() - timedelta(seconds=30)
    
    pending_items = BuildQueue.objects.filter(
        status='pending',
        created_at__lt=threshold_time,
        started_at__isnull=True
    )
    
    if not pending_items.exists():
        return
    
    # Check if these builds have active Celery tasks
    inspector = current_app.control.inspect()
    active_tasks = inspector.active()
    reserved_tasks = inspector.reserved()
    
    # Get all active/reserved task IDs for build_package_task
    active_build_ids = set()
    if active_tasks:
        for worker_tasks in active_tasks.values():
            for task in worker_tasks:
                if task['name'] == 'backend.apps.builds.tasks.build_package_task':
                    # Extract build_queue_id from task args
                    if task.get('args'):
                        active_build_ids.add(task['args'][0])
    
    if reserved_tasks:
        for worker_tasks in reserved_tasks.values():
            for task in worker_tasks:
                if task['name'] == 'backend.apps.builds.tasks.build_package_task':
                    if task.get('args'):
                        active_build_ids.add(task['args'][0])
    
    # Trigger builds for items without active tasks
    triggered_count = 0
    for queue_item in pending_items:
        if queue_item.id not in active_build_ids:
            logger.info(f"Triggering stuck pending build for queue item {queue_item.id}")
            build_package_task.delay(queue_item.id)
            triggered_count += 1
    
    if triggered_count > 0:
        logger.info(f"Triggered {triggered_count} stuck pending builds")

