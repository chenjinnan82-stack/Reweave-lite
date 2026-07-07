"""Local Reweave engine — registry, scan, draft, warehouse (no Lumo)."""

from __future__ import annotations

from typing import Any

from pimos_lite.reweave_preview_pack import build_preview_package, load_latest_preview
from pimos_lite.reweave_capsule_draft import draft_capsules, list_draft_lights
from pimos_lite.reweave_capsule_warehouse import list_capsules, promote_source_drafts
from pimos_lite.reweave_source_registry import add_source_box, get_source_box, list_source_boxes
from pimos_lite.reweave_source_scanner import list_summary_lights
from pimos_lite.reweave_source_scanner import scan_source_box as execute_source_scan
from pimos_lite.reweave_engine.status import local_engine_status

APP_VERSION = "0.3.0"


class LocalReweaveEngine:
    """Facade for desktop shell bridge calls."""

    def get_initial_state(self) -> dict[str, Any]:
        capsules = list_capsules()
        latest = load_latest_preview()
        state: dict[str, Any] = {
            "mode": "desktop_app",
            "backend": "local",
            "engine": "local",
            "engineStatus": local_engine_status(),
            "bridge": True,
            "appVersion": APP_VERSION,
            "skipWelcome": True,
            "canChooseSourceFolder": True,
            "canScanSourceBox": True,
            "canDraftCapsules": True,
            "canPromoteDrafts": True,
            "canGeneratePreview": True,
            "canOpenPreviewFolder": True,
            "useLocalCapsules": len(capsules) > 0,
            "sourceBoxes": list_source_boxes(),
            "sourceSummaries": list_summary_lights(),
            "capsuleDrafts": list_draft_lights(),
            "capsules": capsules,
        }
        if latest:
            state["lastPreview"] = latest
            state["generatedPackage"] = latest.get("generatedPackage")
            state["previewPath"] = latest.get("previewPath")
        return state

    def bind_source_folder(self, path: str) -> dict[str, Any]:
        return add_source_box(path)

    def scan_source(self, source_id: str) -> dict[str, Any]:
        return execute_source_scan(source_id)

    def draft_source(self, source_id: str) -> dict[str, Any]:
        return draft_capsules(source_id)

    def promote_source(self, source_id: str) -> list[dict[str, Any]]:
        return promote_source_drafts(source_id)

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        return get_source_box(source_id)

    def generate_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(payload)
        enriched.setdefault("backend", "local")
        return build_preview_package(enriched)
