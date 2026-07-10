"""Materialize and compile a bounded React/Vite preview from capsule state."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pimos_lite.reweave_capsule_content import is_allowed_relative_path, load_capsule_content


SCHEMA_VERSION = "reweave_react_preview.v1"
RUNTIME_DEPENDENCY_ALLOWLIST = frozenset({"react", "react-dom"})


def _receipt(status: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "source_project_write": False,
        "preview_output_write": status in {"passed", "unavailable", "failed"},
        "network_call": False,
        **extra,
    }


def _complete_snippets(capsule_ids: list[str], targets: list[str]) -> tuple[dict[str, str], list[str]]:
    wanted = set(targets)
    files: dict[str, str] = {}
    for capsule_id in capsule_ids:
        record = load_capsule_content(capsule_id)
        project_files = record.get("project_files") if isinstance(record, dict) else None
        for item in project_files if isinstance(project_files, list) else []:
            if not isinstance(item, dict):
                continue
            relative = str(item.get("relative_path") or "")
            if relative in wanted and isinstance(item.get("content"), str):
                files.setdefault(relative, str(item["content"]))
        snippets = record.get("snippets") if isinstance(record, dict) else None
        for snippet in snippets if isinstance(snippets, list) else []:
            if not isinstance(snippet, dict):
                continue
            relative = str(snippet.get("relative_path") or "")
            if relative not in wanted:
                continue
            if snippet.get("truncated") or snippet.get("redacted"):
                continue
            files.setdefault(relative, str(snippet.get("preview") or ""))
    missing = sorted(wanted - files.keys())
    return files, missing


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _static_text_slots(
    files: dict[str, str],
    project_targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    component_paths = [
        str(item.get("path") or "")
        for item in project_targets
        if isinstance(item, dict) and item.get("kind") == "component"
    ]
    slots: list[dict[str, Any]] = []
    for relative in component_paths:
        source = files.get(relative)
        if source is None:
            continue
        for tag, kind in (("h1", "heading"), ("h2", "heading"), ("p", "description"), ("button", "action")):
            pattern = re.compile(
                rf"(<{tag}\b[^>]*>)([^<>{{}}\r\n]{{1,160}})(</{tag}>)",
                flags=re.IGNORECASE,
            )
            slots.extend(
                {
                    "slot_id": f"{relative}:{tag}:{occurrence}",
                    "file": relative,
                    "tag": tag,
                    "occurrence": occurrence,
                    "kind": kind,
                }
                for occurrence, _match in enumerate(pattern.finditer(source))
            )
    return slots


def _replace_static_slot(source: str, slot: dict[str, Any], replacement: str) -> str:
    tag = str(slot.get("tag") or "")
    wanted = int(slot.get("occurrence") or 0)
    pattern = re.compile(
        rf"(<{tag}\b[^>]*>)([^<>{{}}\r\n]{{1,160}})(</{tag}>)",
        flags=re.IGNORECASE,
    )
    occurrence = -1

    def replace(match: re.Match[str]) -> str:
        nonlocal occurrence
        occurrence += 1
        return f"{match.group(1)}{replacement}{match.group(3)}" if occurrence == wanted else match.group(0)

    return pattern.sub(replace, source)


def _adapt_static_slots(
    files: dict[str, str],
    task: str,
    project_targets: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, Any]]:
    slots = _static_text_slots(files, project_targets)
    headings = [slot for slot in slots if slot["kind"] == "heading"]

    def heading_priority(slot: dict[str, Any]) -> tuple[int, str]:
        stem = Path(str(slot.get("file") or "")).stem.lower()
        return (0 if stem == "app" else 1 if "home" in stem else 2, str(slot.get("file") or ""))

    selected = min(headings, key=heading_priority) if headings else None
    public_slots = [{key: value for key, value in slot.items() if key != "occurrence"} for slot in slots]
    if selected is None:
        return dict(files), {
            "status": "needs_review",
            "mode": "safe_static_text_slots",
            "reason": "safe_static_heading_not_found",
            "slots": public_slots,
            "changes": [],
            "source_project_write": False,
        }
    replacement = html.escape((task or "Reweave task")[:160], quote=False)
    replacement = replacement.replace("{", "&#123;").replace("}", "&#125;")
    updated = dict(files)
    relative = str(selected["file"])
    updated[relative] = _replace_static_slot(updated[relative], selected, replacement)
    return updated, {
        "status": "applied",
        "mode": "safe_static_text_slots",
        "slots": public_slots,
        "changes": [
            {
                "slot_id": selected["slot_id"],
                "reason": "task_goal",
                "value": replacement,
            }
        ],
        "source_project_write": False,
    }


def _compile(project_root: Path, entrypoint: str, external_dependencies: list[str]) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    esbuild = repo_root / "node_modules" / "esbuild" / "lib" / "main.js"
    node = shutil.which("node")
    if not node or not esbuild.is_file():
        return _receipt("unavailable", "esbuild_not_installed")
    outfile = project_root / "dist" / "app.js"
    outfile.parent.mkdir(parents=True, exist_ok=True)
    unsupported = sorted(set(external_dependencies) - RUNTIME_DEPENDENCY_ALLOWLIST)
    external = sorted(
        {
            value
            for name in unsupported
            for value in (str(name), f"{name}/*")
            if name
        }
    )
    script = (
        "const esbuild=require(process.argv[1]);"
        "esbuild.buildSync({entryPoints:[process.argv[2]],outfile:process.argv[3],"
        "bundle:true,platform:'browser',format:'esm',jsx:'automatic',logLevel:'silent',"
        "external:JSON.parse(process.argv[4]),nodePaths:[process.argv[5]]});"
    )
    try:
        completed = subprocess.run(
            [
                node,
                "-e",
                script,
                str(esbuild),
                str(project_root / entrypoint),
                str(outfile),
                json.dumps(external),
                str(repo_root / "node_modules"),
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return _receipt("failed", "esbuild_compile_timeout", compiler="esbuild")
    except OSError:
        return _receipt("unavailable", "esbuild_launch_failed", compiler="esbuild")
    compiled = [path.relative_to(project_root).as_posix() for path in sorted(outfile.parent.glob("*"))]
    if completed.returncode:
        return _receipt(
            "failed",
            "esbuild_compile_failed",
            detail=(completed.stderr or completed.stdout)[-400:],
            compiled_files=compiled,
            compiler="esbuild",
            external_dependencies=external,
            compiler_status="failed",
        )
    if unsupported:
        return _receipt(
            "needs_review",
            "unsupported_runtime_dependencies",
            preview_output_write=True,
            compiled_files=compiled,
            compiler="esbuild",
            compiler_status="passed",
            compile_scope="local_modules_compiled_unsupported_dependencies_externalized",
            unsupported_dependencies=unsupported,
        )
    return _receipt(
        "passed",
        "local_module_graph_compiled",
        compiled_files=compiled,
        compiler="esbuild",
        compiler_status="passed",
        compile_scope="allowlisted_runtime_dependencies_bundled",
        external_dependencies=[],
    )


def build_react_preview(
    root: Path,
    task: str,
    project_graph: dict[str, Any],
    capsule_ids: list[str],
    project_targets: list[dict[str, Any]],
) -> dict[str, Any]:
    target_paths = [
        str(item.get("path") or "")
        for item in project_targets
        if isinstance(item, dict) and is_allowed_relative_path(str(item.get("path") or ""))
    ]
    entrypoints = [str(item) for item in project_graph.get("entrypoints", []) if item]
    if not target_paths or not entrypoints or entrypoints[0] not in target_paths:
        return _receipt("needs_review", "project_targets_incomplete", missing_files=target_paths)
    runtime_files = [str(path) for path in project_graph.get("runtime_files", []) if path]
    missing_targets = sorted(set(runtime_files) - set(target_paths))
    if missing_targets:
        return _receipt(
            "needs_review",
            "project_runtime_closure_unbounded",
            missing_files=missing_targets,
        )
    files, missing = _complete_snippets(capsule_ids, target_paths)
    if missing:
        return _receipt("needs_review", "complete_project_files_unavailable", missing_files=missing)
    files, adaptation = _adapt_static_slots(files, task, project_targets)

    project_root = root / "react_project"
    project_root.mkdir(parents=True, exist_ok=False)
    for relative, content in files.items():
        target = (project_root / relative).resolve()
        try:
            target.relative_to(project_root.resolve())
        except ValueError:
            return _receipt("failed", "react_preview_path_escape")
        _write_text(target, content)

    raw_package_name = str(project_graph.get("package_name") or "reweave-preview").lower()
    package_name = re.sub(r"[^a-z0-9_-]+", "-", raw_package_name).strip("-")
    package = {
        "name": package_name or "reweave-preview",
        "private": True,
        "scripts": {"dev": "vite", "build": "vite build"},
        "dependencies": dict(project_graph.get("package_dependencies") or {}),
        "devDependencies": dict(project_graph.get("package_dev_dependencies") or {}),
    }
    _write_text(project_root / "package.json", json.dumps(package, indent=2, ensure_ascii=False) + "\n")
    _write_text(
        project_root / "index.html",
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="UTF-8">'
        f"<title>{html.escape(task)}</title></head>"
        '<body><div id="root"></div>'
        f'<script type="module" src="/{html.escape(entrypoints[0], quote=True)}"></script>'
        "</body></html>\n",
    )
    result = _compile(project_root, entrypoints[0], list(project_graph.get("external_dependencies") or []))
    result["preview_output_write"] = True
    compile_status = result.get("compiler_status") or result.get("status")
    compile_reason = result.get("reason")
    result["adaptation"] = adaptation
    result["compile_status"] = compile_status
    result["compile_reason"] = compile_reason
    if compile_status == "passed" and adaptation.get("status") != "applied":
        result["status"] = "needs_review"
        result["reason"] = "safe_task_adaptation_unavailable"
    if result.get("status") == "passed":
        css = '<link rel="stylesheet" href="./app.css">' if (project_root / "dist" / "app.css").is_file() else ""
        _write_text(
            project_root / "dist" / "index.html",
            "<!doctype html>\n"
            '<html lang="en"><head><meta charset="UTF-8">'
            f"<title>{html.escape(task)}</title>{css}</head>"
            '<body><div id="root"></div><script type="module" src="./app.js"></script></body></html>\n',
        )
        result["runtime_entry"] = "react_project/dist/index.html"
    result["project_path"] = "react_project"
    result["materialized_files"] = ["index.html", "package.json", *sorted(files)]
    return result
