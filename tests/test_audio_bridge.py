"""Exercise the HTTP bridge without speech models or systemd services."""
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
