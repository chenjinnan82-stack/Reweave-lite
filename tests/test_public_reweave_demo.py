from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from scripts import run_public_reweave_demo as demo


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_public_reweave_demo.py"


def test_public_reweave_demo_help_is_formal_capsule_only() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert all(
        option in completed.stdout
        for option in ("--task", "--capsule-id", "--state-dir")
    )
    assert all(
        option not in completed.stdout
        for option in (
            "--source",
            "--out",
            "--llm",
            "--model",
            "--select-capsule",
            "--timeout",
        )
    )


def test_public_reweave_demo_uses_only_app_service_generation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "ReweaveAppService" in source
    assert "service.generate_product(" in source
    assert "service.get_intake_run(" in source
    assert all(
        token not in source
        for token in (
            "LumoLiteReweaveEngine",
            "create_reweave_engine",
            "bind_source_folder",
            "promote_source",
            "generate_preview",
            "ollama",
            "fallback",
        )
    )


def test_readmes_describe_the_formal_sqlite_service_path() -> None:
    readmes = [
        (ROOT / "README.md").read_text(encoding="utf-8"),
        (ROOT / "README.zh-CN.md").read_text(encoding="utf-8"),
    ]

    for text in readmes:
        assert "ReweaveAppService" in text
        assert "--capsule-id" in text
        assert "SQLite" in text
        assert "run_public_stage4_demo.py" in text
        assert "qwen2.5-coder" not in text
        assert "--llm" not in text
        assert "--model" not in text
        assert "built-in Stage4 composer" not in text
    assert "inactive migration history" in readmes[0]
    assert "非活跃迁移历史" in readmes[1]


def test_public_reweave_demo_requires_a_formal_capsule(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--task",
            "Build a quote tool",
            "--state-dir",
            str(tmp_path),
        ],
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout) == {
        "ok": False,
        "error": {
            "code": "formal_capsule_selection_required",
            "message_key": "formal_capsule_selection_required",
        },
    }


def test_public_reweave_demo_polls_and_returns_raw_product(tmp_path: Path) -> None:
    calls: list[tuple[str, object]] = []
    final = {
        "ok": True,
        "productId": "product-1",
        "manifestDigest": "a" * 64,
        "previewPath": str(tmp_path / "product-1"),
    }

    class Service:
        def __init__(self) -> None:
            calls.append(("state_dir", os.environ.get("REWEAVE_STATE_DIR")))

        def generate_product(self, payload: dict[str, object]) -> dict[str, object]:
            calls.append(("generate", payload))
            return {"ok": True, "run_id": "run-1", "status": "queued"}

        def get_intake_run(self, payload: dict[str, object]) -> dict[str, object]:
            calls.append(("poll", payload))
            poll_count = sum(name == "poll" for name, _value in calls)
            if poll_count == 1:
                return {"ok": True, "data": {"status": "running"}}
            return {"ok": True, "data": {"status": "completed", "data": final}}

        def close(self) -> None:
            calls.append(("close", None))

    with (
        patch.object(demo, "ReweaveAppService", Service),
        patch.object(demo.time, "sleep"),
        patch.dict(os.environ, {"REWEAVE_STATE_DIR": "before"}),
    ):
        result = demo.run(
            "Build a quote tool",
            [" capsule-a ", "capsule-a", "capsule-b"],
            state_dir=str(tmp_path),
        )
        assert os.environ["REWEAVE_STATE_DIR"] == "before"

    assert result == final
    assert calls[0] == ("state_dir", str(tmp_path.resolve()))
    assert calls[1] == (
        "generate",
        {
            "task": "Build a quote tool",
            "capsule_ids": ["capsule-a", "capsule-b"],
            "selection_mode": "manual",
        },
    )
    assert calls[-1] == ("close", None)
