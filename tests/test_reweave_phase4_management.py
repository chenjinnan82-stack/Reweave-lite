"""Bounded Phase 4 tests for the single management service."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_canonical import canonical_json_digest
from pimos_lite.reweave_capsule_intake import (
    COMPUTATION_ADAPTER_CONTRACT_VERSION,
    EXTRACTION_CONTRACT_VERSION,
)
from pimos_lite.reweave_capsule_store import CapsuleWarehouseStore
from pimos_lite.reweave_engine.local import LocalReweaveEngine
from pimos_lite.reweave_javascript_source import (
    _descriptor_relative_snapshot_supported,
    javascript_source_snapshot_supported,
)
from pimos_lite.reweave_source_derivation import (
    get_source_derived_run,
)


class Phase4ManagementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self.state)})
        self.env.start()
        self.store = CapsuleWarehouseStore(self.state / "capsule_warehouse.sqlite3")
        self.service = ReweaveAppService(
            engine=LocalReweaveEngine(), capsule_store=self.store
        )

    def tearDown(self) -> None:
        self.service.close()
        self.env.stop()
        self.temp.cleanup()

    def _wait(self, run_id: str) -> dict[str, object]:
        for _ in range(3_000):
            result = self.service.get_intake_run({"run_id": run_id})
            self.assertTrue(result["ok"])
            task = result["data"]
            if task["status"] in {
                "completed",
                "review_required",
                "failed",
                "cancelled",
            }:
                return task
            time.sleep(0.01)
        self.fail("management task did not finish")

    def _wait_product_plan(self, run_id: str) -> dict[str, object]:
        for _ in range(300):
            result = self.service.get_product_plan_run({"run_id": run_id})
            self.assertTrue(result["ok"])
            task = result["data"]
            if task["status"] in {"completed", "failed", "cancelled"}:
                return task
            time.sleep(0.01)
        self.fail("product planning task did not finish")

    def _ready_project(self) -> str:
        source = self.root / "project"
        source.mkdir()
        (source / "index.html").write_text(
            '<div data-capsule-root="quote"></div>', encoding="utf-8"
        )
        root = self.service._capsule_intake.bind_source_root(
            source, root_kind="single_project"
        )
        discovered = self.service._capsule_intake.discover_projects(str(root["root_id"]))
        project = self.service._capsule_intake.confirm_project(
            str(discovered[0]["project_id"])
        )
        return str(project["project_id"])

    def _ready_complete_project(self) -> tuple[str, Path]:
        source = self.root / "complete-project"
        source.mkdir()
        (source / "index.html").write_text(
            """<!doctype html>
<html><body>
<main data-capsule-root>
  <span data-ref="title"></span>
  <input data-ref="quantity" type="number" min="1" max="10" step="1">
  <button data-action="calculate" type="button">Calculate</button>
</main>
<script type="module" src="./presentation.js"></script>
<script type="module" src="./interaction.js"></script>
<script type="module" src="./compute.js"></script>
</body></html>
""",
            encoding="utf-8",
        )
        (source / "presentation.js").write_text(
            """export function render(root, input) {
  if (typeof input.title !== "string" || input.title.length > 40) {
    return {ok: false, error: {code: "INVALID_TITLE"}};
  }
  const title = root.querySelector("[data-ref='title']");
  title.textContent = input.title;
}
""",
            encoding="utf-8",
        )
        (source / "interaction.js").write_text(
            """export function mount(root, ports) {
  const quantity = root.querySelector("[data-ref='quantity']");
  const button = root.querySelector("[data-action='calculate']");
  const onClick = (event) => {
    event.preventDefault();
    const value = Number(quantity.value);
    if (!Number.isInteger(value) || value < 1 || value > 10) return;
    ports.emit("calculate_requested", {quantity: value});
  };
  button.addEventListener("click", onClick);
  return () => { button.removeEventListener("click", onClick); };
}
""",
            encoding="utf-8",
        )
        (source / "compute.js").write_text(
            """export function compute(input) {
  if (!input || typeof input !== "object" || Object.keys(input).length !== 1) {
    return {ok: false, error: {code: "INVALID_INPUT", field: null, details: {}}};
  }
  if (!Number.isInteger(input.quantity) || input.quantity < 1 || input.quantity > 10) {
    return {ok: false, error: {code: "INVALID_QUANTITY", field: "quantity", details: {}}};
  }
  return {ok: true, value: {total: input.quantity * 2}};
}
""",
            encoding="utf-8",
        )
        root = self.service._capsule_intake.bind_source_root(
            source,
            root_kind="single_project",
        )
        project = self.service._capsule_intake.discover_projects(
            str(root["root_id"])
        )[0]
        confirmed = self.service._capsule_intake.confirm_project(
            str(project["project_id"])
        )
        return str(confirmed["project_id"]), source

    def _select_test_supervision_model(self) -> None:
        selected = {
            "base_url": "http://127.0.0.1:11434",
            "name": "source-handoff-test-model",
            "digest": "b" * 64,
            "selected_at": "2026-08-16T00:00:00Z",
        }
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO app_settings(setting_key, value_json, updated_at) "
                "VALUES ('capsule_supervision_model', ?, ?)",
                (
                    json.dumps(
                        selected,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    selected["selected_at"],
                ),
            )

    def _source_derived_platform_supported(
        self,
        payload: dict[str, object],
    ) -> bool:
        state = self.state / "source_derived_computations"
        model_guard = patch.object(
            self.service._product_planner,
            "_selected_model",
            side_effect=AssertionError("source model must not be read"),
        )
        supervisor_guard = patch.object(
            self.service._capsule_supervisor,
            "selected_model",
            side_effect=AssertionError("supervisor must not be read"),
        )
        with patch(
            "pimos_lite.reweave_app_service.javascript_source_snapshot_supported",
            return_value=False,
        ), model_guard, supervisor_guard:
            result = (
                self.service
                .authorize_and_start_source_derived_computation(payload)
            )
        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"]["code"],
            "source_platform_unsupported_v1",
        )
        self.assertFalse(state.exists())
        if javascript_source_snapshot_supported():
            return True
        with model_guard, supervisor_guard:
            result = (
                self.service
                .authorize_and_start_source_derived_computation(payload)
            )
        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"]["code"],
            "source_platform_unsupported_v1",
        )
        self.assertFalse(state.exists())
        return False

    def test_source_derived_developer_run_reaches_only_isolated_review(
        self,
    ) -> None:
        source = self.root / "source-derived"
        evidence_file = source / "src" / "rules.ts"
        evidence_file.parent.mkdir(parents=True)
        evidence_file.write_text(
            'export function classify(value: string) { return value; }\n',
            encoding="utf-8",
        )
        self.store.initialize()
        self.store.migrate_v1_to_v2()
        root = self.service._capsule_intake.bind_source_root(
            source,
            root_kind="project_collection",
        )
        self._select_test_supervision_model()
        source_model = {
            "name": "source-derived-test:1b",
            "digest": "a" * 64,
            "parameter_count": 1_000_000_000,
            "parameter_size": "1B",
        }
        proposal = {
            "schema": "capability_source_proposal.v2",
            "entry": {
                "module_relpath": "capability.js",
                "export_name": "compute",
            },
            "files": [
                {
                    "path": "capability.js",
                    "content": (
                        "export function compute(arg0) {\n"
                        '  return arg0.includes("urgent") '
                        '? "urgent" : "normal";\n'
                        "}\n"
                    ),
                }
            ],
            "witnesses": [
                {
                    "input": {"message": "routine"},
                    "expected_scalar_result": "normal",
                },
                {
                    "input": {"message": "urgent"},
                    "expected_scalar_result": "urgent",
                },
            ],
        }
        source_calls: list[str] = []
        supervisor_calls: list[str] = []

        def generate(*_args, **_kwargs):
            source_calls.append("generate")
            return {
                "response": proposal,
                "evidence": {"response_digest": "c" * 64},
            }

        def approve(_self, _summary, capability_kind):
            supervisor_calls.append(capability_kind)
            return (
                {
                    "schema_version": "capsule_supervision.v1",
                    "verdict": "approve",
                    "capability_kind": capability_kind,
                    "semantic_summary": "Bounded local computation.",
                    "keep_reason_codes": [
                        "DECLARED_LOCAL_CAPABILITY"
                    ],
                    "remove_reason_codes": [],
                    "brand_signals": [],
                    "sensitive_data_status": "clear",
                    "hidden_dependency_codes": [],
                    "duplicate_suggestions": [],
                    "review_required": False,
                },
                "d" * 64,
                {
                    "name": "source-handoff-test-model",
                    "digest": "b" * 64,
                },
            )

        payload = {
            "source_root_id": str(root["root_id"]),
            "source_relpath": "src/rules.ts",
            "behavior_intent": "Classify bounded text.",
            "input_field": "message",
            "input_min_length": 1,
            "input_max_length": 1000,
            "result_field": "classification",
            "result_enum": ["normal", "urgent"],
            "acceptance_cases": [
                {
                    "input_text": "routine task",
                    "expected_result": "normal",
                },
                {
                    "input_text": "urgent task",
                    "expected_result": "urgent",
                },
            ],
        }
        if not self._source_derived_platform_supported(payload):
            return
        with self.store.read_connection() as connection:
            formal_before = {
                table: int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                )
                for table in ("review_items", "capsules", "capsule_versions")
            }
        revision_before = self.store.current_revision()
        with patch.object(
            self.service._product_planner,
            "_selected_model",
            return_value=source_model,
        ), patch.object(
            self.service._product_planner,
            "run_source_derived_capability_source_proposal",
            side_effect=generate,
        ), patch(
            "pimos_lite.reweave_capsule_stage3.OllamaSupervisor.supervise",
            new=approve,
        ):
            gate = threading.Barrier(3)
            starts: list[dict[str, object]] = []

            def start() -> None:
                gate.wait()
                starts.append(
                    self.service.authorize_and_start_source_derived_computation(
                        payload
                    )
                )

            threads = [threading.Thread(target=start) for _ in range(2)]
            for thread in threads:
                thread.start()
            gate.wait()
            for thread in threads:
                thread.join(5)
                self.assertFalse(thread.is_alive())
            self.assertEqual(len(starts), 2)
            self.assertTrue(all(item["ok"] for item in starts), starts)
            run_ids = {
                str(item.get("run_id") or item["data"]["run_id"])
                for item in starts
            }
            self.assertEqual(len(run_ids), 1)
            run_id = run_ids.pop()
            result = self._wait(run_id)
            self.assertEqual(
                result["status"],
                "review_required",
                result,
            )
            self.assertEqual(result["review_scope"], "isolated")
            self.assertEqual(result["attempt_count"], 1)
            self.assertNotIn("review_id", result)
            self.assertNotIn("source_relpath", result)
            self.assertNotIn("source_root_id", result)
            self.assertNotIn("model", result)
            repeated = (
                self.service
                .authorize_and_start_source_derived_computation(payload)
            )
            self.assertTrue(repeated["ok"], repeated)
            self.assertEqual(repeated["data"]["run_id"], run_id)
            self.assertEqual(
                repeated["data"]["status"],
                "review_required",
            )

        self.assertEqual(source_calls, ["generate"])
        self.assertEqual(supervisor_calls, ["computation"])
        self.assertEqual(self.store.current_revision(), revision_before)
        with self.store.read_connection() as connection:
            formal_after = {
                table: int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                )
                for table in ("review_items", "capsules", "capsule_versions")
            }
        self.assertEqual(formal_after, formal_before)
        run_directories = list(
            (self.state / "source_derived_computations").glob(
                "[0-9a-f]" * 64
            )
        )
        self.assertEqual(len(run_directories), 1)
        durable = get_source_derived_run(self.service._state_root, run_id)
        self.assertEqual(
            [
                (event["status"], event["stage"])
                for event in durable["events"]
            ],
            [
                ("pending", "source_proposal"),
                ("running", "source_proposal"),
                ("running", "intake"),
                ("running", "security"),
                ("running", "runtime"),
                ("running", "supervision"),
                ("review_required", "supervision"),
            ],
        )
        validation_database = (
            run_directories[0]
            / "validation"
            / "capsule_warehouse.sqlite3"
        )
        isolated = CapsuleWarehouseStore(validation_database)
        with isolated.read_connection() as connection:
            self.assertEqual(
                int(
                    connection.execute(
                        "SELECT COUNT(*) FROM review_items "
                        "WHERE candidate_status = 'review_required'"
                    ).fetchone()[0]
                ),
                formal_before["review_items"] + 1,
            )
            self.assertEqual(
                int(
                    connection.execute(
                        "SELECT COUNT(*) FROM capsules"
                    ).fetchone()[0]
                ),
                formal_before["capsules"],
            )
            self.assertEqual(
                int(
                    connection.execute(
                        "SELECT COUNT(*) FROM capsule_versions"
                    ).fetchone()[0]
                ),
                formal_before["capsule_versions"],
            )
        database_bytes = validation_database.read_bytes()
        validation_database.write_bytes(database_bytes + b"tampered")
        if os.name == "posix":
            validation_database.chmod(0o600)
        tampered = self.service.get_intake_run({"run_id": run_id})
        self.assertFalse(tampered["ok"])
        self.assertEqual(
            tampered["error"]["code"],
            "source_derivation_validation_conflict",
        )
        validation_database.write_bytes(database_bytes)
        if os.name == "posix":
            validation_database.chmod(0o600)

    def test_source_derived_run_fails_closed_on_restart_and_tamper(
        self,
    ) -> None:
        source = self.root / "source-derived-recovery"
        source.mkdir()
        (source / "rules.ts").write_text(
            'export const rules = ["urgent"];\n',
            encoding="utf-8",
        )
        self.store.initialize()
        self.store.migrate_v1_to_v2()
        root = self.service._capsule_intake.bind_source_root(
            source,
            root_kind="project_collection",
        )
        self._select_test_supervision_model()
        model = {
            "name": "source-derived-test:1b",
            "digest": "a" * 64,
            "parameter_count": 1_000_000_000,
            "parameter_size": "1B",
        }
        payload = {
            "source_root_id": str(root["root_id"]),
            "source_relpath": "rules.ts",
            "behavior_intent": "Classify bounded text.",
            "input_field": "message",
            "input_min_length": 1,
            "input_max_length": 1000,
            "result_field": "classification",
            "result_enum": ["normal", "urgent"],
            "acceptance_cases": [
                {
                    "input_text": "routine",
                    "expected_result": "normal",
                },
                {
                    "input_text": "urgent",
                    "expected_result": "urgent",
                },
            ],
        }
        with patch.object(
            self.service._product_planner,
            "_selected_model",
            return_value=model,
        ), patch(
            "pimos_lite.reweave_app_service.javascript_source_snapshot_supported",
            return_value=True,
        ), patch.object(
            self.service,
            "_submit_management_task",
            side_effect=lambda _kind, _action, **kwargs: {
                "ok": True,
                "run_id": kwargs["run_id"],
                "status": "queued",
            },
        ):
            started = (
                self.service
                .authorize_and_start_source_derived_computation(payload)
            )
            self.assertTrue(started["ok"], started)
            recovered = self.service.get_intake_run(
                {"run_id": started["run_id"]}
            )
            self.assertTrue(recovered["ok"], recovered)
            self.assertEqual(
                recovered["data"]["error_code"],
                "manual_recovery_required",
            )
            repeated = (
                self.service
                .authorize_and_start_source_derived_computation(payload)
            )
            self.assertEqual(
                repeated["data"]["run_id"],
                started["run_id"],
            )
            self.assertEqual(repeated["data"]["status"], "failed")

            original_source = (source / "rules.ts").read_bytes()
            (source / "rules.ts").write_bytes(original_source + b"\n")
            source_stale = (
                self.service
                .authorize_and_start_source_derived_computation(payload)
            )
            self.assertFalse(source_stale["ok"])
            self.assertEqual(
                source_stale["error"]["code"],
                "source_derivation_run_stale",
            )
            (source / "rules.ts").write_bytes(original_source)

            changed_model = {**model, "digest": "f" * 64}
            with patch.object(
                self.service._product_planner,
                "_selected_model",
                return_value=changed_model,
            ):
                model_stale = (
                    self.service
                    .authorize_and_start_source_derived_computation(payload)
                )
            self.assertFalse(model_stale["ok"])
            self.assertEqual(
                model_stale["error"]["code"],
                "source_derivation_run_stale",
            )

            catalog = self.service._product_planning_catalog()
            changed_catalog = {
                **catalog,
                "warehouse_revision": catalog["warehouse_revision"] + 1,
            }
            with patch.object(
                self.service,
                "_product_planning_catalog",
                return_value=changed_catalog,
            ):
                catalog_stale = (
                    self.service
                    .authorize_and_start_source_derived_computation(payload)
                )
            self.assertFalse(catalog_stale["ok"])
            self.assertEqual(
                catalog_stale["error"]["code"],
                "source_derivation_run_stale",
            )
            self.assertEqual(
                len(
                    list(
                        (
                            self.state
                            / "source_derived_computations"
                        ).glob("[0-9a-f]" * 64)
                    )
                ),
                1,
            )

            run_path = next(
                (
                    self.state
                    / "source_derived_computations"
                ).glob("*/run.json")
            )
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["attempt_count"] = 2
            run_path.write_bytes(
                (
                    json.dumps(
                        run,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
            )
            if os.name == "posix":
                run_path.chmod(0o600)
            conflict = self.service.get_intake_run(
                {"run_id": started["run_id"]}
            )
            self.assertFalse(conflict["ok"])
            self.assertEqual(
                conflict["error"]["code"],
                "source_derivation_run_conflict",
            )

        invalid = dict(payload)
        invalid["source_relpath"] = "../rules.ts"
        with patch(
            "pimos_lite.reweave_app_service.javascript_source_snapshot_supported",
            return_value=True,
        ):
            rejected = (
                self.service
                .authorize_and_start_source_derived_computation(invalid)
            )
        self.assertFalse(rejected["ok"])
        self.assertEqual(
            rejected["error"]["code"],
            "source_derivation_evidence_invalid",
        )

    def test_source_derived_cancel_discards_model_result(
        self,
    ) -> None:
        source = self.root / "source-derived-cancel"
        source.mkdir()
        (source / "rules.ts").write_text(
            'export const rules = ["urgent"];\n',
            encoding="utf-8",
        )
        self.store.initialize()
        self.store.migrate_v1_to_v2()
        root = self.service._capsule_intake.bind_source_root(
            source,
            root_kind="project_collection",
        )
        self._select_test_supervision_model()
        model = {
            "name": "source-derived-test:1b",
            "digest": "a" * 64,
            "parameter_count": 1_000_000_000,
            "parameter_size": "1B",
        }
        entered = threading.Event()
        release = threading.Event()
        source_calls: list[str] = []

        def generate(*_args, **_kwargs):
            source_calls.append("generate")
            entered.set()
            self.assertTrue(release.wait(5))
            return {
                "response": {
                    "schema": "capability_source_proposal.v2",
                    "entry": {
                        "module_relpath": "capability.js",
                        "export_name": "compute",
                    },
                    "files": [
                        {
                            "path": "capability.js",
                            "content": (
                                "export function compute(arg0) { "
                                'return arg0.includes("urgent") '
                                '? "urgent" : "normal"; }\n'
                            ),
                        }
                    ],
                    "witnesses": [
                        {
                            "input": {"message": "routine"},
                            "expected_scalar_result": "normal",
                        },
                        {
                            "input": {"message": "urgent"},
                            "expected_scalar_result": "urgent",
                        },
                    ],
                },
                "evidence": {"response_digest": "c" * 64},
            }

        payload = {
            "source_root_id": str(root["root_id"]),
            "source_relpath": "rules.ts",
            "behavior_intent": "Classify bounded text.",
            "input_field": "message",
            "input_min_length": 1,
            "input_max_length": 1000,
            "result_field": "classification",
            "result_enum": ["normal", "urgent"],
            "acceptance_cases": [
                {
                    "input_text": "routine",
                    "expected_result": "normal",
                },
                {
                    "input_text": "urgent",
                    "expected_result": "urgent",
                },
            ],
        }
        if not self._source_derived_platform_supported(payload):
            return
        with patch.object(
            self.service._product_planner,
            "_selected_model",
            return_value=model,
        ), patch.object(
            self.service._product_planner,
            "run_source_derived_capability_source_proposal",
            side_effect=generate,
        ):
            started = (
                self.service
                .authorize_and_start_source_derived_computation(payload)
            )
            self.assertTrue(started["ok"], started)
            self.assertTrue(entered.wait(5))
            cancelled = self.service.cancel_intake_run(
                {"run_id": started["run_id"]}
            )
            self.assertTrue(cancelled["ok"], cancelled)
            release.set()
            result = self._wait(started["run_id"])
        self.assertEqual(source_calls, ["generate"])
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["stage"], "source_proposal")
        run_dir = next(
            (
                self.state / "source_derived_computations"
            ).glob("[0-9a-f]" * 64)
        )
        self.assertFalse((run_dir / "source" / "capability.js").exists())
        self.assertFalse(
            (run_dir / "validation" / "capsule_warehouse.sqlite3").exists()
        )

        supervisor_entered = threading.Event()
        supervisor_release = threading.Event()

        def approve_after_cancel(_self, _summary, capability_kind):
            supervisor_entered.set()
            self.assertTrue(supervisor_release.wait(5))
            return (
                {
                    "schema_version": "capsule_supervision.v1",
                    "verdict": "approve",
                    "capability_kind": capability_kind,
                    "semantic_summary": "Bounded local computation.",
                    "keep_reason_codes": ["DECLARED_LOCAL_CAPABILITY"],
                    "remove_reason_codes": [],
                    "brand_signals": [],
                    "sensitive_data_status": "clear",
                    "hidden_dependency_codes": [],
                    "duplicate_suggestions": [],
                    "review_required": False,
                },
                "d" * 64,
                {
                    "name": "source-handoff-test-model",
                    "digest": "b" * 64,
                },
            )

        second_payload = {
            **payload,
            "behavior_intent": "Classify another bounded text task.",
        }
        with patch.object(
            self.service._product_planner,
            "_selected_model",
            return_value=model,
        ), patch.object(
            self.service._product_planner,
            "run_source_derived_capability_source_proposal",
            side_effect=generate,
        ), patch(
            "pimos_lite.reweave_capsule_stage3.OllamaSupervisor.supervise",
            new=approve_after_cancel,
        ):
            second = (
                self.service
                .authorize_and_start_source_derived_computation(
                    second_payload
                )
            )
            self.assertTrue(second["ok"], second)
            self.assertTrue(supervisor_entered.wait(15))
            cancelled = self.service.cancel_intake_run(
                {"run_id": second["run_id"]}
            )
            self.assertTrue(cancelled["ok"], cancelled)
            supervisor_release.set()
            second_result = self._wait(second["run_id"])
        self.assertEqual(source_calls, ["generate", "generate"])
        self.assertEqual(second_result["status"], "cancelled")
        self.assertEqual(second_result["stage"], "supervision")
        second_run_dir = next(
            path
            for path in (
                self.state / "source_derived_computations"
            ).glob("[0-9a-f]" * 64)
            if json.loads(
                (path / "run.json").read_text(encoding="utf-8")
            )["run_id"]
            == second["run_id"]
        )
        isolated = CapsuleWarehouseStore(
            second_run_dir
            / "validation"
            / "capsule_warehouse.sqlite3"
        )
        with isolated.read_connection() as connection:
            self.assertEqual(
                int(
                    connection.execute(
                        "SELECT COUNT(*) FROM review_items"
                    ).fetchone()[0]
                ),
                0,
            )

    def _seed_project_contribution(
        self,
        project_id: str,
        *,
        extraction_version: str = EXTRACTION_CONTRACT_VERSION,
        extraction_summary: dict[str, object] | None = None,
        formal_contracts: bool = False,
    ) -> tuple[str, str]:
        capsule_id = "capsule-brand"
        version_id = "version-brand"
        digest = hashlib.sha256(version_id.encode()).hexdigest()
        now = "2026-07-15T00:00:00Z"
        row = {
            "version_id": version_id,
            "capsule_id": capsule_id,
            "version_number": 1,
            "extraction_contract_version": extraction_version,
            "extraction_summary_json": json.dumps(
                extraction_summary or {}, sort_keys=True, separators=(",", ":")
            ),
            "redaction_rules_version": "redaction_rules.v1",
            "canonicalization_version": 1,
            "canonical_hash": digest,
            "activation_json": "{}",
            "input_contract_json": (
                '{"additional_properties":false,"properties":{},"required":[],'
                '"schema":"data_contract.v1","type":"object"}'
                if formal_contracts
                else "{}"
            ),
            "output_contract_json": (
                '{"additional_properties":false,"properties":{},"required":[],'
                '"schema":"data_contract.v1","type":"object"}'
                if formal_contracts
                else "{}"
            ),
            "error_contract_json": (
                '{"errors":{},"schema":"error_contract.v1"}'
                if formal_contracts
                else "{}"
            ),
            "runtime_allowlist_json": "[]",
            "dom_scope_json": "{}",
            "usage_scope_json": '{"kind":"general"}',
            "html_text": "",
            "css_text": "",
            "javascript_modules_json": "[]",
            "cleaning_summary_json": "{}",
            "security_rules_version": "security_rules.v1",
            "supervision_rules_version": "supervision_rules.v1",
            "supervision_model_name": "test-model",
            "supervision_model_digest": digest,
            "supervised_at": now,
            "supervision_result_json": "{}",
            "supervision_response_hash": digest,
            "validation_contract_version": "validation_contract.v1",
            "validation_result_json": "{}",
            "created_at": now,
        }
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO capability_groups VALUES ('brand_capability', 'Brand', ?, ?)",
                (now, now),
            )
            connection.execute(
                "INSERT INTO capsules VALUES (?, 'brand_capability', 'role', 'default', "
                "'computation', 'pending_revalidation', NULL, ?)",
                (capsule_id, now),
            )
            connection.execute(
                f"INSERT INTO capsule_versions ({', '.join(row)}) "
                f"VALUES ({', '.join('?' for _ in row)})",
                tuple(row.values()),
            )
            connection.execute(
                "UPDATE capsules SET current_version_id = ?, status = 'active' "
                "WHERE capsule_id = ?",
                (version_id, capsule_id),
            )
            connection.execute(
                "INSERT INTO capsule_sources VALUES ('source-brand', ?, ?, ?, 'project', "
                "'index.html', ?, ?, 'exact', ?)",
                (
                    version_id,
                    project_id,
                    f"project:{project_id}",
                    digest,
                    digest,
                    now,
                ),
            )
        return capsule_id, version_id

    def test_management_state_is_separate_and_lazy(self) -> None:
        state = self.service.get_initial_state()

        self.assertFalse(self.store.path.exists())
        self.assertIn("capsules", state)
        self.assertTrue(state["capsuleIngestionV1"]["generationActive"])
        self.assertTrue(
            state["capsuleIngestionV1"]["capabilities"]["generationFromSqlite"]
        )
        self.assertFalse(state["capsuleIngestionV1"]["databaseInitialized"])

        groups = self.service.list_capability_groups()
        self.assertEqual(groups, {"ok": True, "data": {"groups": []}})
        self.assertTrue(self.store.path.is_file())

    def test_historical_product_is_visible_without_becoming_history_or_retryable(self) -> None:
        backup = self.state / "backups" / "capsule_warehouse.pre_restore.test.sqlite3"
        backup.parent.mkdir(parents=True)
        backup.write_bytes(b"pre-restore")
        product = {
            "product_id": "product_" + "a" * 32,
            "path": self.state / "products" / ("product_" + "a" * 32),
            "manifest": {},
            "manifest_digest": "b" * 64,
            "status": "historical_version_unavailable_after_restore",
        }
        with patch.object(self.service, "_product_records", return_value=[product]):
            state = self.service.get_initial_state()

        management = state["capsuleIngestionV1"]
        self.assertEqual(state["history"], [])
        self.assertEqual(management["recoverableProducts"], [])
        self.assertEqual(
            management["historicalProducts"],
            [
                {
                    "product_id": product["product_id"],
                    "status": "historical_version_unavailable_after_restore",
                    "manifest_digest": "b" * 64,
                    "pre_restore_backup_path": str(backup.resolve()),
                }
            ],
        )

    def test_capability_display_name_can_change_without_changing_identity(self) -> None:
        self.store.initialize()
        created_at = "2026-07-16T00:00:00Z"
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO capability_groups VALUES ('quote', 'Old name', ?, ?)",
                (created_at, created_at),
            )
        result = self.service.rename_capability_group(
            {"capability_key": "quote", "display_name": "  Quote calculator  "}
        )
        self.assertEqual(
            result,
            {
                "ok": True,
                "data": {
                    "capability_key": "quote",
                    "display_name": "Quote calculator",
                },
            },
        )
        with self.store.read_connection() as connection:
            group = connection.execute(
                "SELECT * FROM capability_groups WHERE capability_key = 'quote'"
            ).fetchone()
            version_count = connection.execute(
                "SELECT COUNT(*) FROM capsule_versions"
            ).fetchone()[0]
        self.assertEqual(group["capability_key"], "quote")
        self.assertEqual(group["display_name"], "Quote calculator")
        self.assertEqual(group["created_at"], created_at)
        self.assertEqual(version_count, 0)

        for payload, code in (
            ({"capability_key": "quote", "display_name": "   "}, "capability_display_name_invalid"),
            ({"capability_key": "quote", "display_name": "x" * 201}, "capability_display_name_invalid"),
            ({"capability_key": "missing", "display_name": "Name"}, "capability_group_not_found"),
            ({"capability_key": "../quote", "display_name": "Name"}, "capability_key_invalid"),
        ):
            with self.subTest(payload=payload):
                rejected = self.service.rename_capability_group(payload)
                self.assertFalse(rejected["ok"])
                self.assertEqual(rejected["error"]["code"], code)

    def test_long_tasks_are_serial_and_errors_do_not_leak(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        active = 0
        maximum = 0
        guard = threading.Lock()

        def blocked(_cancel: threading.Event) -> dict[str, bool]:
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(maximum, active)
            entered.set()
            release.wait(2)
            with guard:
                active -= 1
            return {"done": True}

        first = self.service._submit_management_task("probe", blocked)
        self.assertTrue(entered.wait(1))
        second = self.service._submit_management_task(
            "secret_probe",
            lambda _cancel: (_ for _ in ()).throw(RuntimeError("customer-secret")),
        )
        release.set()

        self.assertEqual(self._wait(first["run_id"])["status"], "completed")
        failed = self._wait(second["run_id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"]["code"], "secret_probe_failed")
        self.assertNotIn("customer-secret", str(failed))
        self.assertEqual(maximum, 1)

    def test_close_cancels_queued_tasks_and_waits_for_running_action(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        queued_ran = threading.Event()

        def running(_cancel: threading.Event) -> dict[str, bool]:
            entered.set()
            release.wait(2)
            return {"committed": True}

        first = self.service._submit_management_task(
            "product_plan_close_running",
            running,
            read_only_planning=True,
        )
        self.assertTrue(entered.wait(1))
        second = self.service._submit_management_task(
            "product_plan_close_queued",
            lambda _cancel: (
                queued_ran.set(),
                {"should_not_run": True},
            )[1],
            read_only_planning=True,
        )
        closed = threading.Event()

        def close_service() -> None:
            self.service.close()
            closed.set()

        closer = threading.Thread(target=close_service)
        closer.start()
        deadline = time.monotonic() + 2
        while not self.service._management_closed:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        rejected = self.service._submit_management_task(
            "product_plan_after_close",
            lambda _cancel: {"should_not_run": True},
            read_only_planning=True,
        )
        self.assertEqual(
            rejected["error"]["code"],
            "capsule_management_closed",
        )
        with patch.object(
            self.service,
            "_ensure_capsule_management",
            side_effect=AssertionError("closed service touched state"),
        ):
            self.assertEqual(
                self.service._submit_management_task(
                    "ordinary_after_close",
                    lambda _cancel: {"should_not_run": True},
                )["error"]["code"],
                "capsule_management_closed",
            )
        self.assertFalse(closed.is_set())
        release.set()
        closer.join(2)
        self.assertTrue(closed.is_set())
        self.assertFalse(queued_ran.is_set())
        self.assertEqual(
            self.service._management_tasks[first["run_id"]]["status"],
            "completed",
        )
        self.assertEqual(
            self.service._management_tasks[second["run_id"]]["status"],
            "cancelled",
        )
        self.service.close()

    def test_read_only_product_planning_task_does_not_initialize_warehouse(self) -> None:
        self.assertFalse(self.store.path.exists())

        started = self.service._submit_management_task(
            "product_plan_probe",
            lambda _cancel: {"read_only": True},
            read_only_planning=True,
        )

        task = self._wait_product_plan(started["run_id"])
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["data"], {"read_only": True})
        self.assertFalse(self.store.path.exists())
        with self.assertRaisesRegex(ValueError, "read_only_planning_kind_invalid"):
            self.service._submit_management_task(
                "refresh_project",
                lambda _cancel: {},
                read_only_planning=True,
            )

    def test_product_planning_catalog_is_exact_eligible_and_code_free(self) -> None:
        project_id = self._ready_project()
        capsule_id, version_id = self._seed_project_contribution(
            project_id,
            formal_contracts=True,
        )
        before = self.store.current_revision()

        with patch.object(self.service._capsule_stage3, "_eligible_exact", return_value=True):
            catalog = self.service._product_planning_catalog()

        self.assertEqual(catalog["warehouse_revision"], before)
        self.assertEqual(len(catalog["capsules"]), 1)
        capsule = catalog["capsules"][0]
        self.assertEqual(
            (capsule["capsule_id"], capsule["version_id"]),
            (capsule_id, version_id),
        )
        self.assertEqual(capsule["identity_status"], "formal_exact_version")
        self.assertEqual(capsule["input_contract"]["schema"], "data_contract.v1")
        self.assertIn(
            capsule["output_contract"]["schema"],
            {"data_contract.v1", "event_outputs.v1", "no_output.v1"},
        )
        self.assertEqual(capsule["error_contract"]["schema"], "error_contract.v1")
        self.assertNotIn("html_text", capsule)
        self.assertNotIn("css_text", capsule)
        self.assertNotIn("javascript_modules_json", capsule)
        self.assertNotIn("source_relpath", capsule)
        self.assertNotIn(str(self.root), str(catalog))
        self.assertEqual(self.store.current_revision(), before)

    def test_product_workspace_restore_receives_current_exact_catalog(self) -> None:
        current = {"warehouse_revision": 11, "capsules": []}
        with patch.object(
            self.service,
            "_product_planning_catalog",
            return_value=current,
        ), patch.object(
            self.service._product_planner,
            "get",
            return_value={"ok": True, "data": {"status": "plan_review"}},
        ) as get_workspace:
            result = self.service.get_product_plan_workspace(
                {"plan_token": "plan_token_" + "a" * 48}
            )
        self.assertTrue(result["ok"])
        get_workspace.assert_called_once_with(
            "plan_token_" + "a" * 48,
            current,
        )

    def test_product_planning_actions_are_read_only_and_task_types_are_isolated(
        self,
    ) -> None:
        self.assertFalse(self.store.path.exists())
        with patch.object(
            self.service._product_planner,
            "list_models",
            return_value={"ok": True, "data": {"models": []}},
        ):
            started = self.service.list_product_planning_models({})
            task = self._wait_product_plan(started["run_id"])
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["data"]["data"]["models"], [])
        self.assertFalse(self.store.path.exists())
        self.assertEqual(
            self.service.get_intake_run({"run_id": started["run_id"]})["error"]["code"],
            "intake_run_not_found",
        )

        entered = threading.Event()
        release = threading.Event()

        def blocked(_cancel: threading.Event) -> dict[str, bool]:
            entered.set()
            release.wait(2)
            return {"ok": True}

        planning = self.service._submit_management_task(
            "product_plan_start",
            blocked,
            cancellable=True,
            read_only_planning=True,
        )
        self.assertTrue(entered.wait(1))
        self.assertEqual(
            self.service.cancel_intake_run({"run_id": planning["run_id"]})["error"]["code"],
            "intake_run_not_cancellable",
        )
        cancelled = self.service.cancel_product_plan_run(
            {"run_id": planning["run_id"]}
        )
        self.assertTrue(cancelled["ok"])
        release.set()
        self.assertIn(
            self._wait_product_plan(planning["run_id"])["status"],
            {"completed", "cancelled"},
        )

        ordinary = self.service._submit_management_task(
            "probe",
            lambda _cancel: {"ok": True},
        )
        self.assertEqual(
            self.service.get_product_plan_run({"run_id": ordinary["run_id"]})[
                "error"
            ]["code"],
            "product_plan_run_not_found",
        )
        self.assertEqual(
            self.service.cancel_product_plan_run({"run_id": ordinary["run_id"]})[
                "error"
            ]["code"],
            "product_plan_run_not_cancellable",
        )
        self.assertEqual(self._wait(ordinary["run_id"])["status"], "completed")

    def test_product_plan_action_suggestion_is_thin_and_read_only(self) -> None:
        self.assertFalse(self.store.path.exists())
        with patch.object(
            self.service._product_planner,
            "suggest_action",
            return_value={
                "ok": True,
                "data": {
                    "suggested_action": "ask_plan",
                    "recommendation_available": True,
                    "suggestion_receipt": "suggestion_receipt_" + "b" * 48,
                    "suggestion_digest": "c" * 64,
                },
            },
        ) as suggest:
            started = self.service.suggest_product_plan_action(
                {
                    "plan_token": "plan_token_" + "a" * 48,
                    "feedback": "解释当前计划",
                }
            )
            task = self._wait_product_plan(started["run_id"])
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["data"]["data"]["suggested_action"], "ask_plan")
        suggest.assert_called_once()
        args = suggest.call_args.args
        self.assertEqual(args[:2], ("plan_token_" + "a" * 48, "解释当前计划"))
        self.assertTrue(callable(args[2]))
        self.assertFalse(self.store.path.exists())

    def test_product_planning_error_envelopes_drive_task_terminal_status(self) -> None:
        failed = self.service._submit_management_task(
            "product_plan_list_models",
            lambda _cancel: {
                "ok": False,
                "error": {
                    "code": "ollama_unavailable",
                    "message_key": "ollama_unavailable",
                },
            },
            read_only_planning=True,
        )
        failed_task = self._wait_product_plan(failed["run_id"])
        self.assertEqual(failed_task["status"], "failed")
        self.assertEqual(failed_task["error"]["code"], "ollama_unavailable")

        cancelled = self.service._submit_management_task(
            "product_plan_start",
            lambda _cancel: {
                "ok": False,
                "error": {
                    "code": "product_plan_cancelled",
                    "message_key": "product_plan_cancelled",
                },
            },
            cancellable=True,
            read_only_planning=True,
        )
        cancelled_task = self._wait_product_plan(cancelled["run_id"])
        self.assertEqual(cancelled_task["status"], "cancelled")

    def test_confirmed_candidate_terminal_retry_is_explicit_and_bounded(self) -> None:
        request = {
            "plan_token": "plan_token_" + "a" * 48,
            "plan_digest": "b" * 64,
            "acceptance_confirmation_digest": "c" * 64,
        }
        calls = 0

        def build(*_args: object) -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("transient")
            return {"candidate_token": "candidate_" + "d" * 32}

        with patch.object(
            self.service,
            "_build_confirmed_product_candidate",
            side_effect=build,
        ):
            first = self.service.start_confirmed_product_candidate(request)
            self.assertEqual(
                self._wait(first["run_id"])["status"],
                "failed",
            )
            self.service._management_tasks[first["run_id"]]["future"].result(
                timeout=2
            )
            retried = self.service.start_confirmed_product_candidate(request)
            self.assertEqual(retried["run_id"], first["run_id"])
            self.assertEqual(
                self._wait(retried["run_id"])["status"],
                "completed",
            )
            completed = self.service.start_confirmed_product_candidate(request)
            self.assertEqual(completed["run_id"], first["run_id"])
            self.assertEqual(completed["status"], "completed")
        self.assertEqual(calls, 2)

        cancelled_run = "run_" + "e" * 32
        cancelled = self.service._submit_management_task(
            "product_candidate_start_confirmed",
            lambda _cancel: {"status": "cancelled"},
            run_id=cancelled_run,
            cancellable=True,
            read_only_candidate=True,
            retry_terminal=True,
        )
        self.assertEqual(
            self._wait(cancelled["run_id"])["status"],
            "cancelled",
        )
        self.service._management_tasks[cancelled["run_id"]]["future"].result(
            timeout=2
        )
        retry_calls = 0

        def retry(_cancel: threading.Event) -> dict[str, bool]:
            nonlocal retry_calls
            retry_calls += 1
            return {"retried": True}

        restarted = self.service._submit_management_task(
            "product_candidate_start_confirmed",
            retry,
            run_id=cancelled_run,
            read_only_candidate=True,
            retry_terminal=True,
        )
        self.assertEqual(
            self._wait(restarted["run_id"])["status"],
            "completed",
        )
        self.assertEqual(retry_calls, 1)

    def test_confirmed_candidate_concurrent_starts_share_one_attempt(self) -> None:
        request = {
            "plan_token": "plan_token_" + "1" * 48,
            "plan_digest": "2" * 64,
            "acceptance_confirmation_digest": "3" * 64,
        }
        entered = threading.Event()
        release = threading.Event()
        calls = 0

        def build(*_args: object) -> dict[str, object]:
            nonlocal calls
            calls += 1
            entered.set()
            release.wait(2)
            return {"candidate_token": "candidate_" + "4" * 32}

        with patch.object(
            self.service,
            "_build_confirmed_product_candidate",
            side_effect=build,
        ):
            first = self.service.start_confirmed_product_candidate(request)
            self.assertTrue(entered.wait(1))
            responses: list[dict[str, object]] = []

            def start() -> None:
                responses.append(
                    self.service.start_confirmed_product_candidate(request)
                )

            threads = [threading.Thread(target=start) for _ in range(100)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(2)
            release.set()
            self.assertEqual(
                self._wait(first["run_id"])["status"],
                "completed",
            )
        self.assertEqual(
            {response["run_id"] for response in responses},
            {first["run_id"]},
        )
        self.assertEqual(calls, 1)

    def test_product_planning_payloads_reject_unknown_fields(self) -> None:
        cases = (
            (
                self.service.list_product_planning_models,
                {"unexpected": True},
                "product_planning_request_invalid",
            ),
            (
                self.service.select_product_planning_model,
                {"name": "small", "digest": "a" * 64, "unexpected": True},
                "product_planning_model_required",
            ),
            (
                self.service.start_product_plan,
                {"goal": "plan", "unexpected": True},
                "product_plan_goal_invalid",
            ),
            (
                self.service.submit_product_plan_answers,
                {
                    "plan_token": "token",
                    "question_set_digest": "a" * 64,
                    "answers": [],
                    "unexpected": True,
                },
                "product_plan_answers_invalid",
            ),
            (
                self.service.suggest_product_plan_action,
                {
                    "plan_token": "token",
                    "feedback": "change",
                    "unexpected": True,
                },
                "product_plan_action_suggestion_invalid",
            ),
            (
                self.service.revise_product_plan,
                {
                    "plan_token": "token",
                    "action": "request",
                    "message": "change",
                    "unexpected": True,
                },
                "product_plan_revision_invalid",
            ),
            (
                self.service.get_product_plan_workspace,
                {"plan_token": "token", "unexpected": True},
                "product_plan_token_invalid",
            ),
            (
                self.service.get_product_plan_run,
                {"run_id": "run", "unexpected": True},
                "product_plan_run_id_required",
            ),
            (
                self.service.cancel_product_plan_run,
                {"run_id": "run", "unexpected": True},
                "product_plan_run_id_required",
            ),
            (
                self.service.confirm_product_plan,
                {
                    "plan_token": "token",
                    "plan_digest": "a" * 64,
                    "unexpected": True,
                },
                "product_plan_confirmation_invalid",
            ),
        )
        for method, payload, code in cases:
            with self.subTest(method=method.__name__):
                self.assertEqual(method(payload)["error"]["code"], code)

    def test_cancel_after_action_commit_keeps_completed_task_status(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def committed(_cancel: threading.Event) -> dict[str, object]:
            entered.set()
            release.wait(2)
            return {"committed": True}

        started = self.service._submit_management_task(
            "commit_probe", committed, cancellable=True
        )
        self.assertTrue(entered.wait(1))
        cancelled = self.service.cancel_intake_run({"run_id": started["run_id"]})
        self.assertTrue(cancelled["ok"])
        release.set()

        task = self._wait(started["run_id"])
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["data"], {"committed": True})

    def test_computation_adapter_v1_inspection_is_retired_without_source_read(self) -> None:
        project_id = self._ready_project()
        revision_before = self.store.current_revision()
        with self.store.read_connection() as connection:
            formal_before = tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("capsules", "capsule_versions", "product_capsule_usage")
            )
        with patch.object(
            self.service._capsule_intake,
            "inspect_computation_adapters",
        ) as inspect:
            result = self.service.start_inspect_computation_adapters(
                {"project_id": project_id}
            )

        self.assertEqual(result["error"]["code"], "adapter_creation_path_retired")
        inspect.assert_not_called()
        self.assertEqual(self.store.current_revision(), revision_before)
        with self.store.read_connection() as connection:
            formal_after = tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("capsules", "capsule_versions", "product_capsule_usage")
            )
        self.assertEqual(formal_after, formal_before)

    def test_computation_adapter_v1_create_is_retired_without_preflight(self) -> None:
        project_id = self._ready_project()
        request = {
            "project_id": project_id,
            "offer_id": "offer-1",
            "arguments": [
                {
                    "source_parameter": "quantity",
                    "input_field": "quantity",
                    "minimum": 0,
                    "maximum": 10,
                }
            ],
            "result_field": "total",
            "examples": [{"input": {"quantity": 4}, "expected": 20}],
            "module_relpath": "forged.js",
            "function_sha256": "f" * 64,
            "source_hash": "e" * 64,
        }
        with patch.object(
            self.service._capsule_intake,
            "create_computation_adapter_candidate",
        ) as create, patch.object(
            self.service._capsule_stage3,
            "preflight_computation_adapter",
            create=True,
        ) as validator, patch.object(
            self.store, "read_connection"
        ) as warehouse_read:
            result = self.service.start_create_computation_adapter(request)

        self.assertEqual(result["error"]["code"], "adapter_creation_path_retired")
        create.assert_not_called()
        validator.assert_not_called()
        warehouse_read.assert_not_called()

    def _scan_v2_offer(self, project_id: str) -> tuple[str, dict[str, object]]:
        if not _descriptor_relative_snapshot_supported():
            self.skipTest("descriptor-relative snapshot primitives are unavailable")
        source = self.root / "project" / "calculate.js"
        source.write_text(
            "export function calculate(quantity) { return quantity * 2; }\n",
            encoding="utf-8",
        )
        offer = {
            "offer_id": "a" * 64,
            "module_relpath": "calculate.js",
            "export_name": "calculate",
            "target_binding_id": "b" * 64,
            "parameters": [
                {"parameter_binding_id": "c" * 64, "name": "quantity"}
            ],
            "dependency_count": 0,
        }

        def inspect(snapshot):
            return {
                "schema": "computation_capture_offers.v2",
                "project_id": snapshot.project_id,
                "source_identity_sha256": snapshot.source_identity_sha256,
                "scope_snapshot_sha256": snapshot.scope_snapshot_sha256,
                "offers": [offer],
            }

        with patch(
            "pimos_lite.reweave_app_service.inspect_ephemeral_computation_offers_v2",
            side_effect=inspect,
        ):
            started = self.service.start_scan_javascript_computations(
                {"project_id": project_id}
            )
            task = self._wait(started["run_id"])
        self.assertEqual(task["status"], "completed")
        inspection = task["data"]
        return str(inspection["project_id"]), offer

    def test_javascript_source_registration_and_scan_use_one_owner_and_safe_offers(self) -> None:
        static_id = self._ready_project()
        with self.store.read_connection() as connection:
            static = connection.execute(
                "SELECT source_root_id FROM projects WHERE project_id = ?",
                (static_id,),
            ).fetchone()
        registered = self.service.register_javascript_computation_source(
            {
                "source_root_id": static["source_root_id"],
                "project_relpath": ".",
                "display_name": "Pricing computations",
            }
        )
        repeated = self.service.register_javascript_computation_source(
            {
                "source_root_id": static["source_root_id"],
                "project_relpath": ".",
                "display_name": "Pricing computations",
            }
        )
        self.assertTrue(registered["ok"])
        self.assertEqual(
            registered["data"]["project_id"], repeated["data"]["project_id"]
        )

        owner_id, offer = self._scan_v2_offer(static_id)
        self.assertEqual(owner_id, registered["data"]["project_id"])
        with self.store.read_connection() as connection:
            owners = connection.execute(
                "SELECT COUNT(*) FROM projects WHERE source_type = "
                "'javascript_computation_source'"
            ).fetchone()[0]
            formal = tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("capsules", "capsule_versions", "product_capsule_usage")
            )
        self.assertEqual(owners, 1)
        self.assertEqual(formal, (0, 0, 0))
        self.assertEqual(
            self.service._javascript_capture_sessions[owner_id]["offers"][
                offer["offer_id"]
            ]["target_binding_id"],
            "b" * 64,
        )

    def test_static_unsupported_scan_reuses_v2_owner_without_legacy_adapter(self) -> None:
        static_id = self._ready_project()
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE projects SET project_state = 'unsupported_v1' WHERE project_id = ?",
                (static_id,),
            )
        with (
            patch.object(
                self.service._capsule_intake, "inspect_computation_adapters"
            ) as legacy_inspect,
            patch.object(
                self.service._capsule_intake,
                "create_computation_adapter_candidate",
            ) as legacy_create,
        ):
            first_owner, _offer = self._scan_v2_offer(static_id)
            second_owner, _offer = self._scan_v2_offer(static_id)

        self.assertEqual(first_owner, second_owner)
        legacy_inspect.assert_not_called()
        legacy_create.assert_not_called()
        with self.store.read_connection() as connection:
            owners = connection.execute(
                "SELECT COUNT(*) FROM projects WHERE source_type = "
                "'javascript_computation_source'"
            ).fetchone()[0]
            formal = tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("capsules", "capsule_versions", "product_capsule_usage")
            )
        self.assertEqual(owners, 1)
        self.assertEqual(formal, (0, 0, 0))

    def test_v2_create_uses_authoritative_offer_and_allows_bound_resubmission(self) -> None:
        static_id = self._ready_project()
        owner_id, offer = self._scan_v2_offer(static_id)
        mapping = {
            "project_id": owner_id,
            "offer_id": offer["offer_id"],
            "review_id": None,
            "arguments": [
                {
                    "parameter_binding_id": "c" * 64,
                    "input_field": "quantity",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                }
            ],
            "result_field": "total",
            "examples": [{"input": {"quantity": 4}, "expected": 8}],
        }
        waiting = {
            "schema": "ephemeral_capture_outcome.v1",
            "status": "waiting_user",
            "review_id": "review-v2",
            "resume_contract": "resubmit_ephemeral_capture.v1",
        }
        with patch.object(
            self.service._capsule_stage3,
            "prepare_ephemeral_computation_capture_v2",
            return_value=waiting,
        ) as prepare:
            first = self.service.start_create_computation_adapter(mapping)
            first_task = self._wait(first["run_id"])
        self.assertEqual(first_task["data"], waiting)
        self.assertEqual(
            prepare.call_args.args[1],
            {
                "module_relpath": "calculate.js",
                "export_name": "calculate",
                "target_binding_id": "b" * 64,
            },
        )

        resubmission = {**mapping, "review_id": "review-v2"}
        with patch.object(
            self.service._capsule_stage3,
            "prepare_ephemeral_computation_capture_v2",
            return_value=waiting,
        ) as prepare_again:
            second = self.service.start_create_computation_adapter(resubmission)
            second_task = self._wait(second["run_id"])
        self.assertEqual(second_task["status"], "completed")
        self.assertEqual(prepare_again.call_args.kwargs["review_id"], "review-v2")
        forged = self.service.start_create_computation_adapter(
            {**resubmission, "module_relpath": "forged.js"}
        )
        self.assertFalse(forged["ok"])
        self.assertEqual(forged["error"]["code"], "capture_request_invalid")

    def test_v3_create_requires_explicit_schema_and_routes_exact_mapping(self) -> None:
        static_id = self._ready_project()
        owner_id, offer = self._scan_v2_offer(static_id)
        request = {
            "schema": "computation_capture_mapping.v3",
            "project_id": owner_id,
            "offer_id": offer["offer_id"],
            "review_id": None,
            "arguments": [
                {
                    "parameter_binding_id": "c" * 64,
                    "input_field": "quantity",
                    "kind": "integer",
                    "minimum": 1,
                    "maximum": 10,
                }
            ],
            "result_field": "unit_price",
            "passthrough_fields": ["quantity"],
            "examples": [
                {
                    "input": {"quantity": 5},
                    "expected": {"quantity": 5, "unit_price": 80},
                }
            ],
        }
        waiting = {
            "schema": "ephemeral_capture_outcome.v1",
            "status": "waiting_user",
            "review_id": "review-v3",
            "resume_contract": "resubmit_ephemeral_capture.v2",
        }
        with patch.object(
            self.service._capsule_stage3,
            "prepare_ephemeral_computation_capture_v3",
            return_value=waiting,
        ) as prepare:
            started = self.service.start_create_computation_adapter(request)
            task = self._wait(started["run_id"])
        self.assertEqual(task["data"], waiting)
        self.assertEqual(
            prepare.call_args.args[1],
            {
                "module_relpath": "calculate.js",
                "export_name": "calculate",
                "target_binding_id": "b" * 64,
            },
        )
        self.assertEqual(
            prepare.call_args.args[2],
            {
                "schema": "computation_capture_mapping.v3",
                "arguments": request["arguments"],
                "result_field": "unit_price",
                "passthrough_fields": ["quantity"],
                "examples": request["examples"],
            },
        )
        invalid = self.service.start_create_computation_adapter(
            {**request, "schema": "computation_capture_mapping.future"}
        )
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["error"]["code"], "capture_request_invalid")
        self.assertEqual(
            self.service._allowed_review_decisions(
                {
                    "candidate_status": "review_required",
                    "candidate": {
                        "candidate_origin": "deterministic_computation_adapter",
                        "adapter_contract_version": "computation_adapter.v3",
                        "usage_scope": {"kind": "general"},
                    },
                    "comparison": {},
                }
            ),
            ["reject"],
        )

    def test_v4_create_requires_explicit_schema_and_routes_exact_mapping(self) -> None:
        static_id = self._ready_project()
        owner_id, offer = self._scan_v2_offer(static_id)
        request = {
            "schema": "computation_capture_mapping.v4",
            "project_id": owner_id,
            "offer_id": offer["offer_id"],
            "review_id": None,
            "arguments": [
                {
                    "parameter_binding_id": "c" * 64,
                    "input_field": "enabled",
                    "kind": "boolean",
                }
            ],
            "result_field": "state",
            "result_enum": ["disabled", "enabled"],
            "proof_schema": "source_graph_proof.v2",
            "examples": [
                {"input": {"enabled": False}, "expected": {"state": "disabled"}},
                {"input": {"enabled": True}, "expected": {"state": "enabled"}},
            ],
        }
        waiting = {
            "schema": "ephemeral_capture_outcome.v1",
            "status": "waiting_user",
            "review_id": "review-v4",
            "resume_contract": "resubmit_ephemeral_capture.v3",
        }
        with patch.object(
            self.service._capsule_stage3,
            "prepare_ephemeral_computation_capture_v4",
            return_value=waiting,
        ) as prepare:
            started = self.service.start_create_computation_adapter(request)
            task = self._wait(started["run_id"])
        self.assertEqual(task["data"], waiting)
        self.assertEqual(
            prepare.call_args.args[2],
            {
                "schema": "computation_capture_mapping.v4",
                "arguments": request["arguments"],
                "result_field": "state",
                "result_enum": ["disabled", "enabled"],
                "proof_schema": "source_graph_proof.v2",
                "examples": request["examples"],
            },
        )
        guessed = dict(request)
        guessed.pop("schema")
        invalid = self.service.start_create_computation_adapter(guessed)
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["error"]["code"], "capture_request_invalid")

    def test_v2_real_record_resubmission_terminates_waiting_review(self) -> None:
        static_id = self._ready_project()
        owner_id, offer = self._scan_v2_offer(static_id)
        request = {
            "project_id": owner_id,
            "offer_id": offer["offer_id"],
            "review_id": "review-v2-real-record",
            "arguments": [
                {
                    "parameter_binding_id": "c" * 64,
                    "input_field": "quantity",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                }
            ],
            "result_field": "total",
            "examples": [{"input": {"quantity": 4}, "expected": 8}],
        }
        rejected = {
            "schema": "ephemeral_capture_outcome.v1",
            "status": "rejected",
            "error_code": "confirmed_real_record_rejected",
        }
        with patch.object(
            self.service._capsule_stage3,
            "prepare_ephemeral_computation_capture_v2",
            return_value=rejected,
        ), patch.object(
            self.service._capsule_stage3,
            "reject_review",
            return_value={"status": "rejected"},
        ) as reject_review:
            started = self.service.start_create_computation_adapter(request)
            task = self._wait(started["run_id"])

        self.assertEqual(task["data"], rejected)
        reject_review.assert_called_once_with(
            "review-v2-real-record",
            reason_code="confirmed_real_record_rejected",
        )

    def test_v2_review_decision_uses_one_time_stage3_authorization(self) -> None:
        binding = "d" * 64
        item = {
            "review_id": "review-v2",
            "candidate_status": "waiting_user",
            "candidate": {
                "candidate_origin": "deterministic_computation_adapter",
                "adapter_contract_version": "computation_adapter.v2",
                "requires_reextract": True,
                "resume_contract": "resubmit_ephemeral_capture.v1",
            },
            "redaction": {
                "codes": ["enumeration_confirmation_required"],
                "enum_decision_binding_sha256": binding,
            },
            "resume_contract": "resubmit_ephemeral_capture.v1",
            "enum_decision": None,
            "allowed_decisions": ["confirm_selected_string_enumeration"],
        }
        recorded = {"review_id": "review-v2", "enum_decision": "confirmed"}
        with patch.object(
            self.service,
            "list_review_items",
            return_value={"ok": True, "data": {"items": [item]}},
        ), patch.object(
            self.service._capsule_stage3,
            "record_ephemeral_capture_decisions",
            return_value=recorded,
        ) as record:
            result = self.service.decide_review_item(
                {
                    "review_id": "review-v2",
                    "decision": "confirm_selected_string_enumeration",
                }
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["capture_resubmission_required"])
        self.assertEqual(
            result["data"]["resume_contract"],
            "resubmit_ephemeral_capture.v1",
        )
        record.assert_called_once_with(
            "review-v2",
            binding,
            enum_decision="confirm_selected_string_enumeration",
        )

    def test_decided_ephemeral_review_remains_listed_for_restart_resubmission(self) -> None:
        project_id = self._ready_project()
        now = "2026-07-18T00:00:00.000Z"
        candidate = {
            "schema": "sanitized_candidate.v1",
            "candidate_origin": "deterministic_computation_adapter",
            "adapter_contract_version": "computation_adapter.v2",
            "requires_reextract": True,
            "resume_contract": "resubmit_ephemeral_capture.v1",
        }
        redaction = {
            "schema": "capture_redaction_summary.v1",
            "codes": ["sensitivity_confirmation_required"],
            "ambiguous_count": 1,
            "brand_count": 0,
            "enumeration_parameter_count": 0,
            "enumeration_value_count": 0,
            "enum_decision_binding_sha256": "d" * 64,
        }
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO intake_runs (run_id, project_id, run_kind, status, "
                "extraction_contract_version, redaction_rules_version, security_rules_version, "
                "supervision_rules_version, validation_contract_version, canonicalization_version, "
                "counts_json, created_at) VALUES ('capture-restart-run', ?, "
                "'refresh_project', 'completed_with_pending', "
                "'extraction_contract.v1', 'redaction_rules.v1', 'security_rules.v1', "
                "'supervision_rules.v1', 'validation_contract.v1', 1, '{}', ?)",
                (project_id, now),
            )
            connection.execute(
                "INSERT INTO review_items (review_id, run_id, project_id, candidate_id, "
                "candidate_status, source_relpath, source_location_json, source_hash, "
                "redaction_rules_version, sanitized_candidate_json, redaction_summary_json, "
                "sensitivity_decision, sensitivity_decided_at, created_at, updated_at) "
                "VALUES ('capture-restart-review', 'capture-restart-run', ?, "
                "'candidate-restart', 'waiting_user', '__ephemeral_capture__', '{}', ?, "
                "'redaction_rules.v1', ?, ?, 'confirm_fictional_fixture', ?, ?, ?)",
                (
                    project_id,
                    "a" * 64,
                    json.dumps(candidate, sort_keys=True, separators=(",", ":")),
                    json.dumps(redaction, sort_keys=True, separators=(",", ":")),
                    now,
                    now,
                    now,
                ),
            )

        listed = self.service.list_review_items({})

        self.assertTrue(listed["ok"])
        item = next(
            row
            for row in listed["data"]["items"]
            if row["review_id"] == "capture-restart-review"
        )
        self.assertEqual(item["allowed_decisions"], [])
        self.assertEqual(
            item["resume_contract"], "resubmit_ephemeral_capture.v1"
        )

        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE review_items SET candidate_status = 'rejected', "
                "decision = 'reject', decided_at = ?, updated_at = ? "
                "WHERE review_id = 'capture-restart-review'",
                (now, now),
            )
            self.store.bump_revision(connection)
        after_reject = self.service.list_review_items({})
        self.assertTrue(after_reject["ok"])
        self.assertNotIn(
            "capture-restart-review",
            {row["review_id"] for row in after_reject["data"]["items"]},
        )

    def test_v2_review_decisions_are_derived_from_safe_capture_evidence(self) -> None:
        decisions = self.service._allowed_review_decisions(
            {
                "candidate_status": "waiting_user",
                "candidate": {
                    "candidate_origin": "deterministic_computation_adapter",
                    "adapter_contract_version": "computation_adapter.v2",
                    "requires_reextract": True,
                    "resume_contract": "resubmit_ephemeral_capture.v1",
                },
                "redaction": {
                    "codes": [
                        "sensitivity_confirmation_required",
                        "brand_confirmation_required",
                        "enumeration_confirmation_required",
                    ]
                },
                "sensitivity_decision": None,
                "brand_decision": None,
                "enum_decision": None,
            }
        )
        self.assertEqual(
            decisions,
            [
                "confirm_fictional_fixture",
                "confirm_real_record_reject",
                "retain_brand_limited",
                "confirm_selected_string_enumeration",
            ],
        )
        self.assertNotIn("process_candidate", decisions)
        self.assertNotIn("confirm_safe_redaction", decisions)
        self.assertNotIn("remove_brand", decisions)

    def test_adapter_waiting_user_requires_explicit_recreation(self) -> None:
        decisions = self.service._allowed_review_decisions(
            {
                "candidate_status": "waiting_user",
                "candidate": {
                    "candidate_origin": "deterministic_computation_adapter",
                    "requires_reextract": True,
                },
                "redaction": {"codes": ["sensitivity_confirmation_required"]},
                "sensitivity_decision": None,
            }
        )

        self.assertNotIn("process_candidate", decisions)
        self.assertIn("confirm_safe_redaction", decisions)

    def test_retired_v1_review_remains_visible_but_cannot_be_decided(self) -> None:
        project_id = self._ready_project()
        now = "2026-07-18T00:00:00Z"
        candidate = {
            "candidate_origin": "deterministic_computation_adapter",
            "adapter_contract_version": "computation_adapter.v1",
        }
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO intake_runs (run_id, project_id, run_kind, status, "
                "extraction_contract_version, redaction_rules_version, security_rules_version, "
                "supervision_rules_version, validation_contract_version, canonicalization_version, "
                "counts_json, created_at) VALUES ('retired-v1-run', ?, 'refresh_project', "
                "'completed_with_pending', 'extraction_contract.v1', 'redaction_rules.v1', "
                "'security_rules.v1', 'supervision_rules.v1', 'validation_contract.v1', "
                "1, '{}', ?)",
                (project_id, now),
            )
            connection.execute(
                "INSERT INTO review_items (review_id, run_id, project_id, candidate_id, "
                "candidate_status, source_relpath, source_location_json, source_hash, "
                "redaction_rules_version, sanitized_candidate_json, redaction_summary_json, "
                "created_at, updated_at) VALUES ('retired-v1-review', 'retired-v1-run', ?, "
                "'retired-v1-candidate', 'waiting_user', 'calculate.js', '{}', ?, "
                "'redaction_rules.v1', ?, '{}', ?, ?)",
                (
                    project_id,
                    "a" * 64,
                    json.dumps(candidate, sort_keys=True, separators=(",", ":")),
                    now,
                    now,
                ),
            )

        listed = self.service.list_review_items({})
        self.assertTrue(listed["ok"], listed)
        item = next(
            row
            for row in listed["data"]["items"]
            if row["review_id"] == "retired-v1-review"
        )
        self.assertTrue(item["adapter_contract_version_expired"])
        self.assertEqual(item["allowed_decisions"], [])

        decided = self.service.decide_review_item(
            {"review_id": "retired-v1-review", "decision": "reject"}
        )
        self.assertEqual(
            decided["error"]["code"], "adapter_contract_version_expired"
        )
        with self.store.read_connection() as connection:
            unchanged = connection.execute(
                "SELECT candidate_status, decision, decided_at FROM review_items "
                "WHERE review_id = 'retired-v1-review'"
            ).fetchone()
        self.assertEqual(tuple(unchanged), ("waiting_user", None, None))

    def test_refresh_all_reports_cooperative_cancel(self) -> None:
        self.store.initialize()
        with self.store.transaction() as connection:
            for index in range(2):
                connection.execute(
                    "INSERT INTO source_roots VALUES (?, 'single_project', ?, 'bound', "
                    "NULL, NULL, NULL, 0, ?, ?)",
                    (
                        f"root-{index}",
                        str(self.root / f"project-{index}"),
                        "2026-07-15T00:00:00Z",
                        "2026-07-15T00:00:00Z",
                    ),
                )
                connection.execute(
                    "INSERT INTO projects VALUES (?, ?, '.', 'index.html', ?, 'ready', "
                    "?, NULL, 'inherit', NULL, NULL, NULL, 0, ?, ?)",
                    (
                        f"project-{index}",
                        f"root-{index}",
                        f"Project {index}",
                        f"signature-{index}",
                        "2026-07-15T00:00:00Z",
                        "2026-07-15T00:00:00Z",
                    ),
                )
        entered = threading.Event()

        def first_then_cancel(_project_id: str, cancel: threading.Event) -> dict[str, object]:
            entered.set()
            for _ in range(100):
                if cancel.is_set():
                    break
                time.sleep(0.005)
            return {"status": "cancelled", "intake": {}, "gate_results": []}

        with patch.object(self.service, "_refresh_project", side_effect=first_then_cancel) as refresh:
            started = self.service.start_refresh_all({})
            self.assertTrue(entered.wait(1))
            self.assertTrue(
                self.service.cancel_intake_run({"run_id": started["run_id"]})["ok"]
            )
            task = self._wait(started["run_id"])
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(refresh.call_count, 1)

    def test_refresh_stops_between_atomic_review_gates(self) -> None:
        project_id = self._ready_project()
        now = "2026-07-15T00:00:00Z"
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO intake_runs (run_id, project_id, run_kind, status, "
                "extraction_contract_version, redaction_rules_version, security_rules_version, "
                "supervision_rules_version, validation_contract_version, canonicalization_version, "
                "counts_json, created_at) VALUES ('gate-run', ?, 'refresh_project', 'completed', "
                "'extraction_contract.v1', 'redaction_rules.v1', 'security_rules.v1', "
                "'supervision_rules.v1', 'validation_contract.v1', 1, '{}', ?)",
                (project_id, now),
            )
            for index in range(2):
                connection.execute(
                    "INSERT INTO review_items "
                    "(review_id, run_id, project_id, candidate_id, candidate_status, "
                    "source_relpath, source_location_json, source_hash, redaction_rules_version, "
                    "sanitized_candidate_json, redaction_summary_json, created_at, updated_at) "
                    "VALUES (?, 'gate-run', ?, ?, 'extracted', 'index.html', '{}', ?, "
                    "'redaction_rules.v1', '{}', '{}', ?, ?)",
                    (
                        f"gate-review-{index}",
                        project_id,
                        f"candidate-{index}",
                        hashlib.sha256(f"source-{index}".encode()).hexdigest(),
                        now,
                        now,
                    ),
                )
        entered = threading.Event()
        release = threading.Event()

        def first_gate(review_id: str) -> dict[str, str]:
            entered.set()
            release.wait(2)
            return {"review_id": review_id, "status": "review_required"}

        with patch.object(
            self.service._capsule_intake,
            "run_intake",
            return_value={"review_ids": ["gate-review-0", "gate-review-1"]},
        ), patch.object(
            self.service._capsule_stage3, "process_review", side_effect=first_gate
        ) as process:
            started = self.service.start_refresh_project({"project_id": project_id})
            self.assertTrue(entered.wait(1))
            self.assertTrue(
                self.service.cancel_intake_run({"run_id": started["run_id"]})["ok"]
            )
            release.set()
            task = self._wait(started["run_id"])
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(process.call_count, 1)

    def test_existing_interrupted_run_is_recovered_by_initial_state(self) -> None:
        self.store.initialize()
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO intake_runs (run_id, project_id, run_kind, status, "
                "extraction_contract_version, redaction_rules_version, security_rules_version, "
                "supervision_rules_version, validation_contract_version, canonicalization_version, "
                "counts_json, created_at) VALUES "
                "('run_interrupted', NULL, 'legacy_import', 'queued', "
                "'extraction_contract.v1', 'redaction_rules.v1', 'security_rules.v1', "
                "'supervision_rules.v1', 'validation_contract.v1', 1, '{}', "
                "'2026-07-15T00:00:00Z')"
            )

        self.service.get_initial_state()

        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT status, error_code FROM intake_runs WHERE run_id = 'run_interrupted'"
            ).fetchone()
        self.assertEqual((row["status"], row["error_code"]), ("interrupted", "application_restarted"))

    def test_restore_waits_for_sync_operation_and_is_not_cancellable(self) -> None:
        self.store.initialize()
        backup = self.store.create_backup("manual")
        entered = threading.Event()
        release = threading.Event()
        restore_started = threading.Event()
        original_list = self.store.list_backups

        def blocked_list() -> list[dict[str, object]]:
            entered.set()
            release.wait(2)
            return original_list()

        def fake_restore(_path: str, *, expected_sha256: str) -> dict[str, object]:
            restore_started.set()
            return {"restored": True, "sha256": expected_sha256}

        with patch.object(self.store, "list_backups", side_effect=blocked_list), patch.object(
            self.store, "restore_backup", side_effect=fake_restore
        ):
            reader = threading.Thread(target=self.service.list_backups)
            reader.start()
            self.assertTrue(entered.wait(1))
            started = self.service.restore_backup(
                {"path": backup["path"], "expected_sha256": backup["sha256"]}
            )
            self.assertTrue(started["ok"])
            self.assertFalse(restore_started.wait(0.05))
            cancelled = self.service.cancel_intake_run({"run_id": started["run_id"]})
            self.assertEqual(cancelled["error"]["code"], "intake_run_not_cancellable")
            release.set()
            reader.join(1)
            self.assertEqual(self._wait(started["run_id"])["status"], "completed")
            self.assertTrue(restore_started.is_set())

    def test_restore_pending_rejects_sync_calls_and_returns_structured_state(self) -> None:
        self.store.initialize()
        backup = self.store.create_backup("manual")
        entered = threading.Event()
        release = threading.Event()

        def blocked_restore(_path: str, *, expected_sha256: str) -> dict[str, object]:
            entered.set()
            release.wait(2)
            return {"restored": True, "sha256": expected_sha256}

        with patch.object(self.store, "restore_backup", side_effect=blocked_restore):
            started = self.service.restore_backup(
                {"path": backup["path"], "expected_sha256": backup["sha256"]}
            )
            self.assertTrue(started["ok"])
            self.assertTrue(entered.wait(1))
            try:
                before = time.monotonic()
                rejected = self.service.list_capability_groups({})
                elapsed = time.monotonic() - before
                self.assertEqual(rejected["error"]["code"], "restore_in_progress")
                self.assertLess(elapsed, 0.5)

                state = self.service.get_initial_state()
                management = state["capsuleIngestionV1"]
                self.assertEqual(management["databaseStatus"], "restore_in_progress")
                self.assertFalse(state["canGenerateProduct"])
                self.assertFalse(state["engineStatus"]["available"])
            finally:
                release.set()
            self.service._management_tasks[started["run_id"]]["future"].result(
                timeout=2
            )
            self.assertEqual(self._wait(started["run_id"])["status"], "completed")

    def test_restore_pending_rejects_all_synchronous_product_writes(self) -> None:
        actions = (
            self.service.confirm_product_plan,
            self.service.record_product_capability_gap_decision,
            self.service.prepare_product_capability_source_proposal,
            self.service.confirm_product_candidate_acceptance,
            self.service.create_local_agent_handoff,
            self.service.revoke_local_agent_handoff,
        )
        self.service._restore_pending = True
        try:
            with patch.object(
                self.service,
                "_payload",
                side_effect=AssertionError("write method entered"),
            ):
                for action in actions:
                    with self.subTest(action=action.__name__):
                        rejected = action({})
                        self.assertEqual(
                            rejected["error"]["code"],
                            "restore_in_progress",
                        )
        finally:
            self.service._restore_pending = False
        self.assertFalse((self.state / "product_workspaces").exists())

    def test_restore_barrier_checks_again_after_operation_lock_wait(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        real_lock = self.service._capsule_operation_lock

        class BlockingLock:
            def __enter__(self) -> object:
                entered.set()
                release.wait(2)
                real_lock.acquire()
                return self

            def __exit__(self, *_args: object) -> None:
                real_lock.release()

        self.service._capsule_operation_lock = BlockingLock()
        result: list[dict[str, object]] = []
        with patch.object(
            self.service._product_planner,
            "revoke_agent_handoff_for_plan",
            side_effect=AssertionError("write method entered"),
        ):
            thread = threading.Thread(
                target=lambda: result.append(
                    self.service.revoke_local_agent_handoff(
                        {"plan_token": "plan_token_" + "a" * 48}
                    )
                )
            )
            thread.start()
            self.assertTrue(entered.wait(1))
            with self.service._management_lock:
                self.service._restore_pending = True
            release.set()
            thread.join(2)
        self.service._restore_pending = False
        self.service._capsule_operation_lock = real_lock
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0]["error"]["code"], "restore_in_progress")

    def test_corrupt_database_still_exposes_and_restores_valid_backup(self) -> None:
        self.store.initialize()
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO app_settings VALUES ('phase', '\"backup\"', ?)",
                ("2026-07-15T00:00:00Z",),
            )
        backup = self.store.create_backup("manual")
        corrupt_bytes = b"not a sqlite database\x00must be preserved"
        self.store.path.write_bytes(corrupt_bytes)

        state = self.service.get_initial_state()
        management = state["capsuleIngestionV1"]
        self.assertEqual(management["databaseStatus"], "unavailable")
        self.assertFalse(state["canGenerateProduct"])
        self.assertIn(backup["path"], {row["path"] for row in management["backups"]})

        listed = self.service.list_backups({})
        self.assertTrue(listed["ok"])
        self.assertIn(
            backup["path"],
            {row["path"] for row in listed["data"]["backups"] if row["valid"]},
        )

        started = self.service.restore_backup(
            {"path": backup["path"], "expected_sha256": backup["sha256"]}
        )
        self.assertTrue(started["ok"])
        self.service._management_tasks[started["run_id"]]["future"].result(timeout=2)
        task = self._wait(started["run_id"])
        self.assertEqual(task["status"], "completed")
        self.assertTrue(task["data"]["pre_restore_backup_is_raw"])
        self.assertEqual(
            Path(task["data"]["pre_restore_backup_path"]).read_bytes(), corrupt_bytes
        )
        with self.store.read_connection() as connection:
            phase = json.loads(
                connection.execute(
                    "SELECT value_json FROM app_settings WHERE setting_key = 'phase'"
                ).fetchone()[0]
            )
        self.assertEqual(phase, "backup")

    def test_model_selection_is_queued(self) -> None:
        with patch.object(
            self.service._capsule_supervisor,
            "select_model",
            return_value={"name": "local", "digest": "a" * 64},
        ):
            model = self.service.select_supervision_model(
                {"name": "local", "digest": "a" * 64}
            )
            self.assertEqual(self._wait(model["run_id"])["status"], "completed")

    def test_source_handoff_is_single_scoped_recoverable_and_runs_real_gates(
        self,
    ) -> None:
        project_id, source = self._ready_complete_project()
        self._select_test_supervision_model()
        source_before = {
            path.relative_to(source).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(source.iterdir())
            if path.is_file()
        }

        created = self.service.create_local_source_handoff(
            {"project_id": project_id}
        )
        self.assertTrue(created["ok"], created)
        token = created["data"]["source_handoff_token"]
        self.assertRegex(token, r"^source_handoff_token_[0-9a-f]{48}$")
        duplicate = self.service.create_local_source_handoff(
            {"project_id": project_id}
        )
        self.assertEqual(
            duplicate["error"]["code"],
            "source_handoff_already_active",
        )
        sidecars = list((self.state / "source_handoffs").glob("*.json"))
        self.assertEqual(len(sidecars), 1)
        sidecar_text = sidecars[0].read_text(encoding="utf-8")
        self.assertNotIn(token, sidecar_text)
        self.assertNotIn(str(source), sidecar_text)
        safe_status = next(
            project["source_handoff"]
            for project in self.service._capsule_management_state()[
                "projects"
            ]
            if project["project_id"] == project_id
        )
        self.assertEqual(
            set(safe_status),
            {
                "schema_version",
                "status",
                "created_at",
                "revoked_at",
                "run_id",
                "run_status",
            },
        )
        self.assertEqual(safe_status["status"], "active")
        self.assertNotIn(token, json.dumps(safe_status))

        binding = self.service._resolve_local_source_handoff(token)
        calls: list[str] = []

        def approve(_summary, capability_kind):
            calls.append(capability_kind)
            return (
                {
                    "schema_version": "capsule_supervision.v1",
                    "verdict": "approve",
                    "capability_kind": capability_kind,
                    "semantic_summary": "Bounded local capability.",
                    "keep_reason_codes": ["DECLARED_LOCAL_CAPABILITY"],
                    "remove_reason_codes": [],
                    "brand_signals": [],
                    "sensitive_data_status": "clear",
                    "hidden_dependency_codes": [],
                    "duplicate_suggestions": [],
                    "review_required": False,
                },
                "a" * 64,
                {
                    "name": "source-handoff-test-model",
                    "digest": "b" * 64,
                },
            )

        original_runtime = self.service._capsule_stage3._runtime_validation

        def layered_runtime(prepared):
            kind = prepared.artifact.canonical_payload["capability_kind"]
            if kind == "computation":
                return original_runtime(prepared)
            normal = len(prepared.fixtures["normal"])
            boundary = len(prepared.fixtures["boundary"])
            result = {
                "schema_version": "qweb_validation.v1",
                "status": "passed",
                "normal_cases": normal,
                "boundary_cases": boundary,
                "invalid_cases": len(prepared.fixtures["invalid"]),
                "repeated_render": kind == "presentation",
                "dispose_idempotent": kind == "interaction",
                "remount_checked": (
                    kind == "interaction" and normal + boundary > 1
                ),
                "acceptance_scope": (
                    "real_qwebengine_interaction"
                    if kind == "interaction"
                    else "real_qwebengine_render"
                ),
            }
            if kind == "interaction":
                names = sorted(
                    prepared.artifact.canonical_payload[
                        "output_contract"
                    ]["events"]
                )
                result.update(
                    {
                        "emission_count": len(names),
                        "emission_names": names,
                    }
                )
            return result

        with patch.object(
            self.service._capsule_supervisor,
            "supervise",
            side_effect=approve,
        ), patch.object(
            self.service._capsule_stage3,
            "_runtime_validation",
            side_effect=layered_runtime,
        ):
            # Layer isolation only: the 29-node process gate remains the QWeb authority.
            started = self.service._start_authorized_source_intake(binding)
            repeated = self.service._start_authorized_source_intake(binding)
            self.assertTrue(started["ok"], started)
            self.assertEqual(repeated["run_id"], started["run_id"])
            self.service._management_tasks[started["run_id"]][
                "future"
            ].result(timeout=30)

        run = self.service._get_authorized_source_intake_run(binding)
        reviews = self.service._get_authorized_source_review_summaries(
            binding
        )
        self.assertTrue(run["ok"], run)
        self.assertIn(
            run["data"]["status"],
            {"completed", "completed_with_pending"},
        )
        self.assertTrue(reviews["ok"], reviews)
        self.assertEqual(
            {item["status"] for item in reviews["data"]["items"]},
            {"review_required"},
        )
        self.assertEqual(
            {item["capability_kind"] for item in reviews["data"]["items"]},
            {"interaction", "presentation", "computation"},
        )
        self.assertEqual(
            sorted(calls),
            ["computation", "interaction", "presentation"],
        )
        with self.store.transaction() as connection:
            interrupted_review = connection.execute(
                "SELECT review_id FROM review_items WHERE run_id = ? "
                "ORDER BY review_id LIMIT 1",
                (binding["run_id"],),
            ).fetchone()[0]
            connection.execute(
                "UPDATE review_items SET candidate_status = "
                "'waiting_validation' WHERE review_id = ?",
                (interrupted_review,),
            )
        interrupted = self.service._get_authorized_source_intake_run(
            binding
        )
        self.assertEqual(interrupted["data"]["status"], "interrupted")
        self.assertEqual(
            interrupted["data"]["error_code"],
            "manual_recovery_required",
        )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE review_items SET candidate_status = "
                "'review_required' WHERE review_id = ?",
                (interrupted_review,),
            )
        with self.store.read_connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM intake_runs WHERE run_id = ?",
                    (binding["run_id"],),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM review_items WHERE run_id = ?",
                    (binding["run_id"],),
                ).fetchone()[0],
                3,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM capsules"
                ).fetchone()[0],
                0,
            )
        self.assertEqual(
            source_before,
            {
                path.relative_to(source).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in sorted(source.iterdir())
                if path.is_file()
            },
        )

        self.service.close()
        self.service = ReweaveAppService(
            engine=LocalReweaveEngine(),
            capsule_store=self.store,
        )
        restored = self.service._resolve_local_source_handoff(token)
        self.assertEqual(restored, binding)
        self.assertTrue(
            self.service._get_authorized_source_intake_run(restored)["ok"]
        )
        self.assertEqual(
            self.service._start_authorized_source_intake(restored)["run_id"],
            binding["run_id"],
        )
        revoked = self.service.revoke_local_source_handoff(
            {"project_id": project_id}
        )
        self.assertEqual(revoked["data"]["status"], "revoked")
        with self.assertRaisesRegex(
            RuntimeError,
            "source_handoff_revoked",
        ):
            self.service._resolve_local_source_handoff(token)
        with self.assertRaisesRegex(
            RuntimeError,
            "source_handoff_revoked",
        ):
            self.service._run_authorized_source_intake(
                binding,
                threading.Event(),
            )
        self.assertEqual(
            self.service.revoke_local_source_handoff(
                {"project_id": project_id}
            )["data"]["status"],
            "revoked",
        )

    def test_source_handoff_stale_tamper_and_multiple_active_fail_closed(
        self,
    ) -> None:
        project_id = self._ready_project()
        self._select_test_supervision_model()
        source = self.root / "project" / "index.html"
        original = source.read_bytes()
        first = self.service.create_local_source_handoff(
            {"project_id": project_id}
        )
        self.assertTrue(first["ok"], first)
        first_token = first["data"]["source_handoff_token"]

        source.write_bytes(original + b"\n")
        stale_status = next(
            project["source_handoff"]
            for project in self.service._capsule_management_state()[
                "projects"
            ]
            if project["project_id"] == project_id
        )
        self.assertEqual(stale_status["status"], "stale")
        with self.assertRaisesRegex(
            RuntimeError,
            "source_handoff_stale",
        ):
            self.service._resolve_local_source_handoff(first_token)
        source.write_bytes(original)
        self.assertTrue(
            self.service.revoke_local_source_handoff(
                {"project_id": project_id}
            )["ok"]
        )

        model_bound = self.service.create_local_source_handoff(
            {"project_id": project_id}
        )
        with patch.object(
            self.service._capsule_supervisor,
            "selected_model",
            return_value={
                "name": "changed-model",
                "digest": "c" * 64,
            },
        ), self.assertRaisesRegex(
            RuntimeError,
            "source_handoff_stale",
        ):
            self.service._resolve_local_source_handoff(
                model_bound["data"]["source_handoff_token"]
            )
        self.assertTrue(
            self.service.revoke_local_source_handoff(
                {"project_id": project_id}
            )["ok"]
        )

        revision_bound = self.service.create_local_source_handoff(
            {"project_id": project_id}
        )
        current_revision = self.store.current_revision()
        with patch.object(
            self.store,
            "current_revision",
            return_value=current_revision + 1,
        ), self.assertRaisesRegex(
            RuntimeError,
            "source_handoff_stale",
        ):
            self.service._resolve_local_source_handoff(
                revision_bound["data"]["source_handoff_token"]
            )
        self.assertTrue(
            self.service.revoke_local_source_handoff(
                {"project_id": project_id}
            )["ok"]
        )

        brand_bound = self.service.create_local_source_handoff(
            {"project_id": project_id}
        )
        with patch.object(
            self.service,
            "_source_handoff_brand_identity",
            return_value={
                "profile_id": "changed",
                "profile_digest": "d" * 64,
                "profile_version": 1,
            },
        ), self.assertRaisesRegex(
            RuntimeError,
            "source_handoff_stale",
        ):
            self.service._resolve_local_source_handoff(
                brand_bound["data"]["source_handoff_token"]
            )
        self.assertTrue(
            self.service.revoke_local_source_handoff(
                {"project_id": project_id}
            )["ok"]
        )

        second = self.service.create_local_source_handoff(
            {"project_id": project_id}
        )
        second_token = second["data"]["source_handoff_token"]
        second_digest = hashlib.sha256(
            second_token.encode("utf-8")
        ).hexdigest()
        directory = self.state / "source_handoffs"
        second_path = (
            directory / f"source_handoff_v1_{second_digest}.json"
        )
        record = json.loads(second_path.read_text(encoding="utf-8"))
        valid_record = dict(record)
        fake_token = "source_handoff_token_" + "c" * 48
        fake_digest = hashlib.sha256(
            fake_token.encode("utf-8")
        ).hexdigest()
        fake = {
            **record,
            "token_digest": fake_digest,
            "run_id": "run_" + "c" * 32,
        }
        fake["canonical_digest"] = canonical_json_digest(
            {
                key: value
                for key, value in fake.items()
                if key != "canonical_digest"
            }
        )
        fake_path = (
            directory / f"source_handoff_v1_{fake_digest}.json"
        )
        fake_path.write_text(
            json.dumps(
                fake,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        if os.name == "posix":
            fake_path.chmod(0o600)
        for token in (second_token, fake_token):
            with self.subTest(token=token), self.assertRaisesRegex(
                RuntimeError,
                "source_handoff_conflict",
            ):
                self.service._resolve_local_source_handoff(token)
        fake_path.unlink()

        record["snapshot_digest"] = "0" * 64
        second_path.write_text(
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        if os.name == "posix":
            second_path.chmod(0o600)
        with self.assertRaisesRegex(
            RuntimeError,
            "source_handoff_conflict",
        ):
            self.service._resolve_local_source_handoff(second_token)
        if os.name == "posix":
            second_path.unlink()
            symlink_target = self.root / "valid-source-handoff.json"
            symlink_target.write_text(
                json.dumps(
                    valid_record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            symlink_target.chmod(0o600)
            second_path.symlink_to(symlink_target)
            with self.assertRaisesRegex(
                RuntimeError,
                "source_handoff_conflict",
            ):
                self.service._resolve_local_source_handoff(second_token)

    def test_source_handoff_rejects_a_preexisting_run_with_wrong_snapshot(
        self,
    ) -> None:
        project_id = self._ready_project()
        self._select_test_supervision_model()
        created = self.service.create_local_source_handoff(
            {"project_id": project_id}
        )
        token = created["data"]["source_handoff_token"]
        binding = self.service._resolve_local_source_handoff(token)
        now = "2026-08-16T23:59:59.000Z"
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO intake_runs (run_id, project_id, run_kind, "
                "status, snapshot_before, snapshot_after, "
                "extraction_contract_version, redaction_rules_version, "
                "security_rules_version, supervision_rules_version, "
                "validation_contract_version, canonicalization_version, "
                "counts_json, completed_at, created_at) VALUES "
                "(?, ?, 'refresh_project', 'completed', ?, ?, "
                "'extraction_contract.v2', 'redaction_rules.v1', "
                "'not_run.stage2', 'not_run.stage2', 'not_run.stage2', "
                "1, '{}', ?, ?)",
                (
                    binding["run_id"],
                    project_id,
                    "0" * 64,
                    "0" * 64,
                    now,
                    now,
                ),
            )
        with self.assertRaisesRegex(
            RuntimeError,
            "source_handoff_conflict",
        ):
            self.service._resolve_local_source_handoff(token)

    def test_completed_management_tasks_are_bounded(self) -> None:
        self.store.initialize()
        run_ids = []
        with patch.object(
            self.service._capsule_supervisor, "list_models", return_value=[]
        ):
            for _ in range(105):
                started = self.service.list_supervision_models({})
                run_ids.append(started["run_id"])
                self.service._management_tasks[started["run_id"]]["future"].result(
                    timeout=2
                )

        self.assertEqual(len(self.service._management_tasks), 100)
        self.assertNotIn(run_ids[0], self.service._management_tasks)
        self.assertIn(run_ids[-1], self.service._management_tasks)
        self.assertTrue(
            all(
                task["status"] in {"completed", "failed", "cancelled"}
                for task in self.service._management_tasks.values()
            )
        )

    def test_scope_revalidation_target_allows_replace_current(self) -> None:
        allowed = self.service._allowed_review_decisions(
            {
                "candidate_status": "review_required",
                "candidate": {"usage_scope": {"kind": "general"}},
                "comparison": {
                    "candidates": [
                        {
                            "contract_match": False,
                            "scope_revalidation_match": True,
                        }
                    ]
                },
            }
        )
        self.assertIn("replace_current", allowed)

    def test_brand_change_atomically_requires_revalidation_and_queues_refresh(self) -> None:
        project_id = self._ready_project()
        capsule_id, version_id = self._seed_project_contribution(project_id)
        with patch.object(
            self.service,
            "_refresh_project",
            return_value={"intake": {"status": "completed"}, "gate_results": []},
        ):
            result = self.service.confirm_projects(
                {
                    "projects": [
                        {
                            "project_id": project_id,
                            "brand_mode": "replace",
                            "brand_profile": {"names": ["HP"]},
                        }
                    ]
                }
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["data"]["errors"], [])
            self.assertEqual(len(result["data"]["run_ids"]), 1)
            self.assertEqual(
                self._wait(result["data"]["run_ids"][0])["status"], "completed"
            )

        with self.store.read_connection() as connection:
            project = connection.execute(
                "SELECT brand_mode, brand_profile_digest FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            capsule = connection.execute(
                "SELECT status, current_version_id FROM capsules WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()
            events = connection.execute(
                "SELECT event_type, from_status, to_status, version_id, reason_code "
                "FROM capsule_status_events WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchall()
        expected_digest = hashlib.sha256(
            json.dumps(
                {"names": ["HP"]}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        self.assertEqual((project["brand_mode"], project["brand_profile_digest"]), ("replace", expected_digest))
        self.assertEqual((capsule["status"], capsule["current_version_id"]), ("pending_revalidation", version_id))
        self.assertEqual(
            [tuple(event) for event in events],
            [
                (
                    "revalidation_required",
                    "active",
                    "pending_revalidation",
                    version_id,
                    "brand_profile_changed",
                )
            ],
        )

    def test_extend_brand_mode_is_rejected_by_service(self) -> None:
        project_id = self._ready_project()

        result = self.service.confirm_projects(
            {
                "projects": [
                    {
                        "project_id": project_id,
                        "brand_mode": "extend",
                        "brand_profile": {"names": ["HP"]},
                    }
                ]
            }
        )

        self.assertEqual(result["error"]["code"], "project_brand_mode_invalid")

        self.service._capsule_intake.set_project_brand(
            project_id,
            mode="replace",
            brand_profile={"names": ["IBM"]},
        )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE projects SET brand_mode = 'extend' WHERE project_id = ?",
                (project_id,),
            )
        self.assertTrue(
            self.service._set_project_brand_and_require_revalidation(
                project_id,
                mode="inherit",
                brand_profile=None,
            )
        )
        self.assertEqual(
            self.service._capsule_intake.get_project(project_id)["brand_mode"],
            "inherit",
        )

    def test_pending_revalidation_cannot_be_manually_reenabled(self) -> None:
        project_id = self._ready_project()
        capsule_id, version_id = self._seed_project_contribution(project_id)
        pending = self.service.set_capsule_status(
            {"capsule_id": capsule_id, "status": "pending_revalidation"}
        )
        self.assertTrue(pending["ok"])

        with patch.object(
            self.service._capsule_stage3, "_eligible_exact", return_value=True
        ) as eligible:
            result = self.service.set_capsule_status(
                {"capsule_id": capsule_id, "status": "active"}
            )
        self.assertEqual(
            result["error"]["code"], "capsule_status_transition_invalid"
        )
        eligible.assert_not_called()
        disabled = self.service.set_capsule_status(
            {"capsule_id": capsule_id, "status": "disabled"}
        )
        self.assertTrue(disabled["ok"])
        with patch.object(
            self.service._capsule_stage3, "_eligible_exact", return_value=True
        ) as eligible_after_disable:
            bypass = self.service.set_capsule_status(
                {"capsule_id": capsule_id, "status": "active"}
            )
        self.assertEqual(bypass["error"]["code"], "capsule_revalidation_required")
        eligible_after_disable.assert_not_called()
        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT status, current_version_id FROM capsules WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()
        self.assertEqual((row["status"], row["current_version_id"]), ("disabled", version_id))

    def test_rule_version_upgrade_marks_active_current_version_for_revalidation(self) -> None:
        project_id = self._ready_project()
        capsule_id, version_id = self._seed_project_contribution(
            project_id,
            extraction_version="extraction_contract.v1",
        )

        state = self.service.get_initial_state()

        self.assertEqual(state["warehouseCapsules"], [])
        with self.store.read_connection() as connection:
            capsule = connection.execute(
                "SELECT status, current_version_id FROM capsules WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()
            event = connection.execute(
                "SELECT event_type, from_status, to_status, version_id, reason_code "
                "FROM capsule_status_events WHERE capsule_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (capsule_id,),
            ).fetchone()
        self.assertEqual(
            (capsule["status"], capsule["current_version_id"]),
            ("pending_revalidation", version_id),
        )
        self.assertEqual(
            tuple(event),
            (
                "revalidation_required",
                "active",
                "pending_revalidation",
                version_id,
                "rule_version_changed",
            ),
        )

    def test_adapter_contract_upgrade_only_marks_adapter_version_for_revalidation(self) -> None:
        project_id = self._ready_project()
        capsule_id, version_id = self._seed_project_contribution(
            project_id,
            extraction_summary={
                "candidate_origin": "deterministic_computation_adapter",
                "adapter_contract_version": "computation_adapter.v0",
            },
        )

        self.service.get_initial_state()

        with self.store.read_connection() as connection:
            capsule = connection.execute(
                "SELECT status, current_version_id FROM capsules WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()
            event = connection.execute(
                "SELECT event_type, reason_code FROM capsule_status_events "
                "WHERE capsule_id = ? ORDER BY created_at DESC LIMIT 1",
                (capsule_id,),
            ).fetchone()
        self.assertEqual(
            (capsule["status"], capsule["current_version_id"]),
            ("pending_revalidation", version_id),
        )
        self.assertEqual(
            tuple(event),
            ("revalidation_required", "adapter_contract_version_changed"),
        )
        self.assertEqual(COMPUTATION_ADAPTER_CONTRACT_VERSION, "computation_adapter.v1")

    def test_v1_retirement_requests_verified_backup_then_marks_active_current(self) -> None:
        project_id = self._ready_project()
        capsule_id, version_id = self._seed_project_contribution(
            project_id,
            extraction_summary={
                "candidate_origin": "deterministic_computation_adapter",
                "adapter_contract_version": "computation_adapter.v1",
            },
        )
        status_during_backup: list[str] = []

        def verified_backup(kind: str) -> dict[str, str]:
            with self.store.read_connection() as connection:
                status_during_backup.append(
                    str(
                        connection.execute(
                            "SELECT status FROM capsules WHERE capsule_id = ?",
                            (capsule_id,),
                        ).fetchone()[0]
                    )
                )
            return {
                "path": str(self.state / "backups" / "verified.sqlite3"),
                "kind": kind,
                "sha256": "f" * 64,
                "warehouse_revision": self.store.current_revision(),
            }

        with patch.object(
            self.store,
            "create_backup",
            side_effect=verified_backup,
        ) as backup:
            self.service.get_initial_state()

        backup.assert_called_once_with("upgrade")
        self.assertEqual(status_during_backup, ["active"])
        with self.store.read_connection() as connection:
            capsule = connection.execute(
                "SELECT status, current_version_id FROM capsules WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()
            events = connection.execute(
                "SELECT event_type, version_id, reason_code FROM capsule_status_events "
                "WHERE capsule_id = ? ORDER BY created_at",
                (capsule_id,),
            ).fetchall()
        self.assertEqual(
            tuple(capsule), ("pending_revalidation", version_id)
        )
        self.assertEqual(
            [tuple(row) for row in events],
            [
                (
                    "revalidation_required",
                    version_id,
                    "adapter_contract_version_changed",
                )
            ],
        )

    def test_v1_retirement_backup_failure_leaves_capsule_active(self) -> None:
        project_id = self._ready_project()
        capsule_id, version_id = self._seed_project_contribution(
            project_id,
            extraction_summary={
                "candidate_origin": "deterministic_computation_adapter",
                "adapter_contract_version": "computation_adapter.v1",
            },
        )

        with patch.object(
            self.store, "create_backup", side_effect=OSError("backup failed")
        ):
            state = self.service.get_initial_state()

        self.assertEqual(state["capsuleIngestionV1"]["databaseStatus"], "unavailable")
        with self.store.read_connection() as connection:
            capsule = connection.execute(
                "SELECT status, current_version_id FROM capsules WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()
            event_count = connection.execute(
                "SELECT COUNT(*) FROM capsule_status_events WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()[0]
        self.assertEqual(tuple(capsule), ("active", version_id))
        self.assertEqual(event_count, 0)

    def test_v1_retirement_rejects_warehouse_change_after_backup(self) -> None:
        project_id = self._ready_project()
        capsule_id, version_id = self._seed_project_contribution(
            project_id,
            extraction_summary={
                "candidate_origin": "deterministic_computation_adapter",
                "adapter_contract_version": "computation_adapter.v1",
            },
        )

        def racing_backup(_kind: str) -> dict[str, object]:
            revision = self.store.current_revision()
            with self.store.transaction() as connection:
                self.store.bump_revision(connection)
            return {
                "path": str(self.state / "backups" / "racing.sqlite3"),
                "kind": "upgrade",
                "sha256": "f" * 64,
                "warehouse_revision": revision,
            }

        with patch.object(self.store, "create_backup", side_effect=racing_backup):
            state = self.service.get_initial_state()

        self.assertEqual(state["capsuleIngestionV1"]["databaseStatus"], "unavailable")
        with self.store.read_connection() as connection:
            capsule = connection.execute(
                "SELECT status, current_version_id FROM capsules WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()
            event_count = connection.execute(
                "SELECT COUNT(*) FROM capsule_status_events WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()[0]
        self.assertEqual(tuple(capsule), ("active", version_id))
        self.assertEqual(event_count, 0)

    def test_v1_retirement_rejects_zero_to_one_race_before_backup(self) -> None:
        project_id = self._ready_project()
        inserted: list[tuple[str, str]] = []
        status_during_backup: list[str] = []

        def insert_v1_after_empty_preflight() -> str:
            if not inserted:
                inserted.append(
                    self._seed_project_contribution(
                        project_id,
                        extraction_summary={
                            "candidate_origin": "deterministic_computation_adapter",
                            "adapter_contract_version": "computation_adapter.v1",
                        },
                    )
                )
                with self.store.transaction() as connection:
                    self.store.bump_revision(connection)
            return "2026-07-19T00:00:00Z"

        def verified_backup(kind: str) -> dict[str, object]:
            capsule_id, _version_id = inserted[0]
            with self.store.read_connection() as connection:
                status_during_backup.append(
                    str(
                        connection.execute(
                            "SELECT status FROM capsules WHERE capsule_id = ?",
                            (capsule_id,),
                        ).fetchone()[0]
                    )
                )
            return {
                "path": str(self.state / "backups" / "zero-to-one.sqlite3"),
                "kind": kind,
                "sha256": "f" * 64,
                "warehouse_revision": self.store.current_revision(),
            }

        with (
            patch(
                "pimos_lite.reweave_app_service._now",
                side_effect=insert_v1_after_empty_preflight,
            ),
            patch.object(
                self.store, "create_backup", side_effect=verified_backup
            ) as backup,
        ):
            self.service.get_initial_state()

        backup.assert_called_once_with("upgrade")
        self.assertEqual(status_during_backup, ["active"])
        capsule_id, version_id = inserted[0]
        with self.store.read_connection() as connection:
            capsule = connection.execute(
                "SELECT status, current_version_id FROM capsules WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()
            event_count = connection.execute(
                "SELECT COUNT(*) FROM capsule_status_events WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()[0]
        self.assertEqual(tuple(capsule), ("pending_revalidation", version_id))
        self.assertEqual(event_count, 1)

    def test_v2_bundle_evidence_expiry_marks_only_active_current_adapter(self) -> None:
        project_id = self._ready_project()
        capsule_id, version_id = self._seed_project_contribution(
            project_id,
            extraction_summary={
                "candidate_origin": "deterministic_computation_adapter",
                "adapter_contract_version": "computation_adapter.v2",
                "ephemeral_capture_payload": {
                    "rule_versions": {
                        "selected_bundle_options_sha256": "0" * 64,
                        "execution_bundle_options_sha256": "1" * 64,
                    }
                },
            },
        )

        with patch.object(
            self.service._capsule_stage3,
            "_stored_version_evidence_eligible",
            return_value=False,
        ) as eligible:
            self.service.get_initial_state()

        eligible.assert_called_once()
        checked = eligible.call_args.args[0]
        self.assertEqual(checked["capsule_id"], capsule_id)
        self.assertEqual(checked["version_id"], version_id)
        self.assertEqual(checked["current_version_id"], version_id)
        with self.store.read_connection() as connection:
            capsule = connection.execute(
                "SELECT status, current_version_id FROM capsules WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()
            events = connection.execute(
                "SELECT event_type, version_id, reason_code FROM capsule_status_events "
                "WHERE capsule_id = ? ORDER BY created_at",
                (capsule_id,),
            ).fetchall()
        self.assertEqual(
            (capsule["status"], capsule["current_version_id"]),
            ("pending_revalidation", version_id),
        )
        self.assertEqual(
            [tuple(row) for row in events],
            [
                (
                    "revalidation_required",
                    version_id,
                    "adapter_evidence_version_changed",
                )
            ],
        )

    def test_v3_current_adapter_remains_active_when_evidence_is_current(self) -> None:
        project_id = self._ready_project()
        capsule_id, version_id = self._seed_project_contribution(
            project_id,
            extraction_summary={
                "candidate_origin": "deterministic_computation_adapter",
                "adapter_contract_version": "computation_adapter.v3",
            },
        )
        before = self.store.current_revision()

        with patch.object(
            self.service._capsule_stage3,
            "_stored_version_evidence_eligible",
            return_value=True,
        ) as eligible:
            self.service._ensure_capsule_management()

        eligible.assert_called_once()
        checked = eligible.call_args.args[0]
        self.assertEqual(checked["capsule_id"], capsule_id)
        self.assertEqual(checked["version_id"], version_id)
        with self.store.read_connection() as connection:
            capsule = connection.execute(
                "SELECT status, current_version_id FROM capsules WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()
            event_count = connection.execute(
                "SELECT COUNT(*) FROM capsule_status_events WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()[0]
        self.assertEqual(tuple(capsule), ("active", version_id))
        self.assertEqual(event_count, 0)
        self.assertEqual(self.store.current_revision(), before)

    def test_adapter_contract_rule_does_not_revalidate_ordinary_extraction(self) -> None:
        project_id = self._ready_project()
        capsule_id, version_id = self._seed_project_contribution(
            project_id,
            extraction_summary={
                "candidate_origin": "source_extraction",
                "extraction_contract_version": EXTRACTION_CONTRACT_VERSION,
            },
        )

        self.service.get_initial_state()

        with self.store.read_connection() as connection:
            capsule = connection.execute(
                "SELECT status, current_version_id FROM capsules WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()
            events = connection.execute(
                "SELECT count(*) FROM capsule_status_events WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()[0]
        self.assertEqual(
            (capsule["status"], capsule["current_version_id"]),
            ("active", version_id),
        )
        self.assertEqual(events, 0)

    def test_brand_review_rejects_asset_confirmation_decision(self) -> None:
        project_id = self._ready_project()
        now = "2026-07-15T00:00:00Z"
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO intake_runs (run_id, project_id, run_kind, status, "
                "extraction_contract_version, redaction_rules_version, security_rules_version, "
                "supervision_rules_version, validation_contract_version, canonicalization_version, "
                "counts_json, created_at) VALUES ('brand-run', ?, 'refresh_project', "
                "'completed_with_pending', 'extraction_contract.v1', 'redaction_rules.v1', "
                "'security_rules.v1', 'supervision_rules.v1', 'validation_contract.v1', "
                "1, '{}', ?)",
                (project_id, now),
            )
            connection.execute(
                "INSERT INTO review_items (review_id, run_id, project_id, candidate_id, "
                "candidate_status, source_relpath, source_location_json, source_hash, "
                "redaction_rules_version, sanitized_candidate_json, redaction_summary_json, "
                "created_at, updated_at) VALUES ('brand-review', 'brand-run', ?, "
                "'brand-candidate', 'waiting_user', 'index.html', '{}', ?, "
                "'redaction_rules.v1', '{}', ?, ?, ?)",
                (
                    project_id,
                    "a" * 64,
                    json.dumps(
                        {
                            "schema": "redaction_summary.v1",
                            "codes": ["brand_confirmation_required"],
                            "brand_count": 1,
                            "brand_profile_id": None,
                            "brand_profile_digest": None,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    now,
                    now,
                ),
            )

        result = self.service.decide_review_item(
            {
                "review_id": "brand-review",
                "decision": "confirm_assets_contain_no_real_records",
            }
        )

        self.assertEqual(result["error"]["code"], "review_decision_not_allowed")
        with self.store.read_connection() as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT asset_decision FROM review_items WHERE review_id = 'brand-review'"
                ).fetchone()[0]
            )

    def test_frozen_review_admission_routes_only_explicit_binding(self) -> None:
        request = {
            "source_database_path": str(self.root / "frozen.sqlite3"),
            "source_directory_path": str(self.root / "frozen-source"),
            "source_database_sha256": "a" * 64,
            "review_id": "review-frozen",
            "expected_warehouse_revision": 7,
            "plan_token": "plan-token",
            "plan_digest": "1" * 64,
            "projection_digest": "2" * 64,
            "authorize_decision_digest": "3" * 64,
            "source_proposal_authorization_digest": "4" * 64,
        }
        catalog = {"warehouse_revision": 7, "capsules": []}
        catalog_digest = hashlib.sha256(
            json.dumps(
                catalog,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        target_catalog_digest = hashlib.sha256(
            b'{"capsules":[]}'
        ).hexdigest()
        plan = {"canonical_digest": request["plan_digest"]}
        workspace = {"status": "plan_review", "plan": plan}
        projection = {
            "projection_digest": request["projection_digest"],
            "catalog_digest": catalog_digest,
            "warehouse_revision": 7,
        }
        decision = {
            "decision": "authorize",
            "canonical_digest": request["authorize_decision_digest"],
        }
        authorization = {
            "plan_digest": request["plan_digest"],
            "gap_id": "gap-test",
            "projection_digest": request["projection_digest"],
            "authorize_decision_digest": request[
                "authorize_decision_digest"
            ],
            "authorization_digest": request[
                "source_proposal_authorization_digest"
            ],
            "capability_key": "year_month_conversion",
            "adapter_contract_version": "computation_adapter.v2",
            "input_contract": {"input": True},
            "output_contract": {"output": True},
            "error_contract": {"error": True},
            "warehouse_revision": 7,
            "catalog_digest": catalog_digest,
        }
        binding = {
            "plan_digest": request["plan_digest"],
            "gap_id": "gap-test",
            "projection_digest": request["projection_digest"],
            "authorize_decision_digest": request[
                "authorize_decision_digest"
            ],
            "source_proposal_authorization_digest": request[
                "source_proposal_authorization_digest"
            ],
            "capability_key": "year_month_conversion",
            "adapter_contract_version": "computation_adapter.v2",
            "input_contract": {"input": True},
            "output_contract": {"output": True},
            "error_contract": {"error": True},
            "authorization_warehouse_revision": 7,
            "authorization_catalog_digest": catalog_digest,
            "target_catalog_digest": target_catalog_digest,
        }
        expected = {
            "review_id": "review-frozen",
            "status": "review_required",
            "canonical_hash": "b" * 64,
            "admission_digest": "c" * 64,
            "warehouse_revision": 8,
        }
        with patch.object(
            self.service,
            "_product_planning_catalog",
            return_value=catalog,
        ), patch.object(
            self.service._product_planner,
            "_catalog",
            return_value=catalog,
        ), patch.object(
            self.service._product_planner,
            "_workspace_by_token",
            return_value=workspace,
        ), patch.object(
            self.service._product_planner,
            "_read_capability_gap_projection",
            return_value=projection,
        ), patch.object(
            self.service._product_planner,
            "_capability_gap_projection_for_workspace",
            return_value=(projection, "available"),
        ) as project_for_workspace, patch.object(
            self.service._product_planner,
            "_capability_gap_projection",
            side_effect=AssertionError("legacy_projection_entry_called"),
        ) as legacy_projection, patch.object(
            self.service._product_planner,
            "_capability_gap_decisions",
            return_value=[decision],
        ), patch.object(
            self.service._product_planner,
            "_read_capability_source_proposal_authorization",
            return_value=authorization,
        ) as read_authorization, patch.object(
            self.service._capsule_stage3,
            "admit_frozen_review",
            return_value=expected,
        ) as admit:
            result = self.service.admit_frozen_review(request)
            tampered_results = {
                field: self.service.admit_frozen_review(
                    {**request, field: "f" * 64}
                )
                for field in (
                    "plan_digest",
                    "projection_digest",
                    "authorize_decision_digest",
                    "source_proposal_authorization_digest",
                )
            }
            read_authorization.return_value = {
                **authorization,
                "catalog_digest": "e" * 64,
            }
            catalog_tampered = self.service.admit_frozen_review(request)

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], expected)
        project_for_workspace.assert_any_call(workspace, plan, catalog)
        legacy_projection.assert_not_called()
        admit.assert_called_once_with(
            Path(request["source_database_path"]),
            Path(request["source_directory_path"]),
            "review-frozen",
            expected_source_sha256="a" * 64,
            expected_warehouse_revision=7,
            authorization_binding=binding,
        )
        invalid = self.service.admit_frozen_review({**request, "extra": True})
        self.assertEqual(
            invalid["error"]["code"], "frozen_review_admission_invalid"
        )
        for field, result in tampered_results.items():
            with self.subTest(field=field):
                self.assertFalse(result["ok"])
                self.assertIn(
                    result["error"]["code"],
                    {
                        "frozen_review_admission_authorization_invalid",
                        "frozen_review_admission_authorization_stale",
                    },
                )
        self.assertEqual(
            catalog_tampered["error"]["code"],
            "frozen_review_admission_authorization_invalid",
        )

    def test_frozen_review_admission_honors_workspace_gap_selection(self) -> None:
        request = {
            "source_database_path": str(self.root / "frozen.sqlite3"),
            "source_directory_path": str(self.root / "frozen-source"),
            "source_database_sha256": "a" * 64,
            "review_id": "review-frozen",
            "expected_warehouse_revision": 71,
            "plan_token": "plan-token",
            "plan_digest": "1" * 64,
            "projection_digest": "2" * 64,
            "authorize_decision_digest": "3" * 64,
            "source_proposal_authorization_digest": "4" * 64,
        }
        catalog = {"warehouse_revision": 71, "capsules": []}
        catalog_digest = hashlib.sha256(
            json.dumps(
                catalog,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        candidate_digest = "5" * 64
        selection_body = {
            "schema_version": "product_capability_gap_target_selection.v1",
            "question_set_digest": "6" * 64,
            "option_id": "option_selected",
            "candidate_digest": candidate_digest,
            "warehouse_revision": 71,
            "catalog_digest": catalog_digest,
            "user_answer_digest": "7" * 64,
        }
        selection = {
            **selection_body,
            "canonical_digest": hashlib.sha256(
                json.dumps(
                    selection_body,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
        }
        plan = {"canonical_digest": request["plan_digest"]}
        workspace = {
            "schema_version": "product_workspace.v8",
            "status": "plan_review",
            "plan": plan,
            "capability_gap_target_selection": selection,
        }
        projection = {
            "projection_digest": request["projection_digest"],
            "catalog_digest": catalog_digest,
            "warehouse_revision": 71,
        }
        decision = {
            "decision": "authorize",
            "canonical_digest": request["authorize_decision_digest"],
        }
        authorization = {
            "plan_digest": request["plan_digest"],
            "gap_id": "gap-test",
            "projection_digest": request["projection_digest"],
            "authorize_decision_digest": request[
                "authorize_decision_digest"
            ],
            "authorization_digest": request[
                "source_proposal_authorization_digest"
            ],
            "capability_key": "workflow_state_classification",
            "adapter_contract_version": "computation_adapter.v4",
            "input_contract": {"input": True},
            "output_contract": {"output": True},
            "error_contract": {"error": True},
            "warehouse_revision": 71,
            "catalog_digest": catalog_digest,
        }
        expected = {
            "review_id": "review-frozen",
            "status": "review_required",
            "canonical_hash": "b" * 64,
            "admission_digest": "c" * 64,
            "warehouse_revision": 72,
        }

        def recalculate(_plan, current_catalog, selected_digest=None):
            if (
                current_catalog["capsules"] == []
                and selected_digest in {None, candidate_digest}
            ):
                return projection, "available"
            return None, "capability_gap_boundary_ambiguous"

        with patch.object(
            self.service,
            "_product_planning_catalog",
            return_value=catalog,
        ), patch.object(
            self.service._product_planner,
            "_catalog",
            side_effect=lambda value: value,
        ), patch.object(
            self.service._product_planner,
            "_workspace_by_token",
            return_value=workspace,
        ), patch.object(
            self.service._product_planner,
            "_read_capability_gap_projection",
            return_value=projection,
        ), patch.object(
            self.service._product_planner,
            "_capability_gap_projection",
            side_effect=recalculate,
        ) as recalculate_projection, patch.object(
            self.service._product_planner,
            "_capability_gap_decisions",
            return_value=[decision],
        ), patch.object(
            self.service._product_planner,
            "_read_capability_source_proposal_authorization",
            return_value=authorization,
        ), patch.object(
            self.service._capsule_stage3,
            "admit_frozen_review",
            return_value=expected,
        ) as admit:
            selected = self.service.admit_frozen_review(request)
            self.assertTrue(selected["ok"])
            recalculate_projection.assert_called_with(
                plan,
                catalog,
                candidate_digest,
            )
            admit.assert_called_once()

            admit.reset_mock()
            wrong_body = {**selection_body, "candidate_digest": "8" * 64}
            workspace["capability_gap_target_selection"] = {
                **wrong_body,
                "canonical_digest": hashlib.sha256(
                    json.dumps(
                        wrong_body,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            }
            wrong = self.service.admit_frozen_review(request)
            self.assertEqual(
                wrong["error"]["code"],
                "frozen_review_admission_authorization_stale",
            )
            admit.assert_not_called()

            workspace["capability_gap_target_selection"] = {
                **selection,
                "canonical_digest": "9" * 64,
            }
            tampered = self.service.admit_frozen_review(request)
            self.assertFalse(tampered["ok"])
            admit.assert_not_called()

            workspace["capability_gap_target_selection"] = selection
            drifted_catalog = {
                "warehouse_revision": 71,
                "capsules": [{"drift": True}],
            }
            self.service._product_planning_catalog.return_value = (
                drifted_catalog
            )
            drifted = self.service.admit_frozen_review(request)
            self.assertEqual(
                drifted["error"]["code"],
                "frozen_review_admission_authorization_stale",
            )
            admit.assert_not_called()

            self.service._product_planning_catalog.return_value = catalog
            for schema_version in (
                "product_workspace.v8",
                "product_workspace.v7",
                "product_workspace.v6",
                "product_workspace.v5",
            ):
                workspace["schema_version"] = schema_version
                workspace["capability_gap_target_selection"] = None
                compatible = self.service.admit_frozen_review(request)
                self.assertTrue(compatible["ok"], schema_version)

            workspace["schema_version"] = "product_workspace.v8"
            workspace["capability_gap_target_selection"] = selection
            self.service._product_planning_catalog.return_value = {
                "warehouse_revision": 72,
                "capsules": [],
            }
            repeated = self.service.admit_frozen_review(
                {**request, "expected_warehouse_revision": 72}
            )
            self.assertTrue(repeated["ok"])

    def test_frozen_ui_review_batch_routes_and_locks_publication_identity(
        self,
    ) -> None:
        catalog = {"warehouse_revision": 7, "capsules": []}
        catalog_digest = hashlib.sha256(
            json.dumps(
                {"capsules": []},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        authorization = {
            "schema": "frozen_stage3_ui_review_admission_authorization.v1",
            "scope": "isolated_rehearsal",
            "source_database_sha256": "a" * 64,
            "source_project_id": "project-ui",
            "source_run_id": "run-ui",
            "source_file_index_digest": "b" * 64,
            "capability_key": "rectangle_area_calculation",
            "display_name": "Rectangle area",
            "page_capability_contract_digest": "c" * 64,
            "supervision_model_name": "test-model",
            "supervision_model_digest": "d" * 64,
            "target_warehouse_revision": 7,
            "target_catalog_digest": catalog_digest,
            "reviews": [
                {
                    "review_id": "review-interaction",
                    "capability_kind": "interaction",
                    "candidate_canonical_hash": "e" * 64,
                    "source_relpath": "interaction.js",
                    "source_file_sha256": "f" * 64,
                    "validation_sha256": "1" * 64,
                    "page_capability_declaration_digest": "2" * 64,
                },
                {
                    "review_id": "review-presentation",
                    "capability_kind": "presentation",
                    "candidate_canonical_hash": "3" * 64,
                    "source_relpath": "presentation.js",
                    "source_file_sha256": "4" * 64,
                    "validation_sha256": "5" * 64,
                    "page_capability_declaration_digest": "6" * 64,
                },
            ],
            "authorization_digest": "7" * 64,
        }
        request = {
            "source_database_path": str(self.root / "source.sqlite3"),
            "source_directory_path": str(self.root / "source"),
            "source_database_sha256": "a" * 64,
            "expected_warehouse_revision": 7,
            "authorization": authorization,
        }
        expected = {
            "status": "review_required",
            "review_ids": [
                "review-interaction",
                "review-presentation",
            ],
            "admission_digests": ["8" * 64, "9" * 64],
            "warehouse_revision": 9,
        }
        with patch.object(
            self.service,
            "_product_planning_catalog",
            return_value=catalog,
        ), patch.object(
            self.service._product_planner,
            "_catalog",
            return_value=catalog,
        ), patch.object(
            self.service._capsule_stage3,
            "admit_frozen_ui_review_batch",
            return_value=expected,
        ) as admit:
            admitted = self.service.admit_frozen_ui_review_batch(request)
        self.assertTrue(admitted["ok"])
        self.assertEqual(admitted["data"], expected)
        admit.assert_called_once_with(
            Path(request["source_database_path"]),
            Path(request["source_directory_path"]),
            expected_source_sha256="a" * 64,
            expected_warehouse_revision=7,
            authorization_binding=authorization,
        )
        self.assertEqual(
            self.service.admit_frozen_ui_review_batch(
                {**request, "extra": True}
            )["error"]["code"],
            "frozen_ui_review_admission_invalid",
        )

        receipt = {
            "schema": "frozen_stage3_ui_review_admission.v1",
            "authorized_capability_key": "rectangle_area_calculation",
            "authorized_display_name": "Rectangle area",
        }
        item = {
            "review_id": "review-interaction",
            "candidate_status": "review_required",
            "candidate": {"frozen_ui_review_admission": receipt},
            "comparison": {},
            "allowed_decisions": ["publish_general", "reject"],
        }
        self.assertEqual(
            self.service._allowed_review_decisions(item),
            ["publish_general", "reject"],
        )
        published = {
            "status": "published",
            "capsule_id": "capsule-ui",
            "version_id": "version-ui",
        }
        with patch.object(
            self.service,
            "list_review_items",
            return_value={"ok": True, "data": {"items": [item]}},
        ), patch.object(
            self.service._capsule_stage3,
            "publish_review",
            return_value=published,
        ) as publish:
            result = self.service.decide_review_item(
                {
                    "review_id": "review-interaction",
                    "decision": "publish_general",
                    "capability_key": "rectangle_area_calculation",
                    "display_name": "Rectangle area",
                    "role_key": "rectangle_dimensions_input",
                    "variant_key": "default",
                }
            )
            wrong_name = self.service.decide_review_item(
                {
                    "review_id": "review-interaction",
                    "decision": "publish_general",
                    "capability_key": "rectangle_area_calculation",
                    "display_name": "Wrong",
                    "role_key": "rectangle_dimensions_input",
                    "variant_key": "default",
                }
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], published)
        publish.assert_called_once()
        self.assertEqual(
            wrong_name["error"]["code"],
            "frozen_review_publication_identity_invalid",
        )
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO capability_groups VALUES (?,?,?,?)",
                (
                    "rectangle_area_calculation",
                    "Rectangle area",
                    "2026-08-11T00:00:00.000Z",
                    "2026-08-11T00:00:00.000Z",
                ),
            )
        presentation = {
            **item,
            "review_id": "review-presentation",
        }
        with patch.object(
            self.service,
            "list_review_items",
            return_value={
                "ok": True,
                "data": {"items": [presentation]},
            },
        ), patch.object(
            self.service._capsule_stage3,
            "publish_review",
            return_value=published,
        ) as publish_second:
            second = self.service.decide_review_item(
                {
                    "review_id": "review-presentation",
                    "decision": "publish_general",
                    "capability_key": "rectangle_area_calculation",
                    "display_name": "Rectangle area",
                    "role_key": "rectangle_area_result",
                    "variant_key": "default",
                }
            )
            wrong_key = self.service.decide_review_item(
                {
                    "review_id": "review-presentation",
                    "decision": "publish_general",
                    "capability_key": "other_area",
                    "display_name": "Rectangle area",
                    "role_key": "rectangle_area_result",
                    "variant_key": "default",
                }
            )
        self.assertTrue(second["ok"])
        publish_second.assert_called_once()
        self.assertEqual(
            wrong_key["error"]["code"],
            "frozen_review_publication_identity_invalid",
        )

    def test_default_review_queue_excludes_history_but_explicit_status_keeps_it(self) -> None:
        project_id = self._ready_project()
        now = "2026-07-15T00:00:00Z"
        statuses = (
            "extracted",
            "waiting_user",
            "waiting_model",
            "waiting_validation",
            "review_required",
            "duplicate",
            "publishable",
            "published",
            "merged",
            "rejected",
        )
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO intake_runs (run_id, project_id, run_kind, status, "
                "extraction_contract_version, redaction_rules_version, security_rules_version, "
                "supervision_rules_version, validation_contract_version, canonicalization_version, "
                "counts_json, created_at) VALUES ('queue-run', ?, 'refresh_project', "
                "'completed_with_pending', 'extraction_contract.v1', 'redaction_rules.v1', "
                "'security_rules.v1', 'supervision_rules.v1', 'validation_contract.v1', "
                "1, '{}', ?)",
                (project_id, now),
            )
            for index, status in enumerate(statuses):
                candidate = (
                    {"usage_scope": {"kind": "general"}}
                    if status == "review_required"
                    else {}
                )
                connection.execute(
                    "INSERT INTO review_items (review_id, run_id, project_id, candidate_id, "
                    "candidate_status, source_relpath, source_location_json, source_hash, "
                    "redaction_rules_version, sanitized_candidate_json, redaction_summary_json, "
                    "created_at, updated_at) VALUES (?, 'queue-run', ?, ?, ?, 'index.html', "
                    "'{}', ?, 'redaction_rules.v1', ?, '{}', ?, ?)",
                    (
                        f"review-{status}",
                        project_id,
                        f"candidate-{index}",
                        status,
                        hashlib.sha256(status.encode()).hexdigest(),
                        json.dumps(candidate, separators=(",", ":")),
                        now,
                        now,
                    ),
                )

        default = self.service.list_review_items({})
        explicit = self.service.list_review_items({"status": "published"})

        self.assertTrue(default["ok"])
        self.assertEqual(
            {item["candidate_status"] for item in default["data"]["items"]},
            {
                "extracted",
                "waiting_user",
                "waiting_model",
                "waiting_validation",
                "review_required",
                "duplicate",
            },
        )
        self.assertTrue(
            all(item["allowed_decisions"] for item in default["data"]["items"])
        )
        self.assertEqual(
            [item["candidate_status"] for item in explicit["data"]["items"]],
            ["published"],
        )

    def test_waiting_candidate_retry_creates_refresh_without_rewriting_old_review(self) -> None:
        self.store.initialize()
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO source_roots VALUES "
                "('root', 'single_project', ?, 'bound', NULL, NULL, NULL, 0, ?, ?)",
                (str(self.root), "2026-07-15T00:00:00Z", "2026-07-15T00:00:00Z"),
            )
            connection.execute(
                "INSERT INTO projects VALUES "
                "('project', 'root', '.', 'index.html', 'Project', 'ready', 'sig', "
                "'old_snapshot', 'inherit', NULL, NULL, NULL, 0, ?, ?)",
                ("2026-07-15T00:00:00Z", "2026-07-15T00:00:00Z"),
            )
            connection.execute(
                "INSERT INTO intake_runs (run_id, project_id, run_kind, status, "
                "extraction_contract_version, redaction_rules_version, security_rules_version, "
                "supervision_rules_version, validation_contract_version, canonicalization_version, "
                "counts_json, created_at) VALUES "
                "('old_run', 'project', 'refresh_project', 'completed_with_pending', "
                "'extraction_contract.v1', 'redaction_rules.v1', 'security_rules.v1', "
                "'supervision_rules.v1', 'validation_contract.v1', 1, '{}', ?)",
                ("2026-07-15T00:00:00Z",),
            )
            connection.execute(
                "INSERT INTO review_items "
                "(review_id, run_id, project_id, candidate_id, candidate_status, source_relpath, "
                "source_location_json, source_hash, redaction_rules_version, "
                "sanitized_candidate_json, redaction_summary_json, created_at, updated_at) "
                "VALUES ('review', 'old_run', 'project', 'candidate', 'waiting_model', "
                "'index.html', '{}', ?, 'redaction_rules.v1', '{}', '{}', ?, ?)",
                ("a" * 64, "2026-07-15T00:00:00Z", "2026-07-15T00:00:00Z"),
            )

        with patch.object(
            self.service,
            "_refresh_project",
            return_value={"intake": {"run_id": "new_run"}, "gate_results": []},
        ) as refresh:
            started = self.service.decide_review_item(
                {"review_id": "review", "decision": "process_candidate"}
            )
            self.assertEqual(self._wait(started["run_id"])["status"], "completed")
        refresh.assert_called_once()
        self.assertEqual(refresh.call_args.args[0], "project")
        with self.store.read_connection() as connection:
            review_status = connection.execute(
                "SELECT candidate_status FROM review_items WHERE review_id = 'review'"
            ).fetchone()[0]
            snapshot = connection.execute(
                "SELECT last_snapshot_hash FROM projects WHERE project_id = 'project'"
            ).fetchone()[0]
        self.assertEqual(review_status, "waiting_model")
        self.assertIsNone(snapshot)


if __name__ == "__main__":
    unittest.main()
