#!/usr/bin/env python3
"""Root helper: back up and add one explicit gpu-unlock target to GRUB."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
from pathlib import Path


TARGET_RE = re.compile(r"^0000:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--grub-default", type=Path, default=Path("/etc/default/grub"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("this narrow helper must run as root")
    if not TARGET_RE.fullmatch(args.target):
        raise SystemExit("invalid PCI target; expected 0000:BB:DD.F")
    if not args.grub_default.is_file():
        raise SystemExit(f"GRUB defaults not found: {args.grub_default}")
    device = Path("/sys/bus/pci/devices") / args.target
    if not device.is_dir() or (device / "vendor").read_text().strip().lower() != "0x10de":
        raise SystemExit(f"target is not a present NVIDIA PCI device: {args.target}")

    text = args.grub_default.read_text()
    match = re.search(r'(?m)^GRUB_CMDLINE_LINUX_DEFAULT=(?P<quote>["\'])(?P<value>.*)(?P=quote)\s*$', text)
    if not match:
        raise SystemExit("GRUB_CMDLINE_LINUX_DEFAULT is missing or not a simple quoted value")
    existing = re.findall(r"(?:^|\s)gpu_unlock\.targets=([^\s]+)", match.group("value"))
    if existing and existing != [args.target]:
        raise SystemExit(f"a different gpu_unlock.targets value already exists: {existing}")
    args.backup_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    shutil.copy2(args.grub_default, args.backup_dir / "grub.before")
    grub_cfg = Path("/boot/grub/grub.cfg")
    if grub_cfg.is_file():
        shutil.copy2(grub_cfg, args.backup_dir / "grub.cfg.before")
    if existing:
        print(f"gpu_unlock.targets={args.target} is already configured")
        return 0
    value = match.group("value").rstrip() + f" gpu_unlock.targets={args.target}"
    rendered = text[:match.start("value")] + value + text[match.end("value"):]
    with tempfile.NamedTemporaryFile("w", dir=args.grub_default.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(args.grub_default.stat().st_mode & 0o777)
    os.replace(temporary, args.grub_default)
    print(f"configured gpu_unlock.targets={args.target}; backup: {args.backup_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
