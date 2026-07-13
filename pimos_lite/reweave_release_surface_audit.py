from __future__ import annotations

from pathlib import Path
from typing import Any


AUDIT_VERSION = "reweave_release_surface_audit.v1"
SUMMARY_VERSION = "lumo_reweave_release_surface_summary.v1"
PUBLIC_ALPHA_SUMMARY_VERSION = "reweave_public_alpha_release_summary.v1"


REQUIRED_SURFACE_FILES = (
    "pimos_lite/capability_registry.py",
    "pimos_lite/capsule_module/__init__.py",
    "pimos_lite/capsule_module/contract.py",
    "pimos_lite/capsule_module/source_extract.py",
    "pimos_lite/composer/__init__.py",
    "pimos_lite/composer/intent.py",
    "pimos_lite/composer/module_native.py",
    "pimos_lite/desktop_reweave_static.py",
    "pimos_lite/reweave_app_service.py",
    "pimos_lite/reweave_behavior_runtime.py",
    "pimos_lite/reweave_capsule_content.py",
    "pimos_lite/reweave_capsule_draft.py",
    "pimos_lite/reweave_capsule_warehouse.py",
    "pimos_lite/reweave_engine/factory.py",
    "pimos_lite/reweave_engine/lumo_lite.py",
    "pimos_lite/reweave_llm_pack.py",
    "pimos_lite/reweave_lumo_lite_artifacts.py",
    "pimos_lite/reweave_lumo_lite_state.py",
    "pimos_lite/reweave_preview_pack.py",
    "pimos_lite/reweave_preview_viewer.py",
    "pimos_lite/reweave_project_graph.py",
    "pimos_lite/reweave_project_renderer.py",
    "pimos_lite/reweave_quality_gate.py",
    "pimos_lite/reweave_react_preview.py",
    "pimos_lite/reweave_snippet_context.py",
    "pimos_lite/reweave_source_registry.py",
    "pimos_lite/reweave_source_scanner.py",
    "pimos_lite/reweave_stage4_composer.py",
    "pimos_lite/reweave_task_intent.py",
    "pimos_lite/reweave_task_plan.py",
    "pimos_lite/safe_preview_write.py",
    "reweave_frontend/app.js",
    "reweave_frontend/artifacts.js",
    "reweave_frontend/bridge.js",
    "reweave_frontend/capsule_reader.js",
    "reweave_frontend/index.html",
    "reweave_frontend/renderers.js",
    "reweave_frontend/source_workflow.js",
    "scripts/run_public_reweave_demo.py",
    "scripts/run_public_stage4_demo.py",
    "start_reweave_static.sh",
)
RELEASE_INCLUDED_SURFACE_FILES = REQUIRED_SURFACE_FILES
RELEASE_SUPPORT_RUNTIME_FILES = (
    "pimos_lite/reweave_engine/local.py",
    "pimos_lite/reweave_engine/lumo.py",
    "pimos_lite/reweave_engine/__init__.py",
    "pimos_lite/reweave_engine/status.py",
    "pimos_lite/reweave_capsule_verifier.py",
    "pimos_lite/reweave_governance_preview.py",
    "pimos_lite/reweave_luna_client.py",
    "pimos_lite/reweave_preview_export.py",
    "pimos_lite/reweave_promote.py",
    "pimos_lite/reweave_release_surface_audit.py",
    "pimos_lite/reweave_reuse_suggestions.py",
    "pimos_lite/reweave_review_queue.py",
)

SURFACE_GLOBS = (
    "pimos_lite/capability_registry.py",
    "pimos_lite/capsule_module/*.py",
    "pimos_lite/composer/*.py",
    "pimos_lite/desktop_reweave_static.py",
    "pimos_lite/reweave*.py",
    "pimos_lite/reweave_engine/*.py",
    "reweave_frontend/*.js",
    "reweave_frontend/*.html",
    "scripts/run_public_*.py",
    "pimos_lite/safe_preview_write.py",
    "start_reweave_static.sh",
)


def build_reweave_release_surface_audit(root: str | Path | None = None) -> dict[str, Any]:
    base = Path(root).resolve() if root else Path(__file__).resolve().parents[1]
    relatives = _surface_paths(base)
    entries = [_entry(base, relative) for relative in relatives]
    missing_product = [relative for relative in REQUIRED_SURFACE_FILES if not (base / relative).is_file()]
    missing_runtime = [relative for relative in RELEASE_SUPPORT_RUNTIME_FILES if not (base / relative).is_file()]
    missing = missing_product + missing_runtime
    mock_fallback = any(row["mock_fallback_present"] for row in entries)
    checks = _release_checks(base)
    launcher = _read(base / "start_reweave_static.sh")
    frontend_write_buttons_blocked = checks.get("lumo_lite_hides_preview_export_actions") is True and checks.get("lumo_lite_blocks_preview_export_handler") is True
    unknown = [row["path"] for row in entries if row["release_disposition"] == "unknown_release_surface"]
    blockers = [name for name, passed in checks.items() if not passed] + [f"unknown_release_surface:{path}" for path in unknown]
    release_status = "passed" if not missing and not blockers else "partial"
    return {
        "audit_version": AUDIT_VERSION,
        "scope": "core_reweave_surface_glob",
        "status": release_status,
        "release_surface_status": release_status,
        "stage4_coverage": "builtin_module_native",
        "backend_mode": "lumo_lite_bridge_first",
        "source_write_allowed": False,
        "frontend_write_buttons_allowed": not frontend_write_buttons_blocked,
        "frontend_write_buttons_blocked_by_lumo_lite": frontend_write_buttons_blocked,
        "legacy_workbench_available_with_token": True,
        "mock_fallback_present": mock_fallback,
        "browser_demo_status": "partial_mock_fallback_present" if mock_fallback else "passed",
        "artifact_trust_boundary": "runtime_state_allowed_roots",
        "launcher_bootstrap_side_effects": {
            "venv_write": ".venv-reweave" in launcher and "python3 -m venv" in launcher,
            "pip_network_install": "pip\" install" in launcher,
        },
        "launcher_bootstrap_policy": "explicit_user_install_only",
        "release_checks": checks,
        "release_blockers": blockers,
        "missing_surface_files": missing,
        "entrypoint_count": len(entries),
        "release_included_files": list(RELEASE_INCLUDED_SURFACE_FILES) + list(RELEASE_SUPPORT_RUNTIME_FILES),
        "release_default_entrypoint_files": list(RELEASE_INCLUDED_SURFACE_FILES),
        "release_support_runtime_files": list(RELEASE_SUPPORT_RUNTIME_FILES),
        "missing_runtime_dependency_files": missing_runtime,
        "release_excluded_support_files": [],
        "release_included_entrypoints": [row["path"] for row in entries if row["release_disposition"] == "included"],
        "release_support_entrypoints": [row["path"] for row in entries if row["release_disposition"] == "included_support_runtime"],
        "release_excluded_entrypoints": [],
        "release_unknown_entrypoints": unknown,
        "entrypoints": entries,
        "public_alpha_status": release_status,
        "overall_release_status": release_status,
    }


def build_reweave_public_alpha_release_summary(
    *,
    reweave_audit: dict[str, Any] | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    audit = reweave_audit or build_reweave_release_surface_audit(root)
    status = str(audit.get("release_surface_status") or audit.get("status") or "missing")
    return {
        "summary_version": PUBLIC_ALPHA_SUMMARY_VERSION,
        "overall_status": status,
        "release_surface_status": status,
        "source_project_write_allowed": False,
        "frontend_write_buttons_allowed": bool(audit.get("frontend_write_buttons_allowed") is True),
        "boundary_line": "Reweave-lite public alpha: no source project write; preview/report/runtime artifact writes are classified separately",
    }


def build_lumo_reweave_release_surface_summary(
    *,
    stage4_audit: dict[str, Any] | None = None,
    reweave_audit: dict[str, Any] | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    reweave = reweave_audit or build_reweave_release_surface_audit(root)
    stage4 = dict(stage4_audit or {})
    stage4_status = str(
        stage4.get("stage4_status")
        or stage4.get("status")
        or reweave.get("stage4_coverage")
        or "missing"
    )
    reweave_status = str(reweave.get("release_surface_status") or reweave.get("status") or "missing")
    overall = "passed" if stage4_status in {"passed", "builtin_module_native"} and reweave_status == "passed" else "partial"
    return {
        "summary_version": SUMMARY_VERSION,
        "overall_status": overall,
        "stage4_status": stage4_status,
        "reweave_status": reweave_status,
        "source_project_write_allowed": False,
        "frontend_write_buttons_allowed": bool(reweave.get("frontend_write_buttons_allowed") is True),
        "boundary_line": "no source project write; preview/report/runtime artifact writes are classified separately",
        "known_limitations": [
            "browser-only mock fallback is not a release backend",
            "legacy Reweave local/lumo workbench remains token-gated support surface",
        ],
    }


def _entry(base: Path, relative: str) -> dict[str, Any]:
    path = base / relative
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {
        "path": relative,
        "exists": path.is_file(),
        "release_role": _role(relative),
        "release_disposition": _disposition(relative),
        "lumo_lite_bridge_only": "lumo_lite" in text or relative.startswith("reweave_frontend/"),
        "write_source_folder_disabled": "write_source_folder" in text and "False" in text,
        "mock_fallback_present": "mock" in text.lower(),
    }


def _role(relative: str) -> str:
    if relative.startswith(("pimos_lite/capsule_module/", "pimos_lite/composer/")) or relative in {
        "pimos_lite/capability_registry.py",
        "pimos_lite/safe_preview_write.py",
    }:
        return "builtin_stage4_composer"
    if relative.endswith("reweave_stage4_composer.py"):
        return "stage4_composer_bridge"
    if relative.endswith("reweave_engine/factory.py"):
        return "engine_factory"
    if relative.endswith("desktop_reweave_static.py"):
        return "desktop_bridge"
    if relative.endswith("reweave_app_service.py"):
        return "service_facade"
    if relative.endswith("reweave_behavior_runtime.py"):
        return "runtime_behavior_validator"
    if "lumo_lite" in relative:
        return "lumo_lite_bridge"
    if relative.endswith("reweave_llm_pack.py"):
        return "optional_local_model_pack"
    if relative in RELEASE_INCLUDED_SURFACE_FILES and relative.startswith("pimos_lite/reweave"):
        return "product_core"
    if relative.startswith("reweave_frontend/"):
        return "frontend_shell"
    if relative.startswith("scripts/run_public_"):
        return "public_cli"
    if relative.endswith("start_reweave_static.sh"):
        return "launcher"
    if "reweave_engine/local.py" in relative or "reweave_engine/lumo.py" in relative:
        return "legacy_workbench"
    return "artifact_viewer"


def _disposition(relative: str) -> str:
    if relative in RELEASE_INCLUDED_SURFACE_FILES:
        return "included"
    if relative in RELEASE_SUPPORT_RUNTIME_FILES:
        return "included_support_runtime"
    return "unknown_release_surface"


def _surface_paths(base: Path) -> list[str]:
    paths: set[str] = set()
    for pattern in SURFACE_GLOBS:
        for path in base.glob(pattern):
            if path.is_file():
                paths.add(path.relative_to(base).as_posix())
    paths.update(REQUIRED_SURFACE_FILES)
    return sorted(paths)


def _release_checks(base: Path) -> dict[str, bool]:
    factory = _read(base / "pimos_lite/reweave_engine/factory.py")
    app_service = _read(base / "pimos_lite/reweave_app_service.py")
    artifacts = _read(base / "pimos_lite/reweave_lumo_lite_artifacts.py")
    frontend = _read(base / "reweave_frontend/app.js")
    llm_pack = _read(base / "pimos_lite/reweave_llm_pack.py")
    launcher = _read(base / "start_reweave_static.sh")
    export_controls_removed = all(
        token not in frontend
        for token in (
            "btn-artifact-open",
            "btn-export-zip",
            "btn-export-copy",
            "chooseExportFolderAndExport",
        )
    )
    export_controls_guarded = (
        "currentPreviewPackageId && !isLumoLiteReadOnly()" in frontend
        and "!currentPreviewPackageId || isLumoLiteReadOnly()" in frontend
    )
    return {
        "default_backend_is_lumo_lite": 'DEFAULT_BACKEND = "lumo_lite"' in factory,
        "legacy_workbench_requires_token": "REWEAVE_ENABLE_LEGACY_WORKBENCH" in factory and "LEGACY_WORKBENCH_TOKEN" in factory,
        "unknown_backend_fails_closed": "return LumoLiteReweaveEngine()" in factory,
        "static_launcher_forces_lumo_lite": 'export REWEAVE_ENGINE="lumo_lite"' in launcher,
        "static_launcher_clears_legacy_workbench_env": "unset REWEAVE_ENABLE_LEGACY_WORKBENCH" in launcher,
        "lumo_lite_service_blocks_mutators": "_lumo_lite_disabled" in app_service and "bind_source_folder" in app_service and "generate_preview" in app_service,
        "artifact_viewer_enforces_root_allowlist": "root_allowlist_enforced" in artifacts and "_is_under_allowed_roots" in artifacts,
        "lumo_lite_hides_preview_export_actions": export_controls_removed or export_controls_guarded,
        "lumo_lite_blocks_preview_export_handler": export_controls_removed or export_controls_guarded,
        "optional_llm_pack_is_local_and_fallback_safe": "external_network_call" in llm_pack
        and "source_project_write" in llm_pack
        and "fallback_used" in llm_pack,
    }


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""
