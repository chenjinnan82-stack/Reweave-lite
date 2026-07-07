"""Reweave engine protocol and factory."""

from __future__ import annotations

import os
from typing import Any, Protocol

from pimos_lite.reweave_engine.local import LocalReweaveEngine

DEFAULT_BACKEND = "lumo_lite"
LEGACY_WORKBENCH_TOKEN = "REWEAVE_LEGACY_WORKBENCH_ACK"


class ReweaveEngine(Protocol):
    def get_initial_state(self) -> dict[str, Any]: ...

    def bind_source_folder(self, path: str) -> dict[str, Any]: ...

    def scan_source(self, source_id: str) -> dict[str, Any]: ...

    def draft_source(self, source_id: str) -> dict[str, Any]: ...

    def promote_source(self, source_id: str) -> list[dict[str, Any]]: ...

    def get_source(self, source_id: str) -> dict[str, Any] | None: ...

    def generate_preview(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def engine_backend_name() -> str:
    return os.environ.get("REWEAVE_ENGINE", DEFAULT_BACKEND).strip().lower() or DEFAULT_BACKEND


def create_reweave_engine() -> ReweaveEngine:
    backend = engine_backend_name()
    if backend == "lumo_lite":
        from pimos_lite.reweave_engine.lumo_lite import LumoLiteReweaveEngine

        return LumoLiteReweaveEngine()
    if backend in {"local", "lumo"} and os.environ.get("REWEAVE_ENABLE_LEGACY_WORKBENCH") != LEGACY_WORKBENCH_TOKEN:
        from pimos_lite.reweave_engine.lumo_lite import LumoLiteReweaveEngine

        return LumoLiteReweaveEngine()
    if backend == "lumo":
        from pimos_lite.reweave_engine.lumo import LumoReweaveEngine

        return LumoReweaveEngine()
    if backend == "local":
        return LocalReweaveEngine()
    from pimos_lite.reweave_engine.lumo_lite import LumoLiteReweaveEngine

    return LumoLiteReweaveEngine()
