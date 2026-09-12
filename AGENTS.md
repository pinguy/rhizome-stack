# Working on Rhizome Stack

This file guides agents developing this repository. It applies throughout the
checkout, subject to more specific instructions in a subdirectory. The separate
`workspace-template/AGENTS.md` is seeded into an installed agent workspace;
keep repository development guidance here and runtime behaviour guidance there.

## Start here

1. Read `README.md`, `CONTRIBUTING.md` and `KNOWN_LIMITATIONS.md`, then the guide
   under `docs/` for the area you are changing.
2. Inspect `git status --short`, the current diff and relevant implementation
   before editing. Preserve existing user changes; do not reset or overwrite them.
3. State the requested outcome and the evidence that will demonstrate it.
   Follow the user's task; the outstanding work below is context, not permission
   to start unrelated changes.
4. Make a focused change, run the relevant checks below, and report what actually
   passed. Update documentation when behaviour or commands change.

## What this project is

A portable, sanitised OpenClaw + Open WebUI distribution for x86-64 Linux and
WSL2, with optional Skills, semantic memory, voice and a Podman Jupyter runtime.
The core chat path is Open WebUI → local adapter → OpenClaw → selected provider.
Ollama and LLM weights are supplied separately. Memory imports support retrieval;
they do not train the language model.

Read `VERSION` for release status and `manifests/versions.json` for authoritative
compatibility pins. Currently OpenClaw is **2026.7.1-2**, Open WebUI is **0.11.0**,
Python requires **3.11+**, and the bundled Node runtime is **22.22.0**.
OpenClaw 2026.8.1 was deliberately excluded. Do not change pins as routine cleanup:
an upgrade needs explicit scope, patch compatibility checks and real acceptance
testing. A source checkout rollback does not undo package or database migrations.

## Where to work

| Task | Entry points |
| --- | --- |
| Linux/WSL installation and preservation | `tools/install.py`, `install-linux.sh`, `install-wsl.sh`, `install-wsl.ps1`, `uninstall.sh` |
| CLI, setup and provider selection | `bin/rhizome-stack`, `tools/welcome.py`, `config/`, `docs/FIRST_RUN.md` |
| Chat routing and model discovery | `components/openclaw_openwebui_adapter.py`, `components/openclaw_ollama_model_sync.py`, `components/openwebui-tools/` |
| Import formats, deduplication and index generations | `tools/import_formats.py`, `tools/import_owner_data.py`, `tools/initialise_empty_memory.py`, `docs/MEMORY.md` |
| Memory retrieval and OpenClaw plugin | `components/query_memory_archive.py`, `components/memory-rhizome/`, `components/sync_openwebui_memory.py` |
| Speech | `components/openwebui_audio_bridge.py`, `components/chatterbox_nano_server.py`, transcription/Whisper components, `components/requirements-voice.txt` |
| Skills installation and provenance | `tools/skills.py`, `components/skills/`, `manifests/skills.json`, `docs/INTEGRATIONS.md` |
| Services and code interpreter | `systemd/`, `containers/jupyter/`, `config/stack.env.example` |
| Upstream patches | `patches/`, `tools/apply_patch_set.py`, `tools/capture_*patches.py` |
| Distribution and verification | `manifests/release-files.json`, `tools/export_release.py`, `tools/build_release.py`, `tools/privacy_audit.py`, `tools/verify_release.py`, `tests/`, `.github/workflows/verify.yml` |

## Invariants to preserve

- Keep private runtime state out of source and releases: no credentials, chats,
  memory contents/indexes, databases, browser profiles, logs, voice references,
  model weights or machine-specific paths. Use synthetic fixtures. Redact receipts
  before publishing them; never weaken the privacy audit to admit private data.
- Keep populated configuration local. Preserve existing `stack.env`, OpenClaw
  settings and workspace notes except for configuration steps explicitly selected
  by the user. Secrets belong outside version control with mode `0600`.
- Installation must remain inspectable and repeatable. Preserve dry-run behaviour,
  existing local skill variants and first-change `.before-rhizome-stack` backups.
  Those backups are not a complete rollback system. Services are staged without
  automatically starting them.
- Repository editing does not authorise modifying a working installation. Inspect
  and back up affected state, explain the concrete change, and obtain permission
  for privileged or destructive operations unless already explicitly authorised.
  Never run a full installer on the owner's machine merely to test a code change.
- Preserve patch hash guards. An unexpected upstream file is a compatibility
  failure to investigate, not a reason to force a patch or remove its checks.
- Bundled Skills are complete, byte-identical snapshots of a pinned upstream
  revision. Do not casually edit them in place. A deliberate refresh must retain
  helpers/references, provenance, licences and updated checksums in
  `manifests/skills.json`. Load a skill only when relevant. Its presence does not
  authorise delegation, messaging or privileged actions.
- Preserve memory import provenance, duplicate origins, stable row ordering,
  locking and complete index generations. Readers must use one coherent snapshot.
  MiniLM L6 and L12 indexes are incompatible despite both having 384 dimensions.
  Do not deserialize untrusted pickle/NPY archives or silently delete old generations.
- Keep optional integrations optional. The Chatterbox add-on overlaps this stack's
  audio units and ports; inspect ownership before combining installers. Core CLI
  start/stop commands do not manage every optional service.
- Preserve upstream attribution and licence boundaries in `LICENSES.md` and
  `third_party/`. Add every new distributable file to
  `manifests/release-files.json`; unlisted files are absent from release exports.

## Checks and honest evidence

Run from the repository root before submitting changes:

```bash
python3 tests/test_static.py
python3 tests/test_behaviour.py
git diff --check
```

The static suite includes syntax, template/patch checks, isolated import/setup
checks, and release export with privacy audit and manifest verification. Behaviour
tests cover formats, imports, model selection and preservation. Add a regression
test for a changed failure mode where it provides meaningful coverage.

The real FAISS storage test skips when dependencies are absent. For storage work,
use an isolated Python environment with the versions in
`.github/workflows/verify.yml` and rerun the behaviour suite. Report skips plainly.
Deterministic-vector FAISS tests do not establish embedding quality. Optional
OpenClaw schema validation also requires the command to be installed; check its
version against the pin before interpreting results.

For release work, export/build outside the source tree to a fresh destination:

```bash
python3 tools/export_release.py --output /tmp/rhizome-stack-release
python3 tools/build_release.py --output-root /tmp/rhizome-stack-build-a
python3 tools/build_release.py --output-root /tmp/rhizome-stack-build-b
```

These commands refuse existing output directories. The builder needs GNU tar and
`zstd`. Compare the two generated archives byte-for-byte before publishing; both
builds must pass privacy and manifest checks. Do not hand-edit generated
`RELEASE-MANIFEST.json`. A source commit is not a published release archive.

For runtime changes, use a disposable target and follow `docs/FIRST_RUN.md` and
`docs/MAINTENANCE.md`. Distinguish the evidence:

| Check | What it establishes |
| --- | --- |
| Static/behaviour suites | The assertions exercised by those tests |
| Installer dry run | Planned actions, without a completed installation |
| `rhizome-stack doctor` | Required commands, files and local configuration |
| `rhizome-stack smoke` | Core HTTP reachability |
| Welcome wizard verification | Selected model appears in the provider catalogue |
| Real browser chat | The actual UI-to-provider inference path |
| Memory, voice or Jupyter acceptance | That particular feature, with its own observed result |

Do not call the stack working solely because a catalogue or health endpoint
responds. Exercise the affected browser/tool path; retain concise, sanitised
receipts. A failed or unavailable check remains failed or unverified.

## Outstanding work when asked to move the project forward

Re-read `KNOWN_LIMITATIONS.md` first; this list is not a separate authoritative
backlog. The current acceptance gap is complete installation and browser testing
on disposable native Linux and actual WSL2. A useful result records the platform,
revision, selected profile/provider, commands, actual chat result, optional
feature checks and failures. Clean dependency installation also needs verification:
the full transitive dependency graph is not locked.

Other documented gaps include WSL GPU setup and combined Chatterbox add-on/stack
acceptance. Scope one task with the user instead of bundling upgrades, dependency
changes and integration work into a general polish pass. Remove a limitation
only when evidence resolves it.

## Finish or hand over

Report what changed, why, checks run with results/skips, and any remaining blocker.
Give a commit or PR link only if it actually exists. If interrupted, leave a short
handover with the current revision, changed files, observed failure, attempted
fixes and exact next action. Keep observations, assumptions and decisions distinct.
Challenge a mistaken premise plainly; evidence matters more than agreement.
