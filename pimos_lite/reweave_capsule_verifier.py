"""Reweave capsule suggestion verifier — metadata-only, no source reads."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pimos_lite.reweave_capsule_draft import draft_rel_path
from pimos_lite.reweave_reuse_suggestions import suggestion_file_path
from pimos_lite.reweave_source_registry import state_dir
from pimos_lite.reweave_source_scanner import summary_rel_path

VERIFICATION_SCHEMA_VERSION = 1
VERIFIED_THRESHOLD = 0.75
WATCH_THRESHOLD = 0.45

UI_EXTENSIONS = frozenset({".html", ".css", ".js", ".jsx", ".tsx", ".vue", ".svelte"})
PYTHON_ENTRIES = frozenset({"main.py", "app.py", "cli.py"})
CONFIG_ENTRIES = frozenset({"package.json", "pyproject.toml", "requirements.txt", "tsconfig.json"})
DATA_EXTENSIONS = frozenset({".json", ".yaml", ".yml", ".csv"})
DOC_EXTENSIONS = frozenset({".md"})
PYTHON_EXTENSIONS = frozenset({".py"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def verified_suggestions_dir() -> Path:
    return state_dir() / "verified_suggestions"


def verification_file_path(source_id: str) -> Path:
    return verified_suggestions_dir() / f"{source_id}.verification.json"


def load_verification(source_id: str) -> dict[str, Any] | None:
    path = verification_file_path(source_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def save_verification(source_id: str, record: dict[str, Any]) -> str:
    path = verification_file_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return f"verified_suggestions/{source_id}.verification.json"


def _status_from_score(score: float) -> str:
    if score >= VERIFIED_THRESHOLD:
        return "verified"
    if score >= WATCH_THRESHOLD:
        return "watch"
    return "rejected"


def _normalize_ext(ext: str) -> str:
    raw = (ext or "").strip().lower()
    if not raw:
        return ""
    return raw if raw.startswith(".") else f".{raw}"


def _entry_basenames(entry_candidates: list[Any]) -> set[str]:
    names: set[str] = set()
    for entry in entry_candidates:
        base = Path(str(entry)).name.lower()
        if base:
            names.add(base)
    return names


def _summary_profile(summary: dict[str, Any]) -> dict[str, Any]:
    extensions_raw = summary.get("extensions") if isinstance(summary.get("extensions"), dict) else {}
    extensions = {_normalize_ext(k) for k in extensions_raw if k}
    entry_names = _entry_basenames(summary.get("entry_candidates") if isinstance(summary.get("entry_candidates"), list) else [])
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    file_count = int(counts.get("files") or 0)
    label = str(summary.get("label") or summary.get("source_id") or "").strip().lower()

    ext_categories: set[str] = set()
    if extensions & UI_EXTENSIONS:
        ext_categories.add("ui")
    if extensions & PYTHON_EXTENSIONS:
        ext_categories.add("python")
    if extensions & DATA_EXTENSIONS:
        ext_categories.add("data")
    if extensions & DOC_EXTENSIONS:
        ext_categories.add("docs")

    return {
        "extensions": extensions,
        "entry_names": entry_names,
        "file_count": file_count,
        "label": label,
        "ext_categories": ext_categories,
    }


def _draft_types(draft: dict[str, Any] | None) -> set[str]:
    if not draft:
        return set()
    candidates = draft.get("candidates") if isinstance(draft.get("candidates"), list) else []
    types: set[str] = set()
    for item in candidates:
        if isinstance(item, dict) and item.get("type"):
            types.add(str(item["type"]).upper())
    return types


def _suggestion_keywords(suggestion: dict[str, Any]) -> str:
    parts = [
        str(suggestion.get("name") or ""),
        str(suggestion.get("type") or ""),
        str(suggestion.get("role") or ""),
    ]
    luna = suggestion.get("luna") if isinstance(suggestion.get("luna"), dict) else {}
    parts.extend(
        [
            str(luna.get("kind") or ""),
            str(luna.get("title") or ""),
        ]
    )
    tags = suggestion.get("tags") if isinstance(suggestion.get("tags"), list) else []
    parts.extend(str(t) for t in tags)
    return " ".join(parts).lower()


def _looks_like_ui(text: str, suggested_type: str) -> bool:
    if suggested_type in {"UI", "STYLE"}:
        return True
    return any(k in text for k in ("ui", "html", "css", "frontend", "layout", "page", "shell", "form"))


def _looks_like_python(text: str, suggested_type: str) -> bool:
    if suggested_type == "LOGIC" and "python" in text:
        return True
    return any(k in text for k in ("python", "main.py", "app.py", "cli", "backend", "api"))


def _looks_like_config(text: str) -> bool:
    return any(k in text for k in ("config", "package.json", "manifest", "pyproject", "requirements", "tsconfig"))


def _looks_like_docs(text: str, suggested_type: str) -> bool:
    if suggested_type == "TEXT":
        return True
    return any(k in text for k in ("readme", "doc", "markdown", "copy", "lesson", "qa_lesson"))


def _looks_like_data(text: str) -> bool:
    return any(k in text for k in ("json", "yaml", "schema", "csv", "data"))


def _verify_one(
    suggestion: dict[str, Any],
    profile: dict[str, Any],
    draft_types: set[str],
) -> dict[str, Any]:
    suggested_type = str(suggestion.get("type") or "Logic").upper()
    text = _suggestion_keywords(suggestion)
    extensions: set[str] = profile["extensions"]
    entry_names: set[str] = profile["entry_names"]
    label: str = profile["label"]
    ext_categories: set[str] = profile["ext_categories"]
    file_count: int = profile["file_count"]

    score = 0.25
    matched: list[str] = []
    missing: list[str] = []

    luna = suggestion.get("luna") if isinstance(suggestion.get("luna"), dict) else {}
    luna_score = luna.get("score")
    if luna_score is not None:
        try:
            score += min(0.15, float(luna_score) * 0.15)
            matched.append("luna_score:present")
        except (TypeError, ValueError):
            missing.append("luna_score:invalid")

    if label and label in text:
        score += 0.08
        matched.append(f"label:{label}")

    if suggested_type in draft_types:
        score += 0.12
        matched.append(f"draft_type:{suggested_type}")

    if _looks_like_ui(text, suggested_type):
        ui_hits = extensions & UI_EXTENSIONS
        if ui_hits:
            score += 0.18 + min(0.12, 0.03 * len(ui_hits))
            for ext in sorted(ui_hits):
                matched.append(f"extension:{ext}")
        else:
            score -= 0.12
            missing.append("extension:ui_stack")
        if "index.html" in entry_names:
            score += 0.08
            matched.append("entry:index.html")

    if _looks_like_python(text, suggested_type):
        if extensions & PYTHON_EXTENSIONS:
            score += 0.16
            matched.append("extension:.py")
        else:
            score -= 0.1
            missing.append("extension:.py")
        py_entries = entry_names & PYTHON_ENTRIES
        if py_entries:
            score += 0.1
            for name in sorted(py_entries):
                matched.append(f"entry:{name}")
        elif "python" in text or "app" in text:
            missing.append("entry:python_app")

    if _looks_like_config(text):
        cfg_entries = entry_names & CONFIG_ENTRIES
        if cfg_entries:
            score += 0.14
            for name in sorted(cfg_entries):
                matched.append(f"entry:{name}")
        else:
            score -= 0.08
            missing.append("entry:config_manifest")

    if _looks_like_docs(text, suggested_type):
        if extensions & DOC_EXTENSIONS:
            score += 0.12
            matched.append("extension:.md")
        if "readme.md" in entry_names:
            score += 0.08
            matched.append("entry:README.md")
        if not (extensions & DOC_EXTENSIONS) and "readme" in text:
            missing.append("extension:.md")

    if _looks_like_data(text):
        data_hits = extensions & DATA_EXTENSIONS
        if data_hits:
            score += 0.12
            for ext in sorted(data_hits):
                matched.append(f"extension:{ext}")
        elif "data" in text or "json" in text:
            missing.append("extension:data_schema")

    if len(ext_categories) >= 2 and len(entry_names) >= 2:
        score += 0.1
        matched.append("project:mixed_structure")
    elif len(ext_categories) >= 3:
        score += 0.08
        matched.append("project:multi_category")

    if file_count >= 20 and len(ext_categories) >= 2:
        score += 0.05
        matched.append("complexity:reasonable")
    elif file_count > 0 and file_count < 3 and len(ext_categories) >= 2:
        score -= 0.05
        missing.append("complexity:sparse_for_mixed")

    score = max(0.0, min(1.0, score))
    verification_status = _status_from_score(score)

    return {
        "id": suggestion.get("id"),
        "name": suggestion.get("name"),
        "origin": suggestion.get("origin") or suggestion.get("source") or "luna_reuse_pack",
        "suggested_type": suggested_type,
        "verification_status": verification_status,
        "verification_score": round(score, 4),
        "evidence_matched": matched,
        "evidence_missing": missing,
        "risk": "suggestion_only_metadata_verified",
        "warehouse_action": "none",
    }


def verify_suggestions(
    source_id: str,
    summary: dict[str, Any],
    reuse_record: dict[str, Any],
    draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify Luna suggestions against scan summary metadata only."""
    suggestions = reuse_record.get("mapped_capsuleSuggestions")
    if not isinstance(suggestions, list):
        suggestions = []

    profile = _summary_profile(summary)
    draft_types = _draft_types(draft)
    results = [_verify_one(item, profile, draft_types) for item in suggestions if isinstance(item, dict)]

    summary_counts = {"verified": 0, "watch": 0, "rejected": 0, "total": len(results)}
    for item in results:
        status = item.get("verification_status")
        if status in summary_counts:
            summary_counts[status] += 1

    draft_path = draft_rel_path(source_id) if draft else None
    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "source_id": source_id,
        "verified_at": _utc_now_iso(),
        "mode": "metadata_only_verification",
        "inputs": {
            "summary_path": summary_rel_path(source_id),
            "reuse_suggestions_path": f"reuse_suggestions/{source_id}.luna_reuse_pack.json",
            "draft_path": draft_path,
        },
        "limits": {
            "no_source_content_read": True,
            "no_llm": True,
            "no_warehouse_promotion": True,
        },
        "results": results,
        "summary": summary_counts,
    }


def verify_and_save(
    source_id: str,
    summary: dict[str, Any],
    reuse_record: dict[str, Any],
    draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = verify_suggestions(source_id, summary, reuse_record, draft)
    save_verification(source_id, record)
    return record
