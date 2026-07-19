#!/usr/bin/env python3
"""Reweave desktop shell — PySide6 + QWebChannel + local engine."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
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
                    "choose_source_folder",
                    "scan_source_box",
                    "draft_capsules",
                    "promote_source_drafts",
                    "notify_generate",
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

            @Slot(result=str)
            def choose_source_folder(self) -> str:
                blocked = self._lumo_lite_block("choose_source_folder")
                if blocked:
                    return json.dumps(blocked)
                _, _, _, _, _, QFileDialog = import_qt_webengine()
                path = QFileDialog.getExistingDirectory(self._parent_widget, "Select source folder")
                if not path:
                    return json.dumps({"ok": False, "cancelled": True})
                source = self._engine.bind_source_folder(path)
                if isinstance(source, dict) and source.get("ok") is False:
                    return json.dumps(source)
                logger.info("Bound source: %s", source.get("path"))
                return json.dumps({"ok": True, "source": source})

            @Slot(str, result=str)
            def scan_source_box(self, source_id: str = "") -> str:
                blocked = self._lumo_lite_block("scan_source_box")
                if blocked:
                    return json.dumps(blocked)
                source_id = (source_id or "").strip()
                if not source_id:
                    return json.dumps({"ok": False, "source_id": "", "error": "missing source_id"})
                try:
                    summary = self._engine.scan_source(source_id)
                    if isinstance(summary, dict) and summary.get("ok") is False:
                        return json.dumps(summary)
                    source = self._engine.get_source(source_id)
                    return json.dumps(
                        {"ok": True, "source_id": source_id, "summary": summary, "source": source}
                    )
                except KeyError:
                    return json.dumps({"ok": False, "source_id": source_id, "error": "source not found"})
                except Exception as exc:
                    logger.exception("Scan failed: %s", source_id)
                    return json.dumps(
                        {
                            "ok": False,
                            "source_id": source_id,
                            "error": str(exc)[:200],
                            "source": self._engine.get_source(source_id),
                        }
                    )

            @Slot(str, result=str)
            def draft_capsules(self, source_id: str = "") -> str:
                blocked = self._lumo_lite_block("draft_capsules")
                if blocked:
                    return json.dumps(blocked)
                source_id = (source_id or "").strip()
                if not source_id:
                    return json.dumps({"ok": False, "source_id": "", "error": "missing source_id"})
                try:
                    draft = self._engine.draft_source(source_id)
                    if isinstance(draft, dict) and draft.get("ok") is False:
                        return json.dumps(draft)
                    source = self._engine.get_source(source_id)
                    return json.dumps(
                        {"ok": True, "source_id": source_id, "draft": draft, "source": source}
                    )
                except Exception as exc:
                    logger.exception("Draft failed: %s", source_id)
                    return json.dumps(
                        {
                            "ok": False,
                            "source_id": source_id,
                            "error": str(exc)[:200],
                            "source": self._engine.get_source(source_id),
                        }
                    )

            @Slot(str, result=str)
            def promote_source_drafts(self, source_id: str = "") -> str:
                blocked = self._lumo_lite_block("promote_source_drafts")
                if blocked:
                    return json.dumps(blocked)
                source_id = (source_id or "").strip()
                if not source_id:
                    return json.dumps({"ok": False, "source_id": "", "error": "missing source_id"})
                try:
                    promoted = self._engine.promote_source(source_id)
                    if isinstance(promoted, dict) and promoted.get("ok") is False:
                        return json.dumps(promoted)
                    source = self._engine.get_source(source_id)
                    state = self._engine.get_initial_state()
                    return json.dumps(
                        {
                            "ok": True,
                            "source_id": source_id,
                            "promoted": promoted,
                            "source": source,
                            "capsules": state.get("capsules", []),
                        }
                    )
                except Exception as exc:
                    logger.exception("Promote failed: %s", source_id)
                    return json.dumps(
                        {
                            "ok": False,
                            "source_id": source_id,
                            "error": str(exc)[:200],
                            "source": self._engine.get_source(source_id),
                        }
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

            @Slot(str, result=str)
            def notify_generate(self, payload_json: str = "") -> str:
                # Historical QWebChannel alias only. The active frontend calls
                # generate_product and neither path can reach generate_preview.
                return self._phase4_call("generate_product", payload_json)

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
