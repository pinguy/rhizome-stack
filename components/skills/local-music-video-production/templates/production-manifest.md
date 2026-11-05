# [PROJECT] — local music-video production manifest

**Project root:** `...`  
**Job/owner:** `...`  
**Last updated (UTC):** `...`  
**Overall:** `DRAFT | BLOCKED | COMPLETE`  
**Last proven gate:** `G#`  
**Next falsifiable test:** `...`  
**Approval policy / designated reviewer:** `...`

## G0 — Brief

- Story hook / beginning / development / turn / ending:
- Audience/platform and intended effect:
- Song: `GENERATE_MINIMAX | IMPORT_EXISTING`
- Target: aspect / 1920×1080 / FPS / expected duration:
- Exact text, lyrics, likenesses, copyrighted assets and rights evidence:
- Time/energy/disk/hardware limitations:
- Acceptance statement and approval receipt:
- Status: `DRAFT | BRIEF_LOCKED`

## G1 — Concept storyboard (must precede production)

- Status: `STORYBOARD_DRAFT | STORYBOARD_APPROVED`
- Version and hash:
- Panel dir / visible ordered contact sheet:
- Story purpose understandable from panels without prompts? `PASS | FAIL`
- Beginning, turn, payoff and character continuity: `PASS | FAIL`
- High-cost/risky shots and fallback:
- Approval record (who/when/criterion):

## G2 — Song lock

- Source: `MiniMax Music 3 | imported`
- Source MP3 / WAV (actual) and immutable SHA-256:
- Generated recipe path, seed, exact model/version; or imported track fingerprint:
- Duration, audio sample rate/channels, lyric version:
- Listening/acceptance record:
- Status: `DRAFT | SONG_LOCKED`

## G3 — Timing lock

- Waveform/BPM/beat phase, verified audible anchors:
- Sections and timestamps:
- Lyric/word timings and vocal sync requirements:
- Breaks, drops, holds and intensity arc:
- Timing CSV path/hash:
- Status: `DRAFT | TIMING_LOCKED`

## G4 — Timed visual storyboard

- Status: `TIMED_BOARD_DRAFT | TIMED_BOARD_LOCKED`
- Parent concept version; song SHA-256:
- Timed panels dir, contact sheet, `shots.csv` and optional animatic:
- Image panel for **every** shot: `PASS | FAIL`
- Exact `[0, song duration]` coverage, transitions/overlap checked: `PASS | FAIL`
- Approved shot IDs and durations; no placeholders: `PASS | FAIL`
- Approval receipt/revision:
- Invalidated downstream work after any edits:

## G5 — Visual canon and prompt book

- Character, wardrobe, recurring props/location, lighting, palette, lens/camera grammar:
- Canon image paths, seeds, prompt, models, reference-chain hashes:
- Deterministic UI/lyric/overlay plans:
- Prompt book path/hash and storyboard revision:
- Each shot ID mapped to a prompt/visual method: `PASS | FAIL`
- Status: `DRAFT | PROMPTS_LOCKED`

## G6 — Video engine readiness (independent of Cutroom)

- Active application and model selection (evidence/time):
- H3 runtime: `FL2VA NF4`, exact selected model/hash and Turbo/Sol/Spectrum state:
- Current allowed H3 steps: **4–50**; actual chosen: ___; packaged tool default: **20**, deliberate fast profile: **8**:
- Mode: `TEXT | FIRST_FRAME_IMAGE`; 24 FPS; target duration 1–15 s:
- Actual T2V job ID/path/hash/ffprobe; observed motion:
- Actual first-frame I2V job ID/path/hash/reference and observed identity:
- Native audio path/codec/32 kHz stereo/sync result:
- Queue/gpu ownership check and expected idle release:
- Failure/retry tests (or `NOT_TESTED`):
- Status: `H3_ENGINE_VERIFIED | VIDEO_BACKEND_PENDING | RECHECK_REQUIRED`
- Optional deliberately selected WAN backend/proof (else `NOT_USED`):

## G7 — Cutroom handoff (separate gate)

- Installed Cutroom UI, backend and process status:
- Source H3 job/take ID and storyboard shot ID:
- Actual file import/attachment (automated vs tested manual):
- Trim and native-audio isolation tests:
- Real Cutroom → FFmpeg render file/log/probe:
- Status: `CUTROOM_VERIFIED | CUTROOM_INTEGRATION_PENDING`

## G8 — Pilot, accepted takes, edit and soundtrack

Record each take in separate `takes.csv` or the Cutroom project, using stable shot IDs:

| Shot ID | Take ID | Mode/reference | Model/hash + 4–50 steps + seed + adapters | FPS/dimensions | Native audio & policy | SHA-256 / source | Decision + reason | Usable seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S001 | T001 | | | | `MUTE | MIX | USE` | | `KEEP | SALVAGE | REGENERATE | BIN` | |

- Pilot shots (face/complex movement/difficult lighting) and pass evidence:
- Final accepted shot/take mapping and storyboard changes:
- Song-locked Cutroom project and project backup:
- Entire duration covered; no unintended frozen frames or loops:
- Frame/seam, identity/props, camera coherence:
- Lyric/typography coverage and spelling:
- Lip-sync intervals **actually checked**:
- Source song remains master; H3 native audio muted by default:
- Selected ambience/SFX rights and mix levels:
- Status: `DRAFT | EDIT_LOCKED`

## G9 — Render, upscale and QC

- Pre-upscale Cutroom song-locked intermediate path and SHA-256:
- Input ffprobe dimensions/fps/duration/audio metadata:
- **Exactly one** finishing path: `SCREENING_ROOM | STANDALONE_SCRIPT`
- Method: `REALESRGAN_X4_PLUS_LANCZOS | LANCZOS_ONLY_EXPLICIT_FALLBACK`
- Order: `AFTER_FULL_COMPOSITE | PICTURE_CLIPS_BEFORE_FINAL_TYPE`
- NCNN executable/model path/hash, GPU Vulkan ID and actual device log:
- Script path/hash or Screening Room job id:
- ESRGAN scale: **native 4×** (not x4plus `-s 2`); tile setting:
- Temp PNG directory and free-disk check:
- Preview source, command/job ID, file, visual and audio PASS/FAIL:
- Full command/settings, exit code, render log:
- Full final MP4 SHA-256 and ffprobe: 1920×1080, expected FPS/duration/audio:
- Playback QC: frames/flicker/tiles/face/text/pad/last frame/audio sync:
- Source intermediate preserved (path/hash):
- Status: `UPSCALE_PENDING | UPSCALE_VERIFIED`

## G10 — Delivery and receipts

- Final MP4 path/hash:
- Delivered exact aspect/FPS/duration/codec:
- Stored contact sheets/storyboard versions / locked song / recipe:
- Shots/takes + prompts + seeds + model config/hashes:
- Cutroom project + source/intermediate logs + finish logs:
- Local-only confirmation or approved external services and data transfer:
- Known defects / quality compromises / untested operations:
- Director acceptance record:
- Status: `BLOCKED | DELIVERY_ACCEPTED`
- Exact restart step if blocked:
- Two lessons for next production:
