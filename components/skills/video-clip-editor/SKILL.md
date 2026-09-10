---
name: "video-clip-editor"
description: "Trim, cut, name, and verify local video clips with ffmpeg."
---

# Video Clip Editor

Use when the user asks to trim, cut, rename, or make a shareable clip from a local video file. Prefer deterministic `ffmpeg`/`ffprobe` work and keep the source untouched.

## Workflow

1. Inspect the input first:
   - `ls -lh <input>`
   - `ffprobe -hide_banner -show_format -show_streams -print_format json <input>`
   - Do not assume an extension; SSR/Matroska files may have no suffix.

2. Choose the output path:
   - Write beside the input unless the user asks otherwise.
   - Use a clean, descriptive basename from the requested title/game, e.g. `clip-2026-08-16_01.00.00.mkv`.
   - Preserve the original file. If the output exists, use a suffix or ask before overwriting.
   - Default to `.mkv` for Matroska/WebM input or unknown/no-extension containers. Use `.mp4` only when codecs/container compatibility is intended.
   - Keep the temporary file in the same intended container as the final output: use `.tmp.mkv` for Matroska and `.tmp.mp4` for MP4. Renaming a Matroska file to `.mp4` does not convert its container.

3. Convert time ranges carefully:
   - If the user says `from A to B`, compute duration as `B - A` and use `-ss A -t duration`.
   - Example: `00:00:03` to `00:05:23` is `00:05:20`, not `00:05:23` of output.

4. Pick the cut method:
   - Fast/lossless attempt when approximate keyframe boundaries are acceptable:
     ```bash
     ffmpeg -hide_banner -y -ss START -i INPUT -t DURATION -map 0 -c copy -avoid_negative_ts make_zero OUTPUT.tmp.CONTAINER
     ```
   - `CONTAINER` must match the intended final container, for example `mkv` or `mp4`.
   - Always probe the result. If duration includes preroll, starts early, or misses the requested boundary, replace it with an accurate re-encode.
   - Accurate default for user-facing clips:
     ```bash
     ffmpeg -hide_banner -y -i INPUT -ss START -t DURATION -map 0 \
       -c:v libx264 -preset veryfast -crf 22 -pix_fmt yuv420p \
       -c:a aac -b:a 128k OUTPUT.tmp.CONTAINER
     ```
   - Use `libx265` only when the user asks for HEVC/smaller output or the existing workflow clearly prefers HEVC; it is slower and may be less broadly shareable.

5. Verify before reporting done:
   - Probe duration, size, codecs, dimensions, and container:
     ```bash
     ffprobe -hide_banner -show_entries format=format_name,duration,size:stream=index,codec_name,codec_type,width,height,avg_frame_rate \
       -of default=noprint_wrappers=1 OUTPUT.tmp.CONTAINER
     ```
   - Check the duration is within normal encoder tolerance of the requested duration.
   - Confirm the probed container matches the intended final extension.
   - If verification passes, move/rename the temp file to the final output path without changing container type.

6. Final response:
   - Give the final absolute path.
   - State the requested source range and final probed duration.
   - Mention the original was left untouched.

## Notes

- Stream copy is not enough by itself for exact starts: keyframes can preserve a few seconds of preroll. Treat `ffprobe` as the judge.
- For game clips, 1080p/60 H.264 CRF 22 with AAC 128k is a good default balance of speed, compatibility, and size.
- Do not delete source videos or failed outputs unless the user explicitly asks; overwrite temp files freely.
