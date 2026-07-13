"""Quality gate helpers for Reweave preview packs."""

from __future__ import annotations

import hashlib
import html
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from pimos_lite.reweave_project_renderer import LOCAL_RUNTIME_CSP
from pimos_lite.reweave_task_intent import MAX_TASK_LEN


_CSS_UNSAFE_RESOURCE = re.compile(
    r"(?is)(?:url\s*\(\s*['\"]?\s*(?!data:)(?:[a-z][a-z0-9+.-]*:|/|(?:\.\./)+|%2e)|@import\b)"
)
_SCRIPT_NETWORK_API = re.compile(
    r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\b|navigator\.sendBeacon|"
    r"window\.open\s*\(|location\.(?:assign|replace)\s*\("
)


class _ProductResourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.styles: list[str] = []
        self.scripts: list[str] = []
        self.remote: list[str] = []
        self.content_security_policies: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): str(value or "") for key, value in attrs}
        tag = tag.lower()
        if tag == "link" and "stylesheet" in values.get("rel", "").lower():
            self.styles.append(values.get("href", ""))
        if tag == "script" and values.get("src"):
            self.scripts.append(values["src"])
        for key in ("src", "href", "action", "poster", "srcset", "data"):
            value = values.get(key, "").strip()
            parsed = urlsplit(value)
            path_parts = Path(unquote(parsed.path)).parts
            if (
                value.startswith("/")
                or ".." in path_parts
                or (parsed.scheme and parsed.scheme.lower() != "data")
            ):
                self.remote.append(value)
        if tag == "meta" and values.get("http-equiv", "").lower() == "refresh":
            content = values.get("content", "")
            if re.search(r"(?i)url\s*=\s*(?:https?:)?//", content):
                self.remote.append(content)
        if tag == "meta" and values.get("http-equiv", "").strip().lower() == "content-security-policy":
            self.content_security_policies.append(" ".join(values.get("content", "").split()))


def inspect_static_runtime_security(html_text: str, style_text: str, app_text: str) -> dict[str, bool]:
    resources = _ProductResourceParser()
    try:
        resources.feed(html_text)
    except Exception:
        return {
            "canonical_csp": False,
            "local_resource_references": False,
            "local_stylesheet_references": False,
            "network_apis_absent": False,
            "passed": False,
        }
    checks = {
        "canonical_csp": resources.content_security_policies == [LOCAL_RUNTIME_CSP],
        "local_resource_references": not resources.remote,
        "local_stylesheet_references": not _CSS_UNSAFE_RESOURCE.search(style_text),
        "network_apis_absent": not _SCRIPT_NETWORK_API.search(app_text),
    }
    return {**checks, "passed": all(checks.values())}


def _css_structure_ok(css: str) -> bool:
    cleaned = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    depth = 0
    quote = ""
    escaped = False
    for char in cleaned:
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote:
            escaped = True
            continue
        if char in {"'", '"'}:
            quote = "" if quote == char else char if not quote else quote
            continue
        if quote:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
    return bool(cleaned.strip()) and depth == 0 and not quote


def _local_resource_present(references: list[str], name: str) -> bool:
    return any(Path(urlsplit(reference).path).name == name for reference in references)


def js_syntax_ok(js: str) -> bool:
    node = shutil.which("node")
    if not node:
        return bool(js.strip()) and not js.rstrip().endswith((".", ",", "=>"))
    with tempfile.TemporaryDirectory(prefix="reweave-js-check-") as tmp:
        path = Path(tmp) / "app.js"
        path.write_text(js, encoding="utf-8")
        return subprocess.run([node, "--check", str(path)], capture_output=True, text=True).returncode == 0


def build_quality_gate(
    root: Path,
    task: str,
    task_plan: dict[str, Any],
    *,
    content_aware: bool,
    behavior_contract: dict[str, Any] | None = None,
    behavior_adaptation: dict[str, Any] | None = None,
    product_entry: dict[str, Any] | None = None,
    source_signals: list[str] | None = None,
) -> dict[str, Any]:
    entry = dict(product_entry or {"path": "index.html", "kind": "static_html"})
    entry_path = str(entry.get("path") or "index.html")
    candidate = root / entry_path
    try:
        resolved_entry = candidate.resolve()
        resolved_entry.relative_to(root.resolve())
        entry_safe = not candidate.is_symlink() and resolved_entry.is_file()
    except (OSError, ValueError):
        resolved_entry = candidate
        entry_safe = False
    html_text = resolved_entry.read_text(encoding="utf-8") if entry_safe else ""
    review_text = (root / "review.html").read_text(encoding="utf-8") if (root / "review.html").is_file() else ""
    product_script = resolved_entry.with_name("app.js") if entry_safe else root / "app.js"
    app_text = product_script.read_text(encoding="utf-8") if product_script.is_file() else ""
    style_path = resolved_entry.with_name("styles.css") if entry_safe else root / "styles.css"
    style_text = style_path.read_text(encoding="utf-8") if style_path.is_file() else ""
    resources = _ProductResourceParser()
    try:
        resources.feed(html_text)
    except Exception:
        resources = _ProductResourceParser()
    static_entry = str(entry.get("kind") or "static_html") == "static_html"
    runtime_security = inspect_static_runtime_security(html_text, style_text, app_text)
    planned = [
        str(item.get("path"))
        for item in task_plan.get("outputs", [])
        if isinstance(item, dict) and item.get("path")
    ]
    reasons = [
        str(item.get("reason"))
        for item in task_plan.get("capsules", [])
        if isinstance(item, dict) and item.get("reason")
    ]
    internal_terms = (
        "Task Intent",
        "Plan files",
        "Source excerpts used",
        "Reused signals",
        "Source-backed cues",
        "Source Boxes",
        "capsule metadata only",
    )
    source_code_terms = ("document.", "window.", "querySelector", "getElementById", "addEventListener")
    technical_scaffolding = ("```", "package.json", '"name":', '"version":', "Content Intake")
    product_text = html_text + "\n" + app_text
    visible_source_signals = [signal for signal in (source_signals or []) if html.escape(signal) in product_text]
    checks = [
        {
            "name": "planned_outputs_exist",
            "passed": all((root / path).is_file() for path in planned),
        },
        {
            "name": "planned_outputs_match_core_files",
            "passed": set(planned) == {"index.html", "styles.css", "app.js"},
        },
        {
            "name": "product_entry_exists",
            "passed": entry_safe,
        },
        {
            "name": "product_entry_javascript_syntax_valid",
            "passed": js_syntax_ok(app_text),
        },
        {
            "name": "static_entry_links_stylesheet",
            "passed": (not static_entry) or _local_resource_present(resources.styles, "styles.css"),
        },
        {
            "name": "static_entry_links_javascript",
            "passed": (not static_entry) or _local_resource_present(resources.scripts, "app.js"),
        },
        {
            "name": "stylesheet_structure_valid",
            "passed": (not static_entry) or _css_structure_ok(style_text),
        },
        {
            "name": "runtime_network_access_closed",
            "passed": (not static_entry) or runtime_security["passed"],
        },
        {
            "name": "task_bound_to_product_entry",
            "passed": html.escape((task or "")[:MAX_TASK_LEN]) in html_text,
        },
        {
            "name": "product_entry_hides_internal_review_terms",
            "passed": all(term not in html_text for term in internal_terms),
        },
        {
            "name": "product_entry_hides_source_code_fragments",
            "passed": all(term not in html_text for term in source_code_terms),
        },
        {
            "name": "product_entry_hides_technical_scaffolding",
            "passed": all(term not in html_text for term in technical_scaffolding),
        },
        {
            "name": "review_artifact_exists",
            "passed": (root / "review.html").is_file(),
        },
        {
            "name": "capsule_reason_visible_in_review",
            "passed": bool(reasons) and any(html.escape(reason) in review_text for reason in reasons),
        },
        {
            "name": "source_cues_visible_in_review",
            "passed": (not content_aware)
            or ("Source excerpts used" in review_text)
            or ("Source-backed cues" in review_text and "capsule metadata only" not in review_text),
        },
    ]
    if behavior_contract is not None:
        interactions = behavior_contract.get("interactions") if isinstance(behavior_contract.get("interactions"), dict) else {}
        events = interactions.get("events") if isinstance(interactions.get("events"), list) else []
        passive_updates = interactions.get("passive_updates") if isinstance(interactions.get("passive_updates"), list) else []
        protected = behavior_adaptation.get("protected") if isinstance(behavior_adaptation, dict) and isinstance(behavior_adaptation.get("protected"), dict) else {}
        expected_ids = [str(item) for item in protected.get("dom_ids", []) if item]
        expected_selectors = [str(item) for item in protected.get("selectors", []) if item]
        source_script = behavior_contract.get("files", {}).get("script", {}) if isinstance(behavior_contract.get("files"), dict) else {}
        expected_script_sha = str(source_script.get("sha256") or "") if isinstance(source_script, dict) else ""
        actual_script_sha = hashlib.sha256((root / "app.js").read_bytes()).hexdigest()
        task_heading = str(behavior_adaptation.get("task_heading") or "") if isinstance(behavior_adaptation, dict) else ""
        adaptation_targets = {
            str(item.get("target") or "")
            for item in behavior_adaptation.get("patches", [])
            if isinstance(behavior_adaptation, dict) and isinstance(item, dict)
        }
        heading_required = bool(adaptation_targets & {"document_title", "primary_heading"})
        checks.extend(
            [
                {
                    "name": "behavior_contract_materialized",
                    "passed": (root / "behavior_contract.json").is_file()
                    and 'data-reweave-behavior="closed"' in html_text,
                },
                {
                    "name": "behavior_adaptation_materialized",
                    "passed": (root / "behavior_adaptation.json").is_file()
                    and 'data-reweave-adaptation="safe-text"' in html_text
                    and bool(task_heading)
                    and (not heading_required or html.escape(task_heading) in html_text),
                },
                {
                    "name": "behavior_dom_contract_preserved",
                    "passed": bool(expected_ids or expected_selectors)
                    and all(
                        re.search(rf'\bid\s*=\s*["\']{re.escape(item)}["\']', html_text)
                        for item in expected_ids
                    )
                    and all(selector.lstrip("#.") in html_text for selector in expected_selectors),
                },
                {
                    "name": "behavior_script_preserved",
                    "passed": bool(expected_script_sha) and actual_script_sha == expected_script_sha,
                },
                {
                    "name": "behavior_event_bindings_preserved",
                    "passed": (
                        bool(events)
                        and all(
                            (
                                str(item.get("target_id") or "") in html_text
                                or str(item.get("target_selector") or "").lstrip("#.") in html_text
                            )
                            and str(item.get("event") or "") in app_text
                            for item in events
                            if isinstance(item, dict)
                        )
                    )
                    or (
                        bool(passive_updates)
                        and all(str(item.get("api") or "") in app_text for item in passive_updates if isinstance(item, dict))
                    ),
                },
            ]
        )
    return {
        "schema_version": "reweave_quality_gate.v1",
        "status": "passed" if all(check["passed"] for check in checks) else "failed",
        "checks": checks,
        "product_entry": entry,
        "metrics": {
            "source_signal_count": len(source_signals or []),
            "visible_source_signal_count": len(visible_source_signals),
            "visible_source_signals": visible_source_signals[:8],
        },
        "source_project_write": False,
        "runtime_network_access": bool(static_entry and not runtime_security["passed"]),
        "behavior_reuse": {
            "status": "static_verified" if behavior_contract is not None else "not_selected",
            "runtime_validation": "required" if behavior_contract is not None else "not_required",
            "interaction_mode": behavior_contract.get("interaction_mode") if behavior_contract is not None else "none",
        },
    }
