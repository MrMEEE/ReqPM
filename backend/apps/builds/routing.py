"""
WebSocket URL routing for builds app
"""
from django.urls import re_path
from backend.apps.builds.consumers import BuildLogConsumer, BuildJobConsumer

websocket_urlpatterns = [
    re_path(r'ws/builds/queue/(?P<queue_item_id>\d+)/log/$', BuildLogConsumer.as_asgi()),
    re_path(r'ws/builds/(?P<build_job_id>\d+)/$', BuildJobConsumer.as_asgi()),
]
