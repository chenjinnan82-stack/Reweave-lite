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
from pimos_lite.reweave_capsule_intake import (
    COMPUTATION_ADAPTER_CONTRACT_VERSION,
    EXTRACTION_CONTRACT_VERSION,
)
from pimos_lite.reweave_capsule_store import CapsuleWarehouseStore
from pimos_lite.reweave_engine.local import LocalReweaveEngine


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
        for _ in range(300):
            result = self.service.get_intake_run({"run_id": run_id})
            self.assertTrue(result["ok"])
            task = result["data"]
            if task["status"] in {"completed", "failed", "cancelled"}:
                return task
            time.sleep(0.01)
        self.fail("management task did not finish")

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

    def _seed_project_contribution(
        self,
        project_id: str,
        *,
        extraction_version: str = EXTRACTION_CONTRACT_VERSION,
        extraction_summary: dict[str, object] | None = None,
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
            "input_contract_json": "{}",
            "output_contract_json": "{}",
            "error_contract_json": "{}",
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
