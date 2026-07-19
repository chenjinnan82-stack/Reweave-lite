#!/usr/bin/env python3
"""Run read-only Reweave V1 evidence pilots against fixed local Git checkouts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_capsule_intake import (
    EXTRACTION_CONTRACT_VERSION,
    REDACTION_RULES_VERSION,
)
from pimos_lite.reweave_capsule_stage3 import (
    SECURITY_RULES_VERSION,
    SUPERVISION_RULES_VERSION,
    VALIDATION_CONTRACT_VERSION,
)
from pimos_lite.reweave_capsule_store import (
    CANONICALIZATION_VERSION,
    SCHEMA_VERSION,
    CapsuleWarehouseStore,
)


MANIFEST_SCHEMA = "reweave_v1_pilot_manifest.v1"
EVIDENCE_SCHEMA = "reweave_real_project_evidence.v1"
TERMINAL_TASK_STATES = {"completed", "failed", "cancelled"}
FORMAL_TABLES = (
    "capability_groups",
    "capsules",
    "capsule_versions",
    "capsule_sources",
    "capsule_assets",
    "capsule_status_events",
    "product_capsule_usage",
    "legacy_capsule_aliases",
)
KINDS = {"presentation", "interaction", "computation"}


class PilotError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_FAILURE_CODES: dict[str, set[str]] = {
    "qualification_entry_unsupported_v1": {
        "inline_script_unsupported_v1",
        "classic_script_unsupported_v1",
        "project_entry_unsupported_v1",
        "static_closure_resource_unsupported_v1",
    },
    "qualification_source_unavailable": {
        "source_root_missing",
        "project_source_missing",
        "project_entry_missing",
        "project_entry_missing_from_snapshot",
        "source_access_denied",
        "source_utf8_invalid",
    },
    "qualification_source_unstable": {
        "source_changed_during_scan",
        "source_case_conflict",
    },
    "qualification_closure_boundary": {
        "static_closure_external_reference",
        "static_closure_reference_invalid",
        "static_closure_file_missing",
        "static_closure_path_outside_project",
        "static_closure_symlink_forbidden",
        "static_closure_outside_snapshot",
    },
    "qualification_budget": {
        "source_limit_exceeded",
        "source_total_size_exceeded",
        "javascript_snapshot_size_exceeded",
    },
    "module_graph_unsupported_v1": {
        "module_import_unsupported",
        "module_bare_specifier",
        "module_remote_specifier",
        "module_reexport_forbidden",
        "module_export_unsupported",
        "module_dynamic_execution_unsupported",
        "module_cycle",
        "module_depth_exceeded",
        "module_count_exceeded",
        "module_extension_unsupported",
    },
    "module_invalid_or_inconsistent": {
        "module_syntax_invalid",
        "module_symbol_duplicate",
        "module_case_conflict",
        "module_too_large",
        "module_snapshot_invalid",
        "module_snapshot_duplicate",
        "module_snapshot_hash_mismatch",
    },
    "bootstrap_top_level_not_declarative_v1": {
        "module_top_level_statement_unsupported",
        "module_top_level_side_effect",
        "module_top_level_mutable_state",
    },
    "atomic_role_not_provable_v1": {
        "missing_supported_entrypoint_v1",
        "unsupported_extraction_boundary_v1",
        "non_atomic_role_closure_v1",
        "anonymous_default_export_unsupported_v1",
        "invalid_render_signature",
        "invalid_mount_signature",
        "invalid_compute_signature",
        "async_entrypoint_forbidden",
    },
    "contract_not_provable_v1": {
        "ambiguous_data_contract_v1",
        "dynamic_input_field",
        "integer_range_overflow",
        "error_contract_unsupported_v1",
        "unresolved_static_dependency_v1",
        "event_binding_unsupported_v1",
        "event_output_unsupported_v1",
        "interaction_dispose_not_closed",
        "dynamic_selector_unsupported_v1",
        "selector_outside_static_root",
        "unsupported_string_construction_v1",
        "literal_evidence_budget_exceeded_v1",
    },
    "ui_root_not_provable_v1": {"html_capsule_root_invalid"},
    "sensitivity_or_brand_gate": {
        "secret_literal_rejected",
        "confirmed_real_record_rejected",
        "sensitivity_confirmation_required",
        "sensitivity_confirmation_required_stage3",
        "sensitive_contract_identifier_unsupported",
        "brand_confirmation_required",
    },
    "stage3_asset_policy": {
        "capsule_asset_total_forbidden",
        "asset_content_confirmation_required_stage3",
        "brand_asset_requires_brand_limited",
    },
    "stage3_compute_runtime": {
        "input_mutated",
        "non_json_output",
        "non_finite_output",
        "promise_output_forbidden",
    },
    "stage3_qweb_runtime": {"submit_prevent_default_required"},
    "validation_environment": {
        "node_unavailable",
        "pyside6_unavailable",
        "esbuild_unavailable",
        "esbuild_bundle_failed",
        "bundle_syntax_invalid",
        "bundle_security_analyzer_failed",
        "javascript_security_analyzer_failed",
        "extraction_analyzer_failed",
        "extraction_analyzer_timeout",
        "compute_worker_failed",
        "compute_worker_failed_timeout",
        "image_worker_failed",
        "image_worker_failed_timeout",
        "qweb_worker_failed",
        "qweb_worker_failed_timeout",
        "qweb_timeout",
    },
    "source_or_evidence_stale": {
        "source_changed_since_review",
        "static_closure_changed",
        "candidate_boundary_changed",
        "candidate_changed_since_validation",
    },
    "supervision_environment_or_verdict": {
        "supervision_rejected",
        "ollama_model_not_selected",
        "ollama_model_not_available",
        "ollama_model_digest_changed",
        "ollama_selection_invalid",
        "ollama_request_failed",
        "ollama_response_invalid",
        "ollama_timeout",
    },
}


def failure_family(code: str) -> str:
    for family, codes in _FAILURE_CODES.items():
        if code in codes:
            return family
    if code.startswith("html_"):
        return "stage3_html_policy"
    if code.startswith("css_"):
        return "stage3_css_policy"
    if code.startswith(("asset_", "image_")):
        return "stage3_asset_policy"
    if code.startswith("compute_"):
        return "stage3_compute_runtime"
    if code.startswith(("qweb_", "presentation_", "interaction_")):
        return "stage3_qweb_runtime"
    if code.startswith("ollama_"):
        return "supervision_environment_or_verdict"
    return "unclassified"


def current_rules() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "extraction_contract_version": EXTRACTION_CONTRACT_VERSION,
        "redaction_rules_version": REDACTION_RULES_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "security_rules_version": SECURITY_RULES_VERSION,
        "supervision_rules_version": SUPERVISION_RULES_VERSION,
        "validation_contract_version": VALIDATION_CONTRACT_VERSION,
    }


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PilotError("manifest_invalid") from exc
    if type(value) is not dict:
        raise PilotError("manifest_invalid")
    return value


def _safe_relative(value: Any) -> str:
    if type(value) is not str or not value or "\\" in value:
        raise PilotError("manifest_path_invalid")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise PilotError("manifest_path_invalid")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise PilotError("manifest_path_invalid")
    return path.as_posix()


def validate_manifest(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != MANIFEST_SCHEMA:
        raise PilotError("manifest_schema_unsupported")
    if value.get("rules") != current_rules():
        raise PilotError("manifest_rule_version_mismatch")
    baseline = value.get("reweave_head")
    if type(baseline) is not str or re.fullmatch(r"[0-9a-f]{40}", baseline) is None:
        raise PilotError("manifest_reweave_head_invalid")
    projects = value.get("projects")
    if type(projects) is not list:
        raise PilotError("manifest_projects_invalid")
    ids: set[str] = set()
    locations: set[str] = set()
    positive_kinds: Counter[str] = Counter()
    cohort_counts: Counter[str] = Counter()
    normalized: list[dict[str, Any]] = []
    for row in projects:
        if type(row) is not dict:
            raise PilotError("manifest_project_invalid")
        pilot_id = row.get("id")
        if type(pilot_id) is not str or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", pilot_id) is None:
            raise PilotError("manifest_project_id_invalid")
        if pilot_id in ids:
            raise PilotError("manifest_project_duplicate")
        ids.add(pilot_id)
        cohort = row.get("cohort")
        if cohort not in {"positive", "bootstrap"}:
            raise PilotError("manifest_cohort_invalid")
        cohort_counts[cohort] += 1
        expected_kind = row.get("expected_kind")
        if cohort == "positive":
            if expected_kind not in KINDS:
                raise PilotError("manifest_expected_kind_invalid")
            positive_kinds[str(expected_kind)] += 1
        elif expected_kind is not None:
            raise PilotError("manifest_expected_kind_invalid")
        checkout_dir = _safe_relative(row.get("checkout_dir"))
        entry_relpath = _safe_relative(row.get("entry_relpath"))
        if checkout_dir in locations:
            raise PilotError("manifest_checkout_duplicate")
        locations.add(checkout_dir)
        commit = row.get("commit")
        if type(commit) is not str or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
            raise PilotError("manifest_commit_invalid")
        repository_url = row.get("repository_url")
        if type(repository_url) is not str or not repository_url.startswith("https://github.com/"):
            raise PilotError("manifest_repository_invalid")
        license_relpath = row.get("license_relpath")
        if license_relpath is not None:
            license_relpath = _safe_relative(license_relpath)
        if cohort == "positive" and license_relpath is None:
            raise PilotError("manifest_positive_license_required")
        selection_order = row.get("selection_order")
        if type(selection_order) is not int or selection_order < 1:
            raise PilotError("manifest_selection_order_invalid")
        normalized.append(
            {
                "id": pilot_id,
                "cohort": cohort,
                "selection_order": selection_order,
                "repository_url": repository_url.removesuffix(".git"),
                "commit": commit,
                "checkout_dir": checkout_dir,
                "entry_relpath": entry_relpath,
                "license_relpath": license_relpath,
                "expected_kind": expected_kind,
            }
        )
    if cohort_counts["positive"] > 12 or cohort_counts["bootstrap"] > 8:
        raise PilotError("manifest_cohort_limit_exceeded")
    if any(count > 4 for count in positive_kinds.values()):
        raise PilotError("manifest_positive_kind_limit_exceeded")
    positive_scout = value.get("positive_scout")
    if type(positive_scout) is not dict:
        raise PilotError("manifest_positive_scout_invalid")
    screened_by_kind = positive_scout.get("screened_by_kind")
    evidence_hashes = positive_scout.get("raw_search_evidence_sha256")
    eligible_count = positive_scout.get("eligible_projects_found")
    if (
        type(screened_by_kind) is not dict
        or set(screened_by_kind) != KINDS
        or any(
            type(screened_by_kind[kind]) is not int
            or not 0 <= screened_by_kind[kind] <= 20
            for kind in KINDS
        )
        or type(evidence_hashes) is not dict
        or set(evidence_hashes) != KINDS
        or any(
            type(evidence_hashes[kind]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", evidence_hashes[kind]) is None
            for kind in KINDS
        )
        or type(eligible_count) is not int
        or eligible_count != cohort_counts["positive"]
        or type(positive_scout.get("status")) is not str
        or not positive_scout["status"]
    ):
        raise PilotError("manifest_positive_scout_invalid")
    orders = [(row["cohort"], row["selection_order"]) for row in normalized]
    if len(orders) != len(set(orders)):
        raise PilotError("manifest_selection_order_duplicate")
    return {
        **value,
        "projects": sorted(
            normalized, key=lambda row: (row["cohort"], row["selection_order"], row["id"])
        ),
    }


def _run_git(root: Path, *args: str) -> bytes:
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
        env=environment,
    )
    if completed.returncode:
        raise PilotError("source_git_invalid")
    return completed.stdout


def _canonical_repository(value: str) -> str:
    normalized = value.strip().removesuffix(".git").removesuffix("/")
    if normalized.startswith("git@github.com:"):
        normalized = "https://github.com/" + normalized.removeprefix("git@github.com:")
    return normalized.casefold()


def _tree_fingerprint(root: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    file_count = 0
    directory_count = 0
    symlink_count = 0
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(name for name in directories if name != ".git")
        for name in directories:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                symlink_count += 1
                digest.update(f"L\0{relative}\0{os.readlink(path)}\n".encode("utf-8"))
            else:
                directory_count += 1
                digest.update(f"D\0{relative}\n".encode("utf-8"))
        for name in sorted(files):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                symlink_count += 1
                digest.update(f"L\0{relative}\0{os.readlink(path)}\n".encode("utf-8"))
                continue
            stat = path.stat()
            file_hash = _sha256_bytes(path.read_bytes())
            file_count += 1
            digest.update(
                f"F\0{relative}\0{stat.st_mode & 0o7777:o}\0{stat.st_size}\0{stat.st_mtime_ns}\0{file_hash}\n".encode(
                    "utf-8"
                )
            )
    return {
        "sha256": digest.hexdigest(),
        "file_count": file_count,
        "directory_count": directory_count,
        "symlink_count": symlink_count,
    }


def preflight_project(workspace: Path, project: dict[str, Any]) -> dict[str, Any]:
    checkout_path = workspace / project["checkout_dir"]
    if checkout_path.is_symlink():
        raise PilotError("source_checkout_symlink_forbidden")
    checkout = checkout_path.resolve()
    workspace_resolved = workspace.resolve()
    if checkout == workspace_resolved or workspace_resolved not in checkout.parents:
        raise PilotError("source_checkout_outside_workspace")
    if checkout.is_symlink() or not checkout.is_dir():
        raise PilotError("source_checkout_missing")
    top = Path(_run_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if top != checkout:
        raise PilotError("source_checkout_not_repository_root")
    head = _run_git(checkout, "rev-parse", "HEAD").decode().strip()
    if head != project["commit"]:
        raise PilotError("source_commit_mismatch")
    status = _run_git(
        checkout, "status", "--porcelain=v1", "-z", "--untracked-files=all"
    )
    if status:
        raise PilotError("source_worktree_dirty")
    origin = _run_git(checkout, "remote", "get-url", "origin").decode().strip()
    if _canonical_repository(origin) != _canonical_repository(project["repository_url"]):
        raise PilotError("source_repository_mismatch")
    entry = checkout.joinpath(*PurePosixPath(project["entry_relpath"]).parts)
    if entry.is_symlink() or not entry.is_file():
        raise PilotError("source_entry_mismatch")
    resolved_entry = entry.resolve()
    if checkout not in resolved_entry.parents:
        raise PilotError("source_entry_mismatch")
    license_hash = None
    if project["license_relpath"] is not None:
        license_path = checkout.joinpath(*PurePosixPath(project["license_relpath"]).parts)
        if license_path.is_symlink() or not license_path.is_file():
            raise PilotError("source_license_missing")
        license_hash = _sha256_bytes(license_path.read_bytes())
    tree = _tree_fingerprint(checkout)
    if tree["symlink_count"]:
        raise PilotError("source_symlink_forbidden")
    return {
        "checkout": checkout,
        "head": head,
        "git_tree": _run_git(checkout, "rev-parse", "HEAD^{tree}").decode().strip(),
        "git_status_sha256": _sha256_bytes(status),
        "source_tree": tree,
        "license_sha256": license_hash,
    }


def _poll(service: ReweaveAppService, run_id: str, *, timeout: float = 180.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = service.get_intake_run({"run_id": run_id})
        if result.get("ok") is not True:
            raise PilotError(str(result.get("error", {}).get("code") or "management_poll_failed"))
        data = result.get("data")
        if type(data) is not dict:
            raise PilotError("management_result_invalid")
        status = str(data.get("status") or "")
        if status in TERMINAL_TASK_STATES:
            if status != "completed":
                raise PilotError(str(data.get("error", {}).get("code") or f"management_{status}"))
            return data
        time.sleep(0.05)
    raise PilotError("management_timeout")


def _formal_counts(store: CapsuleWarehouseStore) -> dict[str, int]:
    with store.read_connection() as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in FORMAL_TABLES
        }


def _assert_source_unchanged(before: dict[str, Any], after: dict[str, Any]) -> None:
    if (
        before["source_tree"] != after["source_tree"]
        or before["git_status_sha256"] != after["git_status_sha256"]
    ):
        raise PilotError("source_changed_by_pilot")


def _assert_rejected_no_formal_write(
    candidates: list[dict[str, Any]], delta: dict[str, int]
) -> None:
    if (
        candidates
        and all(row["candidate_status"] == "rejected" for row in candidates)
        and any(delta.values())
    ):
        raise PilotError("rejected_candidate_formal_write")


def _assert_snapshot_consistent(intake: dict[str, Any]) -> None:
    before = intake.get("snapshot_before")
    after = intake.get("snapshot_after")
    if type(before) is not str or not before or before != after:
        raise PilotError("intake_snapshot_mismatch")


def _parse_json(value: Any, default: Any) -> Any:
    if type(value) is not str:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _stage3_pass(summary: dict[str, Any], response_hash: Any) -> bool:
    evidence = summary.get("stage3_evidence")
    if type(evidence) is not dict:
        return False
    security = evidence.get("security_result")
    validation = evidence.get("validation")
    return bool(
        type(security) is dict
        and security.get("status") == "passed"
        and type(validation) is dict
        and validation.get("status") == "passed"
        and type(response_hash) is str
        and re.fullmatch(r"[0-9a-f]{64}", response_hash)
    )


def _candidate_evidence(row: sqlite3.Row, gate_result: dict[str, Any] | None) -> dict[str, Any]:
    sanitized = _parse_json(row["sanitized_candidate_json"], {})
    redaction = _parse_json(row["redaction_summary_json"], {})
    comparison = _parse_json(row["equivalence_comparison_json"], {})
    codes = {
        str(code)
        for code in redaction.get("codes", [])
        if type(code) is str and code
    }
    codes.update(
        str(code)
        for code in comparison.get("reason_codes", [])
        if type(code) is str and code
    )
    stage3_failure = sanitized.get("stage3_failure")
    stage3_code = (
        str(stage3_failure.get("error_code"))
        if type(stage3_failure) is dict and stage3_failure.get("error_code")
        else None
    )
    if gate_result and gate_result.get("error_code"):
        stage3_code = str(gate_result["error_code"])
    if stage3_code:
        codes.add(stage3_code)
    primary = stage3_code
    if primary is None and row["candidate_status"] in {"rejected", "waiting_user"}:
        classified = sorted(code for code in codes if failure_family(code) != "unclassified")
        primary = classified[0] if classified else (sorted(codes)[0] if codes else None)
    family = failure_family(primary) if primary else None
    stage3_passed = _stage3_pass(sanitized, row["supervision_response_hash"])
    validation = sanitized.get("stage3_evidence", {}).get("validation", {})
    acceptance_scope = validation.get("acceptance_scope") if type(validation) is dict else None
    worker_attempted = stage3_code or ""
    workers: dict[str, bool | None] = {"image": None, "compute": None, "qweb": None}
    cleaning = sanitized.get("stage3_evidence", {}).get("cleaning_summary", {})
    if type(cleaning) is dict and cleaning.get("asset_count") == 0:
        workers["image"] = False
    elif type(cleaning) is dict and type(cleaning.get("asset_count")) is int:
        workers["image"] = True
    if acceptance_scope == "isolated_node_vm_computation":
        workers["compute"] = True
        workers["qweb"] = False
    elif acceptance_scope == "real_qwebengine_interaction":
        workers["qweb"] = True
        workers["compute"] = False
    elif str(worker_attempted).startswith("compute_worker_"):
        workers["compute"] = True
    elif str(worker_attempted).startswith("qweb_"):
        workers["qweb"] = True
    response_hash = row["supervision_response_hash"]
    model_called: bool | None
    if comparison.get("same_run_representative") or row["candidate_status"] == "duplicate":
        model_called = False
    elif type(response_hash) is str and re.fullmatch(r"[0-9a-f]{64}", response_hash):
        model_called = True
    elif stage3_code and str(stage3_code).startswith("ollama_"):
        model_called = None
    elif row["candidate_status"] in {"rejected", "waiting_user", "extracted"}:
        model_called = False
    else:
        model_called = None
    if type(sanitized.get("stage3_evidence")) is dict or stage3_code:
        farthest_gate = "stage3"
    elif row["candidate_status"] == "duplicate":
        farthest_gate = "duplicate_resolution"
    else:
        farthest_gate = "intake"
    return {
        "candidate_status": str(row["candidate_status"]),
        "capability_kind": sanitized.get("capability_kind"),
        "source_relpath": str(row["source_relpath"]),
        "source_hash": str(row["source_hash"]),
        "candidate_canonical_hash": row["candidate_canonical_hash"],
        "stage3_passed": stage3_passed,
        "validation_scope": acceptance_scope,
        "model_called": model_called,
        "workers": workers,
        "farthest_gate": farthest_gate,
        "primary_failure": primary,
        "failure_family": family,
        "all_reason_codes": sorted(codes),
    }


def _project_rows(
    store: CapsuleWarehouseStore,
    intake_run_id: str,
    gate_results: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    gates = {
        str(row.get("review_id")): row
        for row in gate_results
        if type(row) is dict and row.get("review_id")
    }
    with store.read_connection() as connection:
        run = connection.execute(
            "SELECT * FROM intake_runs WHERE run_id = ?", (intake_run_id,)
        ).fetchone()
        if run is None:
            raise PilotError("intake_run_missing")
        reviews = connection.execute(
            "SELECT * FROM review_items WHERE run_id = ? ORDER BY created_at, review_id",
            (intake_run_id,),
        ).fetchall()
    return dict(run), [
        _candidate_evidence(row, gates.get(str(row["review_id"]))) for row in reviews
    ]


def _logical_entry(project: dict[str, Any]) -> str:
    rel = str(project.get("project_relpath") or ".")
    entry = str(project.get("entry_relpath") or "")
    return entry if rel == "." else f"{rel}/{entry}"


def _environment() -> dict[str, Any]:
    try:
        pyside = importlib.metadata.version("PySide6")
    except importlib.metadata.PackageNotFoundError:
        pyside = None
    try:
        node = subprocess.run(
            [os.environ.get("REWEAVE_NODE") or "node", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        node_version = node.stdout.strip().removeprefix("v") if node.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        node_version = None
    return {
        "os": platform.system().lower(),
        "python": platform.python_version(),
        "node": node_version,
        "pyside6": pyside,
    }


def _select_model(service: ReweaveAppService) -> dict[str, Any] | None:
    name = os.environ.get("REWEAVE_PILOT_MODEL_NAME")
    digest = os.environ.get("REWEAVE_PILOT_MODEL_DIGEST")
    if not name and not digest:
        return None
    if not name or not digest:
        raise PilotError("pilot_model_environment_invalid")
    started = service.select_supervision_model({"name": name, "digest": digest})
    if started.get("ok") is not True:
        return {"name": name, "digest": digest, "status": "failed", "error_code": started.get("error", {}).get("code")}
    try:
        _poll(service, str(started["run_id"]), timeout=30)
    except PilotError as exc:
        return {"name": name, "digest": digest, "status": "failed", "error_code": exc.code}
    return {"name": name, "digest": digest, "status": "selected"}


def run_project(
    workspace: Path,
    state_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    before = preflight_project(workspace, project)
    project_state = state_root / project["id"]
    if project_state.exists() and any(project_state.iterdir()):
        raise PilotError("pilot_state_not_empty")
    project_state.mkdir(parents=True, exist_ok=True)
    store = CapsuleWarehouseStore(project_state / "capsule_warehouse.sqlite3")
    service = ReweaveAppService(capsule_store=store)
    qualification: dict[str, Any] = {"state": "unknown", "raw_error_code": None}
    intake_data: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = []
    counts_before: dict[str, int] = {}
    counts_after: dict[str, int] = {}
    model_selection: dict[str, Any] | None = None
    try:
        started = service.discover_source_root(
            {"path": str(before["checkout"]), "root_kind": "single_project"}
        )
        if started.get("ok") is not True:
            raise PilotError(str(started.get("error", {}).get("code") or "source_discovery_failed"))
        discovered_task = _poll(service, str(started["run_id"]))
        discovered = discovered_task.get("data")
        if type(discovered) is not dict or type(discovered.get("projects")) is not list:
            raise PilotError("source_discovery_result_invalid")
        matches = [
            row
            for row in discovered["projects"]
            if type(row) is dict and _logical_entry(row) == project["entry_relpath"]
        ]
        if len(matches) != 1:
            raise PilotError("source_entry_discovery_mismatch")
        selected = matches[0]
        confirmed = service.confirm_projects(
            {"projects": [{"project_id": selected["project_id"], "brand_mode": "clear"}]}
        )
        if confirmed.get("ok") is not True:
            raise PilotError(str(confirmed.get("error", {}).get("code") or "project_confirmation_failed"))
        errors = confirmed.get("data", {}).get("errors", [])
        if errors:
            qualification = {
                "state": "unsupported_v1",
                "raw_error_code": str(errors[0].get("error_code") or "project_confirmation_failed"),
            }
            counts_before = _formal_counts(store)
            counts_after = _formal_counts(store)
        else:
            qualification = {"state": "ready", "raw_error_code": None}
            model_selection = _select_model(service)
            counts_before = _formal_counts(store)
            refreshed = service.start_refresh_project({"project_id": selected["project_id"]})
            if refreshed.get("ok") is not True:
                raise PilotError(str(refreshed.get("error", {}).get("code") or "refresh_project_failed"))
            task = _poll(service, str(refreshed["run_id"]))
            data = task.get("data")
            if type(data) is not dict or type(data.get("intake")) is not dict:
                raise PilotError("refresh_result_invalid")
            intake_result = data["intake"]
            intake_run_id = str(intake_result.get("run_id") or "")
            if not intake_run_id:
                raise PilotError("intake_run_missing")
            run_row, candidates = _project_rows(
                store,
                intake_run_id,
                data.get("gate_results") if type(data.get("gate_results")) is list else [],
            )
            intake_counts = _parse_json(run_row.get("counts_json"), {})
            intake_data = {
                "run_status": run_row.get("status"),
                "snapshot_before": run_row.get("snapshot_before"),
                "snapshot_after": run_row.get("snapshot_after"),
                "snapshot_equal": bool(
                    run_row.get("snapshot_before")
                    and run_row.get("snapshot_before") == run_row.get("snapshot_after")
                ),
                "counts": intake_counts,
                "error_code": run_row.get("error_code"),
                "extraction_contract_version": run_row.get("extraction_contract_version"),
            }
            counts_after = _formal_counts(store)
            _assert_snapshot_consistent(intake_data)
    finally:
        try:
            service.close()
        finally:
            after = preflight_project(workspace, project)
            _assert_source_unchanged(before, after)
    delta = {
        table: counts_after.get(table, 0) - counts_before.get(table, 0)
        for table in FORMAL_TABLES
    }
    _assert_rejected_no_formal_write(candidates, delta)
    if qualification["state"] != "ready" and any(delta.values()):
        raise PilotError("qualification_rejection_formal_write")
    validated = any(row["stage3_passed"] for row in candidates)
    extracted = bool((intake_data or {}).get("counts", {}).get("extracted", 0))
    active = counts_after.get("capsules", 0) > counts_before.get("capsules", 0)
    primary_failure = qualification["raw_error_code"] or next(
        (
            str(row["primary_failure"])
            for row in candidates
            if row.get("primary_failure")
        ),
        None,
    )
    if qualification["state"] != "ready":
        farthest_gate = "qualification"
    elif any(row["farthest_gate"] == "stage3" for row in candidates):
        farthest_gate = "stage3"
    elif any(row["farthest_gate"] == "duplicate_resolution" for row in candidates):
        farthest_gate = "duplicate_resolution"
    else:
        farthest_gate = "intake"
    return {
        "project": {key: project[key] for key in ("id", "cohort", "repository_url", "commit", "entry_relpath", "expected_kind")},
        "qualification": qualification,
        "primary_failure": primary_failure,
        "farthest_gate": farthest_gate,
        "failure_family": (
            failure_family(primary_failure)
            if primary_failure
            else None
        ),
        "source": {
            "head": before["head"],
            "git_tree": before["git_tree"],
            "git_status_sha256_before": before["git_status_sha256"],
            "git_status_sha256_after": after["git_status_sha256"],
            "source_tree_before": before["source_tree"],
            "source_tree_after": after["source_tree"],
            "license_sha256": before["license_sha256"],
        },
        "model_selection": model_selection,
        "intake": intake_data,
        "candidates": candidates,
        "formal_rows": {"before": counts_before, "after": counts_after, "delta": delta},
        "outcome": {
            "intake_positive": extracted,
            "validated_positive": validated,
            "active": active,
            "product_asserted": None,
        },
    }


def summarize(projects: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    candidates = [row for project in projects for row in project.get("candidates", [])]
    raw_codes = Counter(
        str(project["primary_failure"])
        for project in projects
        if project.get("primary_failure")
    )
    family_candidates = Counter(
        str(row["failure_family"])
        for row in candidates
        if row.get("failure_family")
    )
    family_projects: dict[str, set[str]] = defaultdict(set)
    for project in projects:
        if project.get("failure_family"):
            family_projects[str(project["failure_family"])].add(project["project"]["id"])
    unclassified = int(family_candidates.get("unclassified", 0)) + sum(
        project.get("failure_family") == "unclassified" for project in projects
    )
    unclassified_reason_codes = sorted(
        {
            str(code)
            for row in candidates
            for code in row.get("all_reason_codes", [])
            if type(code) is str and failure_family(code) == "unclassified"
        }
    )
    unclassified += len(unclassified_reason_codes)
    positive_projects = [row for row in projects if row["project"]["cohort"] == "positive"]
    validated = [row for row in positive_projects if row["outcome"]["validated_positive"]]
    kinds = {
        str(candidate["capability_kind"])
        for project in validated
        for candidate in project.get("candidates", [])
        if candidate.get("stage3_passed") and candidate.get("capability_kind") in KINDS
    }
    product_values = [row["outcome"]["product_asserted"] for row in positive_projects]
    product_asserted: bool | None = (
        True
        if any(value is True for value in product_values)
        else False if any(value is False for value in product_values) else None
    )
    positive_scout = manifest.get("positive_scout") if type(manifest.get("positive_scout")) is dict else {}
    coverage_passed = len(validated) >= 3 and kinds == KINDS and product_asserted is True
    return {
        "funnel": {
            "screened": len(projects),
            "ready": sum(row["qualification"]["state"] == "ready" for row in projects),
            "extracted_any": sum(row["outcome"]["intake_positive"] for row in projects),
            "stage3_pass_any": sum(row["outcome"]["validated_positive"] for row in projects),
            "active": sum(row["outcome"]["active"] for row in projects),
            "product_asserted": sum(row["outcome"]["product_asserted"] is True for row in projects),
        },
        "candidate_count": len(candidates),
        "candidate_statuses": dict(sorted(Counter(row["candidate_status"] for row in candidates).items())),
        "raw_failure_codes": dict(sorted(raw_codes.items())),
        "qualification_failure_counts": dict(
            sorted(
                Counter(
                    str(project["qualification"]["raw_error_code"])
                    for project in projects
                    if project.get("qualification", {}).get("raw_error_code")
                ).items()
            )
        ),
        "failure_family_candidate_counts": dict(sorted(family_candidates.items())),
        "failure_family_project_counts": {
            family: len(ids) for family, ids in sorted(family_projects.items())
        },
        "unclassified_raw_error_codes": unclassified_reason_codes,
        "classification_gate": "passed" if unclassified == 0 else "failed",
        "positive_coverage": {
            "status": "passed" if coverage_passed else "partial",
            "eligible_projects_found": int(positive_scout.get("eligible_projects_found") or len(positive_projects)),
            "validated_project_count": len(validated),
            "validated_kinds": sorted(kinds),
            "end_to_end_business_assertion": product_asserted,
            "reason": None if coverage_passed else "positive_completion_gate_not_met",
        },
    }


def _assert_isolated_paths(
    workspace: Path, state_root: Path, output: Path | None = None
) -> tuple[Path, Path]:
    workspace = workspace.resolve()
    state_root = state_root.resolve()
    if (
        workspace == state_root
        or workspace in state_root.parents
        or state_root in workspace.parents
    ):
        raise PilotError("pilot_state_overlaps_source_workspace")
    if output is not None:
        output = output.resolve()
        if output == workspace or workspace in output.parents:
            raise PilotError("pilot_output_inside_source_workspace")
    return workspace, state_root


def run_manifest(manifest_path: Path, workspace: Path, state_root: Path) -> dict[str, Any]:
    workspace, state_root = _assert_isolated_paths(workspace, state_root)
    raw_manifest = _read_json(manifest_path)
    manifest = validate_manifest(raw_manifest)
    actual_head = _run_git(ROOT, "rev-parse", "HEAD").decode().strip()
    if actual_head != manifest["reweave_head"]:
        raise PilotError("manifest_reweave_head_mismatch")
    state_root.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    projects = [run_project(workspace, state_root, row) for row in manifest["projects"]]
    result = {
        "schema_version": EVIDENCE_SCHEMA,
        "manifest_sha256": _sha256_bytes(_json_bytes(raw_manifest)),
        "reweave": {
            "head": actual_head,
            "runner_sha256": _sha256_bytes(Path(__file__).read_bytes()),
            "rules": current_rules(),
        },
        "environment": _environment(),
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "projects": projects,
    }
    result["summary"] = summarize(projects, manifest)
    result["gate_status"] = (
        "passed" if result["summary"]["classification_gate"] == "passed" else "failed"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    try:
        workspace, state_root = _assert_isolated_paths(
            Path(args.workspace).expanduser(),
            Path(args.state_root).expanduser(),
            output,
        )
    except PilotError as exc:
        print(
            json.dumps(
                {
                    "schema_version": EVIDENCE_SCHEMA,
                    "gate_status": "failed",
                    "error_code": exc.code,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    try:
        result = run_manifest(
            Path(args.manifest).expanduser().resolve(),
            workspace,
            state_root,
        )
        exit_code = 0 if result["gate_status"] == "passed" else 1
    except PilotError as exc:
        result = {
            "schema_version": EVIDENCE_SCHEMA,
            "gate_status": "failed",
            "error_code": exc.code,
        }
        exit_code = 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_json_bytes(result) + b"\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
