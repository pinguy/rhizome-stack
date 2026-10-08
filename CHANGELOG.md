# Changelog

## Unreleased — hygiene review

- Forward small chat streaming events promptly; preserve gateway error status,
  handle non-JSON errors, and never append a second response to a broken stream.
- Preserve Ollama per-model aliases/parameters during catalogue sync, respect
  configured endpoints and report one-shot failures to systemd. Stage the pinned
  Node/OpenClaw paths in the sync service.
- Confine MiniMax audio and recipe access to the output directory, including
  symlink targets; render dynamic UI text safely and serve correct audio types.
- Validate creative requests before starting GPU work; reject negative/oversized
  bodies and invalid GLiNER timing values before reading or queueing work.
- Write installer files through exclusive private temporary files with cleanup
  on failure, preserving first-change backups.
- Cross-check release manifests against the allow-list, byte counts and hashes;
  reject symlinks and unexpected nested manifest files.
- Add one-command regression checks, HTTP/UI/integrity tests, and CI coverage
  for every suite plus reproducible ZIP and tar.zst builds.

## 0.1.0-alpha.6

- Add an optional pinned ComfyUI setup with a hash-guarded ComfyUI-GGUF patch
  for Qwen Image 2.1 architecture detection.
- Package standalone Qwen Image Desk and MiniMax Music 3 applications without
  Cutroom, video workflows, projects, outputs or reference-machine state.
- Add revision-pinned, SHA-256-verified optional model downloads; weights remain
  outside the release archive.
- Replace broad creative-process killing with exact PID/process-group ownership.
- Add the measured CPU-only MiniLM support path while leaving experimental
  TF-IDF and hybrid retrieval out of the release.
- Produce a deterministic ZIP alongside the existing tar.zst archive.

## 0.1.0-alpha.5

- Bundle the pinned Skills collection with provenance, opt-in profiles and
  preservation of differing local workspace copies.
- Support real ChatGPT, Claude and RhizomeML imports with previews, bounded ZIP
  extraction, provenance, deduplication and complete private index generations.
- Refresh shipped runtime code on reinstall while preserving user state, and
  deploy the resources needed by the installed setup wizard.
- Add optional GLiNER shadow classification and a bounded, tool-free Ornith
  worker with exact model checks, narrow task categories and verification
  receipts. Dispatch remains under Rhizome.
- Add an explicitly started, loopback-only resident GLiNER helper for bounded
  shadow experiments. It is disabled by default and never routes autonomously.
- Add per-job context/output limits, structured prompts, bounded JSON Schema
  checks, timeout quarantine and deterministic exact-string assembly while
  retaining semantic verification as a separate Rhizome decision.
- Harden audio uploads against client-supplied path traversal and use monotonic
  time for the Chatterbox startup deadline.
- Ground only dates explicitly asserted as today's date in web searches and add
  event-centric, symmetric political-framing guidance for news synthesis.
- Expand static, behaviour, workforce, audio, privacy and deterministic release
  checks and document the remaining clean-machine acceptance gaps.

## 0.1.0-alpha.4

- Fix the XDG-isolated onboarding regression exposed by GitHub Actions.

## 0.1.0-alpha.3

- Initial sanitised packaging of the OpenClaw/Open WebUI integration, optional
  memory, voice and Jupyter profiles, versioned patches and first-run wizard.
