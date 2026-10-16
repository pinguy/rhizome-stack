"""Release verification must reject tampering, extra files and symlinks."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
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

    def apply_fixture(self, *, corrupt=False):
        target = self.root / 'installed'
        patches = self.root / 'patches'
        target.mkdir()
        patches.mkdir()
        files = []
        for name in ('first.py', 'second.py'):
            (target / name).write_bytes(b'original\n')
            (target / name).chmod(0o755)
            (patches / name).write_bytes(b'changed\n')
            files.append({'path': name, 'action': 'replace', 'payload': name,
                          'clean_sha256': hashlib.sha256(b'original\n').hexdigest(),
                          'patched_sha256': hashlib.sha256(b'changed\n').hexdigest()})
        if corrupt:
            (patches / 'second.py').write_bytes(b'corrupt\n')
        (patches / 'manifest.json').write_text(json.dumps({'schema': 1, 'files': files}))
        result = subprocess.run([sys.executable, str(ROOT / 'tools/apply_patch_set.py'),
                                 str(patches), str(target)], capture_output=True, text=True)
        return target, patches, result

    def test_corrupt_later_patch_never_changes_installed_files(self):
        target, _, result = self.apply_fixture(corrupt=True)
        self.assertNotEqual(result.returncode, 0)
        for name in ('first.py', 'second.py'):
            self.assertEqual((target / name).read_bytes(), b'original\n')
            self.assertEqual((target / name).stat().st_mode & 0o777, 0o755)
        self.assertFalse((target / '.rhizome-stack-patch-backup').exists())

    def test_replacement_preserves_executable_mode_and_is_repeatable(self):
        target, patches, result = self.apply_fixture()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('first.py', 'second.py'):
            self.assertEqual((target / name).read_bytes(), b'changed\n')
            self.assertEqual((target / name).stat().st_mode & 0o777, 0o755)
            self.assertEqual((target / '.rhizome-stack-patch-backup' / name).read_bytes(), b'original\n')
        again = subprocess.run([sys.executable, str(ROOT / 'tools/apply_patch_set.py'),
                                str(patches), str(target)], capture_output=True, text=True)
        self.assertEqual(again.returncode, 0, again.stderr)

    def test_commit_failure_restores_changed_files_from_backup(self):
        # First prepare a valid fixture, then restore its pristine target.
        target, patches, result = self.apply_fixture()
        self.assertEqual(result.returncode, 0, result.stderr)
        import shutil
        shutil.rmtree(target)
        target.mkdir()
        for name in ('first.py', 'second.py'):
            (target / name).write_bytes(b'original\n')
            (target / name).chmod(0o755)
        sys.path.insert(0, str(ROOT / 'tools'))
        import apply_patch_set
        real_install = apply_patch_set.install_file
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('synthetic write failure')
            real_install(source, destination)

        with patch.object(sys, 'argv', ['apply', str(patches), str(target)]), \
             patch.object(apply_patch_set, 'install_file', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'synthetic write failure'):
                apply_patch_set.main()
        for name in ('first.py', 'second.py'):
            self.assertEqual((target / name).read_bytes(), b'original\n')
            self.assertEqual((target / name).stat().st_mode & 0o777, 0o755)

    def test_failed_diff_after_staged_deletion_preserves_installation(self):
        target, patches, result = self.apply_fixture(corrupt=True)
        manifest = json.loads((patches / 'manifest.json').read_text())
        manifest['files'][0].update(action='delete', payload=None, patched_sha256=None)
        manifest['files'][1].update(action='modify', payload='broken.patch')
        (patches / 'broken.patch').write_text('not a unified diff\n')
        (patches / 'manifest.json').write_text(json.dumps(manifest))
        result = subprocess.run([sys.executable, str(ROOT / 'tools/apply_patch_set.py'),
                                 str(patches), str(target)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sorted(p.name for p in target.iterdir()), ['first.py', 'second.py'])
        self.assertEqual((target / 'first.py').read_bytes(), b'original\n')
        self.assertEqual((target / 'second.py').read_bytes(), b'original\n')

    def test_patch_targets_cannot_escape_installed_root(self):
        target, patches, _ = self.apply_fixture(corrupt=True)
        outside = self.root / 'outside.py'
        outside.write_bytes(b'original\n')
        manifest = json.loads((patches / 'manifest.json').read_text())
        manifest['files'] = [dict(manifest['files'][0], path='../outside.py')]
        (patches / 'manifest.json').write_text(json.dumps(manifest))
        result = subprocess.run([sys.executable, str(ROOT / 'tools/apply_patch_set.py'),
                                 str(patches), str(target)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsafe patch path', result.stderr)
        self.assertEqual(outside.read_bytes(), b'original\n')

    def test_patch_capture_preserves_missing_final_newline(self):
        clean = self.root / 'clean'
        modified = self.root / 'modified'
        target = self.root / 'target'
        output = self.root / 'patches'
        for directory in (clean, modified, target):
            directory.mkdir()
        (clean / 'bundle.js').write_bytes(b'const value=1;')
        (modified / 'bundle.js').write_bytes(b'const value=2;')
        (target / 'bundle.js').write_bytes((clean / 'bundle.js').read_bytes())
        capture = subprocess.run([
            sys.executable, str(ROOT / 'tools/capture_tree_patches.py'),
            '--clean', str(clean), '--modified', str(modified),
            '--output', str(output), 'bundle.js',
        ], capture_output=True, text=True)
        self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
        patch_text = (output / 'bundle.js.patch').read_text()
        self.assertIn('\\ No newline at end of file', patch_text)
        apply = subprocess.run([
            sys.executable, str(ROOT / 'tools/apply_patch_set.py'),
            str(output), str(target),
        ], capture_output=True, text=True)
        self.assertEqual(apply.returncode, 0, apply.stdout + apply.stderr)
        self.assertEqual((target / 'bundle.js').read_bytes(), b'const value=2;')


if __name__ == '__main__':
    unittest.main()
