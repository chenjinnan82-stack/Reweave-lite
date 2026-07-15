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
        "generate_product",
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
        assert json.loads(bridge.notify_generate(json.dumps(payload))) == {
            "ok": True,
            "run_id": "run_product",
        }
        assert service.payloads == [payload, payload]

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
