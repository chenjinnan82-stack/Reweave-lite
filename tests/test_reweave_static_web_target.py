from __future__ import annotations

import base64
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from pimos_lite.reweave_static_web_target import (
    TARGET_ADAPTER_VERSION,
    TARGET_AUTHORIZATION_MODE,
    StaticWebTargetError,
    analyze_static_web_target,
    build_static_web_patch,
    capture_static_web_target,
    static_web_plan_identity,
)


def _write_target(root: Path, *, html: str | None = None) -> None:
    root.mkdir()
    (root / "index.html").write_text(
        html
        or """<!doctype html>
<html><head><link rel="stylesheet" href="./styles.css"></head>
<body><h1>Existing target</h1><img src="./pixel.png"></body></html>
""",
        encoding="utf-8",
    )
    (root / "styles.css").write_text("body { color: #123; }\n", encoding="utf-8")
    (root / "pixel.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")


def _tree(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _capsules() -> list[dict[str, object]]:
    return [
        {
            "capsule_id": "capsule_presentation",
            "version_id": "version_presentation_1",
            "canonical_hash": "1" * 64,
            "capability_key": "quote",
            "role_key": "quote_view",
            "variant_key": "default",
            "capability_kind": "presentation",
            "usage_scope": {"kind": "general"},
        },
        {
            "capsule_id": "capsule_interaction",
            "version_id": "version_interaction_1",
            "canonical_hash": "2" * 64,
            "capability_key": "quote",
            "role_key": "quote_action",
            "variant_key": "default",
            "capability_kind": "interaction",
            "usage_scope": {"kind": "general"},
        },
    ]


def _composition() -> dict[str, object]:
    return {
        "status": "composed",
        "composer_version": "module_native_formal_product.v1",
        "files": {
            "index.html": "<!doctype html><html><body><main>Capsule</main><script src=\"./app.js\"></script></body></html>\n",
            "styles.css": "main { display: block; }\n",
            "app.js": '"use strict";\n',
        },
        "assets": {"assets/1234567890abcdef/pixel.png": b"\x89PNG\r\n\x1a\nasset"},
        "composition_manifest": {
            "schema_version": "module_native_product_composition.v1",
            "connections": [],
        },
        "provenance": {
            "composer_version": "module_native_formal_product.v1",
            "file_provenance": {},
            "asset_provenance": {},
        },
    }


def _patch(root: Path) -> dict[str, object]:
    snapshot = capture_static_web_target(root, "index.html")
    authorization = {
        "mode": TARGET_AUTHORIZATION_MODE,
        "target_snapshot_sha256": snapshot["snapshot_sha256"],
    }
    capsules = _capsules()
    identity = static_web_plan_identity(
        snapshot=snapshot,
        task="Add quote capability",
        capsules=capsules,
        product_scope={"kind": "general"},
        authorization=authorization,
    )
    return build_static_web_patch(
        snapshot=snapshot,
        task="Add quote capability",
        capsules=list(reversed(capsules)),
        product_scope={"kind": "general"},
        authorization=authorization,
        identity=identity,
        composition=_composition(),
    )


def test_profile_is_deterministic_source_free_and_read_only(tmp_path: Path) -> None:
    target = tmp_path / "target"
    _write_target(target)
    before = _tree(target)

    first = analyze_static_web_target(target, "index.html")
    second = analyze_static_web_target(target, "index.html")

    assert first == second
    assert first["schema_version"] == "static_web_target_profile.v1"
    assert first["entry_path"] == "index.html"
    assert first["source_unchanged"] is True
    assert first["resources"] == [
        {"from_path": "index.html", "kind": "asset", "path": "pixel.png"},
        {"from_path": "index.html", "kind": "stylesheet", "path": "styles.css"},
    ]
    assert all(row["passed"] is True for row in first["checks"])
    assert first["permissions"]["target_write"] is False
    assert str(target) not in json.dumps(first, ensure_ascii=False)
    assert _tree(target) == before


@pytest.mark.skipif(
    shutil.which("node") is None
    or not (Path(__file__).resolve().parents[1] / "node_modules" / "typescript").is_dir(),
    reason="Node dependencies are required for source_graph.v1",
)
def test_profile_reuses_source_graph_for_local_module_closure(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "index.html").write_text(
        '<!doctype html><html><head></head><body><script type="module" src="./app.js"></script></body></html>\n',
        encoding="utf-8",
    )
    (target / "app.js").write_text(
        'import { twice } from "./helper.js";\nexport const result = twice(2);\n',
        encoding="utf-8",
    )
    (target / "helper.js").write_text(
        "export function twice(value) { return value * 2; }\n", encoding="utf-8"
    )

    profile = analyze_static_web_target(target, "index.html")

    assert profile["javascript"]["schema_version"] == "source_graph.v1"
    assert profile["javascript"]["entry_modules"] == ["app.js"]
    assert profile["javascript"]["reachable_module_count"] == 2
    assert len(profile["javascript"]["graph_sha256"]) == 64


@pytest.mark.parametrize(
    ("entry", "html_text", "expected"),
    [
        ("../index.html", None, "target_path_invalid"),
        ("index%2ehtml", None, "target_path_invalid"),
        ("index\\html", None, "target_path_invalid"),
        (
            "index.html",
            '<html><head></head><body><script type="module" src="https://example.test/app.js"></script></body></html>',
            "target_remote_reference_forbidden",
        ),
        (
            "index.html",
            '<html><head><link rel="stylesheet" href="./styles.css?v=1"></head><body></body></html>',
            "target_resource_reference_invalid",
        ),
        (
            "index.html",
            '<html><head></head><body><script>globalThis.value = 1;</script></body></html>',
            "target_entry_unsupported_v1",
        ),
        (
            "index.html",
            '<html><head><meta http-equiv="Content-Security-Policy" content="default-src self"></head><body></body></html>',
            "target_csp_unsupported_v1",
        ),
    ],
)
def test_profile_fails_closed_for_unsafe_entry_and_resources(
    tmp_path: Path, entry: str, html_text: str | None, expected: str
) -> None:
    target = tmp_path / "target"
    _write_target(target, html=html_text)

    with pytest.raises(StaticWebTargetError, match=expected) as caught:
        capture_static_web_target(target, entry)

    assert caught.value.code == expected
    assert str(target) not in json.dumps(caught.value.evidence, ensure_ascii=False)


def test_profile_rejects_css_resources_and_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target"
    _write_target(target)
    (target / "styles.css").write_text(
        'body { background: url("./pixel.png"); }\n', encoding="utf-8"
    )
    with pytest.raises(StaticWebTargetError) as css_error:
        capture_static_web_target(target, "index.html")
    assert css_error.value.code == "target_resource_unsupported_v1"

    (target / "styles.css").write_text(
        r'body { background-image: u\72l("./pixel.png"); }' + "\n",
        encoding="utf-8",
    )
    with pytest.raises(StaticWebTargetError) as escaped_css_error:
        capture_static_web_target(target, "index.html")
    assert escaped_css_error.value.code == "target_resource_unsupported_v1"

    (target / "styles.css").write_text("body { color: #123; }\n", encoding="utf-8")
    (target / "linked.js").symlink_to(target / "styles.css")
    with pytest.raises(StaticWebTargetError) as symlink_error:
        capture_static_web_target(target, "index.html")
    assert symlink_error.value.code == "target_symlink_forbidden"


def test_patch_is_complete_deterministic_and_never_writes_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    _write_target(target)
    before = _tree(target)

    first = _patch(target)
    second = _patch(target)

    assert first == second
    assert first["status"] == "ready_for_review"
    assert first["strategy"] == TARGET_ADAPTER_VERSION
    assert first["authorization"]["target_project_write"] is False
    assert first["authorization"]["apply"] is False
    assert first["authorization"]["commit"] is False
    assert first["weave_plan"]["failure_policy"] == "stop_without_target_write"
    assert first["text_unified_diff"].startswith(
        "diff --git a/index.html b/index.html\n"
    )
    assert 'data-reweave-plan="' in first["text_unified_diff"]
    assert len(first["changes"]) == 5
    binary = next(
        row for row in first["changes"] if row["content_encoding"] == "base64"
    )
    decoded = base64.b64decode(binary["after_content"], validate=True)
    assert hashlib.sha256(decoded).hexdigest() == binary["after_sha256"]
    assert binary["diff"] is None
    assert str(target) not in json.dumps(first, ensure_ascii=False)
    assert _tree(target) == before
    assert not (target / "reweave").exists()


@pytest.mark.parametrize(
    ("opening", "closing"),
    [
        ("<!--", "-->"),
        ("<template>", "</template>"),
        ("<select>", "</select>"),
        ("<noscript>", "</noscript>"),
        ("<math>", "</math>"),
        ("<table>", "</table>"),
    ],
)
def test_patch_never_inserts_at_unproven_body_close(
    tmp_path: Path, opening: str, closing: str
) -> None:
    target = tmp_path / "target"
    _write_target(
        target,
        html="<!doctype html><html><head></head><body>"
        f"{opening} </body> {closing}<p>still body</p></html>",
    )

    with pytest.raises(StaticWebTargetError) as body_error:
        _patch(target)

    assert body_error.value.code == "target_entry_unsupported_v1"
    assert body_error.value.evidence["phase"] == "patch"


def test_patch_rejects_scope_authorization_marker_and_output_collisions(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    _write_target(target)
    snapshot = capture_static_web_target(target, "index.html")
    authorization = {
        "mode": TARGET_AUTHORIZATION_MODE,
        "target_snapshot_sha256": snapshot["snapshot_sha256"],
    }
    capsules = _capsules()
    identity = static_web_plan_identity(
        snapshot=snapshot,
        task="Add quote capability",
        capsules=capsules,
        product_scope={"kind": "general"},
        authorization=authorization,
    )
    arguments = {
        "snapshot": snapshot,
        "task": "Add quote capability",
        "capsules": capsules,
        "product_scope": {"kind": "general"},
        "authorization": authorization,
        "identity": identity,
        "composition": _composition(),
    }

    limited = dict(arguments)
    limited["product_scope"] = {
        "kind": "brand_limited",
        "brand_profile_id": "brand_1",
        "brand_profile_digest": "3" * 64,
    }
    with pytest.raises(StaticWebTargetError) as scope_error:
        build_static_web_patch(**limited)
    assert scope_error.value.code == "target_usage_scope_mismatch"

    namespace = target / "reweave" / identity["plan_digest"]
    namespace.mkdir(parents=True)
    with pytest.raises(StaticWebTargetError) as collision_error:
        build_static_web_patch(**arguments)
    assert collision_error.value.code == "target_patch_path_collision"

    namespace.rmdir()
    (target / "reweave").rmdir()
    (target / "index.html").write_text(
        '<html><body data-reweave-plan = "existing"></body></html>', encoding="utf-8"
    )
    marker_snapshot = capture_static_web_target(target, "index.html")
    marker_authorization = {
        "mode": TARGET_AUTHORIZATION_MODE,
        "target_snapshot_sha256": marker_snapshot["snapshot_sha256"],
    }
    marker_identity = static_web_plan_identity(
        snapshot=marker_snapshot,
        task="Add quote capability",
        capsules=capsules,
        product_scope={"kind": "general"},
        authorization=marker_authorization,
    )
    with pytest.raises(StaticWebTargetError) as marker_error:
        build_static_web_patch(
            snapshot=marker_snapshot,
            task="Add quote capability",
            capsules=capsules,
            product_scope={"kind": "general"},
            authorization=marker_authorization,
            identity=marker_identity,
            composition=_composition(),
        )
    assert marker_error.value.code == "target_patch_marker_collision"


def test_patch_rejects_casefold_namespace_and_composer_output_collisions(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    _write_target(target)
    (target / "Reweave").mkdir()

    with pytest.raises(StaticWebTargetError) as namespace_error:
        _patch(target)
    assert namespace_error.value.code == "target_patch_path_collision"

    (target / "Reweave").rmdir()
    snapshot = capture_static_web_target(target, "index.html")
    authorization = {
        "mode": TARGET_AUTHORIZATION_MODE,
        "target_snapshot_sha256": snapshot["snapshot_sha256"],
    }
    capsules = _capsules()
    identity = static_web_plan_identity(
        snapshot=snapshot,
        task="Add quote capability",
        capsules=capsules,
        product_scope={"kind": "general"},
        authorization=authorization,
    )
    composition = _composition()
    composition["assets"] = {
        "Assets/pixel.png": b"first",
        "assets/PIXEL.png": b"second",
    }

    with pytest.raises(StaticWebTargetError) as output_error:
        build_static_web_patch(
            snapshot=snapshot,
            task="Add quote capability",
            capsules=capsules,
            product_scope={"kind": "general"},
            authorization=authorization,
            identity=identity,
            composition=composition,
        )
    assert output_error.value.code == "target_composition_invalid"
