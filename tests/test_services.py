"""Loopback HTTP and configuration regressions; no providers, models or GPU needed."""
from __future__ import annotations

import contextlib
import http.client
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


adapter = load('adapter_test', 'components/openclaw_openwebui_adapter.py')
sync = load('model_sync_test', 'components/openclaw_ollama_model_sync.py')
music = load('music_test', 'components/creative/minimax-music/app.py')
sys.path.insert(0, str(ROOT / 'components/creative/qwen-image-desk'))
qwen = load('qwen_http_test', 'components/creative/qwen-image-desk/app.py')
gliner = load('gliner_http_test', 'components/workforce_gliner_server.py')
# These tests exercise the HTTP boundary only; no encoder or vector operations.
with patch.dict(sys.modules, {'numpy': types.ModuleType('numpy'),
                             'sentence_transformers': types.SimpleNamespace(SentenceTransformer=None)}):
    retrieval = load('retrieval_http_test', 'components/workforce_retrieval_server.py')


@contextlib.contextmanager
def serve(handler, state=None):
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    server.state = state
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(address, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection(*address, timeout=2)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


class AdapterTest(unittest.TestCase):
    payload = json.dumps({'model': 'openclaw/provider/demo', 'stream': True, 'messages': []})

    def test_invalid_requests_do_not_call_gateway(self):
        with patch.object(adapter, 'open_gateway') as upstream, serve(adapter.Handler) as address:
            for body in ('[]', 'null', '{', '{"model":123}', '{"model":"openclaw/"}',
                         '{"model":"openclaw/provider/demo\\nInjected: x"}'):
                with self.subTest(body=body):
                    self.assertEqual(request(address, 'POST', '/v1/chat/completions', body)[0], 400)
            upstream.assert_not_called()

    def test_non_json_gateway_error_is_forwarded_once_without_retry(self):
        error = urllib.error.HTTPError('http://gateway/', 429, 'busy', {}, io.BytesIO(b'<html>busy</html>'))
        with patch.object(adapter, 'gateway_token', return_value='synthetic'), \
             patch.object(adapter, 'open_gateway', side_effect=error) as upstream, serve(adapter.Handler) as address:
            status, _, raw = request(address, 'POST', '/v1/chat/completions', self.payload)
            self.assertEqual(status, 429)
            self.assertIn('429', json.loads(raw)['error']['message'])
            self.assertNotIn(b'<html>', raw)
            upstream.assert_called_once()

    def test_gateway_connection_failure_is_502(self):
        with patch.object(adapter, 'gateway_token', return_value='synthetic'), \
             patch.object(adapter, 'open_gateway', side_effect=urllib.error.URLError('offline')), \
             serve(adapter.Handler) as address:
            self.assertEqual(request(address, 'POST', '/v1/chat/completions', self.payload)[0], 502)

    def test_sse_first_event_arrives_before_upstream_finishes(self):
        release = threading.Event()
        seen = []
        first, last = b'data: first\n\n', b'data: [DONE]\n\n'

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                seen.append((self.headers['x-openclaw-model'], json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(first) + len(last)))
                self.end_headers()
                self.wfile.write(first)
                self.wfile.flush()
                release.wait(4)
                self.wfile.write(last)

        with serve(Upstream) as upstream, \
             patch.object(adapter, 'GATEWAY', f'http://{upstream[0]}:{upstream[1]}'), \
             patch.object(adapter, 'gateway_token', return_value='synthetic'), serve(adapter.Handler) as address:
            connection = http.client.HTTPConnection(*address, timeout=1)
            try:
                connection.request('POST', '/v1/chat/completions', self.payload)
                response = connection.getresponse()
                self.assertEqual(response.read(len(first)), first)
                release.set()
                self.assertEqual(response.read(), last)
            finally:
                release.set()
                connection.close()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], 'provider/demo')
        self.assertEqual(seen[0][1]['model'], 'openclaw/default')

    def test_stream_failure_does_not_append_second_http_response(self):
        upstream = unittest.mock.MagicMock()
        upstream.__enter__.return_value = upstream
        upstream.status = 200
        upstream.headers = {'Content-Type': 'text/event-stream'}
        upstream.read1.side_effect = [b'data: hello\n\n', OSError('upstream dropped')]
        with patch.object(adapter, 'gateway_token', return_value='synthetic'), \
             patch.object(adapter, 'open_gateway', return_value=upstream), serve(adapter.Handler) as address:
            status, _, raw = request(address, 'POST', '/v1/chat/completions', self.payload)
            self.assertEqual(status, 200)
            self.assertEqual(raw, b'data: hello\n\n')


class ModelSyncTest(unittest.TestCase):
    def test_sync_preserves_existing_model_settings_and_removes_stale_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / 'openclaw.json'
            retained = {'alias': 'My local worker', 'params': {'temperature': 0.25}}
            config.write_text(json.dumps({'agents': {'defaults': {'models': {
                'ollama/kept': retained, 'ollama/gone': {}, 'provider/remote': {'alias': 'Remote'},
            }}}}))
            with patch.object(sync, 'CONFIG', config), \
                 patch.object(sync, 'ollama_models', return_value={'ollama/kept', 'ollama/new'}), \
                 patch.object(sync.subprocess, 'run') as run:
                self.assertTrue(sync.sync_once())
                written = json.loads(run.call_args.args[0][4])
                self.assertEqual(written, {'provider/remote': {'alias': 'Remote'},
                                          'ollama/kept': retained, 'ollama/new': {}})
                self.assertEqual(run.call_args.kwargs['timeout'], 30)
                self.assertEqual(run.call_args.kwargs['env']['OPENCLAW_CONFIG_PATH'], str(config))

    def test_once_reports_failure_to_systemd(self):
        with patch.object(sync.sys, 'argv', ['sync', '--once']), \
             patch.object(sync, 'sync_once', side_effect=OSError('offline')), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(sync.main(), 1)

    def test_non_default_ollama_endpoint_is_used_for_model_details(self):
        responses = [io.BytesIO(b'{"models":[{"name":"local"}]}'),
                     io.BytesIO(b'{"capabilities":["tools"]}')]
        with patch.object(sync, 'OLLAMA_BASE', 'http://localhost:12345'), \
             patch.object(sync, 'OLLAMA_TAGS', 'http://localhost:12345/api/tags'), \
             patch.object(sync.urllib.request, 'urlopen', side_effect=responses) as urlopen:
            self.assertEqual(sync.ollama_models(), {'ollama/local'})
            self.assertEqual(urlopen.call_args_list[1].args[0].full_url, 'http://localhost:12345/api/show')


class WorkforceHTTPTest(unittest.TestCase):
    def test_invalid_classifier_deadline_is_rejected_before_enqueue(self):
        state = unittest.mock.MagicMock()
        state.config = {'gliner': {'max_request_chars': 4000}}
        with serve(gliner.Handler, state) as address:
            for deadline in ('invalid', float('nan'), float('inf')):
                body = json.dumps({'request': 'test', 'taxonomy': {}, 'deadline_seconds': deadline})
                self.assertEqual(request(address, 'POST', '/classify', body)[0], 400)
            self.assertEqual(request(address, 'POST', '/classify', headers={'Content-Length': 'bad'})[0], 400)
        state.jobs.put.assert_not_called()

    def test_retrieval_bounds_release_capacity_and_unknown_route_is_404(self):
        index = unittest.mock.MagicMock()
        index.search.return_value = {'candidates': []}
        handler = retrieval.make_handler(index, threading.BoundedSemaphore(1))
        with serve(handler) as address:
            self.assertEqual(request(address, 'POST', '/search', headers={'Content-Length': '-1'})[0], 400)
            self.assertEqual(request(address, 'POST', '/search', '[]')[0], 400)
            self.assertEqual(request(address, 'POST', '/search', '{}')[0], 200)
            self.assertEqual(request(address, 'GET', '/missing')[0], 404)
        index.search.assert_called_once_with({})


class CreativeHTTPTest(unittest.TestCase):
    def test_audio_rejects_traversal_absolute_paths_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'output'
            output.mkdir()
            (root / 'private.mp3').write_bytes(b'private fixture')
            (output / 'escape').symlink_to(root, target_is_directory=True)
            (output / 'linked.mp3').symlink_to(root / 'private.mp3')
            with patch.object(music, 'COMFY_OUTPUT', str(output)), \
                 patch.object(music.urllib.request, 'urlopen') as upstream, serve(music.Handler) as address:
                for sub, name in (('..', 'private.mp3'), (str(root), 'private.mp3'),
                                  ('escape', 'private.mp3'), ('', 'linked.mp3')):
                    query = music.urllib.parse.urlencode({'filename': name, 'subfolder': sub})
                    with self.subTest(sub=sub, name=name):
                        self.assertEqual(request(address, 'GET', '/api/audio?' + query)[0], 400)
                upstream.assert_not_called()

    def test_audio_fallback_has_correct_bytes_and_mime(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'minimax_app'
            output.mkdir()
            (output / 'song.wav').write_bytes(b'RIFF synthetic audio')
            with patch.object(music, 'COMFY_OUTPUT', temporary), \
                 patch.object(music.urllib.request, 'urlopen', side_effect=OSError('offline')), serve(music.Handler) as address:
                status, headers, body = request(address, 'GET', '/api/audio?filename=song.wav&subfolder=minimax_app')
                self.assertEqual(status, 200)
                self.assertEqual(headers['Content-Type'], 'audio/wav')
                self.assertEqual(body, b'RIFF synthetic audio')

    def test_sidecar_symlink_cannot_read_or_delete_outside_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'output/minimax_app'
            folder.mkdir(parents=True)
            private = root / 'private.json'
            private.write_text('{"private":true}')
            song = folder / 'song.mp3'
            song.write_bytes(b'audio')
            (folder / 'song.json').symlink_to(private)
            with patch.object(music, 'COMFY_OUTPUT', str(folder.parent)), serve(music.Handler) as address:
                self.assertEqual(request(address, 'GET', '/api/recipe?filename=song.mp3')[0], 400)
                self.assertEqual(request(address, 'POST', '/api/delete', '{"filename":"song.mp3"}')[0], 400)
                self.assertTrue(song.exists())
                self.assertEqual(private.read_text(), '{"private":true}')

    def test_invalid_generation_never_starts_engine(self):
        with patch.object(music, 'engine_start') as start, patch.object(music, 'comfy_up', return_value=False), \
             patch.object(music, 'submit') as submit, serve(music.Handler) as address:
            bad = ['[]', 'null', '{']
            for options in ({}, {'caption': []}, {'seed': 'banana'}, {'steps': 0},
                            {'seconds': float('nan')}, {'seconds': 301}, {'tiled': 'false'}):
                bad.append(json.dumps({'caption': 'Synthetic prompt', **options} if options else {}))
            for body in bad:
                with self.subTest(body=body):
                    self.assertEqual(request(address, 'POST', '/api/generate', body)[0], 400)
            start.assert_not_called()
            submit.assert_not_called()

    def test_generation_preserves_full_integer_seed(self):
        music.Handler.JOBS.clear()
        seed = 2**64 - 1
        with patch.object(music, 'comfy_up', return_value=True), \
             patch.object(music, 'submit', return_value={'prompt_id': 'synthetic-job'}) as submit, \
             patch.dict(music.STATE, {'busy': False}), serve(music.Handler) as address:
            status, _, body = request(address, 'POST', '/api/generate', json.dumps({'caption': 'A song', 'seed': str(seed)}))
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['seed'], seed)
            self.assertEqual(submit.call_args.args[0]['7']['inputs']['seed'], seed)
        music.Handler.JOBS.clear()

    def test_creative_body_bounds_reject_without_reading(self):
        for handler, route in ((music.Handler, '/api/generate'), (qwen.Handler, '/api/image-studio/generate')):
            with serve(handler) as address:
                for length in ('-1', '131073'):
                    with self.subTest(handler=handler, length=length):
                        self.assertEqual(request(address, 'POST', route, headers={'Content-Length': length})[0], 400)


if __name__ == '__main__':
    unittest.main()
