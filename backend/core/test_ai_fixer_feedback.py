from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from backend.core.ai_fixer import _format_examples, get_past_fix_examples
from backend.apps.packages.tasks import _confirm_successful_ai_fixes


class AIFixerFeedbackTests(SimpleTestCase):
    def test_successful_build_confirms_only_unanswered_ai_revisions(self):
        manager = MagicMock()
        manager.filter.return_value.update.return_value = 1
        fake_model = SimpleNamespace(objects=manager)

        with patch('backend.apps.packages.models.SpecFileRevision', fake_model):
            confirmed = _confirm_successful_ai_fixes(12, [34])

        self.assertEqual(confirmed, 1)
        manager.filter.assert_called_once_with(
            package_id=12,
            id__in=[34],
            commit_message__startswith='AI-fixed:',
            ai_feedback='unknown',
        )
        update_fields = manager.filter.return_value.update.call_args.kwargs
        self.assertEqual(update_fields['ai_feedback'], 'correct')
        self.assertIsNotNone(update_fields['ai_feedback_at'])

    def test_successful_build_does_not_confirm_when_no_ai_fixes_were_applied(self):
        with patch('backend.apps.packages.models.SpecFileRevision') as revision_model:
            confirmed = _confirm_successful_ai_fixes(12, [])

        self.assertEqual(confirmed, 0)
        revision_model.objects.filter.assert_not_called()

    def test_feedback_and_notes_are_retrieved_and_formatted(self):
        package = SimpleNamespace(name='example-package', rpm_path='', last_built_at=None)

        def revision(feedback, note):
            return SimpleNamespace(
                commit_message='AI-fixed: add missing requirement',
                fix_context={
                    'error_keywords': ['foo_bar'],
                    'error_excerpt': 'No module named foo_bar',
                    'actions': ['add_requires'],
                },
                created_at=None,
                package=package,
                ai_feedback=feedback,
                ai_feedback_note=note,
                ai_taught=False,
                ai_taught_note='',
            )

        manager = MagicMock()
        manager.filter.return_value.select_related.return_value.only.return_value = [
            revision('correct', 'This dependency fixed the build.'),
            revision('wrong', 'The package is provided by the runtime already.'),
        ]
        fake_model = SimpleNamespace(objects=manager)

        with patch('backend.apps.packages.models.SpecFileRevision', fake_model):
            examples = get_past_fix_examples('No module named foo_bar')

        prompt_section = _format_examples(examples)
        self.assertEqual([ex['feedback'] for ex in examples], ['correct', 'wrong'])
        self.assertIn('This dependency fixed the build.', prompt_section)
        self.assertIn('The package is provided by the runtime already.', prompt_section)
        self.assertIn('User feedback: this fix worked', prompt_section)
        self.assertIn('User feedback: this fix did not work', prompt_section)
