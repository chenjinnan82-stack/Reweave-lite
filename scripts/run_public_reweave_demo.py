#!/usr/bin/env python3
"""Generate a product from formal SQLite capsules through ReweaveAppService."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pimos_lite.reweave_app_service import ReweaveAppService


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
) -> dict[str, object]:
    task = task.strip()
    selected = list(
        dict.fromkeys(value.strip() for value in capsule_ids if value.strip())
    )
    if not task:
        return _error("task_required")
    if not selected:
        return _error("formal_capsule_selection_required")

    with _state_dir(state_dir):
        service = ReweaveAppService()
        try:
            started = service.generate_product(
                {"task": task, "capsule_ids": selected, "selection_mode": "manual"}
            )
            if started.get("ok") is not True or not started.get("run_id"):
                return started
            run_id = str(started["run_id"])
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
                    return _error("generation_cancelled")
                if status not in {"queued", "running"}:
                    return _error("generation_run_invalid")
                time.sleep(0.1)
        finally:
            service.close()


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
    args = parser.parse_args()
    try:
        result = run(
            task=args.task,
            capsule_ids=args.capsule_id,
            state_dir=args.state_dir,
        )
    except Exception:
        result = _error("public_reweave_cli_failed")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
