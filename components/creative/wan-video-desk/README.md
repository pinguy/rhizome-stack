# WAN Video Desk

WAN Video Desk is a loopback-only browser app for local WAN 2.2 Rapid video
generation through the stack's pinned ComfyUI installation.

## Controls

- **Input:** Text or Image.
- **Model:** either exact installed Rapid v10 Q5_K GGUF.
- 480p or 720p output in 16:9, 4:3 or mobile 9:16.
- 1–10 whole seconds at 16 or 24 FPS.
- 4–20 sampling steps and one to four queued takes.
- Optional OpenClaw prompt expansion, editable final prompt and negative guidance.
- Persistent local gallery with playback, reuse, same-seed reruns, download,
  show-in-folder and Trash-based deletion.

Input and model are separate choices. A choice never silently rewrites the
other. The selected model must support the selected input: image input requires
the I2V model and a locally uploaded PNG, JPEG or WebP reference.

## Runtime boundary

The app starts only the exact ComfyUI process it owns, tracks its PID and process
group, and releases it after the configured idle period. It does not use broad
process killing. `COMFY_CUDA_VISIBLE_DEVICES` may be set in the local stack
environment when a host needs an explicit CUDA device order; no reference-machine
GPU identifier is bundled.

Generated projects, references, MP4 files, logs, model weights and queue state
remain under the installed stack's runtime directory. None are part of the
release archive.

## Models

`--download-creative-models` downloads hash-verified copies of:

- `wan2.2-t2v-rapid-aio-v10-nsfw-Q5_K.gguf`
- `wan2.2-i2v-rapid-aio-v10-nsfw-Q5_K.gguf`
- `umt5-xxl-encoder-Q4_K_M.gguf`
- `wan_2.1_vae.safetensors`
- `clip_vision_h.safetensors`

The blobs are downloaded on the target machine and are not redistributed in
Rhizome Stack.
