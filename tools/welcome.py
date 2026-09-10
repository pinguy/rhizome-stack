#!/usr/bin/env python3
"""Resumable first-run wizard for a new, private Rhizome Stack installation."""

from __future__ import annotations

import getpass
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "rhizome-stack"
ENV_PATH = CONFIG_DIR / "stack.env"
OPENCLAW_CONFIG = Path(os.environ.get("OPENCLAW_CONFIG_PATH", HOME / ".openclaw/openclaw.json"))
STATE_PATH = CONFIG_DIR / "welcome-state.json"

PROVIDERS = {
    "1": ("openai", "OpenAI", "OPENAI_API_KEY", "https://api.openai.com/v1"),
    "2": ("anthropic", "Anthropic", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1"),
    "3": ("nvidia", "NVIDIA NIM", "NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1"),
    "4": ("ollama", "Ollama / local model", "", "http://127.0.0.1:11434"),
    "5": ("compatible", "Other OpenAI-compatible endpoint", "CUSTOM_OPENAI_API_KEY", ""),
    "6": ("gguf", "GGUF / local model (advanced)", "", "http://127.0.0.1:11434"),
}


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def yes(prompt: str, default: bool = False) -> bool:
    marker = "Y/n" if default else "y/N"
    answer = input(f"{prompt} [{marker}]: ").strip().lower()
    return default if not answer else answer in {"y", "yes"}


def read_env() -> tuple[list[str], dict[str, str]]:
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    values = {}
    for line in lines:
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            parsed = shlex.split(value)
            values[key] = parsed[0] if parsed else ""
    return lines, values


def set_env(updates: dict[str, str]) -> None:
    if any(any(char in value for char in ("\n", "\r", "\0", "'")) for value in updates.values()):
        raise ValueError("environment values must be single-line text without apostrophes")
    updates = {key: shlex.quote(value) for key, value in updates.items()}
    lines, _ = read_env()
    seen: set[str] = set()
    rendered = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in updates:
            rendered.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            rendered.append(line)
    for key, value in updates.items():
        if key not in seen:
            rendered.append(f"{key}={value}")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary = ENV_PATH.with_suffix(".tmp")
    temporary.write_text("\n".join(rendered) + "\n")
    temporary.chmod(0o600)
    temporary.replace(ENV_PATH)


def request_json(url: str, headers: dict[str, str]) -> object:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def verify(provider: str, base_url: str, key: str, model: str) -> tuple[bool, str]:
    try:
        if provider in {"ollama", "gguf"}:
            payload = request_json(base_url.rstrip("/") + "/api/tags", {})
            installed = {row.get("name") or row.get("model") for row in payload.get("models", []) if isinstance(row, dict)} if isinstance(payload, dict) else set()
            choices = {model, model + ":latest"} if ":" not in model else {model}
            found = bool(installed & choices)
            return found, f"selected Ollama model {model!r} {'is installed' if found else 'was not found'}"
        headers = {"Authorization": f"Bearer {key}"}
        endpoint = base_url.rstrip("/") + "/models"
        if provider == "anthropic":
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        payload = request_json(endpoint, headers)
        available = {row.get("id") for row in payload.get("data", []) if isinstance(row, dict)} if isinstance(payload, dict) else set()
        found = model in available
        return found, f"selected model {model!r} {'is in the provider catalogue' if found else 'was not found in the provider catalogue'}"
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        # Exception strings may echo a URL containing user-supplied credentials.
        return False, f"verification failed: {type(exc).__name__}; check the endpoint, key and model ID"


def update_openclaw(provider: str, model: str, base_url: str, env_name: str) -> None:
    config = json.loads(OPENCLAW_CONFIG.read_text())
    route_provider = "ollama" if provider == "gguf" else provider
    primary = f"{route_provider}/{model}"
    if provider == "compatible":
        provider_id = ask("Short provider name", "custom")
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", provider_id):
            raise ValueError("provider name must contain lowercase letters, digits, underscores or hyphens")
        primary = f"{provider_id}/{model}"
        config.setdefault("models", {}).setdefault("providers", {})[provider_id] = {
            "baseUrl": base_url,
            "api": "openai-completions",
            "apiKey": {"source": "env", "provider": "default", "id": env_name},
            "models": [{"id": model, "name": model}],
        }
    elif provider == "nvidia":
        config.setdefault("models", {}).setdefault("providers", {})["nvidia"] = {
            "baseUrl": base_url, "api": "openai-completions",
            "apiKey": {"source": "env", "provider": "default", "id": env_name},
            "models": [{"id": model, "name": model}],
        }
    elif provider in {"ollama", "gguf"}:
        ollama = config.setdefault("models", {}).setdefault("providers", {}).setdefault("ollama", {})
        ollama.update({"baseUrl": base_url, "api": "ollama", "apiKey": "ollama-local"})
        models = ollama.setdefault("models", [])
        if not any(row.get("id") == model for row in models):
            models.append({"id": model, "name": model})
        set_env({"OLLAMA_BASE_URL": base_url, "OLLAMA_BASE_URLS": base_url, "DEFAULT_OLLAMA_MODEL": model})
    config.setdefault("agents", {}).setdefault("defaults", {})["model"] = {"primary": primary}
    backup = OPENCLAW_CONFIG.with_name("openclaw.json.before-welcome")
    if not backup.exists():
        shutil.copy2(OPENCLAW_CONFIG, backup)
    temporary = OPENCLAW_CONFIG.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(OPENCLAW_CONFIG)


def configure_gguf(base_url: str) -> tuple[str, bool, str]:
    print("\nGGUF is the advanced local path. The file stays where you put it; it is never packaged.")
    path = Path(ask("Path to the .gguf file")).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".gguf":
        raise ValueError("that is not a readable .gguf file")
    model = ask("Local model name", path.stem.lower().replace(" ", "-"))
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]*", model):
        raise ValueError("invalid local model name")
    context = ask("Context window", "32768")
    if int(context) <= 0:
        raise ValueError("context window must be positive")
    state_dir = CONFIG_DIR / "generated"
    state_dir.mkdir(parents=True, exist_ok=True)
    modelfile = state_dir / f"Modelfile.{model.replace('/', '-') }"
    if any(char in str(path) for char in ('"', "\n", "\r")):
        raise ValueError("GGUF path cannot contain quotes or newlines")
    modelfile.write_text(f'FROM "{path}"\nPARAMETER num_ctx {int(context)}\n')
    subprocess.run(["ollama", "create", model, "-f", str(modelfile)], env={**os.environ, "OLLAMA_HOST": base_url}, check=True)
    ok, message = verify("gguf", base_url, "", model)
    return model, ok, message


def main() -> int:
    print("\nWelcome to Rhizome Stack")
    print("First, choose an intelligence backend. Configure at least one working model now;")
    print("once it responds, Rhizome can help with the remaining setup.\n")
    for key, (_, label, _, _) in PROVIDERS.items():
        print(f"  {key}. {label}")
    choice = ask("Choice", "4")
    if choice not in PROVIDERS:
        print("Unknown choice", file=sys.stderr)
        return 2
    provider, label, env_name, base_url = PROVIDERS[choice]
    if provider in {"ollama", "gguf"}:
        base_url = os.environ.get("OLLAMA_BASE_URL", base_url)
    key = ""
    if provider == "openai":
        print("Create a project API key at https://platform.openai.com/api-keys . API usage is billed separately from ChatGPT.")
    elif provider == "anthropic":
        print("Create an API key in the Anthropic Console: https://console.anthropic.com/settings/keys")
    elif provider == "nvidia":
        print("Create an NVIDIA API key at https://build.nvidia.com/settings/api-keys")
    elif provider == "compatible":
        base_url = ask("Endpoint base URL, normally ending in /v1")
    if env_name:
        key = getpass.getpass(f"{label} API key (hidden; stored locally only): ").strip()
        if not key:
            print("No key supplied; provider setup stopped without changing configuration.", file=sys.stderr)
            return 2
    if provider == "gguf":
        model, ok, message = configure_gguf(base_url)
    else:
        if provider == "ollama":
            print("Ollama must be running with at least one model. Try: ollama pull qwen3:8b")
        model = ask("Model ID", {"openai": "gpt-5.6", "anthropic": "claude-sonnet-4-6", "nvidia": "nvidia/nemotron-3-super-120b-a12b", "ollama": "qwen3:8b"}.get(provider, ""))
        ok, message = verify(provider, base_url, key, model)
    print(("PASS " if ok else "FAIL ") + message)
    if not ok:
        print("The backend was not saved as the default. Fix connectivity/key/model and run this wizard again.")
        return 3
    if env_name:
        set_env({env_name: key})
    update_openclaw(provider, model, base_url, env_name)
    print("Catalogue check passed. A real chat response still needs checking after the services start.")
    choices = {
        "voice": yes("Add local speech-to-text and text-to-speech?"),
        "memory": yes("Add private semantic memory and document indexing?", True),
        "jupyter": yes("Add the optional local Jupyter code environment?"),
        "skills": yes("Add the core reliability and handover skills?", True),
    }
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"schema": 1, "backend": provider, "model": model, "verified": True, "verification": "model-catalogue", "inference_verified": False, "optional": choices}, indent=2) + "\n")
    STATE_PATH.chmod(0o600)
    selected = [name for name, enabled in choices.items() if enabled]
    if selected:
        print("\nSelected optional components: " + ", ".join(selected))
        release_root = Path(__file__).resolve().parents[1]
        installer = release_root / "tools/install.py"
        if (release_root / "manifests/versions.json").exists() and yes("Install the selected components now?", True):
            target = "wsl" if os.environ.get("WSL_INTEROP") or os.environ.get("WSL_DISTRO_NAME") else "linux"
            command = [sys.executable, str(installer), "--target", target]
            for name, enabled in choices.items():
                if enabled:
                    command.append(f"--with-{name}")
            subprocess.run(command, check=True)
        else:
            print("Run the installer again from the unpacked release with the matching --with-* flags when ready.")
    if choices["memory"] and yes("Import your own documents or conversation export now?"):
        source = ask("File or directory to import")
        kind = ask("Type: auto, documents, chatgpt, claude or rhizomeml", "auto")
        subprocess.run([sys.executable, str(Path(__file__).with_name("import_owner_data.py")), "--type", kind, source], check=True)
    print("\nBackend verified and first-run choices saved. Run 'rhizome-stack doctor', then 'rhizome-stack start'.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, EOFError, subprocess.CalledProcessError) as exc:
        print(f"setup failed: {type(exc).__name__}; check your inputs and retry", file=sys.stderr)
        raise SystemExit(2)
