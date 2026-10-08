#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rhizome-creative-test-") as temporary:
        os.environ["RHIZOME_STACK_ROOT"] = temporary
        app_dir = ROOT / "components/creative/qwen-image-desk"
        import sys
        sys.path.insert(0, str(app_dir))
        qwen = load(app_dir / "app.py", "qwen_image_desk_test")
        presets = load(app_dir / "image_presets.py", "qwen_image_presets_test")
        graph = qwen.qwen_graph("test prompt", "", 42, 1024, 576, "test/output")
        check(graph["1"]["inputs"]["unet_name"] == "qwen-image-2.1-UC-Q8_0.gguf", "wrong Qwen diffusion model")
        check(graph["4"]["class_type"] == "TextEncodeQwenImage21", "wrong Qwen encoder node")
        check(graph["6"]["inputs"]["steps"] == 25 and graph["6"]["inputs"]["cfg"] == 1.0,
              "Qwen sampler contract changed")
        edit_graph = qwen.qwen_graph("change the chair to yellow", "", 43, 768, 448,
                                     "test/edit", "reference.png")
        check(edit_graph["9"]["class_type"] == "LoadImage", "Qwen edit graph does not load the reference")
        check(edit_graph["4"]["inputs"]["images.image_1"] == ["10", 0],
              "Qwen edit graph does not condition the encoder")
        check(edit_graph["6"]["inputs"]["latent_image"] == ["4", 2] and "5" not in edit_graph,
              "Qwen edit graph silently retained the text-only latent")
        check(presets.resolve_image_dimensions("landscape-standard") == (1024, 576), "preset mismatch")
        try:
            presets.validate_image_dimensions(1025, 576)
            raise AssertionError("unaligned dimensions were accepted")
        except ValueError:
            pass
        reference_root = Path(temporary) / "references"
        qwen.REFERENCE_DIR = reference_root
        image = io.BytesIO()
        Image.new("RGBA", (96, 80), (20, 40, 220, 128)).save(image, "PNG")
        saved = qwen.save_reference(image.getvalue(), "synthetic-reference.png")
        check(saved["width"] == 96 and saved["height"] == 80, "reference dimensions were not preserved")
        loaded = qwen.reference_image(saved["id"])
        check(Path(loaded["absolute_path"]).is_file(), "normalised reference was not persisted")
        with Image.open(loaded["absolute_path"]) as normalised:
            check(normalised.mode == "RGB", "reference alpha was not normalised")
    print("PASS standalone Qwen graph and dimension boundaries")

    creative = ROOT / "components/creative"
    source = "\n".join(path.read_text(errors="replace") for path in creative.rglob("*") if path.is_file())
    check("pkill" not in source, "creative source contains broad pkill")
    check("/home/ComfyUI" not in source, "creative source contains reference-machine path")
    check("music_video_studio" not in source, "creative source still depends on the excluded studio")
    check("cutroom" not in source.casefold(), "Cutroom source leaked into creative package")
    print("PASS creative isolation and exact-process safety")

    manifest = json.loads((ROOT / "manifests/creative-models.json").read_text())
    destinations = set()
    for item in manifest["models"]:
        check(len(item["revision"]) == 40, f"unpinned revision: {item['repository']}")
        check(len(item["sha256"]) == 64, f"bad digest: {item['destination']}")
        check(item["destination"] not in destinations, f"duplicate destination: {item['destination']}")
        destinations.add(item["destination"])
    check(len(destinations) == 6, "creative model set is incomplete")
    print("PASS creative model revision and checksum manifest")

    for name, port in (("qwen-image-desk.service", "8841"), ("minimax-music-api.service", "8830")):
        unit = (ROOT / "systemd" / name).read_text()
        check("Environment=APP_HOST=127.0.0.1" in unit, f"{name} is not loopback-only")
        check(f"Environment=APP_PORT={port}" in unit, f"{name} port mismatch")
    print("PASS creative systemd loopback boundaries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
