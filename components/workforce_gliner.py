#!/usr/bin/env python3
"""Offline, CPU-only GLiNER classification child process."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: workforce_gliner.py MODEL_DIRECTORY DEVICE")
    model_path = Path(sys.argv[1]).resolve()
    device = sys.argv[2]
    if device not in {"cpu", "cuda"}:
        raise SystemExit("device must be cpu or cuda")
    payload = json.load(sys.stdin)
    request = payload["request"]
    taxonomy = payload["taxonomy"]
    from gliner2 import AutoExtractor

    model = AutoExtractor.from_pretrained(str(model_path), local_files_only=True)
    model.to(device)
    model.eval()
    tokenizer = model.processor.tokenizer
    request_tokens = len(tokenizer(request, add_special_tokens=False)["input_ids"])
    encoder_config = json.loads((model_path / "encoder_config/config.json").read_text(encoding="utf-8"))
    encoder_limit = int(getattr(model.config, "max_len", 0) or encoder_config.get("max_position_embeddings", 0) or 0)
    if encoder_limit and request_tokens >= encoder_limit:
        raise ValueError(f"request alone is too large for encoder ({request_tokens} >= {encoder_limit} tokens)")
    result = model.classify_text(
        request,
        taxonomy,
        include_confidence=True,
        max_len=None,
    )
    revision = None
    revision_file = model_path / "RHIZOME_MODEL_REVISION"
    if revision_file.is_file():
        revision = revision_file.read_text(encoding="utf-8").strip()
    print(json.dumps({
        "classification": result,
        "model_revision": revision,
        "device": device,
        "input_limit_tokens": encoder_limit or None,
        "request_tokens": request_tokens,
    }, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
