# Storyboard — [project name]

This is a **visual deliverable**, not just a prompt or text shot list. Export a contact sheet with panels in order. Use the same stable panel/shot IDs throughout the manifest, prompt book and Cutroom shot records.

## A. Concept storyboard (create FIRST)

- Status: `STORYBOARD_DRAFT | STORYBOARD_APPROVED`
- Revision:
- Concept/one-sentence hook:
- Rough song sections or planned story sequence:
- Character and setting continuity note:
- Panels directory: `storyboard/concept-v01/panels/`
- Contact sheet: `storyboard/concept-v01/contact-sheet.png`
- Director/acceptance record:

| Concept panel | Scene beat / story purpose | Image panel path | What appears / action | Framing & transition | Risks / alternative |
| --- | --- | --- | --- | --- | --- |
| C01 | Opening / establish hook | `panels/C01.png` | [visual description] | [wide, cut to C02] | [risk, alternative] |
| C02 | Development | `panels/C02.png` | [visual description] | [move, transition] | [risk, alternative] |
| C03 | Turning point | `panels/C03.png` | [visual description] | [move, transition] | [risk, alternative] |
| C04 | Ending / payoff | `panels/C04.png` | [visual description] | [final image/hold] | [risk, alternative] |

**Approval checklist:** Viewable panels exist; contact sheet is readable in order; beginning/middle/ending make sense without the prompts; continuity and the punchline are clear; revisions are recorded. **Do not mark approved merely because the files exist.**

## B. Timed storyboard (after accepted song + verified beat grid)

- Status: `TIMED_BOARD_DRAFT | TIMED_BOARD_LOCKED`
- Revision:
- Parent concept revision:
- Locked song SHA-256:
- Song duration / corrected BPM / beat phase:
- Timed panels directory: `storyboard/timed-v01/panels/`
- Contact sheet: `storyboard/timed-v01/contact-sheet.png`
- Timed shot list: `storyboard/timed-v01/shots.csv`
- Optional still-frame animatic over locked audio: `storyboard/timed-v01/animatic.mp4`
- Director/acceptance record:
- Intended delivery: H3 source resolution → Real-ESRGAN x4 + Lanczos 1920×1080 (or explicit fallback); specify any sharp text/overlay needing a post-upscale render.

| Shot ID | Concept ID | In (s) | Out (s) | Beat/lyric | Panel image | Action + camera | Transition | Method | H3 steps/audio plan | Continuity / checks |
| --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- |
| S001 | C01 | 0.000 | 0.000 | [section] | `panels/S001.png` | [subject, movement] | [cut] | [H3 text / H3 first-frame / still / composite] | [8 default; native audio muted unless selected] | [what must match] |

Fill with real timestamps after timing analysis. **Never keep placeholder `0.000` as if a real shot slot were locked.** Every final shot must point to a viewable image panel. For H3-generated shots record whether the input is text or an approved first-frame image, selected **4–24 steps (8 default)**, and whether native audio is retained only as provenance or explicitly used in the mix.

## C. Version and dependency rules

- Editing only a prompt for a locked shot: record prompt revision; storyboard may stay locked if visual intent is unchanged.
- Editing shot composition, location, transitions or order: bump timed storyboard revision, recheck affected neighbours and update dependent shots.
- Changing locked audio: invalidate beat map and `TIMED_BOARD_LOCKED`, regenerate exact timestamps and animatic.
- Changing character/prop canon: identify affected panel IDs, references and generated takes before continuing.
- Keep rejected panels and earlier boards for provenance; do not overwrite approved versions.

## D. Lock test

Before any large reference/image/video batch, verify: (1) complete visible panels, (2) readable ordered contact sheet, (3) exact song coverage, (4) intentional transitions and holds, (5) director acceptance or agreed automated criteria, (6) a path from each panel to its Cutroom shot ID. If one fails, keep status `TIMED_BOARD_DRAFT`.
