"""Optional local LLM pass for public Small Project Pack demos."""

from __future__ import annotations

import json
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import subprocess
import shutil
from pathlib import Path
from typing import Any

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


def _js_syntax_ok(js: str) -> bool:
    node = shutil.which("node")
    if not node:
        return bool(js.strip()) and not js.rstrip().endswith((".", ",", "=>"))
    with tempfile.TemporaryDirectory(prefix="reweave-js-check-") as tmp:
        path = Path(tmp) / "app.js"
        path.write_text(js, encoding="utf-8")
        return subprocess.run([node, "--check", str(path)], capture_output=True, text=True).returncode == 0


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
    if js and not _js_syntax_ok(js):
        errors.append("js_invalid")
    return errors


def call_ollama(prompt: str, *, model: str, base_url: str, timeout: float) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("ollama_url_must_be_localhost")
    url = base_url.rstrip("/") + "/api/generate"
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
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "enabled": True,
        "provider": "ollama",
        "model": model,
        "local_http_call": True,
        "external_network_call": False,
        "source_project_write": False,
        "applied": False,
        "fallback_used": True,
    }
    try:
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
                cag["llm_called"] = bool(meta["applied"])
                cag["model_call"] = bool(meta["applied"])
                cag["network_call"] = bool(meta["applied"])
                data["content_aware_generate"] = cag
            _write_json(path, data)
    return meta
