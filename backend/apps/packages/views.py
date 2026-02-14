"""
ViewSets for Packages app
"""
import os
from django.http import FileResponse, Http404
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from backend.apps.packages.models import (
    Package, PackageDependency, PackageBuild, SpecFileRevision, PackageLog, PackageExtra
)
from backend.apps.packages.serializers import (
    PackageListSerializer, PackageDetailSerializer,
    PackageCreateSerializer, PackageUpdateSerializer,
    PackageDependencySerializer, PackageBuildSerializer,
    SpecFileRevisionSerializer, SpecFileCreateSerializer,
    PackageLogSerializer, PackageExtraSerializer
)
from backend.apps.packages.tasks import (
    generate_spec_file_task, update_package_metadata_task, sync_package_extras_task
)


class PackageViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Package model
    
    list: Get all packages
    create: Create a new package
    retrieve: Get package details with dependencies and builds
    update: Update package
    destroy: Delete package
    
    Custom actions:
    - generate_spec: Generate spec file from PyPI metadata
    - update_metadata: Update package metadata from PyPI
    - dependencies: Get/manage package dependencies
    - builds: Get build history
    - spec_files: Get/create spec file revisions
    """
    
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['project', 'package_type', 'status', 'build_order']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'build_order', 'created_at', 'updated_at']
    ordering = ['build_order', 'name']
    
    def get_queryset(self):
        """Get packages for projects accessible by user"""
        user = self.request.user
        
        if user.is_staff:
            return Package.objects.all()
        
        # Users see packages from their projects
        return Package.objects.filter(
            project__owner=user
        ) | Package.objects.filter(
            project__collaborators__user=user
        ).distinct()
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == 'list':
            return PackageListSerializer
        elif self.action == 'create':
            return PackageCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return PackageUpdateSerializer
        else:
            return PackageDetailSerializer
    
    @action(detail=True, methods=['post'])
    def generate_spec(self, request, pk=None):
        """
        Generate spec file from PyPI metadata
        
        POST /api/packages/{id}/generate_spec/
        Body: {"force": true}  # Optional, to regenerate existing spec
        """
        package = self.get_object()
        force = request.data.get('force', False)
        
        # Trigger spec generation
        generate_spec_file_task.delay(package.id, force=force)
        
        return Response({
            'detail': 'Spec file generation triggered',
            'package_id': package.id
        })
    
    @action(detail=True, methods=['post'])
    def update_metadata(self, request, pk=None):
        """
        Update package metadata from PyPI
        
        POST /api/packages/{id}/update_metadata/
        """
        package = self.get_object()
        
        # Trigger metadata update
        update_package_metadata_task.delay(package.id)
        
        return Response({
            'detail': 'Metadata update triggered',
            'package_id': package.id
        })
    
    @action(detail=True, methods=['post'])
    def fetch_source(self, request, pk=None):
        """
        Fetch source files for a package
        
        POST /api/packages/{id}/fetch_source/
        """
        from backend.apps.packages.tasks import fetch_package_source_task
        
        package = self.get_object()
        
        # Trigger source fetching
        fetch_package_source_task.delay(package.id)
        
        return Response({
            'detail': 'Source fetching triggered',
            'package_id': package.id
        })
    
    @action(detail=True, methods=['get'])
    def dependencies(self, request, pk=None):
        """
        Get package dependencies
        
        GET /api/packages/{id}/dependencies/
        """
        package = self.get_object()
        dependencies = package.dependencies.all()
        serializer = PackageDependencySerializer(dependencies, many=True)
        
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def builds(self, request, pk=None):
        """
        Get package build history from build queue
        
        GET /api/packages/{id}/builds/
        Query params:
        - rhel_version: Filter by RHEL version
        - status: Filter by status (completed, failed, etc.)
        """
        from backend.apps.builds.models import BuildQueue
        from backend.apps.builds.serializers import BuildQueueSerializer
        
        package = self.get_object()
        queue_items = BuildQueue.objects.filter(package=package)
        
        # Filter by query params
        rhel_version = request.query_params.get('rhel_version')
        if rhel_version:
            queue_items = queue_items.filter(rhel_version=rhel_version)
        
        status_filter = request.query_params.get('status')
        if status_filter:
            queue_items = queue_items.filter(status=status_filter)
        
        queue_items = queue_items.select_related('build_job', 'package').order_by('-completed_at')
        serializer = BuildQueueSerializer(queue_items, many=True)
        
        return Response(serializer.data)
    
    @action(detail=True, methods=['get', 'post'])
    def spec_files(self, request, pk=None):
        """
        Get or create spec file revisions
        
        GET /api/packages/{id}/spec_files/ - List all spec revisions
        POST /api/packages/{id}/spec_files/ - Create new revision
        Body: {"content": "...", "changelog": "..."}
        """
        package = self.get_object()
        
        if request.method == 'GET':
            spec_files = package.spec_revisions.order_by('-created_at')
            serializer = SpecFileRevisionSerializer(spec_files, many=True)
            return Response(serializer.data)
        
        elif request.method == 'POST':
            serializer = SpecFileCreateSerializer(
                data=request.data,
                context={'package': package, 'request': request}
            )
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'], url_path='spec_files/latest')
    def latest_spec(self, request, pk=None):
        """
        Get latest spec file content
        
        GET /api/packages/{id}/spec_files/latest/
        """
        package = self.get_object()
        latest = package.spec_files.order_by('-created_at').first()
        
        if not latest:
            return Response(
                {'detail': 'No spec file found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = SpecFileRevisionSerializer(latest)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """
        Get package logs
        
        GET /api/packages/{id}/logs/
        Query params:
        - level: Filter by log level (debug, info, warning, error)
        - limit: Number of logs to return (default: 100)
        """
        package = self.get_object()
        logs = package.logs.all()
        
        # Filter by level if provided
        level = request.query_params.get('level')
        if level:
            logs = logs.filter(level=level)
        
        # Limit results
        limit = int(request.query_params.get('limit', 100))
        logs = logs.order_by('-timestamp')[:limit]
        
        serializer = PackageLogSerializer(logs, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def build_package(self, request, pk=None):
        """
        Build a single package
        
        POST /api/packages/{id}/build_package/
        """
        from backend.apps.packages.tasks import build_single_package_task
        
        package = self.get_object()
        
        # Validate package has spec file
        if not package.spec_revisions.exists():
            return Response(
                {'detail': 'Package must have a spec file before building'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate package has source
        if not package.source_fetched:
            return Response(
                {'detail': 'Package source must be fetched before building'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check dependencies are built
        unbuilt_deps = []
        for dep in package.dependencies.all():
            dep_package = dep.depends_on
            if dep_package and dep_package.build_status not in ['completed', 'not_required']:
                unbuilt_deps.append(dep_package.name)
        
        if unbuilt_deps:
            # Set to waiting_for_deps instead of rejecting
            package.build_status = 'waiting_for_deps'
            package.build_error_message = ''
            package.build_log = ''
            package.save()
            
            from backend.apps.packages.tasks import send_package_update
            send_package_update(package.id)
            
            return Response({
                'detail': f'Package queued, waiting for dependencies: {", ".join(unbuilt_deps)}',
                'package_id': package.id,
                'status': 'waiting_for_deps',
                'unbuilt_dependencies': unbuilt_deps
            })
        
        # All deps ready, trigger build immediately
        build_single_package_task.delay(package.id)
        
        return Response({
            'detail': 'Package build triggered',
            'package_id': package.id
        })
    
    @action(detail=True, methods=['post'])
    def cancel_build(self, request, pk=None):
        """
        Cancel a waiting/pending build
        
        POST /api/packages/{id}/cancel_build/
        """
        package = self.get_object()
        
        if package.build_status not in ['waiting_for_deps', 'pending']:
            return Response(
                {'detail': f'Cannot cancel build in state: {package.build_status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        package.build_status = 'not_built'
        package.build_started_at = None
        package.build_completed_at = None
        package.build_error_message = ''
        package.build_log = ''
        package.save()
        
        from backend.apps.packages.tasks import send_package_update
        send_package_update(package.id)
        
        return Response({
            'detail': 'Build cancelled',
            'package_id': package.id
        })
    
    @action(detail=True, methods=['post'])
    def rebuild_package(self, request, pk=None):
        """
        Rebuild a package (same as build but no dependency checks)
        
        POST /api/packages/{id}/rebuild_package/
        """
        from backend.apps.packages.tasks import build_single_package_task
        
        package = self.get_object()
        
        # Validate package has spec file
        if not package.spec_revisions.exists():
            return Response(
                {'detail': 'Package must have a spec file before building'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate package has source
        if not package.source_fetched:
            return Response(
                {'detail': 'Package source must be fetched before building'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Trigger build (no dependency check for rebuild)
        build_single_package_task.delay(package.id)
        
        return Response({
            'detail': 'Package rebuild triggered',
            'package_id': package.id
        })
    
    @action(detail=True, methods=['get'])
    def build_status(self, request, pk=None):
        """
        Get package build status
        
        GET /api/packages/{id}/build_status/
        """
        package = self.get_object()
        
        return Response({
            'package_id': package.id,
            'package_name': package.name,
            'build_status': package.build_status,
            'build_started_at': package.build_started_at,
            'build_completed_at': package.build_completed_at,
            'build_error_message': package.build_error_message,
            'srpm_path': package.srpm_path,
            'rpm_path': package.rpm_path,
        })
    
    @action(detail=True, methods=['get'])
    def extras(self, request, pk=None):
        """
        Get available extras for this package
        
        GET /api/packages/{id}/extras/
        """
        package = self.get_object()
        extras = package.extras.all()
        serializer = PackageExtraSerializer(extras, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def sync_extras(self, request, pk=None):
        """
        Sync extras from PyPI metadata
        
        POST /api/packages/{id}/sync_extras/
        """
        from backend.apps.packages.tasks import sync_package_extras_task
        
        package = self.get_object()
        task = sync_package_extras_task.delay(package.id)
        
        return Response({
            'message': 'Extras sync started',
            'task_id': task.id
        }, status=status.HTTP_202_ACCEPTED)
    
    @action(detail=True, methods=['patch'], url_path='extras/(?P<extra_id>[^/.]+)')
    def update_extra(self, request, pk=None, extra_id=None):
        """
        Update an extra (enable/disable)
        
        PATCH /api/packages/{id}/extras/{extra_id}/
        Body: { "enabled": true/false }
        """
        from backend.apps.packages.models import PackageExtra
        
        package = self.get_object()
        
        try:
            extra = package.extras.get(id=extra_id)
        except PackageExtra.DoesNotExist:
            return Response(
                {'error': 'Extra not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = PackageExtraSerializer(extra, data=request.data, partial=True)
        if serializer.is_valid():
            old_enabled = extra.enabled
            serializer.save()
            
            # Trigger spec file regeneration and dependency recalculation if extras changed
            if 'enabled' in request.data and old_enabled != extra.enabled:
                from backend.apps.packages.tasks import generate_spec_file_task
                from backend.apps.projects.tasks import resolve_dependencies_task
                
                # Regenerate spec file with new extras
                generate_spec_file_task.delay(package.id, force=True)
                
                # Recalculate dependencies for the entire project since extras affect deps
                resolve_dependencies_task.delay(package.project.id)
            
            return Response(serializer.data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'], url_path='versions')
    def get_versions(self, request, pk=None):
        """
        Get available versions for a package from PyPI
        
        GET /api/packages/{id}/versions/
        """
        package = self.get_object()
        
        try:
            from backend.core.pypi_client import PyPIClient
            
            pypi_client = PyPIClient()
            # Use python_name if available, otherwise fall back to name
            package_name = package.python_name or package.name
            versions = pypi_client.get_package_versions(package_name)
            
            if versions:
                return Response({
                    'package': package_name,
                    'versions': versions,
                    'current_version': package.version
                })
            else:
                return Response(
                    {'error': f'No versions found for {package_name}'},
                    status=status.HTTP_404_NOT_FOUND
                )
        except Exception as e:
            logger.exception(f"Error fetching versions for {package.python_name or package.name}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['patch'], url_path='change-version')
    def change_version(self, request, pk=None):
        """
        Change the version of a package
        
        PATCH /api/packages/{id}/change-version/
        Body: { "version": "1.2.3" }
        """
        package = self.get_object()
        new_version = request.data.get('version')
        
        if not new_version:
            return Response(
                {'error': 'Version is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        old_version = package.version
        
        # Update version
        package.version = new_version
        package.save()
        
        # Trigger spec file regeneration with new version
        from backend.apps.packages.tasks import generate_spec_file_task
        from backend.apps.projects.tasks import resolve_dependencies_task
        
        generate_spec_file_task.delay(package.id, force=True)
        
        # Recalculate dependencies only for this package
        resolve_dependencies_task.delay(package.project.id)
        
        logger.info(f"Changed version of {package.name} from {old_version} to {new_version}")
        
        return Response({
            'message': f'Version changed from {old_version} to {new_version}',
            'package': PackageListSerializer(package).data
        })
    
    @action(detail=True, methods=['get'], url_path='download-rpm')
    def download_rpm(self, request, pk=None):
        """
        Download the RPM file for this package
        
        GET /api/packages/{id}/download-rpm/
        """
        package = self.get_object()
        
        if not package.rpm_path:
            raise Http404("RPM file not available for this package")
        
        if not os.path.exists(package.rpm_path):
            raise Http404("RPM file not found on server")
        
        response = FileResponse(open(package.rpm_path, 'rb'), as_attachment=True)
        response['Content-Disposition'] = f'attachment; filename="{os.path.basename(package.rpm_path)}"'
        return response
    
    @action(detail=True, methods=['get'], url_path='download-srpm')
    def download_srpm(self, request, pk=None):
        """
        Download the SRPM file for this package
        
        GET /api/packages/{id}/download-srpm/
        """
        package = self.get_object()
        
        if not package.srpm_path:
            raise Http404("SRPM file not available for this package")
        
        if not os.path.exists(package.srpm_path):
            raise Http404("SRPM file not found on server")
        
        response = FileResponse(open(package.srpm_path, 'rb'), as_attachment=True)
        response['Content-Disposition'] = f'attachment; filename="{os.path.basename(package.srpm_path)}"'
        return response


class PackageBuildViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ReadOnly ViewSet for PackageBuild model
    
    Builds are created by the build system, not directly via API
    """
    
    permission_classes = [IsAuthenticated]
    serializer_class = PackageBuildSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['package', 'rhel_version', 'status']
    ordering_fields = ['built_at']
    ordering = ['-built_at']
    
    def get_queryset(self):
        """Get builds for packages accessible by user"""
        user = self.request.user
        
        if user.is_staff:
            return PackageBuild.objects.all()
        
        return PackageBuild.objects.filter(
            package__project__owner=user
        ) | PackageBuild.objects.filter(
            package__project__collaborators__user=user
        ).distinct()
    
    @action(detail=True, methods=['get'], url_path='download-rpm')
    def download_rpm(self, request, pk=None):
        """
        Download the RPM file for this build
        
        GET /api/builds/{id}/download-rpm/
        """
        build = self.get_object()
        
        if not build.rpm_path:
            raise Http404("RPM file not available for this build")
        
        if not os.path.exists(build.rpm_path):
            raise Http404("RPM file not found on server")
        
        response = FileResponse(open(build.rpm_path, 'rb'), as_attachment=True)
        response['Content-Disposition'] = f'attachment; filename="{os.path.basename(build.rpm_path)}"'
        return response
    
    @action(detail=True, methods=['get'], url_path='download-srpm')
    def download_srpm(self, request, pk=None):
        """
        Download the SRPM file for this build
        
        GET /api/builds/{id}/download-srpm/
        """
        build = self.get_object()
        
        if not build.srpm_path:
            raise Http404("SRPM file not available for this build")
        
        if not os.path.exists(build.srpm_path):
            raise Http404("SRPM file not found on server")
        
        response = FileResponse(open(build.srpm_path, 'rb'), as_attachment=True)
        response['Content-Disposition'] = f'attachment; filename="{os.path.basename(build.srpm_path)}"'
        return response
