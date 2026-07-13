#!/usr/bin/env bash
# Reweave static desktop shell — PySide6 window + local HTML (not a browser tab).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv-reweave"
REQ="$ROOT/pimos_lite/requirements-desktop.txt"
PYTHON="python3"

export LUNA_BASE_URL="${LUNA_BASE_URL:-http://127.0.0.1:8020}"
export REWEAVE_ENGINE="lumo_lite"
export REWEAVE_LUMO_LITE_STATE_PATH="${REWEAVE_RUNTIME_STATE_PATH:-${REWEAVE_LUMO_LITE_STATE_PATH:-}}"
unset REWEAVE_ENABLE_LEGACY_WORKBENCH

for candidate in \
  "$VENV/bin/python" \
  "$ROOT/.venv/bin/python"
do
  if [[ -x "$candidate" ]]; then
    if "$candidate" -c "from PySide6.QtWebEngineWidgets import QWebEngineView" 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [[ "$PYTHON" == "python3" ]] && ! python3 -c "from PySide6.QtWebEngineWidgets import QWebEngineView" 2>/dev/null; then
  cat >&2 <<EOF
PySide6 + QtWebEngine not found. Reweave will not install dependencies automatically.

Install once, then rerun this script:
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -r "$REQ"
EOF
  exit 2
fi

echo "Using: $PYTHON"
exec "$PYTHON" "$ROOT/pimos_lite/desktop_reweave_static.py" "$@"
