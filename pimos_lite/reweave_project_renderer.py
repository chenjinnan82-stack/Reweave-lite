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


def _behavior_file(contract: dict[str, Any], role: str) -> dict[str, Any] | None:
    files = contract.get("files") if isinstance(contract.get("files"), dict) else {}
    value = files.get(role)
    return value if isinstance(value, dict) else None


def _simple_tag_text(source: str, tag: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*>([^<>]+)</{tag}>", source, flags=re.IGNORECASE)
    return html.unescape(match.group(1).strip()) if match else ""


def _task_heading(task: str) -> str:
    value = re.sub(r"(?i)^\s*(?:build|create|make|generate)\s+(?:(?:a|an|the)\s+)?", "", task or "").strip()
    value = (value or task or "Reweave project")[:120]
    return value[:1].upper() + value[1:] if value[:1].isascii() else value


def _safe_text_slots(source: str) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for tag in ("p", "h2", "h3", "button", "option"):
        pattern = re.compile(rf"<{tag}\b[^>]*>([^<>]+)</{tag}>", flags=re.IGNORECASE)
        for occurrence, match in enumerate(pattern.finditer(source)):
            value = html.unescape(match.group(1).strip())
            if 2 <= len(value) <= 160:
                slots.append(
                    {
                        "slot_id": f"{tag}:{occurrence}",
                        "tag": tag,
                        "occurrence": occurrence,
                        "kind": "data_item" if tag == "option" else "text",
                        "value": value,
                    }
                )
    return slots[:24]


def _safe_style_variables(contract: dict[str, Any]) -> list[dict[str, str]]:
    css = str((_behavior_file(contract, "style") or {}).get("content") or "")
    return [
        {"name": match.group(1), "value": match.group(2)}
        for match in re.finditer(r"(--[a-zA-Z0-9_-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\b", css)
    ][:12]


def build_behavior_adaptation(task: str, contract: dict[str, Any]) -> dict[str, Any]:
    source = str((_behavior_file(contract, "entry") or {}).get("content") or "")
    heading = _task_heading(task)
    patches = [
        {"target": "document_title", "from": _simple_tag_text(source, "title"), "to": heading},
        {"target": "primary_heading", "from": _simple_tag_text(source, "h1"), "to": heading},
    ]
    patches = [patch for patch in patches if patch["from"] and patch["from"] != patch["to"]]
    interactions = contract.get("interactions") if isinstance(contract.get("interactions"), dict) else {}
    protected_ids = {
        str(item.get("id") or "")
        for item in interactions.get("controls", [])
        if isinstance(item, dict) and item.get("id")
    }
    protected_ids.update(str(item) for item in interactions.get("state_target_ids", []) if item)
    protected_ids.update(
        str(item.get("target_id") or "")
        for item in interactions.get("events", [])
        if isinstance(item, dict) and item.get("target_id")
    )
    protected_selectors = sorted(
        str(item.get("target_selector") or "")
        for item in interactions.get("events", [])
        if isinstance(item, dict) and item.get("target_selector")
    )
    return {
        "schema_version": 1,
        "mode": "safe_text_adaptation",
        "task_heading": heading,
        "patches": patches,
        "allowed_text_slots": _safe_text_slots(source),
        "allowed_style_variables": _safe_style_variables(contract),
        "protected": {
            "dom_ids": sorted(protected_ids),
            "selectors": protected_selectors,
            "events": list(interactions.get("events") or []),
            "script_sha256": str((_behavior_file(contract, "script") or {}).get("sha256") or ""),
        },
    }


def _apply_behavior_adaptation(source: str, adaptation: dict[str, Any]) -> str:
    tags = {"document_title": "title", "primary_heading": "h1"}
    for patch in adaptation.get("patches") if isinstance(adaptation.get("patches"), list) else []:
        if not isinstance(patch, dict) or patch.get("target") not in tags:
            continue
        tag = tags[str(patch["target"])]
        replacement = html.escape(str(patch.get("to") or ""))
        pattern = re.compile(rf"(<{tag}\b[^>]*>)[^<>]+(</{tag}>)", flags=re.IGNORECASE)
        source = pattern.sub(
            lambda match: f"{match.group(1)}{replacement}{match.group(2)}",
            source,
            count=1,
        )
    return source


def _build_behavior_index_html(task: str, contract: dict[str, Any], adaptation: dict[str, Any]) -> str:
    entry = _behavior_file(contract, "entry") or {}
    source = _apply_behavior_adaptation(str(entry.get("content") or ""), adaptation)
    source = re.sub(
        r"<link\b[^>]*\brel=[\"'][^\"']*stylesheet[^\"']*[\"'][^>]*>",
        "",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(
        r"<script\b[^>]*\bsrc=[\"'][^\"']+[\"'][^>]*>\s*</script>",
        "",
        source,
        flags=re.IGNORECASE,
    )
    task_meta = f'<meta name="reweave-task" content="{html.escape((task or "")[:MAX_TASK_LEN], quote=True)}">'
    stylesheet = '<link rel="stylesheet" href="styles.css">'
    if re.search(r"</head>", source, flags=re.IGNORECASE):
        source = re.sub(r"</head>", f"  {task_meta}\n  {stylesheet}\n</head>", source, count=1, flags=re.IGNORECASE)
    else:
        source = task_meta + "\n" + stylesheet + "\n" + source
    source = re.sub(
        r"<html(\s|>)",
        r'<html data-reweave-behavior="closed" data-reweave-adaptation="safe-text"\1',
        source,
        count=1,
        flags=re.IGNORECASE,
    )
    footer = '<p class="reweave-build-notes"><a href="review.html">View build notes</a></p>'
    script = '<script src="app.js"></script>'
    if re.search(r"</body>", source, flags=re.IGNORECASE):
        source = re.sub(r"</body>", f"  {footer}\n  {script}\n</body>", source, count=1, flags=re.IGNORECASE)
    else:
        source += "\n" + footer + "\n" + script + "\n"
    return source

def build_index_html(
    task: str,
    capsules: list[dict[str, Any]],
    *,
    content_aware: bool = False,
    snippet_context: dict[str, Any] | None = None,
    task_profile: dict[str, object] | None = None,
    behavior_contract: dict[str, Any] | None = None,
    behavior_adaptation: dict[str, Any] | None = None,
) -> str:
    if behavior_contract and behavior_contract.get("status") == "closed":
        return _build_behavior_index_html(
            task,
            behavior_contract,
            behavior_adaptation or build_behavior_adaptation(task, behavior_contract),
        )
    profile = task_profile or _task_profile(task, capsules)
    task_text = (task or "New Task Pack")[:MAX_TASK_LEN]
    source_page = _source_page_content(snippet_context) if content_aware else {}
    page_title = str(source_page.get("title") or task_text)
    headline = str(source_page.get("headline") or "A runnable local project pack.")
    description = str(source_page.get("description") or "Built locally from the selected project material.")
    action = str(source_page.get("action") or profile["action"])
    status = str(source_page.get("status") or "Ready for local review.")
    fields = source_page.get("fields") if isinstance(source_page.get("fields"), list) else []
    source_cues = source_page.get("cards") or ([] if fields else _source_highlights(snippet_context) if content_aware else [])
    fallback_cues = [] if fields else [str(profile["output_label"])]
    cue_cards = "".join(
        f"<article><h3>{html.escape(str(cue.get('title') or 'Project detail'))}</h3><p>{html.escape(str(cue.get('body') or ''))}</p></article>"
        if isinstance(cue, dict)
        else f"<article><h3>{html.escape(str(cue))}</h3></article>"
        for cue in (source_cues[:4] or fallback_cues)
    )
    form_fields = _source_form_html(fields)
    cards_section = f'<div class="project-cards">{cue_cards}</div>' if cue_cards else ""
    project_class = "project-app with-cards" if cue_cards else "project-app"
    document_title = page_title if page_title == task_text else f"{page_title} | {task_text}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(document_title)}</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <main class="surface">
    <header>
      <p class="eyebrow">{html.escape(str(profile["output_label"]))}</p>
      <h1>{html.escape(page_title)}</h1>
      <p class="note">{html.escape(headline)}</p>
    </header>
    <section class="{project_class}" aria-label="Generated project">
      <div>
        <h2>{html.escape(headline)}</h2>
        <p>{html.escape(description)}</p>
        {form_fields}
        <button id="reweaveDemoButton" type="button" data-ready-message="{html.escape(action)} is ready for local follow-up.">{html.escape(action)}</button>
        <p id="reweaveDemoStatus">{html.escape(status)}</p>
      </div>
      {cards_section}
    </section>
    <p class="review-link"><a href="review.html">View build notes</a></p>
  </main>
  <script src="app.js"></script>
</body>
</html>
"""


def build_review_html(
    task: str,
    capsules: list[dict[str, Any]],
    *,
    content_aware: bool = False,
    snippet_context: dict[str, Any] | None = None,
    task_plan: dict[str, Any] | None = None,
) -> str:
    task_title = html.escape((task or "New Task Pack")[:MAX_TASK_LEN])
    plan = task_plan or _task_plan(_task_intent(task, capsules))
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
    plan_items = "".join(
        f"<li>{html.escape(str(item.get('path')))} — {html.escape(str(item.get('purpose')))}</li>"
        for item in plan["outputs"]
        if isinstance(item, dict)
    )
    reason_items = "".join(
        f"<li><strong>{html.escape(str(item.get('name') or 'Capsule'))}</strong> — {html.escape(str(item.get('reason') or 'Selected capsule'))}</li>"
        for item in plan["capsules"]
        if isinstance(item, dict)
    )
    tag_items = "".join(f"<li>{html.escape(tag)}</li>" for tag in (capsule_tags or ["layout", "copy", "logic"]))
    source_items = "".join(f"<li>{html.escape(name)}</li>" for name in (source_names or ["local Source Box"]))
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
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{task_title} · Review</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <main class="surface review-surface">
    <header>
      <p class="eyebrow">Reweave · provenance review</p>
      <h1>{task_title}</h1>
      <p class="note">Task Intent, capsule notes, and source excerpts live here so the generated page stays clean.</p>
      <p><a href="index.html">Back to generated page</a></p>
    </header>
    <section class="task-output" aria-label="Task Intent">
      <div>
        <p class="eyebrow">Task Intent</p>
        <h2>Planned outputs</h2>
        <ul>{plan_items}</ul>
        <h2>Capsule reasons</h2>
        <ul>{reason_items}</ul>
        <h2>Reused signals</h2>
        <ul>{tag_items}</ul>
        <h2>Source Boxes</h2>
        <ul>{source_items}</ul>
      </div>
      <aside>
        <strong>Trace files</strong>
        <ul>
          <li>task_intent.json</li>
          <li>task_plan.json</li>
          <li>capsules_used.json</li>
          <li>provenance.json</li>
          <li>snippets_used.json</li>
        </ul>
      </aside>
    </section>
    {excerpt_cards}
    <section class="capsules">{body}</section>
  </main>
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
                text = _clean_source_cue(raw)
                if not text:
                    continue
                if 3 <= len(text) <= 80 and text not in highlights:
                    highlights.append(text)
                if len(highlights) >= 6:
                    return highlights
    return highlights


def _source_page_content(snippet_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snippet_context, dict):
        return {}
    html_snippets: list[str] = []
    for cap in snippet_context.get("capsules") if isinstance(snippet_context.get("capsules"), list) else []:
        if not isinstance(cap, dict):
            continue
        for snip in cap.get("snippets") if isinstance(cap.get("snippets"), list) else []:
            if not isinstance(snip, dict):
                continue
            path = str(snip.get("relative_path") or "")
            if path.endswith((".html", ".htm")) or str(snip.get("language_hint") or "") == "html":
                html_snippets.append(str(snip.get("preview_excerpt") or ""))

    result: dict[str, Any] = {"cards": []}
    for excerpt in html_snippets:
        source = html.unescape(excerpt)
        title = _first_tag_text(source, "title")
        headline = _first_tag_text(source, "h1")
        paragraphs = _tag_texts(source, "p")
        actions = _tag_texts(source, "a") + _tag_texts(source, "button")
        if title and not result.get("title"):
            result["title"] = title
        if headline and not result.get("headline"):
            result["headline"] = headline
        description = next((text for text in paragraphs if text != title and text != headline), "")
        if description and not result.get("description"):
            result["description"] = description
        if actions and not result.get("action"):
            result["action"] = actions[0]
        status = _source_status(source)
        if not status:
            status = _first_tag_text(source, "aside")
        if status and not result.get("status"):
            result["status"] = status
        for heading, body in re.findall(r"<h[23][^>]*>(.*?)</h[23]>\s*<p[^>]*>(.*?)</p>", source, flags=re.IGNORECASE | re.DOTALL):
            card = {"title": _clean_source_cue(_strip_tags(heading)), "body": _clean_source_cue(_strip_tags(body))}
            if card["title"] and card["body"] and card not in result["cards"]:
                result["cards"].append(card)
        for article in re.findall(r"<article[^>]*>(.*?)</article>", source, flags=re.IGNORECASE | re.DOTALL):
            title = _first_tag_text(article, "h2") or _first_tag_text(article, "h3") or _first_tag_text(article, "strong")
            body = _first_tag_text(article, "p")
            card = {"title": title, "body": body}
            if title and body and card not in result["cards"]:
                result["cards"].append(card)
        fields = _source_form_fields(source)
        if fields and not result.get("fields"):
            result["fields"] = fields
        if result.get("title") and result.get("headline") and result["cards"]:
            break
    return result


def _tag_texts(source: str, tag: str) -> list[str]:
    return [text for raw in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", source, flags=re.IGNORECASE | re.DOTALL) if (text := _clean_source_cue(_strip_tags(raw)))]


def _first_tag_text(source: str, tag: str) -> str:
    texts = _tag_texts(source, tag)
    return texts[0] if texts else ""


def _source_status(source: str) -> str:
    match = re.search(
        r"<(?:p|div)[^>]*(?:class|id)=[\"'][^\"']*status[^\"']*[\"'][^>]*>(.*?)</(?:p|div)>",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return _clean_source_cue(_strip_tags(match.group(1))) if match else ""


def _source_form_fields(source: str) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for block in re.findall(r"<label[^>]*>(.*?)</label>", source, flags=re.IGNORECASE | re.DOTALL):
        label = _clean_source_cue(block.split("<", 1)[0])
        control = re.search(r"<(input|select)([^>]*)>(.*?)</select>|<(input)([^>]*)/?>", block, flags=re.IGNORECASE | re.DOTALL)
        if not label or not control:
            continue
        tag = (control.group(1) or control.group(4) or "").lower()
        attrs = control.group(2) or control.group(5) or ""
        placeholder_match = re.search(r"placeholder=[\"']([^\"']+)[\"']", attrs, flags=re.IGNORECASE)
        options = _tag_texts(control.group(3) or "", "option") if tag == "select" else []
        fields.append(
            {
                "label": label,
                "kind": "select" if tag == "select" else "input",
                "placeholder": placeholder_match.group(1) if placeholder_match else "",
                "options": options[:6],
            }
        )
    return fields[:4]


def _source_form_html(fields: list[dict[str, Any]]) -> str:
    controls: list[str] = []
    for field in fields:
        label = html.escape(str(field.get("label") or "Details"))
        if field.get("kind") == "select":
            options = "".join(f"<option>{html.escape(str(option))}</option>" for option in field.get("options") or [])
            controls.append(f"<label>{label}<select data-reweave-field>{options}</select></label>")
        else:
            placeholder = html.escape(str(field.get("placeholder") or ""))
            controls.append(f"<label>{label}<input data-reweave-field type=\"text\" placeholder=\"{placeholder}\" /></label>")
    return f"<div class=\"project-form\">{''.join(controls)}</div>" if controls else ""


def _strip_tags(raw: str) -> str:
    return re.sub(r"<[^>]+>", " ", raw)


def _clean_source_cue(raw: str) -> str:
    text = re.sub(r"\s+", " ", str(raw)).strip(" -_•\t")
    text = text.lstrip("#").strip()
    if not text:
        return ""
    if text.startswith("//"):
        return ""
    if any(token in text for token in ("{", "}", ";", "<", ">", "=>")):
        return ""
    if any(token in text for token in ("document.", "window.", "querySelector", "getElementById", "addEventListener")):
        return ""
    if re.search(r"\b(margin|padding|font-family|display|grid-template|background|color)\s*:", text):
        return ""
    return text


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
    accent = next((c for c in colors if c.lower() not in skip and _hex_luminance(c) < 0.55), "#21352a")
    return {"accent": accent, "soft": "#f8fbf8"}


def _hex_luminance(color: str) -> float:
    raw = color.lstrip("#")
    if len(raw) == 3:
        raw = "".join(char * 2 for char in raw)
    if len(raw) != 6:
        return 1.0
    red, green, blue = (int(raw[index : index + 2], 16) / 255 for index in range(0, 6, 2))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def build_styles_css(
    snippet_context: dict[str, Any] | None = None,
    behavior_contract: dict[str, Any] | None = None,
) -> str:
    if behavior_contract and behavior_contract.get("status") == "closed":
        style = _behavior_file(behavior_contract, "style") or {}
        source = str(style.get("content") or "")
        return source.rstrip() + "\n\n.reweave-build-notes { margin: 1rem; font: 14px/1.4 system-ui, sans-serif; }\n"
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
.project-app { display: grid; grid-template-columns: minmax(0, 1fr); gap: 1rem; margin-top: 1rem; padding: 1rem; border: 1px solid #d8e3dc; border-radius: 10px; background: var(--soft); }
.project-app.with-cards { grid-template-columns: minmax(0, 0.9fr) minmax(260px, 1.1fr); }
.project-app h2 { margin: 0 0 0.5rem; }
.project-app button { min-height: 40px; border: 0; border-radius: 6px; padding: 0 0.85rem; background: var(--accent); color: #fff; font: inherit; cursor: pointer; }
#reweaveDemoStatus { margin: 0.75rem 0 0; color: #5f6f62; font-size: 0.9rem; }
.project-form { display: grid; gap: 0.7rem; margin: 1rem 0; }
.project-form label { display: grid; gap: 0.35rem; color: #5f6f62; font-size: 0.9rem; }
.project-form input, .project-form select { box-sizing: border-box; min-height: 40px; width: 100%; border: 1px solid #d8e3dc; border-radius: 6px; padding: 0 0.7rem; background: #fff; color: inherit; font: inherit; }
.project-cards { display: grid; gap: 0.65rem; }
.project-cards article { border: 1px solid #d8e3dc; border-radius: 8px; background: #fff; padding: 0.85rem; }
.project-cards p { margin: 0.35rem 0 0; color: #5f6f62; font-size: 0.9rem; }
.source-excerpts { margin-top: 1rem; }
.excerpt-card { border: 1px solid #e8dfd0; border-radius: 10px; background: #fff; padding: 0.85rem; margin: 0.75rem 0; }
.excerpt-card h3 { margin: 0; font-size: 0.95rem; }
.excerpt-card p { margin: 0.25rem 0 0.65rem; color: #6b5d4a; font-size: 0.8rem; }
.excerpt-card pre { max-height: 220px; overflow: auto; background: #faf7f0; border-radius: 6px; padding: 0.75rem; }
.capsule-card { background: #fff; border: 1px solid #e8dfd0; border-radius: 10px; padding: 1rem; margin: 1rem 0; }
.capsule-card .type { font-size: 0.75rem; color: #a67c3d; }
.capsule-card pre { background: #faf7f0; padding: 0.75rem; border-radius: 6px; overflow: auto; }
.empty { color: #6b5d4a; }
@media (max-width: 680px) { .task-output, .project-app.with-cards { grid-template-columns: 1fr; } .task-output aside { border-left: 0; border-top: 1px solid #e8dfd0; padding-left: 0; padding-top: 1rem; } }
"""
    return css.replace("__ACCENT__", tokens["accent"]).replace("__SOFT__", tokens["soft"])


def build_app_js(behavior_contract: dict[str, Any] | None = None) -> str:
    if behavior_contract and behavior_contract.get("status") == "closed":
        script = _behavior_file(behavior_contract, "script") or {}
        return str(script.get("content") or "")
    return """document.addEventListener('DOMContentLoaded', function () {
  const button = document.getElementById('reweaveDemoButton');
  const status = document.getElementById('reweaveDemoStatus');
  if (button && status) {
    button.addEventListener('click', function () {
      const details = Array.from(document.querySelectorAll('[data-reweave-field]'))
        .map(function (field) { return field.value.trim(); })
        .filter(Boolean);
      status.textContent = details.length
        ? button.textContent + ' ready for ' + details.join(' · ') + '.'
        : (button.dataset.readyMessage || 'Action is ready for local follow-up.');
    });
  }
});
"""
