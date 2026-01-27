"""
Serializers for Celery task results
"""
from rest_framework import serializers
from django_celery_results.models import TaskResult


class TaskResultSerializer(serializers.ModelSerializer):
    """Serializer for Celery task results"""
    
    duration = serializers.SerializerMethodField()
    
    class Meta:
        model = TaskResult
        fields = [
            'id', 'task_id', 'task_name', 'task_args', 'task_kwargs',
            'status', 'result', 'traceback',
            'date_created', 'date_done', 'duration'
        ]
        read_only_fields = ['id', 'task_id', 'task_name', 'task_args', 'task_kwargs',
                           'status', 'result', 'traceback',
                           'date_created', 'date_done', 'duration']
    
    def get_duration(self, obj):
        """Calculate task duration in seconds"""
        if obj.date_done and obj.date_created:
            delta = obj.date_done - obj.date_created
            return round(delta.total_seconds(), 2)
        return None
