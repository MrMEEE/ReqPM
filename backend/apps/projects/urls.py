"""
Projects URL configuration
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from backend.apps.projects.views import ProjectViewSet, ProjectBuildConfigViewSet

# Router will be populated when views are created
router = DefaultRouter()
router.register(r'projects', ProjectViewSet, basename='project')
router.register(r'build-configs', ProjectBuildConfigViewSet, basename='buildconfig')

urlpatterns = [
    path('', include(router.urls)),
]
