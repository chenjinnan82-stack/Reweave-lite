"""Phase 5 formal SQLite capsule product generation tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from pimos_lite.composer.module_native import (
    _bundle_formal_capsule,
    compose_capsule_product,
)
from pimos_lite.reweave_app_service import (
    ProductGenerationError,
    ReweaveAppService,
    _canonical_manifest_bytes,
)
from pimos_lite.reweave_capsule_intake import (
    EXTRACTION_CONTRACT_VERSION,
    REDACTION_RULES_VERSION,
)
from pimos_lite.reweave_capsule_stage3 import (
    SECURITY_RULES_VERSION,
    SUPERVISION_RULES_VERSION,
    VALIDATION_CONTRACT_VERSION,
    generate_computation_adapter_v2,
)
from pimos_lite.reweave_capsule_store import (
    CANONICALIZATION_VERSION,
    CapsuleStoreError,
    CapsuleWarehouseStore,
    canonicalize_capsule,
)
from pimos_lite.reweave_static_web_target import TARGET_AUTHORIZATION_MODE
from scripts import run_public_reweave_demo


ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-07-15T00:00:00Z"
STRICT_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "font-src 'none'; connect-src 'none'; object-src 'none'; frame-src 'none'; "
    "worker-src 'none'; base-uri 'none'; form-action 'none'"
)


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _object_contract(properties: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": properties,
        "required": sorted(properties),
        "additional_properties": False,
    }


EMPTY_OBJECT = _object_contract({})
ERRORS = {"schema": "error_contract.v1", "errors": {}}
QUOTE_HTML = (
    '<section class="quote">'
    '<label>Quantity <input data-ref="quantity" type="number" min="1" max="10" '
    'step="1" value="2"></label>'
    '<button data-action="calculate" type="button">Calculate</button>'
    '<output data-ref="total"></output>'
    "</section>"
)
QUOTE_CSS = "__CAPSULE_ROOT__ .quote { display: grid; gap: 0.5rem; }\n"


def _adapter_errors() -> dict[str, object]:
    details = _object_contract({})
    return {
        "schema": "error_contract.v1",
        "errors": {
            "INPUT_CONTRACT_VIOLATION": {"field": None, "details": details},
            "OUTPUT_CONTRACT_VIOLATION": {"field": None, "details": details},
        },
    }


def _capsule_payload(kind: str) -> dict[str, object]:
    quantity = _object_contract(
        {"quantity": {"type": "integer", "minimum": 1, "maximum": 10}}
    )
    total = _object_contract(
        {"total": {"type": "integer", "minimum": 2, "maximum": 20}}
    )
    base_scope: dict[str, object] = {
        "root_contract": "capsule_root",
        "classes": [],
        "attributes": [],
    }
    if kind == "presentation":
        return {
            "capability_kind": kind,
            "activation": {
                "mode": "declared_input_render",
                "entry_module": "presentation.js",
                "entrypoint": "render",
            },
            "input_contract": total,
            "output_contract": {"schema": "no_output.v1"},
            "error_contract": ERRORS,
            "runtime_allowlist": ["local_computation", "scoped_ui_update"],
            "dom_scope": {
                **base_scope,
                "selectors": ["[data-ref='total']"],
                "events": [],
            },
            "usage_scope": {"kind": "general"},
            "html": QUOTE_HTML,
            "css": QUOTE_CSS,
            "javascript_modules": [
                {
                    "path": "presentation.js",
                    "source": """export function render(root, input) {
  const total = root.querySelector("[data-ref='total']");
  total.textContent = String(input.total);
}
""",
                }
            ],
            "assets": [],
        }
    if kind == "interaction":
        return {
            "capability_kind": kind,
            "activation": {
                "mode": "declared_event_mount",
                "entry_module": "interaction.js",
                "entrypoint": "mount",
                "cleanup": "returned_dispose",
            },
            "input_contract": EMPTY_OBJECT,
            "output_contract": {
                "schema": "event_outputs.v1",
                "events": {"calculate_requested": quantity},
            },
            "error_contract": ERRORS,
            "runtime_allowlist": [
                "declared_event_handling",
                "declared_output_emit",
                "memory_state",
                "scoped_input_read",
                "scoped_ui_update",
            ],
            "dom_scope": {
                **base_scope,
                "selectors": [
                    "[data-action='calculate']",
                    "[data-ref='quantity']",
                ],
                "events": ["click"],
            },
            "usage_scope": {"kind": "general"},
            "html": QUOTE_HTML,
            "css": QUOTE_CSS,
            "javascript_modules": [
                {
                    "path": "interaction.js",
                    "source": """export function mount(root, ports) {
  const quantity = root.querySelector("[data-ref='quantity']");
  const button = root.querySelector("[data-action='calculate']");
  const onClick = (event) => {
    event.preventDefault();
    const value = Number(quantity.value);
    if (!Number.isInteger(value) || value < 1 || value > 10) return;
    ports.emit("calculate_requested", {quantity: value});
  };
  button.addEventListener("click", onClick);
  return () => { button.removeEventListener("click", onClick); };
}
""",
                }
            ],
            "assets": [],
        }
    if kind == "computation":
        return {
            "capability_kind": kind,
            "activation": {
                "mode": "declared_input_compute",
                "entry_module": "computation.js",
                "entrypoint": "compute",
            },
            "input_contract": quantity,
            "output_contract": total,
            "error_contract": ERRORS,
            "runtime_allowlist": ["local_computation"],
            "dom_scope": {
                **base_scope,
                "selectors": [],
                "events": [],
            },
            "usage_scope": {"kind": "general"},
            "html": "",
            "css": "",
            "javascript_modules": [
                {
                    "path": "computation.js",
                    "source": """export function compute(input) {
  return {ok: true, value: {total: input.quantity * 2}};
}
""",
                }
            ],
            "assets": [],
        }
    raise AssertionError(kind)


def _composer_capsules() -> list[dict[str, object]]:
    roles = {
        "presentation": "quote_summary",
        "interaction": "quote_input",
        "computation": "total_price",
    }
    result = []
    for kind, role in roles.items():
        row = _capsule_payload(kind)
        row.update(
            capsule_id=f"capsule_{kind}",
            version_id=f"version_{kind}_1",
            capability_key="quote_calculation",
            role_key=role,
            variant_key="default",
            candidate_origin=None,
            adapter_contract_version=None,
        )
        result.append(row)
    return result


def _version_evidence(kind: str) -> dict[str, object]:
    cleaning = {
        "schema_version": "capsule_cleaning.v1",
        "status": "passed",
        "redaction_count": 0,
        "html_cleaned": kind != "computation",
        "css_cleaned": kind != "computation",
        "asset_count": 0,
    }
    security = {
        "schema_version": "fixed_security.v1",
        "status": "passed",
        "security_rules_version": SECURITY_RULES_VERSION,
        "listener_bindings": (
            [
                {
                    "selector": "[data-action='calculate']",
                    "event": "click",
                    "handler": "onClick",
                }
            ]
            if kind == "interaction"
            else []
        ),
    }
    if kind == "computation":
        validation: dict[str, object] = {
            "schema_version": "runtime_validation.v1",
            "status": "passed",
            "acceptance_scope": "isolated_node_vm_computation",
            "normal_cases": 1,
            "boundary_cases": 0,
            "invalid_cases": 0,
            "repeatability_checked": True,
            "input_freeze_checked": True,
        }
    else:
        validation = {
            "schema_version": "qweb_validation.v1",
            "status": "passed",
            "normal_cases": 1,
            "boundary_cases": 0,
            "invalid_cases": 0,
            "repeated_render": kind == "presentation",
            "dispose_idempotent": kind == "interaction",
            "remount_checked": False,
            "acceptance_scope": (
                "real_qwebengine_render"
                if kind == "presentation"
                else "real_qwebengine_interaction"
            ),
        }
        if kind == "interaction":
            validation.update(
                {
                    "emission_count": 1,
                    "emission_names": ["calculate_requested"],
                }
            )
    supervision = {
        "schema_version": "capsule_supervision.v1",
        "verdict": "approve",
        "capability_kind": kind,
        "semantic_summary": f"Approved {kind} quote role.",
        "keep_reason_codes": ["DECLARED_LOCAL_CAPABILITY"],
        "remove_reason_codes": [],
        "brand_signals": [],
        "sensitive_data_status": "clear",
        "hidden_dependency_codes": [],
        "duplicate_suggestions": [],
        "review_required": False,
    }
    evidence = {
        "schema_version": "stage3_evidence.v1",
        "extraction_contract_version": EXTRACTION_CONTRACT_VERSION,
        "redaction_rules_version": REDACTION_RULES_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "security_rules_version": SECURITY_RULES_VERSION,
        "supervision_rules_version": SUPERVISION_RULES_VERSION,
        "validation_contract_version": VALIDATION_CONTRACT_VERSION,
        "model_name": "phase5-test-model",
        "model_digest": "b" * 64,
        "supervised_at": NOW,
        "cleaning_summary": cleaning,
        "security_result": security,
        "validation": validation,
    }
    return {
        "cleaning": cleaning,
        "validation": validation,
        "supervision": supervision,
        "extraction": {"stage3_evidence": evidence},
    }


def _seed_capsule(
    store: CapsuleWarehouseStore,
    kind: str,
    *,
    capability_key: str = "quote_calculation",
    suffix: str | None = None,
    status: str = "active",
) -> tuple[str, str]:
    identity = suffix or kind
    capsule_id = f"capsule_{identity}"
    version_id = f"version_{identity}_1"
    role_key = {
        "presentation": "quote_summary",
        "interaction": "quote_input",
        "computation": "total_price",
    }[kind]
    if suffix:
        role_key = f"{role_key}_{suffix}"
    payload = _capsule_payload(kind)
    canonical = canonicalize_capsule(payload)
    evidence = _version_evidence(kind)
    with store.transaction() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO capability_groups "
            "(capability_key, display_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (capability_key, capability_key.replace("_", " ").title(), NOW, NOW),
        )
        connection.execute(
            "INSERT INTO capsules "
            "(capsule_id, capability_key, role_key, variant_key, capability_kind, "
            "status, current_version_id, created_at) VALUES (?, ?, ?, 'default', ?, ?, NULL, ?)",
            (
                capsule_id,
                capability_key,
                role_key,
                kind,
                "pending_revalidation" if status == "active" else status,
                NOW,
            ),
        )
        connection.execute(
            "INSERT INTO capsule_versions ("
            "version_id, capsule_id, version_number, extraction_contract_version, "
            "extraction_summary_json, redaction_rules_version, canonicalization_version, "
            "canonical_hash, activation_json, input_contract_json, output_contract_json, "
            "error_contract_json, runtime_allowlist_json, dom_scope_json, usage_scope_json, "
            "html_text, css_text, javascript_modules_json, cleaning_summary_json, "
            "security_rules_version, supervision_rules_version, supervision_model_name, "
            "supervision_model_digest, supervised_at, supervision_result_json, "
            "supervision_response_hash, validation_contract_version, "
            "validation_result_json, created_at"
            ") VALUES ("
            + ",".join("?" for _ in range(29))
            + ")",
            (
                version_id,
                capsule_id,
                1,
                EXTRACTION_CONTRACT_VERSION,
                _json(evidence["extraction"]),
                REDACTION_RULES_VERSION,
                CANONICALIZATION_VERSION,
                canonical.sha256,
                _json(payload["activation"]),
                _json(payload["input_contract"]),
                _json(payload["output_contract"]),
                _json(payload["error_contract"]),
                _json(payload["runtime_allowlist"]),
                _json(payload["dom_scope"]),
                _json(payload["usage_scope"]),
                payload["html"],
                payload["css"],
                _json(payload["javascript_modules"]),
                _json(evidence["cleaning"]),
                SECURITY_RULES_VERSION,
                SUPERVISION_RULES_VERSION,
                "phase5-test-model",
                "b" * 64,
                NOW,
                _json(evidence["supervision"]),
                hashlib.sha256(_json(evidence["supervision"]).encode()).hexdigest(),
                VALIDATION_CONTRACT_VERSION,
                _json(evidence["validation"]),
                NOW,
            ),
        )
        connection.execute(
            "UPDATE capsules SET current_version_id = ?, status = ? WHERE capsule_id = ?",
            (version_id, status, capsule_id),
        )
    return capsule_id, version_id


def _runtime_receipt(_root: Path) -> dict[str, object]:
    return {
        "schema_version": "reweave_product_runtime_validation.v1",
        "status": "passed",
        "acceptance_scope": "real_qwebengine_product_bootstrap",
        "blocked_requests": [],
        "console_messages": [],
    }


def _quality_receipt(_root: Path) -> dict[str, object]:
    return {
        "schema_version": "reweave_product_quality.v1",
        "status": "passed",
        "acceptance_scope": "static_product_package",
        "checks": [],
        "source_project_write": False,
    }


def _composition_stub(**kwargs: object) -> dict[str, object]:
    capsules = sorted(
        list(kwargs["capsules"]),  # type: ignore[arg-type]
        key=lambda row: str(row["capability_kind"]),
    )
    by_kind = {row["capability_kind"]: row for row in capsules}
    connections: list[dict[str, str]] = []
    if "interaction" in by_kind and "computation" in by_kind:
        connections.append(
            {
                "from_version_id": by_kind["interaction"]["version_id"],
                "output": "calculate_requested",
                "to_version_id": by_kind["computation"]["version_id"],
                "input": "$",
            }
        )
    if "computation" in by_kind and "presentation" in by_kind:
        connections.append(
            {
                "from_version_id": by_kind["computation"]["version_id"],
                "output": "value",
                "to_version_id": by_kind["presentation"]["version_id"],
                "input": "$",
            }
        )
    html = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f'<meta http-equiv="Content-Security-Policy" content="{STRICT_CSP}">'
        '<link rel="stylesheet" href="./styles.css"></head><body>'
        '<main id="product-root"></main><script src="./app.js"></script>'
        "</body></html>\n"
    )
    return {
        "status": "composed",
        "composer_version": "phase5_test_composer.v1",
        "files": {
            "index.html": html,
            "styles.css": "#product-root { display: block; }\n",
            "app.js": '"use strict";\n',
        },
        "assets": {},
        "composition_manifest": {"connections": connections},
        "provenance": {"capsules": [row["version_id"] for row in capsules]},
    }


class _NoLegacyEngine:
    pass


@unittest.skipUnless(shutil.which("node"), "Node is required for Phase 5 generation")
class Phase5FormalGenerationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.state = self.root / "state"
        self._environment = patch.dict(
            os.environ, {"REWEAVE_STATE_DIR": str(self.state)}
        )
        self._environment.start()
        self.store = CapsuleWarehouseStore(self.state / "capsule_warehouse.sqlite3")
        self.store.initialize()
        self.ids: dict[str, str] = {}
        self.versions: dict[str, str] = {}
        for kind in ("presentation", "interaction", "computation"):
            capsule_id, version_id = _seed_capsule(self.store, kind)
            self.ids[kind] = capsule_id
            self.versions[kind] = version_id
        self.service = ReweaveAppService(
            _NoLegacyEngine(), capsule_store=self.store
        )

    def tearDown(self) -> None:
        self.service.close()
        self._environment.stop()
        self._temporary.cleanup()

    @contextmanager
    def _fast_generation(self):
        with (
            patch(
                "pimos_lite.reweave_app_service.compose_capsule_product",
                side_effect=_composition_stub,
            ),
            patch(
                "pimos_lite.reweave_app_service._validate_product_static",
                side_effect=_quality_receipt,
            ),
            patch(
                "pimos_lite.reweave_app_service._validate_product_runtime",
                side_effect=_runtime_receipt,
            ),
        ):
            yield

    def _wait(self, started: dict[str, object]) -> dict[str, object]:
        self.assertTrue(started.get("ok"), started)
        run_id = str(started["run_id"])
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            polled = self.service.get_intake_run({"run_id": run_id})
            self.assertTrue(polled.get("ok"), polled)
            state = polled["data"]
            if state["status"] in {"completed", "failed", "cancelled"}:
                return state
            time.sleep(0.01)
        self.fail("generation task did not finish")

    def _start_all(self) -> dict[str, object]:
        return self.service.generate_product(
            {
                "task": "Build a quote calculator",
                "capsule_ids": [
                    self.ids["presentation"],
                    self.ids["interaction"],
                    self.ids["computation"],
                ],
                "selection_mode": "manual",
            }
        )

    def _create_orphan(self) -> Path:
        products_root = self.state / "products"
        before = (
            {
                path.name
                for path in products_root.iterdir()
                if path.name.startswith("product_")
            }
            if products_root.is_dir()
            else set()
        )
        real_read = self.store.read_connection
        calls = 0

        def fail_cleanup_read():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise CapsuleStoreError("cleanup read unavailable")
            return real_read()

        with (
            self._fast_generation(),
            patch.object(
                self.service,
                "_register_product_usage",
                side_effect=sqlite3.OperationalError("usage write failed"),
            ),
            patch.object(self.store, "read_connection", side_effect=fail_cleanup_read),
            self.assertRaisesRegex(ProductGenerationError, "product_commit_failed"),
        ):
            self.service._generate_formal_product(
                "Build a quote calculator", list(self.ids.values())
            )
        products = [
            path
            for path in products_root.iterdir()
            if path.name.startswith("product_") and path.name not in before
        ]
        self.assertEqual(len(products), 1)
        return products[0]

    def test_formal_initial_state_does_not_load_historical_modules(self) -> None:
        script = """
import sys
from pimos_lite.reweave_app_service import ReweaveAppService
service = ReweaveAppService()
service.get_initial_state()
service.close()
for name in sys.modules:
    if name.startswith(('pimos_lite.reweave_engine', 'pimos_lite.capsule_module')):
        raise SystemExit(name)
    if name in {
        'pimos_lite.reweave_capsule_warehouse',
        'pimos_lite.reweave_preview_pack',
        'pimos_lite.reweave_preview_export',
        'pimos_lite.reweave_promote',
        'pimos_lite.composer.intent',
    }:
        raise SystemExit(name)
"""
        environment = dict(os.environ)
        environment["REWEAVE_STATE_DIR"] = str(self.root / "startup-state")
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_cli_run_builds_canonical_registered_product_from_real_evidence(self) -> None:
        if not (ROOT / "node_modules" / "esbuild" / "package.json").is_file():
            self.skipTest("npm ci is required for the formal composer")
        with (
            patch.object(
                run_public_reweave_demo,
                "ReweaveAppService",
                return_value=self.service,
            ),
            patch(
                "pimos_lite.reweave_app_service._validate_product_runtime",
                side_effect=_runtime_receipt,
            ),
        ):
            result = run_public_reweave_demo.run(
                "Build a quote calculator",
                list(self.ids.values()),
                state_dir=str(self.state),
            )

        self.assertTrue(result["ok"], result)
        product = Path(result["previewPath"])
        manifest_bytes = (product / "manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        self.assertEqual(manifest_bytes, _canonical_manifest_bytes(manifest))
        self.assertEqual(
            result["manifestDigest"], hashlib.sha256(manifest_bytes).hexdigest()
        )
        self.assertEqual(
            {row["version_id"] for row in manifest["capsules"]},
            set(self.versions.values()),
        )
        with self.store.read_connection() as connection:
            expected_hashes = {
                str(row["version_id"]): str(row["canonical_hash"])
                for row in connection.execute(
                    "SELECT version_id, canonical_hash FROM capsule_versions"
                )
            }
        self.assertEqual(
            {
                row["version_id"]: row["canonical_hash"]
                for row in manifest["capsules"]
            },
            expected_hashes,
        )
        expected_usage = {
            (row["version_id"], contribution, manifest["generated_at"])
            for row in manifest["capsules"]
            for contribution in row["contributions"]
        }
        with self.store.read_connection() as connection:
            usage = {
                (row["version_id"], row["contribution_role"], row["generated_at"])
                for row in connection.execute(
                    "SELECT * FROM product_capsule_usage WHERE product_id = ?",
                    (manifest["product_id"],),
                )
            }
        self.assertEqual(usage, expected_usage)
        self.assertEqual(
            self.service._read_product_record(product)["status"], "registered"
        )
        self.assertEqual(
            self.service.get_latest_product_entry_path(), str((product / "index.html").resolve())
        )
        self.assertEqual(
            self.service.generate_preview({}),
            {
                "ok": False,
                "error": {
                    "code": "legacy_generation_inactive",
                    "message_key": "legacy_generation_inactive",
                },
            },
        )

    def test_formal_composer_is_deterministic_and_input_order_independent(self) -> None:
        if not (ROOT / "node_modules" / "esbuild" / "package.json").is_file():
            self.skipTest("npm ci is required for the formal composer")
        arguments = {
            "task": "Build a quote calculator",
            "product_id": "product_1234567890abcdef",
            "generated_at": NOW,
        }
        capsules = _composer_capsules()
        first = compose_capsule_product(**arguments, capsules=capsules)
        second = compose_capsule_product(
            **arguments, capsules=list(reversed(capsules))
        )
        self.assertEqual(first, second)
        self.assertNotIn("reweave-formal-compose-", first["files"]["app.js"])

    def test_static_web_target_service_returns_review_only_patch_without_writes(
        self,
    ) -> None:
        if not (ROOT / "node_modules" / "esbuild" / "package.json").is_file():
            self.skipTest("npm ci is required for the formal composer")
        target = self.root / "target"
        target.mkdir()
        (target / "index.html").write_text(
            "<!doctype html><html><head></head><body><h1>Target</h1></body></html>\n",
            encoding="utf-8",
        )
        target_before = {
            path.relative_to(target).as_posix(): (
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in target.rglob("*")
            if path.is_file()
        }
        with self.store.read_connection() as connection:
            usage_before = int(
                connection.execute(
                    "SELECT COUNT(*) FROM product_capsule_usage"
                ).fetchone()[0]
            )
        revision_before = self.store.current_revision()

        profiled = self.service.analyze_static_web_target(
            {"target_path": str(target), "entry_relpath": "index.html"}
        )
        self.assertTrue(profiled.get("ok"), profiled)
        authorization = {
            "mode": TARGET_AUTHORIZATION_MODE,
            "target_snapshot_sha256": profiled["data"]["snapshot_sha256"],
        }
        with patch(
            "pimos_lite.reweave_app_service.compose_capsule_product",
            wraps=compose_capsule_product,
        ) as composer:
            result = self.service.generate_static_web_patch(
                {
                    "target_path": str(target),
                    "entry_relpath": "index.html",
                    "task": "Add quote calculator",
                    "capsule_ids": [
                        self.ids["presentation"],
                        self.ids["interaction"],
                        self.ids["computation"],
                    ],
                    "selection_mode": "manual",
                    "authorization": authorization,
                }
            )

        self.assertTrue(result.get("ok"), result)
        self.assertEqual(composer.call_count, 1)
        patch_data = result["data"]
        self.assertEqual(patch_data["status"], "ready_for_review")
        self.assertEqual(
            patch_data["strategy"], "static_web_iframe_embed.v1"
        )
        self.assertTrue(patch_data["target"]["profile"]["source_unchanged"])
        self.assertFalse(patch_data["authorization"]["target_project_write"])
        self.assertFalse(patch_data["authorization"]["apply"])
        self.assertFalse(patch_data["authorization"]["commit"])
        self.assertIn("data-reweave-plan", patch_data["text_unified_diff"])
        self.assertNotIn(str(target), json.dumps(patch_data, ensure_ascii=False))
        target_after = {
            path.relative_to(target).as_posix(): (
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in target.rglob("*")
            if path.is_file()
        }
        self.assertEqual(target_after, target_before)
        self.assertFalse((target / "reweave").exists())
        self.assertFalse((self.state / "products").exists())
        with self.store.read_connection() as connection:
            usage_after = int(
                connection.execute(
                    "SELECT COUNT(*) FROM product_capsule_usage"
                ).fetchone()[0]
            )
        revision_after = self.store.current_revision()
        self.assertEqual(usage_after, usage_before)
        self.assertEqual(revision_after, revision_before)

    def test_static_web_target_service_rejects_stale_review_authorization(
        self,
    ) -> None:
        target = self.root / "target"
        target.mkdir()
        (target / "index.html").write_text(
            "<!doctype html><html><head></head><body></body></html>\n",
            encoding="utf-8",
        )

        result = self.service.generate_static_web_patch(
            {
                "target_path": str(target),
                "entry_relpath": "index.html",
                "task": "Add quote calculator",
                "capsule_ids": [self.ids["presentation"]],
                "selection_mode": "manual",
                "authorization": {
                    "mode": TARGET_AUTHORIZATION_MODE,
                    "target_snapshot_sha256": "0" * 64,
                },
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "target_snapshot_mismatch")
        self.assertEqual(
            result["error"]["evidence"],
            {
                "status": "rejected",
                "code": "target_snapshot_mismatch",
                "phase": "authorization",
            },
        )
        self.assertFalse((target / "reweave").exists())
        self.assertFalse((self.state / "products").exists())

    def test_formal_composer_rechecks_fixed_computation_adapter(self) -> None:
        if not (ROOT / "node_modules" / "esbuild" / "package.json").is_file():
            self.skipTest("npm ci is required for the formal composer")
        input_contract = _object_contract(
            {
                "quantity": {"type": "integer", "minimum": 0, "maximum": 100},
                "unit_price": {"type": "integer", "minimum": 0, "maximum": 1000},
            }
        )
        output_contract = _object_contract(
            {"total": {"type": "integer", "minimum": 0, "maximum": 100000}}
        )
        details = _object_contract({})
        adapter_source = """import { calculate as __source } from "../calculate.js";

export function compute(input) {
  if (
    input === null
    || typeof input !== "object"
    || Array.isArray(input)
    || Object.keys(input).length !== 2
    || !Object.hasOwn(input, "quantity")
    || !Object.hasOwn(input, "unit_price")
  ) {
    return { ok: false, error: { code: "INPUT_CONTRACT_VIOLATION", field: null, details: {} } };
  }
  if (
    !Number.isSafeInteger(input.quantity)
    || input.quantity < 0
    || input.quantity > 100
    || !Number.isSafeInteger(input.unit_price)
    || input.unit_price < 0
    || input.unit_price > 1000
  ) {
    return { ok: false, error: { code: "INPUT_CONTRACT_VIOLATION", field: null, details: {} } };
  }
  const result = __source(input.quantity, input.unit_price);
  if (
    !Number.isSafeInteger(result)
    || result < 0
    || result > 100000
  ) {
    return { ok: false, error: { code: "OUTPUT_CONTRACT_VIOLATION", field: null, details: {} } };
  }
  return { ok: true, value: { "total": result } };
}
"""
        capsule = {
            "candidate_origin": "deterministic_computation_adapter",
            "adapter_contract_version": "computation_adapter.v1",
            "capability_kind": "computation",
            "activation": {
                "mode": "declared_input_compute",
                "entry_module": "__reweave_adapter__/compute.js",
                "entrypoint": "compute",
            },
            "input_contract": input_contract,
            "output_contract": output_contract,
            "error_contract": {
                "schema": "error_contract.v1",
                "errors": {
                    "INPUT_CONTRACT_VIOLATION": {"field": None, "details": details},
                    "OUTPUT_CONTRACT_VIOLATION": {"field": None, "details": details},
                },
            },
            "runtime_allowlist": ["local_computation"],
            "dom_scope": {
                "root_contract": "capsule_root",
                "selectors": [],
                "classes": [],
                "attributes": [],
                "events": [],
            },
            "usage_scope": {"kind": "general"},
            "html": "",
            "css": "",
            "javascript_modules": [
                {
                    "path": "calculate.js",
                    "source": "export function calculate(quantity, price) { return quantity * price; }\n",
                },
                {
                    "path": "__reweave_adapter__/compute.js",
                    "source": adapter_source,
                },
            ],
            "assets": [],
        }

        bundle = _bundle_formal_capsule(capsule, "ReweaveAdapterTest")

        self.assertIn("ReweaveAdapterTest", bundle)
        mutated = json.loads(json.dumps(capsule))
        mutated["javascript_modules"][1]["source"] = adapter_source.replace(
            "export function compute", "\nexport function compute", 1
        )
        with self.assertRaisesRegex(
            ValueError, "computation_adapter_authorization_invalid"
        ):
            _bundle_formal_capsule(mutated, "ReweaveAdapterTest")

    def test_formal_composer_accepts_and_rechecks_computation_adapter_v2(self) -> None:
        if not (ROOT / "node_modules" / "esbuild" / "package.json").is_file():
            self.skipTest("npm ci is required for the formal composer")
        capsules = _composer_capsules()
        computation = next(
            row for row in capsules if row["capability_kind"] == "computation"
        )
        computation["candidate_origin"] = "deterministic_computation_adapter"
        computation["adapter_contract_version"] = "computation_adapter.v2"
        computation["error_contract"] = _adapter_errors()
        computation["activation"] = {
            "mode": "declared_input_compute",
            "entry_module": "__reweave_adapter__/compute.js",
            "entrypoint": "compute",
        }
        computation["javascript_modules"] = [
            {
                "path": "__reweave_adapter__/compute.js",
                "source": generate_computation_adapter_v2(
                    ["quantity"],
                    computation["input_contract"],
                    computation["output_contract"],
                ),
            },
            {
                "path": "__reweave_capture__/selected.js",
                "source": (
                    "export function __selected(quantity) { "
                    "return quantity * 2; }\n"
                ),
            },
        ]

        composition = compose_capsule_product(
            task="Build a quote calculator",
            product_id="product_1234567890abcdef",
            generated_at=NOW,
            capsules=capsules,
        )

        self.assertEqual(composition["status"], "composed")
        self.assertIn("ReweaveFormalCapsule", composition["files"]["app.js"])

    def test_formal_composer_rejects_invalid_computation_adapter_v2_modules(self) -> None:
        base = _capsule_payload("computation")
        base.update(
            candidate_origin="deterministic_computation_adapter",
            adapter_contract_version="computation_adapter.v2",
        )
        base["error_contract"] = _adapter_errors()
        base["activation"] = {
            "mode": "declared_input_compute",
            "entry_module": "__reweave_adapter__/compute.js",
            "entrypoint": "compute",
        }
        base["javascript_modules"] = [
            {
                "path": "__reweave_adapter__/compute.js",
                "source": generate_computation_adapter_v2(
                    ["quantity"], base["input_contract"], base["output_contract"]
                ),
            },
            {
                "path": "__reweave_capture__/selected.js",
                "source": "export function __selected(quantity) { return quantity * 2; }\n",
            },
        ]
        missing = json.loads(json.dumps(base))
        missing["javascript_modules"] = missing["javascript_modules"][:1]
        extra = json.loads(json.dumps(base))
        extra["javascript_modules"].append(
            {"path": "extra.js", "source": "export const extra = 1;\n"}
        )
        for label, capsule in (("missing", missing), ("extra", extra)):
            with self.subTest(label=label), self.assertRaisesRegex(
                ValueError, "formal_computation_adapter_v2_modules_invalid"
            ):
                _bundle_formal_capsule(capsule, "ReweaveAdapterV2Invalid")

    def test_formal_composer_rejects_tampered_computation_adapter_v2(self) -> None:
        capsule = _capsule_payload("computation")
        capsule.update(
            candidate_origin="deterministic_computation_adapter",
            adapter_contract_version="computation_adapter.v2",
        )
        capsule["error_contract"] = _adapter_errors()
        capsule["activation"] = {
            "mode": "declared_input_compute",
            "entry_module": "__reweave_adapter__/compute.js",
            "entrypoint": "compute",
        }
        adapter = generate_computation_adapter_v2(
            ["quantity"], capsule["input_contract"], capsule["output_contract"]
        )
        capsule["javascript_modules"] = [
            {
                "path": "__reweave_adapter__/compute.js",
                "source": adapter.replace(
                    "const result = __source(input.quantity);",
                    "const result = __source(input.quantity) + 1;",
                ),
            },
            {
                "path": "__reweave_capture__/selected.js",
                "source": "export function __selected(quantity) { return quantity * 2; }\n",
            },
        ]
        with self.assertRaisesRegex(
            ValueError, "computation_adapter_authorization_invalid"
        ):
            _bundle_formal_capsule(capsule, "ReweaveAdapterV2Tampered")

    def test_formal_composer_does_not_apply_v2_module_rule_to_plain_computation(self) -> None:
        capsule = _capsule_payload("computation")
        capsule["javascript_modules"] = [
            {
                "path": "computation.js",
                "source": (
                    'import { factor } from "./helper.js";\n'
                    "export function compute(input) {\n"
                    "  return {ok: true, value: {total: input.quantity * factor}};\n"
                    "}\n"
                ),
            },
            {
                "path": "helper.js",
                "source": "export const factor = 2;\n",
            },
        ]

        bundle = _bundle_formal_capsule(capsule, "ReweavePlainComputation")

        self.assertIn("ReweavePlainComputation", bundle)

    def test_formal_runtime_rejects_values_outside_data_contract(self) -> None:
        if not (ROOT / "node_modules" / "esbuild" / "package.json").is_file():
            self.skipTest("npm ci is required for the formal composer")
        node = os.environ.get("REWEAVE_NODE") or shutil.which("node")
        self.assertIsNotNone(node)
        cases = {
            "string_total": (
                "computation_output_contract_violation",
                "computation",
                'export function compute(input) { return {ok:true,value:{total:"not-an-integer"}}; }\n',
                False,
            ),
            "non_finite_total": (
                "computation_output_contract_violation",
                "computation",
                "export function compute(input) { return {ok:true,value:{total:0 / 0}}; }\n",
                False,
            ),
            "quantity_out_of_range": (
                "interaction_output_contract_violation",
                "interaction",
                """export function mount(root, ports) {
  const button = root.querySelector("[data-action='calculate']");
  const onClick = (event) => {
    event.preventDefault();
    ports.emit("calculate_requested", {quantity: 999});
  };
  button.addEventListener("click", onClick);
  return () => { button.removeEventListener("click", onClick); };
}
""",
                True,
            ),
        }
        for label, (expected, kind, source, invoke_handler) in cases.items():
            with self.subTest(label=label):
                capsules = _composer_capsules()
                capsule = next(
                    row for row in capsules if row["capability_kind"] == kind
                )
                capsule["javascript_modules"][0]["source"] = source
                composition = compose_capsule_product(
                    task="Build a quote calculator",
                    product_id="product_1234567890abcdef",
                    generated_at=NOW,
                    capsules=capsules,
                )
                add_listener = (
                    'addEventListener(_name, handler) { handler({preventDefault() {}}); }'
                    if invoke_handler
                    else "addEventListener() {}"
                )
                prelude = f"""const total = {{textContent: ""}};
const quantity = {{value: "2"}};
const button = {{{add_listener}, removeEventListener() {{}}}};
const root = {{querySelector(selector) {{
  return selector.includes("total") ? total : selector.includes("quantity") ? quantity : button;
}}}};
globalThis.document = {{getElementById() {{ return root; }}}};
"""
                target = self.root / f"{label}.js"
                target.write_text(
                    prelude + composition["files"]["app.js"], encoding="utf-8"
                )
                completed = subprocess.run(
                    [str(node), str(target)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(expected, completed.stderr)

    def test_generation_rejects_ineligible_historical_and_mixed_capability(self) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE capsules SET status = 'pending_revalidation' WHERE capsule_id = ?",
                (self.ids["presentation"],),
            )
        state = self._wait(
            self.service.generate_product(
                {
                    "task": "Quote",
                    "capsule_ids": [self.ids["presentation"]],
                    "selection_mode": "manual",
                }
            )
        )
        self.assertEqual(
            state["error"]["code"], "formal_capsule_not_generation_eligible"
        )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE capsules SET status = 'active' WHERE capsule_id = ?",
                (self.ids["presentation"],),
            )

        historical = self._wait(
            self.service.generate_product(
                {
                    "task": "Quote",
                    "capsule_ids": [self.versions["presentation"]],
                    "selection_mode": "manual",
                }
            )
        )
        self.assertEqual(historical["error"]["code"], "formal_capsule_not_found")

        foreign_id, _version = _seed_capsule(
            self.store,
            "presentation",
            capability_key="foreign_capability",
            suffix="foreign",
        )
        mixed = self._wait(
            self.service.generate_product(
                {
                    "task": "Mixed",
                    "capsule_ids": [foreign_id, self.ids["computation"]],
                    "selection_mode": "manual",
                }
            )
        )
        self.assertEqual(mixed["error"]["code"], "product_capability_group_mismatch")

    def test_definitive_zero_usage_failure_removes_promoted_product(self) -> None:
        with (
            self._fast_generation(),
            patch.object(
                self.service,
                "_register_product_usage",
                side_effect=sqlite3.OperationalError("usage write failed"),
            ),
        ):
            state = self._wait(self._start_all())
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["error"]["code"], "product_commit_failed")
        products = self.state / "products"
        self.assertFalse(
            any(path.name.startswith("product_") for path in products.iterdir())
        )

    def test_unknown_cleanup_read_never_deletes_already_registered_product(self) -> None:
        real_register = self.service._register_product_usage
        real_read = self.store.read_connection
        read_calls = 0

        def register_then_report_failure(*args: object, **kwargs: object) -> None:
            real_register(*args, **kwargs)
            raise sqlite3.OperationalError("commit acknowledgement lost")

        def fail_cleanup_read():
            nonlocal read_calls
            read_calls += 1
            if read_calls == 3:
                raise CapsuleStoreError("cleanup read unavailable")
            return real_read()

        with (
            self._fast_generation(),
            patch.object(
                self.service,
                "_register_product_usage",
                side_effect=register_then_report_failure,
            ),
            patch.object(self.store, "read_connection", side_effect=fail_cleanup_read),
            self.assertRaisesRegex(ProductGenerationError, "product_commit_failed"),
        ):
            self.service._generate_formal_product(
                "Build a quote calculator", list(self.ids.values())
            )

        products = [
            path
            for path in (self.state / "products").iterdir()
            if path.name.startswith("product_")
        ]
        self.assertEqual(len(products), 1)
        with real_read() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM product_capsule_usage WHERE product_id = ?",
                (products[0].name,),
            ).fetchone()[0]
        self.assertGreater(count, 0)

    def test_manifest_tamper_and_symlink_are_not_registered_or_latest(self) -> None:
        with self._fast_generation():
            state = self._wait(self._start_all())
        result = state["data"]
        product = Path(result["previewPath"])
        index = product / "index.html"
        original = index.read_bytes()
        index.write_bytes(original + b"<!-- tampered -->")
        with self.assertRaisesRegex(
            ProductGenerationError, "product_manifest_file_mismatch"
        ):
            self.service._read_product_record(product)
        self.assertIsNone(self.service.get_latest_product_entry_path())

        index.write_bytes(original)
        outside = self.root / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        link = product / "unexpected-link"
        try:
            link.symlink_to(outside)
        except (NotImplementedError, OSError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(
            ProductGenerationError, "product_directory_symlink_forbidden"
        ):
            self.service._read_product_record(product)
        self.assertIsNone(self.service.get_latest_product_entry_path())

    def test_orphan_retry_rechecks_exact_manifest_and_rereads_registration(self) -> None:
        orphan = self._create_orphan()
        record = self.service._read_product_record(orphan)
        self.assertEqual(record["status"], "usage_registration_incomplete")
        with patch.object(
            self.service,
            "_read_product_record",
            wraps=self.service._read_product_record,
        ) as reader, self._fast_generation():
            retried = self.service.retry_product_usage_registration({"product_id": orphan.name})
        self.assertTrue(retried["ok"], retried)
        self.assertEqual(retried["data"]["status"], "registered")
        self.assertEqual(reader.call_count, 2)

        legacy = self._create_orphan()
        legacy_manifest_path = legacy / "manifest.json"
        legacy_manifest = json.loads(legacy_manifest_path.read_bytes())
        for row in legacy_manifest["capsules"]:
            row.pop("canonical_hash")
        legacy_manifest_path.write_bytes(_canonical_manifest_bytes(legacy_manifest))
        with self._fast_generation():
            legacy_retried = self.service.retry_product_usage_registration(
                {"product_id": legacy.name}
            )
        self.assertTrue(legacy_retried["ok"], legacy_retried)
        self.assertEqual(legacy_retried["data"]["status"], "registered")

        def forge_identity(manifest: dict[str, object]) -> None:
            manifest["capsules"][0]["role_key"] = "forged_role"  # type: ignore[index]

        def forge_scope(manifest: dict[str, object]) -> None:
            manifest["product_usage_scope"] = {
                "kind": "brand_limited",
                "brand_profile_id": "forged-brand",
                "brand_profile_digest": "f" * 64,
            }

        def forge_contributions(manifest: dict[str, object]) -> None:
            row = manifest["capsules"][0]  # type: ignore[index]
            row["contributions"] = [row["capability_kind"]]

        def forge_canonical_hash(manifest: dict[str, object]) -> None:
            manifest["capsules"][0]["canonical_hash"] = "f" * 64  # type: ignore[index]

        def forge_connection(manifest: dict[str, object]) -> None:
            manifest["connections"][0]["output"] = "forged_event"  # type: ignore[index]

        for label, mutate in (
            ("identity", forge_identity),
            ("scope", forge_scope),
            ("contributions", forge_contributions),
            ("canonical_hash", forge_canonical_hash),
            ("connection", forge_connection),
        ):
            with self.subTest(label=label):
                second = self._create_orphan()
                manifest_path = second / "manifest.json"
                manifest = json.loads(manifest_path.read_bytes())
                mutate(manifest)
                manifest_path.write_bytes(_canonical_manifest_bytes(manifest))
                with self._fast_generation():
                    rejected = self.service.retry_product_usage_registration(
                        {"product_id": second.name}
                    )
                self.assertFalse(rejected["ok"], rejected)
                self.assertEqual(
                    rejected["error"]["code"],
                    "formal_capsule_selection_expired",
                )
                with self.store.read_connection() as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT COUNT(*) FROM product_capsule_usage WHERE product_id = ?",
                            (second.name,),
                        ).fetchone()[0],
                        0,
                    )

    @unittest.skipUnless(
        (ROOT / ".venv-reweave" / "bin" / "python").is_file()
        or (ROOT / ".venv-reweave" / "Scripts" / "python.exe").is_file(),
        "Independent PySide6 desktop environment required",
    )
    def test_orphan_retry_rejects_forged_receipt_after_real_qweb_revalidation(
        self,
    ) -> None:
        if not (ROOT / "node_modules" / "esbuild" / "package.json").is_file():
            self.skipTest("npm ci is required for the formal composer")
        products_root = self.state / "products"
        real_read = self.store.read_connection

        def create_real_orphan() -> Path:
            before = {path.name for path in products_root.glob("product_*")}
            read_calls = 0

            def fail_cleanup_read():
                nonlocal read_calls
                read_calls += 1
                if read_calls == 3:
                    raise CapsuleStoreError("cleanup read unavailable")
                return real_read()

            with (
                patch.object(
                    self.service,
                    "_register_product_usage",
                    side_effect=sqlite3.OperationalError("usage write failed"),
                ),
                patch.object(
                    self.store, "read_connection", side_effect=fail_cleanup_read
                ),
                self.assertRaisesRegex(
                    ProductGenerationError, "product_commit_failed"
                ),
            ):
                self.service._generate_formal_product(
                    "Build a quote calculator", list(self.ids.values())
                )
            products = [
                path
                for path in products_root.glob("product_*")
                if path.name not in before
            ]
            self.assertEqual(len(products), 1)
            return products[0]

        genuine = create_real_orphan()
        recovered = self.service.retry_product_usage_registration(
            {"product_id": genuine.name}
        )
        self.assertTrue(recovered["ok"], recovered)
        self.assertEqual(recovered["data"]["status"], "registered")

        orphan = create_real_orphan()
        receipt_path = orphan / "runtime_validation.json"
        forged = json.loads(receipt_path.read_bytes())
        forged["acceptance_scope"] = "forged_browser_claim"
        receipt_path.write_text(
            json.dumps(forged, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_path = orphan / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        for row in manifest["files"]:
            if row["path"] == "runtime_validation.json":
                content = receipt_path.read_bytes()
                row["sha256"] = hashlib.sha256(content).hexdigest()
                row["size_bytes"] = len(content)
        manifest_path.write_bytes(_canonical_manifest_bytes(manifest))

        rejected = self.service.retry_product_usage_registration(
            {"product_id": orphan.name}
        )
        self.assertFalse(rejected["ok"], rejected)
        self.assertEqual(
            rejected["error"]["code"], "product_validation_receipt_mismatch"
        )
        with real_read() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM product_capsule_usage WHERE product_id = ?",
                    (orphan.name,),
                ).fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
