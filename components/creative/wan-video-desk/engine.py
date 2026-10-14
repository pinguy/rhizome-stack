#!/usr/bin/env python3
"""ComfyUI adapters and a persistent single-flight generation queue."""

from __future__ import annotations

import copy
from fractions import Fraction
import json
import os
import random
import re
import shutil
import signal
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


STACK_ROOT = Path(os.environ.get("RHIZOME_STACK_ROOT", "~/.local/share/rhizome-stack")).expanduser()
COMFY_DIR = Path(os.environ.get("COMFY_DIR", STACK_ROOT / "creative/ComfyUI"))
COMFY_INPUT = COMFY_DIR / "input"
COMFY_OUTPUT = COMFY_DIR / "output"
PYTHON = Path(os.environ.get("COMFY_PY", COMFY_DIR / ".venv/bin/python"))
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
COMFY_IDLE_SECONDS = max(60, int(os.environ.get("COMFY_IDLE_SECONDS", "300")))
WAN_BACKEND = "wan-2.2-rapid"
WAN_T2V_MODEL = "wan2.2-t2v-rapid-aio-v10-nsfw-Q5_K.gguf"
WAN_I2V_MODEL = "wan2.2-i2v-rapid-aio-v10-nsfw-Q5_K.gguf"
WAN_MODEL_MODES = {WAN_T2V_MODEL: ("t2v",), WAN_I2V_MODEL: ("t2v", "i2v")}
WAN_TEXT_ENCODER = "umt5-xxl-encoder-Q4_K_M.gguf"
WAN_VAE = "wan_2.1_vae.safetensors"
WAN_CLIP_VISION = "clip_vision_h.safetensors"
WAN_FPS = 16
WAN_FPS_OPTIONS = (16, 24)
WAN_MIN_STEPS = 4
WAN_MAX_STEPS = 20
WAN_MAX_SECONDS = 10
WAN_CFG = 1.0
WAN_VAE_DEVICE = os.environ.get("WAN_VAE_DEVICE", "gpu:0")
WAN_DECODE_TEMPORAL_SIZE = 64
WAN_DECODE_TEMPORAL_OVERLAP = 16
# Ordered quality-to-memory fallback ladder. The same-latent reference test
# measured 48/12 at a +0.0999 four-frame reset, versus +0.0751 for 64/16 and
# +0.3032 for 32/8. Try the higher-quality 48/12 window first; reserve 32/12
# for a second decoder OOM on tighter hardware.
WAN_DECODE_FALLBACKS = ((48, 12), (32, 12))


def atomic_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _json_request(path: str, payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        COMFY_URL + path, data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def comfy_up() -> bool:
    try:
        _json_request("/system_stats", timeout=3)
        return True
    except Exception:
        return False


def qc_video(path: Path, expected_frames: int, expected_fps: int | None = None) -> dict:
    """Fast advisory QC. Metrics never reject or delete a generated take."""
    warnings = []
    metrics = {}
    try:
        probe = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=nb_frames,width,height,r_frame_rate:format=duration",
            "-of", "json", str(path),
        ], text=True, timeout=30))
        stream = (probe.get("streams") or [{}])[0]
        frames = int(stream.get("nb_frames") or 0)
        fps = round(float(Fraction(stream.get("r_frame_rate") or "0/1")), 3)
        metrics.update(frames=frames, fps=fps,
                       duration=round(float((probe.get("format") or {}).get("duration") or 0), 6),
                       width=int(stream.get("width") or 0), height=int(stream.get("height") or 0))
        if frames and frames != int(expected_frames):
            warnings.append(f"Expected {expected_frames} frames; decoded {frames}.")
        if expected_fps and fps and abs(fps - int(expected_fps)) > 0.01:
            warnings.append(f"Expected {expected_fps} fps; decoded {fps:g} fps.")

        scan = subprocess.run([
            "ffmpeg", "-hide_banner", "-i", str(path), "-vf",
            "freezedetect=n=-45dB:d=0.35,blackdetect=d=0.1:pix_th=0.10,"
            "blurdetect=block_width=32:block_height=32:block_pct=80",
            "-an", "-f", "null", "-",
        ], text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180, check=False).stderr
        freeze_count = len(re.findall(r"freeze_start:", scan))
        black_count = len(re.findall(r"black_start:", scan))
        blur = re.search(r"blur mean:\s*([0-9.]+)", scan)
        metrics.update(freeze_events=freeze_count, black_events=black_count,
                       blur_mean=round(float(blur.group(1)), 4) if blur else None)
        if freeze_count:
            warnings.append(f"Possible temporal freeze detected ({freeze_count} event).")
        if black_count:
            warnings.append(f"Possible black-frame range detected ({black_count} event).")

        motion = subprocess.run([
            "ffmpeg", "-v", "error", "-i", str(path), "-vf",
            "tblend=all_mode=difference,signalstats,metadata=print:file=-",
            "-an", "-f", "null", "-",
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=180, check=False).stdout
        values = [float(value) for value in re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", motion)]
        if values:
            median = statistics.median(values)
            ratio = max(values) / median if median > 1e-9 else 0.0
            metrics.update(motion_yavg_median=round(median, 4), motion_peak_ratio=round(ratio, 3))
            if ratio > 3.5:
                warnings.append(f"Large adjacent-frame motion/flicker spike ({ratio:.1f}× median).")
    except Exception as exc:
        warnings.append(f"Automated QC could not complete: {type(exc).__name__}.")
    return {"status": "warning" if warnings else "pass", "warnings": warnings,
            "metrics": metrics, "method": "ffprobe + FFmpeg freeze/black/blur/adjacent-motion scan",
            "checked_at": time.time()}


class ComfyEngine:
    """Owns only processes it starts; never uses broad process killing."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.pid_file = state_dir / "comfy.pid"
        self.profile_file = state_dir / "comfy.profile"
        self.log_file = state_dir / "comfy.log"
        self.lock = threading.RLock()

    def owned_pid(self) -> int | None:
        try:
            pid = int(self.pid_file.read_text().strip())
            command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            main = str((COMFY_DIR / "main.py").resolve())
            if main in command and "--port 8188" in command and os.getpgid(pid) == pid:
                return pid
        except (OSError, ValueError, ProcessLookupError):
            pass
        return None

    def status(self) -> dict:
        online = comfy_up()
        pid = self.owned_pid()
        owned = pid is not None
        result = {"online": online, "owned": owned, "pid": pid if owned else None}
        if online:
            try:
                q = _json_request("/queue", timeout=5)
                result["running"] = len(q.get("queue_running") or [])
                result["pending"] = len(q.get("queue_pending") or [])
            except Exception:
                pass
        return result

    def start(self, profile="legacy-static", wait=120) -> bool:
        with self.lock:
            if comfy_up():
                active_profile = None
                try:
                    active_profile = self.profile_file.read_text().strip()
                except OSError:
                    pass
                status = self.status()
                if not status.get("owned") or active_profile == profile:
                    return True
                self.stop_owned()
            self.state_dir.mkdir(parents=True, exist_ok=True)
            log = self.log_file.open("ab")
            env = dict(os.environ)
            visible_devices = os.environ.get("COMFY_CUDA_VISIBLE_DEVICES")
            if visible_devices:
                env.update({"CUDA_DEVICE_ORDER": "PCI_BUS_ID",
                            "CUDA_VISIBLE_DEVICES": visible_devices})
            args = [str(PYTHON), str(COMFY_DIR / "main.py"), "--listen", "127.0.0.1",
                    "--port", "8188"]
            # LTX/Qwen retain their measured static low-VRAM arrangement. WAN
            # GGUF runs in NORMAL_VRAM with DynamicVRAM: forcing --lowvram did
            # not change the Q5 placement or sampling rate and added 31 seconds
            # to the controlled 640x480 I2V canary.
            if profile != "wan-dynamic":
                args.extend(("--lowvram", "--disable-dynamic-vram"))
            proc = subprocess.Popen(
                args,
                cwd=COMFY_DIR, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True, env=env,
            )
            self.pid_file.write_text(str(proc.pid))
            self.profile_file.write_text(profile + "\n")
        deadline = time.time() + wait
        while time.time() < deadline:
            if comfy_up():
                return True
            if proc.poll() is not None:
                break
            time.sleep(1.5)
        return False

    def stop_owned(self) -> bool:
        with self.lock:
            try:
                pid = self.owned_pid()
                if pid is None:
                    return False
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGTERM)
                deadline = time.time() + 10
                while time.time() < deadline:
                    try:
                        waited, _ = os.waitpid(pid, os.WNOHANG)
                        if waited == pid:
                            break
                    except ChildProcessError:
                        break
                    time.sleep(0.2)
                else:
                    os.killpg(pgid, signal.SIGKILL)
                    try:
                        os.waitpid(pid, 0)
                    except ChildProcessError:
                        pass
            except Exception:
                return False
            finally:
                try:
                    self.pid_file.unlink()
                except OSError:
                    pass
                try:
                    self.profile_file.unlink()
                except OSError:
                    pass
        return True

    def free_models(self) -> None:
        if comfy_up():
            try:
                _json_request("/free", {"unload_models": True, "free_memory": True}, timeout=30)
            except Exception:
                pass


def qwen_graph(prompt: str, negative: str, seed: int, width: int, height: int,
               prefix: str, steps: int = 25, cfg: float = 1.0,
               reference_name: str | None = None) -> dict:
    graph = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "qwen-image-2.1-UC-Q8_0.gguf"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "cpu"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "4": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0], "prompt": prompt,
            "negative_prompt": negative or "", "resolution": max(int(width), int(height))}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {
            "width": int(width), "height": int(height), "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "seed": int(seed), "steps": int(steps), "cfg": float(cfg),
            "sampler_name": "euler", "scheduler": "simple", "positive": ["4", 0],
            "negative": ["4", 1], "latent_image": ["5", 0], "denoise": 1.0}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": prefix}},
    }
    if reference_name:
        graph["9"] = {"class_type": "LoadImage", "inputs": {"image": reference_name}}
        graph["10"] = {"class_type": "ImageScale", "inputs": {
            "image": ["9", 0], "upscale_method": "lanczos", "width": int(width),
            "height": int(height), "crop": "center"}}
        graph["4"]["inputs"].update({"images.image_1": ["10", 0], "resolution": 0})
        graph["6"]["inputs"]["latent_image"] = ["4", 2]
        del graph["5"]
    return graph


def video_graph(template: dict, job: dict, prefix: str, reference_name: str | None = None) -> dict:
    graph = copy.deepcopy(template)
    mode = job.get("mode", "t2v")
    prompt_node = "4" if mode == "i2v" else "3"
    negative_node = "5" if mode == "i2v" else "4"
    seed_node = "16" if mode == "i2v" else "11"
    save_node = "24" if mode == "i2v" else "20"
    latent_node = "10" if mode == "i2v" else "6"
    graph[prompt_node]["inputs"]["text"] = job["prompt"]
    graph[negative_node]["inputs"]["text"] = job.get("negative") or (
        "text, titles, lettering, watermark, cuts, scene change, duplicate subject, "
        "distorted face, asymmetrical eyes, deformed anatomy, flicker, pulsing, camera shake")
    graph[seed_node]["inputs"]["noise_seed"] = int(job["seed"])
    width, height = job.get("width", 768), job.get("height", 448)
    frames = int(job.get("frames", 49))
    graph[latent_node]["inputs"].update({"width": width, "height": height, "length": frames})
    if mode == "i2v":
        graph["9"]["inputs"]["image"] = reference_name
        graph["13"]["inputs"]["frames_number"] = frames
        # 384/32 is the measured fast Ti path with useful headroom. 416/32 can
        # cross the 6 GB card's peak after a previous department was resident.
        graph["21"]["inputs"].update({"tile_size": 384, "temporal_size": 32,
                                       "overlap": 64, "temporal_overlap": 16})
    else:
        graph["8"]["inputs"]["frames_number"] = frames
    graph[save_node]["inputs"]["filename_prefix"] = prefix
    return graph


def wan_t2v_graph(job: dict, prefix: str) -> dict:
    """Cordux WAN 2.2 Rapid recipe expressed as a dependency-light API graph."""
    width = int(job.get("width", 768))
    height = int(job.get("height", 448))
    frames = int(job.get("frames", 49))
    fps = int(job.get("fps", WAN_FPS))
    steps = int(job.get("steps", WAN_MIN_STEPS))
    video_model = str(job.get("video_model") or WAN_T2V_MODEL)
    if "t2v" not in WAN_MODEL_MODES.get(video_model, ()):
        raise ValueError("The selected WAN model does not support Text input")
    if width % 16 or height % 16:
        raise ValueError("WAN 2.2 width and height must be multiples of 16")
    if frames < 1 or (frames - 1) % 4:
        raise ValueError("WAN 2.2 frame count must use the 4n+1 sequence")
    if fps not in WAN_FPS_OPTIONS:
        raise ValueError("WAN 2.2 fps must be 16 or 24")
    if not WAN_MIN_STEPS <= steps <= WAN_MAX_STEPS:
        raise ValueError("WAN 2.2 steps must be between 4 and 20")
    prompt = str(job.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("WAN 2.2 needs a text prompt")
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {
            "unet_name": video_model}},
        "2": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 8.0}},
        "3": {"class_type": "CLIPLoaderGGUF", "inputs": {
            "clip_name": WAN_TEXT_ENCODER, "type": "wan"}},
        "4": {"class_type": "SelectCLIPDevice", "inputs": {"clip": ["3", 0], "device": "cpu"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": prompt}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
        "7": {"class_type": "VAELoader", "inputs": {"vae_name": WAN_VAE}},
        # Match the proven I2V decode path: keep WAN VAE work on the RTX 3060
        # and use the same temporal window and bounded OOM fallback.
        "8": {"class_type": "SelectVAEDevice", "inputs": {
            "vae": ["7", 0], "device": WAN_VAE_DEVICE}},
        "9": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {
            "width": width, "height": height, "length": frames, "batch_size": 1}},
        "10": {"class_type": "KSampler", "inputs": {
            "model": ["2", 0], "seed": int(job["seed"]), "steps": steps, "cfg": WAN_CFG,
            "sampler_name": "euler_ancestral", "scheduler": "beta",
            "positive": ["5", 0], "negative": ["6", 0],
            "latent_image": ["9", 0], "denoise": 1.0}},
        "11": {"class_type": "VAEDecodeTiled", "inputs": {
            "samples": ["10", 0], "vae": ["8", 0], "tile_size": 256,
            "overlap": 64, "temporal_size": WAN_DECODE_TEMPORAL_SIZE,
            "temporal_overlap": WAN_DECODE_TEMPORAL_OVERLAP}},
        "12": {"class_type": "CreateVideo", "inputs": {
            "images": ["11", 0], "fps": float(fps), "bit_depth": 8}},
        "13": {"class_type": "SaveVideo", "inputs": {
            "video": ["12", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"}},
    }


def wan_i2v_graph(job: dict, prefix: str, reference_name: str) -> dict:
    """WAN 2.2 Rapid image-to-video graph using only core and GGUF nodes."""
    width = int(job.get("width", 768))
    height = int(job.get("height", 448))
    frames = int(job.get("frames", 49))
    fps = int(job.get("fps", WAN_FPS))
    steps = int(job.get("steps", WAN_MIN_STEPS))
    video_model = str(job.get("video_model") or WAN_I2V_MODEL)
    if "i2v" not in WAN_MODEL_MODES.get(video_model, ()):
        raise ValueError("The selected T2V model needs Text input; choose the I2V model for Image input")
    if width % 16 or height % 16:
        raise ValueError("WAN 2.2 width and height must be multiples of 16")
    if frames < 1 or (frames - 1) % 4:
        raise ValueError("WAN 2.2 frame count must use the 4n+1 sequence")
    if fps not in WAN_FPS_OPTIONS:
        raise ValueError("WAN 2.2 fps must be 16 or 24")
    if not WAN_MIN_STEPS <= steps <= WAN_MAX_STEPS:
        raise ValueError("WAN 2.2 steps must be between 4 and 20")
    prompt = str(job.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("WAN 2.2 needs a text prompt")
    if not reference_name:
        raise ValueError("WAN 2.2 I2V needs a reference image")
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {
            "unet_name": video_model}},
        "2": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 8.0}},
        "3": {"class_type": "CLIPLoaderGGUF", "inputs": {
            "clip_name": WAN_TEXT_ENCODER, "type": "wan"}},
        "4": {"class_type": "SelectCLIPDevice", "inputs": {"clip": ["3", 0], "device": "cpu"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": prompt}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["4", 0], "text": str(job.get("negative") or "")}},
        "7": {"class_type": "VAELoader", "inputs": {"vae_name": WAN_VAE}},
        # I2V must encode the reference before sampling. The 6 GB GTX 1660
        # always OOMed that first encode and retried tiled; keeping this VAE on
        # the 3060 removed the failed pass without reducing Q5 residency.
        "8": {"class_type": "SelectVAEDevice", "inputs": {
            "vae": ["7", 0], "device": WAN_VAE_DEVICE}},
        "9": {"class_type": "LoadImage", "inputs": {"image": reference_name}},
        "10": {"class_type": "ImageScale", "inputs": {
            "image": ["9", 0], "upscale_method": "lanczos", "width": width,
            "height": height, "crop": "center"}},
        "11": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": WAN_CLIP_VISION}},
        "12": {"class_type": "CLIPVisionEncode", "inputs": {
            "clip_vision": ["11", 0], "image": ["10", 0], "crop": "center"}},
        "13": {"class_type": "WanImageToVideo", "inputs": {
            "positive": ["5", 0], "negative": ["6", 0], "vae": ["8", 0],
            "width": width, "height": height, "length": frames, "batch_size": 1,
            "clip_vision_output": ["12", 0], "start_image": ["10", 0]}},
        "14": {"class_type": "KSampler", "inputs": {
            "model": ["2", 0], "seed": int(job["seed"]), "steps": steps, "cfg": WAN_CFG,
            "sampler_name": "euler_ancestral", "scheduler": "beta",
            "positive": ["13", 0], "negative": ["13", 1],
            "latent_image": ["13", 2], "denoise": 1.0}},
        "15": {"class_type": "VAEDecodeTiled", "inputs": {
            "samples": ["14", 0], "vae": ["8", 0], "tile_size": 256,
            "overlap": 64, "temporal_size": WAN_DECODE_TEMPORAL_SIZE,
            "temporal_overlap": WAN_DECODE_TEMPORAL_OVERLAP}},
        "16": {"class_type": "CreateVideo", "inputs": {
            "images": ["15", 0], "fps": float(fps), "bit_depth": 8}},
        "17": {"class_type": "SaveVideo", "inputs": {
            "video": ["16", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"}},
    }


def decode_fallback_plan(backend: str) -> tuple[tuple[int, int], ...]:
    """Return bounded temporal decode retries in quality-first order."""
    return WAN_DECODE_FALLBACKS if backend == WAN_BACKEND else ((16, 8),)


def apply_decode_fallback(graph: dict, backend: str, mode: str, attempt: int) -> tuple[int, int]:
    """Apply one decoder-only OOM fallback without changing the selected model or input mode."""
    temporal_size, temporal_overlap = decode_fallback_plan(backend)[attempt]
    decode_node = (("15" if mode == "i2v" else "11") if backend == WAN_BACKEND
                   else ("21" if mode == "i2v" else "17"))
    graph[decode_node]["inputs"].update({
        "tile_size": 256,
        "overlap": 64,
        "temporal_size": temporal_size,
        "temporal_overlap": temporal_overlap,
    })
    return temporal_size, temporal_overlap


class GenerationQueue:
    def __init__(self, root: Path, workflows: Path, load_project, save_project):
        self.root = root
        self.workflows = workflows
        self.load_project = load_project
        self.save_project = save_project
        self.state_path = root / "state/queue.json"
        self.engine = ComfyEngine(root / "state")
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.pause_after_current = False
        self.last_activity = time.time()
        self.jobs = self._load()
        for job in self.jobs:
            if job.get("status") == "running":
                job.update(status="failed", stage="interrupted", error="Studio restarted during generation")
        self._save()
        self.worker = threading.Thread(target=self._loop, daemon=True, name="studio-generation-queue")
        self.worker.start()

    def _load(self):
        try:
            return json.loads(self.state_path.read_text()).get("jobs", [])
        except Exception:
            return []

    def _save(self):
        atomic_json(self.state_path, {"jobs": self.jobs[-500:],
                                     "pause_after_current": self.pause_after_current})

    def snapshot(self):
        with self.lock:
            return {"jobs": copy.deepcopy(self.jobs), "pause_after_current": self.pause_after_current,
                    "engine": self.engine.status()}

    def add(self, payload: dict) -> list[dict]:
        payload = copy.deepcopy(payload)
        created = []
        takes = max(1, min(12, int(payload.pop("take_count", 1))))
        fixed_seed = payload.get("seed")
        if fixed_seed is None or payload.get("randomise_seed"):
            rng = random.SystemRandom()
            seeds = [rng.randrange(0, 2**63) for _ in range(takes)]
        else:
            fixed_seed = int(fixed_seed)
            if not 0 <= fixed_seed <= 2**63 - takes:
                raise ValueError("Seed plus take count must stay between 0 and 9223372036854775807")
            seeds = [fixed_seed + i for i in range(takes)]
        with self.lock:
            for i in range(takes):
                job = copy.deepcopy(payload)
                job["id"] = "job-" + uuid.uuid4().hex[:12]
                job["created_at"] = time.time()
                job["status"] = "queued"
                job["stage"] = "waiting"
                job["seed"] = seeds[i]
                created.append(job)
                self.jobs.append(job)
            self._save()
        self.wake.set()
        return created

    def action(self, action: str, job_id: str | None = None):
        with self.lock:
            if action == "pause_after_current":
                self.pause_after_current = True
            elif action == "resume":
                self.pause_after_current = False
                self.wake.set()
            elif action == "cancel" and job_id:
                job = next((j for j in self.jobs if j["id"] == job_id), None)
                if job and job["status"] == "queued":
                    job.update(status="cancelled", stage="cancelled")
            elif action == "retry" and job_id:
                source = next((j for j in self.jobs if j["id"] == job_id), None)
                if source and source["status"] in ("failed", "cancelled"):
                    retry = {k: copy.deepcopy(v) for k, v in source.items()
                             if k not in ("id", "status", "stage", "error", "started_at", "finished_at", "result")}
                    retry.update(id="job-" + uuid.uuid4().hex[:12], status="queued", stage="waiting",
                                 created_at=time.time(), retry_of=job_id)
                    self.jobs.append(retry)
                    self.wake.set()
            self._save()
        return self.snapshot()

    def _next(self):
        with self.lock:
            if self.pause_after_current:
                return None
            return next((j for j in self.jobs if j["status"] == "queued"), None)

    def _loop(self):
        while True:
            job = self._next()
            if not job:
                if time.time() - self.last_activity >= COMFY_IDLE_SECONDS:
                    status = self.engine.status()
                    if status.get("online") and status.get("owned"):
                        self.engine.stop_owned()
                        self.last_activity = time.time()
                self.wake.wait(2)
                self.wake.clear()
                continue
            self._run(job)

    def _set(self, job, **values):
        with self.lock:
            job.update(values)
            self._save()

    def _run(self, job):
        self.last_activity = time.time()
        self._set(job, status="running", stage="starting engine", started_at=time.time(), error=None)
        reference_name = None
        try:
            project = self.load_project(job["project_id"])
            project_dir = self.root / "projects" / job["project_id"]
            prefix = f"wan-video-desk/{job['project_id']}/{job['id']}"
            kind = job["kind"]
            backend = job.get("backend") or project.get("settings", {}).get("video_backend") or WAN_BACKEND
            profile = "wan-dynamic" if kind == "video" and backend == WAN_BACKEND else "legacy-static"
            if not self.engine.start(profile=profile):
                raise RuntimeError("ComfyUI did not become ready; see state/comfy.log")
            # Free previous department's models before changing from art to video or vice versa.
            self.engine.free_models()
            reference_name = None
            if kind == "art":
                self._set(job, stage="encoding art prompt")
                reference = job.get("reference_image")
                if reference:
                    source = (project_dir / reference["path"]).resolve(strict=True)
                    if not source.is_relative_to(project_dir.resolve()):
                        raise ValueError("Reference image must belong to this project")
                    reference_name = f"wan-video-desk-{job['id']}.png"
                    shutil.copy2(source, COMFY_INPUT / reference_name)
                    self._set(job, stage="encoding reference and edit prompt")
                graph = qwen_graph(job["prompt"], job.get("negative", ""), job["seed"],
                                   job.get("width", 768), job.get("height", 448), prefix,
                                   job.get("steps", 25), job.get("cfg", 1.0), reference_name)
            else:
                self._set(job, stage="encoding video prompt")
                mode = job.get("mode", "t2v")
                if backend == WAN_BACKEND:
                    if mode == "i2v":
                        reference = job.get("reference_image")
                        if not reference:
                            raise ValueError("WAN 2.2 I2V job has no valid reference image")
                        source = (project_dir / reference["path"]).resolve(strict=True)
                        if not source.is_relative_to(project_dir.resolve()):
                            raise ValueError("Reference image must belong to this project")
                        reference_name = f"wan-video-desk-{job['id']}.png"
                        shutil.copy2(source, COMFY_INPUT / reference_name)
                        self._set(job, stage="encoding reference and motion prompt")
                        graph = wan_i2v_graph(job, prefix, reference_name)
                    else:
                        graph = wan_t2v_graph(job, prefix)
                elif backend == "ltx-2.5":
                    template_name = "ltx_i2v.json" if mode == "i2v" else "ltx_t2v_quality_anchor.json"
                    template = json.loads((self.workflows / template_name).read_text())
                    if mode == "i2v":
                        asset = next((a for a in project.get("assets", []) if a["id"] == job.get("reference_asset_id")), None)
                        if not asset:
                            raise ValueError("I2V job has no valid approved reference")
                        source = project_dir / asset["path"]
                        reference_name = f"wan-video-desk-{job['id']}{source.suffix.lower()}"
                        shutil.copy2(source, COMFY_INPUT / reference_name)
                    graph = video_graph(template, job, prefix, reference_name)
                else:
                    raise ValueError(f"Unknown video backend: {backend}")
            history = None
            decode_fallbacks = decode_fallback_plan(backend) if kind == "video" else ()
            for decode_attempt in range(len(decode_fallbacks) + 1):
                self._set(job, stage="sampling" if decode_attempt == 0 else "retrying safe tiled decode")
                response = _json_request("/prompt", {"prompt": graph, "client_id": "wan-video-desk"}, timeout=30)
                prompt_id = response.get("prompt_id")
                if not prompt_id:
                    raise RuntimeError("ComfyUI rejected prompt: " + json.dumps(response))
                self._set(job, prompt_id=prompt_id)
                deadline = time.time() + (7200 if kind == "video" else 3600)
                decode_oom = False
                while time.time() < deadline:
                    time.sleep(2)
                    data = _json_request(f"/history/{prompt_id}", timeout=15)
                    history = data.get(prompt_id)
                    if history:
                        status = (history.get("status") or {}).get("status_str")
                        if status == "success":
                            break
                        if status == "error":
                            messages = (history.get("status") or {}).get("messages") or []
                            details = json.dumps(messages[-2:])
                            decode_oom = (kind == "video" and decode_attempt < len(decode_fallbacks)
                                          and "VAEDecodeTiled" in details
                                          and "out of memory" in details.lower())
                            if decode_oom:
                                temporal_size, temporal_overlap = apply_decode_fallback(
                                    graph, backend, job.get("mode", "t2v"), decode_attempt)
                                self._set(
                                    job,
                                    stage=f"retrying {temporal_size}/{temporal_overlap} tiled decode",
                                    decode_fallback=True,
                                    decode_fallback_attempt=decode_attempt + 1,
                                    decode_temporal_size=temporal_size,
                                    decode_temporal_overlap=temporal_overlap,
                                )
                                break
                            raise RuntimeError("ComfyUI generation failed: " + details)
                    elapsed = time.time() - job["started_at"]
                    if kind == "video" and elapsed > 70:
                        self._set(job, stage="sampling / tiled decode")
                else:
                    raise TimeoutError("generation exceeded its bounded wall timeout")
                if decode_oom:
                    continue
                break
            else:
                raise RuntimeError("safe tiled decode fallback was exhausted")

            extension = ".png" if kind == "art" else ".mp4"
            candidates = sorted((COMFY_OUTPUT / "wan-video-desk" / job["project_id"]).glob(job["id"] + "*" + extension),
                                key=lambda p: p.stat().st_mtime)
            if not candidates:
                raise FileNotFoundError(f"ComfyUI completed but no {extension} result was found")
            source = candidates[-1]
            if kind == "art":
                target_dir = project_dir / "references"
                target = target_dir / (job["id"] + source.suffix)
            else:
                target_dir = project_dir / "generated"
                target = target_dir / (job["id"] + source.suffix)
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            rel = str(target.relative_to(project_dir))
            self._set(job, stage="registering asset")
            if kind == "art":
                asset = {
                    "id": "asset-" + uuid.uuid4().hex[:10], "kind": job.get("asset_kind", "shot reference"),
                    "path": rel, "prompt": job["prompt"], "negative": job.get("negative", ""),
                    "original_prompt": job.get("original_prompt", job["prompt"]),
                    "expanded_prompt": job.get("expanded_prompt", job["prompt"]),
                    "expander_model": job.get("expander_model"),
                    "prompt_mode": job.get("prompt_mode", "direct"),
                    "reference_image": job.get("reference_image"),
                    "generation_mode": "edit" if job.get("reference_image") else "text-to-image",
                    "seed": job["seed"], "width": job.get("width", 768), "height": job.get("height", 448),
                    "image_preset": job.get("image_preset"),
                    "steps": job.get("steps", 25), "cfg": job.get("cfg", 1.0), "job_id": job["id"],
                    "model": "Qwen Image 2.1 Uncensored", "quant": "Q8_0 GGUF", "backend": "comfyui-qwen",
                    "created_at": time.time(), "project_id": job["project_id"], "shot_id": job.get("shot_id"),
                    "approved": False, "favourite": False, "state": "candidate",
                }
                project.setdefault("assets", []).append(asset)
                result_id = asset["id"]
            else:
                backend = job.get("backend") or project.get("settings", {}).get("video_backend") or WAN_BACKEND
                is_wan = backend == WAN_BACKEND
                generation_seconds = round(max(0.0, time.time() - float(job.get("started_at") or time.time())), 3)
                take = {
                    "id": "take-" + uuid.uuid4().hex[:10], "path": rel, "prompt": job["prompt"],
                    "negative": job.get("negative", ""),
                    "original_prompt": job.get("original_prompt", job["prompt"]),
                    "expanded_prompt": job.get("expanded_prompt", job["prompt"]),
                    "expander_model": job.get("expander_model"),
                    "prompt_mode": job.get("prompt_mode", "direct"),
                    "seed": job["seed"], "frames": job.get("frames", 49), "mode": job.get("mode", "t2v"),
                    "width": job.get("width", 768), "height": job.get("height", 448),
                    "duration_seconds": job.get("duration_seconds"), "quality": job.get("quality"),
                    "aspect_ratio": job.get("aspect_ratio"),
                    "backend": backend,
                    "model": (str(job.get("video_model") or
                                  (WAN_I2V_MODEL if job.get("mode") == "i2v" else WAN_T2V_MODEL))
                              if is_wan else "LTX-2.5"),
                    "quant": "Q5_K" if is_wan else "Q3_K_M", "fps": job.get("fps", WAN_FPS) if is_wan else 24,
                    "steps": job.get("steps", WAN_MIN_STEPS) if is_wan else None, "cfg": WAN_CFG if is_wan else None,
                    "sampler": "euler_ancestral" if is_wan else None,
                    "scheduler": "beta" if is_wan else None, "shift": 8.0 if is_wan else None,
                    "reference_asset_id": job.get("reference_asset_id"),
                    "reference_image": job.get("reference_image"),
                    "job_id": job["id"], "generation_seconds": generation_seconds,
                    "created_at": time.time(), "state": "review", "trim_in": 0, "trim_out": None,
                    "qc": qc_video(target, int(job.get("frames", 49)), int(job.get("fps", WAN_FPS))),
                }
                shot = next(s for s in project["shots"] if s["id"] == job["shot_id"])
                shot.setdefault("takes", []).append(take)
                result_id = take["id"]
            project["updated_at"] = time.time()
            self.save_project(project)
            self._set(job, status="complete", stage="complete", result={"id": result_id, "path": rel},
                      finished_at=time.time())
        except Exception as exc:
            self._set(job, status="failed", stage="failed", error=str(exc), finished_at=time.time())
        finally:
            self.last_activity = time.time()
            if reference_name:
                try:
                    (COMFY_INPUT / reference_name).unlink()
                except OSError:
                    pass
