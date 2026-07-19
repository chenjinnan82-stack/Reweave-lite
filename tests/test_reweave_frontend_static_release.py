"""Static release checks for Reweave's bridge-first frontend shell."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_quality_status_requires_explicit_gate_result() -> None:
    node = shutil.which("node")
    if not node:
        return
    script = (
        "global.window = {}; require(" + repr(str(ROOT / "reweave_frontend" / "renderers.js")) + ");"
        "const files=['task_intent.json','task_plan.json','quality_gate.json'];"
        "console.log(JSON.stringify([window.ReweaveRenderers.taskPackStatusFromFiles(files),"
        "window.ReweaveRenderers.taskPackStatusFromFiles(files,{status:'passed'})]));"
    )
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
    unknown, passed = json.loads(result.stdout)
    assert "Quality report available" in unknown
    assert "passed" not in unknown.lower()
    assert "Quality gate passed" in passed


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


def test_formal_capsule_selection_is_correctable_and_fail_closed() -> None:
    app = (ROOT / "reweave_frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "reweave_frontend" / "styles.css").read_text(encoding="utf-8")
    validation = app[
        app.index("  function formalSelectionError(") : app.index(
            "\n  function finishGenerate(", app.index("  function formalSelectionError(")
        )
    ]

    assert 'remove.className = "reuse-chip-remove";' in app
    assert 'remove.setAttribute("aria-label", formatText("removeCapsule", { name: cap.name }));' in app
    assert "usedCapsuleIds = usedCapsuleIds.filter(function (selectedId)" in app
    assert ".reuse-chip-remove:focus-visible" in styles
    assert "capsules.length !== ids.length" in validation
    assert "formalCapsules.length !== capsules.length" in validation
    assert "formalCapsules.length > 3" in validation
    assert "currentCapability !== capabilityKey" in validation
    assert "seenKinds[kind]" in validation
    assert "requireDomRole && !seenKinds.presentation && !seenKinds.interaction" in validation
    assert "formalSelectionError(usedCapsuleIds, true)" in app
    assert "formalSelectionError(nextIds, false)" in app


def test_desktop_and_frontend_share_one_qwebchannel_connection_guard() -> None:
    app = (ROOT / "reweave_frontend" / "app.js").read_text(encoding="utf-8")
    desktop = (ROOT / "pimos_lite" / "desktop_reweave_static.py").read_text(
        encoding="utf-8"
    )

    assert "window.__reweaveWebChannelConnecting = true;" in app
    assert "window.__reweaveWebChannelConnecting = false;" in app
    assert desktop.count("window.__reweaveWebChannelConnecting = true;") == 2
    assert desktop.count("window.__reweaveWebChannelConnecting = false;") == 2


def test_management_run_receipts_are_bounded_in_the_frontend() -> None:
    node = shutil.which("node")
    if not node:
        return
    app = (ROOT / "reweave_frontend" / "app.js").read_text(encoding="utf-8")
    start = app.index("  function rememberManagementRun(")
    end = app.index("\n  function pollManagementRun(", start)
    script = "var ingestionManagement = {runs: {}};\n" + app[start:end] + """
for (let i = 0; i < 105; i += 1) {
  rememberManagementRun('done-' + i, {status: 'completed'});
}
rememberManagementRun('live', {status: 'running'});
const before = Object.keys(ingestionManagement.runs);
rememberManagementRun('live', {status: 'completed'});
const after = Object.keys(ingestionManagement.runs);
console.log(JSON.stringify({before, after}));
"""
    result = subprocess.run(
        [node, "-e", script], check=True, capture_output=True, text=True
    )
    rows = json.loads(result.stdout)
    assert len(rows["before"]) == 101
    assert "done-0" not in rows["before"]
    assert "done-5" in rows["before"]
    assert "live" in rows["before"]
    assert len(rows["after"]) == 100
    assert "done-5" not in rows["after"]
    assert "done-6" in rows["after"]
    assert "live" in rows["after"]


def test_capsule_warehouse_defaults_to_compact_simple_mode() -> None:
    app = (ROOT / "reweave_frontend" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "reweave_frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "reweave_frontend" / "styles.css").read_text(encoding="utf-8")
    toggle = re.search(r'<input type="checkbox" id="warehouse-developer-mode"([^>]*)>', index)
    assert toggle is not None
    assert "checked" not in toggle.group(1)
    assert 'data-i18n-title="warehousePurpose"' in index
    assert 'data-i18n-title="discoverSourceHelp"' in index
    assert 'id="warehouse-mode-help"' not in index
    assert 'data-i18n="modelTimeoutNote"' not in index
    assert 'data-i18n-title="modelTimeoutNote"' in index
    assert 'setOptionalTitle(bindBtn, canBind ? "" : t("sourceBoxBindingDisabled"));' in app
    assert 'else element.removeAttribute("title");' in app
    assert 'controlHelp(el, key);' in app
    assert 'bindBtn.title = canBind ? ""' not in app
    assert ".capsule-warehouse-popover:not(.developer-mode) .warehouse-developer-only" in styles
    v2 = app[
        app.index("  function renderJavascriptComputationOffers(") : app.index(
            "\n  function renderManagementProjects(",
            app.index("  function renderJavascriptComputationOffers("),
        )
    ]
    assert 'fieldLabel.className = "warehouse-field";' in v2
    assert 'resultLabel.className = "warehouse-field";' in v2
    assert 'relpathLabel.className = "warehouse-field warehouse-developer-only";' in app
    assert 'displayNameLabel.className = "warehouse-field warehouse-developer-only";' in app
    assert 'button.textContent = String(decision)' not in app
    assert 'process_candidate: ["decisionProcessCandidate", "decisionProcessCandidateHelp"]' in app
    assert "project.selected == null && discovered.length === 1" in app
    assert 'confirmationLabel.title = t("adapterMappingConfirmation");' in v2
    assert 't("adapterMappingConfirmShort")' in v2
    assert 'preview.className = "warehouse-meta warehouse-mapping-preview warehouse-developer-only";' in v2
    assert "var simpleHelp = document.createElement" not in v2
    assert 'preview.setAttribute("aria-live", "polite")' not in v2
    assert 'signatureMeta.className = "warehouse-developer-only warehouse-meta";' in v2
    assert 'formatText("adapterInputSourceLabel"' in v2
    assert 't("adapterInputFieldVisibleHelp")' in v2
    assert 't("adapterResultFieldVisibleHelp")' in v2
    assert 'field.setAttribute("aria-describedby", fieldHelp.id);' in v2
    assert 'resultField.setAttribute("aria-describedby", resultHelp.id);' in v2
    assert 'data-i18n-title="createBackupHelp"' in index
    assert 'data-i18n-title="importLegacyHelp"' in index

    node = shutil.which("node")
    if not node:
        return
    start = app.index("  function captureOutcomeStatusKey(")
    end = app.index("\n  function controlHelp(", start)
    script = app[start:end] + """
console.log(JSON.stringify({
  waiting: captureOutcomeStatusKey({status: 'waiting_user'}),
  waitingModel: captureOutcomeStatusKey({status: 'waiting_model'}),
  waitingValidation: captureOutcomeStatusKey({status: 'waiting_validation'}),
  rejected: captureOutcomeStatusKey({status: 'rejected'}),
  passed: captureOutcomeStatusKey({status: 'review_required'}),
  duplicate: captureOutcomeStatusKey({status: 'duplicate'}),
  unknown: captureOutcomeStatusKey({status: 'mystery'}),
  reviewWaits: captureStatusIsWaiting('captureReviewRequired'),
  rejectionWaits: captureStatusIsWaiting('captureRejected')
}));
"""
    result = subprocess.run(
        [node, "-e", script], check=True, capture_output=True, text=True
    )
    rows = json.loads(result.stdout)
    assert rows == {
        "waiting": "captureNeedsDecision",
        "waitingModel": "captureWaitingModel",
        "waitingValidation": "captureWaitingValidation",
        "rejected": "captureRejected",
        "passed": "captureReviewRequired",
        "duplicate": "captureDuplicate",
        "unknown": "captureOutcomeUnknown",
        "reviewWaits": True,
        "rejectionWaits": False,
    }


def test_javascript_scan_eligibility_is_fail_closed_and_explained() -> None:
    app = (ROOT / "reweave_frontend" / "app.js").read_text(encoding="utf-8")
    assert 'scanJavascriptComputations: "查找可复用的计算功能"' in app
    assert 'scanStatus.textContent = t("scanJavascriptRunning");' in app
    assert 'formatText("scanJavascriptFound", { count: existingOffers.length })' in app
    assert 'scanHelp.textContent = t("scanJavascriptComputationsHelp");' in app
    assert 'scanJavascript.setAttribute("aria-describedby", scanHelp.id + " " + scanStatus.id);' in app
    assert 'row.appendChild(scanStatus);' in app
    status_block = app[
        app.index("      var existingInspection = ingestionManagement.adapterOffers") : app.index(
            '      scanJavascript.setAttribute("aria-describedby"',
            app.index("      var existingInspection = ingestionManagement.adapterOffers"),
        )
    ]
    assert status_block.index("if (!scanEligibility.enabled)") < status_block.index(
        'existingInspection.schema === "computation_capture_offers.v2"'
    )
    assert 'source_unavailable: "projectScanSourceMissing"' in app
    assert 'source_platform_unsupported_v1: "projectScanPlatformUnsupported"' in app

    node = shutil.which("node")
    if not node:
        return
    start = app.index("  function computationScanEligibility(")
    end = app.index("\n  function renderManagementProjects(", start)
    script = app[start:end] + """
const rows = {
  readyJs: computationScanEligibility({project_id: 'js', source_type: 'javascript_computation_source', project_state: 'ready'}),
  readyStatic: computationScanEligibility({project_id: 's1', source_type: 'static_web', project_state: 'ready'}),
  unsupportedStatic: computationScanEligibility({project_id: 's2', source_type: 'static_web', project_state: 'unsupported_v1'}),
  pending: computationScanEligibility({project_id: 's3', source_type: 'static_web', project_state: 'pending_confirmation'}),
  discovered: computationScanEligibility({project_id: 's4', source_type: 'static_web', project_state: 'discovered_unconfirmed'}),
  missing: computationScanEligibility({project_id: 's5', source_type: 'static_web', project_state: 'source_missing'}),
  platform: computationScanEligibility({project_id: 's6', source_type: 'static_web', project_state: 'source_platform_unsupported_v1'}),
  unknownState: computationScanEligibility({project_id: 's7', source_type: 'static_web', project_state: 'mystery'}),
  unknownType: computationScanEligibility({project_id: 's8', source_type: 'mystery', project_state: 'ready'}),
  incomplete: computationScanEligibility({source_type: 'static_web', project_state: 'ready'})
};
console.log(JSON.stringify(rows));
"""
    result = subprocess.run(
        [node, "-e", script], check=True, capture_output=True, text=True
    )
    rows = json.loads(result.stdout)
    assert rows == {
        "readyJs": {"enabled": True, "messageKey": "projectScanReady"},
        "readyStatic": {"enabled": True, "messageKey": "projectScanReady"},
        "unsupportedStatic": {
            "enabled": True,
            "messageKey": "projectScanStaticUnsupported",
        },
        "pending": {"enabled": False, "messageKey": "projectScanPending"},
        "discovered": {"enabled": False, "messageKey": "projectScanPending"},
        "missing": {"enabled": False, "messageKey": "projectScanSourceMissing"},
        "platform": {
            "enabled": False,
            "messageKey": "projectScanPlatformUnsupported",
        },
        "unknownState": {
            "enabled": False,
            "messageKey": "projectScanUnknownState",
        },
        "unknownType": {
            "enabled": False,
            "messageKey": "projectScanUnknownType",
        },
        "incomplete": {
            "enabled": False,
            "messageKey": "projectScanIncomplete",
        },
    }


def test_management_run_failure_reaches_project_row_callback() -> None:
    node = shutil.which("node")
    if not node:
        return
    app = (ROOT / "reweave_frontend" / "app.js").read_text(encoding="utf-8")
    start = app.index("  function pollManagementRun(")
    end = app.index("\n  function inspectAndRestoreBackup(", start)
    script = """
var seen = {refreshed: false};
function bridgeCall() {
  return Promise.resolve(JSON.stringify({
    ok: true,
    data: {run: {status: 'failed', error: {code: 'source_unavailable'}}}
  }));
}
function parseBridgeJson(raw) { return JSON.parse(raw); }
function managementPayload(result) { return result && result.ok !== false ? result.data : null; }
function managementError(result) {
  return result && result.error && result.error.code === 'source_unavailable'
    ? 'projectScanSourceMissing'
    : 'managementOperationFailed';
}
function rememberManagementRun() {}
function renderManagementRuns() {}
function setManagementStatus(key) { seen.global = key; }
function refreshIngestionManagement() { seen.refreshed = true; }
function collectRunIds() { return []; }
""" + app[start:end] + """
pollManagementRun('run-1', null, false, function (key) { seen.row = key; });
setTimeout(function () { console.log(JSON.stringify(seen)); }, 0);
"""
    result = subprocess.run(
        [node, "-e", script], check=True, capture_output=True, text=True
    )
    assert json.loads(result.stdout) == {
        "refreshed": False,
        "global": "projectScanSourceMissing",
        "row": "projectScanSourceMissing",
    }


def test_capability_rename_and_historical_product_diagnostics_are_wired() -> None:
    app = (ROOT / "reweave_frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "reweave_frontend" / "styles.css").read_text(encoding="utf-8")
    popover_start = styles.index(".capsule-warehouse-popover {")
    popover_rule = styles[popover_start : styles.index("\n}", popover_start)]
    meta_start = styles.index(".warehouse-status,\n.warehouse-empty,\n.warehouse-meta {")
    meta_rule = styles[meta_start : styles.index("\n}", meta_start)]
    assert 'bridgeCall(\n          "rename_capability_group"' in app
    assert 'rename.textContent = t("renameCapability");' in app
    assert "details.dataset.historicalProductId" in app
    assert 't("preRestoreBackup")' in app
    assert "retry_product_usage_registration" not in app[
        app.index("ingestionManagement.historicalProducts.forEach") :
        app.index("\n  function renderManagementRuns", app.index("ingestionManagement.historicalProducts.forEach"))
    ]
    assert "overflow-x: hidden;" in popover_rule
    assert "overflow-wrap: anywhere;" in meta_rule


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
    assert "stage4_module_native" not in app
    assert "Current Runtime" in index
    assert 'data-i18n="welcomeKicker"' in index
    assert "Bind Source Box" in index
    assert 'data-i18n="sourceBoxNote"' in index
    assert 'id="source-box-mode-note"' in index
    assert 'id="btn-view-runtime"' in index
    assert 'placeholder="Source project read-only; local preview enabled"' in index
    assert "GENERATION INPUT" in index
    assert 'id="generation-input-note"' in index
    assert 'id="use-local-model"' not in index
    assert "useBoundedLocalModel" not in app
    assert 'id="workflow-status"' in index
    assert 'id="workflow-status"' in index
    assert 'class="generated-title" data-i18n="currentRuntime"' in index
    assert "btn-open-folder" not in index
    assert "btn-export-zip" not in index
    assert "btn-export-copy" not in index
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
    assert "currentPreviewPackageId" not in app
    assert 'if (cap.formal_version) {' in app
    assert 'status === "active" && cap.generation_eligible === true' in app
    assert '!cap.formal_version &&' in app
    assert 'cap.origin === "lumo_lite_capsule_warehouse"' not in app
    assert "formal_version: c.formal_version === undefined ? null : c.formal_version" in capsule_reader
    assert "generation_eligible: c.generation_eligible === true" in capsule_reader
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
    assert 'qualityGate && qualityGate.status === "passed"' in renderers
    assert "data.generatedTraceVerified === true" in app
    assert 't("workflowViewProvenance")' in app
    assert "function canBuildTaskPackPreview()" in app
    assert 'els.taskInput.disabled = !taskPackPreview;' in app
    assert 'els.btnGenerate.classList.toggle("hidden", !taskPackPreview);' in app
    assert "Build Small Project Pack" in app
    assert "Small Project Pack ready" in app
    generate_request = app[
        app.index("  function notifyDesktopGenerate(") : app.index(
            "\n  function applyGenerateResult("
        )
    ]
    assert 'bridgeCall("generate_product", JSON.stringify(payload))' in generate_request
    assert "task: text" in generate_request
    assert "capsule_ids: ids" in generate_request
    assert 'selection_mode: "manual"' in generate_request
    for forbidden in (
        "taskText",
        "capsuleIds",
        "capsules:",
        "sourceBoxes",
        "localModel",
        "origin",
        "validateRuntime",
        "useEnrichedContent",
    ):
        assert forbidden not in generate_request
    assert 'bridgeCall("get_intake_run", JSON.stringify({ run_id: runId }))' in app
    assert 'bridgeCall("notify_generate"' not in app
    assert 'desktopCapability("canGenerateProduct")' in app
    assert 'desktopCapability("canUseBoundedLocalModel")' not in app
    assert "qwen2.5-coder:1.5b" not in app
    assert "resolveGenerateIds" not in app
    assert "Array.isArray(result.capsulesUsed)" in app
    assert "data.generatedPackage.productEntry = result.productEntry;" in app
    assert "var productEntry = pkg.productEntry && pkg.productEntry.path;" in app
    assert 'usedCapsuleSelectionMode = "manual";' in app
    assert "setLocalModelStatus" not in app
    assert "Generate will use exactly these capsules." in app
    assert "Capsule drafts are ready. Review the Source Box and store them." in app
    assert 'var ids = usedCapsuleIds.slice();' in app
    assert 'if (usedCapsuleIds.length === 0)' in app
    assert 'els.reweaveResponse.textContent = t("generationAuto");' in app
    assert "auto_match" not in app
    assert "behaviorModuleCount" not in app
    assert 'id="btn-capsule-warehouse" class="btn-ghost btn-collapsed hidden"' in index
    assert 'id="capsule-warehouse-popover"' in index
    assert index.count('class="warehouse-section') == 6
    assert '<details class="warehouse-section"' in index
    assert "var ingestionManagement = {" in app
    assert 'bridgeCall("list_supervision_models", JSON.stringify({}))' in app
    assert 'bridgeCall("list_review_items", JSON.stringify({}))' in app
    assert 'bridgeCall("list_capability_groups", JSON.stringify({}))' in app
    assert 'bridgeCall("get_capsule_detail", JSON.stringify({ capsule_id: capsule.capsule_id }))' in app
    assert 'bridgeCall("list_backups", JSON.stringify({}))' in app
    assert 'bridgeCall("get_intake_run", JSON.stringify({ run_id: runId }))' in app
    assert '"start_inspect_computation_adapters"' not in app
    assert '"start_create_computation_adapter"' in app
    assert '"start_scan_javascript_computations"' in app
    assert 'bridgeCall("register_javascript_computation_source"' in app
    assert 'data-action", "inspect-computation-adapters"' not in app
    assert 'data-action", "create-computation-adapter"' not in app
    assert 'data-action", "scan-javascript-computations"' in app
    assert 'data-action", "create-javascript-computation-capture"' in app
    assert "function renderComputationAdapterOffers" not in app
    assert "legacyAdapterOutcomeStatusKey" not in app
    assert "computation_adapter_offers.v1" not in app
    assert "旧版候选已过期，请重新扫描。" in app
    assert "This legacy candidate has expired. Scan again" in app
    assert 'adapter_creation_path_retired: "adapterCreationPathRetired"' in app
    assert 'adapter_contract_version_expired: "adapterContractVersionExpired"' in app
    assert "var adapterContractExpired = item.adapter_contract_version_expired === true;" in app
    assert "item && item.adapter_contract_version_expired !== true" in app
    assert "var decisions = adapterContractExpired ? []" in app
    assert "if (!adapterContractExpired && !decisions.length" in app
    assert "parameter_binding_id: control.parameter_binding_id" in app
    assert 'kindName === "boolean"' in app
    assert 'kindName === "enum"' in app
    assert 'resume_contract === "resubmit_ephemeral_capture.v1"' in app
    assert 'review_id: String(resumeReview.value || "") || null' in app
    assert 'String(item.project_id || "") === String(inspection.project_id || "")' in app
    assert "module_relpath: offer.module_relpath" not in app
    assert "target_binding_id: offer.target_binding_id" not in app
    assert "module_relpath: offer.module_relpath" not in app
    assert "function_sha256: offer.function_sha256" not in app
    assert "source_hash: offer.source_hash" not in app
    assert 'bridgeCall("decide_review_item"' in app
    assert 'function managementReviewDecisionPayload(reviewId, decision, controls)' in app
    assert '["capability_key", "role_key", "variant_key", "display_name"]' in app
    assert 'names.push("retained_version_id")' in app
    assert 'names.push("target_capsule_id")' in app
    assert 'bridgeCall("decide_review_item", JSON.stringify(decisionPayload))' in app
    decision_start = app.index("  function managementReviewDecisionPayload(")
    decision_end = app.index("\n  function renderManagementReviews(", decision_start)
    decision_payload = app[decision_start:decision_end]
    assert "source_relpath" not in decision_payload
    assert "source_hash" not in decision_payload
    assert "redaction" not in decision_payload
    model_start = app.index('bridgeCall("select_supervision_model"')
    model_end = app.index("    var backup =", model_start)
    assert "trackManagementRuns(result" in app[model_start:model_end]
    assert 'bridgeCall("inspect_backup"' in app
    assert 'startManagementRun("start_legacy_import"' in app
    assert 'id="warehouse-legacy"' in index
    assert "function createBrandEditor(project)" in app
    assert 'brand_mode: mode.value' in app
    brand_editor_start = app.index("  function createBrandEditor(project)")
    brand_editor_end = app.index("\n  function submitProjectConfirmations(", brand_editor_start)
    brand_editor = app[brand_editor_start:brand_editor_end]
    assert '["inherit", "brandInherit"]' in brand_editor
    assert '["clear", "brandClear"]' in brand_editor
    assert '["replace", "brandReplace"]' in brand_editor
    assert '"extend"' not in brand_editor
    assert "function renderManagementLegacy()" in app
    assert 'legacy_capsule_id: alias.legacy_capsule_id' in app
    assert 'relationship: relationship.value' in app
    assert 'capsule_id: selected.capsule_id' in app
    assert 'version_id: selected.version_id' in app
    assert 'legacy.status' in app
    assert 'legacy.path' in app
    legacy_start = app.index("  function renderManagementLegacy()")
    legacy_end = app.index("\n  function renderManagementBackups()", legacy_start)
    legacy_ui = app[legacy_start:legacy_end]
    assert "alias.eligible_targets" in legacy_ui
    assert "ingestionManagement.capabilityGroups" not in legacy_ui
    management_start = app.index("  function managementPayload(")
    management_end = app.index("\n  function addBoundSource(", management_start)
    management = app[management_start:management_end]
    assert "data.capsules" not in management
    assert "usedCapsuleIds" not in management
    assert "notifyDesktopGenerate" not in management
    welcome_start = app.index("  function initWelcome() {")
    welcome_end = app.index("\n  function startCleaning()", welcome_start)
    welcome = app[welcome_start:welcome_end]
    assert "cacheElements();" in welcome
    assert "bindMainEvents();" in welcome
    assert ".generation-input-note" in styles
    assert "open_preview_folder" not in app
    assert "handleExportPreviewPackage" not in app
    assert 'productSummary: "产品能力：{capability} · 源项目写入：{writes} · 追溯：{trace}"' in app
    assert 'productSummary: "Product capability: {capability} · Source writes: {writes} · Trace: {trace}"' in app
    assert "可生成小项目包预览 · 尚无历史验收 · 源项目写入：0" in app
    assert "Task Pack preview available · No acceptance history yet · Source writes: 0" in app
    assert "previewReadyWithoutHistory" in app
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
    assert "Session history" in app
    assert "CAPSULES_VISIBLE" not in app
    assert 'id="btn-open-capsule"' not in index
    assert "show && hasDesktopBridge() && canGenerateProduct()" in app
    assert 'els.reweaveResponse.textContent = t("runtimeReadOnlyMessage");' in app
    assert "function blockReadyRender(message)" in app
    assert "function previewAcceptanceText(acceptance)" in app
    assert 'acceptance.reason === "react_runtime_verified"' in app
    assert 'acceptance.reason === "react_runtime_failed"' in app
    assert 'acceptance.reason === "real_qwebengine_product_bootstrap"' in app
    assert "完整交互仍需验收" in app
    assert "full interaction still needs review" in app
    assert 'lastReactPreview ? t("reactRuntimeVerified") : previewText' in app
    assert "previewAcceptanceText(payload.previewAcceptance)" in app
    assert "lastPreviewAcceptance = result.previewAcceptance || null;" in app
    assert 'acceptanceUsable: "可用 · 交互行为已验证"' in app
    assert 'acceptanceUsable: "Usable · Interaction verified"' in app
    acceptance_formatter = app[app.index("  function previewAcceptanceText("):app.index("\n  function showScreen(")]
    assert "taskPack" not in acceptance_formatter
    assert ".quality_gate" not in acceptance_formatter
    assert ".behavior_reuse" not in acceptance_formatter
    assert "result && result.previewAcceptance" in app
    assert "openFirstLumoLiteCapsule" not in app
    assert ":focus-visible" in styles
    assert ":focus-within" in styles
    assert 'artifact.kind === "preview_artifact"' in app
    assert '"behavior_contract.json": true' in app
    assert '"behavior_adaptation.json": true' in app
    assert '"behavior_validation.json": true' in app
    assert '"project_graph.json": true' in app
    assert '"react_compile.json": true' in app
    assert '"react_runtime_validation.json": true' in app
    assert "function renderGeneratedPreview()" in app
    assert 'runtimeValidation.preview_image === "react_project/dist/preview.png"' in app
    assert "React app · Runtime verified" in app
    assert ".react-preview-image" in styles
    assert 'return !BUILD_NOTE_FILES[name];' in app
    assert "var visibleFiles = userFacingFiles(files);" in app
    assert "var generatedTraceAvailable =" in app
    assert "hasTaskPackPreview || summary.preview_ready" in app
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


def test_desktop_frontend_declares_local_only_content_policy() -> None:
    index = (ROOT / "reweave_frontend" / "index.html").read_text(encoding="utf-8")
    desktop = (ROOT / "pimos_lite" / "desktop_reweave_static.py").read_text(encoding="utf-8")

    assert "Content-Security-Policy" in index
    assert "connect-src 'none'" in index
    assert "frame-src 'none'" in index
    assert "LocalContentCanAccessRemoteUrls, False" in desktop
    assert "DnsPrefetchEnabled, False" in desktop
    assert "JavascriptCanOpenWindows, False" in desktop
    assert "acceptNavigationRequest" in desktop
    assert "LocalFrontendRequestInterceptor" in desktop
    assert 'new URLSearchParams(window.location.search).get("desktop") === "1"' in (ROOT / "reweave_frontend" / "app.js").read_text(encoding="utf-8")


def test_static_web_target_ui_is_review_only_and_fail_closed() -> None:
    app = (ROOT / "reweave_frontend" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "reweave_frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "reweave_frontend" / "styles.css").read_text(encoding="utf-8")

    for element_id in (
        "btn-open-target",
        "screen-target",
        "btn-target-back",
        "target-developer-mode",
        "target-capsule-cards",
        "target-file-diffs",
        "target-rejection-evidence",
        "btn-confirm-target-patch",
        "target-confirmation-receipt",
    ):
        assert f'id="{element_id}"' in index
    toggle = re.search(r'<input type="checkbox" id="target-developer-mode"([^>]*)>', index)
    assert toggle is not None
    assert "checked" not in toggle.group(1)
    assert ".target-developer-only" in styles
    assert ".screen-target.developer-mode .target-developer-only" in styles

    bridge_guard = app[
        app.index("  function hasTargetBridge(") : app.index(
            "\n  function ", app.index("  function hasTargetBridge(") + 1
        )
    ]
    for method in (
        "choose_static_web_target",
        "analyze_static_web_target",
        "generate_static_web_patch",
    ):
        assert method in bridge_guard
    assert 'bridgeCall("analyze_static_web_target", JSON.stringify(payload))' in app
    assert 'bridgeCall("generate_static_web_patch", JSON.stringify(payload))' in app
    assert "targetWorkflow.profileRevision += 1" in app
    assert "targetWorkflow.patchRevision += 1" in app
    analyze = app[
        app.index("  function handleAnalyzeStaticWebTarget(") : app.index(
            "\n  function handleGenerateStaticWebPatch(",
            app.index("  function handleAnalyzeStaticWebTarget("),
        )
    ]
    generate = app[
        app.index("  function handleGenerateStaticWebPatch(") : app.index(
            "\n  function handleConfirmTargetPatch(",
            app.index("  function handleGenerateStaticWebPatch("),
        )
    ]
    assert "requestRevision !== targetWorkflow.profileRevision" in analyze
    assert "requestRevision !== targetWorkflow.patchRevision" in generate

    safe_profile = app[
        app.index("  function isSafeTargetProfile(") : app.index(
            "\n  function ", app.index("  function isSafeTargetProfile(") + 1
        )
    ]
    assert "profile.schema_version" in safe_profile
    assert '"static_web_target_profile.v1"' in safe_profile
    assert 'patch.schema_version !== "static_web_target_patch.v1"' in app
    assert 'patch.status !== "ready_for_review"' in app
    assert 'patch.strategy !== "static_web_iframe_embed.v1"' in app
    assert 'authorization.mode !== "review_patch_only"' in app
    assert 'targetExactObject(profile, [' in app
    assert 'targetExactObject(patch, [' in app
    for write_flag in (
        "target_project_write",
        "apply",
        "commit",
        "product_store_write",
        "usage_registration_write",
    ):
        assert write_flag in app

    confirm_start = app.index("  function handleConfirmTargetPatch(")
    confirm_end = app.index("\n  function ", confirm_start + 1)
    confirmation = app[confirm_start:confirm_end]
    assert "bridgeCall(" not in confirmation
    assert "targetWorkflow.confirmation =" in confirmation
    assert "planId" in confirmation
    assert "snapshotSha256" in confirmation

    render_start = app.index("  function renderTargetPatch(")
    render_end = app.index("\n  function renderTargetError(", render_start)
    patch_render = app[render_start:render_end]
    assert ".textContent = change.diff" in patch_render
    assert 'change.content_encoding === "utf-8"' in patch_render
    assert 'binary.textContent = t("targetBinaryDiff")' in patch_render
    assert "after_content" not in patch_render
    assert "innerHTML" not in patch_render

    error_start = render_end
    error_end = app.index("\n  function ", error_start + 1)
    error_render = app[error_start:error_end]
    assert "targetRejectionEvidence.textContent" in error_render
    assert "rawEvidence.logical_path" in error_render
    assert "rawEvidence.target_path" not in error_render
    assert "innerHTML" not in error_render
    profile_projection = app[
        app.index("  function targetProfileDeveloperEvidence(") : app.index(
            "\n  function renderTargetProfile(",
            app.index("  function targetProfileDeveloperEvidence("),
        )
    ]
    assert "files: profile.files.map" in profile_projection
    assert "files: profile.files," not in profile_projection
    patch_projection = app[
        app.index("  function targetPatchDeveloperEvidence(") : app.index(
            "\n  function renderTargetPatch(",
            app.index("  function targetPatchDeveloperEvidence("),
        )
    ]
    assert "authorization: patch.authorization" not in patch_projection
    assert "weave_plan: patch.weave_plan" not in patch_projection
    assert "composer: patch.composer" not in patch_projection
    assert 'targetBack.addEventListener("click", showStandaloneProduct)' in app
    capsule_render = app[
        app.index("  function renderTargetCapsules(") : app.index(
            "\n  function appendTargetMetric(",
            app.index("  function renderTargetCapsules("),
        )
    ]
    assert "resetTargetPatch();" in capsule_render
    assert ".after_content" not in app
    for forbidden_method in (
        "apply_static_web_patch",
        "commit_static_web_patch",
        "write_static_web_target",
    ):
        assert forbidden_method not in app


def test_static_web_target_ui_acceptance_keeps_confirmation_review_only() -> None:
    report = json.loads(
        (ROOT / "docs" / "reports" / "REWEAVE_STATIC_WEB_TARGET_UI_ACCEPTANCE.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["schema_version"] == "reweave_static_web_target_ui_acceptance.v1"
    assert report["verdict"] == "PASS"
    assert report["desktop_flow"]["acceptance_scope"] == (
        "real_qwebengine_with_stubbed_plan3_service_contract"
    )
    assert report["confirmation"] == {
        "kind": "in_memory_review_receipt",
        "bound_to_plan_id": True,
        "bound_to_target_snapshot_sha256": True,
        "bridge_call": False,
        "write_authorization": False,
        "invalidated_by_input_change": True,
    }
    assert all(value is False for key, value in report["zero_writes"].items() if key != "target_tree_unchanged")
    assert report["zero_writes"]["target_tree_unchanged"] is True
    assert report["scope_limit"]["qt_service_is_stubbed"] is True
    assert report["scope_limit"]["release_tag_moved"] is False


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


def test_stage4_desktop_preview_uses_runtime_review_copy() -> None:
    source = (ROOT / "reweave_frontend" / "app.js").read_text(encoding="utf-8")

    assert 'acceptance.reason === "desktop_runtime_validation_required"' in source
    assert 'generatedFiles.indexOf("composition_plan.json") >= 0' not in source
    assert 'generatedFiles.indexOf("adapter_mapping.json") >= 0' not in source
    assert "data.generatedTraceVerified === true" in source
    assert '"composition_plan.json": true' in source
    assert '"adapter_mapping.json": true' in source
    assert 'bridgeCall("open_generated_product")' in source
    view_handler = source[
        source.index("  function handleViewPreviewPackage()") : source.index(
            "\n  function handleComparePreviewPackages()"
        )
    ]
    assert "get_latest_preview_package" not in view_handler
    assert "stage4_behavior_composition_preview" not in source
    assert 'comparePackage.classList.add("hidden")' in source
