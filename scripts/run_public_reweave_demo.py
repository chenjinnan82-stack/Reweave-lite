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


def _import_reweave() -> tuple[object, object, object, object, object]:
    import sys

    sys.path.insert(0, str(ROOT))
    from pimos_lite.reweave_capsule_draft import draft_capsules
    from pimos_lite.reweave_capsule_warehouse import promote_source_drafts
    from pimos_lite.reweave_preview_pack import build_preview_package
    from pimos_lite.reweave_source_registry import add_source_box
    from pimos_lite.reweave_source_scanner import scan_source_box

    return add_source_box, scan_source_box, draft_capsules, promote_source_drafts, build_preview_package


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


def run(source: Path, task: str, out: Path, *, include_local_paths: bool = False) -> dict[str, object]:
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise SystemExit(f"source folder not found: {source}")
    out = _safe_out(out)

    add_source_box, scan_source_box, draft_capsules, promote_source_drafts, build_preview_package = _import_reweave()

    with tempfile.TemporaryDirectory(prefix="reweave-public-demo-state-") as state:
        os.environ["REWEAVE_STATE_DIR"] = state
        box = add_source_box(source)
        if box.get("status") == "blocked":
            raise SystemExit(str(box.get("last_error") or "source box blocked"))
        scan = scan_source_box(box["id"])
        draft = draft_capsules(box["id"])
        capsules = promote_source_drafts(box["id"])
        capsule_ids = [str(cap["id"]) for cap in capsules[:4]]
        source_box = _source_box_public(box, source, include_local_paths=include_local_paths)
        preview = build_preview_package(
            {
                "task": task,
                "capsuleIds": capsule_ids,
                "backend": "public_demo",
                "sourceBoxes": [source_box],
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
            "task": task,
            "source_box": source_box,
            "selected_capsule_ids": capsule_ids,
            "output_files": _public_files(out),
            "source_project_write": False,
        }
        _write_json(out / "task_pack.json", task_pack)
        summary = [
            "# Reweave public demo",
            "",
            f"- Source Box: `{source.name}`",
            f"- Task: {task}",
            f"- Files scanned: {scan.get('counts', {}).get('files_scanned', 0)}",
            f"- Capsule candidates: {draft.get('candidate_count', 0)}",
            f"- Capsules used: {len(capsule_ids)}",
            "- Source project writes: 0",
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
            "source_project_write": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="examples/source_boxes/customer-quote-widget")
    parser.add_argument("--task", default="Build a quote summary card")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--include-local-paths", action="store_true", help="Include local source paths in stdout and task_pack.json; provenance stays redacted.")
    args = parser.parse_args()

    result = run(Path(args.source), args.task, Path(args.out), include_local_paths=args.include_local_paths)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
