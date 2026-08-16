#!/usr/bin/env python3
"""Run the release-gate QWebEngine nodes in fresh Python processes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QWEB_TEST_NODES = (
    "tests/test_reweave_phase6_desktop.py::test_simple_mode_scans_multiply_without_creating_candidate",
    "tests/test_reweave_phase6_desktop.py::test_static_web_target_review_ui_never_writes_or_calls_confirm_service",
    "tests/test_reweave_phase6_desktop.py::test_capsule_warehouse_read_only_scene_with_real_service",
    "tests/test_reweave_phase6_desktop.py::test_product_capability_gap_decisions_render_and_fail_closed",
    "tests/test_reweave_phase6_desktop.py::test_time_conversion_capability_gap_fixture_renders_and_fails_closed",
    "tests/test_reweave_phase6_desktop.py::test_finite_enum_capability_gap_runs_once_to_exact_review",
    "tests/test_reweave_phase6_desktop.py::test_capability_source_proposal_start_error_is_preserved",
    "tests/test_reweave_phase6_desktop.py::test_published_capability_replan_handoff_runs_once_and_opens_review",
    "tests/test_reweave_phase6_desktop.py::test_multi_field_candidate_acceptance_renders_all_contract_fields",
    "tests/test_reweave_phase6_desktop.py::test_product_flow_builds_previews_exports_and_restores_real_candidate",
    "tests/test_reweave_phase6_desktop.py::test_multi_gap_question_ui_stops_before_plan_or_candidate",
    "tests/test_reweave_phase6_desktop.py::test_gap_target_no_match_stops_with_explicit_copy",
    "tests/test_reweave_phase6_desktop.py::test_static_web_target_review_ui_with_real_service",
    "tests/test_reweave_phase6_desktop.py::test_phase6_desktop_end_to_end_without_reload",
    "tests/test_reweave_capsule_stage3.py::Stage3PySideFlowTest::test_real_qwebengine_blocks_file_escape",
    "tests/test_reweave_capsule_stage3.py::Stage3PySideFlowTest::test_real_qwebengine_checks_repeatable_presentation_render",
    "tests/test_reweave_capsule_stage3.py::Stage3PySideFlowTest::test_real_qwebengine_rejects_non_json_emit_before_clone",
    "tests/test_reweave_capsule_stage3.py::Stage3PySideFlowTest::test_real_qwebengine_rejects_observably_non_idempotent_dispose",
    "tests/test_reweave_capsule_stage3.py::Stage3PySideFlowTest::test_real_qwebengine_rejects_root_ancestor_mutation",
    "tests/test_reweave_capsule_stage3.py::Stage3PySideFlowTest::test_real_qwebengine_runs_declared_event_and_dispose",
    "tests/test_reweave_capsule_stage3.py::Stage3PySideFlowTest::test_real_qwebengine_runs_every_boundary_fixture",
    "tests/test_reweave_plan_execution.py::PlanExecutionV1Test::test_bounded_string_v5_deterministic_vertical_loop",
    "tests/test_reweave_plan_execution.py::PlanExecutionV1Test::test_composed_runtime_requires_exactly_one_non_nested_main",
    "tests/test_reweave_plan_execution.py::PlanExecutionV1Test::test_real_qweb_acceptance_allows_matching_business_output",
    "tests/test_reweave_plan_execution.py::PlanExecutionV1Test::test_real_qweb_acceptance_reports_wrong_business_output",
    "tests/test_reweave_plan_execution.py::PlanExecutionV1Test::test_real_qweb_multi_computation_rejects_bad_intermediate_output",
    "tests/test_reweave_plan_execution.py::PlanExecutionV1Test::test_real_qweb_multi_computation_serial_acceptance",
    "tests/test_reweave_plan_execution.py::PlanExecutionV1Test::test_real_qweb_parameter_binding_is_applied_and_cannot_be_overridden",
    "tests/test_reweave_phase5_generation.py::Phase5FormalGenerationTest::test_orphan_retry_rejects_forged_receipt_after_real_qweb_revalidation",
)
TEST_FILES = (
    "tests/test_reweave_phase6_desktop.py",
    "tests/test_reweave_capsule_stage3.py",
    "tests/test_reweave_plan_execution.py",
    "tests/test_reweave_phase5_generation.py",
)
EXPECTED_NODE_COUNT = 29
NODE_TIMEOUT_SECONDS = 600


def _emit_streams(completed: subprocess.CompletedProcess[bytes]) -> None:
    sys.stdout.buffer.write(completed.stdout)
    sys.stderr.buffer.write(completed.stderr)
    sys.stdout.flush()
    sys.stderr.flush()


def _summary(**values: object) -> None:
    print(
        json.dumps(
            {"schema": "reweave_qwebengine_test_result.v1", **values},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )


def _junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def _isolated_environment(root: Path) -> dict[str, str]:
    paths = {
        "HOME": root / "home",
        "TMPDIR": root / "tmp",
        "TMP": root / "tmp",
        "TEMP": root / "tmp",
        "XDG_CACHE_HOME": root / "cache",
        "XDG_CONFIG_HOME": root / "config",
        "XDG_DATA_HOME": root / "data",
        "XDG_RUNTIME_DIR": root / "runtime",
        "APPDATA": root / "appdata",
        "LOCALAPPDATA": root / "localappdata",
    }
    for path in set(paths.values()):
        path.mkdir(parents=True)
        if path == paths["XDG_RUNTIME_DIR"]:
            path.chmod(0o700)
    environment = os.environ.copy()
    environment.update({key: str(path) for key, path in paths.items()})
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment.pop("PYTEST_ADDOPTS", None)
    return environment


def _is_release_qweb_node(node: str) -> bool:
    method = node.rsplit("::", 1)[-1]
    if node.startswith(f"{TEST_FILES[0]}::"):
        return True
    if node.startswith(f"{TEST_FILES[1]}::Stage3PySideFlowTest::"):
        return method.startswith("test_real_qwebengine_")
    if node.startswith(f"{TEST_FILES[2]}::PlanExecutionV1Test::"):
        return method.startswith("test_real_qweb") or method in {
            "test_bounded_string_v5_deterministic_vertical_loop",
            "test_composed_runtime_requires_exactly_one_non_nested_main",
        }
    return node.startswith(f"{TEST_FILES[3]}::") and "real_qweb" in method


def _collect_nodes() -> list[str]:
    if (
        len(QWEB_TEST_NODES) != EXPECTED_NODE_COUNT
        or len(set(QWEB_TEST_NODES)) != EXPECTED_NODE_COUNT
    ):
        raise RuntimeError("qweb_static_node_set_invalid")
    with tempfile.TemporaryDirectory(prefix="reweave-qweb-collect-") as folder:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "--collect-only",
                "-q",
                *TEST_FILES,
            ],
            cwd=ROOT,
            capture_output=True,
            check=False,
            env=_isolated_environment(Path(folder)),
        )
    if completed.returncode != 0:
        _emit_streams(completed)
        raise RuntimeError(f"qweb_collection_failed:{completed.returncode}")
    output = completed.stdout.decode("utf-8", "strict")
    collected = sorted(
        {
            line.strip()
            for line in output.splitlines()
            if _is_release_qweb_node(line.strip())
        }
    )
    if collected != sorted(QWEB_TEST_NODES):
        _emit_streams(completed)
        raise RuntimeError(
            f"qweb_node_set_changed:{len(collected)}:{EXPECTED_NODE_COUNT}"
        )
    _summary(
        status="passed",
        stage="collect",
        node_count=len(collected),
    )
    return list(QWEB_TEST_NODES)


def main() -> int:
    try:
        nodes = _collect_nodes()
    except (OSError, RuntimeError, UnicodeError) as exc:
        _summary(status="failed", stage="collect", error=type(exc).__name__)
        print(str(exc), file=sys.stderr)
        return 1

    total_started = time.monotonic()
    for index, node in enumerate(nodes, start=1):
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="reweave-qweb-pytest-") as folder:
            isolated_root = Path(folder)
            junit = isolated_root / "result.xml"
            command = [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-q",
                node,
                f"--junitxml={junit}",
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    capture_output=True,
                    check=False,
                    timeout=NODE_TIMEOUT_SECONDS,
                    env=_isolated_environment(isolated_root),
                )
            except subprocess.TimeoutExpired as exc:
                if exc.stdout:
                    sys.stdout.buffer.write(exc.stdout)
                if exc.stderr:
                    sys.stderr.buffer.write(exc.stderr)
                _summary(
                    status="failed",
                    stage="node",
                    node=node,
                    index=index,
                    node_count=len(nodes),
                    error="timeout",
                    timeout_seconds=NODE_TIMEOUT_SECONDS,
                    elapsed_seconds=round(time.monotonic() - started, 3),
                )
                return 1

            _emit_streams(completed)
            elapsed = round(time.monotonic() - started, 3)
            try:
                counts = _junit_counts(junit)
            except (ET.ParseError, OSError, ValueError):
                counts = {"tests": 0, "failures": 0, "errors": 1, "skipped": 0}
            passed = (
                completed.returncode == 0
                and counts["tests"] >= 1
                and counts["failures"] == 0
                and counts["errors"] == 0
                and counts["skipped"] == 0
            )
            _summary(
                status="passed" if passed else "failed",
                stage="node",
                node=node,
                index=index,
                node_count=len(nodes),
                returncode=completed.returncode,
                signal=(-completed.returncode if completed.returncode < 0 else None),
                elapsed_seconds=elapsed,
                junit=counts,
            )
            if not passed:
                return 1

    _summary(
        status="passed",
        stage="complete",
        node_count=len(nodes),
        elapsed_seconds=round(time.monotonic() - total_started, 3),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
