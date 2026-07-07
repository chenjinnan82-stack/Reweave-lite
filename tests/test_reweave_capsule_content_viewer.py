"""Tests for Reweave capsule content viewer (Phase 10)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_capsule_content import (
    content_file_path,
    enrich_capsule_content,
    get_capsule_content,
)
from pimos_lite.reweave_governance_preview import save_governance_preview
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


class ReweaveCapsuleContentViewerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._source_dir = self._state_dir / "user_project"
        self._source_dir.mkdir()
        self._env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._state_dir), "REWEAVE_ENGINE": "local"})
        self._env.start()
        warehouse.clear_warehouse()

        (self._source_dir / "index.html").write_text("<!doctype html><title>Form</title>", encoding="utf-8")
        (self._source_dir / "app.js").write_text("console.log('viewer');", encoding="utf-8")

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

    def test_get_capsule_content_reads_existing_json(self) -> None:
        result = get_capsule_content(self.capsule_id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["capsule_id"], self.capsule_id)
        self.assertIn("snippets", result["content"])
        self.assertGreater(len(result["content"]["snippets"]), 0)

    def test_unenriched_capsule_returns_no_content_enrichment(self) -> None:
        cap_id = "cap_unenriched_viewer"
        warehouse.save_warehouse(
            {
                "capsules": [
                    {
                        "id": cap_id,
                        "name": "Plain",
                        "type": "UI",
                        "status": "active",
                        "source_id": self.source_id,
                        "risk": "metadata_only_promoted",
                    }
                ]
            }
        )
        result = get_capsule_content(cap_id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "no_content_enrichment")

    def test_missing_content_file_returns_content_file_missing(self) -> None:
        cap_id = "cap_missing_content_file"
        warehouse.save_warehouse(
            {
                "capsules": [
                    {
                        "id": cap_id,
                        "name": "Broken",
                        "type": "UI",
                        "status": "active",
                        "source_id": self.source_id,
                        "content_enrichment": {
                            "status": "enriched",
                            "content_path": f"capsule_contents/{cap_id}.content.json",
                            "snippet_count": 1,
                        },
                    }
                ]
            }
        )
        result = get_capsule_content(cap_id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "content_file_missing")

    def test_missing_capsule_returns_capsule_not_found(self) -> None:
        result = get_capsule_content("cap_does_not_exist")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "capsule_not_found")

    def test_viewer_works_when_source_path_gone(self) -> None:
        shutil.rmtree(self._source_dir)
        result = get_capsule_content(self.capsule_id)
        self.assertTrue(result["ok"])
        self.assertIn("limits", result["content"])
        self.assertIn("safety", result["content"])

    def test_payload_includes_snippets_limits_safety_warnings(self) -> None:
        result = get_capsule_content(self.capsule_id)
        content = result["content"]
        self.assertEqual(content["mode"], "controlled_snippet_preview")
        self.assertIn("max_files", content["limits"])
        self.assertFalse(content["safety"]["source_folder_written"])
        self.assertIsInstance(content["warnings"], list)

    def test_generate_still_excludes_full_snippet_preview(self) -> None:
        result = preview.build_preview_package(
            {"taskText": "Viewer tool", "capsuleIds": [self.capsule_id], "backend": "local"}
        )
        used = json.loads((Path(result["previewPath"]) / "capsules_used.json").read_text(encoding="utf-8"))
        prov = json.loads((Path(result["previewPath"]) / "provenance.json").read_text(encoding="utf-8"))
        self.assertNotIn("preview", used[0])
        self.assertNotIn("snippets", prov["capsules"][0])
        self.assertIn("content_enrichment", used[0])

    def test_get_capsule_content_does_not_modify_content_file(self) -> None:
        path = content_file_path(self.capsule_id)
        before = path.read_text(encoding="utf-8")
        mtime_before = path.stat().st_mtime
        get_capsule_content(self.capsule_id)
        get_capsule_content(self.capsule_id)
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertEqual(path.stat().st_mtime, mtime_before)

    def test_app_service_get_capsule_content(self) -> None:
        service = ReweaveAppService(engine=LocalReweaveEngine())
        result = service.get_capsule_content(self.capsule_id)
        self.assertTrue(result["ok"])

    def test_viewer_does_not_call_enrich_or_source_read(self) -> None:
        with patch("pimos_lite.reweave_capsule_content.enrich_capsule_content") as mock_enrich, patch(
            "pimos_lite.reweave_capsule_content.get_source_box"
        ) as mock_box:
            result = get_capsule_content(self.capsule_id)
            self.assertTrue(result["ok"])
            mock_enrich.assert_not_called()
            mock_box.assert_not_called()


if __name__ == "__main__":
    unittest.main()
