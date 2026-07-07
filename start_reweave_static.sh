#!/usr/bin/env bash
# Reweave static desktop shell — PySide6 window + local HTML (not a browser tab).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv-reweave"
REQ="$ROOT/pimos_lite/requirements-desktop.txt"
PYTHON="python3"

export LUNA_BASE_URL="${LUNA_BASE_URL:-http://127.0.0.1:8020}"
export PIMOS_ADMIN_API_KEY_FILE="${PIMOS_ADMIN_API_KEY_FILE:-$ROOT/workspace_sixcats_argus_integration/agent_system/runtime/admin_api_key}"
export REWEAVE_ENGINE="lumo_lite"
unset REWEAVE_ENABLE_LEGACY_WORKBENCH

DEFAULT_LUMO_LITE_PRODUCT_STATE="$ROOT/workspace_sixcats_argus_integration/agent_system/pym_luna_lite_migration_stage4_main_rehearsal/artifacts/capsule_capability_dataset/p120-product-acceptance-read-only-status-current-overlay-smoke/frontend_runtime_state.json"
DEFAULT_LUMO_LITE_RC4_STATE="$ROOT/workspace_sixcats_argus_integration/agent_system/pym_luna_lite_migration_stage4_main_rehearsal/.runtime/rc4_desktop_state/frontend_runtime_state.json"
if [[ -z "${REWEAVE_LUMO_LITE_STATE_PATH:-}" && -f "$DEFAULT_LUMO_LITE_PRODUCT_STATE" ]]; then
  export REWEAVE_LUMO_LITE_STATE_PATH="$DEFAULT_LUMO_LITE_PRODUCT_STATE"
elif [[ -z "${REWEAVE_LUMO_LITE_STATE_PATH:-}" && -f "$DEFAULT_LUMO_LITE_RC4_STATE" ]]; then
  export REWEAVE_LUMO_LITE_STATE_PATH="$DEFAULT_LUMO_LITE_RC4_STATE"
fi

for candidate in \
  "$VENV/bin/python" \
  "$ROOT/Luna/.venv/bin/python" \
  "$ROOT/Doraemon/doraemon_service/.venv/bin/python" \
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
