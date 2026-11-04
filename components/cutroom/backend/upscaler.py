"""Single-flight Lanczos and Real-ESRGAN 1080p mastering for Video Desk."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from fractions import Fraction
from pathlib import Path

from engine import STACK_ROOT, atomic_json


MODEL = os.environ.get("VIDEO_UPSCALER_NCNN_MODEL", "realesrgan-x4plus")
GPU = os.environ.get("VIDEO_UPSCALE_VULKAN_DEVICE", "0")
SCRATCH = Path(os.environ.get(
    "VIDEO_UPSCALE_SCRATCH", STACK_ROOT / "creative/state/video-upscale-scratch"
)).expanduser()
MEDIA_LOCK = Path(os.environ.get(
    "VIDEO_UPSCALE_LOCK", STACK_ROOT / "creative/state/media-generation.lock"
)).expanduser()
FILTER_1080P = (
    "scale=1920:1080:flags=lanczos+accurate_rnd+full_chroma_int:"
    "force_original_aspect_ratio=decrease:force_divisible_by=2,"
    "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1,format=yuv420p"
)


def _realesrgan_paths() -> tuple[Path | None, Path | None]:
    configured = os.environ.get("VIDEO_UPSCALER_NCNN_BIN")
    executable = Path(configured).expanduser() if configured else None
    if executable is None:
        found = shutil.which("realesrgan-ncnn-vulkan")
        executable = Path(found) if found else None
    configured_models = os.environ.get("VIDEO_UPSCALER_NCNN_MODELS")
    models = Path(configured_models).expanduser() if configured_models else None
    if models is None and executable is not None:
        models = executable.parent / "models"
    return executable, models


class UpscaleManager:
    METHODS = ("lanczos", "realesrgan")

    def __init__(self, state_path: Path, *, log_dir: Path | None = None,
                 audio_codec: str = "copy"):
        self.state_path = state_path
        self.log_dir = log_dir
        self.audio_codec = audio_codec
        self.lock = threading.RLock()
        self.state = self._load()
        if self.state.get("status") == "running":
            self.state.update(status="failed", stage="interrupted", progress=0,
                              error="Studio restarted during mastering",
                              finished_at=time.time())
            self._save()

    def _load(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {"status": "idle", "stage": "idle", "progress": 0}

    def _save(self) -> None:
        atomic_json(self.state_path, self.state)

    def snapshot(self) -> dict:
        with self.lock:
            result = copy.deepcopy(self.state)
        if result.get("started_at") and result.get("status") == "running":
            result["elapsed_seconds"] = round(time.time() - result["started_at"], 1)
        return result

    def running(self) -> bool:
        with self.lock:
            return self.state.get("status") == "running"

    def _update(self, **values) -> None:
        with self.lock:
            self.state.update(values)
            self._save()

    @staticmethod
    def _probe(path: Path) -> dict:
        raw = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries",
            "stream=index,codec_type,width,height,avg_frame_rate,nb_frames:format=duration",
            "-of", "json", str(path),
        ], text=True, timeout=30)
        data = json.loads(raw)
        video = next((item for item in data.get("streams", [])
                      if item.get("codec_type") == "video"), None)
        if not video:
            raise RuntimeError("Selected take has no video stream")
        fps = Fraction(video.get("avg_frame_rate") or "0/1")
        try:
            frames = int(video.get("nb_frames") or 0)
        except (TypeError, ValueError):
            frames = 0
        if frames <= 0:
            frames = int(subprocess.check_output([
                "ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
                "-show_entries", "stream=nb_read_packets", "-of", "default=nw=1:nk=1",
                str(path),
            ], text=True, timeout=120).strip())
        if frames <= 0 or fps <= 0:
            raise RuntimeError("Selected take needs a constant frame rate and frame count")
        return {
            "width": int(video.get("width") or 0), "height": int(video.get("height") or 0),
            "frames": frames, "fps": fps,
            "audio": any(item.get("codec_type") == "audio" for item in data.get("streams", [])),
        }

    @staticmethod
    def _dimensions(path: Path) -> tuple[int, int]:
        value = subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path),
        ], text=True, timeout=30).strip()
        width, height = value.split("x", 1)
        return int(width), int(height)

    def start(self, take_id: str, source: Path, output_dir: Path,
              method: str = "lanczos") -> dict:
        method = str(method).lower()
        if method not in self.METHODS:
            raise ValueError("Mastering method must be lanczos or realesrgan")
        with self.lock:
            if self.state.get("status") == "running":
                raise RuntimeError("A 1080p master is already running")
            if (self.state.get("status") == "complete"
                    and self.state.get("take_id") == take_id
                    and self.state.get("method") == method
                    and Path(self.state.get("output_path", "")).is_file()):
                return copy.deepcopy(self.state)
            executable, models = _realesrgan_paths()
            if method == "realesrgan":
                if executable is None or not executable.is_file() or not os.access(executable, os.X_OK):
                    raise RuntimeError(
                        "Real-ESRGAN NCNN is unavailable; set VIDEO_UPSCALER_NCNN_BIN"
                    )
                if models is None or not all((models / f"{MODEL}.{suffix}").is_file()
                                             for suffix in ("param", "bin")):
                    raise RuntimeError(
                        "Real-ESRGAN model files are unavailable; set VIDEO_UPSCALER_NCNN_MODELS"
                    )
            info = self._probe(source)
            SCRATCH.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)
            if method == "realesrgan":
                required = info["frames"] * info["width"] * info["height"] * 52 + 2 * 1024**3
                free = shutil.disk_usage(SCRATCH).free
                if free < required:
                    raise RuntimeError(
                        f"Upscale scratch needs about {required / 1024**3:.1f} GiB free; "
                        f"only {free / 1024**3:.1f} GiB is available"
                    )
            job_id = "upscale-" + uuid.uuid4().hex[:12]
            suffix = "esrgan" if method == "realesrgan" else "lanczos"
            output = output_dir / f"{source.stem}_1080p_{suffix}.mp4"
            if output.exists():
                output = output_dir / f"{source.stem}_1080p_{suffix}_{job_id[-6:]}.mp4"
            started = time.time()
            self.state = {
                "id": job_id, "status": "running", "stage": "preparing", "progress": 1,
                "method": method, "take_id": take_id, "source_path": str(source),
                "output_path": str(output),
                "media_url": f"/media/wan-video-studio/generated/{output.name}",
                "current_frame": 0, "total_frames": info["frames"],
                "source_width": info["width"], "source_height": info["height"],
                "width": 1920, "height": 1080, "fps": str(info["fps"]),
                "model": MODEL if method == "realesrgan" else "FFmpeg Lanczos",
                "gpu": GPU if method == "realesrgan" else None,
                "scratch_root": str(SCRATCH), "started_at": started,
                "elapsed_seconds": 0, "error": None,
            }
            self._save()
        threading.Thread(target=self._run, args=(info, executable, models), daemon=True,
                         name="video-desk-1080p-master").start()
        return self.snapshot()

    def _run_progress(self, command: list[str], stage: str, low: int, high: int,
                      total: int, log_handle) -> None:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1)
        last = 0
        assert process.stdout is not None
        for line in process.stdout:
            log_handle.write(line)
            log_handle.flush()
            if line.startswith("frame="):
                try:
                    last = min(total, int(line.split("=", 1)[1].strip()))
                except ValueError:
                    continue
                self._update(stage=stage, progress=low + round((high - low) * last / total),
                             current_frame=last)
        if process.wait():
            raise RuntimeError(f"{stage.capitalize()} failed; see {self.state.get('log_path')}")

    def _run_realesrgan(self, command: list[str], output_dir: Path,
                        total: int, log_handle) -> None:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1)
        last = 0
        assert process.stdout is not None
        for line in process.stdout:
            log_handle.write(line)
            log_handle.flush()
            if line.rstrip().endswith(" done"):
                last = min(total, last + 1)
                self._update(stage="enhancing", progress=20 + round(68 * last / total),
                             current_frame=last)
        if process.wait():
            raise RuntimeError(f"Neural upscale failed; see {self.state.get('log_path')}")
        produced = len(list(output_dir.glob("*.png")))
        if produced != total:
            raise RuntimeError(f"Neural upscale produced {produced} of {total} frames")

    def _run(self, info: dict, executable: Path | None, models: Path | None) -> None:
        job = self.snapshot()
        source = Path(job["source_path"])
        output = Path(job["output_path"])
        partial = output.with_suffix(".partial.mp4")
        work = None
        lock_handle = None
        log_root = self.log_dir if self.log_dir is not None else output.parent.parent / "logs"
        log_path = log_root / f"{job['id']}.log"
        try:
            MEDIA_LOCK.parent.mkdir(parents=True, exist_ok=True)
            lock_handle = MEDIA_LOCK.open("a+")
            try:
                fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Another local media job is using the GPU or encoder") from exc
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._update(log_path=str(log_path))
            fps = str(info["fps"])
            total = info["frames"]
            audio_args = (["-c:a", "copy"] if self.audio_codec == "copy"
                          else ["-c:a", "aac", "-b:a", "192k"])
            with log_path.open("a", buffering=1) as log_handle:
                log_handle.write(f"method={job['method']}\nsource={source}\noutput={output}\n")
                if job["method"] == "lanczos":
                    self._update(stage="mastering", progress=5, current_frame=0)
                    self._run_progress([
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-i", str(source), "-map", "0:v:0", "-map", "0:a?", "-map_metadata", "0",
                        "-vf", FILTER_1080P, "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                        "-pix_fmt", "yuv420p", *audio_args, "-movflags", "+faststart", str(partial),
                        "-progress", "pipe:1", "-nostats",
                    ], "mastering", 5, 99, total, log_handle)
                else:
                    assert executable is not None and models is not None
                    work = Path(tempfile.mkdtemp(prefix=f"{job['id']}.", dir=SCRATCH))
                    inputs, enhanced = work / "input", work / "enhanced"
                    inputs.mkdir()
                    enhanced.mkdir()
                    self._update(stage="extracting", progress=5, current_frame=0)
                    self._run_progress([
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-i", str(source), "-map", "0:v:0", "-fps_mode", "passthrough",
                        "-start_number", "1", str(inputs / "%08d.png"),
                        "-progress", "pipe:1", "-nostats",
                    ], "extracting", 5, 20, total, log_handle)
                    self._update(stage="enhancing", progress=20, current_frame=0)
                    self._run_realesrgan([
                        str(executable), "-i", str(inputs), "-o", str(enhanced),
                        "-m", str(models), "-n", MODEL, "-s", "4", "-t", "0",
                        "-j", "1:2:2", "-g", GPU, "-f", "png", "-v",
                    ], enhanced, total, log_handle)
                    first_in = self._dimensions(inputs / "00000001.png")
                    first_out = self._dimensions(enhanced / "00000001.png")
                    if first_out != (first_in[0] * 4, first_in[1] * 4):
                        raise RuntimeError("Real-ESRGAN output was not the required native 4× size")
                    duration = float(total / info["fps"])
                    self._update(stage="mastering", progress=88, current_frame=0)
                    self._run_progress([
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-framerate", fps, "-start_number", "1", "-i", str(enhanced / "%08d.png"),
                        "-i", str(source), "-map", "0:v:0", "-map", "1:a?", "-map_metadata", "1",
                        "-t", f"{duration:.6f}", "-vf", FILTER_1080P,
                        "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
                        *audio_args, "-movflags", "+faststart", str(partial),
                        "-progress", "pipe:1", "-nostats",
                    ], "mastering", 88, 99, total, log_handle)
            checked = self._probe(partial)
            if (checked["width"], checked["height"], checked["frames"]) != (1920, 1080, total):
                raise RuntimeError("The 1080p master failed its resolution or frame-count check")
            if info["audio"] and not checked["audio"]:
                raise RuntimeError("The 1080p master lost the source audio")
            os.replace(partial, output)
            finished = time.time()
            self._update(status="complete", stage="complete", progress=100,
                         current_frame=total, finished_at=finished,
                         elapsed_seconds=round(finished - job["started_at"], 1),
                         size_bytes=output.stat().st_size)
        except Exception as exc:
            partial.unlink(missing_ok=True)
            finished = time.time()
            self._update(status="failed", stage="failed", error=str(exc),
                         finished_at=finished,
                         elapsed_seconds=round(finished - job["started_at"], 1))
        finally:
            if work is not None and work.parent == SCRATCH and work.name.startswith(job["id"] + "."):
                shutil.rmtree(work, ignore_errors=True)
            if lock_handle is not None:
                fcntl.flock(lock_handle, fcntl.LOCK_UN)
                lock_handle.close()
