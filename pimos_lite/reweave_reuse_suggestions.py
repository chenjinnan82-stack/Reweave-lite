"""Luna reuse-pack suggestions — suggestion layer only, never warehouse."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pimos_lite.reweave_source_registry import state_dir

SUGGESTIONS_SCHEMA_VERSION = 1
REUSE_PACK_ENDPOINT = "/api/v1/reuse/pack"

_KIND_TYPE_MAP: dict[str, str] = {
    "ui": "UI",
    "frontend": "UI",
    "html": "UI",
    "style": "Style",
    "css": "Style",
    "logic": "Logic",
    "backend": "Logic",
    "api": "Logic",
    "qa_lesson": "Text",
    "lesson": "Text",
    "export": "Export",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def suggestions_dir() -> Path:
    return state_dir() / "reuse_suggestions"


def suggestion_file_path(source_id: str) -> Path:
    return suggestions_dir() / f"{source_id}.luna_reuse_pack.json"


def _infer_type(kind: str, title: str) -> str:
    kind_l = (kind or "").lower()
    title_l = (title or "").lower()
    for key, cap_type in _KIND_TYPE_MAP.items():
        if key in kind_l or key in title_l:
            return cap_type
    return "Logic"


def _normalize_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score > 1.0:
        score = score / 100.0
    return max(0.0, min(1.0, score))


def map_luna_assets_to_suggestions(assets: list[Any], *, pack_query: str = "") -> list[dict[str, Any]]:
    """Map Luna reuse-pack assets to Reweave capsule suggestions (never warehouse entries)."""
    suggestions: list[dict[str, Any]] = []
    for index, item in enumerate(assets):
        if not isinstance(item, dict):
            continue
        asset_id = str(item.get("id") or item.get("asset_id") or f"asset_{index}")
        title = str(item.get("title") or item.get("name") or f"Suggestion {index + 1}")
        kind = str(item.get("kind") or item.get("type") or "artifact")
        score = _normalize_score(item.get("score"))
        suggestion_id = f"luna_asset_{asset_id.replace(':', '_')}"
        suggestions.append(
            {
                "id": suggestion_id,
                "name": title[:120],
                "type": _infer_type(kind, title),
                "source": "luna_reuse_pack",
                "origin": "luna_reuse_pack",
                "status": "suggestion",
                "confidence": score,
                "risk": "suggestion_only",
                "role": str(item.get("reuse_hint") or item.get("summary") or "")[:240],
                "tags": [kind] if kind else [],
                "luna": {
                    "asset_id": asset_id,
                    "score": score,
                    "kind": kind,
                    "title": title,
                    "query": pack_query[:200],
                },
            }
        )
    return suggestions


def _light_assets(assets: list[Any]) -> list[dict[str, Any]]:
    light: list[dict[str, Any]] = []
    for item in assets[:20]:
        if not isinstance(item, dict):
            continue
        light.append(
            {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "title": item.get("title"),
                "score": item.get("score"),
                "reuse_hint": item.get("reuse_hint"),
            }
        )
    return light


def save_reuse_suggestions(source_id: str, record: dict[str, Any]) -> str:
    path = suggestion_file_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return f"reuse_suggestions/{source_id}.luna_reuse_pack.json"


def load_reuse_suggestions(source_id: str) -> dict[str, Any] | None:
    path = suggestion_file_path(source_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def build_reuse_suggestions_record(
    source_id: str,
    *,
    query_payload: dict[str, Any],
    reuse_result: dict[str, Any],
    capsule_suggestions: list[dict[str, Any]],
    warnings: list[str],
    luna_ok: bool,
) -> dict[str, Any]:
    raw = reuse_result.get("raw") if isinstance(reuse_result.get("raw"), dict) else {}
    assets = reuse_result.get("assets") if isinstance(reuse_result.get("assets"), list) else []
    return {
        "schema_version": SUGGESTIONS_SCHEMA_VERSION,
        "source_id": source_id,
        "requested_at": _utc_now_iso(),
        "endpoint": REUSE_PACK_ENDPOINT,
        "query_payload": query_payload,
        "query_summary": str(query_payload.get("query") or "")[:500],
        "assets": _light_assets(assets),
        "mapped_capsuleSuggestions": capsule_suggestions,
        "warnings": warnings,
        "luna_ok": luna_ok,
        "raw_keys": sorted(raw.keys()) if raw else [],
    }
