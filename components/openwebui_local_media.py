"""Shared Open WebUI bridge for local MiniMax, Qwen and WAN generation."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

STACK_ROOT = Path(os.environ.get("RHIZOME_STACK_ROOT", "~/.local/share/rhizome-stack")).expanduser()
MUSIC = os.environ.get("MINIMAX_MUSIC_URL", "http://127.0.0.1:8830").rstrip("/")
IMAGE = os.environ.get("QWEN_IMAGE_DESK_URL", "http://127.0.0.1:8841").rstrip("/")
VIDEO = os.environ.get("WAN_VIDEO_DESK_API_URL", "http://127.0.0.1:8840").rstrip("/")
VIDEO_DESK = os.environ.get("WAN_VIDEO_DESK_URL", VIDEO + "/video-studio/").rstrip("/") + "/"
COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
OLLAMA = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
STRATA = os.environ.get("STRATA_BASE_URL", "http://127.0.0.1:47831").rstrip("/")
STRATA_ENDPOINTS = tuple(dict.fromkeys(
    endpoint.strip().rstrip("/")
    for endpoint in os.environ.get(
        "STRATA_BASE_URLS", STRATA + ",http://127.0.0.1:47832"
    ).split(",")
    if endpoint.strip()
))
STRATA_UNLOAD_WAIT = int(os.environ.get("STRATA_MEDIA_UNLOAD_WAIT", "120"))
OPENWEBUI_PUBLIC = os.environ.get("OPENWEBUI_PUBLIC_URL", "http://127.0.0.1:8080").rstrip("/")
COMFY_OUTPUT = Path(os.environ.get("COMFY_OUTPUT", STACK_ROOT / "creative/ComfyUI/output"))
WAN_PROJECT = (Path(os.environ.get("WAN_DESK_STATE", STACK_ROOT / "creative/state/wan-video-desk"))
               / "projects/wan-video-studio")
STATE = STACK_ROOT / "state/openwebui-media-jobs"
SERVICES = {
    "music": os.environ.get("MINIMAX_MUSIC_SERVICE", "minimax-music-api.service"),
    "image": os.environ.get("QWEN_IMAGE_DESK_SERVICE", "qwen-image-desk.service"),
    "video": os.environ.get("WAN_VIDEO_DESK_SERVICE", "wan-video-desk.service"),
}
APP_URLS = {"music": MUSIC, "image": IMAGE, "video": VIDEO}
HEALTH_ENDPOINTS = {"music": "/api/health", "image": "/api/image-studio/health", "video": "/api/health"}
STOP_ENDPOINTS = {"music": "/api/engine/stop", "image": "/api/image-studio/engine/stop",
                  "video": "/api/engine/stop"}


def request(method, url, body=None, timeout=30, headers=None):
    data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def health(kind):
    if kind not in APP_URLS:
        raise ValueError(f"Unknown local media kind: {kind}")
    value = request("GET", APP_URLS[kind] + HEALTH_ENDPOINTS[kind], timeout=5)
    if not isinstance(value, dict) or not isinstance(value.get("busy"), bool):
        raise RuntimeError("Generation app returned an invalid health response")
    return value


def connection_refused(exc):
    """Only a refused TCP connection establishes that a local service is down."""
    return isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, ConnectionRefusedError)


def ensure_app(kind):
    try:
        health(kind)
        return
    except urllib.error.URLError as exc:
        if not connection_refused(exc):
            raise
        subprocess.run(["systemctl", "--user", "start", SERVICES[kind]], check=True,
                       capture_output=True, timeout=20)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            health(kind)
            return
        except urllib.error.URLError as exc:
            if not connection_refused(exc):
                raise
            time.sleep(1)
    raise RuntimeError("The local generation app did not become ready")


def comfy_idle():
    try:
        value = request("GET", COMFY + "/queue", timeout=5)
    except urllib.error.URLError as exc:
        if connection_refused(exc):
            return True
        raise
    if not isinstance(value, dict) or any(
            not isinstance(value.get(key), list) for key in ("queue_running", "queue_pending")):
        raise RuntimeError("Could not establish ComfyUI queue state; no models were released")
    return not value["queue_running"] and not value["queue_pending"]


def ollama_runners():
    """An unknown runner catalogue must never count as an available GPU."""
    value = request("GET", OLLAMA + "/api/ps", timeout=8)
    if not isinstance(value, dict) or not isinstance(value.get("models"), list):
        raise RuntimeError("Could not establish Ollama runner state; GPU hand-over stopped")
    names = []
    for model in value["models"]:
        name = (model.get("name") or model.get("model")) if isinstance(model, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError("Ollama returned an invalid runner; GPU hand-over stopped")
        names.append(name)
    return names


def selected_model_id(metadata):
    """Return Open WebUI's selected model without trusting a display label."""
    metadata = metadata or {}
    model = metadata.get("model")
    if isinstance(model, dict):
        model = model.get("id") or model.get("model")
    if not isinstance(model, str) or not model.strip():
        model = metadata.get("model_id")
    return model.strip() if isinstance(model, str) else ""


def strata_state():
    """Read and validate all Strata allocations, returning the loaded one.

    Ollama's runner list says nothing about Strata, so an unknown Strata state is
    a hard stop rather than permission to start another GPU workload. The two
    local profiles are mutually exclusive; seeing both loaded is also unsafe.
    """
    states = []
    for base in STRATA_ENDPOINTS:
        value = request("GET", base + "/health", timeout=8)
        if (not isinstance(value, dict) or value.get("service") != "strata" or
                not isinstance(value.get("loaded"), bool)):
            raise RuntimeError("Could not establish Strata model state; GPU hand-over stopped")
        model = value.get("model")
        if model is not None and not isinstance(model, str):
            raise RuntimeError("Strata returned an invalid model identity; GPU hand-over stopped")
        states.append({"loaded": value["loaded"], "model": model or "", "base": base})
    loaded = [state for state in states if state["loaded"]]
    if len(loaded) > 1:
        raise RuntimeError("More than one Strata model is loaded; GPU hand-over stopped")
    return loaded[0] if loaded else {"loaded": False, "model": "", "base": STRATA}


def unload_strata(state):
    if not state["loaded"]:
        return False
    base = state.get("base", STRATA)
    try:
        result = request(
            "POST", base + "/v1/unload?" + urllib.parse.urlencode({"wait": STRATA_UNLOAD_WAIT}),
            {}, timeout=STRATA_UNLOAD_WAIT + 15,
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            raise RuntimeError(
                "Strata still has an active or queued inference request; no GPU work was interrupted"
            ) from exc
        raise
    if not isinstance(result, dict) or result.get("status") not in ("unloaded", "already unloaded"):
        raise RuntimeError("Strata did not acknowledge model unloading; GPU hand-over stopped")
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if not strata_state()["loaded"]:
            return True
        time.sleep(0.5)
    raise RuntimeError("Strata acknowledged unloading but still reports the model loaded")


def restore_chat_backend(handoff):
    """Restore only the chat allocation that this request actually released."""
    if not isinstance(handoff, dict) or not handoff.get("strata_was_loaded"):
        return
    current = strata_state()
    if current["loaded"]:
        return
    base = handoff.get("strata_base", STRATA)
    try:
        result = request("POST", base + "/v1/load", {}, timeout=600)
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            raise RuntimeError("Strata could not restore the chat model because another request is active") from exc
        raise
    if not isinstance(result, dict) or result.get("status") != "loaded":
        raise RuntimeError("Strata did not acknowledge chat-model restoration")
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        state = strata_state()
        if state["loaded"] and state.get("base", STRATA) == base:
            return
        time.sleep(0.5)
    raise RuntimeError("Strata acknowledged loading but never reported the chat model ready")


def hand_over(metadata=None):
    for kind in ("music", "image", "video"):
        try:
            value = health(kind)
        except urllib.error.URLError as exc:
            if connection_refused(exc):
                continue
            raise
        jobs = value.get("jobs") or (value.get("queue") or {}).get("jobs") or []
        if value.get("busy") or value.get("starting") or any(
                job.get("status") in ("queued", "running") for job in jobs):
            raise RuntimeError("A local media job is already running. Let it finish before requesting another.")
    if not comfy_idle():
        raise RuntimeError("ComfyUI is busy with another job; no work was interrupted.")
    model_id = selected_model_id(metadata)
    strata = strata_state()
    handoff = {
        "selected_model": model_id,
        "selected_backend": "strata" if model_id.startswith(
            ("openclaw/strata/", "strata/", "openclaw/strata-s/", "strata-s/")
        ) else "other",
        "strata_model": strata["model"],
        "strata_base": strata.get("base", STRATA),
        "strata_was_loaded": strata["loaded"],
        "ollama_models": [],
    }
    try:
        unload_strata(strata)
    except Exception:
        raise
    loaded = ollama_runners()
    names = []
    try:
        for name in loaded:
            request("POST", OLLAMA + "/api/generate", {"model": name, "keep_alive": 0}, timeout=60)
            names.append(name)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            remaining = ollama_runners()
            if not remaining:
                handoff["ollama_models"] = names
                return handoff
            time.sleep(0.5)
        raise RuntimeError(f"Could not free the local GPU: Ollama still has models loaded: {remaining}")
    except Exception:
        # If Ollama verification fails after Strata was released, put the chat
        # model back before propagating the error. No media engine has started.
        restore_chat_backend(handoff)
        raise


def release_models(kind):
    if not comfy_idle():
        raise RuntimeError("ComfyUI still has queued work; generation models were not interrupted")
    try:
        request("POST", COMFY + "/free", {"unload_models": True, "free_memory": True}, timeout=45)
    except urllib.error.URLError as exc:
        if connection_refused(exc):
            return
        raise
    if kind not in APP_URLS:
        raise ValueError(f"Unknown local media kind: {kind}")
    request("POST", APP_URLS[kind] + STOP_ENDPOINTS[kind], {}, timeout=45)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            request("GET", COMFY + "/queue", timeout=2)
        except urllib.error.URLError as exc:
            if connection_refused(exc):
                return
            raise
        time.sleep(0.5)
    raise RuntimeError("ComfyUI did not stop cleanly, so the chat model was not resumed")


@asynccontextmanager
async def media_lock(emit):
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "generation.lock").open("a") as lock:
        deadline = time.monotonic() + 1800
        announced = False
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not announced:
                    await emit("Waiting for the current local media request…")
                    announced = True
                if time.monotonic() >= deadline:
                    raise TimeoutError("Another local media request is still running")
                await asyncio.sleep(1)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def save_job(path, record):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix="." + path.name + ".", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            temporary.replace(path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)


async def import_reference(kind, file_id, user):
    from open_webui.config import UPLOAD_DIR
    from open_webui.models.files import Files
    entry = await Files.get_file_by_id(file_id)
    if not entry or entry.user_id != user["id"] or not (entry.meta or {}).get("content_type", "").startswith("image/"):
        raise ValueError("Reference must be an image uploaded by you in Open WebUI")
    path = Path(entry.path).resolve(strict=True)
    if not path.is_relative_to(Path(UPLOAD_DIR).resolve()) or path.stat().st_size > 20 * 1024**2:
        raise ValueError("Reference must be a stored upload no larger than 20 MB")
    endpoint = "/api/video-studio/reference" if kind == "video" else "/api/image-studio/reference"
    app = VIDEO if kind == "video" else IMAGE
    return await asyncio.to_thread(
        request, "POST", app + endpoint, path.read_bytes(), 30,
        {"Content-Type": "application/octet-stream", "X-Filename": urllib.parse.quote(entry.filename)},
    )


async def attach_result(kind, source, user, metadata, emitter, source_label=None):
    from open_webui.config import UPLOAD_DIR
    from open_webui.models.files import Files, FileForm
    from open_webui.models.chats import Chats
    from open_webui.utils.chat_id import is_saved_chat_id
    path = Path(source).resolve(strict=True)
    media = {
        "music": (COMFY_OUTPUT, "audio/mpeg", "MiniMax Music 3", "file"),
        "image": (COMFY_OUTPUT, "image/png", "Qwen Image Desk", "image"),
        "video": (WAN_PROJECT / "generated", "video/mp4", "WAN Video Desk", "file"),
    }
    if kind not in media:
        raise ValueError(f"Unknown local media kind: {kind}")
    allowed, mime, default_source_label, attachment_type = media[kind]
    source_label = source_label or default_source_label
    if not path.is_relative_to(allowed.resolve()):
        raise ValueError("Generator returned an unexpected output path")
    file_id = str(uuid.uuid4())
    target = Path(UPLOAD_DIR) / (file_id + "_" + path.name)
    await asyncio.to_thread(shutil.copy2, path, target)
    entry = await Files.insert_new_file(user["id"], FileForm(
        id=file_id, filename=path.name, path=str(target), data={"status": "completed"},
        meta={"name": path.name, "content_type": mime, "size": target.stat().st_size,
              "source": source_label},
    ))
    if not entry:
        raise RuntimeError("Could not register the generated file with Open WebUI")
    url = f"/api/v1/files/{file_id}/content"
    # Open WebUI's supported audio path is a native File card. Its Preview
    # action renders the MP3 player and survives saved-chat reloads.
    attached = {"id": file_id, "type": attachment_type,
                "url": url, "name": path.name, "content_type": mime}
    chat_id, message_id = metadata.get("chat_id"), metadata.get("message_id")
    if is_saved_chat_id(chat_id) and message_id:
        await Chats.add_message_files_by_id_and_message_id(chat_id, message_id, [attached])
    if emitter:
        await emitter({"type": "chat:message:files", "data": {"files": [attached]}})
    return {"file_id": file_id, "url": url, "name": path.name, "path": str(path)}


def retry_key(kind, payload, user_id, metadata, reference_file_id="", idempotency_key=""):
    metadata = metadata or {}
    logical_id = str(metadata.get("message_id") or idempotency_key or "").strip()
    if not logical_id:
        raise ValueError(
            "A stable message ID or idempotency key is required before starting local generation"
        )
    if len(logical_id) > 256:
        raise ValueError("The idempotency key must be 256 characters or fewer")
    identity = [user_id, metadata.get("chat_id"), logical_id, kind, payload, reference_file_id]
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


async def generate(kind, payload, user, metadata=None, emitter=None, reference_file_id="",
                   idempotency_key=""):
    metadata = metadata or {}
    # Seed/reference augmentation must not change the caller's retry identity.
    payload = dict(payload)

    async def status(text, done=False):
        if emitter:
            await emitter({"type": "status", "data": {"description": text, "done": done}})

    if not user or not user.get("id"):
        return json.dumps({"status": "error", "error": "An authenticated Open WebUI user is required"})
    labels = {"music": "MiniMax Music 3", "image": "Qwen Image Desk", "video": "WAN Video Desk"}
    if kind not in labels:
        return json.dumps({"status": "error", "error": f"Unknown local media kind: {kind}"})
    label = ("MiniMax H3" if kind == "video" and
             payload.get("video_model") == "minimax-h3-fl2va-pruned-nf4.safetensors"
             else labels[kind])
    try:
        key = retry_key(kind, payload, user["id"], metadata, reference_file_id, idempotency_key)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)})
    try:
        async with media_lock(status):
            receipt = STATE / (key + ".json")
            record = json.loads(receipt.read_text()) if receipt.exists() else {}
            if record.get("status") == "done":
                return json.dumps(record["result"])
            if record.get("status") == "submitting":
                raise RuntimeError("Previous submission has an uncertain acknowledgement. Check the local app; it will not be submitted twice.")
            if record.get("status") == "failed":
                raise RuntimeError(record.get("error") or "Generation failed")
            await asyncio.to_thread(ensure_app, kind)
            if not record:
                await status(f"Preparing {label} locally…")
                handoff = await asyncio.to_thread(hand_over, metadata)
                if reference_file_id:
                    reference = await import_reference(kind, reference_file_id, user)
                    payload["reference_image_id"] = reference["id"]
                record = {"status": "submitting", "kind": kind, "created_at": time.time(),
                          "chat_handoff": handoff,
                          "unloaded_chat_models": handoff.get("ollama_models", [])}
                save_job(receipt, record)
                if kind == "music":
                    submitted = await asyncio.to_thread(request, "POST", MUSIC + "/api/generate", payload, 150)
                    record["job_id"] = submitted["prompt_id"]
                elif kind == "image":
                    payload.setdefault("seed", secrets.randbits(48))
                    submitted = await asyncio.to_thread(request, "POST", IMAGE + "/api/image-studio/generate", payload, 30)
                    record["job_id"] = submitted["jobs"][0]["id"]
                else:
                    payload.setdefault("seed", secrets.randbits(48))
                    submitted = await asyncio.to_thread(request, "POST", VIDEO + "/api/video-studio/generate", payload, 30)
                    record["job_id"] = submitted["jobs"][0]["id"]
                record["status"] = "running"
                save_job(receipt, record)
            await status(f"{label} is generating…")
            h3_video = (kind == "video" and
                        payload.get("video_model") == "minimax-h3-fl2va-pruned-nf4.safetensors")
            deadline = time.monotonic() + (21600 if h3_video else 1800)
            previous_stage = None
            while time.monotonic() < deadline:
                # Once the engine stops, its in-memory history may disappear.
                # Recover file registration from the receipt, without generating again.
                if record.get("status") == "generated":
                    source = record["source"]
                    break
                await asyncio.sleep(2)
                try:
                    if kind == "music":
                        result = await asyncio.to_thread(
                            request, "GET", MUSIC + "/api/status?" + urllib.parse.urlencode({"prompt_id": record["job_id"]}), None, 20)
                        done, failed = result.get("state") == "done", result.get("state") == "error"
                        source, stage = result.get("path"), "Generating music"
                    elif kind == "image":
                        snapshot = await asyncio.to_thread(request, "GET", IMAGE + "/api/image-studio/health", None, 20)
                        result = next((item for item in snapshot.get("jobs", []) if item["id"] == record["job_id"]), None)
                        if not result:
                            raise RuntimeError("Image job disappeared; it has not been resubmitted")
                        done = result["status"] == "complete"
                        failed = result["status"] in ("failed", "cancelled")
                        asset = next((item for item in snapshot.get("assets", []) if item["id"] == result.get("asset_id")), {})
                        source, stage = asset.get("absolute_path"), result.get("stage", "Generating image")
                    else:
                        snapshot = await asyncio.to_thread(request, "GET", VIDEO + "/api/video-studio/state", None, 20)
                        result = next((item for item in snapshot.get("jobs", []) if item["id"] == record["job_id"]), None)
                        if not result:
                            raise RuntimeError("WAN Video Desk job disappeared; it has not been resubmitted")
                        done = result["status"] == "complete"
                        failed = result["status"] in ("failed", "cancelled")
                        result_path = str((result.get("result") or {}).get("path") or "")
                        source = str(WAN_PROJECT / result_path) if result_path else None
                        stage = result.get("stage", "Generating video")
                except (urllib.error.URLError, TimeoutError):
                    continue
                if failed:
                    record.update(status="failed", error=result.get("error") or "Generation failed", finished_at=time.time())
                    save_job(receipt, record)
                    await asyncio.to_thread(release_models, kind)
                    await asyncio.to_thread(restore_chat_backend, record.get("chat_handoff"))
                    raise RuntimeError(record["error"])
                if done:
                    if not source:
                        raise RuntimeError("Generator completed without a result path")
                    record.update(status="generated", source=source,
                                  generator_result=result.get("result") or {})
                    save_job(receipt, record)
                    break
                if stage != previous_stage:
                    await status(f"{label} · {stage}")
                    previous_stage = stage
            else:
                limit = "six hours" if h3_video else "30 minutes"
                raise TimeoutError(f"Generation is still pending after {limit}. Check the local app; no duplicate was started.")
            await asyncio.to_thread(release_models, kind)
            await asyncio.to_thread(restore_chat_backend, record.get("chat_handoff"))
            media = await attach_result(kind, source, user, metadata, emitter, label)
            await asyncio.sleep(1)
            answer = {"status": "success", "generator": label, **media,
                      "message": "The generated file is attached to this chat. Briefly confirm completion and include the download link. Do not generate again."}
            if kind == "music":
                answer["message"] += " Tell the user the attached MP3 card opens the built-in player. Do not output raw HTML."
            elif kind == "video":
                answer.update(
                    desk_url=VIDEO_DESK,
                    take_id=(record.get("generator_result") or {}).get("id"),
                    download_url=OPENWEBUI_PUBLIC + media["url"],
                )
                answer["message"] += (
                    " Open WebUI embeds the attached MP4 in its native HTML5 video player. "
                    "Make download_url a clickable Markdown link, not inline code. Also include "
                    "the WAN Video Desk link so the user can open, edit, reuse or rerun the take."
                )
            record.update(status="done", result=answer, finished_at=time.time())
            save_job(receipt, record)
            await status(f"{label} complete.", True)
            return json.dumps(answer)
    except Exception as exc:
        await status(f"{label}: {exc}", True)
        return json.dumps({"status": "error", "generator": label, "error": str(exc),
                           "message": "Report this accurately. Do not claim a file was created and do not blindly repeat the request."})
