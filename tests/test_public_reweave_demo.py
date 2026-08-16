from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

from scripts import run_public_reweave_demo as demo


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_public_reweave_demo.py"


def _bounded_result_worker(connection, *_args) -> None:
    connection.send({"ok": True, "productId": "product-1"})
    connection.close()


def _bounded_hanging_worker(_connection, *_args) -> None:
    while True:
        time.sleep(1)


def _bounded_error_worker(_connection, *_args) -> None:
    raise RuntimeError("sentinel")


def _bounded_eof_worker(connection, *_args) -> None:
    connection.close()


def _bounded_invalid_worker(connection, *_args) -> None:
    connection.send(["invalid"])
    connection.close()


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
        for option in (
            "--task",
            "--capsule-id",
            "--state-dir",
            "--timeout-seconds",
        )
    )
    assert all(
        option not in completed.stdout
        for option in (
            "--source",
            "--out",
            "--llm",
            "--model",
            "--select-capsule",
        )
    )


def test_public_reweave_demo_uses_only_app_service_generation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "ReweaveAppService" in source
    assert "service.generate_product(" in source
    assert "service.get_intake_run(" in source
    assert "service.cancel_intake_run(" in source
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
        assert "run_public_stage4_demo.py" not in text
        assert "qwen2.5-coder" not in text
        assert "--llm" not in text
        assert "--model" not in text
        assert "built-in Stage4 composer" not in text
    assert "only public CLI entry" in readmes[0]
    assert "唯一公开 CLI 入口" in readmes[1]


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


def test_public_reweave_demo_timeout_requests_safe_cancel() -> None:
    calls: list[str] = []

    class Service:
        def generate_product(self, _payload: dict[str, object]) -> dict[str, object]:
            return {"ok": True, "run_id": "run-1", "status": "queued"}

        def get_intake_run(self, _payload: dict[str, object]) -> dict[str, object]:
            calls.append("poll")
            return {
                "ok": True,
                "data": {
                    "status": "running" if len(calls) == 1 else "cancelled"
                },
            }

        def cancel_intake_run(
            self, _payload: dict[str, object]
        ) -> dict[str, object]:
            calls.append("cancel")
            return {"ok": True}

        def close(self) -> None:
            calls.append("close")

    with (
        patch.object(demo, "ReweaveAppService", Service),
        patch.object(demo.time, "monotonic", side_effect=(0.0, 1.0)),
        patch.object(demo.time, "sleep"),
    ):
        result = demo.run("Build", ["capsule-a"], timeout_seconds=1)

    assert result == demo._error("generation_timed_out")
    assert calls == ["poll", "cancel", "poll", "close"]


def test_public_reweave_demo_completion_wins_after_cancel_request() -> None:
    completed = {"ok": True, "productId": "product-1"}
    polls = 0

    class Service:
        def generate_product(self, _payload: dict[str, object]) -> dict[str, object]:
            return {"ok": True, "run_id": "run-1", "status": "queued"}

        def get_intake_run(self, _payload: dict[str, object]) -> dict[str, object]:
            nonlocal polls
            polls += 1
            return {
                "ok": True,
                "data": (
                    {"status": "running"}
                    if polls == 1
                    else {"status": "completed", "data": completed}
                ),
            }

        def cancel_intake_run(
            self, _payload: dict[str, object]
        ) -> dict[str, object]:
            return {"ok": True}

        def close(self) -> None:
            pass

    with (
        patch.object(demo, "ReweaveAppService", Service),
        patch.object(demo.time, "monotonic", side_effect=(0.0, 1.0)),
        patch.object(demo.time, "sleep"),
    ):
        result = demo.run("Build", ["capsule-a"], timeout_seconds=1)

    assert result == completed


def test_public_reweave_demo_cancel_drain_is_bounded() -> None:
    cancels = 0

    class Service:
        def generate_product(self, _payload: dict[str, object]) -> dict[str, object]:
            return {"ok": True, "run_id": "run-1", "status": "queued"}

        def get_intake_run(self, _payload: dict[str, object]) -> dict[str, object]:
            return {"ok": True, "data": {"status": "running"}}

        def cancel_intake_run(
            self, _payload: dict[str, object]
        ) -> dict[str, object]:
            nonlocal cancels
            cancels += 1
            return {"ok": True}

        def close(self) -> None:
            pass

    with (
        patch.object(demo, "ReweaveAppService", Service),
        patch.object(demo.time, "monotonic", side_effect=(0.0, 1.0, 31.0)),
        patch.object(demo.time, "sleep"),
    ):
        result = demo.run("Build", ["capsule-a"], timeout_seconds=1)

    assert result == demo._error("generation_cancel_timeout")
    assert cancels == 1


def test_public_reweave_demo_rejects_invalid_timeout_without_starting() -> None:
    with patch.object(
        demo,
        "ReweaveAppService",
        side_effect=AssertionError("service must not start"),
    ):
        assert demo.run("Build", ["capsule-a"], timeout_seconds=0) == demo._error(
            "generation_timeout_invalid"
        )


def test_public_reweave_demo_bounded_process_returns_exact_result() -> None:
    result = demo._run_bounded(
        "Build",
        ["capsule-a"],
        timeout_seconds=1,
        _worker=_bounded_result_worker,
    )

    assert result == {"ok": True, "productId": "product-1"}


def test_public_reweave_demo_bounded_process_stops_hanging_worker() -> None:
    started = time.monotonic()
    with (
        patch.object(demo, "CANCEL_DRAIN_SECONDS", 0),
        patch.object(demo, "PROCESS_OVERHEAD_SECONDS", 0),
        patch.object(demo, "PROCESS_STOP_SECONDS", 0.1),
    ):
        result = demo._run_bounded(
            "Build",
            ["capsule-a"],
            timeout_seconds=1,
            _worker=_bounded_hanging_worker,
        )

    assert result == demo._error("generation_process_timeout")
    assert time.monotonic() - started < 3


def test_public_reweave_demo_bounded_process_fails_closed() -> None:
    for worker in (
        _bounded_error_worker,
        _bounded_eof_worker,
        _bounded_invalid_worker,
    ):
        assert demo._run_bounded(
            "Build",
            ["capsule-a"],
            timeout_seconds=1,
            _worker=worker,
        ) == demo._error("public_reweave_cli_failed")


def test_public_reweave_demo_stop_escalates_to_kill() -> None:
    calls: list[str] = []

    class Process:
        alive = True

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            calls.append("terminate")

        def join(self, timeout: float) -> None:
            calls.append(f"join:{timeout}")

        def kill(self) -> None:
            calls.append("kill")
            self.alive = False

    with patch.object(demo, "PROCESS_STOP_SECONDS", 0.25):
        demo._stop_process(Process())

    assert calls == ["terminate", "join:0.25", "kill", "join:0.25"]
