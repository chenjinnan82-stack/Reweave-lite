"""Reweave preview package v0 — local preview output in app state only."""

from __future__ import annotations

import json
import re
import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pimos_lite.reweave_capsule_warehouse import get_capsule, is_generate_eligible, list_capsules
from pimos_lite.reweave_snippet_context import (
    CONTEXT_LIMITS,
    build_snippet_context,
    build_snippets_used_manifest,
    count_snippets,
)
from pimos_lite.reweave_source_registry import state_dir

PREVIEW_SCHEMA_VERSION = 1
MAX_TASK_LEN = 240
MAX_SNIPPET_LINES = 12


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def preview_packages_dir() -> Path:
    return state_dir() / "preview_packages"


def latest_manifest_path() -> Path:
    return preview_packages_dir() / "latest.json"


def preview_history_index_path() -> Path:
    return preview_packages_dir() / "index.json"


def load_preview_history() -> dict[str, Any]:
    path = preview_history_index_path()
    if not path.is_file():
        return {"schema_version": PREVIEW_SCHEMA_VERSION, "packages": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schema_version": PREVIEW_SCHEMA_VERSION, "packages": []}
    if not isinstance(data, dict):
        return {"schema_version": PREVIEW_SCHEMA_VERSION, "packages": []}
    data.setdefault("schema_version", PREVIEW_SCHEMA_VERSION)
    data.setdefault("packages", [])
    return data


def append_preview_history_entry(
    *,
    folder_name: str,
    rel_folder: str,
    created_at: str,
    mode: str,
    content_aware: bool,
    snippets_used: int,
) -> None:
    """Append a preview package record to preview_packages/index.json."""
    data = load_preview_history()
    packages: list[dict[str, Any]] = [
        item for item in data.get("packages", []) if isinstance(item, dict)
    ]
    entry = {
        "id": folder_name,
        "path": rel_folder.rstrip("/"),
        "created_at": created_at,
        "mode": mode,
        "content_aware": content_aware,
        "snippets_used": snippets_used,
    }
    packages = [item for item in packages if item.get("id") != folder_name]
    packages.insert(0, entry)
    data["packages"] = packages[:50]
    preview_history_index_path().parent.mkdir(parents=True, exist_ok=True)
    tmp = preview_history_index_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(preview_history_index_path())


def _slug_from_task(task: str) -> str:
    base = re.sub(r"[^\w\-]+", "-", (task or "preview").strip().lower()).strip("-")
    if not base:
        base = "preview"
    return base[:48]


def _folder_name(task: str, stamp: str) -> str:
    return f"{_slug_from_task(task)}_{stamp.replace(':', '').replace('-', '')[:15]}"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_index_html(
    task: str,
    capsules: list[dict[str, Any]],
    *,
    content_aware: bool = False,
    snippet_context: dict[str, Any] | None = None,
) -> str:
    profile = _task_profile(task, capsules)
    task_plan = _task_plan(_task_intent(task, capsules))
    task_title = html.escape((task or "New Task Pack")[:MAX_TASK_LEN])
    capsule_names = [str(cap.get("name") or "Capsule") for cap in capsules[:4]]
    capsule_tags = sorted(
        {
            str(tag)
            for cap in capsules
            for tag in (cap.get("tags") or [])
            if str(tag).strip()
        }
    )[:8]
    source_names: list[str] = []
    for cap in capsules:
        raw_source = cap.get("source")
        name = raw_source.get("label") if isinstance(raw_source, dict) else raw_source
        name = str(name or cap.get("source_id") or "").strip()
        if name and name not in source_names:
            source_names.append(name)
    source_names = sorted(source_names)[:4]

    summary = str(profile["summary"])
    signal_items = "".join(
        f"<li>{html.escape(tag)}</li>" for tag in (capsule_tags or ["layout", "copy", "logic"])
    )
    source_items = "".join(
        f"<li>{html.escape(name)}</li>" for name in (source_names or ["local Source Box"])
    )
    plan_items = "".join(
        f"<li>{html.escape(str(item.get('path')))} — {html.escape(str(item.get('purpose')))}</li>"
        for item in task_plan["outputs"]
        if isinstance(item, dict)
    )
    source_cues = _source_highlights(snippet_context) if content_aware else []
    cue_items = "".join(f"<li>{html.escape(cue)}</li>" for cue in source_cues)
    capsule_badges = "".join(
        f"<span>{html.escape(name)}</span>" for name in (capsule_names or ["Selected capsule"])
    )
    project_cards = "".join(
        "<article>"
        f"<strong>{html.escape(str(cap.get('name') or 'Capsule'))}</strong>"
        f"<p>{html.escape(str(cap.get('reason') or 'Selected project pattern'))}</p>"
        "</article>"
        for cap in (task_plan["capsules"][:4] or [{"name": "Project shell", "reason": "Generated local output"}])
    )
    checklist = "".join(
        "<label>"
        "<input class='reweave-step' type='checkbox' />"
        f"<span>{html.escape(step)}</span>"
        "</label>"
        for step in _project_steps(capsules, profile)
    )
    excerpt_cards = ""
    if content_aware and isinstance(snippet_context, dict):
        cards: list[str] = []
        for cap in snippet_context.get("capsules") if isinstance(snippet_context.get("capsules"), list) else []:
            if not isinstance(cap, dict):
                continue
            cap_name = html.escape(str(cap.get("name") or cap.get("capsule_id") or "Capsule"))
            for snip in cap.get("snippets") if isinstance(cap.get("snippets"), list) else []:
                if not isinstance(snip, dict):
                    continue
                rel = html.escape(str(snip.get("relative_path") or "source excerpt"))
                excerpt = html.escape(str(snip.get("preview_excerpt") or "")[:900])
                cards.append(
                    f"<article class='excerpt-card'>"
                    f"<h3>{cap_name}</h3>"
                    f"<p>{rel}</p>"
                    f"<pre>{excerpt}</pre>"
                    f"</article>"
                )
        if cards:
            excerpt_cards = (
                "<section class='source-excerpts' aria-label='Source excerpts used'>"
                "<p class='eyebrow'>Source excerpts used</p>"
                + "".join(cards[:4])
                + "</section>"
            )

    items = []
    for cap in capsules:
        preview = cap.get("preview") or []
        snippet = "\n".join(html.escape(str(line)) for line in preview[:MAX_SNIPPET_LINES])
        name = html.escape(str(cap.get("name") or "Capsule"))
        capsule_type = html.escape(str(cap.get("type") or ""))
        role = html.escape(str(cap.get("role") or ""))
        items.append(
            f"<article class='capsule-card'>"
            f"<h2>{name} <span class='type'>{capsule_type}</span></h2>"
            f"<p class='role'>{role}</p>"
            f"<pre>{snippet}</pre>"
            f"</article>"
        )
    body = "\n".join(items) if items else "<p class='empty'>No capsules selected.</p>"
    note = (
        "Content-aware preview — excerpt manifests in snippets_used.json; not copied source files."
        if content_aware
        else "Preview only — capsules are metadata snippets, not copied source files."
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{task_title}</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <main class="surface">
    <header>
      <p class="eyebrow">Reweave · local preview</p>
      <h1>{task_title}</h1>
      <p class="note">{note}</p>
    </header>
    <section class="task-output" aria-label="Generated task output">
      <div>
        <p class="eyebrow">{html.escape(str(profile["label"]))}</p>
        <h2>{task_title}</h2>
        <p>{html.escape(summary)}</p>
        <div class="capsule-badges">{capsule_badges}</div>
      </div>
      <aside>
        <strong>Plan files</strong>
        <ul>{plan_items}</ul>
        <strong>Reused signals</strong>
        <ul>{signal_items}</ul>
        <strong>Source-backed cues</strong>
        <ul>{cue_items or "<li>capsule metadata only</li>"}</ul>
        <strong>Source Boxes</strong>
        <ul>{source_items}</ul>
      </aside>
    </section>
    <section class="project-app" aria-label="Runnable small project output">
      <div>
        <p class="eyebrow">{html.escape(str(profile["output_label"]))}</p>
        <h2>{task_title}</h2>
        <p>This package is self-contained: no external scripts, no source-folder writes, and every reused capsule is recorded.</p>
        <button id="reweaveDemoButton" type="button">{html.escape(str(profile["action"]))}</button>
        <p id="reweaveDemoStatus">Ready for local review.</p>
      </div>
      <div>
        <div class="project-cards">{project_cards}</div>
        <div class="project-checklist" aria-label="Local review checklist">{checklist}</div>
      </div>
    </section>
    {excerpt_cards}
    <section class="capsules">{body}</section>
  </main>
  <script src="app.js"></script>
</body>
</html>
"""


CAPABILITY_KEYWORDS = {
    "form": ("form", "quote", "input", "submit", "customer", "field"),
    "table": ("table", "list", "queue", "record", "calendar", "row"),
    "copy": ("copy", "landing", "content", "message", "hero", "story"),
    "style": ("style", "css", "brand", "visual", "layout", "design"),
    "logic": ("logic", "workflow", "action", "filter", "calculate", "triage", "interaction"),
    "data": ("data", "dashboard", "metric", "status", "chart", "viewer", "panel"),
}


def _capsule_reason(cap: dict[str, Any], capabilities: list[str]) -> str:
    text = " ".join(
        str(part or "")
        for part in (
            cap.get("name"),
            cap.get("type"),
            cap.get("role"),
            " ".join(str(tag) for tag in (cap.get("tags") or [])),
        )
    ).lower()
    matched = [capability for capability in capabilities if capability in text]
    if matched:
        return "matches " + ", ".join(matched[:3]) + " need"
    return str(cap.get("role") or "selected for source-backed task context")


def _task_intent(task: str, capsules: list[dict[str, Any]]) -> dict[str, Any]:
    # ponytail: keyword intent is enough for v0; replace with parser only when real tasks beat it.
    task_text = (task or "").lower()
    text = " ".join(
        [task or ""]
        + [
            " ".join(
                str(part or "")
                for part in (
                    cap.get("name"),
                    cap.get("type"),
                    cap.get("role"),
                    " ".join(str(tag) for tag in (cap.get("tags") or [])),
                )
            )
            for cap in capsules
            if isinstance(cap, dict)
        ]
    ).lower()
    capabilities = [
        name
        for name, words in CAPABILITY_KEYWORDS.items()
        if any(word in text for word in words)
    ] or ["copy", "style"]
    if any(word in task_text for word in ("component", "react", "tsx", "widget")):
        output_type = "component"
    elif any(word in task_text for word in ("doc", "document", "report", "readme")):
        output_type = "document"
    elif any(word in task_text for word in ("dashboard", "panel", "viewer", "table", "calendar", "data")):
        output_type = "data_panel"
    elif any(word in task_text for word in ("tool", "form", "quote", "interaction")):
        output_type = "tool"
    else:
        output_type = "page"
    return {
        "schema_version": "reweave_task_intent.v1",
        "task": (task or "Build a small project pack")[:MAX_TASK_LEN],
        "goal": (task or "Build a small project pack")[:MAX_TASK_LEN],
        "output_type": output_type,
        "needed_files": ["index.html", "styles.css", "app.js"],
        "capabilities": capabilities,
        "retrieved_capsules": [
            {
                "id": cap.get("id"),
                "name": cap.get("name"),
                "source_id": cap.get("source_id"),
                "reason": _capsule_reason(cap, capabilities),
            }
            for cap in capsules
            if isinstance(cap, dict)
        ],
        "source_project_write": False,
    }


def _task_profile(task: str, capsules: list[dict[str, Any]] | None = None) -> dict[str, object]:
    intent = _task_intent(task, capsules or [])
    output_type = str(intent["output_type"])
    capabilities = [str(item) for item in intent["capabilities"]]
    return {
        "id": "task_driven",
        "label": "Task Intent",
        "output_label": output_type.replace("_", " ").title(),
        "action": "Review output",
        "summary": "A runnable small project pack assembled from the task, selected capsules, and source excerpts.",
        "steps": [
            "Check task goal",
            "Review " + ", ".join(capabilities[:3]) + " signals",
            "Check source excerpts",
            "Check provenance",
            "Confirm source writes stay 0",
        ],
        "output_kinds": (f"{output_type}_html", "task_style", "task_runtime"),
    }


def _task_plan(task_intent: dict[str, Any]) -> dict[str, Any]:
    capsule_ids = [str(item.get("id")) for item in task_intent.get("retrieved_capsules", []) if isinstance(item, dict) and item.get("id")]
    output_type = str(task_intent.get("output_type") or "page")
    return {
        "schema_version": "reweave_task_plan.v1",
        "task": task_intent.get("task"),
        "output_type": output_type,
        "source_project_write": False,
        "composer": {
            "mode": "task_plan_and_snippets",
            "inputs": ["task_intent.json", "task_plan.json", "capsules_used.json"],
            "optional_inputs": ["snippets_used.json"],
        },
        "outputs": [
            {
                "path": "index.html",
                "purpose": f"render the {output_type} for local review",
                "capsule_ids": capsule_ids,
            },
            {
                "path": "styles.css",
                "purpose": "carry source-backed visual structure and spacing",
                "capsule_ids": capsule_ids,
            },
            {
                "path": "app.js",
                "purpose": "add only local preview interaction and review checks",
                "capsule_ids": capsule_ids,
            },
        ],
        "capsules": list(task_intent.get("retrieved_capsules") or []),
        "acceptance": [
            "open index.html locally",
            "confirm index.html, styles.css, and app.js exist",
            "check capsules_used.json",
            "check provenance.json",
            "confirm source writes stay 0",
        ],
    }


def _quality_gate(root: Path, task: str, task_plan: dict[str, Any], *, content_aware: bool) -> dict[str, Any]:
    html_text = (root / "index.html").read_text(encoding="utf-8") if (root / "index.html").is_file() else ""
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
            "name": "task_visible_in_html",
            "passed": html.escape((task or "")[:MAX_TASK_LEN]) in html_text,
        },
        {
            "name": "capsule_reason_visible_in_html",
            "passed": bool(reasons) and any(html.escape(reason) in html_text for reason in reasons),
        },
        {
            "name": "source_cues_visible_in_html",
            "passed": (not content_aware) or ("Source excerpts used" in html_text) or ("Source-backed cues" in html_text and "capsule metadata only" not in html_text),
        },
    ]
    return {
        "schema_version": "reweave_quality_gate.v1",
        "status": "passed" if all(check["passed"] for check in checks) else "failed",
        "checks": checks,
        "source_project_write": False,
    }


def _source_highlights(snippet_context: dict[str, Any] | None) -> list[str]:
    if not isinstance(snippet_context, dict):
        return []
    highlights: list[str] = []
    for cap in snippet_context.get("capsules") if isinstance(snippet_context.get("capsules"), list) else []:
        if not isinstance(cap, dict):
            continue
        for snip in cap.get("snippets") if isinstance(cap.get("snippets"), list) else []:
            if not isinstance(snip, dict):
                continue
            excerpt = str(snip.get("preview_excerpt") or "")
            candidates = re.findall(r">([^<>]{3,80})<", excerpt) or excerpt.splitlines()
            for raw in candidates:
                text = re.sub(r"\s+", " ", raw).strip(" -_•\t")
                if 3 <= len(text) <= 80 and text not in highlights:
                    highlights.append(text)
                if len(highlights) >= 6:
                    return highlights
    return highlights


def _build_preview_readme(task: str, snippet_context: dict[str, Any]) -> str:
    lines = [
        f"# {(task or 'Reweave preview')[:MAX_TASK_LEN]}",
        "",
        "Content-aware preview package (Phase 11).",
        "Excerpt manifests live in snippets_used.json — not full source copies.",
        "",
    ]
    for cap in snippet_context.get("capsules") if isinstance(snippet_context.get("capsules"), list) else []:
        if not isinstance(cap, dict):
            continue
        lines.append(f"## {cap.get('name', 'Capsule')} ({cap.get('capsule_id')})")
        for snip in cap.get("snippets") if isinstance(cap.get("snippets"), list) else []:
            if not isinstance(snip, dict):
                continue
            path = snip.get("relative_path") or "file"
            chars = snip.get("excerpt_chars") or 0
            flags = []
            if snip.get("truncated"):
                flags.append("truncated")
            if snip.get("redacted"):
                flags.append("redacted")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"- {path} · {chars} chars{suffix}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _style_tokens(snippet_context: dict[str, Any] | None) -> dict[str, str]:
    colors: list[str] = []
    if isinstance(snippet_context, dict):
        for cap in snippet_context.get("capsules") if isinstance(snippet_context.get("capsules"), list) else []:
            if not isinstance(cap, dict):
                continue
            for snip in cap.get("snippets") if isinstance(cap.get("snippets"), list) else []:
                if not isinstance(snip, dict):
                    continue
                rel = str(snip.get("relative_path") or "")
                lang = str(snip.get("language_hint") or "")
                if not (rel.endswith(".css") or lang == "css"):
                    continue
                colors.extend(re.findall(r"#[0-9a-fA-F]{3,6}\b", str(snip.get("preview_excerpt") or "")))
    skip = {"#000", "#000000", "#fff", "#ffffff"}
    accent = next((c for c in colors if c.lower() not in skip), "#21352a")
    return {"accent": accent, "soft": "#f8fbf8"}


def _project_steps(capsules: list[dict[str, Any]], profile: dict[str, object] | None = None) -> list[str]:
    if profile and isinstance(profile.get("steps"), list):
        return [str(step) for step in profile["steps"]][:5]
    names = [str(cap.get("name") or "Capsule") for cap in capsules[:3]]
    steps = [f"Review {name}" for name in names]
    steps.extend(["Check provenance", "Confirm source writes stay 0"])
    return steps[:5]


def _build_styles_css(snippet_context: dict[str, Any] | None = None) -> str:
    tokens = _style_tokens(snippet_context)
    css = """:root {
  --accent: __ACCENT__;
  --soft: __SOFT__;
}

body {
  margin: 0;
  font-family: ui-sans-serif, system-ui, sans-serif;
  background: #fdfcf8;
  color: #2b261c;
}
.surface { max-width: 720px; margin: 2rem auto; padding: 0 1.25rem; }
.eyebrow { letter-spacing: 0.08em; text-transform: uppercase; font-size: 0.75rem; color: #8a7355; }
.note { color: #6b5d4a; font-size: 0.9rem; }
.task-output { display: grid; grid-template-columns: minmax(0, 1fr) 220px; gap: 1rem; background: #fff; border: 1px solid #e8dfd0; border-radius: 10px; padding: 1rem; box-shadow: 0 12px 32px rgba(43, 38, 28, 0.08); }
.task-output h2 { margin: 0 0 0.5rem; }
.task-output aside { border-left: 1px solid #e8dfd0; padding-left: 1rem; font-size: 0.9rem; color: #6b5d4a; }
.task-output ul { margin: 0.35rem 0 0.85rem; padding-left: 1.1rem; }
.capsule-badges { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.75rem; }
.capsule-badges span { border: 1px solid #e8dfd0; border-radius: 999px; padding: 0.25rem 0.55rem; color: #6b5d4a; background: #faf7f0; font-size: 0.8rem; }
.project-app { display: grid; grid-template-columns: minmax(0, 0.9fr) minmax(260px, 1.1fr); gap: 1rem; margin-top: 1rem; padding: 1rem; border: 1px solid #d8e3dc; border-radius: 10px; background: var(--soft); }
.project-app h2 { margin: 0 0 0.5rem; }
.project-app button { min-height: 40px; border: 0; border-radius: 6px; padding: 0 0.85rem; background: var(--accent); color: #fff; font: inherit; cursor: pointer; }
#reweaveDemoStatus { margin: 0.75rem 0 0; color: #5f6f62; font-size: 0.9rem; }
.project-cards { display: grid; gap: 0.65rem; }
.project-cards article { border: 1px solid #d8e3dc; border-radius: 8px; background: #fff; padding: 0.85rem; }
.project-cards p { margin: 0.35rem 0 0; color: #5f6f62; font-size: 0.9rem; }
.project-checklist { display: grid; gap: 0.55rem; margin-top: 1rem; }
.project-checklist label { display: flex; align-items: center; gap: 0.5rem; padding: 0.6rem 0.7rem; border: 1px solid #d8e3dc; border-radius: 8px; background: #fff; }
.project-checklist input { accent-color: var(--accent); }
.source-excerpts { margin-top: 1rem; }
.excerpt-card { border: 1px solid #e8dfd0; border-radius: 10px; background: #fff; padding: 0.85rem; margin: 0.75rem 0; }
.excerpt-card h3 { margin: 0; font-size: 0.95rem; }
.excerpt-card p { margin: 0.25rem 0 0.65rem; color: #6b5d4a; font-size: 0.8rem; }
.excerpt-card pre { max-height: 220px; overflow: auto; background: #faf7f0; border-radius: 6px; padding: 0.75rem; }
.capsule-card { background: #fff; border: 1px solid #e8dfd0; border-radius: 10px; padding: 1rem; margin: 1rem 0; }
.capsule-card .type { font-size: 0.75rem; color: #a67c3d; }
.capsule-card pre { background: #faf7f0; padding: 0.75rem; border-radius: 6px; overflow: auto; }
.empty { color: #6b5d4a; }
@media (max-width: 680px) { .task-output, .project-app { grid-template-columns: 1fr; } .task-output aside { border-left: 0; border-top: 1px solid #e8dfd0; padding-left: 0; padding-top: 1rem; } }
"""
    return css.replace("__ACCENT__", tokens["accent"]).replace("__SOFT__", tokens["soft"])


def _build_app_js() -> str:
    return """document.addEventListener('DOMContentLoaded', function () {
  const button = document.getElementById('reweaveDemoButton');
  const status = document.getElementById('reweaveDemoStatus');
  const steps = Array.from(document.querySelectorAll('.reweave-step'));
  function renderProgress() {
    if (!status || !steps.length) return;
    const done = steps.filter(function (item) { return item.checked; }).length;
    status.textContent = done + ' of ' + steps.length + ' local checks complete.';
  }
  steps.forEach(function (item) {
    item.addEventListener('change', renderProgress);
  });
  if (button && status) {
    button.addEventListener('click', function () {
      const next = steps.find(function (item) { return !item.checked; });
      if (next) next.checked = true;
      renderProgress();
    });
  }
  renderProgress();
  console.log('[Reweave] small project pack ready');
});
"""


def _resolve_capsules(capsule_ids: list[str]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for cap_id in capsule_ids:
        cap = get_capsule(cap_id)
        if cap and is_generate_eligible(cap):
            resolved.append(cap)
    return resolved


def _capsule_used_entry(cap: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": cap.get("id"),
        "name": cap.get("name"),
        "type": cap.get("type"),
        "serial": cap.get("serial"),
        "source": cap.get("source"),
        "source_id": cap.get("source_id"),
        "role": cap.get("role"),
        "tags": list(cap.get("tags") or []),
        "status": cap.get("status"),
        "origin": cap.get("origin"),
    }
    if isinstance(cap.get("lineage"), dict):
        entry["lineage"] = dict(cap["lineage"])
    if cap.get("risk"):
        entry["risk"] = cap.get("risk")
    if cap.get("content_mode"):
        entry["content_mode"] = cap.get("content_mode")
    if isinstance(cap.get("content_enrichment"), dict):
        entry["content_enrichment"] = {
            "status": cap["content_enrichment"].get("status"),
            "content_path": cap["content_enrichment"].get("content_path"),
            "snippet_count": cap["content_enrichment"].get("snippet_count"),
        }
    if cap.get("content_risk"):
        entry["content_risk"] = cap.get("content_risk")
    return entry


def _capsule_provenance_entry(cap: dict[str, Any]) -> dict[str, Any]:
    entry = _capsule_used_entry(cap)
    if isinstance(cap.get("snippet"), dict):
        entry["snippet"] = {
            "kind": cap["snippet"].get("kind"),
            "description": cap["snippet"].get("description"),
        }
    enrichment = cap.get("content_enrichment") if isinstance(cap.get("content_enrichment"), dict) else None
    if enrichment and enrichment.get("content_path"):
        entry["content_path"] = enrichment.get("content_path")
    return entry


def _sanitize_source_boxes(rows: Any, *, include_local_paths: bool = False) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    boxes: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        box = {
            "id": row.get("id"),
            "label": row.get("label"),
            "path_policy": "included" if include_local_paths and row.get("path") else "redacted",
        }
        if include_local_paths and row.get("path"):
            box["path"] = str(row["path"])
        boxes.append(box)
    return boxes


def _build_task_pack(task: str, capsules: list[dict[str, Any]], *, selection_mode: str = "selected_capsules") -> dict[str, Any]:
    task_intent = _task_intent(task, capsules)
    task_plan = _task_plan(task_intent)
    profile = _task_profile(task, capsules)
    capsule_ids = [str(c.get("id") or "") for c in capsules if c.get("id")]
    output_kinds = list(profile["output_kinds"])
    capsules_used = list(task_intent["retrieved_capsules"])
    return {
        "schema_version": "reweave_task_pack.v1",
        "mode": "task_pack_preview",
        "package_kind": "small_project_pack",
        "task_profile": profile["id"],
        "task": task,
        "task_intent_path": "task_intent.json",
        "task_intent": task_intent,
        "task_plan_path": "task_plan.json",
        "task_plan": task_plan,
        "quality_gate_path": "quality_gate.json",
        "composer": task_plan["composer"],
        "task_scope": "preview_only",
        "selection_mode": selection_mode,
        "source_project_write": False,
        "selected_capsule_ids": capsule_ids,
        "capsules_used": capsules_used,
        "planned_outputs": [
            {
                "path": "index.html",
                "kind": output_kinds[0],
                "capsule_ids": capsule_ids,
            },
            {
                "path": "styles.css",
                "kind": output_kinds[1],
                "capsule_ids": capsule_ids,
            },
            {
                "path": "app.js",
                "kind": output_kinds[2],
                "capsule_ids": capsule_ids,
            },
        ],
        "planned_files": [
            {
                "path": "preview/index.html",
                "action": "preview_only",
                "reason": task_plan["outputs"][0]["purpose"],
            },
            {
                "path": "task_pack.json",
                "action": "plan_only",
                "reason": "record task scope, capsule inputs, and checks",
            },
        ],
        "validation": task_plan["acceptance"],
        "checks": task_plan["acceptance"],
        "effects": {
            "source_project_write": False,
            "preview_output_write": True,
            "manual_real_write": False,
        },
    }


def _build_summary_md(task: str, capsules: list[dict[str, Any]]) -> str:
    lines = [
        "# Reweave Small Project Pack",
        "",
        f"- Task: {task}",
        f"- Capsules used: {len(capsules)}",
        "- Source project writes: 0",
        "",
        "## Capsules",
    ]
    for cap in capsules:
        lines.append(f"- {cap.get('name', 'Capsule')} ({cap.get('id')})")
    return "\n".join(lines).strip() + "\n"


def build_preview_package(payload: dict[str, Any]) -> dict[str, Any]:
    """Write a local preview package under app state and return UI metadata."""
    task = str(payload.get("taskText") or payload.get("task") or "New tool")[:MAX_TASK_LEN]
    raw_ids = payload.get("capsuleIds") if isinstance(payload.get("capsuleIds"), list) else []
    capsule_ids = [str(x) for x in raw_ids if x]
    capsules = _resolve_capsules(capsule_ids)
    raw_capsules = payload.get("capsules") if isinstance(payload.get("capsules"), list) else []
    if raw_capsules:
        known = {str(cap.get("id") or "") for cap in capsules if isinstance(cap, dict)}
        for cap in raw_capsules:
            if not isinstance(cap, dict):
                continue
            cap_id = str(cap.get("id") or "")
            if capsule_ids and cap_id not in capsule_ids:
                continue
            if cap_id and cap_id not in known:
                capsules.append(cap)
                known.add(cap_id)
    if not capsules and capsule_ids:
        raise ValueError("selected capsules not found in warehouse")

    use_enriched = bool(payload.get("useEnrichedContent"))
    snippet_context: dict[str, Any] | None = None
    if use_enriched:
        snippet_context = build_snippet_context(capsule_ids)

    stamp = _utc_now_iso()
    folder_name = _folder_name(task, stamp)
    root = preview_packages_dir() / folder_name
    root.mkdir(parents=True, exist_ok=False)

    capsules_used = [_capsule_used_entry(c) for c in capsules]
    content_aware_enabled = use_enriched and bool(snippet_context and snippet_context.get("capsules"))
    provenance: dict[str, Any] = {
        "schema_version": PREVIEW_SCHEMA_VERSION,
        "generated_at": stamp,
        "backend": str(payload.get("backend") or "local"),
        "task": task,
        "task_intent_path": "task_intent.json",
        "task_plan_path": "task_plan.json",
        "quality_gate_path": "quality_gate.json",
        "capsule_ids": [c.get("id") for c in capsules],
        "capsules": [_capsule_provenance_entry(c) for c in capsules],
        "outputs": [
            {
                "path": name,
                "capsule_ids": [c.get("id") for c in capsules],
                "source_project_write": False,
            }
            for name in ("index.html", "styles.css", "app.js")
        ],
        "source_boxes": _sanitize_source_boxes(
            payload.get("sourceBoxes"),
            include_local_paths=bool(payload.get("includeLocalSourcePaths")),
        ),
    }

    if use_enriched and snippet_context:
        provenance["content_aware_generate"] = {
            "enabled": True,
            "mode": snippet_context.get("mode", "content_aware_preview"),
            "used_app_state_content_only": True,
            "snippets_used_path": "snippets_used.json" if content_aware_enabled else None,
            "source_folder_read_at_generate_time": False,
            "llm_called": False,
            "dispatch_called": False,
            "limits": snippet_context.get("limits") or dict(CONTEXT_LIMITS),
            "warnings": list(snippet_context.get("warnings") or []),
        }
    else:
        provenance["content_aware_generate"] = {"enabled": False}

    selection_mode = str(payload.get("selectionMode") or payload.get("selection_mode") or "selected_capsules")
    task_pack = _build_task_pack(task, capsules, selection_mode=selection_mode)
    task_intent = task_pack["task_intent"]
    task_plan = task_pack["task_plan"]
    files = ["index.html", "styles.css", "app.js", "task_intent.json", "task_plan.json", "task_pack.json", "capsules_used.json", "provenance.json", "summary.md"]
    _write_text(root / "index.html", _build_index_html(task, capsules, content_aware=content_aware_enabled, snippet_context=snippet_context))
    _write_text(root / "styles.css", _build_styles_css(snippet_context if content_aware_enabled else None))
    _write_text(root / "app.js", _build_app_js())
    _write_text(root / "task_intent.json", json.dumps(task_intent, indent=2, ensure_ascii=False) + "\n")
    _write_text(root / "task_plan.json", json.dumps(task_plan, indent=2, ensure_ascii=False) + "\n")
    _write_text(root / "task_pack.json", json.dumps(task_pack, indent=2, ensure_ascii=False) + "\n")
    _write_text(root / "capsules_used.json", json.dumps(capsules_used, indent=2, ensure_ascii=False) + "\n")
    _write_text(root / "provenance.json", json.dumps(provenance, indent=2, ensure_ascii=False) + "\n")
    _write_text(root / "summary.md", _build_summary_md(task, capsules))

    snippets_used_count = 0
    if content_aware_enabled and snippet_context:
        manifest = build_snippets_used_manifest(snippet_context)
        snippets_used_count = len(manifest.get("snippets") or [])
        _write_text(
            root / "snippets_used.json",
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        )
        files.append("snippets_used.json")
        _write_text(root / "PREVIEW_README.md", _build_preview_readme(task, snippet_context))
        files.append("PREVIEW_README.md")

    quality_gate = _quality_gate(root, task, task_plan, content_aware=content_aware_enabled)
    _write_text(root / "quality_gate.json", json.dumps(quality_gate, indent=2, ensure_ascii=False) + "\n")
    files.append("quality_gate.json")
    if quality_gate["status"] != "passed":
        raise ValueError("preview quality gate failed")

    manifest = {
        "schema_version": PREVIEW_SCHEMA_VERSION,
        "generated_at": stamp,
        "folder_name": folder_name,
        "preview_path": str(root.resolve()),
        "task": task,
        "capsule_count": len(capsules),
    }
    latest_manifest_path().parent.mkdir(parents=True, exist_ok=True)
    tmp = latest_manifest_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(latest_manifest_path())

    rel_folder = f"preview_packages/{folder_name}/"
    append_preview_history_entry(
        folder_name=folder_name,
        rel_folder=rel_folder.rstrip("/"),
        created_at=stamp,
        mode="content_aware_preview" if content_aware_enabled else "metadata_only",
        content_aware=content_aware_enabled,
        snippets_used=snippets_used_count,
    )
    stats: dict[str, Any] = {
        "capsulesUsed": len(capsules),
        "preview": "Local preview package",
        "provenance": "Provenance saved",
    }
    if content_aware_enabled:
        stats["contentAware"] = "Content-aware preview"
        stats["snippetsUsed"] = snippets_used_count

    content_aware_generate = {
        "enabled": use_enriched,
        "snippetsUsed": snippets_used_count,
        "snippetsUsedPath": "snippets_used.json" if content_aware_enabled else None,
        "mode": "content_aware_preview" if content_aware_enabled else None,
    }

    return {
        "ok": True,
        "mock": False,
        "backend": provenance["backend"],
        "previewPath": str(root.resolve()),
        "generatedPackage": {
            "folder": rel_folder,
            "files": files,
            "stats": stats,
        },
        "capsulesUsed": capsules_used,
        "provenance": provenance,
        "taskPack": task_pack,
        "contentAwareGenerate": content_aware_generate,
        "snippetContext": snippet_context if use_enriched else None,
    }


def attach_luna_provenance(preview_path: str | Path, luna_record: dict[str, Any]) -> dict[str, Any]:
    """Merge Luna pack reference into an existing preview package provenance.json."""
    root = Path(preview_path)
    prov_path = root / "provenance.json"
    if not prov_path.is_file():
        raise FileNotFoundError(f"missing provenance: {prov_path}")
    provenance = json.loads(prov_path.read_text(encoding="utf-8"))
    if not isinstance(provenance, dict):
        raise ValueError("provenance.json must be an object")
    provenance["luna"] = luna_record
    _write_text(prov_path, json.dumps(provenance, indent=2, ensure_ascii=False) + "\n")
    return provenance


def build_luna_provenance_record(pack_result: dict[str, Any], *, success: bool) -> dict[str, Any]:
    stamp = _utc_now_iso()
    if success:
        luna_pack = pack_result.get("lunaPack") if isinstance(pack_result.get("lunaPack"), dict) else {}
        return {
            "engine": "lumo",
            "mode": "pack_only",
            "dispatch": False,
            "ok": True,
            "pack_id": luna_pack.get("pack_id"),
            "manifest_path": luna_pack.get("manifest_path"),
            "endpoint": luna_pack.get("endpoint") or "/api/v1/pym/index-pack",
            "created_at": stamp,
        }
    return {
        "engine": "lumo",
        "mode": "pack_only",
        "dispatch": False,
        "ok": False,
        "error": str(pack_result.get("error") or "index_pack_failed")[:200],
        "created_at": stamp,
    }


def load_latest_preview() -> dict[str, Any] | None:
    path = latest_manifest_path()
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    preview_path = data.get("preview_path")
    folder_name = data.get("folder_name", "preview/")
    if preview_path and Path(preview_path).is_dir():
        return {
            "previewPath": str(Path(preview_path).resolve()),
            "generatedPackage": {
                "folder": f"preview_packages/{folder_name}/",
                "files": [
                    "index.html",
                    "styles.css",
                    "app.js",
                    "task_intent.json",
                    "task_plan.json",
                    "task_pack.json",
                    "quality_gate.json",
                    "capsules_used.json",
                    "provenance.json",
                    "summary.md",
                ],
                "stats": {
                    "capsulesUsed": int(data.get("capsule_count") or 0),
                    "preview": "Local preview package",
                    "provenance": "Provenance saved",
                },
            },
            "generated_at": data.get("generated_at"),
            "task": data.get("task"),
        }
    return None
