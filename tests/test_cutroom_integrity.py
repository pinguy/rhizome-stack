"""Cutroom render safety, deterministic output and single-flight recovery."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'components/cutroom/backend'
SPEC = importlib.util.spec_from_file_location('cutroom_renderer_integrity', BACKEND / 'renderer.py')
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


class RenderIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project_dir = Path(self.temp.name) / 'project'
        self.project_dir.mkdir()
        self.audio = self.project_dir / 'song.wav'
        self.audio.write_bytes(b'synthetic input')
        self.project = {
            'id': 'project-test', 'audio': {'path': 'song.wav'},
            'analysis': {'audio': {'duration': 1.0}},
            'shots': [],
            'timeline': {'items': [{'id': 'item-1', 'shot_id': 'intro',
                                    'take_id': 'missing', 'start': 0, 'end': 1.0}],
                         'titles': []},
        }

    def test_project_media_must_not_escape_via_paths_or_symlinks(self):
        outside = Path(self.temp.name) / 'outside.wav'
        outside.write_bytes(b'outside data')
        for path in ('../outside.wav', str(outside), 'nested/../../outside.wav'):
            with self.subTest(path=path):
                self.project['audio']['path'] = path
                with self.assertRaisesRegex(ValueError, 'project'):
                    renderer.render(self.project_dir, self.project, '480p')
        link = self.project_dir / 'linked.wav'
        link.symlink_to(outside)
        self.project['audio']['path'] = 'linked.wav'
        with self.assertRaisesRegex(ValueError, 'escapes'):
            renderer.render(self.project_dir, self.project, '480p')
        self.project['audio']['path'] = 'song.wav'
        self.project['shots'] = [{'id': 'intro', 'takes': [
            {'id': 'missing', 'path': '../outside.wav'}]}]
        with self.assertRaisesRegex(ValueError, 'escapes'):
            renderer.render(self.project_dir, self.project, '480p')

    def test_failed_render_removes_temporary_segments(self):
        def fail_with_partial(command, log, timeout=7200):
            Path(command[-1]).write_bytes(b'partially rendered segment')
            raise RuntimeError('synthetic failure')

        with patch.object(renderer, '_run', side_effect=fail_with_partial):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                renderer.render(self.project_dir, self.project, '480p')
        scratch = self.project_dir / 'timeline/render-work'
        self.assertFalse(list(scratch.iterdir()))

    def test_failed_final_encode_does_not_leave_corrupt_output(self):
        calls = []

        def simulate_failure(command, log, timeout=7200):
            calls.append(command)
            Path(command[-1]).write_bytes(b'partial mp4')
            if len(calls) == 3:
                raise RuntimeError('final encode interrupted')

        with patch.object(renderer, '_run', side_effect=simulate_failure):
            with self.assertRaisesRegex(RuntimeError, 'final encode interrupted'):
                renderer.render(self.project_dir, self.project, '480p')
        self.assertEqual(len(calls), 3)
        self.assertFalse(list((self.project_dir / 'renders').glob('*.mp4')))
        self.assertFalse(list((self.project_dir / 'timeline/render-work').iterdir()))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                         'real FFmpeg/FFprobe required')
    def test_real_ffmpeg_renders_two_distinct_outputs_without_scratch(self):
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi',
                        '-i', 'sine=frequency=440:duration=1', '-y', str(self.audio)],
                       check=True, timeout=20)
        first = renderer.render(self.project_dir, self.project, '480p')
        second = renderer.render(self.project_dir, self.project, '480p')
        self.assertNotEqual(first['path'], second['path'])
        for result in (first, second):
            output = self.project_dir / result['path']
            self.assertTrue(output.is_file())
            probe = subprocess.check_output(['ffprobe', '-v', 'error',
                '-show_entries', 'stream=codec_type,width,height:format=duration',
                '-of', 'json', str(output)], text=True, timeout=10)
            details = json.loads(probe)
            self.assertTrue(any(stream['codec_type'] == 'video' and stream['width'] == 854
                                and stream['height'] == 480 for stream in details['streams']))
            self.assertTrue(any(stream['codec_type'] == 'audio' for stream in details['streams']))
            self.assertAlmostEqual(float(details['format']['duration']), 1.0, delta=0.15)
        self.assertFalse(list((self.project_dir / 'timeline/render-work').iterdir()))


class RenderLockTests(unittest.TestCase):
    def test_byte_range_suffix_and_unsatisfiable_requests(self):
        import io
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'STUDIO_ROOT': temp}):
            sys.path.insert(0, str(BACKEND))
            try:
                spec = importlib.util.spec_from_file_location('cutroom_app_ranges', BACKEND / 'app.py')
                app = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(app)
            finally:
                sys.path.remove(str(BACKEND))
            path = app.project_dir('range-test') / 'video.mp4'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'0123456789')
            for requested, code, payload, content_range in (
                ('bytes=-3', 206, b'789', 'bytes 7-9/10'),
                ('bytes=4-6', 206, b'456', 'bytes 4-6/10'),
                ('bytes=20-', 416, b'', 'bytes */10'),
                ('bytes=8-7', 416, b'', 'bytes */10'),
            ):
                with self.subTest(range=requested):
                    handler = object.__new__(app.Handler)
                    handler.headers = {'Range': requested}
                    handler.wfile = io.BytesIO()
                    responses, headers = [], {}
                    handler.send_response = lambda status: responses.append(status)
                    handler.send_header = lambda name, value: headers.__setitem__(name, value)
                    handler.end_headers = lambda: None
                    handler._media('range-test', 'video.mp4')
                    self.assertEqual(responses, [code])
                    self.assertEqual(handler.wfile.getvalue(), payload)
                    self.assertEqual(headers['Content-Range'], content_range)
                    self.assertEqual(int(headers['Content-Length']), len(payload))

    def test_preflight_failures_release_render_lock(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'STUDIO_ROOT': temp}):
            sys.path.insert(0, str(BACKEND))
            try:
                spec = importlib.util.spec_from_file_location('cutroom_app_integrity', BACKEND / 'app.py')
                app = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(app)
            finally:
                sys.path.remove(str(BACKEND))
            with patch.object(app, 'load_project', side_effect=FileNotFoundError('missing')):
                with self.assertRaises(FileNotFoundError):
                    app.start_render('project-test', '720p')
            self.assertTrue(app.RENDER_LOCK.acquire(blocking=False), 'lock leaked after load failure')
            app.RENDER_LOCK.release()
            with patch.object(app, 'load_project', return_value={'id': 'project-test'}), \
                 patch.object(app, 'save_project', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    app.start_render('project-test', '720p')
            self.assertTrue(app.RENDER_LOCK.acquire(blocking=False), 'lock leaked after save failure')
            app.RENDER_LOCK.release()
            with self.assertRaisesRegex(ValueError, 'preset'):
                app.start_render('project-test', '../bad')
            self.assertTrue(app.RENDER_LOCK.acquire(blocking=False))
            app.RENDER_LOCK.release()


if __name__ == '__main__':
    unittest.main()
