# Local Music Video Production — consolidated v3

A complete, **single** Rhizome/OpenClaw-style production skill. This replaces the original WAN-first root skill **and** the nested H3/upscale patch. It is documentation plus a preserved optional local finishing script, **not** a model installer or a running service.

## What changed

- **One authoritative `SKILL.md`:** two visual storyboard gates, song lock, image references, H3, Cutroom, QC, reproducibility and failure handling. No stale parallel `SKILL.md` inside a patch ZIP.
- **Correct alpha.18 packaged ports:** Qwen **8841**, Video Desk **8840**, Cutroom **8842**, Cutroom backend **8843**, MiniMax Music **8830**.
- **Correct H3 contract:** 1–15 seconds, 24 FPS, 4–50 steps, Open WebUI **20-step default**. Historical **8-step fast mode** remains allowed as an explicitly selected choice. `wan_video.create_video` is the relevant registered media tool for both H3 and WAN when available.
- **Separate engine and editor gates:** an H3 clip working does not prove Cutroom's file import/trim/render path.
- **Two finishing implementations explained:** packaged Screening Room and independent `h3_lanczos_1080p.sh` have different config variables. Choose one route per deliverable, preview, then QC; don't double upscale.
- **Honest capability handling:** bundled docs are snapshots, not evidence of current service state; no invented approval or hardware performance claims.
- **Templates and reference updated:** explicit revision invalidation, per-shot take metadata, soundtrack/native audio isolation, render and integrity receipts.

## Install into an agent workspace

1. Extract the folder to a **new** location, for example `~/.openclaw/workspace/skills/local-music-video-production/` (illustrative path; inspect your actual skill-loading convention).
2. Compare its existing `SKILL.md`, `references/`, `templates/`, and `scripts/` against this version; back up the old folder before replacing it. **Do not overwrite your working runtime scripts by default.**
3. Load/restart the skill using whatever mechanism your OpenClaw version actually supports. This archive does **not** change Rhizome Stack files by itself.
4. Check `rhizome-stack creative status`, inspect available model/tool config, and prove one short local canary for each needed stage. An existing running media job must not be interrupted.
5. Make a test storyboard and a tiny pilot before production.

## Contents

- `SKILL.md` — single source of production logic and gates
- `references/local-tool-map.md` — current packaged interfaces and runtime caveats
- `references/bliss-method.md` — preserved transferable source production lessons, with updated local engine choice
- `templates/storyboard-template.md` — concept + timed **visual** boards
- `templates/production-manifest.md` — complete gate ledger, shots and receipts
- `scripts/h3_lanczos_1080p.sh` — **preserved** original optional finishing script; no algorithmic changes
- `tests/check_package.py` — package sanity checks
- `CHANGELOG.md` — input and change summary

## Limits of verification

This package was consolidated from the uploaded archived skill, bundled H3 patch, current creative documentation and Cutroom source README. It can be validated for completeness and shell syntax here; **it cannot prove current live ComfyUI, model weights, lip-sync, H3→Cutroom adapter, or real 3060 Vulkan rendering** without testing on that workstation. The script's Real-ESRGAN binary/model files are not redistributed.

Nothing is pushed to GitHub or installed on the live machine by producing this ZIP.
