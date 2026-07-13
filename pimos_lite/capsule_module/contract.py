from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


MODULE_CAPSULE_VERSION = "module_capsule.v1"
ALLOWED_STATUSES = {"candidate", "review_required", "active", "quarantine", "disabled"}
PAYLOAD_KEYS = ("fragment_bundle", "slot_patch", "ui_subtree", "data_records")
FALSE_PERMISSIONS = ("model_call", "network_call", "workspace_write", "store_write", "capsule_promotion_allowed")
PORT_GROUPS = ("inputs", "actions", "outputs", "state")
VALUE_TYPES = {"string", "number", "boolean", "selection", "record_list"}
EXPECTED_CHANGES = {"updated", "incremented", "decremented", "toggled", "appended"}


def load_module_capsules(path: Path) -> list[dict[str, Any]]:
    paths = sorted(path.glob("*.json")) if path.is_dir() else [path]
    rows: list[dict[str, Any]] = []
    for candidate in paths:
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("module_capsule_path_not_regular_file")
        data = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("module_capsule_not_object")
        rows.append(data)
    return rows


def validate_module_capsule(capsule: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    if capsule.get("module_capsule_version") != MODULE_CAPSULE_VERSION:
        errors.append(_error("unsupported_version", "module_capsule_version must be module_capsule.v1"))
    for key in ("module_capsule_id", "library_key", "module_kind"):
        if not _non_empty_str(capsule.get(key)):
            errors.append(_error(f"missing_{key}", f"{key} is required"))
    if capsule.get("status") not in ALLOWED_STATUSES:
        errors.append(_error("bad_status", "status is not supported"))
    if not _string_list(capsule.get("capability_tags")):
        errors.append(_error("missing_capability_tags", "capability_tags must contain strings"))
    _validate_governance(capsule.get("governance"), errors)
    _validate_payload(capsule.get("payload"), errors)
    if capsule.get("ports") is not None:
        _validate_ports(capsule.get("ports"), errors, module_kind=str(capsule.get("module_kind") or ""))
    _validate_provenance(capsule.get("provenance"), errors)
    permissions = capsule.get("permissions") if isinstance(capsule.get("permissions"), dict) else {}
    for key in FALSE_PERMISSIONS:
        if permissions.get(key) is not False:
            errors.append(_error(f"{key}_not_allowed", f"{key} must be false"))
    return {"valid": not errors, "errors": errors, "module_capsule_id": capsule.get("module_capsule_id")}


def compare_behavior_ports(ui_capsule: dict[str, Any], logic_capsule: dict[str, Any]) -> dict[str, Any]:
    ui = ui_capsule.get("ports") if isinstance(ui_capsule.get("ports"), dict) else {}
    logic = logic_capsule.get("ports") if isinstance(logic_capsule.get("ports"), dict) else {}
    blockers: list[str] = []
    if not ui or not logic:
        blockers.append("missing_behavior_ports")
    for owner, ports in (("ui", ui), ("logic", logic)):
        port_errors: list[dict[str, str]] = []
        _validate_ports(ports, port_errors)
        if port_errors:
            blockers.append(f"{owner}_ports_invalid")
    mappings: dict[str, list[dict[str, str]]] = {key: [] for key in PORT_GROUPS}
    for group in PORT_GROUPS:
        ui_rows = ui.get(group) if isinstance(ui.get(group), list) else []
        logic_rows = logic.get(group) if isinstance(logic.get(group), list) else []
        if len(ui_rows) != len(logic_rows):
            blockers.append(f"{group}_count_mismatch")
            continue
        pairs = list(zip(ui_rows, logic_rows))
        has_semantic_keys = any(
            isinstance(row, dict) and row.get("semantic_key") for row in [*ui_rows, *logic_rows]
        )
        if len(pairs) > 1 or has_semantic_keys:
            ui_by_key = {
                str(row.get("semantic_key") or ""): row for row in ui_rows if isinstance(row, dict) and row.get("semantic_key")
            }
            logic_keys = [
                str(row.get("semantic_key") or "") for row in logic_rows if isinstance(row, dict) and row.get("semantic_key")
            ]
            if len(ui_by_key) != len(ui_rows) or len(logic_keys) != len(logic_rows):
                blockers.append(f"{group}_semantic_mapping_required")
                continue
            if len(set(logic_keys)) != len(logic_keys) or set(ui_by_key) != set(logic_keys):
                blockers.append(f"{group}_semantic_key_mismatch")
                continue
            pairs = [(ui_by_key[key], logic_port) for key, logic_port in zip(logic_keys, logic_rows)]
        for index, (ui_port, logic_port) in enumerate(pairs):
            if not isinstance(ui_port, dict) or not isinstance(logic_port, dict):
                blockers.append(f"{group}_{index}_invalid")
                continue
            ui_type = str(ui_port.get("value_type") or "")
            logic_type = str(logic_port.get("value_type") or "")
            if group != "actions" and ui_type != logic_type:
                blockers.append(f"{group}_{index}_type_mismatch")
                continue
            mappings[group].append(
                {
                    "ui_port": str(ui_port.get("id") or ""),
                    "logic_port": str(logic_port.get("id") or ""),
                    **({"semantic_key": str(logic_port.get("semantic_key"))} if logic_port.get("semantic_key") else {}),
                    **({"value_type": ui_type} if ui_type else {}),
                }
            )

    ui_inputs = ui.get("inputs") if isinstance(ui.get("inputs"), list) else []
    logic_inputs = logic.get("inputs") if isinstance(logic.get("inputs"), list) else []
    if any(_mapping(row.get("read")).get("kind") != "dom_value" for row in ui_inputs if isinstance(row, dict)):
        blockers.append("ui_input_read_interface_invalid")
    if any(_mapping(row.get("read")).get("kind") != "argument" for row in logic_inputs if isinstance(row, dict)):
        blockers.append("logic_input_read_interface_invalid")

    ui_actions = ui.get("actions") if isinstance(ui.get("actions"), list) else []
    logic_actions = logic.get("actions") if isinstance(logic.get("actions"), list) else []
    if any(str(row.get("event") or "") == "call" for row in ui_actions if isinstance(row, dict)):
        blockers.append("ui_action_event_invalid")
    if any(str(row.get("event") or "") != "call" for row in logic_actions if isinstance(row, dict)):
        blockers.append("logic_action_event_invalid")

    ui_outputs = ui.get("outputs") if isinstance(ui.get("outputs"), list) else []
    logic_outputs = logic.get("outputs") if isinstance(logic.get("outputs"), list) else []
    if any(_mapping(row.get("write")).get("kind") != "dom_property" for row in ui_outputs if isinstance(row, dict)):
        blockers.append("ui_output_write_interface_invalid")
    if any(_mapping(row.get("write")).get("kind") != "return" for row in logic_outputs if isinstance(row, dict)):
        blockers.append("logic_output_write_interface_invalid")

    for owner, ports in (("ui", ui), ("logic", logic)):
        action_ids = {str(row.get("id") or "") for row in ports.get("actions", []) if isinstance(row, dict)}
        for row in ports.get("state", []):
            if isinstance(row, dict) and str(row.get("changes_on") or "") not in action_ids:
                blockers.append(f"{owner}_state_transition_invalid")
                break
    ui_state = ui.get("state") if isinstance(ui.get("state"), list) else []
    logic_state = logic.get("state") if isinstance(logic.get("state"), list) else []
    if any(
        str(left.get("expected_change") or "") != str(right.get("expected_change") or "")
        for left, right in zip(ui_state, logic_state)
        if isinstance(left, dict) and isinstance(right, dict)
    ):
        blockers.append("state_expected_change_mismatch")
    return {
        "status": "compatible" if not blockers else "incompatible",
        "mapping": mappings,
        "blockers": sorted(set(blockers)),
    }


def _validate_governance(value: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, dict):
        errors.append(_error("governance_not_object", "governance must be an object"))
        return
    for key in ("conflicts_with", "requires", "provides"):
        if not isinstance(value.get(key), list):
            errors.append(_error(f"governance_{key}_not_list", f"governance.{key} must be a list"))


def _validate_payload(value: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, dict):
        errors.append(_error("payload_not_object", "payload must be an object"))
        return
    if not any(value.get(key) for key in PAYLOAD_KEYS):
        errors.append(_error("payload_empty", "payload requires fragment_bundle, slot_patch, or ui_subtree"))
    fragment = value.get("fragment_bundle")
    if fragment is not None:
        _validate_fragment_bundle(fragment, errors)
    patch = value.get("slot_patch")
    if patch is not None and not isinstance(patch, dict):
        errors.append(_error("slot_patch_not_object", "slot_patch must be an object"))
    subtree = value.get("ui_subtree")
    if subtree is not None and not isinstance(subtree, dict):
        errors.append(_error("ui_subtree_not_object", "ui_subtree must be an object"))
    elif subtree is not None:
        _validate_ui_subtree(subtree, errors)
    records = value.get("data_records")
    if records is not None:
        _validate_data_records(records, errors)


def _validate_ports(value: Any, errors: list[dict[str, str]], *, module_kind: str = "") -> None:
    if not isinstance(value, dict):
        errors.append(_error("ports_not_object", "ports must be an object"))
        return
    is_data = module_kind == "behavior_data"
    for group in PORT_GROUPS:
        rows = value.get(group)
        if not isinstance(rows, list):
            errors.append(_error(f"ports_{group}_empty", f"ports.{group} must be a non-empty list"))
            continue
        if not rows:
            if is_data and group in {"inputs", "actions", "state"}:
                continue
            errors.append(_error(f"ports_{group}_empty", f"ports.{group} must be a non-empty list"))
            continue
        ids: set[str] = set()
        semantic_keys: set[str] = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or not _non_empty_str(row.get("id")):
                errors.append(_error(f"ports_{group}_{index}_invalid", f"ports.{group}[{index}] requires id"))
                continue
            port_id = str(row["id"])
            if port_id in ids:
                errors.append(_error(f"ports_{group}_duplicate_id", f"ports.{group} ids must be unique"))
            ids.add(port_id)
            semantic_key = row.get("semantic_key")
            if semantic_key is not None:
                if not _non_empty_str(semantic_key):
                    errors.append(_error(f"ports_{group}_{index}_bad_semantic_key", "semantic_key must be a non-empty string"))
                elif str(semantic_key) in semantic_keys:
                    errors.append(_error(f"ports_{group}_duplicate_semantic_key", f"ports.{group} semantic keys must be unique"))
                else:
                    semantic_keys.add(str(semantic_key))
            if group != "actions" and row.get("value_type") not in VALUE_TYPES:
                errors.append(_error(f"ports_{group}_{index}_bad_type", f"ports.{group}[{index}] has unsupported value_type"))
            if group == "inputs":
                read = _mapping(row.get("read"))
                if read.get("kind") not in {"dom_value", "argument"}:
                    errors.append(_error(f"ports_inputs_{index}_bad_read", "input read.kind must be dom_value or argument"))
                if read.get("kind") == "dom_value" and not _non_empty_str(read.get("selector")):
                    errors.append(_error(f"ports_inputs_{index}_missing_selector", "DOM input requires selector"))
            elif group == "actions":
                if row.get("event") not in {"click", "change", "input", "submit", "call", "timer"}:
                    errors.append(_error(f"ports_actions_{index}_bad_event", "action event is unsupported"))
                if not _non_empty_str(row.get("target")):
                    errors.append(_error(f"ports_actions_{index}_missing_target", "action requires target"))
            elif group == "outputs":
                write = _mapping(row.get("write"))
                if write.get("kind") not in {"dom_property", "return", "provide"}:
                    errors.append(_error(f"ports_outputs_{index}_bad_write", "output write.kind is unsupported"))
                if write.get("kind") == "dom_property" and (
                    not _non_empty_str(write.get("selector"))
                    or write.get("property") not in {"value", "textContent", "innerText", "checked"}
                ):
                    errors.append(_error(f"ports_outputs_{index}_bad_dom_write", "DOM output requires selector and supported property"))
                if write.get("kind") == "provide" and not is_data:
                    errors.append(_error(f"ports_outputs_{index}_unexpected_provider", "only data modules may provide records"))
            else:
                if not _non_empty_str(row.get("changes_on")):
                    errors.append(_error(f"ports_state_{index}_missing_transition", "state requires changes_on"))
                if row.get("expected_change") not in EXPECTED_CHANGES:
                    errors.append(_error(f"ports_state_{index}_bad_expected_change", "state expected_change is unsupported"))
                if not _value_matches_type(row.get("initial"), str(row.get("value_type") or "")):
                    errors.append(_error(f"ports_state_{index}_bad_initial", "state initial does not match value_type"))
    action_ids = {
        str(row.get("id") or "")
        for row in value.get("actions", [])
        if isinstance(row, dict) and row.get("id")
    }
    for index, row in enumerate(value.get("state", []) if isinstance(value.get("state"), list) else []):
        if isinstance(row, dict) and str(row.get("changes_on") or "") not in action_ids:
            errors.append(_error(f"ports_state_{index}_unknown_action", "state changes_on must reference an action id"))
    if is_data:
        outputs = value.get("outputs") if isinstance(value.get("outputs"), list) else []
        if len(outputs) != 1 or outputs[0].get("value_type") != "record_list" or _mapping(outputs[0].get("write")).get("kind") != "provide":
            errors.append(_error("data_module_output_invalid", "data module requires one provided record_list output"))
    collections = value.get("collections")
    if collections is not None:
        if not isinstance(collections, list) or not collections:
            errors.append(_error("ports_collections_empty", "ports.collections must be a non-empty list"))
        else:
            for index, row in enumerate(collections):
                write = _mapping(row.get("write")) if isinstance(row, dict) else {}
                fields = write.get("fields") if isinstance(write.get("fields"), list) else []
                if (
                    not isinstance(row, dict)
                    or not _non_empty_str(row.get("id"))
                    or row.get("value_type") != "record_list"
                    or write.get("kind") != "dom_table_rows"
                    or not _non_empty_str(write.get("selector"))
                    or not fields
                    or any(not _non_empty_str(field) for field in fields)
                ):
                    errors.append(_error(f"ports_collections_{index}_invalid", "collection requires a record_list table target and fields"))


def _validate_data_records(value: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != "record_list.v1":
        errors.append(_error("data_records_invalid", "data_records must use record_list.v1"))
        return
    fields = value.get("fields") if isinstance(value.get("fields"), list) else []
    records = value.get("records") if isinstance(value.get("records"), list) else []
    if not fields or len(fields) > 32 or not records or len(records) > 500:
        errors.append(_error("data_records_size_invalid", "data_records requires 1-32 fields and 1-500 records"))
        return
    schema: dict[str, str] = {}
    for row in fields:
        name = str(row.get("name") or "") if isinstance(row, dict) else ""
        value_type = str(row.get("value_type") or "") if isinstance(row, dict) else ""
        if not name or name in schema or value_type not in {"string", "number", "boolean"}:
            errors.append(_error("data_records_field_invalid", "data record fields require unique scalar names and types"))
            return
        schema[name] = value_type
    for row in records:
        if not isinstance(row, dict) or set(row) != set(schema) or any(not _value_matches_type(row[name], value_type) for name, value_type in schema.items()):
            errors.append(_error("data_records_row_invalid", "every data row must match the declared flat schema"))
            return


def _validate_fragment_bundle(value: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, dict):
        errors.append(_error("fragment_bundle_not_object", "fragment_bundle must be an object"))
        return
    if not isinstance(value.get("anchor_hooks"), list):
        errors.append(_error("anchor_hooks_not_list", "fragment_bundle.anchor_hooks must be a list"))
    files = value.get("files_partial")
    if not isinstance(files, list) or not files:
        errors.append(_error("files_partial_empty", "fragment_bundle.files_partial must be a non-empty list"))
        return
    for row in files:
        if not isinstance(row, dict) or not _safe_rel_path(row.get("path")) or not isinstance(row.get("content"), str):
            errors.append(_error("bad_file_partial", "file partials require safe relative path and string content"))


def _validate_ui_subtree(value: dict[str, Any], errors: list[dict[str, str]]) -> None:
    if value.get("schema_version") != "lite_ui_subtree.v1":
        errors.append(_error("bad_ui_subtree_schema_version", "ui_subtree.schema_version must be lite_ui_subtree.v1"))
    if value.get("root_component") not in {"Header", "List", "FormStep", "EmptyState", "SearchBar"}:
        errors.append(_error("unsupported_ui_subtree_root", "ui_subtree.root_component is not supported"))
    if not isinstance(value.get("props"), dict):
        errors.append(_error("ui_subtree_props_not_object", "ui_subtree.props must be an object"))


def _validate_provenance(value: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, dict):
        errors.append(_error("provenance_not_object", "provenance must be an object"))
        return
    if not _non_empty_str(value.get("source_preview_id")):
        errors.append(_error("missing_source_preview_id", "provenance.source_preview_id is required"))
    for key in ("source_capsule_ids", "evidence_refs"):
        if not isinstance(value.get(key), list):
            errors.append(_error(f"provenance_{key}_not_list", f"provenance.{key} must be a list"))


def _safe_rel_path(value: Any) -> bool:
    path = Path(str(value or ""))
    return bool(str(value or "").strip()) and not path.is_absolute() and ".." not in path.parts


def _string_list(value: Any) -> list[str]:
    return [str(row) for row in value or [] if isinstance(row, str) and row.strip()] if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _value_matches_type(value: Any, value_type: str) -> bool:
    if value_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type in {"string", "selection"}:
        return isinstance(value, str)
    if value_type == "record_list":
        return isinstance(value, list)
    return False


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


__all__ = ["MODULE_CAPSULE_VERSION", "compare_behavior_ports", "load_module_capsules", "validate_module_capsule"]
