"""Bounded Phase 4 tests for read-only legacy warehouse import."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_capsule_intake import (
    EXTRACTION_CONTRACT_VERSION,
    IntakeError,
)
from pimos_lite.reweave_capsule_store import CapsuleWarehouseStore
from pimos_lite.reweave_capsule_warehouse import warehouse_path
from pimos_lite.reweave_engine.local import LocalReweaveEngine
from pimos_lite.reweave_source_registry import registry_path


class Phase4LegacyImportTest(unittest.TestCase):
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

    def _write_raw(self, raw: bytes) -> tuple[Path, str]:
        path = warehouse_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest()

    def _write_capsules(self, capsules: list[object]) -> tuple[Path, str]:
        raw = json.dumps(
            {"schema_version": 1, "capsules": capsules},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return self._write_raw(raw)

    def _rows(self, table: str) -> list[dict[str, object]]:
        with self.store.read_connection() as connection:
            return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]

    def _bind_legacy_project(self) -> str:
        source = self.root / "project"
        source.mkdir()
        (source / "index.html").write_text(
            '<div data-capsule-root="quote"></div>', encoding="utf-8"
        )
        root = self.service._capsule_intake.bind_source_root(
            source, root_kind="single_project"
        )
        discovered = self.service._capsule_intake.discover_projects(str(root["root_id"]))
        self.assertEqual(len(discovered), 1)
        project = self.service._capsule_intake.confirm_project(
            str(discovered[0]["project_id"])
        )
        registry_path().write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source_boxes": [
                        {"id": "legacy-source", "path": str(source.resolve())}
                    ],
                }
            ),
            encoding="utf-8",
        )
        return str(project["project_id"])

    def _seed_target(
        self,
        project_id: str,
        suffix: str,
        *,
        source_link: bool = True,
        historical: bool = False,
        disabled: bool = False,
    ) -> tuple[str, str]:
        capsule_id = f"capsule-{suffix}"
        linked_version_id = f"version-{suffix}-1"
        current_version_id = f"version-{suffix}-2" if historical else linked_version_id
        now = "2026-07-15T00:00:00Z"

        def version_row(version_id: str, number: int) -> dict[str, object]:
            digest = hashlib.sha256(version_id.encode()).hexdigest()
            return {
                "version_id": version_id,
                "capsule_id": capsule_id,
                "version_number": number,
                "extraction_contract_version": EXTRACTION_CONTRACT_VERSION,
                "extraction_summary_json": "{}",
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
                "INSERT INTO capability_groups VALUES (?, ?, ?, ?)",
                (f"legacy_target_{suffix}", f"Legacy target {suffix}", now, now),
            )
            connection.execute(
                "INSERT INTO capsules VALUES (?, ?, 'role', 'default', 'computation', "
                "'pending_revalidation', NULL, ?)",
                (capsule_id, f"legacy_target_{suffix}", now),
            )
            rows = [version_row(linked_version_id, 1)]
            if historical:
                rows.append(version_row(current_version_id, 2))
            for row in rows:
                connection.execute(
                    f"INSERT INTO capsule_versions ({', '.join(row)}) "
                    f"VALUES ({', '.join('?' for _ in row)})",
                    tuple(row.values()),
                )
            connection.execute(
                "UPDATE capsules SET current_version_id = ?, status = 'active' "
                "WHERE capsule_id = ?",
                (current_version_id, capsule_id),
            )
            if source_link:
                digest = hashlib.sha256(linked_version_id.encode()).hexdigest()
                connection.execute(
                    "INSERT INTO capsule_sources VALUES (?, ?, ?, ?, 'project', "
                    "'index.html', ?, ?, 'exact', ?)",
                    (
                        f"source-{suffix}",
                        linked_version_id,
                        project_id,
                        f"project:{project_id}",
                        digest,
                        digest,
                        now,
                    ),
                )
            if disabled:
                connection.execute(
                    "UPDATE capsules SET status = 'disabled' WHERE capsule_id = ?",
                    (capsule_id,),
                )
        return capsule_id, linked_version_id

    def test_corrupt_json_fails_run_without_alias_or_legacy_write(self) -> None:
        path, before = self._write_raw(b"{broken")

        with self.assertRaisesRegex(IntakeError, "legacy_warehouse_parse_failed"):
            self.service._legacy_import(threading.Event(), {})

        runs = self._rows("intake_runs")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["run_kind"], "legacy_import")
        self.assertEqual(runs[0]["status"], "failed")
        self.assertEqual(runs[0]["error_code"], "legacy_warehouse_parse_failed")
        self.assertEqual(self._rows("legacy_capsule_aliases"), [])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_cancelled_project_reclean_does_not_publish_legacy_aliases(self) -> None:
        self._bind_legacy_project()
        path, before = self._write_capsules(
            [{"id": "cap_123456789abc", "source_id": "legacy-source"}]
        )
        cancel = threading.Event()

        def cancelled_refresh(_project_id: str, event: threading.Event) -> dict[str, object]:
            event.set()
            return {"status": "cancelled", "intake": {}, "gate_results": []}

        with patch.object(self.service, "_refresh_project", side_effect=cancelled_refresh):
            result = self.service._legacy_import(cancel, {})

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self._rows("legacy_capsule_aliases"), [])
        runs = self._rows("intake_runs")
        self.assertEqual(runs[-1]["status"], "cancelled")
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_mixed_items_are_isolated_and_unbound_items_run_no_gates(self) -> None:
        path, before = self._write_capsules(
            [
                {
                    "id": "cap_0123456789ab",
                    "status": "active",
                    "source_id": "missing-source",
                },
                "not-an-object",
                {"name": "missing id"},
                {"id": "13800138000", "source_id": "missing-source"},
            ]
        )

        with (
            patch.object(self.service, "_refresh_project") as refresh,
            patch.object(self.service._capsule_supervisor, "supervise") as model,
            patch.object(self.service._capsule_stage3, "_runtime_validation") as worker,
        ):
            result = self.service._legacy_import(threading.Event(), {})

        self.assertEqual(result["status"], "completed_with_pending")
        self.assertEqual(
            result["counts"],
            {"total": 4, "skipped": 0, "pending": 1, "rejected": 3, "linked": 0},
        )
        aliases = {
            str(row["legacy_capsule_id"]): row
            for row in self._rows("legacy_capsule_aliases")
        }
        self.assertEqual(aliases["cap_0123456789ab"]["relationship"], "pending")
        self.assertEqual(aliases["item_1"]["relationship"], "rejected")
        self.assertEqual(aliases["item_2"]["relationship"], "rejected")
        self.assertEqual(aliases["item_3"]["relationship"], "rejected")
        self.assertNotIn("13800138000", {row["legacy_capsule_id"] for row in aliases.values()})
        self.assertTrue(all(row["new_version_id"] is None for row in aliases.values()))
        refresh.assert_not_called()
        model.assert_not_called()
        worker.assert_not_called()
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_link_accepts_only_active_current_version_from_recleaned_project(self) -> None:
        project_id = self._bind_legacy_project()
        capsule_id, version_id = self._seed_target(project_id, "valid")
        legacy_id = "cap_111111111111"
        path, before = self._write_capsules(
            [{"id": legacy_id, "source_id": "legacy-source", "status": "ready"}]
        )
        links = {
            legacy_id: {
                "relationship": "cleaned_successor",
                "capsule_id": capsule_id,
                "version_id": version_id,
            }
        }

        with patch.object(
            self.service,
            "_refresh_project",
            return_value={"intake": {}, "gate_results": []},
        ):
            result = self.service._legacy_import(threading.Event(), links)

        self.assertEqual(result["counts"]["linked"], 1)
        alias = self._rows("legacy_capsule_aliases")[0]
        self.assertEqual(alias["relationship"], "cleaned_successor")
        self.assertEqual(alias["new_version_id"], version_id)
        legacy_sources = [
            row
            for row in self._rows("capsule_sources")
            if row["source_kind"] == "legacy_json"
        ]
        self.assertEqual(len(legacy_sources), 1)
        self.assertEqual(legacy_sources[0]["version_id"], version_id)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_link_rejects_disabled_historical_and_unrelated_versions(self) -> None:
        project_id = self._bind_legacy_project()
        cases = (
            ("disabled", {"disabled": True}),
            ("historical", {"historical": True}),
            ("unrelated", {"source_link": False}),
        )
        for index, (suffix, options) in enumerate(cases, start=2):
            with self.subTest(suffix=suffix):
                capsule_id, version_id = self._seed_target(
                    project_id, suffix, **options
                )
                legacy_id = f"cap_{str(index) * 12}"
                path, before = self._write_capsules(
                    [{"id": legacy_id, "source_id": "legacy-source"}]
                )
                links = {
                    legacy_id: {
                        "relationship": "cleaned_successor",
                        "capsule_id": capsule_id,
                        "version_id": version_id,
                    }
                }
                with (
                    patch.object(
                        self.service,
                        "_refresh_project",
                        return_value={"intake": {}, "gate_results": []},
                    ),
                    self.assertRaisesRegex(IntakeError, "legacy_link_target_invalid"),
                ):
                    self.service._legacy_import(threading.Event(), links)
                self.service._fail_running_legacy_runs()
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

        self.assertEqual(self._rows("legacy_capsule_aliases"), [])

    def test_completed_nonpending_alias_is_skipped_for_same_file_hash(self) -> None:
        path, before = self._write_capsules([{"name": "invalid without id"}])

        first = self.service._legacy_import(threading.Event(), {})
        second = self.service._legacy_import(threading.Event(), {})

        self.assertEqual(first["counts"]["rejected"], 1)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(
            second["counts"],
            {"total": 1, "skipped": 1, "pending": 0, "rejected": 0, "linked": 0},
        )
        aliases = self._rows("legacy_capsule_aliases")
        self.assertEqual(len(aliases), 1)
        self.assertEqual(aliases[0]["relationship"], "rejected")
        runs = self._rows("intake_runs")
        self.assertEqual([row["status"] for row in runs], ["completed", "completed"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_management_state_exposes_only_latest_safe_legacy_alias_fields(self) -> None:
        self._write_capsules(
            [{"id": "cap_123456789abc", "source_id": "missing-source"}]
        )
        result = self.service._legacy_import(threading.Event(), {})
        self.assertEqual(result["status"], "completed_with_pending")

        legacy = self.service.get_initial_state()["capsuleIngestionV1"]["legacy"]
        self.assertEqual(legacy["aliasCounts"], {"pending": 1})
        self.assertEqual(len(legacy["aliases"]), 1)
        alias = legacy["aliases"][0]
        self.assertEqual(
            set(alias),
            {
                "legacy_capsule_id",
                "relationship",
                "new_capsule_id",
                "new_version_id",
                "reason_code",
                "created_at",
                "eligible_targets",
            },
        )
        self.assertEqual(alias["legacy_capsule_id"], "cap_123456789abc")
        self.assertEqual(alias["relationship"], "pending")
        self.assertEqual(alias["eligible_targets"], [])

    def test_management_state_only_offers_same_project_active_current_targets(self) -> None:
        project_id = self._bind_legacy_project()
        valid_capsule, valid_version = self._seed_target(project_id, "eligible")
        self._seed_target(project_id, "unrelated_ui", source_link=False)
        legacy_id = "cap_abcdefabcdef"
        self._write_capsules(
            [{"id": legacy_id, "source_id": "legacy-source"}]
        )
        with patch.object(
            self.service,
            "_refresh_project",
            return_value={"status": "completed", "intake": {}, "gate_results": []},
        ):
            result = self.service._legacy_import(threading.Event(), {})
        self.assertEqual(result["status"], "completed_with_pending")

        aliases = self.service.get_initial_state()["capsuleIngestionV1"]["legacy"][
            "aliases"
        ]
        self.assertEqual(len(aliases), 1)
        self.assertEqual(
            [
                (target["capsule_id"], target["version_id"])
                for target in aliases[0]["eligible_targets"]
            ],
            [(valid_capsule, valid_version)],
        )

    def test_nested_ready_project_matches_legacy_path_and_eligible_target(self) -> None:
        collection = self.root / "collection"
        child = collection / "child"
        child.mkdir(parents=True)
        (collection / "index.html").write_text("<main>Parent</main>", encoding="utf-8")
        (child / "index.html").write_text("<main>Child</main>", encoding="utf-8")
        root = self.service._capsule_intake.bind_source_root(
            collection, root_kind="project_collection"
        )
        projects = self.service._capsule_intake.discover_projects(str(root["root_id"]))
        for project in projects:
            self.service._capsule_intake.confirm_project(str(project["project_id"]))
        child_project = next(
            project for project in projects if project["project_relpath"] == "child"
        )
        child_project_id = str(child_project["project_id"])
        registry_path().write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source_boxes": [
                        {"id": "legacy-child", "path": str(child.resolve())}
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.service._legacy_project_id(str(child)), child_project_id)

        valid_capsule, valid_version = self._seed_target(child_project_id, "nested")
        self._write_capsules(
            [{"id": "cap_123abc123abc", "source_id": "legacy-child"}]
        )
        with patch.object(
            self.service,
            "_refresh_project",
            return_value={"status": "completed", "intake": {}, "gate_results": []},
        ):
            result = self.service._legacy_import(threading.Event(), {})
        self.assertEqual(result["status"], "completed_with_pending")

        aliases = self.service.get_initial_state()["capsuleIngestionV1"]["legacy"]["aliases"]
        self.assertEqual(len(aliases), 1)
        self.assertEqual(
            [
                (target["capsule_id"], target["version_id"])
                for target in aliases[0]["eligible_targets"]
            ],
            [(valid_capsule, valid_version)],
        )


if __name__ == "__main__":
    unittest.main()
