"""Static release checks for Reweave's bridge-first frontend shell."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_locale_copy_is_strictly_partitioned() -> None:
    app = (ROOT / "reweave_frontend" / "app.js").read_text(encoding="utf-8")
    zh_start = app.index("    zh: {")
    en_start = app.index("    en: {")
    end = app.index("  };", en_start)
    zh_block = app[zh_start:en_start]
    en_block = app[en_start:end]
    key_pattern = re.compile(r"^\s{6}([A-Za-z][A-Za-z0-9]*):", re.MULTILINE)

    zh_keys = key_pattern.findall(zh_block)
    en_keys = key_pattern.findall(en_block)
    assert len(zh_keys) == len(set(zh_keys))
    assert len(en_keys) == len(set(en_keys))
    assert set(zh_keys) == set(en_keys)
    assert re.search(r"[\u4e00-\u9fff]", zh_block)
    assert not re.search(r"[\u4e00-\u9fff]", en_block)
    for key in ("welcomeTagline", "bindSourceBox", "generationInput", "readerLabel", "sources"):
        assert f'data-i18n="{key}"' in (ROOT / "reweave_frontend" / "index.html").read_text(encoding="utf-8")


def test_mock_fallback_does_not_present_local_warehouse_workbench() -> None:
    app = (ROOT / "reweave_frontend" / "app.js").read_text(encoding="utf-8")
    bridge = (ROOT / "reweave_frontend" / "bridge.js").read_text(encoding="utf-8")
    renderers = (ROOT / "reweave_frontend" / "renderers.js").read_text(encoding="utf-8")
    artifacts = (ROOT / "reweave_frontend" / "artifacts.js").read_text(encoding="utf-8")
    source_workflow = (ROOT / "reweave_frontend" / "source_workflow.js").read_text(encoding="utf-8")
    capsule_reader = (ROOT / "reweave_frontend" / "capsule_reader.js").read_text(encoding="utf-8")
    frontend = "\n".join([app, bridge, renderers, artifacts, source_workflow, capsule_reader])
    index = (ROOT / "reweave_frontend" / "index.html").read_text(encoding="utf-8")
    mock = (ROOT / "reweave_frontend" / "mock-data.json").read_text(encoding="utf-8")
    styles = (ROOT / "reweave_frontend" / "styles.css").read_text(encoding="utf-8")

    assert (ROOT / "reweave_frontend" / "assets" / "reweave-icon.svg").exists()
    assert 'src="assets/reweave-icon.svg"' in index
    assert '<script src="bridge.js"></script>' in index
    assert '<script src="renderers.js"></script>' in index
    assert '<script src="artifacts.js"></script>' in index
    assert '<script src="source_workflow.js"></script>' in index
    assert '<script src="capsule_reader.js"></script>' in index
    assert index.index('src="bridge.js"') < index.index('src="app.js"')
    assert index.index('src="source_workflow.js"') < index.index('src="app.js"')
    assert index.index('src="capsule_reader.js"') < index.index('src="app.js"')
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
    assert 'data-i18n="welcomeKicker"' in index
    assert "Bind Source Box" in index
    assert 'data-i18n="sourceBoxNote"' in index
    assert 'id="source-box-mode-note"' in index
    assert 'id="btn-view-runtime"' in index
    assert 'placeholder="Source project read-only; local preview enabled"' in index
    assert "GENERATION INPUT" in index
    assert 'id="generation-input-note"' in index
    assert 'id="workflow-status"' in index
    assert 'id="workflow-status"' in index
    assert 'class="generated-title" data-i18n="currentRuntime"' in index
    assert 'class="btn-secondary btn-open-folder hidden"' in index
    assert '<span id="sources-count">0</span> <span data-i18n="bound">bound</span>' in index
    assert "Select old project folder" not in index
    assert "Local · Lumo engine" not in index
    assert "Digesting old project into capsules" not in index
    assert '"cleaningSteps":["Current Runtime / artifacts"]' in index
    assert "function normalizeMockFallback()" in app
    assert 'data.lumoLiteMode = "source_read_only_preview_write";' in app
    assert 'sourceReadOnly: "源项目只读"' in app
    assert 'sourceReadOnly: "Source project read-only"' in app
    assert "function isLumoLiteReadOnly(state, fallbackData)" in bridge
    assert "fallbackData && fallbackData.lumoLiteMode" in bridge
    assert "var bridgeHelpers = window.ReweaveBridgeHelpers || {};" in app
    assert "var renderers = window.ReweaveRenderers || {};" in app
    assert "var artifactRenderers = window.ReweaveArtifacts || {};" in app
    assert "var sourceWorkflow = window.ReweaveSourceWorkflow || {};" in app
    assert "var capsuleReader = window.ReweaveCapsuleReader || {};" in app
    assert "window.ReweaveSourceWorkflow" in source_workflow
    assert "window.ReweaveCapsuleReader" in capsule_reader
    assert "normalizeSource: normalizeSource" in source_workflow
    assert "sourceScanLabel: sourceScanLabel" in source_workflow
    assert "normalizeCapsule: normalizeCapsule" in capsule_reader
    assert "previewText: previewText" in capsule_reader
    assert "sourceWorkflow.normalizeSource" in app
    assert "sourceWorkflow.sourceScanLabel" in app
    assert "capsuleReader.normalizeCapsule" in app
    assert "capsuleReader.previewText" in app
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
    assert 'storeBtn.textContent = t("store");' in app
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
    assert "Intent ready · Plan ready · Quality gate passed · Source writes 0" in renderers
    assert 't("workflowViewProvenance")' in app
    assert "function canBuildTaskPackPreview()" in app
    assert 'els.taskInput.disabled = !taskPackPreview;' in app
    assert 'els.btnGenerate.classList.toggle("hidden", !taskPackPreview);' in app
    assert "Build Small Project Pack" in app
    assert "Small Project Pack ready" in app
    assert 'selectionMode: usedCapsuleIds.length > 0 ? "manual" : "auto_match"' in app
    assert "Generate will use exactly these capsules." in app
    assert ".generation-input-note" in styles
    assert 'openFolder.classList.add("hidden");' in app
    assert 'productSummary: "产品能力：{capability} · 源项目写入：{writes} · 追溯：{trace}"' in app
    assert 'productSummary: "Product capability: {capability} · Source writes: {writes} · Trace: {trace}"' in app
    assert 'responseBits.push("Product base ready");' not in app
    assert 'responseBits.push("Task pack ready");' not in app
    assert "btn-artifact-view" in artifacts
    assert "btn-artifact-copy" in artifacts
    assert "btn-artifact-open" not in frontend
    assert "Opened Lumo Lite artifact." not in frontend
    assert 'data.generatedPackage || { folder: "Current Runtime", files: [] }' in app
    assert 'els.generatedPackage.classList.toggle("runtime-read-only", !hasTaskPackPreview);' in app
    assert 'els.generatedPreview.classList.toggle("hidden", !hasTaskPackPreview);' in app
    assert "Runtime artifacts" in app
    assert "capsules_used / trace receipts" in app
    assert 'name === "task_intent.json"' in renderers
    assert 'name === "task_plan.json"' in renderers
    assert 'name === "quality_gate.json"' in renderers
    assert "capsules linked to this runtime" in app
    assert "No local preview history yet" in app
    assert "show && hasDesktopBridge() && (!isLumoLiteReadOnly() || canBuildTaskPackPreview())" in app
    assert 'els.reweaveResponse.textContent = t("runtimeReadOnlyMessage");' in app
    assert "function blockReadyRender(message)" in app
    assert "if ((isLumoLiteReadOnly() && !canBuildTaskPackPreview()) || !result || result.ok === false)" in app
    assert "openFirstLumoLiteCapsule" not in app
    assert ":focus-visible" in styles
    assert ":focus-within" in styles
    assert 'artifact.kind === "preview_artifact"' in app
    assert 'return !BUILD_NOTE_FILES[name];' in app
    assert "var visibleFiles = userFacingFiles(files);" in app
    assert 'renderers.renderFileTree(t("smallProjectPack") + "/", productFiles, escapeHtml)' in app
    assert 'sidecar.classList.toggle("runtime-sidecar-unavailable", !available);' in app
    assert ".machine-core.sidecar-collapsed" in styles
    assert "width: fit-content;" in styles
    assert "animation: reuse-thread 0.3s ease-out both;" in styles
    assert "animation: result-reveal 0.3s ease-out both;" in styles
    assert "reader-thread-in" not in styles
    assert "reuse-token-path" not in styles
    assert 'window.matchMedia("(prefers-reduced-motion: reduce)").matches' in app
    assert "if (els.usedCount && els.usedCapsuleDock) renderUsedChips();" in app
    assert 'if (e.key !== "Escape") return;' in app
    assert 'if (els.reader && !els.reader.classList.contains("hidden")) hideCapsuleReader();' in app
    assert "@media (min-width: 721px) and (max-height: 760px)" in styles
    assert "grid-template-columns: minmax(0, 1fr) 200px;" in styles
    assert "grid-template-columns: minmax(0, 1fr) 132px;" in styles
    assert ".file-tree .folder," in styles
    assert "overflow-wrap: anywhere;" in styles
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
