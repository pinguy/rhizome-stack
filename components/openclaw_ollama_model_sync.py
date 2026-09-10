#!/usr/bin/env python3
"""Keep OpenClaw's model allowlist aligned with the local Ollama catalogue."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


CONFIG = Path.home() / ".openclaw" / "openclaw.json"
OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"
POLL_SECONDS = 10


def ollama_models() -> set[str]:
    with urllib.request.urlopen(OLLAMA_TAGS, timeout=4) as response:
        payload = json.load(response)
    discovered: set[str] = set()
    for row in payload.get("models", []):
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            continue
        name = row["name"]
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/show",
            data=json.dumps({"model": name}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            details = json.load(response)
        # OpenClaw is an agent surface. Plain completion-only models belong in
        # Open WebUI, not here, because they cannot reliably run agent tools.
        if "tools" in details.get("capabilities", []):
            discovered.add(f"ollama/{name}")
    return discovered


def sync_once() -> bool:
    wanted = ollama_models()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    current = config.get("agents", {}).get("defaults", {}).get("models", {})
    if not isinstance(current, dict):
        raise RuntimeError("agents.defaults.models is not an object")

    updated = {key: value for key, value in current.items() if not key.startswith("ollama/")}
    updated.update({key: {} for key in sorted(wanted)})
    if updated == current:
        return False

    # Use OpenClaw's validator and atomic config writer rather than editing its
    # live JSON ourselves. The gateway watches this file and hot-applies it.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        json.dump(updated, handle, separators=(",", ":"))
        value_path = handle.name
    try:
        value = Path(value_path).read_text(encoding="utf-8")
        subprocess.run(
            [
                "openclaw", "config", "set", "agents.defaults.models",
                value, "--strict-json", "--replace",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    finally:
        os.unlink(value_path)

    print(f"synced {len(wanted)} Ollama models", flush=True)
    return True


def main() -> int:
    oneshot = "--once" in sys.argv[1:]
    while True:
        try:
            sync_once()
        except Exception as exc:
            print(f"sync failed: {exc}", file=sys.stderr, flush=True)
        if oneshot:
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
