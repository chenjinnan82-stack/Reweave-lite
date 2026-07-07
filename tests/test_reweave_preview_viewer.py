"""Tests for Reweave preview package viewer / compare (Phase 12)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_capsule_content import enrich_capsule_content
from pimos_lite.reweave_governance_preview import save_governance_preview
from pimos_lite.reweave_preview_pack import attach_luna_provenance, build_luna_provenance_record, build_preview_package
from pimos_lite.reweave_preview_viewer import (
    compare_preview_packages,
    get_latest_preview_package,
    get_preview_package,
)
from pimos_lite.reweave_promote import promote_review_item
from pimos_lite.reweave_review_queue import create_or_update_review_queue, load_review_queue, update_review_decision
from pimos_lite import reweave_capsule_warehouse as warehouse
from pimos_lite import reweave_preview_pack as preview
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


class ReweavePreviewViewerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._source_dir = self._state_dir / "user_project"
        self._source_dir.mkdir()
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

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def _generate(self, *, enriched: bool = False) -> dict:
        payload = {"taskText": f"Tool-{enriched}", "capsuleIds": [self.capsule_id], "backend": "local"}
        if enriched:
            payload["useEnrichedContent"] = True
        return build_preview_package(payload)

    def test_get_latest_preview_package(self) -> None:
        self._generate(enriched=False)
        latest = get_latest_preview_package()
        self.assertTrue(latest["ok"])
        self.assertIn("package", latest)
        self.assertIn("capsules_used.json", latest["package"]["files"])

    def test_viewer_reads_capsules_used(self) -> None:
        result = self._generate(enriched=False)
        folder = Path(result["previewPath"]).name
        viewer = get_preview_package(folder)
        self.assertTrue(viewer["ok"])
        self.assertEqual(len(viewer["capsulesUsed"]), 1)
        self.assertEqual(viewer["capsulesUsed"][0]["capsule_id"], self.capsule_id)

    def test_viewer_reads_snippets_used(self) -> None:
        result = self._generate(enriched=True)
        viewer = get_preview_package(Path(result["previewPath"]).name)
        self.assertTrue(viewer["ok"])
        self.assertTrue(viewer["snippetsUsed"]["enabled"])
        self.assertGreater(viewer["snippetsUsed"]["count"], 0)

    def test_viewer_without_snippets_used(self) -> None:
        result = self._generate(enriched=False)
        viewer = get_preview_package(Path(result["previewPath"]).name)
        self.assertTrue(viewer["ok"])
        self.assertFalse(viewer["snippetsUsed"]["enabled"])

    def test_viewer_reads_provenance(self) -> None:
        result = self._generate(enriched=True)
        viewer = get_preview_package(Path(result["previewPath"]).name)
        self.assertTrue(viewer["ok"])
        self.assertTrue(viewer["provenance"]["content_aware_generate"]["enabled"])

    def test_viewer_without_source_folder(self) -> None:
        result = self._generate(enriched=True)
        shutil.rmtree(self._source_dir)
        viewer = get_preview_package(Path(result["previewPath"]).name)
        self.assertTrue(viewer["ok"])
        self.assertFalse(viewer["safety"]["source_folder_read_at_view_time"])

    def test_compare_snippets_used_added(self) -> None:
        self._generate(enriched=False)
        self._generate(enriched=True)
        cmp = compare_preview_packages()
        self.assertTrue(cmp["ok"])
        self.assertIn("snippets_used.json", cmp["diff"]["files_added"])

    def test_compare_content_aware_changed(self) -> None:
        self._generate(enriched=False)
        self._generate(enriched=True)
        cmp = compare_preview_packages()
        self.assertTrue(cmp["ok"])
        self.assertTrue(cmp["diff"]["content_aware_changed"])

    def test_compare_is_metadata_only(self) -> None:
        self._generate(enriched=False)
        self._generate(enriched=True)
        cmp = compare_preview_packages()
        self.assertFalse(cmp["safety"]["code_diff"])
        self.assertTrue(cmp["safety"]["metadata_compare_only"])

    def test_generate_updates_preview_history(self) -> None:
        self._generate(enriched=False)
        history = preview.load_preview_history()
        self.assertEqual(len(history["packages"]), 1)
        self._generate(enriched=True)
        history = preview.load_preview_history()
        self.assertEqual(len(history["packages"]), 2)
        self.assertTrue(history["packages"][0]["content_aware"])

    def test_luna_provenance_in_viewer(self) -> None:
        result = self._generate(enriched=False)
        luna_record = build_luna_provenance_record(
            {"lunaPack": {"pack_id": "pack_123", "manifest_path": "/tmp/p.json", "endpoint": "/api/v1/pym/index-pack"}},
            success=True,
        )
        attach_luna_provenance(result["previewPath"], luna_record)
        viewer = get_preview_package(Path(result["previewPath"]).name)
        self.assertTrue(viewer["ok"])
        self.assertEqual(viewer["provenance"]["luna"]["pack_id"], "pack_123")

    def test_compare_no_previous_package(self) -> None:
        cmp = compare_preview_packages()
        self.assertFalse(cmp["ok"])
        self.assertEqual(cmp["error"], "no_previous_package")

    def test_viewer_does_not_modify_package(self) -> None:
        result = self._generate(enriched=True)
        root = Path(result["previewPath"])
        before = {
            name: (root / name).read_text(encoding="utf-8")
            for name in ("capsules_used.json", "provenance.json", "snippets_used.json")
            if (root / name).is_file()
        }
        get_preview_package(root.name)
        after = {
            name: (root / name).read_text(encoding="utf-8")
            for name in before
        }
        self.assertEqual(before, after)

    def test_viewer_rejects_relative_escape_from_state_dir(self) -> None:
        outside = self._state_dir.parent / f"{self._state_dir.name}_outside_pkg"
        try:
            outside.mkdir()
            (outside / "provenance.json").write_text("{}", encoding="utf-8")

            viewer = get_preview_package(f"../{outside.name}")

            self.assertFalse(viewer["ok"])
            self.assertEqual(viewer["error"], "package_not_found")
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_latest_preview_fallback_rejects_state_dir_escape(self) -> None:
        outside = self._state_dir.parent / f"{self._state_dir.name}_outside_latest"
        try:
            outside.mkdir()
            (outside / "provenance.json").write_text("{}", encoding="utf-8")
            preview.latest_manifest_path().parent.mkdir(parents=True, exist_ok=True)
            preview.latest_manifest_path().write_text(
                json.dumps({"preview_path": str(outside), "folder_name": outside.name}),
                encoding="utf-8",
            )

            latest = get_latest_preview_package()

            self.assertFalse(latest["ok"])
            self.assertEqual(latest["error"], "no_preview_package")
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_app_service_viewer_methods(self) -> None:
        self._generate(enriched=True)
        service = ReweaveAppService(engine=LocalReweaveEngine())
        latest = service.get_latest_preview_package()
        self.assertTrue(latest["ok"])
        cmp = service.compare_preview_packages()
        self.assertFalse(cmp["ok"])

    def test_browser_fallback_no_crash_on_missing_package(self) -> None:
        latest = get_latest_preview_package()
        self.assertFalse(latest["ok"])


if __name__ == "__main__":
    unittest.main()
