from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from backend.apps.packages.models import Package, PackageLog
from backend.apps.projects.models import Project
from backend.core import ai_fixer


class AIActivityTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username='ai-activity', email='ai-activity@example.com',
        )
        project = Project.objects.create(
            name='activity', git_url='https://example.com/repo.git', owner=user,
        )
        self.started_at = timezone.now() - timedelta(minutes=2)
        self.package = Package.objects.create(
            project=project, name='demo', version='1', build_status='fixing',
            build_started_at=self.started_at,
        )
        self.client = APIClient()
        self.client.force_authenticate(user)

    def log(self, seconds, message):
        entry = PackageLog.objects.create(package=self.package, message=message)
        PackageLog.objects.filter(id=entry.id).update(
            timestamp=self.started_at + timedelta(seconds=seconds),
        )

    def activity(self):
        original_get = cache.get
        with patch('backend.apps.core.views.cache.get', side_effect=lambda key, *args, **kwargs: (
            0 if key == ai_fixer._SLOT_KEY else original_get(key, *args, **kwargs)
        )):
            response = self.client.get('/api/settings/ai_fixer_packages/')
        self.assertEqual(response.status_code, 200)
        return response.data

    def start(self, seconds=1):
        self.log(seconds, 'Rule-based fixers exhausted, trying AI fixer (waiting for slot up to 45s)...')

    def test_previous_build_wait_does_not_appear_or_count(self):
        self.start(-120)
        self.log(-119, 'AI fixer acquired a slot')
        self.assertEqual(self.activity()['packages'], [])
        self.assertEqual(ai_fixer._estimate_active_ai_running_count(), 0)

    def test_acquired_slot_overrides_earlier_wait_and_counts_as_running(self):
        self.start()
        self.log(2, 'AI fixer acquired a slot for demo, querying model now')
        data = self.activity()
        self.assertEqual(data['packages'][0]['state'], 'running')
        self.assertEqual(data['packages'][0]['state_detail'], '')
        self.assertEqual(ai_fixer._estimate_active_ai_running_count(), 1)

    def test_current_wait_is_not_counted_as_running(self):
        self.start()
        self.assertEqual(self.activity()['packages'][0]['state'], 'waiting_for_slot')
        self.assertEqual(ai_fixer._estimate_active_ai_running_count(), 0)

    def test_terminal_outcome_removes_activity(self):
        self.start()
        self.log(2, 'AI fixer acquired a slot')
        self.log(3, 'AI fixer could not propose a fix: the proposed actions did not change the spec')
        self.assertEqual(self.activity()['packages'], [])
        self.assertEqual(ai_fixer._estimate_active_ai_running_count(), 0)

    def test_new_wait_overrides_previous_cycle_acquisition(self):
        self.start()
        self.log(2, 'AI fixer acquired a slot')
        self.log(3, 'AI fixer proposed a spec fix')
        self.start(4)
        self.assertEqual(self.activity()['packages'][0]['state'], 'waiting_for_slot')
        self.assertEqual(ai_fixer._estimate_active_ai_running_count(), 0)

    def test_failed_package_is_not_ai_activity(self):
        self.start()
        self.package.build_status = 'failed'
        self.package.save(update_fields=['build_status'])
        self.assertEqual(self.activity()['packages'], [])
        self.assertEqual(ai_fixer._estimate_active_ai_running_count(), 0)
