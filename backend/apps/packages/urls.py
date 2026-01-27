"""
Packages URL configuration
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from backend.apps.packages.views import PackageViewSet, PackageBuildViewSet

router = DefaultRouter()
router.register(r'packages', PackageViewSet, basename='package')
router.register(r'builds', PackageBuildViewSet, basename='packagebuild')

urlpatterns = [
    path('', include(router.urls)),
]
