#!/usr/bin/env python3
"""Standalone, local Qwen Image Desk backed by an owned ComfyUI process."""

from __future__ import annotations

import io
import json
import mimetypes
import os
import queue
import random
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from image_presets import DEFAULT_IMAGE_PRESET, image_preset_catalogue, resolve_image_dimensions


APP_DIR = Path(__file__).resolve().parent
STATIC = APP_DIR / "static"
STACK_ROOT = Path(os.environ.get("RHIZOME_STACK_ROOT", "~/.local/share/rhizome-stack")).expanduser()
COMFY_DIR = Path(os.environ.get("COMFY_DIR", STACK_ROOT / "creative/ComfyUI"))
COMFY_PY = Path(os.environ.get("COMFY_PY", COMFY_DIR / ".venv/bin/python"))
COMFY_OUTPUT = Path(os.environ.get("COMFY_OUTPUT", COMFY_DIR / "output"))
COMFY_INPUT = Path(os.environ.get("COMFY_INPUT", COMFY_DIR / "input"))
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
APP_HOST = os.environ.get("APP_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("APP_PORT", "8841"))
STATE_DIR = Path(os.environ.get("QWEN_DESK_STATE", STACK_ROOT / "creative/state/qwen-image-desk"))
REFERENCE_DIR = STATE_DIR / "reference-inputs"
OPENCLAW = shutil.which("openclaw") or str(Path.home() / ".npm-global/bin/openclaw")
OPENCLAW_CONFIG = Path(os.environ.get("OPENCLAW_CONFIG_PATH", Path.home() / ".openclaw/openclaw.json"))
OPENCLAW_ADAPTER = os.environ.get("OPENCLAW_API_URL", "http://127.0.0.1:18888").rstrip("/")
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
IDLE_SECONDS = max(60, int(os.environ.get("COMFY_IDLE_SECONDS", "300")))

EXPANDER_INSTRUCTION = (
    "Rewrite the user's rough idea as one precise Qwen Image prompt. Preserve the subject and intent. "
    "Add composition, lighting, material, camera and atmosphere only where useful. Do not add headings, "
    "quotes, commentary, policy language or negative prompts. Return only the final prompt."
)


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def json_request(path: str, payload=None, timeout=30) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(COMFY_URL + path, data=data,
                                     headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def adapter_json(path: str, payload=None, timeout=30) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(OPENCLAW_ADAPTER + path, data=data,
                                     headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def comfy_up() -> bool:
    try:
        json_request("/system_stats", timeout=3)
        return True
    except Exception:
        return False


class ComfyEngine:
    """Start and stop only the exact detached process recorded by this app."""

    def __init__(self):
        self.pid_file = STATE_DIR / "comfy.pid"
        self.log_file = STATE_DIR / "comfy.log"
        self.lock = threading.RLock()
        self.last_activity = time.monotonic()

    def owned_pid(self) -> int | None:
        try:
            pid = int(self.pid_file.read_text().strip())
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            main = str((COMFY_DIR / "main.py").resolve())
            if main in cmdline and "--port 8188" in cmdline and os.getpgid(pid) == pid:
                return pid
        except (OSError, ValueError, ProcessLookupError):
            pass
        return None

    def status(self) -> dict:
        online = comfy_up()
        return {"online": online, "owned": self.owned_pid() is not None}

    def start(self, wait=120) -> bool:
        with self.lock:
            if comfy_up():
                self.last_activity = time.monotonic()
                return True
            main = COMFY_DIR / "main.py"
            if not COMFY_PY.is_file() or not main.is_file():
                raise RuntimeError("ComfyUI is not installed; run the creative installer first")
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            log = self.log_file.open("ab")
            proc = subprocess.Popen(
                [str(COMFY_PY), str(main), "--listen", "127.0.0.1", "--port", "8188", "--lowvram"],
                cwd=COMFY_DIR, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True, env=dict(os.environ, CUDA_DEVICE_ORDER="PCI_BUS_ID"),
            )
            self.pid_file.write_text(str(proc.pid))
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if comfy_up():
                self.last_activity = time.monotonic()
                return True
            if proc.poll() is not None:
                break
            time.sleep(1.5)
        raise RuntimeError(f"ComfyUI did not become ready; inspect {self.log_file}")

    def stop_owned(self) -> bool:
        with self.lock:
            pid = self.owned_pid()
            if pid is None:
                return False
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            self.pid_file.unlink(missing_ok=True)
            return True

    def free_models(self) -> None:
        if comfy_up():
            try:
                json_request("/free", {"unload_models": True, "free_memory": True}, timeout=30)
            except Exception:
                pass


def reference_image(reference_id: str) -> dict:
    if not isinstance(reference_id, str) or not re.fullmatch(r"ref-[a-f0-9]{32}", reference_id):
        raise ValueError("invalid reference image")
    image = (REFERENCE_DIR / f"{reference_id}.png").resolve(strict=True)
    metadata = (REFERENCE_DIR / f"{reference_id}.json").resolve(strict=True)
    if not image.is_relative_to(REFERENCE_DIR.resolve()) or not metadata.is_relative_to(REFERENCE_DIR.resolve()):
        raise ValueError("reference image is outside the desk state directory")
    value = json.loads(metadata.read_text())
    value["absolute_path"] = str(image)
    return value


def save_reference(data: bytes, filename: str) -> dict:
    if not data or len(data) > 20 * 1024**2:
        raise ValueError("reference must be an image no larger than 20 MB")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if opened.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("reference must be PNG, JPEG or WebP")
            prepared = ImageOps.exif_transpose(opened).convert("RGB")
            if prepared.width < 64 or prepared.height < 64 or prepared.width * prepared.height > 40_000_000:
                raise ValueError("reference dimensions are unsupported")
            reference_id = "ref-" + uuid.uuid4().hex
            REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
            target = REFERENCE_DIR / f"{reference_id}.png"
            prepared.save(target, "PNG", optimize=True)
            value = {"id": reference_id, "name": Path(filename).name[:200],
                     "width": prepared.width, "height": prepared.height,
                     "media_url": f"/api/image-studio/reference/{reference_id}"}
            atomic_json(REFERENCE_DIR / f"{reference_id}.json", value)
            return value
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise ValueError("reference is not a valid supported image") from exc


def qwen_graph(prompt: str, negative: str, seed: int, width: int, height: int,
               prefix: str, reference_name: str | None = None) -> dict:
    graph = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "qwen-image-2.1-UC-Q8_0.gguf"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "cpu"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "4": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0], "prompt": prompt,
            "negative_prompt": negative or "", "resolution": max(width, height)}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {
            "width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "seed": seed, "steps": 25, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "positive": ["4", 0],
            "negative": ["4", 1], "latent_image": ["5", 0], "denoise": 1.0}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": prefix}},
    }
    if reference_name:
        graph["9"] = {"class_type": "LoadImage", "inputs": {"image": reference_name}}
        graph["10"] = {"class_type": "ImageScale", "inputs": {
            "image": ["9", 0], "upscale_method": "lanczos", "width": width,
            "height": height, "crop": "center"}}
        graph["4"]["inputs"].update({"images.image_1": ["10", 0], "resolution": 0})
        graph["6"]["inputs"]["latent_image"] = ["4", 2]
        del graph["5"]
    return graph


def openclaw_models() -> list[dict]:
    try:
        result = subprocess.run([OPENCLAW, "models", "list", "--json"], check=True,
                                capture_output=True, text=True, timeout=45)
        payload = json.loads(result.stdout[result.stdout.find("{"):])
        config = json.loads(OPENCLAW_CONFIG.read_text())
        allowed = set(config.get("agents", {}).get("defaults", {}).get("models", {}))
        models = []
        for item in payload.get("models", []):
            key = str(item.get("key") or "")
            if not key or key not in allowed or not item.get("available", False):
                continue
            local = key.startswith("ollama/")
            models.append({"id": "openclaw/" + key, "name": str(item.get("name") or key),
                           "source": "local" if local else "remote",
                           "provider": key.split("/", 1)[0], "context_length": item.get("contextWindow")})
        return sorted(models, key=lambda item: (item["source"] != "local", item["name"].lower()))
    except Exception:
        data = adapter_json("/v1/models", timeout=15)
        return [{"id": item["id"], "name": item.get("name") or item["id"], "source": "remote",
                 "provider": item["id"].removeprefix("openclaw/").split("/", 1)[0]}
                for item in data.get("data", []) if str(item.get("id", "")).startswith("openclaw/")]


def expand_prompt(model: str, prompt: str, editing: bool = False) -> dict:
    prompt = str(prompt or "").strip()
    if not prompt or len(prompt) > 8000:
        raise ValueError("Prompt must contain 1 to 8,000 characters")
    available = {item["id"]: item for item in openclaw_models()}
    selected = available.get(model)
    if not selected:
        raise ValueError("Selected OpenClaw model is unavailable")
    instruction = (
        "Rewrite this image-edit instruction clearly and concisely for Qwen Image 2.1. "
        "An existing reference image will be supplied to Qwen, but you cannot see it. "
        "Preserve exactly the requested changes. Do not invent image details or extra changes. "
        "Keep everything not mentioned unchanged. Return only the edit instruction."
        if editing else EXPANDER_INSTRUCTION
    )
    messages = [{"role": "system", "content": instruction}, {"role": "user", "content": prompt}]
    if selected["source"] == "local":
        request = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps({
            "model": model.removeprefix("openclaw/ollama/"), "stream": False, "think": False,
            "keep_alive": 0, "messages": messages, "options": {"temperature": 0.2, "num_predict": 512},
        }).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=900) as response:
            content = (json.load(response).get("message") or {}).get("content")
    else:
        result = adapter_json("/v1/chat/completions", {
            "model": model, "stream": False, "temperature": 0.2, "messages": messages,
        }, timeout=300)
        content = (((result.get("choices") or [{}])[0].get("message") or {}).get("content"))
    expanded = str(content or "").strip().strip('"')
    if not expanded:
        raise RuntimeError("OpenClaw returned an empty expanded prompt")
    return {"original_prompt": prompt, "expanded_prompt": expanded, "model": model,
            "source": selected["source"], "expanded_at": time.time()}


class JobQueue:
    def __init__(self, engine: ComfyEngine):
        self.engine = engine
        self.lock = threading.RLock()
        self.pending: queue.Queue[dict] = queue.Queue()
        self.jobs: list[dict] = []
        self.assets: list[dict] = []
        try:
            saved = json.loads((STATE_DIR / "state.json").read_text())
            self.jobs, self.assets = saved.get("jobs", []), saved.get("assets", [])
            for job in self.jobs:
                if job.get("status") in {"queued", "running"}:
                    job.update(status="failed", error="service restarted before completion")
        except (OSError, ValueError):
            pass
        threading.Thread(target=self.worker, daemon=True).start()

    def save(self):
        atomic_json(STATE_DIR / "state.json", {"jobs": self.jobs[-100:], "assets": self.assets[:100]})

    def enqueue(self, body: dict) -> list[dict]:
        width, height = resolve_image_dimensions(body.get("preset"), body.get("custom_width"), body.get("custom_height"))
        count = int(body.get("batch_count", 1))
        if count not in range(1, 5):
            raise ValueError("Variants must be between 1 and 4")
        prompt = str(body.get("final_prompt") or "").strip()
        if not prompt or len(prompt) > 16000:
            raise ValueError("Final prompt must contain 1 to 16,000 characters")
        base_seed = int(body.get("seed", random.randrange(2**53)))
        if not 0 <= base_seed <= 2**63 - 1:
            raise ValueError("Seed is outside the supported range")
        reference = reference_image(body["reference_image_id"]) if body.get("reference_image_id") else None
        created = []
        with self.lock:
            for offset in range(count):
                job = {
                    "id": "img-" + uuid.uuid4().hex[:12], "status": "queued", "stage": "queued",
                    "prompt": prompt, "original_prompt": str(body.get("original_prompt") or prompt),
                    "negative": str(body.get("negative") or ""), "expander_model": body.get("expander_model"),
                    "prompt_mode": str(body.get("prompt_mode") or "edited"), "image_preset": body.get("preset"),
                    "reference_image": reference,
                    "width": width, "height": height, "seed": base_seed + offset, "created_at": time.time(),
                }
                self.jobs.append(job)
                self.pending.put(job)
                created.append(dict(job))
            self.save()
        return created

    def update(self, job: dict, **values):
        with self.lock:
            job.update(values)
            self.save()

    def worker(self):
        while True:
            job = self.pending.get()
            self.update(job, status="running", stage="starting engine", started_at=time.time())
            copied_reference = None
            try:
                self.engine.start()
                self.engine.free_models()
                prefix = f"qwen-image-desk/{job['id']}"
                reference = job.get("reference_image")
                if reference:
                    source_reference = Path(reference["absolute_path"]).resolve(strict=True)
                    if not source_reference.is_relative_to(REFERENCE_DIR.resolve()):
                        raise ValueError("reference image is outside the desk state directory")
                    COMFY_INPUT.mkdir(parents=True, exist_ok=True)
                    copied_reference = f"qwen-image-desk-{job['id']}.png"
                    shutil.copy2(source_reference, COMFY_INPUT / copied_reference)
                    self.update(job, stage="encoding reference and edit prompt")
                graph = qwen_graph(job["prompt"], job["negative"], job["seed"],
                                   job["width"], job["height"], prefix, copied_reference)
                response = json_request("/prompt", {"prompt": graph, "client_id": "qwen-image-desk"}, timeout=30)
                prompt_id = response.get("prompt_id")
                if not prompt_id:
                    raise RuntimeError("ComfyUI rejected prompt: " + json.dumps(response))
                self.update(job, stage="sampling", prompt_id=prompt_id)
                deadline = time.monotonic() + 3600
                history = None
                while time.monotonic() < deadline:
                    time.sleep(2)
                    history = json_request(f"/history/{prompt_id}", timeout=15).get(prompt_id)
                    if history:
                        status = (history.get("status") or {}).get("status_str")
                        if status == "success":
                            break
                        if status == "error":
                            raise RuntimeError("ComfyUI generation failed")
                else:
                    raise TimeoutError("image generation exceeded one hour")
                image = next((item for output in history.get("outputs", {}).values()
                              for item in output.get("images", []) if item.get("type") == "output"), None)
                if not image:
                    raise FileNotFoundError("ComfyUI completed without an output image")
                relative = Path(image.get("subfolder", "")) / image["filename"]
                source = (COMFY_OUTPUT / relative).resolve(strict=True)
                if not source.is_relative_to(COMFY_OUTPUT.resolve()):
                    raise ValueError("ComfyUI returned an unsafe output path")
                asset = {
                    "id": "asset-" + uuid.uuid4().hex[:12], "prompt": job["prompt"],
                    "original_prompt": job["original_prompt"], "expanded_prompt": job["prompt"],
                    "negative": job["negative"], "expander_model": job["expander_model"],
                    "prompt_mode": job["prompt_mode"], "image_preset": job["image_preset"],
                    "reference_image": job.get("reference_image"),
                    "generation_mode": "edit" if job.get("reference_image") else "text-to-image",
                    "seed": job["seed"], "width": job["width"], "height": job["height"],
                    "steps": 25, "cfg": 1.0, "model": "Qwen Image 2.1 Uncensored",
                    "quant": "Q8_0 GGUF", "created_at": time.time(), "relative_path": str(relative),
                }
                with self.lock:
                    self.assets.insert(0, asset)
                self.update(job, status="complete", stage="finished", asset_id=asset["id"], finished_at=time.time())
            except Exception as exc:
                self.update(job, status="failed", stage="failed", error=f"{type(exc).__name__}: {exc}")
            finally:
                if copied_reference:
                    (COMFY_INPUT / copied_reference).unlink(missing_ok=True)
                self.engine.last_activity = time.monotonic()
                self.pending.task_done()

    def snapshot(self) -> dict:
        with self.lock:
            assets = []
            for item in self.assets:
                asset = dict(item)
                path = (COMFY_OUTPUT / asset["relative_path"]).resolve()
                asset["absolute_path"] = str(path)
                asset["media_url"] = "/media/" + urllib.parse.quote(asset["relative_path"])
                assets.append(asset)
            return {"jobs": [dict(job) for job in self.jobs[-100:]], "assets": assets}


ENGINE = ComfyEngine()
JOBS = JobQueue(ENGINE)


def idle_watchdog():
    while True:
        time.sleep(15)
        active = any(job.get("status") in {"queued", "running"} for job in JOBS.jobs)
        if not active and time.monotonic() - ENGINE.last_activity >= IDLE_SECONDS:
            ENGINE.stop_owned()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if self.headers.get("Transfer-Encoding") or not 0 <= length <= 128 * 1024:
            raise ValueError("request requires Content-Length between 0 and 128 KiB")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def send_json(self, status: int, value: object):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_file(self, path: Path):
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path in {"/", "/image-studio", "/image-studio/"}:
                return self.send_file(STATIC / "index.html")
            if parsed.path == "/api/image-studio/models":
                return self.send_json(200, {"models": openclaw_models()})
            if parsed.path == "/api/image-studio/health":
                state = JOBS.snapshot()
                active = any(job.get("status") in {"queued", "running"} for job in state["jobs"])
                return self.send_json(200, {"ok": True, "busy": active, **state,
                                            "engine": ENGINE.status()})
            if parsed.path.startswith("/api/image-studio/reference/"):
                reference_id = parsed.path.rsplit("/", 1)[-1]
                return self.send_file(Path(reference_image(reference_id)["absolute_path"]))
            if parsed.path == "/api/image-studio/state":
                state = JOBS.snapshot()
                try:
                    models = openclaw_models()
                    openclaw = {"online": bool(models), "models": len(models),
                                "local": sum(item["source"] == "local" for item in models)}
                except Exception as exc:
                    openclaw = {"online": False, "models": 0, "local": 0, "error": str(exc)}
                return self.send_json(200, {**state, "queue": {"engine": ENGINE.status()},
                                            "openclaw": openclaw, "presets": image_preset_catalogue(),
                                            "default_preset": DEFAULT_IMAGE_PRESET})
            if parsed.path.startswith("/image-studio/static/"):
                name = Path(parsed.path).name
                if name not in {"app.css", "app.js", "icon.svg"}:
                    raise FileNotFoundError
                return self.send_file(STATIC / name)
            if parsed.path == "/image-studio/manifest.webmanifest":
                return self.send_file(STATIC / "manifest.webmanifest")
            if parsed.path == "/image-studio/sw.js":
                return self.send_file(STATIC / "sw.js")
            if parsed.path.startswith("/media/"):
                relative = Path(urllib.parse.unquote(parsed.path.removeprefix("/media/")))
                target = (COMFY_OUTPUT / relative).resolve(strict=True)
                if relative.is_absolute() or not target.is_relative_to(COMFY_OUTPUT.resolve()):
                    raise ValueError("unsafe media path")
                return self.send_file(target)
            self.send_json(404, {"error": "not found"})
        except Exception as exc:
            self.send_json(404, {"error": f"{type(exc).__name__}: {exc}"})

    def do_POST(self):
        try:
            if self.path == "/api/image-studio/expand":
                body = self.json_body()
                return self.send_json(200, expand_prompt(str(body.get("model") or ""), body.get("prompt"),
                                                         bool(body.get("editing"))))
            if self.path == "/api/image-studio/generate":
                return self.send_json(202, {"jobs": JOBS.enqueue(self.json_body())})
            if self.path == "/api/image-studio/reference":
                length = int(self.headers.get("Content-Length", "0"))
                if self.headers.get("Transfer-Encoding") or not 0 < length <= 20 * 1024**2:
                    raise ValueError("reference requires Content-Length between 1 byte and 20 MB")
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError("incomplete reference upload")
                filename = urllib.parse.unquote(self.headers.get("X-Filename") or "reference.png")
                return self.send_json(201, save_reference(raw, filename))
            if self.path == "/api/image-studio/engine/stop":
                if any(job.get("status") in {"queued", "running"} for job in JOBS.jobs):
                    return self.send_json(409, {"error": "An image job is still active"})
                ENGINE.free_models()
                stopped = ENGINE.stop_owned()
                return self.send_json(200, {"stopped": stopped, "engine": ENGINE.status()})
            if self.path == "/api/image-studio/show-output":
                target = Path(str(self.json_body().get("path") or "")).resolve(strict=True)
                if not target.is_file() or not target.is_relative_to(COMFY_OUTPUT.resolve()):
                    raise ValueError("output is outside the creative output directory")
                subprocess.Popen(["xdg-open", str(target.parent)], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                return self.send_json(200, {"shown": True, "selected": False, "method": "xdg-open"})
            self.send_json(404, {"error": "not found"})
        except Exception as exc:
            self.send_json(400, {"error": f"{type(exc).__name__}: {exc}"})


def main() -> int:
    if APP_HOST != "127.0.0.1":
        raise SystemExit("Qwen Image Desk must bind to 127.0.0.1")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=idle_watchdog, daemon=True).start()
    print(f"Qwen Image Desk -> http://{APP_HOST}:{APP_PORT}/image-studio/")
    ThreadingHTTPServer((APP_HOST, APP_PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
