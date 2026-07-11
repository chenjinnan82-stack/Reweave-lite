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
RUNTIME_DEPENDENCY_ALLOWLIST = frozenset({"lucide-react", "react", "react-dom"})


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


def _complete_snippets(
    capsule_ids: list[str],
    targets: list[str],
    *,
    source_id: str = "",
) -> tuple[dict[str, str], list[str]]:
    wanted = set(targets)
    files: dict[str, str] = {}
    for capsule_id in capsule_ids:
        record = load_capsule_content(capsule_id)
        if source_id and isinstance(record, dict) and str(record.get("source_id") or "") != source_id:
            continue
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
        if isinstance(item, dict) and item.get("kind") in {"component", "entry"}
    ]
    slots: list[dict[str, Any]] = []
    for relative in component_paths:
        source = files.get(relative)
        if source is None:
            continue
        file_slots: list[dict[str, Any]] = []
        for tag, kind in (("h1", "heading"), ("h2", "heading"), ("p", "description"), ("button", "action")):
            pattern = re.compile(
                rf"(<{tag}\b[^>]*>)([^<>{{}}\r\n]{{1,160}})(</{tag}>)",
                flags=re.IGNORECASE,
            )
            file_slots.extend(
                {
                    "slot_id": f"{relative}:{tag}:{occurrence}",
                    "file": relative,
                    "tag": tag,
                    "kind": kind,
                    "mode": "static_text",
                    "_start": match.start(2),
                    "_end": match.end(2),
                    "_slot_priority": 1,
                }
                for occurrence, match in enumerate(pattern.finditer(source))
            )
        dynamic_heading = re.compile(
            r"(<(?P<tag>h1|h2)\b[^>]*>)(\{\s*localize\([^{}]{1,200}\)\s*\})(</(?P=tag)>)",
            flags=re.IGNORECASE,
        )
        file_slots.extend(
            {
                "slot_id": f"{relative}:{match.group('tag').lower()}-localized:{occurrence}",
                "file": relative,
                "tag": match.group("tag").lower(),
                "kind": "heading",
                "mode": "localized_heading",
                "_start": match.start(3),
                "_end": match.end(3),
                "_slot_priority": 1,
            }
            for occurrence, match in enumerate(dynamic_heading.finditer(source))
        )
        nested_heading = re.compile(
            r"<(?P<tag>h1|h2)\b[^>]*>(?P<body>.{1,600}?)</(?P=tag)>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        nested_text = re.compile(
            r"<(?P<child>span|strong)\b[^>]*>(?P<text>[^<>{}\r\n]{1,160})</(?P=child)>",
            flags=re.IGNORECASE,
        )
        nested_occurrence = 0
        for heading in nested_heading.finditer(source):
            for match in nested_text.finditer(heading.group("body")):
                file_slots.append(
                    {
                        "slot_id": f"{relative}:{heading.group('tag').lower()}-nested:{nested_occurrence}",
                        "file": relative,
                        "tag": heading.group("tag").lower(),
                        "kind": "heading",
                        "mode": "route_nested_heading",
                        "_start": heading.start("body") + match.start("text"),
                        "_end": heading.start("body") + match.end("text"),
                        "_slot_priority": 0,
                    }
                )
                nested_occurrence += 1
        route_header = re.compile(
            r"<header\b[^>]*>(?P<body>.{1,6000}?)</header>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        route_subtitle = re.compile(
            r"(<strong\b[^>]*>)(\{\s*[A-Za-z_$][\w$]*\s*\})(</strong>)",
            flags=re.IGNORECASE,
        )
        route_occurrence = 0
        for header in route_header.finditer(source):
            for match in route_subtitle.finditer(header.group("body")):
                file_slots.append(
                    {
                        "slot_id": f"{relative}:route-subtitle:{route_occurrence}",
                        "file": relative,
                        "tag": "strong",
                        "kind": "heading",
                        "mode": "route_semantic_subtitle",
                        "_start": header.start("body") + match.start(2),
                        "_end": header.start("body") + match.end(2),
                        "_slot_priority": 0,
                    }
                )
                route_occurrence += 1
        semantic_container = re.compile(
            r"<(?P<container>header)\b[^>]*className\s*=\s*['\"][^'\"]*"
            r"(?P<role>brand|title|caption|hero)[^'\"]*['\"][^>]*>"
            r"(?P<body>.{0,800}?)</(?P=container)>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        semantic_text = re.compile(
            r"(<(?P<tag>strong|span)\b[^>]*>)(?P<text>[^<>{}\r\n]{1,160})(</(?P=tag)>)",
            flags=re.IGNORECASE,
        )
        semantic_occurrence = 0
        for container in semantic_container.finditer(source):
            for match in semantic_text.finditer(container.group("body")):
                tag = match.group("tag").lower()
                role = container.group("role").lower()
                start = container.start("body") + match.start("text")
                end = container.start("body") + match.end("text")
                file_slots.append(
                    {
                        "slot_id": f"{relative}:semantic-{tag}:{semantic_occurrence}",
                        "file": relative,
                        "tag": tag,
                        "kind": "heading",
                        "mode": "semantic_container_text",
                        "_start": start,
                        "_end": end,
                        "_slot_priority": (0 if tag == "strong" else 1) if role != "brand" else 3,
                    }
                )
                semantic_occurrence += 1
        slots.extend(sorted(file_slots, key=lambda slot: int(slot["_start"])))
    return slots


def _replace_static_slot(source: str, slot: dict[str, Any], replacement: str) -> str:
    start = int(slot["_start"])
    end = int(slot["_end"])
    return source[:start] + replacement + source[end:]


def _adapt_source_declared_route(
    files: dict[str, str],
    task: str,
    project_targets: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, Any] | None]:
    # ponytail: source-declared pathname routes only; use a parser if routing syntax grows.
    task_words = {
        word
        for word in re.findall(r"[a-z0-9]+", task.lower())
        if len(word) > 2 and word not in {"build", "from", "project", "this", "tool", "tools", "with"}
    }
    candidates: list[tuple[int, str, str]] = []
    component_paths = {
        str(item.get("path") or "")
        for item in project_targets
        if isinstance(item, dict) and item.get("kind") in {"component", "entry"}
    }
    for relative in sorted(component_paths):
        source = files.get(relative, "")
        for match in re.finditer(r"const\s+(?P<name>[A-Z][A-Z0-9_]*_PATH)\s*=\s*['\"](?P<route>/[^'\"]+)['\"]", source):
            name = match.group("name")
            if not re.search(r"\bpath\s*===\s*" + re.escape(name) + r"\b", source):
                continue
            route = match.group("route")
            score = len(task_words & set(re.findall(r"[a-z0-9]+", route.lower())))
            if score >= 2:
                candidates.append((score, relative, route))
    if not candidates:
        return dict(files), None
    _, relative, route = max(candidates, key=lambda item: (item[0], item[2]))
    state_pattern = re.compile(
        r"(?P<prefix>useState(?:<[^>]+>)?\()\s*window\.location\.pathname\s*\)"
    )
    updated = dict(files)
    updated[relative], count = state_pattern.subn(
        lambda match: match.group("prefix") + json.dumps(route) + ")",
        updated[relative],
        count=1,
    )
    if count != 1:
        return dict(files), None
    return updated, {
        "status": "applied",
        "mode": "source_declared_initial_route",
        "source_path": relative,
        "route": route,
        "source_project_write": False,
    }


def _react_runtime_contract(
    files: dict[str, str],
    project_targets: list[dict[str, Any]],
) -> dict[str, Any]:
    # ponytail: recognize only source-backed patterns proven by real projects; use an AST if this ceiling hurts.
    component_paths = {
        str(item.get("path") or "")
        for item in project_targets
        if isinstance(item, dict) and item.get("kind") in {"component", "entry"}
    }
    navigation_contract: dict[str, Any] | None = None
    for relative in sorted(component_paths):
        source = files.get(relative, "")
        for match in re.finditer(r"<nav\b[^>]*>(.{1,6000}?)</nav>", source, flags=re.IGNORECASE | re.DOTALL):
            body = match.group(1)
            if (
                "<button" not in body
                or "onClick" not in body
                or not re.search(r"className\s*=\s*\{.{0,240}?\bactive\b", body, re.DOTALL)
            ):
                continue
            navigation_contract = {
                "status": "closed",
                "mode": "declared_navigation_state",
                "source_path": relative,
                "control_selector": "nav button",
                "event": "click",
                "state_target": "control.className",
                "expected_change": True,
                "source_project_write": False,
            }
            break
        if navigation_contract is not None:
            break
    state_setters: set[str] = set()
    for source in files.values():
        state_setters.update(
            match.group(1)
            for match in re.finditer(
                r"const\s*\[\s*\w+\s*,\s*(set\w+)\s*\]\s*=\s*useState(?:<[^>]+>)?\(true\)",
                source,
            )
        )
    callback_props: list[tuple[str, str]] = []
    for parent_path, parent_source in sorted(files.items()):
        for callback in re.finditer(
            r"(?P<prop>on[A-Z]\w*)\s*=\s*\{\s*\(\)\s*=>\s*(?P<setter>set\w+)\(false\)\s*\}",
            parent_source,
        ):
            if callback.group("setter") in state_setters:
                callback_props.append((parent_path, callback.group("prop")))
        for handler in re.finditer(r"const\s+(?P<name>\w+)\s*=\s*\(\)\s*=>\s*\{", parent_source):
            body = parent_source[handler.end() : handler.end() + 600]
            if not any(f"{setter}(false)" in body for setter in state_setters):
                continue
            for wiring in re.finditer(
                r"(?P<prop>on[A-Z]\w*)\s*=\s*\{\s*" + re.escape(handler.group("name")) + r"\s*\}",
                parent_source,
            ):
                callback_props.append((parent_path, wiring.group("prop")))
    for parent_path, prop in callback_props:
        button_pattern = re.compile(
            r"<button\b[^>]*onClick\s*=\s*\{\s*"
            + re.escape(prop)
            + r"\s*\}[^>]*>(?P<body>.{1,400}?)</button>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        for child_path, child_source in sorted(files.items()):
            button = button_pattern.search(child_source)
            if not button or "{" in button.group("body"):
                continue
            control_text = " ".join(re.sub(r"<[^>]+>", " ", button.group("body")).split())
            if not control_text:
                continue
            return {
                "status": "closed",
                "mode": "declared_control_disappears",
                "source_path": child_path,
                "wiring_path": parent_path,
                "control_text": html.unescape(control_text),
                "event": "click",
                "state_target": "control.presence",
                "expected_change": True,
                "source_project_write": False,
            }
    for child_path, child_source in sorted(files.items()):
        component = Path(child_path).stem
        group = re.search(
            r"<(?P<tag>div|section)\b[^>]*aria-label\s*=\s*['\"](?P<label>[^'\"\[\]]{1,80})['\"][^>]*>"
            r"(?P<body>.{1,2400}?)</(?P=tag)>",
            child_source,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not group or not re.search(r"onClick\s*=\s*\{\s*\(\)\s*=>\s*on\w+\(", group.group("body")):
            continue
        for parent_path, parent_source in sorted(files.items()):
            if f"<{component}" not in parent_source or "<textarea" not in parent_source:
                continue
            control_selector = f'[aria-label="{group.group("label")}"] button'
            return {
                "status": "closed",
                "mode": "declared_group_to_textbox",
                "source_path": child_path,
                "wiring_path": parent_path,
                "control_selector": control_selector,
                "event": "click",
                "state_target": "textarea.value",
                "state_selector": "textarea",
                "expected_change": True,
                "source_project_write": False,
            }
    if navigation_contract is not None:
        return navigation_contract
    return {
        "status": "unavailable",
        "reason": "declared_react_interaction_not_found",
        "source_project_write": False,
    }


def _adapt_static_slots(
    files: dict[str, str],
    task: str,
    project_targets: list[dict[str, Any]],
    *,
    preferred_route: str = "",
) -> tuple[dict[str, str], dict[str, Any]]:
    slots = _static_text_slots(files, project_targets)
    headings = [
        slot
        for slot in slots
        if slot["kind"] == "heading"
        and (
            preferred_route
            or slot.get("mode") not in {"route_nested_heading", "route_semantic_subtitle"}
        )
    ]
    route_words = set(re.findall(r"[a-z0-9]+", preferred_route.lower())) - {"tool", "tools"}

    def heading_priority(slot: dict[str, Any]) -> tuple[int, int, int, int, int, int, str]:
        path = str(slot.get("file") or "").lower()
        stem = Path(str(slot.get("file") or "")).stem.lower()
        primary = any(word in stem for word in ("home", "opening", "landing", "hero"))
        route_match = len(route_words & set(re.findall(r"[a-z0-9]+", path)))
        return (
            0 if route_words and route_match >= 2 else 1,
            0 if stem == "app" else 1 if primary else 2,
            0 if slot.get("mode") == "route_semantic_subtitle" else 1,
            (0 if slot.get("tag") == "h1" else 1) if route_words else 0,
            int(slot.get("_slot_priority") or 0),
            int(slot.get("_start") or 0),
            str(slot.get("file") or ""),
        )

    selected = min(headings, key=heading_priority) if headings else None
    public_slots = [
        {key: value for key, value in slot.items() if not key.startswith("_")}
        for slot in slots
    ]
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
        "external:JSON.parse(process.argv[4]),nodePaths:[process.argv[5]],"
        "define:{'import.meta.env':'{}'}});"
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
    unsupported_style_directives = sorted(
        directive
        for directive in ("@apply", "@tailwind")
        if any(
            directive in path.read_text(encoding="utf-8", errors="replace")
            for path in outfile.parent.glob("*.css")
        )
    )
    if unsupported_style_directives:
        return _receipt(
            "needs_review",
            "unsupported_style_pipeline",
            preview_output_write=True,
            compiled_files=compiled,
            compiler="esbuild",
            compiler_status="passed",
            unsupported_style_directives=unsupported_style_directives,
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
    files, missing = _complete_snippets(
        capsule_ids,
        target_paths,
        source_id=str(project_graph.get("source_id") or ""),
    )
    if missing:
        return _receipt("needs_review", "complete_project_files_unavailable", missing_files=missing)
    files, route_adaptation = _adapt_source_declared_route(files, task, project_targets)
    files, adaptation = _adapt_static_slots(
        files,
        task,
        project_targets,
        preferred_route=str((route_adaptation or {}).get("route") or ""),
    )
    if route_adaptation is not None:
        adaptation["route"] = route_adaptation
        adaptation["changes"].insert(
            0,
            {
                "slot_id": f"{route_adaptation['source_path']}:initial-route",
                "reason": "task_route",
                "value": route_adaptation["route"],
            },
        )

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
    result["runtime_contract"] = _react_runtime_contract(files, project_targets)
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
