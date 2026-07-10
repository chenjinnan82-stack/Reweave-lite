"""Reweave app service — consistent initial state + engine delegation."""

from __future__ import annotations

from typing import Any

from pimos_lite.reweave_engine.factory import ReweaveEngine, create_reweave_engine
from pimos_lite.reweave_engine.local import LocalReweaveEngine
from pimos_lite.reweave_capsule_draft import load_draft
from pimos_lite.reweave_capsule_warehouse import list_warehouse_capsules, update_capsule_status as apply_capsule_status
from pimos_lite.reweave_capsule_verifier import load_verification, verify_and_save
from pimos_lite.reweave_governance_preview import load_governance_preview, preview_and_save
from pimos_lite.reweave_review_queue import (
    create_or_update_review_queue,
    update_review_decision as apply_review_decision,
)
from pimos_lite.reweave_capsule_content import (
    enrich_capsule_content as execute_capsule_content_enrichment,
    get_capsule_content as fetch_capsule_content,
)
from pimos_lite.reweave_promote import promote_review_item as execute_promote_review_item
from pimos_lite.reweave_engine.lumo import LumoReweaveEngine
from pimos_lite.reweave_luna_client import LunaHttpClient
from pimos_lite.reweave_preview_pack import attach_luna_provenance, build_luna_provenance_record
from pimos_lite.reweave_preview_viewer import (
    compare_preview_packages as compare_preview_packages_view,
    get_latest_preview_package as fetch_latest_preview_package,
    get_preview_package as fetch_preview_package,
)
from pimos_lite.reweave_preview_export import export_preview_package as execute_preview_export
from pimos_lite.reweave_reuse_suggestions import build_reuse_suggestions_record, load_reuse_suggestions, save_reuse_suggestions
from pimos_lite.reweave_source_registry import get_source_box
from pimos_lite.reweave_source_scanner import load_summary

APP_SERVICE_VERSION = "v0"
LUMO_LITE_MODE = "source_read_only_preview_write"
PUBLIC_PRODUCT_ACTIONS = frozenset(
    {
        "get_initial_state",
        "bind_source_folder",
        "scan_source",
        "draft_source",
        "promote_source",
        "get_source",
        "enrich_capsule_content",
        "get_capsule_content",
        "generate_preview",
        "list_lumo_lite_artifacts",
        "get_lumo_lite_artifact",
        "get_lumo_lite_artifact_path",
    }
)
LEGACY_WORKBENCH_ACTIONS = frozenset(
    {
        "verify_source_suggestions",
        "preview_governance_for_source",
        "create_review_queue_for_source",
        "update_review_decision",
        "promote_review_item",
        "list_warehouse_capsules",
        "update_capsule_status",
        "export_preview_package",
    }
)
SUPPORT_VIEWER_ACTIONS = frozenset(
    {
        "get_latest_preview_package",
        "get_preview_package",
        "compare_preview_packages",
    }
)


def release_boundary_for_action(action: str) -> str:
    if action in PUBLIC_PRODUCT_ACTIONS:
        return "public_product"
    if action in LEGACY_WORKBENCH_ACTIONS:
        return "legacy_workbench"
    if action in SUPPORT_VIEWER_ACTIONS:
        return "support_viewer"
    return "unknown"


def public_product_actions() -> tuple[str, ...]:
    return tuple(sorted(PUBLIC_PRODUCT_ACTIONS))


def legacy_workbench_actions() -> tuple[str, ...]:
    return tuple(sorted(LEGACY_WORKBENCH_ACTIONS))


class ReweaveAppService:
    """Thin facade over ReweaveEngine; enriches get_initial_state metadata."""

    def __init__(self, engine: ReweaveEngine | None = None) -> None:
        self._engine = engine or create_reweave_engine()

    @property
    def engine(self) -> ReweaveEngine:
        return self._engine

    def _is_lumo_lite(self) -> bool:
        return self._engine.__class__.__name__ == "LumoLiteReweaveEngine"

    def _is_lumo(self) -> bool:
        return self._engine.__class__.__name__ == "LumoReweaveEngine"

    def _lumo_lite_disabled(self, action: str, **extra: Any) -> dict[str, Any]:
        result = {
            "ok": False,
            "engine": "lumo_lite",
            "mode": LUMO_LITE_MODE,
            "error": "lumo_lite_read_only",
            "action": action,
            "release_boundary": release_boundary_for_action(action),
        }
        result.update(extra)
        return result

    def get_initial_state(self) -> dict[str, Any]:
        state = self._engine.get_initial_state()
        if state.get("engine") != "lumo_lite" and state.get("backend") != "lumo_lite":
            warehouse_caps = list_warehouse_capsules(include_inactive=True)
            state["warehouseCapsules"] = warehouse_caps
            if warehouse_caps:
                state["capsules"] = warehouse_caps
                state["useLocalCapsules"] = True
        state["appService"] = APP_SERVICE_VERSION
        state.setdefault("engine", state.get("backend", "local"))
        if "engineStatus" not in state:
            state["engineStatus"] = {
                "engine": state.get("engine", "local"),
                "available": True,
                "capabilities": {},
            }
        return state

    def bind_source_folder(self, path: str) -> dict[str, Any]:
        return self._engine.bind_source_folder(path)

    def scan_source(self, source_id: str) -> dict[str, Any]:
        return self._engine.scan_source(source_id)

    def draft_source(self, source_id: str) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._engine.draft_source(source_id)
        if not self._is_lumo():
            return self._engine.draft_source(source_id)
        return self._draft_source_lumo(source_id)

    def promote_source(self, source_id: str) -> Any:
        if self._is_lumo_lite():
            return self._engine.promote_source(source_id)
        if not self._is_lumo():
            return self._engine.promote_source(source_id)
        return LocalReweaveEngine().promote_source(source_id)

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        return self._engine.get_source(source_id)

    def verify_source_suggestions(self, source_id: str) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._lumo_lite_disabled("verify_source_suggestions")
        source_id = (source_id or "").strip()
        if not source_id:
            return {"ok": False, "error": "missing source_id"}

        if not get_source_box(source_id):
            return {"ok": False, "error": "source_not_found", "source_id": source_id}

        summary = load_summary(source_id)
        if not summary:
            return {"ok": False, "error": "source_not_scanned", "source_id": source_id}

        reuse_record = load_reuse_suggestions(source_id)
        suggestions = (
            reuse_record.get("mapped_capsuleSuggestions")
            if isinstance(reuse_record, dict)
            else None
        )
        if not reuse_record or not isinstance(suggestions, list) or not suggestions:
            return {"ok": False, "error": "no_reuse_suggestions", "source_id": source_id}

        draft = load_draft(source_id)
        verification = verify_and_save(source_id, summary, reuse_record, draft)
        return {
            "ok": True,
            "source_id": source_id,
            "mode": verification.get("mode"),
            "verification": verification,
            "summary": verification.get("summary"),
        }

    def preview_governance_for_source(self, source_id: str) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._lumo_lite_disabled("preview_governance_for_source")
        source_id = (source_id or "").strip()
        if not source_id:
            return {"ok": False, "error": "missing source_id"}

        if not get_source_box(source_id):
            return {"ok": False, "error": "source_not_found", "source_id": source_id}

        verification = load_verification(source_id)
        if not verification:
            return {"ok": False, "error": "no_verification", "source_id": source_id}

        reuse_record = load_reuse_suggestions(source_id)
        suggestions = (
            reuse_record.get("mapped_capsuleSuggestions")
            if isinstance(reuse_record, dict)
            else None
        )
        if not reuse_record or not isinstance(suggestions, list) or not suggestions:
            return {"ok": False, "error": "no_reuse_suggestions", "source_id": source_id}

        summary = load_summary(source_id)
        draft = load_draft(source_id)
        warnings: list[str] = []
        luna_preview_block: dict[str, Any] | None = None

        if self._is_lumo():
            client = LunaHttpClient()
            if client.health().get("ok"):
                luna_result = client.governance_preview({"stale_days": 30, "include_blocked": False})
                if luna_result.get("ok"):
                    luna_preview_block = {
                        "endpoint": luna_result.get("endpoint"),
                        "raw": luna_result.get("raw"),
                    }
                else:
                    warnings.append("luna_governance_preview_failed")

        preview = preview_and_save(
            source_id,
            verification,
            reuse_record,
            summary,
            draft,
            luna_preview=luna_preview_block,
            warnings=warnings,
        )
        return {
            "ok": True,
            "source_id": source_id,
            "mode": preview.get("mode"),
            "preview": preview,
            "summary": preview.get("summary"),
            "warnings": warnings,
        }

    def create_review_queue_for_source(self, source_id: str) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._lumo_lite_disabled("create_review_queue_for_source")
        source_id = (source_id or "").strip()
        if not source_id:
            return {"ok": False, "error": "missing source_id"}

        if not get_source_box(source_id):
            return {"ok": False, "error": "source_not_found", "source_id": source_id}

        governance_preview = load_governance_preview(source_id)
        if not governance_preview:
            return {"ok": False, "error": "no_governance_preview", "source_id": source_id}

        verification = load_verification(source_id)
        queue = create_or_update_review_queue(source_id, governance_preview, verification)
        preview_items = [
            {
                "review_id": item.get("review_id"),
                "name": item.get("name"),
                "governance_action": item.get("governance_action"),
                "verification_score": item.get("verification_score"),
                "decision": item.get("decision"),
            }
            for item in (queue.get("items") or [])[:3]
            if isinstance(item, dict)
        ]
        return {
            "ok": True,
            "source_id": source_id,
            "mode": queue.get("mode"),
            "queue": queue,
            "summary": queue.get("summary"),
            "preview_items": preview_items,
        }

    def update_review_decision(
        self,
        source_id: str,
        review_id: str,
        decision: str,
        reason: str = "",
    ) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._lumo_lite_disabled("update_review_decision")
        source_id = (source_id or "").strip()
        review_id = (review_id or "").strip()
        if not source_id or not review_id:
            return {"ok": False, "error": "missing source_id or review_id"}

        try:
            result = apply_review_decision(source_id, review_id, decision, reason)
        except FileNotFoundError:
            return {"ok": False, "error": "no_review_queue", "source_id": source_id}
        except KeyError:
            return {"ok": False, "error": "review_item_not_found", "source_id": source_id, "review_id": review_id}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)[:200], "source_id": source_id}

        return {
            "ok": True,
            "source_id": source_id,
            "review_id": review_id,
            "item": result.get("item"),
            "summary": result.get("summary"),
        }

    def promote_review_item(self, source_id: str, review_id: str) -> dict[str, Any]:
        """Explicit promote — approved review item to local warehouse only."""
        if self._is_lumo_lite():
            return self._lumo_lite_disabled("promote_review_item")
        result = execute_promote_review_item(source_id, review_id)
        if result.get("ok"):
            result["warehouseCapsules"] = list_warehouse_capsules(include_inactive=True)
            result["capsules"] = result["warehouseCapsules"]
        return result

    def list_warehouse_capsules(self, *, include_inactive: bool = True) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._lumo_lite_disabled("list_warehouse_capsules", capsules=[], count=0)
        capsules = list_warehouse_capsules(include_inactive=include_inactive)
        return {"ok": True, "capsules": capsules, "count": len(capsules)}

    def update_capsule_status(self, capsule_id: str, status: str) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._lumo_lite_disabled(
                "update_capsule_status",
                capsule_id=(capsule_id or "").strip(),
            )
        capsule_id = (capsule_id or "").strip()
        status = (status or "").strip()
        if not capsule_id or not status:
            return {"ok": False, "error": "missing capsule_id or status"}
        try:
            return apply_capsule_status(capsule_id, status)
        except KeyError:
            return {"ok": False, "error": "capsule_not_found", "capsule_id": capsule_id}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)[:200], "capsule_id": capsule_id}

    def enrich_capsule_content(self, capsule_id: str) -> dict[str, Any]:
        """Explicit controlled snippet enrichment — read-only, user triggered."""
        if self._is_lumo_lite():
            return self._engine.enrich_capsule_content(capsule_id)
        return execute_capsule_content_enrichment(capsule_id)

    def get_capsule_content(self, capsule_id: str) -> dict[str, Any]:
        """Read enriched content from app state — viewer only, no source folder access."""
        if self._is_lumo_lite():
            return self._engine.get_capsule_content(capsule_id)
        return fetch_capsule_content(capsule_id)

    def get_latest_preview_package(self) -> dict[str, Any]:
        """Read-only viewer for the most recent preview package."""
        if self._is_lumo_lite():
            return fetch_latest_preview_package()
        return fetch_latest_preview_package()

    def get_preview_package(self, package_id_or_path: str) -> dict[str, Any]:
        """Read-only viewer for a specific preview package."""
        if self._is_lumo_lite():
            return fetch_preview_package(package_id_or_path)
        return fetch_preview_package(package_id_or_path)

    def compare_preview_packages(self, left_id: str = "", right_id: str = "") -> dict[str, Any]:
        """Metadata-only compare between two preview packages."""
        if self._is_lumo_lite():
            return compare_preview_packages_view(left_id, right_id)
        return compare_preview_packages_view(left_id, right_id)

    def export_preview_package(
        self,
        package_id_or_path: str,
        export_dir: str,
        mode: str = "zip",
    ) -> dict[str, Any]:
        """Export preview package to user-chosen directory (zip or copy)."""
        if self._is_lumo_lite():
            return self._lumo_lite_disabled("export_preview_package")
        return execute_preview_export(package_id_or_path, export_dir, mode=mode)

    def list_lumo_lite_artifacts(self) -> dict[str, Any]:
        if hasattr(self._engine, "list_lumo_lite_artifacts"):
            return self._engine.list_lumo_lite_artifacts()  # type: ignore[attr-defined]
        return {"ok": False, "error": "lumo_lite_artifacts_unavailable"}

    def get_lumo_lite_artifact(self, artifact_id_or_path: str) -> dict[str, Any]:
        if hasattr(self._engine, "get_lumo_lite_artifact"):
            return self._engine.get_lumo_lite_artifact(artifact_id_or_path)  # type: ignore[attr-defined]
        return {"ok": False, "error": "lumo_lite_artifact_unavailable"}

    def get_lumo_lite_artifact_path(self, artifact_id_or_path: str) -> str | None:
        if hasattr(self._engine, "get_lumo_lite_artifact_path"):
            return self._engine.get_lumo_lite_artifact_path(artifact_id_or_path)  # type: ignore[attr-defined]
        return None

    def generate_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._is_lumo_lite():
            return self._engine.generate_preview(payload)
        if not self._is_lumo():
            return self._engine.generate_preview(payload)
        return self._generate_preview_lumo(payload)

    def _generate_preview_lumo(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Local preview first, then optional Luna index-pack provenance (no dispatch)."""
        local = LocalReweaveEngine()
        local_payload = dict(payload)
        local_payload["backend"] = "lumo"

        try:
            local_result = local.generate_preview(local_payload)
        except Exception as exc:
            return {
                "ok": False,
                "engine": "lumo",
                "mode": "pack_only",
                "error": str(exc)[:200],
            }

        if not local_result.get("ok"):
            return local_result

        preview_path = local_result.get("previewPath")
        pack_payload = dict(payload)
        pack_payload["_localPreview"] = local_result
        luna_result = self._engine.generate_preview(pack_payload)

        merged = dict(local_result)
        merged["engine"] = "lumo"
        merged["mode"] = "pack_only"
        merged["dispatch"] = False

        if luna_result.get("ok"):
            luna_record = build_luna_provenance_record(luna_result, success=True)
            if preview_path:
                merged["provenance"] = attach_luna_provenance(preview_path, luna_record)
            merged["lunaPack"] = luna_result.get("lunaPack")
            merged["warnings"] = list(luna_result.get("warnings") or [])
            if not merged["warnings"]:
                merged["warnings"] = ["pack_only — no dispatch or LLM generation"]
            if merged.get("generatedPackage") and isinstance(merged["generatedPackage"].get("stats"), dict):
                merged["generatedPackage"]["stats"]["lunaPack"] = (
                    (merged.get("lunaPack") or {}).get("pack_id") or "indexed"
                )
            return merged

        luna_record = build_luna_provenance_record(luna_result, success=False)
        if preview_path:
            try:
                merged["provenance"] = attach_luna_provenance(preview_path, luna_record)
            except (FileNotFoundError, ValueError):
                pass
        merged["warnings"] = ["luna_index_pack_failed"]
        merged["lunaPack"] = None
        merged["lunaIndexError"] = luna_result.get("error")
        return merged

    def _draft_source_lumo(self, source_id: str) -> dict[str, Any]:
        """Local draft first, then Luna reuse-pack suggestions (never warehouse)."""
        local = LocalReweaveEngine()
        try:
            local_draft = local.draft_source(source_id)
        except Exception:
            raise

        merged = dict(local_draft)
        merged["engine"] = "lumo"
        merged["mode"] = "local_plus_luna_reuse_pack"
        merged["warnings"] = []

        if not isinstance(self._engine, LumoReweaveEngine):
            return merged

        luna_result = self._engine.prepare_reuse_pack({"source_id": source_id, "_localDraft": local_draft})
        if luna_result.get("ok"):
            suggestions = list(luna_result.get("capsuleSuggestions") or [])
            merged["capsuleSuggestions"] = suggestions
            merged["lunaReuse"] = {
                "assets_count": luna_result.get("assets_count", 0),
                "endpoint": luna_result.get("endpoint"),
            }
            reuse_result = luna_result.get("reuseResult") if isinstance(luna_result.get("reuseResult"), dict) else {}
            query_payload = luna_result.get("reuseRequest") if isinstance(luna_result.get("reuseRequest"), dict) else {}
            record = build_reuse_suggestions_record(
                source_id,
                query_payload=query_payload,
                reuse_result=reuse_result,
                capsule_suggestions=suggestions,
                warnings=[],
                luna_ok=True,
            )
            save_reuse_suggestions(source_id, record)
            return merged

        merged["warnings"] = ["luna_reuse_pack_failed"]
        merged["lunaReuseError"] = luna_result.get("error")
        query_payload = {}
        if isinstance(luna_result.get("reuseRequest"), dict):
            query_payload = luna_result["reuseRequest"]
        record = build_reuse_suggestions_record(
            source_id,
            query_payload=query_payload,
            reuse_result={"ok": False, "error": luna_result.get("error"), "assets": []},
            capsule_suggestions=[],
            warnings=["luna_reuse_pack_failed"],
            luna_ok=False,
        )
        save_reuse_suggestions(source_id, record)
        return merged
