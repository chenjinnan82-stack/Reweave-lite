from __future__ import annotations

import pimos_lite.reweave_process_environment as process_environment


def test_windows_subprocess_environment_keeps_only_runtime_requirements(monkeypatch) -> None:
    monkeypatch.setattr(process_environment.os, "name", "nt")
    for key in process_environment._WINDOWS_RUNTIME_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PATH", "runtime-path")
    monkeypatch.setenv("SYSTEMROOT", "C:/Windows")
    monkeypatch.setenv("TEMP", "C:/Temp")
    monkeypatch.setenv("NODE_OPTIONS", "--require=untrusted.js")
    monkeypatch.setenv("NODE_PATH", "untrusted-modules")
    monkeypatch.setenv("REWEAVE_SECRET", "must-not-leak")

    environment = process_environment.restricted_subprocess_environment()

    assert environment == {
        "PATH": "runtime-path",
        "SYSTEMROOT": "C:/Windows",
        "TEMP": "C:/Temp",
    }


def test_subprocess_environment_applies_explicit_worker_overrides(monkeypatch) -> None:
    monkeypatch.setattr(process_environment.os, "name", "posix")
    monkeypatch.setenv("PATH", "runtime-path")

    environment = process_environment.restricted_subprocess_environment(
        {"HOME": "/temporary/home", "TEMP": "/temporary"}
    )

    assert environment == {
        "PATH": "runtime-path",
        "HOME": "/temporary/home",
        "TEMP": "/temporary",
    }
