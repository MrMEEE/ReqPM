from django.test import SimpleTestCase

from backend.apps.packages.models import Package


class BuildLogHistoryTests(SimpleTestCase):
    def test_archive_moves_current_build_and_root_logs_to_last_attempt(self):
        package = Package(
            build_log='current build output',
            build_root_log='current root output',
            last_build_log='older build output',
            last_build_root_log='older root output',
        )

        package.archive_build_logs()

        self.assertEqual(package.build_log, '')
        self.assertEqual(package.build_root_log, '')
        self.assertEqual(package.last_build_log, 'current build output')
        self.assertEqual(package.last_build_root_log, 'current root output')

    def test_archive_keeps_last_attempt_when_current_attempt_is_empty(self):
        package = Package(
            last_build_log='last build output',
            last_build_root_log='last root output',
        )

        package.archive_build_logs()

        self.assertEqual(package.last_build_log, 'last build output')
        self.assertEqual(package.last_build_root_log, 'last root output')

    def test_archive_includes_state_log(self):
        package = Package(
            build_log='build out',
            build_root_log='root out',
            build_state_log='state out',
            last_build_state_log='older state',
        )

        package.archive_build_logs()

        self.assertEqual(package.build_state_log, '')
        self.assertEqual(package.last_build_log, 'build out')
        self.assertEqual(package.last_build_root_log, 'root out')
        self.assertEqual(package.last_build_state_log, 'state out')


class MockBuilderStateLogTests(SimpleTestCase):
    def test_build_rpm_returns_build_root_and_state_logs(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        from backend.plugins.builders.mock import MockBuilder

        with tempfile.TemporaryDirectory() as out:
            def fake_run(args, timeout=None, memory_limit=None):
                if '--rebuild' in args:
                    Path(out, 'build.log').write_text('compiling\n')
                    Path(out, 'root.log').write_text('installing deps\n')
                    Path(out, 'state.log').write_text('Start: build phase\n')
                    return 1, '', 'failed'
                return 0, '', ''

            builder = MockBuilder.__new__(MockBuilder)
            builder.memory_limit = None
            with mock.patch.object(builder, '_run_mock_command', side_effect=fake_run, create=True), \
                    mock.patch.object(builder, '_ensure_gpg_keys_updated', create=True):
                result = builder.build_rpm('pkg.src.rpm', 'rhel-10-x86_64', 'x86_64', out)

        self.assertIn('compiling', result.log_output)
        self.assertIn('installing deps', result.root_log_output)
        self.assertIn('Start: build phase', result.state_log_output)
