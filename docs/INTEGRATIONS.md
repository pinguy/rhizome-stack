# Skills and companion projects

The stack connects the useful pieces of these projects while keeping their
runtimes and ownership clear.

| Project | Integration here | Boundary |
| --- | --- | --- |
| [Skills](https://github.com/pinguy/Skills) | All twelve complete skill directories, including helpers and references, shipped at a pinned revision | Installing a skill does not start its workflow or grant extra permissions |
| [RhizomeML](https://github.com/pinguy/RhizomeML) | Imports its detailed/compact JSONL and PDF JSON formats with provenance | Training code, dependencies, model weights and existing private indexes stay separate |
| [Chatterbox TTS add-on](https://github.com/pinguy/chatterbox-tts-addon) | Companion browser extension/Voice Lab and canonical recovery skill | Its installer overlaps this stack's audio service names and ports |
| [GGUF Converter Studio](https://github.com/pinguy/GGUF-Converter-Studio) | Prepare a GGUF, then select it through the welcome wizard's advanced Ollama route | Conversion/build dependencies stay in the converter environment |

## Skills

```bash
rhizome-stack skills list
rhizome-stack skills install --profile core --dry-run
rhizome-stack skills install --profile core
rhizome-stack skills install --profile all
rhizome-stack skills install council-blackboard
```

The core profile contains:

- `check-notes-first`
- `invariant-guarded-debugging`
- `openwebui-regression-test`
- `privileged-operations`
- `risk-aware-retry`
- `session-handover`

Extras are blackboard, council-blackboard, local-model-runtime-profiler,
chatterbox-tts-recovery, symlink-space-saver and video-clip-editor.
Selecting council-blackboard also selects its blackboard dependency.

The installer reads the default workspace from your OpenClaw config and copies
skills into its `skills/` directory. Override it for another agent:

```bash
rhizome-stack skills install --workspace ~/agent-workspace --profile core
```

Complete directories matter: blackboard and council include executable helpers
alongside their instructions. Every source file is checked against the bundled
SHA-256 manifest before installation. Existing identical skills are left alone;
different local versions are preserved and reported, with exit status 1.
Compare them with `components/skills/` before replacing them manually.

Open a new agent session after installation. Discovery should expose the skill
name and description, with full instructions loaded only when relevant. See
[OpenClaw skill discovery](https://docs.openclaw.ai/tools/skills) for workspace
scope and precedence. This package does not automatically start a council,
send messages, run privileged commands or turn on every specialist tool.

## RhizomeML

The integration was checked against its actual parsers and dataset writers,
not just the overview:

- `batch_embedder.py`: conversation metadata and archive outputs.
- `pdf_to_json.py`: filename, per-page text and combined text.
- `data_formatter.py`: detailed pairs and compact training records.

See [memory import and index compatibility](MEMORY.md). Importing plain-text
interchange data avoids dragging the training environment into the agent
runtime. Themes and quality scores are retained as supplied metadata; the stack
does not claim to have independently verified them.

## Chatterbox

The add-on brings Firefox/Chromium speech controls and Voice Lab. Both projects
use `openwebui-audio-bridge.service`, with bridge port 8010 and CPU synthesis
port 8020. Running both backend installers on the same account can replace
service definitions or cause port conflicts.

Choose one backend owner. Inspect the add-on's current instructions, existing
unit files and endpoint capabilities before sharing it with the stack. The
stack has not adopted the add-on's entire 4.2 backend in this release, and the
two browser/backend paths have not been tested together here.

## GGUF conversion

Use Converter Studio in its own environment, retain the produced GGUF, then
choose the GGUF option in `rhizome-stack welcome`. The wizard creates an Ollama
model using that file and checks that the resulting model is listed. Conversion
support and quantisation depend on the source model; a valid file alone does
not verify chat or tool calling. See the [Ollama Modelfile reference](https://docs.ollama.com/modelfile).

## Reviewed revisions

| Repository | Revision used |
| --- | --- |
| Skills | `41335012d5000dd29d9477c963a6ee1ff0333aba` |
| RhizomeML | `746223badfa946f15dd955c03616624e5a31026b` |

Skills are vendored byte-for-byte with Apache-2.0 retained under
`third_party/skills-LICENSE`. The complete file checksums and core/extra grouping
are in `manifests/skills.json`. Companion tools are linked, not automatically
downloaded or installed.
