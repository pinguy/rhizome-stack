# Video Desk

Video Desk is a loopback-only browser app for local WAN 2.2 Rapid and MiniMax
H3 FL2VA pruned NF4 generation.

## Generation

- Text or first-frame Image input.
- WAN Rapid v10 Q5_K: 480p/720p, 16 or 24 FPS, 1–10 seconds, 4–20 steps.
- MiniMax H3 NF4: 480p/720p, fixed 24 FPS, `17n+5` frames, 1–15 seconds,
  4–50 steps and native 32 kHz stereo audio.
- Optional OpenClaw prompt expansion and persistent local take history.
- Exact-process ownership: H3 may stop this Desk's ComfyUI, never an external
  process.

## 1080p mastering

Screening Room offers Lanczos-only mastering or Real-ESRGAN NCNN/Vulkan 4×
enhancement followed by a Lanczos 1920×1080 master. Lanczos uses FFmpeg with no
extra weights. Real-ESRGAN requires `VIDEO_UPSCALER_NCNN_BIN` and
`VIDEO_UPSCALER_NCNN_MODELS`; its external executable and model pair are not
bundled. Both paths preserve audio, validate frame count and resolution, use a
single-flight lock, report progress and clean temporary data.

## Model/runtime boundary

`--download-creative-models` downloads the revision-pinned, SHA-256-verified WAN
and H3 files listed in `manifests/creative-models.json`. DiffSynth-Studio is
checked out at the pinned commit from `manifests/versions.json`; H3-only Python
additions live under `$RHIZOME_STACK_ROOT/creative/h3-runtime`.

Generated projects, references, MP4 files, logs, weights and queue state remain
under the installed stack's runtime directory. None are in the release archive.
