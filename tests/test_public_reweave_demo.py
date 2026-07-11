from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_CASES = {
    "dashboard": "ops-status-card",
    "landing-page": "artist-landing",
    "form-tool": "customer-quote-widget",
    "admin-panel": "support-ticket-triage",
    "data-viewer": "content-calendar",
}
def test_llm_file_block_parser_accepts_common_markers() -> None:
    from pimos_lite.reweave_llm_pack import parse_file_blocks

    files = parse_file_blocks(
        """### `index.html`
<html></html>
--- styles.css:
body { color: black; }
--- app.js ---
console.log('ok');
"""
    )
    assert set(files) == {"index.html", "styles.css", "app.js"}


def test_bounded_adaptation_rejects_unknown_slots_and_html() -> None:
    from pimos_lite.reweave_llm_pack import parse_bounded_adaptation

    adaptation = {
        "allowed_text_slots": [{"slot_id": "p:0"}],
        "allowed_style_variables": [{"name": "--accent"}],
    }
    for response in (
        '{"text_patches":[{"slot_id":"p:9","value":"No"}],"style_patches":[]}',
        '{"text_patches":[{"slot_id":"p:0","value":"<script>bad</script>"}],"style_patches":[]}',
        '{"text_patches":[{"slot_id":"p:0","value":"New plain text"}],"style_patches":[]}',
    ):
        try:
            parse_bounded_adaptation(response, adaptation)
        except ValueError:
            continue
        raise AssertionError("unsafe bounded adaptation was accepted")


def _assert_local_assets_exist(out: Path) -> None:
    html = (out / "index.html").read_text(encoding="utf-8")
    for asset in re.findall(r"""(?:href|src)=["']([^"']+)["']""", html):
        if asset.startswith(("http://", "https://", "data:", "#")):
            continue
        assert (out / asset).is_file(), asset


def test_public_reweave_demo_help_is_task_driven() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--help",
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert "--source SOURCE" in result.stdout
    assert "--task TASK" in result.stdout
    assert "--template-case" not in result.stdout
    assert "--task-template" not in result.stdout


def test_public_demo_reuses_shared_task_intent_helpers() -> None:
    text = (ROOT / "scripts" / "run_public_reweave_demo.py").read_text(encoding="utf-8")
    assert "CAPABILITY_KEYWORDS =" not in text
    assert "STOP_WORDS =" not in text
    assert "score_capsule_for_task" in text
    assert "reweave_task_intent" in text


def test_public_demo_keeps_complete_react_project_capsule() -> None:
    from scripts.run_public_reweave_demo import _select_enrichable_capsules

    capsules = [
        {"id": "project", "name": "React/Vite Project", "tags": ["react", "vite", "project"]},
        *[
            {"id": str(index), "name": f"Dashboard data {index}", "tags": ["data", "dashboard"]}
            for index in range(5)
        ],
    ]
    selected = _select_enrichable_capsules(
        capsules,
        [],
        lambda _capsule_id: {"ok": True},
        task="Build an operations dashboard",
    )

    assert selected[0]["id"] == "project"
    assert len(selected) == 4


def test_public_reweave_demo_outputs_task_pack(tmp_path: Path) -> None:
    source = ROOT / "examples" / "source_boxes" / "customer-quote-widget"
    out = tmp_path / "reweave_demo"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(source),
            "--task",
            "Build a quote summary card",
            "--out",
            str(out),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["capsules_used"] > 0
    for name in ("task_intent.json", "task_plan.json", "quality_gate.json", "task_pack.json", "capsules_used.json", "provenance.json", "snippets_used.json", "behavior_contract.json", "behavior_adaptation.json", "summary.md"):
        assert (out / name).is_file()
    assert not (source / ".reweave").exists()

    task_pack = json.loads((out / "task_pack.json").read_text(encoding="utf-8"))
    task_intent = json.loads((out / "task_intent.json").read_text(encoding="utf-8"))
    task_plan = json.loads((out / "task_plan.json").read_text(encoding="utf-8"))
    quality_gate = json.loads((out / "quality_gate.json").read_text(encoding="utf-8"))
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    snippets_used = json.loads((out / "snippets_used.json").read_text(encoding="utf-8"))
    behavior_contract = json.loads((out / "behavior_contract.json").read_text(encoding="utf-8"))
    behavior_adaptation = json.loads((out / "behavior_adaptation.json").read_text(encoding="utf-8"))
    assert task_pack["source_project_write"] is False
    assert task_pack["task_intent_path"] == "task_intent.json"
    assert task_pack["task_plan_path"] == "task_plan.json"
    assert task_pack["quality_gate_path"] == "quality_gate.json"
    assert task_pack["quality_gate"]["status"] == "passed"
    assert task_pack["task_intent"]["output_type"] == "tool"
    assert task_pack["task_plan"]["output_type"] == "tool"
    assert task_pack["task_plan"]["composer"]["mode"] == "closed_frontend_module"
    assert task_intent["output_type"] == "tool"
    assert task_plan["outputs"][0]["path"] == "index.html"
    assert task_plan["capsules"]
    assert task_plan["composer"]["optional_inputs"] == ["snippets_used.json"]
    assert task_pack["behavior_reuse"]["status"] == "enabled"
    assert task_pack["behavior_reuse"]["runtime_validation"] == "required"
    assert task_pack["behavior_reuse"]["adaptation_mode"] == "safe_text_adaptation"
    assert task_intent["behavior_reuse"]["capsule_id"] == behavior_contract["selection"]["capsule_id"]
    assert quality_gate["behavior_reuse"]["status"] == "static_verified"
    assert quality_gate["status"] == "passed"
    assert all(check["passed"] for check in quality_gate["checks"])
    assert "check provenance.json" in task_plan["acceptance"]
    assert "form" in task_intent["capabilities"]
    assert task_intent["retrieved_capsules"]
    assert task_pack["selected_capsule_ids"]
    assert provenance["source_boxes"][0]["label"] == "customer-quote-widget"
    assert "path" not in provenance["source_boxes"][0]
    assert "path_hash" not in provenance["source_boxes"][0]
    assert provenance["source_boxes"][0]["path_policy"] == "redacted"
    assert "path_hash" not in payload["source"]
    assert provenance["content_aware_generate"]["enabled"] is True
    assert snippets_used["mode"] == "content_aware_preview"
    assert snippets_used["snippets"]
    assert snippets_used["safety"]["source_folder_read_at_generate_time"] is False
    assert snippets_used["safety"]["used_app_state_content_only"] is True
    html = (out / "index.html").read_text(encoding="utf-8")
    review_html = (out / "review.html").read_text(encoding="utf-8")
    styles = (out / "styles.css").read_text(encoding="utf-8")
    app_js = (out / "app.js").read_text(encoding="utf-8")
    assert "Task Intent" not in html
    assert "Task Intent" in review_html
    assert "Quote summary card" in html
    assert "Prepare a customer estimate" not in html
    assert "quoteButton" in html
    assert "Client name" in html
    assert "Project size" in html
    assert "Select a package to preview pricing." in html
    assert 'data-reweave-behavior="closed"' in html
    assert "Plan files" not in html
    assert "Planned outputs" in review_html
    assert "Source-backed cues" not in html
    assert "Reused signals" not in html
    assert "Source Boxes" not in html
    assert "provenance" not in html.lower()
    assert "Reused signals" in review_html
    assert "Source Boxes" in review_html
    assert "provenance" in review_html.lower()
    assert "capsule metadata only" not in html
    assert "--ink: #172033;" in styles
    assert "quoteButton" in app_js
    assert "Estimated budget" in app_js
    assert app_js == (source / "quote.js").read_text(encoding="utf-8")
    assert behavior_adaptation["mode"] == "safe_text_adaptation"
    assert {item["target"] for item in behavior_adaptation["patches"]} == {
        "document_title",
        "primary_heading",
    }
    assert {"clientName", "projectSize", "quoteButton", "quoteSummary"}.issubset(
        behavior_adaptation["protected"]["dom_ids"]
    )
    _assert_local_assets_exist(out)


def test_behavior_pack_without_title_or_heading_still_passes(tmp_path: Path) -> None:
    source = tmp_path / "counter-source"
    source.mkdir()
    (source / "index.html").write_text(
        '<html><head><link rel="stylesheet" href="styles.css"></head><body>'
        '<button id="go">Go</button><script src="app.js"></script></body></html>',
        encoding="utf-8",
    )
    (source / "styles.css").write_text("button { color: #111; }", encoding="utf-8")
    (source / "app.js").write_text(
        "document.getElementById('go').addEventListener('click', () => {});",
        encoding="utf-8",
    )
    out = tmp_path / "reweave_counter"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(source),
            "--task",
            "Build a daily action counter",
            "--out",
            str(out),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["quality_gate"]["status"] == "passed"
    assert "Build a daily action counter" in (out / "index.html").read_text(encoding="utf-8")


def test_public_reweave_demo_runs_five_source_boxes(tmp_path: Path) -> None:
    listed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--list-template-cases",
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(listed.stdout)
    assert {item["id"] for item in payload["template_cases"]} == set(TEMPLATE_CASES)
    assert payload["warnings"] == ["legacy demo shortcut; prefer --source + --task for the product path"]

    for case_id, source_name in TEMPLATE_CASES.items():
        source = ROOT / "examples" / "source_boxes" / source_name
        out = tmp_path / f"reweave_{case_id}"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_public_reweave_demo.py"),
                "--template-case",
                case_id,
                "--out",
                str(out),
            ],
            check=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["source_project_write"] is False
        assert not (source / ".reweave").exists()
        for required in ("index.html", "review.html", "styles.css", "app.js", "task_intent.json", "task_plan.json", "quality_gate.json", "task_pack.json", "capsules_used.json", "provenance.json", "snippets_used.json"):
            assert (out / required).is_file()
        task_pack = json.loads((out / "task_pack.json").read_text(encoding="utf-8"))
        task_intent = json.loads((out / "task_intent.json").read_text(encoding="utf-8"))
        task_plan = json.loads((out / "task_plan.json").read_text(encoding="utf-8"))
        quality_gate = json.loads((out / "quality_gate.json").read_text(encoding="utf-8"))
        snippets_used = json.loads((out / "snippets_used.json").read_text(encoding="utf-8"))
        html = (out / "index.html").read_text(encoding="utf-8")
        review_html = (out / "review.html").read_text(encoding="utf-8")
        app_js = (out / "app.js").read_text(encoding="utf-8")
        assert task_pack["source_project_write"] is False
        assert task_pack["project_type"] == "small_project_pack"
        assert task_pack["task_intent_path"] == "task_intent.json"
        assert task_pack["task_plan_path"] == "task_plan.json"
        assert task_pack["quality_gate_path"] == "quality_gate.json"
        assert task_intent["needed_files"] == ["index.html", "styles.css", "app.js"]
        assert task_plan["source_project_write"] is False
        behavior_expected = case_id in TEMPLATE_CASES
        assert task_plan["composer"]["mode"] == (
            "closed_frontend_module" if behavior_expected else "task_plan_and_snippets"
        )
        assert quality_gate["status"] == "passed"
        assert task_pack["template_case"]["id"] == case_id
        assert task_pack["template_case"]["source"].endswith(source_name)
        assert payload["warnings"] == ["legacy demo shortcut; prefer --source + --task for the product path"]
        assert task_pack["warnings"] == ["legacy demo shortcut; prefer --source + --task for the product path"]
        assert payload["source"]["label"] == source_name
        assert snippets_used["snippets"]
        assert "Task Intent" not in html
        assert "Task Intent" in review_html
        assert "project-checklist" not in html
        assert "reweave-step" not in html
        if behavior_expected:
            assert task_pack["behavior_reuse"]["status"] == "enabled"
            assert task_pack["behavior_reuse"]["interaction_mode"] == (
                "passive_timer" if case_id == "dashboard" else "user_event"
            )
            assert (out / "behavior_contract.json").is_file()
            assert 'data-reweave-behavior="closed"' in html
        else:
            assert task_pack["behavior_reuse"]["status"] == "unavailable"
            assert "local follow-up" in app_js
        assert "provenance" not in html.lower()
        assert "Source excerpts used" not in html
        assert "Source excerpts used" in review_html
        assert "provenance" in review_html.lower()
        _assert_local_assets_exist(out)


def test_public_reweave_demo_keeps_task_templates_as_demo_shortcuts(tmp_path: Path) -> None:
    listed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--list-task-templates",
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    choices = json.loads(listed.stdout)
    assert choices["warnings"] == ["legacy demo shortcut; prefer --source + --task for the product path"]
    assert {item["id"] for item in choices["task_templates"]} == {
        "portfolio-viewer",
        "operations-panel",
        "artist-landing",
    }

    source = ROOT / "examples" / "source_boxes" / "customer-quote-widget"
    out = tmp_path / "reweave_task_template"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(source),
            "--task-template",
            "operations-panel",
            "--out",
            str(out),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    task_pack = json.loads((out / "task_pack.json").read_text(encoding="utf-8"))
    task_intent = json.loads((out / "task_intent.json").read_text(encoding="utf-8"))
    task_plan = json.loads((out / "task_plan.json").read_text(encoding="utf-8"))
    assert payload["source_project_write"] is False
    assert payload["warnings"] == ["legacy demo shortcut; prefer --source + --task for the product path"]
    assert payload["task_template"]["id"] == "operations-panel"
    assert task_pack["task_template"]["id"] == "operations-panel"
    assert task_pack["warnings"] == ["legacy demo shortcut; prefer --source + --task for the product path"]
    assert "task_profile" not in task_pack
    assert task_pack["task_intent_path"] == "task_intent.json"
    assert task_pack["task_plan_path"] == "task_plan.json"
    assert task_intent["output_type"] == "data_panel"
    assert task_plan["output_type"] == "data_panel"
    assert task_pack["task"] == "Build an operations panel"
    html = (out / "index.html").read_text(encoding="utf-8")
    review_html = (out / "review.html").read_text(encoding="utf-8")
    assert "Task Intent" not in html
    assert "Task Intent" in review_html
    assert "quoteButton" in html
    assert (out / "index.html").is_file()
    assert (out / "provenance.json").is_file()
    _assert_local_assets_exist(out)

    portfolio_out = tmp_path / "reweave_task_template_portfolio"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(source),
            "--task-template",
            "portfolio-viewer",
            "--out",
            str(portfolio_out),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    portfolio_pack = json.loads((portfolio_out / "task_pack.json").read_text(encoding="utf-8"))
    portfolio_intent = json.loads((portfolio_out / "task_intent.json").read_text(encoding="utf-8"))
    portfolio_html = (portfolio_out / "index.html").read_text(encoding="utf-8")
    assert "task_profile" not in portfolio_pack
    assert portfolio_intent["output_type"] == "data_panel"
    portfolio_review_html = (portfolio_out / "review.html").read_text(encoding="utf-8")
    assert "Task Intent" not in portfolio_html
    assert "Task Intent" in portfolio_review_html
    assert "quoteButton" in portfolio_html


def test_artist_source_content_drives_generated_page(tmp_path: Path) -> None:
    source = ROOT / "examples" / "source_boxes" / "artist-landing"
    out = tmp_path / "reweave_artist"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(source),
            "--task",
            "Build an artist landing page",
            "--out",
            str(out),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    html = (out / "index.html").read_text(encoding="utf-8")
    review_html = (out / "review.html").read_text(encoding="utf-8")
    styles = (out / "styles.css").read_text(encoding="utf-8")
    assert "Mira Vale Studio" in html
    assert "Artist landing page" in html
    assert "Mira builds layered ink studies" in html
    assert "Request a studio preview" in html
    assert "Glasshouse Notes" in html
    assert "Task Intent" not in html
    assert "Source excerpts used" in review_html
    assert "color: #1d241f;" in styles
    app_js = (out / "app.js").read_text(encoding="utf-8")
    behavior = json.loads((out / "behavior_contract.json").read_text(encoding="utf-8"))
    assert "visitLink.addEventListener" in app_js
    assert {"target_selector": ".visit-link", "event": "click"} in behavior["interactions"]["events"]


def test_default_capsule_selection_prefers_enrichable_capsules() -> None:
    from scripts.run_public_reweave_demo import _select_enrichable_capsules

    capsules = [{"id": "bad"}, {"id": "good1"}, {"id": "good2"}, {"id": "good3"}, {"id": "good4"}]

    def enrich(capsule_id: str) -> dict[str, object]:
        return {"ok": capsule_id.startswith("good")}

    selected = _select_enrichable_capsules(capsules, [], enrich)
    assert [cap["id"] for cap in selected] == ["good1", "good2", "good3", "good4"]


def test_default_capsule_selection_uses_task_relevance() -> None:
    from scripts.run_public_reweave_demo import _select_enrichable_capsules

    capsules = [
        {"id": "copy", "name": "Markdown Doc", "tags": ["docs", "copy"]},
        {"id": "form", "name": "Quote Form", "tags": ["form", "input"]},
        {"id": "style", "name": "Style Sheet", "tags": ["css", "layout"]},
        {"id": "logic", "name": "Validation Script", "tags": ["javascript", "logic"]},
        {"id": "misc", "name": "Misc Notes", "tags": ["notes"]},
    ]

    selected = _select_enrichable_capsules(
        capsules,
        [],
        lambda capsule_id: {"ok": True},
        task="Build a styled quote form with validation",
    )
    assert [cap["id"] for cap in selected[:3]] == ["form", "style", "logic"]


def test_public_reweave_demo_supports_manual_capsule_selection(tmp_path: Path) -> None:
    source = ROOT / "examples" / "source_boxes" / "customer-quote-widget"
    listed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(source),
            "--list-capsules",
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    choices = json.loads(listed.stdout)
    assert choices["source_project_write"] is False
    assert {item["name"] for item in choices["capsules"]} >= {"Style Sheet", "Script Module"}

    out = tmp_path / "reweave_manual_selection"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(source),
            "--task",
            "Build a styled quote interaction",
            "--select-capsule",
            "Style Sheet",
            "--select-capsule",
            "Script Module",
            "--out",
            str(out),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    task_pack = json.loads((out / "task_pack.json").read_text(encoding="utf-8"))
    task_intent = json.loads((out / "task_intent.json").read_text(encoding="utf-8"))
    task_plan = json.loads((out / "task_plan.json").read_text(encoding="utf-8"))
    capsules_used = json.loads((out / "capsules_used.json").read_text(encoding="utf-8"))
    selected_names = [item["name"] for item in payload["selected_capsules"]]
    assert selected_names == ["Style Sheet", "Script Module"]
    assert task_pack["selection_mode"] == "manual"
    assert task_intent["retrieved_capsules"]
    assert task_plan["capsules"]
    assert all(item.get("reason") for item in task_pack["selected_capsules"])
    assert [item["name"] for item in task_pack["selected_capsules"]] == selected_names
    assert [item["name"] for item in capsules_used] == selected_names
    assert task_pack["source_project_write"] is False
    _assert_local_assets_exist(out)


def test_public_reweave_demo_keeps_optional_ollama_bounded(tmp_path: Path) -> None:
    source = ROOT / "examples" / "source_boxes" / "customer-quote-widget"
    out = tmp_path / "reweave_llm_selection"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(source),
            "--task",
            "Build a styled quote interaction",
            "--select-capsule",
            "Style Sheet",
            "--select-capsule",
            "Script Module",
            "--llm",
            "ollama",
            "--model",
            "tiny-test",
            "--ollama-url",
            "http://127.0.0.1:9",
            "--out",
            str(out),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    task_pack = json.loads((out / "task_pack.json").read_text(encoding="utf-8"))
    assert payload["llm"]["applied"] is False
    assert payload["llm"]["error"] == "no_closed_behavior_module"
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "LLM quote pack" not in html
    assert "/missing.css" not in html
    assert "/missing.js" not in html
    assert "styles.css" in html
    assert "app.js" in html
    assert (out / "app.js").is_file()
    assert provenance["llm_generation"]["model"] == "tiny-test"
    assert provenance["llm_generation"]["local_http_call"] is False
    assert provenance["llm_generation"]["external_network_call"] is False
    assert provenance["llm_generation"]["source_project_write"] is False
    assert provenance["content_aware_generate"]["llm_called"] is False
    assert task_pack["llm_generation"]["applied"] is False
    _assert_local_assets_exist(out)


def test_public_reweave_demo_rejects_remote_ollama_url_without_network(tmp_path: Path) -> None:
    source = ROOT / "examples" / "source_boxes" / "customer-quote-widget"
    out = tmp_path / "reweave_remote_ollama"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(source),
            "--task",
            "Build a quote card",
            "--llm",
            "ollama",
            "--ollama-url",
            "https://example.com",
            "--out",
            str(out),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert payload["llm"]["applied"] is False
    assert "ollama_url_must_be_localhost" in payload["llm"]["error"]
    assert provenance["llm_generation"]["external_network_call"] is False
    assert provenance["llm_generation"]["source_project_write"] is False


def test_bounded_only_ollama_skips_pack_without_closed_behavior(tmp_path: Path) -> None:
    from pimos_lite.reweave_llm_pack import apply_ollama_pack

    out = tmp_path / "preview"
    out.mkdir()
    (out / "task_pack.json").write_text(
        json.dumps({"behavior_reuse": {"status": "unavailable"}}),
        encoding="utf-8",
    )
    (out / "provenance.json").write_text(json.dumps({}), encoding="utf-8")

    with patch("pimos_lite.reweave_llm_pack.call_ollama") as call_model:
        meta = apply_ollama_pack(
            out,
            task="Build a small page",
            selected_capsules=[],
            snippet_context=None,
            model="tiny-test",
            base_url="http://127.0.0.1:11434",
            bounded_only=True,
        )

    call_model.assert_not_called()
    assert meta["error"] == "no_closed_behavior_module"
    assert meta["local_http_call"] is False
    assert meta["source_project_write"] is False
    receipt = json.loads((out / "task_pack.json").read_text(encoding="utf-8"))
    assert receipt["llm_generation"]["error"] == "no_closed_behavior_module"


def test_public_reweave_demo_applies_bounded_llm_adaptation_to_behavior_pack(tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            captured["prompt"] = str(request.get("prompt") or "")
            response = json.dumps(
                {
                    "text_patches": [
                        {"slot_id": "p:0", "value": "Renovation quote desk"},
                        {"slot_id": "button:0", "value": "Calculate renovation budget"},
                        {"slot_id": "option:0", "value": "Room refresh"},
                    ],
                    "style_patches": [{"name": "--accent", "value": "#2563eb"}],
                }
            )
            payload = json.dumps({"response": response}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source = ROOT / "examples" / "source_boxes" / "customer-quote-widget"
    out = tmp_path / "reweave_behavior_bounded_llm"
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_public_reweave_demo.py"),
                "--source",
                str(source),
                "--task",
                "Build a renovation quote tool",
                "--llm",
                "ollama",
                "--model",
                "tiny-bounded-test",
                "--ollama-url",
                f"http://127.0.0.1:{server.server_port}",
                "--out",
                str(out),
            ],
            check=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    payload = json.loads(result.stdout)
    task_pack = json.loads((out / "task_pack.json").read_text(encoding="utf-8"))
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    adaptation = json.loads((out / "behavior_adaptation.json").read_text(encoding="utf-8"))
    html = (out / "index.html").read_text(encoding="utf-8")
    styles = (out / "styles.css").read_text(encoding="utf-8")

    assert payload["llm"]["applied"] is True
    assert payload["llm"]["mode"] == "bounded_behavior_adaptation"
    assert payload["llm"]["text_patch_count"] == 3
    assert payload["llm"]["style_patch_count"] == 1
    assert task_pack["quality_gate"]["status"] == "passed"
    assert task_pack["behavior_reuse"]["bounded_llm_adaptation"] == "applied"
    assert provenance["behavior_reuse"]["bounded_llm_adaptation"] == "applied"
    assert "Renovation quote desk" in html
    assert "Calculate renovation budget" in html
    assert "Room refresh" in html
    assert "--accent: #2563eb" in styles
    assert adaptation["llm_adaptation"]["model"] == "tiny-bounded-test"
    assert (out / "app.js").read_text(encoding="utf-8") == (source / "quote.js").read_text(encoding="utf-8")
    assert "Estimated budget" not in captured["prompt"]


def test_public_reweave_demo_keeps_behavior_pack_when_bounded_llm_is_unavailable(tmp_path: Path) -> None:
    source = ROOT / "examples" / "source_boxes" / "customer-quote-widget"
    out = tmp_path / "reweave_behavior_llm_fallback"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(source),
            "--task",
            "Build a renovation quote tool",
            "--llm",
            "ollama",
            "--ollama-url",
            "http://127.0.0.1:9",
            "--out",
            str(out),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    task_pack = json.loads((out / "task_pack.json").read_text(encoding="utf-8"))

    assert payload["llm"]["applied"] is False
    assert payload["llm"]["fallback_used"] is True
    assert payload["llm"]["mode"] == "bounded_behavior_adaptation"
    assert payload["llm"]["local_http_call"] is True
    assert task_pack["quality_gate"]["status"] == "passed"
    assert "quoteButton" in (out / "index.html").read_text(encoding="utf-8")
    assert (out / "app.js").read_text(encoding="utf-8") == (source / "quote.js").read_text(encoding="utf-8")


def test_bounded_adaptation_rolls_back_when_quality_gate_fails(tmp_path: Path) -> None:
    from pimos_lite.reweave_llm_pack import apply_bounded_behavior_adaptation

    source = ROOT / "examples" / "source_boxes" / "customer-quote-widget"
    out = tmp_path / "reweave_bounded_rollback"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--source",
            str(source),
            "--task",
            "Build a renovation quote tool",
            "--out",
            str(out),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    paths = [out / name for name in ("index.html", "styles.css", "behavior_adaptation.json", "quality_gate.json", "task_pack.json")]
    before = {path: path.read_bytes() for path in paths}
    response = '{"text_patches":[{"slot_id":"p:0","value":"Renovation desk"}],"style_patches":[]}'

    with patch("pimos_lite.reweave_llm_pack.build_quality_gate", return_value={"status": "failed"}):
        try:
            apply_bounded_behavior_adaptation(out, response, model="test")
        except ValueError:
            pass
        else:
            raise AssertionError("failed bounded quality gate did not reject adaptation")

    assert all(path.read_bytes() == before[path] for path in paths)


def test_public_reweave_demo_refuses_repo_output() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--out",
            str(ROOT / "reweave_demo"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "inside the repository" in result.stderr


def test_public_reweave_demo_refuses_existing_non_demo_dir(tmp_path: Path) -> None:
    out = tmp_path / "reweave_existing"
    out.mkdir()
    (out / "keep.txt").write_text("do not delete\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_public_reweave_demo.py"),
            "--out",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "non-demo output directory" in result.stderr
    assert (out / "keep.txt").is_file()
