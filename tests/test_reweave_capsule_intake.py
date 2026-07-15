"""Stage 2 tests for non-active source discovery and candidate intake."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_capsule_intake import (
    IntakeError,
    ReweaveCapsuleIntake,
)
from pimos_lite.reweave_capsule_store import CapsuleWarehouseStore
from pimos_lite.reweave_data_contract import (
    DataContractError,
    canonical_decimal,
    contracts_compatible,
    data_contract_accepts,
    generate_synthetic_fixtures,
    normalize_capsule_contracts,
    normalize_data_contract,
)


def object_contract(properties: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": properties,
        "required": sorted(properties),
        "additional_properties": False,
    }


class DataContractV1Test(unittest.TestCase):
    def test_normalization_decimal_limits_and_forbidden_keywords(self) -> None:
        contract = normalize_data_contract(
            {
                "schema": "data_contract.v1",
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "decimal",
                        "minimum": "0.00",
                        "maximum": "12.80",
                        "max_scale": 2,
                        "enum": ["12.80", "0.00", "12.8"],
                    },
                    "items": {
                        "type": "array",
                        "items": {"type": "boolean"},
                        "max_items": 3,
                    },
                },
                "required": ["amount"],
                "additional_properties": False,
            }
        )
        self.assertEqual(contract["properties"]["amount"]["minimum"], "0")
        self.assertEqual(contract["properties"]["amount"]["maximum"], "12.8")
        self.assertEqual(contract["properties"]["amount"]["enum"], ["0", "12.8"])
        self.assertEqual(canonical_decimal("0.00"), "0")
        self.assertEqual(canonical_decimal("12.80"), "12.8")

        with self.assertRaisesRegex(DataContractError, "data_contract_keyword_forbidden"):
            normalize_data_contract(
                {
                    "schema": "data_contract.v1",
                    "type": "string",
                    "min_length": 0,
                    "max_length": 10,
                    "pattern": ".*",
                }
            )
        with self.assertRaisesRegex(DataContractError, "additional_properties_must_be_false"):
            normalize_data_contract(
                {
                    "schema": "data_contract.v1",
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additional_properties": True,
                }
            )
        with self.assertRaisesRegex(DataContractError, "integer_minimum_invalid"):
            normalize_data_contract(
                {
                    "schema": "data_contract.v1",
                    "type": "integer",
                    "minimum": 0.0,
                    "maximum": 1,
                }
            )

    def test_compatibility_is_conservative(self) -> None:
        source = object_contract(
            {"quantity": {"type": "integer", "minimum": 1, "maximum": 10}}
        )
        wider_target = object_contract(
            {"quantity": {"type": "integer", "minimum": 0, "maximum": 100}}
        )
        narrower_target = object_contract(
            {"quantity": {"type": "integer", "minimum": 5, "maximum": 8}}
        )
        extra_source = object_contract(
            {
                "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
                "unknown": {"type": "boolean"},
            }
        )
        self.assertTrue(contracts_compatible(source, wider_target))
        self.assertFalse(contracts_compatible(source, narrower_target))
        self.assertFalse(contracts_compatible(extra_source, wider_target))

    def test_synthetic_fixtures_are_generated_from_contract_only(self) -> None:
        contract = object_contract(
            {
                "name": {"type": "string", "min_length": 1, "max_length": 8},
                "quantity": {"type": "integer", "minimum": 1, "maximum": 3},
            }
        )
        fixtures = generate_synthetic_fixtures(contract)
        self.assertEqual(fixtures["schema"], "synthetic_fixtures.v1")
        self.assertTrue(all(data_contract_accepts(contract, value) for value in fixtures["normal"]))
        self.assertTrue(all(data_contract_accepts(contract, value) for value in fixtures["boundary"]))
        self.assertTrue(
            all(
                not data_contract_accepts(contract, row["value"])
                for row in fixtures["invalid"]
            )
        )
        self.assertNotIn("source", json.dumps(fixtures))

    def test_integer_fixtures_cover_javascript_safe_range_rejection(self) -> None:
        safe_limit = 9_007_199_254_740_991
        contract = object_contract(
            {
                "value": {
                    "type": "integer",
                    "minimum": -safe_limit,
                    "maximum": safe_limit,
                }
            }
        )

        fixtures = generate_synthetic_fixtures(contract)

        invalid = {row["reason"].split(":", 1)[0]: row["value"] for row in fixtures["invalid"]}
        self.assertEqual(invalid["integer_below"]["value"], -(safe_limit + 1))
        self.assertEqual(invalid["integer_above"]["value"], safe_limit + 1)
        self.assertFalse(data_contract_accepts(contract, invalid["integer_below"]))
        self.assertFalse(data_contract_accepts(contract, invalid["integer_above"]))

    def test_array_fixtures_cover_items_and_wide_contract_families(self) -> None:
        array_contract = object_contract(
            {
                "values": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1, "maximum": 3},
                    "min_items": 1,
                    "max_items": 2,
                }
            }
        )
        array_fixtures = generate_synthetic_fixtures(array_contract)
        reasons = {row["reason"].split(":", 1)[0] for row in array_fixtures["invalid"]}
        self.assertTrue(
            {
                "array_too_short",
                "array_too_long",
                "integer_below",
                "integer_above",
                "wrong_type",
            }.issubset(reasons)
        )
        self.assertTrue(
            all(data_contract_accepts(array_contract, value) for value in array_fixtures["boundary"])
        )
        self.assertTrue(
            any(3 in value["values"] for value in array_fixtures["boundary"])
        )
        self.assertTrue(
            all(
                not data_contract_accepts(array_contract, row["value"])
                for row in array_fixtures["invalid"]
            )
        )

        wide_contract = object_contract(
            {
                f"field_{index:03d}": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3,
                }
                for index in range(70)
            }
        )
        wide_invalid = generate_synthetic_fixtures(wide_contract)["invalid"]
        self.assertLessEqual(len(wide_invalid), 64)
        wide_reasons = {
            row["reason"].split(":", 1)[0]
            for row in wide_invalid
        }
        self.assertTrue(
            {
                "missing_required",
                "additional_property",
                "integer_below",
                "integer_above",
                "wrong_type",
            }.issubset(wide_reasons)
        )

    def test_capsule_wrappers_are_closed(self) -> None:
        input_contract = object_contract({})
        event_contract = {
            "schema": "event_outputs.v1",
            "events": {"submitted": object_contract({"ok": {"type": "boolean"}})},
        }
        errors = {"schema": "error_contract.v1", "errors": {}}
        normalized = normalize_capsule_contracts(
            "interaction", input_contract, event_contract, errors
        )
        self.assertEqual(normalized[1]["schema"], "event_outputs.v1")
        with self.assertRaisesRegex(DataContractError, "presentation_output_contract_invalid"):
            normalize_capsule_contracts(
                "presentation", input_contract, object_contract({}), errors
            )

    def test_member_names_and_string_enums_require_stable_utf8(self) -> None:
        for name in ("name\r", "name\n", "name\x7f", "\ud800"):
            contract = object_contract({name: {"type": "boolean"}})
            with self.subTest(name=repr(name)), self.assertRaisesRegex(
                DataContractError, "object_properties_invalid"
            ):
                normalize_data_contract(contract)

        contract = {
            "schema": "data_contract.v1",
            "type": "string",
            "min_length": 0,
            "max_length": 2,
            "enum": ["\ud800"],
        }
        with self.assertRaisesRegex(DataContractError, "string_enum_value_invalid"):
            normalize_data_contract(contract)
        self.assertFalse(
            data_contract_accepts(
                {
                    "schema": "data_contract.v1",
                    "type": "string",
                    "min_length": 1,
                    "max_length": 1,
                },
                "\ud800",
            )
        )

        input_contract = object_contract({})
        errors = {"schema": "error_contract.v1", "errors": {}}
        with self.assertRaisesRegex(DataContractError, "event_outputs_contract_invalid"):
            normalize_capsule_contracts(
                "interaction",
                input_contract,
                {"schema": "event_outputs.v1", "events": {"sent\n": object_contract({})}},
                errors,
            )


@unittest.skipUnless(shutil.which("node"), "Node is required for TypeScript AST extraction")
class CapsuleIntakeStage2Test(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.state = self.root / "state"
        self.source = self.root / "source"
        self.source.mkdir()
        self._env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self.state)})
        self._env.start()
        self.store = CapsuleWarehouseStore(self.state / "capsule_warehouse.sqlite3")
        self.intake = ReweaveCapsuleIntake(self.store)

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def test_three_atomic_roles_extract_and_second_run_is_no_change(self) -> None:
        self._write_complete_project(self.source)
        project = self._bind_discover_confirm(self.source)

        first = self.intake.run_intake(project["project_id"])

        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["counts"]["extracted"], 3)
        rows = self._review_rows(first["run_id"])
        self.assertEqual(len(rows), 3)
        by_kind = {
            json.loads(row["sanitized_candidate_json"])["capability_kind"]: json.loads(
                row["sanitized_candidate_json"]
            )
            for row in rows
        }
        self.assertEqual(set(by_kind), {"presentation", "interaction", "computation"})
        self.assertEqual(
            by_kind["computation"]["output_contract"]["properties"]["total"],
            {"type": "integer", "minimum": 0, "maximum": 10000},
        )
        self.assertEqual(
            [item["path"] for item in by_kind["computation"]["module_evidence"]],
            ["compute.js", "math.js"],
        )
        self.assertEqual(
            by_kind["interaction"]["output_contract"]["events"]["calculate_requested"]
            ["properties"]["quantity"],
            {"type": "integer", "minimum": 1, "maximum": 10},
        )
        self.assertIn("static_call", by_kind["computation"]["dependency_edge_types"])
        self.assertNotIn("export function", json.dumps(by_kind))

        os.utime(self.source / "compute.js", None)
        second = self.intake.run_intake(project["project_id"])
        self.assertEqual(second["status"], "no_change")
        self.assertEqual(second["review_ids"], [])
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM capsules").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM capsule_versions").fetchone()[0], 0)

    def test_snapshot_and_javascript_total_byte_limits_fail_before_node(self) -> None:
        self._write_complete_project(self.source)
        project = self._bind_discover_confirm(self.source)

        with patch(
            "pimos_lite.reweave_capsule_intake.MAX_SUPPORTED_BYTES", 32
        ), self.assertRaisesRegex(IntakeError, "source_total_size_exceeded"):
            self.intake.run_intake(project["project_id"])

        with patch(
            "pimos_lite.reweave_capsule_intake.MAX_JAVASCRIPT_SNAPSHOT_BYTES", 32
        ), patch("pimos_lite.reweave_capsule_intake.subprocess.run") as node_run:
            with self.assertRaisesRegex(IntakeError, "javascript_snapshot_size_exceeded"):
                self.intake.run_intake(project["project_id"])
            node_run.assert_not_called()

        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM review_items").fetchone()[0], 0)

    def test_parent_snapshot_blocks_unconfirmed_child_then_excludes_it(self) -> None:
        (self.source / "index.html").write_text("<main>Parent</main>", encoding="utf-8")
        child = self.source / "child"
        child.mkdir()
        (child / "index.html").write_text("<main>Child</main>", encoding="utf-8")
        source_root = self.intake.bind_source_root(
            self.source, root_kind="project_collection"
        )
        projects = self.intake.discover_projects(source_root["root_id"])
        parent = next(row for row in projects if row["project_relpath"] == ".")
        child_project = next(row for row in projects if row["project_relpath"] == "child")
        self.intake.confirm_project(parent["project_id"])

        with self.assertRaisesRegex(IntakeError, "discovered_unconfirmed"):
            self.intake.snapshot_project(parent["project_id"])

        self.intake.confirm_project(child_project["project_id"])
        before = self.intake.snapshot_project(parent["project_id"])
        (child / "index.html").write_text("<main>Changed child</main>", encoding="utf-8")
        after = self.intake.snapshot_project(parent["project_id"])
        self.assertEqual(before.digest, after.digest)
        self.assertEqual([item.path for item in after.entries], ["index.html"])

    def test_project_discovery_fails_instead_of_truncating_at_depth_limit(self) -> None:
        nested = self.source
        for index in range(9):
            nested = nested / f"level-{index}"
            nested.mkdir()
        (nested / "index.html").write_text("<main>Too deep</main>", encoding="utf-8")
        source_root = self.intake.bind_source_root(
            self.source, root_kind="project_collection"
        )

        with self.assertRaisesRegex(IntakeError, "source_limit_exceeded"):
            self.intake.discover_projects(source_root["root_id"])

    def test_project_uuid_survives_confirmed_root_reconnect(self) -> None:
        self._write_complete_project(self.source)
        source_root = self.intake.bind_source_root(self.source, root_kind="single_project")
        project = self.intake.discover_projects(source_root["root_id"])[0]
        uuid.UUID(project["project_id"])
        moved = self.root / "moved-source"
        self.source.rename(moved)
        updated_root = self.intake.reconnect_source_root(source_root["root_id"], moved)
        rediscovered = self.intake.discover_projects(source_root["root_id"])[0]

        self.assertEqual(updated_root["root_id"], source_root["root_id"])
        self.assertEqual(rediscovered["project_id"], project["project_id"])
        with self.assertRaisesRegex(IntakeError, "source_root_already_bound"):
            self.intake.bind_source_root(moved, root_kind="single_project")

    def test_reconnect_reuses_binding_path_guards(self) -> None:
        first = self.source / "first"
        second = self.source / "second"
        first.mkdir()
        second.mkdir()
        first_root = self.intake.bind_source_root(first, root_kind="single_project")
        self.intake.bind_source_root(second, root_kind="single_project")

        with self.assertRaisesRegex(IntakeError, "source_root_already_bound"):
            self.intake.reconnect_source_root(first_root["root_id"], second)
        with self.assertRaisesRegex(IntakeError, "reweave_state_dir_inside_source_root"):
            self.intake.reconnect_source_root(first_root["root_id"], self.root)

    def test_source_roots_reject_actual_store_path_and_physical_overlap(self) -> None:
        nested = self.source / "nested"
        nested.mkdir()
        store_in_source = CapsuleWarehouseStore(self.source / "private" / "warehouse.sqlite3")
        intake = ReweaveCapsuleIntake(store_in_source)

        with self.assertRaisesRegex(IntakeError, "reweave_store_inside_source_root"):
            intake.bind_source_root(self.source, root_kind="single_project")
        self.assertFalse(store_in_source.path.exists())

        self.intake.bind_source_root(self.source, root_kind="project_collection")
        with self.assertRaisesRegex(IntakeError, "source_root_overlap"):
            self.intake.bind_source_root(nested, root_kind="single_project")

    def test_discovery_is_atomic_marks_missing_and_requires_reconfirmation(self) -> None:
        (self.source / "index.html").write_text("<main>Parent</main>", encoding="utf-8")
        child = self.source / "child"
        child.mkdir()
        (child / "index.html").write_text("<main>Child</main>", encoding="utf-8")
        source_root = self.intake.bind_source_root(
            self.source, root_kind="project_collection"
        )
        before_revision = self.store.current_revision()
        with patch.object(self.store, "bump_revision", side_effect=RuntimeError("probe")):
            with self.assertRaisesRegex(RuntimeError, "probe"):
                self.intake.discover_projects(source_root["root_id"])
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM projects").fetchone()[0], 0)
        self.assertEqual(self.store.current_revision(), before_revision)

        projects = self.intake.discover_projects(source_root["root_id"])
        self.assertEqual(self.store.current_revision(), before_revision + 1)
        child_project = next(row for row in projects if row["project_relpath"] == "child")
        self.intake.confirm_project(child_project["project_id"])
        shutil.rmtree(child)
        self.intake.discover_projects(source_root["root_id"])
        self.assertEqual(
            self.intake.get_project(child_project["project_id"])["project_state"],
            "source_missing",
        )
        child.mkdir()
        (child / "index.html").write_text("<main>Child</main>", encoding="utf-8")
        self.intake.discover_projects(source_root["root_id"])
        self.assertEqual(
            self.intake.get_project(child_project["project_id"])["project_state"],
            "source_missing",
        )
        self.assertEqual(
            self.intake.confirm_project(child_project["project_id"])["project_state"],
            "ready",
        )

    def test_explicit_project_reconnect_preserves_id_and_absorbs_empty_discovery(self) -> None:
        original = self.source / "original"
        original.mkdir()
        self._write_complete_project(original)
        source_root = self.intake.bind_source_root(
            self.source, root_kind="project_collection"
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        moved = self.source / "moved"
        original.rename(moved)

        rediscovered = self.intake.discover_projects(source_root["root_id"])
        temporary = next(row for row in rediscovered if row["project_relpath"] == "moved")
        self.assertNotEqual(temporary["project_id"], project["project_id"])
        restored = self.intake.reconnect_project(
            project["project_id"], project_relpath="moved", entry_relpath="index.html"
        )

        self.assertEqual(restored["project_id"], project["project_id"])
        self.assertEqual(restored["project_state"], "ready")
        with self.store.read_connection() as connection:
            rows = connection.execute(
                "SELECT project_id FROM projects WHERE source_root_id = ?",
                (source_root["root_id"],),
            ).fetchall()
        self.assertEqual([row[0] for row in rows], [project["project_id"]])

    def test_missing_source_transitions_and_can_be_confirmed_after_reconnect(self) -> None:
        self._write_complete_project(self.source)
        source_root = self.intake.bind_source_root(
            self.source, root_kind="single_project"
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        moved = self.root / "restored-source"
        self.source.rename(moved)

        with self.assertRaisesRegex(IntakeError, "source_root_missing"):
            self.intake.snapshot_project(project["project_id"])
        self.assertEqual(
            self.intake.get_source_root(source_root["root_id"])["status"],
            "source_missing",
        )
        self.assertEqual(
            self.intake.get_project(project["project_id"])["project_state"],
            "source_missing",
        )

        self.intake.reconnect_source_root(source_root["root_id"], moved)
        restored = self.intake.confirm_project(project["project_id"])
        self.assertEqual(restored["project_state"], "ready")

    def test_sensitive_decision_is_bound_to_source_hash(self) -> None:
        self._write_complete_project(self.source)
        compute_path = self.source / "compute.js"
        compute_path.write_text(
            compute_path.read_text(encoding="utf-8").replace(
                "export function compute(input) {",
                'export function compute(input) {\n  const customer = "alice\\x40example.com";',
            ).replace(
                "{total: multiply(input.unit_price, input.quantity)}",
                "{total: multiply(input.unit_price, input.quantity), customer}",
            ),
            encoding="utf-8",
        )
        project = self._bind_discover_confirm(self.source)
        first = self.intake.run_intake(project["project_id"])
        waiting = [row for row in self._review_rows(first["run_id"]) if row["candidate_status"] == "waiting_user"]
        self.assertEqual(len(waiting), 1)
        persisted = json.dumps(dict(waiting[0]), ensure_ascii=False)
        self.assertNotIn("alice@example.com", persisted)
        self.assertNotIn("alice\\x40example.com", persisted)
        self.assertNotIn("const customer", persisted)
        self.assertNotIn(b"alice@example.com", self.store.path.read_bytes())
        self.assertNotIn(b"alice\\x40example.com", self.store.path.read_bytes())

        self.intake.record_review_decisions(
            waiting[0]["review_id"], sensitivity_decision="confirm_safe_redaction"
        )
        second = self.intake.run_intake(project["project_id"])
        self.assertEqual(second["status"], "completed")
        self.assertEqual(second["counts"]["waiting_user"], 0)
        compute_path.write_text(
            compute_path.read_text(encoding="utf-8").replace(
                "alice\\x40example.com", "bob\\x40example.com"
            ),
            encoding="utf-8",
        )
        third = self.intake.run_intake(project["project_id"])
        self.assertEqual(third["counts"]["waiting_user"], 1)
        newest = next(
            row
            for row in self._review_rows(third["run_id"])
            if row["candidate_status"] == "waiting_user"
        )
        self.assertIsNone(newest["sensitivity_decision"])

    def test_real_record_rejection_dominates_same_binding_decisions(self) -> None:
        self._write_complete_project(self.source)
        compute_path = self.source / "compute.js"
        compute_path.write_text(
            compute_path.read_text(encoding="utf-8").replace(
                "export function compute(input) {",
                'export function compute(input) {\n  const customer = "alice\\x40example.com";',
            ).replace(
                "{total: multiply(input.unit_price, input.quantity)}",
                "{total: multiply(input.unit_price, input.quantity), customer}",
            ),
            encoding="utf-8",
        )
        project = self._bind_discover_confirm(self.source)
        first = self.intake.run_intake(project["project_id"])
        original = next(
            row
            for row in self._review_rows(first["run_id"])
            if row["candidate_status"] == "waiting_user"
        )
        columns = list(original.keys())
        placeholders = ", ".join("?" for _ in columns)
        with self.store.transaction() as connection:
            for suffix in ("real", "conflict"):
                values = dict(original)
                values["review_id"] = f"review-{suffix}"
                values["candidate_id"] = f"candidate-{suffix}"
                connection.execute(
                    f"INSERT INTO review_items ({', '.join(columns)}) VALUES ({placeholders})",
                    [values[column] for column in columns],
                )

        self.intake.record_review_decisions(
            original["review_id"], sensitivity_decision="confirm_fictional_fixture"
        )
        self.intake.record_review_decisions(
            "review-real", sensitivity_decision="confirm_real_record_reject"
        )
        with self.assertRaisesRegex(IntakeError, "sensitivity_decision_conflict"):
            self.intake.record_review_decisions(
                "review-conflict", sensitivity_decision="confirm_safe_redaction"
            )

        second = self.intake.run_intake(project["project_id"])
        rejected = next(
            row
            for row in self._review_rows(second["run_id"])
            if row["candidate_status"] == "rejected"
        )
        self.assertIn("confirmed_real_record_rejected", rejected["redaction_summary_json"])

    def test_sensitive_contract_identifier_never_enters_review_storage(self) -> None:
        self._write_complete_project(self.source)
        compute = self.source / "compute.js"
        compute.write_text(
            compute.read_text(encoding="utf-8").replace(
                "{total: multiply(input.unit_price, input.quantity)}",
                '{"alice@example.com": multiply(input.unit_price, input.quantity)}',
            ),
            encoding="utf-8",
        )
        project = self._bind_discover_confirm(self.source)

        first = self.intake.run_intake(project["project_id"])
        waiting = next(
            row
            for row in self._review_rows(first["run_id"])
            if row["candidate_status"] == "waiting_user"
        )
        summary = json.loads(waiting["sanitized_candidate_json"])
        self.assertTrue(summary["requires_reextract"])
        self.assertNotIn("input_contract", summary)
        self.assertNotIn(b"alice@example.com", self.store.path.read_bytes())

        self.intake.record_review_decisions(
            waiting["review_id"], sensitivity_decision="confirm_fictional_fixture"
        )
        second = self.intake.run_intake(project["project_id"])
        rejected = next(
            row
            for row in self._review_rows(second["run_id"])
            if row["candidate_status"] == "rejected"
            and "sensitive_contract_identifier_unsupported"
            in row["redaction_summary_json"]
        )
        self.assertTrue(json.loads(rejected["sanitized_candidate_json"])["requires_reextract"])
        self.assertNotIn(b"alice@example.com", self.store.path.read_bytes())

    def test_css_change_invalidates_sensitive_decision_binding(self) -> None:
        self._write_complete_project(self.source)
        html = self.source / "index.html"
        html.write_text(
            html.read_text(encoding="utf-8").replace(
                "</head>", "</head>"
            ).replace(
                "<html><body>", '<html><head><link rel="stylesheet" href="./styles.css"></head><body>'
            ),
            encoding="utf-8",
        )
        styles = self.source / "styles.css"
        styles.write_text('/* alice@example.com */\n', encoding="utf-8")
        project = self._bind_discover_confirm(self.source)
        first = self.intake.run_intake(project["project_id"])
        waiting = next(
            row
            for row in self._review_rows(first["run_id"])
            if row["candidate_status"] == "waiting_user"
        )
        self.intake.record_review_decisions(
            waiting["review_id"], sensitivity_decision="confirm_safe_redaction"
        )

        styles.write_text('/* bob@example.com */\n', encoding="utf-8")
        second = self.intake.run_intake(project["project_id"])

        newest = next(
            row
            for row in self._review_rows(second["run_id"])
            if row["candidate_status"] == "waiting_user"
        )
        self.assertIsNone(newest["sensitivity_decision"])
        candidate = json.loads(newest["sanitized_candidate_json"])
        self.assertNotEqual(newest["source_hash"], waiting["source_hash"])
        self.assertTrue(candidate["requires_reextract"])
        self.assertNotIn("static_evidence", candidate)
        self.assertNotIn("bob@example.com", self.store.path.read_text("latin-1"))

    def test_confirm_rejects_resource_outside_static_web_v1(self) -> None:
        self._write_complete_project(self.source)
        html = self.source / "index.html"
        html.write_text(
            html.read_text(encoding="utf-8").replace(
                "</main>", '<video src="./clip.mp4"></video></main>'
            ),
            encoding="utf-8",
        )
        (self.source / "clip.mp4").write_bytes(b"not-a-v1-asset")
        source_root = self.intake.bind_source_root(
            self.source, root_kind="single_project"
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]

        with self.assertRaisesRegex(
            IntakeError, "static_closure_resource_unsupported_v1"
        ):
            self.intake.confirm_project(project["project_id"])
        self.assertEqual(
            self.intake.get_project(project["project_id"])["project_state"],
            "unsupported_v1",
        )

    def test_confirm_rejects_symlink_in_static_closure(self) -> None:
        self._write_complete_project(self.source)
        assets = self.source / "assets"
        assets.mkdir()
        (assets / "pixel.png").write_bytes(b"not-decoded-in-stage2")
        (self.source / "alias").symlink_to(assets, target_is_directory=True)
        html = self.source / "index.html"
        html.write_text(
            html.read_text(encoding="utf-8").replace(
                "</main>", '<img src="./alias/pixel.png"></main>'
            ),
            encoding="utf-8",
        )
        source_root = self.intake.bind_source_root(
            self.source, root_kind="single_project"
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]

        with self.assertRaisesRegex(IntakeError, "static_closure_symlink_forbidden"):
            self.intake.confirm_project(project["project_id"])

    def test_project_reconnect_rejects_intermediate_symlink_components(self) -> None:
        original = self.source / "original"
        target = self.source / "target" / "nested"
        original.mkdir()
        target.mkdir(parents=True)
        (original / "index.html").write_text("<main>Original</main>", encoding="utf-8")
        (target / "index.html").write_text("<main>Target</main>", encoding="utf-8")
        (self.source / "alias").symlink_to(self.source / "target", target_is_directory=True)
        source_root = self.intake.bind_source_root(
            self.source, root_kind="project_collection"
        )
        projects = self.intake.discover_projects(source_root["root_id"])
        project = next(row for row in projects if row["project_relpath"] == "original")
        self.intake.confirm_project(project["project_id"])

        with self.assertRaisesRegex(IntakeError, "static_closure_symlink_forbidden"):
            self.intake.reconnect_project(
                project["project_id"],
                project_relpath="alias/nested",
                entry_relpath="index.html",
            )
        self.assertEqual(
            self.intake.get_project(project["project_id"])["project_relpath"], "original"
        )

    def test_brand_retention_requires_bound_profile_and_produces_limited_scope(self) -> None:
        self._write_complete_project(self.source)
        compute = self.source / "compute.js"
        compute.write_text(
            compute.read_text(encoding="utf-8").replace(
                "export function compute(input) {",
                'export function compute(input) {\n  const label = "H" + "P";',
            ).replace(
                "{total: multiply(input.unit_price, input.quantity)}",
                "{total: multiply(input.unit_price, input.quantity), label}",
            ),
            encoding="utf-8",
        )
        source_root = self.intake.bind_source_root(
            self.source,
            root_kind="single_project",
            brand_profile={"names": ["HP"]},
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        first = self.intake.run_intake(project["project_id"])
        waiting = next(
            row
            for row in self._review_rows(first["run_id"])
            if row["candidate_status"] == "waiting_user"
        )
        self.intake.record_review_decisions(
            waiting["review_id"], brand_decision="retain_brand_limited"
        )

        second = self.intake.run_intake(project["project_id"])

        compute = next(
            json.loads(row["sanitized_candidate_json"])
            for row in self._review_rows(second["run_id"])
            if json.loads(row["sanitized_candidate_json"])["capability_kind"]
            == "computation"
        )
        self.assertEqual(compute["usage_scope"]["kind"], "brand_limited")
        self.assertEqual(compute["usage_scope"]["brand_profile_id"], source_root["brand_profile_id"])

    def test_indirect_const_strings_cannot_bypass_sensitive_or_brand_gates(self) -> None:
        self._write_complete_project(self.source)
        compute = self.source / "compute.js"
        compute.write_text(
            compute.read_text(encoding="utf-8").replace(
                "export function compute(input) {",
                """export function compute(input) {
  const user = "alice";
  const at = "@";
  const hostName = "example" + "." + "com";
  const customer = user + at + hostName;
  const brandLeft = "H";
  const brandRight = "P";
  const brandLabel = brandLeft + brandRight;""",
            ).replace(
                "{total: multiply(input.unit_price, input.quantity)}",
                "{total: multiply(input.unit_price, input.quantity), customer, brandLabel}",
            ),
            encoding="utf-8",
        )
        source_root = self.intake.bind_source_root(
            self.source,
            root_kind="single_project",
            brand_profile={"names": ["HP"]},
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])

        result = self.intake.run_intake(project["project_id"])

        compute_row = next(
            row
            for row in self._review_rows(result["run_id"])
            if row["source_relpath"] == "compute.js"
        )
        summary = json.loads(compute_row["redaction_summary_json"])
        self.assertEqual(compute_row["candidate_status"], "waiting_user")
        self.assertIn("email_literal", summary["codes"])
        self.assertIn("brand_literal", summary["codes"])
        self.assertGreater(summary["ambiguous_count"], 0)
        self.assertGreater(summary["brand_count"], 0)
        self.assertNotIn(b"alice@example.com", self.store.path.read_bytes())

    def test_unresolved_string_generators_fail_closed_before_sensitive_gate(self) -> None:
        expressions = {
            "join": '["alice", "@", "example.com"].join("")',
            "concat": '["H"].concat(["P"]).join("")',
            "from_char_code": (
                "String.fromCharCode(97,108,105,99,101,64,101,120,97,109,"
                "112,108,101,46,99,111,109)"
            ),
        }
        for label, expression in expressions.items():
            with self.subTest(generator=label):
                source = self.root / f"string-generator-{label}"
                source.mkdir()
                self._write_complete_project(source)
                presentation = source / "presentation.js"
                presentation.write_text(
                    presentation.read_text(encoding="utf-8").replace(
                        "title.textContent = input.title;",
                        f"title.textContent = {expression};",
                    ),
                    encoding="utf-8",
                )
                project = self._bind_discover_confirm(source)

                result = self.intake.run_intake(project["project_id"])

                row = next(
                    item
                    for item in self._review_rows(result["run_id"])
                    if item["source_relpath"] == "presentation.js"
                )
                self.assertEqual(row["candidate_status"], "rejected")
                self.assertIn(
                    "unsupported_string_construction_v1",
                    row["redaction_summary_json"],
                )

    def test_forbidden_member_names_remain_valid_plain_input_properties(self) -> None:
        self._write_complete_project(self.source)
        presentation = self.source / "presentation.js"
        presentation.write_text(
            presentation.read_text(encoding="utf-8").replace("input.title", "input.parse"),
            encoding="utf-8",
        )
        compute = self.source / "compute.js"
        compute.write_text(
            compute.read_text(encoding="utf-8").replace(
                "input.quantity", "input.parse"
            ),
            encoding="utf-8",
        )
        project = self._bind_discover_confirm(self.source)

        result = self.intake.run_intake(project["project_id"])

        row = next(
            item
            for item in self._review_rows(result["run_id"])
            if item["source_relpath"] == "presentation.js"
        )
        self.assertEqual(row["candidate_status"], "extracted")
        contract = json.loads(row["sanitized_candidate_json"])["input_contract"]
        self.assertIn("parse", contract["properties"])
        compute_row = next(
            item
            for item in self._review_rows(result["run_id"])
            if item["source_relpath"] == "compute.js"
        )
        self.assertEqual(compute_row["candidate_status"], "extracted")
        compute_contract = json.loads(compute_row["sanitized_candidate_json"])[
            "input_contract"
        ]
        self.assertIn("parse", compute_contract["properties"])

    def test_string_factory_aliases_and_json_parse_fail_closed(self) -> None:
        statements = {
            "aliased_from_char_code": (
                "const decode = String.fromCharCode;\n"
                "  title.textContent = decode(97,108,105,99,101,64,101,120,97,109,"
                "112,108,101,46,99,111,109);"
            ),
            "prototype_callback": (
                "const concat = String.prototype.concat;\n"
                '  title.textContent = ["alice", "@", "example.com"].reduce(concat);'
            ),
            "aliased_json_parse": (
                "const parse = JSON.parse;\n"
                r'''  title.textContent = parse("\"alice\\u0040example.com\"");'''
            ),
            "destructured_json_parse": (
                "const {parse} = JSON;\n"
                r'''  title.textContent = parse("\"alice\\u0040example.com\"");'''
            ),
        }
        for label, statement in statements.items():
            with self.subTest(generator=label):
                source = self.root / f"string-alias-{label}"
                source.mkdir()
                self._write_complete_project(source)
                presentation = source / "presentation.js"
                presentation.write_text(
                    presentation.read_text(encoding="utf-8").replace(
                        "title.textContent = input.title;",
                        statement,
                    ),
                    encoding="utf-8",
                )
                project = self._bind_discover_confirm(source)

                result = self.intake.run_intake(project["project_id"])

                row = next(
                    item
                    for item in self._review_rows(result["run_id"])
                    if item["source_relpath"] == "presentation.js"
                )
                self.assertEqual(row["candidate_status"], "rejected")
                self.assertIn(
                    "unsupported_string_construction_v1",
                    row["redaction_summary_json"],
                )

    def test_unused_entry_local_functions_and_arrows_fail_closed(self) -> None:
        declarations = {
            "function": (
                "function unusedHelper(value) { return value; }\n"
                "  const unusedAlias = unusedHelper;"
            ),
            "arrow": (
                "const unusedHelper = (value) => value;\n"
                "  const unusedAlias = unusedHelper;"
            ),
            "const": "const unusedValue = 1;",
            "expression": "input.quantity;",
        }
        for label, declaration in declarations.items():
            with self.subTest(declaration=label):
                source = self.root / f"unused-{label}"
                source.mkdir()
                self._write_complete_project(source)
                compute = source / "compute.js"
                compute.write_text(
                    compute.read_text(encoding="utf-8").replace(
                        "export function compute(input) {",
                        f"export function compute(input) {{\n  {declaration}",
                    ),
                    encoding="utf-8",
                )
                project = self._bind_discover_confirm(source)

                result = self.intake.run_intake(project["project_id"])

                rejected = [
                    row
                    for row in self._review_rows(result["run_id"])
                    if row["source_relpath"] == "compute.js"
                ]
                self.assertEqual(len(rejected), 1)
                self.assertEqual(rejected[0]["candidate_status"], "rejected")
                self.assertIn(
                    "unsupported_extraction_boundary_v1",
                    rejected[0]["redaction_summary_json"],
                )

    def test_extractor_consumes_only_snapshot_module_bytes(self) -> None:
        self._write_complete_project(self.source)
        project = self._bind_discover_confirm(self.source)
        original_run = subprocess.run
        captured_request: dict[str, object] = {}
        captured_command: list[str] = []

        def replace_during_node(command, *args, **kwargs):
            if str(command[-1]).endswith("analyze_reweave_extraction.mjs"):
                captured_command.extend(str(item) for item in command)
                captured_request.update(json.loads(kwargs["input"]))
                compute = self.source / "compute.js"
                original = compute.read_text(encoding="utf-8")
                compute.write_text(original.replace("{total:", "{raced:"), encoding="utf-8")
                try:
                    return original_run(command, *args, **kwargs)
                finally:
                    compute.write_text(original, encoding="utf-8")
            return original_run(command, *args, **kwargs)

        with patch(
            "pimos_lite.reweave_capsule_intake.subprocess.run",
            side_effect=replace_during_node,
        ):
            result = self.intake.run_intake(project["project_id"])

        self.assertNotIn("project_root", captured_request)
        self.assertIn("module_snapshot", captured_request)
        self.assertIn("--max-old-space-size=256", captured_command)
        compute_candidate = next(
            json.loads(row["sanitized_candidate_json"])
            for row in self._review_rows(result["run_id"])
            if json.loads(row["sanitized_candidate_json"]).get("capability_kind")
            == "computation"
        )
        self.assertIn("total", compute_candidate["output_contract"]["properties"])
        self.assertNotIn("raced", compute_candidate["output_contract"]["properties"])

    def test_ignored_directory_cannot_enter_snapshot_closure_or_no_change(self) -> None:
        for index, ignored_name in enumerate(("dist", "Dist", "NODE_MODULES", ".Git")):
            with self.subTest(directory=ignored_name):
                source = self.root / f"ignored-source-{index}"
                source.mkdir()
                ignored = source / ignored_name
                ignored.mkdir()
                (source / "index.html").write_text(
                    '<main></main><script type="module" src="./compute.js"></script>',
                    encoding="utf-8",
                )
                (source / "compute.js").write_text(
                    f'import {{helper}} from "./{ignored_name}/helper.js";\n'
                    "export function compute(input) { "
                    "return {ok:true,value:{result:helper()}}; }\n",
                    encoding="utf-8",
                )
                module = ignored / "helper.js"
                module.write_text(
                    "export function helper() { return 1; }\n",
                    encoding="utf-8",
                )
                project = self._bind_discover_confirm(source)

                with self.assertRaisesRegex(
                    IntakeError, "static_closure_outside_snapshot"
                ):
                    self.intake.run_intake(project["project_id"])
                module.write_text(
                    "export function helper() { return 2; }\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    IntakeError, "static_closure_outside_snapshot"
                ):
                    self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM review_items").fetchone()[0], 0
            )
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM intake_runs WHERE status = 'no_change'"
                ).fetchone()[0],
                0,
            )

    def test_multi_role_module_and_non_returned_dispose_fail_closed(self) -> None:
        (self.source / "index.html").write_text(
            """<main data-capsule-root><span id="title"></span></main>
<script type="module" src="./app.js"></script>""",
            encoding="utf-8",
        )
        (self.source / "app.js").write_text(
            """export function render(root, input) {
  if (typeof input.title !== "string" || input.title.length > 40) return {ok:false,error:{code:"INVALID_TITLE"}};
  const title = root.querySelector("#title");
  title.textContent = input.title;
}
export function compute(input) {
  if (!Number.isInteger(input.quantity) || input.quantity < 1 || input.quantity > 10) return {ok:false,error:{code:"INVALID_QUANTITY"}};
  return {ok:true,value:{quantity:input.quantity}};
}
""",
            encoding="utf-8",
        )
        project = self._bind_discover_confirm(self.source)
        result = self.intake.run_intake(project["project_id"])
        rows = self._review_rows(result["run_id"])
        self.assertEqual(sum(row["candidate_status"] == "extracted" for row in rows), 0)
        self.assertTrue(rows)
        self.assertTrue(
            all("non_atomic_role_closure_v1" in row["redaction_summary_json"] for row in rows)
        )

        second_source = self.root / "dispose-source"
        second_source.mkdir()
        self._write_complete_project(second_source)
        interaction = second_source / "interaction.js"
        interaction.write_text(
            interaction.read_text(encoding="utf-8").replace(
                "  return () => { button.removeEventListener(\"click\", onClick); };",
                "  button.removeEventListener(\"click\", onClick);",
            ),
            encoding="utf-8",
        )
        second_project = self._bind_discover_confirm(second_source)
        second = self.intake.run_intake(second_project["project_id"])
        interaction_row = next(
            row
            for row in self._review_rows(second["run_id"])
            if "interaction_dispose_not_closed" in row["redaction_summary_json"]
        )
        self.assertEqual(interaction_row["candidate_status"], "rejected")

    def test_html_number_attributes_do_not_define_emit_contract(self) -> None:
        self._write_complete_project(self.source)
        interaction = self.source / "interaction.js"
        interaction.write_text(
            interaction.read_text(encoding="utf-8").replace(
                "    const value = Number(quantity.value);\n"
                "    if (!Number.isInteger(value) || value < 1 || value > 10) return;\n"
                "    ports.emit(\"calculate_requested\", {quantity: value});",
                '    ports.emit("calculate_requested", {quantity: Number(quantity.value)});',
            ),
            encoding="utf-8",
        )
        project = self._bind_discover_confirm(self.source)
        result = self.intake.run_intake(project["project_id"])
        rejected = [
            row
            for row in self._review_rows(result["run_id"])
            if row["candidate_status"] == "rejected"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertIn("ambiguous_data_contract_v1", rejected[0]["redaction_summary_json"])

    def test_source_change_during_scan_fails_without_review_rows(self) -> None:
        self._write_complete_project(self.source)
        project = self._bind_discover_confirm(self.source)
        original = self.intake._extract

        def mutate_after_extract(*args, **kwargs):
            result = original(*args, **kwargs)
            compute = self.source / "compute.js"
            compute.write_text(compute.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
            return result

        with patch.object(self.intake, "_extract", side_effect=mutate_after_extract):
            with self.assertRaisesRegex(IntakeError, "source_changed_during_scan"):
                self.intake.run_intake(project["project_id"])

        with self.store.read_connection() as connection:
            run = connection.execute(
                "SELECT status, error_code FROM intake_runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(tuple(run), ("failed", "source_changed_during_scan"))
            self.assertEqual(connection.execute("SELECT count(*) FROM review_items").fetchone()[0], 0)

    def test_snapshot_rejects_regular_file_replacement_between_check_and_open(self) -> None:
        self._write_complete_project(self.source)
        project = self._bind_discover_confirm(self.source)
        target = self.source / "compute.js"
        original = self.source / "compute.original.js"
        replacement = self.source / "compute.replacement.js"
        replacement.write_text(
            "export function compute(input) { return {ok:true,value:{changed:true}}; }\n",
            encoding="utf-8",
        )
        target_resolved = target.resolve()
        original_open = os.open
        swapped = False

        def replace_before_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if Path(path) == target_resolved and not swapped:
                swapped = True
                target.replace(original)
                replacement.replace(target)
            return original_open(path, flags, *args, **kwargs)

        try:
            with patch(
                "pimos_lite.reweave_capsule_intake.os.open",
                side_effect=replace_before_open,
            ), self.assertRaisesRegex(IntakeError, "source_changed_during_scan"):
                self.intake.run_intake(project["project_id"])
        finally:
            if target.exists() or target.is_symlink():
                target.unlink()
            if original.exists():
                original.replace(target)
            if replacement.exists():
                replacement.unlink()

        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM review_items").fetchone()[0], 0)
            self.assertIsNone(
                connection.execute(
                    "SELECT last_snapshot_hash FROM projects WHERE project_id = ?",
                    (project["project_id"],),
                ).fetchone()[0]
            )

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "O_NOFOLLOW"),
        "O_NOFOLLOW symlink race assertion requires POSIX",
    )
    def test_snapshot_rejects_symlink_replacement_between_check_and_open(self) -> None:
        self._write_complete_project(self.source)
        project = self._bind_discover_confirm(self.source)
        target = self.source / "compute.js"
        original = self.source / "compute.original.js"
        outside = self.root / "outside-compute.js"
        outside.write_text(
            "export function compute(input) { return {ok:true,value:{outside:true}}; }\n",
            encoding="utf-8",
        )
        target_resolved = target.resolve()
        original_open = os.open
        swapped = False

        def replace_with_symlink(path, flags, *args, **kwargs):
            nonlocal swapped
            if Path(path) == target_resolved and not swapped:
                swapped = True
                target.replace(original)
                target.symlink_to(outside)
            return original_open(path, flags, *args, **kwargs)

        try:
            with patch(
                "pimos_lite.reweave_capsule_intake.os.open",
                side_effect=replace_with_symlink,
            ), self.assertRaisesRegex(
                IntakeError,
                "static_closure_symlink_forbidden",
            ):
                self.intake.run_intake(project["project_id"])
        finally:
            if target.exists() or target.is_symlink():
                target.unlink()
            if original.exists():
                original.replace(target)

        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM review_items").fetchone()[0], 0)
            self.assertIsNone(
                connection.execute(
                    "SELECT last_snapshot_hash FROM projects WHERE project_id = ?",
                    (project["project_id"],),
                ).fetchone()[0]
            )

    def test_outside_import_is_rejected_without_formal_write(self) -> None:
        project_dir = self.source / "project"
        project_dir.mkdir()
        (project_dir / "index.html").write_text(
            '<main></main><script type="module" src="./compute.js"></script>',
            encoding="utf-8",
        )
        (project_dir / "compute.js").write_text(
            'import {helper} from "../outside.js";\n'
            'export function compute(input) { return {ok:true,value:{result:helper(input)}}; }\n',
            encoding="utf-8",
        )
        (self.source / "outside.js").write_text(
            "export function helper(value) { return value; }\n", encoding="utf-8"
        )
        source_root = self.intake.bind_source_root(
            self.source, root_kind="project_collection"
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])

        with self.assertRaisesRegex(IntakeError, "static_closure_outside_snapshot"):
            self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM review_items").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM capsules").fetchone()[0], 0)

    def test_one_rejected_role_does_not_block_other_atomic_roles(self) -> None:
        self._write_complete_project(self.source)
        compute = self.source / "compute.js"
        compute.write_text(
            compute.read_text(encoding="utf-8").replace(
                "export function compute(input) {",
                "export function compute(input) { document.title;",
            ),
            encoding="utf-8",
        )
        project = self._bind_discover_confirm(self.source)

        result = self.intake.run_intake(project["project_id"])

        self.assertEqual(result["counts"]["extracted"], 2)
        self.assertEqual(result["counts"]["rejected"], 1)
        statuses = [row["candidate_status"] for row in self._review_rows(result["run_id"])]
        self.assertEqual(statuses.count("extracted"), 2)
        self.assertEqual(statuses.count("rejected"), 1)

    def test_exported_arrow_entrypoint_and_missing_module_are_deterministic(self) -> None:
        self._write_complete_project(self.source)
        presentation = self.source / "presentation.js"
        presentation.write_text(
            presentation.read_text(encoding="utf-8").replace(
                "export function render(root, input) {",
                "export const render = (root, input) => {",
            ),
            encoding="utf-8",
        )
        project = self._bind_discover_confirm(self.source)
        first = self.intake.run_intake(project["project_id"])
        presentation_row = next(
            row
            for row in self._review_rows(first["run_id"])
            if json.loads(row["sanitized_candidate_json"]).get("capability_kind")
            == "presentation"
        )
        self.assertEqual(presentation_row["candidate_status"], "extracted")

        compute = self.source / "compute.js"
        compute.write_text(
            compute.read_text(encoding="utf-8").replace(
                'from "./math.js"', 'from "./missing.js"'
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(IntakeError, "static_closure_outside_snapshot"):
            self.intake.run_intake(project["project_id"])

    def test_local_named_and_default_es_module_exports_are_supported(self) -> None:
        self._write_complete_project(self.source)
        presentation = self.source / "presentation.js"
        presentation.write_text(
            presentation.read_text(encoding="utf-8").replace(
                "export function render", "function render"
            )
            + "\nexport {render};\n",
            encoding="utf-8",
        )
        math = self.source / "math.js"
        math.write_text(
            math.read_text(encoding="utf-8").replace(
                "export function multiply", "export default function multiply"
            ),
            encoding="utf-8",
        )
        compute = self.source / "compute.js"
        compute.write_text(
            compute.read_text(encoding="utf-8")
            .replace('import {multiply}', "import multiply")
            .replace("export function compute", "export default function compute"),
            encoding="utf-8",
        )
        project = self._bind_discover_confirm(self.source)

        result = self.intake.run_intake(project["project_id"])

        candidates = [
            json.loads(row["sanitized_candidate_json"])
            for row in self._review_rows(result["run_id"])
            if row["candidate_status"] == "extracted"
        ]
        self.assertEqual(len(candidates), 3)
        compute_candidate = next(
            item for item in candidates if item["capability_kind"] == "computation"
        )
        self.assertEqual(compute_candidate["activation"]["entrypoint"], "default")

    def test_cancel_and_restart_recovery_leave_no_half_candidate(self) -> None:
        self._write_complete_project(self.source)
        project = self._bind_discover_confirm(self.source)
        with self.assertRaisesRegex(IntakeError, "intake_cancelled"):
            self.intake.run_intake(project["project_id"], cancel_check=lambda: True)
        queued = self.intake._create_run(project["project_id"])
        self.assertEqual(self.intake.recover_interrupted_runs(), 1)
        with self.store.read_connection() as connection:
            states = {
                row["run_id"]: row["status"]
                for row in connection.execute(
                    "SELECT run_id, status FROM intake_runs WHERE run_id IN (?, ?)",
                    (queued, connection.execute(
                        "SELECT run_id FROM intake_runs WHERE status = 'cancelled' LIMIT 1"
                    ).fetchone()[0]),
                )
            }
            self.assertIn("cancelled", states.values())
            self.assertIn("interrupted", states.values())
            self.assertEqual(connection.execute("SELECT count(*) FROM review_items").fetchone()[0], 0)

    def _bind_discover_confirm(self, source: Path) -> dict[str, object]:
        source_root = self.intake.bind_source_root(source, root_kind="single_project")
        project = self.intake.discover_projects(source_root["root_id"])[0]
        return self.intake.confirm_project(project["project_id"])

    def _review_rows(self, run_id: str):
        with self.store.read_connection() as connection:
            return connection.execute(
                "SELECT * FROM review_items WHERE run_id = ? ORDER BY created_at, review_id",
                (run_id,),
            ).fetchall()

    @staticmethod
    def _write_complete_project(root: Path, *, extra_compute: str = "") -> None:
        (root / "index.html").write_text(
            """<!doctype html>
<html><body>
<main data-capsule-root>
  <span id="title"></span>
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
        (root / "presentation.js").write_text(
            """export function render(root, input) {
  if (typeof input.title !== "string" || input.title.length > 40) {
    return {ok: false, error: {code: "INVALID_TITLE"}};
  }
  const title = root.querySelector("#title");
  title.textContent = input.title;
}
""",
            encoding="utf-8",
        )
        (root / "interaction.js").write_text(
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
        (root / "math.js").write_text(
            "export function multiply(left, right) { return left * right; }\n",
            encoding="utf-8",
        )
        (root / "compute.js").write_text(
            extra_compute
            + """import {multiply} from "./math.js";
export function compute(input) {
  if (!Number.isInteger(input.quantity) || input.quantity < 1 || input.quantity > 10) {
    return {ok: false, error: {code: "INVALID_QUANTITY"}};
  }
  if (!Number.isInteger(input.unit_price) || input.unit_price < 0 || input.unit_price > 1000) {
    return {ok: false, error: {code: "INVALID_UNIT_PRICE"}};
  }
  return {ok: true, value: {total: multiply(input.unit_price, input.quantity)}};
}
""",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
