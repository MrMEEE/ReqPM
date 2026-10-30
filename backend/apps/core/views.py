"""
Views for Core app
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
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
        settings_row = SystemSettings.load()
        active_builds = limiter.get_active_jobs()
        active_count = limiter.get_active_count()
        max_concurrent = limiter.max_concurrent

        return Response({
            'active_count': active_count,
            'max_concurrent': max_concurrent,
            'worker_concurrency': settings_row.celery_worker_concurrency,
            'ai_worker_concurrency': settings_row.celery_ai_concurrency,
            'available_slots': max(0, max_concurrent - active_count),
            'active_build_ids': active_builds,
        })

    @action(detail=False, methods=['post'])
    def reload_workers(self, request):
        """Reload Celery workers using the configured worker concurrency (admin only)."""
        if not request.user.is_staff:
            return Response(
                {'detail': 'Only administrators can reload workers'},
                status=status.HTTP_403_FORBIDDEN
            )

        import os
        import subprocess
        from pathlib import Path

        script = Path(settings.BASE_DIR) / 'reqpm.sh'
        if not script.exists():
            return Response({'detail': 'reqpm.sh not found'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            outputs = {}
            failed = False
            for service in ('celery', 'celery-tasks', 'celery-projects', 'celery-ai'):
                result = subprocess.run(
                    [str(script), 'restart', service],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    cwd=str(settings.BASE_DIR),
                    env=os.environ.copy(),
                )
                key = service.replace('celery-', '') if service != 'celery' else 'celery'
                outputs[f'{key}_stdout'] = result.stdout
                if result.returncode != 0:
                    failed = True
                    outputs[f'{key}_stderr'] = result.stderr

            if failed:
                return Response(
                    {'detail': 'Failed to reload workers', **outputs},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            return Response({'detail': 'Workers reloaded', **outputs})
        except Exception as e:
            return Response({'detail': f'Failed to reload workers: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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

    @action(detail=False, methods=['get'])
    def ai_fixer_packages(self, request):
        """
        Show packages currently in AI fixer processing.

        A package is considered "in process" when the latest AI-fixer start
        marker is newer than the latest AI-fixer terminal marker in package logs.
        """
        from backend.apps.packages.models import Package
        from backend.core import ai_fixer

        def _extract_correction_description(commit_message):
            msg = (commit_message or '').strip()
            if not msg:
                return ''
            if msg.startswith('AI-fixed:'):
                actions = [a.strip() for a in msg[len('AI-fixed:'):].split(';') if a.strip()]
                return '; '.join(actions)
            return msg

        settings_row = SystemSettings.load()
        cfg = ai_fixer.get_config()
        slot_key = 'ai_fixer:active_count'
        active_count = int(cache.get(slot_key) or 0)
        max_concurrent = int(cfg.get('max_concurrent') or 1)

        in_process = []
        candidates = Package.objects.filter(build_status__in=['building', 'fixing']).select_related('project').order_by('-updated_at')[:250]
        for pkg in candidates:
            logs = list(pkg.logs.order_by('-timestamp').values('timestamp', 'level', 'message')[:200])
            activity = ai_fixer.get_ai_activity(logs, pkg.build_started_at)
            if activity is None:
                continue
            latest_start = activity['started_at']
            latest_ai_log = activity['latest_log']

            elapsed_seconds = None
            if latest_start is not None:
                elapsed_seconds = max(0, int((timezone.now() - latest_start).total_seconds()))

            latest_revision = (
                pkg.spec_revisions
                .order_by('-created_at')
                .values('commit_message', 'ai_feedback_note', 'ai_taught_note')
                .first()
            ) or {}
            correction_description = _extract_correction_description(latest_revision.get('commit_message', ''))
            correction_note = (latest_revision.get('ai_feedback_note') or latest_revision.get('ai_taught_note') or '').strip()

            in_process.append({
                'id': pkg.id,
                'name': pkg.name,
                'version': pkg.version,
                'project_id': pkg.project_id,
                'project_name': getattr(pkg.project, 'name', ''),
                'build_status': pkg.build_status,
                'ai_attempt_count': activity['attempt_count'],
                'ai_started_at': latest_start,
                'ai_elapsed_seconds': elapsed_seconds,
                'state': activity['state'],
                'state_detail': 'waiting_for_slot' if activity['state'] == 'waiting_for_slot' else '',
                'latest_terminal_message': '',
                'last_ai_log': (latest_ai_log or {}).get('message', ''),
                'last_ai_log_at': (latest_ai_log or {}).get('timestamp'),
                'latest_correction_description': correction_description,
                'latest_correction_note': correction_note,
            })

        return Response({
            'enabled': bool(settings_row.ai_fixer_enabled),
            'backend': cfg.get('backend'),
            'active_count': active_count,
            'max_concurrent': max_concurrent,
            'packages': in_process,
        })

    @action(detail=False, methods=['get'])
    def ai_learning_stats(self, request):
        """Aggregate AI feedback/teaching metrics and recent example usage."""
        from collections import Counter
        from backend.apps.packages.models import SpecFileRevision

        def _extract_correction_description(commit_message):
            msg = (commit_message or '').strip()
            if not msg:
                return ''
            if msg.startswith('AI-fixed:'):
                actions = [a.strip() for a in msg[len('AI-fixed:'):].split(';') if a.strip()]
                return '; '.join(actions)
            return msg

        ai_fixes_qs = SpecFileRevision.objects.filter(commit_message__startswith='AI-fixed:')
        taught_qs = SpecFileRevision.objects.filter(ai_taught=True)

        total_ai_fixes = ai_fixes_qs.count()
        feedback_counts = {
            'correct': ai_fixes_qs.filter(ai_feedback='correct').count(),
            'wrong': ai_fixes_qs.filter(ai_feedback='wrong').count(),
            'unknown': ai_fixes_qs.filter(ai_feedback='unknown').count(),
        }

        recent_ai_fixes = list(
            ai_fixes_qs.order_by('-created_at')
            .only('fix_context', 'created_at')[:100]
        )

        example_counter = Counter()
        for rev in recent_ai_fixes:
            ctx = rev.fix_context or {}
            for ex in (ctx.get('examples_used') or []):
                pkg = (ex or {}).get('package', '')
                if not pkg:
                    continue
                key = (
                    pkg,
                    bool((ex or {}).get('taught')),
                    (ex or {}).get('feedback', 'unknown'),
                )
                example_counter[key] += 1

        top_examples = []
        for (pkg, taught, feedback), used_count in example_counter.most_common(8):
            top_examples.append({
                'package': pkg,
                'used_count': used_count,
                'taught': taught,
                'feedback': feedback,
            })

        taught_recent = list(
            taught_qs.order_by('-ai_taught_at')
            .values('id', 'package__id', 'package__name', 'ai_taught_note', 'ai_taught_at', 'commit_message')[:20]
        )
        taught_recent = [
            {
                'revision_id': r['id'],
                'package_id': r['package__id'],
                'package_name': r['package__name'],
                'note': r['ai_taught_note'],
                'taught_at': r['ai_taught_at'],
                'correction_description': _extract_correction_description(r.get('commit_message', '')),
            }
            for r in taught_recent
        ]

        return Response({
            'totals': {
                'ai_fixes': total_ai_fixes,
                'taught_revisions': taught_qs.count(),
                'recent_ai_fixes_considered': len(recent_ai_fixes),
            },
            'feedback': feedback_counts,
            'top_learned_examples_recent': top_examples,
            'recent_taught_revisions': taught_recent,
        })

    @action(detail=False, methods=['post'])
    def ai_unlearn_revision(self, request):
        """Remove a taught revision from AI learning set (admin only)."""
        if not request.user.is_staff:
            return Response(
                {'detail': 'Only administrators can unlearn revisions'},
                status=status.HTTP_403_FORBIDDEN
            )

        from backend.apps.packages.models import SpecFileRevision

        revision_id = request.data.get('revision_id')
        if not revision_id:
            return Response({'detail': 'revision_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            revision = SpecFileRevision.objects.get(id=revision_id)
        except SpecFileRevision.DoesNotExist:
            return Response({'detail': 'Revision not found'}, status=status.HTTP_404_NOT_FOUND)

        # Remove taught markers and strip manual_taught_fix from context actions.
        ctx = dict(revision.fix_context or {})
        actions = [a for a in (ctx.get('actions') or []) if a != 'manual_taught_fix']
        if actions:
            ctx['actions'] = actions
        elif 'actions' in ctx:
            ctx.pop('actions', None)
        ctx.pop('taught', None)

        revision.ai_taught = False
        revision.ai_taught_note = ''
        revision.ai_taught_by = None
        revision.ai_taught_at = None
        revision.fix_context = ctx or None
        revision.save(update_fields=[
            'ai_taught', 'ai_taught_note', 'ai_taught_by', 'ai_taught_at', 'fix_context'
        ])

        return Response({'detail': 'Revision unlearned', 'revision_id': revision.id})

    @action(detail=False, methods=['get'])
    def cleanup_status(self, request):
        """
        Get latest cleanup task metrics and current disk footprint snapshot.
        """
        import subprocess
        from pathlib import Path
        from backend.apps.builds.tasks import get_cleanup_status_snapshot

        def _dir_size_bytes(path: Path):
            if not path.exists():
                return None
            try:
                result = subprocess.run(
                    ['du', '-sb', str(path)],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
                if result.returncode != 0:
                    return None
                token = (result.stdout or '').strip().split()[0]
                return int(token)
            except Exception:
                return None

        build_dir = Path(settings.REQPM['BUILD_DIR'])
        package_builds_dir = build_dir / 'package_builds'
        mock_root = Path('/var/lib/mock')

        disk = None
        try:
            import shutil
            usage = shutil.disk_usage('/')
            disk = {
                'total_bytes': usage.total,
                'used_bytes': usage.used,
                'free_bytes': usage.free,
            }
        except Exception:
            pass

        return Response({
            'cleanup': get_cleanup_status_snapshot(),
            'footprint': {
                'build_dir_bytes': _dir_size_bytes(build_dir),
                'package_builds_bytes': _dir_size_bytes(package_builds_dir),
                'mock_root_bytes': _dir_size_bytes(mock_root),
            },
            'disk': disk,
        })

    @action(detail=False, methods=['post'])
    def run_cleanup_now(self, request):
        """Queue cleanup tasks immediately (admin only)."""
        if not request.user.is_staff:
            return Response(
                {'detail': 'Only administrators can run cleanup tasks'},
                status=status.HTTP_403_FORBIDDEN
            )

        from backend.apps.builds.tasks import cleanup_mock_roots_task, cleanup_old_builds_task

        cfg = SystemSettings.load()
        keep_days = int(cfg.cleanup_builds_after_days or 30)

        mock_task = cleanup_mock_roots_task.delay(3)
        full_task = cleanup_old_builds_task.delay(keep_days)

        return Response({
            'detail': 'Cleanup tasks queued',
            'tasks': {
                'cleanup_mock_roots_task': str(mock_task.id),
                'cleanup_old_builds_task': str(full_task.id),
            },
            'retention_days': keep_days,
        })
