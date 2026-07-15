"""Stage 1 tests for the non-active SQLite capsule warehouse foundation."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite import reweave_capsule_store as store_module
from pimos_lite.reweave_capsule_store import (
    CapsuleStoreError,
    CapsuleWarehouseStore,
    SchemaVersionError,
    canonicalize_capsule,
)


NOW = "2026-07-15T00:00:00Z"


def canonical_payload() -> dict[str, object]:
    return {
        "capability_kind": "computation",
        "activation": {
            "entry_module": "main.js",
            "entrypoint_export": "compute",
            "execution": "sync",
        },
        "input_contract": {
            "schema": "data_contract.v1",
            "type": "object",
            "properties": {
                "quantity": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 99,
                    "enum": [3, 1, 3],
                }
            },
            "required": ["quantity"],
            "additional_properties": False,
        },
        "output_contract": {
            "schema": "data_contract.v1",
            "type": "object",
            "properties": {"total": {"type": "decimal", "scale": "0.01"}},
            "required": ["total"],
            "additional_properties": False,
        },
        "error_contract": {"schema": "error_contract.v1", "errors": {}},
        "runtime_allowlist": ["json", "math", "json"],
        "dom_scope": {
            "root_contract": "capsule_root",
            "selectors": ["[data-ref='result']", "[data-ref='quantity']"],
            "classes": ["is-hidden", "is-hidden"],
            "attributes": ["data-state"],
            "events": [],
        },
        "usage_scope": {"kind": "general"},
        "html": "<section>\r\n  Quote\r</section>\n",
        "css": "__CAPSULE_ROOT__ {\r\n  display: block;\r\n}\n",
        "javascript_modules": [
            {"path": "lib/math.js", "source": "export const twice = n => n * 2;\r\n"},
            {
                "path": "main.js",
                "source": (
                    "import { twice } from './lib/math.js';\r\n"
                    "export function compute(input) { return { ok: true, value: twice(input.quantity) }; }\r\n"
                ),
            },
        ],
        "assets": [
            {
                "logical_path": "images/quote.webp",
                "media_type": "image/webp",
                "sha256": "b" * 64,
            },
            {
                "logical_path": "images/icon.png",
                "media_type": "image/png",
                "sha256": "a" * 64,
            },
        ],
    }


def compact_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class CapsuleWarehouseStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.path = self.root / "state" / "capsule_warehouse.sqlite3"
        self.store = CapsuleWarehouseStore(self.path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_store_is_non_active_until_explicit_initialize(self) -> None:
        self.assertFalse(self.path.exists())
        CapsuleWarehouseStore(self.path)
        self.assertFalse(self.path.exists())

        initialized = self.store.initialize()

        self.assertEqual(initialized, self.path.resolve())
        self.assertTrue(self.path.is_file())
        with self.store.read_connection() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            triggers = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                )
            }
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
            self.assertNotEqual(
                str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
                "wal",
            )
        self.assertEqual(len(tables), 14)
        self.assertEqual(len(triggers), 31)
        if os.name != "nt":
            self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_read_connection_is_really_read_only(self) -> None:
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT 1 AS value").fetchone()["value"], 1)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute(
                    "INSERT INTO app_settings VALUES ('bypass', '{}', ?)", (NOW,)
                )
        self.assertEqual(self.store.current_revision(), 0)

    def test_initialize_rejects_unknown_or_unversioned_nonempty_schema(self) -> None:
        self.path.parent.mkdir(parents=True)
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE stray(value TEXT)")
        connection.commit()
        connection.close()
        with self.assertRaises(SchemaVersionError):
            self.store.initialize()

        self.path.unlink()
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
        connection.close()
        with self.assertRaises(SchemaVersionError):
            self.store.initialize()

    def test_transaction_commits_or_rolls_back_as_one_unit(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "forced"):
            with self.store.transaction() as connection:
                connection.execute(
                    "INSERT INTO app_settings VALUES (?, ?, ?)",
                    ("rolled_back", "true", NOW),
                )
                self.store.bump_revision(connection)
                raise RuntimeError("forced")

        with self.store.read_connection() as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT value_json FROM app_settings WHERE setting_key = 'rolled_back'"
                ).fetchone()
            )
        self.assertEqual(self.store.current_revision(), 0)

        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO app_settings VALUES (?, ?, ?)",
                ("committed", "true", NOW),
            )
            self.assertEqual(self.store.bump_revision(connection), 1)
        self.assertEqual(self.store.current_revision(), 1)

    def test_database_constraints_close_stage_one_gaps(self) -> None:
        self._seed_project_and_active_version()
        with self.store.transaction() as connection:
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "new_capsule_requires_version_before_activation"
            ):
                connection.execute(
                    "INSERT INTO capsules VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "capsule-invalid-current",
                        "quote_calculation",
                        "invalid_current",
                        "default",
                        "computation",
                        "disabled",
                        "version-1",
                        NOW,
                    ),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO capsule_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "source-missing-project",
                        "version-1",
                        None,
                        "project:missing",
                        "project",
                        "main.js",
                        "source-hash",
                        "canonical-hash",
                        "exact",
                        NOW,
                    ),
                )
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "capsule_source_canonical_mismatch"
            ):
                connection.execute(
                    "INSERT INTO capsule_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "source-wrong-canonical-hash",
                        "version-1",
                        "project-1",
                        "project:project-1",
                        "project",
                        "main.js",
                        "source-hash",
                        "different-canonical-hash",
                        "exact",
                        NOW,
                    ),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO capsule_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "source-wrong-project-identity",
                        "version-1",
                        "project-1",
                        "project:not-project-1",
                        "project",
                        "main.js",
                        "source-hash",
                        "canonical-hash",
                        "exact",
                        NOW,
                    ),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO capsule_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "source-empty-legacy-identity",
                        "version-1",
                        None,
                        "legacy:",
                        "legacy_json",
                        "capsules.json",
                        "source-hash",
                        "canonical-hash",
                        "exact",
                        NOW,
                    ),
                )

            connection.execute(
                "UPDATE capsules SET status = 'pending_revalidation' "
                "WHERE capsule_id = 'capsule-1'"
            )
            connection.execute(
                "INSERT INTO capsule_status_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "event-1",
                    "capsule-1",
                    "revalidation_required",
                    "active",
                    "pending_revalidation",
                    "version-1",
                    "rules_upgraded",
                    NOW,
                ),
            )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "status_event_state_mismatch"):
                connection.execute(
                    "INSERT INTO capsule_status_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "event-false-state",
                        "capsule-1",
                        "revalidation_required",
                        "garbage",
                        "pending_revalidation",
                        "version-1",
                        "rules_upgraded",
                        NOW,
                    ),
                )
            connection.execute(
                "UPDATE capsules SET status = 'active' WHERE capsule_id = 'capsule-1'"
            )
            connection.execute(
                "INSERT INTO capsule_status_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "event-2",
                    "capsule-1",
                    "enabled",
                    "pending_revalidation",
                    "active",
                    "version-1",
                    "rules_revalidated",
                    NOW,
                ),
            )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "status_event_state_mismatch"):
                connection.execute(
                    "INSERT INTO capsule_status_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "event-invalid-usage-scope-transition",
                        "capsule-1",
                        "usage_scope_changed",
                        "pending_revalidation",
                        "active",
                        "version-1",
                        "usage_scope_changed",
                        NOW,
                    ),
                )
            connection.execute(
                "INSERT INTO product_capsule_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "usage-1",
                    "product-1",
                    "manifest-a",
                    "capsule-1",
                    "version-1",
                    "quote_calculation",
                    "total_price",
                    "default",
                    '{"kind":"general"}',
                    "computation",
                    NOW,
                ),
            )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "product_manifest_digest_mismatch"):
                connection.execute(
                    "INSERT INTO product_capsule_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "usage-2",
                        "product-1",
                        "manifest-b",
                        "capsule-1",
                        "version-1",
                        "quote_calculation",
                        "total_price",
                        "default",
                        '{"kind":"general"}',
                        "asset",
                        NOW,
                    ),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "capsule_version_immutable"):
                connection.execute(
                    "UPDATE capsule_versions SET html_text = 'changed' WHERE version_id = 'version-1'"
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "capsule_version_delete_forbidden"):
                connection.execute(
                    "DELETE FROM capsule_versions WHERE version_id = 'version-1'"
                )

    def test_warehouse_state_and_version_ownership_are_closed(self) -> None:
        self._seed_project_and_active_version()
        with self.store.transaction() as connection:
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "warehouse_state_delete_forbidden"
            ):
                connection.execute("DELETE FROM warehouse_state")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE warehouse_state SET last_backed_up_revision = warehouse_revision + 1"
                )

            connection.execute(
                "INSERT INTO capability_groups VALUES (?, ?, ?, ?)",
                ("second_capability", "Second capability", NOW, NOW),
            )
            connection.execute(
                "INSERT INTO capsules VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "capsule-2",
                    "second_capability",
                    "second_role",
                    "default",
                    "computation",
                    "disabled",
                    None,
                    NOW,
                ),
            )
            version = list(
                connection.execute(
                    "SELECT * FROM capsule_versions WHERE version_id = 'version-1'"
                ).fetchone()
            )
            version[:3] = ["version-2", "capsule-2", 1]
            connection.execute(
                "INSERT INTO capsule_versions VALUES ("
                + ",".join("?" for _ in version)
                + ")",
                version,
            )
            connection.execute(
                "UPDATE capsules SET current_version_id = 'version-2' "
                "WHERE capsule_id = 'capsule-2'"
            )
            connection.execute(
                "INSERT INTO intake_runs ("
                "run_id, project_id, run_kind, status, extraction_contract_version, "
                "redaction_rules_version, security_rules_version, supervision_rules_version, "
                "validation_contract_version, canonicalization_version, "
                "legacy_source_path_hash, legacy_source_file_hash, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "legacy-run-1",
                    None,
                    "legacy_import",
                    "completed",
                    "extraction.v1",
                    "redaction.v1",
                    "security.v1",
                    "supervision.v1",
                    "validation.v1",
                    1,
                    "legacy-path-hash",
                    "legacy-file-hash",
                    NOW,
                ),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO capsule_status_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "event-mismatch",
                        "capsule-1",
                        "revalidation_required",
                        "active",
                        "pending_revalidation",
                        "version-2",
                        "rules_upgraded",
                        NOW,
                    ),
                )
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "legacy_alias_version_capsule_mismatch"
            ):
                connection.execute(
                    "INSERT INTO legacy_capsule_aliases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "alias-mismatch",
                        "legacy-run-1",
                        "legacy-file-hash",
                        "legacy-id",
                        "exact",
                        "capsule-1",
                        "version-2",
                        "manual_import",
                        NOW,
                    ),
                )
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "legacy_alias_contract_mismatch"
            ):
                connection.execute(
                    "INSERT INTO legacy_capsule_aliases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "alias-non-legacy-run",
                        "run-1",
                        "legacy-file-hash",
                        "legacy-id",
                        "exact",
                        "capsule-1",
                        "version-1",
                        "manual_import",
                        NOW,
                    ),
                )
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "legacy_alias_contract_mismatch"
            ):
                connection.execute(
                    "INSERT INTO legacy_capsule_aliases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "alias-exact-without-target",
                        "legacy-run-1",
                        "legacy-file-hash",
                        "legacy-id",
                        "exact",
                        None,
                        None,
                        "manual_import",
                        NOW,
                    ),
                )
            connection.execute(
                "INSERT INTO legacy_capsule_aliases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "alias-valid",
                    "legacy-run-1",
                    "legacy-file-hash",
                    "legacy-valid-id",
                    "exact",
                    "capsule-1",
                    "version-1",
                    "manual_import",
                    NOW,
                ),
            )

    def test_restore_validation_rejects_invalid_warehouse_state(self) -> None:
        backup = self.store.create_backup("manual")
        for variant in ("missing_singleton", "revision_inversion"):
            with self.subTest(variant=variant):
                tampered = self.root / f"{variant}.sqlite3"
                shutil.copy2(backup["path"], tampered)
                connection = sqlite3.connect(tampered)
                if variant == "missing_singleton":
                    trigger_sql = connection.execute(
                        "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
                        "AND name = 'warehouse_state_no_delete'"
                    ).fetchone()[0]
                    connection.execute("DROP TRIGGER warehouse_state_no_delete")
                    connection.execute("DELETE FROM warehouse_state")
                    connection.execute(trigger_sql)
                else:
                    connection.execute("PRAGMA ignore_check_constraints = ON")
                    connection.execute(
                        "UPDATE warehouse_state SET last_backed_up_revision = warehouse_revision + 1"
                    )
                connection.commit()
                connection.close()
                with self.assertRaisesRegex(
                    SchemaVersionError, "warehouse_state"
                ):
                    self.store.inspect_restore(tampered)

    def test_review_decision_binding_is_immutable(self) -> None:
        self._seed_project_and_active_version()
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO review_items ("
                "review_id, run_id, project_id, candidate_id, candidate_status, "
                "source_relpath, source_location_json, source_hash, redaction_rules_version, "
                "sanitized_candidate_json, redaction_summary_json, created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "review-1",
                    "run-1",
                    "project-1",
                    "candidate-1",
                    "waiting_user",
                    "main.js",
                    "{}",
                    "source-hash",
                    "redaction.v1",
                    "{}",
                    "{}",
                    NOW,
                    NOW,
                ),
            )
            connection.execute(
                "UPDATE review_items SET sensitivity_decision = ?, "
                "sensitivity_decided_at = ?, updated_at = ? WHERE review_id = ?",
                ("confirm_safe_redaction", NOW, NOW, "review-1"),
            )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "review_content_decision_immutable"):
                connection.execute(
                    "UPDATE review_items SET sensitivity_decision = ? WHERE review_id = ?",
                    ("confirm_fictional_fixture", "review-1"),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "review_source_binding_immutable"):
                connection.execute(
                    "UPDATE review_items SET source_hash = ? WHERE review_id = ?",
                    ("new-source-hash", "review-1"),
                )
            connection.execute(
                "UPDATE review_items SET asset_decision = ?, asset_decided_at = ?, "
                "updated_at = ? WHERE review_id = ?",
                ("confirm_assets_contain_no_real_records", NOW, NOW, "review-1"),
            )
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "review_content_decision_immutable"
            ):
                connection.execute(
                    "UPDATE review_items SET asset_decision = NULL WHERE review_id = ?",
                    ("review-1",),
                )

    def test_backup_restore_requires_digest_and_restores_full_snapshot(self) -> None:
        self._write_setting("phase", "before")
        backup = self.store.create_backup("manual")
        self._write_setting("phase", "after")
        self._seed_project_and_active_version()
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO product_capsule_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "usage-after-backup",
                    "product-after-backup",
                    "manifest-after-backup",
                    "capsule-1",
                    "version-1",
                    "quote_calculation",
                    "total_price",
                    "default",
                    '{"kind":"general"}',
                    "computation",
                    NOW,
                ),
            )

        with self.assertRaisesRegex(CapsuleStoreError, "digest"):
            self.store.restore_backup(backup["path"], expected_sha256="0" * 64)
        self.assertEqual(self._read_setting("phase"), "after")

        preview = self.store.inspect_restore(backup["path"])
        self.assertEqual(preview["sha256"], backup["sha256"])
        self.assertEqual(preview["capsules_removed"], 1)
        self.assertEqual(preview["versions_removed"], 1)
        self.assertEqual(preview["product_usage_removed"], 1)
        result = self.store.restore_backup(
            backup["path"], expected_sha256=backup["sha256"]
        )

        self.assertTrue(result["restored"])
        self.assertEqual(self._read_setting("phase"), "before")
        pre_restore = Path(result["pre_restore_backup_path"])
        self.assertTrue(pre_restore.is_file())
        self.assertEqual(self._read_setting_from(pre_restore, "phase"), "after")

    def test_restore_validation_failure_rolls_back_original_database(self) -> None:
        self._write_setting("phase", "backup")
        backup = self.store.create_backup("manual")
        self._write_setting("phase", "current")
        real_verify = store_module._verify_database
        failed = False

        def fail_once_on_replaced_database(path: Path) -> dict[str, object]:
            nonlocal failed
            info = real_verify(path)
            if Path(path).resolve() == self.store.path.resolve() and not failed:
                connection = sqlite3.connect(path)
                try:
                    phase = json.loads(
                        connection.execute(
                            "SELECT value_json FROM app_settings WHERE setting_key = 'phase'"
                        ).fetchone()[0]
                    )
                finally:
                    connection.close()
                if phase == "backup":
                    failed = True
                    raise CapsuleStoreError("forced post-replace verification failure")
            return info

        with patch.object(
            store_module,
            "_verify_database",
            side_effect=fail_once_on_replaced_database,
        ):
            with self.assertRaisesRegex(CapsuleStoreError, "original database preserved"):
                self.store.restore_backup(
                    backup["path"], expected_sha256=backup["sha256"]
                )

        self.assertTrue(failed)
        self.assertEqual(self._read_setting("phase"), "current")

    def test_corrupt_current_database_can_list_inspect_and_restore_backup(self) -> None:
        self._write_setting("phase", "backup")
        backup = self.store.create_backup("manual")
        corrupt_bytes = b"not a sqlite database\x00customer bytes"
        self.path.write_bytes(corrupt_bytes)

        rows = self.store.list_backups()
        listed = next(row for row in rows if row["path"] == backup["path"])
        self.assertTrue(listed["valid"])

        preview = self.store.inspect_restore(backup["path"])
        self.assertFalse(preview["current_database_available"])
        self.assertIsNone(preview["capsules_removed"])
        self.assertIsNone(preview["versions_removed"])
        self.assertIsNone(preview["product_usage_removed"])

        result = self.store.restore_backup(
            backup["path"], expected_sha256=backup["sha256"]
        )
        self.assertTrue(result["restored"])
        self.assertTrue(result["pre_restore_backup_is_raw"])
        self.assertEqual(
            Path(result["pre_restore_backup_path"]).read_bytes(), corrupt_bytes
        )
        self.assertEqual(self._read_setting("phase"), "backup")

    def test_corrupt_current_database_raw_bytes_are_restored_on_failure(self) -> None:
        self._write_setting("phase", "backup")
        backup = self.store.create_backup("manual")
        corrupt_bytes = b"broken active database\x00must survive"
        self.path.write_bytes(corrupt_bytes)
        real_verify = store_module._verify_database
        failed = False

        def fail_after_replacement(path: Path) -> dict[str, object]:
            nonlocal failed
            info = real_verify(path)
            if Path(path).resolve() == self.store.path.resolve() and not failed:
                failed = True
                raise CapsuleStoreError("forced post-replace verification failure")
            return info

        with patch.object(
            store_module, "_verify_database", side_effect=fail_after_replacement
        ):
            with self.assertRaisesRegex(
                CapsuleStoreError, "original database preserved"
            ):
                self.store.restore_backup(
                    backup["path"], expected_sha256=backup["sha256"]
                )

        self.assertTrue(failed)
        self.assertEqual(self.path.read_bytes(), corrupt_bytes)

    def test_restore_rejects_candidate_that_does_not_match_confirmed_backup(self) -> None:
        self._write_setting("phase", "expected")
        expected = self.store.create_backup("manual")
        self._write_setting("phase", "substituted")
        substituted = self.store.create_backup("manual")
        self._write_setting("phase", "current")

        copy_database = store_module._copy_database

        def substitute_candidate(_source: Path, destination: Path) -> None:
            copy_database(Path(substituted["path"]), destination)

        with patch.object(store_module, "_copy_database", substitute_candidate):
            with self.assertRaisesRegex(
                CapsuleStoreError, "restore failed; original database preserved"
            ):
                self.store.restore_backup(
                    expected["path"], expected_sha256=expected["sha256"]
                )

        self.assertEqual(self._read_setting("phase"), "current")

    def test_restore_rejects_corrupt_and_newer_schema_backups(self) -> None:
        self._write_setting("phase", "current")
        corrupt = self.root / "corrupt.sqlite3"
        corrupt.write_bytes(b"not sqlite")
        with self.assertRaises((CapsuleStoreError, sqlite3.DatabaseError)):
            self.store.inspect_restore(corrupt)
        self.assertEqual(self._read_setting("phase"), "current")

        valid = self.store.create_backup("manual")
        newer = self.root / "newer.sqlite3"
        shutil.copy2(valid["path"], newer)
        connection = sqlite3.connect(newer)
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
        connection.close()
        with self.assertRaises(SchemaVersionError):
            self.store.inspect_restore(newer)
        self.assertEqual(self._read_setting("phase"), "current")

    def test_restore_rejects_unknown_or_forged_schema_objects(self) -> None:
        backup = self.store.create_backup("manual")
        for variant in ("extra_table", "forged_trigger"):
            with self.subTest(variant=variant):
                tampered = self.root / f"{variant}.sqlite3"
                shutil.copy2(backup["path"], tampered)
                connection = sqlite3.connect(tampered)
                if variant == "extra_table":
                    connection.execute("CREATE TABLE sensitive_records(value TEXT)")
                else:
                    connection.executescript(
                        "DROP TRIGGER capsules_no_delete;"
                        "CREATE TRIGGER capsules_no_delete BEFORE DELETE ON capsules "
                        "BEGIN SELECT 1; END;"
                    )
                connection.commit()
                connection.close()

                with self.assertRaisesRegex(SchemaVersionError, "schema fingerprint"):
                    self.store.inspect_restore(tampered)

    def test_restore_rejects_rows_that_violate_restored_trigger_invariants(self) -> None:
        self._seed_project_and_active_version()
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO capability_groups VALUES (?, ?, ?, ?)",
                ("second_capability", "Second capability", NOW, NOW),
            )
            connection.execute(
                "INSERT INTO capsules VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "capsule-2",
                    "second_capability",
                    "second_role",
                    "default",
                    "computation",
                    "disabled",
                    None,
                    NOW,
                ),
            )
            version = list(
                connection.execute(
                    "SELECT * FROM capsule_versions WHERE version_id = 'version-1'"
                ).fetchone()
            )
            version[:3] = ["version-2", "capsule-2", 1]
            connection.execute(
                "INSERT INTO capsule_versions VALUES ("
                + ",".join("?" for _ in version)
                + ")",
                version,
            )
            connection.execute(
                "UPDATE capsules SET current_version_id = 'version-2' "
                "WHERE capsule_id = 'capsule-2'"
            )
            connection.execute(
                "INSERT INTO intake_runs ("
                "run_id, project_id, run_kind, status, extraction_contract_version, "
                "redaction_rules_version, security_rules_version, supervision_rules_version, "
                "validation_contract_version, canonicalization_version, "
                "legacy_source_path_hash, legacy_source_file_hash, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "legacy-run-restore",
                    None,
                    "legacy_import",
                    "completed",
                    "extraction.v1",
                    "redaction.v1",
                    "security.v1",
                    "supervision.v1",
                    "validation.v1",
                    1,
                    "legacy-path-hash",
                    "legacy-file-hash",
                    NOW,
                ),
            )
        backup = self.store.create_backup("manual")
        large_asset = b"x" * 1_048_576
        large_asset_sha = hashlib.sha256(large_asset).hexdigest()
        oversized_asset = b"x" * 2_097_152
        oversized_asset_sha = hashlib.sha256(oversized_asset).hexdigest()
        variants = {
            "manifest": (
                ("product_capsule_usage_manifest_consistent",),
                (
                    (
                        "INSERT INTO product_capsule_usage VALUES "
                        "('usage-a', 'product-1', 'manifest-a', 'capsule-1', "
                        "'version-1', 'quote_calculation', 'total_price', 'default', "
                        "'{\"kind\":\"general\"}', 'computation', ?)",
                        (NOW,),
                    ),
                    (
                        "INSERT INTO product_capsule_usage VALUES "
                        "('usage-b', 'product-1', 'manifest-b', 'capsule-1', "
                        "'version-1', 'quote_calculation', 'total_price', 'default', "
                        "'{\"kind\":\"general\"}', 'asset', ?)",
                        (NOW,),
                    ),
                ),
                "product_manifest_digest",
            ),
            "product_identity": (
                ("product_capsule_usage_matches_version",),
                (
                    (
                        "INSERT INTO product_capsule_usage VALUES "
                        "('usage-wrong-key', 'product-2', 'manifest', 'capsule-1', "
                        "'version-1', 'wrong_capability', 'total_price', 'default', "
                        "'{\"kind\":\"general\"}', 'computation', ?)",
                        (NOW,),
                    ),
                ),
                "product_capsule_usage",
            ),
            "source_canonical": (
                ("capsule_sources_canonical_relationship",),
                (
                    (
                        "INSERT INTO capsule_sources VALUES "
                        "('source-wrong-canonical', 'version-1', 'project-1', "
                        "'project:project-1', 'project', 'main.js', 'source-hash', "
                        "'different-canonical-hash', 'exact', ?)",
                        (NOW,),
                    ),
                ),
                "capsule_source_canonical",
            ),
            "canonical_hash": (
                ("capsule_versions_no_update",),
                (
                    (
                        "UPDATE capsule_versions SET canonical_hash = 'forged' "
                        "WHERE version_id = 'version-1'",
                        (),
                    ),
                ),
                "capsule_version_canonical_hash",
            ),
            "canonicalization_version": (
                ("capsule_versions_no_update",),
                (
                    (
                        "UPDATE capsule_versions SET canonicalization_version = 2 "
                        "WHERE version_id = 'version-1'",
                        (),
                    ),
                ),
                "capsule_version_canonicalization_version",
            ),
            "missing_current_version": (
                (),
                (
                    (
                        "UPDATE capsules SET current_version_id = NULL "
                        "WHERE capsule_id = 'capsule-2'",
                        (),
                    ),
                ),
                "capsule_current_version",
            ),
            "asset_size": (
                (),
                (
                    (
                        "INSERT INTO capsule_assets VALUES "
                        "('asset-size', 'version-1', 'asset-size.png', 'image/png', ?, 1, 1, 1, ?)",
                        (hashlib.sha256(b"xx").hexdigest(), b"xx"),
                    ),
                ),
                "capsule_asset_size",
            ),
            "asset_sha256": (
                (),
                (
                    (
                        "INSERT INTO capsule_assets VALUES "
                        "('asset-sha', 'version-1', 'asset-sha.png', 'image/png', ?, 1, 1, 1, ?)",
                        ("0" * 64, b"x"),
                    ),
                ),
                "capsule_asset_sha256",
            ),
            "asset_size_limit": (
                (),
                (
                    ("PRAGMA ignore_check_constraints = ON", ()),
                    (
                        "INSERT INTO capsule_assets VALUES "
                        "('asset-too-large', 'version-1', 'asset-too-large.png', "
                        "'image/png', ?, 2097152, 1, 1, ?)",
                        (oversized_asset_sha, oversized_asset),
                    ),
                ),
                "capsule_asset_size_limit",
            ),
            "asset_dimensions": (
                (),
                (
                    ("PRAGMA ignore_check_constraints = ON", ()),
                    (
                        "INSERT INTO capsule_assets VALUES "
                        "('asset-width', 'version-1', 'asset-width.png', 'image/png', "
                        "?, 1, -1, 1, ?)",
                        (hashlib.sha256(b"x").hexdigest(), b"x"),
                    ),
                ),
                "capsule_asset_pixels",
            ),
            "asset_total_size": (
                (),
                tuple(
                    (
                        "INSERT INTO capsule_assets VALUES "
                        f"('asset-total-{index}', 'version-1', 'asset-{index}.png', "
                        "'image/png', ?, 1048576, 1, 1, ?)",
                        (large_asset_sha, large_asset),
                    )
                    for index in range(6)
                ),
                "capsule_asset_total_size",
            ),
            "status_event": (
                ("capsule_status_events_match_state",),
                (
                    (
                        "INSERT INTO capsule_status_events VALUES "
                        "('event-invalid-static', 'capsule-1', 'enabled', 'active', "
                        "'active', 'version-1', 'invalid_history', ?)",
                        (NOW,),
                    ),
                ),
                "capsule_status_event",
            ),
            "status_event_version": (
                (
                    "capsule_status_events_version_belongs_to_capsule",
                    "capsule_status_events_match_state",
                ),
                (
                    (
                        "INSERT INTO capsule_status_events VALUES "
                        "('event-wrong-version', 'capsule-1', 'current_version_changed', "
                        "'active', 'active', 'version-2', 'invalid_history', ?)",
                        (NOW,),
                    ),
                ),
                "capsule_status_event",
            ),
            "current_version": (
                ("capsules_current_version_belongs_to_capsule",),
                (
                    (
                        "UPDATE capsules SET current_version_id = 'version-2' "
                        "WHERE capsule_id = 'capsule-1'",
                        (),
                    ),
                ),
                "capsule_current_version",
            ),
            "legacy_alias": (
                ("legacy_capsule_aliases_target_matches",),
                (
                    (
                        "INSERT INTO legacy_capsule_aliases VALUES "
                        "('alias-wrong-target', 'legacy-run-restore', 'legacy-file-hash', "
                        "'legacy-id', 'exact', 'capsule-1', 'version-2', "
                        "'invalid_history', ?)",
                        (NOW,),
                    ),
                ),
                "legacy_capsule_alias",
            ),
            "legacy_alias_contract": (
                ("legacy_capsule_aliases_contract",),
                (
                    (
                        "INSERT INTO legacy_capsule_aliases VALUES "
                        "('alias-no-target', 'legacy-run-restore', 'legacy-file-hash', "
                        "'legacy-id', 'exact', NULL, NULL, 'invalid_history', ?)",
                        (NOW,),
                    ),
                ),
                "legacy_capsule_alias",
            ),
            "legacy_alias_run": (
                ("legacy_capsule_aliases_contract",),
                (
                    (
                        "INSERT INTO legacy_capsule_aliases VALUES "
                        "('alias-wrong-run', 'run-1', 'legacy-file-hash', 'legacy-id', "
                        "'exact', 'capsule-1', 'version-1', 'invalid_history', ?)",
                        (NOW,),
                    ),
                ),
                "legacy_capsule_alias",
            ),
        }
        for variant, (trigger_names, statements, invariant) in variants.items():
            with self.subTest(variant=variant):
                tampered = self.root / f"restored_invariant_{variant}.sqlite3"
                shutil.copy2(backup["path"], tampered)
                connection = sqlite3.connect(tampered)
                trigger_sql = [
                    connection.execute(
                        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                        (trigger_name,),
                    ).fetchone()[0]
                    for trigger_name in trigger_names
                ]
                for trigger_name in trigger_names:
                    connection.execute(f"DROP TRIGGER {trigger_name}")
                for statement, parameters in statements:
                    connection.execute(statement, parameters)
                for statement in trigger_sql:
                    connection.execute(statement)
                connection.commit()
                self.assertEqual(
                    store_module._schema_rows(connection),
                    store_module._expected_schema_rows(),
                )
                connection.close()

                with self.assertRaisesRegex(
                    CapsuleStoreError, f"persistent data invariant failed: {invariant}"
                ):
                    self.store.inspect_restore(tampered)

    def test_backup_accepts_historical_product_usage_after_current_version_changes(self) -> None:
        self._seed_project_and_active_version()
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO product_capsule_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "historical-usage",
                    "historical-product",
                    "historical-manifest",
                    "capsule-1",
                    "version-1",
                    "quote_calculation",
                    "total_price",
                    "default",
                    '{"kind":"general"}',
                    "computation",
                    NOW,
                ),
            )
            version = list(
                connection.execute(
                    "SELECT * FROM capsule_versions WHERE version_id = 'version-1'"
                ).fetchone()
            )
            version[0] = "version-2"
            version[2] = 2
            connection.execute(
                "INSERT INTO capsule_versions VALUES ("
                + ",".join("?" for _ in version)
                + ")",
                version,
            )
            connection.execute(
                "UPDATE capsules SET current_version_id = 'version-2' "
                "WHERE capsule_id = 'capsule-1'"
            )
            connection.execute(
                "INSERT INTO capsule_status_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "event-version-2",
                    "capsule-1",
                    "current_version_changed",
                    "active",
                    "active",
                    "version-2",
                    "new_version",
                    NOW,
                ),
            )

        backup = self.store.create_backup("manual")
        inspected = self.store.inspect_restore(backup["path"])
        self.assertEqual(inspected["user_version"], 1)

    def test_backup_retention_preserves_manual_and_keeps_seven_auto(self) -> None:
        manual = [self.store.create_backup("manual") for _ in range(2)]
        for _ in range(8):
            self.store.create_backup("auto")
        backup_paths = [Path(item["path"]) for item in self.store.list_backups()]
        self.assertEqual(
            len([path for path in backup_paths if ".auto." in path.name]),
            7,
        )
        self.assertTrue(all(Path(item["path"]).is_file() for item in manual))

    def _seed_project_and_active_version(self) -> None:
        self.store.initialize()
        payload = canonical_payload()
        payload["assets"] = []
        canonical = canonicalize_capsule(payload)
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO source_roots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "root-1",
                    "single_project",
                    "/read/only/project",
                    "bound",
                    None,
                    None,
                    None,
                    0,
                    NOW,
                    NOW,
                ),
            )
            connection.execute(
                "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "project-1",
                    "root-1",
                    ".",
                    "index.html",
                    "Project",
                    "ready",
                    "signature",
                    "snapshot",
                    "inherit",
                    None,
                    None,
                    None,
                    0,
                    NOW,
                    NOW,
                ),
            )
            connection.execute(
                "INSERT INTO intake_runs ("
                "run_id, project_id, run_kind, status, extraction_contract_version, "
                "redaction_rules_version, security_rules_version, supervision_rules_version, "
                "validation_contract_version, canonicalization_version, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "run-1",
                    "project-1",
                    "refresh_project",
                    "completed",
                    "extraction.v1",
                    "redaction.v1",
                    "security.v1",
                    "supervision.v1",
                    "validation.v1",
                    1,
                    NOW,
                ),
            )
            connection.execute(
                "INSERT INTO capability_groups VALUES (?, ?, ?, ?)",
                ("quote_calculation", "Quote calculation", NOW, NOW),
            )
            connection.execute(
                "INSERT INTO capsules VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "capsule-1",
                    "quote_calculation",
                    "total_price",
                    "default",
                    "computation",
                    "disabled",
                    None,
                    NOW,
                ),
            )
            connection.execute(
                "INSERT INTO capsule_versions VALUES ("
                + ",".join("?" for _ in range(29))
                + ")",
                (
                    "version-1",
                    "capsule-1",
                    1,
                    "extraction.v1",
                    "{}",
                    "redaction.v1",
                    1,
                    canonical.sha256,
                    compact_json(canonical.payload["activation"]),
                    compact_json(canonical.payload["input_contract"]),
                    compact_json(canonical.payload["output_contract"]),
                    compact_json(canonical.payload["error_contract"]),
                    compact_json(canonical.payload["runtime_allowlist"]),
                    compact_json(canonical.payload["dom_scope"]),
                    compact_json(canonical.payload["usage_scope"]),
                    canonical.payload["html"],
                    canonical.payload["css"],
                    compact_json(canonical.payload["javascript_modules"]),
                    "{}",
                    "security.v1",
                    "supervision.v1",
                    "model",
                    "model-digest",
                    NOW,
                    "{}",
                    "response-hash",
                    "validation.v1",
                    "{}",
                    NOW,
                ),
            )
            connection.execute(
                "UPDATE capsules SET current_version_id = ?, status = ? WHERE capsule_id = ?",
                ("version-1", "active", "capsule-1"),
            )

    def _write_setting(self, key: str, value: str) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO app_settings(setting_key, value_json, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(setting_key) DO UPDATE SET "
                "value_json = excluded.value_json, updated_at = excluded.updated_at",
                (key, json.dumps(value), NOW),
            )
            self.store.bump_revision(connection)

    def _read_setting(self, key: str) -> str:
        return self._read_setting_from(self.store.path, key)

    @staticmethod
    def _read_setting_from(path: Path, key: str) -> str:
        connection = sqlite3.connect(path)
        try:
            row = connection.execute(
                "SELECT value_json FROM app_settings WHERE setting_key = ?", (key,)
            ).fetchone()
            assert row is not None
            return json.loads(row[0])
        finally:
            connection.close()


class CanonicalizationV1Test(unittest.TestCase):
    def test_documented_empty_fixed_vector(self) -> None:
        result = canonicalize_capsule(
            {
                "capability_kind": "computation",
                "activation": {},
                "input_contract": {
                    "schema": "data_contract.v1",
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additional_properties": False,
                },
                "output_contract": {
                    "schema": "data_contract.v1",
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additional_properties": False,
                },
                "error_contract": {"schema": "error_contract.v1", "errors": {}},
                "runtime_allowlist": [],
                "dom_scope": {
                    "selectors": [],
                    "classes": [],
                    "attributes": [],
                    "events": [],
                },
                "usage_scope": {},
                "html": "",
                "css": "",
                "javascript_modules": [],
                "assets": [],
            }
        )
        self.assertEqual(
            result.sha256,
            "b4b152b0eae2d1eddb7fbd3d237e8b1bf290b53c79d8fb441e48ae6cebaa1c32",
        )

    def test_fixed_vector_is_stable_across_order_and_newline_variations(self) -> None:
        first_payload = canonical_payload()
        second_payload = copy.deepcopy(first_payload)
        second_payload["runtime_allowlist"] = ["math", "json"]
        second_payload["dom_scope"]["selectors"].reverse()
        second_payload["javascript_modules"].reverse()
        second_payload["assets"].reverse()
        second_payload["html"] = second_payload["html"].replace("\r\n", "\n").replace(
            "\r", "\n"
        )
        second_payload["css"] = second_payload["css"].replace("\r\n", "\n")
        for module in second_payload["javascript_modules"]:
            module["source"] = module["source"].replace("\r\n", "\n")

        first = canonicalize_capsule(first_payload)
        second = canonicalize_capsule(second_payload)

        self.assertEqual(first.json_bytes, second.json_bytes)
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(
            first.sha256,
            "b7de0f35cb52772740123b107f76ee67cd69f757a8cb585d2cfe0fa8b8278201",
        )

    def test_code_or_scope_change_changes_hash(self) -> None:
        base = canonicalize_capsule(canonical_payload()).sha256
        code_changed = canonical_payload()
        code_changed["javascript_modules"][1]["source"] += " "
        scope_changed = canonical_payload()
        scope_changed["usage_scope"] = {
            "kind": "brand_limited",
            "brand_profile_id": "brand-id",
            "brand_profile_digest": "brand-digest",
        }
        self.assertNotEqual(base, canonicalize_capsule(code_changed).sha256)
        self.assertNotEqual(base, canonicalize_capsule(scope_changed).sha256)

    def test_rejects_float_bad_path_and_unknown_outer_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "float"):
            payload = canonical_payload()
            payload["activation"]["timeout"] = 1.5
            canonicalize_capsule(payload)
        with self.assertRaisesRegex(ValueError, "logical path"):
            payload = canonical_payload()
            payload["javascript_modules"][0]["path"] = "../escape.js"
            canonicalize_capsule(payload)
        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            payload = canonical_payload()
            payload["capability_key"] = "not-hashed"
            canonicalize_capsule(payload)

    def test_rejects_normalized_json_key_collision(self) -> None:
        payload = canonical_payload()
        payload["usage_scope"] = {"name\r": "first", "name\n": "second"}

        with self.assertRaisesRegex(ValueError, "control character in key"):
            canonicalize_capsule(payload)

    def test_semantic_strings_are_not_newline_normalized_into_false_duplicates(self) -> None:
        first = canonical_payload()
        second = copy.deepcopy(first)
        first["input_contract"]["properties"]["label"] = {
            "type": "string",
            "enum": ["a\r"],
        }
        second["input_contract"]["properties"]["label"] = {
            "type": "string",
            "enum": ["a\n"],
        }

        self.assertNotEqual(
            canonicalize_capsule(first).sha256,
            canonicalize_capsule(second).sha256,
        )

        bad_path = canonical_payload()
        bad_path["javascript_modules"][0]["path"] = "lib/a\r.js"
        with self.assertRaisesRegex(ValueError, "logical path"):
            canonicalize_capsule(bad_path)


if __name__ == "__main__":
    unittest.main()
