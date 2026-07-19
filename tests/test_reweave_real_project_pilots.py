from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_reweave_v1_real_project_pilots.py"
SPEC = importlib.util.spec_from_file_location("reweave_real_project_pilots", SCRIPT)
assert SPEC and SPEC.loader
PILOTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PILOTS)


class ReweaveRealProjectPilotsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="reweave-pilot-test-")
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.repo = self.workspace / "sample"
        self.repo.mkdir()
        self._git("init", "-q")
        self._git("config", "user.email", "pilot@example.invalid")
        self._git("config", "user.name", "Pilot Test")
        self._git("remote", "add", "origin", "https://github.com/example/sample.git")
        (self.repo / "LICENSE").write_text("MIT\n", encoding="utf-8")
        (self.repo / "index.html").write_text(
            "<!doctype html><html><body><main></main>"
            '<script type="module" src="./app.js"></script></body></html>',
            encoding="utf-8",
        )
        (self.repo / "app.js").write_text('console.log("bootstrap");\n', encoding="utf-8")
        self._git("add", "LICENSE", "index.html", "app.js")
        self._git("commit", "-qm", "fixture")
        self.commit = self._git("rev-parse", "HEAD").strip()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
        return completed.stdout

    def _project(self, **updates: object) -> dict[str, object]:
        value: dict[str, object] = {
            "id": "sample",
            "cohort": "bootstrap",
            "selection_order": 1,
            "repository_url": "https://github.com/example/sample",
            "commit": self.commit,
            "checkout_dir": "sample",
            "entry_relpath": "index.html",
            "license_relpath": "LICENSE",
            "expected_kind": None,
        }
        value.update(updates)
        return value

    def _manifest(self, projects: list[dict[str, object]] | None = None) -> dict[str, object]:
        return {
            "schema_version": PILOTS.MANIFEST_SCHEMA,
            "reweave_head": subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "rules": PILOTS.current_rules(),
            "positive_scout": {
                "screened_by_kind": {
                    "presentation": 0,
                    "interaction": 0,
                    "computation": 0,
                },
                "eligible_projects_found": 0,
                "status": "test_fixture",
                "raw_search_evidence_sha256": {
                    "presentation": "0" * 64,
                    "interaction": "0" * 64,
                    "computation": "0" * 64,
                },
            },
            "projects": projects if projects is not None else [self._project()],
        }

    def test_failure_classification_fails_closed(self) -> None:
        self.assertEqual(
            PILOTS.failure_family("module_top_level_side_effect"),
            "bootstrap_top_level_not_declarative_v1",
        )
        self.assertEqual(
            PILOTS.failure_family("ollama_model_not_selected"),
            "supervision_environment_or_verdict",
        )
        self.assertEqual(PILOTS.failure_family("brand_new_error"), "unclassified")

    def test_preflight_accepts_only_clean_fixed_checkout(self) -> None:
        project = PILOTS.validate_manifest(self._manifest())["projects"][0]
        evidence = PILOTS.preflight_project(self.workspace, project)
        self.assertEqual(evidence["head"], self.commit)
        self.assertEqual(evidence["source_tree"]["symlink_count"], 0)

        with self.assertRaisesRegex(PILOTS.PilotError, "source_commit_mismatch"):
            PILOTS.preflight_project(
                self.workspace, {**project, "commit": "0" * 40}
            )
        (self.repo / "dirty.txt").write_text("dirty", encoding="utf-8")
        with self.assertRaisesRegex(PILOTS.PilotError, "source_worktree_dirty"):
            PILOTS.preflight_project(self.workspace, project)

        (self.repo / "dirty.txt").unlink()
        alias = self.workspace / "sample-alias"
        alias.symlink_to(self.repo, target_is_directory=True)
        with self.assertRaisesRegex(
            PILOTS.PilotError, "source_checkout_symlink_forbidden"
        ):
            PILOTS.preflight_project(
                self.workspace, {**project, "checkout_dir": "sample-alias"}
            )

    def test_manifest_and_output_paths_fail_closed(self) -> None:
        with self.assertRaisesRegex(PILOTS.PilotError, "manifest_path_invalid"):
            PILOTS.validate_manifest(
                self._manifest([self._project(entry_relpath="nested//index.html")])
            )
        positive = self._project(
            cohort="positive", expected_kind="presentation", license_relpath=None
        )
        manifest = self._manifest([positive])
        manifest["positive_scout"]["eligible_projects_found"] = 1
        with self.assertRaisesRegex(
            PILOTS.PilotError, "manifest_positive_license_required"
        ):
            PILOTS.validate_manifest(manifest)
        invalid_scout = self._manifest()
        invalid_scout["positive_scout"]["screened_by_kind"]["presentation"] = 21
        with self.assertRaisesRegex(
            PILOTS.PilotError, "manifest_positive_scout_invalid"
        ):
            PILOTS.validate_manifest(invalid_scout)
        with self.assertRaisesRegex(
            PILOTS.PilotError, "pilot_state_overlaps_source_workspace"
        ):
            PILOTS._assert_isolated_paths(
                self.workspace, self.workspace / "state"
            )
        with self.assertRaisesRegex(
            PILOTS.PilotError, "pilot_output_inside_source_workspace"
        ):
            PILOTS._assert_isolated_paths(
                self.workspace,
                self.root / "state",
                self.workspace / "evidence.json",
            )
        output = self.workspace / "cli-evidence.json"
        with mock.patch.object(
            PILOTS.sys,
            "argv",
            [
                str(SCRIPT),
                "--manifest",
                str(self.root / "unused.json"),
                "--workspace",
                str(self.workspace),
                "--state-root",
                str(self.root / "state"),
                "--output",
                str(output),
            ],
        ), mock.patch("builtins.print"):
            self.assertEqual(PILOTS.main(), 1)
        self.assertFalse(output.exists())

    def test_source_and_rejected_write_guards_fail_closed(self) -> None:
        before = {"source_tree": {"sha256": "a"}, "git_status_sha256": "b"}
        PILOTS._assert_source_unchanged(before, dict(before))
        with self.assertRaisesRegex(PILOTS.PilotError, "source_changed_by_pilot"):
            PILOTS._assert_source_unchanged(
                before,
                {"source_tree": {"sha256": "c"}, "git_status_sha256": "b"},
            )
        PILOTS._assert_rejected_no_formal_write(
            [{"candidate_status": "rejected"}], {"capsules": 0}
        )
        with self.assertRaisesRegex(
            PILOTS.PilotError, "rejected_candidate_formal_write"
        ):
            PILOTS._assert_rejected_no_formal_write(
                [{"candidate_status": "rejected"}], {"capsules": 1}
            )
        PILOTS._assert_snapshot_consistent(
            {"snapshot_before": "same", "snapshot_after": "same"}
        )
        with self.assertRaisesRegex(PILOTS.PilotError, "intake_snapshot_mismatch"):
            PILOTS._assert_snapshot_consistent(
                {"snapshot_before": "before", "snapshot_after": "after"}
            )

    def test_rollup_counts_projects_and_candidates_separately(self) -> None:
        project = {
            "project": {"id": "one", "cohort": "bootstrap"},
            "qualification": {"state": "ready"},
            "primary_failure": "module_top_level_side_effect",
            "failure_family": "bootstrap_top_level_not_declarative_v1",
            "outcome": {
                "intake_positive": False,
                "validated_positive": False,
                "active": False,
                "product_asserted": None,
            },
            "candidates": [
                {
                    "candidate_status": "rejected",
                    "primary_failure": "module_top_level_side_effect",
                    "failure_family": "bootstrap_top_level_not_declarative_v1",
                },
                {
                    "candidate_status": "rejected",
                    "primary_failure": "module_top_level_statement_unsupported",
                    "failure_family": "bootstrap_top_level_not_declarative_v1",
                },
            ],
        }
        summary = PILOTS.summarize([project], self._manifest([]))
        self.assertEqual(summary["candidate_count"], 2)
        self.assertEqual(
            summary["failure_family_candidate_counts"][
                "bootstrap_top_level_not_declarative_v1"
            ],
            2,
        )
        self.assertEqual(
            summary["failure_family_project_counts"][
                "bootstrap_top_level_not_declarative_v1"
            ],
            1,
        )
        self.assertEqual(summary["qualification_failure_counts"], {})
        self.assertEqual(
            summary["raw_failure_codes"], {"module_top_level_side_effect": 1}
        )

    def test_duplicate_model_evidence_and_secondary_unknown_code_fail_closed(self) -> None:
        row = {
            "sanitized_candidate_json": "{}",
            "redaction_summary_json": json.dumps(
                {"codes": ["module_top_level_side_effect", "new_secondary_code"]}
            ),
            "equivalence_comparison_json": json.dumps(
                {"same_run_representative": "review-1"}
            ),
            "candidate_status": "duplicate",
            "source_relpath": "app.js",
            "source_hash": "a" * 64,
            "candidate_canonical_hash": "b" * 64,
            "supervision_response_hash": "c" * 64,
        }
        candidate = PILOTS._candidate_evidence(row, None)
        self.assertIs(candidate["model_called"], False)
        project = {
            "project": {"id": "one", "cohort": "bootstrap"},
            "qualification": {"state": "ready", "raw_error_code": None},
            "primary_failure": "module_top_level_side_effect",
            "failure_family": "bootstrap_top_level_not_declarative_v1",
            "outcome": {
                "intake_positive": False,
                "validated_positive": False,
                "active": False,
                "product_asserted": None,
            },
            "candidates": [candidate],
        }
        summary = PILOTS.summarize([project], self._manifest([]))
        self.assertEqual(summary["classification_gate"], "failed")
        self.assertEqual(
            summary["unclassified_raw_error_codes"], ["new_secondary_code"]
        )

    def test_real_runner_preserves_source_and_formal_tables_for_rejection(self) -> None:
        manifest_path = self.root / "manifest.json"
        manifest_path.write_text(
            json.dumps(self._manifest(), sort_keys=True), encoding="utf-8"
        )
        result = PILOTS.run_manifest(
            manifest_path, self.workspace, self.root / "state"
        )
        self.assertEqual(result["gate_status"], "passed")
        project = result["projects"][0]
        self.assertEqual(project["qualification"]["state"], "ready")
        self.assertEqual(project["intake"]["snapshot_before"], project["intake"]["snapshot_after"])
        self.assertEqual(
            project["candidates"][0]["primary_failure"],
            "module_top_level_statement_unsupported",
        )
        self.assertEqual(
            project["primary_failure"],
            "module_top_level_statement_unsupported",
        )
        self.assertEqual(project["farthest_gate"], "intake")
        self.assertEqual(project["candidates"][0]["farthest_gate"], "intake")
        self.assertFalse(any(project["formal_rows"]["delta"].values()))
        self.assertEqual(
            project["source"]["source_tree_before"],
            project["source"]["source_tree_after"],
        )
        self.assertIs(project["candidates"][0]["model_called"], False)
        self.assertEqual(
            project["candidates"][0]["workers"],
            {"image": None, "compute": None, "qweb": None},
        )

    def test_manifest_head_mismatch_is_rejected_before_execution(self) -> None:
        manifest = self._manifest([])
        manifest["reweave_head"] = "0" * 40
        manifest_path = self.root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(
            PILOTS.PilotError, "manifest_reweave_head_mismatch"
        ):
            PILOTS.run_manifest(
                manifest_path, self.workspace, self.root / "state"
            )


if __name__ == "__main__":
    unittest.main()
