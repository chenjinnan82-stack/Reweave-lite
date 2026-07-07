"""Tests for Reweave governance preview (Phase 5)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_governance_preview import (
    build_governance_preview,
    governance_preview_file_path,
    preview_and_save,
)
from pimos_lite.reweave_luna_client import GOVERNANCE_PREVIEW_PATH, LunaHttpClient
from pimos_lite.reweave_reuse_suggestions import save_reuse_suggestions
from pimos_lite import reweave_capsule_verifier as verifier_mod
from pimos_lite import reweave_capsule_warehouse as warehouse
from pimos_lite import reweave_source_registry as registry
from pimos_lite import reweave_source_scanner as scanner


def _verification_results() -> list[dict]:
    return [
        {
            "id": "luna_asset_keep",
            "name": "Form Shell Suggestion",
            "origin": "luna_reuse_pack",
            "suggested_type": "UI",
            "verification_status": "verified",
            "verification_score": 0.82,
            "warehouse_action": "none",
        },
        {
            "id": "luna_asset_watch",
            "name": "Table View Suggestion",
            "origin": "luna_reuse_pack",
            "suggested_type": "UI",
            "verification_status": "watch",
            "verification_score": 0.55,
            "warehouse_action": "none",
        },
        {
            "id": "luna_asset_prune",
            "name": "CLI Python Service",
            "origin": "luna_reuse_pack",
            "suggested_type": "Logic",
            "verification_status": "rejected",
            "verification_score": 0.2,
            "warehouse_action": "none",
        },
    ]


class ReweaveGovernancePreviewTest(unittest.TestCase):
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

    def test_verified_high_score_becomes_keep(self) -> None:
        record = build_governance_preview(
            "source_a",
            {"results": [_verification_results()[0]]},
        )
        self.assertEqual(record["results"][0]["governance_action"], "keep")

    def test_watch_becomes_watch(self) -> None:
        record = build_governance_preview(
            "source_b",
            {"results": [_verification_results()[1]]},
        )
        self.assertEqual(record["results"][0]["governance_action"], "watch")

    def test_rejected_becomes_prune(self) -> None:
        record = build_governance_preview(
            "source_c",
            {"results": [_verification_results()[2]]},
        )
        self.assertEqual(record["results"][0]["governance_action"], "prune")

    def test_all_results_have_warehouse_action_none(self) -> None:
        record = build_governance_preview("source_d", {"results": _verification_results()})
        for item in record["results"]:
            self.assertEqual(item["warehouse_action"], "none")
            self.assertEqual(item["risk"], "preview_only")

    def test_preview_without_source_folder(self) -> None:
        missing_root = self._state_dir / "missing" / "project"
        registry.add_source_box(str(missing_root))
        record = build_governance_preview("source_missing", {"results": _verification_results()})
        preview_and_save("source_missing", {"results": _verification_results()})
        self.assertTrue(governance_preview_file_path("source_missing").is_file())
        self.assertTrue(record["limits"]["no_source_content_read"])

    def test_governance_preview_file_in_state_dir(self) -> None:
        preview_and_save("source_store", {"results": _verification_results()})
        path = governance_preview_file_path("source_store")
        self.assertTrue(path.is_file())
        self.assertEqual(path.resolve().parent.name, "governance_previews")

    def test_does_not_modify_warehouse(self) -> None:
        root = self._state_dir / "wh-source"
        root.mkdir()
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        box = registry.add_source_box(str(root))
        scanner.scan_source_box(box["id"])
        before = warehouse.list_capsules()
        preview_and_save("source_wh", {"results": _verification_results()})
        after = warehouse.list_capsules()
        self.assertEqual(before, after)


class ReweaveAppServiceGovernancePreviewTest(unittest.TestCase):
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

    def test_no_verification_error(self) -> None:
        root = self._state_dir / "src-a"
        root.mkdir()
        box = registry.add_source_box(str(root))
        result = self.service.preview_governance_for_source(box["id"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "no_verification")

    def _prepare_verified_source(self) -> str:
        root = self._state_dir / "src-b"
        root.mkdir()
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        box = registry.add_source_box(str(root))
        scanner.scan_source_box(box["id"])
        summary = scanner.load_summary(box["id"])
        assert summary is not None
        save_reuse_suggestions(
            box["id"],
            {
                "mapped_capsuleSuggestions": [
                    {
                        "id": "luna_asset_keep",
                        "name": "Form Shell Suggestion",
                        "type": "UI",
                        "origin": "luna_reuse_pack",
                    }
                ],
                "luna_ok": True,
            },
        )
        verifier_mod.verify_and_save(
            box["id"],
            summary,
            {"mapped_capsuleSuggestions": _verification_results()},
        )
        return box["id"]

    def test_preview_success(self) -> None:
        source_id = self._prepare_verified_source()
        result = self.service.preview_governance_for_source(source_id)
        self.assertTrue(result["ok"])
        self.assertIn("summary", result)
        self.assertTrue(governance_preview_file_path(source_id).is_file())

    @patch.dict(os.environ, {"REWEAVE_ENGINE": "lumo", "REWEAVE_ENABLE_LEGACY_WORKBENCH": "REWEAVE_LEGACY_WORKBENCH_ACK"})
    @patch("pimos_lite.reweave_app_service.LunaHttpClient")
    def test_luna_preview_failure_still_succeeds_locally(self, mock_client_cls: MagicMock) -> None:
        source_id = self._prepare_verified_source()
        mock_client = MagicMock()
        mock_client.health.return_value = {"ok": True}
        mock_client.governance_preview.return_value = {
            "ok": False,
            "endpoint": GOVERNANCE_PREVIEW_PATH,
            "error": "timeout",
        }
        mock_client_cls.return_value = mock_client

        service = ReweaveAppService()
        result = service.preview_governance_for_source(source_id)
        self.assertTrue(result["ok"])
        self.assertIn("luna_governance_preview_failed", result.get("warnings") or [])


class LunaGovernancePreviewClientTest(unittest.TestCase):
    @patch("pimos_lite.reweave_luna_client.urllib.request.urlopen")
    def test_governance_preview_success(self, mock_urlopen: MagicMock) -> None:
        payload = {"prune_plan_id": "prune-plan-1", "total_candidates": 0, "candidates": []}
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp

        client = LunaHttpClient(base_url="http://127.0.0.1:8766")
        result = client.governance_preview({})
        self.assertTrue(result["ok"])
        self.assertEqual(result["endpoint"], GOVERNANCE_PREVIEW_PATH)
        self.assertIn("raw", result)


if __name__ == "__main__":
    unittest.main()
