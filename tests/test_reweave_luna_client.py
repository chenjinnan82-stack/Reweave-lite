"""Tests for Luna HTTP client and lumo engine health integration."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from pimos_lite.reweave_engine.local import LocalReweaveEngine
from pimos_lite.reweave_engine.lumo import LumoReweaveEngine
from pimos_lite.reweave_luna_client import (
    DEFAULT_LUNA_BASE_URL,
    LunaHttpClient,
    luna_base_url,
)


class LunaBaseUrlTest(unittest.TestCase):
    def test_default_base_url(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LUNA_BASE_URL", None)
            self.assertEqual(luna_base_url(), DEFAULT_LUNA_BASE_URL)
            client = LunaHttpClient()
            self.assertEqual(client.base_url, DEFAULT_LUNA_BASE_URL)

    def test_luna_base_url_env(self) -> None:
        with patch.dict(os.environ, {"LUNA_BASE_URL": "http://localhost:9999/"}):
            self.assertEqual(luna_base_url(), "http://localhost:9999")
            client = LunaHttpClient()
            self.assertEqual(client.base_url, "http://localhost:9999")


class LunaHttpClientHealthTest(unittest.TestCase):
    def test_health_connection_failure_returns_structured_error(self) -> None:
        client = LunaHttpClient(base_url="http://127.0.0.1:1", timeout_seconds=0.2)
        result = client.health()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("error", result)
        self.assertEqual(result["base_url"], "http://127.0.0.1:1")

    @patch("pimos_lite.reweave_luna_client.urllib.request.urlopen")
    def test_health_success_on_first_probe(self, mock_urlopen: MagicMock) -> None:
        payload = json.dumps({"status": "ok", "vector_db_loaded": True}).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = payload
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp

        client = LunaHttpClient(base_url="http://127.0.0.1:8766")
        result = client.health()
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["endpoint"], "/health")
        self.assertEqual(result["details"]["status"], "ok")


class LunaHttpClientRequestJsonTest(unittest.TestCase):
    @patch("pimos_lite.reweave_luna_client.urllib.request.urlopen")
    def test_request_json_invalid_json(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = b"not-json"
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp

        client = LunaHttpClient(base_url="http://127.0.0.1:8766")
        result = client.request_json("GET", "/health")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid json response")

    @patch("pimos_lite.reweave_luna_client.urllib.request.urlopen")
    def test_request_json_timeout(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.side_effect = TimeoutError("timed out")
        client = LunaHttpClient(base_url="http://127.0.0.1:8766", timeout_seconds=0.1)
        result = client.request_json("GET", "/health")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "timeout")

    @patch("pimos_lite.reweave_luna_client.urllib.request.urlopen")
    def test_request_json_connection_error(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        client = LunaHttpClient(base_url="http://127.0.0.1:8766")
        result = client.request_json("GET", "/health")
        self.assertFalse(result["ok"])
        self.assertIn("connection refused", result["error"])


class LumoEngineStatusTest(unittest.TestCase):
    def test_lumo_unavailable_when_luna_down(self) -> None:
        class DownClient:
            def health(self) -> dict:
                return {
                    "ok": False,
                    "base_url": "http://127.0.0.1:8766",
                    "status": "unavailable",
                    "error": "connection refused",
                }

            def index_pack(self, payload: dict) -> dict:
                return {"ok": False, "endpoint": "/api/v1/pym/index-pack", "error": "down"}

            def reuse_pack(self, payload: dict) -> dict:
                return {"ok": False, "endpoint": "/api/v1/reuse/pack", "error": "down"}

        engine = LumoReweaveEngine(luna_client=DownClient())
        status = engine.get_status()
        self.assertEqual(status["engine"], "lumo")
        self.assertFalse(status["available"])
        self.assertFalse(status["capabilities"]["generate_preview"])
        self.assertFalse(status["capabilities"]["health_probe"])

        state = engine.get_initial_state()
        self.assertFalse(state["lumoAvailable"])
        self.assertTrue(state["canGeneratePreview"])
        self.assertEqual(state["engineStatus"]["engine"], "lumo")

    def test_local_engine_status_unaffected_by_luna(self) -> None:
        with patch.dict(os.environ, {"LUNA_BASE_URL": "http://127.0.0.1:59999"}):
            state = LocalReweaveEngine().get_initial_state()
        self.assertEqual(state["engine"], "local")
        self.assertTrue(state["engineStatus"]["available"])
        self.assertTrue(state["engineStatus"]["capabilities"]["generate_preview"])
        self.assertNotIn("luna", state["engineStatus"])


if __name__ == "__main__":
    unittest.main()
