#!/usr/bin/env python3
"""Verify the release allow-list and SHA-256 manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


IGNORED_PARTS = {"__pycache__", ".pytest_cache"}


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = json.loads((root / "RELEASE-MANIFEST.json").read_text())
    expected = manifest["files"]
    actual = {
        str(path.relative_to(root)): path
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "RELEASE-MANIFEST.json"
        and not any(part in IGNORED_PARTS for part in path.relative_to(root).parts)
    }
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    bad = sorted(name for name in set(expected) & set(actual) if sha(actual[name]) != expected[name]["sha256"])
    if missing or extra or bad:
        print(json.dumps({"valid": False, "missing": missing, "extra": extra, "hash_mismatch": bad}, indent=2))
        return 1
    print(json.dumps({"valid": True, "files": len(actual)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

