#!/usr/bin/env python3
"""Stage and verify a captured patch set before changing exact upstream files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def confined(root: Path, name: str) -> Path:
    relative = Path(name)
    path = root / relative
    if (not name or relative.is_absolute() or ".." in relative.parts
            or path == root or path.is_symlink() or path.resolve() != path):
        raise SystemExit(f"unsafe patch path: {name}")
    return path


def matches(path: Path, digest: str | None) -> bool:
    return not path.exists() if digest is None else path.is_file() and sha(path) == digest


def install_file(source: Path, destination: Path) -> None:
    # A unique sibling makes replacement atomic and preserves executable modes.
    fd, name = tempfile.mkstemp(prefix=".rhizome-patch-", dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copy2(source, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("patch_set", type=Path)
    parser.add_argument("installed_root", type=Path)
    args = parser.parse_args()
    patch_set = args.patch_set.resolve()
    root = args.installed_root.resolve()
    manifest = json.loads((patch_set / "manifest.json").read_text())
    files = manifest["files"]
    seen = set()
    for item in files:
        confined(root, item["path"])
        if item["path"] in seen or item["action"] not in {"delete", "replace", "modify"}:
            raise SystemExit(f"invalid or duplicate patch entry: {item['path']}")
        seen.add(item["path"])
        if item["action"] != "delete":
            confined(patch_set, item["payload"])
        if (item["action"] == "delete") != (item["patched_sha256"] is None):
            raise SystemExit(f"invalid deletion digest: {item['path']}")
    if all(matches(root / item["path"], item["patched_sha256"]) for item in files):
        print("patch set already applied and verified")
        return 0

    def check_base():
        for item in files:
            path = confined(root, item["path"])
            if not path.is_file() or sha(path) != item["clean_sha256"]:
                raise SystemExit(f"base hash mismatch; refusing patch: {item['path']}")

    check_base()
    backup = root / ".rhizome-stack-patch-backup"
    if backup.exists() or backup.is_symlink():
        raise SystemExit(f"backup already exists; reconcile before retrying: {backup}")
    with tempfile.TemporaryDirectory(prefix="rhizome-patch-stage-") as temporary:
        stage = Path(temporary)
        # Do every potentially failing patch operation away from installed code.
        for item in files:
            path = stage / item["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / item["path"], path)
            if item["action"] == "delete":
                path.unlink()
            elif item["action"] == "replace":
                shutil.copyfile(patch_set / item["payload"], path)
            else:
                subprocess.run(["patch", "--batch", "--forward", str(path),
                                "-i", str(patch_set / item["payload"])], cwd=stage, check=True)
        for item in files:
            if not matches(stage / item["path"], item["patched_sha256"]):
                raise SystemExit(f"staged patch hash mismatch: {item['path']}")
        check_base()
        backup.mkdir()
        for item in files:
            target = backup / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / item["path"], target)
        check_base()
        changed = []
        try:
            for item in files:
                path = root / item["path"]
                if item["action"] == "delete":
                    path.unlink()
                else:
                    install_file(stage / item["path"], path)
                changed.append(item)
            for item in files:
                if not matches(root / item["path"], item["patched_sha256"]):
                    raise RuntimeError(f"post-patch hash mismatch: {item['path']}")
        except (Exception, KeyboardInterrupt):
            # Do not overwrite independent changes made after our replacement.
            for item in reversed(changed):
                path = root / item["path"]
                if matches(path, item["patched_sha256"]):
                    install_file(backup / item["path"], path)
            print(f"patch installation failed; inspect rollback files: {backup}", file=sys.stderr)
            raise
    print(f"patch set applied and verified; rollback files: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
