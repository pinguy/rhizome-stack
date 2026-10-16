"""Synthetic HTTP attacks, private configuration migration and supported runtimes."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tests')]
import install
import privacy_audit
from test_services import adapter, music, qwen, serve, request


class HTTPBoundaryTest(unittest.TestCase):
    def test_adapter_rejects_unauthenticated_browser_and_rebinding_requests(self):
        payload = json.dumps({'model': 'openclaw/provider/demo', 'messages': []})
        good = {'Authorization': 'Bearer synthetic-secret', 'Content-Type': 'application/json'}
        with patch.dict(os.environ, {'RHIZOME_ADAPTER_TOKEN': 'synthetic-secret'}), \
             patch.object(adapter, 'open_gateway') as gateway, serve(adapter.Handler) as address:
            cases = [({}, 401), ({'Authorization': 'Bearer wrong'}, 401),
                     ({**good, 'Origin': 'https://hostile.invalid'}, 403),
                     ({**good, 'Origin': 'null'}, 403),
                     ({**good, 'Host': 'rebind.invalid'}, 403),
                     ({**good, 'Host': '127.0.0.1.attacker.invalid'}, 403),
                     ({**good, 'Host': 'localhost' + '@' + 'attacker.invalid'}, 403),
                     ({**good, 'Content-Type': 'text/plain'}, 415),
                     ({**good, 'Content-Type': 'application/x-www-form-urlencoded'}, 415),
                     ({**good, 'Sec-Fetch-Site': 'cross-site'}, 403)]
            for headers, expected in cases:
                with self.subTest(headers=headers):
                    self.assertEqual(request(address, 'POST', '/v1/chat/completions', payload, headers)[0], expected)
            self.assertEqual(request(address, 'GET', '/v1/models')[0], 401)
            self.assertEqual(request(address, 'GET', '/v1/models', headers=good)[0], 200)
            self.assertEqual(request(address, 'GET', '/health')[0], 200)
            gateway.assert_not_called()

    def test_adapter_fails_closed_without_configured_secret(self):
        for token in ('', 'local-adapter'):
            with patch.dict(os.environ, {'RHIZOME_ADAPTER_TOKEN': token}), serve(adapter.Handler) as address:
                self.assertEqual(request(address, 'GET', '/v1/models')[0], 503)

    def test_duplicate_host_and_auth_headers_are_rejected(self):
        with patch.dict(os.environ, {'RHIZOME_ADAPTER_TOKEN': 'synthetic-secret'}), serve(adapter.Handler) as address:
            for header, value, expected in [('Host', 'localhost', 403),
                                            ('Authorization', 'Bearer synthetic-secret', 401)]:
                connection = http.client.HTTPConnection(*address, timeout=2)
                try:
                    connection.putrequest('GET', '/v1/models')
                    connection.putheader('Authorization', 'Bearer synthetic-secret')
                    connection.putheader(header, value)
                    connection.endheaders()
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected)
                    response.read()
                finally:
                    connection.close()

    def test_creative_helpers_reject_cross_site_but_allow_same_origin(self):
        for app, path, function in [(qwen, '/api/image-studio/expand', 'expand_prompt'),
                                     (music, '/api/ai_fill', 'ai_fill')]:
            with patch.object(app, function, return_value={}) as helper, serve(app.Handler) as address:
                body = json.dumps({'model': 'openclaw/provider/demo', 'prompt': 'fixture', 'brief': 'fixture'})
                for headers, status in [({'Origin': 'https://hostile.invalid'}, 403),
                                         ({'Host': 'rebind.invalid'}, 403),
                                         ({'Content-Type': 'text/plain'}, 415)]:
                    self.assertEqual(request(address, 'POST', path, body, headers)[0], status)
                helper.assert_not_called()
                origin = f'http://{address[0]}:{address[1]}'
                self.assertEqual(request(address, 'POST', path, body, {'Origin': origin})[0], 200)
                helper.assert_called_once()


class SecurityConfigurationTest(unittest.TestCase):
    def test_secrets_generated_once_and_other_provider_keys_preserved(self):
        source = 'OPENAI_API_BASE_URLS=http://127.0.0.1:18888/v1;https://provider.invalid/v1\nOPENAI_API_KEYS=local-adapter;keep-provider-key\nWEBUI_SECRET_KEY=keep-webui\n'
        first = install.render_env(source)
        values = install.parse_env(first)
        self.assertEqual(values['OPENAI_API_KEYS'].split(';'), [values['RHIZOME_ADAPTER_TOKEN'], 'keep-provider-key'])
        self.assertNotEqual(values['RHIZOME_ADAPTER_TOKEN'], values['JUPYTER_TOKEN'])
        self.assertEqual(values['WEBUI_SECRET_KEY'], 'keep-webui')
        self.assertEqual(install.render_env(first), first)
        configured = install.parse_env(install.jupyter_settings(first))
        for prefix in ('CODE_EXECUTION', 'CODE_INTERPRETER'):
            self.assertEqual(configured[prefix + '_JUPYTER_AUTH'], 'token')
            self.assertEqual(configured[prefix + '_JUPYTER_AUTH_TOKEN'], values['JUPYTER_TOKEN'])

    def test_python_bounds_and_fallback(self):
        for version, expected in [([3, 10], False), ([3, 11], True), ([3, 12], True), ([3, 13], False), ([3, 14], False)]:
            with patch.object(install.subprocess, 'run', return_value=type('Result', (), {'stdout': json.dumps(version)})()):
                self.assertEqual(install.python_supported('fixture'), expected)
        with patch.object(install, 'python_supported', side_effect=lambda path: path == '/fixture/python3.12'), \
             patch.object(install.shutil, 'which', side_effect=lambda name: '/fixture/' + name):
            self.assertEqual(install.select_runtime_python(), '/fixture/python3.12')
            with self.assertRaises(install.InstallError):
                install.select_runtime_python('/fixture/python3.14')

    def test_incompatible_existing_venv_is_not_modified(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(install, 'STACK_ROOT', Path(temporary)):
            config = Path(temporary) / 'venvs/open-webui/pyvenv.cfg'
            config.parent.mkdir(parents=True)
            config.write_text('fixture')
            with patch.object(install, 'python_supported', return_value=False), self.assertRaises(install.InstallError):
                install.check_existing_venvs()
            self.assertEqual(config.read_text(), 'fixture')

    def test_jupyter_config_requires_token(self):
        from types import SimpleNamespace
        config = SimpleNamespace(IdentityProvider=SimpleNamespace(), ServerApp=SimpleNamespace())
        path = ROOT / 'containers/jupyter/jupyter_server_config.py'
        with patch.dict(os.environ, {'JUPYTER_TOKEN': ''}), self.assertRaises(RuntimeError):
            runpy.run_path(str(path), init_globals={'get_config': lambda: config})
        with patch.dict(os.environ, {'JUPYTER_TOKEN': 'synthetic-jupyter-secret'}):
            runpy.run_path(str(path), init_globals={'get_config': lambda: config})
        self.assertEqual(config.IdentityProvider.token, 'synthetic-jupyter-secret')
        self.assertFalse(config.ServerApp.allow_remote_access)
        self.assertFalse(config.ServerApp.allow_unauthenticated_access)

    def test_privacy_scan_detects_provider_tokens_and_numeric_handle(self):
        fixtures = [('B' + 'SA' + 'x' * 28, 'Brave'), ('h' + 'f_' + 'x' * 30, 'Hugging Face'),
                    ('AK' + 'IA' + 'A' * 16, 'AWS'), ('AS' + 'IA' + 'B' * 16, 'AWS'),
                    ('AI' + 'za' + 'x' * 35, 'Google'), ('xox' + 'b-' + 'x' * 30, 'Slack'),
                    ('ping' + 'uy' + '1234', 'username'), ('TELEGRAM_OWNER_ID=' + '1234567890', 'Telegram')]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for value, expected in fixtures:
                (root / 'fixture.txt').write_text(value)
                with self.subTest(kind=expected):
                    self.assertTrue(any(expected in finding for finding in privacy_audit.audit(root)))
            (root / 'fixture.txt').write_text('TELEGRAM_OWNER_ID=\nBRAVE_API_KEY=\nHF_TOKEN=\n')
            self.assertEqual(privacy_audit.audit(root), [])

    def test_privacy_scan_allows_only_pngs_in_documented_screenshot_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            screenshots = root / "docs/screenshots"
            screenshots.mkdir(parents=True)
            (screenshots / "accepted.png").write_bytes(
                privacy_audit.PNG_SIGNATURE + b"\x00\x00fixture"
            )
            self.assertEqual(privacy_audit.audit(root), [])
            (root / "unreviewed.png").write_bytes(
                privacy_audit.PNG_SIGNATURE + b"\x00\x00fixture"
            )
            self.assertTrue(any(
                "unexpected binary file" in item for item in privacy_audit.audit(root)
            ))


if __name__ == '__main__':
    unittest.main()
