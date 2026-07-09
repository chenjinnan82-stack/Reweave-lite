"""Static release checks for Reweave's bridge-first frontend shell."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mock_fallback_does_not_present_local_warehouse_workbench() -> None:
    app = (ROOT / "reweave_frontend" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "reweave_frontend" / "index.html").read_text(encoding="utf-8")
    mock = (ROOT / "reweave_frontend" / "mock-data.json").read_text(encoding="utf-8")
    styles = (ROOT / "reweave_frontend" / "styles.css").read_text(encoding="utf-8")

    assert (ROOT / "reweave_frontend" / "assets" / "reweave-icon.svg").exists()
    assert 'src="assets/reweave-icon.svg"' in index
    assert ".logo-mark::before" not in styles
    assert ".logo-mark::after" not in styles
    assert 'class="btn-ghost btn-add-source hidden" disabled' in index
    assert '"sourceBoxes":[{"' not in index
    assert '"capsules":[{"' not in index
    assert '"sourceBoxes": []' in mock
    assert '"capsules": []' in mock
    assert "Local · Lumo engine" not in mock
    assert "Recover old work" not in mock
    assert "src_output" not in mock
    assert "cap_form_shell" not in mock
    assert "Current Runtime" in index
    assert "Current Runtime · artifacts" in index
    assert "Bind Source Box" in index
    assert "Choose a source folder to clean into capsules." in index
    assert 'id="source-box-mode-note"' in index
    assert 'id="btn-view-runtime"' in index
    assert 'placeholder="Current Runtime / read-only"' in index
    assert "GENERATION INPUT" in index
    assert 'id="generation-input-note"' in index
    assert 'id="workflow-status"' in index
    assert "Workflow: Bind Source Box" in index
    assert '<h3 class="generated-title">Current Runtime</h3>' in index
    assert 'class="btn-secondary btn-open-folder hidden"' in index
    assert '<span id="sources-count">0</span> bound' in index
    assert "Select old project folder" not in index
    assert "Local · Lumo engine" not in index
    assert "Digesting old project into capsules" not in index
    assert '"cleaningSteps":["Current Runtime / artifacts"]' in index
    assert "function normalizeMockFallback()" in app
    assert 'data.lumoLiteMode = "read_only_runtime_artifact_viewer";' in app
    assert "data && data.lumoLiteMode" in app
    assert "data.sourceBoxes = [];" in app
    assert "data.capsules = [];" in app
    assert "data.warehouseCapsules = [];" in app
    assert 'data.cleaningSteps = ["Current Runtime / artifacts"];' in app
    assert "Current Runtime / artifacts" in app
    assert "currentPreviewPackageId && !isLumoLiteReadOnly()" in app
    assert "!currentPreviewPackageId || isLumoLiteReadOnly()" in app
    assert 'cap.origin === "lumo_lite_capsule_warehouse") return canBuildTaskPackPreview();' in app
    assert "function isCapsuleManageEligible(cap)" in app
    assert "function syncSourceControls()" in app
    assert "function syncWelcomeSourceBoxMode()" in app
    assert "function handleStoreSource(sourceId)" in app
    assert 'storeBtn.textContent = "Store";' in app
    assert "Bind locally, scan read-only, no source writes." in app
    assert 'desktopCapability("canChooseSourceFolder")' in app
    assert 'desktopCapability("canScanSourceBox")' in app
    assert 'desktopCapability("canDraftCapsules")' in app
    assert 'params.get("desktop") === "1"' not in app
    assert 'params.get("main") === "1"' in app
    assert 'classList.toggle("hidden", !allowed)' in app
    assert 'new QWebChannel(qt.webChannelTransport' in app
    assert "function applyLumoLiteRuntimeView()" in app
    assert "function currentWorkflowStep(hasTaskPackPreview)" in app
    assert "function taskPackStatusFromFiles(files)" in app
    assert "Intent ready · Plan ready · Quality gate passed · Source writes 0" in app
    assert "View provenance" in app
    assert "function canBuildTaskPackPreview()" in app
    assert 'els.taskInput.disabled = !taskPackPreview;' in app
    assert 'els.btnGenerate.classList.toggle("hidden", !taskPackPreview);' in app
    assert "Build Small Project Pack" in app
    assert "Small Project Pack ready" in app
    assert 'selectionMode: usedCapsuleIds.length > 0 ? "manual" : "auto_match"' in app
    assert "Generate will use exactly these capsules." in app
    assert ".generation-input-note" in styles
    assert 'openFolder.classList.add("hidden");' in app
    assert "Product capability: unavailable" in app
    assert "summary.product_capability_line || summary.line" in app
    assert 'responseBits.push("Product base ready");' not in app
    assert 'responseBits.push("Task pack ready");' not in app
    assert "btn-artifact-view" in app
    assert "btn-artifact-copy" in app
    assert "btn-artifact-open" not in app
    assert "Opened Lumo Lite artifact." not in app
    assert 'data.generatedPackage || { folder: "Current Runtime", files: [] }' in app
    assert 'els.generatedPackage.classList.toggle("runtime-read-only", !hasTaskPackPreview);' in app
    assert 'els.generatedPreview.classList.toggle("hidden", !hasTaskPackPreview);' in app
    assert "Runtime artifacts" in app
    assert "capsules_used / trace receipts" in app
    assert 'f === "task_intent.json"' in app
    assert 'f === "task_plan.json"' in app
    assert 'f === "quality_gate.json"' in app
    assert "capsules linked to this runtime" in app
    assert "No local generation history in read-only mode" in app
    assert "show && hasDesktopBridge() && (!isLumoLiteReadOnly() || canBuildTaskPackPreview())" in app
    assert 'els.reweaveResponse.textContent = "Current Runtime is read-only.";' in app
    assert "function blockReadyRender(message)" in app
    assert "if ((isLumoLiteReadOnly() && !canBuildTaskPackPreview()) || !result || result.ok === false)" in app
    assert ".generated-package.runtime-read-only .generated-files" in styles
    assert ".sources-list li > span:first-child" in styles
    assert "text-overflow: ellipsis;" in styles


def test_public_release_entrypoints_do_not_reference_private_workspaces() -> None:
    forbidden = (
        "workspace_" + "sixcats_argus_integration",
        "pym_luna_" + "lite_migration_stage4_main_rehearsal",
        "/Users/" + "hack",
        "$ROOT/" + "Luna/",
        "$ROOT/" + "Doraemon/",
    )
    paths = [
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        ROOT / "start_reweave_static.sh",
        ROOT / "pimos_lite" / "reweave_luna_client.py",
        ROOT / "pimos_lite" / "reweave_lumo_lite_artifacts.py",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert not any(value in text for value in forbidden), path


def test_public_source_box_examples_exist() -> None:
    examples = ROOT / "examples" / "source_boxes"
    for name in ("customer-quote-widget", "ops-status-card"):
        box = examples / name
        assert (box / "README.md").is_file()
        assert any(path.suffix in {".html", ".css", ".js"} for path in box.iterdir())


def test_frontend_readme_matches_public_read_only_surface() -> None:
    text = (ROOT / "reweave_frontend" / "README.md").read_text(encoding="utf-8")
    assert "docs/REWEAVE_DESKTOP_STATIC_SHELL.md" not in text
    assert "Open in folder" not in text
    assert "view/open/copy" not in text
    assert "python3 -m http.server 8765" in text
    assert "No frontend apply/export/open-folder write path is exposed." in text


def test_desktop_user_flow_doc_is_linked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_cn = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    doc = ROOT / "docs" / "DESKTOP_USER_FLOW.md"
    assert doc.is_file()
    assert "docs/DESKTOP_USER_FLOW.md" in readme
    assert "docs/DESKTOP_USER_FLOW.md" in readme_cn
    text = doc.read_text(encoding="utf-8")
    assert "Bind Source Box" in text
    assert "Build Small Project Pack" in text
    assert "Real source project writes stay off." in text
