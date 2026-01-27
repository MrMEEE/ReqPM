"""
Views for Core app
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from backend.apps.core.models import SystemSettings
from backend.apps.core.serializers import SystemSettingsSerializer
from backend.apps.builds.concurrency import limiter


class SystemSettingsViewSet(viewsets.ViewSet):
    """
    ViewSet for SystemSettings
    
    Singleton settings - always returns/updates the single settings instance
    """
    
    permission_classes = [IsAuthenticated]
    
    def list(self, request):
        """Get system settings"""
        settings = SystemSettings.load()
        serializer = SystemSettingsSerializer(settings)
        return Response(serializer.data)
    
    def retrieve(self, request, pk=None):
        """Get system settings (same as list since it's a singleton)"""
        settings = SystemSettings.load()
        serializer = SystemSettingsSerializer(settings)
        return Response(serializer.data)
    
    def update(self, request, pk=None):
        """Update system settings (admin only)"""
        if not request.user.is_staff:
            return Response(
                {'detail': 'Only administrators can modify settings'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        settings = SystemSettings.load()
        serializer = SystemSettingsSerializer(settings, data=request.data, partial=False)
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def partial_update(self, request, pk=None):
        """Partially update system settings (admin only)"""
        if not request.user.is_staff:
            return Response(
                {'detail': 'Only administrators can modify settings'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        settings = SystemSettings.load()
        serializer = SystemSettingsSerializer(settings, data=request.data, partial=True)
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def build_status(self, request):
        """Get current build concurrency status"""
        active_builds = limiter.get_active_builds()
        active_count = limiter.get_active_count()
        max_concurrent = limiter.max_concurrent
        
        return Response({
            'active_count': active_count,
            'max_concurrent': max_concurrent,
            'available_slots': max(0, max_concurrent - active_count),
            'active_build_ids': active_builds,
        })
