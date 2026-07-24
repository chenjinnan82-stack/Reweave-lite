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

from pimos_lite.composer.module_native import (
    compose_capsule_product,
    formal_page_contract_digest,
)
from pimos_lite.reweave_app_service import (
    ProductGenerationError,
    ReweaveAppService,
    _validate_product_acceptance,
)
from pimos_lite.reweave_capsule_store import CapsuleWarehouseStore
from pimos_lite.reweave_plan_execution import (
    CandidateAcceptanceError,
    PlanExecutionError,
    build_candidate_acceptance,
    build_parameterized_execution_binding,
    build_parameterized_execution_offer,
    canonical_bytes,
    canonical_digest,
    compile_plan_execution,
    compile_parameterized_plan_execution,
    evaluate_candidate_acceptance,
)
from pimos_lite.reweave_product_planner import (
    PLAN_SCHEMA_VERSION,
    PLANNING_PROMPT_VERSION,
    PLANNING_RULES_VERSION,
)
from tests.test_reweave_phase5_generation import (
    _NoLegacyEngine,
    _capsule_payload,
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


def _acceptance_cases(expected_total: int = 6) -> list[dict]:
    return [
        {
            "requirement_ids": ["requirement_03"],
            "input": {"quantity": 3},
            "expected_output": {"total": expected_total},
        }
    ]


def _acceptance_worker(actual_total: int = 6) -> dict:
    return {
        "schema_version": "candidate_acceptance_worker.v1",
        "status": "completed",
        "cases": [
            {
                "case_id": "case_01",
                "status": "passed",
                "actual_output": {"total": actual_total},
                "error_code": None,
            }
        ],
    }


def _parameterized_payload(kind: str) -> dict[str, object]:
    payload = copy.deepcopy(_capsule_payload(kind))
    total = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {
            "total": {"type": "integer", "minimum": 10, "maximum": 100}
        },
        "required": ["total"],
        "additional_properties": False,
    }
    if kind == "presentation":
        payload["input_contract"] = total
    elif kind == "computation":
        payload["input_contract"] = {
            "schema": "data_contract.v1",
            "type": "object",
            "properties": {
                "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
                "unit_price": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["quantity", "unit_price"],
            "additional_properties": False,
        }
        payload["output_contract"] = total
        payload["javascript_modules"] = [
            {
                "path": "computation.js",
                "source": """export function compute(input) {
  return {ok: true, value: {total: input.quantity * input.unit_price}};
}
""",
            }
        ]
    return payload


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

    def _parameterized_fixture(
        self,
        value: int = 10,
    ) -> tuple[list[dict], dict, dict, dict]:
        capsule_ids = []
        for kind in ("presentation", "interaction", "computation"):
            capsule_id, _version_id = _seed_capsule(
                self.store,
                kind,
                capability_key="parameterized_quote_calculation",
                suffix=f"parameterized_{kind}",
                payload=_parameterized_payload(kind),
            )
            capsule_ids.append(capsule_id)
        capsules, _scope = self.service._load_generation_capsules(
            capsule_ids,
            read_only=True,
        )
        revision = self.service._product_planning_catalog()["warehouse_revision"]
        plan, old_confirmation = _confirmed_plan(capsules, revision)
        offer = build_parameterized_execution_offer(plan, capsules)
        assert offer is not None
        binding = build_parameterized_execution_binding(
            plan,
            offer,
            {
                "schema_version": "parameterized_execution_confirmation.v1",
                "offer_digest": offer["offer_digest"],
                "values": [
                    {
                        "binding_id": offer["bindings"][0]["binding_id"],
                        "value": value,
                    }
                ],
            },
        )
        confirmation = {
            **{
                key: item
                for key, item in old_confirmation.items()
                if key != "receipt_digest"
            },
            "schema_version": "product_plan_confirmation.v2",
            "parameter_binding": binding,
        }
        confirmation["receipt_digest"] = canonical_digest(confirmation)
        return capsules, plan, confirmation, offer

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

    def test_formal_page_contract_is_shared_and_fails_before_execution(self) -> None:
        first_digest = formal_page_contract_digest(self.capsules)
        self.assertEqual(
            first_digest,
            formal_page_contract_digest(copy.deepcopy(self.capsules)),
        )

        css_variant = copy.deepcopy(self.capsules)
        for capsule in css_variant:
            capsule.pop("canonical_hash")
            if capsule["capability_kind"] == "interaction":
                capsule["css"] += "\n[data-action='calculate'] { cursor: pointer; }\n"
        self.assertEqual(first_digest, formal_page_contract_digest(css_variant))

        presentation = next(
            capsule
            for capsule in self.capsules
            if capsule["capability_kind"] == "presentation"
        )
        single_plan = copy.deepcopy(self.plan)
        single_confirmation = copy.deepcopy(self.confirmation)
        for section in single_plan["sections"]:
            section["work_items"][0]["capsule_bindings"] = [
                _binding(presentation)
            ]
        single_confirmation["capsule_revalidation"] = [
            {
                "capsule_id": presentation["capsule_id"],
                "version_id": presentation["version_id"],
                "eligibility_status": "active_current_eligible",
                "review_status": "user_confirmed",
            }
            for _section in single_plan["sections"]
        ]
        _refresh(single_plan, single_confirmation)
        self.assertEqual(
            compile_plan_execution(
                single_plan,
                single_confirmation,
                self.capsules,
            )["schema_version"],
            "plan_execution.v1",
        )

        capsule_ids = []
        for kind in ("presentation", "interaction", "computation"):
            payload = copy.deepcopy(_capsule_payload(kind))
            if kind == "interaction":
                payload["html"] += "\n<!-- distinct formal page -->"
            capsule_id, _version_id = _seed_capsule(
                self.store,
                kind,
                capability_key="page_contract_mismatch",
                suffix=f"page_contract_mismatch_{kind}",
                payload=payload,
            )
            capsule_ids.append(capsule_id)
        mismatched, _scope = self.service._load_generation_capsules(
            capsule_ids,
            read_only=True,
        )
        revision = self.service._product_planning_catalog()["warehouse_revision"]
        mismatch_plan, mismatch_confirmation = _confirmed_plan(
            mismatched,
            revision,
        )
        with self.assertRaisesRegex(
            PlanExecutionError,
            "plan_execution_dom_contract_mismatch",
        ):
            compile_plan_execution(
                mismatch_plan,
                mismatch_confirmation,
                mismatched,
            )
        with self.assertRaisesRegex(ValueError, "product_dom_contract_mismatch"):
            compose_capsule_product(
                task="隔离候选",
                product_id="product_" + "c" * 32,
                generated_at=NOW,
                capsules=mismatched,
            )

    def test_parameterized_offer_binding_and_v1_bytes_are_strict(self) -> None:
        old_execution = compile_plan_execution(
            self.plan,
            self.confirmation,
            self.capsules,
        )
        self.assertEqual(
            canonical_digest(old_execution),
            "803c4497227d74fa15c964038df6d5fb86f996103af69e2fc62bf5202d97ade3",
        )
        old_composition = compose_capsule_product(
            task="隔离候选",
            product_id="product_" + "b" * 32,
            generated_at=NOW,
            capsules=[
                {
                    key: value
                    for key, value in capsule.items()
                    if key != "canonical_hash"
                }
                for capsule in self.capsules
            ],
            candidate_acceptance_port=True,
        )
        self.assertEqual(
            canonical_digest(old_composition),
            "5ac25055962d58afd40b346658480bf20f9f24202473d01ead6be3011962bc36",
        )

        capsules, plan, confirmation, offer = self._parameterized_fixture()
        self.assertEqual(
            offer,
            build_parameterized_execution_offer(
                copy.deepcopy(plan),
                copy.deepcopy(capsules),
            ),
        )
        self.assertEqual(
            [row["input_field"] for row in offer["bindings"]],
            ["unit_price"],
        )
        execution = compile_parameterized_plan_execution(
            plan,
            confirmation,
            capsules,
        )
        repeated = compile_parameterized_plan_execution(
            copy.deepcopy(plan),
            copy.deepcopy(confirmation),
            copy.deepcopy(capsules),
        )
        self.assertEqual(execution["schema_version"], "plan_execution.v2")
        self.assertEqual(canonical_bytes(execution), canonical_bytes(repeated))
        self.assertEqual(
            execution["parameter_binding"],
            confirmation["parameter_binding"],
        )
        composition = compose_capsule_product(
            task=execution["composer_request"]["task"],
            product_id=execution["composer_request"]["product_id"],
            generated_at=execution["composer_request"]["generated_at"],
            capsules=copy.deepcopy(capsules),
            candidate_acceptance_port=True,
            parameter_binding=execution["parameter_binding"],
        )
        self.assertEqual(
            composition["composer_version"],
            "module_native_formal_product.v2",
        )
        self.assertEqual(
            composition["provenance"]["parameter_binding_digest"],
            confirmation["parameter_binding"]["canonical_digest"],
        )
        missing_identity = copy.deepcopy(capsules)
        missing_identity[0].pop("canonical_hash")
        with self.assertRaisesRegex(
            ValueError,
            "formal_capsule_identity_invalid",
        ):
            compose_capsule_product(
                task=execution["composer_request"]["task"],
                product_id=execution["composer_request"]["product_id"],
                generated_at=execution["composer_request"]["generated_at"],
                capsules=missing_identity,
                candidate_acceptance_port=True,
                parameter_binding=execution["parameter_binding"],
            )
        tampered_binding = copy.deepcopy(execution["parameter_binding"])
        tampered_binding["bindings"][0]["canonical_hash"] = "f" * 64
        tampered_binding["canonical_digest"] = canonical_digest(
            {
                key: value
                for key, value in tampered_binding.items()
                if key != "canonical_digest"
            }
        )
        with self.assertRaisesRegex(
            ValueError,
            "parameterized_execution_binding_invalid",
        ):
            compose_capsule_product(
                task=execution["composer_request"]["task"],
                product_id=execution["composer_request"]["product_id"],
                generated_at=execution["composer_request"]["generated_at"],
                capsules=copy.deepcopy(capsules),
                candidate_acceptance_port=True,
                parameter_binding=tampered_binding,
            )

        forged_capsules = copy.deepcopy(capsules)
        forged_computation = next(
            item
            for item in forged_capsules
            if item["capability_kind"] == "computation"
        )
        forged_computation["canonical_hash"] = "f" * 64
        forged_binding = copy.deepcopy(execution["parameter_binding"])
        forged_item = forged_binding["bindings"][0]
        forged_item["canonical_hash"] = "f" * 64
        forged_item["binding_id"] = "parameter_binding_" + canonical_digest(
            {
                "plan_digest": plan["canonical_digest"],
                "capsule_id": forged_item["capsule_id"],
                "version_id": forged_item["version_id"],
                "canonical_hash": forged_item["canonical_hash"],
                "input_field": forged_item["input_field"],
            }
        )[:24]
        forged_binding["canonical_digest"] = canonical_digest(
            {
                key: value
                for key, value in forged_binding.items()
                if key != "canonical_digest"
            }
        )
        with self.assertRaisesRegex(
            ValueError,
            "formal_capsule_identity_invalid",
        ):
            compose_capsule_product(
                task=execution["composer_request"]["task"],
                product_id=execution["composer_request"]["product_id"],
                generated_at=execution["composer_request"]["generated_at"],
                capsules=forged_capsules,
                candidate_acceptance_port=True,
                parameter_binding=forged_binding,
            )

        changed_binding = build_parameterized_execution_binding(
            plan,
            offer,
            {
                "schema_version": "parameterized_execution_confirmation.v1",
                "offer_digest": offer["offer_digest"],
                "values": [
                    {
                        "binding_id": offer["bindings"][0]["binding_id"],
                        "value": 11,
                    }
                ],
            },
        )
        changed_confirmation = {
            **{
                key: item
                for key, item in confirmation.items()
                if key not in {"receipt_digest", "parameter_binding"}
            },
            "parameter_binding": changed_binding,
        }
        changed_confirmation["receipt_digest"] = canonical_digest(
            changed_confirmation
        )
        changed = compile_parameterized_plan_execution(
            plan,
            changed_confirmation,
            capsules,
        )
        self.assertNotEqual(
            confirmation["receipt_digest"],
            changed_confirmation["receipt_digest"],
        )
        self.assertNotEqual(
            execution["execution_digest"],
            changed["execution_digest"],
        )
        self.assertNotEqual(
            execution["composer_request"]["product_id"],
            changed["composer_request"]["product_id"],
        )

        base_request = {
            "schema_version": "parameterized_execution_confirmation.v1",
            "offer_digest": offer["offer_digest"],
            "values": [
                {
                    "binding_id": offer["bindings"][0]["binding_id"],
                    "value": 10,
                }
            ],
        }
        for request in (
            {**base_request, "values": []},
            {**base_request, "values": base_request["values"] * 2},
            {
                **base_request,
                "values": [
                    {"binding_id": "parameter_binding_unknown", "value": 10}
                ],
            },
            {
                **base_request,
                "values": [
                    {
                        "binding_id": offer["bindings"][0]["binding_id"],
                        "value": True,
                    }
                ],
            },
            {
                **base_request,
                "values": [
                    {
                        "binding_id": offer["bindings"][0]["binding_id"],
                        "value": 101,
                    }
                ],
            },
        ):
            with self.subTest(request=request), self.assertRaises(
                PlanExecutionError
            ):
                build_parameterized_execution_binding(plan, offer, request)

        computation = next(
            row for row in capsules if row["capability_kind"] == "computation"
        )
        for contract in (
            {"type": "string", "min_length": 1, "max_length": 8},
            {
                "type": "array",
                "items": {"type": "integer", "minimum": 1, "maximum": 10},
                "min_items": 1,
                "max_items": 2,
            },
            {
                "type": "object",
                "properties": {
                    "amount": {"type": "integer", "minimum": 1, "maximum": 10}
                },
                "required": ["amount"],
                "additional_properties": False,
            },
        ):
            unsupported = copy.deepcopy(capsules)
            target = next(
                row
                for row in unsupported
                if row["capability_kind"] == "computation"
            )
            target["input_contract"]["properties"]["unit_price"] = contract
            with self.subTest(contract=contract), self.assertRaisesRegex(
                PlanExecutionError,
                "parameterized_execution_parameter_unsupported",
            ):
                build_parameterized_execution_offer(plan, unsupported)

        optional = copy.deepcopy(capsules)
        target = next(
            row for row in optional if row["capability_kind"] == "computation"
        )
        target["input_contract"]["required"] = ["quantity"]
        with self.assertRaisesRegex(
            PlanExecutionError,
            "parameterized_execution_contract_incompatible",
        ):
            build_parameterized_execution_offer(plan, optional)
        stale = copy.deepcopy(capsules)
        target = next(
            row for row in stale if row["capability_kind"] == "computation"
        )
        target["input_contract"]["properties"]["unit_price"]["maximum"] = 99
        with self.assertRaisesRegex(
            PlanExecutionError,
            "parameterized_execution_binding_stale",
        ):
            compile_parameterized_plan_execution(plan, confirmation, stale)
        sensitive = copy.deepcopy(capsules)
        target = next(
            row for row in sensitive if row["capability_kind"] == "computation"
        )
        target["input_contract"]["properties"]["unit_price"]["sensitive"] = True
        with self.assertRaisesRegex(
            PlanExecutionError,
            "parameterized_execution_contract_incompatible",
        ):
            build_parameterized_execution_offer(plan, sensitive)
        too_many = copy.deepcopy(capsules)
        target = next(
            row for row in too_many if row["capability_kind"] == "computation"
        )
        for index in range(17):
            field = f"parameter_{index:02d}"
            target["input_contract"]["properties"][field] = {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
            }
            target["input_contract"]["required"].append(field)
        target["input_contract"]["required"].sort()
        with self.assertRaisesRegex(
            PlanExecutionError,
            "parameterized_execution_binding_count_invalid",
        ):
            build_parameterized_execution_offer(plan, too_many)
        self.assertEqual(
            computation["input_contract"]["required"],
            ["quantity", "unit_price"],
        )

    def test_candidate_acceptance_contract_is_strict_and_deterministic(self) -> None:
        input_contract, output_contract = self.service._candidate_acceptance_contracts(
            self.capsules
        )
        first = build_candidate_acceptance(
            self.plan,
            self.confirmation,
            _acceptance_cases(),
            input_contract,
            output_contract,
            "a" * 64,
        )
        second = build_candidate_acceptance(
            copy.deepcopy(self.plan),
            copy.deepcopy(self.confirmation),
            copy.deepcopy(_acceptance_cases()),
            copy.deepcopy(input_contract),
            copy.deepcopy(output_contract),
            "a" * 64,
        )
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertEqual(first["cases"][0]["case_id"], "case_01")
        self.assertEqual(first["requirement_ids"], [
            "requirement_01",
            "requirement_02",
            "requirement_03",
            "requirement_04",
        ])

        receipt = evaluate_candidate_acceptance(
            first,
            _acceptance_worker(),
            input_contract,
            output_contract,
        )
        self.assertEqual(receipt["status"], "passed")
        mismatch = evaluate_candidate_acceptance(
            first,
            _acceptance_worker(7),
            input_contract,
            output_contract,
        )
        self.assertEqual(mismatch["status"], "failed")
        self.assertEqual(
            mismatch["cases"][0]["failure_code"],
            "candidate_output_mismatch",
        )
        nested_output = {
            "schema": "data_contract.v1",
            "type": "object",
            "properties": {
                "meta": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additional_properties": False,
                },
                "values": {
                    "type": "array",
                    "items": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 9,
                    },
                    "min_items": 2,
                    "max_items": 2,
                },
            },
            "required": ["meta", "values"],
            "additional_properties": False,
        }
        nested = build_candidate_acceptance(
            self.plan,
            self.confirmation,
            [{
                "requirement_ids": ["requirement_03"],
                "input": {"quantity": 3},
                "expected_output": {
                    "meta": {"ok": True},
                    "values": [1, 2],
                },
            }],
            input_contract,
            nested_output,
            "b" * 64,
        )
        nested_worker = {
            "schema_version": "candidate_acceptance_worker.v1",
            "status": "completed",
            "cases": [{
                "case_id": "case_01",
                "status": "passed",
                "actual_output": {
                    "values": [1, 2],
                    "meta": {"ok": True},
                },
                "error_code": None,
            }],
        }
        self.assertEqual(
            evaluate_candidate_acceptance(
                nested,
                nested_worker,
                input_contract,
                nested_output,
            )["status"],
            "passed",
        )
        nested_worker["cases"][0]["actual_output"]["values"] = [2, 1]
        self.assertEqual(
            evaluate_candidate_acceptance(
                nested,
                nested_worker,
                input_contract,
                nested_output,
            )["cases"][0]["failure_code"],
            "candidate_output_mismatch",
        )
        nested_worker["cases"][0]["actual_output"] = {
            "meta": {"ok": 1},
            "values": [1, 2],
        }
        self.assertEqual(
            evaluate_candidate_acceptance(
                nested,
                nested_worker,
                input_contract,
                nested_output,
            )["cases"][0]["failure_code"],
            "candidate_output_contract_invalid",
        )

        invalid_cases = (
            [],
            _acceptance_cases() * 17,
            [{
                "requirement_ids": ["requirement_unknown"],
                "input": {"quantity": 3},
                "expected_output": {"total": 6},
            }],
            [{
                "requirement_ids": ["requirement_03", "requirement_03"],
                "input": {"quantity": 3},
                "expected_output": {"total": 6},
            }],
            [{
                "requirement_ids": ["requirement_03"],
                "input": {"quantity": 0},
                "expected_output": {"total": 6},
            }],
            [{
                "requirement_ids": ["requirement_03"],
                "input": {"quantity": 3},
                "expected_output": {"total": 30},
            }],
        )
        for cases in invalid_cases:
            with self.subTest(cases=cases), self.assertRaises(
                CandidateAcceptanceError
            ):
                build_candidate_acceptance(
                    self.plan,
                    self.confirmation,
                    cases,
                    input_contract,
                    output_contract,
                    "a" * 64,
                )

        duplicate = _acceptance_cases() + _acceptance_cases()
        with self.assertRaisesRegex(
            CandidateAcceptanceError,
            "candidate_acceptance_case_duplicate",
        ):
            build_candidate_acceptance(
                self.plan,
                self.confirmation,
                duplicate,
                input_contract,
                output_contract,
                "a" * 64,
            )

    def test_candidate_port_receives_input_but_never_expected_output(self) -> None:
        result = {
            "schema_version": "candidate_acceptance_worker.v1",
            "status": "completed",
            "cases": [],
            "blocked_requests": [],
            "console_messages": [],
            "acceptance_scope": "candidate_business_acceptance",
        }
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(result, separators=(",", ":")),
            },
        )()
        with patch(
            "pimos_lite.reweave_app_service.subprocess.run",
            return_value=completed,
        ) as run:
            _validate_product_acceptance(
                self.root,
                {
                    "cases": [
                        {
                            "case_id": "case_01",
                            "input": {"quantity": 3},
                            "expected_output": {"total": 30},
                        }
                    ]
                },
            )
        request = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(
            request["cases"],
            [{"case_id": "case_01", "input": {"quantity": 3}}],
        )
        self.assertNotIn("expected_output", json.dumps(request))

    def test_acceptance_port_is_candidate_only(self) -> None:
        capsules = [
            {
                key: value
                for key, value in capsule.items()
                if key != "canonical_hash"
            }
            for capsule in self.capsules
        ]
        regular = compose_capsule_product(
            task="普通正式产品",
            product_id="product_" + "a" * 32,
            generated_at=NOW,
            capsules=capsules,
        )
        candidate = compose_capsule_product(
            task="隔离候选",
            product_id="product_" + "b" * 32,
            generated_at=NOW,
            capsules=capsules,
            candidate_acceptance_port=True,
        )
        self.assertNotIn(
            "__reweave_acceptance_v1",
            regular["files"]["app.js"],
        )
        self.assertIn(
            "__reweave_acceptance_v1",
            candidate["files"]["app.js"],
        )
        self.assertNotIn(
            "candidate_acceptance_port",
            regular["composition_manifest"],
        )
        self.assertEqual(
            candidate["composition_manifest"]["candidate_acceptance_port"],
            "candidate_acceptance.v1",
        )

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
            patch(
                "pimos_lite.reweave_app_service._validate_product_acceptance",
                return_value=_acceptance_worker(),
            ),
        ):
            started = self.service.start_product_candidate(
                {
                    "plan_token": "plan_token_test",
                    "plan_digest": self.plan["canonical_digest"],
                    "acceptance_cases": _acceptance_cases(),
                }
            )
            self.assertTrue(started["ok"])
            task = _poll(self.service, started["run_id"])
            self.assertEqual(task["status"], "completed", task)
            candidate = task["data"]["data"]
            self.assertEqual(candidate["schema_version"], "product_candidate.v2")
            self.assertEqual(candidate["status"], "review_ready")
            self.assertNotIn("candidate_id", candidate)
            self.assertTrue(candidate["validation"]["static"]["status"] == "passed")
            self.assertTrue(candidate["validation"]["runtime"]["status"] == "passed")
            self.assertEqual(candidate["validation"]["acceptance"]["status"], "passed")
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
                    "acceptance_cases": _acceptance_cases(),
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
                        "acceptance_cases": _acceptance_cases(),
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
            self.assertTrue((candidate_dir / "acceptance_contract.json").is_file())
            self.assertTrue((candidate_dir / "acceptance_receipt.json").is_file())
            contract_path = candidate_dir / "acceptance_contract.json"
            contract_bytes = contract_path.read_bytes()
            contract = json.loads(contract_bytes)
            contract["cases"][0]["expected_output"]["total"] = 7
            contract_path.write_text(
                json.dumps(contract, ensure_ascii=False),
                encoding="utf-8",
            )
            tampered_contract = self.service.get_product_candidate(
                {"candidate_token": candidate["candidate_token"]}
            )
            self.assertFalse(tampered_contract["ok"])
            self.assertEqual(
                tampered_contract["error"]["code"],
                "product_candidate_invalid",
            )
            contract_path.write_bytes(contract_bytes)

            receipt_path = candidate_dir / "acceptance_receipt.json"
            receipt_bytes = receipt_path.read_bytes()
            receipt = json.loads(receipt_bytes)
            receipt["cases"][0]["actual_output"]["total"] = 7
            receipt_path.write_text(
                json.dumps(receipt, ensure_ascii=False),
                encoding="utf-8",
            )
            tampered_receipt = self.service.get_product_candidate(
                {"candidate_token": candidate["candidate_token"]}
            )
            self.assertFalse(tampered_receipt["ok"])
            self.assertEqual(
                tampered_receipt["error"]["code"],
                "product_candidate_invalid",
            )
            receipt_path.write_bytes(receipt_bytes)

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

    def test_failed_acceptance_is_read_only_and_contract_is_immutable(self) -> None:
        self.service._product_planner = _ConfirmedPlanner(
            self.plan,
            self.confirmation,
        )
        before = _store_snapshot(self.store)
        with (
            patch(
                "pimos_lite.reweave_app_service._validate_product_static",
                _quality_receipt,
            ),
            patch(
                "pimos_lite.reweave_app_service._validate_product_runtime",
                _runtime_receipt,
            ),
            patch(
                "pimos_lite.reweave_app_service._validate_product_acceptance",
                return_value=_acceptance_worker(),
            ),
        ):
            started = self.service.start_product_candidate(
                {
                    "plan_token": "plan_token_failed_acceptance",
                    "plan_digest": self.plan["canonical_digest"],
                    "acceptance_cases": _acceptance_cases(7),
                }
            )
            task = _poll(self.service, started["run_id"])
            self.assertEqual(task["status"], "completed", task)
            candidate = task["data"]["data"]
            self.assertEqual(candidate["status"], "acceptance_failed")
            self.assertEqual(
                candidate["validation"]["acceptance"]["cases"][0]["failure_code"],
                "candidate_output_mismatch",
            )
            opened = self.service.read_product_candidate_file(
                {
                    "candidate_token": candidate["candidate_token"],
                    "relative_path": "app.js",
                }
            )
            self.assertTrue(opened["ok"], opened)

            repeated = self.service.start_product_candidate(
                {
                    "plan_token": "plan_token_failed_acceptance",
                    "plan_digest": self.plan["canonical_digest"],
                    "acceptance_cases": _acceptance_cases(7),
                }
            )
            repeated_task = _poll(self.service, repeated["run_id"])
            self.assertEqual(repeated_task["status"], "completed", repeated_task)
            self.assertEqual(
                repeated_task["data"]["data"]["candidate_token"],
                candidate["candidate_token"],
            )

            conflicting = self.service.start_product_candidate(
                {
                    "plan_token": "plan_token_failed_acceptance",
                    "plan_digest": self.plan["canonical_digest"],
                    "acceptance_cases": _acceptance_cases(),
                }
            )
            conflicting_task = _poll(self.service, conflicting["run_id"])
            self.assertEqual(conflicting_task["status"], "failed")
            self.assertEqual(
                conflicting_task["error"]["code"],
                "candidate_acceptance_contract_conflict",
            )
        self.assertEqual(_store_snapshot(self.store), before)
        self.assertFalse((self.state / "products").exists())
        self.assertEqual(
            len(list((self.state / "product_candidates").glob("candidate_*"))),
            1,
        )

    @unittest.skipUnless(
        Path(".venv-reweave/bin/python").is_file()
        or Path(".venv-reweave/Scripts/python.exe").is_file(),
        "PySide worker environment is required",
    )
    def test_real_qweb_acceptance_allows_matching_business_output(self) -> None:
        self.service._product_planner = _ConfirmedPlanner(
            self.plan,
            self.confirmation,
        )
        started = self.service.start_product_candidate(
            {
                "plan_token": "plan_token_real_acceptance_pass",
                "plan_digest": self.plan["canonical_digest"],
                "acceptance_cases": _acceptance_cases(),
            }
        )
        task = _poll(self.service, started["run_id"])
        self.assertEqual(task["status"], "completed", task)
        candidate = task["data"]["data"]
        self.assertEqual(candidate["status"], "review_ready")
        self.assertEqual(candidate["validation"]["runtime"]["status"], "passed")
        self.assertEqual(
            candidate["validation"]["acceptance"]["product_goal_conformance"],
            "passed",
        )
        self.assertEqual(
            candidate["acceptance"]["cases"][0]["actual_output"],
            {"total": 6},
        )

    @unittest.skipUnless(
        Path(".venv-reweave/bin/python").is_file()
        or Path(".venv-reweave/Scripts/python.exe").is_file(),
        "PySide worker environment is required",
    )
    def test_real_qweb_acceptance_reports_wrong_business_output(self) -> None:
        self.service._product_planner = _ConfirmedPlanner(
            self.plan,
            self.confirmation,
        )
        started = self.service.start_product_candidate(
            {
                "plan_token": "plan_token_real_acceptance",
                "plan_digest": self.plan["canonical_digest"],
                "acceptance_cases": _acceptance_cases(7),
            }
        )
        task = _poll(self.service, started["run_id"])
        self.assertEqual(task["status"], "completed", task)
        candidate = task["data"]["data"]
        self.assertEqual(candidate["status"], "acceptance_failed")
        self.assertEqual(candidate["validation"]["runtime"]["status"], "passed")
        acceptance = candidate["validation"]["acceptance"]
        self.assertEqual(acceptance["runtime_operational"], "passed")
        self.assertEqual(acceptance["product_goal_conformance"], "failed")
        self.assertEqual(acceptance["cases"][0]["actual_output"], {"total": 6})
        self.assertEqual(
            acceptance["cases"][0]["failure_code"],
            "candidate_output_mismatch",
        )
        self.assertEqual(
            candidate["acceptance"]["cases"][0],
            {
                "case_id": "case_01",
                "input": {"quantity": 3},
                "expected_output": {"total": 7},
                "actual_output": {"total": 6},
                "status": "failed",
                "failure_code": "candidate_output_mismatch",
            },
        )
        self.assertNotIn("requirement_ids", candidate["acceptance"]["cases"][0])

    @unittest.skipUnless(
        Path(".venv-reweave/bin/python").is_file()
        or Path(".venv-reweave/Scripts/python.exe").is_file(),
        "PySide worker environment is required",
    )
    def test_real_qweb_parameter_binding_is_applied_and_cannot_be_overridden(
        self,
    ) -> None:
        _capsules, plan, confirmation, _offer = self._parameterized_fixture()
        self.service._product_planner = _ConfirmedPlanner(plan, confirmation)
        cases = [
            {
                "requirement_ids": ["requirement_03"],
                "input": {"quantity": quantity},
                "expected_output": {"total": expected},
            }
            for quantity, expected in ((1, 10), (3, 30), (10, 100))
        ]
        started = self.service.start_product_candidate(
            {
                "plan_token": "plan_token_parameterized_qweb",
                "plan_digest": plan["canonical_digest"],
                "acceptance_cases": cases,
            }
        )
        task = _poll(self.service, started["run_id"])
        self.assertEqual(task["status"], "completed", task)
        candidate = task["data"]["data"]
        self.assertEqual(candidate["status"], "review_ready")
        self.assertEqual(
            [row["actual_output"] for row in candidate["acceptance"]["cases"]],
            [{"total": 10}, {"total": 30}, {"total": 100}],
        )
        self.assertEqual(
            candidate["provenance"]["schema_version"],
            "product_candidate_provenance.v2",
        )
        self.assertEqual(
            candidate["provenance"]["parameter_binding"],
            confirmation["parameter_binding"],
        )
        repeated = self.service.start_product_candidate(
            {
                "plan_token": "plan_token_parameterized_qweb",
                "plan_digest": plan["canonical_digest"],
                "acceptance_cases": cases,
            }
        )
        repeated_candidate = _poll(self.service, repeated["run_id"])[
            "data"
        ]["data"]
        self.assertEqual(
            repeated_candidate["candidate_digest"],
            candidate["candidate_digest"],
        )

        candidate_dir = next(
            (self.state / "product_candidates").glob("candidate_*")
        )
        override = _validate_product_acceptance(
            candidate_dir / "product",
            {
                "cases": [
                    {
                        "case_id": "case_override",
                        "input": {"quantity": 3, "unit_price": 99},
                    }
                ]
            },
        )
        self.assertEqual(
            override["cases"],
            [
                {
                    "case_id": "case_override",
                    "status": "failed",
                    "actual_output": None,
                    "error_code": "candidate_case_execution_failed",
                }
            ],
        )
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
        finally:
            restarted.close()

    def test_runtime_failure_prevents_acceptance_and_candidate_persistence(self) -> None:
        self.service._product_planner = _ConfirmedPlanner(
            self.plan,
            self.confirmation,
        )
        with (
            patch(
                "pimos_lite.reweave_app_service._validate_product_static",
                _quality_receipt,
            ),
            patch(
                "pimos_lite.reweave_app_service._validate_product_runtime",
                side_effect=ProductGenerationError("product_qweb_worker_failed"),
            ),
            patch(
                "pimos_lite.reweave_app_service._validate_product_acceptance"
            ) as acceptance,
        ):
            started = self.service.start_product_candidate(
                {
                    "plan_token": "plan_token_runtime_failed",
                    "plan_digest": self.plan["canonical_digest"],
                    "acceptance_cases": _acceptance_cases(),
                }
            )
            task = _poll(self.service, started["run_id"])
            self.assertEqual(task["status"], "failed")
            self.assertEqual(task["error"]["code"], "product_qweb_worker_failed")
            acceptance.assert_not_called()
        root = self.state / "product_candidates"
        self.assertFalse(root.exists() and list(root.glob("candidate_*")))
        with (
            patch(
                "pimos_lite.reweave_app_service._validate_product_static",
                _quality_receipt,
            ),
            patch(
                "pimos_lite.reweave_app_service._validate_product_runtime",
                _runtime_receipt,
            ),
            patch(
                "pimos_lite.reweave_app_service._validate_product_acceptance",
                side_effect=ProductGenerationError(
                    "candidate_acceptance_port_missing"
                ),
            ),
        ):
            started = self.service.start_product_candidate(
                {
                    "plan_token": "plan_token_acceptance_worker_failed",
                    "plan_digest": self.plan["canonical_digest"],
                    "acceptance_cases": _acceptance_cases(),
                }
            )
            task = _poll(self.service, started["run_id"])
            self.assertEqual(task["status"], "failed")
            self.assertEqual(
                task["error"]["code"],
                "candidate_acceptance_port_missing",
            )
        self.assertFalse(root.exists() and list(root.glob("candidate_*")))

    def test_legacy_candidate_is_read_only_and_never_claims_conformance(self) -> None:
        self.service._product_planner = _ConfirmedPlanner(
            self.plan,
            self.confirmation,
        )
        with (
            patch(
                "pimos_lite.reweave_app_service._validate_product_static",
                _quality_receipt,
            ),
            patch(
                "pimos_lite.reweave_app_service._validate_product_runtime",
                _runtime_receipt,
            ),
            patch(
                "pimos_lite.reweave_app_service._validate_product_acceptance",
                return_value=_acceptance_worker(),
            ),
        ):
            started = self.service.start_product_candidate(
                {
                    "plan_token": "plan_token_legacy_projection",
                    "plan_digest": self.plan["canonical_digest"],
                    "acceptance_cases": _acceptance_cases(),
                }
            )
            task = _poll(self.service, started["run_id"])
            self.assertEqual(task["status"], "completed", task)
        candidate = task["data"]["data"]
        candidate_dir = next(
            (self.state / "product_candidates").glob("candidate_*")
        )
        record_path = candidate_dir / "candidate.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["schema_version"] = "product_candidate.v1"
        record["status"] = "review_ready"
        record.pop("candidate_content_digest")
        record.pop("acceptance")
        record["validation"].pop("acceptance")
        core = {
            key: value
            for key, value in record.items()
            if key not in {"candidate_token", "candidate_digest", "record_digest"}
        }
        record["candidate_digest"] = canonical_digest(core)
        record["record_digest"] = canonical_digest(
            {key: value for key, value in record.items() if key != "record_digest"}
        )
        record_path.write_bytes(canonical_bytes(record) + b"\n")

        restored = self.service.get_product_candidate(
            {"candidate_token": candidate["candidate_token"]}
        )
        self.assertTrue(restored["ok"], restored)
        self.assertEqual(restored["data"]["schema_version"], "product_candidate.v1")
        self.assertEqual(restored["data"]["status"], "legacy_unverified")
        self.assertEqual(
            restored["data"]["product_goal_conformance"],
            "not_available",
        )

    def test_acceptance_requires_one_computation_capsule(self) -> None:
        without_computation = [
            item
            for item in self.capsules
            if item["capability_kind"] != "computation"
        ]
        with self.assertRaisesRegex(
            ProductGenerationError,
            "candidate_acceptance_computation_required",
        ):
            self.service._candidate_acceptance_contracts(without_computation)

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
                "acceptance_cases": _acceptance_cases(),
            }
        )
        task = _poll(self.service, started["run_id"])
        self.assertEqual(task["status"], "failed")
        self.assertEqual(task["error"]["code"], "product_candidate_directory_unsafe")
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
