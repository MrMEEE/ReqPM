"""
WebSocket URL routing for Tasks app
"""
from django.urls import re_path
from backend.apps.tasks.consumers import TaskLogConsumer

websocket_urlpatterns = [
    re_path(r'ws/tasks/(?P<task_id>[a-f0-9\-]+)/log/$', TaskLogConsumer.as_asgi()),
]
