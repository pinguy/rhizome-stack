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
    try:
        manifest = json.loads((root / "RELEASE-MANIFEST.json").read_text())
        allowlist = json.loads((root / "manifests/release-files.json").read_text())
        expected = manifest["files"]
        approved = allowlist["files"]
        if manifest.get("schema") != 1 or allowlist.get("schema") != 1:
            raise ValueError("unsupported manifest schema")
        if not isinstance(expected, dict) or not isinstance(approved, list):
            raise ValueError("invalid file list")
        for name, metadata in expected.items():
            relative = Path(name)
            if (not name or relative.is_absolute() or ".." in relative.parts
                    or relative.as_posix() != name or name == "RELEASE-MANIFEST.json"):
                raise ValueError(f"unsafe manifest path: {name}")
            if (not isinstance(metadata, dict) or not isinstance(metadata.get("sha256"), str)
                    or len(metadata["sha256"]) != 64 or type(metadata.get("bytes")) is not int
                    or metadata["bytes"] < 0):
                raise ValueError(f"invalid manifest entry: {name}")
        if len(approved) != len(set(approved)) or set(expected) != set(approved):
            raise ValueError("SHA-256 manifest does not match the release allow-list")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}))
        return 1
    symlinks = sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_symlink())
    actual = {
        str(path.relative_to(root)): path
        for path in root.rglob("*")
        if path.is_file()
        and path != root / "RELEASE-MANIFEST.json"
        and not path.is_symlink()
        and not any(part in IGNORED_PARTS for part in path.relative_to(root).parts)
    }
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    bad = sorted(name for name in set(expected) & set(actual) if sha(actual[name]) != expected[name]["sha256"])
    sizes = sorted(name for name in set(expected) & set(actual) if actual[name].stat().st_size != expected[name]["bytes"])
    if missing or extra or bad or sizes or symlinks:
        print(json.dumps({"valid": False, "missing": missing, "extra": extra,
                          "hash_mismatch": bad, "size_mismatch": sizes, "symlinks": symlinks}, indent=2))
        return 1
    print(json.dumps({"valid": True, "files": len(actual)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

