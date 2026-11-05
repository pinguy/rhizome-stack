"""WAN media serving and batch boundaries, using synthetic files and no GPU."""
from __future__ import annotations

import http.client
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / 'components/creative/wan-video-desk'
sys.path.insert(0, str(APP_DIR))
import engine


class WanHTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        spec = importlib.util.spec_from_file_location('wan_http_fixture', APP_DIR / 'app.py')
        cls.app = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {'WAN_DESK_STATE': cls.temporary.name}), \
             patch.object(engine, 'GenerationQueue'):
            spec.loader.exec_module(cls.app)
        cls.app.ensure_project()
        (cls.app.project_dir() / 'generated/fixture.mp4').write_bytes(b'0123456789')
        (cls.app.project_dir() / 'generated/empty.mp4').touch()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), cls.app.Handler)
        cls.server.daemon_threads = True
        thread = threading.Thread(target=cls.server.serve_forever,
                                  kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join, 2)
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)

    def request(self, method='GET', path=None, body=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        self.addCleanup(connection.close)
        connection.request(method, path or '/media/wan-video-studio/generated/fixture.mp4',
                           body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    def test_cross_site_prompt_helper_is_rejected_before_model_call(self):
        with patch.object(self.app, 'expand_prompt', return_value={}) as expand:
            for headers, expected in [({'Origin': 'https://hostile.invalid'}, 403),
                                      ({'Host': 'rebind.invalid'}, 403),
                                      ({'Content-Type': 'text/plain'}, 415)]:
                supplied = {'Content-Type': 'application/json', **headers}
                status, _, _ = self.request('POST', '/api/video-studio/expand', '{}', supplied)
                self.assertEqual(status, expected)
            expand.assert_not_called()
            origin = 'http://%s:%s' % self.server.server_address
            self.assertEqual(self.request('POST', '/api/video-studio/expand', '{}',
                                          {'Origin': origin, 'Content-Type': 'application/json'})[0], 200)
            expand.assert_called_once()

    def test_suffix_open_and_bounded_ranges(self):
        for header, wanted, content_range in (
            ('bytes=-4', b'6789', 'bytes 6-9/10'),
            ('bytes=-50', b'0123456789', 'bytes 0-9/10'),
            ('bytes=3-', b'3456789', 'bytes 3-9/10'),
            ('bytes=2-4', b'234', 'bytes 2-4/10'),
        ):
            with self.subTest(header=header):
                status, headers, data = self.request(headers={'Range': header})
                self.assertEqual(status, 206)
                self.assertEqual(data, wanted)
                self.assertEqual(headers['Content-Range'], content_range)
                self.assertEqual(int(headers['Content-Length']), len(wanted))

    def test_unsatisfiable_ranges_report_file_size(self):
        for header in ('bytes=-0', 'bytes=-', 'bytes=10-', 'bytes=4-2', 'bytes=0-1,3-4'):
            with self.subTest(header=header):
                status, headers, _ = self.request(headers={'Range': header})
                self.assertEqual(status, 416)
                self.assertEqual(headers.get('Content-Range'), 'bytes */10')

    def test_empty_file_and_full_file(self):
        self.assertEqual(self.request()[2], b'0123456789')
        status, headers, data = self.request(path='/media/wan-video-studio/generated/empty.mp4')
        self.assertEqual((status, data, headers['Content-Length']), (200, b'', '0'))

    def test_non_object_json_is_a_client_error_without_queue_work(self):
        self.app.QUEUE.add.reset_mock()
        for body in ('[]', 'null', '42', '"text"'):
            with self.subTest(body=body):
                status, _, data = self.request('POST', '/api/video-studio/generate', body,
                                               {'Content-Type': 'application/json'})
                self.assertEqual(status, 400, data)
        self.app.QUEUE.add.assert_not_called()

    def test_mastering_never_stops_queued_or_active_generation(self):
        project = {'shots': [{'takes': [{'id': 'fixture', 'path': 'generated/fixture.mp4'}]}]}
        for status in ('queued', 'running'):
            with self.subTest(status=status), \
                 patch.object(self.app, 'ensure_project', return_value=project), \
                 patch.object(self.app.QUEUE, 'snapshot', return_value={'jobs': [{'status': status}]}), \
                 patch.object(self.app, 'UPSCALE') as upscale:
                upscale.running.return_value = False
                self.app.QUEUE.engine.reset_mock()
                with self.assertRaisesRegex(RuntimeError, 'generation'):
                    self.app.start_video_upscale('fixture', 'lanczos')
                self.app.QUEUE.engine.stop_owned.assert_not_called()
                upscale.start.assert_not_called()

    def test_mastering_requires_idle_engine_and_successful_stop(self):
        project = {'shots': [{'takes': [{'id': 'fixture', 'path': 'generated/fixture.mp4'}]}]}
        for running, pending, stopped in ((1, 0, True), (0, 1, True), (None, None, True), (0, 0, False)):
            with self.subTest(running=running, pending=pending, stopped=stopped), \
                 patch.object(self.app, 'ensure_project', return_value=project), \
                 patch.object(self.app.QUEUE, 'snapshot', return_value={'jobs': []}), \
                 patch.object(self.app, 'UPSCALE') as upscale:
                upscale.running.return_value = False
                self.app.QUEUE.engine.reset_mock()
                self.app.QUEUE.engine.status.return_value = {
                    'online': True, 'owned': True, 'running': running, 'pending': pending,
                }
                self.app.QUEUE.engine.stop_owned.return_value = stopped
                with self.assertRaises(RuntimeError):
                    self.app.start_video_upscale('fixture', 'lanczos')
                if running != 0 or pending != 0:
                    self.app.QUEUE.engine.stop_owned.assert_not_called()
                upscale.start.assert_not_called()

    def test_h3_validation_uses_fixed_fps_legal_frames_and_portable_models(self):
        for path in self.app.H3_REQUIRED_FILES:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        payload = self.app.validate_job({
            'prompt': 'synthetic H3 shot', 'video_model': self.app.H3_MODEL,
            'mode': 't2v', 'fps': 24, 'steps': 20,
            'frames': self.app.h3_frames_for_seconds(5),
            'width': 832, 'height': 480, 'seed': 42,
        })
        self.assertEqual(payload['backend'], self.app.H3_BACKEND)
        self.assertEqual(payload['frames'] % 17, 5)
        with self.assertRaisesRegex(ValueError, '24 fps'):
            self.app.validate_job({**payload, 'fps': 16})
        with self.assertRaisesRegex(ValueError, r'17n\+5'):
            self.app.validate_job({**payload, 'frames': 120})

    def test_h3_gallery_preserves_requested_duration(self):
        project = self.app.ensure_project()
        take = {
            'id': 'take-h3duration', 'path': 'generated/fixture.mp4',
            'frames': self.app.h3_frames_for_seconds(5), 'fps': 24,
            'duration_seconds': 5, 'created_at': 1,
        }
        project['shots'][0]['takes'] = [take]
        self.app.save_project(project)
        self.app.QUEUE.snapshot.return_value = {
            'jobs': [], 'pause_after_current': False, 'engine': {'online': False},
        }
        with patch.object(self.app, 'openclaw_models', return_value=[]):
            snapshot = self.app.state()
        self.assertEqual(snapshot['takes'][0]['duration_seconds'], 5)

    def test_1080p_endpoint_preserves_selected_method(self):
        origin = 'http://%s:%s' % self.server.server_address
        with patch.object(self.app, 'start_video_upscale',
                          return_value={'status': 'running', 'method': 'realesrgan'}) as start:
            status, _, data = self.request(
                'POST', '/api/video-studio/upscale',
                json.dumps({'take_id': 'take-deadbeef', 'method': 'realesrgan'}),
                {'Origin': origin, 'Content-Type': 'application/json'},
            )
        self.assertEqual(status, 202, data)
        start.assert_called_once_with('take-deadbeef', 'realesrgan')


class WanBatchTest(unittest.TestCase):
    def setUp(self):
        self.queue = engine.GenerationQueue.__new__(engine.GenerationQueue)
        self.queue.lock = threading.RLock()
        self.queue.jobs = []
        self.queue._save = Mock()
        self.queue.wake = Mock()

    def test_engine_ownership_rejects_similar_paths_ports_and_embedded_arguments(self):
        owned = engine.ComfyEngine(Path('/synthetic/state'))
        pid = 987654
        main = str((engine.COMFY_DIR / 'main.py').resolve())
        for args, expected in [
            (['python', main, '--port', '8188'], pid),
            (['python', main, '--port', '81880'], None),
            (['python', main + '.other', '--port', '8188'], None),
            (['python', '/unrelated.py', '--note', main, '--port', '8188'], None),
            (['python', main, '--note', '--port 8188'], None),
        ]:
            with self.subTest(args=args), \
                 patch.object(Path, 'read_text', return_value=str(pid)), \
                 patch.object(Path, 'read_bytes', return_value=('\0'.join(args) + '\0').encode()), \
                 patch.object(os, 'getpgid', return_value=pid):
                self.assertEqual(owned.owned_pid(), expected)

    def test_engine_profile_handoff_refuses_busy_or_unknown_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            owned = engine.ComfyEngine(Path(temporary))
            for status, external_pid in (
                ({'online': True, 'owned': False, 'running': 1, 'pending': 0}, 4242),
                ({'online': True, 'owned': False, 'running': 0, 'pending': 0}, None),
                ({'online': True, 'owned': False}, 4242),
            ):
                with self.subTest(status=status, external_pid=external_pid), \
                     patch.object(engine, 'comfy_up', return_value=True), \
                     patch.object(owned, 'status', return_value=status), \
                     patch.object(engine, '_comfy_pid', return_value=external_pid), \
                     patch.object(engine, '_stop_music_engine') as stop:
                    self.assertFalse(owned.start())
                    stop.assert_not_called()

    def test_engine_profile_handoff_stops_known_music_owner_then_starts(self):
        with tempfile.TemporaryDirectory() as temporary:
            owned = engine.ComfyEngine(Path(temporary))
            process = Mock(pid=5151)
            process.poll.return_value = None
            status = {'online': True, 'owned': False, 'running': 0, 'pending': 0}
            with patch.object(engine, 'comfy_up', return_value=True), \
                 patch.object(owned, 'status', return_value=status), \
                 patch.object(engine, '_comfy_pid', return_value=4242), \
                 patch.object(engine, '_stop_music_engine', return_value=True) as stop, \
                 patch.object(engine.subprocess, 'Popen', return_value=process) as popen:
                self.assertTrue(owned.start(profile='legacy-static'))
            stop.assert_called_once()
            popen.assert_called_once()
            self.assertEqual(owned.pid_file.read_text(), '5151')

    def test_reference_jobs_submit_inference_and_register_generated_output(self):
        # A reference path must never satisfy the finished-output sentinel.
        for kind, mode, reference in (('video', 'i2v', True), ('video', 't2v', False),
                                       ('art', 't2v', True)):
            with self.subTest(kind=kind, mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                project_dir = root / 'projects/fixture'
                project_dir.mkdir(parents=True)
                (project_dir / 'reference.png').write_bytes(b'reference pixels')
                inputs, outputs = root / 'input', root / 'output'
                inputs.mkdir()
                result_dir = outputs / 'wan-video-desk/fixture'
                result_dir.mkdir(parents=True)
                extension = '.png' if kind == 'art' else '.mp4'
                (result_dir / ('job-fixture_00001' + extension)).write_bytes(b'generated result')
                project = {'id': 'fixture', 'shots': [{'id': 'shot-fixture', 'takes': []}]}
                job = {'id': 'job-fixture', 'project_id': 'fixture', 'shot_id': 'shot-fixture',
                       'kind': kind, 'mode': mode, 'backend': engine.WAN_BACKEND,
                       'prompt': 'synthetic shot', 'seed': 42, 'width': 640, 'height': 480,
                       'frames': 81, 'fps': 16, 'steps': 4}
                if reference:
                    job['reference_image'] = {'path': 'reference.png'}
                self.queue.root = root
                self.queue.engine = Mock()
                self.queue.load_project = Mock(return_value=project)
                self.queue.save_project = Mock()
                def request(path, payload=None, timeout=None):
                    if path == '/prompt':
                        return {'prompt_id': 'prompt-fixture'}
                    return {'prompt-fixture': {'status': {'status_str': 'success'}}}
                with patch.object(engine, 'COMFY_INPUT', inputs), \
                     patch.object(engine, 'COMFY_OUTPUT', outputs), \
                     patch.object(engine, '_json_request', side_effect=request) as submit, \
                     patch.object(engine.time, 'sleep'), \
                     patch.object(engine, 'qc_video', return_value={'status': 'pass'}):
                    self.queue._run(job)
                self.assertEqual(job['status'], 'complete', job.get('error'))
                self.assertEqual(sum(call.args[0] == '/prompt' for call in submit.call_args_list), 1)
                self.assertEqual((project_dir / job['result']['path']).read_bytes(), b'generated result')
                self.assertEqual(list(inputs.iterdir()), [])
                self.queue.save_project.assert_called_once()

    def test_h3_does_not_start_until_comfy_owner_releases_idle_engine(self):
        self.queue.root = Path('/synthetic')
        self.queue.load_project = Mock(return_value={})
        self.queue.engine = Mock()
        self.queue.engine.stop_idle_for_external_worker.return_value = False
        job = {'id': 'fixture', 'project_id': 'fixture', 'kind': 'video',
               'backend': engine.H3_BACKEND}
        with patch.object(engine, 'run_h3') as run:
            self.queue._run(job)
        self.assertEqual(job['status'], 'failed')
        run.assert_not_called()
        self.queue.engine.stop_idle_for_external_worker.assert_called_once()

    def test_upscale_probe_falls_back_when_frame_count_is_unavailable(self):
        import upscaler
        probe = {'streams': [{'codec_type': 'video', 'avg_frame_rate': '24/1',
                              'nb_frames': 'N/A', 'width': 640, 'height': 480}]}
        with patch.object(upscaler.subprocess, 'check_output',
                          side_effect=[json.dumps(probe), '24\n']) as check:
            info = upscaler.UpscaleManager._probe(Path('/synthetic/video.mkv'))
        self.assertEqual(info['frames'], 24)
        self.assertIn('-count_packets', check.call_args_list[1].args[0])

    def test_zero_seed_batch_stays_sequential_and_keeps_caller_payload(self):
        payload = {'seed': 0, 'take_count': 3, 'prompt': 'fixture'}
        jobs = self.queue.add(payload)
        self.assertEqual([job['seed'] for job in jobs], [0, 1, 2])
        self.assertEqual(payload['take_count'], 3)

    def test_overflow_rejects_entire_batch_before_queueing(self):
        with self.assertRaisesRegex(ValueError, 'Seed'):
            self.queue.add({'seed': 2**63 - 1, 'take_count': 2})
        self.assertEqual(self.queue.jobs, [])
        self.queue._save.assert_not_called()
        self.queue.wake.set.assert_not_called()

    def test_random_batches_randomise_each_take(self):
        for payload in ({'take_count': 3}, {'take_count': 3, 'seed': 42, 'randomise_seed': True}):
            with self.subTest(payload=payload), patch.object(engine.random, 'SystemRandom') as rng:
                rng.return_value.randrange.side_effect = [7, 11, 19]
                self.assertEqual([job['seed'] for job in self.queue.add(payload)], [7, 11, 19])


if __name__ == '__main__':
    unittest.main()
