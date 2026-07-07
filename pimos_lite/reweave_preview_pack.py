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
) -> str:
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
    title = html.escape((task or "Reweave preview")[:MAX_TASK_LEN])
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
  <title>{title}</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <main class="surface">
    <header>
      <p class="eyebrow">Reweave · local preview</p>
      <h1>{title}</h1>
      <p class="note">{note}</p>
    </header>
    <section class="capsules">{body}</section>
  </main>
  <script src="app.js"></script>
</body>
</html>
"""


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


def _build_styles_css() -> str:
    return """body {
  margin: 0;
  font-family: ui-sans-serif, system-ui, sans-serif;
  background: #fdfcf8;
  color: #2b261c;
}
.surface { max-width: 720px; margin: 2rem auto; padding: 0 1.25rem; }
.eyebrow { letter-spacing: 0.08em; text-transform: uppercase; font-size: 0.75rem; color: #8a7355; }
.note { color: #6b5d4a; font-size: 0.9rem; }
.capsule-card { background: #fff; border: 1px solid #e8dfd0; border-radius: 10px; padding: 1rem; margin: 1rem 0; }
.capsule-card .type { font-size: 0.75rem; color: #a67c3d; }
.capsule-card pre { background: #faf7f0; padding: 0.75rem; border-radius: 6px; overflow: auto; }
.empty { color: #6b5d4a; }
"""


def _build_app_js() -> str:
    return """document.addEventListener('DOMContentLoaded', function () {
  console.log('[Reweave] local preview shell ready');
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
        "capsule_ids": [c.get("id") for c in capsules],
        "capsules": [_capsule_provenance_entry(c) for c in capsules],
        "source_boxes": payload.get("sourceBoxes") if isinstance(payload.get("sourceBoxes"), list) else [],
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

    files = ["index.html", "styles.css", "app.js", "capsules_used.json", "provenance.json"]
    _write_text(root / "index.html", _build_index_html(task, capsules, content_aware=content_aware_enabled))
    _write_text(root / "styles.css", _build_styles_css())
    _write_text(root / "app.js", _build_app_js())
    _write_text(root / "capsules_used.json", json.dumps(capsules_used, indent=2, ensure_ascii=False) + "\n")
    _write_text(root / "provenance.json", json.dumps(provenance, indent=2, ensure_ascii=False) + "\n")

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
                    "capsules_used.json",
                    "provenance.json",
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
