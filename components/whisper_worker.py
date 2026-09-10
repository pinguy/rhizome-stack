#!/usr/bin/env python3
"""Persistent CPU faster-whisper worker with a line-oriented JSON protocol."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from faster_whisper import WhisperModel


def main() -> int:
    model = WhisperModel(
        os.environ.get(
            "WHISPER_MODEL",
            str(Path.home() / ".local/share/rhizome-stack/models/faster-whisper-large-v3-turbo"),
        ),
        device="cpu",
        compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
        cpu_threads=int(os.environ.get("WHISPER_CPU_THREADS", "16")),
        local_files_only=True,
    )
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            req = json.loads(line)
            segments, info = model.transcribe(
                req["audio_path"],
                language="en",
                task="transcribe",
                beam_size=1,
                best_of=1,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            print(json.dumps({"text": text, "language": info.language}), flush=True)
        except Exception as exc:
            print(json.dumps({"error": str(exc)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
