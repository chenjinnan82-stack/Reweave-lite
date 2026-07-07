"""Tests for Reweave capsule suggestion verifier (Phase 4)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_capsule_verifier import (
    verification_file_path,
    verify_and_save,
    verify_suggestions,
)
from pimos_lite.reweave_reuse_suggestions import save_reuse_suggestions
from pimos_lite import reweave_capsule_draft as draft_mod
from pimos_lite import reweave_capsule_warehouse as warehouse
from pimos_lite import reweave_source_registry as registry
from pimos_lite import reweave_source_scanner as scanner


def _web_summary(source_id: str, label: str = "demo-web") -> dict:
    return {
        "source_id": source_id,
        "label": label,
        "extensions": {".html": 2, ".css": 1, ".js": 3},
        "entry_candidates": ["index.html", "package.json"],
        "counts": {"files": 12, "dirs": 2},
    }


def _ui_suggestion() -> dict:
    return {
        "id": "luna_asset_ui_1",
        "name": "Form Shell Suggestion",
        "type": "UI",
        "source": "luna_reuse_pack",
        "origin": "luna_reuse_pack",
        "status": "suggestion",
        "confidence": 0.72,
        "risk": "suggestion_only",
        "luna": {"asset_id": "ui-1", "score": 0.72, "kind": "ui", "title": "Form Shell"},
    }


def _python_mismatch_suggestion() -> dict:
    return {
        "id": "luna_asset_py_9",
        "name": "CLI Python Service",
        "type": "Logic",
        "source": "luna_reuse_pack",
        "origin": "luna_reuse_pack",
        "status": "suggestion",
        "confidence": 0.4,
        "risk": "suggestion_only",
        "luna": {"asset_id": "py-9", "score": 0.4, "kind": "backend", "title": "CLI Python Service"},
    }


class ReweaveCapsuleVerifierTest(unittest.TestCase):
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

    def _save_summary(self, source_id: str, summary: dict) -> None:
        scanner.save_summary(summary)

    def _save_reuse(self, source_id: str, suggestions: list[dict]) -> None:
        save_reuse_suggestions(
            source_id,
            {
                "schema_version": 1,
                "source_id": source_id,
                "mapped_capsuleSuggestions": suggestions,
                "luna_ok": True,
            },
        )

    def test_ui_suggestion_verified_or_watch_with_html_stack(self) -> None:
        source_id = "source_web_1"
        summary = _web_summary(source_id)
        self._save_summary(source_id, summary)
        self._save_reuse(source_id, [_ui_suggestion()])

        record = verify_suggestions(source_id, summary, {"mapped_capsuleSuggestions": [_ui_suggestion()]})
        self.assertEqual(record["summary"]["total"], 1)
        result = record["results"][0]
        self.assertIn(result["verification_status"], ("verified", "watch"))
        self.assertGreaterEqual(result["verification_score"], 0.45)
        self.assertTrue(any("extension:" in item for item in result["evidence_matched"]))
        self.assertEqual(result["warehouse_action"], "none")

    def test_mismatch_suggestion_rejected_or_low_score(self) -> None:
        source_id = "source_web_2"
        summary = _web_summary(source_id)
        self._save_summary(source_id, summary)
        suggestion = _python_mismatch_suggestion()
        record = verify_suggestions(source_id, summary, {"mapped_capsuleSuggestions": [suggestion]})
        result = record["results"][0]
        self.assertLess(result["verification_score"], 0.75)
        self.assertIn(result["verification_status"], ("watch", "rejected"))

    def test_verifier_does_not_read_source_folder(self) -> None:
        source_id = "source_missing_path"
        missing_root = self._state_dir / "does-not-exist" / "project"
        registry.add_source_box(str(missing_root))
        summary = _web_summary(source_id)
        self._save_summary(source_id, summary)
        self._save_reuse(source_id, [_ui_suggestion()])

        record = verify_and_save(
            source_id,
            summary,
            {"mapped_capsuleSuggestions": [_ui_suggestion()]},
        )
        self.assertTrue(verification_file_path(source_id).is_file())
        self.assertTrue(record["limits"]["no_source_content_read"])

    def test_verification_file_written_to_state_dir(self) -> None:
        source_id = "source_store"
        summary = _web_summary(source_id)
        self._save_summary(source_id, summary)
        self._save_reuse(source_id, [_ui_suggestion()])
        verify_and_save(source_id, summary, {"mapped_capsuleSuggestions": [_ui_suggestion()]})
        path = verification_file_path(source_id)
        self.assertTrue(path.is_file())
        self.assertEqual(path.resolve().parent.name, "verified_suggestions")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["mode"], "metadata_only_verification")

    def test_all_results_have_warehouse_action_none(self) -> None:
        source_id = "source_wh"
        summary = _web_summary(source_id)
        suggestions = [_ui_suggestion(), _python_mismatch_suggestion()]
        record = verify_suggestions(source_id, summary, {"mapped_capsuleSuggestions": suggestions})
        for item in record["results"]:
            self.assertEqual(item["warehouse_action"], "none")

    def test_verify_does_not_modify_warehouse(self) -> None:
        root = self._state_dir / "wh-source"
        root.mkdir()
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        box = registry.add_source_box(str(root))
        scanner.scan_source_box(box["id"])
        draft_mod.draft_capsules(box["id"])
        before = warehouse.list_capsules()
        summary = scanner.load_summary(box["id"])
        assert summary is not None
        self._save_reuse(box["id"], [_ui_suggestion()])
        verify_and_save(box["id"], summary, {"mapped_capsuleSuggestions": [_ui_suggestion()]})
        after = warehouse.list_capsules()
        self.assertEqual(before, after)


class ReweaveAppServiceVerifyTest(unittest.TestCase):
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

    def test_no_reuse_suggestions_error(self) -> None:
        root = self._state_dir / "src-a"
        root.mkdir()
        box = registry.add_source_box(str(root))
        scanner.scan_source_box(box["id"])
        result = self.service.verify_source_suggestions(box["id"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "no_reuse_suggestions")

    def test_source_not_scanned_error(self) -> None:
        root = self._state_dir / "src-b"
        root.mkdir()
        box = registry.add_source_box(str(root))
        result = self.service.verify_source_suggestions(box["id"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "source_not_scanned")

    def test_verify_success_returns_summary(self) -> None:
        root = self._state_dir / "src-c"
        root.mkdir()
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        box = registry.add_source_box(str(root))
        scanner.scan_source_box(box["id"])
        save_reuse_suggestions(
            box["id"],
            {"mapped_capsuleSuggestions": [_ui_suggestion()], "luna_ok": True},
        )
        result = self.service.verify_source_suggestions(box["id"])
        self.assertTrue(result["ok"])
        self.assertIn("summary", result)
        self.assertEqual(result["summary"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
