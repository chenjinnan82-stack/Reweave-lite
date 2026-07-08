from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_reweave_demo_outputs_task_pack(tmp_path: Path) -> None:
    source = ROOT / "examples" / "source_boxes" / "customer-quote-widget"
    out = tmp_path / "reweave_demo"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(source),
            "--task",
            "Build a quote summary card",
            "--out",
            str(out),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["capsules_used"] > 0
    for name in ("task_pack.json", "capsules_used.json", "provenance.json", "snippets_used.json", "summary.md"):
        assert (out / name).is_file()
    assert not (source / ".reweave").exists()

    task_pack = json.loads((out / "task_pack.json").read_text(encoding="utf-8"))
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    snippets_used = json.loads((out / "snippets_used.json").read_text(encoding="utf-8"))
    assert task_pack["source_project_write"] is False
    assert task_pack["selected_capsule_ids"]
    assert provenance["source_boxes"][0]["label"] == "customer-quote-widget"
    assert "path" not in provenance["source_boxes"][0]
    assert "path_hash" not in provenance["source_boxes"][0]
    assert provenance["source_boxes"][0]["path_policy"] == "redacted"
    assert "path_hash" not in payload["source"]
    assert provenance["content_aware_generate"]["enabled"] is True
    assert snippets_used["mode"] == "content_aware_preview"
    assert snippets_used["snippets"]
    assert snippets_used["safety"]["source_folder_read_at_generate_time"] is False
    assert snippets_used["safety"]["used_app_state_content_only"] is True


def test_public_reweave_demo_refuses_repo_output() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--out",
            str(ROOT / "reweave_demo"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "inside the repository" in result.stderr


def test_public_reweave_demo_refuses_existing_non_demo_dir(tmp_path: Path) -> None:
    out = tmp_path / "reweave_existing"
    out.mkdir()
    (out / "keep.txt").write_text("do not delete\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--out",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "non-demo output directory" in result.stderr
    assert (out / "keep.txt").is_file()
