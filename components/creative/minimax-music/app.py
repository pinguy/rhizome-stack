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
import threading
import time
import uuid
import urllib.request
import urllib.parse
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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
        with urllib.request.urlopen(OPENCLAW_API + "/models", timeout=6) as r:
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
                                     headers={"Content-Type": "application/json"})
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


class Handler(BaseHTTPRequestHandler):
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
<title>MiniMax Music 3</title>
<style>
:root{ --bg:#14161a; --panel:#1e2229; --panel2:#262b34; --line:#333a45;
       --ink:#eef1f5; --muted:#9aa4b2; --accent:#4c8dff; --accent2:#7c5cff; }
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:18px 22px;border-bottom:1px solid var(--line);
       display:flex;align-items:center;gap:12px}
header h1{font-size:18px;margin:0;font-weight:650;letter-spacing:.2px}
header .dot{width:10px;height:10px;border-radius:50%;background:var(--muted);flex:0 0 auto}
header .eng{font-size:12.5px;color:var(--muted);margin-left:auto}
.eng-btn{padding:8px 14px;font-size:13px}
.wrap{max-width:960px;margin:0 auto;padding:22px}
.grid{display:grid;grid-template-columns:1fr;gap:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px}
label{display:block;font-weight:600;margin:0 0 6px;font-size:13.5px}
.hint{color:var(--muted);font-weight:400;font-size:12.5px}
textarea,input,select{width:100%;background:var(--panel2);border:1px solid var(--line);
       color:var(--ink);border-radius:9px;padding:11px 12px;font:inherit;resize:vertical}
textarea:focus,input:focus,select:focus{outline:2px solid var(--accent);border-color:transparent}
textarea.cap{min-height:120px}textarea.lyr{min-height:150px;font-family:ui-monospace,Menlo,monospace;font-size:13px}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px}
.mmss{display:flex;align-items:center;gap:6px;margin-top:8px}
.mmss input{width:64px;text-align:center;padding:7px 8px}
.mmss span{font-size:12.5px;color:var(--muted)}
.btn{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;border:0;
     border-radius:10px;padding:13px 20px;font-weight:650;font-size:15px;cursor:pointer;width:100%}
.btn:disabled{opacity:.55;cursor:default}
.btnrow{display:flex;gap:12px;align-items:center;margin-top:4px}
.btn.sec{background:var(--panel2);border:1px solid var(--line);width:auto;padding:13px 16px}
details{margin-top:6px}summary{cursor:pointer;color:var(--muted);font-size:13.5px;font-weight:600}
.slabel{display:flex;justify-content:space-between}.slabel b{color:var(--accent)}
#status{display:none;margin-top:14px;padding:14px;border:1px solid var(--line);
        border-radius:10px;background:var(--panel2);font-size:14px}
#status.show{display:block}
.spin{display:inline-block;width:15px;height:15px;border:2px solid var(--muted);
      border-top-color:var(--accent);border-radius:50%;animation:sp 0.8s linear infinite;
      vertical-align:-2px;margin-right:8px}
@keyframes sp{to{transform:rotate(360deg)}}
audio{width:100%;margin-top:12px}
.hist{display:flex;flex-direction:column;gap:10px}
.hitem{background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:10px 12px;position:relative}
.hitem .hn{font-size:13px;color:var(--ink);margin-bottom:4px;word-break:break-all;font-weight:600;padding-right:28px}
.hitem .hpath{font-size:11.5px;color:var(--muted);margin-bottom:7px;word-break:break-all;
              font-family:ui-monospace,Menlo,monospace}
.hitem .hpath .cp{cursor:pointer;color:var(--accent);text-decoration:none;margin-left:6px;font-family:system-ui}
a.dl{color:var(--accent);font-size:13px;text-decoration:none;font-weight:600}
.hrow{display:flex;gap:16px;margin-top:6px;flex-wrap:wrap}
a.dl.load{color:var(--accent2)}
.xdel{position:absolute;top:8px;right:8px;width:24px;height:24px;border-radius:6px;
      background:var(--panel);border:1px solid var(--line);color:var(--muted);
      font-size:15px;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center}
.xdel:hover{border-color:#c04a4a;color:#ff8f8f}
.pathline{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:var(--muted);
          margin-top:8px;word-break:break-all}
.pathline .cp{cursor:pointer;color:var(--accent);text-decoration:none;margin-left:6px;font-family:system-ui}
.warn{background:#3a2c10;border:1px solid #6b5220;color:#ffd98a;padding:12px 14px;
      border-radius:10px;margin-bottom:16px;font-size:13.5px;display:none}
.warn.show{display:block}
kbd{background:var(--panel2);border:1px solid var(--line);border-radius:5px;padding:1px 6px;font-size:12px}
</style></head><body>
<header>
  <span class="dot" id="engdot"></span>
  <h1>MiniMax Music 3</h1>
  <span class="eng" id="engtxt">checking engine…</span>
  <button class="btn sec eng-btn" id="engbtn" style="display:none">Stop engine</button>
</header>
<div class="wrap">
  <div class="warn" id="warn"></div>
  <div class="card" id="aicard" style="margin-bottom:16px;border-color:var(--accent)">
    <label>✨ AI brief
      <span class="hint">— pick a model, give it styles + a one-line idea; it writes the description &amp; lyrics and names the song.</span></label>
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:6px">
      <div style="flex:0 0 260px">
        <label for="aimodel" class="hint">Model</label>
        <select id="aimodel"><option value="">loading…</option></select>
      </div>
      <div style="flex:1;min-width:280px">
        <label for="brief" class="hint">Brief</label>
        <textarea id="brief" spellcheck="true" style="width:100%;min-height:70px"
          placeholder="Styles: electronic-pop indie-rock&#10;Short description: synth late-night driving song in a neon-lit city."></textarea>
      </div>
    </div>
    <div class="btnrow" style="margin-top:10px">
      <button class="btn sec" id="aifill">✨ Fill in the details</button>
      <span id="aistatus" class="hint"></span>
    </div>
  </div>
  <div class="grid">
    <div class="card">
      <label for="title">Song name
        <span class="hint">— optional; becomes the file name (e.g. Rainy Night Lo-Fi).</span></label>
      <input type="text" id="title" placeholder="Untitled — a timestamped name is used if blank" spellcheck="true" style="margin-bottom:14px">

      <label>Describe the music
        <span class="hint">— style, mood, instruments, vocals. Specific = better.</span></label>
      <textarea class="cap" id="caption" spellcheck="true"></textarea>

      <label style="margin-top:14px">Lyrics &amp; structure
        <span class="hint">— use tags like <kbd>[Intro]</kbd> <kbd>[Verse]</kbd> <kbd>[Chorus]</kbd> <kbd>[Instrumental]</kbd> <kbd>[Outro]</kbd>. Leave lyric lines empty for instrumental.</span></label>
      <textarea class="lyr" id="lyrics" spellcheck="true"></textarea>

      <div class="row" style="margin-top:14px">
        <div>
          <div class="slabel"><label for="seconds">Length</label><b id="seclab">1m 00s</b></div>
          <input type="range" id="seconds" min="8" max="300" step="1" value="60">
          <div class="mmss">
            <input type="number" id="mins" min="0" max="5" step="1" value="1"><span>min</span>
            <input type="number" id="secs" min="0" max="59" step="1" value="0"><span>sec</span>
            <span class="hint" style="margin-left:auto">8s–5m</span>
          </div>
        </div>
        <div>
          <label for="seed">Seed <span class="hint">(blank = random)</span></label>
          <input type="text" id="seed" placeholder="random">
        </div>
      </div>

      <details>
        <summary>Advanced</summary>
        <div class="row" style="margin-top:12px">
          <div>
            <div class="slabel"><label for="steps">Steps</label><b id="steplab">30</b></div>
            <input type="range" id="steps" min="8" max="60" step="1" value="30">
          </div>
          <div>
            <div class="slabel"><label for="cfg">Guidance (cfg)</label><b id="cfglab">1.7</b></div>
            <input type="range" id="cfg" min="1" max="6" step="0.1" value="1.7">
          </div>
          <div>
            <label for="tiled">Tiled decode <span class="hint">(long songs / low VRAM)</span></label>
            <select id="tiled"><option value="0">Off</option><option value="1">On</option></select>
          </div>
          <div>
            <label for="quality">MP3 quality</label>
            <select id="quality">
              <option value="V0">V0 (VBR ~245k, best)</option>
              <option value="320k">320k (CBR, max)</option>
              <option value="128k">128k (CBR, small)</option>
            </select>
          </div>
        </div>
      </details>

      <div class="btnrow">
        <button class="btn" id="go">Generate music</button>
      </div>
      <div id="status"></div>
    </div>

    <div class="card">
      <label>Recent generations</label>
      <div class="hist" id="hist"><span class="hint">Nothing yet — make your first track.</span></div>
    </div>
  </div>
</div>
<script>
const $=s=>document.querySelector(s);
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const DEF_CAP=`__CAP__`, DEF_LYR=`__LYR__`;
$('#caption').value=DEF_CAP; $('#lyrics').value=DEF_LYR;

// ---- AI brief -> autofill ----
// Model dropdown from OpenClaw (cloud) + Ollama (local), grouped. Refreshes on a
// loop so it tracks the live list — same sources Open WebUI uses.
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
    const grp=(label,items,strip)=>{
      if(!items.length)return;
      const g=document.createElement('optgroup'); g.label=label;
      items.forEach(m=>{const o=document.createElement('option');o.value=m;
        o.textContent=strip?m.replace(/^openclaw\//,''):m; g.appendChild(o);});
      sel.appendChild(g);
    };
    grp('OpenClaw · cloud', ms.filter(m=>m.startsWith('openclaw/')), true);
    grp('Ollama · local (uses VRAM)', ms.filter(m=>!m.startsWith('openclaw/')), false);
    if(prev && ms.includes(prev)) sel.value=prev;   // preserve current selection
  }catch(e){ if(!_modelSig) $('#aimodel').innerHTML='<option value="">models unavailable</option>'; }
}
loadModels(); setInterval(loadModels, 30000);
$('#aifill').addEventListener('click',async()=>{
  const model=$('#aimodel').value, brief=$('#brief').value.trim();
  if(!model){$('#aistatus').textContent='⚠ pick a model';return;}
  if(!brief){$('#aistatus').textContent='⚠ give it a brief first';return;}
  const btn=$('#aifill'); btn.disabled=true;
  $('#aistatus').innerHTML='<span class="spin"></span>Writing with '+esc(model)+'…';
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
// normalise the boxes on blur (e.g. 90s typed in secs -> clamped, reflected)
const reflect=()=>{const t=+$('#seconds').value;$('#mins').value=Math.floor(t/60);$('#secs').value=t%60;};
$('#mins').addEventListener('change',reflect);
$('#secs').addEventListener('change',reflect);
setLen(60);

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
      $('#engtxt').textContent=d.idle_stopped?'engine stopped (idle — frees resources)':'engine off';
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
    const r=await fetch('/api/engine/'+act,{method:'POST'});
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
      $('#status').innerHTML='<span class="spin"></span>Generating… '+esc(d.elapsed)+'s'+(d.where?(' · '+esc(d.where)):'');
      return;
    }
    clearInterval(timer);timer=null;
    if(d.state==='error'){
      $('#status').textContent='⚠ Failed after '+d.elapsed+'s — '+(d.error||'unknown error');
      $('#go').disabled=false;$('#go').textContent='Generate music';return;
    }
    if(d.state==='done'){
      $('#status').innerHTML='✓ '+((d.meta&&d.meta.title)?('“'+esc(d.meta.title)+'” — '):'')+'Done in '+esc(d.elapsed)+'s (seed '+esc(d.meta&&d.meta.seed)+')'+
        '<audio controls autoplay src="'+esc(d.audio_url)+'"></audio>'+
        '<div style="margin-top:8px"><a class="dl" href="'+esc(d.audio_url)+'" download="'+esc(d.filename)+'">⤓ Download '+esc(d.filename)+'</a></div>'+
        (d.path?('<div class="pathline">Saved to: '+esc(d.path)+'<span class="cp" data-copy="'+esc(d.path)+'">copy</span></div>'):'');
      wireCopy($('#status'));
      $('#go').disabled=false;$('#go').textContent='Generate music';
      loadHist();
    }
  }catch(e){/* transient */}
}

$('#go').addEventListener('click',async()=>{
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
    document.querySelector('details').open=true;   // reveal Advanced so it's clear
    window.scrollTo({top:0,behavior:'smooth'});
    $('#title').focus();
    const st=$('#status');st.className='show';
    st.innerHTML='↻ Loaded settings from <b>'+esc(fn)+'</b> — tweak anything and hit Generate.';
  }catch(e){alert('could not load settings: '+e.message);}
}
async function loadHist(){
  try{
    const r=await fetch('/api/history');const d=await r.json();
    if(!d.items||!d.items.length){
      $('#hist').innerHTML='<span class="hint">Nothing yet — make your first track.</span>';return;}
    const box=$('#hist');box.innerHTML='';
    d.items.forEach(it=>{
      const el=document.createElement('div');el.className='hitem';
      el.innerHTML=
        '<button class="xdel" title="Delete">✕</button>'+
        '<div class="hn">'+esc(it.filename)+'</div>'+
        '<div class="hpath">'+esc(it.path)+'<span class="cp" data-copy="'+esc(it.path)+'">copy</span></div>'+
        '<audio controls preload="none" src="'+esc(it.url)+'"></audio>'+
        '<div class="hrow">'+
          '<a class="dl" href="'+esc(it.url)+'" download="'+esc(it.filename)+'">⤓ Download</a>'+
          (it.recipe?'<a class="dl load" href="#">↻ Load settings</a>':'')+
        '</div>';
      el.querySelector('.xdel').onclick=()=>deleteGen(it.filename,el.querySelector('.xdel'));
      const lb=el.querySelector('.load');
      if(lb) lb.onclick=(e)=>{e.preventDefault();loadRecipe(it.filename);};
      wireCopy(el);
      box.appendChild(el);
    });
  }catch(e){}
}
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
