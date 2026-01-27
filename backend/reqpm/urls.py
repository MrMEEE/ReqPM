"""
URL configuration for ReqPM project.
"""
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.reverse import reverse
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)


@api_view(['GET'])
def api_root(request, format=None):
    """API root endpoint"""
    return Response({
        'users': reverse('user-list', request=request, format=format),
        'projects': reverse('project-list', request=request, format=format),
        'packages': reverse('package-list', request=request, format=format),
        'build-jobs': reverse('buildjob-list', request=request, format=format),
        'build-queue': reverse('buildqueue-list', request=request, format=format),
        'repositories': reverse('repository-list', request=request, format=format),
        'auth': {
            'token': reverse('token_obtain_pair', request=request, format=format),
            'token_refresh': reverse('token_refresh', request=request, format=format),
            'register': reverse('register', request=request, format=format),
        },
        'docs': {
            'swagger': reverse('swagger-ui', request=request, format=format),
            'redoc': reverse('redoc', request=request, format=format),
            'schema': reverse('schema', request=request, format=format),
        }
    })


urlpatterns = [
    # API Root
    path('api/', api_root, name='api-root'),
    
    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    
    # API endpoints
    path('api/', include('backend.apps.core.urls')),
    path('api/', include('backend.apps.users.urls')),
    path('api/', include('backend.apps.projects.urls')),
    path('api/', include('backend.apps.packages.urls')),
    path('api/', include('backend.apps.builds.urls')),
    path('api/', include('backend.apps.repositories.urls')),
    path('api/', include('backend.apps.tasks.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
