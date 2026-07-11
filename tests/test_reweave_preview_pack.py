"""Tests for Reweave preview package v0 (no PySide6)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pimos_lite import reweave_capsule_content as content
from pimos_lite import reweave_capsule_draft as draft
from pimos_lite import reweave_capsule_warehouse as warehouse
from pimos_lite import reweave_preview_pack as preview
from pimos_lite import reweave_project_renderer as renderer
from pimos_lite import reweave_react_preview as react_preview
from pimos_lite.reweave_quality_gate import build_quality_gate
from pimos_lite.reweave_behavior_runtime import validate_preview_behavior
from pimos_lite.reweave_project_renderer import build_app_js
from pimos_lite.reweave_project_renderer import build_index_html
from pimos_lite.reweave_project_renderer import build_preview_readme
from pimos_lite.reweave_project_renderer import build_review_html
from pimos_lite.reweave_project_renderer import build_styles_css
from pimos_lite import reweave_source_registry as registry
from pimos_lite import reweave_source_scanner as scanner
from pimos_lite.reweave_task_intent import behavior_contract_search_text, build_task_intent, select_capsules_for_task
from pimos_lite.reweave_task_plan import build_task_plan


class ReweavePreviewPackTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_dir = Path(self._tmpdir.name)
        self._env = patch.dict(os.environ, {"REWEAVE_STATE_DIR": str(self._state_dir)})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def test_empty_behavior_contract_has_no_search_text(self) -> None:
        self.assertEqual(behavior_contract_search_text({}), "")

    def test_react_preview_rejects_truncated_capsule_files(self) -> None:
        record = {
            "snippets": [
                {
                    "relative_path": "src/App.tsx",
                    "preview": "export default function App() {}",
                    "truncated": True,
                    "redacted": False,
                }
            ]
        }
        with patch.object(react_preview, "load_capsule_content", return_value=record):
            files, missing = react_preview._complete_snippets(["cap_react"], ["src/App.tsx"])

        self.assertEqual(files, {})
        self.assertEqual(missing, ["src/App.tsx"])

    def test_react_preview_does_not_mix_project_files_from_another_source(self) -> None:
        records = {
            "cap_other": {
                "source_id": "box_other",
                "project_files": [{"relative_path": "src/App.tsx", "content": "wrong"}],
            },
            "cap_primary": {
                "source_id": "box_primary",
                "project_files": [{"relative_path": "src/App.tsx", "content": "correct"}],
            },
        }
        with patch.object(react_preview, "load_capsule_content", side_effect=records.get):
            files, missing = react_preview._complete_snippets(
                ["cap_other", "cap_primary"],
                ["src/App.tsx"],
                source_id="box_primary",
            )

        self.assertEqual(files, {"src/App.tsx": "correct"})
        self.assertEqual(missing, [])

    def test_react_preview_does_not_replace_dynamic_heading(self) -> None:
        files = {"src/App.tsx": "export default () => <h1>{title}</h1>;"}
        targets = [{"path": "src/App.tsx", "kind": "component"}]

        updated, receipt = react_preview._adapt_static_slots(files, "Build a quote tool", targets)

        self.assertEqual(updated, files)
        self.assertEqual(receipt["status"], "needs_review")
        self.assertEqual(receipt["reason"], "safe_static_heading_not_found")

    def test_react_preview_replaces_bounded_localized_heading(self) -> None:
        files = {"src/pages/Home.tsx": "<h1>{localize(homeHero.title, language)}</h1>"}
        targets = [{"path": "src/pages/Home.tsx", "kind": "component"}]

        updated, receipt = react_preview._adapt_static_slots(files, "Build a portfolio", targets)

        self.assertEqual(updated["src/pages/Home.tsx"], "<h1>Build a portfolio</h1>")
        self.assertEqual(receipt["changes"][0]["slot_id"], "src/pages/Home.tsx:h1-localized:0")

    def test_react_preview_uses_semantic_title_container(self) -> None:
        files = {
            "src/main.tsx": (
                '<header className="mini-title"><span>Brand</span>'
                "<strong>Visible start</strong></header>"
                "<section><h1>Hidden later stage</h1></section>"
            )
        }
        targets = [{"path": "src/main.tsx", "kind": "entry"}]

        updated, receipt = react_preview._adapt_static_slots(files, "Build a planning studio", targets)

        self.assertIn("<strong>Build a planning studio</strong>", updated["src/main.tsx"])
        self.assertIn("<h1>Hidden later stage</h1>", updated["src/main.tsx"])
        self.assertEqual(receipt["changes"][0]["slot_id"], "src/main.tsx:semantic-strong:1")

    def test_react_preview_uses_brand_text_when_no_heading_exists(self) -> None:
        files = {
            "src/DesktopStage.tsx": (
                '<button className="brand-mark"><Logo /><span>Old brand</span></button>'
                "<span>Online</span>"
            )
        }
        targets = [{"path": "src/DesktopStage.tsx", "kind": "component"}]

        updated, receipt = react_preview._adapt_static_slots(files, "Build a material viewer", targets)

        self.assertIn("<span>Build a material viewer</span>", updated["src/DesktopStage.tsx"])
        self.assertIn("<span>Online</span>", updated["src/DesktopStage.tsx"])
        self.assertEqual(receipt["changes"][0]["slot_id"], "src/DesktopStage.tsx:semantic-span:0")

    def test_react_preview_prefers_home_heading_over_hidden_subpage(self) -> None:
        files = {
            "src/pages/CapturePage.tsx": "export default () => <h1>Capture</h1>;",
            "src/pages/HomePage.tsx": "export default () => <h1>Home</h1>;",
        }
        targets = [
            {"path": "src/pages/CapturePage.tsx", "kind": "component"},
            {"path": "src/pages/HomePage.tsx", "kind": "component"},
        ]

        updated, receipt = react_preview._adapt_static_slots(files, "Build a review helper", targets)

        self.assertIn("Build a review helper", updated["src/pages/HomePage.tsx"])
        self.assertIn("Capture", updated["src/pages/CapturePage.tsx"])
        self.assertEqual(receipt["changes"][0]["slot_id"], "src/pages/HomePage.tsx:h1:0")

    def test_react_preview_prefers_opening_heading_over_archive(self) -> None:
        files = {
            "src/CropArchive.tsx": "export default () => <h2>Archive</h2>;",
            "src/OpeningScreen.tsx": "export default () => <h1>Welcome</h1>;",
        }
        targets = [
            {"path": "src/CropArchive.tsx", "kind": "component"},
            {"path": "src/OpeningScreen.tsx", "kind": "component"},
        ]

        updated, receipt = react_preview._adapt_static_slots(files, "Build a crop logbook", targets)

        self.assertIn("Build a crop logbook", updated["src/OpeningScreen.tsx"])
        self.assertIn("Archive", updated["src/CropArchive.tsx"])
        self.assertEqual(receipt["changes"][0]["slot_id"], "src/OpeningScreen.tsx:h1:0")

    def test_react_preview_adapts_heading_in_entry_file(self) -> None:
        files = {"src/main.tsx": "export default () => <main><h1>Studio</h1></main>;"}
        targets = [{"path": "src/main.tsx", "kind": "entry"}]

        updated, receipt = react_preview._adapt_static_slots(files, "Build a studio", targets)

        self.assertIn("Build a studio", updated["src/main.tsx"])
        self.assertEqual(receipt["status"], "applied")

    def test_react_preview_marks_unknown_runtime_dependency_for_review(self) -> None:
        project = self._state_dir / "react-extra-dependency"
        (project / "src").mkdir(parents=True)
        (project / "src" / "main.jsx").write_text(
            "import React from 'react';\nconsole.log(React.version);\n",
            encoding="utf-8",
        )

        receipt = react_preview._compile(project, "src/main.jsx", ["react", "axios"])

        self.assertEqual(receipt["status"], "needs_review")
        self.assertEqual(receipt["compiler_status"], "passed")
        self.assertEqual(receipt["unsupported_dependencies"], ["axios"])
        self.assertTrue(receipt["preview_output_write"])

    def test_react_preview_bundles_allowlisted_lucide_dependency(self) -> None:
        project = self._state_dir / "react-lucide-dependency"
        (project / "src").mkdir(parents=True)
        (project / "src" / "main.jsx").write_text(
            "import React from 'react';\n"
            "import { Camera } from 'lucide-react';\n"
            "console.log(React.version, Camera);\n",
            encoding="utf-8",
        )

        receipt = react_preview._compile(project, "src/main.jsx", ["react", "lucide-react"])

        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["compiler_status"], "passed")

    def test_react_preview_supplies_empty_vite_env(self) -> None:
        project = self._state_dir / "react-vite-env"
        (project / "src").mkdir(parents=True)
        (project / "src" / "main.jsx").write_text(
            "console.log(import.meta.env.VITE_API_BASE || 'local');\n",
            encoding="utf-8",
        )

        receipt = react_preview._compile(project, "src/main.jsx", [])

        self.assertEqual(receipt["status"], "passed")
        compiled = (project / "dist" / "app.js").read_text(encoding="utf-8")
        self.assertIn("define_import_meta_env_default = {}", compiled)
        self.assertNotIn("console.log(import.meta.env", compiled)

    def test_runtime_validation_without_behavior_contract_does_not_start_qt(self) -> None:
        result = validate_preview_behavior(self._state_dir)

        self.assertEqual(result["status"], "not_run")
        self.assertEqual(result["reason"], "no_closed_behavior_module")
        self.assertFalse(result["source_project_write"])

    def _promote_capsules(self) -> list[str]:
        root = self._state_dir / "preview-source"
        root.mkdir()
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        (root / "app.py").write_text("# app", encoding="utf-8")
        box = registry.add_source_box(root)
        scanner.scan_source_box(box["id"])
        draft.draft_capsules(box["id"])
        promoted = warehouse.promote_source_drafts(box["id"])
        return [c["id"] for c in promoted]

    def test_build_preview_writes_to_state_dir(self) -> None:
        cap_ids = self._promote_capsules()
        self.assertGreater(len(cap_ids), 0)
        result = preview.build_preview_package(
            {"taskText": "Client quote tool", "capsuleIds": cap_ids[:2], "backend": "local", "selectionMode": "manual"}
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["mock"])
        preview_path = Path(result["previewPath"])
        self.assertTrue(preview_path.is_dir())
        self.assertEqual(preview_path.resolve().parent, preview.preview_packages_dir().resolve())
        for name in ("index.html", "review.html", "styles.css", "app.js", "task_intent.json", "task_plan.json", "quality_gate.json", "task_pack.json", "capsules_used.json", "provenance.json", "summary.md"):
            self.assertTrue((preview_path / name).is_file())
        html = (preview_path / "index.html").read_text(encoding="utf-8")
        review_html = (preview_path / "review.html").read_text(encoding="utf-8")
        self.assertNotIn("Task Intent", html)
        self.assertIn("reweaveDemoButton", html)
        self.assertIn("review.html", html)
        self.assertNotIn("Plan files", html)
        self.assertIn("Task Intent", review_html)
        self.assertIn("Planned outputs", review_html)
        self.assertNotIn("Source-backed cues", html)
        self.assertNotIn("capsule metadata only", html)
        self.assertIn("Reused signals", review_html)
        self.assertIn("Source Boxes", review_html)
        self.assertIn("Client quote tool", html)
        app_js = (preview_path / "app.js").read_text(encoding="utf-8")
        self.assertIn("local follow-up", app_js)
        task_pack = json.loads((preview_path / "task_pack.json").read_text(encoding="utf-8"))
        task_intent = json.loads((preview_path / "task_intent.json").read_text(encoding="utf-8"))
        task_plan = json.loads((preview_path / "task_plan.json").read_text(encoding="utf-8"))
        quality_gate = json.loads((preview_path / "quality_gate.json").read_text(encoding="utf-8"))
        self.assertEqual(task_pack["mode"], "task_pack_preview")
        self.assertEqual(task_pack["package_kind"], "small_project_pack")
        self.assertEqual(task_pack["task_profile"], "task_driven")
        self.assertEqual(task_pack["task_intent_path"], "task_intent.json")
        self.assertEqual(task_pack["task_plan_path"], "task_plan.json")
        self.assertEqual(task_pack["quality_gate_path"], "quality_gate.json")
        self.assertEqual(task_pack["composer"]["mode"], "task_plan_and_snippets")
        self.assertEqual(task_intent["output_type"], "tool")
        self.assertIn("form", task_intent["capabilities"])
        self.assertEqual(task_plan["output_type"], "tool")
        self.assertEqual(task_plan["composer"]["mode"], "task_plan_and_snippets")
        self.assertEqual({item["path"] for item in task_plan["outputs"]}, {"index.html", "styles.css", "app.js"})
        self.assertTrue(task_plan["capsules"])
        self.assertIn("check provenance.json", task_plan["acceptance"])
        self.assertEqual(quality_gate["status"], "passed")
        self.assertTrue(all(check["passed"] for check in quality_gate["checks"]))
        self.assertEqual(task_pack["selection_mode"], "manual")
        self.assertFalse(task_pack["source_project_write"])
        self.assertEqual(task_pack["selected_capsule_ids"], cap_ids[:2])
        provenance = json.loads((preview_path / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["backend"], "local")
        self.assertEqual(provenance["task_intent_path"], "task_intent.json")
        self.assertEqual(provenance["task_plan_path"], "task_plan.json")
        self.assertEqual(provenance["quality_gate_path"], "quality_gate.json")
        self.assertEqual(len(provenance["capsule_ids"]), 2)
        self.assertEqual(
            {item["path"] for item in provenance["outputs"]},
            {"index.html", "styles.css", "app.js"},
        )
        self.assertTrue(all(item["source_project_write"] is False for item in provenance["outputs"]))

    def test_react_vite_graph_flows_into_preview_only_task_plan(self) -> None:
        root = self._state_dir / "react-vite-preview-source"
        source = root / "src"
        source.mkdir(parents=True)
        (root / "package.json").write_text(
            json.dumps(
                {
                    "name": "react-quote",
                    "dependencies": {"react": "^19.0.0", "react-dom": "^19.0.0"},
                    "devDependencies": {"vite": "^7.0.0"},
                }
            ),
            encoding="utf-8",
        )
        (source / "main.tsx").write_text(
            "import React from 'react';\n"
            "import { createRoot } from 'react-dom/client';\n"
            "import App from './App';\n"
            "import './styles.css';\n"
            "createRoot(document.getElementById('root')!).render(<App />);\n",
            encoding="utf-8",
        )
        (source / "App.tsx").write_text(
            "import React, { useState } from 'react';\n"
            "export default function App() {\n"
            "  const [status, setStatus] = useState('Idle');\n"
            "  const handleQuote = () => setStatus('Ready');\n"
            "  return <main><h1>Old quote</h1><p>Old summary</p>"
            "<button onClick={handleQuote}>Quote</button><span>{status}</span></main>;\n"
            "}\n",
            encoding="utf-8",
        )
        (source / "styles.css").write_text("button { color: teal; }\n", encoding="utf-8")
        before = {path.name: path.read_bytes() for path in source.iterdir()}
        box = registry.add_source_box(root)
        scanner.scan_source_box(box["id"])
        draft.draft_capsules(box["id"])
        promoted = warehouse.promote_source_drafts(box["id"])
        cap_ids = [cap["id"] for cap in promoted]
        for cap_id in cap_ids:
            content.enrich_capsule_content(cap_id)
        project_content = next(
            record
            for record in (content.load_capsule_content(cap_id) for cap_id in cap_ids)
            if isinstance(record, dict) and record.get("project_files")
        )
        self.assertTrue(project_content["project_files_complete"])
        self.assertEqual(
            [item["relative_path"] for item in project_content["project_files"]],
            ["src/main.tsx", "src/App.tsx", "src/styles.css"],
        )

        result = preview.build_preview_package(
            {
                "taskText": "Build a React quote component",
                "capsuleIds": cap_ids,
                "backend": "local",
                "useEnrichedContent": True,
            }
        )

        preview_path = Path(result["previewPath"])
        graph = json.loads((preview_path / "project_graph.json").read_text(encoding="utf-8"))
        intent = json.loads((preview_path / "task_intent.json").read_text(encoding="utf-8"))
        plan = json.loads((preview_path / "task_plan.json").read_text(encoding="utf-8"))
        provenance = json.loads((preview_path / "provenance.json").read_text(encoding="utf-8"))
        compile_receipt = json.loads((preview_path / "react_compile.json").read_text(encoding="utf-8"))
        adaptation_receipt = json.loads((preview_path / "react_adaptation.json").read_text(encoding="utf-8"))
        self.assertEqual(graph["project_kind"], "react_vite")
        self.assertEqual(intent["project_context"]["graph_status"], "analyzed")
        self.assertEqual(
            [item["path"] for item in plan["project_targets"]],
            ["src/main.tsx", "src/App.tsx", "src/styles.css"],
        )
        self.assertTrue(all(item["write_mode"] == "preview_only" for item in plan["project_targets"]))
        self.assertEqual(plan["project_graph_path"], "project_graph.json")
        self.assertFalse(provenance["project_graph"]["source_project_write"])
        self.assertEqual(compile_receipt["status"], "passed")
        self.assertEqual(compile_receipt["compile_scope"], "allowlisted_runtime_dependencies_bundled")
        self.assertEqual(adaptation_receipt["status"], "applied")
        self.assertEqual(adaptation_receipt["mode"], "safe_static_text_slots")
        self.assertEqual(
            [slot["slot_id"] for slot in adaptation_receipt["slots"]],
            ["src/App.tsx:h1:0", "src/App.tsx:p:0", "src/App.tsx:button:0"],
        )
        self.assertEqual(
            intent["react_adaptation"]["changes"][0]["slot_id"],
            "src/App.tsx:h1:0",
        )
        self.assertEqual(plan["react_adaptation_path"], "react_adaptation.json")
        self.assertIn("react_adaptation.json", plan["composer"]["optional_inputs"])
        self.assertTrue((preview_path / "react_project" / "src" / "App.tsx").is_file())
        self.assertIn(
            "Build a React quote component",
            (preview_path / "react_project" / "src" / "App.tsx").read_text(encoding="utf-8"),
        )
        self.assertTrue((preview_path / "react_project" / "dist" / "app.js").is_file())
        self.assertTrue((preview_path / "react_project" / "dist" / "index.html").is_file())
        self.assertFalse(compile_receipt["source_project_write"])
        self.assertEqual(before, {path.name: path.read_bytes() for path in source.iterdir()})

    def test_operations_task_uses_task_intent_not_fixed_template_profile(self) -> None:
        cap_ids = self._promote_capsules()
        result = preview.build_preview_package(
            {"taskText": "Build an operations panel", "capsuleIds": cap_ids[:2], "backend": "local"}
        )

        preview_path = Path(result["previewPath"])
        html = (preview_path / "index.html").read_text(encoding="utf-8")
        task_pack = json.loads((preview_path / "task_pack.json").read_text(encoding="utf-8"))
        task_intent = json.loads((preview_path / "task_intent.json").read_text(encoding="utf-8"))
        task_plan = json.loads((preview_path / "task_plan.json").read_text(encoding="utf-8"))

        review_html = (preview_path / "review.html").read_text(encoding="utf-8")
        self.assertNotIn("Task Intent", html)
        self.assertIn("Task Intent", review_html)
        self.assertIn("Review output", html)
        self.assertEqual(task_pack["task_profile"], "task_driven")
        self.assertEqual(task_intent["output_type"], "data_panel")
        self.assertEqual(task_plan["output_type"], "data_panel")
        self.assertIn("data", task_intent["capabilities"])
        self.assertEqual(
            [item["kind"] for item in task_pack["planned_outputs"]],
            ["data_panel_html", "task_style", "task_runtime"],
        )

    def test_task_selection_uses_source_labels_for_english_and_chinese(self) -> None:
        capsules = []
        for source in ("customer-quote-widget", "content-calendar", "support-ticket-triage"):
            for name, kind in (("HTML Surface", "UI"), ("Style Sheet", "Style"), ("Script Module", "Logic"), ("Markdown Doc", "Text")):
                capsules.append(
                    {
                        "id": f"{source}-{kind}",
                        "name": name,
                        "type": kind,
                        "source": source,
                        "source_id": source,
                        "role": "reusable project capability",
                        "tags": [],
                        "content_enrichment": {"status": "enriched"},
                        "_closed_behavior": name == "HTML Surface",
                    }
                )

        quote = select_capsules_for_task("Build a renovation budget estimator for homeowners", capsules)
        calendar = select_capsules_for_task("Build an editorial calendar data viewer", capsules)
        support = select_capsules_for_task("构建客服工单分流面板", capsules)

        self.assertEqual({cap["source_id"] for cap in quote}, {"customer-quote-widget"})
        self.assertEqual({cap["source_id"] for cap in calendar}, {"content-calendar"})
        self.assertEqual({cap["source_id"] for cap in support}, {"support-ticket-triage"})
        self.assertTrue(any(cap["_closed_behavior"] for cap in quote))
        self.assertTrue(any(cap["_closed_behavior"] for cap in calendar))
        self.assertTrue(any(cap["_closed_behavior"] for cap in support))

    def test_task_selection_uses_behavior_text_when_source_labels_are_opaque(self) -> None:
        capsules = [
            {
                "id": "archive-a-ui",
                "name": "HTML Surface",
                "source": "archive-a",
                "source_id": "archive-a",
                "content_enrichment": {"status": "enriched"},
                "_closed_behavior": True,
                "_behavior_text": "Inventory restock approval queue with approve request button",
            },
            {
                "id": "archive-b-ui",
                "name": "HTML Surface",
                "source": "archive-b",
                "source_id": "archive-b",
                "content_enrichment": {"status": "enriched"},
                "_closed_behavior": True,
                "_behavior_text": "Artist portfolio studio visit and selected works",
            },
        ]

        selected = select_capsules_for_task("Build an inventory restock approval tool", capsules)

        self.assertEqual([cap["source_id"] for cap in selected], ["archive-a"])

    def test_task_selection_prefers_specific_source_name_over_generic_page_words(self) -> None:
        capsules = [
            {
                "id": "system",
                "name": "HTML Surface",
                "source": "sys_monitor",
                "source_id": "system",
                "_behavior_text": "Status display",
            },
            {
                "id": "water",
                "name": "HTML Surface",
                "source": "water-tracker",
                "source_id": "water",
                "_behavior_text": "System dashboard monitor status",
            },
        ]

        selected = select_capsules_for_task("Build a system monitor status dashboard", capsules)

        self.assertEqual([cap["source_id"] for cap in selected], ["system"])

    def test_task_selection_does_not_reward_sources_for_having_more_capsules(self) -> None:
        capsules = [
            {
                "id": "timer",
                "name": "Page Shell",
                "source": "pomodoro-timer",
                "source_id": "timer",
                "_behavior_text": "Pomodoro task timer",
            },
            *[
                {
                    "id": f"generic-{index}",
                    "name": "HTML Surface",
                    "source": "generic-tools",
                    "source_id": "generic",
                    "_behavior_text": "Task tool with timer status",
                }
                for index in range(4)
            ],
        ]

        selected = select_capsules_for_task("Build a Pomodoro task timer", capsules)

        self.assertEqual([cap["source_id"] for cap in selected], ["timer"])

    def test_task_contract_is_shared_across_pack_renderer_gate_and_provenance(self) -> None:
        cap_ids = self._promote_capsules()
        with (
            patch.object(renderer, "_task_intent", side_effect=AssertionError("renderer recomputed task intent")),
            patch.object(renderer, "_task_profile", side_effect=AssertionError("renderer recomputed task profile")),
        ):
            result = preview.build_preview_package(
                {"taskText": "Build a customer quote dashboard", "capsuleIds": cap_ids[:2], "selectionMode": "manual"}
            )

        root = Path(result["previewPath"])
        task_pack = json.loads((root / "task_pack.json").read_text(encoding="utf-8"))
        task_intent = json.loads((root / "task_intent.json").read_text(encoding="utf-8"))
        task_plan = json.loads((root / "task_plan.json").read_text(encoding="utf-8"))
        quality_gate = json.loads((root / "quality_gate.json").read_text(encoding="utf-8"))
        provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
        review_html = (root / "review.html").read_text(encoding="utf-8")

        self.assertEqual(result["taskPack"], task_pack)
        self.assertEqual(task_pack["task_intent"], task_intent)
        self.assertEqual(task_pack["task_plan"], task_plan)
        self.assertEqual(task_pack["quality_gate"], quality_gate)
        expected_paths = {"index.html", "styles.css", "app.js"}
        self.assertEqual({item["path"] for item in task_pack["planned_outputs"]}, expected_paths)
        self.assertEqual({item["path"] for item in task_plan["outputs"]}, expected_paths)
        self.assertEqual({item["path"] for item in provenance["outputs"]}, expected_paths)
        self.assertTrue(all(item["reason"] in review_html for item in task_plan["capsules"]))
        self.assertEqual(result["generatedPackage"]["files"].count("task_pack.json"), 1)
        self.assertFalse(task_pack["source_project_write"])
        self.assertEqual(quality_gate["status"], "passed")

    def test_preview_pack_uses_split_task_helpers(self) -> None:
        self.assertIs(preview._task_intent, build_task_intent)
        self.assertIs(preview._task_plan, build_task_plan)
        self.assertIs(preview._quality_gate, build_quality_gate)
        self.assertIs(preview._build_index_html, build_index_html)
        self.assertIs(preview._build_styles_css, build_styles_css)
        self.assertIs(preview._build_app_js, build_app_js)
        self.assertIs(preview._build_preview_readme, build_preview_readme)
        self.assertIs(preview._build_review_html, build_review_html)

    def test_source_cues_reject_code_fragments(self) -> None:
        self.assertEqual(renderer._clean_source_cue("// DOM elements"), "")
        self.assertEqual(renderer._clean_source_cue("target: document.getElementById('target'),"), "")
        self.assertEqual(renderer._clean_source_cue("Daily hydration target"), "Daily hydration target")

    def test_latest_preview_restored(self) -> None:
        cap_ids = self._promote_capsules()
        preview.build_preview_package({"taskText": "Status panel", "capsuleIds": cap_ids[:1]})
        latest = preview.load_latest_preview()
        assert latest is not None
        self.assertTrue(Path(latest["previewPath"]).is_dir())
        self.assertIn("generatedPackage", latest)
        self.assertIn("task_pack.json", latest["generatedPackage"]["files"])

    def test_missing_capsules_raises(self) -> None:
        with self.assertRaises(ValueError):
            preview.build_preview_package({"taskText": "x", "capsuleIds": ["cap_missing"]})

    def test_failed_quality_gate_removes_new_preview_directory(self) -> None:
        cap_ids = self._promote_capsules()
        with (
            patch.object(preview, "_quality_gate", return_value={"status": "failed"}),
            self.assertRaisesRegex(ValueError, "preview quality gate failed"),
        ):
            preview.build_preview_package({"taskText": "broken preview", "capsuleIds": cap_ids[:1]})

        self.assertEqual(list(preview.preview_packages_dir().iterdir()), [])

    def test_quality_gate_rejects_invalid_javascript(self) -> None:
        root = self._state_dir / "invalid-js"
        root.mkdir()
        (root / "index.html").write_text("<html><body>Invalid JS task</body></html>", encoding="utf-8")
        (root / "review.html").write_text("reason", encoding="utf-8")
        (root / "styles.css").write_text("body {}", encoding="utf-8")
        (root / "app.js").write_text("try {} catch (error) alert(error)", encoding="utf-8")
        task_plan = {
            "outputs": [{"path": name} for name in ("index.html", "styles.css", "app.js")],
            "capsules": [{"reason": "reason"}],
        }

        gate = build_quality_gate(root, "Invalid JS task", task_plan, content_aware=False)

        syntax_check = next(check for check in gate["checks"] if check["name"] == "javascript_syntax_valid")
        self.assertFalse(syntax_check["passed"])
        self.assertEqual(gate["status"], "failed")

    def test_preview_index_escapes_task_and_capsule_fields(self) -> None:
        html = preview._build_index_html(
            "<script>alert(1)</script>",
            [
                {
                    "name": "<img src=x>",
                    "type": "<b>",
                    "role": "<script>role</script>",
                    "preview": ["<script>bad()</script>"],
                }
            ],
        )

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        review_html = preview._build_review_html(
            "<script>alert(1)</script>",
            [
                {
                    "name": "<img src=x>",
                    "type": "<b>",
                    "role": "<script>role</script>",
                    "preview": ["<script>bad()</script>"],
                }
            ],
        )
        self.assertIn("&lt;img src=x&gt;", review_html)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", review_html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x>", html)

    def test_behavior_adaptation_escapes_task_and_preserves_contract_ids(self) -> None:
        contract = {
            "status": "closed",
            "files": {
                "entry": {
                    "content": '<html><head><title>Old</title></head><body><h1>Old heading</h1><button id="runBtn">Run</button></body></html>'
                },
                "script": {"content": "document.getElementById('runBtn')", "sha256": "demo"},
            },
            "interactions": {
                "controls": [{"id": "runBtn"}],
                "events": [{"target_id": "runBtn", "event": "click"}],
                "state_target_ids": [],
            },
        }
        html = preview._build_index_html(
            "Build <script>alert(1)</script>",
            [],
            behavior_contract=contract,
        )

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn('id="runBtn"', html)

    def test_behavior_renderer_moves_inline_script_to_app_file(self) -> None:
        contract = {
            "status": "closed",
            "files": {
                "entry": {
                    "content": '<html><body><button id="runBtn">Run</button><script>window.inlineRan = true;</script></body></html>'
                },
                "script": {"content": "window.inlineRan = true;", "sha256": "demo", "source_kind": "inline"},
            },
            "interactions": {
                "controls": [{"id": "runBtn"}],
                "events": [{"target_id": "runBtn", "event": "click"}],
                "state_target_ids": [],
            },
        }

        html = preview._build_index_html("Run inline tool", [], behavior_contract=contract)

        self.assertNotIn("window.inlineRan", html)
        self.assertEqual(html.count('<script src="app.js"></script>'), 1)

    def test_preview_package_redacts_source_box_paths_by_default(self) -> None:
        result = preview.build_preview_package(
            {
                "taskText": "Path redaction",
                "capsules": [{"id": "cap_demo", "name": "Demo", "type": "ui", "preview": []}],
                "sourceBoxes": [
                    {
                        "id": "source_demo",
                        "label": "demo",
                        "path": "/Users/alice/private-project",
                        "path_hash": "sha256:stable",
                    }
                ],
            }
        )

        provenance = json.loads((Path(result["previewPath"]) / "provenance.json").read_text(encoding="utf-8"))
        box = provenance["source_boxes"][0]
        self.assertEqual(box["id"], "source_demo")
        self.assertEqual(box["label"], "demo")
        self.assertEqual(box["path_policy"], "redacted")
        self.assertNotIn("path", box)
        self.assertNotIn("path_hash", box)


if __name__ == "__main__":
    unittest.main()
