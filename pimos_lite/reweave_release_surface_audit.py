from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


AUDIT_VERSION = "reweave_release_surface_audit.v2"
SUMMARY_VERSION = "reweave_release_surface_summary.v2"
PUBLIC_ALPHA_SUMMARY_VERSION = "reweave_public_alpha_release_summary.v2"


REQUIRED_SURFACE_FILES = (
    "pimos_lite/desktop_reweave_static.py",
    "pimos_lite/reweave_app_service.py",
    "pimos_lite/composer/module_native.py",
    "pimos_lite/reweave_capsule_store.py",
    "pimos_lite/reweave_capsule_intake.py",
    "pimos_lite/reweave_capsule_stage3.py",
    "pimos_lite/reweave_capsule_worker.py",
    "pimos_lite/reweave_data_contract.py",
    "pimos_lite/reweave_process_environment.py",
    "pimos_lite/reweave_javascript_source.py",
    "pimos_lite/reweave_source_registry.py",
    "pimos_lite/reweave_source_scanner.py",
    "scripts/analyze_reweave_extraction.mjs",
    "scripts/analyze_reweave_security.mjs",
    "scripts/analyze_reweave_source_graph.mjs",
    "scripts/validate_reweave_compute.mjs",
    "scripts/run_public_reweave_demo.py",
    "reweave_frontend/app.js",
    "reweave_frontend/artifacts.js",
    "reweave_frontend/bridge.js",
    "reweave_frontend/capsule_reader.js",
    "reweave_frontend/index.html",
    "reweave_frontend/mock-data.json",
    "reweave_frontend/renderers.js",
    "reweave_frontend/source_workflow.js",
    "reweave_frontend/styles.css",
    "reweave_frontend/assets/reweave-icon.svg",
    "start_reweave_static.sh",
)
RELEASE_INCLUDED_SURFACE_FILES = REQUIRED_SURFACE_FILES

HISTORICAL_EXCLUDED_SURFACE_FILES = (
    "pimos_lite/capability_registry.py",
    "pimos_lite/capsule_module/__init__.py",
    "pimos_lite/capsule_module/contract.py",
    "pimos_lite/capsule_module/source_extract.py",
    "pimos_lite/composer/__init__.py",
    "pimos_lite/composer/intent.py",
    "pimos_lite/reweave_behavior_runtime.py",
    "pimos_lite/reweave_capsule_content.py",
    "pimos_lite/reweave_capsule_draft.py",
    "pimos_lite/reweave_capsule_verifier.py",
    "pimos_lite/reweave_capsule_warehouse.py",
    "pimos_lite/reweave_engine/__init__.py",
    "pimos_lite/reweave_engine/factory.py",
    "pimos_lite/reweave_engine/local.py",
    "pimos_lite/reweave_engine/lumo.py",
    "pimos_lite/reweave_engine/lumo_lite.py",
    "pimos_lite/reweave_engine/status.py",
    "pimos_lite/reweave_governance_preview.py",
    "pimos_lite/reweave_llm_pack.py",
    "pimos_lite/reweave_lumo_lite_artifacts.py",
    "pimos_lite/reweave_lumo_lite_state.py",
    "pimos_lite/reweave_luna_client.py",
    "pimos_lite/reweave_preview_export.py",
    "pimos_lite/reweave_preview_pack.py",
    "pimos_lite/reweave_preview_viewer.py",
    "pimos_lite/reweave_project_graph.py",
    "pimos_lite/reweave_project_renderer.py",
    "pimos_lite/reweave_promote.py",
    "pimos_lite/reweave_quality_gate.py",
    "pimos_lite/reweave_react_preview.py",
    "pimos_lite/reweave_reuse_suggestions.py",
    "pimos_lite/reweave_review_queue.py",
    "pimos_lite/reweave_snippet_context.py",
    "pimos_lite/reweave_stage4_composer.py",
    "pimos_lite/reweave_task_intent.py",
    "pimos_lite/reweave_task_plan.py",
    "pimos_lite/safe_preview_write.py",
    "scripts/analyze_reweave_behavior.mjs",
    "scripts/run_public_stage4_demo.py",
)

SURFACE_GLOBS = (
    "pimos_lite/capability_registry.py",
    "pimos_lite/capsule_module/*.py",
    "pimos_lite/composer/*.py",
    "pimos_lite/desktop_reweave_static.py",
    "pimos_lite/reweave*.py",
    "pimos_lite/reweave_engine/*.py",
    "pimos_lite/safe_preview_write.py",
    "reweave_frontend/*.js",
    "reweave_frontend/*.html",
    "reweave_frontend/*.css",
    "reweave_frontend/*.json",
    "reweave_frontend/assets/*",
    "scripts/analyze_reweave*.mjs",
    "scripts/validate_reweave_compute.mjs",
    "scripts/run_public_*.py",
    "start_reweave_static.sh",
)


def build_reweave_release_surface_audit(
    root: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(root).resolve() if root else Path(__file__).resolve().parents[1]
    entries = [_entry(base, relative) for relative in _surface_paths(base)]
    missing = [relative for relative in REQUIRED_SURFACE_FILES if not (base / relative).is_file()]
    checks = _release_checks(base)
    unknown = [
        row["path"]
        for row in entries
        if row["release_disposition"] == "unknown_release_surface"
    ]
    blockers = [name for name, passed in checks.items() if not passed]
    blockers.extend(f"unknown_release_surface:{path}" for path in unknown)
    status = "passed" if not missing and not blockers else "partial"
    included = [
        row["path"] for row in entries if row["release_disposition"] == "included"
    ]
    historical = [
        row["path"]
        for row in entries
        if row["release_disposition"] == "historical_excluded"
    ]
    launcher = _read(base / "start_reweave_static.sh")
    return {
        "audit_version": AUDIT_VERSION,
        "scope": "reweave_stage5_release_surface",
        "status": status,
        "release_surface_status": status,
        "backend_mode": "sqlite_capsule_warehouse",
        "composer_mode": "module_native_memory_input",
        "source_write_allowed": False,
        "legacy_generation_active": False,
        "stage4_coverage": "historical_excluded",
        "release_checks": checks,
        "release_blockers": blockers,
        "missing_surface_files": missing,
        "entrypoint_count": len(entries),
        "release_included_files": list(RELEASE_INCLUDED_SURFACE_FILES),
        "release_default_entrypoint_files": list(RELEASE_INCLUDED_SURFACE_FILES),
        "release_included_entrypoints": included,
        "release_historical_excluded_files": historical,
        "release_excluded_entrypoints": historical,
        "release_unknown_entrypoints": unknown,
        "entrypoints": entries,
        "launcher_bootstrap_side_effects": {
            "venv_write": "python3 -m venv" in launcher,
            "pip_network_install": 'pip" install' in launcher,
        },
        "launcher_bootstrap_policy": "explicit_user_install_only",
        "public_alpha_status": status,
        "overall_release_status": status,
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
        "generation_backend": "sqlite_capsule_warehouse",
        "boundary_line": (
            "Reweave stage 5: read-only Source Boxes; formal SQLite capsules; "
            "one module_native product path"
        ),
    }


def build_lumo_reweave_release_surface_summary(
    *,
    stage4_audit: dict[str, Any] | None = None,
    reweave_audit: dict[str, Any] | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    del stage4_audit
    reweave = reweave_audit or build_reweave_release_surface_audit(root)
    status = str(
        reweave.get("release_surface_status") or reweave.get("status") or "missing"
    )
    return {
        "summary_version": SUMMARY_VERSION,
        "overall_status": status,
        "stage4_status": "historical_excluded",
        "reweave_status": status,
        "source_project_write_allowed": False,
        "generation_backend": "sqlite_capsule_warehouse",
        "boundary_line": "no source project write; legacy generation is inactive",
        "known_limitations": [
            "historical implementation files remain on disk but are excluded from release entrypoints"
        ],
    }


def _entry(base: Path, relative: str) -> dict[str, Any]:
    path = base / relative
    return {
        "path": relative,
        "exists": path.is_file(),
        "release_role": _role(relative),
        "release_disposition": _disposition(relative),
    }


def _role(relative: str) -> str:
    if relative in HISTORICAL_EXCLUDED_SURFACE_FILES:
        return "historical_legacy_surface"
    if relative == "pimos_lite/desktop_reweave_static.py":
        return "desktop_bridge"
    if relative == "pimos_lite/reweave_app_service.py":
        return "application_service"
    if relative == "pimos_lite/composer/module_native.py":
        return "formal_composer"
    if relative == "pimos_lite/reweave_capsule_store.py":
        return "formal_sqlite_warehouse"
    if relative.startswith("pimos_lite/reweave_capsule_") or relative.endswith(
        "reweave_data_contract.py"
    ):
        return "capsule_ingestion"
    if relative in {
        "pimos_lite/reweave_javascript_source.py",
        "pimos_lite/reweave_source_registry.py",
        "pimos_lite/reweave_source_scanner.py",
    }:
        return "read_only_source_intake"
    if relative.startswith("scripts/analyze_reweave") or relative.endswith(
        "validate_reweave_compute.mjs"
    ):
        return "safety_analyzer"
    if relative == "scripts/run_public_reweave_demo.py":
        return "public_cli"
    if relative.startswith("reweave_frontend/"):
        return "frontend_shell"
    if relative == "start_reweave_static.sh":
        return "launcher"
    return "unknown"


def _disposition(relative: str) -> str:
    if relative in RELEASE_INCLUDED_SURFACE_FILES:
        return "included"
    if relative in HISTORICAL_EXCLUDED_SURFACE_FILES:
        return "historical_excluded"
    return "unknown_release_surface"


def _surface_paths(base: Path) -> list[str]:
    paths: set[str] = set()
    for pattern in SURFACE_GLOBS:
        for path in base.glob(pattern):
            if path.is_file():
                paths.add(path.relative_to(base).as_posix())
    paths.discard("pimos_lite/reweave_release_surface_audit.py")
    paths.update(REQUIRED_SURFACE_FILES)
    paths.update(
        relative
        for relative in HISTORICAL_EXCLUDED_SURFACE_FILES
        if (base / relative).is_file()
    )
    return sorted(paths)


def _release_checks(base: Path) -> dict[str, bool]:
    app_service = _read(base / "pimos_lite/reweave_app_service.py")
    composer = _read(base / "pimos_lite/composer/module_native.py")
    desktop = _read(base / "pimos_lite/desktop_reweave_static.py")
    frontend = _read(base / "reweave_frontend/app.js")
    public_cli = _read(base / "scripts/run_public_reweave_demo.py")

    preview_method = _python_function_source(app_service, "generate_preview")
    compose_method = _python_function_source(composer, "compose_capsule_product")
    desktop_method = _python_function_source(desktop, "generate_product")
    frontend_generation = _between(
        frontend,
        "function pollProductRun",
        "function applyGenerateResult",
    )
    service_calls = set(re.findall(r"\bservice\.([A-Za-z_][A-Za-z0-9_]*)\(", public_cli))
    compose_lower = compose_method.casefold()
    eager_imports = _top_level_imports(app_service) | _top_level_imports(composer)
    historical_modules = {
        relative.removesuffix(".py").replace("/", ".")
        for relative in HISTORICAL_EXCLUDED_SURFACE_FILES
        if relative.startswith("pimos_lite/")
        and relative.endswith(".py")
        and not relative.endswith("/__init__.py")
    }
    historical_prefixes = ("pimos_lite.capsule_module", "pimos_lite.reweave_engine")
    return {
        "app_service_legacy_preview_is_inactive": (
            bool(preview_method)
            and 'self._error("legacy_generation_inactive")' in preview_method
        ),
        "public_cli_uses_formal_app_service_only": (
            "ReweaveAppService" in public_cli
            and service_calls
            == {"generate_product", "get_intake_run", "close"}
            and all(
                token not in public_cli
                for token in (
                    "create_reweave_engine",
                    "generate_preview",
                    "promote_source",
                    "LumoLiteReweaveEngine",
                    "ollama",
                    "fallback",
                )
            )
        ),
        "frontend_uses_formal_generation_only": (
            bool(frontend_generation)
            and 'bridgeCall("generate_product"' in frontend_generation
            and 'bridgeCall("get_intake_run"' in frontend_generation
            and 'selection_mode: "manual"' in frontend_generation
            and "usedCapsuleIds.length === 0" in frontend
            and "auto_match" not in frontend
            and "generate_preview" not in frontend
            and "stage4_module_native" not in frontend
            and re.search(r"\borigin\b", frontend, re.IGNORECASE) is None
            and "model" not in frontend_generation.casefold()
        ),
        "sqlite_generation_is_active": (
            '"generationActive": True' in app_service
            and '"generationFromSqlite": True' in app_service
        ),
        "module_native_formal_composer_present": bool(compose_method),
        "module_native_formal_composer_is_memory_only": (
            bool(compose_method)
            and "capsules" in compose_method
            and all(
                token not in compose_lower
                for token in (
                    "capsule_path",
                    "sqlite3",
                    "read_connection",
                    "capsulewarehousestore",
                    "load_module_capsules",
                )
            )
        ),
        "formal_startup_avoids_eager_legacy_imports": not any(
            module in historical_modules
            or any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in historical_prefixes
            )
            for module in eager_imports
        ),
        "desktop_bridge_exposes_formal_generation": (
            bool(desktop_method)
            and '_phase4_call("generate_product"' in desktop_method
        ),
    }


def _top_level_imports(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _python_function_source(source: str, function_name: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    return ""


def _between(source: str, start: str, end: str) -> str:
    start_index = source.find(start)
    if start_index < 0:
        return ""
    end_index = source.find(end, start_index + len(start))
    return source[start_index:] if end_index < 0 else source[start_index:end_index]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""
