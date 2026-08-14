"""Local, review-only product planning with deterministic authority.

The model may describe requirements and suggest capsule references.  This module
owns every durable identity, exact capsule binding, dependency check, digest,
workspace write, revision, and confirmation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import socket
import stat
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from pimos_lite.reweave_canonical import (
    canonical_json_bytes,
    canonical_json_digest,
)
from pimos_lite.reweave_data_contract import (
    DataContractError,
    contracts_compatible,
    data_contract_accepts,
    normalize_capsule_contracts,
)
from pimos_lite.reweave_experience import (
    PROJECT_EXPERIENCE_MILESTONES,
    ExperienceError,
    build_product_experience_model_cases,
    build_product_experience_query,
    build_project_experience_record,
    build_project_experience_scope,
    validate_product_experience_query,
    validate_project_experience_record,
    validate_project_experience_scope,
)
from pimos_lite.reweave_plan_execution import (
    CANDIDATE_ACCEPTANCE_CONFIRMATION_VERSION,
    MAX_CANDIDATE_ACCEPTANCE_CASES,
    PlanExecutionError,
    build_parameterized_execution_binding,
    build_parameterized_execution_offer,
    validate_parameterized_execution_binding,
)


LEGACY_PLAN_SCHEMA_VERSION = "product_plan.v1"
PLAN_SCHEMA_VERSION = "product_plan.v2"
LEGACY_WORKSPACE_SCHEMA_VERSION = "product_workspace.v3"
DIRECT_BLUEPRINT_WORKSPACE_SCHEMA_VERSION = "product_workspace.v4"
LEGACY_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION = "product_workspace.v5"
PREVIOUS_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION = "product_workspace.v6"
PREVIOUS_GAP_WORKSPACE_SCHEMA_VERSION = "product_workspace.v7"
PREVIOUS_TARGET_SELECTION_WORKSPACE_SCHEMA_VERSION = "product_workspace.v8"
PREVIOUS_REQUIREMENT_COVERAGE_WORKSPACE_SCHEMA_VERSION = "product_workspace.v9"
WORKSPACE_SCHEMA_VERSION = "product_workspace.v10"
LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSIONS = frozenset(
    {
        LEGACY_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION,
        PREVIOUS_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION,
        PREVIOUS_GAP_WORKSPACE_SCHEMA_VERSION,
        PREVIOUS_TARGET_SELECTION_WORKSPACE_SCHEMA_VERSION,
        PREVIOUS_REQUIREMENT_COVERAGE_WORKSPACE_SCHEMA_VERSION,
        WORKSPACE_SCHEMA_VERSION,
    }
)
GAP_WORKSPACE_SCHEMA_VERSIONS = frozenset(
    {
        PREVIOUS_GAP_WORKSPACE_SCHEMA_VERSION,
        PREVIOUS_TARGET_SELECTION_WORKSPACE_SCHEMA_VERSION,
        PREVIOUS_REQUIREMENT_COVERAGE_WORKSPACE_SCHEMA_VERSION,
        WORKSPACE_SCHEMA_VERSION,
    }
)
TARGET_SELECTION_WORKSPACE_SCHEMA_VERSIONS = frozenset(
    {
        PREVIOUS_TARGET_SELECTION_WORKSPACE_SCHEMA_VERSION,
        PREVIOUS_REQUIREMENT_COVERAGE_WORKSPACE_SCHEMA_VERSION,
        WORKSPACE_SCHEMA_VERSION,
    }
)
EXPERIENCE_WORKSPACE_SCHEMA_VERSIONS = frozenset({WORKSPACE_SCHEMA_VERSION})
MODEL_SELECTION_SCHEMA_VERSION = "product_planning_model_selection.v1"
SECTION_DRAFT_SCHEMA_VERSION = "product_plan_section_draft.v2"
SECTION_CHECKPOINT_SCHEMA_VERSION = "product_plan_section_checkpoint.v2"
LEGACY_PLANNING_RULES_VERSION = "reweave_product_planning_rules.v2"
SECTION_PLANNING_RULES_VERSION = "reweave_product_planning_rules.v3"
LEGACY_BLUEPRINT_PLANNING_RULES_VERSION = "reweave_product_planning_rules.v4"
DIRECT_BLUEPRINT_PLANNING_RULES_VERSION = "reweave_product_planning_rules.v5"
PREVIOUS_LOCKED_BLUEPRINT_PLANNING_RULES_VERSION = (
    "reweave_product_planning_rules.v6"
)
PREVIOUS_GAP_PLANNING_RULES_VERSION = "reweave_product_planning_rules.v7"
PREVIOUS_TARGET_SELECTION_PLANNING_RULES_VERSION = (
    "reweave_product_planning_rules.v8"
)
PREVIOUS_REQUIREMENT_COVERAGE_PLANNING_RULES_VERSION = (
    "reweave_product_planning_rules.v9"
)
PLANNING_RULES_VERSION = "reweave_product_planning_rules.v10"
SUPPORTED_PLANNING_RULES_VERSIONS = frozenset(
    {
        LEGACY_PLANNING_RULES_VERSION,
        SECTION_PLANNING_RULES_VERSION,
        LEGACY_BLUEPRINT_PLANNING_RULES_VERSION,
        DIRECT_BLUEPRINT_PLANNING_RULES_VERSION,
        PREVIOUS_LOCKED_BLUEPRINT_PLANNING_RULES_VERSION,
        PREVIOUS_GAP_PLANNING_RULES_VERSION,
        PREVIOUS_TARGET_SELECTION_PLANNING_RULES_VERSION,
        PREVIOUS_REQUIREMENT_COVERAGE_PLANNING_RULES_VERSION,
        PLANNING_RULES_VERSION,
    }
)
HISTORICAL_PLANNING_PROMPT_VERSION = "reweave_product_planning_prompt.v5"
LEGACY_PLANNING_PROMPT_VERSION = "reweave_product_planning_prompt.v6"
LEGACY_BLUEPRINT_PROMPT_VERSION = "reweave_product_planning_prompt.v7"
DIRECT_BLUEPRINT_PROMPT_VERSION = "reweave_product_planning_prompt.v8"
LEGACY_LOCKED_BLUEPRINT_PROMPT_VERSION = "reweave_product_planning_prompt.v9"
PREVIOUS_LOCKED_BLUEPRINT_PROMPT_VERSION = "reweave_product_planning_prompt.v10"
PREVIOUS_GAP_PLANNING_PROMPT_VERSION = "reweave_product_planning_prompt.v11"
PREVIOUS_REQUIREMENT_COVERAGE_PROMPT_VERSION = (
    "reweave_product_planning_prompt.v12"
)
PLANNING_PROMPT_VERSION = "reweave_product_planning_prompt.v13"
ACTION_SUGGESTION_PROMPT_VERSION = "product_plan_action_suggestion_prompt.v1"
ACTION_SUGGESTION_SCHEMA_VERSION = "product_plan_action_suggestion.v1"
REVISION_PROMPT_VERSIONS = {
    "plan_revision": "product_plan_revision_prompt.v1",
    "plan_revision_intent": "product_plan_revision_intent_prompt.v2",
    "plan_revision_explanation": "product_plan_revision_explanation_prompt.v1",
    "plan_revision_change": "product_plan_revision_change_prompt.v1",
    "plan_revision_modification": "product_plan_revision_modification_prompt.v2",
    "plan_revision_needs_clarification": (
        "product_plan_revision_clarification_prompt.v1"
    ),
    "plan_revision_proposal": "product_plan_revision_proposal_prompt.v2",
    "plan_revision_fields": "product_plan_revision_fields_prompt.v1",
}
REVISION_SCHEMA_VERSIONS = {
    "plan_revision": "product_plan_revision.v1",
    "plan_revision_intent": "product_plan_revision_intent.v2",
    "plan_revision_explanation": "product_plan_revision_explanation.v1",
    "plan_revision_change": "product_plan_revision_change.v1",
    "plan_revision_modification": "product_plan_revision_modification.v3",
    "plan_revision_needs_clarification": "product_plan_revision_clarification.v1",
    "plan_revision_proposal": "product_plan_revision_proposal.v3",
    "plan_revision_fields": "product_plan_revision_fields.v1",
}
SECTION_IDS = ("frontend", "backend", "data", "infrastructure")
PRODUCT_PLANNING_PHASES = frozenset(
    {
        "model_probe",
        "requirements_outline",
        "composition_selection",
        "product_blueprint",
        *SECTION_IDS,
        "catalog_match",
        "validation",
        "revision",
    }
)
MAX_MODEL_PARAMETERS = 15_000_000_000
MAX_HTTP_REQUEST_BYTES = 256 * 1024
MAX_HTTP_RESPONSE_BYTES = 1024 * 1024
MAX_WORKSPACE_BYTES = 4 * 1024 * 1024
MAX_GOAL_CHARS = 4_000
MAX_FEEDBACK_CHARS = 2_000
CATALOG_BATCH_SIZE = 16
HTTP_TIMEOUT_SECONDS = 45
FORMAL_MODEL_TIMEOUT_SECONDS = 180
EXPERIENCE_INJECTION_DEFAULT = True
CAPABILITY_GAP_PROJECTION_VERSION = "capability_gap_projection.v1"
CAPABILITY_GAP_PROJECTION_V2 = "capability_gap_projection.v2"
CAPABILITY_GAP_DECISION_VERSION = "capability_gap_decision.v1"
CAPABILITY_GAP_TARGET_SELECTION_VERSION = (
    "product_capability_gap_target_selection.v1"
)
CAPABILITY_SOURCE_PROPOSAL_AUTHORIZATION_VERSION = (
    "capability_source_proposal_authorization.v1"
)
CAPABILITY_SOURCE_PROPOSAL_AUTHORIZATION_V2 = (
    "capability_source_proposal_authorization.v2"
)
CAPABILITY_SOURCE_PROPOSAL_REQUEST_VERSION = (
    "capability_source_proposal_request.v1"
)
CAPABILITY_SOURCE_PROPOSAL_PROMPT_VERSION = (
    "capability_source_proposal_prompt.v1"
)
CAPABILITY_SOURCE_PROPOSAL_REQUEST_V2 = (
    "capability_source_proposal_request.v2"
)
CAPABILITY_SOURCE_PROPOSAL_PROMPT_V2 = (
    "capability_source_proposal_prompt.v2"
)
CAPABILITY_SOURCE_PROPOSAL_REQUEST_V3 = (
    "capability_source_proposal_request.v3"
)
CAPABILITY_SOURCE_PROPOSAL_PROMPT_V3 = (
    "capability_source_proposal_prompt.v3"
)
CAPABILITY_SOURCE_PROPOSAL_REQUEST_V4 = (
    "capability_source_proposal_request.v4"
)
CAPABILITY_SOURCE_PROPOSAL_PROMPT_V4 = (
    "capability_source_proposal_prompt.v4"
)
CAPABILITY_SOURCE_FUNCTION_ABI_VERSION = (
    "capability_source_function_abi.v1"
)
CAPABILITY_SOURCE_FUNCTION_ABI_V2 = "capability_source_function_abi.v2"
CAPABILITY_SOURCE_PROPOSAL_OUTPUT_VERSION = "capability_source_proposal.v1"
CAPABILITY_SOURCE_PROPOSAL_OUTPUT_V2 = "capability_source_proposal.v2"
CAPABILITY_SOURCE_PROPOSAL_MAX_BYTES = 4_096
CAPABILITY_SOURCE_PROPOSAL_RUN_VERSION = (
    "capability_source_proposal_run.v1"
)
CAPABILITY_SOURCE_PROPOSAL_RUN_EVENT_VERSION = (
    "capability_source_proposal_run_event.v1"
)
CAPABILITY_SOURCE_PROPOSAL_RUN_STATUSES = frozenset(
    {"pending", "running", "review_required", "failed", "cancelled"}
)
CAPABILITY_SOURCE_PROPOSAL_RUN_STAGES = (
    "source_proposal",
    "intake",
    "security",
    "runtime",
    "supervision",
    "admission",
)
MAX_CAPABILITY_GAP_DECISIONS = 128
CAPABILITY_REPLAN_HANDOFF_VERSION = "capability_replan_handoff.v1"
CAPABILITY_REPLAN_OFFER_VERSION = "product_capability_replan_offer.v1"

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_WORKSPACE_ID = re.compile(r"workspace_[0-9a-f]{32}\Z")
_PLAN_TOKEN = re.compile(r"plan_token_[0-9a-f]{48}\Z")
_HANDOFF_TOKEN = re.compile(r"handoff_token_[0-9a-f]{48}\Z")
_GAP_ID = re.compile(r"gap_[0-9a-f]{20}\Z")
_GAP_DECISION_FILENAME = re.compile(
    r"decision_([0-9]{6})_([0-9a-f]{64})\.json\Z"
)
_SOURCE_PROPOSAL_RUN_ID = re.compile(r"run_[0-9a-f]{32}\Z")
_SOURCE_PROPOSAL_RUN_EVENT_FILENAME = re.compile(
    r"event_([0-9]{6})_([0-9a-f]{64})\.json\Z"
)
_CAPABILITY_REPLAN_HANDOFF_FILENAME = re.compile(
    r"handoff_([0-9a-f]{64})\.json\Z"
)
_SUGGESTION_RECEIPT = re.compile(r"suggestion_receipt_[0-9a-f]{48}\Z")
_SAFE_REF = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,95}\Z")
_RUNNING_STATES = frozenset({"model_probe", "planning"})
_SENSITIVE_QUESTION = re.compile(
    r"password|passcode|token|api[ _-]?key|secret|private key|absolute path|"
    r"密码|口令|令牌|密钥|绝对路径",
    re.IGNORECASE,
)
_ABSENCE_CONSTRAINT = re.compile(
    r"(?:不使用|不需要|无需|不得|禁止|不依赖|"
    r"无(?:网络|登录|数据库|部署)|"
    r"\boffline\b|\blocal[- ]only\b|\bwithout\b|"
    r"\bno (?:network|login|database|deployment)\b)",
    re.IGNORECASE,
)


def _schema_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _question_schema() -> dict[str, Any]:
    option = _schema_object(
        {
            "ref": {"type": "string"},
            "label": {"type": "string"},
            "impact": {"type": "string"},
            "recommended": {"type": "boolean"},
            "forms_gap": {"type": "boolean"},
        }
    )
    return _schema_object(
        {
            "ref": {"type": "string"},
            "prompt": {"type": "string"},
            "options": {
                "type": "array",
                "items": option,
                "minItems": 2,
                "maxItems": 3,
            },
            "allow_custom": {"type": "boolean", "enum": [True]},
        }
    )


def _structured_output_schema(
    call_type: str,
    request_value: dict[str, Any],
    *,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    prompt_version = prompt_version or PLANNING_PROMPT_VERSION
    if call_type == "schema_probe":
        return _schema_object(
            {
                "schema_version": {
                    "type": "string",
                    "enum": ["product_plan_probe.v1"],
                },
                "status": {"type": "string", "enum": ["ready"]},
                "role": {"type": "string", "enum": ["product_planner"]},
            }
        )
    if call_type == "requirements_outline":
        requirement = _schema_object(
            {
                "ref": {"type": "string"},
                "statement": {"type": "string"},
                "source": {
                    "type": "string",
                    "enum": ["goal", "planning_answer"],
                },
            }
        )
        return _schema_object(
            {
                "schema_version": {
                    "type": "string",
                    "enum": ["product_plan_outline.v1"],
                },
                "product_name": {"type": "string"},
                "language": {"type": "string", "enum": ["zh", "en"]},
                "requirements": {
                    "type": "array",
                    "items": requirement,
                    "minItems": 1,
                    "maxItems": 64,
                },
                "needs_clarification": {"type": "boolean"},
                "questions": {
                    "type": "array",
                    "items": _question_schema(),
                    "maxItems": 3,
                },
            }
        )
    if call_type == "composition_selection":
        composition_offers = request_value.get("composition_offers")
        selection_locked = request_value.get("selection_locked") is True
        if type(composition_offers) is not list:
            raise ProductPlanningError("product_plan_call_type_invalid")
        capability_keys = [
            offer.get("capability_key")
            for offer in composition_offers
            if type(offer) is dict
        ]
        if (
            len(capability_keys) != len(composition_offers)
            or any(type(key) is not str or not key for key in capability_keys)
            or (
                selection_locked
                and len(set(capability_keys)) != 1
            )
        ):
            raise ProductPlanningError("product_plan_call_type_invalid")
        return _schema_object(
            {
                "schema_version": {
                    "type": "string",
                    "enum": ["product_composition_selection.v1"],
                },
                "capability_key": {
                    "type": "string",
                    "enum": (
                        sorted(set(capability_keys))
                        if selection_locked
                        else [*sorted(set(capability_keys)), ""]
                    ),
                },
            }
        )
    if call_type == "product_blueprint":
        requirements = request_value.get("requirements")
        composition_offers = request_value.get("composition_offers")
        selection_locked = request_value.get("selection_locked") is True
        capability_gap_lock = request_value.get("capability_gap_lock")
        gap_locked = capability_gap_lock is not None
        if type(requirements) is not list or type(composition_offers) is not list:
            raise ProductPlanningError("product_plan_call_type_invalid")
        if gap_locked and (
            type(capability_gap_lock) is not dict
            or set(capability_gap_lock)
            != {
                "schema_version",
                "capability_key",
                "capability_group_display_name",
                "capability_kind",
                "slot",
                "adapter_contract_version",
                "input_fields",
                "output_fields",
                "existing_members",
            }
            or capability_gap_lock.get("schema_version")
            not in {
                "product_capability_gap_blueprint_lock.v1",
                "product_capability_gap_blueprint_lock.v2",
            }
            or (
                capability_gap_lock.get("schema_version")
                == "product_capability_gap_blueprint_lock.v1"
                and capability_gap_lock.get("adapter_contract_version")
                not in {"computation_adapter.v2", "computation_adapter.v3"}
            )
            or (
                capability_gap_lock.get("schema_version")
                == "product_capability_gap_blueprint_lock.v2"
                and capability_gap_lock.get("adapter_contract_version")
                != "computation_adapter.v4"
            )
            or capability_gap_lock.get("capability_kind") != "computation"
            or not selection_locked
            or composition_offers
        ):
            raise ProductPlanningError("product_plan_call_type_invalid")
        requirement_refs = [
            item.get("ref")
            for item in requirements
            if type(item) is dict and type(item.get("ref")) is str
        ]
        offer_refs: list[str] = []
        offer_members: list[list[str]] = []
        for offer in sorted(
            composition_offers,
            key=lambda item: (
                str(item.get("offer_ref")) if type(item) is dict else ""
            ),
        ):
            if (
                type(offer) is not dict
                or type(offer.get("offer_ref")) is not str
                or type(offer.get("members")) is not list
            ):
                raise ProductPlanningError("product_plan_call_type_invalid")
            members = [
                item.get("candidate_ref")
                for item in offer["members"]
                if type(item) is dict
                and type(item.get("candidate_ref")) is str
            ]
            if (
                len(members) != len(offer["members"])
                or not members
                or len(set(members)) != len(members)
            ):
                raise ProductPlanningError("product_plan_call_type_invalid")
            offer_refs.append(offer["offer_ref"])
            offer_members.append(members)
        if (
            not requirement_refs
            or len(requirement_refs) != len(requirements)
            or len(set(requirement_refs)) != len(requirement_refs)
            or len(set(offer_refs)) != len(offer_refs)
            or "" in offer_refs
        ):
            raise ProductPlanningError("product_plan_call_type_invalid")
        sections = {
            section_id: _schema_object(
                {
                    "applicability": {
                        "type": "string",
                        "enum": (
                            [
                                "applicable"
                                if section_id == "backend"
                                else "not_applicable"
                            ]
                            if gap_locked
                            else ["applicable", "not_applicable"]
                        ),
                    },
                    "summary": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                    },
                }
            )
            for section_id in SECTION_IDS
        }
        assignment = _schema_object(
            {
                "section_id": {"type": "string", "enum": list(SECTION_IDS)},
                "requirement_refs": {
                    "type": "array",
                    "items": {"type": "string", "enum": requirement_refs},
                    "minItems": 1,
                    "uniqueItems": True,
                },
                "title": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 180,
                },
                "summary": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 800,
                },
                "acceptance_intent": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                },
            }
        )
        gap = _schema_object(
            {
                **(
                    {}
                    if gap_locked
                    else {
                        "section_id": {
                            "type": "string",
                            "enum": list(SECTION_IDS),
                        },
                        "requirement_refs": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": requirement_refs,
                            },
                            "minItems": 1,
                            "uniqueItems": True,
                        },
                    }
                ),
                "title": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 180,
                },
                "reason": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                },
            }
        )
        selection_options = [
            _schema_object(
                {
                    "offer_ref": {"type": "string", "enum": [offer_ref]},
                    "assignments": _schema_object(
                        {candidate_ref: assignment for candidate_ref in members}
                    ),
                }
            )
            for offer_ref, members in zip(
                offer_refs,
                offer_members,
                strict=True,
            )
        ]
        if not selection_locked or not selection_options:
            selection_options.append(
                _schema_object(
                    {
                        "offer_ref": {"type": "string", "enum": [""]},
                        "assignments": _schema_object({}),
                    }
                )
            )
        return _schema_object(
            {
                "schema_version": {
                    "type": "string",
                    "enum": ["product_plan_blueprint.v2"],
                },
                "sections": _schema_object(sections),
                "selection": {"oneOf": selection_options},
                "gaps": {
                    "type": "array",
                    "items": gap,
                    **(
                        {"minItems": 1, "maxItems": 1}
                        if gap_locked
                        else (
                            {"maxItems": 0}
                            if (
                                selection_locked
                                and selection_options
                                and prompt_version
                                in {
                                    PREVIOUS_REQUIREMENT_COVERAGE_PROMPT_VERSION,
                                    PLANNING_PROMPT_VERSION,
                                }
                            )
                            else {"maxItems": 64}
                        )
                    ),
                },
            }
        )
    if call_type.startswith("section_"):
        section_id = str(request_value.get("section_id") or "")
        requirements = request_value.get("requirements")
        candidate_catalog = request_value.get("candidate_catalog")
        if (
            section_id not in SECTION_IDS
            or type(requirements) is not list
            or type(candidate_catalog) is not list
        ):
            raise ProductPlanningError("product_plan_call_type_invalid")
        requirement_refs = [
            item.get("ref")
            for item in requirements
            if type(item) is dict and type(item.get("ref")) is str
        ]
        candidate_refs = [
            item.get("candidate_ref")
            for item in candidate_catalog
            if type(item) is dict and type(item.get("candidate_ref")) is str
        ]
        if (
            not requirement_refs
            or len(requirement_refs) != len(requirements)
            or len(set(requirement_refs)) != len(requirement_refs)
            or len(candidate_refs) != len(candidate_catalog)
            or len(set(candidate_refs)) != len(candidate_refs)
            or "" in candidate_refs
        ):
            raise ProductPlanningError("product_plan_call_type_invalid")
        work_item = _schema_object(
            {
                "title": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 180,
                },
                "summary": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 800,
                },
                "requirement_refs": {
                    "type": "array",
                    "items": {"type": "string", "enum": requirement_refs},
                    "minItems": 1,
                    "uniqueItems": True,
                },
                "delivery_wave": {"type": "integer", "enum": [1, 2, 3, 4]},
                "acceptance_intent": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                },
                "candidate_ref": {
                    "type": "string",
                    "enum": ["", *candidate_refs],
                },
                "gap_reason": {
                    "type": "string",
                    "minLength": 0,
                    "maxLength": 500,
                },
            }
        )
        return _schema_object(
            {
                "schema_version": {
                    "type": "string",
                    "enum": [SECTION_DRAFT_SCHEMA_VERSION],
                },
                "section_id": {"type": "string", "enum": [section_id]},
                "summary": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                },
                "work_items": {
                    "type": "array",
                    "items": work_item,
                    "minItems": 1,
                    "maxItems": 48,
                },
            }
        )
    if call_type.startswith("catalog_match_"):
        section_id = str(request_value.get("section_id") or "")
        if section_id not in SECTION_IDS:
            raise ProductPlanningError("product_plan_call_type_invalid")
        match = _schema_object(
            {
                "work_item_ref": {"type": "string"},
                "candidate_ref": {"type": "string"},
                "reason": {"type": "string"},
            }
        )
        return _schema_object(
            {
                "schema_version": {
                    "type": "string",
                    "enum": ["product_plan_match.v1"],
                },
                "section_id": {"type": "string", "enum": [section_id]},
                "matches": {"type": "array", "items": match},
            }
        )
    if call_type == "plan_action_suggestion":
        return _schema_object(
            {
                "suggested_action": {
                    "type": "string",
                    "enum": ["ask_plan", "propose_revision", "edit_goal"],
                }
            }
        )
    if call_type == "plan_revision_intent":
        return _schema_object(
            {
                "intent": {
                    "type": "string",
                    "enum": ["explanation", "change"],
                }
            }
        )
    if call_type == "plan_revision_explanation":
        return _schema_object({"explanation": {"type": "string"}})
    if call_type == "plan_revision_fields":
        return _schema_object(
            {
                "title": {"type": "string", "minLength": 1, "maxLength": 180},
                "summary": {"type": "string", "minLength": 1, "maxLength": 800},
                "acceptance_intent": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                },
                "delivery_wave": {"type": "integer", "enum": [1, 2, 3, 4]},
            }
        )
    if call_type in {
        "plan_revision",
        "plan_revision_change",
        "plan_revision_modification",
        "plan_revision_proposal",
    }:
        current_plan = request_value.get("current_plan")
        if type(current_plan) is not dict:
            raise ProductPlanningError("product_plan_call_type_invalid")
        requirements = current_plan.get("requirements")
        sections = current_plan.get("sections")
        if type(requirements) is not list or type(sections) is not list:
            raise ProductPlanningError("product_plan_call_type_invalid")
        requirement_refs = [
            item.get("requirement_ref")
            for item in requirements
            if type(item) is dict and type(item.get("requirement_ref")) is str
        ]
        binding_refs = [
            item.get("binding_ref")
            for section in sections
            if type(section) is dict and section.get("section_id") in SECTION_IDS
            for item in section.get("work_items", [])
            if type(item) is dict and type(item.get("binding_ref")) is str
        ]
        if (
            len(requirement_refs) != len(requirements)
            or len(set(requirement_refs)) != len(requirement_refs)
        ):
            raise ProductPlanningError("product_plan_call_type_invalid")
        target_section_id: str | None = None
        if call_type == "plan_revision_proposal":
            target_section_id = request_value.get("target_section_id")
            target_sections = [
                section
                for section in sections
                if type(section) is dict
                and section.get("section_id") == target_section_id
            ]
            if (
                type(target_section_id) is not str
                or target_section_id not in SECTION_IDS
                or len(target_sections) != 1
            ):
                raise ProductPlanningError("product_plan_call_type_invalid")
            target_section = target_sections[0]
            binding_refs = [
                item.get("binding_ref")
                for item in target_section.get("work_items", [])
                if type(item) is dict and type(item.get("binding_ref")) is str
            ]
            allowed_requirement_refs = {
                ref
                for item in target_section.get("work_items", [])
                if type(item) is dict
                for ref in item.get("requirement_refs", [])
                if type(ref) is str
            } | {
                ref
                for gap in target_section.get("gaps", [])
                if type(gap) is dict
                for ref in gap.get("requirement_refs", [])
                if type(ref) is str
            }
            requirement_refs = [
                ref for ref in requirement_refs if ref in allowed_requirement_refs
            ]
        if len(set(binding_refs)) != len(binding_refs):
            raise ProductPlanningError("product_plan_call_type_invalid")
        update_properties = {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "acceptance_intent": {"type": "string"},
            "delivery_wave": {"type": "integer", "enum": [1, 2, 3, 4]},
        }
        add_operation = _schema_object(
            {
                "op": {"type": "string", "enum": ["add"]},
                "section_id": {
                    "type": "string",
                    "enum": (
                        [target_section_id]
                        if target_section_id is not None
                        else list(SECTION_IDS)
                    ),
                },
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "requirement_refs": {
                    "type": "array",
                    "items": {"type": "string", "enum": requirement_refs},
                    "minItems": 1,
                    "uniqueItems": True,
                },
                "delivery_wave": {"type": "integer", "enum": [1, 2, 3, 4]},
                "acceptance_intent": {"type": "string"},
            }
        )
        update_operations = [
            {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["update"]},
                    "binding_ref": {"type": "string", "enum": [binding_ref]},
                    **update_properties,
                },
                "required": ["op", "binding_ref"],
                "additionalProperties": False,
                "minProperties": 3,
            }
            for binding_ref in binding_refs
        ]
        remove_operations = [
            _schema_object(
                {
                    "op": {"type": "string", "enum": ["remove"]},
                    "binding_ref": {"type": "string", "enum": [binding_ref]},
                }
            )
            for binding_ref in binding_refs
        ]
        operations = {
            "type": "array",
            "items": {
                "oneOf": [
                    add_operation,
                    *update_operations,
                    *remove_operations,
                ]
            },
            "minItems": 1,
            "maxItems": 16,
        }
        if call_type == "plan_revision_modification":
            return _schema_object({"operations": operations})
        if call_type == "plan_revision":
            return {
                "oneOf": [
                    _schema_object({"explanation": {"type": "string"}}),
                    _schema_object(
                        {
                            "explanation": {"type": "string"},
                            "questions": {
                                "type": "array",
                                "items": _question_schema(),
                                "minItems": 1,
                                "maxItems": 3,
                            },
                        }
                    ),
                    _schema_object({"operations": operations}),
                ]
            }
        if call_type == "plan_revision_proposal":
            return _schema_object({"operations": operations})
        return {
            "oneOf": [
                _schema_object(
                    {
                        "outcome": {
                            "type": "string",
                            "enum": ["modification"],
                        },
                        "operations": operations,
                    }
                ),
                _schema_object(
                    {
                        "outcome": {
                            "type": "string",
                            "enum": ["needs_clarification"],
                        },
                        "questions": {
                            "type": "array",
                            "items": _question_schema(),
                            "minItems": 1,
                            "maxItems": 3,
                        },
                    }
                ),
            ]
        }
    if call_type == "plan_revision_needs_clarification":
        return _schema_object(
            {
                "questions": {
                    "type": "array",
                    "items": _question_schema(),
                    "minItems": 1,
                    "maxItems": 3,
                }
            }
        )
    raise ProductPlanningError("product_plan_call_type_invalid")


class ProductPlanningError(RuntimeError):
    def __init__(self, code: str, rule_code: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.rule_code = rule_code


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _canonical_bytes(value: Any) -> bytes:
    try:
        return canonical_json_bytes(value)
    except (TypeError, ValueError) as exc:
        raise ProductPlanningError("product_plan_json_invalid") from exc


def _digest(value: Any) -> str:
    try:
        return canonical_json_digest(value)
    except (TypeError, ValueError) as exc:
        raise ProductPlanningError("product_plan_json_invalid") from exc


def _strict_json(raw: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def constant(_value: str) -> None:
        raise ValueError("non_finite_json_number")

    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=pairs,
        parse_constant=constant,
    )


def _loopback_base(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ProductPlanningError("ollama_loopback_required")
    try:
        parsed.port
    except ValueError as exc:
        raise ProductPlanningError("ollama_address_invalid") from exc
    return value.rstrip("/")


def _error(code: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "error": {"code": code, "message_key": code},
    }
    if data is not None:
        result["data"] = data
    return result


def _ok(data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": True, "data": data or {}}


def _public_call(method: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def wrapped(self: "ProductPlanner", *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return method(self, *args, **kwargs)
        except ProductPlanningError as exc:
            return _error(exc.code)
        except (OSError, TypeError, UnicodeError, ValueError, json.JSONDecodeError):
            return _error("product_planning_state_unavailable")

    return wrapped


def _safe_text(
    value: Any,
    *,
    minimum: int = 1,
    maximum: int = 1_000,
    rule_code: str | None = None,
) -> str:
    if type(value) is not str or value != value.strip() or not minimum <= len(value) <= maximum:
        raise ProductPlanningError("product_plan_response_invalid", rule_code)
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ProductPlanningError("product_plan_response_invalid", rule_code)
    return value


def _exact_dict(
    value: Any,
    keys: set[str],
    rule_code: str | None = None,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ProductPlanningError("product_plan_response_invalid", rule_code)
    return value


def _stored_exact(
    value: Any,
    keys: set[str],
    rule_code: str | None = None,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ProductPlanningError("product_workspace_corrupt", rule_code)
    return value


class ProductPlanner:
    """One local planner role and one small application-state workspace area."""

    def __init__(
        self,
        state_root: str | Path,
        ollama_base_url: str = "http://127.0.0.1:11434",
        *,
        experience_injection_enabled: bool | None = None,
    ) -> None:
        if (
            experience_injection_enabled is not None
            and type(experience_injection_enabled) is not bool
        ):
            raise TypeError("experience_injection_enabled must be bool or None")
        root = Path(os.path.abspath(os.path.expanduser(str(state_root))))
        # macOS exposes /var and /tmp as stable system aliases into /private.
        # Normalize only those platform aliases; all user-controlled components
        # remain lexical so the no-symlink walk can reject them.
        for alias in (Path("/var"), Path("/tmp")):
            try:
                relative = root.relative_to(alias)
            except ValueError:
                continue
            resolved_alias = alias.resolve(strict=True)
            if resolved_alias != alias:
                root = resolved_alias / relative
            break
        self.root = root
        self.base_url = _loopback_base(ollama_base_url)
        self._experience_injection_enabled = (
            EXPERIENCE_INJECTION_DEFAULT
            if experience_injection_enabled is None
            else experience_injection_enabled
        )
        self._lock = threading.RLock()
        self._action_suggestions: dict[str, dict[str, Any]] = {}

    @_public_call
    def list_models(self) -> dict[str, Any]:
        models = self._available_models()
        selected: dict[str, Any] | None = None
        try:
            selected = self._selected_model(check_current=False)
        except ProductPlanningError:
            selected = None
        return _ok(
            {
                "models": models,
                "selected": (
                    {
                        key: selected[key]
                        for key in ("name", "digest", "parameter_count", "parameter_size")
                    }
                    if selected
                    else None
                ),
                "max_parameter_count": MAX_MODEL_PARAMETERS,
            }
        )

    @_public_call
    def initial_state(self) -> dict[str, Any]:
        selected: dict[str, Any] | None = None
        try:
            current = self._selected_model(check_current=False)
            selected = {
                key: current[key]
                for key in ("name", "digest", "parameter_count", "parameter_size")
            }
        except ProductPlanningError:
            selected = None
        return _ok(
            {
                "schema_version": "product_planning_state.v1",
                "available": True,
                "selected_model": selected,
                "workspaces": [self._summary(item) for item in self._workspaces()],
                "candidate_generation_available": False,
                "product_generation_performed": False,
            }
        )

    @_public_call
    def select_model(
        self,
        name: str,
        digest: str,
        phase_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        if (
            type(name) is not str
            or not name
            or name != name.strip()
            or type(digest) is not str
            or _DIGEST.fullmatch(digest) is None
        ):
            raise ProductPlanningError("product_planning_model_required")
        match = next(
            (
                row
                for row in self._available_models()
                if row["name"] == name and row["digest"] == digest
            ),
            None,
        )
        if match is None:
            raise ProductPlanningError("product_planning_model_not_available")
        if match["eligible_small_model"] is not True:
            if match["eligibility_reason"] == "mixture_of_experts_not_allowed":
                raise ProductPlanningError("product_planning_model_moe_not_allowed")
            raise ProductPlanningError("product_planning_model_too_large")
        self._report_phase("model_probe", phase_callback)
        probe = self._probe(match)
        selected = {
            "schema_version": MODEL_SELECTION_SCHEMA_VERSION,
            "base_url": self.base_url,
            "name": name,
            "digest": digest,
            "parameter_count": match["parameter_count"],
            "parameter_size": match["parameter_size"],
            "selected_at": _now(),
            "probe": probe,
        }
        with self._lock:
            self._atomic_write(self.root / "model_selection.json", selected)
        return _ok(
            {
                "model": {
                    key: selected[key]
                    for key in (
                        "name",
                        "digest",
                        "parameter_count",
                        "parameter_size",
                        "selected_at",
                    )
                },
                "probe": probe,
            }
        )

    @_public_call
    def start(
        self,
        goal: str,
        catalog: dict[str, Any],
        cancel_check: Callable[[], bool] | None = None,
        *,
        resume_plan_token: str | None = None,
        phase_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        goal = _safe_text(goal, maximum=MAX_GOAL_CHARS)
        normalized_catalog = self._catalog(catalog)
        workspace: dict[str, Any] | None = None
        if resume_plan_token is not None:
            previous = self._workspace_by_token(resume_plan_token)
            if (
                previous["status"] in {"failed", "interrupted"}
                and previous["goal"] == goal
                and previous.get("plan") is None
            ):
                workspace = previous
            else:
                self._abandon_workspace(previous)

        model = self._selected_model(check_current=False)
        if workspace is not None and workspace["model"] != self._model_identity(model):
            return self._planning_error(
                workspace,
                ProductPlanningError("product_plan_resume_input_changed"),
            )
        if workspace is None:
            workspace = self._new_workspace(goal, model)
        else:
            workspace["status"] = "model_probe"
            workspace["phase"] = "model_probe"
            workspace["failure_code"] = None
            workspace["updated_at"] = _now()
        with self._lock:
            self._save_workspace(workspace)
        try:
            self._report_phase("model_probe", phase_callback)
            current = self._selected_model(
                check_current=True,
                cancel_check=cancel_check,
            )
            if self._model_identity(current) != workspace["model"]:
                raise ProductPlanningError("product_plan_resume_input_changed")
            return self._continue_initial_planning(
                workspace,
                normalized_catalog,
                cancel_check,
                phase_callback,
            )
        except ProductPlanningError as exc:
            return self._planning_error(workspace, exc)

    @_public_call
    def start_capability_replan(
        self,
        plan_token: str,
        plan_digest: str,
        projection_digest: str,
        binding: dict[str, Any] | None,
        catalog: dict[str, Any],
        cancel_check: Callable[[], bool] | None = None,
        *,
        phase_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        if (
            type(plan_token) is not str
            or _PLAN_TOKEN.fullmatch(plan_token) is None
            or type(plan_digest) is not str
            or _DIGEST.fullmatch(plan_digest) is None
            or type(projection_digest) is not str
            or _DIGEST.fullmatch(projection_digest) is None
        ):
            raise ProductPlanningError("capability_replan_unavailable")
        normalized_catalog = self._catalog(catalog)
        source = self._workspace_by_token(plan_token)
        request = {
            "plan_token": plan_token,
            "plan_digest": plan_digest,
            "projection_digest": projection_digest,
        }
        request_digest = _digest(request)
        existing = self._read_capability_replan_handoff(source)
        if existing is not None:
            if existing["request_digest"] != request_digest:
                raise ProductPlanningError(
                    "capability_replan_handoff_conflict"
                )
            self._validate_capability_replan_current(
                existing,
                normalized_catalog,
            )
            successor = self._successor_workspace_from_handoff(existing)
            return _ok(
                self._workspace_projection(successor, normalized_catalog)
            )
        if binding is None:
            raise ProductPlanningError("capability_replan_unavailable")

        plan = source.get("plan")
        projection = self._read_capability_gap_projection(source)
        if (
            source.get("status") != "plan_review"
            or type(plan) is not dict
            or plan.get("canonical_digest") != plan_digest
            or projection is None
            or projection["projection_digest"] != projection_digest
        ):
            raise ProductPlanningError("capability_replan_unavailable")
        decisions = self._capability_gap_decisions(source, projection)
        decision = decisions[-1] if decisions else None
        authorization = (
            self._read_capability_source_proposal_authorization(
                source,
                projection,
                decision,
            )
            if type(decision) is dict
            and decision.get("decision") == "authorize"
            else None
        )
        if authorization is None:
            raise ProductPlanningError("capability_replan_unavailable")
        binding = self._validate_capability_replan_binding(
            binding,
            projection,
            decision,
            authorization,
        )
        selected_model = self._model_identity(
            self._selected_model(check_current=False)
        )
        if selected_model != source["model"]:
            raise ProductPlanningError(
                "capability_replan_handoff_stale"
            )
        target_offer = self._capability_replan_offer(
            normalized_catalog,
            projection,
            binding["published_capsule"],
            authorization["error_contract"],
        )
        if target_offer is None:
            raise ProductPlanningError("capability_replan_unavailable")
        suggestions = self._capability_replan_acceptance_suggestions(
            normalized_catalog,
            projection,
            decision,
        )
        successor = self._new_workspace(source["goal"], selected_model)
        successor["answers"] = self._planning_answers(source)
        now = _now()
        offer_digest = _digest(target_offer)
        handoff_body = {
            "schema_version": CAPABILITY_REPLAN_HANDOFF_VERSION,
            "source_workspace_id": source["workspace_id"],
            "source_plan_token": plan_token,
            "source_plan_digest": plan_digest,
            "source_gap_id": projection["gap_id"],
            "projection_digest": projection_digest,
            "authorize_decision_digest": decision["canonical_digest"],
            "source_proposal_authorization_digest": authorization[
                "authorization_digest"
            ],
            "admission_review_id": binding["admission_review_id"],
            "admission_digest": binding["admission_digest"],
            "publication_review_id": binding["publication_review_id"],
            "published_capsule": copy.deepcopy(
                binding["published_capsule"]
            ),
            "target_offer": target_offer,
            "target_offer_digest": offer_digest,
            "planning_model": selected_model,
            "successor_workspace_id": successor["workspace_id"],
            "successor_plan_token": successor["plan_token"],
            "authorization_revision": binding["authorization_revision"],
            "admission_revision_before": binding[
                "admission_revision_before"
            ],
            "admission_revision_after": binding[
                "admission_revision_after"
            ],
            "publication_revision": binding["publication_revision"],
            "handoff_catalog_revision": normalized_catalog[
                "warehouse_revision"
            ],
            "catalog_digest": _digest(normalized_catalog),
            "request_digest": request_digest,
            "acceptance_suggestions": suggestions,
            "created_at": now,
        }
        handoff = {
            **handoff_body,
            "handoff_digest": _digest(handoff_body),
        }
        self._validate_capability_replan_handoff(handoff)
        with self._lock:
            repeated = self._read_capability_replan_handoff(source)
            if repeated is not None:
                if repeated != handoff:
                    raise ProductPlanningError(
                        "capability_replan_handoff_conflict"
                    )
                successor = self._successor_workspace_from_handoff(
                    repeated
                )
            else:
                self._write_immutable(
                    self._capability_replan_handoff_path(plan_digest),
                    handoff,
                )
                self._save_workspace(successor)
        try:
            self._report_phase("model_probe", phase_callback)
            current = self._selected_model(
                check_current=True,
                cancel_check=cancel_check,
            )
            if self._model_identity(current) != selected_model:
                raise ProductPlanningError(
                    "capability_replan_handoff_stale"
                )
            self._validate_capability_replan_current(
                handoff,
                normalized_catalog,
            )
            return self._continue_initial_planning(
                successor,
                normalized_catalog,
                cancel_check,
                phase_callback,
            )
        except ProductPlanningError as exc:
            return self._planning_error(successor, exc)

    @_public_call
    def answer(
        self,
        plan_token: str,
        question_set_digest: str,
        answers: list[dict[str, Any]],
        catalog: dict[str, Any],
        cancel_check: Callable[[], bool] | None = None,
        *,
        phase_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        workspace = self._workspace_by_token(plan_token)
        question_set = workspace.get("current_question_set")
        if (
            type(question_set) is not dict
            or question_set.get("digest") != question_set_digest
            or workspace.get("status") != "needs_clarification"
        ):
            return _error(
                "product_plan_question_set_stale",
                self._workspace_projection(workspace),
            )
        if question_set.get("purpose") == "revision":
            return _error(
                "product_plan_question_set_stale",
                self._workspace_projection(workspace),
            )
        try:
            structured = self._answers(question_set, answers)
            normalized_catalog = self._catalog(catalog)
            gap_target_selection = None
            if question_set["purpose"] == "capability_gap_target":
                gap_target_selection = (
                    self._capability_gap_target_selection(
                        question_set,
                        structured,
                        normalized_catalog,
                    )
                )
            handoff = self._capability_replan_for_successor(workspace)
            if handoff is not None:
                self._validate_capability_replan_current(
                    handoff,
                    normalized_catalog,
                    check_model=True,
                    cancel_check=cancel_check,
                )
        except ProductPlanningError as exc:
            return _error(exc.code, self._workspace_projection(workspace))
        workspace["answers"].append(
            {
                "question_set_digest": question_set_digest,
                "purpose": question_set["purpose"],
                "answers": structured,
                "submitted_at": _now(),
                "answers_digest": _digest(structured),
            }
        )
        workspace["current_question_set"] = None
        if gap_target_selection is not None:
            workspace["capability_gap_target_selection"] = (
                gap_target_selection
            )
        workspace["status"] = "planning"
        workspace["failure_code"] = None
        if question_set["purpose"] == "initial":
            if (
                workspace["schema_version"]
                in TARGET_SELECTION_WORKSPACE_SCHEMA_VERSIONS
            ):
                workspace["capability_gap_target_selection"] = None
            workspace["outline"] = None
            workspace["outline_input_digest"] = None
            workspace["outline_response_digest"] = None
            if workspace["schema_version"] == LEGACY_WORKSPACE_SCHEMA_VERSION:
                workspace["section_checkpoints"] = []
            else:
                if (
                    workspace["schema_version"]
                    in LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSIONS
                ):
                    workspace["composition_selection"] = None
                    workspace["composition_selection_input_digest"] = None
                    workspace["composition_selection_response_digest"] = None
                workspace["blueprint"] = None
                workspace["blueprint_input_digest"] = None
                workspace["blueprint_response_digest"] = None
            workspace["delivery_waves"] = {}
        workspace["updated_at"] = _now()
        with self._lock:
            self._save_workspace(workspace)
        try:
            if question_set["purpose"] == "revision":
                self._enter_phase(workspace, "revision", phase_callback)
                feedback = str(workspace.get("pending_revision_feedback") or "")
                return self._request_revision(
                    workspace,
                    feedback,
                    normalized_catalog,
                    cancel_check,
                    structured,
                    phase_callback,
                    "propose_revision",
                )
            return self._continue_initial_planning(
                workspace,
                normalized_catalog,
                cancel_check,
                phase_callback,
            )
        except ProductPlanningError as exc:
            return self._planning_error(workspace, exc)

    @_public_call
    def suggest_action(
        self,
        plan_token: str,
        feedback: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        workspace = self._workspace_by_token(plan_token)
        plan = workspace.get("plan")
        if (
            workspace.get("status") not in {"plan_review", "confirmed"}
            or type(plan) is not dict
            or workspace.get("pending_diff") is not None
            or workspace.get("current_question_set") is not None
        ):
            raise ProductPlanningError("product_plan_action_suggestion_stale")
        feedback = _safe_text(feedback, maximum=MAX_FEEDBACK_CHARS)
        model = self._selected_model(check_current=False)
        if self._model_identity(model) != workspace["model"]:
            raise ProductPlanningError("product_planning_model_digest_changed")
        prompt_plan, _references = self._revision_prompt_plan(
            plan,
            workspace["delivery_waves"],
        )
        request_value = {
            "feedback": feedback,
            "current_plan": prompt_plan,
            "rules": (
                "Suggest ask_plan when the user only wants an explanation of the current "
                "plan, propose_revision when the user wants plan content changed or wants "
                "blocking choices clarified before a change, and edit_goal only when the "
                "user wants to replace the product goal itself. This is advisory only; the "
                "user will make the authoritative choice."
            ),
            "schema_example": {"suggested_action": "ask_plan"},
        }
        suggested_action: str | None = None
        response_digest: str | None = None
        call_evidence: dict[str, Any] = {}
        failure_code: str | None = None
        try:
            value, call_evidence = self._generate_json(
                workspace["model"],
                "plan_action_suggestion",
                request_value,
                cancel_check,
            )
            row = _exact_dict(value, {"suggested_action"})
            if row["suggested_action"] not in {
                "ask_plan",
                "propose_revision",
                "edit_goal",
            }:
                raise ProductPlanningError("product_plan_response_invalid")
            suggested_action = row["suggested_action"]
            response_digest = call_evidence["structured_response_digest"]
        except ProductPlanningError as exc:
            if exc.code not in {
                "ollama_unavailable",
                "ollama_response_invalid",
                "ollama_response_too_large",
                "product_plan_response_invalid",
            }:
                raise
            failure_code = exc.code
        evidence = {
            "schema_version": ACTION_SUGGESTION_SCHEMA_VERSION,
            "base_plan_digest": plan["canonical_digest"],
            "feedback_digest": _digest(feedback),
            "model_name": workspace["model"]["name"],
            "model_digest": workspace["model"]["digest"],
            "prompt_version": ACTION_SUGGESTION_PROMPT_VERSION,
            "structured_response_digest": response_digest,
            "input_bytes": call_evidence.get("input_bytes"),
            "output_bytes": call_evidence.get("output_bytes"),
            "duration_ms": call_evidence.get("duration_ms"),
            "suggested_action": suggested_action,
            "failure_code": failure_code,
        }
        suggestion_digest = _digest(evidence)
        receipt = "suggestion_receipt_" + uuid.uuid4().hex + uuid.uuid4().hex[:16]
        with self._lock:
            self._action_suggestions[receipt] = {
                **evidence,
                "suggestion_digest": suggestion_digest,
            }
            while len(self._action_suggestions) > 64:
                self._action_suggestions.pop(next(iter(self._action_suggestions)))
        return _ok(
            {
                "suggested_action": suggested_action,
                "recommendation_available": suggested_action is not None,
                "suggestion_receipt": receipt,
                "suggestion_digest": suggestion_digest,
            }
        )

    def _consume_action_suggestion(
        self,
        workspace: dict[str, Any],
        feedback: str,
        receipt: str,
        suggestion_digest: str,
    ) -> None:
        plan = workspace.get("plan")
        if (
            type(plan) is not dict
            or _SUGGESTION_RECEIPT.fullmatch(str(receipt)) is None
            or _DIGEST.fullmatch(str(suggestion_digest)) is None
        ):
            raise ProductPlanningError("product_plan_action_suggestion_stale")
        selected = self._selected_model(check_current=False)
        with self._lock:
            evidence = self._action_suggestions.get(receipt)
            if (
                type(evidence) is not dict
                or evidence.get("suggestion_digest") != suggestion_digest
                or evidence.get("base_plan_digest") != plan["canonical_digest"]
                or evidence.get("feedback_digest") != _digest(feedback)
                or evidence.get("model_name") != workspace["model"]["name"]
                or evidence.get("model_digest") != workspace["model"]["digest"]
                or self._model_identity(selected) != workspace["model"]
            ):
                raise ProductPlanningError("product_plan_action_suggestion_stale")
            del self._action_suggestions[receipt]

    @staticmethod
    def _revision_target_section(
        plan: Any,
        value: Any,
    ) -> str:
        if type(value) is not str or value not in SECTION_IDS:
            raise ProductPlanningError(
                "product_plan_revision_invalid",
                "diff.target_section_invalid",
            )
        if (
            type(plan) is not dict
            or sum(
                type(section) is dict and section.get("section_id") == value
                for section in plan.get("sections", [])
            )
            != 1
        ):
            raise ProductPlanningError(
                "product_plan_revision_invalid",
                "diff.target_section_mismatch",
            )
        return value

    @_public_call
    def revise(
        self,
        plan_token: str,
        request: dict[str, Any],
        catalog: dict[str, Any],
        cancel_check: Callable[[], bool] | None = None,
        *,
        phase_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        workspace = self._workspace_by_token(plan_token)
        if type(request) is not dict:
            raise ProductPlanningError("product_plan_revision_invalid")
        action = request.get("action")
        if action in {"accept_diff", "reject_diff"}:
            if set(request) != {
                "action",
                "base_plan_digest",
                "diff_digest",
                "reviewed_plan",
                "reviewed_diff",
            }:
                raise ProductPlanningError("product_plan_revision_invalid")
            self._enter_phase(workspace, "revision", phase_callback)
            pending = workspace.get("pending_diff")
            if (
                type(pending) is not dict
                or not workspace.get("plan")
                or pending.get("base_plan_digest")
                != workspace["plan"].get("canonical_digest")
                or request["base_plan_digest"] != pending.get("base_plan_digest")
                or request["diff_digest"]
                != pending.get("public_diff", {}).get("diff_digest")
                or request["reviewed_plan"] != workspace["plan"]
                or request["reviewed_diff"] != pending.get("public_diff")
            ):
                raise ProductPlanningError("product_plan_diff_stale")
            self._validate_pending_diff(workspace["plan"], pending)
            current = self._catalog(catalog)
            plan_stale = self._stale_bindings(workspace["plan"], current)
            proposed_stale = self._stale_bindings(pending["proposed_plan"], current)
            relevant_stale = plan_stale or (
                proposed_stale if action == "accept_diff" else []
            )
            if relevant_stale:
                invalidated = copy.deepcopy(workspace)
                invalidated["pending_diff"] = None
                invalidated["confirmation"] = None
                invalidated["failure_code"] = (
                    "product_plan_capsule_stale"
                    if plan_stale
                    else "product_plan_diff_capsule_stale"
                )
                invalidated["status"] = "failed" if plan_stale else "plan_review"
                invalidated["updated_at"] = _now()
                with self._lock:
                    self._save_workspace(invalidated)
                return _error(
                    invalidated["failure_code"],
                    {
                        "workspace": self._workspace_projection(invalidated),
                        "stale_work_items": relevant_stale,
                    },
                )
        if action == "accept_diff":
            workspace["plan"] = pending["proposed_plan"]
            workspace["delivery_waves"] = pending["proposed_delivery_waves"]
            workspace["pending_diff"] = None
            workspace["status"] = "plan_review"
            workspace["confirmation"] = None
            workspace["updated_at"] = _now()
            with self._lock:
                self._save_workspace(workspace)
            return _ok(self._workspace_projection(workspace))
        if action == "reject_diff":
            original = workspace["plan"]["canonical_digest"]
            workspace["pending_diff"] = None
            workspace["answers"] = copy.deepcopy(
                workspace["plan"]["planning_answers"]
            )
            workspace["status"] = "plan_review"
            workspace["updated_at"] = _now()
            with self._lock:
                self._save_workspace(workspace)
            if workspace["plan"]["canonical_digest"] != original:
                raise ProductPlanningError("product_plan_diff_rejection_changed_plan")
            return _ok(self._workspace_projection(workspace))
        if action == "edit_diff":
            if set(request) != {"action", "expected_diff_digest", "fields"}:
                raise ProductPlanningError("product_plan_revision_invalid")
            return self._edit_pending_diff(
                workspace,
                request["expected_diff_digest"],
                request["fields"],
                self._catalog(catalog),
                phase_callback,
            )
        if action == "request" and "target_operation" in request:
            target_operation = request.get("target_operation")
            expected = {
                "action",
                "message",
                "target_section_id",
                "target_operation",
                (
                    "requirement_refs"
                    if target_operation == "add"
                    else "target_binding_ref"
                ),
            }
            if (
                target_operation not in {"add", "update"}
                or set(request) != expected
                or type(workspace.get("pending_diff")) is dict
                or workspace.get("status") not in {"plan_review", "confirmed"}
            ):
                raise ProductPlanningError("product_plan_revision_invalid")
            message = _safe_text(request["message"], maximum=MAX_FEEDBACK_CHARS)
            target_section_id = self._revision_target_section(
                workspace.get("plan"),
                request.get("target_section_id"),
            )
            target_scope = self._targeted_revision_scope(
                workspace,
                target_section_id,
                target_operation,
                request.get("requirement_refs"),
                request.get("target_binding_ref"),
            )
            try:
                normalized_catalog = self._catalog(catalog)
                self._enter_phase(workspace, "revision", phase_callback)
                return self._request_targeted_revision(
                    workspace,
                    message,
                    normalized_catalog,
                    cancel_check,
                    phase_callback,
                    target_section_id,
                    target_operation,
                    target_scope,
                )
            except ProductPlanningError as exc:
                return self._planning_error(workspace, exc)
        selected_action = request.get("selected_action")
        if (
            action == "request"
            and selected_action == "propose_revision"
            and "target_section_id" not in request
        ):
            raise ProductPlanningError(
                "product_plan_revision_invalid",
                "diff.target_section_invalid",
            )
        request_keys = {
            "action",
            "message",
            "reviewed_plan",
            "selected_action",
            "suggestion_receipt",
            "suggestion_digest",
        }
        if selected_action == "propose_revision":
            request_keys.add("target_section_id")
        if action != "request" or set(request) != request_keys:
            raise ProductPlanningError("product_plan_revision_invalid")
        if request["reviewed_plan"] != workspace.get("plan"):
            raise ProductPlanningError("product_plan_revision_stale")
        if type(workspace.get("pending_diff")) is dict:
            raise ProductPlanningError("product_plan_diff_pending")
        if workspace.get("status") not in {"plan_review", "confirmed"}:
            raise ProductPlanningError("product_plan_revision_unavailable")
        message = _safe_text(request["message"], maximum=MAX_FEEDBACK_CHARS)
        if (
            type(selected_action) is not str
            or selected_action not in {"ask_plan", "propose_revision", "edit_goal"}
            or type(request["suggestion_receipt"]) is not str
            or type(request["suggestion_digest"]) is not str
        ):
            raise ProductPlanningError("product_plan_revision_invalid")
        target_section_id = (
            self._revision_target_section(
                workspace.get("plan"),
                request.get("target_section_id"),
            )
            if selected_action == "propose_revision"
            else None
        )
        try:
            self._consume_action_suggestion(
                workspace,
                message,
                request["suggestion_receipt"],
                request["suggestion_digest"],
            )
        except ProductPlanningError as exc:
            return _error(exc.code, self._workspace_projection(workspace))
        if selected_action == "edit_goal":
            projection = self._workspace_projection(workspace)
            projection["revision_result"] = {
                "kind": "edit_goal",
                "plan_changed": False,
            }
            return _ok(projection)
        try:
            normalized_catalog = self._catalog(catalog)
            self._enter_phase(workspace, "revision", phase_callback)
            return self._request_revision(
                workspace,
                message,
                normalized_catalog,
                cancel_check,
                [],
                phase_callback,
                selected_action,
                target_section_id,
            )
        except ProductPlanningError as exc:
            return self._planning_error(workspace, exc)

    @_public_call
    def record_capability_gap_decision(
        self,
        plan_token: str,
        plan_digest: str,
        projection_digest: str,
        expected_previous_decision_digest: str | None,
        decision: str,
        behavior_intent: str | None,
        reason: str | None,
        acceptance_cases: list[dict[str, Any]],
        catalog: dict[str, Any],
    ) -> dict[str, Any]:
        workspace = self._workspace_by_token(plan_token)
        plan = workspace.get("plan")
        if (
            workspace.get("status") != "plan_review"
            or type(plan) is not dict
            or plan.get("canonical_digest") != plan_digest
            or _DIGEST.fullmatch(str(projection_digest)) is None
            or (
                expected_previous_decision_digest is not None
                and _DIGEST.fullmatch(
                    str(expected_previous_decision_digest)
                )
                is None
            )
            or decision not in {"authorize", "defer", "reject"}
            or type(acceptance_cases) is not list
        ):
            raise ProductPlanningError("capability_gap_decision_invalid")
        current_catalog = self._catalog(catalog)
        stored_projection = self._read_capability_gap_projection(workspace)
        if stored_projection is not None and (
            stored_projection["warehouse_revision"]
            != current_catalog["warehouse_revision"]
            or stored_projection["catalog_digest"] != _digest(current_catalog)
        ):
            raise ProductPlanningError("capability_gap_projection_stale")
        projection, status = self._capability_gap_projection_for_workspace(
            workspace,
            plan,
            current_catalog,
        )
        if projection is None or status != "available":
            raise ProductPlanningError(status)
        if projection["projection_digest"] != projection_digest:
            raise ProductPlanningError("capability_gap_projection_stale")

        def optional_text(
            value: Any,
            *,
            required: bool,
            maximum: int,
        ) -> str | None:
            if value is None and not required:
                return None
            if (
                type(value) is not str
                or value != value.strip()
                or not value
                or len(value) > maximum
                or any(
                    ord(character) < 32 and character not in "\n\t"
                    for character in value
                )
            ):
                raise ProductPlanningError(
                    "capability_gap_decision_invalid"
                )
            return value

        normalized_behavior = (
            optional_text(behavior_intent, required=True, maximum=1_000)
            if decision == "authorize"
            else None
        )
        normalized_reason = (
            optional_text(reason, required=True, maximum=500)
            if decision == "reject"
            else (
                optional_text(reason, required=False, maximum=500)
                if decision == "defer"
                else None
            )
        )
        normalized_cases = (
            copy.deepcopy(acceptance_cases)
            if decision == "authorize"
            else []
        )
        path = self._capability_gap_projection_path_for(
            workspace,
            plan,
            projection,
        )
        with self._lock:
            if self._capability_source_proposal_authorization_paths(workspace):
                raise ProductPlanningError(
                    "capability_gap_authorization_locked"
                )
            self._ensure_directory(path.parent)
            stored = stored_projection
            if stored is None:
                self._write_immutable(path, projection)
                stored = projection
            if stored != projection:
                raise ProductPlanningError(
                    "capability_gap_projection_stale"
                )
            decisions = self._capability_gap_decisions(
                workspace,
                projection,
            )
            previous = decisions[-1] if decisions else None
            actual_previous = (
                previous["canonical_digest"] if previous is not None else None
            )
            semantics = {
                "decision": decision,
                "behavior_intent": normalized_behavior,
                "reason": normalized_reason,
                "acceptance_cases": normalized_cases,
            }
            if previous is not None and all(
                previous[key] == value for key, value in semantics.items()
            ):
                return _ok(
                    self._workspace_projection(
                        workspace,
                        current_catalog,
                    )
                )
            if expected_previous_decision_digest != actual_previous:
                raise ProductPlanningError(
                    "capability_gap_decision_conflict"
                )
            if len(decisions) >= MAX_CAPABILITY_GAP_DECISIONS:
                raise ProductPlanningError(
                    "capability_gap_decision_limit"
                )
            body = {
                "schema_version": CAPABILITY_GAP_DECISION_VERSION,
                "gap_projection_digest": projection["projection_digest"],
                "plan_digest": plan["canonical_digest"],
                "catalog_digest": projection["catalog_digest"],
                "sequence": len(decisions) + 1,
                "previous_decision_digest": actual_previous,
                **semantics,
                "decision_source": "user_confirmed",
                "decided_at": _now(),
            }
            record = {**body, "canonical_digest": _digest(body)}
            self._validate_capability_gap_decision(
                record,
                projection,
                previous,
            )
            directory = self._capability_gap_decisions_dir(
                workspace,
                plan,
            )
            self._ensure_directory(directory)
            decision_path = directory / (
                f"decision_{record['sequence']:06d}_"
                f"{record['canonical_digest']}.json"
            )
            self._write_immutable(decision_path, record)
        return _ok(
            self._workspace_projection(
                workspace,
                current_catalog,
            )
        )

    @_public_call
    def prepare_capability_source_proposal(
        self,
        plan_token: str,
        plan_digest: str,
        projection_digest: str,
        authorize_decision_digest: str,
        catalog: dict[str, Any],
    ) -> dict[str, Any]:
        workspace = self._workspace_by_token(plan_token)
        plan = workspace.get("plan")
        if (
            workspace.get("status") != "plan_review"
            or type(plan) is not dict
            or plan.get("canonical_digest") != plan_digest
            or _DIGEST.fullmatch(str(projection_digest)) is None
            or _DIGEST.fullmatch(str(authorize_decision_digest)) is None
        ):
            raise ProductPlanningError(
                "capability_source_proposal_authorization_invalid"
            )
        current_catalog = self._catalog(catalog)
        with self._lock:
            projection = self._read_capability_gap_projection(workspace)
            if projection is None:
                raise ProductPlanningError(
                    "capability_source_proposal_authorization_required"
                )
            expected, status = self._capability_gap_projection_for_workspace(
                workspace,
                plan,
                current_catalog,
            )
            if (
                status != "available"
                or expected is None
                or expected != projection
                or projection["projection_digest"] != projection_digest
                or projection["warehouse_revision"]
                != current_catalog["warehouse_revision"]
                or projection["catalog_digest"] != _digest(current_catalog)
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_authorization_stale"
                )
            decisions = self._capability_gap_decisions(
                workspace,
                projection,
            )
            decision = decisions[-1] if decisions else None
            if (
                decision is None
                or decision["decision"] != "authorize"
                or decision["canonical_digest"]
                != authorize_decision_digest
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_authorization_required"
                )
            enum_adapter = (
                projection["adapter_contract_version"]
                == "computation_adapter.v4"
            )
            if enum_adapter and any(
                contract.get("type") == "string"
                for contract in projection["input_contract"][
                    "properties"
                ].values()
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_input_enumeration_review_required"
                )
            path = self._capability_source_proposal_authorization_path_for(
                workspace,
                plan,
                projection,
            )
            existing_paths = (
                self._capability_source_proposal_authorization_paths(
                    workspace
                )
            )
            if existing_paths:
                if existing_paths != [path]:
                    raise ProductPlanningError(
                        "capability_source_proposal_already_locked"
                    )
                self._read_capability_source_proposal_authorization(
                    workspace,
                    projection,
                    decision,
                )
                return _ok(
                    self._workspace_projection(
                        workspace,
                        current_catalog,
                    )
                )
            body = {
                "schema_version": (
                    CAPABILITY_SOURCE_PROPOSAL_AUTHORIZATION_V2
                    if enum_adapter
                    else CAPABILITY_SOURCE_PROPOSAL_AUTHORIZATION_VERSION
                ),
                "plan_id": plan["plan_id"],
                "plan_version": plan["plan_version"],
                "plan_digest": plan["canonical_digest"],
                "gap_id": projection["gap_id"],
                "projection_digest": projection["projection_digest"],
                "capability_key": projection["capability_key"],
                "capability_kind": "computation",
                "slot": projection["slot"],
                "input_contract": copy.deepcopy(
                    projection["input_contract"]
                ),
                "output_contract": copy.deepcopy(
                    projection["output_contract"]
                ),
                "error_contract": (
                    self._capability_source_proposal_error_contract()
                ),
                "adapter_contract_version": projection[
                    "adapter_contract_version"
                ],
                "result_field": projection["result_field"],
                "passthrough_fields": copy.deepcopy(
                    projection["passthrough_fields"]
                ),
                "authorize_decision_digest": decision[
                    "canonical_digest"
                ],
                "behavior_intent": decision["behavior_intent"],
                "acceptance_cases": copy.deepcopy(
                    decision["acceptance_cases"]
                ),
                "warehouse_revision": projection["warehouse_revision"],
                "catalog_digest": projection["catalog_digest"],
                "authorization_source": "user_confirmed_gap_decision",
                "locked_at": _now(),
            }
            if enum_adapter:
                body.update(
                    {
                        "capture_mapping_schema": projection[
                            "capture_mapping_schema"
                        ],
                        "proof_schema": projection["proof_schema"],
                        "result_enum": copy.deepcopy(
                            projection["result_enum"]
                        ),
                    }
                )
            authorization = {
                **body,
                "authorization_digest": _digest(body),
            }
            record = {
                **authorization,
                "request": (
                    self._build_capability_source_proposal_request_v4(
                        authorization
                    )
                    if enum_adapter
                    else self._build_capability_source_proposal_request(
                        authorization
                    )
                ),
            }
            self._validate_capability_source_proposal_authorization(
                workspace,
                record,
                projection,
                decision,
            )
            self._write_immutable(path, record)
        return _ok(
            self._workspace_projection(
                workspace,
                current_catalog,
            )
        )

    def prepare_capability_source_proposal_run(
        self,
        plan_token: str,
        plan_digest: str,
        projection_digest: str,
        authorization_digest: str,
        supervisor_model: dict[str, Any],
        catalog: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            _PLAN_TOKEN.fullmatch(str(plan_token)) is None
            or _DIGEST.fullmatch(str(plan_digest)) is None
            or _DIGEST.fullmatch(str(projection_digest)) is None
            or _DIGEST.fullmatch(str(authorization_digest)) is None
            or type(supervisor_model) is not dict
            or set(supervisor_model) != {"name", "digest"}
            or type(supervisor_model["name"]) is not str
            or not supervisor_model["name"]
            or _DIGEST.fullmatch(str(supervisor_model["digest"])) is None
        ):
            raise ProductPlanningError(
                "capability_source_proposal_run_invalid"
            )
        workspace = self._workspace_by_token(plan_token)
        plan = workspace.get("plan")
        current_catalog = self._catalog(catalog)
        projection = self._read_capability_gap_projection(workspace)
        expected, status = (
            self._capability_gap_projection_for_workspace(
                workspace,
                plan,
                current_catalog,
            )
            if type(plan) is dict
            else (None, "capability_gap_projection_missing")
        )
        decisions = (
            self._capability_gap_decisions(workspace, projection)
            if projection is not None
            else []
        )
        decision = decisions[-1] if decisions else None
        authorization = (
            self._read_capability_source_proposal_authorization(
                workspace,
                projection,
                decision,
            )
            if projection is not None
            and type(decision) is dict
            and decision.get("decision") == "authorize"
            else None
        )
        selected_model = self._model_identity(
            self._selected_model(check_current=False)
        )
        if (
            workspace.get("status") != "plan_review"
            or type(plan) is not dict
            or plan.get("canonical_digest") != plan_digest
            or projection is None
            or expected != projection
            or status != "available"
            or projection.get("projection_digest") != projection_digest
            or projection.get("warehouse_revision")
            != current_catalog["warehouse_revision"]
            or projection.get("catalog_digest") != _digest(current_catalog)
            or decision is None
            or decision.get("decision") != "authorize"
            or authorization is None
            or authorization.get("authorization_digest")
            != authorization_digest
            or workspace.get("model") != selected_model
        ):
            raise ProductPlanningError(
                "capability_source_proposal_run_stale"
            )
        request = self._runtime_capability_source_proposal_request(
            authorization
        )
        created = False
        with self._lock:
            path = self._capability_source_proposal_run_identity_path(
                workspace,
                plan,
            )
            if path.exists() or path.is_symlink():
                identity = self._validate_capability_source_proposal_run_identity(
                    workspace,
                    self._read_json(path),
                )
                expected_binding = {
                    "plan_token": plan_token,
                    "plan_digest": plan_digest,
                    "gap_id": projection["gap_id"],
                    "projection_digest": projection_digest,
                    "authorize_decision_digest": decision[
                        "canonical_digest"
                    ],
                    "authorization_digest": authorization_digest,
                    "request_digest": request["request_digest"],
                    "warehouse_revision": current_catalog[
                        "warehouse_revision"
                    ],
                    "catalog_digest": _digest(current_catalog),
                    "source_proposal_model": selected_model,
                    "supervision_model": copy.deepcopy(supervisor_model),
                }
                if any(
                    identity[key] != value
                    for key, value in expected_binding.items()
                ):
                    raise ProductPlanningError(
                        "capability_source_proposal_run_stale"
                    )
            else:
                now = _now()
                body = {
                    "schema_version": (
                        CAPABILITY_SOURCE_PROPOSAL_RUN_VERSION
                    ),
                    "run_id": f"run_{uuid.uuid4().hex}",
                    "plan_token": plan_token,
                    "plan_digest": plan_digest,
                    "gap_id": projection["gap_id"],
                    "projection_digest": projection_digest,
                    "authorize_decision_digest": decision[
                        "canonical_digest"
                    ],
                    "authorization_digest": authorization_digest,
                    "request_digest": request["request_digest"],
                    "warehouse_revision": current_catalog[
                        "warehouse_revision"
                    ],
                    "catalog_digest": _digest(current_catalog),
                    "source_proposal_model": selected_model,
                    "supervision_model": copy.deepcopy(supervisor_model),
                    "attempt_count": 1,
                    "created_at": now,
                }
                identity = {**body, "canonical_digest": _digest(body)}
                self._validate_capability_source_proposal_run_identity(
                    workspace,
                    identity,
                )
                self._write_immutable(path, identity)
                self._append_capability_source_proposal_run_event_locked(
                    workspace,
                    identity,
                    status="pending",
                    stage="source_proposal",
                    evidence={},
                    error_code=None,
                )
                created = True
        return {
            **self._capability_source_proposal_run_projection(
                workspace,
                identity,
            ),
            "created": created,
        }

    def append_capability_source_proposal_run_event(
        self,
        run_id: str,
        *,
        status: str,
        stage: str,
        evidence: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        workspace, identity = self._capability_source_proposal_run_by_id(
            run_id
        )
        with self._lock:
            self._append_capability_source_proposal_run_event_locked(
                workspace,
                identity,
                status=status,
                stage=stage,
                evidence=evidence or {},
                error_code=error_code,
            )
        return self._capability_source_proposal_run_projection(
            workspace,
            identity,
        )

    def get_capability_source_proposal_run(
        self,
        run_id: str,
    ) -> dict[str, Any]:
        workspace, identity = self._capability_source_proposal_run_by_id(
            run_id
        )
        return self._capability_source_proposal_run_projection(
            workspace,
            identity,
        )

    def capability_source_proposal_run_paths(
        self,
        run_id: str,
    ) -> dict[str, Path]:
        workspace, identity = self._capability_source_proposal_run_by_id(
            run_id
        )
        run_dir = self._capability_source_proposal_run_dir(
            workspace,
            workspace["plan"],
        )
        self._assert_no_symlink_components(run_dir)
        return {
            "run_dir": run_dir,
            "source_dir": run_dir / "source",
            "source_file": run_dir / "source" / "capability.js",
            "validation_dir": run_dir / "validation",
            "validation_database": (
                run_dir / "validation" / "capsule_warehouse.sqlite3"
            ),
            "identity": self._capability_source_proposal_run_identity_path(
                workspace,
                workspace["plan"],
            ),
        }

    def write_capability_source_proposal(
        self,
        run_id: str,
        content: str,
    ) -> dict[str, Any]:
        if (
            type(content) is not str
            or not content.strip()
            or not 1
            <= len(content.encode("utf-8"))
            <= CAPABILITY_SOURCE_PROPOSAL_MAX_BYTES
        ):
            raise ProductPlanningError(
                "capability_source_proposal_response_invalid"
            )
        paths = self.capability_source_proposal_run_paths(run_id)
        source_dir = paths["source_dir"]
        source_file = paths["source_file"]
        data = content.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        with self._lock:
            self._ensure_directory(source_dir)
            self._assert_no_symlink_components(source_dir)
            if source_file.exists() or source_file.is_symlink():
                try:
                    metadata = source_file.lstat()
                    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                    descriptor = os.open(source_file, flags)
                    try:
                        existing = os.read(
                            descriptor,
                            CAPABILITY_SOURCE_PROPOSAL_MAX_BYTES + 1,
                        )
                    finally:
                        os.close(descriptor)
                except OSError as exc:
                    raise ProductPlanningError(
                        "capability_source_proposal_source_conflict"
                    ) from exc
                if (
                    stat.S_ISLNK(metadata.st_mode)
                    or not stat.S_ISREG(metadata.st_mode)
                    or (
                        os.name == "posix"
                        and stat.S_IMODE(metadata.st_mode) & 0o077
                    )
                    or existing != data
                ):
                    raise ProductPlanningError(
                        "capability_source_proposal_source_conflict"
                    )
            else:
                flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                try:
                    descriptor = os.open(source_file, flags, 0o600)
                    try:
                        view = memoryview(data)
                        while view:
                            written = os.write(descriptor, view)
                            if written <= 0:
                                raise OSError("source_write_incomplete")
                            view = view[written:]
                        if os.name == "posix":
                            os.fchmod(descriptor, 0o600)
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                    if os.name == "posix":
                        directory_fd = os.open(
                            source_dir,
                            os.O_RDONLY
                            | getattr(os, "O_DIRECTORY", 0)
                            | getattr(os, "O_NOFOLLOW", 0),
                        )
                        try:
                            os.fsync(directory_fd)
                        finally:
                            os.close(directory_fd)
                except OSError as exc:
                    raise ProductPlanningError(
                        "product_planning_state_unavailable"
                    ) from exc
        return {
            "source_relpath": "source/capability.js",
            "source_sha256": digest,
        }

    def capability_source_proposal_run_context(
        self,
        run_id: str,
    ) -> dict[str, Any]:
        workspace, identity = self._capability_source_proposal_run_by_id(
            run_id
        )
        plan = workspace["plan"]
        projection = self._read_capability_gap_projection(workspace)
        decisions = (
            self._capability_gap_decisions(workspace, projection)
            if projection is not None
            else []
        )
        decision = decisions[-1] if decisions else None
        authorization = (
            self._read_capability_source_proposal_authorization(
                workspace,
                projection,
                decision,
            )
            if projection is not None
            and type(decision) is dict
            and decision.get("decision") == "authorize"
            else None
        )
        if (
            authorization is None
            or identity["plan_digest"] != plan["canonical_digest"]
            or identity["projection_digest"]
            != projection["projection_digest"]
            or identity["authorization_digest"]
            != authorization["authorization_digest"]
        ):
            raise ProductPlanningError(
                "capability_source_proposal_run_conflict"
            )
        return {
            "workspace": copy.deepcopy(workspace),
            "identity": copy.deepcopy(identity),
            "projection": copy.deepcopy(projection),
            "decision": copy.deepcopy(decision),
            "authorization": copy.deepcopy(authorization),
            "request": self._runtime_capability_source_proposal_request(
                authorization
            ),
        }

    def run_capability_source_proposal_model(
        self,
        run_id: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        context = self.capability_source_proposal_run_context(run_id)
        identity = context["identity"]
        request_value = context["request"]
        model = identity["source_proposal_model"]
        self._cancelled(cancel_check)
        current = self._model_identity(
            self._selected_model(
                check_current=True,
                cancel_check=cancel_check,
            )
        )
        if current != model or request_value["request_digest"] != identity[
            "request_digest"
        ]:
            raise ProductPlanningError(
                "capability_source_proposal_model_changed"
            )
        payload = {
            "model": model["name"],
            "prompt": request_value["prompt"],
            "stream": False,
            "think": False,
            "format": request_value["format_schema"],
            "options": {"temperature": 0},
        }
        response, http = self._request(
            "/api/generate",
            payload,
            timeout_seconds=FORMAL_MODEL_TIMEOUT_SECONDS,
        )
        after = self._model_identity(
            self._selected_model(check_current=True)
        )
        if after != model:
            raise ProductPlanningError(
                "capability_source_proposal_model_changed"
            )
        raw_output = response.get("response")
        if type(raw_output) is not str:
            raise ProductPlanningError(
                "capability_source_proposal_response_invalid"
            )
        encoded = raw_output.encode("utf-8")
        if len(encoded) > MAX_HTTP_RESPONSE_BYTES:
            raise ProductPlanningError("ollama_response_too_large")
        try:
            value = _strict_json(encoded)
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ProductPlanningError(
                "capability_source_proposal_response_invalid"
            ) from exc
        proposal = self.validate_capability_source_proposal_response(
            value,
            request_value,
        )
        self._cancelled(cancel_check)
        return {
            "proposal": proposal,
            "evidence": {
                "request_digest": request_value["request_digest"],
                "input_bytes": http["input_bytes"],
                "output_bytes": len(encoded),
                "duration_ms": http["duration_ms"],
                "response_digest": hashlib.sha256(encoded).hexdigest(),
            },
        }

    @_public_call
    def confirm(
        self,
        plan_token: str,
        plan_digest: str,
        reviewed_plan: dict[str, Any],
        catalog: dict[str, Any],
        parameter_capsules: list[dict[str, Any]] | None = None,
        parameter_confirmation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workspace = self._workspace_by_token(plan_token)
        plan = workspace.get("plan")
        if (
            type(plan) is not dict
            or plan.get("canonical_digest") != plan_digest
            or reviewed_plan != plan
            or workspace.get("pending_diff") is not None
        ):
            raise ProductPlanningError("product_plan_confirmation_stale")
        current = self._catalog(catalog)
        stale = self._stale_bindings(plan, current)
        if stale:
            return _error(
                "product_plan_capsule_stale",
                {"stale_work_items": stale},
            )
        offer: dict[str, Any] | None = None
        parameter_binding: dict[str, Any] | None = None
        if parameter_capsules is not None:
            try:
                offer = build_parameterized_execution_offer(
                    plan,
                    parameter_capsules,
                )
                if parameter_confirmation is not None:
                    if offer is None:
                        raise PlanExecutionError(
                            "parameterized_execution_confirmation_invalid"
                        )
                    parameter_binding = build_parameterized_execution_binding(
                        plan,
                        offer,
                        parameter_confirmation,
                    )
            except PlanExecutionError as exc:
                return _error(exc.code, self._workspace_projection(workspace))
        elif parameter_confirmation is not None:
            return _error(
                "parameterized_execution_confirmation_invalid",
                self._workspace_projection(workspace),
            )
        if workspace.get("status") == "confirmed":
            self._validate_confirmed_snapshot(workspace)
            if workspace["confirmation"].get("schema_version") == (
                "product_plan_confirmation.v2"
            ):
                if offer is None:
                    return _error(
                        "parameterized_execution_binding_stale",
                        self._workspace_projection(workspace),
                    )
                try:
                    self._validate_stored_confirmation(
                        workspace["confirmation"],
                        plan,
                        offer,
                    )
                except ProductPlanningError:
                    return _error(
                        "parameterized_execution_binding_stale",
                        self._workspace_projection(workspace),
                    )
            stored_binding = workspace["confirmation"].get("parameter_binding")
            if (
                parameter_confirmation is not None
                and stored_binding != parameter_binding
            ):
                return _error(
                    "product_plan_confirmation_conflict",
                    self._workspace_projection(workspace),
                )
            return _ok(self._workspace_projection(workspace))
        if workspace.get("status") != "plan_review":
            raise ProductPlanningError("product_plan_confirmation_stale")
        snapshot_path = self._confirmation_snapshot_path(workspace, plan)
        if snapshot_path.exists() or snapshot_path.is_symlink():
            existing = _stored_exact(
                self._read_json(snapshot_path),
                {"plan", "confirmation"},
            )
            if existing["plan"] != plan:
                raise ProductPlanningError("product_plan_confirmation_conflict")
            stored_schema = existing["confirmation"].get("schema_version")
            if stored_schema == "product_plan_confirmation.v2" and offer is None:
                raise ProductPlanningError(
                    "parameterized_execution_binding_stale"
                )
            self._validate_stored_confirmation(
                existing["confirmation"],
                plan,
                offer if stored_schema == "product_plan_confirmation.v2" else None,
            )
            if (
                parameter_confirmation is not None
                and existing["confirmation"].get("parameter_binding")
                != parameter_binding
            ):
                raise ProductPlanningError("product_plan_confirmation_conflict")
            recovered = copy.deepcopy(workspace)
            recovered["confirmation"] = existing["confirmation"]
            recovered["status"] = "confirmed"
            recovered["updated_at"] = _now()
            with self._lock:
                self._save_workspace(recovered)
            return _ok(self._workspace_projection(recovered))
        try:
            selected = self._selected_model(check_current=False)
            if self._model_identity(selected) != plan["model"]:
                raise ProductPlanningError("product_planning_model_digest_changed")
        except ProductPlanningError as exc:
            return _error(exc.code, self._workspace_projection(workspace))
        if offer is not None and parameter_binding is None:
            projection = self._workspace_projection(workspace)
            projection["parameter_offer"] = offer
            return _error("parameter_confirmation_required", projection)
        receipt = {
            "schema_version": (
                "product_plan_confirmation.v2"
                if parameter_binding is not None
                else "product_plan_confirmation.v1"
            ),
            "plan_id": plan["plan_id"],
            "plan_version": plan["plan_version"],
            "plan_digest": plan_digest,
            "confirmed_at": _now(),
            "capsule_revalidation": [
                {
                    "capsule_id": binding["capsule_id"],
                    "version_id": binding["version_id"],
                    "eligibility_status": "active_current_eligible",
                    "review_status": "user_confirmed",
                }
                for section in plan["sections"]
                for item in section["work_items"]
                for binding in item["capsule_bindings"]
            ],
            "warehouse_revision": current["warehouse_revision"],
            "product_generated": False,
            "candidate_generated": False,
            "product_usage_written": False,
        }
        if parameter_binding is not None:
            receipt["parameter_binding"] = parameter_binding
        receipt["receipt_digest"] = _digest(receipt)
        confirmed_workspace = copy.deepcopy(workspace)
        confirmed_workspace["confirmation"] = receipt
        confirmed_workspace["status"] = "confirmed"
        confirmed_workspace["updated_at"] = _now()
        with self._lock:
            confirmed = snapshot_path.parent
            self._ensure_directory(confirmed)
            self._write_immutable(
                snapshot_path,
                {"plan": plan, "confirmation": receipt},
            )
            self._save_workspace(confirmed_workspace)
        return _ok(self._workspace_projection(confirmed_workspace))

    def record_product_experience(
        self,
        plan_token: str,
        catalog: dict[str, Any],
        milestone: str,
        *,
        candidate: dict[str, Any] | None = None,
        export_status: str | None = None,
    ) -> dict[str, Any] | None:
        if milestone not in PROJECT_EXPERIENCE_MILESTONES:
            raise ProductPlanningError("project_experience_milestone_invalid")
        with self._lock:
            workspace = self._workspace_by_token(plan_token)
            scope = self._project_experience_scope()
            try:
                record = build_project_experience_record(
                    workspace=workspace,
                    catalog=catalog,
                    project_scope_digest=scope["canonical_digest"],
                    milestone=milestone,
                    candidate=candidate,
                    export_status=export_status,
                )
            except ExperienceError as exc:
                if str(exc) == "project_experience_failure_unattributed":
                    return None
                raise ProductPlanningError(str(exc)) from exc
            path = (
                self._project_experience_root()
                / "records"
                / workspace["workspace_id"]
                / f"{milestone}.json"
            )
            if path.exists() or path.is_symlink():
                try:
                    existing = validate_project_experience_record(
                        self._read_json(path)
                    )
                except ExperienceError as exc:
                    raise ProductPlanningError(
                        "project_experience_record_invalid"
                    ) from exc
                if existing != record:
                    raise ProductPlanningError(
                        "project_experience_record_conflict"
                    )
                return existing
            self._write_immutable(path, record)
            return record

    def retrieve_product_experience(
        self,
        plan_token: str,
        limit: int = 3,
    ) -> dict[str, Any]:
        with self._lock:
            workspace = self._workspace_by_token(plan_token)
            scope = self._project_experience_scope()
            records = self._project_experience_records(
                scope["canonical_digest"]
            )
            try:
                return build_product_experience_query(
                    workspace=workspace,
                    project_scope_digest=scope["canonical_digest"],
                    records_with_workspaces=records,
                    limit=limit,
                )
            except ExperienceError as exc:
                raise ProductPlanningError(str(exc)) from exc

    @_public_call
    def confirm_candidate_acceptance(
        self,
        plan_token: str,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        workspace = self._workspace_by_token(plan_token)
        plan = workspace.get("plan")
        if (
            workspace.get("status") != "confirmed"
            or type(plan) is not dict
            or type(workspace.get("confirmation")) is not dict
        ):
            raise ProductPlanningError(
                "candidate_acceptance_confirmation_unavailable"
            )
        self._validate_candidate_acceptance_confirmation_binding(
            workspace,
            record,
        )
        path = self._candidate_acceptance_confirmation_path(workspace, plan)
        with self._lock:
            self._ensure_directory(path.parent)
            try:
                self._write_immutable(path, record)
            except ProductPlanningError as exc:
                if exc.code == "product_plan_confirmation_conflict":
                    raise ProductPlanningError(
                        "candidate_acceptance_confirmation_conflict"
                    ) from exc
                raise
        return _ok({"acceptance_confirmation": copy.deepcopy(record)})

    @_public_call
    def get_candidate_acceptance_confirmation(
        self,
        plan_token: str,
    ) -> dict[str, Any]:
        workspace = self._workspace_by_token(plan_token)
        plan = workspace.get("plan")
        if (
            workspace.get("status") != "confirmed"
            or type(plan) is not dict
            or type(workspace.get("confirmation")) is not dict
        ):
            raise ProductPlanningError(
                "candidate_acceptance_confirmation_unavailable"
            )
        path = self._candidate_acceptance_confirmation_path(workspace, plan)
        if path.is_symlink() or not path.is_file():
            raise ProductPlanningError(
                "candidate_acceptance_confirmation_required"
            )
        record = self._read_json(path)
        self._validate_candidate_acceptance_confirmation_binding(
            workspace,
            record,
        )
        return _ok({"acceptance_confirmation": copy.deepcopy(record)})

    @_public_call
    def create_agent_handoff(
        self,
        plan_token: str,
        acceptance_confirmation_digest: str,
        capsule_facts_digest: str,
    ) -> dict[str, Any]:
        workspace = self._workspace_by_token(plan_token)
        plan = workspace.get("plan")
        confirmation = workspace.get("confirmation")
        if (
            workspace.get("status") != "confirmed"
            or type(plan) is not dict
            or type(confirmation) is not dict
            or _DIGEST.fullmatch(acceptance_confirmation_digest) is None
            or _DIGEST.fullmatch(capsule_facts_digest) is None
        ):
            raise ProductPlanningError("agent_handoff_confirmation_required")
        acceptance_path = self._candidate_acceptance_confirmation_path(
            workspace,
            plan,
        )
        if acceptance_path.is_symlink() or not acceptance_path.is_file():
            raise ProductPlanningError("agent_handoff_confirmation_required")
        acceptance = self._read_json(acceptance_path)
        self._validate_candidate_acceptance_confirmation_binding(
            workspace,
            acceptance,
        )
        if acceptance["canonical_digest"] != acceptance_confirmation_digest:
            raise ProductPlanningError("agent_handoff_stale")
        handoff_token = (
            "handoff_token_" + uuid.uuid4().hex + uuid.uuid4().hex[:16]
        )
        token_digest = hashlib.sha256(handoff_token.encode("ascii")).hexdigest()
        record = {
            "schema_version": "agent_handoff.v1",
            "token_digest": token_digest,
            "plan_digest": plan["canonical_digest"],
            "plan_confirmation_digest": confirmation["receipt_digest"],
            "acceptance_confirmation_digest": acceptance_confirmation_digest,
            "capsule_facts_digest": capsule_facts_digest,
            "status": "active",
            "created_at": _now(),
            "revoked_at": None,
        }
        record["canonical_digest"] = _digest(record)
        path = self._agent_handoff_path(workspace, token_digest)
        with self._lock:
            self._ensure_directory(path.parent)
            self._write_immutable(path, record)
        return _ok(
            {
                "handoff_token": handoff_token,
                "status": "active",
                "created_at": record["created_at"],
            }
        )

    @_public_call
    def resolve_agent_handoff(self, handoff_token: str) -> dict[str, Any]:
        workspace, record, _path = self._find_agent_handoff(handoff_token)
        if record["status"] == "revoked":
            raise ProductPlanningError("agent_handoff_revoked")
        self._validate_agent_handoff_binding(workspace, record)
        return _ok(
            {
                "plan_token": workspace["plan_token"],
                "plan_digest": record["plan_digest"],
                "plan_confirmation_digest": record[
                    "plan_confirmation_digest"
                ],
                "acceptance_confirmation_digest": record[
                    "acceptance_confirmation_digest"
                ],
                "capsule_facts_digest": record["capsule_facts_digest"],
                "status": "active",
            }
        )

    @_public_call
    def revoke_agent_handoff(self, handoff_token: str) -> dict[str, Any]:
        _workspace, record, path = self._find_agent_handoff(handoff_token)
        if record["status"] == "active":
            record["status"] = "revoked"
            record["revoked_at"] = _now()
            record["canonical_digest"] = _digest(
                {
                    key: value
                    for key, value in record.items()
                    if key != "canonical_digest"
                }
            )
            with self._lock:
                self._atomic_write(path, record)
        return _ok(
            {
                "status": "revoked",
                "revoked_at": record["revoked_at"],
            }
        )

    @_public_call
    def get(
        self,
        plan_token: str,
        catalog: dict[str, Any] | None = None,
        parameter_capsules: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        workspace = self._workspace_by_token(plan_token)
        current: dict[str, Any] | None = None
        if catalog is not None:
            current = self._catalog(catalog)
            plan = workspace.get("plan")
            plan_stale = (
                self._stale_bindings(plan, current)
                if type(plan) is dict
                else []
            )
            pending = workspace.get("pending_diff")
            diff_stale = (
                self._stale_bindings(pending["proposed_plan"], current)
                if type(pending) is dict
                else []
            )
            if plan_stale or diff_stale:
                invalidated = copy.deepcopy(workspace)
                invalidated["pending_diff"] = None
                invalidated["confirmation"] = None
                invalidated["failure_code"] = (
                    "product_plan_capsule_stale"
                    if plan_stale
                    else "product_plan_diff_capsule_stale"
                )
                invalidated["status"] = "failed" if plan_stale else "plan_review"
                invalidated["updated_at"] = _now()
                with self._lock:
                    self._save_workspace(invalidated)
                return _error(
                    invalidated["failure_code"],
                    {
                        "workspace": self._workspace_projection(invalidated),
                        "stale_work_items": plan_stale or diff_stale,
                    },
                )
        confirmation = workspace.get("confirmation")
        if (
            parameter_capsules is not None
            and type(confirmation) is dict
            and confirmation.get("schema_version")
            == "product_plan_confirmation.v2"
        ):
            try:
                offer = build_parameterized_execution_offer(
                    workspace["plan"],
                    parameter_capsules,
                )
                if offer is None:
                    raise PlanExecutionError(
                        "parameterized_execution_binding_stale"
                    )
                self._validate_stored_confirmation(
                    confirmation,
                    workspace["plan"],
                    offer,
                )
            except (PlanExecutionError, ProductPlanningError):
                return _error(
                    "parameterized_execution_binding_stale",
                    self._workspace_projection(workspace),
                )
        return _ok(self._workspace_projection(workspace, current))

    @_public_call
    def abandon(self, plan_token: str) -> dict[str, Any]:
        workspace = self._workspace_by_token(plan_token)
        self._abandon_workspace(workspace)
        return _ok(self._workspace_projection(workspace))

    def _abandon_workspace(self, workspace: dict[str, Any]) -> None:
        if workspace["status"] == "confirmed":
            return
        workspace["status"] = "interrupted"
        workspace["phase"] = None
        workspace["outline"] = None
        workspace["outline_input_digest"] = None
        workspace["outline_response_digest"] = None
        workspace["current_question_set"] = None
        if (
            workspace["schema_version"]
            in TARGET_SELECTION_WORKSPACE_SCHEMA_VERSIONS
        ):
            workspace["capability_gap_target_selection"] = None
        workspace["plan"] = None
        workspace["pending_diff"] = None
        workspace["pending_revision_feedback"] = None
        workspace["confirmation"] = None
        if workspace["schema_version"] == LEGACY_WORKSPACE_SCHEMA_VERSION:
            workspace["section_checkpoints"] = []
        else:
            if (
                workspace["schema_version"]
                in LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSIONS
            ):
                workspace["composition_selection"] = None
                workspace["composition_selection_input_digest"] = None
                workspace["composition_selection_response_digest"] = None
            workspace["blueprint"] = None
            workspace["blueprint_input_digest"] = None
            workspace["blueprint_response_digest"] = None
        workspace["delivery_waves"] = {}
        workspace["failure_code"] = "product_goal_changed"
        workspace["updated_at"] = _now()
        with self._lock:
            self._save_workspace(workspace)

    @_public_call
    def list_summaries(self) -> dict[str, Any]:
        summaries: list[dict[str, Any]] = []
        for workspace in self._workspaces():
            summaries.append(self._summary(workspace))
        summaries.sort(
            key=lambda item: (str(item["updated_at"]), str(item["plan_token"])),
            reverse=True,
        )
        return _ok({"summaries": summaries})

    def _request(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        timeout_seconds: int | float | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if timeout_seconds is None:
            timeout_seconds = HTTP_TIMEOUT_SECONDS
        data = None if payload is None else _canonical_bytes(payload)
        if data is not None and len(data) > MAX_HTTP_REQUEST_BYTES:
            raise ProductPlanningError("ollama_request_too_large")
        request = Request(
            self.base_url + path,
            data=data,
            method="GET" if data is None else "POST",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        started = time.monotonic()
        deadline = started + timeout_seconds
        try:
            self._cancelled(cancel_check)
            with opener.open(
                request,
                timeout=timeout_seconds,
            ) as response:
                chunks: list[bytes] = []
                received = 0
                reader = getattr(response, "read1", None) or response.read
                while received <= MAX_HTTP_RESPONSE_BYTES:
                    self._cancelled(cancel_check)
                    if time.monotonic() >= deadline:
                        raise ProductPlanningError(
                            "ollama_unavailable",
                            "ollama.timeout",
                        )
                    chunk = reader(min(64 * 1024, MAX_HTTP_RESPONSE_BYTES + 1 - received))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    received += len(chunk)
                raw = b"".join(chunks)
        except ProductPlanningError:
            raise
        except HTTPError as exc:
            raise ProductPlanningError(
                "ollama_unavailable",
                "ollama.http",
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ProductPlanningError(
                "ollama_unavailable",
                "ollama.timeout",
            ) from exc
        except URLError as exc:
            rule_code = (
                "ollama.timeout"
                if isinstance(exc.reason, (TimeoutError, socket.timeout))
                else "ollama.connection"
            )
            raise ProductPlanningError("ollama_unavailable", rule_code) from exc
        except OSError as exc:
            raise ProductPlanningError(
                "ollama_unavailable",
                "ollama.connection",
            ) from exc
        elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
        if len(raw) > MAX_HTTP_RESPONSE_BYTES:
            raise ProductPlanningError("ollama_response_too_large")
        try:
            value = _strict_json(raw)
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ProductPlanningError("ollama_response_invalid") from exc
        if type(value) is not dict:
            raise ProductPlanningError("ollama_response_invalid")
        return value, {
            "input_bytes": len(data or b""),
            "output_bytes": len(raw),
            "duration_ms": elapsed_ms,
        }

    def _available_models(
        self,
        cancel_check: Callable[[], bool] | None = None,
    ) -> list[dict[str, Any]]:
        tags, _evidence = self._request("/api/tags", cancel_check=cancel_check)
        if type(tags.get("models")) is not list:
            raise ProductPlanningError("ollama_response_invalid")
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for raw in tags["models"]:
            if type(raw) is not dict:
                continue
            name = raw.get("name")
            digest = raw.get("digest")
            if (
                type(name) is not str
                or not name
                or name != name.strip()
                or type(digest) is not str
                or _DIGEST.fullmatch(digest) is None
                or (name, digest) in seen
            ):
                continue
            seen.add((name, digest))
            show, _show_evidence = self._request(
                "/api/show",
                {"model": name, "verbose": False},
                cancel_check,
            )
            info = show.get("model_info")
            count = (
                info.get("general.parameter_count")
                if type(info) is dict
                else None
            )
            is_moe = type(info) is dict and (
                "moe" in str(info.get("general.architecture") or "").lower()
                or any(
                    type(key) is str
                    and key.endswith((".expert_count", ".expert_used_count"))
                    and type(value) is int
                    and value > 1
                    for key, value in info.items()
                )
            )
            details = show.get("details")
            parameter_size = (
                details.get("parameter_size")
                if type(details) is dict
                else None
            )
            proven = (
                type(count) is int
                and 0 < count <= MAX_MODEL_PARAMETERS
                and not is_moe
            )
            tags_after, _after_evidence = self._request(
                "/api/tags",
                cancel_check=cancel_check,
            )
            current_identities = {
                (item.get("name"), item.get("digest"))
                for item in tags_after.get("models", [])
                if type(item) is dict
            } if type(tags_after.get("models")) is list else set()
            if (name, digest) not in current_identities:
                raise ProductPlanningError("product_planning_model_digest_changed")
            result.append(
                {
                    "name": name,
                    "digest": digest,
                    "parameter_count": count if type(count) is int and count > 0 else None,
                    "parameter_size": (
                        parameter_size
                        if type(parameter_size) is str and parameter_size
                        else None
                    ),
                    "eligible_small_model": proven,
                    "eligibility_reason": (
                        "parameter_count_within_limit"
                        if proven
                        else (
                            "mixture_of_experts_not_allowed"
                            if is_moe
                            else (
                                "parameter_count_exceeds_limit"
                                if type(count) is int
                                and count > MAX_MODEL_PARAMETERS
                                else "parameter_count_unproven"
                            )
                        )
                    ),
                }
            )
        return sorted(result, key=lambda item: (item["name"], item["digest"]))

    def _selected_model(
        self,
        *,
        check_current: bool,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        if not self.root.exists() and not self.root.is_symlink():
            raise ProductPlanningError("product_planning_model_not_selected")
        self._ensure_directory(self.root)
        selected = self._read_json(self.root / "model_selection.json")
        required = {
            "schema_version",
            "base_url",
            "name",
            "digest",
            "parameter_count",
            "parameter_size",
            "selected_at",
            "probe",
        }
        if type(selected) is not dict or set(selected) != required:
            raise ProductPlanningError("product_planning_model_not_selected")
        if (
            selected["schema_version"] != MODEL_SELECTION_SCHEMA_VERSION
            or selected["base_url"] != self.base_url
            or type(selected["name"]) is not str
            or _DIGEST.fullmatch(str(selected["digest"])) is None
            or type(selected["parameter_count"]) is not int
            or not 0 < selected["parameter_count"] <= MAX_MODEL_PARAMETERS
            or type(selected["probe"]) is not dict
            or selected["probe"].get("status") != "passed"
        ):
            raise ProductPlanningError("product_planning_model_selection_invalid")
        if check_current:
            current = next(
                (
                    item
                    for item in self._available_models(cancel_check)
                    if item["name"] == selected["name"]
                    and item["digest"] == selected["digest"]
                ),
                None,
            )
            if (
                current is None
                or current["eligible_small_model"] is not True
                or current["parameter_count"] != selected["parameter_count"]
                or current["parameter_size"] != selected["parameter_size"]
            ):
                raise ProductPlanningError("product_planning_model_digest_changed")
        return selected

    def _probe(self, model: dict[str, Any]) -> dict[str, Any]:
        example = {
            "schema_version": "product_plan_probe.v1",
            "status": "ready",
            "role": "product_planner",
        }
        result, evidence = self._generate_json(
            model,
            "schema_probe",
            example,
        )
        if result != example:
            raise ProductPlanningError("product_planning_model_probe_failed")
        return {
            "schema_version": "product_plan_probe_receipt.v1",
            "status": "passed",
            "prompt_version": PLANNING_PROMPT_VERSION,
            **evidence,
        }

    def _generate_json(
        self,
        model: dict[str, Any],
        call_type: str,
        request_value: dict[str, Any],
        cancel_check: Callable[[], bool] | None = None,
        *,
        prompt_version: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self._cancelled(cancel_check)
        prompt_version = prompt_version or PLANNING_PROMPT_VERSION
        current = next(
            (
                item
                for item in self._available_models(cancel_check)
                if item["name"] == model["name"]
                and item["digest"] == model["digest"]
                and item["eligible_small_model"] is True
                and item["parameter_count"] == model["parameter_count"]
            ),
            None,
        )
        if current is None:
            raise ProductPlanningError("product_planning_model_digest_changed")
        if call_type == "schema_probe":
            prompt = (
                "You are Reweave's local product planning role. For this schema probe, "
                "return exactly the JSON object after this line. Copy every key and value "
                "verbatim. Do not wrap it, rename keys, add keys, or add prose.\n"
                + _canonical_bytes(request_value).decode("utf-8")
            )
        elif call_type == "composition_selection":
            locked_selection = request_value.get("selection_locked") is True
            experience_rules = (
                " Experience cases are non-formal advisory history only. Current goal, "
                "current complete offers, and deterministic rules remain authoritative. "
                "Never use a case to create a gap, member, identity, dependency, or "
                "wiring; treat an attributed failure as negative evidence."
                if prompt_version == PLANNING_PROMPT_VERSION
                else ""
            )
            prompt = (
                "You are Reweave's local product planning role. REQUEST_JSON contains "
                "the product goal, confirmed answers, requirements outline, safe complete "
                "composition offers, and selection rules."
                + experience_rules
                + " Return exactly one JSON object "
                "that matches the supplied response schema. "
                + (
                    "Select the one supplied capability_key; the deterministic core has "
                    "already locked the complete offer. "
                    if locked_selection
                    else "Select only a capability_key or the empty string. "
                )
                + "Do not return offer members, candidate refs, dependencies, wiring, "
                "identifiers, contracts, paths, source code, files, diffs, build claims, "
                "validation claims, markdown, or prose.\nREQUEST_JSON:\n"
                + _canonical_bytes(request_value).decode("utf-8")
            )
        elif (
            call_type == "product_blueprint"
            and request_value.get("selection_locked") is True
            and type(request_value.get("capability_gap_lock")) is dict
            and prompt_version
            in {
                PREVIOUS_GAP_PLANNING_PROMPT_VERSION,
                PREVIOUS_REQUIREMENT_COVERAGE_PROMPT_VERSION,
                PLANNING_PROMPT_VERSION,
            }
        ):
            prompt = (
                "You are Reweave's local product planning role. REQUEST_JSON contains "
                "the product goal, requirements, confirmed answers, existing formal "
                "members, and exactly one deterministic locked computation gap. Return "
                "exactly one JSON object that matches the supplied response schema. "
                "Describe only the title, reason, and section summaries for that one "
                "gap; never add, split, remove, replace, or reinterpret it. The schema "
                "locks its section, requirement coverage, member set, and gap count. "
                "Do not return REQUEST_JSON, add keys, markdown, prose, identifiers, "
                "contracts, paths, source code, files, diffs, build claims, or validation "
                "claims.\nREQUEST_JSON:\n"
                + _canonical_bytes(request_value).decode("utf-8")
            )
        elif (
            call_type == "product_blueprint"
            and request_value.get("selection_locked") is True
            and prompt_version
            in {
                PREVIOUS_REQUIREMENT_COVERAGE_PROMPT_VERSION,
                PLANNING_PROMPT_VERSION,
            }
        ):
            prompt = (
                "You are Reweave's local product planning role. REQUEST_JSON contains "
                "the product goal, requirements, confirmed answers, exactly one locked "
                "complete composition offer, and rules. Return exactly one JSON object "
                "that matches the supplied response schema. Describe every member of the "
                "locked offer and include each supplied candidate_ref exactly once; never "
                "add, remove, replace, or mix members. Mark a section applicable when it "
                "has an assignment or gap, and mark it not_applicable only when it has "
                "neither. Formal requirement coverage comes only from assignment "
                "requirement_refs or a real gap; section summaries do not count. Treat "
                "product-wide absence constraints such as local-only, offline, no network, "
                "no login, no database, or no deployment as acceptance conditions rather "
                "than gaps when the locked offer covers the requested user-visible "
                "behavior. Attach each such requirement_ref to at least one semantically "
                "relevant supplied member and state the constraint in acceptance_intent. "
                "Do not return REQUEST_JSON, add keys, markdown, prose, identifiers, "
                "contracts, paths, source code, files, diffs, build claims, or validation "
                "claims.\nREQUEST_JSON:\n"
                + _canonical_bytes(request_value).decode("utf-8")
            )
        elif (
            call_type == "product_blueprint"
            and request_value.get("selection_locked") is True
            and prompt_version
            in {
                PREVIOUS_LOCKED_BLUEPRINT_PROMPT_VERSION,
                PREVIOUS_GAP_PLANNING_PROMPT_VERSION,
            }
        ):
            prompt = (
                "You are Reweave's local product planning role. REQUEST_JSON contains "
                "the product goal, requirements, confirmed answers, exactly one locked "
                "complete composition offer, and rules. Return exactly one JSON object "
                "that matches the supplied response schema. Describe every member of the "
                "locked offer and include each supplied candidate_ref exactly once; never "
                "add, remove, replace, or mix members. Mark a section applicable when it "
                "has an assignment or gap, and mark it not_applicable only when it has "
                "neither. Do not return REQUEST_JSON, add keys, markdown, prose, "
                "identifiers, contracts, paths, source code, files, diffs, build claims, "
                "or validation claims.\nREQUEST_JSON:\n"
                + _canonical_bytes(request_value).decode("utf-8")
            )
        else:
            example_field = (
                "schema_examples"
                if call_type
                in {"plan_revision", "plan_revision_change", "plan_revision_proposal"}
                else "schema_example"
            )
            prompt = (
                "You are Reweave's local product planning role. REQUEST_JSON contains "
                f"task data, rules, and {example_field}. Return exactly one JSON response "
                f"object using exactly the keys shown in one applicable {example_field} "
                "entry. Do not return REQUEST_JSON, wrap the result in an example field, "
                "add keys, markdown, or "
                "prose. Replace example values with a solution for the supplied task while "
                "obeying its rules. "
                "Never invent capsule identifiers; only use supplied candidate_ref values. "
                "Do not emit paths, source code, secrets, files, diffs, build claims, or "
                "validation claims.\nREQUEST_JSON:\n"
                + _canonical_bytes(request_value).decode("utf-8")
            )
        payload = {
            "model": model["name"],
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": _structured_output_schema(
                call_type,
                request_value,
                prompt_version=prompt_version,
            ),
            "options": {"temperature": 0},
        }
        # One model generation is atomic. A cancellation observed after the call
        # is honored only after the structured response has been strictly checked
        # by the caller, so a completed section can be checkpointed safely.
        response, http = self._request(
            "/api/generate",
            payload,
            timeout_seconds=(
                HTTP_TIMEOUT_SECONDS
                if call_type == "schema_probe"
                else FORMAL_MODEL_TIMEOUT_SECONDS
            ),
        )
        after = next(
            (
                item
                for item in self._available_models()
                if item["name"] == model["name"]
                and item["digest"] == model["digest"]
                and item["eligible_small_model"] is True
                and item["parameter_count"] == model["parameter_count"]
                and item["parameter_size"] == model["parameter_size"]
            ),
            None,
        )
        if after is None:
            raise ProductPlanningError("product_planning_model_digest_changed")
        raw_output = response.get("response")
        if type(raw_output) is not str:
            raise ProductPlanningError("product_plan_response_invalid")
        encoded = raw_output.encode("utf-8")
        if len(encoded) > MAX_HTTP_RESPONSE_BYTES:
            raise ProductPlanningError("ollama_response_too_large")
        try:
            value = _strict_json(encoded)
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ProductPlanningError("product_plan_response_invalid") from exc
        if type(value) is not dict:
            raise ProductPlanningError("product_plan_response_invalid")
        return value, {
            "call_type": call_type,
            "input_bytes": http["input_bytes"],
            "output_bytes": len(encoded),
            "duration_ms": http["duration_ms"],
            "structured_response_digest": hashlib.sha256(encoded).hexdigest(),
        }

    def _catalog(self, value: dict[str, Any]) -> dict[str, Any]:
        if (
            type(value) is not dict
            or set(value) != {"warehouse_revision", "capsules"}
            or type(value["warehouse_revision"]) is not int
            or value["warehouse_revision"] < 0
            or type(value["capsules"]) is not list
        ):
            raise ProductPlanningError("product_planning_catalog_invalid")
        identity_keys = {
            "capsule_id",
            "version_id",
            "display_name",
            "capability_key",
            "role_key",
            "variant_key",
            "capability_kind",
            "canonical_hash",
            "identity_status",
        }
        contract_keys = {"input_contract", "output_contract", "error_contract"}
        capsules: list[dict[str, Any]] = []
        identities: set[tuple[str, str]] = set()
        for raw in value["capsules"]:
            raw_keys = set(raw) if type(raw) is dict else set()
            if type(raw) is not dict or raw_keys not in (
                identity_keys,
                identity_keys | contract_keys,
            ):
                raise ProductPlanningError("product_planning_catalog_invalid")
            row = _exact_dict(raw, set(raw))
            if (
                any(
                    type(row[name]) is not str or not row[name]
                    for name in identity_keys
                )
                or row["identity_status"] != "formal_exact_version"
                or _DIGEST.fullmatch(row["canonical_hash"]) is None
            ):
                raise ProductPlanningError("product_planning_catalog_invalid")
            identity = (row["capsule_id"], row["version_id"])
            if identity in identities:
                raise ProductPlanningError("product_planning_catalog_invalid")
            identities.add(identity)
            if contract_keys <= set(row):
                try:
                    (
                        row["input_contract"],
                        row["output_contract"],
                        row["error_contract"],
                    ) = normalize_capsule_contracts(
                        row["capability_kind"],
                        row["input_contract"],
                        row["output_contract"],
                        row["error_contract"],
                    )
                except DataContractError as exc:
                    raise ProductPlanningError(
                        "product_planning_catalog_invalid"
                    ) from exc
            capsules.append(dict(row))
        capsules.sort(key=lambda item: (item["capsule_id"], item["version_id"]))
        return {
            "warehouse_revision": value["warehouse_revision"],
            "capsules": capsules,
        }

    @staticmethod
    def _stale_bindings(
        plan: dict[str, Any],
        catalog: dict[str, Any],
    ) -> list[dict[str, str]]:
        exact = {
            (item["capsule_id"], item["version_id"]): item
            for item in catalog["capsules"]
        }
        stale: list[dict[str, str]] = []
        for section in plan["sections"]:
            for work_item in section["work_items"]:
                for binding in work_item["capsule_bindings"]:
                    current = exact.get(
                        (binding["capsule_id"], binding["version_id"])
                    )
                    if (
                        current is None
                        or current["canonical_hash"] != binding["canonical_hash"]
                    ):
                        stale.append(
                            {
                                "work_item_id": work_item["work_item_id"],
                                "capsule_id": binding["capsule_id"],
                                "version_id": binding["version_id"],
                                "reason": "formal_exact_version_no_longer_eligible",
                            }
                        )
        return stale

    def _new_workspace(
        self,
        goal: str,
        model: dict[str, Any],
    ) -> dict[str, Any]:
        now = _now()
        return {
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "workspace_id": "workspace_" + uuid.uuid4().hex,
            "plan_token": "plan_token_" + uuid.uuid4().hex + uuid.uuid4().hex[:16],
            "display_name": goal[:80],
            "goal": goal,
            "goal_digest": _digest(goal),
            "status": "model_probe",
            "phase": "model_probe",
            "created_at": now,
            "updated_at": now,
            "model": {
                key: model[key]
                for key in (
                    "name",
                    "digest",
                    "parameter_count",
                    "parameter_size",
                )
            },
            "outline": None,
            "outline_input_digest": None,
            "outline_response_digest": None,
            "question_history": [],
            "current_question_set": None,
            "answers": [],
            "plan": None,
            "pending_diff": None,
            "pending_revision_feedback": None,
            "confirmation": None,
            "model_calls": [],
            "composition_selection": None,
            "composition_selection_input_digest": None,
            "composition_selection_response_digest": None,
            "experience_query_digest": None,
            "experience_injection_enabled": self._experience_injection_enabled,
            "capability_gap_target_selection": None,
            "blueprint": None,
            "blueprint_input_digest": None,
            "blueprint_response_digest": None,
            "delivery_waves": {},
            "failure_code": None,
        }

    def _workspace_projection(
        self,
        workspace: dict[str, Any],
        catalog: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        plan = copy.deepcopy(workspace.get("plan"))
        question_set = workspace.get("current_question_set")
        pending_diff = workspace.get("pending_diff")
        target_section_id = (
            question_set.get("target_section_id")
            if type(question_set) is dict
            and question_set.get("schema_version")
            == "product_plan_question_set.v2"
            else (
                pending_diff.get("target_section_id")
                if type(pending_diff) is dict
                else None
            )
        )
        completed_sections = (
            [
                checkpoint["section_id"]
                for checkpoint in workspace["section_checkpoints"]
            ]
            if workspace["schema_version"] == LEGACY_WORKSPACE_SCHEMA_VERSION
            else (
                list(SECTION_IDS)
                if type(workspace.get("blueprint")) is dict
                else []
            )
        )
        return {
            "plan_token": workspace["plan_token"],
            "display_name": workspace["display_name"],
            "goal": workspace["goal"],
            "goal_digest": workspace["goal_digest"],
            "status": workspace["status"],
            "phase": workspace["phase"],
            "completed_sections": completed_sections,
            "updated_at": workspace["updated_at"],
            "model": copy.deepcopy(workspace["model"]),
            "target_section_id": target_section_id,
            "question_set": copy.deepcopy(question_set),
            "plan": plan,
            "plan_diff": (
                copy.deepcopy(workspace["pending_diff"]["public_diff"])
                if type(workspace.get("pending_diff")) is dict
                else None
            ),
            "confirmation": copy.deepcopy(workspace.get("confirmation")),
            "capability_gaps": self._capability_gap_views(
                workspace,
                catalog,
            ),
            "capability_replan": self._capability_replan_view(
                workspace,
                catalog,
            ),
            "developer_evidence": self._developer_evidence(workspace),
        }

    def _developer_evidence(self, workspace: dict[str, Any]) -> dict[str, Any]:
        plan = workspace.get("plan")
        return {
            "schema_version": "product_plan_developer_evidence.v1",
            "plan_id": plan.get("plan_id") if type(plan) is dict else None,
            "plan_version": plan.get("plan_version") if type(plan) is dict else None,
            "plan_digest": (
                plan.get("canonical_digest") if type(plan) is dict else None
            ),
            "model": copy.deepcopy(workspace["model"]),
            "planning_rules_version": (
                plan.get("planning_rules_version")
                if type(plan) is dict
                else PLANNING_RULES_VERSION
            ),
            "prompt_version": (
                plan.get("prompt_version")
                if type(plan) is dict
                else self._workspace_prompt_version(workspace)
            ),
            "model_calls": [
                {
                    key: call[key]
                    for key in (
                        "call_type",
                        "input_bytes",
                        "output_bytes",
                        "duration_ms",
                        "structured_response_digest",
                    )
                }
                for call in workspace["model_calls"]
            ],
            "completed_sections": (
                [
                    checkpoint["section_id"]
                    for checkpoint in workspace["section_checkpoints"]
                ]
                if workspace["schema_version"] == LEGACY_WORKSPACE_SCHEMA_VERSION
                else (
                    list(SECTION_IDS)
                    if type(workspace.get("blueprint")) is dict
                    else []
                )
            ),
            "failure_code": workspace.get("failure_code"),
            "contains_raw_prompt": False,
            "contains_raw_response": False,
            "candidate_generated": False,
            "product_generated": False,
            "persistent_write_scope": "product_workspaces_only",
        }

    def _summary(self, workspace: dict[str, Any]) -> dict[str, Any]:
        plan = workspace.get("plan")
        return {
            "plan_token": workspace["plan_token"],
            "display_name": workspace["display_name"],
            "status": workspace["status"],
            "updated_at": workspace["updated_at"],
            "plan_version": plan.get("plan_version") if type(plan) is dict else None,
            "confirmed": workspace["status"] == "confirmed",
        }

    def _capability_replan_handoffs_dir(self) -> Path:
        return self.root / "capability_replan_handoffs"

    def _capability_replan_handoff_path(self, plan_digest: str) -> Path:
        if type(plan_digest) is not str or _DIGEST.fullmatch(plan_digest) is None:
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            )
        return (
            self._capability_replan_handoffs_dir()
            / f"handoff_{plan_digest}.json"
        )

    def _validate_capability_replan_handoff(
        self,
        value: Any,
    ) -> dict[str, Any]:
        keys = {
            "schema_version",
            "source_workspace_id",
            "source_plan_token",
            "source_plan_digest",
            "source_gap_id",
            "projection_digest",
            "authorize_decision_digest",
            "source_proposal_authorization_digest",
            "admission_review_id",
            "admission_digest",
            "publication_review_id",
            "published_capsule",
            "target_offer",
            "target_offer_digest",
            "planning_model",
            "successor_workspace_id",
            "successor_plan_token",
            "authorization_revision",
            "admission_revision_before",
            "admission_revision_after",
            "publication_revision",
            "handoff_catalog_revision",
            "catalog_digest",
            "request_digest",
            "acceptance_suggestions",
            "created_at",
            "handoff_digest",
        }
        if type(value) is not dict or set(value) != keys:
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            )
        row = value
        body = {
            key: item for key, item in row.items() if key != "handoff_digest"
        }
        offer = row["target_offer"]
        if (
            type(offer) is not dict
            or set(offer)
            != {"schema_version", "capability_key", "gap_slot", "members"}
        ):
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            )
        members = offer["members"]
        published = row["published_capsule"]
        model = row["planning_model"]
        request = {
            "plan_token": row["source_plan_token"],
            "plan_digest": row["source_plan_digest"],
            "projection_digest": row["projection_digest"],
        }
        revisions = [
            row["authorization_revision"],
            row["admission_revision_before"],
            row["admission_revision_after"],
            row["publication_revision"],
            row["handoff_catalog_revision"],
        ]
        if (
            row["schema_version"] != CAPABILITY_REPLAN_HANDOFF_VERSION
            or _WORKSPACE_ID.fullmatch(
                str(row["source_workspace_id"])
            )
            is None
            or _PLAN_TOKEN.fullmatch(str(row["source_plan_token"])) is None
            or _DIGEST.fullmatch(str(row["source_plan_digest"])) is None
            or _GAP_ID.fullmatch(str(row["source_gap_id"])) is None
            or any(
                _DIGEST.fullmatch(str(row[key])) is None
                for key in (
                    "projection_digest",
                    "authorize_decision_digest",
                    "source_proposal_authorization_digest",
                    "admission_digest",
                    "target_offer_digest",
                    "catalog_digest",
                    "request_digest",
                    "handoff_digest",
                )
            )
            or any(
                type(row[key]) is not str or not row[key]
                for key in ("admission_review_id", "publication_review_id")
            )
            or offer["schema_version"] != CAPABILITY_REPLAN_OFFER_VERSION
            or type(offer["capability_key"]) is not str
            or not offer["capability_key"]
            or offer["gap_slot"]
            not in {
                "only_computation",
                "before_existing_computation",
                "after_existing_computation",
            }
            or type(members) is not list
            or len(members) not in {2, 3, 4}
            or any(
                type(member) is not dict
                or set(member)
                != {
                    "capsule_id",
                    "version_id",
                    "canonical_hash",
                    "capability_kind",
                    "role_key",
                    "variant_key",
                }
                for member in members
            )
            or [
                self._gap_capsule_identity(member) for member in members
            ]
            != members
            or len(
                {
                    (member["capsule_id"], member["version_id"])
                    for member in members
                }
            )
            != len(members)
            or type(published) is not dict
            or set(published)
            != {
                "capsule_id",
                "version_id",
                "canonical_hash",
                "capability_kind",
                "role_key",
                "variant_key",
            }
            or self._gap_capsule_identity(published) != published
            or published["capability_kind"] != "computation"
            or published not in members
            or row["target_offer_digest"] != _digest(offer)
            or type(model) is not dict
            or set(model)
            != {"name", "digest", "parameter_count", "parameter_size"}
            or type(model["name"]) is not str
            or not model["name"]
            or _DIGEST.fullmatch(str(model["digest"])) is None
            or type(model["parameter_count"]) is not int
            or not 0 < model["parameter_count"] <= MAX_MODEL_PARAMETERS
            or (
                model["parameter_size"] is not None
                and type(model["parameter_size"]) is not str
            )
            or _WORKSPACE_ID.fullmatch(
                str(row["successor_workspace_id"])
            )
            is None
            or _PLAN_TOKEN.fullmatch(
                str(row["successor_plan_token"])
            )
            is None
            or any(type(item) is not int or item < 0 for item in revisions)
            or row["authorization_revision"]
            != row["admission_revision_before"]
            or row["admission_revision_after"]
            != row["admission_revision_before"] + 1
            or row["publication_revision"]
            != row["admission_revision_after"] + 1
            or row["handoff_catalog_revision"]
            != row["publication_revision"]
            or type(row["acceptance_suggestions"]) is not list
            or len(row["acceptance_suggestions"]) > MAX_CANDIDATE_ACCEPTANCE_CASES
            or any(
                type(item) is not dict
                or set(item) != {"input", "expected_output"}
                or type(item["input"]) is not dict
                or type(item["expected_output"]) is not dict
                for item in row["acceptance_suggestions"]
            )
            or type(row["created_at"]) is not str
            or not row["created_at"]
            or row["request_digest"] != _digest(request)
            or row["handoff_digest"] != _digest(body)
        ):
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            )
        return row

    def _read_capability_replan_handoff(
        self,
        source: dict[str, Any],
    ) -> dict[str, Any] | None:
        plan = source.get("plan")
        if type(plan) is not dict:
            return None
        path = self._capability_replan_handoff_path(
            plan["canonical_digest"]
        )
        if not path.exists() and not path.is_symlink():
            return None
        row = self._validate_capability_replan_handoff(
            self._read_json(path)
        )
        if (
            row["source_workspace_id"] != source["workspace_id"]
            or row["source_plan_token"] != source["plan_token"]
            or row["source_plan_digest"] != plan["canonical_digest"]
        ):
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            )
        return row

    def _capability_replan_for_successor(
        self,
        workspace: dict[str, Any],
    ) -> dict[str, Any] | None:
        directory = self._capability_replan_handoffs_dir()
        if not directory.exists() and not directory.is_symlink():
            return None
        self._assert_no_symlink_components(directory)
        if directory.is_symlink() or not directory.is_dir():
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            )
        matches: list[dict[str, Any]] = []
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if (
                _CAPABILITY_REPLAN_HANDOFF_FILENAME.fullmatch(path.name)
                is None
                or path.is_symlink()
                or not path.is_file()
            ):
                raise ProductPlanningError(
                    "capability_replan_handoff_conflict"
                )
            row = self._validate_capability_replan_handoff(
                self._read_json(path)
            )
            if row["successor_plan_token"] == workspace["plan_token"]:
                matches.append(row)
        if len(matches) > 1:
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            )
        return matches[0] if matches else None

    def _capability_replan_for_workspace(
        self,
        workspace: dict[str, Any],
    ) -> dict[str, Any] | None:
        direct = self._read_capability_replan_handoff(workspace)
        return (
            direct
            if direct is not None
            else self._capability_replan_for_successor(workspace)
        )

    def _capability_replan_view(
        self,
        workspace: dict[str, Any],
        catalog: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        try:
            handoff = self._capability_replan_for_workspace(workspace)
            if handoff is None:
                return None
            status = "started"
            if catalog is not None:
                self._validate_capability_replan_current(
                    handoff,
                    catalog,
                )
        except ProductPlanningError as exc:
            return {
                "schema_version": CAPABILITY_REPLAN_HANDOFF_VERSION,
                "status": exc.code,
                "source_gap_id": None,
                "role_order": [],
                "successor_plan_token": None,
                "handoff_digest": None,
                "acceptance_suggestions": [],
            }
        return {
            "schema_version": CAPABILITY_REPLAN_HANDOFF_VERSION,
            "status": status,
            "source_gap_id": handoff["source_gap_id"],
            "role_order": [
                member["role_key"]
                for member in handoff["target_offer"]["members"]
            ],
            "successor_plan_token": handoff["successor_plan_token"],
            "handoff_digest": handoff["handoff_digest"],
            "acceptance_suggestions": copy.deepcopy(
                handoff["acceptance_suggestions"]
            ),
        }

    def _workspace_dir(self, workspace_id: str) -> Path:
        if _WORKSPACE_ID.fullmatch(workspace_id) is None:
            raise ProductPlanningError("product_workspace_invalid")
        return self.root / workspace_id

    def _save_workspace(self, workspace: dict[str, Any]) -> None:
        self._validate_workspace(workspace)
        self._ensure_directory(self.root)
        directory = self._workspace_dir(workspace["workspace_id"])
        self._ensure_directory(directory)
        self._atomic_write(directory / "workspace.json", workspace)

    def _workspace_by_token(self, plan_token: str) -> dict[str, Any]:
        if type(plan_token) is not str or _PLAN_TOKEN.fullmatch(plan_token) is None:
            raise ProductPlanningError("product_plan_token_invalid")
        for workspace in self._workspaces():
            if workspace["plan_token"] == plan_token:
                return workspace
        raise ProductPlanningError("product_plan_workspace_not_found")

    def _workspaces(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        self._ensure_directory(self.root)
        result: list[dict[str, Any]] = []
        try:
            entries = sorted(self.root.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            raise ProductPlanningError("product_planning_state_unavailable") from exc
        for entry in entries:
            if _WORKSPACE_ID.fullmatch(entry.name) is None:
                continue
            try:
                if entry.is_symlink() or not entry.is_dir():
                    continue
                workspace = self._read_json(entry / "workspace.json")
                self._validate_workspace(
                    workspace,
                    expected_workspace_id=entry.name,
                )
                if workspace["status"] == "confirmed":
                    self._validate_confirmed_snapshot(workspace)
                if workspace["status"] in _RUNNING_STATES:
                    workspace["status"] = "interrupted"
                    workspace["updated_at"] = _now()
                    self._save_workspace(workspace)
                result.append(workspace)
            except (OSError, ProductPlanningError, ValueError, json.JSONDecodeError):
                continue
        return result

    def _project_experience_root(self) -> Path:
        return self.root.parent / "product_experience"

    def _project_experience_scope(self) -> dict[str, Any]:
        root = self._project_experience_root()
        self._ensure_directory(root)
        self._ensure_directory(root / "records")
        allowed = {"project_scope.json", "records"}
        if {path.name for path in root.iterdir()} - allowed:
            raise ProductPlanningError("project_experience_scope_invalid")
        path = root / "project_scope.json"
        if path.exists() or path.is_symlink():
            try:
                return validate_project_experience_scope(
                    self._read_json(path)
                )
            except ExperienceError as exc:
                raise ProductPlanningError(
                    "project_experience_scope_invalid"
                ) from exc
        scope = build_project_experience_scope(
            f"project_scope_{uuid.uuid4().hex}",
            _now(),
        )
        self._write_immutable(path, scope)
        return scope

    def _project_experience_workspace(
        self,
        workspace_id: str,
    ) -> dict[str, Any]:
        path = self._workspace_dir(workspace_id) / "workspace.json"
        workspace = self._read_json(path)
        self._validate_workspace(
            workspace,
            expected_workspace_id=workspace_id,
        )
        if workspace.get("status") != "confirmed":
            raise ProductPlanningError(
                "project_experience_record_binding_invalid"
            )
        self._validate_confirmed_snapshot(workspace)
        return workspace

    def _project_experience_records(
        self,
        project_scope_digest: str,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        root = self._project_experience_root() / "records"
        self._assert_no_symlink_components(root)
        if root.is_symlink() or not root.is_dir():
            raise ProductPlanningError("project_experience_record_invalid")
        result: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for directory in sorted(root.iterdir(), key=lambda item: item.name):
            if (
                _WORKSPACE_ID.fullmatch(directory.name) is None
                or directory.is_symlink()
                or not directory.is_dir()
            ):
                raise ProductPlanningError(
                    "project_experience_record_invalid"
                )
            seen: set[str] = set()
            for path in sorted(directory.iterdir(), key=lambda item: item.name):
                milestone = path.stem
                if (
                    path.suffix != ".json"
                    or milestone not in PROJECT_EXPERIENCE_MILESTONES
                    or milestone in seen
                    or path.is_symlink()
                    or not path.is_file()
                ):
                    raise ProductPlanningError(
                        "project_experience_record_invalid"
                    )
                seen.add(milestone)
                try:
                    record = validate_project_experience_record(
                        self._read_json(path)
                    )
                except ExperienceError as exc:
                    raise ProductPlanningError(
                        "project_experience_record_invalid"
                    ) from exc
                if (
                    record["source_workspace_id"] != directory.name
                    or record["project_scope_digest"]
                    != project_scope_digest
                ):
                    raise ProductPlanningError(
                        "project_experience_record_binding_invalid"
                    )
                result.append(
                    (
                        record,
                        self._project_experience_workspace(directory.name),
                    )
                )
            if not seen:
                raise ProductPlanningError(
                    "project_experience_record_invalid"
                )
        return result

    def _product_experience_query_path(
        self,
        workspace: dict[str, Any],
    ) -> Path:
        return self._workspace_dir(workspace["workspace_id"]) / (
            "experience_query.json"
        )

    def _validate_frozen_product_experience_query(
        self,
        workspace: dict[str, Any],
    ) -> dict[str, Any] | None:
        if workspace["schema_version"] not in EXPERIENCE_WORKSPACE_SCHEMA_VERSIONS:
            return None
        digest = workspace["experience_query_digest"]
        if digest is None:
            return None
        try:
            query = validate_product_experience_query(
                self._read_json(
                    self._product_experience_query_path(workspace)
                )
            )
        except (ExperienceError, ProductPlanningError) as exc:
            raise ProductPlanningError(
                "project_experience_query_invalid"
            ) from exc
        if (
            query["canonical_digest"] != digest
            or query["query_goal_digest"] != workspace["goal_digest"]
            or query["exact_model_name"] != workspace["model"]["name"]
            or query["exact_model_digest"] != workspace["model"]["digest"]
        ):
            raise ProductPlanningError("project_experience_query_invalid")
        return query

    def _verify_frozen_product_experience_query(
        self,
        workspace: dict[str, Any],
        query: dict[str, Any],
    ) -> None:
        scope = self._project_experience_scope()
        if query["project_scope_digest"] != scope["canonical_digest"]:
            raise ProductPlanningError("project_experience_scope_mismatch")
        records = self._project_experience_records(
            scope["canonical_digest"]
        )
        by_digest: dict[str, dict[str, Any]] = {}
        for record, _historical_workspace in records:
            if record["record_digest"] in by_digest:
                raise ProductPlanningError(
                    "project_experience_record_invalid"
                )
            by_digest[record["record_digest"]] = record
        for item in query["cases"]:
            record = by_digest.get(item["record_digest"])
            if (
                record is None
                or record["source_workspace_id"] == workspace["workspace_id"]
                or record["milestone"] != item["milestone"]
                or record["safe_case"] != item["safe_case"]
                or record["exact_model_name"] != workspace["model"]["name"]
                or record["exact_model_digest"]
                != workspace["model"]["digest"]
            ):
                raise ProductPlanningError(
                    "project_experience_record_binding_invalid"
                )

    def _freeze_product_experience_query(
        self,
        workspace: dict[str, Any],
    ) -> dict[str, Any]:
        if workspace["schema_version"] not in EXPERIENCE_WORKSPACE_SCHEMA_VERSIONS:
            raise ProductPlanningError("project_experience_query_invalid")
        query = self._validate_frozen_product_experience_query(workspace)
        if query is None:
            scope = self._project_experience_scope()
            records = self._project_experience_records(
                scope["canonical_digest"]
            )
            try:
                query = build_product_experience_query(
                    workspace=workspace,
                    project_scope_digest=scope["canonical_digest"],
                    records_with_workspaces=records,
                    limit=3,
                )
            except ExperienceError as exc:
                raise ProductPlanningError(str(exc)) from exc
            path = self._product_experience_query_path(workspace)
            if path.exists() or path.is_symlink():
                try:
                    existing = validate_product_experience_query(
                        self._read_json(path)
                    )
                except (ExperienceError, ProductPlanningError) as exc:
                    raise ProductPlanningError(
                        "project_experience_query_invalid"
                    ) from exc
                if existing != query:
                    raise ProductPlanningError(
                        "project_experience_query_conflict"
                    )
            else:
                self._write_immutable(path, query)
            workspace["experience_query_digest"] = query[
                "canonical_digest"
            ]
            workspace["updated_at"] = _now()
            self._save_workspace(workspace)
        self._verify_frozen_product_experience_query(workspace, query)
        return query

    def _workspace_experience_cases(
        self,
        workspace: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if workspace["schema_version"] not in EXPERIENCE_WORKSPACE_SCHEMA_VERSIONS:
            return []
        query = self._freeze_product_experience_query(workspace)
        if workspace["experience_injection_enabled"] is not True:
            return []
        try:
            return build_product_experience_model_cases(query)
        except ExperienceError as exc:
            raise ProductPlanningError(str(exc)) from exc

    def _validate_workspace(
        self,
        workspace: Any,
        *,
        expected_workspace_id: str | None = None,
    ) -> None:
        common = {
            "schema_version",
            "workspace_id",
            "plan_token",
            "display_name",
            "goal",
            "goal_digest",
            "status",
            "phase",
            "created_at",
            "updated_at",
            "model",
            "outline",
            "outline_input_digest",
            "outline_response_digest",
            "question_history",
            "current_question_set",
            "answers",
            "plan",
            "pending_diff",
            "pending_revision_feedback",
            "confirmation",
            "model_calls",
            "delivery_waves",
            "failure_code",
        }
        schema_version = (
            workspace.get("schema_version") if type(workspace) is dict else None
        )
        if schema_version == LEGACY_WORKSPACE_SCHEMA_VERSION:
            required = {*common, "section_checkpoints"}
        else:
            required = {
                *common,
                "blueprint",
                "blueprint_input_digest",
                "blueprint_response_digest",
            }
            if schema_version in LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSIONS:
                required.update(
                    {
                        "composition_selection",
                        "composition_selection_input_digest",
                        "composition_selection_response_digest",
                    }
                )
            if schema_version in TARGET_SELECTION_WORKSPACE_SCHEMA_VERSIONS:
                required.add("capability_gap_target_selection")
            if schema_version in EXPERIENCE_WORKSPACE_SCHEMA_VERSIONS:
                required.update(
                    {
                        "experience_query_digest",
                        "experience_injection_enabled",
                    }
                )
        if (
            type(workspace) is not dict
            or set(workspace) != required
            or schema_version
            not in {
                LEGACY_WORKSPACE_SCHEMA_VERSION,
                DIRECT_BLUEPRINT_WORKSPACE_SCHEMA_VERSION,
                LEGACY_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION,
                PREVIOUS_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION,
                PREVIOUS_GAP_WORKSPACE_SCHEMA_VERSION,
                PREVIOUS_TARGET_SELECTION_WORKSPACE_SCHEMA_VERSION,
                PREVIOUS_REQUIREMENT_COVERAGE_WORKSPACE_SCHEMA_VERSION,
                WORKSPACE_SCHEMA_VERSION,
            }
            or _WORKSPACE_ID.fullmatch(str(workspace["workspace_id"])) is None
            or (
                expected_workspace_id is not None
                and workspace["workspace_id"] != expected_workspace_id
            )
            or _PLAN_TOKEN.fullmatch(str(workspace["plan_token"])) is None
            or type(workspace["display_name"]) is not str
            or not workspace["display_name"]
            or type(workspace["goal"]) is not str
            or workspace["goal_digest"] != _digest(workspace["goal"])
            or type(workspace["created_at"]) is not str
            or type(workspace["updated_at"]) is not str
            or workspace["status"]
            not in {
                "model_probe",
                "planning",
                "needs_clarification",
                "plan_review",
                "plan_diff_review",
                "confirmed",
                "interrupted",
                "failed",
            }
            or (
                workspace["phase"] is not None
                and workspace["phase"] not in PRODUCT_PLANNING_PHASES
            )
            or type(workspace["question_history"]) is not list
            or type(workspace["answers"]) is not list
            or type(workspace["model_calls"]) is not list
            or (
                schema_version == LEGACY_WORKSPACE_SCHEMA_VERSION
                and type(workspace["section_checkpoints"]) is not list
            )
            or type(workspace["delivery_waves"]) is not dict
            or (
                workspace["pending_revision_feedback"] is not None
                and (
                    type(workspace["pending_revision_feedback"]) is not str
                    or not 1 <= len(workspace["pending_revision_feedback"]) <= MAX_FEEDBACK_CHARS
                )
            )
            or (
                workspace["failure_code"] is not None
                and type(workspace["failure_code"]) is not str
            )
            or (
                schema_version in EXPERIENCE_WORKSPACE_SCHEMA_VERSIONS
                and (
                    type(workspace["experience_injection_enabled"]) is not bool
                    or (
                        workspace["experience_query_digest"] is not None
                        and _DIGEST.fullmatch(
                            str(workspace["experience_query_digest"])
                        )
                        is None
                    )
                    or (
                        workspace["experience_query_digest"] is None
                        and workspace["model_calls"]
                    )
                )
            )
        ):
            raise ProductPlanningError("product_workspace_corrupt")
        model = _stored_exact(
            workspace["model"],
            {"name", "digest", "parameter_count", "parameter_size"},
        )
        if (
            type(model["name"]) is not str
            or not model["name"]
            or _DIGEST.fullmatch(str(model["digest"])) is None
            or type(model["parameter_count"]) is not int
            or not 0 < model["parameter_count"] <= MAX_MODEL_PARAMETERS
            or (
                model["parameter_size"] is not None
                and type(model["parameter_size"]) is not str
            )
        ):
            raise ProductPlanningError("product_workspace_corrupt")
        self._validate_stored_outline(workspace["outline"])
        outline_input_digest = workspace["outline_input_digest"]
        outline_response_digest = workspace["outline_response_digest"]
        stored_plan = workspace.get("plan")
        stored_rules_version = (
            stored_plan.get("planning_rules_version")
            if type(stored_plan) is dict
            and stored_plan.get("planning_rules_version")
            in SUPPORTED_PLANNING_RULES_VERSIONS
            else self._workspace_rules_version(workspace)
        )
        stored_prompt_version = (
            stored_plan.get("prompt_version")
            if type(stored_plan) is dict
            else self._workspace_prompt_version(workspace)
        )
        if workspace["outline"] is None:
            if outline_input_digest is not None or outline_response_digest is not None:
                raise ProductPlanningError("product_workspace_corrupt")
        elif (
            _DIGEST.fullmatch(str(outline_input_digest)) is None
            or outline_input_digest
            != self._outline_input_digest(
                workspace,
                stored_rules_version,
                stored_prompt_version,
            )
            or _DIGEST.fullmatch(str(outline_response_digest)) is None
            or not any(
                call["call_type"] == "requirements_outline"
                and call["structured_response_digest"] == outline_response_digest
                for call in workspace["model_calls"]
            )
        ):
            raise ProductPlanningError("product_workspace_corrupt")
        if (
            any(
                type(item) is not str or _DIGEST.fullmatch(item) is None
                for item in workspace["question_history"]
            )
            or len(set(workspace["question_history"]))
            != len(workspace["question_history"])
        ):
            raise ProductPlanningError("product_workspace_corrupt")
        self._validate_stored_question_set(workspace["current_question_set"])
        self._validate_stored_answers(workspace["answers"])
        if schema_version in EXPERIENCE_WORKSPACE_SCHEMA_VERSIONS:
            self._validate_frozen_product_experience_query(workspace)
        if schema_version in TARGET_SELECTION_WORKSPACE_SCHEMA_VERSIONS:
            self._validate_capability_gap_target_selection(
                workspace["capability_gap_target_selection"]
            )
        for call_index, call in enumerate(workspace["model_calls"]):
            call_type = call.get("call_type") if type(call) is dict else None
            revision_schema_version = REVISION_SCHEMA_VERSIONS.get(str(call_type))
            is_legacy_revision_branch = (
                revision_schema_version is not None
                and call_type not in {"plan_revision", "plan_revision_intent"}
                and "classified_intent" in call
            )
            is_change_branch = call_type == "plan_revision_change"
            keys = {
                "call_type",
                "input_bytes",
                "output_bytes",
                "duration_ms",
                "structured_response_digest",
            }
            if revision_schema_version is not None:
                keys.update(
                    {
                        "base_plan_digest",
                        "revision_request_digest",
                        "model_name",
                        "model_digest",
                        "prompt_version",
                        "schema_version",
                    }
                )
            if is_legacy_revision_branch:
                keys.update({"classified_intent", "intent_response_digest"})
            if is_change_branch:
                keys.add("branch_outcome")
            row = _stored_exact(
                call,
                keys,
            )
            if (
                type(row["call_type"]) is not str
                or any(type(row[key]) is not int or row[key] < 0 for key in ("input_bytes", "output_bytes", "duration_ms"))
                or _DIGEST.fullmatch(str(row["structured_response_digest"])) is None
                or (
                    revision_schema_version is not None
                    and (
                        _DIGEST.fullmatch(str(row["base_plan_digest"])) is None
                        or _DIGEST.fullmatch(str(row["revision_request_digest"])) is None
                        or row["model_name"] != workspace["model"]["name"]
                        or row["model_digest"] != workspace["model"]["digest"]
                        or (
                            row["prompt_version"],
                            row["schema_version"],
                        )
                        not in (
                            {
                                (
                                    REVISION_PROMPT_VERSIONS[row["call_type"]],
                                    revision_schema_version,
                                ),
                                (
                                    "product_plan_revision_intent_prompt.v1",
                                    "product_plan_revision_intent.v1",
                                ),
                            }
                            if call_type == "plan_revision_intent"
                            else (
                                {
                                    (
                                        REVISION_PROMPT_VERSIONS[row["call_type"]],
                                        revision_schema_version,
                                    ),
                                    (
                                        "product_plan_revision_proposal_prompt.v2",
                                        "product_plan_revision_proposal.v2",
                                    ),
                                    (
                                        "product_plan_revision_proposal_prompt.v1",
                                        "product_plan_revision_proposal.v1",
                                    ),
                                }
                                if call_type == "plan_revision_proposal"
                                else {
                                    (
                                        REVISION_PROMPT_VERSIONS[row["call_type"]],
                                        revision_schema_version,
                                    )
                                }
                            )
                        )
                        or (
                            is_legacy_revision_branch
                            and (
                                row["classified_intent"]
                                != row["call_type"].removeprefix("plan_revision_")
                                or (
                                    is_change_branch
                                    and row["branch_outcome"]
                                    not in {"modification", "needs_clarification"}
                                )
                                or _DIGEST.fullmatch(
                                    str(row["intent_response_digest"])
                                )
                                is None
                                or call_index == 0
                                or type(workspace["model_calls"][call_index - 1])
                                is not dict
                                or workspace["model_calls"][call_index - 1].get(
                                    "call_type"
                                )
                                != "plan_revision_intent"
                                or workspace["model_calls"][call_index - 1].get(
                                    "structured_response_digest"
                                )
                                != row["intent_response_digest"]
                                or workspace["model_calls"][call_index - 1].get(
                                    "base_plan_digest"
                                )
                                != row["base_plan_digest"]
                                or workspace["model_calls"][call_index - 1].get(
                                    "revision_request_digest"
                                )
                                != row["revision_request_digest"]
                            )
                        )
                    )
                )
            ):
                raise ProductPlanningError("product_workspace_corrupt")
        if schema_version == LEGACY_WORKSPACE_SCHEMA_VERSION:
            self._validate_section_checkpoints(workspace)
        else:
            if schema_version in LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSIONS:
                self._validate_stored_composition_selection(workspace)
            self._validate_stored_blueprint(workspace)
            if schema_version in LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSIONS and (
                (
                    workspace["blueprint"] is not None
                    and workspace["composition_selection"] is None
                )
                or (
                    type(workspace["blueprint"]) is dict
                    and workspace["blueprint"].get("schema_version")
                    != "product_plan_blueprint.v2"
                )
            ):
                raise ProductPlanningError("product_workspace_corrupt")
        plan = workspace["plan"]
        delivery_waves = workspace["delivery_waves"]
        if plan is None and delivery_waves:
            raise ProductPlanningError("product_workspace_corrupt")
        if plan is not None:
            try:
                self._validate_plan(plan)
            except ProductPlanningError as exc:
                raise ProductPlanningError("product_workspace_corrupt") from exc
            if (
                (
                    schema_version == LEGACY_WORKSPACE_SCHEMA_VERSION
                    and plan["schema_version"] != LEGACY_PLAN_SCHEMA_VERSION
                )
                or (
                    schema_version
                    in {
                        DIRECT_BLUEPRINT_WORKSPACE_SCHEMA_VERSION,
                        LEGACY_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION,
                        PREVIOUS_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION,
                        PREVIOUS_GAP_WORKSPACE_SCHEMA_VERSION,
                        PREVIOUS_TARGET_SELECTION_WORKSPACE_SCHEMA_VERSION,
                        PREVIOUS_REQUIREMENT_COVERAGE_WORKSPACE_SCHEMA_VERSION,
                        WORKSPACE_SCHEMA_VERSION,
                    }
                    and plan["schema_version"] != PLAN_SCHEMA_VERSION
                )
                or
                plan["goal"] != workspace["goal"]
                or plan["goal_digest"] != workspace["goal_digest"]
                or plan["model"] != workspace["model"]
                or workspace["answers"][: len(plan["planning_answers"])]
                != plan["planning_answers"]
                or workspace["outline"] is None
                or set(plan["structured_response_digests"])
                - {
                    call["structured_response_digest"]
                    for call in workspace["model_calls"]
                }
            ):
                raise ProductPlanningError("product_workspace_corrupt")
            work_item_ids = {
                item["work_item_id"]
                for section in plan["sections"]
                for item in section["work_items"]
            }
            if (
                set(delivery_waves) != work_item_ids
                or any(
                    type(wave) is not int or wave not in {1, 2, 3, 4}
                    for wave in delivery_waves.values()
                )
            ):
                raise ProductPlanningError("product_workspace_corrupt")
            self._validate_dependency_compilation(plan, delivery_waves)
        pending = workspace["pending_diff"]
        if pending is not None:
            if type(plan) is not dict:
                raise ProductPlanningError("product_workspace_corrupt")
            try:
                self._validate_pending_diff(plan, pending)
            except ProductPlanningError as exc:
                raise ProductPlanningError("product_workspace_corrupt") from exc
            if (
                type(pending.get("edit_scope")) is dict
                and pending.get("base_delivery_waves") != delivery_waves
            ):
                raise ProductPlanningError("product_workspace_corrupt")
            if pending["proposed_plan"]["planning_answers"] != workspace["answers"]:
                raise ProductPlanningError("product_workspace_corrupt")
        self._validate_stored_confirmation(workspace["confirmation"], plan)
        question_set = workspace["current_question_set"]
        if type(question_set) is dict and question_set["digest"] not in workspace["question_history"]:
            raise ProductPlanningError("product_workspace_corrupt")
        if schema_version in TARGET_SELECTION_WORKSPACE_SCHEMA_VERSIONS:
            target_selection = (
                self._validate_capability_gap_target_selection(
                    workspace["capability_gap_target_selection"]
                )
            )
            target_answers = [
                answer
                for answer in workspace["answers"]
                if answer["purpose"] == "capability_gap_target"
            ]
            if (
                (
                    type(question_set) is dict
                    and question_set.get("purpose")
                    == "capability_gap_target"
                    and target_selection is not None
                )
                or (target_selection is None and target_answers)
                or (
                    target_selection is not None
                    and (
                        len(target_answers) != 1
                        or target_answers[0]["question_set_digest"]
                        != target_selection["question_set_digest"]
                        or target_answers[0]["answers_digest"]
                        != target_selection["user_answer_digest"]
                    )
                )
            ):
                raise ProductPlanningError("product_workspace_corrupt")
        status = workspace["status"]
        if (
            (status == "needs_clarification" and type(question_set) is not dict)
            or (status == "plan_review" and (type(plan) is not dict or pending is not None))
            or (status == "plan_diff_review" and (type(plan) is not dict or type(pending) is not dict))
            or (
                status == "confirmed"
                and (type(plan) is not dict or type(workspace["confirmation"]) is not dict or pending is not None)
            )
            or (
                status in {"plan_review", "plan_diff_review", "confirmed"}
                and question_set is not None
            )
            or (
                status in {"plan_review", "confirmed"}
                and type(plan) is dict
                and plan["planning_answers"]
                != self._planning_answers(workspace)
            )
        ):
            raise ProductPlanningError("product_workspace_corrupt")

    def _validate_stored_outline(self, value: Any) -> None:
        if value is None:
            return
        row = _stored_exact(
            value,
            {
                "schema_version",
                "product_name",
                "language",
                "requirements",
                "needs_clarification",
                "questions",
            },
        )
        if (
            row["schema_version"] != "product_plan_outline.v1"
            or type(row["product_name"]) is not str
            or row["language"] not in {"zh", "en"}
            or type(row["needs_clarification"]) is not bool
            or type(row["requirements"]) is not list
            or not 1 <= len(row["requirements"]) <= 64
            or type(row["questions"]) is not list
            or row["needs_clarification"] != bool(row["questions"])
        ):
            raise ProductPlanningError("product_workspace_corrupt")
        refs: set[str] = set()
        for requirement in row["requirements"]:
            item = _stored_exact(requirement, {"ref", "statement", "source"})
            if (
                _SAFE_REF.fullmatch(str(item["ref"])) is None
                or item["ref"] in refs
                or type(item["statement"]) is not str
                or item["source"] not in {"goal", "planning_answer"}
            ):
                raise ProductPlanningError("product_workspace_corrupt")
            refs.add(item["ref"])
        self._validate_stored_questions(row["questions"])

    def _validate_stored_questions(self, questions: Any) -> None:
        if type(questions) is not list or len(questions) > 3:
            raise ProductPlanningError("product_workspace_corrupt")
        seen: set[str] = set()
        for question in questions:
            row = _stored_exact(question, {"ref", "prompt", "options", "allow_custom"})
            if (
                _SAFE_REF.fullmatch(str(row["ref"])) is None
                or row["ref"] in seen
                or type(row["prompt"]) is not str
                or row["allow_custom"] is not True
                or type(row["options"]) is not list
                or not 2 <= len(row["options"]) <= 3
            ):
                raise ProductPlanningError("product_workspace_corrupt")
            seen.add(row["ref"])
            option_refs: set[str] = set()
            for index, option in enumerate(row["options"]):
                item = _stored_exact(
                    option,
                    {"ref", "label", "impact", "recommended", "forms_gap"},
                )
                if (
                    _SAFE_REF.fullmatch(str(item["ref"])) is None
                    or item["ref"] in option_refs
                    or type(item["label"]) is not str
                    or type(item["impact"]) is not str
                    or item["recommended"] is (index != 0)
                    or type(item["forms_gap"]) is not bool
                ):
                    raise ProductPlanningError("product_workspace_corrupt")
                option_refs.add(item["ref"])

    def _validate_stored_question_set(self, value: Any) -> None:
        if value is None:
            return
        if type(value) is not dict:
            raise ProductPlanningError("product_workspace_corrupt")
        schema_version = value.get("schema_version")
        if schema_version == "product_plan_question_set.v1":
            row = _stored_exact(
                value,
                {"schema_version", "purpose", "questions", "digest"},
            )
            target_section_id = None
        elif schema_version == "product_plan_question_set.v2":
            row = _stored_exact(
                value,
                {
                    "schema_version",
                    "purpose",
                    "target_section_id",
                    "questions",
                    "digest",
                },
            )
            target_section_id = row["target_section_id"]
        elif schema_version == "product_plan_question_set.v3":
            row = _stored_exact(
                value,
                {
                    "schema_version",
                    "purpose",
                    "warehouse_revision",
                    "catalog_digest",
                    "questions",
                    "digest",
                },
            )
            target_section_id = None
        else:
            raise ProductPlanningError("product_workspace_corrupt")
        if (
            row["purpose"]
            not in {"initial", "revision", "capability_gap_target"}
            or (
                schema_version == "product_plan_question_set.v2"
                and (
                    row["purpose"] != "revision"
                    or target_section_id not in SECTION_IDS
                )
            )
            or (
                schema_version == "product_plan_question_set.v3"
                and (
                    row["purpose"] != "capability_gap_target"
                    or type(row["warehouse_revision"]) is not int
                    or row["warehouse_revision"] < 0
                    or _DIGEST.fullmatch(
                        str(row["catalog_digest"])
                    )
                    is None
                )
            )
            or type(row["questions"]) is not list
            or (
                schema_version == "product_plan_question_set.v3"
                and len(row["questions"]) != 1
            )
            or (
                schema_version != "product_plan_question_set.v3"
                and not 1 <= len(row["questions"]) <= 3
            )
            or row["digest"] != _digest({key: item for key, item in row.items() if key != "digest"})
        ):
            raise ProductPlanningError("product_workspace_corrupt")
        seen: set[str] = set()
        for question in row["questions"]:
            item = _stored_exact(
                question,
                {"question_id", "prompt", "options", "allow_custom"},
            )
            if (
                not str(item["question_id"]).startswith("question_")
                or item["question_id"] in seen
                or type(item["prompt"]) is not str
                or (
                    schema_version == "product_plan_question_set.v3"
                    and item["allow_custom"] is not False
                )
                or (
                    schema_version != "product_plan_question_set.v3"
                    and item["allow_custom"] is not True
                )
                or type(item["options"]) is not list
                or not 2 <= len(item["options"]) <= 3
            ):
                raise ProductPlanningError("product_workspace_corrupt")
            seen.add(item["question_id"])
            option_ids: set[str] = set()
            for index, option in enumerate(item["options"]):
                current = _stored_exact(
                    option,
                    {"option_id", "label", "impact", "recommended", "forms_gap"},
                )
                if (
                    not str(current["option_id"]).startswith("option_")
                    or current["option_id"] in option_ids
                    or type(current["label"]) is not str
                    or type(current["impact"]) is not str
                    or (
                        schema_version == "product_plan_question_set.v3"
                        and current["recommended"] is not False
                    )
                    or (
                        schema_version != "product_plan_question_set.v3"
                        and current["recommended"] is (index != 0)
                    )
                    or type(current["forms_gap"]) is not bool
                ):
                    raise ProductPlanningError("product_workspace_corrupt")
                option_ids.add(current["option_id"])

    def _validate_stored_answers(self, value: Any) -> None:
        if type(value) is not list:
            raise ProductPlanningError("product_workspace_corrupt")
        for submission in value:
            row = _stored_exact(
                submission,
                {
                    "question_set_digest",
                    "purpose",
                    "answers",
                    "submitted_at",
                    "answers_digest",
                },
            )
            if (
                _DIGEST.fullmatch(str(row["question_set_digest"])) is None
                or row["purpose"]
                not in {
                    "initial",
                    "revision",
                    "capability_gap_target",
                }
                or type(row["answers"]) is not list
                or type(row["submitted_at"]) is not str
                or row["answers_digest"] != _digest(row["answers"])
            ):
                raise ProductPlanningError("product_workspace_corrupt")
            question_ids: set[str] = set()
            for answer in row["answers"]:
                item = _stored_exact(
                    answer,
                    {"question_id", "source", "value", "forms_gap", "value_digest"},
                )
                if (
                    not str(item["question_id"]).startswith("question_")
                    or item["question_id"] in question_ids
                    or item["source"] not in {"option", "custom"}
                    or type(item["value"]) is not str
                    or type(item["forms_gap"]) is not bool
                    or item["value_digest"] != _digest(item["value"])
                ):
                    raise ProductPlanningError("product_workspace_corrupt")
                question_ids.add(item["question_id"])

    def _outline_input_digest(
        self,
        workspace: dict[str, Any],
        planning_rules_version: str | None = None,
        prompt_version: str | None = None,
    ) -> str:
        planning_rules_version = (
            planning_rules_version or self._workspace_rules_version(workspace)
        )
        prompt_version = prompt_version or self._workspace_prompt_version(workspace)
        return _digest(
            {
                "schema_version": "product_plan_outline_input.v1",
                "goal_digest": workspace["goal_digest"],
                "planning_answers": self._planning_answers(workspace),
                "model": workspace["model"],
                "planning_rules_version": planning_rules_version,
                "prompt_version": prompt_version,
            }
        )

    def _section_input_digest(
        self,
        workspace: dict[str, Any],
        outline: dict[str, Any],
        section_id: str,
        candidate_refs: list[str],
        planning_rules_version: str | None = None,
        prompt_version: str | None = None,
    ) -> str:
        planning_rules_version = (
            planning_rules_version or self._workspace_rules_version(workspace)
        )
        prompt_version = prompt_version or self._workspace_prompt_version(workspace)
        return _digest(
            {
                "schema_version": "product_plan_section_draft_input.v1",
                "goal_digest": workspace["goal_digest"],
                "planning_answers": self._planning_answers(workspace),
                "model": workspace["model"],
                "planning_rules_version": planning_rules_version,
                "prompt_version": prompt_version,
                "outline": outline,
                "outline_response_digest": workspace["outline_response_digest"],
                "section_id": section_id,
                "candidate_refs": candidate_refs,
            }
        )

    def _validate_checkpoint_section(
        self,
        value: Any,
        section_id: str,
        requirement_refs: set[str],
        candidate_refs: set[str],
    ) -> None:
        row = _stored_exact(
            value,
            {"section_id", "summary", "work_items"},
            "section.checkpoint_shape_invalid",
        )
        if row["section_id"] != section_id:
            raise ProductPlanningError(
                "product_workspace_corrupt", "section.section_id_mismatch"
            )
        if type(row["summary"]) is not str or not 1 <= len(row["summary"]) <= 500:
            raise ProductPlanningError(
                "product_workspace_corrupt", "section.summary_invalid"
            )
        if (
            type(row["work_items"]) is not list
            or not 1 <= len(row["work_items"]) <= 48
        ):
            raise ProductPlanningError(
                "product_workspace_corrupt", "section.item_count_invalid"
            )
        for raw in row["work_items"]:
            item = _stored_exact(
                raw,
                {
                    "title",
                    "summary",
                    "requirement_refs",
                    "delivery_wave",
                    "acceptance_intent",
                    "candidate_ref",
                    "gap_reason",
                },
                "section.work_item_shape_invalid",
            )
            if any(
                type(item[key]) is not str or not item[key]
                for key in ("title", "summary", "acceptance_intent")
            ):
                raise ProductPlanningError(
                    "product_workspace_corrupt", "section.work_item_text_invalid"
                )
            if (
                type(item["requirement_refs"]) is not list
                or not item["requirement_refs"]
                or any(type(ref_value) is not str for ref_value in item["requirement_refs"])
                or set(item["requirement_refs"]) - requirement_refs
                or len(set(item["requirement_refs"])) != len(item["requirement_refs"])
            ):
                raise ProductPlanningError(
                    "product_workspace_corrupt", "section.requirement_refs_invalid"
                )
            if (
                type(item["delivery_wave"]) is not int
                or item["delivery_wave"] not in {1, 2, 3, 4}
            ):
                raise ProductPlanningError(
                    "product_workspace_corrupt", "section.delivery_wave_invalid"
                )
            candidate_ref = item["candidate_ref"]
            if type(candidate_ref) is not str or (
                candidate_ref and candidate_ref not in candidate_refs
            ):
                raise ProductPlanningError(
                    "product_workspace_corrupt", "section.candidate_ref_unknown"
                )
            gap_reason = item["gap_reason"]
            if type(gap_reason) is not str:
                raise ProductPlanningError(
                    "product_workspace_corrupt", "section.gap_reason_invalid"
                )
            if candidate_ref and gap_reason:
                raise ProductPlanningError(
                    "product_workspace_corrupt", "section.candidate_gap_conflict"
                )
            if not candidate_ref and not gap_reason:
                raise ProductPlanningError(
                    "product_workspace_corrupt", "section.gap_reason_required"
                )

    def _validate_section_checkpoints(self, workspace: dict[str, Any]) -> None:
        checkpoints = workspace["section_checkpoints"]
        plan = workspace.get("plan")
        planning_rules_version = (
            plan.get("planning_rules_version")
            if type(plan) is dict
            and plan.get("planning_rules_version")
            in SUPPORTED_PLANNING_RULES_VERSIONS
            else SECTION_PLANNING_RULES_VERSION
        )
        prompt_version = (
            plan.get("prompt_version")
            if type(plan) is dict
            and plan.get("prompt_version")
            in {
                HISTORICAL_PLANNING_PROMPT_VERSION,
                LEGACY_PLANNING_PROMPT_VERSION,
            }
            else LEGACY_PLANNING_PROMPT_VERSION
        )
        if len(checkpoints) > len(SECTION_IDS):
            raise ProductPlanningError("product_workspace_corrupt")
        if checkpoints and (
            type(workspace["outline"]) is not dict
            or workspace["outline"]["needs_clarification"] is not False
        ):
            raise ProductPlanningError("product_workspace_corrupt")
        requirement_refs = (
            {item["ref"] for item in workspace["outline"]["requirements"]}
            if type(workspace["outline"]) is dict
            else set()
        )
        model_calls = workspace["model_calls"]
        for index, raw in enumerate(checkpoints):
            checkpoint = _stored_exact(
                raw,
                {
                    "schema_version",
                    "section_id",
                    "input_digest",
                    "section_digest",
                    "model_call_digest",
                    "candidate_refs",
                    "section",
                    "completed_at",
                },
            )
            section_id = SECTION_IDS[index]
            candidate_refs = checkpoint["candidate_refs"]
            if (
                type(candidate_refs) is not list
                or any(
                    type(candidate_ref) is not str
                    or not candidate_ref
                    or _SAFE_REF.fullmatch(candidate_ref) is None
                    for candidate_ref in candidate_refs
                )
                or len(set(candidate_refs)) != len(candidate_refs)
            ):
                raise ProductPlanningError("product_workspace_corrupt")
            self._validate_checkpoint_section(
                checkpoint["section"],
                section_id,
                requirement_refs,
                set(candidate_refs),
            )
            if (
                checkpoint["schema_version"] != SECTION_CHECKPOINT_SCHEMA_VERSION
                or checkpoint["section_id"] != section_id
                or checkpoint["input_digest"]
                != self._section_input_digest(
                    workspace,
                    workspace["outline"],
                    section_id,
                    candidate_refs,
                    planning_rules_version,
                    prompt_version,
                )
                or checkpoint["section_digest"] != _digest(checkpoint["section"])
                or _DIGEST.fullmatch(str(checkpoint["model_call_digest"])) is None
                or type(checkpoint["completed_at"]) is not str
                or sum(
                    call["call_type"] == "section_" + section_id
                    and call["structured_response_digest"]
                    == checkpoint["model_call_digest"]
                    for call in model_calls
                )
                != 1
            ):
                raise ProductPlanningError("product_workspace_corrupt")

    def _validate_blueprint(
        self,
        value: Any,
        requirements: list[dict[str, Any]],
        candidate_refs: set[str],
        composition_offers: dict[str, set[str]] | None = None,
    ) -> dict[str, Any]:
        if type(value) is not dict:
            raise ProductPlanningError(
                "product_plan_response_invalid",
                "blueprint.shape_invalid",
            )
        schema_version = value.get("schema_version")
        if schema_version == "product_plan_blueprint.v1":
            row = _exact_dict(
                value,
                {"schema_version", "sections", "assignments", "gaps"},
                "blueprint.shape_invalid",
            )
            offer_ref = None
        elif schema_version == "product_plan_blueprint.v2":
            row = _exact_dict(
                value,
                {"schema_version", "sections", "selection", "gaps"},
                "blueprint.shape_invalid",
            )
            selection = _exact_dict(
                row["selection"],
                {"offer_ref", "assignments"},
                "blueprint.selection_invalid",
            )
            offer_ref = selection["offer_ref"]
            if type(offer_ref) is not str or type(selection["assignments"]) is not dict:
                raise ProductPlanningError(
                    "product_plan_response_invalid",
                    "blueprint.selection_invalid",
                )
            expected = (composition_offers or {}).get(offer_ref)
            if offer_ref:
                if expected is None:
                    raise ProductPlanningError(
                        "product_plan_offer_unknown",
                        "blueprint.offer_ref_unknown",
                    )
                if set(selection["assignments"]) != expected:
                    raise ProductPlanningError(
                        "product_plan_role_coverage_invalid",
                        "blueprint.offer_members_invalid",
                    )
            elif selection["assignments"]:
                raise ProductPlanningError(
                    "product_plan_role_coverage_invalid",
                    "blueprint.offer_members_invalid",
                )
            row = {
                **row,
                "assignments": selection["assignments"],
            }
        else:
            raise ProductPlanningError(
                "product_plan_response_invalid",
                "blueprint.schema_version_invalid",
            )
        requirement_order = {
            str(item["ref"]): index for index, item in enumerate(requirements)
        }
        if (
            len(requirement_order) != len(requirements)
            or any(_SAFE_REF.fullmatch(ref) is None for ref in requirement_order)
        ):
            raise ProductPlanningError(
                "product_plan_response_invalid",
                "blueprint.requirements_invalid",
            )
        sections_raw = _exact_dict(
            row["sections"],
            set(SECTION_IDS),
            "blueprint.sections_invalid",
        )
        sections: dict[str, dict[str, str]] = {}
        for section_id in SECTION_IDS:
            section = _exact_dict(
                sections_raw[section_id],
                {"applicability", "summary"},
                "blueprint.section_invalid",
            )
            if section["applicability"] not in {
                "applicable",
                "not_applicable",
            }:
                raise ProductPlanningError(
                    "product_plan_response_invalid",
                    "blueprint.applicability_invalid",
                )
            sections[section_id] = {
                "applicability": section["applicability"],
                "summary": _safe_text(
                    section["summary"],
                    maximum=500,
                    rule_code="blueprint.section_summary_invalid",
                ),
            }

        if type(row["assignments"]) is not dict:
            raise ProductPlanningError(
                "product_plan_response_invalid",
                "blueprint.assignments_invalid",
            )
        unknown = set(row["assignments"]) - candidate_refs
        if unknown:
            raise ProductPlanningError(
                "product_plan_candidate_unknown",
                "blueprint.candidate_ref_unknown",
            )
        assignments: dict[str, dict[str, Any]] = {}
        covered: set[str] = set()
        active_sections: set[str] = set()
        for candidate_ref in sorted(row["assignments"]):
            assignment = _exact_dict(
                row["assignments"][candidate_ref],
                {
                    "section_id",
                    "requirement_refs",
                    "title",
                    "summary",
                    "acceptance_intent",
                },
                "blueprint.assignment_invalid",
            )
            section_id = assignment["section_id"]
            refs = assignment["requirement_refs"]
            if (
                section_id not in SECTION_IDS
                or type(refs) is not list
                or not refs
                or any(type(ref) is not str for ref in refs)
                or len(set(refs)) != len(refs)
                or set(refs) - set(requirement_order)
            ):
                raise ProductPlanningError(
                    "product_plan_response_invalid",
                    "blueprint.assignment_reference_invalid",
                )
            normalized_refs = sorted(refs, key=requirement_order.__getitem__)
            assignments[candidate_ref] = {
                "section_id": section_id,
                "requirement_refs": normalized_refs,
                "title": _safe_text(
                    assignment["title"],
                    maximum=180,
                    rule_code="blueprint.assignment_text_invalid",
                ),
                "summary": _safe_text(
                    assignment["summary"],
                    maximum=800,
                    rule_code="blueprint.assignment_text_invalid",
                ),
                "acceptance_intent": _safe_text(
                    assignment["acceptance_intent"],
                    maximum=500,
                    rule_code="blueprint.assignment_text_invalid",
                ),
            }
            covered.update(normalized_refs)
            active_sections.add(section_id)

        if type(row["gaps"]) is not list or len(row["gaps"]) > 64:
            raise ProductPlanningError(
                "product_plan_response_invalid",
                "blueprint.gaps_invalid",
            )
        statements = {
            str(item["ref"]): str(item["statement"]) for item in requirements
        }
        gaps: list[dict[str, Any]] = []
        for raw_gap in row["gaps"]:
            gap = _exact_dict(
                raw_gap,
                {"section_id", "requirement_refs", "title", "reason"},
                "blueprint.gap_invalid",
            )
            refs = gap["requirement_refs"]
            if (
                gap["section_id"] not in SECTION_IDS
                or type(refs) is not list
                or not refs
                or any(type(ref) is not str for ref in refs)
                or len(set(refs)) != len(refs)
                or set(refs) - set(requirement_order)
                or all(_ABSENCE_CONSTRAINT.search(statements[ref]) for ref in refs)
            ):
                raise ProductPlanningError(
                    "product_plan_response_invalid",
                    "blueprint.gap_reference_invalid",
                )
            normalized_refs = sorted(refs, key=requirement_order.__getitem__)
            normalized_gap = {
                "section_id": gap["section_id"],
                "requirement_refs": normalized_refs,
                "title": _safe_text(
                    gap["title"],
                    maximum=180,
                    rule_code="blueprint.gap_text_invalid",
                ),
                "reason": _safe_text(
                    gap["reason"],
                    maximum=500,
                    rule_code="blueprint.gap_text_invalid",
                ),
            }
            gaps.append(normalized_gap)
            covered.update(normalized_refs)
            active_sections.add(gap["section_id"])
        gaps.sort(
            key=lambda item: (
                SECTION_IDS.index(item["section_id"]),
                item["title"],
                item["reason"],
                item["requirement_refs"],
            )
        )

        for section_id in SECTION_IDS:
            applicability = sections[section_id]["applicability"]
            if (section_id in active_sections) != (applicability == "applicable"):
                raise ProductPlanningError(
                    "product_plan_response_invalid",
                    "blueprint.applicability_mismatch",
                )
        if covered != set(requirement_order):
            raise ProductPlanningError(
                "product_plan_requirement_uncovered",
                "blueprint.requirement_uncovered",
            )
        normalized = {
            "schema_version": schema_version,
            "sections": sections,
            "gaps": gaps,
        }
        if schema_version == "product_plan_blueprint.v1":
            normalized["assignments"] = assignments
        else:
            normalized["selection"] = {
                "offer_ref": offer_ref,
                "assignments": assignments,
            }
        return normalized

    @staticmethod
    def _validate_composition_selection(value: Any) -> dict[str, str]:
        row = _exact_dict(
            value,
            {"schema_version", "capability_key"},
            "composition_selection.shape_invalid",
        )
        capability_key = row["capability_key"]
        if (
            row["schema_version"] != "product_composition_selection.v1"
            or type(capability_key) is not str
            or (
                capability_key
                and _SAFE_REF.fullmatch(capability_key) is None
            )
        ):
            raise ProductPlanningError(
                "product_plan_response_invalid",
                "composition_selection.value_invalid",
            )
        return {
            "schema_version": "product_composition_selection.v1",
            "capability_key": capability_key,
        }

    @classmethod
    def _resolve_composition_selection(
        cls,
        selection: dict[str, str],
        composition_offers: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        normalized = cls._validate_composition_selection(selection)
        capability_key = normalized["capability_key"]
        if not capability_key:
            return None
        matches = [
            offer
            for offer in composition_offers
            if offer.get("capability_key") == capability_key
        ]
        if not matches:
            raise ProductPlanningError("product_plan_composition_unknown")
        if len(matches) != 1:
            raise ProductPlanningError(
                "product_plan_composition_selection_ambiguous"
            )
        return matches[0]

    def _validate_stored_composition_selection(
        self,
        workspace: dict[str, Any],
    ) -> None:
        selection = workspace["composition_selection"]
        input_digest = workspace["composition_selection_input_digest"]
        response_digest = workspace["composition_selection_response_digest"]
        if selection is None:
            if input_digest is not None or response_digest is not None:
                raise ProductPlanningError("product_workspace_corrupt")
            return
        if (
            type(workspace["outline"]) is not dict
            or workspace["outline"]["needs_clarification"] is not False
            or _DIGEST.fullmatch(str(input_digest)) is None
            or _DIGEST.fullmatch(str(response_digest)) is None
        ):
            raise ProductPlanningError("product_workspace_corrupt")
        try:
            normalized = self._validate_composition_selection(selection)
        except ProductPlanningError as exc:
            raise ProductPlanningError("product_workspace_corrupt") from exc
        if (
            normalized != selection
            or sum(
                call["call_type"] == "composition_selection"
                and call["structured_response_digest"] == response_digest
                for call in workspace["model_calls"]
            )
            != 1
        ):
            raise ProductPlanningError("product_workspace_corrupt")

    def _validate_stored_blueprint(self, workspace: dict[str, Any]) -> None:
        blueprint = workspace["blueprint"]
        input_digest = workspace["blueprint_input_digest"]
        response_digest = workspace["blueprint_response_digest"]
        if blueprint is None:
            if input_digest is not None or response_digest is not None:
                raise ProductPlanningError("product_workspace_corrupt")
            return
        if (
            type(workspace["outline"]) is not dict
            or workspace["outline"]["needs_clarification"] is not False
            or _DIGEST.fullmatch(str(input_digest)) is None
            or _DIGEST.fullmatch(str(response_digest)) is None
        ):
            raise ProductPlanningError("product_workspace_corrupt")
        try:
            schema_version = (
                blueprint.get("schema_version")
                if type(blueprint) is dict
                else None
            )
            assignments = (
                blueprint.get("assignments", {})
                if schema_version == "product_plan_blueprint.v1"
                else blueprint.get("selection", {}).get("assignments", {})
                if type(blueprint) is dict
                and type(blueprint.get("selection")) is dict
                else {}
            )
            offers = (
                {
                    blueprint["selection"]["offer_ref"]: set(assignments)
                }
                if schema_version == "product_plan_blueprint.v2"
                and blueprint["selection"]["offer_ref"]
                else {}
            )
            normalized = self._validate_blueprint(
                blueprint,
                workspace["outline"]["requirements"],
                set(assignments),
                offers,
            )
        except ProductPlanningError as exc:
            raise ProductPlanningError("product_workspace_corrupt") from exc
        if (
            normalized != blueprint
            or sum(
                call["call_type"] == "product_blueprint"
                and call["structured_response_digest"] == response_digest
                for call in workspace["model_calls"]
            )
            != 1
        ):
            raise ProductPlanningError("product_workspace_corrupt")

    def _validate_stored_confirmation(
        self,
        value: Any,
        plan: Any,
        parameter_offer: dict[str, Any] | None = None,
    ) -> None:
        if value is None:
            return
        common_keys = {
            "schema_version",
            "plan_id",
            "plan_version",
            "plan_digest",
            "confirmed_at",
            "capsule_revalidation",
            "warehouse_revision",
            "product_generated",
            "candidate_generated",
            "product_usage_written",
            "receipt_digest",
        }
        schema_version = value.get("schema_version") if type(value) is dict else None
        row = _stored_exact(
            value,
            (
                common_keys
                if schema_version == "product_plan_confirmation.v1"
                else {*common_keys, "parameter_binding"}
            ),
        )
        canonical = {key: item for key, item in row.items() if key != "receipt_digest"}
        if (
            type(plan) is not dict
            or row["schema_version"]
            not in {
                "product_plan_confirmation.v1",
                "product_plan_confirmation.v2",
            }
            or row["plan_id"] != plan["plan_id"]
            or row["plan_version"] != plan["plan_version"]
            or row["plan_digest"] != plan["canonical_digest"]
            or type(row["confirmed_at"]) is not str
            or type(row["capsule_revalidation"]) is not list
            or type(row["warehouse_revision"]) is not int
            or row["warehouse_revision"] < 0
            or any(row[key] is not False for key in ("product_generated", "candidate_generated", "product_usage_written"))
            or row["receipt_digest"] != _digest(canonical)
        ):
            raise ProductPlanningError("product_workspace_corrupt")
        for binding in row["capsule_revalidation"]:
            item = _stored_exact(
                binding,
                {
                    "capsule_id",
                    "version_id",
                    "eligibility_status",
                    "review_status",
                },
            )
            if (
                type(item["capsule_id"]) is not str
                or type(item["version_id"]) is not str
                or item["eligibility_status"] != "active_current_eligible"
                or item["review_status"] != "user_confirmed"
            ):
                raise ProductPlanningError("product_workspace_corrupt")
        expected = [
            {
                "capsule_id": binding["capsule_id"],
                "version_id": binding["version_id"],
                "eligibility_status": "active_current_eligible",
                "review_status": "user_confirmed",
            }
            for section in plan["sections"]
            for work_item in section["work_items"]
            for binding in work_item["capsule_bindings"]
        ]
        if row["capsule_revalidation"] != expected:
            raise ProductPlanningError("product_workspace_corrupt")
        if row["schema_version"] == "product_plan_confirmation.v2":
            try:
                validate_parameterized_execution_binding(
                    plan,
                    row["parameter_binding"],
                    parameter_offer,
                )
            except PlanExecutionError as exc:
                raise ProductPlanningError("product_workspace_corrupt") from exc

    def _ensure_directory(self, path: Path) -> None:
        try:
            self._assert_no_symlink_components(path)
            if path.exists() or path.is_symlink():
                metadata = path.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                    raise ProductPlanningError("product_workspace_symlink_forbidden")
            else:
                path.mkdir(parents=True, mode=0o700)
            if os.name == "posix":
                os.chmod(path, 0o700)
        except ProductPlanningError:
            raise
        except OSError as exc:
            raise ProductPlanningError("product_planning_state_unavailable") from exc

    @staticmethod
    def _assert_no_symlink_components(path: Path) -> None:
        absolute = Path(os.path.abspath(path))
        for component in reversed((absolute, *absolute.parents)):
            try:
                metadata = component.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise ProductPlanningError("product_planning_state_unavailable") from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise ProductPlanningError("product_workspace_symlink_forbidden")

    def _read_json(self, path: Path) -> Any:
        self._assert_no_symlink_components(path.parent)
        if not path.exists() and not path.is_symlink():
            raise ProductPlanningError("product_planning_state_not_found")
        try:
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ProductPlanningError("product_workspace_symlink_forbidden")
            if (
                os.name == "posix"
                and stat.S_IMODE(metadata.st_mode) & 0o077
            ):
                raise ProductPlanningError("product_workspace_permissions_invalid")
            if metadata.st_size > MAX_WORKSPACE_BYTES:
                raise ProductPlanningError("product_workspace_too_large")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                with os.fdopen(descriptor, "rb") as handle:
                    raw = handle.read(MAX_WORKSPACE_BYTES + 1)
            except BaseException:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise
        except ProductPlanningError:
            raise
        except OSError as exc:
            raise ProductPlanningError("product_planning_state_unavailable") from exc
        if len(raw) > MAX_WORKSPACE_BYTES:
            raise ProductPlanningError("product_workspace_too_large")
        try:
            return _strict_json(raw)
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ProductPlanningError("product_workspace_corrupt") from exc

    def _atomic_write(self, path: Path, value: Any) -> None:
        self._ensure_directory(path.parent)
        self._assert_no_symlink_components(path.parent)
        if path.exists() or path.is_symlink():
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ProductPlanningError("product_workspace_symlink_forbidden")
        payload = _canonical_bytes(value)
        if len(payload) > MAX_WORKSPACE_BYTES:
            raise ProductPlanningError("product_workspace_too_large")
        temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = -1
        try:
            descriptor = os.open(temporary, flags, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            if os.name == "posix":
                os.chmod(path, 0o600)
                directory_fd = os.open(
                    path.parent,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except ProductPlanningError:
            raise
        except OSError as exc:
            raise ProductPlanningError("product_planning_state_unavailable") from exc
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass

    def _write_immutable(self, path: Path, value: Any) -> None:
        if path.exists() or path.is_symlink():
            existing = self._read_json(path)
            if existing != value:
                raise ProductPlanningError("product_plan_confirmation_conflict")
            return
        self._atomic_write(path, value)

    def _capability_gap_plan_dir(
        self,
        workspace: dict[str, Any],
        plan: dict[str, Any],
    ) -> Path:
        return (
            self._workspace_dir(workspace["workspace_id"])
            / "capability_gaps"
            / f"plan_v{plan['plan_version']}_{plan['canonical_digest']}"
        )

    def _capability_gap_projection_path(
        self,
        workspace: dict[str, Any],
        plan: dict[str, Any],
    ) -> Path:
        return self._capability_gap_plan_dir(workspace, plan) / "projection_v1.json"

    def _capability_gap_projection_v2_path(
        self,
        workspace: dict[str, Any],
        plan: dict[str, Any],
    ) -> Path:
        return self._capability_gap_plan_dir(workspace, plan) / "projection_v2.json"

    def _capability_gap_projection_path_for(
        self,
        workspace: dict[str, Any],
        plan: dict[str, Any],
        projection: dict[str, Any],
    ) -> Path:
        if projection.get("schema_version") == CAPABILITY_GAP_PROJECTION_VERSION:
            return self._capability_gap_projection_path(workspace, plan)
        if projection.get("schema_version") == CAPABILITY_GAP_PROJECTION_V2:
            return self._capability_gap_projection_v2_path(workspace, plan)
        raise ProductPlanningError("capability_gap_projection_invalid")

    def _capability_gap_decisions_dir(
        self,
        workspace: dict[str, Any],
        plan: dict[str, Any],
    ) -> Path:
        return self._capability_gap_plan_dir(workspace, plan) / "decisions"

    def _capability_source_proposal_authorization_path(
        self,
        workspace: dict[str, Any],
        plan: dict[str, Any],
    ) -> Path:
        return (
            self._capability_gap_plan_dir(workspace, plan)
            / "source_proposal_authorization_v1.json"
        )

    def _capability_source_proposal_authorization_v2_path(
        self,
        workspace: dict[str, Any],
        plan: dict[str, Any],
    ) -> Path:
        return (
            self._capability_gap_plan_dir(workspace, plan)
            / "source_proposal_authorization_v2.json"
        )

    def _capability_source_proposal_authorization_path_for(
        self,
        workspace: dict[str, Any],
        plan: dict[str, Any],
        projection: dict[str, Any],
    ) -> Path:
        if projection.get("schema_version") == CAPABILITY_GAP_PROJECTION_VERSION:
            return self._capability_source_proposal_authorization_path(
                workspace,
                plan,
            )
        if projection.get("schema_version") == CAPABILITY_GAP_PROJECTION_V2:
            return self._capability_source_proposal_authorization_v2_path(
                workspace,
                plan,
            )
        raise ProductPlanningError("capability_gap_projection_invalid")

    def _capability_source_proposal_authorization_paths(
        self,
        workspace: dict[str, Any],
    ) -> list[Path]:
        root = self._workspace_dir(workspace["workspace_id"]) / "capability_gaps"
        if not root.exists() and not root.is_symlink():
            return []
        self._assert_no_symlink_components(root)
        if root.is_symlink() or not root.is_dir():
            raise ProductPlanningError("product_workspace_symlink_forbidden")
        paths: list[Path] = []
        for entry in sorted(root.iterdir(), key=lambda path: path.name):
            if entry.is_symlink() or not entry.is_dir():
                raise ProductPlanningError("product_workspace_symlink_forbidden")
            for name in (
                "source_proposal_authorization_v1.json",
                "source_proposal_authorization_v2.json",
            ):
                candidate = entry / name
                if candidate.exists() or candidate.is_symlink():
                    if candidate.is_symlink() or not candidate.is_file():
                        raise ProductPlanningError(
                            "product_workspace_symlink_forbidden"
                        )
                    paths.append(candidate)
        return paths

    def _capability_source_proposal_run_dir(
        self,
        workspace: dict[str, Any],
        plan: dict[str, Any],
    ) -> Path:
        return (
            self._capability_gap_plan_dir(workspace, plan)
            / "source_proposal_run_v1"
        )

    def _capability_source_proposal_run_identity_path(
        self,
        workspace: dict[str, Any],
        plan: dict[str, Any],
    ) -> Path:
        return (
            self._capability_source_proposal_run_dir(workspace, plan)
            / "run.json"
        )

    def _capability_source_proposal_run_events_dir(
        self,
        workspace: dict[str, Any],
        plan: dict[str, Any],
    ) -> Path:
        return (
            self._capability_source_proposal_run_dir(workspace, plan)
            / "events"
        )

    def _validate_capability_source_proposal_run_identity(
        self,
        workspace: dict[str, Any],
        value: Any,
    ) -> dict[str, Any]:
        row = _stored_exact(
            value,
            {
                "schema_version",
                "run_id",
                "plan_token",
                "plan_digest",
                "gap_id",
                "projection_digest",
                "authorize_decision_digest",
                "authorization_digest",
                "request_digest",
                "warehouse_revision",
                "catalog_digest",
                "source_proposal_model",
                "supervision_model",
                "attempt_count",
                "created_at",
                "canonical_digest",
            },
        )
        body = {
            key: item
            for key, item in row.items()
            if key != "canonical_digest"
        }
        source_model = _stored_exact(
            row["source_proposal_model"],
            {"name", "digest", "parameter_count", "parameter_size"},
        )
        supervision_model = _stored_exact(
            row["supervision_model"],
            {"name", "digest"},
        )
        plan = workspace.get("plan")
        projection = self._read_capability_gap_projection(workspace)
        decisions = (
            self._capability_gap_decisions(workspace, projection)
            if projection is not None
            else []
        )
        decision = decisions[-1] if decisions else None
        authorization = (
            self._read_capability_source_proposal_authorization(
                workspace,
                projection,
                decision,
            )
            if projection is not None
            and type(decision) is dict
            and decision.get("decision") == "authorize"
            else None
        )
        if (
            row["schema_version"]
            != CAPABILITY_SOURCE_PROPOSAL_RUN_VERSION
            or _SOURCE_PROPOSAL_RUN_ID.fullmatch(str(row["run_id"]))
            is None
            or row["plan_token"] != workspace["plan_token"]
            or type(plan) is not dict
            or row["plan_digest"] != plan["canonical_digest"]
            or projection is None
            or row["gap_id"] != projection["gap_id"]
            or row["projection_digest"]
            != projection["projection_digest"]
            or decision is None
            or row["authorize_decision_digest"]
            != decision["canonical_digest"]
            or authorization is None
            or row["authorization_digest"]
            != authorization["authorization_digest"]
            or row["request_digest"]
            != self._runtime_capability_source_proposal_request(
                authorization
            )["request_digest"]
            or row["warehouse_revision"]
            != authorization["warehouse_revision"]
            or row["catalog_digest"] != authorization["catalog_digest"]
            or source_model != workspace["model"]
            or type(source_model["name"]) is not str
            or not source_model["name"]
            or _DIGEST.fullmatch(str(source_model["digest"])) is None
            or type(source_model["parameter_count"]) is not int
            or source_model["parameter_count"] <= 0
            or type(source_model["parameter_size"]) is not str
            or not source_model["parameter_size"]
            or type(supervision_model["name"]) is not str
            or not supervision_model["name"]
            or _DIGEST.fullmatch(str(supervision_model["digest"])) is None
            or row["attempt_count"] != 1
            or type(row["created_at"]) is not str
            or not row["created_at"]
            or row["canonical_digest"] != _digest(body)
        ):
            raise ProductPlanningError(
                "capability_source_proposal_run_conflict"
            )
        return copy.deepcopy(row)

    @staticmethod
    def _validate_capability_source_proposal_run_evidence(
        value: Any,
    ) -> dict[str, Any]:
        allowed = {
            "source_sha256",
            "source_relpath",
            "model_response_digest",
            "source_identity_sha256",
            "capture_digest",
            "security_digest",
            "runtime_digest",
            "supervision_digest",
            "validation_database_sha256",
            "admission_digest",
            "review_id",
            "canonical_hash",
            "warehouse_revision",
        }
        if type(value) is not dict or set(value) - allowed:
            raise ProductPlanningError(
                "capability_source_proposal_run_event_invalid"
            )
        row = copy.deepcopy(value)
        for key, item in row.items():
            if key == "warehouse_revision":
                if type(item) is not int or item < 0:
                    raise ProductPlanningError(
                        "capability_source_proposal_run_event_invalid"
                    )
            elif key == "source_relpath":
                if item != "source/capability.js":
                    raise ProductPlanningError(
                        "capability_source_proposal_run_event_invalid"
                    )
            elif key == "review_id":
                if (
                    type(item) is not str
                    or re.fullmatch(r"[A-Za-z0-9_-]{1,160}", item)
                    is None
                ):
                    raise ProductPlanningError(
                        "capability_source_proposal_run_event_invalid"
                    )
            elif _DIGEST.fullmatch(str(item)) is None:
                raise ProductPlanningError(
                    "capability_source_proposal_run_event_invalid"
                )
        return row

    def _validate_capability_source_proposal_run_event(
        self,
        value: Any,
        identity: dict[str, Any],
        previous: dict[str, Any] | None,
    ) -> dict[str, Any]:
        row = _stored_exact(
            value,
            {
                "schema_version",
                "run_digest",
                "sequence",
                "previous_event_digest",
                "status",
                "stage",
                "evidence",
                "error_code",
                "created_at",
                "canonical_digest",
            },
        )
        body = {
            key: item
            for key, item in row.items()
            if key != "canonical_digest"
        }
        evidence = self._validate_capability_source_proposal_run_evidence(
            row["evidence"]
        )
        if (
            row["schema_version"]
            != CAPABILITY_SOURCE_PROPOSAL_RUN_EVENT_VERSION
            or row["run_digest"] != identity["canonical_digest"]
            or type(row["sequence"]) is not int
            or row["sequence"] != (1 if previous is None else previous[
                "sequence"
            ] + 1)
            or row["previous_event_digest"]
            != (
                None
                if previous is None
                else previous["canonical_digest"]
            )
            or row["status"]
            not in CAPABILITY_SOURCE_PROPOSAL_RUN_STATUSES
            or row["stage"]
            not in CAPABILITY_SOURCE_PROPOSAL_RUN_STAGES
            or evidence != row["evidence"]
            or (
                row["error_code"] is not None
                and (
                    type(row["error_code"]) is not str
                    or re.fullmatch(
                        r"[a-z][a-z0-9_]{1,95}",
                        row["error_code"],
                    )
                    is None
                )
            )
            or type(row["created_at"]) is not str
            or not row["created_at"]
            or row["canonical_digest"] != _digest(body)
        ):
            raise ProductPlanningError(
                "capability_source_proposal_run_event_invalid"
            )
        if previous is None:
            if (
                row["status"] != "pending"
                or row["stage"] != "source_proposal"
                or row["error_code"] is not None
                or row["evidence"]
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_run_event_invalid"
                )
        else:
            terminal = {"review_required", "failed", "cancelled"}
            previous_index = CAPABILITY_SOURCE_PROPOSAL_RUN_STAGES.index(
                previous["stage"]
            )
            current_index = CAPABILITY_SOURCE_PROPOSAL_RUN_STAGES.index(
                row["stage"]
            )
            if (
                previous["status"] in terminal
                or row["status"] == "pending"
                or current_index < previous_index
                or current_index > previous_index + 1
                or (
                    row["status"] == "running"
                    and row["error_code"] is not None
                )
                or (
                    row["status"] in {"failed", "cancelled"}
                    and row["error_code"] is None
                )
                or (
                    row["status"] == "review_required"
                    and (
                        row["stage"] != "admission"
                        or row["error_code"] is not None
                        or "review_id" not in row["evidence"]
                        or "admission_digest" not in row["evidence"]
                    )
                )
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_run_event_invalid"
                )
        return copy.deepcopy(row)

    def _capability_source_proposal_run_events(
        self,
        workspace: dict[str, Any],
        identity: dict[str, Any],
    ) -> list[dict[str, Any]]:
        directory = self._capability_source_proposal_run_events_dir(
            workspace,
            workspace["plan"],
        )
        if not directory.exists() and not directory.is_symlink():
            return []
        self._assert_no_symlink_components(directory)
        if directory.is_symlink() or not directory.is_dir():
            raise ProductPlanningError(
                "capability_source_proposal_run_conflict"
            )
        try:
            entries = sorted(directory.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            raise ProductPlanningError(
                "product_planning_state_unavailable"
            ) from exc
        events: list[dict[str, Any]] = []
        previous = None
        for entry in entries:
            match = _SOURCE_PROPOSAL_RUN_EVENT_FILENAME.fullmatch(
                entry.name
            )
            if (
                match is None
                or entry.is_symlink()
                or not entry.is_file()
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_run_event_invalid"
                )
            row = self._validate_capability_source_proposal_run_event(
                self._read_json(entry),
                identity,
                previous,
            )
            if (
                int(match.group(1)) != row["sequence"]
                or match.group(2) != row["canonical_digest"]
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_run_event_invalid"
                )
            events.append(row)
            previous = row
        if not events:
            raise ProductPlanningError(
                "capability_source_proposal_run_conflict"
            )
        return events

    def _append_capability_source_proposal_run_event_locked(
        self,
        workspace: dict[str, Any],
        identity: dict[str, Any],
        *,
        status: str,
        stage: str,
        evidence: dict[str, Any],
        error_code: str | None,
    ) -> dict[str, Any]:
        events = self._capability_source_proposal_run_events(
            workspace,
            identity,
        )
        previous = events[-1] if events else None
        body = {
            "schema_version": (
                CAPABILITY_SOURCE_PROPOSAL_RUN_EVENT_VERSION
            ),
            "run_digest": identity["canonical_digest"],
            "sequence": 1 if previous is None else previous["sequence"] + 1,
            "previous_event_digest": (
                None
                if previous is None
                else previous["canonical_digest"]
            ),
            "status": status,
            "stage": stage,
            "evidence": copy.deepcopy(evidence),
            "error_code": error_code,
            "created_at": _now(),
        }
        event = {**body, "canonical_digest": _digest(body)}
        self._validate_capability_source_proposal_run_event(
            event,
            identity,
            previous,
        )
        directory = self._capability_source_proposal_run_events_dir(
            workspace,
            workspace["plan"],
        )
        self._ensure_directory(directory)
        path = directory / (
            f"event_{event['sequence']:06d}_"
            f"{event['canonical_digest']}.json"
        )
        self._write_immutable(path, event)
        return event

    def _capability_source_proposal_run_by_id(
        self,
        run_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if _SOURCE_PROPOSAL_RUN_ID.fullmatch(str(run_id)) is None:
            raise ProductPlanningError(
                "capability_source_proposal_run_not_found"
            )
        matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for workspace in self._workspaces():
            plan = workspace.get("plan")
            if type(plan) is not dict:
                continue
            path = self._capability_source_proposal_run_identity_path(
                workspace,
                plan,
            )
            if not path.exists() and not path.is_symlink():
                continue
            identity = self._validate_capability_source_proposal_run_identity(
                workspace,
                self._read_json(path),
            )
            if identity["run_id"] == run_id:
                matches.append((workspace, identity))
        if len(matches) != 1:
            raise ProductPlanningError(
                "capability_source_proposal_run_not_found"
                if not matches
                else "capability_source_proposal_run_conflict"
            )
        return matches[0]

    def _capability_source_proposal_run_projection(
        self,
        workspace: dict[str, Any],
        identity: dict[str, Any],
    ) -> dict[str, Any]:
        events = self._capability_source_proposal_run_events(
            workspace,
            identity,
        )
        current = events[-1]
        completed_stages = []
        for stage in CAPABILITY_SOURCE_PROPOSAL_RUN_STAGES:
            if any(
                event["stage"] == stage
                and (
                    event["stage"] != current["stage"]
                    or current["status"]
                    in {"review_required", "failed", "cancelled"}
                )
                for event in events
            ):
                completed_stages.append(stage)
        return {
            "schema_version": CAPABILITY_SOURCE_PROPOSAL_RUN_VERSION,
            "run_id": identity["run_id"],
            "attempt_count": identity["attempt_count"],
            "status": current["status"],
            "stage": current["stage"],
            "completed_stages": completed_stages,
            "error_code": current["error_code"],
            "review_id": current["evidence"].get("review_id"),
            "created_at": identity["created_at"],
            "updated_at": current["created_at"],
        }

    @staticmethod
    def _validate_gap_endpoint(value: Any) -> dict[str, Any]:
        row = _stored_exact(
            value,
            {
                "capsule_id",
                "version_id",
                "canonical_hash",
                "capability_kind",
                "role_key",
                "variant_key",
                "port_kind",
                "port_name",
                "contract_digest",
            },
        )
        if (
            any(
                type(row[key]) is not str or not row[key]
                for key in (
                    "capsule_id",
                    "version_id",
                    "capability_kind",
                    "role_key",
                    "variant_key",
                    "port_kind",
                    "port_name",
                )
            )
            or row["capability_kind"]
            not in {"presentation", "interaction", "computation"}
            or row["port_kind"] not in {"event", "input", "output"}
            or _DIGEST.fullmatch(str(row["canonical_hash"])) is None
            or _DIGEST.fullmatch(str(row["contract_digest"])) is None
        ):
            raise ProductPlanningError("capability_gap_projection_invalid")
        return row

    def _validate_capability_gap_projection(
        self,
        workspace: dict[str, Any],
        value: Any,
    ) -> dict[str, Any]:
        plan = workspace.get("plan")
        schema_version = (
            value.get("schema_version") if type(value) is dict else None
        )
        exact_fields = {
            "schema_version",
            "plan_id",
            "plan_version",
            "plan_digest",
            "gap_id",
            "requirement_ids",
            "capability_key",
            "capability_group_display_name",
            "capability_kind",
            "slot",
            "input_contract",
            "output_contract",
            "adapter_contract_version",
            "capture_mapping_schema",
            "result_field",
            "passthrough_fields",
            "upstream",
            "downstream",
            "existing_members",
            "warehouse_revision",
            "catalog_digest",
            "projection_source",
            "projection_digest",
        }
        if schema_version == CAPABILITY_GAP_PROJECTION_V2:
            exact_fields |= {"proof_schema", "result_enum"}
        row = _stored_exact(
            value,
            exact_fields,
        )
        body = {
            key: item for key, item in row.items() if key != "projection_digest"
        }
        if (
            type(plan) is not dict
            or row["schema_version"]
            not in {
                CAPABILITY_GAP_PROJECTION_VERSION,
                CAPABILITY_GAP_PROJECTION_V2,
            }
            or row["plan_id"] != plan["plan_id"]
            or row["plan_version"] != plan["plan_version"]
            or row["plan_digest"] != plan["canonical_digest"]
            or _GAP_ID.fullmatch(str(row["gap_id"])) is None
            or type(row["requirement_ids"]) is not list
            or not row["requirement_ids"]
            or len(set(row["requirement_ids"])) != len(row["requirement_ids"])
            or row["requirement_ids"] != sorted(row["requirement_ids"])
            or any(type(item) is not str for item in row["requirement_ids"])
            or type(row["capability_key"]) is not str
            or not row["capability_key"]
            or type(row["capability_group_display_name"]) is not str
            or not row["capability_group_display_name"]
            or row["capability_kind"] != "computation"
            or row["slot"]
            not in {
                "only_computation",
                "before_existing_computation",
                "after_existing_computation",
            }
            or (
                row["schema_version"] == CAPABILITY_GAP_PROJECTION_VERSION
                and (
                    row["adapter_contract_version"]
                    not in {"computation_adapter.v2", "computation_adapter.v3"}
                    or row["capture_mapping_schema"]
                    not in {
                        "computation_capture_mapping.v2",
                        "computation_capture_mapping.v3",
                    }
                )
            )
            or (
                row["schema_version"] == CAPABILITY_GAP_PROJECTION_V2
                and (
                    row["adapter_contract_version"]
                    != "computation_adapter.v4"
                    or row["capture_mapping_schema"]
                    != "computation_capture_mapping.v4"
                    or row["proof_schema"] != "source_graph_proof.v2"
                    or type(row["result_enum"]) is not list
                    or not row["result_enum"]
                    or len(row["result_enum"]) > 32
                    or not self._utf8_sorted_unique_strings(
                        row["result_enum"]
                    )
                )
            )
            or type(row["result_field"]) is not str
            or not row["result_field"]
            or type(row["passthrough_fields"]) is not list
            or row["passthrough_fields"] != sorted(row["passthrough_fields"])
            or len(set(row["passthrough_fields"]))
            != len(row["passthrough_fields"])
            or any(
                type(item) is not str or not item
                for item in row["passthrough_fields"]
            )
            or type(row["existing_members"]) is not list
            or len(row["existing_members"]) not in {2, 3}
            or type(row["warehouse_revision"]) is not int
            or row["warehouse_revision"] < 0
            or _DIGEST.fullmatch(str(row["catalog_digest"])) is None
            or row["projection_source"] != "deterministic_unique_serial_gap"
            or _DIGEST.fullmatch(str(row["projection_digest"])) is None
            or row["projection_digest"] != _digest(body)
        ):
            raise ProductPlanningError("capability_gap_projection_invalid")
        try:
            normalized_input, normalized_output, _error = (
                normalize_capsule_contracts(
                    "computation",
                    row["input_contract"],
                    row["output_contract"],
                    {"schema": "error_contract.v1", "errors": {}},
                )
            )
        except DataContractError as exc:
            raise ProductPlanningError(
                "capability_gap_projection_invalid"
            ) from exc
        adapter = (
            self._integer_gap_adapter(normalized_input, normalized_output)
            if row["schema_version"] == CAPABILITY_GAP_PROJECTION_VERSION
            else self._finite_enum_gap_adapter(
                normalized_input,
                normalized_output,
            )
        )
        adapter_fields = [
            "adapter_contract_version",
            "capture_mapping_schema",
            "result_field",
            "passthrough_fields",
        ]
        if row["schema_version"] == CAPABILITY_GAP_PROJECTION_V2:
            adapter_fields.extend(["proof_schema", "result_enum"])
        if (
            normalized_input != row["input_contract"]
            or normalized_output != row["output_contract"]
            or adapter is None
            or any(
                row[key] != adapter[key]
                for key in adapter_fields
            )
        ):
            raise ProductPlanningError("capability_gap_projection_invalid")
        self._validate_gap_endpoint(row["upstream"])
        self._validate_gap_endpoint(row["downstream"])
        identities: set[tuple[str, str]] = set()
        for member in row["existing_members"]:
            identity = self._gap_capsule_identity(member)
            if identity != member:
                raise ProductPlanningError("capability_gap_projection_invalid")
            pair = (identity["capsule_id"], identity["version_id"])
            if pair in identities:
                raise ProductPlanningError("capability_gap_projection_invalid")
            identities.add(pair)
        gaps = [
            gap
            for section in plan["sections"]
            for gap in section["gaps"]
        ]
        if (
            len(gaps) != 1
            or gaps[0]["gap_id"] != row["gap_id"]
            or sorted(gaps[0]["requirement_ids"]) != row["requirement_ids"]
        ):
            raise ProductPlanningError("capability_gap_projection_invalid")
        return row

    def _read_capability_gap_projection(
        self,
        workspace: dict[str, Any],
    ) -> dict[str, Any] | None:
        plan = workspace.get("plan")
        if type(plan) is not dict:
            return None
        paths = [
            path
            for path in (
                self._capability_gap_projection_path(workspace, plan),
                self._capability_gap_projection_v2_path(workspace, plan),
            )
            if path.exists() or path.is_symlink()
        ]
        if not paths:
            return None
        if len(paths) != 1:
            raise ProductPlanningError("capability_gap_projection_conflict")
        return self._validate_capability_gap_projection(
            workspace,
            self._read_json(paths[0]),
        )

    def _capability_gap_projection_for_workspace(
        self,
        workspace: dict[str, Any],
        plan: dict[str, Any],
        catalog: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        selection = (
            self._validate_capability_gap_target_selection(
                workspace.get("capability_gap_target_selection")
            )
            if (
                workspace["schema_version"]
                in TARGET_SELECTION_WORKSPACE_SCHEMA_VERSIONS
            )
            else None
        )
        return self._capability_gap_projection(
            plan,
            catalog,
            (
                selection["candidate_digest"]
                if selection is not None
                else None
            ),
        )

    def _prepare_capability_gap_projection(
        self,
        workspace: dict[str, Any],
        catalog: dict[str, Any],
    ) -> dict[str, Any] | None:
        plan = workspace.get("plan")
        if type(plan) is not dict:
            return None
        projection, status = self._capability_gap_projection_for_workspace(
            workspace,
            plan,
            catalog,
        )
        if projection is None or status != "available":
            return None
        path = self._capability_gap_projection_path_for(
            workspace,
            plan,
            projection,
        )
        self._ensure_directory(path.parent)
        self._write_immutable(path, projection)
        return projection

    def _validate_capability_gap_decision(
        self,
        value: Any,
        projection: dict[str, Any],
        previous: dict[str, Any] | None,
    ) -> dict[str, Any]:
        row = _stored_exact(
            value,
            {
                "schema_version",
                "gap_projection_digest",
                "plan_digest",
                "catalog_digest",
                "sequence",
                "previous_decision_digest",
                "decision",
                "behavior_intent",
                "reason",
                "acceptance_cases",
                "decision_source",
                "decided_at",
                "canonical_digest",
            },
        )
        body = {
            key: item for key, item in row.items() if key != "canonical_digest"
        }
        expected_sequence = 1 if previous is None else previous["sequence"] + 1
        expected_previous = (
            None if previous is None else previous["canonical_digest"]
        )
        if (
            row["schema_version"] != CAPABILITY_GAP_DECISION_VERSION
            or row["gap_projection_digest"] != projection["projection_digest"]
            or row["plan_digest"] != projection["plan_digest"]
            or row["catalog_digest"] != projection["catalog_digest"]
            or row["sequence"] != expected_sequence
            or row["previous_decision_digest"] != expected_previous
            or row["decision"] not in {"authorize", "defer", "reject"}
            or row["decision_source"] != "user_confirmed"
            or type(row["decided_at"]) is not str
            or not row["decided_at"]
            or _DIGEST.fullmatch(str(row["canonical_digest"])) is None
            or row["canonical_digest"] != _digest(body)
            or type(row["acceptance_cases"]) is not list
        ):
            raise ProductPlanningError("capability_gap_decision_invalid")
        if row["decision"] == "authorize":
            if (
                type(row["behavior_intent"]) is not str
                or not row["behavior_intent"]
                or row["reason"] is not None
                or not 1 <= len(row["acceptance_cases"]) <= 3
            ):
                raise ProductPlanningError("capability_gap_decision_invalid")
            case_digests: set[str] = set()
            for case in row["acceptance_cases"]:
                exact = _stored_exact(case, {"input", "expected_output"})
                digest = _digest(exact)
                if (
                    digest in case_digests
                    or not data_contract_accepts(
                        projection["input_contract"],
                        exact["input"],
                    )
                    or not data_contract_accepts(
                        projection["output_contract"],
                        exact["expected_output"],
                    )
                    or any(
                        _canonical_bytes(exact["input"][field])
                        != _canonical_bytes(
                            exact["expected_output"][field]
                        )
                        for field in projection["passthrough_fields"]
                    )
                ):
                    raise ProductPlanningError(
                        "capability_gap_acceptance_invalid"
                    )
                case_digests.add(digest)
        elif (
            row["behavior_intent"] is not None
            or row["acceptance_cases"]
        ):
            raise ProductPlanningError("capability_gap_decision_invalid")
        if row["decision"] == "reject":
            if type(row["reason"]) is not str or not row["reason"]:
                raise ProductPlanningError("capability_gap_decision_invalid")
        elif row["decision"] == "defer" and (
            row["reason"] is not None
            and (type(row["reason"]) is not str or not row["reason"])
        ):
                raise ProductPlanningError("capability_gap_decision_invalid")
        return row

    @staticmethod
    def _capability_source_proposal_error_contract() -> dict[str, Any]:
        details = {
            "schema": "data_contract.v1",
            "type": "object",
            "properties": {},
            "required": [],
            "additional_properties": False,
        }
        return {
            "schema": "error_contract.v1",
            "errors": {
                "INPUT_CONTRACT_VIOLATION": {
                    "field": None,
                    "details": details,
                },
                "OUTPUT_CONTRACT_VIOLATION": {
                    "field": None,
                    "details": details,
                },
            },
        }

    @staticmethod
    def _capability_source_proposal_format_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "schema": {
                    "type": "string",
                    "enum": [CAPABILITY_SOURCE_PROPOSAL_OUTPUT_VERSION],
                },
                "entry": {
                    "type": "object",
                    "properties": {
                        "module_relpath": {
                            "type": "string",
                            "enum": ["capability.js"],
                        },
                        "export_name": {
                            "type": "string",
                            "enum": ["compute"],
                        },
                    },
                    "required": ["module_relpath", "export_name"],
                    "additionalProperties": False,
                },
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "enum": ["capability.js"],
                            },
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                    "maxItems": 1,
                },
            },
            "required": ["schema", "entry", "files"],
            "additionalProperties": False,
        }

    @staticmethod
    def _capability_source_proposal_format_schema_v2(
        input_contract: dict[str, Any],
        result_enum: list[str],
    ) -> dict[str, Any]:
        input_properties: dict[str, Any] = {}
        for field in sorted(
            input_contract["properties"],
            key=lambda value: value.encode("utf-8"),
        ):
            contract = input_contract["properties"][field]
            if contract["type"] == "integer":
                input_properties[field] = {"type": "integer"}
            elif contract["type"] == "boolean":
                input_properties[field] = {"type": "boolean"}
            else:
                raise ProductPlanningError(
                    "capability_source_proposal_request_invalid"
                )
        witness_count = len(result_enum)
        return {
            "type": "object",
            "properties": {
                "schema": {
                    "type": "string",
                    "enum": [CAPABILITY_SOURCE_PROPOSAL_OUTPUT_V2],
                },
                "entry": {
                    "type": "object",
                    "properties": {
                        "module_relpath": {
                            "type": "string",
                            "enum": ["capability.js"],
                        },
                        "export_name": {
                            "type": "string",
                            "enum": ["compute"],
                        },
                    },
                    "required": ["module_relpath", "export_name"],
                    "additionalProperties": False,
                },
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "enum": ["capability.js"],
                            },
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                    "maxItems": 1,
                },
                "witnesses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "input": {
                                "type": "object",
                                "properties": input_properties,
                                "required": list(input_properties),
                                "additionalProperties": False,
                            },
                            "expected_scalar_result": {
                                "type": "string",
                                "enum": copy.deepcopy(result_enum),
                            },
                        },
                        "required": ["input", "expected_scalar_result"],
                        "additionalProperties": False,
                    },
                    "minItems": witness_count,
                    "maxItems": witness_count,
                },
            },
            "required": ["schema", "entry", "files", "witnesses"],
            "additionalProperties": False,
        }

    @classmethod
    def _build_capability_source_proposal_request(
        cls,
        authorization: dict[str, Any],
    ) -> dict[str, Any]:
        adapter_version = authorization["adapter_contract_version"]
        adapter_semantics = {
            "contract_version": adapter_version,
            "result_field": authorization["result_field"],
            "passthrough_fields": copy.deepcopy(
                authorization["passthrough_fields"]
            ),
            "source_result": "scalar_integer",
            "adapter_output": (
                "proved_scalar_result"
                if adapter_version == "computation_adapter.v2"
                else "validated_input_passthrough_plus_proved_scalar_result"
            ),
        }
        safe_input = {
            "schema_version": "capability_source_proposal_input.v1",
            "behavior_intent": authorization["behavior_intent"],
            "input_contract": copy.deepcopy(authorization["input_contract"]),
            "output_contract": copy.deepcopy(authorization["output_contract"]),
            "error_contract": copy.deepcopy(authorization["error_contract"]),
            "acceptance_cases": copy.deepcopy(
                authorization["acceptance_cases"]
            ),
            "adapter": adapter_semantics,
            "entry": {
                "module_relpath": "capability.js",
                "export_name": "compute",
            },
            "safety_constraints": [
                "input_immutable",
                "no_dependencies",
                "no_environment",
                "no_filesystem",
                "no_global_state",
                "no_network",
                "no_process",
                "no_randomness",
                "no_time",
                "output_contract_required",
            ],
        }
        prompt = (
            "Generate one deterministic pure JavaScript computation. "
            "Return exactly one JSON object matching FORMAT_SCHEMA. "
            "Create only capability.js with the named export compute. "
            "The source function returns the scalar integer for result_field; "
            "the declared adapter constructs the formal output. "
            "Do not add Markdown or explanation text.\n"
            "REQUEST_JSON:\n"
            + _canonical_bytes(safe_input).decode("utf-8")
        )
        body = {
            "schema_version": CAPABILITY_SOURCE_PROPOSAL_REQUEST_VERSION,
            "formal_binding": {
                "authorization_digest": authorization[
                    "authorization_digest"
                ],
                "plan_digest": authorization["plan_digest"],
                "gap_id": authorization["gap_id"],
                "projection_digest": authorization["projection_digest"],
                "authorize_decision_digest": authorization[
                    "authorize_decision_digest"
                ],
                "warehouse_revision": authorization[
                    "warehouse_revision"
                ],
                "catalog_digest": authorization["catalog_digest"],
                "prompt_version": CAPABILITY_SOURCE_PROPOSAL_PROMPT_VERSION,
                "output_protocol_version": (
                    CAPABILITY_SOURCE_PROPOSAL_OUTPUT_VERSION
                ),
            },
            "model_safe_input": safe_input,
            "prompt": prompt,
            "format_schema": cls._capability_source_proposal_format_schema(),
            "stream": False,
        }
        return {**body, "request_digest": _digest(body)}

    @classmethod
    def _build_capability_source_proposal_request_v2(
        cls,
        authorization: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            row = _stored_exact(
                authorization,
                {
                    "schema_version",
                    "plan_id",
                    "plan_version",
                    "plan_digest",
                    "gap_id",
                    "projection_digest",
                    "capability_key",
                    "capability_kind",
                    "slot",
                    "input_contract",
                    "output_contract",
                    "error_contract",
                    "adapter_contract_version",
                    "result_field",
                    "passthrough_fields",
                    "authorize_decision_digest",
                    "behavior_intent",
                    "acceptance_cases",
                    "warehouse_revision",
                    "catalog_digest",
                    "authorization_source",
                    "locked_at",
                    "authorization_digest",
                    "request",
                },
            )
            authorization_body = {
                key: item
                for key, item in row.items()
                if key not in {"authorization_digest", "request"}
            }
            if (
                row["schema_version"]
                != CAPABILITY_SOURCE_PROPOSAL_AUTHORIZATION_VERSION
                or row["capability_kind"] != "computation"
                or row["authorization_source"]
                != "user_confirmed_gap_decision"
                or row["authorization_digest"] != _digest(authorization_body)
                or row["request"]
                != cls._build_capability_source_proposal_request(row)
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_request_invalid"
                )
            normalized_input, normalized_output, normalized_error = (
                normalize_capsule_contracts(
                    "computation",
                    row["input_contract"],
                    row["output_contract"],
                    row["error_contract"],
                )
            )
            adapter = cls._integer_gap_adapter(
                normalized_input,
                normalized_output,
            )
            if (
                normalized_input != row["input_contract"]
                or normalized_output != row["output_contract"]
                or normalized_error != row["error_contract"]
                or adapter is None
                or adapter["adapter_contract_version"]
                != row["adapter_contract_version"]
                or adapter["result_field"] != row["result_field"]
                or adapter["passthrough_fields"]
                != row["passthrough_fields"]
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_request_invalid"
                )
            input_properties = normalized_input["properties"]
            output_properties = normalized_output["properties"]
            input_fields = sorted(
                input_properties,
                key=lambda field: field.encode("utf-8"),
            )
            scalar_contracts = [
                input_properties[field] for field in input_fields
            ] + [output_properties[row["result_field"]]]
            if any(
                set(contract) != {"type", "minimum", "maximum"}
                or contract["type"] != "integer"
                or type(contract["minimum"]) is not int
                or type(contract["maximum"]) is not int
                or contract["minimum"] > contract["maximum"]
                for contract in scalar_contracts
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_request_invalid"
                )
            source_function = {
                "schema_version": CAPABILITY_SOURCE_FUNCTION_ABI_VERSION,
                "module_relpath": "capability.js",
                "export_name": "compute",
                "parameters": [
                    {
                        "position": position,
                        "parameter_name": f"arg{position}",
                        "input_field": field,
                        "contract": copy.deepcopy(
                            input_properties[field]
                        ),
                    }
                    for position, field in enumerate(input_fields)
                ],
                "return_contract": copy.deepcopy(
                    output_properties[row["result_field"]]
                ),
            }
            source_examples = []
            for case in row["acceptance_cases"]:
                exact = _stored_exact(
                    case,
                    {"input", "expected_output"},
                )
                if (
                    not data_contract_accepts(
                        normalized_input,
                        exact["input"],
                    )
                    or not data_contract_accepts(
                        normalized_output,
                        exact["expected_output"],
                    )
                    or any(
                        _canonical_bytes(exact["input"][field])
                        != _canonical_bytes(
                            exact["expected_output"][field]
                        )
                        for field in row["passthrough_fields"]
                    )
                ):
                    raise ProductPlanningError(
                        "capability_source_proposal_request_invalid"
                    )
                source_examples.append(
                    {
                        "arguments": [
                            copy.deepcopy(exact["input"][field])
                            for field in input_fields
                        ],
                        "expected_scalar_result": copy.deepcopy(
                            exact["expected_output"][row["result_field"]]
                        ),
                    }
                )
            safe_input = {
                "source_function": source_function,
                "adapter_projection": {
                    "contract_version": row[
                        "adapter_contract_version"
                    ],
                    "result_field": row["result_field"],
                    "passthrough_fields": copy.deepcopy(
                        row["passthrough_fields"]
                    ),
                },
                "source_examples": source_examples,
            }
            parameter_names = ", ".join(
                item["parameter_name"]
                for item in source_function["parameters"]
            )
            prompt = (
                "Generate one deterministic pure JavaScript source proposal. "
                f"Implement exactly export function compute({parameter_names}). "
                "The parameters and their order must match source_function. "
                "Return one integer scalar matching return_contract. "
                "Do not return an object, array, Promise, or wrapped result; "
                "Reweave's adapter constructs the formal output object. "
                "Do not modify inputs and do not use dependencies, network, "
                "filesystem, environment variables, process state, global "
                "state, randomness, or time. Return exactly one JSON object "
                "matching FORMAT_SCHEMA with no Markdown or explanation.\n"
                "REQUEST_JSON:\n"
                + _canonical_bytes(safe_input).decode("utf-8")
            )
            v1_request_digest = row["request"]["request_digest"]
            source_abi_digest = _digest(source_function)
            body = {
                "schema_version": CAPABILITY_SOURCE_PROPOSAL_REQUEST_V2,
                "formal_binding": {
                    "authorization_digest": row[
                        "authorization_digest"
                    ],
                    "plan_digest": row["plan_digest"],
                    "gap_id": row["gap_id"],
                    "projection_digest": row["projection_digest"],
                    "authorize_decision_digest": row[
                        "authorize_decision_digest"
                    ],
                    "warehouse_revision": row["warehouse_revision"],
                    "catalog_digest": row["catalog_digest"],
                    "prompt_version": (
                        CAPABILITY_SOURCE_PROPOSAL_PROMPT_V2
                    ),
                    "output_protocol_version": (
                        CAPABILITY_SOURCE_PROPOSAL_OUTPUT_VERSION
                    ),
                    "source_abi_digest": source_abi_digest,
                    "supersedes_request_digest": v1_request_digest,
                    "supersession_reason": (
                        "source_abi_protocol_clarification"
                    ),
                },
                "model_safe_input": safe_input,
                "prompt": prompt,
                "format_schema": (
                    cls._capability_source_proposal_format_schema()
                ),
                "stream": False,
            }
            return {**body, "request_digest": _digest(body)}
        except ProductPlanningError as exc:
            if exc.code == "capability_source_proposal_request_invalid":
                raise
            raise ProductPlanningError(
                "capability_source_proposal_request_invalid"
            ) from exc
        except (DataContractError, KeyError, TypeError) as exc:
            raise ProductPlanningError(
                "capability_source_proposal_request_invalid"
            ) from exc

    @classmethod
    def _build_capability_source_proposal_request_v3(
        cls,
        authorization: dict[str, Any],
        *,
        request_version: str = CAPABILITY_SOURCE_PROPOSAL_REQUEST_V3,
    ) -> dict[str, Any]:
        try:
            if request_version not in {
                CAPABILITY_SOURCE_PROPOSAL_REQUEST_V3,
                CAPABILITY_SOURCE_PROPOSAL_REQUEST_V4,
            }:
                raise ProductPlanningError(
                    "capability_source_proposal_request_invalid"
                )
            unordered_witnesses = (
                request_version == CAPABILITY_SOURCE_PROPOSAL_REQUEST_V4
            )
            authorization_value = (
                {
                    key: item
                    for key, item in authorization.items()
                    if key != "request"
                }
                if type(authorization) is dict
                else authorization
            )
            row = _stored_exact(
                authorization_value,
                {
                    "schema_version",
                    "plan_id",
                    "plan_version",
                    "plan_digest",
                    "gap_id",
                    "projection_digest",
                    "capability_key",
                    "capability_kind",
                    "slot",
                    "input_contract",
                    "output_contract",
                    "error_contract",
                    "adapter_contract_version",
                    "capture_mapping_schema",
                    "proof_schema",
                    "result_field",
                    "result_enum",
                    "passthrough_fields",
                    "authorize_decision_digest",
                    "behavior_intent",
                    "acceptance_cases",
                    "warehouse_revision",
                    "catalog_digest",
                    "authorization_source",
                    "locked_at",
                    "authorization_digest",
                },
            )
            authorization_body = {
                key: item
                for key, item in row.items()
                if key != "authorization_digest"
            }
            normalized_input, normalized_output, normalized_error = (
                normalize_capsule_contracts(
                    "computation",
                    row["input_contract"],
                    row["output_contract"],
                    row["error_contract"],
                )
            )
            adapter = cls._finite_enum_gap_adapter(
                normalized_input,
                normalized_output,
            )
            if (
                row["schema_version"]
                != CAPABILITY_SOURCE_PROPOSAL_AUTHORIZATION_V2
                or row["capability_kind"] != "computation"
                or row["authorization_source"]
                != "user_confirmed_gap_decision"
                or row["authorization_digest"] != _digest(authorization_body)
                or normalized_input != row["input_contract"]
                or normalized_output != row["output_contract"]
                or normalized_error != row["error_contract"]
                or adapter is None
                or any(
                    row[key] != adapter[key]
                    for key in (
                        "adapter_contract_version",
                        "capture_mapping_schema",
                        "proof_schema",
                        "result_field",
                        "result_enum",
                        "passthrough_fields",
                    )
                )
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_request_invalid"
                )
            input_properties = normalized_input["properties"]
            input_fields = sorted(
                input_properties,
                key=lambda value: value.encode("utf-8"),
            )
            for contract in input_properties.values():
                if (
                    set(contract) == {"type", "minimum", "maximum"}
                    and contract["type"] == "integer"
                    and type(contract["minimum"]) is int
                    and type(contract["maximum"]) is int
                    and contract["minimum"] <= contract["maximum"]
                ) or contract == {"type": "boolean"}:
                    continue
                if contract.get("type") == "string":
                    raise ProductPlanningError(
                        "capability_source_proposal_input_enumeration_review_required"
                    )
                raise ProductPlanningError(
                    "capability_source_proposal_request_invalid"
                )
            for case in row["acceptance_cases"]:
                exact = _stored_exact(case, {"input", "expected_output"})
                if not data_contract_accepts(
                    normalized_input,
                    exact["input"],
                ) or not data_contract_accepts(
                    normalized_output,
                    exact["expected_output"],
                ):
                    raise ProductPlanningError(
                        "capability_source_proposal_request_invalid"
                    )
            source_function = {
                "schema_version": CAPABILITY_SOURCE_FUNCTION_ABI_V2,
                "module_relpath": "capability.js",
                "export_name": "compute",
                "parameters": [
                    {
                        "position": position,
                        "parameter_name": f"arg{position}",
                        "input_field": field,
                        "contract": copy.deepcopy(input_properties[field]),
                    }
                    for position, field in enumerate(input_fields)
                ],
                "return_contract": copy.deepcopy(
                    normalized_output["properties"][row["result_field"]]
                ),
            }
            safe_input = {
                "source_function": source_function,
                "adapter_projection": {
                    "contract_version": row["adapter_contract_version"],
                    "capture_mapping_schema": row[
                        "capture_mapping_schema"
                    ],
                    "proof_schema": row["proof_schema"],
                    "result_field": row["result_field"],
                    "result_enum": copy.deepcopy(row["result_enum"]),
                    "passthrough_fields": [],
                },
                "user_acceptance_examples": copy.deepcopy(
                    row["acceptance_cases"]
                ),
                "witness_requirements": {
                    "count": len(row["result_enum"]),
                    (
                        "expected_scalar_results"
                        if unordered_witnesses
                        else "ordered_expected_scalar_results"
                    ): copy.deepcopy(row["result_enum"]),
                    "unique_inputs": True,
                },
            }
            parameter_names = ", ".join(
                item["parameter_name"]
                for item in source_function["parameters"]
            )
            witness_instruction = (
                "Provide exactly one witness for each enum result; "
                "witness array order has no meaning. "
                if unordered_witnesses
                else
                "Provide exactly one witness for each ordered enum result, "
            )
            prompt = (
                "Generate one deterministic pure JavaScript source proposal. "
                f"Implement exactly export function compute({parameter_names}). "
                "The parameters and their order must match source_function. "
                "Return one scalar string from return_contract.enum. "
                "Do not return an object, array, Promise, or wrapped result; "
                "Reweave's adapter constructs the formal output object. "
                f"{witness_instruction}"
                "using unique contract-valid inputs. Do not modify inputs and "
                "do not use dependencies, network, filesystem, environment "
                "variables, process state, global state, randomness, or time. "
                "Return exactly one JSON object matching FORMAT_SCHEMA with "
                "no Markdown or explanation.\nREQUEST_JSON:\n"
                + _canonical_bytes(safe_input).decode("utf-8")
            )
            body = {
                "schema_version": request_version,
                "formal_binding": {
                    "authorization_digest": row["authorization_digest"],
                    "plan_digest": row["plan_digest"],
                    "gap_id": row["gap_id"],
                    "projection_digest": row["projection_digest"],
                    "authorize_decision_digest": row[
                        "authorize_decision_digest"
                    ],
                    "warehouse_revision": row["warehouse_revision"],
                    "catalog_digest": row["catalog_digest"],
                    "prompt_version": (
                        CAPABILITY_SOURCE_PROPOSAL_PROMPT_V4
                        if unordered_witnesses
                        else CAPABILITY_SOURCE_PROPOSAL_PROMPT_V3
                    ),
                    "output_protocol_version": (
                        CAPABILITY_SOURCE_PROPOSAL_OUTPUT_V2
                    ),
                    "source_abi_digest": _digest(source_function),
                },
                "model_safe_input": safe_input,
                "prompt": prompt,
                "format_schema": cls._capability_source_proposal_format_schema_v2(
                    normalized_input,
                    row["result_enum"],
                ),
                "stream": False,
            }
            return {**body, "request_digest": _digest(body)}
        except ProductPlanningError as exc:
            if exc.code in {
                "capability_source_proposal_request_invalid",
                "capability_source_proposal_input_enumeration_review_required",
            }:
                raise
            raise ProductPlanningError(
                "capability_source_proposal_request_invalid"
            ) from exc
        except (DataContractError, KeyError, TypeError) as exc:
            raise ProductPlanningError(
                "capability_source_proposal_request_invalid"
            ) from exc

    @classmethod
    def _build_capability_source_proposal_request_v4(
        cls,
        authorization: dict[str, Any],
    ) -> dict[str, Any]:
        return cls._build_capability_source_proposal_request_v3(
            authorization,
            request_version=CAPABILITY_SOURCE_PROPOSAL_REQUEST_V4,
        )

    @classmethod
    def _runtime_capability_source_proposal_request(
        cls,
        authorization: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            authorization.get("schema_version")
            == CAPABILITY_SOURCE_PROPOSAL_AUTHORIZATION_V2
        ):
            request = authorization.get("request")
            request_version = (
                request.get("schema_version")
                if type(request) is dict
                else CAPABILITY_SOURCE_PROPOSAL_REQUEST_V4
            )
            if request_version == CAPABILITY_SOURCE_PROPOSAL_REQUEST_V3:
                return cls._build_capability_source_proposal_request_v3(
                    authorization
                )
            if request_version == CAPABILITY_SOURCE_PROPOSAL_REQUEST_V4:
                return cls._build_capability_source_proposal_request_v4(
                    authorization
                )
            raise ProductPlanningError(
                "capability_source_proposal_request_invalid"
            )
        return cls._build_capability_source_proposal_request_v2(
            authorization
        )

    @classmethod
    def validate_capability_source_proposal_response(
        cls,
        value: Any,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if (
            type(value) is dict
            and value.get("schema") == CAPABILITY_SOURCE_PROPOSAL_OUTPUT_V2
        ):
            return cls._validate_capability_source_proposal_response_v2(
                value,
                request,
            )
        try:
            row = _stored_exact(value, {"schema", "entry", "files"})
            entry = _stored_exact(
                row["entry"],
                {"module_relpath", "export_name"},
            )
            if (
                row["schema"] != CAPABILITY_SOURCE_PROPOSAL_OUTPUT_VERSION
                or entry
                != {
                    "module_relpath": "capability.js",
                    "export_name": "compute",
                }
                or type(row["files"]) is not list
                or len(row["files"]) != 1
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_response_invalid"
                )
            file = _stored_exact(row["files"][0], {"path", "content"})
            content = file["content"]
            if type(content) is not str:
                raise ProductPlanningError(
                    "capability_source_proposal_response_invalid"
                )
            encoded = content.encode("utf-8")
            exports = re.findall(
                r"\bexport\s+function\s+"
                r"([A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
                content,
            )
            if (
                file["path"] != "capability.js"
                or not content.strip()
                or not 1 <= len(encoded)
                <= CAPABILITY_SOURCE_PROPOSAL_MAX_BYTES
                or "```" in content
                or exports != ["compute"]
                or len(re.findall(r"\bexport\b", content)) != 1
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_response_invalid"
                )
        except ProductPlanningError as exc:
            if exc.code == "capability_source_proposal_response_invalid":
                raise
            raise ProductPlanningError(
                "capability_source_proposal_response_invalid"
            ) from exc
        except (TypeError, UnicodeEncodeError) as exc:
            raise ProductPlanningError(
                "capability_source_proposal_response_invalid"
            ) from exc
        return copy.deepcopy(row)

    @classmethod
    def _validate_capability_source_proposal_response_v2(
        cls,
        value: Any,
        request: dict[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            row = _stored_exact(
                value,
                {"schema", "entry", "files", "witnesses"},
            )
            entry = _stored_exact(
                row["entry"],
                {"module_relpath", "export_name"},
            )
            if (
                type(request) is not dict
                or request.get("schema_version")
                not in {
                    CAPABILITY_SOURCE_PROPOSAL_REQUEST_V3,
                    CAPABILITY_SOURCE_PROPOSAL_REQUEST_V4,
                }
                or row["schema"] != CAPABILITY_SOURCE_PROPOSAL_OUTPUT_V2
                or entry
                != {
                    "module_relpath": "capability.js",
                    "export_name": "compute",
                }
                or type(row["files"]) is not list
                or len(row["files"]) != 1
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_response_invalid"
                )
            file = _stored_exact(row["files"][0], {"path", "content"})
            content = file["content"]
            if type(content) is not str:
                raise ProductPlanningError(
                    "capability_source_proposal_response_invalid"
                )
            encoded = content.encode("utf-8")
            exports = re.findall(
                r"\bexport\s+function\s+"
                r"([A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
                content,
            )
            source_function = request["model_safe_input"]["source_function"]
            request_version = request["schema_version"]
            requirement_key = (
                "expected_scalar_results"
                if request_version
                == CAPABILITY_SOURCE_PROPOSAL_REQUEST_V4
                else "ordered_expected_scalar_results"
            )
            result_enum = request["model_safe_input"][
                "witness_requirements"
            ][requirement_key]
            parameters = source_function["parameters"]
            input_contract = {
                "schema": "data_contract.v1",
                "type": "object",
                "properties": {
                    item["input_field"]: copy.deepcopy(item["contract"])
                    for item in parameters
                },
                "required": [
                    item["input_field"]
                    for item in parameters
                ],
                "additional_properties": False,
            }
            if (
                file["path"] != "capability.js"
                or not content.strip()
                or not 1 <= len(encoded)
                <= CAPABILITY_SOURCE_PROPOSAL_MAX_BYTES
                or "```" in content
                or exports != ["compute"]
                or len(re.findall(r"\bexport\b", content)) != 1
                or type(row["witnesses"]) is not list
                or len(row["witnesses"]) != len(result_enum)
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_response_invalid"
                )
            inputs: set[bytes] = set()
            actual_results: list[str] = []
            witnesses_by_result: dict[str, dict[str, Any]] = {}
            for witness in row["witnesses"]:
                exact = _stored_exact(
                    witness,
                    {"input", "expected_scalar_result"},
                )
                if not data_contract_accepts(
                    input_contract,
                    exact["input"],
                ):
                    raise ProductPlanningError(
                        "capability_source_proposal_response_invalid"
                    )
                input_bytes = _canonical_bytes(exact["input"])
                if input_bytes in inputs:
                    raise ProductPlanningError(
                        "capability_source_proposal_response_invalid"
                    )
                inputs.add(input_bytes)
                scalar = exact["expected_scalar_result"]
                if type(scalar) is not str:
                    raise ProductPlanningError(
                        "capability_source_proposal_response_invalid"
                    )
                actual_results.append(scalar)
                if scalar in witnesses_by_result:
                    raise ProductPlanningError(
                        "capability_source_proposal_response_invalid"
                    )
                witnesses_by_result[scalar] = copy.deepcopy(exact)
            if (
                request_version == CAPABILITY_SOURCE_PROPOSAL_REQUEST_V3
                and actual_results != result_enum
            ) or (
                request_version == CAPABILITY_SOURCE_PROPOSAL_REQUEST_V4
                and set(witnesses_by_result) != set(result_enum)
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_response_invalid"
                )
        except ProductPlanningError as exc:
            if exc.code == "capability_source_proposal_response_invalid":
                raise
            raise ProductPlanningError(
                "capability_source_proposal_response_invalid"
            ) from exc
        except (
            DataContractError,
            KeyError,
            TypeError,
            UnicodeEncodeError,
        ) as exc:
            raise ProductPlanningError(
                "capability_source_proposal_response_invalid"
            ) from exc
        normalized = copy.deepcopy(row)
        if request_version == CAPABILITY_SOURCE_PROPOSAL_REQUEST_V4:
            normalized["witnesses"] = [
                witnesses_by_result[result]
                for result in result_enum
            ]
        return normalized

    def _validate_capability_source_proposal_authorization(
        self,
        workspace: dict[str, Any],
        value: Any,
        projection: dict[str, Any],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            type(value) is dict
            and value.get("schema_version")
            == CAPABILITY_SOURCE_PROPOSAL_AUTHORIZATION_V2
        ):
            return self._validate_capability_source_proposal_authorization_v2(
                workspace,
                value,
                projection,
                decision,
            )
        row = _stored_exact(
            value,
            {
                "schema_version",
                "plan_id",
                "plan_version",
                "plan_digest",
                "gap_id",
                "projection_digest",
                "capability_key",
                "capability_kind",
                "slot",
                "input_contract",
                "output_contract",
                "error_contract",
                "adapter_contract_version",
                "result_field",
                "passthrough_fields",
                "authorize_decision_digest",
                "behavior_intent",
                "acceptance_cases",
                "warehouse_revision",
                "catalog_digest",
                "authorization_source",
                "locked_at",
                "authorization_digest",
                "request",
            },
        )
        body = {
            key: item
            for key, item in row.items()
            if key not in {"authorization_digest", "request"}
        }
        plan = workspace.get("plan")
        if (
            type(plan) is not dict
            or row["schema_version"]
            != CAPABILITY_SOURCE_PROPOSAL_AUTHORIZATION_VERSION
            or row["plan_id"] != plan["plan_id"]
            or row["plan_version"] != plan["plan_version"]
            or row["plan_digest"] != plan["canonical_digest"]
            or row["gap_id"] != projection["gap_id"]
            or row["projection_digest"] != projection["projection_digest"]
            or row["capability_key"] != projection["capability_key"]
            or row["capability_kind"] != "computation"
            or row["slot"] != projection["slot"]
            or row["input_contract"] != projection["input_contract"]
            or row["output_contract"] != projection["output_contract"]
            or row["error_contract"]
            != self._capability_source_proposal_error_contract()
            or row["adapter_contract_version"]
            != projection["adapter_contract_version"]
            or row["result_field"] != projection["result_field"]
            or row["passthrough_fields"]
            != projection["passthrough_fields"]
            or decision["decision"] != "authorize"
            or row["authorize_decision_digest"]
            != decision["canonical_digest"]
            or row["behavior_intent"] != decision["behavior_intent"]
            or row["acceptance_cases"] != decision["acceptance_cases"]
            or row["warehouse_revision"]
            != projection["warehouse_revision"]
            or row["catalog_digest"] != projection["catalog_digest"]
            or row["authorization_source"]
            != "user_confirmed_gap_decision"
            or type(row["locked_at"]) is not str
            or not row["locked_at"]
            or row["authorization_digest"] != _digest(body)
            or row["request"]
            != self._build_capability_source_proposal_request(row)
        ):
            raise ProductPlanningError(
                "capability_source_proposal_authorization_invalid"
            )
        return row

    def _validate_capability_source_proposal_authorization_v2(
        self,
        workspace: dict[str, Any],
        value: Any,
        projection: dict[str, Any],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        row = _stored_exact(
            value,
            {
                "schema_version",
                "plan_id",
                "plan_version",
                "plan_digest",
                "gap_id",
                "projection_digest",
                "capability_key",
                "capability_kind",
                "slot",
                "input_contract",
                "output_contract",
                "error_contract",
                "adapter_contract_version",
                "capture_mapping_schema",
                "proof_schema",
                "result_field",
                "result_enum",
                "passthrough_fields",
                "authorize_decision_digest",
                "behavior_intent",
                "acceptance_cases",
                "warehouse_revision",
                "catalog_digest",
                "authorization_source",
                "locked_at",
                "authorization_digest",
                "request",
            },
        )
        body = {
            key: item
            for key, item in row.items()
            if key not in {"authorization_digest", "request"}
        }
        plan = workspace.get("plan")
        authorization = {
            key: item for key, item in row.items() if key != "request"
        }
        if (
            type(plan) is not dict
            or projection.get("schema_version")
            != CAPABILITY_GAP_PROJECTION_V2
            or row["schema_version"]
            != CAPABILITY_SOURCE_PROPOSAL_AUTHORIZATION_V2
            or row["plan_id"] != plan["plan_id"]
            or row["plan_version"] != plan["plan_version"]
            or row["plan_digest"] != plan["canonical_digest"]
            or row["gap_id"] != projection["gap_id"]
            or row["projection_digest"] != projection["projection_digest"]
            or row["capability_key"] != projection["capability_key"]
            or row["capability_kind"] != "computation"
            or row["slot"] != projection["slot"]
            or row["input_contract"] != projection["input_contract"]
            or row["output_contract"] != projection["output_contract"]
            or row["error_contract"]
            != self._capability_source_proposal_error_contract()
            or any(
                row[key] != projection[key]
                for key in (
                    "adapter_contract_version",
                    "capture_mapping_schema",
                    "proof_schema",
                    "result_field",
                    "result_enum",
                    "passthrough_fields",
                )
            )
            or decision["decision"] != "authorize"
            or row["authorize_decision_digest"]
            != decision["canonical_digest"]
            or row["behavior_intent"] != decision["behavior_intent"]
            or row["acceptance_cases"] != decision["acceptance_cases"]
            or row["warehouse_revision"]
            != projection["warehouse_revision"]
            or row["catalog_digest"] != projection["catalog_digest"]
            or row["authorization_source"]
            != "user_confirmed_gap_decision"
            or type(row["locked_at"]) is not str
            or not row["locked_at"]
            or row["authorization_digest"] != _digest(body)
            or type(row["request"]) is not dict
        ):
            raise ProductPlanningError(
                "capability_source_proposal_authorization_invalid"
            )
        request_version = row["request"].get("schema_version")
        if request_version == CAPABILITY_SOURCE_PROPOSAL_REQUEST_V3:
            expected_request = (
                self._build_capability_source_proposal_request_v3(
                    authorization
                )
            )
        elif request_version == CAPABILITY_SOURCE_PROPOSAL_REQUEST_V4:
            expected_request = (
                self._build_capability_source_proposal_request_v4(
                    authorization
                )
            )
        else:
            raise ProductPlanningError(
                "capability_source_proposal_authorization_invalid"
            )
        if row["request"] != expected_request:
            raise ProductPlanningError(
                "capability_source_proposal_authorization_invalid"
            )
        return row

    def _read_capability_source_proposal_authorization(
        self,
        workspace: dict[str, Any],
        projection: dict[str, Any],
        decision: dict[str, Any],
    ) -> dict[str, Any] | None:
        plan = workspace["plan"]
        path = self._capability_source_proposal_authorization_path_for(
            workspace,
            plan,
            projection,
        )
        paths = self._capability_source_proposal_authorization_paths(workspace)
        if not paths:
            return None
        if paths != [path]:
            raise ProductPlanningError(
                "capability_source_proposal_authorization_invalid"
            )
        return self._validate_capability_source_proposal_authorization(
            workspace,
            self._read_json(path),
            projection,
            decision,
        )

    def _capability_gap_decisions(
        self,
        workspace: dict[str, Any],
        projection: dict[str, Any],
    ) -> list[dict[str, Any]]:
        plan = workspace["plan"]
        directory = self._capability_gap_decisions_dir(workspace, plan)
        if not directory.exists() and not directory.is_symlink():
            return []
        self._assert_no_symlink_components(directory)
        if directory.is_symlink() or not directory.is_dir():
            raise ProductPlanningError("product_workspace_symlink_forbidden")
        try:
            entries = sorted(directory.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            raise ProductPlanningError(
                "product_planning_state_unavailable"
            ) from exc
        if len(entries) > MAX_CAPABILITY_GAP_DECISIONS:
            raise ProductPlanningError("capability_gap_decision_limit")
        decisions: list[dict[str, Any]] = []
        previous: dict[str, Any] | None = None
        for entry in entries:
            match = _GAP_DECISION_FILENAME.fullmatch(entry.name)
            if match is None or entry.is_symlink() or not entry.is_file():
                raise ProductPlanningError("capability_gap_decision_invalid")
            row = self._validate_capability_gap_decision(
                self._read_json(entry),
                projection,
                previous,
            )
            if (
                int(match.group(1)) != row["sequence"]
                or match.group(2) != row["canonical_digest"]
            ):
                raise ProductPlanningError("capability_gap_decision_invalid")
            decisions.append(row)
            previous = row
        return decisions

    def _capability_gap_views(
        self,
        workspace: dict[str, Any],
        catalog: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        plan = workspace.get("plan")
        if type(plan) is not dict:
            return []
        gaps = [
            gap
            for section in plan["sections"]
            for gap in section["gaps"]
        ]
        if not gaps:
            return []
        stored = self._read_capability_gap_projection(workspace)
        expected: dict[str, Any] | None = None
        status = "capability_gap_projection_missing"
        if catalog is not None:
            expected, status = (
                self._capability_gap_projection_for_workspace(
                    workspace,
                    plan,
                    catalog,
                )
            )
        elif stored is not None:
            expected, status = stored, "available"
        if stored is not None:
            projection = stored
            if (
                catalog is not None
                and (
                    expected is None
                    or expected != stored
                    or stored["warehouse_revision"]
                    != catalog["warehouse_revision"]
                    or stored["catalog_digest"] != _digest(catalog)
                )
            ):
                status = "capability_gap_projection_stale"
            else:
                status = "available"
        else:
            projection = expected
        decisions = (
            self._capability_gap_decisions(workspace, projection)
            if projection is not None
            else []
        )
        authorization = None
        source_proposal_run = None
        if projection is not None:
            authorization_path = (
                self._capability_source_proposal_authorization_path_for(
                    workspace,
                    plan,
                    projection,
                )
            )
            if authorization_path.exists() or authorization_path.is_symlink():
                if not decisions or decisions[-1]["decision"] != "authorize":
                    raise ProductPlanningError(
                        "capability_source_proposal_authorization_invalid"
                    )
                authorization = (
                    self._read_capability_source_proposal_authorization(
                        workspace,
                        projection,
                        decisions[-1],
                    )
                )
                run_path = (
                    self._capability_source_proposal_run_identity_path(
                        workspace,
                        plan,
                    )
                )
                if run_path.exists() or run_path.is_symlink():
                    identity = (
                        self._validate_capability_source_proposal_run_identity(
                            workspace,
                            self._read_json(run_path),
                        )
                    )
                    source_proposal_run = (
                        self._capability_source_proposal_run_projection(
                            workspace,
                            identity,
                        )
                    )
        public_projection = (
            {
                key: copy.deepcopy(projection[key])
                for key in (
                    "projection_digest",
                    "capability_key",
                    "capability_group_display_name",
                    "capability_kind",
                    "slot",
                    "input_contract",
                    "output_contract",
                    "adapter_contract_version",
                    "result_field",
                    "passthrough_fields",
                    "warehouse_revision",
                    "catalog_digest",
                )
            }
            if projection is not None
            else None
        )
        if (
            public_projection is not None
            and projection["schema_version"] == CAPABILITY_GAP_PROJECTION_V2
        ):
            public_projection.update(
                {
                    "schema_version": CAPABILITY_GAP_PROJECTION_V2,
                    "proof_schema": projection["proof_schema"],
                    "result_enum": copy.deepcopy(
                        projection["result_enum"]
                    ),
                }
            )
        return [
            {
                "gap_id": gap["gap_id"],
                "title": gap["title"],
                "reason": gap["reason"],
                "requirement_ids": copy.deepcopy(gap["requirement_ids"]),
                "status": (
                    status
                    if len(gaps) == 1
                    else "capability_gap_plan_count_unsupported"
                ),
                "projection": (
                    public_projection
                    if len(gaps) == 1
                    and projection is not None
                    and gap["gap_id"] == projection["gap_id"]
                    else None
                ),
                "decision_history": copy.deepcopy(decisions),
                "current_decision": (
                    copy.deepcopy(decisions[-1]) if decisions else None
                ),
                "source_proposal_authorization": (
                    {
                        "authorization_digest": authorization[
                            "authorization_digest"
                        ],
                        "locked_at": authorization["locked_at"],
                        "status": "locked",
                    }
                    if authorization is not None
                    else None
                ),
                "source_proposal_request": (
                    {
                        "request_digest": authorization["request"][
                            "request_digest"
                        ],
                        "prompt_version": authorization["request"][
                            "formal_binding"
                        ]["prompt_version"],
                        "output_protocol_version": authorization["request"][
                            "formal_binding"
                        ]["output_protocol_version"],
                        "status": "waiting_model_authorization",
                    }
                    if authorization is not None
                    else None
                ),
                "source_proposal_run": (
                    copy.deepcopy(source_proposal_run)
                    if source_proposal_run is not None
                    and source_proposal_run["run_id"]
                    else None
                ),
            }
            for gap in gaps
        ]

    def _validate_confirmed_snapshot(self, workspace: dict[str, Any]) -> None:
        plan = workspace.get("plan")
        confirmation = workspace.get("confirmation")
        if type(plan) is not dict or type(confirmation) is not dict:
            raise ProductPlanningError("product_workspace_corrupt")
        path = self._confirmation_snapshot_path(workspace, plan)
        value = self._read_json(path)
        row = _stored_exact(value, {"plan", "confirmation"})
        if row["plan"] != plan or row["confirmation"] != confirmation:
            raise ProductPlanningError("product_workspace_corrupt")

    def _validate_candidate_acceptance_confirmation_binding(
        self,
        workspace: dict[str, Any],
        value: Any,
    ) -> None:
        plan = workspace.get("plan")
        confirmation = workspace.get("confirmation")
        row = _stored_exact(
            value,
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
        )
        body = {
            key: item for key, item in row.items() if key != "canonical_digest"
        }
        if (
            type(plan) is not dict
            or type(confirmation) is not dict
            or row["schema_version"]
            != CANDIDATE_ACCEPTANCE_CONFIRMATION_VERSION
            or row["plan_digest"] != plan["canonical_digest"]
            or row["plan_confirmation_digest"]
            != confirmation["receipt_digest"]
            or type(row["requirement_ids"]) is not list
            or not row["requirement_ids"]
            or type(row["cases"]) is not list
            or not 1
            <= len(row["cases"])
            <= MAX_CANDIDATE_ACCEPTANCE_CASES
            or type(row["confirmed_at"]) is not str
            or not row["confirmed_at"]
            or row["confirmation_source"] != "user_confirmed"
            or any(
                _DIGEST.fullmatch(str(row[key])) is None
                for key in (
                    "input_contract_digest",
                    "output_contract_digest",
                    "canonical_digest",
                )
            )
            or row["canonical_digest"] != _digest(body)
        ):
            raise ProductPlanningError(
                "candidate_acceptance_confirmation_invalid"
            )

    def _candidate_acceptance_confirmation_path(
        self,
        workspace: dict[str, Any],
        plan: dict[str, Any],
    ) -> Path:
        return (
            self._workspace_dir(workspace["workspace_id"])
            / "confirmed"
            / (
                "candidate_acceptance_v1_"
                f"{plan['plan_version']}_{plan['canonical_digest']}.json"
            )
        )

    def _agent_handoff_path(
        self,
        workspace: dict[str, Any],
        token_digest: str,
    ) -> Path:
        if _DIGEST.fullmatch(token_digest) is None:
            raise ProductPlanningError("agent_handoff_token_invalid")
        return (
            self._workspace_dir(workspace["workspace_id"])
            / "confirmed"
            / f"agent_handoff_v1_{token_digest}.json"
        )

    def _find_agent_handoff(
        self,
        handoff_token: str,
    ) -> tuple[dict[str, Any], dict[str, Any], Path]:
        if (
            type(handoff_token) is not str
            or _HANDOFF_TOKEN.fullmatch(handoff_token) is None
        ):
            raise ProductPlanningError("agent_handoff_token_invalid")
        token_digest = hashlib.sha256(handoff_token.encode("ascii")).hexdigest()
        # ponytail: bounded local workspace scan; add an index only if volume proves it.
        for workspace in self._workspaces():
            path = self._agent_handoff_path(workspace, token_digest)
            if not path.exists() and not path.is_symlink():
                continue
            record = self._read_json(path)
            self._validate_agent_handoff_record(record, token_digest)
            return workspace, record, path
        raise ProductPlanningError("agent_handoff_not_found")

    def _validate_agent_handoff_record(
        self,
        value: Any,
        token_digest: str,
    ) -> None:
        try:
            row = _stored_exact(
                value,
                {
                    "schema_version",
                    "token_digest",
                    "plan_digest",
                    "plan_confirmation_digest",
                    "acceptance_confirmation_digest",
                    "capsule_facts_digest",
                    "status",
                    "created_at",
                    "revoked_at",
                    "canonical_digest",
                },
            )
        except ProductPlanningError as exc:
            raise ProductPlanningError("agent_handoff_invalid") from exc
        body = {
            key: item for key, item in row.items() if key != "canonical_digest"
        }
        if (
            row["schema_version"] != "agent_handoff.v1"
            or row["token_digest"] != token_digest
            or any(
                _DIGEST.fullmatch(str(row[key])) is None
                for key in (
                    "plan_digest",
                    "plan_confirmation_digest",
                    "acceptance_confirmation_digest",
                    "capsule_facts_digest",
                    "canonical_digest",
                )
            )
            or row["status"] not in {"active", "revoked"}
            or type(row["created_at"]) is not str
            or not row["created_at"]
            or (
                row["status"] == "active"
                and row["revoked_at"] is not None
            )
            or (
                row["status"] == "revoked"
                and (
                    type(row["revoked_at"]) is not str
                    or not row["revoked_at"]
                )
            )
            or row["canonical_digest"] != _digest(body)
        ):
            raise ProductPlanningError("agent_handoff_invalid")

    def _validate_agent_handoff_binding(
        self,
        workspace: dict[str, Any],
        record: dict[str, Any],
    ) -> None:
        plan = workspace.get("plan")
        confirmation = workspace.get("confirmation")
        if (
            workspace.get("status") != "confirmed"
            or type(plan) is not dict
            or type(confirmation) is not dict
            or record["plan_digest"] != plan.get("canonical_digest")
            or record["plan_confirmation_digest"]
            != confirmation.get("receipt_digest")
        ):
            raise ProductPlanningError("agent_handoff_stale")
        path = self._candidate_acceptance_confirmation_path(workspace, plan)
        if path.is_symlink() or not path.is_file():
            raise ProductPlanningError("agent_handoff_stale")
        acceptance = self._read_json(path)
        try:
            self._validate_candidate_acceptance_confirmation_binding(
                workspace,
                acceptance,
            )
        except ProductPlanningError as exc:
            raise ProductPlanningError("agent_handoff_stale") from exc
        if (
            acceptance["canonical_digest"]
            != record["acceptance_confirmation_digest"]
        ):
            raise ProductPlanningError("agent_handoff_stale")

    def _confirmation_snapshot_path(
        self,
        workspace: dict[str, Any],
        plan: dict[str, Any],
    ) -> Path:
        return (
            self._workspace_dir(workspace["workspace_id"])
            / "confirmed"
            / f"plan_v{plan['plan_version']}_{plan['canonical_digest']}.json"
        )

    @staticmethod
    def _cancelled(cancel_check: Callable[[], bool] | None) -> None:
        if cancel_check is not None and cancel_check():
            raise ProductPlanningError("product_plan_cancelled")

    @staticmethod
    def _model_identity(model: dict[str, Any]) -> dict[str, Any]:
        return {
            key: model[key]
            for key in ("name", "digest", "parameter_count", "parameter_size")
        }

    @staticmethod
    def _report_phase(
        phase: str,
        phase_callback: Callable[[str], None] | None,
    ) -> None:
        if phase not in PRODUCT_PLANNING_PHASES:
            raise ProductPlanningError("product_plan_phase_invalid")
        if phase_callback is not None:
            phase_callback(phase)

    def _enter_phase(
        self,
        workspace: dict[str, Any],
        phase: str,
        phase_callback: Callable[[str], None] | None,
    ) -> None:
        if phase not in PRODUCT_PLANNING_PHASES:
            raise ProductPlanningError("product_plan_phase_invalid")
        workspace["phase"] = phase
        workspace["updated_at"] = _now()
        with self._lock:
            self._save_workspace(workspace)
        self._report_phase(phase, phase_callback)

    def _planning_error(
        self,
        workspace: dict[str, Any],
        exc: ProductPlanningError,
    ) -> dict[str, Any]:
        workspace["status"] = (
            "interrupted" if exc.code == "product_plan_cancelled" else "failed"
        )
        workspace["failure_code"] = exc.code
        workspace["updated_at"] = _now()
        with self._lock:
            self._save_workspace(workspace)
        return _error(exc.code, self._workspace_projection(workspace))

    @staticmethod
    def _planning_answers(workspace: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(submission)
            for submission in workspace["answers"]
            if submission["purpose"] == "initial"
        ]

    @staticmethod
    def _workspace_rules_version(workspace: dict[str, Any]) -> str:
        if workspace["schema_version"] == LEGACY_WORKSPACE_SCHEMA_VERSION:
            return SECTION_PLANNING_RULES_VERSION
        if (
            workspace["schema_version"]
            == DIRECT_BLUEPRINT_WORKSPACE_SCHEMA_VERSION
        ):
            blueprint = workspace.get("blueprint")
            if (
                type(blueprint) is dict
                and blueprint.get("schema_version")
                == "product_plan_blueprint.v1"
            ):
                return LEGACY_BLUEPRINT_PLANNING_RULES_VERSION
            return DIRECT_BLUEPRINT_PLANNING_RULES_VERSION
        if workspace["schema_version"] in {
            LEGACY_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION,
            PREVIOUS_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION,
        }:
            return PREVIOUS_LOCKED_BLUEPRINT_PLANNING_RULES_VERSION
        if (
            workspace["schema_version"]
            == PREVIOUS_GAP_WORKSPACE_SCHEMA_VERSION
        ):
            return PREVIOUS_GAP_PLANNING_RULES_VERSION
        if (
            workspace["schema_version"]
            == PREVIOUS_TARGET_SELECTION_WORKSPACE_SCHEMA_VERSION
        ):
            return PREVIOUS_TARGET_SELECTION_PLANNING_RULES_VERSION
        if (
            workspace["schema_version"]
            == PREVIOUS_REQUIREMENT_COVERAGE_WORKSPACE_SCHEMA_VERSION
        ):
            return PREVIOUS_REQUIREMENT_COVERAGE_PLANNING_RULES_VERSION
        blueprint = workspace.get("blueprint")
        if (
            type(blueprint) is dict
            and blueprint.get("schema_version") == "product_plan_blueprint.v1"
        ):
            return LEGACY_BLUEPRINT_PLANNING_RULES_VERSION
        return PLANNING_RULES_VERSION

    @staticmethod
    def _workspace_prompt_version(workspace: dict[str, Any]) -> str:
        if workspace["schema_version"] == LEGACY_WORKSPACE_SCHEMA_VERSION:
            return LEGACY_PLANNING_PROMPT_VERSION
        if (
            workspace["schema_version"]
            == LEGACY_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION
        ):
            return LEGACY_LOCKED_BLUEPRINT_PROMPT_VERSION
        if (
            workspace["schema_version"]
            == PREVIOUS_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION
        ):
            return PREVIOUS_LOCKED_BLUEPRINT_PROMPT_VERSION
        if workspace["schema_version"] in {
            PREVIOUS_GAP_WORKSPACE_SCHEMA_VERSION,
            PREVIOUS_TARGET_SELECTION_WORKSPACE_SCHEMA_VERSION,
        }:
            return PREVIOUS_GAP_PLANNING_PROMPT_VERSION
        if (
            workspace["schema_version"]
            == PREVIOUS_REQUIREMENT_COVERAGE_WORKSPACE_SCHEMA_VERSION
        ):
            return PREVIOUS_REQUIREMENT_COVERAGE_PROMPT_VERSION
        if (
            workspace["schema_version"]
            == DIRECT_BLUEPRINT_WORKSPACE_SCHEMA_VERSION
        ):
            blueprint = workspace.get("blueprint")
            if (
                type(blueprint) is dict
                and blueprint.get("schema_version")
                == "product_plan_blueprint.v1"
            ):
                return LEGACY_BLUEPRINT_PROMPT_VERSION
            return DIRECT_BLUEPRINT_PROMPT_VERSION
        blueprint = workspace.get("blueprint")
        if (
            type(blueprint) is dict
            and blueprint.get("schema_version") == "product_plan_blueprint.v1"
        ):
            return LEGACY_BLUEPRINT_PROMPT_VERSION
        return PLANNING_PROMPT_VERSION

    def _continue_initial_planning(
        self,
        workspace: dict[str, Any],
        catalog: dict[str, Any],
        cancel_check: Callable[[], bool] | None,
        phase_callback: Callable[[str], None] | None,
    ) -> dict[str, Any]:
        if workspace["schema_version"] in EXPERIENCE_WORKSPACE_SCHEMA_VERSIONS:
            self._freeze_product_experience_query(workspace)
        workspace["status"] = "planning"
        workspace["failure_code"] = None
        outline = workspace.get("outline")
        if outline is None:
            outline_input_digest = self._outline_input_digest(
                workspace,
                self._workspace_rules_version(workspace),
                self._workspace_prompt_version(workspace),
            )
            self._enter_phase(workspace, "requirements_outline", phase_callback)
            outline, calls = self._outline(
                str(workspace["goal"]),
                self._planning_answers(workspace),
                workspace["model"],
                cancel_check,
            )
            workspace["model_calls"].extend(calls)
            workspace["display_name"] = outline["product_name"]
            workspace["outline"] = outline
            workspace["outline_input_digest"] = outline_input_digest
            workspace["outline_response_digest"] = calls[0][
                "structured_response_digest"
            ]
            workspace["updated_at"] = _now()
            with self._lock:
                self._save_workspace(workspace)
        elif workspace["outline_input_digest"] != self._outline_input_digest(
            workspace,
            self._workspace_rules_version(workspace),
            self._workspace_prompt_version(workspace),
        ):
            raise ProductPlanningError("product_plan_resume_input_changed")
        self._cancelled(cancel_check)
        if outline["needs_clarification"]:
            question_set = self._question_set(outline["questions"], purpose="initial")
            if question_set["digest"] in workspace["question_history"]:
                raise ProductPlanningError("product_plan_question_repeated")
            workspace["question_history"].append(question_set["digest"])
            workspace["current_question_set"] = question_set
            workspace["status"] = "needs_clarification"
            workspace["updated_at"] = _now()
            with self._lock:
                self._save_workspace(workspace)
            return _ok(self._workspace_projection(workspace))
        workspace["current_question_set"] = None
        plan, match_calls = self._build_plan(
            workspace,
            outline,
            catalog,
            cancel_check,
            phase_callback,
        )
        workspace["model_calls"].extend(match_calls)
        if plan is None:
            if (
                workspace["status"] != "needs_clarification"
                or workspace["current_question_set"] is None
            ):
                raise ProductPlanningError(
                    "product_plan_capability_gap_target_ambiguous"
                )
            return _ok(self._workspace_projection(workspace))
        workspace["plan"] = plan
        workspace["status"] = "plan_review"
        workspace["failure_code"] = None
        workspace["updated_at"] = _now()
        with self._lock:
            self._prepare_capability_gap_projection(
                workspace,
                catalog,
            )
            self._save_workspace(workspace)
        return _ok(self._workspace_projection(workspace, catalog))

    def _outline(
        self,
        goal: str,
        answers: list[dict[str, Any]],
        model: dict[str, Any],
        cancel_check: Callable[[], bool] | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        self._cancelled(cancel_check)
        example = {
            "schema_version": "product_plan_outline.v1",
            "product_name": "Short product name",
            "language": "zh",
            "requirements": [
                {
                    "ref": "requirement_1",
                    "statement": "One traceable user requirement",
                    "source": "goal",
                }
            ],
            "needs_clarification": False,
            "questions": [],
        }
        result, evidence = self._generate_json(
            model,
            "requirements_outline",
            {
                "goal": goal,
                "prior_answers": answers,
                "rules": {
                    "requirements": "1 to 64; preserve every material need",
                    "requirement_source": (
                        "Use planning_answer only when the requirement comes from a prior "
                        "clarification answer; otherwise use goal."
                    ),
                    "questions": (
                        "Only when architecture ambiguity blocks planning. Return 1 to 3; "
                        "each has 2 to 3 mutually exclusive options; recommended option first "
                        "but never selected."
                    ),
                    "clarification_status": (
                        "Set needs_clarification true exactly when questions is non-empty; "
                        "set it false exactly when questions is empty."
                    ),
                    "unsupported_option": "Set forms_gap true.",
                },
                "schema_example": example,
            },
            cancel_check,
        )
        required = {
            "schema_version",
            "product_name",
            "language",
            "requirements",
            "needs_clarification",
            "questions",
        }
        value = _exact_dict(result, required, "outline.shape_invalid")
        if value["schema_version"] != "product_plan_outline.v1":
            raise ProductPlanningError(
                "product_plan_response_invalid", "outline.schema_version_invalid"
            )
        if value["language"] not in {"zh", "en"}:
            raise ProductPlanningError(
                "product_plan_response_invalid", "outline.language_invalid"
            )
        if type(value["needs_clarification"]) is not bool:
            raise ProductPlanningError(
                "product_plan_response_invalid", "outline.questions_status_type_invalid"
            )
        product_name = _safe_text(
            value["product_name"],
            maximum=120,
            rule_code="outline.product_name_invalid",
        )
        if type(value["requirements"]) is not list or not 1 <= len(value["requirements"]) <= 64:
            raise ProductPlanningError(
                "product_plan_response_invalid", "outline.requirements_count_invalid"
            )
        requirements: list[dict[str, str]] = []
        refs: set[str] = set()
        for raw in value["requirements"]:
            row = _exact_dict(
                raw,
                {"ref", "statement", "source"},
                "outline.requirement_shape_invalid",
            )
            ref = str(row["ref"])
            if _SAFE_REF.fullmatch(ref) is None:
                raise ProductPlanningError(
                    "product_plan_response_invalid", "outline.reference_invalid"
                )
            if ref in refs:
                raise ProductPlanningError(
                    "product_plan_response_invalid", "outline.duplicate_reference"
                )
            if row["source"] not in {"goal", "planning_answer"}:
                raise ProductPlanningError(
                    "product_plan_response_invalid",
                    "outline.requirement_source_invalid",
                )
            if row["source"] == "planning_answer" and not answers:
                raise ProductPlanningError(
                    "product_plan_response_invalid",
                    "outline.invalid_requirement_source",
                )
            refs.add(ref)
            requirements.append(
                {
                    "ref": ref,
                    "statement": _safe_text(
                        row["statement"],
                        maximum=500,
                        rule_code="outline.requirement_text_invalid",
                    ),
                    "source": row["source"],
                }
            )
        questions = self._validate_questions(value["questions"])
        if value["needs_clarification"] != bool(questions):
            raise ProductPlanningError(
                "product_plan_response_invalid", "outline.questions_status_mismatch"
            )
        return (
            {
                "schema_version": "product_plan_outline.v1",
                "product_name": product_name,
                "language": value["language"],
                "requirements": requirements,
                "needs_clarification": value["needs_clarification"],
                "questions": questions,
            },
            [evidence],
        )

    def _validate_questions(self, value: Any) -> list[dict[str, Any]]:
        if type(value) is not list or len(value) > 3:
            raise ProductPlanningError(
                "product_plan_response_invalid", "outline.questions_count_invalid"
            )
        questions: list[dict[str, Any]] = []
        refs: set[str] = set()
        for raw in value:
            row = _exact_dict(
                raw,
                {"ref", "prompt", "options", "allow_custom"},
                "outline.question_shape_invalid",
            )
            ref = str(row["ref"])
            prompt = _safe_text(
                row["prompt"],
                maximum=500,
                rule_code="outline.question_text_invalid",
            )
            if _SAFE_REF.fullmatch(ref) is None:
                raise ProductPlanningError(
                    "product_plan_response_invalid", "outline.reference_invalid"
                )
            if ref in refs:
                raise ProductPlanningError(
                    "product_plan_response_invalid", "outline.duplicate_reference"
                )
            if row["allow_custom"] is not True:
                raise ProductPlanningError(
                    "product_plan_response_invalid", "outline.allow_custom_invalid"
                )
            if _SENSITIVE_QUESTION.search(prompt):
                raise ProductPlanningError(
                    "product_plan_response_invalid", "outline.sensitive_question"
                )
            if type(row["options"]) is not list or not 2 <= len(row["options"]) <= 3:
                raise ProductPlanningError(
                    "product_plan_response_invalid", "outline.options_count_invalid"
                )
            refs.add(ref)
            options: list[dict[str, Any]] = []
            option_refs: set[str] = set()
            for index, raw_option in enumerate(row["options"]):
                option = _exact_dict(
                    raw_option,
                    {"ref", "label", "impact", "recommended", "forms_gap"},
                    "outline.option_shape_invalid",
                )
                option_ref = str(option["ref"])
                if _SAFE_REF.fullmatch(option_ref) is None:
                    raise ProductPlanningError(
                        "product_plan_response_invalid", "outline.reference_invalid"
                    )
                if option_ref in option_refs:
                    raise ProductPlanningError(
                        "product_plan_response_invalid", "outline.duplicate_reference"
                    )
                if type(option["recommended"]) is not bool or type(
                    option["forms_gap"]
                ) is not bool:
                    raise ProductPlanningError(
                        "product_plan_response_invalid", "outline.option_flags_invalid"
                    )
                if option["recommended"] is (index != 0):
                    raise ProductPlanningError(
                        "product_plan_response_invalid",
                        "outline.recommended_option_order_invalid",
                    )
                option_refs.add(option_ref)
                options.append(
                    {
                        "ref": option_ref,
                        "label": _safe_text(
                            option["label"],
                            maximum=160,
                            rule_code="outline.option_text_invalid",
                        ),
                        "impact": _safe_text(
                            option["impact"],
                            maximum=300,
                            rule_code="outline.option_text_invalid",
                        ),
                        "recommended": option["recommended"],
                        "forms_gap": option["forms_gap"],
                    }
                )
            questions.append(
                {
                    "ref": ref,
                    "prompt": prompt,
                    "options": options,
                    "allow_custom": True,
                }
            )
        return questions

    def _question_set(
        self,
        questions: list[dict[str, Any]],
        *,
        purpose: str,
        target_section_id: str | None = None,
    ) -> dict[str, Any]:
        if (
            purpose not in {"initial", "revision"}
            or not 1 <= len(questions) <= 3
            or (purpose == "initial" and target_section_id is not None)
            or (
                purpose == "revision"
                and target_section_id not in SECTION_IDS
            )
        ):
            raise ProductPlanningError("product_plan_response_invalid")
        public: list[dict[str, Any]] = []
        for question in questions:
            question_id = "question_" + _digest(
                {"purpose": purpose, "ref": question["ref"], "prompt": question["prompt"]}
            )[:20]
            public.append(
                {
                    "question_id": question_id,
                    "prompt": question["prompt"],
                    "options": [
                        {
                            "option_id": "option_"
                            + _digest(
                                {
                                    "question_id": question_id,
                                    "ref": option["ref"],
                                    "label": option["label"],
                                }
                            )[:20],
                            "label": option["label"],
                            "impact": option["impact"],
                            "recommended": option["recommended"],
                            "forms_gap": option["forms_gap"],
                        }
                        for option in question["options"]
                    ],
                    "allow_custom": True,
                }
            )
        result = (
            {
                "schema_version": "product_plan_question_set.v1",
                "purpose": purpose,
                "questions": public,
            }
            if purpose == "initial"
            else {
                "schema_version": "product_plan_question_set.v2",
                "purpose": purpose,
                "target_section_id": target_section_id,
                "questions": public,
            }
        )
        result["digest"] = _digest(result)
        return result

    @classmethod
    def _capability_gap_target_question_set(
        cls,
        candidates: list[dict[str, Any]],
        catalog: dict[str, Any],
    ) -> dict[str, Any]:
        if not 2 <= len(candidates) <= 3:
            raise ProductPlanningError(
                "product_plan_capability_gap_target_ambiguous"
            )
        catalog_digest = _digest(catalog)
        options = []
        for candidate in sorted(
            candidates,
            key=lambda item: _digest(item),
        ):
            candidate_digest = _digest(candidate)
            input_names = "、".join(
                item["name"]
                for item in cls._safe_gap_contract_fields(
                    candidate["input_contract"]
                )
            )
            output_names = "、".join(
                item["name"]
                for item in cls._safe_gap_contract_fields(
                    candidate["output_contract"]
                )
            )
            options.append(
                {
                    "option_id": "option_"
                    + _digest(
                        {
                            "catalog_digest": catalog_digest,
                            "candidate_digest": candidate_digest,
                        }
                    )[:20],
                    "label": candidate["capability_group_display_name"],
                    "impact": (
                        f"输入：{input_names}；输出：{output_names}；"
                        "缺少一个计算能力。"
                    ),
                    "recommended": False,
                    "forms_gap": True,
                }
            )
        question = {
            "question_id": "question_"
            + _digest(
                {
                    "purpose": "capability_gap_target",
                    "catalog_digest": catalog_digest,
                    "option_ids": [
                        option["option_id"] for option in options
                    ],
                }
            )[:20],
            "prompt": "当前正式能力中有多个可补齐的计算缺口，请选择本次要完成的业务能力。",
            "options": options,
            "allow_custom": False,
        }
        body = {
            "schema_version": "product_plan_question_set.v3",
            "purpose": "capability_gap_target",
            "warehouse_revision": catalog["warehouse_revision"],
            "catalog_digest": catalog_digest,
            "questions": [question],
        }
        return {**body, "digest": _digest(body)}

    def _answers(
        self,
        question_set: dict[str, Any],
        value: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if type(value) is not list or len(value) != len(question_set["questions"]):
            raise ProductPlanningError("product_plan_answers_invalid")
        by_id = {item["question_id"]: item for item in question_set["questions"]}
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for raw in value:
            row = _exact_dict(raw, {"question_id", "source", "value"})
            question_id = str(row["question_id"])
            question = by_id.get(question_id)
            if (
                question is None
                or question_id in seen
                or row["source"] not in {"option", "custom"}
                or (
                    row["source"] == "custom"
                    and question["allow_custom"] is not True
                )
            ):
                raise ProductPlanningError("product_plan_answers_invalid")
            seen.add(question_id)
            answer_value = _safe_text(row["value"], maximum=500)
            option = None
            if row["source"] == "option":
                option = next(
                    (
                        item
                        for item in question["options"]
                        if item["option_id"] == answer_value
                    ),
                    None,
                )
                if option is None:
                    raise ProductPlanningError("product_plan_answers_invalid")
            result.append(
                {
                    "question_id": question_id,
                    "source": row["source"],
                    "value": answer_value,
                    "forms_gap": bool(option and option["forms_gap"]),
                    "value_digest": _digest(answer_value),
                }
            )
        return sorted(result, key=lambda item: item["question_id"])

    @staticmethod
    def _validate_capability_gap_target_selection(
        value: Any,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        row = _stored_exact(
            value,
            {
                "schema_version",
                "question_set_digest",
                "option_id",
                "candidate_digest",
                "warehouse_revision",
                "catalog_digest",
                "user_answer_digest",
                "canonical_digest",
            },
        )
        body = {
            key: item
            for key, item in row.items()
            if key != "canonical_digest"
        }
        if (
            row["schema_version"]
            != CAPABILITY_GAP_TARGET_SELECTION_VERSION
            or _DIGEST.fullmatch(str(row["question_set_digest"])) is None
            or not str(row["option_id"]).startswith("option_")
            or _DIGEST.fullmatch(str(row["candidate_digest"])) is None
            or type(row["warehouse_revision"]) is not int
            or row["warehouse_revision"] < 0
            or _DIGEST.fullmatch(str(row["catalog_digest"])) is None
            or _DIGEST.fullmatch(str(row["user_answer_digest"])) is None
            or row["canonical_digest"] != _digest(body)
        ):
            raise ProductPlanningError("product_workspace_corrupt")
        return copy.deepcopy(row)

    @classmethod
    def _capability_gap_target_selection(
        cls,
        question_set: dict[str, Any],
        answers: list[dict[str, Any]],
        catalog: dict[str, Any],
    ) -> dict[str, Any]:
        current = cls._capability_gap_target_question_set(
            cls._capability_gap_candidates(catalog),
            catalog,
        )
        if current != question_set:
            raise ProductPlanningError(
                "product_plan_capability_gap_target_stale"
            )
        if (
            len(answers) != 1
            or answers[0]["source"] != "option"
        ):
            raise ProductPlanningError("product_plan_answers_invalid")
        option_id = answers[0]["value"]
        candidates = sorted(
            cls._capability_gap_candidates(catalog),
            key=lambda item: _digest(item),
        )
        option_ids = [
            option["option_id"]
            for option in current["questions"][0]["options"]
        ]
        try:
            candidate = candidates[option_ids.index(option_id)]
        except (ValueError, IndexError) as exc:
            raise ProductPlanningError(
                "product_plan_answers_invalid"
            ) from exc
        body = {
            "schema_version": CAPABILITY_GAP_TARGET_SELECTION_VERSION,
            "question_set_digest": question_set["digest"],
            "option_id": option_id,
            "candidate_digest": _digest(candidate),
            "warehouse_revision": catalog["warehouse_revision"],
            "catalog_digest": _digest(catalog),
            "user_answer_digest": _digest(answers),
        }
        return {**body, "canonical_digest": _digest(body)}

    @classmethod
    def _selected_capability_gap_candidate(
        cls,
        selection: dict[str, Any],
        catalog: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            selection["warehouse_revision"]
            != catalog["warehouse_revision"]
            or selection["catalog_digest"] != _digest(catalog)
        ):
            raise ProductPlanningError(
                "product_plan_capability_gap_target_stale"
            )
        matches = [
            candidate
            for candidate in cls._capability_gap_candidates(catalog)
            if _digest(candidate) == selection["candidate_digest"]
        ]
        if len(matches) != 1:
            raise ProductPlanningError(
                "product_plan_capability_gap_target_stale"
            )
        expected_option_id = "option_" + _digest(
            {
                "catalog_digest": selection["catalog_digest"],
                "candidate_digest": selection["candidate_digest"],
            }
        )[:20]
        if selection["option_id"] != expected_option_id:
            raise ProductPlanningError(
                "product_plan_capability_gap_target_stale"
            )
        return matches[0]

    @staticmethod
    def _compile_wave_dependencies(
        sections: list[dict[str, Any]],
        delivery_waves: dict[str, int],
    ) -> None:
        items = [
            item
            for section in sections
            for item in section["work_items"]
        ]
        item_ids = [item["work_item_id"] for item in items]
        if len(set(item_ids)) != len(item_ids) or set(delivery_waves) != set(item_ids):
            raise ProductPlanningError("product_plan_dependency_invalid")
        by_wave: dict[int, list[str]] = {wave: [] for wave in range(1, 5)}
        by_id = {item["work_item_id"]: item for item in items}
        for work_item_id in item_ids:
            wave = delivery_waves[work_item_id]
            if type(wave) is not int or wave not in by_wave:
                raise ProductPlanningError("product_plan_delivery_wave_invalid")
            by_wave[wave].append(work_item_id)
        for wave in range(1, 5):
            prior_wave = next(
                (
                    candidate
                    for candidate in range(wave - 1, 0, -1)
                    if by_wave[candidate]
                ),
                None,
            )
            dependencies = list(by_wave[prior_wave]) if prior_wave is not None else []
            for work_item_id in by_wave[wave]:
                by_id[work_item_id]["depends_on"] = dependencies

    @classmethod
    def _validate_dependency_compilation(
        cls,
        plan: dict[str, Any],
        delivery_waves: dict[str, int],
    ) -> None:
        item_ids = {
            item["work_item_id"]
            for section in plan["sections"]
            for item in section["work_items"]
        }
        if (
            set(delivery_waves) != item_ids
            or any(
                type(wave) is not int or wave not in {1, 2, 3, 4}
                for wave in delivery_waves.values()
            )
        ):
            raise ProductPlanningError("product_plan_dependency_invalid")
        if plan["schema_version"] == PLAN_SCHEMA_VERSION:
            by_id = {
                item["work_item_id"]: item
                for section in plan["sections"]
                for item in section["work_items"]
            }
            unresolved = set(by_id)
            expected_waves: dict[str, int] = {}
            while unresolved:
                ready = sorted(
                    work_item_id
                    for work_item_id in unresolved
                    if set(by_id[work_item_id]["depends_on"]) <= set(expected_waves)
                )
                if not ready:
                    raise ProductPlanningError("product_plan_dependency_invalid")
                for work_item_id in ready:
                    dependencies = by_id[work_item_id]["depends_on"]
                    expected_waves[work_item_id] = (
                        1
                        if not dependencies
                        else 1
                        + max(expected_waves[dependency] for dependency in dependencies)
                    )
                    unresolved.remove(work_item_id)
            if expected_waves != delivery_waves:
                raise ProductPlanningError("product_plan_dependency_invalid")
            return
        bound_computations = {
            (binding["capsule_id"], binding["version_id"])
            for section in plan["sections"]
            for item in section["work_items"]
            for binding in item["capsule_bindings"]
            if binding["capability_kind"] == "computation"
        }
        if (
            plan["planning_rules_version"] == LEGACY_PLANNING_RULES_VERSION
            or len(bound_computations) != 2
        ):
            compiled_sections = copy.deepcopy(plan["sections"])
            cls._compile_wave_dependencies(compiled_sections, delivery_waves)
            if compiled_sections != plan["sections"]:
                raise ProductPlanningError("product_plan_dependency_invalid")

    @staticmethod
    def _compile_multi_computation_dependencies(
        sections: list[dict[str, Any]],
        candidate_map: dict[str, dict[str, Any]],
    ) -> None:
        exact_catalog = {
            (item["capsule_id"], item["version_id"]): item
            for item in candidate_map.values()
        }
        occurrences: dict[tuple[str, str], list[dict[str, Any]]] = {}
        selected_groups: set[str] = set()
        for section in sections:
            for work_item in section["work_items"]:
                for binding in work_item["capsule_bindings"]:
                    pair = (binding["capsule_id"], binding["version_id"])
                    capsule = exact_catalog.get(pair)
                    if capsule is None:
                        raise ProductPlanningError(
                            "product_plan_catalog_validation_failed"
                        )
                    selected_groups.add(capsule["capability_key"])
                    occurrences.setdefault(pair, []).append(work_item)
        if not occurrences:
            return

        catalog_groups: dict[str, list[dict[str, Any]]] = {}
        for capsule in candidate_map.values():
            catalog_groups.setdefault(capsule["capability_key"], []).append(capsule)
        multi_groups = {
            capability_key
            for capability_key in selected_groups
            if sum(
                capsule["capability_kind"] == "computation"
                for capsule in catalog_groups[capability_key]
            )
            == 2
        }
        if not multi_groups:
            return
        if len(selected_groups) != 1 or len(multi_groups) != 1:
            raise ProductPlanningError(
                "product_plan_multi_computation_shape_invalid"
            )

        capability_key = next(iter(multi_groups))
        group = catalog_groups[capability_key]
        presentations = [
            capsule
            for capsule in group
            if capsule["capability_kind"] == "presentation"
        ]
        interactions = [
            capsule
            for capsule in group
            if capsule["capability_kind"] == "interaction"
        ]
        computations = [
            capsule
            for capsule in group
            if capsule["capability_kind"] == "computation"
        ]
        if (
            len(group) not in {3, 4}
            or len(presentations) != 1
            or len(interactions) > 1
            or len(computations) != 2
        ):
            raise ProductPlanningError(
                "product_plan_multi_computation_shape_invalid"
            )
        if any(
            not {"input_contract", "output_contract", "error_contract"}
            <= set(capsule)
            for capsule in group
        ):
            raise ProductPlanningError("product_plan_contract_facts_missing")

        expected_pairs = {
            (capsule["capsule_id"], capsule["version_id"])
            for capsule in group
        }
        if set(occurrences) != expected_pairs:
            raise ProductPlanningError("product_plan_role_coverage_invalid")
        if any(len(items) != 1 for items in occurrences.values()):
            raise ProductPlanningError("product_plan_binding_ambiguous")

        compatible_orders = [
            (first, terminal)
            for first, terminal in (
                (computations[0], computations[1]),
                (computations[1], computations[0]),
            )
            if contracts_compatible(
                first["output_contract"], terminal["input_contract"]
            )
        ]
        if len(compatible_orders) != 1:
            raise ProductPlanningError(
                "product_plan_connection_order_ambiguous"
            )
        first, terminal = compatible_orders[0]
        presentation = presentations[0]
        if not contracts_compatible(
            terminal["output_contract"], presentation["input_contract"]
        ):
            raise ProductPlanningError(
                "product_plan_connection_target_ambiguous"
            )

        chain: list[dict[str, Any]] = []
        if interactions:
            interaction = interactions[0]
            events = interaction["output_contract"].get("events")
            matches = (
                [
                    name
                    for name, contract in events.items()
                    if contracts_compatible(contract, first["input_contract"])
                ]
                if type(events) is dict
                else []
            )
            if len(matches) != 1:
                raise ProductPlanningError(
                    "product_plan_connection_source_ambiguous"
                )
            chain.append(
                occurrences[
                    (interaction["capsule_id"], interaction["version_id"])
                ][0]
            )

        chain.extend(
            [
                occurrences[(first["capsule_id"], first["version_id"])][0],
                occurrences[(terminal["capsule_id"], terminal["version_id"])][0],
            ]
        )
        chain.append(
            occurrences[
                (presentation["capsule_id"], presentation["version_id"])
            ][0]
        )

        previous: str | None = None
        for work_item in chain:
            work_item["depends_on"] = [] if previous is None else [previous]
            previous = work_item["work_item_id"]

    def _compile_section_drafts(
        self,
        plan_id: str,
        sections_raw: list[dict[str, Any]],
        requirement_map: dict[str, str],
        candidate_map: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        sections: list[dict[str, Any]] = []
        delivery_waves: dict[str, int] = {}
        for section in sections_raw:
            section_id = section["section_id"]
            work_items: list[dict[str, Any]] = []
            gaps: list[dict[str, Any]] = []
            for index, item in enumerate(section["work_items"]):
                try:
                    requirement_ids = [
                        requirement_map[ref] for ref in item["requirement_refs"]
                    ]
                except KeyError as exc:
                    raise ProductPlanningError(
                        "product_plan_requirement_uncovered"
                    ) from exc
                work_item_id = "work_item_" + _digest(
                    {
                        "plan_id": plan_id,
                        "section_id": section_id,
                        "index": index,
                        "title": item["title"],
                        "summary": item["summary"],
                        "requirement_ids": requirement_ids,
                    }
                )[:20]
                candidate_ref = item["candidate_ref"]
                capsule = candidate_map.get(candidate_ref) if candidate_ref else None
                if candidate_ref and capsule is None:
                    raise ProductPlanningError("product_plan_candidate_unknown")
                bindings = (
                    [
                        {
                            "capsule_id": capsule["capsule_id"],
                            "version_id": capsule["version_id"],
                            "display_name": capsule["display_name"],
                            "capability_kind": capsule["capability_kind"],
                            "canonical_hash": capsule["canonical_hash"],
                            "identity_status": "formal_exact_version",
                            "selection_status": "model_suggested",
                            "review_status": "pending",
                            "reason": item["summary"],
                        }
                    ]
                    if capsule is not None
                    else []
                )
                gap_reason = None if bindings else item["gap_reason"]
                work_items.append(
                    {
                        "work_item_id": work_item_id,
                        "title": item["title"],
                        "description": item["summary"],
                        "requirement_ids": requirement_ids,
                        "depends_on": [],
                        "acceptance_intent": item["acceptance_intent"],
                        "capsule_bindings": bindings,
                        "gap_reason": gap_reason,
                    }
                )
                delivery_waves[work_item_id] = item["delivery_wave"]
                if gap_reason is not None:
                    gaps.append(
                        {
                            "gap_id": "gap_"
                            + _digest(
                                {
                                    "plan_id": plan_id,
                                    "work_item_id": work_item_id,
                                }
                            )[:20],
                            "title": item["title"],
                            "reason": gap_reason,
                            "requirement_ids": requirement_ids,
                        }
                    )
            sections.append(
                {
                    "section_id": section_id,
                    "summary": section["summary"],
                    "work_items": work_items,
                    "gaps": gaps,
                }
            )
        self._compile_wave_dependencies(sections, delivery_waves)
        self._compile_multi_computation_dependencies(
            sections,
            candidate_map,
        )
        return sections, delivery_waves

    def _build_plan(
        self,
        workspace: dict[str, Any],
        outline: dict[str, Any],
        catalog: dict[str, Any],
        cancel_check: Callable[[], bool] | None,
        phase_callback: Callable[[str], None] | None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        if workspace["schema_version"] == LEGACY_WORKSPACE_SCHEMA_VERSION:
            return self._build_legacy_plan(
                workspace,
                outline,
                catalog,
                cancel_check,
                phase_callback,
            )
        return self._build_blueprint_plan(
            workspace,
            outline,
            catalog,
            cancel_check,
            phase_callback,
        )

    def _build_legacy_plan(
        self,
        workspace: dict[str, Any],
        outline: dict[str, Any],
        catalog: dict[str, Any],
        cancel_check: Callable[[], bool] | None,
        phase_callback: Callable[[str], None] | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        model = workspace["model"]
        planning_answers = self._planning_answers(workspace)
        plan_id = "plan_" + _digest(
            {
                "workspace_id": workspace["workspace_id"],
                "goal_digest": workspace["goal_digest"],
                "outline_response_digest": workspace["outline_response_digest"],
            }
        )[:32]
        requirement_map: dict[str, str] = {}
        requirements: list[dict[str, Any]] = []
        for index, raw in enumerate(outline["requirements"], start=1):
            requirement_id = "requirement_" + _digest(
                {
                    "plan_id": plan_id,
                    "index": index,
                    "statement": raw["statement"],
                }
            )[:20]
            requirement_map[raw["ref"]] = requirement_id
            requirements.append(
                {
                    "requirement_id": requirement_id,
                    "statement": raw["statement"],
                    "source": (
                        "planning_answer"
                        if raw["source"] == "planning_answer"
                        else "product_goal"
                    ),
                    "source_digest": (
                        _digest(planning_answers)
                        if raw["source"] == "planning_answer"
                        else workspace["goal_digest"]
                    ),
                }
            )
        candidate_map: dict[str, dict[str, Any]] = {}
        for index, capsule in enumerate(catalog["capsules"]):
            candidate_ref = "candidate_" + _digest(
                {
                    "workspace_id": workspace["workspace_id"],
                    "warehouse_revision": catalog["warehouse_revision"],
                    "index": index,
                    "capsule_id": capsule["capsule_id"],
                    "version_id": capsule["version_id"],
                    "canonical_hash": capsule["canonical_hash"],
                }
            )[:24]
            candidate_map[candidate_ref] = capsule
        sections_raw: list[dict[str, Any]] = []
        section_call_digests: list[str] = []
        candidate_refs = sorted(candidate_map)
        checkpoints = workspace["section_checkpoints"]
        for index, section_id in enumerate(SECTION_IDS):
            self._cancelled(cancel_check)
            expected_input_digest = self._section_input_digest(
                workspace,
                outline,
                section_id,
                candidate_refs,
            )
            if index < len(checkpoints):
                checkpoint = checkpoints[index]
                if (
                    checkpoint["section_id"] != section_id
                    or checkpoint["input_digest"] != expected_input_digest
                    or checkpoint["candidate_refs"] != candidate_refs
                ):
                    raise ProductPlanningError("product_plan_resume_input_changed")
                raw_section = copy.deepcopy(checkpoint["section"])
                section_call_digests.append(checkpoint["model_call_digest"])
            else:
                self._enter_phase(workspace, section_id, phase_callback)
                raw_section, evidence = self._section_call(
                    model,
                    section_id,
                    outline["requirements"],
                    planning_answers,
                    candidate_map,
                    cancel_check,
                )
                try:
                    self._validate_checkpoint_section(
                        raw_section,
                        section_id,
                        {item["ref"] for item in outline["requirements"]},
                        set(candidate_refs),
                    )
                except ProductPlanningError as exc:
                    raise ProductPlanningError(
                        "product_plan_response_invalid",
                        exc.rule_code or "section.checkpoint_invalid",
                    ) from exc
                checkpoint = {
                    "schema_version": SECTION_CHECKPOINT_SCHEMA_VERSION,
                    "section_id": section_id,
                    "input_digest": expected_input_digest,
                    "section_digest": _digest(raw_section),
                    "model_call_digest": evidence["structured_response_digest"],
                    "candidate_refs": candidate_refs,
                    "section": copy.deepcopy(raw_section),
                    "completed_at": _now(),
                }
                workspace["model_calls"].append(evidence)
                workspace["section_checkpoints"].append(checkpoint)
                workspace["updated_at"] = _now()
                with self._lock:
                    self._save_workspace(workspace)
                section_call_digests.append(checkpoint["model_call_digest"])
            sections_raw.append(raw_section)
        self._cancelled(cancel_check)
        self._enter_phase(workspace, "validation", phase_callback)
        sections, delivery_waves = self._compile_section_drafts(
            plan_id,
            sections_raw,
            requirement_map,
            candidate_map,
        )
        plan: dict[str, Any] = {
            "schema_version": LEGACY_PLAN_SCHEMA_VERSION,
            "plan_id": plan_id,
            "plan_version": 1,
            "parent_plan_digest": None,
            "product_name": outline["product_name"],
            "goal": workspace["goal"],
            "goal_digest": workspace["goal_digest"],
            "language": outline["language"],
            "requirements": requirements,
            "planning_answers": copy.deepcopy(planning_answers),
            "sections": sections,
            "model": copy.deepcopy(workspace["model"]),
            "planning_rules_version": SECTION_PLANNING_RULES_VERSION,
            "prompt_version": LEGACY_PLANNING_PROMPT_VERSION,
            "structured_response_digests": [
                workspace["outline_response_digest"],
                *section_call_digests,
            ],
            "warehouse_revision": catalog["warehouse_revision"],
            "candidate_generated": False,
            "product_generated": False,
        }
        plan["canonical_digest"] = self._plan_digest(plan)
        self._validate_plan(plan)
        if self._stale_bindings(plan, catalog):
            raise ProductPlanningError("product_plan_catalog_validation_failed")
        self._cancelled(cancel_check)
        workspace["delivery_waves"] = delivery_waves
        return plan, []

    @staticmethod
    def _safe_blueprint_candidates(
        candidate_map: dict[str, dict[str, Any]],
    ) -> list[dict[str, str]]:
        return [
            {
                "candidate_ref": candidate_ref,
                "display_name": item["display_name"],
                "capability_key": item["capability_key"],
                "role_key": item["role_key"],
                "variant_key": item["variant_key"],
                "capability_kind": item["capability_kind"],
            }
            for candidate_ref, item in sorted(candidate_map.items())
        ]

    @staticmethod
    def _composition_chain(
        selected: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        roles = [
            (item["capability_kind"], item["role_key"], item["variant_key"])
            for item in selected
        ]
        presentations = [
            item for item in selected if item["capability_kind"] == "presentation"
        ]
        interactions = [
            item for item in selected if item["capability_kind"] == "interaction"
        ]
        computations = [
            item for item in selected if item["capability_kind"] == "computation"
        ]
        if (
            len(roles) != len(set(roles))
            or len(presentations) != 1
            or len(interactions) > 1
            or len(computations) not in {1, 2}
            or len(selected) not in {2, 3, 4}
            or any(
                not {"input_contract", "output_contract", "error_contract"}
                <= set(item)
                for item in selected
            )
        ):
            raise ProductPlanningError("product_plan_capability_shape_invalid")
        if len(computations) == 1:
            computation_order = computations
        else:
            compatible_orders = [
                [first, terminal]
                for first, terminal in (
                    (computations[0], computations[1]),
                    (computations[1], computations[0]),
                )
                if contracts_compatible(
                    first["output_contract"], terminal["input_contract"]
                )
            ]
            if len(compatible_orders) != 1:
                raise ProductPlanningError(
                    "product_plan_connection_order_ambiguous"
                )
            computation_order = compatible_orders[0]
        presentation = presentations[0]
        if not contracts_compatible(
            computation_order[-1]["output_contract"],
            presentation["input_contract"],
        ):
            raise ProductPlanningError("product_plan_connection_target_ambiguous")
        chain: list[dict[str, Any]] = []
        if interactions:
            interaction = interactions[0]
            events = interaction["output_contract"].get("events")
            matches = (
                [
                    name
                    for name, contract in events.items()
                    if contracts_compatible(
                        contract,
                        computation_order[0]["input_contract"],
                    )
                ]
                if type(events) is dict
                else []
            )
            if len(matches) != 1:
                raise ProductPlanningError(
                    "product_plan_connection_source_ambiguous"
                )
            chain.append(interaction)
        return [*chain, *computation_order, presentation]

    @classmethod
    def _composition_offers(
        cls,
        candidate_map: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_key: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for candidate_ref, capsule in candidate_map.items():
            by_key.setdefault(capsule["capability_key"], []).append(
                (candidate_ref, capsule)
            )
        safe_by_ref = {
            item["candidate_ref"]: item
            for item in cls._safe_blueprint_candidates(candidate_map)
        }
        offers: list[dict[str, Any]] = []
        for capability_key, rows in sorted(by_key.items()):
            ref_by_pair = {
                (capsule["capsule_id"], capsule["version_id"]): candidate_ref
                for candidate_ref, capsule in rows
            }
            if len(ref_by_pair) != len(rows):
                continue
            try:
                chain = cls._composition_chain(
                    [capsule for _, capsule in rows]
                )
            except ProductPlanningError:
                continue
            member_refs = [
                ref_by_pair[(capsule["capsule_id"], capsule["version_id"])]
                for capsule in chain
            ]
            offer_ref = "offer_" + _digest(
                {
                    "schema_version": "product_composition_offer.v1",
                    "capability_key": capability_key,
                    "members": member_refs,
                }
            )[:24]
            offers.append(
                {
                    "offer_ref": offer_ref,
                    "capability_key": capability_key,
                    "members": [
                        safe_by_ref[candidate_ref]
                        for candidate_ref in member_refs
                    ],
                }
            )
        return sorted(offers, key=lambda offer: offer["offer_ref"])

    def _validate_capability_replan_binding(
        self,
        value: Any,
        projection: dict[str, Any],
        decision: dict[str, Any],
        authorization: dict[str, Any],
    ) -> dict[str, Any]:
        keys = {
            "admission_review_id",
            "admission_digest",
            "publication_review_id",
            "published_capsule",
            "authorization_revision",
            "admission_revision_before",
            "admission_revision_after",
            "publication_revision",
        }
        if type(value) is not dict or set(value) != keys:
            raise ProductPlanningError("capability_replan_unavailable")
        row = value
        published = row["published_capsule"]
        if (
            any(
                type(row[key]) is not str or not row[key]
                for key in ("admission_review_id", "publication_review_id")
            )
            or _DIGEST.fullmatch(str(row["admission_digest"])) is None
            or type(published) is not dict
            or set(published)
            != {
                "capsule_id",
                "version_id",
                "canonical_hash",
                "capability_kind",
                "role_key",
                "variant_key",
            }
            or self._gap_capsule_identity(published) != published
            or published["capability_kind"] != "computation"
            or any(
                type(row[key]) is not int or row[key] < 0
                for key in (
                    "authorization_revision",
                    "admission_revision_before",
                    "admission_revision_after",
                    "publication_revision",
                )
            )
            or row["authorization_revision"]
            != projection["warehouse_revision"]
            or row["authorization_revision"]
            != authorization["warehouse_revision"]
            or row["admission_revision_before"]
            != row["authorization_revision"]
            or row["admission_revision_after"]
            != row["admission_revision_before"] + 1
            or row["publication_revision"]
            != row["admission_revision_after"] + 1
            or decision["canonical_digest"]
            != authorization["authorize_decision_digest"]
        ):
            raise ProductPlanningError("capability_replan_unavailable")
        return copy.deepcopy(row)

    @classmethod
    def _capability_replan_offer(
        cls,
        catalog: dict[str, Any],
        projection: dict[str, Any],
        published_capsule: dict[str, Any],
        authorized_error_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        expected_members = {
            (
                member["capsule_id"],
                member["version_id"],
                member["canonical_hash"],
            )
            for member in projection["existing_members"]
        }
        expected_members.add(
            (
                published_capsule["capsule_id"],
                published_capsule["version_id"],
                published_capsule["canonical_hash"],
            )
        )
        group = [
            capsule
            for capsule in catalog["capsules"]
            if capsule["capability_key"] == projection["capability_key"]
        ]
        actual_members = {
            (
                capsule["capsule_id"],
                capsule["version_id"],
                capsule["canonical_hash"],
            )
            for capsule in group
        }
        published = [
            capsule
            for capsule in group
            if cls._gap_capsule_identity(capsule)
            == published_capsule
        ]
        if (
            actual_members != expected_members
            or len(group) != len(expected_members)
            or len(published) != 1
            or published[0]["capability_kind"] != "computation"
            or published[0].get("input_contract")
            != projection["input_contract"]
            or published[0].get("output_contract")
            != projection["output_contract"]
            or (
                authorized_error_contract is not None
                and published[0].get("error_contract")
                != authorized_error_contract
            )
        ):
            return None
        try:
            chain = cls._composition_chain(group)
        except ProductPlanningError:
            return None
        computations = [
            item for item in chain if item["capability_kind"] == "computation"
        ]
        published_pair = (
            published_capsule["capsule_id"],
            published_capsule["version_id"],
        )
        published_index = next(
            (
                index
                for index, item in enumerate(computations)
                if (item["capsule_id"], item["version_id"])
                == published_pair
            ),
            -1,
        )
        slot = projection["slot"]
        if (
            (
                slot == "only_computation"
                and (len(computations), published_index) != (1, 0)
            )
            or (
                slot == "before_existing_computation"
                and (len(computations), published_index) != (2, 0)
            )
            or (
                slot == "after_existing_computation"
                and (len(computations), published_index) != (2, 1)
            )
        ):
            return None
        return {
            "schema_version": CAPABILITY_REPLAN_OFFER_VERSION,
            "capability_key": projection["capability_key"],
            "gap_slot": slot,
            "members": [
                cls._gap_capsule_identity(member) for member in chain
            ],
        }

    @classmethod
    def _capability_replan_acceptance_suggestions(
        cls,
        catalog: dict[str, Any],
        projection: dict[str, Any],
        decision: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if (
            projection["slot"] != "only_computation"
            or projection["upstream"]["capability_kind"] != "interaction"
            or projection["downstream"]["capability_kind"] != "presentation"
        ):
            return []
        by_identity = {
            (item["capsule_id"], item["version_id"]): item
            for item in catalog["capsules"]
        }
        upstream = by_identity.get(
            (
                projection["upstream"]["capsule_id"],
                projection["upstream"]["version_id"],
            )
        )
        downstream = by_identity.get(
            (
                projection["downstream"]["capsule_id"],
                projection["downstream"]["version_id"],
            )
        )
        events = (
            upstream.get("output_contract", {}).get("events")
            if type(upstream) is dict
            else None
        )
        if (
            type(events) is not dict
            or events.get(projection["upstream"]["port_name"])
            != projection["input_contract"]
            or type(downstream) is not dict
            or downstream.get("input_contract")
            != projection["output_contract"]
        ):
            return []
        return copy.deepcopy(decision["acceptance_cases"])

    def _source_workspace_from_handoff(
        self,
        handoff: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            source = self._read_json(
                self._workspace_dir(handoff["source_workspace_id"])
                / "workspace.json"
            )
            self._validate_workspace(
                source,
                expected_workspace_id=handoff["source_workspace_id"],
            )
        except ProductPlanningError as exc:
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            ) from exc
        if source["plan_token"] != handoff["source_plan_token"]:
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            )
        return source

    def _successor_workspace_from_handoff(
        self,
        handoff: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            successor = self._read_json(
                self._workspace_dir(handoff["successor_workspace_id"])
                / "workspace.json"
            )
            self._validate_workspace(
                successor,
                expected_workspace_id=handoff["successor_workspace_id"],
            )
        except ProductPlanningError as exc:
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            ) from exc
        if successor["plan_token"] != handoff["successor_plan_token"]:
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            )
        return successor

    def _validate_capability_replan_current(
        self,
        handoff: dict[str, Any],
        catalog: dict[str, Any],
        *,
        check_model: bool = False,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        handoff = self._validate_capability_replan_handoff(handoff)
        try:
            source = self._source_workspace_from_handoff(handoff)
            plan = source.get("plan")
            projection = self._read_capability_gap_projection(source)
            decisions = (
                self._capability_gap_decisions(source, projection)
                if projection is not None
                else []
            )
            decision = decisions[-1] if decisions else None
            authorization = (
                self._read_capability_source_proposal_authorization(
                    source,
                    projection,
                    decision,
                )
                if projection is not None
                and type(decision) is dict
                and decision.get("decision") == "authorize"
                else None
            )
        except ProductPlanningError as exc:
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            ) from exc
        if (
            type(plan) is not dict
            or plan["canonical_digest"] != handoff["source_plan_digest"]
            or projection is None
            or projection["gap_id"] != handoff["source_gap_id"]
            or projection["projection_digest"]
            != handoff["projection_digest"]
        ):
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            )
        if (
            authorization is None
            or decision["canonical_digest"]
            != handoff["authorize_decision_digest"]
            or authorization["authorization_digest"]
            != handoff["source_proposal_authorization_digest"]
        ):
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            )
        try:
            selected = self._model_identity(
                self._selected_model(
                    check_current=check_model,
                    cancel_check=cancel_check,
                )
            )
        except ProductPlanningError as exc:
            raise ProductPlanningError(
                "capability_replan_handoff_stale"
            ) from exc
        normalized_catalog = self._catalog(catalog)
        if (
            selected != handoff["planning_model"]
            or normalized_catalog["warehouse_revision"]
            != handoff["handoff_catalog_revision"]
            or _digest(normalized_catalog) != handoff["catalog_digest"]
        ):
            raise ProductPlanningError(
                "capability_replan_handoff_stale"
            )
        offer = self._capability_replan_offer(
            normalized_catalog,
            projection,
            handoff["published_capsule"],
            authorization["error_contract"],
        )
        if (
            offer is None
            or offer != handoff["target_offer"]
            or _digest(offer) != handoff["target_offer_digest"]
        ):
            raise ProductPlanningError(
                "capability_replan_handoff_stale"
            )
        return {
            "handoff": handoff,
            "source": source,
            "projection": projection,
            "authorization": authorization,
            "catalog": {
                "warehouse_revision": normalized_catalog[
                    "warehouse_revision"
                ],
                "capsules": [
                    capsule
                    for capsule in normalized_catalog["capsules"]
                    if self._gap_capsule_identity(capsule)
                    in offer["members"]
                ],
            },
        }

    @staticmethod
    def _gap_capsule_identity(capsule: dict[str, Any]) -> dict[str, str]:
        return {
            key: str(capsule[key])
            for key in (
                "capsule_id",
                "version_id",
                "canonical_hash",
                "capability_kind",
                "role_key",
                "variant_key",
            )
        }

    @staticmethod
    def _integer_gap_adapter(
        input_contract: dict[str, Any],
        output_contract: dict[str, Any],
    ) -> dict[str, Any] | None:
        input_properties = input_contract.get("properties")
        output_properties = output_contract.get("properties")
        if (
            input_contract.get("type") != "object"
            or output_contract.get("type") != "object"
            or type(input_properties) is not dict
            or type(output_properties) is not dict
            or not input_properties
            or not output_properties
            or set(input_contract.get("required", [])) != set(input_properties)
            or set(output_contract.get("required", [])) != set(output_properties)
            or any(
                contract.get("type") != "integer"
                for contract in (
                    *input_properties.values(),
                    *output_properties.values(),
                )
            )
        ):
            return None
        passthrough = sorted(
            field
            for field, contract in output_properties.items()
            if input_properties.get(field) == contract
        )
        result_fields = sorted(set(output_properties) - set(passthrough))
        if len(result_fields) != 1:
            return None
        result_field = result_fields[0]
        if passthrough:
            adapter_version = "computation_adapter.v3"
            mapping_schema = "computation_capture_mapping.v3"
        elif len(output_properties) == 1:
            adapter_version = "computation_adapter.v2"
            mapping_schema = "computation_capture_mapping.v2"
        else:
            return None
        return {
            "adapter_contract_version": adapter_version,
            "capture_mapping_schema": mapping_schema,
            "result_field": result_field,
            "passthrough_fields": passthrough,
        }

    @staticmethod
    def _finite_enum_values(contract: Any) -> list[str] | None:
        if (
            type(contract) is not dict
            or set(contract)
            != {"type", "min_length", "max_length", "enum"}
            or contract.get("type") != "string"
            or type(contract.get("min_length")) is not int
            or type(contract.get("max_length")) is not int
        ):
            return None
        values = contract.get("enum")
        if (
            type(values) is not list
            or not values
            or len(values) > 32
            or any(type(value) is not str for value in values)
            or len(set(values)) != len(values)
        ):
            return None
        try:
            ordered = sorted(values, key=lambda value: value.encode("utf-8"))
            lengths = [
                len(value.encode("utf-16-le")) // 2 for value in ordered
            ]
        except UnicodeEncodeError:
            return None
        if (
            values != ordered
            or contract["min_length"] != min(lengths)
            or contract["max_length"] != max(lengths)
        ):
            return None
        return ordered

    @staticmethod
    def _utf8_sorted_unique_strings(values: Any) -> bool:
        if (
            type(values) is not list
            or any(type(value) is not str for value in values)
            or len(set(values)) != len(values)
        ):
            return False
        try:
            return values == sorted(
                values,
                key=lambda value: value.encode("utf-8"),
            )
        except UnicodeEncodeError:
            return False

    @classmethod
    def _finite_enum_gap_adapter(
        cls,
        input_contract: dict[str, Any],
        output_contract: dict[str, Any],
    ) -> dict[str, Any] | None:
        input_properties = input_contract.get("properties")
        output_properties = output_contract.get("properties")
        if (
            input_contract.get("type") != "object"
            or output_contract.get("type") != "object"
            or input_contract.get("additional_properties") is not False
            or output_contract.get("additional_properties") is not False
            or type(input_properties) is not dict
            or type(output_properties) is not dict
            or not input_properties
            or len(output_properties) != 1
            or input_contract.get("required") != sorted(input_properties)
            or output_contract.get("required") != sorted(output_properties)
        ):
            return None
        for contract in input_properties.values():
            if (
                set(contract) == {"type", "minimum", "maximum"}
                and contract.get("type") == "integer"
                and type(contract.get("minimum")) is int
                and type(contract.get("maximum")) is int
                and contract["minimum"] <= contract["maximum"]
            ):
                continue
            if contract == {"type": "boolean"}:
                continue
            if cls._finite_enum_values(contract) is not None:
                continue
            return None
        result_field = next(iter(output_properties))
        result_enum = cls._finite_enum_values(output_properties[result_field])
        if result_enum is None:
            return None
        return {
            "adapter_contract_version": "computation_adapter.v4",
            "capture_mapping_schema": "computation_capture_mapping.v4",
            "proof_schema": "source_graph_proof.v2",
            "result_field": result_field,
            "result_enum": result_enum,
            "passthrough_fields": [],
        }

    @classmethod
    def _gap_adapter(
        cls,
        input_contract: dict[str, Any],
        output_contract: dict[str, Any],
    ) -> dict[str, Any] | None:
        return cls._integer_gap_adapter(
            input_contract,
            output_contract,
        ) or cls._finite_enum_gap_adapter(
            input_contract,
            output_contract,
        )

    @classmethod
    def _capability_gap_candidates(
        cls,
        catalog: dict[str, Any],
    ) -> list[dict[str, Any]]:
        by_key: dict[str, list[dict[str, Any]]] = {}
        for capsule in catalog["capsules"]:
            by_key.setdefault(capsule["capability_key"], []).append(capsule)
        candidates: list[dict[str, Any]] = []
        for capability_key, raw_group in sorted(by_key.items()):
            group = sorted(
                raw_group,
                key=lambda item: (
                    item["capability_kind"],
                    item["role_key"],
                    item["variant_key"],
                    item["capsule_id"],
                    item["version_id"],
                ),
            )
            presentations = [
                item
                for item in group
                if item["capability_kind"] == "presentation"
            ]
            interactions = [
                item
                for item in group
                if item["capability_kind"] == "interaction"
            ]
            computations = [
                item
                for item in group
                if item["capability_kind"] == "computation"
            ]
            if (
                len(group) not in {2, 3}
                or len(presentations) != 1
                or len(interactions) != 1
                or len(computations) not in {0, 1}
                or any(
                    not {"input_contract", "output_contract", "error_contract"}
                    <= set(item)
                    for item in group
                )
                or len(
                    {
                        (
                            item["capability_kind"],
                            item["role_key"],
                            item["variant_key"],
                        )
                        for item in group
                    }
                )
                != len(group)
            ):
                continue
            interaction = interactions[0]
            presentation = presentations[0]
            events = interaction["output_contract"].get("events")
            if type(events) is not dict or len(events) != 1:
                continue
            event_name = next(iter(events))
            event_contract = events[event_name]
            positions: list[
                tuple[
                    str,
                    dict[str, Any],
                    dict[str, Any],
                    dict[str, Any],
                    dict[str, Any],
                ]
            ] = []
            if not computations:
                adapter = cls._gap_adapter(
                    event_contract,
                    presentation["input_contract"],
                )
                if adapter is not None:
                    positions.append(
                        (
                            "only_computation",
                            event_contract,
                            presentation["input_contract"],
                            {
                                **cls._gap_capsule_identity(interaction),
                                "port_kind": "event",
                                "port_name": event_name,
                                "contract_digest": _digest(event_contract),
                            },
                            {
                                **cls._gap_capsule_identity(presentation),
                                "port_kind": "input",
                                "port_name": "input",
                                "contract_digest": _digest(
                                    presentation["input_contract"]
                                ),
                            },
                        )
                    )
            else:
                computation = computations[0]
                if (
                    contracts_compatible(
                        event_contract,
                        computation["input_contract"],
                    )
                    and contracts_compatible(
                        computation["output_contract"],
                        presentation["input_contract"],
                    )
                ):
                    continue
                if contracts_compatible(
                    computation["output_contract"],
                    presentation["input_contract"],
                ):
                    adapter = cls._gap_adapter(
                        event_contract,
                        computation["input_contract"],
                    )
                    if adapter is not None:
                        positions.append(
                            (
                                "before_existing_computation",
                                event_contract,
                                computation["input_contract"],
                                {
                                    **cls._gap_capsule_identity(interaction),
                                    "port_kind": "event",
                                    "port_name": event_name,
                                    "contract_digest": _digest(event_contract),
                                },
                                {
                                    **cls._gap_capsule_identity(computation),
                                    "port_kind": "input",
                                    "port_name": "input",
                                    "contract_digest": _digest(
                                        computation["input_contract"]
                                    ),
                                },
                            )
                        )
                if contracts_compatible(
                    event_contract,
                    computation["input_contract"],
                ):
                    adapter = cls._gap_adapter(
                        computation["output_contract"],
                        presentation["input_contract"],
                    )
                    if adapter is not None:
                        positions.append(
                            (
                                "after_existing_computation",
                                computation["output_contract"],
                                presentation["input_contract"],
                                {
                                    **cls._gap_capsule_identity(computation),
                                    "port_kind": "output",
                                    "port_name": "output",
                                    "contract_digest": _digest(
                                        computation["output_contract"]
                                    ),
                                },
                                {
                                    **cls._gap_capsule_identity(presentation),
                                    "port_kind": "input",
                                    "port_name": "input",
                                    "contract_digest": _digest(
                                        presentation["input_contract"]
                                    ),
                                },
                            )
                        )
            if len(positions) != 1:
                continue
            slot, input_contract, output_contract, upstream, downstream = positions[0]
            adapter = cls._gap_adapter(input_contract, output_contract)
            if adapter is None:
                continue
            display_names = {str(item["display_name"]) for item in group}
            if len(display_names) != 1:
                continue
            candidates.append(
                {
                    "capability_key": capability_key,
                    "capability_group_display_name": next(iter(display_names)),
                    "capability_kind": "computation",
                    "slot": slot,
                    "input_contract": copy.deepcopy(input_contract),
                    "output_contract": copy.deepcopy(output_contract),
                    **adapter,
                    "upstream": upstream,
                    "downstream": downstream,
                    "existing_members": [
                        cls._gap_capsule_identity(item) for item in group
                    ],
                }
            )
        return sorted(
            candidates,
            key=lambda item: (
                item["capability_key"],
                item["slot"],
                item["upstream"]["capsule_id"],
                item["downstream"]["capsule_id"],
            ),
        )

    @staticmethod
    def _safe_gap_contract_fields(
        contract: dict[str, Any],
    ) -> list[dict[str, Any]]:
        properties = contract["properties"]
        return [
            {
                key: value
                for key, value in {
                    "name": name,
                    "type": field["type"],
                    "minimum": field.get("minimum"),
                    "maximum": field.get("maximum"),
                    "min_length": field.get("min_length"),
                    "max_length": field.get("max_length"),
                    "enum": copy.deepcopy(field.get("enum")),
                }.items()
                if value is not None
            }
            for name, field in sorted(properties.items())
        ]

    @classmethod
    def _capability_gap_blueprint_lock(
        cls,
        candidate: dict[str, Any],
        candidate_map: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        safe_by_pair = {
            (capsule["capsule_id"], capsule["version_id"]): safe
            for safe in cls._safe_blueprint_candidates(candidate_map)
            for capsule in [candidate_map[safe["candidate_ref"]]]
        }
        existing_members: list[dict[str, str]] = []
        for identity in candidate["existing_members"]:
            safe = safe_by_pair.get(
                (identity["capsule_id"], identity["version_id"])
            )
            if (
                safe is None
                or safe["capability_key"] != candidate["capability_key"]
                or any(
                    safe[key] != identity[key]
                    for key in (
                        "role_key",
                        "variant_key",
                        "capability_kind",
                    )
                )
            ):
                raise ProductPlanningError(
                    "product_plan_capability_gap_lock_invalid"
                )
            existing_members.append(copy.deepcopy(safe))
        existing_members.sort(
            key=lambda item: (
                {"interaction": 0, "computation": 1, "presentation": 2}[
                    item["capability_kind"]
                ],
                item["role_key"],
                item["variant_key"],
                item["candidate_ref"],
            )
        )
        return {
            "schema_version": (
                "product_capability_gap_blueprint_lock.v2"
                if candidate["adapter_contract_version"]
                == "computation_adapter.v4"
                else "product_capability_gap_blueprint_lock.v1"
            ),
            "capability_key": candidate["capability_key"],
            "capability_group_display_name": candidate[
                "capability_group_display_name"
            ],
            "capability_kind": "computation",
            "slot": candidate["slot"],
            "adapter_contract_version": candidate[
                "adapter_contract_version"
            ],
            "input_fields": cls._safe_gap_contract_fields(
                candidate["input_contract"]
            ),
            "output_fields": cls._safe_gap_contract_fields(
                candidate["output_contract"]
            ),
            "existing_members": existing_members,
        }

    @classmethod
    def _capability_gap_projection(
        cls,
        plan: dict[str, Any],
        catalog: dict[str, Any],
        candidate_digest: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        gaps = [
            gap
            for section in plan["sections"]
            for gap in section["gaps"]
        ]
        if len(gaps) != 1:
            return None, "capability_gap_plan_count_unsupported"
        candidates = cls._capability_gap_candidates(catalog)
        if candidate_digest is not None:
            candidates = [
                candidate
                for candidate in candidates
                if _digest(candidate) == candidate_digest
            ]
        if not candidates:
            return None, "capability_gap_boundary_unavailable"
        if len(candidates) != 1:
            return None, "capability_gap_boundary_ambiguous"
        candidate = candidates[0]
        gap = gaps[0]
        body = {
            "schema_version": (
                CAPABILITY_GAP_PROJECTION_V2
                if candidate["adapter_contract_version"]
                == "computation_adapter.v4"
                else CAPABILITY_GAP_PROJECTION_VERSION
            ),
            "plan_id": plan["plan_id"],
            "plan_version": plan["plan_version"],
            "plan_digest": plan["canonical_digest"],
            "gap_id": gap["gap_id"],
            "requirement_ids": sorted(gap["requirement_ids"]),
            **candidate,
            "warehouse_revision": catalog["warehouse_revision"],
            "catalog_digest": _digest(catalog),
            "projection_source": "deterministic_unique_serial_gap",
        }
        if candidate["adapter_contract_version"] == "computation_adapter.v4":
            body["proof_schema"] = candidate["proof_schema"]
            body["result_enum"] = copy.deepcopy(candidate["result_enum"])
        return {**body, "projection_digest": _digest(body)}, "available"

    def _composition_selection_input_digest(
        self,
        workspace: dict[str, Any],
        outline: dict[str, Any],
        composition_offers: list[dict[str, Any]],
    ) -> str:
        body = {
            "schema_version": (
                "product_composition_selection_input.v2"
                if workspace["schema_version"]
                in EXPERIENCE_WORKSPACE_SCHEMA_VERSIONS
                else "product_composition_selection_input.v1"
            ),
            "goal_digest": workspace["goal_digest"],
            "planning_answers": self._planning_answers(workspace),
            "model": workspace["model"],
            "planning_rules_version": self._workspace_rules_version(workspace),
            "prompt_version": self._workspace_prompt_version(workspace),
            "outline": outline,
            "outline_response_digest": workspace["outline_response_digest"],
            "composition_offers": sorted(
                composition_offers,
                key=lambda offer: offer["offer_ref"],
            ),
        }
        if workspace["schema_version"] in EXPERIENCE_WORKSPACE_SCHEMA_VERSIONS:
            body.update(
                {
                    "experience_query_digest": workspace[
                        "experience_query_digest"
                    ],
                    "experience_injection_enabled": workspace[
                        "experience_injection_enabled"
                    ],
                    "experience_cases": self._workspace_experience_cases(
                        workspace
                    ),
                }
            )
        return _digest(body)

    @staticmethod
    def _composition_selection_request(
        goal: str,
        outline: dict[str, Any],
        answers: list[dict[str, Any]],
        composition_offers: list[dict[str, Any]],
        *,
        selection_locked: bool,
        prompt_version: str,
        experience_cases: list[dict[str, Any]],
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "goal": goal,
            "prior_answers": answers,
            "outline": outline,
            "composition_offers": sorted(
                composition_offers,
                key=lambda offer: offer["offer_ref"],
            ),
            "rules": {
                "selection": (
                    "Select the one supplied complete composition."
                    if selection_locked
                    else (
                        "Choose exactly one supplied capability_key whose complete "
                        "composition matches the product semantics, or use an empty "
                        "capability_key when none matches."
                    )
                ),
                "authority": (
                    "Do not select offer members, candidate refs, dependencies, "
                    "delivery waves, contracts, or wiring."
                ),
            },
        }
        if prompt_version == PLANNING_PROMPT_VERSION:
            request["experience_cases"] = copy.deepcopy(experience_cases)
        if selection_locked:
            request["selection_locked"] = True
        return request

    def _composition_selection_call(
        self,
        model: dict[str, Any],
        goal: str,
        outline: dict[str, Any],
        answers: list[dict[str, Any]],
        composition_offers: list[dict[str, Any]],
        cancel_check: Callable[[], bool] | None,
        *,
        selection_locked: bool = False,
        prompt_version: str | None = None,
        experience_cases: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, str], dict[str, Any]]:
        if selection_locked and len(composition_offers) != 1:
            raise ProductPlanningError(
                "product_plan_composition_selection_ambiguous"
            )
        prompt_version = prompt_version or PLANNING_PROMPT_VERSION
        request = self._composition_selection_request(
            goal,
            outline,
            answers,
            composition_offers,
            selection_locked=selection_locked,
            prompt_version=prompt_version,
            experience_cases=experience_cases or [],
        )
        result, evidence = self._generate_json(
            model,
            "composition_selection",
            request,
            cancel_check,
            prompt_version=prompt_version,
        )
        selection = self._validate_composition_selection(result)
        evidence["structured_response_digest"] = _digest(selection)
        return selection, evidence

    def _blueprint_input_digest(
        self,
        workspace: dict[str, Any],
        outline: dict[str, Any],
        candidate_map: dict[str, dict[str, Any]],
        composition_offers: list[dict[str, Any]] | None = None,
    ) -> str:
        if composition_offers is None:
            return _digest(
                {
                    "schema_version": "product_plan_blueprint_input.v1",
                    "goal_digest": workspace["goal_digest"],
                    "planning_answers": self._planning_answers(workspace),
                    "model": workspace["model"],
                    "planning_rules_version": (
                        LEGACY_BLUEPRINT_PLANNING_RULES_VERSION
                    ),
                    "prompt_version": LEGACY_BLUEPRINT_PROMPT_VERSION,
                    "outline": outline,
                    "outline_response_digest": workspace[
                        "outline_response_digest"
                    ],
                    "candidate_catalog": self._safe_blueprint_candidates(
                        candidate_map
                    ),
                }
            )
        return _digest(
            {
                "schema_version": "product_plan_blueprint_input.v2",
                "goal_digest": workspace["goal_digest"],
                "planning_answers": self._planning_answers(workspace),
                "model": workspace["model"],
                "planning_rules_version": (
                    DIRECT_BLUEPRINT_PLANNING_RULES_VERSION
                ),
                "prompt_version": DIRECT_BLUEPRINT_PROMPT_VERSION,
                "outline": outline,
                "outline_response_digest": workspace["outline_response_digest"],
                "composition_offers": sorted(
                    composition_offers,
                    key=lambda offer: offer["offer_ref"],
                ),
            }
        )

    def _selected_blueprint_input_digest(
        self,
        workspace: dict[str, Any],
        outline: dict[str, Any],
        selected_offer: dict[str, Any] | None,
        capability_gap_lock: dict[str, Any] | None = None,
    ) -> str:
        input_schema = "product_plan_blueprint_input.v3"
        if workspace["schema_version"] == PREVIOUS_GAP_WORKSPACE_SCHEMA_VERSION:
            input_schema = "product_plan_blueprint_input.v4"
        elif (
            workspace["schema_version"]
            == PREVIOUS_TARGET_SELECTION_WORKSPACE_SCHEMA_VERSION
        ):
            input_schema = "product_plan_blueprint_input.v5"
        elif (
            workspace["schema_version"]
            == PREVIOUS_REQUIREMENT_COVERAGE_WORKSPACE_SCHEMA_VERSION
        ):
            input_schema = "product_plan_blueprint_input.v6"
        elif workspace["schema_version"] == WORKSPACE_SCHEMA_VERSION:
            input_schema = "product_plan_blueprint_input.v7"
        body = {
            "schema_version": input_schema,
            "goal_digest": workspace["goal_digest"],
            "planning_answers": self._planning_answers(workspace),
            "model": workspace["model"],
            "planning_rules_version": self._workspace_rules_version(workspace),
            "prompt_version": self._workspace_prompt_version(workspace),
            "outline": outline,
            "outline_response_digest": workspace["outline_response_digest"],
            "composition_selection_response_digest": workspace[
                "composition_selection_response_digest"
            ],
            "composition_offers": (
                [] if selected_offer is None else [selected_offer]
            ),
        }
        if workspace["schema_version"] in GAP_WORKSPACE_SCHEMA_VERSIONS:
            body["capability_gap_lock"] = copy.deepcopy(capability_gap_lock)
        if (
            workspace["schema_version"]
            in TARGET_SELECTION_WORKSPACE_SCHEMA_VERSIONS
        ):
            body["capability_gap_target_selection"] = copy.deepcopy(
                workspace["capability_gap_target_selection"]
            )
        return _digest(body)

    def _blueprint_call(
        self,
        model: dict[str, Any],
        goal: str,
        outline: dict[str, Any],
        answers: list[dict[str, Any]],
        candidates: dict[str, dict[str, Any]],
        composition_offers: list[dict[str, Any]],
        cancel_check: Callable[[], bool] | None,
        *,
        selection_locked: bool = False,
        prompt_version: str | None = None,
        capability_gap_lock: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        prompt_version = prompt_version or PLANNING_PROMPT_VERSION
        composition_offers = sorted(
            composition_offers,
            key=lambda offer: offer["offer_ref"],
        )
        requirements = outline["requirements"]
        section_example = {
            section_id: {
                "applicability": "not_applicable",
                "summary": "This section is not required for the product.",
            }
            for section_id in SECTION_IDS
        }
        selected_offer = composition_offers[0] if composition_offers else None
        current_locked_offer_protocol = (
            selection_locked
            and selected_offer is not None
            and prompt_version
            in {
                PREVIOUS_REQUIREMENT_COVERAGE_PROMPT_VERSION,
                PLANNING_PROMPT_VERSION,
            }
        )
        assignments: dict[str, dict[str, Any]] = {}
        gaps: list[dict[str, Any]] = []
        requirement_refs = [item["ref"] for item in requirements]
        if selected_offer is not None:
            section_example["frontend"]["applicability"] = "applicable"
            section_example["frontend"]["summary"] = "User-visible product capability."
            for member in selected_offer["members"]:
                assignments[member["candidate_ref"]] = {
                    "section_id": "frontend",
                    "requirement_refs": requirement_refs,
                    "title": member["display_name"],
                    "summary": "Use this member of the selected formal composition.",
                    "acceptance_intent": "Verify its user-visible behavior.",
                }
        else:
            section_example["frontend"]["applicability"] = "applicable"
            section_example["frontend"]["summary"] = "A required capability is missing."
            gaps.append(
                {
                    "section_id": "frontend",
                    "requirement_refs": requirement_refs,
                    "title": "Missing user-visible capability",
                    "reason": "The current formal catalog has no compatible capability.",
                }
            )
        request: dict[str, Any] = {
            "goal": goal,
            "requirements": requirements,
            "prior_answers": answers,
            "composition_offers": composition_offers,
            "rules": {
                "selection": (
                    (
                        "Describe every member of the selected complete composition; "
                        "never add, remove, replace, or mix members."
                    )
                    if selection_locked and selected_offer is not None
                    else (
                        "Describe the one deterministic locked computation gap; "
                        "never add, split, remove, replace, or reinterpret it."
                    )
                    if capability_gap_lock is not None
                    else (
                        "Create only real gaps; no composition offer was selected."
                    )
                    if selection_locked
                    else (
                        "Select exactly one complete composition offer or the empty offer. "
                        "Describe every member required by that offer; never add, remove, "
                        "or mix members."
                    )
                )
                + " Do not emit identifiers, contracts, dependencies, or waves.",
                "sections": (
                    "Use all four fixed sections. A section with an assignment or gap "
                    "must be applicable; a not_applicable section has neither."
                ),
                "gaps": (
                    "Create a gap only for a required user-visible capability absent "
                    "from the catalog. Absence constraints such as offline, local-only, "
                    "no network, no login, no database, or no deployment are not gaps."
                ),
                "coverage": (
                    "Cover every requirement with an assignment or a real gap. Section "
                    "summaries do not count as requirement coverage. When the locked "
                    "offer covers the requested user-visible behavior, attach each "
                    "product-wide absence constraint requirement_ref to at least one "
                    "semantically relevant assignment and state the constraint in its "
                    "acceptance_intent."
                    if current_locked_offer_protocol
                    else "Cover every requirement with an assignment or a real gap."
                ),
            },
        }
        if selection_locked:
            request["selection_locked"] = True
        if capability_gap_lock is not None:
            request["capability_gap_lock"] = copy.deepcopy(
                capability_gap_lock
            )
        else:
            if not selection_locked:
                request["schema_example"] = {
                    "schema_version": "product_plan_blueprint.v2",
                    "sections": section_example,
                    "selection": {
                        "offer_ref": (
                            selected_offer["offer_ref"]
                            if selected_offer is not None
                            else ""
                        ),
                        "assignments": assignments,
                    },
                    "gaps": gaps,
                }
        result, evidence = self._generate_json(
            model,
            "product_blueprint",
            request,
            cancel_check,
            prompt_version=prompt_version,
        )
        if capability_gap_lock is not None:
            result = self._expand_locked_gap_blueprint(
                result,
                requirements,
            )
        blueprint = self._validate_blueprint(
            result,
            requirements,
            set(candidates),
            {
                offer["offer_ref"]: {
                    member["candidate_ref"] for member in offer["members"]
                }
                for offer in composition_offers
            },
        )
        evidence["structured_response_digest"] = _digest(blueprint)
        return blueprint, evidence

    @staticmethod
    def _expand_locked_gap_blueprint(
        value: Any,
        requirements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        row = _exact_dict(
            value,
            {"schema_version", "sections", "selection", "gaps"},
            "blueprint.shape_invalid",
        )
        selection = _exact_dict(
            row["selection"],
            {"offer_ref", "assignments"},
            "blueprint.selection_invalid",
        )
        if (
            row["schema_version"] != "product_plan_blueprint.v2"
            or selection != {"offer_ref": "", "assignments": {}}
            or type(row["gaps"]) is not list
            or len(row["gaps"]) != 1
        ):
            raise ProductPlanningError(
                "product_plan_response_invalid",
                "blueprint.locked_gap_invalid",
            )
        gap = _exact_dict(
            row["gaps"][0],
            {"title", "reason"},
            "blueprint.locked_gap_invalid",
        )
        return {
            "schema_version": "product_plan_blueprint.v2",
            "sections": row["sections"],
            "selection": selection,
            "gaps": [
                {
                    "section_id": "backend",
                    "requirement_refs": [
                        requirement["ref"] for requirement in requirements
                    ],
                    "title": gap["title"],
                    "reason": gap["reason"],
                }
            ],
        }

    @staticmethod
    def _compile_blueprint_dependencies(
        sections: list[dict[str, Any]],
        candidate_map: dict[str, dict[str, Any]],
        selected_refs: list[str],
    ) -> dict[str, int]:
        if not selected_refs:
            return {}
        selected = [candidate_map[candidate_ref] for candidate_ref in selected_refs]
        pairs = [(item["capsule_id"], item["version_id"]) for item in selected]
        if len(set(pairs)) != len(pairs):
            raise ProductPlanningError("product_plan_binding_ambiguous")
        capability_keys = {item["capability_key"] for item in selected}
        if len(capability_keys) != 1:
            raise ProductPlanningError("product_plan_capability_group_invalid")
        capability_key = next(iter(capability_keys))
        group = [
            item
            for item in candidate_map.values()
            if item["capability_key"] == capability_key
        ]
        if {
            (item["capsule_id"], item["version_id"]) for item in group
        } != set(pairs):
            raise ProductPlanningError("product_plan_role_coverage_invalid")
        occurrences: dict[tuple[str, str], dict[str, Any]] = {}
        for section in sections:
            for work_item in section["work_items"]:
                binding = work_item["capsule_bindings"][0]
                pair = (binding["capsule_id"], binding["version_id"])
                if pair in occurrences:
                    raise ProductPlanningError("product_plan_binding_ambiguous")
                occurrences[pair] = work_item
        if set(occurrences) != set(pairs):
            raise ProductPlanningError("product_plan_role_coverage_invalid")
        chain = ProductPlanner._composition_chain(selected)

        delivery_waves: dict[str, int] = {}
        previous: str | None = None
        for wave, capsule in enumerate(chain, start=1):
            work_item = occurrences[(capsule["capsule_id"], capsule["version_id"])]
            work_item["depends_on"] = [] if previous is None else [previous]
            delivery_waves[work_item["work_item_id"]] = wave
            previous = work_item["work_item_id"]
        return delivery_waves

    def _build_blueprint_plan(
        self,
        workspace: dict[str, Any],
        outline: dict[str, Any],
        catalog: dict[str, Any],
        cancel_check: Callable[[], bool] | None,
        phase_callback: Callable[[str], None] | None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        planning_answers = self._planning_answers(workspace)
        replan_handoff = self._capability_replan_for_successor(workspace)
        if replan_handoff is not None:
            catalog = self._validate_capability_replan_current(
                replan_handoff,
                catalog,
            )["catalog"]
        plan_id = "plan_" + _digest(
            {
                "workspace_id": workspace["workspace_id"],
                "goal_digest": workspace["goal_digest"],
                "outline_response_digest": workspace["outline_response_digest"],
            }
        )[:32]
        requirement_map: dict[str, str] = {}
        requirements: list[dict[str, Any]] = []
        for index, raw in enumerate(outline["requirements"], start=1):
            requirement_id = "requirement_" + _digest(
                {
                    "plan_id": plan_id,
                    "index": index,
                    "statement": raw["statement"],
                }
            )[:20]
            requirement_map[raw["ref"]] = requirement_id
            requirements.append(
                {
                    "requirement_id": requirement_id,
                    "statement": raw["statement"],
                    "source": (
                        "planning_answer"
                        if raw["source"] == "planning_answer"
                        else "product_goal"
                    ),
                    "source_digest": (
                        _digest(planning_answers)
                        if raw["source"] == "planning_answer"
                        else workspace["goal_digest"]
                    ),
                }
            )

        candidate_map: dict[str, dict[str, Any]] = {}
        for index, capsule in enumerate(catalog["capsules"]):
            candidate_ref = "candidate_" + _digest(
                {
                    "workspace_id": workspace["workspace_id"],
                    "warehouse_revision": catalog["warehouse_revision"],
                    "index": index,
                    "capsule_id": capsule["capsule_id"],
                    "version_id": capsule["version_id"],
                    "canonical_hash": capsule["canonical_hash"],
                }
            )[:24]
            candidate_map[candidate_ref] = capsule

        blueprint = workspace.get("blueprint")
        direct_blueprint_workspace = (
            workspace["schema_version"]
            == DIRECT_BLUEPRINT_WORKSPACE_SCHEMA_VERSION
        )
        legacy_blueprint = (
            direct_blueprint_workspace
            and
            type(blueprint) is dict
            and blueprint.get("schema_version") == "product_plan_blueprint.v1"
        )
        composition_offers = self._composition_offers(candidate_map)
        blueprint_offers = composition_offers
        selected_offer: dict[str, Any] | None = None
        capability_gap_lock: dict[str, Any] | None = None
        if not direct_blueprint_workspace:
            selection = workspace["composition_selection"]
            experience_cases = self._workspace_experience_cases(workspace)
            selection_input_digest = self._composition_selection_input_digest(
                workspace,
                outline,
                composition_offers,
            )
            if selection is None:
                self._enter_phase(
                    workspace,
                    "composition_selection",
                    phase_callback,
                )
                selection, evidence = self._composition_selection_call(
                    workspace["model"],
                    workspace["goal"],
                    outline,
                    planning_answers,
                    composition_offers,
                    cancel_check,
                    selection_locked=replan_handoff is not None,
                    prompt_version=self._workspace_prompt_version(workspace),
                    experience_cases=experience_cases,
                )
                workspace["model_calls"].append(evidence)
                workspace["composition_selection"] = copy.deepcopy(selection)
                workspace[
                    "composition_selection_input_digest"
                ] = selection_input_digest
                workspace[
                    "composition_selection_response_digest"
                ] = evidence["structured_response_digest"]
                workspace["updated_at"] = _now()
                with self._lock:
                    self._save_workspace(workspace)
            elif (
                workspace["composition_selection_input_digest"]
                != selection_input_digest
                or self._validate_composition_selection(selection) != selection
            ):
                raise ProductPlanningError(
                    "product_plan_resume_input_changed"
                )
            selected_offer = self._resolve_composition_selection(
                selection,
                composition_offers,
            )
            if replan_handoff is not None and selected_offer is None:
                raise ProductPlanningError(
                    "product_plan_composition_unknown"
                )
            blueprint_offers = (
                [] if selected_offer is None else [selected_offer]
            )
            if (
                selected_offer is None
                and workspace["schema_version"] in GAP_WORKSPACE_SCHEMA_VERSIONS
            ):
                gap_candidates = self._capability_gap_candidates(catalog)
                if len(gap_candidates) == 1:
                    capability_gap_lock = (
                        self._capability_gap_blueprint_lock(
                            gap_candidates[0],
                            candidate_map,
                        )
                    )
                elif (
                    workspace["schema_version"]
                    in TARGET_SELECTION_WORKSPACE_SCHEMA_VERSIONS
                    and 2 <= len(gap_candidates) <= 3
                ):
                    target_selection = (
                        self._validate_capability_gap_target_selection(
                            workspace[
                                "capability_gap_target_selection"
                            ]
                        )
                    )
                    if target_selection is None:
                        question_set = (
                            self._capability_gap_target_question_set(
                                gap_candidates,
                                catalog,
                            )
                        )
                        if (
                            question_set["digest"]
                            in workspace["question_history"]
                        ):
                            raise ProductPlanningError(
                                "product_plan_question_repeated"
                            )
                        workspace["question_history"].append(
                            question_set["digest"]
                        )
                        workspace["current_question_set"] = question_set
                        workspace["status"] = "needs_clarification"
                        workspace["phase"] = None
                        workspace["updated_at"] = _now()
                        with self._lock:
                            self._save_workspace(workspace)
                        return None, []
                    capability_gap_lock = (
                        self._capability_gap_blueprint_lock(
                            self._selected_capability_gap_candidate(
                                target_selection,
                                catalog,
                            ),
                            candidate_map,
                        )
                    )
                elif (
                    workspace["schema_version"]
                    in TARGET_SELECTION_WORKSPACE_SCHEMA_VERSIONS
                    and len(gap_candidates) > 3
                ):
                    raise ProductPlanningError(
                        "product_plan_capability_gap_target_ambiguous"
                    )
        offer_members = {
            offer["offer_ref"]: {
                member["candidate_ref"] for member in offer["members"]
            }
            for offer in blueprint_offers
        }
        expected_input_digest = (
            self._blueprint_input_digest(
                workspace,
                outline,
                candidate_map,
                None if legacy_blueprint else composition_offers,
            )
            if direct_blueprint_workspace
            else self._selected_blueprint_input_digest(
                workspace,
                outline,
                selected_offer,
                capability_gap_lock,
            )
        )
        model_calls: list[dict[str, Any]] = []
        if blueprint is None:
            self._enter_phase(workspace, "product_blueprint", phase_callback)
            blueprint, evidence = self._blueprint_call(
                workspace["model"],
                workspace["goal"],
                outline,
                planning_answers,
                candidate_map,
                blueprint_offers,
                cancel_check,
                selection_locked=not direct_blueprint_workspace,
                prompt_version=self._workspace_prompt_version(workspace),
                capability_gap_lock=capability_gap_lock,
            )
            workspace["model_calls"].append(evidence)
            workspace["blueprint"] = copy.deepcopy(blueprint)
            workspace["blueprint_input_digest"] = expected_input_digest
            workspace["blueprint_response_digest"] = evidence[
                "structured_response_digest"
            ]
            workspace["updated_at"] = _now()
            with self._lock:
                self._save_workspace(workspace)
        elif (
            workspace["blueprint_input_digest"] != expected_input_digest
            or self._validate_blueprint(
                blueprint,
                outline["requirements"],
                set(candidate_map),
                None if legacy_blueprint else offer_members,
            )
            != blueprint
        ):
            raise ProductPlanningError("product_plan_resume_input_changed")

        self._cancelled(cancel_check)
        self._enter_phase(workspace, "validation", phase_callback)
        sections_by_id = {
            section_id: {
                "section_id": section_id,
                "applicability": blueprint["sections"][section_id][
                    "applicability"
                ],
                "summary": blueprint["sections"][section_id]["summary"],
                "work_items": [],
                "gaps": [],
            }
            for section_id in SECTION_IDS
        }
        selected_pairs: set[tuple[str, str]] = set()
        assignments = (
            blueprint["assignments"]
            if legacy_blueprint
            else blueprint["selection"]["assignments"]
        )
        selected_refs = sorted(assignments)
        for candidate_ref in selected_refs:
            assignment = assignments[candidate_ref]
            capsule = candidate_map[candidate_ref]
            pair = (capsule["capsule_id"], capsule["version_id"])
            if pair in selected_pairs:
                raise ProductPlanningError("product_plan_binding_ambiguous")
            selected_pairs.add(pair)
            requirement_ids = [
                requirement_map[ref] for ref in assignment["requirement_refs"]
            ]
            work_item_id = "work_item_" + _digest(
                {
                    "plan_id": plan_id,
                    "candidate_ref": candidate_ref,
                    "section_id": assignment["section_id"],
                    "requirement_ids": requirement_ids,
                }
            )[:20]
            sections_by_id[assignment["section_id"]]["work_items"].append(
                {
                    "work_item_id": work_item_id,
                    "title": assignment["title"],
                    "description": assignment["summary"],
                    "requirement_ids": requirement_ids,
                    "depends_on": [],
                    "acceptance_intent": assignment["acceptance_intent"],
                    "capsule_bindings": [
                        {
                            "capsule_id": capsule["capsule_id"],
                            "version_id": capsule["version_id"],
                            "display_name": capsule["display_name"],
                            "capability_kind": capsule["capability_kind"],
                            "canonical_hash": capsule["canonical_hash"],
                            "identity_status": "formal_exact_version",
                            "selection_status": "model_suggested",
                            "review_status": "pending",
                            "reason": assignment["summary"],
                        }
                    ],
                    "gap_reason": None,
                }
            )
        for index, gap in enumerate(blueprint["gaps"]):
            requirement_ids = [
                requirement_map[ref] for ref in gap["requirement_refs"]
            ]
            sections_by_id[gap["section_id"]]["gaps"].append(
                {
                    "gap_id": "gap_"
                    + _digest(
                        {
                            "plan_id": plan_id,
                            "index": index,
                            "section_id": gap["section_id"],
                            "title": gap["title"],
                            "reason": gap["reason"],
                            "requirement_ids": requirement_ids,
                        }
                    )[:20],
                    "title": gap["title"],
                    "reason": gap["reason"],
                    "requirement_ids": requirement_ids,
                }
            )
        sections = [sections_by_id[section_id] for section_id in SECTION_IDS]
        delivery_waves = self._compile_blueprint_dependencies(
            sections,
            candidate_map,
            selected_refs,
        )
        if legacy_blueprint:
            planning_rules_version = LEGACY_BLUEPRINT_PLANNING_RULES_VERSION
            prompt_version = LEGACY_BLUEPRINT_PROMPT_VERSION
        elif direct_blueprint_workspace:
            planning_rules_version = DIRECT_BLUEPRINT_PLANNING_RULES_VERSION
            prompt_version = DIRECT_BLUEPRINT_PROMPT_VERSION
        else:
            planning_rules_version = self._workspace_rules_version(workspace)
            prompt_version = self._workspace_prompt_version(workspace)
        plan: dict[str, Any] = {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": plan_id,
            "plan_version": 1,
            "parent_plan_digest": None,
            "product_name": outline["product_name"],
            "goal": workspace["goal"],
            "goal_digest": workspace["goal_digest"],
            "language": outline["language"],
            "requirements": requirements,
            "planning_answers": copy.deepcopy(planning_answers),
            "sections": sections,
            "model": copy.deepcopy(workspace["model"]),
            "planning_rules_version": planning_rules_version,
            "prompt_version": prompt_version,
            "structured_response_digests": (
                [
                    workspace["outline_response_digest"],
                    workspace["blueprint_response_digest"],
                ]
                if direct_blueprint_workspace
                else [
                    workspace["outline_response_digest"],
                    workspace["composition_selection_response_digest"],
                    workspace["blueprint_response_digest"],
                ]
            ),
            "warehouse_revision": catalog["warehouse_revision"],
            "candidate_generated": False,
            "product_generated": False,
        }
        plan["canonical_digest"] = self._plan_digest(plan)
        self._validate_plan(plan)
        if self._stale_bindings(plan, catalog):
            raise ProductPlanningError("product_plan_catalog_validation_failed")
        workspace["delivery_waves"] = delivery_waves
        return plan, model_calls

    def _section_call(
        self,
        model: dict[str, Any],
        section_id: str,
        requirements: list[dict[str, str]],
        answers: list[dict[str, Any]],
        candidates: dict[str, dict[str, Any]],
        cancel_check: Callable[[], bool] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        safe_candidates = [
            {
                "candidate_ref": candidate_ref,
                "display_name": item["display_name"],
                "capability_key": item["capability_key"],
                "role_key": item["role_key"],
                "variant_key": item["variant_key"],
                "capability_kind": item["capability_kind"],
            }
            for candidate_ref, item in sorted(candidates.items())
        ]
        example_candidate = safe_candidates[0]["candidate_ref"] if safe_candidates else ""
        example = {
            "schema_version": SECTION_DRAFT_SCHEMA_VERSION,
            "section_id": section_id,
            "summary": "Section delivery intent",
            "work_items": [
                {
                    "title": "Traceable work item",
                    "summary": "Capability and delivery intent only",
                    "requirement_refs": [requirements[0]["ref"]],
                    "delivery_wave": 1,
                    "acceptance_intent": "Observable acceptance intent",
                    "candidate_ref": example_candidate,
                    "gap_reason": (
                        "" if example_candidate else "No eligible candidate supports it"
                    ),
                }
            ],
        }
        value, evidence = self._generate_json(
            model,
            "section_" + section_id,
            {
                "section_id": section_id,
                "requirements": requirements,
                "answers": answers,
                "candidate_catalog": safe_candidates,
                "rules": (
                    "Return semantic work-item drafts only. Do not emit work-item IDs, refs, "
                    "dependencies, plan IDs, version IDs, or digests. requirement_refs must "
                    "use supplied requirement refs. delivery_wave must be 1, 2, 3, or 4: "
                    "1 for foundations, identity, core data and contracts; 2 for core business "
                    "capabilities; 3 for integration, user experience and recovery exercises; "
                    "4 for deployment, operations and final validation. Use only a supplied "
                    "candidate_ref when suggesting a capsule. Otherwise use candidate_ref='' "
                    "and provide a concrete gap_reason. A supplied candidate_ref requires "
                    "gap_reason=''. Product-wide absence constraints such as local-only or "
                    "offline operation, no network, login, database, persistence, deployment, "
                    "or backend service are acceptance conditions, not standalone capabilities. "
                    "When supplied candidates cover the requested user-visible behavior, attach "
                    "those constraint requirement_refs to a relevant candidate-backed work item "
                    "and describe them in acceptance_intent; do not create a gap solely for such "
                    "a constraint. Create a gap only when no supplied candidate covers a required "
                    "user-visible behavior, data capability, or integration. Text limits are: "
                    "section summary 1-500 characters; "
                    "work-item title 1-180, summary 1-800, acceptance_intent 1-500, and "
                    "gap_reason 0-500 characters. These text fields must not have leading "
                    "or trailing whitespace. Control characters are forbidden except tab "
                    "and newline. "
                    "Do not emit files, paths, source, diffs, build results, or validations. "
                    "The backend alone assigns formal identities and dependencies."
                ),
                "schema_example": example,
            },
            cancel_check,
        )
        row = _exact_dict(
            value,
            {"schema_version", "section_id", "summary", "work_items"},
            "section.shape_invalid",
        )
        if row["schema_version"] != SECTION_DRAFT_SCHEMA_VERSION:
            raise ProductPlanningError(
                "product_plan_response_invalid", "section.schema_version_invalid"
            )
        if row["section_id"] != section_id:
            raise ProductPlanningError(
                "product_plan_response_invalid", "section.section_id_mismatch"
            )
        if (
            type(row["work_items"]) is not list
            or not 1 <= len(row["work_items"]) <= 48
        ):
            raise ProductPlanningError(
                "product_plan_response_invalid", "section.item_count_invalid"
            )
        work_items: list[dict[str, Any]] = []
        requirement_refs = {item["ref"] for item in requirements}
        candidate_refs = set(candidates)
        for raw in row["work_items"]:
            item = _exact_dict(
                raw,
                {
                    "title",
                    "summary",
                    "requirement_refs",
                    "delivery_wave",
                    "acceptance_intent",
                    "candidate_ref",
                    "gap_reason",
                },
                "section.work_item_shape_invalid",
            )
            if (
                type(item["requirement_refs"]) is not list
                or not item["requirement_refs"]
                or set(item["requirement_refs"]) - requirement_refs
                or len(set(item["requirement_refs"])) != len(item["requirement_refs"])
            ):
                raise ProductPlanningError(
                    "product_plan_response_invalid", "section.requirement_refs_invalid"
                )
            if (
                type(item["delivery_wave"]) is not int
                or item["delivery_wave"] not in {1, 2, 3, 4}
            ):
                raise ProductPlanningError(
                    "product_plan_response_invalid", "section.delivery_wave_invalid"
                )
            candidate_ref = item["candidate_ref"]
            if type(candidate_ref) is not str or (
                candidate_ref and candidate_ref not in candidate_refs
            ):
                raise ProductPlanningError(
                    "product_plan_response_invalid", "section.candidate_ref_unknown"
                )
            gap_reason = _safe_text(
                item["gap_reason"],
                minimum=0,
                maximum=500,
                rule_code="section.gap_reason_invalid",
            )
            if candidate_ref and gap_reason:
                raise ProductPlanningError(
                    "product_plan_response_invalid", "section.candidate_gap_conflict"
                )
            if not candidate_ref and not gap_reason:
                raise ProductPlanningError(
                    "product_plan_response_invalid", "section.gap_reason_required"
                )
            work_items.append(
                {
                    "title": _safe_text(
                        item["title"],
                        maximum=180,
                        rule_code="section.work_item_text_invalid",
                    ),
                    "summary": _safe_text(
                        item["summary"],
                        maximum=800,
                        rule_code="section.work_item_text_invalid",
                    ),
                    "requirement_refs": list(item["requirement_refs"]),
                    "delivery_wave": item["delivery_wave"],
                    "acceptance_intent": _safe_text(
                        item["acceptance_intent"],
                        maximum=500,
                        rule_code="section.work_item_text_invalid",
                    ),
                    "candidate_ref": candidate_ref,
                    "gap_reason": gap_reason,
                }
            )
        return (
            {
                "section_id": section_id,
                "summary": _safe_text(
                    row["summary"],
                    maximum=500,
                    rule_code="section.summary_invalid",
                ),
                "work_items": work_items,
            },
            evidence,
        )

    def _match_call(
        self,
        model: dict[str, Any],
        section_id: str,
        work_item_refs: list[str],
        candidates: dict[str, dict[str, str]],
        cancel_check: Callable[[], bool] | None,
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        safe_candidates = [
            {
                "candidate_ref": ref,
                "display_name": item["display_name"],
                "capability_key": item["capability_key"],
                "role_key": item["role_key"],
                "variant_key": item["variant_key"],
                "capability_kind": item["capability_kind"],
            }
            for ref, item in sorted(candidates.items())
        ]
        value, evidence = self._generate_json(
            model,
            "catalog_match_" + section_id,
            {
                "section_id": section_id,
                "work_item_refs": work_item_refs,
                "candidate_batch": safe_candidates,
                "rules": (
                    "Suggest only semantically relevant candidates from this batch. "
                    "A suggestion is not validation or confirmed matching."
                ),
                "schema_example": {
                    "schema_version": "product_plan_match.v1",
                    "section_id": section_id,
                    "matches": [],
                },
            },
            cancel_check,
        )
        row = _exact_dict(value, {"schema_version", "section_id", "matches"})
        if (
            row["schema_version"] != "product_plan_match.v1"
            or row["section_id"] != section_id
            or type(row["matches"]) is not list
            or len(row["matches"]) > len(work_item_refs) * max(1, len(candidates))
        ):
            raise ProductPlanningError("product_plan_response_invalid")
        result: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for raw in row["matches"]:
            match = _exact_dict(
                raw, {"work_item_ref", "candidate_ref", "reason"}
            )
            key = (str(match["work_item_ref"]), str(match["candidate_ref"]))
            if (
                key[0] not in work_item_refs
                or key[1] not in candidates
                or key in seen
            ):
                raise ProductPlanningError("product_plan_candidate_unknown")
            seen.add(key)
            result.append(
                {
                    "work_item_ref": key[0],
                    "candidate_ref": key[1],
                    "reason": _safe_text(match["reason"], maximum=400),
                }
            )
        return result, evidence

    def _plan_digest(self, plan: dict[str, Any]) -> str:
        canonical = {
            key: value for key, value in plan.items() if key != "canonical_digest"
        }
        return _digest(canonical)

    def _validate_plan(self, plan: Any) -> None:
        required = {
            "schema_version",
            "plan_id",
            "plan_version",
            "parent_plan_digest",
            "product_name",
            "goal",
            "goal_digest",
            "language",
            "requirements",
            "planning_answers",
            "sections",
            "model",
            "planning_rules_version",
            "prompt_version",
            "structured_response_digests",
            "warehouse_revision",
            "candidate_generated",
            "product_generated",
            "canonical_digest",
        }
        if (
            type(plan) is not dict
            or set(plan) != required
            or plan["schema_version"]
            not in {LEGACY_PLAN_SCHEMA_VERSION, PLAN_SCHEMA_VERSION}
            or not re.fullmatch(r"plan_[0-9a-f]{32}", str(plan["plan_id"]))
            or type(plan["plan_version"]) is not int
            or plan["plan_version"] < 1
            or (
                plan["parent_plan_digest"] is not None
                and _DIGEST.fullmatch(str(plan["parent_plan_digest"])) is None
            )
            or plan["goal_digest"] != _digest(plan["goal"])
            or type(plan["product_name"]) is not str
            or type(plan["goal"]) is not str
            or plan["language"] not in {"zh", "en"}
            or type(plan["requirements"]) is not list
            or not plan["requirements"]
            or type(plan["planning_answers"]) is not list
            or type(plan["sections"]) is not list
            or [section.get("section_id") for section in plan["sections"]]
            != list(SECTION_IDS)
            or (
                plan["schema_version"] == LEGACY_PLAN_SCHEMA_VERSION
                and (
                    plan["planning_rules_version"]
                    not in {
                        LEGACY_PLANNING_RULES_VERSION,
                        SECTION_PLANNING_RULES_VERSION,
                    }
                    or plan["prompt_version"]
                    not in {
                        HISTORICAL_PLANNING_PROMPT_VERSION,
                        LEGACY_PLANNING_PROMPT_VERSION,
                    }
                )
            )
            or (
                plan["schema_version"] == PLAN_SCHEMA_VERSION
                and (
                    plan["planning_rules_version"],
                    plan["prompt_version"],
                )
                not in {
                    (
                        LEGACY_BLUEPRINT_PLANNING_RULES_VERSION,
                        LEGACY_BLUEPRINT_PROMPT_VERSION,
                    ),
                    (
                        DIRECT_BLUEPRINT_PLANNING_RULES_VERSION,
                        DIRECT_BLUEPRINT_PROMPT_VERSION,
                    ),
                    (
                        PREVIOUS_LOCKED_BLUEPRINT_PLANNING_RULES_VERSION,
                        LEGACY_LOCKED_BLUEPRINT_PROMPT_VERSION,
                    ),
                    (
                        PREVIOUS_LOCKED_BLUEPRINT_PLANNING_RULES_VERSION,
                        PREVIOUS_LOCKED_BLUEPRINT_PROMPT_VERSION,
                    ),
                    (
                        PREVIOUS_GAP_PLANNING_RULES_VERSION,
                        PREVIOUS_GAP_PLANNING_PROMPT_VERSION,
                    ),
                    (
                        PREVIOUS_TARGET_SELECTION_PLANNING_RULES_VERSION,
                        PREVIOUS_GAP_PLANNING_PROMPT_VERSION,
                    ),
                    (
                        PREVIOUS_REQUIREMENT_COVERAGE_PLANNING_RULES_VERSION,
                        PREVIOUS_REQUIREMENT_COVERAGE_PROMPT_VERSION,
                    ),
                    (PLANNING_RULES_VERSION, PLANNING_PROMPT_VERSION),
                }
            )
            or type(plan["structured_response_digests"]) is not list
            or any(
                _DIGEST.fullmatch(str(item)) is None
                for item in plan["structured_response_digests"]
            )
            or type(plan["warehouse_revision"]) is not int
            or plan["warehouse_revision"] < 0
            or plan["candidate_generated"] is not False
            or plan["product_generated"] is not False
            or plan["canonical_digest"] != self._plan_digest(plan)
        ):
            raise ProductPlanningError("product_plan_invalid")
        try:
            self._validate_stored_answers(plan["planning_answers"])
            model = _stored_exact(
                plan["model"],
                {"name", "digest", "parameter_count", "parameter_size"},
            )
        except ProductPlanningError as exc:
            raise ProductPlanningError("product_plan_invalid") from exc
        if (
            type(model["name"]) is not str
            or _DIGEST.fullmatch(str(model["digest"])) is None
            or type(model["parameter_count"]) is not int
            or not 0 < model["parameter_count"] <= MAX_MODEL_PARAMETERS
            or (
                model["parameter_size"] is not None
                and type(model["parameter_size"]) is not str
            )
        ):
            raise ProductPlanningError("product_plan_invalid")
        requirement_ids: set[str] = set()
        for requirement in plan["requirements"]:
            row = _exact_dict(
                requirement,
                {"requirement_id", "statement", "source", "source_digest"},
            )
            requirement_id = str(row["requirement_id"])
            if (
                not requirement_id.startswith("requirement_")
                or requirement_id in requirement_ids
                or row["source"] not in {"product_goal", "planning_answer"}
                or _DIGEST.fullmatch(str(row["source_digest"])) is None
                or (
                    row["source"] == "product_goal"
                    and row["source_digest"] != plan["goal_digest"]
                )
                or (
                    row["source"] == "planning_answer"
                    and row["source_digest"] != _digest(plan["planning_answers"])
                )
                or type(row["statement"]) is not str
            ):
                raise ProductPlanningError("product_plan_invalid")
            requirement_ids.add(requirement_id)
        work_items: dict[str, dict[str, Any]] = {}
        binding_pairs: set[tuple[str, str]] = set()
        covered: set[str] = set()
        for section in plan["sections"]:
            row = _exact_dict(
                section,
                (
                    {"section_id", "summary", "work_items", "gaps"}
                    if plan["schema_version"] == LEGACY_PLAN_SCHEMA_VERSION
                    else {
                        "section_id",
                        "applicability",
                        "summary",
                        "work_items",
                        "gaps",
                    }
                ),
            )
            if (
                row["section_id"] not in SECTION_IDS
                or type(row["summary"]) is not str
                or type(row["work_items"]) is not list
                or type(row["gaps"]) is not list
                or (
                    plan["schema_version"] == LEGACY_PLAN_SCHEMA_VERSION
                    and not row["work_items"]
                    and not row["gaps"]
                )
                or (
                    plan["schema_version"] == PLAN_SCHEMA_VERSION
                    and (
                        row["applicability"]
                        not in {"applicable", "not_applicable"}
                        or (
                            row["applicability"] == "applicable"
                            and not row["work_items"]
                            and not row["gaps"]
                        )
                        or (
                            row["applicability"] == "not_applicable"
                            and (row["work_items"] or row["gaps"])
                        )
                    )
                )
            ):
                raise ProductPlanningError("product_plan_invalid")
            for item in row["work_items"]:
                work = _exact_dict(
                    item,
                    {
                        "work_item_id",
                        "title",
                        "description",
                        "requirement_ids",
                        "depends_on",
                        "acceptance_intent",
                        "capsule_bindings",
                        "gap_reason",
                    },
                )
                work_id = str(work["work_item_id"])
                if (
                    not work_id.startswith("work_item_")
                    or work_id in work_items
                    or type(work["requirement_ids"]) is not list
                    or not work["requirement_ids"]
                    or set(work["requirement_ids"]) - requirement_ids
                    or len(set(work["requirement_ids"])) != len(work["requirement_ids"])
                    or type(work["depends_on"]) is not list
                    or len(set(work["depends_on"])) != len(work["depends_on"])
                    or type(work["capsule_bindings"]) is not list
                    or bool(work["capsule_bindings"]) == bool(work["gap_reason"])
                    or any(
                        type(work[key]) is not str or not work[key]
                        for key in ("title", "description", "acceptance_intent")
                    )
                    or (
                        work["gap_reason"] is not None
                        and type(work["gap_reason"]) is not str
                    )
                ):
                    raise ProductPlanningError("product_plan_invalid")
                for binding in work["capsule_bindings"]:
                    exact = _exact_dict(
                        binding,
                        {
                            "capsule_id",
                            "version_id",
                            "display_name",
                            "capability_kind",
                            "canonical_hash",
                            "identity_status",
                            "selection_status",
                            "review_status",
                            "reason",
                        },
                    )
                    if (
                        exact["identity_status"] != "formal_exact_version"
                        or exact["selection_status"] != "model_suggested"
                        or exact["review_status"] not in {"pending", "user_confirmed"}
                        or _DIGEST.fullmatch(str(exact["canonical_hash"])) is None
                        or any(
                            type(exact[key]) is not str or not exact[key]
                            for key in (
                                "capsule_id",
                                "version_id",
                                "display_name",
                                "capability_kind",
                                "reason",
                            )
                        )
                    ):
                        raise ProductPlanningError("product_plan_invalid")
                    pair = (exact["capsule_id"], exact["version_id"])
                    if (
                        plan["schema_version"] == PLAN_SCHEMA_VERSION
                        and pair in binding_pairs
                    ):
                        raise ProductPlanningError("product_plan_binding_ambiguous")
                    binding_pairs.add(pair)
                work_items[work_id] = work
                covered.update(work["requirement_ids"])
            for gap in row["gaps"]:
                exact_gap = _exact_dict(
                    gap, {"gap_id", "title", "reason", "requirement_ids"}
                )
                if (
                    not str(exact_gap["gap_id"]).startswith("gap_")
                    or type(exact_gap["requirement_ids"]) is not list
                    or not exact_gap["requirement_ids"]
                    or set(exact_gap["requirement_ids"]) - requirement_ids
                    or any(
                        type(exact_gap[key]) is not str or not exact_gap[key]
                        for key in ("title", "reason")
                    )
                ):
                    raise ProductPlanningError("product_plan_invalid")
                covered.update(exact_gap["requirement_ids"])
        if covered != requirement_ids:
            raise ProductPlanningError(
                "product_plan_requirement_uncovered",
                "section.requirement_uncovered",
            )
        for work_id, item in work_items.items():
            dependencies = item["depends_on"]
            if work_id in dependencies or any(dep not in work_items for dep in dependencies):
                raise ProductPlanningError("product_plan_dependency_invalid")
        self._assert_acyclic(work_items)

    @staticmethod
    def _assert_acyclic(work_items: dict[str, dict[str, Any]]) -> None:
        incoming = {
            work_id: set(item["depends_on"])
            for work_id, item in work_items.items()
        }
        ready = sorted(
            work_id for work_id, dependencies in incoming.items() if not dependencies
        )
        visited: list[str] = []
        while ready:
            current = ready.pop(0)
            visited.append(current)
            for work_id in sorted(incoming):
                if current not in incoming[work_id]:
                    continue
                incoming[work_id].remove(current)
                if not incoming[work_id] and work_id not in visited and work_id not in ready:
                    ready.append(work_id)
                    ready.sort()
        if len(visited) != len(work_items):
            raise ProductPlanningError("product_plan_dependency_cycle")

    def _revision_prompt_plan(
        self,
        plan: dict[str, Any],
        delivery_waves: dict[str, int],
    ) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
        salt = uuid.uuid4().hex
        requirement_refs = {
            requirement["requirement_id"]: "requirement_ref_"
            + _digest(
                {
                    "salt": salt,
                    "index": index,
                    "requirement_id": requirement["requirement_id"],
                }
            )[:20]
            for index, requirement in enumerate(plan["requirements"])
        }
        work_items = [
            (section["section_id"], item)
            for section in plan["sections"]
            for item in section["work_items"]
        ]
        binding_refs = {
            item["work_item_id"]: "binding_ref_"
            + _digest(
                {
                    "salt": salt,
                    "index": index,
                    "work_item_id": item["work_item_id"],
                }
            )[:20]
            for index, (_section_id, item) in enumerate(work_items)
        }
        candidate_index = 0
        sections: list[dict[str, Any]] = []
        for section in plan["sections"]:
            public_items: list[dict[str, Any]] = []
            for item in section["work_items"]:
                suggestions: list[dict[str, str]] = []
                for binding in item["capsule_bindings"]:
                    candidate_ref = "candidate_ref_" + _digest(
                        {
                            "salt": salt,
                            "index": candidate_index,
                            "capsule_id": binding["capsule_id"],
                            "version_id": binding["version_id"],
                        }
                    )[:20]
                    candidate_index += 1
                    suggestions.append(
                        {
                            "candidate_ref": candidate_ref,
                            "display_name": binding["display_name"],
                            "capability_kind": binding["capability_kind"],
                        }
                    )
                public_items.append(
                    {
                        "binding_ref": binding_refs[item["work_item_id"]],
                        "title": item["title"],
                        "summary": item["description"],
                        "requirement_refs": [
                            requirement_refs[requirement_id]
                            for requirement_id in item["requirement_ids"]
                        ],
                        "delivery_wave": delivery_waves[item["work_item_id"]],
                        "acceptance_intent": item["acceptance_intent"],
                        "candidate_suggestions": suggestions,
                    }
                )
            sections.append(
                {
                    "section_id": section["section_id"],
                    "summary": section["summary"],
                    "work_items": public_items,
                    "gaps": [
                        {
                            "title": gap["title"],
                            "reason": gap["reason"],
                            "requirement_refs": [
                                requirement_refs[requirement_id]
                                for requirement_id in gap["requirement_ids"]
                            ],
                        }
                        for gap in section["gaps"]
                    ],
                }
            )
        prompt_plan = {
            "product_name": plan["product_name"],
            "language": plan["language"],
            "requirements": [
                {
                    "requirement_ref": requirement_refs[
                        requirement["requirement_id"]
                    ],
                    "statement": requirement["statement"],
                }
                for requirement in plan["requirements"]
            ],
            "sections": sections,
        }
        return prompt_plan, {
            "binding_refs": {
                opaque: formal for formal, opaque in binding_refs.items()
            },
            "requirement_refs": {
                opaque: formal for formal, opaque in requirement_refs.items()
            },
        }

    def _translate_revision_operations(
        self,
        operations: Any,
        references: dict[str, dict[str, str]],
        current_plan: dict[str, Any],
        target_section_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if type(operations) is not list:
            raise ProductPlanningError(
                "product_plan_diff_invalid",
                "diff.operations_shape_invalid",
            )
        base_items = {
            item["binding_ref"]: {"section_id": section["section_id"], **item}
            for section in current_plan.get("sections", [])
            if type(section) is dict
            for item in section.get("work_items", [])
            if type(item) is dict and type(item.get("binding_ref")) is str
        }
        if target_section_id is not None:
            target_sections = [
                section
                for section in current_plan.get("sections", [])
                if type(section) is dict
                and section.get("section_id") == target_section_id
            ]
            if target_section_id not in SECTION_IDS or len(target_sections) != 1:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.target_section_invalid",
                )
            target_requirement_refs = {
                ref
                for item in target_sections[0].get("work_items", [])
                if type(item) is dict
                for ref in item.get("requirement_refs", [])
                if type(ref) is str
            } | {
                ref
                for gap in target_sections[0].get("gaps", [])
                if type(gap) is dict
                for ref in gap.get("requirement_refs", [])
                if type(ref) is str
            }
        else:
            target_requirement_refs = set(references["requirement_refs"])
        result: list[dict[str, Any]] = []
        for raw in operations:
            if type(raw) is not dict:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.operation_not_object",
                )
            if "op" not in raw:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.operation_required_key_missing.op",
                )
            op = raw["op"]
            if op not in {"add", "update", "remove"}:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.operation_kind_invalid",
                )
            update_fields = (
                "title",
                "summary",
                "acceptance_intent",
                "delivery_wave",
            )
            required_keys = {
                "add": (
                    "op",
                    "section_id",
                    "title",
                    "summary",
                    "requirement_refs",
                    "delivery_wave",
                    "acceptance_intent",
                ),
                "update": ("op", "binding_ref"),
                "remove": ("op", "binding_ref"),
            }[op]
            allowed_keys = {
                "add": set(required_keys),
                "update": {"op", "binding_ref", *update_fields},
                "remove": set(required_keys),
            }[op]
            missing = next((key for key in required_keys if key not in raw), None)
            if missing is not None:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    f"diff.operation_required_key_missing.{missing}",
                )
            if set(raw) - allowed_keys:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.operation_extra_key",
                )
            operation = raw
            if op == "update" and not any(key in operation for key in update_fields):
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.update_fields_empty",
                )
            binding_ref = operation.get("binding_ref")
            base_item = base_items.get(binding_ref) if op != "add" else None
            if op != "add" and base_item is None:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.binding_ref_unknown",
                )
            if (
                target_section_id is not None
                and (
                    (op == "add" and operation["section_id"] != target_section_id)
                    or (
                        op != "add"
                        and base_item["section_id"] != target_section_id
                    )
                )
            ):
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.target_section_mismatch",
                )
            requirement_refs_value = (
                operation["requirement_refs"]
                if op == "add"
                else base_item["requirement_refs"] if op == "update" else []
            )
            if type(requirement_refs_value) is not list or any(
                type(ref) is not str for ref in requirement_refs_value
            ):
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.requirement_refs_shape_invalid",
                )
            if op == "add":
                work_item_id: str | None = None
            else:
                if type(binding_ref) is not str:
                    raise ProductPlanningError(
                        "product_plan_diff_invalid",
                        "diff.binding_ref_shape_invalid",
                    )
                work_item_id = references["binding_refs"].get(binding_ref)
                if work_item_id is None:
                    raise ProductPlanningError(
                        "product_plan_diff_invalid",
                        "diff.binding_ref_unknown",
                    )
            if any(
                ref not in references["requirement_refs"]
                for ref in requirement_refs_value
            ):
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.requirement_ref_unknown",
                )
            if any(ref not in target_requirement_refs for ref in requirement_refs_value):
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.target_section_mismatch",
                )
            requirement_ids = [
                references["requirement_refs"][ref]
                for ref in requirement_refs_value
            ]
            section_id = (
                operation["section_id"]
                if op == "add"
                else base_item["section_id"]
            )
            result.append(
                {
                    "op": op,
                    "work_item_id": work_item_id,
                    "section_id": section_id,
                    "title": operation.get(
                        "title",
                        base_item["title"] if op == "update" else "",
                    ),
                    "description": operation.get(
                        "summary",
                        base_item["summary"] if op == "update" else "",
                    ),
                    "requirement_ids": requirement_ids,
                    "delivery_wave": operation.get(
                        "delivery_wave",
                        base_item["delivery_wave"] if op == "update" else None,
                    ),
                    "acceptance_intent": operation.get(
                        "acceptance_intent",
                        base_item["acceptance_intent"] if op == "update" else "",
                    ),
                }
            )
        return result

    @staticmethod
    def _revision_fields(value: Any) -> dict[str, Any]:
        row = _exact_dict(
            value,
            {"title", "summary", "acceptance_intent", "delivery_wave"},
        )
        if type(row["delivery_wave"]) is not int or row["delivery_wave"] not in {
            1,
            2,
            3,
            4,
        }:
            raise ProductPlanningError(
                "product_plan_response_invalid",
                "diff.delivery_wave_invalid",
            )
        return {
            "title": _safe_text(
                row["title"],
                maximum=180,
                rule_code="diff.title_invalid",
            ),
            "summary": _safe_text(
                row["summary"],
                maximum=800,
                rule_code="diff.description_invalid",
            ),
            "acceptance_intent": _safe_text(
                row["acceptance_intent"],
                maximum=500,
                rule_code="diff.acceptance_intent_invalid",
            ),
            "delivery_wave": row["delivery_wave"],
        }

    @staticmethod
    def _editable_fields(
        item: dict[str, Any],
        delivery_waves: dict[str, int],
    ) -> dict[str, Any]:
        return {
            "title": item["title"],
            "summary": item["description"],
            "acceptance_intent": item["acceptance_intent"],
            "delivery_wave": delivery_waves[item["work_item_id"]],
        }

    def _targeted_plan_diff(
        self,
        current: dict[str, Any],
        proposed: dict[str, Any],
        base_delivery_waves: dict[str, int],
        proposed_delivery_waves: dict[str, int],
        edit_scope: dict[str, Any],
    ) -> dict[str, Any]:
        result = self._plan_diff(current, proposed)
        operation = edit_scope["target_operation"]
        binding_ref = edit_scope["target_binding_ref"]
        before_items = {
            item["work_item_id"]: item
            for section in current["sections"]
            for item in section["work_items"]
        }
        after_items = {
            item["work_item_id"]: item
            for section in proposed["sections"]
            for item in section["work_items"]
        }
        if operation == "add":
            if len(result["added"]) != 1:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.target_operation_mismatch",
                )
            target_work_item_id = result["added"][0]
            editable_before = None
        else:
            target_work_item_id = binding_ref
            editable_before = self._editable_fields(
                before_items[target_work_item_id],
                base_delivery_waves,
            )
        editable_after = self._editable_fields(
            after_items[target_work_item_id],
            proposed_delivery_waves,
        )
        if editable_before == editable_after:
            raise ProductPlanningError(
                "product_plan_diff_invalid",
                "diff.no_effect",
            )
        result.update(
            {
                "schema_version": "product_plan_diff.v3",
                "target_section_id": edit_scope["target_section_id"],
                "target_operation": operation,
                "target_binding_ref": binding_ref,
                "editable_before": editable_before,
                "editable_after": editable_after,
                "dependency_impact_count": sum(
                    change["work_item_id"] != target_work_item_id
                    for change in result["changes"]
                ),
            }
        )
        result["diff_digest"] = _digest(
            {key: value for key, value in result.items() if key != "diff_digest"}
        )
        return result

    def _store_targeted_pending_diff(
        self,
        workspace: dict[str, Any],
        operation: dict[str, Any],
        edit_scope: dict[str, Any],
        catalog: dict[str, Any],
        structured_response_digests: list[str],
        phase_callback: Callable[[str], None] | None,
        *,
        user_edit_digest: str | None = None,
        warehouse_revision: int | None = None,
    ) -> dict[str, Any]:
        plan = workspace["plan"]
        base_delivery_waves = copy.deepcopy(workspace["delivery_waves"])
        proposed, proposed_delivery_waves = self._apply_revision_operations(
            plan,
            [operation],
            base_delivery_waves,
        )
        proposed["plan_version"] = plan["plan_version"] + 1
        proposed["parent_plan_digest"] = plan["canonical_digest"]
        proposed["structured_response_digests"] = list(
            structured_response_digests
        )
        proposed["planning_answers"] = copy.deepcopy(workspace["answers"])
        planning_answers_digest = _digest(proposed["planning_answers"])
        for requirement in proposed["requirements"]:
            if requirement["source"] == "planning_answer":
                requirement["source_digest"] = planning_answers_digest
        proposed["warehouse_revision"] = (
            catalog["warehouse_revision"]
            if warehouse_revision is None
            else warehouse_revision
        )
        proposed["canonical_digest"] = self._plan_digest(proposed)
        self._validate_plan(proposed)
        if self._stale_bindings(plan, catalog) or self._stale_bindings(
            proposed,
            catalog,
        ):
            raise ProductPlanningError("product_plan_diff_capsule_stale")
        public_diff = self._targeted_plan_diff(
            plan,
            proposed,
            base_delivery_waves,
            proposed_delivery_waves,
            edit_scope,
        )
        pending_diff = {
            "target_section_id": edit_scope["target_section_id"],
            "base_plan_digest": plan["canonical_digest"],
            "base_delivery_waves": base_delivery_waves,
            "edit_scope": copy.deepcopy(edit_scope),
            "proposed_plan": proposed,
            "proposed_delivery_waves": proposed_delivery_waves,
            "public_diff": public_diff,
        }
        if user_edit_digest is not None:
            pending_diff["user_edit_digest"] = user_edit_digest
        self._validate_pending_diff(plan, pending_diff)
        self._report_phase("validation", phase_callback)
        workspace["phase"] = "validation"
        workspace["pending_diff"] = pending_diff
        workspace["status"] = "plan_diff_review"
        workspace["confirmation"] = None
        workspace["pending_revision_feedback"] = None
        workspace["updated_at"] = _now()
        with self._lock:
            self._save_workspace(workspace)
        return _ok(self._workspace_projection(workspace))

    def _targeted_revision_scope(
        self,
        workspace: dict[str, Any],
        target_section_id: str,
        target_operation: str,
        requirement_refs: Any,
        target_binding_ref: Any,
    ) -> dict[str, Any]:
        plan = workspace["plan"]
        requirements = {
            requirement["requirement_id"]: requirement
            for requirement in plan["requirements"]
        }
        if target_operation == "add":
            if (
                type(requirement_refs) is not list
                or not requirement_refs
                or any(type(ref) is not str for ref in requirement_refs)
            ):
                raise ProductPlanningError(
                    "product_plan_revision_invalid",
                    "diff.requirement_refs_shape_invalid",
                )
            if len(set(requirement_refs)) != len(requirement_refs):
                raise ProductPlanningError(
                    "product_plan_revision_invalid",
                    "diff.requirement_ref_duplicate",
                )
            if set(requirement_refs) - set(requirements):
                raise ProductPlanningError(
                    "product_plan_revision_invalid",
                    "diff.requirement_ref_unknown",
                )
            locked_requirement_ids = list(requirement_refs)
            locked_work_item_id = None
            current_fields = None
        else:
            if type(target_binding_ref) is not str:
                raise ProductPlanningError(
                    "product_plan_revision_invalid",
                    "diff.binding_ref_shape_invalid",
                )
            matched = [
                (section["section_id"], item)
                for section in plan["sections"]
                for item in section["work_items"]
                if item["work_item_id"] == target_binding_ref
            ]
            if len(matched) != 1:
                raise ProductPlanningError(
                    "product_plan_revision_invalid",
                    "diff.binding_ref_unknown",
                )
            if matched[0][0] != target_section_id:
                raise ProductPlanningError(
                    "product_plan_revision_invalid",
                    "diff.target_section_mismatch",
                )
            locked_work_item_id = target_binding_ref
            locked_requirement_ids = list(matched[0][1]["requirement_ids"])
            current_fields = self._editable_fields(
                matched[0][1],
                workspace["delivery_waves"],
            )
        return {
            "target_binding_ref": locked_work_item_id,
            "requirement_refs": locked_requirement_ids,
            "current_fields": current_fields,
            "requirement_statements": [
                requirements[requirement_id]["statement"]
                for requirement_id in locked_requirement_ids
            ],
        }

    def _request_targeted_revision(
        self,
        workspace: dict[str, Any],
        message: str,
        catalog: dict[str, Any],
        cancel_check: Callable[[], bool] | None,
        phase_callback: Callable[[str], None] | None,
        target_section_id: str,
        target_operation: str,
        target_scope: dict[str, Any],
    ) -> dict[str, Any]:
        plan = workspace["plan"]
        model = self._selected_model(check_current=False)
        if self._model_identity(model) != workspace["model"]:
            raise ProductPlanningError("product_planning_model_digest_changed")
        locked_work_item_id = target_scope["target_binding_ref"]
        locked_requirement_ids = target_scope["requirement_refs"]
        request_digest = _digest(
            {
                "schema_version": "product_plan_targeted_revision_request.v1",
                "base_plan_digest": plan["canonical_digest"],
                "message": message,
                "target_section_id": target_section_id,
                "target_operation": target_operation,
                "target_binding_ref": locked_work_item_id,
                "requirement_refs": locked_requirement_ids,
            }
        )
        request_value = {
            "revision_request": message,
            "editable_context": {
                "current_fields": target_scope["current_fields"],
                "requirement_statements": target_scope[
                    "requirement_statements"
                ],
            },
            "rules": (
                "Return exactly four editable planning fields. Preserve the supplied "
                "meaning, use no leading or trailing whitespace, and use only tab or "
                "newline control characters. Do not return keys other than title, "
                "summary, acceptance_intent, and delivery_wave."
            ),
            "schema_example": {
                "title": "Concise work item title",
                "summary": "Concrete delivery description",
                "acceptance_intent": "Observable acceptance intent",
                "delivery_wave": 3,
            },
        }
        fields_value, evidence = self._generate_json(
            workspace["model"],
            "plan_revision_fields",
            request_value,
            cancel_check,
        )
        fields = self._revision_fields(fields_value)
        evidence.update(
            {
                "base_plan_digest": plan["canonical_digest"],
                "revision_request_digest": request_digest,
                "model_name": workspace["model"]["name"],
                "model_digest": workspace["model"]["digest"],
                "prompt_version": REVISION_PROMPT_VERSIONS[
                    "plan_revision_fields"
                ],
                "schema_version": REVISION_SCHEMA_VERSIONS[
                    "plan_revision_fields"
                ],
            }
        )
        workspace["model_calls"].append(evidence)
        self._cancelled(cancel_check)
        operation = {
            "op": target_operation,
            "work_item_id": locked_work_item_id,
            "section_id": target_section_id,
            "title": fields["title"],
            "description": fields["summary"],
            "requirement_ids": locked_requirement_ids,
            "delivery_wave": fields["delivery_wave"],
            "acceptance_intent": fields["acceptance_intent"],
        }
        edit_scope = {
            "schema_version": "product_plan_diff_edit_scope.v1",
            "target_operation": target_operation,
            "target_section_id": target_section_id,
            "target_binding_ref": locked_work_item_id,
            "requirement_refs": locked_requirement_ids,
        }
        return self._store_targeted_pending_diff(
            workspace,
            operation,
            edit_scope,
            catalog,
            [*plan["structured_response_digests"], evidence["structured_response_digest"]],
            phase_callback,
        )

    def _edit_pending_diff(
        self,
        workspace: dict[str, Any],
        expected_diff_digest: Any,
        fields_value: Any,
        catalog: dict[str, Any],
        phase_callback: Callable[[str], None] | None,
    ) -> dict[str, Any]:
        pending = workspace.get("pending_diff")
        if (
            type(expected_diff_digest) is not str
            or _DIGEST.fullmatch(expected_diff_digest) is None
            or type(pending) is not dict
            or pending.get("public_diff", {}).get("diff_digest")
            != expected_diff_digest
            or workspace.get("status") != "plan_diff_review"
            or type(pending.get("edit_scope")) is not dict
            or pending.get("base_delivery_waves") != workspace["delivery_waves"]
        ):
            raise ProductPlanningError("product_plan_diff_stale")
        self._validate_pending_diff(workspace["plan"], pending)
        try:
            fields = self._revision_fields(fields_value)
        except ProductPlanningError as exc:
            raise ProductPlanningError(
                "product_plan_revision_invalid",
                exc.rule_code,
            ) from exc
        if fields == pending["public_diff"]["editable_after"]:
            raise ProductPlanningError(
                "product_plan_revision_invalid",
                "diff.edit_no_effect",
            )
        edit_scope = copy.deepcopy(pending["edit_scope"])
        target_binding_ref = edit_scope["target_binding_ref"]
        operation = {
            "op": edit_scope["target_operation"],
            "work_item_id": target_binding_ref,
            "section_id": edit_scope["target_section_id"],
            "title": fields["title"],
            "description": fields["summary"],
            "requirement_ids": list(edit_scope["requirement_refs"]),
            "delivery_wave": fields["delivery_wave"],
            "acceptance_intent": fields["acceptance_intent"],
        }
        user_edit_digest = _digest(
            {
                "schema_version": "product_plan_diff_user_edit.v1",
                "fields": fields,
            }
        )
        return self._store_targeted_pending_diff(
            workspace,
            operation,
            edit_scope,
            catalog,
            pending["proposed_plan"]["structured_response_digests"],
            phase_callback,
            user_edit_digest=user_edit_digest,
            warehouse_revision=pending["proposed_plan"]["warehouse_revision"],
        )

    def _request_revision(
        self,
        workspace: dict[str, Any],
        feedback: str,
        catalog: dict[str, Any],
        cancel_check: Callable[[], bool] | None,
        answers: list[dict[str, Any]],
        phase_callback: Callable[[str], None] | None,
        selected_action: str,
        target_section_id: str | None = None,
    ) -> dict[str, Any]:
        plan = workspace.get("plan")
        if (
            type(plan) is not dict
            or selected_action not in {"ask_plan", "propose_revision"}
        ):
            raise ProductPlanningError("product_plan_revision_unavailable")
        if selected_action == "propose_revision":
            target_section_id = self._revision_target_section(
                plan,
                target_section_id,
            )
        elif target_section_id is not None:
            raise ProductPlanningError(
                "product_plan_revision_invalid",
                "diff.target_section_invalid",
            )
        original_status = workspace["status"]
        self._cancelled(cancel_check)
        prompt_plan, revision_refs = self._revision_prompt_plan(
            plan,
            workspace["delivery_waves"],
        )
        revision_request_digest_value = {
                "schema_version": "product_plan_revision_request.v1",
                "base_plan_digest": plan["canonical_digest"],
                "feedback": feedback,
                "clarification_answers": answers,
                "selected_action": selected_action,
        }
        if target_section_id is not None:
            revision_request_digest_value.update(
                {
                    "schema_version": "product_plan_revision_request.v2",
                    "target_section_id": target_section_id,
                }
            )
        revision_request_digest = _digest(revision_request_digest_value)

        def bound_evidence(
            evidence: dict[str, Any],
            call_type: str,
        ) -> dict[str, Any]:
            return {
                **evidence,
                "base_plan_digest": plan["canonical_digest"],
                "revision_request_digest": revision_request_digest,
                "model_name": workspace["model"]["name"],
                "model_digest": workspace["model"]["digest"],
                "prompt_version": REVISION_PROMPT_VERSIONS[call_type],
                "schema_version": REVISION_SCHEMA_VERSIONS[call_type],
            }

        first_binding_ref = next(
            (
                item["binding_ref"]
                for section in prompt_plan["sections"]
                if target_section_id is None
                or section["section_id"] == target_section_id
                for item in section["work_items"]
            ),
            None,
        )
        if first_binding_ref is not None:
            operation_example = {
                "op": "update",
                "binding_ref": first_binding_ref,
                "summary": "Updated delivery intent",
            }
        else:
            operation_example = {
                "op": "add",
                "section_id": target_section_id or "frontend",
                "title": "New plan item",
                "summary": "New delivery intent",
                "requirement_refs": [
                    prompt_plan["requirements"][0]["requirement_ref"]
                ],
                "delivery_wave": 2,
                "acceptance_intent": "Review the new delivery intent",
            }
        if selected_action == "ask_plan":
            call_type = "plan_revision_explanation"
            revision_request: dict[str, Any] = {
                "revision_request": feedback,
                "current_plan": prompt_plan,
                "rules": (
                    "Answer only the user's question about the current plan. Return one "
                    "controlled explanation and do not propose a change, ask questions, "
                    "or return operations."
                ),
                "schema_example": {"explanation": "Controlled explanation"},
            }
        else:
            call_type = "plan_revision_proposal"
            revision_request = {
                "revision_request": feedback,
                "clarification_answers": answers,
                "target_section_id": target_section_id,
                "current_plan": prompt_plan,
                "rules": (
                    "The user explicitly chose one fixed target_section_id and a plan "
                    "revision. Every add, update, or remove must stay inside that supplied "
                    "target section; never choose or change the target section. Return operations "
                    "when every blocking choice is known. Otherwise return an explanation "
                    "plus 1-3 blocking questions. Explanation-only is forbidden. Never return "
                    "questions and operations together. Questions must each have 2-3 mutually "
                    "exclusive options, the recommended option first but not selected, "
                    "allow_custom=true, and unsupported options marked forms_gap=true. For "
                    "update, choose one supplied binding_ref and return only changed title, "
                    "summary, acceptance_intent, or delivery_wave. Never send section_id, "
                    "requirement_refs, dependencies, formal IDs, or digests for update. For "
                    "remove, return only op and a supplied binding_ref. For add, use one fixed "
                    "section_id, known requirement_refs, content, and delivery_wave. The "
                    "backend alone assigns IDs and recompiles dependencies."
                ),
                "operation_schema": {
                    "op": "add|update|remove",
                    "update": "binding_ref plus one or more mutable fields",
                    "remove": "binding_ref only",
                    "add": "section_id, requirement_refs, content, and delivery_wave",
                },
                "schema_examples": [
                    {
                        "explanation": "A blocking choice is still required.",
                        "questions": [
                            {
                                "ref": "blocking_choice",
                                "prompt": "Which option should the plan use?",
                                "options": [
                                    {
                                        "ref": "recommended_option",
                                        "label": "Recommended option",
                                        "impact": "Keeps the plan within current capability.",
                                        "recommended": True,
                                        "forms_gap": False,
                                    },
                                    {
                                        "ref": "alternative_option",
                                        "label": "Alternative option",
                                        "impact": "May form a capability gap.",
                                        "recommended": False,
                                        "forms_gap": True,
                                    },
                                ],
                                "allow_custom": True,
                            }
                        ],
                    },
                    {"operations": [operation_example]},
                ],
            }
        revision_value, revision_evidence = self._generate_json(
            workspace["model"],
            call_type,
            revision_request,
            cancel_check,
        )
        revision_evidence = bound_evidence(revision_evidence, call_type)
        workspace["model_calls"].append(revision_evidence)
        workspace["updated_at"] = _now()
        response_keys = set(revision_value)
        if response_keys == {"explanation"}:
            if selected_action != "ask_plan":
                raise ProductPlanningError("product_plan_response_invalid")
            row = _exact_dict(revision_value, {"explanation"})
            explanation = _safe_text(row["explanation"], maximum=2_000)
            self._cancelled(cancel_check)
            workspace["status"] = (
                "confirmed" if original_status == "confirmed" else "plan_review"
            )
            workspace["pending_revision_feedback"] = None
            with self._lock:
                self._save_workspace(workspace)
            projection = self._workspace_projection(workspace)
            projection["revision_result"] = {
                "kind": "explanation",
                "explanation": explanation,
                "plan_changed": False,
            }
            return _ok(projection)
        if response_keys != {"operations"}:
            raise ProductPlanningError("product_plan_response_invalid")
        if selected_action != "propose_revision":
            raise ProductPlanningError("product_plan_response_invalid")
        row = _exact_dict(revision_value, {"operations"})
        if type(row["operations"]) is not list or not 1 <= len(row["operations"]) <= 16:
            raise ProductPlanningError("product_plan_response_invalid")
        translated_operations = self._translate_revision_operations(
            row["operations"],
            revision_refs,
            prompt_plan,
            target_section_id,
        )
        proposed, proposed_delivery_waves = self._apply_revision_operations(
            plan,
            translated_operations,
            workspace["delivery_waves"],
            target_section_id,
        )
        proposed["plan_version"] = plan["plan_version"] + 1
        proposed["parent_plan_digest"] = plan["canonical_digest"]
        proposed["structured_response_digests"] = (
            list(plan["structured_response_digests"])
            + [revision_evidence["structured_response_digest"]]
        )
        proposed["planning_answers"] = copy.deepcopy(workspace["answers"])
        planning_answers_digest = _digest(proposed["planning_answers"])
        for requirement in proposed["requirements"]:
            if requirement["source"] == "planning_answer":
                requirement["source_digest"] = planning_answers_digest
        proposed["warehouse_revision"] = catalog["warehouse_revision"]
        proposed["canonical_digest"] = self._plan_digest(proposed)
        self._enter_phase(workspace, "validation", phase_callback)
        self._validate_plan(proposed)
        self._cancelled(cancel_check)
        public_diff = self._plan_diff(plan, proposed, target_section_id)
        if not public_diff["changes"]:
            raise ProductPlanningError(
                "product_plan_diff_invalid",
                "diff.no_effect",
            )
        workspace["pending_diff"] = {
            "target_section_id": target_section_id,
            "base_plan_digest": plan["canonical_digest"],
            "proposed_plan": proposed,
            "proposed_delivery_waves": proposed_delivery_waves,
            "public_diff": public_diff,
        }
        workspace["status"] = "plan_diff_review"
        workspace["confirmation"] = None
        workspace["pending_revision_feedback"] = None
        with self._lock:
            self._save_workspace(workspace)
        return _ok(self._workspace_projection(workspace))

    def _apply_revision_operations(
        self,
        plan: dict[str, Any],
        operations: Any,
        current_delivery_waves: dict[str, int],
        target_section_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        if type(operations) is not list or not 1 <= len(operations) <= 16:
            raise ProductPlanningError(
                "product_plan_diff_invalid",
                "diff.operations_count_invalid",
            )
        proposed = copy.deepcopy(plan)
        sections = {
            section["section_id"]: section for section in proposed["sections"]
        }
        if target_section_id is not None and target_section_id not in sections:
            raise ProductPlanningError(
                "product_plan_diff_invalid",
                "diff.target_section_invalid",
            )
        by_id = {
            item["work_item_id"]: (section, item)
            for section in proposed["sections"]
            for item in section["work_items"]
        }
        requirement_ids = {
            item["requirement_id"] for item in proposed["requirements"]
        }
        delivery_waves = dict(current_delivery_waves)
        for index, raw in enumerate(operations):
            try:
                operation = _exact_dict(
                    raw,
                    {
                        "op",
                        "work_item_id",
                        "section_id",
                        "title",
                        "description",
                        "requirement_ids",
                        "delivery_wave",
                        "acceptance_intent",
                    },
                )
            except ProductPlanningError as exc:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.formal_operation_shape_invalid",
                ) from exc
            op = operation["op"]
            section_id = operation["section_id"]
            if op not in {"add", "update", "remove"}:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.formal_operation_kind_invalid",
                )
            if section_id not in sections:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.section_id_invalid",
                )
            if target_section_id is not None and section_id != target_section_id:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.target_section_mismatch",
                )
            if type(operation["requirement_ids"]) is not list:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.requirement_ids_shape_invalid",
                )
            if op == "remove":
                work_id = str(operation["work_item_id"])
                target = by_id.get(work_id)
                if target is None:
                    raise ProductPlanningError(
                        "product_plan_diff_invalid",
                        "diff.remove_target_unknown",
                    )
                if target[0]["section_id"] != section_id:
                    raise ProductPlanningError(
                        "product_plan_diff_invalid",
                        "diff.remove_section_mismatch",
                    )
                if any(
                    operation[key] not in {"", None}
                    for key in (
                        "title",
                        "description",
                        "delivery_wave",
                        "acceptance_intent",
                    )
                ) or operation["requirement_ids"]:
                    raise ProductPlanningError(
                        "product_plan_diff_invalid",
                        "diff.remove_payload_invalid",
                    )
                target[0]["work_items"].remove(target[1])
                by_id.pop(work_id)
                delivery_waves.pop(work_id)
                continue
            if not operation["requirement_ids"]:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.requirement_ids_empty",
                )
            if set(operation["requirement_ids"]) - requirement_ids:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.requirement_id_unknown",
                )
            if len(set(operation["requirement_ids"])) != len(
                operation["requirement_ids"]
            ):
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.requirement_id_duplicate",
                )
            delivery_wave = operation["delivery_wave"]
            if type(delivery_wave) is not int or delivery_wave not in {1, 2, 3, 4}:
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.delivery_wave_invalid",
                )
            title = _safe_text(
                operation["title"],
                maximum=180,
                rule_code="diff.title_invalid",
            )
            description = _safe_text(
                operation["description"],
                maximum=800,
                rule_code="diff.description_invalid",
            )
            acceptance = _safe_text(
                operation["acceptance_intent"],
                maximum=500,
                rule_code="diff.acceptance_intent_invalid",
            )
            if op == "add":
                if operation["work_item_id"] not in {"", None}:
                    raise ProductPlanningError(
                        "product_plan_diff_invalid",
                        "diff.add_work_item_id_not_empty",
                    )
                work_id = "work_item_" + _digest(
                    {
                        "plan_id": plan["plan_id"],
                        "parent": plan["canonical_digest"],
                        "index": index,
                        "section_id": section_id,
                        "title": title,
                        "description": description,
                        "requirement_ids": operation["requirement_ids"],
                        "delivery_wave": delivery_wave,
                    }
                )[:20]
                if work_id in by_id:
                    raise ProductPlanningError(
                        "product_plan_diff_invalid",
                        "diff.generated_work_item_id_duplicate",
                    )
                item = {
                    "work_item_id": work_id,
                    "title": title,
                    "description": description,
                    "requirement_ids": list(operation["requirement_ids"]),
                    "depends_on": [],
                    "acceptance_intent": acceptance,
                    "capsule_bindings": [],
                    "gap_reason": "revision_requires_capsule_rematch",
                }
                sections[section_id]["work_items"].append(item)
                by_id[work_id] = (sections[section_id], item)
                delivery_waves[work_id] = delivery_wave
            else:
                work_id = str(operation["work_item_id"])
                target = by_id.get(work_id)
                if target is None:
                    raise ProductPlanningError(
                        "product_plan_diff_invalid",
                        "diff.update_target_unknown",
                    )
                if target[0]["section_id"] != section_id:
                    raise ProductPlanningError(
                        "product_plan_diff_invalid",
                        "diff.update_section_mismatch",
                    )
                if operation["requirement_ids"] != target[1]["requirement_ids"]:
                    raise ProductPlanningError(
                        "product_plan_diff_invalid",
                        "diff.update_requirements_changed",
                    )
                content_changed = any(
                    (
                        title != target[1]["title"],
                        description != target[1]["description"],
                        acceptance != target[1]["acceptance_intent"],
                    )
                )
                target[1].update(
                    {
                        "title": title,
                        "description": description,
                        "acceptance_intent": acceptance,
                    }
                )
                if content_changed and target[1]["capsule_bindings"]:
                    target[1]["capsule_bindings"] = []
                    target[1]["gap_reason"] = "revision_requires_capsule_rematch"
                delivery_waves[work_id] = delivery_wave
        bound_computations = {
            (binding["capsule_id"], binding["version_id"])
            for section in plan["sections"]
            for item in section["work_items"]
            for binding in item["capsule_bindings"]
            if binding["capability_kind"] == "computation"
        }
        if (
            plan["planning_rules_version"] == LEGACY_PLANNING_RULES_VERSION
            or len(bound_computations) != 2
        ):
            self._compile_wave_dependencies(proposed["sections"], delivery_waves)
        for section in proposed["sections"]:
            section["gaps"] = [
                {
                    "gap_id": "gap_"
                    + _digest(
                        {
                            "plan_id": plan["plan_id"],
                            "work_item_id": item["work_item_id"],
                        }
                    )[:20],
                    "title": item["title"],
                    "reason": item["gap_reason"],
                    "requirement_ids": list(item["requirement_ids"]),
                }
                for item in section["work_items"]
                if item["gap_reason"] is not None
            ]
        if target_section_id is not None:
            current_sections = {
                section["section_id"]: section for section in plan["sections"]
            }
            if any(
                section != current_sections.get(section["section_id"])
                for section in proposed["sections"]
                if section["section_id"] != target_section_id
            ):
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.target_section_mismatch",
                )
        proposed["canonical_digest"] = self._plan_digest(proposed)
        return proposed, delivery_waves

    @staticmethod
    def _plan_diff(
        current: dict[str, Any],
        proposed: dict[str, Any],
        target_section_id: str | None = None,
    ) -> dict[str, Any]:
        before = {
            item["work_item_id"]: {
                "section_id": section["section_id"],
                "item": copy.deepcopy(item),
            }
            for section in current["sections"]
            for item in section["work_items"]
        }
        after = {
            item["work_item_id"]: {
                "section_id": section["section_id"],
                "item": copy.deepcopy(item),
            }
            for section in proposed["sections"]
            for item in section["work_items"]
        }
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        updated = sorted(
            work_id
            for work_id in set(before) & set(after)
            if before[work_id] != after[work_id]
        )
        result = {
            "schema_version": (
                "product_plan_diff.v2"
                if target_section_id is not None
                else "product_plan_diff.v1"
            ),
            "base_plan_digest": current["canonical_digest"],
            "proposed_plan_digest": proposed["canonical_digest"],
            "added": added,
            "removed": removed,
            "updated": updated,
            "changes": [
                {
                    "kind": kind,
                    "work_item_id": work_id,
                    "before": copy.deepcopy(before.get(work_id)),
                    "after": copy.deepcopy(after.get(work_id)),
                }
                for kind, identifiers in (
                    ("added", added),
                    ("removed", removed),
                    ("updated", updated),
                )
                for work_id in identifiers
            ],
        }
        if target_section_id is not None:
            result["target_section_id"] = target_section_id
        result["diff_digest"] = _digest(result)
        return result

    def _validate_pending_diff(
        self,
        current: dict[str, Any],
        pending: Any,
    ) -> None:
        if type(pending) is not dict:
            raise ProductPlanningError("product_plan_diff_invalid")
        basic_keys = {
            "base_plan_digest",
            "proposed_plan",
            "proposed_delivery_waves",
            "public_diff",
        }
        scoped_keys = {
            "target_section_id",
            *basic_keys,
        }
        targeted_keys = {
            "target_section_id",
            "base_delivery_waves",
            "edit_scope",
            *basic_keys,
        }
        pending_keys = set(pending)
        is_scoped = pending_keys == scoped_keys
        is_targeted = pending_keys in {
            frozenset(targeted_keys),
            frozenset({*targeted_keys, "user_edit_digest"}),
        }
        if pending_keys not in {
            frozenset(basic_keys),
            frozenset(scoped_keys),
            frozenset(targeted_keys),
            frozenset({*targeted_keys, "user_edit_digest"}),
        }:
            raise ProductPlanningError("product_plan_diff_invalid")
        row = _exact_dict(
            pending,
            (
                ({*targeted_keys, "user_edit_digest"} if "user_edit_digest" in pending else targeted_keys)
                if is_targeted
                else scoped_keys if is_scoped else basic_keys
            ),
        )
        target_section_id = (
            self._revision_target_section(current, row["target_section_id"])
            if is_scoped or is_targeted
            else None
        )
        if row["base_plan_digest"] != current["canonical_digest"]:
            raise ProductPlanningError("product_plan_diff_stale")
        proposed = row["proposed_plan"]
        self._validate_plan(proposed)
        proposed_delivery_waves = row["proposed_delivery_waves"]
        if type(proposed_delivery_waves) is not dict:
            raise ProductPlanningError("product_plan_diff_invalid")
        try:
            self._validate_dependency_compilation(
                proposed,
                proposed_delivery_waves,
            )
        except ProductPlanningError as exc:
            raise ProductPlanningError("product_plan_diff_invalid") from exc
        if proposed["parent_plan_digest"] != current["canonical_digest"]:
            raise ProductPlanningError("product_plan_diff_invalid")
        if is_targeted:
            base_delivery_waves = row["base_delivery_waves"]
            if type(base_delivery_waves) is not dict:
                raise ProductPlanningError("product_plan_diff_invalid")
            try:
                self._validate_dependency_compilation(
                    current,
                    base_delivery_waves,
                )
            except ProductPlanningError as exc:
                raise ProductPlanningError("product_plan_diff_invalid") from exc
            edit_scope = _exact_dict(
                row["edit_scope"],
                {
                    "schema_version",
                    "target_operation",
                    "target_section_id",
                    "target_binding_ref",
                    "requirement_refs",
                },
            )
            operation_kind = edit_scope["target_operation"]
            requirement_refs = edit_scope["requirement_refs"]
            if (
                edit_scope["schema_version"]
                != "product_plan_diff_edit_scope.v1"
                or operation_kind not in {"add", "update"}
                or edit_scope["target_section_id"] != target_section_id
                or type(requirement_refs) is not list
                or not requirement_refs
                or any(type(ref) is not str for ref in requirement_refs)
                or len(set(requirement_refs)) != len(requirement_refs)
                or set(requirement_refs)
                - {
                    requirement["requirement_id"]
                    for requirement in current["requirements"]
                }
            ):
                raise ProductPlanningError("product_plan_diff_invalid")
            before_items = {
                item["work_item_id"]: (section["section_id"], item)
                for section in current["sections"]
                for item in section["work_items"]
            }
            after_items = {
                item["work_item_id"]: (section["section_id"], item)
                for section in proposed["sections"]
                for item in section["work_items"]
            }
            target_binding_ref = edit_scope["target_binding_ref"]
            if operation_kind == "add":
                added = sorted(set(after_items) - set(before_items))
                if target_binding_ref is not None or len(added) != 1:
                    raise ProductPlanningError("product_plan_diff_invalid")
                target_work_item_id = added[0]
            else:
                if (
                    type(target_binding_ref) is not str
                    or target_binding_ref not in before_items
                    or target_binding_ref not in after_items
                ):
                    raise ProductPlanningError("product_plan_diff_invalid")
                target_work_item_id = target_binding_ref
            target_item = after_items[target_work_item_id]
            if (
                target_item[0] != target_section_id
                or target_item[1]["requirement_ids"] != requirement_refs
            ):
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.target_section_mismatch",
                )
            expected_operation = {
                "op": operation_kind,
                "work_item_id": target_binding_ref,
                "section_id": target_section_id,
                "title": target_item[1]["title"],
                "description": target_item[1]["description"],
                "requirement_ids": list(requirement_refs),
                "delivery_wave": proposed_delivery_waves[target_work_item_id],
                "acceptance_intent": target_item[1]["acceptance_intent"],
            }
            expected_proposed, expected_delivery_waves = (
                self._apply_revision_operations(
                    current,
                    [expected_operation],
                    base_delivery_waves,
                )
            )
            structured_response_digests = proposed[
                "structured_response_digests"
            ]
            if (
                type(structured_response_digests) is not list
                or len(structured_response_digests)
                != len(current["structured_response_digests"]) + 1
                or structured_response_digests[:-1]
                != current["structured_response_digests"]
                or _DIGEST.fullmatch(str(structured_response_digests[-1]))
                is None
                or proposed["planning_answers"]
                != current["planning_answers"]
            ):
                raise ProductPlanningError("product_plan_diff_invalid")
            expected_proposed["plan_version"] = current["plan_version"] + 1
            expected_proposed["parent_plan_digest"] = current[
                "canonical_digest"
            ]
            expected_proposed["structured_response_digests"] = list(
                structured_response_digests
            )
            expected_proposed["planning_answers"] = copy.deepcopy(
                current["planning_answers"]
            )
            expected_proposed["warehouse_revision"] = proposed[
                "warehouse_revision"
            ]
            expected_proposed["canonical_digest"] = self._plan_digest(
                expected_proposed
            )
            if (
                expected_proposed != proposed
                or expected_delivery_waves != proposed_delivery_waves
            ):
                raise ProductPlanningError("product_plan_diff_invalid")
            expected = self._targeted_plan_diff(
                current,
                proposed,
                base_delivery_waves,
                proposed_delivery_waves,
                edit_scope,
            )
            if "user_edit_digest" in row and row["user_edit_digest"] != _digest(
                {
                    "schema_version": "product_plan_diff_user_edit.v1",
                    "fields": expected["editable_after"],
                }
            ):
                raise ProductPlanningError("product_plan_diff_invalid")
        elif target_section_id is not None:
            current_sections = {
                section["section_id"]: section for section in current["sections"]
            }
            if any(
                section != current_sections.get(section["section_id"])
                for section in proposed["sections"]
                if section["section_id"] != target_section_id
            ):
                raise ProductPlanningError(
                    "product_plan_diff_invalid",
                    "diff.target_section_mismatch",
                )
            expected = self._plan_diff(current, proposed, target_section_id)
        else:
            expected = self._plan_diff(current, proposed)
        if row["public_diff"] != expected:
            raise ProductPlanningError("product_plan_diff_invalid")
