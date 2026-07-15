"""Tests for Reweave content-aware generate preview (Phase 11)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_capsule_content import content_file_path, enrich_capsule_content
from pimos_lite.reweave_engine.lumo import LumoReweaveEngine
from pimos_lite.reweave_governance_preview import save_governance_preview
from pimos_lite.reweave_promote import promote_review_item
from pimos_lite.reweave_review_queue import create_or_update_review_queue, load_review_queue, update_review_decision
from pimos_lite.reweave_snippet_context import build_snippet_context
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


class ReweaveContentAwareGenerateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._source_dir = self._state_dir / "user_project"
        self._source_dir.mkdir()
        self._env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._state_dir), "REWEAVE_ENGINE": "local"})
        self._env.start()
        warehouse.clear_warehouse()

        (self._source_dir / "index.html").write_text("<!doctype html>" + ("<p>x</p>" * 200), encoding="utf-8")
        (self._source_dir / "app.js").write_text("console.log('" + ("a" * 1500) + "');", encoding="utf-8")
        (self._source_dir / "extra.txt").write_text("y" * 2000, encoding="utf-8")

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

    def test_default_generate_does_not_use_enriched_content(self) -> None:
        result = preview.build_preview_package(
            {"taskText": "Tool", "capsuleIds": [self.capsule_id], "backend": "local"}
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["contentAwareGenerate"]["enabled"])
        self.assertNotIn("snippets_used.json", result["generatedPackage"]["files"])
        prov = json.loads((Path(result["previewPath"]) / "provenance.json").read_text(encoding="utf-8"))
        self.assertFalse(prov["content_aware_generate"]["enabled"])

    def test_use_enriched_reads_app_state_content(self) -> None:
        result = preview.build_preview_package(
            {
                "taskText": "Tool",
                "capsuleIds": [self.capsule_id],
                "backend": "local",
                "useEnrichedContent": True,
            }
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["contentAwareGenerate"]["enabled"])
        self.assertIn("snippets_used.json", result["generatedPackage"]["files"])
        root = Path(result["previewPath"])
        html = (root / "index.html").read_text(encoding="utf-8")
        review_html = (root / "review.html").read_text(encoding="utf-8")
        self.assertNotIn("Source excerpts used", html)
        self.assertIn("Source excerpts used", review_html)
        self.assertIn("&lt;!doctype html&gt;", review_html)
        snippets_used = json.loads(
            (Path(result["previewPath"]) / "snippets_used.json").read_text(encoding="utf-8")
        )
        self.assertGreater(len(snippets_used["snippets"]), 0)
        self.assertNotIn("preview_excerpt", snippets_used["snippets"][0])

    def test_content_aware_without_source_folder(self) -> None:
        shutil.rmtree(self._source_dir)
        result = preview.build_preview_package(
            {
                "taskText": "Tool",
                "capsuleIds": [self.capsule_id],
                "useEnrichedContent": True,
            }
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["contentAwareGenerate"]["enabled"])

    def test_disabled_capsule_content_not_used(self) -> None:
        warehouse.update_capsule_status(self.capsule_id, "disabled")
        ctx = build_snippet_context([self.capsule_id])
        self.assertEqual(len(ctx["capsules"]), 0)
        self.assertTrue(any("skipped_inactive" in w for w in ctx["warnings"]))

    def test_snippet_char_limit(self) -> None:
        ctx = build_snippet_context([self.capsule_id])
        for cap in ctx["capsules"]:
            for snip in cap["snippets"]:
                self.assertLessEqual(snip["excerpt_chars"], 1200)

    def test_behavior_contract_selection_uses_task_relevance(self) -> None:
        capsules = {
            "copy": {
                "id": "copy",
                "name": "Landing Copy",
                "tags": ["copy"],
                "status": "active",
                "content_enrichment": {"status": "enriched"},
            },
            "form": {
                "id": "form",
                "name": "Quote Form",
                "tags": ["form", "quote"],
                "status": "active",
                "content_enrichment": {"status": "enriched"},
            },
        }
        records = {
            cap_id: {
                "snippets": [{"preview": cap["name"], "relative_path": "index.html"}],
                "behavior_contract": {"status": "closed", "entry_path": "index.html"},
            }
            for cap_id, cap in capsules.items()
        }
        with (
            patch("pimos_lite.reweave_snippet_context.get_capsule", side_effect=capsules.get),
            patch("pimos_lite.reweave_snippet_context.is_generate_eligible", return_value=True),
            patch("pimos_lite.reweave_snippet_context.load_capsule_content", side_effect=records.get),
        ):
            ctx = build_snippet_context(["copy", "form"], task="Build a customer quote form")

        self.assertEqual(ctx["behavior_contract"]["selection"]["capsule_id"], "form")

    def test_total_char_limit(self) -> None:
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        cap = dict(cap)
        cap["snippet"] = {"evidence": ["index.html", "app.js", "extra.txt"]}
        warehouse.save_warehouse({"capsules": [cap]})
        enrich_capsule_content(self.capsule_id)
        ctx = build_snippet_context([self.capsule_id])
        total = sum(s["excerpt_chars"] for c in ctx["capsules"] for s in c["snippets"])
        self.assertLessEqual(total, 6000)

    def test_snippets_used_json_written(self) -> None:
        result = preview.build_preview_package(
            {"taskText": "Tool", "capsuleIds": [self.capsule_id], "useEnrichedContent": True}
        )
        path = Path(result["previewPath"]) / "snippets_used.json"
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["source"], "enriched_capsule_content")
        self.assertFalse(data["safety"]["source_folder_read_at_generate_time"])

    def test_provenance_records_content_aware_generate(self) -> None:
        result = preview.build_preview_package(
            {"taskText": "Tool", "capsuleIds": [self.capsule_id], "useEnrichedContent": True}
        )
        prov = json.loads((Path(result["previewPath"]) / "provenance.json").read_text(encoding="utf-8"))
        cag = prov["content_aware_generate"]
        self.assertTrue(cag["enabled"])
        self.assertEqual(cag["snippets_used_path"], "snippets_used.json")
        self.assertFalse(cag["source_folder_read_at_generate_time"])

    def test_capsules_used_still_has_lineage(self) -> None:
        result = preview.build_preview_package(
            {"taskText": "Tool", "capsuleIds": [self.capsule_id], "useEnrichedContent": True}
        )
        used = json.loads((Path(result["previewPath"]) / "capsules_used.json").read_text(encoding="utf-8"))
        self.assertIn("lineage", used[0])
        self.assertNotIn("preview", used[0])

    def test_lumo_index_pack_no_full_snippet(self) -> None:
        local_result = preview.build_preview_package(
            {"taskText": "Tool", "capsuleIds": [self.capsule_id], "useEnrichedContent": True, "backend": "lumo"}
        )
        calls: list[dict] = []

        class TrackingClient:
            def health(self) -> dict:
                return {"ok": True, "base_url": "http://127.0.0.1:8766", "status": "available", "endpoint": "/health", "details": {}}

            def index_pack(self, payload: dict) -> dict:
                calls.append(payload)
                return {"ok": True, "endpoint": "/api/v1/pym/index-pack", "pack_id": "p1", "manifest_path": "/tmp/p1.json", "raw": {}}

            def reuse_pack(self, payload: dict) -> dict:
                return {"ok": True, "assets": []}

        engine = LumoReweaveEngine(luna_client=TrackingClient())
        payload = {"taskText": "Tool", "capsuleIds": [self.capsule_id], "_localPreview": local_result}
        result = engine.generate_preview(payload)
        self.assertTrue(result["ok"])
        self.assertFalse(result["dispatch"])
        cag = calls[0].get("content_aware_generate")
        self.assertTrue(cag and cag.get("enabled"))
        for cap in calls[0].get("capsules", []):
            self.assertNotIn("preview_excerpt", cap)
            self.assertNotIn("snippets", cap)

    def test_false_flag_matches_phase10(self) -> None:
        result = preview.build_preview_package(
            {"taskText": "Tool", "capsuleIds": [self.capsule_id], "useEnrichedContent": False}
        )
        files = result["generatedPackage"]["files"]
        self.assertNotIn("snippets_used.json", files)
        index_html = (Path(result["previewPath"]) / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("capsule metadata only", index_html)

    def test_no_llm_dispatch_or_source_read(self) -> None:
        with patch("pimos_lite.reweave_source_registry.get_source_box") as mock_box, patch(
            "pimos_lite.reweave_capsule_content._read_text_snippet"
        ) as mock_read:
            result = preview.build_preview_package(
                {"taskText": "Tool", "capsuleIds": [self.capsule_id], "useEnrichedContent": True}
            )
            mock_box.assert_not_called()
            mock_read.assert_not_called()
        snippets = json.loads(
            (Path(result["previewPath"]) / "snippets_used.json").read_text(encoding="utf-8")
        )
        self.assertFalse(snippets["safety"]["llm_called"])
        self.assertFalse(snippets["safety"]["dispatch_called"])

    def test_does_not_write_source_folder(self) -> None:
        before = {p.name for p in self._source_dir.iterdir()}
        preview.build_preview_package(
            {"taskText": "Tool", "capsuleIds": [self.capsule_id], "useEnrichedContent": True}
        )
        after = {p.name for p in self._source_dir.iterdir()}
        self.assertEqual(before, after)

    def test_get_capsule_content_not_modified(self) -> None:
        path = content_file_path(self.capsule_id)
        before = path.read_text(encoding="utf-8")
        preview.build_preview_package(
            {"taskText": "Tool", "capsuleIds": [self.capsule_id], "useEnrichedContent": True}
        )
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_app_service_generate_with_enriched_flag(self) -> None:
        service = ReweaveAppService(engine=LocalReweaveEngine())
        result = service.generate_preview(
            {"taskText": "Tool", "capsuleIds": [self.capsule_id], "useEnrichedContent": True}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "legacy_generation_inactive")


if __name__ == "__main__":
    unittest.main()
