from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rhizome_lifeboat.config import load_config
from rhizome_lifeboat.health import diagnose


class _Handler(BaseHTTPRequestHandler):
    mode = "healthy"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/healthz":
            self._json(200, {"ok": True, "status": "live"})
        elif self.path == "/startupz":
            if self.mode == "html-startup":
                body = b"<html>SPA fallback</html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json(200, {"started": True, "status": "started"})
        elif self.path == "/readyz":
            if self.mode == "database-failure":
                self._json(503, {"ready": False, "failing": ["sqlite integrity failure"]})
            else:
                self._json(200, {"ready": True, "failing": []})
        elif self.path == "/v1/models":
            if self.headers.get("Authorization") != "Bearer test-token":
                self._json(401, {"error": "unauthorised"})
            else:
                self._json(200, {"object": "list", "data": [{"id": "fixture"}]})
        else:
            self._json(404, {"error": "not found"})

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class HealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        token = self.root / "token"
        token.write_text("test-token\n", encoding="utf-8")
        fixture = self.root / "fixture"
        fixture.write_text("safe\n", encoding="utf-8")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config_path = self.root / "lifeboat.toml"
        self.config_path.write_text(
            f'''[store]
root = "{self.root / 'store'}"
mountpoint = "{self.root}"
minimum_free_bytes = 0

[application]
name = "fixture"
version = "1"
revision = "test"

[service]
status_command = ["/usr/bin/true"]

[health]
base_url = "http://127.0.0.1:{self.server.server_port}"
health_path = "/healthz"
startup_path = "/startupz"
ready_path = "/readyz"
functional_path = "/v1/models"
token_file = "{token}"
required_model_count = 1

[[files]]
name = "fixture"
source = "{fixture}"
restore = "{fixture}"
''',
            encoding="utf-8",
        )
        self.config = load_config(self.config_path)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def test_full_health_path(self) -> None:
        _Handler.mode = "healthy"
        result = diagnose(self.config)
        self.assertTrue(result.healthy)
        self.assertEqual(result.failure_class, "HEALTHY")
        self.assertEqual([check.name for check in result.checks], [
            "service", "liveness", "startup", "readiness", "functional"
        ])

    def test_html_200_is_not_startup_success(self) -> None:
        _Handler.mode = "html-startup"
        result = diagnose(self.config)
        self.assertFalse(result.healthy)
        self.assertEqual(result.failure_class, "STARTUP_INCOMPLETE")
        self.assertEqual(result.checks[-1].status_code, 200)
        self.assertIn("content type", result.checks[-1].detail)

    def test_database_admission_is_classified(self) -> None:
        _Handler.mode = "database-failure"
        result = diagnose(self.config)
        self.assertFalse(result.healthy)
        self.assertEqual(result.failure_class, "DATABASE_ADMISSION_FAILURE")


if __name__ == "__main__":
    unittest.main()
