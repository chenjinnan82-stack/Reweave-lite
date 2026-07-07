"""Reweave explicit promote — approved review items to local warehouse only."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pimos_lite.reweave_capsule_warehouse import _icon_for_type, append_capsule_if_absent, get_capsule, list_capsules
from pimos_lite.reweave_review_queue import load_review_queue, save_review_queue
from pimos_lite.reweave_source_registry import get_source_box, state_dir

PROMOTE_ORIGIN = "manual_promote"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def promote_logs_dir() -> Path:
    return state_dir() / "promote_logs"


def promote_log_path(source_id: str) -> Path:
    return promote_logs_dir() / f"{source_id}.promote_log.jsonl"


def _capsule_id_from_review(review_id: str) -> str:
    digest = hashlib.sha256(review_id.encode("utf-8")).hexdigest()[:12]
    return f"cap_{digest}"


def _serial_from_review(review_id: str) -> str:
    digest = hashlib.sha256(review_id.encode("utf-8")).hexdigest()[:2].upper()
    return digest


def append_promote_log(source_id: str, event: dict[str, Any]) -> None:
    path = promote_log_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _find_review_item(record: dict[str, Any], review_id: str) -> dict[str, Any] | None:
    items = record.get("items") if isinstance(record.get("items"), list) else []
    for item in items:
        if isinstance(item, dict) and str(item.get("review_id") or "") == review_id:
            return item
    return None


def build_capsule_from_review_item(
    item: dict[str, Any],
    *,
    source_id: str,
    source_label: str,
    capsule_id: str,
    now: str,
) -> dict[str, Any]:
    cap_type = str(item.get("suggested_type") or "Logic")
    suggestion_id = str(item.get("suggestion_id") or "")
    review_id = str(item.get("review_id") or "")
    name = str(item.get("name") or "Promoted Suggestion")
    return {
        "id": capsule_id,
        "name": name,
        "type": cap_type,
        "status": "active",
        "origin": PROMOTE_ORIGIN,
        "serial": _serial_from_review(review_id),
        "icon": _icon_for_type(cap_type),
        "source": source_label,
        "source_id": source_id,
        "source_box": {
            "source_id": source_id,
            "label": source_label,
        },
        "tags": ["luna_reuse_pack", "manual_promote", "metadata_only"],
        "role": str(item.get("governance_reason") or "Promoted from verified Luna suggestion (metadata only)"),
        "preview": [
            "metadata-only promoted capsule",
            f"suggestion: {suggestion_id}",
            "No source content was read.",
        ],
        "lineage": {
            "suggestion_id": suggestion_id,
            "review_id": review_id,
            "origin": item.get("origin") or "luna_reuse_pack",
            "verification_status": item.get("verification_status"),
            "verification_score": item.get("verification_score"),
            "governance_action": item.get("governance_action"),
            "review_decision": item.get("decision"),
        },
        "risk": "metadata_only_promoted",
        "content_mode": "metadata_snippet",
        "snippet": {
            "kind": "metadata_summary",
            "description": "Promoted from verified Luna suggestion. No source content was read.",
            "evidence": [],
        },
        "review_id": review_id,
        "promoted_at": now,
        "created_at": now,
        "updated_at": now,
    }


def promote_review_item(source_id: str, review_id: str) -> dict[str, Any]:
    """Promote one approved review queue item into local warehouse (explicit, idempotent)."""
    source_id = (source_id or "").strip()
    review_id = (review_id or "").strip()
    if not source_id or not review_id:
        return {"ok": False, "error": "missing source_id or review_id"}

    record = load_review_queue(source_id)
    if not record:
        return {"ok": False, "error": "no_review_queue", "source_id": source_id}

    item = _find_review_item(record, review_id)
    if not item:
        return {"ok": False, "error": "review_item_not_found", "source_id": source_id, "review_id": review_id}

    if str(item.get("decision") or "") != "approved":
        return {"ok": False, "error": "review_item_not_approved", "source_id": source_id, "review_id": review_id}

    capsule_id = str(item.get("capsule_id") or _capsule_id_from_review(review_id))
    if item.get("promoted") and capsule_id:
        return {
            "ok": True,
            "already_promoted": True,
            "source_id": source_id,
            "review_id": review_id,
            "capsule_id": capsule_id,
            "warehouse_action": "promoted",
        }

    existing = get_capsule(capsule_id)
    if existing:
        now = _utc_now_iso()
        item["promoted"] = True
        item["promoted_at"] = item.get("promoted_at") or now
        item["capsule_id"] = capsule_id
        item["warehouse_action"] = "promoted"
        record["updated_at"] = now
        save_review_queue(source_id, record)
        return {
            "ok": True,
            "already_promoted": True,
            "source_id": source_id,
            "review_id": review_id,
            "capsule_id": capsule_id,
            "warehouse_action": "promoted",
        }

    box = get_source_box(source_id)
    source_label = str((box or {}).get("label") or source_id)
    now = _utc_now_iso()
    capsule = build_capsule_from_review_item(
        item,
        source_id=source_id,
        source_label=source_label,
        capsule_id=capsule_id,
        now=now,
    )
    created, final_id = append_capsule_if_absent(capsule)
    capsule_id = final_id

    append_promote_log(
        source_id,
        {
            "event": "promote_to_warehouse",
            "source_id": source_id,
            "review_id": review_id,
            "suggestion_id": item.get("suggestion_id"),
            "capsule_id": capsule_id,
            "created_at": now,
            "origin": PROMOTE_ORIGIN,
            "safety": {
                "source_folder_written": False,
                "source_content_read": False,
                "luna_apply_called": False,
                "dispatch_called": False,
                "recovery_promote_called": False,
            },
        },
    )

    item["promoted"] = True
    item["promoted_at"] = now
    item["capsule_id"] = capsule_id
    item["warehouse_action"] = "promoted"
    record["updated_at"] = now
    save_review_queue(source_id, record)

    return {
        "ok": True,
        "source_id": source_id,
        "review_id": review_id,
        "capsule_id": capsule_id,
        "warehouse_action": "promoted",
        "created": created,
        "already_promoted": not created,
        "capsules": list_capsules(),
    }
