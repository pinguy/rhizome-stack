#!/usr/bin/env python3
"""Two-way bridge between OpenClaw's MEMORY.md and Open WebUI's native Memory
(the "Memory (Experimental)" panel).

Design (Option B):
  push  MEMORY.md  -> Open WebUI native memories (embedded, retrieval-based).
        Each synced entry is tagged with path prefix "openclaw/" so it never
        collides with memories Pingu adds himself (those use other paths).
  pull  Open WebUI native memories (the NON-"openclaw/" ones, i.e. his own) ->
        memory/shared-openwebui.md, which OpenClaw reads live via the
        memory-rhizome markdown fallback and indexes on the next sidecar sync.

Retrieval is top-k vector search with a relevance threshold on the Open WebUI
side, so a large MEMORY.md does NOT bloat every prompt -- only relevant entries
surface per query.

Identify/rollback: everything this script pushes has path starting "openclaw/".
`--purge` deletes exactly those (leaving his own memories untouched). A full
rollback is restoring the webui.db snapshot taken before first run.

No secrets are written to disk; the JWT is minted in-memory from the running
Open WebUI secret key.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import urllib.request
import uuid
from pathlib import Path

OW_URL = "http://127.0.0.1:8080"
USER_ID = os.environ.get("OPENWEBUI_USER_ID", "")
SECRET_FILE = Path(os.environ.get("WEBUI_SECRET_FILE", str(Path.home() / ".config/rhizome-stack/webui_secret_key")))
WS = Path(os.environ.get("RHIZOME_WORKSPACE", str(Path.home() / ".local/share/rhizome-stack/workspace")))
MEMORY_MD = WS / "MEMORY.md"
SHARED_MD = WS / "memory" / "shared-openwebui.md"
SYNC_PREFIX = "openclaw/"          # path marker for entries WE own
MAX_ENTRY_CHARS = 700
MAX_ENTRIES = 250                  # safety cap on push


def _secret() -> str:
    # Prefer the live process env; fall back to the key file.
    try:
        import subprocess
        pid = subprocess.check_output(["pgrep", "-f", "open_webui|open.webui"]).split()[0].decode()
        env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        for kv in env:
            if kv.startswith(b"WEBUI_SECRET_KEY="):
                return kv.split(b"=", 1)[1].decode()
    except Exception:
        pass
    return SECRET_FILE.read_text().strip()


def _token() -> str:
    import jwt
    return jwt.encode(
        {"id": USER_ID, "jti": str(uuid.uuid4()), "iat": datetime.datetime.now(datetime.UTC)},
        _secret(), algorithm="HS256",
    )


def _api(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        OW_URL + "/api/v1/memories" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + _token(), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def list_memories() -> list[dict]:
    return _api("GET", "/") or []


# ---------- MEMORY.md -> discrete memory entries ----------

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "misc"


def parse_memory_md(text: str) -> list[tuple[str, str]]:
    """Return (content, path) tuples. One entry per top-level bullet or
    standalone paragraph, prefixed with its heading breadcrumb for context."""
    entries: list[tuple[str, str]] = []
    h2 = h3 = ""
    buf: list[str] = []

    def flush():
        nonlocal buf
        block = " ".join(x.strip() for x in buf if x.strip()).strip()
        buf = []
        if not block or len(block) < 8:
            return
        crumb = " > ".join(x for x in (h2, h3) if x)
        content = (f"[{crumb}] {block}" if crumb else block)[:MAX_ENTRY_CHARS]
        section = _slug(h3 or h2 or "general")
        entries.append((content, SYNC_PREFIX + section))

    for line in text.splitlines():
        s = line.strip()
        if s.startswith("<!--") or s == "---":
            continue
        if s.startswith("## "):
            flush(); h2 = s[3:].strip(); h3 = ""; continue
        if s.startswith("### "):
            flush(); h3 = s[4:].strip(); continue
        if s.startswith("# "):
            flush(); h2 = s[2:].strip(); h3 = ""; continue
        if re.match(r"^[-*] ", s):          # new top-level bullet => new entry
            flush(); buf.append(re.sub(r"^[-*] ", "", s)); continue
        if not s:                            # blank line => paragraph break
            flush(); continue
        buf.append(s)                        # continuation / sub-bullet / prose
    flush()
    return entries[:MAX_ENTRIES]


# ---------- operations ----------

def purge_synced() -> int:
    ours = [m for m in list_memories() if (m.get("path") or "").startswith(SYNC_PREFIX)]
    for m in ours:
        _api("DELETE", f"/{m['id']}")
    return len(ours)


STAMP = WS / "memory" / ".openwebui-memory-push.stamp"


def _memory_md_hash() -> str:
    import hashlib
    return hashlib.sha256(MEMORY_MD.read_bytes()).hexdigest()


def push(dry: bool, force: bool = False) -> None:
    cur = _memory_md_hash()
    if not force and not dry and STAMP.exists() and STAMP.read_text().strip() == cur:
        print("MEMORY.md unchanged since last push — skipping re-embed (use --force to override)")
        return
    entries = parse_memory_md(MEMORY_MD.read_text())
    print(f"MEMORY.md -> {len(entries)} memory entries (path prefix '{SYNC_PREFIX}')")
    if dry:
        for c, p in entries[:8]:
            print(f"  [{p}] {c[:70]}")
        print("  ... (dry-run, nothing written)")
        return
    removed = purge_synced()
    print(f"  cleared {removed} previously-synced entries")
    added = 0
    for content, path in entries:
        _api("POST", "/add", {"content": content, "type": "context", "path": path})
        added += 1
    STAMP.write_text(cur)
    print(f"  added {added} entries (embedded + in native panel)")


def pull(dry: bool) -> None:
    theirs = [m for m in list_memories() if not (m.get("path") or "").startswith(SYNC_PREFIX)]
    print(f"Open WebUI native memories (his own) -> {SHARED_MD.name}: {len(theirs)} entries")
    lines = [
        "# Shared Open WebUI memories",
        "",
        "<!-- AUTO-GENERATED by scripts/sync_openwebui_memory.py --pull. Do not edit by hand.",
        "     Source of truth is Open WebUI's native Memory panel. OpenClaw reads this file",
        "     live via the memory-rhizome markdown fallback. -->",
        f"_synced {datetime.datetime.now().isoformat(timespec='seconds')} — {len(theirs)} entries_",
        "",
    ]
    for m in sorted(theirs, key=lambda x: x.get("path") or ""):
        p = m.get("path") or "note"
        lines.append(f"- **[{p}]** {(m.get('content') or '').strip()}")
    out = "\n".join(lines) + "\n"
    if dry:
        print(out[:600] + ("..." if len(out) > 600 else ""))
        return
    SHARED_MD.parent.mkdir(parents=True, exist_ok=True)
    SHARED_MD.write_text(out)
    print(f"  wrote {SHARED_MD}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Two-way OpenClaw<->Open WebUI memory sync")
    ap.add_argument("mode", choices=["push", "pull", "sync", "purge", "list"], nargs="?", default="sync")
    ap.add_argument("-n", "--dry-run", action="store_true")
    ap.add_argument("-f", "--force", action="store_true", help="re-push even if MEMORY.md unchanged")
    a = ap.parse_args()
    if a.mode == "list":
        for m in list_memories():
            print(f"  {m.get('path')}: {(m.get('content') or '')[:70]}")
        return 0
    if a.mode == "purge":
        print(f"purged {purge_synced()} synced entries" if not a.dry_run else "(dry-run) would purge synced entries")
        return 0
    if a.mode in ("push", "sync"):
        push(a.dry_run, a.force)
    if a.mode in ("pull", "sync"):
        pull(a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
