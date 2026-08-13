"""Reweave app service — consistent initial state + engine delegation."""

from __future__ import annotations

import base64
import copy
import ctypes
import difflib
import errno
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unicodedata
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from functools import wraps
from html.parser import HTMLParser
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from pimos_lite.composer.module_native import (
    ADAPTER_V3_FORMAL_PRODUCT_COMPOSER_VERSION,
    ADAPTER_V4_FORMAL_PRODUCT_COMPOSER_VERSION,
    FORMAL_PRODUCT_COMPOSER_VERSION,
    MULTI_COMPUTATION_FORMAL_PRODUCT_COMPOSER_VERSION,
    PARAMETERIZED_FORMAL_PRODUCT_COMPOSER_VERSION,
    compose_capsule_product,
)
from pimos_lite.reweave_capsule_intake import (
    COMPUTATION_ADAPTER_CONTRACT_VERSION,
    EXTRACTION_CONTRACT_VERSION,
    REDACTION_RULES_VERSION,
    IntakeError,
    ReweaveCapsuleIntake,
)
from pimos_lite.reweave_canonical import canonical_json_digest
from pimos_lite.reweave_capsule_stage3 import (
    CAPTURE_MAPPING_V3,
    CAPTURE_MAPPING_V4,
    CAPTURE_RESUME_V1,
    CAPTURE_RESUME_V2,
    CAPTURE_RESUME_V3,
    COMPUTATION_ADAPTER_V2,
    COMPUTATION_ADAPTER_V3,
    COMPUTATION_ADAPTER_V4,
    FROZEN_REVIEW_ADMISSION_VERSION,
    FROZEN_UI_REVIEW_ADMISSION_AUTHORIZATION_VERSION,
    FROZEN_UI_REVIEW_ADMISSION_VERSION,
    OllamaSupervisor,
    ReweaveCapsuleStage3,
    SECURITY_RULES_VERSION,
    Stage3Error,
    SUPERVISION_RULES_VERSION,
    VALIDATION_CONTRACT_VERSION,
    inspect_ephemeral_computation_offers_v2,
)
from pimos_lite.reweave_capsule_store import (
    BACKUP_DIRECTORY,
    CANONICALIZATION_VERSION,
    CapsuleStoreError,
    CapsuleWarehouseStore,
    canonicalize_capsule,
)
from pimos_lite.reweave_data_contract import (
    DataContractError,
    data_contract_accepts,
    normalize_capsule_contracts,
)
from pimos_lite.reweave_process_environment import restricted_subprocess_environment
from pimos_lite.reweave_product_planner import (
    CAPABILITY_SOURCE_PROPOSAL_AUTHORIZATION_V2,
    CAPABILITY_SOURCE_PROPOSAL_OUTPUT_V2,
    PRODUCT_PLANNING_PHASES,
    ProductPlanner,
    ProductPlanningError,
)
from pimos_lite.reweave_plan_execution import (
    CANDIDATE_ACCEPTANCE_RECEIPT_VERSION,
    CANDIDATE_ACCEPTANCE_VERSION,
    MAX_CANDIDATE_ACCEPTANCE_CASES,
    MULTI_COMPUTATION_PLAN_EXECUTION_VERSION,
    PARAMETERIZED_PLAN_EXECUTION_VERSION,
    PLAN_EXECUTION_VERSION,
    CandidateAcceptanceError,
    PlanExecutionError,
    build_candidate_acceptance,
    build_candidate_acceptance_confirmation,
    canonical_bytes as plan_execution_bytes,
    canonical_digest as plan_execution_digest,
    compile_multi_computation_plan_execution,
    compile_parameterized_plan_execution,
    compile_plan_execution,
    evaluate_candidate_acceptance,
    validate_candidate_acceptance_confirmation,
)
from pimos_lite.reweave_javascript_source import (
    JAVASCRIPT_SOURCE_TYPE,
    JavascriptScopeSnapshot,
    JavascriptSourceError,
    JavascriptSourceService,
)
from pimos_lite.reweave_page_capability_contract import (
    verify_formal_capsule_identity,
)
from pimos_lite.reweave_source_registry import state_dir
from pimos_lite.reweave_static_web_target import (
    TARGET_AUTHORIZATION_MODE,
    StaticWebTargetError,
    analyze_static_web_target as analyze_static_web_target_profile,
    build_static_web_patch,
    capture_static_web_target,
    rejection_evidence,
    static_web_plan_identity,
)

APP_SERVICE_VERSION = "v2"
LUMO_LITE_MODE = "source_read_only_preview_write"
PRODUCT_MANIFEST_VERSION = "reweave_product_manifest.v1"
PRODUCTS_DIRNAME = "products"
PRODUCT_CANDIDATES_DIRNAME = "product_candidates"
_PRODUCT_ID = re.compile(r"product_[0-9a-f]{32}\Z")
_MANIFEST_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CANDIDATE_ID = re.compile(r"candidate_[0-9a-f]{32}\Z")
_CANDIDATE_TOKEN = re.compile(r"candidate_token_[0-9a-f]{48}\Z")
PUBLIC_PRODUCT_ACTIONS = frozenset(
    {
        "get_initial_state",
        "generate_product",
        "list_product_planning_models",
        "select_product_planning_model",
        "start_product_plan",
        "submit_product_plan_answers",
        "suggest_product_plan_action",
        "revise_product_plan",
        "get_product_plan_run",
        "cancel_product_plan_run",
        "get_product_plan_workspace",
        "record_product_capability_gap_decision",
        "prepare_product_capability_source_proposal",
        "start_product_capability_source_proposal",
        "start_product_capability_replan",
        "confirm_product_plan",
        "confirm_product_candidate_acceptance",
        "create_local_agent_handoff",
        "revoke_local_agent_handoff",
        "list_reusable_product_capabilities",
        "start_product_candidate",
        "get_product_candidate_run",
        "get_product_candidate",
        "read_product_candidate_file",
        "export_product_candidate",
        "analyze_static_web_target",
        "generate_static_web_patch",
        "get_latest_product_entry_path",
    }
)
LEGACY_WORKBENCH_ACTIONS = frozenset(
    {
        "verify_source_suggestions",
        "preview_governance_for_source",
        "create_review_queue_for_source",
        "update_review_decision",
        "promote_review_item",
        "list_warehouse_capsules",
        "update_capsule_status",
        "export_preview_package",
    }
)
SUPPORT_VIEWER_ACTIONS = frozenset(
    {
        "get_latest_preview_package",
        "get_preview_package",
        "compare_preview_packages",
    }
)
CAPSULE_MANAGEMENT_ACTIONS = frozenset(
    {
        "discover_source_root",
        "confirm_projects",
        "register_javascript_computation_source",
        "start_scan_javascript_computations",
        "start_inspect_computation_adapters",
        "start_create_computation_adapter",
        "start_refresh_project",
        "start_refresh_all",
        "get_intake_run",
        "cancel_intake_run",
        "list_supervision_models",
        "select_supervision_model",
        "list_review_items",
        "decide_review_item",
        "list_capability_groups",
        "rename_capability_group",
        "get_capsule_detail",
        "get_capsule_core_code_projection",
        "set_capsule_status",
        "create_backup",
        "list_backups",
        "inspect_backup",
        "restore_backup",
        "start_legacy_import",
        "retry_product_usage_registration",
    }
)

_OLLAMA_LOOPBACK = "http://127.0.0.1:11434"
_LEGACY_ID = re.compile(r"cap_[0-9a-f]{12}")
_TERMINAL_TASK_STATES = frozenset({"completed", "failed", "cancelled"})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise OSError("not_regular_file")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _copy_private_file(source: Path, target: Path) -> None:
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise OSError("target_exists")
    source_descriptor = os.open(
        source,
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    target_descriptor = -1
    try:
        if not stat.S_ISREG(os.fstat(source_descriptor).st_mode):
            raise OSError("source_not_regular")
        target_descriptor = os.open(
            target,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        while True:
            chunk = os.read(source_descriptor, 1024 * 1024)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                written = os.write(target_descriptor, view)
                if written <= 0:
                    raise OSError("copy_incomplete")
                view = view[written:]
        os.fchmod(target_descriptor, 0o600)
        os.fsync(target_descriptor)
    finally:
        os.close(source_descriptor)
        if target_descriptor >= 0:
            os.close(target_descriptor)
    directory_descriptor = os.open(
        target.parent,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _retired_v1_adapter_candidate(candidate: Any) -> bool:
    return bool(
        type(candidate) is dict
        and candidate.get("candidate_origin")
        == "deterministic_computation_adapter"
        and candidate.get("adapter_contract_version")
        == COMPUTATION_ADAPTER_CONTRACT_VERSION
    )


class _InactiveLegacyEngine:
    """Sentinel: formal App/CLI startup must not construct a historical engine."""


def _legacy_call(module: str, name: str, *args: Any, **kwargs: Any) -> Any:
    return getattr(import_module(module), name)(*args, **kwargs)


def LocalReweaveEngine(*args: Any, **kwargs: Any) -> Any:  # noqa: N802
    return _legacy_call(
        "pimos_lite.reweave_engine.local", "LocalReweaveEngine", *args, **kwargs
    )


def LunaHttpClient(*args: Any, **kwargs: Any) -> Any:  # noqa: N802
    return _legacy_call(
        "pimos_lite.reweave_luna_client", "LunaHttpClient", *args, **kwargs
    )


def load_draft(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call("pimos_lite.reweave_capsule_draft", "load_draft", *args, **kwargs)


def list_warehouse_capsules(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_capsule_warehouse",
        "list_warehouse_capsules",
        *args,
        **kwargs,
    )


def apply_capsule_status(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_capsule_warehouse",
        "update_capsule_status",
        *args,
        **kwargs,
    )


def load_verification(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_capsule_verifier", "load_verification", *args, **kwargs
    )


def verify_and_save(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_capsule_verifier", "verify_and_save", *args, **kwargs
    )


def load_governance_preview(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_governance_preview",
        "load_governance_preview",
        *args,
        **kwargs,
    )


def preview_and_save(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_governance_preview", "preview_and_save", *args, **kwargs
    )


def create_or_update_review_queue(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_review_queue",
        "create_or_update_review_queue",
        *args,
        **kwargs,
    )


def apply_review_decision(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_review_queue",
        "update_review_decision",
        *args,
        **kwargs,
    )


def execute_capsule_content_enrichment(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_capsule_content",
        "enrich_capsule_content",
        *args,
        **kwargs,
    )


def fetch_capsule_content(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_capsule_content", "get_capsule_content", *args, **kwargs
    )


def execute_promote_review_item(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_promote", "promote_review_item", *args, **kwargs
    )


def attach_luna_provenance(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_preview_pack", "attach_luna_provenance", *args, **kwargs
    )


def build_luna_provenance_record(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_preview_pack",
        "build_luna_provenance_record",
        *args,
        **kwargs,
    )


def compare_preview_packages_view(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_preview_viewer",
        "compare_preview_packages",
        *args,
        **kwargs,
    )


def fetch_latest_preview_package(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_preview_viewer",
        "get_latest_preview_package",
        *args,
        **kwargs,
    )


def fetch_preview_package(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_preview_viewer", "get_preview_package", *args, **kwargs
    )


def execute_preview_export(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_preview_export",
        "export_preview_package",
        *args,
        **kwargs,
    )


def build_reuse_suggestions_record(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_reuse_suggestions",
        "build_reuse_suggestions_record",
        *args,
        **kwargs,
    )


def load_reuse_suggestions(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_reuse_suggestions",
        "load_reuse_suggestions",
        *args,
        **kwargs,
    )


def save_reuse_suggestions(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_reuse_suggestions",
        "save_reuse_suggestions",
        *args,
        **kwargs,
    )


def get_source_box(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_source_registry", "get_source_box", *args, **kwargs
    )


def legacy_registry_path(*args: Any, **kwargs: Any) -> Any:
    if args or kwargs:
        raise TypeError("legacy_registry_path takes no arguments")
    return state_dir() / "source_boxes.json"


def load_summary(*args: Any, **kwargs: Any) -> Any:
    return _legacy_call(
        "pimos_lite.reweave_source_scanner", "load_summary", *args, **kwargs
    )


def legacy_warehouse_path(*args: Any, **kwargs: Any) -> Any:
    if args or kwargs:
        raise TypeError("legacy_warehouse_path takes no arguments")
    return state_dir() / "capsule_warehouse" / "capsules.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _strict_json_bytes(raw: bytes) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise ValueError("non_finite_json_number")

    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_constant,
    )


class ProductGenerationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _ProductShellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.styles: list[str] = []
        self.scripts: list[str] = []
        self.csp: list[str] = []
        self.inline_script = False
        self.inline_style = False
        self._script_depth = 0
        self._style_depth = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {name.casefold(): str(value or "") for name, value in attrs}
        lowered = tag.casefold()
        if lowered == "link" and values.get("rel", "").casefold() == "stylesheet":
            self.styles.append(values.get("href", ""))
        if lowered == "script":
            source = values.get("src", "")
            if source:
                self.scripts.append(source)
            else:
                self.inline_script = True
            self._script_depth += 1
        if lowered == "style":
            self.inline_style = True
            self._style_depth += 1
        if (
            lowered == "meta"
            and values.get("http-equiv", "").casefold()
            == "content-security-policy"
        ):
            self.csp.append(" ".join(values.get("content", "").split()))

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._script_depth:
            self._script_depth -= 1
        if tag.casefold() == "style" and self._style_depth:
            self._style_depth -= 1


def _canonical_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ProductGenerationError("product_manifest_invalid") from exc
    if _strict_json_bytes(encoded) != manifest:
        raise ProductGenerationError("product_manifest_not_canonical")
    return encoded


def _product_directory() -> Path:
    return state_dir() / PRODUCTS_DIRNAME


def _safe_product_relative(value: object) -> str:
    if type(value) is not str or not value or "\\" in value:
        raise ProductGenerationError("product_file_path_invalid")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ProductGenerationError("product_file_path_invalid")
    return pure.as_posix()


def _write_product_file(root: Path, relative: str, content: str | bytes) -> None:
    logical = _safe_product_relative(relative)
    target = root.joinpath(*PurePosixPath(logical).parts)
    current = root
    for part in PurePosixPath(logical).parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ProductGenerationError("product_file_parent_unsafe")
        current.mkdir(mode=0o700, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise ProductGenerationError("product_file_duplicate")
    data = content.encode("utf-8") if type(content) is str else content
    if type(data) is not bytes:
        raise ProductGenerationError("product_file_content_invalid")
    target.write_bytes(data)
    if os.name == "posix":
        target.chmod(0o600)


def _fsync_product_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_symlink():
            raise ProductGenerationError("product_file_unsafe")
        if path.is_file():
            with path.open("r+b") as handle:
                os.fsync(handle.fileno())
        elif path.is_dir() and os.name == "posix":
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    if os.name == "posix":
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


def _safe_export_directory_name(product_name: object, digest: object) -> str:
    if (
        type(product_name) is not str
        or type(digest) is not str
        or _MANIFEST_DIGEST.fullmatch(digest) is None
    ):
        raise ProductGenerationError("product_candidate_export_request_invalid")
    normalized = unicodedata.normalize("NFC", product_name)
    safe = "".join(
        "-"
        if ord(character) < 32
        or ord(character) == 127
        or character in '<>:"/\\|?*'
        else character
        for character in normalized
    )
    safe = re.sub(r"[\s-]+", "-", safe).strip(" .-")
    if not safe:
        safe = "reweave-product"
    if safe.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        safe = f"reweave-{safe}"
    suffix = f"-{digest[:12]}"
    byte_limit = 240 - len(os.fsencode(suffix))
    while safe and len(os.fsencode(safe)) > byte_limit:
        safe = safe[:-1]
    return f"{safe.rstrip(' .-') or 'reweave-product'}{suffix}"


def _safe_export_parent(value: object) -> Path:
    if (
        type(value) is not str
        or not value
        or len(value) > 4096
        or "\x00" in value
        or not Path(value).is_absolute()
    ):
        raise ProductGenerationError(
            "product_candidate_export_destination_invalid"
        )
    parent = Path(os.path.abspath(value))
    if parent == Path(parent.anchor):
        raise ProductGenerationError(
            "product_candidate_export_destination_invalid"
        )
    return parent


def _validated_export_paths(files: object) -> list[str]:
    if type(files) is not list or not files:
        raise ProductGenerationError("product_candidate_invalid")
    paths: list[str] = []
    components: dict[tuple[tuple[str, ...], str], str] = {}
    for item in files:
        if type(item) is not dict:
            raise ProductGenerationError("product_candidate_invalid")
        logical = _safe_product_relative(item.get("path"))
        if unicodedata.normalize("NFC", logical) != logical:
            raise ProductGenerationError("product_candidate_export_path_unsafe")
        parts = PurePosixPath(logical).parts
        for index, part in enumerate(parts):
            if (
                not part
                or part.endswith((" ", "."))
                or any(
                    ord(character) < 32
                    or ord(character) == 127
                    or character in '<>:"\\|?*'
                    for character in part
                )
                or part.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
            ):
                raise ProductGenerationError(
                    "product_candidate_export_path_unsafe"
                )
            parent = tuple(value.casefold() for value in parts[:index])
            key = (parent, part.casefold())
            previous = components.get(key)
            if previous is not None and previous != part:
                raise ProductGenerationError(
                    "product_candidate_export_path_conflict"
                )
            components[key] = part
        paths.append(logical)
    if len(paths) != len(set(paths)):
        raise ProductGenerationError("product_candidate_invalid")
    return paths


def _read_export_file(root: Path, metadata: dict[str, Any]) -> bytes:
    logical = _safe_product_relative(metadata["path"])
    path = root.joinpath(*PurePosixPath(logical).parts)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ProductGenerationError("product_candidate_invalid") from exc
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise ProductGenerationError("product_candidate_invalid")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
    finally:
        os.close(descriptor)
    if (
        len(data) != metadata["size_bytes"]
        or hashlib.sha256(data).hexdigest() != metadata["sha256"]
    ):
        raise ProductGenerationError("product_candidate_invalid")
    return data


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _open_no_follow_directory(
    path: Path,
) -> tuple[int, tuple[tuple[int, int], ...]]:
    if not path.is_absolute() or path == Path(path.anchor):
        raise ProductGenerationError(
            "product_candidate_export_destination_invalid"
        )
    current = os.open(path.anchor, _directory_open_flags())
    identities = [
        (os.fstat(current).st_dev, os.fstat(current).st_ino)
    ]
    try:
        for part in path.parts[1:]:
            child = os.open(
                part,
                _directory_open_flags(),
                dir_fd=current,
            )
            details = os.fstat(child)
            if not stat.S_ISDIR(details.st_mode):
                os.close(child)
                raise OSError(errno.ENOTDIR, "not_directory")
            os.close(current)
            current = child
            identities.append((details.st_dev, details.st_ino))
    except OSError as exc:
        os.close(current)
        raise ProductGenerationError(
            "product_candidate_export_destination_unsafe"
        ) from exc
    return current, tuple(identities)


def _open_export_directory(path: Path, application_state: Path) -> int:
    try:
        state_path = Path(os.path.abspath(application_state)).resolve(
            strict=True
        )
    except OSError as exc:
        raise ProductGenerationError(
            "product_candidate_export_destination_unsafe"
        ) from exc
    state_descriptor, _state_chain = _open_no_follow_directory(state_path)
    try:
        state_details = os.fstat(state_descriptor)
        state_identity = (state_details.st_dev, state_details.st_ino)
    finally:
        os.close(state_descriptor)
    descriptor, destination_chain = _open_no_follow_directory(path)
    if state_identity in destination_chain:
        os.close(descriptor)
        raise ProductGenerationError(
            "product_candidate_export_destination_unsafe"
        )
    return descriptor


def _open_export_directory_at(parent: int, name: str) -> int:
    try:
        descriptor = os.open(
            name,
            _directory_open_flags(),
            dir_fd=parent,
        )
    except OSError as exc:
        raise ProductGenerationError(
            "product_candidate_export_destination_unsafe"
        ) from exc
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ProductGenerationError(
            "product_candidate_export_destination_unsafe"
        )
    return descriptor


def _write_export_file(root: int, logical: str, data: bytes) -> None:
    current = os.dup(root)
    try:
        for part in PurePosixPath(logical).parts[:-1]:
            try:
                child = _open_export_directory_at(current, part)
            except ProductGenerationError:
                try:
                    os.mkdir(part, 0o700, dir_fd=current)
                except FileExistsError:
                    pass
                child = _open_export_directory_at(current, part)
            os.fchmod(child, 0o700)
            os.close(current)
            current = child
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(
            PurePosixPath(logical).name,
            flags,
            0o600,
            dir_fd=current,
        )
        try:
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("export_write_incomplete")
                view = view[written:]
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(current)
    except OSError as exc:
        raise ProductGenerationError(
            "product_candidate_export_destination_unsafe"
        ) from exc
    finally:
        os.close(current)


def _read_export_file_at(
    root: int,
    metadata: dict[str, Any],
) -> bytes:
    current = os.dup(root)
    try:
        for part in PurePosixPath(metadata["path"]).parts[:-1]:
            child = _open_export_directory_at(current, part)
            os.close(current)
            current = child
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(
            PurePosixPath(metadata["path"]).name,
            flags,
            dir_fd=current,
        )
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode):
                raise ProductGenerationError("product_candidate_invalid")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            data = b"".join(chunks)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ProductGenerationError("product_candidate_invalid") from exc
    finally:
        os.close(current)
    if (
        len(data) != metadata["size_bytes"]
        or hashlib.sha256(data).hexdigest() != metadata["sha256"]
    ):
        raise ProductGenerationError("product_candidate_invalid")
    return data


def _verify_export_tree(
    root: int,
    files: list[dict[str, Any]],
    *,
    error_code: str,
) -> None:
    expected_files = {item["path"]: item for item in files}
    expected_directories = {
        PurePosixPath(*PurePosixPath(logical).parts[:index]).as_posix()
        for logical in expected_files
        for index in range(1, len(PurePosixPath(logical).parts))
    }
    actual_files: set[str] = set()
    actual_directories: set[str] = set()

    def visit(directory: int, prefix: PurePosixPath) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise ProductGenerationError(error_code) from exc
        for entry in entries:
            try:
                details = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ProductGenerationError(error_code) from exc
            logical = (
                prefix / entry.name
                if prefix.parts
                else PurePosixPath(entry.name)
            ).as_posix()
            if stat.S_ISLNK(details.st_mode):
                raise ProductGenerationError(error_code)
            if stat.S_ISDIR(details.st_mode):
                if details.st_mode & 0o777 != 0o700:
                    raise ProductGenerationError(error_code)
                actual_directories.add(logical)
                child = _open_export_directory_at(directory, entry.name)
                try:
                    visit(child, PurePosixPath(logical))
                finally:
                    os.close(child)
                continue
            metadata = expected_files.get(logical)
            if (
                not stat.S_ISREG(details.st_mode)
                or metadata is None
                or details.st_mode & 0o777 != 0o600
            ):
                raise ProductGenerationError(error_code)
            try:
                _read_export_file_at(root, metadata)
            except ProductGenerationError as exc:
                raise ProductGenerationError(error_code) from exc
            actual_files.add(logical)

    if os.fstat(root).st_mode & 0o777 != 0o700:
        raise ProductGenerationError(error_code)
    visit(root, PurePosixPath())
    if (
        actual_files != set(expected_files)
        or actual_directories != expected_directories
    ):
        raise ProductGenerationError(error_code)


def _remove_export_tree_at(
    parent: int,
    name: str,
    expected_identity: tuple[int, int],
) -> None:
    try:
        details = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(details.st_mode)
            or stat.S_ISLNK(details.st_mode)
            or (details.st_dev, details.st_ino) != expected_identity
        ):
            return
        root = _open_export_directory_at(parent, name)
    except (OSError, ProductGenerationError):
        return
    actual = os.fstat(root)
    if (actual.st_dev, actual.st_ino) != expected_identity:
        os.close(root)
        return

    def clear(directory: int) -> None:
        for entry in list(os.scandir(directory)):
            details = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(
                details.st_mode
            ):
                child = _open_export_directory_at(directory, entry.name)
                try:
                    clear(child)
                finally:
                    os.close(child)
                os.rmdir(entry.name, dir_fd=directory)
            else:
                os.unlink(entry.name, dir_fd=directory)

    try:
        clear(root)
    finally:
        os.close(root)
    os.rmdir(name, dir_fd=parent)


def _rename_export_no_replace(
    parent: int,
    source_name: str,
    target_name: str,
) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = library.renameatx_np
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        result = function(
            parent,
            os.fsencode(source_name),
            parent,
            os.fsencode(target_name),
            0x00000004,
        )
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        function = library.renameat2
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        result = function(
            parent,
            os.fsencode(source_name),
            parent,
            os.fsencode(target_name),
            0x00000001,
        )
    else:
        raise ProductGenerationError(
            "product_candidate_export_platform_unsupported"
        )
    if result == 0:
        return
    failure = ctypes.get_errno()
    if failure in {errno.EEXIST, errno.ENOTEMPTY}:
        raise ProductGenerationError("product_candidate_export_conflict")
    raise ProductGenerationError("product_candidate_export_failed")


def _candidate_content_digest(
    execution_digest: str,
    composer_version: str,
    entry: dict[str, str],
    files: list[dict[str, Any]],
) -> str:
    content_files = [
        {
            "path": item["path"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
        }
        for item in files
        if item["path"]
        not in {"manifest.json", "quality_gate.json", "runtime_validation.json"}
    ]
    return plan_execution_digest(
        {
            "schema_version": "product_candidate_content.v1",
            "execution_digest": execution_digest,
            "composer_version": composer_version,
            "entry": entry,
            "files": content_files,
        }
    )


def _validate_product_static(root: Path) -> dict[str, Any]:
    required = ("index.html", "styles.css", "app.js")
    if any(
        (root / name).is_symlink() or not (root / name).is_file()
        for name in required
    ):
        raise ProductGenerationError("product_required_file_missing")
    try:
        html_text = (root / "index.html").read_text(encoding="utf-8")
        css_text = (root / "styles.css").read_text(encoding="utf-8")
        app_text = (root / "app.js").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ProductGenerationError("product_text_file_invalid") from exc
    parser = _ProductShellParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception as exc:
        raise ProductGenerationError("product_html_invalid") from exc
    expected_csp = (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "font-src 'none'; connect-src 'none'; object-src 'none'; frame-src 'none'; "
        "worker-src 'none'; base-uri 'none'; form-action 'none'"
    )
    checks = {
        "root_stylesheet_exact": parser.styles == ["./styles.css"],
        "root_script_exact": parser.scripts == ["./app.js"],
        "inline_code_absent": not parser.inline_script and not parser.inline_style,
        "strict_csp": parser.csp == [expected_csp],
        "css_scoped": "__CAPSULE_ROOT__" not in css_text,
        "network_apis_absent": not re.search(
            r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b|https?://",
            app_text,
        ),
    }
    node = os.environ.get("REWEAVE_NODE") or shutil.which("node")
    if not node:
        raise ProductGenerationError("node_unavailable")
    checked = subprocess.run(
        [node, "--check", str(root / "app.js")],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=restricted_subprocess_environment(),
    )
    checks["javascript_syntax"] = checked.returncode == 0 and not checked.stderr
    if not all(checks.values()):
        raise ProductGenerationError("product_static_validation_failed")
    return {
        "schema_version": "reweave_product_quality.v1",
        "status": "passed",
        "acceptance_scope": "static_product_package",
        "checks": [{"name": name, "passed": passed} for name, passed in checks.items()],
        "source_project_write": False,
    }


def _product_worker_environment(temporary: Path) -> dict[str, str]:
    return restricted_subprocess_environment({
        "HOME": str(temporary),
        "TMPDIR": str(temporary),
        "TMP": str(temporary),
        "TEMP": str(temporary),
        "XDG_CACHE_HOME": str(temporary / "cache"),
        "XDG_CONFIG_HOME": str(temporary / "config"),
        "XDG_DATA_HOME": str(temporary / "data"),
        "APPDATA": str(temporary / "appdata"),
        "LOCALAPPDATA": str(temporary / "localappdata"),
        "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "offscreen"),
        "QTWEBENGINE_CHROMIUM_FLAGS": os.environ.get(
            "QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu"
        ),
    })


def _desktop_worker_python() -> str:
    configured = os.environ.get("REWEAVE_DESKTOP_PYTHON")
    root = Path(__file__).resolve().parents[1]
    candidates = (
        [Path(configured).expanduser()]
        if configured
        else [
            root / ".venv-reweave" / "bin" / "python",
            root / ".venv-reweave" / "Scripts" / "python.exe",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    try:
        import PySide6  # noqa: F401
    except ImportError as exc:
        raise ProductGenerationError("pyside6_unavailable") from exc
    return sys.executable


def _validate_product_runtime(root: Path) -> dict[str, Any]:
    worker = Path(__file__).with_name("reweave_capsule_worker.py")
    allowed = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    with tempfile.TemporaryDirectory(prefix="reweave-product-qweb-") as temporary:
        environment = _product_worker_environment(Path(temporary))
        completed = subprocess.run(
            [_desktop_worker_python(), str(worker)],
            input=json.dumps(
                {
                    "mode": "qweb",
                    "entry": "index.html",
                    "allow_files": allowed,
                    "require_main_landmark": True,
                },
                separators=(",", ":"),
            ),
            capture_output=True,
            text=True,
            cwd=root,
            timeout=12,
            check=False,
            env=environment,
        )
    if completed.returncode or len(completed.stdout.encode("utf-8")) > 1024 * 1024:
        raise ProductGenerationError("product_qweb_worker_failed")
    try:
        result = _strict_json_bytes(completed.stdout.encode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ProductGenerationError("product_qweb_worker_failed") from exc
    if (
        type(result) is not dict
        or result.get("status") != "passed"
        or result.get("acceptance_scope") != "real_qwebengine_runtime"
        or result.get("blocked_requests") != []
        or result.get("console_messages") != []
    ):
        raise ProductGenerationError(
            str(result.get("error_code") or "product_qweb_validation_failed")
            if type(result) is dict
            else "product_qweb_validation_failed"
        )
    return result


def _validate_product_acceptance(
    root: Path,
    contract: dict[str, Any],
) -> dict[str, Any]:
    worker = Path(__file__).with_name("reweave_capsule_worker.py")
    allowed = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    cases = [
        {"case_id": item["case_id"], "input": item["input"]}
        for item in contract["cases"]
    ]
    with tempfile.TemporaryDirectory(
        prefix="reweave-product-acceptance-"
    ) as temporary:
        environment = _product_worker_environment(Path(temporary))
        completed = subprocess.run(
            [_desktop_worker_python(), str(worker)],
            input=json.dumps(
                {
                    "mode": "qweb_acceptance",
                    "entry": "index.html",
                    "allow_files": allowed,
                    "cases": cases,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
            capture_output=True,
            text=True,
            cwd=root,
            timeout=12,
            check=False,
            env=environment,
        )
    if completed.returncode or len(completed.stdout.encode("utf-8")) > 1024 * 1024:
        raise ProductGenerationError("candidate_acceptance_worker_failed")
    try:
        result = _strict_json_bytes(completed.stdout.encode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ProductGenerationError("candidate_acceptance_worker_failed") from exc
    if (
        type(result) is not dict
        or set(result)
        != {
            "schema_version",
            "status",
            "cases",
            "blocked_requests",
            "console_messages",
            "acceptance_scope",
        }
        or result.get("acceptance_scope") != "candidate_business_acceptance"
        or result.get("blocked_requests") != []
        or result.get("console_messages") != []
        or result.get("status") != "completed"
    ):
        code = (
            str(result.get("error_code"))
            if type(result) is dict
            and re.fullmatch(
                r"[a-z][a-z0-9_]{1,95}", str(result.get("error_code") or "")
            )
            else "candidate_acceptance_worker_failed"
        )
        raise ProductGenerationError(code)
    return {
        "schema_version": result["schema_version"],
        "status": result["status"],
        "cases": result["cases"],
    }


def _serialized_management(method: Any) -> Any:
    @wraps(method)
    def wrapped(self: "ReweaveAppService", *args: Any, **kwargs: Any) -> Any:
        with self._management_lock:
            if self._management_closed:
                return self._error("management_closed")
            if self._restore_pending:
                return self._error("restore_in_progress")
        with self._capsule_operation_lock:
            with self._management_lock:
                if self._management_closed:
                    return self._error("management_closed")
                if self._restore_pending:
                    return self._error("restore_in_progress")
            return method(self, *args, **kwargs)

    return wrapped


def release_boundary_for_action(action: str) -> str:
    if action in PUBLIC_PRODUCT_ACTIONS:
        return "public_product"
    if action in LEGACY_WORKBENCH_ACTIONS:
        return "legacy_workbench"
    if action in SUPPORT_VIEWER_ACTIONS:
        return "support_viewer"
    if action in CAPSULE_MANAGEMENT_ACTIONS:
        return "capsule_management"
    return "unknown"


def public_product_actions() -> tuple[str, ...]:
    return tuple(sorted(PUBLIC_PRODUCT_ACTIONS))


def legacy_workbench_actions() -> tuple[str, ...]:
    return tuple(sorted(LEGACY_WORKBENCH_ACTIONS))


class ReweaveAppService:
    """Thin facade over ReweaveEngine; enriches get_initial_state metadata."""

    def __init__(
        self,
        engine: Any | None = None,
        *,
        capsule_store: CapsuleWarehouseStore | None = None,
        ollama_base_url: str = _OLLAMA_LOOPBACK,
    ) -> None:
        self._engine = engine or _InactiveLegacyEngine()
        self._capsule_store = capsule_store or CapsuleWarehouseStore()
        self._ollama_base_url = ollama_base_url
        self._capsule_intake = ReweaveCapsuleIntake(self._capsule_store)
        self._capsule_supervisor = OllamaSupervisor(self._capsule_store)
        self._capsule_stage3 = ReweaveCapsuleStage3(
            self._capsule_store,
            intake=self._capsule_intake,
            supervisor=self._capsule_supervisor,
        )
        self._javascript_sources = JavascriptSourceService(self._capsule_store)
        self._product_planner = ProductPlanner(
            self._capsule_store.path.parent / "product_workspaces",
            ollama_base_url,
        )
        self._management_lock = threading.RLock()
        self._capsule_operation_lock = threading.RLock()
        self._management_executor: ThreadPoolExecutor | None = None
        self._management_tasks: dict[str, dict[str, Any]] = {}
        self._restore_pending = False
        self._management_closed = False
        self._management_recovered = False
        self._management_rules_checked = False
        # Process-local by contract: source bytes, graphs, and offers never enter SQLite.
        self._javascript_capture_sessions: dict[str, dict[str, Any]] = {}

    @property
    def engine(self) -> Any:
        return self._engine

    def _ensure_legacy_engine(self) -> Any:
        if type(self._engine) is _InactiveLegacyEngine:
            with self._management_lock:
                if type(self._engine) is _InactiveLegacyEngine:
                    self._engine = _legacy_call(
                        "pimos_lite.reweave_engine.factory",
                        "create_reweave_engine",
                    )
        return self._engine

    def _is_lumo_lite(self) -> bool:
        self._ensure_legacy_engine()
        return self._engine.__class__.__name__ == "LumoLiteReweaveEngine"

    def _is_lumo(self) -> bool:
        self._ensure_legacy_engine()
        return self._engine.__class__.__name__ == "LumoReweaveEngine"

    def _lumo_lite_disabled(self, action: str, **extra: Any) -> dict[str, Any]:
        result = {
            "ok": False,
            "engine": "lumo_lite",
            "mode": LUMO_LITE_MODE,
            "error": "lumo_lite_read_only",
            "action": action,
            "release_boundary": release_boundary_for_action(action),
        }
        result.update(extra)
        return result

    def get_initial_state(self) -> dict[str, Any]:
        with self._management_lock:
            restore_pending = self._restore_pending
        capsules = [] if restore_pending else self._formal_capsule_summaries()
        products = [] if restore_pending else self._product_records()
        registered = [item for item in products if item["status"] == "registered"]
        latest = registered[0] if registered else None
        planning_result = self._product_planner.initial_state()
        planning = (
            planning_result.get("data")
            if planning_result.get("ok") is True
            and type(planning_result.get("data")) is dict
            else {
                "schema_version": "product_planning_state.v1",
                "available": False,
                "selected_model": None,
                "workspaces": [],
                "candidate_generation_available": False,
                "product_generation_performed": False,
            }
        )
        state: dict[str, Any] = {
            "mode": "desktop_app",
            "backend": "sqlite_capsule_warehouse",
            "engine": "sqlite_capsule_warehouse",
            "engineStatus": {
                "engine": "sqlite_capsule_warehouse",
                "available": True,
                "capabilities": {"formalCapsuleGeneration": True},
            },
            "bridge": True,
            "appVersion": "0.4.0",
            "appService": APP_SERVICE_VERSION,
            "skipWelcome": True,
            "canChooseSourceFolder": False,
            "canScanSourceBox": False,
            "canDraftCapsules": False,
            "canPromoteDrafts": False,
            "canGeneratePreview": False,
            "canGenerateProduct": True,
            "canPlanProduct": planning["available"] is True,
            "canOpenPreviewFolder": False,
            "sourceBoxes": [],
            "capsules": capsules,
            "warehouseCapsules": capsules,
            "useLocalCapsules": bool(capsules),
            "history": [self._product_history_item(item) for item in registered],
            "productPlanning": planning,
        }
        if latest is not None:
            state["previewPath"] = str(latest["path"])
            state["generatedPackage"] = self._generated_package(latest)
        management = self._capsule_management_state()
        management["generationActive"] = True
        management["capabilities"]["generationFromSqlite"] = True
        management["productStatusCounts"] = {
            status: sum(1 for item in products if item["status"] == status)
            for status in sorted({str(item["status"]) for item in products})
        }
        management["recoverableProducts"] = [
            {
                "product_id": str(item["product_id"]),
                "status": "usage_registration_incomplete",
            }
            for item in products
            if item["status"] == "usage_registration_incomplete"
        ]
        pre_restore_backup = self._latest_pre_restore_backup_path()
        management["historicalProducts"] = [
            {
                "product_id": str(item["product_id"]),
                "status": "historical_version_unavailable_after_restore",
                "manifest_digest": str(item["manifest_digest"]),
                "pre_restore_backup_path": pre_restore_backup,
            }
            for item in products
            if item["status"] == "historical_version_unavailable_after_restore"
        ]
        state["capsuleIngestionV1"] = management
        if management.get("databaseStatus") in {
            "restore_in_progress",
            "unavailable",
        }:
            state["canGenerateProduct"] = False
            state["engineStatus"]["available"] = False
        return state

    def _formal_capsule_summaries(self) -> list[dict[str, Any]]:
        if not self._capsule_store.path.is_file():
            return []
        try:
            self._ensure_capsule_management()
            with self._capsule_store.read_connection() as connection:
                rows = connection.execute(
                    "SELECT c.*, g.display_name, cv.* FROM capsules c "
                    "JOIN capability_groups g ON g.capability_key = c.capability_key "
                    "JOIN capsule_versions cv ON cv.version_id = c.current_version_id "
                    "WHERE c.status = 'active' ORDER BY g.display_name, c.role_key, c.variant_key"
                ).fetchall()
        except (CapsuleStoreError, OSError, RuntimeError, sqlite3.Error):
            return []
        result: list[dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            eligible = self._capsule_stage3._eligible_exact(row)
            result.append(
                {
                    "id": str(row["capsule_id"]),
                    "capsule_id": str(row["capsule_id"]),
                    "version_id": str(row["version_id"]),
                    "name": str(row["display_name"]),
                    "type": str(row["capability_kind"]),
                    "role": str(row["role_key"]),
                    "status": "active",
                    "formal_version": True,
                    "generation_eligible": eligible,
                    "tags": [
                        str(row["capability_key"]),
                        str(row["role_key"]),
                        str(row["variant_key"]),
                    ],
                    "preview": [
                        f"{row['capability_key']} / {row['role_key']} / {row['variant_key']}",
                        f"version {row['version_number']}",
                    ],
                }
            )
        return result

    def _product_planning_catalog(self) -> dict[str, Any]:
        """Return an exact, read-only and code-free planning capsule catalog."""
        if not self._capsule_store.path.is_file():
            return {"warehouse_revision": 0, "capsules": []}
        try:
            with self._capsule_store.read_connection() as connection:
                revision_row = connection.execute(
                    "SELECT warehouse_revision FROM warehouse_state "
                    "WHERE singleton_id = 1"
                ).fetchone()
                rows = connection.execute(
                    "SELECT c.*, g.display_name, cv.* FROM capsules c "
                    "JOIN capability_groups g ON g.capability_key = c.capability_key "
                    "JOIN capsule_versions cv ON cv.version_id = c.current_version_id "
                    "WHERE c.status = 'active' "
                    "ORDER BY c.capsule_id, cv.version_id"
                ).fetchall()
        except (CapsuleStoreError, OSError, RuntimeError, sqlite3.Error) as exc:
            raise ProductGenerationError("product_planning_catalog_unavailable") from exc
        capsules: list[dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            if not self._capsule_stage3._eligible_exact(row):
                continue
            try:
                input_contract, output_contract, error_contract = (
                    normalize_capsule_contracts(
                        str(row["capability_kind"]),
                        json.loads(str(row["input_contract_json"])),
                        json.loads(str(row["output_contract_json"])),
                        json.loads(str(row["error_contract_json"])),
                    )
                )
            except (DataContractError, json.JSONDecodeError, TypeError) as exc:
                raise ProductGenerationError(
                    "product_planning_catalog_unavailable"
                ) from exc
            capsules.append(
                {
                    "capsule_id": str(row["capsule_id"]),
                    "version_id": str(row["version_id"]),
                    "display_name": str(row["display_name"]),
                    "capability_key": str(row["capability_key"]),
                    "role_key": str(row["role_key"]),
                    "variant_key": str(row["variant_key"]),
                    "capability_kind": str(row["capability_kind"]),
                    "canonical_hash": str(row["canonical_hash"]),
                    "identity_status": "formal_exact_version",
                    "input_contract": input_contract,
                    "output_contract": output_contract,
                    "error_contract": error_contract,
                }
            )
        return {
            "warehouse_revision": int(revision_row[0]) if revision_row else 0,
            "capsules": capsules,
        }

    @staticmethod
    def _capability_source_proposal_capture_request(
        authorization: dict[str, Any],
        offer: dict[str, Any],
        proposal: dict[str, Any] | None = None,
    ) -> tuple[dict[str, str], dict[str, Any]]:
        if (
            type(authorization) is not dict
            or type(offer) is not dict
            or offer.get("module_relpath") != "capability.js"
            or offer.get("export_name") != "compute"
            or type(offer.get("target_binding_id")) is not str
            or re.fullmatch(
                r"[0-9a-f]{64}",
                str(offer["target_binding_id"]),
            )
            is None
            or type(offer.get("parameters")) is not list
        ):
            raise ProductPlanningError(
                "capability_source_proposal_capture_invalid"
            )
        input_contract, output_contract, _error_contract = (
            normalize_capsule_contracts(
                "computation",
                authorization.get("input_contract"),
                authorization.get("output_contract"),
                authorization.get("error_contract"),
            )
        )
        input_properties = input_contract["properties"]
        output_properties = output_contract["properties"]
        input_fields = sorted(
            input_properties,
            key=lambda field: field.encode("utf-8"),
        )
        parameters = offer["parameters"]
        if (
            len(parameters) != len(input_fields)
            or any(
                type(parameter) is not dict
                or set(parameter)
                != {"parameter_binding_id", "name"}
                or parameter.get("name") != f"arg{index}"
                or re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(parameter.get("parameter_binding_id") or ""),
                )
                is None
                for index, parameter in enumerate(parameters)
            )
        ):
            raise ProductPlanningError(
                "capability_source_proposal_capture_invalid"
            )
        arguments = []
        for field, parameter in zip(input_fields, parameters):
            contract = input_properties[field]
            if (
                set(contract) != {"type", "minimum", "maximum"}
                or contract["type"] != "integer"
                or type(contract["minimum"]) is not int
                or type(contract["maximum"]) is not int
            ):
                if contract == {"type": "boolean"}:
                    arguments.append(
                        {
                            "parameter_binding_id": parameter[
                                "parameter_binding_id"
                            ],
                            "input_field": field,
                            "kind": "boolean",
                        }
                    )
                    continue
                raise ProductPlanningError(
                    "capability_source_proposal_capture_invalid"
                )
            arguments.append(
                {
                    "parameter_binding_id": parameter[
                        "parameter_binding_id"
                    ],
                    "input_field": field,
                    "kind": "integer",
                    "minimum": contract["minimum"],
                    "maximum": contract["maximum"],
                }
            )
        result_field = authorization.get("result_field")
        passthrough_fields = authorization.get("passthrough_fields")
        adapter_version = authorization.get("adapter_contract_version")
        if (
            type(result_field) is not str
            or result_field not in output_properties
            or type(passthrough_fields) is not list
            or adapter_version
            not in {
                COMPUTATION_ADAPTER_V2,
                COMPUTATION_ADAPTER_V3,
                COMPUTATION_ADAPTER_V4,
            }
        ):
            raise ProductPlanningError(
                "capability_source_proposal_capture_invalid"
            )
        examples: list[dict[str, Any]] = []
        seen_inputs: dict[str, str] = {}

        def add_example(input_value: Any, expected_value: Any) -> None:
            if (
                not data_contract_accepts(input_contract, input_value)
                or not data_contract_accepts(output_contract, expected_value)
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_capture_invalid"
                )
            input_digest = canonical_json_digest(input_value)
            expected_digest = canonical_json_digest(expected_value)
            previous = seen_inputs.get(input_digest)
            if previous is not None:
                if previous != expected_digest:
                    raise ProductPlanningError(
                        "capability_source_proposal_capture_invalid"
                    )
                return
            seen_inputs[input_digest] = expected_digest
            examples.append(
                {
                    "input": copy.deepcopy(input_value),
                    "expected": copy.deepcopy(expected_value),
                }
            )

        if adapter_version == COMPUTATION_ADAPTER_V4:
            witnesses = (
                proposal.get("witnesses")
                if type(proposal) is dict
                else None
            )
            result_enum = authorization.get("result_enum")
            if (
                authorization.get("schema_version")
                != CAPABILITY_SOURCE_PROPOSAL_AUTHORIZATION_V2
                or authorization.get("capture_mapping_schema")
                != CAPTURE_MAPPING_V4
                or authorization.get("proof_schema")
                != "source_graph_proof.v2"
                or passthrough_fields
                or type(result_enum) is not list
                or not result_enum
                or type(proposal) is not dict
                or proposal.get("schema")
                != CAPABILITY_SOURCE_PROPOSAL_OUTPUT_V2
                or type(witnesses) is not list
                or len(witnesses) != len(result_enum)
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_capture_invalid"
                )
            actual_results: list[str] = []
            for witness in witnesses:
                if (
                    type(witness) is not dict
                    or set(witness)
                    != {"input", "expected_scalar_result"}
                ):
                    raise ProductPlanningError(
                        "capability_source_proposal_capture_invalid"
                    )
                scalar = witness["expected_scalar_result"]
                actual_results.append(scalar)
                add_example(
                    witness["input"],
                    {result_field: scalar},
                )
            if actual_results != result_enum:
                raise ProductPlanningError(
                    "capability_source_proposal_capture_invalid"
                )
        for case in authorization.get("acceptance_cases") or []:
            if (
                type(case) is not dict
                or set(case) != {"input", "expected_output"}
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_capture_invalid"
                )
            expected = (
                case["expected_output"][result_field]
                if adapter_version == COMPUTATION_ADAPTER_V2
                else case["expected_output"]
            )
            if adapter_version == COMPUTATION_ADAPTER_V2:
                examples.append(
                    {
                        "input": copy.deepcopy(case["input"]),
                        "expected": copy.deepcopy(expected),
                    }
                )
            else:
                add_example(case["input"], expected)
        if len(examples) > 35:
            raise ProductPlanningError(
                "capability_source_proposal_capture_invalid"
            )
        mapping: dict[str, Any] = {
            "arguments": arguments,
            "result_field": result_field,
            "examples": examples,
        }
        if adapter_version == COMPUTATION_ADAPTER_V3:
            mapping = {
                "schema": CAPTURE_MAPPING_V3,
                **mapping,
                "passthrough_fields": passthrough_fields,
            }
        elif adapter_version == COMPUTATION_ADAPTER_V4:
            mapping = {
                "schema": CAPTURE_MAPPING_V4,
                **mapping,
                "result_enum": copy.deepcopy(result_enum),
                "proof_schema": "source_graph_proof.v2",
            }
        return (
            {
                "module_relpath": "capability.js",
                "export_name": "compute",
                "target_binding_id": offer["target_binding_id"],
            },
            mapping,
        )

    def _capability_source_proposal_review_outcome(
        self,
        review_id: str | None,
    ) -> dict[str, Any] | None:
        if not review_id or not self._capsule_store.path.is_file():
            return None
        with self._capsule_store.read_connection() as connection:
            row = connection.execute(
                "SELECT review_id, candidate_status, decision, "
                "retained_version_id, updated_at FROM review_items "
                "WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        if row is None:
            return {
                "status": "missing",
                "review_id": review_id,
            }
        return {
            "status": (
                "published"
                if row["candidate_status"] == "published"
                else (
                    "rejected"
                    if row["candidate_status"] == "rejected"
                    else "review_required"
                )
            ),
            "review_id": str(row["review_id"]),
            "decision": row["decision"],
            "version_id": row["retained_version_id"],
            "updated_at": row["updated_at"],
        }

    def _resolve_product_capability_replan(
        self,
        plan_token: str,
        plan_digest: str,
        projection_digest: str,
        catalog: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        workspace = self._product_planner._workspace_by_token(plan_token)
        plan = workspace.get("plan")
        projection = (
            self._product_planner._read_capability_gap_projection(workspace)
            if type(plan) is dict
            else None
        )
        if (
            workspace.get("status") != "plan_review"
            or type(plan) is not dict
            or plan.get("canonical_digest") != plan_digest
            or projection is None
            or projection.get("projection_digest") != projection_digest
        ):
            raise ProductPlanningError("capability_replan_unavailable")
        decisions = self._product_planner._capability_gap_decisions(
            workspace,
            projection,
        )
        decision = decisions[-1] if decisions else None
        authorization = (
            self._product_planner
            ._read_capability_source_proposal_authorization(
                workspace,
                projection,
                decision,
            )
            if type(decision) is dict
            and decision.get("decision") == "authorize"
            else None
        )
        if authorization is None:
            raise ProductPlanningError("capability_replan_unavailable")
        try:
            selected = self._product_planner._model_identity(
                self._product_planner._selected_model(
                    check_current=False
                )
            )
        except ProductPlanningError as exc:
            raise ProductPlanningError(
                "capability_replan_handoff_stale"
            ) from exc
        if selected != workspace["model"]:
            raise ProductPlanningError(
                "capability_replan_handoff_stale"
            )

        linked: list[tuple[dict[str, Any], dict[str, Any]]] = []
        with self._capsule_store.read_connection() as connection:
            rows = connection.execute(
                "SELECT review_id, candidate_status, decision, "
                "candidate_canonical_hash, sanitized_candidate_json "
                "FROM review_items WHERE candidate_status = 'published' "
                "AND decision = 'publish_general' ORDER BY review_id"
            ).fetchall()
        for raw in rows:
            row = dict(raw)
            try:
                summary = json.loads(row["sanitized_candidate_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            receipt = (
                summary.get("frozen_review_admission")
                if type(summary) is dict
                else None
            )
            if (
                type(receipt) is dict
                and receipt.get("plan_digest") == plan_digest
                and receipt.get("gap_id") == projection["gap_id"]
                and receipt.get("projection_digest") == projection_digest
                and receipt.get("authorize_decision_digest")
                == decision["canonical_digest"]
                and receipt.get("source_proposal_authorization_digest")
                == authorization["authorization_digest"]
            ):
                linked.append((row, receipt))
        if not linked:
            raise ProductPlanningError("capability_replan_unavailable")
        if len(linked) != 1:
            raise ProductPlanningError("capability_replan_ambiguous")
        review, receipt = linked[0]
        receipt_body = {
            key: value for key, value in receipt.items() if key != "digest"
        }
        if (
            receipt.get("schema") != FROZEN_REVIEW_ADMISSION_VERSION
            or receipt.get("source_review_id") != review["review_id"]
            or receipt.get("candidate_canonical_hash")
            != review["candidate_canonical_hash"]
            or receipt.get("authorized_capability_key")
            != projection["capability_key"]
            or receipt.get("authorized_adapter_contract_version")
            != projection["adapter_contract_version"]
            or receipt.get("authorized_input_contract")
            != authorization["input_contract"]
            or receipt.get("authorized_output_contract")
            != authorization["output_contract"]
            or receipt.get("authorized_error_contract")
            != authorization["error_contract"]
            or receipt.get("authorization_warehouse_revision")
            != projection["warehouse_revision"]
            or receipt.get("authorization_catalog_digest")
            != authorization["catalog_digest"]
            or type(receipt.get("target_warehouse_revision_before"))
            is not int
            or type(receipt.get("target_warehouse_revision_after"))
            is not int
            or receipt["target_warehouse_revision_before"]
            != projection["warehouse_revision"]
            or receipt["target_warehouse_revision_after"]
            != receipt["target_warehouse_revision_before"] + 1
            or receipt.get("target_catalog_digest_before")
            != receipt.get("target_catalog_digest_after")
            or receipt.get("digest")
            != canonical_json_digest(receipt_body)
        ):
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            )

        normalized_catalog = self._product_planner._catalog(catalog)
        published_matches = [
            capsule
            for capsule in normalized_catalog["capsules"]
            if capsule["capability_key"] == projection["capability_key"]
            and capsule["capability_kind"] == "computation"
            and capsule["canonical_hash"]
            == receipt["candidate_canonical_hash"]
        ]
        if not published_matches:
            raise ProductPlanningError("capability_replan_unavailable")
        if len(published_matches) != 1:
            raise ProductPlanningError("capability_replan_ambiguous")
        published = published_matches[0]
        with self._capsule_store.read_connection() as connection:
            evidence = connection.execute(
                "SELECT cv.supervision_model_name, "
                "cv.supervision_model_digest FROM capsule_versions cv "
                "JOIN capsules c ON c.capsule_id = cv.capsule_id "
                "WHERE cv.version_id = ? AND c.current_version_id = "
                "cv.version_id AND c.status = 'active'",
                (published["version_id"],),
            ).fetchone()
        if (
            evidence is None
            or evidence["supervision_model_name"]
            != receipt.get("supervision_model_name")
            or evidence["supervision_model_digest"]
            != receipt.get("supervision_model_digest")
            or published["input_contract"]
            != authorization["input_contract"]
            or published["output_contract"]
            != authorization["output_contract"]
            or published["error_contract"]
            != authorization["error_contract"]
        ):
            raise ProductPlanningError(
                "capability_replan_handoff_conflict"
            )
        if (
            normalized_catalog["warehouse_revision"]
            != receipt["target_warehouse_revision_after"] + 1
        ):
            raise ProductPlanningError(
                "capability_replan_handoff_stale"
            )
        published_identity = (
            self._product_planner._gap_capsule_identity(published)
        )
        offer = self._product_planner._capability_replan_offer(
            normalized_catalog,
            projection,
            published_identity,
            authorization["error_contract"],
        )
        if offer is None:
            raise ProductPlanningError("capability_replan_unavailable")
        binding = {
            "admission_review_id": str(review["review_id"]),
            "admission_digest": str(receipt["digest"]),
            "publication_review_id": str(review["review_id"]),
            "published_capsule": published_identity,
            "authorization_revision": projection["warehouse_revision"],
            "admission_revision_before": receipt[
                "target_warehouse_revision_before"
            ],
            "admission_revision_after": receipt[
                "target_warehouse_revision_after"
            ],
            "publication_revision": normalized_catalog[
                "warehouse_revision"
            ],
        }
        return binding, offer, projection

    def _product_capability_replan_view(
        self,
        workspace: dict[str, Any],
        catalog: dict[str, Any],
    ) -> dict[str, Any] | None:
        plan = workspace.get("plan")
        if type(plan) is not dict:
            return None
        projection = self._product_planner._read_capability_gap_projection(
            workspace
        )
        if projection is None:
            return None
        decisions = self._product_planner._capability_gap_decisions(
            workspace,
            projection,
        )
        if not decisions or decisions[-1].get("decision") != "authorize":
            return None
        authorization = (
            self._product_planner
            ._read_capability_source_proposal_authorization(
                workspace,
                projection,
                decisions[-1],
            )
        )
        if authorization is None:
            return None
        try:
            _binding, offer, _projection = (
                self._resolve_product_capability_replan(
                    workspace["plan_token"],
                    plan["canonical_digest"],
                    projection["projection_digest"],
                    catalog,
                )
            )
            status = "available"
            role_order = [
                member["role_key"] for member in offer["members"]
            ]
        except ProductPlanningError as exc:
            status = exc.code
            role_order = []
        return {
            "schema_version": "capability_replan_handoff.v1",
            "status": status,
            "source_gap_id": projection["gap_id"],
            "projection_digest": projection["projection_digest"],
            "role_order": role_order,
            "successor_plan_token": None,
            "handoff_digest": None,
            "acceptance_suggestions": [],
        }

    def close(self) -> None:
        with self._management_lock:
            if self._management_closed:
                return
            self._management_closed = True
            for task in self._management_tasks.values():
                task["cancel_event"].set()
            self._javascript_capture_sessions.clear()
            executor = self._management_executor
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=False)

    def _capsule_management_state(self) -> dict[str, Any]:
        initialized = self._capsule_store.path.is_file()
        legacy = self._legacy_summary()
        legacy["aliases"] = []
        legacy["aliasCounts"] = {}
        state: dict[str, Any] = {
            "schemaVersion": "capsule_ingestion_management.v1",
            "available": True,
            "databaseInitialized": initialized,
            "generationActive": True,
            "singleWarehouse": True,
            "singleComposer": True,
            "legacy": legacy,
            "capabilities": {
                "sourceManagement": True,
                "supervisionModelSelection": True,
                "review": True,
                "warehouseManagement": True,
                "backupRestore": True,
                "legacyReadOnlyImport": True,
                "generationFromSqlite": True,
            },
        }
        with self._management_lock:
            if self._restore_pending:
                state.update(
                    {
                        "databaseStatus": "restore_in_progress",
                        "sourceRoots": [],
                        "projects": [],
                        "reviewCounts": {},
                        "capabilityGroupCount": 0,
                        "selectedSupervisionModel": None,
                        "backups": [],
                    }
                )
                return state
        if not initialized:
            state.update(
                {
                    "sourceRoots": [],
                    "projects": [],
                    "reviewCounts": {},
                    "capabilityGroupCount": 0,
                    "selectedSupervisionModel": None,
                    "backups": self._capsule_store.list_backups(),
                }
            )
            return state
        try:
            legacy_sources = self._legacy_item_source_paths(
                str(legacy.get("fileSha256") or "")
            )
            with self._capsule_operation_lock:
                with self._management_lock:
                    if self._restore_pending:
                        state["databaseStatus"] = "restore_in_progress"
                        return state
                self._ensure_capsule_management()
                with self._capsule_store.read_connection() as connection:
                    state["sourceRoots"] = [
                        self._json_columns(dict(row), ("brand_profile_json",))
                        for row in connection.execute(
                            "SELECT * FROM source_roots ORDER BY created_at, root_id"
                        )
                    ]
                    state["projects"] = [
                        self._json_columns(dict(row), ("brand_profile_json",))
                        for row in connection.execute(
                            "SELECT * FROM projects ORDER BY created_at, project_id"
                        )
                    ]
                    state["reviewCounts"] = {
                        str(row["candidate_status"]): int(row["count"])
                        for row in connection.execute(
                            "SELECT candidate_status, COUNT(*) AS count FROM review_items "
                            "GROUP BY candidate_status"
                        )
                    }
                    state["capabilityGroupCount"] = int(
                        connection.execute("SELECT COUNT(*) FROM capability_groups").fetchone()[0]
                    )
                    legacy_file_hash = legacy.get("fileSha256")
                    if type(legacy_file_hash) is str:
                        aliases: list[dict[str, Any]] = []
                        seen_aliases: set[str] = set()
                        for row in connection.execute(
                            "SELECT legacy_capsule_id, relationship, new_capsule_id, "
                            "new_version_id, reason_code, created_at "
                            "FROM legacy_capsule_aliases WHERE legacy_file_hash = ? "
                            "ORDER BY rowid DESC",
                            (legacy_file_hash,),
                        ):
                            legacy_id = str(row["legacy_capsule_id"])
                            if legacy_id in seen_aliases:
                                continue
                            seen_aliases.add(legacy_id)
                            alias = dict(row)
                            alias["eligible_targets"] = []
                            source_path = legacy_sources.get(legacy_id)
                            if alias["relationship"] == "pending" and source_path:
                                try:
                                    resolved_source = str(
                                        Path(source_path).expanduser().resolve(strict=True)
                                    )
                                except (OSError, RuntimeError):
                                    resolved_source = ""
                                project_ids = self._matching_legacy_projects(
                                    connection, resolved_source
                                )
                                if len(project_ids) == 1:
                                    alias["eligible_targets"] = [
                                        dict(target)
                                        for target in connection.execute(
                                            "SELECT c.capsule_id, cv.version_id, "
                                            "c.capability_key, c.role_key, c.variant_key, "
                                            "g.display_name FROM capsules c "
                                            "JOIN capsule_versions cv "
                                            "ON cv.version_id = c.current_version_id "
                                            "JOIN capability_groups g "
                                            "ON g.capability_key = c.capability_key "
                                            "WHERE c.status = 'active' AND EXISTS ("
                                            "SELECT 1 FROM capsule_sources cs "
                                            "WHERE cs.version_id = cv.version_id "
                                            "AND cs.project_id = ? "
                                            "AND cs.source_kind = 'project') "
                                            "ORDER BY c.capability_key, c.role_key, c.variant_key",
                                            (project_ids[0],),
                                        )
                                    ]
                            aliases.append(alias)
                        legacy["aliases"] = aliases
                        counts: dict[str, int] = {}
                        for alias in aliases:
                            relationship = str(alias["relationship"])
                            counts[relationship] = counts.get(relationship, 0) + 1
                        legacy["aliasCounts"] = counts
                try:
                    state["selectedSupervisionModel"] = self._capsule_supervisor.selected_model()
                except Stage3Error:
                    state["selectedSupervisionModel"] = None
                state["backups"] = self._capsule_store.list_backups()
        except (CapsuleStoreError, OSError, ValueError, sqlite3.Error):
            state["databaseStatus"] = "unavailable"
            state.setdefault("sourceRoots", [])
            state.setdefault("projects", [])
            state.setdefault("reviewCounts", {})
            state.setdefault("capabilityGroupCount", 0)
            state.setdefault("selectedSupervisionModel", None)
            state["backups"] = self._capsule_store.list_backups()
        return state

    @staticmethod
    def _json_columns(row: dict[str, Any], columns: tuple[str, ...]) -> dict[str, Any]:
        for column in columns:
            raw = row.get(column)
            if raw is not None:
                try:
                    row[column] = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    row[column] = None
        return row

    @staticmethod
    def _allowed_review_decisions(item: dict[str, Any]) -> list[str]:
        candidate = item.get("candidate") or {}
        if _retired_v1_adapter_candidate(candidate):
            return []
        comparison = item.get("comparison") or {}
        current_status = str(item.get("candidate_status") or "")
        allowed: list[str] = []
        requires_reextract = (
            candidate.get("candidate_origin")
            == "deterministic_computation_adapter"
            and candidate.get("requires_reextract") is True
        )
        ephemeral_capture = (
            requires_reextract
            and (
                (
                    candidate.get("adapter_contract_version")
                    == COMPUTATION_ADAPTER_V2
                    and candidate.get("resume_contract") == CAPTURE_RESUME_V1
                )
                or (
                    candidate.get("adapter_contract_version")
                    == COMPUTATION_ADAPTER_V3
                    and candidate.get("resume_contract") == CAPTURE_RESUME_V2
                )
                or (
                    candidate.get("adapter_contract_version")
                    == COMPUTATION_ADAPTER_V4
                    and candidate.get("resume_contract") == CAPTURE_RESUME_V3
                )
            )
        )
        if not requires_reextract and current_status in {
            "extracted",
            "waiting_user",
            "waiting_model",
            "waiting_validation",
        }:
            allowed.append("process_candidate")
        if current_status == "waiting_user":
            codes = set((item.get("redaction") or {}).get("codes") or [])
            failure_code = (candidate.get("stage3_failure") or {}).get("error_code")
            if item.get("sensitivity_decision") is None and (
                "sensitivity_confirmation_required" in codes
                or failure_code == "sensitivity_confirmation_required_stage3"
            ):
                allowed.extend(
                    ["confirm_fictional_fixture", "confirm_real_record_reject"]
                    if ephemeral_capture
                    else [
                        "confirm_fictional_fixture",
                        "confirm_safe_redaction",
                        "confirm_real_record_reject",
                    ]
                )
            if item.get("brand_decision") is None and (
                "brand_confirmation_required" in codes
                or failure_code == "brand_confirmation_required"
            ):
                allowed.extend(
                    ["retain_brand_limited"]
                    if ephemeral_capture
                    else ["remove_brand", "retain_brand_limited"]
                )
            if (
                ephemeral_capture
                and item.get("enum_decision") is None
                and "enumeration_confirmation_required" in codes
            ):
                allowed.append("confirm_selected_string_enumeration")
            if item.get("asset_decision") is None and (
                failure_code == "asset_content_confirmation_required_stage3"
            ):
                allowed.append("confirm_assets_contain_no_real_records")
        frozen_product_review = (
            type(candidate.get("frozen_review_admission")) is dict
            and candidate["frozen_review_admission"].get("schema")
            == FROZEN_REVIEW_ADMISSION_VERSION
        )
        frozen_ui_review = (
            type(candidate.get("frozen_ui_review_admission")) is dict
            and candidate["frozen_ui_review_admission"].get("schema")
            == FROZEN_UI_REVIEW_ADMISSION_VERSION
        )
        if current_status == "review_required" and (
            frozen_product_review or frozen_ui_review
        ):
            allowed.extend(["publish_general", "reject"])
        elif (
            current_status == "review_required"
            and candidate.get("adapter_contract_version") == COMPUTATION_ADAPTER_V3
        ):
            allowed.append("reject")
        elif current_status == "review_required":
            usage_kind = (candidate.get("usage_scope") or {}).get("kind")
            if usage_kind == "general":
                allowed.append("publish_general")
            elif usage_kind == "brand_limited":
                allowed.append("publish_brand_limited")
            allowed.extend(["create_variant", "reject"])
            targets = comparison.get("candidates") or []
            if targets:
                allowed.extend(["merge_existing", "semantic_split"])
            if any(
                type(target) is dict
                and (
                    target.get("contract_match") is True
                    or target.get("scope_revalidation_match") is True
                )
                for target in targets
            ):
                allowed.append("replace_current")
        if current_status == "duplicate" and item.get("decision") is None:
            allowed.append("semantic_split")
        return list(dict.fromkeys(allowed))

    @staticmethod
    def _ok(data: Any = None) -> dict[str, Any]:
        return {"ok": True, "data": {} if data is None else data}

    @staticmethod
    def _error(code: str) -> dict[str, Any]:
        return {"ok": False, "error": {"code": code, "message_key": code}}

    @classmethod
    def _exception_error(cls, exc: BaseException, fallback: str) -> dict[str, Any]:
        code = getattr(exc, "code", None)
        if code is None and str(exc) in {"management_closed", "restore_in_progress"}:
            code = str(exc)
        if type(code) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{1,95}", code):
            code = fallback
        return cls._error(code)

    @classmethod
    def _target_exception_error(
        cls, exc: BaseException, fallback: str
    ) -> dict[str, Any]:
        result = cls._exception_error(exc, fallback)
        if isinstance(exc, StaticWebTargetError):
            result["error"]["evidence"] = rejection_evidence(exc)
        else:
            phase = (
                "capsule_selection"
                if isinstance(exc, (CapsuleStoreError, ProductGenerationError, sqlite3.Error))
                else "request"
            )
            result["error"]["evidence"] = {
                "status": "rejected",
                "code": result["error"]["code"],
                "phase": phase,
            }
        return result

    @staticmethod
    def _payload(value: dict[str, Any] | None) -> dict[str, Any]:
        if value is None:
            return {}
        if type(value) is not dict:
            raise ValueError("payload_invalid")
        return value

    def _ensure_capsule_management(self) -> None:
        with self._management_lock:
            if self._management_closed:
                raise RuntimeError("management_closed")
            if self._restore_pending:
                raise RuntimeError("restore_in_progress")
            self._capsule_store.initialize()
            if not self._management_recovered:
                self._capsule_intake.recover_interrupted_runs()
                self._management_recovered = True
            if not self._management_rules_checked:
                self._require_current_rule_versions()
                self._management_rules_checked = True

    def _require_current_rule_versions(self) -> None:
        # Use the serialized store transaction boundary for the preflight query,
        # but do not mutate it. The verified backup is created after this block
        # and before the separate CAS transaction below.
        with self._capsule_store.transaction() as connection:
            active_rows = connection.execute(
                "SELECT cv.extraction_summary_json FROM capsules c "
                "JOIN capsule_versions cv ON cv.version_id = c.current_version_id "
                "WHERE c.status = 'active'"
            ).fetchall()
            retirement_revision = int(
                connection.execute(
                    "SELECT warehouse_revision FROM warehouse_state "
                    "WHERE singleton_id = 1"
                ).fetchone()[0]
            )
        retiring_v1 = False
        for row in active_rows:
            try:
                summary = json.loads(row["extraction_summary_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if _retired_v1_adapter_candidate(summary):
                retiring_v1 = True
                break
        if retiring_v1:
            # The retirement is a warehouse mutation. A verified full backup must
            # exist before the first active-current v1 capsule changes status.
            backup = self._capsule_store.create_backup("upgrade")
            if (
                type(backup.get("warehouse_revision")) is not int
                or backup["warehouse_revision"] != retirement_revision
            ):
                raise CapsuleStoreError("warehouse_changed_during_adapter_retirement")

        now = _now()
        with self._capsule_store.transaction() as connection:
            current_revision = int(
                connection.execute(
                    "SELECT warehouse_revision FROM warehouse_state "
                    "WHERE singleton_id = 1"
                ).fetchone()[0]
            )
            if current_revision != retirement_revision:
                raise CapsuleStoreError(
                    "warehouse_changed_during_adapter_retirement"
                )
            rows = connection.execute(
                "SELECT c.capsule_id, c.current_version_id FROM capsules c "
                "JOIN capsule_versions cv ON cv.version_id = c.current_version_id "
                "WHERE c.status = 'active' AND ("
                "cv.extraction_contract_version <> ? OR "
                "cv.redaction_rules_version <> ? OR "
                "cv.canonicalization_version <> ? OR "
                "cv.security_rules_version <> ? OR "
                "cv.supervision_rules_version <> ? OR "
                "cv.validation_contract_version <> ?)",
                (
                    EXTRACTION_CONTRACT_VERSION,
                    REDACTION_RULES_VERSION,
                    CANONICALIZATION_VERSION,
                    SECURITY_RULES_VERSION,
                    SUPERVISION_RULES_VERSION,
                    VALIDATION_CONTRACT_VERSION,
                ),
            ).fetchall()
            stale = {
                str(row["capsule_id"]): (str(row["current_version_id"]), "rule_version_changed")
                for row in rows
            }
            adapter_rows = connection.execute(
                "SELECT c.status, c.current_version_id, c.capability_kind, cv.* "
                "FROM capsules c JOIN capsule_versions cv "
                "ON cv.version_id = c.current_version_id WHERE c.status = 'active'"
            ).fetchall()
            for row in adapter_rows:
                try:
                    summary = json.loads(row["extraction_summary_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if type(summary) is not dict or summary.get(
                    "candidate_origin"
                ) != "deterministic_computation_adapter":
                    continue
                adapter_version = summary.get("adapter_contract_version")
                if adapter_version == COMPUTATION_ADAPTER_CONTRACT_VERSION:
                    stale[str(row["capsule_id"])] = (
                        str(row["current_version_id"]),
                        "adapter_contract_version_changed",
                    )
                elif adapter_version not in {
                    COMPUTATION_ADAPTER_V2,
                    COMPUTATION_ADAPTER_V3,
                    COMPUTATION_ADAPTER_V4,
                }:
                    stale[str(row["capsule_id"])] = (
                        str(row["current_version_id"]),
                        "adapter_contract_version_changed",
                    )
                elif (
                    adapter_version
                    in {
                        COMPUTATION_ADAPTER_V2,
                        COMPUTATION_ADAPTER_V3,
                        COMPUTATION_ADAPTER_V4,
                    }
                    and not self._capsule_stage3._stored_version_evidence_eligible(
                        dict(row)
                    )
                ):
                    stale[str(row["capsule_id"])] = (
                        str(row["current_version_id"]),
                        "adapter_evidence_version_changed",
                    )
            status_changes = 0
            for capsule_id, (version_id, reason_code) in stale.items():
                changed = connection.execute(
                    "UPDATE capsules SET status = 'pending_revalidation' "
                    "WHERE capsule_id = ? AND current_version_id = ? "
                    "AND status = 'active'",
                    (capsule_id, version_id),
                ).rowcount
                if changed != 1:
                    continue
                status_changes += 1
                connection.execute(
                    "INSERT INTO capsule_status_events VALUES (?, ?, "
                    "'revalidation_required', 'active', 'pending_revalidation', ?, ?, ?)",
                    (
                        f"evt_{uuid.uuid4().hex}",
                        capsule_id,
                        version_id,
                        reason_code,
                        now,
                    ),
                )
            if status_changes:
                self._capsule_store.bump_revision(connection)

    def _executor(self) -> ThreadPoolExecutor:
        if self._management_executor is None:
            self._management_executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="reweave-capsule-management",
            )
        return self._management_executor

    def _submit_management_task(
        self,
        kind: str,
        action: Any,
        *,
        run_id: str | None = None,
        restore: bool = False,
        cancellable: bool = False,
        read_only_planning: bool = False,
        read_only_candidate: bool = False,
        planning_progress: bool = False,
    ) -> dict[str, Any]:
        if read_only_planning and not kind.startswith("product_plan_"):
            raise ValueError("read_only_planning_kind_invalid")
        if planning_progress and not read_only_planning:
            raise ValueError("planning_progress_kind_invalid")
        if read_only_candidate and not kind.startswith("product_candidate_"):
            raise ValueError("read_only_candidate_kind_invalid")
        if not restore and not read_only_planning and not read_only_candidate:
            try:
                self._ensure_capsule_management()
            except (CapsuleStoreError, OSError, RuntimeError, sqlite3.Error) as exc:
                return self._exception_error(exc, "capsule_management_unavailable")
        with self._management_lock:
            if self._management_closed:
                return self._error("capsule_management_closed")
            if self._restore_pending:
                return self._error("restore_in_progress")
            if restore:
                self._restore_pending = True
                for current in self._management_tasks.values():
                    if (
                        current["status"] not in _TERMINAL_TASK_STATES
                        and current["cancellable"]
                    ):
                        current["cancel_event"].set()
            task_id = run_id or f"run_{uuid.uuid4().hex}"
            if run_id is not None:
                if re.fullmatch(r"run_[0-9a-f]{32}", run_id) is None:
                    raise ValueError("management_run_id_invalid")
                existing_task = self._management_tasks.get(run_id)
                if existing_task is not None:
                    if existing_task["kind"] != kind:
                        raise ValueError("management_run_id_conflict")
                    return {
                        "ok": True,
                        "run_id": run_id,
                        "status": existing_task["status"],
                    }
            cancel_event = threading.Event()
            task: dict[str, Any] = {
                "run_id": task_id,
                "kind": kind,
                "status": "queued",
                "created_at": _now(),
                "started_at": None,
                "completed_at": None,
                "data": None,
                "error": None,
                "phase": None,
                "cancellable": cancellable,
                "cancel_event": cancel_event,
                "future": None,
            }
            self._management_tasks[task_id] = task

            def report_phase(phase: str) -> None:
                if phase not in PRODUCT_PLANNING_PHASES:
                    raise ValueError("product_plan_phase_invalid")
                with self._management_lock:
                    if task["status"] == "running":
                        task["phase"] = phase

            def run() -> None:
                try:
                    if cancel_event.is_set() and cancellable:
                        task["status"] = "cancelled"
                        return
                    task["status"] = "running"
                    task["started_at"] = _now()
                    with self._capsule_operation_lock:
                        task["data"] = (
                            action(cancel_event, report_phase)
                            if planning_progress
                            else action(cancel_event)
                        )
                    planner_error = None
                    if (
                        (
                            kind.startswith("product_plan_")
                            or kind.startswith("product_candidate_")
                        )
                        and type(task["data"]) is dict
                        and task["data"].get("ok") is False
                    ):
                        error = task["data"].get("error")
                        planner_error = (
                            error.get("code")
                            if type(error) is dict and type(error.get("code")) is str
                            else f"{kind}_failed"
                        )
                    action_status = (
                        task["data"].get("status")
                        if type(task["data"]) is dict
                        else None
                    )
                    if planner_error is not None:
                        task["status"] = (
                            "cancelled"
                            if cancellable and planner_error == "product_plan_cancelled"
                            else "failed"
                        )
                        if task["status"] == "failed":
                            task["error"] = {
                                "code": planner_error,
                                "message_key": planner_error,
                            }
                    else:
                        task["status"] = (
                            "cancelled"
                            if cancellable and action_status == "cancelled"
                            else "completed"
                        )
                except BaseException as exc:
                    error_code = getattr(exc, "code", None)
                    task["status"] = (
                        "cancelled"
                        if cancellable
                        and cancel_event.is_set()
                        and error_code
                        in {
                            "intake_cancelled",
                            "cancelled_by_user",
                            "product_plan_cancelled",
                        }
                        else "failed"
                    )
                    if task["status"] == "failed":
                        task["error"] = self._exception_error(exc, f"{kind}_failed")["error"]
                    if kind == "legacy_import":
                        try:
                            self._fail_running_legacy_runs()
                        except BaseException:
                            pass
                finally:
                    with self._management_lock:
                        task["completed_at"] = _now()
                        if restore:
                            self._restore_pending = False
                        # ponytail: recent UI receipts only; add persistence if users need older tasks.
                        self._management_tasks.pop(task_id, None)
                        self._management_tasks[task_id] = task
                        terminal = [
                            current
                            for current in self._management_tasks.values()
                            if current["status"] in _TERMINAL_TASK_STATES
                        ]
                        for expired in terminal[:-100]:
                            self._management_tasks.pop(expired["run_id"], None)

            future: Future[None] = self._executor().submit(run)
            task["future"] = future
        return {"ok": True, "run_id": task_id, "status": "queued"}

    def _fail_running_legacy_runs(self) -> None:
        with self._capsule_store.transaction() as connection:
            changed = connection.execute(
                "UPDATE intake_runs SET status = 'failed', error_code = ?, completed_at = ? "
                "WHERE run_kind = 'legacy_import' AND status IN ('queued', 'running')",
                ("legacy_import_failed", _now()),
            ).rowcount
            if changed:
                self._capsule_store.bump_revision(connection)

    @staticmethod
    def _task_view(task: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in task.items()
            if key not in {"cancel_event", "future"} and value is not None
        }

    def discover_source_root(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            source_path = str(request.get("path") or "").strip()
            root_id = str(request.get("root_id") or "").strip()
            root_kind = str(request.get("root_kind") or "project_collection")
            brand_profile = request.get("brand_profile")
            if bool(source_path) == bool(root_id):
                return self._error("source_root_reference_required")
            if brand_profile is not None and type(brand_profile) is not dict:
                return self._error("brand_profile_invalid")

            def action(_cancel: threading.Event) -> dict[str, Any]:
                if source_path:
                    root = self._capsule_intake.bind_source_root(
                        source_path,
                        root_kind=root_kind,
                        brand_profile=brand_profile,
                    )
                    selected_id = str(root["root_id"])
                else:
                    selected_id = root_id
                    root = self._capsule_intake.get_source_root(selected_id)
                projects = self._capsule_intake.discover_projects(selected_id)
                return {"source_root": root, "projects": projects}

            return self._submit_management_task("discover_source_root", action)
        except (ValueError, IntakeError) as exc:
            return self._exception_error(exc, "discover_source_root_invalid")

    @_serialized_management
    def confirm_projects(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            self._ensure_capsule_management()
            request = self._payload(payload)
            entries = request.get("projects")
            if type(entries) is not list or not entries:
                return self._error("projects_required")
            project_ids: list[str] = []
            for entry in entries:
                if type(entry) is not dict:
                    return self._error("project_confirmation_invalid")
                project_id = str(entry.get("project_id") or "").strip()
                if not project_id:
                    return self._error("project_id_required")
                self._capsule_intake.get_project(project_id)
                if "brand_mode" in entry:
                    mode = str(entry.get("brand_mode") or "inherit")
                    if mode not in {"inherit", "replace", "clear"}:
                        return self._error("project_brand_mode_invalid")
                    if mode == "replace":
                        profile = self._capsule_intake._profile_fields(
                            entry.get("brand_profile"), previous=None
                        )
                        if profile["id"] is None:
                            return self._error("project_brand_profile_required")
                project_ids.append(project_id)
            confirmed: list[dict[str, Any]] = []
            errors: list[dict[str, str]] = []
            changed_brand_projects: list[str] = []
            for entry, project_id in zip(entries, project_ids):
                try:
                    self._capsule_intake.confirm_project(project_id)
                    if "brand_mode" in entry:
                        changed = self._set_project_brand_and_require_revalidation(
                            project_id,
                            mode=str(entry.get("brand_mode") or "inherit"),
                            brand_profile=entry.get("brand_profile"),
                        )
                        if changed:
                            changed_brand_projects.append(project_id)
                    confirmed.append(self._capsule_intake.get_project(project_id))
                except (CapsuleStoreError, IntakeError, OSError, ValueError) as exc:
                    error = self._exception_error(exc, "project_confirmation_failed")["error"]
                    errors.append({"project_id": project_id, "error_code": error["code"]})
            run_ids: list[str] = []
            for project_id in changed_brand_projects:
                started = self._submit_management_task(
                    "refresh_project",
                    lambda cancel, current=project_id: self._refresh_project(current, cancel),
                    cancellable=True,
                )
                if started.get("ok") is True:
                    run_ids.append(str(started["run_id"]))
                else:
                    errors.append(
                        {
                            "project_id": project_id,
                            "error_code": str(started["error"]["code"]),
                        }
                    )
            return self._ok(
                {"projects": confirmed, "errors": errors, "run_ids": run_ids}
            )
        except (CapsuleStoreError, IntakeError, OSError, ValueError) as exc:
            return self._exception_error(exc, "confirm_projects_failed")

    def _set_project_brand_and_require_revalidation(
        self,
        project_id: str,
        *,
        mode: str,
        brand_profile: dict[str, Any] | None,
    ) -> bool:
        """Change one project profile and conservatively invalidate its active contributions."""
        now = _now()
        with self._capsule_store.transaction() as connection:
            project_row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if project_row is None:
                raise IntakeError("project_not_found")
            root_row = connection.execute(
                "SELECT * FROM source_roots WHERE root_id = ?",
                (project_row["source_root_id"],),
            ).fetchone()
            if root_row is None:
                raise IntakeError("source_root_not_found")
            project = dict(project_row)
            source_root = dict(root_row)
            if mode == "extend":
                raise IntakeError("project_brand_mode_invalid")
            unsupported_previous = project.get("brand_mode") == "extend"
            previous = (
                None
                if unsupported_previous
                else self._capsule_intake._effective_brand_profile(
                    project, source_root
                )
            )
            if mode == "replace":
                profile = self._capsule_intake._profile_fields(
                    brand_profile, previous=project
                )
                if profile["id"] is None:
                    raise IntakeError("project_brand_profile_required")
            else:
                profile = {
                    "id": project.get("brand_profile_id"),
                    "json": project.get("brand_profile_json"),
                    "digest": project.get("brand_profile_digest"),
                    "version": int(project.get("brand_profile_version") or 0),
                }
            projected = {
                **project,
                "brand_mode": mode,
                "brand_profile_id": profile["id"],
                "brand_profile_json": profile["json"],
                "brand_profile_digest": profile["digest"],
                "brand_profile_version": profile["version"],
            }
            current = self._capsule_intake._effective_brand_profile(
                projected, source_root
            )
            changed = unsupported_previous or (
                previous is not None
                and (previous.get("id"), previous.get("digest"))
                != (current.get("id"), current.get("digest"))
            )
            connection.execute(
                "UPDATE projects SET brand_mode = ?, brand_profile_id = ?, "
                "brand_profile_json = ?, brand_profile_digest = ?, "
                "brand_profile_version = ?, updated_at = ? WHERE project_id = ?",
                (
                    mode,
                    profile["id"],
                    profile["json"],
                    profile["digest"],
                    profile["version"],
                    now,
                    project_id,
                ),
            )
            if changed:
                contributed = connection.execute(
                    "SELECT DISTINCT c.capsule_id, c.current_version_id "
                    "FROM capsules c JOIN capsule_versions cv "
                    "ON cv.capsule_id = c.capsule_id "
                    "JOIN capsule_sources cs ON cs.version_id = cv.version_id "
                    "WHERE cs.project_id = ? AND c.status = 'active' "
                    "AND c.current_version_id IS NOT NULL",
                    (project_id,),
                ).fetchall()
                for capsule in contributed:
                    connection.execute(
                        "UPDATE capsules SET status = 'pending_revalidation' "
                        "WHERE capsule_id = ? AND status = 'active'",
                        (capsule["capsule_id"],),
                    )
                    connection.execute(
                        "INSERT INTO capsule_status_events VALUES (?, ?, "
                        "'revalidation_required', 'active', 'pending_revalidation', ?, ?, ?)",
                        (
                            f"evt_{uuid.uuid4().hex}",
                            capsule["capsule_id"],
                            capsule["current_version_id"],
                            "brand_profile_changed",
                            now,
                        ),
                    )
            self._capsule_store.bump_revision(connection)
        return changed

    def _refresh_project(self, project_id: str, cancel: threading.Event) -> dict[str, Any]:
        intake_result = self._capsule_intake.run_intake(
            project_id,
            cancel_check=cancel.is_set,
        )
        gate_results: list[dict[str, Any]] = []
        extracted_review_ids: list[str] = []
        for review_id in intake_result.get("review_ids", []):
            with self._capsule_store.read_connection() as connection:
                row = connection.execute(
                    "SELECT candidate_status FROM review_items WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
            if row is not None and row["candidate_status"] == "extracted":
                extracted_review_ids.append(str(review_id))
        cancelled_before_completion = False
        for review_id in extracted_review_ids:
            if cancel.is_set():
                cancelled_before_completion = True
                break
            try:
                gate_results.append(self._capsule_stage3.process_review(review_id))
            except Stage3Error as exc:
                gate_results.append(
                    {"review_id": review_id, "status": "failed", "error_code": exc.code}
                )
        return {
            "status": "cancelled" if cancelled_before_completion else "completed",
            "intake": intake_result,
            "gate_results": gate_results,
        }

    def start_refresh_project(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            project_id = str(request.get("project_id") or "").strip()
            if not project_id:
                return self._error("project_id_required")
            return self._submit_management_task(
                "refresh_project",
                lambda cancel: self._refresh_project(project_id, cancel),
                cancellable=True,
            )
        except ValueError as exc:
            return self._exception_error(exc, "refresh_project_invalid")

    def _javascript_owner_for_project(self, project_id: str) -> str:
        """Resolve a static or JavaScript row to the one computation owner."""

        self._ensure_javascript_schema()
        with self._capsule_store.read_connection() as connection:
            row = connection.execute(
                "SELECT project_id, source_root_id, source_type, project_relpath "
                "FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            raise JavascriptSourceError("project_not_found")
        if row["source_type"] == JAVASCRIPT_SOURCE_TYPE:
            return str(row["project_id"])
        if row["source_type"] != "static_web":
            raise JavascriptSourceError("source_type_unsupported_v1")
        owner = self._javascript_sources.ensure_owner(
            str(row["source_root_id"]), str(row["project_relpath"])
        )
        return str(owner["project_id"])

    def _ensure_javascript_schema(self) -> None:
        """Enter the already-tested v2 schema only when the user invokes capture."""

        self._ensure_capsule_management()
        with self._capsule_store.read_connection() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version == 1:
            self._capsule_store.migrate_v1_to_v2()
            with self._management_lock:
                self._management_recovered = False
                self._management_rules_checked = False
            self._ensure_capsule_management()
        elif version != 2:
            raise JavascriptSourceError("javascript_source_schema_unsupported")
        self._javascript_sources.check_unique_owners()

    @_serialized_management
    def register_javascript_computation_source(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            self._ensure_javascript_schema()
            request = self._payload(payload)
            if set(request) - {"source_root_id", "project_relpath", "display_name"}:
                return self._error("javascript_source_registration_invalid")
            root_id = str(request.get("source_root_id") or "").strip()
            project_relpath = str(request.get("project_relpath") or ".").strip()
            display_name = str(request.get("display_name") or "").strip()
            if not root_id or not display_name or len(display_name) > 200:
                return self._error("javascript_source_registration_invalid")
            owner = self._javascript_sources.ensure_owner(root_id, project_relpath)
            project_id = str(owner["project_id"])
            with self._capsule_store.transaction() as connection:
                changed = connection.execute(
                    "UPDATE projects SET display_name = ?, updated_at = ? "
                    "WHERE project_id = ? AND source_type = ?",
                    (display_name, _now(), project_id, JAVASCRIPT_SOURCE_TYPE),
                ).rowcount
                if changed != 1:
                    raise JavascriptSourceError("javascript_source_registration_failed")
                self._capsule_store.bump_revision(connection)
            result = {**owner, "display_name": display_name}
            return self._ok(result)
        except (
            CapsuleStoreError,
            JavascriptSourceError,
            OSError,
            ValueError,
            sqlite3.Error,
        ) as exc:
            return self._exception_error(exc, "javascript_source_registration_failed")

    def start_scan_javascript_computations(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if set(request) != {"project_id"}:
                return self._error("javascript_computation_scan_invalid")
            project_id = str(request.get("project_id") or "").strip()
            if not project_id:
                return self._error("project_id_required")

            def action(cancel: threading.Event) -> dict[str, Any]:
                owner_id = self._javascript_owner_for_project(project_id)
                snapshot = self._javascript_sources.scan(
                    owner_id, cancel_event=cancel
                )
                inspection = inspect_ephemeral_computation_offers_v2(snapshot)
                offers = inspection.get("offers")
                if (
                    inspection.get("schema") != "computation_capture_offers.v2"
                    or inspection.get("project_id") != owner_id
                    or type(offers) is not list
                    or any(
                        type(item) is not dict
                        or type(item.get("offer_id")) is not str
                        or not item["offer_id"]
                        for item in offers
                    )
                ):
                    raise Stage3Error("unclassified_internal_result")
                by_offer = {str(item["offer_id"]): dict(item) for item in offers}
                if len(by_offer) != len(offers):
                    raise Stage3Error("unclassified_internal_result")
                with self._management_lock:
                    self._javascript_capture_sessions[owner_id] = {
                        "snapshot": snapshot,
                        "offers": by_offer,
                        "consumed": {},
                    }
                return inspection

            return self._submit_management_task(
                "scan_javascript_computations", action, cancellable=True
            )
        except ValueError as exc:
            return self._exception_error(exc, "javascript_computation_scan_invalid")

    def _ephemeral_capture_request(
        self, request: dict[str, Any], cancel: threading.Event
    ) -> dict[str, Any]:
        project_id = str(request.get("project_id") or "").strip()
        offer_id = str(request.get("offer_id") or "").strip()
        review_id_value = request.get("review_id")
        review_id = (
            str(review_id_value).strip() if review_id_value is not None else None
        )
        with self._management_lock:
            session = self._javascript_capture_sessions.get(project_id)
            if session is None:
                raise Stage3Error("offer_stale")
            offer = session["offers"].get(offer_id)
            consumed_by = session["consumed"].get(offer_id)
            if offer is None or (
                consumed_by is not None and consumed_by != review_id
            ):
                raise Stage3Error("offer_stale")
            snapshot = session["snapshot"]
        if not isinstance(snapshot, JavascriptScopeSnapshot):
            raise Stage3Error("offer_stale")
        if cancel.is_set():
            raise Stage3Error("scan_cancelled")
        mapping_schema = request.get("schema")
        if mapping_schema is None:
            mapping = {
                "arguments": request.get("arguments"),
                "result_field": request.get("result_field"),
                "examples": request.get("examples"),
            }
            prepare = self._capsule_stage3.prepare_ephemeral_computation_capture_v2
        elif mapping_schema == CAPTURE_MAPPING_V3:
            mapping = {
                "schema": CAPTURE_MAPPING_V3,
                "arguments": request.get("arguments"),
                "result_field": request.get("result_field"),
                "passthrough_fields": request.get("passthrough_fields"),
                "examples": request.get("examples"),
            }
            prepare = self._capsule_stage3.prepare_ephemeral_computation_capture_v3
        elif mapping_schema == CAPTURE_MAPPING_V4:
            mapping = {
                "schema": CAPTURE_MAPPING_V4,
                "arguments": request.get("arguments"),
                "result_field": request.get("result_field"),
                "result_enum": request.get("result_enum"),
                "proof_schema": request.get("proof_schema"),
                "examples": request.get("examples"),
            }
            prepare = self._capsule_stage3.prepare_ephemeral_computation_capture_v4
        else:
            raise Stage3Error("capture_request_invalid")
        selection = {
            "module_relpath": offer.get("module_relpath"),
            "export_name": offer.get("export_name"),
            "target_binding_id": offer.get("target_binding_id"),
        }
        prepared = prepare(
            snapshot,
            selection,
            mapping,
            review_id=review_id,
        )
        if type(prepared) is dict:
            status = str(prepared.get("status") or "")
            returned_review = prepared.get("review_id")
            if status == "rejected" and review_id is not None:
                self._capsule_stage3.reject_review(
                    review_id,
                    reason_code=str(
                        prepared.get("error_code")
                        or "ephemeral_capture_rejected"
                    ),
                )
            with self._management_lock:
                current = self._javascript_capture_sessions.get(project_id)
                if current is session and status == "waiting_user":
                    current["consumed"][offer_id] = returned_review
                elif current is session and status == "rejected":
                    current["offers"].pop(offer_id, None)
            return prepared
        outcome = self._capsule_stage3.process_ephemeral_capture(prepared)
        with self._management_lock:
            current = self._javascript_capture_sessions.get(project_id)
            if current is session:
                current["offers"].pop(offer_id, None)
                current["consumed"].pop(offer_id, None)
        return outcome

    def start_inspect_computation_adapters(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._error("adapter_creation_path_retired")

    def start_create_computation_adapter(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            project_id = str(request.get("project_id") or "").strip()
            offer_id = str(request.get("offer_id") or "").strip()
            if not project_id:
                return self._error("project_id_required")
            if not offer_id:
                return self._error("adapter_mapping_invalid")

            with self._management_lock:
                is_ephemeral_v2 = project_id in self._javascript_capture_sessions
            if is_ephemeral_v2:
                mapping_schema = request.get("schema")
                if mapping_schema is None:
                    allowed_keys = {
                        "project_id",
                        "offer_id",
                        "review_id",
                        "arguments",
                        "result_field",
                        "examples",
                    }
                elif mapping_schema == CAPTURE_MAPPING_V3:
                    allowed_keys = {
                        "schema",
                        "project_id",
                        "offer_id",
                        "review_id",
                        "arguments",
                        "result_field",
                        "passthrough_fields",
                        "examples",
                    }
                elif mapping_schema == CAPTURE_MAPPING_V4:
                    allowed_keys = {
                        "schema",
                        "project_id",
                        "offer_id",
                        "review_id",
                        "arguments",
                        "result_field",
                        "result_enum",
                        "proof_schema",
                        "examples",
                    }
                else:
                    return self._error("capture_request_invalid")
                if set(request) - allowed_keys:
                    return self._error("capture_request_invalid")
                return self._submit_management_task(
                    "create_javascript_computation_capture",
                    lambda cancel: self._ephemeral_capture_request(request, cancel),
                    cancellable=True,
                )
            if request.get("review_id") is not None:
                return self._error("adapter_contract_version_expired")
            return self._error("adapter_creation_path_retired")
        except ValueError as exc:
            return self._exception_error(exc, "create_computation_adapter_invalid")

    def start_refresh_all(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            self._payload(payload)

            def action(cancel: threading.Event) -> dict[str, Any]:
                with self._capsule_store.read_connection() as connection:
                    project_ids = [
                        str(row[0])
                        for row in connection.execute(
                            "SELECT project_id FROM projects WHERE project_state = 'ready' "
                            "ORDER BY created_at, project_id"
                        )
                    ]
                results = []
                for project_id in project_ids:
                    if cancel.is_set():
                        break
                    try:
                        results.append(self._refresh_project(project_id, cancel))
                    except (IntakeError, Stage3Error) as exc:
                        results.append({"project_id": project_id, "error_code": exc.code})
                return {
                    "status": "cancelled" if cancel.is_set() else "completed",
                    "project_count": len(project_ids),
                    "results": results,
                }

            return self._submit_management_task("refresh_all", action, cancellable=True)
        except ValueError as exc:
            return self._exception_error(exc, "refresh_all_invalid")

    def get_intake_run(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            run_id = str(request.get("run_id") or "").strip()
            if not run_id:
                return self._error("run_id_required")
            try:
                product_run = (
                    self._product_planner
                    .get_capability_source_proposal_run(run_id)
                )
            except ProductPlanningError as exc:
                if exc.code not in {
                    "capability_source_proposal_run_not_found",
                }:
                    raise
            else:
                with self._management_lock:
                    live = self._management_tasks.get(run_id)
                if (
                    live is None
                    and product_run["status"] in {"pending", "running"}
                ):
                    product_run = (
                        self._product_planner
                        .append_capability_source_proposal_run_event(
                            run_id,
                            status="failed",
                            stage=product_run["stage"],
                            error_code="manual_recovery_required",
                        )
                    )
                return self._ok(product_run)
            with self._management_lock:
                task = self._management_tasks.get(run_id)
                if task is not None:
                    if str(task["kind"]).startswith("product_plan_"):
                        return self._error("intake_run_not_found")
                    return self._ok(self._task_view(task))
            with self._capsule_operation_lock:
                self._ensure_capsule_management()
                with self._capsule_store.read_connection() as connection:
                    row = connection.execute(
                        "SELECT * FROM intake_runs WHERE run_id = ?", (run_id,)
                    ).fetchone()
                    if row is None:
                        return self._error("intake_run_not_found")
                    result = self._json_columns(dict(row), ("counts_json",))
                    result["review_counts"] = {
                        str(item["candidate_status"]): int(item["count"])
                        for item in connection.execute(
                            "SELECT candidate_status, COUNT(*) AS count FROM review_items "
                            "WHERE run_id = ? GROUP BY candidate_status",
                            (run_id,),
                        )
                    }
            return self._ok(result)
        except (
            CapsuleStoreError,
            OSError,
            ProductPlanningError,
            ValueError,
        ) as exc:
            return self._exception_error(exc, "get_intake_run_failed")

    def cancel_intake_run(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            run_id = str(request.get("run_id") or "").strip()
            if not run_id:
                return self._error("run_id_required")
            try:
                product_run = (
                    self._product_planner
                    .get_capability_source_proposal_run(run_id)
                )
            except ProductPlanningError as exc:
                if exc.code not in {
                    "capability_source_proposal_run_not_found",
                }:
                    raise
            else:
                if product_run["status"] in {
                    "review_required",
                    "failed",
                    "cancelled",
                }:
                    return self._error("intake_run_already_terminal")
                with self._management_lock:
                    task = self._management_tasks.get(run_id)
                    if task is None:
                        self._product_planner.append_capability_source_proposal_run_event(
                            run_id,
                            status="failed",
                            stage=product_run["stage"],
                            error_code="manual_recovery_required",
                        )
                        return self._error("intake_run_not_cancellable")
                    task["cancel_event"].set()
                return self._ok(
                    {"run_id": run_id, "cancel_requested": True}
                )
            with self._management_lock:
                task = self._management_tasks.get(run_id)
                if task is None:
                    return self._error("intake_run_not_cancellable")
                if str(task["kind"]).startswith("product_plan_"):
                    return self._error("intake_run_not_cancellable")
                if not task["cancellable"]:
                    return self._error("intake_run_not_cancellable")
                if task["status"] in _TERMINAL_TASK_STATES:
                    return self._error("intake_run_already_terminal")
                task["cancel_event"].set()
            return self._ok({"run_id": run_id, "cancel_requested": True})
        except (ProductPlanningError, ValueError) as exc:
            return self._exception_error(exc, "cancel_intake_run_failed")

    def list_supervision_models(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            self._payload(payload)
            return self._submit_management_task(
                "list_supervision_models",
                lambda _cancel: {
                    "models": self._capsule_supervisor.list_models(self._ollama_base_url)
                },
            )
        except ValueError as exc:
            return self._exception_error(exc, "list_supervision_models_invalid")

    def select_supervision_model(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            name = str(request.get("name") or "")
            digest = str(request.get("digest") or "")
            if not name or not digest:
                return self._error("supervision_model_required")
            return self._submit_management_task(
                "select_supervision_model",
                lambda _cancel: self._capsule_supervisor.select_model(
                    self._ollama_base_url,
                    name,
                    digest,
                ),
            )
        except ValueError as exc:
            return self._exception_error(exc, "select_supervision_model_failed")

    def list_product_planning_models(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if request:
                return self._error("product_planning_request_invalid")
            return self._submit_management_task(
                "product_plan_list_models",
                lambda _cancel: self._product_planner.list_models(),
                read_only_planning=True,
            )
        except ValueError as exc:
            return self._exception_error(exc, "product_planning_request_invalid")

    def list_reusable_product_capabilities(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            if self._payload(payload):
                return self._error("reusable_capability_request_invalid")
            with self._capsule_operation_lock:
                catalog = self._product_planning_catalog()
                identities = catalog["capsules"]
                capsule_ids = [item["capsule_id"] for item in identities]
                loaded = []
                if capsule_ids:
                    loaded, _scope, _page_contracts = (
                        self._load_generation_capsules_with_page_contracts(
                            capsule_ids,
                            read_only=True,
                        )
                    )
                by_id = {item["capsule_id"]: item for item in loaded}
                with self._capsule_store.read_connection() as connection:
                    result = []
                    for identity in identities:
                        capsule = by_id.get(identity["capsule_id"])
                        source = connection.execute(
                            "SELECT relationship FROM capsule_sources "
                            "WHERE version_id = ? AND candidate_canonical_hash = ? "
                            "AND relationship IN ('exact', 'published_implementation') "
                            "ORDER BY source_link_id LIMIT 1",
                            (identity["version_id"], identity["canonical_hash"]),
                        ).fetchone()
                        if capsule is None or source is None:
                            raise ProductGenerationError(
                                "reusable_capability_source_invalid"
                            )
                        result.append(
                            {
                                **identity,
                                "input_contract": capsule["input_contract"],
                                "output_contract": capsule["output_contract"],
                                "source": {
                                    "status": "formal_exact_source_verified",
                                    "relationship": str(source["relationship"]),
                                },
                            }
                        )
            return self._ok(
                {
                    "schema_version": "reweave_reusable_capability_catalog.v1",
                    "warehouse_revision": catalog["warehouse_revision"],
                    "capabilities": result,
                }
            )
        except (
            CapsuleStoreError,
            OSError,
            ProductGenerationError,
            RuntimeError,
            sqlite3.Error,
            ValueError,
        ) as exc:
            return self._exception_error(
                exc,
                "reusable_capability_catalog_unavailable",
            )

    def select_product_planning_model(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if set(request) != {"name", "digest"}:
                return self._error("product_planning_model_required")
            name = request["name"]
            digest = request["digest"]
            if type(name) is not str or type(digest) is not str:
                return self._error("product_planning_model_required")
            return self._submit_management_task(
                "product_plan_model_probe",
                lambda _cancel, phase: self._product_planner.select_model(
                    name,
                    digest,
                    phase_callback=phase,
                ),
                read_only_planning=True,
                planning_progress=True,
            )
        except ValueError as exc:
            return self._exception_error(exc, "product_planning_model_required")

    def start_product_plan(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if set(request) not in (
                {"goal"},
                {"goal", "supersedes_plan_token"},
            ):
                return self._error("product_plan_goal_invalid")
            goal = request["goal"]
            supersedes = request.get("supersedes_plan_token")
            if (
                type(goal) is not str
                or not goal.strip()
                or len(goal) > 4_000
                or (supersedes is not None and type(supersedes) is not str)
            ):
                return self._error("product_plan_goal_invalid")

            def action(
                cancel: threading.Event,
                phase: Callable[[str], None],
            ) -> dict[str, Any]:
                return self._product_planner.start(
                    goal.strip(),
                    self._product_planning_catalog(),
                    cancel.is_set,
                    resume_plan_token=supersedes,
                    phase_callback=phase,
                )

            return self._submit_management_task(
                "product_plan_start",
                action,
                cancellable=True,
                read_only_planning=True,
                planning_progress=True,
            )
        except ValueError as exc:
            return self._exception_error(exc, "product_plan_goal_invalid")

    def start_product_capability_replan(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if (
                set(request)
                != {"plan_token", "plan_digest", "projection_digest"}
                or any(
                    type(request[key]) is not str or not request[key]
                    for key in request
                )
            ):
                return self._error("capability_replan_unavailable")

            def action(
                cancel: threading.Event,
                phase: Callable[[str], None],
            ) -> dict[str, Any]:
                catalog = self._product_planning_catalog()
                source = self._product_planner._workspace_by_token(
                    request["plan_token"]
                )
                existing = (
                    self._product_planner
                    ._read_capability_replan_handoff(source)
                )
                binding = None
                if existing is None:
                    binding, _offer, _projection = (
                        self._resolve_product_capability_replan(
                            request["plan_token"],
                            request["plan_digest"],
                            request["projection_digest"],
                            catalog,
                        )
                    )
                return self._product_planner.start_capability_replan(
                    request["plan_token"],
                    request["plan_digest"],
                    request["projection_digest"],
                    binding,
                    catalog,
                    cancel.is_set,
                    phase_callback=phase,
                )

            return self._submit_management_task(
                "product_plan_capability_replan",
                action,
                cancellable=True,
                read_only_planning=True,
                planning_progress=True,
            )
        except (
            CapsuleStoreError,
            OSError,
            ProductGenerationError,
            ProductPlanningError,
            ValueError,
            sqlite3.Error,
        ) as exc:
            return self._exception_error(
                exc,
                "capability_replan_unavailable",
            )

    def submit_product_plan_answers(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if set(request) != {
                "plan_token",
                "question_set_digest",
                "answers",
            }:
                return self._error("product_plan_answers_invalid")
            if (
                type(request["plan_token"]) is not str
                or type(request["question_set_digest"]) is not str
                or type(request["answers"]) is not list
            ):
                return self._error("product_plan_answers_invalid")
            return self._submit_management_task(
                "product_plan_answers",
                lambda cancel, phase: self._product_planner.answer(
                    request["plan_token"],
                    request["question_set_digest"],
                    request["answers"],
                    self._product_planning_catalog(),
                    cancel.is_set,
                    phase_callback=phase,
                ),
                cancellable=True,
                read_only_planning=True,
                planning_progress=True,
            )
        except ValueError as exc:
            return self._exception_error(exc, "product_plan_answers_invalid")

    def revise_product_plan(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            action = request.get("action")
            selected_action = request.get("selected_action")
            target_operation = request.get("target_operation")
            if action == "request" and target_operation in {"add", "update"}:
                expected = {
                    "plan_token",
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
            elif action == "request":
                expected = (
                    {
                        "plan_token",
                        "action",
                        "message",
                        "reviewed_plan",
                        "selected_action",
                        "suggestion_receipt",
                        "suggestion_digest",
                        "target_section_id",
                    }
                    if selected_action == "propose_revision"
                    else {
                        "plan_token",
                        "action",
                        "message",
                        "reviewed_plan",
                        "selected_action",
                        "suggestion_receipt",
                        "suggestion_digest",
                    }
                )
            elif action == "edit_diff":
                expected = {
                    "plan_token",
                    "action",
                    "expected_diff_digest",
                    "fields",
                }
            else:
                expected = {
                    "plan_token",
                    "action",
                    "base_plan_digest",
                    "diff_digest",
                    "reviewed_plan",
                    "reviewed_diff",
                }
            if (
                set(request) != expected
                or action
                not in {"request", "edit_diff", "accept_diff", "reject_diff"}
                or type(request.get("plan_token")) is not str
                or (
                    action == "request"
                    and target_operation in {"add", "update"}
                    and (
                        type(request.get("message")) is not str
                        or type(request.get("target_section_id")) is not str
                        or (
                            target_operation == "add"
                            and (
                                type(request.get("requirement_refs")) is not list
                                or any(
                                    type(ref) is not str
                                    for ref in request["requirement_refs"]
                                )
                            )
                        )
                        or (
                            target_operation == "update"
                            and type(request.get("target_binding_ref")) is not str
                        )
                    )
                )
                or (
                    action == "request"
                    and target_operation not in {"add", "update"}
                    and (
                        type(request.get("message")) is not str
                        or type(request.get("reviewed_plan")) is not dict
                        or type(request.get("selected_action")) is not str
                        or type(request.get("suggestion_receipt")) is not str
                        or type(request.get("suggestion_digest")) is not str
                        or (
                            selected_action == "propose_revision"
                            and type(request.get("target_section_id")) is not str
                        )
                    )
                )
                or (
                    action == "edit_diff"
                    and (
                        type(request.get("expected_diff_digest")) is not str
                        or type(request.get("fields")) is not dict
                    )
                )
                or (
                    action in {"accept_diff", "reject_diff"}
                    and (
                        type(request.get("base_plan_digest")) is not str
                        or type(request.get("diff_digest")) is not str
                        or type(request.get("reviewed_plan")) is not dict
                        or type(request.get("reviewed_diff")) is not dict
                    )
                )
            ):
                return self._error("product_plan_revision_invalid")
            revision = {
                key: value
                for key, value in request.items()
                if key != "plan_token"
            }
            if action == "request":
                revision["message"] = request["message"]
            plan_token = request["plan_token"]
            return self._submit_management_task(
                "product_plan_revision",
                lambda cancel, phase: self._product_planner.revise(
                    plan_token,
                    revision,
                    self._product_planning_catalog(),
                    cancel.is_set,
                    phase_callback=phase,
                ),
                cancellable=action == "request",
                read_only_planning=True,
                planning_progress=True,
            )
        except ValueError as exc:
            return self._exception_error(exc, "product_plan_revision_invalid")

    def suggest_product_plan_action(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if (
                set(request) != {"plan_token", "feedback"}
                or type(request.get("plan_token")) is not str
                or type(request.get("feedback")) is not str
            ):
                return self._error("product_plan_action_suggestion_invalid")
            return self._submit_management_task(
                "product_plan_action_suggestion",
                lambda cancel: self._product_planner.suggest_action(
                    request["plan_token"],
                    request["feedback"],
                    cancel.is_set,
                ),
                cancellable=True,
                read_only_planning=True,
            )
        except ValueError as exc:
            return self._exception_error(
                exc,
                "product_plan_action_suggestion_invalid",
            )

    def get_product_plan_run(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if set(request) != {"run_id"} or type(request["run_id"]) is not str:
                return self._error("product_plan_run_id_required")
            run_id = request["run_id"].strip()
            with self._management_lock:
                task = self._management_tasks.get(run_id)
                if task is None or not str(task["kind"]).startswith("product_plan_"):
                    return self._error("product_plan_run_not_found")
                return self._ok(self._task_view(task))
        except ValueError as exc:
            return self._exception_error(exc, "product_plan_run_invalid")

    def cancel_product_plan_run(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if set(request) != {"run_id"} or type(request["run_id"]) is not str:
                return self._error("product_plan_run_id_required")
            run_id = request["run_id"].strip()
            with self._management_lock:
                task = self._management_tasks.get(run_id)
                if (
                    task is None
                    or not str(task["kind"]).startswith("product_plan_")
                    or task["cancellable"] is not True
                ):
                    return self._error("product_plan_run_not_cancellable")
                if task["status"] in _TERMINAL_TASK_STATES:
                    return self._error("product_plan_run_already_terminal")
                task["cancel_event"].set()
            return self._ok({"run_id": run_id, "cancel_requested": True})
        except ValueError as exc:
            return self._exception_error(exc, "product_plan_cancel_failed")

    def get_product_plan_workspace(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if (
                set(request) != {"plan_token"}
                or type(request["plan_token"]) is not str
            ):
                return self._error("product_plan_token_invalid")
            with self._capsule_operation_lock:
                catalog = self._product_planning_catalog()
                restored = self._product_planner.get(
                    request["plan_token"],
                    catalog,
                )
                data = restored.get("data") if type(restored) is dict else None
                published_source_review = False
                if restored.get("ok") is True and type(data) is dict:
                    for gap in data.get("capability_gaps") or []:
                        run = (
                            gap.get("source_proposal_run")
                            if type(gap) is dict
                            else None
                        )
                        if (
                            type(run) is dict
                            and run.get("status") == "review_required"
                        ):
                            outcome = (
                                self._capability_source_proposal_review_outcome(
                                    run.get("review_id")
                                )
                            )
                            run["review_outcome"] = outcome
                            published_source_review = (
                                published_source_review
                                or (
                                    type(outcome) is dict
                                    and outcome.get("status") == "published"
                                )
                            )
                if (
                    restored.get("ok") is True
                    and type(data) is dict
                    and data.get("plan_token") == request["plan_token"]
                    and data.get("capability_replan") is None
                    and published_source_review
                    and hasattr(
                        self._product_planner,
                        "_workspace_by_token",
                    )
                    and hasattr(
                        self._product_planner,
                        "_read_capability_gap_projection",
                    )
                ):
                    workspace = self._product_planner._workspace_by_token(
                        request["plan_token"]
                    )
                    data["capability_replan"] = (
                        self._product_capability_replan_view(
                            workspace,
                            catalog,
                        )
                    )
                confirmation = (
                    data.get("confirmation") if type(data) is dict else None
                )
                plan = data.get("plan") if type(data) is dict else None
                if (
                    restored.get("ok") is not True
                    or type(confirmation) is not dict
                    or confirmation.get("schema_version")
                    != "product_plan_confirmation.v2"
                    or type(plan) is not dict
                ):
                    return restored
                capsule_ids = sorted(
                    {
                        binding["capsule_id"]
                        for section in plan["sections"]
                        for item in section["work_items"]
                        for binding in item["capsule_bindings"]
                    }
                )
                capsules, _scope = self._load_generation_capsules(
                    capsule_ids,
                    read_only=True,
                )
                return self._product_planner.get(
                    request["plan_token"],
                    catalog,
                    [
                        {
                            key: capsule[key]
                            for key in (
                                "capsule_id",
                                "version_id",
                                "canonical_hash",
                                "capability_key",
                                "capability_kind",
                                "input_contract",
                                "output_contract",
                            )
                        }
                        for capsule in capsules
                    ],
                )
        except (CapsuleStoreError, OSError, ProductGenerationError, ValueError) as exc:
            return self._exception_error(exc, "product_plan_workspace_failed")

    def confirm_product_plan(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            expected = {"plan_token", "plan_digest", "reviewed_plan"}
            if (
                set(request) not in (expected, {*expected, "parameter_confirmation"})
                or type(request["plan_token"]) is not str
                or type(request["plan_digest"]) is not str
                or type(request["reviewed_plan"]) is not dict
                or (
                    "parameter_confirmation" in request
                    and type(request["parameter_confirmation"]) is not dict
                )
            ):
                return self._error("product_plan_confirmation_invalid")
            with self._capsule_operation_lock:
                restored = self._product_planner.get(request["plan_token"])
                if restored.get("ok") is not True:
                    return restored
                stored = restored.get("data")
                stored_plan = stored.get("plan") if type(stored) is dict else None
                if (
                    type(stored_plan) is not dict
                    or stored_plan != request["reviewed_plan"]
                    or stored_plan.get("canonical_digest")
                    != request["plan_digest"]
                    or stored.get("status") not in {"plan_review", "confirmed"}
                    or stored.get("plan_diff") is not None
                ):
                    catalog = self._product_planning_catalog()
                    result = self._product_planner.confirm(
                        request["plan_token"],
                        request["plan_digest"],
                        request["reviewed_plan"],
                        catalog,
                        None,
                        request.get("parameter_confirmation"),
                    )
                    if (
                        result.get("ok") is True
                        and result.get("data", {}).get("status") == "confirmed"
                    ):
                        self._record_product_experience(
                            request["plan_token"],
                            "plan_confirmed",
                            catalog=catalog,
                        )
                    return result
                capsule_ids = sorted(
                    {
                        str(binding["capsule_id"])
                        for section in stored_plan["sections"]
                        for item in section["work_items"]
                        for binding in item["capsule_bindings"]
                    }
                )
                parameter_capsules: list[dict[str, Any]] = []
                if capsule_ids:
                    loaded, _scope = self._load_generation_capsules(
                        capsule_ids,
                        read_only=True,
                    )
                    parameter_capsules = [
                        {
                            key: capsule[key]
                            for key in (
                                "capsule_id",
                                "version_id",
                                "canonical_hash",
                                "capability_key",
                                "capability_kind",
                                "input_contract",
                                "output_contract",
                            )
                        }
                        for capsule in loaded
                    ]
                catalog = self._product_planning_catalog()
                result = self._product_planner.confirm(
                    request["plan_token"],
                    request["plan_digest"],
                    request["reviewed_plan"],
                    catalog,
                    parameter_capsules,
                    request.get("parameter_confirmation"),
                )
                if (
                    result.get("ok") is True
                    and result.get("data", {}).get("status") == "confirmed"
                ):
                    self._record_product_experience(
                        request["plan_token"],
                        "plan_confirmed",
                        catalog=catalog,
                    )
                return result
        except (
            CapsuleStoreError,
            OSError,
            ProductGenerationError,
            ProductPlanningError,
            ValueError,
        ) as exc:
            return self._exception_error(exc, "product_plan_confirmation_failed")

    def _record_product_experience(
        self,
        plan_token: str,
        milestone: str,
        *,
        catalog: dict[str, Any] | None = None,
        candidate: dict[str, Any] | None = None,
        export_status: str | None = None,
    ) -> dict[str, Any] | None:
        try:
            return self._product_planner.record_product_experience(
                plan_token,
                catalog or self._product_planning_catalog(),
                milestone,
                candidate=candidate,
                export_status=export_status,
            )
        except ProductPlanningError as exc:
            raise ProductGenerationError(exc.code) from exc

    def retrieve_product_experience(
        self,
        plan_token: str,
        limit: int = 3,
    ) -> dict[str, Any]:
        with self._capsule_operation_lock:
            return self._product_planner.retrieve_product_experience(
                plan_token,
                limit,
            )

    def record_product_capability_gap_decision(
        self,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if set(request) != {
                "plan_token",
                "plan_digest",
                "projection_digest",
                "expected_previous_decision_digest",
                "decision",
                "behavior_intent",
                "reason",
                "acceptance_cases",
            }:
                return self._error("capability_gap_decision_invalid")
            with self._capsule_operation_lock:
                return self._product_planner.record_capability_gap_decision(
                    request["plan_token"],
                    request["plan_digest"],
                    request["projection_digest"],
                    request["expected_previous_decision_digest"],
                    request["decision"],
                    request["behavior_intent"],
                    request["reason"],
                    request["acceptance_cases"],
                    self._product_planning_catalog(),
                )
        except (
            CapsuleStoreError,
            OSError,
            ProductGenerationError,
            ValueError,
        ) as exc:
            return self._exception_error(
                exc,
                "capability_gap_decision_failed",
            )

    def prepare_product_capability_source_proposal(
        self,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if set(request) != {
                "plan_token",
                "plan_digest",
                "projection_digest",
                "authorize_decision_digest",
            }:
                return self._error(
                    "capability_source_proposal_authorization_invalid"
                )
            with self._capsule_operation_lock:
                return (
                    self._product_planner.prepare_capability_source_proposal(
                        request["plan_token"],
                        request["plan_digest"],
                        request["projection_digest"],
                        request["authorize_decision_digest"],
                        self._product_planning_catalog(),
                    )
                )
        except (
            CapsuleStoreError,
            OSError,
            ProductGenerationError,
            ValueError,
        ) as exc:
            return self._exception_error(
                exc,
                "capability_source_proposal_authorization_failed",
            )

    @staticmethod
    def _source_proposal_error_code(exc: BaseException) -> str:
        code = getattr(exc, "code", None)
        return (
            code
            if type(code) is str
            and re.fullmatch(r"[a-z][a-z0-9_]{1,95}", code)
            else "capability_source_proposal_run_failed"
        )

    @staticmethod
    def _prepared_review_runtime_digests(prepared: Any) -> dict[str, str]:
        return {
            "capture_digest": hashlib.sha256(
                prepared.candidate_payload_json
            ).hexdigest(),
            "runtime_digest": hashlib.sha256(
                prepared.preflight_receipt_json
            ).hexdigest(),
        }

    def _run_product_capability_source_proposal(
        self,
        run_id: str,
        cancel: threading.Event,
    ) -> dict[str, Any]:
        stage = "source_proposal"

        def cancelled() -> None:
            if cancel.is_set():
                raise ProductPlanningError("cancelled_by_user")

        def running(
            next_stage: str,
            evidence: dict[str, Any] | None = None,
        ) -> None:
            nonlocal stage
            stage = next_stage
            self._product_planner.append_capability_source_proposal_run_event(
                run_id,
                status="running",
                stage=stage,
                evidence=evidence or {},
            )

        try:
            running("source_proposal")
            generated = (
                self._product_planner.run_capability_source_proposal_model(
                    run_id,
                    cancel.is_set,
                )
            )
            cancelled()
            proposal = generated["proposal"]
            content = proposal["files"][0]["content"]
            source = self._product_planner.write_capability_source_proposal(
                run_id,
                content,
            )
            running(
                "intake",
                {
                    "source_sha256": source["source_sha256"],
                    "source_relpath": source["source_relpath"],
                    "model_response_digest": generated["evidence"][
                        "response_digest"
                    ],
                },
            )
            cancelled()

            context = (
                self._product_planner.capability_source_proposal_run_context(
                    run_id
                )
            )
            authorization = context["authorization"]
            identity = context["identity"]
            paths = self._product_planner.capability_source_proposal_run_paths(
                run_id
            )
            validation_database = paths["validation_database"]
            if validation_database.exists() or validation_database.is_symlink():
                raise ProductPlanningError(
                    "capability_source_proposal_run_conflict"
                )
            _copy_private_file(
                self._capsule_store.path,
                validation_database,
            )
            isolated_store = CapsuleWarehouseStore(validation_database)
            isolated_intake = ReweaveCapsuleIntake(isolated_store)
            isolated_source = JavascriptSourceService(isolated_store)
            isolated_supervisor = OllamaSupervisor(isolated_store)
            isolated_stage3 = ReweaveCapsuleStage3(
                isolated_store,
                intake=isolated_intake,
                supervisor=isolated_supervisor,
            )
            selected_supervisor = isolated_supervisor.selected_model()
            if {
                "name": selected_supervisor["name"],
                "digest": selected_supervisor["digest"],
            } != identity["supervision_model"]:
                raise ProductPlanningError(
                    "capability_source_proposal_supervision_model_changed"
                )
            with self._capsule_store.read_connection() as connection:
                target_selected = connection.execute(
                    "SELECT value_json FROM app_settings WHERE setting_key = "
                    "'capsule_supervision_model'"
                ).fetchone()
            try:
                target_model = json.loads(target_selected[0])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ProductPlanningError(
                    "capability_source_proposal_supervision_model_changed"
                ) from exc
            if {
                "name": target_model.get("name"),
                "digest": target_model.get("digest"),
            } != identity["supervision_model"]:
                raise ProductPlanningError(
                    "capability_source_proposal_supervision_model_changed"
                )

            with isolated_store.read_connection() as connection:
                existing_root = connection.execute(
                    "SELECT root_id FROM source_roots WHERE current_path = ?",
                    (str(paths["source_dir"].resolve()),),
                ).fetchone()
            if existing_root is None:
                root = isolated_intake.bind_source_root(
                    paths["source_dir"],
                    root_kind="single_project",
                )
                root_id = str(root["root_id"])
            else:
                root_id = str(existing_root["root_id"])
            owner = isolated_source.ensure_owner(root_id)
            snapshot = isolated_source.scan(
                str(owner["project_id"]),
                cancel_event=cancel,
            )
            offers = inspect_ephemeral_computation_offers_v2(snapshot)
            if len(offers["offers"]) != 1:
                raise ProductPlanningError(
                    "capability_source_proposal_capture_invalid"
                )
            offer = offers["offers"][0]
            selection, mapping = (
                self._capability_source_proposal_capture_request(
                    authorization,
                    offer,
                    proposal,
                )
            )
            running(
                "security",
                {
                    "source_identity_sha256": (
                        snapshot.source_identity_sha256
                    ),
                    "security_digest": canonical_json_digest(
                        {
                            "selection": selection,
                            "rejection_summary": offers[
                                "rejection_summary"
                            ],
                        }
                    ),
                },
            )
            cancelled()
            prepare = {
                COMPUTATION_ADAPTER_V2: (
                    isolated_stage3.prepare_ephemeral_computation_capture_v2
                ),
                COMPUTATION_ADAPTER_V3: (
                    isolated_stage3.prepare_ephemeral_computation_capture_v3
                ),
                COMPUTATION_ADAPTER_V4: (
                    isolated_stage3.prepare_ephemeral_computation_capture_v4
                ),
            }.get(authorization["adapter_contract_version"])
            if prepare is None:
                raise ProductPlanningError(
                    "capability_source_proposal_capture_invalid"
                )
            prepared = prepare(
                snapshot,
                selection,
                mapping,
            )
            if type(prepared) is dict:
                raise ProductPlanningError(
                    "capability_source_proposal_review_not_ready"
                )
            running(
                "runtime",
                self._prepared_review_runtime_digests(prepared),
            )
            cancelled()
            running("supervision")
            result = isolated_stage3.process_ephemeral_capture(prepared)
            cancelled()
            review_id = str(result.get("review_id") or "")
            if result.get("status") != "review_required" or not review_id:
                raise ProductPlanningError(
                    "capability_source_proposal_review_not_ready"
                )
            with isolated_store.read_connection() as connection:
                review = connection.execute(
                    "SELECT supervision_result_json FROM review_items "
                    "WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
            if review is None or not review["supervision_result_json"]:
                raise ProductPlanningError(
                    "capability_source_proposal_review_not_ready"
                )
            running(
                "admission",
                {
                    "supervision_digest": hashlib.sha256(
                        str(review["supervision_result_json"]).encode(
                            "utf-8"
                        )
                    ).hexdigest(),
                    "validation_database_sha256": _sha256_file(
                        validation_database
                    ),
                },
            )
            cancelled()
            current_catalog = self._product_planning_catalog()
            if (
                current_catalog["warehouse_revision"]
                != identity["warehouse_revision"]
                or canonical_json_digest(current_catalog)
                != identity["catalog_digest"]
            ):
                raise ProductPlanningError(
                    "capability_source_proposal_run_stale"
                )
            admission = self.admit_frozen_review(
                {
                    "source_database_path": str(validation_database),
                    "source_directory_path": str(paths["source_dir"]),
                    "source_database_sha256": _sha256_file(
                        validation_database
                    ),
                    "review_id": review_id,
                    "expected_warehouse_revision": identity[
                        "warehouse_revision"
                    ],
                    "plan_token": identity["plan_token"],
                    "plan_digest": identity["plan_digest"],
                    "projection_digest": identity[
                        "projection_digest"
                    ],
                    "authorize_decision_digest": identity[
                        "authorize_decision_digest"
                    ],
                    "source_proposal_authorization_digest": identity[
                        "authorization_digest"
                    ],
                }
            )
            if admission.get("ok") is not True:
                error = admission.get("error") or {}
                raise ProductPlanningError(
                    str(
                        error.get("code")
                        or "frozen_review_admission_failed"
                    )
                )
            receipt = admission["data"]
            return (
                self._product_planner
                .append_capability_source_proposal_run_event(
                    run_id,
                    status="review_required",
                    stage="admission",
                    evidence={
                        "review_id": review_id,
                        "admission_digest": receipt[
                            "admission_digest"
                        ],
                        "canonical_hash": result["canonical_hash"],
                        "warehouse_revision": receipt[
                            "warehouse_revision"
                        ],
                    },
                )
            )
        except BaseException as exc:
            code = self._source_proposal_error_code(exc)
            status = (
                "cancelled"
                if cancel.is_set() or code == "cancelled_by_user"
                else "failed"
            )
            try:
                return (
                    self._product_planner
                    .append_capability_source_proposal_run_event(
                        run_id,
                        status=status,
                        stage=stage,
                        error_code=(
                            "cancelled_by_user"
                            if status == "cancelled"
                            else code
                        ),
                    )
                )
            except ProductPlanningError:
                raise exc

    def start_product_capability_source_proposal(
        self,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if set(request) != {
                "plan_token",
                "plan_digest",
                "projection_digest",
                "authorization_digest",
            } or any(
                type(request.get(key)) is not str or not request[key]
                for key in request
            ):
                return self._error(
                    "capability_source_proposal_run_invalid"
                )
            with self._capsule_operation_lock:
                self._ensure_capsule_management()
                selected = self._capsule_supervisor.selected_model()
                prepared = (
                    self._product_planner
                    .prepare_capability_source_proposal_run(
                        request["plan_token"],
                        request["plan_digest"],
                        request["projection_digest"],
                        request["authorization_digest"],
                        {
                            "name": selected["name"],
                            "digest": selected["digest"],
                        },
                        self._product_planning_catalog(),
                    )
                )
            run_id = prepared["run_id"]
            if not prepared["created"]:
                with self._management_lock:
                    live = self._management_tasks.get(run_id)
                if live is not None:
                    return {
                        "ok": True,
                        "run_id": run_id,
                        "status": prepared["status"],
                    }
                if prepared["status"] in {"pending", "running"}:
                    recovered = (
                        self._product_planner
                        .append_capability_source_proposal_run_event(
                            run_id,
                            status="failed",
                            stage=prepared["stage"],
                            error_code="manual_recovery_required",
                        )
                    )
                    return {
                        "ok": True,
                        "run_id": run_id,
                        "status": recovered["status"],
                    }
                return {
                    "ok": True,
                    "run_id": run_id,
                    "status": prepared["status"],
                }
            submitted = self._submit_management_task(
                "capability_source_proposal",
                lambda cancel: self._run_product_capability_source_proposal(
                    run_id,
                    cancel,
                ),
                run_id=run_id,
                cancellable=True,
            )
            if submitted.get("ok") is not True:
                self._product_planner.append_capability_source_proposal_run_event(
                    run_id,
                    status="failed",
                    stage=prepared["stage"],
                    error_code=str(
                        (submitted.get("error") or {}).get("code")
                        or "capability_source_proposal_start_failed"
                    ),
                )
            return submitted
        except (
            CapsuleStoreError,
            IntakeError,
            JavascriptSourceError,
            ProductGenerationError,
            ProductPlanningError,
            Stage3Error,
            OSError,
            RuntimeError,
            ValueError,
            sqlite3.Error,
        ) as exc:
            return self._exception_error(
                exc,
                "capability_source_proposal_run_failed",
            )

    def _confirmed_candidate_context(
        self,
        plan_token: str,
    ) -> tuple[
        dict[str, Any],
        list[dict[str, Any]],
        dict[str, Any],
        list[dict[str, Any]],
    ]:
        restored = self._product_planner.get(plan_token)
        data = restored.get("data") if type(restored) is dict else None
        plan = data.get("plan") if type(data) is dict else None
        confirmation = data.get("confirmation") if type(data) is dict else None
        if (
            restored.get("ok") is not True
            or type(data) is not dict
            or data.get("status") != "confirmed"
            or type(plan) is not dict
            or type(confirmation) is not dict
        ):
            code = (
                restored.get("error", {}).get("code")
                if type(restored) is dict
                and type(restored.get("error")) is dict
                else None
            )
            raise ProductGenerationError(
                code
                if type(code) is str
                else "product_candidate_plan_not_confirmed"
            )
        capsule_ids = sorted(
            {
                str(binding["capsule_id"])
                for section in plan["sections"]
                for item in section["work_items"]
                for binding in item["capsule_bindings"]
            }
        )
        capsules, product_scope, page_contracts = self._load_composer_capsules(
            capsule_ids,
            read_only=True,
        )
        current = {
            (capsule["capsule_id"], capsule["version_id"]): capsule
            for capsule in capsules
        }
        if any(
            (binding["capsule_id"], binding["version_id"]) not in current
            or current[(binding["capsule_id"], binding["version_id"])][
                "canonical_hash"
            ]
            != binding["canonical_hash"]
            for section in plan["sections"]
            for item in section["work_items"]
            for binding in item["capsule_bindings"]
        ):
            raise ProductGenerationError("product_candidate_plan_stale")
        parameter_capsules = [
            {
                key: capsule[key]
                for key in (
                    "capsule_id",
                    "version_id",
                    "canonical_hash",
                    "capability_key",
                    "capability_kind",
                    "input_contract",
                    "output_contract",
                )
            }
            for capsule in capsules
        ]
        verified = self._product_planner.get(
            plan_token,
            None,
            parameter_capsules,
        )
        if verified.get("ok") is not True:
            code = (
                verified.get("error", {}).get("code")
                if type(verified.get("error")) is dict
                else None
            )
            raise ProductGenerationError(
                code
                if type(code) is str
                else "product_candidate_plan_not_confirmed"
            )
        return verified["data"], capsules, product_scope, page_contracts

    @staticmethod
    def _agent_handoff_capsule_facts_digest(
        capsules: list[dict[str, Any]],
        product_scope: dict[str, Any],
        page_contracts: list[dict[str, Any]],
    ) -> str:
        return plan_execution_digest(
            {
                "schema_version": "agent_handoff_capsule_facts.v1",
                "capsules": sorted(
                    [
                        {
                            key: capsule[key]
                            for key in (
                                "capsule_id",
                                "version_id",
                                "canonical_hash",
                                "capability_key",
                                "role_key",
                                "variant_key",
                                "capability_kind",
                            )
                        }
                        for capsule in capsules
                    ],
                    key=lambda item: (
                        item["capsule_id"],
                        item["version_id"],
                    ),
                ),
                "page_contracts": sorted(
                    page_contracts,
                    key=lambda item: (
                        item["capsule_id"],
                        item["version_id"],
                    ),
                ),
                "product_scope": product_scope,
            }
        )

    def _validated_candidate_acceptance_confirmation(
        self,
        plan_token: str,
        workspace: dict[str, Any],
        capsules: list[dict[str, Any]],
        page_contracts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        restored = self._product_planner.get_candidate_acceptance_confirmation(
            plan_token
        )
        if restored.get("ok") is not True:
            error = restored.get("error") if type(restored) is dict else None
            code = error.get("code") if type(error) is dict else None
            raise ProductGenerationError(
                code
                if type(code) is str
                else "candidate_acceptance_confirmation_required"
            )
        try:
            execution = self._compile_candidate_execution(
                workspace["plan"],
                workspace["confirmation"],
                capsules,
                page_contracts,
            )
            input_contract, output_contract = (
                self._candidate_acceptance_contracts(capsules, execution)
            )
            return validate_candidate_acceptance_confirmation(
                workspace["plan"],
                workspace["confirmation"],
                restored["data"]["acceptance_confirmation"],
                input_contract,
                output_contract,
            )
        except CandidateAcceptanceError as exc:
            raise ProductGenerationError(exc.code) from exc

    def create_local_agent_handoff(
        self,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if (
                set(request) != {"plan_token"}
                or type(request["plan_token"]) is not str
            ):
                return self._error("agent_handoff_request_invalid")
            with self._capsule_operation_lock:
                workspace, capsules, product_scope, page_contracts = (
                    self._confirmed_candidate_context(request["plan_token"])
                )
                acceptance = (
                    self._validated_candidate_acceptance_confirmation(
                        request["plan_token"],
                        workspace,
                        capsules,
                        page_contracts,
                    )
                )
                result = self._product_planner.create_agent_handoff(
                    request["plan_token"],
                    acceptance["canonical_digest"],
                    self._agent_handoff_capsule_facts_digest(
                        capsules,
                        product_scope,
                        page_contracts,
                    ),
                )
            return result
        except (
            CapsuleStoreError,
            OSError,
            ProductGenerationError,
            ValueError,
        ) as exc:
            return self._exception_error(exc, "agent_handoff_create_failed")

    def revoke_local_agent_handoff(
        self,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if (
                set(request) != {"handoff_token"}
                or type(request["handoff_token"]) is not str
            ):
                return self._error("agent_handoff_request_invalid")
            with self._capsule_operation_lock:
                return self._product_planner.revoke_agent_handoff(
                    request["handoff_token"]
                )
        except (OSError, ValueError) as exc:
            return self._exception_error(exc, "agent_handoff_revoke_failed")

    def _resolve_local_agent_handoff(
        self,
        handoff_token: str,
    ) -> dict[str, Any]:
        with self._capsule_operation_lock:
            resolved = self._product_planner.resolve_agent_handoff(
                handoff_token
            )
            if resolved.get("ok") is not True:
                error = (
                    resolved.get("error")
                    if type(resolved) is dict
                    else None
                )
                code = error.get("code") if type(error) is dict else None
                raise ProductGenerationError(
                    code if type(code) is str else "agent_handoff_invalid"
                )
            binding = resolved["data"]
            try:
                workspace, capsules, product_scope, page_contracts = (
                    self._confirmed_candidate_context(binding["plan_token"])
                )
                acceptance = (
                    self._validated_candidate_acceptance_confirmation(
                        binding["plan_token"],
                        workspace,
                        capsules,
                        page_contracts,
                    )
                )
            except ProductGenerationError as exc:
                raise ProductGenerationError("agent_handoff_stale") from exc
            facts_digest = self._agent_handoff_capsule_facts_digest(
                capsules,
                product_scope,
                page_contracts,
            )
            if (
                workspace["plan"]["canonical_digest"]
                != binding["plan_digest"]
                or workspace["confirmation"]["receipt_digest"]
                != binding["plan_confirmation_digest"]
                or acceptance["canonical_digest"]
                != binding["acceptance_confirmation_digest"]
                or facts_digest != binding["capsule_facts_digest"]
            ):
                raise ProductGenerationError("agent_handoff_stale")
        return {
            "plan_token": binding["plan_token"],
            "plan_digest": binding["plan_digest"],
            "acceptance_confirmation_digest": binding[
                "acceptance_confirmation_digest"
            ],
        }

    def confirm_product_candidate_acceptance(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if (
                set(request)
                != {"plan_token", "plan_digest", "acceptance_cases"}
                or type(request["plan_token"]) is not str
                or type(request["plan_digest"]) is not str
                or _MANIFEST_DIGEST.fullmatch(request["plan_digest"]) is None
                or type(request["acceptance_cases"]) is not list
            ):
                return self._error(
                    "candidate_acceptance_confirmation_request_invalid"
                )
            with self._capsule_operation_lock:
                workspace, capsules, _scope, page_contracts = (
                    self._confirmed_candidate_context(request["plan_token"])
                )
                plan = workspace["plan"]
                confirmation = workspace["confirmation"]
                if plan["canonical_digest"] != request["plan_digest"]:
                    return self._error(
                        "candidate_acceptance_confirmation_stale"
                    )
                execution = self._compile_candidate_execution(
                    plan,
                    confirmation,
                    capsules,
                    page_contracts,
                )
                input_contract, output_contract = (
                    self._candidate_acceptance_contracts(capsules, execution)
                )
                record = build_candidate_acceptance_confirmation(
                    plan,
                    confirmation,
                    request["acceptance_cases"],
                    input_contract,
                    output_contract,
                    _now(),
                )
                persisted = self._product_planner.confirm_candidate_acceptance(
                    request["plan_token"],
                    record,
                )
                if persisted.get("ok") is not True:
                    return persisted
            return self._ok(record)
        except (
            CandidateAcceptanceError,
            CapsuleStoreError,
            OSError,
            ProductGenerationError,
            ValueError,
        ) as exc:
            return self._exception_error(
                exc,
                "candidate_acceptance_confirmation_failed",
            )

    def get_confirmed_product_plan(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if (
                set(request) != {"plan_token"}
                or type(request["plan_token"]) is not str
            ):
                return self._error("product_plan_token_invalid")
            with self._capsule_operation_lock:
                workspace, capsules, _scope, page_contracts = (
                    self._confirmed_candidate_context(request["plan_token"])
                )
                acceptance = (
                    self._product_planner.get_candidate_acceptance_confirmation(
                        request["plan_token"]
                    )
                )
            plan = workspace["plan"]
            confirmation = workspace["confirmation"]
            acceptance_data = (
                acceptance["data"]["acceptance_confirmation"]
                if acceptance.get("ok") is True
                else None
            )
            if (
                acceptance.get("ok") is not True
                and acceptance.get("error", {}).get("code")
                != "candidate_acceptance_confirmation_required"
            ):
                return acceptance
            if type(acceptance_data) is dict:
                execution = self._compile_candidate_execution(
                    plan,
                    confirmation,
                    capsules,
                    page_contracts,
                )
                input_contract, output_contract = (
                    self._candidate_acceptance_contracts(capsules, execution)
                )
                try:
                    acceptance_data = (
                        validate_candidate_acceptance_confirmation(
                            plan,
                            confirmation,
                            acceptance_data,
                            input_contract,
                            output_contract,
                        )
                    )
                except CandidateAcceptanceError as exc:
                    raise ProductGenerationError(exc.code) from exc
            parameters = [
                {
                    "name": binding["input_field"],
                    "value": binding["value"],
                    "source": binding["source"],
                }
                for binding in confirmation.get("parameter_binding", {}).get(
                    "bindings",
                    [],
                )
            ]
            sections = []
            for section in plan["sections"]:
                sections.append(
                    {
                        "section_id": section["section_id"],
                        "work_items": [
                            {
                                "title": item["title"],
                                "summary": item["description"],
                                "acceptance_intent": item[
                                    "acceptance_intent"
                                ],
                                "delivery_wave": item.get("delivery_wave"),
                                "dependency_count": len(item["depends_on"]),
                                "capabilities": [
                                    {
                                        key: binding[key]
                                        for key in (
                                            "display_name",
                                            "capability_kind",
                                            "identity_status",
                                        )
                                    }
                                    for binding in item["capsule_bindings"]
                                ],
                            }
                            for item in section["work_items"]
                        ],
                    }
                )
            return self._ok(
                {
                    "schema_version": "agent_confirmed_product_plan.v1",
                    "plan_token": request["plan_token"],
                    "status": "confirmed",
                    "goal": plan["goal"],
                    "product_name": plan["product_name"],
                    "plan_version": plan["plan_version"],
                    "plan_digest": plan["canonical_digest"],
                    "requirements": [
                        {
                            "statement": requirement["statement"],
                            "source": requirement["source"],
                        }
                        for requirement in plan["requirements"]
                    ],
                    "sections": sections,
                    "confirmation": {
                        "schema_version": confirmation["schema_version"],
                        "confirmed_at": confirmation["confirmed_at"],
                        "parameters": parameters,
                    },
                    "candidate_acceptance": (
                        {
                            "confirmed": True,
                            "confirmation_digest": acceptance_data[
                                "canonical_digest"
                            ],
                            "confirmed_at": acceptance_data["confirmed_at"],
                            "source": acceptance_data[
                                "confirmation_source"
                            ],
                            "cases": [
                                {
                                    key: case[key]
                                    for key in (
                                        "input",
                                        "expected_output",
                                    )
                                }
                                for case in acceptance_data["cases"]
                            ],
                        }
                        if type(acceptance_data) is dict
                        else {"confirmed": False}
                    ),
                }
            )
        except (
            CapsuleStoreError,
            OSError,
            ProductGenerationError,
            ValueError,
        ) as exc:
            return self._exception_error(exc, "product_plan_workspace_failed")

    def _product_candidate_root(self) -> Path:
        return self._capsule_store.path.parent / PRODUCT_CANDIDATES_DIRNAME

    @staticmethod
    def _compile_candidate_execution(
        plan: dict[str, Any],
        confirmation: dict[str, Any],
        capsules: list[dict[str, Any]],
        page_contracts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        computation_count = sum(
            capsule.get("capability_kind") == "computation"
            for capsule in capsules
        )
        if computation_count == 2:
            if confirmation.get("schema_version") != "product_plan_confirmation.v1":
                raise ProductGenerationError(
                    "multi_computation_parameter_binding_unsupported"
                )
            return compile_multi_computation_plan_execution(
                plan,
                confirmation,
                capsules,
                verified_page_contracts=page_contracts,
            )
        return (
            compile_parameterized_plan_execution(
                plan,
                confirmation,
                capsules,
                verified_page_contracts=page_contracts,
            )
            if confirmation.get("schema_version")
            == "product_plan_confirmation.v2"
            else compile_plan_execution(
                plan,
                confirmation,
                capsules,
                verified_page_contracts=page_contracts,
            )
        )

    @staticmethod
    def _candidate_acceptance_contracts(
        capsules: list[dict[str, Any]],
        execution: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        computations = [
            item for item in capsules if item.get("capability_kind") == "computation"
        ]
        interactions = [
            item for item in capsules if item.get("capability_kind") == "interaction"
        ]
        if len(computations) not in {1, 2} or len(interactions) > 1:
            raise ProductGenerationError("candidate_acceptance_computation_required")
        first = terminal = computations[0]
        if len(computations) == 2:
            if (
                type(execution) is not dict
                or execution.get("schema_version")
                != MULTI_COMPUTATION_PLAN_EXECUTION_VERSION
                or type(execution.get("connections")) is not list
            ):
                raise ProductGenerationError(
                    "candidate_acceptance_connection_required"
                )
            by_version = {
                computation["version_id"]: computation
                for computation in computations
            }
            computation_edges = [
                connection
                for connection in execution["connections"]
                if connection.get("source_version_id") in by_version
                and connection.get("target_version_id") in by_version
            ]
            if len(computation_edges) != 1:
                raise ProductGenerationError(
                    "candidate_acceptance_terminal_ambiguous"
                )
            edge = computation_edges[0]
            first = by_version[edge["source_version_id"]]
            terminal = by_version[edge["target_version_id"]]
        input_contract = first.get("input_contract")
        if interactions:
            event_contract = interactions[0].get("output_contract")
            events = (
                event_contract.get("events")
                if type(event_contract) is dict
                and event_contract.get("schema") == "event_outputs.v1"
                else None
            )
            if type(events) is not dict or len(events) != 1:
                raise ProductGenerationError("candidate_acceptance_contract_invalid")
            input_contract = next(iter(events.values()))
        output_contract = terminal.get("output_contract")
        if type(input_contract) is not dict or type(output_contract) is not dict:
            raise ProductGenerationError("candidate_acceptance_contract_invalid")
        return input_contract, output_contract

    @staticmethod
    def _assert_candidate_path_safe(path: Path) -> None:
        absolute = Path(os.path.abspath(path))
        for component in reversed((absolute, *absolute.parents)):
            try:
                metadata = component.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode):
                raise ProductGenerationError("product_candidate_directory_unsafe")

    @staticmethod
    def _candidate_projection(record: dict[str, Any]) -> dict[str, Any]:
        projection = {
            key: json.loads(json.dumps(value, ensure_ascii=False))
            for key, value in record.items()
            if key not in {"candidate_id", "record_digest"}
        }
        if record.get("schema_version") == "product_candidate.v1":
            projection["status"] = "legacy_unverified"
            projection["product_goal_conformance"] = "not_available"
        return projection

    def _read_candidate_record_path(self, candidate_dir: Path) -> dict[str, Any]:
        root = self._product_candidate_root()
        self._assert_candidate_path_safe(root)
        self._assert_candidate_path_safe(candidate_dir)
        try:
            candidate_dir.resolve().relative_to(root.resolve())
        except (OSError, ValueError) as exc:
            raise ProductGenerationError("product_candidate_directory_unsafe") from exc
        metadata = candidate_dir / "candidate.json"
        execution_metadata = candidate_dir / "execution_plan.json"
        product_root = candidate_dir / "product"
        if (
            metadata.is_symlink()
            or not metadata.is_file()
            or execution_metadata.is_symlink()
            or not execution_metadata.is_file()
            or product_root.is_symlink()
            or not product_root.is_dir()
        ):
            raise ProductGenerationError("product_candidate_invalid")
        try:
            record = _strict_json_bytes(metadata.read_bytes())
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ProductGenerationError("product_candidate_invalid") from exc
        v1_required = {
            "schema_version", "status", "candidate_id", "candidate_token",
            "candidate_digest", "record_digest", "created_at", "plan", "execution_digest",
            "composer_version", "entry", "files", "file_changes", "provenance",
            "validation", "permissions",
        }
        if type(record) is not dict:
            raise ProductGenerationError("product_candidate_invalid")
        schema_version = record.get("schema_version")
        if schema_version == "product_candidate.v1":
            required = v1_required
        elif schema_version == "product_candidate.v2":
            required = v1_required | {"candidate_content_digest", "acceptance"}
        else:
            raise ProductGenerationError("product_candidate_invalid")
        if set(record) != required:
            raise ProductGenerationError("product_candidate_invalid")
        core = {
            key: value
            for key, value in record.items()
            if key not in {"candidate_token", "candidate_digest", "record_digest"}
        }
        record_body = {
            key: value for key, value in record.items() if key != "record_digest"
        }
        if (
            record["status"]
            not in (
                {"review_ready"}
                if schema_version == "product_candidate.v1"
                else {"review_ready", "acceptance_failed"}
            )
            or _CANDIDATE_ID.fullmatch(str(record["candidate_id"])) is None
            or record["candidate_id"] != candidate_dir.name
            or _CANDIDATE_TOKEN.fullmatch(str(record["candidate_token"])) is None
            or _MANIFEST_DIGEST.fullmatch(str(record["candidate_digest"])) is None
            or record["candidate_digest"] != plan_execution_digest(core)
            or _MANIFEST_DIGEST.fullmatch(str(record["record_digest"])) is None
            or record["record_digest"] != plan_execution_digest(record_body)
            or _MANIFEST_DIGEST.fullmatch(str(record["execution_digest"])) is None
            or (
                schema_version == "product_candidate.v2"
                and _MANIFEST_DIGEST.fullmatch(
                    str(record["candidate_content_digest"])
                )
                is None
            )
            or type(record["created_at"]) is not str
            or type(record["plan"]) is not dict
            or set(record["plan"]) != {"plan_id", "plan_version", "plan_digest"}
            or not re.fullmatch(r"plan_[0-9a-f]{32}", str(record["plan"]["plan_id"]))
            or type(record["plan"]["plan_version"]) is not int
            or record["plan"]["plan_version"] < 1
            or _MANIFEST_DIGEST.fullmatch(str(record["plan"]["plan_digest"])) is None
            or type(record["composer_version"]) is not str
            or not record["composer_version"]
            or type(record["entry"]) is not dict
            or record["entry"] != {"path": "index.html", "kind": "static_html"}
            or type(record["files"]) is not list
            or not record["files"]
            or type(record["file_changes"]) is not list
            or type(record["provenance"]) is not dict
            or type(record["validation"]) is not dict
            or (
                schema_version == "product_candidate.v2"
                and type(record["acceptance"]) is not dict
            )
            or record["permissions"]
            != {
                "source_project_write": False,
                "target_project_write": False,
                "product_store_write": False,
                "product_usage_write": False,
            }
        ):
            raise ProductGenerationError("product_candidate_invalid")
        try:
            execution = _strict_json_bytes(execution_metadata.read_bytes())
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ProductGenerationError("product_candidate_invalid") from exc
        if (
            type(execution) is not dict
            or execution.get("schema_version")
            not in {
                PLAN_EXECUTION_VERSION,
                PARAMETERIZED_PLAN_EXECUTION_VERSION,
                MULTI_COMPUTATION_PLAN_EXECUTION_VERSION,
            }
            or execution.get("execution_digest") != record["execution_digest"]
            or plan_execution_digest(
                {
                    key: value
                    for key, value in execution.items()
                    if key != "execution_digest"
                }
            )
            != record["execution_digest"]
            or execution.get("plan_id") != record["plan"].get("plan_id")
            or execution.get("plan_version") != record["plan"].get("plan_version")
            or execution.get("plan_digest") != record["plan"].get("plan_digest")
        ):
            raise ProductGenerationError("product_candidate_invalid")
        file_paths: set[str] = set()
        file_text: dict[str, bool] = {}
        file_data: dict[str, bytes] = {}
        for item in record["files"]:
            if (
                type(item) is not dict
                or set(item) != {"path", "sha256", "size_bytes", "text"}
                or type(item["path"]) is not str
                or type(item["size_bytes"]) is not int
                or item["size_bytes"] < 0
                or type(item["text"]) is not bool
                or _MANIFEST_DIGEST.fullmatch(str(item["sha256"])) is None
            ):
                raise ProductGenerationError("product_candidate_invalid")
            logical = _safe_product_relative(item["path"])
            if logical in file_paths:
                raise ProductGenerationError("product_candidate_invalid")
            file_paths.add(logical)
            file_text[logical] = item["text"]
            path = product_root.joinpath(*PurePosixPath(logical).parts)
            self._assert_candidate_path_safe(path)
            if path.is_symlink() or not path.is_file():
                raise ProductGenerationError("product_candidate_invalid")
            data = path.read_bytes()
            file_data[logical] = data
            if (
                len(data) != item["size_bytes"]
                or hashlib.sha256(data).hexdigest() != item["sha256"]
            ):
                raise ProductGenerationError("product_candidate_invalid")
        if record["entry"]["path"] not in file_paths:
            raise ProductGenerationError("product_candidate_invalid")
        if (
            schema_version == "product_candidate.v2"
            and record["candidate_content_digest"]
            != _candidate_content_digest(
                record["execution_digest"],
                record["composer_version"],
                record["entry"],
                record["files"],
            )
        ):
            raise ProductGenerationError("product_candidate_invalid")
        change_paths: set[str] = set()
        for change in record["file_changes"]:
            if (
                type(change) is not dict
                or set(change) != {"path", "operation", "text_diff_sha256"}
                or type(change["path"]) is not str
                or change["operation"] != "added"
                or (
                    change["text_diff_sha256"] is not None
                    and _MANIFEST_DIGEST.fullmatch(str(change["text_diff_sha256"]))
                    is None
                )
            ):
                raise ProductGenerationError("product_candidate_invalid")
            logical = _safe_product_relative(change["path"])
            if logical in change_paths or logical not in file_paths:
                raise ProductGenerationError("product_candidate_invalid")
            if file_text[logical] != (change["text_diff_sha256"] is not None):
                raise ProductGenerationError("product_candidate_invalid")
            if file_text[logical]:
                try:
                    text = file_data[logical].decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ProductGenerationError("product_candidate_invalid") from exc
                expected_diff = "".join(
                    difflib.unified_diff(
                        [],
                        text.splitlines(keepends=True),
                        fromfile="/dev/null",
                        tofile=logical,
                    )
                )
                if (
                    hashlib.sha256(expected_diff.encode("utf-8")).hexdigest()
                    != change["text_diff_sha256"]
                ):
                    raise ProductGenerationError("product_candidate_invalid")
            change_paths.add(logical)
        if change_paths != file_paths:
            raise ProductGenerationError("product_candidate_invalid")
        receipts = record["provenance"].get("file_provenance")
        parameterized_execution = (
            execution["schema_version"] == PARAMETERIZED_PLAN_EXECUTION_VERSION
        )
        multi_computation_execution = (
            execution["schema_version"]
            == MULTI_COMPUTATION_PLAN_EXECUTION_VERSION
        )
        expected_provenance_version = (
            "product_candidate_provenance.v3"
            if multi_computation_execution
            else (
                "product_candidate_provenance.v2"
                if parameterized_execution
                else "product_candidate_provenance.v1"
            )
        )
        provenance_keys = {
            "schema_version",
            "plan_id",
            "plan_version",
            "plan_digest",
            "execution_digest",
            "composer_version",
            "file_provenance",
            "source_project_write",
            "target_project_write",
            "model_source_generation",
        }
        if parameterized_execution:
            provenance_keys.update({"confirmation_digest", "parameter_binding"})
        if multi_computation_execution:
            provenance_keys.update(
                {"connections", "connection_digest", "terminal_output"}
            )
        if (
            set(record["provenance"]) != provenance_keys
            or
            record["provenance"].get("schema_version")
            != expected_provenance_version
            or type(receipts) is not list
            or {receipt.get("path") for receipt in receipts if type(receipt) is dict}
            != file_paths
            or record["validation"].get("static", {}).get("status") != "passed"
            or record["validation"].get("runtime", {}).get("status") != "passed"
        ):
            raise ProductGenerationError("product_candidate_invalid")
        if parameterized_execution and (
            type(execution.get("parameter_binding")) is not dict
            or record["provenance"].get("confirmation_digest")
            != execution.get("confirmation_digest")
            or record["provenance"].get("parameter_binding")
            != execution.get("parameter_binding")
        ):
            raise ProductGenerationError("product_candidate_invalid")
        if multi_computation_execution:
            by_version = {
                capsule["version_id"]: capsule
                for capsule in execution["capsules"]
            }
            terminal_edges = [
                connection
                for connection in execution["connections"]
                if by_version[connection["source_version_id"]][
                    "capability_kind"
                ]
                == "computation"
                and by_version[connection["target_version_id"]][
                    "capability_kind"
                ]
                == "presentation"
            ]
            expected_terminal = (
                {
                    "capsule_id": terminal_edges[0]["source_capsule_id"],
                    "version_id": terminal_edges[0]["source_version_id"],
                    "canonical_hash": terminal_edges[0][
                        "source_canonical_hash"
                    ],
                    "output": terminal_edges[0]["source_output"],
                }
                if len(terminal_edges) == 1
                else None
            )
            if (
                record["provenance"].get("connections")
                != execution.get("connections")
                or record["provenance"].get("connection_digest")
                != execution.get("connection_digest")
                or record["provenance"].get("terminal_output")
                != expected_terminal
            ):
                raise ProductGenerationError("product_candidate_invalid")
        for receipt in receipts:
            if (
                type(receipt) is not dict
                or set(receipt)
                != {
                    "path",
                    "execution_unit_ids",
                    "work_item_ids",
                    "capsule_version_ids",
                }
                or receipt["path"] not in file_paths
                or any(
                    type(receipt[key]) is not list
                    or not receipt[key]
                    or len(receipt[key]) != len(set(receipt[key]))
                    or any(type(value) is not str or not value for value in receipt[key])
                    for key in (
                        "execution_unit_ids",
                        "work_item_ids",
                        "capsule_version_ids",
                    )
                )
            ):
                raise ProductGenerationError("product_candidate_invalid")
        if schema_version == "product_candidate.v1":
            if set(record["validation"]) != {"static", "runtime"}:
                raise ProductGenerationError("product_candidate_invalid")
            return record

        acceptance_contract_path = candidate_dir / "acceptance_contract.json"
        acceptance_receipt_path = candidate_dir / "acceptance_receipt.json"
        if (
            acceptance_contract_path.is_symlink()
            or not acceptance_contract_path.is_file()
            or acceptance_receipt_path.is_symlink()
            or not acceptance_receipt_path.is_file()
        ):
            raise ProductGenerationError("product_candidate_invalid")
        self._assert_candidate_path_safe(acceptance_contract_path)
        self._assert_candidate_path_safe(acceptance_receipt_path)
        try:
            acceptance_contract = _strict_json_bytes(
                acceptance_contract_path.read_bytes()
            )
            acceptance_receipt = _strict_json_bytes(
                acceptance_receipt_path.read_bytes()
            )
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ProductGenerationError("product_candidate_invalid") from exc
        contract_keys = {
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
        receipt_keys = {
            "schema_version",
            "contract_digest",
            "candidate_content_digest",
            "status",
            "runtime_operational",
            "product_goal_conformance",
            "cases",
            "receipt_digest",
        }
        contract_body = (
            {
                key: value
                for key, value in acceptance_contract.items()
                if key != "canonical_digest"
            }
            if type(acceptance_contract) is dict
            else {}
        )
        receipt_body = (
            {
                key: value
                for key, value in acceptance_receipt.items()
                if key != "receipt_digest"
            }
            if type(acceptance_receipt) is dict
            else {}
        )
        contract_cases = (
            acceptance_contract.get("cases", [])
            if type(acceptance_contract) is dict
            else []
        )
        receipt_cases = (
            acceptance_receipt.get("cases", [])
            if type(acceptance_receipt) is dict
            else []
        )
        if (
            type(acceptance_contract) is not dict
            or set(acceptance_contract) != contract_keys
            or acceptance_contract.get("schema_version")
            != CANDIDATE_ACCEPTANCE_VERSION
            or acceptance_contract.get("plan_digest") != record["plan"]["plan_digest"]
            or acceptance_contract.get("confirmation_digest")
            != execution.get("confirmation_digest")
            or acceptance_contract.get("candidate_content_digest")
            != record["candidate_content_digest"]
            or acceptance_contract.get("canonical_digest")
            != plan_execution_digest(contract_body)
            or type(contract_cases) is not list
            or not 1 <= len(contract_cases) <= MAX_CANDIDATE_ACCEPTANCE_CASES
            or type(acceptance_receipt) is not dict
            or set(acceptance_receipt) != receipt_keys
            or acceptance_receipt.get("schema_version")
            != CANDIDATE_ACCEPTANCE_RECEIPT_VERSION
            or acceptance_receipt.get("contract_digest")
            != acceptance_contract.get("canonical_digest")
            or acceptance_receipt.get("candidate_content_digest")
            != record["candidate_content_digest"]
            or acceptance_receipt.get("runtime_operational") != "passed"
            or acceptance_receipt.get("status") not in {"passed", "failed"}
            or acceptance_receipt.get("product_goal_conformance")
            != acceptance_receipt.get("status")
            or acceptance_receipt.get("receipt_digest")
            != plan_execution_digest(receipt_body)
            or type(receipt_cases) is not list
            or len(receipt_cases) != len(contract_cases)
            or set(record["validation"]) != {"static", "runtime", "acceptance"}
            or record["validation"]["acceptance"] != acceptance_receipt
            or record["status"]
            != (
                "review_ready"
                if acceptance_receipt.get("status") == "passed"
                else "acceptance_failed"
            )
        ):
            raise ProductGenerationError("product_candidate_invalid")
        for contract_case, receipt_case in zip(
            contract_cases, receipt_cases, strict=True
        ):
            if (
                type(contract_case) is not dict
                or set(contract_case)
                != {"case_id", "requirement_ids", "input", "expected_output"}
                or type(contract_case["case_id"]) is not str
                or not contract_case["case_id"]
                or type(contract_case["requirement_ids"]) is not list
                or not contract_case["requirement_ids"]
                or type(receipt_case) is not dict
                or set(receipt_case)
                != {
                    "case_id",
                    "status",
                    "actual_output",
                    "failure_code",
                }
                or receipt_case["case_id"] != contract_case["case_id"]
                or receipt_case["status"] not in {"passed", "failed"}
                or (
                    receipt_case["status"] == "passed"
                    and receipt_case["failure_code"] is not None
                )
                or (
                    receipt_case["status"] == "failed"
                    and receipt_case["failure_code"]
                    not in {
                        "candidate_case_execution_failed",
                        "candidate_output_contract_invalid",
                        "candidate_output_mismatch",
                    }
                )
            ):
                raise ProductGenerationError("product_candidate_invalid")
        expected_acceptance = {
            "contract_digest": acceptance_contract["canonical_digest"],
            "status": acceptance_receipt["status"],
            "runtime_operational": acceptance_receipt["runtime_operational"],
            "product_goal_conformance": acceptance_receipt[
                "product_goal_conformance"
            ],
            "cases": [
                {
                    "case_id": contract_case["case_id"],
                    "input": contract_case["input"],
                    "expected_output": contract_case["expected_output"],
                    "actual_output": receipt_case["actual_output"],
                    "status": receipt_case["status"],
                    "failure_code": receipt_case["failure_code"],
                }
                for contract_case, receipt_case in zip(
                    contract_cases,
                    receipt_cases,
                    strict=True,
                )
            ],
        }
        if record["acceptance"] != expected_acceptance:
            raise ProductGenerationError("product_candidate_invalid")
        return record

    def _read_candidate_record(self, candidate_token: str) -> tuple[Path, dict[str, Any]]:
        if _CANDIDATE_TOKEN.fullmatch(candidate_token) is None:
            raise ProductGenerationError("product_candidate_token_invalid")
        root = self._product_candidate_root()
        self._assert_candidate_path_safe(root)
        if not root.is_dir():
            raise ProductGenerationError("product_candidate_not_found")
        # ponytail: bounded app-state scan; add an index only if candidate volume proves it necessary.
        for candidate_dir in sorted(root.glob("candidate_*")):
            if not candidate_dir.is_dir() or candidate_dir.is_symlink():
                continue
            record = self._read_candidate_record_path(candidate_dir)
            if record["candidate_token"] == candidate_token:
                return candidate_dir, record
        raise ProductGenerationError("product_candidate_not_found")

    def _build_product_candidate(
        self,
        plan_token: str,
        plan_digest: str,
        acceptance_cases: list[dict[str, Any]] | None,
        *,
        acceptance_confirmation: dict[str, Any] | None = None,
        read_only_plan: bool = False,
    ) -> dict[str, Any]:
        if read_only_plan:
            workspace, capsules, product_scope, page_contracts = (
                self._confirmed_candidate_context(plan_token)
            )
        else:
            catalog = self._product_planning_catalog()
            restored = self._product_planner.get(plan_token, catalog)
            if (
                restored.get("ok") is not True
                or type(restored.get("data")) is not dict
            ):
                error = restored.get("error") if type(restored) is dict else None
                code = error.get("code") if type(error) is dict else None
                raise ProductGenerationError(
                    code
                    if type(code) is str
                    else "product_candidate_plan_unavailable"
                )
            workspace = restored["data"]
        plan = workspace.get("plan")
        confirmation = workspace.get("confirmation")
        if (
            workspace.get("status") != "confirmed"
            or type(plan) is not dict
            or type(confirmation) is not dict
            or plan.get("canonical_digest") != plan_digest
        ):
            raise ProductGenerationError("product_candidate_plan_not_confirmed")
        if not read_only_plan:
            capsule_ids = sorted(
                {
                    str(binding["capsule_id"])
                    for section in plan.get("sections", [])
                    for item in section.get("work_items", [])
                    for binding in item.get("capsule_bindings", [])
                    if type(binding) is dict and binding.get("capsule_id")
                }
            )
            capsules, product_scope, page_contracts = (
                self._load_composer_capsules(
                    capsule_ids,
                    read_only=True,
                )
            )
        execution = self._compile_candidate_execution(
            plan,
            confirmation,
            capsules,
            page_contracts,
        )
        selected_by_id = {capsule["capsule_id"]: capsule for capsule in capsules}
        selected = [
            selected_by_id[capsule_id]
            for capsule_id in execution["composer_request"]["capsule_ids"]
        ]
        input_contract, output_contract = self._candidate_acceptance_contracts(
            selected,
            execution,
        )
        if acceptance_confirmation is not None:
            try:
                confirmed_acceptance = (
                    validate_candidate_acceptance_confirmation(
                        plan,
                        confirmation,
                        acceptance_confirmation,
                        input_contract,
                        output_contract,
                    )
                )
            except CandidateAcceptanceError as exc:
                raise ProductGenerationError(exc.code) from exc
            acceptance_cases = [
                {
                    key: case[key]
                    for key in (
                        "requirement_ids",
                        "input",
                        "expected_output",
                    )
                }
                for case in confirmed_acceptance["cases"]
            ]
        if acceptance_cases is None:
            raise ProductGenerationError(
                "candidate_acceptance_confirmation_required"
            )
        expected_composer_version = (
            ADAPTER_V4_FORMAL_PRODUCT_COMPOSER_VERSION
            if any(
                capsule.get("adapter_contract_version")
                == COMPUTATION_ADAPTER_V4
                for capsule in selected
            )
            else ADAPTER_V3_FORMAL_PRODUCT_COMPOSER_VERSION
            if any(
                capsule.get("adapter_contract_version")
                == COMPUTATION_ADAPTER_V3
                for capsule in selected
            )
            else {
                MULTI_COMPUTATION_PLAN_EXECUTION_VERSION: (
                    MULTI_COMPUTATION_FORMAL_PRODUCT_COMPOSER_VERSION
                ),
                PARAMETERIZED_PLAN_EXECUTION_VERSION: (
                    PARAMETERIZED_FORMAL_PRODUCT_COMPOSER_VERSION
                ),
            }.get(execution["schema_version"], FORMAL_PRODUCT_COMPOSER_VERSION)
        )
        candidate_id = "candidate_" + plan_execution_digest(
            {
                "execution_digest": execution["execution_digest"],
                "composer_version": expected_composer_version,
            }
        )[:32]
        root = self._product_candidate_root()
        self._assert_candidate_path_safe(root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            root.chmod(0o700)
        final = root / candidate_id
        if final.exists() or final.is_symlink():
            if final.is_symlink() or not final.is_dir():
                raise ProductGenerationError("product_candidate_directory_unsafe")
            existing = self._read_candidate_record_path(final)
            if existing["execution_digest"] != execution["execution_digest"]:
                raise ProductGenerationError("product_candidate_conflict")
            if existing["schema_version"] != "product_candidate.v2":
                raise ProductGenerationError(
                    "candidate_acceptance_contract_conflict"
                )
            try:
                requested_contract = build_candidate_acceptance(
                    plan,
                    confirmation,
                    acceptance_cases,
                    input_contract,
                    output_contract,
                    existing["candidate_content_digest"],
                )
                stored_contract = _strict_json_bytes(
                    (final / "acceptance_contract.json").read_bytes()
                )
            except (
                CandidateAcceptanceError,
                OSError,
                UnicodeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                code = (
                    exc.code
                    if isinstance(exc, CandidateAcceptanceError)
                    else "candidate_acceptance_contract_conflict"
                )
                raise ProductGenerationError(code) from exc
            if requested_contract != stored_contract:
                raise ProductGenerationError(
                    "candidate_acceptance_contract_conflict"
                )
            self._record_product_experience(
                plan_token,
                "candidate_terminal",
                candidate=existing,
            )
            return self._candidate_projection(existing)
        try:
            composition = compose_capsule_product(
                task=execution["composer_request"]["task"],
                product_id=execution["composer_request"]["product_id"],
                generated_at=execution["composer_request"]["generated_at"],
                capsules=selected,
                candidate_acceptance_port=True,
                parameter_binding=execution.get("parameter_binding"),
                verified_page_contracts=page_contracts,
                verified_connections=execution.get("connections"),
                connection_digest=execution.get("connection_digest"),
            )
        except ValueError as exc:
            code = str(exc)
            raise ProductGenerationError(
                code
                if re.fullmatch(r"[a-z][a-z0-9_]{1,95}", code)
                else "product_candidate_composition_failed"
            ) from exc
        if (
            type(composition) is not dict
            or composition.get("status") != "composed"
            or composition.get("composer_version") != expected_composer_version
            or type(composition.get("files")) is not dict
            or type(composition.get("assets")) is not dict
            or type(composition.get("provenance")) is not dict
        ):
            raise ProductGenerationError("product_candidate_composition_invalid")

        temporary = Path(tempfile.mkdtemp(prefix=f".{candidate_id}-", dir=root))
        try:
            product_root = temporary / "product"
            product_root.mkdir(mode=0o700)
            paths: set[str] = set()
            for relative, content in {
                **composition["files"],
                **composition["assets"],
            }.items():
                logical = _safe_product_relative(relative)
                if logical in paths:
                    raise ProductGenerationError("product_candidate_file_duplicate")
                paths.add(logical)
                _write_product_file(product_root, logical, content)

            units = {
                unit["execution_unit_id"]: unit
                for unit in execution["execution_units"]
            }
            version_units: dict[str, set[str]] = {}
            for unit_id, unit in units.items():
                for capsule in unit["capsules"]:
                    version_units.setdefault(capsule["version_id"], set()).add(unit_id)
            composer_provenance = composition["provenance"]
            if (
                type(composer_provenance.get("file_provenance")) is not dict
                or type(composer_provenance.get("asset_provenance")) is not dict
            ):
                raise ProductGenerationError("product_candidate_provenance_invalid")
            file_versions: dict[str, set[str]] = {
                str(path): {str(version) for version in versions}
                for path, versions in composer_provenance["file_provenance"].items()
                if type(path) is str and type(versions) is list
            }
            for path, receipt in composer_provenance["asset_provenance"].items():
                if type(path) is not str or type(receipt) is not dict:
                    raise ProductGenerationError("product_candidate_provenance_invalid")
                sources = receipt.get("sources")
                if type(sources) is not list:
                    raise ProductGenerationError("product_candidate_provenance_invalid")
                file_versions[path] = {
                    str(source["version_id"])
                    for source in sources
                    if type(source) is dict and type(source.get("version_id")) is str
                }
            known_versions = set(version_units)
            file_versions = {
                path: versions or set(known_versions)
                for path, versions in file_versions.items()
            }
            if set(file_versions) != paths or any(
                not versions or any(version not in version_units for version in versions)
                for versions in file_versions.values()
            ):
                raise ProductGenerationError("product_candidate_provenance_invalid")

            def file_receipt(path: str, versions: set[str]) -> dict[str, Any]:
                unit_ids = sorted(
                    {
                        unit_id
                        for version in versions
                        for unit_id in version_units[version]
                    }
                )
                return {
                    "path": path,
                    "execution_unit_ids": unit_ids,
                    "work_item_ids": sorted(
                        {units[unit_id]["work_item_id"] for unit_id in unit_ids}
                    ),
                    "capsule_version_ids": sorted(versions),
                }

            all_unit_ids = sorted(units)
            all_versions = set(version_units)
            multi_computation_execution = (
                execution["schema_version"]
                == MULTI_COMPUTATION_PLAN_EXECUTION_VERSION
            )
            provenance = {
                "schema_version": (
                    "product_candidate_provenance.v3"
                    if multi_computation_execution
                    else (
                        "product_candidate_provenance.v2"
                        if execution["schema_version"]
                        == PARAMETERIZED_PLAN_EXECUTION_VERSION
                        else "product_candidate_provenance.v1"
                    )
                ),
                "plan_id": execution["plan_id"],
                "plan_version": execution["plan_version"],
                "plan_digest": execution["plan_digest"],
                "execution_digest": execution["execution_digest"],
                "composer_version": str(composition.get("composer_version") or ""),
                "file_provenance": [
                    file_receipt(path, file_versions[path])
                    for path in sorted(file_versions)
                ]
                + [
                    {
                        "path": path,
                        "execution_unit_ids": all_unit_ids,
                        "work_item_ids": sorted(
                            {units[unit_id]["work_item_id"] for unit_id in all_unit_ids}
                        ),
                        "capsule_version_ids": sorted(all_versions),
                    }
                    for path in (
                        "manifest.json",
                        "provenance.json",
                        "quality_gate.json",
                        "runtime_validation.json",
                    )
                ],
                "source_project_write": False,
                "target_project_write": False,
                "model_source_generation": False,
            }
            if execution["schema_version"] == PARAMETERIZED_PLAN_EXECUTION_VERSION:
                provenance["confirmation_digest"] = execution[
                    "confirmation_digest"
                ]
                provenance["parameter_binding"] = execution["parameter_binding"]
            if multi_computation_execution:
                provenance["connections"] = execution["connections"]
                provenance["connection_digest"] = execution[
                    "connection_digest"
                ]
                provenance["terminal_output"] = composer_provenance[
                    "terminal_output"
                ]
            _write_product_file(
                product_root,
                "provenance.json",
                json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            )
            _fsync_product_tree(product_root)
            content_files = []
            for path in sorted(product_root.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                data = path.read_bytes()
                content_files.append(
                    {
                        "path": path.relative_to(product_root).as_posix(),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "size_bytes": len(data),
                    }
                )
            candidate_content_digest = _candidate_content_digest(
                execution["execution_digest"],
                str(composition.get("composer_version") or ""),
                {"path": "index.html", "kind": "static_html"},
                content_files,
            )
            try:
                acceptance_contract = build_candidate_acceptance(
                    plan,
                    confirmation,
                    acceptance_cases,
                    input_contract,
                    output_contract,
                    candidate_content_digest,
                )
            except CandidateAcceptanceError as exc:
                raise ProductGenerationError(exc.code) from exc
            quality = _validate_product_static(product_root)
            runtime = _validate_product_runtime(product_root)
            acceptance_worker = _validate_product_acceptance(
                product_root,
                acceptance_contract,
            )
            try:
                acceptance = evaluate_candidate_acceptance(
                    acceptance_contract,
                    acceptance_worker,
                    input_contract,
                    output_contract,
                )
            except CandidateAcceptanceError as exc:
                raise ProductGenerationError(exc.code) from exc
            _write_product_file(
                product_root,
                "quality_gate.json",
                json.dumps(quality, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            )
            _write_product_file(
                product_root,
                "runtime_validation.json",
                json.dumps(runtime, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            )
            _write_product_file(
                temporary,
                "acceptance_contract.json",
                plan_execution_bytes(acceptance_contract) + b"\n",
            )
            _write_product_file(
                temporary,
                "acceptance_receipt.json",
                plan_execution_bytes(acceptance) + b"\n",
            )
            pre_manifest = []
            for path in sorted(product_root.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                data = path.read_bytes()
                pre_manifest.append(
                    {
                        "path": path.relative_to(product_root).as_posix(),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "size_bytes": len(data),
                    }
                )
            manifest = {
                "schema_version": "reweave_candidate_manifest.v1",
                "created_at": confirmation["confirmed_at"],
                "plan": {
                    "plan_id": plan["plan_id"],
                    "plan_version": plan["plan_version"],
                    "plan_digest": plan["canonical_digest"],
                },
                "execution_digest": execution["execution_digest"],
                "composer_version": str(composition.get("composer_version") or ""),
                "product_usage_scope": product_scope,
                "entry": {"path": "index.html", "kind": "static_html"},
                "capsules": execution["capsules"],
                "connections": composition.get("composition_manifest", {}).get(
                    "connections", []
                ),
                "files": pre_manifest,
                "permissions": {
                    "source_project_write": False,
                    "target_project_write": False,
                    "product_store_write": False,
                    "product_usage_write": False,
                },
            }
            if multi_computation_execution:
                manifest["connection_digest"] = execution[
                    "connection_digest"
                ]
                manifest["terminal_output"] = provenance["terminal_output"]
            _write_product_file(
                product_root,
                "manifest.json",
                plan_execution_bytes(manifest) + b"\n",
            )
            with self._capsule_store.read_connection() as connection:
                self._assert_generation_capsules_current(connection, selected)

            files: list[dict[str, Any]] = []
            changes: list[dict[str, Any]] = []
            for path in sorted(product_root.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                data = path.read_bytes()
                logical = path.relative_to(product_root).as_posix()
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    text = None
                files.append(
                    {
                        "path": logical,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "size_bytes": len(data),
                        "text": text is not None,
                    }
                )
                changes.append(
                    {
                        "path": logical,
                        "operation": "added",
                        "text_diff_sha256": (
                            hashlib.sha256(
                                "".join(
                                    difflib.unified_diff(
                                        [],
                                        text.splitlines(keepends=True),
                                        fromfile="/dev/null",
                                        tofile=logical,
                                    )
                                ).encode("utf-8")
                            ).hexdigest()
                            if text is not None
                            else None
                        ),
                    }
                )
            acceptance_projection = {
                "contract_digest": acceptance_contract["canonical_digest"],
                "status": acceptance["status"],
                "runtime_operational": acceptance["runtime_operational"],
                "product_goal_conformance": acceptance[
                    "product_goal_conformance"
                ],
                "cases": [
                    {
                        "case_id": contract_case["case_id"],
                        "input": contract_case["input"],
                        "expected_output": contract_case["expected_output"],
                        "actual_output": receipt_case["actual_output"],
                        "status": receipt_case["status"],
                        "failure_code": receipt_case["failure_code"],
                    }
                    for contract_case, receipt_case in zip(
                        acceptance_contract["cases"],
                        acceptance["cases"],
                        strict=True,
                    )
                ],
            }
            core = {
                "schema_version": "product_candidate.v2",
                "status": (
                    "review_ready"
                    if acceptance["status"] == "passed"
                    else "acceptance_failed"
                ),
                "candidate_id": candidate_id,
                "created_at": confirmation["confirmed_at"],
                "plan": {
                    "plan_id": plan["plan_id"],
                    "plan_version": plan["plan_version"],
                    "plan_digest": plan["canonical_digest"],
                },
                "execution_digest": execution["execution_digest"],
                "candidate_content_digest": candidate_content_digest,
                "composer_version": str(composition.get("composer_version") or ""),
                "entry": {"path": "index.html", "kind": "static_html"},
                "acceptance": acceptance_projection,
                "files": files,
                "file_changes": changes,
                "provenance": provenance,
                "validation": {
                    "static": quality,
                    "runtime": runtime,
                    "acceptance": acceptance,
                },
                "permissions": {
                    "source_project_write": False,
                    "target_project_write": False,
                    "product_store_write": False,
                    "product_usage_write": False,
                },
            }
            candidate_token = "candidate_token_" + uuid.uuid4().hex + uuid.uuid4().hex[:16]
            record = {
                **core,
                "candidate_token": candidate_token,
                "candidate_digest": plan_execution_digest(core),
            }
            record["record_digest"] = plan_execution_digest(record)
            _write_product_file(
                temporary,
                "execution_plan.json",
                plan_execution_bytes(execution) + b"\n",
            )
            _write_product_file(
                temporary,
                "candidate.json",
                plan_execution_bytes(record) + b"\n",
            )
            _fsync_product_tree(temporary)
            if final.exists() or final.is_symlink():
                raise ProductGenerationError("product_candidate_conflict")
            os.replace(temporary, final)
            if os.name == "posix":
                descriptor = os.open(root, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            persisted = self._read_candidate_record_path(final)
            self._record_product_experience(
                plan_token,
                "candidate_terminal",
                candidate=persisted,
            )
            return self._candidate_projection(persisted)
        except (OSError, sqlite3.Error) as exc:
            raise ProductGenerationError("product_candidate_write_failed") from exc
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)

    def start_product_candidate(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if (
                set(request)
                != {"plan_token", "plan_digest", "acceptance_cases"}
                or type(request["plan_token"]) is not str
                or type(request["plan_digest"]) is not str
                or _MANIFEST_DIGEST.fullmatch(request["plan_digest"]) is None
                or type(request["acceptance_cases"]) is not list
                or not 1
                <= len(request["acceptance_cases"])
                <= MAX_CANDIDATE_ACCEPTANCE_CASES
                or any(
                    type(item) is not dict
                    or set(item)
                    != {"requirement_ids", "input", "expected_output"}
                    for item in request["acceptance_cases"]
                )
            ):
                return self._error("product_candidate_request_invalid")
            return self._submit_management_task(
                "product_candidate_start",
                lambda _cancel: self._ok(
                    self._build_product_candidate(
                        request["plan_token"],
                        request["plan_digest"],
                        request["acceptance_cases"],
                    )
                ),
                read_only_candidate=True,
            )
        except ValueError as exc:
            return self._exception_error(exc, "product_candidate_request_invalid")

    def _build_confirmed_product_candidate(
        self,
        plan_token: str,
        plan_digest: str,
        acceptance_confirmation_digest: str,
    ) -> dict[str, Any]:
        restored = self._product_planner.get_candidate_acceptance_confirmation(
            plan_token
        )
        if restored.get("ok") is not True:
            error = restored.get("error") if type(restored) is dict else None
            code = error.get("code") if type(error) is dict else None
            raise ProductGenerationError(
                code
                if type(code) is str
                else "candidate_acceptance_confirmation_required"
            )
        record = restored["data"]["acceptance_confirmation"]
        if record.get("canonical_digest") != acceptance_confirmation_digest:
            raise ProductGenerationError(
                "candidate_acceptance_confirmation_stale"
            )
        return self._build_product_candidate(
            plan_token,
            plan_digest,
            None,
            acceptance_confirmation=record,
            read_only_plan=True,
        )

    def start_confirmed_product_candidate(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if (
                set(request)
                != {
                    "plan_token",
                    "plan_digest",
                    "acceptance_confirmation_digest",
                }
                or type(request["plan_token"]) is not str
                or type(request["plan_digest"]) is not str
                or type(request["acceptance_confirmation_digest"]) is not str
                or _MANIFEST_DIGEST.fullmatch(request["plan_digest"]) is None
                or _MANIFEST_DIGEST.fullmatch(
                    request["acceptance_confirmation_digest"]
                )
                is None
            ):
                return self._error("product_candidate_request_invalid")
            return self._submit_management_task(
                "product_candidate_start_confirmed",
                lambda _cancel: self._ok(
                    self._build_confirmed_product_candidate(
                        request["plan_token"],
                        request["plan_digest"],
                        request["acceptance_confirmation_digest"],
                    )
                ),
                read_only_candidate=True,
            )
        except ValueError as exc:
            return self._exception_error(exc, "product_candidate_request_invalid")

    def get_product_candidate_run(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if set(request) != {"run_id"} or type(request["run_id"]) is not str:
                return self._error("product_candidate_run_id_required")
            with self._management_lock:
                task = self._management_tasks.get(request["run_id"])
                if task is None or not str(task["kind"]).startswith("product_candidate_"):
                    return self._error("product_candidate_run_not_found")
                return self._ok(self._task_view(task))
        except ValueError as exc:
            return self._exception_error(exc, "product_candidate_run_invalid")

    def get_product_candidate(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if (
                set(request) != {"candidate_token"}
                or type(request["candidate_token"]) is not str
            ):
                return self._error("product_candidate_token_invalid")
            _path, record = self._read_candidate_record(request["candidate_token"])
            return self._ok(self._candidate_projection(record))
        except (OSError, ProductGenerationError, ValueError) as exc:
            return self._exception_error(exc, "product_candidate_read_failed")

    def _validated_export_candidate(
        self,
        plan_token: str,
        candidate_token: str,
    ) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        candidate_dir, record = self._read_candidate_record(candidate_token)
        if (
            record.get("schema_version") != "product_candidate.v2"
            or record.get("status") != "review_ready"
            or record.get("acceptance", {}).get("status") != "passed"
            or record.get("acceptance", {}).get("runtime_operational")
            != "passed"
            or record.get("acceptance", {}).get("product_goal_conformance")
            != "passed"
        ):
            raise ProductGenerationError(
                "product_candidate_export_not_ready"
            )
        try:
            workspace, capsules, _scope, page_contracts = (
                self._confirmed_candidate_context(plan_token)
            )
            acceptance_confirmation = (
                self._validated_candidate_acceptance_confirmation(
                    plan_token,
                    workspace,
                    capsules,
                    page_contracts,
                )
            )
        except ProductGenerationError as exc:
            raise ProductGenerationError(
                "product_candidate_export_stale"
            ) from exc
        plan = workspace["plan"]
        if record["plan"] != {
            "plan_id": plan["plan_id"],
            "plan_version": plan["plan_version"],
            "plan_digest": plan["canonical_digest"],
        }:
            raise ProductGenerationError("product_candidate_export_stale")
        try:
            expected_execution = self._compile_candidate_execution(
                plan,
                workspace["confirmation"],
                capsules,
                page_contracts,
            )
            stored_execution = _strict_json_bytes(
                (candidate_dir / "execution_plan.json").read_bytes()
            )
        except PlanExecutionError as exc:
            raise ProductGenerationError(
                "product_candidate_export_stale"
            ) from exc
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ProductGenerationError("product_candidate_invalid") from exc
        if expected_execution != stored_execution:
            raise ProductGenerationError("product_candidate_export_stale")
        input_contract, output_contract = self._candidate_acceptance_contracts(
            capsules,
            expected_execution,
        )
        cases = [
            {
                key: case[key]
                for key in ("requirement_ids", "input", "expected_output")
            }
            for case in acceptance_confirmation["cases"]
        ]
        try:
            expected_contract = build_candidate_acceptance(
                plan,
                workspace["confirmation"],
                cases,
                input_contract,
                output_contract,
                record["candidate_content_digest"],
            )
            stored_contract = _strict_json_bytes(
                (candidate_dir / "acceptance_contract.json").read_bytes()
            )
        except CandidateAcceptanceError as exc:
            raise ProductGenerationError(
                "product_candidate_export_stale"
            ) from exc
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ProductGenerationError("product_candidate_invalid") from exc
        if expected_contract != stored_contract:
            raise ProductGenerationError("product_candidate_export_stale")
        return candidate_dir, record, workspace

    @_serialized_management
    def export_product_candidate(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if (
                set(request)
                != {"plan_token", "candidate_token", "destination_parent"}
                or type(request["plan_token"]) is not str
                or not request["plan_token"]
                or type(request["candidate_token"]) is not str
                or type(request["destination_parent"]) is not str
            ):
                return self._error("product_candidate_export_request_invalid")
            if os.name != "posix":
                return self._error(
                    "product_candidate_export_platform_unsupported"
                )
            candidate_dir, record, workspace = (
                self._validated_export_candidate(
                    request["plan_token"],
                    request["candidate_token"],
                )
            )
            parent = _safe_export_parent(request["destination_parent"])
            _validated_export_paths(record["files"])
            directory_name = _safe_export_directory_name(
                workspace["plan"]["product_name"],
                record["candidate_content_digest"],
            )

            def result(status: str) -> dict[str, Any]:
                self._record_product_experience(
                    request["plan_token"],
                    "export_terminal",
                    candidate=record,
                    export_status=status,
                )
                return self._ok(
                    {
                        "schema_version": "product_candidate_export.v1",
                        "status": status,
                        "directory_name": directory_name,
                        "file_count": len(record["files"]),
                    }
                )

            source = candidate_dir / "product"
            self._assert_candidate_path_safe(source)
            file_data = [
                (item["path"], _read_export_file(source, item))
                for item in record["files"]
            ]

            parent_descriptor = _open_export_directory(
                parent,
                self._capsule_store.path.parent,
            )
            temporary_name = f".reweave-export-{uuid.uuid4().hex}"
            temporary_identity: tuple[int, int] | None = None
            published = False

            def existing_target_descriptor() -> int | None:
                matches = [
                    entry
                    for entry in os.scandir(parent_descriptor)
                    if unicodedata.normalize("NFC", entry.name).casefold()
                    == directory_name.casefold()
                ]
                if not matches:
                    return None
                if len(matches) != 1 or matches[0].name != directory_name:
                    raise ProductGenerationError(
                        "product_candidate_export_conflict"
                    )
                details = matches[0].stat(follow_symlinks=False)
                if stat.S_ISLNK(details.st_mode):
                    raise ProductGenerationError(
                        "product_candidate_export_destination_unsafe"
                    )
                if not stat.S_ISDIR(details.st_mode):
                    raise ProductGenerationError(
                        "product_candidate_export_conflict"
                    )
                return _open_export_directory_at(
                    parent_descriptor,
                    directory_name,
                )

            try:
                existing_descriptor = existing_target_descriptor()
                if existing_descriptor is not None:
                    try:
                        _verify_export_tree(
                            existing_descriptor,
                            record["files"],
                            error_code="product_candidate_export_conflict",
                        )
                    finally:
                        os.close(existing_descriptor)
                    return result("already_saved")
                os.mkdir(
                    temporary_name,
                    0o700,
                    dir_fd=parent_descriptor,
                )
                temporary_details = os.stat(
                    temporary_name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                temporary_identity = (
                    temporary_details.st_dev,
                    temporary_details.st_ino,
                )
                temporary_descriptor = _open_export_directory_at(
                    parent_descriptor,
                    temporary_name,
                )
                if (
                    os.fstat(temporary_descriptor).st_dev,
                    os.fstat(temporary_descriptor).st_ino,
                ) != temporary_identity:
                    os.close(temporary_descriptor)
                    raise ProductGenerationError(
                        "product_candidate_export_destination_unsafe"
                    )
                try:
                    os.fchmod(temporary_descriptor, 0o700)
                    for logical, data in file_data:
                        _write_export_file(
                            temporary_descriptor,
                            logical,
                            data,
                        )
                    _verify_export_tree(
                        temporary_descriptor,
                        record["files"],
                        error_code="product_candidate_export_failed",
                    )
                    _rename_export_no_replace(
                        parent_descriptor,
                        temporary_name,
                        directory_name,
                    )
                    published = True
                    os.fsync(parent_descriptor)
                    _verify_export_tree(
                        temporary_descriptor,
                        record["files"],
                        error_code="product_candidate_export_failed",
                    )
                finally:
                    os.close(temporary_descriptor)
                return result("saved")
            finally:
                if not published and temporary_identity is not None:
                    _remove_export_tree_at(
                        parent_descriptor,
                        temporary_name,
                        temporary_identity,
                    )
                os.close(parent_descriptor)
        except (
            CapsuleStoreError,
            OSError,
            ProductGenerationError,
            ValueError,
        ) as exc:
            return self._exception_error(
                exc,
                "product_candidate_export_failed",
            )

    def read_product_candidate_file(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if (
                set(request) != {"candidate_token", "relative_path"}
                or type(request["candidate_token"]) is not str
                or type(request["relative_path"]) is not str
            ):
                return self._error("product_candidate_file_request_invalid")
            candidate_dir, record = self._read_candidate_record(
                request["candidate_token"]
            )
            logical = _safe_product_relative(request["relative_path"])
            metadata = next(
                (item for item in record["files"] if item["path"] == logical),
                None,
            )
            if metadata is None:
                raise ProductGenerationError("product_candidate_file_not_found")
            path = candidate_dir / "product" / PurePosixPath(logical)
            if path.is_symlink() or not path.is_file():
                raise ProductGenerationError("product_candidate_file_not_found")
            data = path.read_bytes()
            if len(data) > 1024 * 1024:
                raise ProductGenerationError("product_candidate_file_too_large")
            if metadata["text"]:
                content = data.decode("utf-8")
                diff = "".join(
                    difflib.unified_diff(
                        [],
                        content.splitlines(keepends=True),
                        fromfile="/dev/null",
                        tofile=logical,
                    )
                )
                encoding = "utf-8"
            else:
                content = base64.b64encode(data).decode("ascii")
                diff = None
                encoding = "base64"
            return self._ok(
                {
                    "candidate_token": record["candidate_token"],
                    "candidate_digest": record["candidate_digest"],
                    "path": logical,
                    "sha256": metadata["sha256"],
                    "size_bytes": metadata["size_bytes"],
                    "encoding": encoding,
                    "content": content,
                    "text_diff": diff,
                }
            )
        except (OSError, UnicodeError, ProductGenerationError, ValueError) as exc:
            return self._exception_error(exc, "product_candidate_file_read_failed")

    @_serialized_management
    def list_review_items(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            self._ensure_capsule_management()
            request = self._payload(payload)
            status = str(request.get("status") or "").strip()
            query = "SELECT * FROM review_items"
            params: tuple[Any, ...] = ()
            if status:
                query += " WHERE candidate_status = ?"
                params = (status,)
            else:
                query += (
                    " WHERE candidate_status IN "
                    "('extracted', 'waiting_user', 'waiting_model', "
                    "'waiting_validation', 'review_required') "
                    "OR (candidate_status = 'duplicate' AND decision IS NULL)"
                )
            query += " ORDER BY created_at DESC, review_id"
            with self._capsule_store.read_connection() as connection:
                rows = connection.execute(query, params).fetchall()
            items = []
            for row in rows:
                value = dict(row)
                item = {
                    key: value.get(key)
                    for key in (
                        "review_id",
                        "run_id",
                        "project_id",
                        "candidate_id",
                        "candidate_status",
                        "source_relpath",
                        "candidate_canonical_hash",
                        "sensitivity_decision",
                        "brand_decision",
                        "asset_decision",
                        "enum_decision",
                        "enum_decision_binding_sha256",
                        "decision",
                        "retained_version_id",
                        "created_at",
                        "updated_at",
                    )
                }
                for source, target in (
                    ("sanitized_candidate_json", "candidate"),
                    ("redaction_summary_json", "redaction"),
                    ("supervision_result_json", "supervision"),
                    ("equivalence_comparison_json", "comparison"),
                ):
                    raw = value.get(source)
                    try:
                        item[target] = json.loads(raw) if raw else None
                    except (TypeError, json.JSONDecodeError):
                        item[target] = None
                item["allowed_decisions"] = self._allowed_review_decisions(item)
                candidate = item.get("candidate") or {}
                item["adapter_contract_version_expired"] = (
                    _retired_v1_adapter_candidate(candidate)
                )
                item["resume_contract"] = candidate.get("resume_contract")
                if item["resume_contract"] in {
                    CAPTURE_RESUME_V1,
                    CAPTURE_RESUME_V2,
                    CAPTURE_RESUME_V3,
                }:
                    redaction = item.get("redaction") or {}
                    item["capture_summary"] = {
                        key: redaction.get(key)
                        for key in (
                            "ambiguous_count",
                            "brand_count",
                            "enumeration_parameter_count",
                            "enumeration_value_count",
                        )
                    }
                if (
                    not status
                    and not item["allowed_decisions"]
                    and not (
                        item.get("resume_contract")
                        in {
                            CAPTURE_RESUME_V1,
                            CAPTURE_RESUME_V2,
                            CAPTURE_RESUME_V3,
                        }
                        and item.get("candidate_status") == "waiting_user"
                    )
                    and not item["adapter_contract_version_expired"]
                ):
                    continue
                items.append(item)
            return self._ok({"items": items})
        except (CapsuleStoreError, OSError, ValueError, sqlite3.Error) as exc:
            return self._exception_error(exc, "list_review_items_failed")

    @_serialized_management
    def admit_frozen_review(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Controlled internal entry for a previously frozen Stage 3 review."""

        try:
            self._ensure_capsule_management()
            request = self._payload(payload)
            if set(request) != {
                "source_database_path",
                "source_directory_path",
                "source_database_sha256",
                "review_id",
                "expected_warehouse_revision",
                "plan_token",
                "plan_digest",
                "projection_digest",
                "authorize_decision_digest",
                "source_proposal_authorization_digest",
            } or any(
                type(request.get(key)) is not str or not request[key]
                for key in (
                    "source_database_path",
                    "source_directory_path",
                    "source_database_sha256",
                    "review_id",
                    "plan_token",
                    "plan_digest",
                    "projection_digest",
                    "authorize_decision_digest",
                    "source_proposal_authorization_digest",
                )
            ) or type(request["expected_warehouse_revision"]) is not int:
                return self._error("frozen_review_admission_invalid")
            catalog = self._product_planner._catalog(
                self._product_planning_catalog()
            )
            workspace = self._product_planner._workspace_by_token(
                request["plan_token"]
            )
            plan = workspace.get("plan")
            projection = (
                self._product_planner._read_capability_gap_projection(
                    workspace
                )
                if type(plan) is dict
                else None
            )
            expected_projection, projection_status = (
                self._product_planner._capability_gap_projection_for_workspace(
                    workspace,
                    plan,
                    catalog,
                )
                if type(plan) is dict
                else (None, "capability_gap_projection_missing")
            )
            authorized_catalog_digest = canonical_json_digest(
                {
                    "warehouse_revision": projection.get(
                        "warehouse_revision"
                    )
                    if projection is not None
                    else -1,
                    "capsules": catalog["capsules"],
                }
            )
            # Admission bumps warehouse revision but cannot change formal capability facts.
            target_catalog_digest = canonical_json_digest(
                {"capsules": catalog["capsules"]}
            )
            initial_target = bool(
                projection is not None
                and catalog["warehouse_revision"]
                == projection.get("warehouse_revision")
            )
            repeated_target = bool(
                projection is not None
                and catalog["warehouse_revision"]
                == projection.get("warehouse_revision", -2) + 1
            )
            if (
                workspace.get("status") != "plan_review"
                or type(plan) is not dict
                or plan.get("canonical_digest") != request["plan_digest"]
                or projection is None
                or not (initial_target or repeated_target)
                or (
                    initial_target
                    and (
                        projection_status != "available"
                        or expected_projection != projection
                    )
                )
                or projection.get("projection_digest")
                != request["projection_digest"]
                or projection.get("catalog_digest")
                != authorized_catalog_digest
            ):
                raise ProductPlanningError(
                    "frozen_review_admission_authorization_stale"
                )
            decisions = self._product_planner._capability_gap_decisions(
                workspace,
                projection,
            )
            decision = decisions[-1] if decisions else None
            if (
                decision is None
                or decision.get("decision") != "authorize"
                or decision.get("canonical_digest")
                != request["authorize_decision_digest"]
            ):
                raise ProductPlanningError(
                    "frozen_review_admission_authorization_invalid"
                )
            authorization = (
                self._product_planner
                ._read_capability_source_proposal_authorization(
                    workspace,
                    projection,
                    decision,
                )
            )
            if (
                authorization is None
                or authorization.get("authorization_digest")
                != request["source_proposal_authorization_digest"]
                or authorization.get("plan_digest")
                != request["plan_digest"]
                or authorization.get("projection_digest")
                != request["projection_digest"]
                or authorization.get("authorize_decision_digest")
                != request["authorize_decision_digest"]
                or authorization.get("catalog_digest")
                != authorized_catalog_digest
            ):
                raise ProductPlanningError(
                    "frozen_review_admission_authorization_invalid"
                )
            authorization_binding = {
                "plan_digest": authorization["plan_digest"],
                "gap_id": authorization["gap_id"],
                "projection_digest": authorization["projection_digest"],
                "authorize_decision_digest": authorization[
                    "authorize_decision_digest"
                ],
                "source_proposal_authorization_digest": authorization[
                    "authorization_digest"
                ],
                "capability_key": authorization["capability_key"],
                "adapter_contract_version": authorization[
                    "adapter_contract_version"
                ],
                "input_contract": authorization["input_contract"],
                "output_contract": authorization["output_contract"],
                "error_contract": authorization["error_contract"],
                "authorization_warehouse_revision": authorization[
                    "warehouse_revision"
                ],
                "authorization_catalog_digest": authorization[
                    "catalog_digest"
                ],
                "target_catalog_digest": target_catalog_digest,
            }
            result = self._capsule_stage3.admit_frozen_review(
                Path(str(request["source_database_path"])),
                Path(str(request["source_directory_path"])),
                str(request["review_id"]),
                expected_source_sha256=str(request["source_database_sha256"]),
                expected_warehouse_revision=request["expected_warehouse_revision"],
                authorization_binding=authorization_binding,
            )
            return self._ok(result)
        except (
            CapsuleStoreError,
            ProductPlanningError,
            Stage3Error,
            OSError,
            ValueError,
            sqlite3.Error,
        ) as exc:
            return self._exception_error(exc, "frozen_review_admission_failed")

    def admit_frozen_ui_review_batch(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Controlled internal entry for one frozen compatible UI pair."""

        try:
            self._ensure_capsule_management()
            request = self._payload(payload)
            if (
                set(request)
                != {
                    "source_database_path",
                    "source_directory_path",
                    "source_database_sha256",
                    "expected_warehouse_revision",
                    "authorization",
                }
                or any(
                    type(request.get(key)) is not str or not request[key]
                    for key in (
                        "source_database_path",
                        "source_directory_path",
                        "source_database_sha256",
                    )
                )
                or type(request["expected_warehouse_revision"]) is not int
                or type(request["authorization"]) is not dict
                or request["authorization"].get("schema")
                != FROZEN_UI_REVIEW_ADMISSION_AUTHORIZATION_VERSION
            ):
                return self._error("frozen_ui_review_admission_invalid")
            catalog = self._product_planner._catalog(
                self._product_planning_catalog()
            )
            target_catalog_digest = canonical_json_digest(
                {"capsules": catalog["capsules"]}
            )
            authorization = request["authorization"]
            if (
                authorization.get("target_warehouse_revision")
                != request["expected_warehouse_revision"]
                or authorization.get("target_catalog_digest")
                != target_catalog_digest
            ):
                return self._error("frozen_ui_review_admission_target_stale")
            result = self._capsule_stage3.admit_frozen_ui_review_batch(
                Path(str(request["source_database_path"])),
                Path(str(request["source_directory_path"])),
                expected_source_sha256=str(
                    request["source_database_sha256"]
                ),
                expected_warehouse_revision=request[
                    "expected_warehouse_revision"
                ],
                authorization_binding=authorization,
            )
            return self._ok(result)
        except (
            CapsuleStoreError,
            ProductPlanningError,
            Stage3Error,
            OSError,
            ValueError,
            sqlite3.Error,
        ) as exc:
            return self._exception_error(
                exc,
                "frozen_ui_review_admission_failed",
            )

    @_serialized_management
    def decide_review_item(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            self._ensure_capsule_management()
            request = self._payload(payload)
            review_id = str(request.get("review_id") or "").strip()
            decision = str(request.get("decision") or "").strip()
            if not review_id or not decision:
                return self._error("review_decision_required")
            listed = self.list_review_items({})
            if listed.get("ok") is not True:
                return listed
            item = next(
                (
                    current
                    for current in listed["data"]["items"]
                    if current.get("review_id") == review_id
                ),
                None,
            )
            if item is None:
                return self._error("review_item_not_found")
            if item.get("adapter_contract_version_expired") is True:
                return self._error("adapter_contract_version_expired")
            if decision not in item["allowed_decisions"]:
                return self._error("review_decision_not_allowed")
            candidate = item.get("candidate") or {}
            frozen_admission = candidate.get("frozen_review_admission")
            product_source_review = (
                type(frozen_admission) is dict
                and frozen_admission.get("schema")
                == FROZEN_REVIEW_ADMISSION_VERSION
            )
            frozen_ui_admission = candidate.get(
                "frozen_ui_review_admission"
            )
            ui_source_review = (
                type(frozen_ui_admission) is dict
                and frozen_ui_admission.get("schema")
                == FROZEN_UI_REVIEW_ADMISSION_VERSION
            )
            if product_source_review or ui_source_review:
                if decision not in {"publish_general", "reject"}:
                    return self._error("review_decision_not_allowed")
                if decision == "publish_general":
                    capability_key = str(
                        request.get("capability_key") or ""
                    ).strip()
                    role_key = str(request.get("role_key") or "").strip()
                    variant_key = str(
                        request.get("variant_key") or "default"
                    ).strip()
                    display_name = str(
                        request.get("display_name") or ""
                    ).strip()
                    with self._capsule_store.read_connection() as connection:
                        group = connection.execute(
                            "SELECT display_name FROM capability_groups "
                            "WHERE capability_key = ?",
                            (capability_key,),
                        ).fetchone()
                    authorized_capability_key = (
                        frozen_ui_admission.get(
                            "authorized_capability_key"
                        )
                        if ui_source_review
                        else frozen_admission.get(
                            "authorized_capability_key"
                        )
                    )
                    authorized_display_name = (
                        frozen_ui_admission.get("authorized_display_name")
                        if ui_source_review
                        else (
                            str(group["display_name"])
                            if group is not None
                            else None
                        )
                    )
                    if (
                        capability_key != authorized_capability_key
                        or display_name != authorized_display_name
                        or (
                            group is not None
                            and display_name != str(group["display_name"])
                        )
                        or (group is None and not ui_source_review)
                        or re.fullmatch(
                            r"[a-z][a-z0-9_]{0,63}",
                            role_key,
                        )
                        is None
                        or re.fullmatch(
                            r"[a-z][a-z0-9_]{0,63}",
                            variant_key,
                        )
                        is None
                    ):
                        return self._error(
                            "frozen_review_publication_identity_invalid"
                        )
            ephemeral_capture = (
                candidate.get("candidate_origin")
                == "deterministic_computation_adapter"
                and (
                    (
                        candidate.get("adapter_contract_version")
                        == COMPUTATION_ADAPTER_V2
                        and item.get("resume_contract") == CAPTURE_RESUME_V1
                    )
                    or (
                        candidate.get("adapter_contract_version")
                        == COMPUTATION_ADAPTER_V3
                        and item.get("resume_contract") == CAPTURE_RESUME_V2
                    )
                    or (
                        candidate.get("adapter_contract_version")
                        == COMPUTATION_ADAPTER_V4
                        and item.get("resume_contract") == CAPTURE_RESUME_V3
                    )
                )
            )
            if ephemeral_capture and decision in {
                "confirm_fictional_fixture",
                "confirm_real_record_reject",
                "retain_brand_limited",
                "confirm_selected_string_enumeration",
            }:
                binding = str(
                    (item.get("redaction") or {}).get(
                        "enum_decision_binding_sha256"
                    )
                    or ""
                )
                if not re.fullmatch(r"[0-9a-f]{64}", binding):
                    return self._error("capture_decision_rebuild_required")
                kwargs: dict[str, str] = {}
                if decision in {
                    "confirm_fictional_fixture",
                    "confirm_real_record_reject",
                }:
                    kwargs["sensitivity_decision"] = decision
                elif decision == "retain_brand_limited":
                    kwargs["brand_decision"] = decision
                else:
                    kwargs["enum_decision"] = decision
                recorded = self._capsule_stage3.record_ephemeral_capture_decisions(
                    review_id,
                    binding,
                    **kwargs,
                )
                return self._ok(
                    {
                        **recorded,
                        "capture_resubmission_required": True,
                        "resume_contract": item.get("resume_contract"),
                    }
                )
            if decision in {
                "confirm_fictional_fixture",
                "confirm_safe_redaction",
                "confirm_real_record_reject",
            }:
                result = self._capsule_intake.record_review_decisions(
                    review_id, sensitivity_decision=decision
                )
            elif decision in {"remove_brand", "retain_brand_limited"}:
                result = self._capsule_intake.record_review_decisions(
                    review_id, brand_decision=decision
                )
            elif decision == "confirm_assets_contain_no_real_records":
                result = self._capsule_intake.record_review_decisions(
                    review_id, asset_decision=decision
                )
            elif decision == "process_candidate":
                return self._submit_management_task(
                    "process_review",
                    lambda cancel: self._process_review_retry(review_id, cancel),
                    cancellable=True,
                )
            elif decision == "reject":
                result = self._capsule_stage3.reject_review(review_id)
            else:
                result = self._capsule_stage3.publish_review(
                    review_id,
                    decision=decision,
                    capability_key=request.get("capability_key"),
                    role_key=request.get("role_key"),
                    variant_key=str(request.get("variant_key") or "default"),
                    display_name=request.get("display_name"),
                    target_capsule_id=request.get("target_capsule_id"),
                    retained_version_id=request.get("retained_version_id"),
                )
            return self._ok(result)
        except (CapsuleStoreError, IntakeError, Stage3Error, OSError, ValueError) as exc:
            return self._exception_error(exc, "decide_review_item_failed")

    def _process_review_retry(
        self, review_id: str, cancel: threading.Event
    ) -> dict[str, Any]:
        with self._capsule_store.read_connection() as connection:
            row = connection.execute(
                "SELECT candidate_status, project_id FROM review_items WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        if row is None:
            raise Stage3Error("review_item_not_found")
        if row["candidate_status"] == "extracted":
            return self._capsule_stage3.process_review(review_id)
        if row["candidate_status"] not in {
            "waiting_user",
            "waiting_model",
            "waiting_validation",
        } or row["project_id"] is None:
            raise Stage3Error("review_item_not_processable")
        project_id = str(row["project_id"])
        with self._capsule_store.transaction() as connection:
            changed = connection.execute(
                "UPDATE projects SET last_snapshot_hash = NULL, updated_at = ? "
                "WHERE project_id = ?",
                (_now(), project_id),
            ).rowcount
            if changed != 1:
                raise Stage3Error("review_project_not_found")
            self._capsule_store.bump_revision(connection)
        return self._refresh_project(project_id, cancel)

    @_serialized_management
    def list_capability_groups(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            self._ensure_capsule_management()
            self._payload(payload)
            with self._capsule_store.read_connection() as connection:
                groups = []
                for group in connection.execute(
                    "SELECT * FROM capability_groups ORDER BY display_name, capability_key"
                ):
                    capsules = []
                    for capsule in connection.execute(
                        "SELECT c.*, cv.version_number, cv.canonical_hash, cv.usage_scope_json "
                        "FROM capsules c LEFT JOIN capsule_versions cv "
                        "ON cv.version_id = c.current_version_id "
                        "WHERE c.capability_key = ? ORDER BY c.role_key, c.variant_key",
                        (group["capability_key"],),
                    ):
                        item = dict(capsule)
                        try:
                            item["usage_scope"] = json.loads(item.pop("usage_scope_json") or "null")
                        except json.JSONDecodeError:
                            item["usage_scope"] = None
                        capsules.append(item)
                    groups.append({**dict(group), "capsules": capsules})
            return self._ok({"groups": groups})
        except (CapsuleStoreError, OSError, ValueError) as exc:
            return self._exception_error(exc, "list_capability_groups_failed")

    @_serialized_management
    def rename_capability_group(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            self._ensure_capsule_management()
            request = self._payload(payload)
            capability_key = str(request.get("capability_key") or "").strip()
            raw_name = request.get("display_name")
            if re.fullmatch(r"[a-z_][a-z0-9_]*", capability_key) is None:
                return self._error("capability_key_invalid")
            if type(raw_name) is not str:
                return self._error("capability_display_name_invalid")
            display_name = raw_name.strip()
            if not display_name or len(display_name) > 200:
                return self._error("capability_display_name_invalid")
            now = _now()
            with self._capsule_store.transaction() as connection:
                updated = connection.execute(
                    "UPDATE capability_groups SET display_name = ?, updated_at = ? "
                    "WHERE capability_key = ?",
                    (display_name, now, capability_key),
                )
                if updated.rowcount != 1:
                    return self._error("capability_group_not_found")
                self._capsule_store.bump_revision(connection)
            return self._ok(
                {
                    "capability_key": capability_key,
                    "display_name": display_name,
                }
            )
        except (CapsuleStoreError, OSError, ValueError, sqlite3.Error) as exc:
            return self._exception_error(exc, "rename_capability_group_failed")

    @_serialized_management
    def get_capsule_detail(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            self._ensure_capsule_management()
            request = self._payload(payload)
            capsule_id = str(request.get("capsule_id") or "").strip()
            if not capsule_id:
                return self._error("capsule_id_required")
            with self._capsule_store.read_connection() as connection:
                capsule = connection.execute(
                    "SELECT c.*, g.display_name FROM capsules c JOIN capability_groups g "
                    "ON g.capability_key = c.capability_key WHERE c.capsule_id = ?",
                    (capsule_id,),
                ).fetchone()
                if capsule is None:
                    return self._error("capsule_not_found")
                versions = []
                for row in connection.execute(
                    "SELECT * FROM capsule_versions WHERE capsule_id = ? "
                    "ORDER BY version_number DESC",
                    (capsule_id,),
                ):
                    item = self._json_columns(
                        dict(row),
                        (
                            "extraction_summary_json",
                            "activation_json",
                            "input_contract_json",
                            "output_contract_json",
                            "error_contract_json",
                            "runtime_allowlist_json",
                            "dom_scope_json",
                            "usage_scope_json",
                            "javascript_modules_json",
                            "cleaning_summary_json",
                            "supervision_result_json",
                            "validation_result_json",
                        ),
                    )
                    item.pop("html_text", None)
                    item.pop("css_text", None)
                    item.pop("javascript_modules_json", None)
                    versions.append(item)
                sources = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT cs.* FROM capsule_sources cs JOIN capsule_versions cv "
                        "ON cv.version_id = cs.version_id WHERE cv.capsule_id = ? "
                        "ORDER BY cs.read_at DESC",
                        (capsule_id,),
                    )
                ]
                usage = [
                    self._json_columns(dict(row), ("usage_scope_json",))
                    for row in connection.execute(
                        "SELECT * FROM product_capsule_usage WHERE capsule_id = ? "
                        "ORDER BY generated_at DESC",
                        (capsule_id,),
                    )
                ]
                events = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM capsule_status_events WHERE capsule_id = ? "
                        "ORDER BY created_at DESC",
                        (capsule_id,),
                    )
                ]
            return self._ok(
                {
                    "capsule": dict(capsule),
                    "versions": versions,
                    "sources": sources,
                    "product_usage": usage,
                    "status_events": events,
                }
            )
        except (CapsuleStoreError, OSError, ValueError) as exc:
            return self._exception_error(exc, "get_capsule_detail_failed")

    @_serialized_management
    def get_capsule_core_code_projection(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
        except ValueError:
            return self._error("capsule_core_code_projection_unavailable")
        identities: dict[str, str] = {}
        for field in ("capsule_id", "version_id", "project_id"):
            raw = request.get(field)
            if raw is None or (type(raw) is str and not raw.strip()):
                return self._error(f"{field}_required")
            if type(raw) is str and raw == raw.strip():
                identities[field] = raw
            else:
                return self._error("capsule_core_code_projection_unavailable")

        try:
            if not self._capsule_store.path.is_file():
                return self._error("capsule_core_code_projection_unavailable")
            capsule_id = identities["capsule_id"]
            version_id = identities["version_id"]
            project_id = identities["project_id"]
            source_identity = f"project:{project_id}"
            with self._capsule_store.read_connection() as connection:
                connection.execute("BEGIN")
                stored = connection.execute(
                    "SELECT c.status, c.current_version_id, c.capability_kind, cv.* "
                    "FROM capsules c JOIN capsule_versions cv "
                    "ON cv.capsule_id = c.capsule_id "
                    "WHERE c.capsule_id = ? AND cv.version_id = ?",
                    (capsule_id, version_id),
                ).fetchone()
                if stored is None:
                    return self._error("capsule_core_code_projection_unavailable")
                row = dict(stored)

                parsed: dict[str, Any] = {}
                for source, target in (
                    ("extraction_summary_json", "extraction_summary"),
                    ("activation_json", "activation"),
                    ("input_contract_json", "input_contract"),
                    ("output_contract_json", "output_contract"),
                    ("error_contract_json", "error_contract"),
                    ("runtime_allowlist_json", "runtime_allowlist"),
                    ("dom_scope_json", "dom_scope"),
                    ("usage_scope_json", "usage_scope"),
                    ("javascript_modules_json", "javascript_modules"),
                    ("cleaning_summary_json", "cleaning_summary"),
                    ("supervision_result_json", "supervision_result"),
                    ("validation_result_json", "validation_result"),
                ):
                    parsed[target] = _strict_json_bytes(
                        str(row[source]).encode("utf-8")
                    )

                if not self._capsule_stage3._eligible_exact(row):
                    return self._error("capsule_core_code_projection_unavailable")
                source = connection.execute(
                    "SELECT 1 FROM capsule_sources WHERE version_id = ? "
                    "AND project_id = ? AND source_kind = 'project' "
                    "AND source_identity = ? LIMIT 1",
                    (version_id, project_id, source_identity),
                ).fetchone()
                if source is None:
                    return self._error("capsule_core_code_projection_unavailable")

                assets = [
                    {
                        "logical_path": str(asset["logical_path"]),
                        "media_type": str(asset["media_type"]),
                        "sha256": str(asset["sha256"]),
                    }
                    for asset in connection.execute(
                        "SELECT logical_path, media_type, sha256 FROM capsule_assets "
                        "WHERE version_id = ? ORDER BY logical_path",
                        (version_id,),
                    )
                ]

            canonical = canonicalize_capsule(
                {
                    "capability_kind": row["capability_kind"],
                    "activation": parsed["activation"],
                    "input_contract": parsed["input_contract"],
                    "output_contract": parsed["output_contract"],
                    "error_contract": parsed["error_contract"],
                    "runtime_allowlist": parsed["runtime_allowlist"],
                    "dom_scope": parsed["dom_scope"],
                    "usage_scope": parsed["usage_scope"],
                    "html": row["html_text"],
                    "css": row["css_text"],
                    "javascript_modules": parsed["javascript_modules"],
                    "assets": assets,
                }
            )
            try:
                verify_formal_capsule_identity(
                    capability_kind=str(row["capability_kind"]),
                    canonical_payload_digest=canonical.sha256,
                    stored_canonical_hash=row["canonical_hash"],
                    extraction_summary=parsed["extraction_summary"],
                )
            except ValueError:
                return self._error("capsule_core_code_projection_unavailable")

            activation = canonical.payload["activation"]
            entry_module = activation.get("entry_module")
            if (
                type(entry_module) is not str
                or PurePosixPath(entry_module).suffix.lower() not in {".js", ".mjs"}
            ):
                return self._error("capsule_core_code_projection_unavailable")
            entries = [
                module
                for module in canonical.payload["javascript_modules"]
                if module["path"] == entry_module
            ]
            if len(entries) != 1 or not entries[0]["source"].strip():
                return self._error("capsule_core_code_projection_unavailable")

            validation = parsed["validation_result"]
            validation_fields = (
                row["validation_contract_version"],
                validation.get("schema_version") if type(validation) is dict else None,
                validation.get("status") if type(validation) is dict else None,
                validation.get("acceptance_scope") if type(validation) is dict else None,
            )
            if (
                any(type(value) is not str or not value for value in validation_fields)
                or validation_fields[2] != "passed"
            ):
                return self._error("capsule_core_code_projection_unavailable")

            content = entries[0]["source"]
            return self._ok(
                {
                    "schema_version": "capsule_core_code_projection.v1",
                    "capsule_id": capsule_id,
                    "version_id": version_id,
                    "project_id": project_id,
                    "source_identity": source_identity,
                    "canonical_hash": str(row["canonical_hash"]),
                    "capability_kind": row["capability_kind"],
                    "validation": {
                        "contract_version": validation_fields[0],
                        "schema_version": validation_fields[1],
                        "status": validation_fields[2],
                        "acceptance_scope": validation_fields[3],
                    },
                    "core_code": {
                        "kind": "javascript_entry_module",
                        "logical_path": entry_module,
                        "language": "javascript",
                        "content": content,
                        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    },
                }
            )
        except (
            CapsuleStoreError,
            KeyError,
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
            sqlite3.Error,
        ):
            return self._error("capsule_core_code_projection_unavailable")

    @_serialized_management
    def set_capsule_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            self._ensure_capsule_management()
            request = self._payload(payload)
            capsule_id = str(request.get("capsule_id") or "").strip()
            status = str(request.get("status") or "").strip()
            reason_code = str(request.get("reason_code") or "user_status_change").strip()
            if not capsule_id or status not in {"active", "pending_revalidation", "disabled"}:
                return self._error("capsule_status_invalid")
            if not re.fullmatch(r"[a-z][a-z0-9_]{1,95}", reason_code):
                return self._error("capsule_status_reason_invalid")
            with self._capsule_store.transaction() as connection:
                row = connection.execute(
                    "SELECT cv.*, c.status, c.current_version_id, c.capability_key, "
                    "c.role_key, c.variant_key, c.capability_kind FROM capsules c "
                    "LEFT JOIN capsule_versions cv ON cv.version_id = c.current_version_id "
                    "WHERE c.capsule_id = ?",
                    (capsule_id,),
                ).fetchone()
                if row is None:
                    return self._error("capsule_not_found")
                current = dict(row)
                previous = str(current["status"])
                if previous == status:
                    return self._ok({"capsule_id": capsule_id, "status": status})
                if status == "active":
                    if previous == "pending_revalidation":
                        return self._error("capsule_status_transition_invalid")
                    if previous == "disabled" and connection.execute(
                        "SELECT 1 FROM capsule_status_events WHERE capsule_id = ? "
                        "AND version_id = ? AND event_type = 'revalidation_required' LIMIT 1",
                        (capsule_id, current["current_version_id"]),
                    ).fetchone():
                        return self._error("capsule_revalidation_required")
                    eligible = dict(current)
                    eligible["status"] = "active"
                    if not self._capsule_stage3._eligible_exact(eligible):
                        return self._error("capsule_current_version_not_eligible")
                    event_type = "enabled"
                elif status == "pending_revalidation":
                    if previous != "active":
                        return self._error("capsule_status_transition_invalid")
                    event_type = "revalidation_required"
                else:
                    if previous not in {"active", "pending_revalidation"}:
                        return self._error("capsule_status_transition_invalid")
                    event_type = "disabled"
                connection.execute(
                    "UPDATE capsules SET status = ? WHERE capsule_id = ?",
                    (status, capsule_id),
                )
                connection.execute(
                    "INSERT INTO capsule_status_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"evt_{uuid.uuid4().hex}",
                        capsule_id,
                        event_type,
                        previous,
                        status,
                        current["current_version_id"],
                        reason_code,
                        _now(),
                    ),
                )
                self._capsule_store.bump_revision(connection)
            return self._ok({"capsule_id": capsule_id, "status": status})
        except (CapsuleStoreError, Stage3Error, OSError, ValueError) as exc:
            return self._exception_error(exc, "set_capsule_status_failed")

    def create_backup(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            kind = str(request.get("kind") or "manual")
            if kind != "manual":
                return self._error("backup_kind_invalid")
            return self._submit_management_task(
                "create_backup",
                lambda _cancel: self._capsule_store.create_backup(kind),
            )
        except ValueError as exc:
            return self._exception_error(exc, "create_backup_invalid")

    @_serialized_management
    def list_backups(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            self._payload(payload)
            rows = self._capsule_store.list_backups()
            for row in rows:
                if row.get("valid") is False:
                    row["error"] = "backup_invalid"
            return self._ok({"backups": rows})
        except (CapsuleStoreError, OSError, ValueError, sqlite3.Error) as exc:
            return self._exception_error(exc, "list_backups_failed")

    @_serialized_management
    def inspect_backup(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            path = str(request.get("path") or "").strip()
            if not path:
                return self._error("backup_path_required")
            return self._ok(self._capsule_store.inspect_restore(path))
        except (CapsuleStoreError, OSError, ValueError, sqlite3.Error) as exc:
            return self._exception_error(exc, "inspect_backup_failed")

    def restore_backup(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            path = str(request.get("path") or "").strip()
            expected_sha256 = str(request.get("expected_sha256") or "").strip()
            if not path or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
                return self._error("restore_confirmation_required")

            def action(_cancel: threading.Event) -> dict[str, Any]:
                result = self._capsule_store.restore_backup(
                    path, expected_sha256=expected_sha256
                )
                self._capsule_intake.recover_interrupted_runs()
                self._management_recovered = True
                self._management_rules_checked = False
                return result

            return self._submit_management_task(
                "restore_backup",
                action,
                restore=True,
            )
        except ValueError as exc:
            return self._exception_error(exc, "restore_backup_invalid")

    @staticmethod
    def _stable_file_bytes(path: Path, *, limit: int = 16 * 1024 * 1024) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise ValueError("legacy_warehouse_not_found")
        before = path.stat()
        if before.st_size > limit:
            raise ValueError("legacy_warehouse_too_large")
        raw = path.read_bytes()
        after = path.stat()
        if (
            before.st_ino,
            before.st_dev,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_ino,
            after.st_dev,
            after.st_size,
            after.st_mtime_ns,
        ) or len(raw) != before.st_size:
            raise ValueError("legacy_warehouse_changed_during_read")
        return raw

    def _legacy_summary(self) -> dict[str, Any]:
        path = legacy_warehouse_path()
        result: dict[str, Any] = {
            "path": str(path),
            "present": path.is_file() and not path.is_symlink(),
            "readOnly": True,
            "generationSource": False,
            "recognizableEntries": 0,
        }
        if not result["present"]:
            return result
        try:
            raw = self._stable_file_bytes(path)
            data = _strict_json_bytes(raw)
            capsules = data.get("capsules") if type(data) is dict else None
            if type(capsules) is not list:
                raise ValueError("legacy_warehouse_schema_invalid")
            result.update(
                {
                    "fileSha256": hashlib.sha256(raw).hexdigest(),
                    "recognizableEntries": sum(
                        type(item) is dict
                        and type(item.get("id")) is str
                        and _LEGACY_ID.fullmatch(item["id"]) is not None
                        for item in capsules
                    ),
                    "totalEntries": len(capsules),
                    "status": "ready",
                }
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
            result["status"] = "invalid"
        return result

    @staticmethod
    def _legacy_source_paths() -> dict[str, str]:
        path = legacy_registry_path()
        if not path.is_file() or path.is_symlink():
            return {}
        try:
            raw = ReweaveAppService._stable_file_bytes(path)
            value = _strict_json_bytes(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
            return {}
        rows = value.get("source_boxes") if type(value) is dict else None
        if type(rows) is not list:
            return {}
        result: dict[str, str] = {}
        for row in rows:
            if type(row) is not dict:
                continue
            source_id = row.get("id")
            source_path = row.get("path")
            if type(source_id) is str and type(source_path) is str:
                result[source_id] = source_path
        return result

    def _legacy_item_source_paths(self, expected_file_hash: str) -> dict[str, str]:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_file_hash):
            return {}
        try:
            raw = self._stable_file_bytes(legacy_warehouse_path())
            if hashlib.sha256(raw).hexdigest() != expected_file_hash:
                return {}
            value = _strict_json_bytes(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
            return {}
        rows = value.get("capsules") if type(value) is dict else None
        if type(rows) is not list:
            return {}
        registered = self._legacy_source_paths()
        result: dict[str, str] = {}
        for item in rows:
            if type(item) is not dict:
                continue
            legacy_id = item.get("id")
            if type(legacy_id) is not str or _LEGACY_ID.fullmatch(legacy_id) is None:
                continue
            source_box = item.get("source_box")
            source_box = source_box if type(source_box) is dict else {}
            source_id = item.get("source_id") or source_box.get("source_id")
            if type(source_id) is str and source_id in registered:
                result.setdefault(legacy_id, registered[source_id])
        return result

    @staticmethod
    def _matching_legacy_projects(
        connection: sqlite3.Connection, source_path: str
    ) -> list[str]:
        try:
            target = Path(source_path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            return []
        matches: list[str] = []
        rows = connection.execute(
            "SELECT p.project_id, p.project_relpath, r.current_path "
            "FROM projects p JOIN source_roots r ON r.root_id = p.source_root_id "
            "WHERE r.status = 'bound' AND p.project_state = 'ready' "
            "ORDER BY p.project_id"
        ).fetchall()
        for row in rows:
            relative = str(row["project_relpath"])
            if "\\" in relative:
                continue
            pure = PurePosixPath(relative)
            if pure.is_absolute() or any(part == ".." for part in pure.parts):
                continue
            try:
                root = Path(str(row["current_path"])).expanduser().resolve(strict=True)
                candidate = root if relative == "." else root.joinpath(*pure.parts)
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, RuntimeError, ValueError):
                continue
            if resolved == target:
                matches.append(str(row["project_id"]))
        return matches

    def _legacy_project_id(self, source_path: str) -> str | None:
        try:
            resolved = str(Path(source_path).expanduser().resolve(strict=True))
        except (OSError, RuntimeError):
            return None
        with self._capsule_store.read_connection() as connection:
            project_ids = self._matching_legacy_projects(connection, resolved)
        return project_ids[0] if len(project_ids) == 1 else None

    def _create_legacy_run(self, path_hash: str, file_hash: str) -> str:
        run_id = f"run_{uuid.uuid4().hex}"
        with self._capsule_store.transaction() as connection:
            connection.execute(
                "INSERT INTO intake_runs (run_id, project_id, run_kind, status, "
                "extraction_contract_version, redaction_rules_version, security_rules_version, "
                "supervision_rules_version, validation_contract_version, canonicalization_version, "
                "counts_json, legacy_source_path_hash, legacy_source_file_hash, started_at, created_at) "
                "VALUES (?, NULL, 'legacy_import', 'running', ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?)",
                (
                    run_id,
                    EXTRACTION_CONTRACT_VERSION,
                    REDACTION_RULES_VERSION,
                    SECURITY_RULES_VERSION,
                    SUPERVISION_RULES_VERSION,
                    VALIDATION_CONTRACT_VERSION,
                    CANONICALIZATION_VERSION,
                    path_hash,
                    file_hash,
                    _now(),
                    _now(),
                ),
            )
            self._capsule_store.bump_revision(connection)
        return run_id

    def _finish_legacy_run(
        self,
        run_id: str,
        status: str,
        counts: dict[str, Any],
        *,
        error_code: str | None = None,
    ) -> None:
        with self._capsule_store.transaction() as connection:
            connection.execute(
                "UPDATE intake_runs SET status = ?, counts_json = ?, error_code = ?, "
                "completed_at = ? WHERE run_id = ?",
                (
                    status,
                    json.dumps(counts, sort_keys=True, separators=(",", ":")),
                    error_code,
                    _now(),
                    run_id,
                ),
            )
            self._capsule_store.bump_revision(connection)

    def _legacy_import(
        self,
        cancel: threading.Event,
        links: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        path = legacy_warehouse_path()
        path_hash = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()
        try:
            raw = self._stable_file_bytes(path)
        except (OSError, ValueError) as exc:
            raise IntakeError(str(exc)) from exc
        file_hash = hashlib.sha256(raw).hexdigest()
        run_id = self._create_legacy_run(path_hash, file_hash)
        counts = {"total": 0, "skipped": 0, "pending": 0, "rejected": 0, "linked": 0}
        try:
            data = _strict_json_bytes(raw)
            capsules = data.get("capsules") if type(data) is dict else None
            if type(capsules) is not list:
                raise ValueError("legacy_warehouse_schema_invalid")
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
            self._finish_legacy_run(
                run_id,
                "failed",
                counts,
                error_code="legacy_warehouse_parse_failed",
            )
            raise IntakeError("legacy_warehouse_parse_failed") from exc
        counts["total"] = len(capsules)
        source_paths = self._legacy_source_paths()
        aliases: list[dict[str, Any]] = []
        seen: set[str] = set()
        refreshed: dict[str, dict[str, Any]] = {}
        with self._capsule_store.read_connection() as connection:
            completed = {
                str(row[0])
                for row in connection.execute(
                    "SELECT a.legacy_capsule_id FROM legacy_capsule_aliases a "
                    "WHERE a.legacy_file_hash = ? AND a.relationship <> 'pending'",
                    (file_hash,),
                )
            }
        for index, item in enumerate(capsules):
            if cancel.is_set():
                self._finish_legacy_run(run_id, "cancelled", counts, error_code="cancelled_by_user")
                return {"import_run_id": run_id, "status": "cancelled", "counts": counts}
            safe_id = f"item_{index}"
            reason = "legacy_item_invalid"
            relationship = "rejected"
            target: dict[str, Any] | None = None
            if type(item) is dict and type(item.get("id")) is str:
                candidate_id = item["id"]
                if _LEGACY_ID.fullmatch(candidate_id) and candidate_id not in seen:
                    safe_id = candidate_id
                    reason = "legacy_source_project_required"
                    relationship = "pending"
            if safe_id in completed:
                counts["skipped"] += 1
                continue
            if safe_id in seen:
                safe_id = f"item_{index}"
                reason = "legacy_capsule_id_duplicate"
                relationship = "rejected"
            seen.add(safe_id)
            item_hash = hashlib.sha256(
                json.dumps(
                    item if type(item) is dict else {"invalid_item_index": index},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            project_id = None
            if type(item) is dict and relationship == "pending":
                source_box = item.get("source_box") if type(item.get("source_box")) is dict else {}
                source_id = str(item.get("source_id") or source_box.get("source_id") or "")
                source_path = source_paths.get(source_id)
                if source_path:
                    project_id = self._legacy_project_id(source_path)
            if project_id:
                if project_id not in refreshed:
                    try:
                        refreshed[project_id] = self._refresh_project(project_id, cancel)
                    except (IntakeError, Stage3Error) as exc:
                        refreshed[project_id] = {"error_code": exc.code}
                if cancel.is_set() or refreshed[project_id].get("status") == "cancelled":
                    self._finish_legacy_run(
                        run_id, "cancelled", counts, error_code="cancelled_by_user"
                    )
                    return {
                        "import_run_id": run_id,
                        "status": "cancelled",
                        "counts": counts,
                    }
                if "error_code" in refreshed[project_id]:
                    reason = "legacy_reclean_failed"
                else:
                    reason = "legacy_reclean_requires_human_mapping"
                    link = links.get(safe_id)
                    if link is not None:
                        link_relationship = str(link.get("relationship") or "")
                        capsule_id = str(link.get("capsule_id") or "")
                        version_id = str(link.get("version_id") or "")
                        if link_relationship not in {"cleaned_successor", "merged", "variant"}:
                            raise IntakeError("legacy_link_relationship_invalid")
                        with self._capsule_store.read_connection() as connection:
                            row = connection.execute(
                                "SELECT cv.canonical_hash FROM capsule_versions cv "
                                "JOIN capsules c ON c.capsule_id = cv.capsule_id "
                                "WHERE cv.version_id = ? AND cv.capsule_id = ? "
                                "AND c.status = 'active' AND c.current_version_id = cv.version_id "
                                "AND EXISTS (SELECT 1 FROM capsule_sources cs "
                                "WHERE cs.version_id = cv.version_id AND cs.project_id = ? "
                                "AND cs.source_kind = 'project')",
                                (version_id, capsule_id, project_id),
                            ).fetchone()
                        if row is None:
                            raise IntakeError("legacy_link_target_invalid")
                        relationship = link_relationship
                        reason = "legacy_link_user_confirmed"
                        target = {
                            "capsule_id": capsule_id,
                            "version_id": version_id,
                            "canonical_hash": str(row["canonical_hash"]),
                        }
            aliases.append(
                {
                    "legacy_id": safe_id,
                    "relationship": relationship,
                    "reason": reason,
                    "item_hash": item_hash,
                    "target": target,
                }
            )
        if cancel.is_set():
            self._finish_legacy_run(
                run_id, "cancelled", counts, error_code="cancelled_by_user"
            )
            return {"import_run_id": run_id, "status": "cancelled", "counts": counts}
        with self._capsule_store.transaction() as connection:
            for alias in aliases:
                target = alias["target"]
                connection.execute(
                    "INSERT INTO legacy_capsule_aliases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"alias_{uuid.uuid4().hex}",
                        run_id,
                        file_hash,
                        alias["legacy_id"],
                        alias["relationship"],
                        target["capsule_id"] if target else None,
                        target["version_id"] if target else None,
                        alias["reason"],
                        _now(),
                    ),
                )
                if target:
                    connection.execute(
                        "INSERT OR IGNORE INTO capsule_sources VALUES (?, ?, NULL, ?, "
                        "'legacy_json', ?, ?, ?, 'human_equivalent', ?)",
                        (
                            f"src_{uuid.uuid4().hex}",
                            target["version_id"],
                            f"legacy:{file_hash}",
                            f"capsules/{alias['legacy_id']}",
                            alias["item_hash"],
                            alias["item_hash"],
                            _now(),
                        ),
                    )
                counts["linked" if target else alias["relationship"]] += 1
            self._capsule_store.bump_revision(connection)
        status = "completed_with_pending" if counts["pending"] else "completed"
        self._finish_legacy_run(run_id, status, counts)
        return {"import_run_id": run_id, "status": status, "counts": counts}

    def start_legacy_import(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            raw_links = request.get("links") or []
            if type(raw_links) is not list:
                return self._error("legacy_links_invalid")
            links: dict[str, dict[str, Any]] = {}
            for item in raw_links:
                if type(item) is not dict or type(item.get("legacy_capsule_id")) is not str:
                    return self._error("legacy_link_invalid")
                legacy_id = item["legacy_capsule_id"]
                if legacy_id in links or _LEGACY_ID.fullmatch(legacy_id) is None:
                    return self._error("legacy_link_invalid")
                links[legacy_id] = item
            return self._submit_management_task(
                "legacy_import",
                lambda cancel: self._legacy_import(cancel, links),
                cancellable=True,
            )
        except ValueError as exc:
            return self._exception_error(exc, "legacy_import_invalid")

    def bind_source_folder(self, path: str) -> dict[str, Any]:
        return self._ensure_legacy_engine().bind_source_folder(path)

    def scan_source(self, source_id: str) -> dict[str, Any]:
        return self._ensure_legacy_engine().scan_source(source_id)

    def draft_source(self, source_id: str) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._engine.draft_source(source_id)
        if not self._is_lumo():
            return self._engine.draft_source(source_id)
        return self._draft_source_lumo(source_id)

    def promote_source(self, source_id: str) -> Any:
        if self._is_lumo_lite():
            return self._engine.promote_source(source_id)
        if not self._is_lumo():
            return self._engine.promote_source(source_id)
        return LocalReweaveEngine().promote_source(source_id)

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        return self._ensure_legacy_engine().get_source(source_id)

    def verify_source_suggestions(self, source_id: str) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._lumo_lite_disabled("verify_source_suggestions")
        source_id = (source_id or "").strip()
        if not source_id:
            return {"ok": False, "error": "missing source_id"}

        if not get_source_box(source_id):
            return {"ok": False, "error": "source_not_found", "source_id": source_id}

        summary = load_summary(source_id)
        if not summary:
            return {"ok": False, "error": "source_not_scanned", "source_id": source_id}

        reuse_record = load_reuse_suggestions(source_id)
        suggestions = (
            reuse_record.get("mapped_capsuleSuggestions")
            if isinstance(reuse_record, dict)
            else None
        )
        if not reuse_record or not isinstance(suggestions, list) or not suggestions:
            return {"ok": False, "error": "no_reuse_suggestions", "source_id": source_id}

        draft = load_draft(source_id)
        verification = verify_and_save(source_id, summary, reuse_record, draft)
        return {
            "ok": True,
            "source_id": source_id,
            "mode": verification.get("mode"),
            "verification": verification,
            "summary": verification.get("summary"),
        }

    def preview_governance_for_source(self, source_id: str) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._lumo_lite_disabled("preview_governance_for_source")
        source_id = (source_id or "").strip()
        if not source_id:
            return {"ok": False, "error": "missing source_id"}

        if not get_source_box(source_id):
            return {"ok": False, "error": "source_not_found", "source_id": source_id}

        verification = load_verification(source_id)
        if not verification:
            return {"ok": False, "error": "no_verification", "source_id": source_id}

        reuse_record = load_reuse_suggestions(source_id)
        suggestions = (
            reuse_record.get("mapped_capsuleSuggestions")
            if isinstance(reuse_record, dict)
            else None
        )
        if not reuse_record or not isinstance(suggestions, list) or not suggestions:
            return {"ok": False, "error": "no_reuse_suggestions", "source_id": source_id}

        summary = load_summary(source_id)
        draft = load_draft(source_id)
        warnings: list[str] = []
        luna_preview_block: dict[str, Any] | None = None

        if self._is_lumo():
            client = LunaHttpClient()
            if client.health().get("ok"):
                luna_result = client.governance_preview({"stale_days": 30, "include_blocked": False})
                if luna_result.get("ok"):
                    luna_preview_block = {
                        "endpoint": luna_result.get("endpoint"),
                        "raw": luna_result.get("raw"),
                    }
                else:
                    warnings.append("luna_governance_preview_failed")

        preview = preview_and_save(
            source_id,
            verification,
            reuse_record,
            summary,
            draft,
            luna_preview=luna_preview_block,
            warnings=warnings,
        )
        return {
            "ok": True,
            "source_id": source_id,
            "mode": preview.get("mode"),
            "preview": preview,
            "summary": preview.get("summary"),
            "warnings": warnings,
        }

    def create_review_queue_for_source(self, source_id: str) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._lumo_lite_disabled("create_review_queue_for_source")
        source_id = (source_id or "").strip()
        if not source_id:
            return {"ok": False, "error": "missing source_id"}

        if not get_source_box(source_id):
            return {"ok": False, "error": "source_not_found", "source_id": source_id}

        governance_preview = load_governance_preview(source_id)
        if not governance_preview:
            return {"ok": False, "error": "no_governance_preview", "source_id": source_id}

        verification = load_verification(source_id)
        queue = create_or_update_review_queue(source_id, governance_preview, verification)
        preview_items = [
            {
                "review_id": item.get("review_id"),
                "name": item.get("name"),
                "governance_action": item.get("governance_action"),
                "verification_score": item.get("verification_score"),
                "decision": item.get("decision"),
            }
            for item in (queue.get("items") or [])[:3]
            if isinstance(item, dict)
        ]
        return {
            "ok": True,
            "source_id": source_id,
            "mode": queue.get("mode"),
            "queue": queue,
            "summary": queue.get("summary"),
            "preview_items": preview_items,
        }

    def update_review_decision(
        self,
        source_id: str,
        review_id: str,
        decision: str,
        reason: str = "",
    ) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._lumo_lite_disabled("update_review_decision")
        source_id = (source_id or "").strip()
        review_id = (review_id or "").strip()
        if not source_id or not review_id:
            return {"ok": False, "error": "missing source_id or review_id"}

        try:
            result = apply_review_decision(source_id, review_id, decision, reason)
        except FileNotFoundError:
            return {"ok": False, "error": "no_review_queue", "source_id": source_id}
        except KeyError:
            return {"ok": False, "error": "review_item_not_found", "source_id": source_id, "review_id": review_id}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)[:200], "source_id": source_id}

        return {
            "ok": True,
            "source_id": source_id,
            "review_id": review_id,
            "item": result.get("item"),
            "summary": result.get("summary"),
        }

    def promote_review_item(self, source_id: str, review_id: str) -> dict[str, Any]:
        """Explicit promote — approved review item to local warehouse only."""
        if self._is_lumo_lite():
            return self._lumo_lite_disabled("promote_review_item")
        result = execute_promote_review_item(source_id, review_id)
        if result.get("ok"):
            result["warehouseCapsules"] = list_warehouse_capsules(include_inactive=True)
            result["capsules"] = result["warehouseCapsules"]
        return result

    def list_warehouse_capsules(self, *, include_inactive: bool = True) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._lumo_lite_disabled("list_warehouse_capsules", capsules=[], count=0)
        capsules = list_warehouse_capsules(include_inactive=include_inactive)
        return {"ok": True, "capsules": capsules, "count": len(capsules)}

    def update_capsule_status(self, capsule_id: str, status: str) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._lumo_lite_disabled(
                "update_capsule_status",
                capsule_id=(capsule_id or "").strip(),
            )
        capsule_id = (capsule_id or "").strip()
        status = (status or "").strip()
        if not capsule_id or not status:
            return {"ok": False, "error": "missing capsule_id or status"}
        try:
            return apply_capsule_status(capsule_id, status)
        except KeyError:
            return {"ok": False, "error": "capsule_not_found", "capsule_id": capsule_id}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)[:200], "capsule_id": capsule_id}

    def enrich_capsule_content(self, capsule_id: str) -> dict[str, Any]:
        """Explicit controlled snippet enrichment — read-only, user triggered."""
        if self._is_lumo_lite():
            return self._engine.enrich_capsule_content(capsule_id)
        return execute_capsule_content_enrichment(capsule_id)

    def get_capsule_content(self, capsule_id: str) -> dict[str, Any]:
        """Read enriched content from app state — viewer only, no source folder access."""
        if self._is_lumo_lite():
            return self._engine.get_capsule_content(capsule_id)
        return fetch_capsule_content(capsule_id)

    def get_latest_preview_package(self) -> dict[str, Any]:
        """Read-only viewer for the most recent preview package."""
        if self._is_lumo_lite():
            return fetch_latest_preview_package()
        return fetch_latest_preview_package()

    def get_preview_package(self, package_id_or_path: str) -> dict[str, Any]:
        """Read-only viewer for a specific preview package."""
        if self._is_lumo_lite():
            return fetch_preview_package(package_id_or_path)
        return fetch_preview_package(package_id_or_path)

    def compare_preview_packages(self, left_id: str = "", right_id: str = "") -> dict[str, Any]:
        """Metadata-only compare between two preview packages."""
        if self._is_lumo_lite():
            return compare_preview_packages_view(left_id, right_id)
        return compare_preview_packages_view(left_id, right_id)

    def export_preview_package(
        self,
        package_id_or_path: str,
        export_dir: str,
        mode: str = "zip",
    ) -> dict[str, Any]:
        """Export preview package to user-chosen directory (zip or copy)."""
        if self._is_lumo_lite():
            return self._lumo_lite_disabled("export_preview_package")
        return execute_preview_export(package_id_or_path, export_dir, mode=mode)

    def list_lumo_lite_artifacts(self) -> dict[str, Any]:
        self._ensure_legacy_engine()
        if hasattr(self._engine, "list_lumo_lite_artifacts"):
            return self._engine.list_lumo_lite_artifacts()  # type: ignore[attr-defined]
        return {"ok": False, "error": "lumo_lite_artifacts_unavailable"}

    def get_lumo_lite_artifact(self, artifact_id_or_path: str) -> dict[str, Any]:
        self._ensure_legacy_engine()
        if hasattr(self._engine, "get_lumo_lite_artifact"):
            return self._engine.get_lumo_lite_artifact(artifact_id_or_path)  # type: ignore[attr-defined]
        return {"ok": False, "error": "lumo_lite_artifact_unavailable"}

    def get_lumo_lite_artifact_path(self, artifact_id_or_path: str) -> str | None:
        self._ensure_legacy_engine()
        if hasattr(self._engine, "get_lumo_lite_artifact_path"):
            return self._engine.get_lumo_lite_artifact_path(artifact_id_or_path)  # type: ignore[attr-defined]
        return None

    def analyze_static_web_target(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            if set(request) != {"target_path", "entry_relpath"}:
                raise StaticWebTargetError(
                    "target_profile_request_invalid", {"phase": "request"}
                )
            target_path = request.get("target_path")
            entry_relpath = request.get("entry_relpath")
            if type(target_path) is not str or not target_path.strip():
                raise StaticWebTargetError(
                    "target_path_required", {"phase": "path"}
                )
            if type(entry_relpath) is not str or not entry_relpath:
                raise StaticWebTargetError(
                    "target_entry_required", {"phase": "entry"}
                )
            return self._ok(
                analyze_static_web_target_profile(target_path, entry_relpath)
            )
        except (OSError, StaticWebTargetError, ValueError) as exc:
            return self._target_exception_error(exc, "target_profile_failed")

    @_serialized_management
    def generate_static_web_patch(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            self._ensure_capsule_management()
            request = self._payload(payload)
            expected_keys = {
                "target_path",
                "entry_relpath",
                "task",
                "capsule_ids",
                "selection_mode",
                "authorization",
            }
            if set(request) != expected_keys:
                raise StaticWebTargetError(
                    "target_patch_authorization_invalid",
                    {"phase": "authorization"},
                )
            target_path = request.get("target_path")
            entry_relpath = request.get("entry_relpath")
            task = str(request.get("task") or "").strip()
            raw_ids = request.get("capsule_ids")
            selection_mode = request.get("selection_mode")
            authorization = request.get("authorization")
            if type(target_path) is not str or not target_path.strip():
                raise StaticWebTargetError(
                    "target_path_required", {"phase": "path"}
                )
            if type(entry_relpath) is not str or not entry_relpath:
                raise StaticWebTargetError(
                    "target_entry_required", {"phase": "entry"}
                )
            if not task or len(task) > 500:
                raise StaticWebTargetError(
                    "product_task_invalid", {"phase": "request"}
                )
            if (
                type(raw_ids) is not list
                or not raw_ids
                or len(raw_ids) > 3
                or any(type(item) is not str or not item for item in raw_ids)
                or len(raw_ids) != len(set(raw_ids))
            ):
                raise StaticWebTargetError(
                    "formal_capsule_selection_required",
                    {"phase": "capsule_selection"},
                )
            if selection_mode != "manual":
                raise StaticWebTargetError(
                    "formal_selection_mode_invalid",
                    {"phase": "capsule_selection"},
                )
            if (
                type(authorization) is not dict
                or set(authorization) != {"mode", "target_snapshot_sha256"}
                or authorization.get("mode") != TARGET_AUTHORIZATION_MODE
                or re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(authorization.get("target_snapshot_sha256") or ""),
                )
                is None
            ):
                raise StaticWebTargetError(
                    "target_patch_authorization_invalid",
                    {"phase": "authorization"},
                )

            before = capture_static_web_target(target_path, entry_relpath)
            if (
                authorization["target_snapshot_sha256"]
                != before["snapshot_sha256"]
            ):
                raise StaticWebTargetError(
                    "target_snapshot_mismatch", {"phase": "authorization"}
                )
            capsules, product_scope, page_contracts = self._load_composer_capsules(
                list(raw_ids)
            )
            if product_scope != {"kind": "general"}:
                raise StaticWebTargetError(
                    "target_usage_scope_mismatch", {"phase": "authorization"}
                )
            identity = static_web_plan_identity(
                snapshot=before,
                task=task,
                capsules=capsules,
                product_scope=product_scope,
                authorization=authorization,
            )
            try:
                composition = compose_capsule_product(
                    task=task,
                    product_id=identity["product_id"],
                    generated_at="content-addressed",
                    capsules=capsules,
                    verified_page_contracts=page_contracts,
                )
            except ValueError as exc:
                code = str(exc)
                raise ProductGenerationError(
                    code
                    if re.fullmatch(r"[a-z][a-z0-9_]{1,95}", code)
                    else "product_composition_failed"
                ) from exc
            patch = build_static_web_patch(
                snapshot=before,
                task=task,
                capsules=capsules,
                product_scope=product_scope,
                authorization=authorization,
                identity=identity,
                composition=composition,
            )
            with self._capsule_store.read_connection() as connection:
                self._assert_generation_capsules_current(connection, capsules)
            after = capture_static_web_target(target_path, entry_relpath)
            if before["snapshot_sha256"] != after["snapshot_sha256"]:
                raise StaticWebTargetError(
                    "target_changed_during_analysis", {"phase": "consistency"}
                )
            patch["target"]["profile"]["source_unchanged"] = True
            return self._ok(patch)
        except (
            CapsuleStoreError,
            OSError,
            ProductGenerationError,
            sqlite3.Error,
            StaticWebTargetError,
            ValueError,
        ) as exc:
            return self._target_exception_error(exc, "target_patch_generation_failed")

    def generate_product(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            task = str(request.get("task") or "").strip()
            raw_ids = request.get("capsule_ids")
            selection_mode = str(request.get("selection_mode") or "manual")
            if not task or len(task) > 500:
                return self._error("product_task_invalid")
            if (
                type(raw_ids) is not list
                or not raw_ids
                or len(raw_ids) > 3
                or any(type(item) is not str or not item for item in raw_ids)
                or len(raw_ids) != len(set(raw_ids))
            ):
                return self._error("formal_capsule_selection_required")
            if selection_mode != "manual":
                return self._error("formal_selection_mode_invalid")
            capsule_ids = list(raw_ids)
            return self._submit_management_task(
                "generate_product",
                lambda _cancel: self._generate_formal_product(task, capsule_ids),
            )
        except ValueError as exc:
            return self._exception_error(exc, "generate_product_invalid")

    def _load_generation_capsules(
        self,
        capsule_ids: list[str],
        *,
        read_only: bool = False,
        _page_contracts: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not read_only:
            self._ensure_capsule_management()
        placeholders = ",".join("?" for _ in capsule_ids)
        with self._capsule_store.read_connection() as connection:
            rows = connection.execute(
                "SELECT c.status, c.current_version_id, c.capability_key, c.role_key, "
                "c.variant_key, c.capability_kind, cv.* FROM capsules c "
                "JOIN capsule_versions cv ON cv.version_id = c.current_version_id "
                f"WHERE c.capsule_id IN ({placeholders})",
                tuple(capsule_ids),
            ).fetchall()
            by_id = {str(row["capsule_id"]): dict(row) for row in rows}
            if set(by_id) != set(capsule_ids):
                raise ProductGenerationError("formal_capsule_not_found")
            loaded: list[dict[str, Any]] = []
            limited_scopes: set[tuple[str, str]] = set()
            for capsule_id in capsule_ids:
                row = by_id[capsule_id]
                if not self._capsule_stage3._eligible_exact(row):
                    raise ProductGenerationError("formal_capsule_not_generation_eligible")
                try:
                    extraction_summary = _strict_json_bytes(
                        str(row["extraction_summary_json"]).encode("utf-8")
                    )
                except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
                    raise ProductGenerationError(
                        "formal_capsule_contract_invalid"
                    ) from exc
                if type(extraction_summary) is not dict:
                    raise ProductGenerationError("formal_capsule_contract_invalid")
                candidate_origin = extraction_summary.get("candidate_origin")
                adapter_contract_version = extraction_summary.get(
                    "adapter_contract_version"
                )
                if candidate_origin is not None and type(candidate_origin) is not str:
                    raise ProductGenerationError("formal_capsule_contract_invalid")
                if (
                    adapter_contract_version is not None
                    and type(adapter_contract_version) is not str
                ):
                    raise ProductGenerationError("formal_capsule_contract_invalid")
                values: dict[str, Any] = {}
                for source, target in (
                    ("activation_json", "activation"),
                    ("input_contract_json", "input_contract"),
                    ("output_contract_json", "output_contract"),
                    ("error_contract_json", "error_contract"),
                    ("runtime_allowlist_json", "runtime_allowlist"),
                    ("dom_scope_json", "dom_scope"),
                    ("usage_scope_json", "usage_scope"),
                    ("javascript_modules_json", "javascript_modules"),
                ):
                    try:
                        values[target] = _strict_json_bytes(
                            str(row[source]).encode("utf-8")
                        )
                    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
                        raise ProductGenerationError(
                            "formal_capsule_contract_invalid"
                        ) from exc
                usage_scope = values["usage_scope"]
                if type(usage_scope) is not dict:
                    raise ProductGenerationError("formal_capsule_usage_scope_invalid")
                if usage_scope.get("kind") == "brand_limited":
                    limited_scopes.add(
                        (
                            str(usage_scope.get("brand_profile_id") or ""),
                            str(usage_scope.get("brand_profile_digest") or ""),
                        )
                    )
                assets: list[dict[str, Any]] = []
                for asset in connection.execute(
                    "SELECT * FROM capsule_assets WHERE version_id = ? "
                    "ORDER BY logical_path",
                    (row["version_id"],),
                ):
                    content = bytes(asset["content"])
                    digest = hashlib.sha256(content).hexdigest()
                    if digest != asset["sha256"] or len(content) != asset["size_bytes"]:
                        raise ProductGenerationError("formal_capsule_asset_invalid")
                    assets.append(
                        {
                            "logical_path": str(asset["logical_path"]),
                            "media_type": str(asset["media_type"]),
                            "sha256": digest,
                            "content": content,
                        }
                    )
                canonical = canonicalize_capsule(
                    {
                        "capability_kind": row["capability_kind"],
                        "activation": values["activation"],
                        "input_contract": values["input_contract"],
                        "output_contract": values["output_contract"],
                        "error_contract": values["error_contract"],
                        "runtime_allowlist": values["runtime_allowlist"],
                        "dom_scope": values["dom_scope"],
                        "usage_scope": usage_scope,
                        "html": row["html_text"],
                        "css": row["css_text"],
                        "javascript_modules": values["javascript_modules"],
                        "assets": [
                            {
                                "logical_path": item["logical_path"],
                                "media_type": item["media_type"],
                                "sha256": item["sha256"],
                            }
                            for item in assets
                        ],
                    }
                )
                try:
                    identity = verify_formal_capsule_identity(
                        capability_kind=str(row["capability_kind"]),
                        canonical_payload_digest=canonical.sha256,
                        stored_canonical_hash=row["canonical_hash"],
                        extraction_summary=extraction_summary,
                    )
                except ValueError as exc:
                    code = (
                        "formal_capsule_canonical_mismatch"
                        if "page_capability_declaration" not in extraction_summary
                        and "formal_identity_binding" not in extraction_summary
                        else "formal_capsule_identity_invalid"
                    )
                    raise ProductGenerationError(code) from exc
                if identity is not None and _page_contracts is not None:
                    if (
                        connection.execute(
                            "SELECT 1 FROM capsule_sources WHERE version_id = ? "
                            "AND relationship IN ('exact', 'published_implementation') "
                            "AND candidate_canonical_hash = ? LIMIT 1",
                            (row["version_id"], row["canonical_hash"]),
                        ).fetchone()
                        is None
                    ):
                        raise ProductGenerationError(
                            "formal_capsule_source_identity_invalid"
                        )
                    _page_contracts.append(
                        {
                            "capsule_id": capsule_id,
                            "version_id": str(row["version_id"]),
                            "capability_kind": str(row["capability_kind"]),
                            "canonical_hash": str(row["canonical_hash"]),
                            "page_capability_declaration": extraction_summary[
                                "page_capability_declaration"
                            ],
                        }
                    )
                loaded_capsule = {
                        "capsule_id": capsule_id,
                        "version_id": str(row["version_id"]),
                        "canonical_hash": str(row["canonical_hash"]),
                        "capability_key": str(row["capability_key"]),
                        "role_key": str(row["role_key"]),
                        "variant_key": str(row["variant_key"]),
                        "capability_kind": str(row["capability_kind"]),
                        "candidate_origin": candidate_origin,
                        "adapter_contract_version": adapter_contract_version,
                        "activation": values["activation"],
                        "input_contract": values["input_contract"],
                        "output_contract": values["output_contract"],
                        "error_contract": values["error_contract"],
                        "runtime_allowlist": values["runtime_allowlist"],
                        "dom_scope": values["dom_scope"],
                        "usage_scope": usage_scope,
                        "html": str(row["html_text"]),
                        "css": str(row["css_text"]),
                        "javascript_modules": values["javascript_modules"],
                        "assets": assets,
                    }
                if adapter_contract_version == COMPUTATION_ADAPTER_V4:
                    evidence = extraction_summary.get("ephemeral_capture_payload")
                    if type(evidence) is not dict:
                        raise ProductGenerationError(
                            "formal_capsule_contract_invalid"
                        )
                    loaded_capsule["adapter_evidence"] = evidence
                loaded.append(loaded_capsule)
        if len(limited_scopes) > 1 or any(not all(item) for item in limited_scopes):
            raise ProductGenerationError("product_brand_scope_conflict")
        product_scope = (
            {
                "kind": "brand_limited",
                "brand_profile_id": next(iter(limited_scopes))[0],
                "brand_profile_digest": next(iter(limited_scopes))[1],
            }
            if limited_scopes
            else {"kind": "general"}
        )
        return loaded, product_scope

    def _load_generation_capsules_with_page_contracts(
        self,
        capsule_ids: list[str],
        *,
        read_only: bool = False,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
        verified: list[dict[str, Any]] = []
        capsules, product_scope = self._load_generation_capsules(
            capsule_ids,
            read_only=read_only,
            _page_contracts=verified,
        )
        return capsules, product_scope, verified

    def _load_composer_capsules(
        self,
        capsule_ids: list[str],
        *,
        read_only: bool = False,
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, Any],
        list[dict[str, Any]],
    ]:
        return self._load_generation_capsules_with_page_contracts(
            capsule_ids,
            read_only=read_only,
        )

    def _assert_generation_capsules_current(
        self, connection: sqlite3.Connection, capsules: list[dict[str, Any]]
    ) -> None:
        for capsule in capsules:
            row = connection.execute(
                "SELECT c.status, c.current_version_id, c.capability_key, c.role_key, "
                "c.variant_key, c.capability_kind, cv.* FROM capsules c "
                "JOIN capsule_versions cv ON cv.version_id = c.current_version_id "
                "WHERE c.capsule_id = ? AND cv.version_id = ?",
                (capsule["capsule_id"], capsule["version_id"]),
            ).fetchone()
            if (
                row is None
                or not self._capsule_stage3._eligible_exact(dict(row))
                or row["capability_key"] != capsule["capability_key"]
                or row["role_key"] != capsule["role_key"]
                or row["variant_key"] != capsule["variant_key"]
                or row["capability_kind"] != capsule["capability_kind"]
                or row["canonical_hash"] != capsule["canonical_hash"]
                or row["usage_scope_json"]
                != json.dumps(
                    capsule["usage_scope"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            ):
                raise ProductGenerationError("formal_capsule_selection_expired")

    @staticmethod
    def _manifest_capsules(
        capsules: list[dict[str, Any]],
        connections: list[dict[str, Any]],
        *,
        include_canonical_hash: bool = True,
    ) -> list[dict[str, Any]]:
        wired = {
            str(row.get(key) or "")
            for row in connections
            if type(row) is dict
            for key in ("from_version_id", "to_version_id")
            if row.get(key)
        }
        result = []
        for capsule in capsules:
            contributions = {str(capsule["capability_kind"])}
            if capsule["assets"]:
                contributions.add("asset")
            if capsule["version_id"] in wired:
                contributions.add("wiring")
            receipt = {
                "capsule_id": capsule["capsule_id"],
                "version_id": capsule["version_id"],
                "capability_key": capsule["capability_key"],
                "role_key": capsule["role_key"],
                "variant_key": capsule["variant_key"],
                "capability_kind": capsule["capability_kind"],
                "usage_scope": capsule["usage_scope"],
                "contributions": sorted(contributions),
            }
            if include_canonical_hash:
                receipt["canonical_hash"] = capsule["canonical_hash"]
            result.append(receipt)
        return sorted(result, key=lambda item: item["version_id"])

    def _register_product_usage(
        self,
        manifest: dict[str, Any],
        manifest_digest: str,
        capsules: list[dict[str, Any]],
    ) -> None:
        expected = {
            (
                str(row["capsule_id"]),
                str(row["version_id"]),
                str(row["capability_key"]),
                str(row["role_key"]),
                str(row["variant_key"]),
                json.dumps(
                    row["usage_scope"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                str(contribution),
                str(manifest["generated_at"]),
            )
            for row in manifest["capsules"]
            for contribution in row["contributions"]
        }
        with self._capsule_store.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM product_capsule_usage WHERE product_id = ?",
                (manifest["product_id"],),
            ).fetchall()
            if existing:
                actual = {
                    (
                        str(row["capsule_id"]),
                        str(row["version_id"]),
                        str(row["capability_key"]),
                        str(row["role_key"]),
                        str(row["variant_key"]),
                        str(row["usage_scope_json"]),
                        str(row["contribution_role"]),
                        str(row["generated_at"]),
                    )
                    for row in existing
                }
                digests = {str(row["manifest_digest"]) for row in existing}
                if actual == expected and digests == {manifest_digest}:
                    return
                raise ProductGenerationError("product_usage_already_registered")
            self._assert_generation_capsules_current(connection, capsules)
            by_version = {item["version_id"]: item for item in capsules}
            for row in manifest["capsules"]:
                capsule = by_version[row["version_id"]]
                usage_scope_json = json.dumps(
                    capsule["usage_scope"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                for contribution in row["contributions"]:
                    connection.execute(
                        "INSERT INTO product_capsule_usage "
                        "(usage_id, product_id, manifest_digest, capsule_id, version_id, "
                        "capability_key, role_key, variant_key, usage_scope_json, "
                        "contribution_role, generated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            f"usage_{uuid.uuid4().hex}",
                            manifest["product_id"],
                            manifest_digest,
                            capsule["capsule_id"],
                            capsule["version_id"],
                            capsule["capability_key"],
                            capsule["role_key"],
                            capsule["variant_key"],
                            usage_scope_json,
                            contribution,
                            manifest["generated_at"],
                        ),
                    )
            self._capsule_store.bump_revision(connection)

    def _generate_formal_product(
        self, task: str, capsule_ids: list[str]
    ) -> dict[str, Any]:
        capsules, product_scope, page_contracts = self._load_composer_capsules(
            capsule_ids
        )
        product_id = f"product_{uuid.uuid4().hex}"
        generated_at = _now()
        try:
            composition = compose_capsule_product(
                task=task,
                product_id=product_id,
                generated_at=generated_at,
                capsules=capsules,
                verified_page_contracts=page_contracts,
            )
        except ValueError as exc:
            code = str(exc)
            raise ProductGenerationError(
                code if re.fullmatch(r"[a-z][a-z0-9_]{1,95}", code) else "product_composition_failed"
            ) from exc
        if (
            type(composition) is not dict
            or composition.get("status") != "composed"
            or type(composition.get("files")) is not dict
            or type(composition.get("assets")) is not dict
            or type(composition.get("provenance")) is not dict
        ):
            raise ProductGenerationError("product_composition_invalid")
        products = _product_directory()
        if products.is_symlink():
            raise ProductGenerationError("products_directory_unsafe")
        products.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            products.chmod(0o700)
        final = products / product_id
        temporary = Path(tempfile.mkdtemp(prefix=f".{product_id}-", dir=products))
        promoted = False
        usage_registered = False
        try:
            paths: set[str] = set()
            for relative, content in composition["files"].items():
                logical = _safe_product_relative(relative)
                if logical in paths:
                    raise ProductGenerationError("product_file_duplicate")
                paths.add(logical)
                _write_product_file(temporary, logical, content)
            for relative, content in composition["assets"].items():
                logical = _safe_product_relative(relative)
                if logical in paths:
                    raise ProductGenerationError("product_file_duplicate")
                paths.add(logical)
                _write_product_file(temporary, logical, content)
            provenance = dict(composition["provenance"])
            provenance.update(
                {
                    "schema_version": "reweave_product_provenance.v1",
                    "product_id": product_id,
                    "generated_at": generated_at,
                    "source_project_write": False,
                    "runtime_network_access": False,
                }
            )
            _write_product_file(
                temporary,
                "provenance.json",
                json.dumps(
                    provenance,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                )
                + "\n",
            )
            _fsync_product_tree(temporary)
            quality = _validate_product_static(temporary)
            runtime = _validate_product_runtime(temporary)
            _write_product_file(
                temporary,
                "quality_gate.json",
                json.dumps(quality, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            )
            _write_product_file(
                temporary,
                "runtime_validation.json",
                json.dumps(runtime, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            )
            connections = composition.get("composition_manifest", {}).get("connections", [])
            if type(connections) is not list:
                raise ProductGenerationError("product_connections_invalid")
            inventory = []
            for path in sorted(
                item for item in temporary.rglob("*") if item.is_file() and not item.is_symlink()
            ):
                relative = path.relative_to(temporary).as_posix()
                inventory.append(
                    {
                        "path": relative,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "size_bytes": path.stat().st_size,
                    }
                )
            manifest = {
                "schema_version": PRODUCT_MANIFEST_VERSION,
                "product_id": product_id,
                "generated_at": generated_at,
                "task": task,
                "composer_version": str(composition.get("composer_version") or ""),
                "product_usage_scope": product_scope,
                "product_entry": {"path": "index.html", "kind": "static_html"},
                "capsules": self._manifest_capsules(capsules, connections),
                "connections": connections,
                "files": inventory,
            }
            manifest_bytes = _canonical_manifest_bytes(manifest)
            manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
            _write_product_file(temporary, "manifest.json", manifest_bytes)
            with self._capsule_store.read_connection() as connection:
                self._assert_generation_capsules_current(connection, capsules)
            _fsync_product_tree(temporary)
            if final.exists() or final.is_symlink():
                raise ProductGenerationError("product_id_collision")
            os.replace(temporary, final)
            promoted = True
            if os.name == "posix":
                descriptor = os.open(products, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            self._register_product_usage(manifest, manifest_digest, capsules)
            usage_registered = True
        except (OSError, sqlite3.Error) as exc:
            raise ProductGenerationError("product_commit_failed") from exc
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)
            if promoted and not usage_registered and final.exists():
                try:
                    with self._capsule_store.read_connection() as connection:
                        usage_count = int(
                            connection.execute(
                                "SELECT COUNT(*) FROM product_capsule_usage WHERE product_id = ?",
                                (product_id,),
                            ).fetchone()[0]
                        )
                except (CapsuleStoreError, OSError, sqlite3.Error):
                    usage_count = None
                if usage_count == 0:
                    shutil.rmtree(final, ignore_errors=True)
        files = [item["path"] for item in manifest["files"]] + ["manifest.json"]
        capsules_used = [
            {
                "id": row["capsule_id"],
                "capsule_id": row["capsule_id"],
                "version_id": row["version_id"],
                "name": f"{row['capability_key']} / {row['role_key']}",
                "type": row["capability_kind"],
            }
            for row in manifest["capsules"]
        ]
        task_pack = {
            "schema_version": "reweave_product_task.v1",
            "task": task,
            "selection_mode": "manual",
            "product_entry": manifest["product_entry"],
            "quality_gate": quality,
            "manifest_digest": manifest_digest,
        }
        return {
            "ok": True,
            "backend": "sqlite_capsule_warehouse",
            "mode": "formal_capsule_product",
            "productId": product_id,
            "manifestDigest": manifest_digest,
            "previewPath": str(final.resolve()),
            "productEntry": manifest["product_entry"],
            "generatedPackage": {
                "folder": f"{product_id}/",
                "files": files,
                "stats": {
                    "capsulesUsed": len(capsules_used),
                    "preview": "Formal capsule product",
                    "provenance": "Exact versions recorded",
                },
                "productEntry": manifest["product_entry"],
            },
            "capsulesUsed": capsules_used,
            "taskPack": task_pack,
            "provenance": provenance,
            "qualityGate": quality,
            "runtimeValidation": runtime,
            "previewAcceptance": {
                "verdict": "needs_review",
                "reason": "real_qwebengine_product_bootstrap",
            },
            "source_project_write": False,
            "runtime_network_access": False,
            "model_call": False,
            "network_call": False,
        }

    @staticmethod
    def _validate_manifest_shape(manifest: Any, product_id: str) -> None:
        if (
            type(manifest) is not dict
            or set(manifest)
            != {
                "schema_version",
                "product_id",
                "generated_at",
                "task",
                "composer_version",
                "product_usage_scope",
                "product_entry",
                "capsules",
                "connections",
                "files",
            }
            or manifest.get("schema_version") != PRODUCT_MANIFEST_VERSION
            or manifest.get("product_id") != product_id
            or manifest.get("product_entry")
            != {"path": "index.html", "kind": "static_html"}
            or type(manifest.get("generated_at")) is not str
            or not manifest["generated_at"]
            or type(manifest.get("task")) is not str
            or not manifest["task"]
            or type(manifest.get("composer_version")) is not str
            or not manifest["composer_version"]
            or type(manifest.get("product_usage_scope")) is not dict
            or type(manifest.get("capsules")) is not list
            or not manifest["capsules"]
            or type(manifest.get("connections")) is not list
            or type(manifest.get("files")) is not list
        ):
            raise ProductGenerationError("product_manifest_invalid")
        allowed = {"presentation", "interaction", "computation", "asset", "wiring"}
        seen_versions: set[str] = set()
        canonical_hash_mode: bool | None = None
        legacy_keys = {
            "capsule_id",
            "version_id",
            "capability_key",
            "role_key",
            "variant_key",
            "capability_kind",
            "usage_scope",
            "contributions",
        }
        for row in manifest["capsules"]:
            row_keys = set(row) if type(row) is dict else set()
            has_canonical_hash = row_keys == legacy_keys | {"canonical_hash"}
            if frozenset(row_keys) not in {
                frozenset(legacy_keys),
                frozenset(legacy_keys | {"canonical_hash"}),
            }:
                raise ProductGenerationError("product_manifest_capsule_invalid")
            if canonical_hash_mode is None:
                canonical_hash_mode = has_canonical_hash
            elif canonical_hash_mode != has_canonical_hash:
                raise ProductGenerationError("product_manifest_capsule_invalid")
            if (
                type(row) is not dict
                or type(row.get("contributions")) is not list
                or not row["contributions"]
                or row["contributions"] != sorted(set(row["contributions"]))
                or not set(row["contributions"]) <= allowed
                or row.get("capability_kind")
                not in {"presentation", "interaction", "computation"}
                or row["capability_kind"] not in row["contributions"]
                or any(
                    type(row.get(key)) is not str or not row[key]
                    for key in (
                        "capsule_id",
                        "version_id",
                        "capability_key",
                        "role_key",
                        "variant_key",
                    )
                )
                or (
                    has_canonical_hash
                    and _MANIFEST_DIGEST.fullmatch(
                        str(row.get("canonical_hash") or "")
                    )
                    is None
                )
                or type(row.get("usage_scope")) is not dict
                or row.get("version_id") in seen_versions
            ):
                raise ProductGenerationError("product_manifest_capsule_invalid")
            seen_versions.add(str(row["version_id"]))
        paths: set[str] = set()
        for row in manifest["files"]:
            if (
                type(row) is not dict
                or set(row) != {"path", "sha256", "size_bytes"}
                or _MANIFEST_DIGEST.fullmatch(str(row.get("sha256") or "")) is None
                or type(row.get("size_bytes")) is not int
                or row["size_bytes"] < 0
            ):
                raise ProductGenerationError("product_manifest_file_invalid")
            logical = _safe_product_relative(row["path"])
            if logical in paths or logical == "manifest.json":
                raise ProductGenerationError("product_manifest_file_invalid")
            paths.add(logical)

    def _read_product_record(self, directory: Path) -> dict[str, Any]:
        product_id = directory.name
        base = _product_directory().resolve()
        try:
            resolved = directory.resolve(strict=True)
            resolved.relative_to(base)
        except (OSError, ValueError) as exc:
            raise ProductGenerationError("product_directory_unsafe") from exc
        if (
            _PRODUCT_ID.fullmatch(product_id) is None
            or directory.is_symlink()
            or not resolved.is_dir()
        ):
            raise ProductGenerationError("product_directory_unsafe")
        manifest_path = resolved / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ProductGenerationError("product_manifest_missing")
        raw = manifest_path.read_bytes()
        if len(raw) > 1024 * 1024:
            raise ProductGenerationError("product_manifest_invalid")
        try:
            manifest = _strict_json_bytes(raw)
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ProductGenerationError("product_manifest_invalid") from exc
        self._validate_manifest_shape(manifest, product_id)
        if _canonical_manifest_bytes(manifest) != raw:
            raise ProductGenerationError("product_manifest_not_canonical")
        digest = hashlib.sha256(raw).hexdigest()
        expected_paths = {"manifest.json"}
        for row in manifest["files"]:
            path = resolved.joinpath(*PurePosixPath(row["path"]).parts)
            if path.is_symlink() or not path.is_file():
                raise ProductGenerationError("product_manifest_file_missing")
            content = path.read_bytes()
            if len(content) != row["size_bytes"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
                raise ProductGenerationError("product_manifest_file_mismatch")
            expected_paths.add(str(row["path"]))
        entries = list(resolved.rglob("*"))
        if any(path.is_symlink() for path in entries):
            raise ProductGenerationError("product_directory_symlink_forbidden")
        actual_paths = {
            path.relative_to(resolved).as_posix()
            for path in entries
            if path.is_file()
        }
        if actual_paths != expected_paths:
            raise ProductGenerationError("product_directory_file_set_mismatch")
        expected_usage = {
            (
                row["capsule_id"],
                row["version_id"],
                row["capability_key"],
                row["role_key"],
                row["variant_key"],
                json.dumps(
                    row["usage_scope"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                contribution,
                str(manifest["generated_at"]),
            )
            for row in manifest["capsules"]
            for contribution in row["contributions"]
        }
        usage_rows: list[sqlite3.Row] = []
        existing_versions: set[str] = set()
        if self._capsule_store.path.is_file():
            with self._capsule_store.read_connection() as connection:
                usage_rows = connection.execute(
                    "SELECT * FROM product_capsule_usage WHERE product_id = ?",
                    (product_id,),
                ).fetchall()
                placeholders = ",".join("?" for _ in manifest["capsules"])
                existing_versions = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT version_id FROM capsule_versions WHERE version_id IN ("
                        + placeholders
                        + ")",
                        tuple(row["version_id"] for row in manifest["capsules"]),
                    )
                }
        actual_usage = {
            (
                str(row["capsule_id"]),
                str(row["version_id"]),
                str(row["capability_key"]),
                str(row["role_key"]),
                str(row["variant_key"]),
                str(row["usage_scope_json"]),
                str(row["contribution_role"]),
                str(row["generated_at"]),
            )
            for row in usage_rows
        }
        digests = {str(row["manifest_digest"]) for row in usage_rows}
        if actual_usage == expected_usage and digests == {digest}:
            status = "registered"
        elif usage_rows:
            status = "product_usage_inconsistent"
        elif existing_versions != {str(row["version_id"]) for row in manifest["capsules"]}:
            status = "historical_version_unavailable_after_restore"
        else:
            status = "usage_registration_incomplete"
        return {
            "product_id": product_id,
            "path": resolved,
            "manifest_digest": digest,
            "manifest": manifest,
            "status": status,
        }

    def _product_records(self) -> list[dict[str, Any]]:
        root = _product_directory()
        if root.is_symlink() or not root.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for directory in root.iterdir():
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            try:
                records.append(self._read_product_record(directory))
            except (CapsuleStoreError, OSError, ProductGenerationError, sqlite3.Error):
                records.append(
                    {
                        "product_id": directory.name,
                        "path": directory,
                        "manifest": {},
                        "manifest_digest": "",
                        "status": "product_manifest_invalid",
                    }
                )
        return sorted(
            records,
            key=lambda item: str(item.get("manifest", {}).get("generated_at") or ""),
            reverse=True,
        )

    def _latest_pre_restore_backup_path(self) -> str | None:
        root = self._capsule_store.path.parent / BACKUP_DIRECTORY
        try:
            if root.is_symlink() or not root.is_dir():
                return None
            resolved_root = root.resolve(strict=True)
            candidates: list[Path] = []
            paths = list(root.glob("capsule_warehouse.pre_restore.*.sqlite3"))
            paths.extend(root.glob("capsule_warehouse.pre_restore.*.sqlite3.raw"))
            for path in paths:
                if path.is_symlink() or not path.is_file():
                    continue
                resolved = path.resolve(strict=True)
                resolved.relative_to(resolved_root)
                candidates.append(resolved)
            if not candidates:
                return None
            return str(max(candidates, key=lambda path: path.stat().st_mtime_ns))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _generated_package(record: dict[str, Any]) -> dict[str, Any]:
        manifest = record["manifest"]
        return {
            "folder": f"{record['product_id']}/",
            "files": [item["path"] for item in manifest["files"]] + ["manifest.json"],
            "stats": {
                "capsulesUsed": len(manifest["capsules"]),
                "preview": "Formal capsule product",
                "provenance": "Exact versions recorded",
            },
            "productEntry": manifest["product_entry"],
            "mode": "formal_capsule_product",
        }

    @staticmethod
    def _product_history_item(record: dict[str, Any]) -> dict[str, Any]:
        manifest = record["manifest"]
        return {
            "id": record["product_id"],
            "title": str(manifest["task"]),
            "created_at": str(manifest["generated_at"]),
            "capsulesUsed": len(manifest["capsules"]),
            "note": "Formal capsule product",
        }

    def _assert_recoverable_product_matches_composition(
        self,
        record: dict[str, Any],
        capsules: list[dict[str, Any]],
        product_scope: dict[str, Any],
        page_contracts: list[dict[str, Any]],
    ) -> None:
        manifest = record["manifest"]
        try:
            composition = compose_capsule_product(
                task=manifest["task"],
                product_id=manifest["product_id"],
                generated_at=manifest["generated_at"],
                capsules=capsules,
                verified_page_contracts=page_contracts,
            )
        except ValueError as exc:
            raise ProductGenerationError("formal_capsule_selection_expired") from exc
        composition_manifest = composition.get("composition_manifest")
        expected_connections = (
            composition_manifest.get("connections")
            if type(composition_manifest) is dict
            else None
        )
        if type(expected_connections) is not list:
            raise ProductGenerationError("formal_capsule_selection_expired")
        include_canonical_hash = all(
            type(row) is dict and "canonical_hash" in row
            for row in manifest["capsules"]
        )
        expected_capsules = self._manifest_capsules(
            capsules,
            expected_connections,
            include_canonical_hash=include_canonical_hash,
        )
        if (
            manifest["product_usage_scope"] != product_scope
            or manifest["composer_version"] != composition.get("composer_version")
            or manifest["connections"] != expected_connections
            or manifest["capsules"] != expected_capsules
        ):
            raise ProductGenerationError("formal_capsule_selection_expired")

        files = composition.get("files")
        assets = composition.get("assets")
        provenance = composition.get("provenance")
        if type(files) is not dict or type(assets) is not dict or type(provenance) is not dict:
            raise ProductGenerationError("formal_capsule_selection_expired")
        expected_bytes: dict[str, bytes] = {}
        for relative, content in {**files, **assets}.items():
            logical = _safe_product_relative(relative)
            data = content.encode("utf-8") if type(content) is str else content
            if type(data) is not bytes or logical in expected_bytes:
                raise ProductGenerationError("formal_capsule_selection_expired")
            expected_bytes[logical] = data
        expected_provenance = dict(provenance)
        expected_provenance.update(
            {
                "schema_version": "reweave_product_provenance.v1",
                "product_id": manifest["product_id"],
                "generated_at": manifest["generated_at"],
                "source_project_write": False,
                "runtime_network_access": False,
            }
        )
        expected_bytes["provenance.json"] = (
            json.dumps(
                expected_provenance,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        expected_paths = set(expected_bytes) | {
            "quality_gate.json",
            "runtime_validation.json",
        }
        if {str(row["path"]) for row in manifest["files"]} != expected_paths:
            raise ProductGenerationError("formal_capsule_selection_expired")
        product_root = Path(record["path"])
        for logical, expected in expected_bytes.items():
            target = product_root.joinpath(*PurePosixPath(logical).parts)
            if target.is_symlink() or not target.is_file() or target.read_bytes() != expected:
                raise ProductGenerationError("formal_capsule_selection_expired")

    @_serialized_management
    def retry_product_usage_registration(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            product_id = str(request.get("product_id") or "")
            if _PRODUCT_ID.fullmatch(product_id) is None:
                return self._error("product_id_invalid")
            record = self._read_product_record(_product_directory() / product_id)
            if record["status"] == "registered":
                return self._ok({"product_id": product_id, "status": "registered"})
            if record["status"] != "usage_registration_incomplete":
                return self._error(str(record["status"]))
            capsule_ids = [str(row["capsule_id"]) for row in record["manifest"]["capsules"]]
            capsules, product_scope, page_contracts = (
                self._load_composer_capsules(capsule_ids)
            )
            product_root = Path(record["path"])
            for filename, validator in (
                ("quality_gate.json", _validate_product_static),
                ("runtime_validation.json", _validate_product_runtime),
            ):
                expected = (
                    json.dumps(
                        validator(product_root),
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                        allow_nan=False,
                    )
                    + "\n"
                ).encode("utf-8")
                receipt = product_root / filename
                if (
                    receipt.is_symlink()
                    or not receipt.is_file()
                    or receipt.read_bytes() != expected
                ):
                    raise ProductGenerationError(
                        "product_validation_receipt_mismatch"
                    )
            self._assert_recoverable_product_matches_composition(
                record, capsules, product_scope, page_contracts
            )
            self._register_product_usage(
                record["manifest"], record["manifest_digest"], capsules
            )
            confirmed = self._read_product_record(_product_directory() / product_id)
            if confirmed["status"] != "registered":
                return self._error("product_usage_registration_incomplete")
            return self._ok({"product_id": product_id, "status": "registered"})
        except (
            CapsuleStoreError,
            OSError,
            ProductGenerationError,
            sqlite3.Error,
            ValueError,
        ) as exc:
            return self._exception_error(exc, "product_usage_registration_failed")

    def get_latest_product_entry_path(self) -> str | None:
        for record in self._product_records():
            if record["status"] != "registered":
                continue
            candidate = Path(record["path"]) / "index.html"
            if candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(_product_directory().resolve())
            except (OSError, ValueError):
                continue
            return str(resolved)
        return None

    def generate_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        return self._error("legacy_generation_inactive")

    def _generate_preview_lumo(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Local preview first, then optional Luna index-pack provenance (no dispatch)."""
        local = LocalReweaveEngine()
        local_payload = dict(payload)
        local_payload["backend"] = "lumo"

        try:
            local_result = local.generate_preview(local_payload)
        except Exception as exc:
            return {
                "ok": False,
                "engine": "lumo",
                "mode": "pack_only",
                "error": str(exc)[:200],
            }

        if not local_result.get("ok"):
            return local_result

        preview_path = local_result.get("previewPath")
        pack_payload = dict(payload)
        pack_payload["_localPreview"] = local_result
        luna_result = self._engine.generate_preview(pack_payload)

        merged = dict(local_result)
        merged["engine"] = "lumo"
        merged["mode"] = "pack_only"
        merged["dispatch"] = False

        if luna_result.get("ok"):
            luna_record = build_luna_provenance_record(luna_result, success=True)
            if preview_path:
                merged["provenance"] = attach_luna_provenance(preview_path, luna_record)
            merged["lunaPack"] = luna_result.get("lunaPack")
            merged["warnings"] = list(luna_result.get("warnings") or [])
            if not merged["warnings"]:
                merged["warnings"] = ["pack_only — no dispatch or LLM generation"]
            if merged.get("generatedPackage") and isinstance(merged["generatedPackage"].get("stats"), dict):
                merged["generatedPackage"]["stats"]["lunaPack"] = (
                    (merged.get("lunaPack") or {}).get("pack_id") or "indexed"
                )
            return merged

        luna_record = build_luna_provenance_record(luna_result, success=False)
        if preview_path:
            try:
                merged["provenance"] = attach_luna_provenance(preview_path, luna_record)
            except (FileNotFoundError, ValueError):
                pass
        merged["warnings"] = ["luna_index_pack_failed"]
        merged["lunaPack"] = None
        merged["lunaIndexError"] = luna_result.get("error")
        return merged

    def _draft_source_lumo(self, source_id: str) -> dict[str, Any]:
        """Local draft first, then Luna reuse-pack suggestions (never warehouse)."""
        local = LocalReweaveEngine()
        try:
            local_draft = local.draft_source(source_id)
        except Exception:
            raise

        merged = dict(local_draft)
        merged["engine"] = "lumo"
        merged["mode"] = "local_plus_luna_reuse_pack"
        merged["warnings"] = []

        if not self._is_lumo():
            return merged

        luna_result = self._engine.prepare_reuse_pack({"source_id": source_id, "_localDraft": local_draft})
        if luna_result.get("ok"):
            suggestions = list(luna_result.get("capsuleSuggestions") or [])
            merged["capsuleSuggestions"] = suggestions
            merged["lunaReuse"] = {
                "assets_count": luna_result.get("assets_count", 0),
                "endpoint": luna_result.get("endpoint"),
            }
            reuse_result = luna_result.get("reuseResult") if isinstance(luna_result.get("reuseResult"), dict) else {}
            query_payload = luna_result.get("reuseRequest") if isinstance(luna_result.get("reuseRequest"), dict) else {}
            record = build_reuse_suggestions_record(
                source_id,
                query_payload=query_payload,
                reuse_result=reuse_result,
                capsule_suggestions=suggestions,
                warnings=[],
                luna_ok=True,
            )
            save_reuse_suggestions(source_id, record)
            return merged

        merged["warnings"] = ["luna_reuse_pack_failed"]
        merged["lunaReuseError"] = luna_result.get("error")
        query_payload = {}
        if isinstance(luna_result.get("reuseRequest"), dict):
            query_payload = luna_result["reuseRequest"]
        record = build_reuse_suggestions_record(
            source_id,
            query_payload=query_payload,
            reuse_result={"ok": False, "error": luna_result.get("error"), "assets": []},
            capsule_suggestions=[],
            warnings=["luna_reuse_pack_failed"],
            luna_ok=False,
        )
        save_reuse_suggestions(source_id, record)
        return merged
