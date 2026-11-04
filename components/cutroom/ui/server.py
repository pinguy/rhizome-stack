#!/usr/bin/env python3
"""Loopback-only unified Cutroom UI and streaming backend proxy."""

from __future__ import annotations

import argparse
import http.client
import json
import mimetypes
import os
import shutil
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "CutroomUI/0.2"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"{self.log_date_time_string()} {self.address_string()} {fmt % args}\n")

    def do_GET(self) -> None:
        if self.path in {"/ui-health", "/next-health"}:
            return self._json({"ok": True, "service": "cutroom-ui", "upstream": self.server.upstream})
        if self._is_proxy_path():
            return self._proxy()
        self._static(send_body=True)

    def do_HEAD(self) -> None:
        if self._is_proxy_path():
            return self._proxy(send_body=False)
        self._static(send_body=False)

    def do_POST(self) -> None:
        if not self.path.startswith("/api/"):
            return self.send_error(405, "POST is only available for the Cutroom API")
        self._proxy()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _is_proxy_path(self) -> bool:
        path = urllib.parse.urlsplit(self.path).path
        return path.startswith("/api/") or path.startswith("/media/")

    def _proxy(self, send_body: bool = True) -> None:
        connection = http.client.HTTPConnection(self.server.upstream_host, self.server.upstream_port, timeout=120)
        try:
            connection.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            connection.putheader("Host", f"{self.server.upstream_host}:{self.server.upstream_port}")
            for name, value in self.headers.items():
                if name.lower() not in HOP_BY_HOP and name.lower() != "host":
                    connection.putheader(name, value)
            connection.endheaders()

            remaining = int(self.headers.get("Content-Length") or 0)
            while remaining:
                block = self.rfile.read(min(1024 * 1024, remaining))
                if not block:
                    raise ConnectionError("request body ended early")
                connection.send(block)
                remaining -= len(block)

            response = connection.getresponse()
            self.send_response(response.status, response.reason)
            for name, value in response.getheaders():
                if name.lower() not in HOP_BY_HOP:
                    self.send_header(name, value)
            self.send_header("X-Cutroom-UI-Proxy", "1")
            self.end_headers()
            if send_body and self.command != "HEAD":
                while block := response.read(1024 * 1024):
                    self.wfile.write(block)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            if not self.wfile.closed:
                self.send_error(502, f"Cutroom backend unavailable: {exc}")
        finally:
            connection.close()

    def _static(self, send_body: bool) -> None:
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        relative = path.lstrip("/") or "index.html"
        candidate = (DIST / relative).resolve()
        try:
            candidate.relative_to(DIST.resolve())
        except ValueError:
            return self.send_error(403, "invalid path")
        if not candidate.is_file():
            candidate = DIST / "index.html"
        if not candidate.is_file():
            return self.send_error(503, "Cutroom UI is not built; run npm run build")
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(candidate.stat().st_size))
        self.send_header("Cache-Control", "no-cache" if candidate.name == "index.html" else "public, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'")
        self.end_headers()
        if send_body:
            with candidate.open("rb") as handle:
                shutil.copyfileobj(handle, self.wfile, length=1024 * 1024)

    def _json(self, value: object, status: int = 200) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], upstream_host: str, upstream_port: int):
        super().__init__(address, Handler)
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.upstream = f"http://{upstream_host}:{upstream_port}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("CUTROOM_UI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CUTROOM_UI_PORT", "8841")))
    parser.add_argument("--upstream-host", default=os.environ.get("CUTROOM_UPSTREAM_HOST", "127.0.0.1"))
    parser.add_argument("--upstream-port", type=int, default=int(os.environ.get("CUTROOM_UPSTREAM_PORT", "8840")))
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        parser.error("Cutroom UI may only bind to loopback")
    if not DIST.is_dir():
        parser.error(f"missing production build: {DIST}")
    server = Server((args.host, args.port), args.upstream_host, args.upstream_port)
    print(f"Cutroom UI listening on http://{args.host}:{args.port} -> {server.upstream}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
