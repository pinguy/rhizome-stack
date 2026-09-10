#!/usr/bin/env python3
"""Import only files explicitly supplied by the new owner into their private corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import re
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path.home() / ".local/share/rhizome-stack/memory"
CORPUS = ROOT / "owner-imports"
ARCHIVE = ROOT / "archive"
TEXT_EXTENSIONS = {".txt", ".md", ".rst", ".csv", ".json", ".jsonl"}


def clean(value: object) -> str:
    return " ".join(str(value or "").split())


def chunks(text: str, size: int = 1400, overlap: int = 180):
    text = clean(text)
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind(" ", start + size // 2, end)
            end = boundary if boundary > start else end
        yield text[start:end]
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)


def conversation_text(value: object, path: str = "") -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    if isinstance(value, dict):
        role = value.get("role") or value.get("sender")
        content = value.get("content") or value.get("text")
        if isinstance(content, dict):
            content = content.get("parts") or content.get("text")
        if isinstance(content, list):
            content = "\n".join(clean(item) for item in content if clean(item))
        if role and isinstance(content, str) and clean(content):
            found.append((f"{role}: {clean(content)}", {"role": clean(role), "record": path}))
        for key, item in value.items():
            found.extend(conversation_text(item, f"{path}/{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(conversation_text(item, f"{path}/{index}"))
    return found


def read_document(path: Path, kind: str) -> list[tuple[str, dict]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF import needs pypdf in the memory environment") from exc
        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        return [(text, {})]
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("DOCX import needs python-docx in the memory environment") from exc
        return [("\n".join(p.text for p in Document(path).paragraphs), {})]
    if suffix not in TEXT_EXTENSIONS:
        return []
    text = path.read_text(errors="replace")
    if kind in {"chatgpt", "claude"} or (kind == "auto" and suffix in {".json", ".jsonl"}):
        try:
            payload = json.loads(text)
            messages = conversation_text(payload)
            if messages:
                return messages
        except json.JSONDecodeError:
            if kind != "auto":
                raise
    return [(text, {})]


def source_files(source: Path):
    if source.is_dir():
        yield from (item for item in sorted(source.rglob("*")) if item.is_file())
    else:
        yield source


def import_source(source: Path, kind: str) -> int:
    if not source.exists():
        raise RuntimeError(f"source does not exist: {source}")
    if source.suffix.lower() == ".zip":
        extract = CORPUS / "zip-staging" / hashlib.sha256(source.read_bytes()).hexdigest()[:16]
        extract.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(source) as bundle:
            for member in bundle.infolist():
                target = (extract / member.filename).resolve()
                if extract.resolve() not in target.parents and target != extract.resolve():
                    raise RuntimeError("unsafe path in zip export")
                if not member.is_dir():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bundle.read(member))
        source = extract
    CORPUS.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in source_files(source):
        for text, extra in read_document(path, kind):
            for number, piece in enumerate(chunks(text)):
                digest = hashlib.sha256(piece.encode()).hexdigest()
                record = {"id": digest, "text": piece, "source_name": path.name,
                          "source_type": kind, "chunk": number, **extra}
                destination = CORPUS / f"{digest}.json"
                if not destination.exists():
                    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
                    count += 1
    return count


def build_index() -> int:
    import faiss
    import numpy as np
    from sentence_transformers import SentenceTransformer
    records = [json.loads(path.read_text()) for path in sorted(CORPUS.glob("*.json"))]
    texts = [item["text"] for item in records]
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=True) if texts else np.empty((0, 384), dtype="float32")
    index = faiss.IndexFlatIP(384)
    if len(vectors):
        index.add(np.asarray(vectors, dtype="float32"))
    faiss.write_index(index, str(ARCHIVE / "memory.index"))
    np.save(ARCHIVE / "memory_texts.npy", np.asarray(texts, dtype=object), allow_pickle=True)
    with (ARCHIVE / "memory_metadata.pkl").open("wb") as stream:
        pickle.dump([{key: value for key, value in item.items() if key != "text"} for item in records], stream)
    return len(records)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import new-owner material; no source data is added to the distribution")
    parser.add_argument("source", nargs="?")
    parser.add_argument("--type", choices=["auto", "documents", "chatgpt", "claude"], default="auto")
    parser.add_argument("--build-index", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.build_index:
        print(f"indexed {build_index()} private owner chunks")
        return 0
    if not args.source:
        parser.error("source is required")
    count = import_source(Path(args.source).expanduser().resolve(), args.type)
    memory_python = Path.home() / ".local/share/rhizome-stack/venvs/memory/bin/python"
    if memory_python.exists():
        subprocess.run([str(memory_python), str(Path(__file__).resolve()), "--build-index"], check=True)
    else:
        print("Import staged safely, but semantic indexing needs the optional memory component.")
    print(f"imported {count} new private chunks (existing duplicates preserved once)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
