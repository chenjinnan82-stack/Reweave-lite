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
from pimos_lite.reweave_engine.lumo_lite import LumoLiteReweaveEngine
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
        self.assertEqual(state["engineStatus"]["mode"], "read_only_runtime_artifact_viewer")
        self.assertFalse(state["engineStatus"]["capabilities"]["network_call"])
        self.assertTrue(state["engineStatus"]["capabilities"]["capsule_warehouse_read"])
        self.assertFalse(state["engineStatus"]["capabilities"]["capsule_warehouse_management"])
        self.assertTrue(state["engineStatus"]["capabilities"]["warehouse"])
        self.assertEqual(state["engineStatus"]["capabilities"]["generate_preview"], "task_pack_preview")
        self.assertTrue(state["canGeneratePreview"])
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
        self.assertEqual(state["engine"], "lumo_lite")
        self.assertEqual(len(state["warehouseCapsules"]), 1)
        self.assertEqual(state["warehouseCapsules"][0]["origin"], "lumo_lite_capsule_warehouse")
        self.assertNotEqual(state["warehouseCapsules"][0]["id"], "local-promoted")

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
        app_js = Path(__file__).resolve().parents[1] / "reweave_frontend" / "app.js"
        text = app_js.read_text(encoding="utf-8")

        self.assertIn("if (!desktopShellState) return false;", text)
        self.assertIn("return desktopShellState[name] === true;", text)

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
        self.assertIn("Source excerpts used", html)
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
        self.assertIn("task_pack.json", result["generatedPackage"]["files"])
        self.assertTrue((root / "task_pack.json").is_file())
        pack = json.loads((root / "task_pack.json").read_text(encoding="utf-8"))
        self.assertEqual(pack["mode"], "task_pack_preview")
        self.assertEqual(pack["capsules_used"][0]["id"], "capsule_alpha")
        self.assertIn("task_pack.json", viewer["package"]["files"])

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
                content = json.loads(bridge.get_capsule_content(stored["capsules"][0]["id"]))
                selected = stored["capsules"][:2]
                generated = json.loads(
                    bridge.notify_generate(
                        json.dumps(
                            {
                                "taskText": "Build a desktop small project pack",
                                "capsuleIds": [cap["id"] for cap in selected],
                                "capsules": selected,
                                "selectionMode": "manual",
                                "useEnrichedContent": True,
                            }
                        )
                    )
                )
                latest = json.loads(bridge.get_latest_preview_package())
            finally:
                desktop.ReweaveBridge._qobject_cls = None

        self.assertTrue(QFileDialog.called)
        self.assertTrue(bound["ok"])
        self.assertTrue(scanned["ok"])
        self.assertTrue(drafted["ok"])
        self.assertTrue(stored["ok"])
        self.assertGreater(len(stored["capsules"]), 0)
        self.assertTrue(content["ok"])
        self.assertGreater(content["snippet_count"], 0)
        self.assertTrue(generated["ok"])
        self.assertEqual(generated["taskPack"]["selection_mode"], "manual")
        self.assertFalse(generated["taskPack"]["source_project_write"])
        self.assertIn("task_pack.json", generated["generatedPackage"]["files"])
        self.assertIn("snippets_used.json", generated["generatedPackage"]["files"])
        self.assertTrue(latest["ok"])
        self.assertIn("task_pack.json", latest["package"]["files"])
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
        self.assertEqual(result["error"], "lumo_lite_read_only")

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

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "task_pack_preview")
        self.assertFalse(result["source_project_write"])


if __name__ == "__main__":
    unittest.main()
