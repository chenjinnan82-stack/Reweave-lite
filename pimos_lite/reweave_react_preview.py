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


def _compile(project_root: Path, entrypoint: str, external_dependencies: list[str]) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    esbuild = repo_root / "node_modules" / "esbuild" / "lib" / "main.js"
    node = shutil.which("node")
    if not node or not esbuild.is_file():
        return _receipt("unavailable", "esbuild_not_installed")
    outfile = project_root / "dist" / "app.js"
    outfile.parent.mkdir(parents=True, exist_ok=True)
    external = sorted(
        {
            value
            for name in external_dependencies
            for value in (str(name), f"{name}/*")
            if name
        }
    )
    script = (
        "const esbuild=require(process.argv[1]);"
        "esbuild.buildSync({entryPoints:[process.argv[2]],outfile:process.argv[3],"
        "bundle:true,platform:'browser',format:'esm',logLevel:'silent',"
        "external:JSON.parse(process.argv[4])});"
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
        )
    return _receipt(
        "passed",
        "local_module_graph_compiled",
        compiled_files=compiled,
        compiler="esbuild",
        compile_scope="local_modules_external_dependencies_not_bundled",
        external_dependencies=external,
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
    files, missing = _complete_snippets(capsule_ids, target_paths)
    if missing:
        return _receipt("needs_review", "complete_project_files_unavailable", missing_files=missing)

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
    result["project_path"] = "react_project"
    result["materialized_files"] = ["index.html", "package.json", *sorted(files)]
    return result
