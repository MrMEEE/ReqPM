import tarfile
import tempfile
import unittest
from pathlib import Path

from backend.core.spec_generator import fix_setup_directory, get_source_archive_root


class SourceArchiveRootTests(unittest.TestCase):
    def test_reads_case_sensitive_root_from_tarball(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / 'brotli-1.1.0.tar.gz'
            with tarfile.open(archive_path, 'w:gz') as archive:
                info = tarfile.TarInfo('Brotli-1.1.0/PKG-INFO')
                info.size = 0
                archive.addfile(info)

            self.assertEqual(get_source_archive_root(archive_path), 'Brotli-1.1.0')

    def test_rewrites_only_matching_setup_directory_and_is_idempotent(self):
        spec = '%prep\n%setup -q -n brotli-%{version}\n'

        fixed = fix_setup_directory(
            spec,
            expected_dir='brotli-1.1.0',
            archive_root='Brotli-1.1.0',
            version='1.1.0',
        )

        self.assertEqual(fixed, '%prep\n%setup -q -n Brotli-%{version}\n')
        self.assertIsNone(fix_setup_directory(
            fixed,
            expected_dir='brotli-1.1.0',
            archive_root='Brotli-1.1.0',
            version='1.1.0',
        ))

    def test_does_not_change_unrelated_setup_directive(self):
        self.assertIsNone(fix_setup_directory(
            '%prep\n%setup -q -n another-package-%{version}\n',
            expected_dir='brotli-1.1.0',
            archive_root='Brotli-1.1.0',
            version='1.1.0',
        ))


if __name__ == '__main__':
    unittest.main()
