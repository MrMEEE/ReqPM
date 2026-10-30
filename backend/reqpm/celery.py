"""
Celery configuration for ReqPM project.
"""
import os
from celery import Celery
from celery.signals import setup_logging, worker_ready
from celery.schedules import crontab
from django.conf import settings

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.reqpm.settings')

app = Celery('reqpm')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')


@setup_logging.connect
def config_loggers(*args, **kwargs):
    """Configure logging for Celery to use Django logging"""
    from logging.config import dictConfig
    from django.conf import settings
    dictConfig(settings.LOGGING)


BUILD_QUEUE = 'builds'
DEFAULT_QUEUE = 'celery'


def _worker_queues(sender) -> set[str] | None:
    """Queue names consumed by the starting worker, or None if unknown."""
    try:
        return {q.name for q in sender.task_consumer.queues}
    except Exception:
        return None


@worker_ready.connect
def reset_orphaned_builds(sender=None, **kwargs):
    """
    On worker startup, reset state owned by the queues this worker consumes so
    restarting one worker never disturbs work running on another.

    Build worker: reset packages that were actively building when the worker
    died, plus pending rows that already had a recorded start time (plain
    queued pending builds must survive restarts), and clear the build slots.
    Tasks worker: clear the fetch/spec slots.
    """
    import logging
    logger = logging.getLogger(__name__)
    queues = _worker_queues(sender)
    owns_builds = queues is None or BUILD_QUEUE in queues
    owns_tasks = queues is None or DEFAULT_QUEUE in queues
    try:
        if owns_tasks:
            from backend.apps.builds.concurrency import task_limiter
            task_limiter.clear_all()
            logger.info("Cleared task concurrency semaphore on worker startup")
        if not owns_builds:
            return
        import django
        django.setup()
        from backend.apps.packages.models import Package
        from django.db.models import Q
        # Only reset packages that were actively running when the worker died.
        # Plain queued 'pending' rows are legitimate backlog and should survive
        # a worker restart. 'waiting_for_deps' is also intentional queued state.
        stuck = Package.objects.filter(
            Q(build_status='building') | Q(build_status='fixing', autofix_context={}),
        )
        stuck_pending_started = Package.objects.filter(
            build_status='pending',
            build_started_at__isnull=False,
            autofix_context={},
        )
        count = stuck.count()
        count += stuck_pending_started.count()
        if count:
            ids = list(stuck.values_list('id', flat=True)) + list(stuck_pending_started.values_list('id', flat=True))
            for pkg in Package.objects.filter(id__in=ids):
                # Keep the interrupted attempt's logs as the "last attempt".
                pkg.archive_build_logs()
                pkg.build_status = 'not_built'
                pkg.build_started_at = None
                pkg.build_completed_at = None
                pkg.build_error_message = ''
                pkg.save(update_fields=[
                    'build_status', 'build_started_at', 'build_completed_at', 'build_error_message',
                    'build_log', 'build_root_log', 'build_state_log',
                    'last_build_log', 'last_build_root_log', 'last_build_state_log',
                ])
            logger.warning(f"Reset {count} orphaned builds on worker startup: {ids}")

        from backend.apps.builds.concurrency import limiter
        limiter.clear_all()
        logger.info("Cleared build concurrency semaphore on worker startup")
    except Exception as e:
        logger.error(f"Failed to reset orphaned builds: {e}")


# Load task modules from all registered Django apps.
app.autodiscover_tasks()


# Periodic task schedule
app.conf.beat_schedule = {
    'resume-stuck-projects': {
        'task': 'backend.apps.projects.tasks.resume_stuck_projects_task',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
    'sync-all-projects': {
        'task': 'backend.apps.projects.tasks.sync_all_projects_task',
        'schedule': crontab(minute='0'),  # Hourly; SystemSettings.sync_interval_hours throttles per project
    },
    'cleanup-old-repos': {
        'task': 'backend.apps.projects.tasks.cleanup_old_repos_task',
        'schedule': crontab(minute='0', hour='2'),  # Daily at 2 AM
        'args': (7,)  # Remove repos older than 7 days
    },
    'cleanup-old-builds': {
        'task': 'backend.apps.builds.tasks.cleanup_old_builds_task',
        'schedule': crontab(minute='0', hour='3'),  # Daily at 3 AM
        'args': (30,)  # Remove builds older than 30 days
    },
    'cleanup-stale-mock-roots': {
        'task': 'backend.apps.builds.tasks.cleanup_mock_roots_task',
        'schedule': crontab(minute='15', hour='*/1'),  # Hourly at :15
        'args': (3,)  # Scrub unique mock roots older than 3 days
    },
    'sync-all-repositories': {
        'task': 'backend.apps.repositories.tasks.sync_all_repositories_task',
        'schedule': crontab(minute='*/30'),  # Every 30 minutes
    },
    'monitor-pending-work': {
        'task': 'backend.apps.builds.tasks.monitor_pending_work',
        'schedule': 60.0,  # Every 60 seconds
    },
    'discover-blocked-project-dependencies': {
        'task': 'backend.apps.packages.tasks.discover_blocked_project_dependencies_task',
        'schedule': 300.0,
    },
}

if settings.REQPM.get('EXTRAS_SCAN_ENABLED', True):
    interval_seconds = int(settings.REQPM.get('EXTRAS_SCAN_INTERVAL_SECONDS', 3600))
    if interval_seconds > 0:
        app.conf.beat_schedule['scan-packages-for-missing-extras'] = {
            'task': 'backend.apps.packages.tasks.scan_packages_for_missing_extras_task',
            'schedule': float(interval_seconds),
        }


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task to test Celery"""
    print(f'Request: {self.request!r}')
