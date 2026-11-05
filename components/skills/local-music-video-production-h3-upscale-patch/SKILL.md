---
name: "local-music-video-production"
description: "Storyboard-first local music-video pipeline with GPT-5.6-Sol, Qwen Image 2.1, MiniMax Music 3, MiniMax H3 NF4 Turbo + Sol + Spectrum, Cutroom, and local Real-ESRGAN/Lanczos 1080p finishing."
compatibility: Rhizome workstation; loopback-only Cutroom/Qwen Image Desk and MiniMax Music 3; MiniMax H3 local T2V/first-frame video proven; verify live Cutroom handoff separately.
---

# Local Music Video Production

Turn a song idea or finished track into a reproducible local music video with GPT-5.6-Sol coordinating the creative/production work. **Storyboard the concept before generating production assets**; then lock the song, turn the concept panels into a timed storyboard, and only then make final references and video. The locked song is the master clock. A written shot list is **not** a substitute for a viewable storyboard.

Read:
- `references/bliss-method.md` when planning the production or explaining why the gates exist (retain the existing reference; not part of this patch).
- `references/local-tool-map.md` before calling media tools; verify live state because recorded paths/capabilities may be stale.
- `templates/storyboard-template.md` when drafting and locking the storyboard.
- `templates/production-manifest.md` when creating a project record or handover.
- `scripts/h3_lanczos_1080p.sh` and the final-upscale section before exporting a 1080p deliverable; use the copy tested/installed on the workstation, not a guessed absolute path.

## Governing constraints

- Keep media generation local unless Pingu explicitly authorises a different route for the current job.
- Use **MiniMax Music 3** for a new song, preserving its MP3 and companion recipe.
- Use **Qwen Image Desk / Qwen Image 2.1** for concept panels where useful, canon references, plates, and controlled edits. Simple sketches, text boxes and placeholder frames are valid **early storyboard** material; do not waste final-quality generations on throwaway panels.
- Use **Cutroom** for song import and analysis, shot planning, asset/take review, song-locked editing, and FFmpeg assembly of the pre-upscale master. Do not assume a visual storyboard UI exists: persist storyboard panels/contact sheets as project-local files and attach or reference them from Cutroom shot records where supported.
- Use **MiniMax H3 (NF4 Turbo + Sol + Spectrum)** as the designated local video engine. It has already produced verified text-to-video and first-frame-to-video clips with native stereo audio on this workstation. Range **4–24 inference steps**, **8 default**. Recheck live configuration; record the actual setting for every run.
- Never silently substitute Veo, OpenRouter, Seedance, Midjourney, Suno, LTX or another provider/model; a named substitution requires a fresh user decision.
- Separate **H3 engine readiness** (historically demonstrated) from **Cutroom handoff readiness** (must be verified on the live installation). If the direct local H3 runner works but the Cutroom adapter does not, retain generated footage and provenance and mark `CUTROOM_INTEGRATION_PENDING`; do not incorrectly declare H3 itself unready. Never call a video completed until the requested master render and QC exist.
- Serialise large local media jobs. Image, video and music pipelines share GPUs and must not collide.
- **1080p finishing:** after the Cutroom picture is assembled, use the supplied `h3_lanczos_1080p.sh` for **Real-ESRGAN NCNN/Vulkan native 4× then Lanczos to 1920×1080**. The script defaults to `realesrgan-x4plus`, `libx264 -preset slow -crf 17`, aspect-preserving pad, and copies the source audio. `--mode lanczos` is the explicitly selected CPU-only fallback. Check input resolution: enhancing an already-1080p render is an enhancement pass, not a resolution increase.
- Preserve **both** the pre-upscale Cutroom master and the separate 1080p delivery output, hashes, ffprobe results, GPU/model selection, preview evidence and any artefact decisions. Never silently replace the locked song; the script passes through the audio of the assembled input.
- **Upscale ordering:** default to one pass on the assembled video, after a verified short preview. If exact text/graphics or mixed-source footage suffer from post-render enhancement, upscale the accepted H3 *picture clips* before Cutroom compositing and render sharp 1080p text/overlays after the upscale. Record the chosen ordering and prove the actual Cutroom path. Do not upscale everything twice.
- Preserve work in project-local paths: versioned storyboard panels, immutable accepted takes, seeds, recipes, manifests, prompt books, hashes, logs and recoverable edits.
- Do not block unattended work on permissions outside approved project paths. Preserve partial progress and record the precise resume point.

## Gate order and output contract

| Gate | Required evidence | Status |
| --- | --- | --- |
| 1. Brief | Concept, format, constraints, acceptance line | `DRAFT / LOCKED` |
| **2. Concept storyboard** | **Viewable ordered panels, captions, contact sheet and revision ID** | **`STORYBOARD_DRAFT / STORYBOARD_APPROVED`** |
| 3. Research | Narrow research banks supporting storyboard and technical decisions | `DRAFT / LOCKED` |
| 4. Song lock | Accepted audio, recipe/import fingerprint, hash | `DRAFT / LOCKED` |
| 5. Timing | Verified beat/section/lyric map | `DRAFT / LOCKED` |
| **6. Timed storyboard** | **Image panel per intended shot, exact slots, transitions, rough animatic/contact sheet** | **`TIMED_BOARD_DRAFT / TIMED_BOARD_LOCKED`** |
| 7. Visual bible | Canon and approved reference assets with provenance | `DRAFT / LOCKED` |
| 8. Prompt book | One consistent first-round book mapped to storyboard IDs | `DRAFT / LOCKED` |
| 9. Video engine and editing path | Actual H3 mode/native-audio tests plus separate Cutroom import→FFmpeg render | `H3_ENGINE_VERIFIED / VIDEO_BACKEND_PENDING` and `CUTROOM_VERIFIED / CUTROOM_INTEGRATION_PENDING` |
| 10–13. Production | Pilots, takes, locked edit, song/native-audio mix | `BLOCKED / COMPLETE` |
| **14. 1080p finishing** | **Cutroom intermediate; short upscale preview; GPU/model verified; 1920×1080 delivered file; audio/visual QC** | **`UPSCALE_PENDING / UPSCALE_VERIFIED`** |
| 15. Delivery | Immutable deliverable and reproducibility/receipt bundle | `BLOCKED / COMPLETE` |

**Hard dependency:** Do not bulk-generate production-quality images or video until the **timed storyboard is locked**. A working storyboard can use sketches, placeholders or inexpensive draft images. Locking can be based on the user's direction or an already agreed acceptance criterion; do not invent user approval.

A completed job includes: brief and research; concept storyboard panels/contact sheet; locked song; verified timing; locked timed storyboard and optional animatic; visual bible; prompt book; reference and video provenance; shot/take decisions; song-locked Cutroom project; final render and QC receipts. Keep all artifacts even when video is blocked.

## Workflow

### 1. Establish the production brief

Record:
- one-sentence concept, emotional arc, hook, ending and what should be memorable;
- new song (MiniMax) versus supplied song, rough length and intended musical sections;
- audience/platform, aspect ratio, resolution and fps;
- performance, narrative, lyric-video, interface/motion-design or hybrid balance;
- recurring character, setting, location and prop requirements;
- source material, rights constraints and elements that must be pixel/sound exact;
- style, local resources, budget/time constraints and prohibited content.

Write a falsifiable acceptance line. Do not start by generating twenty beautiful shots without deciding what the film is about.

### 2. **Create a visual concept storyboard FIRST**

Before song generation, canon-art volume or video jobs, assemble a rough **beginning → development → turn → climax → ending** board. If the user supplied a finished song, listen to it first; the concept board still precedes detailed shot production.

- Break the narrative into scenes/sections; each scene needs a purpose and visual change.
- Produce a **visible thumbnail/panel for each important scene**: sketch, flat diagram, existing authorised reference or cheap Qwen draft. A paragraph-only outline fails this gate.
- Under every panel record provisional ID, intended lyric or musical moment (or section placeholder), subject/action, composition, location, camera idea and transition to the next panel.
- Include a character/setting continuity note and a readable contact sheet in story order.
- Decide whether special sequences need deterministic code, type, overlays or interfaces instead of model-generated motion.
- Identify the costly/uncertain scenes and propose a fallback before expensive generation.
- Review the complete visual sequence for coherence, pacing, variety and a legible ending; revise scene order here, when revision is cheap.

Store `storyboard/concept-v01/` with numbered panel images and a `contact-sheet` plus `storyboard.md` or CSV. Keep earlier versions; mark the chosen board `STORYBOARD_APPROVED` only when approval is actually established.

**Gate test:** Someone should be able to look at the contact sheet, without reading a prompt book, and understand the intended progression of the video. If not, rewrite the board before moving on.

### 3. Build focused research banks

Research only what affects the storyboard, song, visual language, rights or model limits:
- music/genre grammar and scansion;
- cultural references, technical jokes, factual claims and story beats;
- character/wardrobe/location/props, lighting and palette;
- camera motion and achievable shot types;
- typography, interface and deterministic motion design;
- usable sound sources and rights;
- current local model strengths and failure modes.

Separate evidence, creative preference and assumptions. Feed discoveries back into the concept board rather than silently changing the story in production.

### 4. Create or import and lock the song

For a new song, use MiniMax Music 3: Global Metadata → Vocal Details → Arrangement; use section tags, bounded variants and preserved seeds/recipes. Listen, compare and choose the accepted take. For an existing track, fingerprint the exact imported audio.

Record duration, sample format, hash, recipe path (if any), and chosen take. Do not regenerate a locked song without reopening this gate. The audio is now the single master clock for everything that follows.

### 5. Analyse the locked song

Import into Cutroom. Generate/edit a waveform, BPM, beat and bar grid, phrases, energy/section boundaries and lyric timing where relevant. Verify the beat-grid phase against audible kicks/downbeats; automated estimates can be early or late.

Capture section timestamps, exact vocal/lyric events, narrative turns, musical impacts and intentional holds. The storyboard must fit the **actual** song, not the hoped-for length of a draft.

### 6. **Turn the concept board into a timed visual storyboard**

Revisit every visual panel against the locked audio. Expand a scene into individual shots where needed; merge where pacing benefits. Each timed shot needs:
- stable shot ID, scene/panel lineage and actual image panel file path;
- exact in/out time, duration, section/lyric, beat/bar anchor (or deliberately off-beat reason);
- subject and action, shot size, composition, camera movement, setting and lighting;
- transition from previous shot, continuity dependencies and sound/lyric overlays;
- provisional generation method: `I2V / T2V / composite / deterministic / still`;
- required visual reference, risks, acceptance criteria and fallback/cutaway.

Export a **full-video contact sheet** with readable panel IDs/timestamps. Where feasible, make a low-fidelity **animatic** by playing still panels against the locked song with simple hard cuts/fades; it does not need any generated motion. Check scene transitions, story arc, visual monotony, lyric intelligibility and whether important moments land on the music.

Persist `storyboard/timed-v01/` with the shot table, ordered panels, contact sheet and optional animatic, plus a versioned lock record. Each shot should map to one Cutroom shot slot; if Cutroom cannot display the board, retain a separate source of truth in project-local files and record its paths in Cutroom/manifest.

**Hard gate:** no production reference batches, H3 clips or full prompt submissions before `TIMED_BOARD_LOCKED`. If the song changes, invalidate the timing and timed-board lock. If a shot is later altered, log the storyboard revision and downstream prompt/take impact.

### 7. Lock the visual bible and reference plates

Now the approved sequence defines which character looks, settings and props actually need high-quality references.

Specify canonical face/hair/wardrobe/silhouette, fixed props, location geometry, time-of-day states, palette with labels/values, framing/lens/texture, typography, negative constraints and continuity risks.

Use Qwen Image Desk for small contact-sheet rounds and controlled edits; preserve input/expanded prompts, seed, dimensions, model/version, output paths and reference relationships. Attach approved references to corresponding storyboard/Cutroom shot IDs. Do not bulk-generate before the canon passes at least one revision round.

If a visual cannot be made consistently, return to the timed storyboard to simplify or replace it instead of quietly changing the film.

### 8. Finish the prompt book before video jobs

Draft all first-round MiniMax H3 prompts in one coherent context, keyed to **locked storyboard shot IDs**. For each record, include canon/reference, action, environment, lighting, framing/camera, intra-clip timing, motion intensity, invariants, negative guidance, seed plan, **H3 mode (text / first-frame), 4–24 step setting (8 default)**, native-audio intent, intended usable interval and acceptance test.

Prefer I2V for continuity-critical shots, T2V where identity/reference fidelity is not needed. Keep precision typography and interfaces in deterministic code/FFmpeg. Mark any changes from the storyboard as revisions and re-check adjacent shots.

### 9. MiniMax H3 engine gate and separate Cutroom handoff gate

**Recorded working baseline, not a claim that the live software was inspected here:** on the Z440 / RTX 3060 12GB, MiniMax H3 FL2VA NF4 has already generated playable T2V and first-frame I2V with native stereo audio. The optimised configuration is **NF4 + Turbo + Sol + Spectrum**. Inference steps are **4–24**, **8 by default**. Prior local tests also covered accelerated GPU text conditioning and CPU fallback. Do not reset the machine to an old WAN proposal merely because this skill was stale.

**Engine checks:**
- Confirm the running H3 workflow/model revision, Turbo/Sol/Spectrum settings and memory/offload strategy from live state; record them with the job.
- Confirm text prompt and optional **first-frame reference image** as the two supported modes; never claim other conditioning modes without a real test.
- Generate playable local video, test real motion, preserve seed, steps (default 8 unless the shot specifies otherwise), dimensions, FPS, frame count, model hash, reference hash, output path, job ID and timings.
- Record **native audio** separately: existence, channels, codec/sample rate, synchronisation, defects and whether the take's audio will be used or muted in the edit.
- Exercise cancellation, bounded retry, failed-job diagnostics, immutable accepted takes, serialised VRAM use and idle release when available; do not mark an untested operational feature as passed.

**Cutroom handoff is a separate gate:**
- Confirm how a real H3 take gets from the current local H3/Video Desk runner into the correct Cutroom shot slot, carrying its approved storyboard shot ID and provenance. An integrated adapter is not assumed merely because direct H3 works.
- Verify import/attachment, trim, audio-stream handling and a real Cutroom → FFmpeg final render with a kept H3 clip.
- If direct H3 runs but this path is not tested/working, mark `CUTROOM_INTEGRATION_PENDING` with a concrete next test; do not mark `VIDEO_BACKEND_PENDING` just because a UI integration is missing. A manual file-backed import is acceptable only when actually verified and its steps recorded.
- Use `VIDEO_BACKEND_PENDING` only if H3 generation itself fails or cannot be proved on the current box. Do not silently substitute WAN or any hosted video service.

### 10. Pilot before volume

Make two or three representative clips: continuity-critical face/character, high-motion/camera movement, and difficult light/composition. Compare them to the locked storyboard panels, not merely to the prompts. Inspect actual motion frame by frame. Fix systematic problems before a batch run.

### 11. Generate serially; review and record decisions

Use bounded batches and retain prompt/negative/seed/model/adapter/**step count and Turbo/Sol/Spectrum state**/dimensions/fps/reference/job ID/timestamps/**native-audio metadata**/output paths. Every take gets one decision in Cutroom:
- **KEEP**: usable as planned;
- **SALVAGE**: usable with a specific edit;
- **REGENERATE**: required shot, failed take;
- **BIN**: no production value.

Check identity/wardrobe/props/anatomy, scene continuity, camera motion, real temporal coherence, actual usable intervals, lip-sync where appropriate, and defects hidden or exposed by edits. Change one meaningful cause per bounded retry.

### 12. Edit to the song and storyboard, not clip lengths

Build the Cutroom waveform timeline from locked shot slots. Trim and composite accepted takes without silently looping them or moving the song. A shot change updates the storyboard record. Use deterministic tooling for exact titles/lyrics/UI, stable overlays, beat-locked animation, trims/crops/speed/fades.

For lip sync, measure valid intervals and cut to planned cover shots when they diverge. For visible lyrics, check all required words appear at the right time.

### 13. Build the sound layer deliberately

The **locked MiniMax Music 3 song** remains the final master clock. H3 can generate its own **native audio** with a video take: preserve it as a separate source track, but **mute/discard it by default** when it would compete with the song. Use any H3-generated ambience, effects or dialogue only as an explicit editorial decision after checking rights, timing, intelligibility and mix balance. Never replace or time-stretch the locked song just to match H3 audio. Place additional sound cues on the verified beat grid; tune tonal sounds when helpful; duck beneath vocals; retain cue sources, rights and mix settings.

### 14. Assemble, upscale to 1080p, and validate the deliverable

**Cutroom/FFmpeg assembly:** first finish the song-locked edit and verify every scene seam and neighbouring frames, full timeline coverage, exact duration, intentional loops/holds, typography/lyric timing, audio sync/loudness/clipping and final frame. Render a high-quality **pre-upscale intermediate**, preserving the complete locked-song mix. Save its ffprobe metadata and SHA-256. Do not delete or overwrite it.

**Dedicated H3 finishing script:** the user-supplied, syntactically checked `scripts/h3_lanczos_1080p.sh` uses `realesrgan-ncnn-vulkan` at native 4× (`-s 4`) and Lanczos fit/pad to **1920×1080**, keeping aspect ratio and copying input audio. Real-ESRGAN `x4plus -s 2` was specifically avoided because it produced zoomed/scrambled tiles in earlier testing; do not replace this with 2×. The default output is H.264/x264 slow/CRF 17; an explicit CPU-only `--mode lanczos` exists if GPU enhancement is unavailable or rejected. It **requires** a separate working NCNN/Vulkan binary/models installation for ESRGAN mode; the script alone does not prove live readiness.

1. Check source resolution, FPS (constant frame rate for the ESRGAN path), video/audio duration and whether the assembled master has text or other details that enhancement could damage.
2. Check Vulkan GPU IDs. Use `--list-gpus` and pass `--gpu ID` if auto-selection cannot be trusted; confirm the **RTX 3060** actually selected in NCNN startup log, not simply inferred from a separate tool. GPU IDs are not fixed.
3. Run a **short preview**, usually `--seconds 2`, with a distinct output path. Inspect faces, hands, fine detail, tiles, motion flicker, titles, aspect/padding, audio and frame count at full size. An FFmpeg success exit is not a visual pass.
4. If approved, run the same model/GPU/settings on the full pre-upscale master, using an output name that does not exist. The script refuses overwrites. Temporary PNG sequences are large: place `H3_TMP_DIR` on a writable disk with sufficient space, not tmpfs. Keep `--keep-frames` only for diagnostics.
5. Verify the **delivered** MP4 independently with `ffprobe` and playback: 1920×1080, source aspect respected, expected FPS and duration, correct audio stream and sync, no blank frames, severe artefacts or unwanted freeze. Record chosen model, tile size, GPU ID, method, CRF/preset, command, logs and pre/post hashes.
6. If rendering final text/overlays before ESRGAN makes them soft/distorted, **change ordering**, don't keep rerunning: enhance the relevant accepted H3 picture clips first, then do final Cutroom composition and render precise text at 1080p. Keep original clips immutable, track which version is used for each shot, and QC the full result. The finished 1080p deliverable must not be enhanced again by default.

Example commands (adjust paths/GPU ID after actual inspection):

```bash
# From the patch folder; the script needs ffmpeg/ffprobe and local NCNN models.
bash scripts/h3_lanczos_1080p.sh --list-gpus
bash scripts/h3_lanczos_1080p.sh --gpu 0 --seconds 2 \
  /path/to/cutroom_master.mp4 /path/to/preview_1080p.mp4
bash scripts/h3_lanczos_1080p.sh --gpu 0 \
  /path/to/cutroom_master.mp4 /path/to/final_1080p.mp4
# Explicit, non-neural fallback only:
bash scripts/h3_lanczos_1080p.sh --mode lanczos \
  /path/to/cutroom_master.mp4 /path/to/final_lanczos_1080p.mp4
```

Do not use the example ID `0` as a hardcoded system fact. The script's audio copy is intentional: the final mix must already be correct in the input. If the intermediate audio format is incompatible with MP4 stream copy, stop and fix/choose a compatible intermediate (or document a separate approved mux stage); do not silently degrade the song.

Mark `UPSCALE_VERIFIED` **only after inspecting the actual output**. If enhancement is blocked, keep the Cutroom intermediate, the tested fallback, the attempted command/logs and a precise resume point; do not claim the requested enhanced master exists.

### 15. Close with receipts and learning

Write a succinct production report: which gates passed, evidence and artifact paths, storyboard revisions, versions/local-vs-remote status, accepted takes, rejects and retries, known faults, final media/hash/log receipts, and exact restart point. Distinguish observed faults from conjectured causes. Keep one or two concrete process changes for next time.

## Failure handling

- **Storyboard isn't readable:** stop; redraw panels or add missing transitions. A prose shot list is not enough.
- **Storyboard drift:** halt bulk generation, revise the locked board, identify affected shot IDs and dependent assets, then relock.
- **Song changes:** invalidate beat grid and timed storyboard; do not move clips blindly.
- **Permission/path wait:** only use project-approved locations during unattended runs; checkpoint before batches.
- **OOM/resource collision:** preserve the job record, release the owning engine, and retry only with a measured fallback.
- **Prompt/canon drift:** stop volume, revisit canon + unified prompt book, change one systemic cause.
- **H3 engine fails:** leave storyboard and references complete, mark `VIDEO_BACKEND_PENDING` with logs and a precise next test. **H3 works but Cutroom path fails:** keep the generated clips and mark `CUTROOM_INTEGRATION_PENDING`; do not conflate the two.
- **Native audio conflict:** keep the locked song as master. Preserve H3 take audio as a separately labelled asset; mute it unless explicitly selected and mixed.
- **Partial lip sync:** measure good intervals, use planned covers; do not claim full sync.
- **Upscale fails or distorts content:** stop, keep the source/preview/log, check GPU selection and native 4× path, bound retries; use explicit Lanczos fallback or per-clip-before-overlays ordering when warranted. Mark `UPSCALE_PENDING` until the chosen delivery passes visual and audio inspection.
- **Automation mismatch:** match by immutable job ID and provenance, not prompt text or screen click position.
- **Repeated failure:** bound retries, preserve evidence and change hypothesis rather than resubmitting indefinitely.

## Stopping rule

The production is complete only when the requested **1080p deliverable**, the pre-upscale intermediate, and the reproducibility bundle exist and pass agreed checks. When blocked, preserve all storyboard versions, the locked timing/reference/prompt artifacts, failed-gate evidence and a smallest actionable next test.
