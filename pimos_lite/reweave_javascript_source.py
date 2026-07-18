"""Read-only JavaScript computation source ownership and stable file indexing."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
import unicodedata
import uuid
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from pimos_lite.reweave_capsule_store import CapsuleWarehouseStore
from pimos_lite.reweave_process_environment import restricted_subprocess_environment


JAVASCRIPT_SOURCE_TYPE = "javascript_computation_source"
PROJECT_FILE_INDEX_VERSION = "project_file_index.v1"
SCOPE_SNAPSHOT_VERSION = "javascript_scope_snapshot.v1"
SOURCE_IDENTITY_VERSION = "javascript_source_identity.v1"
GIT_STATUS_CONTRACT_VERSION = "git_status_contract.v1"

MAX_DIRECTORY_ENTRIES = 50_000
MAX_JAVASCRIPT_MODULES = 2_000
MAX_JAVASCRIPT_BYTES = 64 * 1024 * 1024
MAX_JAVASCRIPT_FILE_BYTES = 1024 * 1024
MAX_DIRECTORY_DEPTH = 32
SCAN_TIMEOUT_SECONDS = 60.0
MAX_GIT_STATUS_BYTES = 64 * 1024 * 1024

_PRUNED_DIRECTORIES = frozenset(
    {
        ".git",
        "node_modules",
        "dist",
        "build",
        "coverage",
        ".venv",
        "venv",
        "__pycache__",
    }
)
_JAVASCRIPT_OWNER_CREATION_LOCK = threading.Lock()
_ACTIVE_SCAN_LOCK = threading.Lock()
_ACTIVE_SCAN_PROJECTS: set[str] = set()


class JavascriptSourceError(RuntimeError):
    """A fail-closed, non-sensitive JavaScript source error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _IndexEntry:
    logical_path: str
    entry_kind: str
    size_bytes: int | None
    content_sha256: str | None
    content: bytes | None


@dataclass(frozen=True)
class _Snapshot:
    entries: tuple[_IndexEntry, ...]
    directory_entries: int
    javascript_bytes: int
    file_index_digest: str
    scope_snapshot_sha256: str
    git_exclusion_relpaths: tuple[str, ...]


@dataclass(frozen=True)
class _GitEvidence:
    git_state: str
    commit: str | None
    status_sha256: str | None


@dataclass(frozen=True)
class JavascriptModuleSnapshot:
    """Immutable module bytes for the next in-process source-graph stage."""

    logical_path: str
    content_sha256: str
    content: bytes = field(repr=False)


@dataclass(frozen=True)
class JavascriptScopeSnapshot:
    """Consistent source evidence; callers must never serialize module bytes."""

    project_id: str
    status: str
    file_index_digest: str
    scope_snapshot_sha256: str
    source_identity_sha256: str
    git_state: str
    git_commit: str | None
    git_status_sha256: str | None
    directory_entries: int
    javascript_bytes: int
    modules: tuple[JavascriptModuleSnapshot, ...] = field(repr=False)
    symlinks: tuple[str, ...]

    def safe_summary(self) -> dict[str, Any]:
        """Return the only representation suitable for UI, logs, or JSON."""
        return {
            "project_id": self.project_id,
            "source_type": JAVASCRIPT_SOURCE_TYPE,
            "status": self.status,
            "file_index_digest": self.file_index_digest,
            "scope_snapshot_sha256": self.scope_snapshot_sha256,
            "source_identity_sha256": self.source_identity_sha256,
            "git_state": self.git_state,
            "git_commit": self.git_commit,
            "git_status_sha256": self.git_status_sha256,
            "counts": {
                "directory_entries": self.directory_entries,
                "javascript_modules": len(self.modules),
                "symlinks": len(self.symlinks),
                "javascript_bytes": self.javascript_bytes,
            },
            "source_unchanged": True,
        }


@dataclass(frozen=True)
class _ScanContext:
    project_id: str
    scope_path: Path
    old_snapshot_hash: str | None
    exclusion_relpaths: tuple[str, ...]
    boundary_sha256: str


class JavascriptSourceService:
    """One concrete Stage-C service; it does not create candidates or run code."""

    def __init__(self, store: CapsuleWarehouseStore) -> None:
        self.store = store

    def check_unique_owners(self) -> None:
        """Fail closed when historical rows claim the same physical scope."""
        with self.store.read_connection() as connection:
            _require_schema_v2(connection)
            _assert_unique_owner_rows(_owner_rows(connection))

    def ensure_owner(
        self, source_root_id: str, project_relpath: str = "."
    ) -> dict[str, Any]:
        """Create or reuse the sole JS owner for a physical project scope."""
        normalized_relpath = _validate_scope_relpath(project_relpath)
        with _JAVASCRIPT_OWNER_CREATION_LOCK:
            with self.store.transaction() as connection:
                _require_schema_v2(connection)
                root = connection.execute(
                    "SELECT root_id, current_path, status FROM source_roots "
                    "WHERE root_id = ?",
                    (source_root_id,),
                ).fetchone()
                if root is None or root["status"] != "bound":
                    raise JavascriptSourceError("source_unavailable")
                requested_scope = _physical_scope(
                    str(root["current_path"]), normalized_relpath, require_exists=True
                )

                owners = _owner_rows(connection)
                _assert_unique_owner_rows(owners)
                requested_key = _physical_key(requested_scope)
                matches = [
                    row
                    for row in owners
                    if _owner_physical_key(row) == requested_key
                ]
                if len(matches) > 1:
                    raise JavascriptSourceError("duplicate_javascript_source_scope")
                if matches:
                    return {
                        "project_id": str(matches[0]["project_id"]),
                        "source_type": JAVASCRIPT_SOURCE_TYPE,
                        "created": False,
                    }

                project_id = f"js_{uuid.uuid4().hex}"
                now = _utc_now()
                discovery_signature = _sha256_json(
                    {
                        "version": "javascript_source_registration.v1",
                        "source_root_id": source_root_id,
                        "project_relpath": normalized_relpath,
                    }
                )
                connection.execute(
                    "INSERT INTO projects ("
                    "project_id, source_root_id, source_type, project_relpath, "
                    "entry_relpath, display_name, project_state, "
                    "discovery_signature, last_snapshot_hash, brand_mode, "
                    "brand_profile_id, brand_profile_json, brand_profile_digest, "
                    "brand_profile_version, created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, NULL, ?, 'ready', ?, NULL, 'inherit', "
                    "NULL, NULL, NULL, 0, ?, ?)",
                    (
                        project_id,
                        source_root_id,
                        JAVASCRIPT_SOURCE_TYPE,
                        normalized_relpath,
                        "JavaScript computation source",
                        discovery_signature,
                        now,
                        now,
                    ),
                )
                _invalidate_ancestor_indexes(
                    connection, requested_scope, owners, updated_at=now
                )
                self.store.bump_revision(connection)
                return {
                    "project_id": project_id,
                    "source_type": JAVASCRIPT_SOURCE_TYPE,
                    "created": True,
                }

    def scan(
        self,
        project_id: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> JavascriptScopeSnapshot:
        """Atomically replace one JS owner's index from matching source evidence."""
        deadline = time.monotonic() + SCAN_TIMEOUT_SECONDS
        with _project_scan_guard(project_id):
            _check_active(cancel_event, deadline)
            context = self._read_scan_context(project_id)
            snapshot_before = _capture_snapshot(
                context.scope_path,
                context.exclusion_relpaths,
                cancel_event=cancel_event,
                deadline=deadline,
            )
            git_before = _read_git_evidence(
                context.scope_path,
                exclusion_relpaths=snapshot_before.git_exclusion_relpaths,
                cancel_event=cancel_event,
                deadline=deadline,
            )
            snapshot_middle = _capture_snapshot(
                context.scope_path,
                context.exclusion_relpaths,
                cancel_event=cancel_event,
                deadline=deadline,
            )
            git_after = _read_git_evidence(
                context.scope_path,
                exclusion_relpaths=snapshot_middle.git_exclusion_relpaths,
                cancel_event=cancel_event,
                deadline=deadline,
            )
            snapshot_after = _capture_snapshot(
                context.scope_path,
                context.exclusion_relpaths,
                cancel_event=cancel_event,
                deadline=deadline,
            )
            git_final = _read_git_evidence(
                context.scope_path,
                exclusion_relpaths=snapshot_after.git_exclusion_relpaths,
                cancel_event=cancel_event,
                deadline=deadline,
            )
            snapshot_final = _capture_snapshot(
                context.scope_path,
                context.exclusion_relpaths,
                cancel_event=cancel_event,
                deadline=deadline,
            )
            git_confirmed = _read_git_evidence(
                context.scope_path,
                exclusion_relpaths=snapshot_final.git_exclusion_relpaths,
                cancel_event=cancel_event,
                deadline=deadline,
            )
            if (
                snapshot_before.file_index_digest
                != snapshot_middle.file_index_digest
                or snapshot_middle.file_index_digest
                != snapshot_after.file_index_digest
                or snapshot_after.file_index_digest
                != snapshot_final.file_index_digest
                or snapshot_before.scope_snapshot_sha256
                != snapshot_middle.scope_snapshot_sha256
                or snapshot_middle.scope_snapshot_sha256
                != snapshot_after.scope_snapshot_sha256
                or snapshot_after.scope_snapshot_sha256
                != snapshot_final.scope_snapshot_sha256
                or git_before != git_after
                or git_after != git_final
                or git_final != git_confirmed
            ):
                raise JavascriptSourceError("source_changed")
            _check_active(cancel_event, deadline)

            changed = self._persist_snapshot(
                context,
                snapshot_final,
                cancel_event=cancel_event,
                deadline=deadline,
            )
            source_identity_sha256 = _sha256_json(
                {
                    "version": SOURCE_IDENTITY_VERSION,
                    "scope_snapshot_sha256": snapshot_final.scope_snapshot_sha256,
                    "git_state": git_confirmed.git_state,
                    "commit": git_confirmed.commit,
                    "status_sha256": git_confirmed.status_sha256,
                }
            )
            return JavascriptScopeSnapshot(
                project_id=project_id,
                status="completed" if changed else "no_change",
                file_index_digest=snapshot_final.file_index_digest,
                scope_snapshot_sha256=snapshot_final.scope_snapshot_sha256,
                source_identity_sha256=source_identity_sha256,
                git_state=git_confirmed.git_state,
                git_commit=git_confirmed.commit,
                git_status_sha256=git_confirmed.status_sha256,
                directory_entries=snapshot_final.directory_entries,
                javascript_bytes=snapshot_final.javascript_bytes,
                modules=tuple(
                    JavascriptModuleSnapshot(
                        logical_path=entry.logical_path,
                        content_sha256=str(entry.content_sha256),
                        content=bytes(entry.content or b""),
                    )
                    for entry in snapshot_final.entries
                    if entry.entry_kind == "javascript_module"
                ),
                symlinks=tuple(
                    entry.logical_path
                    for entry in snapshot_final.entries
                    if entry.entry_kind == "symlink"
                ),
            )

    def _read_scan_context(self, project_id: str) -> _ScanContext:
        with self.store.read_connection() as connection:
            _require_schema_v2(connection)
            return _scan_context(connection, project_id)

    def _persist_snapshot(
        self,
        context: _ScanContext,
        snapshot: _Snapshot,
        *,
        cancel_event: threading.Event | None,
        deadline: float,
    ) -> bool:
        with self.store.transaction() as connection:
            _require_schema_v2(connection)
            current = _scan_context(connection, context.project_id)
            if (
                current.boundary_sha256 != context.boundary_sha256
                or current.old_snapshot_hash != context.old_snapshot_hash
            ):
                raise JavascriptSourceError("source_changed")
            _check_active(cancel_event, deadline)

            persisted_hash = snapshot.scope_snapshot_sha256 if snapshot.entries else None
            existing_rows = connection.execute(
                "SELECT logical_path, entry_kind, size_bytes, content_sha256 "
                "FROM project_file_index WHERE project_id = ? ORDER BY logical_path",
                (context.project_id,),
            ).fetchall()
            expected_rows = [
                (
                    entry.logical_path,
                    entry.entry_kind,
                    entry.size_bytes,
                    entry.content_sha256,
                )
                for entry in snapshot.entries
            ]
            actual_rows = [tuple(row) for row in existing_rows]
            if actual_rows == expected_rows and current.old_snapshot_hash == persisted_hash:
                return False

            connection.execute(
                "DELETE FROM project_file_index WHERE project_id = ?",
                (context.project_id,),
            )
            for entry in snapshot.entries:
                _check_active(cancel_event, deadline)
                connection.execute(
                    "INSERT INTO project_file_index ("
                    "project_id, logical_path, entry_kind, size_bytes, content_sha256"
                    ") VALUES (?, ?, ?, ?, ?)",
                    (
                        context.project_id,
                        entry.logical_path,
                        entry.entry_kind,
                        entry.size_bytes,
                        entry.content_sha256,
                    ),
                )
            _check_active(cancel_event, deadline)
            updated = connection.execute(
                "UPDATE projects SET last_snapshot_hash = ?, updated_at = ? "
                "WHERE project_id = ? "
                "AND source_type = 'javascript_computation_source' "
                "AND project_state = 'ready' "
                "AND last_snapshot_hash IS ?",
                (
                    persisted_hash,
                    _utc_now(),
                    context.project_id,
                    context.old_snapshot_hash,
                ),
            )
            if updated.rowcount != 1:
                raise JavascriptSourceError("source_changed")
            self.store.bump_revision(connection)
            return True


def _require_schema_v2(connection: sqlite3.Connection) -> None:
    if int(connection.execute("PRAGMA user_version").fetchone()[0]) != 2:
        raise JavascriptSourceError("javascript_source_requires_schema_v2")


def _owner_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            "SELECT p.project_id, p.source_root_id, p.project_relpath, "
            "p.project_state, p.last_snapshot_hash, r.current_path, r.status "
            "FROM projects p JOIN source_roots r "
            "ON r.root_id = p.source_root_id "
            "WHERE p.source_type = 'javascript_computation_source' "
            "ORDER BY p.project_id"
        )
    )


def _owner_scope(row: sqlite3.Row, *, require_exists: bool) -> Path:
    return _physical_scope(
        str(row["current_path"]),
        _validate_scope_relpath(str(row["project_relpath"])),
        require_exists=require_exists,
    )


def _assert_unique_owner_rows(rows: list[sqlite3.Row]) -> None:
    seen: dict[tuple[Any, ...], str] = {}
    for row in rows:
        key = _owner_physical_key(row)
        if key is None:
            continue
        if key in seen:
            raise JavascriptSourceError("duplicate_javascript_source_scope")
        seen[key] = str(row["project_id"])


def _owner_physical_key(row: sqlite3.Row) -> tuple[Any, ...] | None:
    try:
        return _physical_key(_owner_scope(row, require_exists=False))
    except JavascriptSourceError as exc:
        if exc.code in {"source_scope_symlink_forbidden", "source_unavailable"}:
            return None
        raise


def _invalidate_ancestor_indexes(
    connection: sqlite3.Connection,
    requested_scope: Path,
    owners: list[sqlite3.Row],
    *,
    updated_at: str,
) -> None:
    for row in owners:
        try:
            owner_scope = _owner_scope(row, require_exists=False)
        except JavascriptSourceError as exc:
            if exc.code in {"source_scope_symlink_forbidden", "source_unavailable"}:
                continue
            raise
        relative = _physical_relative_descendant(requested_scope, owner_scope)
        if relative in {None, ""}:
            continue
        project_id = str(row["project_id"])
        connection.execute(
            "DELETE FROM project_file_index WHERE project_id = ?", (project_id,)
        )
        connection.execute(
            "UPDATE projects SET last_snapshot_hash = NULL, updated_at = ? "
            "WHERE project_id = ?",
            (updated_at, project_id),
        )


def _scan_context(connection: sqlite3.Connection, project_id: str) -> _ScanContext:
    row = connection.execute(
        "SELECT p.project_id, p.source_root_id, p.source_type, p.project_relpath, "
        "p.project_state, p.last_snapshot_hash, r.current_path, r.status "
        "FROM projects p JOIN source_roots r ON r.root_id = p.source_root_id "
        "WHERE p.project_id = ?",
        (project_id,),
    ).fetchone()
    if (
        row is None
        or row["source_type"] != JAVASCRIPT_SOURCE_TYPE
        or row["project_state"] != "ready"
        or row["status"] != "bound"
    ):
        raise JavascriptSourceError("source_unavailable")
    owners = _owner_rows(connection)
    _assert_unique_owner_rows(owners)
    scope_path = _physical_scope(
        str(row["current_path"]),
        _validate_scope_relpath(str(row["project_relpath"])),
        require_exists=True,
    )

    exclusions: list[dict[str, str]] = []
    registered = connection.execute(
        "SELECT p.project_id, p.source_type, p.project_relpath, "
        "r.current_path FROM projects p JOIN source_roots r "
        "ON r.root_id = p.source_root_id ORDER BY p.project_id"
    ).fetchall()
    for child in registered:
        if str(child["project_id"]) == project_id:
            continue
        try:
            child_scope = _physical_scope(
                str(child["current_path"]),
                _validate_scope_relpath(str(child["project_relpath"])),
                require_exists=False,
            )
        except JavascriptSourceError as exc:
            if exc.code in {"source_scope_symlink_forbidden", "source_unavailable"}:
                continue
            raise
        relative = _physical_relative_descendant(child_scope, scope_path)
        if relative in {None, ""}:
            continue
        _validate_logical_path(relative)
        exclusions.append(
            {
                "project_id": str(child["project_id"]),
                "source_type": str(child["source_type"]),
                "relative_scope": relative,
            }
        )
    exclusions.sort(
        key=lambda item: (
            item["relative_scope"].encode("utf-8"),
            item["project_id"].encode("utf-8"),
        )
    )
    boundary_sha256 = _sha256_json(
        {
            "version": "javascript_scan_boundary.v1",
            "project_id": project_id,
            "source_root_id": str(row["source_root_id"]),
            "project_relpath": str(row["project_relpath"]),
            "physical_scope_sha256": hashlib.sha256(
                os.fsencode(scope_path)
            ).hexdigest(),
            "exclusions": exclusions,
        }
    )
    return _ScanContext(
        project_id=project_id,
        scope_path=scope_path,
        old_snapshot_hash=row["last_snapshot_hash"],
        exclusion_relpaths=tuple(item["relative_scope"] for item in exclusions),
        boundary_sha256=boundary_sha256,
    )


def _physical_scope(
    current_path: str, project_relpath: str, *, require_exists: bool
) -> Path:
    root = Path(current_path).expanduser()
    if not root.is_absolute():
        raise JavascriptSourceError("source_unavailable")
    resolved_root, root_identity = _stable_no_symlink_path(
        root, require_exists=require_exists
    )
    candidate = (
        resolved_root
        if project_relpath == "."
        else resolved_root.joinpath(*project_relpath.split("/"))
    )
    resolved, _ = _stable_no_symlink_path(candidate, require_exists=require_exists)
    if _path_chain_identity(root, require_exists=require_exists) != root_identity:
        raise JavascriptSourceError("source_changed")
    if resolved != resolved_root and not resolved.is_relative_to(resolved_root):
        raise JavascriptSourceError("source_scope_symlink_forbidden")
    if require_exists:
        try:
            if not resolved.is_dir():
                raise JavascriptSourceError("source_unavailable")
        except OSError:
            raise JavascriptSourceError("source_unavailable") from None
    return resolved


def _stable_no_symlink_path(
    path: Path, *, require_exists: bool
) -> tuple[Path, tuple[tuple[str, int, int], ...]]:
    before = _path_chain_identity(path, require_exists=require_exists)
    try:
        resolved = path.resolve(strict=require_exists)
    except (OSError, RuntimeError):
        raise JavascriptSourceError("source_unavailable") from None
    after = _path_chain_identity(path, require_exists=require_exists)
    if before != after:
        raise JavascriptSourceError("source_changed")
    missing_parts = len(path.parts) - 1 - len(before)
    resolved_anchor = resolved
    for _ in range(missing_parts):
        resolved_anchor = resolved_anchor.parent
    try:
        resolved_info = os.lstat(resolved_anchor)
        if before:
            expected_identity = (before[-1][1], before[-1][2])
        else:
            anchor_info = os.lstat(path.anchor)
            expected_identity = (int(anchor_info.st_dev), int(anchor_info.st_ino))
    except OSError:
        raise JavascriptSourceError("source_changed") from None
    if (
        stat.S_ISLNK(resolved_info.st_mode)
        or not stat.S_ISDIR(resolved_info.st_mode)
        or (int(resolved_info.st_dev), int(resolved_info.st_ino))
        != expected_identity
    ):
        raise JavascriptSourceError("source_changed")
    return resolved, after


def _path_chain_identity(
    path: Path, *, require_exists: bool
) -> tuple[tuple[str, int, int], ...]:
    current = Path(path.anchor)
    missing = False
    identities: list[tuple[str, int, int]] = []
    for part in path.parts[1:]:
        current /= part
        if missing:
            continue
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if require_exists:
                raise JavascriptSourceError("source_unavailable") from None
            missing = True
            continue
        except OSError:
            raise JavascriptSourceError("source_unavailable") from None
        if stat.S_ISLNK(info.st_mode) or os.path.islink(current):
            raise JavascriptSourceError("source_scope_symlink_forbidden")
        if not stat.S_ISDIR(info.st_mode):
            raise JavascriptSourceError("source_unavailable")
        identities.append((str(current), int(info.st_dev), int(info.st_ino)))
    return tuple(identities)


def _reject_symlink_chain(path: Path, *, require_exists: bool) -> None:
    _path_chain_identity(path, require_exists=require_exists)


def _physical_key(path: Path) -> tuple[Any, ...]:
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError:
        return ("path", os.path.normcase(str(path)))
    return ("inode", int(info.st_dev), int(info.st_ino))


def _physical_relative_descendant(child: Path, parent: Path) -> str | None:
    """Return the exact on-disk relative spelling for a physical descendant."""
    parent_key = _physical_key(parent)
    if _physical_key(child) == parent_key:
        return ""
    if parent_key[0] != "inode" or _physical_key(child)[0] != "inode":
        if child == parent:
            return ""
        return child.relative_to(parent).as_posix() if child.is_relative_to(parent) else None

    names: list[str] = []
    current = child
    while current.parent != current:
        current_key = _physical_key(current)
        directory = current.parent
        try:
            with os.scandir(directory) as iterator:
                match = next(
                    (
                        entry.name
                        for entry in iterator
                        if not entry.is_symlink()
                        and _physical_key(Path(entry.path)) == current_key
                    ),
                    None,
                )
        except OSError:
            raise JavascriptSourceError("source_changed") from None
        if match is None:
            raise JavascriptSourceError("source_changed")
        _validate_logical_path(match)
        names.append(match)
        current = directory
        if _physical_key(current) == parent_key:
            return "/".join(reversed(names))
    return None


def _capture_snapshot(
    scope_path: Path,
    exclusion_relpaths: tuple[str, ...],
    *,
    cancel_event: threading.Event | None,
    deadline: float,
) -> _Snapshot:
    if not _descriptor_relative_snapshot_supported():
        raise JavascriptSourceError("source_platform_unsupported_v1")
    entries: list[_IndexEntry] = []
    seen_paths: tuple[set[str], ...] = (set(), set(), set(), set())
    counters = {"entries": 0, "modules": 0, "bytes": 0}
    exclusions = set(exclusion_relpaths)
    git_exclusions = set(exclusion_relpaths)
    root_chain = _path_chain_identity(scope_path, require_exists=True)
    if not root_chain:
        raise JavascriptSourceError("source_unavailable")

    def walk(directory_fd: int, prefix: str, depth: int) -> None:
        _check_active(cancel_event, deadline)
        try:
            directory_before = os.fstat(directory_fd)
        except OSError:
            raise JavascriptSourceError("source_unavailable") from None
        if not stat.S_ISDIR(directory_before.st_mode):
            raise JavascriptSourceError("source_unavailable")
        try:
            with os.scandir(directory_fd) as iterator:
                child_names = []
                for child in iterator:
                    _check_active(cancel_event, deadline)
                    counters["entries"] += 1
                    if counters["entries"] > MAX_DIRECTORY_ENTRIES:
                        raise JavascriptSourceError("source_scope_limit_exceeded")
                    try:
                        child.name.encode("utf-8")
                    except UnicodeEncodeError:
                        raise JavascriptSourceError(
                            "source_path_normalization_conflict"
                        ) from None
                    child_names.append(child.name)
        except OSError:
            raise JavascriptSourceError("source_unavailable") from None
        try:
            child_names.sort(key=lambda item: item.encode("utf-8"))
        except UnicodeEncodeError:
            raise JavascriptSourceError("source_path_normalization_conflict") from None

        for child_name in child_names:
            _check_active(cancel_event, deadline)
            logical_path = child_name if not prefix else f"{prefix}/{child_name}"
            _validate_logical_path(logical_path)
            _register_path(logical_path, seen_paths)
            try:
                child_info = os.stat(
                    child_name, dir_fd=directory_fd, follow_symlinks=False
                )
            except OSError:
                raise JavascriptSourceError("source_changed") from None
            child_mode = child_info.st_mode

            if stat.S_ISLNK(child_mode):
                entries.append(
                    _IndexEntry(logical_path, "symlink", None, None, None)
                )
                continue
            if stat.S_ISDIR(child_mode):
                child_depth = depth + 1
                if child_depth > MAX_DIRECTORY_DEPTH:
                    raise JavascriptSourceError("source_scope_limit_exceeded")
                if child_name in _PRUNED_DIRECTORIES or logical_path in exclusions:
                    git_exclusions.add(logical_path)
                    continue
                child_fd = _open_directory_at(
                    directory_fd, child_name, expected=child_info
                )
                try:
                    walk(child_fd, logical_path, child_depth)
                    opened_child = os.fstat(child_fd)
                finally:
                    os.close(child_fd)
                try:
                    bound_child = os.stat(
                        child_name, dir_fd=directory_fd, follow_symlinks=False
                    )
                except OSError:
                    raise JavascriptSourceError("source_changed") from None
                if (
                    not stat.S_ISDIR(bound_child.st_mode)
                    or _filesystem_object_identity(opened_child)
                    != _filesystem_object_identity(bound_child)
                ):
                    raise JavascriptSourceError("source_changed")
                continue
            if not logical_path.endswith((".js", ".mjs")):
                continue
            if not stat.S_ISREG(child_mode):
                raise JavascriptSourceError("source_unavailable")

            content = _read_regular_file_at(
                directory_fd,
                child_name,
                expected=child_info,
                cancel_event=cancel_event,
                deadline=deadline,
            )
            counters["modules"] += 1
            counters["bytes"] += len(content)
            if (
                counters["modules"] > MAX_JAVASCRIPT_MODULES
                or counters["bytes"] > MAX_JAVASCRIPT_BYTES
            ):
                raise JavascriptSourceError("source_scope_limit_exceeded")
            entries.append(
                _IndexEntry(
                    logical_path,
                    "javascript_module",
                    len(content),
                    hashlib.sha256(content).hexdigest(),
                    content,
                )
            )

        try:
            directory_after = os.fstat(directory_fd)
        except OSError:
            raise JavascriptSourceError("source_changed") from None
        if _stable_object_identity(directory_before) != _stable_object_identity(
            directory_after
        ):
            raise JavascriptSourceError("source_changed")

    root_fd = _open_root_directory(scope_path, expected_chain=root_chain)
    try:
        walk(root_fd, "", 0)
        root_after = os.fstat(root_fd)
    finally:
        os.close(root_fd)
    if _filesystem_object_identity(root_after) != (
        int(root_chain[-1][1]),
        int(root_chain[-1][2]),
    ):
        raise JavascriptSourceError("source_changed")
    if _path_chain_identity(scope_path, require_exists=True) != root_chain:
        raise JavascriptSourceError("source_changed")
    ordered = tuple(sorted(entries, key=lambda entry: entry.logical_path.encode("utf-8")))
    modules = [
        {
            "path": entry.logical_path,
            "size": entry.size_bytes,
            "sha256": entry.content_sha256,
        }
        for entry in ordered
        if entry.entry_kind == "javascript_module"
    ]
    symlinks = [
        {"path": entry.logical_path}
        for entry in ordered
        if entry.entry_kind == "symlink"
    ]
    file_index_digest = _sha256_json(
        {
            "version": PROJECT_FILE_INDEX_VERSION,
            "entries": [
                {
                    "path": entry.logical_path,
                    "kind": entry.entry_kind,
                    "size": entry.size_bytes,
                    "sha256": entry.content_sha256,
                }
                for entry in ordered
            ],
        }
    )
    scope_snapshot_sha256 = _sha256_json(
        {
            "version": SCOPE_SNAPSHOT_VERSION,
            "javascript_modules": modules,
            "symlinks": symlinks,
        }
    )
    return _Snapshot(
        entries=ordered,
        directory_entries=counters["entries"],
        javascript_bytes=counters["bytes"],
        file_index_digest=file_index_digest,
        scope_snapshot_sha256=scope_snapshot_sha256,
        git_exclusion_relpaths=tuple(
            sorted(git_exclusions, key=lambda value: value.encode("utf-8"))
        ),
    )


def _descriptor_relative_snapshot_supported() -> bool:
    return (
        hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_NONBLOCK")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.scandir in os.supports_fd
    )


def _open_flags(*, directory: bool) -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if directory:
        flags |= os.O_DIRECTORY
    else:
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _filesystem_object_identity(value: os.stat_result) -> tuple[int, int]:
    return int(value.st_dev), int(value.st_ino)


def _stable_object_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _stable_file_identity(
    value: os.stat_result,
) -> tuple[int, int, int, int, int]:
    return (*_stable_object_identity(value), int(value.st_size))


def _open_root_directory(
    path: Path, *, expected_chain: tuple[tuple[str, int, int], ...]
) -> int:
    try:
        descriptor = os.open(path, _open_flags(directory=True))
    except OSError:
        raise JavascriptSourceError("source_unavailable") from None
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or _filesystem_object_identity(opened)
            != (int(expected_chain[-1][1]), int(expected_chain[-1][2]))
        ):
            raise JavascriptSourceError("source_changed")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_directory_at(
    parent_fd: int, name: str, *, expected: os.stat_result
) -> int:
    try:
        descriptor = os.open(
            name, _open_flags(directory=True), dir_fd=parent_fd
        )
    except OSError:
        raise JavascriptSourceError("source_changed") from None
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or _filesystem_object_identity(opened)
            != _filesystem_object_identity(expected)
        ):
            raise JavascriptSourceError("source_changed")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_regular_file_at(
    directory_fd: int,
    name: str,
    *,
    expected: os.stat_result,
    cancel_event: threading.Event | None,
    deadline: float,
) -> bytes:
    try:
        descriptor = os.open(
            name, _open_flags(directory=False), dir_fd=directory_fd
        )
    except OSError:
        raise JavascriptSourceError("source_changed") from None
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or _filesystem_object_identity(before)
            != _filesystem_object_identity(expected)
        ):
            raise JavascriptSourceError("source_changed")
        if before.st_size > MAX_JAVASCRIPT_FILE_BYTES:
            raise JavascriptSourceError("source_scope_limit_exceeded")
        chunks: list[bytes] = []
        total = 0
        while True:
            _check_active(cancel_event, deadline)
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_JAVASCRIPT_FILE_BYTES:
                raise JavascriptSourceError("source_scope_limit_exceeded")
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        path_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError:
        raise JavascriptSourceError("source_changed") from None
    if (
        not stat.S_ISREG(path_after.st_mode)
        or _stable_file_identity(before) != _stable_file_identity(after)
        or _stable_file_identity(after) != _stable_file_identity(path_after)
    ):
        raise JavascriptSourceError("source_changed")
    return b"".join(chunks)


def _trusted_git_executable(repository_root: Path) -> str:
    for raw_directory in os.environ.get("PATH", "").split(os.pathsep):
        if not raw_directory:
            continue
        directory = Path(raw_directory).expanduser()
        if not directory.is_absolute():
            continue
        try:
            resolved_directory = directory.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if resolved_directory == repository_root or resolved_directory.is_relative_to(
            repository_root
        ):
            continue
        candidate = shutil.which("git", path=str(resolved_directory))
        if candidate is None:
            continue
        try:
            resolved_candidate = Path(candidate).resolve(strict=True)
            candidate_info = os.lstat(resolved_candidate)
        except (OSError, RuntimeError):
            continue
        if (
            resolved_candidate == repository_root
            or resolved_candidate.is_relative_to(repository_root)
            or not stat.S_ISREG(candidate_info.st_mode)
            or not os.access(resolved_candidate, os.X_OK)
        ):
            continue
        return str(resolved_candidate)
    raise JavascriptSourceError("source_unavailable")


@contextmanager
def _empty_git_attribute_source(
    object_format: str,
) -> Iterator[tuple[str, Path]]:
    if object_format not in {"sha1", "sha256"}:
        raise JavascriptSourceError("source_unavailable")
    payload = b"tree 0\0"
    digest = hashlib.new(object_format, payload).hexdigest()
    try:
        with tempfile.TemporaryDirectory(prefix="reweave-git-attributes.") as raw:
            object_root = Path(raw)
            object_path = object_root / digest[:2] / digest[2:]
            object_path.parent.mkdir(mode=0o700)
            object_path.write_bytes(zlib.compress(payload))
            yield digest, object_root
    except OSError:
        raise JavascriptSourceError("source_unavailable") from None


def _absolute_git_path(raw: bytes, *, require_exists: bool) -> Path:
    if raw.endswith(b"\r\n"):
        raw = raw[:-2]
    elif raw.endswith(b"\n"):
        raw = raw[:-1]
    else:
        raise JavascriptSourceError("source_unavailable")
    if b"\0" in raw or b"\n" in raw or b"\r" in raw:
        raise JavascriptSourceError("source_path_normalization_conflict")
    try:
        path = Path(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise JavascriptSourceError("source_path_normalization_conflict") from None
    if not path.is_absolute():
        raise JavascriptSourceError("source_unavailable")
    try:
        return path.resolve(strict=require_exists)
    except (OSError, RuntimeError):
        raise JavascriptSourceError("source_unavailable") from None


@contextmanager
def _isolated_git_status_repository(
    *,
    repository_root: Path,
    index_path: Path,
    object_directory: Path,
    object_format: str,
    commit: str | None,
) -> Iterator[dict[str, str]]:
    """Expose only inert metadata while Git compares the read-only worktree."""

    if object_format not in {"sha1", "sha256"}:
        raise JavascriptSourceError("source_unavailable")
    try:
        object_info = os.lstat(object_directory)
        if not stat.S_ISDIR(object_info.st_mode) or stat.S_ISLNK(object_info.st_mode):
            raise JavascriptSourceError("source_unavailable")
        if index_path.exists():
            index_info = os.lstat(index_path)
            if not stat.S_ISREG(index_info.st_mode) or stat.S_ISLNK(index_info.st_mode):
                raise JavascriptSourceError("source_unavailable")
            isolated_index = index_path
        else:
            isolated_index = None
        with tempfile.TemporaryDirectory(prefix="reweave-git-status.") as raw:
            git_directory = Path(raw)
            (git_directory / "info").mkdir(mode=0o700)
            (git_directory / "objects").mkdir(mode=0o700)
            (git_directory / "refs" / "heads").mkdir(parents=True, mode=0o700)
            config = [
                "[core]",
                f"\trepositoryformatversion = {1 if object_format == 'sha256' else 0}",
                "\tbare = false",
                "\tfilemode = true",
                "\tlogallrefupdates = false",
            ]
            if object_format == "sha256":
                config.extend(("[extensions]", "\tobjectFormat = sha256"))
            (git_directory / "config").write_text(
                "\n".join(config) + "\n", encoding="ascii"
            )
            (git_directory / "HEAD").write_text(
                f"{commit}\n" if commit else "ref: refs/heads/reweave-unborn\n",
                encoding="ascii",
            )
            environment = {
                "GIT_DIR": str(git_directory),
                "GIT_WORK_TREE": str(repository_root),
                "GIT_OBJECT_DIRECTORY": str(object_directory),
            }
            if isolated_index is not None:
                environment["GIT_INDEX_FILE"] = str(isolated_index)
            else:
                environment["GIT_INDEX_FILE"] = str(git_directory / "index")
            yield environment
    except OSError:
        raise JavascriptSourceError("source_unavailable") from None


def _git_status_pathspecs(
    scope_prefix: str, exclusion_relpaths: tuple[str, ...]
) -> tuple[str, ...]:
    if scope_prefix != ".":
        _validate_logical_path(scope_prefix)
    pathspecs = [f":(literal){scope_prefix}"]
    for relative in sorted(
        set(exclusion_relpaths), key=lambda value: value.encode("utf-8")
    ):
        _validate_logical_path(relative)
        repo_relative = (
            relative if scope_prefix == "." else f"{scope_prefix}/{relative}"
        )
        _validate_logical_path(repo_relative)
        pathspecs.append(f":(exclude,literal){repo_relative}")
    return tuple(pathspecs)


def _read_git_evidence(
    scope_path: Path,
    *,
    exclusion_relpaths: tuple[str, ...] = (),
    cancel_event: threading.Event | None,
    deadline: float,
) -> _GitEvidence:
    stable_scope, _ = _stable_no_symlink_path(scope_path, require_exists=True)
    marker_kind, repository_hint = _git_marker(stable_scope)
    if marker_kind in {"none", "symlink"}:
        return _GitEvidence("non_git", None, None)
    if repository_hint is None:
        raise JavascriptSourceError("source_unavailable")
    git = _trusted_git_executable(repository_hint)

    probe = _run_git(
        git,
        scope_path,
        ["rev-parse", "--is-inside-work-tree"],
        cancel_event=cancel_event,
        deadline=deadline,
        allow_failure=True,
    )
    if probe[0] != 0:
        raise JavascriptSourceError("source_unavailable")
    if probe[1] not in {b"true\n", b"true\r\n"}:
        raise JavascriptSourceError("source_unavailable")

    top_result = _run_git(
        git,
        scope_path,
        ["rev-parse", "--show-toplevel"],
        cancel_event=cancel_event,
        deadline=deadline,
    )
    raw_top = top_result[1]
    if raw_top.endswith(b"\r\n"):
        raw_top = raw_top[:-2]
    elif raw_top.endswith(b"\n"):
        raw_top = raw_top[:-1]
    else:
        raise JavascriptSourceError("source_unavailable")
    try:
        top_text = raw_top.decode("utf-8")
    except UnicodeDecodeError:
        raise JavascriptSourceError("source_path_normalization_conflict") from None
    repo_root, _ = _stable_no_symlink_path(Path(top_text), require_exists=True)
    if _physical_key(repo_root) != _physical_key(repository_hint):
        raise JavascriptSourceError("source_unavailable")
    try:
        scope_from_repo = scope_path.relative_to(repo_root)
    except ValueError:
        raise JavascriptSourceError("source_unavailable") from None
    scope_prefix = scope_from_repo.as_posix() if scope_from_repo.parts else "."

    head_result = _run_git(
        git,
        repo_root,
        ["rev-parse", "--verify", "HEAD"],
        cancel_event=cancel_event,
        deadline=deadline,
        allow_failure=True,
    )
    commit: str | None = None
    if head_result[0] == 0:
        try:
            commit = head_result[1].decode("ascii").strip()
        except UnicodeDecodeError:
            raise JavascriptSourceError("source_unavailable") from None
        if len(commit) not in {40, 64} or any(
            character not in "0123456789abcdef" for character in commit
        ):
            raise JavascriptSourceError("source_unavailable")
    else:
        symbolic_head = _run_git(
            git,
            repo_root,
            ["symbolic-ref", "--quiet", "HEAD"],
            cancel_event=cancel_event,
            deadline=deadline,
            allow_failure=True,
        )
        if symbolic_head[0] != 0 or not symbolic_head[1].startswith(b"refs/heads/"):
            raise JavascriptSourceError("source_unavailable")

    object_format_result = _run_git(
        git,
        repo_root,
        ["rev-parse", "--show-object-format"],
        cancel_event=cancel_event,
        deadline=deadline,
    )
    try:
        object_format = object_format_result[1].decode("ascii").strip()
    except UnicodeDecodeError:
        raise JavascriptSourceError("source_unavailable") from None
    index_result = _run_git(
        git,
        repo_root,
        ["rev-parse", "--path-format=absolute", "--git-path", "index"],
        cancel_event=cancel_event,
        deadline=deadline,
    )
    object_directory_result = _run_git(
        git,
        repo_root,
        ["rev-parse", "--path-format=absolute", "--git-path", "objects"],
        cancel_event=cancel_event,
        deadline=deadline,
    )
    index_path = _absolute_git_path(index_result[1], require_exists=False)
    object_directory = _absolute_git_path(
        object_directory_result[1], require_exists=True
    )
    with _empty_git_attribute_source(object_format) as (
        empty_tree,
        alternate_objects,
    ), _isolated_git_status_repository(
        repository_root=repo_root,
        index_path=index_path,
        object_directory=object_directory,
        object_format=object_format,
        commit=commit,
    ) as isolated_environment:
        isolated_environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(
            alternate_objects
        )
        status_result = _run_git(
            git,
            repo_root,
            [
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--ignore-submodules=all",
                "--no-renames",
                "--",
                *_git_status_pathspecs(scope_prefix, exclusion_relpaths),
            ],
            cancel_event=cancel_event,
            deadline=deadline,
            global_arguments=(f"--attr-source={empty_tree}",),
            environment_overrides=isolated_environment,
        )
    status_entries = _parse_git_status(
        status_result[1],
        scope_prefix=scope_prefix,
        exclusion_relpaths=exclusion_relpaths,
        cancel_event=cancel_event,
        deadline=deadline,
    )
    status_sha256 = _sha256_json(
        {"version": GIT_STATUS_CONTRACT_VERSION, "entries": status_entries}
    )
    return _GitEvidence(
        "dirty_git" if status_entries else "clean_git",
        commit,
        status_sha256,
    )


def _run_git(
    executable: str,
    directory: Path,
    arguments: list[str],
    *,
    cancel_event: threading.Event | None,
    deadline: float,
    allow_failure: bool = False,
    global_arguments: tuple[str, ...] = (),
    environment_overrides: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    _check_active(cancel_event, deadline)
    overrides = {
        "PATH": str(Path(executable).parent),
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "",
        "GIT_PROTOCOL_FROM_USER": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "PAGER": "",
    }
    if environment_overrides:
        overrides.update(environment_overrides)
    environment = restricted_subprocess_environment(overrides)
    command = [
        executable,
        "--no-optional-locks",
        "--no-pager",
        "--no-replace-objects",
        *global_arguments,
        "-c",
        f"core.attributesFile={os.devnull}",
        "-c",
        f"core.excludesFile={os.devnull}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "core.untrackedCache=false",
        "-c",
        "submodule.recurse=false",
        "-C",
        str(directory),
        *arguments,
    ]
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                env=environment,
                shell=False,
                start_new_session=os.name != "nt",
                creationflags=(
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    if os.name == "nt"
                    else 0
                ),
            )
        except OSError:
            raise JavascriptSourceError("source_unavailable") from None
        try:
            while process.poll() is None:
                _check_active(cancel_event, deadline)
                if stdout_file.tell() > MAX_GIT_STATUS_BYTES:
                    raise JavascriptSourceError("source_scope_limit_exceeded")
                time.sleep(0.01)
        except BaseException:
            _terminate_process_tree(process)
            raise
        if stdout_file.tell() > MAX_GIT_STATUS_BYTES:
            raise JavascriptSourceError("source_scope_limit_exceeded")
        stdout_file.seek(0)
        output = stdout_file.read(MAX_GIT_STATUS_BYTES + 1)
        return_code = int(process.returncode)
    if return_code != 0 and not allow_failure:
        raise JavascriptSourceError("source_unavailable")
    return return_code, output


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except OSError:
            pass
        process.wait()


def _parse_git_status(
    raw: bytes,
    *,
    scope_prefix: str,
    exclusion_relpaths: tuple[str, ...] = (),
    cancel_event: threading.Event | None = None,
    deadline: float = float("inf"),
) -> list[dict[str, str]]:
    if not raw:
        return []
    if not raw.endswith(b"\0"):
        raise JavascriptSourceError("source_path_normalization_conflict")
    entries: list[dict[str, str]] = []
    seen: tuple[set[str], ...] = (set(), set(), set(), set())
    position = 0
    record_count = 0
    while position < len(raw):
        _check_active(cancel_event, deadline)
        terminator = raw.find(b"\0", position)
        if terminator < 0:
            raise JavascriptSourceError("source_path_normalization_conflict")
        record = raw[position:terminator]
        position = terminator + 1
        if len(record) < 4 or record[2:3] != b" ":
            raise JavascriptSourceError("source_path_normalization_conflict")
        try:
            status_code = record[:2].decode("ascii")
            repo_path = record[3:].decode("utf-8")
        except UnicodeDecodeError:
            raise JavascriptSourceError("source_path_normalization_conflict") from None
        _validate_status_code(status_code)
        _validate_logical_path(repo_path)
        logical_path = _scope_relative_git_path(repo_path, scope_prefix)
        if any(part in _PRUNED_DIRECTORIES for part in logical_path.split("/")):
            continue
        if any(
            logical_path == excluded or logical_path.startswith(f"{excluded}/")
            for excluded in exclusion_relpaths
        ):
            continue
        record_count += 1
        if record_count > MAX_DIRECTORY_ENTRIES:
            raise JavascriptSourceError("source_scope_limit_exceeded")
        _register_path(logical_path, seen)
        entries.append({"status": status_code, "path": logical_path})
    entries.sort(
        key=lambda item: (item["path"].encode("utf-8"), item["status"].encode("ascii"))
    )
    return entries


def _validate_status_code(value: str) -> None:
    if len(value) != 2 or value == "  " or "R" in value or "C" in value or "!" in value:
        raise JavascriptSourceError("source_path_normalization_conflict")
    if "?" in value and value != "??":
        raise JavascriptSourceError("source_path_normalization_conflict")
    if any(character not in " MADU?" for character in value):
        raise JavascriptSourceError("source_path_normalization_conflict")


def _scope_relative_git_path(repo_path: str, scope_prefix: str) -> str:
    if scope_prefix == ".":
        return repo_path
    prefix = f"{scope_prefix}/"
    if not repo_path.startswith(prefix):
        raise JavascriptSourceError("source_path_normalization_conflict")
    relative = repo_path[len(prefix) :]
    _validate_logical_path(relative)
    return relative


def _git_marker(scope_path: Path) -> tuple[str, Path | None]:
    for candidate in (scope_path, *scope_path.parents):
        try:
            info = os.lstat(candidate / ".git")
        except FileNotFoundError:
            continue
        except OSError:
            raise JavascriptSourceError("source_unavailable") from None
        return (
            ("symlink", candidate)
            if stat.S_ISLNK(info.st_mode)
            else ("real", candidate)
        )
    return "none", None


def _validate_scope_relpath(value: str) -> str:
    if value == ".":
        return value
    _validate_logical_path(value)
    return value


def _validate_logical_path(value: str) -> None:
    if not isinstance(value, str) or not value or value.startswith("/") or value.endswith("/"):
        raise JavascriptSourceError("source_path_normalization_conflict")
    if "\\" in value:
        raise JavascriptSourceError("source_path_normalization_conflict")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise JavascriptSourceError("source_path_normalization_conflict") from None
    parts = value.split("/")
    if any(
        not part
        or part in {".", ".."}
        or any(ord(character) < 32 or ord(character) == 127 for character in part)
        for part in parts
    ):
        raise JavascriptSourceError("source_path_normalization_conflict")


def _register_path(value: str, seen: tuple[set[str], ...]) -> None:
    keys = (
        value,
        value.casefold(),
        unicodedata.normalize("NFC", value),
        unicodedata.normalize("NFC", value).casefold(),
    )
    if any(key in bucket for key, bucket in zip(keys, seen)):
        raise JavascriptSourceError("source_path_normalization_conflict")
    for key, bucket in zip(keys, seen):
        bucket.add(key)


@contextmanager
def _project_scan_guard(project_id: str) -> Iterator[None]:
    with _ACTIVE_SCAN_LOCK:
        if project_id in _ACTIVE_SCAN_PROJECTS:
            raise JavascriptSourceError("scan_already_running")
        _ACTIVE_SCAN_PROJECTS.add(project_id)
    try:
        yield
    finally:
        with _ACTIVE_SCAN_LOCK:
            _ACTIVE_SCAN_PROJECTS.discard(project_id)


def _check_active(
    cancel_event: threading.Event | None, deadline: float
) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise JavascriptSourceError("scan_cancelled")
    if time.monotonic() > deadline:
        raise JavascriptSourceError("source_scope_limit_exceeded")


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
