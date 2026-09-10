#!/usr/bin/env python3
"""Maintainer tool to capture installed wheel drift as hash-guarded text patches."""

from __future__ import annotations

import argparse
import base64
import csv
import difflib
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def wheel_hash(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def text(data: bytes, name: str) -> list[str]:
    if b"\0" in data[:4096]:
        raise SystemExit(f"refusing binary package drift: {name}")
    return data.decode("utf-8").splitlines(keepends=True)


def portable_installed(relative: str, data: bytes) -> bytes:
    value = data.decode("utf-8")
    home = str(Path.home())
    if relative == "open_webui/main.py":
        value = value.replace(
            f"Path(\n    '{home}/.openclaw/workspace/ethics_engine/OpenWebUI_Instructions.txt'\n)",
            "Path(os.getenv('RHIZOME_FRAMEWORK_PATH', str(Path.home() / '.local/share/rhizome-stack/workspace/ethics_engine/OpenWebUI_Instructions.txt')))",
        )
        generic = """RHIZOME_OPERATIONAL_SYSTEM = (
    'Use available tools when the user explicitly requests a lookup, current information, '
    'execution, testing, or calculation. Ground the answer in the returned evidence. Protect '
    'private information, prefer direct low-fluff answers, state uncertainty honestly, and use '
    'local memory only when prior context genuinely matters. Never import another user profile.'
)"""
        value = re.sub(
            r"RHIZOME_OPERATIONAL_SYSTEM = \(.*?\n\)\n\n\ndef _rhizome_compose_system",
            generic + "\n\n\ndef _rhizome_compose_system",
            value,
            flags=re.S,
        )
    elif relative == "open_webui/tools/builtin.py":
        value = value.replace(
            f"'{home}/.openclaw/workspace/state/openwebui-code-work'",
            "str(Path.home() / '.local/share/rhizome-stack/state/openwebui-code-work')",
        )
    elif relative == "open_webui/utils/middleware.py":
        value = value.replace(
            f"'{home}/.openclaw/workspace/shared/openwebui-uploads/'",
            "os.path.expanduser('~/.local/share/rhizome-stack/shared/openwebui-uploads/')",
        )
        value = value.replace(
            f"'{home}/.openclaw/workspace/.venvs/open-webui/lib/python3.12/'\n            'site-packages/open_webui/data/uploads/'",
            "os.path.expanduser('~/.local/share/rhizome-stack/state/openwebui-data/uploads/')",
        )
        value = value.replace(
            f"attrs += (\n                ' host_path=\"{home}/.openclaw/workspace/shared/'\n                f'openwebui-uploads/{{upload_name}}\"'\n            )",
            "attrs += f' host_path=\"{os.path.expanduser(\"~/.local/share/rhizome-stack/shared/openwebui-uploads/\")}{upload_name}\"'",
        )
    return value.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--installed-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prefix", default="open_webui/")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite {args.output}")
    args.output.mkdir(parents=True)
    manifest = {"schema": 1, "wheel": args.wheel.name, "files": []}
    with zipfile.ZipFile(args.wheel) as wheel:
        record_name = next(name for name in wheel.namelist() if name.endswith(".dist-info/RECORD"))
        rows = csv.reader(wheel.read(record_name).decode().splitlines())
        for relative, encoded, _size in rows:
            if not relative.startswith(args.prefix) or not encoded.startswith("sha256="):
                continue
            clean = wheel.read(relative)
            installed_path = args.installed_root / relative
            installed_exists = installed_path.is_file()
            if installed_exists:
                installed_raw = installed_path.read_bytes()
                if wheel_hash(installed_raw) == encoded[7:]:
                    continue
                installed = portable_installed(relative, installed_raw)
            else:
                installed = b""
            action = "modify" if installed_exists else "delete"
            patch_name = relative.replace("/", "__") + ".patch"
            if installed_exists:
                clean_lines = text(clean, relative)
                installed_lines = text(installed, relative)
                if relative.startswith("open_webui/frontend/") or max((len(line) for line in clean_lines + installed_lines), default=0) > 200_000:
                    action = "replace"
                    patch_name = relative.replace("/", "__") + ".replacement.txt"
                    (args.output / patch_name).write_bytes(installed)
                else:
                    diff = difflib.unified_diff(
                        clean_lines, installed_lines,
                        fromfile="a/" + relative, tofile="b/" + relative,
                    )
                    patch_path = args.output / patch_name
                    patch_path.write_text("".join(diff))
            manifest["files"].append({
                "path": relative,
                "action": action,
                "clean_sha256": sha(clean),
                "patched_sha256": sha(installed) if installed_exists else None,
                "payload": patch_name if installed_exists else None,
            })
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"captured {len(manifest['files'])} package changes in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
