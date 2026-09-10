#!/usr/bin/env python3
"""Fail closed when a release contains credentials, personal markers or state."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


TEXT_LIMIT = 5 * 1024 * 1024
FORBIDDEN_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".npy", ".pkl", ".index", ".safetensors",
    ".gguf", ".pt", ".pth", ".onnx", ".wav", ".mp3", ".ogg", ".mkv", ".mp4",
}
FORBIDDEN_NAMES = {
    ".env", ".webui_secret_key", "cookies", "cookies-journal", "login data",
    "webui.db", "device-auth.json",
}
PATTERNS = {
    "reference home path": re.compile(r"/home/" + "ping" + r"uy\b", re.I),
    "reference username/name": re.compile(r"\b(?:" + "ping" + "uy|an" + r"toni(?:\s+nor" + "man)?)" + r"\b", re.I),
    "reference Telegram id": re.compile(r"\b" + "70797" + "25827" + r"\b"),
    "email address": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "GitHub token": re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{30,}\b"),
    "Telegram bot token": re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
}
PUBLIC_ATTRIBUTION_EXEMPTIONS = {
    Path("LICENSE"): ("Copyright (c) 2026 An" + "toni Nor" + "man and Rhizome Stack contributors",),
    Path("README.md"): ("Built by An" + "toni Nor" + "man with heavy AI-assisted development, manual testing,",),
}
PUBLIC_REPOSITORIES = (
    "Skills", "RhizomeML", "rhizome-stack", "chatterbox-tts-addon",
    "kokoro-tts-addon", "GGUF-Converter-Studio",
)
PUBLIC_REPO_PATTERN = re.compile(
    r"(?:https://github\.com/|(?<![\w/]))" + "ping" + "uy/"
    + r"(?:" + "|".join(map(re.escape, PUBLIC_REPOSITORIES)) + r")(?=[/#\s\x60\x22.,)?]|$)"
)


def looks_binary(data: bytes) -> bool:
    return b"\0" in data[:4096]


def audit(root: Path) -> list[str]:
    findings: list[str] = []
    if not root.is_dir():
        return [f"not a directory: {root}"]
    for path in sorted(root.rglob("*")):
        if any(part in {"__pycache__", ".pytest_cache", ".git"} for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            findings.append(f"symlink forbidden: {path.relative_to(root)} -> {path.readlink()}")
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        lowered_parts = {part.lower() for part in relative.parts}
        if path.name.lower() in FORBIDDEN_NAMES:
            findings.append(f"runtime/secret filename forbidden: {relative}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(f"runtime/binary state suffix forbidden: {relative}")
        if lowered_parts & {"memory", "backups", "browser", "credentials", "secrets", "uploads", "logs"}:
            findings.append(f"private-state directory name forbidden: {relative}")
        if path.stat().st_size > TEXT_LIMIT:
            findings.append(f"unexpected file larger than {TEXT_LIMIT} bytes: {relative}")
            continue
        data = path.read_bytes()
        if looks_binary(data):
            findings.append(f"unexpected binary file: {relative}")
            continue
        text = data.decode("utf-8", errors="replace")
        for permitted in PUBLIC_ATTRIBUTION_EXEMPTIONS.get(relative, ()):
            text = text.replace(permitted, "[audited public attribution]")
        for label, pattern in PATTERNS.items():
            # Repository provenance is public attribution. Only suppress the
            # owner's name check here; credentials, home paths and emails still
            # get checked against the original text.
            checked = PUBLIC_REPO_PATTERN.sub("[public repository]", text) if label == "reference username/name" else text
            match = pattern.search(checked)
            if match:
                line = checked.count("\n", 0, match.start()) + 1
                findings.append(f"{label}: {relative}:{line}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    findings = audit(args.root.resolve())
    if findings:
        print("PRIVACY AUDIT FAILED", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print(f"PRIVACY AUDIT PASS: {args.root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
