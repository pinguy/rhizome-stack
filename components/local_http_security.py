"""Shared browser boundary for loopback services; not a local-user sandbox."""
from __future__ import annotations

import hmac
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit


def adapter_headers() -> dict[str, str]:
    token = os.environ.get("RHIZOME_ADAPTER_TOKEN", "")
    if not token or token == "local-adapter":
        raise RuntimeError("RHIZOME_ADAPTER_TOKEN must be configured")
    return {"Authorization": "Bearer " + token, "Content-Type": "application/json"}


def local_authority(value: str):
    # Deliberately accept only explicit loopback names, not DNS-resolved names.
    if not value or any(c.isspace() for c in value) or any(c in value for c in "/?#@,\\"):
        return None
    try:
        parsed = urlsplit("http://" + value)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return None
        return parsed.hostname, parsed.port or 80
    except ValueError:
        return None


class LocalRequestHandler(BaseHTTPRequestHandler):
    """Reject rebinding hosts and cross-site requests before dispatch/body reads."""
    allow_browser_origin = True
    require_adapter_auth = False
    binary_upload_paths: frozenset[str] = frozenset()

    def parse_request(self):
        if not super().parse_request():
            return False
        hosts = self.headers.get_all("Host", [])
        authority = local_authority(hosts[0]) if len(hosts) == 1 else None
        if authority is None:
            return self.reject(403, "Loopback Host required")
        origins = self.headers.get_all("Origin", [])
        if origins:
            # Exact same origin only. No suffix matching, null origins or CORS.
            if (not self.allow_browser_origin or len(origins) != 1
                    or origins[0] != "http://" + hosts[0]):
                return self.reject(403, "Origin is not allowed")
        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            return self.reject(403, "Cross-site requests are not allowed")
        path = urlsplit(self.path).path
        if self.require_adapter_auth and path not in {"/health", "/health/", "/"}:
            token = os.environ.get("RHIZOME_ADAPTER_TOKEN", "")
            if not token or token == "local-adapter":
                return self.reject(503, "Adapter authentication is not configured")
            supplied = self.headers.get_all("Authorization", [])
            expected = ("Bearer " + token).encode()
            if len(supplied) != 1 or not hmac.compare_digest(supplied[0].encode(), expected):
                return self.reject(401, "Valid adapter credentials required")
        if self.command == "POST":
            types = self.headers.get_all("Content-Type", [])
            media_type = types[0].split(";", 1)[0].strip().lower() if len(types) == 1 else ""
            allowed = {"application/json"}
            if path in self.binary_upload_paths:
                allowed = {"application/octet-stream", "image/png", "image/jpeg", "image/webp"}
            if media_type not in allowed:
                return self.reject(415, "Unsupported Content-Type")
        return True

    def reject(self, status, message):
        self.close_connection = True
        self.send_error(status, message)
        return False
