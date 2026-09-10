#!/usr/bin/env python3
"""Build a deterministic, audited release tree and tar.zst archive."""

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    version = (ROOT / "VERSION").read_text().strip()
    destination = args.output_root.resolve() / version
    tree = destination / "rhizome-stack"
    archive = destination / "rhizome-stack.tar.zst"
    if destination.exists():
        print(f"refusing to overwrite release directory: {destination}", file=sys.stderr)
        return 2
    destination.mkdir(parents=True)
    env = os.environ.copy()
    env.setdefault("SOURCE_DATE_EPOCH", "0")
    subprocess.run([sys.executable, str(ROOT / "tools/export_release.py"), "--source-root", str(ROOT), "--output", str(tree)], env=env, check=True)
    tar = subprocess.Popen([
        "tar", "--sort=name", "--mtime=@0", "--owner=0", "--group=0", "--numeric-owner",
        "--mode=u+rwX,go+rX", "-C", str(destination), "-cf", "-", tree.name,
    ], stdout=subprocess.PIPE)
    with archive.open("wb") as output:
        compressor = subprocess.run(["zstd", "-19", "--no-progress", "-c"], stdin=tar.stdout, stdout=output)
    assert tar.stdout is not None
    tar.stdout.close()
    if tar.wait() or compressor.returncode:
        return 2
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n")
    print(f"release archive: {archive}\nsha256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
