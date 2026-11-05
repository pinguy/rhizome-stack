# Rhizome creative tool map — unified v3

**Grounding:** supplied `CREATIVE(1).md` and `OPENWEBUI_MEDIA(1).md` describe Rhizome Stack alpha.18's *packaged* creative profile; `rhizome-stack(10).zip` contains the matching Cutroom source README. Historical user-provided skill/patch files describe older standalone installations. **No part of this map is an assertion about processes currently running on the Z440.** Check the active installation before use.

## Current packaged interface (loopback only)

| App | Packaged UI / service | Launch | Role |
| --- | --- | --- | --- |
| MiniMax Music 3 | `http://127.0.0.1:8830/` | `rhizome-stack creative minimax` | New songs / recipes |
| Qwen Image Desk (Qwen Image 2.1) | `http://127.0.0.1:8841/image-studio/` | `rhizome-stack creative qwen` | Concept panels, references, controlled edits |
| Video Desk (WAN and MiniMax H3) | `http://127.0.0.1:8840/video-studio/` | `rhizome-stack creative wan` | Video generation, gallery, Screening Room |
| Cutroom | `http://127.0.0.1:8842/` | `rhizome-stack creative cutroom` | Song-first storyboard/shot plan, take review and timeline |
| Cutroom internal backend | `127.0.0.1:8843` | started with Cutroom | Not a public-facing remote API |
| Shared ComfyUI | `127.0.0.1:8188` | on demand | Image/audio/WAN generation queue; engine ownership matters |

Command hints: `rhizome-stack creative status`, `rhizome-stack creative stop`. These are **not instructions to stop an unrelated running engine**. Check ownership and active jobs first. The `creative wan` command starts Video Desk despite its historical name; **H3 is selected within Video Desk or by passing the appropriate model to its registered tool**.

**Packaged workspace:** `$RHIZOME_STACK_ROOT/creative/ComfyUI`; Cutroom defaults to `$RHIZOME_STACK_ROOT/creative/state/cutroom`, and Video Desk retains files under `$RHIZOME_STACK_ROOT/creative/state/wan-video-desk/projects/wan-video-studio/generated/` unless `WAN_DESK_STATE` overrides it. Do not assume `/home/ComfyUI/` or older `/home/pinguy/AI-Music-Video-Studio/` paths still exist: they belong to a different installation vintage.

## Tool and model contracts

**Open WebUI saved chats** can expose `qwen_image.create_image`, `minimax_music_3.create_song` and `wan_video.create_video`. The **H3 generation path uses `wan_video.create_video` with the exact H3 model selection**; there is no confirmed standalone `h3.create_video` chat tool. The tool uses an authenticated upload ID for reference images, not arbitrary filesystem paths or remote URLs. The actual tool registration may be missing on a fresh install.

- **MiniMax Music 3:** 8–300 s song duration, 8–60 steps, 1–6 guidance, 1–1000 top-k (packaged validator). Preserve MP3, recipe, seed, sample metadata and hash.
- **Qwen Image 2.1:** standalone generates/edits; source image PNG/JPEG/WebP up to 20 MiB as documented; preserve selected reference and edit provenance. Check its active model before relying on exact seed behaviour.
- **MiniMax H3 (FL2VA pruned NF4 DiffSynth):** **Text** or **first-frame image** input; **1–15 s**, fixed **24 FPS**, **4–50 steps**, documented Open WebUI **20-step default**; native **32 kHz stereo audio**, required `17n+5` frame sequence. Four NF4 weights plus seven processor files (~26 GB), all package-revision/hash pinned. A historical local fast setting was **8 steps** (not the current default). Record NF4/Turbo/Sol/Spectrum settings actually activated and exact model revision. The long chat-tool poll bound is **6 h**; never mistake a long run for completion.
- **WAN 2.2 (optional):** Text or image with compatible specific GGUF, 1–10 s, 16 or 24 FPS, 4–20 steps; tiled decoder 64/16, on decoder-only OOM 48/12 then 32/12. Does not silently replace H3 when H3 integration needs work.
- **Resource handoff:** shared generation lock, idle Ollama unload, wait for empty `/api/ps`, one submission, read-only polling, stop **owned** ComfyUI only, wait for port close. A failed/unreadable health/queue endpoint is a failure, never proof of availability. Stable saved-chat message ID or explicit idempotency key is required by the bridge.

## Cutroom is separate from engine readiness

Cutroom ships a React UI/proxy plus Python backend, project state and FFmpeg renderer. A UI page loading is **not** proof that a selected H3 clip can be attached and rendered. Confirm: `H3 job completed` → `local file retained` → `Cutroom shot ID and provenance` → `real preview/trim` → `FFmpeg export`. Do not fabricate Cutroom URLs or APIs. If direct H3 succeeds but the handoff is missing, mark `CUTROOM_INTEGRATION_PENDING`; use a manual file-backed import only if explicitly tested. Existing Cutroom projects/user content are not part of source distributions.

## 1080p finishing paths (mutually exclusive per output)

**Packaged Video Desk Screening Room:** Lanczos / Real-ESRGAN+Lanczos; its environment settings are `VIDEO_UPSCALER_NCNN_BIN`, `VIDEO_UPSCALER_NCNN_MODELS`, `VIDEO_UPSCALE_SCRATCH`.

**This skill's standalone script:** `scripts/h3_lanczos_1080p.sh`; its settings are `REALESRGAN_BIN`, `REALESRGAN_MODELS`, `H3_TMP_DIR`. It expects an installed `realesrgan-ncnn-vulkan`, its `realesrgan-x4plus.param/.bin` models, FFmpeg, ffprobe, free temporary disk, and a verified NCNN/Vulkan GPU ID. The NVIDIA CUDA index is **not** the Vulkan index. `--list-gpus` is a hint; inspect engine logs. Native ESRGAN **4×** then aspect-safe 1920×1080 Lanczos, H.264 slow CRF17, source audio copy. If the source has an audio codec that cannot be copied into MP4, stop and take an explicitly documented compatible route, not a silent re-encode.

**Important constraints:** existing video may already be at 1080p; enhancement is then *not* resolution increase. Large frame-sequence scratch consumption requires disk budget. Always run short preview, inspect visual frames and audio, then full render and ffprobe/QC. Do not run the two finishing implementations on the same source automatically.

## Operational acceptance

1. Inspect installed config and services and see whether the expected scripts/model hashes are present; do not reinstall by assumption.
2. Verify one short image, one short song (if required), and a short H3 video using the real integration, after obtaining permission for expensive work where relevant.
3. Keep H3 engine, Cutroom integration, finishing and delivery as **independent recorded gates**.
4. Record actual file paths/ports/model IDs, one successful real result and a failure result for each gate; keep absent evidence explicitly `NOT_TESTED`.
