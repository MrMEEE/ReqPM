"""
Views for Celery task results
"""
from rest_framework import viewsets, filters
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django_celery_results.models import TaskResult

from backend.apps.tasks.serializers import TaskResultSerializer


class TaskResultViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing Celery task results
    """
    queryset = TaskResult.objects.all()
    serializer_class = TaskResultSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'task_name']
    search_fields = ['task_name', 'task_id']
    ordering_fields = ['date_created', 'date_done', 'status']
    ordering = ['-date_created']
