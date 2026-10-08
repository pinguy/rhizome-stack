# Optional creative setup

The creative profile installs a separate pinned ComfyUI checkout under
`$RHIZOME_STACK_ROOT/creative/ComfyUI`. It adds two loopback-only browser apps:

- Qwen Image Desk at `http://127.0.0.1:8841/image-studio/`
- MiniMax Music 3 at `http://127.0.0.1:8830/`

Cutroom is not part of this package. Its source, LTX/video workflows, projects,
outputs, logs and reference-machine state are excluded.

## Install

Preview first. Model downloads are large and remain optional:

```bash
./install-linux.sh --dry-run --with-creative
./install-linux.sh --with-creative
./install-linux.sh --with-creative --download-creative-models
```

The installer checks out ComfyUI commit
`af89add63f71a487fde45efc7fba744f3455ae73` and ComfyUI-GGUF commit
`6ea2651e7df66d7585f6ffee804b20e92fb38b8a`. A hash-guarded one-line patch
admits the `qwen_image21` GGUF architecture. Current ComfyUI supplies native
Qwen Image 2.1 and MiniMax Music 3 nodes.

Every optional model URL uses an immutable Hugging Face revision. The downloader
resumes partial transfers and refuses any file whose SHA-256 differs from
`manifests/creative-models.json`.

## Run

```bash
rhizome-stack creative qwen
rhizome-stack creative minimax
rhizome-stack creative status
rhizome-stack creative stop
```

Both apps start ComfyUI on demand at `127.0.0.1:8188`. They may reuse an
already-running endpoint, but they never stop a process they do not own. Owned
engines are tracked by exact PID, command and process group; no broad `pkill`
fallback exists. Generated files stay under the installed ComfyUI output tree.

Qwen Image Desk can optionally use the installed OpenClaw catalogue to expand a
rough prompt before local generation. MiniMax can use OpenClaw or Ollama to fill
a musical brief. Those helpers are optional; direct prompts still work.

Qwen also accepts a local PNG, JPEG or WebP reference up to 20 MB. The reference
is normalised into the Desk's private state directory and passed through Qwen
Image 2.1's native image-conditioning path. Saved assets retain the reference
provenance so **Reuse** and same-seed reruns remain edits rather than silently
falling back to text-to-image.

After registering the packaged `qwen_image` and `minimax_music_3` Open WebUI
tools, explicit image/music creation requests can use these same applications
from an ordinary saved chat. The shared bridge serialises generation, refuses
to interrupt an active ComfyUI job, unloads idle Ollama runners, then frees and
stops only the ComfyUI process owned by the selected app. PNGs are attached
inline; MP3s use Open WebUI's native file card and Preview player. Qwen edits
accept only an image upload owned by the authenticated Open WebUI user.

## Hardware and WSL2

The selected Q8/int8 model set targets a practical local NVIDIA setup but is not
small. CUDA driver compatibility, VRAM capacity and WSL GPU passthrough are host
responsibilities. Treat a healthy web page as staging only: generate one image
and one audio file before calling the target accepted.

## Input and output boundaries

MiniMax validates generation settings before starting ComfyUI: 8–300 seconds,
8–60 steps, guidance 1–6, top-k 1–1000, and a non-negative 64-bit integer seed
(or `random`). Its JSON requests and Qwen's are limited to 128 KiB. Invalid
settings return HTTP 400 with an explanation.

Audio downloads and recipe operations must stay inside the ComfyUI output tree;
absolute paths, parent traversal and symlinks escaping that tree are rejected.
Titles, filenames and errors are rendered as text in the MiniMax UI. WAV and
FLAC downloads retain their correct content types.

Closing a browser tab does not stop ComfyUI. Use the in-app **Stop engine**
button or configure `COMFY_IDLE_SECONDS` for automatic idle shutdown.

The chat bridge records a durable request receipt before submission and refuses
to replay an ambiguously acknowledged generation.
