# Production manifest — [project name]

## Status and gate ownership
- Overall: DRAFT | BLOCKED | COMPLETE
- Current gate:
- Next falsifiable test:
- Project root:
- Director/approval source:
- Last locked artifact / revision:

## 1. Brief
- One-sentence concept:
- Beginning / turning point / ending:
- Emotional arc:
- Format/aspect/resolution/fps:
- Intended platform/audience:
- Song: new MiniMax Music 3 | imported
- Acceptance line:
- Constraints / source rights:
- Status: DRAFT | LOCKED

## 2. CONCEPT STORYBOARD — FIRST CREATIVE GATE
- Status: STORYBOARD_DRAFT | STORYBOARD_APPROVED
- Version / revision:
- Panels directory:
- Ordered contact sheet path:
- Storyboard source (MD/CSV):
- Panel count and section order:
- Story/message readable from panels alone? PASS | FAIL
- Beginning / development / turn / climax / ending covered? PASS | FAIL
- High-risk shots / planned alternatives:
- Approval / acceptance record:
- Changes requested:

## 3. Research banks
- Music/genre/scansion:
- Story/facts/reference map:
- Visual/wardrobe/location:
- Motion/camera:
- Typography/motion design:
- Sound sources and rights:
- Model/backend limitations:

## 4. Song lock
- Source: MiniMax Music 3 | imported
- Audio path:
- Recipe path / seed / engine:
- SHA-256:
- Duration/sample format:
- Song sections:
- Status: DRAFT | LOCKED

## 5. Timing map
- BPM and corrected beat/grid phase:
- Sections and exact timestamps:
- Beat/bar anchors:
- Lyric/word timing:
- Energy/narrative turns:
- Intentional holds:
- Verification evidence:
- Status: DRAFT | LOCKED

## 6. TIMED VISUAL STORYBOARD — REQUIRED BEFORE GENERATION
- Status: TIMED_BOARD_DRAFT | TIMED_BOARD_LOCKED
- Based on concept board revision:
- Based on song SHA-256:
- Version / revision:
- Per-shot illustrated panels directory:
- Ordered contact sheet path:
- Timed shot table path:
- Low-fidelity animatic path (if made):
- Each shot has real panel image? PASS | FAIL
- Each shot maps to an exact music slot? PASS | FAIL
- All sections covered with no unplanned gaps? PASS | FAIL
- Transitions and scene continuity reviewed? PASS | FAIL
- Director's approval or agreed lock criterion:
- Changes / invalidated dependencies:

## 7. Visual bible and approved references
- Character canon:
- Wardrobe:
- Locations/props:
- Lighting/time states:
- Palette with labelled values:
- Framing/lens/texture:
- Negative constraints:
- Canon Qwen reference paths/seeds/model provenance:
- Mapped storyboard shot IDs:
- Status: DRAFT | LOCKED

## 8. Prompt book
- File path / hash:
- Source timed-storyboard revision:
- Source visual-bible revision:
- Coverage of all video shot IDs: PASS | FAIL
- Pilot-shot selection and hypotheses:
- Status: DRAFT | LOCKED

## 9. Backend gates
- Qwen Image ready (observed test):
- MiniMax Music 3 ready (observed test):
- MiniMax H3 engine state: H3_ENGINE_VERIFIED | VIDEO_BACKEND_PENDING | RECHECK_REQUIRED
- H3 workflow/model revision / NF4 / Turbo / Sol / Spectrum settings:
- H3 T2V observed evidence (job ID, path, media probe):
- H3 first-frame I2V observed evidence (job ID, reference hash, media probe):
- H3 native audio observed (codec/channels/sync):
- H3 steps allowed 4–24; selected default: 8
- GPU text-conditioning mode and fallback verified:
- H3 job/cancellation/retry evidence:
- Cutroom adapter or manual-file handoff verified:
- Cutroom shot attachment / audio handling verified:
- Cancellation / bounded retry:
- GPU serialisation / idle release:
- Real Cutroom → FFmpeg render test:
- Cutroom integration state: CUTROOM_VERIFIED | CUTROOM_INTEGRATION_PENDING
- Video engine state: H3_ENGINE_VERIFIED | VIDEO_BACKEND_PENDING | RECHECK_REQUIRED

## 10–13. Shot production, editing and sound
For each shot, store in shot table or storyboard source:
- ID, original concept panel ID and timed-board panel image;
- exact start/end; purpose/lyric and beat anchor;
- action, framing, camera and environment;
- character/location reference path and version;
- generation mode (I2V/T2V/composite/deterministic/still);
- prompt, negative, seed, steps (4–24, 8 default), NF4/Turbo/Sol/Spectrum version/state, job/take provenance;
- native H3 audio path/codec/channels/sync and decision (MUTE | USE | MIX), locked-song alignment;
- continuity dependencies; acceptance/rejection checks;
- take decision (KEEP/SALVAGE/REGENERATE/BIN) and usable interval.

- Cutroom project path:
- Timeline coverage:
- Text/lyric coverage:
- Lip-sync measured intervals:
- Continuity defects:
- H3 native-audio editorial decisions (default MUTE):
- Sound effects / rights / locked-song mix:
- Storyboard deviations and revision records:

## 14. Render, 1080p upscale and QC
- Cutroom assembled intermediate path / hash:
- Input dimensions/fps/duration/audio stream (ffprobe):
- Upscale order: ASSEMBLED_MASTER_THEN_ESRGAN | ACCEPTED_H3_CLIPS_THEN_CUTROOM
- Upscaler source/install path / SHA-256:
- Method: ESRGAN_X4_PLUS_LANCZOS | LANZCOS_CPU_FALLBACK | OTHER_APPROVED
- Real-ESRGAN executable and models path verified:
- Model name / exact NCNN model files:
- Vulkan GPU ID / confirmed RTX 3060 startup log:
- Native ESRGAN scale: 4x (do not use x4plus -s 2)
- Target: 1920×1080, aspect preserved, setsar=1
- Tile size / temporary PNG path / disk budget:
- x264 preset / CRF (default slow / 17):
- Preview command / preview path / visual PASS | FAIL:
- Preview artefacts / rejected settings:
- Full command / logs / exit status:
- Final 1080p video path / SHA-256:
- Final ffprobe dimensions/fps/duration/codec/audio:
- Full-playback visual QC / audio-sync QC:
- Final exact-text/overlay fidelity checked:
- Upscale status: UPSCALE_PENDING | UPSCALE_VERIFIED
- Unresolved defects:
- Final status: BLOCKED | COMPLETE

## 15. Receipts and handover
- Brief / concept-board paths:
- Song fingerprint/recipe:
- Timing / timed-board paths:
- Visual bible / reference provenance:
- Prompt book / shot list:
- Accepted takes / immutable job IDs:
- Intermediate hash / final 1080p hash / upscale command+logs / tool versions:
- Local/remote usage confirmation:
- Failed gates / exact resume point:
- Lessons learned:
