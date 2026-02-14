"""
WebSocket URL routing for packages app
"""
from django.urls import re_path
from backend.apps.packages.consumers import PackageBuildLogConsumer

websocket_urlpatterns = [
    re_path(r'ws/packages/(?P<package_id>\d+)/build-log/$', PackageBuildLogConsumer.as_asgi()),
]
