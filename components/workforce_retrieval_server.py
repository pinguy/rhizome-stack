#!/usr/bin/env python3
"""Loopback-only, CPU-only MiniLM retrieval for optional workforce support."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np
from sentence_transformers import SentenceTransformer


MAX_BODY_BYTES = 64 * 1024


def stable_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


class RetrievalIndex:
    def __init__(self, config_path: Path):
        cfg = json.loads(config_path.read_text(encoding="utf-8"))["retrieval"]
        self.cfg = cfg
        self.model_path = Path(os.path.expanduser(cfg["model_path"])).resolve()
        self.model_revision = str(cfg["model_revision"])
        if self.model_path.name != self.model_revision:
            raise ValueError("MiniLM snapshot path and configured revision differ")
        self.threads = int(cfg.get("threads", 4))
        import torch
        torch.set_num_threads(self.threads)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
        self.model = SentenceTransformer(str(self.model_path), device="cpu", local_files_only=True)
        self.model.max_seq_length = min(int(cfg.get("max_input_tokens", 256)), self.model.max_seq_length)
        if str(self.model.device) != "cpu" or any(p.device.type != "cpu" for p in self.model.parameters()):
            raise RuntimeError("MiniLM escaped CPU placement")
        self.dimension = int(self.model.get_sentence_embedding_dimension())
        self.corpus_path = Path(os.path.expanduser(cfg["corpus_path"]))
        self.cache_dir = Path(os.path.expanduser(cfg["index_dir"]))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.reload()

    def _load_entries(self) -> list[dict[str, Any]]:
        required = {"id", "kind", "title", "content", "provenance", "source_version", "task_tags", "verification"}
        entries, seen = [], set()
        for number, line in enumerate(self.corpus_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            item = json.loads(line)
            if not required <= set(item) or item["id"] in seen:
                raise ValueError(f"invalid or duplicate corpus record at line {number}")
            if item["kind"] not in {"procedure", "example", "fact"} or item["verification"] != "verified":
                raise ValueError(f"untrusted corpus record at line {number}")
            seen.add(item["id"])
            entries.append(item)
        return entries

    def reload(self) -> dict[str, Any]:
        source = self.corpus_path.read_bytes()
        entries = self._load_entries()
        fingerprint = hashlib.sha256(stable_json({
            "model": self.model_revision,
            "normalization": "l2",
            "metric": "inner_product",
            "max_input_tokens": self.model.max_seq_length,
            "entries": entries,
        })).hexdigest()
        vector_path = self.cache_dir / f"{fingerprint}.npy"
        if vector_path.is_file():
            vectors = np.load(vector_path, allow_pickle=False)
        else:
            texts = [f"{x['title']}\n{x['content']}\nTags: {' '.join(x['task_tags'])}" for x in entries]
            vectors = self.model.encode(texts, convert_to_numpy=True, normalize_embeddings=True,
                                        batch_size=16, show_progress_bar=False).astype("float32")
            np.save(vector_path, vectors, allow_pickle=False)
        if vectors.shape != (len(entries), self.dimension):
            raise ValueError("cached vectors are incompatible with configured MiniLM")
        self.entries, self.vectors, self.corpus_version = entries, vectors, fingerprint
        self.corpus_source_sha256 = hashlib.sha256(source).hexdigest()
        for old in self.cache_dir.glob("*.npy"):
            if old != vector_path:
                old.unlink()
        self.cache.clear()
        return self.info()

    def info(self) -> dict[str, Any]:
        return {
            "model_revision": self.model_revision,
            "device": "cpu",
            "dimension": self.dimension,
            "normalization": "l2",
            "similarity_metric": "inner_product_cosine",
            "max_input_tokens": self.model.max_seq_length,
            "corpus_version": self.corpus_version,
            "entries": len(self.entries),
            "threads": self.threads,
        }

    def _segments(self, query: str) -> tuple[list[str], bool]:
        ids = self.model.tokenizer(query, add_special_tokens=False)["input_ids"]
        limit = max(16, self.model.max_seq_length - 2)
        if len(ids) <= limit:
            return [query], False
        starts = [0, max(0, len(ids) // 3 - limit // 2),
                  max(0, 2 * len(ids) // 3 - limit // 2), len(ids) - limit]
        segments, seen = [], set()
        for start in starts:
            piece = self.model.tokenizer.decode(ids[start:start + limit], skip_special_tokens=True)
            if piece not in seen:
                seen.add(piece)
                segments.append(piece)
        return segments, True

    def search(self, request: dict[str, Any]) -> dict[str, Any]:
        query = request.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be non-empty")
        if len(query.encode()) > MAX_BODY_BYTES:
            raise ValueError("query exceeds 64 KiB")
        deadline = float(request.get("deadline_seconds", 2.0))
        if deadline <= 0:
            raise TimeoutError("retrieval deadline expired")
        if hashlib.sha256(self.corpus_path.read_bytes()).hexdigest() != self.corpus_source_sha256:
            raise RuntimeError("corpus changed; explicit reload required")
        key = hashlib.sha256(stable_json({"model": self.model_revision, "query": query,
                                          "corpus": self.corpus_version})).hexdigest()
        now = time.monotonic()
        cached = self.cache.get(key)
        if cached and now - cached[0] <= float(self.cfg.get("cache_ttl_seconds", 300)):
            result = dict(cached[1])
            result["cache_hit"] = True
            return result
        started = time.monotonic()
        segments, segmented = self._segments(query)
        with self.lock:
            qv = self.model.encode(segments, convert_to_numpy=True, normalize_embeddings=True,
                                   batch_size=len(segments), show_progress_bar=False).astype("float32")
        embed_ms = (time.monotonic() - started) * 1000
        if time.monotonic() - started > deadline:
            raise TimeoutError("retrieval deadline expired after embedding")
        scores = (qv @ self.vectors.T).max(axis=0)
        ordering = sorted(range(len(self.entries)), key=lambda i: float(scores[i]), reverse=True)
        candidates = []
        for rank, i in enumerate(ordering[:int(self.cfg.get("candidate_k", 8))], 1):
            item = self.entries[i]
            candidates.append({**item, "semantic_similarity": round(float(scores[i]), 6),
                               "lexical_score": 0.0, "rank": rank})
        result = {
            "ok": True,
            "candidates": candidates,
            "query_segmented": segmented,
            "query_segments": len(segments),
            "cache_hit": False,
            "cache_key": key,
            "retrieval_mode": "minilm",
            "timings_ms": {"embedding": round(embed_ms, 2),
                           "total": round((time.monotonic() - started) * 1000, 2)},
            "index": self.info(),
        }
        self.cache[key] = (now, result)
        return result


def make_handler(index: RetrievalIndex, capacity: threading.BoundedSemaphore):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def send_json(self, status: int, value: dict[str, Any]):
            raw = stable_json(value)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/health":
                self.send_json(200, {"ok": True, "index": index.info()})
            else:
                self.send_json(404, {"error": "not found"})

        def do_POST(self):
            if self.path not in {"/search", "/reload"}:
                self.send_json(404, {"error": "not found"})
                return
            if not capacity.acquire(blocking=False):
                self.send_json(429, {"error": "retrieval queue full"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.headers.get("Transfer-Encoding") or not 0 <= length <= MAX_BODY_BYTES:
                    raise ValueError("request requires Content-Length between 0 and 64 KiB")
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")
                value = index.reload() if self.path == "/reload" else index.search(body)
                self.send_json(200, {"ok": True, "index": value} if self.path == "/reload" else value)
            except TimeoutError as exc:
                self.send_json(504, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self.send_json(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            finally:
                capacity.release()
    return Handler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))["retrieval"]
    if cfg.get("host", "127.0.0.1") != "127.0.0.1":
        raise SystemExit("retrieval service must bind to 127.0.0.1")
    index = RetrievalIndex(args.config)
    server = ThreadingHTTPServer(("127.0.0.1", int(cfg.get("port", 17642))),
                                 make_handler(index, threading.BoundedSemaphore(int(cfg.get("queue_capacity", 2)))))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
