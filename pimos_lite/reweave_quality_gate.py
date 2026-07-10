"""Quality gate helpers for Reweave preview packs."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from pimos_lite.reweave_task_intent import MAX_TASK_LEN


def build_quality_gate(root: Path, task: str, task_plan: dict[str, Any], *, content_aware: bool) -> dict[str, Any]:
    html_text = (root / "index.html").read_text(encoding="utf-8") if (root / "index.html").is_file() else ""
    review_text = (root / "review.html").read_text(encoding="utf-8") if (root / "review.html").is_file() else ""
    planned = [
        str(item.get("path"))
        for item in task_plan.get("outputs", [])
        if isinstance(item, dict) and item.get("path")
    ]
    reasons = [
        str(item.get("reason"))
        for item in task_plan.get("capsules", [])
        if isinstance(item, dict) and item.get("reason")
    ]
    internal_terms = (
        "Task Intent",
        "Plan files",
        "Source excerpts used",
        "Reused signals",
        "Source-backed cues",
        "Source Boxes",
        "capsule metadata only",
    )
    source_code_terms = ("document.", "window.", "querySelector", "getElementById", "addEventListener")
    checks = [
        {
            "name": "planned_outputs_exist",
            "passed": all((root / path).is_file() for path in planned),
        },
        {
            "name": "planned_outputs_match_core_files",
            "passed": set(planned) == {"index.html", "styles.css", "app.js"},
        },
        {
            "name": "task_visible_in_html",
            "passed": html.escape((task or "")[:MAX_TASK_LEN]) in html_text,
        },
        {
            "name": "index_page_hides_internal_review_terms",
            "passed": all(term not in html_text for term in internal_terms),
        },
        {
            "name": "index_page_hides_source_code_fragments",
            "passed": all(term not in html_text for term in source_code_terms),
        },
        {
            "name": "review_artifact_exists",
            "passed": (root / "review.html").is_file(),
        },
        {
            "name": "capsule_reason_visible_in_review",
            "passed": bool(reasons) and any(html.escape(reason) in review_text for reason in reasons),
        },
        {
            "name": "source_cues_visible_in_review",
            "passed": (not content_aware)
            or ("Source excerpts used" in review_text)
            or ("Source-backed cues" in review_text and "capsule metadata only" not in review_text),
        },
    ]
    return {
        "schema_version": "reweave_quality_gate.v1",
        "status": "passed" if all(check["passed"] for check in checks) else "failed",
        "checks": checks,
        "source_project_write": False,
    }
