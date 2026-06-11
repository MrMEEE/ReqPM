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

    @action(detail=False, methods=['get'])
    def ai_status(self, request):
        """AI fixer status: runtime availability, model catalog, download progress"""
        from backend.core import ai_fixer
        from backend.apps.core.tasks import get_download_status

        models = []
        for key, entry in ai_fixer.MODEL_CATALOG.items():
            models.append({
                'key': key,
                'label': entry['label'],
                'size_mb': entry['size_mb'],
                'downloaded': ai_fixer.is_model_downloaded(key),
                'download': get_download_status(key),
            })

        cfg = ai_fixer.get_config()
        return Response({
            'enabled': cfg['enabled'],
            'backend': cfg['backend'],
            'builtin_runtime_available': ai_fixer.builtin_runtime_available(),
            'builtin_install_hint': 'pip install llama-cpp-python',
            'models': models,
        })

    @action(detail=False, methods=['post'])
    def ai_download_model(self, request):
        """Start downloading a builtin GGUF model (admin only)"""
        if not request.user.is_staff:
            return Response(
                {'detail': 'Only administrators can download models'},
                status=status.HTTP_403_FORBIDDEN
            )

        from backend.core import ai_fixer
        from backend.apps.core.tasks import download_ai_model_task, get_download_status

        model_key = request.data.get('model', '')
        if model_key not in ai_fixer.MODEL_CATALOG:
            return Response({'detail': f'Unknown model: {model_key}'},
                            status=status.HTTP_400_BAD_REQUEST)

        if ai_fixer.is_model_downloaded(model_key):
            return Response({'detail': 'Model already downloaded', 'state': 'done'})

        current = get_download_status(model_key)
        if current.get('state') == 'downloading':
            return Response({'detail': 'Download already in progress', 'state': 'downloading'})

        download_ai_model_task.delay(model_key)
        return Response({'detail': 'Download started', 'state': 'downloading'})

    @action(detail=False, methods=['post'])
    def ai_test(self, request):
        """Test the configured AI backend with a trivial prompt (admin only)"""
        if not request.user.is_staff:
            return Response(
                {'detail': 'Only administrators can run the AI test'},
                status=status.HTTP_403_FORBIDDEN
            )

        from backend.core import ai_fixer
        import time

        try:
            start = time.time()
            raw = ai_fixer._query_llm(
                'Test request. Respond with exactly: '
                '{"error_category": "test", "reasoning": "ok", "actions": [{"op": "no_fix", "value": ""}]}'
            )
            elapsed = round(time.time() - start, 1)
            ai_fixer.parse_actions(raw)  # validates JSON shape
            return Response({'ok': True, 'seconds': elapsed,
                             'detail': f'Backend responded with valid JSON in {elapsed}s'})
        except Exception as e:
            return Response({'ok': False, 'detail': str(e)[:500]})
