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

Exact upstream notices retained by this distribution are under `third_party/`.
The installer downloads upstream packages instead of republishing complete
package trees or model weights. Hash-guarded patches do not change the licence
of the upstream material they modify.

Open WebUI's current licence includes a branding condition. This project does
not remove or replace Open WebUI branding.
