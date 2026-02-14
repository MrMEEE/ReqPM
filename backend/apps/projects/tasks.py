"""
Celery tasks for project operations
"""
import os
from celery import shared_task
from django.conf import settings
from django.utils import timezone
import logging

from backend.core.git_manager import GitManager
from backend.core.requirements_parser import RequirementsParser, DependencyResolver
from backend.apps.projects.models import Project, ProjectBranch, ProjectLog

logger = logging.getLogger(__name__)


def log_project(project_id: int, level: str, message: str):
    """
    Helper function to log project messages
    
    Args:
        project_id: ID of the project
        level: Log level (debug, info, warning, error)
        message: Log message
    """
    try:
        ProjectLog.objects.create(
            project_id=project_id,
            level=level,
            message=message
        )
    except Exception as e:
        logger.error(f"Failed to create project log: {e}")



@shared_task(bind=True, max_retries=3)
def clone_project_task(self, project_id: int):
    """
    Clone or update a Git repository for a project
    
    Args:
        project_id: ID of the project to clone
    """
    try:
        project = Project.objects.get(id=project_id)
        project.status = 'cloning'
        project.save()
        
        log_project(project_id, 'info', f"Starting clone of repository: {project.git_url}")
        
        # Initialize Git manager
        git_manager = GitManager(settings.REQPM['GIT_CACHE_DIR'])
        
        # Clone or update repository
        log_project(project_id, 'info', f"Cloning branch '{project.git_branch}'...")
        success, repo_path, error = git_manager.clone_or_update(
            url=project.git_url,
            branch=project.git_branch,
            tag=project.git_tag,
            ssh_key=project.git_ssh_key,
            api_token=project.git_api_token
        )
        
        if not success:
            project.status = 'failed'
            project.status_message = f"Git clone failed: {error}"
            project.save()
            log_project(project_id, 'error', f"Clone failed: {error}")
            logger.error(f"Failed to clone project {project_id}: {error}")
            return
        
        log_project(project_id, 'info', f"Repository cloned successfully to {repo_path}")
        
        # Get current commit hash
        commit_hash = git_manager.get_commit_hash(repo_path)
        if commit_hash:
            project.git_commit = commit_hash
            log_project(project_id, 'info', f"Current commit: {commit_hash[:8]}")
        
        # Update branches and tags
        log_project(project_id, 'info', "Fetching branches and tags...")
        branches, tags = git_manager.get_branches_and_tags(repo_path)
        
        # Store branches
        for branch_name in branches:
            ProjectBranch.objects.update_or_create(
                project=project,
                name=branch_name,
                defaults={'is_tag': False, 'commit_hash': commit_hash or ''}
            )
        
        # Store tags
        for tag_name in tags:
            ProjectBranch.objects.update_or_create(
                project=project,
                name=tag_name,
                defaults={'is_tag': True, 'commit_hash': ''}
            )
        
        log_project(project_id, 'info', f"Found {len(branches)} branches and {len(tags)} tags")
        
        project.status = 'ready'
        project.last_build_at = timezone.now()
        project.save()
        
        log_project(project_id, 'info', "Clone completed successfully")
        logger.info(f"Successfully cloned project {project_id}")
        
        # Trigger requirements analysis
        log_project(project_id, 'info', "Triggering requirements analysis...")
        analyze_requirements_task.delay(project_id)
    
    except Project.DoesNotExist:
        logger.error(f"Project {project_id} not found")
    except Exception as e:
        project = Project.objects.get(id=project_id)
        project.status = 'failed'
        project.status_message = str(e)
        project.save()
        log_project(project_id, 'error', f"Clone error: {str(e)}")
        logger.error(f"Error cloning project {project_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def analyze_requirements_task(self, project_id: int):
    """
    Analyze requirements.txt and create package records
    
    Args:
        project_id: ID of the project to analyze
    """
    try:
        project = Project.objects.get(id=project_id)
        
        if project.status != 'ready':
            logger.warning(f"Project {project_id} not ready for analysis")
            return
        
        project.status = 'analyzing'
        project.save()
        
        log_project(project_id, 'info', "Starting requirements analysis...")
        
        # Initialize Git manager and parser
        git_manager = GitManager(settings.REQPM['GIT_CACHE_DIR'])
        parser = RequirementsParser()
        
        # Calculate repo path from git URL
        repo_name = project.git_url.rstrip('/').split('/')[-1]
        if repo_name.endswith('.git'):
            repo_name = repo_name[:-4]
        repo_path = os.path.join(settings.REQPM['GIT_CACHE_DIR'], repo_name)
        
        # Get requirements files to process
        requirements_files = project.requirements_files if project.requirements_files else ['requirements.txt']
        log_project(project_id, 'info', f"Processing {len(requirements_files)} requirements file(s): {', '.join(requirements_files)}")
        
        all_requirements = []
        processed_files = []
        
        # Read and parse each requirements file
        for req_file in requirements_files:
            log_project(project_id, 'info', f"Reading {req_file}...")
            requirements_content = git_manager.read_file(repo_path, req_file)
            
            if not requirements_content:
                log_project(project_id, 'warning', f"Could not read {req_file}")
                logger.warning(f"Could not read requirements file: {req_file}")
                continue
            
            # Parse requirements
            requirements = parser.parse_string(requirements_content)
            if requirements:
                # Tag requirements with their source file
                for req in requirements:
                    req.source_file = req_file
                all_requirements.extend(requirements)
                processed_files.append(req_file)
                log_project(project_id, 'info', f"Found {len(requirements)} packages in {req_file}")
        
        if not all_requirements:
            project.status = 'failed'
            project.status_message = f"Could not find or read any requirements files: {', '.join(requirements_files)}"
            project.save()
            log_project(project_id, 'error', f"No valid requirements found in any file")
            logger.error(f"No requirements found for project {project_id}")
            return
        
        log_project(project_id, 'info', f"Total packages found: {len(all_requirements)}")
        logger.info(f"Processed {len(processed_files)} requirements files with {len(all_requirements)} packages")
        
        # Create or update package records
        from backend.apps.packages.models import Package
        
        log_project(project_id, 'info', "Creating package records...")
        created_count = 0
        for req in all_requirements:
            package, created = Package.objects.get_or_create(
                project=project,
                name=req.name,
                defaults={
                    'version': req.specs[0][1] if req.specs else '',
                    'package_type': 'dependency',
                    'requirements_file': getattr(req, 'source_file', ''),
                    'is_direct_dependency': True,
                }
            )
            
            # Update existing packages to mark as direct dependency
            if not created:
                package.is_direct_dependency = True
                package.requirements_file = getattr(req, 'source_file', '')
                package.save()
            
            if created:
                created_count += 1
                logger.info(f"Created package: {req.name} for project {project_id}")
        
        project.status = 'ready'
        project.save()
        
        log_project(project_id, 'info', f"Analysis complete: {created_count} new packages, {len(all_requirements) - created_count} existing")
        logger.info(f"Analyzed requirements for project {project_id}: {created_count} packages created")
        
        # Trigger spec file generation for all packages
        log_project(project_id, 'info', "Triggering spec file generation...")
        from backend.apps.packages.tasks import generate_all_spec_files_task
        generate_all_spec_files_task.delay(project_id)
        
        # Trigger dependency resolution
        log_project(project_id, 'info', "Triggering dependency resolution...")
        resolve_dependencies_task.delay(project_id)
    
    except Project.DoesNotExist:
        logger.error(f"Project {project_id} not found")
    except Exception as e:
        project = Project.objects.get(id=project_id)
        project.status = 'failed'
        project.status_message = str(e)
        project.save()
        logger.error(f"Error analyzing requirements for project {project_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def resolve_dependencies_task(self, project_id: int):
    """
    Resolve dependencies for all packages in a project
    
    Args:
        project_id: ID of the project
    """
    try:
        from backend.apps.packages.models import Package, PackageDependency
        from backend.core.pypi_client import PyPIClient
        
        project = Project.objects.get(id=project_id)
        packages = Package.objects.filter(project=project)
        
        log_project(project_id, 'info', "Starting dependency resolution...")
        
        pypi_client = PyPIClient()
        resolver = DependencyResolver()
        
        # Build dependency tree
        dependency_tree = {}
        new_packages = []  # Track newly created packages for spec generation
        
        for package in packages:
            # Get package info from PyPI
            pkg_info = pypi_client.get_package_info(package.python_name or package.name, package.version or None)
            
            if pkg_info:
                # Store runtime dependencies
                deps = []
                for dep_req in pkg_info.runtime_dependencies:
                    dep_name = pypi_client._parse_package_name(dep_req)
                    if dep_name:
                        deps.append(dep_name)
                        
                        # Get version from PyPI for transitive dependencies
                        dep_info = pypi_client.get_package_info(dep_name)
                        dep_version = dep_info.version if dep_info else None
                        
                        # Create or get dependency package
                        dep_package, created = Package.objects.get_or_create(
                            project=project,
                            name=dep_name,
                            defaults={
                                'python_name': dep_name,
                                'version': dep_version or '',
                                'package_type': 'dependency',
                                'is_direct_dependency': False,
                            }
                        )
                        
                        if created:
                            new_packages.append(dep_package.id)
                        
                        # Update version if not set
                        if not dep_package.version and dep_version:
                            dep_package.version = dep_version
                            dep_package.save()
                        
                        # Create dependency link
                        PackageDependency.objects.get_or_create(
                            package=package,
                            depends_on=dep_package,
                            defaults={'dependency_type': 'runtime'}
                        )
                
                dependency_tree[package.name] = deps
        
        # Calculate build order
        build_levels = resolver.calculate_build_order(dependency_tree)
        
        # Assign build order to packages
        for level_index, level_packages in enumerate(build_levels):
            for pkg_name in level_packages:
                Package.objects.filter(
                    project=project,
                    name=pkg_name
                ).update(build_order=level_index)
        
        # Generate specs for newly created transitive dependencies
        if new_packages:
            log_project(project_id, 'info', f"Generating specs for {len(new_packages)} new transitive dependencies")
            from backend.apps.packages.tasks import generate_spec_file_task
            for pkg_id in new_packages:
                generate_spec_file_task.delay(pkg_id, force=True)
        
        log_project(project_id, 'info', f"Dependency resolution complete: {len(build_levels)} build levels, {len(new_packages)} new packages")
        logger.info(f"Resolved dependencies for project {project_id}: {len(build_levels)} build levels")
    
    except Exception as e:
        log_project(project_id, 'error', f"Dependency resolution failed: {str(e)}")
        logger.error(f"Error resolving dependencies for project {project_id}: {e}")
        raise self.retry(exc=e, countdown=60)



@shared_task
def sync_all_projects_task():
    """
    Sync all active projects with their Git repositories
    """
    projects = Project.objects.filter(is_active=True, auto_sync=True)
    
    for project in projects:
        clone_project_task.delay(project.id)
    
    logger.info(f"Triggered sync for {projects.count()} projects")


@shared_task
def cleanup_old_repos_task(days: int = 7):
    """
    Clean up old cached repositories
    
    Args:
        days: Remove repositories older than this many days
    """
    from datetime import timedelta
    
    cutoff_date = timezone.now() - timedelta(days=days)
    old_projects = Project.objects.filter(
        updated_at__lt=cutoff_date,
        status__in=['failed', 'completed']
    )
    
    git_manager = GitManager(settings.REQPM['GIT_CACHE_DIR'])
    
    for project in old_projects:
        # Calculate repo name from git_url
        repo_name = project.git_url.rstrip('/').split('/')[-1]
        if repo_name.endswith('.git'):
            repo_name = repo_name[:-4]
        git_manager.cleanup_cache(repo_name)
        logger.info(f"Cleaned up repository for project {project.id}")
    
    logger.info(f"Cleaned up {old_projects.count()} old repositories")


@shared_task
def resume_stuck_projects_task():
    """
    Resume projects that are stuck in pending or processing states.
    This is typically called on startup or periodically to handle cases
    where Celery was restarted while processing projects.
    """
    from datetime import timedelta
    
    # Find projects that have been in pending state for more than 5 minutes
    stuck_pending = Project.objects.filter(
        status='pending',
        created_at__lt=timezone.now() - timedelta(minutes=5)
    )
    
    for project in stuck_pending:
        logger.info(f"Resuming stuck pending project {project.id}: {project.name}")
        clone_project_task.delay(project.id)
    
    # Find projects stuck in cloning state for more than 30 minutes
    stuck_cloning = Project.objects.filter(
        status='cloning',
        updated_at__lt=timezone.now() - timedelta(minutes=30)
    )
    
    for project in stuck_cloning:
        logger.warning(f"Resuming stuck cloning project {project.id}: {project.name}")
        clone_project_task.delay(project.id)
    
    # Find projects stuck in analyzing state for more than 15 minutes
    stuck_analyzing = Project.objects.filter(
        status='analyzing',
        updated_at__lt=timezone.now() - timedelta(minutes=15)
    )
    
    for project in stuck_analyzing:
        logger.warning(f"Resuming stuck analyzing project {project.id}: {project.name}")
        analyze_requirements_task.delay(project.id)
    
    total_resumed = stuck_pending.count() + stuck_cloning.count() + stuck_analyzing.count()
    if total_resumed > 0:
        logger.info(f"Resumed {total_resumed} stuck projects")
    
    return total_resumed

