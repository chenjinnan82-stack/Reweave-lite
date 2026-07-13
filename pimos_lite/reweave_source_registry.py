"""Reweave Source Box Registry v0 — local metadata only (no scan, no project writes)."""

from __future__ import annotations

import hashlib
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
REGISTRY_FILENAME = "source_boxes.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def state_dir() -> Path:
    """Return Reweave app state directory (never inside a user source folder)."""
    env = os.environ.get("REWEAVE_STATE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library/Application Support/Reweave"
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "Reweave"
    return Path.home() / ".local/share/reweave"


def registry_path() -> Path:
    return state_dir() / REGISTRY_FILENAME


def load_json_state(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return dict(default)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _backup_corrupt_json(path)
        return dict(default)
    except OSError:
        return dict(default)
    return raw if isinstance(raw, dict) else dict(default)


def _backup_corrupt_json(path: Path) -> None:
    backup = path.with_name(f"{path.name}.corrupt.{_utc_now_iso().replace(':', '')}.bak")
    try:
        backup.write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    except OSError:
        pass


def load_registry() -> dict[str, Any]:
    raw = load_json_state(registry_path(), {"schema_version": SCHEMA_VERSION, "source_boxes": []})
    raw.setdefault("schema_version", SCHEMA_VERSION)
    raw.setdefault("source_boxes", [])
    return raw


def save_registry(data: dict[str, Any]) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_boxes": data.get("source_boxes", []),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _source_id_for_path(resolved: Path) -> str:
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:10]
    return f"source_{digest}"


def _normalize_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def list_source_boxes() -> list[dict[str, Any]]:
    boxes = load_registry().get("source_boxes", [])
    return list(boxes) if isinstance(boxes, list) else []


def get_source_box(source_id: str) -> dict[str, Any] | None:
    for box in list_source_boxes():
        if isinstance(box, dict) and box.get("id") == source_id:
            return dict(box)
    return None


def mark_source_scanned(source_id: str, summary_path: str, scanned_at: str) -> dict[str, Any] | None:
    data = load_registry()
    boxes: list[dict[str, Any]] = data.get("source_boxes", [])
    for box in boxes:
        if not isinstance(box, dict) or box.get("id") != source_id:
            continue
        box["scan_status"] = "scanned"
        box["last_scanned_at"] = scanned_at
        box["summary_path"] = summary_path
        box["updated_at"] = scanned_at
        if box.get("draft_status"):
            box["draft_status"] = "stale"
        if box.get("warehouse_status") == "promoted":
            box["warehouse_status"] = "stale"
        box.pop("last_error", None)
        save_registry(data)
        return dict(box)
    return None


def mark_source_scan_failed(source_id: str, error: str) -> dict[str, Any] | None:
    now = _utc_now_iso()
    data = load_registry()
    boxes: list[dict[str, Any]] = data.get("source_boxes", [])
    short = (error or "scan failed")[:200]
    for box in boxes:
        if not isinstance(box, dict) or box.get("id") != source_id:
            continue
        box["scan_status"] = "failed"
        box["last_error"] = short
        box["updated_at"] = now
        save_registry(data)
        return dict(box)
    return None


def mark_source_drafted(source_id: str, draft_path: str, drafted_at: str) -> dict[str, Any] | None:
    data = load_registry()
    boxes: list[dict[str, Any]] = data.get("source_boxes", [])
    for box in boxes:
        if not isinstance(box, dict) or box.get("id") != source_id:
            continue
        box["draft_status"] = "drafted"
        box["draft_path"] = draft_path
        box["last_drafted_at"] = drafted_at
        box["updated_at"] = drafted_at
        box.pop("last_error", None)
        save_registry(data)
        return dict(box)
    return None


def mark_source_draft_failed(source_id: str, error: str) -> dict[str, Any] | None:
    now = _utc_now_iso()
    data = load_registry()
    boxes: list[dict[str, Any]] = data.get("source_boxes", [])
    short = (error or "draft failed")[:200]
    for box in boxes:
        if not isinstance(box, dict) or box.get("id") != source_id:
            continue
        box["draft_status"] = "failed"
        box["last_error"] = short
        box["updated_at"] = now
        save_registry(data)
        return dict(box)
    return None


def mark_source_promoted(source_id: str, promoted_at: str, capsule_count: int) -> dict[str, Any] | None:
    data = load_registry()
    boxes: list[dict[str, Any]] = data.get("source_boxes", [])
    for box in boxes:
        if not isinstance(box, dict) or box.get("id") != source_id:
            continue
        box["warehouse_status"] = "promoted"
        box["last_promoted_at"] = promoted_at
        box["promoted_capsule_count"] = capsule_count
        box["updated_at"] = promoted_at
        save_registry(data)
        return dict(box)
    return None


def add_source_box(path: str | Path) -> dict[str, Any]:
    """Register a source folder by path metadata only. No scan, no reads inside folder."""
    resolved = _normalize_path(path)
    state = state_dir().resolve()
    try:
        state.relative_to(resolved)
    except ValueError:
        pass
    else:
        return {
            "id": _source_id_for_path(resolved),
            "label": resolved.name or str(resolved),
            "path": str(resolved),
            "status": "blocked",
            "scan_status": "not_scanned",
            "draft_status": "not_drafted",
            "last_error": "reweave_state_dir_inside_source_folder",
        }
    now = _utc_now_iso()
    data = load_registry()
    boxes: list[dict[str, Any]] = data.setdefault("source_boxes", [])

    for box in boxes:
        if not isinstance(box, dict):
            continue
        try:
            existing = _normalize_path(box.get("path", ""))
        except (OSError, RuntimeError, ValueError):
            continue
        if existing == resolved:
            box["status"] = "bound"
            box["updated_at"] = now
            box.setdefault("scan_status", "not_scanned")
            save_registry(data)
            return box

    source: dict[str, Any] = {
        "id": _source_id_for_path(resolved),
        "label": resolved.name or str(resolved),
        "path": str(resolved),
        "status": "bound",
        "scan_status": "not_scanned",
        "draft_status": "not_drafted",
        "created_at": now,
        "updated_at": now,
    }
    boxes.append(source)
    save_registry(data)
    return source


def remove_source_box(source_id: str) -> bool:
    data = load_registry()
    boxes: list[dict[str, Any]] = data.get("source_boxes", [])
    kept = [b for b in boxes if isinstance(b, dict) and b.get("id") != source_id]
    if len(kept) == len(boxes):
        return False
    data["source_boxes"] = kept
    save_registry(data)
    return True


def clear_registry() -> None:
    """Clear all source boxes (testing helper)."""
    save_registry({"schema_version": SCHEMA_VERSION, "source_boxes": []})
