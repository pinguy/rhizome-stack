"""Open WebUI tool for local MiniMax Music 3 with GPU handover.

The chat model has already completed its tool call when this runs.  We evict
all currently loaded Ollama models, let the existing MiniMax/ComfyUI app own
the GPU until the track is complete, then return control to Open WebUI.  Its
normal tool-call continuation automatically reloads the selected chat model.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


APP = os.environ.get("MINIMAX_MUSIC_URL", "http://127.0.0.1:8830").rstrip("/")
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
SERVICE = os.environ.get("MINIMAX_MUSIC_SERVICE", "minimax-music-api.service")


def _json(method: str, url: str, body: dict[str, Any] | None = None, timeout: int = 30) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def _ensure_app() -> None:
    try:
        _json("GET", APP + "/api/health", timeout=3)
        return
    except Exception:
        pass
    subprocess.run(
        ["systemctl", "--user", "start", SERVICE],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            _json("GET", APP + "/api/health", timeout=2)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("MiniMax Music API did not become ready")


def _unload_ollama() -> list[str]:
    """Evict every loaded Ollama model; this box cannot share VRAM with MiniMax."""
    try:
        loaded = _json("GET", OLLAMA + "/api/ps", timeout=8).get("models", [])
    except Exception as exc:
        raise RuntimeError(f"Could not inspect Ollama before GPU handover: {exc}") from exc
    names: list[str] = []
    for item in loaded:
        name = item.get("name") or item.get("model")
        if not name:
            continue
        _json("POST", OLLAMA + "/api/generate", {"model": name, "keep_alive": 0}, timeout=45)
        names.append(name)
    return names


class Tools:
    citation = False

    async def create_song(
        self,
        title: str,
        caption: str,
        lyrics: str,
        duration_seconds: int = 60,
        __event_emitter__=None,
    ) -> str:
        """Create a complete song with local MiniMax Music 3.

        Call this only when the user asks to create/generate/render an actual song or music track,
        not when they merely discuss music. Write a detailed MiniMax caption with three labelled
        sections: Global Metadata, Vocal Details, and Arrangement. Put all sung words and section
        tags in lyrics, never in caption. For an instrumental, use structure tags such as
        [Intro], [Instrumental], [Outro]. The operation can take several minutes.

        :param title: A short 2-5 word song title.
        :param caption: Detailed production description using Global Metadata, Vocal Details, and Arrangement sections.
        :param lyrics: Complete singable lyrics with section tags, or instrumental structure tags.
        :param duration_seconds: Requested duration from 10 to 300 seconds.
        :return: Generation result with a playable audio link and saved file path.
        """

        async def status(text: str, done: bool = False) -> None:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": text, "done": done}})

        duration = max(10, min(300, int(duration_seconds)))
        await status("Handing the GPU from the chat model to MiniMax Music 3…")
        try:
            await asyncio.to_thread(_ensure_app)
            unloaded = await asyncio.to_thread(_unload_ollama)
            await status("MiniMax Music 3 is generating the track…")
            submitted = await asyncio.to_thread(
                _json,
                "POST",
                APP + "/api/generate",
                {
                    "title": title.strip(),
                    "caption": caption.strip(),
                    "lyrics": lyrics.strip(),
                    "seconds": duration,
                    "quality": "V0",
                },
                150,
            )
            prompt_id = submitted.get("prompt_id")
            if not prompt_id:
                raise RuntimeError(f"MiniMax did not return a job id: {submitted}")

            deadline = time.monotonic() + 1800
            result: dict[str, Any] = {}
            while time.monotonic() < deadline:
                await asyncio.sleep(2)
                result = await asyncio.to_thread(
                    _json,
                    "GET",
                    APP + "/api/status?" + urllib.parse.urlencode({"prompt_id": prompt_id}),
                    None,
                    20,
                )
                if result.get("state") == "done":
                    break
                if result.get("state") == "error":
                    raise RuntimeError(result.get("error") or "MiniMax generation failed")
            else:
                raise TimeoutError("MiniMax generation exceeded the 30-minute safety limit")

            audio_url = APP + result["audio_url"]
            filename = result.get("filename", "generated track")
            path = result.get("path", "")
            stopped = await asyncio.to_thread(
                _json, "POST", APP + "/api/engine/stop", {}, 45
            )
            if stopped.get("comfy"):
                raise RuntimeError("track completed, but the MiniMax engine did not release the GPU")
            await status("Track complete; returning the GPU to the chat model…", done=True)
            return (
                f"Song generation completed successfully.\n\n"
                f"Title: {title.strip()}\n"
                f"Audio: [Play or download {filename}]({audio_url})\n"
                f"Saved locally: `{path}`\n"
                f"Chat models evicted for the handover: {', '.join(unloaded) if unloaded else 'none loaded'}.\n\n"
                "Continue the conversation normally; Open WebUI will now reload the selected chat model automatically."
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:600]
            await status("Music generation failed; the chat model can resume.", done=True)
            return f"MiniMax Music 3 failed with HTTP {exc.code}: {detail}"
        except Exception as exc:
            await status("Music generation failed; the chat model can resume.", done=True)
            return f"MiniMax Music 3 failed: {type(exc).__name__}: {exc}"
