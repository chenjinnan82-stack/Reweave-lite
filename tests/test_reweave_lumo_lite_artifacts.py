"""Tests for Lumo Lite local artifact viewer helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pimos_lite.reweave_lumo_lite_artifacts import (
    collect_lumo_lite_artifacts,
    get_lumo_lite_artifact,
)
from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_engine.lumo_lite import LumoLiteReweaveEngine


class LumoLiteArtifactsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._root = Path(self._tmpdir.name)
        self._state = self._root / ".runtime"
        self._preview = self._state / "preview"
        self._state.mkdir()
        self._preview.mkdir()
        self._trace = self._state / "lumo_trace.json"
        self._evidence = self._state / "evidence.json"
        self._index = self._preview / "index.html"
        self._trace.write_text(json.dumps({"trace": "ok"}), encoding="utf-8")
        self._evidence.write_text(json.dumps({"evidence": ["a"]}), encoding="utf-8")
        self._index.write_text("<html>preview</html>", encoding="utf-8")
        self._runtime_state = self._state / "frontend_runtime_state.json"
        self._runtime_state.write_text(
            json.dumps(
                {
                    "schema_version": "pym_luna_frontend_runtime_state.v0.1",
                    "paths": {
                        "preview_root": str(self._preview),
                        "output_dir": str(self._state),
                        "old_project_root": str(self._root / "source"),
                    },
                    "bridge": {"network_call": False},
                    "pym_window": {
                        "preview_artifacts": [
                            {"path": "index.html", "preview_only": True},
                            {"path": "missing.js", "preview_only": True},
                        ],
                    },
                    "capsule_warehouse": {
                        "status": "written",
                        "trace_path": str(self._trace),
                        "evidence_package_paths": {"evidence": str(self._evidence)},
                        "selected_capsules": [],
                    },
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_collects_referenced_artifacts_only(self) -> None:
        result = collect_lumo_lite_artifacts(self._runtime_state)
        self.assertTrue(result["ok"])
        kinds = {row["kind"] for row in result["artifacts"]}
        self.assertIn("runtime_state", kinds)
        self.assertIn("preview_root", kinds)
        self.assertIn("output_dir", kinds)
        self.assertIn("trace", kinds)
        self.assertIn("evidence", kinds)
        self.assertIn("preview_artifact", kinds)
        paths = {row["path"] for row in result["artifacts"]}
        self.assertNotIn(str(self._root / "source"), paths)
        self.assertFalse(result["safety"]["source_folder_written"])
        self.assertFalse(result["safety"]["network_called"])

    def test_missing_artifacts_are_reported_without_error(self) -> None:
        result = collect_lumo_lite_artifacts(self._runtime_state)
        missing = [row for row in result["artifacts"] if row["basename"] == "missing.js"]
        self.assertEqual(len(missing), 1)
        self.assertFalse(missing[0]["exists"])
        self.assertEqual(missing[0]["summary"], "missing")

    def test_get_artifact_reads_bounded_json_preview(self) -> None:
        listing = collect_lumo_lite_artifacts(self._runtime_state)
        trace = next(row for row in listing["artifacts"] if row["kind"] == "trace")
        detail = get_lumo_lite_artifact(trace["id"], self._runtime_state)
        self.assertTrue(detail["ok"])
        self.assertEqual(detail["artifact"]["json_preview"], {"trace": "ok"})
        self.assertIn('"trace": "ok"', detail["artifact"]["text_preview"])
        self.assertFalse(detail["artifact"]["truncated"])

    def test_get_directory_artifact_lists_entries(self) -> None:
        listing = collect_lumo_lite_artifacts(self._runtime_state)
        preview = next(row for row in listing["artifacts"] if row["kind"] == "preview_root")
        detail = get_lumo_lite_artifact(preview["path"], self._runtime_state)
        self.assertTrue(detail["ok"])
        names = {row["name"] for row in detail["artifact"]["directory_entries"]}
        self.assertIn("index.html", names)

    def test_unknown_artifact_is_rejected(self) -> None:
        result = get_lumo_lite_artifact(str(self._root / "source" / "secret.py"), self._runtime_state)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "artifact_not_found")

    def test_preview_artifact_path_cannot_escape_preview_root(self) -> None:
        outside = self._root / "outside.txt"
        outside.write_text("outside secret", encoding="utf-8")
        state = json.loads(self._runtime_state.read_text(encoding="utf-8"))
        state["pym_window"]["preview_artifacts"].append({"path": "../outside.txt", "preview_only": True})
        state["pym_window"]["preview_artifacts"].append({"path": str(outside), "preview_only": True})
        self._runtime_state.write_text(json.dumps(state), encoding="utf-8")

        listing = collect_lumo_lite_artifacts(self._runtime_state)
        paths = {row["path"] for row in listing["artifacts"]}
        self.assertNotIn(str(outside.resolve()), paths)
        detail = get_lumo_lite_artifact(str(outside.resolve()), self._runtime_state)
        self.assertFalse(detail["ok"])
        self.assertEqual(detail["error"], "artifact_not_found")

    def test_runtime_state_preview_root_cannot_add_untrusted_artifact_root(self) -> None:
        outside_preview = self._root / "outside-preview"
        outside_preview.mkdir()
        secret = outside_preview / "secret.html"
        secret.write_text("<html>secret</html>", encoding="utf-8")
        state = json.loads(self._runtime_state.read_text(encoding="utf-8"))
        state["paths"]["preview_root"] = str(outside_preview)
        state["pym_window"]["preview_artifacts"] = [{"path": "secret.html", "preview_only": True}]
        self._runtime_state.write_text(json.dumps(state), encoding="utf-8")

        listing = collect_lumo_lite_artifacts(self._runtime_state)
        paths = {row["path"] for row in listing["artifacts"]}

        self.assertNotIn(str(outside_preview.resolve()), paths)
        self.assertNotIn(str(secret.resolve()), paths)
        detail = get_lumo_lite_artifact(str(secret.resolve()), self._runtime_state)
        self.assertFalse(detail["ok"])
        self.assertEqual(detail["error"], "artifact_not_found")

    def test_state_referenced_artifacts_must_stay_under_allowed_roots(self) -> None:
        outside = self._root / "outside-trace.json"
        outside.write_text(json.dumps({"secret": True}), encoding="utf-8")
        state = json.loads(self._runtime_state.read_text(encoding="utf-8"))
        state["capsule_warehouse"]["trace_path"] = str(outside)
        state["capsule_warehouse"]["evidence_package_paths"] = {"outside": str(outside)}
        self._runtime_state.write_text(json.dumps(state), encoding="utf-8")

        listing = collect_lumo_lite_artifacts(self._runtime_state)
        paths = {row["path"] for row in listing["artifacts"]}
        self.assertTrue(listing["safety"]["root_allowlist_enforced"])
        self.assertNotIn(str(outside.resolve()), paths)
        detail = get_lumo_lite_artifact(str(outside.resolve()), self._runtime_state)
        self.assertFalse(detail["ok"])
        self.assertEqual(detail["error"], "artifact_not_found")

    def test_plain_state_folder_does_not_allow_sibling_artifacts(self) -> None:
        state_dir = self._root / "state"
        state_dir.mkdir()
        runtime_state = state_dir / "frontend_runtime_state.json"
        outside = self._root / "outside-trace.json"
        outside.write_text(json.dumps({"secret": True}), encoding="utf-8")
        runtime_state.write_text(
            json.dumps(
                {
                    "schema_version": "pym_luna_frontend_runtime_state.v0.1",
                    "paths": {"output_dir": str(state_dir)},
                    "capsule_warehouse": {"trace_path": str(outside)},
                }
            ),
            encoding="utf-8",
        )

        listing = collect_lumo_lite_artifacts(runtime_state)
        paths = {row["path"] for row in listing["artifacts"]}

        self.assertNotIn(str(outside.resolve()), paths)
        detail = get_lumo_lite_artifact(str(outside.resolve()), runtime_state)
        self.assertFalse(detail["ok"])
        self.assertEqual(detail["error"], "artifact_not_found")

    def test_lumo_lite_engine_exposes_artifacts_in_initial_state(self) -> None:
        engine = LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state))
        state = engine.get_initial_state()
        self.assertEqual(state["engine"], "lumo_lite")
        self.assertGreaterEqual(len(state["lumoLiteArtifacts"]), 5)
        self.assertFalse(state["engineStatus"]["capabilities"]["network_call"])

        listing = engine.list_lumo_lite_artifacts()
        trace = next(row for row in listing["artifacts"] if row["kind"] == "trace")
        detail = engine.get_lumo_lite_artifact(trace["id"])
        self.assertTrue(detail["ok"])
        self.assertEqual(detail["artifact"]["json_preview"], {"trace": "ok"})

    def test_app_service_delegates_lumo_lite_artifact_viewer(self) -> None:
        service = ReweaveAppService(engine=LumoLiteReweaveEngine(runtime_state_path=str(self._runtime_state)))
        listing = service.list_lumo_lite_artifacts()
        self.assertTrue(listing["ok"])
        trace = next(row for row in listing["artifacts"] if row["kind"] == "trace")
        detail = service.get_lumo_lite_artifact(trace["id"])
        self.assertTrue(detail["ok"])
        self.assertEqual(detail["artifact"]["json_preview"], {"trace": "ok"})


if __name__ == "__main__":
    unittest.main()
