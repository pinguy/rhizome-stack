#!/usr/bin/env bash
set -euo pipefail

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive_root="${XDG_STATE_HOME:-$HOME/.local/state}/rhizome-stack/removed-$stamp"
stack_root="$HOME/.local/share/rhizome-stack"
config_root="${XDG_CONFIG_HOME:-$HOME/.config}/rhizome-stack"
unit_root="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
units=(
  openclaw-gateway.service openclaw-openwebui-adapter.service openclaw-ollama-model-sync.service
  openclaw-ollama-model-sync.timer open-webui.service openwebui-audio-bridge.service
  chatterbox-nano.service openwebui-memory-sync.service openwebui-memory-sync.timer
  openwebui-code-jupyter.service
)

mkdir -p "$archive_root/units"
systemctl --user disable --now "${units[@]}" 2>/dev/null || true
for unit in "${units[@]}"; do
  path="$unit_root/$unit"
  [[ -f "$path" ]] || continue
  if ! rg -q 'Rhizome Stack|OpenClaw model adapter|Synchronise tool-capable|local TTS and STT bridge|Chatterbox-Nano|local workspace and Open WebUI memory|code interpreter Jupyter sandbox' "$path"; then
    printf 'Refusing unknown unit: %s\n' "$path" >&2
    exit 2
  fi
  mv "$path" "$archive_root/units/"
  backup="$path.before-rhizome-stack"
  if [[ -f "$backup" ]]; then
    mv "$backup" "$path"
    printf 'Restored pre-existing unit: %s\n' "$path"
  fi
done
[[ ! -d "$stack_root" ]] || mv "$stack_root" "$archive_root/stack"
[[ ! -d "$config_root" ]] || mv "$config_root" "$archive_root/config"
systemctl --user daemon-reload
printf 'Removed files were moved, not deleted: %s\n' "$archive_root"
printf 'OpenClaw user state and populated Open WebUI data were not separately deleted.\n'
