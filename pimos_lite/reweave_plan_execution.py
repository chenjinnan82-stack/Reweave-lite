"""Deterministic confirmed-plan to module_native execution contract."""

from __future__ import annotations

import json
import re
from typing import Any

from pimos_lite import reweave_page_capability_contract as page_contract
from pimos_lite.reweave_canonical import (
    canonical_json_bytes,
    canonical_json_digest,
)
from pimos_lite.reweave_data_contract import (
    DataContractError,
    contracts_compatible,
    data_contract_accepts,
    normalize_data_contract,
)

PLAN_EXECUTION_VERSION = "plan_execution.v1"
PARAMETERIZED_PLAN_EXECUTION_VERSION = "plan_execution.v2"
PARAMETERIZED_EXECUTION_OFFER_VERSION = "parameterized_execution_offer.v1"
PARAMETERIZED_EXECUTION_CONFIRMATION_VERSION = (
    "parameterized_execution_confirmation.v1"
)
PARAMETERIZED_EXECUTION_BINDING_VERSION = "parameterized_execution_binding.v1"
CANDIDATE_ACCEPTANCE_VERSION = "candidate_acceptance.v1"
CANDIDATE_ACCEPTANCE_CONFIRMATION_VERSION = (
    "candidate_acceptance_confirmation.v1"
)
CANDIDATE_ACCEPTANCE_RECEIPT_VERSION = "candidate_acceptance_receipt.v1"
CANDIDATE_ACCEPTANCE_WORKER_VERSION = "candidate_acceptance_worker.v1"
MAX_CANDIDATE_ACCEPTANCE_CASES = 16
MAX_CANDIDATE_ACCEPTANCE_BYTES = 1024 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_PLAN_ID = re.compile(r"plan_[0-9a-f]{32}\Z")
_SECTION_IDS = ("frontend", "backend", "data", "infrastructure")
MAX_PARAMETERIZED_EXECUTION_BINDINGS = 16


class PlanExecutionError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CandidateAcceptanceError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def canonical_bytes(value: Any) -> bytes:
    try:
        return canonical_json_bytes(value)
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise PlanExecutionError("plan_execution_json_invalid") from exc


def canonical_digest(value: Any) -> str:
    try:
        return canonical_json_digest(value)
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise PlanExecutionError("plan_execution_json_invalid") from exc


def _exact(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise PlanExecutionError(code)
    return value


def _acceptance_copy(value: Any) -> Any:
    try:
        encoded = canonical_bytes(value)
    except PlanExecutionError as exc:
        raise CandidateAcceptanceError("candidate_acceptance_json_invalid") from exc
    if len(encoded) > MAX_CANDIDATE_ACCEPTANCE_BYTES:
        raise CandidateAcceptanceError("candidate_acceptance_payload_too_large")
    return json.loads(encoded)


def _acceptance_exact(
    value: Any,
    keys: set[str],
    code: str,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise CandidateAcceptanceError(code)
    return value


def _json_exact(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(
            _json_exact(left[key], right[key]) for key in left
        )
    if type(left) is list:
        return len(left) == len(right) and all(
            _json_exact(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _parameter_field_contract(field: str, contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {field: contract},
        "required": [field],
        "additional_properties": False,
    }


def _plan_parameter_context(
    plan: dict[str, Any],
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    set[str],
    set[str],
]:
    if type(plan) is not dict:
        raise PlanExecutionError("parameterized_execution_plan_invalid")
    canonical = {key: value for key, value in plan.items() if key != "canonical_digest"}
    if (
        plan.get("schema_version") != "product_plan.v1"
        or _DIGEST.fullmatch(str(plan.get("canonical_digest"))) is None
        or plan["canonical_digest"] != canonical_digest(canonical)
        or type(plan.get("requirements")) is not list
        or type(plan.get("sections")) is not list
    ):
        raise PlanExecutionError("parameterized_execution_plan_invalid")
    requirement_ids = {
        row.get("requirement_id")
        for row in plan["requirements"]
        if type(row) is dict and type(row.get("requirement_id")) is str
    }
    if len(requirement_ids) != len(plan["requirements"]) or None in requirement_ids:
        raise PlanExecutionError("parameterized_execution_plan_invalid")
    work_item_ids: set[str] = set()
    context: dict[tuple[str, str], dict[str, Any]] = {}
    for section in plan["sections"]:
        if type(section) is not dict or type(section.get("work_items")) is not list:
            raise PlanExecutionError("parameterized_execution_plan_invalid")
        for work_item in section["work_items"]:
            if (
                type(work_item) is not dict
                or type(work_item.get("work_item_id")) is not str
                or work_item["work_item_id"] in work_item_ids
                or type(work_item.get("requirement_ids")) is not list
                or not work_item["requirement_ids"]
                or set(work_item["requirement_ids"]) - requirement_ids
                or type(work_item.get("capsule_bindings")) is not list
            ):
                raise PlanExecutionError("parameterized_execution_plan_invalid")
            work_item_ids.add(work_item["work_item_id"])
            for binding in work_item["capsule_bindings"]:
                if (
                    type(binding) is not dict
                    or type(binding.get("capsule_id")) is not str
                    or type(binding.get("version_id")) is not str
                    or _DIGEST.fullmatch(str(binding.get("canonical_hash"))) is None
                ):
                    raise PlanExecutionError("parameterized_execution_plan_invalid")
                key = (binding["capsule_id"], binding["version_id"])
                item = context.setdefault(
                    key,
                    {
                        "canonical_hash": binding["canonical_hash"],
                        "work_item_ids": set(),
                        "requirement_ids": set(),
                    },
                )
                if item["canonical_hash"] != binding["canonical_hash"]:
                    raise PlanExecutionError("parameterized_execution_plan_invalid")
                item["work_item_ids"].add(work_item["work_item_id"])
                item["requirement_ids"].update(work_item["requirement_ids"])
    return context, requirement_ids, work_item_ids


def build_parameterized_execution_offer(
    plan: dict[str, Any],
    capsules: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Derive public integer execution parameters from exact formal contracts."""

    context, _requirement_ids, _work_item_ids = _plan_parameter_context(plan)
    if type(capsules) is not list:
        raise PlanExecutionError("parameterized_execution_capsule_invalid")
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for capsule in capsules:
        if type(capsule) is not dict:
            raise PlanExecutionError("parameterized_execution_capsule_invalid")
        key = (capsule.get("capsule_id"), capsule.get("version_id"))
        if (
            key not in context
            or key in seen
            or _DIGEST.fullmatch(str(capsule.get("canonical_hash"))) is None
            or capsule["canonical_hash"] != context[key]["canonical_hash"]
            or capsule.get("capability_kind")
            not in {"presentation", "interaction", "computation"}
        ):
            raise PlanExecutionError("parameterized_execution_capsule_invalid")
        seen.add(key)
        selected.append(capsule)
    if seen != set(context):
        raise PlanExecutionError("parameterized_execution_capsule_invalid")
    computations = [
        item for item in selected if item["capability_kind"] == "computation"
    ]
    interactions = [
        item for item in selected if item["capability_kind"] == "interaction"
    ]
    if len(computations) != 1 or len(interactions) != 1:
        return None
    computation = computations[0]
    interaction = interactions[0]
    if computation.get("capability_key") != interaction.get("capability_key"):
        raise PlanExecutionError("parameterized_execution_contract_incompatible")
    try:
        computation_input = normalize_data_contract(computation["input_contract"])
        interaction_output = interaction["output_contract"]
        if (
            type(interaction_output) is not dict
            or set(interaction_output) != {"schema", "events"}
            or interaction_output.get("schema") != "event_outputs.v1"
            or type(interaction_output.get("events")) is not dict
            or len(interaction_output["events"]) != 1
        ):
            raise DataContractError("parameterized_event_contract_invalid")
        runtime_input = normalize_data_contract(
            next(iter(interaction_output["events"].values()))
        )
    except (DataContractError, KeyError, TypeError) as exc:
        raise PlanExecutionError(
            "parameterized_execution_contract_incompatible"
        ) from exc
    if (
        computation_input["type"] != "object"
        or runtime_input["type"] != "object"
        or set(computation_input["properties"]) != set(computation_input["required"])
        or set(runtime_input["properties"]) != set(runtime_input["required"])
        or set(runtime_input["properties"]) - set(computation_input["properties"])
    ):
        raise PlanExecutionError("parameterized_execution_contract_incompatible")
    for field, source_contract in runtime_input["properties"].items():
        target_contract = computation_input["properties"][field]
        if not contracts_compatible(
            _parameter_field_contract(field, source_contract),
            _parameter_field_contract(field, target_contract),
        ):
            raise PlanExecutionError("parameterized_execution_contract_incompatible")
    parameter_fields = sorted(
        set(computation_input["required"]) - set(runtime_input["properties"])
    )
    if not parameter_fields:
        return None
    if len(parameter_fields) > MAX_PARAMETERIZED_EXECUTION_BINDINGS:
        raise PlanExecutionError("parameterized_execution_binding_count_invalid")
    if set(runtime_input["properties"]) & set(parameter_fields):
        raise PlanExecutionError("parameterized_execution_contract_incompatible")
    computation_key = (
        computation["capsule_id"],
        computation["version_id"],
    )
    references = context[computation_key]
    input_contract_digest = canonical_digest(computation_input)
    bindings: list[dict[str, Any]] = []
    for field in parameter_fields:
        value_contract = computation_input["properties"][field]
        if value_contract.get("type") != "integer":
            raise PlanExecutionError("parameterized_execution_parameter_unsupported")
        binding_id = "parameter_binding_" + canonical_digest(
            {
                "plan_digest": plan["canonical_digest"],
                "capsule_id": computation["capsule_id"],
                "version_id": computation["version_id"],
                "canonical_hash": computation["canonical_hash"],
                "input_field": field,
            }
        )[:24]
        bindings.append(
            {
                "binding_id": binding_id,
                "capsule_id": computation["capsule_id"],
                "version_id": computation["version_id"],
                "canonical_hash": computation["canonical_hash"],
                "input_contract_digest": input_contract_digest,
                "requirement_ids": sorted(references["requirement_ids"]),
                "work_item_ids": sorted(references["work_item_ids"]),
                "input_field": field,
                "value_contract": value_contract,
            }
        )
    body = {
        "schema_version": PARAMETERIZED_EXECUTION_OFFER_VERSION,
        "plan_digest": plan["canonical_digest"],
        "bindings": bindings,
    }
    return {**body, "offer_digest": canonical_digest(body)}


def _validate_parameter_offer(
    plan: dict[str, Any],
    offer: dict[str, Any],
) -> list[dict[str, Any]]:
    context, requirement_ids, work_item_ids = _plan_parameter_context(plan)
    row = _exact(
        offer,
        {"schema_version", "plan_digest", "bindings", "offer_digest"},
        "parameterized_execution_offer_invalid",
    )
    body = {key: value for key, value in row.items() if key != "offer_digest"}
    if (
        row["schema_version"] != PARAMETERIZED_EXECUTION_OFFER_VERSION
        or row["plan_digest"] != plan["canonical_digest"]
        or type(row["bindings"]) is not list
        or not 1 <= len(row["bindings"]) <= MAX_PARAMETERIZED_EXECUTION_BINDINGS
        or row["offer_digest"] != canonical_digest(body)
    ):
        raise PlanExecutionError("parameterized_execution_offer_invalid")
    result: list[dict[str, Any]] = []
    binding_ids: set[str] = set()
    fields: set[str] = set()
    for raw in row["bindings"]:
        item = _exact(
            raw,
            {
                "binding_id",
                "capsule_id",
                "version_id",
                "canonical_hash",
                "input_contract_digest",
                "requirement_ids",
                "work_item_ids",
                "input_field",
                "value_contract",
            },
            "parameterized_execution_offer_invalid",
        )
        key = (item["capsule_id"], item["version_id"])
        try:
            value_contract = normalize_data_contract(
                _parameter_field_contract(
                    item["input_field"],
                    item["value_contract"],
                )
            )["properties"][item["input_field"]]
        except (DataContractError, KeyError, TypeError) as exc:
            raise PlanExecutionError(
                "parameterized_execution_offer_invalid"
            ) from exc
        if (
            type(item["binding_id"]) is not str
            or not item["binding_id"].startswith("parameter_binding_")
            or item["binding_id"] in binding_ids
            or type(item["input_field"]) is not str
            or not item["input_field"]
            or item["input_field"] in fields
            or key not in context
            or context[key]["canonical_hash"] != item["canonical_hash"]
            or _DIGEST.fullmatch(str(item["input_contract_digest"])) is None
            or value_contract["type"] != "integer"
            or type(item["requirement_ids"]) is not list
            or item["requirement_ids"] != sorted(set(item["requirement_ids"]))
            or not item["requirement_ids"]
            or set(item["requirement_ids"]) - requirement_ids
            or type(item["work_item_ids"]) is not list
            or item["work_item_ids"] != sorted(set(item["work_item_ids"]))
            or not item["work_item_ids"]
            or set(item["work_item_ids"]) - work_item_ids
        ):
            raise PlanExecutionError("parameterized_execution_offer_invalid")
        binding_ids.add(item["binding_id"])
        fields.add(item["input_field"])
        result.append({**item, "value_contract": value_contract})
    if result != sorted(result, key=lambda item: item["input_field"]):
        raise PlanExecutionError("parameterized_execution_offer_invalid")
    return result


def build_parameterized_execution_binding(
    plan: dict[str, Any],
    offer: dict[str, Any],
    confirmation: dict[str, Any],
) -> dict[str, Any]:
    offered = _validate_parameter_offer(plan, offer)
    request = _exact(
        confirmation,
        {"schema_version", "offer_digest", "values"},
        "parameterized_execution_confirmation_invalid",
    )
    if (
        request["schema_version"]
        != PARAMETERIZED_EXECUTION_CONFIRMATION_VERSION
        or request["offer_digest"] != offer["offer_digest"]
        or type(request["values"]) is not list
    ):
        raise PlanExecutionError("parameterized_execution_confirmation_invalid")
    values: dict[str, int] = {}
    for raw in request["values"]:
        item = _exact(
            raw,
            {"binding_id", "value"},
            "parameterized_execution_confirmation_invalid",
        )
        if (
            type(item["binding_id"]) is not str
            or item["binding_id"] in values
            or type(item["value"]) is not int
        ):
            raise PlanExecutionError("parameterized_execution_confirmation_invalid")
        values[item["binding_id"]] = item["value"]
    if set(values) != {item["binding_id"] for item in offered}:
        raise PlanExecutionError("parameterized_execution_confirmation_invalid")
    bindings = []
    for item in offered:
        value = values[item["binding_id"]]
        if not data_contract_accepts(
            _parameter_field_contract(item["input_field"], item["value_contract"]),
            {item["input_field"]: value},
        ):
            raise PlanExecutionError("parameterized_execution_value_invalid")
        bindings.append(
            {
                key: item[key]
                for key in (
                    "binding_id",
                    "capsule_id",
                    "version_id",
                    "canonical_hash",
                    "input_contract_digest",
                    "requirement_ids",
                    "work_item_ids",
                    "input_field",
                )
            }
            | {
                "value": value,
                "value_digest": canonical_digest(value),
                "source": "user_confirmed",
            }
        )
    body = {
        "schema_version": PARAMETERIZED_EXECUTION_BINDING_VERSION,
        "offer_digest": offer["offer_digest"],
        "plan_digest": plan["canonical_digest"],
        "bindings": bindings,
    }
    return {**body, "canonical_digest": canonical_digest(body)}


def validate_parameterized_execution_binding(
    plan: dict[str, Any],
    binding: dict[str, Any],
    offer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context, requirement_ids, work_item_ids = _plan_parameter_context(plan)
    row = _exact(
        binding,
        {
            "schema_version",
            "offer_digest",
            "plan_digest",
            "bindings",
            "canonical_digest",
        },
        "parameterized_execution_binding_invalid",
    )
    body = {key: value for key, value in row.items() if key != "canonical_digest"}
    if (
        row["schema_version"] != PARAMETERIZED_EXECUTION_BINDING_VERSION
        or row["plan_digest"] != plan["canonical_digest"]
        or _DIGEST.fullmatch(str(row["offer_digest"])) is None
        or type(row["bindings"]) is not list
        or not 1 <= len(row["bindings"]) <= MAX_PARAMETERIZED_EXECUTION_BINDINGS
        or row["canonical_digest"] != canonical_digest(body)
    ):
        raise PlanExecutionError("parameterized_execution_binding_invalid")
    bindings: list[dict[str, Any]] = []
    seen: set[str] = set()
    fields: set[str] = set()
    for raw in row["bindings"]:
        item = _exact(
            raw,
            {
                "binding_id",
                "capsule_id",
                "version_id",
                "canonical_hash",
                "input_contract_digest",
                "requirement_ids",
                "work_item_ids",
                "input_field",
                "value",
                "value_digest",
                "source",
            },
            "parameterized_execution_binding_invalid",
        )
        key = (item["capsule_id"], item["version_id"])
        expected_id = "parameter_binding_" + canonical_digest(
            {
                "plan_digest": plan["canonical_digest"],
                "capsule_id": item["capsule_id"],
                "version_id": item["version_id"],
                "canonical_hash": item["canonical_hash"],
                "input_field": item["input_field"],
            }
        )[:24]
        if (
            type(item["binding_id"]) is not str
            or item["binding_id"] in seen
            or item["binding_id"] != expected_id
            or type(item["capsule_id"]) is not str
            or type(item["version_id"]) is not str
            or _DIGEST.fullmatch(str(item["canonical_hash"])) is None
            or key not in context
            or context[key]["canonical_hash"] != item["canonical_hash"]
            or _DIGEST.fullmatch(str(item["input_contract_digest"])) is None
            or type(item["requirement_ids"]) is not list
            or item["requirement_ids"] != sorted(set(item["requirement_ids"]))
            or not item["requirement_ids"]
            or set(item["requirement_ids"]) - requirement_ids
            or item["requirement_ids"]
            != sorted(context[key]["requirement_ids"])
            or type(item["work_item_ids"]) is not list
            or item["work_item_ids"] != sorted(set(item["work_item_ids"]))
            or not item["work_item_ids"]
            or set(item["work_item_ids"]) - work_item_ids
            or item["work_item_ids"] != sorted(context[key]["work_item_ids"])
            or type(item["input_field"]) is not str
            or not item["input_field"]
            or item["input_field"] in fields
            or type(item["value"]) is not int
            or item["value_digest"] != canonical_digest(item["value"])
            or item["source"] != "user_confirmed"
        ):
            raise PlanExecutionError("parameterized_execution_binding_invalid")
        seen.add(item["binding_id"])
        fields.add(item["input_field"])
        bindings.append(dict(item))
    if bindings != sorted(bindings, key=lambda item: item["input_field"]):
        raise PlanExecutionError("parameterized_execution_binding_invalid")
    if offer is not None:
        expected = build_parameterized_execution_binding(
            plan,
            offer,
            {
                "schema_version": PARAMETERIZED_EXECUTION_CONFIRMATION_VERSION,
                "offer_digest": offer["offer_digest"],
                "values": [
                    {
                        "binding_id": item["binding_id"],
                        "value": item["value"],
                    }
                    for item in bindings
                ],
            },
        )
        if expected != row:
            raise PlanExecutionError("parameterized_execution_binding_stale")
    return {**body, "canonical_digest": row["canonical_digest"]}


def build_candidate_acceptance(
    plan: dict[str, Any],
    confirmation: dict[str, Any],
    cases: list[dict[str, Any]],
    input_contract: dict[str, Any],
    output_contract: dict[str, Any],
    candidate_content_digest: str,
) -> dict[str, Any]:
    """Canonicalize user-confirmed product conformance examples."""

    plan_body = (
        {key: value for key, value in plan.items() if key != "canonical_digest"}
        if type(plan) is dict
        else {}
    )
    confirmation_body = (
        {
            key: value
            for key, value in confirmation.items()
            if key != "receipt_digest"
        }
        if type(confirmation) is dict
        else {}
    )
    if (
        type(plan) is not dict
        or plan.get("schema_version") != "product_plan.v1"
        or _DIGEST.fullmatch(str(plan.get("canonical_digest"))) is None
        or plan.get("canonical_digest") != canonical_digest(plan_body)
        or type(plan.get("requirements")) is not list
        or type(confirmation) is not dict
        or confirmation.get("schema_version")
        not in {
            "product_plan_confirmation.v1",
            "product_plan_confirmation.v2",
        }
        or confirmation.get("plan_id") != plan.get("plan_id")
        or confirmation.get("plan_version") != plan.get("plan_version")
        or confirmation.get("plan_digest") != plan.get("canonical_digest")
        or _DIGEST.fullmatch(str(confirmation.get("receipt_digest"))) is None
        or confirmation.get("receipt_digest")
        != canonical_digest(confirmation_body)
        or _DIGEST.fullmatch(str(candidate_content_digest)) is None
    ):
        raise CandidateAcceptanceError("candidate_acceptance_binding_invalid")
    requirement_ids = {
        item.get("requirement_id")
        for item in plan["requirements"]
        if type(item) is dict and type(item.get("requirement_id")) is str
    }
    if len(requirement_ids) != len(plan["requirements"]) or not requirement_ids:
        raise CandidateAcceptanceError("candidate_acceptance_requirement_invalid")
    try:
        normalized_input = normalize_data_contract(input_contract)
        normalized_output = normalize_data_contract(output_contract)
    except DataContractError as exc:
        raise CandidateAcceptanceError("candidate_acceptance_contract_invalid") from exc
    if (
        type(cases) is not list
        or not 1 <= len(cases) <= MAX_CANDIDATE_ACCEPTANCE_CASES
    ):
        raise CandidateAcceptanceError("candidate_acceptance_case_count_invalid")

    normalized_cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(cases, start=1):
        case = _acceptance_exact(
            raw,
            {"requirement_ids", "input", "expected_output"},
            "candidate_acceptance_case_invalid",
        )
        case_requirements = case["requirement_ids"]
        if (
            type(case_requirements) is not list
            or not case_requirements
            or any(type(value) is not str for value in case_requirements)
            or len(case_requirements) != len(set(case_requirements))
            or set(case_requirements) - requirement_ids
        ):
            raise CandidateAcceptanceError("candidate_acceptance_requirement_invalid")
        item_input = _acceptance_copy(case["input"])
        expected_output = _acceptance_copy(case["expected_output"])
        if not data_contract_accepts(normalized_input, item_input):
            raise CandidateAcceptanceError("candidate_acceptance_input_invalid")
        if not data_contract_accepts(normalized_output, expected_output):
            raise CandidateAcceptanceError("candidate_acceptance_expected_output_invalid")
        semantic = {
            "requirement_ids": sorted(case_requirements),
            "input": item_input,
            "expected_output": expected_output,
        }
        semantic_digest = canonical_digest(semantic)
        if semantic_digest in seen:
            raise CandidateAcceptanceError("candidate_acceptance_case_duplicate")
        seen.add(semantic_digest)
        normalized_cases.append(
            {
                "case_id": f"case_{index:02d}",
                **semantic,
            }
        )

    contract = {
        "schema_version": CANDIDATE_ACCEPTANCE_VERSION,
        "plan_digest": plan["canonical_digest"],
        "confirmation_digest": confirmation["receipt_digest"],
        "candidate_content_digest": candidate_content_digest,
        "requirement_ids": sorted(requirement_ids),
        "input_contract_digest": canonical_digest(normalized_input),
        "output_contract_digest": canonical_digest(normalized_output),
        "cases": normalized_cases,
    }
    contract["canonical_digest"] = canonical_digest(contract)
    _acceptance_copy(contract)
    return contract


def build_candidate_acceptance_confirmation(
    plan: dict[str, Any],
    confirmation: dict[str, Any],
    cases: list[dict[str, Any]],
    input_contract: dict[str, Any],
    output_contract: dict[str, Any],
    confirmed_at: str,
) -> dict[str, Any]:
    """Canonicalize one user-owned acceptance specification before generation."""

    if type(confirmed_at) is not str or not confirmed_at or len(confirmed_at) > 128:
        raise CandidateAcceptanceError(
            "candidate_acceptance_confirmation_invalid"
        )
    normalized = build_candidate_acceptance(
        plan,
        confirmation,
        cases,
        input_contract,
        output_contract,
        "0" * 64,
    )
    record = {
        "schema_version": CANDIDATE_ACCEPTANCE_CONFIRMATION_VERSION,
        "plan_digest": normalized["plan_digest"],
        "plan_confirmation_digest": normalized["confirmation_digest"],
        "requirement_ids": normalized["requirement_ids"],
        "input_contract_digest": normalized["input_contract_digest"],
        "output_contract_digest": normalized["output_contract_digest"],
        "cases": normalized["cases"],
        "confirmed_at": confirmed_at,
        "confirmation_source": "user_confirmed",
    }
    record["canonical_digest"] = canonical_digest(record)
    _acceptance_copy(record)
    return record


def validate_candidate_acceptance_confirmation(
    plan: dict[str, Any],
    confirmation: dict[str, Any],
    record: dict[str, Any],
    input_contract: dict[str, Any],
    output_contract: dict[str, Any],
) -> dict[str, Any]:
    """Rebuild a stored acceptance confirmation and reject any divergence."""

    row = _acceptance_exact(
        record,
        {
            "schema_version",
            "plan_digest",
            "plan_confirmation_digest",
            "requirement_ids",
            "input_contract_digest",
            "output_contract_digest",
            "cases",
            "confirmed_at",
            "confirmation_source",
            "canonical_digest",
        },
        "candidate_acceptance_confirmation_invalid",
    )
    if (
        row["schema_version"] != CANDIDATE_ACCEPTANCE_CONFIRMATION_VERSION
        or row["confirmation_source"] != "user_confirmed"
        or type(row["cases"]) is not list
    ):
        raise CandidateAcceptanceError(
            "candidate_acceptance_confirmation_invalid"
        )
    raw_cases = [
        {
            key: case[key]
            for key in ("requirement_ids", "input", "expected_output")
        }
        if type(case) is dict
        and set(case)
        == {"case_id", "requirement_ids", "input", "expected_output"}
        else {}
        for case in row["cases"]
    ]
    try:
        expected = build_candidate_acceptance_confirmation(
            plan,
            confirmation,
            raw_cases,
            input_contract,
            output_contract,
            row["confirmed_at"],
        )
    except (CandidateAcceptanceError, KeyError) as exc:
        raise CandidateAcceptanceError(
            "candidate_acceptance_confirmation_invalid"
        ) from exc
    if expected != row:
        raise CandidateAcceptanceError(
            "candidate_acceptance_confirmation_invalid"
        )
    return _acceptance_copy(row)


def evaluate_candidate_acceptance(
    contract: dict[str, Any],
    worker_result: dict[str, Any],
    input_contract: dict[str, Any],
    output_contract: dict[str, Any],
) -> dict[str, Any]:
    """Build a stable receipt from one bounded QWebEngine acceptance run."""

    required_contract = {
        "schema_version",
        "plan_digest",
        "confirmation_digest",
        "candidate_content_digest",
        "requirement_ids",
        "input_contract_digest",
        "output_contract_digest",
        "cases",
        "canonical_digest",
    }
    contract = _acceptance_exact(
        contract,
        required_contract,
        "candidate_acceptance_contract_invalid",
    )
    contract_body = {
        key: value for key, value in contract.items() if key != "canonical_digest"
    }
    if (
        contract["schema_version"] != CANDIDATE_ACCEPTANCE_VERSION
        or any(
            _DIGEST.fullmatch(str(contract.get(key))) is None
            for key in (
                "plan_digest",
                "confirmation_digest",
                "candidate_content_digest",
                "input_contract_digest",
                "output_contract_digest",
                "canonical_digest",
            )
        )
        or contract["canonical_digest"] != canonical_digest(contract_body)
        or type(contract["cases"]) is not list
        or not 1 <= len(contract["cases"]) <= MAX_CANDIDATE_ACCEPTANCE_CASES
    ):
        raise CandidateAcceptanceError("candidate_acceptance_contract_invalid")
    try:
        normalized_input = normalize_data_contract(input_contract)
        normalized_output = normalize_data_contract(output_contract)
    except DataContractError as exc:
        raise CandidateAcceptanceError("candidate_acceptance_contract_invalid") from exc
    if (
        canonical_digest(normalized_input) != contract["input_contract_digest"]
        or canonical_digest(normalized_output) != contract["output_contract_digest"]
        or type(contract["requirement_ids"]) is not list
        or not contract["requirement_ids"]
        or any(type(value) is not str for value in contract["requirement_ids"])
        or len(contract["requirement_ids"]) != len(set(contract["requirement_ids"]))
    ):
        raise CandidateAcceptanceError("candidate_acceptance_contract_invalid")
    for index, case in enumerate(contract["cases"], start=1):
        row = _acceptance_exact(
            case,
            {"case_id", "requirement_ids", "input", "expected_output"},
            "candidate_acceptance_contract_invalid",
        )
        if (
            row["case_id"] != f"case_{index:02d}"
            or type(row["requirement_ids"]) is not list
            or not row["requirement_ids"]
            or any(type(value) is not str for value in row["requirement_ids"])
            or len(row["requirement_ids"]) != len(set(row["requirement_ids"]))
            or set(row["requirement_ids"]) - set(contract["requirement_ids"])
            or not data_contract_accepts(normalized_input, row["input"])
            or not data_contract_accepts(normalized_output, row["expected_output"])
        ):
            raise CandidateAcceptanceError("candidate_acceptance_contract_invalid")

    result = _acceptance_exact(
        worker_result,
        {"schema_version", "status", "cases"},
        "candidate_acceptance_worker_invalid",
    )
    if (
        result["schema_version"] != CANDIDATE_ACCEPTANCE_WORKER_VERSION
        or result["status"] != "completed"
        or type(result["cases"]) is not list
        or len(result["cases"]) != len(contract["cases"])
    ):
        raise CandidateAcceptanceError("candidate_acceptance_worker_invalid")

    receipts: list[dict[str, Any]] = []
    overall = "passed"
    for expected_case, worker_case in zip(
        contract["cases"], result["cases"], strict=True
    ):
        row = _acceptance_exact(
            worker_case,
            {"case_id", "status", "actual_output", "error_code"},
            "candidate_acceptance_worker_invalid",
        )
        if row["case_id"] != expected_case.get("case_id"):
            raise CandidateAcceptanceError("candidate_acceptance_worker_invalid")
        if row["status"] == "failed":
            if (
                row["actual_output"] is not None
                or row["error_code"] != "candidate_case_execution_failed"
            ):
                raise CandidateAcceptanceError("candidate_acceptance_worker_invalid")
            status = "failed"
            actual_output = None
            failure_code = "candidate_case_execution_failed"
        elif row["status"] == "passed":
            if row["error_code"] is not None:
                raise CandidateAcceptanceError("candidate_acceptance_worker_invalid")
            actual_output = _acceptance_copy(row["actual_output"])
            if not data_contract_accepts(normalized_output, actual_output):
                status = "failed"
                actual_output = None
                failure_code = "candidate_output_contract_invalid"
            elif not _json_exact(actual_output, expected_case.get("expected_output")):
                status = "failed"
                failure_code = "candidate_output_mismatch"
            else:
                status = "passed"
                failure_code = None
        else:
            raise CandidateAcceptanceError("candidate_acceptance_worker_invalid")
        if status == "failed":
            overall = "failed"
        receipts.append(
            {
                "case_id": expected_case["case_id"],
                "status": status,
                "actual_output": actual_output,
                "failure_code": failure_code,
            }
        )

    receipt = {
        "schema_version": CANDIDATE_ACCEPTANCE_RECEIPT_VERSION,
        "contract_digest": contract["canonical_digest"],
        "candidate_content_digest": contract["candidate_content_digest"],
        "status": overall,
        "runtime_operational": "passed",
        "product_goal_conformance": overall,
        "cases": receipts,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    _acceptance_copy(receipt)
    return receipt


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
    *,
    verified_page_contracts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compile one fully capsule-backed confirmed plan into one composer request."""
    return _compile_plan_execution(
        plan,
        confirmation,
        capsules,
        execution_version=PLAN_EXECUTION_VERSION,
        parameter_binding=None,
        verified_page_contracts=verified_page_contracts,
    )


def compile_parameterized_plan_execution(
    plan: dict[str, Any],
    confirmation: dict[str, Any],
    capsules: list[dict[str, Any]],
    *,
    verified_page_contracts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compile one parameter-confirmed plan without changing the v1 contract."""
    if type(confirmation) is not dict:
        raise PlanExecutionError("plan_execution_confirmation_invalid")
    offer = build_parameterized_execution_offer(plan, capsules)
    if offer is None:
        raise PlanExecutionError("parameterized_execution_binding_required")
    binding = validate_parameterized_execution_binding(
        plan,
        confirmation.get("parameter_binding"),
        offer,
    )
    return _compile_plan_execution(
        plan,
        confirmation,
        capsules,
        execution_version=PARAMETERIZED_PLAN_EXECUTION_VERSION,
        parameter_binding=binding,
        verified_page_contracts=verified_page_contracts,
    )


def _compile_plan_execution(
    plan: dict[str, Any],
    confirmation: dict[str, Any],
    capsules: list[dict[str, Any]],
    *,
    execution_version: str,
    parameter_binding: dict[str, Any] | None,
    verified_page_contracts: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Shared exact compiler; the parameter-free branch preserves v1 bytes."""

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
    expected_confirmation_version = "product_plan_confirmation.v1"
    if parameter_binding is not None:
        confirmation_keys = {*confirmation_keys, "parameter_binding"}
        expected_confirmation_version = "product_plan_confirmation.v2"
    confirmation = _exact(
        confirmation,
        confirmation_keys,
        "plan_execution_confirmation_invalid",
    )
    confirmation_body = {
        key: value for key, value in confirmation.items() if key != "receipt_digest"
    }
    if (
        confirmation["schema_version"] != expected_confirmation_version
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
        or (
            parameter_binding is not None
            and confirmation.get("parameter_binding") != parameter_binding
        )
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
    try:
        page_contract.validate_formal_page_contract(
            selected,
            verified_page_contracts=verified_page_contracts,
        )
    except ValueError as exc:
        code = {
            "product_dom_contract_mismatch": "plan_execution_dom_contract_mismatch",
            "formal_page_contract_identity_invalid": (
                "plan_execution_page_contract_identity_invalid"
            ),
            "formal_page_contract_version_mismatch": (
                "plan_execution_page_contract_version_mismatch"
            ),
            "formal_page_contract_provider_missing": (
                "plan_execution_page_contract_provider_missing"
            ),
            "page_capability_element_missing": (
                "plan_execution_page_capability_element_missing"
            ),
            "page_capability_element_mismatch": (
                "plan_execution_page_capability_element_mismatch"
            ),
            "page_capability_event_missing": (
                "plan_execution_page_capability_event_missing"
            ),
            "page_capability_read_missing": (
                "plan_execution_page_capability_read_missing"
            ),
            "page_capability_write_missing": (
                "plan_execution_page_capability_write_missing"
            ),
        }.get(str(exc), "plan_execution_capsule_invalid")
        raise PlanExecutionError(code) from exc

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
    composition_facts = {
        "contract": execution_version,
        "plan_digest": plan["canonical_digest"],
        "confirmation_digest": confirmation["receipt_digest"],
        "capsules": capsule_identities,
    }
    if parameter_binding is not None:
        composition_facts["parameter_binding_digest"] = parameter_binding[
            "canonical_digest"
        ]
    composition_key = canonical_digest(composition_facts)
    execution = {
        "schema_version": execution_version,
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
    if parameter_binding is not None:
        execution["parameter_binding"] = parameter_binding
        execution["composer_request"]["parameter_binding_digest"] = (
            parameter_binding["canonical_digest"]
        )
    execution["execution_digest"] = canonical_digest(execution)
    return execution


__all__ = [
    "CANDIDATE_ACCEPTANCE_CONFIRMATION_VERSION",
    "CANDIDATE_ACCEPTANCE_RECEIPT_VERSION",
    "CANDIDATE_ACCEPTANCE_VERSION",
    "CANDIDATE_ACCEPTANCE_WORKER_VERSION",
    "MAX_CANDIDATE_ACCEPTANCE_CASES",
    "MAX_PARAMETERIZED_EXECUTION_BINDINGS",
    "PLAN_EXECUTION_VERSION",
    "PARAMETERIZED_EXECUTION_BINDING_VERSION",
    "PARAMETERIZED_EXECUTION_CONFIRMATION_VERSION",
    "PARAMETERIZED_EXECUTION_OFFER_VERSION",
    "PARAMETERIZED_PLAN_EXECUTION_VERSION",
    "CandidateAcceptanceError",
    "PlanExecutionError",
    "build_candidate_acceptance",
    "build_candidate_acceptance_confirmation",
    "build_parameterized_execution_binding",
    "build_parameterized_execution_offer",
    "canonical_bytes",
    "canonical_digest",
    "compile_plan_execution",
    "compile_parameterized_plan_execution",
    "evaluate_candidate_acceptance",
    "validate_candidate_acceptance_confirmation",
    "validate_parameterized_execution_binding",
]
