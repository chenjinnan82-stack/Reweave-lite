"""Tests for Reweave engine factory and Lumo stub."""

from __future__ import annotations

import os
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_luna_client import DEFAULT_LUNA_BASE_URL, LunaHttpClient, luna_base_url
from pimos_lite.reweave_engine.factory import LEGACY_WORKBENCH_TOKEN, create_reweave_engine, engine_backend_name
from pimos_lite.reweave_engine.local import LocalReweaveEngine
from pimos_lite.reweave_engine.lumo import LumoReweaveEngine
from pimos_lite.reweave_engine.lumo_lite import LumoLiteReweaveEngine


class ReweaveEngineFactoryTest(unittest.TestCase):
    def test_luna_default_base_url_matches_meowbus_luna_port(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(DEFAULT_LUNA_BASE_URL, "http://127.0.0.1:8020")
            self.assertEqual(luna_base_url(), "http://127.0.0.1:8020")

    def test_luna_client_reads_runtime_key_file_for_loopback_requests(self) -> None:
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def read(self) -> bytes:
                return b'{"ok": true}'

        captured_headers: dict[str, str] = {}

        def fake_urlopen(request: urllib.request.Request, timeout: float):
            captured_headers.update({key.lower(): value for key, value in request.header_items()})
            return Response()

        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "admin_api_key"
            key_path.write_text("secret-local-key\n", encoding="utf-8")
            with patch.dict(os.environ, {"PIMOS_ADMIN_API_KEY_FILE": str(key_path)}, clear=True):
                with patch("urllib.request.urlopen", fake_urlopen):
                    result = LunaHttpClient(base_url="http://127.0.0.1:8020").request_json(
                        "POST",
                        "/api/v1/pym/index-pack",
                        {},
                    )

        self.assertTrue(result["ok"])
        self.assertEqual(captured_headers["x-api-key"], "secret-local-key")

    def test_default_backend_is_lumo_lite_bridge(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REWEAVE_ENGINE", None)
            engine = create_reweave_engine()
            self.assertIsInstance(engine, LumoLiteReweaveEngine)
            self.assertEqual(engine_backend_name(), "lumo_lite")

    def test_local_backend_requires_explicit_workbench_token(self) -> None:
        with patch.dict(os.environ, {"REWEAVE_ENGINE": "local"}):
            engine = create_reweave_engine()
            self.assertIsInstance(engine, LumoLiteReweaveEngine)

        with patch.dict(os.environ, {"REWEAVE_ENGINE": "local", "REWEAVE_ENABLE_LEGACY_WORKBENCH": LEGACY_WORKBENCH_TOKEN}):
            engine = create_reweave_engine()
            self.assertIsInstance(engine, LocalReweaveEngine)

    def test_lumo_backend_requires_explicit_workbench_token(self) -> None:
        with patch.dict(os.environ, {"REWEAVE_ENGINE": "lumo", "LUNA_BASE_URL": "http://127.0.0.1:9"}):
            engine = create_reweave_engine()
            self.assertIsInstance(engine, LumoLiteReweaveEngine)

        with patch.dict(os.environ, {"REWEAVE_ENGINE": "lumo", "REWEAVE_ENABLE_LEGACY_WORKBENCH": LEGACY_WORKBENCH_TOKEN, "LUNA_BASE_URL": "http://127.0.0.1:9"}):
            engine = create_reweave_engine()
            self.assertIsInstance(engine, LumoReweaveEngine)
            state = engine.get_initial_state()
            self.assertEqual(state["backend"], "lumo")
            self.assertEqual(state["engine"], "lumo")
            self.assertIn("engineStatus", state)
            self.assertEqual(state["engineStatus"]["engine"], "lumo")
            self.assertFalse(state["lumoAvailable"])
            self.assertTrue(state["canGeneratePreview"])
            self.assertFalse(state["engineStatus"]["capabilities"]["generate_preview"])

    def test_unknown_backend_fails_closed_to_lumo_lite(self) -> None:
        with patch.dict(os.environ, {"REWEAVE_ENGINE": "typo-local"}):
            self.assertIsInstance(create_reweave_engine(), LumoLiteReweaveEngine)

    def test_static_launcher_forces_lumo_lite_and_clears_workbench_env(self) -> None:
        script = Path(__file__).resolve().parents[1] / "start_reweave_static.sh"
        text = script.read_text(encoding="utf-8")

        self.assertIn('export REWEAVE_ENGINE="lumo_lite"', text)
        self.assertIn("unset REWEAVE_ENABLE_LEGACY_WORKBENCH", text)
        self.assertNotIn("REWEAVE_STAGE4_BIN_DIR", text)
        self.assertNotIn(".venv-stage4", text)
        self.assertNotIn("DEFAULT_LUMO_LITE_PRODUCT_STATE=", text)
        self.assertNotIn("DEFAULT_LUMO_LITE_RC4_STATE=", text)
        self.assertNotIn("PIMOS_ADMIN_API_KEY_FILE", text)
        self.assertNotIn('pip" install', text)
        self.assertNotIn("python3 -m venv \"$VENV\"\n  ", text)

    def test_desktop_frontend_navigation_stays_inside_frontend_root(self) -> None:
        from pimos_lite.desktop_reweave_static import _is_frontend_file, _is_preview_image, reweave_index_path

        self.assertTrue(_is_frontend_file(str(reweave_index_path())))
        self.assertFalse(_is_frontend_file(str(Path.home())))
        self.assertFalse(_is_preview_image(str(Path.home() / "preview.png")))

    def test_lumo_available_when_luna_health_ok(self) -> None:
        class HealthyClient:
            def health(self) -> dict:
                return {
                    "ok": True,
                    "base_url": "http://127.0.0.1:8020",
                    "status": "available",
                    "endpoint": "/health",
                    "details": {"status": "ok"},
                }

            def index_pack(self, payload: dict) -> dict:
                return {"ok": False, "endpoint": "/api/v1/pym/index-pack", "error": "unused in status test"}

        engine = LumoReweaveEngine(luna_client=HealthyClient())
        state = engine.get_initial_state()
        self.assertTrue(state["lumoAvailable"])
        self.assertTrue(state["engineStatus"]["available"])
        self.assertTrue(state["engineStatus"]["capabilities"]["health_probe"])
        self.assertTrue(state["canGeneratePreview"])
        self.assertEqual(state["engineStatus"]["capabilities"]["generate_preview"], "pack_only")
        self.assertTrue(state["engineStatus"]["capabilities"]["pym_index_pack"])
        self.assertFalse(state["engineStatus"]["capabilities"]["dispatch"])
        self.assertTrue(state["engineStatus"]["capabilities"]["reuse_pack"])
        self.assertEqual(state["engineStatus"]["capabilities"]["prepare"], "local_plus_luna_reuse_pack")

    def test_lumo_generate_pack_only_when_luna_down(self) -> None:
        class DownClient:
            def health(self) -> dict:
                return {"ok": False, "status": "unavailable", "error": "down"}

            def index_pack(self, payload: dict) -> dict:
                raise AssertionError("index_pack should not be called when health is down")

            def reuse_pack(self, payload: dict) -> dict:
                raise AssertionError("reuse_pack should not be called when health is down")

        engine = LumoReweaveEngine(luna_client=DownClient())
        result = engine.generate_preview({"taskText": "x", "capsuleIds": []})
        self.assertFalse(result["ok"])
        self.assertEqual(result["engine"], "lumo")
        self.assertEqual(result.get("error"), "luna_unavailable")


if __name__ == "__main__":
    unittest.main()
