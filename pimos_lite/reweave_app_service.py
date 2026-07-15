"""Reweave app service — consistent initial state + engine delegation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from functools import wraps
from html.parser import HTMLParser
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Any

from pimos_lite.composer.module_native import compose_capsule_product
from pimos_lite.reweave_capsule_intake import (
    EXTRACTION_CONTRACT_VERSION,
    REDACTION_RULES_VERSION,
    IntakeError,
    ReweaveCapsuleIntake,
)
from pimos_lite.reweave_capsule_stage3 import (
    OllamaSupervisor,
    ReweaveCapsuleStage3,
    SECURITY_RULES_VERSION,
    Stage3Error,
    SUPERVISION_RULES_VERSION,
    VALIDATION_CONTRACT_VERSION,
)
from pimos_lite.reweave_capsule_store import (
    BACKUP_DIRECTORY,
    CANONICALIZATION_VERSION,
    CapsuleStoreError,
    CapsuleWarehouseStore,
    canonicalize_capsule,
)
from pimos_lite.reweave_process_environment import restricted_subprocess_environment
from pimos_lite.reweave_source_registry import state_dir

APP_SERVICE_VERSION = "v2"
LUMO_LITE_MODE = "source_read_only_preview_write"
PRODUCT_MANIFEST_VERSION = "reweave_product_manifest.v1"
PRODUCTS_DIRNAME = "products"
_PRODUCT_ID = re.compile(r"product_[0-9a-f]{32}\Z")
_MANIFEST_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
PUBLIC_PRODUCT_ACTIONS = frozenset(
    {
        "get_initial_state",
        "generate_product",
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
                {"mode": "qweb", "entry": "index.html", "allow_files": allowed},
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
        self._capsule_intake = ReweaveCapsuleIntake(self._capsule_store)
        self._capsule_supervisor = OllamaSupervisor(self._capsule_store)
        self._capsule_stage3 = ReweaveCapsuleStage3(
            self._capsule_store,
            intake=self._capsule_intake,
            supervisor=self._capsule_supervisor,
        )
        self._ollama_base_url = ollama_base_url
        self._management_lock = threading.RLock()
        self._capsule_operation_lock = threading.RLock()
        self._management_executor: ThreadPoolExecutor | None = None
        self._management_tasks: dict[str, dict[str, Any]] = {}
        self._restore_pending = False
        self._management_closed = False
        self._management_recovered = False
        self._management_rules_checked = False

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
            "canOpenPreviewFolder": False,
            "sourceBoxes": [],
            "capsules": capsules,
            "warehouseCapsules": capsules,
            "useLocalCapsules": bool(capsules),
            "history": [self._product_history_item(item) for item in registered],
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

    def close(self) -> None:
        with self._management_lock:
            if self._management_closed:
                return
            self._management_closed = True
            for task in self._management_tasks.values():
                task["cancel_event"].set()
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
        comparison = item.get("comparison") or {}
        current_status = str(item.get("candidate_status") or "")
        allowed: list[str] = []
        if current_status in {
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
                    [
                        "confirm_fictional_fixture",
                        "confirm_safe_redaction",
                        "confirm_real_record_reject",
                    ]
                )
            if item.get("brand_decision") is None and (
                "brand_confirmation_required" in codes
                or failure_code == "brand_confirmation_required"
            ):
                allowed.extend(["remove_brand", "retain_brand_limited"])
            if item.get("asset_decision") is None and (
                failure_code == "asset_content_confirmation_required_stage3"
            ):
                allowed.append("confirm_assets_contain_no_real_records")
        if current_status == "review_required":
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
        now = _now()
        with self._capsule_store.transaction() as connection:
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
            for row in rows:
                connection.execute(
                    "UPDATE capsules SET status = 'pending_revalidation' "
                    "WHERE capsule_id = ? AND status = 'active'",
                    (row["capsule_id"],),
                )
                connection.execute(
                    "INSERT INTO capsule_status_events VALUES (?, ?, "
                    "'revalidation_required', 'active', 'pending_revalidation', ?, ?, ?)",
                    (
                        f"evt_{uuid.uuid4().hex}",
                        row["capsule_id"],
                        row["current_version_id"],
                        "rule_version_changed",
                        now,
                    ),
                )
            if rows:
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
        restore: bool = False,
        cancellable: bool = False,
    ) -> dict[str, Any]:
        if not restore:
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
            task_id = f"run_{uuid.uuid4().hex}"
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
                "cancellable": cancellable,
                "cancel_event": cancel_event,
                "future": None,
            }
            self._management_tasks[task_id] = task

            def run() -> None:
                try:
                    if cancel_event.is_set() and cancellable:
                        task["status"] = "cancelled"
                        return
                    task["status"] = "running"
                    task["started_at"] = _now()
                    with self._capsule_operation_lock:
                        task["data"] = action(cancel_event)
                    action_status = (
                        task["data"].get("status")
                        if type(task["data"]) is dict
                        else None
                    )
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
                        and error_code in {"intake_cancelled", "cancelled_by_user"}
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
            with self._management_lock:
                task = self._management_tasks.get(run_id)
                if task is not None:
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
        except (CapsuleStoreError, OSError, ValueError) as exc:
            return self._exception_error(exc, "get_intake_run_failed")

    def cancel_intake_run(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            request = self._payload(payload)
            run_id = str(request.get("run_id") or "").strip()
            if not run_id:
                return self._error("run_id_required")
            with self._management_lock:
                task = self._management_tasks.get(run_id)
                if task is None:
                    return self._error("intake_run_not_cancellable")
                if not task["cancellable"]:
                    return self._error("intake_run_not_cancellable")
                if task["status"] in _TERMINAL_TASK_STATES:
                    return self._error("intake_run_already_terminal")
                task["cancel_event"].set()
            return self._ok({"run_id": run_id, "cancel_requested": True})
        except ValueError as exc:
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
                if not status and not item["allowed_decisions"]:
                    continue
                items.append(item)
            return self._ok({"items": items})
        except (CapsuleStoreError, OSError, ValueError, sqlite3.Error) as exc:
            return self._exception_error(exc, "list_review_items_failed")

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
            if decision not in item["allowed_decisions"]:
                return self._error("review_decision_not_allowed")
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
        self, capsule_ids: list[str]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
                if canonical.sha256 != row["canonical_hash"]:
                    raise ProductGenerationError("formal_capsule_canonical_mismatch")
                loaded.append(
                    {
                        "capsule_id": capsule_id,
                        "version_id": str(row["version_id"]),
                        "capability_key": str(row["capability_key"]),
                        "role_key": str(row["role_key"]),
                        "variant_key": str(row["variant_key"]),
                        "capability_kind": str(row["capability_kind"]),
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
                )
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
        capsules: list[dict[str, Any]], connections: list[dict[str, Any]]
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
            result.append(
                {
                    "capsule_id": capsule["capsule_id"],
                    "version_id": capsule["version_id"],
                    "capability_key": capsule["capability_key"],
                    "role_key": capsule["role_key"],
                    "variant_key": capsule["variant_key"],
                    "capability_kind": capsule["capability_kind"],
                    "usage_scope": capsule["usage_scope"],
                    "contributions": sorted(contributions),
                }
            )
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
        capsules, product_scope = self._load_generation_capsules(capsule_ids)
        product_id = f"product_{uuid.uuid4().hex}"
        generated_at = _now()
        try:
            composition = compose_capsule_product(
                task=task,
                product_id=product_id,
                generated_at=generated_at,
                capsules=capsules,
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
        for row in manifest["capsules"]:
            if (
                type(row) is not dict
                or set(row)
                != {
                    "capsule_id",
                    "version_id",
                    "capability_key",
                    "role_key",
                    "variant_key",
                    "capability_kind",
                    "usage_scope",
                    "contributions",
                }
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
    ) -> None:
        manifest = record["manifest"]
        try:
            composition = compose_capsule_product(
                task=manifest["task"],
                product_id=manifest["product_id"],
                generated_at=manifest["generated_at"],
                capsules=capsules,
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
        expected_capsules = self._manifest_capsules(capsules, expected_connections)
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
            capsules, product_scope = self._load_generation_capsules(capsule_ids)
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
                record, capsules, product_scope
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
