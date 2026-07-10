"""Reweave preview package v0 — local preview output in app state only."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pimos_lite.reweave_capsule_warehouse import get_capsule, is_generate_eligible, list_capsules
from pimos_lite.reweave_quality_gate import build_quality_gate as _quality_gate
from pimos_lite.reweave_project_renderer import build_app_js as _build_app_js
from pimos_lite.reweave_project_renderer import build_behavior_adaptation as _build_behavior_adaptation
from pimos_lite.reweave_project_renderer import build_index_html as _build_index_html
from pimos_lite.reweave_project_renderer import build_preview_readme as _build_preview_readme
from pimos_lite.reweave_project_renderer import build_review_html as _build_review_html
from pimos_lite.reweave_project_renderer import build_styles_css as _build_styles_css
from pimos_lite.reweave_snippet_context import (
    CONTEXT_LIMITS,
    build_snippet_context,
    build_snippets_used_manifest,
    count_snippets,
)
from pimos_lite.reweave_source_registry import state_dir
from pimos_lite.reweave_task_intent import MAX_TASK_LEN
from pimos_lite.reweave_task_intent import build_task_intent as _task_intent
from pimos_lite.reweave_task_intent import build_task_profile as _task_profile
from pimos_lite.reweave_task_plan import build_task_plan as _task_plan

PREVIEW_SCHEMA_VERSION = 1


def preview_acceptance(task_pack: dict[str, Any]) -> dict[str, str]:
    quality_gate = task_pack.get("quality_gate") if isinstance(task_pack.get("quality_gate"), dict) else {}
    quality_status = str(quality_gate.get("status") or "")
    if quality_status == "failed":
        return {"verdict": "rejected", "reason": "quality_gate_failed"}
    if quality_status != "passed":
        return {"verdict": "needs_review", "reason": "quality_gate_not_reported"}
    behavior = task_pack.get("behavior_reuse") if isinstance(task_pack.get("behavior_reuse"), dict) else {}
    if behavior.get("status") != "enabled":
        return {"verdict": "needs_review", "reason": "closed_behavior_unavailable"}
    validation = task_pack.get("behavior_validation") if isinstance(task_pack.get("behavior_validation"), dict) else {}
    if validation.get("status") == "passed":
        return {"verdict": "usable", "reason": "runtime_behavior_verified"}
    if validation.get("status") == "failed":
        return {"verdict": "rejected", "reason": "runtime_behavior_failed"}
    return {"verdict": "needs_review", "reason": "runtime_validation_required"}


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


def _build_task_pack(
    task: str,
    capsules: list[dict[str, Any]],
    *,
    task_intent: dict[str, Any],
    task_plan: dict[str, Any],
    task_profile: dict[str, object],
    selection_mode: str = "selected_capsules",
) -> dict[str, Any]:
    capsule_ids = [str(c.get("id") or "") for c in capsules if c.get("id")]
    output_kinds = list(task_profile["output_kinds"])
    capsules_used = list(task_intent["retrieved_capsules"])
    return {
        "schema_version": "reweave_task_pack.v1",
        "mode": "task_pack_preview",
        "package_kind": "small_project_pack",
        "task_profile": task_profile["id"],
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
        snippet_context = build_snippet_context(capsule_ids, task=task)

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
    task_intent = _task_intent(task, capsules)
    task_plan = _task_plan(task_intent)
    candidate_contract = (
        snippet_context.get("behavior_contract")
        if isinstance(snippet_context, dict) and isinstance(snippet_context.get("behavior_contract"), dict)
        else None
    )
    behavior_contract = (
        candidate_contract
        if payload.get("reuseBehavior") is True and candidate_contract and candidate_contract.get("status") == "closed"
        else None
    )
    behavior_adaptation = _build_behavior_adaptation(task, behavior_contract) if behavior_contract else None
    if behavior_contract is not None:
        selection = behavior_contract.get("selection") if isinstance(behavior_contract.get("selection"), dict) else {}
        task_intent["behavior_reuse"] = {
            "status": "selected",
            "mode": behavior_contract.get("mode"),
            "interaction_mode": behavior_contract.get("interaction_mode", "user_event"),
            "entry_path": behavior_contract.get("entry_path"),
            "capsule_id": selection.get("capsule_id"),
            "reason": selection.get("reason"),
        }
        task_plan["composer"] = {
            "mode": "closed_frontend_module",
            "inputs": ["task_intent.json", "task_plan.json", "behavior_contract.json", "behavior_adaptation.json", "capsules_used.json"],
            "optional_inputs": ["snippets_used.json"],
        }
        task_plan["behavior_contract_path"] = "behavior_contract.json"
        task_plan["behavior_adaptation_path"] = "behavior_adaptation.json"
        task_plan["acceptance"].append(
            "observe declared passive state change"
            if behavior_contract.get("interaction_mode") == "passive_timer"
            else "run declared behavior interactions"
        )
    task_profile = _task_profile(task, capsules, task_intent=task_intent)
    task_pack = _build_task_pack(
        task,
        capsules,
        task_intent=task_intent,
        task_plan=task_plan,
        task_profile=task_profile,
        selection_mode=selection_mode,
    )
    if behavior_contract is not None:
        task_pack["behavior_contract_path"] = "behavior_contract.json"
        task_pack["behavior_adaptation_path"] = "behavior_adaptation.json"
        task_pack["behavior_reuse"] = {
            "status": "enabled",
            "mode": behavior_contract.get("mode"),
            "interaction_mode": behavior_contract.get("interaction_mode", "user_event"),
            "entry_path": behavior_contract.get("entry_path"),
            "runtime_validation": "required",
            "validation_kind": (
                "observe_state_change"
                if behavior_contract.get("interaction_mode") == "passive_timer"
                else "execute_user_event"
            ),
            "adaptation_mode": behavior_adaptation.get("mode") if behavior_adaptation else None,
        }
        provenance["behavior_reuse"] = {
            "status": "enabled",
            "mode": behavior_contract.get("mode"),
            "interaction_mode": behavior_contract.get("interaction_mode", "user_event"),
            "contract_path": "behavior_contract.json",
            "adaptation_path": "behavior_adaptation.json",
            "source_read_at_generate_time": False,
            "source_project_write": False,
        }
    elif payload.get("reuseBehavior") is True:
        task_pack["behavior_reuse"] = {
            "status": "unavailable",
            "reason": "no_closed_frontend_module",
        }
        provenance["behavior_reuse"] = dict(task_pack["behavior_reuse"])
    files = ["index.html", "review.html", "styles.css", "app.js", "task_intent.json", "task_plan.json", "task_pack.json", "capsules_used.json", "provenance.json", "summary.md"]
    _write_text(
        root / "index.html",
        _build_index_html(
            task,
            capsules,
            content_aware=content_aware_enabled,
            snippet_context=snippet_context,
            task_profile=task_profile,
            behavior_contract=behavior_contract,
            behavior_adaptation=behavior_adaptation,
        ),
    )
    _write_text(
        root / "review.html",
        _build_review_html(
            task,
            capsules,
            content_aware=content_aware_enabled,
            snippet_context=snippet_context,
            task_plan=task_plan,
        ),
    )
    _write_text(
        root / "styles.css",
        _build_styles_css(snippet_context if content_aware_enabled else None, behavior_contract=behavior_contract),
    )
    _write_text(root / "app.js", _build_app_js(behavior_contract))
    _write_text(root / "task_intent.json", json.dumps(task_intent, indent=2, ensure_ascii=False) + "\n")
    _write_text(root / "task_plan.json", json.dumps(task_plan, indent=2, ensure_ascii=False) + "\n")
    _write_text(root / "capsules_used.json", json.dumps(capsules_used, indent=2, ensure_ascii=False) + "\n")
    _write_text(root / "provenance.json", json.dumps(provenance, indent=2, ensure_ascii=False) + "\n")
    _write_text(root / "summary.md", _build_summary_md(task, capsules))
    if behavior_contract is not None:
        _write_text(root / "behavior_contract.json", json.dumps(behavior_contract, indent=2, ensure_ascii=False) + "\n")
        _write_text(root / "behavior_adaptation.json", json.dumps(behavior_adaptation, indent=2, ensure_ascii=False) + "\n")
        files.append("behavior_contract.json")
        files.append("behavior_adaptation.json")

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

    quality_gate = _quality_gate(
        root,
        task,
        task_plan,
        content_aware=content_aware_enabled,
        behavior_contract=behavior_contract,
        behavior_adaptation=behavior_adaptation,
    )
    task_pack["quality_gate"] = quality_gate
    _write_text(root / "task_pack.json", json.dumps(task_pack, indent=2, ensure_ascii=False) + "\n")
    _write_text(root / "quality_gate.json", json.dumps(quality_gate, indent=2, ensure_ascii=False) + "\n")
    files.append("quality_gate.json")
    if quality_gate["status"] != "passed":
        shutil.rmtree(root, ignore_errors=True)
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
    if behavior_contract is not None:
        stats["behaviorReuse"] = "Closed frontend module"

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


def attach_behavior_validation(preview_path: str | Path, receipt: dict[str, Any]) -> dict[str, Any]:
    """Persist one runtime validation receipt beside its preview package."""
    root = Path(preview_path).resolve()
    task_pack_path = root / "task_pack.json"
    provenance_path = root / "provenance.json"
    task_pack = json.loads(task_pack_path.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    task_pack["behavior_validation_path"] = "behavior_validation.json"
    task_pack["behavior_validation"] = receipt
    provenance["behavior_validation_path"] = "behavior_validation.json"
    provenance["behavior_validation"] = receipt
    _write_text(root / "behavior_validation.json", json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
    _write_text(task_pack_path, json.dumps(task_pack, indent=2, ensure_ascii=False) + "\n")
    _write_text(provenance_path, json.dumps(provenance, indent=2, ensure_ascii=False) + "\n")
    return {"taskPack": task_pack, "provenance": provenance}


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
