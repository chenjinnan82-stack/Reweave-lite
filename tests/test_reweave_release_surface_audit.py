from __future__ import annotations

from pathlib import Path

from pimos_lite.reweave_release_surface_audit import _disposition, build_lumo_reweave_release_surface_summary, build_reweave_release_surface_audit


def test_reweave_release_surface_audit_checks_release_boundary() -> None:
    root = Path(__file__).resolve().parents[1]

    audit = build_reweave_release_surface_audit(root)

    assert audit["audit_version"] == "reweave_release_surface_audit.v1"
    assert audit["scope"] == "core_reweave_surface_glob"
    assert audit["status"] == "passed"
    assert audit["release_surface_status"] == "passed"
    assert audit["stage4_coverage"] == "not_included"
    assert audit["backend_mode"] == "lumo_lite_bridge_first"
    assert audit["source_write_allowed"] is False
    assert audit["frontend_write_buttons_allowed"] is False
    assert audit["frontend_write_buttons_blocked_by_lumo_lite"] is True
    assert audit["overall_release_status"] == "partial_until_stage4_audit_supplied"
    assert audit["missing_surface_files"] == []
    assert audit["release_blockers"] == []
    assert all(audit["release_checks"].values())
    assert audit["legacy_workbench_available_with_token"] is True
    assert audit["launcher_bootstrap_side_effects"] == {"venv_write": True, "pip_network_install": True}
    assert audit["launcher_bootstrap_policy"] == "allowed_dependency_bootstrap_exception_not_source_write"
    assert audit["browser_demo_status"] in {"passed", "partial_mock_fallback_present"}
    paths = {row["path"] for row in audit["entrypoints"]}
    assert "pimos_lite/reweave_engine/lumo_lite.py" in paths
    assert "pimos_lite/reweave_lumo_lite_state.py" in paths
    assert "pimos_lite/reweave_engine/factory.py" in paths
    assert "reweave_frontend/app.js" in paths
    assert audit["release_included_entrypoints"] == list(audit["release_included_files"])
    assert "pimos_lite/reweave_engine/local.py" in audit["release_excluded_support_files"]
    assert "pimos_lite/reweave_preview_export.py" in audit["release_excluded_support_files"]
    dispositions = {row["path"]: row["release_disposition"] for row in audit["entrypoints"]}
    assert dispositions["pimos_lite/reweave_engine/lumo_lite.py"] == "included"
    assert dispositions["pimos_lite/reweave_lumo_lite_state.py"] == "included"
    assert dispositions["pimos_lite/reweave_engine/local.py"] == "excluded_support_only"
    assert audit["release_unknown_entrypoints"] == []


def test_reweave_release_surface_unknown_file_is_not_silent_support() -> None:
    assert _disposition("pimos_lite/reweave_new_entry.py") == "unknown_release_surface"


def test_lumo_reweave_release_summary_waits_for_stage4_audit() -> None:
    root = Path(__file__).resolve().parents[1]
    reweave = build_reweave_release_surface_audit(root)

    partial = build_lumo_reweave_release_surface_summary(reweave_audit=reweave)
    passed = build_lumo_reweave_release_surface_summary(stage4_audit={"stage4_status": "passed"}, reweave_audit=reweave)

    assert partial["summary_version"] == "lumo_reweave_release_surface_summary.v1"
    assert partial["overall_status"] == "partial"
    assert partial["stage4_status"] == "not_provided"
    assert partial["reweave_status"] == "passed"
    assert passed["overall_status"] == "passed"
    assert passed["source_project_write_allowed"] is False
    assert "no source project write" in passed["boundary_line"]
