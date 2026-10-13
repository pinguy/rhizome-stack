# Reviewed archive integration — 13 October 2026

Integrated the reviewed `rhizome-stack(2).zip` with repository commit
`92ae6d73fb9fbcaf2a22b520b26b73b7b4fa858d`, preserving newer repository work.
The resulting source is the 0.1.0-alpha.7 candidate; OpenClaw 2026.7.1-2 and
Open WebUI 0.11.0 remain pinned.

## Reconciliation

The repository already contained the review's model visibility, fallback
preservation, private configuration writes, media request identity and terminal
failure fixes. Its media receipts additionally retain completed outputs before
engine shutdown and fsync their directory. These implementations, existing voice
lifecycle fixes, tool-registration handling and shared test dependencies were
preserved. The archive's duplicate private-file helper was not added.

Integrated from the supplied archive:

- Brave search tool 1.9.0, replacing the repository's 1.7.2 implementation.
- Qwen gallery deletion through desktop Trash and stale-entry pruning, with
  corresponding frontend controls and gallery regression coverage.
- Reference-image dimension checks before pixel decoding and batch seed bounds
  checked before enqueueing any images.
- Validated generator health responses and immediate failure for HTTP errors
  during startup polling, complementing the repository's queue-state guards.
- First-run documentation explaining model visibility, preserved fallbacks and
  private configuration writes; updated release version and review links.

## Validation

The combined source passed all 12 bundled suites: 120 unittest cases, no skips,
plus static and creative graph/manifest checks. Five cases were added to the
repository's existing coverage. NumPy/FAISS storage tests used deterministic
vectors; HTTP, service and GPU boundaries used fixtures or mocks.

Release export passed the privacy audit, allow-list and SHA-256/size checks.
Two independent ZIP builds matched byte-for-byte; so did the two tar.zst builds.
`git diff --check` passed. Generated archives and runtime state are not committed.

The previously delivered ZIP passed its own nine-suite/97-case check. The
numbers above apply to this integrated repository, which retains the additional
upstream tests and fixes.

No live provider chat, GPU generation, full runtime dependency installation,
OpenClaw schema validation, browser acceptance or clean native Linux/WSL2
installation was performed. Existing acceptance limits remain documented in
`KNOWN_LIMITATIONS.md`. Follow the maintenance guide and inspect an installer
dry run before updating a working installation.
