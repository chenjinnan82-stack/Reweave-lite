"""User-authorized source evidence for one isolated computation proposal."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import threading
import uuid
from functools import wraps
from pathlib import Path, PurePosixPath
from typing import Any

from pimos_lite.reweave_canonical import canonical_json_digest
from pimos_lite.reweave_data_contract import (
    DataContractError,
    data_contract_accepts,
    normalize_capsule_contracts,
)
from pimos_lite.reweave_product_planner import (
    CAPABILITY_SOURCE_FUNCTION_ABI_V3,
    CAPABILITY_SOURCE_PROPOSAL_OUTPUT_V2,
    CAPABILITY_SOURCE_PROPOSAL_REQUEST_V5,
    ProductPlanner,
    ProductPlanningError,
)


SOURCE_DERIVATION_AUTHORIZATION_VERSION = (
    "source_derived_computation_authorization.v1"
)
SOURCE_DERIVATION_REQUEST_V1 = (
    "source_derived_capability_source_proposal_request.v1"
)
SOURCE_DERIVATION_REQUEST_VERSION = (
    "source_derived_capability_source_proposal_request.v2"
)
SOURCE_DERIVATION_PROMPT_V1 = (
    "source_derived_capability_source_proposal_prompt.v1"
)
SOURCE_DERIVATION_PROMPT_VERSION = (
    "source_derived_capability_source_proposal_prompt.v2"
)
MAX_EVIDENCE_FILES = 4
MAX_EVIDENCE_FILE_BYTES = 128 * 1024
MAX_EVIDENCE_BYTES = 256 * 1024
MAX_ACCEPTANCE_CASES = 16
SOURCE_DERIVED_RUN_VERSION = "source_derived_computation_run.v1"
SOURCE_DERIVED_RUN_EVENT_VERSION = (
    "source_derived_computation_run_event.v1"
)
SOURCE_DERIVED_RUN_STATUS_VERSION = (
    "source_derived_computation_run_status.v1"
)
SOURCE_DERIVED_STATE_DIRECTORY = "source_derived_computations"
SOURCE_DERIVED_RUN_STATUSES = frozenset(
    {"pending", "running", "review_required", "failed", "cancelled"}
)
SOURCE_DERIVED_RUN_STAGES = (
    "source_proposal",
    "intake",
    "security",
    "runtime",
    "supervision",
)
MAX_SOURCE_DERIVED_STATE_BYTES = 512 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID = re.compile(r"run_[0-9a-f]{32}\Z")
_EVENT_FILE = re.compile(
    r"event_([0-9]{6})_([0-9a-f]{64})\.json\Z"
)
_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,199}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{1,95}\Z")
_SAFE_SUFFIXES = frozenset({".js", ".jsx", ".mjs", ".ts", ".tsx"})
_SECRET = re.compile(
    r"(?is)(?:api[_-]?key|secret|token|password|access[_-]?key|secret[_-]?key)"
    r"\s*['\"]?\s*[:=]\s*(?:['\"][^'\"]+['\"]|[^\s<;]+)|"
    r"Bearer\s+[A-Za-z0-9\-._~+/]+=*|\bsk-[A-Za-z0-9]{8,}\b|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
_STATE_LOCK = threading.RLock()


class SourceDerivationError(ValueError):
    """A bounded, non-sensitive source-derivation error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _serialized_state(function: Any) -> Any:
    @wraps(function)
    def locked(*args: Any, **kwargs: Any) -> Any:
        # ponytail: state-root ownership makes one process lock sufficient.
        with _STATE_LOCK:
            return function(*args, **kwargs)

    return locked


def _canonical_bytes(value: Any) -> bytes:
    try:
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
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise SourceDerivationError("source_derivation_state_invalid") from exc


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_key")
        value[key] = item
    return value


def _strict_json(raw: bytes) -> Any:
    text = raw.decode("utf-8", errors="strict")
    value = json.loads(
        text,
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=lambda _value: (_ for _ in ()).throw(
            ValueError("non_finite")
        ),
    )
    if _canonical_bytes(value) != raw:
        raise ValueError("non_canonical")
    return value


def _ensure_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
            metadata.st_mode
        ):
            raise SourceDerivationError("source_derivation_state_conflict")
        if os.name == "posix":
            os.chmod(path, 0o700)
    except SourceDerivationError:
        raise
    except OSError as exc:
        raise SourceDerivationError(
            "source_derivation_state_unavailable"
        ) from exc


def _assert_safe_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    for component in reversed((absolute, *absolute.parents)):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise SourceDerivationError(
                "source_derivation_state_unavailable"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise SourceDerivationError("source_derivation_state_conflict")


def _read_json_file(path: Path) -> Any:
    _assert_safe_components(path.parent)
    descriptor = -1
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise SourceDerivationError(
                "source_derivation_state_conflict"
            )
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or (before.st_dev, before.st_ino)
            != (after.st_dev, after.st_ino)
            or after.st_size > MAX_SOURCE_DERIVED_STATE_BYTES
            or (
                os.name == "posix"
                and stat.S_IMODE(after.st_mode) != 0o600
            )
        ):
            raise SourceDerivationError(
                "source_derivation_state_conflict"
            )
        raw = os.read(descriptor, MAX_SOURCE_DERIVED_STATE_BYTES + 1)
        if len(raw) != after.st_size:
            raise SourceDerivationError(
                "source_derivation_state_conflict"
            )
        return _strict_json(raw)
    except SourceDerivationError:
        raise
    except (
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise SourceDerivationError(
            "source_derivation_state_conflict"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_private_bytes(path: Path, maximum: int, code: str) -> bytes:
    _assert_safe_components(path.parent)
    descriptor = -1
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise SourceDerivationError(code)
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (before.st_dev, before.st_ino)
            != (opened.st_dev, opened.st_ino)
            or not 0 <= opened.st_size <= maximum
            or (
                os.name == "posix"
                and stat.S_IMODE(opened.st_mode) != 0o600
            )
        ):
            raise SourceDerivationError(code)
        remaining = opened.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise SourceDerivationError(code)
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise SourceDerivationError(code)
        return b"".join(chunks)
    except SourceDerivationError:
        raise
    except OSError as exc:
        raise SourceDerivationError(code) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_immutable_bytes(path: Path, data: bytes, code: str) -> None:
    _ensure_directory(path.parent)
    _assert_safe_components(path.parent)
    if path.exists() or path.is_symlink():
        if _read_private_bytes(path, len(data), code) != data:
            raise SourceDerivationError(code)
        return
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("write_incomplete")
            view = view[written:]
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _read_private_bytes(path, len(data), code) != data:
                raise SourceDerivationError(code)
            return
        temporary_metadata = temporary.lstat()
        published_metadata = path.lstat()
        if (
            stat.S_ISLNK(published_metadata.st_mode)
            or not stat.S_ISREG(published_metadata.st_mode)
            or (
                temporary_metadata.st_dev,
                temporary_metadata.st_ino,
            )
            != (
                published_metadata.st_dev,
                published_metadata.st_ino,
            )
        ):
            raise SourceDerivationError(code)
        temporary.unlink()
        if os.name == "posix":
            directory = os.open(
                path.parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except SourceDerivationError:
        raise
    except OSError as exc:
        raise SourceDerivationError(
            "source_derivation_state_unavailable"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            if temporary.exists() and not temporary.is_symlink():
                temporary.unlink()
        except OSError:
            pass


def _write_immutable(path: Path, value: Any) -> None:
    payload = _canonical_bytes(value)
    if len(payload) > MAX_SOURCE_DERIVED_STATE_BYTES:
        raise SourceDerivationError("source_derivation_state_invalid")
    _ensure_directory(path.parent)
    _assert_safe_components(path.parent)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("write_incomplete")
            view = view[written:]
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _read_json_file(path) != value:
                raise SourceDerivationError(
                    "source_derivation_state_conflict"
                )
            return
        temporary.unlink()
        if os.name == "posix":
            directory = os.open(
                path.parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except SourceDerivationError:
        raise
    except OSError as exc:
        raise SourceDerivationError(
            "source_derivation_state_unavailable"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            if temporary.exists() and not temporary.is_symlink():
                temporary.unlink()
        except OSError:
            pass


def _exact(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise SourceDerivationError(code)
    return value


def _safe_relative(value: Any) -> str:
    try:
        encoded = value.encode("utf-8") if type(value) is str else b""
    except UnicodeEncodeError as exc:
        raise SourceDerivationError(
            "source_derivation_evidence_invalid"
        ) from exc
    if (
        type(value) is not str
        or not value
        or len(encoded) > 1024
        or "\\" in value
    ):
        raise SourceDerivationError("source_derivation_evidence_invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.suffix.lower() not in _SAFE_SUFFIXES
    ):
        raise SourceDerivationError("source_derivation_evidence_invalid")
    return path.as_posix()


def _evidence_rows(evidence: Any, *, include_content: bool) -> list[dict[str, Any]]:
    if (
        type(evidence) is not list
        or not 1 <= len(evidence) <= MAX_EVIDENCE_FILES
    ):
        raise SourceDerivationError("source_derivation_evidence_invalid")
    rows: list[dict[str, Any]] = []
    total = 0
    seen: set[str] = set()
    for raw in evidence:
        required = {"logical_path", "sha256", "size_bytes"}
        if include_content:
            required.add("content")
        row = _exact(
            raw,
            required,
            "source_derivation_evidence_invalid",
        )
        logical_path = _safe_relative(row["logical_path"])
        digest = row["sha256"]
        size = row["size_bytes"]
        if (
            logical_path in seen
            or type(digest) is not str
            or _DIGEST.fullmatch(digest) is None
            or type(size) is not int
            or not 1 <= size <= MAX_EVIDENCE_FILE_BYTES
        ):
            raise SourceDerivationError("source_derivation_evidence_invalid")
        normalized = {
            "logical_path": logical_path,
            "sha256": digest,
            "size_bytes": size,
        }
        if include_content:
            content = row["content"]
            if type(content) is not str:
                raise SourceDerivationError(
                    "source_derivation_evidence_invalid"
                )
            try:
                encoded = content.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise SourceDerivationError(
                    "source_derivation_evidence_invalid"
                ) from exc
            if (
                len(encoded) != size
                or hashlib.sha256(encoded).hexdigest() != digest
                or _SECRET.search(content) is not None
            ):
                raise SourceDerivationError(
                    "source_derivation_evidence_invalid"
                )
            normalized["content"] = content
        rows.append(normalized)
        seen.add(logical_path)
        total += size
    if total > MAX_EVIDENCE_BYTES:
        raise SourceDerivationError("source_derivation_evidence_invalid")
    rows.sort(key=lambda item: item["logical_path"].encode("utf-8"))
    return rows


def _target(
    *,
    input_contract: Any,
    output_contract: Any,
    error_contract: Any,
    result_field: Any,
    acceptance_cases: Any,
) -> dict[str, Any]:
    try:
        normalized_input, normalized_output, normalized_error = (
            normalize_capsule_contracts(
                "computation",
                input_contract,
                output_contract,
                error_contract,
            )
        )
    except DataContractError as exc:
        raise SourceDerivationError(
            "source_derivation_contract_invalid"
        ) from exc
    properties = normalized_input["properties"]
    output_properties = normalized_output["properties"]
    if (
        len(properties) != 1
        or normalized_input["required"] != list(properties)
        or type(result_field) is not str
        or set(output_properties) != {result_field}
        or normalized_output["required"] != [result_field]
    ):
        raise SourceDerivationError("source_derivation_contract_invalid")
    input_field, input_value = next(iter(properties.items()))
    result_value = output_properties[result_field]
    if (
        set(input_value) != {"type", "min_length", "max_length"}
        or input_value["type"] != "string"
        or type(input_value["min_length"]) is not int
        or type(input_value["max_length"]) is not int
        or not 0
        <= input_value["min_length"]
        <= input_value["max_length"]
        <= 10_000
        or set(result_value)
        != {"type", "min_length", "max_length", "enum"}
        or result_value["type"] != "string"
        or type(result_value["enum"]) is not list
        or not 2 <= len(result_value["enum"]) <= 100
        or any(type(item) is not str or not item for item in result_value["enum"])
        or len(set(result_value["enum"])) != len(result_value["enum"])
    ):
        raise SourceDerivationError("source_derivation_contract_invalid")
    result_enum = sorted(
        result_value["enum"],
        key=lambda item: item.encode("utf-8"),
    )
    normalized_output = copy.deepcopy(normalized_output)
    normalized_output["properties"][result_field]["enum"] = result_enum
    if (
        type(acceptance_cases) is not list
        or not 1 <= len(acceptance_cases) <= MAX_ACCEPTANCE_CASES
    ):
        raise SourceDerivationError("source_derivation_acceptance_invalid")
    cases: list[dict[str, Any]] = []
    for raw in acceptance_cases:
        row = _exact(
            raw,
            {"input", "expected_output"},
            "source_derivation_acceptance_invalid",
        )
        if not data_contract_accepts(
            normalized_input, row["input"]
        ) or not data_contract_accepts(
            normalized_output, row["expected_output"]
        ):
            raise SourceDerivationError(
                "source_derivation_acceptance_invalid"
            )
        cases.append(copy.deepcopy(row))
    return {
        "input_contract": normalized_input,
        "output_contract": normalized_output,
        "error_contract": normalized_error,
        "input_field": input_field,
        "result_field": result_field,
        "result_enum": result_enum,
        "acceptance_cases": cases,
    }


def build_source_derived_authorization(
    *,
    source_snapshot_sha256: str,
    project_graph_digest: str,
    evidence: list[dict[str, Any]],
    behavior_intent: str,
    input_contract: dict[str, Any],
    output_contract: dict[str, Any],
    error_contract: dict[str, Any],
    result_field: str,
    acceptance_cases: list[dict[str, Any]],
    source_proposal_model: dict[str, str],
    warehouse_revision: int,
    catalog_digest: str,
    authorized_at: str,
) -> dict[str, Any]:
    """Freeze source hashes and a user-confirmed bounded computation target."""

    if (
        type(source_snapshot_sha256) is not str
        or _DIGEST.fullmatch(source_snapshot_sha256) is None
        or type(project_graph_digest) is not str
        or _DIGEST.fullmatch(project_graph_digest) is None
        or type(behavior_intent) is not str
        or not behavior_intent.strip()
        or len(behavior_intent.encode("utf-8")) > 2_000
        or type(source_proposal_model) is not dict
        or set(source_proposal_model) != {"name", "digest"}
        or _MODEL_NAME.fullmatch(str(source_proposal_model.get("name") or ""))
        is None
        or _DIGEST.fullmatch(
            str(source_proposal_model.get("digest") or "")
        )
        is None
        or type(warehouse_revision) is not int
        or warehouse_revision < 0
        or type(catalog_digest) is not str
        or _DIGEST.fullmatch(catalog_digest) is None
        or type(authorized_at) is not str
        or not authorized_at
    ):
        raise SourceDerivationError("source_derivation_authorization_invalid")
    target = _target(
        input_contract=input_contract,
        output_contract=output_contract,
        error_contract=error_contract,
        result_field=result_field,
        acceptance_cases=acceptance_cases,
    )
    evidence_rows = _evidence_rows(evidence, include_content=False)
    body = {
        "schema_version": SOURCE_DERIVATION_AUTHORIZATION_VERSION,
        "source_kind": "react_vite",
        "source_snapshot_sha256": source_snapshot_sha256,
        "project_graph_digest": project_graph_digest,
        "evidence": evidence_rows,
        "evidence_digest": canonical_json_digest(evidence_rows),
        "behavior_intent": behavior_intent.strip(),
        **target,
        "adapter_contract_version": "computation_adapter.v5",
        "capture_mapping_schema": "computation_capture_mapping.v5",
        "proof_schema": "source_graph_proof.v3",
        "source_proposal_model": copy.deepcopy(source_proposal_model),
        "warehouse_revision": warehouse_revision,
        "catalog_digest": catalog_digest,
        "authorization_source": "user_confirmed_source_derivation",
        "authorized_at": authorized_at,
    }
    return {
        **body,
        "authorization_digest": canonical_json_digest(body),
    }


def build_source_derived_request(
    authorization: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    request_version: str = SOURCE_DERIVATION_REQUEST_VERSION,
) -> dict[str, Any]:
    """Build the model-safe request after rechecking the frozen source bytes."""

    if request_version not in {
        SOURCE_DERIVATION_REQUEST_V1,
        SOURCE_DERIVATION_REQUEST_VERSION,
    }:
        raise SourceDerivationError("source_derivation_request_invalid")
    row = validate_source_derived_authorization(authorization)
    evidence_rows = _evidence_rows(evidence, include_content=True)
    evidence_identity = [
        {key: item[key] for key in ("logical_path", "sha256", "size_bytes")}
        for item in evidence_rows
    ]
    if (
        evidence_identity != row["evidence"]
        or canonical_json_digest(evidence_identity) != row["evidence_digest"]
    ):
        raise SourceDerivationError("source_derivation_evidence_stale")
    input_contract = row["input_contract"]
    input_field = row["input_field"]
    result_field = row["result_field"]
    result_enum = row["result_enum"]
    source_function = {
        "schema_version": CAPABILITY_SOURCE_FUNCTION_ABI_V3,
        "module_relpath": "capability.js",
        "export_name": "compute",
        "parameters": [
            {
                "position": 0,
                "parameter_name": "arg0",
                "input_field": input_field,
                "contract": copy.deepcopy(
                    input_contract["properties"][input_field]
                ),
            }
        ],
        "return_contract": copy.deepcopy(
            row["output_contract"]["properties"][result_field]
        ),
    }
    safe_input = {
        "source_function": source_function,
        "adapter_projection": {
            "contract_version": "computation_adapter.v5",
            "capture_mapping_schema": "computation_capture_mapping.v5",
            "proof_schema": "source_graph_proof.v3",
            "result_field": result_field,
            "result_enum": copy.deepcopy(result_enum),
            "passthrough_fields": [],
        },
        "user_behavior_intent": row["behavior_intent"],
        "user_acceptance_examples": copy.deepcopy(row["acceptance_cases"]),
        "authorized_source_evidence": evidence_rows,
        "witness_requirements": {
            "count": len(result_enum),
            "expected_scalar_results": copy.deepcopy(result_enum),
            "unique_inputs": True,
        },
    }
    prompt_version = (
        SOURCE_DERIVATION_PROMPT_V1
        if request_version == SOURCE_DERIVATION_REQUEST_V1
        else SOURCE_DERIVATION_PROMPT_VERSION
    )
    scalar_rule = (
        ""
        if request_version == SOURCE_DERIVATION_REQUEST_V1
        else (
            " Every return statement must return one allowed result_enum "
            "string scalar directly. Never return an object such as "
            "{result_field: value}; computation_adapter.v5 performs that "
            "wrapping after proof."
        )
    )
    prompt = (
        "Derive one deterministic pure JavaScript computation proposal from "
        "the user-authorized source evidence. The target contract and examples "
        "are authoritative; source evidence is context and must not widen the "
        "target. Implement exactly export function compute(arg0). The function "
        "may only use direct arg0.includes(\"fixed non-empty literal\"), boolean "
        "&&, ||, !, conditional branches, and scalar enum returns."
        + scalar_rule
        + " Do not copy dependencies, objects, arrays, regular expressions, "
        "other string methods, environment access, network, filesystem, time, "
        "randomness, or project state. Return exactly one JSON object matching "
        "FORMAT_SCHEMA with no Markdown or explanation.\nREQUEST_JSON:\n"
        + json.dumps(
            safe_input,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    body = {
        "schema_version": request_version,
        "formal_binding": {
            "authorization_digest": row["authorization_digest"],
            "source_snapshot_sha256": row["source_snapshot_sha256"],
            "project_graph_digest": row["project_graph_digest"],
            "evidence_digest": row["evidence_digest"],
            "warehouse_revision": row["warehouse_revision"],
            "catalog_digest": row["catalog_digest"],
            "source_proposal_model": copy.deepcopy(
                row["source_proposal_model"]
            ),
            "prompt_version": prompt_version,
            "output_protocol_version": CAPABILITY_SOURCE_PROPOSAL_OUTPUT_V2,
            "source_abi_digest": canonical_json_digest(source_function),
        },
        "model_safe_input": safe_input,
        "prompt": prompt,
        "format_schema": ProductPlanner._capability_source_proposal_format_schema_v2(
            input_contract,
            result_enum,
        ),
        "stream": False,
    }
    return {**body, "request_digest": canonical_json_digest(body)}


def validate_source_derived_authorization(
    value: Any,
) -> dict[str, Any]:
    try:
        row = _exact(
            value,
            {
                "schema_version",
                "source_kind",
                "source_snapshot_sha256",
                "project_graph_digest",
                "evidence",
                "evidence_digest",
                "behavior_intent",
                "input_contract",
                "output_contract",
                "error_contract",
                "input_field",
                "result_field",
                "result_enum",
                "acceptance_cases",
                "adapter_contract_version",
                "capture_mapping_schema",
                "proof_schema",
                "source_proposal_model",
                "warehouse_revision",
                "catalog_digest",
                "authorization_source",
                "authorized_at",
                "authorization_digest",
            },
            "source_derivation_authorization_invalid",
        )
        body = {
            key: copy.deepcopy(item)
            for key, item in row.items()
            if key != "authorization_digest"
        }
        rebuilt = build_source_derived_authorization(
            source_snapshot_sha256=row["source_snapshot_sha256"],
            project_graph_digest=row["project_graph_digest"],
            evidence=row["evidence"],
            behavior_intent=row["behavior_intent"],
            input_contract=row["input_contract"],
            output_contract=row["output_contract"],
            error_contract=row["error_contract"],
            result_field=row["result_field"],
            acceptance_cases=row["acceptance_cases"],
            source_proposal_model=row["source_proposal_model"],
            warehouse_revision=row["warehouse_revision"],
            catalog_digest=row["catalog_digest"],
            authorized_at=row["authorized_at"],
        )
        if (
            row["schema_version"] != SOURCE_DERIVATION_AUTHORIZATION_VERSION
            or row["source_kind"] != "react_vite"
            or row["adapter_contract_version"] != "computation_adapter.v5"
            or row["capture_mapping_schema"] != "computation_capture_mapping.v5"
            or row["proof_schema"] != "source_graph_proof.v3"
            or row["authorization_source"]
            != "user_confirmed_source_derivation"
            or row["authorization_digest"] != canonical_json_digest(body)
            or rebuilt != row
        ):
            raise SourceDerivationError(
                "source_derivation_authorization_invalid"
            )
    except SourceDerivationError:
        raise
    except (KeyError, TypeError, UnicodeError, ValueError) as exc:
        raise SourceDerivationError(
            "source_derivation_authorization_invalid"
        ) from exc
    return copy.deepcopy(row)


def validate_source_derived_response(
    value: Any,
    request: dict[str, Any],
    authorization: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reuse the formal v5 output validator without creating a second parser."""

    request_version = (
        request.get("schema_version")
        if type(request) is dict
        else None
    )
    if (
        request_version
        not in {
            SOURCE_DERIVATION_REQUEST_V1,
            SOURCE_DERIVATION_REQUEST_VERSION,
        }
        or request
        != build_source_derived_request(
            authorization,
            evidence,
            request_version=request_version,
        )
    ):
        raise SourceDerivationError("source_derivation_response_invalid")
    compatible = copy.deepcopy(request)
    compatible["schema_version"] = CAPABILITY_SOURCE_PROPOSAL_REQUEST_V5
    try:
        return ProductPlanner.validate_capability_source_proposal_response(
            value,
            compatible,
        )
    except ProductPlanningError as exc:
        raise SourceDerivationError(
            "source_derivation_response_invalid"
        ) from exc


def _is_reparse_point(metadata: os.stat_result) -> bool:
    return bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _descriptor_relative_reads_supported() -> bool:
    return (
        hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in getattr(os, "supports_dir_fd", set())
        and os.stat in getattr(os, "supports_dir_fd", set())
        and os.stat in getattr(os, "supports_follow_symlinks", set())
    )


def _read_evidence_by_descriptor(root: Path, logical_path: str) -> bytes:
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
    )
    absolute = Path(os.path.abspath(root))
    current = os.open(absolute.anchor, directory_flags)
    descriptor = -1
    try:
        for part in (
            *absolute.parts[1:],
            *PurePosixPath(logical_path).parts[:-1],
        ):
            child = os.open(
                part,
                directory_flags,
                dir_fd=current,
            )
            details = os.fstat(child)
            if not stat.S_ISDIR(details.st_mode):
                os.close(child)
                raise SourceDerivationError(
                    "source_derivation_evidence_invalid"
                )
            os.close(current)
            current = child
        name = PurePosixPath(logical_path).name
        descriptor = os.open(name, file_flags, dir_fd=current)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or not 1 <= before.st_size <= MAX_EVIDENCE_FILE_BYTES
        ):
            raise SourceDerivationError(
                "source_derivation_evidence_invalid"
            )
        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                raise SourceDerivationError(
                    "source_derivation_evidence_invalid"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        path_after = os.stat(
            name,
            dir_fd=current,
            follow_symlinks=False,
        )
        stable = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        if (
            not stat.S_ISREG(path_after.st_mode)
            or stable(before) != stable(after)
            or stable(after) != stable(path_after)
        ):
            raise SourceDerivationError(
                "source_derivation_evidence_invalid"
            )
        return b"".join(chunks)
    except SourceDerivationError:
        raise
    except OSError as exc:
        raise SourceDerivationError(
            "source_derivation_evidence_invalid"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(current)


def read_source_derived_evidence(
    source_root: str | Path,
    source_relpath: str,
) -> list[dict[str, Any]]:
    """Read one authorized JS/TS evidence file without following links."""

    logical_path = _safe_relative(source_relpath)
    root = Path(source_root)
    if _descriptor_relative_reads_supported():
        raw = _read_evidence_by_descriptor(root, logical_path)
        try:
            content = raw.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise SourceDerivationError(
                "source_derivation_evidence_invalid"
            ) from exc
        return _evidence_rows(
            [
                {
                    "logical_path": logical_path,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size_bytes": len(raw),
                    "content": content,
                }
            ],
            include_content=True,
        )
    descriptor = -1
    try:
        root_metadata = root.lstat()
        if (
            stat.S_ISLNK(root_metadata.st_mode)
            or _is_reparse_point(root_metadata)
            or not stat.S_ISDIR(root_metadata.st_mode)
        ):
            raise SourceDerivationError(
                "source_derivation_evidence_invalid"
            )
        current = root
        for part in PurePosixPath(logical_path).parts:
            current = current / part
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode) or _is_reparse_point(
                metadata
            ):
                raise SourceDerivationError(
                    "source_derivation_evidence_invalid"
                )
        before = current.lstat()
        if (
            _is_reparse_point(before)
            or not stat.S_ISREG(before.st_mode)
            or not 1 <= before.st_size <= MAX_EVIDENCE_FILE_BYTES
        ):
            raise SourceDerivationError(
                "source_derivation_evidence_invalid"
            )
        descriptor = os.open(
            current,
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        after = os.fstat(descriptor)
        if (
            _is_reparse_point(after)
            or not stat.S_ISREG(after.st_mode)
            or (before.st_dev, before.st_ino)
            != (after.st_dev, after.st_ino)
            or after.st_size != before.st_size
        ):
            raise SourceDerivationError(
                "source_derivation_evidence_invalid"
            )
        raw = os.read(descriptor, MAX_EVIDENCE_FILE_BYTES + 1)
        if len(raw) != after.st_size:
            raise SourceDerivationError(
                "source_derivation_evidence_invalid"
            )
        content = raw.decode("utf-8", errors="strict")
    except SourceDerivationError:
        raise
    except (OSError, UnicodeError) as exc:
        raise SourceDerivationError(
            "source_derivation_evidence_invalid"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return _evidence_rows(
        [
            {
                "logical_path": logical_path,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
                "content": content,
            }
        ],
        include_content=True,
    )


def source_derived_project_graph_digest(
    evidence: list[dict[str, Any]],
) -> str:
    rows = _evidence_rows(evidence, include_content=True)
    identities = [
        {key: row[key] for key in ("logical_path", "sha256", "size_bytes")}
        for row in rows
    ]
    if len(identities) != 1:
        raise SourceDerivationError("source_derivation_evidence_invalid")
    return canonical_json_digest(
        {"entry": identities[0]["logical_path"], "evidence": identities}
    )


def source_derived_authorization_binding_digest(
    authorization: dict[str, Any],
) -> str:
    row = validate_source_derived_authorization(authorization)
    return canonical_json_digest(
        {
            key: value
            for key, value in row.items()
            if key not in {"authorized_at", "authorization_digest"}
        }
    )


def _source_derived_user_request_digest(
    authorization: dict[str, Any],
    source_root_id: str,
    source_relpath: str,
) -> str:
    row = validate_source_derived_authorization(authorization)
    return canonical_json_digest(
        {
            "source_root_id": source_root_id,
            "source_relpath": source_relpath,
            "behavior_intent": row["behavior_intent"],
            "input_contract": row["input_contract"],
            "output_contract": row["output_contract"],
            "error_contract": row["error_contract"],
            "result_field": row["result_field"],
            "acceptance_cases": row["acceptance_cases"],
        }
    )


def source_derived_run_paths(
    state_root: str | Path,
    authorization_digest: str,
) -> dict[str, Path]:
    if _DIGEST.fullmatch(str(authorization_digest)) is None:
        raise SourceDerivationError("source_derivation_run_not_found")
    run_dir = (
        Path(state_root)
        / SOURCE_DERIVED_STATE_DIRECTORY
        / authorization_digest
    )
    _assert_safe_components(run_dir.parent)
    return {
        "root": run_dir.parent,
        "run_dir": run_dir,
        "authorization": run_dir / "authorization.json",
        "run": run_dir / "run.json",
        "events": run_dir / "events",
        "source_dir": run_dir / "source",
        "source_file": run_dir / "source" / "capability.js",
        "validation_dir": run_dir / "validation",
        "validation_database": (
            run_dir / "validation" / "capsule_warehouse.sqlite3"
        ),
    }


def _validate_model_identity(value: Any) -> dict[str, Any]:
    row = _exact(
        value,
        {"name", "digest", "parameter_count", "parameter_size"},
        "source_derivation_run_conflict",
    )
    if (
        _MODEL_NAME.fullmatch(str(row["name"])) is None
        or _DIGEST.fullmatch(str(row["digest"])) is None
        or type(row["parameter_count"]) is not int
        or row["parameter_count"] <= 0
        or type(row["parameter_size"]) is not str
        or not row["parameter_size"]
        or len(row["parameter_size"].encode("utf-8")) > 128
    ):
        raise SourceDerivationError("source_derivation_run_conflict")
    return copy.deepcopy(row)


def _validate_supervision_model(value: Any) -> dict[str, str]:
    row = _exact(
        value,
        {"name", "digest"},
        "source_derivation_run_conflict",
    )
    if (
        _MODEL_NAME.fullmatch(str(row["name"])) is None
        or _DIGEST.fullmatch(str(row["digest"])) is None
    ):
        raise SourceDerivationError("source_derivation_run_conflict")
    return copy.deepcopy(row)


def _validate_run_identity(
    authorization: dict[str, Any],
    value: Any,
) -> dict[str, Any]:
    row = _exact(
        value,
        {
            "schema_version",
            "run_id",
            "authorization_digest",
            "authorization_binding_digest",
            "user_request_digest",
            "request_digest",
            "source_root_id",
            "source_relpath",
            "source_snapshot_sha256",
            "project_graph_digest",
            "warehouse_revision",
            "catalog_digest",
            "source_proposal_model",
            "supervision_model",
            "attempt_count",
            "created_at",
            "canonical_digest",
        },
        "source_derivation_run_conflict",
    )
    body = {
        key: copy.deepcopy(item)
        for key, item in row.items()
        if key != "canonical_digest"
    }
    source_model = _validate_model_identity(row["source_proposal_model"])
    supervisor = _validate_supervision_model(row["supervision_model"])
    if (
        row["schema_version"] != SOURCE_DERIVED_RUN_VERSION
        or _RUN_ID.fullmatch(str(row["run_id"])) is None
        or row["authorization_digest"]
        != authorization["authorization_digest"]
        or row["authorization_binding_digest"]
        != source_derived_authorization_binding_digest(authorization)
        or row["user_request_digest"]
        != _source_derived_user_request_digest(
            authorization,
            row["source_root_id"],
            row["source_relpath"],
        )
        or _DIGEST.fullmatch(str(row["request_digest"])) is None
        or _SAFE_ID.fullmatch(str(row["source_root_id"])) is None
        or row["source_relpath"]
        != authorization["evidence"][0]["logical_path"]
        or row["source_snapshot_sha256"]
        != authorization["source_snapshot_sha256"]
        or row["project_graph_digest"]
        != authorization["project_graph_digest"]
        or row["warehouse_revision"] != authorization["warehouse_revision"]
        or row["catalog_digest"] != authorization["catalog_digest"]
        or {
            "name": source_model["name"],
            "digest": source_model["digest"],
        }
        != authorization["source_proposal_model"]
        or supervisor != row["supervision_model"]
        or row["attempt_count"] != 1
        or type(row["created_at"]) is not str
        or not row["created_at"]
        or row["canonical_digest"] != canonical_json_digest(body)
    ):
        raise SourceDerivationError("source_derivation_run_conflict")
    return copy.deepcopy(row)


def _validate_event_evidence(value: Any) -> dict[str, Any]:
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
        "review_id",
        "canonical_hash",
    }
    if type(value) is not dict or set(value) - allowed:
        raise SourceDerivationError("source_derivation_run_event_invalid")
    row = copy.deepcopy(value)
    for key, item in row.items():
        if key == "source_relpath":
            if item != "source/capability.js":
                raise SourceDerivationError(
                    "source_derivation_run_event_invalid"
                )
        elif key == "review_id":
            if (
                type(item) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{1,160}", item) is None
            ):
                raise SourceDerivationError(
                    "source_derivation_run_event_invalid"
                )
        elif _DIGEST.fullmatch(str(item)) is None:
            raise SourceDerivationError(
                "source_derivation_run_event_invalid"
            )
    return row


def _validate_run_event(
    value: Any,
    identity: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    row = _exact(
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
        "source_derivation_run_event_invalid",
    )
    body = {
        key: copy.deepcopy(item)
        for key, item in row.items()
        if key != "canonical_digest"
    }
    evidence = _validate_event_evidence(row["evidence"])
    if (
        row["schema_version"] != SOURCE_DERIVED_RUN_EVENT_VERSION
        or row["run_digest"] != identity["canonical_digest"]
        or type(row["sequence"]) is not int
        or row["sequence"]
        != (1 if previous is None else previous["sequence"] + 1)
        or row["previous_event_digest"]
        != (
            None if previous is None else previous["canonical_digest"]
        )
        or row["status"] not in SOURCE_DERIVED_RUN_STATUSES
        or row["stage"] not in SOURCE_DERIVED_RUN_STAGES
        or evidence != row["evidence"]
        or (
            row["error_code"] is not None
            and _ERROR_CODE.fullmatch(str(row["error_code"])) is None
        )
        or type(row["created_at"]) is not str
        or not row["created_at"]
        or row["canonical_digest"] != canonical_json_digest(body)
    ):
        raise SourceDerivationError(
            "source_derivation_run_event_invalid"
        )
    if previous is None:
        if (
            row["status"] != "pending"
            or row["stage"] != "source_proposal"
            or row["error_code"] is not None
            or row["evidence"]
        ):
            raise SourceDerivationError(
                "source_derivation_run_event_invalid"
            )
        return copy.deepcopy(row)
    previous_index = SOURCE_DERIVED_RUN_STAGES.index(previous["stage"])
    current_index = SOURCE_DERIVED_RUN_STAGES.index(row["stage"])
    if (
        previous["status"] in {"review_required", "failed", "cancelled"}
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
                row["stage"] != "supervision"
                or row["error_code"] is not None
                or "review_id" not in row["evidence"]
                or "validation_database_sha256"
                not in row["evidence"]
            )
        )
    ):
        raise SourceDerivationError("source_derivation_run_event_invalid")
    return copy.deepcopy(row)


def _read_run_events(
    paths: dict[str, Path],
    identity: dict[str, Any],
) -> list[dict[str, Any]]:
    directory = paths["events"]
    if not directory.exists() and not directory.is_symlink():
        raise SourceDerivationError("source_derivation_run_conflict")
    try:
        metadata = directory.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
            metadata.st_mode
        ):
            raise SourceDerivationError(
                "source_derivation_run_conflict"
            )
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
    except SourceDerivationError:
        raise
    except OSError as exc:
        raise SourceDerivationError(
            "source_derivation_state_unavailable"
        ) from exc
    events: list[dict[str, Any]] = []
    previous = None
    for path in entries:
        match = _EVENT_FILE.fullmatch(path.name)
        if match is None:
            raise SourceDerivationError(
                "source_derivation_run_event_invalid"
            )
        event = _validate_run_event(
            _read_json_file(path),
            identity,
            previous,
        )
        if (
            int(match.group(1)) != event["sequence"]
            or match.group(2) != event["canonical_digest"]
        ):
            raise SourceDerivationError(
                "source_derivation_run_event_invalid"
            )
        events.append(event)
        previous = event
    if not events:
        raise SourceDerivationError("source_derivation_run_conflict")
    return events


def _read_run_directory(
    state_root: str | Path,
    authorization_digest: str,
) -> dict[str, Any]:
    paths = source_derived_run_paths(state_root, authorization_digest)
    try:
        metadata = paths["run_dir"].lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
            metadata.st_mode
        ):
            raise SourceDerivationError(
                "source_derivation_run_conflict"
            )
    except SourceDerivationError:
        raise
    except OSError as exc:
        raise SourceDerivationError(
            "source_derivation_run_not_found"
        ) from exc
    authorization = validate_source_derived_authorization(
        _read_json_file(paths["authorization"])
    )
    if authorization["authorization_digest"] != authorization_digest:
        raise SourceDerivationError("source_derivation_run_conflict")
    identity = _validate_run_identity(
        authorization,
        _read_json_file(paths["run"]),
    )
    events = _read_run_events(paths, identity)
    return {
        "authorization": authorization,
        "identity": identity,
        "events": events,
        "paths": paths,
    }


@_serialized_state
def source_derived_run_records(
    state_root: str | Path,
) -> list[dict[str, Any]]:
    root = Path(state_root) / SOURCE_DERIVED_STATE_DIRECTORY
    if not root.exists() and not root.is_symlink():
        return []
    try:
        metadata = root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
            metadata.st_mode
        ):
            raise SourceDerivationError(
                "source_derivation_state_conflict"
            )
        entries = sorted(root.iterdir(), key=lambda item: item.name)
    except SourceDerivationError:
        raise
    except OSError as exc:
        raise SourceDerivationError(
            "source_derivation_state_unavailable"
        ) from exc
    records = []
    for path in entries:
        if _DIGEST.fullmatch(path.name) is None:
            raise SourceDerivationError(
                "source_derivation_state_conflict"
            )
        records.append(_read_run_directory(state_root, path.name))
    return records


@_serialized_state
def get_source_derived_run(
    state_root: str | Path,
    run_id: str,
) -> dict[str, Any]:
    if _RUN_ID.fullmatch(str(run_id)) is None:
        raise SourceDerivationError("source_derivation_run_not_found")
    # ponytail: O(n) is enough for developer runs; add an index only after
    # measured state volume makes this scan material.
    matches = [
        record
        for record in source_derived_run_records(state_root)
        if record["identity"]["run_id"] == run_id
    ]
    if not matches:
        raise SourceDerivationError("source_derivation_run_not_found")
    if len(matches) != 1:
        raise SourceDerivationError("source_derivation_run_conflict")
    record = matches[0]
    source_hashes = {
        event["evidence"]["source_sha256"]
        for event in record["events"]
        if "source_sha256" in event["evidence"]
    }
    if source_hashes:
        if len(source_hashes) != 1:
            raise SourceDerivationError(
                "source_derivation_source_conflict"
            )
        source = _read_private_bytes(
            record["paths"]["source_file"],
            128 * 1024,
            "source_derivation_source_conflict",
        )
        if hashlib.sha256(source).hexdigest() != next(iter(source_hashes)):
            raise SourceDerivationError(
                "source_derivation_source_conflict"
            )
    validation_hashes = {
        event["evidence"]["validation_database_sha256"]
        for event in record["events"]
        if "validation_database_sha256" in event["evidence"]
    }
    if validation_hashes:
        if len(validation_hashes) != 1:
            raise SourceDerivationError(
                "source_derivation_validation_conflict"
            )
        database = _read_private_bytes(
            record["paths"]["validation_database"],
            1024 * 1024 * 1024,
            "source_derivation_validation_conflict",
        )
        if hashlib.sha256(database).hexdigest() != next(
            iter(validation_hashes)
        ):
            raise SourceDerivationError(
                "source_derivation_validation_conflict"
            )
    return record


def source_derived_run_projection(
    record: dict[str, Any],
) -> dict[str, Any]:
    identity = record["identity"]
    latest = record["events"][-1]
    return {
        "schema_version": SOURCE_DERIVED_RUN_STATUS_VERSION,
        "run_id": identity["run_id"],
        "status": latest["status"],
        "stage": latest["stage"],
        "attempt_count": identity["attempt_count"],
        "review_scope": "isolated",
        "created_at": identity["created_at"],
        "updated_at": latest["created_at"],
        "error_code": latest["error_code"],
    }


@_serialized_state
def prepare_source_derived_run(
    state_root: str | Path,
    authorization: dict[str, Any],
    request: dict[str, Any],
    *,
    source_root_id: str,
    source_relpath: str,
    source_proposal_model: dict[str, Any],
    supervision_model: dict[str, str],
    created_at: str,
) -> dict[str, Any]:
    authorization = validate_source_derived_authorization(authorization)
    if (
        _SAFE_ID.fullmatch(str(source_root_id)) is None
        or _safe_relative(source_relpath)
        != authorization["evidence"][0]["logical_path"]
        or type(request) is not dict
        or _DIGEST.fullmatch(str(request.get("request_digest"))) is None
        or type(created_at) is not str
        or not created_at
    ):
        raise SourceDerivationError("source_derivation_run_invalid")
    source_model = _validate_model_identity(source_proposal_model)
    supervisor = _validate_supervision_model(supervision_model)
    binding_digest = source_derived_authorization_binding_digest(
        authorization
    )
    user_request_digest = _source_derived_user_request_digest(
        authorization,
        source_root_id,
        source_relpath,
    )
    for record in source_derived_run_records(state_root):
        identity = record["identity"]
        if identity["user_request_digest"] != user_request_digest:
            continue
        if identity["authorization_binding_digest"] != binding_digest:
            raise SourceDerivationError("source_derivation_run_stale")
        expected = {
            "source_root_id": source_root_id,
            "source_relpath": source_relpath,
            "source_snapshot_sha256": authorization[
                "source_snapshot_sha256"
            ],
            "project_graph_digest": authorization[
                "project_graph_digest"
            ],
            "warehouse_revision": authorization["warehouse_revision"],
            "catalog_digest": authorization["catalog_digest"],
            "source_proposal_model": source_model,
            "supervision_model": supervisor,
        }
        if any(identity[key] != value for key, value in expected.items()):
            raise SourceDerivationError("source_derivation_run_stale")
        return {
            **source_derived_run_projection(record),
            "created": False,
        }
    paths = source_derived_run_paths(
        state_root,
        authorization["authorization_digest"],
    )
    body = {
        "schema_version": SOURCE_DERIVED_RUN_VERSION,
        "run_id": f"run_{uuid.uuid4().hex}",
        "authorization_digest": authorization["authorization_digest"],
        "authorization_binding_digest": binding_digest,
        "user_request_digest": user_request_digest,
        "request_digest": request["request_digest"],
        "source_root_id": source_root_id,
        "source_relpath": source_relpath,
        "source_snapshot_sha256": authorization[
            "source_snapshot_sha256"
        ],
        "project_graph_digest": authorization["project_graph_digest"],
        "warehouse_revision": authorization["warehouse_revision"],
        "catalog_digest": authorization["catalog_digest"],
        "source_proposal_model": source_model,
        "supervision_model": supervisor,
        "attempt_count": 1,
        "created_at": created_at,
    }
    identity = {**body, "canonical_digest": canonical_json_digest(body)}
    _validate_run_identity(authorization, identity)
    _ensure_directory(paths["run_dir"])
    _write_immutable(paths["authorization"], authorization)
    _write_immutable(paths["run"], identity)
    _ensure_directory(paths["events"])
    event_body = {
        "schema_version": SOURCE_DERIVED_RUN_EVENT_VERSION,
        "run_digest": identity["canonical_digest"],
        "sequence": 1,
        "previous_event_digest": None,
        "status": "pending",
        "stage": "source_proposal",
        "evidence": {},
        "error_code": None,
        "created_at": created_at,
    }
    event = {
        **event_body,
        "canonical_digest": canonical_json_digest(event_body),
    }
    _validate_run_event(event, identity, None)
    _write_immutable(
        paths["events"]
        / f"event_000001_{event['canonical_digest']}.json",
        event,
    )
    record = _read_run_directory(
        state_root,
        authorization["authorization_digest"],
    )
    return {**source_derived_run_projection(record), "created": True}


@_serialized_state
def append_source_derived_run_event(
    state_root: str | Path,
    run_id: str,
    *,
    status: str,
    stage: str,
    evidence: dict[str, Any] | None = None,
    error_code: str | None = None,
    created_at: str,
) -> dict[str, Any]:
    record = get_source_derived_run(state_root, run_id)
    previous = record["events"][-1]
    body = {
        "schema_version": SOURCE_DERIVED_RUN_EVENT_VERSION,
        "run_digest": record["identity"]["canonical_digest"],
        "sequence": previous["sequence"] + 1,
        "previous_event_digest": previous["canonical_digest"],
        "status": status,
        "stage": stage,
        "evidence": copy.deepcopy(evidence or {}),
        "error_code": error_code,
        "created_at": created_at,
    }
    event = {**body, "canonical_digest": canonical_json_digest(body)}
    _validate_run_event(
        event,
        record["identity"],
        previous,
    )
    _write_immutable(
        record["paths"]["events"]
        / (
            f"event_{event['sequence']:06d}_"
            f"{event['canonical_digest']}.json"
        ),
        event,
    )
    return source_derived_run_projection(
        get_source_derived_run(state_root, run_id)
    )


@_serialized_state
def write_source_derived_proposal(
    state_root: str | Path,
    run_id: str,
    content: str,
) -> dict[str, str]:
    if (
        type(content) is not str
        or not content.strip()
        or not 1 <= len(content.encode("utf-8")) <= 128 * 1024
    ):
        raise SourceDerivationError("source_derivation_response_invalid")
    record = get_source_derived_run(state_root, run_id)
    path = record["paths"]["source_file"]
    data = content.encode("utf-8")
    _write_immutable_bytes(
        path,
        data,
        "source_derivation_source_conflict",
    )
    return {
        "source_relpath": "source/capability.js",
        "source_sha256": hashlib.sha256(data).hexdigest(),
    }
