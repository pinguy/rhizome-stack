#!/usr/bin/env python3
"""All-local AI Music Video Studio — one browser app, no node graphs exposed."""

from __future__ import annotations

import io
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from analysis import analyse, probe
from engine import (GenerationQueue, H3_BACKEND, H3_DEFAULT_STEPS, H3_FPS,
                    H3_MAX_SECONDS,
                    H3_MAX_STEPS, H3_MIN_STEPS, H3_MODEL, H3_MODEL_ROOT,
                    H3_TURBO_BACKEND, H3_TURBO_MAX_STEPS, H3_TURBO_MIN_STEPS,
                    H3_TURBO_MODEL, H3_TURBO_STEPS,
                    H3_TURBO_WORKFLOW,
                    WAN_BACKEND, WAN_CLIP_VISION, WAN_FPS,
                    WAN_FPS_OPTIONS, WAN_I2V_MODEL, WAN_MAX_SECONDS,
                    WAN_MAX_STEPS, WAN_MIN_STEPS, WAN_MODEL_MODES, WAN_TEXT_ENCODER,
                    WAN_T2V_MODEL, WAN_VAE, atomic_json)
from image_presets import (DEFAULT_IMAGE_PRESET, image_preset_catalogue,
                           preset_for_dimensions, resolve_image_dimensions,
                           validate_image_dimensions)
from renderer import render
from upscaler import UpscaleManager


APP_DIR = Path(__file__).resolve().parent
STATIC = APP_DIR / "static"
IMAGE_STATIC = APP_DIR / "image_static"
VIDEO_STATIC = APP_DIR / "video_static"
WORKFLOWS = APP_DIR / "workflows"
STACK_ROOT = Path(os.environ.get(
    "RHIZOME_STACK_ROOT", "~/.local/share/rhizome-stack"
)).expanduser()
COMFY_DIR = Path(os.environ.get(
    "COMFY_DIR", STACK_ROOT / "creative/ComfyUI"
)).expanduser()
ROOT = Path(os.environ.get(
    "STUDIO_ROOT", STACK_ROOT / "creative/state/cutroom"
)).expanduser()
PROJECTS = ROOT / "projects"
HOST = os.environ.get("STUDIO_HOST", "127.0.0.1")
PORT = int(os.environ.get("STUDIO_PORT", "8840"))
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MAX_UPLOAD = 2 * 1024**3
IMAGE_PROJECT_ID = "qwen-image-studio"
VIDEO_PROJECT_ID = "wan-video-studio"
OPENCLAW_ADAPTER = os.environ.get("OPENCLAW_ADAPTER_URL", "http://127.0.0.1:18888")
OPENCLAW_BIN = os.environ.get(
    "OPENCLAW_BIN", str(Path.home() / ".npm-global/bin/openclaw")
)
OPENCLAW_CONFIG = Path(os.environ.get(
    "OPENCLAW_CONFIG", Path.home() / ".openclaw/openclaw.json"
)).expanduser()
WAN_MODEL_FILES = {
    WAN_T2V_MODEL: COMFY_DIR / "models/unet" / WAN_T2V_MODEL,
    WAN_I2V_MODEL: COMFY_DIR / "models/unet" / WAN_I2V_MODEL,
}
WAN_COMMON_REQUIRED_FILES = (
    COMFY_DIR / "models/text_encoders" / WAN_TEXT_ENCODER,
    COMFY_DIR / "models/vae" / WAN_VAE,
)
WAN_CLIP_VISION_FILE = COMFY_DIR / "models/clip_vision" / WAN_CLIP_VISION
H3_REQUIRED_FILES = {
    "minimax-h3-fl2va-pruned-nf4.safetensors": 10_483_868_433,
    "minimax-h3-text-encoder-nf4.safetensors": 15_324_775_807,
    "video_vae_nf4.safetensors": 1_613_201_536,
    "audio_vae_nf4.safetensors": 284_004_112,
}
H3_PROCESSOR_FILES = (
    "chat_template.json", "merges.txt", "preprocessor_config.json", "tokenizer.json",
    "tokenizer_config.json", "video_preprocessor_config.json", "vocab.json",
)
H3_PROCESSOR = H3_MODEL_ROOT / "FL2VA/processor"
H3_TURBO_REQUIRED_FILES = (
    COMFY_DIR / "models/diffusion_models/minimax-h3-fl2va-pruned-nf4.safetensors",
    COMFY_DIR / "models/text_encoders/minimax-h3-text-encoder-nf4.safetensors",
    COMFY_DIR / "models/vae/minimax_h3_video_vae_int8_convrot.safetensors",
    COMFY_DIR / "models/vae/minimax_h3_audio_vae_fp32.safetensors",
    COMFY_DIR / "models/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
    H3_TURBO_WORKFLOW,
)
H3_TURBO_NODE_DIRS = (
    COMFY_DIR / "custom_nodes/ComfyUI_bnb_nf4_fp4_Loaders",
    COMFY_DIR / "custom_nodes/ComfyUI-MiniMax-H3-Turbo",
    COMFY_DIR / "custom_nodes/ComfyUI-sol-attn",
    COMFY_DIR / "custom_nodes/ComfyUI-Spectrum-MiniMax-H3",
)
EXPANDER_INSTRUCTION = """You improve rough prompts for Qwen Image 2.1.
Preserve the user's subject, meaning, mood and constraints. Add only useful visual specificity: clear subject details, environment, composition, lighting, materials, colour language and camera/viewpoint when appropriate. Keep the result practical and concise, normally 60 to 120 words. Do not invent extra people, brands, text, logos, lore or unrelated story elements. Avoid keyword soup, breathless hype and repetitive style adjectives. If the input is already precise, make only small improvements. Return only the finished image prompt, with no preamble, quotes, headings or commentary."""
_OPENCLAW_MODELS_CACHE = (0.0, [])
_OPENCLAW_MODELS_LOCK = threading.Lock()
VIDEO_FORMATS = {
    "480p": {"16:9": (832, 480), "4:3": (640, 480), "mobile": (480, 832)},
    "720p": {"16:9": (1280, 720), "4:3": (960, 720), "mobile": (720, 1280)},
}
H3_VIDEO_FORMATS = {
    "480p": {"16:9": (832, 480), "4:3": (640, 480), "mobile": (480, 832)},
    "720p": {"16:9": (1344, 768), "4:3": (1024, 768), "mobile": (768, 1344)},
}


def h3_ready() -> bool:
    return (all((H3_MODEL_ROOT / name).is_file()
                and (H3_MODEL_ROOT / name).stat().st_size == size
                and not (H3_MODEL_ROOT / (name + ".aria2")).exists()
                for name, size in H3_REQUIRED_FILES.items())
            and all((H3_PROCESSOR / name).is_file() for name in H3_PROCESSOR_FILES))


def h3_turbo_ready() -> bool:
    return (all(path.is_file() and path.stat().st_size > 0
                for path in H3_TURBO_REQUIRED_FILES)
            and all(path.is_dir() for path in H3_TURBO_NODE_DIRS))


def h3_frames_for_seconds(seconds: int) -> int:
    """Nearest legal 17n+5 frame count to the requested wall time at 24 fps."""
    target = max(5, int(seconds) * H3_FPS)
    n = max(0, round((target - 5) / 17))
    return n * 17 + 5

for directory in (PROJECTS, ROOT / "state", ROOT / "logs"):
    directory.mkdir(parents=True, exist_ok=True)


def now():
    return time.time()


def safe_id(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", value or ""):
        raise ValueError("invalid project id")
    return value


def slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (value or "untitled").lower()).strip("-")
    return (text or "untitled")[:48]


def project_dir(project_id: str) -> Path:
    return PROJECTS / safe_id(project_id)


def show_output_in_file_manager(path_value: str) -> dict:
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError("Output path is required")
    try:
        target = Path(path_value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Generated image no longer exists") from exc
    root = ROOT.resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("Output must be a generated studio file")

    uri = target.as_uri()
    try:
        shown = subprocess.run([
            "gdbus", "call", "--session",
            "--dest", "org.freedesktop.FileManager1",
            "--object-path", "/org/freedesktop/FileManager1",
            "--method", "org.freedesktop.FileManager1.ShowItems",
            f"['{uri}']", "",
        ], capture_output=True, text=True, timeout=10, check=False)
        if shown.returncode == 0:
            return {"shown": True, "selected": True, "method": "FileManager1.ShowItems"}
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        pass

    try:
        subprocess.Popen(["xdg-open", str(target.parent)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise RuntimeError("Could not open the system file manager") from exc
    return {"shown": True, "selected": False, "method": "xdg-open"}


def unload_ollama_models() -> None:
    try:
        with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=5) as response:
            loaded = json.load(response).get("models", [])
    except Exception as exc:
        raise RuntimeError("Could not verify that Ollama released the RTX 3060") from exc
    for item in loaded:
        model = item.get("name") or item.get("model")
        if not model:
            continue
        payload = json.dumps({"model": model, "keep_alive": 0}).encode()
        request = urllib.request.Request(OLLAMA + "/api/generate", data=payload,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30):
            pass
    deadline = time.time() + 30
    while time.time() < deadline:
        with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=5) as response:
            if not json.load(response).get("models"):
                return
        time.sleep(0.5)
    raise RuntimeError("Ollama did not release its loaded GPU model")


def load_project(project_id: str) -> dict:
    return json.loads((project_dir(project_id) / "project.json").read_text())


def save_project(project: dict) -> None:
    pid = safe_id(project["id"])
    current_revision = 0
    try:
        current_revision = int(load_project(pid).get("revision", 0))
    except Exception:
        pass
    project["updated_at"] = now()
    project["revision"] = max(current_revision, int(project.get("revision", 0))) + 1
    atomic_json(project_dir(pid) / "project.json", project)


def list_projects() -> list[dict]:
    out = []
    for path in PROJECTS.glob("*/project.json"):
        try:
            p = json.loads(path.read_text())
            if p.get("kind") in ("image-studio", "video-studio"):
                continue
            out.append({"id": p["id"], "name": p["name"], "updated_at": p.get("updated_at"),
                        "duration": (p.get("analysis") or {}).get("audio", {}).get("duration"),
                        "shots": len(p.get("shots", [])), "assets": len(p.get("assets", [])),
                        "cover": next((a["path"] for a in p.get("assets", []) if a.get("favourite")), None)})
        except Exception:
            continue
    return sorted(out, key=lambda p: p.get("updated_at") or 0, reverse=True)


def ensure_image_project() -> dict:
    base = project_dir(IMAGE_PROJECT_ID)
    path = base / "project.json"
    if path.is_file():
        return load_project(IMAGE_PROJECT_ID)
    for sub in ("references", "thumbnails", "logs"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    created = now()
    project = {
        "id": IMAGE_PROJECT_ID,
        "kind": "image-studio",
        "name": "Qwen Image Desk",
        "created_at": created,
        "updated_at": created,
        "revision": 1,
        "assets": [],
        "shots": [],
        "timeline": {"items": [], "overlays": []},
    }
    atomic_json(path, project)
    return project


def adapter_json(path: str, payload=None, timeout=30) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        OPENCLAW_ADAPTER + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def openclaw_models() -> list[dict]:
    """Return the live allowed OpenClaw catalogue, including local Ollama rows."""
    global _OPENCLAW_MODELS_CACHE
    with _OPENCLAW_MODELS_LOCK:
        cached_at, cached = _OPENCLAW_MODELS_CACHE
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
            _OPENCLAW_MODELS_CACHE = (time.monotonic(), models)
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


def expand_image_prompt(model: str, prompt: str, editing: bool = False) -> dict:
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ValueError("Enter a rough prompt first")
    if len(prompt) > 8_000:
        raise ValueError("Prompt is too long")
    available = {item["id"]: item for item in openclaw_models()}
    selected = available.get(model)
    if not selected:
        raise ValueError("Selected OpenClaw model is unavailable")
    messages = [
        {"role": "system", "content": (
            "Rewrite this image-edit instruction clearly and concisely for Qwen Image 2.1. "
            "An existing reference image will be supplied to Qwen, but you cannot see it. "
            "Preserve exactly the requested changes. Do not invent image details or extra changes. "
            "Keep everything not mentioned unchanged. Return only the edit instruction."
            if editing else EXPANDER_INSTRUCTION)},
        {"role": "user", "content": prompt},
    ]
    if selected["source"] == "local":
        request = urllib.request.Request(
            OLLAMA + "/api/chat",
            data=json.dumps({
                "model": model.removeprefix("openclaw/ollama/"),
                "stream": False, "think": False, "keep_alive": 0,
                "messages": messages, "options": {"temperature": 0.2, "num_predict": 512},
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
        raise RuntimeError("OpenClaw returned an empty expanded prompt")
    return {"original_prompt": prompt, "expanded_prompt": expanded,
            "model": model, "source": selected["source"], "expanded_at": now()}


def expand_video_prompt(model: str, prompt: str) -> dict:
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
            "Rewrite the user's rough idea as one practical WAN 2.2 text-to-video prompt. "
            "Preserve the subject, meaning, mood and constraints. Describe one continuous shot: "
            "subject and action, setting, lighting, framing, camera path, motion intensity and temporal "
            "continuity. Do not invent extra people, brands, text, cuts or scene changes. Avoid keyword "
            "soup. Use 60 to 120 words unless the idea is already precise. Return only the finished prompt."
        )},
        {"role": "user", "content": prompt},
    ]
    if selected["source"] == "local":
        request = urllib.request.Request(
            OLLAMA + "/api/chat",
            data=json.dumps({
                "model": model.removeprefix("openclaw/ollama/"),
                "stream": False, "think": False, "keep_alive": 0,
                "messages": messages, "options": {"temperature": 0.2, "num_predict": 512},
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


def reference_image_info(reference_id: str, owner_project_id: str = IMAGE_PROJECT_ID) -> dict:
    if not isinstance(reference_id, str) or not re.fullmatch(r"ref-[a-f0-9]{32}", reference_id):
        raise ValueError("Invalid reference image")
    base = project_dir(owner_project_id) / "reference_inputs"
    target = base / (reference_id + ".png")
    metadata = base / (reference_id + ".json")
    if not target.is_file() or not metadata.is_file():
        raise ValueError("Reference image is missing; upload it again")
    return json.loads(metadata.read_text())


def save_reference_image(data: bytes, filename: str,
                         owner_project_id: str = IMAGE_PROJECT_ID) -> dict:
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
    # Flatten alpha over white and strip source metadata before local inference.
    rgb = Image.new("RGB", image.size, "white")
    rgb.paste(image, mask=image.getchannel("A"))
    if owner_project_id == IMAGE_PROJECT_ID:
        ensure_image_project()
    elif owner_project_id == VIDEO_PROJECT_ID:
        ensure_video_project()
    else:
        raise ValueError("Reference image owner is not a standalone studio project")
    reference_id = "ref-" + uuid.uuid4().hex
    relative = "reference_inputs/" + reference_id + ".png"
    target = project_dir(owner_project_id) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    rgb.save(target, "PNG")
    info = {"id": reference_id, "path": relative, "name": Path(filename).name[:200],
            "width": rgb.width, "height": rgb.height,
            "media_url": f"/media/{owner_project_id}/{relative}"}
    atomic_json(target.with_suffix(".json"), info)
    return info


def image_studio_state() -> dict:
    project = ensure_image_project()
    snapshot = QUEUE.snapshot()
    jobs = [job for job in snapshot["jobs"] if job.get("project_id") == IMAGE_PROJECT_ID][-100:]
    project_assets = project.get("assets", [])
    existing_assets = [
        asset for asset in project_assets
        if (project_dir(IMAGE_PROJECT_ID) / str(asset.get("path") or "")).is_file()
    ]
    if len(existing_assets) != len(project_assets):
        project["assets"] = existing_assets
        save_project(project)
    assets = sorted(existing_assets, key=lambda asset: asset.get("created_at", 0), reverse=True)
    assets = [dict(asset) for asset in assets]
    for asset in assets:
        asset["absolute_path"] = str(project_dir(IMAGE_PROJECT_ID) / asset["path"])
        asset["media_url"] = f"/media/{IMAGE_PROJECT_ID}/{urllib.parse.quote(asset['path'])}"
    try:
        models = openclaw_models()
        adapter_state = {"online": bool(models), "models": len(models),
                         "local": sum(item["source"] == "local" for item in models),
                         "remote": sum(item["source"] == "remote" for item in models)}
    except Exception as exc:
        adapter_state = {"online": False, "error": str(exc)}
    return {
        "project_id": IMAGE_PROJECT_ID,
        "assets": assets,
        "jobs": jobs,
        "queue": {"pause_after_current": snapshot["pause_after_current"], "engine": snapshot["engine"]},
        "openclaw": adapter_state,
        "presets": image_preset_catalogue(),
        "default_preset": DEFAULT_IMAGE_PRESET,
    }


def delete_image_studio_asset(asset_id: str) -> dict:
    if not isinstance(asset_id, str) or not re.fullmatch(r"asset-[a-f0-9]+", asset_id):
        raise ValueError("Invalid image id")
    project = ensure_image_project()
    asset = next((item for item in project.get("assets", []) if item.get("id") == asset_id), None)
    if asset is None:
        raise ValueError("Image is no longer in the gallery")
    base = project_dir(IMAGE_PROJECT_ID).resolve()
    target = (base / str(asset.get("path") or "")).resolve()
    if not target.is_relative_to(base):
        raise ValueError("Image path is outside the Qwen Image Desk project")
    if target.is_file():
        trashed = subprocess.run(["gio", "trash", str(target)], capture_output=True, text=True,
                                 timeout=30, check=False)
        if trashed.returncode != 0:
            raise RuntimeError(trashed.stderr.strip() or "Could not move the image to Trash")
    project["assets"] = [item for item in project.get("assets", []) if item.get("id") != asset_id]
    save_project(project)
    return {"deleted": True, "id": asset_id, "trashed": target.is_file() is False}


def ensure_video_project() -> dict:
    base = project_dir(VIDEO_PROJECT_ID)
    path = base / "project.json"
    if path.is_file():
        return load_project(VIDEO_PROJECT_ID)
    for sub in ("generated", "accepted", "salvage", "logs", "reference_inputs"):
        (base / sub).mkdir(parents=True, exist_ok=True)
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
            "frames": 49, "seed": 420251006, "takes": [], "selected_take_id": None,
        }],
        "timeline": {"items": [], "titles": []},
        "settings": {"video_backend": WAN_BACKEND, "fps": WAN_FPS},
    }
    atomic_json(path, project)
    return project


def video_studio_state() -> dict:
    project = ensure_video_project()
    shot = project["shots"][0]
    base = project_dir(VIDEO_PROJECT_ID)
    existing = [take for take in shot.get("takes", [])
                if (base / str(take.get("path") or "")).is_file()]
    if len(existing) != len(shot.get("takes", [])):
        shot["takes"] = existing
        save_project(project)
    takes = [dict(take) for take in sorted(existing, key=lambda item: item.get("created_at", 0), reverse=True)]
    snapshot = QUEUE.snapshot()
    jobs = [job for job in snapshot["jobs"] if job.get("project_id") == VIDEO_PROJECT_ID][-100:]
    jobs_by_take = {job.get("result", {}).get("id"): job for job in jobs if job.get("result", {}).get("id")}
    for take in takes:
        take["absolute_path"] = str(base / take["path"])
        take["media_url"] = f"/media/{VIDEO_PROJECT_ID}/{urllib.parse.quote(take['path'])}"
        take["duration_seconds"] = round((int(take.get("frames", 17)) - 1) / int(take.get("fps", WAN_FPS)), 3)
        source_job = jobs_by_take.get(take.get("id"))
        if not take.get("generation_seconds") and source_job and source_job.get("started_at") and source_job.get("finished_at"):
            take["generation_seconds"] = round(max(0.0, source_job["finished_at"] - source_job["started_at"]), 3)
    try:
        models = openclaw_models()
        adapter_state = {"online": bool(models), "models": len(models),
                         "local": sum(item["source"] == "local" for item in models),
                         "remote": sum(item["source"] == "remote" for item in models)}
    except Exception as exc:
        adapter_state = {"online": False, "error": str(exc)}
    return {
        "project_id": VIDEO_PROJECT_ID,
        "takes": takes,
        "jobs": jobs,
        "upscale": UPSCALE.snapshot(),
        "queue": {"pause_after_current": snapshot["pause_after_current"], "engine": snapshot["engine"]},
        "openclaw": adapter_state,
        "backend": {"id": WAN_BACKEND, "name": "Local Video Desk", "fps": WAN_FPS,
                    "fps_options": list(WAN_FPS_OPTIONS),
                    "t2v": True, "i2v": True},
        "video_models": [
            {"id": name, "name": name, "modes": list(WAN_MODEL_MODES[name]),
             "mode": WAN_MODEL_MODES[name][-1],
             "ready": all(path.is_file() for path in (model_path, *WAN_COMMON_REQUIRED_FILES)),
             "backend": WAN_BACKEND, "fps_options": list(WAN_FPS_OPTIONS),
             "max_seconds": WAN_MAX_SECONDS,
             "steps": {"default": WAN_MIN_STEPS, "min": WAN_MIN_STEPS, "max": WAN_MAX_STEPS},
             "formats": {quality: {aspect: list(size) for aspect, size in aspects.items()}
                         for quality, aspects in VIDEO_FORMATS.items()},
             "native_audio": False}
            for name, model_path in WAN_MODEL_FILES.items()
        ] + [{
            "id": H3_MODEL, "name": "MiniMax H3 · FL2VA pruned NF4",
            "modes": ["t2v", "i2v"], "mode": "i2v", "ready": h3_ready(),
            "backend": H3_BACKEND, "fps_options": [H3_FPS],
            "max_seconds": H3_MAX_SECONDS,
            "steps": {"default": H3_DEFAULT_STEPS, "min": H3_MIN_STEPS, "max": H3_MAX_STEPS},
            "formats": {quality: {aspect: list(size) for aspect, size in aspects.items()}
                        for quality, aspects in H3_VIDEO_FORMATS.items()},
            "native_audio": True,
        }, {
            "id": H3_TURBO_MODEL, "name": "MiniMax H3 · NF4 Turbo + Sol + Spectrum",
            "modes": ["t2v", "i2v"], "mode": "t2v", "ready": h3_turbo_ready(),
            "backend": H3_TURBO_BACKEND, "fps_options": [H3_FPS],
            "max_seconds": H3_MAX_SECONDS,
            "steps": {"default": H3_TURBO_STEPS, "min": H3_TURBO_MIN_STEPS,
                      "max": H3_TURBO_MAX_STEPS},
            "formats": {quality: {aspect: list(size) for aspect, size in aspects.items()}
                        for quality, aspects in H3_VIDEO_FORMATS.items()},
            "native_audio": True,
        }],
        "formats": {quality: {aspect: list(size) for aspect, size in aspects.items()}
                    for quality, aspects in VIDEO_FORMATS.items()},
        "durations": list(range(1, H3_MAX_SECONDS + 1)),
        "fps_options": list(WAN_FPS_OPTIONS),
        "steps": {"default": WAN_MIN_STEPS, "min": WAN_MIN_STEPS, "max": WAN_MAX_STEPS},
    }


def delete_video_studio_take(take_id: str) -> dict:
    if not isinstance(take_id, str) or not re.fullmatch(r"take-[a-f0-9]+", take_id):
        raise ValueError("Invalid video id")
    project = ensure_video_project()
    shot = project["shots"][0]
    take = next((item for item in shot.get("takes", []) if item.get("id") == take_id), None)
    if take is None:
        raise ValueError("Video is no longer in the gallery")
    base = project_dir(VIDEO_PROJECT_ID).resolve()
    target = (base / str(take.get("path") or "")).resolve()
    if not target.is_relative_to(base):
        raise ValueError("Video path is outside the WAN Video Desk project")
    if target.is_file():
        trashed = subprocess.run(["gio", "trash", str(target)], capture_output=True, text=True,
                                 timeout=30, check=False)
        if trashed.returncode != 0:
            raise RuntimeError(trashed.stderr.strip() or "Could not move the video to Trash")
    shot["takes"] = [item for item in shot.get("takes", []) if item.get("id") != take_id]
    if shot.get("selected_take_id") == take_id:
        shot["selected_take_id"] = None
    save_project(project)
    return {"deleted": True, "id": take_id, "trashed": not target.is_file()}


def create_project(name: str, filename: str, body_reader, length: int) -> dict:
    project_id = f"{slug(name)}-{time.strftime('%y%m%d')}-{uuid.uuid4().hex[:5]}"
    base = project_dir(project_id)
    for sub in ("audio", "analysis", "references", "generated", "salvage", "accepted",
                "thumbnails", "timeline", "renders", "logs"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower() or ".audio"
    original = base / "audio" / ("source" + ext)
    remaining = length
    with original.open("wb") as handle:
        while remaining:
            chunk = body_reader(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("upload ended before Content-Length")
            handle.write(chunk)
            remaining -= len(chunk)
    info = probe(original)
    project = {
        "schema": "music-video-studio.project/v1", "id": project_id, "name": name or Path(filename).stem,
        "created_at": now(), "updated_at": now(), "revision": 1,
        "audio": {"path": str(original.relative_to(base)), "original_filename": Path(filename).name,
                  "preserved": True, **info},
        "analysis": None, "shots": [], "assets": [], "seeds": [
            {"seed": 420251006, "favourite": True, "known_good": True,
             "note": "WAN 2.2 Rapid setup seed; keep only if its moving result earns it."}
        ],
        "bible": {
            "core_concept": "", "overall_look": "", "genre_style": "", "colour_language": "",
            "lighting_language": "", "character": "", "hair": "", "face": "", "wardrobe": "",
            "recurring_props": "", "location_1": "", "additional_locations": "", "camera_language": "",
            "recurring_motifs": "", "visual_rules": "", "avoid": "", "negative_guidance": "",
        },
        "timeline": {"snap": True, "zoom": 1.0, "items": [], "titles": []},
        "renders": [], "render_state": {"status": "idle"},
        "settings": {"video_backend": WAN_BACKEND, "default_preset": "compatibility", "fps": WAN_FPS},
    }
    save_project(project)
    return project


def validate_video_job(body: dict, project_id: str) -> dict:
    project = load_project(project_id)
    if not any(shot.get("id") == body.get("shot_id") for shot in project.get("shots", [])):
        raise ValueError("video job must name a shot in this project")
    if not str(body.get("prompt") or "").strip():
        raise ValueError("video prompt is required")
    backend = str(body.get("backend") or project.get("settings", {}).get("video_backend") or WAN_BACKEND)
    mode = str(body.get("mode") or "t2v")
    if backend not in (WAN_BACKEND, H3_BACKEND, H3_TURBO_BACKEND, "ltx-2.5"):
        raise ValueError("choose an installed local video backend")
    if mode not in ("t2v", "i2v"):
        raise ValueError("video mode must be t2v or i2v")
    if backend == WAN_BACKEND:
        video_model = str(body.get("video_model") or WAN_T2V_MODEL)
        if video_model not in WAN_MODEL_FILES:
            raise ValueError("Choose an installed WAN video model")
        if mode not in WAN_MODEL_MODES[video_model]:
            raise ValueError(f"{video_model} does not support {mode.upper()} input")
        required = (WAN_MODEL_FILES[video_model], *WAN_COMMON_REQUIRED_FILES)
        if mode == "i2v":
            required = (*required, WAN_CLIP_VISION_FILE)
        missing = [path.name for path in required if not path.is_file()]
        if missing:
            raise ValueError("WAN 2.2 is missing required files: " + ", ".join(missing))
        if mode == "i2v":
            reference = body.get("reference_image")
            if not isinstance(reference, dict) or not reference.get("path"):
                asset = next((item for item in project.get("assets", [])
                              if item.get("id") == body.get("reference_asset_id")), None)
                if asset:
                    reference = {"id": asset.get("id"), "path": asset.get("path"),
                                 "name": Path(str(asset.get("path") or "reference.png")).name}
                    body["reference_image"] = reference
            if not isinstance(reference, dict) or not reference.get("path"):
                raise ValueError("WAN 2.2 image-to-video needs a reference image")
            base = project_dir(project_id).resolve()
            source = (base / str(reference["path"])).resolve()
            if not source.is_relative_to(base) or not source.is_file():
                raise ValueError("WAN 2.2 reference image is missing")
        fps = int(body.get("fps", WAN_FPS))
        steps = int(body.get("steps", WAN_MIN_STEPS))
        if fps not in WAN_FPS_OPTIONS:
            raise ValueError("WAN 2.2 fps must be 16 or 24")
        if not WAN_MIN_STEPS <= steps <= WAN_MAX_STEPS:
            raise ValueError("WAN 2.2 steps must be between 4 and 20")
        frames = int(body.get("frames", 49))
        if (frames - 1) % fps or not 1 <= (frames - 1) // fps <= WAN_MAX_SECONDS:
            raise ValueError("WAN 2.2 frames must describe 1–10 whole seconds at 16 or 24 fps")
        body["fps"] = fps
        body["steps"] = steps
        body["video_model"] = video_model
    elif backend in (H3_BACKEND, H3_TURBO_BACKEND):
        turbo = backend == H3_TURBO_BACKEND
        expected_model = H3_TURBO_MODEL if turbo else H3_MODEL
        video_model = str(body.get("video_model") or expected_model)
        if video_model != expected_model:
            raise ValueError("Choose the installed MiniMax H3 NF4 model")
        if not (h3_turbo_ready() if turbo else h3_ready()):
            raise ValueError("MiniMax H3 NF4 is missing or still downloading required local files")
        if mode == "i2v":
            reference = body.get("reference_image")
            if not isinstance(reference, dict) or not reference.get("path"):
                asset = next((item for item in project.get("assets", [])
                              if item.get("id") == body.get("reference_asset_id")), None)
                if asset:
                    reference = {"id": asset.get("id"), "path": asset.get("path"),
                                 "name": Path(str(asset.get("path") or "reference.png")).name}
                    body["reference_image"] = reference
            if not isinstance(reference, dict) or not reference.get("path"):
                raise ValueError("MiniMax H3 Image input needs a first-frame reference image")
            base = project_dir(project_id).resolve()
            source = (base / str(reference["path"])).resolve()
            if not source.is_relative_to(base) or not source.is_file():
                raise ValueError("MiniMax H3 reference image is missing")
        fps = int(body.get("fps", H3_FPS))
        steps = int(body.get("steps", H3_TURBO_STEPS if turbo else H3_DEFAULT_STEPS))
        frames = int(body.get("frames", 73))
        if fps != H3_FPS:
            raise ValueError("MiniMax H3 runs at its native 24 fps")
        if turbo and not H3_TURBO_MIN_STEPS <= steps <= H3_TURBO_MAX_STEPS:
            raise ValueError("MiniMax H3 Turbo steps must be between 4 and 24")
        if not turbo and not H3_MIN_STEPS <= steps <= H3_MAX_STEPS:
            raise ValueError("MiniMax H3 steps must be between 4 and 50")
        if frames < 5 or frames > h3_frames_for_seconds(H3_MAX_SECONDS) or (frames - 5) % 17:
            raise ValueError("MiniMax H3 frames must use the 17n+5 sequence up to 15 seconds")
        body.update(fps=H3_FPS, steps=steps, video_model=expected_model)
    else:
        frames = int(body.get("frames", 49))
        if frames not in (49, 73, 97, 121, 145):
            raise ValueError("LTX-2.5 frames must be one of 49, 73, 97, 121 or 145")
        body["fps"] = 24
    width = int(body.get("width", 768))
    height = int(body.get("height", 448))
    alignment = 32 if backend in (H3_BACKEND, H3_TURBO_BACKEND) else 16
    limit = 1344 if backend in (H3_BACKEND, H3_TURBO_BACKEND) else 1280
    if not (256 <= width <= limit and 256 <= height <= limit
            and width % alignment == 0 and height % alignment == 0):
        raise ValueError(f"video width and height must be 256–{limit} and multiples of {alignment}")
    body.update(backend=backend, mode=mode, frames=frames, width=width, height=height)
    return body


def analyse_project(project_id: str) -> dict:
    project = load_project(project_id)
    base = project_dir(project_id)
    result = analyse(base / project["audio"]["path"])
    atomic_json(base / "analysis/analysis.json", result)
    project["analysis"] = {k: v for k, v in result.items() if k != "shots"}
    project["shots"] = result["shots"]
    project["timeline"]["items"] = [
        {"id": "item-" + shot["id"], "shot_id": shot["id"], "take_id": None,
         "start": shot["start"], "end": shot["end"], "trim_in": 0, "speed": 1.0,
         "reverse": False, "fit": "cover", "transition": "cut"}
        for shot in project["shots"]
    ]
    save_project(project)
    return project


DIRECTOR_SYSTEM = """You are the AI Director inside a practical music-video production studio.
Return JSON only. Propose one coherent, shootable concept using recurring character, wardrobe, locations and motifs.
Never reinvent the world for every shot. Generated clips are 2-6 seconds; models create shots and the editor creates the video.
JSON keys: concept (string), bible (object using the supplied bible keys), and shot_prompts (array of objects with
shot_id, prompt, reference_prompt, framing, camera, mode). Match every supplied shot_id exactly once where practical.
Prompts must describe a single continuous shot with stable identity, restrained camera motion, no cuts and no text."""


def ollama_models():
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=5) as response:
            return [m["name"] for m in json.load(response).get("models", [])]
    except Exception:
        return []


def director(project: dict, model: str, brief: str, lyrics: str) -> dict:
    models = openclaw_models()
    if not model:
        model = next((item["id"] for item in models if item["id"] == "openclaw/openai/gpt-5.6-sol"),
                     models[0]["id"] if models else "")
    selected = next((item for item in models if item["id"] == model), None)
    if not selected:
        raise ValueError("choose an available OpenClaw model")
    messages = [{"role": "system", "content": DIRECTOR_SYSTEM}, {"role": "user", "content": json.dumps({
            "project": project["name"], "brief": brief, "lyrics": lyrics,
            "analysis": {"bpm": project["analysis"]["bpm"], "sections": project["analysis"]["sections"]},
            "bible_keys": list(project["bible"].keys()),
            "shots": [{k: s.get(k) for k in ("id", "start", "end", "section", "framing", "camera", "mode")}
                      for s in project["shots"]],
        })}]
    if selected["source"] == "local":
        payload = {
            "model": model.removeprefix("openclaw/ollama/"), "stream": False,
            "format": "json", "think": False, "keep_alive": 0, "messages": messages,
            "options": {"temperature": .9, "num_predict": 6000},
        }
        req = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        # A 90-shot plan produced ~5,100 tokens in 15 minutes on the slowest 27B local model.
        # Keep the request bounded, but leave enough wall time for the configured 6,000-token ceiling.
        with urllib.request.urlopen(req, timeout=1800) as response:
            text = (json.load(response).get("message") or {}).get("content", "")
    else:
        response = adapter_json("/v1/chat/completions", {
            "model": model, "stream": False, "temperature": .9,
            "max_tokens": 6000, "messages": messages,
        }, timeout=900)
        text = (((response.get("choices") or [{}])[0].get("message") or {}).get("content", ""))
    if isinstance(text, list):
        text = "\n".join(str(part.get("text", "")) for part in text if isinstance(part, dict))
    result = json.loads(text[text.find("{"):text.rfind("}") + 1])
    if isinstance(result.get("bible"), dict):
        for key in project["bible"]:
            if key in result["bible"]:
                project["bible"][key] = str(result["bible"][key])
    if result.get("concept"):
        project["bible"]["core_concept"] = str(result["concept"])
    prompts = {p.get("shot_id"): p for p in result.get("shot_prompts", []) if isinstance(p, dict)}
    for shot in project["shots"]:
        proposal = prompts.get(shot["id"])
        if proposal:
            for key in ("prompt", "reference_prompt", "framing", "camera", "mode"):
                if proposal.get(key) is not None:
                    shot[key] = proposal[key]
    project["director"] = {"model": model, "brief": brief, "lyrics": lyrics, "result": result, "created_at": now()}
    save_project(project)
    return project


QUEUE = GenerationQueue(ROOT, WORKFLOWS, load_project, save_project)
UPSCALE = UpscaleManager(ROOT / "state/upscale.json")
RENDER_LOCK = threading.Lock()


def require_upscale_idle() -> None:
    if UPSCALE.running():
        raise RuntimeError("Wait for the RTX 3060 upscale to finish before starting another local media job")


def start_video_upscale(take_id: str) -> dict:
    require_upscale_idle()
    project = ensure_video_project()
    take = next((item for item in project["shots"][0].get("takes", [])
                 if item.get("id") == take_id), None)
    if take is None:
        raise ValueError("Choose a generated video take to upscale")
    base = project_dir(VIDEO_PROJECT_ID).resolve()
    source = (base / str(take.get("path") or "")).resolve()
    if not source.is_relative_to(base) or not source.is_file():
        raise ValueError("The selected video file no longer exists")

    snapshot = QUEUE.snapshot()
    if any(job.get("status") in ("queued", "running") for job in snapshot["jobs"]):
        raise RuntimeError("Wait for the local generation queue to finish before upscaling")
    engine = snapshot["engine"]
    if engine.get("running") or engine.get("pending"):
        raise RuntimeError("ComfyUI still has a generation in progress")
    if engine.get("online"):
        if not engine.get("owned"):
            raise RuntimeError("ComfyUI is running outside Local Video Desk; stop it before upscaling")
        QUEUE.engine.free_models()
        if not QUEUE.engine.stop_owned():
            raise RuntimeError("Could not stop Local Video Desk's ComfyUI process")
    unload_ollama_models()
    return UPSCALE.start(take_id, source, base / "generated")


def start_render(project_id: str, preset: str):
    if preset not in ("480p", "720p"):
        raise ValueError("unsupported render preset")
    if not RENDER_LOCK.acquire(blocking=False):
        raise RuntimeError("another final render is already running")

    try:
        project = load_project(project_id)
        project["render_state"] = {"status": "running", "preset": preset, "started_at": now()}
        save_project(project)

        def work():
            try:
                current = load_project(project_id)
                result = render(project_dir(project_id), current, preset)
                current = load_project(project_id)
                current.setdefault("renders", []).append(result)
                current["render_state"] = {"status": "complete", "result": result, "finished_at": now()}
                save_project(current)
            except Exception as exc:
                try:
                    current = load_project(project_id)
                    current["render_state"] = {"status": "failed", "error": str(exc), "finished_at": now()}
                    save_project(current)
                except Exception:
                    # A missing/unwritable project cannot persist an error status;
                    # log the failure while still releasing the render lock.
                    logging.exception("Cutroom could not persist a failed render state")
            finally:
                RENDER_LOCK.release()

        threading.Thread(target=work, daemon=True, name="studio-render").start()
    except BaseException:
        # Pre-flight (or thread creation) can fail before the worker owns the lock.
        RENDER_LOCK.release()
        raise


class Handler(BaseHTTPRequestHandler):
    server_version = "MusicVideoStudio/0.1"

    def log_message(self, fmt, *args):
        message = "%s - %s\n" % (self.log_date_time_string(), fmt % args)
        with (ROOT / "logs/app.log").open("a") as handle:
            handle.write(message)

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message):
        self._json({"error": str(message)}, status)

    def _body_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 16 * 1024 * 1024:
            raise ValueError("JSON request too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def _static(self, name):
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

    def _image_static(self, name):
        path = (IMAGE_STATIC / name).resolve()
        if IMAGE_STATIC.resolve() not in path.parents or not path.is_file():
            return self._error(404, "not found")
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _video_static(self, name):
        path = (VIDEO_STATIC / name).resolve()
        if VIDEO_STATIC.resolve() not in path.parents or not path.is_file():
            return self._error(404, "not found")
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _media(self, project_id, relative):
        base = project_dir(project_id).resolve()
        path = (base / urllib.parse.unquote(relative)).resolve()
        if base not in path.parents or not path.is_file():
            return self._error(404, "media not found")
        size = path.stat().st_size
        start, end = 0, size - 1
        range_header = self.headers.get("Range")
        status = 200
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if match and (match.group(1) or match.group(2)):
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(size - 1, int(last)) if last else size - 1
                else:
                    # A suffix range requests the last N bytes, not bytes 0..N.
                    start = max(0, size - int(last))
                    end = size - 1
                if size == 0 or start >= size or end < start:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
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
            try:
                while remaining:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path in ("/image-studio", "/image-studio/", "/image-studio/index.html"):
                return self._image_static("index.html")
            if path.startswith("/image-studio/static/"):
                return self._image_static(path.removeprefix("/image-studio/static/"))
            if path == "/image-studio/manifest.webmanifest":
                return self._image_static("manifest.webmanifest")
            if path == "/image-studio/sw.js":
                return self._image_static("sw.js")
            if path in ("/video-studio", "/video-studio/", "/video-studio/index.html"):
                return self._video_static("index.html")
            if path.startswith("/video-studio/static/"):
                return self._video_static(path.removeprefix("/video-studio/static/"))
            if path == "/video-studio/manifest.webmanifest":
                return self._video_static("manifest.webmanifest")
            if path == "/video-studio/sw.js":
                return self._video_static("sw.js")
            if path.startswith("/static/"):
                return self._static(path[8:])
            if path == "/manifest.webmanifest":
                return self._static("manifest.webmanifest")
            if path == "/sw.js":
                return self._static("sw.js")
            if path == "/api/health":
                return self._json({"ok": True, "version": "0.1.0", "root": str(ROOT),
                                   "projects": len(list_projects()), "queue": QUEUE.snapshot(),
                                   "upscale": UPSCALE.snapshot()})
            if path == "/api/projects":
                return self._json({"projects": list_projects()})
            if path == "/api/image-studio/state":
                return self._json(image_studio_state())
            if path == "/api/image-studio/models":
                return self._json({"models": openclaw_models(), "online": True})
            if path == "/api/video-studio/state":
                return self._json(video_studio_state())
            if path == "/api/video-studio/models":
                return self._json({"models": openclaw_models(), "online": True})
            if path == "/api/models":
                return self._json({"director_models": openclaw_models(), "video_backends": [
                    {"id": WAN_BACKEND, "name": "WAN 2.2 Rapid Q5_K", "ready": True,
                     "t2v": True, "i2v": False, "fps": WAN_FPS, "model": WAN_T2V_MODEL},
                    {"id": H3_BACKEND, "name": "MiniMax H3 FL2VA pruned NF4",
                     "ready": h3_ready(), "t2v": True, "i2v": True, "fps": H3_FPS,
                     "model": H3_MODEL, "native_audio": True},
                    {"id": H3_TURBO_BACKEND, "name": "MiniMax H3 NF4 Turbo + Sol + Spectrum",
                     "ready": h3_turbo_ready(), "t2v": True, "i2v": True, "fps": H3_FPS,
                     "model": H3_TURBO_MODEL, "native_audio": True},
                    {"id": "ltx-2.5", "name": "LTX-2.5 Local · legacy", "ready": True,
                     "t2v": True, "i2v": True, "fps": 24, "model": "LTX-2.5"}],
                    "default_video_backend": WAN_BACKEND,
                    "presets": {"compatibility": [768, 448], "draft": [832, 480], "quality": [1280, 704]},
                    "image_presets": image_preset_catalogue(),
                    "default_image_preset": DEFAULT_IMAGE_PRESET,
                    "valid_frames": [17, 33, 49, 65, 81],
                    "valid_frames_by_backend": {
                        WAN_BACKEND: [17, 33, 49, 65, 81],
                        H3_BACKEND: [22, 39, 56, 73, 90, 107, 124, 141, 158, 175, 192, 209, 226, 243, 260, 277, 294, 311, 328, 345, 362],
                        H3_TURBO_BACKEND: [22, 39, 56, 73, 90, 107, 124, 141, 158, 175, 192, 209, 226, 243, 260, 277, 294, 311, 328, 345, 362],
                        "ltx-2.5": [49, 73, 97, 121, 145],
                    }})
            match = re.fullmatch(r"/api/project/([^/]+)", path)
            if match:
                return self._json(load_project(match.group(1)))
            match = re.fullmatch(r"/media/([^/]+)/(.*)", path)
            if match:
                return self._media(match.group(1), match.group(2))
            return self._error(404, "route not found")
        except BrokenPipeError:
            pass
        except Exception as exc:
            self._error(500, exc)

    def do_POST(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            if path == "/api/projects/new":
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 < length <= MAX_UPLOAD:
                    return self._error(400, "invalid or oversized song upload")
                name = urllib.parse.unquote(self.headers.get("X-Project-Name") or "Untitled video")
                filename = urllib.parse.unquote(self.headers.get("X-Filename") or "source.audio")
                project = create_project(name, filename, self.rfile.read, length)
                return self._json(project, 201)
            if path == "/api/image-studio/expand":
                require_upscale_idle()
                body = self._body_json()
                return self._json(expand_image_prompt(body.get("model", ""), body.get("prompt", ""),
                                                     bool(body.get("editing"))))
            if path == "/api/video-studio/expand":
                require_upscale_idle()
                body = self._body_json()
                return self._json(expand_video_prompt(body.get("model", ""), body.get("prompt", "")))
            if path == "/api/image-studio/reference":
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 < length <= 20 * 1024**2:
                    return self._error(400, "Reference must be between 1 byte and 20 MB")
                data = self.rfile.read(length)
                if len(data) != length:
                    return self._error(400, "Reference upload was incomplete")
                filename = urllib.parse.unquote(self.headers.get("X-Filename") or "reference.png")
                return self._json(save_reference_image(data, filename), 201)
            if path == "/api/video-studio/reference":
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 < length <= 20 * 1024**2:
                    return self._error(400, "Reference must be between 1 byte and 20 MB")
                data = self.rfile.read(length)
                if len(data) != length:
                    return self._error(400, "Reference upload was incomplete")
                filename = urllib.parse.unquote(self.headers.get("X-Filename") or "reference.png")
                return self._json(save_reference_image(data, filename, VIDEO_PROJECT_ID), 201)
            if path == "/api/image-studio/show-output":
                body = self._body_json()
                return self._json(show_output_in_file_manager(body.get("path", "")))
            if path == "/api/image-studio/delete":
                body = self._body_json()
                return self._json(delete_image_studio_asset(body.get("id", "")))
            if path == "/api/video-studio/show-output":
                body = self._body_json()
                return self._json(show_output_in_file_manager(body.get("path", "")))
            if path == "/api/video-studio/delete":
                body = self._body_json()
                return self._json(delete_video_studio_take(body.get("id", "")))
            if path == "/api/video-studio/upscale":
                body = self._body_json()
                return self._json(start_video_upscale(str(body.get("take_id") or "")), 202)
            if path == "/api/video-studio/generate":
                require_upscale_idle()
                body = self._body_json()
                final_prompt = str(body.get("final_prompt") or "").strip()
                original_prompt = str(body.get("original_prompt") or final_prompt).strip()
                negative = str(body.get("negative") or "").strip()
                if not final_prompt:
                    return self._error(400, "Review or enter the final motion prompt before generating")
                if len(final_prompt) > 12_000 or len(negative) > 8_000:
                    return self._error(400, "Prompt is too long")
                video_model = str(body.get("video_model") or WAN_T2V_MODEL)
                if video_model in WAN_MODEL_FILES:
                    backend = WAN_BACKEND
                    formats = VIDEO_FORMATS
                    default_fps, default_steps = WAN_FPS, WAN_MIN_STEPS
                elif video_model == H3_MODEL:
                    backend = H3_BACKEND
                    formats = H3_VIDEO_FORMATS
                    default_fps, default_steps = H3_FPS, H3_DEFAULT_STEPS
                elif video_model == H3_TURBO_MODEL:
                    backend = H3_TURBO_BACKEND
                    formats = H3_VIDEO_FORMATS
                    default_fps, default_steps = H3_FPS, H3_TURBO_STEPS
                else:
                    return self._error(400, "Choose an installed local video model")
                quality = str(body.get("quality") or "480p")
                aspect = str(body.get("aspect") or "16:9")
                if quality not in formats or aspect not in formats[quality]:
                    return self._error(400, "Choose a supported resolution and aspect ratio")
                try:
                    duration = int(body.get("duration_seconds", 3))
                    fps = int(body.get("fps", default_fps))
                    steps = int(body.get("steps", default_steps))
                    seed = int(body.get("seed"))
                    batch = max(1, min(4, int(body.get("batch_count", 1))))
                except (TypeError, ValueError):
                    return self._error(400, "Duration, fps, steps, seed and take count must be numbers")
                max_seconds = H3_MAX_SECONDS if backend in (H3_BACKEND, H3_TURBO_BACKEND) else WAN_MAX_SECONDS
                if not 1 <= duration <= max_seconds:
                    return self._error(400, f"Duration must be a whole number from 1 to {max_seconds} seconds")
                if backend in (H3_BACKEND, H3_TURBO_BACKEND):
                    if fps != H3_FPS:
                        return self._error(400, "MiniMax H3 runs at 24 fps")
                    if (backend == H3_TURBO_BACKEND
                            and not H3_TURBO_MIN_STEPS <= steps <= H3_TURBO_MAX_STEPS):
                        return self._error(400, "MiniMax H3 Turbo steps must be from 4 to 24")
                    if backend == H3_BACKEND and not H3_MIN_STEPS <= steps <= H3_MAX_STEPS:
                        return self._error(400, "MiniMax H3 steps must be from 4 to 50")
                else:
                    if fps not in WAN_FPS_OPTIONS:
                        return self._error(400, "Frame rate must be 16 or 24 fps")
                    if not WAN_MIN_STEPS <= steps <= WAN_MAX_STEPS:
                        return self._error(400, "WAN steps must be from 4 to 20")
                if not 0 <= seed < 2**63:
                    return self._error(400, "Seed must be between 0 and 9223372036854775807")
                width, height = formats[quality][aspect]
                ensure_video_project()
                mode = str(body.get("mode") or "t2v")
                if mode not in ("t2v", "i2v"):
                    return self._error(400, "Choose Text or Image input")
                reference_id = body.get("reference_image_id")
                if mode == "i2v" and not reference_id:
                    return self._error(400, "Image input needs a reference image")
                reference = (reference_image_info(reference_id, VIDEO_PROJECT_ID)
                             if mode == "i2v" else None)
                payload = {
                    "project_id": VIDEO_PROJECT_ID, "video_model": video_model,
                    "kind": "video", "backend": backend, "mode": mode,
                    "reference_image": reference,
                    "shot_id": "shot-video-desk", "prompt": final_prompt, "negative": negative,
                    "original_prompt": original_prompt, "expanded_prompt": final_prompt,
                    "expander_model": body.get("expander_model") or None,
                    "prompt_mode": body.get("prompt_mode") or "edited",
                    "duration_seconds": duration, "quality": quality, "aspect_ratio": aspect,
                    "seed": seed, "fps": fps, "steps": steps,
                    "frames": h3_frames_for_seconds(duration) if backend in (H3_BACKEND, H3_TURBO_BACKEND) else duration * fps + 1,
                    "width": width, "height": height, "take_count": batch,
                }
                validate_video_job(payload, VIDEO_PROJECT_ID)
                jobs = QUEUE.add(payload)
                return self._json({"jobs": jobs}, 201)
            if path == "/api/image-studio/generate":
                require_upscale_idle()
                body = self._body_json()
                final_prompt = str(body.get("final_prompt") or "").strip()
                original_prompt = str(body.get("original_prompt") or final_prompt).strip()
                negative = str(body.get("negative") or "").strip()
                if not final_prompt:
                    return self._error(400, "Review or enter the final prompt before generating")
                if len(final_prompt) > 12_000 or len(negative) > 8_000:
                    return self._error(400, "Prompt is too long")
                preset = str(body.get("preset") or DEFAULT_IMAGE_PRESET)
                try:
                    seed = int(body.get("seed"))
                    batch = max(1, min(4, int(body.get("batch_count", 1))))
                except (TypeError, ValueError):
                    return self._error(400, "Seed and batch count must be numbers")
                if not 0 <= seed < 2**63:
                    return self._error(400, "Seed must be between 0 and 9223372036854775807")
                width, height = resolve_image_dimensions(
                    preset, body.get("custom_width"), body.get("custom_height"))
                ensure_image_project()
                reference_id = body.get("reference_image_id")
                reference = reference_image_info(reference_id) if reference_id is not None else None
                jobs = QUEUE.add({
                    "project_id": IMAGE_PROJECT_ID,
                    "kind": "art",
                    "asset_kind": "standalone image",
                    "reference_image": reference,
                    "prompt": final_prompt,
                    "negative": negative,
                    "original_prompt": original_prompt,
                    "expanded_prompt": final_prompt,
                    "expander_model": body.get("expander_model") or None,
                    "prompt_mode": body.get("prompt_mode") or "edited",
                    "seed": seed,
                    "width": width,
                    "height": height,
                    "image_preset": preset,
                    "steps": 25,
                    "cfg": 1.0,
                    "take_count": batch,
                })
                return self._json({"jobs": jobs}, 201)
            match = re.fullmatch(r"/api/project/([^/]+)/analyse", path)
            if match:
                return self._json(analyse_project(match.group(1)))
            match = re.fullmatch(r"/api/project/([^/]+)/save", path)
            if match:
                incoming = self._body_json()
                if incoming.get("id") != match.group(1):
                    return self._error(400, "project id mismatch")
                save_project(incoming)
                return self._json(load_project(match.group(1)))
            match = re.fullmatch(r"/api/project/([^/]+)/director", path)
            if match:
                body = self._body_json()
                return self._json(director(load_project(match.group(1)), body.get("model", ""),
                                           body.get("brief", ""), body.get("lyrics", "")))
            match = re.fullmatch(r"/api/project/([^/]+)/asset/upload", path)
            if match:
                project = load_project(match.group(1))
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 < length <= 100 * 1024**2:
                    return self._error(400, "invalid asset upload")
                filename = urllib.parse.unquote(self.headers.get("X-Filename") or "reference.png")
                ext = Path(filename).suffix.lower()
                if ext not in (".png", ".jpg", ".jpeg", ".webp"):
                    return self._error(400, "reference must be PNG, JPEG or WebP")
                asset_id = "asset-" + uuid.uuid4().hex[:10]
                target = project_dir(project["id"]) / "references" / (asset_id + ext)
                target.write_bytes(self.rfile.read(length))
                asset = {"id": asset_id, "kind": self.headers.get("X-Asset-Kind") or "shot reference",
                         "path": str(target.relative_to(project_dir(project["id"]))), "prompt": "Imported reference",
                         "seed": None, "model": "import", "backend": "file", "created_at": now(),
                         "project_id": project["id"], "shot_id": self.headers.get("X-Shot-Id") or None,
                         "approved": True, "favourite": False, "state": "approved"}
                project["assets"].append(asset)
                save_project(project)
                return self._json(asset, 201)
            match = re.fullmatch(r"/api/project/([^/]+)/queue", path)
            if match:
                require_upscale_idle()
                body = self._body_json()
                body["project_id"] = match.group(1)
                if body.get("kind") not in ("art", "video"):
                    return self._error(400, "queue kind must be art or video")
                if body.get("kind") == "art":
                    preset = body.get("image_preset")
                    if preset:
                        width, height = resolve_image_dimensions(
                            preset, body.get("width"), body.get("height"))
                    else:
                        width, height = validate_image_dimensions(
                            body.get("width", 768), body.get("height", 448))
                        preset = preset_for_dimensions(width, height)
                    body.update(width=width, height=height, image_preset=preset)
                else:
                    validate_video_job(body, match.group(1))
                created = QUEUE.add(body)
                return self._json({"jobs": created}, 201)
            if path == "/api/queue/action":
                body = self._body_json()
                return self._json(QUEUE.action(body.get("action", ""), body.get("job_id")))
            match = re.fullmatch(r"/api/project/([^/]+)/asset/([^/]+)/state", path)
            if match:
                project = load_project(match.group(1))
                body = self._body_json()
                asset = next(a for a in project["assets"] if a["id"] == match.group(2))
                for key in ("state", "approved", "favourite", "kind", "shot_id"):
                    if key in body:
                        asset[key] = body[key]
                save_project(project)
                return self._json(project)
            match = re.fullmatch(r"/api/project/([^/]+)/take/([^/]+)/state", path)
            if match:
                project = load_project(match.group(1))
                body = self._body_json()
                found = None
                for shot in project["shots"]:
                    take = next((t for t in shot.get("takes", []) if t["id"] == match.group(2)), None)
                    if take:
                        found = take
                        take["state"] = body.get("state", take["state"])
                        if take["state"] == "keep":
                            shot["selected_take_id"] = take["id"]
                            item = next((i for i in project["timeline"]["items"] if i["shot_id"] == shot["id"]), None)
                            if item:
                                item["take_id"] = take["id"]
                        if take["state"] == "salvage":
                            source = project_dir(project["id"]) / take["path"]
                            target = project_dir(project["id"]) / "salvage" / source.name
                            if source.exists() and not target.exists():
                                shutil.copy2(source, target)
                            take["salvage_path"] = str(target.relative_to(project_dir(project["id"])))
                        break
                if not found:
                    return self._error(404, "take not found")
                save_project(project)
                return self._json(project)
            match = re.fullmatch(r"/api/project/([^/]+)/render", path)
            if match:
                body = self._body_json()
                start_render(match.group(1), body.get("preset", "720p"))
                return self._json({"status": "running"}, 202)
            if path == "/api/engine/start":
                return self._json({"started": QUEUE.engine.start(), "engine": QUEUE.engine.status()})
            if path == "/api/engine/stop":
                return self._json({"stopped": QUEUE.engine.stop_owned(), "engine": QUEUE.engine.status()})
            return self._error(404, "route not found")
        except ValueError as exc:
            self._error(400, exc)
        except Exception as exc:
            self._error(500, exc)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"AI Music Video Studio -> http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
