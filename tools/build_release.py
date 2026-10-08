#!/usr/bin/env python3
"""Build deterministic, audited tar.zst and ZIP release archives."""

import argparse
import hashlib
import os
import subprocess
import sys
import zipfile
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
    zip_archive = destination / "rhizome-stack.zip"
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
    with zipfile.ZipFile(zip_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(tree.rglob("*")):
            if not path.is_file():
                continue
            relative = Path(tree.name) / path.relative_to(tree)
            info = zipfile.ZipInfo(str(relative), date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = ((path.stat().st_mode & 0o777) | 0o100000) << 16
            with path.open("rb") as stream:
                bundle.writestr(info, stream.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    sums = []
    for path in (archive, zip_archive):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        sums.append(f"{digest}  {path.name}")
        print(f"release archive: {path}\nsha256: {digest}")
    (destination / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
