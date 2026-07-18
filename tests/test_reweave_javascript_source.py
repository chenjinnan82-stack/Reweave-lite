from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

import pimos_lite.reweave_javascript_source as javascript_source
from pimos_lite.reweave_capsule_store import CapsuleWarehouseStore
from pimos_lite.reweave_javascript_source import (
    JavascriptScopeSnapshot,
    JavascriptSourceError,
    JavascriptSourceService,
)


@contextmanager
def _sandbox() -> Path:
    temporary_root = Path("/private/tmp")
    if not temporary_root.is_dir():
        temporary_root = Path(tempfile.gettempdir())
    with tempfile.TemporaryDirectory(
        dir=temporary_root, prefix="reweave-javascript-source-test."
    ) as raw:
        yield Path(raw)


def _store(base: Path, *, migrate: bool = True) -> CapsuleWarehouseStore:
    store = CapsuleWarehouseStore(base / "state" / "capsule_warehouse.sqlite3")
    store.initialize()
    if migrate:
        store.migrate_v1_to_v2()
    return store


def _add_root(
    store: CapsuleWarehouseStore, root_id: str, source: Path, *, status: str = "bound"
) -> None:
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO source_roots ("
            "root_id, root_kind, current_path, status, brand_profile_id, "
            "brand_profile_json, brand_profile_digest, brand_profile_version, "
            "created_at, updated_at"
            ") VALUES (?, 'single_project', ?, ?, NULL, NULL, NULL, 0, ?, ?)",
            (root_id, str(source), status, _NOW, _NOW),
        )


def _add_project(
    store: CapsuleWarehouseStore,
    *,
    project_id: str,
    root_id: str,
    source_type: str,
    project_relpath: str = ".",
    entry_relpath: str | None = None,
) -> None:
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO projects ("
            "project_id, source_root_id, source_type, project_relpath, "
            "entry_relpath, display_name, project_state, discovery_signature, "
            "last_snapshot_hash, brand_mode, brand_profile_id, brand_profile_json, "
            "brand_profile_digest, brand_profile_version, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, 'fixture', 'ready', ?, NULL, 'inherit', "
            "NULL, NULL, NULL, 0, ?, ?)",
            (
                project_id,
                root_id,
                source_type,
                project_relpath,
                entry_relpath,
                hashlib.sha256(project_id.encode()).hexdigest(),
                _NOW,
                _NOW,
            ),
        )


def _owner(
    store: CapsuleWarehouseStore, root_id: str, project_relpath: str = "."
) -> tuple[JavascriptSourceService, str]:
    service = JavascriptSourceService(store)
    result = service.ensure_owner(root_id, project_relpath)
    return service, str(result["project_id"])


def _index_state(
    store: CapsuleWarehouseStore, project_id: str
) -> tuple[str | None, list[tuple[object, ...]], int]:
    with store.read_connection() as connection:
        project = connection.execute(
            "SELECT last_snapshot_hash FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        rows = connection.execute(
            "SELECT logical_path, entry_kind, size_bytes, content_sha256 "
            "FROM project_file_index WHERE project_id = ? ORDER BY logical_path",
            (project_id,),
        ).fetchall()
        revision = int(
            connection.execute(
                "SELECT warehouse_revision FROM warehouse_state WHERE singleton_id = 1"
            ).fetchone()[0]
        )
    return project[0], [tuple(row) for row in rows], revision


def _formal_counts(store: CapsuleWarehouseStore) -> dict[str, int]:
    tables = (
        "intake_runs",
        "review_items",
        "capability_groups",
        "capsules",
        "capsule_versions",
        "capsule_sources",
        "capsule_assets",
        "capsule_status_events",
        "product_capsule_usage",
        "legacy_capsule_aliases",
    )
    with store.read_connection() as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }


def _tree_digest(root: Path) -> str:
    rows: list[dict[str, object]] = []

    def walk(directory: Path, prefix: str) -> None:
        for child in sorted(os.scandir(directory), key=lambda item: os.fsencode(item.name)):
            relative = child.name if not prefix else f"{prefix}/{child.name}"
            if child.is_symlink():
                rows.append({"path": relative, "kind": "symlink", "target": os.readlink(child.path)})
            elif child.is_dir(follow_symlinks=False):
                rows.append({"path": relative, "kind": "directory"})
                walk(Path(child.path), relative)
            elif child.is_file(follow_symlinks=False):
                rows.append(
                    {
                        "path": relative,
                        "kind": "file",
                        "sha256": hashlib.sha256(Path(child.path).read_bytes()).hexdigest(),
                    }
                )

    walk(root, "")
    return _canonical_sha256(rows)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _assert_code(code: str, action: object) -> None:
    with pytest.raises(JavascriptSourceError) as caught:
        action()  # type: ignore[operator]
    assert caught.value.code == code


def _git(directory: Path, *arguments: str) -> str:
    if shutil.which("git") is None:
        pytest.skip("git is required for this fixture")
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_NAME": "Reweave Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Reweave Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
    )
    result = subprocess.run(
        ["git", "-C", str(directory), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    return result.stdout.decode("utf-8").strip()


_NOW = "2026-07-17T00:00:00Z"


@pytest.fixture(autouse=True)
def _skip_real_scan_without_descriptor_support(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    is_platform_gate = (
        request.node.name
        == "test_snapshot_fails_closed_without_descriptor_relative_primitives"
    )
    if javascript_source._descriptor_relative_snapshot_supported() or is_platform_gate:
        return

    def skip_unsupported_scan(*args: object, **kwargs: object) -> None:
        pytest.skip("descriptor-relative snapshot primitives are unavailable")

    monkeypatch.setattr(JavascriptSourceService, "scan", skip_unsupported_scan)


def test_stage_c_requires_explicit_schema_v2() -> None:
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        store = _store(base, migrate=False)
        _add_root(store, "root", source)

        _assert_code(
            "javascript_source_requires_schema_v2",
            lambda: JavascriptSourceService(store).ensure_owner("root"),
        )


def test_unique_owner_reuses_across_roots_and_blocks_historical_duplicates() -> None:
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        store = _store(base)
        _add_root(store, "root-a", source)
        _add_root(store, "root-b", source)
        service = JavascriptSourceService(store)
        barrier = threading.Barrier(2)

        def create(root_id: str) -> dict[str, object]:
            barrier.wait()
            return service.ensure_owner(root_id)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create, ("root-a", "root-b")))
        assert len({result["project_id"] for result in results}) == 1
        assert sorted(bool(result["created"]) for result in results) == [False, True]
        with store.read_connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM projects "
                "WHERE source_type = 'javascript_computation_source'"
            ).fetchone()[0] == 1

    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        store = _store(base)
        _add_root(store, "root-a", source)
        _add_root(store, "root-b", source)
        _add_project(
            store,
            project_id="duplicate-a",
            root_id="root-a",
            source_type="javascript_computation_source",
        )
        _add_project(
            store,
            project_id="duplicate-b",
            root_id="root-b",
            source_type="javascript_computation_source",
        )
        _assert_code(
            "duplicate_javascript_source_scope",
            JavascriptSourceService(store).check_unique_owners,
        )


def test_scope_and_ancestor_symlinks_are_rejected_but_unrelated_links_are_indexed() -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks are unavailable")
    with _sandbox() as base:
        real = base / "real"
        real.mkdir()
        (real / "app.js").write_text("export const value = 1;\n", encoding="utf-8")
        linked_root = base / "linked-root"
        try:
            linked_root.symlink_to(real, target_is_directory=True)
        except OSError:
            pytest.skip("symlink creation is not permitted")
        store = _store(base)
        _add_root(store, "linked", linked_root)
        _assert_code(
            "source_scope_symlink_forbidden",
            lambda: JavascriptSourceService(store).ensure_owner("linked"),
        )

    with _sandbox() as base:
        source = base / "source"
        target = base / "outside.js"
        fake_git = base / "outside-git"
        source.mkdir()
        fake_git.mkdir()
        target.write_text("secret payload", encoding="utf-8")
        (source / "app.js").write_text("export const value = 1;\n", encoding="utf-8")
        (source / "outside-link.js").symlink_to(target)
        (source / "broken").symlink_to(base / "missing")
        (source / ".git").symlink_to(fake_git, target_is_directory=True)
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        snapshot = service.scan(project_id)

        assert snapshot.git_state == "non_git"
        assert snapshot.symlinks == (".git", "broken", "outside-link.js")
        assert [module.logical_path for module in snapshot.modules] == ["app.js"]
        with store.read_connection() as connection:
            assert [tuple(row) for row in connection.execute(
                "SELECT logical_path, entry_kind, size_bytes, content_sha256 "
                "FROM project_file_index ORDER BY logical_path"
            )] == [
                (".git", "symlink", None, None),
                ("app.js", "javascript_module", 24, hashlib.sha256(b"export const value = 1;\n").hexdigest()),
                ("broken", "symlink", None, None),
                ("outside-link.js", "symlink", None, None),
            ]

    with _sandbox() as base:
        source = base / "source"
        real_child = base / "child"
        source.mkdir()
        real_child.mkdir()
        (source / "linked-child").symlink_to(real_child, target_is_directory=True)
        store = _store(base)
        _add_root(store, "root", source)
        _assert_code(
            "source_scope_symlink_forbidden",
            lambda: JavascriptSourceService(store).ensure_owner(
                "root", "linked-child"
            ),
        )


def test_scan_handles_large_nonbuild_tree_prunes_and_never_writes_source_or_formal_tables() -> None:
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        for index in range(805):
            (source / f"note-{index:04d}.txt").write_text("ignored", encoding="utf-8")
        (source / "quote.js").write_text("export const quote = 20;\n", encoding="utf-8")
        for dirname in javascript_source._PRUNED_DIRECTORIES - {".git"}:
            directory = source / dirname
            directory.mkdir()
            (directory / "hidden.js").write_text("fetch('https://invalid');", encoding="utf-8")
        before_tree = _tree_digest(source)
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        formal_before = _formal_counts(store)

        snapshot = service.scan(project_id)
        summary_text = json.dumps(snapshot.safe_summary(), sort_keys=True)

        assert isinstance(snapshot, JavascriptScopeSnapshot)
        assert snapshot.status == "completed"
        assert [module.logical_path for module in snapshot.modules] == ["quote.js"]
        assert snapshot.modules[0].content == b"export const quote = 20;\n"
        assert "export const quote = 20" not in repr(snapshot.modules[0])
        assert "content=" not in repr(snapshot.modules[0])
        assert "export const quote = 20" not in repr(snapshot)
        assert "modules=" not in repr(snapshot)
        assert "export const" not in summary_text
        assert str(source) not in summary_text
        assert _tree_digest(source) == before_tree
        assert _formal_counts(store) == formal_before == {
            "intake_runs": 0,
            "review_items": 0,
            "capability_groups": 0,
            "capsules": 0,
            "capsule_versions": 0,
            "capsule_sources": 0,
            "capsule_assets": 0,
            "capsule_status_events": 0,
            "product_capsule_usage": 0,
            "legacy_capsule_aliases": 0,
        }


def test_digest_contract_sorting_and_mtime_independence() -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks are unavailable")
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        a_bytes = b"export const a = 1;\n"
        z_bytes = b"export const z = 2;\n"
        (source / "z.mjs").write_bytes(z_bytes)
        (source / "a.js").write_bytes(a_bytes)
        try:
            (source / "link").symlink_to("missing")
        except OSError:
            pytest.skip("symlink creation is not permitted")
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")

        first = service.scan(project_id)
        expected_entries = [
            {
                "path": "a.js",
                "kind": "javascript_module",
                "size": len(a_bytes),
                "sha256": hashlib.sha256(a_bytes).hexdigest(),
            },
            {"path": "link", "kind": "symlink", "size": None, "sha256": None},
            {
                "path": "z.mjs",
                "kind": "javascript_module",
                "size": len(z_bytes),
                "sha256": hashlib.sha256(z_bytes).hexdigest(),
            },
        ]
        assert first.file_index_digest == _canonical_sha256(
            {"version": "project_file_index.v1", "entries": expected_entries}
        )
        assert first.scope_snapshot_sha256 == _canonical_sha256(
            {
                "version": "javascript_scope_snapshot.v1",
                "javascript_modules": [
                    {"path": row["path"], "size": row["size"], "sha256": row["sha256"]}
                    for row in (expected_entries[0], expected_entries[2])
                ],
                "symlinks": [{"path": "link"}],
            }
        )
        original = (source / "a.js").stat()
        os.utime(source / "a.js", ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000))
        second = service.scan(project_id)
        assert second.status == "no_change"
        assert second.file_index_digest == first.file_index_digest
        assert second.source_identity_sha256 == first.source_identity_sha256


def test_parent_scan_excludes_registered_static_and_javascript_descendants() -> None:
    with _sandbox() as base:
        source = base / "source"
        child = source / "child"
        source.mkdir()
        child.mkdir()
        (source / "root.js").write_text("export const root = 1;\n", encoding="utf-8")
        (child / "child.js").write_text("export const child = 1;\n", encoding="utf-8")
        (child / "index.html").write_text("<main></main>", encoding="utf-8")
        store = _store(base)
        _add_root(store, "root", source)
        service, parent_id = _owner(store, "root")
        first = service.scan(parent_id)
        assert [module.logical_path for module in first.modules] == [
            "child/child.js",
            "root.js",
        ]

        _add_project(
            store,
            project_id="static-child",
            root_id="root",
            source_type="static_web",
            project_relpath="child",
            entry_relpath="index.html",
        )
        child_owner = service.ensure_owner("root", "child")
        assert child_owner["created"] is True
        assert _index_state(store, parent_id)[1] == []

        rescanned = service.scan(parent_id)
        assert [module.logical_path for module in rescanned.modules] == ["root.js"]


def test_physical_parent_detection_handles_case_aliases_when_supported() -> None:
    with _sandbox() as base:
        source = base / "Source"
        alias = base / "source"
        child = source / "Child"
        source.mkdir()
        child.mkdir()
        if not alias.is_dir() or javascript_source._physical_key(alias) != javascript_source._physical_key(source):
            pytest.skip("filesystem is case-sensitive")
        (source / "root.js").write_text("export const root = 1;\n", encoding="utf-8")
        (child / "child.js").write_text("export const child = 1;\n", encoding="utf-8")
        store = _store(base)
        _add_root(store, "canonical", source)
        _add_root(store, "alias", alias)
        service, parent_id = _owner(store, "canonical")
        service.scan(parent_id)

        child_owner = service.ensure_owner("alias", "Child")

        assert child_owner["created"] is True
        assert _index_state(store, parent_id)[1] == []
        rescanned = service.scan(parent_id)
        assert [module.logical_path for module in rescanned.modules] == ["root.js"]


def test_unrelated_historical_symlink_owner_does_not_block_valid_scope() -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks are unavailable")
    with _sandbox() as base:
        source = base / "source"
        unrelated = base / "unrelated"
        linked = base / "linked"
        source.mkdir()
        unrelated.mkdir()
        try:
            linked.symlink_to(unrelated, target_is_directory=True)
        except OSError:
            pytest.skip("symlink creation is not permitted")
        (source / "valid.js").write_text("export const valid = 1;\n", encoding="utf-8")
        store = _store(base)
        _add_root(store, "valid-root", source)
        _add_root(store, "invalid-root", linked)
        _add_project(
            store,
            project_id="invalid-owner",
            root_id="invalid-root",
            source_type="javascript_computation_source",
        )
        service, valid_id = _owner(store, "valid-root")

        snapshot = service.scan(valid_id)

        assert [module.logical_path for module in snapshot.modules] == ["valid.js"]
        _assert_code(
            "source_scope_symlink_forbidden",
            lambda: service.scan("invalid-owner"),
        )


@pytest.mark.parametrize(
    ("limit_name", "limit_value", "fixture_kind"),
    [
        ("MAX_DIRECTORY_ENTRIES", 1, "entries"),
        ("MAX_JAVASCRIPT_MODULES", 1, "modules"),
        ("MAX_JAVASCRIPT_BYTES", 1, "bytes"),
        ("MAX_JAVASCRIPT_FILE_BYTES", 1, "file"),
        ("MAX_DIRECTORY_DEPTH", 0, "depth"),
        ("SCAN_TIMEOUT_SECONDS", -1.0, "timeout"),
    ],
)
def test_every_resource_limit_fails_closed_and_preserves_old_index(
    limit_name: str, limit_value: int | float, fixture_kind: str
) -> None:
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        (source / "a.js").write_text("export const a = 1;\n", encoding="utf-8")
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        service.scan(project_id)
        old_state = _index_state(store, project_id)

        if fixture_kind == "entries":
            (source / "extra.txt").write_text("x", encoding="utf-8")
        elif fixture_kind == "modules":
            (source / "b.js").write_text("export const b = 2;\n", encoding="utf-8")
        elif fixture_kind == "depth":
            (source / "nested").mkdir()
        with patch.object(javascript_source, limit_name, limit_value):
            _assert_code(
                "source_scope_limit_exceeded", lambda: service.scan(project_id)
            )
        assert _index_state(store, project_id) == old_state


def test_exact_resource_boundaries_pass() -> None:
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        content = b"x"
        (source / "a.js").write_bytes(content)
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        with (
            patch.object(javascript_source, "MAX_DIRECTORY_ENTRIES", 1),
            patch.object(javascript_source, "MAX_JAVASCRIPT_MODULES", 1),
            patch.object(javascript_source, "MAX_JAVASCRIPT_BYTES", 1),
            patch.object(javascript_source, "MAX_JAVASCRIPT_FILE_BYTES", 1),
            patch.object(javascript_source, "MAX_DIRECTORY_DEPTH", 0),
        ):
            snapshot = service.scan(project_id)
        assert snapshot.status == "completed"
        assert snapshot.modules[0].content == content


def test_source_change_cancel_and_crash_never_replace_old_index() -> None:
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        module = source / "a.js"
        module.write_text("export const a = 1;\n", encoding="utf-8")
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        service.scan(project_id)
        old_state = _index_state(store, project_id)
        real_capture = javascript_source._capture_snapshot
        calls = 0

        def changing_capture(*args: object, **kwargs: object) -> object:
            nonlocal calls
            calls += 1
            result = real_capture(*args, **kwargs)
            if calls == 1:
                module.write_text("export const a = 2;\n", encoding="utf-8")
            return result

        with patch.object(javascript_source, "_capture_snapshot", changing_capture):
            _assert_code("source_changed", lambda: service.scan(project_id))
        assert _index_state(store, project_id) == old_state

        cancel = threading.Event()
        cancel.set()
        _assert_code(
            "scan_cancelled", lambda: service.scan(project_id, cancel_event=cancel)
        )
        assert _index_state(store, project_id) == old_state

        calls = 0

        def crashing_capture(*args: object, **kwargs: object) -> object:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("fault injection")
            return real_capture(*args, **kwargs)

        with patch.object(javascript_source, "_capture_snapshot", crashing_capture):
            with pytest.raises(RuntimeError, match="fault injection"):
                service.scan(project_id)
        assert _index_state(store, project_id) == old_state


def test_change_after_git_evidence_still_invalidates_final_snapshot() -> None:
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        module = source / "a.js"
        module.write_text("export const a = 1;\n", encoding="utf-8")
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        service.scan(project_id)
        old_state = _index_state(store, project_id)
        real_git_evidence = javascript_source._read_git_evidence
        calls = 0

        def changing_git_evidence(*args: object, **kwargs: object) -> object:
            nonlocal calls
            calls += 1
            result = real_git_evidence(*args, **kwargs)
            if calls == 2:
                module.write_text("export const a = 2;\n", encoding="utf-8")
            return result

        with patch.object(
            javascript_source, "_read_git_evidence", changing_git_evidence
        ):
            _assert_code("source_changed", lambda: service.scan(project_id))
        assert _index_state(store, project_id) == old_state


def test_non_javascript_change_between_final_git_and_snapshot_is_rejected() -> None:
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        (source / "a.js").write_text("export const a = 1;\n", encoding="utf-8")
        _git(source, "init", "-q")
        _git(source, "add", "a.js")
        _git(source, "commit", "-q", "-m", "fixture")
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        service.scan(project_id)
        old_state = _index_state(store, project_id)
        real_capture = javascript_source._capture_snapshot
        calls = 0

        def changing_final_snapshot(*args: object, **kwargs: object) -> object:
            nonlocal calls
            calls += 1
            if calls == 4:
                (source / "note.txt").write_text("changed\n", encoding="utf-8")
            return real_capture(*args, **kwargs)

        with patch.object(
            javascript_source, "_capture_snapshot", changing_final_snapshot
        ):
            _assert_code("source_changed", lambda: service.scan(project_id))
        assert _index_state(store, project_id) == old_state


def test_javascript_change_after_final_git_sample_invalidates_source_snapshot() -> None:
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        module = source / "a.js"
        module.write_text("export const a = 1;\n", encoding="utf-8")
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        service.scan(project_id)
        old_state = _index_state(store, project_id)
        real_git_evidence = javascript_source._read_git_evidence
        calls = 0

        def changing_git_evidence(*args: object, **kwargs: object) -> object:
            nonlocal calls
            calls += 1
            result = real_git_evidence(*args, **kwargs)
            if calls == 3:
                module.write_text("export const a = 2;\n", encoding="utf-8")
            return result

        with patch.object(
            javascript_source, "_read_git_evidence", changing_git_evidence
        ):
            _assert_code("source_changed", lambda: service.scan(project_id))
        assert _index_state(store, project_id) == old_state


def test_same_project_scan_lock_rejects_parallel_refresh() -> None:
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        (source / "a.js").write_text("export const a = 1;\n", encoding="utf-8")
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        started = threading.Event()
        release = threading.Event()
        real_capture = javascript_source._capture_snapshot
        calls = 0

        def blocking_capture(*args: object, **kwargs: object) -> object:
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                assert release.wait(timeout=10)
            return real_capture(*args, **kwargs)

        with patch.object(javascript_source, "_capture_snapshot", blocking_capture):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(service.scan, project_id)
                assert started.wait(timeout=10)
                _assert_code(
                    "scan_already_running", lambda: service.scan(project_id)
                )
                release.set()
                assert future.result(timeout=10).status == "completed"


def test_path_validation_and_collision_rules_fail_closed() -> None:
    for pair in (
        ("A/x.js", "a/x.js"),
        ("é.js", "e\u0301.js"),
        ("Straße.js", "STRASSE.js"),
    ):
        seen: tuple[set[str], ...] = (set(), set(), set(), set())
        javascript_source._register_path(pair[0], seen)
        _assert_code(
            "source_path_normalization_conflict",
            lambda pair=pair, seen=seen: javascript_source._register_path(pair[1], seen),
        )
    for invalid in (
        "/absolute.js",
        "a\\b.js",
        "a//b.js",
        "a/./b.js",
        "a/../b.js",
        "newline\n.js",
        "trailing/",
        "\udcff.js",
    ):
        _assert_code(
            "source_path_normalization_conflict",
            lambda invalid=invalid: javascript_source._validate_logical_path(invalid),
        )

    if os.name == "nt":
        return
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        (source / "bad\\name.js").write_text("x", encoding="utf-8")
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        _assert_code(
            "source_path_normalization_conflict", lambda: service.scan(project_id)
        )


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_scope_resolution_rejects_directory_to_symlink_swap() -> None:
    with _sandbox() as base:
        root = base / "root"
        child = root / "child"
        outside = base / "outside"
        root.mkdir()
        child.mkdir()
        outside.mkdir()
        original_identity = javascript_source._path_chain_identity
        swapped = False

        def swap_after_identity(
            path: Path, *, require_exists: bool
        ) -> tuple[tuple[str, int, int], ...]:
            nonlocal swapped
            identity = original_identity(path, require_exists=require_exists)
            if Path(path) == child and not swapped:
                saved = root / "saved-child"
                child.rename(saved)
                try:
                    child.symlink_to(outside, target_is_directory=True)
                except OSError:
                    pytest.skip("symlink creation is not permitted")
                swapped = True
            return identity

        with patch.object(
            javascript_source, "_path_chain_identity", swap_after_identity
        ):
            _assert_code(
                "source_scope_symlink_forbidden",
                lambda: javascript_source._physical_scope(
                    str(root), "child", require_exists=True
                ),
            )


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_scope_resolution_rejects_root_symlink_aba_and_preserves_index() -> None:
    with _sandbox() as base:
        source = base / "source"
        outside = base / "outside"
        source.mkdir()
        outside.mkdir()
        (source / "inside.js").write_text(
            "export const inside = 1;\n", encoding="utf-8"
        )
        (outside / "outside.js").write_text(
            "export const outside = 1;\n", encoding="utf-8"
        )
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        service.scan(project_id)
        old_state = _index_state(store, project_id)
        real_resolve = Path.resolve
        swapped = False

        def resolve_during_aba(path: Path, strict: bool = False) -> Path:
            nonlocal swapped
            if path == source and not swapped:
                saved = base / "saved-source"
                source.rename(saved)
                try:
                    source.symlink_to(outside, target_is_directory=True)
                except OSError:
                    saved.rename(source)
                    pytest.skip("symlink creation is not permitted")
                try:
                    escaped = real_resolve(source, strict=strict)
                finally:
                    source.unlink()
                    saved.rename(source)
                swapped = True
                return escaped
            return real_resolve(path, strict=strict)

        with patch.object(Path, "resolve", resolve_during_aba):
            _assert_code("source_changed", lambda: service.scan(project_id))

        assert _index_state(store, project_id) == old_state
        assert [row[0] for row in old_state[1]] == ["inside.js"]


@pytest.mark.skipif(
    not javascript_source._descriptor_relative_snapshot_supported(),
    reason="descriptor-relative snapshot primitives are unavailable",
)
@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_snapshot_parent_symlink_aba_never_reads_outside_scope() -> None:
    with _sandbox() as base:
        source = base / "source"
        child = source / "child"
        outside = base / "outside"
        child.mkdir(parents=True)
        outside.mkdir()
        inside_bytes = b'export const value = "inside";\n'
        outside_bytes = b'export const value = "OUTSIDE_SENTINEL";\n'
        (child / "value.js").write_bytes(inside_bytes)
        (outside / "value.js").write_bytes(outside_bytes)
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        service.scan(project_id)
        old_state = _index_state(store, project_id)
        real_read = javascript_source._read_regular_file_at
        observed: list[bytes] = []
        swapped = False

        def swap_parent_before_read(
            directory_fd: int,
            name: str,
            *,
            expected: os.stat_result,
            cancel_event: threading.Event | None,
            deadline: float,
        ) -> bytes:
            nonlocal swapped
            if name != "value.js" or swapped:
                return real_read(
                    directory_fd,
                    name,
                    expected=expected,
                    cancel_event=cancel_event,
                    deadline=deadline,
                )
            swapped = True
            saved = source / "saved-child"
            child.rename(saved)
            try:
                child.symlink_to(outside, target_is_directory=True)
            except OSError:
                saved.rename(child)
                pytest.skip("symlink creation is not permitted")
            try:
                content = real_read(
                    directory_fd,
                    name,
                    expected=expected,
                    cancel_event=cancel_event,
                    deadline=deadline,
                )
                observed.append(content)
                return content
            finally:
                child.unlink()
                saved.rename(child)

        with patch.object(
            javascript_source, "_read_regular_file_at", swap_parent_before_read
        ):
            _assert_code("source_changed", lambda: service.scan(project_id))

        assert observed == [inside_bytes]
        assert outside_bytes not in observed
        assert _index_state(store, project_id) == old_state


def test_snapshot_fails_closed_without_descriptor_relative_primitives() -> None:
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        (source / "value.js").write_text(
            "export const value = 1;\n", encoding="utf-8"
        )
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        old_state = _index_state(store, project_id)

        with patch.object(
            javascript_source,
            "_descriptor_relative_snapshot_supported",
            return_value=False,
        ), patch.object(
            javascript_source,
            "_open_root_directory",
            side_effect=AssertionError("source directory must not be opened"),
        ), patch.object(
            javascript_source,
            "_read_git_evidence",
            side_effect=AssertionError("git evidence must not be read"),
        ):
            _assert_code(
                "source_platform_unsupported_v1", lambda: service.scan(project_id)
            )
        assert _index_state(store, project_id) == old_state


@pytest.mark.skipif(
    not javascript_source._descriptor_relative_snapshot_supported(),
    reason="descriptor-relative snapshot primitives are unavailable",
)
@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is POSIX-only")
def test_regular_file_to_fifo_race_fails_without_blocking() -> None:
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        module = source / "value.js"
        original = b"export const value = 1;\n"
        module.write_bytes(original)
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        service.scan(project_id)
        old_state = _index_state(store, project_id)
        real_read = javascript_source._read_regular_file_at
        swapped = False

        def replace_with_fifo(
            directory_fd: int,
            name: str,
            *,
            expected: os.stat_result,
            cancel_event: threading.Event | None,
            deadline: float,
        ) -> bytes:
            nonlocal swapped
            if name != "value.js" or swapped:
                return real_read(
                    directory_fd,
                    name,
                    expected=expected,
                    cancel_event=cancel_event,
                    deadline=deadline,
                )
            swapped = True
            module.unlink()
            os.mkfifo(module)
            try:
                return real_read(
                    directory_fd,
                    name,
                    expected=expected,
                    cancel_event=cancel_event,
                    deadline=deadline,
                )
            finally:
                module.unlink()
                module.write_bytes(original)

        started = time.monotonic()
        with patch.object(
            javascript_source, "_read_regular_file_at", replace_with_fifo
        ):
            _assert_code("source_changed", lambda: service.scan(project_id))
        assert time.monotonic() - started < 2
        assert _index_state(store, project_id) == old_state


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is POSIX-only")
def test_javascript_special_file_is_rejected_without_opening_it() -> None:
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        os.mkfifo(source / "blocked.js")
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")

        started = time.monotonic()
        _assert_code("source_unavailable", lambda: service.scan(project_id))
        assert time.monotonic() - started < 2


def test_git_identity_is_scope_limited_structured_and_read_only() -> None:
    with _sandbox() as base:
        repository = base / "repository"
        selected = repository / "selected"
        selected.mkdir(parents=True)
        (selected / "quote.js").write_text("export const quote = 20;\n", encoding="utf-8")
        (repository / "outside.txt").write_text("outside", encoding="utf-8")
        _git(repository, "init", "-q")
        _git(repository, "add", "selected/quote.js", "outside.txt")
        _git(repository, "commit", "-q", "-m", "fixture")
        commit = _git(repository, "rev-parse", "HEAD")
        git_index = repository / ".git" / "index"
        index_before = (git_index.read_bytes(), git_index.stat().st_mtime_ns)
        source_before = _tree_digest(repository)

        store = _store(base)
        _add_root(store, "root", repository)
        service, project_id = _owner(store, "root", "selected")
        clean = service.scan(project_id)
        assert clean.git_state == "clean_git"
        assert clean.git_commit == commit
        assert clean.git_status_sha256 == _canonical_sha256(
            {"version": "git_status_contract.v1", "entries": []}
        )
        assert (git_index.read_bytes(), git_index.stat().st_mtime_ns) == index_before
        assert _tree_digest(repository) == source_before

        (repository / "outside-new.txt").write_text("outside only", encoding="utf-8")
        outside_dirty = service.scan(project_id)
        assert outside_dirty.status == "no_change"
        assert outside_dirty.source_identity_sha256 == clean.source_identity_sha256

        (selected / "quote.js").write_text("export const quote = 21;\n", encoding="utf-8")
        dirty = service.scan(project_id)
        assert dirty.git_state == "dirty_git"
        assert dirty.git_commit == commit
        assert dirty.git_status_sha256 != clean.git_status_sha256


def test_git_identity_excludes_registered_child_project_changes() -> None:
    with _sandbox() as base:
        repository = base / "repository"
        child = repository / "child"
        child.mkdir(parents=True)
        (repository / "root.js").write_text("export const root = 1;\n", encoding="utf-8")
        (child / "child.js").write_text("export const child = 1;\n", encoding="utf-8")
        (child / "index.html").write_text("<main></main>", encoding="utf-8")
        _git(repository, "init", "-q")
        _git(repository, "add", "root.js", "child/child.js", "child/index.html")
        _git(repository, "commit", "-q", "-m", "fixture")
        store = _store(base)
        _add_root(store, "root", repository)
        service, parent_id = _owner(store, "root")
        service.scan(parent_id)
        _add_project(
            store,
            project_id="static-child",
            root_id="root",
            source_type="static_web",
            project_relpath="child",
            entry_relpath="index.html",
        )
        clean_boundary = service.scan(parent_id)
        assert [module.logical_path for module in clean_boundary.modules] == ["root.js"]

        (child / "child.js").write_text("export const child = 2;\n", encoding="utf-8")
        after_child_change = service.scan(parent_id)

        assert after_child_change.status == "no_change"
        assert after_child_change.git_state == "clean_git"
        assert (
            after_child_change.source_identity_sha256
            == clean_boundary.source_identity_sha256
        )


@pytest.mark.skipif(
    not Path("/usr/bin/touch").is_file(), reason="fsmonitor injection probe is POSIX-only"
)
def test_git_local_fsmonitor_and_git_environment_cannot_execute_or_redirect() -> None:
    with _sandbox() as base:
        repository = base / "repository"
        redirected = base / "redirected"
        repository.mkdir()
        redirected.mkdir()
        (repository / "quote.js").write_text("export const quote = 20;\n", encoding="utf-8")
        (redirected / "other.js").write_text("export const other = 1;\n", encoding="utf-8")
        _git(repository, "init", "-q")
        _git(repository, "add", "quote.js")
        _git(repository, "commit", "-q", "-m", "fixture")
        _git(repository, "config", "core.fsmonitor", "/usr/bin/touch")
        _git(redirected, "init", "-q")
        before = _tree_digest(repository)

        store = _store(base)
        _add_root(store, "root", repository)
        service, project_id = _owner(store, "root")
        with patch.dict(
            os.environ,
            {"GIT_DIR": str(redirected / ".git"), "GIT_WORK_TREE": str(redirected)},
        ):
            snapshot = service.scan(project_id)

        assert snapshot.git_state == "clean_git"
        assert [module.logical_path for module in snapshot.modules] == ["quote.js"]
        assert _tree_digest(repository) == before


@pytest.mark.skipif(os.name == "nt", reason="executable PATH probe is POSIX-only")
def test_git_executable_is_never_resolved_from_the_source_repository() -> None:
    real_git = shutil.which("git")
    if real_git is None:
        pytest.skip("git is required for this fixture")
    with _sandbox() as base:
        repository = base / "repository"
        fake_bin = repository / "tools"
        repository.mkdir()
        fake_bin.mkdir()
        (repository / "quote.js").write_text(
            "export const quote = 20;\n", encoding="utf-8"
        )
        _git(repository, "init", "-q")
        _git(repository, "add", "quote.js")
        _git(repository, "commit", "-q", "-m", "fixture")
        marker = base / "source-git-executed"
        fake_git = fake_bin / "git"
        fake_git.write_text(
            f"#!/bin/sh\nprintf executed > '{marker}'\nexit 1\n",
            encoding="utf-8",
        )
        fake_git.chmod(0o755)
        store = _store(base)
        _add_root(store, "root", repository)
        service, project_id = _owner(store, "root")

        trusted_path = os.pathsep.join((str(fake_bin), str(Path(real_git).parent)))
        with patch.dict(os.environ, {"PATH": trusted_path}):
            snapshot = service.scan(project_id)
        assert snapshot.git_commit == _git(repository, "rev-parse", "HEAD")
        assert not marker.exists()

        with patch.dict(os.environ, {"PATH": str(fake_bin)}):
            _assert_code("source_unavailable", lambda: service.scan(project_id))
        assert not marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="Git clean-filter probe is POSIX-only")
def test_git_status_never_executes_repository_clean_filters() -> None:
    with _sandbox() as base:
        repository = base / "repository"
        repository.mkdir()
        module = repository / "quote.js"
        module.write_text("export const quote = 20;\n", encoding="utf-8")
        _git(repository, "init", "-q")
        _git(repository, "add", "quote.js")
        _git(repository, "commit", "-q", "-m", "fixture")
        marker = base / "clean-filter-executed"
        clean_filter = base / "clean-filter"
        clean_filter.write_text(
            f"#!/bin/sh\nprintf executed > '{marker}'\n/bin/cat\n",
            encoding="utf-8",
        )
        clean_filter.chmod(0o755)
        _git(repository, "config", "filter.audit.clean", str(clean_filter))
        (repository / ".gitattributes").write_text(
            "*.js filter=audit\n", encoding="utf-8"
        )
        (repository / ".git" / "info" / "attributes").write_text(
            "*.js filter=audit\n", encoding="utf-8"
        )
        module.write_text("export const quote = 21;\n", encoding="utf-8")
        store = _store(base)
        _add_root(store, "root", repository)
        service, project_id = _owner(store, "root")

        snapshot = service.scan(project_id)

        assert snapshot.git_state == "dirty_git"
        assert not marker.exists()


def test_git_status_pathspec_prunes_untracked_build_trees_before_output_limit() -> None:
    with _sandbox() as base:
        repository = base / "repository"
        pruned = repository / "node_modules"
        repository.mkdir()
        pruned.mkdir()
        (repository / "quote.js").write_text(
            "export const quote = 20;\n", encoding="utf-8"
        )
        _git(repository, "init", "-q")
        _git(repository, "add", "quote.js")
        _git(repository, "commit", "-q", "-m", "fixture")
        for index in range(100):
            (pruned / f"ignored-{index:03d}.txt").write_text(
                "ignored", encoding="utf-8"
            )
        store = _store(base)
        _add_root(store, "root", repository)
        service, project_id = _owner(store, "root")

        with patch.object(javascript_source, "MAX_GIT_STATUS_BYTES", 256):
            snapshot = service.scan(project_id)

        assert snapshot.git_state == "clean_git"
        assert [module.logical_path for module in snapshot.modules] == ["quote.js"]


def test_git_status_parser_rejects_malformed_records_and_sorts_safe_tuples() -> None:
    parsed = javascript_source._parse_git_status(
        b"?? z file.js\0 M a.js\0", scope_prefix="."
    )
    assert parsed == [
        {"status": " M", "path": "a.js"},
        {"status": "??", "path": "z file.js"},
    ]
    for raw in (
        b"?? missing-null",
        b"? short\0",
        b"!! ignored.js\0",
        b"R  renamed.js\0",
        b"?? ../escape.js\0",
        b"?? bad\xff.js\0",
        b"?? duplicate.js\0?? duplicate.js\0",
    ):
        _assert_code(
            "source_path_normalization_conflict",
            lambda raw=raw: javascript_source._parse_git_status(raw, scope_prefix="."),
        )
    with patch.object(javascript_source, "MAX_DIRECTORY_ENTRIES", 1):
        _assert_code(
            "source_scope_limit_exceeded",
            lambda: javascript_source._parse_git_status(
                b"?? one.js\0?? two.js\0", scope_prefix="."
            ),
        )
        assert javascript_source._parse_git_status(
            b"?? node_modules/ignored.js\0"
            b"?? registered-child/ignored.js\0"
            b"?? kept.js\0",
            scope_prefix=".",
            exclusion_relpaths=("registered-child",),
        ) == [{"status": "??", "path": "kept.js"}]
    cancelled = threading.Event()
    cancelled.set()
    _assert_code(
        "scan_cancelled",
        lambda: javascript_source._parse_git_status(
            b"?? one.js\0", scope_prefix=".", cancel_event=cancelled
        ),
    )


def test_scan_result_is_immutable_and_non_git_identity_is_canonical() -> None:
    with _sandbox() as base:
        source = base / "source"
        source.mkdir()
        content = b"export const value = 1;\n"
        (source / "value.js").write_bytes(content)
        store = _store(base)
        _add_root(store, "root", source)
        service, project_id = _owner(store, "root")
        snapshot = service.scan(project_id)

        assert snapshot.git_state == "non_git"
        assert snapshot.git_commit is None
        assert snapshot.git_status_sha256 is None
        assert snapshot.source_identity_sha256 == _canonical_sha256(
            {
                "version": "javascript_source_identity.v1",
                "scope_snapshot_sha256": snapshot.scope_snapshot_sha256,
                "git_state": "non_git",
                "commit": None,
                "status_sha256": None,
            }
        )
        with pytest.raises(Exception):
            snapshot.status = "forged"  # type: ignore[misc]
        assert snapshot.modules[0].content == content
