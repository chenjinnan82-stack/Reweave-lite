"""Reweave preview package archive / export — app state only, no source writes."""

from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pimos_lite.reweave_preview_viewer import resolve_package_root
from pimos_lite.reweave_source_registry import list_source_boxes, state_dir

README_FILENAME = "README_REWEAVE_PREVIEW.txt"
EXPORT_LOG_DIR = "export_logs"
EXPORT_LOG_FILENAME = "preview_export_log.jsonl"

README_CONTENT = """Reweave local preview package
=============================

This is a Reweave local preview package.
It is not a deployed project.
It was generated from Reweave app state.
Source folder was not modified.
See provenance.json, capsules_used.json, snippets_used.json for trace.

这是 Reweave 生成的本地预览包，不是正式部署项目；源项目未被修改。
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def export_log_path() -> Path:
    return state_dir() / EXPORT_LOG_DIR / EXPORT_LOG_FILENAME


def _safe_basename(name: str) -> str:
    base = Path(name).name
    if not base or base in {".", ".."}:
        raise ValueError("invalid_filename")
    if ".." in base or "/" in name or "\\" in name:
        raise ValueError("path_traversal_blocked")
    return base


def _is_under_path(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def is_export_to_source_folder_blocked(export_dir: Path) -> bool:
    """Block exports into registered source folders, or directories that contain them."""
    export_resolved = export_dir.expanduser().resolve()
    for box in list_source_boxes():
        if not isinstance(box, dict):
            continue
        raw_path = box.get("path")
        if not raw_path:
            continue
        try:
            source_path = Path(str(raw_path)).expanduser().resolve()
        except OSError:
            continue
        if export_resolved == source_path or _is_under_path(export_resolved, source_path) or _is_under_path(source_path, export_resolved):
            return True
    return False


def _list_exportable_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    files: list[Path] = []
    for entry in sorted(root.iterdir()):
        if entry.is_file() and not entry.is_symlink():
            files.append(entry)
    return files


def _unique_export_target(base_dir: Path, stem: str, suffix: str = "") -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = base_dir / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    numbered = base_dir / f"{stem}_{stamp}{suffix}"
    if not numbered.exists():
        return numbered
    index = 1
    while True:
        alt = base_dir / f"{stem}_{stamp}_{index}{suffix}"
        if not alt.exists():
            return alt
        index += 1


def append_export_log(record: dict[str, Any]) -> None:
    path = export_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_exports_for_package(package_id: str) -> list[dict[str, Any]]:
    """Return prior export log entries for a package id (newest first)."""
    path = export_log_path()
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if str(record.get("package_id") or "") == package_id:
            entries.append(
                {
                    "mode": record.get("mode"),
                    "export_path": record.get("export_path"),
                    "created_at": record.get("created_at"),
                }
            )
    return entries


def _write_export_log(package_id: str, mode: str, export_path: Path) -> None:
    append_export_log(
        {
            "event": "preview_package_exported",
            "package_id": package_id,
            "mode": mode,
            "export_path": str(export_path.resolve()),
            "created_at": _utc_now_iso(),
            "safety": {
                "source_folder_read": False,
                "source_folder_written": False,
                "preview_package_modified": False,
                "dispatch_called": False,
                "luna_apply_called": False,
            },
        }
    )


def _export_name_stem(package_id: str) -> str:
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in package_id).strip("-")
    if not safe_id:
        safe_id = "preview"
    return f"reweave_preview_{safe_id}"


def _export_zip(root: Path, package_id: str, export_dir: Path) -> Path:
    stem = _export_name_stem(package_id)
    zip_path = _unique_export_target(export_dir, stem, ".zip")
    files = _list_exportable_files(root)
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            arcname = _safe_basename(file_path.name)
            archive.write(file_path, arcname=arcname)
        archive.writestr(_safe_basename(README_FILENAME), README_CONTENT)
    return zip_path


def _export_copy(root: Path, package_id: str, export_dir: Path) -> Path:
    stem = _export_name_stem(package_id)
    dest = _unique_export_target(export_dir, stem, "")
    dest.mkdir(parents=True, exist_ok=False)
    for file_path in _list_exportable_files(root):
        shutil.copy2(file_path, dest / _safe_basename(file_path.name))
    (dest / README_FILENAME).write_text(README_CONTENT, encoding="utf-8")
    return dest


def export_preview_package(
    package_id_or_path: str,
    export_dir: str | Path,
    *,
    mode: str = "zip",
) -> dict[str, Any]:
    """Export a preview package to zip or copy folder. Does not modify the source package."""
    root, package_id = resolve_package_root(package_id_or_path)
    if not root:
        return {"ok": False, "error": "package_not_found", "package_id": package_id_or_path}

    export_mode = (mode or "zip").strip().lower()
    if export_mode not in {"zip", "copy"}:
        return {"ok": False, "error": "invalid_export_mode", "mode": mode}

    try:
        target_dir = Path(export_dir).expanduser().resolve()
    except OSError:
        return {"ok": False, "error": "invalid_export_dir"}

    if is_export_to_source_folder_blocked(target_dir):
        return {"ok": False, "error": "export_to_source_folder_blocked"}

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {"ok": False, "error": "export_dir_not_writable"}

    before_snapshot = {
        file_path.name: file_path.read_bytes()
        for file_path in _list_exportable_files(root)
    }

    try:
        if export_mode == "zip":
            export_path = _export_zip(root, package_id, target_dir)
        else:
            export_path = _export_copy(root, package_id, target_dir)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return {"ok": False, "error": str(exc)[:200]}

    after_snapshot = {
        file_path.name: file_path.read_bytes()
        for file_path in _list_exportable_files(root)
    }
    if before_snapshot != after_snapshot:
        return {"ok": False, "error": "preview_package_modified_unexpectedly"}

    _write_export_log(package_id, export_mode, export_path)
    return {
        "ok": True,
        "package_id": package_id,
        "mode": export_mode,
        "export_path": str(export_path.resolve()),
    }
