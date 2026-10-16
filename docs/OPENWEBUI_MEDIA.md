# Qwen, MiniMax and WAN inside Open WebUI

The creative profile connects Qwen Image Desk, MiniMax Music 3 and WAN Video
Desk to ordinary saved Open WebUI chats while safely sharing one local GPU with
Ollama.

## What the integration does

The local model can call:

- `qwen_image.create_image` to generate a PNG or edit an uploaded image;
- `minimax_music_3.create_song` to generate an MP3; and
- `wan_video.create_video` to generate a text-to-video MP4 or condition one on
  an uploaded image.

PNGs render inline. MP3s use Open WebUI's native File card and Preview player.
MP4s are durable file attachments rendered by the pinned Open WebUI 0.11.0
frontend patch as an inline HTML5 `<video controls>` player. Every completed WAN
take also remains in WAN Video Desk with its generation settings and provenance,
so it can be inspected, downloaded, rerun or used as the basis for another take.

## Runtime flow

```text
saved Open WebUI chat
  -> packaged Qwen, MiniMax or WAN tool
  -> shared generation lock
  -> refuse if ComfyUI or another media job is busy
  -> unload every Ollama runner with keep_alive=0
  -> wait until Ollama /api/ps is empty
  -> start the selected packaged generator on demand
  -> submit generation exactly once
  -> retry only read-only status polling
  -> free ComfyUI models and stop the engine owned by that application
  -> wait until the ComfyUI port is closed
  -> copy the result into Open WebUI's upload store
  -> create the Open WebUI file row and attach it to the saved message
  -> return to model continuation; Open WebUI reloads the local chat model
```

The durable receipt under
`~/.local/share/rhizome-stack/state/openwebui-media-jobs/` prevents an
uncertain submission from being blindly repeated. Receipts are private files
(mode `0600`) written atomically and flushed to disk. The completed output path
is saved before ComfyUI is stopped, allowing a repeated invocation with the same
user, chat, message and arguments to recover an attachment failure without
submitting another generation. Changing the message or arguments creates a new
request; this is not an automatic retry across different chat turns.

## Install and register

Install the creative profile and its verified model files:

```bash
./install-linux.sh --with-creative --download-creative-models
```

After creating the first local Open WebUI administrator, create an API token,
place only the token in a mode-0600 file, and register the packaged tools:

```bash
install -m 600 /dev/null ~/.config/rhizome-stack/openwebui-admin.token
${EDITOR:-vi} ~/.config/rhizome-stack/openwebui-admin.token
python3 ~/.local/share/rhizome-stack/tools/register_openwebui_tools.py \
  --token-file ~/.config/rhizome-stack/openwebui-admin.token
```

The relevant registered IDs are `qwen_image`, `minimax_music_3` and
`wan_video`. The pinned Open WebUI patch attaches them to default model metadata
and gives the model explicit routing instructions for image, song and video
creation. A separate hash-guarded replacement modifies only the pinned generated
frontend chunk needed to render `video/mp4` attachments inline. Open WebUI
updates require that replacement and all normal image/file branches to be
re-derived and browser-tested against the new build.

## Use from chat

Examples:

- “Create a square Qwen image of a ceramic fox mug on a café table.”
- Attach an image, then ask: “Edit this image so the chair is yellow; preserve
  the rest of the scene.”
- “Create a 30-second instrumental synthwave track called Neon Drive Home.”
- “Create a five-second 4:3 video of waves rolling over black volcanic sand.”
- Attach an image, then ask: “Animate this as a subtle five-second WAN video.”

Qwen edits and WAN image-to-video requests accept only a PNG, JPEG or WebP file
owned by the authenticated Open WebUI user and no larger than 20 MiB. The tools
pass the owned Open WebUI file ID, never an arbitrary filesystem path or remote
URL. WAN defaults to T2V v10 Q5_K, 640×480 (4:3), 480p, 16 FPS, four steps and
five seconds unless the caller deliberately overrides a supported setting.

## Failure boundaries

- Media calls are serialised; active work is not interrupted.
- Only a refused connection counts as an offline service. HTTP errors,
  timeouts and malformed health or queue responses block hand-off or report
  cleanup failure; they are not evidence that the engine is idle or stopped.
- Ollama must return a valid runner list both before unloading and while
  checking that the GPU is free. A missing or malformed list blocks hand-off.
- Generation submission is not automatically retried.
- A failed or timed-out job is reported as a failure, never as a created file.
- Result paths must remain under the selected packaged application's output
  directory.
- Only the ComfyUI process owned by the selected packaged application is
  stopped.
- Open WebUI file ownership and saved-chat attachment APIs remain authoritative.
- WAN uses the accepted 64/16 tiled temporal decoder normally. On decoder OOM
  it tries 48/12 first for better luminance consistency, then 32/12 only as the
  tighter-memory fallback. Other errors are not retried through this ladder.

The standalone desks remain useful for manual control, but they and the
Open WebUI tools use the same local services and model files.

See [the browser showcase](SHOWCASE.md) for captured reference-machine evidence
of all three desks plus Open WebUI's inline PNG, native MP3 Preview and patched
inline MP4 player. The screenshots contain no user database, generated media
files or credentials; those remain excluded runtime state.
