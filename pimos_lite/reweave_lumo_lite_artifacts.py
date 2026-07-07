"""Read-only Lumo Lite local artifact viewer helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pimos_lite.reweave_lumo_lite_state import (
    capsule_warehouse_block,
    load_lumo_lite_runtime_state,
    lumo_lite_state_path,
)

MAX_TEXT_PREVIEW_CHARS = 12000
MAX_DIR_ENTRIES = 40


def collect_lumo_lite_artifacts(runtime_state_path: str | Path | None = None) -> dict[str, Any]:
    """Collect local artifacts referenced by Lumo Lite runtime state."""

    loaded = load_lumo_lite_runtime_state(runtime_state_path)
    if not loaded.get("ok"):
        return {
            "ok": False,
            "engine": "lumo_lite",
            "mode": "read_only_artifacts",
            "error": loaded.get("error") or "runtime_state_unavailable",
            "artifacts": [],
            "safety": _viewer_safety(),
        }

    state = loaded.get("state") if isinstance(loaded.get("state"), dict) else {}
    state_path = Path(str(loaded.get("path") or ""))
    rows: list[dict[str, Any]] = []

    paths = state.get("paths") if isinstance(state.get("paths"), dict) else {}
    preview_root = _path_or_none(paths.get("preview_root"))
    output_dir = _path_or_none(paths.get("output_dir"))
    allowed_roots = _artifact_roots(state_path=state_path, preview_root=preview_root)
    _append_artifact(rows, kind="runtime_state", label="frontend_runtime_state.json", path=state_path, allowed_roots=allowed_roots)
    _append_artifact(rows, kind="preview_root", label="Preview folder", path=preview_root, allowed_roots=allowed_roots)
    _append_artifact(rows, kind="output_dir", label="Output state folder", path=output_dir, allowed_roots=allowed_roots)

    warehouse = capsule_warehouse_block(state)
    _append_artifact(rows, kind="trace", label="Lumo trace", path=_path_or_none(warehouse.get("trace_path")), allowed_roots=allowed_roots)
    for index, path in enumerate(_path_values(warehouse.get("evidence_package_paths")), start=1):
        _append_artifact(rows, kind="evidence", label=f"Evidence package {index}", path=_path_or_none(path), allowed_roots=allowed_roots)

    pym_window = state.get("pym_window") if isinstance(state.get("pym_window"), dict) else {}
    for artifact in _dict_list(pym_window.get("preview_artifacts")):
        raw_path = str(artifact.get("path") or "").strip()
        if not raw_path:
            continue
        path = _preview_artifact_path(raw_path, preview_root)
        if path is None:
            continue
        _append_artifact(
            rows,
            kind="preview_artifact",
            label=str(artifact.get("path") or path.name),
            path=path,
            source={"preview_only": bool(artifact.get("preview_only", True))},
            allowed_roots=allowed_roots,
        )

    deduped = _dedupe(rows)
    return {
        "ok": True,
        "engine": "lumo_lite",
        "mode": "read_only_artifacts",
        "runtime_state_path": str(state_path),
        "artifacts": deduped,
        "count": len(deduped),
        "safety": _viewer_safety(),
    }


def get_lumo_lite_artifact(
    artifact_id_or_path: str,
    runtime_state_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return bounded read-only details for one known Lumo Lite artifact."""

    wanted = str(artifact_id_or_path or "").strip()
    if not wanted:
        return {"ok": False, "error": "missing_artifact_id", "safety": _viewer_safety()}

    listing = collect_lumo_lite_artifacts(runtime_state_path)
    if not listing.get("ok"):
        return listing
    artifact = _find_artifact(listing.get("artifacts"), wanted)
    if artifact is None:
        return {"ok": False, "error": "artifact_not_found", "safety": _viewer_safety()}

    path = Path(str(artifact.get("path") or ""))
    detail = dict(artifact)
    detail["directory_entries"] = []
    detail["text_preview"] = ""
    detail["json_preview"] = None
    detail["truncated"] = False
    if path.is_dir():
        detail["directory_entries"] = _directory_entries(path)
    elif path.is_file():
        _attach_file_preview(detail, path)
    return {
        "ok": True,
        "engine": "lumo_lite",
        "mode": "read_only_artifact",
        "artifact": detail,
        "safety": _viewer_safety(),
    }


def get_lumo_lite_artifact_path(
    artifact_id_or_path: str,
    runtime_state_path: str | Path | None = None,
) -> Path | None:
    listing = collect_lumo_lite_artifacts(runtime_state_path)
    if not listing.get("ok"):
        return None
    artifact = _find_artifact(listing.get("artifacts"), artifact_id_or_path)
    if not artifact:
        return None
    path = Path(str(artifact.get("path") or ""))
    return path if path.exists() else None


def default_lumo_lite_runtime_state_path() -> Path | None:
    return lumo_lite_state_path()


def _append_artifact(
    rows: list[dict[str, Any]],
    *,
    kind: str,
    label: str,
    path: Path | None,
    source: dict[str, Any] | None = None,
    allowed_roots: list[Path] | None = None,
) -> None:
    if path is None:
        return
    path = path.expanduser().resolve(strict=False)
    if not _is_under_allowed_roots(path, allowed_roots or []):
        return
    exists = path.exists()
    is_dir = path.is_dir()
    is_file = path.is_file()
    rows.append(
        {
            "id": _artifact_id(kind, path),
            "kind": kind,
            "label": label,
            "path": str(path),
            "basename": path.name,
            "exists": exists,
            "is_dir": is_dir,
            "is_file": is_file,
            "size_bytes": _size(path) if is_file else 0,
            "readable": bool(exists and (is_dir or is_file)),
            "summary": _summary(kind, path, exists=exists, is_dir=is_dir, is_file=is_file),
            "source": dict(source or {}),
            "safety": _viewer_safety(),
        }
    )


def _artifact_id(kind: str, path: Path) -> str:
    digest = hashlib.sha256(f"{kind}:{path}".encode("utf-8")).hexdigest()[:12]
    return f"lumo_art_{digest}"


def _summary(kind: str, path: Path, *, exists: bool, is_dir: bool, is_file: bool) -> str:
    if not exists:
        return "missing"
    if is_dir:
        return f"{kind} directory"
    if is_file:
        return f"{kind} file"
    return kind


def _size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("kind") or ""), str(row.get("path") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _find_artifact(rows: Any, wanted: str) -> dict[str, Any] | None:
    wanted = str(wanted or "").strip()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if wanted in {str(row.get("id") or ""), str(row.get("path") or "")}:
            return dict(row)
    return None


def _attach_file_preview(detail: dict[str, Any], path: Path) -> None:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        detail["readable"] = False
        return
    detail["truncated"] = len(raw) > MAX_TEXT_PREVIEW_CHARS
    text = raw[:MAX_TEXT_PREVIEW_CHARS]
    detail["text_preview"] = text
    if path.suffix.lower() == ".json":
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        detail["json_preview"] = parsed if isinstance(parsed, dict | list) else None


def _directory_entries(path: Path) -> list[dict[str, Any]]:
    try:
        entries = sorted(path.iterdir(), key=lambda item: item.name)[:MAX_DIR_ENTRIES]
    except OSError:
        return []
    return [
        {
            "name": entry.name,
            "kind": "dir" if entry.is_dir() else "file" if entry.is_file() else "other",
            "size_bytes": _size(entry) if entry.is_file() else 0,
        }
        for entry in entries
    ]


def _path_or_none(value: Any) -> Path | None:
    raw = str(value or "").strip()
    return Path(raw) if raw else None


def _artifact_roots(*, state_path: Path, preview_root: Path | None) -> list[Path]:
    roots = [state_path]
    if state_path.parent.name in {".runtime", "runtime", "artifacts"}:
        roots.append(state_path.parent)
    for parent in [state_path, *state_path.parents]:
        if parent.name == "pym_luna_lite_migration_stage4_main_rehearsal":
            roots.extend([parent / "artifacts", parent / ".runtime", parent / "runtime"])
            break
    trusted = _dedupe_roots(roots)
    if preview_root is not None:
        resolved_preview = preview_root.expanduser().resolve(strict=False)
        if _is_under_allowed_roots(resolved_preview, trusted):
            roots.append(resolved_preview)
    return _dedupe_roots(roots)


def _dedupe_roots(roots: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        resolved = root.expanduser().resolve(strict=False)
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        out.append(resolved)
    return out


def _is_under_allowed_roots(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _preview_artifact_path(raw_path: str, preview_root: Path | None) -> Path | None:
    if preview_root is None:
        return None
    root = preview_root.expanduser().resolve()
    raw = str(raw_path or "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def _path_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [str(item).strip() for item in value.values() if str(item).strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _viewer_safety() -> dict[str, bool]:
    return {
        "root_allowlist_enforced": True,
        "source_folder_written": False,
        "dispatch_called": False,
        "network_called": False,
        "model_called": False,
        "watcher_started": False,
        "promotion_called": False,
    }
