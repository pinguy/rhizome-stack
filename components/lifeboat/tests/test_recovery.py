from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import contextlib
import dataclasses
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rhizome_lifeboat.config import load_config
from rhizome_lifeboat.recovery import recover_automatically, undo_recovery
from rhizome_lifeboat.window import load_window, prepare_change


class _RecoveryHandler(BaseHTTPRequestHandler):
    database: Path
    config_file: Path
    transient_ready_failures = 0

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._json(200, {"ok": True, "status": "live"})
        elif self.path == "/startupz":
            self._json(200, {"started": True, "status": "started"})
        elif self.path == "/readyz":
            failures: list[str] = []
            if type(self).transient_ready_failures:
                type(self).transient_ready_failures -= 1
                failures.append("temporary startup warmup")
            try:
                json.loads(self.config_file.read_text(encoding="utf-8"))
            except Exception as error:
                failures.append(f"config admission failure: {error}")
            try:
                with contextlib.closing(
                    sqlite3.connect(f"file:{self.database}?mode=ro", uri=True)
                ) as connection:
                    quick = connection.execute("PRAGMA quick_check").fetchone()[0]
                if quick != "ok":
                    failures.append(f"sqlite integrity failure: {quick}")
            except Exception as error:
                failures.append(f"sqlite admission failure: {error}")
            self._json(200 if not failures else 503, {"ready": not failures, "failing": failures})
        elif self.path == "/v1/models":
            if self.headers.get("Authorization") == "Bearer test-token":
                self._json(200, {"object": "list", "data": [{"id": "fixture-model"}]})
            else:
                self._json(401, {"error": "unauthorised"})
        else:
            self._json(404, {"error": "not found"})

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.live = self.root / "live"
        self.store = self.root / "store"
        self.live.mkdir()
        self.config_file = self.live / "openclaw.json"
        self.config_file.write_text('{"gateway":{"port":18789}}\n', encoding="utf-8")
        self.database = self.live / "state.sqlite"
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.execute("PRAGMA user_version=7")
            connection.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO events(value) VALUES ('known-good')")
            connection.commit()
        self.plugin_tree = self.live / "plugins"
        self.plugin_tree.mkdir()
        (self.plugin_tree / "runtime.js").write_text("known-good plugin\n", encoding="utf-8")
        self.runtime_link = self.live / "runtime-link"
        self.runtime_link.symlink_to(self.plugin_tree)

        self.token = self.root / "token"
        self.token.write_text("test-token\n", encoding="utf-8")
        self.active = self.root / "service.active"
        self.active.touch()
        self.control = self.root / "control.py"
        self.control.write_text(
            '''from pathlib import Path
import sys
action, name = sys.argv[1], Path(sys.argv[2])
if action == "status":
    raise SystemExit(0 if name.exists() else 3)
if action == "start":
    name.touch()
elif action == "stop":
    name.unlink(missing_ok=True)
elif action == "journal":
    print("fixture gateway: database admission failed")
else:
    raise SystemExit(2)
''',
            encoding="utf-8",
        )

        _RecoveryHandler.database = self.database
        _RecoveryHandler.config_file = self.config_file
        _RecoveryHandler.transient_ready_failures = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _RecoveryHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        python = sys.executable
        self.config_path = self.root / "lifeboat.toml"
        self.config_path.write_text(
            f'''[store]
root = "{self.store}"
mountpoint = "{self.root}"
minimum_free_bytes = 0

[application]
name = "OpenClaw-fixture"
version = "1.0"
revision = "test"

[service]
stop_command = ["{python}", "{self.control}", "stop", "{self.active}"]
start_command = ["{python}", "{self.control}", "start", "{self.active}"]
status_command = ["{python}", "{self.control}", "status", "{self.active}"]
journal_command = ["{python}", "{self.control}", "journal", "{self.active}"]
command_timeout_seconds = 5

[health]
base_url = "http://127.0.0.1:{self.server.server_port}"
health_path = "/healthz"
startup_path = "/startupz"
ready_path = "/readyz"
functional_path = "/v1/models"
token_file = "{self.token}"
timeout_seconds = 1
startup_grace_seconds = 3
required_model_count = 1

[policy]
change_window_seconds = 300
maximum_automatic_rollbacks = 1
failure_confirmation_attempts = 1
failure_confirmation_interval_seconds = 0
automatic_failure_classes = ["DATABASE_ADMISSION_FAILURE", "CONFIG_ADMISSION_FAILURE"]

[[files]]
name = "gateway-config"
source = "{self.config_file}"
restore = "{self.config_file}"

[[databases]]
name = "state"
source = "{self.database}"
restore = "{self.database}"
expected_user_version = 7

[[trees]]
name = "plugins"
source = "{self.plugin_tree}"
restore = "{self.plugin_tree}"

[[symlinks]]
name = "runtime-link"
source = "{self.runtime_link}"
restore = "{self.runtime_link}"
''',
            encoding="utf-8",
        )
        self.config = load_config(self.config_path)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def _corrupt_database(self) -> None:
        self.database.write_bytes(b"deliberately broken sqlite database\n")

    def test_complete_disposable_database_recovery(self) -> None:
        prepared = prepare_change(self.config, "disposable schema change")
        self._corrupt_database()
        (self.plugin_tree / "runtime.js").write_text("broken plugin\n", encoding="utf-8")
        self.runtime_link.unlink()
        self.runtime_link.symlink_to(self.live / "wrong-target")

        result = recover_automatically(self.config)
        self.assertEqual(result["outcome"], "recovered")
        self.assertEqual(result["checkpoint_id"], prepared["checkpoint"]["checkpoint_id"])
        self.assertTrue(self.active.exists())
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            value = connection.execute("SELECT value FROM events").fetchone()[0]
            quick = connection.execute("PRAGMA quick_check").fetchone()[0]
        self.assertEqual(value, "known-good")
        self.assertEqual(quick, "ok")
        self.assertEqual(
            (self.plugin_tree / "runtime.js").read_text(encoding="utf-8"),
            "known-good plugin\n",
        )
        self.assertEqual(self.runtime_link.readlink(), self.plugin_tree)
        self.assertEqual(load_window(self.config)["automatic_rollbacks_attempted"], 1)
        self.assertEqual(load_window(self.config)["status"], "closed")
        failed_state = Path(result["quarantine"]) / "failed-state" / "state" / "main"
        self.assertEqual(failed_state.read_bytes(), b"deliberately broken sqlite database\n")
        self.assertTrue(Path(result["receipt_path"]).is_file())

    def test_failure_outside_change_window_does_not_restore(self) -> None:
        original = self.database.read_bytes()
        self._corrupt_database()
        result = recover_automatically(self.config)
        self.assertEqual(result["status"], "operator-intervention-required")
        self.assertIn("no recorded change window", result["reason"])
        self.assertNotEqual(self.database.read_bytes(), original)

    def test_process_crash_gets_one_ordinary_restart_without_rollback(self) -> None:
        self.active.unlink()
        result = recover_automatically(self.config)
        self.assertEqual(result["outcome"], "restarted")
        self.assertTrue(self.active.exists())
        self.assertIsNone(load_window(self.config))

    def test_broken_gateway_configuration_is_restored(self) -> None:
        prepare_change(self.config, "configuration change drill")
        self.config_file.write_text("{broken-json\n", encoding="utf-8")
        result = recover_automatically(self.config)
        self.assertEqual(result["outcome"], "recovered")
        self.assertEqual(
            json.loads(self.config_file.read_text(encoding="utf-8")),
            {"gateway": {"port": 18789}},
        )

    def test_interrupted_restore_preserves_evidence_and_exhausts_attempt(self) -> None:
        prepare_change(self.config, "interrupted recovery drill")
        self._corrupt_database()
        result = recover_automatically(self.config, fail_after_restores=1)
        self.assertEqual(result["outcome"], "operator-intervention-required")
        self.assertIn("deliberate interrupted-restore", result["error"])
        self.assertTrue((Path(result["quarantine"]) / "failed-state.json").is_file())
        state = load_window(self.config)
        self.assertEqual(state["automatic_rollbacks_attempted"], 1)
        second = recover_automatically(self.config)
        self.assertEqual(second["status"], "operator-intervention-required")
        self.assertIn("limit exhausted", second["reason"])

    def test_transient_readiness_failure_does_not_rollback(self) -> None:
        prepare_change(self.config, "transient readiness drill")
        _RecoveryHandler.transient_ready_failures = 1
        config = dataclasses.replace(
            self.config,
            policy=dataclasses.replace(
                self.config.policy,
                failure_confirmation_attempts=2,
                failure_confirmation_interval_seconds=0,
            ),
        )
        result = recover_automatically(config)
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(load_window(config)["automatic_rollbacks_attempted"], 0)

    def test_corrupted_selected_checkpoint_is_rejected_without_restore(self) -> None:
        prepared = prepare_change(self.config, "corrupted candidate drill")
        checkpoint = self.store / "checkpoints" / prepared["checkpoint"]["checkpoint_id"]
        manifest = json.loads((checkpoint / "manifest.json").read_text(encoding="utf-8"))
        database_item = next(item for item in manifest["items"] if item["kind"] == "sqlite")
        artifact = checkpoint / database_item["artifact"]
        with artifact.open("r+b") as handle:
            handle.seek(128)
            handle.write(b"corrupt-checkpoint")
        self._corrupt_database()
        result = recover_automatically(self.config)
        self.assertEqual(result["outcome"], "operator-intervention-required")
        self.assertIn("checkpoint rejected before service stop", result["error"])
        self.assertEqual(self.database.read_bytes(), b"deliberately broken sqlite database\n")
        self.assertEqual(load_window(self.config)["outcome"], "checkpoint-rejected")

    def test_successful_recovery_can_be_undone_from_quarantine(self) -> None:
        prepare_change(self.config, "undo drill")
        self._corrupt_database()
        recovered = recover_automatically(self.config)
        self.assertEqual(recovered["outcome"], "recovered")
        undone = undo_recovery(self.config, recovered["incident_id"])
        self.assertEqual(undone["outcome"], "undone")
        self.assertEqual(self.database.read_bytes(), b"deliberately broken sqlite database\n")
        self.assertEqual(undone["post_undo_health"]["failure_class"], "DATABASE_ADMISSION_FAILURE")


if __name__ == "__main__":
    unittest.main()
