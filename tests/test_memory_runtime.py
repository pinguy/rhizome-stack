"""Bounded memory child-process behaviour without FAISS or model weights."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'components/memory-rhizome/runtime_client.js'


class MemoryRuntimeTest(unittest.TestCase):
    def test_missing_hung_partial_and_oversized_workers_degrade_cleanly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            helpers = {
                'hung.py': 'import time\nfor line in __import__("sys").stdin:\n time.sleep(30)\n',
                'partial.py': 'import sys,time\nfor line in sys.stdin:\n print("{\\\"ok\\\":", end="", flush=True); time.sleep(30)\n',
                'oversized.py': 'import sys,time\nfor line in sys.stdin:\n print("x"*4096, end="", flush=True); time.sleep(30)\n',
                'slow_valid.py': 'import json,sys,time\nfor line in sys.stdin:\n time.sleep(0.25); print(json.dumps({"ok": True}), flush=True)\n',
                'valid.py': 'import json,sys\nfor line in sys.stdin:\n print(json.dumps({"ok": True}), flush=True)\n',
                'failure.py': 'import json,sys\nfor line in sys.stdin:\n print(json.dumps({"ok": False, "error": "index missing"}), flush=True)\n',
                'malformed.py': 'import sys\nfor line in sys.stdin:\n print("this is not json", flush=True)\n',
            }
            for name, content in helpers.items():
                (root / name).write_text(content)
            script = textwrap.dedent(f'''\
                import {{ RhizomeServer }} from {json.dumps(CLIENT.as_uri())};
                const root = process.argv[1];
                const base = {{
                  pythonPath: {json.dumps(sys.executable)}, baseDir: root, indexPath: root + "/index",
                  textsPath: root + "/texts", metadataPath: root + "/meta",
                  embedModel: "fixture", device: "cpu", requestTimeoutMs: 120,
                  maxResponseBytes: 1024,
                }};
                const outcomes = {{}};
                async function run(label, name, pythonPath = base.pythonPath, requestTimeoutMs = 1000) {{
                  const server = new RhizomeServer({{...base, pythonPath, requestTimeoutMs}}, root + "/" + name);
                  outcomes[label] = await server.request({{type:"status"}});
                  outcomes[label + ":health"] = server.health();
                  server.stop();
                }}
                await run("valid", "valid.py");
                await run("slow_valid", "slow_valid.py");
                await run("failure", "failure.py");
                await run("malformed", "malformed.py");
                await run("hung", "hung.py", base.pythonPath, 120);
                await run("partial", "partial.py", base.pythonPath, 120);
                await run("oversized", "oversized.py");
                await run("missing", "valid.py", root + "/missing-python");
                console.log(JSON.stringify(outcomes));
            ''')
            result = subprocess.run(['node', '--input-type=module', '-e', script, str(root)],
                                    text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            outcomes = json.loads(result.stdout)
            self.assertTrue(outcomes['valid']['ok'])
            self.assertTrue(outcomes['valid:health']['available'])
            self.assertTrue(outcomes['slow_valid']['ok'])
            self.assertTrue(outcomes['slow_valid:health']['available'])
            self.assertFalse(outcomes['failure']['ok'])
            self.assertFalse(outcomes['failure:health']['available'])
            self.assertEqual(outcomes['failure:health']['error'], 'index missing')
            self.assertFalse(outcomes['malformed:health']['available'])
            self.assertIn('bad json', outcomes['malformed:health']['error'])
            self.assertTrue(outcomes['hung']['unavailable'])
            self.assertIn('timed out', outcomes['hung']['error'])
            self.assertTrue(outcomes['partial']['unavailable'])
            self.assertIn('timed out', outcomes['partial']['error'])
            self.assertTrue(outcomes['oversized']['unavailable'])
            self.assertIn('exceeded', outcomes['oversized']['error'])
            self.assertTrue(outcomes['missing']['unavailable'])
            self.assertIn('error', outcomes['missing']['error'])

    def test_workspace_fallback_never_derives_from_archive_parent(self):
        source = (ROOT / 'components/memory-rhizome/index.ts').read_text()
        self.assertNotIn('path.dirname(cfg.baseDir)', source)
        self.assertGreaterEqual(source.count('cfg.workspaceDir'), 4)
        self.assertIn('rootConfig?.agents?.defaults?.workspace', source)


if __name__ == '__main__':
    unittest.main()
