# Changelog

## 0.1.0-alpha.14 candidate — 16 October 2026 hygiene follow-up

- Stage every upstream patch and verify its resulting hash before changing
  installed code. Preserve file permissions, use atomic file replacements and
  restore changed files on ordinary installation errors, keeping rollback copies.
- Reject escaping, symlinked and duplicate patch targets without weakening the
  clean/patched hash guards or changing upstream payloads.
- Match complete process arguments in all three creative desks so a similar
  script name, embedded argument or port cannot pass the ComfyUI ownership check.
- Reject incomplete Qwen JSON bodies before prompt expansion or generation.
- Add regression cases and document patch failure recovery and test limits.
- Preserve the repository's portable workforce reference when integrating the
  refreshed snapshot; include it in release and skill checksum manifests.

## 0.1.0-alpha.13 candidate — 16 October 2026 Control UI quota fix

- Delay the terminal-chat allowance refresh until the chat event has settled,
  preserve the last usable five-hour/weekly snapshot when the provider briefly
  returns an empty window list, and retry once after 15 seconds.
- Add a deterministic regression for the empty-first-refresh path. The quota
  control must retain both windows, refresh on retry and never require a whole
  Chrome-app reload to recover.
- Preserve alpha.12 unchanged as evidence of the bad immediate-refresh build.

## 0.1.0-alpha.12 candidate — 16 October 2026 current-stack capture

- Re-capture every live Open WebUI 0.11.0 and OpenClaw 2026.7.1-2 downstream
  patch against pristine upstream packages, including the current Control UI
  quota refresh, provider fallback probe, model catalogue/store changes and
  Jupyter cold-wake retry.
- Add the fail-fast, no-pull Jupyter service and token-aware 30-second idle
  guard so a missing image cannot cause registry-pull crash loops and a cold
  code-interpreter call can wake the sandbox.
- Refresh Qwen Image Desk, WAN Video Desk and MiniMax Music 3. MiniMax now
  displays every returned writer model and supports per-track deletion.
- Refresh thirteen pinned upstream Skills at revision
  `99e53d4501703a78fb87ad4221512029558802b7`, add
  `minimum-sufficient-change`, and refresh the two owner-supplied stack skills.
- Lock Reuters into the Brave search source policy with an explicit regression
  for reputable-reporting classification.
- Add privacy-scrubbed browser screenshots of all three standalone apps and
  real saved Open WebUI PNG, MP3 Preview and inline MP4 render paths.

## 0.1.0-alpha.11 candidate — 14 October 2026 security review

- Require a private adapter bearer token, loopback Host and JSON requests;
  reject browser origins and cross-site calls before forwarding to OpenClaw.
- Authenticate creative desk adapter calls and protect their local HTTP
  endpoints against cross-site requests and DNS rebinding.
- Generate separate adapter and Jupyter secrets; require authenticated Jupyter
  with Host checks and configure both Open WebUI code execution paths.
- Select Python 3.11–3.12 before installation and reject incompatible existing
  environments. Consume both Python bounds from the version manifest.
- Expand privacy detection for Brave, Hugging Face, AWS, Google and Slack
  credentials and numbered handles; remove the embedded personal identifier.
- Add security regressions and document the saved-settings migration required
  for existing Open WebUI installations in `docs/SECURITY_UPGRADE.md`.

## 0.1.0-alpha.10 candidate — 14 October 2026 hygiene review

- Stop GPU hand-over when Ollama returns a missing or malformed runner list,
  including the final unload check; unknown state no longer counts as idle.
- Correct WAN suffix byte ranges for media playback and report file size on
  rejected ranges. Reject non-object JSON requests with HTTP 400.
- Preserve seed zero in WAN batches, randomise every take when requested,
  and reject seed overflow before any batch job is queued.
- Decode quoted environment settings and JSON-escape template values when
  creating OpenClaw configuration, preserving tokens and paths accurately.
- Extend WAN HTTP/batch and three-generator receipt recovery regressions;
  correct stale Ollama installation and creative output documentation.

## 0.1.0-alpha.9 candidate — 14 October 2026 WAN chat integration

- Add the packaged `wan_video` Open WebUI tool, shared VRAM hand-off and
  durable MP4 saved-chat attachments alongside Qwen Image and MiniMax Music.
- Add the pinned Open WebUI 0.11.0 inline HTML5 MP4 renderer replacement and
  hash verification without changing the existing PNG or MP3 branches.
- Retain completed WAN takes in Video Desk so chat-generated clips can be
  inspected, downloaded and reused from the standalone interface.
- Retry WAN tiled decoding at 48/12 after the normal 64/16 path runs out of
  memory, reserving 32/12 for a second, tighter-memory attempt.
- Preserve the newer Ollama welcome/install flow from the reviewed main
  archive, including explicit confirmation before pulling missing Ornith tags.

## 0.1.0-alpha.8 candidate — 14 October 2026 standalone WAN Video Desk

- Package standalone WAN Video Desk with text-to-video and image-to-video
  workflows, pinned model assets, gallery provenance and editable takes.
- Refresh the Qwen Image Desk and MiniMax Music interfaces while preserving
  their hardened packaged backends and shared ComfyUI ownership boundaries.

## 0.1.0-alpha.7 candidate — 13 October 2026 integration

- Integrate the reviewed archive with the current repository, retaining its
  existing onboarding, private-write, voice and media-recovery improvements.
- Upgrade the packaged Brave search tool from 1.7.2 to the supplied 1.9.0,
  including bounded async work, partial results and expanded diagnostics.
- Add Qwen gallery deletion through desktop Trash and prune stale entries.
- Validate generator health responses and stop startup polling on HTTP errors.
- Reject oversized references before pixel decoding and seed overflow before
  queueing a Qwen batch. Extend regression coverage and document verification.

## Unreleased — hygiene review

- Add wizard-selected models to the gateway allow-list and preserve fallback
  routes, aliases and model tuning when changing the primary provider.
- Treat HTTP 404 as a missing tool during registration while retaining other
  API failures and preserving existing tool customisations.
- Protect Whisper decoding from stale idle timers, bound worker startup/reply
  waits, and reap failed workers without unread stderr pipes.
- Restore Chatterbox's cached default voice after successful or failed previews,
  including installations without a configured reference WAV; use a monotonic
  idle clock and reject malformed text/seed inputs before generation.
- Honour speech cancellation during startup and the final chunk, the configured
  bridge port, and custom voice-model download directories.
- Extend private atomic writes to onboarding, memory-plugin setup and imported
  records; add setup and voice lifecycle regressions.
- Distinguish refused connections from HTTP/queue errors during media hand-off;
  unknown ComfyUI state now blocks model release rather than reporting idle.
- Retain completed media output paths before engine shutdown so attachment
  failures can recover without polling lost history or generating duplicates.
- Keep media request inputs stable across retries, preserve terminal failures,
  and write private, fsynced receipts through exclusive temporary files.
- Add 15 media/registration regressions and one shared test dependency file,
  including the Pillow dependency required by Qwen reference-image checks.

- Add Qwen Image Desk reference upload/edit conditioning with persisted
  provenance, reuse and same-seed reruns while preserving text-only generation.
- Refresh the MiniMax Music 3 interface without replacing the hardened packaged
  backend or its exact-process ownership boundary.
- Add opt-in Open WebUI Qwen/MiniMax tools with serialised Ollama-to-ComfyUI VRAM
  hand-off and durable native PNG/MP3 saved-chat attachments.
- Package Chatterbox Voice Lab with local media preparation, normalised preview,
  rollback-backed default switching and Trash-based library removal.
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
