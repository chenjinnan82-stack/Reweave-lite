"""Tests for Reweave Capsule Warehouse v0 (no PySide6)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite import reweave_capsule_draft as draft
from pimos_lite import reweave_capsule_warehouse as warehouse
from pimos_lite import reweave_source_registry as registry
from pimos_lite import reweave_source_scanner as scanner


class ReweaveCapsuleWarehouseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._state_dir)})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def _bind_scan_draft(self) -> str:
        root = self._state_dir / "warehouse-project"
        root.mkdir()
        (root / "main.py").write_text("# entry", encoding="utf-8")
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        box = registry.add_source_box(root)
        scanner.scan_source_box(box["id"])
        draft.draft_capsules(box["id"])
        return box["id"]

    def test_promote_writes_warehouse_not_source_folder(self) -> None:
        source_id = self._bind_scan_draft()
        root = registry.get_source_box(source_id)
        assert root is not None
        source_path = Path(root["path"])
        promoted = warehouse.promote_source_drafts(source_id)
        self.assertGreater(len(promoted), 0)
        wh_path = warehouse.warehouse_path()
        self.assertTrue(wh_path.is_file())
        self.assertEqual(wh_path.resolve().parent, warehouse.warehouse_dir().resolve())
        self.assertNotEqual(wh_path.resolve().parent, source_path.resolve())
        updated = registry.get_source_box(source_id)
        assert updated is not None
        self.assertEqual(updated["warehouse_status"], "promoted")
        self.assertEqual(updated["promoted_capsule_count"], len(promoted))

    def test_list_capsules_after_promote(self) -> None:
        source_id = self._bind_scan_draft()
        warehouse.promote_source_drafts(source_id)
        caps = warehouse.list_capsules()
        self.assertGreater(len(caps), 0)
        first = caps[0]
        self.assertTrue(first["id"].startswith("cap_"))
        self.assertEqual(first["source_id"], source_id)
        loaded = warehouse.get_capsule(first["id"])
        assert loaded is not None
        self.assertEqual(loaded["name"], first["name"])

    def test_corrupt_warehouse_is_backed_up_and_treated_empty(self) -> None:
        path = warehouse.warehouse_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")

        data = warehouse.load_warehouse()

        self.assertEqual(data["capsules"], [])
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")
        self.assertTrue(list(path.parent.glob("capsules.json.corrupt.*.bak")))

    def test_promote_is_idempotent(self) -> None:
        source_id = self._bind_scan_draft()
        first = warehouse.promote_source_drafts(source_id)
        second = warehouse.promote_source_drafts(source_id)
        self.assertGreater(len(first), 0)
        self.assertEqual(second, [])
        data = json.loads(warehouse.warehouse_path().read_text(encoding="utf-8"))
        self.assertEqual(len(data["capsules"]), len(first))


if __name__ == "__main__":
    unittest.main()
