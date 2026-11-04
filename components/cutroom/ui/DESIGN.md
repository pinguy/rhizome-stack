# Cutroom unified design contract

## Subject and job

Cutroom is for one person making a local AI music video. Its single job is
to turn a finished song, planned shots and generated takes into a controlled,
recoverable master without hiding the song clock.

## Visual system

- **Black room** `#080a0f`: monitor and edit-suite background.
- **Bench** `#0d1017`: primary panels.
- **Steel** `#282f3d`: boundaries and inactive controls.
- **Timecode cyan** `#56daf2`: active selection and navigational truth.
- **Cue amber** `#ffb32e`: playhead and time-sensitive actions.
- **Take purple** `#8164d5`: generated-media accents.
- Noto Sans for interface text and Noto Sans Mono for clocks, seeds and metadata.

## Signature

The timeline begins with a labelled song-structure strip. Beats, waveform,
sections and video cuts share the same absolute clock. This is the part that
must remain recognisably Cutroom rather than becoming a generic NLE shell.

## Layout

```text
Single production navigation and document controls
Context library | working canvas | contextual inspector
Direct / Build / Shoot / Cut / Finish in one shell
Song sections, V1 shots and A1 master waveform in Cut
```

The deliberate risk is showing musical structure as a first-class timeline
track instead of hiding it behind markers. Everything else stays restrained.
