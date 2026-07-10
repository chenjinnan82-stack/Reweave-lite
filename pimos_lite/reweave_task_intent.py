"""Task intent helpers for Reweave preview packs."""

from __future__ import annotations

import re
from typing import Any

MAX_TASK_LEN = 240

CAPABILITY_KEYWORDS = {
    "form": ("form", "quote", "input", "submit", "customer", "field"),
    "table": ("table", "list", "queue", "record", "calendar", "row"),
    "copy": ("copy", "landing", "content", "message", "hero", "story"),
    "style": ("style", "css", "brand", "visual", "layout", "design"),
    "logic": ("logic", "workflow", "action", "filter", "calculate", "triage", "interaction"),
    "data": ("data", "dashboard", "metric", "status", "chart", "viewer", "panel"),
}
STOP_WORDS = {"a", "an", "and", "as", "build", "from", "for", "into", "old", "project", "the", "this", "to", "with"}


def capsule_match_text(cap: dict[str, Any]) -> str:
    parts = [
        cap.get("id"),
        cap.get("name"),
        cap.get("type"),
        cap.get("role"),
        " ".join(str(tag) for tag in (cap.get("tags") or []) if tag),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def task_terms(task: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", task.lower()) if len(word) > 2 and word not in STOP_WORDS}


def task_capabilities(task: str) -> list[str]:
    text = task.lower()
    return [
        name
        for name, words in CAPABILITY_KEYWORDS.items()
        if any(word in text for word in words)
    ] or ["copy", "style"]


def score_capsule_for_task(task: str, cap: dict[str, Any], *, enrichable: bool = False) -> int:
    # ponytail: metadata scoring; add embeddings only after real tasks beat this.
    text = capsule_match_text(cap)
    score = 2 if enrichable else 0
    score += sum(3 for term in task_terms(task) if term in text)
    for capability in task_capabilities(task):
        words = CAPABILITY_KEYWORDS[capability]
        if capability in text:
            score += 6
        score += sum(2 for word in words if word in text)
    return score


def capsule_reason(cap: dict[str, Any], capabilities: list[str]) -> str:
    text = capsule_match_text(cap)
    matched = [capability for capability in capabilities if capability in text]
    if matched:
        return "matches " + ", ".join(matched[:3]) + " need"
    return str(cap.get("role") or "selected for source-backed task context")


def build_task_intent(task: str, capsules: list[dict[str, Any]]) -> dict[str, Any]:
    # ponytail: keyword intent is enough for v0; replace with parser only when real tasks beat it.
    task_text = (task or "").lower()
    text = " ".join(
        [task or ""]
        + [capsule_match_text(cap) for cap in capsules if isinstance(cap, dict)]
    ).lower()
    capabilities = [
        name
        for name, words in CAPABILITY_KEYWORDS.items()
        if any(word in text for word in words)
    ] or ["copy", "style"]
    if any(word in task_text for word in ("component", "react", "tsx", "widget")):
        output_type = "component"
    elif any(word in task_text for word in ("doc", "document", "report", "readme")):
        output_type = "document"
    elif any(word in task_text for word in ("dashboard", "panel", "viewer", "table", "calendar", "data")):
        output_type = "data_panel"
    elif any(word in task_text for word in ("tool", "form", "quote", "interaction")):
        output_type = "tool"
    else:
        output_type = "page"
    return {
        "schema_version": "reweave_task_intent.v1",
        "task": (task or "Build a small project pack")[:MAX_TASK_LEN],
        "goal": (task or "Build a small project pack")[:MAX_TASK_LEN],
        "output_type": output_type,
        "needed_files": ["index.html", "styles.css", "app.js"],
        "capabilities": capabilities,
        "retrieved_capsules": [
            {
                "id": cap.get("id"),
                "name": cap.get("name"),
                "source_id": cap.get("source_id"),
                "reason": capsule_reason(cap, capabilities),
            }
            for cap in capsules
            if isinstance(cap, dict)
        ],
        "source_project_write": False,
    }


def build_task_profile(
    task: str,
    capsules: list[dict[str, Any]] | None = None,
    *,
    task_intent: dict[str, Any] | None = None,
) -> dict[str, object]:
    intent = task_intent or build_task_intent(task, capsules or [])
    output_type = str(intent["output_type"])
    capabilities = [str(item) for item in intent["capabilities"]]
    return {
        "id": "task_driven",
        "label": "Task Intent",
        "output_label": output_type.replace("_", " ").title(),
        "action": "Review output",
        "summary": "A runnable small project pack assembled from the task, selected capsules, and source excerpts.",
        "steps": [
            "Check task goal",
            "Review " + ", ".join(capabilities[:3]) + " output",
            "Try the main action",
            "Check page copy and layout",
            "Confirm original project stays unchanged",
        ],
        "output_kinds": (f"{output_type}_html", "task_style", "task_runtime"),
    }
