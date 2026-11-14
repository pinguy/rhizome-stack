#!/usr/bin/env python3
"""Loopback-only OpenAI adapter exposing OpenClaw's live non-Ollama models."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_http_security import LocalRequestHandler


HOST = "127.0.0.1"
PORT = int(os.environ.get("OPENCLAW_WEBUI_ADAPTER_PORT", os.environ.get("ADAPTER_PORT", "18888")))
GATEWAY = "http://127.0.0.1:" + str(int(os.environ.get("OPENCLAW_PORT", "18789")))
CONFIG = Path(os.environ.get("OPENCLAW_CONFIG_PATH", os.environ.get("OPENCLAW_CONFIG", "~/.openclaw/openclaw.json"))).expanduser()
MODEL_PREFIX = "openclaw/"
OPENWEBUI_AGENT_ID = os.environ.get("OPENCLAW_WEBUI_AGENT_ID", "openwebui")
OPENCLAW_BIN = os.environ.get(
    "OPENCLAW_BIN",
    os.path.expanduser("~/.npm-global/bin/openclaw"),
)
GATEWAY_TIMEOUT_SECONDS = int(
    os.environ.get("OPENCLAW_WEBUI_GATEWAY_TIMEOUT_SECONDS", "3700")
)
_cache: tuple[float, list[dict]] = (0.0, [])
_cache_lock = threading.Lock()
CACHE_REFRESH_SECONDS = 10
RAW_TOOL_CALL_OPEN = "<tool_call>"
RAW_TOOL_CALL_CLOSE = "</tool_call>"
MAX_RAW_TOOL_CALL_CHARS = 1_000_000


class LeadingToolMarkupFilter:
    """Remove only malformed tool markup leaked at the start of a reply.

    OpenClaw already diagnoses these blocks as unstructured tool calls and can
    retry for a visible answer.  A streamed client cannot retract the rejected
    first attempt, so the Open WebUI boundary withholds that exact leading
    protocol block while allowing ordinary prose to keep streaming.
    """

    def __init__(self) -> None:
        self.pending = ""
        self.suppressing = False
        self.removed = False
        self.passthrough = False

    def feed(self, text: str) -> str:
        if self.passthrough:
            return text
        self.pending += text
        while True:
            candidate = self.pending.lstrip()
            if not candidate:
                return ""
            if len(self.pending) > MAX_RAW_TOOL_CALL_CHARS:
                self.passthrough = True
                output, self.pending = self.pending, ""
                return output
            if self.suppressing:
                close_at = candidate.find(RAW_TOOL_CALL_CLOSE)
                if close_at < 0:
                    return ""
                self.pending = candidate[close_at + len(RAW_TOOL_CALL_CLOSE):]
                self.suppressing = False
                self.removed = True
                continue
            if RAW_TOOL_CALL_OPEN.startswith(candidate):
                return ""
            if candidate.startswith(RAW_TOOL_CALL_OPEN):
                self.suppressing = True
                continue
            output = self.pending.lstrip("\r\n") if self.removed else self.pending
            self.pending = ""
            self.passthrough = True
            return output

    def finish(self) -> str:
        if self.passthrough:
            return ""
        output, self.pending = self.pending, ""
        self.passthrough = True
        if self.removed and not output.strip():
            return ""
        return output


def _sanitize_openai_payload(payload: object, markup: LeadingToolMarkupFilter) -> bool:
    """Sanitize Chat Completions content in place; return whether it changed."""
    if not isinstance(payload, dict) or not isinstance(payload.get("choices"), list):
        return False
    changed = False
    for choice in payload["choices"]:
        if not isinstance(choice, dict):
            continue
        container = choice.get("delta")
        if not isinstance(container, dict):
            container = choice.get("message")
        if not isinstance(container, dict) or not isinstance(container.get("content"), str):
            continue
        original = container["content"]
        container["content"] = markup.feed(original)
        changed = changed or container["content"] != original
    return changed


def _pending_sse_event(text: str) -> bytes:
    payload = {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}
    return b"data: " + json.dumps(payload, separators=(",", ":")).encode() + b"\n\n"


def _sanitize_sse_line(line: bytes, markup: LeadingToolMarkupFilter) -> list[bytes]:
    ending = b""
    content = line
    if content.endswith(b"\r\n"):
        content, ending = content[:-2], b"\r\n"
    elif content.endswith(b"\n"):
        content, ending = content[:-1], b"\n"
    if not content.startswith(b"data:"):
        return [line]
    raw = content[5:].lstrip()
    if raw == b"[DONE]":
        pending = markup.finish()
        return ([_pending_sse_event(pending)] if pending else []) + [line]
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        return [line]
    if not _sanitize_openai_payload(payload, markup):
        return [line]
    encoded = b"data: " + json.dumps(payload, separators=(",", ":")).encode()
    return [encoded + ending]


def sanitized_sse_chunks(upstream):
    """Yield complete SSE lines while filtering a fragmented leading tool block."""
    markup = LeadingToolMarkupFilter()
    buffered = b""
    while chunk := upstream.read1(65536):
        buffered += chunk
        while b"\n" in buffered:
            line, buffered = buffered.split(b"\n", 1)
            for output in _sanitize_sse_line(line + b"\n", markup):
                yield output
    if buffered:
        for output in _sanitize_sse_line(buffered, markup):
            yield output
    pending = markup.finish()
    if pending:
        yield _pending_sse_event(pending)


def sanitize_json_response(raw: bytes) -> bytes:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        return raw
    markup = LeadingToolMarkupFilter()
    changed = _sanitize_openai_payload(payload, markup)
    pending = markup.finish()
    if pending:
        # A complete JSON response contains the whole message, so pending text
        # means it was not a complete leading protocol block and must survive.
        for choice in payload.get("choices", []):
            container = choice.get("message") if isinstance(choice, dict) else None
            if isinstance(container, dict) and isinstance(container.get("content"), str):
                container["content"] += pending
                changed = True
                break
    return json.dumps(payload).encode() if changed else raw


def open_gateway(req: urllib.request.Request):
    """Open one logical OpenClaw run.

    The gateway owns provider retries. Replaying a completed gateway 429 here
    starts a new agent session and duplicates the gateway's own provider
    attempts, so the adapter must never add another retry layer.
    """
    return urllib.request.urlopen(req, timeout=GATEWAY_TIMEOUT_SECONDS)


def gateway_token() -> str:
    with CONFIG.open(encoding="utf-8") as handle:
        return json.load(handle)["gateway"]["auth"]["token"]


def refresh_models() -> list[dict]:
    global _cache
    result = subprocess.run(
        [OPENCLAW_BIN, "models", "list", "--json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "OPENCLAW_CONFIG_PATH": str(CONFIG)},
    )
    payload = json.loads(result.stdout[result.stdout.find("{"):])
    with CONFIG.open(encoding="utf-8") as handle:
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


class Handler(LocalRequestHandler):
    allow_browser_origin = False
    require_adapter_auth = True
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
        # Every POST is a single logical run; close even on a rejected body so
        # unread bytes cannot be interpreted as another HTTP request.
        self.close_connection = True
        if self.path.rstrip("/") != "/v1/chat/completions":
            self.json_response(404, {"error": {"message": "not found"}})
            return
        response_started = False
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("transfer encoding is not supported; send Content-Length")
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 20_000_000:
                raise ValueError("invalid request size")
            body = self.rfile.read(size)
            if len(body) != size:
                raise ValueError("incomplete request body")
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            selected = payload.get("model", "")
            if not isinstance(selected, str) or not selected.startswith(MODEL_PREFIX):
                raise ValueError("unknown OpenClaw model id")
            backend_model = selected[len(MODEL_PREFIX):]
            if not backend_model or any(ord(char) < 32 or ord(char) == 127 for char in backend_model):
                raise ValueError("invalid OpenClaw model id")
            if backend_model.startswith("ollama/"):
                raise ValueError("Ollama models are intentionally excluded")
        except (ValueError, TypeError) as exc:
            self.json_response(400, {"error": {"message": str(exc)}})
            return
        try:
            payload["model"] = "openclaw/default"
            req = urllib.request.Request(
                GATEWAY + "/v1/chat/completions",
                data=json.dumps(payload).encode(),
                method="POST",
                headers={
                    "Authorization": f"Bearer {gateway_token()}",
                    "Content-Type": "application/json",
                    "x-openclaw-agent-id": OPENWEBUI_AGENT_ID,
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
                response_started = True
                if "text/event-stream" in content_type.lower():
                    for chunk in sanitized_sse_chunks(upstream):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                else:
                    # Non-streaming Chat Completions are small enough to parse
                    # once, and need the same malformed-prefix protection.
                    self.wfile.write(sanitize_json_response(upstream.read()))
                    self.wfile.flush()
        except urllib.error.HTTPError as exc:
            with exc:
                try:
                    error = json.loads(exc.read(65536))
                except (ValueError, OSError):
                    error = None
            if not isinstance(error, dict):
                error = {"error": {"message": f"OpenClaw gateway returned HTTP {exc.code}"}}
            self.json_response(exc.code, error)
        except (BrokenPipeError, ConnectionResetError):
            # The browser/client cancelled the request. There is no downstream
            # connection left on which to report another error.
            return
        except Exception as exc:
            if not response_started:
                self.json_response(502, {"error": {"message": str(exc)}})
            # Once streaming begins, another HTTP response would corrupt it.


if __name__ == "__main__":
    # Populate once before accepting requests, then refresh out of band. The
    # old request-time refresh blocked Open WebUI's picker for several seconds
    # and concurrent requests could each start a separate CLI discovery.
    refresh_models()
    threading.Thread(target=refresh_models_forever, name="model-refresh", daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    server.serve_forever()
