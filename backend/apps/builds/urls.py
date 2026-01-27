"""
Builds URL configuration
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from backend.apps.builds.views import (
    BuildJobViewSet, BuildQueueViewSet, BuildWorkerViewSet, available_targets
)
from backend.apps.builds.health import system_health

router = DefaultRouter()
router.register(r'build-jobs', BuildJobViewSet, basename='buildjob')
router.register(r'build-queue', BuildQueueViewSet, basename='buildqueue')
router.register(r'build-workers', BuildWorkerViewSet, basename='buildworker')

urlpatterns = [
    path('', include(router.urls)),
    path('available-targets/', available_targets, name='available-targets'),
    path('system-health/', system_health, name='system-health'),
]
