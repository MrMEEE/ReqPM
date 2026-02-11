"""
Utilities for sending WebSocket updates from tasks
"""
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


def send_build_job_update(build_job_id):
    """
    Send build job update via WebSocket
    
    Args:
        build_job_id: ID of the build job
    """
    from backend.apps.builds.models import BuildJob
    from backend.apps.builds.serializers import BuildJobDetailSerializer
    
    try:
        build_job = BuildJob.objects.get(id=build_job_id)
        serializer = BuildJobDetailSerializer(build_job)
        
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'build_job_{build_job_id}',
            {
                'type': 'build_update',
                'data': serializer.data
            }
        )
    except Exception as e:
        # Don't fail the task if WebSocket update fails
        pass


def send_queue_item_update(queue_item_id):
    """
    Send queue item update via WebSocket
    
    Args:
        queue_item_id: ID of the queue item
    """
    from backend.apps.builds.models import BuildQueue
    from backend.apps.builds.serializers import BuildQueueSerializer
    
    try:
        queue_item = BuildQueue.objects.select_related('package', 'build_job').get(id=queue_item_id)
        serializer = BuildQueueSerializer(queue_item)
        
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'build_job_{queue_item.build_job_id}',
            {
                'type': 'queue_update',
                'data': serializer.data
            }
        )
    except Exception as e:
        # Don't fail the task if WebSocket update fails
        pass
