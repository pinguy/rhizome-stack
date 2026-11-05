# Local tool map

Live state and current documentation beat this reference. Paths and readiness below are recorded from the user's supplied map, not newly verified on the workstation.

## Storyboard artifacts (project-local, no new service assumed)

- Purpose: **make the visual plan visible before production**. Storyboards are not merely a text shot list.
- Place under a project's root, e.g. `storyboard/concept-v01/` and `storyboard/timed-v01/`.
- Each version holds numbered panel images, an ordered contact sheet, a panel/shot table, revision metadata, and optionally a song-locked animatic.
- Draft panels may be rough hand sketches, local diagrams, placeholders or bounded Qwen Image drafts. They are **not** final plates.
- The timed board records exact song in/out, beat/lyric anchors, transitions and shot IDs; a Cutroom shot should reference that ID and panel path.
- Do not assume Cutroom has an illustrated storyboard editor or animatic generator until tested. If it does not, keep storyboard/animatic creation in project-local scripts and import or link shot references through available Cutroom functionality.
- See `../templates/storyboard-template.md` and `../templates/production-manifest.md`.

## MiniMax Music 3

- Purpose: create a song and preserve a reproducible recipe.
- Source: `/home/ComfyUI/minimax_app/`
- Chrome app: **MiniMax Music 3** / launcher `minimax-music`
- Loopback UI: `http://127.0.0.1:8830/`
- Output: `/home/ComfyUI/output/minimax_app/`
- Each accepted track retains MP3 plus companion JSON recipe and seed/engine metadata.
- Engine starts on demand and unloads after use.
- The accepted song's actual audio timings supersede provisional concept-board timings.

## Qwen Image Desk

- Purpose: bounded draft concept panels, visual bible, character/location references, plates and controlled edits.
- Source: `/home/ComfyUI/music_video_studio/`
- Chrome app: **Qwen Image Desk**
- Launcher: `/home/pinguy/.local/bin/qwen-image-desk`
- Loopback UI: `http://127.0.0.1:8840/image-studio/`
- Persistent outputs: `/home/pinguy/AI-Music-Video-Studio/projects/qwen-image-studio/`
- Recorded local art engine: Qwen Image 2.1 through shared ComfyUI queue.
- Preserve prompts, seeds, dimensions, provenance, reference paths and concept/timed storyboard shot ID mapping.
- Don't burn GPU time creating final-quality plates before `TIMED_BOARD_LOCKED`.

## Cutroom

- Purpose: song import/analysis, visual bible, shot plan, asset/take review, song-locked timeline and FFmpeg final render.
- Source: `/home/ComfyUI/music_video_studio/`
- Projects/state: `/home/pinguy/AI-Music-Video-Studio/`
- Chrome app: **Cutroom**
- Loopback UI: `http://127.0.0.1:8840/`
- Service: `music-video-studio.service`
- Source song is the master clock.
- Successful takes are immutable; project JSON autosaves atomically.
- Bridge to storyboard: carry stable shot IDs, timed in/out and panel path into existing shot records. Verify feature support on the live installation; if absent, retain an external storyboard table as source of truth rather than claiming a built-in feature.

## MiniMax H3 · NF4 Turbo + Sol + Spectrum

- **Video engine, not MiniMax Music 3**: local H3 FL2VA, tested on the HP Z440 / RTX 3060 12GB.
- **Recorded modes**: text-to-video and **first-frame** image-to-video, both producing **native stereo audio** in prior tests.
- **Sampler**: **4–24 steps**; **8 steps default**. Preserve the chosen steps, seed and model/adapter versions with every take.
- **Optimisation**: NF4 Turbo + Sol + Spectrum. Earlier test records showed accelerated GPU text conditioning with a CPU fallback, but verify the current service/settings before relying on this.
- **State distinction**: engine generation has been demonstrated; current **Cutroom adapter/import and final-render handoff are not verified by these documents**. Never regress to WAN solely because a stale proposal mentions it.
- **Integration**: map each generated file and optional first-frame reference to a `TIMED_BOARD_LOCKED` shot ID; preserve prompt, negative, seed, steps, exact model/LoRA state, dimensions, FPS/frame count, audio stream information, timing, file hash, source job ID and accepted/rejected decision.
- **Audio contract**: the music-video soundtrack is the locked MiniMax Music 3 song. H3's native audio belongs to its video take, preserved as a separate track and **muted by default** unless an explicit sound-design decision selects it.
- **Local runner/paths**: find from live installed H3 / Video Desk configuration before invoking. No unverified port, executable, ComfyUI workflow filename or Cutroom API is fabricated here.
- **Cutroom gate**: verify real file handoff and kept-take render. If unverified mark `CUTROOM_INTEGRATION_PENDING`, not `VIDEO_BACKEND_PENDING`.

## H3 1080p finishing — Real-ESRGAN → Lanczos

- **Provided source:** `scripts/h3_lanczos_1080p.sh` (identical bytes to the supplied `h3_lanczos_1080p(1).sh`). The **installed workstation path is not yet verified**; copy/install in a user-approved location and record the actual path and SHA-256.
- **Default path:** Cutroom assembles a high-quality song-locked intermediate → sample 2-second upscale preview → visually approve → whole-master upscale → final 1080p QC. For crisp deterministic type or composited graphics, upscale approved H3 picture clips **before** final Cutroom overlay/render instead, and do not upscale the same picture twice.
- **Default method:** `realesrgan-ncnn-vulkan`, `realesrgan-x4plus`, native `-s 4`; Lanczos shrink/fit/pad to **1920×1080**; H.264/x264 slow/CRF 17; source audio bitstream copied. The script supports other bundled model names but they require actual model files and should be documented by run.
- **GPU:** NCNN/Vulkan ID (not CUDA ID); prefer RTX 3060 only after verifying the startup log; `--list-gpus` and `--gpu ID` are available. Its GPU detection is best-effort.
- **Fallback:** `--mode lanczos` is CPU-only conventional resampling; not neural enhancement. Record explicitly when chosen.
- **Preview:** `--seconds 2` with a unique preview filename; check tiles/zoom, face/detail consistency, video duration/fps and audio sync. Native 4× avoids the documented `x4plus -s 2` tiled corruption issue.
- **Disk/memory:** large PNG sequences are created under `H3_TMP_DIR` or the output directory; ensure sufficient free disk and serialise Vulkan jobs with other GPU work. No overwrite of existing output. Source unchanged.
- **Readiness:** `bash -n` validates shell syntax only. A real NCNN models/binary test and a Cutroom→upscale→QC run on the user's workstation have **not** been verified here.

## Explicitly excluded defaults

- OpenRouter/Veo was removed and is not a fallback.
- BLISS's Midjourney, Suno and Seedance/Higgsfield stack is reference history, not the local implementation.
- WAN 2.2 is historical/optional, not the default. Existing Cutroom video backends do not become this skill's default merely because they are present.
