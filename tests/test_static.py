#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    for path in sorted((ROOT / "manifests").glob("*.json")):
        json.loads(path.read_text())
        print(f"PASS JSON {path.relative_to(ROOT)}")
    json.loads((ROOT / "config/openclaw.template.json").read_text())
    for path in sorted(ROOT.rglob("*.py")):
        subprocess.run([sys.executable, "-m", "py_compile", str(path)], check=True)
    print("PASS Python syntax")
    for path in sorted(ROOT.rglob("*.sh")) + [ROOT / "install-linux.sh", ROOT / "install-wsl.sh", ROOT / "uninstall.sh", ROOT / "bin/rhizome-stack"]:
        subprocess.run(["bash", "-n", str(path)], check=True)
    print("PASS shell syntax")
    spec = importlib.util.spec_from_file_location("rhizome_installer", ROOT / "tools/install.py")
    installer = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(installer)
    check(installer.distro_family({"ID": "cachyos"}) == "arch", "CachyOS mapping failed")
    check(installer.distro_family({"ID": "ubuntu", "ID_LIKE": "debian"}) == "debian", "WSL Ubuntu mapping failed")
    print("PASS target distro mappings")
    with tempfile.TemporaryDirectory(prefix="rhizome-import-") as temporary:
        temp = Path(temporary)
        source = temp / "chatgpt.json"
        source.write_text(json.dumps([
            {"title": "Example", "messages": [
                {"role": "user", "content": "A private test question"},
                {"role": "assistant", "content": "A private test answer"},
            ]}
        ]))
        env = os.environ.copy()
        env["HOME"] = str(temp / "owner-home")
        command = [sys.executable, str(ROOT / "tools/import_owner_data.py"), "--type", "chatgpt", str(source)]
        first = subprocess.run(command, env=env, text=True, capture_output=True)
        second = subprocess.run(command, env=env, text=True, capture_output=True)
        check(first.returncode == 0 and "imported 2 new" in first.stdout, first.stderr)
        check(second.returncode == 0 and "imported 0 new" in second.stdout, second.stderr)
        records = list((Path(env["HOME"]) / ".local/share/rhizome-stack/memory/owner-imports").glob("*.json"))
        check(len(records) == 2, "conversation import was not idempotent")
    print("PASS owner import isolation and idempotence")
    class ModelHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = json.dumps({"models": [{"name": "test-local"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="rhizome-welcome-") as temporary:
            home = Path(temporary)
            (home / ".openclaw").mkdir()
            config = (ROOT / "config/openclaw.template.json").read_text()
            for before, after in {
                "${STACK_ROOT}": str(home / ".local/share/rhizome-stack"),
                "${DEFAULT_OLLAMA_MODEL}": "test-local",
                "${OPENCLAW_GATEWAY_TOKEN}": "generated-test-token",
            }.items():
                config = config.replace(before, after)
            (home / ".openclaw/openclaw.json").write_text(config)
            env = os.environ.copy()
            env.update({
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "OLLAMA_BASE_URL": f"http://127.0.0.1:{server.server_port}",
            })
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/welcome.py")], env=env,
                input="4\ntest-local\nn\nn\nn\nn\n", text=True, capture_output=True,
            )
            check(result.returncode == 0, result.stdout + result.stderr)
            state = json.loads((home / ".config/rhizome-stack/welcome-state.json").read_text())
            check(state["verified"] is True and state["model"] == "test-local", "welcome state is wrong")
    finally:
        server.shutdown()
        server.server_close()
    print("PASS first-run local provider verification")
    for path in sorted((ROOT / "systemd").glob("*")):
        text = path.read_text()
        check("/home/" not in text, f"hard-coded home in {path}")
        check("[Unit]" in text, f"missing Unit section in {path}")
    print("PASS systemd template invariants")
    for manifest_path in sorted((ROOT / "patches").glob("*/*/manifest.json")):
        manifest = json.loads(manifest_path.read_text())
        for item in manifest["files"]:
            check(not Path(item["path"]).is_absolute(), f"absolute patch target in {manifest_path}")
            check(len(item["clean_sha256"]) == 64, f"bad base hash in {manifest_path}")
            if item.get("payload"):
                check((manifest_path.parent / item["payload"]).is_file(), f"missing patch payload in {manifest_path}")
    print("PASS patch manifest invariants")
    openclaw = shutil.which("openclaw")
    if openclaw:
        with tempfile.TemporaryDirectory(prefix="rhizome-config-") as temporary:
            config = Path(temporary) / "openclaw.json"
            rendered = (ROOT / "config/openclaw.template.json").read_text()
            for before, after in {
                "${STACK_ROOT}": str(Path(temporary) / "stack"),
                "${DEFAULT_OLLAMA_MODEL}": "qwen3:8b",
                "${OPENCLAW_GATEWAY_TOKEN}": "test-token-not-secret",
            }.items():
                rendered = rendered.replace(before, after)
            config.write_text(rendered)
            env = os.environ.copy()
            env.update({"OPENCLAW_CONFIG_PATH": str(config), "OPENCLAW_STATE_DIR": str(Path(temporary) / "state")})
            result = subprocess.run([openclaw, "config", "validate", "--json"], env=env, text=True, capture_output=True)
            payload = json.loads(result.stdout)
            check(payload.get("valid") is True, f"OpenClaw template schema invalid: {payload}")
        print("PASS OpenClaw schema validation")
    with tempfile.TemporaryDirectory(prefix="rhizome-stack-test-") as temporary:
        output = Path(temporary) / "release"
        result = subprocess.run([
            sys.executable, str(ROOT / "tools/export_release.py"),
            "--source-root", str(ROOT), "--output", str(output)
        ])
        check(result.returncode == 0, "release export/privacy gate failed")
        subprocess.run([sys.executable, str(output / "tools/verify_release.py"), str(output)], check=True)
    print("PASS isolated release export")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
