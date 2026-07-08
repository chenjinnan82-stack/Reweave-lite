#!/usr/bin/env python3
"""Run a public Reweave-lite Source Box -> Task Pack demo."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = ".reweave_public_demo"
DEFAULT_OUT = Path(tempfile.gettempdir()) / "reweave_public_demo"


def _import_reweave() -> tuple[object, object, object, object, object, object, object]:
    import sys

    sys.path.insert(0, str(ROOT))
    from pimos_lite.reweave_capsule_draft import draft_capsules
    from pimos_lite.reweave_capsule_content import enrich_capsule_content
    from pimos_lite.reweave_llm_pack import apply_ollama_pack
    from pimos_lite.reweave_capsule_warehouse import promote_source_drafts
    from pimos_lite.reweave_preview_pack import build_preview_package
    from pimos_lite.reweave_source_registry import add_source_box
    from pimos_lite.reweave_source_scanner import scan_source_box

    return add_source_box, scan_source_box, draft_capsules, promote_source_drafts, build_preview_package, enrich_capsule_content, apply_ollama_pack


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
    parts = [
        cap.get("id"),
        cap.get("name"),
        cap.get("type"),
        cap.get("role"),
        " ".join(str(tag) for tag in (cap.get("tags") or []) if tag),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _public_capsule(cap: dict[str, object]) -> dict[str, object]:
    return {
        "id": cap.get("id"),
        "name": cap.get("name"),
        "type": cap.get("type"),
        "role": cap.get("role"),
        "tags": list(cap.get("tags") or []),
        "source_id": cap.get("source_id"),
    }


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
) -> dict[str, object]:
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise SystemExit(f"source folder not found: {source}")
    out = _safe_out(out)

    imported = _import_reweave()
    add_source_box, scan_source_box, draft_capsules, promote_source_drafts, build_preview_package, enrich_capsule_content, apply_ollama_pack = imported

    with tempfile.TemporaryDirectory(prefix="reweave-public-demo-state-") as state:
        os.environ["REWEAVE_STATE_DIR"] = state
        box = add_source_box(source)
        if box.get("status") == "blocked":
            raise SystemExit(str(box.get("last_error") or "source box blocked"))
        scan = scan_source_box(box["id"])
        draft = draft_capsules(box["id"])
        capsules = promote_source_drafts(box["id"])
        selected_capsules = _select_capsules(capsules, select_capsules or [])
        capsule_ids = [str(cap["id"]) for cap in selected_capsules]
        for cap_id in capsule_ids:
            enrich_capsule_content(cap_id)
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
        preview = build_preview_package(
            {
                "task": task,
                "capsuleIds": capsule_ids,
                "backend": "public_demo",
                "sourceBoxes": [source_box],
                "useEnrichedContent": True,
            }
        )

        preview_path = Path(str(preview["previewPath"]))
        _prepare_out(out)
        for item in preview_path.iterdir():
            target = out / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)

        task_pack = {
            "schema_version": "reweave_public_task_pack.v1",
            "project_type": "small_project_pack",
            "task": task,
            "source_box": source_box,
            "selected_capsule_ids": capsule_ids,
            "selected_capsules": [_public_capsule(cap) for cap in selected_capsules],
            "selection_mode": "manual" if select_capsules else "default_first_four",
            "output_files": _public_files(out),
            "source_project_write": False,
        }
        _write_json(out / "task_pack.json", task_pack)
        llm_result: dict[str, object] = {"enabled": False}
        if llm == "ollama":
            llm_result = apply_ollama_pack(
                out,
                task=task,
                selected_capsules=[_public_capsule(cap) for cap in selected_capsules],
                snippet_context=preview.get("snippetContext") if isinstance(preview, dict) else None,
                model=model,
                base_url=ollama_url,
                timeout=llm_timeout,
                require=require_llm,
            )
        elif llm != "none":
            raise SystemExit(f"unsupported llm: {llm}")

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
            "selected_capsules": [_public_capsule(cap) for cap in selected_capsules],
            "llm": llm_result,
            "source_project_write": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="examples/source_boxes/customer-quote-widget")
    parser.add_argument("--task", default="Build a quote summary card")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--list-capsules", action="store_true", help="List capsule choices for a Source Box and exit without writing an output pack.")
    parser.add_argument("--select-capsule", action="append", default=[], help="Select a capsule by id, exact name, or text match. Repeat up to four times.")
    parser.add_argument("--include-local-paths", action="store_true", help="Include local source paths in stdout and task_pack.json; provenance stays redacted.")
    parser.add_argument("--llm", choices=("none", "ollama"), default="none", help="Optional local model pass. Default: none.")
    parser.add_argument("--model", default="qwen2.5-coder:1.5b", help="Ollama model name when --llm ollama is used.")
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"), help="Ollama base URL.")
    parser.add_argument("--llm-timeout", type=float, default=60.0, help="Ollama request timeout in seconds.")
    parser.add_argument("--require-llm", action="store_true", help="Fail instead of falling back when local model generation fails.")
    args = parser.parse_args()

    result = run(
        Path(args.source),
        args.task,
        Path(args.out),
        include_local_paths=args.include_local_paths,
        select_capsules=args.select_capsule,
        list_capsules=args.list_capsules,
        llm=args.llm,
        model=args.model,
        ollama_url=args.ollama_url,
        llm_timeout=args.llm_timeout,
        require_llm=args.require_llm,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
