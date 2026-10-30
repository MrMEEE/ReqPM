import tarfile
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from backend.apps.packages.tasks import (
    _AI_FIXER_NAME,
    _MAX_APPLICATIONS_PER_FIXER,
    _run_autofix_round,
    _spec_fingerprint,
)
from backend.core.spec_generator import get_source_top_level_modules


class _FakeRevisionStore:
    """Minimal stand-in for SpecFileRevision used by _run_autofix_round."""

    def __init__(self, contents):
        self.revisions = []
        for content in contents:
            self.add(content)
        self.objects = self

    def add(self, content):
        rev = SimpleNamespace(id=len(self.revisions) + 1, content=content)
        rev.delete = lambda r=rev: self.revisions.remove(r)
        self.revisions.append(rev)
        return rev

    def filter(self, **kwargs):
        return self

    def order_by(self, *args):
        return self

    def first(self):
        return self.revisions[-1] if self.revisions else None


class AutofixRepeatGuardTests(SimpleTestCase):
    def _state(self, *contents):
        return {
            'tried_specs': {_spec_fingerprint(c) for c in contents},
            'fixer_counts': {},
            'exhausted': set(),
        }

    def _run(self, store, fixers, state):
        package = SimpleNamespace(id=1, name='pkg')
        with patch('backend.apps.packages.models.SpecFileRevision', store), \
                patch('backend.apps.packages.tasks.log_package'):
            return _run_autofix_round(package, fixers, state)

    def test_fixer_recreating_tried_spec_is_discarded_and_next_fixer_runs(self):
        store = _FakeRevisionStore(['glob A', 'glob B'])
        state = self._state('glob A', 'glob B')
        ai_calls = []

        fixers = [
            ('wrong_module_glob', lambda: bool(store.add('glob A'))),
            (_AI_FIXER_NAME, lambda: ai_calls.append(1) or bool(store.add('ai spec'))),
        ]
        applied = self._run(store, fixers, state)

        self.assertEqual(applied, _AI_FIXER_NAME)
        self.assertEqual(ai_calls, [1])
        self.assertEqual([r.content for r in store.revisions], ['glob A', 'glob B', 'ai spec'])
        self.assertIn('wrong_module_glob', state['exhausted'])

    def test_exhausted_fixer_is_not_called_again(self):
        store = _FakeRevisionStore(['base'])
        state = self._state('base')
        state['exhausted'].add('wrong_module_glob')
        calls = []
        fixers = [('wrong_module_glob', lambda: calls.append(1) or True)]

        self.assertIsNone(self._run(store, fixers, state))
        self.assertEqual(calls, [])

    def test_rule_fixer_is_capped_per_run(self):
        store = _FakeRevisionStore(['base'])
        state = self._state('base')
        counter = iter(range(100))
        fixers = [('unpackaged_files', lambda: bool(store.add(f'spec {next(counter)}')))]

        results = [self._run(store, fixers, state) for _ in range(_MAX_APPLICATIONS_PER_FIXER + 1)]

        self.assertEqual(results[:-1], ['unpackaged_files'] * _MAX_APPLICATIONS_PER_FIXER)
        self.assertIsNone(results[-1])

    def test_new_spec_is_accepted_and_remembered(self):
        store = _FakeRevisionStore(['base'])
        state = self._state('base')
        fixers = [('wrong_module_glob', lambda: bool(store.add('google glob')))]

        self.assertEqual(self._run(store, fixers, state), 'wrong_module_glob')
        self.assertIn(_spec_fingerprint('google glob'), state['tried_specs'])


class SourceTopLevelModulesTests(SimpleTestCase):
    def _archive(self, temp_dir, files):
        path = Path(temp_dir) / 'pkg-1.0.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                import io
                archive.addfile(info, io.BytesIO(data))
        return path

    def test_prefers_top_level_txt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._archive(temp_dir, {
                'googleapis_common_protos-1.70.0/googleapis_common_protos.egg-info/top_level.txt': b'google\n',
                'googleapis_common_protos-1.70.0/google/api/__init__.py': b'',
                'googleapis_common_protos-1.70.0/setup.py': b'',
            })
            self.assertEqual(get_source_top_level_modules(path), ['google'])

    def test_falls_back_to_python_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._archive(temp_dir, {
                'pkg-1.0/src/realmod/__init__.py': b'',
                'pkg-1.0/tests/test_x.py': b'',
                'pkg-1.0/setup.py': b'',
                'pkg-1.0/single.py': b'',
            })
            self.assertEqual(get_source_top_level_modules(path), ['realmod', 'single'])

    def test_real_googleapis_common_protos_archive(self):
        archive = (Path(settings.BASE_DIR) / 'build_artifacts' / 'package_builds' / '3886'
                   / 'googleapis_common_protos-1.70.0.tar.gz')
        if not archive.exists():
            self.skipTest('package 3886 archive not available')
        self.assertEqual(get_source_top_level_modules(archive), ['google'])
