"""
Celery configuration for ReqPM project.
"""
import os
from celery import Celery
from celery.signals import setup_logging
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
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task to test Celery"""
    print(f'Request: {self.request!r}')
