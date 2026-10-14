#!/usr/bin/env python3
"""
MiniMax Music 3 - simple web app front-end for ComfyUI.

Zero third-party dependencies (Python stdlib only). It talks to a running
ComfyUI instance over its HTTP API using the exact workflow that was
validated by hand, so you never have to touch a node graph.

Run it through ``rhizome-stack creative minimax`` or its user service.

Then open http://127.0.0.1:8830 in your browser.
"""

import datetime
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import urllib.request
import urllib.parse
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from local_http_security import LocalRequestHandler, adapter_headers

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
COMFY_PORT = int(os.environ.get("COMFY_PORT", "8188"))
APP_HOST = os.environ.get("APP_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("APP_PORT", "8830"))
STACK_ROOT = os.path.expanduser(os.environ.get("RHIZOME_STACK_ROOT", "~/.local/share/rhizome-stack"))
COMFY_DIR = os.environ.get("COMFY_DIR", os.path.join(STACK_ROOT, "creative", "ComfyUI"))
COMFY_OUTPUT = os.environ.get("COMFY_OUTPUT", os.path.join(COMFY_DIR, "output"))
COMFY_PY = os.environ.get("COMFY_PY", os.path.join(COMFY_DIR, ".venv/bin/python"))
COMFY_MAIN = os.path.join(COMFY_DIR, "main.py")
LOGDIR = os.environ.get("MINIMAX_LOGDIR", os.path.join(STACK_ROOT, "creative", "state", "minimax-music"))

# Stop the engine after this many seconds with no generation activity (0 = never).
# Default OFF; use the manual "Stop engine" button or enable idle auto-stop.
# Closing a browser tab does not stop the engine.
IDLE_SECONDS = int(os.environ.get("COMFY_IDLE_SECONDS", "0"))

DIT   = "minimax_music3_dit_int8_convrot.safetensors"
CLIPT = "minimax_music3_text_encoder_pruned_int8_convrot.safetensors"
VAE   = "minimax_music3_dav.safetensors"


def _comfy_version():
    try:
        with open(os.path.join(COMFY_DIR, "comfyui_version.py")) as f:
            for line in f:
                if "__version__" in line:
                    return line.split("=", 1)[1].strip().strip("\"'")
    except Exception:
        pass
    return "unknown"


COMFY_VERSION = _comfy_version()

# Prefill so the very first click produces something listenable.
DEFAULT_CAPTION = (
    "Global Metadata: warm lo-fi chillhop instrumental, 80 BPM, mellow and cozy, "
    "vinyl crackle, tape hiss, late-night headphones vibe.\n\n"
    "Vocal Details: no vocals, purely instrumental.\n\n"
    "Arrangement: soft boom-bap drums, round sub bass, warm Rhodes chords, "
    "gentle jazzy guitar licks, constant vinyl crackle as texture."
)
DEFAULT_LYRICS = "[Intro]\n[Instrumental]\n[Outro]"


# ---------------------------------------------------------------------------
# AI brief -> autofill (local Ollama)
# ---------------------------------------------------------------------------
# Two backends, exactly like Open WebUI is wired:
#   - OpenClaw OpenAI-compatible adapter: cloud/API models (ids start "openclaw/"),
#     routed via the gateway, NO local VRAM.
#   - Ollama: local GGUF models — these DO use VRAM, so we unload them after a fill
#     so MiniMax/ComfyUI gets the GPU back.
OPENCLAW_API = os.environ.get("OPENCLAW_API_URL", "http://127.0.0.1:18888/v1")
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

AI_SYSTEM = (
    "You are an expert songwriter and prompt engineer for MiniMax Music 3. From a short brief "
    "(styles + a one-line idea) you invent a complete, original song. "
    "Return STRICT JSON with exactly these keys: \"title\", \"caption\", \"lyrics\".\n\n"
    "GROUND EVERYTHING IN THE BRIEF. Use the exact genres/styles the user gives; derive the mood, "
    "BPM, instruments and theme from THEIR words. Never fall back on a house style — do NOT default "
    "to synthwave, neon, or night-driving unless the brief explicitly asks. Each song must feel "
    "distinct to its own brief.\n\n"
    "CAPTION — MiniMax's three labelled sections, separated by blank lines. Write vivid English "
    "SENTENCES, not comma-separated tag lists:\n"
    "  Global Metadata: one rich sentence — mood + genre(/sub-genre) + BPM, then the key sonic "
    "textures and production vibe.\n"
    "  Vocal Details: a specific vocal description (e.g. 'sultry male baritone with breathy jazz "
    "phrasing'), or 'Instrumental — no vocals'. Never vague like 'female vocal'.\n"
    "  Arrangement: the specific instruments and how they enter and build across the song.\n"
    "The caption is DESCRIPTION ONLY — it must NEVER contain lyrics or [section] tags.\n\n"
    "LYRICS — section tags each on their own line: [Intro] [Verse] [Pre-Chorus] [Chorus] [Bridge] "
    "[Instrumental] [Outro]. Write real, singable lines that fit the theme, with ONE clear, "
    "repeatable chorus. If the brief asks for instrumental/no vocals, output only structure tags "
    "with empty lines (e.g. [Intro]\\n[Instrumental]\\n[Outro]). All song words and [tags] go ONLY "
    "here, never in the caption.\n\n"
    "TITLE — 2-5 words that fit THIS song's genre and theme (not generic).\n\n"
    "Example shape only — MATCH THE USER'S BRIEF, do not copy this genre:\n"
    "{\"title\": \"Marble & Rust\", "
    "\"caption\": \"Global Metadata: A warm, wistful 92 BPM neo-soul groove with dusty analog warmth, "
    "round Rhodes chords and a soft vinyl hiss.\\n\\nVocal Details: Relaxed, soul-flavoured female "
    "vocals with gentle ad-libs and close, intimate phrasing.\\n\\nArrangement: Brushed drums and "
    "fretless bass open it, Rhodes and muted guitar join at the verse, and a small horn section "
    "lifts the chorus.\", "
    "\"lyrics\": \"[Verse]\\nWe built a house from borrowed time\\n[Chorus]\\nBut love don't rust, it "
    "only shines\\n[Outro]\"}\n\n"
    "Output ONLY the JSON, nothing else."
)


def ai_models():
    """Merged list, cloud first then local — same sources Open WebUI uses."""
    out = []
    try:  # OpenClaw adapter (cloud); ids start with "openclaw/"
        with urllib.request.urlopen(urllib.request.Request(OPENCLAW_API + "/models", headers=adapter_headers()), timeout=6) as r:
            data = json.load(r)
        out += [m["id"] for m in data.get("data", []) if m.get("id")]
    except Exception:
        pass
    try:  # local Ollama models
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=6) as r:
            data = json.load(r)
        out += [m["name"] for m in data.get("models", []) if m.get("name")]
    except Exception:
        pass
    return out


def _is_cloud(model):
    return (model or "").startswith("openclaw/")


def ollama_unload(model):
    """Evict a local model from VRAM (keep_alive=0) so ComfyUI/MiniMax gets the
    GPU back. Cloud models have nothing to unload. Best-effort, never raises."""
    if _is_cloud(model):
        return
    try:
        req = urllib.request.Request(
            OLLAMA + "/api/generate",
            data=json.dumps({"model": model, "keep_alive": 0}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
    except Exception:
        pass


def _extract_json(text):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        return json.loads(text[i:j + 1])
    raise ValueError("model did not return JSON")


def ai_fill(model, brief, seconds=60):
    brief = (brief or "").strip()
    if not brief:
        raise ValueError("empty brief")
    user = ("Brief:\n%s\n\nTarget length: about %d seconds. Write the JSON now."
            % (brief, int(seconds or 60)))
    messages = [{"role": "system", "content": AI_SYSTEM},
                {"role": "user", "content": user}]
    if _is_cloud(model):
        # OpenClaw adapter, OpenAI chat-completions format.
        payload = {"model": model, "messages": messages, "stream": False,
                   "temperature": 1.0, "top_p": 0.95, "max_tokens": 1200}
        url = OPENCLAW_API + "/chat/completions"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers=adapter_headers())
        with urllib.request.urlopen(req, timeout=240) as r:
            data = json.load(r)
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
    else:
        # Local Ollama, native chat format; unload after answering (VRAM back).
        payload = {"model": model, "messages": messages, "stream": False,
                   "format": "json", "think": False, "keep_alive": 0,
                   "options": {"temperature": 1.0, "top_p": 0.95, "num_predict": 1000}}
        url = OLLAMA + "/api/chat"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=240) as r:
            data = json.load(r)
        content = (data.get("message") or {}).get("content", "")
    obj = _extract_json(content)
    title = (obj.get("title") or "").strip().strip('"')
    caption = (obj.get("caption") or "").strip()
    lyrics = (obj.get("lyrics") or "").strip()

    # Safety net: some models dump lyrics into the caption and leave lyrics empty.
    # If the caption contains song-section tags and the lyrics slot has no real
    # content, split them back apart at the first tag.
    tag_re = re.compile(r"\[(?:intro|verse|pre-?chorus|chorus|hook|bridge|outro|instrumental|refrain|drop|break)\]",
                        re.IGNORECASE)
    lyrics_empty = (not lyrics) or lyrics == DEFAULT_LYRICS or not tag_re.search(lyrics)
    m = tag_re.search(caption)
    if m and lyrics_empty:
        moved = caption[m.start():].strip()
        caption = caption[:m.start()].strip()
        if moved:
            lyrics = moved

    return {"title": title, "caption": caption, "lyrics": lyrics}


# ---------------------------------------------------------------------------
# ComfyUI helpers
# ---------------------------------------------------------------------------
def comfy_get(path, timeout=10):
    with urllib.request.urlopen(COMFY + path, timeout=timeout) as r:
        return json.load(r)


def comfy_up():
    try:
        comfy_get("/system_stats", timeout=4)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Engine lifecycle (start / stop / idle auto-stop)
#
# The app owns ComfyUI's lifecycle so we can free VRAM/RAM when idle and bring
# it back on demand. Same spirit as the Chatterbox idle-unload: only real
# generation activity resets the idle clock -- health/status polls do NOT, or
# an open browser tab would pin the engine forever.
# ---------------------------------------------------------------------------
ENGINE_LOCK = threading.RLock()
STATE = {
    "last_activity": time.time(),   # bumped only by real generation activity
    "busy": False,                  # a job is in flight
    "idle_stopped": False,          # engine stopped by the watchdog (vs by user)
    "starting": False,
}


def _pidfile():
    return os.path.join(LOGDIR, "comfy.pid")


def _read_pid():
    try:
        with open(_pidfile()) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _owned_pid(pid):
    """Accept only the exact detached ComfyUI process recorded by this app."""
    if not pid or pid == os.getpid():
        return False
    try:
        cmdline = open("/proc/%d/cmdline" % pid, "rb").read().replace(b"\0", b" ").decode(errors="replace")
        return (os.path.realpath(COMFY_MAIN) in cmdline
                and "--port %d" % COMFY_PORT in cmdline
                and os.getpgid(pid) == pid)
    except (OSError, ProcessLookupError):
        return False


def touch_activity():
    STATE["last_activity"] = time.time()


def engine_start(wait=90):
    """Start ComfyUI if it isn't up. Returns True once reachable."""
    with ENGINE_LOCK:
        if comfy_up():
            return True
        STATE["starting"] = True
        os.makedirs(LOGDIR, exist_ok=True)
        log = open(os.path.join(LOGDIR, "comfy.log"), "ab")
        env = dict(os.environ, CUDA_DEVICE_ORDER="PCI_BUS_ID")
        proc = subprocess.Popen(
            [COMFY_PY, COMFY_MAIN, "--port", str(COMFY_PORT), "--listen", "127.0.0.1"],
            cwd=COMFY_DIR, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
            start_new_session=True, env=env)
        with open(_pidfile(), "w") as f:
            f.write(str(proc.pid))
    deadline = time.time() + wait
    while time.time() < deadline:
        if comfy_up():
            STATE["starting"] = False
            STATE["idle_stopped"] = False
            touch_activity()
            return True
        time.sleep(1.5)
    STATE["starting"] = False
    return False


def engine_stop(reason="user"):
    """Stop the running ComfyUI engine. Frees its VRAM/RAM."""
    with ENGINE_LOCK:
        stopped = False
        pid = _read_pid()
        if _owned_pid(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                stopped = True
            except (OSError, ProcessLookupError):
                pass
        try:
            os.remove(_pidfile())
        except Exception:
            pass
        STATE["idle_stopped"] = (reason == "idle")
        # give it a moment to release the port
        for _ in range(10):
            if not comfy_up():
                break
            time.sleep(0.5)
        return stopped


def watchdog():
    """Background thread: stop the engine after IDLE_SECONDS of no activity."""
    while True:
        time.sleep(15)
        if IDLE_SECONDS <= 0:
            continue
        try:
            if STATE["busy"] or STATE["starting"]:
                continue
            if not comfy_up():
                continue
            # never stop while ComfyUI has queued/running work
            try:
                qd = comfy_get("/queue", timeout=5)
                if qd.get("queue_running") or qd.get("queue_pending"):
                    touch_activity()
                    continue
            except Exception:
                continue
            if time.time() - STATE["last_activity"] >= IDLE_SECONDS:
                engine_stop(reason="idle")
        except Exception:
            pass


def slugify(name):
    """Turn a song title into a safe file name (no path, no odd chars)."""
    s = (name or "").strip()
    s = re.sub(r"[^\w\s()\-]", "", s)   # keep letters/digits/_ () - and spaces
    s = re.sub(r"\s+", "_", s)
    s = s.strip("_.")[:60]
    return s


def build_recipe(mp3_path, meta):
    """The canonical, reproducible recipe for a generated track."""
    return {
        "app": "MiniMax Music 3 app",
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "file": os.path.basename(mp3_path),
        "title": meta.get("title") or "",
        "caption": meta.get("caption", ""),
        "lyrics": meta.get("lyrics", ""),
        "seed": meta.get("seed"),
        "length_seconds": meta.get("seconds"),
        "steps": meta.get("steps"),
        "guidance_cfg": meta.get("cfg"),
        "top_k": meta.get("top_k"),
        "tiled_decode": bool(meta.get("tiled")),
        "quality": meta.get("quality", "V0"),
        "engine": {
            "diffusion_model": DIT,
            "text_encoder": CLIPT,
            "vae": VAE,
            "sampler": "euler",
            "scheduler": "simple",
            "comfyui_version": COMFY_VERSION,
        },
    }


def embed_id3(mp3_path, r):
    """Embed the key info into the MP3 as ID3 tags (best-effort, via ffmpeg)."""
    if not shutil.which("ffmpeg"):
        return
    comment = "Seed %s | %ss | steps %s | cfg %s | %s" % (
        r["seed"], r["length_seconds"], r["steps"], r["guidance_cfg"], DIT)
    tmp = mp3_path + ".tag.tmp.mp3"
    args = ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3_path,
            "-c", "copy", "-map_metadata", "-1", "-write_id3v2", "1",
            "-metadata", "title=%s" % (r["title"] or os.path.splitext(r["file"])[0]),
            "-metadata", "artist=MiniMax Music 3",
            "-metadata", "album=MiniMax Music 3",
            "-metadata", "genre=MiniMax Music 3",
            "-metadata", "comment=%s" % comment,
            "-metadata", "lyrics=%s" % r["lyrics"],
            "-metadata", "MM_caption=%s" % r["caption"],
            "-metadata", "MM_lyrics=%s" % r["lyrics"],
            "-metadata", "MM_seed=%s" % r["seed"],
            "-metadata", "MM_length_seconds=%s" % r["length_seconds"],
            "-metadata", "MM_steps=%s" % r["steps"],
            "-metadata", "MM_guidance_cfg=%s" % r["guidance_cfg"],
            "-metadata", "MM_top_k=%s" % r["top_k"],
            "-metadata", "MM_model=%s" % DIT,
            tmp]
    try:
        subprocess.run(args, timeout=60, check=True)
        os.replace(tmp, mp3_path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass


def save_metadata(mp3_path, meta):
    """Write the JSON sidecar and embed ID3 tags. Idempotent (skips if done)."""
    base = os.path.splitext(mp3_path)[0]
    jpath = base + ".json"
    if os.path.exists(jpath):
        return
    r = build_recipe(mp3_path, meta)
    try:
        with open(jpath, "w") as f:
            json.dump(r, f, indent=2, ensure_ascii=False)
    except Exception:
        return
    embed_id3(mp3_path, r)


def build_prompt(caption, lyrics, seconds, seed, steps, cfg, top_k, tiled, prefix, quality="V0"):
    """Return a ComfyUI API-format prompt graph for MiniMax Music 3."""
    seconds = max(0.04, min(float(seconds), 300.0))
    graph = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": DIT, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIPT, "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader",
              "inputs": {"vae_name": VAE}},
        "4": {"class_type": "MiniMaxMusic3TextEncode",
              "inputs": {"clip": ["2", 0], "caption": caption, "lyrics": lyrics,
                         "seed": int(seed), "max_duration": seconds,
                         "cfg_scale": float(cfg), "top_k": int(top_k)}},
        "5": {"class_type": "ConditioningZeroOut",
              "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyMiniMaxMusic3LatentAudio",
              "inputs": {"seconds": ["4", 1], "batch_size": 1}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["6", 0], "seed": int(seed), "steps": int(steps),
                         "cfg": float(cfg), "sampler_name": "euler", "scheduler": "simple",
                         "denoise": 1.0}},
    }
    if tiled:
        graph["8"] = {"class_type": "VAEDecodeAudioTiled",
                      "inputs": {"samples": ["7", 0], "vae": ["3", 0],
                                 "tile_size": 1536, "overlap": 64}}
    else:
        graph["8"] = {"class_type": "VAEDecodeAudio",
                      "inputs": {"samples": ["7", 0], "vae": ["3", 0]}}
    graph["9"] = {"class_type": "SaveAudioMP3",
                  "inputs": {"audio": ["8", 0], "filename_prefix": prefix, "quality": quality}}
    return graph


def submit(graph):
    data = json.dumps({"prompt": graph, "client_id": str(uuid.uuid4())}).encode()
    req = urllib.request.Request(COMFY + "/prompt", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def find_output_file(prompt_id):
    """Return (filename, subfolder) for the saved audio, or None if not ready."""
    try:
        hist = comfy_get("/history/%s" % prompt_id, timeout=10)
    except Exception:
        return None
    entry = hist.get(prompt_id)
    if not entry:
        return None
    status = entry.get("status", {})
    for out in entry.get("outputs", {}).values():
        for kind in ("audio", "mp3", "flac", "wav"):
            if kind in out and out[kind]:
                a = out[kind][0]
                return a.get("filename"), a.get("subfolder", ""), status
    # completed but no audio -> error
    if status.get("completed") is False and status.get("status_str") == "error":
        return ("__error__", "", status)
    return None


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
def output_path(filename, subfolder="minimax_app"):
    """Confine media and sidecars to the output tree, including symlink targets."""
    if (not isinstance(filename, str) or not filename or filename in {".", ".."}
            or any(char in filename for char in '/\\\x00\r\n"')
            or not isinstance(subfolder, str) or "\x00" in subfolder):
        raise ValueError("bad output filename")
    relative = Path(subfolder)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("output is outside the creative output directory")
    root = Path(COMFY_OUTPUT).resolve()
    target = root / relative / filename
    if not target.resolve().is_relative_to(root):
        raise ValueError("output is outside the creative output directory")
    return target


def generation_options(body):
    """Validate before starting the engine or allocating GPU work."""
    result = {}
    for key in ("title", "caption", "lyrics"):
        value = body.get(key, "")
        if not isinstance(value, str):
            raise ValueError(f"{key} must be text")
        result[key] = value.strip()
    if not result["caption"]:
        raise ValueError("Please describe the music (the caption is required).")
    for key, default, low, high, integral in (
        ("seconds", 60, 8, 300, False), ("steps", 30, 8, 60, True),
        ("cfg", 1.7, 1, 6, False), ("top_k", 50, 1, 1000, True),
        ("seed", None, 0, 2**64 - 1, True),
    ):
        value = body.get(key, default)
        if key == "seed" and value in (None, "", "random"):
            value = uuid.uuid4().int & 0xFFFFFFFFFFFF
        try:
            if isinstance(value, bool):
                raise ValueError
            number = int(value) if integral else float(value)
            if integral and not isinstance(value, (str, int)) and number != value:
                raise ValueError
            if not math.isfinite(number) or not low <= number <= high:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"{key} must be {'an integer' if integral else 'a number'} between {low} and {high}") from None
        result[key] = number
    if not isinstance(body.get("tiled", False), bool):
        raise ValueError("tiled must be a boolean")
    result["tiled"] = body.get("tiled", False)
    result["quality"] = body.get("quality", "V0")
    if result["quality"] not in ("V0", "128k", "320k"):
        raise ValueError("quality must be V0, 128k or 320k")
    return result


class Handler(LocalRequestHandler):
    # in-memory index of submitted jobs {prompt_id: {"t0":..., "meta":...}}
    JOBS = {}

    def log_message(self, *a):
        pass  # quiet

    def json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if self.headers.get("Transfer-Encoding") or not 0 <= length <= 128 * 1024:
            raise ValueError("request requires Content-Length between 0 and 128 KiB")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("incomplete request body")
        body = json.loads(raw or b"{}")
        if not isinstance(body, dict):
            raise ValueError("request body must be an object")
        return body

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    # ---- routing ----
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            return self._send(200, INDEX_HTML, "text/html; charset=utf-8")
        if u.path == "/api/health":
            up = comfy_up()
            idle_for = round(time.time() - STATE["last_activity"], 0)
            remaining = None
            if up and IDLE_SECONDS > 0 and not STATE["busy"]:
                remaining = max(0, IDLE_SECONDS - int(idle_for))
            return self._send(200, {
                "comfy": up, "comfy_url": COMFY, "busy": STATE["busy"],
                "starting": STATE["starting"], "idle_stopped": STATE["idle_stopped"],
                "idle_seconds": IDLE_SECONDS, "idle_remaining": remaining,
            })
        if u.path == "/api/status":
            return self._status(q.get("prompt_id", [""])[0])
        if u.path == "/api/audio":
            return self._audio(q.get("filename", [""])[0], q.get("subfolder", [""])[0])
        if u.path == "/api/history":
            return self._history()
        if u.path == "/api/recipe":
            return self._recipe(q.get("filename", [""])[0])
        if u.path == "/api/ai_models":
            return self._send(200, {"models": ai_models()})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/generate":
            return self._generate()
        if u.path == "/api/engine/stop":
            if STATE["busy"]:
                return self._send(409, {"error": "A track is generating right now — try again when it finishes."})
            engine_stop(reason="user")
            return self._send(200, {"comfy": comfy_up()})
        if u.path == "/api/engine/start":
            ok = engine_start()
            return self._send(200 if ok else 503, {"comfy": comfy_up(),
                    "error": None if ok else "engine failed to start"})
        if u.path == "/api/delete":
            try:
                body = self.json_body()
            except Exception as e:
                return self._send(400, {"error": "bad request: %s" % e})
            return self._delete(body.get("filename", ""))
        if u.path == "/api/ai_fill":
            try:
                body = self.json_body()
            except Exception as e:
                return self._send(400, {"error": "bad request: %s" % e})
            model = body.get("model")
            if not isinstance(model, str):
                return self._send(400, {"error": "model must be text"})
            model = model.strip()
            if not model:
                return self._send(400, {"error": "pick a model first"})
            try:
                out = ai_fill(model, body.get("brief", ""), body.get("seconds", 60))
            except ValueError:
                return self._send(400, {"error": "Give it a brief first (styles + a one-line idea)."})
            except urllib.error.HTTPError as e:
                return self._send(502, {"error": "Ollama rejected the request: %s" % e.read().decode()[:300]})
            except Exception as e:
                return self._send(502, {"error": "AI fill failed: %s" % e})
            return self._send(200, out)
        if u.path == "/api/ai_unload":
            try:
                body = self.json_body()
            except (ValueError, TypeError) as e:
                return self._send(400, {"error": str(e)})
            m = body.get("model", "")
            if not isinstance(m, str):
                return self._send(400, {"error": "model must be text"})
            m = m.strip()
            if m:
                ollama_unload(m)   # no-op for cloud models
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})

    # ---- endpoints ----
    def _generate(self):
        try:
            options = generation_options(self.json_body())
        except (ValueError, TypeError) as e:
            return self._send(400, {"error": "bad request: %s" % e})

        title, caption, lyrics = (options[key] for key in ("title", "caption", "lyrics"))
        seconds, seed, steps, cfg, top_k, tiled, quality = (
            options[key] for key in ("seconds", "seed", "steps", "cfg", "top_k", "tiled", "quality"))

        if not comfy_up():
            # transparently cold-start the engine (idle auto-stop or manual kill)
            if not engine_start():
                return self._send(503, {"error": "Could not start the ComfyUI engine — see logs/comfy.log."})

        touch_activity()
        slug = slugify(title)
        prefix = "minimax_app/%s" % (slug if slug else ("song_%d" % int(time.time())))
        graph = build_prompt(caption, lyrics, seconds, seed, steps, cfg, top_k, tiled, prefix, quality)
        try:
            res = submit(graph)
        except urllib.error.HTTPError as e:
            return self._send(502, {"error": "ComfyUI rejected the job: %s" % e.read().decode()[:400]})
        except Exception as e:
            return self._send(502, {"error": "Could not reach ComfyUI: %s" % e})

        STATE["busy"] = True
        touch_activity()
        pid = res.get("prompt_id")
        Handler.JOBS[pid] = {"t0": time.time(),
                             "meta": {"title": title, "caption": caption, "lyrics": lyrics,
                                      "seconds": seconds, "seed": int(seed),
                                      "steps": steps, "cfg": cfg, "top_k": top_k,
                                      "tiled": tiled, "quality": quality}}
        return self._send(200, {"prompt_id": pid, "seed": int(seed)})

    def _status(self, pid):
        if not pid:
            return self._send(400, {"error": "missing prompt_id"})
        job = Handler.JOBS.get(pid, {})
        elapsed = round(time.time() - job.get("t0", time.time()), 1)
        out = find_output_file(pid)
        if out is None:
            # still queued / running - report queue position if we can
            pos = None
            try:
                qd = comfy_get("/queue", timeout=6)
                running = [x for x in qd.get("queue_running", []) if x[1] == pid]
                pending = [i for i, x in enumerate(qd.get("queue_pending", [])) if x[1] == pid]
                if running:
                    pos = "running"
                elif pending:
                    pos = "queued #%d" % (pending[0] + 1)
            except Exception:
                pass
            return self._send(200, {"state": "working", "elapsed": elapsed, "where": pos})
        fn, sub, status = out
        STATE["busy"] = False
        touch_activity()  # start the idle clock from job completion
        if fn != "__error__" and job.get("meta"):
            try:
                save_metadata(str(output_path(fn, sub)), job["meta"])
            except Exception:
                pass
        if fn == "__error__":
            msg = "generation failed in ComfyUI"
            for m in status.get("messages", []):
                if isinstance(m, list) and m and m[0] == "execution_error":
                    msg = m[1].get("exception_message", msg)
            return self._send(200, {"state": "error", "elapsed": elapsed, "error": msg})
        url = "/api/audio?filename=%s&subfolder=%s" % (
            urllib.parse.quote(fn), urllib.parse.quote(sub))
        path = os.path.join(COMFY_OUTPUT, sub, fn)
        return self._send(200, {"state": "done", "elapsed": elapsed,
                                "audio_url": url, "filename": fn, "path": path,
                                "meta": job.get("meta", {})})

    def _audio(self, filename, subfolder):
        try:
            path = output_path(filename, subfolder)
            if path.suffix.lower() not in {".mp3", ".flac", ".wav"}:
                raise ValueError("unsupported audio extension")
        except (ValueError, OSError) as e:
            return self._send(400, {"error": str(e)})
        # Prefer proxying via ComfyUI /view (works regardless of disk layout).
        qs = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": "output"})
        try:
            with urllib.request.urlopen(COMFY + "/view?" + qs, timeout=30) as r:
                data = r.read()
        except Exception:
            # fallback: read straight off disk
            if not os.path.isfile(path):
                return self._send(404, {"error": "audio not found"})
            with open(path, "rb") as f:
                data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", {".mp3": "audio/mpeg", ".flac": "audio/flac", ".wav": "audio/wav"}[path.suffix.lower()])
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Disposition", 'inline; filename="%s"' % filename)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _history(self):
        d = os.path.join(COMFY_OUTPUT, "minimax_app")
        items = []
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.lower().endswith((".mp3", ".flac", ".wav")):
                    p = os.path.join(d, fn)
                    jp = os.path.splitext(p)[0] + ".json"
                    items.append({"filename": fn,
                                  "url": "/api/audio?filename=%s&subfolder=minimax_app" %
                                         urllib.parse.quote(fn),
                                  "path": p,
                                  "recipe": os.path.exists(jp),
                                  "mtime": int(os.path.getmtime(p)),
                                  "size": os.path.getsize(p)})
        items.sort(key=lambda i: i["mtime"], reverse=True)  # newest first
        return self._send(200, {"items": items[:40], "folder": d})

    def _recipe(self, filename):
        try:
            output_path(filename)
            jp = output_path(Path(filename).stem + ".json")
        except (ValueError, OSError) as e:
            return self._send(400, {"error": str(e)})
        if not os.path.isfile(jp):
            return self._send(404, {"error": "no saved settings for this track"})
        try:
            with open(jp) as f:
                return self._send(200, json.load(f))
        except Exception as e:
            return self._send(500, {"error": str(e)})

    def _delete(self, filename):
        try:
            p = output_path(filename)
            sidecar = output_path(Path(filename).stem + ".json")
            if p.suffix.lower() not in {".mp3", ".flac", ".wav"}:
                raise ValueError("unsupported audio extension")
        except (ValueError, OSError) as e:
            return self._send(400, {"error": str(e)})
        if not os.path.isfile(p):
            return self._send(404, {"error": "not found"})
        try:
            os.remove(p)
        except Exception as e:
            return self._send(500, {"error": str(e)})
        # also remove the recipe sidecar so nothing is orphaned
        try:
            if os.path.isfile(sidecar):
                os.remove(sidecar)
        except Exception:
            pass
        return self._send(200, {"deleted": filename})


# ---------------------------------------------------------------------------
# UI  (single-page, color-blind-friendly: status uses text + icons, not colour)
# ---------------------------------------------------------------------------
INDEX_HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0b1015">
<title>MiniMax Music 3</title>
<style>
:root{--bg:#e9eff4;--panel:#fff;--field:#f3f6f9;--line:#d6e0e8;--ink:#142737;--muted:#53697b;--accent:#315ed5;--accent-deep:#2347aa;--accent-soft:#e3eaff;--signal:#d58b26;--library:#102638;--library-card:#193448;--library-line:#35546b;--library-muted:#b8cad8;--radius:18px}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 'Adwaita Sans','Segoe UI',sans-serif}
button,input,textarea,select{font:inherit}
button,a,input,textarea,select,summary{-webkit-tap-highlight-color:transparent}
button,a,summary{touch-action:manipulation}
button{cursor:pointer}button:disabled{cursor:wait;opacity:.55}
a{color:var(--accent)}
:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
.masthead{max-width:1560px;margin:auto;padding:25px 40px 18px;display:flex;align-items:center;gap:15px}
.brand-mark{width:44px;height:44px;border-radius:13px;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;gap:4px;flex-shrink:0;box-shadow:0 8px 24px #315ed528}
.brand-mark i{display:block;background:currentColor;width:4px;border-radius:3px;height:14px}.brand-mark i:nth-child(2){height:25px}.brand-mark i:nth-child(3){height:19px}
h1,h2,h3,p{margin:0}h1,h2,h3{font-family:'Fira Sans Condensed','Adwaita Sans',sans-serif}
h1{font-size:24px;letter-spacing:-.5px;line-height:1.1;font-weight:600}
.brand-sub{font-size:12px;color:var(--muted);margin-top:4px}
.engine-tools{margin-left:auto;display:flex;gap:12px;align-items:center}.eng{font-size:12px;color:var(--muted)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--muted);margin-right:7px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;background:var(--accent);color:#fff;border:1px solid transparent;border-radius:10px;padding:12px 20px;font-size:14px;font-weight:650;min-height:44px;text-decoration:none;transition:background .15s,box-shadow .15s}
.btn:hover:not(:disabled){box-shadow:0 5px 15px #1724311c;background:var(--accent-deep)}
.btn.sec{background:var(--panel);border-color:var(--line);color:var(--ink)}.btn.sec:hover:not(:disabled){background:var(--field)}
.eng-btn{font-size:12px;padding:8px 12px;min-height:38px}
.wrap{max-width:1560px;margin:auto;padding:0 40px 40px}.workspace{display:grid;grid-template-columns:minmax(0,1fr) 405px;gap:24px;align-items:start}
.editor{min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);box-shadow:0 10px 32px #16304708;overflow:hidden}
.editor-heading{padding:25px 30px 22px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:16px;background:linear-gradient(120deg,#fff 0%,#f8faff 100%)}
.eyebrow{color:var(--muted);font-size:10px;font-weight:700;letter-spacing:1.7px;text-transform:uppercase;margin-bottom:5px}
h2{font-size:29px;letter-spacing:-.6px;line-height:1.2;font-weight:550}.editor-heading p:last-child{color:var(--muted);font-size:13px;margin-top:6px}
.session-badge{padding:5px 10px;border-radius:6px;background:var(--accent-soft);color:var(--accent);font:600 11px 'Adwaita Mono',monospace;white-space:nowrap}
.stage{display:grid;grid-template-columns:58px minmax(0,1fr);border-bottom:1px solid var(--line)}.stage:last-child{border-bottom:0}.stage-rail{padding:27px 0 0 25px}.stage-number{display:grid;place-items:center;width:30px;height:30px;border:1px solid var(--line);border-radius:8px;background:var(--field);color:var(--muted);font:700 11px 'Adwaita Mono',monospace}.stage-content{min-width:0;padding:25px 30px 28px 0}.stage-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:18px}.stage-head h3{font-size:20px;letter-spacing:-.25px;font-weight:600}.stage-head p{color:var(--muted);font-size:12px;margin-top:3px}.stage-kicker{font:650 10px 'Adwaita Mono',monospace;color:var(--accent);letter-spacing:1.2px;text-transform:uppercase}
.field{margin-bottom:21px}.field:last-child{margin-bottom:0}label{display:block;font-size:13px;font-weight:650;margin-bottom:7px}.optional{font-size:12px;color:var(--muted);font-weight:400;margin-left:6px}
.hint{color:var(--muted);font-size:12px;font-weight:400}.field-help{display:block;margin-top:7px}
input:not([type=range]),textarea,select{width:100%;min-width:0;border:1px solid var(--line);border-radius:9px;background:var(--field);color:var(--ink);padding:11px 13px;transition:border-color .15s;line-height:1.55}
input::placeholder,textarea::placeholder{color:#687889;opacity:1}
input:not([type=range]):focus,textarea:focus,select:focus{outline:2px solid var(--accent);outline-offset:1px;background:var(--panel)}
textarea{resize:vertical;display:block}textarea.cap{min-height:135px}textarea.lyr{min-height:185px;font:13px/1.8 'Adwaita Mono',monospace}
#title{background:transparent;font-size:20px;font-weight:500;padding:9px 0;border:0;border-bottom:1px solid var(--line);border-radius:0}
summary{cursor:pointer;font-size:13px;font-weight:600;list-style:none;display:flex;align-items:center;gap:10px;min-height:46px}summary::-webkit-details-marker{display:none}
summary::after{content:'+';margin-left:auto;color:var(--muted);font-size:20px;font-weight:400}details[open]>summary::after{content:'−'}
.idea-box{border:1px solid #cfdbee;background:linear-gradient(135deg,#f5f8ff 0%,#eef3ff 100%);border-radius:13px;padding:16px}.idea-box textarea{min-height:92px;background:#fff}.idea-actions{display:grid;grid-template-columns:minmax(240px,1fr) auto;gap:12px;align-items:end;margin-top:13px}.writer-field label{display:flex;justify-content:space-between;align-items:baseline}.writer-field label span{font-size:10px;color:var(--muted);font-weight:500}.writer-field select{background:#fff}.idea-actions .btn{min-height:46px;white-space:nowrap}.rhizome-mark{color:var(--accent);font-size:16px;margin-right:4px}
#aistatus{font-size:12px;color:var(--muted);margin-top:10px;overflow-wrap:anywhere}#aistatus:empty{display:none}
.field-heading{display:flex;align-items:baseline;justify-content:space-between;gap:12px}.tagbar{display:flex;gap:6px;flex-wrap:wrap;margin:9px 0 0}
.tag{font:11px/1.5 'Adwaita Mono',monospace;border:1px solid var(--line);background:var(--panel);color:var(--muted);border-radius:6px;padding:5px 8px;min-height:30px}.tag:hover{color:var(--accent);border-color:var(--accent)}
.song-fields{display:grid;grid-template-columns:minmax(0,1fr);gap:20px}.row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}.settings-row{background:var(--field);border:1px solid var(--line);border-radius:11px;padding:16px}.settings-row input:not([type=range]){background:var(--panel)}
.seed-row{display:flex;align-items:stretch;gap:8px}.seed-row input{flex:1}.seed-random{flex:0 0 45px;border:1px solid var(--line);border-radius:9px;background:var(--panel);color:var(--accent);font-size:20px;font-weight:700}.seed-random:hover{background:var(--accent-soft);border-color:var(--accent)}
.slabel{display:flex;justify-content:space-between;align-items:baseline}.slabel b{font:12px 'Adwaita Mono',monospace;color:var(--accent)}
input[type=range]{accent-color:var(--accent);width:100%;padding:0;height:24px;cursor:pointer}.mmss{display:flex;align-items:center;gap:6px;margin-top:6px;font-size:12px;color:var(--muted)}.mmss input{width:55px!important;padding:5px 7px!important;text-align:center}
.advanced{border-top:1px solid var(--line);margin-top:20px;padding-top:5px}.advanced summary{color:var(--muted)}.advanced .row{padding:12px 0 0}
.render-action{margin-top:20px;border:1px solid #cbd8f2;border-radius:13px;padding:15px 16px;display:flex;align-items:center;justify-content:space-between;gap:20px;background:linear-gradient(110deg,#f1f5ff,#e7edff)}.generate-note{font-size:12px;color:var(--muted);max-width:320px}.generate-note strong{display:block;color:var(--ink);font-size:13px;margin-bottom:2px}#go{min-width:215px;min-height:48px;font-size:15px}
#status{display:none;margin-top:14px;padding:15px 16px;border:1px solid var(--line);border-radius:11px;background:var(--field);font-size:13px;overflow-wrap:anywhere}#status.show{display:block}#status audio{margin-top:12px}.pathline{font:11px/1.6 'Adwaita Mono',monospace;color:var(--muted);overflow-wrap:anywhere;margin-top:12px}
.spin{display:inline-block;width:14px;height:14px;border:2px solid var(--line);border-top-color:var(--accent);border-radius:50%;animation:spin 1s linear infinite;vertical-align:-2px;margin-right:7px}@keyframes spin{to{transform:rotate(360deg)}}
.library{background:var(--library);color:#f4f8fc;border:1px solid var(--library);border-radius:var(--radius);padding:23px 20px 18px;position:sticky;top:18px;min-width:0;color-scheme:dark;box-shadow:0 12px 34px #10263818}
.library .eyebrow{color:var(--library-muted)}.library h2{font-size:25px}.library-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}.library .hint{color:var(--library-muted)}
.count-badge{border:1px solid var(--library-line);border-radius:7px;color:var(--library-muted);padding:3px 9px;font:12px 'Adwaita Mono',monospace}
.library input{background:var(--library-card)!important;border-color:var(--library-line)!important;color:#f4f8fc!important;font-size:13px}.library input::placeholder{color:var(--library-muted)}
.library-tools{display:flex;gap:8px;align-items:center;margin-bottom:12px}.refresh{background:var(--library-card);border:1px solid var(--library-line);border-radius:9px;color:#f4f8fc;min-width:43px;height:43px;font-size:18px}.refresh:hover{background:#28465b}
.now-playing{border:1px solid #496b82;border-radius:12px;background:linear-gradient(145deg,#1f4056,#183246);padding:14px;margin-bottom:12px}.now-label{font:700 9px 'Adwaita Mono',monospace;letter-spacing:1.2px;text-transform:uppercase;color:#9fbae0}.now-title{font-size:16px;line-height:1.3;margin-top:4px;overflow-wrap:anywhere}.now-meta{font-size:10px;color:var(--library-muted);margin-top:3px}.now-playing audio{width:100%;height:38px;display:block;margin-top:11px}.now-actions{display:flex;gap:15px;align-items:center;flex-wrap:wrap;margin-top:10px}
.hist{display:flex;flex-direction:column;gap:5px;max-height:calc(100vh - 430px);min-height:180px;overflow:auto;scrollbar-width:thin;scrollbar-color:var(--library-line) transparent;padding-right:3px}
.track-row{display:grid;grid-template-columns:36px minmax(0,1fr);align-items:center;gap:9px;border:1px solid transparent;border-radius:9px;padding:7px;background:transparent;min-width:0;flex-shrink:0}.track-row:hover{background:var(--library-card);border-color:#29475c}.track-row.selected{background:var(--library-card);border-color:#557890}.play-track{display:grid;place-items:center;width:34px;height:34px;border:1px solid var(--library-line);border-radius:8px;background:#203e53;color:#fff;font-size:12px;padding:0}.play-track:hover{background:#2d5169}.track-select{min-width:0;border:0;background:none;color:inherit;text-align:left;padding:0;cursor:pointer}.track-select>.hn,.track-select>.track-date{display:block}.hn{font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.35}.track-date{font-size:9px;color:var(--library-muted);margin-top:2px}.track-state{font-size:9px;color:#bcd0ef;margin-left:5px}
a.dl,.text-button{font-size:12px;font-weight:600;text-decoration:none;background:transparent;border:0;padding:0;color:var(--accent);cursor:pointer}.library a.dl,.library .text-button{color:#c5d9ff}.library a.dl:hover,.text-button:hover{text-decoration:underline}
.xdel{margin-left:auto;color:var(--library-muted);font-size:11px;background:none;border:0;padding:4px;min-height:28px}.xdel:hover{color:#fff;text-decoration:underline}
.file-details{margin-top:8px;border-top:1px solid var(--library-line);padding-top:3px}.file-details summary{font-size:10px;font-weight:400;color:var(--library-muted);min-height:26px}.file-details summary::after{font-size:14px;color:var(--library-muted)}
.hpath{font:10px/1.6 'Adwaita Mono',monospace;color:var(--library-muted);overflow-wrap:anywhere;padding:4px 0}.cp{display:inline-block;margin-top:4px;margin-left:6px;font-size:11px;border:0;background:none;color:var(--accent);cursor:pointer;padding:3px}.library .cp{color:#bed6ff}
.library-footer{font-size:10px;color:var(--library-muted);padding-top:12px;display:flex;justify-content:space-between;gap:8px}.empty{font-size:13px;color:var(--library-muted);padding:28px 10px;text-align:center}.empty strong{display:block;color:#f4f8fc;font-size:15px;margin-bottom:8px}
.warn{display:none;margin-bottom:18px;background:#fff4dc;border:1px solid #dfc182;border-radius:10px;padding:12px 16px;color:#684910;font-size:13px}.warn.show{display:block}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(min-width:1500px){.workspace{grid-template-columns:minmax(0,1fr) 430px}}
@media(max-width:1100px){.masthead{padding:22px 24px 18px}.wrap{padding:0 24px 30px}.workspace{grid-template-columns:minmax(0,1fr) 350px;gap:18px}.editor-heading{padding:22px 24px}.stage-content{padding-right:24px}.stage-rail{padding-left:20px}.row{gap:14px}.library{padding:20px 15px}.eng{max-width:230px}.idea-actions{grid-template-columns:1fr}.idea-actions .btn{width:100%}.render-action{align-items:stretch;flex-direction:column}.generate-note{max-width:none}#go{width:100%}}
@media(max-width:850px){.workspace{grid-template-columns:1fr}.library{position:static}.hist{max-height:520px}.engine-tools{gap:8px}.eng{max-width:190px}.masthead{padding-top:20px}.brand-sub{display:none}}
@media(max-width:520px){.masthead{padding:18px 16px 14px;gap:10px;flex-wrap:wrap}.brand-mark{width:37px;height:37px;border-radius:11px}h1{font-size:22px}.engine-tools{width:100%;justify-content:space-between;margin-top:3px}.eng{max-width:none}.wrap{padding:0 10px 24px}.editor-heading{padding:20px 17px}.editor-heading h2{font-size:26px}.session-badge{display:none}.stage{grid-template-columns:1fr}.stage-rail{padding:18px 17px 0}.stage-number{width:auto;height:auto;display:inline;border:0;background:none;color:var(--accent);font-size:10px}.stage-number::before{content:'STEP '}.stage-content{padding:8px 17px 24px}.stage-head{margin-bottom:14px}.row{grid-template-columns:1fr}.settings-row{gap:18px}.field-heading .hint{display:none}.idea-box{padding:13px}.idea-actions{grid-template-columns:1fr}.render-action{padding:14px}.tagbar{gap:5px}.library{border-radius:14px}.now-actions{gap:12px}}

/* Shared creative-desk skin: visual alignment with Qwen Image Desk and WAN Video Desk. */
:root{color-scheme:dark;--bg:#0b1015;--panel:#111820;--field:#0c131a;--line:#2a3743;--ink:#eef3f7;--muted:#94a4b3;--accent:#66c7e8;--accent-deep:#4ca8c9;--accent-soft:#122936;--signal:#ffc45e;--library:#111b25;--library-card:#172532;--library-line:#344858;--library-muted:#9db0c0;--radius:0}
body{background:var(--bg);color:var(--ink);font-family:Inter,'Segoe UI',system-ui,sans-serif}
a{color:var(--accent)}
:focus-visible{outline:2px solid var(--signal);outline-offset:3px}
.masthead{max-width:none;min-height:92px;margin:0;padding:18px clamp(24px,3vw,48px);position:sticky;top:0;z-index:20;background:rgba(8,13,18,.96);border-bottom:1px solid var(--line);backdrop-filter:blur(16px);box-shadow:none}
.brand-mark{width:48px;height:48px;border:1px solid #8b6727;border-radius:50%;background:transparent;color:var(--signal);box-shadow:inset 0 0 0 5px var(--bg),inset 0 0 0 6px #49391f}
.brand-mark i{width:3px;border-radius:1px}
h1,h2,h3{font-family:'Iowan Old Style','Palatino Linotype',Palatino,Georgia,serif;font-weight:500;letter-spacing:-.025em}
h1{font-size:31px;font-weight:500}.brand-sub{margin-top:1px;color:var(--signal);font:700 10px/1.4 'Adwaita Mono','SFMono-Regular',monospace;letter-spacing:1.6px;text-transform:uppercase}
.engine-tools{gap:8px}.eng{padding:7px 12px;border:1px solid #31506a;border-radius:999px;color:#a9bac8;font:11px 'Adwaita Mono','SFMono-Regular',monospace}.dot{background:var(--accent);box-shadow:0 0 0 3px #66c7e817}.eng-btn{border-radius:999px!important;min-height:32px!important;padding:6px 12px!important}
.wrap{max-width:none;margin:0;padding:0}.workspace{grid-template-columns:minmax(560px,1.05fr) minmax(420px,.8fr);gap:0;align-items:start;min-height:calc(100vh - 92px)}
.editor{background:linear-gradient(145deg,#111820 0%,#0e151c 100%);border:0;border-right:1px solid var(--line);border-radius:0;box-shadow:none;overflow:hidden}
.editor-heading{min-height:154px;padding:36px clamp(28px,4vw,64px);border-bottom:1px solid var(--line);background:radial-gradient(circle at 92% 12%,#173142 0,transparent 31%),linear-gradient(145deg,#111820,#0f171e)}
.eyebrow{color:var(--signal);font:700 10px/1.4 'Adwaita Mono','SFMono-Regular',monospace;letter-spacing:1.7px}.editor-heading p:last-child{color:var(--muted)}
h2{font-size:31px;font-weight:500}.session-badge{border:1px solid #31506a;border-radius:999px;background:#0b141c;color:#b6c7d5;padding:6px 11px}
.stage{grid-template-columns:68px minmax(0,1fr);border-bottom:1px solid var(--line)}.stage-rail{padding:32px 0 0 clamp(24px,3vw,48px)}.stage-number{display:block;width:31px;height:auto;padding-top:7px;border:0;border-top:2px solid var(--accent);border-radius:0;background:transparent;color:#93a5b3;text-align:left}.stage-content{padding:30px clamp(28px,4vw,64px) 38px 14px}.stage-head{margin-bottom:20px}.stage-head h3{font-size:25px;font-weight:500}.stage-head p{color:var(--muted)}.stage-kicker{color:var(--signal);letter-spacing:1.4px}
label{color:#dbe4ea} .optional,.hint{color:var(--muted)}
input:not([type=range]),textarea,select{border-color:var(--line);border-radius:8px;background:#0a1117;color:var(--ink);box-shadow:inset 0 1px 0 #ffffff05}
input::placeholder,textarea::placeholder{color:#70818f}
input:not([type=range]):focus,textarea:focus,select:focus{outline:1px solid var(--accent);border-color:var(--accent);background:#0b131a}
#title{color:var(--ink);border-bottom-color:var(--line)}
.idea-box,.settings-row{border:1px solid var(--line);border-radius:10px;background:linear-gradient(145deg,#13202a,#101820)}.idea-box textarea,.writer-field select,.settings-row input:not([type=range]){background:#091017}
.btn{border-radius:7px;background:var(--accent);color:#061117;box-shadow:none}.btn:hover:not(:disabled){background:#82d6f1;box-shadow:none}.btn.sec{border-color:var(--line);background:#17222c;color:var(--ink)}.btn.sec:hover:not(:disabled){background:#202e3a}
.tag{border-color:var(--line);border-radius:5px;background:#131d26;color:#a9b7c3}.tag:hover{border-color:var(--signal);color:var(--signal)}
.seed-random{border-color:var(--line);border-radius:7px;background:#17222c;color:var(--signal)}.seed-random:hover{border-color:var(--signal);background:#202d36}.slabel b{color:var(--signal)}input[type=range]{accent-color:var(--accent)}
.advanced{border-top-color:var(--line)}.advanced summary{color:#b4c1cb}
.render-action{border:1px solid #4e452e;border-radius:10px;background:linear-gradient(110deg,#181d1d,#242116)}.generate-note{color:var(--muted)}.generate-note strong{color:var(--ink)}#go{background:var(--signal);color:#201706}#go:hover:not(:disabled){background:#ffd47e}
#status{border-color:var(--line);background:#0d161e}.warn{border-color:#765b28;background:#2a2112;color:#ffe0a0}
.library{height:calc(100vh - 92px);top:92px;padding:36px clamp(24px,3vw,48px) 22px;position:sticky;border:0;border-radius:0;background:radial-gradient(circle at 100% 0,#183347 0,transparent 35%),linear-gradient(155deg,#152330 0%,#0f1922 72%);box-shadow:none;color:var(--ink)}
.library .eyebrow{color:var(--signal)}.library h2{font-size:31px;font-weight:500}.library-head{padding-bottom:18px;margin-bottom:18px;border-bottom:1px solid var(--library-line)}.count-badge{border-color:#3a586f;border-radius:999px;color:#b0c2cf}
.library input{border-color:var(--library-line)!important;border-radius:7px!important;background:#0c1821!important}.refresh{border-color:var(--library-line);border-radius:7px;background:#182b39;color:var(--accent)}.refresh:hover{background:#213b4e}
.now-playing{border:1px solid #3b5d74;border-radius:10px;background:linear-gradient(145deg,#193348,#132736);box-shadow:0 12px 30px #050a0e35}.now-label{color:var(--signal)}.now-title{font-family:'Iowan Old Style','Palatino Linotype',Palatino,Georgia,serif;font-size:19px;font-weight:500}.now-meta{color:var(--library-muted)}
.hist{max-height:calc(100vh - 452px);gap:5px}.track-row{border-radius:7px}.track-row:hover,.track-row.selected{background:#192c3a}.track-row:hover{border-color:#34556d}.track-row.selected{border-color:var(--accent)}.play-track{border-color:#3a586d;border-radius:6px;background:#1b3b4f;color:var(--accent)}.play-track:hover{background:#27536c}.library a.dl,.library .text-button,.library .cp{color:#91dafa}.track-state{color:#b8dded}
.library-footer{border-top:1px solid var(--library-line);margin-top:9px;padding-top:12px}
@media(max-width:1100px){.masthead{padding:18px 24px}.workspace{grid-template-columns:minmax(0,1fr) 365px}.wrap{padding:0}.editor-heading{padding:30px 28px}.stage-content{padding-right:28px}.library{padding:30px 20px 20px}.idea-actions{grid-template-columns:1fr}}
@media(max-width:850px){.workspace{grid-template-columns:1fr}.editor{border-right:0}.library{position:static;height:auto;min-height:560px;border-top:1px solid var(--line)}.hist{max-height:520px}.brand-sub{display:block}}
@media(max-width:520px){.masthead{padding:14px 16px}.brand-mark{width:40px;height:40px;border-radius:50%}h1{font-size:25px}.wrap{padding:0}.editor-heading{padding:26px 18px}.editor-heading h2{font-size:28px}.stage{grid-template-columns:1fr}.stage-rail{padding:22px 18px 0}.stage-number{width:31px}.stage-content{padding:9px 18px 28px}.library{border-radius:0;padding:28px 18px}.render-action{padding:14px}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
</style></head><body>
<header class="masthead">
  <div class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></div>
  <div><h1>MiniMax Music 3</h1><p class="brand-sub">Your local music studio</p></div>
  <div class="engine-tools"><span class="eng" role="status"><span class="dot" id="engdot" aria-hidden="true"></span><span id="engtxt">Checking engine…</span></span><button class="btn sec eng-btn" id="engbtn" style="display:none">Start engine</button></div>
</header>
<main class="wrap">
  <div class="warn" id="warn" role="alert"></div>
  <div class="workspace">
    <section class="editor" aria-labelledby="editorTitle">
      <div class="editor-heading"><div><p class="eyebrow">Studio session</p><h2 id="editorTitle">Take an idea to a finished track.</h2><p>Draft it, shape it, then render locally.</p></div><span class="session-badge">MUSIC 3 · LOCAL</span></div>
      <section class="stage" aria-labelledby="ideaTitle">
        <div class="stage-rail"><span class="stage-number">01</span></div>
        <div class="stage-content">
          <div class="stage-head"><div><span class="stage-kicker">Start here</span><h3 id="ideaTitle">Give Rhizome the rough idea.</h3><p>A genre, a feeling and what the song is about is enough.</p></div></div>
          <div class="idea-box">
            <label for="brief">Song brief</label><textarea id="brief" spellcheck="true" placeholder="Disco-house with a driving bassline and a powerful female vocal. A song about leaving a dead-end town behind."></textarea>
            <div class="idea-actions">
              <div class="writer-field"><label for="aimodel">Writing with <span>cloud models use no local VRAM</span></label><select id="aimodel"><option value="">Loading writers…</option></select></div>
              <button class="btn" id="aifill"><span class="rhizome-mark" aria-hidden="true">✦</span> Draft the song</button>
            </div>
            <div id="aistatus" role="status" aria-live="polite"></div>
          </div>
        </div>
      </section>
      <section class="stage" aria-labelledby="songTitle">
        <div class="stage-rail"><span class="stage-number">02</span></div>
        <div class="stage-content">
          <div class="stage-head"><div><span class="stage-kicker">Song sheet</span><h3 id="songTitle">Shape what gets performed.</h3><p>Rhizome fills these in; every word stays editable.</p></div></div>
          <div class="song-fields">
            <div class="field"><label for="title">Song name <span class="optional">optional</span></label><input type="text" id="title" placeholder="Give this track a name…" spellcheck="true" autocomplete="off"></div>
            <div class="field"><label for="caption">Sound &amp; performance</label><textarea class="cap" id="caption" spellcheck="true" aria-describedby="captionHelp"></textarea><span class="hint field-help" id="captionHelp">Genre, mood, instruments, vocal character and arrangement.</span></div>
            <div class="field"><div class="field-heading"><label for="lyrics">Lyrics &amp; structure</label><span class="hint">Section by section</span></div><textarea class="lyr" id="lyrics" spellcheck="true" aria-describedby="lyricsHelp"></textarea>
              <div class="tagbar" aria-label="Insert song section"><button class="tag" data-tag="Intro" type="button">+ Intro</button><button class="tag" data-tag="Verse" type="button">+ Verse</button><button class="tag" data-tag="Chorus" type="button">+ Chorus</button><button class="tag" data-tag="Instrumental" type="button">+ Instrumental</button><button class="tag" data-tag="Bridge" type="button">+ Bridge</button><button class="tag" data-tag="Outro" type="button">+ Outro</button></div>
              <span class="hint field-help" id="lyricsHelp">For an instrumental, keep the section tags and leave out lyric lines.</span>
            </div>
          </div>
        </div>
      </section>
      <section class="stage" aria-labelledby="renderTitle">
        <div class="stage-rail"><span class="stage-number">03</span></div>
        <div class="stage-content">
          <div class="stage-head"><div><span class="stage-kicker">Render</span><h3 id="renderTitle">Set the take and generate.</h3><p>The music engine starts automatically and rests when idle.</p></div></div>
          <div class="row settings-row">
            <div><div class="slabel"><label for="seconds">Track length</label><b id="seclab">1m 00s</b></div><input type="range" id="seconds" min="8" max="300" step="1" value="60"><div class="mmss"><input type="number" id="mins" min="0" max="5" step="1" value="1" aria-label="Minutes"><span>min</span><input type="number" id="secs" min="0" max="59" step="1" value="0" aria-label="Seconds"><span>sec</span><span style="margin-left:auto">Up to 5 min</span></div></div>
            <div><label for="seed">Seed <span class="optional">optional</span></label><div class="seed-row"><input type="text" id="seed" placeholder="Random each time" inputmode="numeric"><button class="seed-random" id="randomSeed" type="button" title="Choose random seed" aria-label="Choose random music seed">↻</button></div><span class="hint field-help">Reuse a seed to revisit the same starting point.</span></div>
          </div>
          <details class="advanced" id="advanced"><summary>Fine-tune generation <span class="hint">Quality &amp; output</span></summary><div class="row">
            <div><div class="slabel"><label for="steps">Steps</label><b id="steplab">30</b></div><input type="range" id="steps" min="8" max="60" step="1" value="30"></div>
            <div><div class="slabel"><label for="cfg">Guidance</label><b id="cfglab">1.7</b></div><input type="range" id="cfg" min="1" max="6" step="0.1" value="1.7"></div>
            <div><label for="tiled">Memory-saving decode</label><select id="tiled"><option value="0">Off</option><option value="1">On · useful for long songs</option></select></div>
            <div><label for="quality">MP3 quality</label><select id="quality"><option value="V0">V0 · high quality, variable bitrate</option><option value="320k">320 kbps · maximum bitrate</option><option value="128k">128 kbps · smaller file</option></select></div>
          </div></details>
          <div class="render-action"><p class="generate-note"><strong>Everything stays on this machine.</strong>Your settings and audio are saved with the track.</p><button class="btn" id="go">Generate music</button></div>
          <div id="status" role="status" aria-live="polite"></div>
        </div>
      </section>
    </section>
    <aside class="library" aria-labelledby="libraryTitle">
      <div class="library-head"><div><p class="eyebrow">Listening room</p><h2 id="libraryTitle">Your tracks</h2></div><span class="count-badge" id="trackCount" aria-label="Track count">—</span></div>
      <div class="now-playing" id="nowPlaying" hidden>
        <p class="now-label">On the deck</p><h3 class="now-title" id="nowTitle"></h3><p class="now-meta" id="nowMeta"></p>
        <audio id="libraryPlayer" controls preload="metadata"></audio>
        <div class="now-actions"><a class="dl" id="nowDownload" href="#" download>Download</a><button class="text-button" id="nowLoad" type="button">Load settings</button><button class="xdel" id="nowDelete" type="button">Delete</button></div>
        <details class="file-details"><summary>File details</summary><div class="hpath" id="nowPath"></div></details>
      </div>
      <div class="library-tools"><label for="trackSearch" class="sr-only">Search recent tracks</label><input id="trackSearch" type="search" placeholder="Find a track…" autocomplete="off"><button id="refreshTracks" class="refresh" title="Refresh tracks" aria-label="Refresh tracks">↻</button></div>
      <div class="hist" id="hist"><p class="empty">Loading your tracks…</p></div>
      <p id="noMatches" class="empty" hidden>No matching tracks. Try another name.</p>
      <div class="library-footer"><span>Recent tracks · newest first</span><span>Saved locally</span></div>
    </aside>
  </div>
</main>
<script>
const $=s=>document.querySelector(s);
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const DEF_CAP=`__CAP__`, DEF_LYR=`__LYR__`;
$('#caption').value=DEF_CAP; $('#lyrics').value=DEF_LYR;

// ---- AI brief -> autofill ----
// The backend exposes every live route/tag. The studio deliberately presents a
// short writing roster; long-context aliases are useful elsewhere but only make
// this one-job picker noisy.
const DEFAULT_WRITER='openclaw/openai/gpt-5.6-sol';
const WRITERS=[
  {id:DEFAULT_WRITER,label:'Rhizome · GPT-5.6 Sol',group:'Recommended'},
  {id:'openclaw/openai/gpt-5.6-luna',label:'GPT-5.6 Luna · quicker',group:'Cloud'},
  {id:'openclaw/openai/gpt-5.6-terra',label:'GPT-5.6 Terra · deeper',group:'Cloud'},
  {id:'openclaw/openai/gpt-6-astra',label:'GPT-6 Astra · long context',group:'Cloud'},
  {id:'openclaw/anthropic/claude-sonnet-4-6',label:'Claude Sonnet 4.6',group:'Cloud'},
  {id:'openclaw/anthropic/claude-opus-4-6',label:'Claude Opus 4.6',group:'Cloud'},
  {id:'qwen3-8-27b-turbofcfusion-735-882-here--dec14241:fast16k',label:'TurboFusion 27B · fast 16K',group:'Local · uses VRAM'},
  {id:'qwen3-6-27b-fable-fus-711-unheretic-nm--0f9c77ed:fast16k',label:'Fable 27B · fast 16K',group:'Local · uses VRAM'},
  {id:'ornith-1.5:35b',label:'Ornith 35B',group:'Local · uses VRAM'}
];
let _modelSig='';
async function loadModels(){
  try{
    const d=await (await fetch('/api/ai_models')).json();
    const ms=d.models||[];
    const sig=ms.join('|');
    if(sig===_modelSig) return;              // unchanged — leave the dropdown alone
    _modelSig=sig;
    const sel=$('#aimodel'); const prev=sel.value; sel.innerHTML='';
    if(!ms.length){sel.innerHTML='<option value="">no models (OpenClaw/Ollama offline)</option>';return;}
    const available=WRITERS.filter(writer=>ms.includes(writer.id));
    const grp=(label,items)=>{
      if(!items.length)return;
      const g=document.createElement('optgroup'); g.label=label;
      items.forEach(writer=>{const o=document.createElement('option');o.value=writer.id;
        o.textContent=writer.label; g.appendChild(o);});
      sel.appendChild(g);
    };
    [...new Set(available.map(writer=>writer.group))].forEach(group=>grp(group,available.filter(writer=>writer.group===group)));
    if(!available.length){sel.innerHTML='<option value="">no supported writing models online</option>';return;}
    sel.value=(prev && available.some(writer=>writer.id===prev))?prev:(available.some(writer=>writer.id===DEFAULT_WRITER)?DEFAULT_WRITER:available[0].id);
  }catch(e){ if(!_modelSig) $('#aimodel').innerHTML='<option value="">models unavailable</option>'; }
}
loadModels(); setInterval(loadModels, 30000);
$('#aifill').addEventListener('click',async()=>{
  const model=$('#aimodel').value, brief=$('#brief').value.trim();
  if(!model){$('#aistatus').textContent='⚠ pick a model';return;}
  if(!brief){$('#aistatus').textContent='⚠ give it a brief first';return;}
  const btn=$('#aifill'); btn.disabled=true;
  $('#aistatus').innerHTML='<span class="spin"></span>Writing with '+esc($('#aimodel').selectedOptions[0]?.textContent||model)+'…';
  try{
    const secs=parseInt($('#seconds').value)||60;
    const r=await fetch('/api/ai_fill',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({model,brief,seconds:secs})});
    const d=await r.json();
    if(!r.ok) throw new Error(d.error||'failed');
    if(d.title)$('#title').value=d.title;
    if(d.caption)$('#caption').value=d.caption;
    if(d.lyrics)$('#lyrics').value=d.lyrics;
    // Free VRAM only for LOCAL models; cloud models use none.
    if(model.startsWith('openclaw/')){
      $('#aistatus').textContent='✓ filled — tweak anything and hit Generate.';
    }else{
      $('#aistatus').innerHTML='<span class="spin"></span>filled — freeing GPU…';
      try{await fetch('/api/ai_unload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model})});}catch(_){}
      $('#aistatus').textContent='✓ filled & GPU freed — tweak anything and hit Generate.';
    }
  }catch(e){$('#aistatus').textContent='⚠ '+e.message;}
  finally{btn.disabled=false;}
});
const bind=(id,lab,suf='')=>{const e=$(id);const l=$(lab);const u=()=>l.textContent=e.value+suf;e.addEventListener('input',u);u();};
bind('#steps','#steplab'); bind('#cfg','#cfglab');

// Length: slider <-> minutes/seconds boxes, clamped 8..300s.
const LMIN=8, LMAX=300, pad=n=>String(n).padStart(2,'0');
function fmtLen(t){const m=Math.floor(t/60),s=t%60;return m>0?(m+'m '+pad(s)+'s'):(s+'s');}
function setLen(t,src){
  t=Math.max(LMIN,Math.min(LMAX,Math.round(t)));
  $('#seconds').value=t; $('#seclab').textContent=fmtLen(t);
  if(src!=='boxes'){$('#mins').value=Math.floor(t/60);$('#secs').value=t%60;}
}
$('#seconds').addEventListener('input',()=>setLen(+$('#seconds').value,'slider'));
function fromBoxes(){
  const m=Math.max(0,Math.min(5,parseInt($('#mins').value||'0',10)));
  const s=Math.max(0,Math.min(59,parseInt($('#secs').value||'0',10)));
  setLen(m*60+s,'boxes');
}
$('#mins').addEventListener('input',fromBoxes);
$('#secs').addEventListener('input',fromBoxes);
// Normalise when leaving the pair, not while focus moves into the other box.
const reflect=()=>{const t=+$('#seconds').value;$('#mins').value=Math.floor(t/60);$('#secs').value=t%60;};
$('#mins').addEventListener('blur',event=>{if(event.relatedTarget!==$('#secs'))reflect();});
$('#secs').addEventListener('blur',event=>{if(event.relatedTarget!==$('#mins'))reflect();});
setLen(60);

$('#randomSeed').addEventListener('click',()=>{
  const values=new Uint32Array(2);crypto.getRandomValues(values);
  $('#seed').value=String((BigInt(values[0])<<16n)+BigInt(values[1]&0xffff));
});

let engineOK=false, engBusy=false;
function fmtIdle(s){ if(s==null)return''; const m=Math.floor(s/60),ss=s%60; return m>0?(m+'m '+ss+'s'):(ss+'s'); }
async function health(){
  try{const r=await fetch('/api/health');const d=await r.json();engineOK=d.comfy;engBusy=d.busy;
    $('#engdot').style.background=d.comfy?'#3ddc84':(d.starting?'#e0a72a':'#8a8f98');
    const btn=$('#engbtn');
    if(d.starting){
      $('#engtxt').textContent='engine starting…'; btn.style.display='none';
      $('#warn').classList.remove('show');
    }else if(d.comfy){
      let t='engine online';
      if(d.busy) t+=' · generating';
      else if(d.idle_remaining!=null) t+=' · idle-stop in '+fmtIdle(d.idle_remaining);
      $('#engtxt').textContent=t;
      btn.style.display=''; btn.textContent='Stop engine'; btn.dataset.act='stop';
      btn.disabled=d.busy;
      $('#warn').classList.remove('show');
    }else{
      $('#engtxt').textContent=d.idle_stopped?'Ready · engine resting':'Ready · starts when you generate';
      btn.style.display=''; btn.textContent='Start engine'; btn.dataset.act='start'; btn.disabled=false;
      $('#warn').classList.remove('show');
    }
  }catch(e){$('#engtxt').textContent='engine unreachable';}
}
$('#engbtn').addEventListener('click',async()=>{
  const act=$('#engbtn').dataset.act;
  const btn=$('#engbtn'); btn.disabled=true;
  btn.textContent = act==='stop'?'Stopping…':'Starting…';
  try{
    const r=await fetch('/api/engine/'+act,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const d=await r.json();
    if(!r.ok && d.error) alert(d.error);
  }catch(e){alert('failed: '+e.message);}
  health();
});
health(); setInterval(health,5000);

let timer=null;
async function poll(pid){
  try{
    const r=await fetch('/api/status?prompt_id='+encodeURIComponent(pid));
    const d=await r.json();
    if(d.state==='working'){
      $('#status').innerHTML='<span class="spin"></span>Generating… '+d.elapsed+'s'+(d.where?(' · '+esc(d.where)):'');
      return;
    }
    clearInterval(timer);timer=null;
    if(d.state==='error'){
      $('#status').innerHTML='⚠ Failed after '+d.elapsed+'s — '+esc(d.error||'unknown error');
      $('#go').disabled=false;$('#go').textContent='Generate music';return;
    }
    if(d.state==='done'){
      $('#status').innerHTML='✓ '+((d.meta&&d.meta.title)?('“'+esc(d.meta.title)+'” — '):'')+'Done in '+d.elapsed+'s (seed '+(d.meta&&d.meta.seed)+')'+
        '<audio controls autoplay src="'+esc(d.audio_url)+'"></audio>'+
        '<div style="margin-top:8px"><a class="dl" href="'+esc(d.audio_url)+'" download="'+esc(d.filename)+'">⤓ Download '+esc(d.filename)+'</a></div>'+
        (d.path?('<div class="pathline">Saved to: '+esc(d.path)+'<button type="button" class="cp" data-copy="'+esc(d.path)+'">Copy path</button></div>'):'');
      wireCopy($('#status'));
      $('#go').disabled=false;$('#go').textContent='Generate music';
      loadHist();
    }
  }catch(e){/* transient */}
}

$('#go').addEventListener('click',async()=>{
  if(!$('#caption').value.trim()){ $('#status').className='show';$('#status').textContent='Describe the sound before generating.';$('#caption').focus();return; }
  const payload={
    title:$('#title').value, caption:$('#caption').value, lyrics:$('#lyrics').value,
    seconds:+$('#seconds').value, seed:$('#seed').value.trim()||'random',
    steps:+$('#steps').value, cfg:+$('#cfg').value, tiled:$('#tiled').value==='1',
    quality:$('#quality').value
  };
  $('#go').disabled=true;$('#go').textContent='Working…';
  $('#status').className='show';
  $('#status').innerHTML='<span class="spin"></span>'+(engineOK?'Submitting…':'Starting engine (first run ~15s)…');
  try{
    const r=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    if(!r.ok){throw new Error(d.error||'submit failed');}
    if($('#seed').value.trim()===''){$('#seed').placeholder=d.seed;}
    timer=setInterval(()=>poll(d.prompt_id),1500);poll(d.prompt_id);
  }catch(e){
    $('#status').textContent='⚠ '+e.message;
    $('#go').disabled=false;$('#go').textContent='Generate music';
  }
});

function wireCopy(root){
  root.querySelectorAll('.cp[data-copy]').forEach(el=>{
    el.onclick=async()=>{try{await navigator.clipboard.writeText(el.dataset.copy);
      const o=el.textContent;el.textContent='copied ✓';setTimeout(()=>el.textContent=o,1200);}catch(e){}};
  });
}
async function deleteGen(fn,btn){
  if(!confirm('Delete this track?\n\n'+fn))return;
  btn.disabled=true;
  try{
    const r=await fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:fn})});
    const d=await r.json();
    if(!r.ok){alert(d.error||'delete failed');btn.disabled=false;return;}
    loadHist();
  }catch(e){alert('delete failed: '+e.message);btn.disabled=false;}
}
async function loadRecipe(fn){
  try{
    const r=await fetch('/api/recipe?filename='+encodeURIComponent(fn));
    const d=await r.json();
    if(!r.ok){alert(d.error||'could not load settings');return;}
    $('#title').value=d.title||'';
    $('#caption').value=d.caption||'';
    $('#lyrics').value=d.lyrics||'';
    $('#seed').value=(d.seed!=null?d.seed:'');
    if(d.length_seconds!=null) setLen(d.length_seconds);
    if(d.steps!=null){$('#steps').value=d.steps;$('#steplab').textContent=d.steps;}
    if(d.guidance_cfg!=null){$('#cfg').value=d.guidance_cfg;$('#cfglab').textContent=d.guidance_cfg;}
    $('#tiled').value=d.tiled_decode?'1':'0';
    if(d.quality) $('#quality').value=d.quality;
    $('#advanced').open=true;   // reveal Advanced so it's clear
    window.scrollTo({top:0,behavior:'smooth'});
    $('#title').focus();
    const st=$('#status');st.className='show';
    st.innerHTML='↻ Loaded settings from <b>'+esc(fn)+'</b> — tweak anything and hit Generate.';
  }catch(e){alert('could not load settings: '+e.message);}
}
let historyItems=[],currentTrack=null;
const libraryPlayer=$('#libraryPlayer');
function trackView(it){
  return {
    name:it.filename.replace(/\.(mp3|flac|wav)$/i,'').replace(/_\d+_?$/,'').replace(/_/g,' '),
    date:new Date(it.mtime*1000).toLocaleDateString('en-GB',{day:'numeric',month:'short'}),
    size:it.size<1048576 ? `${Math.round(it.size/1024)} KB` : `${(it.size/1048576).toFixed(1)} MB`
  };
}
function refreshTrackStates(){
  $('#hist').querySelectorAll('.track-row').forEach(row=>{
    const selected=currentTrack&&row.dataset.filename===currentTrack.filename;
    row.classList.toggle('selected',Boolean(selected));
    row.querySelector('.track-state').textContent=selected?'Selected':'';
    const play=row.querySelector('.play-track');
    const playing=selected&&!libraryPlayer.paused;
    play.textContent=playing?'Ⅱ':'▶';
    play.setAttribute('aria-label',(playing?'Pause ':'Play ')+row.dataset.title);
  });
}
function selectTrack(it,autoplay=false){
  const view=trackView(it),same=currentTrack&&currentTrack.filename===it.filename;
  currentTrack=it;
  $('#nowPlaying').hidden=false;$('#nowTitle').textContent=view.name;$('#nowMeta').textContent=view.date+' · '+view.size;
  if(!same){libraryPlayer.src=it.url;libraryPlayer.setAttribute('aria-label','Play '+view.name);}
  const download=$('#nowDownload');download.href=it.url;download.download=it.filename;
  const load=$('#nowLoad');load.hidden=!it.recipe;load.onclick=()=>loadRecipe(it.filename);
  $('#nowDelete').onclick=()=>deleteGen(it.filename,$('#nowDelete'));
  $('#nowPath').innerHTML=esc(it.path)+'<button type="button" class="cp" data-copy="'+esc(it.path)+'">Copy path</button>';
  wireCopy($('#nowPlaying'));refreshTrackStates();
  if(autoplay){
    if(same&&!libraryPlayer.paused)libraryPlayer.pause();
    else libraryPlayer.play().catch(()=>{});
  }
}
function filterHistory(){
  const query=$('#trackSearch').value.trim().toLocaleLowerCase();
  const tracks=[...$('#hist').querySelectorAll('.track-row')];
  let visible=0;
  tracks.forEach(el=>{el.hidden=!el.dataset.filename.toLocaleLowerCase().includes(query);if(!el.hidden)visible++;});
  $('#trackCount').textContent=query ? `${visible}/${tracks.length}` : String(tracks.length);
  $('#noMatches').textContent='No matching tracks. Try another name.';
  $('#noMatches').hidden=!query || visible>0 || !tracks.length;
}
async function loadHist(){
  const refresh=$('#refreshTracks');refresh.disabled=true;
  try{
    const r=await fetch('/api/history');
    if(!r.ok)throw new Error('Could not load tracks');
    const d=await r.json();
    const box=$('#hist');box.innerHTML='';
    historyItems=d.items||[];
    $('.library-footer span').textContent=d.items?.length===40?'Latest 40 tracks · newest first':'Recent tracks · newest first';
    if(!d.items||!d.items.length){
      currentTrack=null;libraryPlayer.pause();libraryPlayer.removeAttribute('src');$('#nowPlaying').hidden=true;
      box.innerHTML='<p class="empty"><strong>Your first track starts here.</strong>Describe a sound and generate music. Your recordings will appear here.</p>';
      filterHistory();return;
    }
    d.items.forEach((it,index)=>{
      const view=trackView(it),el=document.createElement('article');el.className='track-row';el.dataset.filename=it.filename;el.dataset.title=view.name;
      el.innerHTML=
        '<button class="play-track" type="button" aria-label="Play '+esc(view.name)+'">▶</button>'+
        '<button class="track-select" type="button"><span class="hn">'+esc(view.name)+'<span class="track-state"></span></span><span class="track-date">'+esc(view.date)+' · '+esc(view.size)+'</span></button>';
      el.querySelector('.play-track').onclick=()=>selectTrack(it,true);
      el.querySelector('.track-select').onclick=()=>selectTrack(it,false);
      box.appendChild(el);
    });
    const keep=currentTrack&&d.items.find(it=>it.filename===currentTrack.filename);
    selectTrack(keep||d.items[0],false);
    filterHistory();
  }catch(e){
    $('#trackCount').textContent='—';
    $('#noMatches').hidden=true;
    if(!$('#hist').querySelector('.track-row'))$('#hist').innerHTML='<p class="empty">Could not load tracks. Use Refresh to try again.</p>';
    else{ $('#noMatches').textContent='Could not refresh tracks. Your previous list is still shown.';$('#noMatches').hidden=false; }
  }finally{refresh.disabled=false;}
}
$('#trackSearch').addEventListener('input',filterHistory);
$('#refreshTracks').addEventListener('click',loadHist);
libraryPlayer.addEventListener('play',refreshTrackStates);libraryPlayer.addEventListener('pause',refreshTrackStates);libraryPlayer.addEventListener('ended',refreshTrackStates);
document.addEventListener('play',event=>{
  if(event.target.tagName==='AUDIO')document.querySelectorAll('audio').forEach(audio=>{if(audio!==event.target)audio.pause();});
},true);
document.querySelectorAll('[data-tag]').forEach(button=>button.addEventListener('click',()=>{
  const lyrics=$('#lyrics');const start=lyrics.selectionStart;
  const prefix=start>0&&lyrics.value[start-1]!=='\n'?'\n':'';
  lyrics.setRangeText(prefix+'['+button.dataset.tag+']\n',start,lyrics.selectionEnd,'end');
  lyrics.focus();lyrics.dispatchEvent(new Event('input',{bubbles:true}));
}));
loadHist();

</script>
</body></html>
"""
INDEX_HTML = INDEX_HTML.replace("__CAP__", DEFAULT_CAPTION.replace("`", "\\`")) \
                       .replace("__LYR__", DEFAULT_LYRICS.replace("`", "\\`"))


def main():
    os.makedirs(LOGDIR, exist_ok=True)
    if comfy_up():
        touch_activity()  # don't idle-kill an engine that's already up at boot
    threading.Thread(target=watchdog, daemon=True).start()
    srv = ThreadingHTTPServer((APP_HOST, APP_PORT), Handler)
    print("MiniMax Music 3 app  ->  http://%s:%d" % (APP_HOST, APP_PORT))
    print("ComfyUI engine       ->  %s  (%s)" % (COMFY, "up" if comfy_up() else "DOWN - starts on demand"))
    idle_txt = ("%d min" % (IDLE_SECONDS // 60)) if IDLE_SECONDS > 0 else "disabled"
    print("Idle auto-stop       ->  %s" % idle_txt)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
