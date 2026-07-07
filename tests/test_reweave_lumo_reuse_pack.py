"""Tests for Lumo reuse-pack prepare integration (Phase 3)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_engine.local import LocalReweaveEngine
from pimos_lite.reweave_engine.lumo import LumoReweaveEngine
from pimos_lite.reweave_luna_client import REUSE_PACK_PATH, LunaHttpClient
from pimos_lite.reweave_reuse_suggestions import load_reuse_suggestions, suggestion_file_path
from pimos_lite import reweave_capsule_draft as draft
from pimos_lite import reweave_capsule_warehouse as warehouse
from pimos_lite import reweave_source_registry as registry
from pimos_lite import reweave_source_scanner as scanner


class LunaReusePackClientTest(unittest.TestCase):
    @patch("pimos_lite.reweave_luna_client.urllib.request.urlopen")
    def test_reuse_pack_success_parses_assets(self, mock_urlopen: MagicMock) -> None:
        payload = {
            "query": "demo static web",
            "assets": [
                {"id": "a1", "kind": "qa_lesson", "title": "Form Shell", "score": 0.72, "reuse_hint": "adapt"},
                {"id": "a2", "kind": "ui", "title": "Table View", "score": 0.55},
            ],
            "lessons": [],
        }
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp

        client = LunaHttpClient(base_url="http://127.0.0.1:8766")
        result = client.reuse_pack({"query": "demo", "top_k": 5})
        self.assertTrue(result["ok"])
        self.assertEqual(result["endpoint"], REUSE_PACK_PATH)
        self.assertEqual(len(result["assets"]), 2)
        self.assertEqual(result["assets"][0]["id"], "a1")

    @patch("pimos_lite.reweave_luna_client.urllib.request.urlopen")
    def test_reuse_pack_network_failure(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        client = LunaHttpClient(base_url="http://127.0.0.1:8766")
        result = client.reuse_pack({"query": "demo", "top_k": 2})
        self.assertFalse(result["ok"])
        self.assertEqual(result["endpoint"], REUSE_PACK_PATH)


class LumoPrepareReusePackTest(unittest.TestCase):
    def test_prepare_reuse_pack_never_calls_dispatch_apply_promote(self) -> None:
        calls: list[tuple[str, str]] = []

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
                calls.append(("POST", "/api/v1/pym/index-pack"))
                return {"ok": False, "endpoint": "/api/v1/pym/index-pack", "error": "unused"}

            def reuse_pack(self, payload: dict) -> dict:
                calls.append(("POST", REUSE_PACK_PATH))
                return {
                    "ok": True,
                    "endpoint": REUSE_PACK_PATH,
                    "assets": [
                        {"id": "asset-1", "kind": "ui", "title": "Form Shell Suggestion", "score": 0.72},
                    ],
                    "raw": {"query": payload.get("query")},
                }

        engine = LumoReweaveEngine(luna_client=TrackingClient())
        result = engine.prepare_reuse_pack({"source_id": "source_test"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "reuse_pack_ranking")
        self.assertEqual(len(result["capsuleSuggestions"]), 1)
        suggestion = result["capsuleSuggestions"][0]
        self.assertEqual(suggestion["source"], "luna_reuse_pack")
        self.assertEqual(suggestion["origin"], "luna_reuse_pack")
        self.assertEqual(suggestion["risk"], "suggestion_only")
        self.assertEqual(suggestion["status"], "suggestion")
        endpoints = [path for _, path in calls]
        self.assertIn(REUSE_PACK_PATH, endpoints)
        self.assertNotIn("/api/v1/pym/dispatch", endpoints)
        self.assertNotIn("/api/v1/artifacts/governance/apply-prune", endpoints)
        self.assertNotIn("/api/v1/recovery/promote", endpoints)


class LumoAppServicePrepareTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._env = patch.dict(
            os.environ,
            {"REWEAVE_STATE_DIR": str(self._state_dir), "REWEAVE_ENGINE": "lumo"},
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def _scan_source(self) -> str:
        root = self._state_dir / "prepare-source"
        root.mkdir()
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        (root / "app.py").write_text("# app", encoding="utf-8")
        box = registry.add_source_box(str(root))
        scanner.scan_source_box(box["id"])
        return box["id"]

    def test_lumo_prepare_fallback_when_luna_down(self) -> None:
        class DownClient:
            def health(self) -> dict:
                return {
                    "ok": False,
                    "base_url": "http://127.0.0.1:8766",
                    "status": "unavailable",
                    "error": "down",
                }

            def index_pack(self, payload: dict) -> dict:
                return {"ok": False, "endpoint": "/api/v1/pym/index-pack", "error": "down"}

            def reuse_pack(self, payload: dict) -> dict:
                raise AssertionError("reuse_pack must not run when health fails")

        service = ReweaveAppService(engine=LumoReweaveEngine(luna_client=DownClient()))
        source_id = self._scan_source()
        draft_result = service.draft_source(source_id)
        self.assertIn("candidate_count", draft_result)
        self.assertIn("luna_reuse_pack_failed", draft_result.get("warnings") or [])
        self.assertTrue(suggestion_file_path(source_id).is_file())
        stored = load_reuse_suggestions(source_id)
        assert stored is not None
        self.assertFalse(stored["luna_ok"])

    def test_luna_suggestions_not_in_warehouse(self) -> None:
        class HealthyClient:
            def health(self) -> dict:
                return {
                    "ok": True,
                    "base_url": "http://127.0.0.1:8766",
                    "status": "available",
                    "endpoint": "/health",
                    "details": {},
                }

            def index_pack(self, payload: dict) -> dict:
                return {"ok": False, "endpoint": "/api/v1/pym/index-pack", "error": "unused"}

            def reuse_pack(self, payload: dict) -> dict:
                return {
                    "ok": True,
                    "endpoint": REUSE_PACK_PATH,
                    "assets": [
                        {"id": "luna-asset-1", "kind": "ui", "title": "Luna UI Suggestion", "score": 0.8},
                    ],
                    "raw": {},
                }

        service = ReweaveAppService(engine=LumoReweaveEngine(luna_client=HealthyClient()))
        source_id = self._scan_source()
        draft_result = service.draft_source(source_id)
        suggestions = draft_result.get("capsuleSuggestions") or []
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["risk"], "suggestion_only")

        promoted = service.promote_source(source_id)
        self.assertGreater(len(promoted), 0)
        warehouse_caps = warehouse.list_capsules()
        luna_ids = {s["id"] for s in suggestions}
        for cap in warehouse_caps:
            self.assertNotIn(cap.get("id"), luna_ids)
            self.assertNotEqual(cap.get("source"), "luna_reuse_pack")

    def test_does_not_write_user_source_folder(self) -> None:
        class HealthyClient:
            def health(self) -> dict:
                return {"ok": True, "base_url": "http://127.0.0.1:8766", "status": "available", "endpoint": "/health", "details": {}}

            def index_pack(self, payload: dict) -> dict:
                return {"ok": False, "endpoint": "/api/v1/pym/index-pack", "error": "unused"}

            def reuse_pack(self, payload: dict) -> dict:
                return {
                    "ok": True,
                    "endpoint": REUSE_PACK_PATH,
                    "assets": [{"id": "x1", "kind": "ui", "title": "Suggestion", "score": 0.5}],
                    "raw": {},
                }

        root = self._state_dir / "user-source"
        root.mkdir()
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        before = set(root.iterdir())
        box = registry.add_source_box(str(root))
        scanner.scan_source_box(box["id"])

        service = ReweaveAppService(engine=LumoReweaveEngine(luna_client=HealthyClient()))
        service.draft_source(box["id"])
        service.promote_source(box["id"])
        self.assertEqual(before, set(root.iterdir()))


class LocalPrepareUnchangedTest(unittest.TestCase):
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

    def test_local_draft_unchanged(self) -> None:
        root = self._state_dir / "local-source"
        root.mkdir()
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        box = registry.add_source_box(str(root))
        scanner.scan_source_box(box["id"])

        service = ReweaveAppService()
        draft_result = service.draft_source(box["id"])
        self.assertIn("candidates", draft_result)
        self.assertNotIn("capsuleSuggestions", draft_result)
        self.assertFalse(suggestion_file_path(box["id"]).is_file())


if __name__ == "__main__":
    unittest.main()
