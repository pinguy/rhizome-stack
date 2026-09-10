#!/usr/bin/env python3
"""Create a deterministic release tree from the sanitised project directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_root.resolve()
    if (source / "rhizome-stack").is_dir():
        source = source / "rhizome-stack"
    output = args.output.resolve()
    release_list = json.loads((source / "manifests/release-files.json").read_text())
    approved = []
    for name in release_list["files"]:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe release path: {name}")
        path = source / relative
        if not path.is_file() or path.is_symlink() or path.resolve() != path:
            raise ValueError(f"release file missing or symlinked: {name}")
        approved.append(path)
    if output.exists():
        print(f"refusing to overwrite existing output: {output}", file=sys.stderr)
        return 2
    if source == output or source in output.parents:
        print("output must be outside the source tree", file=sys.stderr)
        return 2
    output.mkdir(parents=True)
    for path in sorted(approved):
        target = output / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    manifest = {
        "schema": 1,
        "created_at": datetime.fromtimestamp(
            int(__import__("os").environ.get("SOURCE_DATE_EPOCH", "0")), timezone.utc
        ).isoformat(),
        "source_kind": "sanitised-allow-list-tree",
        "files": {
            str(path.relative_to(output)): {"sha256": digest(path), "bytes": path.stat().st_size}
            for path in sorted(output.rglob("*")) if path.is_file()
        },
    }
    manifest_path = output / "RELEASE-MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    audit = subprocess.run([sys.executable, str(output / "tools/privacy_audit.py"), str(output)])
    if audit.returncode:
        print(f"release retained for inspection but is NOT publishable: {output}", file=sys.stderr)
        return audit.returncode
    verify = subprocess.run([sys.executable, str(output / "tools/verify_release.py"), str(output)])
    if verify.returncode:
        print(f"release manifest verification failed: {output}", file=sys.stderr)
        return verify.returncode
    print(f"release ready for manual review: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
