#!/usr/bin/env python3
"""Render text through the shared local Chatterbox bridge."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_URL = "http://127.0.0.1:8010/v1/audio/speech"
DEFAULT_KEY = "local-dev-key"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--url", default=os.environ.get("CHATTERBOX_TTS_URL", DEFAULT_URL))
    parser.add_argument("--api-key", default=os.environ.get("CHATTERBOX_API_KEY", DEFAULT_KEY))
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()

    text = args.text.strip()
    if not text:
        parser.error("--text must not be empty")
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"model": "tts-1", "voice": "rhizome", "input": text}).encode()
    request = urllib.request.Request(
        args.url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {args.api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(600).decode("utf-8", errors="replace")
        raise SystemExit(f"Chatterbox HTTP {exc.code}: {detail}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise SystemExit(f"Chatterbox request failed: {exc}") from exc
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise SystemExit("Chatterbox returned invalid WAV data")

    handle, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(audio)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, output)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
