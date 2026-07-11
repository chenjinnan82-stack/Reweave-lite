"""Lumo Lite local-state Reweave engine (P15 read-only path)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pimos_lite.reweave_capsule_content import enrich_capsule_content as enrich_local_capsule_content
from pimos_lite.reweave_capsule_content import get_capsule_content as get_local_capsule_content
from pimos_lite.reweave_capsule_content import load_capsule_content
from pimos_lite.reweave_capsule_draft import draft_capsules, list_draft_lights
from pimos_lite.reweave_capsule_warehouse import get_capsule as get_local_capsule
from pimos_lite.reweave_capsule_warehouse import list_capsules as list_local_capsules
from pimos_lite.reweave_capsule_warehouse import promote_source_drafts as promote_local_drafts
from pimos_lite.reweave_capsule_warehouse import is_generate_eligible
from pimos_lite.reweave_preview_pack import build_preview_package
from pimos_lite.reweave_preview_pack import attach_behavior_validation
from pimos_lite.reweave_preview_pack import attach_react_runtime_validation
from pimos_lite.reweave_preview_pack import preview_acceptance
from pimos_lite.reweave_behavior_runtime import validate_preview_behavior, validate_react_preview_behavior
from pimos_lite.reweave_lumo_lite_artifacts import (
    collect_lumo_lite_artifacts,
    get_lumo_lite_artifact,
    get_lumo_lite_artifact_path,
)
from pimos_lite.reweave_lumo_lite_state import (
    capsule_warehouse_block,
    load_lumo_lite_runtime_state,
    lumo_lite_capsule_warehouse,
    lumo_lite_source_boxes,
    map_capsule_warehouse_to_reweave_capsules,
)
from pimos_lite.reweave_llm_pack import apply_ollama_pack
from pimos_lite.reweave_source_registry import add_source_box, get_source_box, list_source_boxes
from pimos_lite.reweave_source_scanner import list_summary_lights
from pimos_lite.reweave_source_scanner import scan_source_box as execute_source_scan
from pimos_lite.reweave_task_intent import (
    behavior_contract_search_text,
    ensure_complete_project_capsule,
    select_capsules_for_task,
)

APP_VERSION = "0.3.0"
LUMO_LITE_MODE = "source_read_only_preview_write"


def lumo_lite_engine_status(load_result: dict[str, Any]) -> dict[str, Any]:
    available = bool(load_result.get("ok"))
    return {
        "engine": "lumo_lite",
        "available": available,
        "mode": LUMO_LITE_MODE,
        "runtime_state": {
            "status": load_result.get("status"),
            "path": load_result.get("path", ""),
            "error": load_result.get("error", ""),
        },
        "capabilities": {
            "frontend_runtime_state": available,
            "capsule_warehouse": available,
            "capsule_warehouse_read": available,
            "capsule_warehouse_management": False,
            "local_capsule_store": True,
            "local_artifact_view": available,
            "bind": True,
            "scan": True,
            "prepare": True,
            "warehouse": True,
            "generate_preview": "task_pack_preview",
            "health_probe": False,
            "reuse_pack": False,
            "pym_index_pack": False,
            "dispatch": False,
            "governance_apply": False,
            "recovery_promote": False,
            "llm_generation": False,
            "bounded_local_model": "payload_opt_in",
            "write_source_folder": False,
            "network_call": False,
        },
    }


def lumo_lite_runtime_summary(
    runtime_state: dict[str, Any],
    *,
    capsule_count: int = 0,
    artifact_count: int = 0,
) -> dict[str, Any]:
    warehouse = capsule_warehouse_block(runtime_state)
    acceptance = runtime_state.get("capsule_product_acceptance")
    if not isinstance(acceptance, dict):
        acceptance = {}
    safety = runtime_state.get("safety")
    if not isinstance(safety, dict):
        safety = {}
    product_base = runtime_state.get("lumo_product_base")
    if not isinstance(product_base, dict):
        product_base = {}
    task_pack = runtime_state.get("lumo_task_pack")
    if not isinstance(task_pack, dict):
        task_pack = {}

    status = str(runtime_state.get("status") or "").strip()
    source_write_count = acceptance.get("source_project_write_count")
    if source_write_count is None and safety.get("real_workspace_writes") == "blocked":
        source_write_count = 0

    acceptance_line = str(acceptance.get("line") or "").strip()
    if not acceptance_line:
        accepted = acceptance.get("accepted_count")
        total = acceptance.get("reviewable_case_run_count")
        if accepted is not None and total is not None:
            acceptance_line = f"Product acceptance: {accepted}/{total}"
        elif source_write_count is not None:
            acceptance_line = f"Source writes: {source_write_count}"
        else:
            acceptance_line = "Runtime state loaded" if runtime_state else "Runtime state unavailable"

    trace_available = bool(
        warehouse.get("trace_path")
        or warehouse.get("capsule_warehouse_trace_receipt")
        or acceptance.get("trace_ready")
        or acceptance.get("trace_ready_count")
    )
    product_capability = "ready" if acceptance and trace_available and source_write_count == 0 else "review" if acceptance else "unavailable"
    source_writes = source_write_count if source_write_count is not None else "unknown"
    trace_label = "ready" if trace_available else "unavailable"
    product_capability_line = f"Product capability: {product_capability} · Source writes: {source_writes} · Trace {trace_label}"

    return {
        "mode": LUMO_LITE_MODE,
        "runtime": str(runtime_state.get("runtime") or "Current Runtime"),
        "status": status,
        "preview_ready": status == "preview_ready" or bool(warehouse.get("preview_path")),
        "capsules_used": capsule_count,
        "trace_available": trace_available,
        "acceptance_line": acceptance_line,
        "product_capability_line": product_capability_line,
        "source_project_write_count": source_write_count,
        "product_base_status": str(product_base.get("status") or ""),
        "product_mode": str(product_base.get("product_mode") or ""),
        "task_pack_status": str(task_pack.get("status") or ""),
        "task_pack_scope": str(task_pack.get("task_scope") or ""),
        "artifact_count": artifact_count,
        "read_only": True,
        "line": product_capability_line,
    }


class LumoLiteReweaveEngine:
    """Expose P15 Lumo Lite local state to the existing Reweave frontend."""

    def __init__(self, runtime_state_path: str | None = None) -> None:
        self._runtime_state_path = runtime_state_path

    def _load(self) -> dict[str, Any]:
        return load_lumo_lite_runtime_state(self._runtime_state_path)

    def get_initial_state(self) -> dict[str, Any]:
        load_result = self._load()
        runtime_state = load_result.get("state") if isinstance(load_result.get("state"), dict) else {}
        state_path = str(load_result.get("path") or "")
        warehouse = lumo_lite_capsule_warehouse(runtime_state, state_path=state_path)
        capsules = map_capsule_warehouse_to_reweave_capsules(
            runtime_state,
            state_path=state_path,
        )
        local_capsules = list_local_capsules()
        all_capsules = capsules + local_capsules
        source_boxes = _merge_source_boxes(
            lumo_lite_source_boxes({"capsule_warehouse": warehouse}),
            list_source_boxes(),
        )
        artifacts = collect_lumo_lite_artifacts(self._runtime_state_path)
        artifact_items = artifacts.get("artifacts") if artifacts.get("ok") else []

        base = {
            "mode": "desktop_app",
            "backend": "lumo_lite",
            "engine": "lumo_lite",
            "engineStatus": lumo_lite_engine_status(load_result),
            "appVersion": APP_VERSION,
            "skipWelcome": True,
            "lumoLiteAvailable": bool(load_result.get("ok")),
            "lumoLiteMode": LUMO_LITE_MODE,
            "lumoLiteRuntimeStatePath": str(load_result.get("path") or ""),
            "lumoLiteRuntimeStateStatus": str(load_result.get("status") or ""),
            "lumoLiteRuntimeSummary": lumo_lite_runtime_summary(
                runtime_state,
                capsule_count=len(capsules),
                artifact_count=len(artifact_items) if isinstance(artifact_items, list) else 0,
            ),
            "lumoLiteCapsuleWarehouse": warehouse,
            "lumoLiteArtifacts": artifact_items if isinstance(artifact_items, list) else [],
            "lumoLiteArtifactStatus": artifacts.get("mode") if artifacts.get("ok") else artifacts.get("error"),
            "warehouseCapsules": all_capsules,
            "capsules": all_capsules,
            "useLocalCapsules": bool(local_capsules),
            "useLumoLiteCapsules": bool(capsules),
            "sourceBoxes": source_boxes,
            "sourceSummaries": list_summary_lights(),
            "capsuleDrafts": list_draft_lights(),
            "canChooseSourceFolder": True,
            "canScanSourceBox": True,
            "canDraftCapsules": True,
            "canPromoteDrafts": True,
            "canGeneratePreview": True,
            "canUseBoundedLocalModel": True,
            "canOpenPreviewFolder": False,
            "bridge": {
                "network_call": False,
                "model_call": False,
                "watcher": False,
                "dispatch": False,
                "mode": LUMO_LITE_MODE,
            },
        }
        if load_result.get("error"):
            base["lumoLiteError"] = load_result.get("error")
        return base

    def bind_source_folder(self, path: str) -> dict[str, Any]:
        source = add_source_box(path)
        source["lumo_lite_intake"] = "local_metadata_only"
        source["source_project_write"] = False
        return source

    def scan_source(self, source_id: str) -> dict[str, Any]:
        return execute_source_scan(source_id)

    def draft_source(self, source_id: str) -> dict[str, Any]:
        return draft_capsules(source_id)

    def promote_source(self, source_id: str) -> list[dict[str, Any]]:
        promoted = promote_local_drafts(source_id)
        enriched: list[dict[str, Any]] = []
        for cap in promoted:
            cap_id = str(cap.get("id") or "")
            if not cap_id:
                continue
            enrich_local_capsule_content(cap_id)
            enriched.append(get_local_capsule(cap_id) or cap)
        return enriched or promoted

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        return get_source_box(source_id)

    def enrich_capsule_content(self, capsule_id: str) -> dict[str, Any]:
        return enrich_local_capsule_content(capsule_id)

    def get_capsule_content(self, capsule_id: str) -> dict[str, Any]:
        return get_local_capsule_content(capsule_id)

    def select_capsules(self, task: str) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        behavior_by_source: dict[str, str] = {}
        complete_project_capsule_ids: set[str] = set()
        for capsule in list_local_capsules():
            if not is_generate_eligible(capsule):
                continue
            candidate = dict(capsule)
            content = load_capsule_content(str(candidate.get("id") or "")) or {}
            contract = content.get("behavior_contract") if isinstance(content.get("behavior_contract"), dict) else {}
            candidate["_closed_behavior"] = contract.get("status") == "closed"
            source_id = str(candidate.get("source_id") or candidate.get("source") or "")
            if content.get("project_files_complete") is True:
                complete_project_capsule_ids.add(str(candidate.get("id") or ""))
            behavior_text = behavior_contract_search_text(contract)
            if behavior_text:
                behavior_by_source[source_id] = behavior_text
            candidates.append(candidate)
        for candidate in candidates:
            source_id = str(candidate.get("source_id") or candidate.get("source") or "")
            candidate["_behavior_text"] = behavior_by_source.get(source_id, "")
        selected = select_capsules_for_task(task, candidates)
        return ensure_complete_project_capsule(selected, candidates, complete_project_capsule_ids)

    def generate_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = str(payload.get("taskText") or payload.get("task") or "New tool")
        effective_payload = dict(payload)
        if str(payload.get("selectionMode") or payload.get("selection_mode") or "") == "auto_match":
            selected = self.select_capsules(task)
            effective_payload["capsuleIds"] = [str(cap.get("id")) for cap in selected if cap.get("id")]
            effective_payload["capsules"] = selected
        capsule_ids = effective_payload.get("capsuleIds") if isinstance(effective_payload.get("capsuleIds"), list) else []
        use_enriched = bool(payload.get("useEnrichedContent"))
        if not use_enriched:
            for cap_id in capsule_ids:
                cap = get_local_capsule(str(cap_id))
                enrichment = cap.get("content_enrichment") if isinstance(cap, dict) and isinstance(cap.get("content_enrichment"), dict) else {}
                if str(enrichment.get("status") or "") == "enriched":
                    use_enriched = True
                    break
        try:
            result = build_preview_package(
                {
                    **effective_payload,
                    "backend": "lumo_lite_task_pack",
                    "taskPack": True,
                    "useEnrichedContent": use_enriched,
                    "reuseBehavior": True,
                }
            )
        except ValueError as exc:
            if not str(exc).startswith("preview quality gate failed"):
                raise
            return {
                "ok": False,
                "mode": "task_pack_preview",
                "source_project_write": False,
                "dispatch": False,
                "network_call": False,
                "model_call": False,
                "previewAcceptance": {"verdict": "rejected", "reason": "quality_gate_failed"},
                "error": str(exc),
            }
        if not isinstance(result.get("taskPack"), dict):
            raise ValueError("preview core did not return taskPack")
        local_model = effective_payload.get("localModel") if isinstance(effective_payload.get("localModel"), dict) else {}
        model_meta: dict[str, Any] = {"enabled": False, "local_http_call": False, "applied": False}
        if local_model.get("enabled") is True:
            selected_capsules = effective_payload.get("capsules") if isinstance(effective_payload.get("capsules"), list) else []
            provider = str(local_model.get("provider") or "ollama").strip().lower()
            model = str(local_model.get("model") or "qwen2.5-coder:1.5b").strip()
            base_url = str(local_model.get("baseUrl") or "http://127.0.0.1:11434").strip()
            try:
                timeout = max(1.0, min(120.0, float(local_model.get("timeout") or 60)))
            except (TypeError, ValueError):
                timeout = 60.0
            if provider != "ollama":
                model_meta = {
                    "enabled": True,
                    "provider": provider,
                    "model": model,
                    "local_http_call": False,
                    "external_network_call": False,
                    "source_project_write": False,
                    "applied": False,
                    "fallback_used": True,
                    "error": "unsupported_local_model_provider",
                }
            else:
                model_meta = apply_ollama_pack(
                    Path(result["previewPath"]),
                    task=task,
                    selected_capsules=[cap for cap in selected_capsules if isinstance(cap, dict)],
                    snippet_context=result.get("snippetContext"),
                    model=model,
                    base_url=base_url,
                    timeout=timeout,
                    require=bool(local_model.get("require")),
                    bounded_only=True,
                )
                root = Path(result["previewPath"])
                result["taskPack"] = json.loads((root / "task_pack.json").read_text(encoding="utf-8"))
                result["provenance"] = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
        if effective_payload.get("validateRuntime") is True:
            react_preview = result["taskPack"].get("react_preview")
            if isinstance(react_preview, dict) and react_preview.get("status") == "passed":
                runtime_contract = (
                    react_preview.get("runtime_contract")
                    if isinstance(react_preview.get("runtime_contract"), dict)
                    else None
                )
                validation = validate_react_preview_behavior(result["previewPath"], task, runtime_contract)
                attached = attach_react_runtime_validation(result["previewPath"], validation)
                receipt_name = "react_runtime_validation.json"
            else:
                validation = validate_preview_behavior(result["previewPath"])
                attached = attach_behavior_validation(result["previewPath"], validation)
                receipt_name = "behavior_validation.json"
            result.update(attached)
            result["runtimeValidation"] = validation
            files = result.get("generatedPackage", {}).get("files")
            if isinstance(files, list) and receipt_name not in files:
                files.append(receipt_name)
        result["mode"] = "task_pack_preview"
        result["source_project_write"] = False
        result["dispatch"] = False
        result["localModel"] = model_meta
        result["model_call"] = bool(model_meta.get("local_http_call"))
        result["network_call"] = bool(model_meta.get("local_http_call"))
        result["previewAcceptance"] = preview_acceptance(result["taskPack"])
        return result

    def list_lumo_lite_artifacts(self) -> dict[str, Any]:
        return collect_lumo_lite_artifacts(self._runtime_state_path)

    def get_lumo_lite_artifact(self, artifact_id_or_path: str) -> dict[str, Any]:
        return get_lumo_lite_artifact(artifact_id_or_path, self._runtime_state_path)

    def get_lumo_lite_artifact_path(self, artifact_id_or_path: str) -> str | None:
        path = get_lumo_lite_artifact_path(artifact_id_or_path, self._runtime_state_path)
        return str(path) if path is not None else None

    def _disabled(self, error: str, **extra: Any) -> dict[str, Any]:
        result = {
            "ok": False,
            "engine": "lumo_lite",
            "mode": LUMO_LITE_MODE,
            "error": error,
            "dispatch": False,
            "network_call": False,
            "model_call": False,
        }
        result.update(extra)
        return result


def _merge_source_boxes(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for source in group:
            if not isinstance(source, dict):
                continue
            source_id = str(source.get("id") or "").strip()
            if source_id:
                merged[source_id] = dict(source)
    return list(merged.values())
