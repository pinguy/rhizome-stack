#!/bin/bash
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <input_audio_file>"
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

INPUT_FILE="$1"
TEMP_WAV="/tmp/temp_audio.wav"
FINAL_WAV="/tmp/output.wav"
TRANSCRIPT_OUT="$SCRIPT_DIR/transcript.txt"

cleanup() {
  rm -f "$TEMP_WAV" "$FINAL_WAV"
}
trap cleanup EXIT

# Step 0: Convert to WAV
echo "Step 0: Convert to WAV"
ffmpeg -y -i "$INPUT_FILE" -vn -acodec pcm_s16le -ar 16000 -ac 1 "$TEMP_WAV"

echo "Steps 1-3: Preserve broadband audio for Whisper"
cp "$TEMP_WAV" "$FINAL_WAV"

# Step 4: Run Transcription
echo "Step 4: Run Whisper transcription"
${HOME}/.local/share/rhizome-stack/venvs/voice/bin/python \
  "$SCRIPT_DIR/transcribe_faster_whisper.py" "$FINAL_WAV" "$TRANSCRIPT_OUT"

# Retention safety: keep at most the newest audio file in TTS_SST
if [ -x "$SCRIPT_DIR/enforce_audio_retention.sh" ]; then
  "$SCRIPT_DIR/enforce_audio_retention.sh" >/dev/null 2>&1 || true
fi
