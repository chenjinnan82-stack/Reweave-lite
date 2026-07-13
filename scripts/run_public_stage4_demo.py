#!/usr/bin/env python3
"""Compose public behavior capsules with the built-in Stage4 runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_public_reweave_demo import _import_reweave, _prepare_out, _public_files, _safe_out, _temporary_state_dir
from pimos_lite.reweave_preview_pack import load_preview_history


SOURCES = (
    ROOT / "examples/source_boxes/order-form-ui",
    ROOT / "examples/source_boxes/order-total-logic",
    ROOT / "examples/source_boxes/result-history-state",
)
WORKFLOW_SOURCES = (
    ROOT / "examples/source_boxes/approval-workflow-ui",
    ROOT / "examples/source_boxes/approval-state-logic",
)
DATA_SOURCES = (
    ROOT / "examples/source_boxes/order-data-view-ui",
    ROOT / "examples/source_boxes/order-records-data",
    ROOT / "examples/source_boxes/regional-total-logic",
)
DEFAULT_OUT = Path(tempfile.gettempdir()) / "reweave_stage4_demo"
DEFAULT_TASK = "Build an order estimate with result history"
WORKFLOW_TASK = "Build an approval form that toggles workflow status"
DATA_TASK = "Build a regional order data viewer with filtered totals"


def _digest_sources(sources: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for source in sources:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                digest.update(source.name.encode())
                digest.update(path.relative_to(source).as_posix().encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def _validate_interaction(script: Path, case: str) -> dict[str, str]:
    node = shutil.which("node")
    if not node:
        raise SystemExit("node is required for the Stage4 interaction check")
    harness = """
const fs = require('fs');
const vm = require('vm');
const events = {};
const elements = {
  '#price': {value: '12'}, '#quantity': {value: '8'},
  '#estimate': {addEventListener: (name, fn) => { events[name] = fn; }},
  '#total': {textContent: '0'}, '#reweave-state-result': {textContent: '0'}
};
global.document = {
  addEventListener: (name, fn) => { events[name] = fn; },
  querySelector: (selector) => elements[selector]
};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
events.DOMContentLoaded();
events.click();
if (elements['#total'].textContent !== '96') throw new Error('expected total 96');
if (elements['#reweave-state-result'].textContent !== '1') throw new Error('expected history 1');
process.stdout.write(JSON.stringify({total: elements['#total'].textContent, history: elements['#reweave-state-result'].textContent}));
"""
    if case == "workflow":
        harness = """
const fs = require('fs');
const vm = require('vm');
const events = {};
const elements = {
  '#approval-status': {value: 'draft'},
  '#toggle-approval': {addEventListener: (name, fn) => { events[name] = fn; }},
  '#next-status': {textContent: 'draft'}
};
global.document = {
  addEventListener: (name, fn) => { events[name] = fn; },
  querySelector: (selector) => elements[selector]
};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
events.DOMContentLoaded();
events.click();
if (elements['#next-status'].textContent !== 'approved') throw new Error('expected approved status');
process.stdout.write(JSON.stringify({status: elements['#next-status'].textContent}));
"""
    elif case == "data":
        harness = """
const fs = require('fs');
const vm = require('vm');
const events = {};
const renderedRows = [];
const elements = {
  '#region': {value: 'North'},
  '#filter-orders': {addEventListener: (name, fn) => { events[name] = fn; }},
  '#region-total': {textContent: '0'},
  '#orders-body': {replaceChildren: () => { renderedRows.length = 0; }, appendChild: (row) => renderedRows.push(row)}
};
global.document = {
  addEventListener: (name, fn) => { events[name] = fn; },
  querySelector: (selector) => elements[selector],
  createElement: (tag) => ({tag, children: [], textContent: '', appendChild(child) { this.children.push(child); }})
};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
events.DOMContentLoaded();
events.click();
if (elements['#region-total'].textContent !== '420') throw new Error('expected regional total 420');
const northTotal = elements['#region-total'].textContent;
elements['#region'].value = 'South';
events.click();
if (elements['#region-total'].textContent !== '80') throw new Error('expected regional total 80');
if (renderedRows.length !== 3) throw new Error('expected three rendered rows');
process.stdout.write(JSON.stringify({northTotal, southTotal: elements['#region-total'].textContent, rows: String(renderedRows.length)}));
"""
    completed = subprocess.run([node, "-e", harness, str(script)], capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or "Stage4 interaction check failed")
    return json.loads(completed.stdout)


def run(out: Path, *, task: str = "", case: str = "estimate") -> dict[str, object]:
    cases = {
        "estimate": (SOURCES, DEFAULT_TASK),
        "workflow": (WORKFLOW_SOURCES, WORKFLOW_TASK),
        "data": (DATA_SOURCES, DATA_TASK),
    }
    if case not in cases:
        raise ValueError(f"unknown Stage4 demo case: {case}")
    sources, default_task = cases[case]
    task = task or default_task
    resolved_out = out
    for source in sources:
        resolved_out = _safe_out(resolved_out, source)
    before = _digest_sources(sources)
    engine_type = _import_reweave()

    with tempfile.TemporaryDirectory(prefix="reweave-public-stage4-state-") as state, _temporary_state_dir(state):
        engine = engine_type()
        for source in sources:
            box = engine.bind_source_folder(str(source))
            engine.scan_source(str(box["id"]))
            engine.draft_source(str(box["id"]))
            engine.promote_source(str(box["id"]))
        preview = engine.generate_preview({"taskText": task, "selectionMode": "auto_behavior"})
        if preview.get("ok") is not True:
            raise SystemExit(str(preview.get("error") or "stage4 composition failed"))
        preview_root = Path(str(preview["previewPath"]))
        _prepare_out(resolved_out)
        for path in preview_root.iterdir():
            if path.is_symlink() or not path.is_file():
                raise SystemExit(f"unsafe Stage4 output: {path.name}")
            shutil.copy2(path, resolved_out / path.name)
        preview_history_count = len(load_preview_history().get("packages", []))

    if preview_history_count != 1:
        raise SystemExit(f"expected one preview history entry, got {preview_history_count}")

    required = {
        "index.html",
        "styles.css",
        "app.js",
        "composition_plan.json",
        "adapter_mapping.json",
        "task_pack.json",
        "capsules_used.json",
        "provenance.json",
        "quality_gate.json",
    }
    missing = sorted(required - set(_public_files(resolved_out)))
    if missing:
        raise SystemExit(f"missing Stage4 output files: {missing}")
    if _digest_sources(sources) != before:
        raise SystemExit("Source Box changed during composition")
    provenance = json.loads((resolved_out / "provenance.json").read_text(encoding="utf-8"))
    interaction = _validate_interaction(resolved_out / "app.js", case)
    runtime_validation = {
        "status": "passed",
        "inputs": (
            {"current_status": "draft"}
            if case == "workflow"
            else {"regions": ["North", "South"]}
            if case == "data"
            else {"price": 12, "quantity": 8}
        ),
        "outputs": interaction,
        "preview_history_count": preview_history_count,
        "source_project_write": False,
    }
    (resolved_out / "runtime_validation.json").write_text(
        json.dumps(runtime_validation, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    quality_gate = json.loads((resolved_out / "quality_gate.json").read_text(encoding="utf-8"))
    quality_gate["runtime_validation"] = "passed"
    quality_gate.setdefault("checks", []).append({"name": "stage4_runtime_interaction", "passed": True})
    (resolved_out / "quality_gate.json").write_text(
        json.dumps(quality_gate, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    task_pack = json.loads((resolved_out / "task_pack.json").read_text(encoding="utf-8"))
    task_pack["runtime_validation_path"] = "runtime_validation.json"
    task_pack.setdefault("behavior_reuse", {})["runtime_validation"] = "passed"
    task_pack["quality_gate"] = quality_gate
    (resolved_out / "task_pack.json").write_text(
        json.dumps(task_pack, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "out": str(resolved_out),
        "case": case,
        "task": task,
        "source_boxes": [source.name for source in sources],
        "selected_module_capsule_ids": provenance.get("selected_module_capsule_ids", []),
        "files": _public_files(resolved_out),
        "interaction": interaction,
        "preview_history_count": preview_history_count,
        "source_project_write": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--task", default="")
    parser.add_argument("--case", choices=("estimate", "workflow", "data"), default="estimate")
    args = parser.parse_args()
    print(
        json.dumps(
            run(Path(args.out), task=args.task, case=args.case),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
