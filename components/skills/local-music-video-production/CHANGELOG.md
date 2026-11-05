# Changelog

## 3.0 — 5 November 2026

**Merged:** `Archive.tar(9).gz` original `SKILL.md`, the archive's v2 storyboard refinement, and nested `local-music-video-production-h3-upscale-patch.zip` skill, tool map, manifest, visual storyboard template and finishing script. Reconciled with supplied `CREATIVE(1).md`, `OPENWEBUI_MEDIA(1).md`, and the alpha.18 Cutroom README from `rhizome-stack(10).zip`.

**Corrections:** WAN no longer the default; H3 4–50 steps / 20 packaged default with explicitly chosen 8-step speed preset; corrected Qwen/Video/Cutroom ports; replaced `/home/ComfyUI` assumptions with `$RHIZOME_STACK_ROOT`; named actual chat-tool entrypoint; kept Song and native H3 audio separate; distinguished Screening Room settings from standalone upscaler settings.

**Hardening:** concept and timed storyboard approvals as separate gates; real H3 generation vs Cutroom handoff gates; no silent automatic rerun or cloud fallback; one finishing path; explicit preview and delivered-video quality gate; immutable job/shot/source receipts; audit-friendly failure/recovery outcomes.

**Preserved:** existing `h3_lanczos_1080p.sh` implementation (not silently modified), original BLISS lessons, local-only intent and song-first timeline contract. No claim of live installation or GPU acceptance.
