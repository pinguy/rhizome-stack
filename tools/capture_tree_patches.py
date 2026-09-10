#!/usr/bin/env python3
"""Capture known text-file drift between two otherwise matching trees."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--modified", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite {args.output}")
    args.output.mkdir(parents=True)
    manifest = {"schema": 1, "files": []}
    for relative in args.paths:
        clean = (args.clean / relative).read_bytes()
        modified = (args.modified / relative).read_bytes()
        if clean == modified:
            raise SystemExit(f"listed file is unchanged: {relative}")
        clean_text = clean.decode("utf-8").splitlines(keepends=True)
        modified_text = modified.decode("utf-8").splitlines(keepends=True)
        name = relative.replace("/", "__") + ".patch"
        diff = difflib.unified_diff(clean_text, modified_text, fromfile="a/" + relative, tofile="b/" + relative)
        (args.output / name).write_text("".join(diff))
        manifest["files"].append({
            "path": relative,
            "action": "modify",
            "clean_sha256": sha(clean),
            "patched_sha256": sha(modified),
            "payload": name,
        })
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"captured {len(manifest['files'])} changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

