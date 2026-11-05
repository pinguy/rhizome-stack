---
name: local-music-video-production
description: Local, storyboard-first music-video production in Rhizome: MiniMax Music 3, Qwen Image 2.1, MiniMax H3 (WAN optional), Cutroom, verified 1080p finishing, and full provenance.
compatibility: Rhizome Stack alpha.18 creative profile; local media services on loopback; verify installed software, models, tools and hardware before taking action.
---

# Local Music Video Production — unified v3

Make a finished, **reproducible music video**, not a folder of impressive clips. An LLM may plan, write lyrics, coordinate, critique and call tools; deterministic tools own timing, file integrity, queuing, mixing and final rendering. The **locked song is the master clock**. **Visual storyboard before production**, then **timed storyboard before bulk video**. All generation is local by default.

## Read first and establish real capabilities

1. Read `references/local-tool-map.md` for *documented* app ports, model constraints and launch commands. These describe the packaged alpha.18 configuration, **not a live health check**.
2. Read `references/bliss-method.md` for production lessons, `templates/storyboard-template.md` for both storyboard gates and `templates/production-manifest.md` for receipts.
3. Confirm live tools, model versions, current configuration, writable project root, free disk, GPU ownership, and real integration paths before invoking any generator. Never guess an endpoint, model ID, GPU ID or filesystem path.
4. The bundled `scripts/h3_lanczos_1080p.sh` is an **optional independent finishing route**. Rhizome Video Desk Screening Room also has a native mastering route. **Choose one for a given output; do not run both automatically.**

**Current packaged defaults (source docs, not live assertions):**

| Stage | Default | Important limit |
| --- | --- | --- |
| Planning, lyrics, direction | Available local LLM through OpenClaw/Ollama | An LLM is not the timing engine; do not assume a particular installed model |
| New song | MiniMax Music 3 | Lock actual audio and companion recipe/seed |
| Still/reference/edit | Qwen Image 2.1, Qwen Image Desk | Reference edits retain ownership and image provenance |
| Video | **MiniMax H3 FL2VA pruned NF4 via Video Desk** | T2V or **first-frame** I2V, 1–15 s, **24 FPS**, **4–50 steps**; packaged tool **20-step default**, 8-step speed preset only when deliberately chosen; native **32 kHz stereo** audio |
| Alternative video | WAN 2.2, **only when deliberately selected** | 1–10 s, 16/24 FPS, 4–20 steps; distinct model/input pairing |
| Editorial | Cutroom + FFmpeg | Song-locked project; actual H3 take import/render must be tested |
| Delivery | Cutroom intermediate + one verified 1080p finishing route | Real-ESRGAN native 4× then Lanczos fit/pad, or explicit Lanczos-only fallback |

Do not carry forward the older patch's **H3 4–24 steps / 8 default** as a service contract. Those were earlier workflow settings; **8 steps is an intentionally selected fast experiment**, not the documented alpha.18 default. Source docs allow 4–50 steps and expose 20 as the H3 chat-tool default. Check the live UI/API before each production.

## Non-negotiable production rules

- **Local by default.** Do not silently use Suno, Udio, Midjourney, Seedance, Veo, OpenRouter, hosted Sora or other external services. Only switch when explicitly authorised for this job, and log the change and any privacy implications.
- **Do not invent user approval.** Mark `STORYBOARD_APPROVED`, `TIMED_BOARD_LOCKED`, `SONG_LOCKED` or `DELIVERY_ACCEPTED` only with explicit user approval or a specific pre-agreed acceptance rule. An authorised autonomous run may follow that rule; without one, checkpoint for review.
- **Single-flight media.** Serialise heavy Qwen/MiniMax/H3/WAN jobs; never stop an engine you do not own. Treat a busy, unreadable or ambiguous queue as **not available**, not idle.
- **No duplicate submissions.** Preserve idempotency receipts/job IDs. Retry read-only status polling; do not resubmit an ambiguous generation just because a response timed out.
- **Preserve work.** Keep the source song, earlier storyboard versions, accepted takes, render intermediates, manifests, hashes, original reference images and diagnostic logs. Never silently overwrite an accepted artefact.
- **Use bounded experiments.** Pilot tricky scenes, limit retries, and change one meaningful variable at a time. Do not spend hours producing clips before the plan is coherent.
- **Honest evidence.** A healthy UI or prior test does not prove current generation, Cutroom handoff, audio sync or 1080p delivery. Report **observed / historical / pending / failed** separately.
- **Safety and rights.** Record the right to use supplied music, likenesses and other source materials. Do not import arbitrary files outside approved project roots or handle private uploads by unverified path/URL.
- **No host mutation by surprise.** Installing model weights, changing services, elevated operations, clearing disk and network downloads require the normal user-approval and change-control path.

## Project contract and gate sequence

Each production should contain the following **project-local, versioned artifacts**. Track gate state and the smallest next test in `production-manifest.md`. A later success does not erase an earlier failure.

| Gate | Evidence required | Lock state |
| --- | --- | --- |
| G0 Brief | Scope, story hook/ending, duration, format, rights, constraints, acceptance definition | `BRIEF_LOCKED` |
| G1 Concept storyboard **first** | **Visible** beginning→turn→ending panels, readable contact sheet, notes, revision and approval | `STORYBOARD_APPROVED` |
| G2 Song | Approved MP3 or imported master, recipe (if generated), immutable hash and duration | `SONG_LOCKED` |
| G3 Timing | Verified beat phase, section/lyric map, exact duration, anchors | `TIMING_LOCKED` |
| G4 Timed storyboard | **Per-shot illustrated panel**, stable shot ID, exact audio in/out, full coverage, transitions and approved contact sheet / optional animatic | `TIMED_BOARD_LOCKED` |
| G5 Visual canon / prompt book | Approved identity/world references, consistent **complete first-round** prompt book mapped to IDs | `PROMPTS_LOCKED` |
| G6 Engine | Actual H3 T2V/I2V tested as needed, model/steps/FPS/native audio/queue evidence | `H3_ENGINE_VERIFIED` or `VIDEO_BACKEND_PENDING` |
| G7 Cutroom | Accepted H3 file attached/imported in a real shot, trimmed, sound handled, rendered with FFmpeg | `CUTROOM_VERIFIED` or `CUTROOM_INTEGRATION_PENDING` |
| G8 Production/edit | Pilots, accepted takes, song-locked timeline, QC of each seam, lyric/visual/lip-sync decisions | `EDIT_LOCKED` |
| G9 Finishing | Pre-upscale master, 2-second preview accepted, full 1080p output, picture/audio checks, hashes | `UPSCALE_VERIFIED` |
| G10 Delivery | Final MP4, reproducibility bundle, known defects, acceptance and resume notes | `DELIVERY_ACCEPTED` |

If **G6 works but G7 fails**, mark `CUTROOM_INTEGRATION_PENDING`, not `VIDEO_BACKEND_PENDING`. An externally imported file-backed Cutroom workflow is acceptable **only if tested**. If the requested target is a draft rather than a finished video, explicitly scope out later gates rather than claiming production complete.

## Production workflow

### 0. Brief and constraints

Record concept, beginning/turn/ending, memorable hook, musical direction, target audience/platform, aspect ratio, FPS, output resolution, projected length, visual tone, characters, recurring locations/props, lyrics/typography, allowed sources, rights, approval owner and acceptable flaws. Identify where exact pixels/words matter. Set expected GPU/disk/time constraints and a **testable acceptance statement**.

### 1. Concept storyboard before song/art volume

Create `storyboard/concept-v01/panels/`, a numbered **contact sheet** and a brief visual narrative. A text-only list **does not pass**. Use sketches, rough shapes, pre-existing authorised images or low-cost Qwen draft frames rather than expensive final art. Show progression, shot/scene purpose, camera ideas, transition, character continuity and risky scenes with fallback options. Assess the story from the contact sheet without relying on the prompt book. Record approval and version; preserve rejected revisions. If a finished song was supplied, inspect/listen to it before the concept storyboard, but still make the visual board before bulk production.

### 2. Research and song lock

Research only questions affecting the concept, lyrics/scansion, props/culture, rights, camera language, typography, effects or model limits. Separate facts, assumptions and creative preferences. If generating music, write a structured MiniMax Music 3 brief (global metadata → vocals → arrangement, with song-section markers), make **bounded** candidates, listen, then accept an actual file with its recipe and seed. If imported, fingerprint the source. Save immutable song path, SHA-256, duration, format and provenance. A song replacement invalidates every downstream beat/shot timestamp.

### 3. Timing lock

Import or analyse the *exact locked song*. Use Cutroom waveform/BPM/section estimates but verify grid phase against audible hits; correct offsets. Create exact lyric-word/phrase timing when needed, section start/end, beat/bar anchors, drops, instrumental breaks and intentional holds. Record evidence rather than trusting an LLM's estimated BPM. The song must not later be stretched or looped to accommodate video generation.

### 4. Timed visual storyboard **before bulk images or video**

Turn concept panels into `storyboard/timed-vNN/panels/SNNN.png`, an ordered contact sheet and `shots.csv`. Each shot includes: stable ID, concept ID, **real** start/end seconds, musical anchor, purpose, panel image, subject/action, camera, scene, transition, reference/continuity dependencies, generation method (H3 T2V / first-frame I2V / still / deterministic composite), audio plan, fallback and acceptance criteria. Validate coverage of `[0, song duration]`, accounting for deliberate transitions and overlaps. Optional: export a low-resolution **animatic using the locked audio**. Lock the visual board only after the whole cut reads well and the approval rule is satisfied. Avoid treating placeholder `0.000` times as valid slots.

### 5. Visual bible and first-round prompt book

Use Qwen Image 2.1 for **approved** character, wardrobe, place, prop and lighting references; make controlled edits where useful. Preserve exact model, references, hashes, seed, dimensions and prompt history. For every planned H3 shot, prepare a prompt containing: storyboard ID, approved reference, action, setting, lighting, composition, camera movement, temporal beats, style, stable elements, negatives, target usable span, 24 FPS, selected step count, seed, and native-audio decision. Prefer first-frame I2V for continuity-critical subjects. Use deterministic overlays/FFmpeg for exact text, logos, lyric captions and UI animation. Finish one consistent prompt book **before** the expensive run so terminology and identity do not drift.

### 6. Engine qualification and Cutroom qualification — **two different gates**

**H3 engine:** inspect live model selection. Prove a short T2V and first-frame I2V job **when the chosen shots require them**; verify playable file, actual duration/FPS, frame count, meaningful motion, reference fidelity, **native audio sample rate/channels** where present, job/provenance/seed/steps/model IDs, and bounded failure behaviour. H3 uses a **17n+5** frame sequence, handled by the selected installed implementation; do not fabricate frame formulas or force arbitrary unsupported counts. Record selected Turbo/Sol/Spectrum state, not a guessed global default. If the live path fails, preserve diagnostics and mark `VIDEO_BACKEND_PENDING`.

**Cutroom integration:** take a real H3 output through the *current supported* route into the correct Cutroom shot, with project-local path, ID and provenance. Verify import, trim, audio isolation, preview and Cutroom→FFmpeg output. If this fails but H3 generation works, preserve the clip and mark `CUTROOM_INTEGRATION_PENDING`. Do not claim the model failed or silently fall back to WAN.

**Optional WAN:** if the user expressly selects WAN for a shot, use its own mode/model pairing, FPS and decoder OOM ladder; it is not the default video engine. No cloud fallback without authorisation.

### 7. Pilot, serial production and decisions

Pilot at least a continuity-critical face, a motion-heavy shot and a difficult-lighting/composite case if relevant. Check motion across frames: strong first frames can conceal frozen or corrupted sequences. Correct systemic faults *before* volume. Then use bounded serial batches and immutable, unique take paths. Record model hashes, reference hashes, prompt revision, negative prompt, job ID, steps, seed, resolution, FPS, start/end, run timing, native audio and output SHA-256. Every take receives **KEEP / SALVAGE / REGENERATE / BIN** plus why and usable seconds. Bounded retries must test a changed hypothesis. Retain originals even if a cropped/upscaled derivative is selected.

### 8. Song-locked edit, sync and sound

Cut to the verified grid, not the model's clip lengths. Trim and place takes by storyboard ID. Use deliberate holds, covers and transition rules; don't silently loop a shot. Measure usable lip-sync portions; use a planned cover shot when the mouth diverges. Verify lyric coverage and on-screen spelling/timing. **The locked song is the principal final audio.** H3 native audio remains a separately labelled take component and is **muted by default**; only mix selected ambience/FX/dialogue when intentionally approved, aligned, rights-checked and ducked beneath vocals. Don't let H3 audio replace the song. Render a high-quality, *separate* song-locked Cutroom intermediate and record `ffprobe`, hash and render log.

### 9. Choose exactly one 1080p finishing path

**Option A — packaged Video Desk Screening Room:** use its installed **Real-ESRGAN + Lanczos** or explicit CPU Lanczos mode. Its environment keys are `VIDEO_UPSCALER_NCNN_BIN`, `VIDEO_UPSCALER_NCNN_MODELS`, and `VIDEO_UPSCALE_SCRATCH`. Verify its available entrypoint and real output first.

**Option B — supplied standalone script:** run `scripts/h3_lanczos_1080p.sh`. It expects `REALESRGAN_BIN`, `REALESRGAN_MODELS`, and optionally `H3_TMP_DIR` (these are **not** the same env keys as Screening Room). Verify available binary, model files, temp free space and NCNN/Vulkan device ID. The default uses `realesrgan-x4plus -s 4` **native 4×**, then aspect-preserving Lanczos fit/pad to **1920×1080**, H.264 CRF17/preset slow, and **copies** source audio. Do not change `x4plus` to `-s 2`; that mode has produced scrambled tiles in the recorded workflow. If GPU enhancement is unavailable, `--mode lanczos` is an **explicit non-neural fallback**, not the same quality claim.

For either route: (1) inspect source, exact captions/graphics and audio; (2) run a uniquely named ~2-second preview; (3) **visually inspect** faces, hair, tiles, flicker, captions, padding, motion and audio; (4) run full film only if passed; (5) validate the final playable MP4 with `ffprobe`, full playback, dimensions/FPS, duration, blank-frame checks, audio sync and hashes. Keep intermediate and final separate. A script exit code is not visual QC.

If upscaling post-composite damages exact typography or graphics, consider the **alternative ordering**: upscale accepted H3 picture clips first, then composite sharp graphics and text at 1080p within Cutroom/FFmpeg. Track which derivative is used, re-render and verify the entire result. **No double upscale by default.** Verify the actual installed editorial path can do this before claiming it did.

### 10. Delivery, lessons and resume

Deliver final file **only when the requested gate passed**. Include contact sheets, storyboard versions, song hash/recipe, exact timed shots, visual bible, prompt book, accepted takes and their IDs/hashes, Cutroom project/intermediate, selected audio mixes, finishing command/settings/logs, final MP4/hash, defects and user acceptance. Distinguish *measured improvement* from subjective impression. Capture a concise “next time” note and exact resume step if blocked.

## Status and failure handling

- **No readable concept/timed visual storyboard:** checkpoint, correct panel sequence/shot coverage; a prose plan is insufficient.
- **Song changed:** invalidate timing, timed board, edit and relevant media dependency records; never quietly reuse old timestamps.
- **Canon/storyboard drift:** version affected board and references, trace downstream shots and relock. Do not regenerate unaffected shots.
- **GPU OOM / busy engine / unreadable queue:** retain evidence, stop only owned processes, choose measured fallback or defer. Do not race an external ComfyUI client.
- **H3 engine good, Cutroom untested:** `CUTROOM_INTEGRATION_PENDING`; preserve the successful media and provenance.
- **Native audio conflict:** keep H3 audio separate, mute by default, and preserve the locked song.
- **Lip-sync partial:** record good ranges and plan cuts; never claim full sync from a single attractive frame.
- **Upscale fails / worsens content:** retain original, failed preview, log, GPU/model evidence; choose an explicitly labelled fallback or different compositing order. Keep `UPSCALE_PENDING` until delivery QC.
- **Permissions/download/model drift:** don't mutate the workstation unexpectedly. Preserve stage and smallest verification step.
- **Repeated failure / interrupted agent:** resume by immutable job ID and file hashes, not screenshot coordinates, prompt text or repeated media submission.

**Stop condition:** a full video is `COMPLETE` only after song-locked production, the requested 1080p master, audio/video QC and reproducibility receipts exist. Otherwise report the highest completed gate, blocker and next falsifiable test. Never call a technically generated clip a finished music video.
