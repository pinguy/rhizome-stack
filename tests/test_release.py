"""Release verification must reject tampering, extra files and symlinks."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'manifests').mkdir()
        (self.root / 'approved.txt').write_text('Public fixture')
        self.files = ['approved.txt', 'manifests/release-files.json']
        (self.root / 'manifests/release-files.json').write_text(json.dumps({'schema': 1, 'files': self.files}))
        self.manifest = {'schema': 1, 'files': {name: {
            'sha256': hashlib.sha256((self.root / name).read_bytes()).hexdigest(),
            'bytes': (self.root / name).stat().st_size,
        } for name in self.files}}
        self.write_manifest()

    def write_manifest(self):
        (self.root / 'RELEASE-MANIFEST.json').write_text(json.dumps(self.manifest))

    def verify(self, valid):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/verify_release.py'), str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if valid else 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['valid'], valid)

    def test_valid_export(self):
        self.verify(True)

    def test_changed_content(self):
        (self.root / 'approved.txt').write_text('Changed contents')
        self.verify(False)

    def test_extra_nested_manifest_is_not_hidden(self):
        (self.root / 'manifests/RELEASE-MANIFEST.json').write_text('{}')
        self.verify(False)

    def test_bytes_are_verified(self):
        self.manifest['files']['approved.txt']['bytes'] += 1
        self.write_manifest()
        self.verify(False)

    def test_symlink_with_identical_contents_is_not_a_release_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'copy.txt'
            source.write_text('Public fixture')
            (self.root / 'approved.txt').unlink()
            (self.root / 'approved.txt').symlink_to(source)
            self.verify(False)

    def test_manifest_cannot_silently_omit_allowlisted_file(self):
        del self.manifest['files']['approved.txt']
        (self.root / 'approved.txt').unlink()
        self.write_manifest()
        self.verify(False)

    def test_malformed_manifest_fails_cleanly(self):
        (self.root / 'RELEASE-MANIFEST.json').write_text('{')
        self.verify(False)


if __name__ == '__main__':
    unittest.main()
