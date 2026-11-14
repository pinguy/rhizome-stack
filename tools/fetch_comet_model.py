#!/usr/bin/env python3
"""Download the pinned COMET checkpoint and fail closed on its main weight."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSIONS = json.loads((ROOT / "manifests/versions.json").read_text())
EXPECTED_SIZE = 1_625_695_432
EXPECTED_SHA256 = "068ef0181830c81913f26a84404afa48035d5797c2fc33fd383b2f23251cc5f0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=VERSIONS["comet_model_repo"],
        revision=VERSIONS["comet_model_revision"],
        local_dir=args.output,
        allow_patterns=["config.json", "pytorch_model.bin", "vocab.json", "merges.txt",
                        "added_tokens.json", "special_tokens_map.json", "tokenizer_config.json",
                        "README.md"],
    )
    weights = args.output / "pytorch_model.bin"
    if not weights.is_file() or weights.stat().st_size != EXPECTED_SIZE:
        raise SystemExit("downloaded COMET weights have the wrong size")
    got = sha256(weights)
    if got != EXPECTED_SHA256:
        raise SystemExit(f"downloaded COMET weights failed SHA-256: {got}")
    print(f"verified COMET checkpoint: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
