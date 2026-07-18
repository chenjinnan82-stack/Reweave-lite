"""Non-active Stage 2 source discovery and atomic-candidate intake."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit

from pimos_lite.reweave_capsule_store import (
    BACKUP_DIRECTORY,
    CANONICALIZATION_VERSION,
    TARGET_SCHEMA_VERSION,
    CapsuleWarehouseStore,
)
from pimos_lite.reweave_data_contract import (
    MAX_SAFE_INTEGER,
    DataContractError,
    generate_synthetic_fixtures,
    normalize_capsule_contracts,
)
from pimos_lite.reweave_process_environment import restricted_subprocess_environment
from pimos_lite.reweave_source_registry import state_dir


EXTRACTION_CONTRACT_VERSION = "extraction_contract.v2"
COMPUTATION_ADAPTER_CONTRACT_VERSION = "computation_adapter.v1"
COMPUTATION_ADAPTER_ENTRY = "__reweave_adapter__/compute.js"
REDACTION_RULES_VERSION = "redaction_rules.v1"
SECURITY_RULES_VERSION = "not_run.stage2"
SUPERVISION_RULES_VERSION = "not_run.stage2"
VALIDATION_CONTRACT_VERSION = "not_run.stage2"

MAX_FILES = 800
MAX_DEPTH = 8
MAX_FILE_SIZE = 1024 * 1024
MAX_SUPPORTED_BYTES = 64 * 1024 * 1024
MAX_JAVASCRIPT_SNAPSHOT_BYTES = 16 * 1024 * 1024
_TEXT_SUFFIXES = frozenset({".html", ".css", ".js", ".mjs"})
_ASSET_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".next",
        ".turbo",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
        "vendor",
        "venv",
    }
)
_SENSITIVITY_DECISIONS = frozenset(
    {
        "confirm_fictional_fixture",
        "confirm_safe_redaction",
        "confirm_real_record_reject",
    }
)
_BRAND_DECISIONS = frozenset({"remove_brand", "retain_brand_limited"})
_ASSET_DECISIONS = frozenset({"confirm_assets_contain_no_real_records"})
_ENUM_DECISIONS = frozenset({"confirm_selected_string_enumeration"})
_SECRET = re.compile(
    r"(?is)(?:api[_-]?key|secret|password|access[_-]?key|secret[_-]?key)\s*['\"]?\s*[:=]\s*"
    r"(?:['\"][^'\"]+['\"]|[^\s<;]+)|Bearer\s+[A-Za-z0-9\-._~+/]+=*|"
    r"\bsk-[A-Za-z0-9]{8,}\b|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_RECORD = re.compile(
    r"(?is)\b(?:customer|client|person|employee|patient|order|account|address|phone|email)"
    r"(?:[_-]?(?:id|name|number))?\b\s*[:=]\s*['\"][^'\"]+['\"]"
)
_ACTIVE_PROJECTS: set[str] = set()
_ACTIVE_PROJECTS_LOCK = threading.Lock()
_ADAPTER_MEMBER = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z")


class IntakeError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SnapshotEntry:
    path: str
    file_type: str
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class ProjectSnapshot:
    digest: str
    entries: tuple[SnapshotEntry, ...]
    text: dict[str, str]


@dataclass(frozen=True)
class ProjectContext:
    project: dict[str, Any]
    source_root: dict[str, Any]
    path: Path
    excluded_relpaths: tuple[str, ...]


class _HtmlInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[dict[str, Any]] = []
        self.stack: list[int] = []
        self.scripts: list[tuple[str, str]] = []
        self.stylesheets: list[str] = []
        self.resources: list[str] = []
        self.inline_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        parent = self.stack[-1] if self.stack else None
        index = len(self.nodes)
        self.nodes.append({"tag": tag.lower(), "attrs": values, "parent": parent})
        if tag.lower() not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}:
            self.stack.append(index)
        if tag.lower() == "script":
            source = values.get("src", "").strip()
            if source:
                self.scripts.append((values.get("type", "").strip().lower(), source))
            else:
                self.inline_script = True
        if tag.lower() == "link" and "stylesheet" in values.get("rel", "").lower() and values.get("href"):
            self.stylesheets.append(values["href"].strip())
        resource_names = ()
        if tag.lower() in {"audio", "img", "input", "source", "video"}:
            resource_names = ("src", "poster")
        for name in resource_names:
            if values.get(name):
                self.resources.append(values[name].strip())

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack and self.nodes[self.stack[-1]]["tag"] == tag.lower():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.nodes[self.stack[index]]["tag"] == tag:
                del self.stack[index:]
                return

    def static_root(self) -> int | None:
        explicit = [index for index, node in enumerate(self.nodes) if "data-capsule-root" in node["attrs"]]
        if explicit:
            return explicit[0] if len(explicit) == 1 else None
        mains = [index for index, node in enumerate(self.nodes) if node["tag"] == "main"]
        if len(mains) == 1:
            return mains[0]
        forms = [index for index, node in enumerate(self.nodes) if node["tag"] == "form"]
        return forms[0] if len(forms) == 1 else None

    def selector_contracts(self) -> tuple[list[str], dict[str, dict[str, Any]], str | None]:
        root = self.static_root()
        if root is None:
            return [], {}, None
        selectors: set[str] = set()
        controls: dict[str, dict[str, Any]] = {}
        for index, node in enumerate(self.nodes):
            if index != root and not self._is_descendant(index, root):
                continue
            attrs = node["attrs"]
            node_selectors: list[str] = []
            if attrs.get("id"):
                node_selectors.append(f"#{attrs['id']}")
            for name in ("data-ref", "data-action"):
                if attrs.get(name):
                    node_selectors.extend(
                        [f"[{name}='{attrs[name]}']", f'[{name}="{attrs[name]}"]']
                    )
            selectors.update(node_selectors)
            contract = self._control_contract(node["tag"], attrs)
            if contract:
                for selector in node_selectors:
                    controls[selector] = contract
        root_node = self.nodes[root]
        root_selector = (
            f"#{root_node['attrs']['id']}"
            if root_node["attrs"].get("id")
            else root_node["tag"]
        )
        return sorted(selectors), controls, root_selector

    def _is_descendant(self, index: int, ancestor: int) -> bool:
        parent = self.nodes[index]["parent"]
        while parent is not None:
            if parent == ancestor:
                return True
            parent = self.nodes[parent]["parent"]
        return False

    @staticmethod
    def _control_contract(tag: str, attrs: dict[str, str]) -> dict[str, Any] | None:
        if tag == "input" and attrs.get("type", "text").lower() == "checkbox":
            return {"checked_contract": {"type": "boolean"}}
        if tag == "input" and attrs.get("type", "text").lower() == "number":
            try:
                minimum = int(attrs["min"])
                maximum = int(attrs["max"])
                step = int(attrs.get("step", "1"))
            except (KeyError, ValueError):
                return None
            if step != 1 or minimum > maximum:
                return None
            return {
                "value_contract": {
                    "type": "integer",
                    "minimum": minimum,
                    "maximum": maximum,
                }
            }
        if tag in {"input", "textarea"}:
            try:
                minimum = int(attrs.get("minlength", "1" if "required" in attrs else "0"))
                maximum = int(attrs["maxlength"])
            except (KeyError, ValueError):
                return None
            if not 0 <= minimum <= maximum <= 10000:
                return None
            return {
                "value_contract": {
                    "type": "string",
                    "min_length": minimum,
                    "max_length": maximum,
                }
            }
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _uuid() -> str:
    return str(uuid.uuid4())


def _safe_relative(value: str) -> str:
    raw = value.replace("\\", "/")
    path_value = PurePosixPath(raw)
    if not raw or path_value.is_absolute() or any(part in {"", ".", ".."} for part in path_value.parts):
        raise IntakeError("source_relative_path_invalid")
    return path_value.as_posix()


def _local_reference(base_relpath: str, value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or value.startswith(("/", "//")) or parsed.query:
        raise IntakeError("static_closure_external_reference")
    if not parsed.path or parsed.path.startswith("#"):
        raise IntakeError("static_closure_reference_invalid")
    joined = PurePosixPath(base_relpath).parent.joinpath(parsed.path)
    return _safe_relative(joined.as_posix())


def _is_ignored_directory(name: str) -> bool:
    folded = name.casefold()
    return folded in _IGNORED_DIRS or folded.startswith(".venv")


@contextmanager
def _project_guard(project_id: str) -> Iterator[None]:
    # ponytail: the desktop has one process; add an OS lock only if multiple writers appear.
    with _ACTIVE_PROJECTS_LOCK:
        if project_id in _ACTIVE_PROJECTS:
            raise IntakeError("project_refresh_in_progress")
        _ACTIVE_PROJECTS.add(project_id)
    try:
        yield
    finally:
        with _ACTIVE_PROJECTS_LOCK:
            _ACTIVE_PROJECTS.discard(project_id)


class ReweaveCapsuleIntake:
    """One concrete Stage 2 application object; it is not wired into the current app."""

    def __init__(self, store: CapsuleWarehouseStore | None = None) -> None:
        self.store = store or CapsuleWarehouseStore()
        self._capture_decision_lock = threading.RLock()
        self._capture_decision_authorizations: dict[str, tuple[str, str]] = {}

    def _authorize_capture_review_decision(
        self, review_id: str, decision_binding_sha256: str
    ) -> str:
        if (
            type(review_id) is not str
            or not review_id
            or re.fullmatch(r"[0-9a-f]{64}", decision_binding_sha256 or "") is None
        ):
            raise IntakeError("capture_decision_rebuild_required")
        token = secrets.token_hex(32)
        with self._capture_decision_lock:
            self._capture_decision_authorizations[review_id] = (
                decision_binding_sha256,
                token,
            )
        return token

    def bind_source_root(
        self,
        source_path: str | Path,
        *,
        root_kind: str,
        brand_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if root_kind not in {"single_project", "project_collection"}:
            raise IntakeError("source_root_kind_invalid")
        source = Path(source_path).expanduser()
        if source.is_symlink() or not source.is_dir():
            raise IntakeError("source_root_not_directory")
        resolved = source.resolve()
        self._validate_source_root_path(resolved)
        profile = self._profile_fields(brand_profile, previous=None)
        root_id = _uuid()
        now = _now()
        with self.store.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM source_roots WHERE current_path = ?", (str(resolved),)
            ).fetchone():
                raise IntakeError("source_root_already_bound")
            self._reject_overlapping_source_root(connection, resolved)
            connection.execute(
                "INSERT INTO source_roots VALUES (?, ?, ?, 'bound', ?, ?, ?, ?, ?, ?)",
                (
                    root_id,
                    root_kind,
                    str(resolved),
                    profile["id"],
                    profile["json"],
                    profile["digest"],
                    profile["version"],
                    now,
                    now,
                ),
            )
            self.store.bump_revision(connection)
        return self.get_source_root(root_id)

    def get_source_root(self, root_id: str) -> dict[str, Any]:
        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM source_roots WHERE root_id = ?", (root_id,)
            ).fetchone()
        if row is None:
            raise IntakeError("source_root_not_found")
        return dict(row)

    def reconnect_source_root(self, root_id: str, source_path: str | Path) -> dict[str, Any]:
        source = Path(source_path).expanduser()
        if source.is_symlink() or not source.is_dir():
            raise IntakeError("source_root_not_directory")
        resolved = source.resolve()
        self._validate_source_root_path(resolved)
        now = _now()
        with self.store.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM source_roots WHERE current_path = ? AND root_id <> ?",
                (str(resolved), root_id),
            ).fetchone():
                raise IntakeError("source_root_already_bound")
            self._reject_overlapping_source_root(connection, resolved, exclude_root_id=root_id)
            changed = connection.execute(
                "UPDATE source_roots SET current_path = ?, status = 'bound', updated_at = ? "
                "WHERE root_id = ?",
                (str(resolved), now, root_id),
            ).rowcount
            if not changed:
                raise IntakeError("source_root_not_found")
            self.store.bump_revision(connection)
        return self.get_source_root(root_id)

    def set_root_brand_profile(
        self, root_id: str, brand_profile: dict[str, Any] | None
    ) -> dict[str, Any]:
        current = self.get_source_root(root_id)
        profile = self._profile_fields(brand_profile, previous=current)
        now = _now()
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE source_roots SET brand_profile_id = ?, brand_profile_json = ?, "
                "brand_profile_digest = ?, brand_profile_version = ?, updated_at = ? WHERE root_id = ?",
                (
                    profile["id"],
                    profile["json"],
                    profile["digest"],
                    profile["version"],
                    now,
                    root_id,
                ),
            )
            self.store.bump_revision(connection)
        return self.get_source_root(root_id)

    def set_project_brand(
        self,
        project_id: str,
        *,
        mode: str,
        brand_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if mode not in {"inherit", "extend", "replace", "clear"}:
            raise IntakeError("project_brand_mode_invalid")
        if mode == "extend":
            raise IntakeError("project_brand_extend_unsupported_v1")
        project = self.get_project(project_id)
        if mode == "replace":
            profile = self._profile_fields(brand_profile, previous=project)
            if profile["id"] is None:
                raise IntakeError("project_brand_profile_required")
        else:
            profile = {
                "id": project.get("brand_profile_id"),
                "json": project.get("brand_profile_json"),
                "digest": project.get("brand_profile_digest"),
                "version": int(project.get("brand_profile_version") or 0),
            }
        now = _now()
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE projects SET brand_mode = ?, brand_profile_id = ?, brand_profile_json = ?, "
                "brand_profile_digest = ?, brand_profile_version = ?, updated_at = ? WHERE project_id = ?",
                (
                    mode,
                    profile["id"],
                    profile["json"],
                    profile["digest"],
                    profile["version"],
                    now,
                    project_id,
                ),
            )
            self.store.bump_revision(connection)
        return self.get_project(project_id)

    def discover_projects(self, root_id: str) -> list[dict[str, Any]]:
        source_root = self.get_source_root(root_id)
        root = Path(source_root["current_path"])
        if not root.is_dir():
            self._mark_root_missing(root_id)
            raise IntakeError("source_root_missing")
        candidates: list[dict[str, Any]] = []
        folded_entries: dict[str, str] = {}
        for entry in self._html_entries(root):
            project_path = entry.parent
            project_relpath = project_path.relative_to(root).as_posix() or "."
            entry_relpath = entry.name
            logical_entry = (
                entry_relpath
                if project_relpath == "."
                else f"{project_relpath}/{entry_relpath}"
            )
            folded = logical_entry.casefold()
            if folded in folded_entries and folded_entries[folded] != logical_entry:
                raise IntakeError("source_case_conflict")
            folded_entries[folded] = logical_entry
            html = self._read_utf8(
                entry,
                root=root,
                relative=entry.relative_to(root).as_posix(),
            )
            inventory = _HtmlInventory()
            inventory.feed(html)
            reasons = self._discovery_reasons(entry, inventory)
            unsupported = any(
                reason in {"requires_build", "framework_source", "generated_output_only"}
                for reason in reasons
            )
            signature = hashlib.sha256(
                f"{entry.name}\0{hashlib.sha256(html.encode('utf-8')).hexdigest()}".encode()
            ).hexdigest()
            candidates.append(
                {
                    "project_relpath": project_relpath,
                    "entry_relpath": entry_relpath,
                    "display_name": entry.stem,
                    "project_state": (
                        "unsupported_v1" if unsupported else "discovered_unconfirmed"
                    ),
                    "discovery_signature": signature,
                    "discovery_reasons": reasons,
                }
            )

        now = _now()
        discovered: list[dict[str, Any]] = []
        with self.store.transaction() as connection:
            schema_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            is_v2 = schema_version == TARGET_SCHEMA_VERSION
            existing_rows = connection.execute(
                "SELECT * FROM projects WHERE source_root_id = ?"
                + (" AND source_type = 'static_web'" if is_v2 else ""),
                (root_id,),
            ).fetchall()
            existing = {
                (str(row["project_relpath"]), str(row["entry_relpath"])): row
                for row in existing_rows
            }
            seen_ids: set[str] = set()
            for candidate in candidates:
                key = (candidate["project_relpath"], candidate["entry_relpath"])
                current = existing.get(key)
                if current is None:
                    project_id = _uuid()
                    if is_v2:
                        connection.execute(
                            "INSERT INTO projects ("
                            "project_id, source_root_id, source_type, project_relpath, "
                            "entry_relpath, display_name, project_state, discovery_signature, "
                            "last_snapshot_hash, brand_mode, brand_profile_id, "
                            "brand_profile_json, brand_profile_digest, brand_profile_version, "
                            "created_at, updated_at"
                            ") VALUES (?, ?, 'static_web', ?, ?, ?, ?, ?, NULL, 'inherit', "
                            "NULL, NULL, NULL, 0, ?, ?)",
                            (
                                project_id,
                                root_id,
                                candidate["project_relpath"],
                                candidate["entry_relpath"],
                                candidate["display_name"],
                                candidate["project_state"],
                                candidate["discovery_signature"],
                                now,
                                now,
                            ),
                        )
                    else:
                        connection.execute(
                            "INSERT INTO projects ("
                            "project_id, source_root_id, project_relpath, entry_relpath, "
                            "display_name, project_state, discovery_signature, "
                            "last_snapshot_hash, brand_mode, brand_profile_id, "
                            "brand_profile_json, brand_profile_digest, brand_profile_version, "
                            "created_at, updated_at"
                            ") VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'inherit', "
                            "NULL, NULL, NULL, 0, ?, ?)",
                            (
                                project_id,
                                root_id,
                                candidate["project_relpath"],
                                candidate["entry_relpath"],
                                candidate["display_name"],
                                candidate["project_state"],
                                candidate["discovery_signature"],
                                now,
                                now,
                            ),
                        )
                else:
                    project_id = str(current["project_id"])
                    connection.execute(
                        "UPDATE projects SET discovery_signature = ?, display_name = ?, updated_at = ? "
                        "WHERE project_id = ?"
                        + (" AND source_type = 'static_web'" if is_v2 else ""),
                        (
                            candidate["discovery_signature"],
                            candidate["display_name"],
                            now,
                            project_id,
                        ),
                    )
                seen_ids.add(project_id)
                row = connection.execute(
                    "SELECT * FROM projects WHERE project_id = ?"
                    + (" AND source_type = 'static_web'" if is_v2 else ""),
                    (project_id,),
                ).fetchone()
                item = dict(row)
                item["discovery_reasons"] = candidate["discovery_reasons"]
                discovered.append(item)
            for row in existing_rows:
                if str(row["project_id"]) not in seen_ids:
                    connection.execute(
                        "UPDATE projects SET project_state = 'source_missing', updated_at = ? "
                        "WHERE project_id = ?"
                        + (" AND source_type = 'static_web'" if is_v2 else ""),
                        (now, row["project_id"]),
                    )
            self.store.bump_revision(connection)
        return discovered

    def reconnect_project(
        self,
        project_id: str,
        *,
        project_relpath: str,
        entry_relpath: str,
    ) -> dict[str, Any]:
        """Reconnect one project to a user-selected entry under its existing source root."""
        project = self.get_project(project_id)
        source_root = self.get_source_root(str(project["source_root_id"]))
        root = Path(source_root["current_path"])
        if not root.is_dir():
            self._mark_root_missing(str(source_root["root_id"]))
            raise IntakeError("source_root_missing")
        normalized_project = (
            "." if project_relpath == "." else _safe_relative(project_relpath)
        )
        normalized_entry = _safe_relative(entry_relpath)
        if PurePosixPath(normalized_entry).suffix.lower() != ".html":
            raise IntakeError("project_entry_unsupported_v1")
        project_path = (
            root if normalized_project == "." else root.joinpath(*PurePosixPath(normalized_project).parts)
        )
        if normalized_project != ".":
            self._reject_symlink_components(root, normalized_project)
        if project_path.is_symlink() or not project_path.is_dir():
            raise IntakeError("project_source_missing")
        resolved_project = project_path.resolve()
        resolved_root = root.resolve()
        if resolved_project != resolved_root and resolved_root not in resolved_project.parents:
            raise IntakeError("project_path_outside_source_root")
        entry = resolved_project.joinpath(*PurePosixPath(normalized_entry).parts)
        self._reject_symlink_components(resolved_project, normalized_entry)
        if entry.is_symlink() or not entry.is_file():
            raise IntakeError("project_entry_missing")
        resolved_entry = entry.resolve()
        if resolved_entry != resolved_project and resolved_project not in resolved_entry.parents:
            raise IntakeError("project_path_outside_source_root")
        html = self._read_utf8(
            entry,
            root=resolved_project,
            relative=normalized_entry,
        )
        inventory = _HtmlInventory()
        inventory.feed(html)
        candidate_project = dict(project)
        candidate_project.update(
            {"project_relpath": normalized_project, "entry_relpath": normalized_entry}
        )
        context = ProjectContext(candidate_project, source_root, resolved_project, ())
        self._validate_static_inventory(context, inventory)
        signature = hashlib.sha256(
            f"{PurePosixPath(normalized_entry).name}\0"
            f"{hashlib.sha256(html.encode('utf-8')).hexdigest()}".encode()
        ).hexdigest()
        now = _now()
        with self.store.transaction() as connection:
            locations = connection.execute(
                "SELECT project_id, project_relpath, entry_relpath, project_state, "
                "last_snapshot_hash, brand_profile_id FROM projects "
                "WHERE source_root_id = ? AND project_id <> ?",
                (project["source_root_id"], project_id),
            ).fetchall()
            logical = f"{normalized_project}/{normalized_entry}".casefold()
            conflict = next(
                (
                    row
                    for row in locations
                    if f"{row['project_relpath']}/{row['entry_relpath']}".casefold()
                    == logical
                ),
                None,
            )
            if conflict is not None:
                has_runs = connection.execute(
                    "SELECT 1 FROM intake_runs WHERE project_id = ? LIMIT 1",
                    (conflict["project_id"],),
                ).fetchone()
                if (
                    conflict["project_state"] != "discovered_unconfirmed"
                    or conflict["last_snapshot_hash"] is not None
                    or conflict["brand_profile_id"] is not None
                    or has_runs is not None
                ):
                    raise IntakeError("project_location_already_bound")
                connection.execute(
                    "DELETE FROM projects WHERE project_id = ?", (conflict["project_id"],)
                )
            connection.execute(
                "UPDATE projects SET project_relpath = ?, entry_relpath = ?, display_name = ?, "
                "project_state = 'ready', discovery_signature = ?, last_snapshot_hash = NULL, "
                "updated_at = ? WHERE project_id = ?",
                (
                    normalized_project,
                    normalized_entry,
                    PurePosixPath(normalized_entry).stem,
                    signature,
                    now,
                    project_id,
                ),
            )
            self.store.bump_revision(connection)
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise IntakeError("project_not_found")
        return dict(row)

    def confirm_project(self, project_id: str) -> dict[str, Any]:
        context = self._project_context(project_id, allow_unconfirmed_children=True)
        entry = context.path / context.project["entry_relpath"]
        if entry.is_symlink() or not entry.is_file():
            self._set_project_state(project_id, "source_missing")
            raise IntakeError("project_entry_missing")
        if entry.suffix.lower() != ".html":
            self._set_project_state(project_id, "unsupported_v1")
            raise IntakeError("project_entry_unsupported_v1")
        inventory = _HtmlInventory()
        inventory.feed(
            self._read_utf8(
                entry,
                root=context.path,
                relative=str(context.project["entry_relpath"]),
            )
        )
        try:
            self._validate_static_inventory(context, inventory)
        except IntakeError:
            self._set_project_state(project_id, "unsupported_v1")
            raise
        self._set_project_state(project_id, "ready")
        return self.get_project(project_id)

    def snapshot_project(self, project_id: str) -> ProjectSnapshot:
        context = self._project_context(project_id)
        entry = context.path.joinpath(
            *PurePosixPath(str(context.project["entry_relpath"])).parts
        )
        if entry.is_symlink() or not entry.is_file():
            self._set_project_state(project_id, "source_missing")
            raise IntakeError("project_entry_missing_from_snapshot")
        entries: list[SnapshotEntry] = []
        text: dict[str, str] = {}
        folded: dict[str, str] = {}
        count = 0
        total_supported_bytes = 0
        for path_value in self._walk_project_files(context.path, context.excluded_relpaths):
            relative = path_value.relative_to(context.path).as_posix()
            suffix = path_value.suffix.lower()
            if suffix not in _TEXT_SUFFIXES | _ASSET_SUFFIXES:
                continue
            count += 1
            if count > MAX_FILES:
                raise IntakeError("source_limit_exceeded")
            key = relative.casefold()
            if key in folded and folded[key] != relative:
                raise IntakeError("source_case_conflict")
            folded[key] = relative
            content, stable_mtime_ns = self._read_stable_bytes(
                path_value,
                root=context.path,
                relative=relative,
            )
            total_supported_bytes += len(content)
            if total_supported_bytes > MAX_SUPPORTED_BYTES:
                raise IntakeError("source_total_size_exceeded")
            digest = hashlib.sha256(content).hexdigest()
            if suffix in _TEXT_SUFFIXES:
                try:
                    text[relative] = content.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise IntakeError("source_utf8_invalid") from exc
            entries.append(
                SnapshotEntry(
                    path=relative,
                    file_type="text" if suffix in _TEXT_SUFFIXES else "image",
                    size=len(content),
                    mtime_ns=stable_mtime_ns,
                    sha256=digest,
                )
            )
        entry_relpath = PurePosixPath(str(context.project["entry_relpath"])).as_posix()
        if entry_relpath not in text:
            if entry.is_symlink() or not entry.is_file():
                self._set_project_state(project_id, "source_missing")
            raise IntakeError("project_entry_missing_from_snapshot")
        entries.sort(key=lambda item: item.path)
        payload = "".join(
            f"{item.path}\0{item.file_type}\0{item.size}\0{item.sha256}\n"
            for item in entries
        ).encode("utf-8")
        return ProjectSnapshot(hashlib.sha256(payload).hexdigest(), tuple(entries), text)

    def inspect_computation_adapters(
        self,
        project_id: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Reject the retired computation_adapter.v1 discovery path."""
        raise IntakeError("adapter_creation_path_retired")

    def _inspect_computation_adapters_v1(
        self,
        project_id: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Return source-free adapter offers from one consistent project snapshot."""
        with _project_guard(project_id):
            context = self._project_context(project_id)
            before = self.snapshot_project(project_id)
            if cancel_check and cancel_check():
                raise IntakeError("intake_cancelled")
            if any(
                item.path == COMPUTATION_ADAPTER_ENTRY
                or item.path.startswith("__reweave_adapter__/")
                for item in before.entries
            ):
                raise IntakeError("adapter_source_unsupported_v1")
            git_before = self._adapter_git_evidence(context.path)
            result = self._run_extraction_analyzer(
                before, {"mode": "inspect_computation_adapters"}
            )
            offers = [
                self._adapter_public_offer(project_id, before.digest, git_before, item)
                for item in result.get("offers", [])
                if type(item) is dict
            ]
            offers.sort(
                key=lambda item: (
                    item["module_relpath"], item["export_name"], item["offer_id"]
                )
            )
            if len({item["offer_id"] for item in offers}) != len(offers):
                raise IntakeError("adapter_source_unsupported_v1")
            after = self.snapshot_project(project_id)
            git_after = self._adapter_git_evidence(context.path)
            if before.digest != after.digest or git_before != git_after:
                raise IntakeError("source_changed_during_scan")
            if cancel_check and cancel_check():
                raise IntakeError("intake_cancelled")
            rejected = sum(
                1 for item in result.get("rejections", []) if type(item) is dict
            )
            return {
                "schema": "computation_adapter_offers.v1",
                "project_id": project_id,
                "snapshot_sha256": before.digest,
                "git_commit": git_before["commit"],
                "git_state": git_before["state"],
                "offers": offers,
                "rejection_summary": (
                    [{"code": "adapter_source_unsupported_v1", "count": rejected}]
                    if rejected
                    else []
                ),
            }

    @staticmethod
    def _adapter_git_evidence(project_path: Path) -> dict[str, str | None]:
        git = shutil.which("git")
        if not git:
            return {"state": "dirty_or_non_git", "commit": None, "status_sha256": None}
        environment = restricted_subprocess_environment()
        try:
            status = subprocess.run(
                [git, "-C", str(project_path), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                capture_output=True,
                timeout=5,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"state": "dirty_or_non_git", "commit": None, "status_sha256": None}
        if status.returncode:
            return {"state": "dirty_or_non_git", "commit": None, "status_sha256": None}
        status_digest = hashlib.sha256(status.stdout).hexdigest()
        if status.stdout:
            return {
                "state": "dirty_or_non_git",
                "commit": None,
                "status_sha256": status_digest,
            }
        try:
            head = subprocess.run(
                [git, "-C", str(project_path), "rev-parse", "--verify", "HEAD"],
                capture_output=True,
                timeout=5,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"state": "dirty_or_non_git", "commit": None, "status_sha256": status_digest}
        commit = head.stdout.decode("ascii", errors="ignore").strip().lower()
        if head.returncode or re.fullmatch(r"[0-9a-f]{40,64}", commit) is None:
            return {"state": "dirty_or_non_git", "commit": None, "status_sha256": status_digest}
        return {"state": "clean", "commit": commit, "status_sha256": status_digest}

    @staticmethod
    def _adapter_offer_id(
        project_id: str,
        snapshot_digest: str,
        git_evidence: dict[str, str | None],
        offer: dict[str, Any],
    ) -> str:
        identity = {
            "adapter_contract_version": COMPUTATION_ADAPTER_CONTRACT_VERSION,
            "project_id": project_id,
            "snapshot_sha256": snapshot_digest,
            "git_state": git_evidence["state"],
            "git_commit": git_evidence["commit"],
            "git_status_sha256": git_evidence["status_sha256"],
            "module_relpath": offer.get("module_relpath"),
            "export_name": offer.get("export_name"),
            "parameters": offer.get("parameters"),
            "function_sha256": offer.get("function_sha256"),
            "closure": offer.get("closure"),
        }
        return "adapter_offer_" + hashlib.sha256(_json(identity).encode("utf-8")).hexdigest()

    def _adapter_public_offer(
        self,
        project_id: str,
        snapshot_digest: str,
        git_evidence: dict[str, str | None],
        offer: dict[str, Any],
    ) -> dict[str, Any]:
        module_relpath = _safe_relative(str(offer.get("module_relpath") or ""))
        export_name = offer.get("export_name")
        parameters = offer.get("parameters")
        function_sha256 = offer.get("function_sha256")
        closure = offer.get("closure")
        if (
            PurePosixPath(module_relpath).suffix.lower() not in {".js", ".mjs"}
            or type(export_name) is not str
            or re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", export_name) is None
            or type(parameters) is not list
            or not parameters
            or any(
                type(item) is not str
                or re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", item) is None
                for item in parameters
            )
            or len(parameters) != len(set(parameters))
            or type(function_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", function_sha256) is None
            or type(closure) is not list
            or not closure
        ):
            raise IntakeError("adapter_source_unsupported_v1")
        safe_closure: list[dict[str, str]] = []
        for row in closure:
            if type(row) is not dict or set(row) != {"logical_path", "sha256"}:
                raise IntakeError("adapter_source_unsupported_v1")
            logical = _safe_relative(str(row.get("logical_path") or ""))
            digest = row.get("sha256")
            if (
                PurePosixPath(logical).suffix.lower() not in {".js", ".mjs"}
                or type(digest) is not str
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                raise IntakeError("adapter_source_unsupported_v1")
            safe_closure.append({"logical_path": logical, "sha256": digest})
        if safe_closure != sorted(safe_closure, key=lambda row: row["logical_path"]):
            raise IntakeError("adapter_source_unsupported_v1")
        normalized = {
            "module_relpath": module_relpath,
            "export_name": export_name,
            "parameters": list(parameters),
            "function_sha256": function_sha256,
            "closure": safe_closure,
        }
        return {
            "offer_id": self._adapter_offer_id(
                project_id, snapshot_digest, git_evidence, normalized
            ),
            **normalized,
        }

    @staticmethod
    def _validate_adapter_mapping(
        payload: dict[str, Any], offer: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]], str, str]:
        if set(payload) - {
            "project_id",
            "offer_id",
            "arguments",
            "result_field",
            "examples",
        }:
            raise IntakeError("adapter_mapping_invalid")
        raw_arguments = payload.get("arguments")
        result_field = payload.get("result_field")
        raw_examples = payload.get("examples")
        if (
            type(raw_arguments) is not list
            or type(result_field) is not str
            or _ADAPTER_MEMBER.fullmatch(result_field) is None
            or type(raw_examples) is not list
            or not 1 <= len(raw_examples) <= 64
        ):
            raise IntakeError("adapter_mapping_invalid")
        source_parameters = offer["parameters"]
        if len(raw_arguments) != len(source_parameters):
            raise IntakeError("adapter_mapping_invalid")
        by_source: dict[str, dict[str, Any]] = {}
        input_fields: set[str] = set()
        for row in raw_arguments:
            if type(row) is not dict or set(row) != {
                "source_parameter",
                "input_field",
                "minimum",
                "maximum",
            }:
                raise IntakeError("adapter_mapping_invalid")
            source_parameter = row.get("source_parameter")
            input_field = row.get("input_field")
            minimum = row.get("minimum")
            maximum = row.get("maximum")
            if (
                type(source_parameter) is not str
                or source_parameter not in source_parameters
                or source_parameter in by_source
                or type(input_field) is not str
                or _ADAPTER_MEMBER.fullmatch(input_field) is None
                or input_field in input_fields
                or input_field == result_field
                or type(minimum) is not int
                or type(maximum) is not int
                or not -MAX_SAFE_INTEGER <= minimum <= maximum <= MAX_SAFE_INTEGER
            ):
                raise IntakeError("adapter_mapping_invalid")
            normalized = {
                "source_parameter": source_parameter,
                "input_field": input_field,
                "minimum": minimum,
                "maximum": maximum,
            }
            by_source[source_parameter] = normalized
            input_fields.add(input_field)
        if set(by_source) != set(source_parameters):
            raise IntakeError("adapter_mapping_invalid")
        arguments = [by_source[name] for name in source_parameters]
        examples: list[dict[str, Any]] = []
        for row in raw_examples:
            if type(row) is not dict or set(row) != {"input", "expected"}:
                raise IntakeError("adapter_mapping_invalid")
            value = row.get("input")
            expected = row.get("expected")
            if (
                type(value) is not dict
                or set(value) != input_fields
                or type(expected) is not int
                or not -MAX_SAFE_INTEGER <= expected <= MAX_SAFE_INTEGER
            ):
                raise IntakeError("adapter_mapping_invalid")
            normalized_input: dict[str, int] = {}
            for argument in arguments:
                field = argument["input_field"]
                item = value.get(field)
                if (
                    type(item) is not int
                    or not argument["minimum"] <= item <= argument["maximum"]
                ):
                    raise IntakeError("adapter_mapping_invalid")
                normalized_input[field] = item
            examples.append({"input": normalized_input, "expected": expected})
        mapping = {"arguments": arguments, "result_field": result_field}
        mapping_hash = hashlib.sha256(_json(mapping).encode("utf-8")).hexdigest()
        examples_hash = hashlib.sha256(_json(examples).encode("utf-8")).hexdigest()
        return arguments, result_field, examples, mapping_hash, examples_hash

    def create_computation_adapter_candidate(
        self,
        payload: dict[str, Any],
        *,
        cancel_check: Callable[[], bool] | None = None,
        validator: Callable[[dict[str, Any], list[dict[str, Any]], str], dict[str, Any]]
        | None = None,
    ) -> dict[str, Any]:
        """Reject creation through the retired computation_adapter.v1 path."""
        raise IntakeError("adapter_creation_path_retired")

    def _create_computation_adapter_candidate_v1(
        self,
        payload: dict[str, Any],
        *,
        cancel_check: Callable[[], bool] | None = None,
        validator: Callable[[dict[str, Any], list[dict[str, Any]], str], dict[str, Any]]
        | None = None,
    ) -> dict[str, Any]:
        """Rebuild one offer, preflight it in memory, then persist one safe review row."""
        if type(payload) is not dict:
            raise IntakeError("adapter_mapping_invalid")
        project_id = payload.get("project_id")
        offer_id = payload.get("offer_id")
        if type(project_id) is not str or not project_id or type(offer_id) is not str:
            raise IntakeError("adapter_mapping_invalid")
        if validator is None:
            raise IntakeError("adapter_security_rejected")
        with _project_guard(project_id):
            context = self._project_context(project_id)
            before = self.snapshot_project(project_id)
            git_before = self._adapter_git_evidence(context.path)
            if cancel_check and cancel_check():
                raise IntakeError("intake_cancelled")
            if any(
                item.path == COMPUTATION_ADAPTER_ENTRY
                or item.path.startswith("__reweave_adapter__/")
                for item in before.entries
            ):
                raise IntakeError("adapter_source_unsupported_v1")
            inspected = self._run_extraction_analyzer(
                before, {"mode": "inspect_computation_adapters"}
            )
            matching: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for raw_offer in inspected.get("offers", []):
                if type(raw_offer) is not dict:
                    continue
                public = self._adapter_public_offer(
                    project_id, before.digest, git_before, raw_offer
                )
                if public["offer_id"] == offer_id:
                    matching.append((raw_offer, public))
            if len(matching) != 1:
                raise IntakeError("adapter_offer_stale")
            _raw_offer, offer = matching[0]
            arguments, result_field, examples, mapping_hash, examples_hash = (
                self._validate_adapter_mapping(payload, offer)
            )
            if cancel_check and cancel_check():
                raise IntakeError("intake_cancelled")
            built = self._run_extraction_analyzer(
                before,
                {
                    "mode": "build_computation_adapter",
                    "offer": {
                        key: offer[key]
                        for key in (
                            "module_relpath",
                            "export_name",
                            "parameters",
                            "function_sha256",
                            "closure",
                        )
                    },
                    "arguments": arguments,
                    "result_field": result_field,
                },
            )
            candidate = built.get("candidate")
            output_range = built.get("output_range")
            if (
                type(candidate) is not dict
                or candidate.get("capability_kind") != "computation"
                or candidate.get("activation")
                != {
                    "mode": "declared_input_compute",
                    "entry_module": COMPUTATION_ADAPTER_ENTRY,
                    "entrypoint": "compute",
                }
                or type(output_range) is not dict
                or set(output_range) != {"minimum", "maximum"}
                or type(output_range.get("minimum")) is not int
                or type(output_range.get("maximum")) is not int
            ):
                raise IntakeError("adapter_source_unsupported_v1")
            try:
                (
                    candidate["input_contract"],
                    candidate["output_contract"],
                    candidate["error_contract"],
                ) = normalize_capsule_contracts(
                    "computation",
                    candidate["input_contract"],
                    candidate["output_contract"],
                    candidate["error_contract"],
                )
                fixtures = generate_synthetic_fixtures(candidate["input_contract"])
            except (DataContractError, KeyError, TypeError) as exc:
                raise IntakeError("adapter_mapping_invalid") from exc
            output_property = candidate["output_contract"].get("properties", {}).get(
                result_field
            )
            if (
                candidate["output_contract"].get("required") != [result_field]
                or type(output_property) is not dict
                or output_property.get("type") != "integer"
                or output_property.get("minimum") != output_range["minimum"]
                or output_property.get("maximum") != output_range["maximum"]
            ):
                raise IntakeError("adapter_interval_unproven")
            try:
                preflight = validator(candidate, examples, result_field)
            except Exception as exc:
                code = getattr(exc, "code", None)
                if code not in {
                    "adapter_example_mismatch",
                    "adapter_source_exception",
                    "adapter_security_rejected",
                }:
                    code = "adapter_security_rejected"
                raise IntakeError(code) from exc
            if (
                type(preflight) is not dict
                or preflight.get("schema_version")
                != "computation_adapter_preflight.v1"
                or preflight.get("status") != "passed"
                or preflight.get("acceptance_scope")
                != "isolated_node_vm_computation"
                or preflight.get("example_count") != len(examples)
                or preflight.get("example_set_sha256") != examples_hash
            ):
                raise IntakeError("adapter_security_rejected")
            after = self.snapshot_project(project_id)
            git_after = self._adapter_git_evidence(context.path)
            if before.digest != after.digest or git_before != git_after:
                raise IntakeError("source_changed_during_scan")
            if cancel_check and cancel_check():
                raise IntakeError("intake_cancelled")

            module_by_path = {
                str(item.get("path") or ""): item
                for item in candidate.get("javascript_modules", [])
                if type(item) is dict
            }
            adapter_module = module_by_path.get(COMPUTATION_ADAPTER_ENTRY)
            if type(adapter_module) is not dict or type(adapter_module.get("source")) is not str:
                raise IntakeError("adapter_source_unsupported_v1")
            evidence = {
                "candidate_origin": "deterministic_computation_adapter",
                "adapter_contract_version": COMPUTATION_ADAPTER_CONTRACT_VERSION,
                "source": {
                    "module_relpath": offer["module_relpath"],
                    "export_name": offer["export_name"],
                    "function_sha256": offer["function_sha256"],
                    "snapshot_sha256": before.digest,
                    "git_commit": git_before["commit"],
                    "git_state": git_before["state"],
                },
                "closure": offer["closure"],
                "mapping": {
                    "arguments": arguments,
                    "result_field": result_field,
                    "mapping_sha256": mapping_hash,
                },
                "generated_adapter": {
                    "logical_path": COMPUTATION_ADAPTER_ENTRY,
                    "sha256": hashlib.sha256(
                        adapter_module["source"].encode("utf-8")
                    ).hexdigest(),
                },
                "examples": {
                    "count": len(examples),
                    "canonical_sha256": examples_hash,
                    "passed": True,
                },
            }
            profile = self._effective_brand_profile(context.project, context.source_root)
            run_id = self._create_run(project_id)
            self._set_run(run_id, "running", started_at=_now())
            row = self._adapter_candidate_row(
                project_id,
                run_id,
                candidate,
                fixtures,
                evidence,
                profile,
            )
            counts = {
                "adapter_only": True,
                "candidate_origin": "deterministic_computation_adapter",
                "adapter_contract_version": COMPUTATION_ADAPTER_CONTRACT_VERSION,
                "candidates": 1,
                "waiting_user": int(row["candidate_status"] == "waiting_user"),
                "rejected": int(row["candidate_status"] == "rejected"),
                "extracted": int(row["candidate_status"] == "extracted"),
                "effective_brand_profile_id": profile.get("id"),
                "effective_brand_profile_digest": profile.get("digest"),
            }
            status = "completed_with_pending"
            review_ids = self._commit_candidate_rows(
                run_id,
                project_id,
                before.digest,
                after.digest,
                status,
                counts,
                [row],
                update_project_snapshot=False,
            )
            return {
                "run_id": run_id,
                "status": status,
                "counts": counts,
                "review_ids": review_ids,
                "adapter": {
                    "offer_id": offer_id,
                    "candidate_status": row["candidate_status"],
                    "example_count": len(examples),
                    "mapping_sha256": mapping_hash,
                    "adapter_sha256": evidence["generated_adapter"]["sha256"],
                },
            }

    def rebuild_computation_adapter_candidate(
        self,
        project_id: str,
        summary: dict[str, Any],
        *,
        snapshot: ProjectSnapshot | None = None,
    ) -> dict[str, Any]:
        """Deterministically replay a persisted adapter boundary for Stage 3."""
        if (
            type(summary) is not dict
            or summary.get("candidate_origin") != "deterministic_computation_adapter"
            or summary.get("adapter_contract_version")
            != COMPUTATION_ADAPTER_CONTRACT_VERSION
        ):
            raise IntakeError("adapter_contract_version_expired")
        evidence = summary.get("adapter_evidence")
        if type(evidence) is not dict or set(evidence) != {
            "candidate_origin",
            "adapter_contract_version",
            "source",
            "closure",
            "mapping",
            "generated_adapter",
            "examples",
        }:
            raise IntakeError("candidate_boundary_changed")
        source = evidence.get("source")
        mapping = evidence.get("mapping")
        generated = evidence.get("generated_adapter")
        if (
            evidence.get("candidate_origin") != "deterministic_computation_adapter"
            or evidence.get("adapter_contract_version")
            != COMPUTATION_ADAPTER_CONTRACT_VERSION
            or type(source) is not dict
            or type(mapping) is not dict
            or type(generated) is not dict
        ):
            raise IntakeError("candidate_boundary_changed")
        current = snapshot or self.snapshot_project(project_id)
        if source.get("snapshot_sha256") != current.digest:
            raise IntakeError("candidate_boundary_changed")
        context = self._project_context(project_id)
        git_evidence = self._adapter_git_evidence(context.path)
        if (
            source.get("git_state") != git_evidence["state"]
            or source.get("git_commit") != git_evidence["commit"]
        ):
            raise IntakeError("candidate_boundary_changed")
        inspected = self._run_extraction_analyzer(
            current, {"mode": "inspect_computation_adapters"}
        )
        expected_offer = {
            "module_relpath": source.get("module_relpath"),
            "export_name": source.get("export_name"),
            "function_sha256": source.get("function_sha256"),
            "closure": evidence.get("closure"),
        }
        offers = [
            item
            for item in inspected.get("offers", [])
            if type(item) is dict
            and all(item.get(key) == value for key, value in expected_offer.items())
        ]
        if len(offers) != 1:
            raise IntakeError("candidate_boundary_changed")
        offer = offers[0]
        arguments = mapping.get("arguments")
        result_field = mapping.get("result_field")
        if type(arguments) is not list or type(result_field) is not str:
            raise IntakeError("candidate_boundary_changed")
        mapping_payload = {
            "arguments": arguments,
            "result_field": result_field,
        }
        if mapping.get("mapping_sha256") != hashlib.sha256(
            _json(mapping_payload).encode("utf-8")
        ).hexdigest():
            raise IntakeError("candidate_boundary_changed")
        rebuilt = self._run_extraction_analyzer(
            current,
            {
                "mode": "build_computation_adapter",
                "offer": {
                    key: offer[key]
                    for key in (
                        "module_relpath",
                        "export_name",
                        "parameters",
                        "function_sha256",
                        "closure",
                    )
                },
                "arguments": arguments,
                "result_field": result_field,
            },
        )
        candidate = rebuilt.get("candidate")
        if type(candidate) is not dict:
            raise IntakeError("candidate_boundary_changed")
        adapter_modules = [
            item
            for item in candidate.get("javascript_modules", [])
            if type(item) is dict and item.get("path") == COMPUTATION_ADAPTER_ENTRY
        ]
        if (
            len(adapter_modules) != 1
            or type(adapter_modules[0].get("source")) is not str
            or generated.get("logical_path") != COMPUTATION_ADAPTER_ENTRY
            or generated.get("sha256")
            != hashlib.sha256(adapter_modules[0]["source"].encode("utf-8")).hexdigest()
        ):
            raise IntakeError("candidate_boundary_changed")
        return candidate

    def run_intake(
        self,
        project_id: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        with _project_guard(project_id):
            context = self._project_context(project_id)
            if context.project["project_state"] != "ready":
                raise IntakeError("project_not_ready")
            run_id = self._create_run(project_id)
            try:
                self._set_run(run_id, "running", started_at=_now())
                self._cancel_if_requested(run_id, cancel_check)
                before = self.snapshot_project(project_id)
                profile = self._effective_brand_profile(context.project, context.source_root)
                if self._is_no_change(
                    project_id,
                    before.digest,
                    profile.get("id"),
                    profile.get("digest"),
                ):
                    after = self.snapshot_project(project_id)
                    if after.digest != before.digest:
                        raise IntakeError("source_changed_during_scan")
                    self._cancel_if_requested(run_id, cancel_check)
                    counts = {
                        "candidates": 0,
                        "effective_brand_profile_id": profile.get("id"),
                        "effective_brand_profile_digest": profile.get("digest"),
                    }
                    self._finish_run(run_id, "no_change", before.digest, after.digest, counts)
                    return {"run_id": run_id, "status": "no_change", "counts": counts, "review_ids": []}

                self._cancel_if_requested(run_id, cancel_check)
                analysis, inventory = self._extract(context, before)
                rows = self._candidate_rows(
                    project_id,
                    run_id,
                    before,
                    analysis,
                    inventory,
                    profile,
                )
                self._cancel_if_requested(run_id, cancel_check)
                after = self.snapshot_project(project_id)
                if after.digest != before.digest:
                    raise IntakeError("source_changed_during_scan")
                self._cancel_if_requested(run_id, cancel_check)
                waiting = sum(row["candidate_status"] in {"waiting_user", "review_required"} for row in rows)
                rejected = sum(row["candidate_status"] == "rejected" for row in rows)
                counts = {
                    "candidates": len(rows),
                    "waiting_user": sum(row["candidate_status"] == "waiting_user" for row in rows),
                    "review_required": sum(row["candidate_status"] == "review_required" for row in rows),
                    "rejected": rejected,
                    "extracted": sum(row["candidate_status"] == "extracted" for row in rows),
                    "effective_brand_profile_id": profile.get("id"),
                    "effective_brand_profile_digest": profile.get("digest"),
                }
                status = "completed_with_pending" if waiting else "completed"
                review_ids = self._commit_candidate_rows(
                    run_id, project_id, before.digest, after.digest, status, counts, rows
                )
                return {"run_id": run_id, "status": status, "counts": counts, "review_ids": review_ids}
            except IntakeError as exc:
                if exc.code != "intake_cancelled":
                    self._fail_run(run_id, exc.code)
                raise
            except Exception as exc:
                self._fail_run(run_id, "stage2_internal_error")
                raise IntakeError("stage2_internal_error") from exc

    def record_review_decisions(
        self,
        review_id: str,
        *,
        sensitivity_decision: str | None = None,
        brand_decision: str | None = None,
        asset_decision: str | None = None,
        enum_decision: str | None = None,
        enum_decision_binding_sha256: str | None = None,
        _capture_decision_token: str | None = None,
    ) -> dict[str, Any]:
        if (
            sensitivity_decision is None
            and brand_decision is None
            and asset_decision is None
            and enum_decision is None
        ):
            raise IntakeError("review_decision_required")
        if sensitivity_decision is not None and sensitivity_decision not in _SENSITIVITY_DECISIONS:
            raise IntakeError("sensitivity_decision_invalid")
        if brand_decision is not None and brand_decision not in _BRAND_DECISIONS:
            raise IntakeError("brand_decision_invalid")
        if asset_decision is not None and asset_decision not in _ASSET_DECISIONS:
            raise IntakeError("asset_decision_invalid")
        if enum_decision is not None and enum_decision not in _ENUM_DECISIONS:
            raise IntakeError("enum_decision_invalid")
        if (enum_decision is None) != (enum_decision_binding_sha256 is None) or (
            enum_decision_binding_sha256 is not None
            and re.fullmatch(r"[0-9a-f]{64}", enum_decision_binding_sha256) is None
        ):
            raise IntakeError("enum_decision_binding_invalid")
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM review_items WHERE review_id = ?", (review_id,)
            ).fetchone()
            if row is None or row["candidate_status"] != "waiting_user":
                raise IntakeError("review_item_not_waiting_user")
            allowed = self._allowed_review_decisions(row)
            try:
                candidate = json.loads(row["sanitized_candidate_json"])
            except (json.JSONDecodeError, TypeError) as exc:
                raise IntakeError("review_decision_not_allowed") from exc
            capture_v2 = (
                type(candidate) is dict
                and candidate.get("candidate_origin")
                == "deterministic_computation_adapter"
                and candidate.get("adapter_contract_version")
                == "computation_adapter.v2"
            )
            if capture_v2:
                with self._capture_decision_lock:
                    authorization = self._capture_decision_authorizations.get(review_id)
                if (
                    authorization is None
                    or authorization[0] != row["source_hash"]
                    or not secrets.compare_digest(
                        authorization[1], _capture_decision_token or ""
                    )
                ):
                    raise IntakeError("capture_decision_rebuild_required")
            if any(
                decision is not None and decision not in allowed
                for decision in (
                    sensitivity_decision,
                    brand_decision,
                    asset_decision,
                    enum_decision,
                )
            ):
                raise IntakeError("review_decision_not_allowed")
            if sensitivity_decision and row["sensitivity_decision"] is not None:
                raise IntakeError("sensitivity_decision_already_set")
            if brand_decision and row["brand_decision"] is not None:
                raise IntakeError("brand_decision_already_set")
            if asset_decision and row["asset_decision"] is not None:
                raise IntakeError("asset_decision_already_set")
            if enum_decision and row["enum_decision"] is not None:
                raise IntakeError("enum_decision_already_set")
            if enum_decision is not None:
                try:
                    enum_summary = json.loads(row["redaction_summary_json"])
                except (json.JSONDecodeError, TypeError) as exc:
                    raise IntakeError("enum_decision_binding_invalid") from exc
                if (
                    type(enum_summary) is not dict
                    or enum_summary.get("enum_decision_binding_sha256")
                    != enum_decision_binding_sha256
                ):
                    raise IntakeError("enum_decision_binding_invalid")
            candidate_brand = self._review_brand_binding(row["redaction_summary_json"])
            current_brand: tuple[str | None, str | None] | None = None
            if brand_decision is not None:
                current = connection.execute(
                    "SELECT CASE WHEN p.brand_mode = 'inherit' THEN r.brand_profile_id "
                    "WHEN p.brand_mode = 'clear' THEN NULL ELSE p.brand_profile_id END, "
                    "CASE WHEN p.brand_mode = 'inherit' THEN r.brand_profile_digest "
                    "WHEN p.brand_mode = 'clear' THEN NULL ELSE p.brand_profile_digest END "
                    "FROM projects p JOIN source_roots r ON r.root_id = p.source_root_id "
                    "WHERE p.project_id = ?",
                    (row["project_id"],),
                ).fetchone()
                if current is None:
                    raise IntakeError("project_not_found")
                current_brand = (current[0], current[1])
                if candidate_brand != current_brand:
                    raise IntakeError("brand_profile_changed")
            bound_rows = connection.execute(
                "SELECT sensitivity_decision, brand_decision, asset_decision, "
                "redaction_summary_json FROM review_items "
                "WHERE project_id = ? AND source_relpath = ? AND source_hash = ? "
                "AND redaction_rules_version = ?",
                (
                    row["project_id"],
                    row["source_relpath"],
                    row["source_hash"],
                    row["redaction_rules_version"],
                ),
            ).fetchall()
            existing_sensitivity = {
                str(item["sensitivity_decision"])
                for item in bound_rows
                if item["sensitivity_decision"] is not None
            }
            existing_brand = {
                str(item["brand_decision"])
                for item in bound_rows
                if item["brand_decision"] is not None
                and self._review_brand_binding(item["redaction_summary_json"])
                == candidate_brand
            }
            existing_asset = {
                str(item["asset_decision"])
                for item in bound_rows
                if item["asset_decision"] is not None
            }
            if sensitivity_decision is not None:
                if "confirm_real_record_reject" in existing_sensitivity:
                    if sensitivity_decision != "confirm_real_record_reject":
                        raise IntakeError("sensitivity_decision_conflict")
                elif (
                    sensitivity_decision != "confirm_real_record_reject"
                    and existing_sensitivity
                    and existing_sensitivity != {sensitivity_decision}
                ):
                    raise IntakeError("sensitivity_decision_conflict")
            if brand_decision is not None and existing_brand and existing_brand != {brand_decision}:
                raise IntakeError("brand_decision_conflict")
            if asset_decision is not None and existing_asset and existing_asset != {asset_decision}:
                raise IntakeError("asset_decision_conflict")
            now = _now()
            updates: list[str] = ["updated_at = ?"]
            values: list[Any] = [now]
            if sensitivity_decision:
                updates.extend(["sensitivity_decision = ?", "sensitivity_decided_at = ?"])
                values.extend([sensitivity_decision, now])
            if brand_decision:
                if brand_decision == "retain_brand_limited":
                    if current_brand is None or current_brand[0] is None:
                        raise IntakeError("brand_profile_required_for_retention")
                updates.extend(["brand_decision = ?", "brand_decided_at = ?"])
                values.extend([brand_decision, now])
            if asset_decision:
                updates.extend(["asset_decision = ?", "asset_decided_at = ?"])
                values.extend([asset_decision, now])
            if enum_decision:
                updates.extend(
                    [
                        "enum_decision = ?",
                        "enum_decision_binding_sha256 = ?",
                        "enum_decided_at = ?",
                    ]
                )
                values.extend(
                    [enum_decision, enum_decision_binding_sha256, now]
                )
            values.append(review_id)
            connection.execute(
                f"UPDATE review_items SET {', '.join(updates)} WHERE review_id = ?",
                values,
            )
            self.store.bump_revision(connection)
            updated = connection.execute(
                "SELECT * FROM review_items WHERE review_id = ?", (review_id,)
            ).fetchone()
        if capture_v2:
            with self._capture_decision_lock:
                current = self._capture_decision_authorizations.get(review_id)
                if current is not None and secrets.compare_digest(
                    current[1], _capture_decision_token or ""
                ):
                    self._capture_decision_authorizations.pop(review_id, None)
        return dict(updated)

    def recover_interrupted_runs(self) -> int:
        now = _now()
        with self.store.transaction() as connection:
            count = connection.execute(
                "UPDATE intake_runs SET status = 'interrupted', completed_at = ?, "
                "error_code = 'application_restarted' WHERE status IN ('queued', 'running')",
                (now,),
            ).rowcount
            if count:
                self.store.bump_revision(connection)
        return count

    def _extract(
        self, context: ProjectContext, snapshot: ProjectSnapshot
    ) -> tuple[dict[str, Any], _HtmlInventory]:
        entry_rel = context.project["entry_relpath"]
        html = snapshot.text.get(entry_rel)
        if html is None:
            raise IntakeError("project_entry_missing_from_snapshot")
        inventory = _HtmlInventory()
        inventory.feed(html)
        self._validate_static_inventory(context, inventory)
        selectors, controls, _root_selector = inventory.selector_contracts()
        entry_modules = [
            _local_reference(entry_rel, source)
            for script_type, source in inventory.scripts
            if script_type == "module"
        ]
        snapshot_paths = {item.path for item in snapshot.entries}
        static_references = entry_modules + [
            _local_reference(entry_rel, source)
            for source in inventory.stylesheets + inventory.resources
        ]
        if any(relative not in snapshot_paths for relative in static_references):
            raise IntakeError("static_closure_outside_snapshot")
        if not entry_modules:
            return {
                "status": "ok",
                "candidates": [],
                "rejections": [
                    {
                        "entry_module": entry_rel,
                        "entrypoint": None,
                        "capability_kind": "presentation",
                        "error_code": "missing_supported_entrypoint_v1",
                    }
                ],
            }, inventory
        request = {
            "entry_modules": entry_modules,
            "html_selectors": selectors,
            "html_controls": controls,
        }
        result = self._run_extraction_analyzer(snapshot, request)
        snapshot_boundary_codes = {
            "module_not_found",
            "module_path_excluded",
            "module_path_outside_project",
        }
        if any(
            str(item.get("error_code") or "") in snapshot_boundary_codes
            for item in result.get("rejections", [])
            if isinstance(item, dict)
        ):
            raise IntakeError("static_closure_outside_snapshot")
        if inventory.static_root() is None:
            candidates = result.get("candidates", [])
            result["candidates"] = [
                item for item in candidates if item.get("capability_kind") == "computation"
            ]
            result["rejections"] = [
                {**item, "error_code": "html_capsule_root_invalid"}
                if item.get("capability_kind") in {"presentation", "interaction"}
                else item
                for item in result.get("rejections", [])
            ]
            result["rejections"].extend(
                {
                    "entry_module": item.get("activation", {}).get("entry_module"),
                    "entrypoint": item.get("activation", {}).get("entrypoint"),
                    "capability_kind": item.get("capability_kind"),
                    "error_code": "html_capsule_root_invalid",
                }
                for item in candidates
                if item.get("capability_kind") != "computation"
            )
        return result, inventory

    def _run_extraction_analyzer(
        self, snapshot: ProjectSnapshot, request: dict[str, Any]
    ) -> dict[str, Any]:
        node = os.environ.get("REWEAVE_NODE") or shutil.which("node")
        if not node:
            raise IntakeError("node_unavailable")
        script = Path(__file__).resolve().parents[1] / "scripts/analyze_reweave_extraction.mjs"
        snapshot_by_path = {item.path: item for item in snapshot.entries}
        javascript_paths = [
            relative
            for relative in sorted(snapshot.text)
            if PurePosixPath(relative).suffix.lower() in {".js", ".mjs"}
        ]
        if sum(snapshot_by_path[relative].size for relative in javascript_paths) > MAX_JAVASCRIPT_SNAPSHOT_BYTES:
            raise IntakeError("javascript_snapshot_size_exceeded")
        analyzer_request = {
            **request,
            "module_snapshot": [
                {
                    "path": relative,
                    "source": snapshot.text[relative],
                    "sha256": snapshot_by_path[relative].sha256,
                }
                for relative in javascript_paths
            ],
        }
        try:
            process = subprocess.run(
                [node, "--max-old-space-size=256", str(script)],
                input=_json(analyzer_request),
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                env=restricted_subprocess_environment(),
            )
        except subprocess.TimeoutExpired as exc:
            raise IntakeError("extraction_analyzer_timeout") from exc
        if process.returncode or process.stderr or len(process.stdout.encode("utf-8")) > 40 * 1024 * 1024:
            raise IntakeError("extraction_analyzer_failed")
        try:
            result = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise IntakeError("extraction_analyzer_failed") from exc
        if result.get("status") != "ok":
            raise IntakeError(str(result.get("error_code") or "extraction_analyzer_failed"))
        return result

    def _candidate_rows(
        self,
        project_id: str,
        run_id: str,
        snapshot: ProjectSnapshot,
        analysis: dict[str, Any],
        inventory: _HtmlInventory,
        profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        entry_rel = self.get_project(project_id)["entry_relpath"]
        html_text = snapshot.text.get(entry_rel, "")
        css_text = "\n".join(
            snapshot.text.get(_local_reference(entry_rel, item), "")
            for item in inventory.stylesheets
        )
        static_paths = {entry_rel}
        static_paths.update(
            _local_reference(entry_rel, item)
            for item in inventory.stylesheets + inventory.resources
        )
        snapshot_by_path = {item.path: item for item in snapshot.entries}
        static_evidence = [
            {
                "path": relative,
                "file_type": snapshot_by_path[relative].file_type,
                "sha256": snapshot_by_path[relative].sha256,
            }
            for relative in sorted(static_paths)
        ]
        for candidate in analysis.get("candidates", []):
            try:
                (
                    candidate["input_contract"],
                    candidate["output_contract"],
                    candidate["error_contract"],
                ) = normalize_capsule_contracts(
                    candidate["capability_kind"],
                    candidate["input_contract"],
                    candidate["output_contract"],
                    candidate["error_contract"],
                )
                fixtures = generate_synthetic_fixtures(candidate["input_contract"])
            except (DataContractError, KeyError, TypeError) as exc:
                rows.append(
                    self._rejected_row(
                        run_id,
                        project_id,
                        str(candidate.get("activation", {}).get("entry_module") or entry_rel),
                        snapshot.digest,
                        str(getattr(exc, "code", "ambiguous_data_contract_v1")),
                        candidate.get("capability_kind"),
                    )
                )
                continue
            modules = candidate.get("javascript_modules", [])
            source_hash = self._candidate_source_hash(static_evidence, modules)
            source_relpath = str(candidate["activation"]["entry_module"])
            raw = "\n".join(
                [str(item.get("source") or "") for item in modules]
                + [str(item) for item in candidate.get("literal_values", [])]
                + [unescape(html_text), css_text]
            )
            sensitivity = self._sensitivity(raw, profile)
            decisions = self._bound_decisions(
                project_id,
                source_relpath,
                source_hash,
                profile=profile,
            )
            status = "extracted"
            reason_codes = list(sensitivity["codes"])
            if sensitivity["secret_count"]:
                status = "rejected"
                reason_codes.append("secret_literal_rejected")
            elif sensitivity["ambiguous_count"]:
                decision = decisions.get("sensitivity")
                if decision == "confirm_real_record_reject":
                    status = "rejected"
                    reason_codes.append("confirmed_real_record_rejected")
                elif decision not in {"confirm_fictional_fixture", "confirm_safe_redaction"}:
                    status = "waiting_user"
                    reason_codes.append("sensitivity_confirmation_required")
                else:
                    reason_codes.append("sensitivity_decision_reused")
            usage_scope: dict[str, Any] = {"kind": "general"}
            if sensitivity["brand_count"]:
                brand = decisions.get("brand")
                if brand == "retain_brand_limited" and profile.get("id"):
                    usage_scope = {
                        "kind": "brand_limited",
                        "brand_profile_id": profile["id"],
                        "brand_profile_digest": profile["digest"],
                    }
                    reason_codes.append("brand_retention_decision_reused")
                elif brand == "remove_brand":
                    reason_codes.append("brand_removal_decision_reused")
                elif status != "rejected":
                    status = "waiting_user"
                    reason_codes.append("brand_confirmation_required")
            contract_sensitivity = self._sensitivity(
                _json(
                    {
                        "input": candidate["input_contract"],
                        "output": candidate["output_contract"],
                        "error": candidate["error_contract"],
                    }
                ),
                profile,
            )
            if status == "extracted" and any(
                contract_sensitivity[key]
                for key in ("secret_count", "ambiguous_count", "brand_count")
            ):
                status = "rejected"
                reason_codes.append("sensitive_contract_identifier_unsupported")
            sanitized = (
                self._sanitize_candidate(candidate, fixtures, usage_scope, static_evidence)
                if status == "extracted"
                else {
                    "schema": "sanitized_candidate.v1",
                    "extraction_contract_version": EXTRACTION_CONTRACT_VERSION,
                    "capability_kind": candidate.get("capability_kind"),
                    "requires_reextract": True,
                }
            )
            rows.append(
                {
                    "review_id": _uuid(),
                    "run_id": run_id,
                    "project_id": project_id,
                    "candidate_id": self._candidate_id(project_id, candidate, source_hash),
                    "candidate_status": status,
                    "source_relpath": source_relpath,
                    "source_location_json": _json(
                        {
                            "entry": source_relpath,
                            **(
                                {
                                    "module_paths": sorted(
                                        str(item.get("path") or "") for item in modules
                                    )
                                }
                                if status == "extracted"
                                else {"module_count": len(modules)}
                            ),
                        }
                    ),
                    "source_hash": source_hash,
                    "sanitized_candidate_json": _json(sanitized),
                    "redaction_summary_json": _json(
                        {
                            "schema": "redaction_summary.v1",
                            "codes": sorted(set(reason_codes)),
                            "secret_count": sensitivity["secret_count"],
                            "ambiguous_count": sensitivity["ambiguous_count"],
                            "brand_count": sensitivity["brand_count"],
                            "brand_profile_id": profile.get("id"),
                            "brand_profile_digest": profile.get("digest"),
                        }
                    ),
                }
            )
        for rejection in analysis.get("rejections", []):
            rows.append(
                self._rejected_row(
                    run_id,
                    project_id,
                    str(rejection.get("entry_module") or entry_rel),
                    snapshot.digest,
                    str(rejection.get("error_code") or "unsupported_extraction_boundary_v1"),
                    rejection.get("capability_kind"),
                )
            )
        return rows

    def _adapter_candidate_row(
        self,
        project_id: str,
        run_id: str,
        candidate: dict[str, Any],
        fixtures: dict[str, Any],
        evidence: dict[str, Any],
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        modules = candidate.get("javascript_modules", [])
        source_relpath = str(evidence["source"]["module_relpath"])
        source_hash = self._candidate_source_hash([], modules)
        raw = "\n".join(
            [str(item.get("source") or "") for item in modules]
            + [str(item) for item in candidate.get("literal_values", [])]
        )
        sensitivity = self._sensitivity(raw, profile)
        decisions = self._bound_decisions(
            project_id,
            source_relpath,
            source_hash,
            profile=profile,
        )
        status = "extracted"
        reason_codes = list(sensitivity["codes"])
        if sensitivity["secret_count"]:
            status = "rejected"
            reason_codes.append("secret_literal_rejected")
        elif sensitivity["ambiguous_count"]:
            decision = decisions.get("sensitivity")
            if decision == "confirm_real_record_reject":
                status = "rejected"
                reason_codes.append("confirmed_real_record_rejected")
            elif decision not in {"confirm_fictional_fixture", "confirm_safe_redaction"}:
                status = "waiting_user"
                reason_codes.append("sensitivity_confirmation_required")
            else:
                reason_codes.append("sensitivity_decision_reused")
        usage_scope: dict[str, Any] = {"kind": "general"}
        if sensitivity["brand_count"]:
            brand = decisions.get("brand")
            if brand == "retain_brand_limited" and profile.get("id"):
                usage_scope = {
                    "kind": "brand_limited",
                    "brand_profile_id": profile["id"],
                    "brand_profile_digest": profile["digest"],
                }
                reason_codes.append("brand_retention_decision_reused")
            elif brand == "remove_brand":
                reason_codes.append("brand_removal_decision_reused")
            elif status != "rejected":
                status = "waiting_user"
                reason_codes.append("brand_confirmation_required")
        contract_sensitivity = self._sensitivity(
            _json(
                {
                    "input": candidate["input_contract"],
                    "output": candidate["output_contract"],
                    "error": candidate["error_contract"],
                }
            ),
            profile,
        )
        if status == "extracted" and any(
            contract_sensitivity[key]
            for key in ("secret_count", "ambiguous_count", "brand_count")
        ):
            status = "rejected"
            reason_codes.append("sensitive_contract_identifier_unsupported")
        static_evidence = [
            {
                "path": row["logical_path"],
                "file_type": "text",
                "sha256": row["sha256"],
            }
            for row in evidence["closure"]
        ]
        if status == "extracted":
            sanitized = self._sanitize_candidate(
                candidate, fixtures, usage_scope, static_evidence
            )
            sanitized.update(
                {
                    "candidate_origin": "deterministic_computation_adapter",
                    "adapter_contract_version": COMPUTATION_ADAPTER_CONTRACT_VERSION,
                    "adapter_evidence": evidence,
                }
            )
        else:
            sanitized = {
                "schema": "sanitized_candidate.v1",
                "extraction_contract_version": EXTRACTION_CONTRACT_VERSION,
                "candidate_origin": "deterministic_computation_adapter",
                "adapter_contract_version": COMPUTATION_ADAPTER_CONTRACT_VERSION,
                "capability_kind": "computation",
                "requires_reextract": True,
            }
        return {
            "review_id": _uuid(),
            "run_id": run_id,
            "project_id": project_id,
            "candidate_id": self._candidate_id(project_id, candidate, source_hash),
            "candidate_status": status,
            "source_relpath": source_relpath,
            "source_location_json": _json(
                {
                    "entry": source_relpath,
                    **(
                        {
                            "module_paths": sorted(
                                str(item.get("path") or "") for item in modules
                            )
                        }
                        if status == "extracted"
                        else {"module_count": len(modules)}
                    ),
                }
            ),
            "source_hash": source_hash,
            "sanitized_candidate_json": _json(sanitized),
            "redaction_summary_json": _json(
                {
                    "schema": "redaction_summary.v1",
                    "codes": sorted(set(reason_codes)),
                    "secret_count": sensitivity["secret_count"],
                    "ambiguous_count": sensitivity["ambiguous_count"],
                    "brand_count": sensitivity["brand_count"],
                    "brand_profile_id": profile.get("id"),
                    "brand_profile_digest": profile.get("digest"),
                }
            ),
        }

    def _sanitize_candidate(
        self,
        candidate: dict[str, Any],
        fixtures: dict[str, Any],
        usage_scope: dict[str, Any],
        static_evidence: list[dict[str, str]],
    ) -> dict[str, Any]:
        modules = candidate.get("javascript_modules", [])
        return {
            "schema": "sanitized_candidate.v1",
            "extraction_contract_version": EXTRACTION_CONTRACT_VERSION,
            "capability_kind": candidate["capability_kind"],
            "activation": candidate["activation"],
            "input_contract": candidate["input_contract"],
            "output_contract": candidate["output_contract"],
            "error_contract": candidate["error_contract"],
            "dom_scope_summary": {
                "root_contract": candidate["dom_scope"].get("root_contract"),
                "selector_count": len(candidate["dom_scope"].get("selectors", [])),
                "class_count": len(candidate["dom_scope"].get("classes", [])),
                "attributes": sorted(candidate["dom_scope"].get("attributes", [])),
                "events": sorted(candidate["dom_scope"].get("events", [])),
            },
            "usage_scope": usage_scope,
            "static_evidence": static_evidence,
            "module_evidence": [
                {
                    "path": item["path"],
                    "sha256": hashlib.sha256(item["source"].encode("utf-8")).hexdigest(),
                }
                for item in sorted(modules, key=lambda row: row["path"])
            ],
            "dependency_edge_types": sorted(
                set(str(item.get("type") or "static_import") for item in candidate.get("dependencies", []))
                or {"static_import"}
            ),
            "fixture_summary": {
                "schema": fixtures["schema"],
                "normal_count": len(fixtures["normal"]),
                "boundary_count": len(fixtures["boundary"]),
                "invalid_count": len(fixtures["invalid"]),
            },
        }

    def _rejected_row(
        self,
        run_id: str,
        project_id: str,
        source_relpath: str,
        source_hash: str,
        error_code: str,
        capability_kind: Any,
    ) -> dict[str, Any]:
        return {
            "review_id": _uuid(),
            "run_id": run_id,
            "project_id": project_id,
            "candidate_id": f"candidate_{hashlib.sha256(f'{project_id}:{source_relpath}:{error_code}'.encode()).hexdigest()[:20]}",
            "candidate_status": "rejected",
            "source_relpath": source_relpath,
            "source_location_json": _json({"entry": source_relpath, "module_paths": []}),
            "source_hash": source_hash,
            "sanitized_candidate_json": _json(
                {
                    "schema": "sanitized_candidate.v1",
                    "extraction_contract_version": EXTRACTION_CONTRACT_VERSION,
                    "capability_kind": capability_kind,
                    "rejected": True,
                }
            ),
            "redaction_summary_json": _json(
                {
                    "schema": "redaction_summary.v1",
                    "codes": [error_code],
                    "secret_count": 0,
                    "ambiguous_count": 0,
                    "brand_count": 0,
                }
            ),
        }

    def _commit_candidate_rows(
        self,
        run_id: str,
        project_id: str,
        snapshot_before: str,
        snapshot_after: str,
        status: str,
        counts: dict[str, Any],
        rows: list[dict[str, Any]],
        *,
        update_project_snapshot: bool = True,
    ) -> list[str]:
        now = _now()
        with self.store.transaction() as connection:
            for row in rows:
                connection.execute(
                    "INSERT INTO review_items (review_id, run_id, project_id, candidate_id, "
                    "candidate_status, source_relpath, source_location_json, source_hash, "
                    "redaction_rules_version, sanitized_candidate_json, redaction_summary_json, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["review_id"],
                        run_id,
                        project_id,
                        row["candidate_id"],
                        row["candidate_status"],
                        row["source_relpath"],
                        row["source_location_json"],
                        row["source_hash"],
                        REDACTION_RULES_VERSION,
                        row["sanitized_candidate_json"],
                        row["redaction_summary_json"],
                        now,
                        now,
                    ),
                )
            if update_project_snapshot:
                connection.execute(
                    "UPDATE projects SET last_snapshot_hash = ?, updated_at = ? WHERE project_id = ?",
                    (snapshot_after, now, project_id),
                )
            connection.execute(
                "UPDATE intake_runs SET status = ?, snapshot_before = ?, snapshot_after = ?, "
                "counts_json = ?, completed_at = ? WHERE run_id = ?",
                (status, snapshot_before, snapshot_after, _json(counts), now, run_id),
            )
            self.store.bump_revision(connection)
        return [row["review_id"] for row in rows]

    def _bound_decisions(
        self,
        project_id: str,
        source_relpath: str,
        source_hash: str,
        *,
        profile: dict[str, Any] | None = None,
    ) -> dict[str, str | None]:
        if profile is None:
            context = self._project_context(project_id, allow_unconfirmed_children=True)
            profile = self._effective_brand_profile(context.project, context.source_root)
        with self.store.read_connection() as connection:
            rows = connection.execute(
                "SELECT sensitivity_decision, brand_decision, asset_decision, "
                "redaction_summary_json FROM review_items "
                "WHERE project_id = ? AND source_relpath = ? AND source_hash = ? "
                "AND redaction_rules_version = ? ORDER BY created_at DESC",
                (project_id, source_relpath, source_hash, REDACTION_RULES_VERSION),
            ).fetchall()
        sensitivity_values = {str(row[0]) for row in rows if row[0] is not None}
        current_brand = (profile.get("id"), profile.get("digest"))
        brand_values = {
            str(row[1])
            for row in rows
            if row[1] is not None
            and self._review_brand_binding(row[3]) == current_brand
        }
        asset_values = {str(row[2]) for row in rows if row[2] is not None}
        if "confirm_real_record_reject" in sensitivity_values:
            sensitivity = "confirm_real_record_reject"
        elif len(sensitivity_values) > 1:
            raise IntakeError("sensitivity_decision_conflict")
        else:
            sensitivity = next(iter(sensitivity_values), None)
        if len(brand_values) > 1:
            raise IntakeError("brand_decision_conflict")
        if len(asset_values) > 1:
            raise IntakeError("asset_decision_conflict")
        brand = next(iter(brand_values), None)
        asset = next(iter(asset_values), None)
        return {"sensitivity": sensitivity, "brand": brand, "asset": asset}

    @staticmethod
    def _review_brand_binding(
        summary_json: str,
    ) -> tuple[str | None, str | None] | None:
        try:
            summary = json.loads(summary_json)
        except (json.JSONDecodeError, TypeError):
            return None
        if (
            type(summary) is not dict
            or "brand_profile_id" not in summary
            or "brand_profile_digest" not in summary
        ):
            return None
        profile_id = summary["brand_profile_id"]
        profile_digest = summary["brand_profile_digest"]
        if profile_id is not None and type(profile_id) is not str:
            return None
        if profile_digest is not None and type(profile_digest) is not str:
            return None
        return profile_id, profile_digest

    @staticmethod
    def _allowed_review_decisions(row: Any) -> frozenset[str]:
        try:
            summary = json.loads(row["redaction_summary_json"])
            candidate = json.loads(row["sanitized_candidate_json"])
        except (json.JSONDecodeError, TypeError):
            return frozenset()
        if type(summary) is not dict or type(candidate) is not dict:
            return frozenset()
        raw_codes = summary.get("codes")
        if type(raw_codes) is not list or not all(type(code) is str for code in raw_codes):
            return frozenset()
        codes = set(raw_codes)
        failure = candidate.get("stage3_failure")
        failure_code = failure.get("error_code") if type(failure) is dict else None
        capture_v2 = (
            candidate.get("candidate_origin")
            == "deterministic_computation_adapter"
            and candidate.get("adapter_contract_version")
            == "computation_adapter.v2"
        )
        allowed: set[str] = set()
        if (
            "sensitivity_confirmation_required" in codes
            or failure_code == "sensitivity_confirmation_required_stage3"
        ):
            allowed.update(
                {"confirm_fictional_fixture", "confirm_real_record_reject"}
                if capture_v2
                else _SENSITIVITY_DECISIONS
            )
        if (
            "brand_confirmation_required" in codes
            or failure_code == "brand_confirmation_required"
        ):
            allowed.update(
                {"retain_brand_limited"} if capture_v2 else _BRAND_DECISIONS
            )
        if failure_code == "asset_content_confirmation_required_stage3":
            allowed.update(_ASSET_DECISIONS)
        if "enumeration_confirmation_required" in codes:
            allowed.update(_ENUM_DECISIONS)
        return frozenset(allowed)

    @staticmethod
    def _sensitivity(
        raw: str,
        profile: dict[str, Any],
        *,
        literal_raw: str | None = None,
    ) -> dict[str, Any]:
        identity_raw = raw if literal_raw is None else literal_raw
        secret_count = len(_SECRET.findall(raw))
        email_count = len(_EMAIL.findall(raw))
        phone_count = len(_PHONE.findall(identity_raw))
        card_count = len(_CARD.findall(identity_raw))
        record_count = len(_RECORD.findall(raw))
        lowered = raw.casefold()
        brand_count = sum(lowered.count(term.casefold()) for term in profile.get("terms", []))
        codes = []
        if email_count:
            codes.append("email_literal")
        if phone_count:
            codes.append("phone_literal")
        if card_count:
            codes.append("card_literal")
        if record_count:
            codes.append("record_like_literal")
        if brand_count:
            codes.append("brand_literal")
        return {
            "secret_count": secret_count,
            "ambiguous_count": email_count + phone_count + card_count + record_count,
            "brand_count": brand_count,
            "codes": codes,
        }

    @staticmethod
    def _candidate_source_hash(
        static_evidence: list[dict[str, str]],
        modules: list[dict[str, Any]],
    ) -> str:
        rows = [
            f"{item['path']}:{item['sha256']}"
            for item in sorted(static_evidence, key=lambda row: row["path"])
        ]
        rows.extend(
            f"{item['path']}:{hashlib.sha256(item['source'].encode('utf-8')).hexdigest()}"
            for item in sorted(modules, key=lambda row: row["path"])
        )
        return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()

    @staticmethod
    def _candidate_id(
        project_id: str, candidate: dict[str, Any], source_hash: str
    ) -> str:
        identity = _json(
            {
                "project_id": project_id,
                "capability_kind": candidate["capability_kind"],
                "activation": candidate["activation"],
                "source_hash": source_hash,
            }
        )
        return f"candidate_{hashlib.sha256(identity.encode()).hexdigest()[:20]}"

    def _project_context(
        self, project_id: str, *, allow_unconfirmed_children: bool = False
    ) -> ProjectContext:
        with self.store.read_connection() as connection:
            project_row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if project_row is None:
                raise IntakeError("project_not_found")
            source_row = connection.execute(
                "SELECT * FROM source_roots WHERE root_id = ?", (project_row["source_root_id"],)
            ).fetchone()
            children = connection.execute(
                "SELECT project_relpath, project_state FROM projects "
                "WHERE source_root_id = ? AND project_id <> ?",
                (project_row["source_root_id"], project_id),
            ).fetchall()
        project = dict(project_row)
        source_root = dict(source_row)
        root = Path(source_root["current_path"])
        if not root.is_dir():
            self._mark_root_missing(str(source_root["root_id"]))
            raise IntakeError("source_root_missing")
        project_rel = str(project["project_relpath"])
        if project_rel != ".":
            self._reject_symlink_components(root, project_rel)
        project_path = root if project_rel == "." else root / _safe_relative(project_rel)
        if project_path.is_symlink() or not project_path.is_dir():
            self._set_project_state(project_id, "source_missing")
            raise IntakeError("project_source_missing")
        resolved = project_path.resolve()
        if resolved != root.resolve() and not str(resolved).startswith(f"{root.resolve()}{os.sep}"):
            raise IntakeError("project_path_outside_source_root")
        entry = resolved.joinpath(
            *PurePosixPath(str(project["entry_relpath"])).parts
        )
        self._reject_symlink_components(resolved, str(project["entry_relpath"]))
        if entry.is_symlink() or not entry.is_file():
            self._set_project_state(project_id, "source_missing")
            raise IntakeError("project_entry_missing")
        excluded: list[str] = []
        base = PurePosixPath(project_rel)
        for child in children:
            child_rel = PurePosixPath(str(child["project_relpath"]))
            try:
                relative = child_rel.relative_to(base)
            except ValueError:
                continue
            if relative == PurePosixPath("."):
                continue
            if child["project_state"] == "discovered_unconfirmed" and not allow_unconfirmed_children:
                raise IntakeError("discovered_unconfirmed")
            excluded.append(relative.as_posix())
        return ProjectContext(project, source_root, resolved, tuple(sorted(set(excluded))))

    def _validate_source_root_path(self, source_root: Path) -> None:
        try:
            state_dir().resolve().relative_to(source_root)
        except ValueError:
            pass
        else:
            raise IntakeError("reweave_state_dir_inside_source_root")
        for protected in (
            self.store.path.resolve(),
            (self.store.path.parent / BACKUP_DIRECTORY).resolve(),
        ):
            if protected == source_root or source_root in protected.parents:
                raise IntakeError("reweave_store_inside_source_root")

    def _reject_overlapping_source_root(
        self,
        connection: Any,
        source_root: Path,
        *,
        exclude_root_id: str | None = None,
    ) -> None:
        rows = connection.execute(
            "SELECT root_id, current_path FROM source_roots"
        ).fetchall()
        protected = (
            self.store.path.resolve(),
            (self.store.path.parent / BACKUP_DIRECTORY).resolve(),
        )
        for row in rows:
            if exclude_root_id is not None and str(row["root_id"]) == exclude_root_id:
                continue
            existing = Path(row["current_path"]).resolve()
            if any(path == existing or existing in path.parents for path in protected):
                raise IntakeError("reweave_store_inside_source_root")
            if existing == source_root or existing in source_root.parents or source_root in existing.parents:
                raise IntakeError("source_root_overlap")

    def _validate_static_inventory(
        self, context: ProjectContext, inventory: _HtmlInventory
    ) -> None:
        entry_rel = str(context.project["entry_relpath"])
        if inventory.inline_script:
            raise IntakeError("inline_script_unsupported_v1")
        for script_type, source in inventory.scripts:
            if script_type != "module":
                raise IntakeError("classic_script_unsupported_v1")
            relative = _local_reference(entry_rel, source)
            if PurePosixPath(relative).suffix.lower() not in {".js", ".mjs"}:
                raise IntakeError("static_closure_resource_unsupported_v1")
            self._require_local_file(context.path, relative)
        for reference in inventory.stylesheets:
            relative = _local_reference(entry_rel, reference)
            if PurePosixPath(relative).suffix.lower() != ".css":
                raise IntakeError("static_closure_resource_unsupported_v1")
            self._require_local_file(context.path, relative)
        for reference in inventory.resources:
            relative = _local_reference(entry_rel, reference)
            if PurePosixPath(relative).suffix.lower() not in _ASSET_SUFFIXES:
                raise IntakeError("static_closure_resource_unsupported_v1")
            self._require_local_file(context.path, relative)

    @staticmethod
    def _reject_symlink_components(root: Path, relative: str) -> None:
        current = root
        for part in PurePosixPath(relative).parts:
            current /= part
            if current.is_symlink():
                raise IntakeError("static_closure_symlink_forbidden")

    @staticmethod
    def _require_local_file(root: Path, relative: str) -> None:
        parts = PurePosixPath(relative).parts
        path_value = root.joinpath(*parts)
        current = root
        for part in parts:
            current /= part
            if current.is_symlink():
                raise IntakeError("static_closure_symlink_forbidden")
        if not path_value.is_file():
            raise IntakeError("static_closure_file_missing")
        resolved = path_value.resolve()
        if resolved != root and not str(resolved).startswith(f"{root}{os.sep}"):
            raise IntakeError("static_closure_path_outside_project")

    @staticmethod
    def _html_entries(root: Path) -> Iterator[Path]:
        stack: list[tuple[Path, int]] = [(root, 0)]
        count = 0
        while stack:
            directory, depth = stack.pop()
            try:
                entries = sorted(directory.iterdir(), key=lambda item: item.name.casefold(), reverse=True)
            except OSError as exc:
                raise IntakeError("source_access_denied") from exc
            for item in entries:
                if item.is_symlink():
                    continue
                if item.is_dir() and not _is_ignored_directory(item.name):
                    if depth >= MAX_DEPTH:
                        raise IntakeError("source_limit_exceeded")
                    stack.append((item, depth + 1))
                elif item.is_file() and item.suffix.lower() == ".html":
                    count += 1
                    if count > MAX_FILES:
                        raise IntakeError("source_limit_exceeded")
                    yield item

    @staticmethod
    def _walk_project_files(root: Path, excluded: tuple[str, ...]) -> Iterator[Path]:
        excluded_paths = {PurePosixPath(item) for item in excluded}
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            directory, depth = stack.pop()
            try:
                entries = sorted(directory.iterdir(), key=lambda item: item.name.casefold(), reverse=True)
            except OSError as exc:
                raise IntakeError("source_access_denied") from exc
            for item in entries:
                relative = PurePosixPath(item.relative_to(root).as_posix())
                if any(relative == value or value in relative.parents for value in excluded_paths):
                    continue
                if item.is_symlink():
                    continue
                if item.is_dir():
                    if _is_ignored_directory(item.name):
                        continue
                    if depth >= MAX_DEPTH:
                        raise IntakeError("source_limit_exceeded")
                    stack.append((item, depth + 1))
                elif item.is_file():
                    yield item

    def _read_utf8(self, path_value: Path, *, root: Path, relative: str) -> str:
        try:
            content, _mtime_ns = self._read_stable_bytes(
                path_value,
                root=root,
                relative=relative,
            )
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IntakeError("source_utf8_invalid") from exc

    def _read_stable_bytes(
        self,
        path_value: Path,
        *,
        root: Path,
        relative: str,
    ) -> tuple[bytes, int]:
        """Read one regular source file without following a replace-time symlink."""
        root_absolute = Path(os.path.abspath(root))

        def checked_root_state() -> tuple[os.stat_result, Path]:
            try:
                state = root_absolute.lstat()
                resolved = root_absolute.resolve(strict=True)
            except OSError as exc:
                self._raise_source_read_error(exc)
            if not stat.S_ISDIR(state.st_mode):
                if stat.S_ISLNK(state.st_mode):
                    raise IntakeError("static_closure_symlink_forbidden")
                raise IntakeError("source_changed_during_scan")
            if resolved != root_absolute:
                raise IntakeError("static_closure_symlink_forbidden")
            return state, resolved

        root_before, root_resolved = checked_root_state()
        self._reject_symlink_components(root, relative)

        def checked_path_state() -> tuple[os.stat_result, Path]:
            try:
                state = path_value.lstat()
                resolved = path_value.resolve(strict=True)
            except OSError as exc:
                self._raise_source_read_error(exc)
            if not stat.S_ISREG(state.st_mode):
                if stat.S_ISLNK(state.st_mode):
                    raise IntakeError("static_closure_symlink_forbidden")
                raise IntakeError("source_changed_during_scan")
            if resolved != root_resolved and root_resolved not in resolved.parents:
                raise IntakeError("static_closure_path_outside_project")
            return state, resolved

        before, resolved_before = checked_path_state()
        if before.st_size > MAX_FILE_SIZE:
            raise IntakeError("source_limit_exceeded")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path_value, flags)
        except OSError as exc:
            self._raise_source_read_error(exc)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or self._file_state(opened) != self._file_state(
                before
            ):
                raise IntakeError("source_changed_during_scan")
            chunks: list[bytes] = []
            remaining = MAX_FILE_SIZE + 1
            while remaining:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            after_open = os.fstat(descriptor)
        finally:
            os.close(descriptor)

        content = b"".join(chunks)
        after, resolved_after = checked_path_state()
        root_after, root_resolved_after = checked_root_state()
        self._reject_symlink_components(root, relative)
        if (
            self._file_state(root_before) != self._file_state(root_after)
            or root_resolved != root_resolved_after
            or self._file_state(opened) != self._file_state(after_open)
            or self._file_state(after_open) != self._file_state(after)
            or resolved_before != resolved_after
            or len(content) != after_open.st_size
        ):
            raise IntakeError("source_changed_during_scan")
        if len(content) > MAX_FILE_SIZE:
            raise IntakeError("source_limit_exceeded")
        return content, int(after_open.st_mtime_ns)

    @staticmethod
    def _file_state(value: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            int(value.st_dev),
            int(value.st_ino),
            stat.S_IFMT(value.st_mode),
            int(value.st_size),
            int(value.st_mtime_ns),
        )

    @staticmethod
    def _raise_source_read_error(exc: OSError) -> None:
        if exc.errno == errno.ELOOP:
            raise IntakeError("static_closure_symlink_forbidden") from exc
        if exc.errno in {errno.EACCES, errno.EPERM}:
            raise IntakeError("source_access_denied") from exc
        raise IntakeError("source_changed_during_scan") from exc

    @staticmethod
    def _discovery_reasons(entry: Path, inventory: _HtmlInventory) -> list[str]:
        reasons = ["static_index_entry" if entry.name.lower() == "index.html" else "nested_static_entry"]
        sources = [source for _kind, source in inventory.scripts]
        if any(source.lower().endswith((".tsx", ".ts", ".jsx")) for source in sources):
            reasons.append("framework_source")
        elif any(kind == "module" and source.lower().endswith((".js", ".mjs")) for kind, source in inventory.scripts):
            reasons.append("local_module_entry")
        return reasons

    @staticmethod
    def _profile_fields(
        profile: dict[str, Any] | None, *, previous: dict[str, Any] | None
    ) -> dict[str, Any]:
        if profile is None:
            return {"id": None, "json": None, "digest": None, "version": 0}
        if type(profile) is not dict:
            raise IntakeError("brand_profile_invalid")
        encoded = _json(profile)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        previous_id = previous.get("brand_profile_id") if previous else None
        previous_version = int(previous.get("brand_profile_version") or 0) if previous else 0
        return {
            "id": previous_id or _uuid(),
            "json": encoded,
            "digest": digest,
            "version": previous_version + 1,
        }

    @staticmethod
    def _effective_brand_profile(
        project: dict[str, Any], source_root: dict[str, Any]
    ) -> dict[str, Any]:
        mode = project.get("brand_mode")
        if mode == "extend":
            raise IntakeError("project_brand_extend_unsupported_v1")
        row = source_root if mode == "inherit" else project
        if mode == "clear" or not row.get("brand_profile_id"):
            return {"id": None, "digest": None, "terms": []}
        try:
            profile = json.loads(row.get("brand_profile_json") or "{}")
        except json.JSONDecodeError:
            raise IntakeError("brand_profile_invalid")
        terms: list[str] = []

        def collect(value: Any) -> None:
            if type(value) is str:
                cleaned = value.strip()
                if cleaned and not cleaned.startswith(("#", "http://", "https://")):
                    terms.append(cleaned)
            elif type(value) is list:
                for item in value:
                    collect(item)
            elif type(value) is dict:
                for item in value.values():
                    collect(item)

        collect(profile)
        return {
            "id": row["brand_profile_id"],
            "digest": row["brand_profile_digest"],
            "terms": sorted(set(terms)),
        }

    def _create_run(self, project_id: str) -> str:
        run_id = _uuid()
        now = _now()
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO intake_runs (run_id, project_id, run_kind, status, "
                "extraction_contract_version, redaction_rules_version, security_rules_version, "
                "supervision_rules_version, validation_contract_version, canonicalization_version, "
                "counts_json, created_at) VALUES (?, ?, 'refresh_project', 'queued', ?, ?, ?, ?, ?, ?, '{}', ?)",
                (
                    run_id,
                    project_id,
                    EXTRACTION_CONTRACT_VERSION,
                    REDACTION_RULES_VERSION,
                    SECURITY_RULES_VERSION,
                    SUPERVISION_RULES_VERSION,
                    VALIDATION_CONTRACT_VERSION,
                    CANONICALIZATION_VERSION,
                    now,
                ),
            )
            self.store.bump_revision(connection)
        return run_id

    def _set_run(self, run_id: str, status: str, *, started_at: str | None = None) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE intake_runs SET status = ?, started_at = COALESCE(?, started_at) WHERE run_id = ?",
                (status, started_at, run_id),
            )
            self.store.bump_revision(connection)

    def _finish_run(
        self,
        run_id: str,
        status: str,
        before: str,
        after: str,
        counts: dict[str, Any],
    ) -> None:
        now = _now()
        with self.store.transaction() as connection:
            project_id = connection.execute(
                "SELECT project_id FROM intake_runs WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            connection.execute(
                "UPDATE intake_runs SET status = ?, snapshot_before = ?, snapshot_after = ?, "
                "counts_json = ?, completed_at = ? WHERE run_id = ?",
                (status, before, after, _json(counts), now, run_id),
            )
            connection.execute(
                "UPDATE projects SET last_snapshot_hash = ?, updated_at = ? WHERE project_id = ?",
                (after, now, project_id),
            )
            self.store.bump_revision(connection)

    def _fail_run(self, run_id: str, code: str) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE intake_runs SET status = 'failed', error_code = ?, completed_at = ? "
                "WHERE run_id = ? AND status IN ('queued', 'running')",
                (code, _now(), run_id),
            )
            self.store.bump_revision(connection)

    def _cancel_if_requested(
        self, run_id: str, cancel_check: Callable[[], bool] | None
    ) -> None:
        if cancel_check and cancel_check():
            with self.store.transaction() as connection:
                connection.execute(
                    "UPDATE intake_runs SET status = 'cancelled', completed_at = ?, "
                    "error_code = 'cancelled_by_user' WHERE run_id = ?",
                    (_now(), run_id),
                )
                self.store.bump_revision(connection)
            raise IntakeError("intake_cancelled")

    def _is_no_change(
        self,
        project_id: str,
        snapshot_hash: str,
        brand_profile_id: str | None,
        brand_digest: str | None,
    ) -> bool:
        with self.store.read_connection() as connection:
            project = connection.execute(
                "SELECT last_snapshot_hash FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            run = connection.execute(
                "SELECT * FROM intake_runs WHERE project_id = ? AND status IN ('completed', 'no_change') "
                "ORDER BY created_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        if project is None or project[0] != snapshot_hash or run is None:
            return False
        try:
            previous_counts = json.loads(run["counts_json"])
            previous_profile_id = previous_counts.get("effective_brand_profile_id")
            previous_digest = previous_counts.get("effective_brand_profile_digest")
        except (json.JSONDecodeError, TypeError):
            return False
        return (
            run["extraction_contract_version"] == EXTRACTION_CONTRACT_VERSION
            and run["redaction_rules_version"] == REDACTION_RULES_VERSION
            and run["security_rules_version"] == SECURITY_RULES_VERSION
            and run["supervision_rules_version"] == SUPERVISION_RULES_VERSION
            and run["validation_contract_version"] == VALIDATION_CONTRACT_VERSION
            and run["canonicalization_version"] == CANONICALIZATION_VERSION
            and previous_profile_id == brand_profile_id
            and previous_digest == brand_digest
        )

    def _set_project_state(self, project_id: str, state: str) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE projects SET project_state = ?, updated_at = ? WHERE project_id = ?",
                (state, _now(), project_id),
            )
            self.store.bump_revision(connection)

    def _mark_root_missing(self, root_id: str) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE source_roots SET status = 'source_missing', updated_at = ? WHERE root_id = ?",
                (_now(), root_id),
            )
            connection.execute(
                "UPDATE projects SET project_state = 'source_missing', updated_at = ? WHERE source_root_id = ?",
                (_now(), root_id),
            )
            self.store.bump_revision(connection)
