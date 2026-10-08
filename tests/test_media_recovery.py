"""Media hand-off and receipt recovery without real models or service changes."""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


media = load('media_recovery', 'components/openwebui_local_media.py')
registration = load('tool_registration', 'tools/register_openwebui_tools.py')


def http_error(code):
    return urllib.error.HTTPError('http://localhost/', code, 'fixture', {}, io.BytesIO(b'fixture'))


class QueueSafetyTest(unittest.TestCase):
    def test_only_refused_connection_means_offline(self):
        with patch.object(media, 'request', side_effect=urllib.error.URLError(ConnectionRefusedError())):
            self.assertTrue(media.comfy_idle())
        for error in (http_error(500), http_error(404), urllib.error.URLError('unreachable'), TimeoutError()):
            with self.subTest(error=error), patch.object(media, 'request', side_effect=error):
                with self.assertRaises((urllib.error.URLError, TimeoutError)):
                    media.comfy_idle()

    def test_malformed_queue_is_not_idle(self):
        for value in ({}, {'queue_running': [], 'queue_pending': None}, [], {'queue_running': 0, 'queue_pending': []}):
            with self.subTest(value=value), patch.object(media, 'request', return_value=value):
                with self.assertRaises(RuntimeError):
                    media.comfy_idle()

    def test_valid_idle_and_busy_queues(self):
        for running, pending in (([], []), ([['running']], []), ([], [['pending']])):
            with patch.object(media, 'request', return_value={'queue_running': running, 'queue_pending': pending}):
                self.assertEqual(media.comfy_idle(), not running and not pending)

    def test_health_error_prevents_unloading(self):
        with patch.object(media, 'health', side_effect=http_error(503)), patch.object(media, 'request') as request:
            with self.assertRaises(urllib.error.HTTPError):
                media.hand_over()
            request.assert_not_called()

    def test_queue_error_prevents_unloading(self):
        with patch.object(media, 'health', return_value={'busy': False}), \
             patch.object(media, 'request', side_effect=http_error(500)) as request:
            with self.assertRaises(urllib.error.HTTPError):
                media.hand_over()
            self.assertEqual(request.call_args.args[:2], ('GET', media.COMFY + '/queue'))
            request.assert_called_once()

    def test_release_error_is_not_reported_as_shutdown(self):
        with patch.object(media, 'comfy_idle', return_value=True), \
             patch.object(media, 'request', side_effect=http_error(500)):
            with self.assertRaises(urllib.error.HTTPError):
                media.release_models('music')

    def test_shutdown_poll_error_is_not_a_closed_port(self):
        with patch.object(media, 'comfy_idle', return_value=True), \
             patch.object(media, 'request', side_effect=[{}, {}, http_error(500)]):
            with self.assertRaises(urllib.error.HTTPError):
                media.release_models('music')

    def test_unhealthy_app_is_not_restarted(self):
        with patch.object(media, 'health', side_effect=http_error(503)), \
             patch.object(media.subprocess, 'run') as run:
            with self.assertRaises(urllib.error.HTTPError):
                media.ensure_app('music')
            run.assert_not_called()


class ReceiptTest(unittest.TestCase):
    def test_receipt_private_and_predictable_symlink_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            victim = root / 'unrelated'
            victim.write_text('preserve')
            receipt = root / 'job.json'
            receipt.with_suffix('.tmp').symlink_to(victim)
            media.save_job(receipt, {'status': 'submitting'})
            self.assertEqual(victim.read_text(), 'preserve')
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(receipt.read_text())['status'], 'submitting')

    def test_failed_write_preserves_receipt_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / 'job.json'
            media.save_job(receipt, {'status': 'running'})
            with patch.object(media.os, 'fsync', side_effect=OSError('fixture disk failure')):
                with self.assertRaises(OSError):
                    media.save_job(receipt, {'status': 'generated'})
            self.assertEqual(json.loads(receipt.read_text())['status'], 'running')
            self.assertEqual(list(Path(temporary).iterdir()), [receipt])


class RecoveryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name)
        for name, value in [('STATE', self.state), ('ensure_app', unittest.mock.Mock()),
                            ('hand_over', unittest.mock.Mock(return_value=['synthetic-model'])),
                            ('release_models', unittest.mock.Mock())]:
            patcher = patch.object(media, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        sleeper = patch.object(media.asyncio, 'sleep', AsyncMock())
        sleeper.start()
        self.addCleanup(sleeper.stop)
        self.user = {'id': 'user-1'}
        self.metadata = {'chat_id': 'chat-1', 'message_id': 'message-1'}

    async def test_completed_file_survives_attachment_failure_for_both_generators(self):
        for kind in ('music', 'image'):
            with self.subTest(kind=kind):
                payload = {'prompt': 'synthetic'}
                output = str(self.state / (kind + '.output'))
                def upstream(method, url, *args):
                    if method == 'POST':
                        return {'prompt_id': 'job-1'} if kind == 'music' else {'jobs': [{'id': 'job-1'}]}
                    if kind == 'music':
                        return {'state': 'done', 'path': output}
                    return {'jobs': [{'id': 'job-1', 'status': 'complete', 'asset_id': 'asset-1'}],
                            'assets': [{'id': 'asset-1', 'absolute_path': output}]}
                with patch.object(media, 'request', side_effect=upstream) as request, \
                     patch.object(media, 'attach_result', AsyncMock(side_effect=[OSError('upload unavailable'),
                                                                                {'file_id': 'file-1'}])) as attach:
                    first = json.loads(await media.generate(kind, payload, self.user, self.metadata))
                    self.assertEqual(first['status'], 'error')
                    receipts = [json.loads(p.read_text()) for p in self.state.glob('*.json')]
                    self.assertTrue(any(r.get('source') == output and r['status'] == 'generated' for r in receipts))
                    second = json.loads(await media.generate(kind, payload, self.user, self.metadata))
                    self.assertEqual(second['status'], 'success')
                    third = json.loads(await media.generate(kind, payload, self.user, self.metadata))
                    self.assertEqual(second, third)
                    self.assertEqual(payload, {'prompt': 'synthetic'})
                    self.assertEqual(request.call_count, 2, 'Recovery must not submit or poll a stopped engine')
                    self.assertEqual(attach.await_count, 2)
                    self.assertEqual(attach.await_args.args[1], output)

    async def test_uncertain_submission_is_not_replayed(self):
        with patch.object(media, 'request', side_effect=TimeoutError('acknowledgement lost')) as request:
            await media.generate('image', {}, self.user, self.metadata)
            result = json.loads(await media.generate('image', {}, self.user, self.metadata))
            self.assertIn('uncertain', result['error'])
            request.assert_called_once()

    async def test_failed_generation_is_not_polled_or_submitted_again(self):
        with patch.object(media, 'request', side_effect=[{'prompt_id': 'job-1'},
                                                       {'state': 'error', 'error': 'synthetic failure'}]) as request:
            first = json.loads(await media.generate('music', {}, self.user, self.metadata))
            second = json.loads(await media.generate('music', {}, self.user, self.metadata))
            self.assertEqual(first['error'], 'synthetic failure')
            self.assertEqual(first, second)
            self.assertEqual(request.call_count, 2)


class ToolRegistrationTest(unittest.TestCase):
    def test_missing_tool_lookup_allows_creation(self):
        with patch.object(registration.urllib.request, 'urlopen', side_effect=http_error(404)):
            self.assertIsNone(registration.api('http://localhost', 'fixture', 'GET', '/id/qwen_image'))

    def test_other_api_failures_remain_errors(self):
        for method, path, code in [('GET', '/id/qwen_image', 401), ('GET', '/id/qwen_image', 500),
                                   ('POST', '/create', 404), ('GET', '/unexpected', 404)]:
            with self.subTest(method=method, path=path, code=code), \
                 patch.object(registration.urllib.request, 'urlopen', side_effect=http_error(code)):
                with self.assertRaises(RuntimeError):
                    registration.api('http://localhost', 'fixture', method, path)


if __name__ == '__main__':
    unittest.main()
