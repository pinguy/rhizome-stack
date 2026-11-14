"""Release 19 Strata, gpu-unlock and COMET packaging boundaries."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import install
import privacy_audit


class Release19Integrations(unittest.TestCase):
    def test_strata_provider_render_is_loopback_only_and_secret_free(self):
        env = {"OPENCLAW_GATEWAY_TOKEN": "synthetic", "DEFAULT_OLLAMA_MODEL": "fixture"}
        config = json.loads(install.render_openclaw(env, with_strata=True))
        providers = config["models"]["providers"]
        self.assertEqual(providers["strata"]["baseUrl"], "http://127.0.0.1:47831/v1")
        self.assertEqual(providers["strata-s"]["baseUrl"], "http://127.0.0.1:47832/v1")
        for provider in (providers["strata"], providers["strata-s"]):
            self.assertEqual(provider["timeoutSeconds"], 3500)
            self.assertEqual(provider["models"][0]["contextTokens"], 114688)
            self.assertNotIn("/home/", json.dumps(provider))
        main = next(agent for agent in config["agents"]["list"]
                    if agent["id"] == "main")
        self.assertEqual(main["model"], {
            "primary": "ollama/fixture",
            "fallbacks": ["strata/gyro-gyro-m"],
        })
        self.assertEqual(config["tools"]["sessions"]["visibility"], "agent")

    def test_non_strata_render_has_session_recovery_without_missing_fallback(self):
        env = {"OPENCLAW_GATEWAY_TOKEN": "synthetic", "DEFAULT_OLLAMA_MODEL": "fixture"}
        config = json.loads(install.render_openclaw(env))
        main = next(agent for agent in config["agents"]["list"]
                    if agent["id"] == "main")
        self.assertNotIn("model", main)
        self.assertEqual(config["tools"]["sessions"]["visibility"], "agent")

    def test_gpu_unlock_dependencies_are_explicit(self):
        self.assertIn("dkms", install.package_command(
            "arch", voice=False, jupyter=False, creative=False, gpu_unlock=True))
        self.assertIn("dkms", install.package_command(
            "debian", voice=False, jupyter=False, creative=False, gpu_unlock=True))

    def test_comet_bridge_default_is_stack_relative(self):
        module_path = ROOT / "components/comet_atomic/comet_weightspace.py"
        spec = importlib.util.spec_from_file_location("portable_comet", module_path)
        module = importlib.util.module_from_spec(spec)
        with tempfile.TemporaryDirectory() as temporary, \
             patch.dict("os.environ", {"RHIZOME_STACK_ROOT": temporary}, clear=False):
            spec.loader.exec_module(module)
            self.assertEqual(module.DEFAULT_MODEL_DIR,
                             Path(temporary) / "models/comet-atomic/comet-bart-ai2")

    def test_pins_match_accepted_reference_machine_revisions(self):
        versions = json.loads((ROOT / "manifests/versions.json").read_text())
        self.assertEqual(versions["strata_git"], "d2f096475817d4666c364c820b0ca830f751cfc5")
        self.assertEqual(versions["gpu_unlock_git"], "0532473b4b105ed216948ed9c5aaeab0fa5c734f")
        self.assertEqual(versions["comet_atomic_git"], "33129ff9fbab126a98ce03f10017c405a553aeab")
        self.assertEqual(versions["weightspace"], "0.3.0")

    def test_no_reference_machine_paths_in_new_runtime_files(self):
        paths = [
            ROOT / "components/comet_atomic/comet_weightspace.py",
            ROOT / "components/run_strata_profile.py",
            ROOT / "components/strata_peer_unload.py",
            ROOT / "tools/fetch_comet_model.py",
            ROOT / "tools/configure_grub_gpu_unlock.py",
            ROOT / "systemd/strata-api.service",
            ROOT / "systemd/strata-api-s.service",
        ]
        text = "\n".join(path.read_text() for path in paths)
        self.assertIsNone(privacy_audit.PATTERNS["reference home path"].search(text))
        self.assertNotIn("/500GB", text)


if __name__ == "__main__":
    unittest.main()
