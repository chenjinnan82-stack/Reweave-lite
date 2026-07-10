"""Optional local LLM pass for public Small Project Pack demos."""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from pimos_lite.reweave_quality_gate import build_quality_gate, js_syntax_ok

PACK_FILES = ("index.html", "styles.css", "app.js")


def _json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _snippet_text(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    chunks: list[str] = []
    for cap in context.get("capsules") if isinstance(context.get("capsules"), list) else []:
        if not isinstance(cap, dict):
            continue
        chunks.append(f"Capsule: {cap.get('name') or cap.get('capsule_id')}")
        for snip in cap.get("snippets") if isinstance(cap.get("snippets"), list) else []:
            if not isinstance(snip, dict):
                continue
            rel = snip.get("relative_path") or "source"
            excerpt = str(snip.get("preview_excerpt") or "")[:1000]
            chunks.append(f"[{rel}]\n{excerpt}")
    return "\n\n".join(chunks)[:5000]


def build_prompt(task: str, capsules: list[dict[str, Any]], snippet_context: dict[str, Any] | None) -> str:
    capsule_lines = "\n".join(
        f"- {cap.get('name')} ({cap.get('type')}): {cap.get('role')}" for cap in capsules[:4]
    )
    snippets = _snippet_text(snippet_context)
    return f"""Build a small, self-contained web project pack from the selected Reweave capsules.

Task:
{task}

Selected capsules:
{capsule_lines}

Source snippets:
{snippets}

Rules:
- Return exactly three file blocks.
- Do not use external CDNs or missing local files.
- index.html may only reference styles.css and app.js.
- Always include an app.js block, even if it only wires a tiny local interaction.
- Keep it small, complete, and runnable by opening index.html.

Format:
--- index.html ---
<!doctype html>
...
--- styles.css ---
...
--- app.js ---
...
"""


def parse_file_blocks(text: str) -> dict[str, str]:
    matches = list(
        re.finditer(
            r"^\s*(?:---|###)\s*`?(index\.html|styles\.css|app\.js)`?\s*(?:---|:)?\s*$",
            text,
            re.MULTILINE,
        )
    )
    files: dict[str, str] = {}
    for i, match in enumerate(matches):
        name = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        content = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", content)
        content = re.sub(r"\s*```$", "", content).strip()
        if content:
            files[name] = content + "\n"
    return files


def _local_assets_ok(html: str) -> bool:
    allowed = {"styles.css", "app.js"}
    for asset in re.findall(r"""(?:href|src)=["']([^"']+)["']""", html):
        if asset.startswith(("http://", "https://", "data:", "#")):
            return False
        if asset.startswith("/"):
            return False
        if asset not in allowed:
            return False
    return True


def _normalize_html_assets(html: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    original = html
    html = re.sub(r"<link\b[^>]*rel=[\"']?stylesheet[\"']?[^>]*>", "", html, flags=re.I)
    html = re.sub(r"<script\b[^>]*src=[\"'][^\"']+[\"'][^>]*>\s*</script>", "", html, flags=re.I)
    if "</head>" in html.lower():
        html = re.sub(r"</head>", '  <link rel="stylesheet" href="styles.css">\n</head>', html, flags=re.I, count=1)
    else:
        html = '<link rel="stylesheet" href="styles.css">\n' + html
    if "</body>" in html.lower():
        html = re.sub(r"</body>", '  <script src="app.js"></script>\n</body>', html, flags=re.I, count=1)
    else:
        html += '\n<script src="app.js"></script>\n'
    if html != original:
        warnings.append("normalized_html_assets")
    return html, warnings


def normalize_files(files: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    files = dict(files)
    warnings: list[str] = []
    if files.get("index.html"):
        files["index.html"], asset_warnings = _normalize_html_assets(files["index.html"])
        warnings.extend(asset_warnings)
    if not files.get("styles.css", "").strip():
        files["styles.css"] = "body { font-family: system-ui, sans-serif; }\n"
        warnings.append("filled_missing_styles_css")
    if not files.get("app.js", "").strip():
        files["app.js"] = "document.addEventListener('DOMContentLoaded', function () { console.log('[Reweave] local model pack ready'); });\n"
        warnings.append("filled_missing_app_js")
    return files, warnings


def validate_files(files: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for name in PACK_FILES:
        if not files.get(name, "").strip():
            errors.append(f"missing:{name}")
    html = files.get("index.html", "")
    css = files.get("styles.css", "")
    js = files.get("app.js", "")
    if html and "<html" not in html.lower():
        errors.append("index_missing_html")
    if html and not _local_assets_ok(html):
        errors.append("index_has_missing_or_external_assets")
    if css and (css.count("{") != css.count("}") or not re.search(r"[^{}]+\{[^{}]+\}", css, re.S)):
        errors.append("css_invalid")
    if js and not js_syntax_ok(js):
        errors.append("js_invalid")
    return errors


def build_bounded_adaptation_prompt(task: str, adaptation: dict[str, Any]) -> str:
    allowed = {
        "text_slots": adaptation.get("allowed_text_slots") or [],
        "style_variables": adaptation.get("allowed_style_variables") or [],
    }
    return f"""Adapt a closed Reweave frontend module to the task without changing behavior.

Task:
{task}

Allowed targets:
{json.dumps(allowed, ensure_ascii=False)}

Return one JSON object only with two arrays named text_patches and style_patches.
Each text patch must contain slot_id and a task-specific value.
Each style patch must contain name and a hexadecimal color value.

Rules:
- Use only listed slot_id and variable names.
- The only text patch keys are exactly "slot_id" and "value"; never rename "value".
- Rewrite at least two text slots with wording specific to the task domain.
- Every returned value must differ from its current value.
- Use an empty style_patches array when no style variable is listed.
- Plain text only; no HTML.
- CSS values must be hex colors.
- Do not return JavaScript, DOM ids, selectors, files, or explanations.
"""


def parse_bounded_adaptation(text: str, adaptation: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("bounded_adaptation_missing_json")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict) or set(data) - {"text_patches", "style_patches"}:
        raise ValueError("bounded_adaptation_invalid_shape")
    slots = {
        str(item.get("slot_id")): item
        for item in adaptation.get("allowed_text_slots", [])
        if isinstance(item, dict) and item.get("slot_id")
    }
    variables = {
        str(item.get("name"))
        for item in adaptation.get("allowed_style_variables", [])
        if isinstance(item, dict) and item.get("name")
    }
    text_patches: list[dict[str, str]] = []
    seen_slots: set[str] = set()
    for item in data.get("text_patches") or []:
        if not isinstance(item, dict):
            raise ValueError("bounded_adaptation_invalid_text_patch")
        slot_id = str(item.get("slot_id") or "")
        value = str(item.get("value") or "").strip()
        if slot_id not in slots or slot_id in seen_slots or not (1 <= len(value) <= 160):
            raise ValueError("bounded_adaptation_disallowed_text_patch")
        if any(char in value for char in "<>\r\n"):
            raise ValueError("bounded_adaptation_text_must_be_plain")
        if value.casefold() in {"new plain text", "new text", "placeholder", "todo", "example"}:
            raise ValueError("bounded_adaptation_placeholder_text")
        if value == str(slots[slot_id].get("value") or ""):
            continue
        seen_slots.add(slot_id)
        text_patches.append({"slot_id": slot_id, "value": value})
    style_patches: list[dict[str, str]] = []
    seen_variables: set[str] = set()
    for item in data.get("style_patches") or []:
        if not isinstance(item, dict):
            raise ValueError("bounded_adaptation_invalid_style_patch")
        name = str(item.get("name") or "")
        value = str(item.get("value") or "")
        if name not in variables or name in seen_variables or not re.fullmatch(r"#[0-9a-fA-F]{3,8}", value):
            raise ValueError("bounded_adaptation_disallowed_style_patch")
        current = next(
            str(item.get("value") or "")
            for item in adaptation.get("allowed_style_variables", [])
            if isinstance(item, dict) and item.get("name") == name
        )
        if value.casefold() == current.casefold():
            continue
        seen_variables.add(name)
        style_patches.append({"name": name, "value": value})
    if len(text_patches) > 8 or len(style_patches) > 4 or not (text_patches or style_patches):
        raise ValueError("bounded_adaptation_patch_limit")
    return {"text_patches": text_patches, "style_patches": style_patches}


def _replace_text_slot(source: str, slot: dict[str, Any], value: str) -> str:
    tag = str(slot.get("tag") or "")
    target = int(slot.get("occurrence") or 0)
    pattern = re.compile(rf"(<{tag}\b[^>]*>)([^<>]+)(</{tag}>)", flags=re.IGNORECASE)
    current = -1

    def replace(match: re.Match[str]) -> str:
        nonlocal current
        current += 1
        return f"{match.group(1)}{html.escape(value)}{match.group(3)}" if current == target else match.group(0)

    updated = pattern.sub(replace, source)
    if current < target:
        raise ValueError("bounded_adaptation_slot_missing")
    return updated


def apply_bounded_behavior_adaptation(out: Path, response: str, *, model: str) -> dict[str, Any]:
    adaptation_path = out / "behavior_adaptation.json"
    adaptation = _json(adaptation_path)
    contract = _json(out / "behavior_contract.json")
    task_plan = _json(out / "task_plan.json")
    task_pack = _json(out / "task_pack.json")
    patches = parse_bounded_adaptation(response, adaptation)
    index_path, styles_path = out / "index.html", out / "styles.css"
    quality_path, task_pack_path = out / "quality_gate.json", out / "task_pack.json"
    original_files = {
        path: path.read_bytes()
        for path in (index_path, styles_path, adaptation_path, quality_path, task_pack_path)
    }
    original_index, original_styles = index_path.read_text(encoding="utf-8"), styles_path.read_text(encoding="utf-8")
    updated_index, updated_styles = original_index, original_styles
    slots = {
        str(item.get("slot_id")): item
        for item in adaptation.get("allowed_text_slots", [])
        if isinstance(item, dict) and item.get("slot_id")
    }
    for patch in patches["text_patches"]:
        updated_index = _replace_text_slot(updated_index, slots[patch["slot_id"]], patch["value"])
    for patch in patches["style_patches"]:
        pattern = re.compile(rf"({re.escape(patch['name'])}\s*:\s*)#[0-9a-fA-F]{{3,8}}\b")
        updated_styles, count = pattern.subn(lambda match: match.group(1) + patch["value"], updated_styles, count=1)
        if count != 1:
            raise ValueError("bounded_adaptation_style_variable_missing")
    updated_adaptation = dict(adaptation)
    updated_adaptation["llm_adaptation"] = {"status": "applied", "model": model, **patches}
    try:
        index_path.write_text(updated_index, encoding="utf-8")
        styles_path.write_text(updated_styles, encoding="utf-8")
        _write_json(adaptation_path, updated_adaptation)
        gate = build_quality_gate(
            out,
            str(task_pack.get("task") or ""),
            task_plan,
            content_aware=True,
            behavior_contract=contract,
            behavior_adaptation=updated_adaptation,
        )
        if gate.get("status") != "passed":
            raise ValueError("bounded_adaptation_quality_gate_failed")
        _write_json(quality_path, gate)
        task_pack["quality_gate"] = gate
        task_pack["behavior_reuse"]["bounded_llm_adaptation"] = "applied"
        _write_json(task_pack_path, task_pack)
    except Exception:
        for path, content in original_files.items():
            path.write_bytes(content)
        raise
    return patches


def _ollama_generate_url(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("ollama_url_must_be_localhost")
    return base_url.rstrip("/") + "/api/generate"


def call_ollama(prompt: str, *, model: str, base_url: str, timeout: float) -> str:
    url = _ollama_generate_url(base_url)
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "seed": 7},
        }
    ).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return str(payload.get("response") or "")


def apply_ollama_pack(
    out: Path,
    *,
    task: str,
    selected_capsules: list[dict[str, Any]],
    snippet_context: dict[str, Any] | None,
    model: str,
    base_url: str,
    timeout: float = 60,
    require: bool = False,
    bounded_only: bool = False,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "enabled": True,
        "provider": "ollama",
        "model": model,
        "local_http_call": False,
        "external_network_call": False,
        "source_project_write": False,
        "applied": False,
        "fallback_used": True,
    }
    task_pack = _json(out / "task_pack.json") if (out / "task_pack.json").is_file() else {}
    behavior = task_pack.get("behavior_reuse") if isinstance(task_pack.get("behavior_reuse"), dict) else {}
    try:
        _ollama_generate_url(base_url)
    except ValueError as exc:
        meta["error"] = str(exc)
        if require:
            raise SystemExit(f"llm generation failed: {meta['error']}") from exc
    if not meta.get("error"):
        if behavior.get("status") == "enabled":
            try:
                meta["local_http_call"] = True
                adaptation = _json(out / "behavior_adaptation.json")
                response = call_ollama(
                    build_bounded_adaptation_prompt(task, adaptation),
                    model=model,
                    base_url=base_url,
                    timeout=timeout,
                )
                patches = apply_bounded_behavior_adaptation(out, response, model=model)
                meta.update(
                    {
                        "applied": True,
                        "fallback_used": False,
                        "mode": "bounded_behavior_adaptation",
                        "text_patch_count": len(patches["text_patches"]),
                        "style_patch_count": len(patches["style_patches"]),
                    }
                )
            except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
                meta["error"] = str(exc)[:240]
                meta["mode"] = "bounded_behavior_adaptation"
                if require:
                    raise SystemExit(f"llm generation failed: {meta['error']}") from exc
        elif bounded_only:
            meta["mode"] = "bounded_behavior_adaptation"
            meta["error"] = "no_closed_behavior_module"
        else:
            try:
                meta["local_http_call"] = True
                response = call_ollama(
                    build_prompt(task, selected_capsules, snippet_context),
                    model=model,
                    base_url=base_url,
                    timeout=timeout,
                )
                files, warnings = normalize_files(parse_file_blocks(response))
                errors = validate_files(files)
                if errors:
                    raise ValueError("invalid_llm_output:" + ",".join(errors))
                for name, content in files.items():
                    (out / name).write_text(content, encoding="utf-8")
                meta.update({"applied": True, "fallback_used": False, "normalizations": warnings})
            except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
                meta["error"] = str(exc)[:240]
                if require:
                    raise SystemExit(f"llm generation failed: {meta['error']}") from exc

    for name in ("provenance.json", "task_pack.json"):
        path = out / name
        if path.is_file():
            data = _json(path)
            data["llm_generation"] = meta
            if name == "provenance.json":
                cag = data.get("content_aware_generate") if isinstance(data.get("content_aware_generate"), dict) else {}
                cag["llm_called"] = bool(meta["local_http_call"])
                cag["model_call"] = bool(meta["local_http_call"])
                cag["network_call"] = bool(meta["local_http_call"])
                data["content_aware_generate"] = cag
                if meta.get("applied") and meta.get("mode") == "bounded_behavior_adaptation":
                    behavior_meta = data.get("behavior_reuse") if isinstance(data.get("behavior_reuse"), dict) else {}
                    behavior_meta["bounded_llm_adaptation"] = "applied"
                    data["behavior_reuse"] = behavior_meta
            _write_json(path, data)
    return meta
