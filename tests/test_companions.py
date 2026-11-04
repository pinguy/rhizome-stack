"""Portable Cutroom and Lifeboat source boundaries."""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    cutroom = ROOT / "components/cutroom"
    lifeboat = ROOT / "components/lifeboat"
    for required in (
        cutroom / "README.md",
        cutroom / "ui/package.json",
        cutroom / "ui/server.py",
        cutroom / "backend/app.py",
        cutroom / "backend/analysis.py",
        cutroom / "backend/renderer.py",
        lifeboat / "README.md",
        lifeboat / "config.example.toml",
        lifeboat / "src/rhizome_lifeboat/checkpoint.py",
        lifeboat / "src/rhizome_lifeboat/recovery.py",
        lifeboat / "src/rhizome_lifeboat/retention.py",
    ):
        check(required.is_file(), f"missing companion source: {required.relative_to(ROOT)}")

    package = json.loads((cutroom / "ui/package.json").read_text())
    check(package["name"] == "cutroom-ui", "unexpected Cutroom package")
    check(package["version"] == "0.2.0-alpha.2", "unexpected Cutroom source revision")
    for unit, port in (("cutroom-backend.service", "8843"), ("cutroom-ui.service", "8842")):
        source = (ROOT / "systemd" / unit).read_text()
        check(f"127.0.0.1" in source and port in source, f"{unit} is not loopback-scoped")

    shipped = "\n".join(
        path.read_text(errors="replace")
        for component in (cutroom, lifeboat)
        for path in component.rglob("*")
        if (path.is_file()
            and "__pycache__" not in path.parts
            and "node_modules" not in path.parts
            and path.suffix != ".pyc"
            and path.stat().st_size < 5 * 1024 * 1024)
    ).casefold()
    for forbidden in (
        "/home/" + "ping" + "uy",
        "an" + "toni nor" + "man",
        "gpu-" + "105de105",
        "gpu-" + "00e5dba8",
    ):
        check(forbidden not in shipped, f"reference-machine value leaked: {forbidden}")

    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(lifeboat / "tests")],
        cwd=ROOT,
        env={**__import__("os").environ, "PYTHONPATH": str(lifeboat / "src")},
        capture_output=True,
        text=True,
        timeout=180,
    )
    check(result.returncode == 0, result.stdout + result.stderr)
    print("PASS Cutroom and Lifeboat portable source boundaries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
