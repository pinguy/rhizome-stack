#!/usr/bin/env python3
"""Import only files explicitly supplied by the new owner into their private corpus."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from import_formats import records as conversation_records, structured_records

STACK_ROOT = Path(os.environ.get("RHIZOME_STACK_ROOT", Path.home() / ".local/share/rhizome-stack")).expanduser()
ROOT = STACK_ROOT / "memory"
CORPUS = ROOT / "owner-imports"
ARCHIVE = ROOT / "archive"
TEXT_EXTENSIONS = {".txt", ".md", ".rst", ".csv", ".json", ".jsonl"}
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def clean(value: object) -> str:
    return " ".join(str(value or "").split())


def chunks(text: str, size: int = 1400, overlap: int = 180):
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("chunk overlap must be nonnegative and smaller than chunk size")
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
    return list(conversation_records(value, path))


def read_document(path: Path, kind: str):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF import needs pypdf in the memory environment") from exc
        for number, page in enumerate(PdfReader(path).pages, 1):
            yield page.extract_text() or "", {"source": "pdf", "document_id": path.name,
                                              "filename": path.name, "page": number}
        return
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("DOCX import needs python-docx in the memory environment") from exc
        yield "\n".join(p.text for p in Document(path).paragraphs), {"source": "document", "filename": path.name}
        return
    structured = suffix in {".json", ".jsonl"} or path.name.lower().endswith((".json.gz", ".jsonl.gz"))
    if structured and kind != "documents":
        yield from structured_records(path)
        return
    if suffix in TEXT_EXTENSIONS:
        yield path.read_text(encoding="utf-8-sig"), {"source": "document", "filename": path.name}


def source_files(source: Path):
    if source.is_dir():
        yield from (item for item in sorted(source.rglob("*"))
                    if item.is_file() and not item.is_symlink()
                    and all(not parent.is_symlink() for parent in item.parents if parent != source))
    else:
        yield source


def import_source(source: Path, kind: str, dry_run: bool = False) -> int:
    if not source.exists():
        raise RuntimeError(f"source does not exist: {source}")
    if source.suffix.lower() == ".zip":
        # No permanent copy of a whole account export (attachments included).
        with tempfile.TemporaryDirectory(prefix="rhizome-import-") as temporary, zipfile.ZipFile(source) as bundle:
            extract = Path(temporary)
            if sum(item.file_size for item in bundle.infolist()) > 2 * 1024**3:
                raise RuntimeError("zip export exceeds the 2 GiB unpacked limit; import selected files instead")
            for member in bundle.infolist():
                target = (extract / member.filename).resolve()
                if extract.resolve() not in target.parents and target != extract.resolve():
                    raise RuntimeError("unsafe path in zip export")
                if not member.is_dir() and (target.suffix.lower() in TEXT_EXTENSIONS | {".pdf", ".docx"}
                                           or target.name.lower().endswith((".json.gz", ".jsonl.gz"))):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bundle.read(member))
            return import_source(extract, kind, dry_run)
    if not dry_run:
        CORPUS.mkdir(parents=True, exist_ok=True, mode=0o700)
    count = 0
    seen = set()
    for path in source_files(source):
        for text, extra in read_document(path, kind):
            for number, piece in enumerate(chunks(text)):
                digest = hashlib.sha256(piece.encode()).hexdigest()
                origin = {"source_name": path.name, "source_type": kind,
                          **{key: value for key, value in extra.items() if key not in {"id", "text", "origins"}},
                          "chunk_id": number}
                record = {"id": digest, "text": piece, **origin, "origins": [origin]}
                destination = CORPUS / f"{digest}.json"
                if not destination.exists() and digest not in seen:
                    count += 1
                seen.add(digest)
                if dry_run:
                    continue
                if destination.exists():
                    record = json.loads(destination.read_text())
                    origins = record.setdefault("origins", [{k: v for k, v in record.items() if k not in {"id", "text", "origins"}}])
                    if origin in origins:
                        continue
                    origins.append(origin)
                temporary = destination.with_suffix(".tmp")
                temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
                temporary.chmod(0o600)
                temporary.replace(destination)
    return count


def build_index() -> int:
    import faiss
    import numpy as np
    from sentence_transformers import SentenceTransformer
    records = [json.loads(path.read_text()) for path in sorted(CORPUS.glob("*.json"))]
    # Preserve row IDs across additions: ranker adjustments refer to these IDs.
    previous = ARCHIVE.resolve()
    if (previous / "memory.index").exists():
        old_count = faiss.read_index(str(previous / "memory.index")).ntotal
        manifest_path = previous / "manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        if old_count and manifest.get("source_kind") != "rhizome-stack-owner-imports":
            raise RuntimeError("existing archive is not managed by this importer; preserve it and import into a separate stack root")
        if old_count:
            with (previous / "memory_metadata.pkl").open("rb") as stream:
                order = {row["id"]: n for n, row in enumerate(pickle.load(stream))}
            if len(order) != old_count or not order.keys() <= {item["id"] for item in records}:
                raise RuntimeError("staged corpus is missing indexed rows; restore it before rebuilding to preserve row IDs")
            records.sort(key=lambda item: (order.get(item["id"], len(order)), item["id"]))
    texts = [item["text"] for item in records]
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    model = SentenceTransformer(EMBED_MODEL, device="cpu") if texts else None
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=True) if texts else np.empty((0, 384), dtype="float32")
    index = faiss.IndexFlatIP(384)
    if len(vectors):
        index.add(np.asarray(vectors, dtype="float32"))
    # Build a complete generation before promoting it. Readers resolve archive
    # once, so index/text/metadata always come from the same generation.
    generation = Path(tempfile.mkdtemp(prefix="archive-generation-", dir=ROOT))
    faiss.write_index(index, str(generation / "memory.index"))
    np.save(generation / "memory_texts.npy", np.asarray(texts, dtype=object), allow_pickle=True)
    with (generation / "memory_metadata.pkl").open("wb") as stream:
        pickle.dump([{key: value for key, value in item.items() if key != "text"} for item in records], stream)
    (generation / "manifest.json").write_text(json.dumps({
        "schema": 1, "model": EMBED_MODEL, "dimension": 384, "count": len(records),
        "source_kind": "rhizome-stack-owner-imports",
    }, indent=2) + "\n")
    for name in ("memory_usefulness.json", "memory_manual_adjustments.json"):
        if (previous / name).exists():
            shutil.copy2(previous / name, generation / name)
    for path in generation.iterdir():
        path.chmod(0o600)
    link = ROOT / "archive.next"
    link.symlink_to(generation.name, target_is_directory=True)
    legacy_backup = None
    try:
        if ARCHIVE.exists() and not ARCHIVE.is_symlink():
            legacy_backup = ROOT / (generation.name + "-previous")
            ARCHIVE.rename(legacy_backup)
        link.replace(ARCHIVE)
    except OSError:
        if legacy_backup and not ARCHIVE.exists():
            legacy_backup.rename(ARCHIVE)
        raise
    finally:
        link.unlink(missing_ok=True)
    return len(records)


def main() -> int:
    memory_python = STACK_ROOT / "venvs/memory/bin/python"
    if memory_python.exists() and Path(sys.prefix).resolve() != memory_python.parent.parent.resolve():
        os.execv(str(memory_python), [str(memory_python), str(Path(__file__).resolve()), *sys.argv[1:]])
    parser = argparse.ArgumentParser(description="Import new-owner material; no source data is added to the distribution")
    parser.add_argument("source", nargs="?")
    parser.add_argument("--type", choices=["auto", "documents", "chatgpt", "claude", "rhizomeml"], default="auto")
    parser.add_argument("--dry-run", action="store_true", help="count new chunks without writing or downloading models")
    parser.add_argument("--no-index", action="store_true", help="stage text now; rebuild the index separately")
    parser.add_argument("--reindex", action="store_true", help="index already staged imports without importing a source")
    parser.add_argument("--build-index", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.build_index:
        print(f"indexed {build_index()} private owner chunks")
        return 0
    if not args.source and not args.reindex:
        parser.error("source is required unless --reindex is used")
    if args.reindex and (args.dry_run or args.no_index):
        parser.error("--reindex cannot be combined with --dry-run or --no-index")
    os.umask(0o077)
    if args.dry_run:
        count = import_source(Path(args.source).expanduser().resolve(), args.type, True)
        print(f"would import {count} new private chunks; no files changed")
        return 0
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (ROOT / "import.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        count = import_source(Path(args.source).expanduser().resolve(), args.type) if args.source else 0
        if args.source and count == 0 and not any(CORPUS.glob("*.json")):
            raise RuntimeError("no supported text records found; check export format or use --type documents for raw text")
        memory_python = STACK_ROOT / "venvs/memory/bin/python"
        if not args.no_index and memory_python.exists():
            subprocess.run([str(memory_python), str(Path(__file__).resolve()), "--build-index"], check=True)
            print("Index ready. Restart openclaw-gateway to load it in the running agent.")
        elif args.reindex:
            raise RuntimeError("reindex needs the optional memory component")
        elif not args.no_index:
            print("Import staged safely, but semantic indexing needs the optional memory component.")
        print(f"imported {count} new private chunks (duplicate text retains all source references)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"import failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
