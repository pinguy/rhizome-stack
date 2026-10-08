#!/usr/bin/env python3
"""Fetch the exact optional CPU MiniLM snapshot selected for retrieval."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-root", type=Path, default=Path(os.environ.get(
        "RHIZOME_STACK_ROOT", "~/.local/share/rhizome-stack")).expanduser() / "models/all-MiniLM-L6-v2")
    args = parser.parse_args()
    versions = json.loads((ROOT / "manifests/versions.json").read_text())
    revision = versions["minilm_revision"]
    destination = args.model_root / revision
    snapshot_download(repo_id="sentence-transformers/all-MiniLM-L6-v2", revision=revision,
                      local_dir=destination, local_dir_use_symlinks=False)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
