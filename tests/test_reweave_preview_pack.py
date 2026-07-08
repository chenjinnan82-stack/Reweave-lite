"""Tests for Reweave preview package v0 (no PySide6)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite import reweave_capsule_draft as draft
from pimos_lite import reweave_capsule_warehouse as warehouse
from pimos_lite import reweave_preview_pack as preview
from pimos_lite import reweave_source_registry as registry
from pimos_lite import reweave_source_scanner as scanner


class ReweavePreviewPackTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._state_dir)})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def _promote_capsules(self) -> list[str]:
        root = self._state_dir / "preview-source"
        root.mkdir()
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        (root / "app.py").write_text("# app", encoding="utf-8")
        box = registry.add_source_box(root)
        scanner.scan_source_box(box["id"])
        draft.draft_capsules(box["id"])
        promoted = warehouse.promote_source_drafts(box["id"])
        return [c["id"] for c in promoted]

    def test_build_preview_writes_to_state_dir(self) -> None:
        cap_ids = self._promote_capsules()
        self.assertGreater(len(cap_ids), 0)
        result = preview.build_preview_package(
            {"taskText": "Client quote tool", "capsuleIds": cap_ids[:2], "backend": "local"}
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["mock"])
        preview_path = Path(result["previewPath"])
        self.assertTrue(preview_path.is_dir())
        self.assertEqual(preview_path.resolve().parent, preview.preview_packages_dir().resolve())
        for name in ("index.html", "styles.css", "app.js", "task_pack.json", "capsules_used.json", "provenance.json", "summary.md"):
            self.assertTrue((preview_path / name).is_file())
        html = (preview_path / "index.html").read_text(encoding="utf-8")
        self.assertIn("Small Project Pack", html)
        self.assertIn("reweaveDemoButton", html)
        self.assertIn("Client quote tool", html)
        task_pack = json.loads((preview_path / "task_pack.json").read_text(encoding="utf-8"))
        self.assertEqual(task_pack["mode"], "task_pack_preview")
        self.assertEqual(task_pack["package_kind"], "small_project_pack")
        self.assertFalse(task_pack["source_project_write"])
        self.assertEqual(task_pack["selected_capsule_ids"], cap_ids[:2])
        provenance = json.loads((preview_path / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["backend"], "local")
        self.assertEqual(len(provenance["capsule_ids"]), 2)
        self.assertEqual(
            {item["path"] for item in provenance["outputs"]},
            {"index.html", "styles.css", "app.js"},
        )
        self.assertTrue(all(item["source_project_write"] is False for item in provenance["outputs"]))

    def test_latest_preview_restored(self) -> None:
        cap_ids = self._promote_capsules()
        preview.build_preview_package({"taskText": "Status panel", "capsuleIds": cap_ids[:1]})
        latest = preview.load_latest_preview()
        assert latest is not None
        self.assertTrue(Path(latest["previewPath"]).is_dir())
        self.assertIn("generatedPackage", latest)
        self.assertIn("task_pack.json", latest["generatedPackage"]["files"])

    def test_missing_capsules_raises(self) -> None:
        with self.assertRaises(ValueError):
            preview.build_preview_package({"taskText": "x", "capsuleIds": ["cap_missing"]})

    def test_preview_index_escapes_task_and_capsule_fields(self) -> None:
        html = preview._build_index_html(
            "<script>alert(1)</script>",
            [
                {
                    "name": "<img src=x>",
                    "type": "<b>",
                    "role": "<script>role</script>",
                    "preview": ["<script>bad()</script>"],
                }
            ],
        )

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&lt;img src=x&gt;", html)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x>", html)

    def test_preview_package_redacts_source_box_paths_by_default(self) -> None:
        result = preview.build_preview_package(
            {
                "taskText": "Path redaction",
                "capsules": [{"id": "cap_demo", "name": "Demo", "type": "ui", "preview": []}],
                "sourceBoxes": [
                    {
                        "id": "source_demo",
                        "label": "demo",
                        "path": "/Users/alice/private-project",
                        "path_hash": "sha256:stable",
                    }
                ],
            }
        )

        provenance = json.loads((Path(result["previewPath"]) / "provenance.json").read_text(encoding="utf-8"))
        box = provenance["source_boxes"][0]
        self.assertEqual(box["id"], "source_demo")
        self.assertEqual(box["label"], "demo")
        self.assertEqual(box["path_policy"], "redacted")
        self.assertNotIn("path", box)
        self.assertNotIn("path_hash", box)


if __name__ == "__main__":
    unittest.main()
