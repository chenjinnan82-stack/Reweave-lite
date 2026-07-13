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


def _safe_out(path: Path, source: Path) -> Path:
    resolved = path.expanduser().resolve()
    source = source.expanduser().resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise SystemExit("refusing to write demo output inside the repository")
    if resolved == Path.home().resolve():
        raise SystemExit("refusing to use home directory as demo output")
    if resolved.parent == resolved:
        raise SystemExit("refusing to use filesystem root as demo output")
    if not resolved.name.startswith(("reweave_", ".reweave_", "demo_")):
        raise SystemExit("demo output directory name must start with reweave_, .reweave_, or demo_")
    if resolved == source or source in resolved.parents or resolved in source.parents:
        raise SystemExit("refusing output path that overlaps the Source Box")
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
    llm_intent_patch: bool = False,
    llm_capsule_ranking: bool = False,
    validate_runtime: bool = False,
) -> dict[str, object]:
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise SystemExit(f"source folder not found: {source}")
    out = _safe_out(out, source)

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
        if (llm_intent_patch or llm_capsule_ranking) and llm != "ollama":
            raise SystemExit("planning patches require --llm ollama")
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
                    "intentPatch": llm_intent_patch,
                    "capsuleRanking": llm_capsule_ranking,
                },
            }
        )
        if preview.get("ok") is False:
            raise SystemExit(str(preview.get("error") or "preview generation failed"))
        preview_path = Path(str(preview.get("previewPath") or ""))
        if preview_path.is_dir():
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
        public_receipt = {
            "schema_version": "reweave_public_demo_receipt.v1",
            "project_type": task_pack.get("package_kind", "small_project_pack"),
            "source_box": source_box,
            "selected_capsules": public_capsules,
            "selection_mode": "manual" if select_capsules else "task_retrieval",
            "output_files": _public_files(out),
            "product_entry": task_pack.get("product_entry") or {"path": "index.html", "kind": "static_html"},
            "source_project_write": False,
        }
        _write_json(out / "public_demo_receipt.json", public_receipt)
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
            "public_demo_receipt": public_receipt,
            "product_entry": task_pack.get("product_entry") or {"path": "index.html", "kind": "static_html"},
            "behavior_reuse": task_pack.get("behavior_reuse"),
            "runtime_validation": preview.get("runtimeValidation"),
            "preview_acceptance": preview.get("previewAcceptance"),
            "llm": llm_result,
            "source_project_write": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source")
    parser.add_argument("--task")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--list-capsules", action="store_true", help="List capsule choices for a Source Box and exit without writing an output pack.")
    parser.add_argument("--select-capsule", action="append", default=[], help="Select a capsule by id, exact name, or text match. Repeat up to four times.")
    parser.add_argument("--include-local-paths", action="store_true", help="Include local source paths in stdout and task_pack.json; provenance stays redacted.")
    parser.add_argument("--llm", choices=("none", "ollama"), default="none", help="Optional local model pass. Default: none.")
    parser.add_argument("--model", default="qwen2.5-coder:1.5b", help="Ollama model name when --llm ollama is used.")
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"), help="Ollama base URL.")
    parser.add_argument("--llm-timeout", type=float, default=60.0, help="Ollama request timeout in seconds.")
    parser.add_argument("--require-llm", action="store_true", help="Fail instead of falling back when local model generation fails.")
    parser.add_argument("--llm-intent-patch", action="store_true", help="Experimental opt-in to bounded task intent refinement.")
    parser.add_argument("--llm-capsule-ranking", action="store_true", help="Experimental opt-in to ranking only the selected capsules.")
    parser.add_argument("--validate-runtime", action="store_true", help="Run the optional local desktop behavior check and write its receipt.")
    args = parser.parse_args()

    source = args.source or DEFAULT_SOURCE
    task = args.task or DEFAULT_TASK

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
        llm_intent_patch=args.llm_intent_patch,
        llm_capsule_ranking=args.llm_capsule_ranking,
        validate_runtime=args.validate_runtime,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
