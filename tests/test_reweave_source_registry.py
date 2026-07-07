"""Tests for Reweave Source Box Registry v0 (no PySide6)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite import reweave_source_registry as registry


class ReweaveSourceRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._state_dir)})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def test_add_and_list_source_box(self) -> None:
        folder = self._state_dir / "my-old-project"
        folder.mkdir()
        source = registry.add_source_box(folder)
        self.assertEqual(source["label"], "my-old-project")
        self.assertEqual(source["status"], "bound")
        self.assertEqual(source["scan_status"], "not_scanned")
        self.assertEqual(source["draft_status"], "not_drafted")
        self.assertTrue(source["id"].startswith("source_"))
        boxes = registry.list_source_boxes()
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0]["path"], str(folder.resolve()))

    def test_duplicate_path_does_not_duplicate(self) -> None:
        folder = self._state_dir / "dup-test"
        folder.mkdir()
        first = registry.add_source_box(folder)
        second = registry.add_source_box(folder)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(registry.list_source_boxes()), 1)

    def test_registry_file_exists(self) -> None:
        folder = self._state_dir / "boxed"
        folder.mkdir()
        registry.add_source_box(folder)
        path = registry.registry_path()
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(len(data["source_boxes"]), 1)

    def test_corrupt_registry_is_backed_up_and_treated_empty(self) -> None:
        path = registry.registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")

        data = registry.load_registry()

        self.assertEqual(data["source_boxes"], [])
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")
        self.assertTrue(list(path.parent.glob("source_boxes.json.corrupt.*.bak")))

    def test_add_source_box_does_not_read_folder_contents(self) -> None:
        folder = self._state_dir / "sealed"
        folder.mkdir()
        secret = folder / "secret.txt"
        secret.write_text("do not read", encoding="utf-8")

        with patch("os.listdir", side_effect=AssertionError("must not listdir")):
            with patch.object(Path, "iterdir", side_effect=AssertionError("must not iterdir")):
                source = registry.add_source_box(folder)

        self.assertEqual(source["label"], "sealed")
        self.assertEqual(secret.read_text(encoding="utf-8"), "do not read")

    def test_state_dir_inside_source_folder_is_blocked(self) -> None:
        folder = self._state_dir / "source-root"
        folder.mkdir()

        with patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(folder / ".reweave")}):
            source = registry.add_source_box(folder)

        self.assertEqual(source["status"], "blocked")
        self.assertEqual(source["last_error"], "reweave_state_dir_inside_source_folder")
        self.assertFalse((folder / ".reweave" / "source_boxes.json").exists())

    def test_remove_and_clear(self) -> None:
        folder = self._state_dir / "rm-me"
        folder.mkdir()
        source = registry.add_source_box(folder)
        self.assertTrue(registry.remove_source_box(source["id"]))
        self.assertEqual(registry.list_source_boxes(), [])
        registry.add_source_box(folder)
        registry.clear_registry()
        self.assertEqual(registry.list_source_boxes(), [])


if __name__ == "__main__":
    unittest.main()
