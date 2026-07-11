#!/usr/bin/env python3
"""Run a public Reweave-lite Source Box -> Task Pack demo."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pimos_lite.reweave_task_intent import capsule_match_text as shared_capsule_match_text

MARKER = ".reweave_public_demo"
DEFAULT_OUT = Path(tempfile.gettempdir()) / "reweave_public_demo"
DEFAULT_SOURCE = "examples/source_boxes/customer-quote-widget"
DEFAULT_TASK = "Build a quote summary card"
LEGACY_SHORTCUT_WARNING = "legacy demo shortcut; prefer --source + --task for the product path"
TEMPLATE_CASES: dict[str, dict[str, str]] = {
    "dashboard": {
        "kind": "dashboard",
        "source": "examples/source_boxes/ops-status-card",
        "task": "Build an operations dashboard",
        "purpose": "status cards, metric copy, and review checklist",
    },
    "landing-page": {
        "kind": "landing_page",
        "source": "examples/source_boxes/artist-landing",
        "task": "Build an artist landing page",
        "purpose": "artist hero, selected works, and studio call to action",
    },
    "form-tool": {
        "kind": "form_tool",
        "source": "examples/source_boxes/customer-quote-widget",
        "task": "Build a customer quote form tool",
        "purpose": "form shell, quote summary, and pricing interaction",
    },
    "admin-panel": {
        "kind": "admin_panel",
        "source": "examples/source_boxes/support-ticket-triage",
        "task": "Build a support triage admin panel",
        "purpose": "queue layout, priority tags, and triage action",
    },
    "data-viewer": {
        "kind": "data_viewer",
        "source": "examples/source_boxes/content-calendar",
        "task": "Build a content calendar data viewer",
        "purpose": "calendar cards, publishing status, and readable data rows",
    },
}
TASK_TEMPLATES: dict[str, dict[str, str]] = {
    "portfolio-viewer": {
        "kind": "portfolio_viewer",
        "task": "Build a portfolio project viewer",
        "purpose": "turn an old personal or portfolio site into a browsable project viewer",
    },
    "operations-panel": {
        "kind": "operations_panel",
        "task": "Build an operations panel",
        "purpose": "reuse an old business tool or workflow demo as a compact operations panel",
    },
    "artist-landing": {
        "kind": "artist_landing",
        "task": "Build an artist landing page",
        "purpose": "reuse an old artwork, event, or creator page as a focused landing page",
    },
}


def _import_reweave() -> type[object]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from pimos_lite.reweave_engine.lumo_lite import LumoLiteReweaveEngine

    return LumoLiteReweaveEngine


@contextmanager
def _temporary_state_dir(path: str) -> Iterator[None]:
    previous = os.environ.get("REWEAVE_STATE_DIR")
    os.environ["REWEAVE_STATE_DIR"] = path
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("REWEAVE_STATE_DIR", None)
        else:
            os.environ["REWEAVE_STATE_DIR"] = previous


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _safe_out(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise SystemExit("refusing to write demo output inside the repository")
    if resolved == Path.home().resolve():
        raise SystemExit("refusing to use home directory as demo output")
    if resolved.parent == resolved:
        raise SystemExit("refusing to use filesystem root as demo output")
    if not resolved.name.startswith(("reweave_", ".reweave_", "demo_")):
        raise SystemExit("demo output directory name must start with reweave_, .reweave_, or demo_")
    return resolved


def _source_box_public(box: dict[str, object], source: Path, *, include_local_paths: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": box["id"],
        "label": box["label"],
        "path_policy": "included" if include_local_paths else "redacted",
    }
    if include_local_paths:
        payload["path"] = str(source)
    return payload


def _prepare_out(out: Path) -> None:
    marker = out / MARKER
    if out.exists():
        if not marker.is_file():
            raise SystemExit(f"refusing to overwrite non-demo output directory: {out}")
        shutil.rmtree(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir()
    marker.write_text("reweave public demo output\n", encoding="utf-8")


def _public_files(out: Path) -> list[str]:
    return sorted(p.name for p in out.iterdir() if p.is_file() and p.name != MARKER)


def _capsule_match_text(cap: dict[str, object]) -> str:
    return shared_capsule_match_text(cap)


def _public_capsule(cap: dict[str, object], *, reason: str | None = None) -> dict[str, object]:
    payload = {
        "id": cap.get("id"),
        "name": cap.get("name"),
        "type": cap.get("type"),
        "role": cap.get("role"),
        "tags": list(cap.get("tags") or []),
        "source_id": cap.get("source_id"),
    }
    if reason:
        payload["reason"] = reason
    return payload


def _public_template_cases() -> list[dict[str, str]]:
    return [{"id": case_id, **payload} for case_id, payload in TEMPLATE_CASES.items()]


def _public_task_templates() -> list[dict[str, str]]:
    return [{"id": template_id, **payload} for template_id, payload in TASK_TEMPLATES.items()]


def _select_capsules(capsules: list[dict[str, object]], selectors: list[str]) -> list[dict[str, object]]:
    if not selectors:
        return capsules[:4]
    selected: list[dict[str, object]] = []
    for selector in selectors:
        needle = selector.strip().lower()
        match = next((cap for cap in capsules if str(cap.get("id") or "").lower() == needle), None)
        if match is None:
            match = next((cap for cap in capsules if str(cap.get("name") or "").lower() == needle), None)
        if match is None:
            match = next((cap for cap in capsules if needle and needle in _capsule_match_text(cap)), None)
        if match is None:
            raise SystemExit(f"capsule selector did not match: {selector}")
        if match not in selected:
            selected.append(match)
    return selected[:4]


def run(
    source: Path,
    task: str,
    out: Path,
    *,
    include_local_paths: bool = False,
    select_capsules: list[str] | None = None,
    list_capsules: bool = False,
    llm: str = "none",
    model: str = "qwen2.5-coder:1.5b",
    ollama_url: str = "http://127.0.0.1:11434",
    llm_timeout: float = 60,
    require_llm: bool = False,
    validate_runtime: bool = False,
    template_case: str | None = None,
    task_template: str | None = None,
) -> dict[str, object]:
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise SystemExit(f"source folder not found: {source}")
    out = _safe_out(out)

    engine_type = _import_reweave()

    with tempfile.TemporaryDirectory(prefix="reweave-public-demo-state-") as state, _temporary_state_dir(state):
        engine = engine_type()
        box = engine.bind_source_folder(str(source))
        if box.get("status") == "blocked":
            raise SystemExit(str(box.get("last_error") or "source box blocked"))
        scan = engine.scan_source(str(box["id"]))
        draft = engine.draft_source(str(box["id"]))
        capsules = engine.promote_source(str(box["id"]))
        if select_capsules:
            selected_capsules = _select_capsules(capsules, select_capsules)
            for capsule in selected_capsules:
                engine.enrich_capsule_content(str(capsule["id"]))
        else:
            selected_capsules = engine.select_capsules(task)
        capsule_ids = [str(cap["id"]) for cap in selected_capsules]
        if list_capsules:
            return {
                "ok": True,
                "source": _source_box_public(box, source, include_local_paths=include_local_paths),
                "files_scanned": scan.get("counts", {}).get("files_scanned", 0),
                "capsule_candidates": draft.get("candidate_count", 0),
                "capsules": [_public_capsule(cap) for cap in capsules],
                "source_project_write": False,
            }
        source_box = _source_box_public(box, source, include_local_paths=include_local_paths)
        if llm not in {"none", "ollama"}:
            raise SystemExit(f"unsupported llm: {llm}")
        preview = engine.generate_preview(
            {
                "taskText": task,
                "capsuleIds": capsule_ids,
                "capsules": selected_capsules,
                "sourceBoxes": [source_box],
                "useEnrichedContent": True,
                "selectionMode": "manual" if select_capsules else "task_retrieval",
                "validateRuntime": validate_runtime,
                "localModel": {
                    "enabled": llm == "ollama",
                    "provider": "ollama",
                    "model": model,
                    "baseUrl": ollama_url,
                    "timeout": llm_timeout,
                    "require": require_llm,
                },
            }
        )
        if preview.get("ok") is False:
            raise SystemExit(str(preview.get("error") or "preview generation failed"))

        preview_path = Path(str(preview["previewPath"]))
        _prepare_out(out)
        for item in preview_path.iterdir():
            target = out / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
        task_intent = _json(out / "task_intent.json") if (out / "task_intent.json").is_file() else {}
        task_plan = _json(out / "task_plan.json") if (out / "task_plan.json").is_file() else {}
        quality_gate = _json(out / "quality_gate.json") if (out / "quality_gate.json").is_file() else {}
        reasons = {
            str(item.get("id")): str(item.get("reason"))
            for item in (task_intent.get("retrieved_capsules") if isinstance(task_intent, dict) else []) or []
            if isinstance(item, dict) and item.get("id")
        }
        public_capsules = [
            _public_capsule(cap, reason=reasons.get(str(cap.get("id"))))
            for cap in selected_capsules
        ]

        task_pack = _json(out / "task_pack.json")
        if not isinstance(task_pack, dict):
            raise SystemExit("preview task_pack.json must contain an object")
        task_pack.update(
            {
                "project_type": task_pack.get("package_kind", "small_project_pack"),
                "source_box": source_box,
                "selected_capsules": public_capsules,
                "selection_mode": "manual" if select_capsules else "task_retrieval",
                "output_files": _public_files(out),
            }
        )
        if template_case:
            task_pack["template_case"] = {"id": template_case, **TEMPLATE_CASES[template_case]}
            task_pack["demo_shortcut"] = "template_case"
        if task_template:
            task_pack["task_template"] = {"id": task_template, **TASK_TEMPLATES[task_template]}
            task_pack["demo_shortcut"] = "task_template"
        if template_case or task_template:
            task_pack["warnings"] = [LEGACY_SHORTCUT_WARNING]
        _write_json(out / "task_pack.json", task_pack)
        llm_result = preview.get("localModel") if isinstance(preview.get("localModel"), dict) else {"enabled": False}

        summary = [
            "# Reweave public demo",
            "",
            f"- Source Box: `{source.name}`",
            f"- Task: {task}",
            f"- Files scanned: {scan.get('counts', {}).get('files_scanned', 0)}",
            f"- Capsule candidates: {draft.get('candidate_count', 0)}",
            f"- Capsules used: {len(capsule_ids)}",
            "- Source project writes: 0",
            f"- Local model: {llm_result.get('model', 'off') if llm_result.get('enabled') else 'off'}",
            f"- LLM applied: {bool(llm_result.get('applied'))}",
            "",
        ]
        (out / "summary.md").write_text("\n".join(summary), encoding="utf-8")

        return {
            "ok": True,
            "out": str(out),
            "source": source_box,
            "task": task,
            "files": _public_files(out),
            "capsules_used": len(_json(out / "capsules_used.json")),
            "selected_capsules": public_capsules,
            "task_intent": task_intent,
            "task_plan": task_plan,
            "quality_gate": quality_gate,
            "behavior_reuse": task_pack.get("behavior_reuse"),
            "runtime_validation": preview.get("runtimeValidation"),
            "preview_acceptance": preview.get("previewAcceptance"),
            "llm": llm_result,
            "source_project_write": False,
            "template_case": task_pack.get("template_case"),
            "task_template": task_pack.get("task_template"),
            "warnings": task_pack.get("warnings", []),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source")
    parser.add_argument("--task")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--list-capsules", action="store_true", help="List capsule choices for a Source Box and exit without writing an output pack.")
    parser.add_argument("--list-template-cases", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--template-case", choices=tuple(TEMPLATE_CASES), help=argparse.SUPPRESS)
    parser.add_argument("--list-task-templates", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--task-template", choices=tuple(TASK_TEMPLATES), help=argparse.SUPPRESS)
    parser.add_argument("--select-capsule", action="append", default=[], help="Select a capsule by id, exact name, or text match. Repeat up to four times.")
    parser.add_argument("--include-local-paths", action="store_true", help="Include local source paths in stdout and task_pack.json; provenance stays redacted.")
    parser.add_argument("--llm", choices=("none", "ollama"), default="none", help="Optional local model pass. Default: none.")
    parser.add_argument("--model", default="qwen2.5-coder:1.5b", help="Ollama model name when --llm ollama is used.")
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"), help="Ollama base URL.")
    parser.add_argument("--llm-timeout", type=float, default=60.0, help="Ollama request timeout in seconds.")
    parser.add_argument("--require-llm", action="store_true", help="Fail instead of falling back when local model generation fails.")
    parser.add_argument("--validate-runtime", action="store_true", help="Run the optional local desktop behavior check and write its receipt.")
    args = parser.parse_args()
    if args.list_template_cases:
        print(json.dumps({"ok": True, "template_cases": _public_template_cases(), "source_project_write": False, "warnings": [LEGACY_SHORTCUT_WARNING]}, indent=2, ensure_ascii=False))
        return
    if args.list_task_templates:
        print(json.dumps({"ok": True, "task_templates": _public_task_templates(), "source_project_write": False, "warnings": [LEGACY_SHORTCUT_WARNING]}, indent=2, ensure_ascii=False))
        return

    case = TEMPLATE_CASES.get(args.template_case or "") if args.template_case else None
    task_template = TASK_TEMPLATES.get(args.task_template or "") if args.task_template else None
    source = args.source or (case["source"] if case else DEFAULT_SOURCE)
    task = args.task or (task_template["task"] if task_template else case["task"] if case else DEFAULT_TASK)

    result = run(
        Path(source),
        task,
        Path(args.out),
        include_local_paths=args.include_local_paths,
        select_capsules=args.select_capsule,
        list_capsules=args.list_capsules,
        llm=args.llm,
        model=args.model,
        ollama_url=args.ollama_url,
        llm_timeout=args.llm_timeout,
        require_llm=args.require_llm,
        validate_runtime=args.validate_runtime,
        template_case=args.template_case,
        task_template=args.task_template,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
