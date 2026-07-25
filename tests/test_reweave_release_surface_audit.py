from __future__ import annotations

import ast
from pathlib import Path

from pimos_lite.reweave_canonical import (
    canonical_json_bytes,
    canonical_json_digest,
)
from pimos_lite.reweave_release_surface_audit import (
    _disposition,
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

    assert audit["audit_version"] == "reweave_release_surface_audit.v2"
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
        "sqlite_generation_is_active": True,
        "module_native_formal_composer_present": True,
        "module_native_formal_composer_is_memory_only": True,
        "formal_startup_avoids_eager_legacy_imports": True,
        "desktop_bridge_exposes_formal_generation": True,
        "product_planning_is_local_review_only": True,
        "desktop_bridge_exposes_product_planning": True,
    }


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
