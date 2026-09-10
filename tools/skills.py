#!/usr/bin/env python3
"""Install the audited Skills snapshot without replacing local customisations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def workspace() -> Path:
    config_path = Path(os.environ.get("OPENCLAW_CONFIG_PATH", Path.home() / ".openclaw/openclaw.json"))
    if config_path.exists():
        config = json.loads(config_path.read_text())
        configured = config.get("agents", {}).get("defaults", {}).get("workspace")
        if configured:
            return Path(configured).expanduser().resolve()
    return Path(os.environ.get("RHIZOME_STACK_ROOT", Path.home() / ".local/share/rhizome-stack")) / "workspace"


def hashes(root: Path) -> dict[str, str]:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink in skill directory: {path}")
        if path.is_file() and "__pycache__" not in path.parts:
            files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def install(names: list[str], destination: Path, manifest: dict, dry_run: bool = False) -> int:
    # Check every source before changing any installed skill.
    for name in names:
        if hashes(PROJECT / "components/skills" / name) != manifest["skills"][name]["files"]:
            raise ValueError(f"bundled skill checksum mismatch: {name}")
    conflicts = 0
    for name in names:
        source = PROJECT / "components/skills" / name
        target = destination / name
        if target.exists() or target.is_symlink():
            if target.is_dir() and not target.is_symlink() and hashes(target) == hashes(source):
                print(f"PASS {name}: already installed")
            else:
                print(f"PRESERVED {name}: existing local copy differs; compare with {source}")
                conflicts += 1
            continue
        print(f"{'PLAN' if dry_run else 'INSTALL'} {name} -> {target}")
        if not dry_run:
            destination.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".skill-", dir=destination) as temporary:
                staged = Path(temporary) / name
                shutil.copytree(source, staged, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                staged.rename(target)
    return 1 if conflicts else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["list", "install"])
    parser.add_argument("names", nargs="*", help="specific skill directory names")
    parser.add_argument("--profile", choices=["core", "all"], default="core")
    parser.add_argument("--workspace", type=Path, help="override the configured OpenClaw workspace")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((PROJECT / "manifests/skills.json").read_text())
    if args.action == "list":
        print(f"Skills snapshot: {manifest['commit']}")
        for name, entry in manifest["skills"].items():
            print(f"{entry['profile']:5}  {name}")
        return 0
    names = list(dict.fromkeys(args.names)) or [
        name for name, entry in manifest["skills"].items()
        if args.profile == "all" or entry["profile"] == "core"
    ]
    unknown = sorted(set(names) - manifest["skills"].keys())
    if unknown:
        parser.error("unknown skills: " + ", ".join(unknown))
    if "council-blackboard" in names and "blackboard" not in names:
        names.insert(0, "blackboard")
    try:
        selected_workspace = args.workspace.expanduser().resolve() if args.workspace else workspace()
        result = install(names, selected_workspace / "skills", manifest, args.dry_run)
        print("Open a new agent session to discover installed skills; load full instructions only when needed.")
        return result
    except (OSError, ValueError) as exc:
        print(f"skill installation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
