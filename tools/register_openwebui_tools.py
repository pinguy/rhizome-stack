#!/usr/bin/env python3
"""Register the packaged Open WebUI tools without overwriting existing tools."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from file_utils import atomic_write_text


TOOLS = {
    "rhizome_web_search": ("Web Search", "web_search.py", "Current public web research through the configured search provider."),
    "rhizome_memory": ("Local Memory", "memory_search.py", "Read-only search of local memory and book indexes."),
    "openclaw_agent": ("OpenClaw Agent", "openclaw_agent.py", "Delegate a bounded task to the paired local OpenClaw agent."),
    "minimax_music_3": ("MiniMax Music 3", "minimax_music.py", "Create local songs and attach them as native playable Open WebUI files."),
    "qwen_image": ("Qwen Image Desk", "qwen_image.py", "Create or reference-edit local images and attach them to the saved chat."),
    "wan_video": ("WAN Video Desk", "wan_video.py", "Create local WAN videos and attach durable MP4s to the saved chat."),
}


def api(base: str, token: str, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        base.rstrip("/") + "/api/v1/tools" + path,
        data=data,
        method=method,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        with exc:
            if exc.code == 404 and method == "GET" and path.startswith("/id/"):
                return None
            detail = exc.read(4096).decode(errors="replace")
        raise RuntimeError(f"Open WebUI API {exc.code}: {detail[:1000]}") from exc


def source_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def update_payload(existing: dict, shipped: str, description: str) -> dict:
    return {
        "id": existing["id"],
        "name": existing.get("name") or existing["id"],
        "content": shipped,
        "meta": existing.get("meta") or {
            "description": description, "manifest": {}, "has_user_valves": False,
        },
        "access_grants": existing.get("access_grants") or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--token-file", type=Path, required=True, help="0600 file containing an Open WebUI admin API token")
    parser.add_argument("--mode", choices=("preserve", "diff", "update"), default="preserve",
                        help="preserve existing tools, report drift, or update drift after a private backup")
    parser.add_argument("--backup-dir", type=Path,
                        help="directory for pre-update tool source (default: XDG state directory)")
    parser.add_argument("--hash-only", action="store_true", help="with --mode diff, omit unified source diffs")
    args = parser.parse_args()
    if args.token_file.stat().st_mode & 0o077:
        raise SystemExit("token file must not be accessible by group or others (chmod 600)")
    token = args.token_file.read_text().strip()
    if not token:
        raise SystemExit("token file is empty")
    source_root = Path(__file__).resolve().parents[1] / "components/openwebui-tools"
    drift = False
    backup_root = args.backup_dir
    for tool_id, (name, filename, description) in TOOLS.items():
        shipped = (source_root / filename).read_text()
        shipped_hash = source_hash(shipped)
        existing = api(args.base_url, token, "GET", f"/id/{tool_id}")
        if existing:
            deployed = existing.get("content")
            if not isinstance(deployed, str):
                raise RuntimeError(f"Open WebUI did not return source for tool: {tool_id}")
            deployed_hash = source_hash(deployed)
            state = "current" if deployed_hash == shipped_hash else "drift"
            print(f"tool {tool_id}: {state} deployed={deployed_hash} shipped={shipped_hash}")
            if state == "current":
                continue
            drift = True
            if args.mode == "preserve":
                print(f"preserve existing customised tool: {tool_id}")
                continue
            if args.mode == "diff":
                if not args.hash_only:
                    print("".join(difflib.unified_diff(
                        deployed.splitlines(keepends=True), shipped.splitlines(keepends=True),
                        fromfile=f"deployed/{tool_id}.py", tofile=f"shipped/{tool_id}.py",
                    )), end="")
                continue
            if backup_root is None:
                state_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                backup_root = state_root / "rhizome-stack/openwebui-tool-backups" / stamp
            backup_root.mkdir(parents=True, exist_ok=True)
            atomic_write_text(
                backup_root / f"{tool_id}.json",
                json.dumps(existing, indent=2, sort_keys=True) + "\n",
                0o600,
            )
            updated = api(args.base_url, token, "POST", f"/id/{tool_id}/update",
                          update_payload(existing, shipped, description))
            if not updated or updated.get("id") != tool_id:
                raise SystemExit(f"tool update returned an unexpected response: {tool_id}")
            print(f"updated tool after backup: {tool_id} -> {backup_root / (tool_id + '.json')}")
            continue
        drift = True
        print(f"tool {tool_id}: missing shipped={shipped_hash}")
        if args.mode == "diff":
            continue
        payload = {
            "id": tool_id,
            "name": name,
            "content": shipped,
            "meta": {"description": description, "manifest": {}, "has_user_valves": False},
            "access_grants": [],
        }
        created = api(args.base_url, token, "POST", "/create", payload)
        if not created or created.get("id") != tool_id:
            raise SystemExit(f"tool creation returned an unexpected response: {tool_id}")
        print(f"created tool: {tool_id}")
    return int(args.mode == "diff" and drift)


if __name__ == "__main__":
    raise SystemExit(main())
