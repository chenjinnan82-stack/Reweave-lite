"""Reweave preview package viewer / compare — read-only app state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pimos_lite.reweave_preview_pack import (
    load_latest_preview,
    load_preview_history,
    preview_acceptance,
    preview_packages_dir,
)
from pimos_lite.reweave_source_registry import state_dir

VIEWER_SAFETY = {
    "source_folder_read_at_view_time": False,
    "source_folder_written": False,
    "llm_called": False,
    "dispatch_called": False,
}


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _list_package_files(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir() if entry.is_file())


def _mode_from_provenance(provenance: dict[str, Any]) -> str:
    cag = provenance.get("content_aware_generate") if isinstance(provenance.get("content_aware_generate"), dict) else {}
    if cag.get("enabled"):
        return str(cag.get("mode") or "content_aware_preview")
    return "metadata_only"


def _normalize_capsules_used(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        if "capsule_id" not in entry and entry.get("id"):
            entry["capsule_id"] = entry["id"]
        out.append(entry)
    return out


def _snippets_used_summary(root: Path) -> dict[str, Any]:
    manifest = _read_json(root / "snippets_used.json")
    if not isinstance(manifest, dict):
        return {"enabled": False, "count": 0, "items": []}
    items: list[dict[str, Any]] = []
    for snip in manifest.get("snippets") if isinstance(manifest.get("snippets"), list) else []:
        if not isinstance(snip, dict):
            continue
        items.append(
            {
                "capsule_id": snip.get("capsule_id"),
                "relative_path": snip.get("relative_path"),
                "language_hint": snip.get("language_hint"),
                "excerpt_chars": snip.get("excerpt_chars"),
                "truncated": snip.get("truncated"),
                "redacted": snip.get("redacted"),
            }
        )
    return {"enabled": True, "count": len(items), "items": items}


def _provenance_summary(provenance: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if isinstance(provenance.get("content_aware_generate"), dict):
        summary["content_aware_generate"] = dict(provenance["content_aware_generate"])
    if isinstance(provenance.get("luna"), dict):
        summary["luna"] = dict(provenance["luna"])
    if isinstance(provenance.get("behavior_validation"), dict):
        summary["behavior_validation"] = dict(provenance["behavior_validation"])
    return summary


def resolve_package_root(package_id_or_path: str) -> tuple[Path | None, str]:
    """Resolve a preview package directory from id, relative path, or absolute path."""
    raw = (package_id_or_path or "").strip()
    if not raw:
        return None, ""

    state_root = state_dir()
    candidate = Path(raw)
    if candidate.is_dir():
        resolved = candidate.resolve()
        if _is_relative_to(resolved, state_root):
            return resolved, candidate.name
        return None, candidate.name

    under_state = state_root / raw
    if under_state.is_dir():
        resolved = under_state.resolve()
        if _is_relative_to(resolved, state_root):
            return resolved, under_state.name
        return None, under_state.name

    folder_name = raw.rstrip("/").split("/")[-1]
    by_name = preview_packages_dir() / folder_name
    if by_name.is_dir():
        resolved = by_name.resolve()
        if _is_relative_to(resolved, state_root):
            return resolved, folder_name
        return None, folder_name

    for entry in load_preview_history().get("packages") if isinstance(load_preview_history().get("packages"), list) else []:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "")
        entry_path = str(entry.get("path") or "")
        if raw not in {entry_id, entry_path, entry_path.rstrip("/")}:
            continue
        resolved = (state_root / entry_path).resolve()
        if resolved.is_dir() and _is_relative_to(resolved, state_root):
            return resolved, entry_id or resolved.name

    return None, folder_name or raw


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def build_viewer_payload(root: Path, package_id: str) -> dict[str, Any]:
    """Build read-only viewer payload for a preview package directory."""
    warnings: list[str] = []
    if not root.is_dir():
        return {"ok": False, "error": "package_not_found"}

    files = _list_package_files(root)
    provenance_raw = _read_json(root / "provenance.json")
    provenance = provenance_raw if isinstance(provenance_raw, dict) else {}
    if not provenance:
        warnings.append("provenance_missing")

    capsules_used = _normalize_capsules_used(_read_json(root / "capsules_used.json"))
    snippets_used = _snippets_used_summary(root)
    task_pack_raw = _read_json(root / "task_pack.json")
    task_pack = task_pack_raw if isinstance(task_pack_raw, dict) else {}

    from pimos_lite.reweave_preview_export import load_exports_for_package

    return {
        "ok": True,
        "package": {
            "id": package_id,
            "path": str(root.resolve()),
            "created_at": provenance.get("generated_at"),
            "mode": _mode_from_provenance(provenance),
            "files": files,
        },
        "capsulesUsed": capsules_used,
        "snippetsUsed": snippets_used,
        "previewAcceptance": preview_acceptance(task_pack),
        "provenance": _provenance_summary(provenance),
        "exports": load_exports_for_package(package_id),
        "safety": dict(VIEWER_SAFETY),
        "warnings": warnings,
    }


def get_latest_preview_package() -> dict[str, Any]:
    history = load_preview_history()
    packages = history.get("packages") if isinstance(history.get("packages"), list) else []
    for entry in packages:
        if not isinstance(entry, dict):
            continue
        target = str(entry.get("path") or entry.get("id") or "")
        root, package_id = resolve_package_root(target)
        if root:
            return build_viewer_payload(root, package_id)

    latest = load_latest_preview()
    if latest and latest.get("previewPath"):
        root, package_id = resolve_package_root(str(latest["previewPath"]))
        if root:
            return build_viewer_payload(root, package_id)

    pkg_dir = preview_packages_dir()
    state_root = state_dir().resolve()
    if pkg_dir.is_dir() and _is_relative_to(pkg_dir.resolve(), state_root):
        dirs = sorted(
            (item.resolve() for item in pkg_dir.iterdir() if item.is_dir() and _is_relative_to(item.resolve(), state_root)),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if dirs:
            return build_viewer_payload(dirs[0], dirs[0].name)

    return {"ok": False, "error": "no_preview_package"}


def get_preview_package(package_id_or_path: str) -> dict[str, Any]:
    root, package_id = resolve_package_root(package_id_or_path)
    if not root:
        return {"ok": False, "error": "package_not_found", "package_id": package_id_or_path}
    return build_viewer_payload(root, package_id)


def compare_preview_packages(left_id: str = "", right_id: str = "") -> dict[str, Any]:
    """Metadata-only compare — no code diff."""
    left_key = (left_id or "").strip()
    right_key = (right_id or "").strip()

    if not left_key and not right_key:
        history = load_preview_history().get("packages") if isinstance(load_preview_history().get("packages"), list) else []
        if len(history) < 2:
            return {"ok": False, "error": "no_previous_package"}
        right_key = str(history[0].get("id") or history[0].get("path") or "")
        left_key = str(history[1].get("id") or history[1].get("path") or "")

    left = get_preview_package(left_key) if left_key else get_latest_preview_package()
    right = get_preview_package(right_key) if right_key else get_latest_preview_package()
    if not left.get("ok"):
        return left
    if not right.get("ok"):
        return right

    left_files = set(left["package"]["files"])
    right_files = set(right["package"]["files"])
    left_cag = (left.get("provenance") or {}).get("content_aware_generate") or {}
    right_cag = (right.get("provenance") or {}).get("content_aware_generate") or {}
    left_luna = (left.get("provenance") or {}).get("luna") or {}
    right_luna = (right.get("provenance") or {}).get("luna") or {}

    return {
        "ok": True,
        "left": {"id": left["package"]["id"], "mode": left["package"]["mode"]},
        "right": {"id": right["package"]["id"], "mode": right["package"]["mode"]},
        "diff": {
            "files_added": sorted(right_files - left_files),
            "files_removed": sorted(left_files - right_files),
            "capsules_used_delta": len(right.get("capsulesUsed") or []) - len(left.get("capsulesUsed") or []),
            "snippets_used_delta": (right.get("snippetsUsed") or {}).get("count", 0)
            - (left.get("snippetsUsed") or {}).get("count", 0),
            "content_aware_changed": bool(left_cag.get("enabled")) != bool(right_cag.get("enabled")),
            "luna_pack_changed": bool(left_luna.get("pack_id")) != bool(right_luna.get("pack_id")),
        },
        "safety": {
            "code_diff": False,
            "metadata_compare_only": True,
        },
    }
