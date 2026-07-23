"""Confirmed plan execution and isolated product candidate tests."""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_capsule_store import CapsuleWarehouseStore
from pimos_lite.reweave_plan_execution import (
    PlanExecutionError,
    canonical_bytes,
    canonical_digest,
    compile_plan_execution,
)
from pimos_lite.reweave_product_planner import (
    PLAN_SCHEMA_VERSION,
    PLANNING_PROMPT_VERSION,
    PLANNING_RULES_VERSION,
)
from tests.test_reweave_phase5_generation import (
    _NoLegacyEngine,
    _quality_receipt,
    _runtime_receipt,
    _seed_capsule,
)


NOW = "2026-07-23T00:00:00Z"
SECTIONS = ("frontend", "backend", "data", "infrastructure")


class _ConfirmedPlanner:
    def __init__(self, plan: dict, confirmation: dict) -> None:
        self.plan = copy.deepcopy(plan)
        self.confirmation = copy.deepcopy(confirmation)

    def get(self, _token: str, _catalog: dict) -> dict:
        return {
            "ok": True,
            "data": {
                "status": "confirmed",
                "plan": copy.deepcopy(self.plan),
                "confirmation": copy.deepcopy(self.confirmation),
            },
        }


def _binding(capsule: dict) -> dict:
    display_names = {
        "presentation": "报价结果呈现",
        "interaction": "报价参数输入",
        "computation": "报价计算",
    }
    return {
        "capsule_id": capsule["capsule_id"],
        "version_id": capsule["version_id"],
        "display_name": display_names[capsule["capability_kind"]],
        "capability_kind": capsule["capability_kind"],
        "canonical_hash": capsule["canonical_hash"],
        "identity_status": "formal_exact_version",
        "selection_status": "model_suggested",
        "review_status": "user_confirmed",
        "reason": "Exact formal capability selected for the bounded plan.",
    }


def _confirmed_plan(
    capsules: list[dict],
    warehouse_revision: int,
) -> tuple[dict, dict]:
    by_kind = {capsule["capability_kind"]: capsule for capsule in capsules}
    chosen = (
        by_kind["presentation"],
        by_kind["interaction"],
        by_kind["computation"],
        by_kind["presentation"],
    )
    goal = "构建一个可运行的本地报价计算产品。"
    goal_digest = canonical_digest(goal)
    requirements = [
        {
            "requirement_id": f"requirement_{index:02d}",
            "statement": f"正式需求 {index}",
            "source": "product_goal",
            "source_digest": goal_digest,
        }
        for index in range(1, 5)
    ]
    sections = []
    previous = None
    for index, (section_id, capsule) in enumerate(zip(SECTIONS, chosen), start=1):
        work_id = f"work_item_{index:02d}"
        section_names = {
            "frontend": "前端交互与报价结果",
            "backend": "本地输入处理",
            "data": "确定性报价计算",
            "infrastructure": "本地运行与验证",
        }
        sections.append(
            {
                "section_id": section_id,
                "summary": section_names[section_id],
                "work_items": [
                    {
                        "work_item_id": work_id,
                        "title": section_names[section_id],
                        "description": "复用正式胶囊完成该章节的有界能力。",
                        "requirement_ids": [f"requirement_{index:02d}"],
                        "depends_on": [] if previous is None else [previous],
                        "acceptance_intent": "组合后的产品在本机隔离环境中可运行。",
                        "capsule_bindings": [_binding(capsule)],
                        "gap_reason": None,
                    }
                ],
                "gaps": [],
            }
        )
        previous = work_id
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": "plan_" + "1" * 32,
        "plan_version": 1,
        "parent_plan_digest": None,
        "product_name": "本地报价产品",
        "goal": goal,
        "goal_digest": goal_digest,
        "language": "zh",
        "requirements": requirements,
        "planning_answers": [],
        "sections": sections,
        "model": {
            "name": "contract-test-model",
            "digest": "2" * 64,
            "parameter_count": 1,
            "parameter_size": "1B",
        },
        "planning_rules_version": PLANNING_RULES_VERSION,
        "prompt_version": PLANNING_PROMPT_VERSION,
        "structured_response_digests": ["3" * 64],
        "warehouse_revision": warehouse_revision,
        "candidate_generated": False,
        "product_generated": False,
    }
    plan["canonical_digest"] = canonical_digest(plan)
    confirmation = {
        "schema_version": "product_plan_confirmation.v1",
        "plan_id": plan["plan_id"],
        "plan_version": plan["plan_version"],
        "plan_digest": plan["canonical_digest"],
        "confirmed_at": NOW,
        "capsule_revalidation": [
            {
                "capsule_id": binding["capsule_id"],
                "version_id": binding["version_id"],
                "eligibility_status": "active_current_eligible",
                "review_status": "user_confirmed",
            }
            for section in plan["sections"]
            for item in section["work_items"]
            for binding in item["capsule_bindings"]
        ],
        "warehouse_revision": warehouse_revision,
        "product_generated": False,
        "candidate_generated": False,
        "product_usage_written": False,
    }
    confirmation["receipt_digest"] = canonical_digest(confirmation)
    return plan, confirmation


def _refresh(plan: dict, confirmation: dict) -> None:
    plan["canonical_digest"] = canonical_digest(
        {key: value for key, value in plan.items() if key != "canonical_digest"}
    )
    confirmation["plan_digest"] = plan["canonical_digest"]
    confirmation["receipt_digest"] = canonical_digest(
        {
            key: value
            for key, value in confirmation.items()
            if key != "receipt_digest"
        }
    )


def _poll(service: ReweaveAppService, run_id: str) -> dict:
    for _ in range(3000):
        response = service.get_product_candidate_run({"run_id": run_id})
        if response["ok"] and response["data"]["status"] in {
            "completed",
            "failed",
            "cancelled",
        }:
            return response["data"]
        time.sleep(0.01)
    raise AssertionError("candidate run did not finish")


def _store_snapshot(store: CapsuleWarehouseStore) -> dict:
    tables = (
        "warehouse_state",
        "capability_groups",
        "capsules",
        "capsule_versions",
        "capsule_assets",
        "capsule_sources",
        "product_capsule_usage",
    )
    with store.read_connection() as connection:
        return {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
            for table in tables
        }


@unittest.skipUnless(shutil.which("node"), "Node.js is required")
class PlanExecutionV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.environment = patch.dict(
            os.environ,
            {"REWEAVE_STATE_DIR": str(self.state)},
        )
        self.environment.start()
        self.store = CapsuleWarehouseStore(self.state / "capsule_warehouse.sqlite3")
        self.store.initialize()
        self.service = ReweaveAppService(_NoLegacyEngine(), capsule_store=self.store)
        for kind in ("presentation", "interaction", "computation"):
            _seed_capsule(self.store, kind)
        self.capsules, _scope = self.service._load_generation_capsules(
            ["capsule_presentation", "capsule_interaction", "capsule_computation"],
            read_only=True,
        )
        revision = self.service._product_planning_catalog()["warehouse_revision"]
        self.plan, self.confirmation = _confirmed_plan(self.capsules, revision)

    def tearDown(self) -> None:
        self.service.close()
        self.environment.stop()
        self.temporary.cleanup()

    def test_compiler_is_deterministic_and_fail_closed(self) -> None:
        first = compile_plan_execution(
            self.plan,
            self.confirmation,
            self.capsules,
        )
        second = compile_plan_execution(
            copy.deepcopy(self.plan),
            copy.deepcopy(self.confirmation),
            copy.deepcopy(self.capsules),
        )
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertEqual(len(first["execution_units"]), 4)
        self.assertEqual(
            [unit["sequence"] for unit in first["execution_units"]],
            [1, 2, 3, 4],
        )
        self.assertEqual(len(first["capsules"]), 3)
        self.assertEqual(
            set(first["composer_request"]["capsule_ids"]),
            {"capsule_presentation", "capsule_interaction", "capsule_computation"},
        )
        by_work = {
            unit["work_item_id"]: unit for unit in first["execution_units"]
        }
        self.assertEqual(by_work["work_item_01"]["depends_on"], [])
        self.assertEqual(
            by_work["work_item_02"]["depends_on"],
            [by_work["work_item_01"]["execution_unit_id"]],
        )

        gap_plan = copy.deepcopy(self.plan)
        gap_confirmation = copy.deepcopy(self.confirmation)
        gap_plan["sections"][0]["gaps"] = [
            {
                "gap_id": "gap_01",
                "title": "unsupported",
                "reason": "missing formal capsule",
                "requirement_ids": ["requirement_01"],
            }
        ]
        _refresh(gap_plan, gap_confirmation)
        with self.assertRaisesRegex(PlanExecutionError, "plan_execution_gap_present"):
            compile_plan_execution(gap_plan, gap_confirmation, self.capsules)

        stale_plan = copy.deepcopy(self.plan)
        stale_confirmation = copy.deepcopy(self.confirmation)
        stale_plan["sections"][0]["work_items"][0]["capsule_bindings"][0][
            "canonical_hash"
        ] = "f" * 64
        _refresh(stale_plan, stale_confirmation)
        with self.assertRaisesRegex(PlanExecutionError, "plan_execution_binding_stale"):
            compile_plan_execution(stale_plan, stale_confirmation, self.capsules)

        dependency_plan = copy.deepcopy(self.plan)
        dependency_confirmation = copy.deepcopy(self.confirmation)
        dependency_plan["sections"][1]["work_items"][0]["depends_on"] = [
            "work_item_unknown"
        ]
        _refresh(dependency_plan, dependency_confirmation)
        with self.assertRaisesRegex(
            PlanExecutionError,
            "plan_execution_dependency_invalid",
        ):
            compile_plan_execution(
                dependency_plan,
                dependency_confirmation,
                self.capsules,
            )

        cycle_plan = copy.deepcopy(self.plan)
        cycle_confirmation = copy.deepcopy(self.confirmation)
        cycle_plan["sections"][0]["work_items"][0]["depends_on"] = [
            "work_item_04"
        ]
        _refresh(cycle_plan, cycle_confirmation)
        with self.assertRaisesRegex(
            PlanExecutionError,
            "plan_execution_dependency_cycle",
        ):
            compile_plan_execution(cycle_plan, cycle_confirmation, self.capsules)

        mixed_capsules = copy.deepcopy(self.capsules)
        mixed_capsules[0]["capability_key"] = "different_group"
        with self.assertRaisesRegex(
            PlanExecutionError,
            "plan_execution_capability_group_mismatch",
        ):
            compile_plan_execution(self.plan, self.confirmation, mixed_capsules)

        duplicate_plan = copy.deepcopy(self.plan)
        duplicate_confirmation = copy.deepcopy(self.confirmation)
        duplicate_capsules = copy.deepcopy(self.capsules)
        computation = next(
            capsule
            for capsule in duplicate_capsules
            if capsule["capability_kind"] == "computation"
        )
        computation["capability_kind"] = "presentation"
        data_binding = duplicate_plan["sections"][2]["work_items"][0][
            "capsule_bindings"
        ][0]
        data_binding["capability_kind"] = "presentation"
        _refresh(duplicate_plan, duplicate_confirmation)
        with self.assertRaisesRegex(
            PlanExecutionError,
            "plan_execution_capability_kind_duplicate",
        ):
            compile_plan_execution(
                duplicate_plan,
                duplicate_confirmation,
                duplicate_capsules,
            )

        no_dom_plan = copy.deepcopy(self.plan)
        no_dom_confirmation = copy.deepcopy(self.confirmation)
        computation = next(
            capsule
            for capsule in self.capsules
            if capsule["capability_kind"] == "computation"
        )
        for section in no_dom_plan["sections"]:
            section["work_items"][0]["capsule_bindings"] = [_binding(computation)]
        no_dom_confirmation["capsule_revalidation"] = [
            {
                "capsule_id": computation["capsule_id"],
                "version_id": computation["version_id"],
                "eligibility_status": "active_current_eligible",
                "review_status": "user_confirmed",
            }
            for _section in no_dom_plan["sections"]
        ]
        _refresh(no_dom_plan, no_dom_confirmation)
        with self.assertRaisesRegex(
            PlanExecutionError,
            "plan_execution_dom_capsule_required",
        ):
            compile_plan_execution(no_dom_plan, no_dom_confirmation, self.capsules)

    def test_candidate_is_isolated_idempotent_and_recoverable(self) -> None:
        self.service._product_planner = _ConfirmedPlanner(
            self.plan,
            self.confirmation,
        )
        before = _store_snapshot(self.store)
        source = self.root / "source-sentinel"
        target = self.root / "target-sentinel"
        source.write_text("source unchanged\n", encoding="utf-8")
        target.write_text("target unchanged\n", encoding="utf-8")
        products = self.state / "products"

        with (
            patch(
                "pimos_lite.reweave_app_service._validate_product_static",
                _quality_receipt,
            ),
            patch(
                "pimos_lite.reweave_app_service._validate_product_runtime",
                _runtime_receipt,
            ),
        ):
            started = self.service.start_product_candidate(
                {
                    "plan_token": "plan_token_test",
                    "plan_digest": self.plan["canonical_digest"],
                }
            )
            self.assertTrue(started["ok"])
            task = _poll(self.service, started["run_id"])
            self.assertEqual(task["status"], "completed", task)
            candidate = task["data"]["data"]
            self.assertEqual(candidate["schema_version"], "product_candidate.v1")
            self.assertEqual(candidate["status"], "review_ready")
            self.assertNotIn("candidate_id", candidate)
            self.assertTrue(candidate["validation"]["static"]["status"] == "passed")
            self.assertTrue(candidate["validation"]["runtime"]["status"] == "passed")
            self.assertEqual(
                {row["path"] for row in candidate["provenance"]["file_provenance"]},
                {row["path"] for row in candidate["files"]},
            )
            self.assertTrue(
                all(
                    row["execution_unit_ids"]
                    and row["work_item_ids"]
                    and row["capsule_version_ids"]
                    for row in candidate["provenance"]["file_provenance"]
                )
            )

            repeated = self.service.start_product_candidate(
                {
                    "plan_token": "plan_token_test",
                    "plan_digest": self.plan["canonical_digest"],
                }
            )
            repeated_task = _poll(self.service, repeated["run_id"])
            repeated_candidate = repeated_task["data"]["data"]
            self.assertEqual(
                repeated_candidate["candidate_token"],
                candidate["candidate_token"],
            )
            self.assertEqual(
                repeated_candidate["candidate_digest"],
                candidate["candidate_digest"],
            )

            second_state = self.root / "second-state"
            second_store = CapsuleWarehouseStore(
                second_state / "capsule_warehouse.sqlite3"
            )
            second_store.initialize()
            second_service = ReweaveAppService(
                _NoLegacyEngine(),
                capsule_store=second_store,
            )
            try:
                for kind in ("presentation", "interaction", "computation"):
                    _seed_capsule(second_store, kind)
                second_service._product_planner = _ConfirmedPlanner(
                    self.plan,
                    self.confirmation,
                )
                reproduced = second_service.start_product_candidate(
                    {
                        "plan_token": "plan_token_reproduced",
                        "plan_digest": self.plan["canonical_digest"],
                    }
                )
                reproduced_task = _poll(second_service, reproduced["run_id"])
                reproduced_candidate = reproduced_task["data"]["data"]
                self.assertEqual(
                    reproduced_candidate["candidate_digest"],
                    candidate["candidate_digest"],
                )
                self.assertEqual(
                    reproduced_candidate["files"],
                    candidate["files"],
                )
            finally:
                second_service.close()

            restarted = ReweaveAppService(
                _NoLegacyEngine(),
                capsule_store=self.store,
            )
            try:
                restored = restarted.get_product_candidate(
                    {"candidate_token": candidate["candidate_token"]}
                )
                self.assertTrue(restored["ok"], restored)
                self.assertEqual(restored["data"], candidate)
                opened = restarted.read_product_candidate_file(
                    {
                        "candidate_token": candidate["candidate_token"],
                        "relative_path": "index.html",
                    }
                )
                self.assertTrue(opened["ok"], opened)
                self.assertEqual(opened["data"]["encoding"], "utf-8")
                self.assertIn("--- /dev/null", opened["data"]["text_diff"])
                traversal = restarted.read_product_candidate_file(
                    {
                        "candidate_token": candidate["candidate_token"],
                        "relative_path": "../index.html",
                    }
                )
                self.assertFalse(traversal["ok"])
                self.assertEqual(
                    traversal["error"]["code"],
                    "product_file_path_invalid",
                )
            finally:
                restarted.close()

            candidate_dir = next(
                (self.state / "product_candidates").glob("candidate_*")
            )
            (candidate_dir / "product" / "index.html").write_text(
                "corrupted\n",
                encoding="utf-8",
            )
            corrupted = self.service.get_product_candidate(
                {"candidate_token": candidate["candidate_token"]}
            )
            self.assertFalse(corrupted["ok"])
            self.assertEqual(
                corrupted["error"]["code"],
                "product_candidate_invalid",
            )

        self.assertEqual(_store_snapshot(self.store), before)
        self.assertFalse(products.exists())
        self.assertEqual(source.read_text(encoding="utf-8"), "source unchanged\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "target unchanged\n")
        candidate_root = self.state / "product_candidates"
        self.assertEqual(len(list(candidate_root.glob("candidate_*"))), 1)
        execution_path = next(candidate_root.glob("candidate_*")) / "execution_plan.json"
        execution = json.loads(execution_path.read_text(encoding="utf-8"))
        self.assertEqual(execution["schema_version"], "plan_execution.v1")
        self.assertEqual(execution["execution_digest"], candidate["execution_digest"])
        if os.name == "posix":
            self.assertEqual(candidate_root.stat().st_mode & 0o777, 0o700)
            self.assertTrue(
                all(
                    path.stat().st_mode & 0o777 == 0o600
                    for path in candidate_root.rglob("*")
                    if path.is_file()
                )
            )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_candidate_root_symlink_fails_closed(self) -> None:
        self.service._product_planner = _ConfirmedPlanner(
            self.plan,
            self.confirmation,
        )
        outside = self.root / "outside"
        outside.mkdir()
        os.symlink(outside, self.state / "product_candidates")
        started = self.service.start_product_candidate(
            {
                "plan_token": "plan_token_symlink",
                "plan_digest": self.plan["canonical_digest"],
            }
        )
        task = _poll(self.service, started["run_id"])
        self.assertEqual(task["status"], "failed")
        self.assertEqual(task["error"]["code"], "product_candidate_directory_unsafe")
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
