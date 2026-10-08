"""Exercise the HTTP bridge without speech models or systemd services."""
import importlib.util
import io
import json
import subprocess
import sys
import threading
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "components/openwebui_audio_bridge.py"
if not SOURCE.exists():
    SOURCE = ROOT / "openwebui_audio_bridge.py"
spec = importlib.util.spec_from_file_location("audio_bridge", SOURCE)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class AudioBridgeTests(unittest.TestCase):
    def setUp(self):
        bridge.app.config.update(TESTING=True)
        self.client = bridge.app.test_client()
        self.headers = {"Authorization": f"Bearer {bridge.BRIDGE_API_KEY}"}
        self.uploads = tempfile.TemporaryDirectory()
        self.addCleanup(self.uploads.cleanup)
        self.upload_root = Path(self.uploads.name)
        temporary_directory = tempfile.TemporaryDirectory
        self.enterContext(patch.object(
            bridge.tempfile, "TemporaryDirectory",
            side_effect=lambda **kwargs: temporary_directory(dir=self.upload_root, **kwargs)))
        # Configure only the prerequisite check; no worker or model is started.
        if hasattr(bridge, "whisper_configured"):
            self.enterContext(patch.object(bridge, "whisper_configured", return_value=True))
        else:
            self.enterContext(patch.object(bridge, "TRANSCRIBE_SH", str(SOURCE)))
        self.decode = self.enterContext(patch.object(bridge, "transcribe_whisper_audio"))
        self.unload = self.enterContext(patch.object(bridge, "schedule_whisper_unload"))

    def upload(self, filename, endpoint="/v1/audio/transcriptions", headers=None):
        return self.client.post(endpoint, headers=self.headers if headers is None else headers,
                                data={"file": (io.BytesIO(b"test audio"), filename)})

    def test_untrusted_filenames_stay_in_private_temporary_directory(self):
        outside = self.upload_root / "outside.wav"
        outside.write_bytes(b"keep this")
        for filename in (str(outside), "../outside.wav", "..", "normal.wav"):
            with self.subTest(filename=filename):
                observed = []

                def decode(path):
                    observed.append(path)
                    self.assertNotEqual(path.parent, self.upload_root)
                    self.assertTrue(path.resolve().is_relative_to(self.upload_root))
                    self.assertEqual(path.read_bytes(), b"test audio")
                    return "transcribed"

                self.decode.side_effect = decode
                response = self.upload(filename)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["text"], "transcribed")
                self.assertEqual(outside.read_bytes(), b"keep this")
                self.assertFalse(observed[0].exists())

    def test_failed_transcription_cleans_up_upload(self):
        observed = []

        def fail(path):
            observed.append(path)
            raise RuntimeError("decoder unavailable")

        self.decode.side_effect = fail
        response = self.upload("normal.wav", endpoint="/audio/transcriptions")
        self.assertEqual(response.status_code, 500)
        self.assertFalse(observed[0].exists())
        self.unload.assert_not_called()

    def test_authentication_happens_before_file_writes(self):
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            with self.subTest(headers=headers):
                response = self.upload("../outside.wav", headers=headers)
                self.assertEqual(response.status_code, 401)
        self.decode.assert_not_called()
        self.assertEqual(list(self.upload_root.iterdir()), [])

    def test_health_deadline_ignores_wall_clock_changes(self):
        with patch.object(bridge.time, "monotonic", side_effect=[10.0, 10.0, 11.1]), \
             patch.object(bridge.time, "time", side_effect=AssertionError("wall clock used")), \
             patch.object(bridge.time, "sleep"), \
             patch.object(bridge.requests, "get", side_effect=ConnectionError) as get:
            self.assertFalse(bridge.wait_for_chatterbox("http://unused", timeout_s=1.0))
        self.assertEqual(get.call_count, 1)

    def test_healthy_backend_returns_immediately(self):
        with patch.object(bridge.requests, "get") as get, patch.object(bridge.time, "sleep") as sleep:
            get.return_value.ok = True
            self.assertTrue(bridge.wait_for_chatterbox("http://unused", timeout_s=1.0))
        sleep.assert_not_called()

    def test_malformed_speech_never_starts_backend(self):
        with patch.object(bridge, 'ensure_chatterbox_running') as start:
            for body in ([], None, {'input': 12}, {'input': ['text']}, {'input': '""'}):
                with self.subTest(body=body):
                    response = self.client.post('/v1/audio/speech', json=body, headers=self.headers)
                    self.assertEqual(response.status_code, 400)
            start.assert_not_called()

    def test_stop_during_startup_prevents_synthesis(self):
        def startup(*args):
            bridge.cancel_active_tts()
            return True
        with patch.object(bridge, 'ensure_chatterbox_running', side_effect=startup), \
             patch.object(bridge.requests, 'post') as post:
            response = self.client.post('/v1/audio/speech', json={'input': 'Hello'}, headers=self.headers)
            self.assertEqual(response.status_code, 409)
            post.assert_not_called()

    def test_stop_during_final_chunk_discards_audio(self):
        def synthesize(*args, **kwargs):
            bridge.cancel_active_tts()
            return MagicMock(content=b'synthetic audio')
        with patch.object(bridge, 'ensure_chatterbox_running', return_value=True), \
             patch.object(bridge.requests, 'post', side_effect=synthesize) as post:
            response = self.client.post('/v1/audio/speech', json={'input': 'Hello'}, headers=self.headers)
            self.assertEqual(response.status_code, 409)
            post.assert_called_once()


class WhisperLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(bridge, '_whisper_worker', None))
        self.enterContext(patch.object(bridge, '_whisper_unload_timer', None))
        self.enterContext(patch.object(bridge, '_whisper_idle_epoch', 0))
        self.addCleanup(bridge.cancel_whisper_unload)

    def worker(self, code):
        worker = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True)
        self.addCleanup(bridge.stop_whisper_worker, worker)
        return worker

    def test_partial_json_reply_times_out_instead_of_hanging(self):
        worker = self.worker("import sys,time; sys.stdout.write('{'); sys.stdout.flush(); time.sleep(30)")
        with self.assertRaises(TimeoutError):
            bridge.whisper_reply(worker, 0.2)

    def test_eof_and_non_object_reply_fail_cleanly(self):
        for code in ("pass", "print('[]')"):
            with self.subTest(code=code):
                worker = self.worker(code)
                with self.assertRaises(RuntimeError):
                    bridge.whisper_reply(worker, 5)

    def test_failed_decode_reaps_worker_and_allows_fresh_start(self):
        code = "import sys; print('{\"error\":\"decode failed\"}', flush=True); sys.stdin.readline()"
        worker = self.worker(code)
        bridge._whisper_worker = worker
        with patch.object(bridge, 'get_whisper_worker', return_value=worker):
            with self.assertRaisesRegex(RuntimeError, 'decode failed'):
                bridge.transcribe_whisper_audio(Path('synthetic.wav'))
        self.assertIsNone(bridge._whisper_worker)
        self.assertIsNotNone(worker.poll())
        self.assertTrue(worker.stdout.closed)

    def test_successful_worker_returns_complete_unicode_text(self):
        code = "import sys,json; sys.stdin.readline(); print(json.dumps({'text':'  café  '}), flush=True)"
        worker = self.worker(code)
        with patch.object(bridge, 'get_whisper_worker', return_value=worker):
            self.assertEqual(bridge.transcribe_whisper_audio(Path('synthetic.wav')), 'café')

    def test_failed_startup_does_not_cache_a_live_worker(self):
        worker = self.worker("import time; print('{\"ready\":false}', flush=True); time.sleep(30)")
        with patch.object(bridge.subprocess, 'Popen', return_value=worker):
            with self.assertRaisesRegex(RuntimeError, 'failed to become ready'):
                bridge.get_whisper_worker()
        self.assertIsNone(bridge._whisper_worker)
        self.assertIsNotNone(worker.poll())

    def test_idle_timer_waits_for_decode_and_rejects_stale_epoch(self):
        worker = MagicMock()
        bridge._whisper_worker = worker
        entered = threading.Event()
        done = threading.Event()
        def expire():
            entered.set()
            bridge.unload_whisper_model_if_idle(0)
            done.set()
        with patch.object(bridge, 'stop_whisper_worker') as stop:
            with bridge._whisper_decode_lock:
                thread = threading.Thread(target=expire, daemon=True)
                thread.start()
                self.assertTrue(entered.wait(1))
                self.assertFalse(done.wait(0.05))
                bridge.cancel_whisper_unload()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            stop.assert_not_called()
            self.assertIs(bridge._whisper_worker, worker)
            bridge.unload_whisper_model_if_idle(bridge._whisper_idle_epoch)
            stop.assert_called_once_with(worker)
            self.assertIsNone(bridge._whisper_worker)


if __name__ == "__main__":
    unittest.main()
