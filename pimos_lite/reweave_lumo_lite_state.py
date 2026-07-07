"""Read-only adapter for Lumo Lite frontend runtime state."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

STATE_PATH_ENV = "REWEAVE_LUMO_LITE_STATE_PATH"
LEGACY_STATE_PATH_ENV = "LUMO_LITE_FRONTEND_RUNTIME_STATE"


def lumo_lite_state_path() -> Path | None:
    """Return the configured Lumo Lite frontend runtime state path."""

    raw = os.environ.get(STATE_PATH_ENV) or os.environ.get(LEGACY_STATE_PATH_ENV)
    if not raw or not raw.strip():
        return None
    return Path(raw).expanduser().resolve()


def load_lumo_lite_runtime_state(path: str | Path | None = None) -> dict[str, Any]:
    """Load local frontend_runtime_state.json without mutating it."""

    state_path = Path(path).expanduser().resolve() if path is not None else lumo_lite_state_path()
    if state_path is None:
        return {
            "ok": False,
            "status": "unconfigured",
            "error": f"missing {STATE_PATH_ENV}",
        }
    if not state_path.is_file():
        return {
            "ok": False,
            "status": "missing",
            "path": str(state_path),
            "error": "frontend_runtime_state.json not found",
        }
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "status": "invalid_json",
            "path": str(state_path),
            "error": str(exc)[:200],
        }
    except OSError as exc:
        return {
            "ok": False,
            "status": "read_failed",
            "path": str(state_path),
            "error": str(exc)[:200],
        }
    if not isinstance(raw, dict):
        return {
            "ok": False,
            "status": "invalid_shape",
            "path": str(state_path),
            "error": "runtime state must be a JSON object",
        }
    return {
        "ok": True,
        "status": "available",
        "path": str(state_path),
        "state": raw,
    }


def capsule_warehouse_block(runtime_state: dict[str, Any]) -> dict[str, Any]:
    block = runtime_state.get("capsule_warehouse") if isinstance(runtime_state, dict) else None
    return dict(block) if isinstance(block, dict) else {}


def lumo_lite_capsule_warehouse(runtime_state: dict[str, Any], *, state_path: str = "") -> dict[str, Any]:
    return capsule_warehouse_block(runtime_state) or _warehouse_from_latest_report(runtime_state, state_path=state_path)


def map_capsule_warehouse_to_reweave_capsules(
    runtime_state: dict[str, Any],
    *,
    state_path: str = "",
) -> list[dict[str, Any]]:
    """Map Lumo Lite capsule warehouse rows to Reweave read-only capsules."""

    warehouse = lumo_lite_capsule_warehouse(runtime_state, state_path=state_path)
    selected = _capsule_rows(warehouse)
    if not selected:
        return []
    evidence_paths = _path_list(warehouse.get("evidence_package_paths"))
    blocked_reasons = _string_list(warehouse.get("blocked_reasons"))

    capsules: list[dict[str, Any]] = []
    for idx, item in enumerate(selected):
        item = dict(item) if isinstance(item, dict) else {"capsule_id": str(item or "")}
        raw_id = str(item.get("capsule_id") or item.get("id") or f"capsule_{idx}").strip()
        if not raw_id:
            continue
        title = str(item.get("title") or item.get("name") or raw_id).strip()
        source_box_id = str(item.get("source_box_id") or item.get("source_box") or "").strip()
        reason = str(item.get("reason") or item.get("selection_reason") or "").strip()
        digest = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:10]
        preview = [
            "Lumo Lite capsule warehouse receipt",
            f"capsule_id: {raw_id}",
        ]
        if source_box_id:
            preview.append(f"source_box_id: {source_box_id}")
        if reason:
            preview.append(f"reason: {reason}")
        if warehouse.get("status"):
            preview.append(f"warehouse_status: {warehouse.get('status')}")
        if warehouse.get("assembly_status"):
            preview.append(f"assembly_status: {warehouse.get('assembly_status')}")
        if warehouse.get("trace_path"):
            preview.append(f"trace_path: {warehouse.get('trace_path')}")
        for path in evidence_paths[:3]:
            preview.append(f"evidence: {path}")
        for blocked in blocked_reasons[:3]:
            preview.append(f"blocked: {blocked}")

        capsules.append(
            {
                "id": f"lumo_lite_{digest}",
                "name": _display_title(title),
                "type": "LumoLite",
                "serial": digest[:2].upper(),
                "icon": "◫",
                "source": {"source_id": source_box_id, "label": source_box_id or "Lumo Lite"},
                "source_id": source_box_id,
                "tags": ["lumo-lite", "capsule-warehouse", "read-only"],
                "role": reason or "Selected by Lumo Lite capsule warehouse",
                "preview": preview,
                "status": "read_only",
                "origin": "lumo_lite_capsule_warehouse",
                "risk": "read_only_external_state",
                "content_mode": "metadata_only",
                "lumo_lite_receipt": {
                    "capsule_id": raw_id,
                    "warehouse_status": str(warehouse.get("status") or ""),
                    "invocation_status": str(warehouse.get("invocation_status") or ""),
                    "assembly_status": str(warehouse.get("assembly_status") or ""),
                    "reason": reason,
                    "trace_path": str(warehouse.get("trace_path") or ""),
                    "evidence_package_paths": evidence_paths,
                    "blocked_reasons": blocked_reasons,
                    "frontend_runtime_state": state_path,
                },
                "lineage": {
                    "lumo_lite_capsule_id": raw_id,
                    "frontend_runtime_state": state_path,
                    "source_box_id": source_box_id,
                },
            }
        )
    return capsules


def lumo_lite_source_boxes(runtime_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Build read-only source box rows from capsule_warehouse source_box_ids."""

    warehouse = capsule_warehouse_block(runtime_state)
    source_ids = warehouse.get("source_box_ids")
    if not isinstance(source_ids, list):
        return []
    boxes: list[dict[str, Any]] = []
    for raw in source_ids:
        source_id = str(raw or "").strip()
        if not source_id:
            continue
        boxes.append(
            {
                "id": source_id,
                "label": source_id,
                "status": "read_only",
                "scan_status": "read_only",
                "draft_status": "read_only",
                "warehouse_status": "read_only",
            }
        )
    return boxes


def _capsule_rows(warehouse: dict[str, Any]) -> list[Any]:
    for key in ("selected_capsules", "retrieved_capsules", "capsules_used"):
        rows = warehouse.get(key)
        if isinstance(rows, list) and rows:
            return rows
    return []


def _display_title(title: str) -> str:
    if title.startswith("product_") and title.endswith(" capsule"):
        return title.removeprefix("product_").removesuffix(" capsule").replace("_", " ").title()
    return title


def _warehouse_from_latest_report(runtime_state: dict[str, Any], *, state_path: str = "") -> dict[str, Any]:
    acceptance = runtime_state.get("capsule_product_acceptance") if isinstance(runtime_state, dict) else None
    if not isinstance(acceptance, dict):
        return {}
    report_path = _resolve_near(str(acceptance.get("latest_live_report_path") or ""), state_path)
    if report_path is None:
        return {}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    selected: list[dict[str, Any]] = []
    source_box_ids: list[str] = []
    seen: set[str] = set()
    trace_path = ""
    for row in report.get("cases") or []:
        if not isinstance(row, dict):
            continue
        artifacts = row.get("artifacts") if isinstance(row.get("artifacts"), dict) else {}
        trace_file = _resolve_near(str(artifacts.get("trace_path") or ""), str(report_path))
        if trace_file is None:
            continue
        try:
            trace = json.loads(trace_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not trace_path:
            trace_path = str(artifacts.get("trace_path") or trace_file)
        for capsule in trace.get("capsules_used") or []:
            if not isinstance(capsule, dict):
                continue
            capsule_id = str(capsule.get("capsule_id") or "").strip()
            if not capsule_id or capsule_id in seen:
                continue
            seen.add(capsule_id)
            source_box_id = str(capsule.get("source_box_id") or "").strip()
            if source_box_id and source_box_id not in source_box_ids:
                source_box_ids.append(source_box_id)
            selected.append(
                {
                    "capsule_id": capsule_id,
                    "title": str(capsule.get("title") or capsule_id),
                    "kind": str(capsule.get("kind") or "capability_trace"),
                    "source_box_id": source_box_id,
                    "reason": str(capsule.get("reason") or "used by capability trace"),
                    "selected_for_invocation": True,
                    "may_start_assembly": False,
                }
            )
    if not selected:
        return {}
    return {
        "mode": "capability_report_read_only",
        "status": "ready",
        "trace_status": "ready",
        "source_box_ids": source_box_ids,
        "selected_count": len(selected),
        "selected_capsules": selected,
        "retrieved_capsules": [row["capsule_id"] for row in selected],
        "capsules_used": [row["capsule_id"] for row in selected],
        "trace_path": trace_path,
        "blocked_reasons": [],
    }


def _resolve_near(raw: str, anchor: str = "") -> Path | None:
    if not raw.strip():
        return None
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path if path.is_file() else None
    base = Path(anchor).expanduser().resolve().parent if anchor else Path.cwd()
    for parent in (base, *base.parents):
        candidate = parent / path
        if candidate.is_file():
            return candidate
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _path_list(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [str(path).strip() for path in value.values() if str(path).strip()]
    return _string_list(value)
