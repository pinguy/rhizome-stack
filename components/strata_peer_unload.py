#!/usr/bin/env python3
"""Unload one loopback Strata peer before another profile takes the GPUs."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def request(method: str, url: str, body=None, timeout: float = 8):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("http://127.0.0.1:"):
        print("usage: strata-peer-unload.py http://127.0.0.1:PORT", file=sys.stderr)
        return 2
    base = sys.argv[1].rstrip("/")
    try:
        state = request("GET", base + "/health")
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError):
            return 0
        raise
    if not isinstance(state, dict) or state.get("service") != "strata" or not isinstance(state.get("loaded"), bool):
        raise RuntimeError(f"{base} returned an invalid Strata health response")
    if not state["loaded"]:
        return 0
    result = request("POST", base + "/v1/unload?" + urllib.parse.urlencode({"wait": 120}), {}, timeout=135)
    if not isinstance(result, dict) or result.get("status") not in ("unloaded", "already unloaded"):
        raise RuntimeError(f"{base} did not acknowledge unloading")
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if request("GET", base + "/health").get("loaded") is False:
            return 0
        time.sleep(0.5)
    raise RuntimeError(f"{base} still reports a loaded model after unloading")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"strata peer unload failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
