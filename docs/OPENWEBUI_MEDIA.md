# Qwen and MiniMax inside Open WebUI

The creative profile ships more than the standalone Qwen Image Desk and
MiniMax Music 3 pages. It also connects both generators to ordinary Open WebUI
chats while safely sharing one local GPU with Ollama.

## What the integration does

From a saved Open WebUI chat, the local model can call:

- `qwen_image.create_image` to generate a PNG or edit an uploaded image; and
- `minimax_music_3.create_song` to generate an MP3.

Finished PNGs are stored as Open WebUI image attachments and render inline.
Finished MP3s are stored as native file attachments, so the saved chat keeps
Open WebUI's File card and built-in Preview player after a reload. The tools do
not emit temporary paths or raw HTML players as the user-facing result.

## Runtime flow

```text
saved Open WebUI chat
  -> packaged Qwen or MiniMax tool
  -> shared generation lock
  -> refuse if ComfyUI or another media job is busy
  -> unload every Ollama runner with keep_alive=0
  -> wait until Ollama /api/ps is empty
  -> start Qwen Image Desk or MiniMax Music 3 on demand
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

The relevant registered IDs are `qwen_image` and `minimax_music_3`.
The pinned Open WebUI patch attaches them to the default model metadata and
adds the routing instruction that distinguishes an actual creation request
from ordinary discussion.

## Use from chat

Examples:

- “Create a square Qwen image of a ceramic fox mug on a café table.”
- Attach an image, then ask: “Edit this image so the chair is yellow; preserve
  the rest of the scene.”
- “Create a 30-second instrumental synthwave track called Neon Drive Home.”

Qwen edits accept only an image upload owned by the authenticated Open WebUI
user and no larger than 20 MiB. The tool passes the owned Open WebUI file ID,
never an arbitrary filesystem path or remote URL.

## Failure boundaries

- Media calls are serialised; active work is not interrupted.
- Only a refused connection counts as an offline service. HTTP errors,
  timeouts and malformed queue responses block hand-off or report cleanup
  failure; they are not evidence that the engine is idle or stopped.
- Generation submission is not automatically retried.
- A failed or timed-out job is reported as a failure, never as a created file.
- Result paths must remain under the configured ComfyUI output directory.
- Only the ComfyUI process owned by the selected packaged application is
  stopped.
- Open WebUI file ownership and saved-chat attachment APIs remain
  authoritative.

The standalone desks remain useful for manual control, but they and the
Open WebUI tools use the same local services and model files.
