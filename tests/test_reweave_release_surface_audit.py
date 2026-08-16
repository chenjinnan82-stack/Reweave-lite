from __future__ import annotations

import ast
import shutil
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_canonical import (
    canonical_json_bytes,
    canonical_json_digest,
)
from pimos_lite.reweave_release_surface_audit import (
    FRONTEND_LOADED_SCRIPTS,
    REQUIRED_SURFACE_FILES,
    _disposition,
    _frontend_loaded_scripts,
    build_lumo_reweave_release_surface_summary,
    build_reweave_public_alpha_release_summary,
    build_reweave_release_surface_audit,
)


ROOT = Path(__file__).resolve().parents[1]


def test_shared_canonical_json_digest_is_fixed() -> None:
    value = {"b": 2, "a": 1}

    assert canonical_json_bytes(value) == b'{"a":1,"b":2}'
    assert (
        canonical_json_digest(value)
        == "43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777"
    )


def test_pimos_lite_internal_import_graph_is_acyclic() -> None:
    modules: dict[str, Path] = {}
    for path in (ROOT / "pimos_lite").rglob("*.py"):
        parts = list(path.relative_to(ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules[".".join(parts)] = path
    imports = {name: set() for name in modules}
    for name, path in modules.items():
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    prefix = package.split(".")
                    if node.level > 1:
                        prefix = prefix[: -(node.level - 1)]
                    base = ".".join(
                        [*prefix, *((node.module or "").split("."))]
                    ).strip(".")
                else:
                    base = node.module or ""
                targets = [base] if base else []
                targets.extend(
                    f"{base}.{alias.name}".strip(".")
                    for alias in node.names
                    if alias.name != "*"
                )
            imports[name].update(target for target in targets if target in modules)

    visited: set[str] = set()
    active: list[str] = []

    def visit(module: str) -> None:
        if module in active:
            cycle = " -> ".join([*active[active.index(module) :], module])
            raise AssertionError(f"internal import cycle: {cycle}")
        if module in visited:
            return
        active.append(module)
        for dependency in sorted(imports[module]):
            visit(dependency)
        active.pop()
        visited.add(module)

    for module in sorted(modules):
        visit(module)

    canonical = "pimos_lite.reweave_canonical"
    store = "pimos_lite.reweave_capsule_store"
    assert canonical in imports["pimos_lite.reweave_capsule_store"]
    assert canonical in imports["pimos_lite.reweave_page_capability_contract"]
    assert canonical in imports["pimos_lite.composer.module_native"]
    assert canonical in imports["pimos_lite.reweave_product_planner"]
    assert canonical in imports["pimos_lite.reweave_plan_execution"]
    assert store not in imports["pimos_lite.reweave_page_capability_contract"]
    assert store not in imports["pimos_lite.composer.module_native"]


def test_reweave_release_surface_audit_matches_stage5_mainline() -> None:
    audit = build_reweave_release_surface_audit(ROOT)

    assert audit["audit_version"] == "reweave_release_surface_audit.v3"
    assert audit["scope"] == "reweave_stage5_release_surface"
    assert audit["status"] == "passed"
    assert audit["release_surface_status"] == "passed"
    assert audit["backend_mode"] == "sqlite_capsule_warehouse"
    assert audit["composer_mode"] == "module_native_memory_input"
    assert audit["stage4_coverage"] == "historical_excluded"
    assert audit["source_write_allowed"] is False
    assert audit["legacy_generation_active"] is False
    assert audit["missing_surface_files"] == []
    assert audit["release_blockers"] == []
    assert audit["release_unknown_entrypoints"] == []
    assert audit["frontend_loaded_scripts"] == list(FRONTEND_LOADED_SCRIPTS)
    assert all(audit["release_checks"].values())
    assert audit["launcher_bootstrap_side_effects"] == {
        "venv_write": False,
        "pip_network_install": False,
    }


def test_stage5_formal_and_historical_surfaces_are_separate() -> None:
    audit = build_reweave_release_surface_audit(ROOT)
    included = set(audit["release_included_entrypoints"])
    historical = set(audit["release_excluded_entrypoints"])

    assert {
        "pimos_lite/desktop_reweave_static.py",
        "pimos_lite/reweave_app_service.py",
        "pimos_lite/reweave_canonical.py",
        "pimos_lite/reweave_plan_execution.py",
        "pimos_lite/reweave_product_planner.py",
        "pimos_lite/composer/module_native.py",
        "pimos_lite/reweave_capsule_store.py",
        "pimos_lite/reweave_capsule_intake.py",
        "pimos_lite/reweave_capsule_stage3.py",
        "pimos_lite/reweave_capsule_worker.py",
        "pimos_lite/reweave_data_contract.py",
        "pimos_lite/reweave_process_environment.py",
        "pimos_lite/reweave_javascript_source.py",
        "pimos_lite/reweave_static_web_target.py",
        "scripts/analyze_reweave_extraction.mjs",
        "scripts/analyze_reweave_security.mjs",
        "scripts/analyze_reweave_source_graph.mjs",
        "scripts/validate_reweave_compute.mjs",
        "scripts/run_public_reweave_demo.py",
        "reweave_frontend/app.js",
        "start_reweave_static.sh",
    } <= included
    assert {
        "pimos_lite/reweave_llm_pack.py",
        "pimos_lite/reweave_engine/factory.py",
        "pimos_lite/reweave_preview_export.py",
        "pimos_lite/reweave_preview_pack.py",
        "pimos_lite/reweave_promote.py",
        "pimos_lite/reweave_stage4_composer.py",
        "scripts/analyze_reweave_behavior.mjs",
    } <= historical
    assert included.isdisjoint(historical)

    dispositions = {
        row["path"]: row["release_disposition"] for row in audit["entrypoints"]
    }
    assert dispositions["scripts/run_public_reweave_demo.py"] == "included"
    assert dispositions["pimos_lite/reweave_plan_execution.py"] == "included"
    assert dispositions["pimos_lite/composer/__init__.py"] == "included"
    assert dispositions["pimos_lite/reweave_llm_pack.py"] == "historical_excluded"

    javascript_source = next(
        row
        for row in audit["entrypoints"]
        if row["path"] == "pimos_lite/reweave_javascript_source.py"
    )
    assert javascript_source["release_disposition"] == "included"
    assert javascript_source["release_role"] == "read_only_source_intake"

    target_planner = next(
        row
        for row in audit["entrypoints"]
        if row["path"] == "pimos_lite/reweave_static_web_target.py"
    )
    assert target_planner["release_disposition"] == "included"
    assert target_planner["release_role"] == "static_web_target_planner"


def test_stage5_contract_checks_are_explicit() -> None:
    checks = build_reweave_release_surface_audit(ROOT)["release_checks"]

    assert checks == {
        "app_service_legacy_preview_is_inactive": True,
        "public_cli_uses_formal_app_service_only": True,
        "frontend_uses_formal_generation_only": True,
        "frontend_loaded_scripts_closed_world": True,
        "frontend_generation_actions_formal_only": True,
        "legacy_json_mutators_absent_from_loaded_frontend": True,
        "sqlite_generation_is_active": True,
        "module_native_formal_composer_present": True,
        "module_native_package_exports_formal_only": True,
        "module_native_formal_composer_is_memory_only": True,
        "formal_startup_avoids_eager_legacy_imports": True,
        "desktop_bridge_exposes_formal_generation": True,
        "legacy_json_mutators_absent_from_desktop_bridge": True,
        "public_product_actions_use_formal_generation_only": True,
        "agent_candidate_actions_have_public_product_boundary": True,
        "formal_entrypoints_exclude_stage4_composer": True,
        "product_planning_is_local_review_only": True,
        "desktop_bridge_exposes_product_planning": True,
    }

    import pimos_lite.composer as composer_package
    from pimos_lite.composer.module_native import compose_module_native_preview
    from pimos_lite.reweave_app_service import PUBLIC_PRODUCT_ACTIONS

    assert composer_package.__all__ == ["compose_capsule_product"]
    assert callable(composer_package.compose_capsule_product)
    assert not hasattr(composer_package, "compose_module_native_preview")
    assert callable(compose_module_native_preview)
    assert "generate_product" in PUBLIC_PRODUCT_ACTIONS
    assert "get_confirmed_product_plan" in PUBLIC_PRODUCT_ACTIONS
    assert "start_confirmed_product_candidate" in PUBLIC_PRODUCT_ACTIONS
    assert "generate_preview" not in PUBLIC_PRODUCT_ACTIONS


def test_reweave_public_release_summaries_use_sqlite_mainline() -> None:
    audit = build_reweave_release_surface_audit(ROOT)
    public = build_reweave_public_alpha_release_summary(reweave_audit=audit)
    compatibility = build_lumo_reweave_release_surface_summary(
        stage4_audit={"stage4_status": "passed"},
        reweave_audit=audit,
    )

    assert public["summary_version"] == "reweave_public_alpha_release_summary.v2"
    assert public["overall_status"] == "passed"
    assert public["generation_backend"] == "sqlite_capsule_warehouse"
    assert "formal SQLite capsules" in public["boundary_line"]
    assert compatibility["summary_version"] == "reweave_release_surface_summary.v2"
    assert compatibility["overall_status"] == "passed"
    assert compatibility["stage4_status"] == "historical_excluded"
    assert compatibility["generation_backend"] == "sqlite_capsule_warehouse"


def test_unknown_release_surface_still_fails_closed() -> None:
    assert _disposition("pimos_lite/reweave_new_entry.py") == "unknown_release_surface"


def _copy_release_surface(target: Path) -> None:
    for relative in REQUIRED_SURFACE_FILES:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    (target / "node_modules").mkdir()
    shutil.copytree(
        ROOT / "node_modules/typescript",
        target / "node_modules/typescript",
    )


def test_frontend_script_manifest_rejects_nonlocal_or_undeclared_scripts(
    tmp_path: Path,
) -> None:
    frontend = tmp_path / "reweave_frontend"
    frontend.mkdir()
    for name in FRONTEND_LOADED_SCRIPTS:
        shutil.copy2(ROOT / "reweave_frontend" / name, frontend / name)
    original = (ROOT / "reweave_frontend/index.html").read_text(encoding="utf-8")
    cases = (
        original.replace('src="bridge.js"', 'src="https://example.test/bridge.js"'),
        original.replace('src="bridge.js"', 'src="/bridge.js"'),
        original.replace('src="bridge.js"', 'src="../bridge.js"'),
        original.replace('src="bridge.js"', 'src="bridge.js?old=1"'),
        original.replace(
            '<script src="bridge.js"></script>',
            '<script async src="bridge.js"></script>',
        ),
        original.replace(
            '<script src="bridge.js"></script>',
            '<script src="bridge.js"></script><script src="bridge.js"></script>',
        ),
        original.replace(
            '<script src="bridge.js"></script>',
            '<script>window.retired = true;</script><script src="bridge.js"></script>',
        ),
    )
    for value in cases:
        (frontend / "index.html").write_text(value, encoding="utf-8")
        assert _frontend_loaded_scripts(tmp_path) is None

    (frontend / "index.html").write_text(original, encoding="utf-8")
    (frontend / "bridge.js").unlink()
    assert _frontend_loaded_scripts(tmp_path) is None
    (frontend / "bridge.js").symlink_to(ROOT / "reweave_frontend/bridge.js")
    assert _frontend_loaded_scripts(tmp_path) is None


def test_release_audit_fails_closed_for_extra_script_or_retired_generation(
    tmp_path: Path,
) -> None:
    _copy_release_surface(tmp_path)
    index = tmp_path / "reweave_frontend/index.html"
    original_index = index.read_text(encoding="utf-8")
    retired = tmp_path / "reweave_frontend/retired.js"
    retired.write_text('bridgeCall("generate_preview", {});\n', encoding="utf-8")
    index.write_text(
        original_index.replace(
            '<script src="app.js"></script>',
            '<script src="retired.js"></script><script src="app.js"></script>',
        ),
        encoding="utf-8",
    )
    audit = build_reweave_release_surface_audit(tmp_path)
    assert audit["status"] == "partial"
    assert audit["release_checks"]["frontend_loaded_scripts_closed_world"] is False

    index.write_text(original_index, encoding="utf-8")
    product_scene = tmp_path / "reweave_frontend/product_plan_scene.js"
    original_scene = product_scene.read_text(encoding="utf-8")
    product_scene.write_text(
        original_scene + '\nbridgeCall("generate_preview", {});\n',
        encoding="utf-8",
    )
    audit = build_reweave_release_surface_audit(tmp_path)
    assert audit["status"] == "partial"
    assert (
        audit["release_checks"]["frontend_generation_actions_formal_only"] is False
    )

    product_scene.write_text("function {", encoding="utf-8")
    audit = build_reweave_release_surface_audit(tmp_path)
    assert audit["status"] == "partial"
    assert audit["release_checks"]["frontend_generation_actions_formal_only"] is False


def test_release_audit_fails_closed_without_typescript_analysis() -> None:
    with patch(
        "pimos_lite.reweave_release_surface_audit.shutil.which",
        return_value=None,
    ):
        audit = build_reweave_release_surface_audit(ROOT)

    assert audit["status"] == "partial"
    assert audit["release_checks"]["frontend_generation_actions_formal_only"] is False
    assert (
        audit["release_checks"]["legacy_json_mutators_absent_from_loaded_frontend"]
        is False
    )
