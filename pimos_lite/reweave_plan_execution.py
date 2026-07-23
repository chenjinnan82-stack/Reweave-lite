"""Deterministic confirmed-plan to module_native execution contract."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


PLAN_EXECUTION_VERSION = "plan_execution.v1"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_PLAN_ID = re.compile(r"plan_[0-9a-f]{32}\Z")
_SECTION_IDS = ("frontend", "backend", "data", "infrastructure")


class PlanExecutionError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise PlanExecutionError("plan_execution_json_invalid") from exc


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _exact(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise PlanExecutionError(code)
    return value


def _topological_order(items: dict[str, dict[str, Any]]) -> list[str]:
    incoming = {item_id: set(item["depends_on"]) for item_id, item in items.items()}
    ready = sorted(item_id for item_id, deps in incoming.items() if not deps)
    visited: list[str] = []
    while ready:
        current = ready.pop(0)
        visited.append(current)
        for item_id in sorted(incoming):
            if current not in incoming[item_id]:
                continue
            incoming[item_id].remove(current)
            if not incoming[item_id] and item_id not in visited and item_id not in ready:
                ready.append(item_id)
        ready.sort()
    if len(visited) != len(items):
        raise PlanExecutionError("plan_execution_dependency_cycle")
    return visited


def compile_plan_execution(
    plan: dict[str, Any],
    confirmation: dict[str, Any],
    capsules: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compile one fully capsule-backed confirmed plan into one composer request."""

    plan_keys = {
        "schema_version", "plan_id", "plan_version", "parent_plan_digest",
        "product_name", "goal", "goal_digest", "language", "requirements",
        "planning_answers", "sections", "model", "planning_rules_version",
        "prompt_version", "structured_response_digests", "warehouse_revision",
        "candidate_generated", "product_generated", "canonical_digest",
    }
    plan = _exact(plan, plan_keys, "plan_execution_plan_invalid")
    canonical_plan = {key: value for key, value in plan.items() if key != "canonical_digest"}
    if (
        plan["schema_version"] != "product_plan.v1"
        or _PLAN_ID.fullmatch(str(plan["plan_id"])) is None
        or type(plan["plan_version"]) is not int
        or plan["plan_version"] < 1
        or (
            plan["parent_plan_digest"] is not None
            and _DIGEST.fullmatch(str(plan["parent_plan_digest"])) is None
        )
        or type(plan["product_name"]) is not str
        or not plan["product_name"]
        or type(plan["goal"]) is not str
        or not plan["goal"]
        or plan["goal_digest"] != canonical_digest(plan["goal"])
        or plan["language"] not in {"zh", "en"}
        or type(plan["planning_answers"]) is not list
        or type(plan["model"]) is not dict
        or set(plan["model"])
        != {"name", "digest", "parameter_count", "parameter_size"}
        or type(plan["model"]["name"]) is not str
        or not plan["model"]["name"]
        or _DIGEST.fullmatch(str(plan["model"]["digest"])) is None
        or type(plan["model"]["parameter_count"]) is not int
        or not 0 < plan["model"]["parameter_count"] <= 15_000_000_000
        or (
            plan["model"]["parameter_size"] is not None
            and type(plan["model"]["parameter_size"]) is not str
        )
        or type(plan["planning_rules_version"]) is not str
        or not plan["planning_rules_version"]
        or type(plan["prompt_version"]) is not str
        or not plan["prompt_version"]
        or type(plan["structured_response_digests"]) is not list
        or any(
            _DIGEST.fullmatch(str(item)) is None
            for item in plan["structured_response_digests"]
        )
        or type(plan["warehouse_revision"]) is not int
        or plan["warehouse_revision"] < 0
        or plan["candidate_generated"] is not False
        or plan["product_generated"] is not False
        or plan["canonical_digest"] != canonical_digest(canonical_plan)
    ):
        raise PlanExecutionError("plan_execution_plan_invalid")

    confirmation_keys = {
        "schema_version", "plan_id", "plan_version", "plan_digest",
        "confirmed_at", "capsule_revalidation", "warehouse_revision",
        "product_generated", "candidate_generated", "product_usage_written",
        "receipt_digest",
    }
    confirmation = _exact(
        confirmation,
        confirmation_keys,
        "plan_execution_confirmation_invalid",
    )
    confirmation_body = {
        key: value for key, value in confirmation.items() if key != "receipt_digest"
    }
    if (
        confirmation["schema_version"] != "product_plan_confirmation.v1"
        or confirmation["plan_id"] != plan["plan_id"]
        or confirmation["plan_version"] != plan["plan_version"]
        or confirmation["plan_digest"] != plan["canonical_digest"]
        or type(confirmation["confirmed_at"]) is not str
        or type(confirmation["warehouse_revision"]) is not int
        or confirmation["warehouse_revision"] < 0
        or confirmation["product_generated"] is not False
        or confirmation["candidate_generated"] is not False
        or confirmation["product_usage_written"] is not False
        or confirmation["receipt_digest"] != canonical_digest(confirmation_body)
    ):
        raise PlanExecutionError("plan_execution_confirmation_invalid")

    requirements = plan["requirements"]
    if type(requirements) is not list or not requirements:
        raise PlanExecutionError("plan_execution_requirement_invalid")
    requirement_ids: set[str] = set()
    answers_digest = canonical_digest(plan["planning_answers"])
    for requirement in requirements:
        row = _exact(
            requirement,
            {"requirement_id", "statement", "source", "source_digest"},
            "plan_execution_requirement_invalid",
        )
        requirement_id = row["requirement_id"]
        if (
            type(requirement_id) is not str
            or not requirement_id.startswith("requirement_")
            or requirement_id in requirement_ids
            or type(row["statement"]) is not str
            or not row["statement"]
            or row["source"] not in {"product_goal", "planning_answer"}
            or _DIGEST.fullmatch(str(row["source_digest"])) is None
            or (
                row["source"] == "product_goal"
                and row["source_digest"] != plan["goal_digest"]
            )
            or (
                row["source"] == "planning_answer"
                and row["source_digest"] != answers_digest
            )
        ):
            raise PlanExecutionError("plan_execution_requirement_invalid")
        requirement_ids.add(requirement_id)

    if type(capsules) is not list:
        raise PlanExecutionError("plan_execution_capsule_invalid")
    capsule_map: dict[tuple[str, str], dict[str, Any]] = {}
    for capsule in capsules:
        if type(capsule) is not dict:
            raise PlanExecutionError("plan_execution_capsule_invalid")
        capsule_id = capsule.get("capsule_id")
        version_id = capsule.get("version_id")
        if (
            type(capsule_id) is not str
            or not capsule_id
            or type(version_id) is not str
            or not version_id
            or _DIGEST.fullmatch(str(capsule.get("canonical_hash"))) is None
            or type(capsule.get("capability_key")) is not str
            or not capsule["capability_key"]
            or capsule.get("capability_kind")
            not in {"presentation", "interaction", "computation"}
        ):
            raise PlanExecutionError("plan_execution_capsule_invalid")
        key = (capsule_id, version_id)
        if key in capsule_map:
            raise PlanExecutionError("plan_execution_capsule_invalid")
        capsule_map[key] = capsule

    sections = plan["sections"]
    if (
        type(sections) is not list
        or any(type(section) is not dict for section in sections)
        or [section.get("section_id") for section in sections] != list(_SECTION_IDS)
    ):
        raise PlanExecutionError("plan_execution_section_invalid")
    work_items: dict[str, dict[str, Any]] = {}
    work_sections: dict[str, str] = {}
    bindings_by_work: dict[str, list[dict[str, Any]]] = {}
    covered: set[str] = set()
    plan_binding_pairs: list[tuple[str, str]] = []
    for section in sections:
        row = _exact(
            section,
            {"section_id", "summary", "work_items", "gaps"},
            "plan_execution_section_invalid",
        )
        if (
            type(row["summary"]) is not str
            or not row["summary"]
            or row["gaps"] != []
            or type(row["work_items"]) is not list
            or not row["work_items"]
        ):
            raise PlanExecutionError("plan_execution_gap_present")
        for item in row["work_items"]:
            work = _exact(
                item,
                {
                    "work_item_id", "title", "description", "requirement_ids",
                    "depends_on", "acceptance_intent", "capsule_bindings",
                    "gap_reason",
                },
                "plan_execution_work_item_invalid",
            )
            work_id = work["work_item_id"]
            if (
                type(work_id) is not str
                or not work_id.startswith("work_item_")
                or work_id in work_items
                or type(work["requirement_ids"]) is not list
                or not work["requirement_ids"]
                or any(type(value) is not str for value in work["requirement_ids"])
                or len(set(work["requirement_ids"])) != len(work["requirement_ids"])
                or set(work["requirement_ids"]) - requirement_ids
                or type(work["depends_on"]) is not list
                or any(type(value) is not str for value in work["depends_on"])
                or len(set(work["depends_on"])) != len(work["depends_on"])
                or type(work["capsule_bindings"]) is not list
                or not work["capsule_bindings"]
                or work["gap_reason"] is not None
                or any(
                    type(work[field]) is not str or not work[field]
                    for field in ("title", "description", "acceptance_intent")
                )
            ):
                raise PlanExecutionError("plan_execution_work_item_invalid")
            exact_bindings: list[dict[str, Any]] = []
            for binding in work["capsule_bindings"]:
                exact = _exact(
                    binding,
                    {
                        "capsule_id", "version_id", "display_name", "capability_kind",
                        "canonical_hash", "identity_status", "selection_status",
                        "review_status", "reason",
                    },
                    "plan_execution_binding_invalid",
                )
                if (
                    type(exact["capsule_id"]) is not str
                    or not exact["capsule_id"]
                    or type(exact["version_id"]) is not str
                    or not exact["version_id"]
                ):
                    raise PlanExecutionError("plan_execution_binding_invalid")
                pair = (exact["capsule_id"], exact["version_id"])
                capsule = capsule_map.get(pair)
                if (
                    exact["identity_status"] != "formal_exact_version"
                    or exact["selection_status"] != "model_suggested"
                    or exact["review_status"] not in {"pending", "user_confirmed"}
                    or capsule is None
                    or exact["canonical_hash"] != capsule["canonical_hash"]
                    or exact["capability_kind"] != capsule["capability_kind"]
                ):
                    raise PlanExecutionError("plan_execution_binding_stale")
                exact_bindings.append(capsule)
                plan_binding_pairs.append(pair)
            work_items[work_id] = work
            work_sections[work_id] = row["section_id"]
            bindings_by_work[work_id] = exact_bindings
            covered.update(work["requirement_ids"])

    if covered != requirement_ids:
        raise PlanExecutionError("plan_execution_requirement_uncovered")
    for work_id, item in work_items.items():
        if work_id in item["depends_on"] or any(
            dependency not in work_items for dependency in item["depends_on"]
        ):
            raise PlanExecutionError("plan_execution_dependency_invalid")
    work_order = _topological_order(work_items)

    revalidation = confirmation["capsule_revalidation"]
    if type(revalidation) is not list:
        raise PlanExecutionError("plan_execution_confirmation_invalid")
    confirmed_pairs: list[tuple[str, str]] = []
    for binding in revalidation:
        row = _exact(
            binding,
            {"capsule_id", "version_id", "eligibility_status", "review_status"},
            "plan_execution_confirmation_invalid",
        )
        if (
            type(row["capsule_id"]) is not str
            or not row["capsule_id"]
            or type(row["version_id"]) is not str
            or not row["version_id"]
            or row["eligibility_status"] != "active_current_eligible"
            or row["review_status"] != "user_confirmed"
        ):
            raise PlanExecutionError("plan_execution_confirmation_invalid")
        confirmed_pairs.append((row["capsule_id"], row["version_id"]))
    if confirmed_pairs != plan_binding_pairs:
        raise PlanExecutionError("plan_execution_confirmation_invalid")

    selected = sorted(
        {pair: capsule_map[pair] for pair in plan_binding_pairs}.values(),
        key=lambda capsule: (
            capsule["capability_kind"],
            capsule["capsule_id"],
            capsule["version_id"],
        ),
    )
    capability_keys = {capsule["capability_key"] for capsule in selected}
    capability_kinds = [capsule["capability_kind"] for capsule in selected]
    if not 1 <= len(selected) <= 3:
        raise PlanExecutionError("plan_execution_capsule_count_invalid")
    if len(capability_keys) != 1:
        raise PlanExecutionError("plan_execution_capability_group_mismatch")
    if len(capability_kinds) != len(set(capability_kinds)):
        raise PlanExecutionError("plan_execution_capability_kind_duplicate")
    if not ({"presentation", "interaction"} & set(capability_kinds)):
        raise PlanExecutionError("plan_execution_dom_capsule_required")

    unit_ids = {
        work_id: "execution_unit_"
        + canonical_digest(
            {"plan_digest": plan["canonical_digest"], "work_item_id": work_id}
        )[:24]
        for work_id in sorted(work_items)
    }
    units = []
    for sequence, work_id in enumerate(work_order, start=1):
        item = work_items[work_id]
        units.append(
            {
                "execution_unit_id": unit_ids[work_id],
                "sequence": sequence,
                "section_id": work_sections[work_id],
                "work_item_id": work_id,
                "requirement_ids": list(item["requirement_ids"]),
                "depends_on": [unit_ids[dependency] for dependency in item["depends_on"]],
                "kind": "reuse_capsule",
                "capsules": [
                    {
                        "capsule_id": capsule["capsule_id"],
                        "version_id": capsule["version_id"],
                        "canonical_hash": capsule["canonical_hash"],
                        "capability_key": capsule["capability_key"],
                        "capability_kind": capsule["capability_kind"],
                    }
                    for capsule in bindings_by_work[work_id]
                ],
            }
        )
    capsule_identities = [
        {
            "capsule_id": capsule["capsule_id"],
            "version_id": capsule["version_id"],
            "canonical_hash": capsule["canonical_hash"],
            "capability_key": capsule["capability_key"],
            "capability_kind": capsule["capability_kind"],
        }
        for capsule in selected
    ]
    composition_key = canonical_digest(
        {
            "contract": PLAN_EXECUTION_VERSION,
            "plan_digest": plan["canonical_digest"],
            "confirmation_digest": confirmation["receipt_digest"],
            "capsules": capsule_identities,
        }
    )
    execution = {
        "schema_version": PLAN_EXECUTION_VERSION,
        "plan_id": plan["plan_id"],
        "plan_version": plan["plan_version"],
        "plan_digest": plan["canonical_digest"],
        "confirmation_digest": confirmation["receipt_digest"],
        "warehouse_revision": confirmation["warehouse_revision"],
        "execution_units": units,
        "capsules": capsule_identities,
        "composer_request": {
            "task": plan["goal"],
            "product_id": "product_" + composition_key[:32],
            "generated_at": confirmation["confirmed_at"],
            "capsule_ids": [capsule["capsule_id"] for capsule in selected],
        },
    }
    execution["execution_digest"] = canonical_digest(execution)
    return execution


__all__ = [
    "PLAN_EXECUTION_VERSION",
    "PlanExecutionError",
    "canonical_bytes",
    "canonical_digest",
    "compile_plan_execution",
]
