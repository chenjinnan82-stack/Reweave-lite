"""Canonical Stage4 module-native composer owned by Reweave-lite.

This is the one-way migration of the minimal composer from Stage4 baseline
``ab8e62d``. The former Stage4 copy is historical reference only.
"""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from itertools import combinations, permutations
from pathlib import Path
from typing import Any

from pimos_lite.capsule_module import compare_behavior_ports, load_module_capsules, validate_module_capsule
from pimos_lite.composer.intent import build_intent_record
from pimos_lite.reweave_project_renderer import with_local_runtime_csp
from pimos_lite.safe_preview_write import write_preview_files


COMPOSITION_PLAN_VERSION = "lite_composition_plan.v1"
COMPOSER_VERSION = "lite_module_native_composer.v1"
CAPABILITY_GRAPH_VERSION = "module_capability_graph.v1"
_MAX_CAPABILITY_PLANS = 256
_MAX_MODEL_PLAN_CANDIDATES = 12
REGION_MERGE_CONTRACT_VERSION = "module_native_region_merge_contract.v1"
WIRING_RECEIPT_VERSION = "module_native_wiring_receipt.v1"
def compose_module_native_preview(
    *,
    goal: str,
    capsule_path: Path,
    capability_tags: list[str] | None = None,
    module_ids: list[str] | None = None,
    disabled_module_ids: list[str] | None = None,
    disabled_library_keys: list[str] | None = None,
    avoid_library_keys: list[str] | None = None,
    write_preview_root: Path | None = None,
    legacy_task_id: str = "",
    max_modules: int = 1,
    auto_behavior: bool = False,
    selected_plan_id: str = "",
) -> dict[str, Any]:
    capsules = load_module_capsules(capsule_path)
    all_capsules = list(capsules)
    intent = build_intent_record(goal=goal, capability_tags=capability_tags, legacy_task_id=legacy_task_id, max_modules=max_modules)
    requested_ids = _unique(_string_list(module_ids))
    selected_capability_plan: dict[str, Any] = {}
    if selected_plan_id:
        graph = build_module_capability_graph(all_capsules, goal=goal, max_modules=max_modules)
        selected_capability_plan = next(
            (dict(row) for row in graph["plans"] if row.get("plan_id") == selected_plan_id and row.get("currently_executable")),
            {},
        )
        if not selected_capability_plan or selected_capability_plan.get("module_ids") != requested_ids:
            return _rejected(
                intent=intent,
                rejected=[{"module_capsule_id": "", "reason": "selected_capability_plan_invalid"}],
            )
    if requested_ids:
        by_id = {str(row.get("module_capsule_id") or ""): row for row in capsules}
        missing = [module_id for module_id in requested_ids if module_id not in by_id]
        if missing:
            return _rejected(
                intent=intent,
                rejected=[{"module_capsule_id": module_id, "reason": "requested_module_not_found"} for module_id in missing],
            )
        capsules = [by_id[module_id] for module_id in requested_ids]
    if auto_behavior:
        selected_modules, rejected, selection_audit = _select_behavior_modules(
            capsules,
            goal=goal,
            max_modules=max_modules,
            disabled_module_ids=disabled_module_ids,
            disabled_library_keys=disabled_library_keys,
            avoid_library_keys=avoid_library_keys,
        )
    elif requested_ids:
        selected_modules, rejected, selection_audit = _select_requested_modules(
            capsules,
            max_modules=max(1, int(max_modules)),
            disabled_module_ids=disabled_module_ids,
            disabled_library_keys=disabled_library_keys,
            avoid_library_keys=avoid_library_keys,
        )
        if selected_capability_plan:
            selection_audit["selected_capability_plan"] = selected_capability_plan
    else:
        return _rejected(
            intent=intent,
            rejected=[{"module_capsule_id": "", "reason": "behavior_module_selection_required"}],
        )
    if not selected_modules:
        return _rejected(intent=intent, rejected=rejected, selection_audit=selection_audit)
    try:
        auto_selection = selection_audit.get("auto_behavior") if isinstance(selection_audit.get("auto_behavior"), dict) else {}
        selected_mode = str(selected_capability_plan.get("mode") or auto_selection.get("mode") or "")
        topology = {
            "branch": "fan_out",
            "fan_in": "fan_in",
        }.get(selected_mode, "serial")
        behavior_composition = _compose_behavior_modules(selected_modules, topology=topology)
        if behavior_composition is None:
            raise ValueError("behavior_modules_required")
        files = dict(behavior_composition["files"])
    except ValueError as exc:
        return _rejected(
            intent=intent,
            selection_audit=selection_audit,
            rejected=[
                *rejected,
                {"module_capsule_id": ",".join(row["module_capsule_id"] for row in selected_modules), "reason": f"compose_failed:{exc}"},
            ],
        )
    plan = _plan(
        intent=intent,
        selected_modules=selected_modules,
        rejected=rejected,
        selection_audit=selection_audit,
        behavior_composition=behavior_composition,
    )
    files["adapter_mapping.json"] = json.dumps(behavior_composition["adapter_mapping"], indent=2, ensure_ascii=False) + "\n"
    files["composition_plan.json"] = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    preview_write = write_preview_root is not None
    written = _write_files(files, write_preview_root) if preview_write else []
    return {
        "composer_version": COMPOSER_VERSION,
        "status": "composed",
        "composition_mode": "module_native",
        "composition_strategy": "behavior_adapter",
        "intent": intent,
        "composition_plan": plan,
        "rejection_summary": _rejection_summary(rejected),
        "selected_module_capsule_ids": [row["module_capsule_id"] for row in selected_modules],
        "requested_module_capsule_ids": requested_ids,
        "selected_capability_plan_id": str(selected_capability_plan.get("plan_id") or ""),
        "selection_mode": (
            "auto_behavior_data"
            if auto_behavior and behavior_composition.get("data_capsule_id")
            else
            "auto_behavior_graph_chain"
            if auto_behavior and len(selected_modules) > 3
            else
            "auto_behavior_chain"
            if auto_behavior and len(selected_modules) == 3
            else "auto_behavior_pair"
            if auto_behavior
            else "selected_capability_plan"
            if selected_capability_plan
            else "explicit"
        ),
        "files": files,
        "written_files": written,
        "permissions": _permissions(preview_write=preview_write),
        "effects": _effects(preview_write=preview_write),
        "default_desktop_path_changed": False,
    }


def _select_requested_modules(
    capsules: list[dict[str, Any]],
    *,
    max_modules: int,
    disabled_module_ids: list[str] | None = None,
    disabled_library_keys: list[str] | None = None,
    avoid_library_keys: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
    disabled_ids = set(_string_list(disabled_module_ids))
    disabled_keys = set(_string_list(disabled_library_keys))
    avoid_keys = set(_string_list(avoid_library_keys))
    rejected: list[dict[str, str]] = []
    if len(capsules) > max_modules:
        rejected.extend({"module_capsule_id": str(row.get("module_capsule_id") or ""), "reason": "module_budget_exceeded"} for row in capsules)
    for capsule in capsules:
        capsule_id = str(capsule.get("module_capsule_id") or "")
        library_key = str(capsule.get("library_key") or "")
        if not validate_module_capsule(capsule)["valid"]:
            rejected.append({"module_capsule_id": capsule_id, "reason": "invalid_capsule"})
        elif capsule.get("status") != "active":
            rejected.append({"module_capsule_id": capsule_id, "reason": "not_active"})
        elif capsule_id in disabled_ids or library_key in disabled_keys:
            rejected.append({"module_capsule_id": capsule_id, "reason": "disabled_by_capsule_library"})
        elif library_key in avoid_keys:
            rejected.append({"module_capsule_id": capsule_id, "reason": "avoid_by_capsule_library"})
    conflict_edges = _conflict_edges(capsules)
    if conflict_edges:
        rejected.extend(
            {"module_capsule_id": capsule_id, "reason": "conflicts_with_selected_module"}
            for capsule_id in _unique([edge["from"] for edge in conflict_edges] + [edge["to"] for edge in conflict_edges])
        )
    selected = [] if rejected else list(capsules)
    return selected, rejected, _selection_audit(
        candidates=capsules,
        selected=selected,
        max_modules=max_modules,
        conflict_edges=conflict_edges,
    )


def _select_behavior_modules(
    capsules: list[dict[str, Any]],
    *,
    goal: str,
    max_modules: int = 5,
    disabled_module_ids: list[str] | None = None,
    disabled_library_keys: list[str] | None = None,
    avoid_library_keys: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
    disabled_ids = set(_string_list(disabled_module_ids))
    disabled_keys = set(_string_list(disabled_library_keys))
    avoid_keys = set(_string_list(avoid_library_keys))
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for capsule in capsules:
        capsule_id = str(capsule.get("module_capsule_id") or "")
        library_key = str(capsule.get("library_key") or "")
        if not validate_module_capsule(capsule)["valid"]:
            rejected.append({"module_capsule_id": capsule_id, "reason": "invalid_capsule"})
        elif capsule.get("status") != "active":
            rejected.append({"module_capsule_id": capsule_id, "reason": "not_active"})
        elif capsule_id in disabled_ids or library_key in disabled_keys:
            rejected.append({"module_capsule_id": capsule_id, "reason": "disabled_by_capsule_library"})
        elif library_key in avoid_keys:
            rejected.append({"module_capsule_id": capsule_id, "reason": "avoid_by_capsule_library"})
        elif not isinstance(capsule.get("ports"), dict):
            rejected.append({"module_capsule_id": capsule_id, "reason": "not_behavior_module"})
        else:
            eligible.append(capsule)

    graph = build_module_capability_graph(eligible, goal=goal, max_modules=max_modules)
    rejected.extend(graph["rejected"])
    options = [row for row in graph["plans"] if row["currently_executable"]]
    if options:
        best_score = options[0]["score"]
        smallest = min(len(row["module_ids"]) for row in options if row["score"] == best_score)
        options = [row for row in options if row["score"] == best_score and len(row["module_ids"]) == smallest]
    selected: list[dict[str, Any]] = []
    auto_result: dict[str, Any] = {"status": "not_selected", "matched_terms": [], "score": 0}
    if not options or options[0]["score"] == 0:
        rejected.append({"module_capsule_id": "", "reason": "auto_behavior_no_task_match"})
    elif len(options) > 1 and options[0]["score"] == options[1]["score"]:
        rejected.append({"module_capsule_id": "", "reason": "auto_behavior_ambiguous"})
    else:
        plan = options[0]
        by_id = {str(row.get("module_capsule_id") or ""): row for row in eligible}
        selected = [by_id[module_id] for module_id in plan["module_ids"]]
        auto_result = {
            "status": "selected",
            "score": plan["score"],
            "matched_terms": plan["matched_terms"],
            "mode": plan["mode"],
            "plan_id": plan["plan_id"],
            "module_ids": plan["module_ids"],
        }
    audit = _selection_audit(candidates=eligible, selected=selected, max_modules=max_modules)
    audit["auto_behavior"] = auto_result
    audit["capability_graph"] = graph
    return selected, rejected, audit


def build_module_capability_graph(
    capsules: list[dict[str, Any]],
    *,
    goal: str,
    max_modules: int = 5,
) -> dict[str, Any]:
    """Plan closed behavior chains; writing remains owned by the composer."""
    limit = max(2, min(5, int(max_modules)))
    active: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for row in capsules:
        capsule_id = str(row.get("module_capsule_id") or "")
        if row.get("status") != "active":
            rejected.append({"module_capsule_id": capsule_id, "reason": "not_active"})
        elif not isinstance(row.get("ports"), dict):
            rejected.append({"module_capsule_id": capsule_id, "reason": "not_behavior_module"})
        elif not validate_module_capsule(row)["valid"]:
            rejected.append({"module_capsule_id": capsule_id, "reason": "invalid_capsule"})
        else:
            active.append(row)
    task_words = _behavior_task_words(goal)
    rank = lambda row: (-len(task_words & _behavior_module_words(row)), str(row.get("module_capsule_id") or ""))
    ui_rows = sorted((row for row in active if _port_role(row) == "ui"), key=rank)
    logic_rows = sorted((row for row in active if _port_role(row) == "logic"), key=rank)
    data_rows = sorted((row for row in active if _port_role(row) == "data"), key=rank)
    plans: list[dict[str, Any]] = []

    for ui in ui_rows:
        for logic in logic_rows:
            if len(plans) >= _MAX_CAPABILITY_PLANS:
                break
            pair_id = f"{ui.get('module_capsule_id')},{logic.get('module_capsule_id')}"
            compatibility = compare_behavior_ports(ui, logic)
            compatible = compatibility["status"] == "compatible"
            if compatible:
                base = _capability_plan([ui, logic], "pair", _pair_graph_edges(ui, logic, compatibility), task_words)
                plans.extend(
                    _extend_capability_plan(
                        base,
                        logic_rows,
                        task_words,
                        limit,
                        _MAX_CAPABILITY_PLANS - len(plans),
                    )
                )
                branch_plans = _branch_capability_plans(
                    base,
                    logic_rows,
                    task_words,
                    limit,
                    _MAX_CAPABILITY_PLANS - len(plans),
                )
                plans.extend(branch_plans)
                for branch_plan in branch_plans:
                    plans.extend(
                        _fan_in_capability_plans(
                            branch_plan,
                            logic_rows,
                            task_words,
                            limit,
                            _MAX_CAPABILITY_PLANS - len(plans),
                        )
                    )
            for data in data_rows:
                try:
                    mapping = _data_adapter_mapping(ui, data, logic)
                except ValueError:
                    continue
                compatible = True
                base = _capability_plan([ui, data, logic], "data", _data_graph_edges(ui, data, logic, mapping), task_words)
                plans.extend(
                    _extend_capability_plan(
                        base,
                        logic_rows,
                        task_words,
                        limit,
                        _MAX_CAPABILITY_PLANS - len(plans),
                    )
                )
                branch_plans = _branch_capability_plans(
                    base,
                    logic_rows,
                    task_words,
                    limit,
                    _MAX_CAPABILITY_PLANS - len(plans),
                )
                plans.extend(branch_plans)
                for branch_plan in branch_plans:
                    plans.extend(
                        _fan_in_capability_plans(
                            branch_plan,
                            logic_rows,
                            task_words,
                            limit,
                            _MAX_CAPABILITY_PLANS - len(plans),
                        )
                    )
            if not compatible:
                rejected.append({"module_capsule_id": pair_id, "reason": "incompatible_behavior_pair"})

    plan_limit_reached = len(plans) >= _MAX_CAPABILITY_PLANS
    plans = [row for row in plans if not _conflict_edges(row["_modules"])]
    unique = {(row["mode"], tuple(row["module_ids"])): row for row in plans}
    plans = sorted(unique.values(), key=lambda row: (-row["score"], len(row["module_ids"]), row["plan_id"]))
    for row in plans:
        row.pop("_modules", None)
    edges = {
        (edge["from"], edge["to"], edge["kind"]): edge
        for plan in plans
        for edge in plan["connections"]
    }
    return {
        "graph_version": CAPABILITY_GRAPH_VERSION,
        "goal": goal,
        "nodes": [_graph_node(row) for row in active],
        "edges": list(edges.values()),
        "plans": plans,
        "model_candidates": [
            {
                "id": row["plan_id"],
                "name": f"Composition plan ({len(row['module_ids'])} capsules)",
                "type": "Capsule composition plan",
                "tags": row["matched_terms"],
                "capabilitySummary": row["capability_summary"],
                "orderedSteps": row["ordered_steps"],
                "effectTrace": row["effect_trace"],
                "topology": row["topology"],
                "moduleIds": row["module_ids"],
                "currentlyExecutable": row["currently_executable"],
            }
            for row in plans
            if row["currently_executable"]
        ][:_MAX_MODEL_PLAN_CANDIDATES],
        "rejected": rejected,
        "max_modules": limit,
        "plan_limit_reached": plan_limit_reached,
    }


def _capability_plan(
    modules: list[dict[str, Any]],
    mode: str,
    connections: list[dict[str, str]],
    task_words: set[str],
) -> dict[str, Any]:
    module_ids = [str(row.get("module_capsule_id") or "") for row in modules]
    words = set().union(*(_behavior_module_words(row) for row in modules))
    matched = sorted(task_words & words)
    digest = hashlib.sha1(f"{mode}|{'|'.join(module_ids)}".encode("utf-8")).hexdigest()[:10]
    summaries = [str(row.get("capability_summary") or row.get("module_kind") or "") for row in modules]
    return {
        "plan_id": f"cap-plan-{digest}",
        "mode": mode,
        "module_ids": module_ids,
        "connections": connections,
        "score": len(matched),
        "matched_terms": matched,
        "capability_summary": " -> ".join(summary for summary in summaries if summary),
        "ordered_steps": [_behavior_step(row, index) for index, row in enumerate(modules, start=1)],
        "effect_trace": _effect_trace(modules, mode),
        "topology": "fan_in" if mode == "fan_in" else "fan_out" if mode == "branch" else "serial",
        "currently_executable": mode in {"pair", "data", "chain", "graph_chain", "branch", "fan_in"} and len(modules) <= 5,
        "source_project_write": False,
        "_modules": modules,
    }


def _effect_trace(modules: list[dict[str, Any]], mode: str) -> list[dict[str, str]]:
    actions = [
        str(_dict_list(_mapping(row.get("ports")).get("actions"))[0].get("target") or "")
        for row in modules
        if _port_role(row) == "logic"
    ]
    if len(actions) < 2:
        return []
    if mode == "branch":
        return [{"from_action": actions[0], "to_action": action} for action in actions[1:]]
    if mode == "fan_in" and len(actions) == 4:
        return [
            {"from_action": actions[0], "to_action": actions[1]},
            {"from_action": actions[0], "to_action": actions[2]},
            {"from_action": actions[1], "to_action": actions[3]},
            {"from_action": actions[2], "to_action": actions[3]},
        ]
    return [{"from_action": source, "to_action": target} for source, target in zip(actions, actions[1:])]


def _behavior_step(capsule: dict[str, Any], order: int) -> dict[str, Any]:
    ports = _mapping(capsule.get("ports"))
    action = next(iter(_dict_list(ports.get("actions"))), {})
    state = next(iter(_dict_list(ports.get("state"))), {})
    role = _port_role(capsule)
    return {
        "order": order,
        "role": role,
        "action": str((action.get("id") if role == "ui" else action.get("target")) or action.get("id") or ""),
        "event": str(action.get("event") or ""),
        "reads": [f"{row.get('semantic_key')}:{row.get('value_type')}" for row in _dict_list(ports.get("inputs"))],
        "writes": [f"{row.get('semantic_key')}:{row.get('value_type')}" for row in _dict_list(ports.get("outputs"))],
        "state_change": str(state.get("expected_change") or ""),
    }


def _extend_capability_plan(
    base: dict[str, Any],
    logic_rows: list[dict[str, Any]],
    task_words: set[str],
    max_modules: int,
    plan_budget: int,
) -> list[dict[str, Any]]:
    if plan_budget <= 0:
        return []
    plans = [base]
    if len(base["module_ids"]) >= max_modules:
        return plans
    previous = base["_modules"][-1]
    if _port_role(previous) != "logic":
        return plans
    for candidate in logic_rows:
        if len(plans) >= plan_budget:
            break
        candidate_id = str(candidate.get("module_capsule_id") or "")
        if candidate_id in base["module_ids"]:
            continue
        chain_edges = _logic_chain_edges(previous, candidate)
        if not chain_edges:
            continue
        modules = [*base["_modules"], candidate]
        mode = "chain" if len(modules) == 3 else "graph_chain"
        extended = _capability_plan(modules, mode, [*base["connections"], *chain_edges], task_words)
        extended["currently_executable"] = bool(base["currently_executable"])
        plans.extend(
            _extend_capability_plan(
                extended,
                logic_rows,
                task_words,
                max_modules,
                plan_budget - len(plans),
            )
        )
    return plans


def _branch_capability_plans(
    base: dict[str, Any],
    logic_rows: list[dict[str, Any]],
    task_words: set[str],
    max_modules: int,
    plan_budget: int,
) -> list[dict[str, Any]]:
    if plan_budget <= 0 or len(base["module_ids"]) + 2 > max_modules:
        return []
    primary = base["_modules"][-1]
    compatible = [
        (candidate, _logic_chain_edges(primary, candidate))
        for candidate in logic_rows
        if str(candidate.get("module_capsule_id") or "") not in base["module_ids"]
    ]
    compatible = [(candidate, edges) for candidate, edges in compatible if edges]
    plans: list[dict[str, Any]] = []
    for left, right in combinations(compatible, 2):
        if len(plans) >= plan_budget:
            break
        branches = sorted((left, right), key=lambda row: str(row[0].get("module_capsule_id") or ""))
        modules = [*base["_modules"], *(row[0] for row in branches)]
        connections = [*base["connections"], *(edge for row in branches for edge in row[1])]
        plans.append(_capability_plan(modules, "branch", connections, task_words))
    return plans


def _fan_in_capability_plans(
    branch_plan: dict[str, Any],
    logic_rows: list[dict[str, Any]],
    task_words: set[str],
    max_modules: int,
    plan_budget: int,
) -> list[dict[str, Any]]:
    if plan_budget <= 0 or len(branch_plan["module_ids"]) + 1 > max_modules:
        return []
    branches = branch_plan["_modules"][-2:]
    plans: list[dict[str, Any]] = []
    for merger in logic_rows:
        if str(merger.get("module_capsule_id") or "") in branch_plan["module_ids"]:
            continue
        bindings = _fan_in_bindings(branches, merger)
        if not bindings:
            continue
        merger_id = str(merger.get("module_capsule_id") or "")
        action = _dict_list(_mapping(merger.get("ports")).get("actions"))[0]
        output = _dict_list(_mapping(merger.get("ports")).get("outputs"))[0]
        state = _dict_list(_mapping(merger.get("ports")).get("state"))[0]
        connections = [*branch_plan["connections"]]
        connections.extend(
            {
                "from": f"{binding['from_module_id']}:{binding['from_output_port']}",
                "to": f"{merger_id}:{binding['to_input_port']}",
                "kind": "fan_in_input",
            }
            for binding in bindings
        )
        connections.extend(
            [
                {"from": f"{merger_id}:{action.get('id')}", "to": f"{merger_id}:{output.get('id')}", "kind": "fan_in_action"},
                {"from": f"{merger_id}:{output.get('id')}", "to": f"{merger_id}:{state.get('id')}", "kind": "fan_in_state"},
            ]
        )
        plans.append(_capability_plan([*branch_plan["_modules"], merger], "fan_in", connections, task_words))
        if len(plans) >= plan_budget:
            break
    return plans


def _fan_in_bindings(branches: list[dict[str, Any]], merger: dict[str, Any]) -> list[dict[str, Any]]:
    inputs = _dict_list(_mapping(merger.get("ports")).get("inputs"))
    actions = _dict_list(_mapping(merger.get("ports")).get("actions"))
    outputs = _dict_list(_mapping(merger.get("ports")).get("outputs"))
    states = _dict_list(_mapping(merger.get("ports")).get("state"))
    if (
        len(branches) != 2
        or len(inputs) != 2
        or any(_mapping(row.get("read")).get("kind") != "argument" for row in inputs)
        or len(actions) != 1
        or actions[0].get("event") != "call"
        or len(outputs) != 1
        or len(states) != 1
    ):
        return []
    candidates: list[tuple[int, list[dict[str, Any]]]] = []
    for ordered_inputs in permutations(enumerate(inputs)):
        bindings: list[dict[str, Any]] = []
        score = 0
        for branch_index, (branch, (input_index, input_port)) in enumerate(zip(branches, ordered_inputs), start=1):
            branch_outputs = _dict_list(_mapping(branch.get("ports")).get("outputs"))
            if len(branch_outputs) != 1 or branch_outputs[0].get("value_type") != input_port.get("value_type"):
                break
            branch_words = _behavior_words(
                [*_string_list(branch.get("capability_tags")), str(branch.get("capability_summary") or "")]
            )
            words = (branch_words & _behavior_words([str(input_port.get("semantic_key") or "")])) - {"result"}
            if not words:
                break
            score += len(words)
            bindings.append(
                {
                    "branch_index": branch_index,
                    "input_index": input_index,
                    "from_module_id": str(branch.get("module_capsule_id") or ""),
                    "from_output_port": str(branch_outputs[0].get("id") or ""),
                    "to_input_port": str(input_port.get("id") or ""),
                    "semantic_key": str(input_port.get("semantic_key") or ""),
                    "value_type": str(input_port.get("value_type") or ""),
                }
            )
        if len(bindings) == 2:
            candidates.append((score, bindings))
    if not candidates:
        return []
    candidates.sort(key=lambda row: row[0], reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return []
    return sorted(candidates[0][1], key=lambda row: row["input_index"])


def _pair_graph_edges(
    ui: dict[str, Any],
    logic: dict[str, Any],
    compatibility: dict[str, Any],
) -> list[dict[str, str]]:
    ui_id = str(ui.get("module_capsule_id") or "")
    logic_id = str(logic.get("module_capsule_id") or "")
    edges: list[dict[str, str]] = []
    for group, pairs in _mapping(compatibility.get("mapping")).items():
        for pair in _dict_list(pairs):
            if group in {"inputs", "actions"}:
                source, target = f"{ui_id}:{pair.get('ui_port')}", f"{logic_id}:{pair.get('logic_port')}"
            else:
                source, target = f"{logic_id}:{pair.get('logic_port')}", f"{ui_id}:{pair.get('ui_port')}"
            edges.append({"from": source, "to": target, "kind": f"behavior_{group}"})
    return edges


def _data_graph_edges(
    ui: dict[str, Any],
    data: dict[str, Any],
    logic: dict[str, Any],
    mapping: dict[str, Any],
) -> list[dict[str, str]]:
    ui_id = str(ui.get("module_capsule_id") or "")
    data_id = str(data.get("module_capsule_id") or "")
    logic_id = str(logic.get("module_capsule_id") or "")
    edges: list[dict[str, str]] = []
    for row in _dict_list(mapping.get("inputs")):
        if _mapping(row.get("read")).get("kind") == "data_records":
            edges.append({"from": f"{data_id}:records", "to": f"{logic_id}:{row.get('logic_port')}", "kind": "data_input"})
        else:
            edges.append({"from": f"{ui_id}:{row.get('ui_port')}", "to": f"{logic_id}:{row.get('logic_port')}", "kind": "behavior_input"})
    collection = _mapping(mapping.get("collection"))
    action = _mapping(mapping.get("action"))
    output = _mapping(mapping.get("output"))
    edges.extend(
        [
            {"from": f"{data_id}:records", "to": f"{ui_id}:{collection.get('ui_port')}", "kind": "data_collection"},
            {"from": f"{ui_id}:{action.get('ui_port')}", "to": f"{logic_id}:{action.get('logic_port')}", "kind": "behavior_actions"},
            {"from": f"{logic_id}:{output.get('logic_port')}", "to": f"{ui_id}:{output.get('ui_port')}", "kind": "behavior_outputs"},
        ]
    )
    for row in _dict_list(mapping.get("state")):
        edges.append(
            {
                "from": f"{logic_id}:{row.get('logic_port')}",
                "to": f"{ui_id}:{row.get('ui_port')}",
                "kind": "behavior_state",
            }
        )
    return edges


def _logic_chain_edges(source: dict[str, Any], target: dict[str, Any]) -> list[dict[str, str]]:
    source_outputs = _dict_list(_mapping(source.get("ports")).get("outputs"))
    target_ports = _mapping(target.get("ports"))
    target_inputs = _dict_list(target_ports.get("inputs"))
    if len(source_outputs) != 1 or len(target_inputs) != 1:
        return []
    output, input_port = source_outputs[0], target_inputs[0]
    if (
        output.get("semantic_key") != input_port.get("semantic_key")
        or output.get("value_type") != input_port.get("value_type")
        or _mapping(input_port.get("read")).get("kind") != "argument"
    ):
        return []
    actions = _dict_list(target_ports.get("actions"))
    outputs = _dict_list(target_ports.get("outputs"))
    if len(actions) != 1 or actions[0].get("event") != "call" or len(outputs) != 1:
        return []
    source_ref = f"{source.get('module_capsule_id')}:{output.get('id')}"
    target_id = str(target.get("module_capsule_id") or "")
    edges = [
        {"from": source_ref, "to": f"{target_id}:{input_port.get('id')}", "kind": "logic_chain_input"},
        {"from": source_ref, "to": f"{target_id}:{actions[0].get('id')}", "kind": "logic_chain_action"},
    ]
    states = _dict_list(target_ports.get("state"))
    if len(states) == 1:
        edges.append(
            {
                "from": f"{target_id}:{outputs[0].get('id')}",
                "to": f"{target_id}:{states[0].get('id')}",
                "kind": "logic_chain_state",
            }
        )
    return edges


def _graph_node(capsule: dict[str, Any]) -> dict[str, Any]:
    return {
        "module_id": str(capsule.get("module_capsule_id") or ""),
        "role": _port_role(capsule),
        "module_kind": str(capsule.get("module_kind") or ""),
        "tags": _string_list(capsule.get("capability_tags")),
        "capability_summary": str(capsule.get("capability_summary") or ""),
    }


def _behavior_task_words(goal: str) -> set[str]:
    return _behavior_words([str(goal or "")]) - {"build", "from", "into", "old", "project", "the", "this", "tool", "with"}


def _behavior_module_words(capsule: dict[str, Any]) -> set[str]:
    values = [
        *_string_list(capsule.get("capability_tags")),
        str(capsule.get("capability_summary") or ""),
        str(capsule.get("module_kind") or ""),
        str(capsule.get("library_key") or ""),
    ]
    return _behavior_words(values)


def _behavior_words(values: list[str]) -> set[str]:
    words = {word for value in values for word in re.findall(r"[a-z0-9]+", value.lower()) if len(word) > 2}
    # ponytail: suffix normalization is enough for local tags; replace only if real retrieval needs semantics.
    return words | {
        word[: -len(suffix)]
        for word in words
        for suffix in ("ing", "ed", "al", "s")
        if word.endswith(suffix) and len(word) - len(suffix) >= 5
    }


def _conflict_edges(capsules: list[dict[str, Any]]) -> list[dict[str, str]]:
    ids = {str(row.get("module_capsule_id") or "") for row in capsules}
    keys = {str(row.get("library_key") or "") for row in capsules}
    by_key = {str(row.get("library_key") or ""): str(row.get("module_capsule_id") or "") for row in capsules}
    edges: list[dict[str, str]] = []
    for capsule in capsules:
        source = str(capsule.get("module_capsule_id") or "")
        blocked = set(_string_list(_mapping(capsule.get("governance")).get("conflicts_with")))
        for target in sorted(blocked & (ids | keys)):
            edges.append({"from": source, "to": by_key.get(target, target), "matched_by": target})
    return edges


def _compose_behavior_modules(capsules: list[dict[str, Any]], *, topology: str = "serial") -> dict[str, Any] | None:
    ported = [row for row in capsules if isinstance(row.get("ports"), dict)]
    if not ported:
        return None
    if not 2 <= len(capsules) <= 5 or len(ported) != len(capsules):
        raise ValueError("behavior_composition_requires_two_to_five_ported_modules")
    ui_rows = [row for row in ported if _port_role(row) == "ui"]
    logic_rows = [row for row in ported if _port_role(row) == "logic"]
    data_rows = [row for row in ported if _port_role(row) == "data"]
    if len(ui_rows) != 1 or len(data_rows) > 1 or not 1 <= len(logic_rows) <= 4:
        raise ValueError("behavior_composition_requires_one_ui_optional_data_and_one_to_four_logic_roles")
    ui = ui_rows[0]
    if data_rows:
        compatible = []
        for row in logic_rows:
            try:
                mapping = _data_adapter_mapping(ui, data_rows[0], row)
            except ValueError:
                continue
            compatible.append((row, mapping))
        if len(compatible) != 1:
            raise ValueError("data_primary_logic_must_be_unique")
        logic, _mapping_result = compatible[0]
        followers = [row for row in logic_rows if row is not logic]
        return _compose_data_behavior_modules(ui, data_rows[0], logic, followers, topology=topology)
    compatible = [(row, compare_behavior_ports(ui, row)) for row in logic_rows]
    compatible = [(row, result) for row, result in compatible if result["status"] == "compatible"]
    if len(compatible) != 1:
        raise ValueError("behavior_primary_logic_must_be_unique")
    logic, compatibility = compatible[0]
    chain, branches, merger = _logic_followers(logic, [row for row in logic_rows if row is not logic], topology)

    ui_files = _declared_fragment_files(ui)
    if set(ui_files) != {"index.html", "styles.css"}:
        raise ValueError("ui_behavior_module_requires_index_and_styles_only")
    logic_script, logic_function, source_function = _isolated_logic_module(logic, "reweavePrimaryLogic")
    adapter_mapping = _adapter_mapping(ui, logic, compatibility)
    adapter_mapping["action"].update({"function": logic_function, "source_function": source_function})
    chain_scripts, chain_mappings = _logic_chain_contracts(logic, chain)
    branch_scripts, branch_mappings = _logic_branch_contracts(logic, branches)
    merge_script, merge_mapping = _logic_merge_contract(branches, merger)
    if chain_mappings:
        adapter_mapping["logic_chain"] = chain_mappings
    if branch_mappings:
        adapter_mapping["logic_branches"] = branch_mappings
    if merge_mapping:
        adapter_mapping["logic_merge"] = merge_mapping
    _validate_ui_adapter_targets(ui_files["index.html"], adapter_mapping)
    adapter = _render_behavior_adapter(adapter_mapping)
    index_html = _ensure_behavior_assets(ui_files["index.html"])
    index_html = _ensure_behavior_state_output(index_html, adapter_mapping)
    return {
        "files": {
            "index.html": index_html,
            "styles.css": ui_files["styles.css"],
            "app.js": "\n\n".join(
                row.rstrip() for row in (logic_script, *chain_scripts, *branch_scripts, merge_script, adapter) if row
            ),
        },
        "ui_capsule_id": str(ui.get("module_capsule_id") or ""),
        "logic_capsule_id": str(logic.get("module_capsule_id") or ""),
        "logic_chain_capsule_ids": [str(row.get("module_capsule_id") or "") for row in chain],
        "logic_branch_capsule_ids": [str(row.get("module_capsule_id") or "") for row in branches],
        "logic_merge_capsule_id": str(merger.get("module_capsule_id") or "") if merger else "",
        "adapter_mapping": adapter_mapping,
        "compatibility": compatibility,
    }


def _compose_data_behavior_modules(
    ui: dict[str, Any],
    data: dict[str, Any],
    logic: dict[str, Any],
    followers: list[dict[str, Any]],
    *,
    topology: str,
) -> dict[str, Any]:
    ui_files = _declared_fragment_files(ui)
    if set(ui_files) != {"index.html", "styles.css"}:
        raise ValueError("ui_behavior_module_requires_index_and_styles_only")
    logic_script, logic_function, source_function = _isolated_logic_module(logic, "reweavePrimaryLogic")
    adapter_mapping = _data_adapter_mapping(ui, data, logic)
    adapter_mapping["action"].update({"function": logic_function, "source_function": source_function})
    chain, branches, merger = _logic_followers(logic, followers, topology)
    chain_scripts, chain_mappings = _logic_chain_contracts(logic, chain)
    branch_scripts, branch_mappings = _logic_branch_contracts(logic, branches)
    merge_script, merge_mapping = _logic_merge_contract(branches, merger)
    if chain_mappings:
        adapter_mapping["logic_chain"] = chain_mappings
    if branch_mappings:
        adapter_mapping["logic_branches"] = branch_mappings
    if merge_mapping:
        adapter_mapping["logic_merge"] = merge_mapping
    _validate_ui_adapter_targets(ui_files["index.html"], adapter_mapping)
    records = _mapping(_mapping(data.get("payload")).get("data_records")).get("records")
    if not isinstance(records, list):
        raise ValueError("data_module_records_missing")
    index_html = _ensure_behavior_assets(ui_files["index.html"])
    index_html = _ensure_behavior_state_output(index_html, adapter_mapping)
    return {
        "files": {
            "index.html": index_html,
            "styles.css": ui_files["styles.css"],
            "app.js": "\n\n".join(
                row.rstrip()
                for row in (
                    logic_script,
                    *chain_scripts,
                    *branch_scripts,
                    merge_script,
                    _render_data_behavior_adapter(adapter_mapping, records),
                )
                if row
            ),
        },
        "ui_capsule_id": str(ui.get("module_capsule_id") or ""),
        "logic_capsule_id": str(logic.get("module_capsule_id") or ""),
        "data_capsule_id": str(data.get("module_capsule_id") or ""),
        "logic_chain_capsule_ids": [str(row.get("module_capsule_id") or "") for row in chain],
        "logic_branch_capsule_ids": [str(row.get("module_capsule_id") or "") for row in branches],
        "logic_merge_capsule_id": str(merger.get("module_capsule_id") or "") if merger else "",
        "adapter_mapping": adapter_mapping,
        "compatibility": {"status": "compatible", "mapping": adapter_mapping, "blockers": []},
    }


def _port_role(capsule: dict[str, Any]) -> str:
    if capsule.get("module_kind") == "behavior_data" and isinstance(_mapping(capsule.get("payload")).get("data_records"), dict):
        return "data"
    ports = _mapping(capsule.get("ports"))
    inputs = _dict_list(ports.get("inputs"))
    outputs = _dict_list(ports.get("outputs"))
    actions = _dict_list(ports.get("actions"))
    if inputs and outputs and actions and all(_mapping(row.get("read")).get("kind") == "dom_value" for row in inputs) and all(
        _mapping(row.get("write")).get("kind") == "dom_property" for row in outputs
    ) and all(str(row.get("event") or "") != "call" for row in actions):
        return "ui"
    if inputs and outputs and actions and all(_mapping(row.get("read")).get("kind") == "argument" for row in inputs) and all(
        _mapping(row.get("write")).get("kind") == "return" for row in outputs
    ) and all(str(row.get("event") or "") == "call" for row in actions):
        return "logic"
    return "unknown"


def _data_adapter_mapping(ui: dict[str, Any], data: dict[str, Any], logic: dict[str, Any]) -> dict[str, Any]:
    ui_ports = _mapping(ui.get("ports"))
    data_ports = _mapping(data.get("ports"))
    logic_ports = _mapping(logic.get("ports"))
    ui_inputs = {str(row.get("semantic_key") or ""): row for row in _dict_list(ui_ports.get("inputs"))}
    data_outputs = _dict_list(data_ports.get("outputs"))
    logic_inputs = _dict_list(logic_ports.get("inputs"))
    ui_actions = _dict_list(ui_ports.get("actions"))
    logic_actions = _dict_list(logic_ports.get("actions"))
    ui_outputs = _dict_list(ui_ports.get("outputs"))
    logic_outputs = _dict_list(logic_ports.get("outputs"))
    collections = _dict_list(ui_ports.get("collections"))
    if not all(len(rows) == 1 for rows in (data_outputs, ui_actions, logic_actions, ui_outputs, logic_outputs, collections)):
        raise ValueError("data_behavior_requires_single_data_action_output_and_collection")
    data_output = data_outputs[0]
    data_input = next(
        (
            row
            for row in logic_inputs
            if row.get("semantic_key") == data_output.get("semantic_key")
            and row.get("value_type") == data_output.get("value_type") == "record_list"
        ),
        None,
    )
    if data_input is None:
        raise ValueError("data_output_not_consumed_by_logic")
    record_payload = _mapping(_mapping(data.get("payload")).get("data_records"))
    fields = [str(row.get("name") or "") for row in _dict_list(record_payload.get("fields"))]
    required_fields = [str(row) for row in data_input.get("required_fields", []) if str(row)]
    collection = collections[0]
    collection_write = _mapping(collection.get("write"))
    collection_fields = [str(row) for row in collection_write.get("fields", []) if str(row)]
    if not set(required_fields) <= set(fields) or not set(collection_fields) <= set(fields):
        raise ValueError("data_record_fields_incompatible")
    mapped_inputs: list[dict[str, Any]] = []
    used_ui_keys: set[str] = set()
    for logic_input in logic_inputs:
        semantic_key = str(logic_input.get("semantic_key") or "")
        if logic_input is data_input:
            mapped_inputs.append(
                {
                    "ui_port": "",
                    "logic_port": str(logic_input.get("id") or ""),
                    "semantic_key": semantic_key,
                    "value_type": "record_list",
                    "read": {"kind": "data_records"},
                    "argument": str(logic_input.get("id") or ""),
                }
            )
            continue
        ui_input = ui_inputs.get(semantic_key)
        if ui_input is None or ui_input.get("value_type") != logic_input.get("value_type"):
            raise ValueError("ui_input_not_compatible_with_data_logic")
        used_ui_keys.add(semantic_key)
        mapped_inputs.append(
            {
                "ui_port": str(ui_input.get("id") or ""),
                "logic_port": str(logic_input.get("id") or ""),
                "semantic_key": semantic_key,
                "value_type": str(logic_input.get("value_type") or ""),
                "read": _mapping(ui_input.get("read")),
                "argument": str(logic_input.get("id") or ""),
            }
        )
    if used_ui_keys != set(ui_inputs):
        raise ValueError("unused_ui_input_in_data_composition")
    ui_output, logic_output = ui_outputs[0], logic_outputs[0]
    if ui_output.get("semantic_key") != logic_output.get("semantic_key") or ui_output.get("value_type") != logic_output.get("value_type"):
        raise ValueError("data_logic_output_not_compatible_with_ui")
    ui_action, logic_action = ui_actions[0], logic_actions[0]
    if ui_action.get("event") == "call" or logic_action.get("event") != "call":
        raise ValueError("data_behavior_action_interface_invalid")
    ui_state = _dict_list(ui_ports.get("state"))
    logic_state = _dict_list(logic_ports.get("state"))
    if len(ui_state) != 1 or len(logic_state) != 1 or ui_state[0].get("expected_change") != logic_state[0].get("expected_change"):
        raise ValueError("data_behavior_state_incompatible")
    return {
        "schema_version": "module_native_adapter_mapping.v1",
        "status": "compatible",
        "ui_capsule_id": str(ui.get("module_capsule_id") or ""),
        "data_capsule_id": str(data.get("module_capsule_id") or ""),
        "logic_capsule_id": str(logic.get("module_capsule_id") or ""),
        "inputs": mapped_inputs,
        "data": {
            "output_port": str(data_output.get("id") or ""),
            "logic_port": str(data_input.get("id") or ""),
            "fields": fields,
            "record_count": len(record_payload.get("records") or []),
        },
        "collection": {
            "ui_port": str(collection.get("id") or ""),
            "write": collection_write,
        },
        "action": {
            "ui_port": str(ui_action.get("id") or ""),
            "event": str(ui_action.get("event") or ""),
            "target": str(ui_action.get("target") or ""),
            "logic_port": str(logic_action.get("id") or ""),
            "function": str(logic_action.get("target") or ""),
        },
        "output": {
            "logic_port": str(logic_output.get("id") or ""),
            "ui_port": str(ui_output.get("id") or ""),
            "value_type": str(ui_output.get("value_type") or ""),
            "write": _mapping(ui_output.get("write")),
        },
        "state": [{"ui_port": str(ui_state[0].get("id") or ""), "logic_port": str(logic_state[0].get("id") or "")}],
        "source_project_write": False,
    }


def _declared_fragment_files(capsule: dict[str, Any]) -> dict[str, str]:
    payload = _mapping(capsule.get("payload"))
    fragment = _mapping(payload.get("fragment_bundle"))
    slots = {str(key): str(value) for key, value in _mapping(payload.get("slot_patch")).items()}
    return {
        str(row.get("path") or ""): _apply_slots(str(row.get("content") or ""), slots)
        for row in _dict_list(fragment.get("files_partial"))
    }


def _logic_module_contract(capsule: dict[str, Any]) -> tuple[str, str]:
    files = _declared_fragment_files(capsule)
    if set(files) != {"app.js"}:
        raise ValueError("logic_behavior_module_requires_pure_app_js_only")
    script = files["app.js"]
    if re.search(r"\b(?:document|window|localStorage|sessionStorage|fetch|XMLHttpRequest|WebSocket|eval|require)\b", script):
        raise ValueError("logic_behavior_module_must_not_access_dom")
    ports = _mapping(capsule.get("ports"))
    action = _dict_list(ports.get("actions"))[0]
    function_name = str(action.get("target") or "")
    function_match = re.search(rf"\bfunction\s+{re.escape(function_name)}\s*\(([^)]*)\)\s*{{", script)
    if not function_match:
        raise ValueError("logic_behavior_function_not_found")
    parameters = [row.strip() for row in function_match.group(1).split(",") if row.strip()]
    if len(parameters) != len(_dict_list(ports.get("inputs"))) or "return" not in script:
        raise ValueError("logic_behavior_function_contract_mismatch")
    return script, function_name


def _isolated_logic_module(capsule: dict[str, Any], alias: str) -> tuple[str, str, str]:
    script, function_name = _logic_module_contract(capsule)
    indented = "\n".join(f"  {line}" for line in script.rstrip().splitlines())
    return f"const {alias} = (() => {{\n{indented}\n  return {function_name};\n}})();", alias, function_name


def _state_logic_mapping(primary: dict[str, Any], state_logic: dict[str, Any], function_name: str) -> dict[str, Any]:
    mapping = _chain_logic_mapping(primary, state_logic, function_name, 1)
    if mapping["expected_change"] == "updated":
        raise ValueError("state_logic_requires_observable_state_change")
    return mapping


def _ordered_logic_chain(primary: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous = primary
    ordered: list[dict[str, Any]] = []
    for candidate in candidates:
        if not _logic_chain_edges(previous, candidate):
            raise ValueError("logic_chain_order_incompatible")
        ordered.append(candidate)
        previous = candidate
    return ordered


def _logic_followers(
    primary: dict[str, Any],
    candidates: list[dict[str, Any]],
    topology: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    if topology == "serial":
        return _ordered_logic_chain(primary, candidates), [], None
    if topology == "fan_out" and len(candidates) == 2 and all(_logic_chain_edges(primary, row) for row in candidates):
        return [], candidates, None
    if (
        topology == "fan_in"
        and len(candidates) == 3
        and all(_logic_chain_edges(primary, row) for row in candidates[:2])
        and _fan_in_bindings(candidates[:2], candidates[2])
    ):
        return [], candidates[:2], candidates[2]
    raise ValueError("logic_topology_incompatible")


def _logic_chain_contracts(
    primary: dict[str, Any],
    chain: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    scripts: list[str] = []
    mappings: list[dict[str, Any]] = []
    previous = primary
    for index, capsule in enumerate(chain, start=1):
        script, function_name, source_function = _isolated_logic_module(capsule, f"reweaveChainLogic{index}")
        scripts.append(script)
        mapping = _chain_logic_mapping(previous, capsule, function_name, index)
        mapping["source_function"] = source_function
        mappings.append(mapping)
        previous = capsule
    return scripts, mappings


def _logic_branch_contracts(
    primary: dict[str, Any],
    branches: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    scripts: list[str] = []
    mappings: list[dict[str, Any]] = []
    for index, capsule in enumerate(branches, start=1):
        script, function_name, source_function = _isolated_logic_module(capsule, f"reweaveBranchLogic{index}")
        scripts.append(script)
        mapping = _chain_logic_mapping(primary, capsule, function_name, index)
        mapping["source_function"] = source_function
        mappings.append(mapping)
    return scripts, mappings


def _logic_merge_contract(
    branches: list[dict[str, Any]],
    merger: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    if merger is None:
        return "", {}
    bindings = _fan_in_bindings(branches, merger)
    if not bindings:
        raise ValueError("fan_in_merge_contract_incompatible")
    script, function_name, source_function = _isolated_logic_module(merger, "reweaveMergeLogic")
    ports = _mapping(merger.get("ports"))
    output = _dict_list(ports.get("outputs"))[0]
    state = _dict_list(ports.get("state"))[0]
    return script, {
        "logic_capsule_id": str(merger.get("module_capsule_id") or ""),
        "function": function_name,
        "source_function": source_function,
        "inputs": bindings,
        "output": {
            "logic_port": str(output.get("id") or ""),
            "value_type": str(output.get("value_type") or ""),
            "write": {
                "kind": "dom_property",
                "selector": "#reweave-merge-result",
                "property": "textContent",
            },
        },
        "expected_change": str(state.get("expected_change") or ""),
    }


def _chain_logic_mapping(
    primary: dict[str, Any],
    state_logic: dict[str, Any],
    function_name: str,
    index: int,
) -> dict[str, Any]:
    primary_outputs = _dict_list(_mapping(primary.get("ports")).get("outputs"))
    state_ports = _mapping(state_logic.get("ports"))
    state_inputs = _dict_list(state_ports.get("inputs"))
    state_outputs = _dict_list(state_ports.get("outputs"))
    state_rows = _dict_list(state_ports.get("state"))
    if len(primary_outputs) != 1 or len(state_inputs) != 1 or len(state_outputs) != 1 or len(state_rows) != 1:
        raise ValueError("state_logic_requires_single_input_output_and_state")
    source, target = primary_outputs[0], state_inputs[0]
    if source.get("semantic_key") != target.get("semantic_key") or source.get("value_type") != target.get("value_type"):
        raise ValueError("state_logic_input_incompatible_with_primary_output")
    output = state_outputs[0]
    selector = "#reweave-state-result" if index == 1 else f"#reweave-state-result-{index}"
    return {
        "logic_capsule_id": str(state_logic.get("module_capsule_id") or ""),
        "function": function_name,
        "input": {
            "from_logic_port": str(source.get("id") or ""),
            "logic_port": str(target.get("id") or ""),
            "semantic_key": str(target.get("semantic_key") or ""),
            "value_type": str(target.get("value_type") or ""),
        },
        "output": {
            "logic_port": str(output.get("id") or ""),
            "value_type": str(output.get("value_type") or ""),
            "write": {"kind": "dom_property", "selector": selector, "property": "textContent"},
        },
        "expected_change": str(state_rows[0].get("expected_change") or ""),
    }


def _adapter_mapping(ui: dict[str, Any], logic: dict[str, Any], compatibility: dict[str, Any]) -> dict[str, Any]:
    ui_ports = _mapping(ui.get("ports"))
    logic_ports = _mapping(logic.get("ports"))
    ui_inputs = {str(row.get("id") or ""): row for row in _dict_list(ui_ports.get("inputs"))}
    logic_inputs = {str(row.get("id") or ""): row for row in _dict_list(logic_ports.get("inputs"))}
    inputs = []
    for pair in compatibility["mapping"]["inputs"]:
        ui_port = ui_inputs[str(pair.get("ui_port") or "")]
        logic_port = logic_inputs[str(pair.get("logic_port") or "")]
        inputs.append({**pair, "read": _mapping(ui_port.get("read")), "argument": str(logic_port.get("id") or "")})
    ui_action = _dict_list(ui_ports.get("actions"))[0]
    logic_action = _dict_list(logic_ports.get("actions"))[0]
    ui_output = _dict_list(ui_ports.get("outputs"))[0]
    logic_output = _dict_list(logic_ports.get("outputs"))[0]
    return {
        "schema_version": "module_native_adapter_mapping.v1",
        "status": "compatible",
        "ui_capsule_id": str(ui.get("module_capsule_id") or ""),
        "logic_capsule_id": str(logic.get("module_capsule_id") or ""),
        "inputs": inputs,
        "action": {
            "ui_port": str(ui_action.get("id") or ""),
            "event": str(ui_action.get("event") or ""),
            "target": str(ui_action.get("target") or ""),
            "logic_port": str(logic_action.get("id") or ""),
            "function": str(logic_action.get("target") or ""),
        },
        "output": {
            "logic_port": str(logic_output.get("id") or ""),
            "ui_port": str(ui_output.get("id") or ""),
            "value_type": str(ui_output.get("value_type") or ""),
            "write": _mapping(ui_output.get("write")),
        },
        "state": compatibility["mapping"]["state"],
        "source_project_write": False,
    }


def _render_behavior_adapter(mapping: dict[str, Any]) -> str:
    reads = []
    arguments = []
    for index, row in enumerate(_dict_list(mapping.get("inputs"))):
        variable = f"input{index}"
        selector = json.dumps(str(_mapping(row.get("read")).get("selector") or ""))
        access = f"document.querySelector({selector}).value"
        reads.append(f"  const {variable} = Number({access});" if row.get("value_type") == "number" else f"  const {variable} = {access};")
        arguments.append(variable)
    action = _mapping(mapping.get("action"))
    output = _mapping(mapping.get("output"))
    write = _mapping(output.get("write"))
    result_value = "Boolean(result)" if output.get("value_type") == "boolean" else "String(result)"
    chain_lines = _render_logic_chain(mapping, indent="  ")
    return (
        "document.addEventListener('DOMContentLoaded', () => {\n"
        f"  document.querySelector({json.dumps(str(action.get('target') or ''))}).addEventListener({json.dumps(str(action.get('event') or ''))}, () => {{\n"
        + "\n".join(reads)
        + f"\n  const result = {action.get('function')}({', '.join(arguments)});\n"
        f"  document.querySelector({json.dumps(str(write.get('selector') or ''))}).{write.get('property')} = {result_value};"
        + ("\n" + chain_lines if chain_lines else "")
        + "\n"
        "  });\n"
        "});\n"
    )


def _render_data_behavior_adapter(mapping: dict[str, Any], records: list[Any]) -> str:
    reads: list[str] = []
    arguments: list[str] = []
    for index, row in enumerate(_dict_list(mapping.get("inputs"))):
        read = _mapping(row.get("read"))
        if read.get("kind") == "data_records":
            arguments.append("reweaveRecords")
            continue
        variable = f"input{index}"
        selector = json.dumps(str(read.get("selector") or ""))
        access = f"document.querySelector({selector}).value"
        reads.append(f"    const {variable} = Number({access});" if row.get("value_type") == "number" else f"    const {variable} = {access};")
        arguments.append(variable)
    action = _mapping(mapping.get("action"))
    output = _mapping(mapping.get("output"))
    output_write = _mapping(output.get("write"))
    result_value = "Boolean(result)" if output.get("value_type") == "boolean" else "String(result)"
    collection = _mapping(mapping.get("collection"))
    collection_write = _mapping(collection.get("write"))
    selector = json.dumps(str(collection_write.get("selector") or ""))
    fields = json.dumps(collection_write.get("fields") or [], ensure_ascii=False)
    chain_lines = _render_logic_chain(mapping, indent="    ")
    return (
        f"const reweaveRecords = {json.dumps(records, ensure_ascii=False)};\n\n"
        "document.addEventListener('DOMContentLoaded', () => {\n"
        f"  const collection = document.querySelector({selector});\n"
        "  collection.replaceChildren();\n"
        f"  const fields = {fields};\n"
        "  for (const record of reweaveRecords) {\n"
        "    const row = document.createElement('tr');\n"
        "    for (const field of fields) {\n"
        "      const cell = document.createElement('td');\n"
        "      cell.textContent = String(record[field] ?? '');\n"
        "      row.appendChild(cell);\n"
        "    }\n"
        "    collection.appendChild(row);\n"
        "  }\n"
        f"  document.querySelector({json.dumps(str(action.get('target') or ''))}).addEventListener({json.dumps(str(action.get('event') or ''))}, () => {{\n"
        + "\n".join(reads)
        + f"\n    const result = {action.get('function')}({', '.join(arguments)});\n"
        f"    document.querySelector({json.dumps(str(output_write.get('selector') or ''))}).{output_write.get('property')} = {result_value};\n"
        + (chain_lines + "\n" if chain_lines else "")
        + "  });\n"
        + "});\n"
    )


def _render_logic_chain(mapping: dict[str, Any], *, indent: str) -> str:
    lines: list[str] = []
    previous = "result"
    for index, row in enumerate(_dict_list(mapping.get("logic_chain")), start=1):
        variable = f"chainResult{index}"
        output = _mapping(row.get("output"))
        write = _mapping(output.get("write"))
        value = f"Boolean({variable})" if output.get("value_type") == "boolean" else f"String({variable})"
        lines.extend(
            [
                f"{indent}const {variable} = {row.get('function')}({previous});",
                f"{indent}document.querySelector({json.dumps(str(write.get('selector') or ''))}).{write.get('property')} = {value};",
            ]
        )
        previous = variable
    for index, row in enumerate(_dict_list(mapping.get("logic_branches")), start=1):
        variable = f"branchResult{index}"
        output = _mapping(row.get("output"))
        write = _mapping(output.get("write"))
        value = f"Boolean({variable})" if output.get("value_type") == "boolean" else f"String({variable})"
        lines.extend(
            [
                f"{indent}const {variable} = {row.get('function')}(result);",
                f"{indent}document.querySelector({json.dumps(str(write.get('selector') or ''))}).{write.get('property')} = {value};",
            ]
        )
    merge = _mapping(mapping.get("logic_merge"))
    if merge:
        arguments = [f"branchResult{int(row.get('branch_index') or 0)}" for row in _dict_list(merge.get("inputs"))]
        output = _mapping(merge.get("output"))
        write = _mapping(output.get("write"))
        value = "Boolean(fanInResult)" if output.get("value_type") == "boolean" else "String(fanInResult)"
        lines.extend(
            [
                f"{indent}const fanInResult = {merge.get('function')}({', '.join(arguments)});",
                f"{indent}document.querySelector({json.dumps(str(write.get('selector') or ''))}).{write.get('property')} = {value};",
            ]
        )
    return "\n".join(lines)


def _ensure_behavior_assets(index_html: str) -> str:
    source = with_local_runtime_csp(index_html)
    if "styles.css" not in source:
        source = source.replace("</head>", '<link rel="stylesheet" href="styles.css"></head>', 1)
    if "app.js" not in source:
        source = source.replace("</body>", '<script src="app.js"></script></body>', 1)
    return source


def _ensure_behavior_state_output(index_html: str, mapping: dict[str, Any]) -> str:
    followers = _dict_list(mapping.get("logic_chain")) or _dict_list(mapping.get("logic_branches"))
    merge = _mapping(mapping.get("logic_merge"))
    if merge:
        followers = [*followers, merge]
    if not followers:
        return index_html
    outputs: list[str] = []
    for index, row in enumerate(followers, start=1):
        selector = str(_mapping(_mapping(row.get("output")).get("write")).get("selector") or "")
        output_id = selector.removeprefix("#")
        if not output_id or f'id="{output_id}"' in index_html:
            raise ValueError("generated_state_output_conflicts_with_ui")
        outputs.append(
            f'<p data-reweave-composed-state="{index}">Step {index}: '
            f'<output id="{output_id}" aria-live="polite">0</output></p>'
        )
    output = "".join(outputs)
    if "</main>" in index_html:
        return index_html.replace("</main>", output + "</main>", 1)
    if "</body>" in index_html:
        return index_html.replace("</body>", output + "</body>", 1)
    raise ValueError("ui_behavior_state_output_target_missing")


class _PortHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.by_id: dict[str, list[dict[str, str]]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: str(value or "") for key, value in attrs}
        if values.get("id"):
            self.by_id.setdefault(values["id"], []).append({"tag": tag, **values})


def _validate_ui_adapter_targets(index_html: str, mapping: dict[str, Any]) -> None:
    parser = _PortHTMLParser()
    parser.feed(index_html)

    def target(selector: str) -> dict[str, str]:
        if not selector.startswith("#") or len(parser.by_id.get(selector[1:], [])) != 1:
            raise ValueError(f"ui_behavior_target_missing_or_ambiguous:{selector}")
        return parser.by_id[selector[1:]][0]

    for row in _dict_list(mapping.get("inputs")):
        read = _mapping(row.get("read"))
        if read.get("kind") == "data_records":
            continue
        element = target(str(read.get("selector") or ""))
        if element["tag"] not in {"input", "select", "textarea"}:
            raise ValueError("ui_behavior_input_target_invalid")
        if row.get("value_type") == "number" and element["tag"] == "input" and element.get("type") != "number":
            raise ValueError("ui_behavior_input_type_mismatch")
    action = _mapping(mapping.get("action"))
    if target(str(action.get("target") or ""))["tag"] not in {"button", "input", "form"}:
        raise ValueError("ui_behavior_action_target_invalid")
    output = _mapping(mapping.get("output"))
    write = _mapping(output.get("write"))
    element = target(str(write.get("selector") or ""))
    if write.get("property") in {"value", "checked"} and element["tag"] not in {"input", "select", "textarea"}:
        raise ValueError("ui_behavior_output_target_invalid")
    collection = _mapping(mapping.get("collection"))
    if collection:
        collection_element = target(str(_mapping(collection.get("write")).get("selector") or ""))
        if collection_element["tag"] != "tbody":
            raise ValueError("ui_behavior_collection_target_invalid")


def _selection_audit(
    *,
    candidates: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    max_modules: int,
    trimmed: list[dict[str, Any]] | None = None,
    conflict_edges: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    trimmed_rows = trimmed or []
    return {
        "selection_audit_version": "module_native_selection_audit.v1",
        "eligible_module_ids": [str(row.get("module_capsule_id") or "") for row in candidates],
        "selected_module_ids": [str(row.get("module_capsule_id") or "") for row in selected],
        "trimmed_module_ids": [str(row.get("module_capsule_id") or "") for row in trimmed_rows],
        "module_budget": {
            "max_modules": int(max_modules),
            "eligible_count": len(candidates),
            "selected_count": len(selected),
            "trimmed_count": len(trimmed_rows),
            "trimmed_module_ids": [str(row.get("module_capsule_id") or "") for row in trimmed_rows],
        },
        "conflict_graph": _conflict_graph(conflict_edges or []),
    }


def _conflict_graph(edges: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "graph_version": "module_native_conflict_graph.v1",
        "status": "blocked" if edges else "clear",
        "edge_count": len(edges),
        "edges": edges,
        "hard_reject": bool(edges),
    }


def _module_source(capsule: dict[str, Any]) -> str:
    return str(_mapping(capsule.get("provenance")).get("source_preview_id") or "")


def _plan(
    *,
    intent: dict[str, Any],
    selected_modules: list[dict[str, Any]],
    rejected: list[dict[str, str]],
    selection_audit: dict[str, Any],
    behavior_composition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_ids = [row["module_capsule_id"] for row in selected_modules]
    digest = hashlib.sha1((intent["goal"] + ",".join(selected_ids)).encode("utf-8")).hexdigest()[:10]
    plan = {
        "plan_version": COMPOSITION_PLAN_VERSION,
        "plan_id": f"plan-{digest}",
        "intent": intent,
        "conflict_graph": selection_audit.get("conflict_graph") or _conflict_graph([]),
        "selection_receipt": {
            "selected": selected_ids[0] if len(selected_ids) == 1 else selected_ids,
            "rejected": rejected,
            "module_budget": selection_audit.get("module_budget") or {},
            "auto_behavior": selection_audit.get("auto_behavior") or {},
            "capability_graph": selection_audit.get("capability_graph") or {},
            "selected_capability_plan": selection_audit.get("selected_capability_plan") or {},
        },
    }
    if behavior_composition:
        ui_id = str(behavior_composition["ui_capsule_id"])
        logic_id = str(behavior_composition["logic_capsule_id"])
        data_id = str(behavior_composition.get("data_capsule_id") or "")
        chain_ids = [str(row) for row in behavior_composition.get("logic_chain_capsule_ids", []) if row]
        branch_ids = [str(row) for row in behavior_composition.get("logic_branch_capsule_ids", []) if row]
        merge_id = str(behavior_composition.get("logic_merge_capsule_id") or "")
        by_id = {str(row["module_capsule_id"]): row for row in selected_modules}
        wires = [
            {
                "from": f"{ui_id}:{behavior_composition['adapter_mapping']['action']['ui_port']}",
                "to": f"{logic_id}:{behavior_composition['adapter_mapping']['action']['logic_port']}",
                "strategy": "generated_adapter",
            },
            {
                "from": f"{logic_id}:{behavior_composition['adapter_mapping']['output']['logic_port']}",
                "to": f"{ui_id}:{behavior_composition['adapter_mapping']['output']['ui_port']}",
                "strategy": "generated_adapter",
            },
        ]
        modules = [
            {
                "module_capsule_id": ui_id,
                "role": "ui",
                "merge_strategy": "behavior_adapter",
                "provenance_source": _module_source(by_id[ui_id]),
                "priority": 1,
            },
            {
                "module_capsule_id": logic_id,
                "role": "logic",
                "merge_strategy": "behavior_adapter",
                "provenance_source": _module_source(by_id[logic_id]),
                "priority": 2,
            },
        ]
        provenance_map = {
            "index.html": ui_id,
            "styles.css": ui_id,
            "app.js:function": logic_id,
            "app.js:adapter": COMPOSER_VERSION,
            "adapter_mapping.json": COMPOSER_VERSION,
            "composition_plan.json": COMPOSER_VERSION,
        }
        region_provenance = {
            "ui": {"module_capsule_id": ui_id, "provenance_source": _module_source(by_id[ui_id])},
            "logic": {"module_capsule_id": logic_id, "provenance_source": _module_source(by_id[logic_id])},
        }
        index_provenance = [
            {"contributor_type": "module_capsule", "module_capsule_id": ui_id, "contribution": "ui_markup"},
            {"contributor_type": "composer", "composer_id": COMPOSER_VERSION, "contribution": "asset_wiring"},
        ]
        app_provenance = [
            {"contributor_type": "module_capsule", "module_capsule_id": logic_id, "contribution": "pure_logic"},
            {"contributor_type": "composer", "composer_id": COMPOSER_VERSION, "contribution": "behavior_adapter"},
        ]
        if data_id:
            data_mapping = _mapping(behavior_composition["adapter_mapping"].get("data"))
            collection_mapping = _mapping(behavior_composition["adapter_mapping"].get("collection"))
            collection_write = _mapping(collection_mapping.get("write"))
            wires[0:0] = [
                {
                    "from": f"{data_id}:{data_mapping.get('output_port')}",
                    "to": f"{logic_id}:{data_mapping.get('logic_port')}",
                    "strategy": "generated_adapter",
                },
                {
                    "from": f"{data_id}:{data_mapping.get('output_port')}",
                    "to": f"{ui_id}:{collection_mapping.get('ui_port')}",
                    "strategy": "generated_table_adapter",
                },
            ]
            modules.insert(
                1,
                {
                    "module_capsule_id": data_id,
                    "role": "data",
                    "merge_strategy": "behavior_adapter",
                    "provenance_source": _module_source(by_id[data_id]),
                    "priority": 2,
                },
            )
            modules[-1]["priority"] = 3
            provenance_map["app.js:data_records"] = data_id
            region_provenance["data"] = {
                "module_capsule_id": data_id,
                "provenance_source": _module_source(by_id[data_id]),
                "record_count": data_mapping.get("record_count"),
                "fields": data_mapping.get("fields"),
                "table_target": collection_write.get("selector"),
            }
            app_provenance.insert(
                0,
                {"contributor_type": "module_capsule", "module_capsule_id": data_id, "contribution": "data_records"},
            )
        follower_ids = branch_ids or chain_ids
        if follower_ids:
            mapping_key = "logic_branches" if branch_ids else "logic_chain"
            contribution = "logic_branch" if branch_ids else "logic_chain"
            follower_regions: list[dict[str, Any]] = []
            previous_id = logic_id
            for index, (follower_id, follower_mapping) in enumerate(
                zip(follower_ids, _dict_list(behavior_composition["adapter_mapping"].get(mapping_key))),
                start=1,
            ):
                follower_input = _mapping(follower_mapping.get("input"))
                follower_output = _mapping(follower_mapping.get("output"))
                follower_write = _mapping(follower_output.get("write"))
                source_id = logic_id if branch_ids else previous_id
                wires.extend(
                    [
                        {
                            "from": f"{source_id}:{follower_input.get('from_logic_port')}",
                            "to": f"{follower_id}:{follower_input.get('logic_port')}",
                            "strategy": "generated_adapter",
                        },
                        {
                            "from": f"{follower_id}:{follower_output.get('logic_port')}",
                            "to": f"{COMPOSER_VERSION}:{follower_write.get('selector')}",
                            "strategy": "generated_adapter",
                        },
                    ]
                )
                modules.append(
                    {
                        "module_capsule_id": follower_id,
                        "role": contribution,
                        "merge_strategy": "behavior_adapter",
                        "provenance_source": _module_source(by_id[follower_id]),
                        "priority": len(modules) + 1,
                    }
                )
                provenance_map[f"app.js:{contribution}:{index}"] = follower_id
                follower_regions.append(
                    {
                        "module_capsule_id": follower_id,
                        "provenance_source": _module_source(by_id[follower_id]),
                        "output_selector": follower_write.get("selector"),
                    }
                )
                app_provenance.insert(
                    len(app_provenance) - 1,
                    {
                        "contributor_type": "module_capsule",
                        "module_capsule_id": follower_id,
                        "contribution": contribution,
                    },
                )
                if not branch_ids:
                    previous_id = follower_id
            provenance_map[f"index.html:generated_{contribution}_outputs"] = COMPOSER_VERSION
            region_provenance[contribution] = follower_regions
            index_provenance.append(
                {
                    "contributor_type": "composer",
                    "composer_id": COMPOSER_VERSION,
                    "contribution": f"generated_{contribution}_outputs",
                }
            )
        if merge_id:
            merge_mapping = _mapping(behavior_composition["adapter_mapping"].get("logic_merge"))
            merge_output = _mapping(merge_mapping.get("output"))
            merge_write = _mapping(merge_output.get("write"))
            for binding in _dict_list(merge_mapping.get("inputs")):
                wires.append(
                    {
                        "from": f"{binding.get('from_module_id')}:{binding.get('from_output_port')}",
                        "to": f"{merge_id}:{binding.get('to_input_port')}",
                        "strategy": "generated_adapter",
                    }
                )
            wires.append(
                {
                    "from": f"{merge_id}:{merge_output.get('logic_port')}",
                    "to": f"{COMPOSER_VERSION}:{merge_write.get('selector')}",
                    "strategy": "generated_adapter",
                }
            )
            modules.append(
                {
                    "module_capsule_id": merge_id,
                    "role": "logic_merge",
                    "merge_strategy": "behavior_adapter",
                    "provenance_source": _module_source(by_id[merge_id]),
                    "priority": len(modules) + 1,
                }
            )
            provenance_map["app.js:logic_merge"] = merge_id
            provenance_map["index.html:generated_logic_merge_output"] = COMPOSER_VERSION
            region_provenance["logic_merge"] = {
                "module_capsule_id": merge_id,
                "provenance_source": _module_source(by_id[merge_id]),
                "input_bindings": _dict_list(merge_mapping.get("inputs")),
                "output_selector": merge_write.get("selector"),
            }
            app_provenance.insert(
                len(app_provenance) - 1,
                {"contributor_type": "module_capsule", "module_capsule_id": merge_id, "contribution": "logic_merge"},
            )
            index_provenance.append(
                {"contributor_type": "composer", "composer_id": COMPOSER_VERSION, "contribution": "generated_logic_merge_output"}
            )
        plan.update(
            {
                "composition_strategy": "behavior_adapter",
                "composition_topology": "fan_in" if merge_id else "fan_out" if branch_ids else "serial",
                "modules": modules,
                "regions": {},
                "region_merge_contract": {
                    "contract_version": REGION_MERGE_CONTRACT_VERSION,
                    "merge_mode": "behavior_adapter",
                    "selected_module_count": len(selected_modules),
                    "effects": {"model_call": False, "network_call": False, "store_write": False, "promotion": False},
                },
                "adapter_mapping_path": "adapter_mapping.json",
                "wiring": wires,
                "wiring_receipt": {
                    "receipt_version": WIRING_RECEIPT_VERSION,
                    "status": "wired",
                    "wires": wires,
                    "cross_region_writes": False,
                    "cross_module_wiring": True,
                    "unresolved_wires": [],
                },
                "provenance_map": provenance_map,
                "region_provenance": region_provenance,
                "file_provenance": {
                    "index.html": index_provenance,
                    "styles.css": [
                        {"contributor_type": "module_capsule", "module_capsule_id": ui_id, "contribution": "ui_style"}
                    ],
                    "app.js": app_provenance,
                    "adapter_mapping.json": [
                        {"contributor_type": "composer", "composer_id": COMPOSER_VERSION, "contribution": "port_mapping"}
                    ],
                    "composition_plan.json": [
                        {"contributor_type": "composer", "composer_id": COMPOSER_VERSION, "contribution": "composition_plan"}
                    ],
                },
            }
        )
    return plan


def _rejected(*, intent: dict[str, Any], rejected: list[dict[str, str]], selection_audit: dict[str, Any] | None = None) -> dict[str, Any]:
    audit = selection_audit or _selection_audit(candidates=[], selected=[], max_modules=int(intent.get("max_modules") or 1))
    return {
        "composer_version": COMPOSER_VERSION,
        "status": "composition_rejected",
        "composition_mode": "module_native",
        "intent": intent,
        "composition_plan": {
            "plan_version": COMPOSITION_PLAN_VERSION,
            "region_merge_contract": {
                "contract_version": REGION_MERGE_CONTRACT_VERSION,
                "merge_mode": "behavior_adapter",
                "selected_module_count": 0,
                "effects": {"model_call": False, "network_call": False, "store_write": False, "promotion": False},
            },
            "conflict_graph": audit.get("conflict_graph") or _conflict_graph([]),
            "modules": [],
            "regions": {},
            "wiring": [],
            "wiring_receipt": {
                "receipt_version": WIRING_RECEIPT_VERSION,
                "status": "not_wired",
                "wires": [],
                "cross_region_writes": False,
                "cross_module_wiring": False,
                "unresolved_wires": [],
            },
            "selection_receipt": {
                "selected": "",
                "rejected": rejected,
                "module_budget": audit.get("module_budget") or {},
                "auto_behavior": audit.get("auto_behavior") or {},
                "capability_graph": audit.get("capability_graph") or {},
            },
            "provenance_map": {},
            "region_provenance": {},
            "file_provenance": {},
        },
        "rejection_summary": _rejection_summary(rejected),
        "selected_module_capsule_ids": [],
        "files": {},
        "written_files": [],
        "permissions": _permissions(),
        "effects": _effects(),
        "default_desktop_path_changed": False,
    }


def _apply_slots(content: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        content = content.replace(f"{{{{slot.{key}}}}}", value)
    return content


def _rejection_summary(rejected: list[dict[str, str]]) -> dict[str, Any]:
    reasons = [str(row.get("reason") or "") for row in rejected if row.get("reason")]
    return {
        "total_rejected": len(rejected),
        "reasons": _unique(reasons),
        "counts_by_reason": {reason: reasons.count(reason) for reason in _unique(reasons)},
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _write_files(files: dict[str, str], root: Path) -> list[str]:
    return sorted(write_preview_files(files, root))


def _permissions(*, preview_write: bool = False) -> dict[str, bool]:
    return {
        "model_call": False,
        "network_call": False,
        "runtime_network_access": False,
        "workspace_write": False,
        "preview_write": preview_write,
        "store_write": False,
        "capsule_promotion_allowed": False,
        "fallback_full_generation_used": False,
    }


def _effects(*, preview_write: bool = False) -> dict[str, bool]:
    return {
        "preview_write": preview_write,
        "source_project_write": False,
        "real_source_project_write": False,
        "store_write": False,
        "promotion": False,
        "runtime_network_access": False,
    }


__all__ = [
    "CAPABILITY_GRAPH_VERSION",
    "COMPOSER_VERSION",
    "COMPOSITION_PLAN_VERSION",
    "build_module_capability_graph",
    "compose_module_native_preview",
]
