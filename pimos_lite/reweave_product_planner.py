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


PLAN_SCHEMA_VERSION = "product_plan.v1"
WORKSPACE_SCHEMA_VERSION = "product_workspace.v3"
MODEL_SELECTION_SCHEMA_VERSION = "product_planning_model_selection.v1"
SECTION_DRAFT_SCHEMA_VERSION = "product_plan_section_draft.v2"
SECTION_CHECKPOINT_SCHEMA_VERSION = "product_plan_section_checkpoint.v2"
PLANNING_RULES_VERSION = "reweave_product_planning_rules.v2"
PLANNING_PROMPT_VERSION = "reweave_product_planning_prompt.v5"
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

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_WORKSPACE_ID = re.compile(r"workspace_[0-9a-f]{32}\Z")
_PLAN_TOKEN = re.compile(r"plan_token_[0-9a-f]{48}\Z")
_SUGGESTION_RECEIPT = re.compile(r"suggestion_receipt_[0-9a-f]{48}\Z")
_SAFE_REF = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,95}\Z")
_RUNNING_STATES = frozenset({"model_probe", "planning"})
_SENSITIVE_QUESTION = re.compile(
    r"password|passcode|token|api[ _-]?key|secret|private key|absolute path|"
    r"密码|口令|令牌|密钥|绝对路径",
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
) -> dict[str, Any]:
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
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductPlanningError("product_plan_json_invalid") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


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
    ) -> None:
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
        workspace["status"] = "planning"
        workspace["failure_code"] = None
        if question_set["purpose"] == "initial":
            workspace["outline"] = None
            workspace["outline_input_digest"] = None
            workspace["outline_response_digest"] = None
            workspace["section_checkpoints"] = []
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
    def confirm(
        self,
        plan_token: str,
        plan_digest: str,
        reviewed_plan: dict[str, Any],
        catalog: dict[str, Any],
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
        if workspace.get("status") == "confirmed":
            self._validate_confirmed_snapshot(workspace)
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
            self._validate_stored_confirmation(existing["confirmation"], plan)
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
        receipt = {
            "schema_version": "product_plan_confirmation.v1",
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

    @_public_call
    def get(
        self,
        plan_token: str,
        catalog: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workspace = self._workspace_by_token(plan_token)
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
        return _ok(self._workspace_projection(workspace))

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
        workspace["plan"] = None
        workspace["pending_diff"] = None
        workspace["pending_revision_feedback"] = None
        workspace["confirmation"] = None
        workspace["section_checkpoints"] = []
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
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self._cancelled(cancel_check)
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
            "format": _structured_output_schema(call_type, request_value),
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
        keys = {
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
        capsules: list[dict[str, str]] = []
        identities: set[tuple[str, str]] = set()
        for raw in value["capsules"]:
            row = _exact_dict(raw, keys)
            if (
                any(
                    type(row[name]) is not str or not row[name]
                    for name in keys
                )
                or row["identity_status"] != "formal_exact_version"
                or _DIGEST.fullmatch(row["canonical_hash"]) is None
            ):
                raise ProductPlanningError("product_planning_catalog_invalid")
            identity = (row["capsule_id"], row["version_id"])
            if identity in identities:
                raise ProductPlanningError("product_planning_catalog_invalid")
            identities.add(identity)
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
            "section_checkpoints": [],
            "delivery_waves": {},
            "failure_code": None,
        }

    def _workspace_projection(self, workspace: dict[str, Any]) -> dict[str, Any]:
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
        return {
            "plan_token": workspace["plan_token"],
            "display_name": workspace["display_name"],
            "goal": workspace["goal"],
            "goal_digest": workspace["goal_digest"],
            "status": workspace["status"],
            "phase": workspace["phase"],
            "completed_sections": [
                checkpoint["section_id"]
                for checkpoint in workspace["section_checkpoints"]
            ],
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
            "planning_rules_version": PLANNING_RULES_VERSION,
            "prompt_version": PLANNING_PROMPT_VERSION,
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
            "completed_sections": [
                checkpoint["section_id"]
                for checkpoint in workspace["section_checkpoints"]
            ],
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

    def _validate_workspace(
        self,
        workspace: Any,
        *,
        expected_workspace_id: str | None = None,
    ) -> None:
        required = {
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
            "section_checkpoints",
            "delivery_waves",
            "failure_code",
        }
        if (
            type(workspace) is not dict
            or set(workspace) != required
            or workspace["schema_version"] != WORKSPACE_SCHEMA_VERSION
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
            or type(workspace["section_checkpoints"]) is not list
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
        if workspace["outline"] is None:
            if outline_input_digest is not None or outline_response_digest is not None:
                raise ProductPlanningError("product_workspace_corrupt")
        elif (
            _DIGEST.fullmatch(str(outline_input_digest)) is None
            or outline_input_digest != self._outline_input_digest(workspace)
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
        self._validate_section_checkpoints(workspace)
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
            compiled_sections = copy.deepcopy(plan["sections"])
            try:
                self._compile_wave_dependencies(compiled_sections, delivery_waves)
            except ProductPlanningError as exc:
                raise ProductPlanningError("product_workspace_corrupt") from exc
            if compiled_sections != plan["sections"]:
                raise ProductPlanningError("product_workspace_corrupt")
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
                and plan["planning_answers"] != workspace["answers"]
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
        else:
            raise ProductPlanningError("product_workspace_corrupt")
        if (
            row["purpose"] not in {"initial", "revision"}
            or (
                schema_version == "product_plan_question_set.v2"
                and (
                    row["purpose"] != "revision"
                    or target_section_id not in SECTION_IDS
                )
            )
            or type(row["questions"]) is not list
            or not 1 <= len(row["questions"]) <= 3
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
                or item["allow_custom"] is not True
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
                    or current["recommended"] is (index != 0)
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
                or row["purpose"] not in {"initial", "revision"}
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

    def _outline_input_digest(self, workspace: dict[str, Any]) -> str:
        return _digest(
            {
                "schema_version": "product_plan_outline_input.v1",
                "goal_digest": workspace["goal_digest"],
                "planning_answers": self._planning_answers(workspace),
                "model": workspace["model"],
                "planning_rules_version": PLANNING_RULES_VERSION,
                "prompt_version": PLANNING_PROMPT_VERSION,
            }
        )

    def _section_input_digest(
        self,
        workspace: dict[str, Any],
        outline: dict[str, Any],
        section_id: str,
        candidate_refs: list[str],
    ) -> str:
        return _digest(
            {
                "schema_version": "product_plan_section_draft_input.v1",
                "goal_digest": workspace["goal_digest"],
                "planning_answers": self._planning_answers(workspace),
                "model": workspace["model"],
                "planning_rules_version": PLANNING_RULES_VERSION,
                "prompt_version": PLANNING_PROMPT_VERSION,
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

    def _validate_stored_confirmation(self, value: Any, plan: Any) -> None:
        if value is None:
            return
        row = _stored_exact(
            value,
            {
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
            },
        )
        canonical = {key: item for key, item in row.items() if key != "receipt_digest"}
        if (
            type(plan) is not dict
            or row["schema_version"] != "product_plan_confirmation.v1"
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

    def _ensure_directory(self, path: Path) -> None:
        try:
            self._assert_no_symlink_components(path)
            if path.exists() or path.is_symlink():
                metadata = path.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                    raise ProductPlanningError("product_workspace_symlink_forbidden")
            else:
                path.mkdir(parents=True, mode=0o700)
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
            if stat.S_IMODE(metadata.st_mode) & 0o077:
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

    def _continue_initial_planning(
        self,
        workspace: dict[str, Any],
        catalog: dict[str, Any],
        cancel_check: Callable[[], bool] | None,
        phase_callback: Callable[[str], None] | None,
    ) -> dict[str, Any]:
        workspace["status"] = "planning"
        workspace["failure_code"] = None
        outline = workspace.get("outline")
        if outline is None:
            outline_input_digest = self._outline_input_digest(workspace)
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
        elif workspace["outline_input_digest"] != self._outline_input_digest(workspace):
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
        workspace["plan"] = plan
        workspace["status"] = "plan_review"
        workspace["failure_code"] = None
        workspace["updated_at"] = _now()
        with self._lock:
            self._save_workspace(workspace)
        return _ok(self._workspace_projection(workspace))

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
            if question is None or question_id in seen or row["source"] not in {"option", "custom"}:
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

    def _compile_section_drafts(
        self,
        plan_id: str,
        sections_raw: list[dict[str, Any]],
        requirement_map: dict[str, str],
        candidate_map: dict[str, dict[str, str]],
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
        return sections, delivery_waves

    def _build_plan(
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
        candidate_map: dict[str, dict[str, str]] = {}
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
            "planning_rules_version": PLANNING_RULES_VERSION,
            "prompt_version": PLANNING_PROMPT_VERSION,
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

    def _section_call(
        self,
        model: dict[str, Any],
        section_id: str,
        requirements: list[dict[str, str]],
        answers: list[dict[str, Any]],
        candidates: dict[str, dict[str, str]],
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
                    "gap_reason=''. Text limits are: section summary 1-500 characters; "
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
            or plan["schema_version"] != PLAN_SCHEMA_VERSION
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
            or plan["planning_rules_version"] != PLANNING_RULES_VERSION
            or plan["prompt_version"] != PLANNING_PROMPT_VERSION
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
        covered: set[str] = set()
        for section in plan["sections"]:
            row = _exact_dict(
                section, {"section_id", "summary", "work_items", "gaps"}
            )
            if (
                row["section_id"] not in SECTION_IDS
                or type(row["summary"]) is not str
                or type(row["work_items"]) is not list
                or type(row["gaps"]) is not list
                or not row["work_items"] and not row["gaps"]
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
        compiled_sections = copy.deepcopy(proposed["sections"])
        try:
            self._compile_wave_dependencies(
                compiled_sections,
                proposed_delivery_waves,
            )
        except ProductPlanningError as exc:
            raise ProductPlanningError("product_plan_diff_invalid") from exc
        if compiled_sections != proposed["sections"]:
            raise ProductPlanningError("product_plan_diff_invalid")
        if proposed["parent_plan_digest"] != current["canonical_digest"]:
            raise ProductPlanningError("product_plan_diff_invalid")
        if is_targeted:
            base_delivery_waves = row["base_delivery_waves"]
            if type(base_delivery_waves) is not dict:
                raise ProductPlanningError("product_plan_diff_invalid")
            current_sections = copy.deepcopy(current["sections"])
            self._compile_wave_dependencies(current_sections, base_delivery_waves)
            if current_sections != current["sections"]:
                raise ProductPlanningError("product_plan_diff_invalid")
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
