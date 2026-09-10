#!/usr/bin/env python3
"""Maintainer tool: import explicitly reviewed glue source from a live workspace.

This is intentionally not a recursive copier. Each source has a destination and
small, reviewable portability transformation. Run the privacy audit afterwards.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


FILES = {
    "scripts/openclaw_openwebui_adapter.py": "openclaw_openwebui_adapter.py",
    "scripts/openclaw_ollama_model_sync.py": "openclaw_ollama_model_sync.py",
    "scripts/sync_openwebui_memory.py": "sync_openwebui_memory.py",
    "scripts/query_rhizomeml_archive.py": "query_memory_archive.py",
    "scripts/chatterbox_tts_cli.py": "chatterbox_tts_cli.py",
    "TTS_SST/openwebui_audio_bridge.py": "openwebui_audio_bridge.py",
    "TTS_SST/chatterbox_nano_server.py": "chatterbox_nano_server.py",
    "TTS_SST/transcribe_faster_whisper.py": "transcribe_faster_whisper.py",
    "TTS_SST/whisper_worker.py": "whisper_worker.py",
    "TTS_SST/transcribe.sh": "transcribe.sh",
    "extensions/memory-rhizome/index.ts": "memory-rhizome/index.ts",
    "extensions/memory-rhizome/rhizome_memory_server.py": "memory-rhizome/rhizome_memory_server.py",
    "extensions/memory-rhizome/openclaw.plugin.json": "memory-rhizome/openclaw.plugin.json",
    "extensions/memory-rhizome/package.json": "memory-rhizome/package.json",
    "extensions/memory-rhizome/package-lock.json": "memory-rhizome/package-lock.json",
    "extensions/memory-rhizome/README.md": "memory-rhizome/README.md",
    "scripts/openwebui_web_search_tool.py": "openwebui-tools/web_search.py",
    "scripts/openwebui_rhizome_memory_tool.py": "openwebui-tools/memory_search.py",
    "scripts/openwebui_openclaw_agent_tool.py": "openwebui-tools/openclaw_agent.py",
}


def transform(relative: str, text: str, home: Path) -> str:
    text = re.sub(r"^#!.*python[^\n]*", "#!/usr/bin/env python3", text)
    workspace = str(home / ".openclaw/workspace")
    if relative.endswith("sync_openwebui_memory.py"):
        text = text.replace("import json\n", "import json\nimport os\n")
        text = re.sub(r'^USER_ID = .*$', 'USER_ID = os.environ.get("OPENWEBUI_USER_ID", "")', text, flags=re.M)
        text = re.sub(
            r'^SECRET_FILE = .*$',
            'SECRET_FILE = Path(os.environ.get("WEBUI_SECRET_FILE", str(Path.home() / ".config/rhizome-stack/webui_secret_key")))',
            text, flags=re.M,
        )
        text = re.sub(
            r'^WS = .*$',
            'WS = Path(os.environ.get("RHIZOME_WORKSPACE", str(Path.home() / ".local/share/rhizome-stack/workspace")))',
            text, flags=re.M,
        )
    elif relative.endswith("openwebui_audio_bridge.py"):
        text = text.replace(
            f"TTS_SST_DIR = Path('{workspace}/TTS_SST')",
            'TTS_SST_DIR = Path(os.environ.get("VOICE_COMPONENT_DIR", str(Path.home() / ".local/share/rhizome-stack/components")))',
        )
        text = text.replace(
            f"'{workspace}/.venvs/faster-whisper/bin/python'",
            'str(Path.home() / ".local/share/rhizome-stack/venvs/voice/bin/python")',
        )
        text = text.replace(
            f"'{home}/.local/share/openclaw/models/faster-whisper-large-v3-turbo'",
            'str(Path.home() / ".local/share/rhizome-stack/models/faster-whisper-large-v3-turbo")',
        )
    elif relative.endswith("chatterbox_nano_server.py"):
        text = text.replace(
            f'"{workspace}/TTS_SST/models/chatterbox-nano"',
            'str(Path.home() / ".local/share/rhizome-stack/models/chatterbox-nano")',
        )
    elif relative.endswith("transcribe_faster_whisper.py"):
        text = text.replace("import sys\n", "import os\nimport sys\n")
        text = text.replace(
            f'"{home}/.local/share/openclaw/models/faster-whisper-large-v3-turbo"',
            'os.environ.get("WHISPER_MODEL", str(Path.home() / ".local/share/rhizome-stack/models/faster-whisper-large-v3-turbo"))',
        )
    elif relative.endswith("whisper_worker.py"):
        text = text.replace(
            f'"{home}/.local/share/openclaw/models/faster-whisper-large-v3-turbo"',
            'str(Path.home() / ".local/share/rhizome-stack/models/faster-whisper-large-v3-turbo")',
        )
        text = text.replace("import sys\n", "import sys\nfrom pathlib import Path\n")
    elif relative.endswith("transcribe.sh"):
        text = text.replace(
            f"{workspace}/.venvs/faster-whisper/bin/python",
            '${HOME}/.local/share/rhizome-stack/venvs/voice/bin/python',
        )
    elif relative.endswith("query_rhizomeml_archive.py"):
        text = text.replace(
            f'Path("{workspace}/RhizomeML")',
            'Path(os.environ.get("RHIZOME_ARCHIVE_DIR", str(Path.home() / ".local/share/rhizome-stack/memory/archive")))',
        )
        text = text.replace(
            f'Path("{home}/.openclaw/rag")',
            'Path(os.environ.get("BOOK_RAG_DIR", str(Path.home() / ".local/share/rhizome-stack/memory/books")))',
        )
        text = text.replace(
            f'Path("{workspace}/memory/vector_store")',
            'Path(os.environ.get("WORKSPACE_MEMORY_INDEX_DIR", str(Path.home() / ".local/share/rhizome-stack/memory/workspace")))',
        )
    elif relative.endswith("memory-rhizome/index.ts"):
        text = text.replace('import path from "node:path";\n', 'import path from "node:path";\nimport os from "node:os";\n')
        text = text.replace(
            f'const OPENCLAW_DIST = "{home}/.npm-global/lib/node_modules/openclaw/dist";',
            'const OPENCLAW_DIST = process.env.OPENCLAW_DIST ?? path.join(os.homedir(), ".npm-global/lib/node_modules/openclaw/dist");',
        )
        text = text.replace(
            f'cfg.baseDir || "{workspace}/RhizomeML"',
            'cfg.baseDir || path.join(os.homedir(), ".local/share/rhizome-stack/memory/archive")',
        )
        text = text.replace(
            f'cfg.pythonPath || "{home}/.venv/bin/python"',
            'cfg.pythonPath || path.join(os.homedir(), ".local/share/rhizome-stack/venvs/memory/bin/python")',
        )
        text = re.sub(r'timezone: "[A-Za-z_]+/[A-Za-z_]+",', 'timezone: process.env.TZ || "UTC",', text)
    elif relative.endswith("memory-rhizome/rhizome_memory_server.py"):
        text = text.replace(
            f'os.environ.get("RHIZOME_BASE_DIR", "{workspace}/RhizomeML")',
            'os.environ.get("RHIZOME_BASE_DIR", os.path.expanduser("~/.local/share/rhizome-stack/memory/archive"))',
        )
    elif relative.endswith("memory-rhizome/openclaw.plugin.json"):
        text = text.replace(f"{home}/.venv/bin/python", "~/.local/share/rhizome-stack/venvs/memory/bin/python")
        text = text.replace(f"{workspace}/RhizomeML", "~/.local/share/rhizome-stack/memory/archive")
    elif relative.endswith("openwebui_web_search_tool.py"):
        text = re.sub(
            r'OPENWEBUI_DB = Path\(\n\s*"[^"]+"\n\)',
            'OPENWEBUI_DB = Path(os.environ.get("OPENWEBUI_DB", str(Path.home() / ".local/share/rhizome-stack/state/openwebui-data/webui.db")))',
            text,
        )
        text = re.sub(
            r'OPENCLAW_CONFIG = Path\("[^"]+"\)',
            'OPENCLAW_CONFIG = Path(os.environ.get("OPENCLAW_CONFIG", str(Path.home() / ".openclaw/openclaw.json")))',
            text,
        )
        text = re.sub(r'LOCAL_TZ = ZoneInfo\("[^"]+"\)', 'LOCAL_TZ = ZoneInfo(os.environ.get("TZ", "UTC"))', text)
        text = re.sub(r'DEFAULT_LOCALITY = "[^"]*"', 'DEFAULT_LOCALITY = os.environ.get("DEFAULT_LOCALITY", "")', text)
        text = re.sub(
            r'LOCAL_NEWS_QUERY_TERMS = \(.*?\n\)',
            'LOCAL_NEWS_QUERY_TERMS = (\n    "around me",\n    "in my area",\n    "local headlines",\n    "local news",\n    "near me",\n)',
            text,
            flags=re.S,
        )
    elif relative.endswith("openwebui_rhizome_memory_tool.py"):
        text = re.sub(
            r'^DEFAULT_PYTHON = .*$',
            'DEFAULT_PYTHON = str(Path.home() / ".local/share/rhizome-stack/venvs/memory/bin/python")',
            text, flags=re.M,
        )
        text = re.sub(
            r'^DEFAULT_QUERY_SCRIPT = .*$',
            'DEFAULT_QUERY_SCRIPT = str(Path.home() / ".local/share/rhizome-stack/components/query_memory_archive.py")',
            text, flags=re.M,
        )
    elif relative.endswith("openwebui_openclaw_agent_tool.py"):
        text = text.replace("import json\n", "import json\nimport os\n")
        text = re.sub(
            r'^CONFIG = Path\("[^"]+"\)$',
            'CONFIG = Path(os.environ.get("OPENCLAW_CONFIG", str(Path.home() / ".openclaw/openclaw.json")))',
            text, flags=re.M,
        )
    text = text.replace(str(home), "${HOME}")
    local_user = os.environ.get("USER", "__local_user__")
    text = re.sub(rf"\b{re.escape(local_user)}\b", "the-user", text, flags=re.I)
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parents[1] / "components")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for source_name, target_name in FILES.items():
        source = workspace / source_name
        if not source.is_file():
            raise SystemExit(f"missing reviewed source: {source}")
        target = destination / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(transform(source_name, source.read_text(), Path.home()))
        target.chmod(0o755)
        print(f"vendored {source_name} -> {target.relative_to(destination.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
