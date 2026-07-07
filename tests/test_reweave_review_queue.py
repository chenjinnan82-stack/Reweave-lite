"""Tests for Reweave manual review queue (Phase 6)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_governance_preview import save_governance_preview
from pimos_lite.reweave_review_queue import (
    build_review_queue,
    create_or_update_review_queue,
    review_queue_file_path,
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
            {
                "id": "luna_asset_prune",
                "name": "Bad Match",
                "origin": "luna_reuse_pack",
                "verification_status": "rejected",
                "verification_score": 0.2,
                "governance_action": "prune",
                "governance_reason": "Rejected",
            },
        ]
    }


class ReweaveReviewQueueTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._env = patch.dict(
            os.environ,
            {
                "REWEAVE_STATE_DIR": str(self._state_dir),
                "REWEAVE_ENGINE": "local",
                "REWEAVE_ENABLE_LEGACY_WORKBENCH": "REWEAVE_LEGACY_WORKBENCH_ACK",
            },
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def test_keep_and_manual_review_enter_queue_as_pending(self) -> None:
        queue = build_review_queue("source_a", _governance_preview())
        ids = {item["suggestion_id"] for item in queue["items"]}
        self.assertIn("luna_asset_keep", ids)
        self.assertIn("luna_asset_review", ids)
        for item in queue["items"]:
            if item["suggestion_id"] in {"luna_asset_keep", "luna_asset_review"}:
                self.assertEqual(item["decision"], "pending")

    def test_watch_enters_queue_as_deferred(self) -> None:
        queue = build_review_queue("source_b", _governance_preview())
        watch_items = [i for i in queue["items"] if i["suggestion_id"] == "luna_asset_watch"]
        self.assertEqual(len(watch_items), 1)
        self.assertEqual(watch_items[0]["decision"], "deferred")

    def test_prune_not_in_queue(self) -> None:
        queue = build_review_queue("source_c", _governance_preview())
        ids = {item["suggestion_id"] for item in queue["items"]}
        self.assertNotIn("luna_asset_prune", ids)
        self.assertEqual(queue["summary"]["total"], 3)

    def test_all_items_warehouse_action_none(self) -> None:
        queue = build_review_queue("source_d", _governance_preview())
        for item in queue["items"]:
            self.assertEqual(item["warehouse_action"], "none")

    def test_update_decision(self) -> None:
        create_or_update_review_queue("source_e", _governance_preview())
        queue = build_review_queue("source_e", _governance_preview())
        review_id = queue["items"][0]["review_id"]
        result = update_review_decision("source_e", review_id, "approved", "looks good")
        self.assertEqual(result["item"]["decision"], "approved")
        self.assertEqual(result["item"]["warehouse_action"], "none")
        self.assertEqual(result["summary"]["approved"], 1)

    def test_regenerate_preserves_decisions(self) -> None:
        create_or_update_review_queue("source_f", _governance_preview())
        first = build_review_queue("source_f", _governance_preview())
        review_id = first["items"][0]["review_id"]
        update_review_decision("source_f", review_id, "rejected", "no")
        second = create_or_update_review_queue("source_f", _governance_preview())
        preserved = next(i for i in second["items"] if i["review_id"] == review_id)
        self.assertEqual(preserved["decision"], "rejected")

    def test_queue_file_in_state_dir(self) -> None:
        create_or_update_review_queue("source_g", _governance_preview())
        path = review_queue_file_path("source_g")
        self.assertTrue(path.is_file())
        self.assertEqual(path.resolve().parent.name, "review_queue")

    def test_without_source_folder(self) -> None:
        registry.add_source_box(str(self._state_dir / "missing" / "project"))
        create_or_update_review_queue("source_h", _governance_preview())
        self.assertTrue(review_queue_file_path("source_h").is_file())

    def test_does_not_modify_warehouse(self) -> None:
        before = warehouse.list_capsules()
        create_or_update_review_queue("source_i", _governance_preview())
        queue = build_review_queue("source_i", _governance_preview())
        update_review_decision("source_i", queue["items"][0]["review_id"], "approved")
        after = warehouse.list_capsules()
        self.assertEqual(before, after)


class ReweaveAppServiceReviewQueueTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._env = patch.dict(
            os.environ,
            {
                "REWEAVE_STATE_DIR": str(self._state_dir),
                "REWEAVE_ENGINE": "local",
                "REWEAVE_ENABLE_LEGACY_WORKBENCH": "REWEAVE_LEGACY_WORKBENCH_ACK",
            },
        )
        self._env.start()
        self.service = ReweaveAppService()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def test_no_governance_preview_error(self) -> None:
        root = self._state_dir / "src-a"
        root.mkdir()
        box = registry.add_source_box(str(root))
        result = self.service.create_review_queue_for_source(box["id"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "no_governance_preview")

    def test_create_review_queue_success(self) -> None:
        root = self._state_dir / "src-b"
        root.mkdir()
        box = registry.add_source_box(str(root))
        save_governance_preview(box["id"], _governance_preview())
        result = self.service.create_review_queue_for_source(box["id"])
        self.assertTrue(result["ok"])
        self.assertIn("summary", result)
        self.assertTrue(review_queue_file_path(box["id"]).is_file())


if __name__ == "__main__":
    unittest.main()
