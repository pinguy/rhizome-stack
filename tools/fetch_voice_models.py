#!/usr/bin/env python3
"""Download redistributable-at-source voice models into local runtime state."""

from pathlib import Path
from huggingface_hub import snapshot_download


root = Path.home() / ".local/share/rhizome-stack/models"
root.mkdir(parents=True, exist_ok=True)
snapshot_download(
    repo_id="ResembleAI/chatterbox-nano",
    local_dir=root / "chatterbox-nano",
)
snapshot_download(
    repo_id="Systran/faster-whisper-large-v3-turbo",
    local_dir=root / "faster-whisper-large-v3-turbo",
)
print(f"voice models ready under {root}")

