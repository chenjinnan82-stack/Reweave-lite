"""Tests for Reweave's Lumo Lite local-state adapter."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_app_service import APP_SERVICE_VERSION, ReweaveAppService
from pimos_lite.reweave_engine.factory import create_reweave_engine
from pimos_lite.reweave_engine.lumo_lite import LumoLiteReweaveEngine, _discard_unpublished_preview
from pimos_lite.reweave_lumo_lite_state import (
    load_lumo_lite_runtime_state,
    lumo_lite_capsule_warehouse,
    map_capsule_warehouse_to_reweave_capsules,
)


class LumoLiteLocalStateAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._root = Path(self._tmpdir.name)
        self._runtime_state = self._root / "frontend_runtime_state.json"
        self._reweave_state = self._root / "reweave-state"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _write_runtime_state(self) -> None:
        payload = {
            "schema_version": "pym_luna_frontend_runtime_state.v0.1",
            "runtime": "PymLiteProgram + LunaLiteProgram",
            "status": "preview_ready",
            "bridge": {"network_call": False, "model_call": False, "watcher": False},
            "capsule_warehouse": {
                "mode": "read_only",
                "status": "ready",
                "source_box_ids": ["box_alpha"],
                "selected_capsules": [
                    {
                        "capsule_id": "capsule_alpha",
                        "title": "Alpha Capsule",
                        "source_box_id": "box_alpha",
                        "reason": "matches task context",
                    }
                ],
                "skipped_capsules": [],
                "trace_path": "/tmp/trace.json",
                "evidence_package_paths": {"evidence": "/tmp/evidence.json"},
                "blocked_reasons": [],
            },
            "capsule_product_acceptance": {
                "line": "Product acceptance: 27/30 | Source writes: 0 | Trace ready: 30/30",
                "accepted_count": 27,
                "reviewable_case_run_count": 30,
                "source_project_write_count": 0,
                "trace_ready": True,
            },
            "lumo_product_base": {
                "status": "ready",
                "product_mode": "small_task_capsule_workbench",
            },
            "lumo_task_pack": {
                "status": "ready",
                "task_scope": "single_file_small_task",
            },
        }
        self._runtime_state.write_text(json.dumps(payload), encoding="utf-8")

    def test_load_runtime_state_from_configured_path(self) -> None:
        self._write_runtime_state()
        result = load_lumo_lite_runtime_state(self._runtime_state)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["state"]["runtime"], "PymLiteProgram + LunaLiteProgram")

    def test_maps_capsule_warehouse_to_read_only_reweave_capsules(self) -> None:
        self._write_runtime_state()
        loaded = load_lumo_lite_runtime_state(self._runtime_state)
        capsules = map_capsule_warehouse_to_reweave_capsules(
            loaded["state"],
            state_path=loaded["path"],
        )
        self.assertEqual(len(capsules), 1)
        cap = capsules[0]
        self.assertEqual(cap["name"], "Alpha Capsule")
        self.assertEqual(cap["status"], "read_only")
        self.assertEqual(cap["origin"], "lumo_lite_capsule_warehouse")
        self.assertEqual(cap["content_mode"], "metadata_only")
        self.assertEqual(cap["source"]["source_id"], "box_alpha")
        self.assertEqual(cap["lumo_lite_receipt"]["warehouse_status"], "ready")
        self.assertEqual(cap["lumo_lite_receipt"]["trace_path"], "/tmp/trace.json")
        self.assertEqual(cap["lumo_lite_receipt"]["evidence_package_paths"], ["/tmp/evidence.json"])
        self.assertIn("frontend_runtime_state", cap["lineage"])

    def test_maps_retrieved_capsules_when_selected_capsules_are_missing(self) -> None:
        payload = {
            "schema_version": "pym_luna_frontend_runtime_state.v0.1",
            "status": "preview_ready",
            "capsule_warehouse": {
                "status": "ready",
                "trace_path": "/tmp/trace.json",
                "retrieved_capsules": [
                    {
                        "capsule_id": "retrieved_alpha",
                        "title": "Retrieved Alpha",
                        "source_box_id": "box_alpha",
                        "reason": "trace-selected fallback",
                    }
                ],
            },
        }
        self._runtime_state.write_text(json.dumps(payload), encoding="utf-8")

        capsules = map_capsule_warehouse_to_reweave_capsules(payload, state_path=str(self._runtime_state))

        self.assertEqual(len(capsules), 1)
        self.assertEqual(capsules[0]["name"], "Retrieved Alpha")
        self.assertEqual(capsules[0]["lumo_lite_receipt"]["capsule_id"], "retrieved_alpha")

    def test_derives_capsules_from_latest_live_report_when_runtime_has_no_warehouse(self) -> None:
        report_dir = self._root / "artifacts" / "dataset" / "case" / "preview"
        report_dir.mkdir(parents=True)
        trace_path = report_dir / "lumo_trace.json"
        trace_path.write_text(
            json.dumps(
                {
                    "capsules_used": [
                        {
                            "capsule_id": "cap_from_report",
                            "title": "Report Capsule",
                            "source_box_id": "box_report",
                            "reason": "latest report trace",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        report_path = self._root / "artifacts" / "dataset" / "report.json"
        report_path.write_text(
            json.dumps({"cases": [{"artifacts": {"trace_path": "artifacts/dataset/case/preview/lumo_trace.json"}}]}),
            encoding="utf-8",
        )
        payload = {
            "schema_version": "pym_luna_frontend_runtime_state.v0.1",
            "status": "preview_ready",
            "capsule_product_acceptance": {"latest_live_report_path": "artifacts/dataset/report.json"},
        }
        self._runtime_state.write_text(json.dumps(payload), encoding="utf-8")

        warehouse = lumo_lite_capsule_warehouse(payload, state_path=str(self._runtime_state))
        capsules = map_capsule_warehouse_to_reweave_capsules(payload, state_path=str(self._runtime_state))

        self.assertEqual(warehouse["selected_count"], 1)
        self.assertEqual(capsules[0]["name"], "Report Capsule")

    def test_lumo_lite_engine_initial_state_is_read_only_and_local(self) -> None:
        self._write_runtime_state()
        with patch.dict(
            os.environ,
            {
                "REWEAVE_STATE_DIR": str(self._reweave_state),
                "REWEAVE_LUMO_LITE_STATE_PATH": str(self._runtime_state),
            },
        ):
            engine = LumoLiteReweaveEngine()
            state = engine.get_initial_state()

        self.assertEqual(state["backend"], "lumo_lite")
        self.assertEqual(state["engine"], "lumo_lite")
        self.assertTrue(state["lumoLiteAvailable"])
        self.assertEqual(state["engineStatus"]["mode"], "source_read_only_preview_write")
        self.assertFalse(state["engineStatus"]["capabilities"]["network_call"])
        self.assertEqual(state["engineStatus"]["capabilities"]["bounded_local_model"], "payload_opt_in")
        self.assertTrue(state["engineStatus"]["capabilities"]["capsule_warehouse_read"])
        self.assertFalse(state["engineStatus"]["capabilities"]["capsule_warehouse_management"])
        self.assertTrue(state["engineStatus"]["capabilities"]["warehouse"])
        self.assertEqual(state["engineStatus"]["capabilities"]["generate_preview"], "task_pack_preview")
        self.assertTrue(state["canGeneratePreview"])
        self.assertTrue(state["canUseBoundedLocalModel"])
        self.assertTrue(state["canChooseSourceFolder"])
        self.assertTrue(state["canScanSourceBox"])
        self.assertTrue(state["canDraftCapsules"])
        self.assertTrue(state["canPromoteDrafts"])
        self.assertEqual(state["lumoLiteRuntimeSummary"]["runtime"], "PymLiteProgram + LunaLiteProgram")
        self.assertTrue(state["lumoLiteRuntimeSummary"]["preview_ready"])
        self.assertEqual(state["lumoLiteRuntimeSummary"]["capsules_used"], 1)
        self.assertTrue(state["lumoLiteRuntimeSummary"]["trace_available"])
        self.assertEqual(state["lumoLiteRuntimeSummary"]["source_project_write_count"], 0)
        self.assertEqual(
            state["lumoLiteRuntimeSummary"]["line"],
            "Product capability: ready · Source writes: 0 · Trace ready",
        )
        self.assertEqual(
            state["lumoLiteRuntimeSummary"]["acceptance_line"],
            "Product acceptance: 27/30 | Source writes: 0 | Trace ready: 30/30",
        )
        self.assertEqual(
            state["lumoLiteRuntimeSummary"]["product_capability_line"],
            "Product capability: ready · Source writes: 0 · Trace ready",
        )
        self.assertEqual(state["lumoLiteRuntimeSummary"]["product_base_status"], "ready")
        self.assertEqual(state["lumoLiteRuntimeSummary"]["task_pack_status"], "ready")
        self.assertEqual(state["lumoLiteRuntimeSummary"]["task_pack_scope"], "single_file_small_task")
        self.assertEqual(len(state["warehouseCapsules"]), 1)
        self.assertEqual(state["warehouseCapsules"][0]["status"], "read_only")
        self.assertFalse(state["useLocalCapsules"])
        self.assertTrue(state["useLumoLiteCapsules"])
        self.assertFalse(state["bridge"]["network_call"])
        self.assertEqual(state["sourceSummaries"], [])
        self.assertEqual(state["capsuleDrafts"], [])
        self.assertNotIn("lastPreview", state)
        self.assertNotIn("generatedPackage", state)
        self.assertNotIn("previewPath", state)

    def test_app_service_lumo_lite_state_does_not_mix_local_warehouse(self) -> None:
        self._write_runtime_state()
        local_capsule = {"id": "local-promoted", "origin": "manual_promote", "status": "active"}
        service = ReweaveAppService(engine=LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state)))

        with patch("pimos_lite.reweave_app_service.list_warehouse_capsules", return_value=[local_capsule]) as local_warehouse:
            state = service.get_initial_state()

        local_warehouse.assert_not_called()
        self.assertEqual(state["appService"], APP_SERVICE_VERSION)
        self.assertEqual(state["engine"], "sqlite_capsule_warehouse")
        self.assertEqual(state["warehouseCapsules"], [])
        self.assertTrue(state["canGenerateProduct"])
        self.assertFalse(state["canGeneratePreview"])

    def test_app_service_lumo_lite_blocks_local_warehouse_management(self) -> None:
        service = ReweaveAppService(engine=LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state)))

        with (
            patch("pimos_lite.reweave_app_service.list_warehouse_capsules") as list_local,
            patch("pimos_lite.reweave_app_service.apply_capsule_status") as update_local,
            patch("pimos_lite.reweave_app_service.execute_promote_review_item") as promote_local,
        ):
            listed = service.list_warehouse_capsules()
            updated = service.update_capsule_status("capsule_alpha", "disabled")
            promoted = service.promote_review_item("box_alpha", "review_alpha")

        self.assertEqual(listed["error"], "lumo_lite_read_only")
        self.assertEqual(updated["error"], "lumo_lite_read_only")
        self.assertEqual(promoted["error"], "lumo_lite_read_only")
        list_local.assert_not_called()
        update_local.assert_not_called()
        promote_local.assert_not_called()

    def test_app_service_lumo_lite_unknown_artifact_path_is_none(self) -> None:
        self._write_runtime_state()
        service = ReweaveAppService(engine=LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state)))

        self.assertIsNone(service.get_lumo_lite_artifact_path("missing-artifact-id"))

    def test_app_service_lumo_lite_blocks_local_state_writers(self) -> None:
        service = ReweaveAppService(engine=LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state)))

        with (
            patch("pimos_lite.reweave_app_service.verify_and_save") as verify_local,
            patch("pimos_lite.reweave_app_service.preview_and_save") as preview_local,
            patch("pimos_lite.reweave_app_service.create_or_update_review_queue") as queue_local,
            patch("pimos_lite.reweave_app_service.apply_review_decision") as decision_local,
            patch("pimos_lite.reweave_app_service.execute_preview_export") as export_local,
        ):
            results = [
                service.verify_source_suggestions("box_alpha"),
                service.preview_governance_for_source("box_alpha"),
                service.create_review_queue_for_source("box_alpha"),
                service.update_review_decision("box_alpha", "review_alpha", "approved"),
                service.export_preview_package("pkg", "/tmp/export", "zip"),
            ]

        self.assertTrue(all(result["error"] == "lumo_lite_read_only" for result in results))
        verify_local.assert_not_called()
        preview_local.assert_not_called()
        queue_local.assert_not_called()
        decision_local.assert_not_called()
        export_local.assert_not_called()

    def test_app_service_lumo_lite_allows_task_pack_preview_and_viewer_reads(self) -> None:
        service = ReweaveAppService(engine=LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state)))

        with (
            patch("pimos_lite.reweave_app_service.fetch_latest_preview_package", return_value={"ok": True}) as latest_local,
            patch("pimos_lite.reweave_app_service.fetch_preview_package", return_value={"ok": True}) as package_local,
            patch("pimos_lite.reweave_app_service.compare_preview_packages_view", return_value={"ok": True}) as compare_local,
        ):
            latest = service.get_latest_preview_package()
            package = service.get_preview_package("pkg")
            compare = service.compare_preview_packages("a", "b")

        self.assertTrue(latest["ok"])
        self.assertTrue(package["ok"])
        self.assertTrue(compare["ok"])
        latest_local.assert_called_once_with()
        package_local.assert_called_once_with("pkg")
        compare_local.assert_called_once_with("a", "b")

    def test_desktop_release_assets_do_not_require_mock_warehouse(self) -> None:
        from pimos_lite import desktop_reweave_static as desktop

        frontend = self._root / "frontend"
        frontend.mkdir()
        for name in ("index.html", "styles.css", "app.js"):
            (frontend / name).write_text("", encoding="utf-8")

        with (
            patch.object(desktop, "REWEAVE_DIR", frontend),
            patch.object(desktop, "REWEAVE_INDEX", frontend / "index.html"),
        ):
            self.assertEqual(desktop.ensure_reweave_assets(), (frontend / "index.html").resolve())

    def test_desktop_shell_starts_on_source_box_onboarding(self) -> None:
        desktop_py = Path(__file__).resolve().parents[1] / "pimos_lite" / "desktop_reweave_static.py"
        text = desktop_py.read_text(encoding="utf-8")

        self.assertIn('url.setQuery("desktop=1")', text)
        self.assertNotIn('url.setQuery("desktop=1&main=1")', text)

    def test_frontend_desktop_capability_defaults_to_closed(self) -> None:
        bridge_js = Path(__file__).resolve().parents[1] / "reweave_frontend" / "bridge.js"
        text = bridge_js.read_text(encoding="utf-8")

        self.assertIn("function desktopCapability(state, name)", text)
        self.assertIn("if (!state) return false;", text)
        self.assertIn("return state[name] === true;", text)

    def test_frontend_lumo_lite_clears_mock_runtime_state(self) -> None:
        app_js = Path(__file__).resolve().parents[1] / "reweave_frontend" / "app.js"
        text = app_js.read_text(encoding="utf-8")

        self.assertIn("function clearLumoLiteMockState()", text)
        self.assertIn("delete data.generatedPackage;", text)
        self.assertIn("data.history = [];", text)
        self.assertIn("data.sampleTask = \"\";", text)
        self.assertIn("if (isLumoLiteState(state))", text)

    def test_lumo_lite_engine_allows_source_intake_without_source_write(self) -> None:
        source = self._root / "source"
        source.mkdir()
        original = "<html><body>Legacy quote shell</body></html>\n"
        (source / "index.html").write_text(original, encoding="utf-8")

        with patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._reweave_state)}):
            engine = LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state))
            box = engine.bind_source_folder(str(source))
            summary = engine.scan_source(box["id"])
            draft = engine.draft_source(box["id"])
            promoted = engine.promote_source(box["id"])
            result = engine.generate_preview(
                {
                    "taskText": "build a quote summary card",
                    "capsuleIds": [promoted[0]["id"]],
                    "capsules": promoted[:1],
                    "sourceBoxes": [box],
                }
            )
            state = engine.get_initial_state()

        self.assertEqual(box["source_project_write"], False)
        self.assertEqual(summary["scan_status"], "scanned")
        self.assertGreaterEqual(summary["counts"]["files_scanned"], 1)
        self.assertGreater(draft["candidate_count"], 0)
        self.assertGreater(len(promoted), 0)
        self.assertEqual(promoted[0]["content_enrichment"]["status"], "enriched")
        self.assertEqual((source / "index.html").read_text(encoding="utf-8"), original)
        self.assertIn(box["id"], {item["id"] for item in state["sourceBoxes"]})
        self.assertIn(box["id"], {item["source_id"] for item in state["sourceSummaries"]})
        self.assertIn(box["id"], {item["source_id"] for item in state["capsuleDrafts"]})
        self.assertIn(box["id"], {item["source_id"] for item in state["warehouseCapsules"] if "source_id" in item})
        preview_root = Path(result["previewPath"])
        self.assertTrue((preview_root / "index.html").is_file())
        self.assertTrue((preview_root / "task_pack.json").is_file())
        task_pack = json.loads((preview_root / "task_pack.json").read_text(encoding="utf-8"))
        self.assertEqual(task_pack["mode"], "task_pack_preview")
        self.assertFalse(task_pack["source_project_write"])
        self.assertEqual(task_pack["selected_capsule_ids"], [promoted[0]["id"]])
        self.assertTrue((preview_root / "snippets_used.json").is_file())
        html = (preview_root / "index.html").read_text(encoding="utf-8")
        review_html = (preview_root / "review.html").read_text(encoding="utf-8")
        self.assertNotIn("Source excerpts used", html)
        self.assertIn("Source excerpts used", review_html)
        self.assertIn("Legacy quote shell", html)

    def test_lumo_lite_engine_builds_task_pack_preview_without_source_write(self) -> None:
        capsule = {
            "id": "capsule_alpha",
            "name": "Alpha Capsule",
            "type": "UI",
            "source_id": "box_alpha",
            "role": "task context",
            "status": "read_only",
            "origin": "lumo_lite_capsule_warehouse",
            "preview": ["Alpha preview"],
        }
        with patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._reweave_state)}):
            engine = LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state))
            result = engine.generate_preview(
                {
                    "taskText": "build a small panel",
                    "capsuleIds": ["capsule_alpha"],
                    "capsules": [capsule],
                }
            )
            viewer = ReweaveAppService(engine=engine).get_preview_package(result["previewPath"])

        root = Path(result["previewPath"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "task_pack_preview")
        self.assertFalse(result["source_project_write"])
        self.assertFalse(result["dispatch"])
        self.assertFalse(result["network_call"])
        self.assertFalse(result["model_call"])
        self.assertFalse(result["localModel"]["enabled"])
        self.assertEqual(
            result["previewAcceptance"],
            {"verdict": "needs_review", "reason": "closed_behavior_unavailable"},
        )
        self.assertIn("task_pack.json", result["generatedPackage"]["files"])
        self.assertTrue((root / "task_pack.json").is_file())
        pack = json.loads((root / "task_pack.json").read_text(encoding="utf-8"))
        self.assertEqual(result["taskPack"], pack)
        self.assertEqual(result["generatedPackage"]["files"].count("task_pack.json"), 1)
        self.assertEqual(pack["mode"], "task_pack_preview")
        self.assertEqual(pack["capsules_used"][0]["id"], "capsule_alpha")
        self.assertIn("task_pack.json", viewer["package"]["files"])

    def test_lumo_lite_engine_owns_auto_capsule_selection(self) -> None:
        capsules = [
            {
                "id": f"{source}-{kind}",
                "name": name,
                "type": kind,
                "source": source,
                "source_id": source,
                "role": "reusable project capability",
                "tags": [],
                "status": "active",
                "content_enrichment": {"status": "enriched"},
            }
            for source in ("content-calendar", "support-ticket-triage")
            for name, kind in (("HTML Surface", "UI"), ("Style Sheet", "Style"), ("Script Module", "Logic"), ("Markdown Doc", "Text"))
        ]
        captured: dict[str, object] = {}

        def build_stub(payload: dict[str, object]) -> dict[str, object]:
            captured.update(payload)
            return {"ok": True, "previewPath": str(self._root), "taskPack": {"selection_mode": "auto_match"}, "provenance": {}}

        with (
            patch("pimos_lite.reweave_engine.lumo_lite.list_local_capsules", return_value=capsules),
            patch(
                "pimos_lite.reweave_engine.lumo_lite.load_capsule_content",
                side_effect=lambda capsule_id: {"behavior_contract": {"status": "closed"}} if capsule_id.endswith("-UI") else {},
            ),
            patch("pimos_lite.reweave_engine.lumo_lite.build_preview_package", side_effect=build_stub),
        ):
            result = LumoLiteReweaveEngine().generate_preview(
                {"taskText": "构建客服工单分流面板", "selectionMode": "auto_match", "useEnrichedContent": True}
            )

        selected = captured["capsules"]
        assert isinstance(selected, list)
        self.assertEqual({cap["source_id"] for cap in selected}, {"support-ticket-triage"})
        self.assertIn("support-ticket-triage-UI", captured["capsuleIds"])
        self.assertTrue(all("_behavior_text" in cap for cap in selected))
        self.assertEqual(result["taskPack"]["selection_mode"], "auto_match")

    def test_lumo_lite_auto_selection_keeps_complete_react_project_capsule(self) -> None:
        capsules = [
            {"id": "box-react", "source_id": "box", "status": "active"},
            {"id": "box-copy", "source_id": "box", "status": "active"},
            {"id": "box-style", "source_id": "box", "status": "active"},
            {"id": "box-data", "source_id": "box", "status": "active"},
        ]
        ranked = capsules[1:]

        with (
            patch("pimos_lite.reweave_engine.lumo_lite.list_local_capsules", return_value=capsules),
            patch(
                "pimos_lite.reweave_engine.lumo_lite.load_capsule_content",
                side_effect=lambda capsule_id: {"project_files_complete": capsule_id == "box-react"},
            ),
            patch("pimos_lite.reweave_engine.lumo_lite.select_capsules_for_task", return_value=ranked),
        ):
            selected = LumoLiteReweaveEngine().select_capsules("Build a React dashboard")

        self.assertEqual([item["id"] for item in selected], ["box-react", "box-copy", "box-style"])

    def test_lumo_lite_engine_owns_preview_acceptance(self) -> None:
        engine = LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state))
        cases = (
            ("enabled", None, "needs_review", "runtime_validation_required"),
            ("enabled", "passed", "usable", "runtime_behavior_verified"),
            ("enabled", "failed", "rejected", "runtime_behavior_failed"),
            ("unavailable", None, "needs_review", "closed_behavior_unavailable"),
        )
        for behavior_status, validation_status, verdict, reason in cases:
            task_pack = {
                "quality_gate": {"status": "passed"},
                "behavior_reuse": {"status": behavior_status},
            }
            if validation_status:
                task_pack["behavior_validation"] = {"status": validation_status}
            with (
                self.subTest(behavior_status=behavior_status, validation_status=validation_status),
                patch(
                    "pimos_lite.reweave_engine.lumo_lite.build_preview_package",
                    return_value={"ok": True, "previewPath": str(self._root), "taskPack": task_pack},
                ),
            ):
                result = engine.generate_preview({"taskText": "Build a small tool"})

            self.assertEqual(result["previewAcceptance"], {"verdict": verdict, "reason": reason})

    def test_preview_acceptance_soft_blocks_semantic_mismatch_after_runtime_passes(self) -> None:
        from pimos_lite.reweave_preview_pack import preview_acceptance

        result = preview_acceptance(
            {
                "quality_gate": {"status": "passed"},
                "behavior_reuse": {"status": "enabled"},
                "behavior_validation": {"status": "passed"},
                "semantic_compatibility": {"status": "needs_review", "missing_capabilities": ["elapsed_time"]},
            }
        )

        self.assertEqual(result, {"verdict": "needs_review", "reason": "semantic_compatibility_needs_review"})

    def test_lumo_lite_engine_rejects_unverified_react_preview(self) -> None:
        engine = LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state))
        for status, verdict, reason in (
            ("failed", "rejected", "react_compile_failed"),
            ("unavailable", "needs_review", "react_compile_not_verified"),
            ("needs_review", "needs_review", "react_compile_not_verified"),
        ):
            task_pack = {
                "quality_gate": {"status": "passed"},
                "react_preview": {"status": status},
                "behavior_reuse": {"status": "enabled"},
                "behavior_validation": {"status": "passed"},
            }
            with (
                self.subTest(status=status),
                patch(
                    "pimos_lite.reweave_engine.lumo_lite.build_preview_package",
                    return_value={"ok": True, "previewPath": str(self._root), "taskPack": task_pack},
                ),
            ):
                result = engine.generate_preview({"taskText": "Build a React tool"})

            self.assertEqual(result["previewAcceptance"], {"verdict": verdict, "reason": reason})

    def test_lumo_lite_engine_requires_react_runtime_validation(self) -> None:
        engine = LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state))
        for validation_status, verdict, reason in (
            (None, "needs_review", "react_runtime_not_verified"),
            ("passed", "usable", "react_runtime_verified"),
            ("failed", "rejected", "react_runtime_failed"),
        ):
            task_pack = {
                "quality_gate": {"status": "passed"},
                "react_preview": {"status": "passed"},
            }
            if validation_status:
                task_pack["react_runtime_validation"] = {"status": validation_status}
            with (
                self.subTest(validation_status=validation_status),
                patch(
                    "pimos_lite.reweave_engine.lumo_lite.build_preview_package",
                    return_value={"ok": True, "previewPath": str(self._root), "taskPack": task_pack},
                ),
            ):
                result = engine.generate_preview({"taskText": "Build a React tool"})

            self.assertEqual(result["previewAcceptance"], {"verdict": verdict, "reason": reason})

    def test_lumo_lite_engine_records_successful_runtime_validation(self) -> None:
        preview_root = self._root / "validated-preview"
        preview_root.mkdir()
        task_pack = {
            "quality_gate": {"status": "passed", "checks": []},
            "behavior_reuse": {"status": "enabled"},
            "runtime_expected_text": "Working tool",
        }
        provenance = {"source_project_write": False}
        (preview_root / "task_pack.json").write_text(json.dumps(task_pack), encoding="utf-8")
        (preview_root / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
        (preview_root / "quality_gate.json").write_text(json.dumps(task_pack["quality_gate"]), encoding="utf-8")
        base_result = {
            "ok": True,
            "previewPath": str(preview_root),
            "generatedPackage": {"files": ["task_pack.json", "provenance.json"]},
            "taskPack": task_pack,
            "provenance": provenance,
        }
        receipt = {
            "schema_version": "reweave_behavior_validation.v1",
            "status": "passed",
            "reason": "observable_state_changed",
            "source_project_write": False,
            "network_call": False,
            "rendered": True,
            "task_text_rendered": True,
            "interaction_present": True,
            "interaction_changed": True,
        }
        with (
            patch("pimos_lite.reweave_engine.lumo_lite.build_preview_package", return_value=base_result),
            patch("pimos_lite.reweave_engine.lumo_lite.validate_preview_behavior", return_value=receipt) as validator,
        ):
            result = LumoLiteReweaveEngine().generate_preview(
                {"taskText": "Build a working tool", "validateRuntime": True}
            )

        self.assertEqual(
            result["previewAcceptance"],
            {"verdict": "usable", "reason": "runtime_behavior_verified"},
        )
        validator.assert_called_once_with(str(preview_root), "Working tool")
        self.assertEqual(result["taskPack"]["quality_gate"]["status"], "passed")
        self.assertEqual(result["runtimeValidation"], receipt)
        self.assertIn("behavior_validation.json", result["generatedPackage"]["files"])
        self.assertEqual(
            json.loads((preview_root / "task_pack.json").read_text(encoding="utf-8"))["behavior_validation"],
            receipt,
        )

    def test_lumo_lite_engine_records_successful_react_runtime_validation(self) -> None:
        preview_root = self._root / "validated-react-preview"
        preview_root.mkdir()
        task_pack = {
            "quality_gate": {"status": "passed", "checks": []},
            "react_preview": {"status": "passed"},
            "product_entry": {"path": "react_project/dist/index.html", "kind": "react_build"},
        }
        provenance = {"source_project_write": False}
        (preview_root / "task_pack.json").write_text(json.dumps(task_pack), encoding="utf-8")
        (preview_root / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
        (preview_root / "quality_gate.json").write_text(json.dumps(task_pack["quality_gate"]), encoding="utf-8")
        base_result = {
            "ok": True,
            "previewPath": str(preview_root),
            "generatedPackage": {"files": ["task_pack.json", "provenance.json"]},
            "taskPack": task_pack,
            "provenance": provenance,
        }
        receipt = {
            "schema_version": "reweave_behavior_validation.v1",
            "status": "passed",
            "reason": "react_declared_state_changed",
            "source_project_write": False,
            "network_call": False,
            "rendered": True,
            "task_text_rendered": True,
            "interaction_present": True,
            "interaction_changed": True,
        }
        with (
            patch("pimos_lite.reweave_engine.lumo_lite.build_preview_package", return_value=base_result),
            patch(
                "pimos_lite.reweave_engine.lumo_lite.validate_react_preview_behavior",
                return_value=receipt,
            ) as react_validator,
            patch("pimos_lite.reweave_engine.lumo_lite.validate_preview_behavior") as static_validator,
        ):
            result = LumoLiteReweaveEngine().generate_preview(
                {"taskText": "Build a working React tool", "validateRuntime": True}
            )

        react_validator.assert_called_once_with(str(preview_root), "Build a working React tool", None)
        static_validator.assert_not_called()
        self.assertEqual(result["previewAcceptance"], {"verdict": "usable", "reason": "react_runtime_verified"})
        self.assertIn("react_runtime_validation.json", result["generatedPackage"]["files"])
        stored = json.loads((preview_root / "task_pack.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["react_runtime_validation"], receipt)
        self.assertEqual(stored["react_preview"]["runtime_validation"], receipt)
        self.assertEqual(stored["quality_gate"]["status"], "passed")

    def test_lumo_lite_engine_returns_rejected_quality_gate_result(self) -> None:
        engine = LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state))
        with patch(
            "pimos_lite.reweave_engine.lumo_lite.build_preview_package",
            side_effect=ValueError("preview quality gate failed"),
        ):
            result = engine.generate_preview({"taskText": "Build a broken tool"})

        self.assertFalse(result["ok"])
        self.assertFalse(result["source_project_write"])
        self.assertEqual(
            result["previewAcceptance"],
            {"verdict": "rejected", "reason": "quality_gate_failed"},
        )

    def test_strict_llm_failure_does_not_publish_latest_or_history(self) -> None:
        state = self._reweave_state
        pending = state / "preview_packages" / "pending"

        def build(payload: dict) -> dict:
            self.assertTrue(payload["deferPublish"])
            pending.mkdir(parents=True)
            task_pack = {"task": "Strict model task", "quality_gate": {"status": "passed"}}
            provenance = {"generated_at": "2026-07-13T00:00:00Z", "source_project_write": False}
            (pending / "task_pack.json").write_text(json.dumps(task_pack), encoding="utf-8")
            (pending / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
            return {
                "ok": True,
                "previewPath": str(pending),
                "previewPublished": False,
                "generatedPackage": {"files": ["task_pack.json", "provenance.json"]},
                "taskPack": task_pack,
                "provenance": provenance,
                "capsulesUsed": [],
            }

        with (
            patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(state)}),
            patch("pimos_lite.reweave_engine.lumo_lite.build_preview_package", side_effect=build),
            patch(
                "pimos_lite.reweave_engine.lumo_lite.apply_ollama_pack",
                return_value={
                    "enabled": True,
                    "status": "failed",
                    "applied": False,
                    "local_http_call": True,
                    "error": "model_unavailable",
                },
            ),
            patch("pimos_lite.reweave_engine.lumo_lite.publish_preview_package") as publish,
        ):
            result = LumoLiteReweaveEngine().generate_preview(
                {
                    "taskText": "Strict model task",
                    "localModel": {"enabled": True, "provider": "ollama", "require": True},
                }
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["previewDiscarded"])
        self.assertFalse(pending.exists())
        self.assertFalse((state / "preview_packages" / "latest.json").exists())
        self.assertFalse((state / "preview_packages" / "index.json").exists())
        publish.assert_not_called()

    def test_unpublished_preview_cleanup_cannot_delete_outside_state(self) -> None:
        outside = self._root / "outside-preview"
        outside.mkdir()
        inside = self._reweave_state / "preview_packages" / "pending"
        inside.mkdir(parents=True)

        with patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._reweave_state)}):
            self.assertFalse(_discard_unpublished_preview(str(outside)))
            self.assertTrue(outside.is_dir())
            self.assertTrue(_discard_unpublished_preview(str(inside)))
            self.assertFalse(inside.exists())

    def test_rescan_refreshes_capsule_content_with_stable_id(self) -> None:
        state = self._reweave_state
        source = self._root / "refresh-source"
        source.mkdir()
        html = source / "index.html"
        html.write_text("<!doctype html><h1>Version One</h1>", encoding="utf-8")
        (source / "styles.css").write_text("body {}", encoding="utf-8")
        (source / "app.js").write_text("console.log('ready');", encoding="utf-8")
        engine = LumoLiteReweaveEngine()

        with patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(state)}):
            box = engine.bind_source_folder(str(source))
            engine.scan_source(box["id"])
            engine.draft_source(box["id"])
            first = engine.promote_source(box["id"])
            page = next(row for row in first if row["name"] == "Page Shell")
            first_id = page["id"]
            first_content = engine.get_capsule_content(first_id)
            self.assertIn("Version One", json.dumps(first_content))

            html.write_text("<!doctype html><h1>Version Two</h1>", encoding="utf-8")
            engine.scan_source(box["id"])
            refreshed_source = engine.get_source(box["id"])
            self.assertEqual(refreshed_source["warehouse_status"], "stale")
            engine.draft_source(box["id"])
            second = engine.promote_source(box["id"])
            refreshed_page = next(row for row in second if row["name"] == "Page Shell")
            second_content = engine.get_capsule_content(refreshed_page["id"])

        self.assertEqual(refreshed_page["id"], first_id)
        self.assertIn("Version Two", json.dumps(second_content))
        self.assertNotIn("Version One", json.dumps(second_content))

    def test_lumo_lite_engine_applies_opt_in_bounded_local_model(self) -> None:
        preview_root = self._root / "preview"
        preview_root.mkdir()
        task_pack = {"behavior_reuse": {"status": "enabled"}}
        provenance = {"content_aware_generate": {"enabled": True}}
        (preview_root / "task_pack.json").write_text(json.dumps(task_pack), encoding="utf-8")
        (preview_root / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
        base_result = {
            "ok": True,
            "previewPath": str(preview_root),
            "taskPack": task_pack,
            "provenance": provenance,
            "snippetContext": {"capsules": []},
        }
        applied_meta = {
            "enabled": True,
            "provider": "ollama",
            "model": "tiny-test",
            "local_http_call": True,
            "external_network_call": False,
            "source_project_write": False,
            "applied": True,
            "fallback_used": False,
            "mode": "bounded_behavior_adaptation",
        }

        def apply_stub(out: Path, **kwargs: object) -> dict[str, object]:
            self.assertEqual(out, preview_root)
            updated_pack = {**task_pack, "llm_generation": applied_meta}
            updated_provenance = {**provenance, "llm_generation": applied_meta}
            (out / "task_pack.json").write_text(json.dumps(updated_pack), encoding="utf-8")
            (out / "provenance.json").write_text(json.dumps(updated_provenance), encoding="utf-8")
            return applied_meta

        engine = LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state))
        with (
            patch("pimos_lite.reweave_engine.lumo_lite.build_preview_package", return_value=base_result),
            patch("pimos_lite.reweave_engine.lumo_lite.apply_ollama_pack", side_effect=apply_stub) as apply_model,
        ):
            result = engine.generate_preview(
                {
                    "taskText": "Build a renovation budget estimator",
                    "capsuleIds": ["capsule_alpha"],
                    "capsules": [{"id": "capsule_alpha"}],
                    "localModel": {
                        "enabled": True,
                        "provider": "ollama",
                        "model": "tiny-test",
                        "baseUrl": "http://127.0.0.1:11434",
                        "timeout": 5,
                    },
                }
            )

        apply_model.assert_called_once()
        self.assertTrue(result["network_call"])
        self.assertTrue(result["model_call"])
        self.assertTrue(result["localModel"]["applied"])
        self.assertEqual(result["taskPack"]["llm_generation"]["mode"], "bounded_behavior_adaptation")
        self.assertEqual(result["provenance"]["llm_generation"]["provider"], "ollama")
        self.assertFalse(result["source_project_write"])

    def test_lumo_lite_engine_applies_explicit_planning_patch_without_copy_pass(self) -> None:
        preview_root = self._root / "planning-preview"
        preview_root.mkdir()
        planning_meta = {
            "enabled": True,
            "provider": "ollama",
            "model": "tiny-test",
            "mode": "bounded_planning",
            "requested_slots": ["intent_patch"],
            "applied_slots": ["intent_patch"],
            "requested_slots_applied": True,
            "local_http_call": True,
            "applied": True,
            "fallback_used": False,
            "status": "applied",
        }
        planning_result = {
            "intent_patch": {"output_type": "page", "capabilities": ["copy", "style"]},
            "ordered_capsule_ids": [],
            "slots": {"intent_patch": {"enabled": True, "applied": True, "status": "applied"}},
            "meta": planning_meta,
        }
        captured: dict[str, object] = {}

        def build_stub(payload: dict[str, object]) -> dict[str, object]:
            captured.update(payload)
            task_pack = {
                "quality_gate": {"status": "passed"},
                "product_entry": {"path": "index.html", "kind": "static_html"},
                "llm_generation": payload["planningModelMeta"],
            }
            return {
                "ok": True,
                "previewPath": str(preview_root),
                "generatedPackage": {"files": []},
                "taskPack": task_pack,
                "provenance": {"llm_generation": payload["planningModelMeta"]},
            }

        with (
            patch("pimos_lite.reweave_engine.lumo_lite.apply_ollama_planning", return_value=planning_result) as plan_model,
            patch("pimos_lite.reweave_engine.lumo_lite.apply_ollama_pack") as copy_model,
            patch("pimos_lite.reweave_engine.lumo_lite.build_preview_package", side_effect=build_stub),
            patch("pimos_lite.reweave_engine.lumo_lite.publish_preview_package") as publish,
        ):
            result = LumoLiteReweaveEngine().generate_preview(
                {
                    "taskText": "Build a portfolio viewer",
                    "capsuleIds": ["cap_a", "cap_b"],
                    "capsules": [{"id": "cap_a"}, {"id": "cap_b"}],
                    "localModel": {
                        "enabled": True,
                        "provider": "ollama",
                        "model": "tiny-test",
                        "intentPatch": True,
                        "require": True,
                    },
                }
            )

        plan_model.assert_called_once()
        copy_model.assert_not_called()
        publish.assert_called_once()
        self.assertEqual(captured["intentPatch"], planning_result["intent_patch"])
        self.assertEqual(result["localModel"]["applied_slots"], ["intent_patch"])
        self.assertTrue(result["model_call"])

    def test_factory_selects_lumo_lite_without_touching_legacy_lumo(self) -> None:
        with patch.dict(os.environ, {"REWEAVE_ENGINE": "lumo_lite"}):
            self.assertIsInstance(create_reweave_engine(), LumoLiteReweaveEngine)

    def test_desktop_bridge_keeps_lumo_lite_blocked_errors_blocked(self) -> None:
        from pimos_lite import desktop_reweave_static as desktop

        class QObject:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

        def Slot(*_args, **_kwargs):
            def decorate(fn):
                return fn

            return decorate

        service = ReweaveAppService(engine=LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state)))

        with (
            patch.object(desktop, "import_qt_bridge", return_value=(QObject, Slot, object)),
        ):
            desktop.ReweaveBridge._qobject_cls = None
            try:
                bridge = desktop.ReweaveBridge.create(service)
                results = [
                    json.loads(bridge.create_review_queue_for_source("box_alpha")),
                    json.loads(bridge.update_review_decision(json.dumps({"sourceId": "box_alpha", "reviewId": "review_alpha", "decision": "approved"}))),
                    json.loads(bridge.promote_review_item(json.dumps({"sourceId": "box_alpha", "reviewId": "review_alpha"}))),
                    json.loads(bridge.list_warehouse_capsules(json.dumps({"include_inactive": True}))),
                    json.loads(bridge.update_capsule_status(json.dumps({"capsuleId": "capsule_alpha", "status": "disabled"}))),
                    json.loads(bridge.preview_governance_for_source("box_alpha")),
                    json.loads(bridge.verify_source_suggestions("box_alpha")),
                    json.loads(bridge.export_preview_package(json.dumps({"packageIdOrPath": "package-alpha", "exportDir": str(self._root), "mode": "zip"}))),
                ]
            finally:
                desktop.ReweaveBridge._qobject_cls = None

        self.assertTrue(all(result["ok"] is False for result in results))
        self.assertTrue(all(result["error"] == "lumo_lite_read_only" for result in results))

    def test_desktop_bridge_lumo_lite_allows_source_intake_only(self) -> None:
        from pimos_lite import desktop_reweave_static as desktop

        class QObject:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

        def Slot(*_args, **_kwargs):
            def decorate(fn):
                return fn

            return decorate

        source = self._root / "source"
        source.mkdir()
        original = "<html></html>\n"
        (source / "index.html").write_text(original, encoding="utf-8")

        class QFileDialog:
            called = False

            @staticmethod
            def getExistingDirectory(*_args, **_kwargs) -> str:
                QFileDialog.called = True
                return str(source)

        service = ReweaveAppService(engine=LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state)))

        with (
            patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._reweave_state)}),
            patch.object(desktop, "import_qt_bridge", return_value=(QObject, Slot, object)),
            patch.object(desktop, "import_qt_webengine", return_value=(object, object, object, object, object, QFileDialog)),
        ):
            desktop.ReweaveBridge._qobject_cls = None
            try:
                bridge = desktop.ReweaveBridge.create(service)
                bound = json.loads(bridge.choose_source_folder())
                scanned = json.loads(bridge.scan_source_box(bound["source"]["id"]))
                drafted = json.loads(bridge.draft_capsules(bound["source"]["id"]))
                stored = json.loads(bridge.promote_source_drafts(bound["source"]["id"]))
                generated = json.loads(
                    bridge.notify_generate(
                        json.dumps(
                            {
                                "task": "Build a desktop small project pack",
                                "capsule_ids": [],
                                "selection_mode": "manual",
                            }
                        )
                    )
                )
            finally:
                desktop.ReweaveBridge._qobject_cls = None

        self.assertTrue(QFileDialog.called)
        self.assertTrue(bound["ok"])
        self.assertTrue(scanned["ok"])
        self.assertTrue(drafted["ok"])
        self.assertTrue(stored["ok"])
        self.assertEqual(stored["capsules"], [])
        self.assertFalse(generated["ok"])
        self.assertEqual(
            generated["error"]["code"], "formal_capsule_selection_required"
        )
        self.assertEqual((source / "index.html").read_text(encoding="utf-8"), original)

    def test_desktop_bridge_lumo_lite_export_does_not_open_folder_chooser(self) -> None:
        from pimos_lite import desktop_reweave_static as desktop

        class QObject:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

        def Slot(*_args, **_kwargs):
            def decorate(fn):
                return fn

            return decorate

        class QFileDialog:
            called = False

            @staticmethod
            def getExistingDirectory(*_args, **_kwargs) -> str:
                QFileDialog.called = True
                raise AssertionError("lumo_lite export must not open a folder chooser")

        service = ReweaveAppService(engine=LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state)))

        with (
            patch.object(desktop, "import_qt_bridge", return_value=(QObject, Slot, object)),
            patch.object(desktop, "import_qt_webengine", return_value=(object, object, object, object, object, QFileDialog)),
        ):
            desktop.ReweaveBridge._qobject_cls = None
            try:
                bridge = desktop.ReweaveBridge.create(service)
                result = json.loads(
                    bridge.choose_export_folder_and_export(
                        json.dumps({"packageIdOrPath": "package-alpha", "mode": "zip"})
                    )
                )
            finally:
                desktop.ReweaveBridge._qobject_cls = None

        self.assertFalse(QFileDialog.called)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "lumo_lite_read_only")

    def test_desktop_bridge_lumo_lite_open_preview_folder_is_blocked(self) -> None:
        from pimos_lite import desktop_reweave_static as desktop

        class QObject:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

        def Slot(*_args, **_kwargs):
            def decorate(fn):
                return fn

            return decorate

        service = ReweaveAppService(engine=LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state)))

        with patch.object(desktop, "import_qt_bridge", return_value=(QObject, Slot, object)):
            desktop.ReweaveBridge._qobject_cls = None
            try:
                bridge = desktop.ReweaveBridge.create(service)
                result = json.loads(bridge.open_preview_folder(str(self._root)))
            finally:
                desktop.ReweaveBridge._qobject_cls = None

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "legacy_preview_open_inactive")

    def test_desktop_bridge_lumo_lite_unknown_artifact_does_not_open_current_directory(self) -> None:
        from pimos_lite import desktop_reweave_static as desktop

        class QObject:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

        def Slot(*_args, **_kwargs):
            def decorate(fn):
                return fn

            return decorate

        self._write_runtime_state()
        service = ReweaveAppService(engine=LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state)))

        with patch.object(desktop, "import_qt_bridge", return_value=(QObject, Slot, object)):
            desktop.ReweaveBridge._qobject_cls = None
            try:
                bridge = desktop.ReweaveBridge.create(service)
                result = json.loads(bridge.open_lumo_lite_artifact("missing-artifact-id"))
            finally:
                desktop.ReweaveBridge._qobject_cls = None

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "artifact_not_found")

    def test_desktop_bridge_lumo_lite_notify_generate_builds_task_pack_preview(self) -> None:
        from pimos_lite import desktop_reweave_static as desktop

        class QObject:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

        def Slot(*_args, **_kwargs):
            def decorate(fn):
                return fn

            return decorate

        service = ReweaveAppService(engine=LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state)))

        with (
            patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._reweave_state)}),
            patch.object(desktop, "import_qt_bridge", return_value=(QObject, Slot, object)),
        ):
            desktop.ReweaveBridge._qobject_cls = None
            try:
                bridge = desktop.ReweaveBridge.create(service)
                result = json.loads(
                    bridge.notify_generate(
                        json.dumps(
                            {
                                "taskText": "x",
                                "capsuleIds": ["capsule_alpha"],
                                "capsules": [
                                    {
                                        "id": "capsule_alpha",
                                        "name": "Alpha Capsule",
                                        "type": "UI",
                                        "source_id": "box_alpha",
                                        "status": "read_only",
                                        "origin": "lumo_lite_capsule_warehouse",
                                    }
                                ],
                            }
                        )
                    )
                )
            finally:
                desktop.ReweaveBridge._qobject_cls = None

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "product_task_invalid")


if __name__ == "__main__":
    unittest.main()
