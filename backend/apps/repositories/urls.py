"""
Repositories URL configuration
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from backend.apps.repositories.views import RepositoryViewSet, RepositoryPackageViewSet

router = DefaultRouter()
router.register(r'repositories', RepositoryViewSet, basename='repository')
router.register(r'repository-packages', RepositoryPackageViewSet, basename='repositorypackage')

urlpatterns = [
    path('', include(router.urls)),
]
