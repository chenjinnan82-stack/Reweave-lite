#!/usr/bin/env python3
"""Generate a product from formal SQLite capsules through ReweaveAppService."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
import time
from contextlib import contextmanager
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Callable, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pimos_lite.reweave_app_service import ReweaveAppService


DEFAULT_TIMEOUT_SECONDS = 120
CANCEL_DRAIN_SECONDS = 30
MAX_TIMEOUT_SECONDS = 3600
PROCESS_OVERHEAD_SECONDS = 30
PROCESS_STOP_SECONDS = 5


@contextmanager
def _state_dir(path: str | None) -> Iterator[None]:
    previous = os.environ.get("REWEAVE_STATE_DIR")
    if path:
        os.environ["REWEAVE_STATE_DIR"] = str(Path(path).expanduser().resolve())
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("REWEAVE_STATE_DIR", None)
        else:
            os.environ["REWEAVE_STATE_DIR"] = previous


def _error(code: str) -> dict[str, object]:
    return {"ok": False, "error": {"code": code, "message_key": code}}


def run(
    task: str,
    capsule_ids: list[str],
    *,
    state_dir: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    task = task.strip()
    selected = list(
        dict.fromkeys(value.strip() for value in capsule_ids if value.strip())
    )
    if not task:
        return _error("task_required")
    if not selected:
        return _error("formal_capsule_selection_required")
    if (
        type(timeout_seconds) is not int
        or timeout_seconds < 1
        or timeout_seconds > MAX_TIMEOUT_SECONDS
    ):
        return _error("generation_timeout_invalid")

    with _state_dir(state_dir):
        service = ReweaveAppService()
        try:
            started = service.generate_product(
                {"task": task, "capsule_ids": selected, "selection_mode": "manual"}
            )
            if started.get("ok") is not True or not started.get("run_id"):
                return started
            run_id = str(started["run_id"])
            deadline = time.monotonic() + timeout_seconds
            cancel_deadline: float | None = None
            while True:
                polled = service.get_intake_run({"run_id": run_id})
                if polled.get("ok") is not True:
                    return polled
                state = polled.get("data")
                if not isinstance(state, dict):
                    return _error("generation_run_invalid")
                status = str(state.get("status") or "")
                if status == "completed":
                    result = state.get("data")
                    return (
                        result
                        if isinstance(result, dict)
                        else _error("generation_result_invalid")
                    )
                if status == "failed":
                    error = state.get("error")
                    return (
                        {"ok": False, "error": error}
                        if isinstance(error, dict)
                        else _error("generation_failed")
                    )
                if status == "cancelled":
                    return _error(
                        "generation_timed_out"
                        if cancel_deadline is not None
                        else "generation_cancelled"
                    )
                if status not in {"queued", "running"}:
                    return _error("generation_run_invalid")
                now = time.monotonic()
                if cancel_deadline is None and now >= deadline:
                    cancelled = service.cancel_intake_run({"run_id": run_id})
                    error = cancelled.get("error")
                    error_code = (
                        error.get("code") if isinstance(error, dict) else None
                    )
                    if (
                        cancelled.get("ok") is not True
                        and error_code != "intake_run_already_terminal"
                    ):
                        return cancelled
                    cancel_deadline = now + CANCEL_DRAIN_SECONDS
                elif cancel_deadline is not None and now >= cancel_deadline:
                    return _error("generation_cancel_timeout")
                time.sleep(0.1)
        finally:
            service.close()


def _bounded_child(
    connection: Connection,
    task: str,
    capsule_ids: list[str],
    state_dir: str | None,
    timeout_seconds: int,
) -> None:
    try:
        result = run(
            task,
            capsule_ids,
            state_dir=state_dir,
            timeout_seconds=timeout_seconds,
        )
    except BaseException:
        result = _error("public_reweave_cli_failed")
    try:
        connection.send(result)
    except (BrokenPipeError, EOFError, OSError):
        pass
    finally:
        connection.close()


def _stop_process(process: multiprocessing.Process) -> None:
    if not process.is_alive():
        return
    process.terminate()
    process.join(PROCESS_STOP_SECONDS)
    if process.is_alive():
        process.kill()
        process.join(PROCESS_STOP_SECONDS)


def _run_bounded(
    task: str,
    capsule_ids: list[str],
    *,
    state_dir: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    _worker: Callable[..., None] = _bounded_child,
) -> dict[str, object]:
    if (
        type(timeout_seconds) is not int
        or timeout_seconds < 1
        or timeout_seconds > MAX_TIMEOUT_SECONDS
    ):
        return _error("generation_timeout_invalid")
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker,
        args=(sender, task, capsule_ids, state_dir, timeout_seconds),
        name="reweave-public-cli",
    )
    started = False
    try:
        process.start()
        started = True
        sender.close()
        if not receiver.poll(
            timeout_seconds + CANCEL_DRAIN_SECONDS + PROCESS_OVERHEAD_SECONDS
        ):
            _stop_process(process)
            return _error("generation_process_timeout")
        try:
            result = receiver.recv()
        except (EOFError, OSError):
            result = None
        process.join(PROCESS_STOP_SECONDS)
        if process.is_alive():
            _stop_process(process)
            return _error("public_reweave_cli_failed")
        if process.exitcode != 0 or not isinstance(result, dict):
            return _error("public_reweave_cli_failed")
        return result
    finally:
        sender.close()
        receiver.close()
        if started and process.is_alive():
            _stop_process(process)
        process.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, help="Task to generate.")
    parser.add_argument(
        "--capsule-id",
        action="append",
        default=[],
        help="Formal SQLite capsule ID. Repeat for each capsule.",
    )
    parser.add_argument(
        "--state-dir",
        help="Optional Reweave state directory containing capsule_warehouse.sqlite3.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Maximum generation time before safe cancellation (default: 120).",
    )
    args = parser.parse_args()
    try:
        result = _run_bounded(
            task=args.task,
            capsule_ids=args.capsule_id,
            state_dir=args.state_dir,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception:
        result = _error("public_reweave_cli_failed")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
