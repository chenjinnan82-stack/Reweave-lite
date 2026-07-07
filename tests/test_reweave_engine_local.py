"""Tests for LocalReweaveEngine facade (no PySide6)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_engine.local import LocalReweaveEngine
from pimos_lite import reweave_source_registry as registry


class LocalReweaveEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._state_dir)})
        self._env.start()
        self.engine = LocalReweaveEngine()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def test_initial_state_shape(self) -> None:
        state = self.engine.get_initial_state()
        self.assertEqual(state["backend"], "local")
        self.assertEqual(state["engine"], "local")
        self.assertIn("engineStatus", state)
        self.assertTrue(state["engineStatus"]["available"])
        self.assertTrue(state["skipWelcome"])
        self.assertIn("sourceBoxes", state)
        self.assertIn("capsules", state)

    def test_full_pipeline_via_engine(self) -> None:
        root = self._state_dir / "engine-project"
        root.mkdir()
        (root / "app.py").write_text("# app", encoding="utf-8")
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        box = self.engine.bind_source_folder(str(root))
        self.engine.scan_source(box["id"])
        self.engine.draft_source(box["id"])
        promoted = self.engine.promote_source(box["id"])
        self.assertGreater(len(promoted), 0)
        gen = self.engine.generate_preview(
            {"taskText": "Engine preview", "capsuleIds": [promoted[0]["id"]], "backend": "local"}
        )
        self.assertTrue(gen["ok"])
        self.assertTrue(gen.get("previewPath"))
        state = self.engine.get_initial_state()
        self.assertTrue(state["useLocalCapsules"])
        self.assertGreater(len(state["capsules"]), 0)
        self.assertIn("generatedPackage", state)
        self.assertIn("previewPath", state)


if __name__ == "__main__":
    unittest.main()
