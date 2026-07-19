"""Read-only Static Web target profiling and review-only Patch generation."""

from __future__ import annotations

import base64
import difflib
import hashlib
import html
import json
import os
import re
import shutil
import stat
import subprocess
import unicodedata
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from pimos_lite.reweave_capsule_intake import (
    MAX_DEPTH,
    MAX_FILES,
    MAX_SUPPORTED_BYTES,
    _ASSET_SUFFIXES,
    _TEXT_SUFFIXES,
    _is_ignored_directory,
    IntakeError,
    ReweaveCapsuleIntake,
)
from pimos_lite.reweave_process_environment import restricted_subprocess_environment
from pimos_lite.reweave_source_registry import state_dir


TARGET_PROFILE_VERSION = "static_web_target_profile.v1"
TARGET_PATCH_VERSION = "static_web_target_patch.v1"
WEAVE_PLAN_VERSION = "static_web_weave_plan.v1"
TARGET_ADAPTER_VERSION = "static_web_iframe_embed.v1"
TARGET_AUTHORIZATION_MODE = "review_patch_only"

_SUPPORTED_SUFFIXES = _TEXT_SUFFIXES | _ASSET_SUFFIXES
_PATH_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_CSS_RESOURCE = re.compile(r"(?is)@import\b|(?:url|image-set)\s*\(")
_BODY_CLOSE = re.compile(r"(?i)</body\s*>")
_PATCH_MARKER = re.compile(r"(?i)\bdata-reweave-plan\s*=")
_PATCH_UNSAFE_CONTEXTS = {
    "head",
    "math",
    "noembed",
    "noscript",
    "plaintext",
    "script",
    "select",
    "style",
    "table",
    "template",
    "textarea",
    "title",
    "xmp",
}


class StaticWebTargetError(RuntimeError):
    def __init__(self, code: str, evidence: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.evidence = dict(evidence or {})


class _TargetHTMLInventory(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source = source
        self.line_starts = [0]
        self.line_starts.extend(
            match.end() for match in re.finditer("\n", source)
        )
        self.references: list[tuple[str, str, str, str]] = []
        self.body_end_positions: list[int] = []
        self.patch_contexts: list[str] = []
        self.inline_script = False
        self.inline_style = False
        self.unsupported_feature: str | None = None
        self.csp = False

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        lowered = tag.casefold()
        if lowered in _PATCH_UNSAFE_CONTEXTS:
            self.patch_contexts.append(lowered)
        names = [name.casefold() for name, _value in attrs]
        if len(names) != len(set(names)):
            self.unsupported_feature = self.unsupported_feature or "duplicate_attribute"
        values = {
            name.casefold(): str(value or "").strip() for name, value in attrs
        }
        if any(name.startswith("on") for name in values):
            self.unsupported_feature = self.unsupported_feature or "inline_event"
        if (
            "style" in values
            or "srcset" in values
            or "background" in values
            or values.get("formaction")
            or values.get("ping")
        ):
            self.unsupported_feature = self.unsupported_feature or "inline_resource"
        if lowered == "base":
            self.unsupported_feature = self.unsupported_feature or "base_element"
        if lowered == "style":
            self.inline_style = True
        if lowered in {
            "embed",
            "frame",
            "frameset",
            "iframe",
            "object",
            "portal",
            "svg",
        }:
            self.unsupported_feature = self.unsupported_feature or "embedded_document"
        if lowered == "form" and values.get("action"):
            self.unsupported_feature = self.unsupported_feature or "form_action"
        if lowered == "meta":
            http_equiv = values.get("http-equiv", "").casefold()
            if http_equiv == "content-security-policy":
                self.csp = True
            if http_equiv == "refresh":
                self.unsupported_feature = self.unsupported_feature or "meta_refresh"
        if lowered == "script":
            source = values.get("src", "")
            if not source:
                self.inline_script = True
            else:
                self.references.append(
                    (lowered, "src", source, values.get("type", "").casefold())
                )
        if lowered == "link" and values.get("href"):
            if "stylesheet" not in values.get("rel", "").casefold().split():
                self.unsupported_feature = self.unsupported_feature or "link_resource"
            else:
                self.references.append((lowered, "href", values["href"], "stylesheet"))
        for attribute in ("src", "poster"):
            if lowered in {
                "audio",
                "img",
                "input",
                "source",
                "track",
                "video",
            } and values.get(attribute):
                self.references.append((lowered, attribute, values[attribute], "asset"))

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered == "body":
            if self.patch_contexts:
                return
            line, column = self.getpos()
            if line < 1 or line > len(self.line_starts):
                return
            position = self.line_starts[line - 1] + column
            if _BODY_CLOSE.match(self.source, position):
                self.body_end_positions.append(position)
            return
        if lowered not in _PATCH_UNSAFE_CONTEXTS:
            return
        if not self.patch_contexts or self.patch_contexts[-1] != lowered:
            self.unsupported_feature = self.unsupported_feature or "html_parse_context"
            return
        self.patch_contexts.pop()


def analyze_static_web_target(
    target_path: str | Path, entry_relpath: str
) -> dict[str, Any]:
    """Return a stable, source-free target profile without writing the target."""

    before = capture_static_web_target(target_path, entry_relpath)
    after = capture_static_web_target(target_path, entry_relpath)
    if before["snapshot_sha256"] != after["snapshot_sha256"]:
        raise StaticWebTargetError(
            "target_changed_during_analysis", {"phase": "consistency"}
        )
    profile = dict(before["profile"])
    profile["source_unchanged"] = True
    return profile


def capture_static_web_target(
    target_path: str | Path, entry_relpath: str
) -> dict[str, Any]:
    """Capture one bounded in-memory snapshot for a selected Static Web entry."""

    root = _target_root(target_path)
    entry = _logical_path(entry_relpath)
    if PurePosixPath(entry).suffix.casefold() != ".html":
        raise StaticWebTargetError(
            "target_entry_unsupported_v1", {"phase": "entry", "logical_path": entry}
        )

    reader = ReweaveCapsuleIntake()
    seen = (set(), set(), set(), set())
    files: dict[str, bytes] = {}
    file_rows: list[dict[str, Any]] = []
    path_rows: list[dict[str, str]] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    supported_count = 0
    supported_bytes = 0

    while stack:
        directory, depth = stack.pop()
        try:
            children = sorted(
                directory.iterdir(), key=lambda item: item.name.encode("utf-8")
            )
        except (OSError, UnicodeEncodeError) as exc:
            raise StaticWebTargetError(
                "target_path_invalid", {"phase": "path"}
            ) from exc
        for child in children:
            logical = child.relative_to(root).as_posix()
            _logical_path(logical)
            _register_path(logical, seen)
            try:
                state = child.lstat()
            except OSError as exc:
                raise StaticWebTargetError(
                    "target_changed_during_analysis",
                    {"phase": "snapshot", "logical_path": logical},
                ) from exc
            if stat.S_ISLNK(state.st_mode):
                raise StaticWebTargetError(
                    "target_symlink_forbidden",
                    {"phase": "path", "logical_path": logical},
                )
            if stat.S_ISDIR(state.st_mode):
                path_rows.append({"path": logical, "kind": "directory"})
                if _is_ignored_directory(child.name):
                    continue
                if depth >= MAX_DEPTH:
                    raise StaticWebTargetError(
                        "target_limit_exceeded", {"phase": "snapshot"}
                    )
                stack.append((child, depth + 1))
                continue
            if not stat.S_ISREG(state.st_mode):
                raise StaticWebTargetError(
                    "target_path_invalid",
                    {"phase": "path", "logical_path": logical},
                )
            path_rows.append({"path": logical, "kind": "file"})
            if child.suffix.casefold() not in _SUPPORTED_SUFFIXES:
                continue
            supported_count += 1
            if supported_count > MAX_FILES:
                raise StaticWebTargetError(
                    "target_limit_exceeded", {"phase": "snapshot"}
                )
            try:
                content, _mtime_ns = reader._read_stable_bytes(
                    child, root=root, relative=logical
                )
            except (IntakeError, OSError) as exc:
                code = getattr(exc, "code", "")
                mapped = {
                    "static_closure_symlink_forbidden": "target_symlink_forbidden",
                    "static_closure_path_outside_project": "target_path_outside_root",
                    "source_access_denied": "target_access_denied",
                    "source_limit_exceeded": "target_limit_exceeded",
                }.get(code, "target_changed_during_analysis")
                raise StaticWebTargetError(
                    mapped, {"phase": "snapshot", "logical_path": logical}
                ) from exc
            supported_bytes += len(content)
            if supported_bytes > MAX_SUPPORTED_BYTES:
                raise StaticWebTargetError(
                    "target_limit_exceeded", {"phase": "snapshot"}
                )
            digest = hashlib.sha256(content).hexdigest()
            kind = "text" if child.suffix.casefold() in _TEXT_SUFFIXES else "binary"
            if kind == "text":
                try:
                    content.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise StaticWebTargetError(
                        "target_utf8_invalid",
                        {"phase": "snapshot", "logical_path": logical},
                    ) from exc
            files[logical] = content
            file_rows.append(
                {
                    "path": logical,
                    "kind": kind,
                    "size_bytes": len(content),
                    "sha256": digest,
                }
            )

    entry_bytes = files.get(entry)
    if entry_bytes is None:
        raise StaticWebTargetError(
            "target_entry_missing", {"phase": "entry", "logical_path": entry}
        )
    entry_html = entry_bytes.decode("utf-8")
    file_rows.sort(key=lambda row: row["path"].encode("utf-8"))
    path_rows.sort(key=lambda row: row["path"].encode("utf-8"))
    snapshot_sha256 = _sha256_json(
        {
            "paths": path_rows,
            "supported_files": [
                {
                    "path": row["path"],
                    "kind": row["kind"],
                    "size_bytes": row["size_bytes"],
                    "sha256": row["sha256"],
                }
                for row in file_rows
            ],
        }
    )
    resources, javascript = _validate_target_resources(
        entry, entry_html, files, snapshot_sha256
    )
    profile = {
        "schema_version": TARGET_PROFILE_VERSION,
        "target_kind": "static_web",
        "entry_path": entry,
        "snapshot_sha256": snapshot_sha256,
        "files": file_rows,
        "resources": resources,
        "javascript": javascript,
        "checks": [
            {"name": "path_boundary", "passed": True},
            {"name": "stable_snapshot", "passed": True},
            {"name": "html_resource_references", "passed": True},
            {"name": "javascript_module_closure", "passed": True},
        ],
        "permissions": {
            "target_read": True,
            "target_write": False,
            "apply": False,
            "commit": False,
            "store_write": False,
            "network_access": False,
            "model_call": False,
        },
    }
    return {
        "root": root,
        "entry_path": entry,
        "entry_html": entry_html,
        "files": files,
        "path_keys": tuple(frozenset(bucket) for bucket in seen),
        "snapshot_sha256": snapshot_sha256,
        "profile": profile,
    }


def static_web_plan_identity(
    *,
    snapshot: dict[str, Any],
    task: str,
    capsules: list[dict[str, Any]],
    product_scope: dict[str, Any],
    authorization: dict[str, Any],
) -> dict[str, str]:
    receipts = _capsule_receipts(capsules)
    seed = {
        "adapter_version": TARGET_ADAPTER_VERSION,
        "authorization": authorization,
        "capsules": receipts,
        "entry_path": snapshot["entry_path"],
        "product_scope": product_scope,
        "target_snapshot_sha256": snapshot["snapshot_sha256"],
        "task": task,
    }
    digest = _sha256_json(seed)
    return {
        "plan_id": f"weave_{digest}",
        "plan_digest": digest,
        "product_id": f"product_{digest}",
    }


def build_static_web_patch(
    *,
    snapshot: dict[str, Any],
    task: str,
    capsules: list[dict[str, Any]],
    product_scope: dict[str, Any],
    authorization: dict[str, Any],
    identity: dict[str, str],
    composition: dict[str, Any],
) -> dict[str, Any]:
    """Build complete Patch data in memory; never write *snapshot["root"]*."""

    if product_scope != {"kind": "general"}:
        raise StaticWebTargetError(
            "target_usage_scope_mismatch", {"phase": "authorization"}
        )
    if authorization != {
        "mode": TARGET_AUTHORIZATION_MODE,
        "target_snapshot_sha256": snapshot["snapshot_sha256"],
    }:
        raise StaticWebTargetError(
            "target_patch_authorization_invalid", {"phase": "authorization"}
        )
    expected_identity = static_web_plan_identity(
        snapshot=snapshot,
        task=task,
        capsules=capsules,
        product_scope=product_scope,
        authorization=authorization,
    )
    if identity != expected_identity:
        raise StaticWebTargetError(
            "target_patch_authorization_invalid", {"phase": "authorization"}
        )

    files = composition.get("files")
    assets = composition.get("assets")
    manifest = composition.get("composition_manifest")
    provenance = composition.get("provenance")
    if (
        composition.get("status") != "composed"
        or type(files) is not dict
        or set(files) != {"index.html", "styles.css", "app.js"}
        or any(type(value) is not str for value in files.values())
        or type(assets) is not dict
        or any(type(value) is not bytes for value in assets.values())
        or set(files) & set(assets)
        or type(manifest) is not dict
        or type(manifest.get("connections")) is not list
        or type(provenance) is not dict
    ):
        raise StaticWebTargetError(
            "target_composition_invalid", {"phase": "composition"}
        )

    entry_path = str(snapshot["entry_path"])
    entry_parent = PurePosixPath(entry_path).parent
    namespace_relative = PurePosixPath("reweave") / identity["plan_digest"]
    namespace = (
        namespace_relative
        if entry_parent == PurePosixPath(".")
        else entry_parent / namespace_relative
    )
    _assert_namespace_available(
        snapshot["root"], namespace.as_posix(), snapshot["path_keys"]
    )

    output_mapping: list[dict[str, Any]] = []
    additions: dict[str, tuple[bytes, str, str]] = {}
    planned_paths = (set(), set(), set(), set())
    for composer_path, value in sorted(
        {**files, **assets}.items(), key=lambda item: item[0].encode("utf-8")
    ):
        safe = _logical_path(composer_path)
        target_path = _logical_path((namespace / PurePosixPath(safe)).as_posix())
        content = value.encode("utf-8") if type(value) is str else value
        if type(content) is not bytes or target_path in additions:
            raise StaticWebTargetError(
                "target_composition_invalid", {"phase": "composition"}
            )
        try:
            _register_path(target_path, planned_paths)
        except StaticWebTargetError as exc:
            raise StaticWebTargetError(
                "target_composition_invalid", {"phase": "composition"}
            ) from exc
        encoding = "utf-8" if composer_path in files else "base64"
        additions[target_path] = (content, encoding, composer_path)
        output_mapping.append(
            {
                "composer_path": composer_path,
                "target_path": target_path,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    if any(
        any(
            key in bucket
            for key, bucket in zip(_path_keys(parent.as_posix()), planned_paths)
        )
        for target_path in additions
        for parent in PurePosixPath(target_path).parents
        if parent != PurePosixPath(".")
    ):
        raise StaticWebTargetError(
            "target_composition_invalid", {"phase": "composition"}
        )

    entry_html = str(snapshot["entry_html"])
    if _PATCH_MARKER.search(entry_html):
        raise StaticWebTargetError(
            "target_patch_marker_collision",
            {"phase": "patch", "logical_path": entry_path},
        )
    inventory = _parse_target_html(entry_html, phase="patch")
    if len(inventory.body_end_positions) != 1:
        raise StaticWebTargetError(
            "target_entry_unsupported_v1",
            {"phase": "patch", "logical_path": entry_path},
        )
    iframe_source = f"./reweave/{identity['plan_digest']}/index.html"
    iframe = (
        f'<iframe data-reweave-plan="{identity["plan_id"]}" '
        f'src="{html.escape(iframe_source, quote=True)}" '
        f'title="{html.escape(task, quote=True)}" width="100%" height="640"></iframe>'
    )
    newline = "\r\n" if "\r\n" in entry_html and "\n" not in entry_html.replace("\r\n", "") else "\n"
    position = inventory.body_end_positions[0]
    prefix = "" if entry_html[:position].endswith(("\n", "\r")) else newline
    modified_entry = (
        entry_html[:position] + prefix + iframe + newline + entry_html[position:]
    )

    changes: list[dict[str, Any]] = [
        _change(
            path=entry_path,
            operation="modify",
            before=entry_html.encode("utf-8"),
            after=modified_entry.encode("utf-8"),
            encoding="utf-8",
            origin=TARGET_ADAPTER_VERSION,
        )
    ]
    for target_path, (content, encoding, _composer_path) in additions.items():
        changes.append(
            _change(
                path=target_path,
                operation="add",
                before=None,
                after=content,
                encoding=encoding,
                origin="module_native",
            )
        )
    changes.sort(key=lambda row: row["path"].encode("utf-8"))
    text_unified_diff = "".join(
        row["diff"] for row in changes if type(row.get("diff")) is str
    )
    receipts = _capsule_receipts(capsules)
    affected = [
        {"path": row["path"], "operation": row["operation"]} for row in changes
    ]
    return {
        "schema_version": TARGET_PATCH_VERSION,
        "status": "ready_for_review",
        "plan_id": identity["plan_id"],
        "strategy": TARGET_ADAPTER_VERSION,
        "target": {
            "entry_path": entry_path,
            "snapshot_sha256": snapshot["snapshot_sha256"],
            "profile": snapshot["profile"],
        },
        "authorization": {
            "mode": TARGET_AUTHORIZATION_MODE,
            "target_snapshot_sha256": snapshot["snapshot_sha256"],
            "usage_scope": product_scope,
            "usage_scope_match": True,
            "target_project_write": False,
            "apply": False,
            "commit": False,
        },
        "weave_plan": {
            "schema_version": WEAVE_PLAN_VERSION,
            "plan_id": identity["plan_id"],
            "adapter_version": TARGET_ADAPTER_VERSION,
            "task": task,
            "capsules": receipts,
            "affected_files": affected,
            "validation_steps": [
                "target_snapshot_match",
                "target_path_and_resource_boundaries",
                "capsule_usage_scope",
                "module_native_composition",
                "target_output_collision",
                "target_snapshot_unchanged",
            ],
            "failure_policy": "stop_without_target_write",
        },
        "composer": {
            "composer_version": composition.get("composer_version"),
            "connections": manifest["connections"],
            "provenance": provenance,
            "output_mapping": output_mapping,
        },
        "changes": changes,
        "text_unified_diff": text_unified_diff,
        "evidence": {
            "schema_version": "static_web_target_patch_evidence.v1",
            "status": "passed",
            "checks": [
                {"name": "target_snapshot_bound", "passed": True},
                {"name": "target_paths_and_resources", "passed": True},
                {"name": "capsule_usage_scope", "passed": True},
                {"name": "module_native_composition", "passed": True},
                {"name": "output_paths_collision_free", "passed": True},
                {"name": "target_snapshot_unchanged", "passed": True},
            ],
            "target_project_write": False,
            "product_store_write": False,
            "usage_registration_write": False,
        },
    }


def rejection_evidence(error: StaticWebTargetError) -> dict[str, Any]:
    evidence = {"status": "rejected", "code": error.code}
    evidence.update(error.evidence)
    return evidence


def _target_root(value: str | Path) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise StaticWebTargetError("target_path_required", {"phase": "path"})
    raw = Path(value).expanduser()
    if raw.is_symlink() or not raw.is_dir():
        raise StaticWebTargetError("target_path_invalid", {"phase": "path"})
    try:
        root = raw.resolve(strict=True)
        home = Path.home().resolve(strict=True)
        application_state = state_dir().resolve()
    except OSError as exc:
        raise StaticWebTargetError("target_path_invalid", {"phase": "path"}) from exc
    filesystem_root = Path(root.anchor).resolve()
    if root in {filesystem_root, home}:
        raise StaticWebTargetError("target_path_invalid", {"phase": "path"})
    try:
        application_state.relative_to(root)
    except ValueError:
        pass
    else:
        raise StaticWebTargetError("target_path_invalid", {"phase": "path"})
    return root


def _logical_path(value: Any) -> str:
    if type(value) is not str or not value or value.startswith("/") or value.endswith("/"):
        raise StaticWebTargetError("target_path_invalid", {"phase": "path"})
    if "\\" in value or "%" in value:
        raise StaticWebTargetError("target_path_invalid", {"phase": "path"})
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise StaticWebTargetError("target_path_invalid", {"phase": "path"}) from exc
    parts = value.split("/")
    if any(not part or part in {".", ".."} or _PATH_CONTROL.search(part) for part in parts):
        raise StaticWebTargetError("target_path_invalid", {"phase": "path"})
    return value


def _path_keys(value: str) -> tuple[str, str, str, str]:
    return (
        value,
        value.casefold(),
        unicodedata.normalize("NFC", value),
        unicodedata.normalize("NFC", value).casefold(),
    )


def _register_path(value: str, seen: tuple[set[str], ...]) -> None:
    keys = _path_keys(value)
    if any(key in bucket for key, bucket in zip(keys, seen)):
        raise StaticWebTargetError(
            "target_path_invalid", {"phase": "path", "logical_path": value}
        )
    for key, bucket in zip(keys, seen):
        bucket.add(key)


def _validate_target_resources(
    entry_path: str,
    entry_html: str,
    files: dict[str, bytes],
    snapshot_sha256: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    inventory = _parse_target_html(entry_html, phase="resource")
    if inventory.inline_script:
        raise StaticWebTargetError(
            "target_entry_unsupported_v1",
            {"phase": "resource", "reason": "inline_script"},
        )
    if inventory.inline_style:
        raise StaticWebTargetError(
            "target_entry_unsupported_v1",
            {"phase": "resource", "reason": "inline_style"},
        )
    if inventory.unsupported_feature:
        raise StaticWebTargetError(
            "target_entry_unsupported_v1",
            {"phase": "resource", "reason": inventory.unsupported_feature},
        )
    if inventory.csp:
        raise StaticWebTargetError(
            "target_csp_unsupported_v1", {"phase": "authorization"}
        )

    resources: list[dict[str, str]] = []
    entry_modules: list[str] = []
    for tag, attribute, raw, role in inventory.references:
        logical = _resource_path(entry_path, raw, tag=tag, attribute=attribute)
        suffix = PurePosixPath(logical).suffix.casefold()
        expected = (
            {".js", ".mjs"}
            if tag == "script"
            else ({".css"} if role == "stylesheet" else _ASSET_SUFFIXES)
        )
        if suffix not in expected:
            raise StaticWebTargetError(
                "target_resource_unsupported_v1",
                {"phase": "resource", "logical_path": logical},
            )
        if logical not in files:
            raise StaticWebTargetError(
                "target_resource_missing",
                {"phase": "resource", "logical_path": logical},
            )
        if tag == "script":
            if role != "module":
                raise StaticWebTargetError(
                    "target_entry_unsupported_v1",
                    {"phase": "resource", "reason": "classic_script"},
                )
            entry_modules.append(logical)
        resources.append(
            {
                "from_path": entry_path,
                "kind": "javascript" if tag == "script" else role,
                "path": logical,
            }
        )

    stylesheet_paths = {
        row["path"] for row in resources if row["kind"] == "stylesheet"
    }
    for logical in sorted(stylesheet_paths, key=lambda value: value.encode("utf-8")):
        content = files[logical]
        text = content.decode("utf-8")
        if "\\" in text or _CSS_RESOURCE.search(text):
            raise StaticWebTargetError(
                "target_resource_unsupported_v1",
                {"phase": "resource", "logical_path": logical},
            )

    resources.sort(
        key=lambda row: (row["from_path"], row["kind"], row["path"])
    )
    javascript = _validate_javascript_closure(
        files, sorted(set(entry_modules), key=lambda value: value.encode("utf-8")), snapshot_sha256
    )
    return resources, javascript


def _parse_target_html(entry_html: str, *, phase: str) -> _TargetHTMLInventory:
    inventory = _TargetHTMLInventory(entry_html)
    try:
        inventory.feed(entry_html)
        inventory.close()
    except Exception as exc:
        raise StaticWebTargetError(
            "target_entry_unsupported_v1", {"phase": phase}
        ) from exc
    return inventory


def _resource_path(owner: str, value: str, *, tag: str, attribute: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or value.startswith(("/", "//")):
        raise StaticWebTargetError(
            "target_remote_reference_forbidden",
            {
                "phase": "resource",
                "tag": tag,
                "attribute": attribute,
                "scheme": parsed.scheme.casefold(),
            },
        )
    if not parsed.path or parsed.query or parsed.fragment or "%" in parsed.path or "\\" in parsed.path:
        raise StaticWebTargetError(
            "target_resource_reference_invalid",
            {"phase": "resource", "tag": tag, "attribute": attribute},
        )
    stack = list(PurePosixPath(owner).parent.parts)
    if stack == ["."]:
        stack = []
    for part in parsed.path.split("/"):
        if part in {"", "."}:
            if part == "" and parsed.path != "./":
                raise StaticWebTargetError(
                    "target_resource_reference_invalid",
                    {"phase": "resource", "tag": tag, "attribute": attribute},
                )
            continue
        if part == "..":
            if not stack:
                raise StaticWebTargetError(
                    "target_path_outside_root",
                    {"phase": "resource", "tag": tag, "attribute": attribute},
                )
            stack.pop()
            continue
        if _PATH_CONTROL.search(part):
            raise StaticWebTargetError(
                "target_resource_reference_invalid",
                {"phase": "resource", "tag": tag, "attribute": attribute},
            )
        stack.append(part)
    if not stack:
        raise StaticWebTargetError(
            "target_resource_reference_invalid",
            {"phase": "resource", "tag": tag, "attribute": attribute},
        )
    return _logical_path("/".join(stack))


def _validate_javascript_closure(
    files: dict[str, bytes], entry_modules: list[str], snapshot_sha256: str
) -> dict[str, Any]:
    if not entry_modules:
        return {
            "schema_version": "source_graph.v1",
            "entry_modules": [],
            "reachable_module_count": 0,
            "graph_sha256": None,
        }
    node = os.environ.get("REWEAVE_NODE") or shutil.which("node")
    if not node:
        raise StaticWebTargetError(
            "target_javascript_validation_unavailable", {"phase": "javascript"}
        )
    modules = [
        {
            "path": path,
            "source_base64": base64.b64encode(content).decode("ascii"),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for path, content in sorted(files.items())
        if PurePosixPath(path).suffix.casefold() in {".js", ".mjs"}
    ]
    request = {
        "schema": "source_graph_request.v1",
        "mode": "graph",
        "project_id": f"target_{snapshot_sha256[:20]}",
        "scope_snapshot_sha256": snapshot_sha256,
        "source_identity_sha256": snapshot_sha256,
        "entry_modules": entry_modules,
        "module_snapshot": modules,
        "symlinks": [],
    }
    repository = Path(__file__).resolve().parents[1]
    try:
        completed = subprocess.run(
            [
                node,
                "--max-old-space-size=512",
                str(repository / "scripts" / "analyze_reweave_source_graph.mjs"),
            ],
            input=_canonical_json(request),
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=repository,
            timeout=60,
            check=False,
            env=restricted_subprocess_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        raise StaticWebTargetError(
            "target_javascript_validation_timeout", {"phase": "javascript"}
        ) from exc
    except OSError as exc:
        raise StaticWebTargetError(
            "target_javascript_validation_unavailable", {"phase": "javascript"}
        ) from exc
    if completed.returncode or completed.stderr or len(completed.stdout.encode("utf-8")) > 16 * 1024 * 1024:
        raise StaticWebTargetError(
            "target_javascript_closure_unproven", {"phase": "javascript"}
        )
    try:
        graph = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise StaticWebTargetError(
            "target_javascript_closure_unproven", {"phase": "javascript"}
        ) from exc
    if type(graph) is not dict or graph.get("schema") != "source_graph.v1" or graph.get("status") != "ok":
        reason = graph.get("error_code") if type(graph) is dict else None
        evidence = {"phase": "javascript"}
        if type(reason) is str and re.fullmatch(r"[a-z][a-z0-9_]{1,95}", reason):
            evidence["reason"] = reason
        raise StaticWebTargetError("target_javascript_closure_unproven", evidence)
    graph_modules = graph.get("modules")
    if type(graph_modules) is not list:
        raise StaticWebTargetError(
            "target_javascript_closure_unproven", {"phase": "javascript"}
        )
    return {
        "schema_version": "source_graph.v1",
        "entry_modules": entry_modules,
        "reachable_module_count": len(graph_modules),
        "graph_sha256": _sha256_json(graph),
    }


def _assert_namespace_available(
    root: Path,
    logical: str,
    existing: tuple[frozenset[str], ...],
) -> None:
    parts = PurePosixPath(_logical_path(logical)).parts
    current = root
    for index, part in enumerate(parts):
        current /= part
        prefix = "/".join(parts[: index + 1])
        keys = _path_keys(prefix)
        exact_exists = keys[0] in existing[0]
        equivalent_exists = any(
            key in bucket for key, bucket in zip(keys, existing)
        )
        if current.is_symlink():
            raise StaticWebTargetError(
                "target_symlink_forbidden",
                {"phase": "patch", "logical_path": prefix},
            )
        if index < len(parts) - 1 and equivalent_exists and not exact_exists:
            raise StaticWebTargetError(
                "target_patch_path_collision",
                {"phase": "patch", "logical_path": prefix},
            )
        if index < len(parts) - 1 and current.exists() and not current.is_dir():
            raise StaticWebTargetError(
                "target_patch_path_collision",
                {"phase": "patch", "logical_path": prefix},
            )
    if equivalent_exists or current.exists():
        raise StaticWebTargetError(
            "target_patch_path_collision",
            {"phase": "patch", "logical_path": logical},
        )


def _capsule_receipts(capsules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    receipts = [
        {
            "capsule_id": row["capsule_id"],
            "version_id": row["version_id"],
            "canonical_hash": row["canonical_hash"],
            "capability_key": row["capability_key"],
            "role_key": row["role_key"],
            "variant_key": row["variant_key"],
            "capability_kind": row["capability_kind"],
            "usage_scope": row["usage_scope"],
        }
        for row in capsules
    ]
    return sorted(
        receipts,
        key=lambda row: (
            row["capability_kind"], row["capsule_id"], row["version_id"]
        ),
    )


def _change(
    *,
    path: str,
    operation: str,
    before: bytes | None,
    after: bytes,
    encoding: str,
    origin: str,
) -> dict[str, Any]:
    before_sha256 = hashlib.sha256(before).hexdigest() if before is not None else None
    after_sha256 = hashlib.sha256(after).hexdigest()
    if encoding == "utf-8":
        after_content = after.decode("utf-8")
        before_text = before.decode("utf-8") if before is not None else ""
        diff = _unified_diff(path, before_text, after_content, operation)
    else:
        after_content = base64.b64encode(after).decode("ascii")
        diff = None
    return {
        "path": path,
        "operation": operation,
        "origin": origin,
        "before_sha256": before_sha256,
        "after_sha256": after_sha256,
        "size_bytes": len(after),
        "content_encoding": encoding,
        "after_content": after_content,
        "diff": diff,
    }


def _unified_diff(path: str, before: str, after: str, operation: str) -> str:
    header = [f"diff --git a/{path} b/{path}\n"]
    if operation == "add":
        header.append("new file mode 100644\n")
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile="/dev/null" if operation == "add" else f"a/{path}",
        tofile=f"b/{path}",
        lineterm="\n",
    )
    for line in lines:
        if line.endswith("\n"):
            header.append(line)
        else:
            header.extend((line + "\n", "\\ No newline at end of file\n"))
    return "".join(header)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


__all__ = [
    "TARGET_ADAPTER_VERSION",
    "TARGET_AUTHORIZATION_MODE",
    "TARGET_PATCH_VERSION",
    "TARGET_PROFILE_VERSION",
    "StaticWebTargetError",
    "analyze_static_web_target",
    "build_static_web_patch",
    "capture_static_web_target",
    "rejection_evidence",
    "static_web_plan_identity",
]
