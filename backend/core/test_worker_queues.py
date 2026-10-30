from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from backend.apps.builds.concurrency import limiter, task_limiter
from backend.apps.packages import tasks
from backend.apps.packages.models import Package
from backend.apps.projects.models import Project
from backend.reqpm import celery as celery_module
from backend.reqpm.celery import app


def _queue_for(task_name):
    return app.amqp.router.route({}, task_name)['queue'].name


def _sender(*queues):
    return SimpleNamespace(
        task_consumer=SimpleNamespace(queues=[SimpleNamespace(name=q) for q in queues]),
    )


class WorkerQueueRoutingTests(TestCase):
    def test_ai_concurrency_setting_is_independent_and_validated(self):
        from backend.apps.core.models import SystemSettings
        from backend.apps.core.serializers import SystemSettingsSerializer
        settings = SystemSettings.load()
        original_build_concurrency = settings.celery_worker_concurrency
        serializer = SystemSettingsSerializer(settings, data={'celery_ai_concurrency': 3}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        settings.refresh_from_db()
        self.assertEqual(settings.celery_ai_concurrency, 3)
        self.assertEqual(settings.celery_worker_concurrency, original_build_concurrency)
        for value in (0, 21):
            invalid = SystemSettingsSerializer(settings, data={'celery_ai_concurrency': value}, partial=True)
            self.assertFalse(invalid.is_valid())

    def test_builds_go_to_build_queue(self):
        self.assertEqual(_queue_for('backend.apps.packages.tasks.build_single_package_task'), 'builds')
        self.assertEqual(_queue_for('backend.apps.builds.tasks.build_package_task'), 'builds')

    def test_non_build_work_stays_on_default_queue(self):
        for name in (
            'backend.apps.packages.tasks.fetch_package_source_task',
            'backend.apps.packages.tasks.generate_spec_file_task',
            'backend.apps.packages.tasks.fix_and_rebuild_task',
            'backend.apps.builds.tasks.monitor_pending_work',
        ):
            with self.subTest(task=name):
                self.assertEqual(_queue_for(name), 'celery')

    def test_ai_fixes_and_replies_go_to_ai_queue(self):
        self.assertEqual(_queue_for(tasks.ai_fix_package_task.name), 'ai')
        self.assertEqual(_queue_for(tasks.ai_fixer_reply_task.name), 'ai')

    def test_slot_wait_requeue_routes_to_build_queue(self):
        with patch.object(app.amqp, 'send_task_message') as send, \
                patch.object(app, 'producer_or_acquire'):
            tasks.build_single_package_task.apply_async(args=[1], kwargs={'slot_wait': True}, countdown=15)
        self.assertEqual(send.call_args.kwargs['queue'].name, 'builds')


class SeparateSlotTests(TestCase):
    def test_fetch_and_spec_slots_are_independent_of_build_slots(self):
        self.assertNotEqual(limiter.semaphore_key, task_limiter.semaphore_key)
        self.assertNotEqual(limiter.orphan_suspect_key, task_limiter.orphan_suspect_key)
        self.assertEqual(task_limiter.max_concurrent, 2)

    def test_fetch_uses_task_slots_even_when_builds_are_full(self):
        owner = get_user_model().objects.create_user(username='slots', email='slots@example.com')
        project = Project.objects.create(name='slots', owner=owner, git_url='https://example.com/p.git')
        package = Package.objects.create(project=project, name='demo', version='1.0')

        with patch.object(limiter, 'try_acquire', side_effect=AssertionError('build slot used')), \
                patch.object(task_limiter, 'try_acquire', side_effect=TimeoutError('no task slot')) as acquire, \
                patch.object(tasks.fetch_package_source_task, 'retry', side_effect=RuntimeError('retry')):
            with self.assertRaises(RuntimeError):
                tasks.fetch_package_source_task.run(package.id)
        acquire.assert_called_once_with(f'fetch_{package.id}')


class WorkerStartupResetTests(TestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user(username='startup', email='startup@example.com')
        project = Project.objects.create(name='startup', owner=owner, git_url='https://example.com/p.git')
        self.package = Package.objects.create(
            project=project, name='demo', version='1.0', build_status='building',
        )

    def _start(self, sender):
        with patch.object(limiter, 'clear_all') as clear_builds, \
                patch.object(task_limiter, 'clear_all') as clear_tasks:
            celery_module.reset_orphaned_builds(sender=sender)
        self.package.refresh_from_db()
        return clear_builds, clear_tasks

    def test_tasks_worker_restart_leaves_running_builds_alone(self):
        clear_builds, clear_tasks = self._start(_sender('celery'))
        self.assertEqual(self.package.build_status, 'building')
        clear_builds.assert_not_called()
        clear_tasks.assert_called_once()

    def test_projects_worker_restart_leaves_everything_alone(self):
        clear_builds, clear_tasks = self._start(_sender('projects'))
        self.assertEqual(self.package.build_status, 'building')
        clear_builds.assert_not_called()
        clear_tasks.assert_not_called()

    def test_build_worker_restart_resets_interrupted_builds(self):
        clear_builds, clear_tasks = self._start(_sender('builds'))
        self.assertEqual(self.package.build_status, 'not_built')
        clear_builds.assert_called_once()
        clear_tasks.assert_not_called()

    def test_build_worker_restart_preserves_dedicated_ai_fix(self):
        self.package.build_status = 'fixing'
        self.package.autofix_context = {'token': 'test', 'phase': 'ai'}
        self.package.save()
        self._start(_sender('builds'))
        self.assertEqual(self.package.build_status, 'fixing')

    def test_build_worker_restart_preserves_queued_ai_rebuild(self):
        from django.utils import timezone
        self.package.build_status = 'pending'
        self.package.build_started_at = timezone.now()
        self.package.autofix_context = {'token': 'test', 'phase': 'rebuild'}
        self.package.save()
        self._start(_sender('builds'))
        self.assertEqual(self.package.build_status, 'pending')

    def test_ai_worker_startup_does_not_clear_build_slots(self):
        clear_builds, clear_tasks = self._start(_sender('ai'))
        self.assertEqual(self.package.build_status, 'building')
        clear_builds.assert_not_called()
        clear_tasks.assert_not_called()
