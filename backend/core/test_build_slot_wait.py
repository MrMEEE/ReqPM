from contextlib import contextmanager
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from backend.apps.packages import tasks
from backend.apps.packages.models import Package
from backend.apps.projects.models import Project


@contextmanager
def _no_slot(job_id):
    raise TimeoutError('No build slot available (0/2 free).')
    yield  # pragma: no cover


class BuildSlotWaitTests(TestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user(
            username='slot-wait', email='slot-wait@example.com',
        )
        project = Project.objects.create(
            name='slot-wait', owner=owner, git_url='https://example.com/project.git',
        )
        self.package = Package.objects.create(
            project=project, name='demo', version='1.0', build_status='not_built',
        )

    def _run(self, **kwargs):
        with patch('backend.apps.builds.concurrency.limiter.try_acquire', side_effect=_no_slot), \
                patch.object(tasks, 'send_package_update'), \
                patch.object(tasks.build_single_package_task, 'apply_async') as requeue:
            tasks.build_single_package_task.apply(args=[self.package.id], kwargs=kwargs, retries=10)
        return requeue

    def test_no_slot_requeues_without_consuming_retries(self):
        requeue = self._run()

        requeue.assert_called_once_with(
            args=[self.package.id], kwargs={'slot_wait': True}, countdown=15,
        )
        self.package.refresh_from_db()
        self.assertEqual(self.package.build_status, 'pending')

    def test_slot_wait_keeps_waiting_while_queued(self):
        self.package.build_status = 'waiting_for_deps'
        self.package.save(update_fields=['build_status'])

        requeue = self._run(slot_wait=True)

        requeue.assert_called_once()
        self.package.refresh_from_db()
        self.assertEqual(self.package.build_status, 'waiting_for_deps')

    def test_cancelled_package_stops_waiting(self):
        # Cancelling a waiting build resets it to not_built.
        requeue = self._run(slot_wait=True)

        requeue.assert_not_called()
        self.package.refresh_from_db()
        self.assertEqual(self.package.build_status, 'not_built')
