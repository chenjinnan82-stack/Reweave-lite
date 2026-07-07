from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_reweave_demo_outputs_task_pack(tmp_path: Path) -> None:
    out = tmp_path / "demo"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(ROOT / "examples" / "source_boxes" / "customer-quote-widget"),
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
    for name in ("task_pack.json", "capsules_used.json", "provenance.json", "summary.md"):
        assert (out / name).is_file()

    task_pack = json.loads((out / "task_pack.json").read_text(encoding="utf-8"))
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert task_pack["source_project_write"] is False
    assert provenance["source_boxes"][0]["label"] == "customer-quote-widget"
