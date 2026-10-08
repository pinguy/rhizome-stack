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
sys.path.insert(0, str(ROOT / "tools"))


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
    voice_app = (ROOT / "components/chatterbox_voice_app.py").read_text()
    check('app.run(host="127.0.0.1"' in voice_app, "Voice Lab is not loopback-only")
    register_spec = importlib.util.spec_from_file_location(
        "rhizome_tool_registration", ROOT / "tools/register_openwebui_tools.py")
    register = importlib.util.module_from_spec(register_spec)
    assert register_spec.loader is not None
    register_spec.loader.exec_module(register)
    expected_tools = {
        "rhizome_memory", "rhizome_web_search", "openclaw_agent",
        "minimax_music_3", "qwen_image",
    }
    check(set(register.TOOLS) == expected_tools, "packaged Open WebUI tool IDs changed")
    main_patch = (ROOT / "patches/open-webui/0.11.0/open_webui__main.py.patch").read_text()
    for tool_id in expected_tools - {"openclaw_agent"}:
        check(repr(tool_id) in main_patch, f"default tool ID missing from Open WebUI patch: {tool_id}")
    check("RHIZOME_MEDIA_SYSTEM" in main_patch, "Open WebUI patch lacks local media routing")
    media_doc = (ROOT / "docs/OPENWEBUI_MEDIA.md").read_text()
    for required in (
        "qwen_image.create_image", "minimax_music_3.create_song",
        "unload every Ollama runner", "attach it to the saved message",
        "Open WebUI reloads the local chat model",
    ):
        check(required in media_doc, f"Open WebUI local-media shipping contract is missing: {required}")
    print("PASS Voice Lab and local media registration invariants")
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
