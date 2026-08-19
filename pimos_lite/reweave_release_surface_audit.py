from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit


AUDIT_VERSION = "reweave_release_surface_audit.v3"
SUMMARY_VERSION = "reweave_release_surface_summary.v2"
PUBLIC_ALPHA_SUMMARY_VERSION = "reweave_public_alpha_release_summary.v2"

FRONTEND_LOADED_SCRIPTS = (
    "bridge.js",
    "renderers.js",
    "artifacts.js",
    "source_workflow.js",
    "capsule_reader.js",
    "capsule_warehouse_scene.js",
    "product_plan_scene.js",
    "target_workflow.js",
    "app.js",
)
LEGACY_JSON_MUTATORS = frozenset(
    {
        "choose_source_folder",
        "scan_source_box",
        "draft_capsules",
        "promote_source_drafts",
    }
)


REQUIRED_SURFACE_FILES = (
    "pimos_lite/desktop_reweave_static.py",
    "pimos_lite/reweave_app_service.py",
    "pimos_lite/reweave_agent_stdio.py",
    "pimos_lite/reweave_canonical.py",
    "pimos_lite/reweave_plan_execution.py",
    "pimos_lite/reweave_page_capability_contract.py",
    "pimos_lite/reweave_product_planner.py",
    "pimos_lite/composer/__init__.py",
    "pimos_lite/composer/module_native.py",
    "pimos_lite/reweave_capsule_store.py",
    "pimos_lite/reweave_capsule_intake.py",
    "pimos_lite/reweave_capsule_stage3.py",
    "pimos_lite/reweave_capsule_worker.py",
    "pimos_lite/reweave_data_contract.py",
    "pimos_lite/reweave_experience.py",
    "pimos_lite/reweave_process_environment.py",
    "pimos_lite/reweave_source_derivation.py",
    "pimos_lite/reweave_javascript_source.py",
    "pimos_lite/reweave_static_web_target.py",
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
    "reweave_frontend/capsule_warehouse_scene.js",
    "reweave_frontend/index.html",
    "reweave_frontend/mock-data.json",
    "reweave_frontend/product_plan_scene.js",
    "reweave_frontend/renderers.js",
    "reweave_frontend/source_workflow.js",
    "reweave_frontend/target_workflow.js",
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
    loaded_scripts = _frontend_loaded_scripts(base)
    checks = _release_checks(base, loaded_scripts)
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
        "frontend_loaded_scripts": loaded_scripts or [],
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
    if relative == "pimos_lite/reweave_agent_stdio.py":
        return "local_agent_jsonl_entry"
    if relative == "pimos_lite/reweave_canonical.py":
        return "deterministic_canonical_contract"
    if relative == "pimos_lite/reweave_plan_execution.py":
        return "confirmed_plan_execution_compiler"
    if relative == "pimos_lite/reweave_page_capability_contract.py":
        return "formal_page_capability_contract"
    if relative == "pimos_lite/reweave_product_planner.py":
        return "local_product_planner"
    if relative == "pimos_lite/composer/__init__.py":
        return "formal_composer_package"
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
    if relative == "pimos_lite/reweave_static_web_target.py":
        return "static_web_target_planner"
    if relative == "pimos_lite/reweave_experience.py":
        return "project_local_experience"
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


def _release_checks(
    base: Path,
    loaded_scripts: list[str] | None = None,
) -> dict[str, bool]:
    app_service = _read(base / "pimos_lite/reweave_app_service.py")
    composer_package = _read(base / "pimos_lite/composer/__init__.py")
    composer = _read(base / "pimos_lite/composer/module_native.py")
    desktop = _read(base / "pimos_lite/desktop_reweave_static.py")
    product_planner = _read(base / "pimos_lite/reweave_product_planner.py")
    frontend = _read(base / "reweave_frontend/app.js")
    public_cli = _read(base / "scripts/run_public_reweave_demo.py")

    preview_method = _python_function_source(app_service, "generate_preview")
    compose_method = _python_function_source(composer, "compose_capsule_product")
    desktop_method = _python_function_source(desktop, "generate_product")
    desktop_plan_method = _python_function_source(desktop, "start_product_plan")
    desktop_plan_suggestion_method = _python_function_source(
        desktop,
        "suggest_product_plan_action",
    )
    frontend_generation = _between(
        frontend,
        "function pollProductRun",
        "function applyGenerateResult",
    )
    service_calls = set(re.findall(r"\bservice\.([A-Za-z_][A-Za-z0-9_]*)\(", public_cli))
    compose_lower = compose_method.casefold()
    eager_imports = _top_level_imports(app_service) | _top_level_imports(composer)
    composer_exports = _python_string_collection(composer_package, "__all__")
    composer_imports = _python_from_imports(composer_package)
    bridge_slots = _python_slot_methods(desktop)
    public_product_actions = _python_string_collection(
        app_service,
        "PUBLIC_PRODUCT_ACTIONS",
    )
    loaded_scripts = (
        _frontend_loaded_scripts(base) if loaded_scripts is None else loaded_scripts
    )
    frontend_actions = (
        _javascript_frontend_actions(
            base,
            [base / "reweave_frontend" / name for name in loaded_scripts],
        )
        if loaded_scripts is not None
        else {}
    )
    formal_imports: set[str] = set()
    for relative in REQUIRED_SURFACE_FILES:
        if relative.endswith(".py"):
            formal_imports.update(_python_import_references(_read(base / relative)))
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
            == {
                "generate_product",
                "get_intake_run",
                "cancel_intake_run",
                "close",
            }
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
            and frontend_actions.get("bridge_generation_actions")
            == ["generate_product"]
            and frontend_actions.get("generation_literals")
            == ["generate_product"]
            and 'selection_mode: "manual"' in frontend_generation
            and "usedCapsuleIds.length === 0" in frontend
            and "auto_match" not in frontend
            and "stage4_module_native" not in frontend
            and re.search(r"\borigin\b", frontend, re.IGNORECASE) is None
            and "model" not in frontend_generation.casefold()
        ),
        "frontend_loaded_scripts_closed_world": (
            loaded_scripts == list(FRONTEND_LOADED_SCRIPTS)
        ),
        "frontend_generation_actions_formal_only": (
            frontend_actions.get("bridge_generation_actions")
            == ["generate_product"]
            and frontend_actions.get("generation_literals")
            == ["generate_product"]
        ),
        "legacy_json_mutators_absent_from_loaded_frontend": (
            frontend_actions.get("legacy_mutator_references") == []
        ),
        "sqlite_generation_is_active": (
            '"generationActive": True' in app_service
            and '"generationFromSqlite": True' in app_service
        ),
        "module_native_formal_composer_present": bool(compose_method),
        "module_native_package_exports_formal_only": (
            composer_exports == {"compose_capsule_product"}
            and composer_imports
            == {
                (
                    "pimos_lite.composer.module_native",
                    "compose_capsule_product",
                )
            }
        ),
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
            and bridge_slots.intersection(
                {"generate_product", "generate_preview", "notify_generate"}
            )
            == {"generate_product"}
        ),
        "legacy_json_mutators_absent_from_desktop_bridge": (
            not bridge_slots.intersection(LEGACY_JSON_MUTATORS)
        ),
        "public_product_actions_use_formal_generation_only": (
            "generate_product" in public_product_actions
            and "generate_preview" not in public_product_actions
            and "notify_generate" not in public_product_actions
        ),
        "agent_candidate_actions_have_public_product_boundary": (
            {
                "get_confirmed_product_plan",
                "start_confirmed_product_candidate",
            }
            <= public_product_actions
        ),
        "formal_entrypoints_exclude_stage4_composer": (
            not any(
                module == "pimos_lite.reweave_stage4_composer"
                or module.startswith("pimos_lite.reweave_stage4_composer.")
                for module in formal_imports
            )
        ),
        "product_planning_is_local_review_only": (
            "class ProductPlanner" in product_planner
            and "ProxyHandler({})" in product_planner
            and "product_workspaces_only" in product_planner
            and "candidate_generated" in product_planner
            and "product_generated" in product_planner
            and "compose_capsule_product" not in product_planner
            and "product_capsule_usage" not in product_planner
            and "api.openai.com" not in product_planner
        ),
        "desktop_bridge_exposes_product_planning": (
            bool(desktop_plan_method)
            and '_phase4_call("start_product_plan"' in desktop_plan_method
            and bool(desktop_plan_suggestion_method)
            and "_phase4_call(" in desktop_plan_suggestion_method
            and '"suggest_product_plan_action"' in desktop_plan_suggestion_method
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


def _python_string_collection(source: str, name: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "frozenset"
            and len(value.args) == 1
            and not value.keywords
        ):
            value = value.args[0]
        try:
            collection = ast.literal_eval(value)
        except (ValueError, TypeError):
            return set()
        if not isinstance(collection, (list, tuple, set, frozenset)) or not all(
            isinstance(item, str) for item in collection
        ):
            return set()
        return set(collection)
    return set()


def _python_from_imports(source: str) -> set[tuple[str, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    return {
        (node.module, alias.name)
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }


def _python_slot_methods(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    methods: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            decorator_name = (
                target.id
                if isinstance(target, ast.Name)
                else target.attr
                if isinstance(target, ast.Attribute)
                else ""
            )
            if decorator_name == "Slot":
                methods.add(node.name)
                break
    return methods


def _python_import_references(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Call) and node.args:
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else ""
            )
            if (
                name in {"__import__", "import_module"}
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                modules.add(node.args[0].value)
    return modules


class _FrontendScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[str] = []
        self.valid = True
        self._inside_script = False
        self._script_src: str | None = None
        self._script_type = ""
        self._script_body: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() != "script":
            return
        if self._inside_script:
            self.valid = False
            return
        names = [name.casefold() for name, _value in attrs]
        if len(names) != len(set(names)):
            self.valid = False
        values = {
            name.casefold(): value or ""
            for name, value in attrs
        }
        self._inside_script = True
        self._script_src = values.get("src")
        self._script_type = values.get("type", "").strip().casefold()
        self._script_body = []
        if self._script_src is not None:
            if set(names) != {"src"}:
                self.valid = False
            self.scripts.append(self._script_src)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() == "script":
            self.valid = False

    def handle_data(self, data: str) -> None:
        if self._inside_script:
            self._script_body.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "script":
            return
        if not self._inside_script:
            self.valid = False
            return
        body = "".join(self._script_body).strip()
        if self._script_src is None:
            if self._script_type != "application/json":
                self.valid = False
        elif body:
            self.valid = False
        self._inside_script = False
        self._script_src = None
        self._script_type = ""
        self._script_body = []

    def close(self) -> None:
        super().close()
        if self._inside_script:
            self.valid = False


def _frontend_loaded_scripts(base: Path) -> list[str] | None:
    index = base / "reweave_frontend/index.html"
    if not index.is_file() or index.is_symlink():
        return None
    try:
        parser = _FrontendScriptParser()
        parser.feed(index.read_text(encoding="utf-8"))
        parser.close()
    except (OSError, UnicodeError):
        return None
    scripts = parser.scripts
    if (
        not parser.valid
        or index.parent.is_symlink()
        or scripts != list(FRONTEND_LOADED_SCRIPTS)
        or len(scripts) != len(set(scripts))
    ):
        return None
    frontend_root = index.parent
    for source in scripts:
        parsed = urlsplit(source)
        relative = PurePosixPath(parsed.path)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or "\\" in source
            or relative.is_absolute()
            or ".." in relative.parts
        ):
            return None
        path = frontend_root.joinpath(*relative.parts)
        if path.is_symlink() or not path.is_file():
            return None
    return scripts


def _javascript_frontend_actions(
    base: Path,
    paths: list[Path],
) -> dict[str, list[str]]:
    node = shutil.which("node")
    if not node or not paths or any(not path.is_file() for path in paths):
        return {}
    probe = r"""
import fs from "node:fs";
import * as ts from "typescript";
const names = new Set(["generate_product", "generate_preview", "notify_generate"]);
const legacy = new Set([
  "choose_source_folder",
  "scan_source_box",
  "draft_capsules",
  "promote_source_drafts",
]);
const generationLiterals = new Set();
const bridgeGenerationActions = new Set();
const bridgeActions = new Set();
const legacyMutatorReferences = new Set();
function visit(current) {
  if (ts.isStringLiteralLike(current) && names.has(current.text)) {
    generationLiterals.add(current.text);
  }
  if (
    (ts.isStringLiteralLike(current) || ts.isIdentifier(current))
    && legacy.has(current.text)
  ) {
    legacyMutatorReferences.add(current.text);
  }
  if (
    ts.isCallExpression(current)
    && ts.isIdentifier(current.expression)
    && current.expression.text === "bridgeCall"
    && current.arguments.length
    && ts.isStringLiteralLike(current.arguments[0])
  ) {
    const action = current.arguments[0].text;
    bridgeActions.add(action);
    if (names.has(action)) bridgeGenerationActions.add(action);
  }
  ts.forEachChild(current, visit);
}
for (const path of process.argv.slice(1)) {
  const source = fs.readFileSync(path, "utf8");
  const tree = ts.createSourceFile(
    path,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.JS,
  );
  if (tree.parseDiagnostics.length) process.exit(2);
  visit(tree);
}
process.stdout.write(JSON.stringify({
  bridge_actions: [...bridgeActions].sort(),
  bridge_generation_actions: [...bridgeGenerationActions].sort(),
  generation_literals: [...generationLiterals].sort(),
  legacy_mutator_references: [...legacyMutatorReferences].sort(),
}));
"""
    try:
        completed = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                probe,
                *(str(path) for path in paths),
            ],
            cwd=base,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        value = json.loads(completed.stdout) if completed.returncode == 0 else {}
    except (json.JSONDecodeError, OSError, subprocess.TimeoutExpired):
        return {}
    if not isinstance(value, dict) or any(
        not isinstance(value.get(key), list)
        or not all(isinstance(item, str) for item in value[key])
        for key in (
            "bridge_actions",
            "bridge_generation_actions",
            "generation_literals",
            "legacy_mutator_references",
        )
    ):
        return {}
    return value


def _between(source: str, start: str, end: str) -> str:
    start_index = source.find(start)
    if start_index < 0:
        return ""
    end_index = source.find(end, start_index + len(start))
    return source[start_index:] if end_index < 0 else source[start_index:end_index]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""
