"""Project-local, redacted, non-formal Reweave experience records."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from typing import Any


NOT_RECORDED = "NOT_RECORDED"
AUTHORITY = "non_formal_derived_experience"
REDACTION_POLICY_VERSION = "reweave_experience_redaction.v1"
DERIVATION_RULE_VERSION = "reweave_experience_derivation.v1"
LABEL_RULE_VERSION = "reweave_experience_task_label_rules.v1"
PROJECT_EXPERIENCE_SCOPE_VERSION = "project_experience_scope.v1"
PROJECT_EXPERIENCE_RECORD_VERSION = "project_experience_record.v1"
PROJECT_EXPERIENCE_QUERY_VERSION = "product_experience_query.v1"
PROJECT_EXPERIENCE_CASE_VERSION = "product_experience_case_projection.v1"
PROJECT_EXPERIENCE_RANKING_VERSION = "reweave_experience_ranking.v1"
PROJECT_EXPERIENCE_MILESTONES = (
    "plan_confirmed",
    "candidate_terminal",
    "export_terminal",
)
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SAFE_ID = re.compile(r"[a-z][a-z0-9_-]{0,95}\Z")
SAFE_VERSION = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}\Z")
SAFE_OFFER_REF = re.compile(r"offer_[0-9a-f]{24}\Z")
WORKSPACE_ID = re.compile(r"workspace_[0-9a-f]{32}\Z")
ABSOLUTE_PATH_FRAGMENT = re.compile(
    r"(?:^|(?<=[^A-Za-z0-9_]))"
    r"(?:file://|~[\\/]|[A-Za-z]:[\\/]|(?:/+|\\+)(?:$|(?=[^/\\\s])))",
    re.IGNORECASE,
)
PLANNING_FIELDS = (
    "goal_safe_projection",
    "frozen_catalog_digest",
    "composition_offer_digest",
    "exact_model_name",
    "exact_model_digest",
    "model_selection",
    "user_decision",
    "plan_digest",
    "execution_digest",
    "connection_digest",
    "candidate_result",
    "delivery_result",
    "correction_count",
    "failure_attribution",
)
VALIDATION_FIELDS = (
    "gap_digest",
    "projection_digest",
    "decision_digest",
    "authorization_digest",
    "source_proposal_digest",
    "intake_result",
    "security_result",
    "runtime_result",
    "supervision_result",
    "admission_result",
    "publication_result",
    "rule_version_identities",
    "candidate_result",
    "export_result",
    "visual_result",
    "failure_attribution",
    "regression_evidence",
)
RATE_METRICS = (
    "legal_offer_coverage_rate",
    "correct_planning_rate",
    "correct_rejection_rate",
    "capability_gap_accuracy",
    "source_proposal_gate_pass_rate",
    "formal_capsule_reuse_rate",
    "strong_model_upgrade_rate",
    "standalone_delivery_success_rate",
)
AVERAGE_METRICS = (
    "average_human_corrections",
    "average_model_calls_per_delivery",
    "recorded_delivery_cost",
)

_LATIN_TOKEN = re.compile(r"[a-z][a-z0-9_]{1,63}")
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_GENERIC_TOKENS = frozenset(
    {
        "all",
        "and",
        "app",
        "application",
        "create",
        "display",
        "final",
        "input",
        "local",
        "only",
        "result",
        "system",
        "the",
        "tool",
        "user",
        "一个",
        "不依",
        "仅展",
        "创建",
        "完成",
        "工具",
        "所有",
        "本地",
        "用户",
        "系统",
        "结果",
        "网络",
        "输入",
        "进行",
    }
)


class ExperienceError(ValueError):
    """Strict experience validation or persistence input failure."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_digest(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExperienceError("duplicate_json_key")
        result[key] = value
    return result


def strict_json_bytes(raw: bytes, *, name: str) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ExperienceError("non_finite_json_number")
            ),
        )
    except ExperienceError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExperienceError(f"invalid_json:{name}") from exc


def build_project_experience_scope(scope_id: str, created_at: str) -> dict[str, Any]:
    body = {
        "schema_version": PROJECT_EXPERIENCE_SCOPE_VERSION,
        "authority": AUTHORITY,
        "scope_id": _safe_id(scope_id, "project_experience_scope_invalid"),
        "created_at": created_at,
    }
    return validate_project_experience_scope(
        {**body, "canonical_digest": canonical_digest(body)}
    )


def validate_project_experience_scope(value: Any) -> dict[str, Any]:
    row = _exact_dict(
        value,
        {"schema_version", "authority", "scope_id", "created_at", "canonical_digest"},
        "project_experience_scope_invalid",
    )
    body = {key: item for key, item in row.items() if key != "canonical_digest"}
    if (
        row["schema_version"] != PROJECT_EXPERIENCE_SCOPE_VERSION
        or row["authority"] != AUTHORITY
        or _safe_id(row["scope_id"], "project_experience_scope_invalid")
        != row["scope_id"]
        or type(row["created_at"]) is not str
        or not row["created_at"]
        or _digest(row["canonical_digest"], "project_experience_scope_invalid")
        != row["canonical_digest"]
        or row["canonical_digest"] != canonical_digest(body)
    ):
        raise ExperienceError("project_experience_scope_invalid")
    return row


def _exact_dict(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ExperienceError(code)
    return value


def _digest(value: Any, code: str) -> str:
    if type(value) is not str or SHA256.fullmatch(value) is None:
        raise ExperienceError(code)
    return value


def _safe_id(value: Any, code: str) -> str:
    if type(value) is not str or SAFE_ID.fullmatch(value) is None:
        raise ExperienceError(code)
    return value


def _safe_version(value: Any, code: str) -> str:
    if type(value) is not str or SAFE_VERSION.fullmatch(value) is None:
        raise ExperienceError(code)
    return value


def _enum_or_not(value: Any, allowed: set[str], code: str) -> str:
    if value == NOT_RECORDED:
        return value
    if type(value) is not str or value not in allowed:
        raise ExperienceError(code)
    return value


def _digest_or_not(value: Any, code: str) -> str:
    return value if value == NOT_RECORDED else _digest(value, code)


def _safe_model_name(value: Any) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 200
        or ABSOLUTE_PATH_FRAGMENT.search(value) is not None
    ):
        raise ExperienceError("invalid_model_name")
    return value


def normalize_experience_model_name(value: Any) -> str:
    return _safe_model_name(value)


def _failure_attribution(value: Any) -> Any:
    if value == NOT_RECORDED:
        return value
    row = _exact_dict(
        value,
        {"status", "code", "rule_version", "evidence_digest"},
        "invalid_failure_attribution",
    )
    if row["status"] != "RECORDED":
        raise ExperienceError("invalid_failure_attribution")
    return {
        "status": "RECORDED",
        "code": _safe_id(row["code"], "invalid_failure_attribution"),
        "rule_version": _safe_version(
            row["rule_version"], "invalid_failure_attribution"
        ),
        "evidence_digest": _digest(
            row["evidence_digest"], "invalid_failure_attribution"
        ),
    }


def _model_selection(value: Any) -> Any:
    if value == NOT_RECORDED:
        return value
    if type(value) is str:
        if SAFE_OFFER_REF.fullmatch(value) is None:
            raise ExperienceError("invalid_model_selection")
        return value
    row = _exact_dict(
        value,
        {"status", "offer_ref"},
        "invalid_model_selection",
    )
    status = _enum_or_not(
        row["status"],
        {"selected", "no_match", "rejected", "invalid_output"},
        "invalid_model_selection",
    )
    offer_ref = row["offer_ref"]
    if status == "selected":
        if type(offer_ref) is not str or SAFE_OFFER_REF.fullmatch(offer_ref) is None:
            raise ExperienceError("invalid_model_selection")
    elif offer_ref != NOT_RECORDED:
        raise ExperienceError("invalid_model_selection")
    return {"status": status, "offer_ref": offer_ref}


def _rule_identities(value: Any) -> Any:
    if value == NOT_RECORDED:
        return value
    if type(value) is not list or not value:
        raise ExperienceError("invalid_rule_version_identities")
    rows = []
    for raw in value:
        row = _exact_dict(
            raw,
            {"name", "version", "digest"},
            "invalid_rule_version_identities",
        )
        rows.append(
            {
                "name": _safe_id(row["name"], "invalid_rule_version_identities"),
                "version": _safe_version(
                    row["version"], "invalid_rule_version_identities"
                ),
                "digest": _digest(
                    row["digest"], "invalid_rule_version_identities"
                ),
            }
        )
    rows.sort(key=lambda item: (item["name"], item["version"], item["digest"]))
    if len({canonical_bytes(row) for row in rows}) != len(rows):
        raise ExperienceError("invalid_rule_version_identities")
    return rows


def _regression_evidence(value: Any) -> Any:
    if value == NOT_RECORDED:
        return value
    if type(value) is not list or not value:
        raise ExperienceError("invalid_regression_evidence")
    rows = []
    for raw in value:
        row = _exact_dict(
            raw,
            {"evidence_digest", "rule_version"},
            "invalid_regression_evidence",
        )
        rows.append(
            {
                "evidence_digest": _digest(
                    row["evidence_digest"], "invalid_regression_evidence"
                ),
                "rule_version": _safe_version(
                    row["rule_version"], "invalid_regression_evidence"
                ),
            }
        )
    rows.sort(key=lambda item: (item["rule_version"], item["evidence_digest"]))
    if len({canonical_bytes(row) for row in rows}) != len(rows):
        raise ExperienceError("invalid_regression_evidence")
    return rows


def _planning_value(field: str, value: Any) -> Any:
    if field == "goal_safe_projection":
        if value == NOT_RECORDED:
            return value
        row = _exact_dict(
            value,
            {"canonical_value_sha256"},
            "invalid_goal_safe_projection",
        )
        return {
            "canonical_value_sha256": _digest(
                row["canonical_value_sha256"],
                "invalid_goal_safe_projection",
            )
        }
    if field in {
        "frozen_catalog_digest",
        "composition_offer_digest",
        "exact_model_digest",
        "plan_digest",
        "execution_digest",
        "connection_digest",
    }:
        return _digest_or_not(value, f"invalid_{field}")
    if field == "exact_model_name":
        return value if value == NOT_RECORDED else _safe_model_name(value)
    if field == "model_selection":
        return _model_selection(value)
    if field == "user_decision":
        return _enum_or_not(
            value,
            {"confirmed", "rejected", "deferred", "corrected"},
            "invalid_user_decision",
        )
    if field == "candidate_result":
        return _enum_or_not(
            value,
            {"review_ready", "rejected", "failed", "not_generated"},
            "invalid_candidate_result",
        )
    if field == "delivery_result":
        return _enum_or_not(
            value,
            {"passed", "failed", "not_attempted"},
            "invalid_delivery_result",
        )
    if field == "correction_count":
        if value == NOT_RECORDED:
            return value
        if type(value) is not int or value < 0:
            raise ExperienceError("invalid_correction_count")
        return value
    if field == "failure_attribution":
        return _failure_attribution(value)
    raise ExperienceError("unknown_record_field")


def _validation_value(field: str, value: Any) -> Any:
    if field in {
        "gap_digest",
        "projection_digest",
        "decision_digest",
        "authorization_digest",
        "source_proposal_digest",
    }:
        return _digest_or_not(value, f"invalid_{field}")
    enums = {
        "intake_result": {"passed", "failed", "rejected", "not_run"},
        "security_result": {"passed", "failed", "rejected", "not_run"},
        "runtime_result": {"passed", "failed", "not_run"},
        "supervision_result": {"approve", "reject", "failed", "not_run"},
        "admission_result": {"review_required", "failed", "not_run"},
        "publication_result": {"published", "rejected", "failed", "not_run"},
        "candidate_result": {"review_ready", "rejected", "failed", "not_generated"},
        "export_result": {"passed", "failed", "not_run"},
        "visual_result": {"passed", "failed", "deferred", "not_run"},
    }
    if field in enums:
        return _enum_or_not(value, enums[field], f"invalid_{field}")
    if field == "rule_version_identities":
        return _rule_identities(value)
    if field == "failure_attribution":
        return _failure_attribution(value)
    if field == "regression_evidence":
        return _regression_evidence(value)
    raise ExperienceError("unknown_record_field")


def normalize_planning_experience_value(field: str, value: Any) -> Any:
    return _planning_value(field, value)


def normalize_validation_experience_value(field: str, value: Any) -> Any:
    return _validation_value(field, value)


def validate_experience_record(
    raw: bytes,
    expected_schema: str,
    expected_sha256: str,
) -> dict[str, Any]:
    _digest(expected_sha256, "invalid_experience_file_digest")
    if sha256_bytes(raw) != expected_sha256:
        raise ExperienceError("experience_file_digest_mismatch")
    value = strict_json_bytes(raw, name="experience.json")
    allowed = (
        PLANNING_FIELDS
        if expected_schema == "planning_experience.v1"
        else VALIDATION_FIELDS
    )
    required = {
        "schema",
        "authority",
        "redaction_policy_version",
        "derivation_rule_version",
        "record_id",
        "project_scope_digest",
        *allowed,
        "source_evidence_references",
        "canonical_digest",
    }
    row = _exact_dict(value, required, "invalid_experience_record")
    digest = row["canonical_digest"]
    body = {key: item for key, item in row.items() if key != "canonical_digest"}
    if (
        expected_schema not in {"planning_experience.v1", "validation_experience.v1"}
        or row["schema"] != expected_schema
        or row["authority"] != AUTHORITY
        or row["redaction_policy_version"] != REDACTION_POLICY_VERSION
        or row["derivation_rule_version"] != DERIVATION_RULE_VERSION
        or _safe_id(row["record_id"], "invalid_experience_record")
        != row["record_id"]
        or _digest(row["project_scope_digest"], "invalid_experience_record")
        != row["project_scope_digest"]
        or _digest(digest, "invalid_experience_record") != digest
        or digest != canonical_digest(body)
    ):
        raise ExperienceError("invalid_experience_record")
    validator = (
        _planning_value
        if expected_schema == "planning_experience.v1"
        else _validation_value
    )
    for field in allowed:
        validator(field, row[field])
    refs = row["source_evidence_references"]
    if type(refs) is not list:
        raise ExperienceError("invalid_experience_record")
    normalized_refs = []
    for ref in refs:
        item = _exact_dict(
            ref,
            {"evidence_id", "sha256"},
            "invalid_experience_record",
        )
        normalized_refs.append(
            {
                "evidence_id": _safe_id(
                    item["evidence_id"], "invalid_experience_record"
                ),
                "sha256": _digest(item["sha256"], "invalid_experience_record"),
            }
        )
    if refs != sorted(normalized_refs, key=lambda item: item["evidence_id"]):
        raise ExperienceError("invalid_experience_record")
    return row


def validate_task_label(raw: bytes, expected_sha256: str) -> dict[str, Any]:
    _digest(expected_sha256, "invalid_task_label_digest")
    if sha256_bytes(raw) != expected_sha256:
        raise ExperienceError("task_label_file_digest_mismatch")
    row = _exact_dict(
        strict_json_bytes(raw, name="task-label.json"),
        {
            "schema",
            "authority",
            "task_id",
            "project_scope_digest",
            "planning_experience_sha256",
            "validation_experience_sha256",
            "fixed_model",
            "label_rule_version",
            "attribution_status",
            "metrics",
            "canonical_digest",
        },
        "invalid_task_label",
    )
    model = _exact_dict(
        row["fixed_model"],
        {"name", "digest"},
        "invalid_task_label",
    )
    metrics = row["metrics"]
    if type(metrics) is not dict or set(metrics) - set(RATE_METRICS + AVERAGE_METRICS):
        raise ExperienceError("invalid_task_label")
    normalized_metrics: dict[str, Any] = {}
    for name in RATE_METRICS:
        value = metrics.get(name, NOT_RECORDED)
        if value != NOT_RECORDED and type(value) is not bool:
            raise ExperienceError(f"invalid_rate_metric:{name}")
        normalized_metrics[name] = value
    for name in AVERAGE_METRICS:
        value = metrics.get(name, NOT_RECORDED)
        if value != NOT_RECORDED and (
            type(value) not in {int, float}
            or not math.isfinite(value)
            or value < 0
        ):
            raise ExperienceError(f"invalid_average_metric:{name}")
        normalized_metrics[name] = value
    body = {key: value for key, value in row.items() if key != "canonical_digest"}
    if (
        row["schema"] != "reweave_experience_task_label.v1"
        or row["authority"] != AUTHORITY
        or _safe_id(row["task_id"], "invalid_task_label") != row["task_id"]
        or _digest(row["project_scope_digest"], "invalid_task_label")
        != row["project_scope_digest"]
        or _digest(row["planning_experience_sha256"], "invalid_task_label")
        != row["planning_experience_sha256"]
        or _digest(row["validation_experience_sha256"], "invalid_task_label")
        != row["validation_experience_sha256"]
        or _safe_model_name(model["name"]) != model["name"]
        or _digest(model["digest"], "invalid_task_label") != model["digest"]
        or row["label_rule_version"] != LABEL_RULE_VERSION
        or row["attribution_status"] not in {"RECORDED", NOT_RECORDED}
        or row["metrics"]
        != {
            name: normalized_metrics[name]
            for name in RATE_METRICS + AVERAGE_METRICS
        }
        or _digest(row["canonical_digest"], "invalid_task_label")
        != row["canonical_digest"]
        or row["canonical_digest"] != canonical_digest(body)
    ):
        raise ExperienceError("invalid_task_label")
    return row


def _record(
    schema: str,
    record_id: str,
    scope_digest: str,
    values: dict[str, Any],
    references: list[dict[str, str]],
) -> dict[str, Any]:
    fields = PLANNING_FIELDS if schema == "planning_experience.v1" else VALIDATION_FIELDS
    validator = _planning_value if schema == "planning_experience.v1" else _validation_value
    body: dict[str, Any] = {
        "schema": schema,
        "authority": AUTHORITY,
        "redaction_policy_version": REDACTION_POLICY_VERSION,
        "derivation_rule_version": DERIVATION_RULE_VERSION,
        "record_id": record_id,
        "project_scope_digest": _digest(scope_digest, "invalid_project_scope"),
    }
    for field in fields:
        body[field] = validator(field, values.get(field, NOT_RECORDED))
    body["source_evidence_references"] = sorted(
        references,
        key=lambda item: item["evidence_id"],
    )
    result = {**body, "canonical_digest": canonical_digest(body)}
    validate_experience_record(
        canonical_bytes(result),
        schema,
        sha256_bytes(canonical_bytes(result)),
    )
    return result


def _ordered_safe_members(
    plan: dict[str, Any],
    catalog: dict[str, Any],
) -> list[dict[str, str]]:
    if (
        type(catalog) is not dict
        or type(catalog.get("capsules")) is not list
        or type(plan) is not dict
        or type(plan.get("sections")) is not list
    ):
        raise ExperienceError("project_experience_context_invalid")
    catalog_by_identity = {
        (item.get("capsule_id"), item.get("version_id")): item
        for item in catalog["capsules"]
        if type(item) is dict
    }
    work_items = {
        item["work_item_id"]: item
        for section in plan["sections"]
        for item in section.get("work_items", [])
        if type(item) is dict and item.get("capsule_bindings")
    }
    incoming = {
        work_id: set(item.get("depends_on", []))
        for work_id, item in work_items.items()
    }
    ready = sorted(key for key, deps in incoming.items() if not deps)
    ordered: list[dict[str, str]] = []
    visited: set[str] = set()
    while ready:
        work_id = ready.pop(0)
        visited.add(work_id)
        bindings = work_items[work_id]["capsule_bindings"]
        if type(bindings) is not list or len(bindings) != 1:
            raise ExperienceError("project_experience_context_invalid")
        binding = bindings[0]
        current = catalog_by_identity.get(
            (binding.get("capsule_id"), binding.get("version_id"))
        )
        if (
            type(current) is not dict
            or current.get("canonical_hash") != binding.get("canonical_hash")
        ):
            raise ExperienceError("project_experience_catalog_stale")
        ordered.append(
            {
                key: str(current[key])
                for key in (
                    "display_name",
                    "capability_key",
                    "role_key",
                    "variant_key",
                    "capability_kind",
                )
            }
        )
        for other in sorted(incoming):
            if work_id in incoming[other]:
                incoming[other].remove(work_id)
                if not incoming[other] and other not in visited and other not in ready:
                    ready.append(other)
                    ready.sort()
    if len(visited) != len(work_items) or not ordered:
        raise ExperienceError("project_experience_context_invalid")
    return ordered


def _catalog_digest(catalog: dict[str, Any]) -> str:
    if (
        type(catalog) is not dict
        or type(catalog.get("warehouse_revision")) is not int
        or type(catalog.get("capsules")) is not list
    ):
        raise ExperienceError("project_experience_context_invalid")
    capsules = sorted(
        catalog["capsules"],
        key=lambda item: (
            str(item.get("capsule_id")),
            str(item.get("version_id")),
            str(item.get("canonical_hash")),
        ),
    )
    return canonical_digest(
        {
            "warehouse_revision": catalog["warehouse_revision"],
            "capsules": capsules,
        }
    )


def build_project_experience_record(
    *,
    workspace: dict[str, Any],
    catalog: dict[str, Any],
    project_scope_digest: str,
    milestone: str,
    candidate: dict[str, Any] | None = None,
    export_status: str | None = None,
) -> dict[str, Any]:
    if milestone not in PROJECT_EXPERIENCE_MILESTONES:
        raise ExperienceError("project_experience_milestone_invalid")
    plan = workspace.get("plan")
    model = workspace.get("model")
    if (
        type(plan) is not dict
        or type(model) is not dict
        or workspace.get("status") != "confirmed"
        or type(workspace.get("confirmation")) is not dict
        or WORKSPACE_ID.fullmatch(str(workspace.get("workspace_id"))) is None
        or plan.get("canonical_digest") is None
        or plan.get("goal_digest") != workspace.get("goal_digest")
    ):
        raise ExperienceError("project_experience_context_invalid")
    if milestone == "plan_confirmed" and candidate is not None:
        raise ExperienceError("project_experience_context_invalid")
    if milestone != "plan_confirmed" and type(candidate) is not dict:
        raise ExperienceError("project_experience_context_invalid")
    if milestone == "export_terminal" and export_status not in {"saved", "already_saved"}:
        raise ExperienceError("project_experience_context_invalid")
    members = _ordered_safe_members(plan, catalog)
    failure_attribution: Any = NOT_RECORDED
    if candidate is not None and candidate.get("status") != "review_ready":
        acceptance = candidate.get("acceptance")
        cases = acceptance.get("cases") if type(acceptance) is dict else None
        failure_code = next(
            (
                item.get("failure_code")
                for item in cases or []
                if type(item) is dict
                and type(item.get("failure_code")) is str
                and item["failure_code"]
            ),
            None,
        )
        if type(failure_code) is not str or SAFE_ID.fullmatch(failure_code) is None:
            raise ExperienceError("project_experience_failure_unattributed")
        failure_attribution = {
            "status": "RECORDED",
            "code": failure_code,
            "rule_version": "candidate_acceptance.v1",
            "evidence_digest": canonical_digest(acceptance),
        }
    safe_case = {
        "schema_version": PROJECT_EXPERIENCE_CASE_VERSION,
        "milestone": milestone,
        "members": members,
        "user_decision": "confirmed",
        "candidate_result": (
            "not_generated"
            if candidate is None
            else (
                "review_ready"
                if candidate.get("status") == "review_ready"
                else "failed"
            )
        ),
        "delivery_result": (
            "passed" if milestone == "export_terminal" else "not_attempted"
        ),
        "failure_attribution": failure_attribution,
    }
    workspace_digest = canonical_digest(workspace)
    references = [{"evidence_id": "workspace", "sha256": workspace_digest}]
    if candidate is not None:
        references.append(
            {
                "evidence_id": "candidate",
                "sha256": canonical_digest(candidate),
            }
        )
    selection = workspace.get("blueprint", {}).get("selection", {})
    offer_ref = (
        selection.get("offer_ref")
        if type(selection) is dict
        and type(selection.get("offer_ref")) is str
        and SAFE_OFFER_REF.fullmatch(selection["offer_ref"])
        else NOT_RECORDED
    )
    execution_digest = (
        candidate.get("execution_digest")
        if type(candidate) is dict
        and SHA256.fullmatch(str(candidate.get("execution_digest")))
        else NOT_RECORDED
    )
    connection_digest = (
        candidate.get("provenance", {}).get("connection_digest")
        if type(candidate) is dict
        and type(candidate.get("provenance")) is dict
        and SHA256.fullmatch(
            str(candidate["provenance"].get("connection_digest"))
        )
        else NOT_RECORDED
    )
    planning = _record(
        "planning_experience.v1",
        "planning",
        project_scope_digest,
        {
            "goal_safe_projection": {
                "canonical_value_sha256": workspace["goal_digest"]
            },
            "frozen_catalog_digest": _catalog_digest(catalog),
            "composition_offer_digest": canonical_digest(members),
            "exact_model_name": model["name"],
            "exact_model_digest": model["digest"],
            "model_selection": offer_ref,
            "user_decision": "confirmed",
            "plan_digest": plan["canonical_digest"],
            "execution_digest": execution_digest,
            "connection_digest": connection_digest,
            "candidate_result": safe_case["candidate_result"],
            "delivery_result": safe_case["delivery_result"],
            "failure_attribution": failure_attribution,
        },
        references,
    )
    validation = _record(
        "validation_experience.v1",
        "validation",
        project_scope_digest,
        {
            "candidate_result": safe_case["candidate_result"],
            "export_result": (
                "passed" if milestone == "export_terminal" else "not_run"
            ),
            "failure_attribution": failure_attribution,
        },
        references,
    )
    body = {
        "schema_version": PROJECT_EXPERIENCE_RECORD_VERSION,
        "authority": AUTHORITY,
        "redaction_policy_version": REDACTION_POLICY_VERSION,
        "derivation_rule_version": DERIVATION_RULE_VERSION,
        "project_scope_digest": project_scope_digest,
        "source_workspace_id": workspace["workspace_id"],
        "source_plan_token_digest": canonical_digest(workspace["plan_token"]),
        "source_goal_digest": workspace["goal_digest"],
        "lineage_digest": canonical_digest(
            {
                "workspace_id": workspace["workspace_id"],
                "goal_digest": workspace["goal_digest"],
            }
        ),
        "milestone": milestone,
        "exact_model_name": model["name"],
        "exact_model_digest": model["digest"],
        "safe_case": safe_case,
        "planning_experience": planning,
        "validation_experience": validation,
    }
    result = {**body, "record_digest": canonical_digest(body)}
    return validate_project_experience_record(result)


def validate_project_experience_record(value: Any) -> dict[str, Any]:
    row = _exact_dict(
        value,
        {
            "schema_version",
            "authority",
            "redaction_policy_version",
            "derivation_rule_version",
            "project_scope_digest",
            "source_workspace_id",
            "source_plan_token_digest",
            "source_goal_digest",
            "lineage_digest",
            "milestone",
            "exact_model_name",
            "exact_model_digest",
            "safe_case",
            "planning_experience",
            "validation_experience",
            "record_digest",
        },
        "project_experience_record_invalid",
    )
    body = {key: item for key, item in row.items() if key != "record_digest"}
    if (
        row["schema_version"] != PROJECT_EXPERIENCE_RECORD_VERSION
        or row["authority"] != AUTHORITY
        or row["redaction_policy_version"] != REDACTION_POLICY_VERSION
        or row["derivation_rule_version"] != DERIVATION_RULE_VERSION
        or _digest(row["project_scope_digest"], "project_experience_record_invalid")
        != row["project_scope_digest"]
        or WORKSPACE_ID.fullmatch(str(row["source_workspace_id"])) is None
        or any(
            _digest(row[key], "project_experience_record_invalid") != row[key]
            for key in (
                "source_plan_token_digest",
                "source_goal_digest",
                "lineage_digest",
                "exact_model_digest",
                "record_digest",
            )
        )
        or row["milestone"] not in PROJECT_EXPERIENCE_MILESTONES
        or _safe_model_name(row["exact_model_name"]) != row["exact_model_name"]
        or row["record_digest"] != canonical_digest(body)
    ):
        raise ExperienceError("project_experience_record_invalid")
    safe_case = _exact_dict(
        row["safe_case"],
        {
            "schema_version",
            "milestone",
            "members",
            "user_decision",
            "candidate_result",
            "delivery_result",
            "failure_attribution",
        },
        "project_experience_record_invalid",
    )
    if (
        safe_case["schema_version"] != PROJECT_EXPERIENCE_CASE_VERSION
        or safe_case["milestone"] != row["milestone"]
        or safe_case["user_decision"] != "confirmed"
        or safe_case["candidate_result"]
        not in {"not_generated", "review_ready", "failed"}
        or safe_case["delivery_result"] not in {"not_attempted", "passed"}
        or _failure_attribution(safe_case["failure_attribution"])
        != safe_case["failure_attribution"]
        or type(safe_case["members"]) is not list
        or not safe_case["members"]
    ):
        raise ExperienceError("project_experience_record_invalid")
    for member in safe_case["members"]:
        current = _exact_dict(
            member,
            {
                "display_name",
                "capability_key",
                "role_key",
                "variant_key",
                "capability_kind",
            },
            "project_experience_record_invalid",
        )
        if any(
            type(item) is not str
            or not item
            or ABSOLUTE_PATH_FRAGMENT.search(item) is not None
            for item in current.values()
        ):
            raise ExperienceError("project_experience_record_invalid")
    for key, schema in (
        ("planning_experience", "planning_experience.v1"),
        ("validation_experience", "validation_experience.v1"),
    ):
        raw = canonical_bytes(row[key])
        validate_experience_record(raw, schema, sha256_bytes(raw))
        if row[key]["project_scope_digest"] != row["project_scope_digest"]:
            raise ExperienceError("project_experience_record_invalid")
    planning = row["planning_experience"]
    validation = row["validation_experience"]
    expected = {
        "plan_confirmed": ("not_generated", "not_attempted", "not_run"),
        "candidate_terminal": (
            safe_case["candidate_result"],
            "not_attempted",
            "not_run",
        ),
        "export_terminal": (
            safe_case["candidate_result"],
            "passed",
            "passed",
        ),
    }[row["milestone"]]
    if (
        planning["exact_model_name"] != row["exact_model_name"]
        or planning["exact_model_digest"] != row["exact_model_digest"]
        or planning["plan_digest"] == NOT_RECORDED
        or planning["goal_safe_projection"]
        != {"canonical_value_sha256": row["source_goal_digest"]}
        or (
            planning["candidate_result"],
            planning["delivery_result"],
            validation["export_result"],
        )
        != expected
        or validation["candidate_result"] != safe_case["candidate_result"]
    ):
        raise ExperienceError("project_experience_record_invalid")
    return row


def goal_tokens(value: str) -> frozenset[str]:
    if type(value) is not str:
        raise ExperienceError("project_experience_query_invalid")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens = set(_LATIN_TOKEN.findall(normalized))
    for run in _CJK_RUN.findall(normalized):
        tokens.update(
            run[index : index + 2]
            for index in range(max(1, len(run) - 1))
        )
    return frozenset(token for token in tokens if token not in _GENERIC_TOKENS)


def _similarity(left: frozenset[str], right: frozenset[str]) -> int:
    if not left or not right:
        return 0
    return (2_000_000 * len(left & right)) // (len(left) + len(right))


def build_product_experience_query(
    *,
    workspace: dict[str, Any],
    project_scope_digest: str,
    records_with_workspaces: list[tuple[dict[str, Any], dict[str, Any]]],
    limit: int = 3,
) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 3:
        raise ExperienceError("project_experience_query_invalid")
    model = workspace.get("model")
    if (
        type(model) is not dict
        or type(workspace.get("goal")) is not str
        or SHA256.fullmatch(str(workspace.get("goal_digest"))) is None
        or WORKSPACE_ID.fullmatch(str(workspace.get("workspace_id"))) is None
        or _safe_model_name(model.get("name")) != model.get("name")
        or _digest(model.get("digest"), "project_experience_query_invalid")
        != model.get("digest")
    ):
        raise ExperienceError("project_experience_query_invalid")
    query_tokens = goal_tokens(workspace["goal"])
    latest: dict[str, tuple[int, dict[str, Any], str]] = {}
    milestone_rank = {
        milestone: index
        for index, milestone in enumerate(PROJECT_EXPERIENCE_MILESTONES)
    }
    for raw, historical_workspace in records_with_workspaces:
        record = validate_project_experience_record(raw)
        historical_goal = historical_workspace.get("goal")
        if (
            type(historical_goal) is not str
            or historical_workspace.get("workspace_id")
            != record["source_workspace_id"]
            or historical_workspace.get("goal_digest")
            != record["source_goal_digest"]
        ):
            raise ExperienceError("project_experience_record_binding_invalid")
        if record["project_scope_digest"] != project_scope_digest:
            raise ExperienceError("project_experience_scope_mismatch")
        if (
            record["exact_model_name"] != model.get("name")
            or record["exact_model_digest"] != model.get("digest")
            or record["source_workspace_id"] == workspace["workspace_id"]
        ):
            continue
        rank = milestone_rank[record["milestone"]]
        current = latest.get(record["lineage_digest"])
        if current is None or (rank, record["record_digest"]) > (
            current[0],
            current[1]["record_digest"],
        ):
            latest[record["lineage_digest"]] = (rank, record, historical_goal)
    matches = []
    for _rank, record, historical_goal in latest.values():
        similarity = _similarity(query_tokens, goal_tokens(historical_goal))
        if similarity <= 0:
            continue
        matches.append(
            {
                "record_digest": record["record_digest"],
                "milestone": record["milestone"],
                "similarity_millionths": similarity,
                "safe_case": record["safe_case"],
            }
        )
    matches.sort(
        key=lambda item: (
            -item["similarity_millionths"],
            item["record_digest"],
        )
    )
    body = {
        "schema_version": PROJECT_EXPERIENCE_QUERY_VERSION,
        "authority": AUTHORITY,
        "project_scope_digest": project_scope_digest,
        "query_goal_digest": workspace["goal_digest"],
        "exact_model_name": model["name"],
        "exact_model_digest": model["digest"],
        "ranking_rule_version": PROJECT_EXPERIENCE_RANKING_VERSION,
        "cases": matches[:limit],
    }
    return validate_product_experience_query(
        {**body, "canonical_digest": canonical_digest(body)}
    )


def validate_product_experience_query(value: Any) -> dict[str, Any]:
    row = _exact_dict(
        value,
        {
            "schema_version",
            "authority",
            "project_scope_digest",
            "query_goal_digest",
            "exact_model_name",
            "exact_model_digest",
            "ranking_rule_version",
            "cases",
            "canonical_digest",
        },
        "project_experience_query_invalid",
    )
    body = {key: item for key, item in row.items() if key != "canonical_digest"}
    if (
        row["schema_version"] != PROJECT_EXPERIENCE_QUERY_VERSION
        or row["authority"] != AUTHORITY
        or _digest(row["project_scope_digest"], "project_experience_query_invalid")
        != row["project_scope_digest"]
        or _digest(row["query_goal_digest"], "project_experience_query_invalid")
        != row["query_goal_digest"]
        or _safe_model_name(row["exact_model_name"]) != row["exact_model_name"]
        or _digest(row["exact_model_digest"], "project_experience_query_invalid")
        != row["exact_model_digest"]
        or row["ranking_rule_version"] != PROJECT_EXPERIENCE_RANKING_VERSION
        or type(row["cases"]) is not list
        or len(row["cases"]) > 3
        or _digest(row["canonical_digest"], "project_experience_query_invalid")
        != row["canonical_digest"]
        or row["canonical_digest"] != canonical_digest(body)
    ):
        raise ExperienceError("project_experience_query_invalid")
    normalized_cases = []
    for raw in row["cases"]:
        case = _exact_dict(
            raw,
            {"record_digest", "milestone", "similarity_millionths", "safe_case"},
            "project_experience_query_invalid",
        )
        if (
            _digest(case["record_digest"], "project_experience_query_invalid")
            != case["record_digest"]
            or case["milestone"] not in PROJECT_EXPERIENCE_MILESTONES
            or type(case["similarity_millionths"]) is not int
            or not 1 <= case["similarity_millionths"] <= 1_000_000
            or type(case["safe_case"]) is not dict
        ):
            raise ExperienceError("project_experience_query_invalid")
        normalized_cases.append(case)
    if row["cases"] != sorted(
        normalized_cases,
        key=lambda item: (-item["similarity_millionths"], item["record_digest"]),
    ):
        raise ExperienceError("project_experience_query_invalid")
    return row


def build_product_experience_model_cases(
    value: Any,
) -> list[dict[str, Any]]:
    """Project a frozen query into the only fields safe for model selection."""

    query = validate_product_experience_query(value)
    result: list[dict[str, Any]] = []
    for rank, item in enumerate(query["cases"], start=1):
        safe_case = item["safe_case"]
        capability_keys = {
            member["capability_key"] for member in safe_case["members"]
        }
        if len(capability_keys) != 1:
            raise ExperienceError("project_experience_query_invalid")
        failure = safe_case["failure_attribution"]
        result.append(
            {
                "rank": rank,
                "capability_key": next(iter(capability_keys)),
                "members": [
                    {
                        key: member[key]
                        for key in (
                            "display_name",
                            "role_key",
                            "variant_key",
                            "capability_kind",
                        )
                    }
                    for member in safe_case["members"]
                ],
                "outcome": {
                    "candidate_result": safe_case["candidate_result"],
                    "delivery_result": safe_case["delivery_result"],
                    "attributed_failure_type": (
                        failure["code"]
                        if type(failure) is dict
                        and failure.get("status") == "RECORDED"
                        else ""
                    ),
                },
            }
        )
    return result
