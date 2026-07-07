"""Lumo Reweave engine — local intake + Luna reuse/index pack (no dispatch)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pimos_lite.reweave_capsule_warehouse import get_capsule
from pimos_lite.reweave_engine.local import APP_VERSION, LocalReweaveEngine
from pimos_lite.reweave_engine.status import lumo_engine_status
from pimos_lite.reweave_luna_client import INDEX_PACK_PATH, REUSE_PACK_PATH, LunaHttpClient
from pimos_lite.reweave_reuse_suggestions import map_luna_assets_to_suggestions
from pimos_lite.reweave_source_scanner import load_summary


class LunaClient(Protocol):
    def health(self) -> dict[str, Any]: ...

    def index_pack(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def reuse_pack(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def _lumo_message(status: dict[str, Any]) -> str:
    if status.get("available"):
        return "Luna reuse-pack ranking + index-pack available — no dispatch or LLM generation"
    luna = status.get("luna") if isinstance(status.get("luna"), dict) else {}
    err = luna.get("error") or "Luna unavailable"
    return f"Luna unavailable: {err} — local prepare/preview still available"


def _resolve_capsule_metadata(payload: dict[str, Any], local_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if local_result and isinstance(local_result.get("capsulesUsed"), list):
        return [dict(item) for item in local_result["capsulesUsed"] if isinstance(item, dict)]
    capsule_ids = [str(x) for x in (payload.get("capsuleIds") or []) if x]
    resolved: list[dict[str, Any]] = []
    for cap_id in capsule_ids:
        cap = get_capsule(cap_id)
        if not cap:
            continue
        resolved.append(
            {
                "id": cap.get("id"),
                "name": cap.get("name"),
                "type": cap.get("type"),
                "source_id": cap.get("source_id"),
                "tags": list(cap.get("tags") or []),
                "origin": cap.get("origin"),
                "risk": cap.get("risk"),
                "content_mode": cap.get("content_mode"),
                "lineage": dict(cap["lineage"]) if isinstance(cap.get("lineage"), dict) else None,
            }
        )
        enrichment = cap.get("content_enrichment") if isinstance(cap.get("content_enrichment"), dict) else None
        if enrichment:
            resolved[-1]["content_enrichment"] = {
                "status": enrichment.get("status"),
                "content_path": enrichment.get("content_path"),
                "snippet_count": enrichment.get("snippet_count"),
            }
    return resolved


def build_reuse_pack_payload(source_id: str, summary: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build Luna POST /api/v1/reuse/pack body from scan summary metadata only."""
    summary = summary or load_summary(source_id) or {}
    label = str(summary.get("label") or source_id).strip()
    extensions = summary.get("extensions") if isinstance(summary.get("extensions"), dict) else {}
    entry_candidates = summary.get("entry_candidates") if isinstance(summary.get("entry_candidates"), list) else []

    query_bits: list[str] = []
    if label:
        query_bits.append(label)
    for ext in sorted(extensions.keys()):
        query_bits.append(str(ext).lstrip("."))
    for entry in entry_candidates[:5]:
        query_bits.append(Path(str(entry)).name)

    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    file_count = counts.get("files")
    if file_count:
        query_bits.append(f"{file_count} files")

    query = " ".join(bit for bit in query_bits if bit).strip()[:1000] or label or "reweave source"
    top_k = 5
    return {"query": query, "top_k": top_k}


class LumoReweaveEngine:
    """Delegates intake to local engine; Luna hooks are pack-only / reuse ranking."""

    def __init__(self, luna_client: LunaClient | None = None) -> None:
        self._local = LocalReweaveEngine()
        self._luna: LunaClient = luna_client or LunaHttpClient()

    def health(self) -> dict[str, Any]:
        return self._luna.health()

    def get_status(self) -> dict[str, Any]:
        return lumo_engine_status(self.health())

    def capabilities(self) -> dict[str, Any]:
        return dict(self.get_status()["capabilities"])

    def get_initial_state(self) -> dict[str, Any]:
        state = self._local.get_initial_state()
        status = self.get_status()
        state["backend"] = "lumo"
        state["engine"] = "lumo"
        state["engineStatus"] = status
        state["appVersion"] = APP_VERSION
        state["lumoAvailable"] = bool(status.get("available"))
        state["lumoMessage"] = _lumo_message(status)
        state["canGeneratePreview"] = True
        return state

    def bind_source_folder(self, path: str) -> dict[str, Any]:
        return self._local.bind_source_folder(path)

    def scan_source(self, source_id: str) -> dict[str, Any]:
        return self._local.scan_source(source_id)

    def draft_source(self, source_id: str) -> dict[str, Any]:
        return self._local.draft_source(source_id)

    def promote_source(self, source_id: str) -> list[dict[str, Any]]:
        return self._local.promote_source(source_id)

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        return self._local.get_source(source_id)

    def build_index_pack_payload(
        self,
        payload: dict[str, Any],
        local_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build Luna POST /api/v1/pym/index-pack body from Reweave generate payload."""
        task = str(payload.get("taskText") or payload.get("task") or "").strip()
        capsule_ids = [str(x) for x in (payload.get("capsuleIds") or []) if x]
        capsules = _resolve_capsule_metadata(payload, local_result)

        query_bits: list[str] = []
        if task:
            query_bits.append(task)
        for cap in capsules:
            name = cap.get("name")
            if name:
                query_bits.append(str(name))
            for tag in cap.get("tags") or []:
                query_bits.append(str(tag))

        query = " ".join(query_bits).strip()[:1000] or "reweave preview"
        top_k = max(1, min(20, len(capsule_ids) or 5))

        body: dict[str, Any] = {
            "query": query,
            "task_goal": task or query,
            "top_k": top_k,
            "capsules": capsules,
        }

        if local_result and isinstance(local_result.get("contentAwareGenerate"), dict):
            cag = local_result["contentAwareGenerate"]
            body["content_aware_generate"] = {
                "enabled": bool(cag.get("enabled")),
                "mode": cag.get("mode"),
                "snippets_used_path": cag.get("snippetsUsedPath"),
                "snippet_count": cag.get("snippetsUsed"),
                "used_app_state_content_only": True,
            }

        return body

    def prepare_reuse_pack(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Luna reuse-pack ranking only — suggestions, never warehouse writes."""
        health = self.health()
        if not health.get("ok"):
            return {
                "ok": False,
                "engine": "lumo",
                "mode": "reuse_pack_ranking",
                "error": "luna_unavailable",
                "fallbackRecommended": True,
            }

        source_id = str(payload.get("source_id") or "").strip()
        if not source_id:
            return {
                "ok": False,
                "engine": "lumo",
                "mode": "reuse_pack_ranking",
                "error": "missing source_id",
                "fallbackRecommended": True,
            }

        luna_request = build_reuse_pack_payload(source_id)
        reuse_result = self._luna.reuse_pack(luna_request)
        if not reuse_result.get("ok"):
            return {
                "ok": False,
                "engine": "lumo",
                "mode": "reuse_pack_ranking",
                "error": str(reuse_result.get("error") or "reuse_pack_failed")[:200],
                "fallbackRecommended": True,
                "endpoint": reuse_result.get("endpoint", REUSE_PACK_PATH),
            }

        assets = reuse_result.get("assets") if isinstance(reuse_result.get("assets"), list) else []
        query = str(luna_request.get("query") or "")
        suggestions = map_luna_assets_to_suggestions(assets, pack_query=query)
        return {
            "ok": True,
            "engine": "lumo",
            "mode": "reuse_pack_ranking",
            "assets_count": len(assets),
            "capsuleSuggestions": suggestions,
            "endpoint": reuse_result.get("endpoint", REUSE_PACK_PATH),
            "query": query,
            "warnings": [],
            "reuseRequest": luna_request,
            "reuseResult": reuse_result,
        }

    def generate_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Luna index-pack reference only — no dispatch, no LLM generation, no local preview."""
        health = self.health()
        if not health.get("ok"):
            return {
                "ok": False,
                "engine": "lumo",
                "mode": "pack_only",
                "dispatch": False,
                "error": "luna_unavailable",
                "fallbackRecommended": True,
            }

        local_result = payload.get("_localPreview") if isinstance(payload.get("_localPreview"), dict) else None
        luna_request = self.build_index_pack_payload(payload, local_result)
        pack_result = self._luna.index_pack(luna_request)
        if not pack_result.get("ok"):
            return {
                "ok": False,
                "engine": "lumo",
                "mode": "pack_only",
                "dispatch": False,
                "error": str(pack_result.get("error") or "index_pack_failed")[:200],
                "fallbackRecommended": True,
                "endpoint": pack_result.get("endpoint", INDEX_PACK_PATH),
            }

        return {
            "ok": True,
            "engine": "lumo",
            "mode": "pack_only",
            "dispatch": False,
            "lunaPack": {
                "pack_id": pack_result.get("pack_id"),
                "manifest_path": pack_result.get("manifest_path"),
                "endpoint": pack_result.get("endpoint", INDEX_PACK_PATH),
            },
            "warnings": [],
        }
