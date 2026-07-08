from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_BOXES = (
    "customer-quote-widget",
    "ops-status-card",
    "support-ticket-triage",
    "content-calendar",
    "launch-checklist",
)


def _assert_local_assets_exist(out: Path) -> None:
    html = (out / "index.html").read_text(encoding="utf-8")
    for asset in re.findall(r"""(?:href|src)=["']([^"']+)["']""", html):
        if asset.startswith(("http://", "https://", "data:", "#")):
            continue
        assert (out / asset).is_file(), asset


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
    html = (out / "index.html").read_text(encoding="utf-8")
    styles = (out / "styles.css").read_text(encoding="utf-8")
    app_js = (out / "app.js").read_text(encoding="utf-8")
    assert "Small Project Pack" in html
    assert "reweaveDemoButton" in html
    assert "project-checklist" in html
    assert "reweave-step" in html
    assert "--accent: #172033;" in styles
    assert "local checks complete" in app_js
    _assert_local_assets_exist(out)


def test_public_reweave_demo_runs_five_source_boxes(tmp_path: Path) -> None:
    for name in SOURCE_BOXES:
        source = ROOT / "examples" / "source_boxes" / name
        out = tmp_path / f"reweave_{name}"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_public_reweave_demo.py"),
                "--source",
                str(source),
                "--task",
                f"Build a small project from {name}",
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
        assert payload["source_project_write"] is False
        assert not (source / ".reweave").exists()
        for required in ("index.html", "styles.css", "app.js", "task_pack.json", "capsules_used.json", "provenance.json", "snippets_used.json"):
            assert (out / required).is_file()
        task_pack = json.loads((out / "task_pack.json").read_text(encoding="utf-8"))
        snippets_used = json.loads((out / "snippets_used.json").read_text(encoding="utf-8"))
        html = (out / "index.html").read_text(encoding="utf-8")
        app_js = (out / "app.js").read_text(encoding="utf-8")
        assert task_pack["source_project_write"] is False
        assert task_pack["project_type"] == "small_project_pack"
        assert snippets_used["snippets"]
        assert "Small Project Pack" in html
        assert "project-checklist" in html
        assert "reweave-step" in html
        assert "local checks complete" in app_js
        assert "Source excerpts used" in html
        _assert_local_assets_exist(out)


def test_public_reweave_demo_supports_manual_capsule_selection(tmp_path: Path) -> None:
    source = ROOT / "examples" / "source_boxes" / "customer-quote-widget"
    listed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(source),
            "--list-capsules",
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    choices = json.loads(listed.stdout)
    assert choices["source_project_write"] is False
    assert {item["name"] for item in choices["capsules"]} >= {"Style Sheet", "Script Module"}

    out = tmp_path / "reweave_manual_selection"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(source),
            "--task",
            "Build a styled quote interaction",
            "--select-capsule",
            "Style Sheet",
            "--select-capsule",
            "Script Module",
            "--out",
            str(out),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    task_pack = json.loads((out / "task_pack.json").read_text(encoding="utf-8"))
    capsules_used = json.loads((out / "capsules_used.json").read_text(encoding="utf-8"))
    selected_names = [item["name"] for item in payload["selected_capsules"]]
    assert selected_names == ["Style Sheet", "Script Module"]
    assert task_pack["selection_mode"] == "manual"
    assert [item["name"] for item in task_pack["selected_capsules"]] == selected_names
    assert [item["name"] for item in capsules_used] == selected_names
    assert task_pack["source_project_write"] is False
    _assert_local_assets_exist(out)


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
