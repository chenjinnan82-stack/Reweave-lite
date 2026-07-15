from __future__ import annotations

from pathlib import Path

from pimos_lite.reweave_release_surface_audit import (
    _disposition,
    build_lumo_reweave_release_surface_summary,
    build_reweave_public_alpha_release_summary,
    build_reweave_release_surface_audit,
)


def test_reweave_release_surface_audit_checks_release_boundary() -> None:
    root = Path(__file__).resolve().parents[1]

    audit = build_reweave_release_surface_audit(root)

    assert audit["audit_version"] == "reweave_release_surface_audit.v1"
    assert audit["scope"] == "core_reweave_surface_glob"
    assert audit["status"] == "passed"
    assert audit["release_surface_status"] == "passed"
    assert audit["stage4_coverage"] == "builtin_module_native"
    assert audit["backend_mode"] == "lumo_lite_bridge_first"
    assert audit["source_write_allowed"] is False
    assert audit["frontend_write_buttons_allowed"] is False
    assert audit["frontend_write_buttons_blocked_by_lumo_lite"] is True
    assert audit["public_alpha_status"] == "passed"
    assert audit["overall_release_status"] == "passed"
    assert audit["missing_surface_files"] == []
    assert audit["release_blockers"] == []
    assert all(audit["release_checks"].values())
    assert audit["legacy_workbench_available_with_token"] is True
    assert audit["launcher_bootstrap_side_effects"] == {"venv_write": False, "pip_network_install": False}
    assert audit["launcher_bootstrap_policy"] == "explicit_user_install_only"
    assert audit["browser_demo_status"] in {"passed", "partial_mock_fallback_present"}
    paths = {row["path"] for row in audit["entrypoints"]}
    assert "pimos_lite/reweave_behavior_runtime.py" in paths
    assert "pimos_lite/reweave_preview_pack.py" in paths
    assert "pimos_lite/reweave_task_intent.py" in paths
    assert "pimos_lite/reweave_task_plan.py" in paths
    assert "pimos_lite/reweave_engine/lumo_lite.py" in paths
    assert "pimos_lite/reweave_lumo_lite_state.py" in paths
    assert "pimos_lite/reweave_engine/factory.py" in paths
    assert "reweave_frontend/app.js" in paths
    assert audit["release_included_entrypoints"] == list(audit["release_default_entrypoint_files"])
    assert set(audit["release_support_runtime_files"]) <= set(audit["release_included_files"])
    assert audit["missing_runtime_dependency_files"] == []
    assert "pimos_lite/reweave_engine/local.py" in audit["release_support_runtime_files"]
    assert "pimos_lite/reweave_preview_export.py" in audit["release_support_runtime_files"]
    assert audit["release_non_active_foundation_files"] == [
        "pimos_lite/reweave_capsule_intake.py",
        "pimos_lite/reweave_capsule_stage3.py",
        "pimos_lite/reweave_capsule_store.py",
        "pimos_lite/reweave_capsule_worker.py",
        "pimos_lite/reweave_data_contract.py",
        "scripts/analyze_reweave_extraction.mjs",
        "scripts/analyze_reweave_security.mjs",
        "scripts/validate_reweave_compute.mjs",
    ]
    assert audit["release_non_active_entrypoints"] == [
        "pimos_lite/reweave_capsule_intake.py",
        "pimos_lite/reweave_capsule_stage3.py",
        "pimos_lite/reweave_capsule_store.py",
        "pimos_lite/reweave_capsule_worker.py",
        "pimos_lite/reweave_data_contract.py",
        "scripts/analyze_reweave_extraction.mjs",
        "scripts/analyze_reweave_security.mjs",
        "scripts/validate_reweave_compute.mjs",
    ]
    assert audit["missing_non_active_foundation_files"] == []
    assert audit["release_excluded_support_files"] == []
    assert "pimos_lite/reweave_preview_pack.py" not in audit["release_excluded_support_files"]
    dispositions = {row["path"]: row["release_disposition"] for row in audit["entrypoints"]}
    assert dispositions["pimos_lite/reweave_behavior_runtime.py"] == "included"
    assert dispositions["pimos_lite/reweave_preview_pack.py"] == "included"
    assert dispositions["pimos_lite/reweave_task_intent.py"] == "included"
    assert dispositions["pimos_lite/reweave_task_plan.py"] == "included"
    assert dispositions["pimos_lite/reweave_engine/lumo_lite.py"] == "included"
    assert dispositions["pimos_lite/reweave_lumo_lite_state.py"] == "included"
    assert dispositions["pimos_lite/reweave_engine/local.py"] == "included_support_runtime"
    assert (
        dispositions["pimos_lite/reweave_capsule_store.py"]
        == "included_non_active_foundation"
    )
    assert (
        dispositions["pimos_lite/reweave_capsule_intake.py"]
        == "included_non_active_foundation"
    )
    assert (
        dispositions["pimos_lite/reweave_data_contract.py"]
        == "included_non_active_foundation"
    )
    assert (
        dispositions["scripts/analyze_reweave_extraction.mjs"]
        == "included_non_active_foundation"
    )
    assert (
        dispositions["pimos_lite/reweave_capsule_stage3.py"]
        == "included_non_active_foundation"
    )
    assert (
        dispositions["pimos_lite/reweave_capsule_worker.py"]
        == "included_non_active_foundation"
    )
    assert (
        dispositions["scripts/analyze_reweave_security.mjs"]
        == "included_non_active_foundation"
    )
    assert (
        dispositions["scripts/validate_reweave_compute.mjs"]
        == "included_non_active_foundation"
    )
    assert audit["release_unknown_entrypoints"] == []
    assert "scripts/run_public_reweave_demo.py" in audit["release_included_entrypoints"]
    assert "scripts/run_public_stage4_demo.py" in audit["release_included_entrypoints"]


def test_reweave_public_alpha_release_summary_is_self_contained() -> None:
    root = Path(__file__).resolve().parents[1]
    summary = build_reweave_public_alpha_release_summary(root=root)

    assert summary["summary_version"] == "reweave_public_alpha_release_summary.v1"
    assert summary["overall_status"] == "passed"
    assert summary["release_surface_status"] == "passed"
    assert summary["source_project_write_allowed"] is False
    assert "Reweave-lite public alpha" in summary["boundary_line"]


def test_reweave_release_surface_unknown_file_is_not_silent_support() -> None:
    assert _disposition("pimos_lite/reweave_new_entry.py") == "unknown_release_surface"


def test_lumo_reweave_release_summary_uses_builtin_stage4() -> None:
    root = Path(__file__).resolve().parents[1]
    reweave = build_reweave_release_surface_audit(root)

    builtin = build_lumo_reweave_release_surface_summary(reweave_audit=reweave)
    passed = build_lumo_reweave_release_surface_summary(stage4_audit={"stage4_status": "passed"}, reweave_audit=reweave)

    assert builtin["summary_version"] == "lumo_reweave_release_surface_summary.v1"
    assert builtin["overall_status"] == "passed"
    assert builtin["stage4_status"] == "builtin_module_native"
    assert builtin["reweave_status"] == "passed"
    assert passed["overall_status"] == "passed"
    assert passed["source_project_write_allowed"] is False
    assert "no source project write" in passed["boundary_line"]
