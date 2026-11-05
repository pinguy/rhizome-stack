# Local tool map

Live state and current documentation beat this reference.

## MiniMax Music 3

- Purpose: create the song and preserve a reproducible recipe.
- Source: `/home/ComfyUI/minimax_app/`
- Chrome app: **MiniMax Music 3** / launcher `minimax-music`
- Loopback UI: `http://127.0.0.1:8830/`
- Output: `/home/ComfyUI/output/minimax_app/`
- Each accepted track should keep its MP3 plus companion JSON recipe and seed/engine metadata.
- The engine starts on demand and unloads after use.

## Qwen Image Desk

- Purpose: storyboard-driven concept art, approved visual bible, character/location references, plates, and controlled reference edits.
- Production plates follow storyboard approval; do not use large image batches to discover the story.
- Source: `/home/ComfyUI/music_video_studio/`
- Chrome app: **Qwen Image Desk**
- Launcher: `/home/pinguy/.local/bin/qwen-image-desk`
- Loopback UI: `http://127.0.0.1:8840/image-studio/`
- Persistent outputs: `/home/pinguy/AI-Music-Video-Studio/projects/qwen-image-studio/`
- Current local art engine: Qwen Image 2.1 through the shared ComfyUI queue.
- Preserve prompts, seeds, dimensions, model provenance, and reference-image relationships.

## Cutroom

- Purpose: song import/analysis, storyboard/rough animatic planning (where implemented), visual bible, shot plan, asset attachment, take review, song-locked timeline, and FFmpeg final render.
- Storyboard source and time-coded animatic must be preserved; check live capabilities before asserting Cutroom supports preview/animatic assembly.
- Source: `/home/ComfyUI/music_video_studio/`
- Projects/state: `/home/pinguy/AI-Music-Video-Studio/`
- Chrome app: **Cutroom**
- Loopback UI: `http://127.0.0.1:8840/`
- Service: `music-video-studio.service`
- Source song is the master clock.
- Successful takes are immutable; project JSON autosaves atomically.

## WAN 2.2

- Intended purpose: local T2V/I2V camera backend.
- Status at proposal creation: not yet installed/qualified for this workflow.
- Required integration: a Cutroom camera adapter accepting mode, prompt, negative guidance, optional reference, dimensions, frame count, and seed; it must return a playable local file plus immutable provenance.
- Never mark it ready from model files alone. Pass the readiness gate in SKILL.md on the actual box.

## Explicitly excluded defaults

- OpenRouter/Veo was removed and is not a fallback.
- The BLISS document's Midjourney, Suno, and Seedance/Higgsfield stack is reference history, not the local implementation.
- Existing Cutroom video backends do not become this skill's default merely because they are present.
