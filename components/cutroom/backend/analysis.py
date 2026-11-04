#!/usr/bin/env python3
"""Deterministic song analysis and cut planning for Music Video Studio."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import numpy as np


def probe(path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,format_name:stream=codec_name,sample_rate,channels",
        "-select_streams", "a:0", "-of", "json", str(path),
    ]
    data = json.loads(subprocess.check_output(cmd, timeout=30))
    duration = float((data.get("format") or {}).get("duration") or 0)
    stream = (data.get("streams") or [{}])[0]
    return {
        "duration": round(duration, 6),
        "format": (data.get("format") or {}).get("format_name", "unknown"),
        "codec": stream.get("codec_name", "unknown"),
        "sample_rate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
    }


def _decode(path: Path, rate: int = 22050) -> np.ndarray:
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
        "-ar", str(rate), "-f", "f32le", "pipe:1",
    ]
    raw = subprocess.check_output(cmd, timeout=600)
    return np.frombuffer(raw, dtype="<f4").copy()


def _normalise(values: np.ndarray) -> np.ndarray:
    if not len(values):
        return values
    lo, hi = np.percentile(values, [5, 95])
    if hi <= lo + 1e-9:
        return np.zeros_like(values)
    return np.clip((values - lo) / (hi - lo), 0, 1)


def _estimate_bpm(onset: np.ndarray, rate: float) -> float:
    if len(onset) < 8 or np.max(onset) <= 0:
        return 120.0
    x = onset - np.mean(onset)
    corr = np.correlate(x, x, mode="full")[len(x) - 1:]
    min_lag = max(1, int(rate * 60 / 200))
    max_lag = min(len(corr) - 1, int(rate * 60 / 65))
    if max_lag <= min_lag:
        return 120.0
    lag = int(np.argmax(corr[min_lag:max_lag + 1]) + min_lag)
    bpm = 60.0 * rate / lag
    while bpm < 80:
        bpm *= 2
    while bpm > 180:
        bpm /= 2
    return round(float(bpm), 2)


def _sections(duration: float, energy: np.ndarray, seconds_per_bin: float) -> list[dict]:
    if duration <= 0:
        return []
    # Structure inference is intentionally conservative: broad song regions,
    # with energy-derived names only when the signal warrants it.
    bounds = [0.0]
    for f in (0.12, 0.32, 0.55, 0.78, 0.92):
        t = round(duration * f, 3)
        if t - bounds[-1] >= 8 and duration - t >= 5:
            bounds.append(t)
    bounds.append(duration)
    names = ["intro", "verse", "chorus", "verse / build", "chorus / peak", "outro"]
    out = []
    for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
        ia = max(0, int(a / seconds_per_bin))
        ib = min(len(energy), max(ia + 1, int(b / seconds_per_bin)))
        e = float(np.mean(energy[ia:ib])) if ib > ia else 0.0
        name = names[min(i, len(names) - 1)]
        if i not in (0, len(bounds) - 2):
            if e > .72:
                name = "chorus / peak"
            elif e < .28:
                name = "breakdown"
        out.append({"id": f"section-{i+1:02d}", "name": name,
                    "start": round(a, 3), "end": round(b, 3), "energy": round(e, 3)})
    return out


def _plan_shots(duration: float, bpm: float, energy: np.ndarray, onset_times: np.ndarray,
                sections: list[dict]) -> list[dict]:
    beat = 60.0 / max(1.0, bpm)
    bar = beat * 4
    boundaries = [0.0]
    t = 0.0
    while t < duration - 1.5:
        idx = min(len(energy) - 1, max(0, int((t / max(duration, .001)) * len(energy))))
        e = float(energy[idx]) if len(energy) else .5
        bars = 1 if e > .76 else (2 if e < .24 else 1)
        target = max(2.0, min(6.0, bar * bars))
        raw = t + target
        # Prefer an onset near the target, otherwise a beat-aligned cut.
        candidates = onset_times[(onset_times >= raw - .55) & (onset_times <= raw + .55)]
        nxt = float(candidates[np.argmin(np.abs(candidates - raw))]) if len(candidates) else round(raw / beat) * beat
        nxt = max(t + 2.0, min(t + 6.2, nxt, duration))
        if duration - nxt < 1.4:
            nxt = duration
        boundaries.append(round(nxt, 3))
        t = nxt
        if t >= duration - .01:
            break
    if boundaries[-1] < duration:
        boundaries[-1] = round(duration, 3)

    framings = ["wide", "medium", "close", "detail", "medium", "insert"]
    cameras = ["slow push-in", "locked frame", "gentle orbit", "handheld drift", "lateral track", "macro glide"]
    shots = []
    for i, (a, b) in enumerate(zip(boundaries, boundaries[1:])):
        mid = (a + b) / 2
        section = next((s for s in sections if s["start"] <= mid < s["end"]), sections[-1] if sections else {})
        shots.append({
            "id": f"shot-{i+1:03d}", "number": i + 1,
            "start": round(a, 3), "end": round(b, 3), "duration": round(b - a, 3),
            "section": section.get("name", "sequence"),
            "framing": framings[i % len(framings)], "camera": cameras[i % len(cameras)],
            "mode": "t2v", "backend": "wan-2.2-rapid", "prompt": "", "reference_asset_id": None,
            "preset": "compatibility", "frames": valid_frames(b - a), "seed": 420251006,
            "takes": [], "selected_take_id": None, "transition": "cut",
        })
    return shots


def valid_frames(seconds: float) -> int:
    values = [17, 33, 49, 65, 81]
    needed = seconds * 16 + 1
    return next((value for value in values if value >= needed), values[-1])


def analyse(path: Path) -> dict:
    meta = probe(path)
    y = _decode(path)
    sr = 22050
    if not len(y):
        raise ValueError("audio decoder returned no samples")

    hop = 512
    frame = 2048
    padded = np.pad(y, (0, frame))
    count = max(1, 1 + (len(y) - 1) // hop)
    rms = np.empty(count, dtype=np.float32)
    flux = np.zeros(count, dtype=np.float32)
    previous = None
    window = np.hanning(frame).astype(np.float32)
    for i in range(count):
        chunk = padded[i * hop:i * hop + frame]
        rms[i] = math.sqrt(float(np.mean(chunk * chunk)) + 1e-12)
        spectrum = np.abs(np.fft.rfft(chunk * window))
        if previous is not None:
            flux[i] = float(np.maximum(0, spectrum - previous).sum())
        previous = spectrum
    energy = _normalise(rms)
    onset = _normalise(flux)
    frame_rate = sr / hop
    bpm = _estimate_bpm(onset, frame_rate)
    duration = meta["duration"] or len(y) / sr

    threshold = float(np.percentile(onset, 82))
    peak_idx = np.where((onset > threshold) & (onset >= np.roll(onset, 1)) & (onset >= np.roll(onset, -1)))[0]
    onset_times = peak_idx.astype(np.float64) * hop / sr

    beat = 60.0 / bpm
    beats = np.arange(0, duration + beat / 2, beat)
    bars = beats[::4]
    seconds_per_bin = hop / sr
    sections = _sections(duration, energy, seconds_per_bin)
    shots = _plan_shots(duration, bpm, energy, onset_times, sections)

    # 1,600 min/max waveform buckets are compact enough for instant canvas drawing.
    buckets = 1600
    step = max(1, len(y) // buckets)
    wave = []
    for i in range(0, len(y), step):
        chunk = y[i:i + step]
        wave.append([round(float(chunk.min()), 4), round(float(chunk.max()), 4)])
        if len(wave) >= buckets:
            break
    energy_points = [[round(i * seconds_per_bin, 3), round(float(v), 3)]
                     for i, v in enumerate(energy[::max(1, int(frame_rate / 4))])]
    return {
        "audio": meta, "bpm": bpm, "beat_interval": round(beat, 6),
        "beats": [round(float(v), 3) for v in beats],
        "bars": [round(float(v), 3) for v in bars],
        "onsets": [round(float(v), 3) for v in onset_times[:5000]],
        "waveform": wave, "energy": energy_points,
        "sections": sections, "shots": shots,
        "method": "ffmpeg mono decode + RMS energy + spectral-flux autocorrelation",
    }
