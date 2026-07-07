"""Tests for Lumo index-pack integration (Phase 2)."""

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
from pimos_lite.reweave_luna_client import INDEX_PACK_PATH, LunaHttpClient
from pimos_lite import reweave_capsule_draft as draft
from pimos_lite import reweave_capsule_warehouse as warehouse
from pimos_lite import reweave_preview_pack as preview
from pimos_lite import reweave_source_registry as registry
from pimos_lite import reweave_source_scanner as scanner


class LunaIndexPackClientTest(unittest.TestCase):
    @patch("pimos_lite.reweave_luna_client.urllib.request.urlopen")
    def test_index_pack_success_parses_pack_id_and_manifest(self, mock_urlopen: MagicMock) -> None:
        payload = {
            "pack_id": "luna-pym-test-001",
            "manifest_path": "/tmp/luna/handoffs/luna-pym-test-001.json",
            "taskbook_text": "PYM-TASKBOOK",
            "index_pack": {"contract": "LUNA-PYM-INDEX-PACK"},
        }
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp

        client = LunaHttpClient(base_url="http://127.0.0.1:8766")
        result = client.index_pack({"query": "demo", "task_goal": "demo", "top_k": 2})
        self.assertTrue(result["ok"])
        self.assertEqual(result["endpoint"], INDEX_PACK_PATH)
        self.assertEqual(result["pack_id"], "luna-pym-test-001")
        self.assertIn("manifest_path", result)
        self.assertIn("raw", result)

    @patch("pimos_lite.reweave_luna_client.urllib.request.urlopen")
    def test_index_pack_network_failure(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        client = LunaHttpClient(base_url="http://127.0.0.1:8766")
        result = client.index_pack({"query": "demo", "top_k": 1})
        self.assertFalse(result["ok"])
        self.assertEqual(result["endpoint"], INDEX_PACK_PATH)
        self.assertIn("error", result)


class LumoGeneratePreviewTest(unittest.TestCase):
    def test_generate_preview_never_calls_dispatch(self) -> None:
        calls: list[tuple[str, str, dict | None]] = []

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
                calls.append(("POST", INDEX_PACK_PATH, payload))
                return {
                    "ok": True,
                    "endpoint": INDEX_PACK_PATH,
                    "pack_id": "luna-pym-track-001",
                    "manifest_path": "/tmp/luna/handoffs/luna-pym-track-001.json",
                    "raw": {},
                }

        engine = LumoReweaveEngine(luna_client=TrackingClient())
        result = engine.generate_preview({"taskText": "Quote tool", "capsuleIds": ["cap_a"]})
        self.assertTrue(result["ok"])
        self.assertFalse(result["dispatch"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], INDEX_PACK_PATH)
        self.assertNotIn("/api/v1/pym/dispatch", [c[1] for c in calls])

    def test_generate_preview_luna_unavailable(self) -> None:
        class DownClient:
            def health(self) -> dict:
                return {
                    "ok": False,
                    "base_url": "http://127.0.0.1:8766",
                    "status": "unavailable",
                    "error": "connection refused",
                }

            def index_pack(self, payload: dict) -> dict:
                raise AssertionError("index_pack must not run when health fails")

        engine = LumoReweaveEngine(luna_client=DownClient())
        result = engine.generate_preview({"taskText": "x", "capsuleIds": []})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "luna_unavailable")
        self.assertTrue(result.get("fallbackRecommended"))


class LumoAppServiceGenerateTest(unittest.TestCase):
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

    def _promote_capsules(self) -> list[str]:
        root = self._state_dir / "source-project"
        root.mkdir()
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        (root / "app.py").write_text("# app", encoding="utf-8")
        box = registry.add_source_box(str(root))
        scanner.scan_source_box(box["id"])
        draft.draft_capsules(box["id"])
        promoted = warehouse.promote_source_drafts(box["id"])
        return [c["id"] for c in promoted]

    def test_lumo_generate_local_fallback_when_luna_down(self) -> None:
        class DownClient:
            def health(self) -> dict:
                return {
                    "ok": False,
                    "base_url": "http://127.0.0.1:8766",
                    "status": "unavailable",
                    "error": "down",
                }

            def index_pack(self, payload: dict) -> dict:
                raise AssertionError("index_pack must not run when health fails")

        service = ReweaveAppService(engine=LumoReweaveEngine(luna_client=DownClient()))
        cap_ids = self._promote_capsules()
        result = service.generate_preview(
            {"taskText": "Fallback preview", "capsuleIds": cap_ids[:1], "sourceBoxes": []}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["engine"], "lumo")
        self.assertIn("luna_index_pack_failed", result.get("warnings") or [])
        self.assertTrue(Path(result["previewPath"]).is_dir())

    def test_provenance_records_luna_pack_on_success(self) -> None:
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
                return {
                    "ok": True,
                    "endpoint": INDEX_PACK_PATH,
                    "pack_id": "luna-pym-prov-001",
                    "manifest_path": "/tmp/luna/handoffs/luna-pym-prov-001.json",
                    "raw": {},
                }

        service = ReweaveAppService(engine=LumoReweaveEngine(luna_client=HealthyClient()))
        cap_ids = self._promote_capsules()
        result = service.generate_preview(
            {"taskText": "Pack provenance", "capsuleIds": cap_ids[:1], "sourceBoxes": []}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["lunaPack"]["pack_id"], "luna-pym-prov-001")
        prov = json.loads((Path(result["previewPath"]) / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(prov["luna"]["pack_id"], "luna-pym-prov-001")
        self.assertFalse(prov["luna"]["dispatch"])

    def test_provenance_records_luna_failure(self) -> None:
        class FailPackClient:
            def health(self) -> dict:
                return {
                    "ok": True,
                    "base_url": "http://127.0.0.1:8766",
                    "status": "available",
                    "endpoint": "/health",
                    "details": {},
                }

            def index_pack(self, payload: dict) -> dict:
                return {
                    "ok": False,
                    "endpoint": INDEX_PACK_PATH,
                    "error": "timeout",
                }

        service = ReweaveAppService(engine=LumoReweaveEngine(luna_client=FailPackClient()))
        cap_ids = self._promote_capsules()
        result = service.generate_preview(
            {"taskText": "Pack failure", "capsuleIds": cap_ids[:1], "sourceBoxes": []}
        )
        self.assertTrue(result["ok"])
        prov = json.loads((Path(result["previewPath"]) / "provenance.json").read_text(encoding="utf-8"))
        self.assertFalse(prov["luna"]["ok"])
        self.assertEqual(prov["luna"]["error"], "timeout")

    def test_does_not_write_user_source_folder(self) -> None:
        class HealthyClient:
            def health(self) -> dict:
                return {"ok": True, "base_url": "http://127.0.0.1:8766", "status": "available", "endpoint": "/health", "details": {}}

            def index_pack(self, payload: dict) -> dict:
                return {
                    "ok": True,
                    "endpoint": INDEX_PACK_PATH,
                    "pack_id": "luna-pym-src-001",
                    "manifest_path": "/tmp/luna/handoffs/luna-pym-src-001.json",
                    "raw": {},
                }

        root = self._state_dir / "user-source"
        root.mkdir()
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        before = set(root.iterdir())
        box = registry.add_source_box(str(root))
        scanner.scan_source_box(box["id"])
        draft.draft_capsules(box["id"])
        promoted = warehouse.promote_source_drafts(box["id"])

        service = ReweaveAppService(engine=LumoReweaveEngine(luna_client=HealthyClient()))
        service.generate_preview(
            {"taskText": "Source safety", "capsuleIds": [promoted[0]["id"]], "sourceBoxes": []}
        )
        after = set(root.iterdir())
        self.assertEqual(before, after)


class LocalEngineUnchangedTest(unittest.TestCase):
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

    def test_local_engine_generate_unchanged(self) -> None:
        root = self._state_dir / "local-source"
        root.mkdir()
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        box = registry.add_source_box(str(root))
        scanner.scan_source_box(box["id"])
        draft.draft_capsules(box["id"])
        promoted = warehouse.promote_source_drafts(box["id"])

        service = ReweaveAppService()
        result = service.generate_preview(
            {"taskText": "Local only", "capsuleIds": [promoted[0]["id"]], "backend": "local"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result.get("backend"), "local")
        self.assertNotIn("lunaPack", result)
        prov = json.loads((Path(result["previewPath"]) / "provenance.json").read_text(encoding="utf-8"))
        self.assertNotIn("luna", prov)


if __name__ == "__main__":
    unittest.main()
