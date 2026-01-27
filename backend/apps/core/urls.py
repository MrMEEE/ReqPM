"""
URL configuration for Core app
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from backend.apps.core.views import SystemSettingsViewSet

router = DefaultRouter()
router.register(r'settings', SystemSettingsViewSet, basename='settings')

urlpatterns = [
    path('', include(router.urls)),
]
