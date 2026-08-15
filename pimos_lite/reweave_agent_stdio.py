"""Narrow local-agent JSONL entry over the existing ReweaveAppService."""

from __future__ import annotations

import json
import re
import sys
from typing import Any, BinaryIO, TextIO

from pimos_lite.reweave_app_service import ReweaveAppService


AGENT_PROTOCOL_VERSION = "reweave_agent_jsonl.v2"
AGENT_ACTIONS = frozenset(
    {
        "bind_user_handoff",
        "list_reusable_product_capabilities",
        "get_confirmed_product_plan",
        "start_confirmed_product_candidate",
        "get_product_candidate_run",
        "get_product_candidate",
        "read_product_candidate_file",
    }
)
_REQUEST_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_MAX_REQUEST_BYTES = 1024 * 1024
_INTERNAL_CANDIDATE_FILES = frozenset({"manifest.json", "provenance.json"})


def _error(request_id: str | None, code: str) -> dict[str, Any]:
    return {
        "protocol": AGENT_PROTOCOL_VERSION,
        "id": request_id,
        "ok": False,
        "error": {"code": code, "message_key": code},
    }


def _candidate_projection(value: dict[str, Any]) -> dict[str, Any]:
    acceptance = value.get("acceptance")
    provenance = value.get("provenance")
    validation = value.get("validation")
    parameter_binding = (
        provenance.get("parameter_binding")
        if type(provenance) is dict
        else None
    )
    source_versions = sorted(
        {
            str(version_id)
            for receipt in (
                provenance.get("file_provenance", [])
                if type(provenance) is dict
                else []
            )
            if type(receipt) is dict
            for version_id in receipt.get("capsule_version_ids", [])
            if type(version_id) is str
        }
    )
    return {
        "schema_version": "agent_product_candidate.v1",
        "candidate_token": value.get("candidate_token"),
        "candidate_digest": value.get("candidate_digest"),
        "candidate_content_digest": value.get("candidate_content_digest"),
        "status": value.get("status"),
        "plan": {
            key: value.get("plan", {}).get(key)
            for key in ("plan_version", "plan_digest")
        },
        "entry": value.get("entry"),
        "files": [
            item
            for item in value.get("files", [])
            if type(item) is dict
            and item.get("path") not in _INTERNAL_CANDIDATE_FILES
        ],
        "file_changes": [
            item
            for item in value.get("file_changes", [])
            if type(item) is dict
            and item.get("path") not in _INTERNAL_CANDIDATE_FILES
        ],
        "acceptance": {
            "status": acceptance.get("status"),
            "runtime_operational": acceptance.get("runtime_operational"),
            "product_goal_conformance": acceptance.get(
                "product_goal_conformance"
            ),
            "cases": [
                {
                    key: case.get(key)
                    for key in (
                        "input",
                        "expected_output",
                        "actual_output",
                        "status",
                        "failure_code",
                    )
                }
                for case in acceptance.get("cases", [])
                if type(case) is dict
            ],
        }
        if type(acceptance) is dict
        else None,
        "validation": {
            "static": validation.get("static", {}).get("status"),
            "runtime": validation.get("runtime", {}).get("status"),
            "acceptance": validation.get("acceptance", {}).get("status"),
        }
        if type(validation) is dict
        else None,
        "formal_source_count": len(source_versions),
        "parameters": [
            {
                "name": item.get("input_field"),
                "value": item.get("value"),
                "source": item.get("source"),
            }
            for item in (
                parameter_binding.get("bindings", [])
                if type(parameter_binding) is dict
                else []
            )
            if type(item) is dict
        ],
        "permissions": value.get("permissions"),
    }


def _plan_projection(value: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: value.get(key)
        for key in (
            "schema_version",
            "status",
            "goal",
            "product_name",
            "plan_version",
            "requirements",
            "sections",
            "confirmation",
        )
    }
    acceptance = value.get("candidate_acceptance")
    if type(acceptance) is dict:
        result["candidate_acceptance"] = {
            key: acceptance.get(key)
            for key in ("confirmed", "confirmed_at", "source", "cases")
            if acceptance.get(key) is not None
        }
    return result


def _run_projection(value: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: value.get(key)
        for key in (
            "run_id",
            "status",
            "created_at",
            "started_at",
            "completed_at",
            "error",
        )
        if value.get(key) is not None
    }
    data = value.get("data")
    candidate = (
        data.get("data")
        if type(data) is dict
        and data.get("ok") is True
        and type(data.get("data")) is dict
        else None
    )
    if type(candidate) is dict:
        result["candidate"] = _candidate_projection(candidate)
    return result


def _capability_projection(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": value.get("schema_version"),
        "warehouse_revision": value.get("warehouse_revision"),
        "capabilities": [
            {
                key: item.get(key)
                for key in (
                    "display_name",
                    "capability_kind",
                    "identity_status",
                    "input_contract",
                    "output_contract",
                    "source",
                )
            }
            for item in value.get("capabilities", [])
            if type(item) is dict
        ],
    }


def _file_projection(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "candidate_token",
            "candidate_digest",
            "path",
            "sha256",
            "size_bytes",
            "encoding",
            "content",
            "text_diff",
        )
    }


def dispatch_agent_request(
    service: ReweaveAppService,
    request: Any,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = session if session is not None else {}
    request_id = request.get("id") if type(request) is dict else None
    if (
        type(request) is not dict
        or set(request) != {"protocol", "id", "action", "payload"}
        or type(request_id) is not str
        or _REQUEST_ID.fullmatch(request_id) is None
        or type(request.get("payload")) is not dict
    ):
        return _error(
            request_id if type(request_id) is str else None,
            "agent_request_invalid",
        )
    if request["protocol"] != AGENT_PROTOCOL_VERSION:
        return _error(request_id, "agent_protocol_version_invalid")
    action = request["action"]
    if type(action) is not str or action not in AGENT_ACTIONS:
        return _error(request_id, "agent_action_not_allowed")
    payload = request["payload"]
    if action == "bind_user_handoff":
        if (
            set(payload) != {"handoff_token"}
            or type(payload["handoff_token"]) is not str
        ):
            return _error(request_id, "agent_handoff_request_invalid")
        try:
            service._resolve_local_agent_handoff(payload["handoff_token"])
        except Exception as exc:
            code = getattr(exc, "code", None)
            return _error(
                request_id,
                code
                if type(code) is str
                and re.fullmatch(r"[a-z][a-z0-9_]{1,95}", code)
                else "agent_handoff_invalid",
            )
        session.clear()
        session.update(
            {
                "handoff_token": payload["handoff_token"],
                "run_ids": set(),
            }
        )
        return {
            "protocol": AGENT_PROTOCOL_VERSION,
            "id": request_id,
            "ok": True,
            "data": {"status": "bound"},
        }
    handoff_token = session.get("handoff_token")
    if type(handoff_token) is not str:
        return _error(request_id, "agent_session_unbound")
    try:
        binding = service._resolve_local_agent_handoff(handoff_token)
    except Exception as exc:
        code = getattr(exc, "code", None)
        return _error(
            request_id,
            code
            if type(code) is str
            and re.fullmatch(r"[a-z][a-z0-9_]{1,95}", code)
            else "agent_handoff_invalid",
        )
    expected_fields = {
        "list_reusable_product_capabilities": set(),
        "get_confirmed_product_plan": set(),
        "start_confirmed_product_candidate": set(),
        "get_product_candidate_run": {"run_id"},
        "get_product_candidate": {"candidate_token"},
        "read_product_candidate_file": {
            "candidate_token",
            "relative_path",
        },
    }[action]
    if set(payload) != expected_fields or any(
        type(payload[field]) is not str for field in expected_fields
    ):
        return _error(request_id, "agent_action_payload_invalid")
    if action == "list_reusable_product_capabilities":
        method_payload = {}
    elif action == "get_confirmed_product_plan":
        method_payload = {"plan_token": binding["plan_token"]}
    elif action == "start_confirmed_product_candidate":
        method_payload = {
            "plan_token": binding["plan_token"],
            "plan_digest": binding["plan_digest"],
            "acceptance_confirmation_digest": binding[
                "acceptance_confirmation_digest"
            ],
        }
    else:
        method_payload = payload
    if action == "get_product_candidate_run":
        if payload["run_id"] not in session["run_ids"]:
            return _error(request_id, "agent_candidate_run_not_in_scope")
    if action in {"get_product_candidate", "read_product_candidate_file"}:
        scoped = service.get_product_candidate(
            {"candidate_token": payload["candidate_token"]}
        )
        if scoped.get("ok") is not True:
            error = scoped.get("error")
            code = error.get("code") if type(error) is dict else None
            return _error(
                request_id,
                code if type(code) is str else "agent_action_failed",
            )
        if (
            scoped.get("data", {}).get("plan", {}).get("plan_digest")
            != binding["plan_digest"]
        ):
            return _error(request_id, "agent_candidate_not_in_scope")
    method = getattr(service, action)
    try:
        response = method(method_payload)
    except Exception:
        return _error(request_id, "agent_internal_error")
    if type(response) is not dict or type(response.get("ok")) is not bool:
        return _error(request_id, "agent_internal_error")
    if response["ok"] is not True:
        error = response.get("error")
        code = error.get("code") if type(error) is dict else None
        return _error(
            request_id,
            code if type(code) is str else "agent_action_failed",
        )
    data = response.get("data")
    if action == "start_confirmed_product_candidate":
        run_id = response.get("run_id")
        if type(run_id) is not str:
            return _error(request_id, "agent_internal_error")
        session["run_ids"].add(run_id)
        data = {
            "run_id": run_id,
            "status": response.get("status"),
        }
    elif action == "list_reusable_product_capabilities":
        data = _capability_projection(data)
    elif action == "get_confirmed_product_plan":
        data = _plan_projection(data)
    elif action == "get_product_candidate_run":
        candidate = (
            data.get("data", {}).get("data")
            if type(data) is dict
            and type(data.get("data")) is dict
            and data.get("data", {}).get("ok") is True
            else None
        )
        if (
            type(candidate) is dict
            and candidate.get("plan", {}).get("plan_digest")
            != binding["plan_digest"]
        ):
            return _error(request_id, "agent_candidate_not_in_scope")
        data = _run_projection(data)
    elif action == "get_product_candidate":
        data = _candidate_projection(data)
    elif action == "read_product_candidate_file":
        if (
            type(data) is dict
            and data.get("path") in _INTERNAL_CANDIDATE_FILES
        ):
            return _error(request_id, "agent_candidate_file_not_readable")
        data = _file_projection(data)
    return {
        "protocol": AGENT_PROTOCOL_VERSION,
        "id": request_id,
        "ok": True,
        "data": data,
    }


def serve_jsonl(
    service: ReweaveAppService,
    input_stream: BinaryIO | TextIO,
    output_stream: TextIO,
) -> None:
    session: dict[str, Any] = {}
    while True:
        raw = input_stream.readline(_MAX_REQUEST_BYTES + 1)
        if raw in {b"", ""}:
            break
        newline = b"\n" if isinstance(raw, bytes) else "\n"
        try:
            encoded = (
                raw
                if isinstance(raw, bytes)
                else raw.encode("utf-8", errors="strict")
            )
        except UnicodeError:
            encoded = b""
            response = _error(None, "agent_json_invalid")
        else:
            response = None
        if len(encoded) > _MAX_REQUEST_BYTES:
            response = _error(None, "agent_request_too_large")
        if response is not None and not raw.endswith(newline):
            while True:
                remainder = input_stream.readline(_MAX_REQUEST_BYTES + 1)
                if remainder in {b"", ""} or remainder.endswith(newline):
                    break
        if response is not None:
            line = ""
        else:
            try:
                line = encoded.decode("utf-8", errors="strict")
            except UnicodeError:
                response = _error(None, "agent_json_invalid")
                line = ""
        if not line.strip():
            if response is None:
                continue
        if response is None:
            try:
                request = json.loads(
                    line,
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(value)
                    ),
                )
            except (UnicodeError, ValueError, json.JSONDecodeError):
                response = _error(None, "agent_json_invalid")
            else:
                response = dispatch_agent_request(service, request, session)
        output_stream.write(
            json.dumps(
                response,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        )
        output_stream.flush()


def main() -> int:
    service = ReweaveAppService()
    try:
        serve_jsonl(service, sys.stdin.buffer, sys.stdout)
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
