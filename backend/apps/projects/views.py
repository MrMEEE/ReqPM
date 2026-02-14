"""
ViewSets for Projects app
"""
import logging
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.db import models

logger = logging.getLogger(__name__)

from backend.apps.projects.models import (
    Project, ProjectBranch, ProjectBuildConfig, ProjectCollaborator
)
from backend.apps.projects.serializers import (
    ProjectListSerializer, ProjectDetailSerializer,
    ProjectCreateSerializer, ProjectUpdateSerializer,
    ProjectBranchSerializer, ProjectBuildConfigSerializer,
    ProjectCollaboratorSerializer
)
from backend.apps.projects.tasks import (
    clone_project_task, analyze_requirements_task,
    resolve_dependencies_task
)
from backend.apps.packages.tasks import (
    generate_all_spec_files_task, check_package_updates_task
)


class ProjectViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Project model
    
    list: Get all projects accessible by user
    create: Create a new project (triggers git clone)
    retrieve: Get project details
    update: Update project (triggers sync if git ref changed)
    destroy: Delete project
    
    Custom actions:
    - sync: Trigger git sync
    - analyze: Analyze requirements.txt
    - resolve_dependencies: Resolve package dependencies
    - generate_specs: Generate spec files for all packages
    - check_updates: Check for package updates
    - branches: List available branches
    - collaborators: Manage project collaborators
    """
    
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'owner', 'build_version']
    search_fields = ['name', 'description', 'git_url']
    ordering_fields = ['name', 'created_at', 'updated_at', 'last_build_at']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Get projects accessible by current user"""
        user = self.request.user
        
        # Admin can see all projects
        if user.is_staff:
            return Project.objects.all()
        
        # Users see their own projects and projects they collaborate on
        return Project.objects.filter(
            owner=user
        ) | Project.objects.filter(
            collaborators__user=user
        ).distinct()
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == 'list':
            return ProjectListSerializer
        elif self.action == 'create':
            return ProjectCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ProjectUpdateSerializer
        else:
            return ProjectDetailSerializer
    
    @action(detail=True, methods=['post'])
    def sync(self, request, pk=None):
        """
        Trigger git sync for project
        
        POST /api/projects/{id}/sync/
        """
        project = self.get_object()
        
        if project.status in ['cloning', 'analyzing']:
            return Response(
                {'detail': 'Project is already being synced'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Trigger clone/update task
        clone_project_task.delay(project.id)
        
        return Response({
            'detail': 'Sync triggered',
            'project_id': project.id,
            'status': 'pending'
        })
    
    @action(detail=True, methods=['post'])
    def analyze(self, request, pk=None):
        """
        Analyze requirements.txt for project
        
        POST /api/projects/{id}/analyze/
        """
        project = self.get_object()
        
        if project.status != 'ready':
            return Response(
                {'detail': 'Project must be in ready state'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Trigger analysis task
        analyze_requirements_task.delay(project.id)
        
        return Response({
            'detail': 'Analysis triggered',
            'project_id': project.id
        })
    
    @action(detail=True, methods=['post'])
    def resolve_dependencies(self, request, pk=None):
        """
        Resolve package dependencies
        
        POST /api/projects/{id}/resolve_dependencies/
        """
        project = self.get_object()
        
        # Trigger dependency resolution
        resolve_dependencies_task.delay(project.id)
        
        return Response({
            'detail': 'Dependency resolution triggered',
            'project_id': project.id
        })
    
    @action(detail=True, methods=['post'])
    def generate_specs(self, request, pk=None):
        """
        Generate spec files for all packages
        
        POST /api/projects/{id}/generate_specs/
        """
        project = self.get_object()
        
        # Trigger spec generation
        generate_all_spec_files_task.delay(project.id)
        
        return Response({
            'detail': 'Spec file generation triggered',
            'project_id': project.id
        })
    
    @action(detail=True, methods=['post'])
    def check_updates(self, request, pk=None):
        """
        Check for package updates
        
        POST /api/projects/{id}/check_updates/
        """
        project = self.get_object()
        
        # Trigger update check
        result = check_package_updates_task.delay(project.id)
        
        return Response({
            'detail': 'Update check triggered',
            'project_id': project.id,
            'task_id': result.id
        })
    
    @action(detail=True, methods=['get'])
    def branches(self, request, pk=None):
        """
        List available branches for project
        
        GET /api/projects/{id}/branches/
        """
        project = self.get_object()
        branches = project.branches.all()
        serializer = ProjectBranchSerializer(branches, many=True)
        
        return Response(serializer.data)
    
    @action(detail=True, methods=['get', 'post'])
    def collaborators(self, request, pk=None):
        """
        Manage project collaborators
        
        GET /api/projects/{id}/collaborators/ - List collaborators
        POST /api/projects/{id}/collaborators/ - Add collaborator
        """
        project = self.get_object()
        
        # Check if user is owner or admin
        if project.owner != request.user and not request.user.is_staff:
            return Response(
                {'detail': 'Only project owner can manage collaborators'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if request.method == 'GET':
            collaborators = project.collaborators.all()
            serializer = ProjectCollaboratorSerializer(collaborators, many=True)
            return Response(serializer.data)
        
        elif request.method == 'POST':
            serializer = ProjectCollaboratorSerializer(data=request.data)
            if serializer.is_valid():
                serializer.save(
                    project=project,
                    added_by=request.user
                )
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['delete'], url_path='collaborators/(?P<collaborator_id>[^/.]+)')
    def remove_collaborator(self, request, pk=None, collaborator_id=None):
        """
        Remove a collaborator
        
        DELETE /api/projects/{id}/collaborators/{collaborator_id}/
        """
        project = self.get_object()
        
        # Check if user is owner or admin
        if project.owner != request.user and not request.user.is_staff:
            return Response(
                {'detail': 'Only project owner can manage collaborators'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        collaborator = get_object_or_404(
            ProjectCollaborator,
            id=collaborator_id,
            project=project
        )
        collaborator.delete()
        
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """
        Get project logs
        
        GET /api/projects/{id}/logs/?since={timestamp}
        """
        from backend.apps.projects.models import ProjectLog
        
        project = self.get_object()
        
        # Get logs, optionally filtered by timestamp
        queryset = project.logs.all()
        
        # Filter by timestamp if provided
        since = request.query_params.get('since')
        if since:
            try:
                from django.utils.dateparse import parse_datetime
                since_dt = parse_datetime(since)
                if since_dt:
                    queryset = queryset.filter(timestamp__gt=since_dt)
            except (ValueError, TypeError):
                pass
        
        # Limit to last 500 logs
        queryset = queryset[:500]
        
        logs = [{
            'id': log.id,
            'level': log.level,
            'message': log.message,
            'timestamp': log.timestamp.isoformat()
        } for log in queryset]
        
        return Response({'logs': logs})
    
    @action(detail=True, methods=['get'])
    def packages(self, request, pk=None):
        """
        Get packages for a project - returns direct and transitive dependencies separately
        
        GET /api/projects/{id}/packages/
        """
        from backend.apps.packages.models import Package
        from backend.apps.packages.serializers import PackageListSerializer
        
        project = self.get_object()
        
        # Get direct and transitive dependencies separately
        direct_packages = Package.objects.filter(
            project=project, 
            is_direct_dependency=True
        ).prefetch_related('dependencies', 'dependents', 'dependents__package', 'extras').order_by('name')
        
        transitive_packages = Package.objects.filter(
            project=project, 
            is_direct_dependency=False
        ).prefetch_related('dependencies', 'dependents', 'dependents__package', 'extras').order_by('name')
        
        # Serialize both lists
        direct_serializer = PackageListSerializer(direct_packages, many=True)
        transitive_serializer = PackageListSerializer(transitive_packages, many=True)
        
        # Combine for total count and backward compatibility
        all_packages = list(direct_serializer.data) + list(transitive_serializer.data)
        
        return Response({
            'packages': all_packages,
            'direct_dependencies': direct_serializer.data,
            'transitive_dependencies': transitive_serializer.data,
            'count': len(all_packages),
            'direct_count': len(direct_serializer.data),
            'transitive_count': len(transitive_serializer.data),
        })
    
    @action(detail=True, methods=['post'], url_path='fetch-all-sources')
    def fetch_all_sources(self, request, pk=None):
        """
        Trigger source fetching for all packages with spec files
        
        POST /api/projects/{id}/fetch-all-sources/
        """
        from backend.apps.packages.models import Package, SpecFileRevision
        from backend.apps.packages.tasks import fetch_package_source_task
        
        project = self.get_object()
        
        # Get all packages that have spec files
        # Use Exists subquery instead of annotate+filter to avoid
        # 'Cannot combine a unique query with a non-unique query' error
        packages_with_specs = Package.objects.filter(
            project=project,
            id__in=SpecFileRevision.objects.values('package_id').distinct()
        )
        
        count = packages_with_specs.count()
        
        # Trigger source fetching for each package
        for package in packages_with_specs:
            fetch_package_source_task.delay(package.id)
        
        logger.info(f"Triggered source fetching for {count} packages in project {project.id}")
        
        return Response({
            'message': f'Started fetching sources for {count} packages',
            'count': count
        })
    
    @action(detail=True, methods=['post'], url_path='build-all-packages')
    def build_all_packages(self, request, pk=None):
        """
        Build all packages in the project
        
        POST /api/projects/{id}/build-all-packages/
        
        Triggers builds for all packages that have specs and sources.
        Only builds packages that haven't been successfully built yet.
        Builds will be triggered in dependency order (dependencies first).
        """
        from backend.apps.packages.tasks import build_single_package_task
        from backend.apps.packages.models import SpecFileRevision
        from backend.apps.projects.tasks import log_project
        
        project = self.get_object()
        
        # Get all packages with specs (source_fetched is a @property, filter in Python)
        packages_with_specs = project.packages.filter(
            id__in=SpecFileRevision.objects.values('package_id').distinct()
        )
        # Filter for packages that have their sources fetched and are not already successfully built
        packages = [p for p in packages_with_specs if p.source_fetched and p.build_status != 'completed']
        
        if not packages:
            return Response(
                {'detail': 'No packages need building (all packages are either missing specs/sources or already built)'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Sort packages by dependency order (build dependencies first)
        # We'll use a simple topological sort based on dependencies
        package_list = packages
        build_order = []
        remaining = set(package_list)
        
        while remaining:
            # Find packages with no unbuilt dependencies in remaining set
            ready = []
            for pkg in remaining:
                deps = set(pkg.dependencies.filter(
                    depends_on__in=remaining
                ).values_list('depends_on_id', flat=True))
                
                if not deps:
                    ready.append(pkg)
            
            if not ready:
                # Circular dependency or no progress - add all remaining
                build_order.extend(remaining)
                break
            
            build_order.extend(ready)
            for pkg in ready:
                remaining.remove(pkg)
        
        count = len(build_order)
        
        # Trigger builds
        for package in build_order:
            build_single_package_task.delay(package.id)
        
        log_project(project.id, 'info', f"Triggered builds for {count} packages")
        logger.info(f"Triggered builds for {count} packages in project {project.id}")
        
        return Response({
            'message': f'Started building {count} packages',
            'count': count,
            'packages': [pkg.name for pkg in build_order]
        })
    
    @action(detail=False, methods=['post'])
    def fetch_branches(self, request):
        """
        Fetch branches from a Git repository URL
        
        POST /api/projects/fetch_branches/
        Body: { "repository_url": "https://github.com/user/repo.git" }
        """
        from django.conf import settings
        from backend.core.git_manager import GitManager
        
        repository_url = request.data.get('repository_url')
        if not repository_url:
            return Response(
                {'detail': 'repository_url is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Initialize GitManager
        git_manager = GitManager(settings.REQPM['GIT_CACHE_DIR'])
        
        # Fetch branches
        branches = git_manager.get_remote_branches(repository_url)
        
        if not branches:
            return Response(
                {'detail': 'Could not fetch branches. Please check the repository URL and your access permissions.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return Response({
            'branches': branches,
            'default': 'main' if 'main' in branches else ('master' if 'master' in branches else branches[0] if branches else 'main')
        })
    
    @action(detail=False, methods=['post'])
    def fetch_requirements_files(self, request):
        """
        Find requirements files in a Git repository
        
        POST /api/projects/fetch_requirements_files/
        Body: { 
            "repository_url": "https://github.com/user/repo.git",
            "branch": "main"  # optional
        }
        """
        from django.conf import settings
        from backend.core.git_manager import GitManager
        import os
        
        repository_url = request.data.get('repository_url')
        branch = request.data.get('branch')
        
        if not repository_url:
            return Response(
                {'detail': 'repository_url is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Initialize GitManager
        git_manager = GitManager(settings.REQPM['GIT_CACHE_DIR'])
        
        # Clone the repository (or use cached version)
        success, repo_path, error = git_manager.clone_or_update(
            url=repository_url,
            branch=branch
        )
        
        if not success:
            return Response(
                {'detail': f'Could not clone repository: {error}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Find requirements files
        requirements_files = git_manager.find_requirements_files(repo_path)
        
        if not requirements_files:
            return Response({
                'detail': 'No requirements files found in repository',
                'requirements_files': []
            })
        
        return Response({
            'requirements_files': requirements_files,
            'default': 'requirements.txt' if 'requirements.txt' in requirements_files else requirements_files[0] if requirements_files else None
        })


class ProjectBuildConfigViewSet(viewsets.ModelViewSet):
    """ViewSet for ProjectBuildConfig model"""
    
    permission_classes = [IsAuthenticated]
    serializer_class = ProjectBuildConfigSerializer
    
    def get_queryset(self):
        """Get build configs for projects accessible by user"""
        user = self.request.user
        
        if user.is_staff:
            return ProjectBuildConfig.objects.all()
        
        return ProjectBuildConfig.objects.filter(
            project__owner=user
        ) | ProjectBuildConfig.objects.filter(
            project__collaborators__user=user
        ).distinct()
    
    def perform_create(self, serializer):
        """Set created_by to current user"""
        serializer.save(created_by=self.request.user)
