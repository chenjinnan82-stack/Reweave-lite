"""Stage 3 safety and isolated-runtime tests."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pimos_lite.reweave_capsule_stage3 as stage3_module
from pimos_lite.reweave_capsule_intake import (
    EXTRACTION_CONTRACT_VERSION,
    IntakeError,
    ReweaveCapsuleIntake,
)
from pimos_lite.reweave_capsule_stage3 import (
    CAPTURE_MAPPING_V3,
    CAPTURE_MAPPING_V4,
    FROZEN_UI_REVIEW_ADMISSION_AUTHORIZATION_VERSION,
    FROZEN_UI_REVIEW_ADMISSION_VERSION,
    PreparedReview,
    OllamaSupervisor,
    ReweaveCapsuleStage3,
    Stage3Error,
    capture_static_gate,
    _normalize_capture_mapping_v3,
    _normalize_capture_mapping_v4,
    inspect_ephemeral_computation_offers_v2,
    make_prepared_review,
    _clean_assets,
    _validate_computation,
    _validate_qweb,
    sanitize_css,
    sanitize_html,
)
from pimos_lite.reweave_page_capability_contract import (
    build_page_capability_contract_v2,
)
from pimos_lite.reweave_capsule_store import (
    CapsuleStoreError,
    CapsuleWarehouseStore,
)
from pimos_lite.reweave_javascript_source import (
    JavascriptSourceService,
    _descriptor_relative_snapshot_supported,
)


ROOT = Path(__file__).resolve().parents[1]


def _stage_e_graph(snapshot: object, entry_module: str) -> dict[str, object]:
    modules = [
        {
            "path": item.logical_path,
            "source_base64": base64.b64encode(item.content).decode("ascii"),
            "sha256": item.content_sha256,
        }
        for item in snapshot.modules
    ]
    request = {
        "schema": "source_graph_request.v1",
        "mode": "graph",
        "project_id": snapshot.project_id,
        "scope_snapshot_sha256": snapshot.scope_snapshot_sha256,
        "source_identity_sha256": snapshot.source_identity_sha256,
        "entry_modules": [entry_module],
        "module_snapshot": modules,
        "symlinks": [{"path": item} for item in snapshot.symlinks],
    }
    completed = subprocess.run(
        [
            shutil.which("node"),
            "--max-old-space-size=512",
            str(ROOT / "scripts" / "analyze_reweave_source_graph.mjs"),
        ],
        input=json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["status"] == "ok", result
    return result


def _stage_e_selection(
    snapshot: object, entry_module: str, export_name: str
) -> tuple[dict[str, str], list[dict[str, object]]]:
    graph = _stage_e_graph(snapshot, entry_module)
    module = next(
        item for item in graph["modules"] if item["logical_path"] == entry_module
    )
    exported = next(
        item for item in module["exports"] if item["public_name"] == export_name
    )
    bindings = {
        binding["binding_id"]: binding
        for graph_module in graph["modules"]
        for binding in graph_module["bindings"]
    }
    binding = bindings[exported["binding_id"]]
    while "parameters" not in binding:
        binding = bindings[binding["target_binding_id"]]
    return (
        {
            "module_relpath": entry_module,
            "export_name": export_name,
            "target_binding_id": binding["binding_id"],
        },
        binding["parameters"],
    )


class HtmlCssSafetyTest(unittest.TestCase):
    def test_html_is_scoped_rewritten_and_fail_closed(self) -> None:
        scope = {
            "selectors": ["[data-ref='quantity']", "[data-action='calculate']"],
        }
        cleaned = sanitize_html(
            """<section data-capsule-root class="quote">
<label for="quantity">Quantity</label>
<input id="quantity" data-ref="quantity" type="number" min="0">
<button data-action="calculate" type="button">Calculate</button>
</section>""",
            dom_scope=scope,
            asset_paths=set(),
            redact_strings=[],
        )
        self.assertIn('id="__CAPSULE_ID__-quantity"', cleaned)
        self.assertIn('for="__CAPSULE_ID__-quantity"', cleaned)

        rejected = [
            '<section data-capsule-root><button onclick="alert(1)">X</button></section>',
            '<section data-capsule-root><img src="https://example.test/a.png"></section>',
            '<section data-capsule-root><script>1</script></section>',
            '<section data-capsule-root><div for="quantity"></div></section>',
            '<section data-capsule-root><!doctype html><p>X</p></section>',
            '<section data-capsule-root><p id="same"></p><p id="same"></p></section>',
            '<section data-capsule-root><p id="Foo"></p><p id="foo"></p></section>',
            '<section data-capsule-root><p aria-label="private">X</p></section>',
        ]
        for source in rejected:
            with self.subTest(source=source), self.assertRaises(Stage3Error):
                sanitize_html(
                    source,
                    dom_scope={"selectors": []},
                    asset_paths=set(),
                    redact_strings=[],
                )
        deeply_nested = (
            '<section data-capsule-root>' + "<div>" * 1500 + "x" + "</div>" * 1500 + "</section>"
        )
        with self.assertRaisesRegex(Stage3Error, "html_parse_failed"):
            sanitize_html(
                deeply_nested,
                dom_scope={"selectors": []},
                asset_paths=set(),
                redact_strings=[],
            )

    def test_html_root_selection_contract(self) -> None:
        allowed = {
            "explicit": (
                "<main>outside</main><section data-capsule-root>inside</section>",
                "<section>inside</section>",
            ),
            "main": ("<aside>outside</aside><main>inside</main>", "<main>inside</main>"),
            "form": ("<aside>outside</aside><form>inside</form>", "<form>inside</form>"),
        }
        for label, (source, expected) in allowed.items():
            with self.subTest(label=label):
                self.assertEqual(
                    sanitize_html(
                        source,
                        dom_scope={"selectors": []},
                        asset_paths=set(),
                        redact_strings=[],
                    ),
                    expected,
                )

        rejected = {
            "multiple_explicit": (
                "<main data-capsule-root></main><section data-capsule-root></section>"
            ),
            "ambiguous": "<main></main><main></main><form></form><form></form>",
            "nested_explicit": (
                "<section data-capsule-root><div data-capsule-root></div></section>"
            ),
        }
        for label, source in rejected.items():
            with self.subTest(label=label), self.assertRaisesRegex(
                Stage3Error, "html_capsule_root_invalid"
            ):
                sanitize_html(
                    source,
                    dom_scope={"selectors": []},
                    asset_paths=set(),
                    redact_strings=[],
                )

    def test_stage3_page_capability_declaration_validates_dom_accesses(self) -> None:
        cleaned = sanitize_html(
            """<section data-capsule-root>
<input data-ref="quantity" type="number">
<button data-action="calculate" type="button">Calculate</button>
<span data-ref="total"></span>
</section>""",
            dom_scope={
                "selectors": [
                    "[data-action='calculate']",
                    "[data-ref='quantity']",
                    "[data-ref='total']",
                ]
            },
            asset_paths=set(),
            redact_strings=[],
        )
        declaration = stage3_module._stage3_page_capability_declaration(
            "interaction",
            cleaned,
            [
                {
                    "selector": "[data-action='calculate']",
                    "reads": [],
                    "writes": [],
                    "events": ["click"],
                },
                {
                    "selector": "[data-ref='quantity']",
                    "reads": ["value"],
                    "writes": [],
                    "events": [],
                },
            ],
        )
        self.assertEqual(
            declaration["schema_version"],
            "page_capability_declaration.v2",
        )
        self.assertEqual(declaration["capability_kind"], "interaction")
        self.assertEqual(len(declaration["requires"]), 2)

        with self.assertRaisesRegex(Stage3Error, "page_capability_event_missing"):
            stage3_module._stage3_page_capability_declaration(
                "interaction",
                cleaned,
                [
                    {
                        "selector": "[data-ref='total']",
                        "reads": [],
                        "writes": [],
                        "events": ["submit"],
                    }
                ],
            )

    def test_css_parser_scopes_safe_rules_and_rejects_escape_or_global_access(self) -> None:
        cleaned = sanitize_css(
            ".thumbnail > [data-state='ready']:hover { display: grid; gap: 0.75rem; }",
            redact_strings=[],
        )
        self.assertIn("__CAPSULE_ROOT__ .thumbnail", cleaned)

        rejected = [
            "body { color: red; }",
            ".a + .b { color: red; }",
            "@import 'remote.css';",
            ".a { background-image: url('x'); }",
            ".a\\75 rl { color: red; }",
            ".a) { color: red; }",
        ]
        for source in rejected:
            with self.subTest(source=source), self.assertRaises(Stage3Error):
                sanitize_css(source, redact_strings=[])


@unittest.skipUnless(shutil.which("node"), "Node is required for TypeScript AST safety")
class JavaScriptSafetyTest(unittest.TestCase):
    def _analyze(
        self,
        source: str,
        capability_kind: str = "interaction",
        extra_modules: list[dict[str, str]] | None = None,
    ) -> dict[str, object]:
        entrypoint = {
            "presentation": "render",
            "interaction": "mount",
            "computation": "compute",
        }[capability_kind]
        module_name = f"{capability_kind}.js"
        request = {
            "mode": "candidate",
            "capability_kind": capability_kind,
            "activation": {"entry_module": module_name, "entrypoint": entrypoint},
            "dom_scope": {
                "selectors": ["[data-action='calculate']", "[data-ref='quantity']"],
                "classes": ["is-invalid"],
                "attributes": ["data-state"],
                "events": ["click"],
            },
            "output_contract": {
                "schema": "event_outputs.v1",
                "events": {"calculate_requested": {}},
            },
            "javascript_modules": [
                {"path": module_name, "source": source},
                *(extra_modules or []),
            ],
        }
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "scripts/analyze_reweave_security.mjs")],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def test_interaction_event_is_opaque_and_dispose_is_required(self) -> None:
        safe = self._analyze(
            """export function mount(root, ports) {
  const quantity = root.querySelector("[data-ref='quantity']");
  const button = root.querySelector("[data-action='calculate']");
  const onClick = (event) => {
    event.preventDefault();
    ports.emit("calculate_requested", {quantity: Number(quantity.value)});
  };
  button.addEventListener("click", onClick);
  return () => { button.removeEventListener("click", onClick); };
}"""
        )
        self.assertEqual(safe["status"], "passed")
        self.assertEqual(
            safe["page_capability_accesses"],
            [
                {
                    "selector": "[data-action='calculate']",
                    "reads": [],
                    "writes": [],
                    "events": ["click"],
                },
                {
                    "selector": "[data-ref='quantity']",
                    "reads": ["value"],
                    "writes": [],
                    "events": [],
                },
            ],
        )

        for fragment, code in [
            ("const leaked = event.target;", "event_object_property_forbidden"),
            ("fetch('/track');", "forbidden_call"),
            ("setTimeout(() => {}, 1);", "forbidden_call"),
        ]:
            source = """export function mount(root, ports) {
  const quantity = root.querySelector("[data-ref='quantity']");
  const button = root.querySelector("[data-action='calculate']");
  const onClick = (event) => { event.preventDefault(); %s };
  button.addEventListener("click", onClick);
  return () => { button.removeEventListener("click", onClick); };
}""" % fragment
            with self.subTest(code=code):
                result = self._analyze(source)
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["error_code"], code)

        missing_dispose = self._analyze(
            """export function mount(root, ports) {
  const button = root.querySelector("[data-action='calculate']");
  const onClick = (event) => { event.preventDefault(); };
  button.addEventListener("click", onClick);
  return () => {};
}"""
        )
        self.assertEqual(missing_dispose["error_code"], "interaction_dispose_not_closed")

    def test_dom_provenance_and_imported_handlers_fail_closed(self) -> None:
        escaped_dom = self._analyze(
            """export function mount(root, ports) {
  const button = root.querySelector("[data-action='calculate']");
  root.querySelector("[data-action='calculate']").offsetParent.hidden = true;
  const onClick = (event) => { event.preventDefault(); };
  button.addEventListener("click", onClick);
  return () => { button.removeEventListener("click", onClick); };
}"""
        )
        self.assertEqual(escaped_dom["status"], "rejected")
        self.assertEqual(escaped_dom["error_code"], "dom_write_forbidden")

        imported_handler = self._analyze(
            """import {onClick} from "./handler.js";
export function mount(root, ports) {
  const button = root.querySelector("[data-action='calculate']");
  button.addEventListener("click", onClick);
  return () => { button.removeEventListener("click", onClick); };
}""",
            extra_modules=[
                {
                    "path": "handler.js",
                    "source": "export function onClick(event) { const leaked = event.target; }\n",
                }
            ],
        )
        self.assertEqual(imported_handler["status"], "rejected")
        self.assertEqual(
            imported_handler["error_code"], "event_handler_must_be_local"
        )

    def test_computation_rejects_state_environment_and_input_mutation(self) -> None:
        rejected = [
            (
                "let count = 0; export function compute(input) { count += 1; return {ok:true,value:{count}}; }",
                "module_state_mutation_forbidden",
            ),
            (
                "export function compute(input) { input.quantity = 2; return {ok:true,value:{quantity:2}}; }",
                "input_mutation_forbidden",
            ),
            (
                "export function compute(input) { return {ok:true,value:{value:Math.random()}}; }",
                "unknown_call_target",
            ),
            (
                "fetch('/track'); export function compute(input) { return {ok:true,value:{value:1}}; }",
                "module_top_level_execution_forbidden",
            ),
        ]
        for source, code in rejected:
            with self.subTest(code=code):
                result = self._analyze(source, "computation")
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["error_code"], code)

    def test_adapter_exception_does_not_authorize_ordinary_input_forwarding(self) -> None:
        helper = {
            "path": "calculate.js",
            "source": (
                "export function calculate(value) { "
                "return {ok:true,value:{total:value}}; }\n"
            ),
        }
        rejected = {
            "whole_input": (
                'import { calculate } from "./calculate.js"; '
                "export function compute(input) { return calculate(input); }"
            ),
            "input_value_alias": (
                'import { calculate } from "./calculate.js"; '
                "export function compute(input) { "
                "const value = input.quantity; return calculate(value); }"
            ),
            "input_value_expression_alias": (
                'import { calculate } from "./calculate.js"; '
                "export function compute(input) { "
                "const value = input.quantity + 0; return calculate(value); }"
            ),
            "input_value_conversion_alias": (
                'import { calculate } from "./calculate.js"; '
                "export function compute(input) { "
                "const value = Number(input.quantity); return calculate(value); }"
            ),
            "input_value_unary_expression": (
                'import { calculate } from "./calculate.js"; '
                "export function compute(input) { return calculate(+input.quantity); }"
            ),
            "input_value_template_expression": (
                'import { calculate } from "./calculate.js"; '
                "export function compute(input) { "
                "return calculate(`${input.quantity}`); }"
            ),
            "input_value_assignment_alias": (
                'import { calculate } from "./calculate.js"; '
                "export function compute(input) { "
                "let value = 0; value = input.quantity; return calculate(value); }"
            ),
            "local_closure_forwarding": (
                'import { calculate } from "./calculate.js"; '
                "export function compute(input) { "
                "const value = input.quantity; "
                "function forward() { return calculate(value); } "
                "return forward(); }"
            ),
            "member_call": (
                'import { calculate } from "./calculate.js"; '
                "export function compute(input) { "
                "return calculate.call(null, input.quantity); }"
            ),
            "dynamic_target": (
                'import { calculate } from "./calculate.js"; '
                "export function compute(input) { "
                "return (input.quantity ? calculate : calculate)(input.quantity); }"
            ),
        }

        for name, source in rejected.items():
            with self.subTest(name=name):
                result = self._analyze(
                    source,
                    "computation",
                    extra_modules=[helper],
                )
                self.assertEqual(result["status"], "rejected", result)

    def test_compute_worker_enforces_per_case_timeout(self) -> None:
        empty_object = {
            "schema": "data_contract.v1",
            "type": "object",
            "properties": {},
            "required": [],
            "additional_properties": False,
        }
        payload = {
            "activation": {"entry_module": "compute.js", "entrypoint": "compute"},
            "javascript_modules": [
                {
                    "path": "compute.js",
                    "source": "export function compute(input) { while (true) {} }",
                }
            ],
            "output_contract": empty_object,
            "error_contract": {"schema": "error_contract.v1", "errors": {}},
        }
        fixtures = {
            "schema": "synthetic_fixtures.v1",
            "normal": [{}],
            "boundary": [],
            "invalid": [],
        }
        with self.assertRaisesRegex(Stage3Error, "compute_case_timeout"):
            _validate_computation(payload, fixtures)

    def test_exact_duplicate_requires_full_current_version_evidence(self) -> None:
        cleaning = {
            "schema_version": "capsule_cleaning.v1",
            "status": "passed",
            "redaction_count": 0,
            "html_cleaned": False,
            "css_cleaned": False,
            "asset_count": 0,
        }
        security = {
            "schema_version": "fixed_security.v1",
            "status": "passed",
            "security_rules_version": "security_rules.v1",
            "listener_bindings": [],
        }
        validation = {
            "schema_version": "runtime_validation.v1",
            "status": "passed",
            "acceptance_scope": "isolated_node_vm_computation",
            "normal_cases": 1,
            "boundary_cases": 1,
            "invalid_cases": 1,
            "repeatability_checked": True,
            "input_freeze_checked": True,
        }
        supervision = {
            "schema_version": "capsule_supervision.v1",
            "verdict": "approve",
            "capability_kind": "computation",
            "semantic_summary": "Compute a bounded total.",
            "keep_reason_codes": ["DECLARED_LOCAL_COMPUTATION"],
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
            "redaction_rules_version": "redaction_rules.v1",
            "canonicalization_version": 1,
            "security_rules_version": "security_rules.v1",
            "supervision_rules_version": "supervision_rules.v1",
            "validation_contract_version": "validation_contract.v1",
            "model_name": "test-model",
            "model_digest": "b" * 64,
            "supervised_at": "2026-07-15T00:00:00Z",
            "cleaning_summary": cleaning,
            "security_result": security,
            "validation": validation,
        }
        row = {
            "status": "active",
            "version_id": "old-version",
            "current_version_id": "new-version",
            "extraction_contract_version": EXTRACTION_CONTRACT_VERSION,
            "redaction_rules_version": "redaction_rules.v1",
            "canonicalization_version": 1,
            "security_rules_version": "security_rules.v1",
            "supervision_rules_version": "supervision_rules.v1",
            "validation_contract_version": "validation_contract.v1",
            "capability_kind": "computation",
            "supervision_model_name": "test-model",
            "supervision_model_digest": "b" * 64,
            "supervised_at": "2026-07-15T00:00:00Z",
            "supervision_result_json": json.dumps(supervision),
            "supervision_response_hash": "a" * 64,
            "validation_result_json": json.dumps(validation),
            "cleaning_summary_json": json.dumps(cleaning),
            "extraction_summary_json": json.dumps({"stage3_evidence": evidence}),
        }
        self.assertFalse(ReweaveCapsuleStage3._eligible_exact(row))
        row["current_version_id"] = "old-version"
        self.assertTrue(ReweaveCapsuleStage3._eligible_exact(row))

        for column, corrupted in (
            ("supervision_result_json", '{"verdict":"approve"}'),
            (
                "validation_result_json",
                '{"status":"passed","acceptance_scope":"isolated_node_vm_computation"}',
            ),
            ("supervision_response_hash", "not-a-sha256"),
            ("cleaning_summary_json", '{"status":"passed"}'),
            ("extraction_summary_json", "{}"),
        ):
            with self.subTest(column=column):
                original = row[column]
                row[column] = corrupted
                self.assertFalse(ReweaveCapsuleStage3._eligible_exact(row))
                row[column] = original

        review_supervision = dict(supervision)
        review_supervision.update({"verdict": "review", "review_required": True})
        row["supervision_result_json"] = json.dumps(review_supervision)
        self.assertFalse(ReweaveCapsuleStage3._eligible_exact(row))
        evidence["human_approval"] = {
            "decision": "publish_general",
            "review_id": "review-1",
            "decided_at": "2026-07-15T00:00:00Z",
        }
        row["extraction_summary_json"] = json.dumps({"stage3_evidence": evidence})
        self.assertTrue(ReweaveCapsuleStage3._eligible_exact(row))

    def test_manual_publication_evidence_requires_real_kind_specific_scope(self) -> None:
        evidence = {
            "schema_version": "stage3_evidence.v1",
            "extraction_contract_version": EXTRACTION_CONTRACT_VERSION,
            "redaction_rules_version": "redaction_rules.v1",
            "canonicalization_version": 1,
            "security_rules_version": "security_rules.v1",
            "supervision_rules_version": "supervision_rules.v1",
            "validation_contract_version": "validation_contract.v1",
            "model_name": "test-model",
            "model_digest": "b" * 64,
            "supervised_at": "2026-07-15T00:00:00Z",
            "cleaning_summary": {
                "schema_version": "capsule_cleaning.v1",
                "status": "passed",
                "redaction_count": 0,
                "html_cleaned": True,
                "css_cleaned": False,
                "asset_count": 0,
            },
            "security_result": {
                "schema_version": "fixed_security.v1",
                "status": "passed",
                "security_rules_version": "security_rules.v1",
                "listener_bindings": [],
            },
            "validation": {
                "schema_version": "qweb_validation.v1",
                "status": "passed",
                "normal_cases": 1,
                "boundary_cases": 0,
                "repeated_render": True,
                "dispose_idempotent": False,
                "remount_checked": False,
                "acceptance_scope": "synthetic_declared_interaction",
                "invalid_cases": 1,
            },
        }
        self.assertFalse(
            ReweaveCapsuleStage3._evidence_current(evidence, "presentation")
        )
        evidence["validation"]["acceptance_scope"] = "real_qwebengine_render"
        self.assertTrue(
            ReweaveCapsuleStage3._evidence_current(evidence, "presentation")
        )
        evidence["validation"]["unexpected"] = True
        self.assertFalse(
            ReweaveCapsuleStage3._evidence_current(evidence, "presentation")
        )


class _ApprovingSupervisor:
    def __init__(self):
        self.calls = 0

    def supervise(self, _summary, capability_kind):
        self.calls += 1
        result = {
            "schema_version": "capsule_supervision.v1",
            "verdict": "approve",
            "capability_kind": capability_kind,
            "semantic_summary": "Compute a bounded total.",
            "keep_reason_codes": ["DECLARED_LOCAL_COMPUTATION"],
            "remove_reason_codes": [],
            "brand_signals": [],
            "sensitive_data_status": "clear",
            "hidden_dependency_codes": [],
            "duplicate_suggestions": [],
            "review_required": False,
        }
        return result, "a" * 64, {"name": "test-model", "digest": "b" * 64}


class OllamaBoundaryTest(unittest.TestCase):
    def test_request_forwards_operation_timeout(self) -> None:
        observed = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def read(_limit):
                return b'{"models":[]}'

        class Opener:
            @staticmethod
            def open(_request, timeout):
                observed.append(timeout)
                return Response()

        with patch.object(stage3_module, "build_opener", return_value=Opener()):
            OllamaSupervisor._request("http://127.0.0.1:11434", "/api/tags")
            OllamaSupervisor._request(
                "http://127.0.0.1:11434",
                "/api/generate",
                {"model": "local-model"},
                timeout_seconds=stage3_module.OLLAMA_SUPERVISION_TIMEOUT_SECONDS,
            )
        self.assertEqual(
            observed,
            [
                stage3_module.OLLAMA_METADATA_TIMEOUT_SECONDS,
                stage3_module.OLLAMA_SUPERVISION_TIMEOUT_SECONDS,
            ],
        )

    def test_supervision_timeout_remains_ollama_unavailable(self) -> None:
        with patch.object(stage3_module, "build_opener") as build:
            build.return_value.open.side_effect = TimeoutError("timed out")
            with self.assertRaisesRegex(Stage3Error, "ollama_unavailable"):
                OllamaSupervisor._request(
                    "http://127.0.0.1:11434",
                    "/api/generate",
                    {"model": "local-model"},
                    timeout_seconds=stage3_module.OLLAMA_SUPERVISION_TIMEOUT_SECONDS,
                )
        self.assertEqual(
            build.return_value.open.call_args.kwargs,
            {"timeout": stage3_module.OLLAMA_SUPERVISION_TIMEOUT_SECONDS},
        )

    def test_metadata_and_supervision_use_operation_timeouts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = CapsuleWarehouseStore(Path(temporary) / "warehouse.sqlite3")
            supervisor = OllamaSupervisor(store)
            base = "http://127.0.0.1:11434"
            with patch.object(
                supervisor,
                "_request",
                return_value=({"models": []}, b'{"models":[]}'),
            ) as request:
                self.assertEqual(supervisor.list_models(base), [])
            request.assert_called_once_with(
                base,
                "/api/tags",
                timeout_seconds=stage3_module.OLLAMA_METADATA_TIMEOUT_SECONDS,
            )

            selected = {
                "base_url": base,
                "name": "local-model",
                "digest": "d" * 64,
                "selected_at": "2026-07-29T00:00:00.000Z",
            }
            response = {
                "schema_version": "capsule_supervision.v1",
                "verdict": "approve",
                "capability_kind": "computation",
                "semantic_summary": "Compute a bounded value.",
                "keep_reason_codes": ["LOCAL"],
                "remove_reason_codes": [],
                "brand_signals": [],
                "sensitive_data_status": "clear",
                "hidden_dependency_codes": [],
                "duplicate_suggestions": [],
                "review_required": False,
            }
            with (
                patch.object(supervisor, "selected_model", return_value=selected),
                patch.object(
                    supervisor,
                    "list_models",
                    return_value=[{"name": selected["name"], "digest": selected["digest"]}],
                ),
                patch.object(
                    supervisor,
                    "_request",
                    return_value=(
                        {"response": json.dumps(response)},
                        b'{"response":"fixture"}',
                    ),
                ) as request,
            ):
                result, _response_hash, _selected = supervisor.supervise(
                    {"schema_version": "capsule_supervision_input.v1"},
                    "computation",
                )
            self.assertEqual(result["verdict"], "approve")
            self.assertEqual(request.call_args.args[:2], (base, "/api/generate"))
            self.assertEqual(
                request.call_args.kwargs,
                {
                    "timeout_seconds": (
                        stage3_module.OLLAMA_SUPERVISION_TIMEOUT_SECONDS
                    )
                },
            )

    def test_explicit_loopback_selection_and_digest_recheck(self) -> None:
        state = {"digest": "d" * 64, "prompts": [], "malformed": False}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self._send({"models": [{"name": "local-model", "digest": state["digest"]}]})

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                state["prompts"].append(body["prompt"])
                self._send(
                    {
                        "response": "not-json"
                        if state["malformed"]
                        else json.dumps(
                            {
                                "schema_version": "capsule_supervision.v1",
                                "verdict": "approve",
                                "capability_kind": "computation",
                                "semantic_summary": "Compute a total.",
                                "keep_reason_codes": ["LOCAL"],
                                "remove_reason_codes": [],
                                "brand_signals": [],
                                "sensitive_data_status": "clear",
                                "hidden_dependency_codes": [],
                                "duplicate_suggestions": [],
                                "review_required": False,
                            }
                        )
                    }
                )

            def _send(self, value):
                encoded = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                store = CapsuleWarehouseStore(Path(temporary) / "warehouse.sqlite3")
                supervisor = OllamaSupervisor(store)
                base = f"http://127.0.0.1:{server.server_port}"
                with self.assertRaisesRegex(Stage3Error, "ollama_model_not_selected"):
                    supervisor.selected_model()
                supervisor.select_model(base, "local-model", state["digest"])
                result, response_hash, selected = supervisor.supervise(
                    {"schema_version": "capsule_supervision_input.v1", "fixture": {"value": 2}},
                    "computation",
                )
                self.assertEqual(result["verdict"], "approve")
                self.assertEqual(len(response_hash), 64)
                self.assertEqual(selected["name"], "local-model")
                self.assertNotIn("export function", state["prompts"][0])
                self.assertIn('"schema_version":"capsule_supervision.v1"', state["prompts"][0])
                self.assertIn('"capability_kind":"computation"', state["prompts"][0])
                self.assertIn('"duplicate_suggestions":[]', state["prompts"][0])
                state["digest"] = "e" * 64
                with self.assertRaisesRegex(Stage3Error, "ollama_model_digest_changed"):
                    supervisor.supervise({}, "computation")
                state["digest"] = "d" * 64
                state["malformed"] = True
                with self.assertRaisesRegex(Stage3Error, "ollama_supervision_invalid"):
                    supervisor.supervise({}, "computation")
                with self.assertRaisesRegex(Stage3Error, "ollama_loopback_required"):
                    supervisor.list_models("http://192.0.2.1:11434")
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()


@unittest.skipUnless(shutil.which("node"), "Node is required for UI source intake")
class FrozenUiReviewAdmissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.store = CapsuleWarehouseStore(
            self.root / "source-state" / "capsule_warehouse.sqlite3"
        )
        self.store.initialize()
        self.store.migrate_v1_to_v2()
        self.intake = ReweaveCapsuleIntake(self.store)
        self.stage3 = ReweaveCapsuleStage3(
            self.store,
            intake=self.intake,
            supervisor=_ApprovingSupervisor(),
        )

    def tearDown(self) -> None:
        self._temporary.cleanup()

    @staticmethod
    def _validation(prepared: PreparedReview) -> dict[str, object]:
        kind = prepared.artifact.canonical_payload["capability_kind"]
        result: dict[str, object] = {
            "schema_version": "qweb_validation.v1",
            "status": "passed",
            "normal_cases": 1,
            "boundary_cases": 1,
            "invalid_cases": 1,
            "repeated_render": kind == "presentation",
            "dispose_idempotent": kind == "interaction",
            "remount_checked": kind == "interaction",
            "acceptance_scope": (
                "real_qwebengine_interaction"
                if kind == "interaction"
                else "real_qwebengine_render"
            ),
        }
        if kind == "interaction":
            result.update(
                {
                    "emission_count": 1,
                    "emission_names": ["area_requested"],
                }
            )
        return result

    def _review_pair(self) -> tuple[list[dict[str, object]], dict[str, object]]:
        (self.source / "index.html").write_text(
            """<!doctype html><html><body><main data-capsule-root>
<input data-ref="width" type="number" min="1" max="1000" step="1">
<input data-ref="height" type="number" min="1" max="1000" step="1">
<p data-ref="error"></p><button data-action="calculate">Calculate</button>
<span data-ref="area"></span></main>
<script type="module" src="./presentation.js"></script>
<script type="module" src="./interaction.js"></script></body></html>""",
            encoding="utf-8",
        )
        (self.source / "interaction.js").write_text(
            """export function mount(root, ports) {
  const width = root.querySelector("[data-ref='width']");
  const height = root.querySelector("[data-ref='height']");
  const button = root.querySelector("[data-action='calculate']");
  const onClick = (event) => {
    event.preventDefault();
    const widthValue = Number(width.value);
    const heightValue = Number(height.value);
    if (!Number.isInteger(widthValue) || widthValue < 1 || widthValue > 1000) return;
    if (!Number.isInteger(heightValue) || heightValue < 1 || heightValue > 1000) return;
    ports.emit("area_requested", {width: widthValue, height: heightValue});
  };
  button.addEventListener("click", onClick);
  return () => { button.removeEventListener("click", onClick); };
}
""",
            encoding="utf-8",
        )
        (self.source / "presentation.js").write_text(
            """export function render(root, input) {
  if (!input || typeof input !== "object" || Object.keys(input).length !== 1) {
    return {ok: false, error: {code: "INVALID_INPUT", field: null, details: {}}};
  }
  if (!Number.isInteger(input.area) || input.area < 1 || input.area > 1000000) {
    return {ok: false, error: {code: "INVALID_AREA", field: "area", details: {}}};
  }
  const area = root.querySelector("[data-ref='area']");
  area.textContent = input.area;
}
""",
            encoding="utf-8",
        )
        root = self.intake.bind_source_root(
            self.source,
            root_kind="single_project",
        )
        project = self.intake.discover_projects(root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        run = self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM review_items WHERE run_id = ? "
                    "ORDER BY review_id",
                    (run["run_id"],),
                ).fetchall()
            ]
        self.assertEqual(len(rows), 2)
        with patch.object(
            ReweaveCapsuleStage3,
            "_runtime_validation",
            new=lambda _stage3, prepared: self._validation(prepared),
        ):
            for row in rows:
                result = self.stage3.process_review(row["review_id"])
                self.assertEqual(result["status"], "review_required")
        snapshot = self.intake.snapshot_project(project["project_id"])
        with self.store.read_connection() as connection:
            reviewed = [
                dict(
                    connection.execute(
                        "SELECT * FROM review_items WHERE review_id = ?",
                        (row["review_id"],),
                    ).fetchone()
                )
                for row in rows
            ]
        file_index = [
            {
                "path": item.path,
                "file_type": item.file_type,
                "size": item.size,
                "sha256": item.sha256,
            }
            for item in snapshot.entries
        ]
        return reviewed, {
            "project_id": project["project_id"],
            "run_id": run["run_id"],
            "file_index": file_index,
        }

    def _authorization(
        self,
        reviews: list[dict[str, object]],
        lineage: dict[str, object],
        target_revision: int,
    ) -> dict[str, object]:
        authorized_reviews = []
        declarations: dict[str, dict[str, object]] = {}
        for review in reviews:
            summary = json.loads(str(review["sanitized_candidate_json"]))
            kind = summary["capability_kind"]
            declarations[kind] = summary["page_capability_declaration"]
            source = next(
                row
                for row in lineage["file_index"]
                if row["path"] == review["source_relpath"]
            )
            validation = summary["stage3_evidence"]["validation"]
            authorized_reviews.append(
                {
                    "review_id": review["review_id"],
                    "capability_kind": kind,
                    "candidate_canonical_hash": review[
                        "candidate_canonical_hash"
                    ],
                    "source_relpath": review["source_relpath"],
                    "source_file_sha256": source["sha256"],
                    "validation_sha256": hashlib.sha256(
                        stage3_module._canonical_json_bytes(validation)
                    ).hexdigest(),
                    "page_capability_declaration_digest": (
                        summary["page_capability_declaration"][
                            "canonical_digest"
                        ]
                    ),
                }
            )
        authorized_reviews.sort(
            key=lambda item: ("interaction", "presentation").index(
                item["capability_kind"]
            )
        )
        page_contract = build_page_capability_contract_v2(
            presentation_provides=declarations["presentation"]["provides"],
            interaction_requires=declarations["interaction"]["requires"],
        )
        value: dict[str, object] = {
            "schema": FROZEN_UI_REVIEW_ADMISSION_AUTHORIZATION_VERSION,
            "scope": "isolated_rehearsal",
            "source_database_sha256": hashlib.sha256(
                self.store.path.read_bytes()
            ).hexdigest(),
            "source_project_id": lineage["project_id"],
            "source_run_id": lineage["run_id"],
            "source_file_index_digest": hashlib.sha256(
                stage3_module._canonical_json_bytes(lineage["file_index"])
            ).hexdigest(),
            "capability_key": "rectangle_area_calculation",
            "display_name": "Rectangle area",
            "page_capability_contract_digest": page_contract[
                "canonical_digest"
            ],
            "supervision_model_name": "test-model",
            "supervision_model_digest": "b" * 64,
            "target_warehouse_revision": target_revision,
            "target_catalog_digest": "c" * 64,
            "reviews": authorized_reviews,
        }
        value["authorization_digest"] = hashlib.sha256(
            stage3_module._canonical_json_bytes(value)
        ).hexdigest()
        return value

    @staticmethod
    def _target(path: Path) -> CapsuleWarehouseStore:
        store = CapsuleWarehouseStore(path)
        store.initialize()
        store.migrate_v1_to_v2()
        selected = {
            "base_url": "http://127.0.0.1:11434",
            "name": "test-model",
            "digest": "b" * 64,
            "selected_at": "2026-08-11T00:00:00.000Z",
        }
        with store.transaction() as connection:
            connection.execute(
                "INSERT INTO app_settings(setting_key,value_json,updated_at) "
                "VALUES ('capsule_supervision_model',?,?)",
                (
                    json.dumps(
                        selected,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    selected["selected_at"],
                ),
            )
        return store

    def test_ui_pair_is_atomically_admitted_and_idempotent(self) -> None:
        reviews, lineage = self._review_pair()
        target = self._target(
            self.root / "target" / "capsule_warehouse.sqlite3"
        )
        target_stage3 = ReweaveCapsuleStage3(target)
        before = target.current_revision()
        authorization = self._authorization(reviews, lineage, before)
        with patch.object(
            ReweaveCapsuleStage3,
            "_runtime_validation",
            new=lambda _stage3, prepared: self._validation(prepared),
        ):
            admitted = target_stage3.admit_frozen_ui_review_batch(
                self.store.path,
                self.source,
                expected_source_sha256=authorization[
                    "source_database_sha256"
                ],
                expected_warehouse_revision=before,
                authorization_binding=authorization,
            )
            repeated = target_stage3.admit_frozen_ui_review_batch(
                self.store.path,
                self.source,
                expected_source_sha256=authorization[
                    "source_database_sha256"
                ],
                expected_warehouse_revision=before,
                authorization_binding=authorization,
            )
        self.assertEqual(admitted["status"], "review_required")
        self.assertEqual(admitted["warehouse_revision"], before + 2)
        self.assertEqual(repeated["status"], "already_admitted")
        self.assertEqual(target.current_revision(), before + 2)
        with target.read_connection() as connection:
            stored = connection.execute(
                "SELECT sanitized_candidate_json FROM review_items "
                "ORDER BY review_id"
            ).fetchall()
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM capsule_versions"
                ).fetchone()[0],
                0,
            )
        self.assertEqual(len(stored), 2)
        receipts = [
            json.loads(row["sanitized_candidate_json"])[
                "frozen_ui_review_admission"
            ]
            for row in stored
        ]
        self.assertTrue(
            all(
                receipt["schema"]
                == FROZEN_UI_REVIEW_ADMISSION_VERSION
                and receipt["batch_authorization_digest"]
                == authorization["authorization_digest"]
                for receipt in receipts
            )
        )

    def test_ui_pair_tampering_and_existing_group_fail_without_reviews(
        self,
    ) -> None:
        reviews, lineage = self._review_pair()
        for case in ("authorization", "page_contract", "existing_group"):
            with self.subTest(case=case):
                target = self._target(
                    self.root / case / "capsule_warehouse.sqlite3"
                )
                before = target.current_revision()
                authorization = self._authorization(
                    reviews,
                    lineage,
                    before,
                )
                if case == "authorization":
                    authorization["reviews"][1][
                        "validation_sha256"
                    ] = "f" * 64
                elif case == "page_contract":
                    authorization["page_capability_contract_digest"] = (
                        "f" * 64
                    )
                else:
                    with target.transaction() as connection:
                        connection.execute(
                            "INSERT INTO capability_groups VALUES (?,?,?,?)",
                            (
                                "rectangle_area_calculation",
                                "Rectangle area",
                                "2026-08-11T00:00:00.000Z",
                                "2026-08-11T00:00:00.000Z",
                            ),
                        )
                if case != "existing_group":
                    authorization["authorization_digest"] = hashlib.sha256(
                        stage3_module._canonical_json_bytes(
                            {
                                key: value
                                for key, value in authorization.items()
                                if key != "authorization_digest"
                            }
                        )
                    ).hexdigest()
                with patch.object(
                    ReweaveCapsuleStage3,
                    "_runtime_validation",
                    new=lambda _stage3, prepared: self._validation(prepared),
                ), self.assertRaises(Stage3Error):
                    ReweaveCapsuleStage3(
                        target
                    ).admit_frozen_ui_review_batch(
                        self.store.path,
                        self.source,
                        expected_source_sha256=authorization[
                            "source_database_sha256"
                        ],
                        expected_warehouse_revision=before,
                        authorization_binding=authorization,
                    )
                with target.read_connection() as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT count(*) FROM review_items"
                        ).fetchone()[0],
                        0,
                    )

    def test_ui_batch_membership_source_and_transaction_fail_closed(
        self,
    ) -> None:
        reviews, lineage = self._review_pair()
        target = self._target(
            self.root / "fail-closed" / "capsule_warehouse.sqlite3"
        )
        before = target.current_revision()
        authorization = self._authorization(reviews, lineage, before)

        for mutate in ("missing", "duplicate"):
            invalid = json.loads(json.dumps(authorization))
            if mutate == "missing":
                invalid["reviews"].pop()
            else:
                invalid["reviews"][1]["capability_kind"] = "interaction"
            invalid["authorization_digest"] = hashlib.sha256(
                stage3_module._canonical_json_bytes(
                    {
                        key: value
                        for key, value in invalid.items()
                        if key != "authorization_digest"
                    }
                )
            ).hexdigest()
            with self.subTest(mutate=mutate), self.assertRaisesRegex(
                Stage3Error,
                "frozen_ui_review_admission_invalid",
            ):
                ReweaveCapsuleStage3(target).admit_frozen_ui_review_batch(
                    self.store.path,
                    self.source,
                    expected_source_sha256=invalid[
                        "source_database_sha256"
                    ],
                    expected_warehouse_revision=before,
                    authorization_binding=invalid,
                )

        original = target.bump_revision
        calls = 0

        def fail_second(connection):
            nonlocal calls
            calls += 1
            value = original(connection)
            if calls == 2:
                raise Stage3Error("forced_second_admission_failure")
            return value

        with patch.object(
            ReweaveCapsuleStage3,
            "_runtime_validation",
            new=lambda _stage3, prepared: self._validation(prepared),
        ), patch.object(
            target,
            "bump_revision",
            side_effect=fail_second,
        ), self.assertRaisesRegex(
            Stage3Error,
            "forced_second_admission_failure",
        ):
            ReweaveCapsuleStage3(target).admit_frozen_ui_review_batch(
                self.store.path,
                self.source,
                expected_source_sha256=authorization[
                    "source_database_sha256"
                ],
                expected_warehouse_revision=before,
                authorization_binding=authorization,
            )
        self.assertEqual(target.current_revision(), before)
        with target.read_connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM review_items"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM source_roots"
                ).fetchone()[0],
                0,
            )

        (self.source / "presentation.js").write_text(
            "export function render() { throw new Error('tampered'); }\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            Stage3Error,
            "frozen_ui_review_source_changed",
        ):
            ReweaveCapsuleStage3(target).admit_frozen_ui_review_batch(
                self.store.path,
                self.source,
                expected_source_sha256=authorization[
                    "source_database_sha256"
                ],
                expected_warehouse_revision=before,
                authorization_binding=authorization,
            )


@unittest.skipUnless(shutil.which("node"), "Node is required for Stage 3 validation")
class Stage3ComputationFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self._environment = patch.dict(
            os.environ, {"REWEAVE_STATE_DIR": str(self.root / "state")}
        )
        self._environment.start()
        self.store = CapsuleWarehouseStore(self.root / "state" / "capsule_warehouse.sqlite3")
        self.intake = ReweaveCapsuleIntake(self.store)
        self.supervisor = _ApprovingSupervisor()
        self.stage3 = ReweaveCapsuleStage3(
            self.store, intake=self.intake, supervisor=self.supervisor
        )

    def tearDown(self) -> None:
        self._environment.stop()
        self._temporary.cleanup()

    def _initialize_clean_source_git(self) -> tuple[str, str]:
        git = shutil.which("git")
        if not git:
            self.skipTest("git is unavailable")
        commands = (
            [git, "init", "--quiet"],
            [git, "config", "user.name", "Reweave Test"],
            [git, "config", "user.email", "reweave@example.invalid"],
            [git, "add", "--", "index.html", "calculate.js"],
            [git, "commit", "--quiet", "-m", "initial"],
        )
        for command in commands:
            subprocess.run(
                command,
                cwd=self.source,
                check=True,
                capture_output=True,
            )
        commit = subprocess.run(
            [git, "rev-parse", "--verify", "HEAD"],
            cwd=self.source,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return git, commit

    def test_compute_candidate_runs_in_node_vm_then_waits_for_identity(self) -> None:
        (self.source / "index.html").write_text(
            """<!doctype html><html><body><main data-capsule-root></main>
<script type="module" src="./compute.js"></script></body></html>""",
            encoding="utf-8",
        )
        (self.source / "compute.js").write_text(
            """export function compute(input) {
  if (!input || typeof input !== "object" || Object.keys(input).length !== 1) {
    return {ok: false, error: {code: "INVALID_INPUT", field: null, details: {}}};
  }
  if (!Number.isInteger(input.quantity) || input.quantity < 1 || input.quantity > 10) {
    return {ok: false, error: {code: "INVALID_QUANTITY", field: "quantity", details: {}}};
  }
  return {ok: true, value: {total: input.quantity * 2}};
}
""",
            encoding="utf-8",
        )
        source_root = self.intake.bind_source_root(
            self.source, root_kind="single_project"
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        run = self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            review = connection.execute(
                "SELECT review_id FROM review_items WHERE run_id = ? AND candidate_status = 'extracted'",
                (run["run_id"],),
            ).fetchone()

        result = self.stage3.process_review(review["review_id"])

        self.assertEqual(result["status"], "review_required", result)
        self.assertEqual(result["validation_scope"], "isolated_node_vm_computation")
        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM review_items WHERE review_id = ?", (review["review_id"],)
            ).fetchone()
            self.assertEqual(row["candidate_status"], "review_required")
            self.assertIsNotNone(row["candidate_canonical_hash"])
            self.assertEqual(connection.execute("SELECT count(*) FROM capsules").fetchone()[0], 0)

        valid_candidate_summary = row["sanitized_candidate_json"]
        synthetic_summary = json.loads(valid_candidate_summary)
        synthetic_summary["stage3_evidence"]["validation"][
            "acceptance_scope"
        ] = "synthetic_declared_interaction"
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE review_items SET sanitized_candidate_json = ? WHERE review_id = ?",
                (json.dumps(synthetic_summary), review["review_id"]),
            )
            self.store.bump_revision(connection)
        with self.assertRaisesRegex(Stage3Error, "stage3_evidence_expired"):
            self.stage3.publish_review(
                review["review_id"],
                decision="publish_general",
                capability_key="bounded_total",
                role_key="double_quantity",
                display_name="Bounded total",
            )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE review_items SET sanitized_candidate_json = ? WHERE review_id = ?",
                (valid_candidate_summary, review["review_id"]),
            )
            self.store.bump_revision(connection)

        valid_supervision = row["supervision_result_json"]
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE review_items SET supervision_result_json = ? WHERE review_id = ?",
                ('{"verdict":"approve"}', review["review_id"]),
            )
            self.store.bump_revision(connection)
        with self.assertRaisesRegex(Stage3Error, "stage3_evidence_invalid"):
            self.stage3.publish_review(
                review["review_id"],
                decision="publish_general",
                capability_key="bounded_total",
                role_key="double_quantity",
                display_name="Bounded total",
            )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE review_items SET supervision_result_json = ? WHERE review_id = ?",
                (valid_supervision, review["review_id"]),
            )
            self.store.bump_revision(connection)

        original_publication_snapshot_check = self.stage3._assert_snapshot

        def reject_before_publication_transaction(prepared):
            original_publication_snapshot_check(prepared)
            with self.store.transaction() as connection:
                connection.execute(
                    "UPDATE review_items SET candidate_status = 'rejected', "
                    "decision = 'reject', decided_at = 'concurrent' WHERE review_id = ?",
                    (review["review_id"],),
                )
                self.store.bump_revision(connection)

        with patch.object(
            self.stage3,
            "_assert_snapshot",
            side_effect=reject_before_publication_transaction,
        ), self.assertRaisesRegex(Stage3Error, "review_decision_conflict"):
            self.stage3.publish_review(
                review["review_id"],
                decision="publish_general",
                capability_key="bounded_total",
                role_key="double_quantity",
                display_name="Bounded total",
            )
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM capsules").fetchone()[0], 0)
            self.assertEqual(
                connection.execute(
                    "SELECT decision FROM review_items WHERE review_id = ?",
                    (review["review_id"],),
                ).fetchone()[0],
                "reject",
            )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE review_items SET candidate_status = 'review_required', "
                "decision = NULL, decided_at = NULL WHERE review_id = ?",
                (review["review_id"],),
            )
            self.store.bump_revision(connection)

        published = self.stage3.publish_review(
            review["review_id"],
            decision="publish_general",
            capability_key="bounded_total",
            role_key="double_quantity",
            display_name="Bounded total",
        )
        self.assertEqual(published["status"], "published")
        self.assertEqual(self.supervisor.calls, 1)
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM capsules").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM capsule_versions").fetchone()[0], 1)

        second_source = self.root / "second-source"
        shutil.copytree(self.source, second_source)
        second_root = self.intake.bind_source_root(
            second_source, root_kind="single_project"
        )
        second_project = self.intake.discover_projects(second_root["root_id"])[0]
        self.intake.confirm_project(second_project["project_id"])
        second_run = self.intake.run_intake(second_project["project_id"])
        with self.store.read_connection() as connection:
            second_review = connection.execute(
                "SELECT review_id FROM review_items WHERE run_id = ? AND candidate_status = 'extracted'",
                (second_run["run_id"],),
            ).fetchone()

        original_snapshot_check = self.stage3._assert_snapshot

        def expire_exact_target(prepared):
            original_snapshot_check(prepared)
            with self.store.transaction() as connection:
                connection.execute(
                    "UPDATE capsules SET status = 'disabled' WHERE capsule_id = ?",
                    (published["capsule_id"],),
                )
                self.store.bump_revision(connection)

        with patch.object(
            self.stage3, "_assert_snapshot", side_effect=expire_exact_target
        ), self.assertRaisesRegex(Stage3Error, "exact_duplicate_target_expired"):
            self.stage3.process_review(second_review["review_id"])
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE capsules SET status = 'active' WHERE capsule_id = ?",
                (published["capsule_id"],),
            )
            self.store.bump_revision(connection)

        duplicate = self.stage3.process_review(second_review["review_id"])
        self.assertEqual(duplicate["status"], "duplicate")
        self.assertFalse(duplicate["model_called"])
        self.assertEqual(self.supervisor.calls, 1)

        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE projects SET brand_mode = 'extend' WHERE project_id = ?",
                (second_project["project_id"],),
            )
        with self.assertRaisesRegex(
            Stage3Error, "project_brand_extend_unsupported_v1"
        ):
            self.stage3.publish_review(
                second_review["review_id"],
                decision="semantic_split",
                capability_key="bounded_total_split",
                role_key="double_quantity",
                display_name="Bounded total split",
            )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE projects SET brand_mode = 'inherit' WHERE project_id = ?",
                (second_project["project_id"],),
            )

        original_split_snapshot_check = self.stage3._assert_snapshot

        def mark_split_target_pending(prepared):
            original_split_snapshot_check(prepared)
            with self.store.transaction() as connection:
                connection.execute(
                    "UPDATE capsules SET status = 'pending_revalidation' "
                    "WHERE capsule_id = ?",
                    (published["capsule_id"],),
                )
                self.store.bump_revision(connection)

        with patch.object(
            self.stage3,
            "_assert_snapshot",
            side_effect=mark_split_target_pending,
        ), self.assertRaisesRegex(Stage3Error, "semantic_split_target_invalid"):
            self.stage3.publish_review(
                second_review["review_id"],
                decision="semantic_split",
                capability_key="bounded_total_split",
                role_key="double_quantity",
                display_name="Bounded total split",
            )
        with self.store.read_connection() as connection:
            unchanged_review = connection.execute(
                "SELECT candidate_status, decision FROM review_items WHERE review_id = ?",
                (second_review["review_id"],),
            ).fetchone()
            self.assertEqual(tuple(unchanged_review), ("duplicate", None))
            self.assertEqual(connection.execute("SELECT count(*) FROM capsules").fetchone()[0], 1)
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE capsules SET status = 'active' WHERE capsule_id = ?",
                (published["capsule_id"],),
            )
            self.store.bump_revision(connection)

        split = self.stage3.publish_review(
            second_review["review_id"],
            decision="semantic_split",
            capability_key="bounded_total_split",
            role_key="double_quantity",
            display_name="Bounded total split",
        )
        self.assertEqual(split["status"], "published")
        self.assertEqual(self.supervisor.calls, 1)
        with self.store.read_connection() as connection:
            statuses = [
                row[0]
                for row in connection.execute(
                    "SELECT status FROM capsules ORDER BY created_at, capsule_id"
                )
            ]
            split_review = connection.execute(
                "SELECT decision, retained_version_id FROM review_items WHERE review_id = ?",
                (second_review["review_id"],),
            ).fetchone()
        self.assertCountEqual(statuses, ["disabled", "active"])
        self.assertEqual(tuple(split_review), ("semantic_split", published["version_id"]))

        third_source = self.root / "third-source"
        shutil.copytree(self.source, third_source)
        third_root = self.intake.bind_source_root(third_source, root_kind="single_project")
        third_project = self.intake.discover_projects(third_root["root_id"])[0]
        self.intake.confirm_project(third_project["project_id"])
        third_run = self.intake.run_intake(third_project["project_id"])
        with self.store.read_connection() as connection:
            third_review = connection.execute(
                "SELECT review_id FROM review_items WHERE run_id = ? AND candidate_status = 'extracted'",
                (third_run["run_id"],),
            ).fetchone()
        with patch(
            "pimos_lite.reweave_capsule_stage3.SECURITY_RULES_VERSION",
            "security_rules.v2",
        ):
            revalidated = self.stage3.process_review(third_review["review_id"])
        self.assertEqual(revalidated["status"], "published")
        self.assertEqual(revalidated["version_number"], 2)
        self.assertEqual(self.supervisor.calls, 2)

    def test_computation_adapter_is_exactly_preflighted_and_replayed(self) -> None:
        (self.source / "index.html").write_text(
            "<!doctype html><html><body><main></main></body></html>",
            encoding="utf-8",
        )
        (self.source / "calculate.js").write_text(
            "export function calculate(quantity, price) {\n"
            "  return quantity * price;\n"
            "}\n",
            encoding="utf-8",
        )
        source_root = self.intake.bind_source_root(
            self.source, root_kind="single_project"
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        inspected = self.intake._inspect_computation_adapters_v1(project["project_id"])
        self.assertEqual(len(inspected["offers"]), 1, inspected)
        payload = {
            "project_id": project["project_id"],
            "offer_id": inspected["offers"][0]["offer_id"],
            "arguments": [
                {
                    "source_parameter": "quantity",
                    "input_field": "quantity",
                    "minimum": 0,
                    "maximum": 100,
                },
                {
                    "source_parameter": "price",
                    "input_field": "unit_price",
                    "minimum": 0,
                    "maximum": 1000,
                },
            ],
            "result_field": "total",
            "examples": [
                {"input": {"quantity": 4, "unit_price": 5}, "expected": 20}
            ],
        }
        mismatched = json.loads(json.dumps(payload))
        mismatched["examples"][0]["expected"] = 21
        with self.assertRaisesRegex(IntakeError, "adapter_example_mismatch"):
            self.intake._create_computation_adapter_candidate_v1(
                mismatched, validator=self.stage3.preflight_computation_adapter
            )
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM intake_runs").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM review_items").fetchone()[0], 0)

        created = self.intake._create_computation_adapter_candidate_v1(
            payload, validator=self.stage3.preflight_computation_adapter
        )
        self.assertEqual(created["adapter"]["candidate_status"], "extracted")
        with self.store.read_connection() as connection:
            review = dict(
                connection.execute(
                    "SELECT * FROM review_items WHERE review_id = ?",
                    (created["review_ids"][0],),
                ).fetchone()
            )
            project_row = connection.execute(
                "SELECT last_snapshot_hash FROM projects WHERE project_id = ?",
                (project["project_id"],),
            ).fetchone()
            self.assertIsNone(project_row["last_snapshot_hash"])

        summary = json.loads(review["sanitized_candidate_json"])
        rebuilt = self.intake.rebuild_computation_adapter_candidate(
            project["project_id"], summary
        )
        expired = json.loads(json.dumps(summary))
        expired["adapter_contract_version"] = "computation_adapter.v0"
        with self.assertRaisesRegex(IntakeError, "adapter_contract_version_expired"):
            self.intake.rebuild_computation_adapter_candidate(
                project["project_id"], expired
            )
        with self.assertRaisesRegex(Stage3Error, "adapter_example_mismatch"):
            self.stage3.preflight_computation_adapter(
                rebuilt,
                [{"input": {"quantity": 4, "unit_price": 5}, "expected": 21}],
                "total",
            )
        changed = json.loads(json.dumps(rebuilt))
        for module in changed["javascript_modules"]:
            if module["path"] == "__reweave_adapter__/compute.js":
                module["source"] = module["source"].replace(
                    "export function compute", "\nexport function compute", 1
                )
        with self.assertRaisesRegex(Stage3Error, "adapter_security_rejected"):
            self.stage3.preflight_computation_adapter(
                changed,
                [{"input": {"quantity": 4, "unit_price": 5}, "expected": 20}],
                "total",
            )

        with self.assertRaisesRegex(Stage3Error, "adapter_contract_version_expired"):
            self.stage3.process_review(review["review_id"])
        with self.assertRaisesRegex(Stage3Error, "adapter_contract_version_expired"):
            self.stage3.publish_review(
                review["review_id"],
                decision="publish_general",
                capability_key="quote_calculation",
                role_key="total_price",
                variant_key="default",
                display_name="Quote calculation",
            )
        with self.store.read_connection() as connection:
            unchanged = connection.execute(
                "SELECT candidate_status, decision, candidate_canonical_hash "
                "FROM review_items WHERE review_id = ?",
                (review["review_id"],),
            ).fetchone()
            formal_count = connection.execute(
                "SELECT COUNT(*) FROM capsule_versions"
            ).fetchone()[0]
        self.assertEqual(tuple(unchanged), ("extracted", None, None))
        self.assertEqual(formal_count, 0)

    def test_computation_adapter_git_evidence_and_replay_are_bound(self) -> None:
        successful_status = subprocess.CompletedProcess(
            args=["git", "status"], returncode=0, stdout=b"", stderr=b"warning\n"
        )
        successful_head = subprocess.CompletedProcess(
            args=["git", "rev-parse"],
            returncode=0,
            stdout=(b"a" * 40) + b"\n",
            stderr=b"warning\n",
        )
        with patch(
            "pimos_lite.reweave_capsule_intake.subprocess.run",
            side_effect=[successful_status, successful_head],
        ):
            warned = self.intake._adapter_git_evidence(self.source)
        self.assertEqual(
            warned,
            {
                "state": "clean",
                "commit": "a" * 40,
                "status_sha256": hashlib.sha256(b"").hexdigest(),
            },
        )

        (self.source / "index.html").write_text(
            "<!doctype html><html><body><main></main></body></html>",
            encoding="utf-8",
        )
        (self.source / "calculate.js").write_text(
            "export function calculate(quantity, price) { return quantity * price; }\n",
            encoding="utf-8",
        )
        git, commit = self._initialize_clean_source_git()
        source_root = self.intake.bind_source_root(
            self.source, root_kind="single_project"
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        inspected = self.intake._inspect_computation_adapters_v1(project["project_id"])
        self.assertEqual(inspected["git_state"], "clean")
        self.assertEqual(inspected["git_commit"], commit)
        offer = inspected["offers"][0]
        payload = {
            "project_id": project["project_id"],
            "offer_id": offer["offer_id"],
            "arguments": [
                {
                    "source_parameter": "quantity",
                    "input_field": "quantity",
                    "minimum": 0,
                    "maximum": 100,
                },
                {
                    "source_parameter": "price",
                    "input_field": "unit_price",
                    "minimum": 0,
                    "maximum": 1000,
                },
            ],
            "result_field": "total",
            "examples": [
                {"input": {"quantity": 4, "unit_price": 5}, "expected": 20}
            ],
        }
        created = self.intake._create_computation_adapter_candidate_v1(
            payload, validator=self.stage3.preflight_computation_adapter
        )
        with self.store.read_connection() as connection:
            summary = json.loads(
                connection.execute(
                    "SELECT sanitized_candidate_json FROM review_items WHERE review_id = ?",
                    (created["review_ids"][0],),
                ).fetchone()[0]
            )
        source_evidence = summary["adapter_evidence"]["source"]
        self.assertEqual(source_evidence["git_state"], "clean")
        self.assertEqual(source_evidence["git_commit"], commit)
        original_snapshot = self.intake.snapshot_project(project["project_id"])
        self.intake.rebuild_computation_adapter_candidate(
            project["project_id"], summary, snapshot=original_snapshot
        )

        dirty_probe = self.source / "notes.txt"
        dirty_probe.write_text("not part of the supported source snapshot\n", encoding="utf-8")
        self.assertEqual(
            self.intake.snapshot_project(project["project_id"]).digest,
            original_snapshot.digest,
        )
        with self.assertRaisesRegex(IntakeError, "candidate_boundary_changed"):
            self.intake.rebuild_computation_adapter_candidate(
                project["project_id"], summary
            )
        dirty_probe.unlink()

        subprocess.run(
            [git, "commit", "--quiet", "--allow-empty", "-m", "identity change"],
            cwd=self.source,
            check=True,
            capture_output=True,
        )
        self.assertEqual(
            self.intake.snapshot_project(project["project_id"]).digest,
            original_snapshot.digest,
        )
        with self.assertRaisesRegex(Stage3Error, "adapter_contract_version_expired"):
            self.stage3.process_review(created["review_ids"][0])

    def test_brand_scope_revalidation_replaces_the_pending_current_version(self) -> None:
        (self.source / "index.html").write_text(
            """<!doctype html><html><body><main data-capsule-root></main>
<script type="module" src="./compute.js"></script></body></html>""",
            encoding="utf-8",
        )
        (self.source / "compute.js").write_text(
            """export function compute(input) {
  if (!input || typeof input !== "object" || Object.keys(input).length !== 1) {
    return {ok: false, error: {code: "INVALID_INPUT", field: null, details: {}}};
  }
  if (!Number.isInteger(input.quantity) || input.quantity < 1 || input.quantity > 10) {
    return {ok: false, error: {code: "INVALID_QUANTITY", field: "quantity", details: {}}};
  }
  return {ok: true, value: {total: input.quantity * 2}};
}
""",
            encoding="utf-8",
        )
        source_root = self.intake.bind_source_root(
            self.source,
            root_kind="single_project",
            brand_profile={"names": ["HP"]},
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        first = self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            review = connection.execute(
                "SELECT review_id, sanitized_candidate_json FROM review_items "
                "WHERE run_id = ? AND candidate_status = 'extracted'",
                (first["run_id"],),
            ).fetchone()
        candidate = json.loads(review["sanitized_candidate_json"])
        candidate["usage_scope"] = {
            "kind": "brand_limited",
            "brand_profile_id": source_root["brand_profile_id"],
            "brand_profile_digest": source_root["brand_profile_digest"],
        }
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE review_items SET sanitized_candidate_json = ? WHERE review_id = ?",
                (json.dumps(candidate), review["review_id"]),
            )
        initial_review = self.stage3.process_review(review["review_id"])
        self.assertEqual(initial_review["status"], "review_required", initial_review)
        published = self.stage3.publish_review(
            review["review_id"],
            decision="publish_brand_limited",
            capability_key="branded_total",
            role_key="double_quantity",
            display_name="Branded total",
        )

        self.intake.set_project_brand(
            project["project_id"], mode="replace", brand_profile={"names": ["IBM"]}
        )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE capsules SET status = 'pending_revalidation' WHERE capsule_id = ?",
                (published["capsule_id"],),
            )
            connection.execute(
                "INSERT INTO capsule_status_events VALUES "
                "('evt_brand_scope_change', ?, 'revalidation_required', 'active', "
                "'pending_revalidation', ?, 'brand_profile_changed', "
                "'2026-07-16T00:00:00Z')",
                (published["capsule_id"], published["version_id"]),
            )
            self.store.bump_revision(connection)
        second = self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            replacement_review = connection.execute(
                "SELECT review_id FROM review_items WHERE run_id = ? "
                "AND candidate_status = 'extracted'",
                (second["run_id"],),
            ).fetchone()
        reviewed = self.stage3.process_review(replacement_review["review_id"])
        self.assertEqual(reviewed["status"], "review_required", reviewed)
        with self.store.read_connection() as connection:
            comparison = json.loads(
                connection.execute(
                    "SELECT equivalence_comparison_json FROM review_items WHERE review_id = ?",
                    (replacement_review["review_id"],),
                ).fetchone()[0]
            )
        target = next(
            row
            for row in comparison["candidates"]
            if row["capsule_id"] == published["capsule_id"]
        )
        self.assertFalse(target["contract_match"])
        self.assertTrue(target["scope_revalidation_match"])

        original_snapshot_check = self.stage3._assert_snapshot

        def activate_target_before_publish(prepared):
            original_snapshot_check(prepared)
            with self.store.transaction() as connection:
                connection.execute(
                    "UPDATE capsules SET status = 'active' WHERE capsule_id = ?",
                    (published["capsule_id"],),
                )

        with patch.object(
            self.stage3,
            "_assert_snapshot",
            side_effect=activate_target_before_publish,
        ), self.assertRaisesRegex(Stage3Error, "replace_current_target_expired"):
            self.stage3.publish_review(
                replacement_review["review_id"],
                decision="replace_current",
                target_capsule_id=published["capsule_id"],
            )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE capsules SET status = 'pending_revalidation' WHERE capsule_id = ?",
                (published["capsule_id"],),
            )

        replacement = self.stage3.publish_review(
            replacement_review["review_id"],
            decision="replace_current",
            target_capsule_id=published["capsule_id"],
        )
        self.assertEqual(replacement["capsule_id"], published["capsule_id"])
        self.assertEqual(replacement["version_number"], 2)
        with self.store.read_connection() as connection:
            current = connection.execute(
                "SELECT c.status, c.current_version_id, cv.usage_scope_json "
                "FROM capsules c JOIN capsule_versions cv "
                "ON cv.version_id = c.current_version_id WHERE c.capsule_id = ?",
                (published["capsule_id"],),
            ).fetchone()
        self.assertEqual(current["status"], "active")
        self.assertEqual(current["current_version_id"], replacement["version_id"])
        self.assertEqual(json.loads(current["usage_scope_json"]), {"kind": "general"})

    def test_human_merge_rechecks_active_current_target_inside_transaction(self) -> None:
        html_source = """<!doctype html><html><body><main data-capsule-root></main>
<script type="module" src="./compute.js"></script></body></html>"""
        javascript = """export function compute(input) {
  if (!input || typeof input !== "object" || Object.keys(input).length !== 1) {
    return {ok: false, error: {code: "INVALID_INPUT", field: null, details: {}}};
  }
  if (!Number.isInteger(input.quantity) || input.quantity < 1 || input.quantity > 10) {
    return {ok: false, error: {code: "INVALID_QUANTITY", field: "quantity", details: {}}};
  }
  return {ok: true, value: {total: input.quantity * 2}};
}
"""

        def intake_review(directory: Path, suffix: str = "") -> str:
            directory.mkdir(exist_ok=True)
            (directory / "index.html").write_text(html_source, encoding="utf-8")
            (directory / "compute.js").write_text(
                javascript + suffix, encoding="utf-8"
            )
            root = self.intake.bind_source_root(directory, root_kind="single_project")
            project = self.intake.discover_projects(root["root_id"])[0]
            self.intake.confirm_project(project["project_id"])
            run = self.intake.run_intake(project["project_id"])
            with self.store.read_connection() as connection:
                row = connection.execute(
                    "SELECT review_id FROM review_items WHERE run_id = ? "
                    "AND candidate_status = 'extracted'",
                    (run["run_id"],),
                ).fetchone()
            return str(row["review_id"])

        first_review = intake_review(self.source)
        self.assertEqual(self.stage3.process_review(first_review)["status"], "review_required")
        published = self.stage3.publish_review(
            first_review,
            decision="publish_general",
            capability_key="merge_target",
            role_key="total",
            display_name="Merge target",
        )
        second_review = intake_review(
            self.root / "alternate-source", "// alternate source form\n"
        )
        candidate = self.stage3.process_review(second_review)
        self.assertEqual(candidate["status"], "review_required")

        original_snapshot_check = self.stage3._assert_snapshot

        def expire_merge_target(prepared):
            original_snapshot_check(prepared)
            with self.store.transaction() as connection:
                connection.execute(
                    "UPDATE capsules SET status = 'disabled' WHERE capsule_id = ?",
                    (published["capsule_id"],),
                )
                self.store.bump_revision(connection)

        with patch.object(
            self.stage3, "_assert_snapshot", side_effect=expire_merge_target
        ), self.assertRaisesRegex(Stage3Error, "retained_version_evidence_expired"):
            self.stage3.publish_review(
                second_review,
                decision="merge_existing",
                retained_version_id=published["version_id"],
            )
        with self.store.read_connection() as connection:
            review = connection.execute(
                "SELECT candidate_status, retained_version_id FROM review_items "
                "WHERE review_id = ?",
                (second_review,),
            ).fetchone()
            source_count = connection.execute(
                "SELECT count(*) FROM capsule_sources WHERE version_id = ?",
                (published["version_id"],),
            ).fetchone()[0]
        self.assertEqual(review["candidate_status"], "review_required")
        self.assertIsNone(review["retained_version_id"])
        self.assertEqual(source_count, 1)

    def test_stage3_sensitive_html_decision_reopens_a_new_run(self) -> None:
        (self.source / "index.html").write_text(
            """<!doctype html><html><body><section data-capsule-root>
<input data-ref="quantity" name="account_number" type="number" min="1" max="10" value="2">
<button data-action="send" type="button">Send</button></section>
<script type="module" src="./interaction.js"></script></body></html>""",
            encoding="utf-8",
        )
        (self.source / "interaction.js").write_text(
            """export function mount(root, ports) {
  const quantity = root.querySelector("[data-ref='quantity']");
  const button = root.querySelector("[data-action='send']");
  const onClick = (event) => {
    event.preventDefault();
    const value = Number(quantity.value);
    if (!Number.isInteger(value) || value < 1 || value > 10) return;
    ports.emit("sent", {quantity: value});
  };
  button.addEventListener("click", onClick);
  return () => { button.removeEventListener("click", onClick); };
}
""",
            encoding="utf-8",
        )
        source_root = self.intake.bind_source_root(self.source, root_kind="single_project")
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        first = self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            review = connection.execute(
                "SELECT review_id FROM review_items WHERE run_id = ? AND candidate_status = 'extracted'",
                (first["run_id"],),
            ).fetchone()

        waiting = self.stage3.process_review(review["review_id"])

        self.assertEqual(waiting["status"], "waiting_user")
        self.assertEqual(self.supervisor.calls, 0)
        with self.store.read_connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM intake_runs WHERE run_id = ?", (first["run_id"],)
                ).fetchone()[0],
                "completed",
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT last_snapshot_hash FROM projects WHERE project_id = ?",
                    (project["project_id"],),
                ).fetchone()[0]
            )
        self.intake.record_review_decisions(
            review["review_id"], sensitivity_decision="confirm_fictional_fixture"
        )
        second = self.intake.run_intake(project["project_id"])
        self.assertNotEqual(second["status"], "no_change")

    def test_encoded_and_composed_sensitive_strings_never_reach_formal_storage(self) -> None:
        (self.source / "index.html").write_text(
            """<!doctype html><html><body><main data-capsule-root>
alice&#64;example.com</main><script type="module" src="./compute.js"></script>
</body></html>""",
            encoding="utf-8",
        )
        (self.source / "compute.js").write_text(
            """export function compute(input) {
  const contact = "bob" + "@" + "example.com";
  if (!Number.isInteger(input.quantity) || input.quantity < 1 || input.quantity > 10) {
    return {ok: false, error: {code: "INVALID_QUANTITY", field: "quantity", details: {}}};
  }
  return {ok: true, value: {total: input.quantity, contact}};
}
""",
            encoding="utf-8",
        )
        source_root = self.intake.bind_source_root(
            self.source, root_kind="single_project"
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        first = self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            waiting = connection.execute(
                "SELECT * FROM review_items WHERE run_id = ? AND candidate_status = 'waiting_user'",
                (first["run_id"],),
            ).fetchone()
        self.assertIsNotNone(waiting)
        warehouse_bytes = self.store.path.read_bytes()
        self.assertNotIn(b"alice@example.com", warehouse_bytes)
        self.assertNotIn(b"alice&#64;example.com", warehouse_bytes)
        self.assertNotIn(b"bob@example.com", warehouse_bytes)

        self.intake.record_review_decisions(
            waiting["review_id"], sensitivity_decision="confirm_fictional_fixture"
        )
        second = self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            extracted = connection.execute(
                "SELECT review_id FROM review_items WHERE run_id = ? AND candidate_status = 'extracted'",
                (second["run_id"],),
            ).fetchone()
        result = self.stage3.process_review(extracted["review_id"])
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error_code"], "composed_sensitive_string_unsupported")
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM capsules").fetchone()[0], 0)

    def test_composed_brand_string_cannot_be_published_as_general(self) -> None:
        (self.source / "index.html").write_text(
            """<!doctype html><html><body><main data-capsule-root></main>
<script type="module" src="./compute.js"></script></body></html>""",
            encoding="utf-8",
        )
        (self.source / "compute.js").write_text(
            """export function compute(input) {
  const label = "H" + "P";
  if (!Number.isInteger(input.quantity) || input.quantity < 1 || input.quantity > 10) {
    return {ok: false, error: {code: "INVALID_QUANTITY", field: "quantity", details: {}}};
  }
  return {ok: true, value: {total: input.quantity, label}};
}
""",
            encoding="utf-8",
        )
        source_root = self.intake.bind_source_root(
            self.source,
            root_kind="single_project",
            brand_profile={"names": ["HP"]},
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        first = self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            waiting = connection.execute(
                "SELECT review_id FROM review_items WHERE run_id = ? AND candidate_status = 'waiting_user'",
                (first["run_id"],),
            ).fetchone()
        self.intake.record_review_decisions(
            waiting["review_id"], brand_decision="remove_brand"
        )
        second = self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            review = connection.execute(
                "SELECT review_id FROM review_items WHERE run_id = ? AND candidate_status = 'extracted'",
                (second["run_id"],),
            ).fetchone()

        result = self.stage3.process_review(review["review_id"])

        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error_code"], "composed_brand_string_unsupported")

    def test_image_pixels_require_a_source_hash_bound_human_decision(self) -> None:
        image_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
        )
        (self.source / "pixel.png").write_bytes(image_bytes)
        (self.source / "index.html").write_text(
            """<!doctype html><html><body><section data-capsule-root>
<span data-ref="title"></span><img src="./pixel.png" alt="sample"></section>
<script type="module" src="./presentation.js"></script></body></html>""",
            encoding="utf-8",
        )
        (self.source / "presentation.js").write_text(
            """export function render(root, input) {
  if (typeof input.title !== "string" || input.title.length > 40) {
    return {ok: false, error: {code: "INVALID_TITLE", field: "title", details: {}}};
  }
  const title = root.querySelector("[data-ref='title']");
  title.textContent = input.title;
}
""",
            encoding="utf-8",
        )
        source_root = self.intake.bind_source_root(
            self.source, root_kind="single_project"
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        first = self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            review = connection.execute(
                "SELECT review_id, source_relpath, source_hash FROM review_items "
                "WHERE run_id = ? AND candidate_status = 'extracted'",
                (first["run_id"],),
            ).fetchone()

        waiting = self.stage3.process_review(review["review_id"])

        self.assertEqual(waiting["status"], "waiting_user", waiting)
        self.assertEqual(
            waiting["error_code"], "asset_content_confirmation_required_stage3"
        )
        self.assertEqual(self.supervisor.calls, 0)
        self.intake.record_review_decisions(
            review["review_id"],
            asset_decision="confirm_assets_contain_no_real_records",
        )
        self.assertEqual(
            self.intake._bound_decisions(
                project["project_id"], review["source_relpath"], review["source_hash"]
            )["asset"],
            "confirm_assets_contain_no_real_records",
        )
        second = self.intake.run_intake(project["project_id"])
        self.assertEqual(second["counts"]["extracted"], 1)

    def test_atomic_root_does_not_collect_document_external_assets(self) -> None:
        (self.source / "outside.png").write_bytes(b"not-read-by-the-atomic-capsule")
        (self.source / "index.html").write_text(
            """<!doctype html><html><body>
<main><span data-ref="title"></span></main>
<img src="./outside.png" alt="outside">
<script type="module" src="./presentation.js"></script></body></html>""",
            encoding="utf-8",
        )
        (self.source / "presentation.js").write_text(
            """export function render(root, input) {
  if (typeof input.title !== "string" || input.title.length > 40) {
    return {ok: false, error: {code: "INVALID_TITLE", field: "title", details: {}}};
  }
  const title = root.querySelector("[data-ref='title']");
  title.textContent = input.title;
}
""",
            encoding="utf-8",
        )
        source_root = self.intake.bind_source_root(
            self.source, root_kind="single_project"
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        run = self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            review = connection.execute(
                "SELECT * FROM review_items WHERE run_id = ? AND candidate_status = 'extracted'",
                (run["run_id"],),
            ).fetchone()

        prepared = self.stage3._prepare(dict(review))

        self.assertEqual(prepared.artifact.assets, ())
        self.assertNotIn("outside.png", prepared.artifact.canonical_payload["html"])
        summary = json.loads(prepared.review["sanitized_candidate_json"])
        declaration = summary["page_capability_declaration"]
        binding = summary["formal_identity_binding"]
        self.assertEqual(declaration["capability_kind"], "presentation")
        self.assertEqual(
            declaration["provides"][0]["selector"],
            "[data-ref='title']",
        )
        self.assertIn("textContent", declaration["provides"][0]["writes"])
        self.assertEqual(
            binding["canonical_payload_digest"],
            prepared.artifact.canonical_payload_digest,
        )
        self.assertEqual(
            binding["page_capability_declaration_digest"],
            declaration["canonical_digest"],
        )
        self.assertEqual(
            prepared.artifact.version_canonical_hash,
            binding["formal_identity_digest"],
        )
        self.assertNotEqual(
            prepared.artifact.version_canonical_hash,
            prepared.artifact.canonical_payload_digest,
        )
        with (
            patch.object(self.stage3, "_hash_matches", return_value=[]) as matches,
            patch.object(
                self.stage3,
                "_runtime_validation",
                return_value={
                    "schema_version": "qweb_validation.v1",
                    "status": "passed",
                    "acceptance_scope": "test_only",
                },
            ),
        ):
            outcome = self.stage3.shared_stage3_gate(prepared)
        self.assertEqual(outcome.kind, "review_required")
        matches.assert_called_once_with(binding["formal_identity_digest"])
        self.assertNotIn(
            "page_capability_declaration",
            prepared.artifact.canonical_payload,
        )


DESKTOP_PYTHON = ROOT / ".venv-reweave" / "bin" / "python"


@unittest.skipUnless(DESKTOP_PYTHON.is_file(), "Independent PySide6 desktop environment required")
class Stage3PySideFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self._environment = patch.dict(
            os.environ,
            {
                "REWEAVE_STATE_DIR": str(self.root / "state"),
                "REWEAVE_DESKTOP_PYTHON": str(DESKTOP_PYTHON),
            },
        )
        self._environment.start()
        self.store = CapsuleWarehouseStore(self.root / "state" / "capsule_warehouse.sqlite3")
        self.intake = ReweaveCapsuleIntake(self.store)
        self.stage3 = ReweaveCapsuleStage3(
            self.store, intake=self.intake, supervisor=_ApprovingSupervisor()
        )

    def tearDown(self) -> None:
        self._environment.stop()
        self._temporary.cleanup()

    def test_image_worker_reencodes_and_rejects_disguised_html(self) -> None:
        # 1x1 RGBA PNG; the worker decodes and emits fresh bytes without metadata.
        original = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
        )
        (self.source / "pixel.png").write_bytes(original)
        cleaned = _clean_assets({"pixel.png": original})
        self.assertEqual(cleaned[0].media_type, "image/png")
        self.assertEqual((cleaned[0].width, cleaned[0].height), (1, 1))
        self.assertEqual((self.source / "pixel.png").read_bytes(), original)
        (self.source / "fake.png").write_text("<html>not an image</html>", encoding="utf-8")
        with self.assertRaisesRegex(Stage3Error, "image_magic_forbidden"):
            _clean_assets({"fake.png": b"<html>not an image</html>"})
        with self.assertRaisesRegex(Stage3Error, "image_format_mismatch"):
            _clean_assets({"pixel.jpg": original})

    def test_real_qwebengine_runs_declared_event_and_dispose(self) -> None:
        (self.source / "index.html").write_text(
            """<!doctype html><html><body><main>
<input data-ref="quantity" type="number" min="1" max="10" step="1" value="2">
<button data-action="calculate" type="button">Calculate</button>
</main><script type="module" src="./interaction.js"></script></body></html>""",
            encoding="utf-8",
        )
        (self.source / "interaction.js").write_text(
            """export function mount(root, ports) {
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
            encoding="utf-8",
        )
        source_root = self.intake.bind_source_root(
            self.source, root_kind="single_project"
        )
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        run = self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            review = connection.execute(
                "SELECT review_id FROM review_items WHERE run_id = ? AND candidate_status = 'extracted'",
                (run["run_id"],),
            ).fetchone()

        result = self.stage3.process_review(review["review_id"])

        self.assertEqual(result["status"], "review_required", result)
        self.assertEqual(result["validation_scope"], "real_qwebengine_interaction")
        with self.store.read_connection() as connection:
            persisted = connection.execute(
                "SELECT sanitized_candidate_json FROM review_items WHERE review_id = ?",
                (review["review_id"],),
            ).fetchone()
        declaration = json.loads(persisted["sanitized_candidate_json"])[
            "page_capability_declaration"
        ]
        self.assertEqual(declaration["capability_kind"], "interaction")
        self.assertEqual(len(declaration["requires"]), 2)

        published = self.stage3.publish_review(
            review["review_id"],
            decision="publish_general",
            capability_key="quote_calculation",
            role_key="quote_input",
            display_name="Quote input",
        )
        with self.store.read_connection() as connection:
            review_row = connection.execute(
                "SELECT candidate_canonical_hash, sanitized_candidate_json "
                "FROM review_items WHERE review_id = ?",
                (review["review_id"],),
            ).fetchone()
            version_row = connection.execute(
                "SELECT canonical_hash, extraction_summary_json "
                "FROM capsule_versions WHERE version_id = ?",
                (published["version_id"],),
            ).fetchone()
            source_row = connection.execute(
                "SELECT candidate_canonical_hash FROM capsule_sources "
                "WHERE version_id = ? AND relationship = 'published_implementation'",
                (published["version_id"],),
            ).fetchone()
        summary = json.loads(version_row["extraction_summary_json"])
        binding = summary["formal_identity_binding"]
        identity_digest = binding["formal_identity_digest"]
        self.assertEqual(review_row["candidate_canonical_hash"], identity_digest)
        self.assertEqual(version_row["canonical_hash"], identity_digest)
        self.assertEqual(source_row["candidate_canonical_hash"], identity_digest)
        self.assertEqual(
            binding["page_capability_declaration_digest"],
            summary["page_capability_declaration"]["canonical_digest"],
        )
        self.assertNotEqual(
            binding["canonical_payload_digest"],
            identity_digest,
        )

    def test_real_qwebengine_rejects_observably_non_idempotent_dispose(self) -> None:
        payload = {
            "capability_kind": "interaction",
            "activation": {
                "entry_module": "interaction.js",
                "entrypoint": "mount",
            },
            "javascript_modules": [
                {
                    "path": "interaction.js",
                    "source": """export function mount(root, ports) {
  const button = root.querySelector("[data-action='run']");
  const onClick = (event) => { event.preventDefault(); ports.emit("ran", {}); };
  button.addEventListener("click", onClick);
  return () => {
    button.removeEventListener("click", onClick);
    button.value = button.value === "a" ? "b" : "a";
  };
}
""",
                }
            ],
            "html": '<button data-action="run" type="button">Run</button>',
            "css": "",
            "input_contract": {
                "schema": "data_contract.v1",
                "type": "object",
                "properties": {},
                "required": [],
                "additional_properties": False,
            },
            "output_contract": {
                "schema": "event_outputs.v1",
                "events": {
                    "ran": {
                        "schema": "data_contract.v1",
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additional_properties": False,
                    }
                },
            },
        }
        fixtures = {"normal": [{}]}

        with self.assertRaisesRegex(Stage3Error, "interaction_dispose_not_idempotent"):
            _validate_qweb(
                payload,
                fixtures,
                (),
                [{"selector": "[data-action='run']", "event": "click"}],
            )

    def test_real_qwebengine_rejects_root_ancestor_mutation(self) -> None:
        payload = {
            "capability_kind": "interaction",
            "activation": {"entry_module": "interaction.js", "entrypoint": "mount"},
            "javascript_modules": [
                {
                    "path": "interaction.js",
                    "source": """export function mount(root, ports) {
  root.offsetParent.hidden = true;
  return () => {};
}
""",
                }
            ],
            "html": '<span data-ref="title"></span>',
            "css": "",
            "input_contract": {
                "schema": "data_contract.v1",
                "type": "object",
                "properties": {},
                "required": [],
                "additional_properties": False,
            },
            "output_contract": {"schema": "event_outputs.v1", "events": {}},
        }

        with self.assertRaisesRegex(Stage3Error, "qweb_root_escape_detected"):
            _validate_qweb(
                payload,
                {"normal": [{}], "boundary": [], "invalid": []},
                (),
                [],
            )

    def test_real_qwebengine_runs_every_boundary_fixture(self) -> None:
        payload = {
            "capability_kind": "presentation",
            "activation": {"entry_module": "presentation.js", "entrypoint": "render"},
            "javascript_modules": [
                {
                    "path": "presentation.js",
                    "source": """export function render(root, input) {
  if (input.title.length === 1) return {boundary_failed: true};
  root.querySelector("[data-ref='title']").textContent = input.title;
}
""",
                }
            ],
            "html": '<span data-ref="title"></span>',
            "css": "",
            "input_contract": {
                "schema": "data_contract.v1",
                "type": "object",
                "properties": {
                    "title": {"type": "string", "min_length": 1, "max_length": 6}
                },
                "required": ["title"],
                "additional_properties": False,
            },
            "output_contract": {"schema": "no_output.v1"},
        }
        fixtures = {
            "normal": [{"title": "xxxxxx"}],
            "boundary": [{"title": "x"}],
            "invalid": [{"reason": "too_long", "value": {"title": "xxxxxxx"}}],
        }

        with self.assertRaisesRegex(Stage3Error, "presentation_return_forbidden"):
            _validate_qweb(payload, fixtures, (), [])

    def test_real_qwebengine_rejects_non_json_emit_before_clone(self) -> None:
        payload = {
            "capability_kind": "interaction",
            "activation": {"entry_module": "interaction.js", "entrypoint": "mount"},
            "javascript_modules": [
                {
                    "path": "interaction.js",
                    "source": """export function mount(root, ports) {
  const button = root.querySelector("[data-action='run']");
  const onClick = (event) => {
    event.preventDefault();
    ports.emit("ran", {callback: () => {}});
  };
  button.addEventListener("click", onClick);
  return () => { button.removeEventListener("click", onClick); };
}
""",
                }
            ],
            "html": '<button data-action="run" type="button">Run</button>',
            "css": "",
            "input_contract": {
                "schema": "data_contract.v1",
                "type": "object",
                "properties": {},
                "required": [],
                "additional_properties": False,
            },
            "output_contract": {
                "schema": "event_outputs.v1",
                "events": {
                    "ran": {
                        "schema": "data_contract.v1",
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additional_properties": False,
                    }
                },
            },
        }

        with self.assertRaisesRegex(Stage3Error, "qweb_output_non_json"):
            _validate_qweb(
                payload,
                {"normal": [{}], "boundary": [], "invalid": []},
                (),
                [{"selector": "[data-action='run']", "event": "click"}],
            )

    def test_real_qwebengine_checks_repeatable_presentation_render(self) -> None:
        (self.source / "index.html").write_text(
            """<!doctype html><html><body><section data-capsule-root>
<span data-ref="title"></span></section>
<script type="module" src="./presentation.js"></script></body></html>""",
            encoding="utf-8",
        )
        (self.source / "presentation.js").write_text(
            """export function render(root, input) {
  if (typeof input.title !== "string" || input.title.length > 40) {
    return {ok: false, error: {code: "INVALID_TITLE", field: "title", details: {}}};
  }
  const title = root.querySelector("[data-ref='title']");
  title.textContent = input.title;
}
""",
            encoding="utf-8",
        )
        source_root = self.intake.bind_source_root(self.source, root_kind="single_project")
        project = self.intake.discover_projects(source_root["root_id"])[0]
        self.intake.confirm_project(project["project_id"])
        run = self.intake.run_intake(project["project_id"])
        with self.store.read_connection() as connection:
            review = connection.execute(
                "SELECT review_id FROM review_items WHERE run_id = ? AND candidate_status = 'extracted'",
                (run["run_id"],),
            ).fetchone()

        result = self.stage3.process_review(review["review_id"])

        self.assertEqual(result["status"], "review_required", result)
        self.assertEqual(result["validation_scope"], "real_qwebengine_render")
        with self.store.read_connection() as connection:
            persisted = connection.execute(
                "SELECT sanitized_candidate_json FROM review_items WHERE review_id = ?",
                (review["review_id"],),
            ).fetchone()
        declaration = json.loads(persisted["sanitized_candidate_json"])[
            "page_capability_declaration"
        ]
        self.assertEqual(declaration["capability_kind"], "presentation")
        self.assertEqual(declaration["provides"][0]["selector"], "[data-ref='title']")

    def test_real_qwebengine_blocks_file_escape(self) -> None:
        package = self.root / "qweb-package"
        package.mkdir()
        (package / "index.html").write_text(
            """<!doctype html><html><body><img src="file:///tmp/alice@example.com">
<script src="app.js"></script></body></html>""",
            encoding="utf-8",
        )
        (package / "app.js").write_text(
            'globalThis.__reweave_result={schema_version:"qweb_validation.v1",status:"passed"};',
            encoding="utf-8",
        )
        environment = dict(os.environ)
        environment.update(
            {
                "QT_QPA_PLATFORM": "offscreen",
                "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu",
                "TMPDIR": str(package),
            }
        )
        completed = subprocess.run(
            [str(DESKTOP_PYTHON), str(ROOT / "pimos_lite/reweave_capsule_worker.py")],
            input=json.dumps(
                {
                    "mode": "qweb",
                    "entry": "index.html",
                    "allow_files": ["index.html", "app.js"],
                }
            ),
            capture_output=True,
            text=True,
            cwd=package,
            timeout=12,
            check=False,
            env=environment,
        )
        self.assertEqual(completed.returncode, 0)
        result = json.loads(completed.stdout)
        self.assertEqual(result["error_code"], "qweb_request_blocked")
        self.assertIn("file", {item["scheme"] for item in result["blocked_requests"]})
        self.assertEqual(result["blocked_requests"][0]["logical_path"], "<outside>")
        self.assertNotIn("alice@example.com", completed.stdout)

        payload = {
            "capability_kind": "presentation",
            "activation": {"entry_module": "presentation.js", "entrypoint": "render"},
            "javascript_modules": [
                {
                    "path": "presentation.js",
                    "source": "export function render(root, input) {}\n",
                }
            ],
            "html": '<img src="file:///etc/passwd" alt="blocked">',
            "css": "",
            "input_contract": {
                "schema": "data_contract.v1",
                "type": "object",
                "properties": {},
                "required": [],
                "additional_properties": False,
            },
            "output_contract": {"schema": "no_output.v1"},
        }
        with self.assertRaisesRegex(Stage3Error, "qweb_request_blocked") as raised:
            _validate_qweb(
                payload,
                {"normal": [{}], "boundary": [], "invalid": []},
                (),
                [],
            )
        self.assertEqual(
            {item["scheme"] for item in raised.exception.details["blocked_requests"]},
            {"file"},
        )


@unittest.skipUnless(
    _descriptor_relative_snapshot_supported(),
    "descriptor-relative snapshot primitives are unavailable",
)
@unittest.skipUnless(shutil.which("node"), "Node is required for Stage E capture")
class StageECaptureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            dir="/private/tmp" if Path("/private/tmp").is_dir() else None,
            prefix="reweave-stage-e-test.",
        )
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.store = CapsuleWarehouseStore(
            self.root / "state" / "capsule_warehouse.sqlite3"
        )
        self.store.initialize()
        self.store.migrate_v1_to_v2()
        now = "2026-07-18T00:00:00.000Z"
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO source_roots ("
                "root_id, root_kind, current_path, status, brand_profile_id, "
                "brand_profile_json, brand_profile_digest, brand_profile_version, "
                "created_at, updated_at"
                ") VALUES ('root-stage-e', 'single_project', ?, 'bound', "
                "NULL, NULL, NULL, 0, ?, ?)",
                (str(self.source), now, now),
            )
        self.source_service = JavascriptSourceService(self.store)
        self.project_id = str(
            self.source_service.ensure_owner("root-stage-e")["project_id"]
        )
        self.stage3 = ReweaveCapsuleStage3(self.store)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _formal_counts(self) -> dict[str, int]:
        tables = (
            "intake_runs",
            "review_items",
            "capability_groups",
            "capsules",
            "capsule_versions",
            "capsule_sources",
            "product_capsule_usage",
        )
        with self.store.read_connection() as connection:
            return {
                table: int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
                for table in tables
            }

    def _positive_capture(self) -> tuple[PreparedReview, object, dict[str, object]]:
        source_path = self.source / "calc.js"
        source_path.write_text(
            """const fee = 2;
export function calculate(quantity, price) {
  if (quantity > 5) return quantity * price + fee;
  return quantity * price;
}
""",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(snapshot, "calc.js", "calculate")
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "quantity",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                },
                {
                    "parameter_binding_id": parameters[1]["binding_id"],
                    "input_field": "unit_price",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                },
            ],
            "result_field": "total",
            "examples": [{"input": {"quantity": 4, "unit_price": 5}, "expected": 20}],
        }
        prepared = self.stage3.prepare_ephemeral_computation_capture_v2(
            snapshot,
            selection,
            mapping,
        )
        self.assertIsInstance(prepared, PreparedReview)
        return prepared, snapshot, mapping

    def _positive_capture_v3(
        self,
    ) -> tuple[PreparedReview, object, dict[str, object], dict[str, str]]:
        source_path = self.source / "discount.js"
        source_path.write_text(
            "export function discount(quantity) { return 105 - quantity * 5; }\n",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(
            snapshot, "discount.js", "discount"
        )
        mapping = {
            "schema": CAPTURE_MAPPING_V3,
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "quantity",
                    "kind": "integer",
                    "minimum": 1,
                    "maximum": 10,
                }
            ],
            "result_field": "unit_price",
            "passthrough_fields": ["quantity"],
            "examples": [
                {
                    "input": {"quantity": 5},
                    "expected": {"quantity": 5, "unit_price": 80},
                }
            ],
        }
        prepared = self.stage3.prepare_ephemeral_computation_capture_v3(
            snapshot,
            selection,
            mapping,
        )
        self.assertIsInstance(prepared, PreparedReview)
        return prepared, snapshot, mapping, selection

    def _positive_capture_v4(
        self,
    ) -> tuple[PreparedReview, object, dict[str, object], dict[str, str]]:
        (self.source / "priority.js").write_text(
            """export function classifyPriority(urgent, important) {
  if (urgent && important) return "do_now";
  if (!urgent && important) return "schedule";
  if (urgent && !important) return "delegate";
  return "drop";
}
""",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(
            snapshot, "priority.js", "classifyPriority"
        )
        cases = [
            (False, False, "drop"),
            (False, True, "schedule"),
            (True, False, "delegate"),
            (True, True, "do_now"),
        ]
        mapping = {
            "schema": CAPTURE_MAPPING_V4,
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "urgent",
                    "kind": "boolean",
                },
                {
                    "parameter_binding_id": parameters[1]["binding_id"],
                    "input_field": "important",
                    "kind": "boolean",
                },
            ],
            "result_field": "priority",
            "result_enum": ["delegate", "do_now", "drop", "schedule"],
            "proof_schema": "source_graph_proof.v2",
            "examples": [
                {
                    "input": {"urgent": urgent, "important": important},
                    "expected": {"priority": expected},
                }
                for urgent, important, expected in cases
            ],
        }
        prepared = self.stage3.prepare_ephemeral_computation_capture_v4(
            snapshot,
            selection,
            mapping,
        )
        self.assertIsInstance(prepared, PreparedReview)
        return prepared, snapshot, mapping, selection

    def test_capture_v2_adapter_and_digest_are_unchanged(self) -> None:
        prepared, _snapshot, _mapping = self._positive_capture()
        payload = json.loads(prepared.candidate_payload_json)
        modules = {
            item["path"]: item["source"]
            for item in payload["canonical_candidate"]["javascript_modules"]
        }
        self.assertEqual(
            hashlib.sha256(
                modules["__reweave_adapter__/compute.js"].encode("utf-8")
            ).hexdigest(),
            "9d907e046b918ef09289f59af5a311c601f7543ab3245f360bac48415c4ed3a4",
        )
        self.assertEqual(
            payload["mapping_sha256"],
            "76e2256bd761e54239338fb7877cf505ee5359324ba830903f6f6c5cd9ee9046",
        )
        self.assertEqual(
            payload["execution_bundle_sha256"],
            "195aec2d5ee6577a2c275a5413150a228ab3689d97e4975cb43e227ace7d30ad",
        )

    def test_capture_v3_restarts_publishes_and_rejects_tampered_evidence(self) -> None:
        prepared, snapshot, mapping, selection = self._positive_capture_v3()
        repeated = self.stage3.prepare_ephemeral_computation_capture_v3(
            snapshot,
            selection,
            mapping,
        )
        self.assertEqual(
            prepared.candidate_payload_json,
            repeated.candidate_payload_json,
        )
        payload = json.loads(prepared.candidate_payload_json)
        self.assertEqual(
            payload["canonical_candidate"]["output_contract"]["properties"],
            {
                "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
                "unit_price": {"type": "integer", "minimum": 55, "maximum": 100},
            },
        )
        with patch.object(
            self.stage3.supervisor,
            "supervise",
            return_value=self._approved_supervision(),
        ):
            result = self.stage3.process_ephemeral_capture(prepared)
        self.assertEqual(result["status"], "review_required")
        with self.store.read_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM capsules").fetchone()[0],
                0,
            )
            candidate = json.loads(
                connection.execute(
                    "SELECT sanitized_candidate_json FROM review_items "
                    "WHERE review_id = ?",
                    (result["review_id"],),
                ).fetchone()[0]
            )
        self.assertEqual(
            candidate["adapter_contract_version"],
            "computation_adapter.v3",
        )
        restarted = ReweaveCapsuleStage3(self.store)
        published = restarted.publish_review(
            result["review_id"],
            decision="publish_general",
            capability_key="discount",
            role_key="policy",
            display_name="Discount policy",
        )
        self.assertEqual(published["status"], "published")
        with self.store.read_connection() as connection:
            row = dict(
                connection.execute(
                    "SELECT cv.*, c.status, c.current_version_id, c.capability_kind "
                    "FROM capsule_versions cv JOIN capsules c "
                    "ON c.capsule_id = cv.capsule_id WHERE cv.version_id = ?",
                    (published["version_id"],),
                ).fetchone()
            )
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["current_version_id"], published["version_id"])
        self.assertEqual(
            json.loads(row["validation_result_json"])["status"], "passed"
        )
        self.assertTrue(restarted._eligible_exact(row))

        stale_mapping = dict(row)
        extraction = json.loads(stale_mapping["extraction_summary_json"])
        extraction["ephemeral_capture_payload"]["mapping"]["passthrough_fields"] = []
        stale_mapping["extraction_summary_json"] = json.dumps(
            extraction, sort_keys=True, separators=(",", ":")
        )
        self.assertFalse(restarted._eligible_exact(stale_mapping))

        stale_digest = dict(row)
        extraction = json.loads(stale_digest["extraction_summary_json"])
        extraction["ephemeral_capture_payload"]["mapping_sha256"] = "0" * 64
        stale_digest["extraction_summary_json"] = json.dumps(
            extraction, sort_keys=True, separators=(",", ":")
        )
        self.assertFalse(restarted._eligible_exact(stale_digest))

        stale_source = dict(row)
        modules = json.loads(stale_source["javascript_modules_json"])
        modules[0]["source"] += "\n// forged"
        stale_source["javascript_modules_json"] = json.dumps(
            modules, sort_keys=True, separators=(",", ":")
        )
        self.assertFalse(restarted._eligible_exact(stale_source))

        stale_identity = dict(row)
        stale_identity["canonical_hash"] = "0" * 64
        self.assertFalse(restarted._eligible_exact(stale_identity))

        with self.assertRaisesRegex(sqlite3.IntegrityError, "capsule_version_immutable"):
            with self.store.transaction() as connection:
                connection.execute(
                    "UPDATE capsule_versions SET extraction_summary_json = ? "
                    "WHERE version_id = ?",
                    ("{}", published["version_id"]),
                )

    def test_capture_v4_restarts_publishes_and_rejects_tampered_evidence(self) -> None:
        prepared, snapshot, mapping, selection = self._positive_capture_v4()
        repeated = self.stage3.prepare_ephemeral_computation_capture_v4(
            snapshot, selection, mapping
        )
        unordered = json.loads(json.dumps(mapping))
        unordered["result_enum"].reverse()
        reordered = self.stage3.prepare_ephemeral_computation_capture_v4(
            snapshot, selection, unordered
        )
        self.assertEqual(
            prepared.candidate_payload_json,
            repeated.candidate_payload_json,
        )
        self.assertEqual(
            prepared.candidate_payload_json,
            reordered.candidate_payload_json,
        )
        payload = json.loads(prepared.candidate_payload_json)
        self.assertEqual(payload["source_graph_proof"]["schema"], "source_graph_proof.v2")
        self.assertEqual(
            payload["canonical_candidate"]["output_contract"]["properties"],
            {
                "priority": {
                    "type": "string",
                    "min_length": 4,
                    "max_length": 8,
                    "enum": ["delegate", "do_now", "drop", "schedule"],
                }
            },
        )
        with patch.object(
            self.stage3.supervisor,
            "supervise",
            return_value=self._approved_supervision(),
        ):
            result = self.stage3.process_ephemeral_capture(prepared)
        self.assertEqual(result["status"], "review_required")
        restarted = ReweaveCapsuleStage3(self.store)
        published = restarted.publish_review(
            result["review_id"],
            decision="publish_general",
            capability_key="priority_classification",
            role_key="classify_priority",
            display_name="Priority classification",
        )
        self.assertEqual(published["status"], "published")
        with self.store.read_connection() as connection:
            row = dict(
                connection.execute(
                    "SELECT cv.*, c.status, c.current_version_id, c.capability_kind "
                    "FROM capsule_versions cv JOIN capsules c "
                    "ON c.capsule_id = cv.capsule_id WHERE cv.version_id = ?",
                    (published["version_id"],),
                ).fetchone()
            )
        self.assertTrue(restarted._eligible_exact(row))
        for label, mutate in (
            (
                "proof",
                lambda value: value["ephemeral_capture_payload"].update(
                    source_graph_proof_sha256="0" * 64
                ),
            ),
            (
                "mapping",
                lambda value: value["ephemeral_capture_payload"]["mapping"].update(
                    result_enum=["do_now"]
                ),
            ),
            (
                "examples",
                lambda value: value["ephemeral_capture_payload"]["mapping"][
                    "examples"
                ][0]["expected"].update(priority="critical"),
            ),
        ):
            changed = dict(row)
            extraction = json.loads(changed["extraction_summary_json"])
            mutate(extraction)
            changed["extraction_summary_json"] = json.dumps(
                extraction, sort_keys=True, separators=(",", ":")
            )
            with self.subTest(label=label):
                self.assertFalse(restarted._eligible_exact(changed))

        changed = dict(row)
        modules = json.loads(changed["javascript_modules_json"])
        modules[0]["source"] += "\n// forged"
        changed["javascript_modules_json"] = json.dumps(
            modules, sort_keys=True, separators=(",", ":")
        )
        self.assertFalse(restarted._eligible_exact(changed))
        changed = dict(row)
        validation = json.loads(changed["validation_result_json"])
        validation["status"] = "failed"
        changed["validation_result_json"] = json.dumps(
            validation, sort_keys=True, separators=(",", ":")
        )
        self.assertFalse(restarted._eligible_exact(changed))

    def test_capture_v4_mapping_requires_closed_enum_examples(self) -> None:
        _prepared, snapshot, mapping, selection = self._positive_capture_v4()
        normalized = _normalize_capture_mapping_v4(mapping)
        self.assertEqual(normalized[3], ["delegate", "do_now", "drop", "schedule"])
        mixed = {
            "schema": CAPTURE_MAPPING_V4,
            "arguments": [
                {
                    "parameter_binding_id": "a" * 64,
                    "input_field": "count",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                },
                {
                    "parameter_binding_id": "b" * 64,
                    "input_field": "enabled",
                    "kind": "boolean",
                },
                {
                    "parameter_binding_id": "c" * 64,
                    "input_field": "mode",
                    "kind": "enum",
                    "values": ["manual", "auto"],
                },
            ],
            "result_field": "state",
            "result_enum": ["off", "on"],
            "proof_schema": "source_graph_proof.v2",
            "examples": [
                {
                    "input": {"count": 0, "enabled": False, "mode": "auto"},
                    "expected": {"state": "off"},
                },
                {
                    "input": {"count": 10, "enabled": True, "mode": "manual"},
                    "expected": {"state": "on"},
                },
            ],
        }
        mixed_normalized = _normalize_capture_mapping_v4(mixed)
        self.assertEqual(
            [item["kind"] for item in mixed_normalized[0]],
            ["integer", "boolean", "enum"],
        )
        for label, mutate in (
            ("passthrough", lambda value: value.update(passthrough_fields=[])),
            ("duplicate", lambda value: value.update(result_enum=["low", "low"])),
            ("missing_case", lambda value: value["examples"].pop()),
            (
                "outside",
                lambda value: value["examples"][0]["expected"].update(
                    priority="urgent"
                ),
            ),
        ):
            changed = json.loads(json.dumps(mapping))
            mutate(changed)
            with self.subTest(label=label), self.assertRaisesRegex(
                Stage3Error, "adapter_mapping_invalid"
            ):
                _normalize_capture_mapping_v4(changed)
        mismatched = json.loads(json.dumps(mapping))
        mismatched["examples"][0]["expected"]["priority"] = "schedule"
        mismatched["examples"][1]["expected"]["priority"] = "drop"
        with self.assertRaisesRegex(Stage3Error, "adapter_example_mismatch"):
            self.stage3.prepare_ephemeral_computation_capture_v4(
                snapshot, selection, mismatched
            )

    def test_capture_v3_mapping_rejects_invalid_passthrough(self) -> None:
        binding = "a" * 64
        valid = {
            "schema": CAPTURE_MAPPING_V3,
            "arguments": [
                {
                    "parameter_binding_id": binding,
                    "input_field": "quantity",
                    "kind": "integer",
                    "minimum": 1,
                    "maximum": 10,
                }
            ],
            "result_field": "unit_price",
            "passthrough_fields": ["quantity"],
            "examples": [
                {
                    "input": {"quantity": 5},
                    "expected": {"quantity": 5, "unit_price": 80},
                }
            ],
        }
        invalid_values = [
            [],
            ["quantity", "quantity"],
            ["missing"],
            ["unit_price"],
        ]
        for passthrough in invalid_values:
            changed = json.loads(json.dumps(valid))
            changed["passthrough_fields"] = passthrough
            with self.subTest(passthrough=passthrough):
                with self.assertRaisesRegex(Stage3Error, "adapter_mapping_invalid"):
                    _normalize_capture_mapping_v3(changed)
        changed = json.loads(json.dumps(valid))
        changed["examples"][0]["expected"]["quantity"] = 6
        with self.assertRaisesRegex(Stage3Error, "adapter_mapping_invalid"):
            _normalize_capture_mapping_v3(changed)
        changed = json.loads(json.dumps(valid))
        changed["arguments"].append(
            {
                "parameter_binding_id": "b" * 64,
                "input_field": "enabled",
                "kind": "boolean",
            }
        )
        changed["passthrough_fields"] = ["quantity", "enabled"]
        changed["examples"][0]["input"]["enabled"] = True
        changed["examples"][0]["expected"]["enabled"] = True
        with self.assertRaisesRegex(Stage3Error, "adapter_mapping_invalid"):
            _normalize_capture_mapping_v3(changed)

    def test_capture_v3_object_return_remains_interval_unproven(self) -> None:
        (self.source / "object.js").write_text(
            "export function discount(quantity) { "
            "return { quantity, unit_price: 105 - quantity * 5 }; }\n",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(
            snapshot, "object.js", "discount"
        )
        mapping = {
            "schema": CAPTURE_MAPPING_V3,
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "quantity",
                    "kind": "integer",
                    "minimum": 1,
                    "maximum": 10,
                }
            ],
            "result_field": "unit_price",
            "passthrough_fields": ["quantity"],
            "examples": [
                {
                    "input": {"quantity": 5},
                    "expected": {"quantity": 5, "unit_price": 80},
                }
            ],
        }
        with self.assertRaisesRegex(Stage3Error, "interval_unproven"):
            self.stage3.prepare_ephemeral_computation_capture_v3(
                snapshot,
                selection,
                mapping,
            )

    def test_large_numeric_contract_bounds_are_not_sensitive_literals(self) -> None:
        (self.source / "large.js").write_text(
            "export function calculate(quantity, price) { return quantity * price; }\n",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(
            snapshot, "large.js", "calculate"
        )
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "quantity",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10_000,
                },
                {
                    "parameter_binding_id": parameters[1]["binding_id"],
                    "input_field": "unit_price",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 100_000,
                },
            ],
            "result_field": "total",
            "examples": [
                {"input": {"quantity": 4, "unit_price": 5}, "expected": 20}
            ],
        }

        prepared = self.stage3.prepare_ephemeral_computation_capture_v2(
            snapshot, selection, mapping
        )

        self.assertIsInstance(prepared, PreparedReview)
        with self.store.read_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM review_items").fetchone()[0],
                0,
            )

    def test_phone_and_card_strings_still_require_sensitive_review(self) -> None:
        phone = "13800138000"
        card = "4111111111111111"
        (self.source / "sensitive.js").write_text(
            f'''export function calculate(mode, value) {{
  if (mode === "{phone}") return value * 2;
  if (mode === "{card}") return value * 3;
  return value;
}}
''',
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(
            snapshot, "sensitive.js", "calculate"
        )
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "mode",
                    "kind": "enum",
                    "values": ["safe", phone, card],
                },
                {
                    "parameter_binding_id": parameters[1]["binding_id"],
                    "input_field": "value",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                },
            ],
            "result_field": "total",
            "examples": [{"input": {"mode": "safe", "value": 4}, "expected": 4}],
        }

        waiting = self.stage3.prepare_ephemeral_computation_capture_v2(
            snapshot, selection, mapping
        )

        self.assertEqual(waiting["status"], "waiting_user")
        self.assertGreaterEqual(waiting["safe_summary"]["ambiguous_count"], 2)
        self.assertIn("confirm_fictional_fixture", waiting["allowed_decisions"])
        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM review_items "
                "WHERE review_id = ?",
                (waiting["review_id"],),
            ).fetchone()
        stored_text = "\n".join(
            value for value in dict(row).values() if type(value) is str
        )
        self.assertNotIn(phone, stored_text)
        self.assertNotIn(card, stored_text)
        database_bytes = self.store.path.read_bytes()
        self.assertNotIn(phone.encode("utf-8"), database_bytes)
        self.assertNotIn(card.encode("utf-8"), database_bytes)

    def test_numeric_card_literal_still_requires_sensitive_review(self) -> None:
        card = "4111111111111111"
        (self.source / "numeric-sensitive.js").write_text(
            f"""export function calculate(value) {{
  if (value === {card}) return 1;
  return value;
}}
""",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(
            snapshot, "numeric-sensitive.js", "calculate"
        )
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "value",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                }
            ],
            "result_field": "total",
            "examples": [{"input": {"value": 4}, "expected": 4}],
        }

        waiting = self.stage3.prepare_ephemeral_computation_capture_v2(
            snapshot, selection, mapping
        )

        self.assertEqual(waiting["status"], "waiting_user")
        self.assertGreaterEqual(waiting["safe_summary"]["ambiguous_count"], 1)
        database_bytes = self.store.path.read_bytes()
        self.assertNotIn(card.encode("utf-8"), database_bytes)

    def test_capture_rejects_incomplete_independent_literal_evidence(self) -> None:
        phone = "13800138000"
        (self.source / "evidence.js").write_text(
            f'''export function calculate(mode, value) {{
  if (mode === "{phone}") return value * 2;
  return value;
}}
''',
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(
            snapshot, "evidence.js", "calculate"
        )
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "mode",
                    "kind": "enum",
                    "values": ["safe", phone],
                },
                {
                    "parameter_binding_id": parameters[1]["binding_id"],
                    "input_field": "value",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                },
            ],
            "result_field": "total",
            "examples": [{"input": {"mode": "safe", "value": 4}, "expected": 4}],
        }
        original = stage3_module._analyze_javascript

        def omit_literal_evidence(candidate: object, redact_strings: object) -> dict:
            result = original(candidate, redact_strings)
            if result.get("sensitivity_literals_by_path"):
                result["sensitivity_literals_by_path"][
                    stage3_module.CAPTURE_SELECTED_ENTRY
                ] = []
            return result

        with patch(
            "pimos_lite.reweave_capsule_stage3._analyze_javascript",
            side_effect=omit_literal_evidence,
        ), self.assertRaisesRegex(
            Stage3Error, "^capture_sensitivity_evidence_invalid$"
        ):
            self.stage3.prepare_ephemeral_computation_capture_v2(
                snapshot, selection, mapping
            )

    def test_enum_contract_uses_utf16_code_unit_lengths(self) -> None:
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": "0" * 64,
                    "input_field": "mode",
                    "kind": "enum",
                    "values": ["😀"],
                }
            ],
            "result_field": "total",
            "examples": [{"input": {"mode": "😀"}, "expected": 1}],
        }
        arguments, _domains, result_field, _examples, _enumerations = (
            stage3_module._normalize_capture_mapping(mapping)
        )

        input_contract, _output_contract, _error_contract = (
            stage3_module._capture_contracts(
                arguments,
                result_field,
                {"kind": "integer", "intervals": [[1, 1]]},
            )
        )

        self.assertEqual(
            input_contract["properties"]["mode"],
            {
                "type": "string",
                "min_length": 2,
                "max_length": 2,
                "enum": ["😀"],
            },
        )

    def test_enum_mapping_rejects_non_utf8_string_structurally(self) -> None:
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": "0" * 64,
                    "input_field": "mode",
                    "kind": "enum",
                    "values": ["\ud800"],
                }
            ],
            "result_field": "total",
            "examples": [{"input": {"mode": "valid"}, "expected": 1}],
        }

        with self.assertRaisesRegex(Stage3Error, "^adapter_mapping_invalid$"):
            stage3_module._normalize_capture_mapping(mapping)

    @staticmethod
    def _approved_supervision() -> tuple[dict[str, object], str, dict[str, str]]:
        return (
            {
                "schema_version": "capsule_supervision.v1",
                "verdict": "approve",
                "capability_kind": "computation",
                "semantic_summary": "Compute a bounded total.",
                "keep_reason_codes": ["DECLARED_LOCAL_COMPUTATION"],
                "remove_reason_codes": [],
                "brand_signals": [],
                "sensitive_data_status": "clear",
                "hidden_dependency_codes": [],
                "duplicate_suggestions": [],
                "review_required": False,
            },
            "a" * 64,
            {"name": "stage-f-test-model", "digest": "b" * 64},
        )

    def test_capture_offer_inspection_is_safe_and_read_only(self) -> None:
        (self.source / "offer.js").write_text(
            "export function total(quantity, price) { return quantity * price; }\n",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        before = self._formal_counts()
        result = inspect_ephemeral_computation_offers_v2(snapshot)
        self.assertEqual(result["schema"], "computation_capture_offers.v2")
        offer = next(item for item in result["offers"] if item["export_name"] == "total")
        self.assertEqual(offer["module_relpath"], "offer.js")
        self.assertEqual([item["name"] for item in offer["parameters"]], ["quantity", "price"])
        self.assertNotIn(str(self.source), json.dumps(result))
        self.assertNotIn("return quantity", json.dumps(result))
        self.assertEqual(self._formal_counts(), before)

    def test_offer_inspection_isolates_unrelated_rejected_module(self) -> None:
        (self.source / "offer.js").write_text(
            "export function total(quantity, price) { return quantity * price; }\n",
            encoding="utf-8",
        )
        (self.source / "unrelated.js").write_text(
            'import { value } from "package"; '
            "export function ignored(value) { return value; }\n",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        before = self._formal_counts()

        result = inspect_ephemeral_computation_offers_v2(snapshot)

        self.assertEqual(
            [
                (item["module_relpath"], item["export_name"])
                for item in result["offers"]
            ],
            [("offer.js", "total")],
        )
        self.assertEqual(
            result["rejection_summary"],
            [{"code": "closure_unproven", "count": 1}],
        )
        self.assertEqual(self._formal_counts(), before)

    def test_offer_inspection_rejects_impossible_rejection_count(self) -> None:
        (self.source / "offer.js").write_text(
            "export function total(quantity, price) { return quantity * price; }\n",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "ok",
                    "modules": [],
                    "rejection_summary": [
                        {"code": "closure_unproven", "count": 2}
                    ],
                }
            ),
            stderr="",
        )

        with patch(
            "pimos_lite.reweave_capsule_stage3.subprocess.run",
            return_value=completed,
        ):
            with self.assertRaisesRegex(Stage3Error, "^bundle_security_rejected$"):
                inspect_ephemeral_computation_offers_v2(snapshot)

    def test_ephemeral_capture_uses_shared_gate_and_delays_modules_until_success(self) -> None:
        prepared, _snapshot, _mapping = self._positive_capture()
        before = self._formal_counts()
        original_gate = self.stage3.shared_stage3_gate
        with (
            patch.object(
                self.stage3.supervisor,
                "supervise",
                return_value=self._approved_supervision(),
            ),
            patch.object(
                self.stage3,
                "shared_stage3_gate",
                wraps=original_gate,
            ) as shared,
            patch(
                "pimos_lite.reweave_capsule_stage3._validate_computation",
                wraps=stage3_module._validate_computation,
            ) as runtime,
        ):
            result = self.stage3.process_ephemeral_capture(prepared)
        self.assertEqual(result["status"], "review_required", result)
        shared.assert_called_once()
        runtime.assert_called_once()
        self.assertIsNotNone(runtime.call_args.kwargs.get("execution_bundle"))
        self.assertEqual(
            runtime.call_args.kwargs.get("execution_bundle_sha256"),
            json.loads(prepared.preflight_receipt_json)["execution_bundle_sha256"],
        )
        after = self._formal_counts()
        self.assertEqual(after["intake_runs"], before["intake_runs"] + 1)
        self.assertEqual(after["review_items"], before["review_items"] + 1)
        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT candidate_status, sanitized_candidate_json "
                "FROM review_items WHERE review_id = ?",
                (result["review_id"],),
            ).fetchone()
        self.assertEqual(row["candidate_status"], "review_required")
        summary = json.loads(row["sanitized_candidate_json"])
        self.assertEqual(
            summary["ephemeral_capture_payload"]["canonical_candidate"][
                "javascript_modules"
            ],
            json.loads(prepared.candidate_payload_json)["canonical_candidate"][
                "javascript_modules"
            ],
        )
        self.assertEqual(
            summary["stage3_evidence"]["validation"]["acceptance_scope"],
            "isolated_node_vm_computation",
        )

    def test_ephemeral_waiting_failure_persists_no_modules_and_requires_resubmission(self) -> None:
        prepared, _snapshot, _mapping = self._positive_capture()
        with patch.object(
            self.stage3.supervisor,
            "supervise",
            side_effect=Stage3Error("ollama_unavailable"),
        ):
            result = self.stage3.process_ephemeral_capture(prepared)
        self.assertEqual(result["status"], "waiting_model")
        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT sanitized_candidate_json FROM review_items WHERE review_id = ?",
                (result["review_id"],),
            ).fetchone()
        serialized = row["sanitized_candidate_json"]
        self.assertNotIn("javascript_modules", serialized)
        self.assertNotIn("calculate", serialized)
        self.assertIn("resubmit_ephemeral_capture.v1", serialized)
        with self.assertRaisesRegex(Stage3Error, "capture_resubmission_required"):
            self.stage3.process_review(result["review_id"])

    def test_ephemeral_review_rebuilds_after_restart_and_publishes_v2(self) -> None:
        prepared, _snapshot, _mapping = self._positive_capture()
        with patch.object(
            self.stage3.supervisor,
            "supervise",
            return_value=self._approved_supervision(),
        ):
            reviewed = self.stage3.process_ephemeral_capture(prepared)
        restarted = ReweaveCapsuleStage3(self.store)
        published = restarted.publish_review(
            reviewed["review_id"],
            decision="publish_general",
            capability_key="captured_total",
            role_key="total",
            variant_key="default",
            display_name="Captured total",
        )
        self.assertEqual(published["status"], "published")
        with self.store.read_connection() as connection:
            capsule = connection.execute(
                "SELECT status, current_version_id FROM capsules WHERE capsule_id = ?",
                (published["capsule_id"],),
            ).fetchone()
            version = connection.execute(
                "SELECT extraction_summary_json, javascript_modules_json "
                "FROM capsule_versions WHERE version_id = ?",
                (published["version_id"],),
            ).fetchone()
            eligibility_row = dict(
                connection.execute(
                    "SELECT cv.*, c.status, c.current_version_id, c.capability_kind "
                    "FROM capsule_versions cv JOIN capsules c "
                    "ON c.capsule_id = cv.capsule_id WHERE cv.version_id = ?",
                    (published["version_id"],),
                ).fetchone()
            )
        self.assertEqual(capsule["status"], "active")
        self.assertEqual(capsule["current_version_id"], published["version_id"])
        extraction = json.loads(version["extraction_summary_json"])
        self.assertEqual(extraction["adapter_contract_version"], "computation_adapter.v2")
        self.assertEqual(
            [item["path"] for item in json.loads(version["javascript_modules_json"])],
            ["__reweave_adapter__/compute.js", "__reweave_capture__/selected.js"],
        )
        self.assertTrue(
            self.stage3._stored_version_evidence_eligible(eligibility_row)
        )
        for key in (
            "selected_bundle_options_sha256",
            "execution_bundle_options_sha256",
        ):
            stale = dict(eligibility_row)
            stale_extraction = json.loads(stale["extraction_summary_json"])
            stale_extraction["ephemeral_capture_payload"]["rule_versions"][key] = (
                "0" * 64
            )
            stale["extraction_summary_json"] = json.dumps(
                stale_extraction, sort_keys=True, separators=(",", ":")
            )
            self.assertFalse(
                self.stage3._stored_version_evidence_eligible(stale), key
            )

    def _frozen_review_authorization_binding(
        self,
        prepared: PreparedReview,
        warehouse_revision: int,
    ) -> dict[str, object]:
        payload = json.loads(prepared.candidate_payload_json)
        candidate = payload["canonical_candidate"]
        return {
            "plan_digest": "1" * 64,
            "gap_id": "gap-test",
            "projection_digest": "2" * 64,
            "authorize_decision_digest": "3" * 64,
            "source_proposal_authorization_digest": "4" * 64,
            "capability_key": "captured_total",
            "adapter_contract_version": payload[
                "adapter_contract_version"
            ],
            "input_contract": candidate["input_contract"],
            "output_contract": candidate["output_contract"],
            "error_contract": candidate["error_contract"],
            "authorization_warehouse_revision": warehouse_revision,
            "authorization_catalog_digest": "5" * 64,
            "target_catalog_digest": "5" * 64,
        }

    @staticmethod
    def _select_frozen_review_model(store: CapsuleWarehouseStore) -> None:
        selected = {
            "base_url": "http://127.0.0.1:11434",
            "name": "stage-f-test-model",
            "digest": "b" * 64,
            "selected_at": "2026-08-08T00:00:00Z",
        }
        with store.transaction() as connection:
            connection.execute(
                "INSERT INTO app_settings(setting_key, value_json, updated_at) "
                "VALUES ('capsule_supervision_model', ?, ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET "
                "value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (
                    json.dumps(
                        selected,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    selected["selected_at"],
                ),
            )

    def test_frozen_review_is_revalidated_and_admitted_without_publication(self) -> None:
        prepared, _snapshot, _mapping = self._positive_capture()
        with patch.object(
            self.stage3.supervisor,
            "supervise",
            return_value=self._approved_supervision(),
        ):
            reviewed = self.stage3.process_ephemeral_capture(prepared)
        source_sha256 = hashlib.sha256(self.store.path.read_bytes()).hexdigest()
        target = CapsuleWarehouseStore(
            self.root / "target" / "capsule_warehouse.sqlite3"
        )
        target.initialize()
        target.migrate_v1_to_v2()
        target_stage3 = ReweaveCapsuleStage3(target)
        before_revision = target.current_revision()
        self._select_frozen_review_model(target)
        binding = self._frozen_review_authorization_binding(
            prepared,
            before_revision,
        )

        admitted = target_stage3.admit_frozen_review(
            self.store.path,
            self.source,
            reviewed["review_id"],
            expected_source_sha256=source_sha256,
            expected_warehouse_revision=before_revision,
            authorization_binding=binding,
        )

        self.assertEqual(admitted["status"], "review_required")
        with target.read_connection() as connection:
            row = connection.execute(
                "SELECT candidate_status, decision, sanitized_candidate_json "
                "FROM review_items WHERE review_id = ?",
                (reviewed["review_id"],),
            ).fetchone()
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM capsule_versions"
                ).fetchone()[0],
                0,
            )
        self.assertEqual((row["candidate_status"], row["decision"]), ("review_required", None))
        receipt = json.loads(row["sanitized_candidate_json"])[
            "frozen_review_admission"
        ]
        self.assertEqual(receipt["source_database_sha256"], source_sha256)
        self.assertEqual(
            receipt["schema"],
            "frozen_stage3_review_admission.v2",
        )
        self.assertEqual(
            receipt["source_proposal_authorization_digest"],
            binding["source_proposal_authorization_digest"],
        )
        self.assertEqual(
            receipt["target_warehouse_revision_before"],
            before_revision,
        )
        self.assertEqual(
            receipt["target_warehouse_revision_after"],
            admitted["warehouse_revision"],
        )
        repeated = target_stage3.admit_frozen_review(
            self.store.path,
            self.source,
            reviewed["review_id"],
            expected_source_sha256=source_sha256,
            expected_warehouse_revision=admitted["warehouse_revision"],
            authorization_binding=binding,
        )
        self.assertEqual(repeated["status"], "already_admitted")
        self.assertEqual(target.current_revision(), admitted["warehouse_revision"])

        restarted = ReweaveCapsuleStage3(target)
        self.assertEqual(
            restarted._review(reviewed["review_id"])["candidate_status"],
            "review_required",
        )
        with target.read_connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM capsule_versions"
                ).fetchone()[0],
                0,
            )

    def test_frozen_review_admission_v2_accepts_v4_without_publication(self) -> None:
        prepared, _snapshot, _mapping, _selection = self._positive_capture_v4()
        with patch.object(
            self.stage3.supervisor,
            "supervise",
            return_value=self._approved_supervision(),
        ):
            reviewed = self.stage3.process_ephemeral_capture(prepared)
        source_sha256 = hashlib.sha256(self.store.path.read_bytes()).hexdigest()
        target = CapsuleWarehouseStore(
            self.root / "target-v4" / "capsule_warehouse.sqlite3"
        )
        target.initialize()
        target.migrate_v1_to_v2()
        self._select_frozen_review_model(target)
        before_revision = target.current_revision()
        binding = self._frozen_review_authorization_binding(
            prepared,
            before_revision,
        )
        stage3 = ReweaveCapsuleStage3(target)

        admitted = stage3.admit_frozen_review(
            self.store.path,
            self.source,
            reviewed["review_id"],
            expected_source_sha256=source_sha256,
            expected_warehouse_revision=before_revision,
            authorization_binding=binding,
        )

        self.assertEqual(admitted["status"], "review_required")
        with target.read_connection() as connection:
            row = connection.execute(
                "SELECT sanitized_candidate_json FROM review_items "
                "WHERE review_id = ?",
                (reviewed["review_id"],),
            ).fetchone()
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM capsules").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM capsule_versions"
                ).fetchone()[0],
                0,
            )
        receipt = json.loads(row["sanitized_candidate_json"])[
            "frozen_review_admission"
        ]
        self.assertEqual(
            (
                receipt["schema"],
                receipt["authorized_adapter_contract_version"],
            ),
            (
                "frozen_stage3_review_admission.v2",
                "computation_adapter.v4",
            ),
        )
        repeated = stage3.admit_frozen_review(
            self.store.path,
            self.source,
            reviewed["review_id"],
            expected_source_sha256=source_sha256,
            expected_warehouse_revision=admitted["warehouse_revision"],
            authorization_binding=binding,
        )
        self.assertEqual(repeated["status"], "already_admitted")
        self.assertEqual(
            target.current_revision(),
            before_revision + 1,
        )
        changed_binding = copy.deepcopy(binding)
        changed_binding["target_catalog_digest"] = "6" * 64
        with self.assertRaisesRegex(
            Stage3Error,
            "^frozen_review_identity_conflict$",
        ):
            stage3.admit_frozen_review(
                self.store.path,
                self.source,
                reviewed["review_id"],
                expected_source_sha256=source_sha256,
                expected_warehouse_revision=admitted["warehouse_revision"],
                authorization_binding=changed_binding,
            )

    def test_frozen_review_admission_v4_rejects_proof_and_mapping_tampering(
        self,
    ) -> None:
        prepared, _snapshot, _mapping, _selection = self._positive_capture_v4()
        with patch.object(
            self.stage3.supervisor,
            "supervise",
            return_value=self._approved_supervision(),
        ):
            reviewed = self.stage3.process_ephemeral_capture(prepared)

        def changed_database(name, mutate):
            path = self.root / f"changed-v4-{name}.sqlite3"
            shutil.copy2(self.store.path, path)
            store = CapsuleWarehouseStore(path)
            with store.transaction() as connection:
                row = connection.execute(
                    "SELECT sanitized_candidate_json FROM review_items "
                    "WHERE review_id = ?",
                    (reviewed["review_id"],),
                ).fetchone()
                summary = json.loads(row["sanitized_candidate_json"])
                mutate(summary)
                connection.execute(
                    "UPDATE review_items SET sanitized_candidate_json = ? "
                    "WHERE review_id = ?",
                    (
                        json.dumps(
                            summary,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        reviewed["review_id"],
                    ),
                )
            return path

        cases = {
            "proof": lambda summary: summary[
                "ephemeral_capture_payload"
            ]["source_graph_proof"]["result_domain"]["values"].pop(),
            "result_enum": lambda summary: summary[
                "ephemeral_capture_payload"
            ]["mapping"]["result_enum"].pop(),
            "witness": lambda summary: summary[
                "ephemeral_capture_payload"
            ]["mapping"]["examples"][0]["expected"].update(
                priority="schedule"
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(tamper=name):
                changed = changed_database(name, mutate)
                target = CapsuleWarehouseStore(
                    self.root / f"target-v4-{name}" / "capsule_warehouse.sqlite3"
                )
                target.initialize()
                target.migrate_v1_to_v2()
                self._select_frozen_review_model(target)
                revision = target.current_revision()
                binding = self._frozen_review_authorization_binding(
                    prepared,
                    revision,
                )
                with self.assertRaises(Stage3Error):
                    ReweaveCapsuleStage3(target).admit_frozen_review(
                        changed,
                        self.source,
                        reviewed["review_id"],
                        expected_source_sha256=hashlib.sha256(
                            changed.read_bytes()
                        ).hexdigest(),
                        expected_warehouse_revision=revision,
                        authorization_binding=binding,
                    )
                self.assertEqual(target.current_revision(), revision)
                with target.read_connection() as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT COUNT(*) FROM review_items"
                        ).fetchone()[0],
                        0,
                    )

    def test_frozen_review_admission_rejects_changed_validation(self) -> None:
        prepared, _snapshot, _mapping = self._positive_capture()
        with patch.object(
            self.stage3.supervisor,
            "supervise",
            return_value=self._approved_supervision(),
        ):
            reviewed = self.stage3.process_ephemeral_capture(prepared)
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT sanitized_candidate_json FROM review_items WHERE review_id = ?",
                (reviewed["review_id"],),
            ).fetchone()
            summary = json.loads(row["sanitized_candidate_json"])
            summary["stage3_evidence"]["validation"]["normal_cases"] += 1
            connection.execute(
                "UPDATE review_items SET sanitized_candidate_json = ? WHERE review_id = ?",
                (
                    json.dumps(summary, sort_keys=True, separators=(",", ":")),
                    reviewed["review_id"],
                ),
            )
        source_sha256 = hashlib.sha256(self.store.path.read_bytes()).hexdigest()
        target = CapsuleWarehouseStore(
            self.root / "target-invalid" / "capsule_warehouse.sqlite3"
        )
        target.initialize()
        target.migrate_v1_to_v2()
        self._select_frozen_review_model(target)
        binding = self._frozen_review_authorization_binding(
            prepared,
            target.current_revision(),
        )
        initial_revision = target.current_revision()

        with self.assertRaisesRegex(Stage3Error, "^stage3_validation_changed$"):
            ReweaveCapsuleStage3(target).admit_frozen_review(
                self.store.path,
                self.source,
                reviewed["review_id"],
                expected_source_sha256=source_sha256,
                expected_warehouse_revision=target.current_revision(),
                authorization_binding=binding,
            )
        with target.read_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM review_items").fetchone()[0],
                0,
            )

    def test_frozen_review_admission_rejects_digest_source_and_mapping_tampering(
        self,
    ) -> None:
        prepared, _snapshot, _mapping = self._positive_capture()
        with patch.object(
            self.stage3.supervisor,
            "supervise",
            return_value=self._approved_supervision(),
        ):
            reviewed = self.stage3.process_ephemeral_capture(prepared)
        source_sha256 = hashlib.sha256(self.store.path.read_bytes()).hexdigest()

        target = CapsuleWarehouseStore(
            self.root / "target-tamper" / "capsule_warehouse.sqlite3"
        )
        target.initialize()
        target.migrate_v1_to_v2()
        target_stage3 = ReweaveCapsuleStage3(target)
        self._select_frozen_review_model(target)
        binding = self._frozen_review_authorization_binding(
            prepared,
            target.current_revision(),
        )
        with self.assertRaisesRegex(Stage3Error, "^frozen_review_source_changed$"):
            target_stage3.admit_frozen_review(
                self.store.path,
                self.source,
                reviewed["review_id"],
                expected_source_sha256="0" * 64,
                expected_warehouse_revision=target.current_revision(),
                authorization_binding=binding,
            )

        changed_source = self.root / "changed-source"
        shutil.copytree(self.source, changed_source)
        (changed_source / "calc.js").write_text(
            "export function calculate() { return 0; }\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(Stage3Error, "^frozen_review_source_changed$"):
            target_stage3.admit_frozen_review(
                self.store.path,
                changed_source,
                reviewed["review_id"],
                expected_source_sha256=source_sha256,
                expected_warehouse_revision=target.current_revision(),
                authorization_binding=binding,
            )

        changed_database = self.root / "changed.sqlite3"
        shutil.copy2(self.store.path, changed_database)
        changed_store = CapsuleWarehouseStore(changed_database)
        with changed_store.transaction() as connection:
            row = connection.execute(
                "SELECT sanitized_candidate_json FROM review_items WHERE review_id = ?",
                (reviewed["review_id"],),
            ).fetchone()
            summary = json.loads(row["sanitized_candidate_json"])
            summary["ephemeral_capture_payload"]["mapping"]["result_field"] = "changed"
            connection.execute(
                "UPDATE review_items SET sanitized_candidate_json = ? WHERE review_id = ?",
                (
                    json.dumps(summary, sort_keys=True, separators=(",", ":")),
                    reviewed["review_id"],
                ),
            )
        changed_sha256 = hashlib.sha256(changed_database.read_bytes()).hexdigest()
        with self.assertRaises(Stage3Error):
            target_stage3.admit_frozen_review(
                changed_database,
                self.source,
                reviewed["review_id"],
                expected_source_sha256=changed_sha256,
                expected_warehouse_revision=target.current_revision(),
                authorization_binding=binding,
            )
        with target.read_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM review_items").fetchone()[0],
                0,
            )

    def test_frozen_review_admission_rejects_authorization_model_and_lineage_drift(
        self,
    ) -> None:
        prepared, _snapshot, _mapping = self._positive_capture()
        with patch.object(
            self.stage3.supervisor,
            "supervise",
            return_value=self._approved_supervision(),
        ):
            reviewed = self.stage3.process_ephemeral_capture(prepared)
        source_sha256 = hashlib.sha256(self.store.path.read_bytes()).hexdigest()

        target = CapsuleWarehouseStore(
            self.root / "target-v2-drift" / "capsule_warehouse.sqlite3"
        )
        target.initialize()
        target.migrate_v1_to_v2()
        self._select_frozen_review_model(target)
        stage3 = ReweaveCapsuleStage3(target)
        initial_revision = target.current_revision()
        binding = self._frozen_review_authorization_binding(
            prepared,
            target.current_revision(),
        )
        changed_contract = json.loads(json.dumps(binding))
        changed_contract["input_contract"]["properties"]["quantity"][
            "maximum"
        ] = 9
        with self.assertRaisesRegex(
            Stage3Error,
            "^frozen_review_authorization_mismatch$",
        ):
            stage3.admit_frozen_review(
                self.store.path,
                self.source,
                reviewed["review_id"],
                expected_source_sha256=source_sha256,
                expected_warehouse_revision=target.current_revision(),
                authorization_binding=changed_contract,
            )
        self.assertEqual(target.current_revision(), initial_revision)
        with target.transaction() as connection:
            selected = {
                "base_url": "http://127.0.0.1:11434",
                "name": "different-model",
                "digest": "c" * 64,
                "selected_at": "2026-08-08T00:00:00Z",
            }
            connection.execute(
                "UPDATE app_settings SET value_json = ? "
                "WHERE setting_key = 'capsule_supervision_model'",
                (
                    json.dumps(
                        selected,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
        with self.assertRaisesRegex(
            Stage3Error,
            "^frozen_review_supervision_model_changed$",
        ):
            stage3.admit_frozen_review(
                self.store.path,
                self.source,
                reviewed["review_id"],
                expected_source_sha256=source_sha256,
                expected_warehouse_revision=target.current_revision(),
                authorization_binding=binding,
            )
        self.assertEqual(target.current_revision(), initial_revision)
        self._select_frozen_review_model(target)
        admitted = stage3.admit_frozen_review(
            self.store.path,
            self.source,
            reviewed["review_id"],
            expected_source_sha256=source_sha256,
            expected_warehouse_revision=target.current_revision(),
            authorization_binding=binding,
        )
        tamper_cases = (
            (
                "root",
                "UPDATE source_roots SET current_path = ?",
                (str(self.root / "wrong-source"),),
                "UPDATE source_roots SET current_path = ?",
                (str(self.source),),
            ),
            (
                "project",
                "UPDATE projects SET display_name = ?",
                ("changed project",),
                "UPDATE projects SET display_name = ?",
                ("JavaScript computation source",),
            ),
            (
                "file_index",
                "UPDATE project_file_index SET size_bytes = size_bytes + 1",
                (),
                "UPDATE project_file_index SET size_bytes = size_bytes - 1",
                (),
            ),
            (
                "run",
                "UPDATE intake_runs SET status = ?",
                ("failed",),
                "UPDATE intake_runs SET status = ?",
                ("completed_with_pending",),
            ),
            (
                "review",
                "UPDATE review_items SET candidate_status = ? "
                "WHERE review_id = ?",
                ("waiting_user", reviewed["review_id"]),
                "UPDATE review_items SET candidate_status = ? "
                "WHERE review_id = ?",
                ("review_required", reviewed["review_id"]),
            ),
        )
        for name, change_sql, change_args, restore_sql, restore_args in tamper_cases:
            with self.subTest(lineage=name):
                with sqlite3.connect(target.path) as connection:
                    connection.execute(change_sql, change_args)
                try:
                    error = (
                        CapsuleStoreError
                        if name == "file_index"
                        else Stage3Error
                    )
                    with self.assertRaises(error) as raised:
                        stage3.admit_frozen_review(
                            self.store.path,
                            self.source,
                            reviewed["review_id"],
                            expected_source_sha256=source_sha256,
                            expected_warehouse_revision=admitted[
                                "warehouse_revision"
                            ],
                            authorization_binding=binding,
                        )
                    if name != "file_index":
                        self.assertEqual(
                            str(raised.exception),
                            "frozen_review_identity_conflict",
                        )
                finally:
                    with sqlite3.connect(target.path) as connection:
                        connection.execute(restore_sql, restore_args)
                self.assertEqual(
                    target.current_revision(),
                    admitted["warehouse_revision"],
                )

    def test_frozen_review_admission_does_not_upgrade_v1_receipt(self) -> None:
        prepared, _snapshot, _mapping = self._positive_capture()
        with patch.object(
            self.stage3.supervisor,
            "supervise",
            return_value=self._approved_supervision(),
        ):
            reviewed = self.stage3.process_ephemeral_capture(prepared)
        source_sha256 = hashlib.sha256(self.store.path.read_bytes()).hexdigest()
        target = CapsuleWarehouseStore(
            self.root / "target-v1-receipt" / "capsule_warehouse.sqlite3"
        )
        target.initialize()
        target.migrate_v1_to_v2()
        self._select_frozen_review_model(target)
        stage3 = ReweaveCapsuleStage3(target)
        binding = self._frozen_review_authorization_binding(
            prepared,
            target.current_revision(),
        )
        admitted = stage3.admit_frozen_review(
            self.store.path,
            self.source,
            reviewed["review_id"],
            expected_source_sha256=source_sha256,
            expected_warehouse_revision=target.current_revision(),
            authorization_binding=binding,
        )
        with target.transaction() as connection:
            row = connection.execute(
                "SELECT sanitized_candidate_json FROM review_items "
                "WHERE review_id = ?",
                (reviewed["review_id"],),
            ).fetchone()
            summary = json.loads(row[0])
            summary["frozen_review_admission"] = {
                "schema": "frozen_stage3_review_admission.v1"
            }
            connection.execute(
                "UPDATE review_items SET sanitized_candidate_json = ? "
                "WHERE review_id = ?",
                (
                    json.dumps(
                        summary,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    reviewed["review_id"],
                ),
            )
        with self.assertRaisesRegex(
            Stage3Error,
            "^frozen_review_identity_conflict$",
        ):
            stage3.admit_frozen_review(
                self.store.path,
                self.source,
                reviewed["review_id"],
                expected_source_sha256=source_sha256,
                expected_warehouse_revision=admitted["warehouse_revision"],
                authorization_binding=binding,
            )

    def test_exact_duplicate_rechecks_selected_model_inside_transaction(self) -> None:
        prepared, snapshot, mapping = self._positive_capture()
        approved = self._approved_supervision()
        with patch.object(
            self.stage3.supervisor, "supervise", return_value=approved
        ):
            reviewed = self.stage3.process_ephemeral_capture(prepared)
        published = self.stage3.publish_review(
            reviewed["review_id"],
            decision="publish_general",
            capability_key="captured_duplicate",
            role_key="total",
            display_name="Captured duplicate",
        )
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO app_settings(setting_key, value_json, updated_at) VALUES "
                "('capsule_supervision_model', ?, ?)",
                (
                    json.dumps(
                        {
                            "base_url": "http://127.0.0.1:11434",
                            "name": approved[2]["name"],
                            "digest": approved[2]["digest"],
                            "selected_at": "2026-07-18T00:00:00Z",
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "2026-07-18T00:00:00Z",
                ),
            )
            self.store.bump_revision(connection)
        selection, _parameters = _stage_e_selection(
            snapshot, "calc.js", "calculate"
        )
        duplicate = self.stage3.prepare_ephemeral_computation_capture_v2(
            snapshot, selection, mapping
        )
        internal = self.stage3._prepare_ephemeral_for_stage3(duplicate)
        outcome = self.stage3.shared_stage3_gate(internal)
        self.assertEqual(outcome.kind, "exact_duplicate")
        target_fingerprint = outcome.version["target_evidence_fingerprint"]
        with self.store.read_connection() as connection:
            row = dict(
                connection.execute(
                    "SELECT cv.*, c.status, c.current_version_id, c.capability_kind "
                    "FROM capsule_versions cv JOIN capsules c "
                    "ON c.capsule_id = cv.capsule_id WHERE cv.version_id = ?",
                    (published["version_id"],),
                ).fetchone()
            )
        changed = dict(row)
        extraction = json.loads(changed["extraction_summary_json"])
        extraction["ephemeral_capture_payload"]["rule_versions"][
            "typescript_version"
        ] = "forged.v999"
        changed["extraction_summary_json"] = json.dumps(
            extraction, sort_keys=True, separators=(",", ":")
        )
        self.assertNotEqual(
            self.stage3._exact_evidence_fingerprint(changed), target_fingerprint
        )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE app_settings SET value_json = ?, updated_at = ? "
                "WHERE setting_key = 'capsule_supervision_model'",
                (
                    json.dumps(
                        {
                            "base_url": "http://127.0.0.1:11434",
                            "name": "changed-model",
                            "digest": "c" * 64,
                            "selected_at": "2026-07-18T00:00:01Z",
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "2026-07-18T00:00:01Z",
                ),
            )
            self.store.bump_revision(connection)
        with self.store.read_connection() as connection:
            before_sources = connection.execute(
                "SELECT count(*) FROM capsule_sources"
            ).fetchone()[0]
        with self.assertRaisesRegex(Stage3Error, "exact_duplicate_target_expired"):
            self.stage3._persist_ephemeral_duplicate(
                outcome.prepared, outcome.version
            )
        with self.store.read_connection() as connection:
            after_sources = connection.execute(
                "SELECT count(*) FROM capsule_sources"
            ).fetchone()[0]
            duplicate_rows = connection.execute(
                "SELECT count(*) FROM review_items WHERE candidate_status = 'duplicate'"
            ).fetchone()[0]
        self.assertEqual(after_sources, before_sources)
        self.assertEqual(duplicate_rows, 0)

    def test_v2_duplicate_semantic_split_reuses_eligible_version_without_storing_modules(self) -> None:
        prepared, snapshot, mapping = self._positive_capture()
        approved = self._approved_supervision()
        with patch.object(
            self.stage3.supervisor, "supervise", return_value=approved
        ):
            reviewed = self.stage3.process_ephemeral_capture(prepared)
        original = self.stage3.publish_review(
            reviewed["review_id"],
            decision="publish_general",
            capability_key="captured_original",
            role_key="total",
            display_name="Captured original",
        )
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO app_settings(setting_key, value_json, updated_at) VALUES "
                "('capsule_supervision_model', ?, ?)",
                (
                    json.dumps(
                        {
                            "base_url": "http://127.0.0.1:11434",
                            "name": approved[2]["name"],
                            "digest": approved[2]["digest"],
                            "selected_at": "2026-07-18T00:00:00Z",
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "2026-07-18T00:00:00Z",
                ),
            )
            self.store.bump_revision(connection)
        def cloned_source(name: str) -> tuple[str, object, dict[str, str]]:
            path = self.root / name
            path.mkdir()
            shutil.copy2(self.source / "calc.js", path / "calc.js")
            root_id = f"root-{name}"
            now = "2026-07-18T00:00:00.000Z"
            with self.store.transaction() as connection:
                connection.execute(
                    "INSERT INTO source_roots ("
                    "root_id, root_kind, current_path, status, brand_profile_id, "
                    "brand_profile_json, brand_profile_digest, brand_profile_version, "
                    "created_at, updated_at) VALUES (?, 'single_project', ?, 'bound', "
                    "NULL, NULL, NULL, 0, ?, ?)",
                    (root_id, str(path), now, now),
                )
                self.store.bump_revision(connection)
            project_id = str(
                self.source_service.ensure_owner(root_id)["project_id"]
            )
            clone_snapshot = self.source_service.scan(project_id)
            clone_selection, _clone_parameters = _stage_e_selection(
                clone_snapshot, "calc.js", "calculate"
            )
            return root_id, clone_snapshot, clone_selection

        _second_root, second_snapshot, selection = cloned_source("second-source")
        repeated = self.stage3.prepare_ephemeral_computation_capture_v2(
            second_snapshot, selection, mapping
        )
        with patch.object(
            self.stage3.supervisor,
            "supervise",
            side_effect=AssertionError("exact duplicate must skip supervision"),
        ):
            duplicate = self.stage3.process_ephemeral_capture(repeated)
        self.assertEqual(duplicate["status"], "duplicate")
        with self.store.read_connection() as connection:
            duplicate_row = dict(
                connection.execute(
                    "SELECT * FROM review_items WHERE review_id = ?",
                    (duplicate["review_id"],),
                ).fetchone()
            )
        self.assertEqual(duplicate_row["retained_version_id"], original["version_id"])
        self.assertEqual(
            duplicate_row["candidate_canonical_hash"], original["canonical_hash"]
        )
        self.assertNotIn(
            "javascript_modules", duplicate_row["sanitized_candidate_json"]
        )
        split = self.stage3.publish_review(
            duplicate["review_id"],
            decision="semantic_split",
            capability_key="captured_split",
            role_key="total",
            display_name="Captured split",
        )
        with self.store.read_connection() as connection:
            old_capsule = connection.execute(
                "SELECT status FROM capsules WHERE capsule_id = ?",
                (original["capsule_id"],),
            ).fetchone()
            new_capsule = connection.execute(
                "SELECT status, current_version_id FROM capsules WHERE capsule_id = ?",
                (split["capsule_id"],),
            ).fetchone()
            version = dict(
                connection.execute(
                    "SELECT cv.*, c.status, c.current_version_id, c.capability_kind "
                    "FROM capsule_versions cv JOIN capsules c "
                    "ON c.capsule_id = cv.capsule_id WHERE cv.version_id = ?",
                    (split["version_id"],),
                ).fetchone()
            )
            source = connection.execute(
                "SELECT source_hash FROM capsule_sources WHERE version_id = ? "
                "AND relationship = 'published_implementation'",
                (split["version_id"],),
            ).fetchone()
        self.assertEqual(old_capsule["status"], "disabled")
        self.assertEqual(tuple(new_capsule), ("active", split["version_id"]))
        self.assertEqual(
            source["source_hash"], second_snapshot.source_identity_sha256
        )
        extraction = json.loads(version["extraction_summary_json"])
        self.assertEqual(
            extraction["semantic_split_reuse"]["retained_version_id"],
            original["version_id"],
        )
        self.assertEqual(
            extraction["semantic_split_reuse"]["source_identity_sha256"],
            second_snapshot.source_identity_sha256,
        )
        self.assertTrue(self.stage3._stored_version_evidence_eligible(version))

        third_root, third_snapshot, third_selection = cloned_source("third-source")
        third = self.stage3.prepare_ephemeral_computation_capture_v2(
            third_snapshot, third_selection, mapping
        )
        third_duplicate = self.stage3.process_ephemeral_capture(third)
        self.stage3.intake.set_root_brand_profile(
            third_root, {"names": ["HP"]}
        )
        with self.assertRaisesRegex(Stage3Error, "brand_profile_changed"):
            self.stage3.publish_review(
                third_duplicate["review_id"],
                decision="semantic_split",
                capability_key="captured_split_stale_brand",
                role_key="total",
                display_name="Stale brand split",
            )

    def test_shared_gate_rejects_incomplete_bound_decisions_without_modules(self) -> None:
        (self.source / "enum.js").write_text(
            "export function total(mode, value) { "
            'if (mode === "double") return value * 2; return value; }\n',
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(snapshot, "enum.js", "total")
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "mode",
                    "kind": "enum",
                    "values": ["single", "double"],
                },
                {
                    "parameter_binding_id": parameters[1]["binding_id"],
                    "input_field": "value",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                },
            ],
            "result_field": "total",
            "examples": [{"input": {"mode": "double", "value": 4}, "expected": 8}],
        }
        waiting = self.stage3.prepare_ephemeral_computation_capture_v2(
            snapshot, selection, mapping
        )
        with patch(
            "pimos_lite.reweave_capsule_stage3._capture_review_decisions",
            return_value={
                "sensitivity_decision": None,
                "brand_decision": None,
                "enum_decision": "confirm_selected_string_enumeration",
                "enum_decision_binding_sha256": waiting[
                    "decision_binding_sha256"
                ],
            },
        ):
            prepared = self.stage3.prepare_ephemeral_computation_capture_v2(
                snapshot, selection, mapping, review_id=waiting["review_id"]
            )
        with self.assertRaisesRegex(Stage3Error, "capture_resubmission_required"):
            self.stage3.process_ephemeral_capture(prepared)
        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT sanitized_candidate_json FROM review_items WHERE review_id = ?",
                (waiting["review_id"],),
            ).fetchone()
        self.assertNotIn("javascript_modules", row["sanitized_candidate_json"])

    def test_brand_change_during_formal_runtime_prevents_module_persistence(self) -> None:
        prepared, _snapshot, _mapping = self._positive_capture()
        original_runtime = self.stage3._runtime_validation

        def change_brand(value: object) -> dict[str, object]:
            result = original_runtime(value)
            self.stage3.intake.set_root_brand_profile(
                "root-stage-e", {"names": ["HP"]}
            )
            return result

        with (
            patch.object(
                self.stage3.supervisor,
                "supervise",
                return_value=self._approved_supervision(),
            ),
            patch.object(
                self.stage3,
                "_runtime_validation",
                side_effect=change_brand,
            ),
            self.assertRaisesRegex(Stage3Error, "brand_profile_changed"),
        ):
            self.stage3.process_ephemeral_capture(prepared)
        with self.store.read_connection() as connection:
            rows = connection.execute(
                "SELECT sanitized_candidate_json FROM review_items"
            ).fetchall()
            sources = connection.execute(
                "SELECT count(*) FROM capsule_sources"
            ).fetchone()[0]
        self.assertFalse(any("javascript_modules" in row[0] for row in rows))
        self.assertEqual(sources, 0)

    def test_capture_bundle_adapter_gate_and_preflight_are_deterministic(self) -> None:
        before_counts = self._formal_counts()
        prepared, snapshot, mapping = self._positive_capture()
        source_hash = hashlib.sha256((self.source / "calc.js").read_bytes()).hexdigest()
        candidate = json.loads(prepared.candidate_payload_json)
        receipt = json.loads(prepared.preflight_receipt_json)
        self.assertEqual(candidate["adapter_contract_version"], "computation_adapter.v2")
        self.assertEqual(
            [item["path"] for item in candidate["canonical_candidate"]["javascript_modules"]],
            ["__reweave_adapter__/compute.js", "__reweave_capture__/selected.js"],
        )
        self.assertEqual(
            candidate["canonical_candidate"]["runtime_allowlist"],
            ["local_computation"],
        )
        self.assertEqual(receipt["validation_scope"], "adapter_example_preflight")
        self.assertIs(receipt["formal_runtime_evidence"], False)
        self.assertTrue(receipt["passed"])
        self.assertEqual(self._formal_counts(), before_counts)
        self.assertEqual(
            hashlib.sha256((self.source / "calc.js").read_bytes()).hexdigest(),
            source_hash,
        )

        gate = capture_static_gate(
            prepared.candidate_payload_json,
            snapshot=snapshot,
            expected_source_identity_sha256=snapshot.source_identity_sha256,
        )
        with patch.object(
            stage3_module,
            "_run_json_command",
            return_value={
                "schema_version": "runtime_validation.v1",
                "status": "passed",
                "cases": [{"ok": True, "value": {"total": 20}}],
            },
        ):
            with self.assertRaisesRegex(Stage3Error, "compute_validation_failed"):
                _validate_computation(
                    candidate["canonical_candidate"],
                    {
                        "normal": [{"quantity": 4, "unit_price": 5}],
                        "boundary": [],
                        "invalid": [],
                    },
                    execution_bundle=gate.execution_bundle,
                    execution_bundle_sha256=gate.execution_bundle_sha256,
                )

        selection, _parameters = _stage_e_selection(snapshot, "calc.js", "calculate")
        repeated = self.stage3.prepare_ephemeral_computation_capture_v2(
            snapshot,
            selection,
            mapping,
        )
        self.assertIsInstance(repeated, PreparedReview)
        self.assertEqual(repeated.candidate_payload_json, prepared.candidate_payload_json)
        self.assertEqual(repeated.rule_versions_json, prepared.rule_versions_json)
        self.assertEqual(repeated.preflight_receipt_json, prepared.preflight_receipt_json)

        tampered = json.loads(prepared.candidate_payload_json)
        tampered["canonical_candidate"]["javascript_modules"][0]["source"] += "\nconst extra = 1;\n"
        tampered_bytes = json.dumps(
            tampered,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        with self.assertRaises(Stage3Error):
            capture_static_gate(
                tampered_bytes,
                snapshot=snapshot,
                expected_source_identity_sha256=snapshot.source_identity_sha256,
            )

        for field in ("source_graph_version", "bundle_contract_version"):
            invalid_evidence = json.loads(prepared.candidate_payload_json)
            invalid_evidence[field] = "forged.v999"
            with self.assertRaises(Stage3Error):
                capture_static_gate(
                    json.dumps(
                        invalid_evidence,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                    snapshot=snapshot,
                    expected_source_identity_sha256=snapshot.source_identity_sha256,
                )
        invalid_closure = json.loads(prepared.candidate_payload_json)
        invalid_closure["dependency_closure"]["closure_sha256"] = "0" * 64
        with self.assertRaisesRegex(Stage3Error, "capture_evidence_invalid"):
            capture_static_gate(
                json.dumps(
                    invalid_closure,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
                snapshot=snapshot,
                expected_source_identity_sha256=snapshot.source_identity_sha256,
            )

        forged_scope = json.loads(prepared.candidate_payload_json)
        forged_scope["scope_snapshot_sha256"] = "f" * 64
        with self.assertRaisesRegex(Stage3Error, "capture_payload_invalid"):
            capture_static_gate(
                json.dumps(
                    forged_scope,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
                snapshot=snapshot,
                expected_source_identity_sha256=snapshot.source_identity_sha256,
            )

        rules = json.loads(prepared.rule_versions_json)
        with self.assertRaisesRegex(Stage3Error, "prepared_review_invalid"):
            make_prepared_review(
                run_id=prepared.run_id,
                review_id=prepared.review_id,
                candidate_id=prepared.candidate_id,
                project_id="wrong-project",
                source_identity_sha256=prepared.source_identity_sha256,
                decision_binding_sha256=prepared.decision_binding_sha256,
                candidate_payload_json=prepared.candidate_payload_json,
                rule_versions=rules,
                preflight_receipt_json=prepared.preflight_receipt_json,
                snapshot=snapshot,
            )

        forged_rules = dict(rules)
        forged_rules["security_rules_version"] = "forged.v999"
        with self.assertRaisesRegex(Stage3Error, "prepared_review_invalid"):
            make_prepared_review(
                run_id=prepared.run_id,
                review_id=prepared.review_id,
                candidate_id=prepared.candidate_id,
                project_id=prepared.project_id,
                source_identity_sha256=prepared.source_identity_sha256,
                decision_binding_sha256=prepared.decision_binding_sha256,
                candidate_payload_json=prepared.candidate_payload_json,
                rule_versions=forged_rules,
                preflight_receipt_json=prepared.preflight_receipt_json,
                snapshot=snapshot,
            )
        forged_receipt = json.loads(prepared.preflight_receipt_json)
        forged_receipt["execution_bundle_sha256"] = "0" * 64
        with self.assertRaisesRegex(Stage3Error, "prepared_review_invalid"):
            make_prepared_review(
                run_id=prepared.run_id,
                review_id=prepared.review_id,
                candidate_id=prepared.candidate_id,
                project_id=prepared.project_id,
                source_identity_sha256=prepared.source_identity_sha256,
                decision_binding_sha256=prepared.decision_binding_sha256,
                candidate_payload_json=prepared.candidate_payload_json,
                rule_versions=rules,
                preflight_receipt_json=json.dumps(
                    forged_receipt,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
                snapshot=snapshot,
            )

    def test_private_capture_workspace_is_marked_and_cleaned(self) -> None:
        root = stage3_module._capture_private_temp_root()
        with stage3_module._capture_temp_workspace() as workspace:
            self.assertTrue(workspace.is_dir())
            self.assertEqual(workspace.parent, root)
            self.assertEqual(
                (workspace / ".reweave-capture-job-v1").read_bytes(),
                stage3_module._CAPTURE_JOB_MARKER,
            )
        self.assertFalse(workspace.exists())

        stale = root / f"job-999999-{os.urandom(16).hex()}"
        stale.mkdir(mode=0o700)
        stale_marker = stale / ".reweave-capture-job-v1"
        stale_marker.write_bytes(stage3_module._CAPTURE_JOB_MARKER)
        unmarked = root / f"job-999998-{os.urandom(16).hex()}"
        unmarked.mkdir(mode=0o700)
        try:
            with (
                patch.object(stage3_module, "_CAPTURE_TEMP_INITIALIZED", False),
                patch.object(stage3_module, "_capture_process_alive", return_value=False),
            ):
                stage3_module._capture_private_temp_root()
            self.assertFalse(stale.exists())
            self.assertTrue(unmarked.exists())
        finally:
            shutil.rmtree(stale, ignore_errors=True)
            shutil.rmtree(unmarked, ignore_errors=True)

    def test_enum_waiting_summary_contains_no_values_and_resubmits(self) -> None:
        (self.source / "price.js").write_text(
            """export function price(mode, value) {
  if (mode === "double") return value * 2;
  return value;
}
""",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(snapshot, "price.js", "price")
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "mode",
                    "kind": "enum",
                    "values": ["single", "double"],
                },
                {
                    "parameter_binding_id": parameters[1]["binding_id"],
                    "input_field": "value",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                },
            ],
            "result_field": "total",
            "examples": [{"input": {"mode": "double", "value": 4}, "expected": 8}],
        }
        before_counts = self._formal_counts()
        waiting = self.stage3.prepare_ephemeral_computation_capture_v2(
            snapshot,
            selection,
            mapping,
        )
        self.assertEqual(waiting["status"], "waiting_user")
        serialized = json.dumps(waiting, ensure_ascii=False)
        self.assertNotIn("double", serialized)
        self.assertNotIn("single", serialized)
        self.assertNotIn("javascript_modules", serialized)
        self.assertNotIn("examples", serialized)
        after_waiting = self._formal_counts()
        self.assertEqual(after_waiting["intake_runs"], before_counts["intake_runs"] + 1)
        self.assertEqual(after_waiting["review_items"], before_counts["review_items"] + 1)
        for table in set(before_counts) - {"intake_runs", "review_items"}:
            self.assertEqual(after_waiting[table], before_counts[table])
        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT sanitized_candidate_json, redaction_summary_json, "
                "source_location_json FROM review_items WHERE review_id = ?",
                (waiting["review_id"],),
            ).fetchone()
        persisted = "\n".join(str(value) for value in row)
        self.assertNotIn("double", persisted)
        self.assertNotIn("single", persisted)
        self.assertNotIn("price.js", persisted)
        self.assertNotIn('"input"', persisted)

        with self.assertRaisesRegex(Stage3Error, "capture_decision_rebuild_required"):
            self.stage3.record_ephemeral_capture_decisions(
                waiting["review_id"],
                "0" * 64,
                enum_decision="confirm_selected_string_enumeration",
            )
        restarted = ReweaveCapsuleStage3(self.store)
        with self.assertRaisesRegex(Stage3Error, "capture_decision_rebuild_required"):
            restarted.record_ephemeral_capture_decisions(
                waiting["review_id"],
                waiting["decision_binding_sha256"],
                enum_decision="confirm_selected_string_enumeration",
            )
        reauthorized = restarted.prepare_ephemeral_computation_capture_v2(
            snapshot,
            selection,
            mapping,
            review_id=waiting["review_id"],
        )
        self.assertEqual(reauthorized["status"], "waiting_user")
        restarted.record_ephemeral_capture_decisions(
            waiting["review_id"],
            waiting["decision_binding_sha256"],
            enum_decision="confirm_selected_string_enumeration",
        )

        prepared = restarted.prepare_ephemeral_computation_capture_v2(
            snapshot,
            selection,
            mapping,
            review_id=waiting["review_id"],
        )
        self.assertIsInstance(prepared, PreparedReview)
        self.assertEqual(
            prepared.decision_binding_sha256, waiting["decision_binding_sha256"]
        )
        self.assertEqual(prepared.review_id, waiting["review_id"])
        self.assertEqual(self._formal_counts(), after_waiting)

    def test_cross_module_helper_boolean_and_tree_shaken_danger_are_supported(self) -> None:
        (self.source / "helper.js").write_text(
            """const factor = 2;
export function adjust(value) {
  return value * factor;
}
export function unrelatedDanger() {
  return fetch("/must-not-enter-capture");
}
""",
            encoding="utf-8",
        )
        (self.source / "main.js").write_text(
            """import { adjust } from "./helper.js";
export function calculate(enabled, value) {
  if (enabled) return adjust(value);
  return value;
}
""",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(snapshot, "main.js", "calculate")
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "enabled",
                    "kind": "boolean",
                },
                {
                    "parameter_binding_id": parameters[1]["binding_id"],
                    "input_field": "value",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                },
            ],
            "result_field": "total",
            "examples": [
                {"input": {"enabled": True, "value": 4}, "expected": 8},
                {"input": {"enabled": False, "value": 4}, "expected": 4},
            ],
        }
        prepared = self.stage3.prepare_ephemeral_computation_capture_v2(
            snapshot,
            selection,
            mapping,
        )
        self.assertIsInstance(prepared, PreparedReview)
        payload = json.loads(prepared.candidate_payload_json)
        selected = next(
            item["source"]
            for item in payload["canonical_candidate"]["javascript_modules"]
            if item["path"] == "__reweave_capture__/selected.js"
        )
        self.assertIn("adjust", selected)
        self.assertNotIn("must-not-enter-capture", selected)
        self.assertNotIn("fetch", selected)

    def test_proved_top_level_helper_initializer_survives_capture(self) -> None:
        (self.source / "initialized.js").write_text(
            """function twice(value) {
  return value * 2;
}
const base = 3;
const fee = twice(base);
export function calculate(value) {
  return value + fee;
}
""",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(
            snapshot, "initialized.js", "calculate"
        )
        prepared = self.stage3.prepare_ephemeral_computation_capture_v2(
            snapshot,
            selection,
            {
                "arguments": [
                    {
                        "parameter_binding_id": parameters[0]["binding_id"],
                        "input_field": "value",
                        "kind": "integer",
                        "minimum": 0,
                        "maximum": 10,
                    }
                ],
                "result_field": "total",
                "examples": [{"input": {"value": 4}, "expected": 10}],
            },
        )
        self.assertIsInstance(prepared, PreparedReview)

    def test_source_change_invalidates_waiting_capture_before_execution(self) -> None:
        source_path = self.source / "mode.js"
        source_path.write_text(
            """export function calculate(mode, value) {
  if (mode === "double") return value * 2;
  return value;
}
""",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(snapshot, "mode.js", "calculate")
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "mode",
                    "kind": "enum",
                    "values": ["single", "double"],
                },
                {
                    "parameter_binding_id": parameters[1]["binding_id"],
                    "input_field": "value",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                },
            ],
            "result_field": "total",
            "examples": [{"input": {"mode": "double", "value": 4}, "expected": 8}],
        }
        waiting = self.stage3.prepare_ephemeral_computation_capture_v2(
            snapshot,
            selection,
            mapping,
        )
        self.stage3.record_ephemeral_capture_decisions(
            waiting["review_id"],
            waiting["decision_binding_sha256"],
            enum_decision="confirm_selected_string_enumeration",
        )
        source_path.write_text(
            """export function calculate(mode, value) {
  if (mode === "double") return value * 3;
  return value;
}
""",
            encoding="utf-8",
        )
        with patch(
            "pimos_lite.reweave_capsule_stage3._validate_computation"
        ) as worker, self.assertRaisesRegex(Stage3Error, "source_changed"):
            self.stage3.prepare_ephemeral_computation_capture_v2(
                snapshot,
                selection,
                mapping,
                review_id=waiting["review_id"],
            )
        worker.assert_not_called()

    def test_capture_sensitive_decisions_cannot_request_source_rewrite(self) -> None:
        (self.source / "customer.js").write_text(
            """export function calculate(customer, value) {
  if (customer === "alice@example.com") return value * 2;
  return value;
}
""",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(
            snapshot, "customer.js", "calculate"
        )
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "customer",
                    "kind": "enum",
                    "values": ["anonymous", "alice@example.com"],
                },
                {
                    "parameter_binding_id": parameters[1]["binding_id"],
                    "input_field": "value",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                },
            ],
            "result_field": "total",
            "examples": [
                {
                    "input": {"customer": "alice@example.com", "value": 4},
                    "expected": 8,
                }
            ],
        }
        waiting = self.stage3.prepare_ephemeral_computation_capture_v2(
            snapshot,
            selection,
            mapping,
        )
        self.assertEqual(waiting["status"], "waiting_user")
        self.assertIn("confirm_fictional_fixture", waiting["allowed_decisions"])
        self.assertIn("confirm_real_record_reject", waiting["allowed_decisions"])
        self.assertNotIn("confirm_safe_redaction", waiting["allowed_decisions"])
        changed_examples = json.loads(json.dumps(mapping))
        changed_examples["examples"][0]["expected"] = 4
        with patch(
            "pimos_lite.reweave_capsule_stage3._validate_computation"
        ) as worker, self.assertRaisesRegex(
            Stage3Error, "capture_resubmission_required"
        ):
            self.stage3.prepare_ephemeral_computation_capture_v2(
                snapshot,
                selection,
                changed_examples,
                review_id=waiting["review_id"],
            )
        worker.assert_not_called()
        with self.assertRaisesRegex(Stage3Error, "review_decision_not_allowed"):
            self.stage3.record_ephemeral_capture_decisions(
                waiting["review_id"],
                waiting["decision_binding_sha256"],
                sensitivity_decision="confirm_safe_redaction",
            )
        with self.assertRaisesRegex(IntakeError, "capture_decision_rebuild_required"):
            self.stage3.intake.record_review_decisions(
                waiting["review_id"],
                sensitivity_decision="confirm_fictional_fixture",
            )
        self.stage3.record_ephemeral_capture_decisions(
            waiting["review_id"],
            waiting["decision_binding_sha256"],
            sensitivity_decision="confirm_real_record_reject",
        )
        with patch(
            "pimos_lite.reweave_capsule_stage3._validate_computation"
        ) as worker:
            rejected = self.stage3.prepare_ephemeral_computation_capture_v2(
                snapshot,
                selection,
                mapping,
                review_id=waiting["review_id"],
            )
        worker.assert_not_called()
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(
            rejected["error_code"], "confirmed_real_record_rejected"
        )
        serialized = json.dumps(rejected, ensure_ascii=False)
        self.assertNotIn("alice@example.com", serialized)

    def test_source_change_during_preflight_prevents_prepared_review(self) -> None:
        source_path = self.source / "late.js"
        source_path.write_text(
            """export function calculate(value) {
  return value * 2;
}
""",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(snapshot, "late.js", "calculate")
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "value",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                }
            ],
            "result_field": "total",
            "examples": [{"input": {"value": 4}, "expected": 8}],
        }

        def mutate_during_preflight(*_args: object, **_kwargs: object) -> dict[str, object]:
            source_path.write_text(
                """export function calculate(value) {
  return value * 3;
}
""",
                encoding="utf-8",
            )
            return {"schema_version": "runtime_validation.v1", "status": "passed"}

        with patch(
            "pimos_lite.reweave_capsule_stage3._validate_computation",
            side_effect=mutate_during_preflight,
        ), self.assertRaisesRegex(Stage3Error, "source_changed"):
            self.stage3.prepare_ephemeral_computation_capture_v2(
                snapshot,
                selection,
                mapping,
            )

    def test_brand_change_during_preflight_prevents_prepared_review(self) -> None:
        source_path = self.source / "brand.js"
        source_path.write_text(
            '''export function calculate(value) {
  if ("HP" === "HP") return value * 2;
  return value;
}
''',
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(
            snapshot, "brand.js", "calculate"
        )
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "value",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                }
            ],
            "result_field": "total",
            "examples": [{"input": {"value": 4}, "expected": 8}],
        }

        def mutate_brand(*_args: object, **_kwargs: object) -> dict[str, object]:
            self.stage3.intake.set_root_brand_profile(
                "root-stage-e", {"names": ["HP"]}
            )
            return {}

        with patch(
            "pimos_lite.reweave_capsule_stage3._validate_computation",
            side_effect=mutate_brand,
        ), self.assertRaisesRegex(Stage3Error, "brand_profile_changed"):
            self.stage3.prepare_ephemeral_computation_capture_v2(
                snapshot,
                selection,
                mapping,
            )

    def test_unsafe_source_never_reaches_example_worker(self) -> None:
        (self.source / "unsafe.js").write_text(
            """export function calculate(value) {
  fetch("/private");
  return value;
}
""",
            encoding="utf-8",
        )
        snapshot = self.source_service.scan(self.project_id)
        selection, parameters = _stage_e_selection(snapshot, "unsafe.js", "calculate")
        mapping = {
            "arguments": [
                {
                    "parameter_binding_id": parameters[0]["binding_id"],
                    "input_field": "value",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 10,
                }
            ],
            "result_field": "total",
            "examples": [{"input": {"value": 4}, "expected": 4}],
        }
        with patch(
            "pimos_lite.reweave_capsule_stage3._validate_computation"
        ) as worker, self.assertRaises(Stage3Error):
            self.stage3.prepare_ephemeral_computation_capture_v2(
                snapshot,
                selection,
                mapping,
            )
        worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
