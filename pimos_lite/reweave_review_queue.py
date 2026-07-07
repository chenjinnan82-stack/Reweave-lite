"""Reweave manual review queue — human decisions only, never warehouse."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pimos_lite.reweave_source_registry import state_dir

REVIEW_QUEUE_SCHEMA_VERSION = 1
VALID_DECISIONS = frozenset({"pending", "approved", "rejected", "deferred"})
QUEUE_GOVERNANCE_ACTIONS = frozenset({"keep", "needs_manual_review", "watch"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def review_queue_dir() -> Path:
    return state_dir() / "review_queue"


def review_queue_file_path(source_id: str) -> Path:
    return review_queue_dir() / f"{source_id}.review_queue.json"


def load_review_queue(source_id: str) -> dict[str, Any] | None:
    path = review_queue_file_path(source_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def save_review_queue(source_id: str, record: dict[str, Any]) -> str:
    path = review_queue_file_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return f"review_queue/{source_id}.review_queue.json"


def _review_id_for(suggestion_id: str) -> str:
    safe = str(suggestion_id or "unknown").replace(":", "_").replace("/", "_")
    return f"review_{safe}"


def _verification_type_lookup(verification: dict[str, Any] | None) -> dict[str, str]:
    lookup: dict[str, str] = {}
    if not verification:
        return lookup
    results = verification.get("results") if isinstance(verification.get("results"), list) else []
    for item in results:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "")
        if sid:
            lookup[sid] = str(item.get("suggested_type") or item.get("type") or "Logic")
    return lookup


def _default_decision(governance_action: str) -> str:
    if governance_action == "watch":
        return "deferred"
    return "pending"


def _queue_item_from_governance(
    gov_item: dict[str, Any],
    *,
    type_lookup: dict[str, str],
) -> dict[str, Any]:
    suggestion_id = str(gov_item.get("id") or "")
    governance_action = str(gov_item.get("governance_action") or "")
    return {
        "review_id": _review_id_for(suggestion_id),
        "suggestion_id": suggestion_id,
        "name": gov_item.get("name"),
        "origin": gov_item.get("origin") or "luna_reuse_pack",
        "suggested_type": type_lookup.get(suggestion_id, "Logic"),
        "verification_status": gov_item.get("verification_status"),
        "verification_score": gov_item.get("verification_score"),
        "governance_action": governance_action,
        "governance_reason": gov_item.get("governance_reason") or "",
        "decision": _default_decision(governance_action),
        "decision_reason": "",
        "risk": "manual_review_required",
        "warehouse_action": "none",
    }


def _summarize_items(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"pending": 0, "approved": 0, "rejected": 0, "deferred": 0, "total": len(items)}
    for item in items:
        decision = str(item.get("decision") or "pending")
        if decision in summary:
            summary[decision] += 1
    return summary


def _merge_existing_decisions(
    new_items: list[dict[str, Any]],
    existing: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not existing:
        return new_items
    prior_items = existing.get("items") if isinstance(existing.get("items"), list) else []
    by_suggestion: dict[str, dict[str, Any]] = {}
    by_review: dict[str, dict[str, Any]] = {}
    for item in prior_items:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("suggestion_id") or "")
        rid = str(item.get("review_id") or "")
        if sid:
            by_suggestion[sid] = item
        if rid:
            by_review[rid] = item

    merged: list[dict[str, Any]] = []
    for item in new_items:
        sid = str(item.get("suggestion_id") or "")
        rid = str(item.get("review_id") or "")
        old = by_suggestion.get(sid) or by_review.get(rid)
        if old:
            item = dict(item)
            item["review_id"] = str(old.get("review_id") or item["review_id"])
            item["decision"] = str(old.get("decision") or item["decision"])
            item["decision_reason"] = str(old.get("decision_reason") or "")
            if old.get("promoted"):
                item["promoted"] = True
                item["promoted_at"] = old.get("promoted_at")
                item["capsule_id"] = old.get("capsule_id")
                item["warehouse_action"] = old.get("warehouse_action", "promoted")
        merged.append(item)
    return merged


def build_review_queue(
    source_id: str,
    governance_preview: dict[str, Any],
    verification: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build manual review queue from governance preview (worth-review items only)."""
    results = governance_preview.get("results") if isinstance(governance_preview.get("results"), list) else []
    type_lookup = _verification_type_lookup(verification)

    items: list[dict[str, Any]] = []
    for gov_item in results:
        if not isinstance(gov_item, dict):
            continue
        action = str(gov_item.get("governance_action") or "")
        if action not in QUEUE_GOVERNANCE_ACTIONS:
            continue
        items.append(_queue_item_from_governance(gov_item, type_lookup=type_lookup))

    items = _merge_existing_decisions(items, existing)
    now = _utc_now_iso()
    created_at = now
    if existing and isinstance(existing.get("created_at"), str):
        created_at = existing["created_at"]

    return {
        "schema_version": REVIEW_QUEUE_SCHEMA_VERSION,
        "source_id": source_id,
        "created_at": created_at,
        "updated_at": now,
        "mode": "manual_review_only",
        "inputs": {
            "governance_preview_path": f"governance_previews/{source_id}.governance_preview.json",
            "verification_path": f"verified_suggestions/{source_id}.verification.json",
            "reuse_suggestions_path": f"reuse_suggestions/{source_id}.luna_reuse_pack.json",
        },
        "limits": {
            "no_promote": True,
            "no_warehouse_write": True,
            "no_apply": True,
            "no_dispatch": True,
            "no_source_content_read": True,
        },
        "items": items,
        "summary": _summarize_items(items),
    }


def create_or_update_review_queue(
    source_id: str,
    governance_preview: dict[str, Any],
    verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = load_review_queue(source_id)
    record = build_review_queue(source_id, governance_preview, verification, existing)
    save_review_queue(source_id, record)
    return record


def update_review_decision(
    source_id: str,
    review_id: str,
    decision: str,
    reason: str = "",
) -> dict[str, Any]:
    """Update one queue item decision — never touches warehouse."""
    decision_norm = (decision or "").strip().lower()
    if decision_norm not in VALID_DECISIONS:
        raise ValueError(f"invalid decision: {decision}")

    record = load_review_queue(source_id)
    if not record:
        raise FileNotFoundError(f"review queue missing for: {source_id}")

    items = record.get("items") if isinstance(record.get("items"), list) else []
    updated_item: dict[str, Any] | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("review_id") or "") == review_id:
            item["decision"] = decision_norm
            item["decision_reason"] = (reason or "")[:500]
            item["warehouse_action"] = "none"
            updated_item = dict(item)
            break

    if updated_item is None:
        raise KeyError(f"review item not found: {review_id}")

    record["updated_at"] = _utc_now_iso()
    record["summary"] = _summarize_items(items)
    save_review_queue(source_id, record)
    return {"queue": record, "item": updated_item, "summary": record["summary"]}
