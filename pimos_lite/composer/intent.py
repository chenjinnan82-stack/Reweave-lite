from __future__ import annotations

from typing import Any

from pimos_lite.capability_registry import build_capability_record


INTENT_RECORD_VERSION = "lite_intent_record.v1"


def build_intent_record(
    *,
    goal: str,
    capability_tags: list[str] | None = None,
    legacy_task_id: str = "",
    max_modules: int = 1,
) -> dict[str, Any]:
    capability = build_capability_record(goal, capability_tags=capability_tags, legacy_task_id=legacy_task_id)
    return {
        "intent_record_version": INTENT_RECORD_VERSION,
        "goal": capability["goal"],
        "capability_tags": capability["capability_tags"],
        "module_kinds": capability["module_kinds"],
        "legacy_task_id": capability["legacy_task_id"],
        "legacy_task_id_role": capability["legacy_task_id_role"],
        "max_modules": int(max_modules),
    }


__all__ = ["INTENT_RECORD_VERSION", "build_intent_record"]
