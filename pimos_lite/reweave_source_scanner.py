"""Reweave Source Box Scanner v0 — explicit, read-only directory summary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pimos_lite.reweave_source_registry import (
    get_source_box,
    load_json_state,
    mark_source_scan_failed,
    mark_source_scanned,
    state_dir,
)

SUMMARY_SCHEMA_VERSION = 1

IGNORED_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".next",
        ".turbo",
        "target",
        "vendor",
    }
)

IGNORED_FILE_NAMES = frozenset({".DS_Store"})

ENTRY_CANDIDATE_NAMES = frozenset(
    {
        "package.json",
        "index.html",
        "main.py",
        "app.py",
        "README.md",
        "pyproject.toml",
    }
)


@dataclass(frozen=True)
class ScanLimits:
    max_files: int = 800
    max_depth: int = 8
    max_file_size_bytes: int = 1048576


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def summaries_dir() -> Path:
    return state_dir() / "source_summaries"


def summary_file_path(source_id: str) -> Path:
    return summaries_dir() / f"{source_id}.summary.json"


def summary_rel_path(source_id: str) -> str:
    return f"source_summaries/{source_id}.summary.json"


def save_summary(summary: dict[str, Any]) -> str:
    """Persist summary under app state (never inside the source folder)."""
    path = summary_file_path(summary["source_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return summary_rel_path(summary["source_id"])


def load_summary(source_id: str) -> dict[str, Any] | None:
    path = summary_file_path(source_id)
    data = load_json_state(path, {})
    return data if isinstance(data, dict) else None


def load_summary_light(source_id: str) -> dict[str, Any] | None:
    """Lightweight summary for get_initial_state (no full tree)."""
    summary = load_summary(source_id)
    if not summary:
        return None
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    return {
        "source_id": source_id,
        "scan_status": summary.get("scan_status"),
        "scanned_at": summary.get("scanned_at"),
        "files_total": counts.get("files_total", 0),
        "files_scanned": counts.get("files_scanned", 0),
    }


def list_summary_lights() -> list[dict[str, Any]]:
    lights: list[dict[str, Any]] = []
    for path in sorted(summaries_dir().glob("source_*.summary.json")):
        source_id = path.stem.replace(".summary", "")
        light = load_summary_light(source_id)
        if light:
            lights.append(light)
    return lights


def scan_directory_readonly(
    root: Path,
    *,
    source_id: str,
    label: str,
    limits: ScanLimits | None = None,
) -> dict[str, Any]:
    """Walk *root* read-only. Stats only — no file content reads."""
    limits = limits or ScanLimits()
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(f"not a directory: {resolved}")

    warnings: list[str] = []
    counts = {
        "files_total": 0,
        "dirs_total": 0,
        "files_scanned": 0,
        "files_skipped": 0,
    }
    extensions: dict[str, int] = {}
    entry_candidates: list[str] = []
    sample_paths_by_extension: dict[str, list[str]] = {}
    files_scanned = 0
    stop = False

    def record_file(entry: Path) -> None:
        nonlocal files_scanned, stop
        if stop:
            return
        if files_scanned >= limits.max_files:
            if "max_files_reached" not in warnings:
                warnings.append("max_files_reached")
            stop = True
            return

        counts["files_total"] += 1
        try:
            size = entry.stat().st_size
        except OSError:
            counts["files_skipped"] += 1
            warnings.append(f"stat_failed:{entry.name}")
            return

        if size > limits.max_file_size_bytes:
            counts["files_skipped"] += 1
            return

        files_scanned += 1
        counts["files_scanned"] += 1
        ext = entry.suffix.lower()
        extensions[ext] = extensions.get(ext, 0) + 1
        try:
            rel = entry.relative_to(resolved).as_posix()
        except ValueError:
            rel = entry.name
        samples = sample_paths_by_extension.setdefault(ext, [])
        if rel not in samples and len(samples) < 5:
            samples.append(rel)

        if entry.name in ENTRY_CANDIDATE_NAMES:
            if rel not in entry_candidates:
                entry_candidates.append(rel)

    def walk(directory: Path, depth: int) -> None:
        nonlocal stop
        if stop or depth > limits.max_depth:
            if depth > limits.max_depth and "max_depth_reached" not in warnings:
                warnings.append("max_depth_reached")
            return

        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            warnings.append(f"access_denied:{directory}")
            return

        for entry in entries:
            if stop:
                return
            name = entry.name
            if name in IGNORED_FILE_NAMES:
                counts["files_skipped"] += 1
                continue
            if entry.is_symlink():
                counts["files_skipped"] += 1
                warnings.append(f"symlink_skipped:{name}")
                continue
            if entry.is_dir():
                counts["dirs_total"] += 1
                if name in IGNORED_DIR_NAMES:
                    counts["files_skipped"] += 1
                    continue
                walk(entry, depth + 1)
            elif entry.is_file():
                record_file(entry)
            else:
                counts["files_skipped"] += 1

    walk(resolved, 0)

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "source_id": source_id,
        "label": label,
        "path": str(resolved),
        "scan_status": "scanned",
        "scanned_at": _utc_now_iso(),
        "limits": {
            "max_files": limits.max_files,
            "max_depth": limits.max_depth,
            "max_file_size_bytes": limits.max_file_size_bytes,
        },
        "counts": counts,
        "extensions": dict(sorted(extensions.items(), key=lambda kv: (-kv[1], kv[0]))),
        "sample_paths_by_extension": {
            ext: paths for ext, paths in sorted(sample_paths_by_extension.items(), key=lambda kv: kv[0])
        },
        "ignored_dirs": sorted(IGNORED_DIR_NAMES),
        "entry_candidates": entry_candidates,
        "warnings": warnings,
    }


def scan_source_box(source_id: str, *, limits: ScanLimits | None = None) -> dict[str, Any]:
    """Explicit scan for one registered source box. Updates registry metadata."""
    box = get_source_box(source_id)
    if not box:
        raise KeyError(f"source not found: {source_id}")

    root = Path(box.get("path", ""))
    if not root.is_dir():
        mark_source_scan_failed(source_id, "source path not found")
        raise FileNotFoundError(f"source path not found: {root}")

    try:
        summary = scan_directory_readonly(
            root,
            source_id=source_id,
            label=str(box.get("label") or root.name),
            limits=limits,
        )
        rel = save_summary(summary)
        mark_source_scanned(source_id, rel, summary["scanned_at"])
        return summary
    except Exception as exc:
        mark_source_scan_failed(source_id, str(exc))
        raise
