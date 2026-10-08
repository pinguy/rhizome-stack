#!/usr/bin/env python3
"""Download redistributable-at-source voice models into local runtime state."""

import argparse
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-root', type=Path, default=Path(os.environ.get(
        'RHIZOME_STACK_ROOT', '~/.local/share/rhizome-stack')).expanduser() / 'models')
    args = parser.parse_args()
    from huggingface_hub import snapshot_download
    root = args.model_root.expanduser()
    root.mkdir(parents=True, exist_ok=True)
    for repository, directory in (
        ('ResembleAI/chatterbox-nano', 'chatterbox-nano'),
        ('Systran/faster-whisper-large-v3-turbo', 'faster-whisper-large-v3-turbo'),
    ):
        snapshot_download(repo_id=repository, local_dir=root / directory)
    print(f'voice models ready under {root}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

