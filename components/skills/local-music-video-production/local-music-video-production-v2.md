---
name: "local-music-video-production"
description: "Local music-video pipeline using MiniMax Music 3, Qwen Image, Cutroom, and qualified WAN 2.2."
compatibility: Rhizome workstation; loopback-only Cutroom/Qwen Image Desk and MiniMax Music 3; WAN 2.2 video adapter required before video generation.
---

# Local Music Video Production

Use this skill to turn a song or song idea into a reproducible local music-video project. Treat the song as the master clock, separate creative decisions from expensive generation, and preserve enough provenance to reproduce every accepted asset.

Read:
- `references/bliss-method.md` when planning the production or explaining why the gates exist.
- `references/local-tool-map.md` before calling any media tool; live state wins if paths or capabilities differ.
- `templates/production-manifest.md` when creating a project record or handover.

## Governing constraints

- Keep media generation local unless Pingu explicitly authorises another route for the current job.
- Use **MiniMax Music 3** for a new song and save its recipe beside the audio.
- Use **Qwen Image Desk / Qwen Image 2.1** for concept art, character/location references, plates, and controlled edits.
- Use **Cutroom** for song import and analysis, shot planning, asset/take review, song-locked editing, and final FFmpeg render.
- Use **WAN 2.2** for video only after its local Cutroom/ComfyUI adapter is installed and has passed the readiness gate below.
- Do not silently substitute Veo, OpenRouter, Seedance, Midjourney, Suno, LTX, or another provider/model. A named substitute requires a fresh user decision.
- If WAN 2.2 is not ready, finish every non-video artifact and leave the project at `VIDEO_BACKEND_PENDING`. Do not call that a completed video.
- Serialise large local media jobs. The GPUs are shared and image/video/music pipelines must not fight for memory.
- Preserve user work. Use project-local files, immutable successful takes, seeds, recipes, manifests, and recoverable edits.

## Output contract

A production should leave:

1. a locked song or imported-song fingerprint;
2. a brief and research bank;
3. a beat/section/lyric timing map;
4. an approved storyboard and rough song-synchronised animatic before production images or video;
5. a shot list tied to exact song time and storyboard panel IDs;
6. an editable visual bible based on the approved storyboard;
7. a complete prompt book before bulk generation;
8. approved Qwen reference assets with seeds and provenance;
9. WAN takes with review decisions when the backend is qualified;
10. a song-locked Cutroom timeline;
11. the rendered master plus manifest, shot list, prompts/seeds, QC notes, and render log.

Mark each stage `DRAFT`, `LOCKED`, `BLOCKED`, or `COMPLETE`. A later stage does not erase an earlier unresolved gate.

## Workflow

### 1. Establish the production brief

Capture:

- song source: create with MiniMax Music 3 or import an existing track;
- emotional arc and the one-sentence idea;
- intended audience/platform, aspect ratio, resolution, frame rate, and duration;
- performance, narrative, lyric-video, motion-design, or hybrid balance;
- recurring character/location/object canon;
- rights-sensitive source material and any assets that must remain exact;
- constraints on time, hardware, style, and content.

Write a falsifiable acceptance line such as: “A three-minute 16:9 video whose cuts and visual changes land on the locked song structure, with the same lead character and wardrobe canon across all precision shots.”

### 2. Build focused research banks

Research only what changes prompts, design, timing, or rights decisions. Typical banks:

- musical/genre grammar and reference vocabulary;
- story, metaphor, cultural references, or joke/pun map;
- wardrobe, character, location, prop, and colour/shape language;
- motion/camera grammar;
- typography, interface, or motion-design system;
- source audio/SFX that can legally be used;
- known limitations of the current local models.

Label facts, taste decisions, hypotheses, and borrowed references separately. Prefer authentic source artifacts where their exactness carries meaning; record provenance and rights status.

### 3. Create and lock the song

If making a new song:

1. Use MiniMax Music 3.
2. Write the brief as Global Metadata → Vocal Details → Arrangement.
3. Use section tags to control structure.
4. Generate bounded variants with recorded seeds.
5. Compare the actual audio, choose one take, and freeze its audio file and companion JSON recipe.

If importing a song, fingerprint the exact source file and do not alter it silently.

After lock:

- record duration, sample format, file hash, recipe path, and chosen take;
- do not regenerate or replace it without reopening the song gate;
- treat it as the single master clock for every later edit.

### 4. Analyse the locked audio

Import the song into Cutroom and generate its waveform, BPM estimate, beats, bars, energy, broad structure, and editable cut plan.

Verify the beat grid against audible anchors. Automated beat tracking can sit early or late; correct the phase before timing cuts. Add exact lyric/word timing when visible lyrics or lip sync matter.

Create a timing map containing:

- song sections and section boundaries;
- beats/bars used for cuts;
- vocal entries, lyric phrases, instrumental hits, and quiet spaces;
- energy curve and narrative turning points;
- intentional holds where the edit should breathe.

### 5. Storyboard FIRST, before production assets

After song lock and beat-grid verification, turn the brief into a **complete beginning-to-end storyboard**. This is the mandatory creative approval gate before producing Qwen character plates or WAN footage. A short text/thumbnail concept sketch is acceptable here; do not spend GPU time making polished production art to discover the story.

- Divide the song into sections, then panels/shots with stable IDs, exact in/out times, section/lyric/beat anchors, narrative purpose, visual action and emotional change.
- Specify subject, framing, camera movement, environment, transitions, on-screen words, overlays and intended SFX. Call out repeated subjects, props and costumes that will require canon.
- Label each panel with its intended method: still, I2V, T2V, deterministic overlay/composite, or intentional hold. Do not assert an unqualified backend is ready.
- For each panel, record expected duration, shot dependencies, failure fallback, and one observable acceptance test.
- Assemble a **rough animatic** against the locked song in Cutroom when the current Cutroom supports it; otherwise make a local time-coded sequence from simple text cards/placeholders and record that limitation. No unsupported Cutroom capability should be claimed.
- Watch it from start to finish. Check narrative clarity, actual pacing, lyric coverage, empty sections, cut positions, excessive shot counts and required continuity. Fix the sequence before buying/generating hundreds of assets.
- Save storyboard source, panels or contact sheet, version/hash, animatic path (or documented blocker), and an explicit `STORYBOARD_APPROVED` decision in the manifest. Approval is a recorded human creative decision; the agent may propose revisions but must not silently mark its own unreviewed draft approved.

**Gate:** `STORYBOARD_DRAFT` → `STORYBOARD_APPROVED`. No production reference/plate batch, video prompt submission or bulk video generation before approval. A narrowly bounded feasibility test may be separately labelled as such and must not be passed off as approved production content.

### 6. Lock the visual bible FROM the storyboard

Use the approved panels to identify the *actual* characters, locations, wardrobe and recurring objects required. Define stable identity before generating production references:

- character face, hair, wardrobe, silhouette, and recurring identifiers;
- location geometry and persistent props;
- palette described with names and values, not colour alone;
- lighting/time-of-day states;
- lens, framing, texture, era, typography, and motion rules;
- negative constraints and known continuity risks.

Use Qwen Image Desk to make **small, storyboard-driven** contact sheets and controlled reference edits. Approve canonical images, attach them to the corresponding storyboard/Cutroom shot IDs, and preserve original prompt, expanded/edited prompt, seed, dimensions, model provenance, output path and reference relationship.

If the canon changes the story, revise the storyboard and animatic and re-approve the affected panels. Do not bulk-generate until both storyboard and canon survive a revision round.

For interface-heavy, lyric-heavy or geometry-sensitive concepts, design a deterministic overlay or reusable visual engine before video generation. Let generated footage supply organic motion; let code/FFmpeg own exact text, cursor paths, timing and repeatable layout.

### 7. Finish the storyboard-derived prompt book before submitting video jobs

Write the complete first-round WAN prompt book from the approved storyboard panel IDs and locked visual bible in one coherent context before queueing it. This protects character canon, camera grammar, and terminology from prompt drift.

Each prompt should state:

- the approved reference/canon;
- subject and action;
- setting, time, and lighting;
- framing/lens/camera path;
- temporal beats inside the clip;
- motion intensity;
- what must remain unchanged;
- negative guidance;
- seed strategy and expected usable interval.

Use Qwen reference plates for identity and composition. Prefer I2V for continuity-critical shots and T2V only where reference fidelity is not required.

### 8. WAN 2.2 readiness gate

Before the first real production uses WAN 2.2, prove on this box:

- the exact model files and adapter ID are recorded;
- T2V completes and returns playable local footage;
- reference-led I2V completes where supported;
- several seeds produce real motion rather than a held frame;
- output timing/frame count is correct;
- cancellation and bounded retry work;
- failed jobs preserve diagnostics without overwriting successful takes;
- model/VRAM ownership is serialised with Qwen and MiniMax;
- idle release returns the machine to its expected state;
- a kept take survives the real Cutroom-to-FFmpeg final-render path.

Until all checks pass, stop at `VIDEO_BACKEND_PENDING`.

### 9. Pilot before volume

Run two or three representative clips:

- one continuity-critical character shot;
- one high-motion or camera-motion shot;
- one difficult lighting/composition shot.

Review actual motion frame-by-frame. A good first frame is not a good video. If the pilot exposes a systematic defect, change the prompt book or adapter once, then rerun the pilot. Do not burn through the full shot list while the hypothesis is failing.

### 10. Generate serially and review ruthlessly

Submit bounded batches through the local queue. Keep prompt, negative, seed, model/adapter, dimensions, frame count, reference, timestamps, and output path with every take.

Classify every take in Cutroom:

- **KEEP** — works as intended;
- **SALVAGE** — usable with trim, crop, speed, reverse, cover, or overlay;
- **REGENERATE** — the shot is needed but this take fails;
- **BIN** — no production value.

Check:

- identity, wardrobe, anatomy, props, and location continuity;
- temporal coherence and real motion;
- camera path and framing;
- lip-sync interval if applicable;
- exact usable start/end;
- artifacts hidden by a cut versus artifacts that remain visible.

Bound retries. Change one meaningful variable at a time and record what the retry is testing.

### 11. Edit to the song, not to clip length

Arrange approved takes on the Cutroom waveform timeline. The source song remains authoritative. Trim generated clips to slots, hold only when intentional, and never silently loop a short take.

Use deterministic tools for:

- exact typography and lyric coverage;
- titles and interface elements;
- trim, reverse, speed, crop/fit, fades, and compositing;
- beat-locked actions;
- stable repeated layout.

For lip sync, measure the interval that actually holds and cut to a cover shot before divergence. For lyric videos, verify every required token appears at the intended time.

### 12. Build the sound layer deliberately

Keep generated music and production SFX separate. Place SFX as musical events where appropriate:

- align transients to the beat grid;
- tune tonal cues to the song key where useful;
- duck cues under intelligible vocals;
- preserve the locked song's perceived balance;
- record each cue and source.

Do not upload copyrighted or third-party sounds into a model unless the usage terms and rights permit it.

### 13. Validate seams and render

Before the master render:

- inspect every chapter/scene seam on frames immediately before and after the cut;
- confirm full timeline coverage, no unintended gaps/loops/holds, and exact final duration;
- verify lyric/text coverage where applicable;
- inspect representative motion and continuity at full output size;
- confirm audio sync, loudness, clipping, and final-frame behaviour;
- verify all used paths exist and all accepted assets have provenance.

Render through Cutroom/FFmpeg. Record codec, resolution, frame rate, colour metadata, audio settings, duration, file hash, and log path.

### 14. Close with receipts and learning

Produce a short report containing:

- what was made and which gates passed;
- model/tool versions and local/remote status;
- accepted assets and unresolved defects;
- retries, failures, and discarded hypotheses;
- render/hash/log receipts;
- exact resume point if incomplete;
- one or two lessons that should change the next production.

Do not hide known defects behind “complete”. Separate observed defects from inferred causes.

## Failure handling

- **Permission or path wait:** keep unattended work inside already permitted project paths; checkpoint before launching a long batch.
- **OOM/resource collision:** pause submission, preserve the live job record, release the owning engine cleanly, and retry only with a proven bounded fallback.
- **Storyboard drift:** stop work, revise affected panels and animatic, and regain explicit creative approval before regenerating.
- **Prompt drift:** stop bulk work, return to the approved storyboard, locked canon and prompt book, and change one systematic cause.
- **Bad beat phase:** retime the grid before further editing.
- **Weak video backend:** finish planning/references and stop at `VIDEO_BACKEND_PENDING`; do not route around the local-only decision.
- **Partial lip sync:** use measured good intervals and planned covers rather than pretending the whole clip holds.
- **Automation mismatch:** match outputs by immutable job ID and provenance, not identical prompt text or screen position.
- **Repeated failure:** use the risk-aware retry policy; after bounded evidence, mark the route dead and change the hypothesis.

## Stopping rule

The job is complete only when the requested master and its reproducibility bundle exist and pass the agreed checks. If a backend or creative decision blocks completion, leave a precise resumable handover with finished artifacts, the failed gate, evidence, and the smallest next test.
