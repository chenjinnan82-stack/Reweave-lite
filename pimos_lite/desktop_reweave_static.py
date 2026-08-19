#!/usr/bin/env python3
"""Reweave desktop shell — PySide6 + QWebChannel + local engine."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
REWEAVE_DIR = REPO_ROOT / "reweave_frontend"
REWEAVE_INDEX = REWEAVE_DIR / "index.html"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pimos_lite.reweave_app_service import ReweaveAppService  # noqa: E402

WINDOW_TITLE = "Reweave"
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 820
MIN_WIDTH = 1100
MIN_HEIGHT = 720

logger = logging.getLogger("reweave.desktop")


def _copy_to_system_clipboard(value: str) -> None:
    from PySide6.QtGui import QGuiApplication

    application = QGuiApplication.instance()
    if application is None:
        raise RuntimeError("clipboard_application_unavailable")
    clipboard = application.clipboard()
    try:
        clipboard.setText(value)
        if clipboard.text() != value:
            raise RuntimeError("clipboard_write_mismatch")
    except BaseException:
        try:
            clipboard.clear()
        except BaseException:
            pass
        raise


def reweave_index_path() -> Path:
    return REWEAVE_INDEX.resolve()


def ensure_reweave_assets() -> Path:
    index = reweave_index_path()
    if not index.is_file():
        raise FileNotFoundError(f"Missing Reweave entry: {index}")
    for name in ("styles.css", "app.js"):
        path = REWEAVE_DIR / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing Reweave asset: {path}")
    return index


def _is_frontend_file(path: str) -> bool:
    try:
        root = REWEAVE_DIR.resolve(strict=True)
        candidate = Path(path)
        candidate.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        return False
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink() or cursor.parent == cursor:
            return False
        cursor = cursor.parent
    return True


def _is_preview_image(path: str) -> bool:
    from pimos_lite.reweave_preview_pack import preview_packages_dir

    candidate = Path(path)
    if candidate.suffix.lower() != ".png":
        return False
    try:
        root = preview_packages_dir().resolve()
        candidate.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        return False
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink() or cursor.parent == cursor:
            return False
        cursor = cursor.parent
    return True


def import_qt_webengine():
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError as exc:
        raise SystemExit(
            "PySide6 with QtWebEngine is required.\n"
            "Install example: pip install pyside6 pyside6-addons\n"
            f"Import error: {exc}"
        ) from exc
    return QApplication, QMainWindow, QWebEngineView, QWebEngineSettings, QUrl, QFileDialog


def import_qt_bridge():
    try:
        from PySide6.QtCore import QObject, Slot
        from PySide6.QtWebChannel import QWebChannel
    except ImportError as exc:
        raise SystemExit(
            "PySide6 QtWebChannel is required.\n"
            "Install example: pip install pyside6 pyside6-addons\n"
            f"Import error: {exc}"
        ) from exc
    return QObject, Slot, QWebChannel


def locate_qwebchannel_js() -> Path | None:
    try:
        import PySide6
    except ImportError:
        return None
    root = Path(PySide6.__file__).resolve().parent
    for rel in ("Qt/qml/QtWebChannel/qwebchannel.js", "qml/QtWebChannel/qwebchannel.js"):
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


class ReweaveBridge:
    """QWebChannel bridge backed by ReweaveEngine facade."""

    _qobject_cls: Any = None

    @classmethod
    def _ensure_qt_base(cls):
        if cls._qobject_cls is not None:
            return cls._qobject_cls

        QObject, Slot, _ = import_qt_bridge()

        class _BridgeImpl(QObject):
            def __init__(self, engine: Any, parent=None):
                super().__init__(parent)
                self._engine = engine
                self._parent_widget = parent
                self._candidate_preview_windows: list[Any] = []

            @staticmethod
            def _phase4_error(code: str, message_key: str) -> str:
                return json.dumps(
                    {"ok": False, "error": {"code": code, "message_key": message_key}}
                )

            def _phase4_call(self, method_name: str, payload_json: str = "") -> str:
                try:
                    payload = json.loads(payload_json) if payload_json else {}
                except json.JSONDecodeError:
                    return self._phase4_error("invalid_payload", "invalidPayload")
                if not isinstance(payload, dict):
                    return self._phase4_error("invalid_payload", "invalidPayload")
                method = getattr(self._engine, method_name, None)
                if not callable(method):
                    return self._phase4_error("service_unavailable", "serviceUnavailable")
                try:
                    return json.dumps(method(payload))
                except Exception:
                    # Never reflect exception text: it may contain a local path or source content.
                    logger.error("Phase 4 bridge call failed: %s", method_name)
                    return self._phase4_error("internal_error", "internalError")

            def _lumo_lite_block(self, action: str) -> dict[str, Any] | None:
                if action in {
                    "enrich_capsule_content",
                    "get_capsule_content",
                    "get_latest_preview_package",
                    "get_preview_package",
                    "compare_preview_packages",
                    "open_generated_product",
                }:
                    return None
                state = self._engine.get_initial_state()
                if state.get("backend") == "lumo_lite" or state.get("engine") == "lumo_lite":
                    return {"ok": False, "error": "lumo_lite_read_only", "action": action}
                return None

            @Slot(result=str)
            def get_initial_state(self) -> str:
                return json.dumps(self._engine.get_initial_state())

            @Slot(result=str)
            def choose_source_root(self) -> str:
                try:
                    _, _, _, _, _, QFileDialog = import_qt_webengine()
                    path = QFileDialog.getExistingDirectory(
                        self._parent_widget, "Select source root"
                    )
                except Exception:
                    logger.error("Phase 4 source root chooser failed")
                    return self._phase4_error("internal_error", "internalError")
                if not path:
                    return json.dumps({"ok": False, "cancelled": True})
                return self._phase4_call(
                    "discover_source_root",
                    json.dumps({"path": path, "root_kind": "project_collection"}),
                )

            @Slot(result=str)
            def choose_static_web_target(self) -> str:
                try:
                    _, _, _, _, _, QFileDialog = import_qt_webengine()
                    path = QFileDialog.getExistingDirectory(
                        self._parent_widget, "Select Static Web target"
                    )
                except Exception:
                    logger.error("Static Web target chooser failed")
                    return self._phase4_error("internal_error", "internalError")
                if not path:
                    return json.dumps({"ok": False, "cancelled": True})
                return json.dumps(
                    {
                        "ok": True,
                        "target_path": path,
                        "display_name": Path(path).name or "Static Web target",
                    }
                )

            @Slot(str, result=str)
            def discover_source_root(self, payload_json: str = "") -> str:
                return self._phase4_call("discover_source_root", payload_json)

            @Slot(str, result=str)
            def confirm_projects(self, payload_json: str = "") -> str:
                return self._phase4_call("confirm_projects", payload_json)

            @Slot(str, result=str)
            def register_javascript_computation_source(
                self, payload_json: str = ""
            ) -> str:
                return self._phase4_call(
                    "register_javascript_computation_source", payload_json
                )

            @Slot(str, result=str)
            def start_scan_javascript_computations(
                self, payload_json: str = ""
            ) -> str:
                return self._phase4_call(
                    "start_scan_javascript_computations", payload_json
                )

            @Slot(str, result=str)
            def start_inspect_computation_adapters(self, payload_json: str = "") -> str:
                return self._phase4_call(
                    "start_inspect_computation_adapters", payload_json
                )

            @Slot(str, result=str)
            def start_create_computation_adapter(self, payload_json: str = "") -> str:
                return self._phase4_call(
                    "start_create_computation_adapter", payload_json
                )

            @Slot(str, result=str)
            def start_refresh_project(self, payload_json: str = "") -> str:
                return self._phase4_call("start_refresh_project", payload_json)

            @Slot(str, result=str)
            def start_refresh_all(self, payload_json: str = "") -> str:
                return self._phase4_call("start_refresh_all", payload_json)

            @Slot(str, result=str)
            def authorize_and_start_source_derived_computation(
                self, payload_json: str = ""
            ) -> str:
                return self._phase4_call(
                    "authorize_and_start_source_derived_computation",
                    payload_json,
                )

            @Slot(str, result=str)
            def get_intake_run(self, payload_json: str = "") -> str:
                return self._phase4_call("get_intake_run", payload_json)

            @Slot(str, result=str)
            def cancel_intake_run(self, payload_json: str = "") -> str:
                return self._phase4_call("cancel_intake_run", payload_json)

            @Slot(str, result=str)
            def list_supervision_models(self, payload_json: str = "") -> str:
                return self._phase4_call("list_supervision_models", payload_json)

            @Slot(str, result=str)
            def select_supervision_model(self, payload_json: str = "") -> str:
                return self._phase4_call("select_supervision_model", payload_json)

            @Slot(str, result=str)
            def list_product_planning_models(self, payload_json: str = "") -> str:
                return self._phase4_call(
                    "list_product_planning_models", payload_json
                )

            @Slot(str, result=str)
            def select_product_planning_model(self, payload_json: str = "") -> str:
                return self._phase4_call(
                    "select_product_planning_model", payload_json
                )

            @Slot(str, result=str)
            def start_product_plan(self, payload_json: str = "") -> str:
                return self._phase4_call("start_product_plan", payload_json)

            @Slot(str, result=str)
            def start_product_capability_replan(
                self, payload_json: str = ""
            ) -> str:
                return self._phase4_call(
                    "start_product_capability_replan", payload_json
                )

            @Slot(str, result=str)
            def submit_product_plan_answers(self, payload_json: str = "") -> str:
                return self._phase4_call(
                    "submit_product_plan_answers", payload_json
                )

            @Slot(str, result=str)
            def suggest_product_plan_action(self, payload_json: str = "") -> str:
                return self._phase4_call(
                    "suggest_product_plan_action", payload_json
                )

            @Slot(str, result=str)
            def revise_product_plan(self, payload_json: str = "") -> str:
                return self._phase4_call("revise_product_plan", payload_json)

            @Slot(str, result=str)
            def get_product_plan_run(self, payload_json: str = "") -> str:
                return self._phase4_call("get_product_plan_run", payload_json)

            @Slot(str, result=str)
            def cancel_product_plan_run(self, payload_json: str = "") -> str:
                return self._phase4_call("cancel_product_plan_run", payload_json)

            @Slot(str, result=str)
            def get_product_plan_workspace(self, payload_json: str = "") -> str:
                return self._phase4_call(
                    "get_product_plan_workspace", payload_json
                )

            @Slot(str, result=str)
            def confirm_product_plan(self, payload_json: str = "") -> str:
                return self._phase4_call("confirm_product_plan", payload_json)

            @Slot(str, result=str)
            def record_product_capability_gap_decision(
                self, payload_json: str = ""
            ) -> str:
                return self._phase4_call(
                    "record_product_capability_gap_decision",
                    payload_json,
                )

            @Slot(str, result=str)
            def prepare_product_capability_source_proposal(
                self, payload_json: str = ""
            ) -> str:
                return self._phase4_call(
                    "prepare_product_capability_source_proposal",
                    payload_json,
                )

            @Slot(str, result=str)
            def start_product_capability_source_proposal(
                self, payload_json: str = ""
            ) -> str:
                return self._phase4_call(
                    "start_product_capability_source_proposal",
                    payload_json,
                )

            @Slot(str, result=str)
            def confirm_product_candidate_acceptance(
                self, payload_json: str = ""
            ) -> str:
                return self._phase4_call(
                    "confirm_product_candidate_acceptance", payload_json
                )

            @Slot(str, result=str)
            def copy_local_agent_handoff_binding(
                self, payload_json: str = ""
            ) -> str:
                try:
                    payload = json.loads(payload_json) if payload_json else {}
                except json.JSONDecodeError:
                    return self._phase4_error(
                        "invalid_payload",
                        "invalidPayload",
                    )
                if (
                    type(payload) is not dict
                    or set(payload) != {"plan_token"}
                    or type(payload["plan_token"]) is not str
                ):
                    return self._phase4_error(
                        "agent_handoff_request_invalid",
                        "agent_handoff_request_invalid",
                    )
                method = getattr(
                    self._engine,
                    "create_local_agent_handoff",
                    None,
                )
                revoke = getattr(
                    self._engine,
                    "revoke_local_agent_handoff",
                    None,
                )
                if not callable(method) or not callable(revoke):
                    return self._phase4_error(
                        "service_unavailable",
                        "serviceUnavailable",
                    )
                result = method(payload)
                if type(result) is not dict:
                    return self._phase4_error(
                        "internal_error",
                        "internalError",
                    )
                data = result.get("data") if type(result) is dict else None
                token = (
                    data.get("handoff_token")
                    if type(data) is dict
                    else None
                )
                if (
                    result.get("ok") is not True
                    or type(token) is not str
                    or re.fullmatch(
                        r"handoff_token_[0-9a-f]{48}",
                        token,
                    )
                    is None
                ):
                    if result.get("ok") is True:
                        try:
                            revoke({"plan_token": payload["plan_token"]})
                        except BaseException:
                            pass
                        return self._phase4_error(
                            "internal_error",
                            "internalError",
                        )
                    return json.dumps(result)
                request_line = json.dumps(
                    {
                        "protocol": "reweave_agent_jsonl.v2",
                        "id": "bind-user-handoff",
                        "action": "bind_user_handoff",
                        "payload": {"handoff_token": token},
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                try:
                    _copy_to_system_clipboard(request_line)
                except BaseException:
                    try:
                        revoke({"plan_token": payload["plan_token"]})
                    except BaseException:
                        pass
                    return self._phase4_error(
                        "agent_handoff_clipboard_failed",
                        "agent_handoff_clipboard_failed",
                    )
                return json.dumps(
                    {
                        "ok": True,
                        "data": {
                            "status": "active",
                            "created_at": data.get("created_at"),
                        },
                    }
                )

            @Slot(str, result=str)
            def revoke_local_agent_handoff(
                self, payload_json: str = ""
            ) -> str:
                return self._phase4_call(
                    "revoke_local_agent_handoff", payload_json
                )

            @Slot(str, result=str)
            def copy_local_source_handoff_binding(
                self, payload_json: str = ""
            ) -> str:
                try:
                    payload = json.loads(payload_json) if payload_json else {}
                except json.JSONDecodeError:
                    return self._phase4_error(
                        "invalid_payload",
                        "invalidPayload",
                    )
                if (
                    type(payload) is not dict
                    or set(payload) != {"project_id"}
                    or type(payload["project_id"]) is not str
                    or not payload["project_id"].strip()
                ):
                    return self._phase4_error(
                        "source_handoff_request_invalid",
                        "source_handoff_request_invalid",
                    )
                method = getattr(
                    self._engine,
                    "create_local_source_handoff",
                    None,
                )
                revoke = getattr(
                    self._engine,
                    "revoke_local_source_handoff",
                    None,
                )
                if not callable(method) or not callable(revoke):
                    return self._phase4_error(
                        "service_unavailable",
                        "serviceUnavailable",
                    )

                def revoke_after_failure() -> bool:
                    try:
                        revoked = revoke(
                            {"project_id": payload["project_id"]}
                        )
                    except BaseException:
                        return False
                    revoked_data = (
                        revoked.get("data")
                        if type(revoked) is dict
                        else None
                    )
                    return (
                        type(revoked) is dict
                        and revoked.get("ok") is True
                        and type(revoked_data) is dict
                        and revoked_data.get("status")
                        in {"revoked", "none"}
                    )

                result = method(payload)
                if type(result) is not dict:
                    return self._phase4_error(
                        "internal_error",
                        "internalError",
                    )
                data = result.get("data") if type(result) is dict else None
                token = (
                    data.get("source_handoff_token")
                    if type(data) is dict
                    else None
                )
                if (
                    result.get("ok") is not True
                    or type(token) is not str
                    or re.fullmatch(
                        r"source_handoff_token_[0-9a-f]{48}",
                        token,
                    )
                    is None
                ):
                    if result.get("ok") is True:
                        if not revoke_after_failure():
                            return self._phase4_error(
                                "source_handoff_clipboard_revoke_failed",
                                "source_handoff_clipboard_revoke_failed",
                            )
                        return self._phase4_error(
                            "internal_error",
                            "internalError",
                        )
                    return json.dumps(result)
                request_line = json.dumps(
                    {
                        "protocol": "reweave_agent_jsonl.v2",
                        "id": "bind-user-handoff",
                        "action": "bind_user_handoff",
                        "payload": {"handoff_token": token},
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                try:
                    _copy_to_system_clipboard(request_line)
                except BaseException:
                    if not revoke_after_failure():
                        return self._phase4_error(
                            "source_handoff_clipboard_revoke_failed",
                            "source_handoff_clipboard_revoke_failed",
                        )
                    return self._phase4_error(
                        "source_handoff_clipboard_failed",
                        "source_handoff_clipboard_failed",
                    )
                return json.dumps(
                    {
                        "ok": True,
                        "data": {
                            "schema_version": "source_handoff_status.v1",
                            "status": "active",
                            "created_at": data.get("created_at"),
                        },
                    }
                )

            @Slot(str, result=str)
            def revoke_local_source_handoff(
                self, payload_json: str = ""
            ) -> str:
                return self._phase4_call(
                    "revoke_local_source_handoff", payload_json
                )

            @Slot(str, result=str)
            def copy_local_source_derived_handoff_binding(
                self, payload_json: str = ""
            ) -> str:
                try:
                    payload = (
                        json.loads(payload_json) if payload_json else {}
                    )
                except json.JSONDecodeError:
                    return self._phase4_error(
                        "invalid_payload", "invalidPayload"
                    )
                if (
                    type(payload) is not dict
                    or set(payload) != {"source_root_id"}
                    or type(payload["source_root_id"]) is not str
                    or not payload["source_root_id"].strip()
                ):
                    return self._phase4_error(
                        "source_derived_handoff_request_invalid",
                        "source_derived_handoff_request_invalid",
                    )
                create = getattr(
                    self._engine,
                    "create_local_source_derived_handoff",
                    None,
                )
                revoke = getattr(
                    self._engine,
                    "revoke_local_source_derived_handoff",
                    None,
                )
                if not callable(create) or not callable(revoke):
                    return self._phase4_error(
                        "service_unavailable", "serviceUnavailable"
                    )

                def revoke_after_failure() -> bool:
                    try:
                        result = revoke(payload)
                    except BaseException:
                        return False
                    data = (
                        result.get("data")
                        if type(result) is dict
                        else None
                    )
                    return (
                        type(result) is dict
                        and result.get("ok") is True
                        and type(data) is dict
                        and data.get("status") in {"revoked", "none"}
                    )

                result = create(payload)
                data = (
                    result.get("data")
                    if type(result) is dict
                    else None
                )
                token = (
                    data.get("source_derived_handoff_token")
                    if type(data) is dict
                    else None
                )
                if (
                    type(result) is not dict
                    or result.get("ok") is not True
                    or type(token) is not str
                    or re.fullmatch(
                        r"source_derived_handoff_token_[0-9a-f]{48}",
                        token,
                    )
                    is None
                ):
                    if (
                        type(result) is dict
                        and result.get("ok") is True
                        and not revoke_after_failure()
                    ):
                        return self._phase4_error(
                            "source_derived_handoff_clipboard_revoke_failed",
                            "source_derived_handoff_clipboard_revoke_failed",
                        )
                    return (
                        json.dumps(result)
                        if type(result) is dict
                        else self._phase4_error(
                            "internal_error", "internalError"
                        )
                    )
                request_line = json.dumps(
                    {
                        "protocol": "reweave_agent_jsonl.v2",
                        "id": "bind-user-handoff",
                        "action": "bind_user_handoff",
                        "payload": {"handoff_token": token},
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                try:
                    _copy_to_system_clipboard(request_line)
                except BaseException:
                    if not revoke_after_failure():
                        return self._phase4_error(
                            "source_derived_handoff_clipboard_revoke_failed",
                            "source_derived_handoff_clipboard_revoke_failed",
                        )
                    return self._phase4_error(
                        "source_derived_handoff_clipboard_failed",
                        "source_derived_handoff_clipboard_failed",
                    )
                return json.dumps(
                    {
                        "ok": True,
                        "data": {
                            "schema_version": (
                                "source_derived_handoff_status.v1"
                            ),
                            "status": "active",
                            "created_at": data.get("created_at"),
                        },
                    }
                )

            @Slot(str, result=str)
            def revoke_local_source_derived_handoff(
                self, payload_json: str = ""
            ) -> str:
                return self._phase4_call(
                    "revoke_local_source_derived_handoff",
                    payload_json,
                )

            @Slot(str, result=str)
            def decide_local_source_derived_handoff_proposal(
                self, payload_json: str = ""
            ) -> str:
                return self._phase4_call(
                    "decide_local_source_derived_handoff_proposal",
                    payload_json,
                )

            @Slot(str, result=str)
            def get_confirmed_product_plan(self, payload_json: str = "") -> str:
                return self._phase4_call(
                    "get_confirmed_product_plan", payload_json
                )

            @Slot(str, result=str)
            def start_confirmed_product_candidate(
                self, payload_json: str = ""
            ) -> str:
                return self._phase4_call(
                    "start_confirmed_product_candidate", payload_json
                )

            @Slot(str, result=str)
            def get_product_candidate_run(self, payload_json: str = "") -> str:
                return self._phase4_call(
                    "get_product_candidate_run", payload_json
                )

            @Slot(str, result=str)
            def get_product_candidate(self, payload_json: str = "") -> str:
                return self._phase4_call("get_product_candidate", payload_json)

            @Slot(str, result=str)
            def read_product_candidate_file(
                self, payload_json: str = ""
            ) -> str:
                return self._phase4_call(
                    "read_product_candidate_file", payload_json
                )

            @Slot(str, result=str)
            def choose_product_candidate_export_folder(
                self, payload_json: str = ""
            ) -> str:
                try:
                    request = json.loads(payload_json) if payload_json else {}
                except json.JSONDecodeError:
                    return self._phase4_error("invalid_payload", "invalidPayload")
                if (
                    not isinstance(request, dict)
                    or set(request) != {"plan_token", "candidate_token"}
                    or not isinstance(request.get("plan_token"), str)
                    or not isinstance(request.get("candidate_token"), str)
                ):
                    return self._phase4_error(
                        "product_candidate_export_request_invalid",
                        "product_candidate_export_request_invalid",
                    )
                try:
                    _, _, _, _, _, QFileDialog = import_qt_webengine()
                    parent = QFileDialog.getExistingDirectory(
                        self._parent_widget, "Save product"
                    )
                except Exception:
                    logger.error("Product candidate folder chooser failed")
                    return self._phase4_error("internal_error", "internalError")
                if not parent:
                    return json.dumps({"ok": False, "cancelled": True})
                return self._phase4_call(
                    "export_product_candidate",
                    json.dumps(
                        {
                            "plan_token": request["plan_token"],
                            "candidate_token": request["candidate_token"],
                            "destination_parent": parent,
                        }
                    ),
                )

            @Slot(str, result=str)
            def preview_product_candidate(self, payload_json: str = "") -> str:
                try:
                    request = json.loads(payload_json) if payload_json else {}
                except json.JSONDecodeError:
                    return self._phase4_error("invalid_payload", "invalidPayload")
                if (
                    not isinstance(request, dict)
                    or set(request) != {"candidate_token"}
                    or not isinstance(request.get("candidate_token"), str)
                ):
                    return self._phase4_error(
                        "product_candidate_token_invalid",
                        "product_candidate_token_invalid",
                    )
                verified = self._engine.get_product_candidate(request)
                if not isinstance(verified, dict) or verified.get("ok") is not True:
                    return json.dumps(verified)
                candidate = verified.get("data")
                if (
                    not isinstance(candidate, dict)
                    or candidate.get("status") != "review_ready"
                ):
                    return self._phase4_error(
                        "product_candidate_preview_not_ready",
                        "product_candidate_preview_not_ready",
                    )
                try:
                    files = candidate.get("files")
                    entry_record = candidate.get("entry")
                    if (
                        not isinstance(files, list)
                        or not isinstance(entry_record, dict)
                        or set(entry_record) != {"path", "kind"}
                        or not isinstance(entry_record.get("path"), str)
                    ):
                        raise ValueError("candidate_projection_invalid")
                    temporary = tempfile.TemporaryDirectory(
                        prefix="reweave-candidate-preview-"
                    )
                    product_root = Path(temporary.name)
                    os.chmod(product_root, 0o700)
                    allowed: set[Path] = set()
                    for metadata in files:
                        if not isinstance(metadata, dict):
                            raise ValueError("candidate_file_invalid")
                        logical = PurePosixPath(str(metadata.get("path") or ""))
                        if (
                            logical.is_absolute()
                            or not logical.parts
                            or any(part in {"", ".", ".."} for part in logical.parts)
                        ):
                            raise ValueError("candidate_file_invalid")
                        opened = self._engine.read_product_candidate_file(
                            {
                                "candidate_token": request["candidate_token"],
                                "relative_path": logical.as_posix(),
                            }
                        )
                        data_record = (
                            opened.get("data")
                            if isinstance(opened, dict)
                            and opened.get("ok") is True
                            else None
                        )
                        if (
                            not isinstance(data_record, dict)
                            or data_record.get("path") != logical.as_posix()
                            or data_record.get("sha256") != metadata.get("sha256")
                        ):
                            raise ValueError("candidate_file_invalid")
                        if data_record.get("encoding") == "utf-8":
                            data = str(data_record.get("content") or "").encode("utf-8")
                        elif data_record.get("encoding") == "base64":
                            data = base64.b64decode(
                                str(data_record.get("content") or ""),
                                validate=True,
                            )
                        else:
                            raise ValueError("candidate_file_invalid")
                        if (
                            len(data) != metadata.get("size_bytes")
                            or hashlib.sha256(data).hexdigest()
                            != metadata.get("sha256")
                        ):
                            raise ValueError("candidate_file_invalid")
                        target = product_root.joinpath(*logical.parts)
                        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                        for parent in (target.parent, *target.parent.parents):
                            if parent == product_root.parent:
                                break
                            os.chmod(parent, 0o700)
                        with target.open("xb") as stream:
                            stream.write(data)
                        os.chmod(target, 0o600)
                        allowed.add(target.resolve(strict=True))
                    entry = product_root.joinpath(
                        *PurePosixPath(entry_record["path"]).parts
                    ).resolve(strict=True)
                    if entry not in allowed:
                        raise ValueError("entry_not_allowed")

                    (
                        _,
                        QMainWindow,
                        QWebEngineView,
                        QWebEngineSettings,
                        QUrl,
                        _,
                    ) = import_qt_webengine()
                    from PySide6.QtWebEngineCore import (
                        QWebEnginePage,
                        QWebEngineProfile,
                        QWebEngineUrlRequestInterceptor,
                    )

                    class CandidateInterceptor(QWebEngineUrlRequestInterceptor):
                        def __init__(self, parent=None):
                            super().__init__(parent)
                            self.blocked_count = 0

                        def interceptRequest(self, info):
                            url = info.requestUrl()
                            if (
                                url.scheme().lower() == "about"
                                and url.toString() == "about:blank"
                            ):
                                return
                            if url.isLocalFile():
                                try:
                                    if Path(url.toLocalFile()).resolve(strict=True) in allowed:
                                        return
                                except OSError:
                                    pass
                            self.blocked_count += 1
                            info.block(True)

                    class CandidatePage(QWebEnginePage):
                        def acceptNavigationRequest(
                            self, url, navigation_type, is_main_frame
                        ):
                            del navigation_type, is_main_frame
                            if (
                                url.scheme().lower() == "about"
                                and url.toString() == "about:blank"
                            ):
                                return True
                            if not url.isLocalFile():
                                return False
                            try:
                                return (
                                    Path(url.toLocalFile()).resolve(strict=True)
                                    in allowed
                                )
                            except OSError:
                                return False

                    window = QMainWindow(self._parent_widget)
                    window.setWindowTitle("Reweave · Product preview")
                    window.resize(960, 720)
                    view = QWebEngineView(window)
                    profile = QWebEngineProfile(view)
                    interceptor = CandidateInterceptor(profile)
                    profile.setUrlRequestInterceptor(interceptor)
                    page = CandidatePage(profile, view)
                    view.setPage(page)
                    settings = page.settings()
                    settings.setAttribute(
                        QWebEngineSettings.LocalContentCanAccessFileUrls, True
                    )
                    settings.setAttribute(
                        QWebEngineSettings.LocalContentCanAccessRemoteUrls, False
                    )
                    settings.setAttribute(QWebEngineSettings.DnsPrefetchEnabled, False)
                    settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, False)
                    settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
                    settings.setAttribute(
                        QWebEngineSettings.JavascriptCanOpenWindows, False
                    )
                    view._reweave_candidate_profile = profile
                    view._reweave_candidate_interceptor = interceptor
                    view._reweave_candidate_temporary = temporary
                    window.setCentralWidget(view)
                    window._reweave_candidate_allowed = allowed
                    self._candidate_preview_windows.append(window)
                    window.destroyed.connect(
                        lambda *_args, current=window: (
                            self._candidate_preview_windows.remove(current)
                            if current in self._candidate_preview_windows
                            else None
                        )
                    )
                    view.load(QUrl.fromLocalFile(str(entry)))
                    window.show()
                except Exception:
                    logger.error("Product candidate preview failed")
                    return self._phase4_error("internal_error", "internalError")
                return json.dumps(
                    {
                        "ok": True,
                        "data": {
                            "status": "opened",
                            "network_access": False,
                            "outside_file_access": False,
                        },
                    }
                )

            @Slot(str, result=str)
            def list_review_items(self, payload_json: str = "") -> str:
                return self._phase4_call("list_review_items", payload_json)

            @Slot(str, result=str)
            def decide_review_item(self, payload_json: str = "") -> str:
                return self._phase4_call("decide_review_item", payload_json)

            @Slot(str, result=str)
            def list_capability_groups(self, payload_json: str = "") -> str:
                return self._phase4_call("list_capability_groups", payload_json)

            @Slot(str, result=str)
            def rename_capability_group(self, payload_json: str = "") -> str:
                return self._phase4_call("rename_capability_group", payload_json)

            @Slot(str, result=str)
            def get_capsule_detail(self, payload_json: str = "") -> str:
                return self._phase4_call("get_capsule_detail", payload_json)

            @Slot(str, result=str)
            def get_capsule_core_code_projection(self, payload_json: str = "") -> str:
                return self._phase4_call(
                    "get_capsule_core_code_projection", payload_json
                )

            @Slot(str, result=str)
            def set_capsule_status(self, payload_json: str = "") -> str:
                return self._phase4_call("set_capsule_status", payload_json)

            @Slot(str, result=str)
            def create_backup(self, payload_json: str = "") -> str:
                return self._phase4_call("create_backup", payload_json)

            @Slot(str, result=str)
            def list_backups(self, payload_json: str = "") -> str:
                return self._phase4_call("list_backups", payload_json)

            @Slot(str, result=str)
            def inspect_backup(self, payload_json: str = "") -> str:
                return self._phase4_call("inspect_backup", payload_json)

            @Slot(str, result=str)
            def inspect_restore(self, payload_json: str = "") -> str:
                return self._phase4_call("inspect_backup", payload_json)

            @Slot(str, result=str)
            def restore_backup(self, payload_json: str = "") -> str:
                return self._phase4_call("restore_backup", payload_json)

            @Slot(str, result=str)
            def start_legacy_import(self, payload_json: str = "") -> str:
                return self._phase4_call("start_legacy_import", payload_json)

            @Slot(str, result=str)
            def generate_product(self, payload_json: str = "") -> str:
                return self._phase4_call("generate_product", payload_json)

            @Slot(str, result=str)
            def analyze_static_web_target(self, payload_json: str = "") -> str:
                return self._phase4_call("analyze_static_web_target", payload_json)

            @Slot(str, result=str)
            def generate_static_web_patch(self, payload_json: str = "") -> str:
                return self._phase4_call("generate_static_web_patch", payload_json)

            @Slot(str, result=str)
            def retry_product_usage_registration(self, payload_json: str = "") -> str:
                return self._phase4_call(
                    "retry_product_usage_registration", payload_json
                )

            @Slot(str, result=str)
            def create_review_queue_for_source(self, source_id: str = "") -> str:
                blocked = self._lumo_lite_block("create_review_queue_for_source")
                if blocked:
                    return json.dumps(blocked)
                source_id = (source_id or "").strip()
                if not source_id:
                    return json.dumps({"ok": False, "source_id": "", "error": "missing source_id"})
                try:
                    if not hasattr(self._engine, "create_review_queue_for_source"):
                        return json.dumps({"ok": False, "source_id": source_id, "error": "review_unavailable"})
                    result = self._engine.create_review_queue_for_source(source_id)
                    return json.dumps(result)
                except Exception as exc:
                    logger.exception("Create review queue failed: %s", source_id)
                    return json.dumps(
                        {"ok": False, "source_id": source_id, "error": str(exc)[:200]}
                    )

            @Slot(str, result=str)
            def update_review_decision(self, payload_json: str = "") -> str:
                blocked = self._lumo_lite_block("update_review_decision")
                if blocked:
                    return json.dumps(blocked)
                payload: dict[str, Any] = {}
                if payload_json:
                    try:
                        payload = json.loads(payload_json)
                    except json.JSONDecodeError:
                        payload = {"raw": payload_json}
                source_id = str(payload.get("source_id") or payload.get("sourceId") or "").strip()
                review_id = str(payload.get("review_id") or payload.get("reviewId") or "").strip()
                decision = str(payload.get("decision") or "").strip()
                reason = str(payload.get("reason") or "")
                if not source_id or not review_id:
                    return json.dumps({"ok": False, "error": "missing source_id or review_id"})
                try:
                    if not hasattr(self._engine, "update_review_decision"):
                        return json.dumps({"ok": False, "source_id": source_id, "error": "review_unavailable"})
                    result = self._engine.update_review_decision(source_id, review_id, decision, reason)
                    return json.dumps(result)
                except Exception as exc:
                    logger.exception("Update review decision failed: %s", source_id)
                    return json.dumps(
                        {"ok": False, "source_id": source_id, "error": str(exc)[:200]}
                    )

            @Slot(str, result=str)
            def promote_review_item(self, payload_json: str = "") -> str:
                blocked = self._lumo_lite_block("promote_review_item")
                if blocked:
                    return json.dumps(blocked)
                payload: dict[str, Any] = {}
                if payload_json:
                    try:
                        payload = json.loads(payload_json)
                    except json.JSONDecodeError:
                        payload = {"raw": payload_json}
                source_id = str(payload.get("source_id") or payload.get("sourceId") or "").strip()
                review_id = str(payload.get("review_id") or payload.get("reviewId") or "").strip()
                if not source_id or not review_id:
                    return json.dumps({"ok": False, "error": "missing source_id or review_id"})
                try:
                    if not hasattr(self._engine, "promote_review_item"):
                        return json.dumps({"ok": False, "source_id": source_id, "error": "promote_unavailable"})
                    result = self._engine.promote_review_item(source_id, review_id)
                    return json.dumps(result)
                except Exception as exc:
                    logger.exception("Promote review item failed: %s", source_id)
                    return json.dumps(
                        {"ok": False, "source_id": source_id, "error": str(exc)[:200]}
                    )

            @Slot(str, result=str)
            def list_warehouse_capsules(self, payload_json: str = "") -> str:
                blocked = self._lumo_lite_block("list_warehouse_capsules")
                if blocked:
                    return json.dumps(blocked)
                include_inactive = True
                if payload_json:
                    try:
                        payload = json.loads(payload_json)
                        if isinstance(payload, dict) and "include_inactive" in payload:
                            include_inactive = bool(payload.get("include_inactive"))
                    except json.JSONDecodeError:
                        pass
                try:
                    if not hasattr(self._engine, "list_warehouse_capsules"):
                        return json.dumps({"ok": False, "error": "warehouse_list_unavailable"})
                    result = self._engine.list_warehouse_capsules(include_inactive=include_inactive)
                    return json.dumps(result)
                except Exception as exc:
                    logger.exception("List warehouse capsules failed")
                    return json.dumps({"ok": False, "error": str(exc)[:200]})

            @Slot(str, result=str)
            def update_capsule_status(self, payload_json: str = "") -> str:
                blocked = self._lumo_lite_block("update_capsule_status")
                if blocked:
                    return json.dumps(blocked)
                payload: dict[str, Any] = {}
                if payload_json:
                    try:
                        payload = json.loads(payload_json)
                    except json.JSONDecodeError:
                        payload = {"raw": payload_json}
                capsule_id = str(payload.get("capsule_id") or payload.get("capsuleId") or "").strip()
                status = str(payload.get("status") or "").strip()
                if not capsule_id or not status:
                    return json.dumps({"ok": False, "error": "missing capsule_id or status"})
                try:
                    if not hasattr(self._engine, "update_capsule_status"):
                        return json.dumps({"ok": False, "error": "status_update_unavailable"})
                    result = self._engine.update_capsule_status(capsule_id, status)
                    return json.dumps(result)
                except Exception as exc:
                    logger.exception("Update capsule status failed: %s", capsule_id)
                    return json.dumps(
                        {"ok": False, "capsule_id": capsule_id, "error": str(exc)[:200]}
                    )

            @Slot(str, result=str)
            def enrich_capsule_content(self, capsule_id: str = "") -> str:
                blocked = self._lumo_lite_block("enrich_capsule_content")
                if blocked:
                    return json.dumps(blocked)
                capsule_id = (capsule_id or "").strip()
                if not capsule_id:
                    return json.dumps({"ok": False, "error": "missing capsule_id"})
                try:
                    if not hasattr(self._engine, "enrich_capsule_content"):
                        return json.dumps({"ok": False, "error": "enrichment_unavailable"})
                    result = self._engine.enrich_capsule_content(capsule_id)
                    return json.dumps(result)
                except Exception as exc:
                    logger.exception("Enrich capsule content failed: %s", capsule_id)
                    return json.dumps(
                        {"ok": False, "capsule_id": capsule_id, "error": str(exc)[:200]}
                    )

            @Slot(str, result=str)
            def get_capsule_content(self, capsule_id: str = "") -> str:
                blocked = self._lumo_lite_block("get_capsule_content")
                if blocked:
                    return json.dumps(blocked)
                capsule_id = (capsule_id or "").strip()
                if not capsule_id:
                    return json.dumps({"ok": False, "error": "missing capsule_id"})
                try:
                    if not hasattr(self._engine, "get_capsule_content"):
                        return json.dumps({"ok": False, "error": "content_viewer_unavailable"})
                    result = self._engine.get_capsule_content(capsule_id)
                    return json.dumps(result)
                except Exception as exc:
                    logger.exception("Get capsule content failed: %s", capsule_id)
                    return json.dumps(
                        {"ok": False, "capsule_id": capsule_id, "error": str(exc)[:200]}
                    )

            @Slot(result=str)
            def get_latest_preview_package(self) -> str:
                blocked = self._lumo_lite_block("get_latest_preview_package")
                if blocked:
                    return json.dumps(blocked)
                try:
                    if not hasattr(self._engine, "get_latest_preview_package"):
                        return json.dumps({"ok": False, "error": "preview_viewer_unavailable"})
                    return json.dumps(self._engine.get_latest_preview_package())
                except Exception as exc:
                    logger.exception("Get latest preview package failed")
                    return json.dumps({"ok": False, "error": str(exc)[:200]})

            @Slot(str, result=str)
            def get_preview_package(self, package_id_or_path: str = "") -> str:
                blocked = self._lumo_lite_block("get_preview_package")
                if blocked:
                    return json.dumps(blocked)
                package_id_or_path = (package_id_or_path or "").strip()
                if not package_id_or_path:
                    return json.dumps({"ok": False, "error": "missing package_id"})
                try:
                    if not hasattr(self._engine, "get_preview_package"):
                        return json.dumps({"ok": False, "error": "preview_viewer_unavailable"})
                    return json.dumps(self._engine.get_preview_package(package_id_or_path))
                except Exception as exc:
                    logger.exception("Get preview package failed: %s", package_id_or_path)
                    return json.dumps({"ok": False, "error": str(exc)[:200]})

            @Slot(str, result=str)
            def compare_preview_packages(self, payload_json: str = "") -> str:
                blocked = self._lumo_lite_block("compare_preview_packages")
                if blocked:
                    return json.dumps(blocked)
                left_id = ""
                right_id = ""
                if payload_json:
                    try:
                        payload = json.loads(payload_json)
                        if isinstance(payload, dict):
                            left_id = str(payload.get("leftId") or payload.get("left_id") or "")
                            right_id = str(payload.get("rightId") or payload.get("right_id") or "")
                    except json.JSONDecodeError:
                        pass
                try:
                    if not hasattr(self._engine, "compare_preview_packages"):
                        return json.dumps({"ok": False, "error": "preview_compare_unavailable"})
                    result = self._engine.compare_preview_packages(left_id, right_id)
                    return json.dumps(result)
                except Exception as exc:
                    logger.exception("Compare preview packages failed")
                    return json.dumps({"ok": False, "error": str(exc)[:200]})

            @Slot(str, result=str)
            def choose_export_folder_and_export(self, payload_json: str = "") -> str:
                blocked = self._lumo_lite_block("choose_export_folder_and_export")
                if blocked:
                    return json.dumps(blocked)
                payload: dict[str, Any] = {}
                if payload_json:
                    try:
                        payload = json.loads(payload_json)
                    except json.JSONDecodeError:
                        payload = {"raw": payload_json}
                package_id = str(
                    payload.get("packageIdOrPath")
                    or payload.get("package_id")
                    or payload.get("packageId")
                    or ""
                ).strip()
                mode = str(payload.get("mode") or "zip").strip().lower()
                if not package_id:
                    return json.dumps({"ok": False, "error": "missing package_id"})
                try:
                    if not hasattr(self._engine, "export_preview_package"):
                        return json.dumps({"ok": False, "error": "preview_export_unavailable"})
                    if getattr(self._engine, "_is_lumo_lite", lambda: False)():
                        return json.dumps(self._engine.export_preview_package(package_id, "", mode))
                    _, _, _, _, _, QFileDialog = import_qt_webengine()
                    export_dir = QFileDialog.getExistingDirectory(
                        self._parent_widget, "Select export folder"
                    )
                    if not export_dir:
                        return json.dumps({"ok": False, "cancelled": True})
                    result = self._engine.export_preview_package(package_id, export_dir, mode)
                    return json.dumps(result)
                except Exception as exc:
                    logger.exception("Export preview package failed: %s", package_id)
                    return json.dumps({"ok": False, "error": str(exc)[:200]})

            @Slot(str, result=str)
            def export_preview_package(self, payload_json: str = "") -> str:
                blocked = self._lumo_lite_block("export_preview_package")
                if blocked:
                    return json.dumps(blocked)
                payload: dict[str, Any] = {}
                if payload_json:
                    try:
                        payload = json.loads(payload_json)
                    except json.JSONDecodeError:
                        payload = {"raw": payload_json}
                package_id = str(
                    payload.get("packageIdOrPath")
                    or payload.get("package_id")
                    or payload.get("packageId")
                    or ""
                ).strip()
                export_dir = str(payload.get("exportDir") or payload.get("export_dir") or "").strip()
                mode = str(payload.get("mode") or "zip").strip().lower()
                if not package_id or not export_dir:
                    return json.dumps({"ok": False, "error": "missing package_id or export_dir"})
                try:
                    if not hasattr(self._engine, "export_preview_package"):
                        return json.dumps({"ok": False, "error": "preview_export_unavailable"})
                    result = self._engine.export_preview_package(package_id, export_dir, mode)
                    return json.dumps(result)
                except Exception as exc:
                    logger.exception("Export preview package failed: %s", package_id)
                    return json.dumps({"ok": False, "error": str(exc)[:200]})

            @Slot(result=str)
            def list_lumo_lite_artifacts(self) -> str:
                try:
                    if not hasattr(self._engine, "list_lumo_lite_artifacts"):
                        return json.dumps({"ok": False, "error": "lumo_lite_artifacts_unavailable"})
                    return json.dumps(self._engine.list_lumo_lite_artifacts())
                except Exception as exc:
                    logger.exception("List Lumo Lite artifacts failed")
                    return json.dumps({"ok": False, "error": str(exc)[:200]})

            @Slot(str, result=str)
            def get_lumo_lite_artifact(self, artifact_id_or_path: str = "") -> str:
                artifact_id_or_path = (artifact_id_or_path or "").strip()
                if not artifact_id_or_path:
                    return json.dumps({"ok": False, "error": "missing_artifact_id"})
                try:
                    if not hasattr(self._engine, "get_lumo_lite_artifact"):
                        return json.dumps({"ok": False, "error": "lumo_lite_artifact_unavailable"})
                    return json.dumps(self._engine.get_lumo_lite_artifact(artifact_id_or_path))
                except Exception as exc:
                    logger.exception("Get Lumo Lite artifact failed: %s", artifact_id_or_path)
                    return json.dumps({"ok": False, "error": str(exc)[:200]})

            @Slot(str, result=str)
            def open_lumo_lite_artifact(self, artifact_id_or_path: str = "") -> str:
                artifact_id_or_path = (artifact_id_or_path or "").strip()
                if not artifact_id_or_path:
                    return json.dumps({"ok": False, "error": "missing_artifact_id"})
                try:
                    if not hasattr(self._engine, "get_lumo_lite_artifact_path"):
                        return json.dumps({"ok": False, "error": "lumo_lite_artifact_unavailable"})
                    raw_path = self._engine.get_lumo_lite_artifact_path(artifact_id_or_path)
                    if not raw_path:
                        return json.dumps({"ok": False, "error": "artifact_not_found"})
                    path = Path(str(raw_path))
                    if not path.exists():
                        return json.dumps({"ok": False, "error": "artifact_not_found"})
                    from PySide6.QtCore import QUrl
                    from PySide6.QtGui import QDesktopServices

                    opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
                    return json.dumps({"ok": bool(opened), "path": str(path.resolve())})
                except Exception as exc:
                    logger.exception("Open Lumo Lite artifact failed: %s", artifact_id_or_path)
                    return json.dumps({"ok": False, "error": str(exc)[:200]})

            @Slot(str, result=str)
            def preview_governance_for_source(self, source_id: str = "") -> str:
                blocked = self._lumo_lite_block("preview_governance_for_source")
                if blocked:
                    return json.dumps(blocked)
                source_id = (source_id or "").strip()
                if not source_id:
                    return json.dumps({"ok": False, "source_id": "", "error": "missing source_id"})
                try:
                    if not hasattr(self._engine, "preview_governance_for_source"):
                        return json.dumps({"ok": False, "source_id": source_id, "error": "preview_unavailable"})
                    result = self._engine.preview_governance_for_source(source_id)
                    return json.dumps(result)
                except Exception as exc:
                    logger.exception("Governance preview failed: %s", source_id)
                    return json.dumps(
                        {"ok": False, "source_id": source_id, "error": str(exc)[:200]}
                    )

            @Slot(str, result=str)
            def verify_source_suggestions(self, source_id: str = "") -> str:
                blocked = self._lumo_lite_block("verify_source_suggestions")
                if blocked:
                    return json.dumps(blocked)
                source_id = (source_id or "").strip()
                if not source_id:
                    return json.dumps({"ok": False, "source_id": "", "error": "missing source_id"})
                try:
                    if not hasattr(self._engine, "verify_source_suggestions"):
                        return json.dumps({"ok": False, "source_id": source_id, "error": "verify_unavailable"})
                    result = self._engine.verify_source_suggestions(source_id)
                    return json.dumps(result)
                except Exception as exc:
                    logger.exception("Verify suggestions failed: %s", source_id)
                    return json.dumps(
                        {"ok": False, "source_id": source_id, "error": str(exc)[:200]}
                    )

            @Slot(result=str)
            def open_generated_product(self) -> str:
                path = self._engine.get_latest_product_entry_path() if hasattr(self._engine, "get_latest_product_entry_path") else None
                if not path:
                    return json.dumps({"ok": False, "error": "product_entry_unavailable"})
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices

                opened = QDesktopServices.openUrl(QUrl.fromLocalFile(path))
                return json.dumps({"ok": bool(opened), "source_project_write": False})

            @Slot(str, result=str)
            def open_preview_folder(self, path: str = "") -> str:
                del path
                return self._phase4_error(
                    "legacy_preview_open_inactive", "legacyPreviewOpenInactive"
                )

        cls._qobject_cls = _BridgeImpl
        return cls._qobject_cls

    @classmethod
    def create(cls, engine: Any, parent=None):
        impl = cls._ensure_qt_base()
        return impl(engine, parent)


def _setup_web_channel(view, bridge) -> None:
    """Attach QWebChannel after the page loads (avoids QtWebEngine crash on macOS)."""
    _, _, QWebChannel = import_qt_bridge()
    page = view.page()
    channel = QWebChannel()
    channel.registerObject("reweaveBridge", bridge)
    page.setWebChannel(channel)
    view._reweave_web_channel = channel

    init_js = """
    (function () {
      function connect() {
        if (typeof qt === 'undefined' || !qt.webChannelTransport) return;
        if (typeof QWebChannel === 'undefined') return;
        if (window.reweaveBridge || window.__reweaveWebChannelConnecting) return;
        window.__reweaveWebChannelConnecting = true;
        new QWebChannel(qt.webChannelTransport, function (channel) {
          window.__reweaveWebChannelConnecting = false;
          window.reweaveBridge = channel.objects.reweaveBridge;
          window.dispatchEvent(new Event('reweave-bridge-ready'));
        });
      }
      if (typeof QWebChannel === 'undefined') {
        var script = document.createElement('script');
        script.src = 'qrc:///qtwebchannel/qwebchannel.js';
        script.onload = connect;
        document.head.appendChild(script);
        return;
      }
      connect();
    })();
    """
    legacy_init_js = """
    (function () {
      if (typeof qt === 'undefined' || !qt.webChannelTransport) return;
      if (typeof QWebChannel === 'undefined') return;
      if (window.reweaveBridge || window.__reweaveWebChannelConnecting) return;
      window.__reweaveWebChannelConnecting = true;
      new QWebChannel(qt.webChannelTransport, function (channel) {
        window.__reweaveWebChannelConnecting = false;
        window.reweaveBridge = channel.objects.reweaveBridge;
        window.dispatchEvent(new Event('reweave-bridge-ready'));
      });
    })();
    """

    def on_load_finished(ok: bool) -> None:
        if not ok:
            logger.error("Failed to load Reweave index.html")
            return

        qc_path = locate_qwebchannel_js()
        if qc_path is None:
            page.runJavaScript(init_js)
            return
        source = qc_path.read_text(encoding="utf-8")

        def run_init(_result=None):
            page.runJavaScript(legacy_init_js)

        page.runJavaScript(source, run_init)

    view.loadFinished.connect(on_load_finished)


def create_reweave_window():
    QApplication, QMainWindow, QWebEngineView, QWebEngineSettings, QUrl, _ = import_qt_webengine()
    ensure_reweave_assets()
    engine = ReweaveAppService()

    window = QMainWindow()
    bridge = ReweaveBridge.create(engine, parent=window)
    service_closed = False

    def close_service(*_args) -> None:
        nonlocal service_closed
        if service_closed:
            return
        service_closed = True
        close = getattr(engine, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.error("Reweave service close failed")

    app = QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(close_service)
    window.destroyed.connect(close_service)
    window._reweave_close_service = close_service

    window.setWindowTitle(WINDOW_TITLE)
    window.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
    window.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
    window.setStyleSheet("background-color: #fdfcf8;")

    view = QWebEngineView(window)
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineUrlRequestInterceptor

    class LocalFrontendPage(QWebEnginePage):
        def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
            if not is_main_frame:
                return True
            if url.scheme().lower() == "about":
                return url.toString() == "about:blank"
            return url.isLocalFile() and _is_frontend_file(url.toLocalFile())

    class LocalFrontendRequestInterceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info):
            url = info.requestUrl()
            if url.scheme().lower() in {"about", "blob", "data", "qrc"}:
                return
            if url.isLocalFile() and (_is_frontend_file(url.toLocalFile()) or _is_preview_image(url.toLocalFile())):
                return
            info.block(True)

    view.setPage(LocalFrontendPage(view))
    request_interceptor = LocalFrontendRequestInterceptor(view)
    view.page().profile().setUrlRequestInterceptor(request_interceptor)
    view._reweave_request_interceptor = request_interceptor
    settings = view.settings()
    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
    settings.setAttribute(QWebEngineSettings.DnsPrefetchEnabled, False)
    settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
    settings.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
    settings.setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, False)

    window.setCentralWidget(view)
    _setup_web_channel(view, bridge)

    index = reweave_index_path()
    url = QUrl.fromLocalFile(str(index))
    url.setQuery("desktop=1")
    view.load(url)

    return window, bridge


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    QApplication, _, _, _, _, _ = import_qt_webengine()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Reweave")
    window, _bridge = create_reweave_window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
