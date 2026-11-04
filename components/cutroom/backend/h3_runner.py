#!/usr/bin/env python3
"""Isolated MiniMax H3 NF4 inference worker for the portable Video Desk."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import torch
from PIL import Image

from diffsynth.pipelines.minimax_h3_audio_video import MiniMaxH3Pipeline, ModelConfig
from diffsynth.utils.data.audio_video import write_video_audio


MODEL_FILES = {
    "minimax-h3-fl2va-pruned-nf4.safetensors": 10_483_868_433,
    "minimax-h3-text-encoder-nf4.safetensors": 15_324_775_807,
    "video_vae_nf4.safetensors": 1_613_201_536,
    "audio_vae_nf4.safetensors": 284_004_112,
}


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: h3_runner.py REQUEST.json OUTPUT.mp4")
    request_path = Path(sys.argv[1]).resolve(strict=True)
    output_path = Path(sys.argv[2]).resolve(strict=False)
    request = json.loads(request_path.read_text())
    model_root = Path(request["model_root"]).expanduser().resolve(strict=True)
    processor = model_root / "FL2VA/processor"
    for filename, expected_size in MODEL_FILES.items():
        path = model_root / filename
        if not path.is_file():
            raise FileNotFoundError(f"required MiniMax H3 model is missing: {path}")
        if path.with_name(path.name + ".aria2").exists():
            raise RuntimeError(f"required MiniMax H3 model is still downloading: {path}")
        if path.stat().st_size != expected_size:
            raise RuntimeError(f"required MiniMax H3 model has the wrong size: {path}")
    if not processor.is_dir():
        raise FileNotFoundError(f"MiniMax H3 processor is missing: {processor}")

    width = int(request["width"])
    height = int(request["height"])
    frames = int(request["frames"])
    steps = int(request["steps"])
    if width % 32 or height % 32:
        raise ValueError("MiniMax H3 width and height must be multiples of 32")
    if frames < 5 or (frames - 5) % 17:
        raise ValueError("MiniMax H3 frames must use the 17n+5 sequence")
    if not 4 <= steps <= 50:
        raise ValueError("MiniMax H3 steps must be between 4 and 50")

    vram_config = {
        "offload_dtype": "disk", "offload_device": "disk",
        "onload_dtype": "disk", "onload_device": "disk",
        "preparing_dtype": torch.bfloat16, "preparing_device": "cuda",
        "computation_dtype": torch.bfloat16, "computation_device": "cuda",
    }
    pipe = MiniMaxH3Pipeline.from_pretrained(
        torch_dtype=torch.bfloat16,
        device="cuda",
        model_configs=[
            ModelConfig(path=str(model_root / filename), **vram_config)
            for filename in MODEL_FILES
        ],
        processor_config=ModelConfig(path=str(processor)),
        vram_limit=max(1.0, torch.cuda.mem_get_info("cuda")[1] / 1024**3 - 2.0),
        redirect_common_files=False,
    )

    keyframes = None
    keyframe_indices = None
    reference_path = request.get("reference_path")
    if reference_path:
        with Image.open(reference_path) as image:
            keyframes = [image.convert("RGB").copy()]
        keyframe_indices = [0]

    video, audio = pipe(
        prompt=str(request["prompt"]), height=height, width=width,
        num_frames=frames, num_inference_steps=steps, seed=int(request["seed"]),
        cfg_scale=1.0, flow_shift=12.0, audio_flow_shift=3.0,
        tiled=True, tile_size=256, tile_overlap=64,
        keyframes=keyframes, keyframe_indices=keyframe_indices,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial = output_path.with_suffix(".partial.mp4")
    write_video_audio(video=video, audio=audio, output_path=str(partial),
                      fps=24, audio_sample_rate=32000)
    os.replace(partial, output_path)
    print(json.dumps({"status": "success", "output": str(output_path), "frames": len(video)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
