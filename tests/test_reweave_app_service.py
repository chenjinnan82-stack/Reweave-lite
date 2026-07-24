"""Tests for ReweaveAppService initial state."""

from __future__ import annotations

import os
import threading
import unittest
from unittest.mock import patch

from pimos_lite.reweave_app_service import (
    APP_SERVICE_VERSION,
    CAPSULE_MANAGEMENT_ACTIONS,
    LEGACY_WORKBENCH_ACTIONS,
    PUBLIC_PRODUCT_ACTIONS,
    SUPPORT_VIEWER_ACTIONS,
    ReweaveAppService,
    legacy_workbench_actions,
    public_product_actions,
    release_boundary_for_action,
)
from pimos_lite.reweave_engine.local import LocalReweaveEngine
from pimos_lite.reweave_engine.lumo_lite import LumoLiteReweaveEngine


class ReweaveAppServiceTest(unittest.TestCase):
    def test_get_initial_state_includes_app_service_and_engine_status(self) -> None:
        service = ReweaveAppService(engine=LocalReweaveEngine())
        state = service.get_initial_state()
        self.assertEqual(state["appService"], APP_SERVICE_VERSION)
        self.assertEqual(state["engine"], "sqlite_capsule_warehouse")
        self.assertIn("engineStatus", state)
        self.assertTrue(state["engineStatus"]["available"])
        self.assertTrue(state["canGenerateProduct"])
        self.assertTrue(state["canPlanProduct"])
        self.assertFalse(state["canGeneratePreview"])
        self.assertEqual(
            state["productPlanning"]["schema_version"],
            "product_planning_state.v1",
        )
        self.assertEqual(state["productPlanning"]["workspaces"], [])

    def test_lumo_engine_via_service_when_env_set(self) -> None:
        class DownClient:
            def health(self) -> dict:
                return {
                    "ok": False,
                    "base_url": "http://127.0.0.1:8020",
                    "status": "unavailable",
                    "error": "down",
                }

        with patch.dict(os.environ, {"REWEAVE_ENGINE": "lumo"}):
            from pimos_lite.reweave_engine.lumo import LumoReweaveEngine

            service = ReweaveAppService(engine=LumoReweaveEngine(luna_client=DownClient()))
            state = service.get_initial_state()
            self.assertEqual(state["backend"], "sqlite_capsule_warehouse")
            self.assertTrue(state["engineStatus"]["available"])

    def test_lumo_lite_blocked_service_actions_share_release_boundary_shape(self) -> None:
        service = ReweaveAppService(engine=LumoLiteReweaveEngine())
        results = [
            service.create_review_queue_for_source("source_alpha"),
            service.promote_review_item("source_alpha", "review_alpha"),
            service.list_warehouse_capsules(),
            service.update_capsule_status("capsule_alpha", "disabled"),
            service.export_preview_package("package_alpha", "/tmp/export", "zip"),
        ]

        self.assertEqual(
            {item["action"] for item in results},
            {
                "create_review_queue_for_source",
                "promote_review_item",
                "list_warehouse_capsules",
                "update_capsule_status",
                "export_preview_package",
            },
        )
        self.assertTrue(all(item["ok"] is False for item in results))
        self.assertTrue(all(item["engine"] == "lumo_lite" for item in results))
        self.assertTrue(all(item["mode"] == "source_read_only_preview_write" for item in results))
        self.assertTrue(all(item["error"] == "lumo_lite_read_only" for item in results))
        self.assertTrue(all(item["release_boundary"] == "legacy_workbench" for item in results))

    def test_release_boundaries_are_explicit_and_disjoint(self) -> None:
        self.assertFalse(PUBLIC_PRODUCT_ACTIONS & LEGACY_WORKBENCH_ACTIONS)
        self.assertFalse(PUBLIC_PRODUCT_ACTIONS & SUPPORT_VIEWER_ACTIONS)
        self.assertFalse(LEGACY_WORKBENCH_ACTIONS & SUPPORT_VIEWER_ACTIONS)
        self.assertFalse(CAPSULE_MANAGEMENT_ACTIONS & PUBLIC_PRODUCT_ACTIONS)
        self.assertFalse(CAPSULE_MANAGEMENT_ACTIONS & LEGACY_WORKBENCH_ACTIONS)
        self.assertFalse(CAPSULE_MANAGEMENT_ACTIONS & SUPPORT_VIEWER_ACTIONS)
        self.assertEqual(release_boundary_for_action("generate_product"), "public_product")
        for action in (
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
            "start_product_candidate",
            "get_product_candidate_run",
            "get_product_candidate",
            "read_product_candidate_file",
        ):
            self.assertEqual(release_boundary_for_action(action), "public_product")
        self.assertEqual(
            release_boundary_for_action("analyze_static_web_target"),
            "public_product",
        )
        self.assertEqual(
            release_boundary_for_action("generate_static_web_patch"),
            "public_product",
        )
        self.assertEqual(release_boundary_for_action("generate_preview"), "unknown")
        self.assertEqual(release_boundary_for_action("export_preview_package"), "legacy_workbench")
        self.assertEqual(release_boundary_for_action("get_preview_package"), "support_viewer")
        self.assertEqual(release_boundary_for_action("list_review_items"), "capsule_management")
        self.assertEqual(
            release_boundary_for_action("start_inspect_computation_adapters"),
            "capsule_management",
        )
        self.assertEqual(
            release_boundary_for_action("start_create_computation_adapter"),
            "capsule_management",
        )
        self.assertEqual(
            release_boundary_for_action("register_javascript_computation_source"),
            "capsule_management",
        )
        self.assertEqual(
            release_boundary_for_action("start_scan_javascript_computations"),
            "capsule_management",
        )
        self.assertEqual(release_boundary_for_action("made_up_action"), "unknown")
        self.assertIn("generate_product", public_product_actions())
        self.assertIn("start_product_plan", public_product_actions())
        self.assertIn("suggest_product_plan_action", public_product_actions())
        self.assertIn("confirm_product_plan", public_product_actions())
        self.assertIn("start_product_candidate", public_product_actions())
        self.assertIn("get_product_candidate", public_product_actions())
        self.assertIn("analyze_static_web_target", public_product_actions())
        self.assertIn("generate_static_web_patch", public_product_actions())
        self.assertNotIn("generate_preview", public_product_actions())
        self.assertIn("export_preview_package", legacy_workbench_actions())

    def test_revision_targeted_and_edit_requests_are_forwarded_strictly(self) -> None:
        class Cancel:
            @staticmethod
            def is_set() -> bool:
                return False

        class Planner:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            def revise(self, token, request, _catalog, _cancel, *, phase_callback):
                self.calls.append((token, request))
                return {"ok": True, "data": {"forwarded": True}}

        service = object.__new__(ReweaveAppService)
        planner = Planner()
        submissions: list[dict] = []
        service._product_planner = planner
        service._product_planning_catalog = lambda: {}
        def submit(_kind, action, **kwargs):
            submissions.append(kwargs)
            return action(Cancel(), lambda _phase: None)

        service._submit_management_task = submit
        base = {
            "plan_token": "plan_token_public",
            "action": "request",
            "message": "调整数据备份策略",
            "reviewed_plan": {},
            "selected_action": "propose_revision",
            "suggestion_receipt": "suggestion_receipt_public",
            "suggestion_digest": "0" * 64,
        }

        targeted_add = {
            "plan_token": "plan_token_public",
            "action": "request",
            "message": "新增数据备份工作项",
            "target_section_id": "data",
            "target_operation": "add",
            "requirement_refs": ["requirement_public"],
        }
        self.assertTrue(service.revise_product_plan(targeted_add)["ok"])
        self.assertEqual(
            planner.calls[-1][1],
            {key: value for key, value in targeted_add.items() if key != "plan_token"},
        )
        self.assertTrue(submissions[-1]["cancellable"])
        targeted_update = {
            "plan_token": "plan_token_public",
            "action": "request",
            "message": "修改数据工作项",
            "target_section_id": "data",
            "target_operation": "update",
            "target_binding_ref": "work_item_public",
        }
        self.assertTrue(service.revise_product_plan(targeted_update)["ok"])
        self.assertEqual(
            planner.calls[-1][1],
            {
                key: value
                for key, value in targeted_update.items()
                if key != "plan_token"
            },
        )
        self.assertTrue(submissions[-1]["cancellable"])
        self.assertEqual(
            service.revise_product_plan(
                {**targeted_add, "target_binding_ref": "work_item_public"}
            )["error"]["code"],
            "product_plan_revision_invalid",
        )
        self.assertEqual(
            service.revise_product_plan(
                {**targeted_update, "requirement_refs": ["requirement_public"]}
            )["error"]["code"],
            "product_plan_revision_invalid",
        )

        edit = {
            "plan_token": "plan_token_public",
            "action": "edit_diff",
            "expected_diff_digest": "2" * 64,
            "fields": {
                "title": "数据备份与恢复",
                "summary": "每日增量备份，每周全量备份。",
                "acceptance_intent": "完成恢复演练。",
                "delivery_wave": 3,
            },
        }
        self.assertTrue(service.revise_product_plan(edit)["ok"])
        self.assertEqual(
            planner.calls[-1][1],
            {key: value for key, value in edit.items() if key != "plan_token"},
        )
        self.assertEqual(
            service.revise_product_plan({**edit, "fields": []})["error"]["code"],
            "product_plan_revision_invalid",
        )
        self.assertFalse(submissions[-1]["cancellable"])
        for invalid in (
            {**targeted_add, "requirement_refs": "requirement_public"},
            {**targeted_add, "requirement_refs": [None]},
        ):
            self.assertEqual(
                service.revise_product_plan(invalid)["error"]["code"],
                "product_plan_revision_invalid",
            )

        self.assertEqual(
            service.revise_product_plan(base)["error"]["code"],
            "product_plan_revision_invalid",
        )
        wrong_type = {**base, "target_section_id": None}
        self.assertEqual(
            service.revise_product_plan(wrong_type)["error"]["code"],
            "product_plan_revision_invalid",
        )
        forwarded = service.revise_product_plan(
            {**base, "target_section_id": "data"}
        )
        self.assertTrue(forwarded["ok"])
        self.assertEqual(planner.calls[-1][1]["target_section_id"], "data")

        for selected_action in ("ask_plan", "edit_goal"):
            unscoped = {**base, "selected_action": selected_action}
            self.assertTrue(service.revise_product_plan(unscoped)["ok"])
            self.assertNotIn("target_section_id", planner.calls[-1][1])
            scoped = {**unscoped, "target_section_id": "data"}
            self.assertEqual(
                service.revise_product_plan(scoped)["error"]["code"],
                "product_plan_revision_invalid",
            )

        self.assertEqual(
                service.submit_product_plan_answers(
                {
                    "plan_token": "plan_token_public",
                    "question_set_digest": "1" * 64,
                    "answers": [],
                    "target_section_id": "data",
                }
            )["error"]["code"],
            "product_plan_answers_invalid",
        )

    def test_parameter_confirmation_uses_existing_strict_public_action(self) -> None:
        class Planner:
            def __init__(self) -> None:
                self.calls: list[tuple] = []
                self.get_calls: list[tuple] = []
                self.plan: dict = {}
                self.status = "plan_review"
                self.confirmation = None

            def confirm(self, *args):
                self.calls.append(args)
                if args[2] != self.plan:
                    return {
                        "ok": False,
                        "error": {"code": "product_plan_confirmation_stale"},
                    }
                return {"ok": True, "data": {"forwarded": True}}

            def get(self, *args):
                self.get_calls.append(args)
                return {
                    "ok": True,
                    "data": {
                        "status": self.status,
                        "plan": self.plan,
                        "plan_diff": None,
                        "confirmation": self.confirmation,
                    },
                }

        service = object.__new__(ReweaveAppService)
        planner = Planner()
        service._product_planner = planner
        service._capsule_operation_lock = threading.RLock()
        service._product_planning_catalog = lambda: {
            "warehouse_revision": 1,
            "capsules": [],
        }
        loaded = {
            "capsule_id": "capsule_parameterized",
            "version_id": "version_parameterized_1",
            "canonical_hash": "a" * 64,
            "capability_key": "parameterized_quote",
            "capability_kind": "computation",
            "input_contract": {},
            "output_contract": {},
            "private_source": "must-not-forward",
        }
        service._load_generation_capsules = lambda ids, read_only: (
            [loaded],
            {},
        )
        reviewed_plan = {
            "canonical_digest": "b" * 64,
            "sections": [
                {
                    "work_items": [
                        {
                            "capsule_bindings": [
                                {"capsule_id": "capsule_parameterized"}
                            ]
                        }
                    ]
                }
            ]
        }
        planner.plan = reviewed_plan
        base = {
            "plan_token": "plan_token_public",
            "plan_digest": "b" * 64,
            "reviewed_plan": reviewed_plan,
        }
        self.assertTrue(service.confirm_product_plan(base)["ok"])
        self.assertIsNone(planner.calls[-1][5])
        self.assertEqual(
            planner.calls[-1][4],
            [
                {
                    key: loaded[key]
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
            ],
        )
        confirmation = {
            "schema_version": "parameterized_execution_confirmation.v1",
            "offer_digest": "c" * 64,
            "values": [
                {"binding_id": "parameter_binding_public", "value": 10}
            ],
        }
        self.assertTrue(
            service.confirm_product_plan(
                {**base, "parameter_confirmation": confirmation}
            )["ok"]
        )
        self.assertEqual(planner.calls[-1][5], confirmation)
        self.assertEqual(
            service.confirm_product_plan({**base, "extra": True})["error"][
                "code"
            ],
            "product_plan_confirmation_invalid",
        )
        self.assertEqual(
            service.confirm_product_plan(
                {**base, "reviewed_plan": {"sections": 1}}
            )["error"]["code"],
            "product_plan_confirmation_stale",
        )
        self.assertIsNone(planner.calls[-1][4])
        planner.status = "confirmed"
        planner.confirmation = {
            "schema_version": "product_plan_confirmation.v2",
        }
        restored = service.get_product_plan_workspace(
            {"plan_token": "plan_token_public"}
        )
        self.assertTrue(restored["ok"])
        self.assertEqual(len(planner.get_calls[-1]), 3)
        self.assertEqual(
            planner.get_calls[-1][2],
            [
                {
                    key: loaded[key]
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
            ],
        )


if __name__ == "__main__":
    unittest.main()
