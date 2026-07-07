"""Tests for ReweaveAppService initial state."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from pimos_lite.reweave_app_service import APP_SERVICE_VERSION, ReweaveAppService
from pimos_lite.reweave_engine.local import LocalReweaveEngine


class ReweaveAppServiceTest(unittest.TestCase):
    def test_get_initial_state_includes_app_service_and_engine_status(self) -> None:
        service = ReweaveAppService(engine=LocalReweaveEngine())
        state = service.get_initial_state()
        self.assertEqual(state["appService"], APP_SERVICE_VERSION)
        self.assertEqual(state["engine"], "local")
        self.assertIn("engineStatus", state)
        self.assertTrue(state["engineStatus"]["available"])

    def test_lumo_engine_via_service_when_env_set(self) -> None:
        class DownClient:
            def health(self) -> dict:
                return {
                    "ok": False,
                    "base_url": "http://127.0.0.1:8020",
                    "status": "unavailable",
                    "error": "down",
                }

        with patch.dict(os.environ, {"REWEAVE_ENGINE": "lumo"}):
            from pimos_lite.reweave_engine.lumo import LumoReweaveEngine

            service = ReweaveAppService(engine=LumoReweaveEngine(luna_client=DownClient()))
            state = service.get_initial_state()
            self.assertEqual(state["backend"], "lumo")
            self.assertFalse(state["engineStatus"]["available"])


if __name__ == "__main__":
    unittest.main()
