"""Stage 3 safety and isolated-runtime tests."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from pimos_lite.reweave_capsule_intake import (
    EXTRACTION_CONTRACT_VERSION,
    ReweaveCapsuleIntake,
)
from pimos_lite.reweave_capsule_stage3 import (
    OllamaSupervisor,
    ReweaveCapsuleStage3,
    Stage3Error,
    _clean_assets,
    _validate_computation,
    _validate_qweb,
    sanitize_css,
    sanitize_html,
)
from pimos_lite.reweave_capsule_store import CapsuleWarehouseStore


ROOT = Path(__file__).resolve().parents[1]


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
<section data-capsule-root><span data-ref="title"></span></section>
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
            """<!doctype html><html><body><section data-capsule-root>
<input data-ref="quantity" type="number" min="1" max="10" step="1" value="2">
<button data-action="calculate" type="button">Calculate</button>
</section><script type="module" src="./interaction.js"></script></body></html>""",
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


if __name__ == "__main__":
    unittest.main()
