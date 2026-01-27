"""
ViewSets for Builds app
"""
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from backend.apps.builds.models import BuildJob, BuildQueue, BuildWorker
from backend.apps.builds.serializers import (
    BuildJobListSerializer, BuildJobDetailSerializer,
    BuildJobCreateSerializer, BuildQueueSerializer,
    BuildWorkerSerializer
)
from backend.apps.repositories.tasks import publish_build_to_repository_task
from backend.plugins.builders import get_builder, list_builders


class BuildJobViewSet(viewsets.ModelViewSet):
    """
    ViewSet for BuildJob model
    
    list: Get all build jobs
    create: Create a new build job
    retrieve: Get build job details with queue
    destroy: Cancel/delete build job
    
    Custom actions:
    - queue: Get build queue items
    - publish: Publish successful builds to repository
    - cancel: Cancel running build
    - retry: Retry failed builds
    """
    
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['project', 'status']
    ordering_fields = ['created_at', 'started_at', 'completed_at', 'progress']
    ordering = ['-created_at']
    http_method_names = ['get', 'post', 'delete']
    
    def get_queryset(self):
        """Get build jobs for projects accessible by user"""
        user = self.request.user
        
        if user.is_staff:
            return BuildJob.objects.all()
        
        return BuildJob.objects.filter(
            project__owner=user
        ) | BuildJob.objects.filter(
            project__collaborators__user=user
        ).distinct()
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == 'create':
            return BuildJobCreateSerializer
        elif self.action == 'list':
            return BuildJobListSerializer
        else:
            return BuildJobDetailSerializer
    
    def create(self, request, *args, **kwargs):
        """Create a new build job"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        
        return Response(result, status=status.HTTP_202_ACCEPTED)
    
    def destroy(self, request, *args, **kwargs):
        """Delete build job"""
        build_job = self.get_object()
        
        # If build is currently running, cancel it first
        if build_job.status in ['running', 'building']:
            # Cancel pending/queued items
            build_job.queue_items.filter(
                status__in=['pending', 'queued', 'blocked']
            ).update(
                status='cancelled',
                error_message='Build job deleted by user'
            )
        
        # Always delete the build job
        build_job.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    @action(detail=True, methods=['get'])
    def queue(self, request, pk=None):
        """
        Get build queue items for this job
        
        GET /api/build-jobs/{id}/queue/
        Query params:
        - status: Filter by status
        - rhel_version: Filter by RHEL version
        """
        build_job = self.get_object()
        queue = build_job.queue_items.all()
        
        # Filter by query params
        status_filter = request.query_params.get('status')
        if status_filter:
            queue = queue.filter(status=status_filter)
        
        rhel_version = request.query_params.get('rhel_version')
        if rhel_version:
            queue = queue.filter(rhel_version=rhel_version)
        
        queue = queue.select_related('package').order_by('package__build_order', 'package__name')
        serializer = BuildQueueSerializer(queue, many=True)
        
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """
        Publish successful builds to a repository
        
        POST /api/build-jobs/{id}/publish/
        Body: {"repository": 1}
        """
        build_job = self.get_object()
        
        if build_job.status != 'completed':
            return Response(
                {'detail': 'Build job must be completed'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        repository_id = request.data.get('repository')
        if not repository_id:
            return Response(
                {'detail': 'repository field is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Trigger publish task
        publish_build_to_repository_task.delay(build_job.id, repository_id)
        
        return Response({
            'detail': 'Publishing triggered',
            'build_job_id': build_job.id,
            'repository_id': repository_id
        })
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """
        Cancel running build job
        
        POST /api/build-jobs/{id}/cancel/
        """
        build_job = self.get_object()
        
        if build_job.status not in ['pending', 'building']:
            return Response(
                {'detail': 'Can only cancel pending or building jobs'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        build_job.status = 'cancelled'
        build_job.save()
        
        # Cancel pending queue items
        build_job.queue_items.filter(status='pending').update(
            status='cancelled',
            error_message='Build job cancelled by user'
        )
        
        return Response({'detail': 'Build job cancelled'})
    
    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """
        Retry failed builds in a job
        
        POST /api/build-jobs/{id}/retry/
        """
        build_job = self.get_object()
        
        if build_job.status != 'failed':
            return Response(
                {'detail': 'Can only retry failed builds'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Reset failed queue items to pending
        failed_items = build_job.queue_items.filter(status='failed')
        failed_count = failed_items.count()
        
        failed_items.update(
            status='pending',
            error_message='',
            started_at=None,
            completed_at=None
        )
        
        # Reset build job status
        build_job.status = 'pending'
        build_job.failed_packages = 0
        build_job.save()
        
        # Trigger build processing
        from backend.apps.builds.tasks import process_build_queue
        process_build_queue.delay(build_job.id)
        
        return Response({
            'detail': f'Retrying {failed_count} failed builds',
            'build_job_id': build_job.id
        })


class BuildQueueViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ReadOnly ViewSet for BuildQueue model
    
    View individual build queue items
    
    Actions:
    - retry: Retry a failed or cancelled build
    """
    
    permission_classes = [IsAuthenticated]
    serializer_class = BuildQueueSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['build_job', 'package', 'rhel_version', 'status']
    ordering_fields = ['created_at', 'started_at', 'completed_at']
    ordering = ['package__build_order', 'package__name']
    
    def get_queryset(self):
        """Get queue items for accessible build jobs"""
        user = self.request.user
        
        if user.is_staff:
            return BuildQueue.objects.all()
        
        return BuildQueue.objects.filter(
            build_job__project__owner=user
        ) | BuildQueue.objects.filter(
            build_job__project__collaborators__user=user
        ).distinct()
    
    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """
        Retry a failed or cancelled build
        
        POST /api/build-queue/{id}/retry/
        """
        queue_item = self.get_object()
        
        if queue_item.status not in ['failed', 'cancelled']:
            return Response(
                {'detail': f'Cannot retry build with status: {queue_item.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Reset the queue item
        queue_item.status = 'pending'
        queue_item.error_message = ''
        queue_item.build_log = ''
        queue_item.srpm_path = ''
        queue_item.rpm_path = ''
        queue_item.started_at = None
        queue_item.completed_at = None
        queue_item.save()
        
        # Trigger the build task
        from backend.apps.builds.tasks import build_package_task
        build_package_task.delay(queue_item.id)
        
        return Response({
            'detail': 'Build retry triggered',
            'queue_item_id': queue_item.id,
            'package': queue_item.package.name,
            'rhel_version': queue_item.rhel_version
        })


class BuildWorkerViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ReadOnly ViewSet for BuildWorker model
    
    View available build workers
    """
    
    permission_classes = [IsAuthenticated]
    serializer_class = BuildWorkerSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['status', 'hostname']
    ordering_fields = ['hostname', 'last_seen']
    ordering = ['hostname']
    queryset = BuildWorker.objects.all()


# Helper view for listing available build targets
@action(detail=False, methods=['get'])
def available_targets(request):
    """
    Get available build targets from build system
    
    GET /api/builds/available-targets/
    """
    builder = get_builder('mock')
    
    if not builder or not builder.is_available():
        return Response(
            {'detail': 'Build system not available'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    targets = builder.get_available_targets()
    
    return Response({
        'builder': 'mock',
        'targets': targets,
        'count': len(targets)
    })
