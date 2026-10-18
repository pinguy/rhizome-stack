# Response to the 18 October 2026 independent audit

Version 0.1.0-alpha.15 addresses the nine numbered findings in the independent
source and engineering audit of the alpha.14 candidate.

## Corrections

- **F1:** curated Markdown fallback and recall tracking now use the configured
  OpenClaw workspace, independently of the vector archive directory.
- **F2:** Open WebUI delegation keys are scoped by authenticated user and a
  digest of the complete saved-chat ID. Unsaved calls receive isolated random
  sessions; there is no global `unsaved` session.
- **F3:** uninstall uses an installed manifest covering all 18 shipped user
  units, resolves the configured stack root, has a dry-run, verifies ownership
  before mutation, restores prior unit backups and has no ripgrep dependency.
- **F4:** a staged OpenClaw memory configuration is validated through
  `OPENCLAW_CONFIG_PATH` before the active configuration is promoted.
- **F5:** the memory worker handles spawn/exit as terminal conditions and
  bounds request time and response bytes. Status reflects observed health.
- **F6:** Jupyter mounts the actual Open WebUI `UPLOAD_DIR` read-only and the
  middleware confines advertised paths to that directory.
- **F7:** tool registration retains preservation as its default, while adding
  explicit hash/diff and update-with-private-backup modes. `doctor` reports
  deployed-versus-shipped drift when an admin token file is configured.
- **F8:** media generation requires a stable message ID or explicit
  idempotency key before it starts a service or GPU hand-off.
- **F9:** OpenClaw delegation validates and honours `OPENCLAW_PORT`.

The Debian and Arch prerequisite lists now explicitly include `patch`.
Regression coverage includes differing workspace/archive roots, missing/hung/
malformed memory workers, session-key isolation, custom ports, uninstall
dry-run/rollback/idempotency, staged-config validation failure, upload path
confinement, tool update backups and media retry identity.

## Boundaries retained

The deployment remains owner-operated and loopback-oriented, not a hostile
multi-user isolation boundary. The upstream Ollama installer is still fetched
and run only after consent but is not pinned by content digest. Privacy scans
cannot prove that screenshot pixels contain no personal information, so manual
visual review remains required. A real browser upload/Jupyter check, GPU media
generation, native Linux install and WSL2 acceptance remain environment-level
release gates rather than claims made by static tests.
