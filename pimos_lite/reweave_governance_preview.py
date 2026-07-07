"""Reweave governance preview — read-only suggestion governance, no apply."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pimos_lite.reweave_capsule_draft import draft_rel_path
from pimos_lite.reweave_source_registry import state_dir
from pimos_lite.reweave_source_scanner import summary_rel_path

GOVERNANCE_PREVIEW_SCHEMA_VERSION = 1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def governance_previews_dir() -> Path:
    return state_dir() / "governance_previews"


def governance_preview_file_path(source_id: str) -> Path:
    return governance_previews_dir() / f"{source_id}.governance_preview.json"


def load_governance_preview(source_id: str) -> dict[str, Any] | None:
    path = governance_preview_file_path(source_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def save_governance_preview(source_id: str, record: dict[str, Any]) -> str:
    path = governance_preview_file_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return f"governance_previews/{source_id}.governance_preview.json"


def _duplicate_key(item: dict[str, Any]) -> tuple[str, str, str]:
    name = str(item.get("name") or "").strip().lower()
    suggested_type = str(item.get("suggested_type") or item.get("type") or "").strip().upper()
    origin = str(item.get("origin") or item.get("source") or "luna_reuse_pack").strip().lower()
    return name, suggested_type, origin


def _mark_duplicate_lowers(results: list[dict[str, Any]]) -> set[str]:
    """Return ids of lower-scoring duplicates that should be flagged."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in results:
        key = _duplicate_key(item)
        if not key[0]:
            continue
        groups.setdefault(key, []).append(item)

    flagged: set[str] = set()
    for items in groups.values():
        if len(items) < 2:
            continue
        ranked = sorted(items, key=lambda x: float(x.get("verification_score") or 0), reverse=True)
        for dup in ranked[1:]:
            item_id = str(dup.get("id") or "")
            if item_id:
                flagged.add(item_id)
    return flagged


def _governance_for_item(
    item: dict[str, Any],
    *,
    duplicate_lower: bool,
) -> tuple[str, str]:
    status = str(item.get("verification_status") or "watch")
    try:
        score = float(item.get("verification_score") or 0)
    except (TypeError, ValueError):
        score = 0.0

    if status == "rejected":
        return "prune", "Verification rejected by metadata rules."

    if status == "watch":
        if duplicate_lower:
            return "needs_manual_review", "Duplicate watch suggestion with lower verification score."
        return "watch", "Metadata match inconclusive; continue monitoring."

    if status == "verified":
        if score >= 0.8:
            if duplicate_lower:
                return "needs_manual_review", "Verified but duplicate of a higher-ranked suggestion."
            return "keep", "High metadata match and supported by local source summary."
        if score >= 0.75:
            if duplicate_lower:
                return "needs_manual_review", "Verified with moderate confidence and duplicate overlap."
            return "needs_manual_review", "Verified with moderate metadata confidence."

    if duplicate_lower:
        return "prune", "Low verification confidence with duplicate overlap."
    return "prune", "Low verification confidence."


def build_governance_preview(
    source_id: str,
    verification: dict[str, Any],
    reuse_record: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    draft: dict[str, Any] | None = None,
    *,
    luna_preview: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build read-only governance preview from verification results."""
    verification_results = verification.get("results") if isinstance(verification.get("results"), list) else []
    duplicate_lowers = _mark_duplicate_lowers(verification_results)

    results: list[dict[str, Any]] = []
    for item in verification_results:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        action, reason = _governance_for_item(item, duplicate_lower=item_id in duplicate_lowers)
        results.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "origin": item.get("origin") or "luna_reuse_pack",
                "verification_status": item.get("verification_status"),
                "verification_score": item.get("verification_score"),
                "governance_action": action,
                "governance_reason": reason,
                "risk": "preview_only",
                "warehouse_action": "none",
            }
        )

    summary_counts = {
        "keep": 0,
        "watch": 0,
        "prune": 0,
        "needs_manual_review": 0,
        "total": len(results),
    }
    for item in results:
        action = item.get("governance_action")
        if action in summary_counts:
            summary_counts[action] += 1

    record: dict[str, Any] = {
        "schema_version": GOVERNANCE_PREVIEW_SCHEMA_VERSION,
        "source_id": source_id,
        "previewed_at": _utc_now_iso(),
        "mode": "preview_only",
        "inputs": {
            "verification_path": f"verified_suggestions/{source_id}.verification.json",
            "reuse_suggestions_path": f"reuse_suggestions/{source_id}.luna_reuse_pack.json",
            "summary_path": summary_rel_path(source_id) if summary else None,
            "draft_path": draft_rel_path(source_id) if draft else None,
        },
        "limits": {
            "no_apply": True,
            "no_promote": True,
            "no_warehouse_write": True,
            "no_source_content_read": True,
        },
        "results": results,
        "summary": summary_counts,
        "warnings": list(warnings or []),
    }
    if luna_preview:
        record["luna_preview"] = luna_preview
    if reuse_record and isinstance(reuse_record.get("query_summary"), str):
        record["inputs"]["reuse_query_summary"] = reuse_record["query_summary"][:500]
    return record


def preview_and_save(
    source_id: str,
    verification: dict[str, Any],
    reuse_record: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    draft: dict[str, Any] | None = None,
    *,
    luna_preview: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    record = build_governance_preview(
        source_id,
        verification,
        reuse_record,
        summary,
        draft,
        luna_preview=luna_preview,
        warnings=warnings,
    )
    save_governance_preview(source_id, record)
    return record
