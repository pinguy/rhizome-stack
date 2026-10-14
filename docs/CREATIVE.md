# Optional creative setup

The creative profile installs a separate pinned ComfyUI checkout under
`$RHIZOME_STACK_ROOT/creative/ComfyUI`. It adds three loopback-only browser apps:

- Qwen Image Desk at `http://127.0.0.1:8841/image-studio/`
- MiniMax Music 3 at `http://127.0.0.1:8830/`
- WAN Video Desk at `http://127.0.0.1:8840/video-studio/`

Cutroom is not part of this package. Its source, LTX workflows, projects,
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
rhizome-stack creative wan
rhizome-stack creative status
rhizome-stack creative stop
```

All three apps start ComfyUI on demand at `127.0.0.1:8188`. They may reuse an
already-running endpoint, but they never stop a process they do not own. Owned
engines are tracked by exact PID, command and process group; no broad `pkill`
fallback exists. Qwen and MiniMax outputs stay under the installed ComfyUI
output tree. WAN also retains each completed MP4 under
`$RHIZOME_STACK_ROOT/creative/state/wan-video-desk/projects/wan-video-studio/generated/`
(or the configured `WAN_DESK_STATE` directory).

Qwen Image Desk can optionally use the installed OpenClaw catalogue to expand a
rough prompt before local generation. MiniMax can use OpenClaw or Ollama to fill
a musical brief. WAN Video Desk can use the same catalogue to expand a motion
prompt. Those helpers are optional; direct prompts still work.

WAN Video Desk keeps Input (`Text` or `Image`) and the exact selected GGUF as
separate controls. Image input requires an uploaded reference and the I2V model;
the application never silently changes either choice. It offers 480p/720p,
16:9/4:3/mobile formats, 16 or 24 FPS, 1–10 seconds and 4–20 steps. Completed
MP4 files remain in its local gallery with full generation provenance.
Fixed-seed batches increment the seed for each take, including seed zero.
A batch that would exceed the maximum seed is rejected before queue insertion.
Both WAN modes use the accepted 64/16 temporal decoder. A decoder-only
out-of-memory failure retries at 48/12 first to preserve luminance consistency,
then at 32/12 for tighter memory. Other failures do not enter that ladder.

Qwen also accepts a local PNG, JPEG or WebP reference up to 20 MB. The reference
is normalised into the Desk's private state directory and passed through Qwen
Image 2.1's native image-conditioning path. Saved assets retain the reference
provenance so **Reuse** and same-seed reruns remain edits rather than silently
falling back to text-to-image.

After registering the packaged `qwen_image`, `minimax_music_3` and `wan_video`
Open WebUI tools, explicit image, music and video creation requests can use these applications
from an ordinary saved chat. The shared bridge serialises generation, refuses
to interrupt an active ComfyUI job, unloads idle Ollama runners, then frees and
stops only the ComfyUI process owned by the selected app. PNGs are attached
inline; MP3s use Open WebUI's native file card and Preview player; MP4s use the
pinned inline HTML5 player and remain editable in WAN Video Desk. Qwen edits and
WAN image-to-video requests accept only an image upload owned by the
authenticated Open WebUI user.

## Hardware and WSL2

The selected Q8/int8/Q5_K model set targets a practical local NVIDIA setup but is not
small. CUDA driver compatibility, VRAM capacity and WSL GPU passthrough are host
responsibilities. Treat a healthy web page as staging only: generate one image,
one audio file and one short video before calling the target accepted.

## Input and output boundaries

MiniMax validates generation settings before starting ComfyUI: 8–300 seconds,
8–60 steps, guidance 1–6, top-k 1–1000, and a non-negative 64-bit integer seed
(or `random`). Its JSON requests and Qwen's are limited to 128 KiB. Invalid
settings return HTTP 400 with an explanation.

WAN validates its model/input pairing, reference ownership, 1–10 second length,
16/24 FPS, 4–20 steps, dimensions and seed before queue insertion. Its JSON
requests are limited to 16 MiB and image references to 20 MiB.

Audio downloads and recipe operations must stay inside the ComfyUI output tree;
absolute paths, parent traversal and symlinks escaping that tree are rejected.
Titles, filenames and errors are rendered as text in the MiniMax UI. WAV and
FLAC downloads retain their correct content types.

Closing a browser tab does not stop ComfyUI. Use the in-app **Stop engine**
button or configure `COMFY_IDLE_SECONDS` for automatic idle shutdown.

The chat bridge records a durable request receipt before submission and refuses
to replay an ambiguously acknowledged generation.
