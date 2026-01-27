"""
URL configuration for Tasks app
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from backend.apps.tasks.views import TaskResultViewSet

router = DefaultRouter()
router.register(r'tasks', TaskResultViewSet, basename='task')

urlpatterns = router.urls
