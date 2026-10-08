"""Chatterbox request isolation with synthetic conditioning and waveform data."""
from __future__ import annotations

import contextlib
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


class ChatterboxRuntimeTests(unittest.TestCase):
    def load_server(self, configured_reference=False):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(directory)
        voice = root / 'preview.wav'
        voice.write_bytes(b'fixture')
        self.reference = voice
        model = MagicMock(sr=24000)
        model.conds = object()
        def prepare(path):
            model.conds = ('configured', path)
        model.prepare_conditionals.side_effect = prepare
        def generate(text, audio_prompt_path=None):
            if audio_prompt_path:
                model.conds = ('preview', audio_prompt_path)
            wave = MagicMock()
            wave.squeeze.return_value.detach.return_value.cpu.return_value.numpy.return_value = [0.0, 0.0]
            return wave
        model.generate.side_effect = generate
        turbo = types.SimpleNamespace(from_local=MagicMock(return_value=model))
        torch = types.SimpleNamespace(set_num_interop_threads=MagicMock(),
                                      inference_mode=contextlib.nullcontext, manual_seed=MagicMock())
        soundfile = types.SimpleNamespace(write=lambda output, *args, **kwargs: output.write(b'RIFF synthetic'))
        modules = {'torch': torch, 'soundfile': soundfile,
                   'chatterbox': types.ModuleType('chatterbox'),
                   'chatterbox.tts_turbo': types.SimpleNamespace(ChatterboxTurboTTS=turbo)}
        env = {'CHATTERBOX_MODEL_DIR': str(root), 'CHATTERBOX_REFERENCE_ROOT': str(root),
               'CHATTERBOX_REFERENCE_WAV': str(voice) if configured_reference else '',
               'CHATTERBOX_EXTRA_SITE_PACKAGES': '', 'CHATTERBOX_IDLE_SECONDS': '0'}
        with patch.dict(sys.modules, modules), patch.dict(os.environ, env):
            spec = importlib.util.spec_from_file_location('chatterbox_runtime_fixture',
                                                       ROOT / 'components/chatterbox_nano_server.py')
            server = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(server)
        server.app.config.update(TESTING=True)
        self.model = model
        self.server = server
        self.client = server.app.test_client()
        self.headers = {'Authorization': f'Bearer {server.API_KEY}'}

    def test_preview_restores_bundled_voice_for_next_request(self):
        self.load_server()
        default = self.model.conds
        response = self.client.post('/v1/audio/speech', json={'input': 'Preview',
                                    'reference_audio': str(self.reference)}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIs(self.model.conds, default)
        self.assertEqual(self.server.active_reference, 'model-default')
        response = self.client.post('/v1/audio/speech', json={'input': 'Next utterance'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIs(self.model.conds, default)
        self.model.prepare_conditionals.assert_not_called()

    def test_preview_failure_restores_configured_voice_and_activity(self):
        self.load_server(configured_reference=True)
        default = self.model.conds
        def fail(*args, **kwargs):
            self.model.conds = object()
            raise RuntimeError('synthetic generation failure')
        self.model.generate.side_effect = fail
        with patch.object(self.server.app.logger, 'exception'):
            response = self.client.post('/v1/audio/speech', json={'input': 'Preview',
                                        'reference_audio': str(self.reference)}, headers=self.headers)
        self.assertEqual(response.status_code, 500)
        self.assertIs(self.model.conds, default)
        self.assertEqual(self.server.active_reference, str(self.reference))
        self.assertEqual(self.server.active_requests, 0)
        self.model.prepare_conditionals.assert_called_once()

    def test_malformed_input_and_invalid_seeds_never_generate(self):
        self.load_server()
        bodies = [[], None, {'input': 123}, {'input': ['hello']}]
        bodies.extend({'input': 'Hello', 'seed': seed} for seed in (True, 0.5, 2**64, -(2**63)-1, 'invalid'))
        for body in bodies:
            with self.subTest(body=body):
                response = self.client.post('/v1/audio/speech', json=body, headers=self.headers)
                self.assertEqual(response.status_code, 400)
        self.model.generate.assert_not_called()

    def test_idle_clock_ignores_wall_clock_changes(self):
        self.load_server()
        with patch.object(self.server.time, 'monotonic', side_effect=[10.0, 12.0]), \
             patch.object(self.server.time, 'time', side_effect=AssertionError('wall clock used')):
            self.server.mark_activity()
            self.assertEqual(self.server.idle_seconds(), 2.0)


if __name__ == '__main__':
    unittest.main()
