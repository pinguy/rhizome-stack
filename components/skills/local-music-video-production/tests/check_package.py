#!/usr/bin/env python3
"""Read-only sanity checks for the consolidated skill package."""
from pathlib import Path
import hashlib
import subprocess

root = Path(__file__).resolve().parents[1]
required = [
    "SKILL.md", "README.md", "CHANGELOG.md",
    "references/local-tool-map.md", "references/bliss-method.md",
    "templates/storyboard-template.md", "templates/production-manifest.md",
    "scripts/h3_lanczos_1080p.sh",
]
for name in required:
    path = root / name
    assert path.is_file() and path.stat().st_size > 0, f"Missing/empty {name}"

skill = (root / "SKILL.md").read_text()
mapfile = (root / "references/local-tool-map.md").read_text()
board = (root / "templates/storyboard-template.md").read_text()
manifest = (root / "templates/production-manifest.md").read_text()
checks = {
    "single authoritative root skill": len(list(root.rglob("SKILL.md"))) == 1,
    "H3 default engine": "**MiniMax H3" in skill,
    "4-50 supported steps": "4–50" in skill and "4–50" in manifest,
    "20-step documented default": "20-step default" in skill,
    "8-step fast mode not default": "8-step speed preset only when deliberately chosen" in skill,
    "concept gate": "STORYBOARD_APPROVED" in skill and "STORYBOARD_APPROVED" in board,
    "timed board gate": "TIMED_BOARD_LOCKED" in skill and "TIMED_BOARD_LOCKED" in board,
    "separate integration gate": "CUTROOM_INTEGRATION_PENDING" in skill and "CUTROOM_INTEGRATION_PENDING" in manifest,
    "upscale gate": "UPSCALE_VERIFIED" in skill and "UPSCALE_VERIFIED" in manifest,
    "correct service ports": all(x in mapfile for x in [":8830", ":8840", ":8841", ":8842", ":8843"]),
    "separate upscaler environments": "VIDEO_UPSCALER_NCNN_BIN" in mapfile and "REALESRGAN_BIN" in mapfile,
    "source soundtrack preserved": "locked song" in skill.lower() and "MUTE" in manifest,
}
for label, passed in checks.items():
    print(("PASS" if passed else "FAIL"), label)
    assert passed, label
subprocess.run(["bash", "-n", str(root / "scripts/h3_lanczos_1080p.sh")], check=True)
print("PASS shell syntax")
print("Upscale script sha256:", hashlib.sha256((root / "scripts/h3_lanczos_1080p.sh").read_bytes()).hexdigest())
