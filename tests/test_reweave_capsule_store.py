"""SQLite capsule warehouse schema, migration, backup, and recovery tests."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
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


def schema_fingerprint_sha256(
    rows: tuple[tuple[str, str, str, str], ...]
) -> str:
    payload = json.dumps(
        rows,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def typed_database_snapshot(
    path: Path,
    tables: set[str] | frozenset[str],
    columns_by_table: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, tuple[tuple[str, ...], list[tuple[object, ...]]]]:
    connection = sqlite3.connect(path)
    try:
        result: dict[str, tuple[tuple[str, ...], list[tuple[object, ...]]]] = {}
        for table in sorted(tables):
            quoted_table = '"' + table.replace('"', '""') + '"'
            info = connection.execute(f"PRAGMA table_info({quoted_table})").fetchall()
            columns = (
                columns_by_table[table]
                if columns_by_table is not None
                else tuple(str(row[1]) for row in info)
            )
            primary_key = tuple(
                str(row[1])
                for row in sorted(info, key=lambda item: int(item[5]))
                if int(row[5]) > 0
            )
            projection = ", ".join(
                f'"{column}", typeof("{column}")' for column in columns
            )
            order_by = ", ".join(f'"{column}"' for column in primary_key)
            rows = [
                tuple(row)
                for row in connection.execute(
                    f"SELECT {projection} FROM {quoted_table} ORDER BY {order_by}"
                )
            ]
            result[table] = (columns, rows)
        return result
    finally:
        connection.close()


def scope_snapshot_sha256(
    modules: list[dict[str, object]], symlinks: list[dict[str, str]]
) -> str:
    payload = json.dumps(
        {
            "version": "javascript_scope_snapshot.v1",
            "javascript_modules": modules,
            "symlinks": symlinks,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
        self.store.initialize()
        self.store.migrate_v1_to_v2()
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

    def test_list_backups_isolates_invalid_directory_entries(self) -> None:
        backup = self.store.create_backup("manual")
        backup_path = Path(backup["path"])
        backup_root = backup_path.parent
        directory = backup_root / "capsule_warehouse.manual.directory.sqlite3"
        directory.mkdir()
        invalid_paths = [directory]
        if hasattr(os, "symlink"):
            broken = backup_root / "capsule_warehouse.manual.broken.sqlite3"
            alias = backup_root / "capsule_warehouse.manual.alias.sqlite3"
            try:
                broken.symlink_to(backup_root / "missing.sqlite3")
                alias.symlink_to(backup_path)
            except OSError:
                pass
            else:
                invalid_paths.extend((broken, alias))

        rows = {Path(row["path"]): row for row in self.store.list_backups()}

        self.assertTrue(rows[backup_path]["valid"])
        for path in invalid_paths:
            self.assertFalse(rows[path]["valid"])
            self.assertIn("error", rows[path])

    def test_corrupt_current_database_raw_bytes_are_restored_on_failure(self) -> None:
        self.store.initialize()
        self.store.migrate_v1_to_v2()
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
        self.store.initialize()
        self.store.migrate_v1_to_v2()
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

    def test_invalid_regular_backups_do_not_evict_valid_retention_set(self) -> None:
        valid = [self.store.create_backup("upgrade") for _ in range(3)]
        backup_root = Path(valid[0]["path"]).parent
        invalid = []
        for index in range(3):
            path = backup_root / (
                f"capsule_warehouse.upgrade.99999999T99999999999{index}Z."
                f"invalid{index}.sqlite3"
            )
            path.write_bytes(b"not a sqlite database")
            invalid.append(path)

        self.store._apply_retention("upgrade")

        self.assertTrue(all(Path(item["path"]).is_file() for item in valid))
        self.assertTrue(all(path.is_file() for path in invalid))
        rows = {Path(row["path"]): row for row in self.store.list_backups()}
        self.assertTrue(all(rows[Path(item["path"])]["valid"] for item in valid))
        self.assertTrue(all(not rows[path]["valid"] for path in invalid))

    def test_v1_fingerprint_is_frozen_and_v2_schema_is_exact(self) -> None:
        self.assertEqual(
            schema_fingerprint_sha256(store_module._expected_schema_rows(1)),
            "31ca94b97ad9e6539f9d62f5938759232aa1a6f3cdac49950962f03555b48bd1",
        )
        self.assertEqual(
            schema_fingerprint_sha256(store_module._expected_schema_rows(2)),
            "2f5c245eee172d57abc065d1c63ad76e11925aec6a021d586a9384c4cbde2ada",
        )

        self.store.initialize()
        v2_path = self.root / "fresh-v2.sqlite3"
        connection = sqlite3.connect(v2_path)
        connection.executescript(
            "PRAGMA foreign_keys=ON;\n"
            + store_module.SCHEMA_SQL_V2
            + "\nPRAGMA user_version=2;"
        )
        connection.close()
        store_module._prepare_database_file(v2_path)
        info = store_module._verify_database(v2_path, expected_version=2)
        self.assertEqual(info["user_version"], 2)

        connection = sqlite3.connect(v2_path)
        counts = dict(
            connection.execute(
                "SELECT type, count(*) FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' GROUP BY type"
            )
        )
        self.assertEqual(counts, {"index": 11, "table": 15, "trigger": 34})
        self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        with self.assertRaises(SchemaVersionError):
            store_module._assert_schema_objects(connection, expected_version=1)
        connection.close()
        connection = sqlite3.connect(self.path)
        with self.assertRaises(SchemaVersionError):
            store_module._assert_schema_objects(connection, expected_version=2)
        connection.close()

        variants = {
            "extra_table": "CREATE TABLE unexpected(value TEXT)",
            "extra_view": "CREATE VIEW unexpected_view AS SELECT 1 AS value",
            "missing_index": "DROP INDEX idx_projects_js_scope",
            "forged_partial_index": (
                "DROP INDEX idx_projects_js_scope;"
                "CREATE UNIQUE INDEX idx_projects_js_scope "
                "ON projects(source_root_id, project_relpath)"
            ),
            "missing_trigger": "DROP TRIGGER project_file_index_owner_insert",
            "forged_trigger": (
                "DROP TRIGGER project_file_index_owner_insert;"
                "CREATE TRIGGER project_file_index_owner_insert "
                "BEFORE INSERT ON project_file_index BEGIN SELECT 1; END"
            ),
            "forged_table": (
                "DROP TABLE project_file_index;"
                "CREATE TABLE project_file_index(value TEXT)"
            ),
        }
        for variant, mutation_sql in variants.items():
            with self.subTest(variant=variant):
                tampered = self.root / f"v2-{variant}.sqlite3"
                shutil.copy2(v2_path, tampered)
                connection = sqlite3.connect(tampered)
                connection.executescript(mutation_sql)
                connection.commit()
                connection.close()
                with self.assertRaisesRegex(
                    SchemaVersionError, "schema fingerprint|incomplete schema"
                ):
                    store_module._verify_database(tampered, expected_version=2)

    def test_explicit_v1_to_v2_migration_preserves_complete_v1_data(self) -> None:
        asset_content = b"\x89PNG\r\n\x1a\nlegacy-pixel"
        self._seed_project_and_active_version(asset_content=asset_content)
        with self.store.transaction() as connection:
            canonical_hash = connection.execute(
                "SELECT canonical_hash FROM capsule_versions WHERE version_id = 'version-1'"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO app_settings VALUES (?, ?, ?)",
                ("migration-marker", '"before"', NOW),
            )
            connection.execute(
                "INSERT INTO review_items ("
                "review_id, run_id, project_id, candidate_id, candidate_status, "
                "source_relpath, source_location_json, source_hash, redaction_rules_version, "
                "sanitized_candidate_json, redaction_summary_json, sensitivity_decision, "
                "sensitivity_decided_at, created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "review-migration",
                    "run-1",
                    "project-1",
                    "candidate-migration",
                    "waiting_user",
                    "main.js",
                    "{}",
                    "source-hash",
                    "redaction.v1",
                    "{}",
                    "{}",
                    "confirm_safe_redaction",
                    NOW,
                    NOW,
                    NOW,
                ),
            )
            connection.execute(
                "INSERT INTO capsule_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "source-migration",
                    "version-1",
                    "project-1",
                    "project:project-1",
                    "project",
                    "main.js",
                    "source-hash",
                    canonical_hash,
                    "exact",
                    NOW,
                ),
            )
            connection.execute(
                "INSERT INTO capsule_status_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "event-migration",
                    "capsule-1",
                    "current_version_changed",
                    "active",
                    "active",
                    "version-1",
                    "migration_fixture",
                    NOW,
                ),
            )
            connection.execute(
                "INSERT INTO product_capsule_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "usage-migration",
                    "product-migration",
                    "manifest-migration",
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
            connection.execute(
                "INSERT INTO intake_runs ("
                "run_id, run_kind, status, extraction_contract_version, "
                "redaction_rules_version, security_rules_version, supervision_rules_version, "
                "validation_contract_version, canonicalization_version, "
                "legacy_source_file_hash, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "legacy-run-migration",
                    "legacy_import",
                    "completed",
                    "extraction.v1",
                    "redaction.v1",
                    "security.v1",
                    "supervision.v1",
                    "validation.v1",
                    1,
                    "legacy-file-hash",
                    NOW,
                ),
            )
            connection.execute(
                "INSERT INTO legacy_capsule_aliases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "alias-migration",
                    "legacy-run-migration",
                    "legacy-file-hash",
                    "legacy-capsule",
                    "exact",
                    "capsule-1",
                    "version-1",
                    "migration_fixture",
                    NOW,
                ),
            )

        before = typed_database_snapshot(self.path, store_module._TABLES)
        before_columns = {table: value[0] for table, value in before.items()}
        source_sha256 = store_module._sha256_file(self.path)
        result = self.store.migrate_v1_to_v2()

        self.assertTrue(result["migrated"])
        self.assertEqual(result["from_version"], 1)
        self.assertEqual(result["to_version"], 2)
        self.assertEqual(result["source_sha256"], source_sha256)
        self.assertNotEqual(result["target_sha256"], source_sha256)
        after = typed_database_snapshot(
            self.path, store_module._TABLES, before_columns
        )
        self.assertEqual(after, before)

        upgrade_backup = Path(result["upgrade_backup_path"])
        self.assertTrue(upgrade_backup.is_file())
        self.assertEqual(
            store_module._verify_database(
                upgrade_backup, expected_version=1
            )["user_version"],
            1,
        )
        self.assertEqual(
            store_module._sha256_file(upgrade_backup),
            result["upgrade_backup_sha256"],
        )
        if os.name != "nt":
            self.assertEqual(upgrade_backup.stat().st_mode & 0o777, 0o600)

        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(
                [
                    tuple(row)
                    for row in connection.execute(
                        "SELECT DISTINCT source_type FROM projects"
                    )
                ],
                [("static_web",)],
            )
            self.assertEqual(
                tuple(
                    connection.execute(
                        "SELECT enum_decision, enum_decision_binding_sha256, enum_decided_at "
                        "FROM review_items WHERE review_id = 'review-migration'"
                    ).fetchone()
                ),
                (None, None, None),
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM project_file_index").fetchone()[0],
                0,
            )
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

        with self.store.transaction() as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "capsule_version_immutable"):
                connection.execute(
                    "UPDATE capsule_versions SET extraction_summary_json = '{}' "
                    "WHERE version_id = 'version-1'"
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "capsule_delete_forbidden"):
                connection.execute("DELETE FROM capsules WHERE capsule_id = 'capsule-1'")
            append_only_rows = (
                ("capsule_versions", "version_id", "version-1", "created_at"),
                ("capsule_sources", "source_link_id", "source-migration", "read_at"),
                ("capsule_assets", "asset_id", "asset-1", "width"),
                ("capsule_status_events", "event_id", "event-migration", "reason_code"),
                ("product_capsule_usage", "usage_id", "usage-migration", "generated_at"),
                ("legacy_capsule_aliases", "alias_id", "alias-migration", "reason_code"),
            )
            for table, id_column, row_id, mutable_column in append_only_rows:
                with self.subTest(table=table, operation="update"):
                    with self.assertRaises(sqlite3.IntegrityError):
                        connection.execute(
                            f"UPDATE {table} SET {mutable_column} = ? "
                            f"WHERE {id_column} = ?",
                            (NOW, row_id),
                        )
                with self.subTest(table=table, operation="delete"):
                    with self.assertRaises(sqlite3.IntegrityError):
                        connection.execute(
                            f"DELETE FROM {table} WHERE {id_column} = ?",
                            (row_id,),
                        )

        target_sha256 = store_module._sha256_file(self.path)
        backup_count = len(list((self.path.parent / "backups").glob("*.upgrade.*.sqlite3")))
        second = self.store.migrate_v1_to_v2()
        self.assertFalse(second["migrated"])
        self.assertEqual(store_module._sha256_file(self.path), target_sha256)
        self.assertEqual(
            len(list((self.path.parent / "backups").glob("*.upgrade.*.sqlite3"))),
            backup_count,
        )
        self.assertEqual(
            list(self.path.parent.glob(".capsule_warehouse.sqlite3.v1-rollback.*")),
            [],
        )

    def test_migration_faults_preserve_v1_bytes_and_cas_does_not_overwrite(self) -> None:
        self._write_setting("phase", "v1")
        source_bytes = self.path.read_bytes()

        with patch.object(
            store_module,
            "_create_v2_candidate",
            side_effect=CapsuleStoreError("forced candidate failure"),
        ):
            with self.assertRaisesRegex(CapsuleStoreError, "original database preserved"):
                self.store.migrate_v1_to_v2()
        self.assertEqual(self.path.read_bytes(), source_bytes)
        self.assertEqual(
            store_module._verify_database(
                self.path, expected_version=1
            )["user_version"],
            1,
        )

        real_verify = store_module._verify_database
        failed_after_replace = False

        def fail_after_replace(
            path: Path, *, expected_version: int | None = None
        ) -> dict[str, object]:
            nonlocal failed_after_replace
            info = real_verify(path, expected_version=expected_version)
            if (
                Path(path).resolve() == self.path.resolve()
                and info["user_version"] == 2
                and not failed_after_replace
            ):
                failed_after_replace = True
                raise CapsuleStoreError("forced post-replace migration failure")
            return info

        with patch.object(
            store_module, "_verify_database", side_effect=fail_after_replace
        ):
            with self.assertRaisesRegex(CapsuleStoreError, "original database preserved"):
                self.store.migrate_v1_to_v2()
        self.assertTrue(failed_after_replace)
        self.assertEqual(self.path.read_bytes(), source_bytes)
        self.assertEqual(
            list(self.path.parent.glob(".capsule_warehouse.sqlite3.v2-candidate.*")),
            [],
        )
        self.assertEqual(
            list(self.path.parent.glob(".capsule_warehouse.sqlite3.v1-rollback.*")),
            [],
        )

        real_create_candidate = store_module._create_v2_candidate

        def create_candidate_then_change_source(source: Path, target: Path) -> None:
            real_create_candidate(source, target)
            connection = sqlite3.connect(self.path)
            connection.execute(
                "INSERT INTO app_settings VALUES (?, ?, ?)",
                ("external-change", '"kept"', NOW),
            )
            connection.commit()
            connection.close()

        with patch.object(
            store_module,
            "_create_v2_candidate",
            side_effect=create_candidate_then_change_source,
        ):
            with self.assertRaisesRegex(CapsuleStoreError, "changed and was not replaced"):
                self.store.migrate_v1_to_v2()
        self.assertEqual(
            store_module._verify_database(
                self.path, expected_version=1
            )["user_version"],
            1,
        )
        self.assertEqual(self._read_setting("external-change"), "kept")

        sidecar = Path(f"{self.path}-wal")
        sidecar.write_bytes(b"unexpected")
        bytes_before_sidecar_rejection = self.path.read_bytes()
        try:
            with self.assertRaisesRegex(CapsuleStoreError, "sidecar"):
                self.store.migrate_v1_to_v2()
        finally:
            sidecar.unlink()
        self.assertEqual(self.path.read_bytes(), bytes_before_sidecar_rejection)

    def test_migration_barrier_rejects_reentrant_write_at_replace_boundary(self) -> None:
        self._write_setting("phase", "before")
        real_fsync_directory = store_module._fsync_directory
        attempted = False

        def probe_replace_boundary(path: Path) -> None:
            nonlocal attempted
            if Path(path).resolve() == self.path.parent.resolve() and not attempted:
                attempted = True
                with self.assertRaisesRegex(
                    CapsuleStoreError, "exclusive warehouse operation"
                ):
                    with self.store.transaction() as connection:
                        connection.execute(
                            "INSERT INTO app_settings VALUES (?, ?, ?)",
                            ("late-write", '"lost"', NOW),
                        )
            real_fsync_directory(path)

        with patch.object(
            store_module, "_fsync_directory", side_effect=probe_replace_boundary
        ):
            result = self.store.migrate_v1_to_v2()

        self.assertTrue(attempted)
        self.assertTrue(result["migrated"])
        with self.store.read_connection() as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT value_json FROM app_settings WHERE setting_key = 'late-write'"
                ).fetchone()
            )

        errors: list[BaseException] = []
        started = threading.Event()

        def write_after_barrier() -> None:
            started.set()
            try:
                with self.store.transaction() as connection:
                    connection.execute(
                        "INSERT INTO app_settings VALUES (?, ?, ?)",
                        ("after-barrier", '"kept"', NOW),
                    )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        thread = threading.Thread(target=write_after_barrier)
        thread.start()
        self.assertTrue(started.wait(1))
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self._read_setting("after-barrier"), "kept")

    def test_migration_fault_matrix_is_atomic_and_cleans_temporary_files(self) -> None:
        real_copy_file_bytes = store_module._copy_file_bytes
        real_fsync_file = store_module._fsync_file
        real_replace = os.replace

        def rollback_copy_failure(source: Path, target: Path) -> None:
            if "v1-rollback" in Path(target).name:
                raise OSError("forced rollback copy failure")
            real_copy_file_bytes(source, target)

        def candidate_fsync_failure(path: Path) -> None:
            if "v2-candidate" in Path(path).name:
                raise OSError("forced candidate fsync failure")
            real_fsync_file(path)

        def candidate_replace_failure(source: Path, target: Path) -> None:
            if "v2-candidate" in Path(source).name:
                raise OSError("forced candidate replace failure")
            real_replace(source, target)

        cases = {
            "upgrade_backup": (
                store_module.CapsuleWarehouseStore,
                "_create_backup_locked",
                CapsuleStoreError("forced upgrade backup failure"),
            ),
            "rollback_copy": (
                store_module,
                "_copy_file_bytes",
                rollback_copy_failure,
            ),
            "candidate_sql": (
                store_module,
                "_create_v2_candidate",
                sqlite3.OperationalError("forced candidate SQL failure"),
            ),
            "candidate_base_exception": (
                store_module,
                "_create_v2_candidate",
                KeyboardInterrupt("forced candidate interruption"),
            ),
            "candidate_fsync": (
                store_module,
                "_fsync_file",
                candidate_fsync_failure,
            ),
            "candidate_replace": (
                os,
                "replace",
                candidate_replace_failure,
            ),
        }
        for name, (target, attribute, effect) in cases.items():
            with self.subTest(fault=name):
                store = self._new_v1_store(f"migration-fault-{name}")
                before = store.path.read_bytes()
                with patch.object(target, attribute, side_effect=effect):
                    with self.assertRaises(CapsuleStoreError):
                        store.migrate_v1_to_v2()
                self.assertEqual(store.path.read_bytes(), before)
                self.assertEqual(
                    store_module._verify_database(
                        store.path, expected_version=1
                    )["user_version"],
                    1,
                )
                self.assertEqual(
                    list(store.path.parent.glob(".*.v1-rollback.*")), []
                )
                self.assertEqual(
                    list(store.path.parent.glob(".*.v2-candidate.*")), []
                )

    def test_migration_recovery_failure_preserves_verified_rollback_evidence(self) -> None:
        store = self._new_v1_store("migration-recovery-failure")
        source_sha256 = store_module._sha256_file(store.path)
        real_verify = store_module._verify_database
        real_replace = os.replace
        failed_after_replace = False

        def fail_post_replace(
            path: Path, *, expected_version: int | None = None
        ) -> dict[str, object]:
            nonlocal failed_after_replace
            info = real_verify(path, expected_version=expected_version)
            if (
                Path(path).resolve() == store.path.resolve()
                and info["user_version"] == 2
                and not failed_after_replace
            ):
                failed_after_replace = True
                raise CapsuleStoreError("forced post-replace failure")
            return info

        def fail_recovery_replace(source: Path, target: Path) -> None:
            if "migration-recovery" in Path(source).name:
                raise OSError("forced recovery replace failure")
            real_replace(source, target)

        with patch.object(
            store_module, "_verify_database", side_effect=fail_post_replace
        ), patch.object(os, "replace", side_effect=fail_recovery_replace):
            with self.assertRaisesRegex(
                CapsuleStoreError, "rollback preserved"
            ):
                store.migrate_v1_to_v2()
        self.assertTrue(failed_after_replace)
        rollback_paths = list(store.path.parent.glob(".*.v1-rollback.*"))
        self.assertEqual(len(rollback_paths), 1)
        self.assertEqual(
            store_module._sha256_file(rollback_paths[0]), source_sha256
        )

    def test_restore_uses_one_private_digest_bound_backup_snapshot(self) -> None:
        self._write_setting("phase", "confirmed-a")
        backup_a = self.store.create_backup("manual")
        backup_a_path = Path(backup_a["path"])
        backup_a_bytes = backup_a_path.read_bytes()
        self._write_setting("phase", "other-b")
        backup_b = self.store.create_backup("manual")
        backup_b_path = Path(backup_b["path"])

        real_copy_file_bytes = store_module._copy_file_bytes
        copied = False

        def mutate_live_backup_after_snapshot(source: Path, target: Path) -> None:
            nonlocal copied
            real_copy_file_bytes(source, target)
            if (
                Path(source).resolve() == backup_a_path.resolve()
                and "confirmed-backup" in Path(target).name
                and not copied
            ):
                copied = True
                shutil.copy2(backup_b_path, backup_a_path)

        try:
            with patch.object(
                store_module,
                "_copy_file_bytes",
                side_effect=mutate_live_backup_after_snapshot,
            ):
                result = self.store.restore_backup(
                    backup_a_path, expected_sha256=backup_a["sha256"]
                )
        finally:
            backup_a_path.write_bytes(backup_a_bytes)
        self.assertTrue(copied)
        self.assertTrue(result["restored"])
        self.assertEqual(self._read_setting("phase"), "confirmed-a")

        self._write_setting("phase", "still-current")

        def substitute_before_snapshot(source: Path, target: Path) -> None:
            if (
                Path(source).resolve() == backup_a_path.resolve()
                and "confirmed-backup" in Path(target).name
            ):
                real_copy_file_bytes(backup_b_path, target)
            else:
                real_copy_file_bytes(source, target)

        with patch.object(
            store_module,
            "_copy_file_bytes",
            side_effect=substitute_before_snapshot,
        ):
            with self.assertRaisesRegex(CapsuleStoreError, "digest"):
                self.store.restore_backup(
                    backup_a_path, expected_sha256=backup_a["sha256"]
                )
        self.assertEqual(self._read_setting("phase"), "still-current")

    def test_v2_persistent_invariants_guard_commit_and_open(self) -> None:
        store = self._new_v2_store("v2-invariant-commit")
        with self.assertRaisesRegex(
            CapsuleStoreError, "javascript_scope_snapshot"
        ):
            with store.transaction() as connection:
                self._insert_unhashed_js_index(connection)

        with store.read_connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM project_file_index"
                ).fetchone()[0],
                0,
            )

        connection = sqlite3.connect(store.path)
        connection.execute("PRAGMA foreign_keys=ON")
        self._insert_unhashed_js_index(connection)
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(
            CapsuleStoreError, "javascript_scope_snapshot"
        ):
            store.initialize()

    def test_v1_backup_is_migrated_only_in_v2_restore_candidate(self) -> None:
        self._write_setting("phase", "v1-backup")
        backup = self.store.create_backup("manual")
        backup_path = Path(backup["path"])
        backup_bytes = backup_path.read_bytes()

        self.store.migrate_v1_to_v2()
        self._write_setting("phase", "v2-current")
        v2_backup = self.store.create_backup("manual")
        listed = {
            Path(item["path"]): item for item in self.store.list_backups()
        }
        self.assertEqual(listed[backup_path]["user_version"], 1)
        self.assertEqual(listed[Path(v2_backup["path"])]["user_version"], 2)

        preview = self.store.inspect_restore(backup_path)
        self.assertEqual(preview["user_version"], 1)
        self.assertEqual(preview["current_user_version"], 2)
        result = self.store.restore_backup(
            backup_path, expected_sha256=backup["sha256"]
        )
        self.assertTrue(result["restored"])
        self.assertEqual(result["restored_user_version"], 2)
        self.assertEqual(self._read_setting("phase"), "v1-backup")
        self.assertEqual(backup_path.read_bytes(), backup_bytes)
        self.assertEqual(
            store_module._verify_database(
                Path(result["pre_restore_backup_path"]), expected_version=2
            )["user_version"],
            2,
        )

        self._write_setting("phase", "v2-before-failed-restore")
        current_snapshot = typed_database_snapshot(
            self.path, set(store_module._TABLES) | {"project_file_index"}
        )
        real_verify = store_module._verify_database
        failed_after_restore = False

        def fail_restored_v1_candidate(
            path: Path, *, expected_version: int | None = None
        ) -> dict[str, object]:
            nonlocal failed_after_restore
            info = real_verify(path, expected_version=expected_version)
            if Path(path).resolve() == self.path.resolve() and not failed_after_restore:
                connection = sqlite3.connect(path)
                value = connection.execute(
                    "SELECT value_json FROM app_settings WHERE setting_key = 'phase'"
                ).fetchone()[0]
                connection.close()
                if json.loads(value) == "v1-backup":
                    failed_after_restore = True
                    raise CapsuleStoreError("forced migrated restore failure")
            return info

        with patch.object(
            store_module, "_verify_database", side_effect=fail_restored_v1_candidate
        ):
            with self.assertRaisesRegex(CapsuleStoreError, "original database preserved"):
                self.store.restore_backup(
                    backup_path, expected_sha256=backup["sha256"]
                )
        self.assertTrue(failed_after_restore)
        self.assertEqual(
            typed_database_snapshot(
                self.path, set(store_module._TABLES) | {"project_file_index"}
            ),
            current_snapshot,
        )
        self.assertEqual(
            store_module._verify_database(
                self.path, expected_version=2
            )["user_version"],
            2,
        )
        self.assertEqual(backup_path.read_bytes(), backup_bytes)

    def test_corrupt_v2_database_restores_v1_backup_as_v2(self) -> None:
        self._write_setting("phase", "v1-backup")
        backup = self.store.create_backup("manual")
        self.store.migrate_v1_to_v2()
        self.assertEqual(
            store_module._verify_database(self.path, expected_version=2)["user_version"],
            2,
        )
        corrupt_bytes = b"corrupt v2 database\x00must be retained"
        self.path.write_bytes(corrupt_bytes)

        result = self.store.restore_backup(
            backup["path"], expected_sha256=backup["sha256"]
        )

        self.assertTrue(result["restored"])
        self.assertEqual(result["restored_user_version"], 2)
        self.assertEqual(self._read_setting("phase"), "v1-backup")
        self.assertEqual(
            store_module._verify_database(self.path, expected_version=2)["user_version"],
            2,
        )
        self.assertTrue(result["pre_restore_backup_is_raw"])
        self.assertEqual(
            Path(result["pre_restore_backup_path"]).read_bytes(), corrupt_bytes
        )

    def test_v2_source_index_and_enum_constraints_fail_closed(self) -> None:
        self.store.initialize()
        self.store.migrate_v1_to_v2()
        module_hash = "a" * 64
        snapshot_hash = scope_snapshot_sha256(
            [{"path": "src/main.js", "size": 4, "sha256": module_hash}],
            [{"path": "vendor/link.js"}],
        )

        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO source_roots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "root-v2",
                    "project_collection",
                    "/read/only/v2",
                    "bound",
                    None,
                    None,
                    None,
                    0,
                    NOW,
                    NOW,
                ),
            )
            project_sql = (
                "INSERT INTO projects ("
                "project_id, source_root_id, source_type, project_relpath, entry_relpath, "
                "display_name, project_state, discovery_signature, last_snapshot_hash, "
                "brand_mode, brand_profile_id, brand_profile_json, brand_profile_digest, "
                "brand_profile_version, created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )
            connection.execute(
                project_sql,
                (
                    "static-v2",
                    "root-v2",
                    "static_web",
                    "web",
                    "index.html",
                    "Static",
                    "ready",
                    "static-signature",
                    None,
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
                project_sql,
                (
                    "js-v2",
                    "root-v2",
                    "javascript_computation_source",
                    "javascript",
                    None,
                    "JavaScript",
                    "ready",
                    "js-signature",
                    None,
                    "inherit",
                    None,
                    None,
                    None,
                    0,
                    NOW,
                    NOW,
                ),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    project_sql,
                    (
                        "static-no-entry",
                        "root-v2",
                        "static_web",
                        "bad-static",
                        None,
                        "Bad",
                        "ready",
                        "bad",
                        None,
                        "inherit",
                        None,
                        None,
                        None,
                        0,
                        NOW,
                        NOW,
                    ),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    project_sql,
                    (
                        "duplicate-static-entry",
                        "root-v2",
                        "static_web",
                        "web",
                        "index.html",
                        "Duplicate Static",
                        "ready",
                        "duplicate-static",
                        None,
                        "inherit",
                        None,
                        None,
                        None,
                        0,
                        NOW,
                        NOW,
                    ),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    project_sql,
                    (
                        "duplicate-js-scope",
                        "root-v2",
                        "javascript_computation_source",
                        "javascript",
                        None,
                        "Duplicate",
                        "ready",
                        "duplicate",
                        None,
                        "inherit",
                        None,
                        None,
                        None,
                        0,
                        NOW,
                        NOW,
                    ),
                )
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "project_source_identity_immutable"
            ):
                connection.execute(
                    "UPDATE projects SET project_relpath = 'changed' "
                    "WHERE project_id = 'js-v2'"
                )
            for assignment in (
                "project_id = 'js-v2-renamed'",
                "source_root_id = 'missing-root'",
                "source_type = 'static_web'",
                "entry_relpath = 'index.html'",
            ):
                with self.subTest(project_identity=assignment):
                    with self.assertRaisesRegex(
                        sqlite3.IntegrityError,
                        "project_source_identity_immutable",
                    ):
                        connection.execute(
                            f"UPDATE projects SET {assignment} "
                            "WHERE project_id = 'js-v2'"
                        )

            index_sql = (
                "INSERT INTO project_file_index "
                "(project_id, logical_path, entry_kind, size_bytes, content_sha256) "
                "VALUES (?, ?, ?, ?, ?)"
            )
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "project_file_index_owner_mismatch"
            ):
                connection.execute(
                    index_sql,
                    ("static-v2", "main.js", "javascript_module", 4, module_hash),
                )
            for bad_row in (
                ("js-v2", "null.js", "javascript_module", None, None),
                (
                    "js-v2",
                    "blob-size.js",
                    "javascript_module",
                    sqlite3.Binary(b"4"),
                    module_hash,
                ),
                (
                    "js-v2",
                    "blob-hash.js",
                    "javascript_module",
                    4,
                    sqlite3.Binary(b"a" * 64),
                ),
                ("js-v2", "uppercase.js", "javascript_module", 4, "A" * 64),
                ("js-v2", "bad-link.js", "symlink", 4, module_hash),
            ):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(index_sql, bad_row)
            connection.execute(
                index_sql,
                ("js-v2", "src/main.js", "javascript_module", 4, module_hash),
            )
            connection.execute(
                index_sql,
                ("js-v2", "vendor/link.js", "symlink", None, None),
            )
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "project_file_index_owner_mismatch"
            ):
                connection.execute(
                    "UPDATE project_file_index SET project_id = 'static-v2' "
                    "WHERE project_id = 'js-v2' AND logical_path = 'src/main.js'"
                )
            connection.execute(
                "UPDATE projects SET last_snapshot_hash = ? WHERE project_id = 'js-v2'",
                (snapshot_hash,),
            )

            run_sql = (
                "INSERT INTO intake_runs ("
                "run_id, project_id, run_kind, status, extraction_contract_version, "
                "redaction_rules_version, security_rules_version, supervision_rules_version, "
                "validation_contract_version, canonicalization_version, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )
            connection.execute(
                run_sql,
                (
                    "scan-v2",
                    "js-v2",
                    "javascript_computation_scan",
                    "completed",
                    "extraction.v2",
                    "redaction.v1",
                    "security.v1",
                    "supervision.v1",
                    "validation.v1",
                    1,
                    NOW,
                ),
            )
            connection.execute(
                run_sql,
                (
                    "capture-v2",
                    "js-v2",
                    "javascript_computation_capture",
                    "completed",
                    "extraction.v2",
                    "redaction.v1",
                    "security.v1",
                    "supervision.v1",
                    "validation.v1",
                    1,
                    NOW,
                ),
            )
            connection.execute(
                "INSERT INTO review_items ("
                "review_id, run_id, project_id, candidate_id, candidate_status, "
                "source_relpath, source_location_json, source_hash, redaction_rules_version, "
                "sanitized_candidate_json, redaction_summary_json, created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "enum-review-v2",
                    "capture-v2",
                    "js-v2",
                    "enum-candidate-v2",
                    "waiting_user",
                    "src/main.js",
                    "{}",
                    module_hash,
                    "redaction.v1",
                    "{}",
                    "{}",
                    NOW,
                    NOW,
                ),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE review_items SET enum_decision = ? WHERE review_id = ?",
                    ("confirm_selected_string_enumeration", "enum-review-v2"),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE review_items SET enum_decision = ?, "
                    "enum_decision_binding_sha256 = ?, enum_decided_at = ? "
                    "WHERE review_id = ?",
                    (
                        "confirm_selected_string_enumeration",
                        "B" * 64,
                        NOW,
                        "enum-review-v2",
                    ),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE review_items SET enum_decision = ?, "
                    "enum_decision_binding_sha256 = ?, enum_decided_at = ? "
                    "WHERE review_id = ?",
                    (
                        "confirm_selected_string_enumeration",
                        sqlite3.Binary(b"b" * 64),
                        NOW,
                        "enum-review-v2",
                    ),
                )
            connection.execute(
                "UPDATE review_items SET enum_decision = ?, "
                "enum_decision_binding_sha256 = ?, enum_decided_at = ? "
                "WHERE review_id = ?",
                (
                    "confirm_selected_string_enumeration",
                    "b" * 64,
                    NOW,
                    "enum-review-v2",
                ),
            )
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "review_content_decision_immutable"
            ):
                connection.execute(
                    "UPDATE review_items SET enum_decision_binding_sha256 = ? "
                    "WHERE review_id = ?",
                    ("c" * 64, "enum-review-v2"),
                )
            for assignment in (
                "enum_decision = NULL",
                "enum_decision_binding_sha256 = NULL",
                "enum_decided_at = NULL",
                "enum_decided_at = '2026-07-16T00:00:00Z'",
            ):
                with self.subTest(enum_identity=assignment):
                    with self.assertRaisesRegex(
                        sqlite3.IntegrityError,
                        "review_content_decision_immutable",
                    ):
                        connection.execute(
                            f"UPDATE review_items SET {assignment} "
                            "WHERE review_id = 'enum-review-v2'"
                        )

        self.assertEqual(
            store_module._verify_database(
                self.path, expected_version=2
            )["user_version"],
            2,
        )

        tampered_enum = self.root / "v2-invariant-enum-blob.sqlite3"
        shutil.copy2(self.path, tampered_enum)
        connection = sqlite3.connect(tampered_enum)
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(
            "INSERT INTO review_items ("
            "review_id, run_id, project_id, candidate_id, candidate_status, "
            "source_relpath, source_location_json, source_hash, redaction_rules_version, "
            "sanitized_candidate_json, redaction_summary_json, enum_decision, "
            "enum_decision_binding_sha256, enum_decided_at, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "enum-review-v2-blob",
                "capture-v2",
                "js-v2",
                "enum-candidate-v2-blob",
                "waiting_user",
                "src/main.js",
                "{}",
                module_hash,
                "redaction.v1",
                "{}",
                "{}",
                "confirm_selected_string_enumeration",
                sqlite3.Binary(b"b" * 64),
                NOW,
                NOW,
                NOW,
            ),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(
            CapsuleStoreError, "review_enum_decision_binding"
        ):
            store_module._verify_database(tampered_enum, expected_version=2)

        for variant in ("path_collision", "invalid_path", "bad_snapshot"):
            with self.subTest(variant=variant):
                tampered = self.root / f"v2-invariant-{variant}.sqlite3"
                shutil.copy2(self.path, tampered)
                connection = sqlite3.connect(tampered)
                if variant == "path_collision":
                    connection.execute(
                        "INSERT INTO project_file_index VALUES (?, ?, ?, ?, ?)",
                        ("js-v2", "SRC/main.js", "javascript_module", 4, "d" * 64),
                    )
                    expected_error = "path_collision"
                elif variant == "invalid_path":
                    connection.execute(
                        "INSERT INTO project_file_index VALUES (?, ?, ?, ?, ?)",
                        ("js-v2", "../escape.js", "javascript_module", 4, "d" * 64),
                    )
                    expected_error = "project_file_index_path"
                else:
                    connection.execute(
                        "UPDATE projects SET last_snapshot_hash = ? WHERE project_id = 'js-v2'",
                        ("0" * 64,),
                    )
                    expected_error = "javascript_scope_snapshot"
                connection.commit()
                connection.close()
                with self.assertRaisesRegex(CapsuleStoreError, expected_error):
                    store_module._verify_database(tampered, expected_version=2)

    def _seed_project_and_active_version(
        self, *, asset_content: bytes | None = None
    ) -> None:
        self.store.initialize()
        payload = canonical_payload()
        asset_digest = (
            hashlib.sha256(asset_content).hexdigest()
            if asset_content is not None
            else None
        )
        payload["assets"] = (
            [
                {
                    "logical_path": "images/pixel.png",
                    "media_type": "image/png",
                    "sha256": asset_digest,
                }
            ]
            if asset_digest is not None
            else []
        )
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
            if asset_content is not None and asset_digest is not None:
                connection.execute(
                    "INSERT INTO capsule_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "asset-1",
                        "version-1",
                        "images/pixel.png",
                        "image/png",
                        asset_digest,
                        len(asset_content),
                        1,
                        1,
                        asset_content,
                    ),
                )
            connection.execute(
                "UPDATE capsules SET current_version_id = ?, status = ? WHERE capsule_id = ?",
                ("version-1", "active", "capsule-1"),
            )

    def _new_v2_store(self, name: str) -> CapsuleWarehouseStore:
        path = self.root / name / "capsule_warehouse.sqlite3"
        path.parent.mkdir(parents=True)
        connection = sqlite3.connect(path)
        connection.executescript(
            "PRAGMA foreign_keys=ON;\n"
            + store_module.SCHEMA_SQL_V2
            + "\nPRAGMA user_version=2;"
        )
        connection.close()
        store_module._prepare_database_file(path)
        return CapsuleWarehouseStore(path)

    def _new_v1_store(self, name: str) -> CapsuleWarehouseStore:
        path = self.root / name / "capsule_warehouse.sqlite3"
        path.parent.mkdir(parents=True)
        connection = sqlite3.connect(path)
        connection.executescript(store_module.SCHEMA_SQL_V1)
        connection.execute(
            "INSERT INTO app_settings VALUES (?, ?, ?)",
            ("phase", '"v1"', NOW),
        )
        connection.commit()
        connection.close()
        store_module._prepare_database_file(path)
        return CapsuleWarehouseStore(path)

    @staticmethod
    def _insert_unhashed_js_index(connection: sqlite3.Connection) -> None:
        connection.execute(
            "INSERT INTO source_roots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "root-js-invariant",
                "single_project",
                "/read/only/js-invariant",
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
            "INSERT INTO projects ("
            "project_id, source_root_id, source_type, project_relpath, entry_relpath, "
            "display_name, project_state, discovery_signature, last_snapshot_hash, "
            "brand_mode, brand_profile_id, brand_profile_json, brand_profile_digest, "
            "brand_profile_version, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "project-js-invariant",
                "root-js-invariant",
                "javascript_computation_source",
                ".",
                None,
                "JS invariant",
                "ready",
                "signature",
                None,
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
            "INSERT INTO project_file_index VALUES (?, ?, ?, ?, ?)",
            (
                "project-js-invariant",
                "src/main.js",
                "javascript_module",
                4,
                "a" * 64,
            ),
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
