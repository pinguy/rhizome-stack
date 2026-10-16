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
