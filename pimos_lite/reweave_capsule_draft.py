"""Reweave Capsule Candidate Draft v0 — rule-based drafts from scan summaries only."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pimos_lite.reweave_source_registry import get_source_box, mark_source_draft_failed, mark_source_drafted
from pimos_lite.reweave_source_registry import state_dir
from pimos_lite.reweave_source_scanner import load_summary

DRAFT_SCHEMA_VERSION = 1

_EXT_RULES: list[tuple[str, str, str, list[str], list[str]]] = [
    (".html", "HTML Surface", "UI", ["html", "layout"], ["<html>", "  …", "</html>"]),
    (".css", "Style Sheet", "Style", ["css", "layout"], [".surface {", "  …", "}"]),
    (".js", "Script Module", "Logic", ["javascript", "logic"], ["function …()", "export …"]),
    (".ts", "Type Module", "Logic", ["typescript", "logic"], ["interface …", "export …"]),
    (".py", "Python Module", "Logic", ["python", "logic"], ["def …():", "  …"]),
    (".json", "JSON Data", "Logic", ["json", "data"], ["{", "  …", "}"]),
    (".md", "Markdown Doc", "Text", ["docs", "copy"], ["# …", "…"]),
]

_ENTRY_RULES: dict[str, tuple[str, str, str, list[str], list[str]]] = {
    "index.html": ("Page Shell", "UI", "entry page structure", ["html", "entry"], ["<html>", "  <body>", "</html>"]),
    "main.py": ("App Entry", "Logic", "application entrypoint", ["python", "entry"], ["if __name__ == '__main__':"]),
    "app.py": ("App Entry", "Logic", "application entrypoint", ["python", "entry"], ["app = …"]),
    "package.json": ("Package Manifest", "Export", "package metadata", ["npm", "export"], ['"name": …']),
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def drafts_dir() -> Path:
    return state_dir() / "capsule_drafts"


def draft_file_path(source_id: str) -> Path:
    return drafts_dir() / f"{source_id}.draft.json"


def draft_rel_path(source_id: str) -> str:
    return f"capsule_drafts/{source_id}.draft.json"


def _serial_for(draft_id: str) -> str:
    digest = hashlib.sha256(draft_id.encode("utf-8")).hexdigest()[:2].upper()
    return digest


def _candidate_from_rule(
    source_id: str,
    source_label: str,
    suffix: str,
    name: str,
    cap_type: str,
    role: str,
    tags: list[str],
    preview: list[str],
) -> dict[str, Any]:
    draft_id = f"draft_{source_id}_{suffix}"
    return {
        "draft_id": draft_id,
        "name": name,
        "type": cap_type,
        "serial": _serial_for(draft_id),
        "source_id": source_id,
        "source": source_label,
        "tags": tags,
        "role": role,
        "preview": preview,
        "status": "draft",
    }


def build_draft_candidates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Build capsule draft candidates from a scan summary (no file reads)."""
    source_id = str(summary.get("source_id", ""))
    source_label = str(summary.get("label") or source_id)
    extensions = summary.get("extensions") if isinstance(summary.get("extensions"), dict) else {}
    entry_candidates = summary.get("entry_candidates") if isinstance(summary.get("entry_candidates"), list) else []

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(candidate: dict[str, Any]) -> None:
        key = candidate["draft_id"]
        if key in seen:
            return
        seen.add(key)
        candidates.append(candidate)

    for entry in entry_candidates:
        base = Path(str(entry)).name
        rule = _ENTRY_RULES.get(base)
        if not rule:
            continue
        name, cap_type, role, tags, preview = rule
        suffix = base.replace(".", "_")
        add(_candidate_from_rule(source_id, source_label, suffix, name, cap_type, role, tags, preview))

    for ext, count in sorted(extensions.items(), key=lambda kv: (-kv[1], kv[0])):
        if count <= 0:
            continue
        for rule_ext, name, cap_type, tags, preview in _EXT_RULES:
            if ext != rule_ext:
                continue
            suffix = (ext or "none").lstrip(".") + "_ext"
            role = f"reusable {ext or 'file'} pattern ({count} files)"
            add(_candidate_from_rule(source_id, source_label, suffix, name, cap_type, role, tags, preview))
            break

    return candidates[:8]


def save_draft(draft: dict[str, Any]) -> str:
    path = draft_file_path(draft["source_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return draft_rel_path(draft["source_id"])


def load_draft(source_id: str) -> dict[str, Any] | None:
    path = draft_file_path(source_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def load_draft_light(source_id: str) -> dict[str, Any] | None:
    draft = load_draft(source_id)
    if not draft:
        return None
    candidates = draft.get("candidates") if isinstance(draft.get("candidates"), list) else []
    return {
        "source_id": source_id,
        "drafted_at": draft.get("drafted_at"),
        "candidate_count": len(candidates),
    }


def list_draft_lights() -> list[dict[str, Any]]:
    lights: list[dict[str, Any]] = []
    if not drafts_dir().is_dir():
        return lights
    for path in sorted(drafts_dir().glob("source_*.draft.json")):
        source_id = path.name.replace(".draft.json", "")
        light = load_draft_light(source_id)
        if light:
            lights.append(light)
    return lights


def draft_capsules(source_id: str) -> dict[str, Any]:
    """Create draft candidates from an existing scan summary."""
    box = get_source_box(source_id)
    if not box:
        raise KeyError(f"source not found: {source_id}")
    if box.get("scan_status") != "scanned":
        raise ValueError("source must be scanned before drafting")

    summary = load_summary(source_id)
    if not summary:
        raise FileNotFoundError(f"scan summary missing for: {source_id}")

    try:
        candidates = build_draft_candidates(summary)
        draft = {
            "schema_version": DRAFT_SCHEMA_VERSION,
            "source_id": source_id,
            "label": summary.get("label") or box.get("label"),
            "drafted_at": _utc_now_iso(),
            "candidate_count": len(candidates),
            "candidates": candidates,
        }
        rel = save_draft(draft)
        mark_source_drafted(source_id, rel, draft["drafted_at"])
        return draft
    except Exception as exc:
        mark_source_draft_failed(source_id, str(exc))
        raise
