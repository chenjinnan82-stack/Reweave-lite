"""Tests for ReweaveAppService initial state."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
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
from pimos_lite.reweave_agent_stdio import (
    AGENT_PROTOCOL_VERSION,
    serve_jsonl,
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
            "record_product_capability_gap_decision",
            "prepare_product_capability_source_proposal",
            "start_product_capability_source_proposal",
            "start_product_capability_replan",
            "confirm_product_candidate_acceptance",
            "create_local_agent_handoff",
            "revoke_local_agent_handoff",
            "list_reusable_product_capabilities",
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
        self.assertIn(
            "record_product_capability_gap_decision",
            public_product_actions(),
        )
        self.assertIn(
            "prepare_product_capability_source_proposal",
            public_product_actions(),
        )
        self.assertIn(
            "start_product_capability_source_proposal",
            public_product_actions(),
        )
        self.assertIn(
            "start_product_capability_replan",
            public_product_actions(),
        )
        self.assertIn(
            "confirm_product_candidate_acceptance",
            public_product_actions(),
        )
        self.assertIn("create_local_agent_handoff", public_product_actions())
        self.assertIn("revoke_local_agent_handoff", public_product_actions())
        self.assertIn(
            "list_reusable_product_capabilities",
            public_product_actions(),
        )
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

    def test_capability_gap_decision_action_forwards_only_client_decision(
        self,
    ) -> None:
        class Planner:
            def __init__(self) -> None:
                self.calls: list[tuple] = []

            def record_capability_gap_decision(self, *args):
                self.calls.append(args)
                return {"ok": True, "data": {"capability_gaps": []}}

        service = object.__new__(ReweaveAppService)
        planner = Planner()
        catalog = {"warehouse_revision": 41, "capsules": []}
        service._product_planner = planner
        service._capsule_operation_lock = threading.RLock()
        service._product_planning_catalog = lambda: catalog
        request = {
            "plan_token": "plan_token_public",
            "plan_digest": "a" * 64,
            "projection_digest": "b" * 64,
            "expected_previous_decision_digest": None,
            "decision": "authorize",
            "behavior_intent": "按数量计算折扣单价。",
            "reason": None,
            "acceptance_cases": [
                {
                    "input": {"quantity": 5},
                    "expected_output": {
                        "quantity": 5,
                        "unit_price": 80,
                    },
                }
            ],
        }

        result = service.record_product_capability_gap_decision(request)

        self.assertTrue(result["ok"])
        self.assertEqual(
            planner.calls,
            [
                (
                    request["plan_token"],
                    request["plan_digest"],
                    request["projection_digest"],
                    None,
                    request["decision"],
                    request["behavior_intent"],
                    None,
                    request["acceptance_cases"],
                    catalog,
                )
            ],
        )
        self.assertEqual(
            service.record_product_capability_gap_decision(
                {**request, "capsule_id": "not-accepted"}
            )["error"]["code"],
            "capability_gap_decision_invalid",
        )

    def test_capability_gap_decision_action_needs_no_enum_specific_fields(
        self,
    ) -> None:
        class Planner:
            calls: list[tuple] = []

            def record_capability_gap_decision(self, *args):
                self.calls.append(args)
                return {"ok": True, "data": {"capability_gaps": []}}

        service = object.__new__(ReweaveAppService)
        planner = Planner()
        catalog = {"warehouse_revision": 67, "capsules": []}
        service._product_planner = planner
        service._capsule_operation_lock = threading.RLock()
        service._product_planning_catalog = lambda: catalog
        request = {
            "plan_token": "plan_token_public",
            "plan_digest": "a" * 64,
            "projection_digest": "b" * 64,
            "expected_previous_decision_digest": None,
            "decision": "authorize",
            "behavior_intent": "根据两个布尔条件返回有限状态。",
            "reason": None,
            "acceptance_cases": [
                {
                    "input": {"enabled": True, "verified": False},
                    "expected_output": {"access_state": "limited"},
                }
            ],
        }
        result = service.record_product_capability_gap_decision(request)
        self.assertTrue(result["ok"])
        self.assertEqual(planner.calls[0][-1], catalog)
        self.assertEqual(planner.calls[0][7], request["acceptance_cases"])

    def test_capability_replan_action_accepts_only_historical_locators(
        self,
    ) -> None:
        class Planner:
            def __init__(self) -> None:
                self.calls: list[tuple] = []

            @staticmethod
            def _workspace_by_token(_token):
                return {"plan": {"canonical_digest": "a" * 64}}

            @staticmethod
            def _read_capability_replan_handoff(_workspace):
                return None

            def start_capability_replan(self, *args, **kwargs):
                self.calls.append((*args, kwargs))
                return {
                    "ok": True,
                    "data": {
                        "plan_token": "plan_token_successor",
                        "status": "plan_review",
                    },
                }

        service = object.__new__(ReweaveAppService)
        planner = Planner()
        catalog = {"warehouse_revision": 57, "capsules": []}
        binding = {"publication_revision": 57}
        service._product_planner = planner
        service._product_planning_catalog = lambda: catalog
        service._resolve_product_capability_replan = (
            lambda *_args: (binding, {"members": []}, {})
        )

        def submit(kind, action, **options):
            self.assertEqual(kind, "product_plan_capability_replan")
            self.assertTrue(options["cancellable"])
            self.assertTrue(options["read_only_planning"])
            self.assertTrue(options["planning_progress"])
            return action(threading.Event(), lambda _phase: None)

        service._submit_management_task = submit
        request = {
            "plan_token": "plan_token_source",
            "plan_digest": "a" * 64,
            "projection_digest": "b" * 64,
        }
        result = service.start_product_capability_replan(request)

        self.assertTrue(result["ok"])
        self.assertEqual(planner.calls[0][:5], (
            request["plan_token"],
            request["plan_digest"],
            request["projection_digest"],
            binding,
            catalog,
        ))
        self.assertEqual(
            service.start_product_capability_replan(
                {**request, "goal": "client must not submit this"}
            )["error"]["code"],
            "capability_replan_unavailable",
        )

    def test_capability_replan_projection_starts_after_source_review_publication(
        self,
    ) -> None:
        plan_token = "plan_token_source"
        review_id = "review_source"

        class Planner:
            @staticmethod
            def get(_token, _catalog):
                return {
                    "ok": True,
                    "data": {
                        "plan_token": plan_token,
                        "plan": {"canonical_digest": "a" * 64},
                        "confirmation": None,
                        "capability_replan": None,
                        "capability_gaps": [
                            {
                                "source_proposal_run": {
                                    "status": "review_required",
                                    "review_id": review_id,
                                }
                            }
                        ],
                    },
                }

            @staticmethod
            def _workspace_by_token(_token):
                return {"plan_token": plan_token}

            @staticmethod
            def _read_capability_gap_projection(_workspace):
                return {"projection_digest": "b" * 64}

        service = object.__new__(ReweaveAppService)
        service._capsule_operation_lock = threading.RLock()
        service._product_planner = Planner()
        service._product_planning_catalog = lambda: {
            "warehouse_revision": 55,
            "capsules": [],
        }
        outcome = {"status": "review_required", "review_id": review_id}
        service._capability_source_proposal_review_outcome = (
            lambda _review_id: dict(outcome)
        )
        replan_calls: list[tuple] = []

        def replan_view(*args):
            replan_calls.append(args)
            return {"status": "available"}

        service._product_capability_replan_view = replan_view

        waiting = service.get_product_plan_workspace(
            {"plan_token": plan_token}
        )
        self.assertTrue(waiting["ok"])
        self.assertIsNone(waiting["data"]["capability_replan"])
        self.assertEqual(
            waiting["data"]["capability_gaps"][0][
                "source_proposal_run"
            ]["review_outcome"]["status"],
            "review_required",
        )
        self.assertEqual(replan_calls, [])

        outcome["status"] = "rejected"
        rejected = service.get_product_plan_workspace(
            {"plan_token": plan_token}
        )
        self.assertIsNone(rejected["data"]["capability_replan"])
        self.assertEqual(replan_calls, [])

        outcome["status"] = "published"
        published = service.get_product_plan_workspace(
            {"plan_token": plan_token}
        )
        self.assertEqual(
            published["data"]["capability_replan"],
            {"status": "available"},
        )
        self.assertEqual(len(replan_calls), 1)

    def test_source_proposal_prepare_action_accepts_only_lock_digests(
        self,
    ) -> None:
        class Planner:
            def __init__(self) -> None:
                self.calls: list[tuple] = []

            def prepare_capability_source_proposal(self, *args):
                self.calls.append(args)
                return {"ok": True, "data": {"capability_gaps": []}}

        service = object.__new__(ReweaveAppService)
        planner = Planner()
        catalog = {"warehouse_revision": 42, "capsules": []}
        service._product_planner = planner
        service._capsule_operation_lock = threading.RLock()
        service._product_planning_catalog = lambda: catalog
        request = {
            "plan_token": "plan_token_public",
            "plan_digest": "a" * 64,
            "projection_digest": "b" * 64,
            "authorize_decision_digest": "c" * 64,
        }

        result = service.prepare_product_capability_source_proposal(request)

        self.assertTrue(result["ok"])
        self.assertEqual(
            planner.calls,
            [
                (
                    request["plan_token"],
                    request["plan_digest"],
                    request["projection_digest"],
                    request["authorize_decision_digest"],
                    catalog,
                )
            ],
        )
        self.assertEqual(
            service.prepare_product_capability_source_proposal(
                {**request, "capability_key": "not-accepted"}
            )["error"]["code"],
            "capability_source_proposal_authorization_invalid",
        )

    def test_source_proposal_prepare_accepts_finite_enum_v2_authorization(
        self,
    ) -> None:
        from tests.test_reweave_product_planner import (
            StubPlanner,
            finite_enum_gap_catalog,
            start_quote_gap_plan,
        )

        with tempfile.TemporaryDirectory() as temporary:
            planner = StubPlanner(Path(temporary) / "product_workspaces")
            catalog = finite_enum_gap_catalog()
            created = start_quote_gap_plan(planner, catalog)
            plan = created["data"]["plan"]
            projection = created["data"]["capability_gaps"][0]["projection"]
            authorized = planner.record_capability_gap_decision(
                created["data"]["plan_token"],
                plan["canonical_digest"],
                projection["projection_digest"],
                None,
                "authorize",
                "根据两个布尔条件返回有限状态。",
                None,
                [
                    {
                        "input": {"important": True, "urgent": True},
                        "expected_output": {"priority": "do_now"},
                    }
                ],
                catalog,
            )
            decision = authorized["data"]["capability_gaps"][0][
                "current_decision"
            ]
            service = object.__new__(ReweaveAppService)
            service._product_planner = planner
            service._capsule_operation_lock = threading.RLock()
            service._product_planning_catalog = lambda: catalog
            result = service.prepare_product_capability_source_proposal(
                {
                    "plan_token": created["data"]["plan_token"],
                    "plan_digest": plan["canonical_digest"],
                    "projection_digest": projection["projection_digest"],
                    "authorize_decision_digest": decision["canonical_digest"],
                }
            )
            self.assertTrue(result["ok"])
            workspace = planner._workspace_by_token(
                created["data"]["plan_token"]
            )
            self.assertFalse(
                planner._capability_source_proposal_authorization_path(
                    workspace,
                    plan,
                ).exists()
            )
            authorization = json.loads(
                planner._capability_source_proposal_authorization_v2_path(
                    workspace,
                    plan,
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                authorization["schema_version"],
                "capability_source_proposal_authorization.v2",
            )
            self.assertEqual(
                authorization["request"]["schema_version"],
                "capability_source_proposal_request.v4",
            )

    def test_source_proposal_capture_v4_uses_witnesses_before_user_cases(
        self,
    ) -> None:
        input_contract = {
            "schema": "data_contract.v1",
            "type": "object",
            "properties": {
                "important": {"type": "boolean"},
                "urgent": {"type": "boolean"},
            },
            "required": ["important", "urgent"],
            "additional_properties": False,
        }
        output_contract = {
            "schema": "data_contract.v1",
            "type": "object",
            "properties": {
                "priority": {
                    "type": "string",
                    "min_length": 4,
                    "max_length": 8,
                    "enum": ["delegate", "do_now", "drop", "schedule"],
                }
            },
            "required": ["priority"],
            "additional_properties": False,
        }
        authorization = {
            "schema_version": "capability_source_proposal_authorization.v2",
            "input_contract": input_contract,
            "output_contract": output_contract,
            "error_contract": {"schema": "error_contract.v1", "errors": {}},
            "adapter_contract_version": "computation_adapter.v4",
            "capture_mapping_schema": "computation_capture_mapping.v4",
            "proof_schema": "source_graph_proof.v2",
            "result_field": "priority",
            "result_enum": ["delegate", "do_now", "drop", "schedule"],
            "passthrough_fields": [],
            "acceptance_cases": [
                {
                    "input": {"important": True, "urgent": True},
                    "expected_output": {"priority": "do_now"},
                }
            ],
        }
        witnesses = [
            (False, True, "delegate"),
            (True, True, "do_now"),
            (False, False, "drop"),
            (True, False, "schedule"),
        ]
        proposal = {
            "schema": "capability_source_proposal.v2",
            "witnesses": [
                {
                    "input": {
                        "important": important,
                        "urgent": urgent,
                    },
                    "expected_scalar_result": result,
                }
                for important, urgent, result in witnesses
            ],
        }
        offer = {
            "module_relpath": "capability.js",
            "export_name": "compute",
            "target_binding_id": "a" * 64,
            "parameters": [
                {"parameter_binding_id": "b" * 64, "name": "arg0"},
                {"parameter_binding_id": "c" * 64, "name": "arg1"},
            ],
        }
        selection, mapping = (
            ReweaveAppService._capability_source_proposal_capture_request(
                authorization,
                offer,
                proposal,
            )
        )
        self.assertEqual(selection["target_binding_id"], "a" * 64)
        self.assertEqual(
            [item["kind"] for item in mapping["arguments"]],
            ["boolean", "boolean"],
        )
        self.assertEqual(
            mapping["schema"],
            "computation_capture_mapping.v4",
        )
        self.assertEqual(mapping["proof_schema"], "source_graph_proof.v2")
        self.assertEqual(
            [
                item["expected"]["priority"]
                for item in mapping["examples"]
            ],
            authorization["result_enum"],
        )
        conflicting = copy.deepcopy(authorization)
        conflicting["acceptance_cases"][0]["expected_output"]["priority"] = (
            "drop"
        )
        with self.assertRaisesRegex(
            Exception,
            "capability_source_proposal_capture_invalid",
        ):
            ReweaveAppService._capability_source_proposal_capture_request(
                conflicting,
                offer,
                proposal,
            )

    def test_source_proposal_run_action_uses_frozen_server_identities(
        self,
    ) -> None:
        class Planner:
            calls: list[tuple] = []

            def prepare_capability_source_proposal_run(self, *args):
                self.calls.append(args)
                return {
                    "created": True,
                    "run_id": "run_" + "1" * 32,
                    "status": "pending",
                    "stage": "source_proposal",
                }

        class Supervisor:
            @staticmethod
            def selected_model():
                return {"name": "supervisor", "digest": "d" * 64}

        service = object.__new__(ReweaveAppService)
        planner = Planner()
        service._product_planner = planner
        service._capsule_supervisor = Supervisor()
        service._capsule_operation_lock = threading.RLock()
        service._ensure_capsule_management = lambda: None
        catalog = {"warehouse_revision": 57, "capsules": []}
        service._product_planning_catalog = lambda: catalog
        submitted: list[tuple] = []

        def submit(kind, action, **options):
            submitted.append((kind, options))
            return {
                "ok": True,
                "run_id": options["run_id"],
                "status": "queued",
            }

        service._submit_management_task = submit
        request = {
            "plan_token": "plan_token_public",
            "plan_digest": "a" * 64,
            "projection_digest": "b" * 64,
            "authorization_digest": "c" * 64,
        }

        result = service.start_product_capability_source_proposal(request)

        self.assertTrue(result["ok"])
        self.assertEqual(
            planner.calls,
            [
                (
                    request["plan_token"],
                    request["plan_digest"],
                    request["projection_digest"],
                    request["authorization_digest"],
                    {"name": "supervisor", "digest": "d" * 64},
                    catalog,
                )
            ],
        )
        self.assertEqual(
            submitted,
            [
                (
                    "capability_source_proposal",
                    {
                        "run_id": "run_" + "1" * 32,
                        "cancellable": True,
                    },
                )
            ],
        )
        self.assertEqual(
            service.start_product_capability_source_proposal(
                {**request, "source": "client-must-not-submit"}
            )["error"]["code"],
            "capability_source_proposal_run_invalid",
        )

    def test_prepared_review_runtime_digests_hash_stage3_bytes(self) -> None:
        class Prepared:
            candidate_payload_json = b'{"candidate":"ready"}'
            preflight_receipt_json = b'{"runtime":"passed"}'

        self.assertEqual(
            ReweaveAppService._prepared_review_runtime_digests(Prepared()),
            {
                "capture_digest": hashlib.sha256(
                    Prepared.candidate_payload_json
                ).hexdigest(),
                "runtime_digest": hashlib.sha256(
                    Prepared.preflight_receipt_json
                ).hexdigest(),
            },
        )

    def test_frozen_product_review_limits_user_decisions(self) -> None:
        frozen = {
            "candidate_status": "review_required",
            "candidate": {
                "adapter_contract_version": "computation_adapter.v3",
                "frozen_review_admission": {
                    "schema": "frozen_stage3_review_admission.v2",
                },
            },
        }
        ordinary_v3 = {
            "candidate_status": "review_required",
            "candidate": {
                "adapter_contract_version": "computation_adapter.v3",
            },
        }

        self.assertEqual(
            ReweaveAppService._allowed_review_decisions(frozen),
            ["publish_general", "reject"],
        )
        self.assertEqual(
            ReweaveAppService._allowed_review_decisions(ordinary_v3),
            ["reject"],
        )

    def test_source_proposal_run_poll_recovers_or_cancels_without_retry(
        self,
    ) -> None:
        run_id = "run_" + "2" * 32

        class Planner:
            status = "running"
            appended: list[dict] = []

            def get_capability_source_proposal_run(self, current_run_id):
                assert current_run_id == run_id
                return {
                    "run_id": run_id,
                    "status": self.status,
                    "stage": "runtime",
                }

            def append_capability_source_proposal_run_event(
                self, current_run_id, **event
            ):
                assert current_run_id == run_id
                self.appended.append(event)
                self.status = event["status"]
                return {
                    "run_id": run_id,
                    "status": event["status"],
                    "stage": event["stage"],
                    "error_code": event["error_code"],
                }

        service = object.__new__(ReweaveAppService)
        planner = Planner()
        service._product_planner = planner
        service._management_lock = threading.RLock()
        service._management_tasks = {}

        recovered = service.get_intake_run({"run_id": run_id})

        self.assertTrue(recovered["ok"])
        self.assertEqual(recovered["data"]["status"], "failed")
        self.assertEqual(
            planner.appended,
            [
                {
                    "status": "failed",
                    "stage": "runtime",
                    "error_code": "manual_recovery_required",
                }
            ],
        )

        planner.status = "running"
        cancel = threading.Event()
        service._management_tasks[run_id] = {
            "kind": "capability_source_proposal",
            "cancel_event": cancel,
        }
        result = service.cancel_intake_run({"run_id": run_id})

        self.assertTrue(result["ok"])
        self.assertTrue(cancel.is_set())

    def test_agent_jsonl_protocol_is_strict_and_redacts_capability_details(
        self,
    ) -> None:
        class Service:
            @staticmethod
            def _resolve_local_agent_handoff(token):
                if token != "handoff_token_" + "1" * 48:
                    raise ValueError("invalid")
                return {
                    "plan_token": "plan_token_internal",
                    "plan_digest": "a" * 64,
                    "acceptance_confirmation_digest": "b" * 64,
                }

            @staticmethod
            def list_reusable_product_capabilities(_payload):
                return {
                    "ok": True,
                    "data": {
                        "schema_version": (
                            "reweave_reusable_capability_catalog.v1"
                        ),
                        "warehouse_revision": 1,
                        "capabilities": [
                            {
                                "capsule_id": "capsule_1",
                                "version_id": "version_1",
                                "display_name": "报价计算",
                                "capability_key": "quote",
                                "role_key": "compute",
                                "variant_key": "default",
                                "capability_kind": "computation",
                                "canonical_hash": "a" * 64,
                                "identity_status": "formal_exact_version",
                                "input_contract": {},
                                "output_contract": {},
                                "source": {
                                    "status": "formal_exact_source_verified",
                                    "relationship": "exact",
                                },
                                "source_relpath": "/private/source.js",
                                "html_text": "<main>private</main>",
                            }
                        ],
                    },
                }

        requests = "\n".join(
            [
                json.dumps(
                    {
                        "protocol": AGENT_PROTOCOL_VERSION,
                        "id": "unbound",
                        "action": "list_reusable_product_capabilities",
                        "payload": {},
                    }
                ),
                json.dumps(
                    {
                        "protocol": AGENT_PROTOCOL_VERSION,
                        "id": "bind",
                        "action": "bind_user_handoff",
                        "payload": {
                            "handoff_token": "handoff_token_" + "1" * 48
                        },
                    }
                ),
                json.dumps(
                    {
                        "protocol": AGENT_PROTOCOL_VERSION,
                        "id": "catalog",
                        "action": "list_reusable_product_capabilities",
                        "payload": {},
                    }
                ),
                json.dumps(
                    {
                        "protocol": "reweave_agent_jsonl.v0",
                        "id": "old",
                        "action": "list_reusable_product_capabilities",
                        "payload": {},
                    }
                ),
                "{not-json",
            ]
        )
        output = io.StringIO()
        serve_jsonl(Service(), io.StringIO(requests), output)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[0]["error"]["code"], "agent_session_unbound")
        self.assertTrue(rows[1]["ok"])
        self.assertEqual(rows[1]["data"], {"status": "bound"})
        self.assertTrue(rows[2]["ok"])
        public = json.dumps(rows[2], ensure_ascii=False)
        self.assertNotIn("handoff_token_", json.dumps(rows[1]))
        self.assertNotIn("source_relpath", public)
        self.assertNotIn("/private/", public)
        self.assertNotIn("html_text", public)
        self.assertNotIn("capsule_id", public)
        self.assertNotIn("version_id", public)
        self.assertNotIn("canonical_hash", public)
        self.assertEqual(
            rows[3]["error"]["code"],
            "agent_protocol_version_invalid",
        )
        self.assertEqual(rows[4]["error"]["code"], "agent_json_invalid")


if __name__ == "__main__":
    unittest.main()
