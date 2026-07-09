"""Pure project renderer helpers for Reweave preview packs."""

from __future__ import annotations

import html
import re
from typing import Any

from pimos_lite.reweave_task_intent import MAX_TASK_LEN
from pimos_lite.reweave_task_intent import build_task_intent as _task_intent
from pimos_lite.reweave_task_intent import build_task_profile as _task_profile
from pimos_lite.reweave_task_plan import build_task_plan as _task_plan

MAX_SNIPPET_LINES = 12

def build_index_html(
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


def build_preview_readme(task: str, snippet_context: dict[str, Any]) -> str:
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


def build_styles_css(snippet_context: dict[str, Any] | None = None) -> str:
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


def build_app_js() -> str:
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
