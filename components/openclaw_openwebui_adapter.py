#!/usr/bin/env python3
"""Loopback-only OpenAI adapter exposing OpenClaw's live non-Ollama models."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOST = "127.0.0.1"
PORT = int(os.environ.get("OPENCLAW_WEBUI_ADAPTER_PORT", "18888"))
GATEWAY = "http://127.0.0.1:18789"
MODEL_PREFIX = "openclaw/"
OPENCLAW_BIN = os.environ.get(
    "OPENCLAW_BIN",
    os.path.expanduser("~/.npm-global/bin/openclaw"),
)
_cache: tuple[float, list[dict]] = (0.0, [])
_cache_lock = threading.Lock()
CACHE_REFRESH_SECONDS = 10


def open_gateway(req: urllib.request.Request):
    """Open one logical OpenClaw run.

    The gateway owns provider retries. Replaying a completed gateway 429 here
    starts a new agent session and duplicates the gateway's own provider
    attempts, so the adapter must never add another retry layer.
    """
    return urllib.request.urlopen(req, timeout=900)


def gateway_token() -> str:
    with open(os.path.expanduser("~/.openclaw/openclaw.json"), encoding="utf-8") as handle:
        return json.load(handle)["gateway"]["auth"]["token"]


def refresh_models() -> list[dict]:
    global _cache
    result = subprocess.run(
        [OPENCLAW_BIN, "models", "list", "--json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload = json.loads(result.stdout[result.stdout.find("{"):])
    with open(os.path.expanduser("~/.openclaw/openclaw.json"), encoding="utf-8") as handle:
        config = json.load(handle)
    # The gateway honours the agent's model visibility allowlist.  The CLI
    # catalogue is broader, so advertising every "available" model would put
    # unusable entries in Open WebUI's picker.
    allowed = set(config.get("agents", {}).get("defaults", {}).get("models", {}))
    models = []
    for item in payload.get("models", []):
        key = item.get("key", "")
        if (
            not key
            or key not in allowed
            or key.startswith("ollama/")
            or not item.get("available", False)
        ):
            continue
        model_input = item.get("input", "")
        models.append({
            "id": MODEL_PREFIX + key,
            "object": "model",
            "created": 0,
            "owned_by": "openclaw",
            "name": f'{item.get("name", key)} · OpenClaw',
            "context_length": item.get("contextWindow"),
            "openclaw_model": key,
            "capabilities": {
                "vision": "image" in model_input,
            },
        })
    models.sort(key=lambda row: row["id"])
    with _cache_lock:
        _cache = (time.monotonic(), models)
    return models


def live_models() -> list[dict]:
    """Return the last known-good catalogue without blocking UI requests."""
    with _cache_lock:
        return list(_cache[1])


def refresh_models_forever() -> None:
    while True:
        time.sleep(CACHE_REFRESH_SECONDS)
        try:
            refresh_models()
        except Exception as exc:
            # Keep serving the previous catalogue. A transient CLI/gateway
            # fault must not make Open WebUI's model picker disappear.
            print(f"OpenClaw model refresh failed; keeping stale catalogue: {exc}", flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.client_address[0]} {fmt % args}", flush=True)

    def json_response(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_GET(self) -> None:
        try:
            if self.path.rstrip("/") == "/v1/models":
                self.json_response(200, {"object": "list", "data": live_models()})
                return
            if self.path.startswith("/v1/models/"):
                wanted = urllib.parse.unquote(self.path.removeprefix("/v1/models/"))
                model = next((m for m in live_models() if m["id"] == wanted), None)
                self.json_response(200 if model else 404, model or {"error": {"message": "model not found"}})
                return
            if self.path.rstrip("/") in ("", "/health"):
                self.json_response(200, {"ok": True, "models": len(live_models())})
                return
            self.json_response(404, {"error": {"message": "not found"}})
        except Exception as exc:
            self.json_response(502, {"error": {"message": str(exc)}})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/chat/completions":
            self.json_response(404, {"error": {"message": "not found"}})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 20_000_000:
                raise ValueError("invalid request size")
            body = self.rfile.read(size)
            payload = json.loads(body)
            selected = payload.get("model", "")
            if not selected.startswith(MODEL_PREFIX):
                raise ValueError("unknown OpenClaw model id")
            backend_model = selected[len(MODEL_PREFIX):]
            if backend_model.startswith("ollama/"):
                raise ValueError("Ollama models are intentionally excluded")
            payload["model"] = "openclaw/default"
            req = urllib.request.Request(
                GATEWAY + "/v1/chat/completions",
                data=json.dumps(payload).encode(),
                method="POST",
                headers={
                    "Authorization": f"Bearer {gateway_token()}",
                    "Content-Type": "application/json",
                    "x-openclaw-model": backend_model,
                    "x-openclaw-message-channel": "webchat",
                },
            )
            with open_gateway(req) as upstream:
                self.send_response(upstream.status)
                content_type = upstream.headers.get("Content-Type", "application/json")
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                while chunk := upstream.read(65536):
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as exc:
            self.json_response(exc.code, json.loads(exc.read() or b'{}'))
        except (BrokenPipeError, ConnectionResetError):
            # The browser/client cancelled the request. There is no downstream
            # connection left on which to report another error.
            return
        except Exception as exc:
            self.json_response(400, {"error": {"message": str(exc)}})


if __name__ == "__main__":
    # Populate once before accepting requests, then refresh out of band. The
    # old request-time refresh blocked Open WebUI's picker for several seconds
    # and concurrent requests could each start a separate CLI discovery.
    refresh_models()
    threading.Thread(target=refresh_models_forever, name="model-refresh", daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    server.serve_forever()
