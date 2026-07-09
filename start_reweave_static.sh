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

if [[ "$PYTHON" == "python3" ]]; then
  echo "PySide6 + QtWebEngine not found. Setting up $VENV ..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip
  # Large wheels (~440MB). Use mirror if default PyPI is slow or resets:
  PIP_INDEX="${PIP_INDEX_URL:-https://pypi.org/simple}"
  echo "Installing from: $PIP_INDEX (set PIP_INDEX_URL for a mirror if download fails)"
  "$VENV/bin/pip" install --retries 10 --timeout 300 -i "$PIP_INDEX" -r "$REQ"
  PYTHON="$VENV/bin/python"
fi

echo "Using: $PYTHON"
exec "$PYTHON" "$ROOT/pimos_lite/desktop_reweave_static.py" "$@"
