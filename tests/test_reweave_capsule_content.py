"""Tests for Reweave controlled capsule content enrichment (Phase 9)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_capsule_content import (
    collect_candidate_paths,
    content_file_path,
    enrich_capsule_content,
    is_allowed_relative_path,
    redact_secrets,
    resolve_safe_path,
)
from pimos_lite.reweave_engine.lumo import LumoReweaveEngine
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


class ReweaveCapsuleContentTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._source_dir = self._state_dir / "user_project"
        self._source_dir.mkdir()
        self._env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._state_dir), "REWEAVE_ENGINE": "local"})
        self._env.start()
        warehouse.clear_warehouse()

        (self._source_dir / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
        (self._source_dir / "app.js").write_text("console.log('hello');", encoding="utf-8")
        (self._source_dir / "styles.css").write_text("body { margin: 0; }", encoding="utf-8")
        (self._source_dir / ".env").write_text("API_KEY=super-secret-value", encoding="utf-8")
        (self._source_dir / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (self._source_dir / "secrets.pem").write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----", encoding="utf-8")
        (self._source_dir / "large.txt").write_text("x" * 5000, encoding="utf-8")

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

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def test_active_promoted_capsule_can_enrich(self) -> None:
        result = enrich_capsule_content(self.capsule_id)
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["snippet_count"], 1)
        self.assertTrue(content_file_path(self.capsule_id).is_file())

    def test_disabled_capsule_cannot_enrich(self) -> None:
        warehouse.update_capsule_status(self.capsule_id, "disabled")
        result = enrich_capsule_content(self.capsule_id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "capsule_not_active")

    def test_deprecated_capsule_cannot_enrich(self) -> None:
        warehouse.update_capsule_status(self.capsule_id, "deprecated")
        result = enrich_capsule_content(self.capsule_id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "capsule_not_active")

    def test_only_whitelist_extensions_read(self) -> None:
        summary = scanner.load_summary(self.source_id)
        assert summary
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        paths = collect_candidate_paths(cap, summary)
        for rel in paths:
            self.assertTrue(is_allowed_relative_path(rel))
            self.assertFalse(rel.endswith(".png"))
            self.assertFalse(rel.endswith(".pem"))

    def test_binary_file_not_read(self) -> None:
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        cap = dict(cap)
        cap["snippet"] = {"evidence": ["logo.png", "index.html"]}
        summary = scanner.load_summary(self.source_id) or {}
        paths = collect_candidate_paths(cap, summary)
        self.assertIn("index.html", paths)
        self.assertNotIn("logo.png", paths)

    def test_env_and_pem_not_read(self) -> None:
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        cap = dict(cap)
        cap["snippet"] = {"evidence": [".env", "secrets.pem", "app.js"]}
        summary = scanner.load_summary(self.source_id) or {}
        paths = collect_candidate_paths(cap, summary)
        self.assertIn("app.js", paths)
        self.assertNotIn(".env", paths)
        self.assertNotIn("secrets.pem", paths)

    def test_path_traversal_rejected(self) -> None:
        resolved = resolve_safe_path(self._source_dir, "../../etc/passwd")
        self.assertIsNone(resolved)
        self.assertFalse(is_allowed_relative_path("../index.html"))

    def test_per_file_byte_limit(self) -> None:
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        cap = dict(cap)
        cap["snippet"] = {"evidence": ["large.txt"]}
        warehouse.save_warehouse({"capsules": [cap]})
        result = enrich_capsule_content(self.capsule_id)
        self.assertTrue(result["ok"])
        snippet = result["content"]["snippets"][0]
        self.assertLessEqual(snippet["bytes_read"], 4096)
        self.assertTrue(snippet["truncated"])

    def test_total_byte_limit(self) -> None:
        for i in range(6):
            (self._source_dir / f"chunk{i}.txt").write_text("a" * 3000, encoding="utf-8")
        scanner.scan_source_box(self.source_id)
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        cap = dict(cap)
        cap["snippet"] = {"evidence": [f"chunk{i}.txt" for i in range(6)]}
        warehouse.save_warehouse({"capsules": [cap]})
        result = enrich_capsule_content(self.capsule_id)
        self.assertTrue(result["ok"])
        total = sum(s["bytes_read"] for s in result["content"]["snippets"])
        self.assertLessEqual(total, 16000)
        self.assertLessEqual(len(result["content"]["snippets"]), 5)

    def test_secret_redaction(self) -> None:
        text = "API_KEY=sk-abcdefghijklmnop\nBearer deadbeef12345\npassword=secret"
        redacted, was = redact_secrets(text)
        self.assertTrue(was)
        self.assertIn("[REDACTED_SECRET]", redacted)
        self.assertNotIn("sk-abcdefghijklmnop", redacted)

    def test_output_in_capsule_contents(self) -> None:
        enrich_capsule_content(self.capsule_id)
        path = content_file_path(self.capsule_id)
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["mode"], "controlled_snippet_preview")
        self.assertFalse(data["safety"]["source_folder_written"])

    def test_does_not_write_source_folder(self) -> None:
        before = {p.name for p in self._source_dir.iterdir()}
        enrich_capsule_content(self.capsule_id)
        after = {p.name for p in self._source_dir.iterdir()}
        self.assertEqual(before, after)

    def test_warehouse_metadata_updated(self) -> None:
        enrich_capsule_content(self.capsule_id)
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        self.assertEqual(cap.get("content_mode"), "controlled_snippet_preview")
        enrichment = cap.get("content_enrichment")
        assert isinstance(enrichment, dict)
        self.assertEqual(enrichment.get("status"), "enriched")
        self.assertEqual(cap.get("content_risk"), "controlled_snippet_preview")
        self.assertEqual(cap.get("risk"), "metadata_only_promoted")

    def test_generate_does_not_include_full_snippet(self) -> None:
        enrich_capsule_content(self.capsule_id)
        result = preview.build_preview_package(
            {"taskText": "Form tool", "capsuleIds": [self.capsule_id], "backend": "local"}
        )
        used_path = Path(result["previewPath"]) / "capsules_used.json"
        used = json.loads(used_path.read_text(encoding="utf-8"))
        entry = used[0]
        self.assertIn("content_enrichment", entry)
        self.assertNotIn("preview", entry)
        prov = json.loads((Path(result["previewPath"]) / "provenance.json").read_text(encoding="utf-8"))
        self.assertIn("content_path", prov["capsules"][0])
        self.assertNotIn("snippets", prov["capsules"][0])

    def test_source_path_missing_returns_error(self) -> None:
        missing_root = self._state_dir / "gone" / "project"
        box = registry.add_source_box(str(missing_root))
        source_id = str(box["id"])
        cap_id = "cap_missing_path_test"
        warehouse.save_warehouse(
            {
                "capsules": [
                    {
                        "id": cap_id,
                        "name": "Missing Path Capsule",
                        "type": "UI",
                        "status": "active",
                        "source_id": source_id,
                        "source_box": {"source_id": source_id, "label": "gone"},
                        "snippet": {"evidence": ["index.html"]},
                        "risk": "metadata_only_promoted",
                    }
                ]
            }
        )
        result = enrich_capsule_content(cap_id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "source_path_not_found")

    def test_app_service_enrich(self) -> None:
        service = ReweaveAppService(engine=LocalReweaveEngine())
        result = service.enrich_capsule_content(self.capsule_id)
        self.assertTrue(result["ok"])

    def test_lumo_index_pack_carries_enrichment_metadata_not_snippets(self) -> None:
        enrich_capsule_content(self.capsule_id)
        local_result = preview.build_preview_package(
            {"taskText": "Form tool", "capsuleIds": [self.capsule_id], "backend": "lumo"}
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
        result = engine.generate_preview(
            {"taskText": "Form tool", "capsuleIds": [self.capsule_id], "_localPreview": local_result}
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["dispatch"])
        meta = calls[0]["capsules"][0].get("content_enrichment")
        self.assertIsNotNone(meta)
        self.assertNotIn("snippets", calls[0]["capsules"][0])


if __name__ == "__main__":
    unittest.main()
