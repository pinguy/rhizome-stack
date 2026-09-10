#!/usr/bin/env python3
"""RhizomeML FAISS recall server (stdin/stdout JSONL).

Protocol (one JSON per line):
- {"type":"search","query":"...","k":10,"snippetMaxChars":700}
  -> {"ok":true,"results":[{"idx":123,"score":0.81,"snippet":"...","meta":{...}}, ...]}

- {"type":"get","idx":123}
  -> {"ok":true,"idx":123,"text":"...","meta":{...}}

This is designed to be spawned once and kept alive by the OpenClaw plugin.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
import time
import traceback

# Apply limits before NumPy, FAISS, PyTorch, or BLAS initialise their pools.
os.environ.setdefault("MALLOC_ARENA_MAX", "2")
os.environ.setdefault("MALLOC_TRIM_THRESHOLD_", "131072")
os.environ.setdefault("MALLOC_MMAP_THRESHOLD_", "131072")
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "4")

import numpy as np

# These are expected to exist in ${HOME}/.venv
import faiss  # type: ignore
from sentence_transformers import SentenceTransformer  # type: ignore


def eprint(*a):
    print(*a, file=sys.stderr, flush=True)


def main():
    base_dir = os.environ.get("RHIZOME_BASE_DIR", os.path.expanduser("~/.local/share/rhizome-stack/memory/archive"))
    index_path = os.environ.get("RHIZOME_INDEX", os.path.join(base_dir, "memory.index"))
    texts_path = os.environ.get("RHIZOME_TEXTS", os.path.join(base_dir, "memory_texts.npy"))
    meta_path = os.environ.get("RHIZOME_META", os.path.join(base_dir, "memory_metadata.pkl"))
    snapshot_dir = os.path.realpath(base_dir)
    def snapshot_path(value):
        return os.path.join(snapshot_dir, os.path.basename(value)) if os.path.dirname(value) == base_dir else value
    index_path, texts_path, meta_path = map(snapshot_path, (index_path, texts_path, meta_path))
    model_name = os.environ.get("RHIZOME_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    device = os.environ.get("RHIZOME_DEVICE", "cpu")
    usefulness_state_path = os.environ.get(
        "RHIZOME_USEFULNESS_STATE",
        os.path.join(base_dir, "memory_usefulness.json"),
    )
    manual_adjustments_path = os.environ.get(
        "RHIZOME_MANUAL_ADJUSTMENTS",
        os.path.join(base_dir, "memory_manual_adjustments.json"),
    )
    alpha = float(os.environ.get("RHIZOME_WEIGHT_RETRIEVALS", "0.05"))
    beta = float(os.environ.get("RHIZOME_WEIGHT_RECENCY", "0.05"))
    gamma = float(os.environ.get("RHIZOME_WEIGHT_SEMANTIC", "0.85"))
    delta = float(os.environ.get("RHIZOME_WEIGHT_MANUAL", "0.05"))
    lexical_share = max(
        0.0,
        min(1.0, float(os.environ.get("RHIZOME_LEXICAL_SHARE", "0.25"))),
    )
    recency_half_life_days = max(
        1.0, float(os.environ.get("RHIZOME_RECENCY_HALF_LIFE_DAYS", "120"))
    )
    frequency_saturation_retrievals = max(
        1, int(os.environ.get("RHIZOME_FREQUENCY_SATURATION_RETRIEVALS", "20"))
    )
    weight_total = alpha + beta + gamma + delta
    if weight_total <= 0:
        raise ValueError("usefulness weights must sum to a positive number")

    faiss.omp_set_num_threads(max(1, int(os.environ.get("OMP_NUM_THREADS", "4"))))

    # Load big assets once
    index = faiss.read_index(index_path)
    texts = np.load(texts_path, allow_pickle=True)

    # metadata is a pickle list[dict]
    import pickle

    with open(meta_path, "rb") as f:
        meta = pickle.load(f)

    if index.ntotal != len(texts) or len(texts) != len(meta):
        raise ValueError(f"memory count mismatch: index={index.ntotal}, texts={len(texts)}, metadata={len(meta)}")
    manifest_path = os.path.join(snapshot_dir, "manifest.json")
    if os.path.isfile(manifest_path):
        with open(manifest_path) as stream:
            archive_model = json.load(stream).get("model")
        if archive_model and archive_model != model_name:
            raise ValueError(f"memory embedding model mismatch: archive={archive_model}, configured={model_name}")

    # Determine device
    st_device = device
    if device == "auto":
        # A single MiniLM query is faster and dramatically leaner without loading
        # the CUDA runtime into this long-lived helper.
        st_device = "cpu"

    embedder = SentenceTransformer(model_name, device=st_device)
    try:
        import torch

        torch.set_num_threads(max(1, int(os.environ.get("OMP_NUM_THREADS", "4"))))
        torch.set_num_interop_threads(1)
    except (ImportError, RuntimeError):
        pass

    # Determine metric/scoring
    metric = getattr(index, "metric_type", None)
    is_ip = metric == faiss.METRIC_INNER_PRODUCT

    def dist_to_score(d: float) -> float:
        # For L2: smaller is better. For IP: bigger is better.
        if is_ip:
            # IP similarities can be >1 depending on normalization; clamp a bit
            return float(d)
        return float(1.0 / (1.0 + d))

    def make_snippet(s: str, max_chars: int) -> str:
        s = " ".join(str(s).split())
        if len(s) <= max_chars:
            return s
        return s[: max_chars - 1] + "…"

    def content_signature(s: str) -> frozenset[str]:
        """Token signature for repeated boilerplate that may have citation prefixes."""
        words = re.findall(r"\w+", str(s).casefold())[:96]
        return frozenset(words)

    stopwords = frozenset(
        {
            "a", "an", "and", "are", "as", "at", "be", "been", "but", "by",
            "did", "do", "does", "for", "from", "had", "has", "have", "how",
            "i", "if", "in", "is", "it", "its", "me", "my", "not", "of", "on",
            "or", "our", "should", "so", "that", "the", "their", "them", "there",
            "these", "they", "this", "to", "was", "we", "were", "what", "when",
            "where", "which", "who", "why", "will", "with", "you", "your",
        }
    )

    def lexical_tokens(s: str) -> set[str]:
        """Meaning-bearing tokens for exact-name/date/path recall."""
        tokens = set()
        for raw in re.findall(r"[a-z0-9]+", str(s).casefold()):
            token = re.sub(r"(?<=\d)(st|nd|rd|th)$", "", raw)
            if token not in stopwords and (len(token) > 2 or token.isdigit()):
                tokens.add(token)
        return tokens

    def lexical_score(query_tokens: set[str], text: str) -> float:
        if not query_tokens:
            return 0.0
        text_tokens = lexical_tokens(text)
        matched = query_tokens & text_tokens
        coverage = len(matched) / len(query_tokens)
        # Coverage finds exact facts; compactness stops a long rambling export
        # winning merely because it happens to mention several query terms.
        compactness = min(1.0, len(query_tokens) / max(1, len(text_tokens)))
        return min(1.0, coverage * (0.6 + 0.4 * compactness))

    def is_near_duplicate(signature: frozenset[str], seen: list[frozenset[str]]) -> bool:
        if not signature:
            return any(not prior for prior in seen)
        for prior in seen:
            union = signature | prior
            if union and len(signature & prior) / len(union) >= 0.85:
                return True
        return False

    def load_json_object(path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                value = json.load(f)
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    usefulness_state = load_json_object(usefulness_state_path)

    def save_usefulness_state() -> None:
        parent = os.path.dirname(usefulness_state_path) or "."
        os.makedirs(parent, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".memory_usefulness.", suffix=".json", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(usefulness_state, f, sort_keys=True, separators=(",", ":"))
                f.write("\n")
            os.replace(tmp_path, usefulness_state_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def timestamp_from_meta(m: dict) -> float | None:
        for key in ("timestamp", "updated_at", "created_at"):
            try:
                ts = float(m.get(key))
            except (TypeError, ValueError):
                continue
            if math.isfinite(ts) and ts > 0:
                # Accept millisecond timestamps without requiring metadata migration.
                return ts / 1000.0 if ts > 10_000_000_000 else ts
        return None

    def usefulness_score(
        idx: int,
        vector_semantic: float,
        lexical: float,
        m: dict,
        now: float,
        manual: dict,
    ):
        entry = usefulness_state.get(str(idx), {})
        retrievals = max(0, int(entry.get("retrievals", 0)))
        frequency = min(
            1.0,
            math.log1p(retrievals) / math.log1p(frequency_saturation_retrievals),
        )

        ts = timestamp_from_meta(m)
        if ts is None:
            recency = 0.0
        else:
            age_days = max(0.0, (now - ts) / 86400.0)
            recency = math.exp(-math.log(2.0) * age_days / recency_half_life_days)

        vector_semantic = max(0.0, min(1.0, vector_semantic))
        lexical = max(0.0, min(1.0, lexical))
        # Embeddings handle paraphrase; lexical overlap protects exact names,
        # dates and paths that small sentence embeddings often blur together.
        semantic = (
            (1.0 - lexical_share) * vector_semantic
            + lexical_share * lexical
        )
        try:
            manual_value = float(manual.get(str(idx), m.get("manual_adjustment", 0.0)))
        except (TypeError, ValueError):
            manual_value = 0.0
        # Manual controls are signed: -1 suppresses, 0 is neutral, +1 boosts.
        # Keeping zero genuinely neutral avoids giving every memory a hidden
        # baseline bonus and lets a human correction outweigh popularity.
        manual_component = max(-1.0, min(1.0, manual_value))
        score = (
            alpha * frequency
            + beta * recency
            + gamma * semantic
            + delta * manual_component
        ) / weight_total
        return max(0.0, min(1.0, score)), {
            "retrievals": retrievals,
            "frequency": frequency,
            "recency": recency,
            "semantic": semantic,
            "vectorSemantic": vector_semantic,
            "lexical": lexical,
            "manual": manual_value,
        }

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            typ = req.get("type")

            if typ == "search":
                q = str(req.get("query", ""))
                k = int(req.get("k", 10))
                snippet_max = int(req.get("snippetMaxChars", 700))
                if not q:
                    out = {"ok": True, "results": []}
                    print(json.dumps(out), flush=True)
                    continue

                emb = embedder.encode([q], convert_to_numpy=True, normalize_embeddings=True)
                emb = emb.astype("float32")
                query_tokens = lexical_tokens(q)

                # Pull a broader semantic candidate set before usefulness reranking.
                # Leave enough headroom to replace repeated exports/title pages
                # with distinct memories after normalized-prefix deduplication.
                candidate_k = min(index.ntotal, max(k * 20, 200))
                D, I = index.search(emb, candidate_k)
                now = time.time()
                manual_adjustments = load_json_object(manual_adjustments_path)
                results = []
                seen_content = []
                for dist, idx in zip(D[0].tolist(), I[0].tolist()):
                    if idx < 0:
                        continue
                    try:
                        t = texts[idx]
                    except Exception:
                        t = ""
                    try:
                        m = meta[idx]
                    except Exception:
                        m = {}
                    signature = content_signature(str(t))
                    if is_near_duplicate(signature, seen_content):
                        continue
                    seen_content.append(signature)
                    vector_semantic = dist_to_score(float(dist))
                    lexical = lexical_score(query_tokens, str(t))
                    score, components = usefulness_score(
                        int(idx),
                        vector_semantic,
                        lexical,
                        m,
                        now,
                        manual_adjustments,
                    )
                    results.append(
                        {
                            "idx": int(idx),
                            "score": score,
                            "vectorScore": vector_semantic,
                            "usefulness": components,
                            "snippet": make_snippet(str(t), snippet_max),
                            "meta": m,
                        }
                    )
                results.sort(key=lambda r: (r["score"], r["vectorScore"]), reverse=True)
                results = results[:k]

                # Search results are impressions, not evidence that a memory helped.
                # Track them for diagnostics but never feed them back into ranking.
                for result in results:
                    key = str(result["idx"])
                    entry = usefulness_state.setdefault(key, {})
                    entry["impressions"] = max(0, int(entry.get("impressions", 0))) + 1
                    entry["last_impression"] = now
                save_usefulness_state()
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "results": results,
                            "ranker": {
                                "formula": "alpha*log_frequency + beta*recency + gamma*blended_semantic + delta*manual",
                                "weights": {
                                    "alpha": alpha,
                                    "beta": beta,
                                    "gamma": gamma,
                                    "delta": delta,
                                },
                                "recencyHalfLifeDays": recency_half_life_days,
                                "frequencySaturationRetrievals": frequency_saturation_retrievals,
                                "lexicalShare": lexical_share,
                            },
                        }
                    ),
                    flush=True,
                )

            elif typ == "get":
                idx = int(req.get("idx"))
                t = str(texts[idx])
                m = meta[idx] if idx < len(meta) else {}
                # An explicit full-memory fetch is a stronger signal that the
                # caller consumed the result than merely appearing in search.
                now = time.time()
                entry = usefulness_state.setdefault(str(idx), {})
                entry["retrievals"] = max(0, int(entry.get("retrievals", 0))) + 1
                entry["last_retrieved"] = now
                save_usefulness_state()
                print(json.dumps({"ok": True, "idx": idx, "text": t, "meta": m}), flush=True)

            else:
                print(json.dumps({"ok": False, "error": "unknown request type"}), flush=True)

        except Exception as e:
            print(
                json.dumps({"ok": False, "error": str(e), "trace": traceback.format_exc()}),
                flush=True,
            )


if __name__ == "__main__":
    main()
