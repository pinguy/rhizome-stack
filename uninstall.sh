#!/usr/bin/env bash
set -euo pipefail

dry_run=false
case "${1:-}" in
  "") ;;
  --dry-run) dry_run=true ;;
  *) printf 'usage: %s [--dry-run]\n' "$0" >&2; exit 64 ;;
esac

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive_root="${XDG_STATE_HOME:-$HOME/.local/state}/rhizome-stack/removed-$stamp"
config_root="${XDG_CONFIG_HOME:-$HOME/.config}/rhizome-stack"
unit_root="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

stack_root="${RHIZOME_STACK_ROOT:-}"
if [[ -z "$stack_root" && -f "$config_root/stack.env" ]]; then
  stack_root="$(python3 - "$config_root/stack.env" <<'PY'
import os
import shlex
import sys
from pathlib import Path

for raw in Path(sys.argv[1]).read_text().splitlines():
    key, separator, value = raw.partition('=')
    if separator and key.strip() == 'RHIZOME_STACK_ROOT':
        parsed = shlex.split(value, posix=True)
        if len(parsed) != 1:
            raise SystemExit('invalid RHIZOME_STACK_ROOT in stack.env')
        print(os.path.abspath(os.path.expanduser(parsed[0])))
        break
PY
)"
fi
stack_root="${stack_root:-$HOME/.local/share/rhizome-stack}"
stack_root="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$stack_root")"

if [[ "$stack_root" == / || "$stack_root" == "$HOME" || "$stack_root" == "$config_root" || "$stack_root" == "$unit_root" ]]; then
  printf 'Refusing unsafe stack root: %s\n' "$stack_root" >&2
  exit 2
fi

manifest="$stack_root/manifests/systemd-units.json"
units=()
if [[ -f "$manifest" ]]; then
  unit_output="$(python3 - "$manifest" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
units = payload.get('units')
if payload.get('schema') != 1 or not isinstance(units, list):
    raise SystemExit('invalid installed systemd unit manifest')
for unit in units:
    if not isinstance(unit, str) or '/' in unit or not unit.endswith(('.service', '.timer')):
        raise SystemExit('unsafe installed systemd unit manifest')
    print(unit)
PY
)"
  [[ -z "$unit_output" ]] || mapfile -t units <<<"$unit_output"
else
  units=(
    chatterbox-nano.service chatterbox-voice-app.service minimax-music-api.service
    open-webui.service openclaw-gateway.service openclaw-ollama-model-sync.service
    openclaw-ollama-model-sync.timer openclaw-openwebui-adapter.service
    openwebui-audio-bridge.service openwebui-code-jupyter-idle-guard.service
    openwebui-code-jupyter-idle-guard.timer openwebui-code-jupyter.service
    openwebui-memory-sync.service openwebui-memory-sync.timer qwen-image-desk.service
    rhizome-gliner-resident.service rhizome-workforce-retrieval.service wan-video-desk.service
  )
fi

# Establish the target before stopping or moving anything. A repeated run is
# allowed after the stack has already been archived.
if [[ -d "$stack_root" && (! -f "$stack_root/VERSION" || ! -f "$stack_root/manifests/components.json") ]]; then
  printf 'Refusing unrecognised stack root: %s\n' "$stack_root" >&2
  exit 2
fi

owned_units=()
unknown_units=()
for unit in "${units[@]}"; do
  installed="$unit_root/$unit"
  [[ -f "$installed" ]] || continue
  template="$stack_root/systemd/$unit"
  if [[ ! -f "$template" ]]; then
    # An already-removed stack cannot establish ownership. Preserve the unit.
    [[ ! -d "$stack_root" ]] && continue
    unknown_units+=("$installed")
    continue
  fi
  if python3 - "$template" "$installed" "$stack_root" "$HOME" "$config_root" <<'PY'
import sys
from pathlib import Path

template, installed, stack_root, home, config_root = map(Path, sys.argv[1:])
rendered = template.read_text().replace('@@STACK_ROOT@@', str(stack_root)).replace('@@HOME@@', str(home))
rendered = rendered.replace(str(home / '.config/rhizome-stack/stack.env'), str(config_root / 'stack.env'))
raise SystemExit(0 if installed.read_text() == rendered else 1)
PY
  then
    owned_units+=("$unit")
  else
    unknown_units+=("$installed")
  fi
done

if ((${#unknown_units[@]})); then
  printf 'Refusing modified or unknown units:\n' >&2
  printf '  %s\n' "${unknown_units[@]}" >&2
  exit 2
fi

if $dry_run; then
  printf 'DRY RUN stack root: %s\n' "$stack_root"
  printf 'DRY RUN config root: %s\n' "$config_root"
  printf 'DRY RUN archive root: %s\n' "$archive_root"
  printf 'DRY RUN owned units (%d):\n' "${#owned_units[@]}"
  printf '  %s\n' "${owned_units[@]}"
  exit 0
fi

# A repeat uninstall must be a true no-op: keep the original recovery archive,
# and don't restart systemd when there is no longer anything to remove.
if [[ ! -d "$stack_root" && ! -d "$config_root" ]] && ((${#owned_units[@]} == 0)); then
  printf 'Rhizome Stack is already uninstalled; nothing to archive.\n'
  exit 0
fi

mkdir -p "$archive_root/units"
if ((${#owned_units[@]})); then
  systemctl --user disable --now "${owned_units[@]}" 2>/dev/null || true
fi
for unit in "${owned_units[@]}"; do
  path="$unit_root/$unit"
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
