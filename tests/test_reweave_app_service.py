"""Tests for ReweaveAppService initial state."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from pimos_lite.reweave_app_service import (
    APP_SERVICE_VERSION,
    CAPSULE_MANAGEMENT_ACTIONS,
    LEGACY_WORKBENCH_ACTIONS,
    PUBLIC_PRODUCT_ACTIONS,
    SUPPORT_VIEWER_ACTIONS,
    ReweaveAppService,
    legacy_workbench_actions,
    public_product_actions,
    release_boundary_for_action,
)
from pimos_lite.reweave_engine.local import LocalReweaveEngine
from pimos_lite.reweave_engine.lumo_lite import LumoLiteReweaveEngine


class ReweaveAppServiceTest(unittest.TestCase):
    def test_get_initial_state_includes_app_service_and_engine_status(self) -> None:
        service = ReweaveAppService(engine=LocalReweaveEngine())
        state = service.get_initial_state()
        self.assertEqual(state["appService"], APP_SERVICE_VERSION)
        self.assertEqual(state["engine"], "sqlite_capsule_warehouse")
        self.assertIn("engineStatus", state)
        self.assertTrue(state["engineStatus"]["available"])
        self.assertTrue(state["canGenerateProduct"])
        self.assertFalse(state["canGeneratePreview"])

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
            self.assertEqual(state["backend"], "sqlite_capsule_warehouse")
            self.assertTrue(state["engineStatus"]["available"])

    def test_lumo_lite_blocked_service_actions_share_release_boundary_shape(self) -> None:
        service = ReweaveAppService(engine=LumoLiteReweaveEngine())
        results = [
            service.create_review_queue_for_source("source_alpha"),
            service.promote_review_item("source_alpha", "review_alpha"),
            service.list_warehouse_capsules(),
            service.update_capsule_status("capsule_alpha", "disabled"),
            service.export_preview_package("package_alpha", "/tmp/export", "zip"),
        ]

        self.assertEqual(
            {item["action"] for item in results},
            {
                "create_review_queue_for_source",
                "promote_review_item",
                "list_warehouse_capsules",
                "update_capsule_status",
                "export_preview_package",
            },
        )
        self.assertTrue(all(item["ok"] is False for item in results))
        self.assertTrue(all(item["engine"] == "lumo_lite" for item in results))
        self.assertTrue(all(item["mode"] == "source_read_only_preview_write" for item in results))
        self.assertTrue(all(item["error"] == "lumo_lite_read_only" for item in results))
        self.assertTrue(all(item["release_boundary"] == "legacy_workbench" for item in results))

    def test_release_boundaries_are_explicit_and_disjoint(self) -> None:
        self.assertFalse(PUBLIC_PRODUCT_ACTIONS & LEGACY_WORKBENCH_ACTIONS)
        self.assertFalse(PUBLIC_PRODUCT_ACTIONS & SUPPORT_VIEWER_ACTIONS)
        self.assertFalse(LEGACY_WORKBENCH_ACTIONS & SUPPORT_VIEWER_ACTIONS)
        self.assertFalse(CAPSULE_MANAGEMENT_ACTIONS & PUBLIC_PRODUCT_ACTIONS)
        self.assertFalse(CAPSULE_MANAGEMENT_ACTIONS & LEGACY_WORKBENCH_ACTIONS)
        self.assertFalse(CAPSULE_MANAGEMENT_ACTIONS & SUPPORT_VIEWER_ACTIONS)
        self.assertEqual(release_boundary_for_action("generate_product"), "public_product")
        self.assertEqual(
            release_boundary_for_action("analyze_static_web_target"),
            "public_product",
        )
        self.assertEqual(
            release_boundary_for_action("generate_static_web_patch"),
            "public_product",
        )
        self.assertEqual(release_boundary_for_action("generate_preview"), "unknown")
        self.assertEqual(release_boundary_for_action("export_preview_package"), "legacy_workbench")
        self.assertEqual(release_boundary_for_action("get_preview_package"), "support_viewer")
        self.assertEqual(release_boundary_for_action("list_review_items"), "capsule_management")
        self.assertEqual(
            release_boundary_for_action("start_inspect_computation_adapters"),
            "capsule_management",
        )
        self.assertEqual(
            release_boundary_for_action("start_create_computation_adapter"),
            "capsule_management",
        )
        self.assertEqual(
            release_boundary_for_action("register_javascript_computation_source"),
            "capsule_management",
        )
        self.assertEqual(
            release_boundary_for_action("start_scan_javascript_computations"),
            "capsule_management",
        )
        self.assertEqual(release_boundary_for_action("made_up_action"), "unknown")
        self.assertIn("generate_product", public_product_actions())
        self.assertIn("analyze_static_web_target", public_product_actions())
        self.assertIn("generate_static_web_patch", public_product_actions())
        self.assertNotIn("generate_preview", public_product_actions())
        self.assertIn("export_preview_package", legacy_workbench_actions())


if __name__ == "__main__":
    unittest.main()
