#!/usr/bin/env python3
"""Single-instance, loopback-only resident GLiNER classifier."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


MAX_BODY_BYTES = 64 * 1024


@dataclass
class Work:
    request: str
    taxonomy: dict[str, Any]
    submitted: float = field(default_factory=time.monotonic)
    event: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None
    error: str | None = None
    shadow: bool = False
    request_sha256: str = ""


class State:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        gliner = config["gliner"]
        self.started = time.monotonic()
        self.ready = False
        self.load_ms: float | None = None
        self.load_error: str | None = None
        self.active = False
        self.completed = 0
        self.skipped_full = 0
        self.jobs: queue.Queue[Work | None] = queue.Queue(maxsize=int(gliner.get("queue_capacity", 4)))
        self.results_path = Path(str(gliner.get("shadow_results_path", Path.home() / ".local/state/rhizome-stack/gliner-shadow.jsonl")))
        self.model: Any = None
        self.tokenizer: Any = None
        self.encoder_limit = 0
        self.model_revision: str | None = None

    def load(self) -> None:
        from gliner2 import AutoExtractor

        gliner = self.config["gliner"]
        model_path = Path(str(gliner["model_path"])).resolve()
        started = time.monotonic()
        self.model = AutoExtractor.from_pretrained(str(model_path), local_files_only=True)
        self.model.to(str(gliner.get("device", "cpu")))
        self.model.eval()
        self.tokenizer = self.model.processor.tokenizer
        encoder_config = json.loads((model_path / "encoder_config/config.json").read_text(encoding="utf-8"))
        self.encoder_limit = int(getattr(self.model.config, "max_len", 0) or encoder_config.get("max_position_embeddings", 0) or 0)
        revision_file = model_path / "RHIZOME_MODEL_REVISION"
        if revision_file.is_file():
            self.model_revision = revision_file.read_text(encoding="utf-8").strip()
        self.load_ms = round((time.monotonic() - started) * 1000, 1)
        self.ready = True

    def classify(self, work: Work) -> dict[str, Any]:
        tokens = len(self.tokenizer(work.request, add_special_tokens=False)["input_ids"])
        if self.encoder_limit and tokens >= self.encoder_limit:
            raise ValueError(f"request alone is too large for encoder ({tokens} >= {self.encoder_limit} tokens)")
        started = time.monotonic()
        classification = self.model.classify_text(
            work.request, work.taxonomy, include_confidence=True, max_len=None,
        )
        inference_ms = round((time.monotonic() - started) * 1000, 1)
        memory: dict[str, Any] = {}
        if str(self.config["gliner"].get("device")) == "cuda":
            import torch
            memory = {
                "allocated_mib": round(torch.cuda.memory_allocated() / 1024 / 1024, 1),
                "reserved_mib": round(torch.cuda.memory_reserved() / 1024 / 1024, 1),
            }
        return {
            "classification": classification,
            "metrics": {
                "queue_ms": round((started - work.submitted) * 1000, 1),
                "warm_inference_ms": inference_ms,
                "checkpoint_load_ms": self.load_ms,
                "request_tokens": tokens,
                "input_limit_tokens": self.encoder_limit or None,
                "model_revision": self.model_revision,
                "device": str(self.config["gliner"].get("device")),
                "cuda_memory": memory,
                "scores_are_calibrated_probabilities": False,
            },
        }

    def record_shadow(self, work: Work) -> None:
        record = {
            "timestamp": time.time(), "request_sha256": work.request_sha256,
            "result": work.result, "error": work.error,
        }
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        with self.results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def worker(self) -> None:
        while True:
            work = self.jobs.get()
            if work is None:
                self.jobs.task_done()
                return
            self.active = True
            try:
                work.result = self.classify(work)
            except Exception as exc:  # receipt boundary; server stays available
                work.error = f"{type(exc).__name__}: {exc}"
            finally:
                self.active = False
                self.completed += 1
                if work.shadow:
                    self.record_shadow(work)
                work.event.set()
                self.jobs.task_done()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], state: State) -> None:
        super().__init__(address, Handler)
        self.state = state


class Handler(BaseHTTPRequestHandler):
    server: Server

    def reply(self, status: int, value: dict[str, Any]) -> None:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        state = self.server.state
        if self.path != "/health":
            self.reply(404, {"error": "not_found"})
            return
        self.reply(200 if state.ready else 503, {
            "ready": state.ready, "load_error": state.load_error,
            "process_startup_ms": round((time.monotonic() - state.started) * 1000, 1),
            "checkpoint_load_ms": state.load_ms, "queue_depth": state.jobs.qsize(),
            "queue_capacity": state.jobs.maxsize, "active": state.active,
            "completed": state.completed, "skipped_queue_full": state.skipped_full,
        })

    def do_POST(self) -> None:
        if self.path not in {"/classify", "/shadow"}:
            self.reply(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if self.headers.get("Transfer-Encoding") or not 0 < length <= MAX_BODY_BYTES:
                raise ValueError("invalid request size or transfer encoding")
            payload = json.loads(self.rfile.read(length))
            request = payload["request"]
            taxonomy = payload["taxonomy"]
            if not isinstance(request, str) or not request.strip() or not isinstance(taxonomy, dict):
                raise ValueError("invalid request or taxonomy")
            max_chars = int(self.server.state.config["gliner"].get("max_request_chars", 4000))
            if len(request) > max_chars:
                raise ValueError(f"request exceeds {max_chars} characters")
            queue_wait = float(payload.get("queue_wait_seconds", 0.05))
            deadline = float(payload.get("deadline_seconds", 5.0))
            if not math.isfinite(queue_wait) or not math.isfinite(deadline):
                raise ValueError("queue wait and deadline must be finite numbers")
            queue_wait = max(0.0, min(queue_wait, 1.0))
            deadline = max(0.01, min(deadline, 30.0))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            self.reply(400, {"error": str(exc)})
            return
        shadow = self.path == "/shadow"
        work = Work(request=request, taxonomy=taxonomy, shadow=shadow,
                    request_sha256=hashlib.sha256(request.encode()).hexdigest())
        try:
            self.server.state.jobs.put(work, timeout=queue_wait)
        except queue.Full:
            self.server.state.skipped_full += 1
            self.reply(429, {"accepted": False, "reason": "queue_full"})
            return
        if shadow:
            self.reply(202, {"accepted": True, "state": "queued", "request_sha256": work.request_sha256})
            return
        if not work.event.wait(deadline):
            self.reply(504, {"error": "deadline_exceeded", "execution_state": "unknown",
                             "underlying_may_continue": True})
            return
        if work.error:
            self.reply(500, {"error": work.error})
            return
        self.reply(200, work.result or {"error": "missing_result"})

    def log_message(self, *_args: Any) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    gliner = config["gliner"]
    if not gliner.get("resident_enabled", False):
        raise SystemExit("resident GLiNER is not explicitly enabled")
    device = str(gliner.get("device", "cpu"))
    if device not in {"cpu", "cuda"}:
        raise SystemExit("resident GLiNER device must be cpu or cuda")
    os.environ["CUDA_VISIBLE_DEVICES"] = (
        "" if device == "cpu" else str(gliner.get("cuda_visible_devices", "0"))
    )
    host = str(gliner.get("resident_host", "127.0.0.1"))
    if host != "127.0.0.1":
        raise SystemExit("resident GLiNER must bind to 127.0.0.1")
    lock_path = Path(f"/tmp/rhizome-gliner-resident-{os.getuid()}.lock")
    lock = lock_path.open("w", encoding="utf-8")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("resident GLiNER already owns the process lock")
    state = State(config)
    try:
        state.load()
    except Exception as exc:
        state.load_error = f"{type(exc).__name__}: {exc}"
        raise
    threading.Thread(target=state.worker, name="gliner-worker", daemon=True).start()
    server = Server((host, int(gliner.get("resident_port", 17641))), state)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        state.jobs.put(None)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
