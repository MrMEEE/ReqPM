"""
ASGI config for ReqPM project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.reqpm.settings')

django_asgi_app = get_asgi_application()

from backend.apps.builds.routing import websocket_urlpatterns as builds_ws_urls
from backend.apps.projects.routing import websocket_urlpatterns as projects_ws_urls
from backend.apps.packages.routing import websocket_urlpatterns as packages_ws_urls
from backend.apps.tasks.routing import websocket_urlpatterns as tasks_ws_urls

# Combine all WebSocket URL patterns
websocket_urlpatterns = builds_ws_urls + projects_ws_urls + packages_ws_urls + tasks_ws_urls

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
