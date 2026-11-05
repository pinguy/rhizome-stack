#!/usr/bin/env bash
# H3 video upscaler: Real-ESRGAN (NCNN/Vulkan) at native 4x,
# then Lanczos finish to 1080p; or the original CPU-only Lanczos fallback.
# Fixed 2026-10-30: x4plus -s 2 causes scrambled/zoomed tiles (upstream #73).
# No modifications to ComfyUI, Python, CUDA or your NVIDIA driver.
set -Eeuo pipefail

usage() {
  cat <<'HELP'
Usage:
  h3_upscale_1080p.sh [OPTIONS] INPUT_VIDEO [OUTPUT_MP4]

Options:
  --mode esrgan|lanczos          Neural upscaling (default) or original CPU-only mode
  --model NAME                  realesrgan-x4plus (default), realesr-animevideov3,
                                realesrgan-x4plus-anime, realesrnet-x4plus
  --gpu ID                      NCNN Vulkan GPU ID (default: choose RTX 3060 if detected)
  --list-gpus                   Show available Vulkan device IDs and exit
  --tile N                      GPU tile size, 0=automatic (default: 0)
  --seconds N                   Preview only first N seconds (e.g., 2)
  --preset NAME                 x264 preset, e.g. medium, slow (default: slow)
  --crf N                       x264 quality, lower=better (default: 17)
  --keep-frames                 Leave extracted/upscaled PNGs for debugging
  -h, --help                    Show help

Environment (if automatic binary lookup is not right):
  REALESRGAN_BIN=/home/you/opt/realesrgan/realesrgan-ncnn-vulkan
  REALESRGAN_MODELS=/home/you/opt/realesrgan/models
  H3_TMP_DIR=/path/on/fast/drive

Examples:
  ./h3_upscale_1080p.sh --list-gpus
  ./h3_upscale_1080p.sh --gpu 0 --seconds 0.2 dragon.mp4 dragon_test.mp4
  ./h3_upscale_1080p.sh --gpu 0 dragon.mp4
  ./h3_upscale_1080p.sh --mode lanczos dragon.mp4 dragon_lanczos.mp4
HELP
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"; }

mode=esrgan
model=realesrgan-x4plus
gpu=''
tile=0
seconds=''
preset=slow
crf=17
keep_frames=0
args=()
while (( $# )); do
  case "$1" in
    --mode|--model|--gpu|--tile|--seconds|--preset|--crf)
      opt=$1
      (( $# >= 2 )) || die "Missing value for $opt"
      val=$2
      case "$opt" in
        --mode) mode=$val ;;
        --model) model=$val ;;
        --gpu) gpu=$val ;;
        --tile) tile=$val ;;
        --seconds) seconds=$val ;;
        --preset) preset=$val ;;
        --crf) crf=$val ;;
      esac
      shift 2 ;;
    --keep-frames) keep_frames=1; shift ;;
    --list-gpus)
      if command -v vulkaninfo >/dev/null 2>&1; then
        vulkaninfo --summary 2>/dev/null | grep -E "^[[:space:]]*GPU[0-9]+:|deviceName[[:space:]]*=" || true
        echo "These are Vulkan IDs; check the Real-ESRGAN startup log to confirm the selected GPU."
      else
        echo "Install vulkan-tools (sudo pacman -S --needed vulkan-tools) to list Vulkan GPUs." >&2
        exit 1
      fi
      exit 0 ;;
    -h|--help) usage; exit 0 ;;
    --) shift; args+=("$@"); break ;;
    -*) die "Unknown option: $1" ;;
    *) args+=("$1"); shift ;;
  esac
done

(( ${#args[@]} >= 1 && ${#args[@]} <= 2 )) || { usage >&2; exit 2; }
[[ "$mode" == esrgan || "$mode" == lanczos ]] || die "--mode must be esrgan or lanczos"
[[ "$model" =~ ^(realesrgan-x4plus|realesr-animevideov3|realesrgan-x4plus-anime|realesrnet-x4plus)$ ]] || die "Unsupported model name: $model"
[[ "$tile" =~ ^[0-9]+$ ]] || die "--tile needs a non-negative integer"
[[ -z "$gpu" || "$gpu" =~ ^[0-9]+$ ]] || die "--gpu must be a non-negative Vulkan device ID"
[[ "$crf" =~ ^[0-9]+$ ]] && (( crf <= 51 )) || die "--crf must be 0-51"
[[ "$preset" =~ ^(ultrafast|superfast|veryfast|faster|fast|medium|slow|slower|veryslow)$ ]] || die "Unknown x264 preset: $preset"
if [[ -n "$seconds" ]]; then
  [[ "$seconds" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "--seconds must be a positive number"
  awk -v s="$seconds" 'BEGIN {exit !(s > 0)}' || die "--seconds must be greater than zero"
fi

need ffmpeg
need ffprobe
need awk
need find
need mktemp

input=${args[0]}
[[ -f "$input" ]] || die "Input file does not exist: $input"
input=$(realpath -- "$input")

if (( ${#args[@]} == 2 )); then
  output=${args[1]}
else
  suffix=_1080p_esrgan
  [[ "$mode" == lanczos ]] && suffix=_1080p_lanczos
  [[ -n "$seconds" ]] && suffix+='_preview'
  output="${input%.*}${suffix}.mp4"
fi
[[ "$output" == *.mp4 ]] || die "Output filename must end in .mp4"
[[ ! -e "$output" ]] || die "Output already exists; refusing to overwrite: $output"
output_parent=$(dirname -- "$output")
[[ -d "$output_parent" && -w "$output_parent" ]] || die "Output directory missing or not writable: $output_parent"
output=$(realpath -m -- "$output")
[[ "$input" != "$output" ]] || die 'Input and output must differ'

filter='scale=1920:1080:flags=lanczos+accurate_rnd+full_chroma_int:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1,format=yuv420p'

echo "Input:  $input"
echo "Output: $output"
echo "Method: $mode -> 1920x1080, aspect preserved, H.264 CRF $crf ($preset)"

if [[ "$mode" == lanczos ]]; then
  cmd=(ffmpeg -hide_banner -stats -nostdin -n -i "$input")
  [[ -z "$seconds" ]] || cmd+=(-t "$seconds")
  "${cmd[@]}" -map 0:v:0 -map '0:a?' -vf "$filter" \
    -c:v libx264 -preset "$preset" -crf "$crf" -pix_fmt yuv420p \
    -c:a copy -movflags +faststart "$output"
  echo "DONE: $output"
  exit 0
fi

# Resolve an explicitly supplied binary or the normal standalone installation.
real_bin=${REALESRGAN_BIN:-"$HOME/opt/realesrgan/realesrgan-ncnn-vulkan"}
if [[ ! -x "$real_bin" ]]; then
  if command -v realesrgan-ncnn-vulkan >/dev/null 2>&1; then
    real_bin=$(command -v realesrgan-ncnn-vulkan)
  else
    die "Real-ESRGAN missing. Install under ~/opt/realesrgan or set REALESRGAN_BIN. See setup instructions."
  fi
fi
real_bin=$(realpath -- "$real_bin")
models_dir=${REALESRGAN_MODELS:-"$(dirname "$real_bin")/models"}
[[ -f "$models_dir/$model.param" && -f "$models_dir/$model.bin" ]] || \
  die "Missing model files in $models_dir ($model.param and $model.bin)"

fps=$(ffprobe -v error -select_streams v:0 -show_entries stream=avg_frame_rate \
      -of default=noprint_wrappers=1:nokey=1 "$input" | head -n 1)
[[ "$fps" =~ ^[0-9]+(/[0-9]+)?$ && "$fps" != '0/0' && "$fps" != '0' ]] || \
  die "Unsupported frame rate ($fps); expected a constant frame rate video"

# Place large temporary PNG sequences on the output drive, not tmpfs (/tmp).
tmp_root=${H3_TMP_DIR:-$output_parent}
[[ -d "$tmp_root" && -w "$tmp_root" ]] || die "Temporary directory is not writable: $tmp_root"
tmp=$(mktemp -d "$tmp_root/h3-upscale.XXXXXXXX")
cleanup() {
  if (( keep_frames )); then
    printf '\nKept temporary PNG frames at: %s\n' "$tmp"
  else
    rm -rf -- "$tmp"
  fi
}
trap cleanup EXIT
mkdir -p "$tmp/input" "$tmp/upscaled"

# The models bundled with NCNN are 4x native. Using -s 2 with x4plus
# can corrupt the tile mapping even though the CLI accepts 2 (upstream #73).
# Always upscale at 4x and downsample with Lanczos afterwards.
if [[ -z "$gpu" ]] && command -v vulkaninfo >/dev/null 2>&1; then
  # Best effort: ncnn typically follows Vulkan device enumeration. Verify startup log.
  detected=$(vulkaninfo --summary 2>/dev/null | awk '
    /^[[:space:]]*GPU[0-9]+:/ { idx=$1; sub(/^GPU/, "", idx); sub(/:$/, "", idx) }
    /deviceName[[:space:]]*=/ && /RTX 3060/ { print idx; exit }
  ') || true
  if [[ -n "$detected" && "$detected" =~ ^[0-9]+$ ]]; then
    gpu=$detected
    echo "Detected RTX 3060 as Vulkan GPU $gpu (verify selected device in ncnn log)"
  fi
fi
if [[ -z "$gpu" ]]; then
  echo "WARNING: No RTX 3060 GPU ID selected; ncnn auto may use your GTX 1660 Ti." >&2
  echo "         Run --list-gpus and pass --gpu 0 or --gpu 1 explicitly." >&2
fi
echo "Model: $model; native 4x neural scaling, then Lanczos fit/pad to 1080p"
echo "FPS:   $fps (constant-frame-rate workflow)"
echo "Temp:  $tmp (PNG frames use substantial disk space)"
[[ -z "$gpu" ]] || echo "GPU:   Vulkan device $gpu"

# Original H3 clips have constant frame rate. This preserves each decoded frame.
echo '[1/3] Extracting frames...'
extract=(ffmpeg -hide_banner -loglevel error -stats -nostdin -i "$input")
[[ -z "$seconds" ]] || extract+=(-t "$seconds")
"${extract[@]}" -map 0:v:0 -fps_mode passthrough -start_number 1 "$tmp/input/%08d.png"
frame_count=$(find "$tmp/input" -maxdepth 1 -type f -name '*.png' | wc -l)
(( frame_count > 0 )) || die 'No video frames extracted'
echo "      Extracted $frame_count frames"

echo '[2/3] Upscaling with Vulkan GPU...'
realesrgan_args=(-i "$tmp/input" -o "$tmp/upscaled" -m "$models_dir" -n "$model" -s 4 -t "$tile" -j 1:2:2 -v)
[[ -z "$gpu" ]] || realesrgan_args+=(-g "$gpu")
"$real_bin" "${realesrgan_args[@]}"

upscaled_count=$(find "$tmp/upscaled" -maxdepth 1 -type f -name '*.png' | wc -l)
(( upscaled_count == frame_count )) || \
  die "Frame mismatch: extracted $frame_count; upscaled $upscaled_count. Frames kept with --keep-frames only."
[[ -f "$tmp/upscaled/00000001.png" ]] || die 'Expected first upscaled PNG missing'

# Assert correct 4x dimensions. This will not detect all visual artefacts;
# inspect your short preview before running full clips.
IFS=x read -r src_w src_h < <(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0:s=x "$tmp/input/00000001.png")
IFS=x read -r dst_w dst_h < <(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0:s=x "$tmp/upscaled/00000001.png")
(( dst_w == 4 * src_w && dst_h == 4 * src_h )) || \
  die "Wrong frame dimensions: input ${src_w}x${src_h}, enhanced ${dst_w}x${dst_h}; expected $((4*src_w))x$((4*src_h))"

echo '[3/3] Assembling 1080p MP4 and copying original audio...'
# We set video duration from the exact frame count to avoid including trailing audio.
video_length=$(awk -v f="$frame_count" -v r="$fps" 'BEGIN {split(r,a,"/"); rate=a[1]/(a[2] ? a[2] : 1); printf "%.6f",f/rate}')
ffmpeg -hide_banner -stats -nostdin -n \
  -framerate "$fps" -start_number 1 -i "$tmp/upscaled/%08d.png" \
  -i "$input" \
  -map 0:v:0 -map '1:a?' -map_metadata 1 \
  -t "$video_length" \
  -vf "$filter" \
  -c:v libx264 -preset "$preset" -crf "$crf" -pix_fmt yuv420p \
  -c:a copy -movflags +faststart "$output"

echo "DONE: $output"
