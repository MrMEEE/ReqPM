"""
Celery configuration for ReqPM project.
"""
import os
from celery import Celery
from celery.signals import setup_logging, worker_ready
from celery.schedules import crontab

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


@worker_ready.connect
def reset_orphaned_builds(**kwargs):
    """
    On worker startup, reset any packages stuck in pending/building.
    These are orphans from a previous worker that crashed or was restarted.
    Also clear the Redis concurrency semaphore so slots aren't permanently lost.
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        import django
        django.setup()
        from backend.apps.packages.models import Package
        stuck = Package.objects.filter(build_status__in=['pending', 'building', 'waiting_for_deps'])
        count = stuck.count()
        if count:
            ids = list(stuck.values_list('id', flat=True))
            stuck.update(
                build_status='not_built',
                build_started_at=None,
                build_completed_at=None,
                build_error_message='',
                build_log='',
            )
            logger.warning(f"Reset {count} orphaned builds on worker startup: {ids}")

        from backend.apps.builds.concurrency import limiter
        limiter.clear_all()
        logger.info("Cleared concurrency semaphore on worker startup")
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
        'schedule': crontab(minute='0', hour='*/6'),  # Every 6 hours
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
    'sync-all-repositories': {
        'task': 'backend.apps.repositories.tasks.sync_all_repositories_task',
        'schedule': crontab(minute='*/30'),  # Every 30 minutes
    },
    'monitor-pending-work': {
        'task': 'backend.apps.builds.tasks.monitor_pending_work',
        'schedule': 60.0,  # Every 60 seconds
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task to test Celery"""
    print(f'Request: {self.request!r}')
