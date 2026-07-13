from __future__ import annotations

import re
from typing import Any


CAPABILITY_REGISTRY_VERSION = "lite_capability_registry.v1"

CAPABILITY_ROWS = (
    {
        "capability_tag": "task_board",
        "module_kind": "task_board",
        "legacy_task_id": "filterable_task_board",
        "keywords": ("task board", "kanban", "board", "任务板", "看板"),
    },
    {
        "capability_tag": "status_panel",
        "module_kind": "status_panel",
        "legacy_task_id": "local_status_panel",
        "keywords": ("status", "health", "queue", "monitor", "状态", "健康", "队列"),
    },
    {
        "capability_tag": "snippet",
        "module_kind": "snippet_card",
        "legacy_task_id": "snippet_organizer",
        "keywords": ("snippet", "code snippet", "code note", "代码片段", "片段"),
    },
    {
        "capability_tag": "todo_list",
        "module_kind": "todo_list",
        "legacy_task_id": "todo_micro_tool",
        "keywords": ("todo", "todo list", "checklist", "待办", "清单"),
    },
    {
        "capability_tag": "multi_step_form",
        "module_kind": "multi_step_form",
        "legacy_task_id": "multi_step_form",
        "keywords": ("form", "wizard", "multi step", "step form", "表单", "多步", "步骤"),
    },
    {
        "capability_tag": "notes_validation",
        "module_kind": "notes_validation",
        "legacy_task_id": "notes_with_validation",
        "keywords": ("note", "notes", "validation", "validate", "rule", "笔记", "校验", "验证", "规则"),
    },
    {
        "capability_tag": "component_preview",
        "module_kind": "component_preview",
        "legacy_task_id": "component_preview_entry",
        "keywords": ("component", "ui component", "组件"),
    },
    {
        "capability_tag": "estimate_form",
        "module_kind": "estimate_form",
        "legacy_task_id": "",
        "keywords": ("estimate form", "order estimate", "budget form", "估算表单", "预算表单"),
    },
    {
        "capability_tag": "calculation",
        "module_kind": "calculation",
        "legacy_task_id": "",
        "keywords": ("calculate", "calculation", "estimate", "budget", "计算", "估算", "预算"),
    },
    {
        "capability_tag": "task_form",
        "module_kind": "task_form",
        "legacy_task_id": "",
        "keywords": ("task form", "add task", "任务表单", "新增任务"),
    },
    {
        "capability_tag": "state_machine",
        "module_kind": "state_machine",
        "legacy_task_id": "",
        "keywords": ("state machine", "stateful", "task count", "状态机", "任务计数"),
    },
)


def build_capability_record(goal: str, *, capability_tags: list[str] | None = None, legacy_task_id: str = "") -> dict[str, Any]:
    tags = _clean_tags(capability_tags)
    if not tags:
        tags = _infer_tags(goal)
    rows = [row for row in CAPABILITY_ROWS if row["capability_tag"] in tags]
    return {
        "capability_registry_version": CAPABILITY_REGISTRY_VERSION,
        "goal": str(goal or "").strip(),
        "capability_tags": tags,
        "module_kinds": [str(row["module_kind"]) for row in rows],
        "legacy_task_id": str(legacy_task_id or _legacy_task_id(tags) or ""),
        "legacy_task_id_role": "seed_shell_compat",
    }


def _infer_tags(goal: str) -> list[str]:
    text = str(goal or "").lower()
    return [str(row["capability_tag"]) for row in CAPABILITY_ROWS if any(_contains(text, word) for word in row["keywords"])]


def _legacy_task_id(tags: list[str]) -> str:
    for tag in tags:
        for row in CAPABILITY_ROWS:
            if row["capability_tag"] == tag:
                return str(row["legacy_task_id"])
    return ""


def _clean_tags(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    allowed = {str(row["capability_tag"]) for row in CAPABILITY_ROWS}
    for value in values or []:
        tag = str(value or "").strip()
        if tag in allowed and tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def _contains(text: str, keyword: str) -> bool:
    token = str(keyword or "").strip().lower()
    if not token:
        return False
    if any(ord(char) > 127 for char in token):
        return token in text
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text) is not None


__all__ = ["CAPABILITY_REGISTRY_VERSION", "CAPABILITY_ROWS", "build_capability_record"]
