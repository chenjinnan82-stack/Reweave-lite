"""Quality gate helpers for Reweave preview packs."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from pimos_lite.reweave_task_intent import MAX_TASK_LEN


def build_quality_gate(root: Path, task: str, task_plan: dict[str, Any], *, content_aware: bool) -> dict[str, Any]:
    html_text = (root / "index.html").read_text(encoding="utf-8") if (root / "index.html").is_file() else ""
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
            "name": "capsule_reason_visible_in_html",
            "passed": bool(reasons) and any(html.escape(reason) in html_text for reason in reasons),
        },
        {
            "name": "source_cues_visible_in_html",
            "passed": (not content_aware)
            or ("Source excerpts used" in html_text)
            or ("Source-backed cues" in html_text and "capsule metadata only" not in html_text),
        },
    ]
    return {
        "schema_version": "reweave_quality_gate.v1",
        "status": "passed" if all(check["passed"] for check in checks) else "failed",
        "checks": checks,
        "source_project_write": False,
    }
