# Hygiene review — 8 October 2026

Second pass over the supplied pre-media/voice-lab archive. OpenClaw 2026.7.1-2,
Open WebUI 0.11.0, all other compatibility/model pins, bundled skill snapshots,
and routing defaults are retained. No installed service, owner configuration or
model weight was changed during this review.

## Additional fixes

| Area | Confirmed failure | Change |
| --- | --- | --- |
| Provider onboarding | A selected model could remain absent from the allow-list used by the adapter; selecting a primary erased fallbacks | Add the selected model and retain existing model settings/fallbacks |
| Tool registration | A missing tool reported by HTTP 404 aborted first-time registration | Accept 404 only for tool-ID lookup; preserve existing tools and propagate other errors |
| Whisper lifecycle | A previous idle timer could terminate an active decoder; unbounded reads and unread stderr could hang it | Serialise idle unload with decoding, invalidate stale timers, bound JSON replies and reap failed workers |
| Voice preview isolation | With no configured reference WAV, a preview left its conditioning in the shared model | Restore the cached bundled/configured default after success or failure without re-encoding it |
| Speech requests | JSON arrays/non-text input could fail as server errors; stop during startup/final generation was missed | Validate text and seeds before model work; retain the cancellation epoch through startup and check completion |
| Runtime paths | The bridge ignored its configured port; voice downloads ignored custom install roots | Honour the port and pass the selected model directory explicitly |
| Private writes | Wizard, memory-plugin and import paths still used predictable temporary filenames | Share exclusive private writes with fsync, atomic replacement and failure cleanup |

## Verification of this pass

- Eleven suites passed: 96 unittest cases, plus the static and creative
  graph/manifest check groups, with no skips. Nineteen regression cases were
  added for the failures above.
- Real FAISS I/O uses deterministic vectors; no embedding model was downloaded.
- Real local subprocess pipes exercise partial replies, EOF, Unicode text,
  failed startup and decode cleanup. A concurrent timer fixture verifies that
  unload waits for the decode lock and ignores a superseded timer.
- A loopback HTTP fixture exercises first-time tool registration, preserving
  an existing tool and propagating authentication/create errors.
- Chatterbox request isolation uses synthetic conditioning/waveform objects.
  The pinned upstream source was inspected to confirm that preparing a preview
  replaces `model.conds`. These checks do not test speech inference or quality.
- Installer/setup/import tests use disposable directories and symlink fixtures;
  no working installation was modified. The custom-root download test mocks the
  downloader and fetches no weights.
- Privacy audit, allow-list, SHA-256/size verification and `git diff --check`
  passed. Two independent ZIP and tar.zst builds matched byte-for-byte, retaining
  the supplied executable permissions.

Test environment: Linux x86-64, Python 3.12, Node for JavaScript checks, and the
Flask/Requests/NumPy/FAISS versions documented in the repository's CI. Dependencies
were installed in a disposable environment outside the source tree. Complete
Linux/WSL installation, live provider chat, actual Whisper/Chatterbox inference,
and GPU image/music generation remain unverified here. No compatibility upgrade
or real model download was attempted.

## Applying this archive

Use the updated source with the existing maintenance procedure and inspect an
installer dry run using the same optional profiles as the target. Preserve
private config and weights. Refresh the voice components and restart only the
affected services deliberately, then check actual chat, transcription, voice
preview isolation and long-speech stop through the browser. Existing populated
`stack.env` files are preserved; add timeout overrides locally only if needed.

## Previous pass — 7 October 2026

Reviewed the supplied 0.1.0-alpha.6 candidate archive and applied the fixes below.
The upstream version pins, model manifests, bundled skill snapshots and runtime
routing defaults remain unchanged. This is an unreleased maintenance pass, not
a claim of complete Linux/WSL or GPU acceptance.

## Fixes

| Area | Issue | Change |
| --- | --- | --- |
| Chat streaming | Reading 64 KiB at once could hold small SSE events until the response ended | Forward available chunks immediately; close a broken stream without appending a second HTTP response |
| Gateway errors | A non-JSON error body could crash error handling; connection failures were labelled client errors | Preserve upstream HTTP status, supply a safe JSON fallback and use HTTP 502 for connection failures; no replay/retry added |
| Model sync | Catalogue refresh erased aliases and per-model parameters; one-shot failures returned success | Preserve settings for retained models, honour the configured endpoint, bound CLI execution and report failures to systemd |
| Runtime paths | Sync depended on a shell PATH that user services may not inherit | Stage the pinned Node/OpenClaw paths; keep the reader and CLI on the same selected config |
| MiniMax file access | The audio fallback accepted escaping subfolders; recipe symlinks could escape the output tree | Validate paths before proxying, reading or deleting; reject parent traversal, absolute paths and escaping symlinks |
| MiniMax UI | Titles, filenames, paths and backend error strings could become HTML | Escape dynamic markup and use text for error messages; correct WAV/FLAC response types |
| Creative requests | Negative lengths could block a read; malformed generation settings could fail after starting the engine | Bound JSON bodies and validate types, finite numbers and generation limits before GPU work |
| Workforce HTTP | Bad timing values could fail after enqueue; unknown retrieval routes reported success | Validate deadlines before enqueue, reject invalid bodies and return HTTP 404 for unknown retrieval paths |
| Installer writes | Predictable temporary names could follow symlinks; secrets were written before permissions tightened | Use exclusive private temporary files, flush/fsync, atomically replace and clean up failures |
| Release verification | Byte counts and the allow-list were not cross-checked; nested manifest names were ignored | Verify counts, hashes and membership; reject symlinks and extra nested manifests; report malformed manifests cleanly |
| Test maintenance | Creative checks were absent from CI and documented test commands | Add `python3 tools/check.py`, automatic suite discovery and CI comparisons of both release archive formats |

## Verification

- Nine test suites passed with no skips: 77 unittest cases, plus the static and
  creative graph/manifest check groups. This includes 26 new regression cases.
- FAISS tests used the real NumPy/FAISS packages with deterministic vectors.
- Local HTTP fixtures verified early SSE delivery, error handling, request
  rejection, model-setting preservation and file containment.
- The actual MiniMax JavaScript handlers ran in Node with a small DOM fixture,
  including hostile title, filename and error strings. This is not a full browser
  or visual acceptance test.
- Installer write failures and temporary-file symlink attacks used disposable
  fixtures only. The installer was not run against a working installation.
- Privacy audit, allow-list, SHA-256 and byte-count verification passed for the
  exported release. Two independent ZIP builds and two tar.zst builds matched
  byte-for-byte. The supplied archive's executable permissions were preserved.
- `git diff --check` passed. The final ZIP contains regenerated release metadata,
  source and this report; it excludes test environments and runtime state.

The local test environment was Linux x86-64 with Python 3.12. No real provider
request, OpenClaw schema validation, fresh dependency installation of the full
stack, WSL2 installation, GLiNER/MiniLM model inference or GPU image/music
render was performed. The existing clean-machine acceptance limitations still
apply. The new GitHub Actions workflow was inspected locally but not run on
GitHub during this review.

## Handover

Use this archive as the updated source. `CHANGELOG.md` records the maintenance
changes without advancing the release version. Follow the existing maintenance
procedure, select the same optional profiles as the target installation, and
inspect an installer dry run before applying it. The model-sync unit has changed;
reinstalling stages that change with the other service templates.

After applying to a target, verify an actual streamed chat, retained Ollama
aliases/parameters after a sync, and a real image/music generation if the
creative profile is used. Keep the existing local configuration, backups and
model weights. The review makes no change to GLiNER's advisory authority or the
configured CPU/GPU placement.
