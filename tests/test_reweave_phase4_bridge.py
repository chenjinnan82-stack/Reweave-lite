from __future__ import annotations

import json
from unittest.mock import patch

from pimos_lite import desktop_reweave_static as desktop


class _QObject:
    def __init__(self, *_args, **_kwargs) -> None:
        pass


def _slot(*_args, **_kwargs):
    def decorate(function):
        return function

    return decorate


def _bridge(service):
    desktop.ReweaveBridge._qobject_cls = None
    with patch.object(desktop, "import_qt_bridge", return_value=(_QObject, _slot, object)):
        return desktop.ReweaveBridge.create(service)


def test_phase4_bridge_forwards_json_payloads_to_app_service() -> None:
    class Service:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def __getattr__(self, name: str):
            def call(payload: dict):
                self.calls.append((name, payload))
                return {"ok": True, "method": name, "payload": payload}

            return call

    service = Service()
    bridge = _bridge(service)
    methods = (
        "discover_source_root",
        "confirm_projects",
        "register_javascript_computation_source",
        "start_scan_javascript_computations",
        "start_inspect_computation_adapters",
        "start_create_computation_adapter",
        "start_refresh_project",
        "start_refresh_all",
        "authorize_and_start_source_derived_computation",
        "admit_source_derived_review",
        "admit_source_derived_standard_ui_reviews",
        "get_intake_run",
        "cancel_intake_run",
        "list_supervision_models",
        "select_supervision_model",
        "list_product_planning_models",
        "select_product_planning_model",
        "start_product_plan",
        "submit_product_plan_answers",
        "suggest_product_plan_action",
        "revise_product_plan",
        "get_product_plan_run",
        "cancel_product_plan_run",
        "get_product_plan_workspace",
        "confirm_product_plan",
        "revoke_local_source_handoff",
        "revoke_local_source_derived_handoff",
        "decide_local_source_derived_handoff_proposal",
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
        "generate_product",
        "analyze_static_web_target",
        "generate_static_web_patch",
    )
    try:
        for method in methods:
            result = json.loads(getattr(bridge, method)(json.dumps({"token": method})))
            assert result == {
                "ok": True,
                "method": method,
                "payload": {"token": method},
            }
        alias = json.loads(bridge.inspect_restore('{"backup_path":"backup.sqlite3"}'))
        assert alias["method"] == "inspect_backup"
        assert service.calls[-1] == (
            "inspect_backup",
            {"backup_path": "backup.sqlite3"},
        )
    finally:
        desktop.ReweaveBridge._qobject_cls = None


def test_generation_slots_only_call_generate_product_with_strict_json() -> None:
    class Service:
        def __init__(self) -> None:
            self.payloads: list[dict] = []

        def generate_product(self, payload: dict):
            self.payloads.append(payload)
            return {"ok": True, "run_id": "run_product"}

        def generate_preview(self, _payload: dict):
            raise AssertionError("legacy generate_preview must be inactive")

    service = Service()
    bridge = _bridge(service)
    payload = {
        "task": "Build a quote",
        "capsule_ids": ["cap_quote"],
        "selection_mode": "manual",
    }
    try:
        assert json.loads(bridge.generate_product(json.dumps(payload))) == {
            "ok": True,
            "run_id": "run_product",
        }
        assert not hasattr(bridge, "notify_generate")
        assert not hasattr(bridge, "generate_preview")
        for retired in (
            "choose_source_folder",
            "scan_source_box",
            "draft_capsules",
            "promote_source_drafts",
        ):
            assert not hasattr(bridge, retired)
        assert service.payloads == [payload]

        malformed = json.loads(bridge.generate_product("[not-json"))
        assert malformed["error"] == {
            "code": "invalid_payload",
            "message_key": "invalidPayload",
        }
        non_object = json.loads(bridge.generate_product("[]"))
        assert non_object["error"] == {
            "code": "invalid_payload",
            "message_key": "invalidPayload",
        }
    finally:
        desktop.ReweaveBridge._qobject_cls = None

    try:
        import PySide6.QtCore  # noqa: F401
    except ImportError:
        return
    real_bridge = desktop.ReweaveBridge.create(service)
    try:
        meta = real_bridge.metaObject()
        signatures = {
            bytes(meta.method(index).methodSignature()).decode("ascii")
            for index in range(meta.methodOffset(), meta.methodCount())
        }
        assert "generate_product(QString)" in signatures
        assert "copy_local_source_handoff_binding(QString)" in signatures
        assert "revoke_local_source_handoff(QString)" in signatures
        assert (
            "copy_local_source_derived_handoff_binding(QString)"
            in signatures
        )
        assert (
            "revoke_local_source_derived_handoff(QString)" in signatures
        )
        assert (
            "decide_local_source_derived_handoff_proposal(QString)"
            in signatures
        )
        assert "notify_generate(QString)" not in signatures
        assert "generate_preview(QString)" not in signatures
        for retired in (
            "choose_source_folder()",
            "scan_source_box(QString)",
            "draft_capsules(QString)",
            "promote_source_drafts(QString)",
        ):
            assert retired not in signatures
    finally:
        desktop.ReweaveBridge._qobject_cls = None


def test_phase4_bridge_rejects_bad_json_and_never_reflects_exception_text() -> None:
    secret = "customer@example.com /private/customer/project"

    class Service:
        def restore_backup(self, _payload: dict):
            raise RuntimeError(secret)

    bridge = _bridge(Service())
    try:
        malformed = json.loads(bridge.restore_backup("[not-json"))
        assert malformed["error"] == {
            "code": "invalid_payload",
            "message_key": "invalidPayload",
        }

        raw = bridge.restore_backup("{}")
        assert secret not in raw
        assert json.loads(raw)["error"] == {
            "code": "internal_error",
            "message_key": "internalError",
        }
    finally:
        desktop.ReweaveBridge._qobject_cls = None


def test_choose_source_root_only_forwards_selected_directory() -> None:
    class Service:
        def __init__(self) -> None:
            self.payload = None

        def discover_source_root(self, payload: dict):
            self.payload = payload
            return {"ok": True}

    class FileDialog:
        @staticmethod
        def getExistingDirectory(*_args, **_kwargs) -> str:
            return "/tmp/source-root"

    service = Service()
    bridge = _bridge(service)
    try:
        with patch.object(
            desktop,
            "import_qt_webengine",
            return_value=(object, object, object, object, object, FileDialog),
        ):
            assert json.loads(bridge.choose_source_root()) == {"ok": True}
        assert service.payload == {
            "path": "/tmp/source-root",
            "root_kind": "project_collection",
        }
    finally:
        desktop.ReweaveBridge._qobject_cls = None


def test_static_web_target_bridge_is_review_only() -> None:
    class Service:
        def __getattr__(self, name: str):
            raise AssertionError(f"chooser must not call service method {name}")

    class FileDialog:
        @staticmethod
        def getExistingDirectory(*_args, **_kwargs) -> str:
            return "/tmp/example-site"

    class CancelDialog:
        @staticmethod
        def getExistingDirectory(*_args, **_kwargs) -> str:
            return ""

    bridge = _bridge(Service())
    try:
        with patch.object(
            desktop,
            "import_qt_webengine",
            return_value=(object, object, object, object, object, FileDialog),
        ):
            assert json.loads(bridge.choose_static_web_target()) == {
                "ok": True,
                "target_path": "/tmp/example-site",
                "display_name": "example-site",
            }
        with patch.object(
            desktop,
            "import_qt_webengine",
            return_value=(object, object, object, object, object, CancelDialog),
        ):
            assert json.loads(bridge.choose_static_web_target()) == {
                "ok": False,
                "cancelled": True,
            }

        assert not hasattr(bridge, "apply_static_web_patch")
        assert not hasattr(bridge, "commit_static_web_patch")
        assert not hasattr(bridge, "write_static_web_target")
    finally:
        desktop.ReweaveBridge._qobject_cls = None


def test_source_handoff_bridge_copies_one_strict_binding_and_revokes_on_failure() -> None:
    token = "source_handoff_token_" + "a" * 48

    class Service:
        def __init__(self) -> None:
            self.created: list[dict] = []
            self.revoked: list[dict] = []

        def create_local_source_handoff(self, payload: dict):
            self.created.append(payload)
            return {
                "ok": True,
                "data": {
                    "source_handoff_token": token,
                    "created_at": "2026-08-16T10:00:00Z",
                },
            }

        def revoke_local_source_handoff(self, payload: dict):
            self.revoked.append(payload)
            return {
                "ok": True,
                "data": {
                    "schema_version": "source_handoff_status.v1",
                    "status": "revoked",
                },
            }

    service = Service()
    bridge = _bridge(service)
    copied: list[str] = []
    try:
        with patch.object(
            desktop,
            "_copy_to_system_clipboard",
            side_effect=copied.append,
        ):
            raw = bridge.copy_local_source_handoff_binding(
                json.dumps({"project_id": "project_static"})
            )
        result = json.loads(raw)
        assert result == {
            "ok": True,
            "data": {
                "schema_version": "source_handoff_status.v1",
                "status": "active",
                "created_at": "2026-08-16T10:00:00Z",
            },
        }
        assert token not in raw
        assert service.created == [{"project_id": "project_static"}]
        assert json.loads(copied[0]) == {
            "protocol": "reweave_agent_jsonl.v2",
            "id": "bind-user-handoff",
            "action": "bind_user_handoff",
            "payload": {"handoff_token": token},
        }

        forwarded = json.loads(
            bridge.revoke_local_source_handoff(
                json.dumps({"project_id": "project_static"})
            )
        )
        assert forwarded["data"]["status"] == "revoked"
        assert service.revoked == [{"project_id": "project_static"}]

        invalid = json.loads(
            bridge.copy_local_source_handoff_binding(
                json.dumps({"project_id": "project_static", "path": "/tmp/source"})
            )
        )
        assert invalid["error"]["code"] == "source_handoff_request_invalid"

        service.create_local_source_handoff = lambda _payload: {
            "ok": True,
            "data": {"source_handoff_token": "handoff_token_" + "b" * 48},
        }
        wrong_prefix = json.loads(
            bridge.copy_local_source_handoff_binding(
                json.dumps({"project_id": "project_static"})
            )
        )
        assert wrong_prefix["error"]["code"] == "internal_error"
        assert service.revoked[-1] == {"project_id": "project_static"}
        service.create_local_source_handoff = lambda _payload: {
            "ok": True,
            "data": {
                "source_handoff_token": token,
                "created_at": "2026-08-16T10:00:00Z",
            },
        }
        with patch.object(
            desktop,
            "_copy_to_system_clipboard",
            side_effect=RuntimeError("clipboard denied"),
        ):
            failed = json.loads(
                bridge.copy_local_source_handoff_binding(
                    json.dumps({"project_id": "project_static"})
                )
            )
        assert failed["error"]["code"] == "source_handoff_clipboard_failed"
        assert service.revoked[-1] == {"project_id": "project_static"}

        service.revoke_local_source_handoff = lambda _payload: {
            "ok": False,
            "error": {"code": "source_handoff_conflict"},
        }
        with patch.object(
            desktop,
            "_copy_to_system_clipboard",
            side_effect=RuntimeError("clipboard denied"),
        ):
            revoke_failed = json.loads(
                bridge.copy_local_source_handoff_binding(
                    json.dumps({"project_id": "project_static"})
                )
            )
        assert (
            revoke_failed["error"]["code"]
            == "source_handoff_clipboard_revoke_failed"
        )
    finally:
        desktop.ReweaveBridge._qobject_cls = None


def test_source_derived_handoff_clipboard_never_returns_token() -> None:
    token = "source_derived_handoff_token_" + "c" * 48
    ui_token = "source_derived_ui_handoff_token_" + "d" * 48

    class Service:
        def __init__(self) -> None:
            self.revoked: list[dict] = []

        @staticmethod
        def create_local_source_derived_handoff(payload: dict):
            token_key = (
                "source_derived_ui_handoff_token"
                if payload.get("action_profile")
                == "source_derived_ui_agent.v1"
                else "source_derived_handoff_token"
            )
            return {
                "ok": True,
                "data": {
                    token_key: (
                        ui_token
                        if token_key
                        == "source_derived_ui_handoff_token"
                        else token
                    ),
                    "created_at": "2026-08-19T00:00:00Z",
                },
            }

        def revoke_local_source_derived_handoff(self, payload: dict):
            self.revoked.append(payload)
            return {
                "ok": True,
                "data": {
                    "schema_version": (
                        "source_derived_handoff_status.v1"
                    ),
                    "status": "revoked",
                },
            }

    service = Service()
    bridge = _bridge(service)
    copied: list[str] = []
    payload = {"source_root_id": "root_source"}
    try:
        with patch.object(
            desktop,
            "_copy_to_system_clipboard",
            side_effect=copied.append,
        ):
            raw = bridge.copy_local_source_derived_handoff_binding(
                json.dumps(payload)
            )
        result = json.loads(raw)
        assert result["data"] == {
            "schema_version": "source_derived_handoff_status.v1",
            "action_profile": "source_derived_agent.v1",
            "status": "active",
            "created_at": "2026-08-19T00:00:00Z",
        }
        assert token not in raw
        assert json.loads(copied[0])["payload"] == {
            "handoff_token": token
        }

        with patch.object(
            desktop,
            "_copy_to_system_clipboard",
            side_effect=copied.append,
        ):
            ui_raw = bridge.copy_local_source_derived_handoff_binding(
                json.dumps(
                    {
                        **payload,
                        "action_profile": "source_derived_ui_agent.v1",
                    }
                )
            )
        ui_result = json.loads(ui_raw)
        assert ui_result["data"]["action_profile"] == (
            "source_derived_ui_agent.v1"
        )
        assert ui_token not in ui_raw
        assert json.loads(copied[1])["payload"] == {
            "handoff_token": ui_token
        }

        with patch.object(
            desktop,
            "_copy_to_system_clipboard",
            side_effect=RuntimeError("clipboard denied"),
        ):
            failed = json.loads(
                bridge.copy_local_source_derived_handoff_binding(
                    json.dumps(payload)
                )
            )
        assert (
            failed["error"]["code"]
            == "source_derived_handoff_clipboard_failed"
        )
        assert service.revoked == [payload]
    finally:
        desktop.ReweaveBridge._qobject_cls = None
