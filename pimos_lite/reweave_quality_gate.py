"""Quality gate helpers for Reweave preview packs."""

from __future__ import annotations

import hashlib
import html
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pimos_lite.reweave_task_intent import MAX_TASK_LEN


def js_syntax_ok(js: str) -> bool:
    node = shutil.which("node")
    if not node:
        return bool(js.strip()) and not js.rstrip().endswith((".", ",", "=>"))
    with tempfile.TemporaryDirectory(prefix="reweave-js-check-") as tmp:
        path = Path(tmp) / "app.js"
        path.write_text(js, encoding="utf-8")
        return subprocess.run([node, "--check", str(path)], capture_output=True, text=True).returncode == 0


def build_quality_gate(
    root: Path,
    task: str,
    task_plan: dict[str, Any],
    *,
    content_aware: bool,
    behavior_contract: dict[str, Any] | None = None,
    behavior_adaptation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    html_text = (root / "index.html").read_text(encoding="utf-8") if (root / "index.html").is_file() else ""
    review_text = (root / "review.html").read_text(encoding="utf-8") if (root / "review.html").is_file() else ""
    app_text = (root / "app.js").read_text(encoding="utf-8") if (root / "app.js").is_file() else ""
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
            "name": "javascript_syntax_valid",
            "passed": js_syntax_ok(app_text),
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
    if behavior_contract is not None:
        interactions = behavior_contract.get("interactions") if isinstance(behavior_contract.get("interactions"), dict) else {}
        events = interactions.get("events") if isinstance(interactions.get("events"), list) else []
        passive_updates = interactions.get("passive_updates") if isinstance(interactions.get("passive_updates"), list) else []
        protected = behavior_adaptation.get("protected") if isinstance(behavior_adaptation, dict) and isinstance(behavior_adaptation.get("protected"), dict) else {}
        expected_ids = [str(item) for item in protected.get("dom_ids", []) if item]
        expected_selectors = [str(item) for item in protected.get("selectors", []) if item]
        source_script = behavior_contract.get("files", {}).get("script", {}) if isinstance(behavior_contract.get("files"), dict) else {}
        expected_script_sha = str(source_script.get("sha256") or "") if isinstance(source_script, dict) else ""
        actual_script_sha = hashlib.sha256((root / "app.js").read_bytes()).hexdigest()
        task_heading = str(behavior_adaptation.get("task_heading") or "") if isinstance(behavior_adaptation, dict) else ""
        adaptation_targets = {
            str(item.get("target") or "")
            for item in behavior_adaptation.get("patches", [])
            if isinstance(behavior_adaptation, dict) and isinstance(item, dict)
        }
        heading_required = bool(adaptation_targets & {"document_title", "primary_heading"})
        checks.extend(
            [
                {
                    "name": "behavior_contract_materialized",
                    "passed": (root / "behavior_contract.json").is_file()
                    and 'data-reweave-behavior="closed"' in html_text,
                },
                {
                    "name": "behavior_adaptation_materialized",
                    "passed": (root / "behavior_adaptation.json").is_file()
                    and 'data-reweave-adaptation="safe-text"' in html_text
                    and bool(task_heading)
                    and (not heading_required or html.escape(task_heading) in html_text),
                },
                {
                    "name": "behavior_dom_contract_preserved",
                    "passed": bool(expected_ids or expected_selectors)
                    and all(
                        re.search(rf'\bid\s*=\s*["\']{re.escape(item)}["\']', html_text)
                        for item in expected_ids
                    )
                    and all(selector.lstrip("#.") in html_text for selector in expected_selectors),
                },
                {
                    "name": "behavior_script_preserved",
                    "passed": bool(expected_script_sha) and actual_script_sha == expected_script_sha,
                },
                {
                    "name": "behavior_event_bindings_preserved",
                    "passed": (
                        bool(events)
                        and all(
                            (
                                str(item.get("target_id") or "") in html_text
                                or str(item.get("target_selector") or "").lstrip("#.") in html_text
                            )
                            and str(item.get("event") or "") in app_text
                            for item in events
                            if isinstance(item, dict)
                        )
                    )
                    or (
                        bool(passive_updates)
                        and all(str(item.get("api") or "") in app_text for item in passive_updates if isinstance(item, dict))
                    ),
                },
            ]
        )
    return {
        "schema_version": "reweave_quality_gate.v1",
        "status": "passed" if all(check["passed"] for check in checks) else "failed",
        "checks": checks,
        "source_project_write": False,
        "behavior_reuse": {
            "status": "static_verified" if behavior_contract is not None else "not_selected",
            "runtime_validation": "required" if behavior_contract is not None else "not_required",
            "interaction_mode": behavior_contract.get("interaction_mode") if behavior_contract is not None else "none",
        },
    }
