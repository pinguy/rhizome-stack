# Changelog

## 0.1.0-alpha.2

- Bundle all twelve Skills directories at a pinned commit, retain Apache-2.0
  and add checked, opt-in core/all installation.
- Refresh shipped runtime code on reinstall, preserve user workspace files,
  and deploy the installer resources needed by the installed welcome wizard.
- Read actual ChatGPT/Claude exports, JSONL/GZIP and RhizomeML dataset/PDF formats.
  Preserve source metadata and multiple origins for duplicate text.
- Add import previews, stage-only mode, explicit reindexing, private file
  permissions, bounded ZIP extraction and complete index generations.
- Keep memory row IDs stable on additions; check index counts and embedding
  model identity when loading.
- Check the selected model rather than accepting any successful catalogue
  response. Save the selected Ollama endpoint and complete NVIDIA provider data.
- Add CLI help, installed runtime checks and bounded HTTP smoke probes.
- Replace the release export's exclusion-only scan with an explicit file list.
- Expand first-run, integration, memory and maintenance guides and add
  regression tests for the confirmed failure cases.

## 0.1.0-alpha.1

Initial sanitised packaging of the OpenClaw/Open WebUI integration, optional
memory/voice/Jupyter profiles, versioned patches and first-run wizard.
