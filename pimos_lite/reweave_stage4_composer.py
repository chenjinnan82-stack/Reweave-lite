"""Thin bridge to the single built-in Stage4 composer owned by Reweave-lite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pimos_lite.capsule_module import extract_behavior_module_capsules, load_module_capsules
from pimos_lite.composer.module_native import COMPOSER_VERSION, build_module_capability_graph, compose_module_native_preview


COMPOSER_OWNER = "stage4_module_native"
COMPOSER_SOURCE_OWNERSHIP = "reweave_lite_canonical"


def extract_with_stage4(
    *,
    source_root: Path,
    role: str,
    source_id: str,
    source_capsule_id: str = "",
) -> dict[str, Any]:
    results = extract_many_with_stage4(
        source_root=source_root,
        role=role,
        source_id=source_id,
        source_capsule_id=source_capsule_id,
    )
    if len(results) != 1:
        return {"status": "rejected", "reason": f"{role}_source_has_multiple_behavior_modules", "source_project_write": False}
    return results[0]


def extract_many_with_stage4(
    *,
    source_root: Path,
    role: str,
    source_id: str,
    source_capsule_id: str = "",
) -> list[dict[str, Any]]:
    try:
        results = extract_behavior_module_capsules(
            source_root,
            role=role,
            source_id=source_id,
            source_capsule_id=source_capsule_id,
        )
    except ValueError as exc:
        return [{"status": "rejected", "reason": str(exc), "source_project_write": False}]
    for result in results:
        permissions = result.get("permissions") if isinstance(result.get("permissions"), dict) else {}
        if result.get("module_capsule_version") != "module_capsule.v1" or permissions.get("workspace_write") is not False:
            raise RuntimeError("unexpected_stage4_behavior_module")
        result["composer_owner"] = COMPOSER_OWNER
        result["composer_source_ownership"] = COMPOSER_SOURCE_OWNERSHIP
    return results


def compose_with_stage4(
    *,
    goal: str,
    capsule_path: Path,
    capability_tags: list[str] | None = None,
    module_ids: list[str] | None = None,
    max_modules: int = 1,
    preview_root: Path | None = None,
    auto_behavior: bool = False,
    selected_plan_id: str = "",
) -> dict[str, Any]:
    capsules = capsule_path.expanduser().resolve()
    if not capsules.exists():
        raise FileNotFoundError("stage4_module_capsules_not_found")
    result = compose_module_native_preview(
        capsule_path=capsules,
        goal=goal,
        capability_tags=capability_tags,
        module_ids=module_ids,
        max_modules=max(1, int(max_modules)),
        write_preview_root=preview_root.expanduser().resolve() if preview_root is not None else None,
        auto_behavior=auto_behavior,
        selected_plan_id=selected_plan_id,
    )
    if result.get("composition_mode") != "module_native" or result.get("composer_version") != COMPOSER_VERSION:
        raise RuntimeError("unexpected_composer_owner")
    effects = result.get("effects") if isinstance(result.get("effects"), dict) else {}
    if effects.get("source_project_write") is not False:
        raise RuntimeError("stage4_composer_source_write_not_closed")
    result["composer_owner"] = COMPOSER_OWNER
    result["composer_source_ownership"] = COMPOSER_SOURCE_OWNERSHIP
    return result


def plan_with_stage4(
    *,
    goal: str,
    capsule_path: Path,
    max_modules: int = 5,
) -> dict[str, Any]:
    capsules = capsule_path.expanduser().resolve()
    if not capsules.exists():
        raise FileNotFoundError("stage4_module_capsules_not_found")
    graph = build_module_capability_graph(load_module_capsules(capsules), goal=goal, max_modules=max_modules)
    return {
        **graph,
        "composer_owner": COMPOSER_OWNER,
        "composer_source_ownership": COMPOSER_SOURCE_OWNERSHIP,
        "source_project_write": False,
    }


def list_stage4_module_capsules(*, capsule_path: Path) -> list[dict[str, Any]]:
    capsules = capsule_path.expanduser().resolve()
    paths = sorted(capsules.glob("*.json")) if capsules.is_dir() else [capsules]
    result: list[dict[str, Any]] = []
    for path in paths:
        if path.is_symlink():
            continue
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(row, dict) or row.get("status") != "active" or not row.get("module_capsule_id"):
            continue
        kind = str(row.get("module_kind") or "behavior")
        item = {
            "id": str(row["module_capsule_id"]),
            "name": kind.replace("_", " ").title(),
            "type": "Behavior module",
            "tags": [str(tag) for tag in row.get("capability_tags", []) if tag],
            "status": "active",
            "origin": COMPOSER_OWNER,
            "moduleKind": kind,
            "source": str((row.get("provenance") or {}).get("source_preview_id") or ""),
        }
        if row.get("capability_summary"):
            item["capabilitySummary"] = str(row["capability_summary"])
        result.append(item)
    return result


__all__ = [
    "COMPOSER_OWNER",
    "COMPOSER_SOURCE_OWNERSHIP",
    "compose_with_stage4",
    "extract_many_with_stage4",
    "extract_with_stage4",
    "list_stage4_module_capsules",
    "plan_with_stage4",
]
