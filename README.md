# Rhizome Stack

Built by Antoni Norman with heavy AI-assisted development, manual testing,
direction, tuning and final integration. Built on and alongside OpenClaw,
Open WebUI and other open-source projects; upstream authorship is preserved in
[LICENSES.md](LICENSES.md).

Portable packaging for the working OpenClaw + Open WebUI integration used on the
reference CachyOS machine. The repository contains installation logic and a
sanitised workspace seed; it does **not** contain the owner's credentials,
memory, chats, browser profile, voice samples, model blobs, or databases.

Current status: **alpha candidate**. See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)
before installing or publishing it.

## Supported targets

- Native Linux: CachyOS/Arch and Debian/Ubuntu, x86-64, systemd user services.
- WSL2: Ubuntu or Debian with systemd enabled.

Other distributions are rejected by preflight until their package mapping and
service behaviour have been tested.

## What is installed

- A pinned OpenClaw CLI and gateway (`2026.7.1-2` by default).
- Open WebUI in an isolated Python virtual environment (`0.11.0` by default).
- The dynamic OpenClaw-to-Open-WebUI model adapter.
- Local Ollama catalogue sync.
- Optional Chatterbox-Nano TTS and faster-whisper STT wiring.
- Optional Podman-backed Jupyter code interpreter.
- Empty, user-owned workspace memory scaffolding.
- A shared first-run wizard for provider verification and optional components.
- Owner-only document, book, ChatGPT and Claude history import.

Model weights are downloaded separately and are never part of a release
archive. Provider and messaging credentials are entered on the target machine.

## Install

Inspect the scripts first. Then:

```bash
./install-linux.sh --dry-run
./install-linux.sh
```

Under WSL2:

```bash
./install-wsl.sh --dry-run
./install-wsl.sh
```

Optional profiles may be combined:

```bash
./install-linux.sh --with-memory --with-voice --download-models --with-jupyter
```

Installers do not accept secrets on the command line. After installation, run
`rhizome-stack welcome`. It configures and verifies the intelligence backend
first, then offers optional local components and private knowledge import.

## Release safety

Releases are assembled from an explicit allow-list:

```bash
python3 tools/export_release.py --source-root .. --output /tmp/rhizome-stack-release
python3 tools/privacy_audit.py /tmp/rhizome-stack-release
```

Official archives are produced deterministically with `tools/build_release.py`.

The audit is a release gate, not a proof that arbitrary files are safe. A human
must still inspect the generated manifest and diff before publishing.

## Current boundary

This extraction preserves the glue and service topology. The five changed
OpenClaw bundles and fifteen changed/retired Open WebUI package files are
captured as versioned, hash-guarded patch sets. Three generated frontend files
use audited textual replacements because ordinary line patches are malformed
against minified bundles. Model weights and user databases remain external.

The live machine is not modified by developing or exporting this package.

## Licence

This is deliberately multi-licensed. Original Rhizome Stack glue is MIT;
upstream-derived files keep their upstream terms. In particular, Open WebUI
0.11.0 uses the Open WebUI licence and its historical MIT/BSD boundaries.
See [LICENSES.md](LICENSES.md) and [third_party/](third_party/).
