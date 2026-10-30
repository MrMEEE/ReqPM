"""
Tests for recording AI fixer exchanges (AIFixAttempt) and user replies.
"""
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from backend.apps.packages.models import AIFixAttempt, Package, SpecFileRevision
from backend.apps.projects.models import Project
from backend.core import ai_fixer

SPEC = """Name: demo
Version: 1.0
Release: 1%{?dist}
Summary: demo
License: MIT
BuildRequires: python3-devel

%description
demo

%files -f %{pyproject_files}
"""

CFG = {
    'enabled': True, 'backend': 'ollama', 'model': 'test-model', 'base_url': 'http://x',
    'api_key': '', 'timeout': 5, 'max_attempts': 3, 'max_concurrent': 1,
    'max_log_lines': 50, 'slot_wait_timeout': 5,
}


class ShebangBypassActionTests(SimpleTestCase):
    def test_explicit_action_disables_only_shebang_check(self):
        response = ai_fixer.parse_response(json.dumps({
            'actions': [{'op': 'disable_shebang_check', 'value': 'brp-mangle-shebangs'}],
        }))
        content, descriptions = ai_fixer.apply_actions(SPEC, response['actions'])
        self.assertEqual(content, '%undefine __brp_mangle_shebangs\n' + SPEC)
        self.assertIn('shebang validation bypassed', descriptions[0])

    def test_other_macros_and_commands_are_rejected(self):
        for value in ('__os_install_post', 'brp-strip', '%undefine other', 'brp-mangle-shebangs\n%undefine other'):
            with self.subTest(value=value):
                action = {'op': 'disable_shebang_check', 'value': value}
                with self.assertRaises(ValueError):
                    ai_fixer.parse_response(json.dumps({'actions': [action]}))
                with self.assertRaises(ValueError):
                    ai_fixer.apply_actions(SPEC, [action])

    def test_repeated_bypass_reports_no_change(self):
        action = {'op': 'disable_shebang_check', 'value': 'brp-mangle-shebangs'}
        content, _ = ai_fixer.apply_actions(SPEC, [action])
        with self.assertRaisesRegex(ValueError, 'already disabled'):
            ai_fixer.apply_actions(content, [action])


class GeneralSpecActionTests(SimpleTestCase):
    INSERT = {
        'op': 'insert_lines',
        'value': {'anchor': '%description', 'position': 'before', 'lines': ['%global debug_package %{nil}', '']},
    }

    def parse(self, actions, *ops):
        return ai_fixer.parse_response(
            json.dumps({'actions': actions}), allowed_ops=ai_fixer.enabled_ops({}) | set(ops))

    def test_general_actions_are_disabled_by_default(self):
        rewritten = SPEC.replace('demo\n\n%files', 'demo package\n\n%files')
        for action in (self.INSERT, {'op': 'rewrite_spec', 'value': rewritten}):
            with self.subTest(op=action['op']), self.assertRaisesRegex(ValueError, 'disabled'):
                self.parse([action])

    def test_insert_lines_uses_one_exact_anchor(self):
        actions = self.parse([self.INSERT], 'insert_lines')['actions']
        content, descriptions = ai_fixer.apply_actions(SPEC, actions)
        self.assertIn('BuildRequires: python3-devel\n\n%global debug_package %{nil}\n\n%description', content)
        self.assertEqual(descriptions, ['inserted 2 line(s) before "%description"'])
        with self.assertRaisesRegex(ValueError, 'already present'):
            ai_fixer.apply_actions(content, actions)

    def test_insert_lines_rejects_missing_ambiguous_and_identity_changes(self):
        missing = {**self.INSERT, 'value': {**self.INSERT['value'], 'anchor': '%build'}}
        with self.assertRaisesRegex(ValueError, 'not found'):
            ai_fixer.apply_actions(SPEC, [missing])
        ambiguous_spec = SPEC + '\ndemo\n'
        ambiguous = {**self.INSERT, 'value': {**self.INSERT['value'], 'anchor': 'demo'}}
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            ai_fixer.apply_actions(ambiguous_spec, [ambiguous])
        for lines in (['Version: 2.0'], ['ok\nbad'], [], ['x'] * 41):
            action = {**self.INSERT, 'value': {**self.INSERT['value'], 'lines': lines}}
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                self.parse([action], 'insert_lines')

    def test_rewrite_spec_replaces_spec_but_preserves_identity(self):
        rewritten = SPEC.replace('%files -f %{pyproject_files}', '%files -f %{pyproject_files}\n%doc README.md')
        actions = self.parse([{'op': 'rewrite_spec', 'value': rewritten}], 'rewrite_spec')['actions']
        content, descriptions = ai_fixer.apply_actions(SPEC, actions)
        self.assertEqual(content, rewritten)
        self.assertEqual(descriptions, ['rewrote complete spec (+1/-0 lines)'])

        changed = rewritten.replace('Version: 1.0', 'Version: 2.0')
        with self.assertRaisesRegex(ValueError, 'must not change Version'):
            ai_fixer.apply_actions(SPEC, [{'op': 'rewrite_spec', 'value': changed}])
        with self.assertRaisesRegex(ValueError, 'identical'):
            ai_fixer.apply_actions(SPEC, [{'op': 'rewrite_spec', 'value': SPEC}])

    def test_rewrite_spec_must_be_complete_and_alone(self):
        for value in ('Name: demo\n', SPEC.replace('%files', '%install'), 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.parse([{'op': 'rewrite_spec', 'value': value}], 'rewrite_spec')
        with self.assertRaisesRegex(ValueError, 'only action'):
            self.parse([
                {'op': 'rewrite_spec', 'value': SPEC + '\n'},
                {'op': 'set_license', 'value': 'MIT'},
            ], 'rewrite_spec')

    def test_prompt_and_spec_context_only_expand_when_enabled(self):
        self.assertNotIn('insert_lines', ai_fixer.get_system_prompt({}))
        self.assertIn('## Relevant spec sections', ai_fixer._spec_prompt_section(SPEC, {}))
        cfg = {'allow_insert_lines': True, 'allow_spec_rewrite': True}
        prompt = ai_fixer.get_system_prompt(cfg)
        self.assertIn('- insert_lines:', prompt)
        self.assertIn('- rewrite_spec:', prompt)
        self.assertEqual(ai_fixer._spec_prompt_section(SPEC, cfg), f'## Full spec file\n{SPEC}')


class OpenAICompletionBudgetTests(SimpleTestCase):
    def setUp(self):
        config = mock.patch.object(ai_fixer, 'get_config', return_value={**CFG, 'backend': 'openai'})
        config.start()
        self.addCleanup(config.stop)
        post = mock.patch.object(ai_fixer.requests, 'post')
        self.post = post.start()
        self.addCleanup(post.stop)

    def response(self, finish_reason, **message):
        response = mock.Mock()
        response.json.return_value = {
            'choices': [{'finish_reason': finish_reason, 'message': {'role': 'assistant', **message}}],
        }
        return response

    def test_completed_response_has_room_for_reasoning(self):
        self.post.return_value = self.response('stop', content='{"actions": []}')

        self.assertEqual(ai_fixer._query_llm_messages([]), '{"actions": []}')
        self.assertEqual(self.post.call_count, 1)
        self.assertEqual(self.post.call_args.kwargs['json']['max_tokens'], 8192)

    def test_reasoning_only_length_response_retries_with_larger_budget(self):
        self.post.side_effect = [
            self.response('length', reasoning_content='private intermediate reasoning'),
            self.response('stop', content='{"actions": []}'),
        ]

        self.assertEqual(ai_fixer._query_llm_messages([{'role': 'user', 'content': 'Fix this'}]),
                         '{"actions": []}')
        payloads = [call.kwargs['json'] for call in self.post.call_args_list]
        self.assertEqual([payload['max_tokens'] for payload in payloads], [8192, 16384])
        self.assertEqual(payloads[0]['messages'], payloads[1]['messages'])

    def test_partial_content_at_length_limit_is_not_accepted(self):
        self.post.side_effect = [
            self.response('length', content='{"actions": []}'),
            self.response('stop', content='{"actions": [{"op": "no_fix", "value": ""}]}'),
        ]

        self.assertEqual(ai_fixer._query_llm_messages([]),
                         '{"actions": [{"op": "no_fix", "value": ""}]}')
        self.assertEqual(self.post.call_count, 2)

    def test_repeated_truncation_fails_explicitly_without_leaking_reasoning(self):
        self.post.return_value = self.response('length', reasoning_content='private reasoning')

        with self.assertRaisesRegex(RuntimeError, 'output token limit.*16384') as raised:
            ai_fixer._query_llm_messages([])

        self.assertEqual(self.post.call_count, 2)
        self.assertNotIn('private reasoning', str(raised.exception))

    def test_missing_content_without_truncation_does_not_retry(self):
        self.post.return_value = self.response('stop', reasoning_content='private reasoning')

        with self.assertRaisesRegex(RuntimeError, 'no assistant text'):
            ai_fixer._query_llm_messages([])

        self.assertEqual(self.post.call_count, 1)

    def test_http_error_does_not_retry(self):
        response = self.response('stop', content='{"actions": []}')
        response.raise_for_status.side_effect = ai_fixer.requests.HTTPError('HTTP error')
        self.post.return_value = response

        with self.assertRaises(ai_fixer.requests.HTTPError):
            ai_fixer._query_llm_messages([])

        self.assertEqual(self.post.call_count, 1)
        response.json.assert_not_called()


class AIFixAttemptTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='u', email='u@example.com', password='p')
        self.project = Project.objects.create(name='p', git_url='https://example.com/x.git', owner=self.user)
        self.package = Package.objects.create(
            project=self.project, name='demo', version='1.0',
            build_log='error: Installed (but unpackaged) file(s) found:\n   /usr/bin/demo',
        )
        SpecFileRevision.objects.create(package=self.package, content=SPEC, commit_message='Initial spec file generated')

        patches = [
            mock.patch.object(ai_fixer, 'get_config', return_value=dict(CFG)),
            mock.patch.object(ai_fixer, '_acquire_slot_blocking', return_value=True),
            mock.patch.object(ai_fixer, '_release_slot'),
            mock.patch.object(ai_fixer, 'get_past_fix_examples', return_value=[]),
            mock.patch.object(ai_fixer, 'validate_spec', return_value=True),
            mock.patch('backend.apps.packages.tasks.log_package'),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_openai_chat_response_extracts_content_string(self):
        content = ai_fixer._extract_openai_chat_content({
            'choices': [{'message': {'role': 'assistant', 'content': '{"actions": []}'}}],
        })

        self.assertEqual(content, '{"actions": []}')

    def test_openai_chat_response_extracts_text_blocks(self):
        content = ai_fixer._extract_openai_chat_content({
            'choices': [{
                'message': {
                    'role': 'assistant',
                    'content': [
                        {'type': 'text', 'text': '{"error_category":'},
                        {'type': 'output_text', 'text': '"unknown"}'},
                    ],
                },
            }],
        })

        self.assertEqual(content, '{"error_category":"unknown"}')

    def test_openai_chat_response_without_content_has_actionable_error(self):
        with self.assertRaisesRegex(
            RuntimeError,
            r'no assistant text in message\.content .*finish_reason=tool_calls; message_fields=role, tool_calls',
        ):
            ai_fixer._extract_openai_chat_content({
                'choices': [{
                    'finish_reason': 'tool_calls',
                    'message': {'role': 'assistant', 'tool_calls': []},
                }],
            })

    def _run(self, response):
        with mock.patch.object(ai_fixer, '_query_llm_messages', return_value=response) as q:
            attempt = ai_fixer.attempt_ai_fix_detailed(self.package.id, self.package.build_log)
        return attempt, q

    def test_no_fix_keeps_reasoning(self):
        attempt, _ = self._run(json.dumps({
            'error_category': 'network', 'reasoning': 'Needs network access during build',
            'actions': [{'op': 'no_fix', 'value': ''}],
        }))
        self.assertEqual(attempt.status, 'no_fix')
        self.assertEqual(attempt.reasoning, 'Needs network access during build')
        self.assertIn('Needs network access', ai_fixer.summarize_attempt(attempt))
        self.assertIn('AI fixer could not propose a fix', ai_fixer.summarize_attempt(attempt))
        self.assertIn('network', attempt.raw_response)
        self.assertEqual(self.package.spec_revisions.count(), 1)

    def test_invalid_response_is_recorded(self):
        attempt, _ = self._run('I am not sure what to do here')
        self.assertEqual(attempt.status, 'invalid_response')
        self.assertEqual(attempt.raw_response, 'I am not sure what to do here')
        self.assertTrue(attempt.error_message)

    def test_llm_error_is_recorded(self):
        with mock.patch.object(ai_fixer, '_query_llm_messages', side_effect=RuntimeError('boom')):
            attempt = ai_fixer.attempt_ai_fix_detailed(self.package.id, self.package.build_log)
        self.assertEqual(attempt.status, 'error')
        self.assertIn('boom', attempt.error_message)

    def test_abandoned_attempt_is_closed_without_changing_historical_model(self):
        attempt = AIFixAttempt.objects.create(
            package=self.package, status='running', model_name='openai/previous-model',
        )
        AIFixAttempt.objects.filter(id=attempt.id).update(
            created_at=timezone.now() - timedelta(hours=2),
        )
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get(f'/api/packages/{self.package.id}/ai_attempts/')

        self.assertEqual(response.status_code, 200)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'error')
        self.assertEqual(attempt.model_name, 'openai/previous-model')
        self.assertIn('interrupted or abandoned', attempt.error_message)
        self.assertIsNotNone(attempt.completed_at)
        self.assertEqual(response.data[0]['status'], 'error')

    def test_recent_running_and_queued_attempts_are_not_expired(self):
        running = AIFixAttempt.objects.create(package=self.package, status='running')
        pending = AIFixAttempt.objects.create(package=self.package, status='pending')
        AIFixAttempt.objects.filter(id=pending.id).update(
            created_at=timezone.now() - timedelta(hours=2),
        )

        self.assertEqual(ai_fixer.expire_abandoned_attempts(self.package.id), 0)
        running.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(running.status, 'running')
        self.assertEqual(pending.status, 'pending')

    def test_attempt_on_package_still_fixing_is_not_expired(self):
        self.package.build_status = 'fixing'
        self.package.save(update_fields=['build_status'])
        attempt = AIFixAttempt.objects.create(package=self.package, status='running')
        AIFixAttempt.objects.filter(id=attempt.id).update(
            created_at=timezone.now() - timedelta(hours=2),
        )

        self.assertEqual(ai_fixer.expire_abandoned_attempts(self.package.id), 0)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'running')

    def test_exhausted_openai_output_budget_is_recorded_without_applying_fix(self):
        response = mock.Mock()
        response.json.return_value = {
            'choices': [{
                'finish_reason': 'length',
                'message': {'role': 'assistant', 'reasoning_content': 'private reasoning'},
            }],
        }
        with mock.patch.object(ai_fixer, 'get_config', return_value={**CFG, 'backend': 'openai'}), \
                mock.patch.object(ai_fixer.requests, 'post', return_value=response) as post:
            attempt = ai_fixer.attempt_ai_fix_detailed(self.package.id, self.package.build_log)

        self.assertEqual(post.call_count, 2)
        self.assertEqual(attempt.status, 'error')
        self.assertIn('16384', attempt.error_message)
        self.assertNotIn('private reasoning', attempt.error_message)
        self.assertEqual(attempt.raw_response, '')
        self.assertIsNone(attempt.revision)
        self.assertEqual(self.package.spec_revisions.count(), 1)

    def test_applied_fix_links_revision(self):
        attempt, _ = self._run(json.dumps({
            'error_category': 'unpackaged', 'reasoning': 'binary not listed',
            'actions': [{'op': 'add_files_entry', 'value': '%{_bindir}/demo'}],
        }))
        self.assertEqual(attempt.status, 'applied')
        self.assertIsNotNone(attempt.revision)
        self.assertEqual(attempt.revision.fix_context['ai_attempt_id'], attempt.id)
        self.assertTrue(ai_fixer.attempt_ai_fix.__name__)

    def test_cancelled_dedicated_fix_does_not_change_spec(self):
        self.package.build_status = 'fixing'
        self.package.autofix_context = {'token': 'test-token', 'phase': 'ai'}
        self.package.save()

        def cancel_during_query(*args, **kwargs):
            Package.objects.filter(pk=self.package.pk).update(
                build_status='not_built', autofix_context={},
            )
            return json.dumps({
                'actions': [{'op': 'add_files_entry', 'value': '%{_bindir}/demo'}],
            })

        with mock.patch.object(ai_fixer, '_query_llm_messages', side_effect=cancel_during_query):
            attempt = ai_fixer.attempt_ai_fix_detailed(self.package.id, self.package.build_log)
        self.assertEqual(attempt.status, 'error')
        self.assertIn('cancelled or superseded', attempt.error_message)
        self.assertEqual(self.package.spec_revisions.count(), 1)

    def test_unchanged_when_actions_skipped(self):
        attempt, _ = self._run(json.dumps({
            'error_category': 'deps', 'reasoning': 'self dep',
            'actions': [{'op': 'add_buildrequires', 'value': 'python3-demo'}],
        }))
        self.assertEqual(attempt.status, 'unchanged')
        self.assertEqual(self.package.spec_revisions.count(), 1)

    def test_rejected_pip_proposal_gets_specific_feedback_and_can_conclude_no_fix(self):
        pip_proposal = json.dumps({
            'error_category': 'missing-pip', 'reasoning': 'Install pip',
            'actions': [{'op': 'add_buildrequires', 'value': 'python3dist(pip)'}],
        })
        no_fix = json.dumps({
            'error_category': 'install-macro',
            'reasoning': 'The install macro must handle unmatched dist-info globs.',
            'actions': [{'op': 'no_fix', 'value': ''}],
        })
        with mock.patch.object(ai_fixer, '_query_llm_messages', side_effect=[pip_proposal, no_fix]) as query:
            attempt = ai_fixer.attempt_ai_fix_detailed(self.package.id, self.package.build_log)

        self.assertEqual(query.call_count, 2)
        self.assertEqual(attempt.status, 'no_fix')
        self.assertEqual(attempt.parent.status, 'unchanged')
        self.assertIn("normalizes to 'python3-pip'", attempt.parent.error_message)
        messages = query.call_args.args[0]
        self.assertEqual(messages[1]['content'], pip_proposal)
        self.assertIn(attempt.parent.error_message, messages[2]['content'])
        self.assertIn('use no_fix', messages[2]['content'])
        self.assertEqual(self.package.spec_revisions.count(), 1)

    def test_reconsideration_can_apply_a_different_allowed_action(self):
        responses = [
            json.dumps({
                'actions': [{'op': 'add_buildrequires', 'value': 'python3dist(pip)'}],
            }),
            json.dumps({
                'actions': [{'op': 'add_files_entry', 'value': '%{_bindir}/demo'}],
            }),
        ]
        with mock.patch.object(ai_fixer, '_query_llm_messages', side_effect=responses) as query:
            attempt = ai_fixer.attempt_ai_fix_detailed(self.package.id, self.package.build_log)

        self.assertEqual(query.call_count, 2)
        self.assertEqual(attempt.status, 'applied')
        self.assertEqual(attempt.parent.status, 'unchanged')
        self.assertEqual(self.package.spec_revisions.count(), 2)
        self.assertEqual(attempt.revision.fix_context['ai_attempt_id'], attempt.id)

    def test_repeated_unusable_proposal_is_bounded(self):
        response = json.dumps({
            'actions': [{'op': 'add_buildrequires', 'value': 'python3dist(pip)'}],
        })
        attempt, query = self._run(response)
        self.assertEqual(query.call_count, 2)
        self.assertEqual(attempt.status, 'unchanged')
        self.assertEqual(self.package.spec_revisions.count(), 1)

    def test_self_dependency_reconsideration_receives_explicit_rejection(self):
        proposal = json.dumps({
            'reasoning': 'Install the missing module',
            'actions': [{'op': 'add_buildrequires', 'value': 'python3dist(demo)'}],
        })
        attempt, query = self._run(proposal)

        self.assertEqual(query.call_count, 2)
        self.assertEqual(attempt.status, 'unchanged')
        self.assertEqual(attempt.parent.status, 'unchanged')
        self.assertLessEqual(attempt.parent.completed_at, attempt.created_at)
        self.assertIn('refers to the package being built (demo)', attempt.parent.error_message)
        self.assertIn('cannot be its own build/runtime dependency',
                      query.call_args.args[0][-1]['content'])
        self.assertEqual(self.package.spec_revisions.count(), 1)

    def test_prompt_includes_actual_build_and_install_commands(self):
        spec = SPEC.replace('%description', '%build\n%pyproject_wheel\n\n'
                            '%install\n%pyproject_install\n%pyproject_save_files demo\n\n%description')
        context = ai_fixer.extract_spec_context(spec)
        self.assertIn('%pyproject_wheel', context)
        self.assertIn('%pyproject_install', context)
        self.assertNotIn('%description', context)

    def test_reply_includes_history_and_user_message(self):
        first, _ = self._run(json.dumps({
            'error_category': 'unknown', 'reasoning': 'cannot tell', 'actions': [{'op': 'no_fix', 'value': ''}],
        }))
        reply = AIFixAttempt.objects.create(
            package=self.package, parent=first, source='user_reply',
            user_message='The binary /usr/bin/demo must be added to %files', created_by=self.user,
        )
        answer = json.dumps({
            'error_category': 'unpackaged', 'reasoning': 'thanks',
            'actions': [{'op': 'add_files_entry', 'value': '%{_bindir}/demo'}],
        })
        with mock.patch.object(ai_fixer, '_query_llm_messages', return_value=answer) as q:
            applied = ai_fixer.reply_to_attempt(reply.id)
        self.assertTrue(applied)
        messages = q.call_args[0][0]
        self.assertEqual([m['role'] for m in messages], ['user', 'assistant', 'user'])
        self.assertEqual(messages[1]['content'], first.raw_response)
        self.assertIn('must be added to %files', messages[2]['content'])
        self.assertIn('cannot tell', messages[2]['content'])
        reply.refresh_from_db()
        self.assertEqual(reply.status, 'applied')
        self.assertEqual(reply.revision.created_by, self.user)
        self.assertEqual(reply.revision.fix_context['user_message'], reply.user_message)

    def test_conversation_is_truncated(self):
        parent = None
        for i in range(8):
            parent = AIFixAttempt.objects.create(
                package=self.package, parent=parent, prompt=f'p{i}', raw_response=f'r{i}', status='no_fix')
        messages = ai_fixer.build_conversation(parent)
        contents = [m['content'] for m in messages]
        self.assertEqual(contents[:2], ['p0', 'r0'])
        self.assertEqual(contents[-2:], ['p7', 'r7'])
        self.assertEqual(len(messages), 2 * ai_fixer._MAX_HISTORY_EXCHANGES)

    def test_reply_endpoint(self):
        first, _ = self._run(json.dumps({
            'error_category': 'x', 'reasoning': 'y', 'actions': [{'op': 'no_fix', 'value': ''}],
        }))
        client = APIClient()
        client.force_authenticate(self.user)
        with mock.patch.object(ai_fixer, 'is_enabled', return_value=True), \
                mock.patch('backend.apps.packages.tasks.ai_fixer_reply_task.delay') as delay, \
                mock.patch('backend.apps.packages.views.PackageViewSet.get_object', return_value=self.package):
            resp = client.post(
                f'/api/packages/{self.package.id}/ai_attempts/{first.id}/reply/',
                {'message': 'try harder', 'rebuild': False}, format='json')
            self.assertEqual(resp.status_code, 202, resp.content)
            delay.assert_called_once()
            listing = client.get(f'/api/packages/{self.package.id}/ai_attempts/')
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()), 2)
        child = AIFixAttempt.objects.get(id=resp.json()['id'])
        self.assertEqual(child.parent_id, first.id)
        self.assertFalse(child.rebuild_requested)
