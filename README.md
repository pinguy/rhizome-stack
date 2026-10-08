# Rhizome Stack

Built by Antoni Norman with heavy AI-assisted development, manual testing,
direction, tuning and final integration. Built on and alongside OpenClaw,
Open WebUI and other open-source projects; upstream authorship is preserved in
[LICENSES.md](LICENSES.md).

**A portable OpenClaw + Open WebUI setup, with local memory, practical agent
skills and optional speech.** Start with one working model, then add what you
need. Linux and WSL2 use the same setup wizard.

**Status: 0.1.0-alpha.6 candidate.** Installer and regression checks are automated; complete
native Linux and WSL2 installations still need acceptance testing.
Read [known limitations](KNOWN_LIMITATIONS.md) before installing on a working machine.

## What you get

| Component | Purpose | Included by default? |
| --- | --- | --- |
| OpenClaw gateway + Open WebUI | Agent runtime and browser interface, joined by a model adapter | Yes |
| Pinned upstream patches | Preserve the integration against specific upstream builds | Yes |
| Skills | Six core reliability skills; fourteen bundled skills available on demand | Optional |
| GLiNER + Ornith workforce | Optional routing advice and a bounded, text-only local worker under Rhizome | Optional; configured separately |
| Semantic memory | Import your own documents, chat exports and RhizomeML data; hybrid retrieval | Optional |
| Voice | Chatterbox-Nano TTS and faster-whisper STT | Optional |
| Code interpreter | Podman-backed Jupyter environment | Optional |
| CPU MiniLM retrieval | Revision-pinned semantic support for bounded workforce jobs | Optional |
| Qwen Image Desk | Standalone local image workbench over pinned ComfyUI | Optional |
| MiniMax Music 3 | Local song-generation web application over pinned ComfyUI | Optional |

OpenClaw stays pinned to **2026.7.1-2** and Open WebUI to **0.11.0**.
The pinned versions are compatibility choices, not promises that they are the
latest releases. Upgrading them requires checking the patches and real request
path first.

## Start here

Requirements: x86-64 Linux, Python **3.11+**, an Arch/CachyOS or Debian/Ubuntu
family distribution, and systemd user services. Under WSL2 use Ubuntu or Debian
with systemd enabled. Downloads require internet access; the optional voice and
memory environments can use substantial disk space.

Clone the repository, inspect the installer, and preview its actions:

```bash
git clone https://github.com/pinguy/rhizome-stack.git
cd rhizome-stack
./install-linux.sh --dry-run --with-skills
./install-linux.sh --with-skills
```

On WSL2 substitute `./install-wsl.sh`; see [WSL setup](docs/WSL.md).
System packages use interactive sudo; services are staged but not started.

If `~/.local/bin` is not on your PATH, use the full command:

```bash
~/.local/bin/rhizome-stack welcome
~/.local/bin/rhizome-stack doctor
~/.local/bin/rhizome-stack start
~/.local/bin/rhizome-stack smoke
```

Open **http://localhost:8080**, create the first local administrator, choose a
model and send a real message. A model catalogue or healthy HTTP endpoint does
not prove that inference works. [First-run guide](docs/FIRST_RUN.md) covers
provider setup, optional modules and packaged Open WebUI tools.

## Add what you need

```bash
# Profiles can be combined; no model blobs are in this repository.
./install-linux.sh --with-memory --with-skills
./install-linux.sh --with-voice --download-models
./install-linux.sh --with-jupyter
./install-linux.sh --with-routing
./install-linux.sh --with-retrieval
./install-linux.sh --with-creative --download-creative-models

# Launch either creative app after installation.
rhizome-stack creative qwen
rhizome-stack creative minimax

# See the collection, or install the extra skills deliberately.
rhizome-stack skills list
rhizome-stack skills install --profile all --dry-run
rhizome-stack skills install --profile all

# Preview a private import before writing anything.
rhizome-stack import ~/Downloads/conversations.json --type chatgpt --dry-run
rhizome-stack import ~/Downloads/conversations.json --type chatgpt
rhizome-stack import ~/Downloads/memory.jsonl.gz --type rhizomeml
```

Ollama and its models are installed separately. Hosted provider credentials are
entered on the target machine. Memory, chats, credentials, voice references,
browser profiles and model weights are never seeded from the reference machine.

## Guides

- [First run and model verification](docs/FIRST_RUN.md)
- [Memory formats, provenance and rebuilding](docs/MEMORY.md)
- [Skills and companion projects](docs/INTEGRATIONS.md)
- [GLiNER routing advice and the Ornith workforce](docs/WORKFORCE.md)
- [ComfyUI, Qwen Image Desk and MiniMax Music 3](docs/CREATIVE.md)
- [Updating and troubleshooting](docs/MAINTENANCE.md)
- [Native Linux](docs/LINUX.md) · [WSL2](docs/WSL.md)
- [Changes](CHANGELOG.md) · [Known limitations](KNOWN_LIMITATIONS.md)

## Development and releases

```bash
# Keep the test environment outside the source tree.
python3 -m venv /tmp/rhizome-stack-tests
/tmp/rhizome-stack-tests/bin/python -m pip install Flask==3.1.2 requests==2.32.5 numpy==2.3.5 faiss-cpu==1.15.0
/tmp/rhizome-stack-tests/bin/python tools/check.py
python3 tools/export_release.py --output /tmp/rhizome-stack-release
python3 tools/build_release.py --output-root /tmp/rhizome-stack-build
```

The test runner discovers every `tests/test_*.py` suite and returns a failure
if any suite fails. Node is needed for the creative JavaScript regression;
FAISS storage checks skip explicitly when its dependencies are absent.
See [hygiene review notes](docs/HYGIENE_REVIEW.md) for changes and validation limits.

The exporter copies only the paths in `manifests/release-files.json`, then runs
the privacy audit and SHA-256 manifest verification. Unlisted files are excluded.
Inspect the resulting manifest and diff before distributing a release.

Original glue and documentation are MIT; bundled Skills retain Apache-2.0,
and upstream patches retain their upstream terms. See [LICENSES.md](LICENSES.md).
