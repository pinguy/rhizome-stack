#!/usr/bin/env python3
"""Install Rhizome Stack without importing state from the reference machine."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
VERSIONS = json.loads((PROJECT / "manifests/versions.json").read_text())
HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "rhizome-stack"
STACK_ROOT = Path(os.environ.get("RHIZOME_STACK_ROOT", HOME / ".local/share/rhizome-stack")).expanduser()
UNIT_DIR = HOME / ".config/systemd/user"
OPENCLAW_HOME = HOME / ".openclaw"


class InstallError(RuntimeError):
    pass


def read_os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path("/etc/os-release")
    if not path.is_file():
        return values
    for raw in path.read_text().splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def is_wsl() -> bool:
    if os.environ.get("WSL_INTEROP") or os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
    except OSError:
        return False


def distro_family(info: dict[str, str]) -> str:
    names = {info.get("ID", ""), *info.get("ID_LIKE", "").split()}
    if names & {"arch", "cachyos", "manjaro"}:
        return "arch"
    if names & {"debian", "ubuntu", "linuxmint", "pop"}:
        return "debian"
    raise InstallError(
        f"unsupported distribution {info.get('PRETTY_NAME', 'unknown')!r}; "
        "supported families are Arch/CachyOS and Debian/Ubuntu"
    )


def command_text(command: list[str]) -> str:
    return " ".join(shlex_quote(part) for part in command)


def shlex_quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


class Runner:
    def __init__(self, dry_run: bool):
        self.dry_run = dry_run

    def run(self, command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str] | None:
        print("+", command_text(command))
        if self.dry_run:
            return None
        return subprocess.run(command, text=True, check=check)

    def write(self, path: Path, content: str, mode: int = 0o644) -> None:
        print(f"+ write {path} mode={mode:o}")
        if self.dry_run:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_text() == content:
            path.chmod(mode)
            return
        if path.exists():
            backup = path.with_name(path.name + ".before-rhizome-stack")
            if not backup.exists():
                shutil.copy2(path, backup)
                print(f"  backup: {backup}")
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content)
        temporary.chmod(mode)
        temporary.replace(path)

    def copy_tree(self, source: Path, destination: Path) -> None:
        print(f"+ seed {destination} from {source}")
        if self.dry_run:
            return
        destination.mkdir(parents=True, exist_ok=True)
        for source_path in sorted(source.rglob("*")):
            if not source_path.is_file():
                continue
            relative = source_path.relative_to(source)
            target = destination / relative
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)

    def deploy_tree(self, source: Path, destination: Path) -> None:
        """Refresh shipped code; seed-only copying is reserved for user content."""
        for source_path in sorted(source.rglob("*")):
            if not source_path.is_file() or "__pycache__" in source_path.parts or source_path.suffix == ".pyc":
                continue
            target = destination / source_path.relative_to(source)
            if target == source_path:
                continue
            self.write(target, source_path.read_text(), source_path.stat().st_mode & 0o777)


def require_preflight(target: str) -> str:
    if platform.machine() not in {"x86_64", "amd64"}:
        raise InstallError("the first release supports x86-64 only")
    wsl = is_wsl()
    if target == "wsl" and not wsl:
        raise InstallError("install-wsl.sh must run inside WSL2")
    if target == "linux" and wsl:
        raise InstallError("WSL detected; use install-wsl.sh")
    if target == "wsl" and Path("/proc/1/comm").read_text().strip() != "systemd":
        raise InstallError(
            "WSL systemd is not enabled. Add '[boot]\\nsystemd=true' to "
            "/etc/wsl.conf, run 'wsl --shutdown' from Windows, then retry."
        )
    return distro_family(read_os_release())


def package_command(family: str, *, voice: bool, jupyter: bool) -> list[str]:
    common_arch = [
        "base-devel", "curl", "git", "jq", "nodejs", "npm", "python", "python-pip",
        "python-virtualenv", "rsync", "sqlite", "xz", "zstd",
    ]
    common_debian = [
        "build-essential", "ca-certificates", "curl", "git", "jq", "nodejs", "npm",
        "python3", "python3-pip", "python3-venv", "rsync", "sqlite3", "xz-utils", "zstd",
    ]
    if voice:
        common_arch.append("ffmpeg")
        common_debian.append("ffmpeg")
    if jupyter:
        common_arch.append("podman")
        common_debian.append("podman")
    if family == "arch":
        return ["sudo", "pacman", "-S", "--needed", *common_arch]
    return ["sudo", "apt-get", "install", "-y", *common_debian]


def render_unit(name: str, stack_root: Path) -> str:
    template = (PROJECT / "systemd" / name).read_text()
    return (template.replace("@@STACK_ROOT@@", str(stack_root)).replace("@@HOME@@", str(HOME))
            .replace(str(HOME / ".config/rhizome-stack/stack.env"), str(CONFIG_DIR / "stack.env")))


def populate_secrets(content: str) -> str:
    values = {
        "OPENCLAW_GATEWAY_TOKEN": secrets.token_urlsafe(36),
        "WEBUI_SECRET_KEY": secrets.token_urlsafe(48),
    }
    lines = []
    for line in content.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in values and not value:
            line = f"{key}={values[key]}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def render_env(existing: str | None = None) -> str:
    if existing:
        return populate_secrets(existing)
    sample = (PROJECT / "config/stack.env.example").read_text()
    sample = sample.replace("%h/.local/share/rhizome-stack", str(STACK_ROOT)).replace("%h", str(HOME))
    return populate_secrets(sample)


def parse_env(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in content.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def render_openclaw(env: dict[str, str]) -> str:
    content = (PROJECT / "config/openclaw.template.json").read_text()
    replacements = {
        "${STACK_ROOT}": str(STACK_ROOT),
        "${DEFAULT_OLLAMA_MODEL}": env.get("DEFAULT_OLLAMA_MODEL", "qwen3:8b"),
        "${OPENCLAW_GATEWAY_TOKEN}": env["OPENCLAW_GATEWAY_TOKEN"],
    }
    for needle, value in replacements.items():
        content = content.replace(needle, value)
    json.loads(content)
    return content


def configure_files(runner: Runner) -> None:
    env_path = CONFIG_DIR / "stack.env"
    existing = env_path.read_text() if env_path.is_file() else None
    env_content = render_env(existing)
    runner.write(env_path, env_content, 0o600)
    openclaw_config = OPENCLAW_HOME / "openclaw.json"
    if not openclaw_config.exists():
        runner.write(openclaw_config, render_openclaw(parse_env(env_content)), 0o600)
    else:
        print(f"+ preserve existing {openclaw_config}")
    runner.copy_tree(PROJECT / "workspace-template", STACK_ROOT / "workspace")
    for directory in ["components", "state/openwebui-data", "state/openwebui-code-work", "shared/openwebui-uploads"]:
        path = STACK_ROOT / directory
        print(f"+ ensure {path}")
        if not runner.dry_run:
            path.mkdir(parents=True, exist_ok=True)
    for unit in sorted((PROJECT / "systemd").glob("*.service")) + sorted((PROJECT / "systemd").glob("*.timer")):
        runner.write(UNIT_DIR / unit.name, render_unit(unit.name, STACK_ROOT))
    runner.write(HOME / ".local/bin/rhizome-stack", (PROJECT / "bin/rhizome-stack").read_text(), 0o755)


def install_node_runtime(runner: Runner) -> Path:
    version = VERSIONS["node_runtime"]
    runtime = STACK_ROOT / f"runtime/node-v{version}-linux-x64"
    node_bin = runtime / "bin"
    if node_bin.joinpath("node").is_file():
        print(f"+ preserve existing Node runtime {runtime}")
        return node_bin
    archive_name = f"node-v{version}-linux-x64.tar.xz"
    base_url = f"https://nodejs.org/dist/v{version}"
    print(f"+ install verified Node runtime {version} under {runtime}")
    if runner.dry_run:
        return node_bin
    cache = STACK_ROOT / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / archive_name
    sums = cache / f"node-v{version}-SHASUMS256.txt"
    download_atomic(f"{base_url}/SHASUMS256.txt", sums)
    wanted = None
    for line in sums.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        if name.lstrip("*") == archive_name:
            wanted = digest
            break
    if not wanted:
        raise InstallError(f"Node checksum missing for {archive_name}")
    import hashlib
    if archive.exists():
        got = hashlib.sha256(archive.read_bytes()).hexdigest()
        if got != wanted:
            quarantine = archive.with_name(archive.name + f".invalid-{int(time.time())}")
            archive.replace(quarantine)
            print(f"  quarantined invalid cached archive: {quarantine}")
    if not archive.exists():
        download_atomic(f"{base_url}/{archive_name}", archive)
    got = hashlib.sha256(archive.read_bytes()).hexdigest()
    if got != wanted:
        raise InstallError(f"Node archive checksum mismatch: got {got}, expected {wanted}")
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runner.run(["tar", "-xJf", str(archive), "-C", str(runtime.parent)])
    return node_bin


def download_atomic(url: str, destination: Path, attempts: int = 3) -> None:
    """Download through curl with continuation, bounded stalls and atomic promotion."""
    part = destination.with_name(destination.name + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(1, attempts + 1):
        try:
            subprocess.run([
                "curl", "--fail", "--location", "--continue-at", "-",
                "--connect-timeout", "15", "--speed-limit", "1024",
                "--speed-time", "30", "--retry", "3", "--retry-all-errors",
                "--output", str(part), url,
            ], check=True)
            part.replace(destination)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt < attempts:
                delay = 2 ** attempt
                print(
                    f"  transient download failure ({attempt}/{attempts}); "
                    f"keeping {part.name} and retrying in {delay}s"
                )
                time.sleep(delay)
    raise InstallError(f"download failed after {attempts} attempts: {url}: {last_error}")


def install_runtime(runner: Runner) -> Path:
    node_bin = install_node_runtime(runner)
    npm_prefix = HOME / ".npm-global"
    openclaw_spec = f"openclaw@{VERSIONS['openclaw']}"
    node_path = f"PATH={node_bin}:/usr/local/bin:/usr/bin:/bin"
    runner.run(["env", node_path, str(node_bin / "npm"), "install", "--global", "--prefix", str(npm_prefix), openclaw_spec])
    openclaw_dist = npm_prefix / "lib/node_modules/openclaw/dist"
    runner.run([
        sys.executable, str(PROJECT / "tools/apply_patch_set.py"),
        str(PROJECT / "patches/openclaw" / VERSIONS["openclaw"]), str(openclaw_dist),
    ])
    wiki_deps = STACK_ROOT / "runtime/memory-wiki-runtime-deps"
    runner.write(wiki_deps / "package.json", (PROJECT / "manifests/memory-wiki-runtime-package.json").read_text())
    runner.run(["env", node_path, str(node_bin / "npm"), "install", "--prefix", str(wiki_deps)])
    wiki_link = openclaw_dist / "extensions/memory-wiki/node_modules"
    print(f"+ ensure runtime dependency link {wiki_link} -> {wiki_deps / 'node_modules'}")
    if not runner.dry_run:
        if wiki_link.is_symlink():
            if wiki_link.resolve() != (wiki_deps / "node_modules").resolve():
                raise InstallError(f"unexpected existing symlink: {wiki_link}")
        elif wiki_link.exists():
            raise InstallError(f"refusing to replace existing path: {wiki_link}")
        else:
            wiki_link.symlink_to(wiki_deps / "node_modules", target_is_directory=True)
    webui_venv = STACK_ROOT / "venvs/open-webui"
    if not runner.dry_run and not webui_venv.exists():
        runner.run([sys.executable, "-m", "venv", str(webui_venv)])
    runner.run([str(webui_venv / "bin/pip"), "install", "--upgrade", "pip"])
    runner.run([str(webui_venv / "bin/pip"), "install", f"open-webui=={VERSIONS['open_webui']}"])
    patch_set = PROJECT / "patches/open-webui" / VERSIONS["open_webui"]
    if runner.dry_run:
        print(f"+ apply hash-guarded patch set {patch_set} to the Open WebUI site-packages root")
    else:
        site_root = subprocess.check_output([
            str(webui_venv / "bin/python"), "-c",
            "import site; print(site.getsitepackages()[0])",
        ], text=True).strip()
        runner.run([sys.executable, str(PROJECT / "tools/apply_patch_set.py"), str(patch_set), site_root])
    components_venv = STACK_ROOT / "venvs/components"
    if not runner.dry_run and not components_venv.exists():
        runner.run([sys.executable, "-m", "venv", str(components_venv)])
    runner.run([str(components_venv / "bin/pip"), "install", "-r", str(PROJECT / "components/requirements.txt")])
    return node_bin


def install_voice(runner: Runner, download_models: bool) -> None:
    venv = STACK_ROOT / "venvs/voice"
    if not runner.dry_run and not venv.exists():
        runner.run([sys.executable, "-m", "venv", str(venv)])
    pip = venv / "bin/pip"
    runner.run([str(pip), "install", "--index-url", "https://download.pytorch.org/whl/cpu", "torch==2.10.0"])
    runner.run([str(pip), "install", "-r", str(PROJECT / "components/requirements-voice.txt")])
    source = STACK_ROOT / "src/chatterbox"
    if not source.exists():
        runner.run(["git", "clone", "--filter=blob:none", "https://github.com/resemble-ai/chatterbox.git", str(source)])
        runner.run(["git", "-C", str(source), "checkout", "--detach", VERSIONS["chatterbox_git"]])
    patch = PROJECT / "patches/chatterbox/5de7a54-float32-inputs.patch"
    if not runner.dry_run:
        forward = subprocess.run(["git", "-C", str(source), "apply", "--check", str(patch)])
        if forward.returncode == 0:
            runner.run(["git", "-C", str(source), "apply", str(patch)])
        else:
            reverse = subprocess.run(["git", "-C", str(source), "apply", "--reverse", "--check", str(patch)])
            if reverse.returncode != 0:
                raise InstallError("Chatterbox patch is neither applicable nor already applied")
    runner.run([str(pip), "install", "--editable", str(source)])
    if download_models:
        runner.run([str(venv / "bin/python"), str(PROJECT / "tools/fetch_voice_models.py")])


def install_memory(runner: Runner, node_bin: Path) -> None:
    venv = STACK_ROOT / "venvs/memory"
    if not runner.dry_run and not venv.exists():
        runner.run([sys.executable, "-m", "venv", str(venv)])
    runner.run([str(venv / "bin/pip"), "install", "-r", str(PROJECT / "components/requirements-memory.txt")])
    runner.run([str(venv / "bin/python"), str(PROJECT / "tools/initialise_empty_memory.py")])
    plugin = STACK_ROOT / "components/memory-rhizome"
    node_path = f"PATH={node_bin}:/usr/local/bin:/usr/bin:/bin"
    runner.run(["env", node_path, str(node_bin / "npm"), "install", "--prefix", str(plugin)])
    runner.run(["env", node_path, str(node_bin / "npm"), "run", "--prefix", str(plugin), "build"])
    if not runner.dry_run:
        config_path = OPENCLAW_HOME / "openclaw.json"
        config = json.loads(config_path.read_text())
        plugins = config.setdefault("plugins", {})
        load_paths = plugins.setdefault("load", {}).setdefault("paths", [])
        if str(plugin) not in load_paths:
            load_paths.append(str(plugin))
        plugins.setdefault("slots", {})["memory"] = "memory-rhizome"
        plugins.setdefault("entries", {})["memory-rhizome"] = {
            "enabled": True,
            "config": {
                "pythonPath": str(venv / "bin/python"),
                "baseDir": str(STACK_ROOT / "memory/archive"),
                "indexPath": str(STACK_ROOT / "memory/archive/memory.index"),
                "textsPath": str(STACK_ROOT / "memory/archive/memory_texts.npy"),
                "metadataPath": str(STACK_ROOT / "memory/archive/memory_metadata.pkl"),
                "embedModel": "sentence-transformers/all-MiniLM-L6-v2",
                "device": "cpu",
                "topK": 12,
                "snippetMaxChars": 700,
            },
        }
        backup = config_path.with_suffix(".json.before-memory-rhizome")
        if not backup.exists():
            shutil.copy2(config_path, backup)
        temporary = config_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(config, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(config_path)
        runner.run(["env", node_path, str(HOME / ".npm-global/bin/openclaw"), "config", "validate"])


def install_jupyter(runner: Runner) -> None:
    runner.run([
        "podman", "build", "--tag", "localhost/rhizome-stack-jupyter:1",
        "--file", str(PROJECT / "containers/jupyter/Containerfile"),
        str(PROJECT / "containers/jupyter"),
    ])


def install_components(runner: Runner) -> None:
    source = PROJECT / "components"
    if source.is_dir():
        runner.deploy_tree(source, STACK_ROOT / "components")
    else:
        raise InstallError("components directory missing; release is incomplete")
    # The installed welcome wizard can re-run the installer only if its
    # manifests, patches and templates travel with it.
    for directory in ["tools", "manifests", "patches", "config", "systemd", "containers", "workspace-template", "bin", "third_party"]:
        runner.deploy_tree(PROJECT / directory, STACK_ROOT / directory)
    runner.write(STACK_ROOT / "VERSION", (PROJECT / "VERSION").read_text())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["linux", "wsl"], required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-packages", action="store_true")
    parser.add_argument("--skip-runtime", action="store_true")
    parser.add_argument("--with-voice", action="store_true")
    parser.add_argument("--download-models", action="store_true", help="download large voice/STT weights; requires --with-voice")
    parser.add_argument("--with-memory", action="store_true")
    parser.add_argument("--with-jupyter", action="store_true")
    parser.add_argument("--with-skills", action="store_true", help="install the six core reliability skills")
    args = parser.parse_args()
    runner = Runner(args.dry_run)
    try:
        if args.download_models and not args.with_voice:
            raise InstallError("--download-models requires --with-voice")
        family = require_preflight(args.target)
        print(f"preflight: target={args.target} family={family} architecture={platform.machine()}")
        if not args.skip_packages:
            if family == "debian":
                runner.run(["sudo", "apt-get", "update"])
            runner.run(package_command(family, voice=args.with_voice, jupyter=args.with_jupyter))
        configure_files(runner)
        install_components(runner)
        if args.with_skills:
            # Use the source copy in dry runs, without writing installed state.
            command = [sys.executable, str(PROJECT / "tools/skills.py"), "install", "--profile", "core"]
            if runner.dry_run:
                command += ["--dry-run"]
            runner.run(command)
        if not args.skip_runtime:
            node_bin = install_runtime(runner)
            if args.with_voice:
                install_voice(runner, args.download_models)
            if args.with_memory:
                install_memory(runner, node_bin)
            if args.with_jupyter:
                install_jupyter(runner)
        if not args.dry_run:
            runner.run(["systemctl", "--user", "daemon-reload"])
        print("installation staged successfully")
        print(f"configuration: {CONFIG_DIR / 'stack.env'}")
        print("services are not started automatically; run 'rhizome-stack welcome' next")
        return 0
    except (InstallError, OSError, subprocess.CalledProcessError) as exc:
        print(f"install failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
