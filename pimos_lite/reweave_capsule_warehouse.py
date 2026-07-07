"""Reweave Capsule Warehouse v0 — local capsule store (promoted from drafts)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pimos_lite.reweave_capsule_draft import load_draft
from pimos_lite.reweave_source_registry import get_source_box, load_json_state, mark_source_promoted
from pimos_lite.reweave_source_registry import state_dir

WAREHOUSE_SCHEMA_VERSION = 1
WAREHOUSE_FILENAME = "capsules.json"
VALID_CAPSULE_STATUSES = frozenset({"active", "ready", "disabled", "deprecated"})
GENERATE_ELIGIBLE_STATUSES = frozenset({"active", "ready"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def warehouse_dir() -> Path:
    return state_dir() / "capsule_warehouse"


def warehouse_path() -> Path:
    return warehouse_dir() / WAREHOUSE_FILENAME


def load_warehouse() -> dict[str, Any]:
    data = load_json_state(warehouse_path(), {"schema_version": WAREHOUSE_SCHEMA_VERSION, "capsules": []})
    data.setdefault("schema_version", WAREHOUSE_SCHEMA_VERSION)
    data.setdefault("capsules", [])
    return data


def save_warehouse(data: dict[str, Any]) -> None:
    warehouse_dir().mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": WAREHOUSE_SCHEMA_VERSION,
        "capsules": data.get("capsules", []),
    }
    path = warehouse_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _capsule_id_from_draft(draft_id: str) -> str:
    digest = hashlib.sha256(draft_id.encode("utf-8")).hexdigest()[:12]
    return f"cap_{digest}"


def list_capsules() -> list[dict[str, Any]]:
    caps = load_warehouse().get("capsules", [])
    return [dict(c) for c in caps if isinstance(c, dict)]


def status_log_path() -> Path:
    return warehouse_dir() / "status_log.jsonl"


def append_status_log(event: dict[str, Any]) -> None:
    path = status_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _source_ref(cap: dict[str, Any]) -> dict[str, str]:
    source_box = cap.get("source_box") if isinstance(cap.get("source_box"), dict) else {}
    source_id = str(cap.get("source_id") or source_box.get("source_id") or "")
    raw_source = cap.get("source")
    if isinstance(raw_source, dict):
        source_id = source_id or str(raw_source.get("source_id") or "")
        label = str(raw_source.get("label") or source_id)
    else:
        label = str(raw_source or source_box.get("label") or source_id or "")
    return {"source_id": source_id, "label": label}


def normalize_capsule_record(cap: dict[str, Any]) -> dict[str, Any]:
    """Normalize warehouse capsule for API / dock (no source folder reads)."""
    source = _source_ref(cap)
    status = str(cap.get("status") or "active")
    record: dict[str, Any] = {
        "id": cap.get("id"),
        "name": cap.get("name"),
        "type": cap.get("type"),
        "status": status,
        "origin": cap.get("origin"),
        "source": source,
        "serial": cap.get("serial"),
        "icon": cap.get("icon") or _icon_for_type(str(cap.get("type") or "Logic")),
        "tags": list(cap.get("tags") or []),
        "role": cap.get("role") or "",
        "preview": list(cap.get("preview") or []),
        "risk": cap.get("risk"),
        "content_mode": cap.get("content_mode"),
        "snippet": cap.get("snippet") if isinstance(cap.get("snippet"), dict) else None,
        "created_at": cap.get("created_at") or cap.get("promoted_at"),
        "updated_at": cap.get("updated_at") or cap.get("promoted_at"),
    }
    if isinstance(cap.get("lineage"), dict):
        record["lineage"] = dict(cap["lineage"])
    if isinstance(cap.get("content_enrichment"), dict):
        record["content_enrichment"] = dict(cap["content_enrichment"])
    if cap.get("content_risk"):
        record["content_risk"] = cap.get("content_risk")
    return record


def is_generate_eligible(cap: dict[str, Any]) -> bool:
    return str(cap.get("status") or "active") in GENERATE_ELIGIBLE_STATUSES


def list_warehouse_capsules(*, include_inactive: bool = True) -> list[dict[str, Any]]:
    """List warehouse capsules from app state only."""
    capsules = [normalize_capsule_record(c) for c in list_capsules()]
    if include_inactive:
        return capsules
    return [c for c in capsules if is_generate_eligible(c)]


def list_generate_eligible_capsules() -> list[dict[str, Any]]:
    return list_warehouse_capsules(include_inactive=False)


def update_capsule_status(capsule_id: str, status: str) -> dict[str, Any]:
    """Update warehouse capsule status metadata — never deletes or touches source folder."""
    capsule_id = (capsule_id or "").strip()
    status_norm = (status or "").strip().lower()
    if not capsule_id:
        raise ValueError("missing capsule_id")
    if status_norm not in VALID_CAPSULE_STATUSES:
        raise ValueError(f"invalid status: {status}")

    data = load_warehouse()
    capsules: list[dict[str, Any]] = data.setdefault("capsules", [])
    updated: dict[str, Any] | None = None
    now = _utc_now_iso()
    for cap in capsules:
        if not isinstance(cap, dict):
            continue
        if str(cap.get("id") or "") != capsule_id:
            continue
        prior = str(cap.get("status") or "active")
        cap["status"] = status_norm
        cap["updated_at"] = now
        updated = dict(cap)
        append_status_log(
            {
                "event": "capsule_status_update",
                "capsule_id": capsule_id,
                "from_status": prior,
                "to_status": status_norm,
                "created_at": now,
            }
        )
        break

    if updated is None:
        raise KeyError(f"capsule not found: {capsule_id}")

    save_warehouse(data)
    return {
        "ok": True,
        "capsule_id": capsule_id,
        "status": status_norm,
        "capsule": normalize_capsule_record(updated),
        "capsules": list_warehouse_capsules(include_inactive=True),
    }


def get_capsule(capsule_id: str) -> dict[str, Any] | None:
    for cap in list_capsules():
        if cap.get("id") == capsule_id:
            return cap
    return None


def append_capsule_if_absent(capsule: dict[str, Any]) -> tuple[bool, str]:
    """Append capsule if id/review_id absent. Returns (created, capsule_id)."""
    cap_id = str(capsule.get("id") or "")
    review_id = str(capsule.get("review_id") or "")
    data = load_warehouse()
    capsules: list[dict[str, Any]] = data.setdefault("capsules", [])
    for existing in capsules:
        if not isinstance(existing, dict):
            continue
        if cap_id and existing.get("id") == cap_id:
            return False, cap_id
        if review_id and existing.get("review_id") == review_id:
            return False, str(existing.get("id") or cap_id)
    capsules.append(capsule)
    save_warehouse(data)
    return True, cap_id


def promote_source_drafts(source_id: str) -> list[dict[str, Any]]:
    """Promote draft candidates for one source into the warehouse."""
    box = get_source_box(source_id)
    if not box:
        raise KeyError(f"source not found: {source_id}")

    draft = load_draft(source_id)
    if not draft:
        raise FileNotFoundError(f"draft missing for: {source_id}")

    candidates = draft.get("candidates") if isinstance(draft.get("candidates"), list) else []
    if not candidates:
        raise ValueError("no draft candidates to promote")

    data = load_warehouse()
    capsules: list[dict[str, Any]] = data.setdefault("capsules", [])
    existing_ids = {c.get("id") for c in capsules if isinstance(c, dict)}
    promoted: list[dict[str, Any]] = []
    now = _utc_now_iso()

    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        draft_id = str(cand.get("draft_id", ""))
        cap_id = _capsule_id_from_draft(draft_id)
        if cap_id in existing_ids:
            continue
        capsule = {
            "id": cap_id,
            "name": cand.get("name", "Capsule"),
            "type": cand.get("type", "UI"),
            "serial": cand.get("serial") or "00",
            "icon": _icon_for_type(str(cand.get("type", "UI"))),
            "source": str(cand.get("source") or box.get("label") or source_id),
            "source_id": source_id,
            "tags": list(cand.get("tags") or []),
            "role": str(cand.get("role") or "reusable module"),
            "preview": list(cand.get("preview") or ["…"]),
            "status": "ready",
            "promoted_at": now,
            "draft_id": draft_id,
        }
        capsules.append(capsule)
        existing_ids.add(cap_id)
        promoted.append(capsule)

    save_warehouse(data)
    mark_source_promoted(source_id, now, len(promoted))
    return promoted


def _icon_for_type(cap_type: str) -> str:
    mapping = {
        "UI": "</>",
        "Logic": "{}",
        "Style": "◫",
        "Text": "≡",
        "Export": "⇩",
        "Guard": "⛨",
    }
    return mapping.get(cap_type, "◫")


def clear_warehouse() -> None:
    """Testing helper."""
    save_warehouse({"schema_version": WAREHOUSE_SCHEMA_VERSION, "capsules": []})
