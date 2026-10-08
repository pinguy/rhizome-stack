# Licensing and provenance

Rhizome Stack is a packaging and integration project, not a claim of original
authorship over OpenClaw, Open WebUI or the other projects it connects.

| Material | Licence | Upstream |
|---|---|---|
| Original installer, wizard, importers, glue and documentation | MIT (`LICENSE`) | This repository |
| `patches/openclaw/` and OpenClaw-derived integration behaviour | MIT | https://github.com/openclaw/openclaw |
| `patches/open-webui/` and Open WebUI-derived modifications | Open WebUI multi-licence terms | https://github.com/open-webui/open-webui |
| Chatterbox integration and upstream source installed at runtime | MIT | https://github.com/resemble-ai/chatterbox |
| faster-whisper installed dependencies | MIT | https://github.com/SYSTRAN/faster-whisper |
| Ollama integration | MIT | https://github.com/ollama/ollama |
| Twelve unmodified upstream skill directories under `components/skills/` | Apache-2.0 (`third_party/skills-LICENSE`) | https://github.com/pinguy/Skills |
| Owner-supplied `ornith-research-workforce` and `openclaw-downstream-maintainer`, with stack adaptations | MIT (`LICENSE`) | Owner-supplied archive; per-entry provenance in `manifests/skills.json` |
| Optional GLiNER2 library and GLiNER2.5-Decide weights | Apache-2.0 upstream terms; weights are not bundled | https://github.com/fastino-ai/GLiNER2 and https://huggingface.co/fastino/GLiNER2.5-Decide |
| ComfyUI installed at runtime | GPL-3.0 | https://github.com/Comfy-Org/ComfyUI |
| ComfyUI-GGUF installed at runtime and one-line compatibility patch | Apache-2.0 | https://github.com/city96/ComfyUI-GGUF |
| Qwen Image 2.1 model files | Qwen Research licence; weights are not bundled | https://huggingface.co/Comfy-Org/Qwen-Image-2.1 |
| Qwen Image 2.1 Uncensored GGUF | Repository terms; weights are not bundled | https://huggingface.co/abenzerps/Qwen-Image-2.1-Uncensored-GGUF |
| MiniMax Music 3 ComfyUI model files | Apache-2.0 repository terms; weights are not bundled | https://huggingface.co/Comfy-Org/MiniMax-Music-3 |
| sentence-transformers/all-MiniLM-L6-v2 | Apache-2.0; weights are downloaded separately | https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 |

The upstream Skills snapshot is pinned to a full commit and every bundled skill file is
SHA-256 checked by `manifests/skills.json`. Keep the complete directories and
their Apache notice together when redistributing them. The original MIT grant
does not relicense those upstream files. Per-entry provenance/licence fields
override the manifest-level upstream defaults for the two additional skills.

RhizomeML is a companion pipeline. The stack reads its JSON/JSONL interchange
formats; it does not bundle its training code, dependencies or private indexes.
The reviewed source commit and integration boundary are in
[docs/INTEGRATIONS.md](docs/INTEGRATIONS.md).

Exact upstream notices retained by this distribution are under `third_party/`.
The installer downloads upstream packages instead of republishing complete
package trees or model weights. Hash-guarded patches do not change the licence
of the upstream material they modify.

Open WebUI's current licence includes a branding condition. This project does
not remove or replace Open WebUI branding.
