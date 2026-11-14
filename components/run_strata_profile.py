#!/usr/bin/env python3
"""Start one pinned source Strata profile through its lazy loopback API."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--peer-port", required=True, type=int)
    parser.add_argument("--stack-root", required=True, type=Path)
    args = parser.parse_args()
    source = args.stack_root / "src/Strata"
    candidates = []
    for path in source.glob("strata-*.json"):
        try:
            config = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        aliases = config.get("aliases") or []
        if args.model == config.get("model_name") or args.model in aliases or args.model in str(config.get("model_name", "")):
            candidates.append(path)
    if len(candidates) != 1:
        raise SystemExit(f"expected one Strata config for {args.model}, found {len(candidates)}; run the installer with --download-strata-models")
    python = source / ".venv/bin/python"
    if not python.is_file():
        raise SystemExit(f"Strata runtime is missing: {python}")
    command = [str(python), "-m", "serve.server", "--engine", "strata",
               "--config", str(candidates[0]), "--host", "127.0.0.1",
               "--port", str(args.port), "--api-key", "none", "--lazy",
               "--idle-unload", "600", "--min-free-vram-mib", "512"]
    os.chdir(source)
    os.execv(str(python), command)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
