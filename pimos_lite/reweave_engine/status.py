"""Reweave engine status helpers (local vs lumo)."""

from __future__ import annotations

from typing import Any

LOCAL_CAPABILITIES: dict[str, bool] = {
    "bind": True,
    "scan": True,
    "prepare": True,
    "warehouse": True,
    "generate_preview": True,
    "health_probe": False,
    "reuse_pack": False,
    "pym_index_pack": False,
    "verify_suggestions": True,
    "governance_preview": True,
    "manual_review_queue": True,
    "explicit_promote": True,
    "warehouse_list": True,
    "capsule_status_update": True,
    "generate_with_warehouse_capsules": True,
    "capsule_content_enrichment": True,
    "controlled_snippet_preview": True,
    "capsule_content_viewer": True,
    "content_aware_generate": True,
    "preview_package_viewer": True,
    "preview_package_compare": True,
    "preview_package_export": True,
    "preview_package_archive": True,
    "promote_suggestion_to_warehouse": False,
    "recovery_promote": False,
    "dispatch": False,
    "governance_apply": False,
    "write_source_folder": False,
    "llm_generation": False,
}

LUMO_BUSINESS_CAPABILITIES: dict[str, bool] = {
    "prepare": False,
    "reuse_pack": False,
    "generate_preview": False,
    "pym_index_pack": False,
    "verify_suggestions": True,
    "governance_preview": False,
    "manual_review_queue": True,
    "explicit_promote": True,
    "warehouse_list": True,
    "capsule_status_update": True,
    "generate_with_warehouse_capsules": True,
    "capsule_content_enrichment": True,
    "controlled_snippet_preview": True,
    "capsule_content_viewer": True,
    "content_aware_generate": True,
    "preview_package_viewer": True,
    "preview_package_compare": True,
    "preview_package_export": True,
    "preview_package_archive": True,
    "promote_suggestion_to_warehouse": False,
    "recovery_promote": False,
    "dispatch": False,
    "governance_apply": False,
    "llm_generation": False,
    "write_source_folder": False,
}


def local_engine_status() -> dict[str, Any]:
    return {
        "engine": "local",
        "available": True,
        "capabilities": dict(LOCAL_CAPABILITIES),
    }


def lumo_engine_status(luna_health: dict[str, Any]) -> dict[str, Any]:
    luna_ok = bool(luna_health.get("ok"))
    capabilities: dict[str, Any] = dict(LUMO_BUSINESS_CAPABILITIES)
    capabilities["health_probe"] = luna_ok
    if luna_ok:
        capabilities["pym_index_pack"] = True
        capabilities["reuse_pack"] = True
        capabilities["generate_preview"] = "pack_only"
        capabilities["prepare"] = "local_plus_luna_reuse_pack"
        capabilities["governance_preview"] = "local_plus_luna_preview"
        capabilities["promote_suggestion_to_warehouse"] = "manual_only"
        capabilities["recovery_promote"] = False
    return {
        "engine": "lumo",
        "available": luna_ok,
        "luna": dict(luna_health),
        "capabilities": capabilities,
    }
