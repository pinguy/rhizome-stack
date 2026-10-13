"""Onboarding visibility, private writes and first-time tool registration."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import install
import import_owner_data as importer
import register_openwebui_tools as registration
import welcome
import fetch_voice_models

spec = importlib.util.spec_from_file_location('setup_adapter', ROOT / 'components/openclaw_openwebui_adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class SetupRegressions(unittest.TestCase):
    def test_ornith_menu_accepts_exact_library_tags(self):
        for choice, expected in (('1', 'ornith-1.5:9b'), ('2', 'ornith-1.5:35b')):
            with self.subTest(choice=choice):
                with (patch.object(welcome, 'ask', return_value=choice),
                      patch.object(welcome, 'verify', return_value=(True, 'found')) as verify,
                      patch.object(welcome, 'yes') as yes,
                      patch.object(welcome.subprocess, 'run') as run,
                      contextlib.redirect_stdout(io.StringIO())):
                    self.assertEqual(welcome.choose_ollama_model('http://127.0.0.1:11434'),
                                     (expected, True, 'found'))
                    verify.assert_called_once_with('ollama', 'http://127.0.0.1:11434', '', expected)
                    yes.assert_not_called()
                    run.assert_not_called()

    def test_ornith_model_download_declined_by_default(self):
        with (patch.object(welcome, 'ask', return_value='2'),
              patch.object(welcome, 'verify', return_value=(False, 'selected Ollama model was not found')),
              patch.object(welcome, 'yes', return_value=False) as yes,
              patch.object(welcome.subprocess, 'run') as run,
              contextlib.redirect_stdout(io.StringIO())):
            model, ok, message = welcome.choose_ollama_model('http://127.0.0.1:11434')
        self.assertEqual(model, 'ornith-1.5:35b')
        self.assertFalse(ok)
        self.assertIn('ollama pull ornith-1.5:35b', message)
        self.assertFalse(yes.call_args.args[1])
        run.assert_not_called()

    def test_ornith_confirmed_pull_checks_catalogue_again(self):
        with (patch.object(welcome, 'ask', return_value='1'),
              patch.object(welcome, 'verify', side_effect=[(False, 'selected Ollama model was not found'),
                                                           (True, 'installed')]) as verify,
              patch.object(welcome, 'yes', return_value=True),
              patch.object(welcome.shutil, 'which', return_value='/usr/bin/ollama'),
              patch.object(welcome.subprocess, 'run') as run,
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(welcome.choose_ollama_model('http://127.0.0.1:11434'),
                             ('ornith-1.5:9b', True, 'installed'))
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(run.call_args.args[0], ['ollama', 'pull', 'ornith-1.5:9b'])
        self.assertEqual(run.call_args.kwargs['env']['OLLAMA_HOST'], 'http://127.0.0.1:11434')
        self.assertTrue(run.call_args.kwargs['check'])

    def test_ornith_never_pulls_when_server_unreachable(self):
        with (patch.object(welcome, 'ask', return_value='2'),
              patch.object(welcome, 'verify', return_value=(False, 'verification failed: URLError')),
              patch.object(welcome, 'yes') as yes,
              patch.object(welcome.subprocess, 'run') as run,
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(welcome.choose_ollama_model('http://127.0.0.1:11434'),
                             ('ornith-1.5:35b', False, 'verification failed: URLError'))
        yes.assert_not_called()
        run.assert_not_called()

    def test_ollama_other_model_remains_available(self):
        with (patch.object(welcome, 'ask', side_effect=['3', 'test-local']),
              patch.object(welcome, 'verify', return_value=(True, 'installed')) as verify,
              patch.object(welcome.subprocess, 'run') as run,
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(welcome.choose_ollama_model('http://127.0.0.1:11434'),
                             ('test-local', True, 'installed'))
        verify.assert_called_once_with('ollama', 'http://127.0.0.1:11434', '', 'test-local')
        run.assert_not_called()

    def test_ollama_opt_in_preserves_existing_installation(self):
        runner = MagicMock(dry_run=False)
        with patch.object(install.shutil, 'which', return_value='/usr/bin/ollama'):
            install.install_ollama(runner, 'arch')
        runner.run.assert_not_called()

    def test_ollama_dry_run_uses_arch_packages_and_never_executes(self):
        runner = install.Runner(dry_run=True)
        commands = []
        with patch.object(install.shutil, 'which', side_effect=lambda name:
                          '/usr/bin/nvidia-smi' if name == 'nvidia-smi' else None), \
             patch.object(runner, 'run', side_effect=lambda cmd: commands.append(cmd)):
            install.install_ollama(runner, 'arch')
        self.assertEqual(commands, [
            ['sudo', 'pacman', '-S', '--needed', 'ollama', 'ollama-cuda'],
            ['sudo', 'systemctl', 'enable', '--now', 'ollama'],
        ])

    def test_ollama_debian_dry_run_never_downloads(self):
        runner = install.Runner(dry_run=True)
        with patch.object(install.shutil, 'which', return_value=None), \
             patch.object(install.urllib.request, 'urlopen') as download, \
             patch.object(runner, 'run') as run:
            install.install_ollama(runner, 'debian')
        download.assert_not_called()
        run.assert_called_once_with(['sudo', 'systemctl', 'enable', '--now', 'ollama'])

    def test_ollama_welcome_offers_install_only_when_needed(self):
        with patch.object(welcome.shutil, 'which', return_value=None), \
             patch.object(welcome, 'request_json', return_value={'models': []}), \
             patch.object(welcome, 'yes') as confirm:
            welcome.ensure_ollama('ollama', 'http://127.0.0.1:11434')
        confirm.assert_not_called()  # Existing API-only Ollama backend works.

        with patch.object(welcome.shutil, 'which', return_value=None), \
             patch.object(welcome, 'yes', return_value=False), \
             self.assertRaisesRegex(ValueError, 'declined'):
            welcome.ensure_ollama('gguf', 'http://127.0.0.1:11434')

    def test_voice_fetch_uses_selected_root_without_downloading_in_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'custom/models'
            download = MagicMock()
            with patch.dict(sys.modules, {'huggingface_hub': types.SimpleNamespace(snapshot_download=download)}), \
                 patch.object(sys, 'argv', ['fetch-voice', '--model-root', str(destination)]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(fetch_voice_models.main(), 0)
            self.assertEqual([call.kwargs['local_dir'] for call in download.call_args_list],
                             [destination / 'chatterbox-nano', destination / 'faster-whisper-large-v3-turbo'])

    def test_selected_provider_is_visible_and_retains_fallbacks_and_tuning(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / 'openclaw.json'
            settings = {'alias': 'My primary', 'params': {'temperature': 0.3}}
            config.write_text(json.dumps({'agents': {'defaults': {
                'model': {'primary': 'old/model', 'fallbacks': ['old/fallback']},
                'models': {'provider/chosen': settings, 'old/fallback': {}},
            }}}))
            with patch.object(welcome, 'OPENCLAW_CONFIG', config):
                welcome.update_openclaw('provider', 'chosen', 'http://unused', '')
                welcome.update_openclaw('provider', 'new', 'http://unused', '')
            saved = json.loads(config.read_text())['agents']['defaults']
            self.assertEqual(saved['model'], {'primary': 'provider/new', 'fallbacks': ['old/fallback']})
            self.assertEqual(saved['models']['provider/chosen'], settings)
            catalogue = subprocess.CompletedProcess([], 0, json.dumps({'models': [
                {'key': 'provider/new', 'available': True},
                {'key': 'unselected/model', 'available': True},
            ]}))
            with patch.object(adapter, 'CONFIG', config), \
                 patch.object(adapter.subprocess, 'run', return_value=catalogue):
                self.assertEqual([row['id'] for row in adapter.refresh_models()], ['openclaw/provider/new'])
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((config.parent / 'openclaw.json.before-welcome').read_text())
                             ['agents']['defaults']['model']['primary'], 'old/model')

    def test_wizard_private_writes_ignore_predictable_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            victim = root / 'other.txt'
            victim.write_text('keep me')
            env, config = root / 'stack.env', root / 'openclaw.json'
            config.write_text('{}')
            for path in (env, config):
                path.with_suffix('.tmp').symlink_to(victim)
            with patch.multiple(welcome, CONFIG_DIR=root, ENV_PATH=env, OPENCLAW_CONFIG=config):
                welcome.set_env({'SYNTHETIC_KEY': 'fixture value'})
                welcome.update_openclaw('provider', 'demo', 'http://unused', '')
            self.assertEqual(victim.read_text(), 'keep me')
            self.assertEqual(welcome.shlex.split(env.read_text().split('=', 1)[1]), ['fixture value'])
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_memory_profile_private_config_write_ignores_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / 'claw'
            home.mkdir()
            config = home / 'openclaw.json'
            config.write_text('{"gateway":{"port":18789}}')
            victim = root / 'other.txt'
            victim.write_text('keep me')
            config.with_suffix('.json.tmp').symlink_to(victim)
            runner = MagicMock(dry_run=False)
            with patch.multiple(install, STACK_ROOT=root / 'stack', OPENCLAW_HOME=home):
                install.install_memory(runner, root / 'node/bin')
            self.assertEqual(victim.read_text(), 'keep me')
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(config.read_text())['gateway']['port'], 18789)
            self.assertEqual(json.loads(config.read_text())['plugins']['slots']['memory'], 'memory-rhizome')

    def test_import_write_preserves_duplicate_provenance_without_symlink_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            corpus = root / 'imports'
            corpus.mkdir()
            source = root / 'note.txt'
            source.write_text('Synthetic import')
            digest = hashlib.sha256(b'Synthetic import').hexdigest()
            victim = root / 'other.txt'
            victim.write_text('keep me')
            (corpus / (digest + '.tmp')).symlink_to(victim)
            with patch.object(importer, 'CORPUS', corpus):
                self.assertEqual(importer.import_source(source, 'documents'), 1)
                source2 = root / 'second.txt'
                source2.write_text(source.read_text())
                self.assertEqual(importer.import_source(source2, 'documents'), 0)
            record = corpus / (digest + '.json')
            self.assertEqual(victim.read_text(), 'keep me')
            self.assertEqual(record.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(json.loads(record.read_text())['origins']), 2)

    def test_tool_registration_creates_missing_and_preserves_existing_over_http(self):
        created = []
        class API(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def respond(self, status, value):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def do_GET(self):
                if self.path.endswith('/id/rhizome_memory'):
                    self.respond(200, {'id': 'rhizome_memory', 'content': 'owner customisation'})
                elif self.path.endswith('/id/denied'):
                    self.respond(401, {'detail': 'unauthorised'})
                else:
                    self.respond(404, {'detail': 'not found'})
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if 'id' not in payload:
                    self.respond(404, {'detail': 'not found'})
                    return
                created.append(payload)
                self.respond(200, {'id': payload['id']})
        server = ThreadingHTTPServer(('127.0.0.1', 0), API)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                token = Path(temporary) / 'token'
                token.write_text('synthetic-local-token')
                token.chmod(0o600)
                base = f'http://127.0.0.1:{server.server_port}'
                with patch.object(sys, 'argv', ['register', '--base-url', base, '--token-file', str(token)]), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(registration.main(), 0)
                self.assertEqual([row['id'] for row in created],
                             ['rhizome_web_search', 'openclaw_agent', 'minimax_music_3', 'qwen_image'])
                with self.assertRaisesRegex(RuntimeError, '401'):
                    registration.api(base, 'synthetic', 'GET', '/id/denied')
                with self.assertRaisesRegex(RuntimeError, '404'):
                    registration.api(base, 'synthetic', 'POST', '/create', {})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == '__main__':
    unittest.main()
