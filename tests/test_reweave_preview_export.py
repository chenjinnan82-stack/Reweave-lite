"""Tests for Reweave preview package export / archive (Phase 13)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_capsule_content import enrich_capsule_content
from pimos_lite.reweave_governance_preview import save_governance_preview
from pimos_lite.reweave_preview_export import (
    export_log_path,
    export_preview_package,
    is_export_to_source_folder_blocked,
)
from pimos_lite.reweave_preview_pack import build_preview_package
from pimos_lite.reweave_promote import promote_review_item
from pimos_lite.reweave_review_queue import create_or_update_review_queue, load_review_queue, update_review_decision
from pimos_lite import reweave_capsule_warehouse as warehouse
from pimos_lite import reweave_source_registry as registry
from pimos_lite import reweave_source_scanner as scanner
from pimos_lite.reweave_engine.local import LocalReweaveEngine


def _governance_preview() -> dict:
    return {
        "results": [
            {
                "id": "luna_asset_keep",
                "name": "Form Shell",
                "origin": "luna_reuse_pack",
                "verification_status": "verified",
                "verification_score": 0.82,
                "governance_action": "keep",
                "governance_reason": "High metadata match",
            }
        ]
    }


class ReweavePreviewExportTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name) / "reweave_state"
        self._state_dir.mkdir()
        self._source_dir = self._state_dir / "user_project"
        self._source_dir.mkdir()
        self._export_dir = self._state_dir / "exports"
        self._export_dir.mkdir()
        self._env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._state_dir), "REWEAVE_ENGINE": "local"})
        self._env.start()
        warehouse.clear_warehouse()

        (self._source_dir / "index.html").write_text("<!doctype html><p>x</p>", encoding="utf-8")
        box = registry.add_source_box(str(self._source_dir))
        self.source_id = str(box["id"])
        scanner.scan_source_box(self.source_id)
        save_governance_preview(self.source_id, _governance_preview())
        create_or_update_review_queue(self.source_id, _governance_preview())
        queue = load_review_queue(self.source_id)
        assert queue
        self.review_id = queue["items"][0]["review_id"]
        update_review_decision(self.source_id, self.review_id, "approved")
        promoted = promote_review_item(self.source_id, self.review_id)
        self.capsule_id = str(promoted["capsule_id"])
        enrich_capsule_content(self.capsule_id)

        self.metadata_result = build_preview_package(
            {"taskText": "Tool-meta", "capsuleIds": [self.capsule_id], "backend": "local"}
        )
        self.package_id = Path(self.metadata_result["previewPath"]).name
        self.package_root = Path(self.metadata_result["previewPath"])

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def test_zip_export_success(self) -> None:
        result = export_preview_package(self.package_id, self._export_dir, mode="zip")
        self.assertTrue(result["ok"])
        export_path = Path(result["export_path"])
        self.assertTrue(export_path.is_file())
        self.assertTrue(export_path.suffix == ".zip")

    def test_copy_export_success(self) -> None:
        result = export_preview_package(self.package_id, self._export_dir, mode="copy")
        self.assertTrue(result["ok"])
        export_path = Path(result["export_path"])
        self.assertTrue(export_path.is_dir())
        self.assertTrue((export_path / "index.html").is_file())

    def test_export_rejects_arbitrary_existing_directory(self) -> None:
        outside = Path(self._tmpdir.name) / "outside_package"
        outside.mkdir()
        (outside / "index.html").write_text("<html>outside</html>", encoding="utf-8")

        result = export_preview_package(str(outside), self._export_dir, mode="zip")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "package_not_found")

    def test_zip_has_no_absolute_paths(self) -> None:
        result = export_preview_package(self.package_id, self._export_dir, mode="zip")
        with zipfile.ZipFile(result["export_path"], "r") as archive:
            for name in archive.namelist():
                self.assertFalse(name.startswith("/"))
                self.assertNotIn("..", name)

    def test_readme_in_zip(self) -> None:
        result = export_preview_package(self.package_id, self._export_dir, mode="zip")
        with zipfile.ZipFile(result["export_path"], "r") as archive:
            self.assertIn("README_REWEAVE_PREVIEW.txt", archive.namelist())
            readme = archive.read("README_REWEAVE_PREVIEW.txt").decode("utf-8")
            self.assertIn("not a deployed project", readme)
            self.assertIn("源项目未被修改", readme)

    def test_export_log_written(self) -> None:
        export_preview_package(self.package_id, self._export_dir, mode="zip")
        log_path = export_log_path()
        self.assertTrue(log_path.is_file())
        lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 1)
        record = json.loads(lines[-1])
        self.assertEqual(record["event"], "preview_package_exported")
        self.assertEqual(record["package_id"], self.package_id)

    def test_export_does_not_modify_preview_package(self) -> None:
        before = {
            name: (self.package_root / name).read_bytes()
            for name in ("capsules_used.json", "provenance.json", "index.html")
        }
        export_preview_package(self.package_id, self._export_dir, mode="zip")
        after = {
            name: (self.package_root / name).read_bytes()
            for name in before
        }
        self.assertEqual(before, after)

    def test_export_does_not_read_source_folder(self) -> None:
        with patch("pimos_lite.reweave_source_registry.get_source_box") as mock_box, patch(
            "pimos_lite.reweave_capsule_content._read_text_snippet"
        ) as mock_read:
            result = export_preview_package(self.package_id, self._export_dir, mode="zip")
            mock_box.assert_not_called()
            mock_read.assert_not_called()
        self.assertTrue(result["ok"])

    def test_export_does_not_write_source_folder(self) -> None:
        before = {p.name for p in self._source_dir.iterdir()}
        export_preview_package(self.package_id, self._export_dir, mode="zip")
        after = {p.name for p in self._source_dir.iterdir()}
        self.assertEqual(before, after)

    def test_export_to_source_folder_blocked(self) -> None:
        self.assertTrue(is_export_to_source_folder_blocked(self._source_dir))
        result = export_preview_package(self.package_id, self._source_dir, mode="zip")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "export_to_source_folder_blocked")

    def test_export_to_directory_containing_source_folder_blocked(self) -> None:
        self.assertTrue(is_export_to_source_folder_blocked(self._state_dir))
        result = export_preview_package(self.package_id, self._state_dir, mode="zip")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "export_to_source_folder_blocked")

    def test_package_not_found(self) -> None:
        result = export_preview_package("missing_package_id", self._export_dir, mode="zip")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "package_not_found")

    def test_duplicate_zip_not_overwritten(self) -> None:
        first = export_preview_package(self.package_id, self._export_dir, mode="zip")
        second = export_preview_package(self.package_id, self._export_dir, mode="zip")
        self.assertTrue(first["ok"] and second["ok"])
        self.assertNotEqual(first["export_path"], second["export_path"])
        self.assertTrue(Path(first["export_path"]).is_file())
        self.assertTrue(Path(second["export_path"]).is_file())

    def test_export_without_snippets_used(self) -> None:
        result = export_preview_package(self.package_id, self._export_dir, mode="zip")
        self.assertTrue(result["ok"])
        with zipfile.ZipFile(result["export_path"], "r") as archive:
            names = archive.namelist()
            self.assertIn("capsules_used.json", names)
            self.assertIn("provenance.json", names)

    def test_provenance_and_capsules_included(self) -> None:
        result = export_preview_package(self.package_id, self._export_dir, mode="copy")
        dest = Path(result["export_path"])
        self.assertTrue((dest / "capsules_used.json").is_file())
        self.assertTrue((dest / "provenance.json").is_file())
        capsules = json.loads((dest / "capsules_used.json").read_text(encoding="utf-8"))
        self.assertEqual(len(capsules), 1)

    def test_content_aware_export_includes_snippets_used(self) -> None:
        enriched = build_preview_package(
            {
                "taskText": "Tool-rich",
                "capsuleIds": [self.capsule_id],
                "backend": "local",
                "useEnrichedContent": True,
            }
        )
        package_id = Path(enriched["previewPath"]).name
        result = export_preview_package(package_id, self._export_dir, mode="zip")
        with zipfile.ZipFile(result["export_path"], "r") as archive:
            self.assertIn("snippets_used.json", archive.namelist())

    def test_app_service_export(self) -> None:
        service = ReweaveAppService(engine=LocalReweaveEngine())
        result = service.export_preview_package(self.package_id, str(self._export_dir), "zip")
        self.assertTrue(result["ok"])

    def test_export_works_when_source_path_removed(self) -> None:
        shutil.rmtree(self._source_dir)
        result = export_preview_package(self.package_id, self._export_dir, mode="zip")
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
