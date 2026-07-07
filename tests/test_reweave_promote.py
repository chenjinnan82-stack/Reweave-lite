"""Tests for Reweave explicit promote (Phase 7)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_governance_preview import save_governance_preview
from pimos_lite.reweave_promote import promote_log_path, promote_review_item
from pimos_lite.reweave_review_queue import (
    create_or_update_review_queue,
    load_review_queue,
    update_review_decision,
)
from pimos_lite import reweave_capsule_warehouse as warehouse
from pimos_lite import reweave_source_registry as registry


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
            },
            {
                "id": "luna_asset_review",
                "name": "Table View",
                "origin": "luna_reuse_pack",
                "verification_status": "verified",
                "verification_score": 0.76,
                "governance_action": "needs_manual_review",
                "governance_reason": "Moderate confidence",
            },
            {
                "id": "luna_asset_watch",
                "name": "Docs Pack",
                "origin": "luna_reuse_pack",
                "verification_status": "watch",
                "verification_score": 0.55,
                "governance_action": "watch",
                "governance_reason": "Inconclusive",
            },
        ]
    }


class ReweavePromoteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._source_dir = self._state_dir / "user_project"
        self._source_dir.mkdir()
        self._env = patch.dict(
            os.environ,
            {
                "REWEAVE_STATE_DIR": str(self._state_dir),
                "REWEAVE_ENGINE": "local",
                "REWEAVE_ENABLE_LEGACY_WORKBENCH": "REWEAVE_LEGACY_WORKBENCH_ACK",
            },
        )
        self._env.start()
        warehouse.clear_warehouse()
        box = registry.add_source_box(str(self._source_dir))
        self.source_id = str(box["id"])
        save_governance_preview(self.source_id, _governance_preview())
        create_or_update_review_queue(self.source_id, _governance_preview())
        self.queue = load_review_queue(self.source_id)
        assert self.queue
        self.review_id = self.queue["items"][0]["review_id"]

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def _approve_first(self) -> None:
        update_review_decision(self.source_id, self.review_id, "approved")

    def test_approved_review_item_can_promote(self) -> None:
        self._approve_first()
        result = promote_review_item(self.source_id, self.review_id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["warehouse_action"], "promoted")
        self.assertTrue(result["capsule_id"].startswith("cap_"))

    def test_pending_review_item_cannot_promote(self) -> None:
        result = promote_review_item(self.source_id, self.review_id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "review_item_not_approved")

    def test_rejected_review_item_cannot_promote(self) -> None:
        update_review_decision(self.source_id, self.review_id, "rejected")
        result = promote_review_item(self.source_id, self.review_id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "review_item_not_approved")

    def test_deferred_review_item_cannot_promote(self) -> None:
        watch_item = self.queue["items"][2]
        update_review_decision(self.source_id, watch_item["review_id"], "deferred")
        result = promote_review_item(self.source_id, watch_item["review_id"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "review_item_not_approved")

    def test_promote_adds_warehouse_capsule(self) -> None:
        self._approve_first()
        before = len(warehouse.list_capsules())
        promote_review_item(self.source_id, self.review_id)
        after = len(warehouse.list_capsules())
        self.assertEqual(after, before + 1)

    def test_promote_marks_review_item_promoted(self) -> None:
        self._approve_first()
        result = promote_review_item(self.source_id, self.review_id)
        record = load_review_queue(self.source_id)
        assert record
        item = next(i for i in record["items"] if i["review_id"] == self.review_id)
        self.assertTrue(item.get("promoted"))
        self.assertEqual(item.get("capsule_id"), result["capsule_id"])
        self.assertEqual(item.get("warehouse_action"), "promoted")
        self.assertTrue(item.get("promoted_at"))

    def test_repeat_promote_is_idempotent(self) -> None:
        self._approve_first()
        first = promote_review_item(self.source_id, self.review_id)
        second = promote_review_item(self.source_id, self.review_id)
        self.assertTrue(second.get("already_promoted"))
        self.assertEqual(first["capsule_id"], second["capsule_id"])
        self.assertEqual(len(warehouse.list_capsules()), 1)

    def test_promote_log_jsonl_written(self) -> None:
        self._approve_first()
        promote_review_item(self.source_id, self.review_id)
        log_path = promote_log_path(self.source_id)
        self.assertTrue(log_path.is_file())
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        event = json.loads(lines[0])
        self.assertEqual(event["event"], "promote_to_warehouse")
        self.assertEqual(event["origin"], "manual_promote")
        self.assertFalse(event["safety"]["source_folder_written"])
        self.assertFalse(event["safety"]["source_content_read"])

    def test_capsule_risk_metadata_only_promoted(self) -> None:
        self._approve_first()
        result = promote_review_item(self.source_id, self.review_id)
        cap = warehouse.get_capsule(result["capsule_id"])
        assert cap
        self.assertEqual(cap["risk"], "metadata_only_promoted")

    def test_capsule_content_mode_metadata_snippet(self) -> None:
        self._approve_first()
        result = promote_review_item(self.source_id, self.review_id)
        cap = warehouse.get_capsule(result["capsule_id"])
        assert cap
        self.assertEqual(cap["content_mode"], "metadata_snippet")
        self.assertEqual(cap["snippet"]["kind"], "metadata_summary")

    def test_promote_without_source_folder_path(self) -> None:
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

    def test_promote_does_not_write_source_folder(self) -> None:
        before = {p.name for p in self._source_dir.iterdir()}
        self._approve_first()
        promote_review_item(self.source_id, self.review_id)
        after = {p.name for p in self._source_dir.iterdir()}
        self.assertEqual(before, after)

    def test_promote_does_not_call_luna_apply_dispatch_recovery(self) -> None:
        self._approve_first()
        with patch("pimos_lite.reweave_luna_client.LunaHttpClient") as mock_cls:
            promote_review_item(self.source_id, self.review_id)
        mock_cls.assert_not_called()

    def test_app_service_promote_review_item(self) -> None:
        self._approve_first()
        svc = ReweaveAppService()
        result = svc.promote_review_item(self.source_id, self.review_id)
        self.assertTrue(result["ok"])
        self.assertIn("capsules", result)


if __name__ == "__main__":
    unittest.main()
