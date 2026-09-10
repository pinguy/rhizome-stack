#!/usr/bin/env python3
"""One-shot faster-whisper fallback used when the audio bridge is unavailable."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from faster_whisper import WhisperModel


if len(sys.argv) != 3:
    raise SystemExit("usage: transcribe_faster_whisper.py AUDIO OUTPUT")

model = WhisperModel(
    os.environ.get("WHISPER_MODEL", str(Path.home() / ".local/share/rhizome-stack/models/faster-whisper-large-v3-turbo")),
    device="cpu", compute_type="int8", cpu_threads=16, local_files_only=True,
)
segments, _ = model.transcribe(
    sys.argv[1], language="en", task="transcribe", beam_size=1, best_of=1,
    temperature=0.0, condition_on_previous_text=False, vad_filter=False,
)
text = " ".join(segment.text.strip() for segment in segments).strip()
Path(sys.argv[2]).write_text(text + "\n", encoding="utf-8")
