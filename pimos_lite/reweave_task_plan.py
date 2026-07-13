"""Task plan helpers for Reweave preview packs."""

from __future__ import annotations

from typing import Any


def build_task_plan(task_intent: dict[str, Any]) -> dict[str, Any]:
    output_type = str(task_intent.get("output_type") or "page")
    plan = {
        "schema_version": "reweave_task_plan.v1",
        "task": task_intent.get("task"),
        "output_type": output_type,
        "source_project_write": False,
        "composer": {
            "mode": "task_plan_and_snippets",
            "inputs": ["task_intent.json", "task_plan.json", "capsules_used.json"],
            "optional_inputs": ["snippets_used.json"],
        },
        "outputs": [
            {
                "path": "index.html",
                "purpose": f"render the {output_type} for local review",
                "capsule_ids": [],
            },
            {
                "path": "styles.css",
                "purpose": "carry source-backed visual structure and spacing",
                "capsule_ids": [],
            },
            {
                "path": "app.js",
                "purpose": "add only local preview interaction and review checks",
                "capsule_ids": [],
            },
        ],
        "capsules": list(task_intent.get("retrieved_capsules") or []),
        "acceptance": [
            "open index.html locally",
            "confirm index.html, styles.css, and app.js exist",
            "check capsules_used.json",
            "check provenance.json",
            "confirm source writes stay 0",
        ],
    }
    project_context = task_intent.get("project_context")
    if isinstance(project_context, dict):
        plan["project_graph_path"] = "project_graph.json"
        plan["project_targets"] = list(project_context.get("candidate_files") or [])
        plan["composer"]["optional_inputs"].append("project_graph.json")
        plan["acceptance"].append("review React/Vite project targets without writing source files")
    return plan
