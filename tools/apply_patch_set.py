#!/usr/bin/env python3
"""Apply a captured package patch set only to its exact clean upstream files."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("patch_set", type=Path)
    parser.add_argument("installed_root", type=Path)
    args = parser.parse_args()
    patch_set = args.patch_set.resolve()
    root = args.installed_root.resolve()
    manifest = json.loads((patch_set / "manifest.json").read_text())
    already_applied = True
    for item in manifest["files"]:
        path = root / item["path"]
        wanted = item["patched_sha256"]
        if wanted is None:
            if path.exists():
                already_applied = False
        elif not path.is_file() or sha(path) != wanted:
            already_applied = False
    if already_applied:
        print("patch set already applied and verified")
        return 0
    for item in manifest["files"]:
        path = root / item["path"]
        if not path.is_file() or sha(path) != item["clean_sha256"]:
            raise SystemExit(f"base hash mismatch; refusing patch: {item['path']}")
    backup = root / ".rhizome-stack-patch-backup"
    if backup.exists():
        raise SystemExit(f"backup already exists; reconcile before retrying: {backup}")
    backup.mkdir()
    for item in manifest["files"]:
        source = root / item["path"]
        target = backup / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for item in manifest["files"]:
        path = root / item["path"]
        if item["action"] == "delete":
            path.unlink()
        elif item["action"] == "replace":
            replacement = patch_set / item["payload"]
            temporary = path.with_name(path.name + ".rhizome-stack.tmp")
            temporary.write_bytes(replacement.read_bytes())
            temporary.replace(path)
        else:
            subprocess.run(["patch", "--batch", "--forward", "-p1", "-i", str(patch_set / item["payload"])], cwd=root, check=True)
    for item in manifest["files"]:
        path = root / item["path"]
        wanted = item["patched_sha256"]
        if wanted is None:
            if path.exists():
                raise SystemExit(f"post-patch deletion failed: {item['path']}")
        elif not path.is_file() or sha(path) != wanted:
            raise SystemExit(f"post-patch hash mismatch: {item['path']}")
    print(f"patch set applied and verified; rollback files: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
