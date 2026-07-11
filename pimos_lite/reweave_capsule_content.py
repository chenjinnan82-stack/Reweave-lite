"""Reweave controlled capsule content enrichment — explicit, read-only snippet preview."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pimos_lite.reweave_capsule_warehouse import (
    GENERATE_ELIGIBLE_STATUSES,
    get_capsule,
    is_generate_eligible,
    list_warehouse_capsules,
    load_warehouse,
    save_warehouse,
)
from pimos_lite.reweave_reuse_suggestions import load_reuse_suggestions
from pimos_lite.reweave_capsule_verifier import load_verification
from pimos_lite.reweave_source_registry import get_source_box, state_dir
from pimos_lite.reweave_source_scanner import load_summary
from pimos_lite.reweave_project_graph import MAX_RUNTIME_FILES

CONTENT_SCHEMA_VERSION = 1
MAX_FILES = 5
MAX_BYTES_PER_FILE = 4096
MAX_TOTAL_BYTES = 16000
MAX_BEHAVIOR_FILE_BYTES = 65536
MAX_BEHAVIOR_TOTAL_BYTES = 131072
MAX_PROJECT_FILE_BYTES = 262144
MAX_PROJECT_TOTAL_BYTES = 524288
RUNTIME_DEPENDENCY_PATTERNS = (
    ("fetch", r"\bfetch\s*\("),
    ("xml_http_request", r"\bXMLHttpRequest\b"),
    ("web_socket", r"\bWebSocket\s*\("),
    ("event_source", r"\bEventSource\s*\("),
    ("send_beacon", r"\bnavigator\.sendBeacon\s*\("),
    ("dynamic_import", r"\bimport\s*\("),
    ("module_import", r"(?m)^\s*import\s+"),
    ("commonjs_require", r"\brequire\s*\("),
    ("python_service", r"(?i)\bpython(?:3)?\s+[\w./-]+\.py\b"),
)

ALLOWED_EXTENSIONS = frozenset(
    {
        ".html",
        ".css",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".vue",
        ".svelte",
        ".py",
        ".md",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".txt",
    }
)

BLOCKED_EXTENSIONS = frozenset(
    {
        ".env",
        ".pem",
        ".key",
        ".crt",
        ".sqlite",
        ".db",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".pdf",
    }
)

BLOCKED_DIR_NAMES = frozenset(
    {"node_modules", ".git", ".venv", "venv", "dist", "build", ".next", "target", "vendor"}
)

EXTENSION_HINTS: tuple[tuple[str, str], ...] = (
    ("css", ".css"),
    ("style", ".css"),
    ("html", ".html"),
    ("page", ".html"),
    ("javascript", ".js"),
    ("script", ".js"),
    ("jsx", ".jsx"),
    ("tsx", ".tsx"),
    ("typescript", ".ts"),
    ("json", ".json"),
    ("markdown", ".md"),
    ("docs", ".md"),
    ("copy", ".md"),
    ("python", ".py"),
)

SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(api[_-]?key|secret|token|password|access[_-]?key|secret[_-]?key)\s*[:=]\s*\S+"), r"\1: [REDACTED_SECRET]"),
    (re.compile(r"(?i)Bearer\s+[A-Za-z0-9\-._~+/]+=*"), "Bearer [REDACTED_SECRET]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{8,}\b"), "[REDACTED_SECRET]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "[REDACTED_SECRET]"),
    (re.compile(r"(?i)password\s*=\s*\S+"), "password=[REDACTED_SECRET]"),
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def content_dir() -> Path:
    return state_dir() / "capsule_contents"


def content_file_path(capsule_id: str) -> Path:
    safe = capsule_id.replace("/", "_").replace("\\", "_")
    return content_dir() / f"{safe}.content.json"


def content_rel_path(capsule_id: str) -> str:
    return f"capsule_contents/{capsule_id}.content.json"


def load_capsule_content(capsule_id: str) -> dict[str, Any] | None:
    path = content_file_path(capsule_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def save_capsule_content(capsule_id: str, record: dict[str, Any]) -> str:
    path = content_file_path(capsule_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return content_rel_path(capsule_id)


def redact_secrets(text: str) -> tuple[str, bool]:
    redacted = False
    result = text
    for pattern, repl in SECRET_PATTERNS:
        new_result, count = pattern.subn(repl, result)
        if count:
            redacted = True
            result = new_result
    return result, redacted


def _language_hint(ext: str) -> str:
    mapping = {
        ".html": "html",
        ".css": "css",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".vue": "vue",
        ".svelte": "svelte",
        ".py": "python",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".txt": "text",
    }
    return mapping.get(ext.lower(), "text")


def _normalize_rel_path(raw: str) -> str:
    return raw.strip().replace("\\", "/").lstrip("/")


def _path_has_blocked_dir(rel_path: str) -> bool:
    parts = [p for p in _normalize_rel_path(rel_path).split("/") if p]
    for part in parts:
        if part in BLOCKED_DIR_NAMES:
            return True
        if part.startswith("."):
            return True
    return False


def is_allowed_relative_path(rel_path: str) -> bool:
    rel = _normalize_rel_path(rel_path)
    if not rel or ".." in rel.split("/"):
        return False
    if _path_has_blocked_dir(rel):
        return False
    suffix = Path(rel).suffix.lower()
    if suffix in BLOCKED_EXTENSIONS:
        return False
    return suffix in ALLOWED_EXTENSIONS


def resolve_safe_path(source_root: Path, relative: str) -> Path | None:
    rel = _normalize_rel_path(relative)
    if not rel or not is_allowed_relative_path(rel):
        return None
    root = source_root.resolve()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


class _FrontendEntryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.styles: list[str] = []
        self.scripts: list[str] = []
        self.inline_scripts: list[str] = []
        self.assets: list[str] = []
        self.controls: list[dict[str, str]] = []
        self._button: dict[str, str] | None = None
        self._inline_script: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): str(value or "") for key, value in attrs}
        tag = tag.lower()
        if tag == "link" and "stylesheet" in values.get("rel", "").lower() and values.get("href"):
            self.styles.append(values["href"])
        elif tag == "script":
            if values.get("src"):
                self.scripts.append(values["src"])
            else:
                self._inline_script = []
        elif tag in {"img", "source", "video", "audio"} and values.get("src"):
            self.assets.append(values["src"])
        elif tag in {"input", "select", "textarea"}:
            self.controls.append(
                {
                    "kind": tag,
                    "id": values.get("id", ""),
                    "name": values.get("name", ""),
                    "type": values.get("type", ""),
                }
            )
        elif tag == "button":
            self._button = {"kind": "button", "id": values.get("id", ""), "name": values.get("name", ""), "text": ""}

    def handle_data(self, data: str) -> None:
        if self._inline_script is not None:
            self._inline_script.append(data)
        if self._button is not None:
            self._button["text"] = (self._button.get("text", "") + " " + data).strip()

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._inline_script is not None:
            self.inline_scripts.append("".join(self._inline_script).strip())
            self._inline_script = None
        if tag.lower() == "button" and self._button is not None:
            self.controls.append(self._button)
            self._button = None


def _frontend_reference(entry_path: str, raw: str) -> tuple[str, str]:
    value = (raw or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or value.startswith("//"):
        return "external", value
    if value.startswith(("#", "data:")):
        return "ignored", value
    if not parsed.path or parsed.path.startswith("/"):
        return "blocked", value
    relative = _normalize_rel_path((Path(entry_path).parent / parsed.path).as_posix())
    return ("local", relative) if is_allowed_relative_path(relative) else ("blocked", relative)


def _complete_text_file(
    source_root: Path,
    relative: str,
    *,
    max_bytes: int = MAX_BEHAVIOR_FILE_BYTES,
) -> tuple[dict[str, Any] | None, str]:
    path = resolve_safe_path(source_root, relative)
    if path is None:
        return None, f"unsafe_or_missing:{relative}"
    try:
        raw = path.read_bytes()
    except OSError:
        return None, f"read_failed:{relative}"
    if len(raw) > max_bytes:
        return None, f"file_too_large:{relative}"
    if b"\x00" in raw:
        return None, f"binary_content:{relative}"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, f"non_utf8:{relative}"
    cleaned, redacted = redact_secrets(text)
    if redacted:
        return None, f"secret_detected:{relative}"
    return {
        "relative_path": _normalize_rel_path(relative),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "content": cleaned,
    }, ""


def _behavior_interactions(parser: _FrontendEntryParser, script: str) -> dict[str, Any]:
    names: dict[str, dict[str, str]] = {}
    collections: dict[str, str] = {}
    for pattern in (
        r"(?:const|let|var)\s+(\w+)\s*=\s*document\.getElementById\(['\"]([^'\"]+)['\"]\)",
        r"(\w+)\s*:\s*document\.getElementById\(['\"]([^'\"]+)['\"]\)",
    ):
        names.update(
            {match.group(1): {"target_id": match.group(2)} for match in re.finditer(pattern, script)}
        )
    for pattern in (
        r"(?:const|let|var)\s+(\w+)\s*=\s*document\.querySelector\(['\"]([^'\"]+)['\"]\)",
        r"(\w+)\s*:\s*document\.querySelector\(['\"]([^'\"]+)['\"]\)",
    ):
        for match in re.finditer(pattern, script):
            names[match.group(1)] = {"target_selector": match.group(2)}
    for match in re.finditer(
        r"(?:const|let|var)\s+(\w+)\s*=\s*(?:Array\.from\(\s*)?document\.querySelectorAll\(['\"]([^'\"]+)['\"]\)",
        script,
    ):
        collections[match.group(1)] = match.group(2)

    events: list[dict[str, str]] = []
    for match in re.finditer(
        r"document\.getElementById\(['\"]([^'\"]+)['\"]\)\.addEventListener\(['\"]([^'\"]+)['\"]",
        script,
    ):
        events.append({"target_id": match.group(1), "event": match.group(2)})
    for match in re.finditer(
        r"(?:(?:this\.)?(?:elements|el)\.)?(\w+)\.addEventListener\(['\"]([^'\"]+)['\"]",
        script,
    ):
        target = names.get(match.group(1))
        event = {**target, "event": match.group(2)} if target else None
        if event and event not in events:
            events.append(event)
    for match in re.finditer(
        r"(\w+)\.forEach\(\s*\(?\s*(\w+)\s*\)?\s*=>\s*\2\.addEventListener\(['\"]([^'\"]+)['\"]",
        script,
    ):
        selector = collections.get(match.group(1))
        event = {"target_selector": selector, "event": match.group(3)} if selector else None
        if event and event not in events:
            events.append(event)

    referenced_ids = sorted(set(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", script)))
    action_ids = {item["target_id"] for item in events if item.get("target_id")}
    referenced_selectors = sorted(
        {str(item.get("target_selector")) for item in names.values() if item.get("target_selector")}
    )
    action_selectors = {item["target_selector"] for item in events if item.get("target_selector")}
    passive_updates = []
    if re.search(r"\bsetInterval\s*\(", script):
        passive_updates.append({"kind": "timer", "api": "setInterval"})
    return {
        "controls": parser.controls,
        "events": events,
        "passive_updates": passive_updates,
        "state_target_ids": [target for target in referenced_ids if target not in action_ids],
        "state_target_selectors": [target for target in referenced_selectors if target not in action_selectors],
    }


def build_frontend_behavior_contract(
    source_root: Path,
    summary: dict[str, Any],
    capsule: dict[str, Any],
) -> dict[str, Any] | None:
    """Capture one complete standalone frontend module during explicit enrichment."""
    if str(capsule.get("name") or "") not in {"Page Shell", "HTML Surface"}:
        return None
    entries = [str(item) for item in summary.get("entry_candidates", []) if Path(str(item)).suffix.lower() == ".html"]
    if not entries:
        return {"schema_version": 1, "status": "blocked", "blockers": ["missing_html_entry"]}
    entry_path = sorted(entries, key=lambda item: (Path(item).name != "index.html", len(Path(item).parts), item))[0]
    entry, error = _complete_text_file(source_root, entry_path)
    if entry is None:
        return {"schema_version": 1, "status": "blocked", "entry_path": entry_path, "blockers": [error]}

    parser = _FrontendEntryParser()
    try:
        parser.feed(str(entry["content"]))
    except Exception:
        return {"schema_version": 1, "status": "blocked", "entry_path": entry_path, "blockers": ["invalid_html"]}

    blockers: list[str] = []
    warnings: list[str] = []
    local_styles: list[str] = []
    local_scripts: list[str] = []
    for raw in parser.styles:
        kind, value = _frontend_reference(entry_path, raw)
        if kind == "local" and value not in local_styles:
            local_styles.append(value)
        elif kind == "external":
            warnings.append(f"external_style_omitted:{raw}")
        elif kind == "blocked":
            blockers.append(f"blocked_style:{raw}")
    for raw in parser.scripts:
        kind, value = _frontend_reference(entry_path, raw)
        if kind == "local" and value not in local_scripts:
            local_scripts.append(value)
        elif kind == "external":
            blockers.append(f"external_script:{raw}")
        elif kind == "blocked":
            blockers.append(f"blocked_script:{raw}")
    for raw in parser.assets:
        kind, _ = _frontend_reference(entry_path, raw)
        if kind not in {"ignored"}:
            blockers.append(f"asset_dependency:{raw}")
    if len(local_styles) > 1:
        blockers.append("multiple_stylesheets_not_supported")
    if len(local_scripts) + len(parser.inline_scripts) > 1:
        blockers.append("multiple_scripts_not_supported")
    if not local_scripts and not parser.inline_scripts:
        blockers.append("missing_local_script")

    style = script = None
    for relative, role in ((local_styles[0], "style") if local_styles else (None, None), (local_scripts[0], "script") if local_scripts else (None, None)):
        if relative is None:
            continue
        file_record, file_error = _complete_text_file(source_root, relative)
        if file_record is None:
            blockers.append(file_error)
        elif role == "style":
            style = file_record
        else:
            script = file_record

    if parser.inline_scripts:
        inline = parser.inline_scripts[0]
        raw = inline.encode("utf-8")
        cleaned, redacted = redact_secrets(inline)
        if len(raw) > MAX_BEHAVIOR_FILE_BYTES:
            blockers.append("inline_script_too_large")
        elif redacted:
            blockers.append("secret_detected:inline_script")
        else:
            script = {
                "relative_path": "<inline-script>",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "content": cleaned,
                "source_kind": "inline",
            }

    script_bytes = 0 if (script or {}).get("source_kind") == "inline" else int((script or {}).get("bytes", 0))
    total_bytes = int(entry["bytes"]) + int((style or {}).get("bytes", 0)) + script_bytes
    if total_bytes > MAX_BEHAVIOR_TOTAL_BYTES:
        blockers.append("module_too_large")
    script_text = str((script or {}).get("content") or "")
    interactions = _behavior_interactions(parser, script_text)
    if not interactions["events"] and not interactions["passive_updates"]:
        blockers.append("missing_behavior_events")
    if not interactions["state_target_ids"] and not interactions["state_target_selectors"]:
        blockers.append("missing_observable_state_target")
    blockers.extend(
        f"runtime_dependency:{name}"
        for name, pattern in RUNTIME_DEPENDENCY_PATTERNS
        if re.search(pattern, script_text)
    )
    if blockers:
        return {
            "schema_version": 1,
            "status": "blocked",
            "entry_path": entry_path,
            "dependencies": {"styles": local_styles, "scripts": local_scripts, "inline_script_count": len(parser.inline_scripts)},
            "blockers": sorted(set(blockers)),
            "warnings": warnings,
        }

    return {
        "schema_version": 1,
        "status": "closed",
        "mode": "whole_frontend_module",
        "interaction_mode": "user_event" if interactions["events"] else "passive_timer",
        "entry_path": entry_path,
        "files": {"entry": entry, "style": style, "script": script},
        "dependencies": {
            "styles": local_styles,
            "scripts": local_scripts,
            "inline_script_count": len(parser.inline_scripts),
            "external_styles_omitted": warnings,
        },
        "interactions": interactions,
        "materialized_files": ["index.html", "styles.css", "app.js"],
        "safety": {
            "source_project_write": False,
            "source_read_during_enrichment": True,
            "source_read_at_generate_time": False,
            "complete_files_only": True,
        },
    }


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in paths:
        rel = _normalize_rel_path(raw)
        if not rel or rel in seen:
            continue
        seen.add(rel)
        out.append(rel)
    return out


def _paths_from_lineage(lineage: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("relative_path", "path", "file", "source_path", "evidence_path"):
        val = lineage.get(key)
        if val:
            paths.append(str(val))
    evidence = lineage.get("evidence")
    if isinstance(evidence, list):
        paths.extend(str(x) for x in evidence if x)
    return paths


def _paths_from_snippet(snippet: dict[str, Any] | None) -> list[str]:
    if not snippet:
        return []
    evidence = snippet.get("evidence")
    if isinstance(evidence, list):
        return [str(x) for x in evidence if x]
    return []


def _paths_from_evidence_matched(matched: list[Any], entry_candidates: list[Any]) -> list[str]:
    paths: list[str] = []
    entries = [_normalize_rel_path(str(e)) for e in entry_candidates if e]
    for item in matched:
        if not isinstance(item, str):
            continue
        if item.startswith("entry:"):
            name = item.split(":", 1)[1].strip()
            for ec in entries:
                if Path(ec).name.lower() == name.lower() or ec.lower() == name.lower():
                    paths.append(ec)
        elif item.startswith("extension:"):
            ext = item.split(":", 1)[1].strip()
            if not ext.startswith("."):
                ext = f".{ext}"
            for ec in entries:
                if ec.lower().endswith(ext.lower()):
                    paths.append(ec)
                    break
    return paths


def _paths_from_verification(source_id: str, suggestion_id: str, summary: dict[str, Any]) -> list[str]:
    verification = load_verification(source_id)
    if not verification:
        return []
    results = verification.get("results") if isinstance(verification.get("results"), list) else []
    entry_candidates = summary.get("entry_candidates") if isinstance(summary.get("entry_candidates"), list) else []
    for item in results:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") != suggestion_id:
            continue
        matched = item.get("evidence_matched") if isinstance(item.get("evidence_matched"), list) else []
        return _paths_from_evidence_matched(matched, entry_candidates)
    return []


def _paths_from_reuse_assets(source_id: str, suggestion_id: str) -> list[str]:
    record = load_reuse_suggestions(source_id)
    if not record:
        return []
    paths: list[str] = []
    assets = record.get("assets") if isinstance(record.get("assets"), list) else []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("id") or "")
        if suggestion_id and f"luna_asset_{asset_id.replace(':', '_')}" != suggestion_id:
            continue
        for key in ("relative_path", "path", "file"):
            val = asset.get(key)
            if val:
                paths.append(str(val))
    suggestions = record.get("mapped_capsuleSuggestions")
    if isinstance(suggestions, list):
        for sug in suggestions:
            if not isinstance(sug, dict):
                continue
            if str(sug.get("id") or "") != suggestion_id:
                continue
            for key in ("relative_path", "path", "file"):
                val = sug.get(key)
                if val:
                    paths.append(str(val))
    return paths


def _extension_hints_from_capsule(capsule: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    for key in ("type", "name", "role"):
        val = capsule.get(key)
        if val:
            parts.append(str(val).lower())
    tags = capsule.get("tags") if isinstance(capsule.get("tags"), list) else []
    parts.extend(str(tag).lower() for tag in tags if tag)
    haystack = " ".join(parts)
    hints: list[str] = []
    for token, ext in EXTENSION_HINTS:
        if token in haystack and ext not in hints:
            hints.append(ext)
    return hints


def _paths_from_summary_extension_samples(capsule: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    samples = summary.get("sample_paths_by_extension")
    if not isinstance(samples, dict):
        return []
    paths: list[str] = []
    for ext in _extension_hints_from_capsule(capsule):
        raw_paths = samples.get(ext)
        if isinstance(raw_paths, list):
            paths.extend(str(p) for p in raw_paths if p)
    return paths


def _paths_from_project_graph(capsule: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    tags = {str(tag).lower() for tag in capsule.get("tags", []) if tag}
    graph = summary.get("project_graph") if isinstance(summary.get("project_graph"), dict) else {}
    if "react" not in tags or graph.get("project_kind") != "react_vite":
        return []
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    return [
        str(node.get("path"))
        for node in nodes
        if isinstance(node, dict)
        and node.get("path")
        and node.get("kind") in {"entry", "component", "style", "module"}
    ][:MAX_FILES]


def collect_candidate_paths(capsule: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    """Collect candidate relative paths without scanning the full source tree."""
    source_id = str(capsule.get("source_id") or "")
    suggestion_id = ""
    lineage = capsule.get("lineage") if isinstance(capsule.get("lineage"), dict) else {}
    if lineage:
        suggestion_id = str(lineage.get("suggestion_id") or "")
        paths = _paths_from_lineage(lineage)
    else:
        paths = []

    snippet = capsule.get("snippet") if isinstance(capsule.get("snippet"), dict) else None
    paths.extend(_paths_from_snippet(snippet))

    if source_id and suggestion_id:
        paths.extend(_paths_from_verification(source_id, suggestion_id, summary))
        paths.extend(_paths_from_reuse_assets(source_id, suggestion_id))

    paths = _dedupe_paths(paths)

    if not paths:
        paths = _dedupe_paths(_paths_from_project_graph(capsule, summary))

    if not paths:
        paths = _dedupe_paths(_paths_from_summary_extension_samples(capsule, summary))

    if not paths:
        entry_candidates = summary.get("entry_candidates") if isinstance(summary.get("entry_candidates"), list) else []
        paths = _dedupe_paths([str(e) for e in entry_candidates if e])

    return [p for p in paths if is_allowed_relative_path(p)][:MAX_FILES]


def _complete_react_project_files(
    source_root: Path,
    capsule: dict[str, Any],
    summary: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], bool]:
    tags = {str(tag).lower() for tag in capsule.get("tags", []) if tag}
    graph = summary.get("project_graph") if isinstance(summary.get("project_graph"), dict) else {}
    paths = [str(path) for path in graph.get("runtime_files", []) if path]
    if not {"project", "react"}.issubset(tags) or graph.get("project_kind") != "react_vite" or not paths:
        return [], [], False
    files: list[dict[str, Any]] = []
    warnings: list[str] = []
    total_bytes = 0
    for relative in paths[:MAX_RUNTIME_FILES]:
        item, warning = _complete_text_file(source_root, relative, max_bytes=MAX_PROJECT_FILE_BYTES)
        if item is None:
            warnings.append(warning)
            continue
        if total_bytes + int(item["bytes"]) > MAX_PROJECT_TOTAL_BYTES:
            warnings.append("project_total_bytes_exceeded")
            break
        files.append(item)
        total_bytes += int(item["bytes"])
    complete = len(paths) <= MAX_RUNTIME_FILES and len(files) == len(paths)
    return files, warnings, complete


def _read_text_snippet(file_path: Path, max_bytes: int) -> tuple[str, int, bool]:
    raw = file_path.read_bytes()[: max_bytes + 1]
    if b"\x00" in raw[:max_bytes]:
        raise ValueError("binary_content")
    truncated = len(raw) > max_bytes
    chunk = raw[:max_bytes]
    text = chunk.decode("utf-8", errors="replace")
    return text, len(chunk), truncated


def _apply_enrichment_metadata(
    capsule_id: str,
    *,
    success: bool,
    snippet_count: int = 0,
    error: str = "",
) -> None:
    now = _utc_now_iso()
    data = load_warehouse()
    for cap in data.get("capsules", []):
        if not isinstance(cap, dict) or str(cap.get("id") or "") != capsule_id:
            continue
        if success:
            cap["content_mode"] = "controlled_snippet_preview"
            cap["content_risk"] = "controlled_snippet_preview"
            cap["content_enrichment"] = {
                "status": "enriched",
                "content_path": content_rel_path(capsule_id),
                "snippet_count": snippet_count,
                "updated_at": now,
            }
        else:
            cap["content_enrichment"] = {
                "status": "failed",
                "error": (error or "enrichment_failed")[:200],
                "updated_at": now,
            }
        cap["updated_at"] = now
        break
    save_warehouse(data)


def enrich_capsule_content(capsule_id: str) -> dict[str, Any]:
    """Explicit user-triggered content enrichment — read-only whitelist snippets."""
    capsule_id = (capsule_id or "").strip()
    if not capsule_id:
        return {"ok": False, "error": "missing_capsule_id"}

    capsule = get_capsule(capsule_id)
    if not capsule:
        return {"ok": False, "error": "capsule_not_found", "capsule_id": capsule_id}

    status = str(capsule.get("status") or "active")
    if status not in GENERATE_ELIGIBLE_STATUSES:
        return {"ok": False, "error": "capsule_not_active", "capsule_id": capsule_id, "status": status}

    source_id = str(capsule.get("source_id") or "")
    if not source_id:
        source_box = capsule.get("source_box") if isinstance(capsule.get("source_box"), dict) else {}
        source_id = str(source_box.get("source_id") or "")

    if not source_id:
        _apply_enrichment_metadata(capsule_id, success=False, error="missing_source_id")
        return {"ok": False, "error": "missing_source_id", "capsule_id": capsule_id}

    box = get_source_box(source_id)
    if not box:
        _apply_enrichment_metadata(capsule_id, success=False, error="source_not_found")
        return {"ok": False, "error": "source_not_found", "capsule_id": capsule_id, "source_id": source_id}

    source_path = Path(str(box.get("path") or ""))
    if not source_path.is_dir():
        _apply_enrichment_metadata(capsule_id, success=False, error="source_path_not_found")
        return {"ok": False, "error": "source_path_not_found", "capsule_id": capsule_id, "source_id": source_id}

    summary = load_summary(source_id) or {}
    candidates = collect_candidate_paths(capsule, summary)
    warnings: list[str] = []
    snippets: list[dict[str, Any]] = []
    total_bytes = 0
    now = _utc_now_iso()

    for rel in candidates:
        if len(snippets) >= MAX_FILES:
            warnings.append("max_files_reached")
            break
        if total_bytes >= MAX_TOTAL_BYTES:
            warnings.append("max_total_bytes_reached")
            break

        safe = resolve_safe_path(source_path, rel)
        if not safe:
            warnings.append(f"skipped_unsafe_path:{rel}")
            continue

        remaining = MAX_TOTAL_BYTES - total_bytes
        per_file_limit = min(MAX_BYTES_PER_FILE, remaining)
        if per_file_limit <= 0:
            warnings.append("max_total_bytes_reached")
            break

        try:
            preview, bytes_read, truncated = _read_text_snippet(safe, per_file_limit)
        except ValueError:
            warnings.append(f"skipped_binary:{rel}")
            continue
        except OSError as exc:
            warnings.append(f"read_failed:{rel}:{str(exc)[:40]}")
            continue

        preview, redacted = redact_secrets(preview)
        total_bytes += bytes_read
        snippets.append(
            {
                "relative_path": _normalize_rel_path(rel),
                "language_hint": _language_hint(safe.suffix),
                "bytes_read": bytes_read,
                "truncated": truncated,
                "redacted": redacted,
                "preview": preview,
            }
        )

    if not snippets:
        _apply_enrichment_metadata(capsule_id, success=False, error="no_readable_snippets")
        return {
            "ok": False,
            "error": "no_readable_snippets",
            "capsule_id": capsule_id,
            "warnings": warnings,
        }

    record = {
        "schema_version": CONTENT_SCHEMA_VERSION,
        "capsule_id": capsule_id,
        "source_id": source_id,
        "created_at": now,
        "mode": "controlled_snippet_preview",
        "limits": {
            "max_files": MAX_FILES,
            "max_bytes_per_file": MAX_BYTES_PER_FILE,
            "max_total_bytes": MAX_TOTAL_BYTES,
            "secret_redaction": True,
        },
        "safety": {
            "source_folder_written": False,
            "llm_called": False,
            "dispatch_called": False,
            "binary_read": False,
        },
        "snippets": snippets,
        "warnings": warnings,
    }
    project_files, project_warnings, project_files_complete = _complete_react_project_files(
        source_path,
        capsule,
        summary,
    )
    if project_files:
        record["project_files"] = project_files
        record["project_files_complete"] = project_files_complete
        record["warnings"].extend(project_warnings)
    behavior_contract = build_frontend_behavior_contract(source_path, summary, capsule)
    if behavior_contract is not None:
        record["behavior_contract"] = behavior_contract
    rel_path = save_capsule_content(capsule_id, record)
    _apply_enrichment_metadata(capsule_id, success=True, snippet_count=len(snippets))

    updated = get_capsule(capsule_id)
    return {
        "ok": True,
        "capsule_id": capsule_id,
        "source_id": source_id,
        "content_path": rel_path,
        "snippet_count": len(snippets),
        "content": record,
        "capsule": updated,
        "capsules": list_warehouse_capsules(include_inactive=True),
        "warnings": warnings,
    }


def get_capsule_content(capsule_id: str) -> dict[str, Any]:
    """Read enriched capsule content from app state only — never touches source folder."""
    capsule_id = (capsule_id or "").strip()
    if not capsule_id:
        return {"ok": False, "error": "missing_capsule_id"}

    capsule = get_capsule(capsule_id)
    if not capsule:
        return {"ok": False, "error": "capsule_not_found", "capsule_id": capsule_id}

    enrichment = capsule.get("content_enrichment") if isinstance(capsule.get("content_enrichment"), dict) else None
    if not enrichment or str(enrichment.get("status") or "") != "enriched":
        return {"ok": False, "error": "no_content_enrichment", "capsule_id": capsule_id}

    record = load_capsule_content(capsule_id)
    if not record:
        return {"ok": False, "error": "content_file_missing", "capsule_id": capsule_id}

    snippets = record.get("snippets") if isinstance(record.get("snippets"), list) else []
    return {
        "ok": True,
        "capsule_id": capsule_id,
        "content_path": str(enrichment.get("content_path") or content_rel_path(capsule_id)),
        "snippet_count": len(snippets),
        "content": {
            "mode": record.get("mode"),
            "limits": record.get("limits") if isinstance(record.get("limits"), dict) else {},
            "safety": record.get("safety") if isinstance(record.get("safety"), dict) else {},
            "snippets": snippets,
            "warnings": list(record.get("warnings") or []),
        },
    }
