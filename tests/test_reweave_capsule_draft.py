"""Tests for Reweave Capsule Draft v0 (no PySide6)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite import reweave_capsule_draft as draft
from pimos_lite import reweave_source_registry as registry
from pimos_lite import reweave_source_scanner as scanner


class ReweaveCapsuleDraftTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._state_dir)})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def _make_project(self) -> Path:
        root = self._state_dir / "draft-project"
        root.mkdir()
        (root / "main.py").write_text("print('hi')\n", encoding="utf-8")
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        (root / "styles.css").write_text("body {}", encoding="utf-8")
        return root

    def test_draft_requires_scan(self) -> None:
        root = self._make_project()
        box = registry.add_source_box(root)
        with self.assertRaises(ValueError):
            draft.draft_capsules(box["id"])

    def test_draft_from_summary_only(self) -> None:
        root = self._make_project()
        box = registry.add_source_box(root)
        scanner.scan_source_box(box["id"])
        result = draft.draft_capsules(box["id"])
        self.assertGreater(result["candidate_count"], 0)
        path = draft.draft_file_path(box["id"])
        self.assertTrue(path.is_file())
        self.assertEqual(path.resolve().parent, draft.drafts_dir().resolve())
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["source_id"], box["id"])
        updated = registry.get_source_box(box["id"])
        assert updated is not None
        self.assertEqual(updated["draft_status"], "drafted")
        self.assertTrue(updated.get("draft_path", "").startswith("capsule_drafts/"))

    def test_react_project_candidate_comes_from_project_graph(self) -> None:
        candidates = draft.build_draft_candidates(
            {
                "source_id": "source_react",
                "label": "React source",
                "extensions": {},
                "entry_candidates": [],
                "project_graph": {
                    "project_kind": "react_vite",
                    "entrypoints": ["src/main.tsx"],
                    "runtime_files": ["src/main.tsx", "src/App.tsx"],
                },
            }
        )

        self.assertEqual(candidates[0]["name"], "React/Vite Project")
        self.assertEqual(candidates[0]["tags"], ["react", "vite", "project"])

    def test_corrupt_draft_is_backed_up_and_treated_missing(self) -> None:
        path = draft.draft_file_path("source_bad")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")

        self.assertIsNone(draft.load_draft("source_bad"))
        self.assertTrue(list(path.parent.glob("source_bad.draft.json.corrupt.*.bak")))


if __name__ == "__main__":
    unittest.main()
