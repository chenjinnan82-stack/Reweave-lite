"""Lumo Lite local-state Reweave engine (P15 read-only path)."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
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
from pimos_lite.reweave_preview_pack import append_preview_history_entry, build_preview_package, preview_packages_dir
from pimos_lite.reweave_preview_pack import publish_preview_package
from pimos_lite.reweave_preview_pack import attach_behavior_validation
from pimos_lite.reweave_preview_pack import attach_react_runtime_validation
from pimos_lite.reweave_preview_pack import load_preview_history
from pimos_lite.reweave_preview_pack import preview_acceptance
from pimos_lite.reweave_quality_gate import inspect_static_runtime_security
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
from pimos_lite.reweave_llm_pack import (
    apply_ollama_pack,
    apply_ollama_planning,
    select_ollama_action_sequence,
    select_ollama_wiring_plan,
)
from pimos_lite.reweave_source_registry import add_source_box, get_source_box, list_source_boxes, state_dir
from pimos_lite.reweave_source_scanner import list_summary_lights
from pimos_lite.reweave_source_scanner import scan_source_box as execute_source_scan
from pimos_lite.reweave_stage4_composer import (
    compose_with_stage4,
    extract_many_with_stage4,
    list_stage4_module_capsules,
    plan_with_stage4,
)
from pimos_lite.reweave_task_intent import (
    behavior_contract_search_text,
    build_task_intent,
    ensure_complete_project_capsule,
    select_capsules_for_task,
)

APP_VERSION = "0.3.0"
LUMO_LITE_MODE = "source_read_only_preview_write"


def _discard_unpublished_preview(path: str) -> bool:
    raw = Path(path)
    if not path or raw.is_symlink():
        return False
    resolved = raw.resolve()
    try:
        resolved.relative_to(preview_packages_dir().resolve())
    except ValueError:
        return False
    shutil.rmtree(resolved, ignore_errors=True)
    return not resolved.exists()


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

    def __init__(
        self,
        runtime_state_path: str | None = None,
    ) -> None:
        self._runtime_state_path = runtime_state_path
        self._latest_stage4_product_entry: Path | None = None
        self._stage4_extraction_status: dict[str, Any] = {"status": "not_run", "warnings": []}

    def _stage4_modules(self) -> list[dict[str, Any]]:
        return self._local_stage4_modules()

    def _local_stage4_modules(self) -> list[dict[str, Any]]:
        path = self._local_stage4_capsules()
        if not path.is_dir():
            return []
        return list_stage4_module_capsules(capsule_path=path)

    @staticmethod
    def _local_stage4_capsules() -> Path:
        return state_dir() / "stage4_behavior_modules"

    def _stage4_capsule_path_for(self, module_ids: list[str]) -> Path | None:
        path = self._local_stage4_capsules()
        if not path.is_dir():
            return None
        requested = set(module_ids)
        available = {str(row["id"]) for row in list_stage4_module_capsules(capsule_path=path)}
        return path if requested <= available else None

    def _extract_source_behavior_modules(
        self,
        source_id: str,
        source_capsules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not source_id or Path(source_id).name != source_id:
            return []
        source = get_source_box(source_id) or {}
        source_root = Path(str(source.get("path") or ""))
        if not source_root.is_dir():
            return []
        local_root = self._local_stage4_capsules()
        legacy_module_prefix = f"module-{source_id.replace('_', '-')}-"
        stale_paths: set[Path] = set()
        if local_root.is_dir():
            for path in local_root.glob("*.json"):
                try:
                    row = json.loads(path.read_text(encoding="utf-8")) if not path.is_symlink() else {}
                except (OSError, json.JSONDecodeError):
                    continue
                provenance = row.get("provenance") if isinstance(row, dict) and isinstance(row.get("provenance"), dict) else {}
                if (
                    str(provenance.get("source_box_id") or "") == source_id
                    or source_id in provenance.get("source_capsule_ids", [])
                    or str(row.get("module_capsule_id") or "").startswith(legacy_module_prefix)
                ):
                    stale_paths.add(path)
        source_capsule_ids = {
            "ui": next(
                (str(row.get("id") or "") for name in ("Page Shell", "HTML Surface") for row in source_capsules if row.get("name") == name),
                "",
            ),
            "logic": next((str(row.get("id") or "") for row in source_capsules if row.get("name") == "Script Module"), ""),
            "data": next((str(row.get("id") or "") for row in source_capsules if row.get("name") == "JSON Data"), ""),
        }
        requested = [(role, source_capsule_ids[role]) for role in ("ui", "logic", "data") if source_capsule_ids[role]]
        if not requested:
            self._stage4_extraction_status = {"status": "not_available", "warnings": ["no_stage4_source_capsules"]}
            return []
        extracted: list[tuple[str, dict[str, Any]]] = []
        rejected: list[tuple[str, str]] = []
        for role, source_capsule_id in requested:
            results = extract_many_with_stage4(
                source_root=source_root,
                role=role,
                source_id=source_id,
                source_capsule_id=source_capsule_id,
            )
            for result in results:
                module_id = str(result.get("module_capsule_id") or "")
                if result.get("status") == "rejected":
                    rejected.append((role, f"{role}:{result.get('reason') or 'rejected'}"))
                    continue
                if result.get("module_capsule_version") != "module_capsule.v1" or not module_id or Path(module_id).name != module_id:
                    self._stage4_extraction_status = {"status": "failed", "warnings": [f"{role}:invalid_stage4_module"]}
                    return []
                extracted.append((role, result))
        if rejected and (not extracted or any(role != "data" for role, _warning in rejected)):
            self._stage4_extraction_status = {"status": "rejected", "warnings": [warning for _role, warning in rejected]}
            return []

        local_root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="stage4-behavior-modules-", dir=local_root.parent))
        backup: Path | None = None
        try:
            if local_root.is_dir():
                for path in local_root.iterdir():
                    if path in stale_paths or path.is_symlink() or not path.is_file():
                        continue
                    shutil.copy2(path, staging / path.name)
            for role, result in extracted:
                (staging / f"{result['module_capsule_id']}.json").write_text(
                    json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            if local_root.exists():
                backup = Path(tempfile.mkdtemp(prefix="stage4-behavior-modules-backup-", dir=local_root.parent))
                backup.rmdir()
                local_root.replace(backup)
            staging.replace(local_root)
        except Exception:
            if backup is not None and backup.exists() and not local_root.exists():
                backup.replace(local_root)
            shutil.rmtree(staging, ignore_errors=True)
            raise
        else:
            if backup is not None:
                shutil.rmtree(backup, ignore_errors=True)
        self._stage4_extraction_status = {
            "status": "extracted_with_warnings" if rejected else "extracted",
            "warnings": [warning for _role, warning in rejected],
            "module_ids": [str(result.get("module_capsule_id") or "") for _role, result in extracted],
        }
        return [result for _role, result in extracted]

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
        stage4_modules = self._stage4_modules()
        preview_history = [
            {
                "title": str(row.get("task") or row.get("id") or "Preview"),
                "capsulesUsed": int(row.get("capsule_count") or 0),
                "note": str(row.get("mode") or "local preview"),
            }
            for row in load_preview_history().get("packages", [])
            if isinstance(row, dict)
        ]
        all_capsules = capsules + local_capsules + stage4_modules
        source_boxes = _merge_source_boxes(
            lumo_lite_source_boxes({"capsule_warehouse": warehouse}),
            list_source_boxes(),
        )
        artifacts = collect_lumo_lite_artifacts(self._runtime_state_path)
        artifact_items = artifacts.get("artifacts") if artifacts.get("ok") else []

        engine_status = lumo_lite_engine_status(load_result)
        engine_status["capabilities"]["stage4_behavior_composition"] = bool(stage4_modules)
        base = {
            "mode": "desktop_app",
            "backend": "lumo_lite",
            "engine": "lumo_lite",
            "engineStatus": engine_status,
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
            "useStage4Modules": bool(stage4_modules),
            "stage4Extraction": dict(self._stage4_extraction_status),
            "sourceBoxes": source_boxes,
            "sourceSummaries": list_summary_lights(),
            "capsuleDrafts": list_draft_lights(),
            "history": preview_history,
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
        try:
            self._extract_source_behavior_modules(source_id, enriched or promoted)
        except (OSError, RuntimeError, TimeoutError) as exc:
            self._stage4_extraction_status = {"status": "failed", "warnings": [str(exc)]}
        returned = enriched or promoted
        return [{**cap, "stage4_extraction": dict(self._stage4_extraction_status)} for cap in returned]

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
        selection_mode = str(payload.get("selectionMode") or payload.get("selection_mode") or "")
        if selection_mode == "auto_behavior":
            local_modules = {str(row["id"]): row for row in self._local_stage4_modules()}
            if not local_modules:
                return {"ok": False, "error": "no_local_behavior_modules", "source_project_write": False}
            return self._generate_stage4_preview(
                task,
                [],
                local_modules,
                auto_behavior=True,
                local_model=payload.get("localModel") if isinstance(payload.get("localModel"), dict) else None,
            )
        raw_ids = payload.get("capsuleIds") if isinstance(payload.get("capsuleIds"), list) else []
        selected_ids = [str(item) for item in raw_ids if item]
        stage4_modules = {str(row["id"]): row for row in self._stage4_modules()}
        selected_stage4_ids = [module_id for module_id in selected_ids if module_id in stage4_modules]
        if selected_stage4_ids:
            if len(selected_stage4_ids) != len(selected_ids):
                return {"ok": False, "error": "mixed_stage4_and_reweave_capsules_not_supported", "source_project_write": False}
            return self._generate_stage4_preview(task, selected_stage4_ids, stage4_modules)
        if selection_mode == "auto_match":
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
        local_model = effective_payload.get("localModel") if isinstance(effective_payload.get("localModel"), dict) else {}
        provider = str(local_model.get("provider") or "ollama").strip().lower()
        model = str(local_model.get("model") or "qwen2.5-coder:1.5b").strip()
        base_url = str(local_model.get("baseUrl") or "http://127.0.0.1:11434").strip()
        try:
            timeout = max(1.0, min(120.0, float(local_model.get("timeout") or 60)))
        except (TypeError, ValueError):
            timeout = 60.0
        planning_requested = bool(local_model.get("intentPatch") or local_model.get("capsuleRanking"))
        deferred_publish = bool(local_model.get("enabled") is True and local_model.get("require") is True)
        planning_result: dict[str, Any] | None = None
        if local_model.get("enabled") is True and provider == "ollama" and planning_requested:
            selected_capsules = (
                [cap for cap in effective_payload.get("capsules", []) if isinstance(cap, dict)]
                if isinstance(effective_payload.get("capsules"), list)
                else []
            )
            if not selected_capsules:
                selected_capsules = [
                    cap
                    for cap_id in capsule_ids
                    if isinstance((cap := get_local_capsule(str(cap_id))), dict)
                ]
            planning_result = apply_ollama_planning(
                task=task,
                intent=build_task_intent(task, selected_capsules),
                capsules=selected_capsules,
                model=model,
                base_url=base_url,
                timeout=timeout,
                enable_intent_patch=bool(local_model.get("intentPatch")),
                enable_capsule_ranking=bool(local_model.get("capsuleRanking")),
            )
            ordered_ids = planning_result.get("ordered_capsule_ids")
            if isinstance(ordered_ids, list) and ordered_ids:
                by_id = {str(cap.get("id")): cap for cap in selected_capsules if cap.get("id")}
                effective_payload["capsuleIds"] = ordered_ids
                effective_payload["capsules"] = [by_id[cap_id] for cap_id in ordered_ids]
                capsule_ids = ordered_ids
            if planning_result.get("intent_patch"):
                effective_payload["intentPatch"] = planning_result["intent_patch"]
            effective_payload["planningModelMeta"] = planning_result["meta"]
        try:
            result = build_preview_package(
                {
                    **effective_payload,
                    "backend": "lumo_lite_task_pack",
                    "taskPack": True,
                    "useEnrichedContent": use_enriched,
                    "reuseBehavior": True,
                    "deferPublish": deferred_publish,
                }
            )
        except ValueError as exc:
            error = str(exc)
            if error not in {"no_reusable_capsules", "no_reusable_capsule_content"} and not error.startswith(
                "preview quality gate failed"
            ):
                raise
            return {
                "ok": False,
                "mode": "task_pack_preview",
                "source_project_write": False,
                "dispatch": False,
                "network_call": False,
                "model_call": False,
                "previewAcceptance": {
                    "verdict": "rejected",
                    "reason": error if error in {"no_reusable_capsules", "no_reusable_capsule_content"} else "quality_gate_failed",
                },
                "error": error,
            }
        if not isinstance(result.get("taskPack"), dict):
            raise ValueError("preview core did not return taskPack")
        model_meta: dict[str, Any] = {"enabled": False, "status": "disabled", "local_http_call": False, "applied": False}
        if local_model.get("enabled") is True:
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
                    "status": "failed",
                    "required": bool(local_model.get("require")),
                    "error": "unsupported_local_model_provider",
                }
            elif planning_result is not None:
                model_meta = planning_result["meta"]
            else:
                model_meta = apply_ollama_pack(
                    Path(result["previewPath"]),
                    task=task,
                    snippet_context=result.get("snippetContext"),
                    model=model,
                    base_url=base_url,
                    timeout=timeout,
                    require=bool(local_model.get("require")),
                )
                root = Path(result["previewPath"])
                result["taskPack"] = json.loads((root / "task_pack.json").read_text(encoding="utf-8"))
                result["provenance"] = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
            model_requirement_met = bool(
                model_meta.get("requested_slots_applied")
                if planning_requested
                else model_meta.get("applied")
            )
            if local_model.get("require") is True and not model_requirement_met:
                preview_discarded = _discard_unpublished_preview(str(result.get("previewPath") or ""))
                return {
                    "ok": False,
                    "mode": "task_pack_preview",
                    "localModel": model_meta,
                    "model_call": bool(model_meta.get("local_http_call")),
                    "network_call": bool(model_meta.get("local_http_call")),
                    "source_project_write": False,
                    "previewDiscarded": preview_discarded,
                    "previewAcceptance": {"verdict": "rejected", "reason": "llm_required_but_not_applied"},
                    "error": f"llm_required_but_not_applied:{model_meta.get('error') or model_meta.get('status')}",
                }
        if effective_payload.get("validateRuntime") is True:
            product_entry = result["taskPack"].get("product_entry") if isinstance(result["taskPack"].get("product_entry"), dict) else {}
            react_preview = result["taskPack"].get("react_preview")
            if product_entry.get("kind") == "react_build" and isinstance(react_preview, dict) and react_preview.get("status") == "passed":
                runtime_contract = (
                    react_preview.get("runtime_contract")
                    if isinstance(react_preview.get("runtime_contract"), dict)
                    else None
                )
                validation = validate_react_preview_behavior(result["previewPath"], task, runtime_contract)
                attached = attach_react_runtime_validation(result["previewPath"], validation)
                receipt_name = "react_runtime_validation.json"
            else:
                expected_text = str(result["taskPack"].get("runtime_expected_text") or task)
                validation = validate_preview_behavior(result["previewPath"], expected_text)
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
        result["productEntry"] = result["taskPack"].get("product_entry") or {"path": "index.html", "kind": "static_html"}
        if isinstance(result.get("generatedPackage"), dict):
            result["generatedPackage"]["productEntry"] = result["productEntry"]
        result["model_call"] = bool(model_meta.get("local_http_call"))
        result["network_call"] = bool(model_meta.get("local_http_call"))
        result["previewAcceptance"] = preview_acceptance(result["taskPack"])
        if deferred_publish and result.get("previewPublished") is not True:
            publish_preview_package(result)
        return result

    def _generate_stage4_preview(
        self,
        task: str,
        module_ids: list[str],
        modules: dict[str, dict[str, Any]],
        *,
        auto_behavior: bool = False,
        local_model: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        capsule_path = self._local_stage4_capsules() if auto_behavior else self._stage4_capsule_path_for(module_ids)
        if capsule_path is None:
            return {"ok": False, "error": "stage4_modules_not_in_one_library", "source_project_write": False}
        requested_auto_behavior = auto_behavior
        planning_meta: dict[str, Any] = {}
        selected_graph_plan: dict[str, Any] = {}
        selected_plan_id = ""
        if auto_behavior and local_model and local_model.get("enabled") is True and local_model.get("capsuleRanking") is True:
            graph = plan_with_stage4(goal=task, capsule_path=capsule_path, max_modules=5)
            candidates = [row for row in graph.get("model_candidates", []) if row.get("currentlyExecutable") is True]
            if not candidates:
                return {"ok": False, "error": "no_executable_stage4_composition_plan", "source_project_write": False}
            provider = str(local_model.get("provider") or "ollama").strip().lower()
            if provider != "ollama":
                return {"ok": False, "error": "stage4_plan_ranking_requires_ollama", "source_project_write": False}
            try:
                timeout = max(1.0, min(120.0, float(local_model.get("timeout") or 60)))
            except (TypeError, ValueError):
                timeout = 60.0
            model = str(local_model.get("model") or "qwen2.5-coder:1.5b").strip()
            base_url = str(local_model.get("baseUrl") or "http://127.0.0.1:11434").strip()
            plan_actions = {
                str(row.get("id") or ""): [
                    str(step.get("action") or "")
                    for step in row.get("orderedSteps", [])
                    if isinstance(step, dict) and step.get("role") == "logic" and step.get("action")
                ]
                for row in candidates
            }
            allowed_actions = sorted({action for actions in plan_actions.values() for action in actions})
            has_duplicate_actions = any(len(actions) != len(set(actions)) for actions in plan_actions.values())
            if has_duplicate_actions and len(candidates) > 1:
                wiring = select_ollama_wiring_plan(
                    task=task,
                    plans=candidates,
                    model=model,
                    base_url=base_url,
                    timeout=timeout,
                )
                selected_plan_id = str(wiring.get("selected_plan_id") or "")
                planning_meta = dict(wiring.get("meta") or {})
                ordered_plan_ids = [selected_plan_id] if selected_plan_id else []
            elif len(allowed_actions) > 1:
                planning = select_ollama_action_sequence(
                    task=task,
                    actions=allowed_actions,
                    model=model,
                    base_url=base_url,
                    timeout=timeout,
                )
                ordered_actions = [str(row) for row in planning.get("ordered_actions", []) if row]
                matching = []
                for row in candidates:
                    actions = plan_actions.get(str(row.get("id") or ""), [])
                    if row.get("topology") == "fan_in":
                        matches = (
                            len(actions) == len(ordered_actions)
                            and len(actions) >= 4
                            and actions[0] == ordered_actions[0]
                            and actions[-1] == ordered_actions[-1]
                            and set(actions[1:-1]) == set(ordered_actions[1:-1])
                        )
                    elif row.get("topology") == "fan_out":
                        matches = (
                            len(actions) == len(ordered_actions)
                            and bool(actions)
                            and actions[0] == ordered_actions[0]
                            and set(actions[1:]) == set(ordered_actions[1:])
                        )
                    else:
                        matches = actions == ordered_actions
                    if matches:
                        matching.append(row)
                if ordered_actions and not matching:
                    planning_meta = dict(planning.get("meta") or {})
                    planning_meta.update(
                        {
                            "applied": False,
                            "status": "failed",
                            "fallback_used": True,
                            "error": "stage4_model_action_sequence_not_unique",
                        }
                    )
                    if local_model.get("require") is True:
                        return {
                            "ok": False,
                            "error": "stage4_model_action_sequence_not_unique",
                            "model_selection": planning_meta,
                            "source_project_write": False,
                        }
                    ordered_plan_ids = []
                elif len(matching) > 1:
                    wiring = select_ollama_wiring_plan(
                        task=task,
                        plans=matching,
                        model=model,
                        base_url=base_url,
                        timeout=timeout,
                    )
                    selected_plan_id = str(wiring.get("selected_plan_id") or "")
                    action_meta = dict(planning.get("meta") or {})
                    wiring_meta = dict(wiring.get("meta") or {})
                    planning_applied = bool(action_meta.get("applied") and wiring_meta.get("applied"))
                    planning_meta = {
                        "applied": planning_applied,
                        "status": "applied" if planning_applied else "failed",
                        "fallback_used": not planning_applied,
                        "local_http_call": bool(action_meta.get("local_http_call") or wiring_meta.get("local_http_call")),
                        "external_network_call": False,
                        "source_project_write": False,
                        "action_sequence": action_meta,
                        "wiring_plan": wiring_meta,
                    }
                    if not planning_applied:
                        planning_meta["error"] = str(wiring_meta.get("error") or "stage4_model_wiring_plan_not_applied")
                    if not selected_plan_id:
                        if local_model.get("require") is True:
                            return {
                                "ok": False,
                                "error": "stage4_model_wiring_plan_not_applied",
                                "model_selection": planning_meta,
                                "source_project_write": False,
                            }
                        ordered_plan_ids = []
                    else:
                        ordered_plan_ids = [selected_plan_id]
                else:
                    ordered_plan_ids = [str(matching[0].get("id") or "")] if matching else []
            else:
                planning = apply_ollama_planning(
                    task=task,
                    intent={"output_type": "tool", "capabilities": ["logic"]},
                    capsules=candidates,
                    model=model,
                    base_url=base_url,
                    timeout=timeout,
                    enable_intent_patch=False,
                    enable_capsule_ranking=True,
                )
                ordered_plan_ids = [str(row) for row in planning.get("ordered_capsule_ids", []) if row]
            if not planning_meta:
                planning_meta = dict(planning.get("meta") or {})
            plans_by_id = {str(row.get("id") or ""): row for row in candidates}
            if ordered_plan_ids:
                selected = plans_by_id.get(ordered_plan_ids[0])
                if selected is None:
                    return {"ok": False, "error": "stage4_model_selected_unknown_plan", "source_project_write": False}
                module_ids = [str(row) for row in selected.get("moduleIds", []) if row]
                selected_graph_plan = next(
                    (dict(row) for row in graph.get("plans", []) if row.get("plan_id") == selected.get("id")),
                    {},
                )
                selected_plan_id = str(selected.get("id") or "")
                auto_behavior = False
            if local_model.get("require") is True and not planning_meta.get("applied"):
                return {
                    "ok": False,
                    "error": "stage4_llm_plan_ranking_required_but_not_applied",
                    "model_selection": planning_meta,
                    "source_project_write": False,
                }
        preview_packages_dir().mkdir(parents=True, exist_ok=True)
        preview_root = Path(tempfile.mkdtemp(prefix="stage4-", dir=preview_packages_dir()))
        tags = list(
            dict.fromkeys(
                str(tag)
                for module_id in module_ids
                for tag in modules[module_id].get("tags", [])
                if tag
            )
        )
        try:
            result = compose_with_stage4(
                capsule_path=capsule_path,
                goal=task,
                capability_tags=tags,
                module_ids=module_ids,
                max_modules=5 if auto_behavior else len(module_ids),
                preview_root=preview_root,
                auto_behavior=auto_behavior,
                selected_plan_id=selected_plan_id,
            )
        except Exception:
            shutil.rmtree(preview_root, ignore_errors=True)
            raise
        if result.get("status") != "composed":
            shutil.rmtree(preview_root, ignore_errors=True)
            return {
                "ok": False,
                "error": "stage4_composition_rejected",
                "composition": result,
                "source_project_write": False,
            }
        selected_module_ids = [str(row) for row in result.get("selected_module_capsule_ids", []) if row]
        if (
            not selected_module_ids
            or any(module_id not in modules for module_id in selected_module_ids)
            or (module_ids and set(selected_module_ids) != set(module_ids))
        ):
            shutil.rmtree(preview_root, ignore_errors=True)
            return {"ok": False, "error": "stage4_selected_unknown_module", "source_project_write": False}
        preview_resolved = preview_root.resolve()
        required_files = ("index.html", "styles.css", "app.js")
        stage4_files = (*required_files, "composition_plan.json", "adapter_mapping.json")
        for name in stage4_files:
            candidate = preview_root / name
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(preview_resolved)
            except (OSError, ValueError):
                resolved = candidate
            if candidate.is_symlink() or not resolved.is_file():
                shutil.rmtree(preview_root, ignore_errors=True)
                return {
                    "ok": False,
                    "error": "stage4_required_output_missing_or_unsafe",
                    "file": name,
                    "source_project_write": False,
                }
        runtime_security = inspect_static_runtime_security(
            (preview_root / "index.html").read_text(encoding="utf-8"),
            (preview_root / "styles.css").read_text(encoding="utf-8"),
            (preview_root / "app.js").read_text(encoding="utf-8"),
        )
        if not runtime_security["passed"]:
            shutil.rmtree(preview_root, ignore_errors=True)
            return {
                "ok": False,
                "error": "stage4_runtime_security_failed",
                "checks": runtime_security,
                "source_project_write": False,
            }
        product_entry = {"path": "index.html", "kind": "static_html"}
        composition_plan = result.get("composition_plan") if isinstance(result.get("composition_plan"), dict) else {}
        file_provenance = composition_plan.get("file_provenance") if isinstance(composition_plan.get("file_provenance"), dict) else {}
        file_module_ids = {
            name: list(
                dict.fromkeys(
                    str(row.get("module_capsule_id"))
                    for row in file_provenance.get(name, [])
                    if isinstance(row, dict) and row.get("module_capsule_id")
                )
            )
            for name in required_files
        }
        contributor_ids = {module_id for ids in file_module_ids.values() for module_id in ids}
        if any(not file_module_ids[name] for name in required_files) or contributor_ids != set(selected_module_ids):
            shutil.rmtree(preview_root, ignore_errors=True)
            return {
                "ok": False,
                "error": "stage4_file_provenance_incomplete",
                "source_project_write": False,
            }
        outputs = [
            {
                "path": name,
                "capsule_ids": file_module_ids[name],
                "source_project_write": False,
            }
            for name in required_files
        ]
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        capsules_used = [{**modules[module_id], "usage": "output_contributor"} for module_id in selected_module_ids]
        quality_gate = {
            "status": "passed",
            "runtime_validation": "required",
            "runtime_network_access": False,
            "checks": [
                {"name": "stage4_required_product_files", "passed": True},
                {"name": "stage4_selected_modules_known", "passed": True},
                {
                    "name": "stage4_runtime_network_access_closed",
                    "passed": runtime_security["passed"],
                    "details": runtime_security,
                },
            ],
        }
        task_pack = {
            "schema_version": "reweave_task_pack.v1",
            "mode": "stage4_behavior_composition_preview",
            "package_kind": "small_project_pack",
            "task": task,
            "generated_at": created_at,
            "source_project_write": False,
            "selection_mode": (
                "model_ranked_behavior_plan"
                if selected_graph_plan
                else "auto_behavior"
                if requested_auto_behavior
                else "manual"
            ),
            "composition_strategy": result.get("composition_strategy"),
            "composer_source_ownership": result.get("composer_source_ownership"),
            "composition_plan": composition_plan,
            "product_entry": product_entry,
            "selected_capsule_ids": selected_module_ids,
            "capsules_used": capsules_used,
            "planned_outputs": outputs,
            "quality_gate_path": "quality_gate.json",
            "quality_gate": quality_gate,
            "capsules_used_path": "capsules_used.json",
            "provenance_path": "provenance.json",
            "behavior_reuse": {
                "status": "enabled",
                "mode": "stage4_behavior_composition",
                "runtime_validation": "required",
            },
            "capability_graph_plan": selected_graph_plan,
            "model_selection": planning_meta,
            "effects": {
                "source_project_write": False,
                "preview_output_write": True,
                "runtime_network_access": False,
                "model_call": bool(planning_meta.get("local_http_call")),
                "network_call": bool(planning_meta.get("local_http_call")),
            },
        }
        provenance = {
            "schema_version": "reweave_preview_pack.v1",
            "generated_at": created_at,
            "backend": "stage4_module_native",
            "task": task,
            "composer_owner": result.get("composer_owner"),
            "composer_source_ownership": result.get("composer_source_ownership"),
            "source_project_write": False,
            "runtime_network_access": False,
            "model_call": bool(planning_meta.get("local_http_call")),
            "network_call": bool(planning_meta.get("local_http_call")),
            "selected_module_capsule_ids": selected_module_ids,
            "file_provenance": file_provenance,
            "outputs": outputs,
            "product_entry": product_entry,
            "capability_graph_plan": selected_graph_plan,
            "model_selection": planning_meta,
        }
        receipts = {
            "task_pack.json": task_pack,
            "capsules_used.json": capsules_used,
            "provenance.json": provenance,
            "quality_gate.json": quality_gate,
        }
        try:
            for name, payload in receipts.items():
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=preview_root,
                    prefix=f".{name}.",
                    delete=False,
                ) as handle:
                    handle.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
                    temporary = Path(handle.name)
                temporary.replace(preview_root / name)
            for name in receipts:
                candidate = preview_root / name
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(preview_resolved)
                if candidate.is_symlink() or not resolved.is_file():
                    raise RuntimeError(f"unsafe Stage4 receipt: {name}")
            files = sorted(
                path.name
                for path in preview_root.iterdir()
                if path.is_file() and not path.is_symlink()
            )
            append_preview_history_entry(
                folder_name=preview_root.name,
                rel_folder=f"preview_packages/{preview_root.name}",
                created_at=created_at,
                mode="stage4_behavior_composition_preview",
                content_aware=False,
                snippets_used=0,
                task=task,
                capsule_count=len(selected_module_ids),
            )
        except Exception:
            shutil.rmtree(preview_root, ignore_errors=True)
            raise
        self._latest_stage4_product_entry = preview_root / "index.html"
        return {
            "ok": True,
            "backend": "lumo_lite",
            "mode": "stage4_behavior_composition_preview",
            "previewPath": str(preview_root.resolve()),
            "productEntry": product_entry,
            "generatedPackage": {
                "folder": preview_root.name + "/",
                "files": files,
                "stats": {"capsulesUsed": len(selected_module_ids), "preview": "Stage4 composition", "provenance": "Provenance saved"},
                "productEntry": product_entry,
            },
            "capsulesUsed": capsules_used,
            "taskPack": task_pack,
            "provenance": provenance,
            "runtimeValidation": {"status": "not_run", "reason": "desktop_runtime_validation_required"},
            "previewAcceptance": {"verdict": "needs_review", "reason": "desktop_runtime_validation_required"},
            "source_project_write": False,
            "dispatch": False,
            "model_call": bool(planning_meta.get("local_http_call")),
            "network_call": bool(planning_meta.get("local_http_call")),
            "runtime_network_access": False,
            "modelSelection": planning_meta,
        }

    def get_latest_product_entry_path(self) -> str | None:
        candidate = self._latest_stage4_product_entry
        if candidate is None or candidate.is_symlink() or not candidate.is_file():
            return None
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(preview_packages_dir().resolve())
        except (OSError, ValueError):
            return None
        return str(resolved)

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
