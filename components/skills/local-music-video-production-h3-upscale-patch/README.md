# Local music-video skill patch — H3 + storyboard-first correction

Main creative stack: **GPT-5.6-Sol** (planning/orchestration), **Qwen Image 2.1** (visuals), **MiniMax Music 3** (songs), and **MiniMax H3** (video).

Current video backend: **MiniMax H3 NF4 Turbo + Sol + Spectrum**, **4–24 steps**, **8 default**, **text or first-frame I2V**, **native stereo audio**. This corrects the stale WAN 2.2 assumption.

- `scripts/h3_lanczos_1080p.sh`: a verbatim bundled copy of the user-provided Real-ESRGAN native-4x → Lanczos 1080p script (SHA-256: `df59765b06df02e2c15a747127c7f01e9f3d9cf3ee2887f696324399ff6e1cab`).
- `SKILL.md`: two-stage storyboard approval (concept panels first, timed visual board after song lock), H3-specific generation settings, audio separation, separate Cutroom/H3 readiness gates, and the 1080p delivery gate.
- `references/local-tool-map.md`: local MiniMax Music 3 vs MiniMax H3 roles, video provenance and Cutroom handoff caveat.
- `templates/production-manifest.md`: records H3 engine settings, video/take audio, standalone tests, Cutroom status, intermediate/final hashes and 1080p QC independently.
- `templates/storyboard-template.md`: viewable storyboard and H3 shot settings.

**Status honesty:** historical local H3 text/video and first-frame/video plus audio tests exist, but this patch has not inspected the user's live workstation or proven the current H3 → Cutroom → FFmpeg path. `H3_ENGINE_VERIFIED` is historical evidence; `CUTROOM_INTEGRATION_PENDING` remains until measured. This package modifies documents only; it does not deploy files.

Keep the already-existing `references/bliss-method.md`: it was not supplied with the three original Markdown files and is intentionally not fabricated here.

## 1080p finishing

Default: approved storyboard → generated H3 takes → Cutroom edit/locked song master → script preview on assembled video → Real-ESRGAN native 4x then Lanczos 1920×1080 → final QC. If exact text/graphics are harmed, upscale the accepted H3 picture clips first and add sharp text in Cutroom/FFmpeg at 1080p. Always keep the source unchanged.

Syntax of the supplied shell script was checked with `bash -n`. No Real-ESRGAN GPU upscale or full end-to-end integration was executed, so GPU/model paths and final output remain to be tested on the Z440.
