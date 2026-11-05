# [PROJECT] — viewable storyboard and shot ledger

**Every approved panel must actually exist as an image. A shot list alone is not a storyboard.** Use stable `C###` concept IDs and `S###` song-locked shot IDs, consistently in Cutroom, prompt book, previews, asset names and manifest.

## A. Concept storyboard — first creative gate

- Revision / status: `concept-v01` / `STORYBOARD_DRAFT` or `STORYBOARD_APPROVED`
- Concept / emotional arc / visual punchline:
- Panels dir: `storyboard/concept-v01/panels/`
- Ordered sheet: `storyboard/concept-v01/contact-sheet.png`
- Approval owner, method and receipt:

| Concept ID | Story function | Visible panel path | Subject/action and camera | Transition | Risk and workaround |
| --- | --- | --- | --- | --- | --- |
| C001 | Opening hook | `panels/C001.png` | | | |
| C002 | Development | `panels/C002.png` | | | |
| C003 | Turn/climax | `panels/C003.png` | | | |
| C004 | Ending | `panels/C004.png` | | | |

**Lock check:** viewable ordered panels; intelligible progression without reading prompts; coverage of beginning, development, turn and ending; characters/props coherent; risks identified; approval actually recorded. Do not generate large batches from a draft.

## B. Timed storyboard — after song lock and timing verification

- Revision / status: `timed-v01` / `TIMED_BOARD_DRAFT` or `TIMED_BOARD_LOCKED`
- Parent concept revision:
- Locked song path / SHA-256 / exact duration:
- Beat/BPM phase and lyric timing validated by:
- Panels dir: `storyboard/timed-v01/panels/`
- Ordered sheet: `storyboard/timed-v01/contact-sheet.png`
- Shot table: `storyboard/timed-v01/shots.csv`
- Optional low-res audio-locked animatic: `storyboard/timed-v01/animatic.mp4`
- Approval receipt:

| Shot ID | Concept | In seconds | Out seconds | Beat/lyric cue | Real panel image | Action/camera/transition | Method/reference | H3 steps, audio policy | Acceptance/continuity |
| --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- |
| S001 | C001 | TBD | TBD | | `panels/S001.png` | | H3 first-frame / T2V / composite / still | 20 default; native audio MUTE unless selected | |

**Do not treat `TBD`, `0.000` placeholders or unchecked overlaps as locked.** Validate exact song coverage including approved transition overlaps. H3 mode is text or **first-frame** reference, not arbitrary multi-frame video conditioning. Configured H3 range is **4–50 steps**, fixed **24 FPS**; 8 steps may be intentionally chosen as an accelerated profile but is **not** the packaged default. Select final settings from live config.

## C. Version/invalidation rules

- Changing only wording of a prompt without altering visual intent → record prompt revision, keep storyboard if still valid.
- Changing shot order, timing, transitions, composition or references → new `timed-vNN` revision and affected shot remap.
- Changing the locked song → invalidate beat map, timed storyboard, sync and edit; rebuild downstream timestamps.
- Changing character/world canon → identify affected image references and video takes; do not blindly discard unrelated work.
- Preserve old contact sheets, rejected panels and approval receipts; no destructive replacement.

## D. Pre-batch go/no-go

- [ ] Concept storyboard actually visible and approved
- [ ] Locked song and verified timing in manifest
- [ ] Timed board has image panels and contact sheet for every shot
- [ ] Full timeline covered, continuity and transitions reviewed
- [ ] Prompt book addresses every H3/video shot ID
- [ ] Source/canon references and rights recorded
- [ ] Current H3 and Cutroom gates independently evaluated
