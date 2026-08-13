#!/usr/bin/env python3
"""Derive redacted, non-formal Reweave experience from explicit evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Callable


NOT_RECORDED = "NOT_RECORDED"
AUTHORITY = "non_formal_derived_experience"
REDACTION_POLICY_VERSION = "reweave_experience_redaction.v1"
DERIVATION_RULE_VERSION = "reweave_experience_derivation.v1"
LABEL_RULE_VERSION = "reweave_experience_task_label_rules.v1"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SAFE_ID = re.compile(r"[a-z][a-z0-9_-]{0,95}\Z")
SAFE_VERSION = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}\Z")
SAFE_OFFER_REF = re.compile(r"offer_[0-9a-f]{24}\Z")
WINDOWS_DRIVE = re.compile(r"[A-Za-z]:[\\/]")

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


class ExperienceExportError(ValueError):
    pass


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


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExperienceExportError("duplicate_json_key")
        result[key] = value
    return result


def strict_json_bytes(raw: bytes, *, name: str) -> Any:
    try:
        text = raw.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ExperienceExportError("non_finite_json_number")
            ),
        )
    except ExperienceExportError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExperienceExportError(f"invalid_json:{name}") from exc


def load_json(path: Path) -> Any:
    try:
        if path.is_symlink() or not path.is_file():
            raise ExperienceExportError(f"invalid_json_path:{path.name}")
        return strict_json_bytes(path.read_bytes(), name=path.name)
    except ExperienceExportError:
        raise
    except OSError as exc:
        raise ExperienceExportError(f"invalid_json:{path.name}") from exc


def _exact_dict(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ExperienceExportError(code)
    return value


def _digest(value: Any, code: str) -> str:
    if type(value) is not str or SHA256.fullmatch(value) is None:
        raise ExperienceExportError(code)
    return value


def _safe_id(value: Any, code: str) -> str:
    if type(value) is not str or SAFE_ID.fullmatch(value) is None:
        raise ExperienceExportError(code)
    return value


def _safe_version(value: Any, code: str) -> str:
    if type(value) is not str or SAFE_VERSION.fullmatch(value) is None:
        raise ExperienceExportError(code)
    return value


def _enum_or_not(value: Any, allowed: set[str], code: str) -> str:
    if value == NOT_RECORDED:
        return value
    if type(value) is not str or value not in allowed:
        raise ExperienceExportError(code)
    return value


def _digest_or_not(value: Any, code: str) -> str:
    return value if value == NOT_RECORDED else _digest(value, code)


def _safe_model_name(value: Any) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 200
        or value.startswith(("/", "\\", "~"))
        or "/Users/" in value
        or WINDOWS_DRIVE.match(value)
        or value.lower().startswith("file://")
    ):
        raise ExperienceExportError("invalid_model_name")
    return value


def json_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if type(pointer) is not str or not pointer.startswith("/"):
        raise ExperienceExportError("invalid_json_pointer")
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        try:
            current = current[int(token)] if type(current) is list else current[token]
        except (KeyError, IndexError, TypeError, ValueError):
            return NOT_RECORDED
    return current


def _safe_relative_path(value: Any) -> PurePosixPath:
    if (
        type(value) is not str
        or not value
        or "\x00" in value
        or value.startswith(("/", "\\", "~"))
        or value.lower().startswith("file://")
        or WINDOWS_DRIVE.match(value)
        or "\\" in value
    ):
        raise ExperienceExportError("unsafe_evidence_path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ExperienceExportError("unsafe_evidence_path")
    return relative


def _resolve_evidence_path(index_path: Path, value: Any) -> Path:
    relative = _safe_relative_path(value)
    root = index_path.parent.resolve(strict=True)
    current = root
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ExperienceExportError("missing_evidence") from exc
        if stat.S_ISLNK(mode):
            raise ExperienceExportError("unsafe_evidence_symlink")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ExperienceExportError("unsafe_evidence_path") from exc
    if not resolved.is_file():
        raise ExperienceExportError("missing_evidence")
    return resolved


def _validate_index_path(index_path: Path) -> Path:
    if index_path.is_symlink() or not index_path.is_file():
        raise ExperienceExportError("invalid_index_path")
    return index_path.resolve(strict=True)


def _load_evidence_index(
    index_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, str]]]:
    index_path = _validate_index_path(index_path)
    index = _exact_dict(
        load_json(index_path),
        {"schema", "project_scope_digest", "evidence", "records"},
        "invalid_index_shape",
    )
    if index["schema"] != "reweave_experience_evidence_index.v1":
        raise ExperienceExportError("invalid_index_schema")
    scope = _digest(index["project_scope_digest"], "invalid_project_scope_digest")
    if type(index["evidence"]) is not list or not index["evidence"]:
        raise ExperienceExportError("evidence_required")
    if type(index["records"]) is not list or not index["records"]:
        raise ExperienceExportError("records_required")
    values: dict[str, Any] = {}
    references: dict[str, dict[str, str]] = {}
    for raw in sorted(
        index["evidence"],
        key=lambda item: item.get("evidence_id", "") if type(item) is dict else "",
    ):
        item = _exact_dict(
            raw,
            {"evidence_id", "path", "project_scope_digest", "sha256"},
            "invalid_evidence_entry",
        )
        evidence_id = _safe_id(item["evidence_id"], "invalid_evidence_id")
        if evidence_id in values:
            raise ExperienceExportError("duplicate_evidence_id")
        if item["project_scope_digest"] != scope:
            raise ExperienceExportError("cross_project_evidence")
        expected = _digest(item["sha256"], "invalid_evidence_digest")
        path = _resolve_evidence_path(index_path, item["path"])
        try:
            raw_bytes = path.read_bytes()
        except OSError as exc:
            raise ExperienceExportError(f"missing_evidence:{evidence_id}") from exc
        if sha256_bytes(raw_bytes) != expected:
            raise ExperienceExportError(f"evidence_digest_mismatch:{evidence_id}")
        values[evidence_id] = strict_json_bytes(raw_bytes, name=path.name)
        references[evidence_id] = {"evidence_id": evidence_id, "sha256": expected}
    return index, values, references


def _failure_attribution(value: Any) -> Any:
    if value == NOT_RECORDED:
        return value
    row = _exact_dict(
        value,
        {"status", "code", "rule_version", "evidence_digest"},
        "invalid_failure_attribution",
    )
    if row["status"] != "RECORDED":
        raise ExperienceExportError("invalid_failure_attribution")
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
            raise ExperienceExportError("invalid_model_selection")
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
            raise ExperienceExportError("invalid_model_selection")
    elif offer_ref != NOT_RECORDED:
        raise ExperienceExportError("invalid_model_selection")
    return {"status": status, "offer_ref": offer_ref}


def _rule_identities(value: Any) -> Any:
    if value == NOT_RECORDED:
        return value
    if type(value) is not list or not value:
        raise ExperienceExportError("invalid_rule_version_identities")
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
        raise ExperienceExportError("invalid_rule_version_identities")
    return rows


def _regression_evidence(value: Any) -> Any:
    if value == NOT_RECORDED:
        return value
    if type(value) is not list or not value:
        raise ExperienceExportError("invalid_regression_evidence")
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
        raise ExperienceExportError("invalid_regression_evidence")
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
            raise ExperienceExportError("invalid_correction_count")
        return value
    if field == "failure_attribution":
        return _failure_attribution(value)
    raise ExperienceExportError("unknown_record_field")


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
    raise ExperienceExportError("unknown_record_field")


def derive_records(index_path: Path) -> list[dict[str, Any]]:
    index, evidence, references = _load_evidence_index(index_path)
    scope = index["project_scope_digest"]
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    ordered = sorted(
        index["records"],
        key=lambda row: (
            row.get("schema", "") if type(row) is dict else "",
            row.get("record_id", "") if type(row) is dict else "",
        ),
    )
    for raw in ordered:
        spec = _exact_dict(
            raw,
            {"schema", "record_id", "project_scope_digest", "fields"},
            "invalid_record_spec",
        )
        schema = spec["schema"]
        if schema not in {"planning_experience.v1", "validation_experience.v1"}:
            raise ExperienceExportError("invalid_record_schema")
        record_id = _safe_id(spec["record_id"], "invalid_record_id")
        if (schema, record_id) in seen:
            raise ExperienceExportError("duplicate_record_id")
        seen.add((schema, record_id))
        if spec["project_scope_digest"] != scope:
            raise ExperienceExportError("cross_project_record")
        fields = spec["fields"]
        allowed = PLANNING_FIELDS if schema == "planning_experience.v1" else VALIDATION_FIELDS
        if type(fields) is not dict or set(fields) - set(allowed):
            raise ExperienceExportError("unknown_record_field")
        used: set[str] = set()
        record: dict[str, Any] = {
            "schema": schema,
            "authority": AUTHORITY,
            "redaction_policy_version": REDACTION_POLICY_VERSION,
            "derivation_rule_version": DERIVATION_RULE_VERSION,
            "record_id": record_id,
            "project_scope_digest": scope,
        }
        for field in allowed:
            mapping = fields.get(field)
            if mapping is None:
                value = NOT_RECORDED
            else:
                mapping = _exact_dict(
                    mapping,
                    {"evidence_id", "pointer", "mode"},
                    "invalid_field_mapping",
                )
                evidence_id = mapping["evidence_id"]
                if type(evidence_id) is not str or evidence_id not in evidence:
                    raise ExperienceExportError("invalid_field_mapping")
                expected_mode = "digest" if field == "goal_safe_projection" else "value"
                if mapping["mode"] != expected_mode:
                    raise ExperienceExportError("invalid_field_projection_mode")
                used.add(evidence_id)
                projected = json_pointer(evidence[evidence_id], mapping["pointer"])
                value = (
                    {
                        "canonical_value_sha256": sha256_bytes(
                            canonical_bytes(projected)
                        )
                    }
                    if mapping["mode"] == "digest" and projected != NOT_RECORDED
                    else projected
                )
            validator: Callable[[str, Any], Any] = (
                _planning_value
                if schema == "planning_experience.v1"
                else _validation_value
            )
            record[field] = validator(field, value)
        record["source_evidence_references"] = [
            references[evidence_id] for evidence_id in sorted(used)
        ]
        record["canonical_digest"] = sha256_bytes(canonical_bytes(record))
        records.append(record)
    return records


def validate_experience_record(
    raw: bytes,
    expected_schema: str,
    expected_sha256: str,
) -> dict[str, Any]:
    _digest(expected_sha256, "invalid_experience_file_digest")
    if sha256_bytes(raw) != expected_sha256:
        raise ExperienceExportError("experience_file_digest_mismatch")
    value = strict_json_bytes(raw, name="experience.json")
    allowed = PLANNING_FIELDS if expected_schema == "planning_experience.v1" else VALIDATION_FIELDS
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
        row["schema"] != expected_schema
        or row["authority"] != AUTHORITY
        or row["redaction_policy_version"] != REDACTION_POLICY_VERSION
        or row["derivation_rule_version"] != DERIVATION_RULE_VERSION
        or _safe_id(row["record_id"], "invalid_experience_record") != row["record_id"]
        or _digest(row["project_scope_digest"], "invalid_experience_record")
        != row["project_scope_digest"]
        or _digest(digest, "invalid_experience_record") != digest
        or digest != sha256_bytes(canonical_bytes(body))
    ):
        raise ExperienceExportError("invalid_experience_record")
    validator = _planning_value if expected_schema == "planning_experience.v1" else _validation_value
    for field in allowed:
        validator(field, row[field])
    refs = row["source_evidence_references"]
    if type(refs) is not list:
        raise ExperienceExportError("invalid_experience_record")
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
        raise ExperienceExportError("invalid_experience_record")
    return row


def validate_experience_file(
    path: Path,
    expected_schema: str,
    expected_sha256: str,
) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ExperienceExportError("invalid_experience_file")
    try:
        return validate_experience_record(
            path.read_bytes(),
            expected_schema,
            expected_sha256,
        )
    except OSError as exc:
        raise ExperienceExportError("invalid_experience_file") from exc


def _prepare_output_directory(output_dir: Path) -> tuple[Path, bool]:
    if output_dir.is_symlink():
        raise ExperienceExportError("output_directory_unsafe")
    created = False
    if output_dir.exists():
        if not output_dir.is_dir():
            raise ExperienceExportError("output_directory_invalid")
        try:
            if any(output_dir.iterdir()):
                raise ExperienceExportError("output_directory_not_empty")
        except OSError as exc:
            raise ExperienceExportError("output_directory_invalid") from exc
    else:
        parent = output_dir.parent
        if parent.is_symlink() or not parent.is_dir():
            raise ExperienceExportError("output_parent_invalid")
        try:
            output_dir.mkdir(mode=0o700)
            created = True
        except OSError as exc:
            raise ExperienceExportError("output_directory_create_failed") from exc
    if output_dir.is_symlink():
        raise ExperienceExportError("output_directory_unsafe")
    return output_dir.resolve(strict=True), created


def _write_temp_file(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600, follow_symlinks=False)


def _atomic_write_collection(output_dir: Path, files: dict[str, bytes]) -> list[Path]:
    if not files or any(
        type(name) is not str
        or not name
        or Path(name).name != name
        or name.startswith(".")
        for name in files
    ):
        raise ExperienceExportError("output_file_invalid")
    root, created = _prepare_output_directory(output_dir)
    temporary: list[Path] = []
    final: list[Path] = []
    try:
        for name in sorted(files):
            temp = root / f".{name}.{uuid.uuid4().hex}.tmp"
            _write_temp_file(temp, files[name])
            temporary.append(temp)
        for name, temp in zip(sorted(files), temporary):
            target = root / name
            if target.exists() or target.is_symlink():
                raise ExperienceExportError("output_conflict")
            os.rename(temp, target)
            final.append(target)
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return final
    except BaseException as exc:
        for path in temporary + final:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        if created:
            try:
                root.rmdir()
            except OSError:
                pass
        if isinstance(exc, ExperienceExportError):
            raise
        raise ExperienceExportError("output_write_failed") from exc


def write_experience(index_path: Path, output_dir: Path) -> list[Path]:
    records = derive_records(index_path)
    files = {
        f"{record['record_id']}.{record['schema']}.json": canonical_bytes(record)
        for record in records
    }
    return _atomic_write_collection(output_dir, files)


def _read_safe_reference(
    benchmark_path: Path,
    value: Any,
    expected_schema: str,
) -> tuple[dict[str, Any], str]:
    row = _exact_dict(
        value,
        {"path", "sha256"},
        "invalid_benchmark_reference",
    )
    expected = _digest(row["sha256"], "invalid_benchmark_reference")
    path = _resolve_evidence_path(benchmark_path, row["path"])
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ExperienceExportError("invalid_benchmark_reference") from exc
    return validate_experience_record(raw, expected_schema, expected), expected


def validate_task_label(
    raw: bytes,
    expected_sha256: str,
) -> dict[str, Any]:
    _digest(expected_sha256, "invalid_task_label_digest")
    if sha256_bytes(raw) != expected_sha256:
        raise ExperienceExportError("task_label_file_digest_mismatch")
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
        raise ExperienceExportError("invalid_task_label")
    normalized_metrics: dict[str, Any] = {}
    for name in RATE_METRICS:
        value = metrics.get(name, NOT_RECORDED)
        if value != NOT_RECORDED and type(value) is not bool:
            raise ExperienceExportError(f"invalid_rate_metric:{name}")
        normalized_metrics[name] = value
    for name in AVERAGE_METRICS:
        value = metrics.get(name, NOT_RECORDED)
        if value != NOT_RECORDED and (
            type(value) not in {int, float}
            or not math.isfinite(value)
            or value < 0
        ):
            raise ExperienceExportError(f"invalid_average_metric:{name}")
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
        or row["metrics"] != {
            name: normalized_metrics[name]
            for name in RATE_METRICS + AVERAGE_METRICS
        }
        or _digest(row["canonical_digest"], "invalid_task_label")
        != row["canonical_digest"]
        or row["canonical_digest"] != sha256_bytes(canonical_bytes(body))
    ):
        raise ExperienceExportError("invalid_task_label")
    return row


def _read_task_label(
    benchmark_path: Path,
    value: Any,
) -> tuple[dict[str, Any], str]:
    row = _exact_dict(
        value,
        {"path", "sha256"},
        "invalid_benchmark_reference",
    )
    expected = _digest(row["sha256"], "invalid_benchmark_reference")
    path = _resolve_evidence_path(benchmark_path, row["path"])
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ExperienceExportError("invalid_benchmark_reference") from exc
    return validate_task_label(raw, expected), expected


def _rate_metric(values: list[Any]) -> dict[str, Any]:
    recorded = [value for value in values if value != NOT_RECORDED]
    missing = len(values) - len(recorded)
    numerator = sum(1 for value in recorded if value is True)
    return {
        "recorded_count": len(recorded),
        "missing_count": missing,
        "numerator": numerator,
        "denominator": len(values),
        "rate": (
            numerator / len(values)
            if values and missing == 0
            else NOT_RECORDED
        ),
    }


def _average_metric(values: list[Any]) -> dict[str, Any]:
    recorded = [value for value in values if value != NOT_RECORDED]
    missing = len(values) - len(recorded)
    total = sum(recorded)
    return {
        "recorded_count": len(recorded),
        "missing_count": missing,
        "sum": total,
        "count": len(values),
        "average": (
            total / len(values)
            if values and missing == 0
            else NOT_RECORDED
        ),
    }


def build_scorecard(index_path: Path) -> dict[str, Any]:
    index_path = _validate_index_path(index_path)
    index = _exact_dict(
        load_json(index_path),
        {"schema", "fixed_model", "tasks"},
        "invalid_scorecard_index_shape",
    )
    if index["schema"] != "reweave_task_coverage_benchmark.v1":
        raise ExperienceExportError("invalid_scorecard_index_schema")
    model = _exact_dict(
        index["fixed_model"],
        {"name", "digest"},
        "invalid_fixed_model",
    )
    fixed_model = {
        "name": _safe_model_name(model["name"]),
        "digest": _digest(model["digest"], "invalid_fixed_model"),
    }
    tasks = index["tasks"]
    if type(tasks) is not list or not tasks:
        raise ExperienceExportError("invalid_benchmark_tasks")
    ordered = sorted(
        tasks,
        key=lambda task: task.get("task_id", "") if type(task) is dict else "",
    )
    if len(
        {
            task.get("task_id")
            for task in ordered
            if type(task) is dict
        }
    ) != len(ordered):
        raise ExperienceExportError("invalid_benchmark_tasks")
    included = []
    metric_values: dict[str, list[Any]] = {
        name: [] for name in RATE_METRICS + AVERAGE_METRICS
    }
    for raw in ordered:
        task = _exact_dict(
            raw,
            {"task_id", "planning", "validation", "label"},
            "invalid_benchmark_task",
        )
        task_id = _safe_id(task["task_id"], "invalid_benchmark_task")
        planning, planning_sha = _read_safe_reference(
            index_path, task["planning"], "planning_experience.v1"
        )
        validation, validation_sha = _read_safe_reference(
            index_path, task["validation"], "validation_experience.v1"
        )
        label, label_sha = _read_task_label(index_path, task["label"])
        scope = planning["project_scope_digest"]
        if (
            validation["project_scope_digest"] != scope
            or label["project_scope_digest"] != scope
            or label["task_id"] != task_id
            or label["planning_experience_sha256"] != planning_sha
            or label["validation_experience_sha256"] != validation_sha
            or planning["exact_model_name"] != fixed_model["name"]
            or planning["exact_model_digest"] != fixed_model["digest"]
            or label["fixed_model"] != fixed_model
        ):
            raise ExperienceExportError("cross_project_or_model_benchmark_task")
        included.append(
            {
                "task_id": task_id,
                "project_scope_digest": scope,
                "planning_experience_sha256": planning_sha,
                "validation_experience_sha256": validation_sha,
                "task_label_sha256": label_sha,
                "attribution_status": label["attribution_status"],
            }
        )
        for name in metric_values:
            metric_values[name].append(label["metrics"][name])
    result: dict[str, Any] = {
        "schema": "reweave_task_coverage_baseline.v1",
        "authority": AUTHORITY,
        "redaction_policy_version": REDACTION_POLICY_VERSION,
        "derivation_rule_version": DERIVATION_RULE_VERSION,
        "fixed_model": fixed_model,
        "task_count": len(included),
        "included_tasks": included,
        "task_distribution_breadth": "INSUFFICIENT",
        "metrics": {
            **{
                name: _rate_metric(metric_values[name])
                for name in RATE_METRICS
            },
            **{
                name: _average_metric(metric_values[name])
                for name in AVERAGE_METRICS
            },
        },
        "claims": {
            "model_qualification": False,
            "architecture_pass": False,
            "task_distribution_sufficient": False,
        },
    }
    result["canonical_digest"] = sha256_bytes(canonical_bytes(result))
    return result


def write_scorecard(index_path: Path, output_dir: Path) -> Path:
    result = build_scorecard(index_path)
    return _atomic_write_collection(
        output_dir,
        {"task-coverage-baseline.json": canonical_bytes(result)},
    )[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--scorecard", action="store_true")
    args = parser.parse_args()
    if args.scorecard:
        write_scorecard(args.index, args.output_dir)
    else:
        write_experience(args.index, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
