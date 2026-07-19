from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from pimos_lite.reweave_stage4_composer import (
    COMPOSER_OWNER,
    COMPOSER_SOURCE_OWNERSHIP,
    compose_with_stage4,
    extract_many_with_stage4,
    extract_with_stage4,
    list_stage4_module_capsules,
    plan_with_stage4,
)
from pimos_lite.composer.module_native import CAPABILITY_GRAPH_VERSION, build_module_capability_graph
from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_engine.lumo_lite import LumoLiteReweaveEngine
from pimos_lite.reweave_preview_viewer import get_latest_preview_package
from pimos_lite.reweave_project_renderer import LOCAL_RUNTIME_CSP, without_scripts


def _stage4_layout(root: Path) -> tuple[Path, Path]:
    capsules = root / "capsules"
    capsules.mkdir()
    return root, capsules


def _write_stage4_product(preview_root: Path) -> None:
    (preview_root / "index.html").write_text(
        f'<!doctype html><meta http-equiv="Content-Security-Policy" content="{LOCAL_RUNTIME_CSP}"><title>Estimate</title>',
        encoding="utf-8",
    )
    (preview_root / "styles.css").write_text("body {}", encoding="utf-8")
    (preview_root / "app.js").write_text("console.log('ready');", encoding="utf-8")
    (preview_root / "composition_plan.json").write_text("{}", encoding="utf-8")
    (preview_root / "adapter_mapping.json").write_text("{}", encoding="utf-8")


def _file_provenance(*module_ids: str) -> dict[str, list[dict[str, str]]]:
    ui_id = module_ids[0]
    logic_ids = module_ids[1:] or module_ids[:1]
    return {
        "index.html": [{"module_capsule_id": ui_id}],
        "styles.css": [{"module_capsule_id": ui_id}],
        "app.js": [{"module_capsule_id": module_id} for module_id in logic_ids],
    }


def _five_module_rows(tmp_path: Path) -> list[dict[str, object]]:
    repo = Path(__file__).resolve().parents[1]
    rows: list[dict[str, object]] = [
        extract_with_stage4(
            source_root=repo / "examples/source_boxes/order-form-ui",
            role="ui",
            source_id="source-ui",
        ),
        extract_with_stage4(
            source_root=repo / "examples/source_boxes/order-total-logic",
            role="logic",
            source_id="source-total",
        ),
        extract_with_stage4(
            source_root=repo / "examples/source_boxes/result-history-state",
            role="logic",
            source_id="source-history",
        ),
    ]
    for name, function in (
        ("increment", "function incrementResult(result) { return result + 1; }\n"),
        ("add", "function addResult(result) { return result + 2; }\n"),
    ):
        source = tmp_path / name
        source.mkdir()
        (source / f"{name}.js").write_text(function, encoding="utf-8")
        rows.append(extract_with_stage4(source_root=source, role="logic", source_id=f"source-{name}"))
    return rows


def _fan_out_rows(tmp_path: Path) -> list[dict[str, object]]:
    repo = Path(__file__).resolve().parents[1]
    rows: list[dict[str, object]] = [
        extract_with_stage4(
            source_root=repo / "examples/source_boxes/order-form-ui",
            role="ui",
            source_id="source-ui",
        ),
        extract_with_stage4(
            source_root=repo / "examples/source_boxes/order-total-logic",
            role="logic",
            source_id="source-total",
        ),
    ]
    for name, function in (
        ("discount", "function applyDiscount(result) { return result - 10; }\n"),
        ("tax", "function addTax(result) { return result + 5; }\n"),
    ):
        source = tmp_path / name
        source.mkdir()
        (source / f"{name}.js").write_text(function, encoding="utf-8")
        rows.append(extract_with_stage4(source_root=source, role="logic", source_id=f"source-{name}"))
    return rows


def _fan_in_rows(tmp_path: Path) -> list[dict[str, object]]:
    rows = _fan_out_rows(tmp_path)
    source = tmp_path / "merge"
    source.mkdir()
    (source / "merge.js").write_text(
        "function combinePayable(discountResult, taxResult) { return discountResult * 1000 + taxResult; }\n",
        encoding="utf-8",
    )
    rows.append(extract_with_stage4(source_root=source, role="logic", source_id="source-merge"))
    return rows


def _duplicate_action_rows(tmp_path: Path) -> list[dict[str, object]]:
    rows = _fan_out_rows(tmp_path)
    for row, delta in zip(rows[-2:], (-10, 5), strict=True):
        row["ports"]["actions"][0]["target"] = "adjustResult"
        row["payload"]["fragment_bundle"]["files_partial"][0]["content"] = (
            f"function adjustResult(result) {{ return result + ({delta}); }}\n"
        )
    return rows


def test_stage4_is_the_only_builtin_composer_owner(tmp_path: Path) -> None:
    _root, capsules = _stage4_layout(tmp_path)
    repo = Path(__file__).resolve().parents[1]
    for role, source in (
        ("ui", repo / "examples/source_boxes/order-form-ui"),
        ("logic", repo / "examples/source_boxes/order-total-logic"),
    ):
        module = extract_with_stage4(source_root=source, role=role, source_id=f"source-{role}")
        (capsules / f"{role}.json").write_text(json.dumps(module), encoding="utf-8")

    result = compose_with_stage4(
        goal="Build an estimate tool",
        capsule_path=capsules,
        max_modules=2,
        preview_root=tmp_path / "preview",
        auto_behavior=True,
    )

    assert result["status"] == "composed"
    assert result["composer_owner"] == COMPOSER_OWNER
    assert result["composer_source_ownership"] == COMPOSER_SOURCE_OWNERSHIP
    assert set(result["written_files"]) == {
        "adapter_mapping.json",
        "app.js",
        "composition_plan.json",
        "index.html",
        "styles.css",
    }


def test_stage4_failure_has_no_reweave_fallback(tmp_path: Path) -> None:
    _root, capsules = _stage4_layout(tmp_path)
    result = compose_with_stage4(goal="x", capsule_path=capsules)

    assert result["status"] == "composition_rejected"
    assert result["composer_owner"] == COMPOSER_OWNER
    assert not (tmp_path / "preview").exists()


def test_stage4_behavior_extractor_is_called_without_source_write(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text(
        '<!doctype html><input id="price" type="number"><button id="estimate">Estimate</button><output id="total">0</output>',
        encoding="utf-8",
    )
    (source / "styles.css").write_text("body {}", encoding="utf-8")
    result = extract_with_stage4(
        source_root=source,
        role="ui",
        source_id="source-a",
        source_capsule_id="cap-source-a",
    )

    assert result["composer_owner"] == COMPOSER_OWNER
    assert result["permissions"]["workspace_write"] is False
    assert result["permissions"]["source_boundary_escape"] is False
    assert result["permissions"]["runtime_network_access"] is False
    assert sorted(path.name for path in source.iterdir()) == ["index.html", "styles.css"]


def test_stage4_extracts_and_composes_one_closed_event_from_ordinary_js(tmp_path: Path) -> None:
    source = tmp_path / "source"
    assets = source / "assets"
    assets.mkdir(parents=True)
    (source / "index.html").write_text(
        '<!doctype html><html><head><link rel="stylesheet" href="assets/site.css"></head><body>'
        '<input id="price" type="number"><input id="count" type="number">'
        '<button id="estimate">Estimate</button><output id="total">0</output>'
        '<script src="assets/app.js"></script></body></html>',
        encoding="utf-8",
    )
    (assets / "site.css").write_text("body {}\n", encoding="utf-8")
    (assets / "app.js").write_text(
        'const price=document.getElementById("price");'
        'const count=document.getElementById("count");'
        'const estimate=document.getElementById("estimate");'
        'const total=document.getElementById("total");'
        'function normalizeAmount(value) { return Number(value); }'
        'function calculateTotal(unitPrice, count) {'
        'return normalizeAmount(unitPrice) * normalizeAmount(count);'
        '}'
        'function handleEstimate() {'
        'const currentPrice = Number(price.value);'
        'const currentCount = Number(count.value);'
        'total.textContent = calculateTotal(currentPrice, currentCount);'
        '}'
        'estimate.addEventListener("click", handleEstimate);',
        encoding="utf-8",
    )
    before = {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    modules = [
        extract_with_stage4(source_root=source, role="ui", source_id="ordinary"),
        extract_with_stage4(source_root=source, role="logic", source_id="ordinary"),
    ]
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    for module in modules:
        (capsules / f"{module['module_capsule_id']}.json").write_text(json.dumps(module), encoding="utf-8")
    preview = tmp_path / "preview"
    result = compose_with_stage4(
        goal="Build an estimate tool",
        capsule_path=capsules,
        module_ids=[str(module["module_capsule_id"]) for module in modules],
        max_modules=2,
        preview_root=preview,
    )
    harness = r"""const fs=require('fs'),vm=require('vm');const e={};const x={'#price':{value:'12'},'#count':{value:'8'},'#estimate':{addEventListener:(n,f)=>e[n]=f},'#total':{textContent:'0'}};global.document={addEventListener:(n,f)=>e[n]=f,querySelector:s=>x[s]};vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));e.DOMContentLoaded();e.click();if(x['#total'].textContent!=='96')throw Error(x['#total'].textContent);"""

    subprocess.run(["node", "-e", harness, str(preview / "app.js")], check=True)
    assert result["status"] == "composed"
    assert {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*") if path.is_file()} == before


def test_stage4_extracts_one_closed_class_state_projection(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "tracker.js").write_text(
        "class WaterTracker {\n"
        "  calculateConsumedFromHistory(historyArray) {\n"
        "    this.consumed = historyArray.reduce((sum, entry) => sum + entry.amount, 0);\n"
        "  }\n"
        "  logDrink(amount) {\n"
        "    this.history.push({ amount, timestamp: new Date().toISOString() });\n"
        "    localStorage.setItem('history', JSON.stringify(this.history));\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    before = (source / "tracker.js").read_bytes()

    module = extract_with_stage4(
        source_root=source,
        role="logic",
        source_id="water-tracker",
        source_capsule_id="cap-water-tracker",
    )
    script = module["payload"]["fragment_bundle"]["files_partial"][0]["content"]
    harness = script + "\nif (calculateConsumedFromHistory([{amount:250},{amount:500}]) !== 750) throw Error('bad total');"

    subprocess.run(["node", "-e", harness], check=True)
    assert module["module_kind"] == "behavior_state"
    assert module["ports"]["inputs"] == [
        {
            "id": "historyarray",
            "semantic_key": "history_array",
            "value_type": "record_list",
            "read": {"kind": "argument"},
            "required_fields": ["amount"],
        }
    ]
    assert module["ports"]["state"][0]["id"] == "consumed"
    assert module["ports"]["actions"][0]["target"] == "calculateConsumedFromHistory"
    assert module["provenance"]["source_symbol"] == "tracker.js#WaterTracker.calculateConsumedFromHistory"
    assert module["provenance"]["extraction_mode"] == "pure_state_projection"
    assert "localStorage" not in script
    assert (source / "tracker.js").read_bytes() == before


def test_stage4_extracts_multiple_closed_logic_modules_for_small_model_selection(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "pricing").mkdir(parents=True)
    (source / "shipping").mkdir()
    (source / "pricing" / "calculate.js").write_text(
        "function calculateTotal(unitPrice, count) { return unitPrice * count; }\n",
        encoding="utf-8",
    )
    (source / "shipping" / "estimate.js").write_text(
        "function estimateShipping(distance, rate) { return distance * rate; }\n",
        encoding="utf-8",
    )
    before = {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*") if path.is_file()}

    modules = extract_many_with_stage4(
        source_root=source,
        role="logic",
        source_id="source-tools",
        source_capsule_id="cap-script",
    )

    assert len(modules) == 2
    assert len({row["module_capsule_id"] for row in modules}) == 2
    assert {row["ports"]["actions"][0]["target"] for row in modules} == {"calculateTotal", "estimateShipping"}
    assert all(row["capability_summary"].startswith("Function ") for row in modules)
    assert all(row["permissions"]["workspace_write"] is False for row in modules)
    assert {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*") if path.is_file()} == before


def test_stage4_extracts_string_append_logic_contract(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "audit.js").write_text(
        'function auditResult(result) { return result + " / audited"; }\n',
        encoding="utf-8",
    )

    module = extract_with_stage4(source_root=source, role="logic", source_id="source-audit")

    assert module["ports"]["inputs"][0]["value_type"] == "string"
    assert module["ports"]["outputs"][0]["value_type"] == "string"


def test_capability_graph_accepts_generic_string_logic_chain(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    source = tmp_path / "source"
    source.mkdir()
    (source / "audit.js").write_text(
        'function auditResult(result) { return result + " / audited"; }\n',
        encoding="utf-8",
    )
    modules = [
        extract_with_stage4(
            source_root=repo / "examples/source_boxes/approval-workflow-ui",
            role="ui",
            source_id="workflow-ui",
        ),
        extract_with_stage4(
            source_root=repo / "examples/source_boxes/approval-state-logic",
            role="logic",
            source_id="workflow-toggle",
        ),
        extract_with_stage4(source_root=source, role="logic", source_id="workflow-audit"),
    ]

    graph = build_module_capability_graph(modules, goal="Toggle approval, then audit result", max_modules=3)

    assert any(
        row["currently_executable"]
        and [step["action"] for step in row["ordered_steps"] if step["role"] == "logic"]
        == ["toggleApprovalStatus", "auditResult"]
        for row in graph["plans"]
    )


def test_capability_graph_plans_five_executable_connected_capsules(tmp_path: Path) -> None:
    modules = _five_module_rows(tmp_path)

    graph = build_module_capability_graph(
        modules,
        goal="Build an estimate with result history increment and add steps",
        max_modules=5,
    )
    five = [row for row in graph["plans"] if len(row["module_ids"]) == 5]

    assert graph["graph_version"] == CAPABILITY_GRAPH_VERSION
    assert five
    assert all(row["currently_executable"] is True for row in five)
    assert all(len(row["connections"]) >= 7 for row in five)
    assert any(
        [step["action"] for step in row["ordered_steps"]]
        == ["estimate", "calculateTotal", "recordResultHistory", "incrementResult", "addResult"]
        for row in five
    )
    assert all("payload" not in row for row in graph["nodes"])
    assert all("payload" not in row for row in graph["model_candidates"])
    assert all(row.get("orderedSteps") for row in graph["model_candidates"])


def test_composer_executes_five_capsule_logic_chain(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required")
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    rows = _five_module_rows(tmp_path)
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")
    preview = tmp_path / "preview"

    result = compose_with_stage4(
        goal="Build an order estimate with result history increment and add steps",
        capsule_path=capsules,
        module_ids=[str(row["module_capsule_id"]) for row in rows],
        max_modules=5,
        preview_root=preview,
        auto_behavior=False,
    )
    assert result["status"] == "composed", result

    harness = """
const fs = require('fs');
const vm = require('vm');
const events = {};
const elements = {
  '#price': {value: '12'}, '#quantity': {value: '8'},
  '#estimate': {addEventListener: (name, fn) => { events[name] = fn; }},
  '#total': {textContent: '0'},
  '#reweave-state-result': {textContent: '0'},
  '#reweave-state-result-2': {textContent: '0'},
  '#reweave-state-result-3': {textContent: '0'}
};
global.document = {
  addEventListener: (name, fn) => { events[name] = fn; },
  querySelector: (selector) => elements[selector]
};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
events.DOMContentLoaded();
events.click();
const actual = ['#total', '#reweave-state-result', '#reweave-state-result-2', '#reweave-state-result-3']
  .map((key) => elements[key].textContent);
if (actual.join(',') !== '96,1,2,4') throw new Error(`unexpected chain: ${actual}`);
"""
    completed = subprocess.run(
        [node, "-e", harness, str(preview / "app.js")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert result["status"] == "composed"
    assert result["selection_mode"] == "explicit"
    assert len(result["selected_module_capsule_ids"]) == 5
    assert len(result["composition_plan"]["modules"]) == 5
    assert result["composition_plan"]["wiring_receipt"]["unresolved_wires"] == []
    app_contributors = {
        row["module_capsule_id"]
        for row in result["composition_plan"]["file_provenance"]["app.js"]
        if row.get("module_capsule_id")
    }
    assert app_contributors == set(result["selected_module_capsule_ids"][1:])
    assert result["effects"]["source_project_write"] is False


def test_composer_executes_verified_fan_out_plan(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required")
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    rows = _fan_out_rows(tmp_path)
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")
    graph = build_module_capability_graph(
        rows,
        goal="Calculate the total, then apply discount and add tax independently",
        max_modules=4,
    )
    plan = next(row for row in graph["plans"] if row["topology"] == "fan_out" and len(row["module_ids"]) == 4)
    preview = tmp_path / "preview"

    result = compose_with_stage4(
        goal="Calculate the total, then apply discount and add tax independently",
        capsule_path=capsules,
        module_ids=plan["module_ids"],
        max_modules=4,
        preview_root=preview,
        selected_plan_id=plan["plan_id"],
    )
    harness = r"""const fs=require('fs'),vm=require('vm');const e={};const x={'#price':{value:'12'},'#quantity':{value:'8'},'#estimate':{addEventListener:(n,f)=>e[n]=f},'#total':{textContent:'0'},'#reweave-state-result':{textContent:'0'},'#reweave-state-result-2':{textContent:'0'}};global.document={addEventListener:(n,f)=>e[n]=f,querySelector:s=>x[s]};vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));e.DOMContentLoaded();e.click();const branches=[x['#reweave-state-result'].textContent,x['#reweave-state-result-2'].textContent].sort();if(x['#total'].textContent!=='96'||branches.join(',')!=='101,86')throw Error(`${x['#total'].textContent}:${branches}`);"""
    completed = subprocess.run(
        [node, "-e", harness, str(preview / "app.js")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert result["status"] == "composed"
    assert result["selection_mode"] == "selected_capability_plan"
    assert result["selected_capability_plan_id"] == plan["plan_id"]
    assert result["composition_plan"]["composition_topology"] == "fan_out"
    assert result["composition_plan"]["selection_receipt"]["selected_capability_plan"]["plan_id"] == plan["plan_id"]
    app_contributors = {
        row["module_capsule_id"]
        for row in result["composition_plan"]["file_provenance"]["app.js"]
        if row.get("module_capsule_id")
    }
    assert app_contributors == set(plan["module_ids"][1:])
    assert result["effects"]["source_project_write"] is False


def test_composer_isolates_duplicate_logic_action_symbols(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required")
    rows = _duplicate_action_rows(tmp_path)
    graph = build_module_capability_graph(rows, goal="Build parallel adjustments", max_modules=4)
    duplicate_ids = {str(row["module_capsule_id"]) for row in rows[-2:]}
    plan = next(
        plan
        for plan in graph["plans"]
        if plan["topology"] == "fan_out" and duplicate_ids.issubset(set(plan["module_ids"]))
    )

    capsules = tmp_path / "duplicate-action-capsules"
    capsules.mkdir()
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")
    preview = tmp_path / "duplicate-action-preview"
    result = compose_with_stage4(
        goal="Build parallel adjustments",
        capsule_path=capsules,
        module_ids=plan["module_ids"],
        max_modules=4,
        preview_root=preview,
        selected_plan_id=plan["plan_id"],
    )
    harness = r"""const fs=require('fs'),vm=require('vm');const e={};const x={'#price':{value:'12'},'#quantity':{value:'8'},'#estimate':{addEventListener:(n,f)=>e[n]=f},'#total':{textContent:'0'},'#reweave-state-result':{textContent:'0'},'#reweave-state-result-2':{textContent:'0'}};global.document={addEventListener:(n,f)=>e[n]=f,querySelector:s=>x[s]};vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));e.DOMContentLoaded();e.click();const branches=[x['#reweave-state-result'].textContent,x['#reweave-state-result-2'].textContent].sort();if(branches.join(',')!=='101,86')throw Error(branches.join(','));"""
    completed = subprocess.run([node, "-e", harness, str(preview / "app.js")], capture_output=True, text=True)

    assert completed.returncode == 0, completed.stderr
    assert result["status"] == "composed"
    mappings = json.loads((preview / "adapter_mapping.json").read_text(encoding="utf-8"))["logic_branches"]
    assert {row["function"] for row in mappings} == {"reweaveBranchLogic1", "reweaveBranchLogic2"}
    assert {row["source_function"] for row in mappings} == {"adjustResult"}


def test_auto_behavior_executes_its_selected_fan_out_topology(tmp_path: Path) -> None:
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    rows = _fan_out_rows(tmp_path)
    for row, semantic_key in zip(rows[2:], ("discount_result", "tax_result")):
        row["ports"]["outputs"][0]["semantic_key"] = semantic_key
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")

    result = compose_with_stage4(
        goal="Calculate total with discount and tax",
        capsule_path=capsules,
        max_modules=4,
        preview_root=tmp_path / "preview",
        auto_behavior=True,
    )

    assert result["status"] == "composed"
    assert result["composition_plan"]["composition_topology"] == "fan_out"
    assert result["composition_plan"]["selection_receipt"]["auto_behavior"]["mode"] == "branch"


def test_composer_executes_verified_fan_in_plan(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required")
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    rows = _fan_in_rows(tmp_path)
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")
    task = "Calculate total, run discount and tax independently, then combine both results"
    graph = build_module_capability_graph(rows, goal=task, max_modules=5)
    plan = next(row for row in graph["plans"] if row["topology"] == "fan_in" and len(row["module_ids"]) == 5)
    preview = tmp_path / "preview"

    result = compose_with_stage4(
        goal=task,
        capsule_path=capsules,
        module_ids=plan["module_ids"],
        max_modules=5,
        preview_root=preview,
        selected_plan_id=plan["plan_id"],
    )
    harness = r"""const fs=require('fs'),vm=require('vm');const e={};const x={'#price':{value:'12'},'#quantity':{value:'8'},'#estimate':{addEventListener:(n,f)=>e[n]=f},'#total':{textContent:'0'},'#reweave-state-result':{textContent:'0'},'#reweave-state-result-2':{textContent:'0'},'#reweave-merge-result':{textContent:'0'}};global.document={addEventListener:(n,f)=>e[n]=f,querySelector:s=>x[s]};vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));e.DOMContentLoaded();e.click();if(x['#total'].textContent!=='96'||x['#reweave-state-result'].textContent!=='86'||x['#reweave-state-result-2'].textContent!=='101'||x['#reweave-merge-result'].textContent!=='86101')throw Error(`${x['#total'].textContent}:${x['#reweave-state-result'].textContent}:${x['#reweave-state-result-2'].textContent}:${x['#reweave-merge-result'].textContent}`);"""
    completed = subprocess.run(
        [node, "-e", harness, str(preview / "app.js")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert result["status"] == "composed"
    assert result["composition_plan"]["composition_topology"] == "fan_in"
    assert result["composition_plan"]["selection_receipt"]["selected_capability_plan"]["plan_id"] == plan["plan_id"]
    app_contributors = {
        row["module_capsule_id"]
        for row in result["composition_plan"]["file_provenance"]["app.js"]
        if row.get("module_capsule_id")
    }
    assert app_contributors == set(plan["module_ids"][1:])
    assert result["effects"]["source_project_write"] is False


def test_capability_graph_rejects_ambiguous_fan_in_mapping(tmp_path: Path) -> None:
    rows = _fan_out_rows(tmp_path)
    source = tmp_path / "ambiguous-merge"
    source.mkdir()
    (source / "merge.js").write_text(
        "function combineResults(leftValue, rightValue) { return leftValue + rightValue; }\n",
        encoding="utf-8",
    )
    rows.append(extract_with_stage4(source_root=source, role="logic", source_id="source-ambiguous"))

    graph = build_module_capability_graph(
        rows,
        goal="Calculate total, branch twice, then combine results",
        max_modules=5,
    )

    assert not any(row["topology"] == "fan_in" for row in graph["plans"])


def test_capability_graph_prioritizes_task_relevant_nodes_before_plan_budget(tmp_path: Path) -> None:
    ui_base, logic_base = _fan_out_rows(tmp_path)[:2]
    ui_rows = []
    logic_rows = []
    for index in range(20):
        ui = json.loads(json.dumps(ui_base))
        ui.update(
            {
                "module_capsule_id": f"module-ui-{index:02d}",
                "library_key": f"ui-{index:02d}",
                "capability_tags": [f"ui-noise-{index}"],
                "capability_summary": f"ui noise {index}",
            }
        )
        ui_rows.append(ui)
        logic = json.loads(json.dumps(logic_base))
        logic.update(
            {
                "module_capsule_id": f"module-logic-{index:02d}",
                "library_key": f"logic-{index:02d}",
                "capability_tags": [f"logic-noise-{index}"],
                "capability_summary": f"logic noise {index}",
            }
        )
        logic_rows.append(logic)
    ui_rows[-1].update({"capability_tags": ["needle-ui"], "capability_summary": "needle ui"})
    logic_rows[-1].update({"capability_tags": ["needle-logic"], "capability_summary": "needle logic"})

    graph = build_module_capability_graph(
        [*ui_rows, *logic_rows],
        goal="Build needle ui with needle logic",
        max_modules=2,
    )
    wanted = {"module-ui-19", "module-logic-19"}

    assert graph["plan_limit_reached"] is True
    assert any(set(row["module_ids"]) == wanted for row in graph["plans"])
    assert any(set(row["moduleIds"]) == wanted for row in graph["model_candidates"])


def test_composer_rejects_unknown_selected_capability_plan(tmp_path: Path) -> None:
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    rows = _fan_out_rows(tmp_path)
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")

    result = compose_with_stage4(
        goal="Build a fan-out estimate",
        capsule_path=capsules,
        module_ids=[str(row["module_capsule_id"]) for row in rows],
        max_modules=4,
        preview_root=tmp_path / "preview",
        selected_plan_id="cap-plan-invented",
    )

    assert result["status"] == "composition_rejected"
    assert result["rejection_summary"]["reasons"] == ["selected_capability_plan_invalid"]
    assert not (tmp_path / "preview").exists()


def test_composer_executes_data_with_logic_chain(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required")
    repo = Path(__file__).resolve().parents[1]
    rows = [
        extract_with_stage4(
            source_root=repo / "examples/source_boxes/order-data-view-ui",
            role="ui",
            source_id="data-ui",
        ),
        extract_with_stage4(
            source_root=repo / "examples/source_boxes/order-records-data",
            role="data",
            source_id="records",
        ),
        extract_with_stage4(
            source_root=repo / "examples/source_boxes/regional-total-logic",
            role="logic",
            source_id="regional-total",
        ),
    ]
    for name, function in (
        ("add-fee", "function addFee(result) { return result + 5; }\n"),
        ("double-result", "function doubleResult(result) { return result * 2; }\n"),
    ):
        source = tmp_path / name
        source.mkdir()
        (source / f"{name}.js").write_text(function, encoding="utf-8")
        rows.append(extract_with_stage4(source_root=source, role="logic", source_id=name))
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")
    preview = tmp_path / "preview"

    result = compose_with_stage4(
        goal="Calculate regional total, then add fee, then double result",
        capsule_path=capsules,
        module_ids=[str(row["module_capsule_id"]) for row in rows],
        max_modules=5,
        preview_root=preview,
    )
    harness = r"""const fs=require('fs'),vm=require('vm');const e={},rows=[];const x={'#region':{value:'North'},'#filter-orders':{addEventListener:(n,f)=>e[n]=f},'#region-total':{textContent:'0'},'#orders-body':{replaceChildren:()=>{rows.length=0},appendChild:r=>rows.push(r)},'#reweave-state-result':{textContent:'0'},'#reweave-state-result-2':{textContent:'0'}};global.document={addEventListener:(n,f)=>e[n]=f,querySelector:s=>x[s],createElement:t=>({tag:t,children:[],textContent:'',appendChild(c){this.children.push(c)}})};vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));e.DOMContentLoaded();e.click();const a=['#region-total','#reweave-state-result','#reweave-state-result-2'].map(k=>x[k].textContent);if(a.join(',')!=='420,425,850'||rows.length!==3)throw Error(a);"""
    completed = subprocess.run(
        [node, "-e", harness, str(preview / "app.js")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result["status"] == "composed"
    assert completed.returncode == 0, completed.stderr
    assert len(result["selected_module_capsule_ids"]) == 5
    assert result["effects"]["source_project_write"] is False


def test_auto_behavior_rejects_ambiguous_five_capsule_order(tmp_path: Path) -> None:
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    rows = _five_module_rows(tmp_path)
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")

    result = compose_with_stage4(
        goal="Build an order estimate with result history increment and add steps",
        capsule_path=capsules,
        max_modules=5,
        preview_root=tmp_path / "preview",
        auto_behavior=True,
    )

    assert result["status"] == "composition_rejected"
    assert "auto_behavior_ambiguous" in result["rejection_summary"]["reasons"]
    assert not (tmp_path / "preview").exists()


def test_capability_graph_bounds_large_plan_search_for_small_models() -> None:
    repo = Path(__file__).resolve().parents[1]
    ui = extract_with_stage4(
        source_root=repo / "examples/source_boxes/order-form-ui",
        role="ui",
        source_id="source-ui",
    )
    primary = extract_with_stage4(
        source_root=repo / "examples/source_boxes/order-total-logic",
        role="logic",
        source_id="source-total",
    )
    state = extract_with_stage4(
        source_root=repo / "examples/source_boxes/result-history-state",
        role="logic",
        source_id="source-history",
    )
    states = []
    for index in range(20):
        row = json.loads(json.dumps(state))
        row["module_capsule_id"] = f"module-state-{index}"
        row["library_key"] = f"source/state/{index}"
        states.append(row)

    graph = build_module_capability_graph(
        [ui, primary, *states],
        goal="Build estimate result history",
        max_modules=5,
    )

    assert len(graph["plans"]) <= 256
    assert len(graph["model_candidates"]) <= 12
    assert graph["plan_limit_reached"] is True


@pytest.mark.parametrize(
    ("html", "styles", "reason"),
    [
        (
            '<input id="price" type="number"><button id="estimate">Estimate</button>'
            '<output id="total">0</output><p>password=supersecret</p>',
            "body {}",
            "source_secret_detected:index.html",
        ),
        (
            '<iframe src="https://example.invalid/frame"></iframe><input id="price" type="number">'
            '<button id="estimate">Estimate</button><output id="total">0</output>',
            "body {}",
            "ui_source_runtime_network_resource_not_allowed",
        ),
        (
            '<iframe src=https://example.invalid/frame></iframe><input id="price" type="number">'
            '<button id="estimate">Estimate</button><output id="total">0</output>',
            "body {}",
            "ui_source_runtime_network_resource_not_allowed",
        ),
        (
            '<input id="price" type="number"><button id="estimate">Estimate</button><output id="total">0</output>',
            "body { background: url(https://example.invalid/bg.png); }",
            "ui_source_runtime_network_resource_not_allowed",
        ),
    ],
)
def test_stage4_extractor_rejects_secret_and_runtime_network_sources(
    tmp_path: Path, html: str, styles: str, reason: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text(html, encoding="utf-8")
    (source / "styles.css").write_text(styles, encoding="utf-8")

    result = extract_with_stage4(source_root=source, role="ui", source_id="source-a")

    assert result == {"status": "rejected", "reason": reason, "source_project_write": False}


def test_stage4_extractor_rejects_source_file_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.css"
    outside.write_text("body { color: red; }", encoding="utf-8")
    (source / "index.html").write_text(
        '<input id="price" type="number"><button id="estimate">Estimate</button><output id="total">0</output>',
        encoding="utf-8",
    )
    (source / "styles.css").symlink_to(outside)

    result = extract_with_stage4(source_root=source, role="ui", source_id="source-a")

    assert result == {
        "status": "rejected",
        "reason": "source_symlink_not_allowed:styles.css",
        "source_project_write": False,
    }


def test_stage4_script_stripping_handles_malformed_end_tag() -> None:
    source = '<main>safe<script src="app.js"></script \t><p>after</p></main>'

    result = without_scripts(source)

    assert result == "<main>safe<p>after</p></main>"


def test_stage4_data_extractor_rejects_symlink_and_secret(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text('[{"region":"north","amount":1}]', encoding="utf-8")
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / "data.json").symlink_to(outside)
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "data.json").write_text('[{"password":"supersecret","amount":1}]', encoding="utf-8")

    linked_result = extract_with_stage4(source_root=linked, role="data", source_id="source-data")
    secret_result = extract_with_stage4(source_root=secret, role="data", source_id="source-data")

    assert linked_result["status"] == "rejected"
    assert linked_result["reason"] == "source_symlink_not_allowed:data.json"
    assert secret_result["status"] == "rejected"
    assert secret_result["reason"] == "source_secret_detected:data.json"


def test_stage4_extractor_rejects_oversized_source_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text("x" * (1024 * 1024 + 1), encoding="utf-8")
    (source / "styles.css").write_text("body {}", encoding="utf-8")

    result = extract_with_stage4(source_root=source, role="ui", source_id="source-a")

    assert result == {
        "status": "rejected",
        "reason": "source_file_too_large:index.html",
        "source_project_write": False,
    }


def test_invalid_json_data_candidate_does_not_discard_valid_ui_module(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text(
        '<input id="price" type="number"><button id="estimate">Estimate</button><output id="total">0</output>',
        encoding="utf-8",
    )
    (source / "styles.css").write_text("body {}", encoding="utf-8")
    (source / "package.json").write_text('{"name":"old-project"}', encoding="utf-8")
    state = tmp_path / "state"

    with patch.dict("os.environ", {"REWEAVE_STATE_DIR": str(state)}):
        engine = LumoLiteReweaveEngine()
        box = engine.bind_source_folder(str(source))
        engine.scan_source(str(box["id"]))
        engine.draft_source(str(box["id"]))
        promoted = engine.promote_source(str(box["id"]))
        modules = engine._local_stage4_modules()

    assert promoted[0]["stage4_extraction"]["status"] == "extracted_with_warnings"
    assert any(warning.startswith("data:") for warning in promoted[0]["stage4_extraction"]["warnings"])
    assert [module["moduleKind"] for module in modules] == ["behavior_ui"]


def test_source_promotion_stores_multiple_closed_behavior_modules(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "logic").mkdir(parents=True)
    (source / "index.html").write_text(
        '<!doctype html><input id="unitPrice" type="number"><input id="count" type="number">'
        '<button id="estimate">Estimate</button><output id="total">0</output>',
        encoding="utf-8",
    )
    (source / "styles.css").write_text("body {}", encoding="utf-8")
    (source / "logic" / "total.js").write_text(
        "function calculateTotal(unitPrice, count) { return unitPrice * count; }\n",
        encoding="utf-8",
    )
    (source / "logic" / "discount.js").write_text(
        "function calculateDiscount(subtotal, rate) { return subtotal * rate; }\n",
        encoding="utf-8",
    )
    state = tmp_path / "state"
    before = {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*") if path.is_file()}

    with patch.dict("os.environ", {"REWEAVE_STATE_DIR": str(state)}):
        engine = LumoLiteReweaveEngine()
        box = engine.bind_source_folder(str(source))
        engine.scan_source(str(box["id"]))
        engine.draft_source(str(box["id"]))
        promoted = engine.promote_source(str(box["id"]))
        modules = engine._local_stage4_modules()

    assert promoted[0]["stage4_extraction"]["status"] == "extracted"
    assert [row["moduleKind"] for row in modules].count("behavior_logic") == 2
    assert [row["moduleKind"] for row in modules].count("behavior_ui") == 1
    logic_summaries = {row["capabilitySummary"] for row in modules if row["moduleKind"] == "behavior_logic"}
    assert any("calculateTotal" in summary for summary in logic_summaries)
    assert any("calculateDiscount" in summary for summary in logic_summaries)
    assert {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*") if path.is_file()} == before


def test_stage4_capsule_listing_is_sanitized(tmp_path: Path) -> None:
    _cli, capsules = _stage4_layout(tmp_path)
    (capsules / "ui.json").write_text(
        json.dumps(
            {
                "module_capsule_id": "module-ui",
                "module_kind": "estimate_form",
                "capability_tags": ["estimate_form"],
                "status": "active",
                "provenance": {"source_preview_id": "source-a", "local_path": "/private/source"},
            }
        ),
        encoding="utf-8",
    )
    (capsules / "linked.json").symlink_to(capsules / "ui.json")

    result = list_stage4_module_capsules(capsule_path=capsules)

    assert result == [
        {
            "id": "module-ui",
            "name": "Estimate Form",
            "type": "Behavior module",
            "tags": ["estimate_form"],
            "status": "active",
            "origin": COMPOSER_OWNER,
            "moduleKind": "estimate_form",
            "source": "source-a",
        }
    ]


def test_reextract_preserves_stale_source_module_when_new_extract_is_rejected(tmp_path: Path) -> None:
    _stage4_layout(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    state = tmp_path / "state"
    engine = LumoLiteReweaveEngine()
    with patch.dict("os.environ", {"REWEAVE_STATE_DIR": str(state)}):
        box = engine.bind_source_folder(str(source))
        source_id = str(box["id"])
        capsule = {"id": "cap-ui", "name": "Page Shell"}
        ready = {
            "module_capsule_version": "module_capsule.v1",
            "module_capsule_id": "module-ui",
            "provenance": {"source_box_id": source_id, "source_capsule_ids": ["cap-ui"]},
        }
        with patch("pimos_lite.reweave_engine.lumo_lite.extract_many_with_stage4", return_value=[ready]):
            assert engine._extract_source_behavior_modules(source_id, [capsule]) == [ready]
        assert list((state / "stage4_behavior_modules").glob("*.json"))

        legacy = state / "stage4_behavior_modules" / "legacy.json"
        legacy.write_text(
            json.dumps({"module_capsule_id": f"module-{source_id.replace('_', '-')}-logic", "provenance": {}}),
            encoding="utf-8",
        )
        before = {path.name: path.read_bytes() for path in (state / "stage4_behavior_modules").glob("*.json")}

        with patch(
            "pimos_lite.reweave_engine.lumo_lite.extract_many_with_stage4",
            return_value=[{"status": "rejected", "reason": "no_behavior"}],
        ):
            assert engine._extract_source_behavior_modules(source_id, [capsule]) == []
        after = {path.name: path.read_bytes() for path in (state / "stage4_behavior_modules").glob("*.json")}
        assert after == before

        with patch("pimos_lite.reweave_engine.lumo_lite.extract_many_with_stage4", side_effect=TimeoutError("timeout")):
            with pytest.raises(TimeoutError):
                engine._extract_source_behavior_modules(source_id, [capsule])
        assert {path.name: path.read_bytes() for path in (state / "stage4_behavior_modules").glob("*.json")} == before


def test_stage4_extract_timeout_does_not_fail_regular_capsule_promotion(tmp_path: Path) -> None:
    engine = LumoLiteReweaveEngine()
    promoted = [{"id": "cap-ui", "name": "Page Shell"}]
    with (
        patch("pimos_lite.reweave_engine.lumo_lite.promote_local_drafts", return_value=promoted),
        patch("pimos_lite.reweave_engine.lumo_lite.enrich_local_capsule_content"),
        patch("pimos_lite.reweave_engine.lumo_lite.get_local_capsule", return_value=promoted[0]),
        patch.object(engine, "_extract_source_behavior_modules", side_effect=TimeoutError("extract timeout")),
    ):
        result = engine.promote_source("source-a")

    assert result[0]["id"] == "cap-ui"
    assert result[0]["stage4_extraction"] == {"status": "failed", "warnings": ["extract timeout"]}


def test_desktop_engine_routes_selected_modules_to_stage4(tmp_path: Path) -> None:
    _cli, capsules = _stage4_layout(tmp_path)
    modules = [
        {"id": "module-ui", "name": "Form UI", "tags": ["estimate_form"], "status": "active", "origin": COMPOSER_OWNER},
        {"id": "module-logic", "name": "Calculation", "tags": ["calculation"], "status": "active", "origin": COMPOSER_OWNER},
    ]
    composed = {
        "status": "composed",
        "composer_owner": COMPOSER_OWNER,
        "composer_source_ownership": COMPOSER_SOURCE_OWNERSHIP,
        "composition_strategy": "behavior_adapter",
        "selected_module_capsule_ids": ["module-ui", "module-logic"],
        "files": {"index.html": "", "styles.css": "", "app.js": "", "composition_plan.json": "", "adapter_mapping.json": ""},
        "composition_plan": {"file_provenance": _file_provenance("module-ui", "module-logic")},
        "effects": {"source_project_write": False},
    }
    def compose_result(**kwargs: object) -> dict[str, object]:
        _write_stage4_product(Path(str(kwargs["preview_root"])))
        return composed

    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch("pimos_lite.reweave_engine.lumo_lite.list_stage4_module_capsules", return_value=modules),
        patch("pimos_lite.reweave_engine.lumo_lite.compose_with_stage4", side_effect=compose_result) as compose,
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir", return_value=tmp_path / "previews"),
        patch("pimos_lite.reweave_engine.lumo_lite.append_preview_history_entry") as history,
    ):
        result = engine.generate_preview(
            {"taskText": "Build an estimate tool", "capsuleIds": ["module-ui", "module-logic"], "selectionMode": "manual"}
        )
        expected_entry = tmp_path / "previews" / result["generatedPackage"]["folder"] / "index.html"
        assert engine.get_latest_product_entry_path() == str(expected_entry.resolve())
        service = ReweaveAppService(engine=engine)
        assert service.get_latest_product_entry_path() is None
        assert service.generate_preview({"taskText": "legacy"})["error"]["code"] == "legacy_generation_inactive"
        expected_entry.unlink()
        expected_entry.symlink_to(tmp_path / "outside.html")
        assert engine.get_latest_product_entry_path() is None

    assert result["ok"] is True
    assert result["mode"] == "stage4_behavior_composition_preview"
    assert set(result["generatedPackage"]["files"]) == {
        "adapter_mapping.json",
        "app.js",
        "capsules_used.json",
        "composition_plan.json",
        "index.html",
        "provenance.json",
        "quality_gate.json",
        "styles.css",
        "task_pack.json",
    }
    preview_root = Path(result["previewPath"])
    assert json.loads((preview_root / "task_pack.json").read_text(encoding="utf-8")) == result["taskPack"]
    assert json.loads((preview_root / "provenance.json").read_text(encoding="utf-8")) == result["provenance"]
    assert all(row["usage"] == "output_contributor" for row in json.loads((preview_root / "capsules_used.json").read_text(encoding="utf-8")))
    assert json.loads((preview_root / "quality_gate.json").read_text(encoding="utf-8"))["status"] == "passed"
    history.assert_called_once()
    assert result["previewAcceptance"] == {"verdict": "needs_review", "reason": "desktop_runtime_validation_required"}
    assert result["source_project_write"] is False
    assert result["taskPack"]["composer_source_ownership"] == COMPOSER_SOURCE_OWNERSHIP
    assert result["provenance"]["composer_source_ownership"] == COMPOSER_SOURCE_OWNERSHIP
    assert compose.call_args.kwargs["module_ids"] == ["module-ui", "module-logic"]


def test_desktop_engine_rejects_stage4_product_with_permissive_csp(tmp_path: Path) -> None:
    _cli, capsules = _stage4_layout(tmp_path)
    modules = [
        {"id": "module-ui", "name": "Form UI", "tags": ["form"], "status": "active", "origin": COMPOSER_OWNER},
        {"id": "module-logic", "name": "Logic", "tags": ["logic"], "status": "active", "origin": COMPOSER_OWNER},
    ]
    composed = {
        "status": "composed",
        "composer_owner": COMPOSER_OWNER,
        "composer_source_ownership": COMPOSER_SOURCE_OWNERSHIP,
        "composition_strategy": "behavior_adapter",
        "selected_module_capsule_ids": ["module-ui", "module-logic"],
        "composition_plan": {"file_provenance": _file_provenance("module-ui", "module-logic")},
    }

    def compose_result(**kwargs: object) -> dict[str, object]:
        root = Path(str(kwargs["preview_root"]))
        _write_stage4_product(root)
        (root / "index.html").write_text(
            '<meta http-equiv="Content-Security-Policy" content="default-src *"><title>Unsafe</title>',
            encoding="utf-8",
        )
        return composed

    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch("pimos_lite.reweave_engine.lumo_lite.list_stage4_module_capsules", return_value=modules),
        patch("pimos_lite.reweave_engine.lumo_lite.compose_with_stage4", side_effect=compose_result),
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir", return_value=tmp_path / "previews"),
        patch("pimos_lite.reweave_engine.lumo_lite.append_preview_history_entry") as history,
    ):
        result = engine.generate_preview(
            {"taskText": "Build a tool", "capsuleIds": ["module-ui", "module-logic"], "selectionMode": "manual"}
        )

    assert result["ok"] is False
    assert result["error"] == "stage4_runtime_security_failed"
    assert result["checks"]["canonical_csp"] is False
    assert not Path(result.get("previewPath", tmp_path / "missing")).exists()
    history.assert_not_called()


def test_desktop_engine_auto_behavior_uses_only_local_stage4_modules(tmp_path: Path) -> None:
    _cli, capsules = _stage4_layout(tmp_path)
    modules = [
        {"id": "module-ui", "name": "Form UI", "tags": ["form"], "status": "active", "origin": COMPOSER_OWNER},
        {"id": "module-logic", "name": "Logic", "tags": ["logic"], "status": "active", "origin": COMPOSER_OWNER},
    ]
    composed = {
        "status": "composed",
        "composer_owner": COMPOSER_OWNER,
        "composition_strategy": "behavior_adapter",
        "selected_module_capsule_ids": ["module-ui", "module-logic"],
        "files": {"index.html": "", "styles.css": "", "app.js": "", "composition_plan.json": "", "adapter_mapping.json": ""},
        "composition_plan": {"file_provenance": _file_provenance("module-ui", "module-logic")},
        "effects": {"source_project_write": False},
    }
    def compose_result(**kwargs: object) -> dict[str, object]:
        _write_stage4_product(Path(str(kwargs["preview_root"])))
        return composed

    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_modules", return_value=modules),
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch("pimos_lite.reweave_engine.lumo_lite.compose_with_stage4", side_effect=compose_result) as compose,
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir", return_value=tmp_path / "previews"),
        patch("pimos_lite.reweave_engine.lumo_lite.append_preview_history_entry"),
    ):
        result = engine.generate_preview({"taskText": "Build a form", "selectionMode": "auto_behavior"})

    assert result["ok"] is True
    assert result["taskPack"]["selection_mode"] == "auto_behavior"
    assert compose.call_args.kwargs["module_ids"] == []
    assert compose.call_args.kwargs["auto_behavior"] is True


def test_small_model_can_only_rank_executable_capability_graph_plans(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    alternate = tmp_path / "alternate"
    alternate.mkdir()
    (alternate / "compute.js").write_text(
        "function computeTotal(unitPrice, count) { return unitPrice * count; }\n",
        encoding="utf-8",
    )
    rows = [
        extract_with_stage4(
            source_root=repo / "examples/source_boxes/order-form-ui",
            role="ui",
            source_id="source-ui",
        ),
        extract_with_stage4(
            source_root=repo / "examples/source_boxes/order-total-logic",
            role="logic",
            source_id="source-total",
        ),
        extract_with_stage4(source_root=alternate, role="logic", source_id="source-alternate"),
    ]
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")
    modules = list_stage4_module_capsules(capsule_path=capsules)
    def select_actions(**kwargs: object) -> dict[str, object]:
        assert kwargs["actions"] == ["calculateTotal", "computeTotal"]
        return {
            "ordered_actions": ["computeTotal"],
            "meta": {"applied": True, "status": "applied", "local_http_call": True, "source_project_write": False},
        }

    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_modules", return_value=modules),
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch("pimos_lite.reweave_engine.lumo_lite.select_ollama_action_sequence", side_effect=select_actions),
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir", return_value=tmp_path / "previews"),
        patch("pimos_lite.reweave_engine.lumo_lite.append_preview_history_entry"),
    ):
        result = engine.generate_preview(
            {
                "taskText": "Build an order total estimate",
                "selectionMode": "auto_behavior",
                "localModel": {
                    "enabled": True,
                    "provider": "ollama",
                    "model": "qwen2.5-coder:1.5b",
                    "capsuleRanking": True,
                    "require": True,
                },
            }
        )

    assert result["ok"] is True
    assert result["taskPack"]["selection_mode"] == "model_ranked_behavior_plan"
    assert [
        step["action"] for step in result["taskPack"]["capability_graph_plan"]["ordered_steps"] if step["role"] == "logic"
    ] == ["computeTotal"]
    assert result["taskPack"]["model_selection"]["applied"] is True
    assert result["model_call"] is True
    assert result["network_call"] is True
    assert result["source_project_write"] is False


def test_small_model_can_select_and_execute_five_capsule_plan(tmp_path: Path) -> None:
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    rows = _five_module_rows(tmp_path)
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")
    modules = list_stage4_module_capsules(capsule_path=capsules)
    desired_ids = [str(row["module_capsule_id"]) for row in rows]
    def select_actions(**kwargs: object) -> dict[str, object]:
        assert set(kwargs["actions"]) == {"addResult", "calculateTotal", "incrementResult", "recordResultHistory"}
        return {
            "ordered_actions": ["calculateTotal", "recordResultHistory", "incrementResult", "addResult"],
            "meta": {"applied": True, "status": "applied", "local_http_call": True, "source_project_write": False},
        }

    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_modules", return_value=modules),
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch("pimos_lite.reweave_engine.lumo_lite.select_ollama_action_sequence", side_effect=select_actions),
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir", return_value=tmp_path / "previews"),
        patch("pimos_lite.reweave_engine.lumo_lite.append_preview_history_entry"),
    ):
        result = engine.generate_preview(
            {
                "taskText": "Build an order estimate with result history increment and add steps",
                "selectionMode": "auto_behavior",
                "localModel": {
                    "enabled": True,
                    "provider": "ollama",
                    "model": "qwen2.5-coder:1.5b",
                    "capsuleRanking": True,
                    "require": True,
                },
            }
        )

    assert result["ok"] is True
    assert result["taskPack"]["selection_mode"] == "model_ranked_behavior_plan"
    assert [
        step["action"] for step in result["taskPack"]["capability_graph_plan"]["ordered_steps"] if step["role"] == "logic"
    ] == ["calculateTotal", "recordResultHistory", "incrementResult", "addResult"]
    assert result["taskPack"]["selected_capsule_ids"] == desired_ids
    assert len(result["taskPack"]["composition_plan"]["modules"]) == 5
    assert result["source_project_write"] is False


def test_small_model_selects_one_verified_fan_out_plan(tmp_path: Path) -> None:
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    rows = _fan_out_rows(tmp_path)
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")
    modules = list_stage4_module_capsules(capsule_path=capsules)

    def select_actions(**kwargs: object) -> dict[str, object]:
        assert set(kwargs["actions"]) == {"calculateTotal", "applyDiscount", "addTax"}
        return {
            "ordered_actions": ["calculateTotal", "applyDiscount", "addTax"],
            "meta": {"applied": True, "status": "applied", "local_http_call": True},
        }

    def select_wiring(**kwargs: object) -> dict[str, object]:
        plans = kwargs["plans"]
        assert isinstance(plans, list)
        assert {row["topology"] for row in plans} == {"serial", "fan_out"}
        selected = next(row for row in plans if row["topology"] == "fan_out")
        return {
            "selected_plan_id": selected["id"],
            "meta": {
                "applied": True,
                "status": "applied",
                "local_http_call": True,
                "selected_plan_id": selected["id"],
                "selected_topology": "fan_out",
            },
        }

    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_modules", return_value=modules),
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch("pimos_lite.reweave_engine.lumo_lite.select_ollama_action_sequence", side_effect=select_actions),
        patch("pimos_lite.reweave_engine.lumo_lite.select_ollama_wiring_plan", side_effect=select_wiring),
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir", return_value=tmp_path / "previews"),
        patch("pimos_lite.reweave_engine.lumo_lite.append_preview_history_entry"),
    ):
        result = engine.generate_preview(
            {
                "taskText": "Calculate the total, then apply discount and add tax independently",
                "selectionMode": "auto_behavior",
                "localModel": {
                    "enabled": True,
                    "provider": "ollama",
                    "model": "qwen2.5:7b",
                    "capsuleRanking": True,
                    "require": True,
                },
            }
        )

    assert result["ok"] is True
    assert result["taskPack"]["capability_graph_plan"]["topology"] == "fan_out"
    assert result["taskPack"]["composition_plan"]["composition_topology"] == "fan_out"
    assert result["taskPack"]["model_selection"]["wiring_plan"]["selected_topology"] == "fan_out"
    assert result["source_project_write"] is False


def test_small_model_selects_plan_when_logic_actions_share_a_name(tmp_path: Path) -> None:
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    rows = _duplicate_action_rows(tmp_path)
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")
    modules = list_stage4_module_capsules(capsule_path=capsules)

    def select_wiring(**kwargs: object) -> dict[str, object]:
        selected = next(row for row in kwargs["plans"] if row["topology"] == "fan_out")
        return {
            "selected_plan_id": selected["id"],
            "meta": {
                "applied": True,
                "status": "applied",
                "fallback_used": False,
                "local_http_call": True,
                "selected_plan_id": selected["id"],
                "selected_topology": "fan_out",
            },
        }

    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_modules", return_value=modules),
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch("pimos_lite.reweave_engine.lumo_lite.select_ollama_action_sequence") as action_sequence,
        patch("pimos_lite.reweave_engine.lumo_lite.select_ollama_wiring_plan", side_effect=select_wiring),
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir", return_value=tmp_path / "previews"),
        patch("pimos_lite.reweave_engine.lumo_lite.append_preview_history_entry"),
    ):
        result = engine.generate_preview(
            {
                "taskText": "Calculate the total and adjust it independently in two ways",
                "selectionMode": "auto_behavior",
                "localModel": {"enabled": True, "capsuleRanking": True, "require": True},
            }
        )

    action_sequence.assert_not_called()
    assert result["ok"] is True
    assert result["taskPack"]["composition_plan"]["composition_topology"] == "fan_out"
    assert result["taskPack"]["model_selection"]["applied"] is True


def test_small_model_selects_and_executes_verified_fan_in_plan(tmp_path: Path) -> None:
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    rows = _fan_in_rows(tmp_path)
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")
    modules = list_stage4_module_capsules(capsule_path=capsules)
    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_modules", return_value=modules),
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch(
            "pimos_lite.reweave_engine.lumo_lite.select_ollama_action_sequence",
            return_value={
                "ordered_actions": ["calculateTotal", "applyDiscount", "addTax", "combinePayable"],
                "meta": {"applied": True, "status": "applied", "local_http_call": True},
            },
        ),
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir", return_value=tmp_path / "previews"),
        patch("pimos_lite.reweave_engine.lumo_lite.append_preview_history_entry"),
    ):
        result = engine.generate_preview(
            {
                "taskText": "Calculate total, run discount and tax independently, then combine both results",
                "selectionMode": "auto_behavior",
                "localModel": {
                    "enabled": True,
                    "provider": "ollama",
                    "model": "qwen2.5:7b",
                    "capsuleRanking": True,
                    "require": True,
                },
            }
        )

    assert result["ok"] is True
    assert result["taskPack"]["capability_graph_plan"]["topology"] == "fan_in"
    assert result["taskPack"]["composition_plan"]["composition_topology"] == "fan_in"
    assert result["taskPack"]["model_selection"]["applied"] is True
    assert result["source_project_write"] is False


def test_required_small_model_wiring_failure_has_no_fallback(tmp_path: Path) -> None:
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    rows = _fan_out_rows(tmp_path)
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")
    modules = list_stage4_module_capsules(capsule_path=capsules)
    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_modules", return_value=modules),
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch(
            "pimos_lite.reweave_engine.lumo_lite.select_ollama_action_sequence",
            return_value={
                "ordered_actions": ["calculateTotal", "applyDiscount", "addTax"],
                "meta": {"applied": True, "status": "applied", "local_http_call": True},
            },
        ),
        patch(
            "pimos_lite.reweave_engine.lumo_lite.select_ollama_wiring_plan",
            return_value={
                "selected_plan_id": "",
                "meta": {"applied": False, "status": "failed", "local_http_call": True},
            },
        ),
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir") as previews,
    ):
        result = engine.generate_preview(
            {
                "taskText": "Calculate total, then discount and tax independently",
                "selectionMode": "auto_behavior",
                "localModel": {
                    "enabled": True,
                    "provider": "ollama",
                    "model": "qwen2.5:7b",
                    "capsuleRanking": True,
                    "require": True,
                },
            }
        )

    assert result["ok"] is False
    assert result["error"] == "stage4_model_wiring_plan_not_applied"
    assert result["model_selection"]["applied"] is False
    previews.assert_not_called()


def test_optional_small_model_invalid_plan_falls_back_to_deterministic_topology(tmp_path: Path) -> None:
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    rows = _fan_out_rows(tmp_path)
    for row, semantic_key in zip(rows[2:], ("discount_result", "tax_result")):
        row["ports"]["outputs"][0]["semantic_key"] = semantic_key
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")
    modules = list_stage4_module_capsules(capsule_path=capsules)
    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_modules", return_value=modules),
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch(
            "pimos_lite.reweave_engine.lumo_lite.select_ollama_action_sequence",
            return_value={
                "ordered_actions": ["applyDiscount", "calculateTotal"],
                "meta": {"applied": True, "status": "applied", "local_http_call": True},
            },
        ),
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir", return_value=tmp_path / "previews"),
        patch("pimos_lite.reweave_engine.lumo_lite.append_preview_history_entry"),
    ):
        result = engine.generate_preview(
            {
                "taskText": "Calculate total with discount and tax",
                "selectionMode": "auto_behavior",
                "localModel": {"enabled": True, "capsuleRanking": True, "require": False},
            }
        )

    assert result["ok"] is True
    assert result["taskPack"]["selection_mode"] == "auto_behavior"
    assert result["taskPack"]["composition_plan"]["composition_topology"] == "fan_out"
    assert result["taskPack"]["model_selection"]["applied"] is False
    assert result["taskPack"]["model_selection"]["fallback_used"] is True
    assert result["taskPack"]["model_selection"]["error"] == "stage4_model_action_sequence_not_unique"


def test_small_model_action_sequence_must_match_one_legal_plan(tmp_path: Path) -> None:
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    rows = _five_module_rows(tmp_path)
    for row in rows:
        (capsules / f"{row['module_capsule_id']}.json").write_text(json.dumps(row), encoding="utf-8")
    modules = list_stage4_module_capsules(capsule_path=capsules)

    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_modules", return_value=modules),
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch(
            "pimos_lite.reweave_engine.lumo_lite.select_ollama_action_sequence",
            return_value={
                "ordered_actions": ["recordResultHistory", "calculateTotal"],
                "meta": {"applied": True, "status": "applied", "local_http_call": True},
            },
        ),
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir") as previews,
    ):
        result = engine.generate_preview(
            {
                "taskText": "Build an invalid order",
                "selectionMode": "auto_behavior",
                "localModel": {"enabled": True, "capsuleRanking": True, "require": True},
            }
        )

    assert result["ok"] is False
    assert result["error"] == "stage4_model_action_sequence_not_unique"
    previews.assert_not_called()


def test_small_model_cannot_invent_capability_graph_plan(tmp_path: Path) -> None:
    modules = [{"id": "module-ui", "name": "UI", "tags": ["form"], "status": "active"}]
    graph = {
        "model_candidates": [
            {
                "id": "cap-plan-allowed",
                "moduleIds": ["module-ui"],
                "currentlyExecutable": True,
            }
        ],
        "plans": [],
    }
    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_modules", return_value=modules),
        patch.object(engine, "_local_stage4_capsules", return_value=tmp_path / "capsules"),
        patch("pimos_lite.reweave_engine.lumo_lite.plan_with_stage4", return_value=graph),
        patch(
            "pimos_lite.reweave_engine.lumo_lite.apply_ollama_planning",
            return_value={
                "ordered_capsule_ids": ["cap-plan-invented"],
                "meta": {"applied": True, "local_http_call": True},
            },
        ),
    ):
        result = engine.generate_preview(
            {
                "taskText": "Build a tool",
                "selectionMode": "auto_behavior",
                "localModel": {"enabled": True, "capsuleRanking": True, "require": True},
            }
        )

    assert result == {"ok": False, "error": "stage4_model_selected_unknown_plan", "source_project_write": False}


def test_required_small_model_plan_ranking_does_not_accept_no_change(tmp_path: Path) -> None:
    modules = [{"id": "module-ui", "name": "UI", "tags": ["form"], "status": "active"}]
    graph = {
        "model_candidates": [{"id": "cap-plan-allowed", "moduleIds": ["module-ui"], "currentlyExecutable": True}],
        "plans": [],
    }
    meta = {"applied": False, "status": "skipped", "local_http_call": True, "error": "planning_patch_no_change"}
    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_modules", return_value=modules),
        patch.object(engine, "_local_stage4_capsules", return_value=tmp_path / "capsules"),
        patch("pimos_lite.reweave_engine.lumo_lite.plan_with_stage4", return_value=graph),
        patch(
            "pimos_lite.reweave_engine.lumo_lite.apply_ollama_planning",
            return_value={"ordered_capsule_ids": [], "meta": meta},
        ),
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir") as previews,
    ):
        result = engine.generate_preview(
            {
                "taskText": "Build a tool",
                "selectionMode": "auto_behavior",
                "localModel": {"enabled": True, "capsuleRanking": True, "require": True},
            }
        )

    assert result["ok"] is False
    assert result["error"] == "stage4_llm_plan_ranking_required_but_not_applied"
    assert result["model_selection"] == meta
    previews.assert_not_called()


def test_capability_graph_planner_rejects_symlinked_module_file(tmp_path: Path) -> None:
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (capsules / "linked.json").symlink_to(outside)

    with pytest.raises(ValueError, match="module_capsule_path_not_regular_file"):
        plan_with_stage4(goal="Build a tool", capsule_path=capsules)


def test_stage4_success_requires_complete_file_provenance(tmp_path: Path) -> None:
    _root, capsules = _stage4_layout(tmp_path)
    modules = [
        {"id": "module-ui", "name": "Form UI", "tags": ["form"], "status": "active", "origin": COMPOSER_OWNER},
        {"id": "module-logic", "name": "Logic", "tags": ["logic"], "status": "active", "origin": COMPOSER_OWNER},
    ]
    composed = {
        "status": "composed",
        "composer_owner": COMPOSER_OWNER,
        "selected_module_capsule_ids": ["module-ui", "module-logic"],
        "files": {"index.html": "", "styles.css": "", "app.js": ""},
        "composition_plan": {"file_provenance": {}},
    }

    def compose_result(**kwargs: object) -> dict[str, object]:
        _write_stage4_product(Path(str(kwargs["preview_root"])))
        return composed

    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch("pimos_lite.reweave_engine.lumo_lite.list_stage4_module_capsules", return_value=modules),
        patch("pimos_lite.reweave_engine.lumo_lite.compose_with_stage4", side_effect=compose_result),
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir", return_value=tmp_path / "previews"),
        patch("pimos_lite.reweave_engine.lumo_lite.append_preview_history_entry") as history,
    ):
        result = engine.generate_preview(
            {"taskText": "Build a form", "capsuleIds": ["module-ui", "module-logic"]}
        )

    assert result == {
        "ok": False,
        "error": "stage4_file_provenance_incomplete",
        "source_project_write": False,
    }
    history.assert_not_called()


def test_stage4_success_requires_real_product_files(tmp_path: Path) -> None:
    _cli, capsules = _stage4_layout(tmp_path)
    modules = [{"id": "module-ui", "name": "Form UI", "tags": ["form"], "status": "active", "origin": COMPOSER_OWNER}]
    composed = {
        "status": "composed",
        "composer_owner": COMPOSER_OWNER,
        "selected_module_capsule_ids": ["module-ui"],
        "files": {"index.html": "", "styles.css": "", "app.js": ""},
        "composition_plan": {"file_provenance": _file_provenance("module-ui")},
    }
    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch("pimos_lite.reweave_engine.lumo_lite.list_stage4_module_capsules", return_value=modules),
        patch("pimos_lite.reweave_engine.lumo_lite.compose_with_stage4", return_value=composed),
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir", return_value=tmp_path / "previews"),
        patch("pimos_lite.reweave_engine.lumo_lite.append_preview_history_entry") as history,
    ):
        result = engine.generate_preview({"taskText": "Build a form", "capsuleIds": ["module-ui"]})

    assert result == {
        "ok": False,
        "error": "stage4_required_output_missing_or_unsafe",
        "file": "index.html",
        "source_project_write": False,
    }
    history.assert_not_called()


def test_stage4_success_rejects_symlink_product_file(tmp_path: Path) -> None:
    _cli, capsules = _stage4_layout(tmp_path)
    modules = [{"id": "module-ui", "name": "Form UI", "tags": ["form"], "status": "active", "origin": COMPOSER_OWNER}]
    composed = {
        "status": "composed",
        "composer_owner": COMPOSER_OWNER,
        "selected_module_capsule_ids": ["module-ui"],
        "files": {"index.html": "", "styles.css": "", "app.js": ""},
        "composition_plan": {"file_provenance": _file_provenance("module-ui")},
    }
    outside = tmp_path / "outside.html"
    outside.write_text("outside", encoding="utf-8")

    def compose_result(**kwargs: object) -> dict[str, object]:
        root = Path(str(kwargs["preview_root"]))
        (root / "index.html").symlink_to(outside)
        (root / "styles.css").write_text("body {}", encoding="utf-8")
        (root / "app.js").write_text("console.log('ready');", encoding="utf-8")
        return composed

    engine = LumoLiteReweaveEngine()
    with (
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch("pimos_lite.reweave_engine.lumo_lite.list_stage4_module_capsules", return_value=modules),
        patch("pimos_lite.reweave_engine.lumo_lite.compose_with_stage4", side_effect=compose_result),
        patch("pimos_lite.reweave_engine.lumo_lite.preview_packages_dir", return_value=tmp_path / "previews"),
        patch("pimos_lite.reweave_engine.lumo_lite.append_preview_history_entry"),
    ):
        result = engine.generate_preview({"taskText": "Build a form", "capsuleIds": ["module-ui"]})

    assert result["ok"] is False
    assert result["error"] == "stage4_required_output_missing_or_unsafe"
    assert outside.read_text(encoding="utf-8") == "outside"


def test_stage4_preview_is_recoverable_from_normal_history(tmp_path: Path) -> None:
    _cli, capsules = _stage4_layout(tmp_path)
    modules = [
        {"id": "module-ui", "name": "Form UI", "tags": ["form"], "status": "active", "origin": COMPOSER_OWNER},
        {"id": "module-logic", "name": "Logic", "tags": ["logic"], "status": "active", "origin": COMPOSER_OWNER},
    ]
    composed = {
        "status": "composed",
        "composer_owner": COMPOSER_OWNER,
        "composition_strategy": "behavior_adapter",
        "selected_module_capsule_ids": ["module-ui", "module-logic"],
        "files": {"index.html": "", "styles.css": "", "app.js": ""},
        "composition_plan": {"file_provenance": _file_provenance("module-ui", "module-logic")},
    }

    def compose_result(**kwargs: object) -> dict[str, object]:
        _write_stage4_product(Path(str(kwargs["preview_root"])))
        return composed

    state = tmp_path / "state"
    engine = LumoLiteReweaveEngine()
    with (
        patch.dict("os.environ", {"REWEAVE_STATE_DIR": str(state)}),
        patch.object(engine, "_local_stage4_capsules", return_value=capsules),
        patch("pimos_lite.reweave_engine.lumo_lite.list_stage4_module_capsules", return_value=modules),
        patch("pimos_lite.reweave_engine.lumo_lite.compose_with_stage4", side_effect=compose_result),
    ):
        generated = engine.generate_preview({"taskText": "Build a form", "capsuleIds": ["module-ui", "module-logic"]})
        recovered = get_latest_preview_package()

    assert generated["ok"] is True
    assert recovered["ok"] is True
    assert {"task_pack.json", "capsules_used.json", "provenance.json", "quality_gate.json"} <= set(recovered["package"]["files"])


def test_public_stage4_source_boxes_compose_with_builtin_runtime(tmp_path: Path) -> None:
    from scripts.run_public_stage4_demo import run

    result = run(tmp_path / "reweave_stage4_integration")

    assert result == {
        "ok": False,
        "error": {
            "code": "legacy_stage4_demo_inactive",
            "message_key": "legacy_stage4_demo_inactive",
        },
    }


def test_public_stage4_workflow_source_boxes_compose_with_builtin_runtime(tmp_path: Path) -> None:
    from scripts.run_public_stage4_demo import run

    result = run(tmp_path / "reweave_stage4_workflow_integration", case="workflow")

    assert result["ok"] is False
    assert result["error"]["code"] == "legacy_stage4_demo_inactive"


def test_public_stage4_data_source_boxes_compose_with_builtin_runtime(tmp_path: Path) -> None:
    from scripts.run_public_stage4_demo import run

    result = run(tmp_path / "reweave_stage4_data_integration", case="data")

    assert result["ok"] is False
    assert result["error"]["code"] == "legacy_stage4_demo_inactive"


def test_stage4_structured_data_composition_requires_data_and_matching_fields(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    capsules = tmp_path / "capsules"
    capsules.mkdir()
    for role, source in (
        ("ui", root / "examples/source_boxes/order-data-view-ui"),
        ("logic", root / "examples/source_boxes/regional-total-logic"),
    ):
        module = extract_with_stage4(source_root=source, role=role, source_id=f"source-{role}")
        (capsules / f"{role}.json").write_text(json.dumps(module), encoding="utf-8")

    missing_data = compose_with_stage4(
        goal="Build a regional order data viewer with filtered totals",
        capsule_path=capsules,
        max_modules=3,
        auto_behavior=True,
    )

    bad_data = tmp_path / "bad-data"
    bad_data.mkdir()
    (bad_data / "data.json").write_text(
        '[{"order":"A-101","zone":"north","amount":120}]',
        encoding="utf-8",
    )
    module = extract_with_stage4(source_root=bad_data, role="data", source_id="source-data")
    (capsules / "data.json").write_text(json.dumps(module), encoding="utf-8")
    incompatible = compose_with_stage4(
        goal="Build a regional order data viewer with filtered totals",
        capsule_path=capsules,
        max_modules=3,
        auto_behavior=True,
    )

    assert missing_data["status"] == "composition_rejected"
    assert incompatible["status"] == "composition_rejected"


def test_desktop_bridge_runs_structured_data_composition_flow(tmp_path: Path) -> None:
    from pimos_lite import desktop_reweave_static as desktop

    class QObject:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

    def Slot(*_args: object, **_kwargs: object):
        return lambda fn: fn

    class QFileDialog:
        @staticmethod
        def getExistingDirectory(*_args: object, **_kwargs: object) -> str:
            return ""

    state = tmp_path / "state"
    service = ReweaveAppService(engine=LumoLiteReweaveEngine())
    with (
        patch.dict("os.environ", {"REWEAVE_STATE_DIR": str(state)}),
        patch.object(desktop, "import_qt_bridge", return_value=(QObject, Slot, object)),
        patch.object(desktop, "import_qt_webengine", return_value=(object, object, object, object, object, QFileDialog)),
    ):
        desktop.ReweaveBridge._qobject_cls = None
        try:
            bridge = desktop.ReweaveBridge.create(service)
            generated = json.loads(
                bridge.notify_generate(
                    json.dumps({"taskText": "legacy", "selectionMode": "auto_behavior"})
                )
            )
        finally:
            desktop.ReweaveBridge._qobject_cls = None

    assert generated["ok"] is False
    assert generated["error"]["code"] == "product_task_invalid"
