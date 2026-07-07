"""Tests for Reweave warehouse management (Phase 8)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_engine.lumo import LumoReweaveEngine
from pimos_lite.reweave_luna_client import INDEX_PACK_PATH
from pimos_lite.reweave_promote import build_capsule_from_review_item, promote_review_item
from pimos_lite.reweave_review_queue import create_or_update_review_queue, load_review_queue, update_review_decision
from pimos_lite.reweave_governance_preview import save_governance_preview
from pimos_lite import reweave_capsule_warehouse as warehouse
from pimos_lite import reweave_preview_pack as preview
from pimos_lite import reweave_source_registry as registry
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


class ReweaveWarehouseManagementTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._source_dir = self._state_dir / "user_project"
        self._source_dir.mkdir()
        self._env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._state_dir), "REWEAVE_ENGINE": "local"})
        self._env.start()
        warehouse.clear_warehouse()
        box = registry.add_source_box(str(self._source_dir))
        self.source_id = str(box["id"])
        save_governance_preview(self.source_id, _governance_preview())
        create_or_update_review_queue(self.source_id, _governance_preview())
        queue = load_review_queue(self.source_id)
        assert queue
        self.review_id = queue["items"][0]["review_id"]
        update_review_decision(self.source_id, self.review_id, "approved")
        result = promote_review_item(self.source_id, self.review_id)
        self.capsule_id = str(result["capsule_id"])

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def test_list_warehouse_capsules_returns_promoted(self) -> None:
        caps = warehouse.list_warehouse_capsules()
        self.assertEqual(len(caps), 1)
        cap = caps[0]
        self.assertEqual(cap["id"], self.capsule_id)
        self.assertEqual(cap["origin"], "manual_promote")
        self.assertEqual(cap["risk"], "metadata_only_promoted")
        self.assertIsInstance(cap["source"], dict)
        self.assertEqual(cap["source"]["source_id"], self.source_id)

    def test_get_initial_state_includes_warehouse_capsules(self) -> None:
        service = ReweaveAppService(engine=LocalReweaveEngine())
        state = service.get_initial_state()
        self.assertIn("warehouseCapsules", state)
        self.assertEqual(len(state["warehouseCapsules"]), 1)
        self.assertTrue(state["useLocalCapsules"])
        self.assertEqual(state["capsules"][0]["id"], self.capsule_id)

    def test_disabled_capsule_not_in_generate_resolve(self) -> None:
        warehouse.update_capsule_status(self.capsule_id, "disabled")
        with self.assertRaises(ValueError):
            preview.build_preview_package(
                {"taskText": "Tool", "capsuleIds": [self.capsule_id], "backend": "local"}
            )

    def test_deprecated_capsule_not_in_generate_resolve(self) -> None:
        warehouse.update_capsule_status(self.capsule_id, "deprecated")
        with self.assertRaises(ValueError):
            preview.build_preview_package(
                {"taskText": "Tool", "capsuleIds": [self.capsule_id], "backend": "local"}
            )

    def test_active_capsule_in_generate_payload(self) -> None:
        result = preview.build_preview_package(
            {"taskText": "Form tool", "capsuleIds": [self.capsule_id], "backend": "local"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["capsulesUsed"]), 1)
        self.assertEqual(result["capsulesUsed"][0]["id"], self.capsule_id)

    def test_capsules_used_json_records_lineage(self) -> None:
        result = preview.build_preview_package(
            {"taskText": "Form tool", "capsuleIds": [self.capsule_id], "backend": "local"}
        )
        used_path = Path(result["previewPath"]) / "capsules_used.json"
        used = json.loads(used_path.read_text(encoding="utf-8"))
        self.assertEqual(used[0]["content_mode"], "metadata_snippet")
        self.assertIn("lineage", used[0])

    def test_provenance_records_lineage(self) -> None:
        result = preview.build_preview_package(
            {"taskText": "Form tool", "capsuleIds": [self.capsule_id], "backend": "local"}
        )
        prov_path = Path(result["previewPath"]) / "provenance.json"
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
        self.assertIn("capsules", prov)
        self.assertEqual(prov["capsules"][0]["id"], self.capsule_id)
        self.assertIn("lineage", prov["capsules"][0])

    def test_update_capsule_status_active_to_disabled(self) -> None:
        result = warehouse.update_capsule_status(self.capsule_id, "disabled")
        self.assertTrue(result["ok"])
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        self.assertEqual(cap["status"], "disabled")

    def test_update_capsule_status_allows_ready(self) -> None:
        warehouse.update_capsule_status(self.capsule_id, "disabled")
        result = warehouse.update_capsule_status(self.capsule_id, "ready")

        self.assertTrue(result["ok"])
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        self.assertEqual(cap["status"], "ready")

    def test_update_capsule_status_does_not_delete(self) -> None:
        warehouse.update_capsule_status(self.capsule_id, "deprecated")
        self.assertEqual(len(warehouse.list_capsules()), 1)

    def test_no_source_folder_read(self) -> None:
        missing_root = self._state_dir / "missing" / "project"
        box = registry.add_source_box(str(missing_root))
        source_id = str(box["id"])
        save_governance_preview(source_id, _governance_preview())
        create_or_update_review_queue(source_id, _governance_preview())
        queue = load_review_queue(source_id)
        assert queue
        review_id = queue["items"][0]["review_id"]
        update_review_decision(source_id, review_id, "approved")
        result = promote_review_item(source_id, review_id)
        self.assertTrue(result["ok"])
        cap = warehouse.get_capsule(result["capsule_id"])
        self.assertIsNotNone(cap)

    def test_no_source_folder_write(self) -> None:
        before = {p.name for p in self._source_dir.iterdir()}
        warehouse.update_capsule_status(self.capsule_id, "disabled")
        warehouse.update_capsule_status(self.capsule_id, "active")
        preview.build_preview_package(
            {"taskText": "Tool", "capsuleIds": [self.capsule_id], "backend": "local"}
        )
        after = {p.name for p in self._source_dir.iterdir()}
        self.assertEqual(before, after)

    def test_local_engine_still_available(self) -> None:
        service = ReweaveAppService(engine=LocalReweaveEngine())
        result = service.list_warehouse_capsules()
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)

    def test_lumo_index_pack_payload_includes_capsule_metadata(self) -> None:
        calls: list[dict] = []

        class TrackingClient:
            def health(self) -> dict:
                return {
                    "ok": True,
                    "base_url": "http://127.0.0.1:8766",
                    "status": "available",
                    "endpoint": "/health",
                    "details": {},
                }

            def index_pack(self, payload: dict) -> dict:
                calls.append(payload)
                return {
                    "ok": True,
                    "endpoint": INDEX_PACK_PATH,
                    "pack_id": "luna-pym-wh-001",
                    "manifest_path": "/tmp/luna/handoffs/luna-pym-wh-001.json",
                    "raw": {},
                }

            def reuse_pack(self, payload: dict) -> dict:
                return {"ok": True, "assets": [], "endpoint": "/reuse"}

        local_result = preview.build_preview_package(
            {"taskText": "Form tool", "capsuleIds": [self.capsule_id], "backend": "lumo"}
        )
        engine = LumoReweaveEngine(luna_client=TrackingClient())
        payload = {
            "taskText": "Form tool",
            "capsuleIds": [self.capsule_id],
            "_localPreview": local_result,
        }
        result = engine.generate_preview(payload)
        self.assertTrue(result["ok"])
        self.assertFalse(result["dispatch"])
        self.assertEqual(len(calls), 1)
        self.assertIn("capsules", calls[0])
        self.assertEqual(calls[0]["capsules"][0]["id"], self.capsule_id)
        self.assertIn("lineage", calls[0]["capsules"][0])

    def test_app_service_update_capsule_status(self) -> None:
        service = ReweaveAppService(engine=LocalReweaveEngine())
        result = service.update_capsule_status(self.capsule_id, "disabled")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(len(result["capsules"]), 1)


if __name__ == "__main__":
    unittest.main()
