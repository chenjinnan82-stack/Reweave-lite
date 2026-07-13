"""Tests for Reweave controlled capsule content enrichment (Phase 9)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite import reweave_capsule_content as content
from pimos_lite.reweave_app_service import ReweaveAppService
from pimos_lite.reweave_capsule_content import (
    build_frontend_behavior_contract,
    collect_candidate_paths,
    content_file_path,
    enrich_capsule_content,
    is_allowed_relative_path,
    redact_secrets,
    resolve_safe_path,
)
from pimos_lite.reweave_engine.lumo import LumoReweaveEngine
from pimos_lite.reweave_governance_preview import save_governance_preview
from pimos_lite.reweave_promote import promote_review_item
from pimos_lite.reweave_review_queue import create_or_update_review_queue, load_review_queue, update_review_decision
from pimos_lite import reweave_capsule_warehouse as warehouse
from pimos_lite import reweave_preview_pack as preview
from pimos_lite import reweave_source_registry as registry
from pimos_lite import reweave_source_scanner as scanner
from pimos_lite.reweave_engine.local import LocalReweaveEngine


def _governance_preview() -> dict:
    return {
        "results": [
            {
                "id": "luna_asset_keep",
                "name": "Form Shell",
                "origin": "luna_reuse_pack",
                "verification_status": "verified",
                "verification_score": 0.82,
                "governance_action": "keep",
                "governance_reason": "High metadata match",
            }
        ]
    }


class ReweaveCapsuleContentTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._source_dir = self._state_dir / "user_project"
        self._source_dir.mkdir()
        self._env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._state_dir), "REWEAVE_ENGINE": "local"})
        self._env.start()
        warehouse.clear_warehouse()

        (self._source_dir / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
        (self._source_dir / "app.js").write_text("console.log('hello');", encoding="utf-8")
        (self._source_dir / "styles.css").write_text("body { margin: 0; }", encoding="utf-8")
        (self._source_dir / ".env").write_text("API_KEY=super-secret-value", encoding="utf-8")
        (self._source_dir / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (self._source_dir / "secrets.pem").write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----", encoding="utf-8")
        (self._source_dir / "large.txt").write_text("x" * 5000, encoding="utf-8")

        box = registry.add_source_box(str(self._source_dir))
        self.source_id = str(box["id"])
        scanner.scan_source_box(self.source_id)
        save_governance_preview(self.source_id, _governance_preview())
        create_or_update_review_queue(self.source_id, _governance_preview())
        queue = load_review_queue(self.source_id)
        assert queue
        self.review_id = queue["items"][0]["review_id"]
        update_review_decision(self.source_id, self.review_id, "approved")
        promoted = promote_review_item(self.source_id, self.review_id)
        self.capsule_id = str(promoted["capsule_id"])

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def test_active_promoted_capsule_can_enrich(self) -> None:
        result = enrich_capsule_content(self.capsule_id)
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["snippet_count"], 1)
        self.assertTrue(content_file_path(self.capsule_id).is_file())

    def test_complete_react_project_allows_bounded_large_stylesheet(self) -> None:
        root = self._state_dir / "react-project"
        (root / "src").mkdir(parents=True)
        (root / "src" / "main.tsx").write_text("export default function App() {}\n", encoding="utf-8")
        (root / "src" / "styles.css").write_text(".surface { color: teal; }\n" * 5000, encoding="utf-8")

        files, warnings, complete = content._complete_react_project_files(
            root,
            {"tags": ["react", "project"]},
            {
                "project_graph": {
                    "project_kind": "react_vite",
                    "runtime_files": ["src/main.tsx", "src/styles.css"],
                }
            },
        )

        self.assertTrue(complete)
        self.assertEqual(warnings, [])
        self.assertEqual([item["relative_path"] for item in files], ["src/main.tsx", "src/styles.css"])
        duplicate, _, duplicate_complete = content._complete_react_project_files(
            root,
            {"tags": ["react", "tsx"]},
            {"project_graph": {"project_kind": "react_vite", "runtime_files": ["src/main.tsx"]}},
        )
        self.assertEqual(duplicate, [])
        self.assertFalse(duplicate_complete)

    def test_closed_frontend_module_contract_keeps_complete_files_and_events(self) -> None:
        (self._source_dir / "alternate.html").write_text("<html><body>Alternate</body></html>", encoding="utf-8")
        (self._source_dir / "index.html").write_text(
            '<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head>'
            '<body><label for="amount">Invoice amount</label><input id="amount" placeholder="125">'
            '<button id="runBtn">Run</button><p id="status"></p>'
            '<script src="app.js"></script></body></html>',
            encoding="utf-8",
        )
        (self._source_dir / "app.js").write_text(
            "const runBtn = document.getElementById('runBtn');\n"
            "runBtn.addEventListener('click', () => { document.getElementById('status').textContent = 'done'; });\n",
            encoding="utf-8",
        )
        summary = scanner.scan_source_box(self.source_id)
        contract = build_frontend_behavior_contract(
            self._source_dir,
            summary,
            {"name": "Page Shell"},
        )

        assert contract
        self.assertEqual(contract["status"], "closed")
        self.assertEqual(contract["entry_path"], "index.html")
        self.assertEqual(contract["mode"], "whole_frontend_module")
        self.assertIn("textContent = 'done'", contract["files"]["script"]["content"])
        self.assertIn({"target_id": "runBtn", "event": "click"}, contract["interactions"]["events"])
        semantics = content.build_behavior_semantics(contract)
        fields = semantics["field_contract"]
        self.assertEqual(
            fields["inputs"],
            [{"source_key": "amount", "control_kind": "input", "value_kind": "text", "label": "Invoice amount"}],
        )
        self.assertEqual(
            fields["actions"],
            [
                {
                    "source_key": "runBtn",
                    "event": "click",
                    "control_kind": "button",
                    "label": "Run",
                    "cardinality": 1,
                }
            ],
        )
        self.assertEqual(
            fields["outputs"],
            [
                {
                    "source_key": "status",
                    "target_kind": "id",
                    "write_property": "textContent",
                    "value_kind": "text",
                }
            ],
        )
        self.assertEqual(fields["events"], [{"target_id": "runBtn", "event": "click"}])
        self.assertEqual(fields["limits"], "source_labels_and_structural_roles_only")
        self.assertFalse(contract["safety"]["source_project_write"])

    def test_field_contract_keeps_select_label_and_excludes_input_from_outputs(self) -> None:
        (self._source_dir / "index.html").write_text(
            '<html><body><label>Project size<select id="projectSize">'
            '<option>Small</option><option>Large</option></select></label>'
            '<button id="quoteButton">Build quote</button><button id="helpButton">Help</button>'
            '<input id="quoteResult" readonly><p id="quoteSummary"></p>'
            '<script src="app.js"></script></body></html>',
            encoding="utf-8",
        )
        (self._source_dir / "app.js").write_text(
            "const projectSize = document.getElementById('projectSize');"
            "document.getElementById('quoteButton').addEventListener('click', () => {"
            "document.getElementById('quoteResult').value = projectSize.value;"
            "document.getElementById('quoteSummary').textContent = projectSize.value; });",
            encoding="utf-8",
        )
        summary = scanner.scan_source_box(self.source_id)
        contract = build_frontend_behavior_contract(self._source_dir, summary, {"name": "Page Shell"})

        assert contract
        fields = content.build_behavior_semantics(contract)["field_contract"]

        self.assertEqual(
            fields["inputs"],
            [
                {
                    "source_key": "projectSize",
                    "control_kind": "select",
                    "value_kind": "selection",
                    "label": "Project size",
                    "options": [
                        {"value": "Small", "label": "Small"},
                        {"value": "Large", "label": "Large"},
                    ],
                }
            ],
        )
        self.assertEqual([item["source_key"] for item in fields["actions"]], ["quoteButton"])
        self.assertEqual(
            fields["outputs"],
            [
                {
                    "source_key": "quoteResult",
                    "target_kind": "id",
                    "write_property": "value",
                    "value_kind": "text",
                },
                {
                    "source_key": "quoteSummary",
                    "target_kind": "id",
                    "write_property": "textContent",
                    "value_kind": "text",
                },
            ],
        )
        self.assertEqual(fields["status"], "observed")

    def test_field_contract_distinguishes_assignments_from_comparisons(self) -> None:
        parser = content._FrontendEntryParser()
        parser.feed('<input id="amount" type="number"><button id="run">Run</button>')
        comparisons = content._behavior_interactions(
            parser,
            "const amount = document.getElementById('amount'); "
            "document.getElementById('run').addEventListener('click', () => amount.value === '2');",
        )
        assignment = content._behavior_interactions(
            parser,
            "const amount = document.getElementById('amount'); amount.value += 1;",
        )

        self.assertEqual(comparisons["writes"], [])
        self.assertEqual(
            assignment["writes"],
            [
                {
                    "target_id": "amount",
                    "property": "value",
                    "operator": "+=",
                    "value_kind": "number",
                }
            ],
        )

    def test_field_contract_stays_partial_when_multiple_events_cannot_be_related_to_outputs(self) -> None:
        semantics = content.build_behavior_semantics(
            {
                "interactions": {
                    "controls": [
                        {"kind": "button", "id": "add", "text": "Add"},
                        {"kind": "button", "id": "remove", "text": "Remove"},
                    ],
                    "events": [
                        {"target_id": "add", "event": "click"},
                        {"target_id": "remove", "event": "click"},
                    ],
                    "writes": [
                        {
                            "target_id": "total",
                            "property": "textContent",
                            "operator": "=",
                            "value_kind": "text",
                        }
                    ],
                }
            }
        )

        self.assertEqual(semantics["field_contract"]["status"], "partial")
        self.assertEqual(semantics["field_contract"]["relations"], [])

    def test_frontend_module_contract_blocks_multiple_scripts(self) -> None:
        (self._source_dir / "extra.js").write_text("console.log('extra')", encoding="utf-8")
        (self._source_dir / "index.html").write_text(
            '<html><body><script src="app.js"></script><script src="extra.js"></script></body></html>',
            encoding="utf-8",
        )
        summary = scanner.scan_source_box(self.source_id)
        contract = build_frontend_behavior_contract(self._source_dir, summary, {"name": "Page Shell"})

        assert contract
        self.assertEqual(contract["status"], "blocked")
        self.assertIn("multiple_scripts_not_supported", contract["blockers"])

    def test_closed_frontend_module_contract_accepts_named_html_entry(self) -> None:
        (self._source_dir / "index.html").unlink()
        (self._source_dir / "calendar.html").write_text(
            '<html><body><button id="publishNext">Publish</button><p id="status"></p>'
            '<script src="calendar.js"></script></body></html>',
            encoding="utf-8",
        )
        (self._source_dir / "calendar.js").write_text(
            "document.getElementById('publishNext').addEventListener('click', () => { "
            "document.getElementById('status').textContent = 'published'; });",
            encoding="utf-8",
        )
        summary = scanner.scan_source_box(self.source_id)
        contract = build_frontend_behavior_contract(self._source_dir, summary, {"name": "HTML Surface"})

        assert contract
        self.assertEqual(contract["status"], "closed")
        self.assertEqual(contract["entry_path"], "calendar.html")

    def test_frontend_module_contract_accepts_query_selector_all_events(self) -> None:
        (self._source_dir / "index.html").write_text(
            '<html><body><input type="checkbox" class="step"><p id="progress"></p>'
            '<script src="app.js"></script></body></html>',
            encoding="utf-8",
        )
        (self._source_dir / "app.js").write_text(
            'const steps = Array.from(document.querySelectorAll(".step")); '
            'const progress = document.getElementById("progress"); '
            'steps.forEach((item) => item.addEventListener("change", () => { '
            'progress.textContent = "1 complete"; }));',
            encoding="utf-8",
        )
        summary = scanner.scan_source_box(self.source_id)
        contract = build_frontend_behavior_contract(self._source_dir, summary, {"name": "Page Shell"})

        assert contract
        self.assertEqual(contract["status"], "closed")
        self.assertIn({"target_selector": ".step", "event": "change"}, contract["interactions"]["events"])
        self.assertIn("progress", contract["interactions"]["state_target_ids"])

    def test_frontend_module_contract_accepts_object_query_selectors(self) -> None:
        (self._source_dir / "index.html").write_text(
            '<html><body><button id="run">Run</button><p id="status">Waiting</p>'
            '<script src="app.js"></script></body></html>',
            encoding="utf-8",
        )
        (self._source_dir / "app.js").write_text(
            'const el = { run: document.querySelector("#run"), status: document.querySelector("#status") }; '
            'el.run.addEventListener("click", () => { el.status.textContent = "Done"; });',
            encoding="utf-8",
        )
        summary = scanner.scan_source_box(self.source_id)
        contract = build_frontend_behavior_contract(self._source_dir, summary, {"name": "Page Shell"})

        assert contract
        self.assertEqual(contract["status"], "closed")
        self.assertIn({"target_selector": "#run", "event": "click"}, contract["interactions"]["events"])
        self.assertIn("#status", contract["interactions"]["state_target_selectors"])
        fields = content.build_behavior_semantics(contract)["field_contract"]
        self.assertEqual([item["source_key"] for item in fields["actions"]], ["run"])
        self.assertEqual(
            fields["outputs"],
            [
                {
                    "source_key": "#status",
                    "target_kind": "selector",
                    "write_property": "textContent",
                    "value_kind": "text",
                }
            ],
        )

    def test_field_contract_recognizes_link_cta_as_an_action(self) -> None:
        parser = content._FrontendEntryParser()
        parser.feed('<a class="visit-link" href="#status">Request visit</a><p id="status">Open</p>')
        interactions = content._behavior_interactions(
            parser,
            "const link = document.querySelector('.visit-link'); "
            "const status = document.getElementById('status'); "
            "link.addEventListener('click', () => { status.textContent = 'Requested'; });",
        )
        fields = content.build_behavior_semantics({"interactions": interactions})["field_contract"]

        self.assertEqual(fields["status"], "observed")
        self.assertEqual(fields["actions"][0]["source_key"], ".visit-link")
        self.assertEqual(fields["actions"][0]["control_kind"], "a")
        self.assertEqual(fields["actions"][0]["label"], "Request visit")

    def test_frontend_module_contract_accepts_observable_passive_timer(self) -> None:
        (self._source_dir / "index.html").write_text(
            '<html><body><p id="status">Waiting</p><script src="app.js"></script></body></html>',
            encoding="utf-8",
        )
        (self._source_dir / "app.js").write_text(
            'const status = document.getElementById("status"); '
            'setInterval(() => { status.textContent = "Updated"; }, 3000);',
            encoding="utf-8",
        )
        summary = scanner.scan_source_box(self.source_id)
        contract = build_frontend_behavior_contract(self._source_dir, summary, {"name": "Page Shell"})

        assert contract
        self.assertEqual(contract["status"], "closed")
        self.assertEqual(contract["interaction_mode"], "passive_timer")
        self.assertEqual(contract["interactions"]["events"], [])
        self.assertEqual(contract["interactions"]["passive_updates"], [{"kind": "timer", "api": "setInterval"}])
        self.assertIn("status", contract["interactions"]["state_target_ids"])

    def test_frontend_module_contract_extracts_one_inline_script(self) -> None:
        (self._source_dir / "index.html").write_text(
            '<html><body><button id="run">Run</button><p id="status"></p><script>'
            'const status = document.getElementById("status"); '
            'document.getElementById("run").addEventListener("click", () => { status.textContent = "done"; });'
            '</script></body></html>',
            encoding="utf-8",
        )
        summary = scanner.scan_source_box(self.source_id)
        contract = build_frontend_behavior_contract(self._source_dir, summary, {"name": "Page Shell"})

        assert contract
        self.assertEqual(contract["status"], "closed")
        self.assertEqual(contract["files"]["script"]["source_kind"], "inline")
        self.assertEqual(contract["dependencies"]["inline_script_count"], 1)
        self.assertIn("status.textContent", contract["files"]["script"]["content"])

    def test_frontend_module_contract_blocks_static_html(self) -> None:
        (self._source_dir / "index.html").write_text("<html><body>Static page</body></html>", encoding="utf-8")
        summary = scanner.scan_source_box(self.source_id)
        contract = build_frontend_behavior_contract(self._source_dir, summary, {"name": "Page Shell"})

        assert contract
        self.assertEqual(contract["status"], "blocked")
        self.assertIn("missing_local_script", contract["blockers"])
        self.assertIn("missing_behavior_events", contract["blockers"])

    def test_frontend_module_contract_blocks_runtime_network_dependency(self) -> None:
        (self._source_dir / "index.html").write_text(
            '<html><body><button id="runBtn">Run</button><script src="app.js"></script></body></html>',
            encoding="utf-8",
        )
        (self._source_dir / "app.js").write_text(
            "document.getElementById('runBtn').addEventListener('click', () => fetch('/api/run'));",
            encoding="utf-8",
        )
        summary = scanner.scan_source_box(self.source_id)
        contract = build_frontend_behavior_contract(self._source_dir, summary, {"name": "Page Shell"})

        assert contract
        self.assertEqual(contract["status"], "blocked")
        self.assertIn("runtime_dependency:fetch", contract["blockers"])

    def test_frontend_module_contract_blocks_required_python_service(self) -> None:
        (self._source_dir / "index.html").write_text(
            '<html><body><button id="runBtn">Run</button><p id="status"></p>'
            '<script src="app.js"></script></body></html>',
            encoding="utf-8",
        )
        (self._source_dir / "app.js").write_text(
            'const status = document.getElementById("status"); '
            'document.getElementById("runBtn").addEventListener("click", () => { '
            'status.textContent = "Run python scraper.py first"; });',
            encoding="utf-8",
        )
        summary = scanner.scan_source_box(self.source_id)
        contract = build_frontend_behavior_contract(self._source_dir, summary, {"name": "Page Shell"})

        assert contract
        self.assertEqual(contract["status"], "blocked")
        self.assertIn("runtime_dependency:python_service", contract["blockers"])

    def test_frontend_module_contract_blocks_unobservable_click_state(self) -> None:
        (self._source_dir / "index.html").write_text(
            '<html><body><button id="runBtn">Run</button><script src="app.js"></script></body></html>',
            encoding="utf-8",
        )
        (self._source_dir / "app.js").write_text(
            "let count = 0; document.getElementById('runBtn').addEventListener('click', () => { count += 1; });",
            encoding="utf-8",
        )
        summary = scanner.scan_source_box(self.source_id)
        contract = build_frontend_behavior_contract(self._source_dir, summary, {"name": "Page Shell"})

        assert contract
        self.assertEqual(contract["status"], "blocked")
        self.assertIn("missing_observable_state_target", contract["blockers"])

    def test_disabled_capsule_cannot_enrich(self) -> None:
        warehouse.update_capsule_status(self.capsule_id, "disabled")
        result = enrich_capsule_content(self.capsule_id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "capsule_not_active")

    def test_deprecated_capsule_cannot_enrich(self) -> None:
        warehouse.update_capsule_status(self.capsule_id, "deprecated")
        result = enrich_capsule_content(self.capsule_id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "capsule_not_active")

    def test_only_whitelist_extensions_read(self) -> None:
        summary = scanner.load_summary(self.source_id)
        assert summary
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        paths = collect_candidate_paths(cap, summary)
        for rel in paths:
            self.assertTrue(is_allowed_relative_path(rel))
            self.assertFalse(rel.endswith(".png"))
            self.assertFalse(rel.endswith(".pem"))

    def test_binary_file_not_read(self) -> None:
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        cap = dict(cap)
        cap["snippet"] = {"evidence": ["logo.png", "index.html"]}
        summary = scanner.load_summary(self.source_id) or {}
        paths = collect_candidate_paths(cap, summary)
        self.assertIn("index.html", paths)
        self.assertNotIn("logo.png", paths)

    def test_env_and_pem_not_read(self) -> None:
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        cap = dict(cap)
        cap["snippet"] = {"evidence": [".env", "secrets.pem", "app.js"]}
        summary = scanner.load_summary(self.source_id) or {}
        paths = collect_candidate_paths(cap, summary)
        self.assertIn("app.js", paths)
        self.assertNotIn(".env", paths)
        self.assertNotIn("secrets.pem", paths)

    def test_path_traversal_rejected(self) -> None:
        resolved = resolve_safe_path(self._source_dir, "../../etc/passwd")
        self.assertIsNone(resolved)
        self.assertFalse(is_allowed_relative_path("../index.html"))

    def test_per_file_byte_limit(self) -> None:
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        cap = dict(cap)
        cap["snippet"] = {"evidence": ["large.txt"]}
        warehouse.save_warehouse({"capsules": [cap]})
        result = enrich_capsule_content(self.capsule_id)
        self.assertTrue(result["ok"])
        snippet = result["content"]["snippets"][0]
        self.assertLessEqual(snippet["bytes_read"], 4096)
        self.assertTrue(snippet["truncated"])

    def test_total_byte_limit(self) -> None:
        for i in range(6):
            (self._source_dir / f"chunk{i}.txt").write_text("a" * 3000, encoding="utf-8")
        scanner.scan_source_box(self.source_id)
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        cap = dict(cap)
        cap["snippet"] = {"evidence": [f"chunk{i}.txt" for i in range(6)]}
        warehouse.save_warehouse({"capsules": [cap]})
        result = enrich_capsule_content(self.capsule_id)
        self.assertTrue(result["ok"])
        total = sum(s["bytes_read"] for s in result["content"]["snippets"])
        self.assertLessEqual(total, 16000)
        self.assertLessEqual(len(result["content"]["snippets"]), 5)

    def test_secret_redaction(self) -> None:
        text = "API_KEY=sk-abcdefghijklmnop\nBearer deadbeef12345\npassword=secret"
        redacted, was = redact_secrets(text)
        self.assertTrue(was)
        self.assertIn("[REDACTED_SECRET]", redacted)
        self.assertNotIn("sk-abcdefghijklmnop", redacted)

    def test_corrupt_capsule_content_is_backed_up_and_treated_missing(self) -> None:
        path = content_file_path("bad")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")

        self.assertIsNone(content.load_capsule_content("bad"))
        self.assertTrue(list(path.parent.glob("bad.content.json.corrupt.*.bak")))

    def test_behavior_contract_rejects_remote_iframe_and_stylesheet_url(self) -> None:
        (self._source_dir / "index.html").write_text(
            '<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head><body>'
            '<iframe src="https://example.invalid/frame"></iframe><button id="run">Run</button>'
            '<p id="status"></p><script src="app.js"></script></body></html>',
            encoding="utf-8",
        )
        (self._source_dir / "styles.css").write_text(
            "body { background: url(https://example.invalid/bg.png); }",
            encoding="utf-8",
        )
        (self._source_dir / "app.js").write_text(
            "document.getElementById('run').addEventListener('click', () => {"
            "document.getElementById('status').textContent = 'done'; });",
            encoding="utf-8",
        )
        summary = scanner.scan_source_box(self.source_id)

        contract = build_frontend_behavior_contract(
            self._source_dir,
            summary,
            {"name": "Page Shell", "tags": ["html", "entry"]},
        )

        self.assertEqual(contract["status"], "blocked")
        self.assertTrue(any(str(row).startswith("runtime_network_reference:") for row in contract["blockers"]))

    def test_output_in_capsule_contents(self) -> None:
        enrich_capsule_content(self.capsule_id)
        path = content_file_path(self.capsule_id)
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["mode"], "controlled_snippet_preview")
        self.assertFalse(data["safety"]["source_folder_written"])

    def test_does_not_write_source_folder(self) -> None:
        before = {p.name for p in self._source_dir.iterdir()}
        enrich_capsule_content(self.capsule_id)
        after = {p.name for p in self._source_dir.iterdir()}
        self.assertEqual(before, after)

    def test_warehouse_metadata_updated(self) -> None:
        enrich_capsule_content(self.capsule_id)
        cap = warehouse.get_capsule(self.capsule_id)
        assert cap
        self.assertEqual(cap.get("content_mode"), "controlled_snippet_preview")
        enrichment = cap.get("content_enrichment")
        assert isinstance(enrichment, dict)
        self.assertEqual(enrichment.get("status"), "enriched")
        self.assertEqual(cap.get("content_risk"), "controlled_snippet_preview")
        self.assertEqual(cap.get("risk"), "metadata_only_promoted")

    def test_generate_does_not_include_full_snippet(self) -> None:
        enrich_capsule_content(self.capsule_id)
        result = preview.build_preview_package(
            {"taskText": "Form tool", "capsuleIds": [self.capsule_id], "backend": "local"}
        )
        used_path = Path(result["previewPath"]) / "capsules_used.json"
        used = json.loads(used_path.read_text(encoding="utf-8"))
        entry = used[0]
        self.assertIn("content_enrichment", entry)
        self.assertNotIn("preview", entry)
        prov = json.loads((Path(result["previewPath"]) / "provenance.json").read_text(encoding="utf-8"))
        self.assertIn("content_path", prov["capsules"][0])
        self.assertNotIn("snippets", prov["capsules"][0])

    def test_source_path_missing_returns_error(self) -> None:
        missing_root = self._state_dir / "gone" / "project"
        box = registry.add_source_box(str(missing_root))
        source_id = str(box["id"])
        cap_id = "cap_missing_path_test"
        warehouse.save_warehouse(
            {
                "capsules": [
                    {
                        "id": cap_id,
                        "name": "Missing Path Capsule",
                        "type": "UI",
                        "status": "active",
                        "source_id": source_id,
                        "source_box": {"source_id": source_id, "label": "gone"},
                        "snippet": {"evidence": ["index.html"]},
                        "risk": "metadata_only_promoted",
                    }
                ]
            }
        )
        result = enrich_capsule_content(cap_id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "source_path_not_found")

    def test_app_service_enrich(self) -> None:
        service = ReweaveAppService(engine=LocalReweaveEngine())
        result = service.enrich_capsule_content(self.capsule_id)
        self.assertTrue(result["ok"])

    def test_lumo_index_pack_carries_enrichment_metadata_not_snippets(self) -> None:
        enrich_capsule_content(self.capsule_id)
        local_result = preview.build_preview_package(
            {"taskText": "Form tool", "capsuleIds": [self.capsule_id], "backend": "lumo"}
        )
        calls: list[dict] = []

        class TrackingClient:
            def health(self) -> dict:
                return {"ok": True, "base_url": "http://127.0.0.1:8766", "status": "available", "endpoint": "/health", "details": {}}

            def index_pack(self, payload: dict) -> dict:
                calls.append(payload)
                return {"ok": True, "endpoint": "/api/v1/pym/index-pack", "pack_id": "p1", "manifest_path": "/tmp/p1.json", "raw": {}}

            def reuse_pack(self, payload: dict) -> dict:
                return {"ok": True, "assets": []}

        engine = LumoReweaveEngine(luna_client=TrackingClient())
        result = engine.generate_preview(
            {"taskText": "Form tool", "capsuleIds": [self.capsule_id], "_localPreview": local_result}
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["dispatch"])
        meta = calls[0]["capsules"][0].get("content_enrichment")
        self.assertIsNotNone(meta)
        self.assertNotIn("snippets", calls[0]["capsules"][0])

    def test_behavior_semantics_reports_missing_elapsed_time_without_blocking(self) -> None:
        contract = {
            "files": {
                "script": {
                    "content": "const score = 10; const accuracy = hits / total;",
                }
            },
            "interactions": {
                "controls": [{"kind": "button", "id": "start"}],
                "events": [{"target_id": "start", "event": "click"}],
                "state_target_ids": ["score", "accuracy"],
            },
        }

        semantics = content.build_behavior_semantics(contract)
        claims = content.semantic_claims(["Show reaction time and accuracy score"])
        compatibility = content.build_semantic_compatibility(semantics, claims)

        self.assertEqual(semantics["capabilities"], ["scoring_accuracy"])
        self.assertEqual(semantics["field_contract"]["status"], "partial")
        self.assertEqual(claims, ["scoring_accuracy", "elapsed_time"])
        self.assertEqual(compatibility["status"], "needs_review")
        self.assertEqual(compatibility["missing_capabilities"], ["elapsed_time"])
        self.assertEqual(compatibility["enforcement"], "preview_acceptance_soft_gate")

    def test_behavior_semantics_covers_selection_lookup_and_counter_progress(self) -> None:
        selection = content.build_behavior_semantics(
            {
                "files": {"script": {"content": "const item = prices[document.getElementById('size').value];"}},
                "interactions": {
                    "controls": [{"kind": "select", "id": "size"}],
                    "events": [{"target_id": "submit", "event": "click"}],
                    "state_target_ids": ["summary"],
                },
            }
        )
        counter = content.build_behavior_semantics(
            {
                "files": {"script": {"content": "openTickets = Math.max(0, openTickets - 1);"}},
                "interactions": {
                    "controls": [{"kind": "button", "id": "resolve"}],
                    "events": [{"target_id": "resolve", "event": "click"}],
                    "state_target_ids": ["status"],
                },
            }
        )

        self.assertIn("selection_lookup", selection["capabilities"])
        self.assertIn("counter_progress", counter["capabilities"])
        self.assertEqual(content.semantic_claims(["Package selection and quote summary"]), ["selection_lookup"])
        self.assertEqual(content.semantic_claims(["Resolve oldest ticket"]), ["counter_progress"])
        self.assertEqual(content.semantic_claims(["Open the scorecard summary"]), [])

    def test_behavior_semantics_covers_checklist_and_passive_status(self) -> None:
        checklist = content.build_behavior_semantics(
            {
                "files": {"script": {"content": "items.filter((item) => item.checked).length;"}},
                "interactions": {
                    "controls": [{"kind": "input", "id": "step", "type": "checkbox"}],
                    "events": [{"target_selector": ".step", "event": "change"}],
                    "state_target_ids": ["progress"],
                },
            }
        )
        passive = content.build_behavior_semantics(
            {
                "files": {"script": {"content": "setInterval(updateStatus, 3000);"}},
                "interactions": {
                    "controls": [],
                    "events": [],
                    "passive_updates": [{"kind": "timer", "api": "setInterval"}],
                    "state_target_ids": ["incidentLine"],
                },
            }
        )

        self.assertIn("checklist_progress", checklist["capabilities"])
        self.assertIn("passive_status", passive["capabilities"])
        self.assertEqual(content.semantic_claims(["Release checklist progress"]), ["checklist_progress"])
        self.assertEqual(content.semantic_claims(["Automatic status refresh"]), ["passive_status"])

    def test_field_mapping_preview_preserves_source_value_kinds(self) -> None:
        contract = {
            "status": "observed",
            "inputs": [
                {"source_key": "width", "label": "Width", "value_kind": "number"},
                {"source_key": "height", "label": "Height", "value_kind": "number"},
            ],
            "actions": [{"source_key": "calculate", "label": "Calculate"}],
            "outputs": [{"source_key": "total", "value_kind": "number"}],
        }

        preview = content.build_field_mapping_preview(
            "Build a budget tool; Inputs: Room area, Material rate; Action: Calculate budget; Output: Estimated budget.",
            contract,
        )

        self.assertEqual(preview["status"], "ready")
        self.assertEqual([item["target_label"] for item in preview["mappings"]], [
            "Room area",
            "Material rate",
            "Calculate budget",
            "Estimated budget",
        ])
        self.assertEqual(
            [item["compatibility"] for item in preview["mappings"]],
            [
                "source_value_kind_preserved",
                "source_value_kind_preserved",
                "source_role_preserved",
                "source_value_kind_preserved",
            ],
        )
        self.assertFalse(preview["source_project_write"])
        self.assertFalse(preview["model_call"])

    def test_field_mapping_preview_blocks_partial_or_mismatched_contracts(self) -> None:
        preview = content.build_field_mapping_preview(
            "Inputs: One, Two; Output: Result.",
            {
                "status": "partial",
                "inputs": [{"source_key": "only", "value_kind": "text"}],
                "actions": [],
                "outputs": [{"source_key": "result", "value_kind": "text"}],
            },
        )

        self.assertEqual(preview["status"], "needs_review")
        self.assertEqual(preview["blockers"], ["field_contract_not_fully_observed", "inputs_count_mismatch"])


if __name__ == "__main__":
    unittest.main()
