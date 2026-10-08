#!/usr/bin/env python3
"""Fetch pinned creative model files with resume and mandatory SHA-256 checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comfy-root", type=Path, default=Path(os.environ.get(
        "COMFY_DIR", Path(os.environ.get("RHIZOME_STACK_ROOT", "~/.local/share/rhizome-stack")).expanduser() / "creative/ComfyUI")))
    args = parser.parse_args()
    manifest = json.loads((ROOT / "manifests/creative-models.json").read_text())
    for item in manifest["models"]:
        destination = args.comfy_root / "models" / item["destination"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file() and sha256(destination) == item["sha256"]:
            print(f"verified existing {destination}")
            continue
        if destination.exists():
            quarantine = destination.with_name(destination.name + f".invalid-{int(time.time())}")
            destination.replace(quarantine)
            print(f"quarantined invalid file: {quarantine}")
        part = destination.with_suffix(destination.suffix + ".part")
        encoded_path = "/".join(urllib.parse.quote(piece, safe="") for piece in item["source_path"].split("/"))
        url = f"https://huggingface.co/{item['repository']}/resolve/{item['revision']}/{encoded_path}?download=true"
        subprocess.run([
            "curl", "--fail", "--location", "--continue-at", "-", "--connect-timeout", "15",
            "--speed-limit", "1024", "--speed-time", "60", "--retry", "5", "--retry-all-errors",
            "--output", str(part), url,
        ], check=True)
        got = sha256(part)
        if got != item["sha256"]:
            raise SystemExit(f"checksum mismatch for {destination.name}: got {got}, expected {item['sha256']}")
        part.replace(destination)
        print(f"installed {item['component']}: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
