#!/usr/bin/env python3
"""Register the packaged Open WebUI tools without overwriting existing tools."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path


TOOLS = {
    "rhizome_web_search": ("Web Search", "web_search.py", "Current public web research through the configured search provider."),
    "rhizome_memory": ("Local Memory", "memory_search.py", "Read-only search of local memory and book indexes."),
    "openclaw_agent": ("OpenClaw Agent", "openclaw_agent.py", "Delegate a bounded task to the paired local OpenClaw agent."),
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
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Open WebUI API {exc.code}: {detail[:1000]}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--token-file", type=Path, required=True, help="0600 file containing an Open WebUI admin API token")
    args = parser.parse_args()
    if args.token_file.stat().st_mode & 0o077:
        raise SystemExit("token file must not be accessible by group or others (chmod 600)")
    token = args.token_file.read_text().strip()
    if not token:
        raise SystemExit("token file is empty")
    source_root = Path(__file__).resolve().parents[1] / "components/openwebui-tools"
    for tool_id, (name, filename, description) in TOOLS.items():
        existing = api(args.base_url, token, "GET", f"/id/{tool_id}")
        if existing:
            print(f"preserve existing tool: {tool_id}")
            continue
        payload = {
            "id": tool_id,
            "name": name,
            "content": (source_root / filename).read_text(),
            "meta": {"description": description, "manifest": {}, "has_user_valves": False},
            "access_grants": [],
        }
        created = api(args.base_url, token, "POST", "/create", payload)
        if not created or created.get("id") != tool_id:
            raise SystemExit(f"tool creation returned an unexpected response: {tool_id}")
        print(f"created tool: {tool_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

