"""Read-only React/Vite project graph inspection."""

from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path
from typing import Any


SOURCE_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".css")
MAX_GRAPH_FILES = 200
MAX_SOURCE_BYTES = 262144
_IMPORT_RE = re.compile(
    r"(?:import|export)\s+(?:[^'\"]*?\s+from\s+)?['\"]([^'\"]+)['\"]"
    r"|require\(\s*['\"]([^'\"]+)['\"]\s*\)",
    flags=re.MULTILINE,
)


def _package_name(specifier: str) -> str:
    parts = specifier.split("/")
    return "/".join(parts[:2]) if specifier.startswith("@") else parts[0]


def _source_files(root: Path) -> list[Path]:
    src = root / "src"
    if not src.is_dir() or src.is_symlink():
        return []
    files: list[Path] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > 8 or len(files) >= MAX_GRAPH_FILES:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            return
        for entry in entries:
            if len(files) >= MAX_GRAPH_FILES or entry.is_symlink():
                continue
            if entry.is_dir():
                walk(entry, depth + 1)
            elif entry.is_file() and entry.suffix.lower() in SOURCE_EXTENSIONS:
                files.append(entry)

    walk(src, 0)
    return files


def _read_source(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > MAX_SOURCE_BYTES or b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _resolve_local_import(source_path: str, specifier: str, known: set[str]) -> str | None:
    base = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), specifier))
    if base == ".." or base.startswith("../"):
        return None
    candidates = [base]
    if not Path(base).suffix:
        candidates.extend(base + suffix for suffix in SOURCE_EXTENSIONS)
        candidates.extend(posixpath.join(base, "index" + suffix) for suffix in SOURCE_EXTENSIONS)
    return next((candidate for candidate in candidates if candidate in known), None)


def inspect_react_vite_project(root: Path) -> dict[str, Any]:
    """Return a bounded dependency graph without writing to the source project."""
    resolved = root.expanduser().resolve()
    package_path = resolved / "package.json"
    base = {
        "schema_version": 1,
        "status": "not_applicable",
        "project_kind": "unknown",
        "source_project_write": False,
        "nodes": [],
        "edges": [],
        "entrypoints": [],
        "external_dependencies": [],
        "unresolved_imports": [],
        "warnings": [],
    }
    if not package_path.is_file() or package_path.is_symlink():
        return base
    try:
        if package_path.stat().st_size > MAX_SOURCE_BYTES:
            return {**base, "status": "unavailable", "warnings": ["package_manifest_too_large"]}
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {**base, "status": "unavailable", "warnings": ["package_manifest_invalid"]}
    if not isinstance(package, dict):
        return {**base, "status": "unavailable", "warnings": ["package_manifest_invalid"]}

    dependencies: dict[str, Any] = {}
    for key in ("dependencies", "devDependencies"):
        value = package.get(key)
        if isinstance(value, dict):
            dependencies.update(value)
    if "react" not in dependencies or "vite" not in dependencies:
        kind = "react" if "react" in dependencies else "vite" if "vite" in dependencies else "unknown"
        return {**base, "project_kind": kind}

    files = _source_files(resolved)
    known = {path.relative_to(resolved).as_posix() for path in files}
    entrypoints = [
        path
        for path in (
            "src/main.tsx",
            "src/main.jsx",
            "src/main.ts",
            "src/main.js",
            "src/index.tsx",
            "src/index.jsx",
        )
        if path in known
    ]
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    external: set[str] = set()
    unresolved: list[dict[str, str]] = []

    for path in files:
        relative = path.relative_to(resolved).as_posix()
        text = _read_source(path)
        if text is None:
            nodes.append({"path": relative, "kind": "unreadable", "imports": []})
            continue
        specifiers = [match.group(1) or match.group(2) for match in _IMPORT_RE.finditer(text)]
        imports: list[str] = []
        for specifier in specifiers:
            if specifier.startswith("."):
                target = _resolve_local_import(relative, specifier, known)
                if target:
                    imports.append(target)
                    edges.append({"from": relative, "to": target})
                else:
                    unresolved.append({"from": relative, "specifier": specifier})
            else:
                external.add(_package_name(specifier))
        if relative in entrypoints:
            kind = "entry"
        elif path.suffix.lower() == ".css":
            kind = "style"
        elif path.suffix.lower() in {".jsx", ".tsx"}:
            kind = "component"
        else:
            kind = "module"
        nodes.append({"path": relative, "kind": kind, "imports": imports})

    warnings = []
    if not entrypoints:
        warnings.append("entrypoint_not_found")
    if len(files) >= MAX_GRAPH_FILES:
        warnings.append("max_graph_files_reached")
    return {
        **base,
        "status": "analyzed" if entrypoints else "partial",
        "project_kind": "react_vite",
        "package_name": str(package.get("name") or ""),
        "entrypoints": entrypoints,
        "nodes": nodes,
        "edges": edges,
        "external_dependencies": sorted(external),
        "unresolved_imports": unresolved,
        "warnings": warnings,
        "counts": {"nodes": len(nodes), "edges": len(edges), "unresolved": len(unresolved)},
    }
