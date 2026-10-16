#!/usr/bin/env bash
set -euo pipefail
umask 077

service="${OPENWEBUI_CODE_JUPYTER_SERVICE:-openwebui-code-jupyter.service}"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/rhizome-stack/openwebui-code-jupyter"
state_file="$state_dir/ollama-empty-since"
min_idle_seconds="${OPENWEBUI_CODE_JUPYTER_STOP_AFTER_EMPTY_SECONDS:-60}"
jupyter_url="${CODE_INTERPRETER_JUPYTER_URL:-http://127.0.0.1:8889}"
jupyter_token="${CODE_INTERPRETER_JUPYTER_AUTH_TOKEN:-${JUPYTER_TOKEN:-}}"

mkdir -p "$state_dir"

ollama_has_runner() {
  command -v ollama >/dev/null 2>&1 \
    && ollama ps 2>/dev/null | awk 'NR > 1 { found = 1 } END { exit found ? 0 : 1 }'
}

if ! systemctl --user is-active --quiet "$service"; then
  rm -f "$state_file"
  # A loaded local chat model is a useful wake signal. Hosted-provider code
  # calls are covered by Open WebUI's direct wake/retry patch instead.
  if ollama_has_runner; then
    systemctl --user start "$service"
  fi
  exit 0
fi

if ollama_has_runner; then
  rm -f "$state_file"
  exit 0
fi

# Unknown kernel state is not idle. A missing token or failed request keeps the
# sandbox alive rather than risking interruption of user code.
if [[ -z "$jupyter_token" ]]; then
  rm -f "$state_file"
  exit 0
fi
kernels_json="$(curl -fsS -H "Authorization: token $jupyter_token" "$jupyter_url/api/kernels" 2>/dev/null || printf 'unknown')"
if [[ "$kernels_json" != "[]" ]]; then
  rm -f "$state_file"
  exit 0
fi

now="$(date +%s)"
if [[ ! -s "$state_file" ]]; then
  printf '%s\n' "$now" > "$state_file"
  exit 0
fi
empty_since="$(<"$state_file")"
case "$empty_since" in
  ''|*[!0-9]*) empty_since="$now" ;;
esac
if (( now - empty_since >= min_idle_seconds )); then
  systemctl --user stop "$service"
  rm -f "$state_file"
fi
