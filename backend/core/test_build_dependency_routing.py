import tempfile
from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from backend.apps.packages import tasks
from backend.apps.packages.tasks import _run_autofix_round as run_fixers
from backend.apps.packages.models import Package, PackageDependency, SpecFileRevision
from backend.apps.projects.models import Project
from backend.plugins.builders.base import BuildResult


class BuildDependencyRoutingTests(TestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user(
            username='dependency-routing', email='dependency-routing@example.com',
        )
        self.project = Project.objects.create(
            name='dependency-routing', owner=owner, git_url='https://example.com/project.git',
        )
        self.package = Package.objects.create(
            project=self.project, name='demo', version='1.0',
        )
        SpecFileRevision.objects.create(
            package=self.package,
            content='Name: python3-demo\nVersion: 1.0\n%description\ndemo\n%files\n',
            commit_message='Initial spec file generated',
        )
        self.dependency = Package.objects.create(
            project=self.project, name='cython', version='3.0.12', build_status='not_built',
        )
        self.missing_log = (
            "No matching package to install: 'python3dist(cython) = 3.0.12'\n"
            'Not all dependencies satisfied\nError: Some packages could not be found.'
        )
        self.packaging_log = (
            'RPM build errors:\nerror: File not found: '
            '/builddir/build/BUILDROOT/python3-demo/usr/src/debug/demo/missing.c'
        )
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        build_dir = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(self.settings(
            REQPM={**settings.REQPM, 'BUILD_DIR': build_dir},
        ))
        sources = Path(build_dir) / 'sources' / self.package.name
        sources.mkdir(parents=True)
        (sources / 'demo-1.0.tar.gz').write_bytes(b'source archive placeholder')

        self.builder = Mock()
        self.builder.build_srpm.return_value = BuildResult(success=True, srpm_path='demo.src.rpm')
        self.stack.enter_context(patch(
            'backend.plugins.builders.get_builder', return_value=self.builder,
        ))
        self.stack.enter_context(patch(
            'backend.apps.builds.concurrency.limiter.try_acquire', return_value=nullcontext(),
        ))
        self.stack.enter_context(patch.object(
            tasks, '_ensure_spec_source0_macro', side_effect=lambda package, revision, **kw: revision,
        ))
        for name in ('send_package_update', 'log_package'):
            self.stack.enter_context(patch.object(tasks, name))
        self.stack.enter_context(patch.object(tasks, '_update_project_local_repo', return_value=None))
        self.stack.enter_context(patch('backend.apps.projects.tasks.log_project'))
        self.queue = self.stack.enter_context(patch.object(tasks.build_single_package_task, 'delay'))
        self.pypi = self.stack.enter_context(patch('backend.core.pypi_client.PyPIClient'))
        self.fixer_round = self.stack.enter_context(patch.object(
            tasks, '_run_autofix_round', return_value=None,
        ))
        self.ai_fixer = self.stack.enter_context(patch.object(tasks, '_detect_and_fix_with_ai'))
        self.ai_queue = self.stack.enter_context(patch.object(tasks.ai_fix_package_task, 'delay'))
        self.stack.enter_context(patch('backend.core.ai_fixer.is_enabled', return_value=True))
        self.stack.enter_context(patch('backend.core.ai_fixer.get_config', return_value={'max_attempts': 3}))

    def run_build(self):
        tasks.build_single_package_task.run(self.package.id)
        self.package.refresh_from_db()

    def test_resolver_selects_shared_compatible_release_and_queues_rebuild(self):
        self.dependency.is_direct_dependency = False
        self.dependency.version = '4.1.0'
        self.dependency.build_status = 'completed'
        self.dependency.save()
        item = '(python3dist(cython) >= 3.11 with python3dist(cython) < 4~~)'
        self.package.analyzed_errors = [{'category': 'Missing Packages', 'items': [item]}]
        self.package.save()
        other = Package.objects.create(
            project=self.project, name='other',
            analyzed_errors=[{
                'category': 'Missing Dependencies',
                'items': ['python3dist(cython) >= 3.12'],
            }],
        )
        self.pypi.return_value.get_all_versions.return_value = [
            '3.9.0', '3.11.0', '3.12.0', '4.1.0', '5.0rc1',
        ]
        with patch('backend.apps.packages.artifact_cleanup.wipe_package_artifacts_for_rebuild'), \
                patch.object(tasks.generate_spec_file_task, 'delay') as generate:
            result = tasks._resolve_missing_dep_status(self.package, self.project)
        self.dependency.refresh_from_db()
        self.assertEqual(self.dependency.version, '3.12.0')
        self.assertEqual(self.dependency.build_status, 'pending')
        self.assertEqual(result, 'dep_build_pending')
        generate.assert_called_once_with(self.dependency.pk, force=True, auto_build=True)

    def test_resolver_preserves_version_when_constraints_conflict(self):
        self.dependency.is_direct_dependency = False
        self.dependency.version = '4.1.0'
        self.dependency.save()
        self.pypi.return_value.get_all_versions.return_value = ['3.12.0', '4.1.0']
        PackageDependency.objects.create(
            package=self.package, depends_on=self.dependency, version_constraint='cython>=4',
        )
        with patch.object(tasks.generate_spec_file_task, 'delay') as generate:
            tasks._reconcile_dependency_versions(
                self.package, ['python3dist(cython) < 4'], [self.dependency],
            )
        self.dependency.refresh_from_db()
        self.assertEqual(self.dependency.version, '4.1.0')
        generate.assert_not_called()
        tasks.log_package.assert_called_with(
            self.package.pk, 'warning',
            'No compatible release of cython satisfies all recorded project constraints: python3dist(cython) < 4',
        )

    def test_enabled_extra_without_rpm_declaration_is_repaired_and_rebuilt_once(self):
        from backend.core.spec_generator import ensure_enabled_extras
        from backend.apps.packages.models import PackageExtra
        spec = (
            'Name: python3-cython\nVersion: 3.0.12\n'
            '%install\n%pyproject_save_files cython\n%files -f %{pyproject_files}\n'
            '%changelog\n- Preserve history\n'
        )
        SpecFileRevision.objects.create(package=self.dependency, content=spec)
        PackageExtra.objects.create(package=self.dependency, name='toml', enabled=True)
        self.dependency.build_status = 'completed'
        self.dependency.save()
        item = 'python3dist(cython[toml]) = 3.0.12'
        self.package.analyzed_errors = [{'category': 'Missing Packages', 'items': [item]}]
        self.package.save()
        self.assertFalse(tasks._has_required_extras_enabled(self.dependency, {'toml'}))
        with patch('backend.apps.packages.artifact_cleanup.wipe_package_artifacts_for_rebuild'):
            status = tasks._resolve_missing_dep_status(self.package, self.project)
        self.assertEqual(status, 'dep_build_pending')
        self.queue.assert_called_once_with(self.dependency.id)
        revision = self.dependency.spec_revisions.order_by('-created_at').first()
        self.assertIn('%pyproject_extras_subpkg -n python3-cython toml', revision.content)
        self.assertIn('- Preserve history', revision.content)
        self.assertEqual(ensure_enabled_extras(revision.content, ['toml']), revision.content)
        self.assertTrue(tasks._has_required_extras_enabled(self.dependency, {'toml'}))
        tasks._resolve_missing_dep_status(self.package, self.project)
        self.queue.assert_called_once()

    def test_dependency_blockers_explain_transitive_version_conflict(self):
        from backend.apps.packages.serializers import PackageDetailSerializer, PackageListSerializer

        self.prepare_waiting_package('dep_build_pending')
        requirement = 'python3dist(flit-core) < 4'
        self.dependency.analyzed_errors = [{
            'category': 'Missing Dependencies', 'items': [requirement],
        }]
        self.dependency.save()
        backend = Package.objects.create(
            project=self.project, name='flit-core', version='4.1.0', build_status='completed',
        )
        blockers = PackageDetailSerializer(self.package).data['dependency_blockers']
        self.assertEqual(len(blockers), 2)
        conflict = blockers[1]
        self.assertEqual(conflict['package_id'], self.dependency.id)
        self.assertEqual(conflict['requirement'], requirement)
        self.assertEqual(conflict['candidates'][0]['reason'], 'Version conflict')
        self.assertEqual(conflict['candidates'][0]['version'], '4.1.0')
        detail = PackageDetailSerializer(self.package).data['status_detail']
        self.assertIn('Version conflict: flit-core 4.1.0', detail)
        self.assertIn(requirement, detail)
        self.assertEqual(PackageListSerializer(self.package).data['status_detail'], detail)
        self.assertEqual(
            PackageListSerializer(self.package).data['dependency_blockers'], blockers,
        )
        self.assertEqual(
            PackageListSerializer().get_dep_blocking_items(self.dependency), [requirement],
        )
        backend.version = '3.12.0'
        backend.save()
        self.assertEqual(PackageListSerializer().get_dep_blocking_items(self.dependency), [])
        self.assertEqual(len(PackageDetailSerializer(self.package).data['dependency_blockers']), 1)

    def test_dependency_blockers_handle_cycles(self):
        from backend.apps.packages.serializers import get_dependency_blockers

        self.prepare_waiting_package('waiting_for_deps')
        PackageDependency.objects.create(package=self.dependency, depends_on=self.package)
        self.assertEqual(len(get_dependency_blockers(self.package)), 2)

    def test_dependency_blockers_show_absent_package(self):
        from backend.apps.packages.serializers import get_dependency_blockers

        self.package.build_status = 'missing_packages'
        self.package.analyzed_errors = [{
            'category': 'Missing Dependencies', 'items': ['python3dist(flit-core) < 4'],
        }]
        self.package.save()
        blockers = get_dependency_blockers(self.package)
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]['candidates'], [])

    def run_monitor(self, scheduled=None, active=None):
        from backend.apps.builds.tasks import monitor_pending_work

        with patch('celery.current_app.control.inspect') as inspect:
            inspect.return_value.active.return_value = active or {}
            inspect.return_value.reserved.return_value = {}
            inspect.return_value.scheduled.return_value = scheduled or {}
            monitor_pending_work()

    def test_monitor_recovers_pending_metadata_status_with_existing_spec(self):
        self.package.status = 'pending'
        self.package.build_status = 'pending'
        self.package.save()
        Package.objects.filter(pk=self.package.pk).update(
            updated_at=timezone.now() - timezone.timedelta(minutes=5),
        )
        self.run_monitor()
        self.queue.assert_called_once_with(self.package.id)

    def test_slot_retry_preserves_dependency_blocked_state(self):
        for state in ('waiting_for_deps', 'dep_build_pending', 'missing_packages'):
            with self.subTest(state=state):
                self.package.build_status = state
                self.package.save()
                with patch(
                    'backend.apps.builds.concurrency.limiter.try_acquire',
                    side_effect=TimeoutError('No slot'),
                ), patch.object(
                    tasks.build_single_package_task, 'apply_async',
                ) as requeue:
                    tasks.build_single_package_task.run(self.package.id)
                requeue.assert_called_once()
                self.package.refresh_from_db()
                self.assertEqual(self.package.build_status, state)

    def test_monitor_reclassifies_known_blocker_without_dispatching_consumer(self):
        self.package.status = 'pending'
        self.package.build_status = 'pending'
        self.package.build_started_at = timezone.now()
        self.package.analyzed_errors = [{
            'category': 'Missing Packages', 'items': ['python3dist(cython) = 3.0.12'],
        }]
        self.package.save()
        Package.objects.filter(pk=self.package.pk).update(
            updated_at=timezone.now() - timezone.timedelta(minutes=5),
        )
        self.run_monitor()
        self.package.refresh_from_db()
        self.assertEqual(self.package.build_status, 'dep_build_pending')
        self.assertNotIn((self.package.id,), [call.args for call in self.queue.call_args_list])

    def prepare_waiting_package(self, dependency_status='completed'):
        self.package.status = 'ready'
        self.package.build_status = 'waiting_for_deps'
        self.package.save()
        self.dependency.build_status = dependency_status
        self.dependency.save()
        PackageDependency.objects.create(package=self.package, depends_on=self.dependency)

    def test_monitor_recovers_waiting_package_once_without_losing_logs(self):
        self.prepare_waiting_package()
        self.package.build_log = 'previous attempt'
        self.package.save()
        Package.objects.filter(pk=self.package.pk).update(
            updated_at=timezone.now() - timezone.timedelta(minutes=5),
        )
        self.run_monitor()
        self.queue.assert_called_once_with(self.package.id)
        self.package.refresh_from_db()
        self.assertEqual(self.package.build_status, 'pending')
        self.assertEqual(self.package.build_log, 'previous attempt')

    def test_monitor_preserves_real_dependency_wait(self):
        self.prepare_waiting_package('dep_build_pending')
        self.run_monitor()
        self.queue.assert_not_called()
        self.package.refresh_from_db()
        self.assertEqual(self.package.build_status, 'waiting_for_deps')

    def test_monitor_does_not_duplicate_scheduled_slot_retry(self):
        self.prepare_waiting_package()
        self.run_monitor({'worker': [{'request': {
            'name': 'backend.apps.packages.tasks.build_single_package_task',
            'args': [self.package.id],
        }}]})
        self.queue.assert_not_called()

    def test_dependency_completion_marks_ready_waiter_pending(self):
        self.prepare_waiting_package()
        tasks.trigger_waiting_builds(self.dependency.id)
        self.package.refresh_from_db()
        self.assertEqual(self.package.build_status, 'pending')
        self.queue.assert_called_once_with(self.package.id)

    def assert_dependency_wait(self):
        self.assertEqual(self.package.build_status, 'dep_build_pending')
        self.assertTrue(PackageDependency.objects.filter(
            package=self.package, depends_on=self.dependency,
        ).exists())
        self.queue.assert_called_once_with(self.dependency.id)
        self.pypi.return_value.get_package_info.assert_not_called()
        self.ai_fixer.assert_not_called()
        self.assertEqual(self.package.spec_revisions.count(), 1)
        self.assertTrue(self.package.analyzed_errors)
        self.assertIsNotNone(self.package.build_completed_at)

    def test_missing_dependency_in_root_log_bypasses_all_rpm_fixers(self):
        self.builder.build_rpm.return_value = BuildResult(
            success=False, root_log_output=self.missing_log, error_message='builddep failed',
        )

        self.run_build()

        self.assert_dependency_wait()
        self.assertEqual(self.package.build_root_log, self.missing_log)
        self.fixer_round.assert_not_called()
        self.builder.build_rpm.assert_called_once()

    def test_missing_dependency_in_build_log_bypasses_all_rpm_fixers(self):
        self.builder.build_rpm.return_value = BuildResult(
            success=False, log_output=self.missing_log, error_message='builddep failed',
        )

        self.run_build()

        self.assert_dependency_wait()
        self.assertEqual(self.package.build_log, self.missing_log)
        self.fixer_round.assert_not_called()

    def test_srpm_dependency_failure_bypasses_spec_fixers(self):
        self.builder.build_srpm.return_value = BuildResult(
            success=False, log_output=self.missing_log, error_message='builddep failed',
        )
        with patch.object(tasks, '_detect_and_fix_directory_mismatch') as directory_fixer, \
                patch.object(tasks, '_detect_and_fix_pyproject_save_files_invalid_m_option') as module_fixer:
            self.run_build()

        self.assert_dependency_wait()
        directory_fixer.assert_not_called()
        module_fixer.assert_not_called()
        self.builder.build_rpm.assert_not_called()

    def test_dependency_failure_after_retry_stops_fixer_loop(self):
        self.builder.build_rpm.side_effect = [
            BuildResult(success=False, log_output=self.packaging_log, error_message='file missing'),
            BuildResult(success=False, root_log_output=self.missing_log, error_message='builddep failed'),
        ]
        self.fixer_round.return_value = 'missing_files_section_paths'

        self.run_build()

        self.assert_dependency_wait()
        self.fixer_round.assert_called_once()
        self.assertEqual(self.package.last_build_log, self.packaging_log)
        self.assertEqual(self.package.build_root_log, self.missing_log)
        self.assertEqual(self.builder.build_rpm.call_count, 2)

    def test_dependency_failure_during_srpm_retry_uses_latest_logs(self):
        self.builder.build_srpm.side_effect = [
            BuildResult(success=True, srpm_path='demo.src.rpm'),
            BuildResult(success=False, root_log_output=self.missing_log, error_message='builddep failed'),
        ]
        self.builder.build_rpm.return_value = BuildResult(
            success=False, log_output=self.packaging_log, error_message='file missing',
        )
        self.fixer_round.return_value = 'missing_files_section_paths'

        self.run_build()

        self.assert_dependency_wait()
        self.fixer_round.assert_called_once()
        self.assertEqual(self.package.build_root_log, self.missing_log)
        self.assertIn('builddep failed', self.package.build_error_message)
        self.builder.build_rpm.assert_called_once()

    def test_unknown_dependency_is_marked_missing_without_running_fixers(self):
        self.dependency.delete()
        self.pypi.return_value.get_package_info.return_value = None
        self.builder.build_rpm.return_value = BuildResult(
            success=False, root_log_output=self.missing_log, error_message='builddep failed',
        )

        self.run_build()

        self.assertEqual(self.package.build_status, 'missing_packages')
        self.pypi.return_value.get_package_info.assert_called_once_with('cython')
        self.fixer_round.assert_not_called()
        self.ai_fixer.assert_not_called()
        self.queue.assert_not_called()

    def test_packaging_failure_still_runs_spec_fixers(self):
        self.builder.build_rpm.return_value = BuildResult(
            success=False, log_output=self.packaging_log, error_message='file missing',
        )

        self.run_build()

        self.assertEqual(self.package.build_status, 'fixing')
        self.fixer_round.assert_called_once()
        self.queue.assert_not_called()
        self.ai_fixer.assert_not_called()
        self.ai_queue.assert_called_once_with(self.package.id, self.package.autofix_context['token'])
        self.assertEqual(self.package.build_log, self.packaging_log)

    def _queue_packaging_ai_fix(self):
        self.builder.build_rpm.return_value = BuildResult(
            success=False, log_output=self.packaging_log, error_message='file missing',
        )
        self.run_build()
        return self.package.autofix_context['token']

    def test_ai_handoff_releases_slot_before_query_and_successful_rebuild_confirms_fix(self):
        token = self._queue_packaging_ai_fix()
        self.fixer_round.side_effect = run_fixers

        def apply_fix(*args):
            SpecFileRevision.objects.create(
                package=self.package, content='Name: python3-demo\nVersion: 1.0\n# fixed\n',
                commit_message='AI-fixed: test fix',
            )
            return True

        self.ai_fixer.side_effect = apply_fix
        with self.settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}), \
                patch('backend.apps.builds.concurrency.limiter.try_acquire', side_effect=AssertionError('AI used a build slot')), \
                patch.object(tasks.build_single_package_task, 'apply_async') as rebuild:
            tasks.ai_fix_package_task.run(self.package.id, token)
        rebuild.assert_called_once_with(args=[self.package.id], kwargs={'autofix_token': token})
        self.package.refresh_from_db()
        self.assertEqual(self.package.build_status, 'pending')
        self.assertEqual(self.package.autofix_context['ai_attempt'], 1)
        revision = self.package.spec_revisions.latest('id')
        self.assertEqual(self.package.autofix_context['revision_ids'], [revision.id])

        self.builder.build_rpm.return_value = BuildResult(success=True, rpm_paths=['demo.rpm'])
        with patch.object(tasks, 'trigger_waiting_builds'):
            tasks.build_single_package_task.run(self.package.id, autofix_token=token)
        self.package.refresh_from_db()
        revision.refresh_from_db()
        self.assertEqual(self.package.build_status, 'completed')
        self.assertEqual(revision.ai_feedback, 'correct')
        self.assertEqual(self.package.autofix_context, {})

    def test_ai_failure_preserves_failed_build_logs(self):
        token = self._queue_packaging_ai_fix()
        self.fixer_round.side_effect = run_fixers
        self.ai_fixer.return_value = False
        with self.settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}), \
                patch.object(tasks.build_single_package_task, 'apply_async') as rebuild:
            tasks.ai_fix_package_task.run(self.package.id, token)
        self.package.refresh_from_db()
        self.assertEqual(self.package.build_status, 'failed')
        self.assertEqual(self.package.build_log, self.packaging_log)
        self.assertIn('untried spec', self.package.build_error_message)
        rebuild.assert_not_called()

    def test_duplicate_ai_spec_is_discarded_without_rebuilding(self):
        token = self._queue_packaging_ai_fix()
        self.fixer_round.side_effect = run_fixers
        original = self.package.spec_revisions.latest('id')

        def repeat_spec(*args):
            SpecFileRevision.objects.create(
                package=self.package, content=original.content, commit_message='AI-fixed: repeated',
            )
            return True

        self.ai_fixer.side_effect = repeat_spec
        with self.settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}), \
                patch.object(tasks.build_single_package_task, 'apply_async') as rebuild:
            tasks.ai_fix_package_task.run(self.package.id, token)
        self.assertEqual(self.package.spec_revisions.count(), 1)
        rebuild.assert_not_called()

    def test_cancelled_ai_request_does_not_rebuild(self):
        token = self._queue_packaging_ai_fix()
        self.fixer_round.side_effect = run_fixers

        def cancel_during_query(*args):
            Package.objects.filter(pk=self.package.pk).update(build_status='not_built', autofix_context={})
            return False

        self.ai_fixer.side_effect = cancel_during_query
        with self.settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}), \
                patch.object(tasks.build_single_package_task, 'apply_async') as rebuild:
            tasks.ai_fix_package_task.run(self.package.id, token)
        self.package.refresh_from_db()
        self.assertEqual(self.package.build_status, 'not_built')
        rebuild.assert_not_called()

    def test_obsolete_ai_rebuild_does_not_start_builder(self):
        self.package.build_status = 'not_built'
        self.package.save()
        tasks.build_single_package_task.run(self.package.id, autofix_token='obsolete')
        self.builder.build_rpm.assert_not_called()

    def test_ai_attempt_limit_is_preserved_across_handoff(self):
        token = self._queue_packaging_ai_fix()
        context = self.package.autofix_context
        context.update(phase='rebuild', ai_attempt=3)
        self.package.autofix_context = context
        self.package.build_status = 'pending'
        self.package.save()
        self.ai_queue.reset_mock()
        with patch('backend.core.ai_fixer.get_config', return_value={'max_attempts': 3}):
            tasks.build_single_package_task.run(self.package.id, autofix_token=token)
        self.package.refresh_from_db()
        self.assertEqual(self.package.build_status, 'failed')
        self.ai_queue.assert_not_called()

    def test_monitor_recovers_abandoned_ai_lock_after_two_observations(self):
        from django.core.cache import cache
        token = self._queue_packaging_ai_fix()
        self.ai_queue.reset_mock()
        with self.settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}), \
                patch('backend.apps.builds.concurrency.limiter.reclaim_orphaned_slots'), \
                patch('backend.apps.builds.concurrency.task_limiter.reclaim_orphaned_slots'):
            cache.set(f'package-ai-fix:{token}', True, timeout=7200)
            self.run_monitor(active={'ai@test': []})
            self.ai_queue.assert_not_called()
            self.run_monitor(active={'ai@test': []})
        self.ai_queue.assert_called_once_with(self.package.id, token)

    def test_monitor_does_not_requeue_an_active_ai_fix(self):
        token = self._queue_packaging_ai_fix()
        self.ai_queue.reset_mock()
        with patch('backend.apps.builds.concurrency.limiter.reclaim_orphaned_slots'), \
                patch('backend.apps.builds.concurrency.task_limiter.reclaim_orphaned_slots'):
            self.run_monitor(active={'ai@test': [{
                'name': tasks.ai_fix_package_task.name,
                'args': [self.package.id, token],
            }]})
        self.ai_queue.assert_not_called()

    def test_missing_import_or_compiler_remains_eligible_for_spec_fix(self):
        for log in (
            "ModuleNotFoundError: No module named 'cython'",
            "error: command 'gcc' failed: No such file or directory",
            'fatal error: ffi.h: No such file or directory',
        ):
            with self.subTest(log=log):
                self.assertFalse(tasks._has_unavailable_build_dependencies(self.package, log, ''))

    def test_self_dependency_remains_eligible_for_spec_fix(self):
        self.assertFalse(tasks._has_unavailable_build_dependencies(
            self.package, "No matching package to install: 'python3dist(demo)'", '',
        ))

    def test_dependency_sentinel_without_named_items_bypasses_fixers(self):
        self.assertTrue(tasks._has_unavailable_build_dependencies(
            self.package, '', 'Not all dependencies satisfied',
        ))

    def test_rpm_equality_requires_exact_version(self):
        for operator, version, expected in (
            ('=', '3.1.3', False), ('=', '3.0.12', True),
            ('==', '3.1.3', False), ('>=', '3.1.3', True),
            ('<=', '3.1.3', False), ('!=', '3.0.12', False),
        ):
            with self.subTest(operator=operator, version=version):
                self.assertEqual(tasks._satisfies_dep_version_constraint(
                    f'python3dist(cython) {operator} 3.0.12', version,
                ), expected)

    def known_version_blocker(self):
        self.dependency.version = '3.1.3'
        self.dependency.build_status = 'completed'
        self.dependency.save()
        self.package.build_status = 'failed'
        self.package.build_started_at = timezone.now()
        self.package.build_log = 'Previous failure log'
        self.package.analyzed_errors = [{
            'category': 'Missing Packages', 'items': ['python3dist(cython) = 3.0.12'],
        }]
        self.package.save()

    def test_wrong_built_version_does_not_start_another_build(self):
        self.known_version_blocker()

        self.run_build()

        self.assertEqual(self.package.build_status, 'dep_build_pending')
        self.assertEqual(self.package.build_log, 'Previous failure log')
        self.builder.build_srpm.assert_not_called()
        self.builder.build_rpm.assert_not_called()
        self.fixer_round.assert_not_called()
        self.queue.assert_not_called()
        self.assertTrue(PackageDependency.objects.filter(
            package=self.package, depends_on=self.dependency,
        ).exists())

    def test_matching_version_unblocks_known_dependency_failure(self):
        self.known_version_blocker()
        self.dependency.version = '3.0.12'
        self.dependency.save()

        self.assertFalse(tasks._defer_known_dependency_blockers(self.package))

    def test_changed_spec_is_allowed_to_recheck_old_dependency_failure(self):
        self.known_version_blocker()
        SpecFileRevision.objects.create(
            package=self.package, content='Name: python3-demo\n', commit_message='Changed requirement',
        )

        self.assertFalse(tasks._defer_known_dependency_blockers(self.package))

    def test_dependency_completion_does_not_wake_wrong_version(self):
        self.known_version_blocker()
        self.package.build_status = 'dep_build_pending'
        self.package.save()

        tasks.trigger_waiting_builds(self.dependency.id)

        self.queue.assert_not_called()

    def test_periodic_discovery_dispatches_each_blocked_project_once(self):
        self.package.build_status = 'missing_packages'
        self.package.save()
        self.dependency.build_status = 'dep_build_pending'
        self.dependency.save()
        with patch.object(tasks.refresh_missing_packages_state_task, 'delay') as refresh:
            count = tasks.discover_blocked_project_dependencies_task()

        self.assertEqual(count, 1)
        refresh.assert_called_once_with(self.project.id)

    def test_periodic_discovery_does_not_dispatch_healthy_projects(self):
        with patch.object(tasks.refresh_missing_packages_state_task, 'delay') as refresh:
            self.assertEqual(tasks.discover_blocked_project_dependencies_task(), 0)
        refresh.assert_not_called()

    def test_refresh_discovers_absent_backend_and_links_all_consumers(self):
        self.package.build_status = 'missing_packages'
        self.package.analyzed_errors = [{
            'category': 'Missing Packages', 'items': ['python3dist(hatch-vcs) >= 0.5'],
        }]
        self.package.save()
        self.dependency.build_status = 'dep_build_pending'
        self.dependency.analyzed_errors = self.package.analyzed_errors
        self.dependency.save()
        self.pypi.return_value.get_package_info.return_value = SimpleNamespace(
            name='hatch-vcs', version='0.5.0', summary='', description='',
            home_page='', license='MIT',
        )
        with patch.object(tasks.generate_spec_file_task, 'delay') as generate, \
                patch.object(tasks.refresh_missing_packages_state_task, 'delay'):
            tasks.refresh_missing_packages_state_task(self.project.id)

        backend = Package.objects.get(project=self.project, name='hatch-vcs')
        self.assertFalse(backend.is_direct_dependency)
        self.assertEqual(backend.package_type, 'dependency')
        generate.assert_called_once_with(backend.id, force=False, auto_build=True)
        self.assertEqual(PackageDependency.objects.filter(depends_on=backend).count(), 2)
        self.package.refresh_from_db()
        self.assertEqual(self.package.build_status, 'dep_build_pending')
