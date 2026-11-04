#!/usr/bin/env python3
"""Deterministic FFmpeg edit/render path. The source song is always the clock."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


def _run(command: list[str], log, timeout=7200):
    log.write("$ " + " ".join(command) + "\n")
    log.flush()
    result = subprocess.run(command, stdout=log, stderr=log, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"ffmpeg exited {result.returncode}; see {log.name}")


def _take_map(project: dict) -> dict:
    return {t["id"]: t for shot in project.get("shots", []) for t in shot.get("takes", [])}


def _media_inside_project(project_dir: Path, relative: str) -> Path:
    """Resolve project-owned media, never arbitrary paths from editable project JSON.

    Missing takes can still fall back to a slate; the caller checks is_file().
    """
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("media path must be relative to the project")
    root = project_dir.resolve(strict=True)
    target = (root / relative).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("media path escapes the project directory")
    return target


def render(project_dir: Path, project: dict, preset: str = "720p") -> dict:
    if preset not in ("480p", "720p"):
        raise ValueError("unsupported render preset")
    width, height = (854, 480) if preset == "480p" else (1280, 720)
    audio_rel = (project.get("audio") or {}).get("path")
    if not audio_rel:
        raise ValueError("project has no source song")
    audio = _media_inside_project(project_dir, audio_rel)
    if not audio.is_file():
        raise ValueError("source song is missing")
    duration = float(project["analysis"]["audio"]["duration"])
    takes = _take_map(project)
    items = sorted((project.get("timeline") or {}).get("items") or [], key=lambda x: x["start"])
    if not items:
        for shot in project.get("shots", []):
            if shot.get("selected_take_id"):
                items.append({"id": "item-" + shot["id"], "shot_id": shot["id"],
                              "take_id": shot["selected_take_id"], "start": shot["start"],
                              "end": shot["end"], "trim_in": 0, "speed": 1.0,
                              "reverse": False, "fit": "cover", "transition": "cut"})
    if not items:
        raise ValueError("timeline has no kept takes")

    renders = project_dir / "renders"
    work = project_dir / "timeline/render-work"
    renders.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:12]
    output = renders / f"{project['id']}-{preset}-{stamp}.mp4"
    log_path = project_dir / "logs" / f"render-{stamp}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    segment_paths = []

    try:
        with tempfile.TemporaryDirectory(prefix=f"{stamp}-", dir=work) as scratch_name:
            scratch = Path(scratch_name)
            with log_path.open("w") as log:
                for index, item in enumerate(items):
                    target = max(.04, float(item["end"]) - float(item["start"]))
                    take = takes.get(item.get("take_id"))
                    source = _media_inside_project(project_dir, take["path"]) if take else None
                    seg = scratch / f"{index:04d}.mp4"
                    vf = []
                    if source is not None and source.is_file():
                        trim_in = max(0.0, float(item.get("trim_in") or take.get("trim_in") or 0))
                        vf.append(f"trim=start={trim_in:.6f}")
                        if item.get("reverse"):
                            vf.append("reverse")
                        speed = max(.1, min(4.0, float(item.get("speed") or 1.0)))
                        vf.append(f"setpts=(PTS-STARTPTS)/{speed:.6f}")
                        vf.extend([
                            f"scale={width}:{height}:force_original_aspect_ratio={'increase' if item.get('fit','cover') == 'cover' else 'decrease'}",
                            f"crop={width}:{height}" if item.get("fit", "cover") == "cover" else f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
                            "setsar=1", "fps=24", "format=yuv420p",
                            f"tpad=stop_mode=clone:stop_duration={target + 1:.6f}",
                            f"trim=duration={target:.6f}", "setpts=PTS-STARTPTS",
                        ])
                        if item.get("transition") == "fade":
                            fade = min(.35, target / 4)
                            vf.extend([f"fade=t=in:st=0:d={fade}", f"fade=t=out:st={target-fade:.6f}:d={fade}"])
                        command = ["ffmpeg", "-y", "-i", str(source), "-an",
                                   "-vf", ",".join(vf), "-t", f"{target:.6f}", "-r", "24",
                                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", str(seg)]
                    else:
                        label = (item.get("shot_id") or f"SHOT {index+1}").replace("'", "")
                        command = ["ffmpeg", "-y", "-f", "lavfi", "-i",
                                   f"color=c=0x090b10:s={width}x{height}:r=24:d={target}", "-vf",
                                   f"drawtext=text='{label}':fontcolor=white@0.5:fontsize=28:x=(w-text_w)/2:y=(h-text_h)/2",
                                   "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", str(seg)]
                    _run(command, log)
                    segment_paths.append(seg)

                concat_file = scratch / "concat.txt"
                concat_file.write_text("".join("file '" + str(p).replace("'", "'\\''") + "'\n" for p in segment_paths))
                joined = scratch / "joined.mp4"
                _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
                      "-c", "copy", str(joined)], log)

                vf = [f"tpad=stop_mode=clone:stop_duration={duration + 1:.6f}", f"trim=duration={duration:.6f}"]
                for title in (project.get("timeline") or {}).get("titles", []):
                    text = str(title.get("text", "")).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
                    start, end = float(title.get("start", 0)), float(title.get("end", 3))
                    size = int(title.get("size", 52))
                    pos = title.get("position", "lower")
                    y = "h*0.78" if pos == "lower" else ("h*0.16" if pos == "upper" else "(h-text_h)/2")
                    vf.append("drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                              f"text='{text}':fontcolor=white:fontsize={size}:borderw=2:bordercolor=black@0.65:"
                              f"x=(w-text_w)/2:y={y}:enable='between(t,{start:.3f},{end:.3f})'")
                _run(["ffmpeg", "-y", "-i", str(joined), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                      "-vf", ",".join(vf), "-t", f"{duration:.6f}", "-c:v", "libx264", "-preset", "slow",
                      "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k",
                      "-movflags", "+faststart", str(output)], log)

                verify = subprocess.check_output([
                    "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height,r_frame_rate",
                    "-of", "json", str(output)
                ], text=True)
                log.write("\nVERIFY\n" + verify + "\n")

    except BaseException:
        # Do not leave a partially written MP4 masquerading as a finished render.
        with contextlib.suppress(FileNotFoundError):
            output.unlink()
        raise

    manifest = {
        "rendered_at": time.time(), "output": str(output.relative_to(project_dir)),
        "preset": preset, "width": width, "height": height, "source_audio": audio_rel,
        "master_duration": duration, "timeline_items": items, "project_revision": project.get("revision", 0),
        "render_log": str(log_path.relative_to(project_dir)),
    }
    manifest_path = renders / f"{output.stem}-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    shot_list = renders / f"{output.stem}-shot-list.json"
    shot_list.write_text(json.dumps(project.get("shots", []), indent=2) + "\n")
    return {"path": str(output.relative_to(project_dir)), "manifest": str(manifest_path.relative_to(project_dir)),
            "shot_list": str(shot_list.relative_to(project_dir)), "log": str(log_path.relative_to(project_dir)),
            "width": width, "height": height, "duration": duration}
