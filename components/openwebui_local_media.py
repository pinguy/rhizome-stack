"""Shared Open WebUI bridge for local MiniMax Music 3 and Qwen Image Desk."""
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
COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
OLLAMA = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
COMFY_OUTPUT = Path(os.environ.get("COMFY_OUTPUT", STACK_ROOT / "creative/ComfyUI/output"))
STATE = STACK_ROOT / "state/openwebui-media-jobs"
SERVICES = {
    "music": os.environ.get("MINIMAX_MUSIC_SERVICE", "minimax-music-api.service"),
    "image": os.environ.get("QWEN_IMAGE_DESK_SERVICE", "qwen-image-desk.service"),
}


def request(method, url, body=None, timeout=30, headers=None):
    data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def health(kind):
    endpoint = "/api/health" if kind == "music" else "/api/image-studio/health"
    return request("GET", (MUSIC if kind == "music" else IMAGE) + endpoint, timeout=5)


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
        except (urllib.error.URLError, TimeoutError):
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


def hand_over():
    for kind in ("music", "image"):
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
    loaded = request("GET", OLLAMA + "/api/ps", timeout=8).get("models", [])
    names = []
    for model in loaded:
        name = model.get("name") or model.get("model")
        if name:
            request("POST", OLLAMA + "/api/generate", {"model": name, "keep_alive": 0}, timeout=60)
            names.append(name)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        remaining = request("GET", OLLAMA + "/api/ps", timeout=8).get("models", [])
        if not remaining:
            return names
        time.sleep(0.5)
    remaining_names = [item.get("name") or item.get("model") for item in remaining]
    raise RuntimeError(f"Could not free the local GPU: Ollama still has models loaded: {remaining_names}")


def release_models(kind):
    if not comfy_idle():
        raise RuntimeError("ComfyUI still has queued work; generation models were not interrupted")
    try:
        request("POST", COMFY + "/free", {"unload_models": True, "free_memory": True}, timeout=45)
    except urllib.error.URLError as exc:
        if connection_refused(exc):
            return
        raise
    app = MUSIC if kind == "music" else IMAGE
    endpoint = "/api/engine/stop" if kind == "music" else "/api/image-studio/engine/stop"
    request("POST", app + endpoint, {}, timeout=45)
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


async def import_reference(file_id, user):
    from open_webui.config import UPLOAD_DIR
    from open_webui.models.files import Files
    entry = await Files.get_file_by_id(file_id)
    if not entry or entry.user_id != user["id"] or not (entry.meta or {}).get("content_type", "").startswith("image/"):
        raise ValueError("Reference must be an image uploaded by you in Open WebUI")
    path = Path(entry.path).resolve(strict=True)
    if not path.is_relative_to(Path(UPLOAD_DIR).resolve()) or path.stat().st_size > 20 * 1024**2:
        raise ValueError("Reference must be a stored upload no larger than 20 MB")
    return await asyncio.to_thread(
        request, "POST", IMAGE + "/api/image-studio/reference", path.read_bytes(), 30,
        {"Content-Type": "application/octet-stream", "X-Filename": urllib.parse.quote(entry.filename)},
    )


async def attach_result(kind, source, user, metadata, emitter):
    from open_webui.config import UPLOAD_DIR
    from open_webui.models.files import Files, FileForm
    from open_webui.models.chats import Chats
    from open_webui.utils.chat_id import is_saved_chat_id
    path = Path(source).resolve(strict=True)
    if not path.is_relative_to(COMFY_OUTPUT.resolve()):
        raise ValueError("Generator returned an unexpected output path")
    file_id = str(uuid.uuid4())
    target = Path(UPLOAD_DIR) / (file_id + "_" + path.name)
    await asyncio.to_thread(shutil.copy2, path, target)
    mime = "audio/mpeg" if kind == "music" else "image/png"
    entry = await Files.insert_new_file(user["id"], FileForm(
        id=file_id, filename=path.name, path=str(target), data={"status": "completed"},
        meta={"name": path.name, "content_type": mime, "size": target.stat().st_size,
              "source": "MiniMax Music 3" if kind == "music" else "Qwen Image Desk"},
    ))
    if not entry:
        raise RuntimeError("Could not register the generated file with Open WebUI")
    url = f"/api/v1/files/{file_id}/content"
    # Open WebUI's supported audio path is a native File card. Its Preview
    # action renders the MP3 player and survives saved-chat reloads.
    attached = {"id": file_id, "type": "file" if kind == "music" else "image",
                "url": url, "name": path.name, "content_type": mime}
    chat_id, message_id = metadata.get("chat_id"), metadata.get("message_id")
    if is_saved_chat_id(chat_id) and message_id:
        await Chats.add_message_files_by_id_and_message_id(chat_id, message_id, [attached])
    if emitter:
        await emitter({"type": "chat:message:files", "data": {"files": [attached]}})
    return {"file_id": file_id, "url": url, "name": path.name, "path": str(path)}


async def generate(kind, payload, user, metadata=None, emitter=None, reference_file_id=""):
    metadata = metadata or {}
    # Seed/reference augmentation must not change the caller's retry identity.
    payload = dict(payload)

    async def status(text, done=False):
        if emitter:
            await emitter({"type": "status", "data": {"description": text, "done": done}})

    if not user or not user.get("id"):
        return json.dumps({"status": "error", "error": "An authenticated Open WebUI user is required"})
    label = "MiniMax Music 3" if kind == "music" else "Qwen Image Desk"
    identity = [user["id"], metadata.get("chat_id"), metadata.get("message_id") or str(uuid.uuid4()),
                kind, payload, reference_file_id]
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
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
                unloaded = await asyncio.to_thread(hand_over)
                if reference_file_id:
                    reference = await import_reference(reference_file_id, user)
                    payload["reference_image_id"] = reference["id"]
                record = {"status": "submitting", "kind": kind, "created_at": time.time(),
                          "unloaded_chat_models": unloaded}
                save_job(receipt, record)
                if kind == "music":
                    submitted = await asyncio.to_thread(request, "POST", MUSIC + "/api/generate", payload, 150)
                    record["job_id"] = submitted["prompt_id"]
                else:
                    payload["seed"] = secrets.randbits(48)
                    submitted = await asyncio.to_thread(request, "POST", IMAGE + "/api/image-studio/generate", payload, 30)
                    record["job_id"] = submitted["jobs"][0]["id"]
                record["status"] = "running"
                save_job(receipt, record)
            await status(f"{label} is generating…")
            deadline = time.monotonic() + 1800
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
                    else:
                        snapshot = await asyncio.to_thread(request, "GET", IMAGE + "/api/image-studio/health", None, 20)
                        result = next((item for item in snapshot.get("jobs", []) if item["id"] == record["job_id"]), None)
                        if not result:
                            raise RuntimeError("Image job disappeared; it has not been resubmitted")
                        done = result["status"] == "complete"
                        failed = result["status"] in ("failed", "cancelled")
                        asset = next((item for item in snapshot.get("assets", []) if item["id"] == result.get("asset_id")), {})
                        source, stage = asset.get("absolute_path"), result.get("stage", "Generating image")
                except (urllib.error.URLError, TimeoutError):
                    continue
                if failed:
                    record.update(status="failed", error=result.get("error") or "Generation failed", finished_at=time.time())
                    save_job(receipt, record)
                    await asyncio.to_thread(release_models, kind)
                    raise RuntimeError(record["error"])
                if done:
                    if not source:
                        raise RuntimeError("Generator completed without a result path")
                    record.update(status="generated", source=source)
                    save_job(receipt, record)
                    break
                if stage != previous_stage:
                    await status(f"{label} · {stage}")
                    previous_stage = stage
            else:
                raise TimeoutError("Generation is still pending after 30 minutes. Check the local app; no duplicate was started.")
            await asyncio.to_thread(release_models, kind)
            media = await attach_result(kind, source, user, metadata, emitter)
            await asyncio.sleep(1)
            answer = {"status": "success", "generator": label, **media,
                      "message": "The generated file is attached to this chat. Briefly confirm completion and include the download link. Do not generate again."}
            if kind == "music":
                answer["message"] += " Tell the user the attached MP3 card opens the built-in player. Do not output raw HTML."
            record.update(status="done", result=answer, finished_at=time.time())
            save_job(receipt, record)
            await status(f"{label} complete.", True)
            return json.dumps(answer)
    except Exception as exc:
        await status(f"{label}: {exc}", True)
        return json.dumps({"status": "error", "generator": label, "error": str(exc),
                           "message": "Report this accurately. Do not claim a file was created and do not blindly repeat the request."})
