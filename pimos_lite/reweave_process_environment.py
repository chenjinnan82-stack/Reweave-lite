"""Minimal environment for trusted Reweave subprocess launchers."""

from __future__ import annotations

import os
from collections.abc import Mapping


_WINDOWS_RUNTIME_KEYS = (
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "SYSTEMDRIVE",
    "TEMP",
    "TMP",
)


def restricted_subprocess_environment(
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Keep injection-prone Node variables out while preserving Windows runtime keys."""

    environment = {"PATH": os.environ.get("PATH", "")}
    if os.name == "nt":
        for key in _WINDOWS_RUNTIME_KEYS:
            value = os.environ.get(key)
            if value:
                environment[key] = value
    if overrides:
        environment.update(overrides)
    return environment
