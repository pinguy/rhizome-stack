#!/usr/bin/env python3
"""Portable standalone WAN Video Desk backed by one owned ComfyUI process."""

from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from local_http_security import LocalRequestHandler, adapter_headers

from PIL import Image, ImageOps, UnidentifiedImageError

from engine import (
    GenerationQueue,
    WAN_BACKEND,
    WAN_CLIP_VISION,
    WAN_FPS,
    WAN_FPS_OPTIONS,
    WAN_I2V_MODEL,
    WAN_MAX_SECONDS,
    WAN_MAX_STEPS,
    WAN_MIN_STEPS,
    WAN_MODEL_MODES,
    WAN_TEXT_ENCODER,
    WAN_T2V_MODEL,
    WAN_VAE,
    atomic_json,
)


APP_DIR = Path(__file__).resolve().parent
STATIC = APP_DIR / "static"
STACK_ROOT = Path(os.environ.get("RHIZOME_STACK_ROOT", "~/.local/share/rhizome-stack")).expanduser()
COMFY_DIR = Path(os.environ.get("COMFY_DIR", STACK_ROOT / "creative/ComfyUI"))
ROOT = Path(os.environ.get("WAN_DESK_STATE", STACK_ROOT / "creative/state/wan-video-desk"))
PROJECTS = ROOT / "projects"
HOST = os.environ.get("APP_HOST", "127.0.0.1")
PORT = int(os.environ.get("APP_PORT", "8840"))
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OPENCLAW_ADAPTER = os.environ.get("OPENCLAW_API_URL", "http://127.0.0.1:18888").rstrip("/")
OPENCLAW_BIN = shutil.which("openclaw") or str(Path.home() / ".npm-global/bin/openclaw")
OPENCLAW_CONFIG = Path(os.environ.get("OPENCLAW_CONFIG_PATH", Path.home() / ".openclaw/openclaw.json"))
VIDEO_PROJECT_ID = "wan-video-studio"
VIDEO_FORMATS = {
    "480p": {"16:9": (832, 480), "4:3": (640, 480), "mobile": (480, 832)},
    "720p": {"16:9": (1280, 720), "4:3": (960, 720), "mobile": (720, 1280)},
}
WAN_MODEL_FILES = {
    WAN_T2V_MODEL: COMFY_DIR / "models/diffusion_models" / WAN_T2V_MODEL,
    WAN_I2V_MODEL: COMFY_DIR / "models/diffusion_models" / WAN_I2V_MODEL,
}
WAN_COMMON_FILES = (
    COMFY_DIR / "models/text_encoders" / WAN_TEXT_ENCODER,
    COMFY_DIR / "models/vae" / WAN_VAE,
)
WAN_CLIP_FILE = COMFY_DIR / "models/clip_vision" / WAN_CLIP_VISION
_MODELS_CACHE: tuple[float, list[dict]] = (0.0, [])
_MODELS_LOCK = threading.Lock()

for directory in (PROJECTS, ROOT / "state", ROOT / "logs"):
    directory.mkdir(parents=True, exist_ok=True)


def now() -> float:
    return time.time()


def project_dir() -> Path:
    return PROJECTS / VIDEO_PROJECT_ID


def load_project(_: str = VIDEO_PROJECT_ID) -> dict:
    return json.loads((project_dir() / "project.json").read_text())


def save_project(project: dict) -> None:
    if project.get("id") != VIDEO_PROJECT_ID:
        raise ValueError("invalid WAN Video Desk project")
    revision = 0
    try:
        revision = int(load_project().get("revision", 0))
    except Exception:
        pass
    project["updated_at"] = now()
    project["revision"] = max(revision, int(project.get("revision", 0))) + 1
    atomic_json(project_dir() / "project.json", project)


def ensure_project() -> dict:
    path = project_dir() / "project.json"
    if path.is_file():
        return load_project()
    for subdirectory in ("generated", "reference_inputs"):
        (project_dir() / subdirectory).mkdir(parents=True, exist_ok=True)
    created = now()
    project = {
        "schema": "wan-video-studio.project/v1",
        "id": VIDEO_PROJECT_ID,
        "kind": "video-studio",
        "name": "WAN Video Desk",
        "created_at": created,
        "updated_at": created,
        "revision": 1,
        "assets": [],
        "shots": [{
            "id": "shot-video-desk", "number": 1, "start": 0, "end": 5,
            "duration": 5, "section": "standalone", "mode": "t2v",
            "backend": WAN_BACKEND, "prompt": "", "negative": "",
            "frames": 81, "seed": 420251006, "takes": [], "selected_take_id": None,
        }],
        "timeline": {"items": [], "titles": []},
        "settings": {"video_backend": WAN_BACKEND, "fps": WAN_FPS},
    }
    atomic_json(path, project)
    return project


def adapter_json(path: str, payload=None, timeout=30) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        OPENCLAW_ADAPTER + path,
        data=data,
        headers=adapter_headers(),
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def openclaw_models() -> list[dict]:
    global _MODELS_CACHE
    with _MODELS_LOCK:
        cached_at, cached = _MODELS_CACHE
        if cached and time.monotonic() - cached_at < 60:
            return [dict(item) for item in cached]
        try:
            result = subprocess.run(
                [OPENCLAW_BIN, "models", "list", "--json"], check=True,
                capture_output=True, text=True, timeout=45,
            )
            payload = json.loads(result.stdout[result.stdout.find("{"):])
            config = json.loads(OPENCLAW_CONFIG.read_text())
            allowed = set(config.get("agents", {}).get("defaults", {}).get("models", {}))
            models = []
            for item in payload.get("models", []):
                key = str(item.get("key") or "")
                if not key or key not in allowed or not item.get("available", False):
                    continue
                local = key.startswith("ollama/")
                models.append({
                    "id": "openclaw/" + key,
                    "name": str(item.get("name") or key.removeprefix("ollama/")),
                    "source": "local" if local else "remote",
                    "provider": key.split("/", 1)[0],
                    "context_length": item.get("contextWindow"),
                })
            models.sort(key=lambda item: (item["source"] != "local", item["name"].lower()))
            _MODELS_CACHE = (time.monotonic(), models)
            return [dict(item) for item in models]
        except Exception:
            if cached:
                return [dict(item) for item in cached]
            data = adapter_json("/v1/models", timeout=15)
            return [
                {"id": item["id"], "name": item.get("name") or item["id"].removeprefix("openclaw/"),
                 "source": "remote", "provider": item["id"].removeprefix("openclaw/").split("/", 1)[0],
                 "context_length": item.get("context_length")}
                for item in data.get("data", [])
                if str(item.get("id", "")).startswith("openclaw/")
            ]


def expand_prompt(model: str, prompt: str) -> dict:
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ValueError("Enter a rough video idea first")
    if len(prompt) > 8_000:
        raise ValueError("Prompt is too long")
    available = {item["id"]: item for item in openclaw_models()}
    selected = available.get(model)
    if not selected:
        raise ValueError("Selected OpenClaw model is unavailable")
    messages = [
        {"role": "system", "content": (
            "Rewrite the user's rough idea as one practical WAN 2.2 video prompt. Preserve the "
            "subject, meaning, mood and constraints. Describe one continuous shot: subject and "
            "action, setting, lighting, framing, camera path, motion intensity and temporal "
            "continuity. Do not invent extra people, brands, text, cuts or scene changes. Avoid "
            "keyword soup. Use 60 to 120 words unless the idea is already precise. Return only "
            "the finished prompt."
        )},
        {"role": "user", "content": prompt},
    ]
    if selected["source"] == "local":
        request = urllib.request.Request(
            OLLAMA + "/api/chat",
            data=json.dumps({
                "model": model.removeprefix("openclaw/ollama/"), "stream": False,
                "think": False, "keep_alive": 0, "messages": messages,
                "options": {"temperature": 0.2, "num_predict": 512},
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=900) as response:
            content = (json.load(response).get("message") or {}).get("content")
    else:
        result = adapter_json("/v1/chat/completions", {
            "model": model, "stream": False, "temperature": 0.2, "messages": messages,
        }, timeout=300)
        content = (((result.get("choices") or [{}])[0].get("message") or {}).get("content"))
    if isinstance(content, list):
        content = "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    expanded = str(content or "").strip().strip('"')
    if not expanded:
        raise RuntimeError("OpenClaw returned an empty video prompt")
    return {"original_prompt": prompt, "expanded_prompt": expanded,
            "model": model, "source": selected["source"], "expanded_at": now()}


def reference_info(reference_id: str) -> dict:
    if not isinstance(reference_id, str) or not re.fullmatch(r"ref-[a-f0-9]{32}", reference_id):
        raise ValueError("Invalid reference image")
    base = project_dir() / "reference_inputs"
    target = base / (reference_id + ".png")
    metadata = base / (reference_id + ".json")
    if not target.is_file() or not metadata.is_file():
        raise ValueError("Reference image is missing; upload it again")
    return json.loads(metadata.read_text())


def save_reference(data: bytes, filename: str) -> dict:
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError("Reference must be a PNG, JPEG or WebP image")
            if source.width * source.height > 40_000_000:
                raise ValueError("Reference must be no larger than 40 megapixels")
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Cannot read this image; choose a valid PNG, JPEG or WebP") from exc
    rgb = Image.new("RGB", image.size, "white")
    rgb.paste(image, mask=image.getchannel("A"))
    ensure_project()
    reference_id = "ref-" + uuid.uuid4().hex
    relative = "reference_inputs/" + reference_id + ".png"
    target = project_dir() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    rgb.save(target, "PNG")
    info = {"id": reference_id, "path": relative, "name": Path(filename).name[:200],
            "width": rgb.width, "height": rgb.height,
            "media_url": f"/media/{VIDEO_PROJECT_ID}/{relative}"}
    atomic_json(target.with_suffix(".json"), info)
    return info


def show_output(path_value: str) -> dict:
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError("Output path is required")
    try:
        target = Path(path_value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Generated video no longer exists") from exc
    root = ROOT.resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("Output must be a generated WAN Video Desk file")
    try:
        shown = subprocess.run([
            "gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1",
            "--object-path", "/org/freedesktop/FileManager1",
            "--method", "org.freedesktop.FileManager1.ShowItems", f"['{target.as_uri()}']", "",
        ], capture_output=True, text=True, timeout=10, check=False)
        if shown.returncode == 0:
            return {"shown": True, "selected": True, "method": "FileManager1.ShowItems"}
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        pass
    subprocess.Popen(["xdg-open", str(target.parent)], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return {"shown": True, "selected": False, "method": "xdg-open"}


def state() -> dict:
    project = ensure_project()
    shot = project["shots"][0]
    existing = [take for take in shot.get("takes", [])
                if (project_dir() / str(take.get("path") or "")).is_file()]
    if len(existing) != len(shot.get("takes", [])):
        shot["takes"] = existing
        save_project(project)
    takes = [dict(take) for take in sorted(existing, key=lambda item: item.get("created_at", 0), reverse=True)]
    snapshot = QUEUE.snapshot()
    jobs = [job for job in snapshot["jobs"] if job.get("project_id") == VIDEO_PROJECT_ID][-100:]
    jobs_by_take = {job.get("result", {}).get("id"): job for job in jobs if job.get("result", {}).get("id")}
    for take in takes:
        take["absolute_path"] = str(project_dir() / take["path"])
        take["media_url"] = f"/media/{VIDEO_PROJECT_ID}/{urllib.parse.quote(take['path'])}"
        take["duration_seconds"] = round((int(take.get("frames", 17)) - 1) / int(take.get("fps", WAN_FPS)), 3)
        source_job = jobs_by_take.get(take.get("id"))
        if not take.get("generation_seconds") and source_job and source_job.get("started_at") and source_job.get("finished_at"):
            take["generation_seconds"] = round(source_job["finished_at"] - source_job["started_at"], 3)
    try:
        models = openclaw_models()
        adapter = {"online": bool(models), "models": len(models),
                   "local": sum(item["source"] == "local" for item in models),
                   "remote": sum(item["source"] == "remote" for item in models)}
    except Exception as exc:
        adapter = {"online": False, "error": str(exc)}
    model_rows = []
    for name, model_path in WAN_MODEL_FILES.items():
        required = [model_path, *WAN_COMMON_FILES]
        if "i2v" in WAN_MODEL_MODES[name]:
            required.append(WAN_CLIP_FILE)
        model_rows.append({"id": name, "name": name, "modes": list(WAN_MODEL_MODES[name]),
                           "mode": WAN_MODEL_MODES[name][-1],
                           "ready": all(path.is_file() for path in required)})
    return {
        "project_id": VIDEO_PROJECT_ID, "takes": takes, "jobs": jobs,
        "queue": {"pause_after_current": snapshot["pause_after_current"], "engine": snapshot["engine"]},
        "openclaw": adapter,
        "backend": {"id": WAN_BACKEND, "name": "WAN 2.2 Rapid Q5_K", "fps": WAN_FPS,
                    "fps_options": list(WAN_FPS_OPTIONS), "t2v": True, "i2v": True},
        "video_models": model_rows,
        "formats": {quality: {aspect: list(size) for aspect, size in aspects.items()}
                    for quality, aspects in VIDEO_FORMATS.items()},
        "durations": list(range(1, WAN_MAX_SECONDS + 1)),
        "fps_options": list(WAN_FPS_OPTIONS),
        "steps": {"default": WAN_MIN_STEPS, "min": WAN_MIN_STEPS, "max": WAN_MAX_STEPS},
    }


def delete_take(take_id: str) -> dict:
    if not isinstance(take_id, str) or not re.fullmatch(r"take-[a-f0-9]+", take_id):
        raise ValueError("Invalid video id")
    project = ensure_project()
    shot = project["shots"][0]
    take = next((item for item in shot.get("takes", []) if item.get("id") == take_id), None)
    if take is None:
        raise ValueError("Video is no longer in the gallery")
    base = project_dir().resolve()
    target = (base / str(take.get("path") or "")).resolve()
    if not target.is_relative_to(base):
        raise ValueError("Video path is outside WAN Video Desk")
    if target.is_file():
        trashed = subprocess.run(["gio", "trash", str(target)], capture_output=True,
                                 text=True, timeout=30, check=False)
        if trashed.returncode != 0:
            raise RuntimeError(trashed.stderr.strip() or "Could not move the video to Trash")
    shot["takes"] = [item for item in shot.get("takes", []) if item.get("id") != take_id]
    if shot.get("selected_take_id") == take_id:
        shot["selected_take_id"] = None
    save_project(project)
    return {"deleted": True, "id": take_id, "trashed": not target.is_file()}


def validate_job(body: dict) -> dict:
    project = ensure_project()
    if not str(body.get("prompt") or "").strip():
        raise ValueError("Video prompt is required")
    mode = str(body.get("mode") or "t2v")
    model = str(body.get("video_model") or WAN_T2V_MODEL)
    if mode not in ("t2v", "i2v"):
        raise ValueError("Video input must be Text or Image")
    if model not in WAN_MODEL_FILES:
        raise ValueError("Choose an installed WAN video model")
    if mode not in WAN_MODEL_MODES[model]:
        raise ValueError(f"{model} does not support {mode.upper()} input")
    required = [WAN_MODEL_FILES[model], *WAN_COMMON_FILES]
    if mode == "i2v":
        required.append(WAN_CLIP_FILE)
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise ValueError("WAN 2.2 is missing required files: " + ", ".join(missing))
    if mode == "i2v":
        reference = body.get("reference_image")
        if not isinstance(reference, dict) or not reference.get("path"):
            raise ValueError("Image input needs a reference image")
        source = (project_dir() / str(reference["path"])).resolve()
        if not source.is_relative_to(project_dir().resolve()) or not source.is_file():
            raise ValueError("WAN 2.2 reference image is missing")
    fps = int(body.get("fps", WAN_FPS))
    steps = int(body.get("steps", WAN_MIN_STEPS))
    frames = int(body.get("frames", 81))
    width = int(body.get("width", 640))
    height = int(body.get("height", 480))
    if fps not in WAN_FPS_OPTIONS:
        raise ValueError("WAN 2.2 fps must be 16 or 24")
    if not WAN_MIN_STEPS <= steps <= WAN_MAX_STEPS:
        raise ValueError("WAN 2.2 steps must be between 4 and 20")
    if (frames - 1) % fps or not 1 <= (frames - 1) // fps <= WAN_MAX_SECONDS:
        raise ValueError("WAN 2.2 frames must describe 1–10 whole seconds")
    if not (256 <= width <= 1280 and 256 <= height <= 1280 and width % 16 == 0 and height % 16 == 0):
        raise ValueError("Video dimensions must be 256–1280 and multiples of 16")
    body.update(backend=WAN_BACKEND, mode=mode, video_model=model, fps=fps,
                steps=steps, frames=frames, width=width, height=height,
                project_id=VIDEO_PROJECT_ID, shot_id="shot-video-desk", kind="video")
    project["settings"]["fps"] = fps
    return body


QUEUE = GenerationQueue(ROOT, APP_DIR / "workflows", load_project, save_project)


class Handler(LocalRequestHandler):
    binary_upload_paths = frozenset({"/api/video-studio/reference"})
    server_version = "WANVideoDesk/0.1"

    def log_message(self, fmt, *args):
        with (ROOT / "logs/app.log").open("a") as handle:
            handle.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def _json(self, data, status=200, headers=None):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message):
        self._json({"error": str(message)}, status)

    def _length(self, limit: int) -> int:
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Transfer-Encoding is not supported")
        raw = self.headers.get("Content-Length")
        if raw is None or not raw.isdigit():
            raise ValueError("A valid Content-Length is required")
        length = int(raw)
        if not 0 < length <= limit:
            raise ValueError("Request is empty or too large")
        return length

    def _body_json(self) -> dict:
        length = self._length(16 * 1024 * 1024)
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("JSON upload was incomplete")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _static(self, name: str):
        path = (STATIC / name).resolve()
        if STATIC.resolve() not in path.parents or not path.is_file():
            return self._error(404, "not found")
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _media(self, relative: str):
        base = project_dir().resolve()
        path = (base / urllib.parse.unquote(relative)).resolve()
        if base not in path.parents or not path.is_file():
            return self._error(404, "media not found")
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", range_header)
            try:
                if not match or not any(match.groups()) or not size:
                    raise ValueError("invalid byte range")
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(size - 1, int(last)) if last else size - 1
                else:
                    suffix = int(last)
                    if suffix <= 0:
                        raise ValueError("invalid suffix length")
                    start = max(0, size - suffix)
                if start > end or start >= size:
                    raise ValueError("byte range outside file")
            except ValueError:
                return self._json({"error": "invalid or unsatisfiable byte range"}, 416,
                                  {"Content-Range": f"bytes */{size}"})
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self):
        try:
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/video-studio", "/video-studio/", "/video-studio/index.html"):
                return self._static("index.html")
            if path.startswith("/video-studio/static/"):
                return self._static(path.removeprefix("/video-studio/static/"))
            if path == "/video-studio/manifest.webmanifest":
                return self._static("manifest.webmanifest")
            if path == "/video-studio/sw.js":
                return self._static("sw.js")
            if path == "/api/health":
                snapshot = QUEUE.snapshot()
                active = any(job.get("status") in ("queued", "running")
                             for job in snapshot.get("jobs", []))
                return self._json({"ok": True, "busy": active, "starting": False,
                                   "jobs": snapshot.get("jobs", []), "queue": snapshot})
            if path == "/api/video-studio/state":
                return self._json(state())
            if path == "/api/video-studio/models":
                return self._json({"models": openclaw_models(), "online": True})
            prefix = f"/media/{VIDEO_PROJECT_ID}/"
            if path.startswith(prefix):
                return self._media(path.removeprefix(prefix))
            return self._error(404, "route not found")
        except BrokenPipeError:
            pass
        except ValueError as exc:
            self._error(400, exc)
        except Exception as exc:
            self._error(500, exc)

    def do_POST(self):
        try:
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/video-studio/expand":
                body = self._body_json()
                return self._json(expand_prompt(body.get("model", ""), body.get("prompt", "")))
            if path == "/api/video-studio/reference":
                length = self._length(20 * 1024**2)
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError("Reference upload was incomplete")
                filename = urllib.parse.unquote(self.headers.get("X-Filename") or "reference.png")
                return self._json(save_reference(data, filename), 201)
            if path == "/api/video-studio/show-output":
                return self._json(show_output(self._body_json().get("path", "")))
            if path == "/api/video-studio/delete":
                return self._json(delete_take(self._body_json().get("id", "")))
            if path == "/api/video-studio/generate":
                body = self._body_json()
                final_prompt = str(body.get("final_prompt") or "").strip()
                original_prompt = str(body.get("original_prompt") or final_prompt).strip()
                negative = str(body.get("negative") or "").strip()
                if not final_prompt:
                    raise ValueError("Review or enter the final motion prompt before generating")
                if len(final_prompt) > 12_000 or len(negative) > 8_000:
                    raise ValueError("Prompt is too long")
                quality = str(body.get("quality") or "480p")
                aspect = str(body.get("aspect") or "4:3")
                if quality not in VIDEO_FORMATS or aspect not in VIDEO_FORMATS[quality]:
                    raise ValueError("Choose a supported resolution and aspect ratio")
                try:
                    duration = int(body.get("duration_seconds", 5))
                    fps = int(body.get("fps", WAN_FPS))
                    steps = int(body.get("steps", WAN_MIN_STEPS))
                    seed = int(body.get("seed"))
                    batch = max(1, min(4, int(body.get("batch_count", 1))))
                except (TypeError, ValueError) as exc:
                    raise ValueError("Duration, fps, steps, seed and take count must be numbers") from exc
                if not 1 <= duration <= WAN_MAX_SECONDS:
                    raise ValueError("Duration must be a whole number from 1 to 10 seconds")
                if not 0 <= seed < 2**63:
                    raise ValueError("Seed must be between 0 and 9223372036854775807")
                mode = str(body.get("mode") or "t2v")
                reference = reference_info(body.get("reference_image_id")) if mode == "i2v" else None
                width, height = VIDEO_FORMATS[quality][aspect]
                payload = validate_job({
                    "video_model": str(body.get("video_model") or WAN_T2V_MODEL),
                    "mode": mode, "reference_image": reference,
                    "prompt": final_prompt, "negative": negative,
                    "original_prompt": original_prompt, "expanded_prompt": final_prompt,
                    "expander_model": body.get("expander_model") or None,
                    "prompt_mode": body.get("prompt_mode") or "edited",
                    "duration_seconds": duration, "quality": quality, "aspect_ratio": aspect,
                    "seed": seed, "fps": fps, "steps": steps, "frames": duration * fps + 1,
                    "width": width, "height": height, "take_count": batch,
                })
                return self._json({"jobs": QUEUE.add(payload)}, 201)
            if path == "/api/queue/action":
                body = self._body_json()
                return self._json(QUEUE.action(body.get("action", ""), body.get("job_id")))
            if path == "/api/engine/start":
                return self._json({"started": QUEUE.engine.start(profile="wan-dynamic"),
                                   "engine": QUEUE.engine.status()})
            if path == "/api/engine/stop":
                return self._json({"stopped": QUEUE.engine.stop_owned(),
                                   "engine": QUEUE.engine.status()})
            return self._error(404, "route not found")
        except ValueError as exc:
            self._error(400, exc)
        except Exception as exc:
            self._error(500, exc)


def main() -> None:
    ensure_project()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"WAN Video Desk -> http://{HOST}:{PORT}/video-studio/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
