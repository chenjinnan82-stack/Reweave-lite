"""Tests for Reweave Source Box Scanner v0 (no PySide6)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite import reweave_source_registry as registry
from pimos_lite import reweave_source_scanner as scanner


class ReweaveSourceScannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._state_dir)})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def _make_project(self) -> Path:
        root = self._state_dir / "sample-project"
        root.mkdir()
        (root / "main.py").write_text("print('hi')\n", encoding="utf-8")
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        (root / "node_modules").mkdir()
        (root / "node_modules" / "pkg.js").write_text("//", encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / "HEAD").write_text("ref", encoding="utf-8")
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "x.pyc").write_bytes(b"\x00\x01")
        (root / "lib").mkdir()
        (root / "lib" / "util.py").write_text("# util", encoding="utf-8")
        return root

    def test_scan_returns_counts_and_extensions(self) -> None:
        root = self._make_project()
        box = registry.add_source_box(root)
        summary = scanner.scan_directory_readonly(root, source_id=box["id"], label=box["label"])
        self.assertEqual(summary["scan_status"], "scanned")
        self.assertGreater(summary["counts"]["files_scanned"], 0)
        self.assertIn(".py", summary["extensions"])
        self.assertIn("main.py", summary["entry_candidates"])

    def test_ignored_dirs_not_counted_as_scanned_files(self) -> None:
        root = self._make_project()
        summary = scanner.scan_directory_readonly(root, source_id="source_test", label="sample")
        names_in_node = any("node_modules" in w for w in summary["warnings"])
        self.assertFalse(names_in_node)
        self.assertEqual(summary["extensions"].get(".js", 0), 0)

    def test_venv_prefix_dirs_are_not_sampled(self) -> None:
        root = self._state_dir / "venv-prefix"
        root.mkdir()
        (root / ".venv-reweave").mkdir()
        (root / ".venv-reweave" / "main.py").write_text("print('dependency')", encoding="utf-8")
        (root / "app.py").write_text("print('app')", encoding="utf-8")

        summary = scanner.scan_directory_readonly(root, source_id="source_venv", label="venv")

        self.assertEqual(summary["extensions"].get(".py"), 1)
        self.assertEqual(summary["sample_paths_by_extension"][".py"], ["app.py"])

    def test_does_not_read_file_contents(self) -> None:
        root = self._state_dir / "read-guard"
        root.mkdir()
        secret = root / "secret.py"
        secret.write_text("SECRET", encoding="utf-8")

        with patch.object(Path, "read_text", side_effect=AssertionError("must not read file content")):
            with patch.object(Path, "read_bytes", side_effect=AssertionError("must not read file content")):
                summary = scanner.scan_directory_readonly(root, source_id="source_guard", label="read-guard")

        self.assertEqual(secret.read_text(encoding="utf-8"), "SECRET")
        self.assertEqual(summary["counts"]["files_scanned"], 1)

    def test_scan_skips_file_and_dir_symlinks(self) -> None:
        root = self._state_dir / "symlink-guard"
        outside = self._state_dir / "outside"
        root.mkdir()
        outside.mkdir()
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        (outside / "secret.py").write_text("SECRET", encoding="utf-8")
        (root / "linked-file.py").symlink_to(outside / "secret.py")
        (root / "linked-dir").symlink_to(outside, target_is_directory=True)

        summary = scanner.scan_directory_readonly(root, source_id="source_symlink", label="symlink")

        self.assertEqual(summary["counts"]["files_scanned"], 1)
        self.assertIn("symlink_skipped:linked-file.py", summary["warnings"])
        self.assertIn("symlink_skipped:linked-dir", summary["warnings"])

    def test_max_files_limit(self) -> None:
        root = self._state_dir / "many-files"
        root.mkdir()
        for i in range(10):
            (root / f"f{i}.txt").write_text("x", encoding="utf-8")
        limits = scanner.ScanLimits(max_files=3, max_depth=8)
        summary = scanner.scan_directory_readonly(
            root, source_id="source_many", label="many", limits=limits
        )
        self.assertEqual(summary["counts"]["files_scanned"], 3)

    def test_corrupt_summary_is_backed_up_and_treated_missing(self) -> None:
        path = scanner.summary_file_path("source_bad")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")

        data = scanner.load_summary("source_bad")

        self.assertEqual(data, {})
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")
        self.assertTrue(list(path.parent.glob("source_bad.summary.json.corrupt.*.bak")))

    def test_summary_written_to_state_dir_not_source_folder(self) -> None:
        root = self._make_project()
        box = registry.add_source_box(root)
        summary = scanner.scan_source_box(box["id"])
        summary_path = scanner.summary_file_path(box["id"])
        self.assertTrue(summary_path.is_file())
        self.assertEqual(summary_path.resolve().parent, scanner.summaries_dir().resolve())
        self.assertNotEqual(summary_path.resolve().parent, root.resolve())
        on_disk = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["source_id"], box["id"])
        self.assertEqual(summary["source_id"], box["id"])

    def test_registry_updated_after_scan(self) -> None:
        root = self._make_project()
        box = registry.add_source_box(root)
        scanner.scan_source_box(box["id"])
        updated = registry.get_source_box(box["id"])
        assert updated is not None
        self.assertEqual(updated["scan_status"], "scanned")
        self.assertTrue(updated.get("summary_path", "").startswith("source_summaries/"))
        self.assertTrue(updated.get("last_scanned_at"))


if __name__ == "__main__":
    unittest.main()
