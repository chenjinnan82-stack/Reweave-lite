(function () {
  "use strict";

  var data = null;
  var selectedCapsuleId = null;
  var usedCapsuleIds = [];
  var appState = "idle";
  var CAPSULES_VISIBLE = 5;
  var isGenerating = false;
  var mainEventsBound = false;
  var locale = localStorage.getItem("reweave_locale") || "zh";
  var lastPreviewAcceptance = null;

  var STR = {
    zh: {
      privacy: "本地运行，数据不会离开此设备。",
      history: "历史",
      artifacts: "构建资料",
      welcomeKicker: "来源箱 · 当前运行状态 · 构建资料",
      welcomeTagline: "绑定一个旧项目文件夹，将其整理为可复用胶囊。",
      welcomePhilosophy: "不是复制，是消化后再织。",
      sourceBox: "来源箱",
      bindSourceBox: "绑定来源箱",
      sourceBoxNote: "选择一个旧项目文件夹，整理为胶囊。",
      sourceBoxReadOnlyNote: "本地绑定、只读扫描，不写入源项目。",
      sourceBoxBindingDisabled: "来源箱绑定尚未开放。",
      viewCurrentRuntime: "查看当前运行状态",
      cleaningRuntime: "正在载入运行状态与构建资料",
      capsules: "胶囊",
      taskPlaceholder: "描述你想从旧项目重新织出的页面或工具…",
      taskPackPlaceholder: "描述你想生成的小项目包…",
      runtimePlaceholder: "源项目只读，本地预览可写",
      buildSmallProjectPack: "生成小项目包",
      generationInput: "生成输入",
      usedPlaceholder: "选中的胶囊会出现在这里",
      generationAuto: "未手动选择时，系统会自动匹配胶囊。",
      generationManual: "已选择 {count} 个胶囊；本次生成只使用这些胶囊。",
      generationResolved: "系统已匹配 {count} 个胶囊。",
      draftsReadyStore: "胶囊草稿已就绪，请在来源箱中确认入仓。",
      selecting: "正在选择胶囊…",
      readyResponse: "已使用 {count} 个胶囊生成本地项目预览。",
      acceptanceUsable: "可用 · 交互行为已验证",
      acceptanceNeedsBehavior: "需复核 · 未找到完整行为模块",
      acceptanceNeedsQuality: "需复核 · 质量检查结果缺失",
      acceptanceNeedsRuntime: "需复核 · 等待运行验证",
      acceptanceRejected: "已拒绝 · 质量检查未通过",
      acceptanceRejectedRuntime: "已拒绝 · 交互行为验证失败",
      generationFailed: "生成失败，请检查任务和胶囊状态。",
      taskPackUnavailable: "小项目包预览当前不可用。",
      localPreview: "本地预览",
      newTask: "新任务",
      docked: "已加入本次任务。",
      openFolder: "已打开本地预览文件夹。",
      openFolderMock: "当前仅支持本地预览。",
      useInTask: "用于任务",
      openCapsule: "查看胶囊",
      readOnly: "只读",
      sourceReadOnly: "源项目只读",
      capsulesUsed: "个胶囊已使用",
      readerLabel: "胶囊详情",
      fromSource: "来源",
      tagsPrefix: "标签",
      rolePrefix: "选用原因",
      preview: "预览",
      previewStatus: "预览状态",
      status: "状态",
      currentRuntime: "当前运行状态",
      runtime: "运行状态",
      smallProjectPack: "小项目包",
      runtimeArtifacts: "运行资料",
      runtimeTraceFiles: "胶囊使用记录 / 追溯凭证",
      workflow: "工作流",
      traceAvailable: "追溯可用",
      traceUnavailable: "追溯不可用",
      previewReady: "预览已就绪",
      previewNotReady: "预览未就绪",
      smallProjectPackReady: "小项目包已就绪",
      capsulesLinked: "当前运行状态关联了 {count} 个胶囊",
      noCapsuleUsage: "当前运行状态未报告胶囊使用记录",
      productSummary: "产品能力：{capability} · 源项目写入：{writes} · 追溯：{trace}",
      capabilityReady: "就绪",
      capabilityReview: "需复核",
      capabilityUnavailable: "不可用",
      previewReadyNoAcceptance: "可生成小项目包预览 · 尚无历史验收 · 源项目写入：0",
      sourceWrites: "源项目写入",
      trace: "追溯",
      ready: "就绪",
      unavailable: "不可用",
      notReady: "未就绪",
      unknown: "未知",
      workflowViewProvenance: "查看来源记录",
      workflowBindSource: "绑定来源箱",
      workflowScanSource: "扫描来源箱",
      workflowStoreCapsules: "胶囊入仓",
      workflowBuildPack: "选择胶囊，然后生成小项目包",
      workflowIntentReady: "任务意图就绪 · 计划就绪 · 质量门通过 · 源项目写入 0",
      workflowPackReady: "小项目包就绪 · 源项目写入 0",
      viewPackage: "查看项目包",
      compareLast: "对比上次结果",
      sources: "来源箱",
      bound: "已绑定",
      addSource: "添加来源箱",
      lastUsed: "最近使用：2 天前",
      previewPackage: "预览项目包",
      close: "关闭",
      switchLanguage: "切换语言",
      noHistoryReadOnly: "暂无本地预览历史",
      noHistory: "暂无历史",
      historyMeta: "使用了 {count} 个胶囊 · {note}",
      scan: "扫描",
      store: "入仓",
      prepare: "准备",
      sourcePreparing: "准备中…",
      sourceScanning: "扫描中…",
      sourceReady: "就绪",
      sourceScanned: "已扫描",
      sourceFailed: "失败",
      sourceNotScanned: "未扫描",
      artifactCopied: "构建资料路径已复制。",
      runtimeReadOnlyMessage: "源项目只读；本地预览写入已启用。",
      capsuleReadOnlyMessage: "该胶囊为只读状态。",
      loadFailed: "加载本地演示数据失败，请通过桌面程序或本地服务运行。",
      noPreviewPackage: "暂无预览项目包。",
      noPreviousPackage: "暂无可对比的历史项目包。",
      lunaPackIndexed: "Luna 索引已就绪",
      contentAwarePreview: "内容感知预览",
      snippets: "摘录",
      viewContent: "查看内容",
      enrichContent: "补充内容",
      copied: "已复制",
      enrichedContentPreview: "使用补充内容预览",
      localModelRefinement: "本地模型优化",
      localModelOff: "关闭",
      localModelReady: "就绪",
      localModelRunning: "处理中",
      localModelApplied: "已应用",
      localModelFallback: "已回退",
      openFolderButton: "打开文件夹",
      exportZip: "导出 ZIP",
      exportCopy: "导出副本",
      warnings: "警告",
      truncated: "已截断",
      redacted: "已脱敏",
      verify: "验证",
      review: "复核",
      promote: "提升",
      exported: "已导出",
      approve: "通过",
      reject: "拒绝",
      defer: "稍后处理",
      promoted: "已提升",
      pending: "待处理",
      approved: "已通过",
      rejected: "已拒绝",
      deferred: "已延后",
    },
    en: {
      privacy: "All local. Nothing leaves your machine.",
      history: "History",
      artifacts: "Build notes",
      welcomeKicker: "Source Box · Current Runtime · Build notes",
      welcomeTagline: "Bind an old project folder and clean it into reusable capsules.",
      welcomePhilosophy: "Digest first, then reweave.",
      sourceBox: "Source Box",
      bindSourceBox: "Bind Source Box",
      sourceBoxNote: "Choose an old project folder to clean into capsules.",
      sourceBoxReadOnlyNote: "Bind locally, scan read-only, no source writes.",
      sourceBoxBindingDisabled: "Source Box binding is not enabled.",
      viewCurrentRuntime: "View Current Runtime",
      cleaningRuntime: "Loading runtime and build notes",
      capsules: "Capsules",
      taskPlaceholder: "Describe the tool or page to reweave...",
      taskPackPlaceholder: "Describe a small project pack...",
      runtimePlaceholder: "Source project read-only; local preview enabled",
      buildSmallProjectPack: "Build Small Project Pack",
      generationInput: "Generation input",
      usedPlaceholder: "Selected capsules dock here",
      generationAuto: "Generate will auto-pick capsules if none are selected.",
      generationManual: "Generation input: {count} selected. Generate will use exactly these capsules.",
      generationResolved: "Reweave matched {count} capsules.",
      draftsReadyStore: "Capsule drafts are ready. Review the Source Box and store them.",
      selecting: "Reweave is selecting capsules…",
      readyResponse: "Reweave used {count} capsules and prepared a local preview package.",
      acceptanceUsable: "Usable · Interaction verified",
      acceptanceNeedsBehavior: "Needs review · No closed behavior module",
      acceptanceNeedsQuality: "Needs review · Quality result missing",
      acceptanceNeedsRuntime: "Needs review · Runtime validation required",
      acceptanceRejected: "Rejected · Quality check failed",
      acceptanceRejectedRuntime: "Rejected · Interaction validation failed",
      generationFailed: "Generation failed. Check the task and capsule state.",
      taskPackUnavailable: "Task Pack preview is unavailable.",
      localPreview: "local preview",
      newTask: "New task",
      docked: "docked for this task.",
      openFolder: "Opened local preview folder.",
      openFolderMock: "Local preview only.",
      useInTask: "Use in task",
      openCapsule: "Open capsule",
      readOnly: "Read-only",
      sourceReadOnly: "Source project read-only",
      capsulesUsed: "capsules used",
      readerLabel: "Capsule Reader",
      fromSource: "from",
      tagsPrefix: "tags",
      rolePrefix: "role",
      preview: "Preview",
      previewStatus: "Preview status",
      status: "Status",
      currentRuntime: "Current Runtime",
      runtime: "Runtime",
      smallProjectPack: "Small Project Pack",
      runtimeArtifacts: "Runtime artifacts",
      runtimeTraceFiles: "capsules_used / trace receipts",
      workflow: "Workflow",
      traceAvailable: "Trace available",
      traceUnavailable: "Trace unavailable",
      previewReady: "Preview ready",
      previewNotReady: "Preview not ready",
      smallProjectPackReady: "Small Project Pack ready",
      capsulesLinked: "{count} capsules linked to this runtime",
      noCapsuleUsage: "No capsule usage reported by current runtime",
      productSummary: "Product capability: {capability} · Source writes: {writes} · Trace: {trace}",
      capabilityReady: "ready",
      capabilityReview: "review",
      capabilityUnavailable: "unavailable",
      previewReadyNoAcceptance: "Task Pack preview available · No acceptance history yet · Source writes: 0",
      sourceWrites: "source writes",
      trace: "trace",
      ready: "ready",
      unavailable: "unavailable",
      notReady: "not ready",
      unknown: "unknown",
      workflowViewProvenance: "View provenance",
      workflowBindSource: "Bind Source Box",
      workflowScanSource: "Scan Source Box",
      workflowStoreCapsules: "Store Capsules",
      workflowBuildPack: "Select capsules, then Build Small Project Pack",
      workflowIntentReady: "Intent ready · Plan ready · Quality gate passed · Source writes 0",
      workflowPackReady: "Task Pack ready · Source writes 0",
      viewPackage: "View package",
      compareLast: "Compare last",
      sources: "Sources",
      bound: "bound",
      addSource: "Add source",
      lastUsed: "Last used 2d ago",
      previewPackage: "Preview package",
      close: "Close",
      switchLanguage: "Switch language",
      noHistoryReadOnly: "No local preview history yet",
      noHistory: "No history yet",
      historyMeta: "used {count} capsules · {note}",
      scan: "Scan",
      store: "Store",
      prepare: "Prepare",
      sourcePreparing: "Preparing…",
      sourceScanning: "Scanning…",
      sourceReady: "Ready",
      sourceScanned: "Scanned",
      sourceFailed: "Failed",
      sourceNotScanned: "Not scanned",
      artifactCopied: "Artifact path copied.",
      runtimeReadOnlyMessage: "Source project read-only; local preview writes enabled.",
      capsuleReadOnlyMessage: "This capsule is read-only.",
      loadFailed: "Failed to load local demo data. Run the desktop app or a local server.",
      noPreviewPackage: "No preview package is available.",
      noPreviousPackage: "No previous package is available.",
      lunaPackIndexed: "Luna pack indexed",
      contentAwarePreview: "Content-aware preview",
      snippets: "Snippets",
      viewContent: "View content",
      enrichContent: "Enrich content",
      copied: "Copied",
      enrichedContentPreview: "Use enriched content preview",
      localModelRefinement: "Local model refinement",
      localModelOff: "Off",
      localModelReady: "Ready",
      localModelRunning: "Running",
      localModelApplied: "Applied",
      localModelFallback: "Fallback",
      openFolderButton: "Open in folder",
      exportZip: "Export zip",
      exportCopy: "Export copy",
      warnings: "Warnings",
      truncated: "truncated",
      redacted: "redacted",
      verify: "Verify",
      review: "Review",
      promote: "Promote",
      exported: "Exported",
      approve: "Approve",
      reject: "Reject",
      defer: "Defer",
      promoted: "Promoted",
      pending: "Pending",
      approved: "Approved",
      rejected: "Rejected",
      deferred: "Deferred",
    },
  };

  var els = {};
  var desktopBridge = null;
  var bridgeReady = false;
  var desktopShellState = null;
  var scanningSourceIds = {};
  var preparingSourceIds = {};
  var verifyingSourceIds = {};
  var previewingSourceIds = {};
  var reviewingSourceIds = {};
  var lastPreviewPath = "";
  var pendingGeneratePromise = null;
  var useEnrichedContentPreview = false;
  var useBoundedLocalModel = false;
  var usedCapsuleSelectionMode = "manual";
  var currentPreviewPackageId = "";
  var previewViewerMode = "view";
  var lumoLiteArtifacts = [];
  var BUILD_NOTE_FILES = {
    "PREVIEW_README.md": true,
    "behavior_adaptation.json": true,
    "behavior_contract.json": true,
    "behavior_validation.json": true,
    "capsules_used.json": true,
    "frontend_runtime_state.json": true,
    "provenance.json": true,
    "quality_gate.json": true,
    "snippets_used.json": true,
    "summary.md": true,
    "task_intent.json": true,
    "task_pack.json": true,
    "task_plan.json": true,
  };
  var bridgeHelpers = window.ReweaveBridgeHelpers || {};
  var renderers = window.ReweaveRenderers || {};
  var artifactRenderers = window.ReweaveArtifacts || {};
  var sourceWorkflow = window.ReweaveSourceWorkflow || {};
  var capsuleReader = window.ReweaveCapsuleReader || {};

  function $(id) {
    return document.getElementById(id);
  }

  function parseBridgeJson(raw) {
    return bridgeHelpers.parseBridgeJson ? bridgeHelpers.parseBridgeJson(raw) : null;
  }

  function hasDesktopBridge() {
    return !!(desktopBridge && typeof desktopBridge.choose_source_folder === "function");
  }

  function desktopCapability(name) {
    return bridgeHelpers.desktopCapability
      ? bridgeHelpers.desktopCapability(desktopShellState, name)
      : false;
  }

  function isLumoLiteReadOnly() {
    return bridgeHelpers.isLumoLiteReadOnly
      ? bridgeHelpers.isLumoLiteReadOnly(desktopShellState, data)
      : false;
  }

  function isLumoLiteState(state) {
    return bridgeHelpers.isLumoLiteState ? bridgeHelpers.isLumoLiteState(state) : false;
  }

  function canBuildTaskPackPreview() {
    return bridgeHelpers.canBuildTaskPackPreview
      ? bridgeHelpers.canBuildTaskPackPreview(desktopShellState, data)
      : false;
  }

  function clearLumoLiteMockState() {
    delete data.generatedPackage;
    delete data.lastPreview;
    delete data.previewPath;
    data.history = [];
    data.sampleTask = "";
    lastPreviewPath = "";
    currentPreviewPackageId = "";
  }

  function normalizeMockFallback() {
    data.sourceBoxes = [];
    data.capsules = [];
    data.warehouseCapsules = [];
    data.generateCapsuleIds = [];
    data.history = [];
    data.sampleTask = "";
    data.lumoLiteMode = "source_read_only_preview_write";
    data.lumoLiteRuntimeSummary = {
      line: "Source project read-only / local preview enabled",
      capsules_used: 0,
      preview_ready: false,
      trace_available: false,
      product_capability_line: "Product capability: unavailable · Source writes: 0 · Trace unavailable",
      product_base_status: "",
      task_pack_status: "",
    };
    data.cleaningSteps = ["Current Runtime / artifacts"];
    data.generatedPackage = {
      folder: "",
      files: [],
      stats: {
        capsulesUsed: 0,
        preview: "Current Runtime / artifacts",
        provenance: "Trace unavailable without Lumo Lite runtime",
      },
    };
  }

  function syncSourceControls() {
    var addSourceBtn = document.querySelector(".btn-add-source");
    if (!addSourceBtn) return;
    var allowed = hasDesktopBridge() && desktopCapability("canChooseSourceFolder");
    addSourceBtn.disabled = !allowed;
    addSourceBtn.classList.toggle("hidden", !allowed);
  }

  function syncWelcomeSourceBoxMode() {
    var bindBtn = $("btn-select-folder");
    var note = $("source-box-mode-note");
    var runtimeBtn = $("btn-view-runtime");
    if (!bindBtn) return;
    var readOnly = hasDesktopBridge() && isLumoLiteReadOnly();
    var canBind = !hasDesktopBridge() || desktopCapability("canChooseSourceFolder");
    bindBtn.textContent = t("bindSourceBox");
    bindBtn.disabled = !canBind;
    bindBtn.setAttribute("aria-disabled", canBind ? "false" : "true");
    bindBtn.title = canBind ? "" : t("sourceBoxBindingDisabled");
    if (note) {
      note.textContent = readOnly ? t("sourceBoxReadOnlyNote") : t("sourceBoxNote");
    }
    if (runtimeBtn) runtimeBtn.classList.toggle("hidden", !readOnly);
  }

  function getLumoLiteRuntimeSummary() {
    if (desktopShellState && desktopShellState.lumoLiteRuntimeSummary) {
      return desktopShellState.lumoLiteRuntimeSummary;
    }
    return data && data.lumoLiteRuntimeSummary ? data.lumoLiteRuntimeSummary : null;
  }

  function lumoPreviewFiles() {
    var seen = {};
    return lumoLiteArtifacts.reduce(function (files, artifact) {
      var name = artifact && artifact.kind === "preview_artifact" ? String(artifact.basename || "") : "";
      if (name && !seen[name]) {
        seen[name] = true;
        files.push(name);
      }
      return files;
    }, []);
  }

  function userFacingFiles(files) {
    return (Array.isArray(files) ? files : []).filter(function (name) {
      return !BUILD_NOTE_FILES[name];
    });
  }

  function applyLumoLiteRuntimeView() {
    if (!els.taskInput) return;
    if (!isLumoLiteReadOnly()) {
      setRuntimeSidecarAvailable(false);
      return;
    }
    var summary = getLumoLiteRuntimeSummary() || {};
    var taskPackPreview = canBuildTaskPackPreview();
    if (els.btnLumoArtifacts) {
      els.btnLumoArtifacts.classList.toggle("hidden", lumoLiteArtifacts.length === 0);
    }
    var artifactFiles = lumoPreviewFiles();
    var productFiles = userFacingFiles(artifactFiles);
    var generatedFiles = data.generatedPackage && Array.isArray(data.generatedPackage.files)
      ? data.generatedPackage.files
      : [];
    var hasTaskPackPreview =
      taskPackPreview &&
      (productFiles.length > 0 ||
        (!!lastPreviewPath &&
          generatedFiles.indexOf("task_pack.json") >= 0));
    var generatedTraceAvailable =
      hasTaskPackPreview &&
      generatedFiles.indexOf("capsules_used.json") >= 0 &&
      generatedFiles.indexOf("provenance.json") >= 0;
    var traceAvailable = !!summary.trace_available || generatedTraceAvailable;
    var capsulesUsed = hasTaskPackPreview ? usedCapsuleIds.length : Number(summary.capsules_used || 0);
    var traceText = traceAvailable ? t("traceAvailable") : t("traceUnavailable");
    var previewText = hasTaskPackPreview
      ? t("smallProjectPackReady")
      : summary.preview_ready
        ? t("previewReady")
        : t("previewNotReady");
    var sourceWrites = summary.source_project_write_count;
    var previewReadyWithoutHistory = taskPackPreview && !summary.status && !summary.trace_available;
    if (previewReadyWithoutHistory || hasTaskPackPreview) sourceWrites = 0;
    if (sourceWrites === undefined || sourceWrites === null || sourceWrites === "") sourceWrites = t("unknown");
    setRuntimeSidecarAvailable(
      !!(summary.status || summary.preview_ready || traceAvailable || sourceWrites === 0)
    );
    var capability =
      lastPreviewAcceptance && hasTaskPackPreview
        ? lastPreviewAcceptance.verdict === "usable"
          ? t("capabilityReady")
          : lastPreviewAcceptance.verdict === "needs_review"
            ? t("capabilityReview")
            : t("capabilityUnavailable")
        : sourceWrites === 0 && traceAvailable
          ? t("capabilityReady")
        : summary.status
          ? t("capabilityReview")
          : t("capabilityUnavailable");
    var responseText = lastPreviewAcceptance && hasTaskPackPreview
      ? previewAcceptanceText(lastPreviewAcceptance)
      : previewReadyWithoutHistory
      ? t("previewReadyNoAcceptance")
      : formatText("productSummary", {
          capability: capability,
          writes: sourceWrites,
          trace: traceAvailable ? t("ready") : t("unavailable"),
        });

    if (!taskPackPreview) els.taskInput.value = "";
    els.taskInput.placeholder = taskPackPreview ? t("taskPackPlaceholder") : t("runtimePlaceholder");
    els.taskInput.disabled = !taskPackPreview;
    if (els.btnGenerate) {
      els.btnGenerate.disabled = !taskPackPreview;
      els.btnGenerate.setAttribute("aria-disabled", taskPackPreview ? "false" : "true");
      els.btnGenerate.title = taskPackPreview ? t("buildSmallProjectPack") : t("runtimeReadOnlyMessage");
      els.btnGenerate.classList.toggle("hidden", !taskPackPreview);
    }
    if (els.generatedPackage) {
      els.generatedPackage.classList.toggle("runtime-read-only", !hasTaskPackPreview);
    }
    var title = document.querySelector(".generated-title");
    if (title) title.textContent = hasTaskPackPreview ? t("smallProjectPack") : t("currentRuntime");
    if (els.generatedTree && hasTaskPackPreview && productFiles.length > 0) {
      els.generatedTree.innerHTML = renderers.renderFileTree
        ? renderers.renderFileTree(t("smallProjectPack") + "/", productFiles, escapeHtml)
        : '<div class="folder">' + escapeHtml(t("smallProjectPack")) + "/</div>";
    } else if (els.generatedTree && !hasTaskPackPreview) {
      els.generatedTree.innerHTML =
        '<div class="folder">' + escapeHtml(t("runtimeArtifacts")) + "</div>" +
        '<div class="file highlight">frontend_runtime_state.json</div>' +
        '<div class="file highlight-subtle">' + escapeHtml(t("runtimeTraceFiles")) + "</div>";
    }
    if (els.generatedPreview) {
      els.generatedPreview.classList.toggle("hidden", !hasTaskPackPreview);
    }
    var previewLabel = document.querySelector(".preview-label");
    if (previewLabel) previewLabel.textContent = previewText;
    if (els.usedCount && !hasTaskPackPreview) {
      els.usedCount.textContent = String(capsulesUsed);
    }
    if (els.usedCapsuleDock && !hasTaskPackPreview) {
      var usedText =
        capsulesUsed > 0
          ? formatText("capsulesLinked", { count: capsulesUsed })
          : t("noCapsuleUsage");
      els.usedCapsuleDock.innerHTML =
        '<span class="used-placeholder runtime-used-note">' + escapeHtml(usedText) + "</span>";
    }
    if (els.genCapsulesUsed && !hasTaskPackPreview) {
      els.genCapsulesUsed.innerHTML =
        '<span class="meta-icon" aria-hidden="true">◫</span> ' +
        capsulesUsed +
        " " +
        escapeHtml(t("capsulesUsed"));
    }
    if (els.workflowStatus) {
      var workflowText = hasTaskPackPreview
        ? taskPackStatusFromFiles(artifactFiles.length ? artifactFiles : data.generatedPackage.files || [])
        : currentWorkflowStep(hasTaskPackPreview);
      els.workflowStatus.innerHTML =
        '<span class="meta-icon" aria-hidden="true">↳</span> ' +
        escapeHtml(t("workflow")) +
        ": " +
        escapeHtml(workflowText);
    }
    var metaLines = document.querySelectorAll(".generated-meta .meta-line");
    if (metaLines[2]) metaLines[2].innerHTML = '<span class="meta-icon" aria-hidden="true">◎</span> ' + previewText;
    if (metaLines[3]) metaLines[3].innerHTML = '<span class="meta-icon" aria-hidden="true">⛓</span> ' + traceText;
    if (els.runtimeSidecarMode) els.runtimeSidecarMode.textContent = t("sourceReadOnly");
    if (els.runtimeSidecarSource) {
      els.runtimeSidecarSource.textContent = responseText;
    }
    if (els.runtimeSidecarStatus) {
      els.runtimeSidecarStatus.textContent =
        t("sourceWrites") +
        ": " +
        sourceWrites +
        "\n" +
        t("trace") +
        ": " +
        (traceAvailable ? t("ready") : t("unavailable")) +
        "\n" +
        t("preview") +
        ": " +
        (hasTaskPackPreview || summary.preview_ready ? t("ready") : t("notReady")) +
        "\n" +
        t("capsules") +
        ": " +
        capsulesUsed;
    }
    if (els.previewPackageActions) els.previewPackageActions.classList.add("hidden");
    var openFolder = $("btn-open-folder");
    if (openFolder) openFolder.classList.add("hidden");
    if (els.reweaveResponse) els.reweaveResponse.textContent = responseText;
  }

  function currentWorkflowStep(hasTaskPackPreview) {
    if (hasTaskPackPreview) return t("workflowViewProvenance");
    var sources = Array.isArray(data.sourceBoxes) ? data.sourceBoxes : [];
    if (!sources.length) return t("workflowBindSource");
    var needsScan = sources.some(function (src) {
      return (src.scan_status || "not_scanned") === "not_scanned";
    });
    if (needsScan) return t("workflowScanSource");
    var capsules = Array.isArray(data.warehouseCapsules) ? data.warehouseCapsules : data.capsules || [];
    if (!capsules.length) return t("workflowStoreCapsules");
    return t("workflowBuildPack");
  }

  function taskPackStatusFromFiles(files) {
    files = Array.isArray(files) ? files : [];
    if (
      files.indexOf("task_intent.json") >= 0 &&
      files.indexOf("task_plan.json") >= 0 &&
      files.indexOf("quality_gate.json") >= 0
    ) {
      return t("workflowIntentReady");
    }
    if (files.indexOf("task_pack.json") >= 0) return t("workflowPackReady");
    return t("workflowViewProvenance");
  }

  function bridgeCall(method, arg) {
    return new Promise(function (resolve) {
      if (!hasDesktopBridge()) {
        resolve(null);
        return;
      }
      var fn = desktopBridge[method];
      if (typeof fn !== "function") {
        resolve(null);
        return;
      }
      var ret;
      try {
        ret = arg !== undefined ? fn(arg) : fn();
      } catch (e) {
        console.warn("[Reweave] bridge call failed:", method, e);
        resolve(null);
        return;
      }
      if (ret && typeof ret.then === "function") {
        ret.then(resolve).catch(function () {
          resolve(null);
        });
        return;
      }
      resolve(ret);
    });
  }

  function initDesktopBridge(callback) {
    var finished = false;
    var connecting = false;
    function finish(available) {
      if (finished) return;
      finished = true;
      if (typeof callback === "function") callback(available);
    }

    function attach() {
      if (window.reweaveBridge && typeof window.reweaveBridge.choose_source_folder === "function") {
        desktopBridge = window.reweaveBridge;
        bridgeReady = true;
        bridgeCall("get_initial_state").then(function (raw) {
          desktopShellState = parseBridgeJson(raw);
          applyDesktopInitialState(desktopShellState);
          finish(true);
        });
        return true;
      }
      return false;
    }

    function connectQtBridge() {
      if (finished || connecting || typeof qt === "undefined" || !qt.webChannelTransport || typeof QWebChannel === "undefined") {
        return false;
      }
      connecting = true;
      new QWebChannel(qt.webChannelTransport, function (channel) {
        window.reweaveBridge = channel.objects.reweaveBridge;
        connecting = false;
        attach();
      });
      return true;
    }

    if (attach()) return;
    var retryUntil = Date.now() + 6000;
    function retryAttach() {
      if (attach() || connectQtBridge() || finished) return;
      if (Date.now() < retryUntil) setTimeout(retryAttach, 50);
    }
    retryAttach();

    window.addEventListener("reweave-bridge-ready", function onReady() {
      window.removeEventListener("reweave-bridge-ready", onReady);
      if (!attach()) finish(false);
    });

    setTimeout(function () {
      finish(hasDesktopBridge());
    }, 7000);
  }

  function mergeSourceFromDesktop(source) {
    if (!source || !source.id) return;
    if (!data.sourceBoxes) data.sourceBoxes = [];
    var idx = -1;
    data.sourceBoxes.forEach(function (s, i) {
      if (s.id === source.id || (source.path && s.path === source.path)) idx = i;
    });
    var entry = sourceWorkflow.normalizeSource ? sourceWorkflow.normalizeSource(source) : source;
    if (idx >= 0) {
      data.sourceBoxes[idx] = entry;
    } else {
      data.sourceBoxes.push(entry);
    }
  }

  function normalizeDockCapsule(c) {
    return capsuleReader.normalizeCapsule ? capsuleReader.normalizeCapsule(c) : c || null;
  }

  function isMetadataCapsule(cap) {
    return capsuleReader.isMetadataCapsule ? capsuleReader.isMetadataCapsule(cap) : false;
  }

  function isCapsuleGenerateEligible(cap) {
    if (!cap) return false;
    if (cap.origin === "lumo_lite_capsule_warehouse") return canBuildTaskPackPreview();
    var status = cap.status || "active";
    return status === "active" || status === "ready";
  }

  function isCapsuleManageEligible(cap) {
    return !!(cap && cap.origin !== "lumo_lite_capsule_warehouse" && isCapsuleGenerateEligible(cap));
  }

  function applyWarehouseCapsules(capsules) {
    if (!Array.isArray(capsules)) return;
    data.capsules = capsules.map(normalizeDockCapsule).filter(Boolean);
    data.warehouseCapsules = data.capsules.slice();
    data.generateCapsuleIds = data.capsules.filter(isCapsuleGenerateEligible).map(function (cap) {
      return cap.id;
    });
    if (els.capsuleStrip) {
      renderCapsuleStrip();
    }
    updateEnrichedContentToggle();
  }

  function applyDesktopInitialState(state) {
    if (!hasDesktopBridge() || !state || !data) return;
    if (isLumoLiteState(state)) {
      clearLumoLiteMockState();
      data.lumoLiteRuntimeSummary = state.lumoLiteRuntimeSummary || null;
    }
    if (Array.isArray(state.sourceBoxes)) {
      data.sourceBoxes = state.sourceBoxes.map(function (s) {
        return sourceWorkflow.normalizeSource ? sourceWorkflow.normalizeSource(s) : s;
      }).filter(Boolean);
    }
    if (Array.isArray(state.warehouseCapsules)) {
      applyWarehouseCapsules(state.warehouseCapsules);
    } else if (state.useLocalCapsules && Array.isArray(state.capsules) && state.capsules.length) {
      applyWarehouseCapsules(state.capsules);
    }
    if (state.generatedPackage) {
      data.generatedPackage = state.generatedPackage;
    }
    if (Array.isArray(state.lumoLiteArtifacts)) {
      lumoLiteArtifacts = state.lumoLiteArtifacts.slice();
      if (els.btnLumoArtifacts) {
        els.btnLumoArtifacts.classList.toggle("hidden", lumoLiteArtifacts.length === 0);
      }
    }
    if (state.previewPath) {
      lastPreviewPath = state.previewPath;
    } else if (state.lastPreview && state.lastPreview.previewPath) {
      lastPreviewPath = state.lastPreview.previewPath;
    }
    if ($("sources-count")) {
      renderSources();
    }
    syncSourceControls();
    syncWelcomeSourceBoxMode();
    applyLumoLiteRuntimeView();
  }

  function addBoundSource(source) {
    mergeSourceFromDesktop(source);
    renderSources();
  }

  function handleAddSource() {
    if (!hasDesktopBridge()) return;
    if (!desktopCapability("canChooseSourceFolder")) {
      if (els.reweaveResponse) els.reweaveResponse.textContent = t("runtimeReadOnlyMessage");
      return;
    }
    bridgeCall("choose_source_folder").then(function (raw) {
      var result = parseBridgeJson(raw);
      if (!result || result.cancelled) return;
      if (result.ok && result.source) {
        addBoundSource(result.source);
      }
    });
  }

  function applyLunaReuseFromDraft(draftResult) {
    if (!draftResult || !draftResult.draft) return;
    var draft = draftResult.draft;
    var sourceId = draftResult.source_id || draft.source_id;
    if (Array.isArray(draft.capsuleSuggestions) && draft.capsuleSuggestions.length && sourceId) {
      if (!data.lunaReuseBySource) data.lunaReuseBySource = {};
      data.lunaReuseBySource[sourceId] = {
        count: draft.capsuleSuggestions.length,
        suggestions: draft.capsuleSuggestions,
      };
      console.log("[Reweave] Luna reuse suggestions:", draft.capsuleSuggestions.length);
    }
    if (Array.isArray(draft.warnings) && draft.warnings.length) {
      console.warn("[Reweave] prepare warnings:", draft.warnings.join(", "));
    }
  }

  function applyVerificationResult(sourceId, result) {
    if (!result || !result.ok || !result.summary) return;
    if (!data.verificationBySource) data.verificationBySource = {};
    data.verificationBySource[sourceId] = {
      verified: result.summary.verified || 0,
      watch: result.summary.watch || 0,
      rejected: result.summary.rejected || 0,
      total: result.summary.total || 0,
    };
    console.log(
      "[Reweave] suggestion verification:",
      data.verificationBySource[sourceId].verified,
      "verified /",
      data.verificationBySource[sourceId].watch,
      "watch /",
      data.verificationBySource[sourceId].rejected,
      "rejected"
    );
  }

  function applyGovernancePreviewResult(sourceId, result) {
    if (!result || !result.ok || !result.summary) return;
    if (!data.governancePreviewBySource) data.governancePreviewBySource = {};
    data.governancePreviewBySource[sourceId] = {
      keep: result.summary.keep || 0,
      watch: result.summary.watch || 0,
      prune: result.summary.prune || 0,
      needs_manual_review: result.summary.needs_manual_review || 0,
      total: result.summary.total || 0,
    };
    if (result.warnings && result.warnings.length) {
      console.warn("[Reweave] governance preview warnings:", result.warnings.join(", "));
    }
    console.log(
      "[Reweave] governance preview:",
      data.governancePreviewBySource[sourceId].keep,
      "keep /",
      data.governancePreviewBySource[sourceId].watch,
      "watch /",
      data.governancePreviewBySource[sourceId].prune,
      "prune /",
      data.governancePreviewBySource[sourceId].needs_manual_review,
      "review"
    );
  }

  function applyReviewQueueResult(sourceId, result) {
    if (!result || !result.ok || !result.summary) return;
    if (!data.reviewQueueBySource) data.reviewQueueBySource = {};
    var items = (result.queue && result.queue.items) || [];
    data.reviewQueueBySource[sourceId] = {
      summary: result.summary,
      items: items,
    };
    console.log("[Reweave] review queue:", result.summary);
  }

  function handleCreateReviewQueue(sourceId) {
    if (!hasDesktopBridge() || !sourceId || isLumoLiteReadOnly()) return;
    reviewingSourceIds[sourceId] = true;
    renderSources();
    bridgeCall("create_review_queue_for_source", sourceId).then(function (raw) {
      delete reviewingSourceIds[sourceId];
      var result = parseBridgeJson(raw);
      if (result && result.ok) {
        applyReviewQueueResult(sourceId, result);
      } else if (result && result.error) {
        console.warn("[Reweave] review queue failed:", result.error);
      }
      renderSources();
    });
  }

  function handlePromoteReviewItem(sourceId, reviewId) {
    if (!hasDesktopBridge() || !sourceId || !reviewId) return;
    if (isLumoLiteReadOnly() || !desktopCapability("canPromoteDrafts")) return;
    bridgeCall(
      "promote_review_item",
      JSON.stringify({
        source_id: sourceId,
        review_id: reviewId,
      })
    ).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (!result || !result.ok) {
        if (result && result.error) {
          console.warn("[Reweave] promote failed:", result.error);
        }
        return;
      }
      if (data.reviewQueueBySource && data.reviewQueueBySource[sourceId]) {
        var items = data.reviewQueueBySource[sourceId].items;
        if (Array.isArray(items)) {
          items.forEach(function (item) {
            if (item.review_id === reviewId) {
              item.promoted = true;
              item.capsule_id = result.capsule_id;
              item.warehouse_action = result.warehouse_action || "promoted";
            }
          });
        }
      }
      if (!data.promotedCountBySource) data.promotedCountBySource = {};
      var prev = data.promotedCountBySource[sourceId] || 0;
      if (!result.already_promoted) {
        data.promotedCountBySource[sourceId] = prev + 1;
      }
      if (Array.isArray(result.capsules)) {
        applyWarehouseCapsules(result.capsules);
      } else if (Array.isArray(result.warehouseCapsules)) {
        applyWarehouseCapsules(result.warehouseCapsules);
      }
      renderSources();
    });
  }

  function handleEnrichCapsuleContent(capsuleId) {
    if (!hasDesktopBridge() || !capsuleId) return;
    bridgeCall("enrich_capsule_content", capsuleId).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (result && result.ok) {
        if (Array.isArray(result.capsules)) {
          applyWarehouseCapsules(result.capsules);
        }
        var cap = findCapsule(capsuleId);
        if (cap && result.content_path) {
          cap.content_enrichment = {
            status: "enriched",
            content_path: result.content_path,
            snippet_count: result.snippet_count,
          };
        }
        clearReaderContentPanel();
        if (cap) showCapsuleReader(cap);
      } else if (result && result.error) {
        console.warn("[Reweave] enrich failed:", result.error);
      }
    });
  }

  function clearReaderContentPanel() {
    var panel = document.getElementById("reader-content-panel");
    if (panel) panel.remove();
  }

  function renderReaderContentPanel(cap, contentPayload) {
    clearReaderContentPanel();
    if (!contentPayload || !els.reader) return;
    var panel = document.createElement("div");
    panel.id = "reader-content-panel";
    panel.className = "reader-content-panel";

    var safety = contentPayload.safety || {};
    var safetyEl = document.createElement("p");
    safetyEl.className = "reader-content-safety";
    var safetyBits = ["preview only"];
    if (safety.source_folder_written === false) safetyBits.unshift("source folder not modified");
    if ((contentPayload.limits || {}).secret_redaction) safetyBits.push("secrets redacted");
    safetyEl.textContent = safetyBits.join(" · ");
    panel.appendChild(safetyEl);

    var warnings = Array.isArray(contentPayload.warnings) ? contentPayload.warnings : [];
    if (warnings.length) {
      var warnBtn = document.createElement("button");
      warnBtn.type = "button";
      warnBtn.className = "btn-ghost btn-content-warnings";
      warnBtn.textContent = t("warnings") + " " + warnings.length;
      var warnList = document.createElement("ul");
      warnList.className = "reader-content-warnings hidden";
      warnings.forEach(function (w) {
        var li = document.createElement("li");
        li.textContent = String(w);
        warnList.appendChild(li);
      });
      warnBtn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        warnList.classList.toggle("hidden");
      });
      panel.appendChild(warnBtn);
      panel.appendChild(warnList);
    }

    var snippets = Array.isArray(contentPayload.snippets) ? contentPayload.snippets.slice(0, 2) : [];
    snippets.forEach(function (snip) {
      var block = document.createElement("div");
      block.className = "reader-snippet-block";
      var head = document.createElement("div");
      head.className = "reader-snippet-head";
      head.textContent =
        (snip.relative_path || "file") +
        " · " +
        (snip.language_hint || "text") +
        " · " +
        (snip.bytes_read != null ? snip.bytes_read + " bytes" : "");
      block.appendChild(head);
      var badges = document.createElement("div");
      badges.className = "reader-snippet-badges";
      if (snip.truncated) {
        var tBadge = document.createElement("span");
        tBadge.className = "reader-snippet-badge";
        tBadge.textContent = t("truncated");
        badges.appendChild(tBadge);
      }
      if (snip.redacted) {
        var rBadge = document.createElement("span");
        rBadge.className = "reader-snippet-badge reader-snippet-badge-redacted";
        rBadge.textContent = t("redacted");
        badges.appendChild(rBadge);
      }
      if (badges.childNodes.length) block.appendChild(badges);
      var pre = document.createElement("pre");
      pre.className = "reader-snippet-preview";
      pre.textContent = String(snip.preview || "");
      block.appendChild(pre);
      panel.appendChild(block);
    });

    var previewEl = $("reader-preview");
    if (previewEl && previewEl.parentNode === els.reader) {
      var actions = document.querySelector(".reader-actions");
      if (actions && actions.parentNode === els.reader) {
        els.reader.insertBefore(panel, actions);
      } else {
        els.reader.appendChild(panel);
      }
    } else {
      els.reader.appendChild(panel);
    }
  }

  function handleViewCapsuleContent(capsuleId) {
    if (!hasDesktopBridge() || !capsuleId) return;
    bridgeCall("get_capsule_content", capsuleId).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (!result || !result.ok || !result.content) {
        if (result && result.error) {
          console.warn("[Reweave] view content failed:", result.error);
        }
        return;
      }
      var cap = findCapsule(capsuleId);
      if (cap) renderReaderContentPanel(cap, result.content);
    });
  }

  function handleUpdateCapsuleStatus(capsuleId, status) {
    if (!hasDesktopBridge() || !capsuleId || !status) return;
    bridgeCall(
      "update_capsule_status",
      JSON.stringify({ capsule_id: capsuleId, status: status })
    ).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (result && result.ok && Array.isArray(result.capsules)) {
        applyWarehouseCapsules(result.capsules);
        if (selectedCapsuleId === capsuleId) {
          var cap = findCapsule(capsuleId);
          if (cap) showCapsuleReader(cap);
        }
      } else if (result && result.error) {
        console.warn("[Reweave] capsule status update failed:", result.error);
      }
    });
  }

  function handleReviewDecision(sourceId, reviewId, decision) {
    if (!hasDesktopBridge() || !sourceId || !reviewId) return;
    bridgeCall(
      "update_review_decision",
      JSON.stringify({
        source_id: sourceId,
        review_id: reviewId,
        decision: decision,
        reason: "",
      })
    ).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (result && result.ok && result.summary && data.reviewQueueBySource && data.reviewQueueBySource[sourceId]) {
        data.reviewQueueBySource[sourceId].summary = result.summary;
        if (result.item && Array.isArray(data.reviewQueueBySource[sourceId].items)) {
          data.reviewQueueBySource[sourceId].items.forEach(function (item) {
            if (item.review_id === result.item.review_id) {
              item.decision = result.item.decision;
            }
          });
        }
        renderSources();
      }
    });
  }

  function appendReviewMiniPanel(li, sourceId, queueData) {
    if (!queueData || !Array.isArray(queueData.items) || !queueData.items.length) return;
    var panel = document.createElement("div");
    panel.className = "source-review-mini";
    queueData.items.slice(0, 3).forEach(function (item) {
      var row = document.createElement("div");
      row.className = "source-review-row";
      var score = item.verification_score != null ? Number(item.verification_score).toFixed(2) : "—";
      row.innerHTML =
        '<span class="source-review-name">' +
        escapeHtml(item.name || item.review_id) +
        "</span>" +
        '<span class="source-review-meta">' +
        escapeHtml(item.governance_action || "") +
        " · " +
        escapeHtml(String(score)) +
        "</span>";
      if (item.decision === "pending" || item.decision === "deferred") {
        ["approved", "rejected", "deferred"].forEach(function (decision) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.className = "btn-ghost btn-source-scan btn-review-decision";
          btn.textContent = decision === "approved" ? t("approve") : decision === "rejected" ? t("reject") : t("defer");
          btn.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            handleReviewDecision(sourceId, item.review_id, decision);
          });
          row.appendChild(btn);
        });
      } else if (item.decision === "approved" && !item.promoted) {
        if (hasDesktopBridge() && !isLumoLiteReadOnly() && desktopCapability("canPromoteDrafts")) {
          var promoteBtn = document.createElement("button");
          promoteBtn.type = "button";
          promoteBtn.className = "btn-ghost btn-source-scan btn-review-promote";
          promoteBtn.textContent = t("promote");
          promoteBtn.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            handlePromoteReviewItem(sourceId, item.review_id);
          });
          row.appendChild(promoteBtn);
        }
      } else {
        var tag = document.createElement("span");
        tag.className = "source-review-decision";
        tag.textContent = item.promoted ? t("promoted") : t(item.decision);
        row.appendChild(tag);
      }
      panel.appendChild(row);
    });
    li.appendChild(panel);
  }

  function handleGovernancePreview(sourceId) {
    if (!hasDesktopBridge() || !sourceId || isLumoLiteReadOnly()) return;
    previewingSourceIds[sourceId] = true;
    renderSources();
    bridgeCall("preview_governance_for_source", sourceId).then(function (raw) {
      delete previewingSourceIds[sourceId];
      var result = parseBridgeJson(raw);
      if (result && result.ok) {
        applyGovernancePreviewResult(sourceId, result);
      } else if (result && result.error) {
        console.warn("[Reweave] governance preview failed:", result.error);
      }
      renderSources();
    });
  }

  function handleVerifySource(sourceId) {
    if (!hasDesktopBridge() || !sourceId || isLumoLiteReadOnly()) return;
    verifyingSourceIds[sourceId] = true;
    renderSources();
    bridgeCall("verify_source_suggestions", sourceId).then(function (raw) {
      delete verifyingSourceIds[sourceId];
      var result = parseBridgeJson(raw);
      if (result && result.ok) {
        applyVerificationResult(sourceId, result);
      } else if (result && result.error) {
        console.warn("[Reweave] verify failed:", result.error);
      }
      renderSources();
    });
  }

  function handlePrepareSource(sourceId) {
    if (!hasDesktopBridge() || !sourceId) return;
    if (!desktopCapability("canDraftCapsules")) return;
    preparingSourceIds[sourceId] = true;
    renderSources();
    bridgeCall("draft_capsules", sourceId).then(function (raw) {
      var draftResult = parseBridgeJson(raw);
      if (!draftResult || !draftResult.ok) {
        delete preparingSourceIds[sourceId];
        if (draftResult && draftResult.source) {
          mergeSourceFromDesktop(draftResult.source);
        } else {
          var idx = (data.sourceBoxes || []).findIndex(function (s) {
            return s.id === sourceId;
          });
          if (idx >= 0) {
            data.sourceBoxes[idx].draft_status = "failed";
            data.sourceBoxes[idx].last_error = (draftResult && draftResult.error) || "draft failed";
          }
        }
        renderSources();
        return;
      }
      if (draftResult.source) mergeSourceFromDesktop(draftResult.source);
      applyLunaReuseFromDraft(draftResult);
      if (!desktopCapability("canPromoteDrafts") || isLumoLiteReadOnly()) {
        delete preparingSourceIds[sourceId];
        renderSources();
        return;
      }
      bridgeCall("promote_source_drafts", sourceId).then(function (promoteRaw) {
        delete preparingSourceIds[sourceId];
        var promoteResult = parseBridgeJson(promoteRaw);
        if (promoteResult && promoteResult.source) {
          mergeSourceFromDesktop(promoteResult.source);
        }
        if (promoteResult && promoteResult.ok && Array.isArray(promoteResult.capsules)) {
          applyWarehouseCapsules(promoteResult.capsules);
        }
        renderSources();
      });
    });
  }

  function handleStoreSource(sourceId) {
    if (!hasDesktopBridge() || !sourceId) return;
    if (!desktopCapability("canPromoteDrafts")) return;
    preparingSourceIds[sourceId] = true;
    renderSources();
    bridgeCall("promote_source_drafts", sourceId).then(function (raw) {
      delete preparingSourceIds[sourceId];
      var result = parseBridgeJson(raw);
      if (result && result.source) {
        mergeSourceFromDesktop(result.source);
      }
      if (result && result.ok && Array.isArray(result.capsules)) {
        applyWarehouseCapsules(result.capsules);
      }
      renderSources();
    });
  }

  function runDesktopSourcePipeline(sourceId, onDone) {
    if (!sourceId) {
      if (onDone) onDone(false);
      return;
    }
    bridgeCall("scan_source_box", sourceId).then(function (scanRaw) {
      var scanResult = parseBridgeJson(scanRaw);
      if (!scanResult || !scanResult.ok) {
        if (onDone) onDone(false);
        return;
      }
      if (scanResult.source) mergeSourceFromDesktop(scanResult.source);
      bridgeCall("draft_capsules", sourceId).then(function (draftRaw) {
        var draftResult = parseBridgeJson(draftRaw);
        if (!draftResult || !draftResult.ok) {
          if (onDone) onDone(false);
          return;
        }
        if (draftResult.source) mergeSourceFromDesktop(draftResult.source);
        applyLunaReuseFromDraft(draftResult);
        if (!desktopCapability("canPromoteDrafts") || isLumoLiteReadOnly()) {
          if (onDone) onDone(true);
          return;
        }
        bridgeCall("promote_source_drafts", sourceId).then(function (promoteRaw) {
          var promoteResult = parseBridgeJson(promoteRaw);
          if (promoteResult && promoteResult.source) {
            mergeSourceFromDesktop(promoteResult.source);
          }
          if (promoteResult && promoteResult.ok && Array.isArray(promoteResult.capsules)) {
            applyWarehouseCapsules(promoteResult.capsules);
          }
          if (onDone) onDone(!!(promoteResult && promoteResult.ok));
        });
      });
    });
  }

  function handleDesktopWelcomeIntake() {
    if (!desktopCapability("canChooseSourceFolder")) {
      syncWelcomeSourceBoxMode();
      return;
    }
    bridgeCall("choose_source_folder").then(function (raw) {
      var result = parseBridgeJson(raw);
      if (!result || result.cancelled || !result.ok || !result.source) return;
      mergeSourceFromDesktop(result.source);
      showScreen("screen-cleaning");
      var stepsEl = $("cleaning-steps");
      var bar = $("progress-bar");
      stepsEl.innerHTML = "";
      ["Binding source folder", "Scanning structure", "Preparing capsule drafts"].forEach(function (text) {
        var li = document.createElement("li");
        li.textContent = text;
        stepsEl.appendChild(li);
      });
      bar.style.width = "12%";
      runDesktopSourcePipeline(result.source.id, function (ok) {
        bar.style.width = "100%";
        stepsEl.querySelectorAll("li").forEach(function (li) {
          li.classList.add("done");
        });
        setTimeout(function () {
          initMain();
          var needsStore = (data.sourceBoxes || []).some(function (source) {
            return source.draft_status === "drafted" && source.warehouse_status !== "promoted";
          });
          if (ok && needsStore && els.reweaveResponse) {
            els.reweaveResponse.textContent = t("draftsReadyStore");
          }
        }, ok ? 320 : 480);
      });
    });
  }

  function handleScanSource(sourceId) {
    if (!hasDesktopBridge() || !sourceId) return;
    if (!desktopCapability("canScanSourceBox")) return;
    scanningSourceIds[sourceId] = true;
    renderSources();
    bridgeCall("scan_source_box", sourceId).then(function (raw) {
      delete scanningSourceIds[sourceId];
      var result = parseBridgeJson(raw);
      if (result && result.source) {
        addBoundSource(result.source);
      } else if (result && !result.ok) {
        var idx = (data.sourceBoxes || []).findIndex(function (s) {
          return s.id === sourceId;
        });
        if (idx >= 0) {
          data.sourceBoxes[idx].scan_status = "failed";
          data.sourceBoxes[idx].last_error = result.error || "scan failed";
        }
        renderSources();
      }
    });
  }

  function sourceScanLabel(src) {
    if (sourceWorkflow.sourceScanLabel) {
      return sourceWorkflow.sourceScanLabel(src, {
        preparing: !!preparingSourceIds[src.id],
        scanning: !!scanningSourceIds[src.id],
        verifying: !!verifyingSourceIds[src.id],
        previewing: !!previewingSourceIds[src.id],
        reviewing: !!reviewingSourceIds[src.id],
        lunaReuse: !!(data.lunaReuseBySource && data.lunaReuseBySource[src.id]),
        locale: locale,
      });
    }
    return src.scan_status || "not_scanned";
  }

  function getGenerateCandidateIds() {
    if (usedCapsuleSelectionMode === "manual" && usedCapsuleIds.length > 0) return usedCapsuleIds.slice();
    return (data.capsules || []).filter(isCapsuleGenerateEligible).map(function (cap) {
      return cap.id;
    });
  }

  function anyEnrichedInIds(ids) {
    return (ids || []).some(function (id) {
      var cap = findCapsule(id);
      return !!(cap && cap.content_enrichment && cap.content_enrichment.status === "enriched");
    });
  }

  function updateEnrichedContentToggle() {
    var wrap = $("enriched-content-toggle-wrap");
    var checkbox = $("use-enriched-content");
    if (!wrap || !checkbox) return;
    var canUse = hasDesktopBridge() && anyEnrichedInIds(getGenerateCandidateIds());
    wrap.classList.toggle("hidden", !canUse);
    if (!canUse) {
      useEnrichedContentPreview = false;
      checkbox.checked = false;
    }
  }

  function setLocalModelStatus(key) {
    var status = $("local-model-status");
    if (!status) return;
    status.setAttribute("data-i18n", key);
    status.textContent = t(key);
  }

  function updateLocalModelToggle() {
    var wrap = $("local-model-toggle-wrap");
    var checkbox = $("use-local-model");
    if (!wrap || !checkbox) return;
    var supported = hasDesktopBridge() && desktopCapability("canUseBoundedLocalModel");
    wrap.classList.toggle("hidden", !supported);
    if (!supported) {
      useBoundedLocalModel = false;
      checkbox.checked = false;
      setLocalModelStatus("localModelOff");
    }
  }

  function notifyDesktopGenerate(text, ids) {
    if (!hasDesktopBridge()) {
      pendingGeneratePromise = null;
      return Promise.resolve(null);
    }
    var candidates = ids.length ? ids : getGenerateCandidateIds();
    var payload = {
      taskText: text,
      capsuleIds: ids,
      capsules: ids.map(findCapsule).filter(Boolean),
      selectionMode: usedCapsuleSelectionMode,
      useEnrichedContent: !!(useEnrichedContentPreview && anyEnrichedInIds(candidates)),
      validateRuntime: true,
      localModel: useBoundedLocalModel
        ? { enabled: true, provider: "ollama", model: "qwen2.5-coder:1.5b" }
        : { enabled: false },
      sourceBoxes: (data.sourceBoxes || []).map(function (s) {
        return { id: s.id, label: s.label, path: s.path || "", status: s.status };
      }),
    };
    pendingGeneratePromise = bridgeCall("notify_generate", JSON.stringify(payload));
    return pendingGeneratePromise;
  }

  function applyGenerateResult(result) {
    if (!result || !result.ok) return;
    lastPreviewAcceptance = result.previewAcceptance || null;
    if (result.generatedPackage) {
      data.generatedPackage = result.generatedPackage;
    }
    if (result.previewPath) {
      lastPreviewPath = result.previewPath;
    }
    if (result.lunaPack && result.lunaPack.pack_id) {
      console.log("[Reweave] Luna pack indexed:", result.lunaPack.pack_id);
      data.lunaPack = result.lunaPack;
    }
    if (result.warnings && result.warnings.length) {
      console.warn("[Reweave] generate warnings:", result.warnings.join(", "));
    }
    if (result.contentAwareGenerate) {
      data.contentAwareGenerate = result.contentAwareGenerate;
    }
    if (Array.isArray(result.capsulesUsed)) {
      usedCapsuleIds = result.capsulesUsed.map(function (cap) { return cap.id; }).filter(Boolean);
      usedCapsuleSelectionMode = result.taskPack && result.taskPack.selection_mode === "auto_match" ? "auto_match" : "manual";
      renderUsedChips();
    }
    if (result.localModel && result.localModel.enabled) {
      setLocalModelStatus(result.localModel.applied ? "localModelApplied" : "localModelFallback");
    } else if (useBoundedLocalModel) {
      setLocalModelStatus("localModelFallback");
    }
  }

  function previewAcceptanceText(acceptance) {
    if (!acceptance) return "";
    if (acceptance.verdict === "usable" && acceptance.reason === "runtime_behavior_verified") {
      return t("acceptanceUsable");
    }
    if (acceptance.reason === "runtime_behavior_failed") return t("acceptanceRejectedRuntime");
    if (acceptance.verdict === "rejected") return t("acceptanceRejected");
    if (acceptance.reason === "quality_gate_not_reported") return t("acceptanceNeedsQuality");
    if (acceptance.reason === "runtime_validation_required") return t("acceptanceNeedsRuntime");
    return t("acceptanceNeedsBehavior");
  }

  function showScreen(id) {
    ["screen-welcome", "screen-cleaning", "screen-main"].forEach(function (sid) {
      $(sid).classList.toggle("hidden", sid !== id);
    });
  }

  function loadMockData(callback) {
    var embed = document.getElementById("mock-data-embed");

    function apply(raw) {
      data = JSON.parse(raw);
      normalizeMockFallback();
      callback(null);
    }

    function useEmbed() {
      if (!embed || !embed.textContent.trim()) {
        callback(new Error("Failed to load mock-data.json"));
        return;
      }
      try {
        apply(embed.textContent);
      } catch (e) {
        callback(e);
      }
    }

    var xhr = new XMLHttpRequest();
    xhr.open("GET", "mock-data.json", true);
    xhr.onload = function () {
      if ((xhr.status >= 200 && xhr.status < 300) || xhr.status === 0) {
        try {
          apply(xhr.responseText);
          return;
        } catch (e) {
          useEmbed();
          return;
        }
      }
      useEmbed();
    };
    xhr.onerror = useEmbed;
    xhr.send();
  }

  function t(key) {
    return (STR[locale] && STR[locale][key]) || STR.en[key] || key;
  }

  function formatText(key, values) {
    var text = t(key);
    Object.keys(values || {}).forEach(function (name) {
      text = text.split("{" + name + "}").join(String(values[name]));
    });
    return text;
  }

  function prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function setAppState(state) {
    appState = state;
    if (els.screenMain) {
      els.screenMain.setAttribute("data-app-state", state);
    }
  }

  function syncAppState() {
    if (isGenerating) {
      setAppState("invoking");
      return;
    }
    if (usedCapsuleIds.length > 0 && els.reweaveResponse && els.reweaveResponse.textContent) {
      setAppState("ready");
      return;
    }
    if (selectedCapsuleId) {
      setAppState("selected");
      return;
    }
    setAppState("idle");
  }

  function getCapsuleSerial(cap) {
    return capsuleReader.serial ? capsuleReader.serial(cap) : "00";
  }

  function applyLocale() {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var key = el.getAttribute("data-i18n");
      if (key && t(key)) el.textContent = t(key);
    });
    document.querySelectorAll("[data-i18n-aria-label]").forEach(function (el) {
      var key = el.getAttribute("data-i18n-aria-label");
      if (key && t(key)) el.setAttribute("aria-label", t(key));
    });
    var input = $("task-input");
    if (input) input.placeholder = t("taskPlaceholder");
    var langBtn = $("btn-lang");
    if (langBtn) langBtn.textContent = locale === "zh" ? "中 / EN" : "EN / 中";
    var wl = $("btn-welcome-lang");
    if (wl) wl.textContent = locale === "zh" ? "中 / EN" : "EN / 中";
    if (els.usedCapsuleDock && usedCapsuleIds.length === 0) {
      els.usedCapsuleDock.innerHTML =
        '<span class="used-placeholder">' + escapeHtml(t("usedPlaceholder")) + "</span>";
    }
    if (els.generationInputNote) {
      els.generationInputNote.textContent =
        usedCapsuleIds.length > 0
          ? formatText("generationManual", { count: usedCapsuleIds.length })
          : t("generationAuto");
    }
    var useBtn = $("btn-use-in-task");
    if (useBtn) useBtn.textContent = t("useInTask");
    var openCapBtn = $("btn-open-capsule");
    if (openCapBtn) openCapBtn.textContent = t("openCapsule");
    var readerLabel = document.querySelector(".reader-slot-label");
    if (readerLabel) readerLabel.textContent = t("readerLabel").toUpperCase();
    syncWelcomeSourceBoxMode();
    if (data) {
      renderHistory();
      renderSources();
    }
    if (selectedCapsuleId && els.reader && !els.reader.classList.contains("hidden")) {
      var selected = findCapsule(selectedCapsuleId);
      if (selected) showCapsuleReader(selected);
    }
    applyLumoLiteRuntimeView();
  }

  function toggleLocale() {
    locale = locale === "zh" ? "en" : "zh";
    localStorage.setItem("reweave_locale", locale);
    applyLocale();
    if (els.usedCount && els.usedCapsuleDock) renderUsedChips();
    if (appState === "ready" && usedCapsuleIds.length > 0) {
      finishGenerate(els.taskInput.value.trim() || data.sampleTask || t("smallProjectPack"), usedCapsuleIds.length, true);
    }
  }

  function initWelcome() {
    applyLocale();
    syncWelcomeSourceBoxMode();
    $("btn-select-folder").addEventListener("click", function () {
      if (hasDesktopBridge() && !desktopCapability("canChooseSourceFolder")) {
        syncWelcomeSourceBoxMode();
        return;
      }
      if (hasDesktopBridge()) {
        handleDesktopWelcomeIntake();
      } else {
        startCleaning();
      }
    });
    var vr = $("btn-view-runtime");
    if (vr) {
      vr.addEventListener("click", function () {
        initMain();
      });
    }
    var wl = $("btn-welcome-lang");
    if (wl) wl.addEventListener("click", toggleLocale);
  }

  function startCleaning() {
    showScreen("screen-cleaning");
    var stepsEl = $("cleaning-steps");
    var bar = $("progress-bar");
    stepsEl.innerHTML = "";
    var steps = data.cleaningSteps || [];
    steps.forEach(function (text) {
      var li = document.createElement("li");
      li.textContent = text;
      stepsEl.appendChild(li);
    });

    var index = 0;
    function tick() {
      var items = stepsEl.querySelectorAll("li");
      items.forEach(function (li, i) {
        li.classList.remove("active", "done");
        if (i < index) li.classList.add("done");
        if (i === index) li.classList.add("active");
      });
      bar.style.width = ((index + 1) / steps.length) * 100 + "%";
      index += 1;
      if (index <= steps.length) {
        setTimeout(tick, 650);
      } else {
        setTimeout(initMain, 400);
      }
    }
    tick();
  }

  function initMain() {
    showScreen("screen-main");
    cacheElements();
    usedCapsuleIds = [];
    selectedCapsuleId = null;
    isGenerating = false;
    applyLocale();
    renderCapsuleStrip();
    renderGeneratedPackage(!!lastPreviewPath);
    renderHistory();
    renderSources();
    bindMainEvents();
    if (data.sampleTask && els.taskInput) {
      els.taskInput.value = data.sampleTask;
    }
    if (els.reweaveResponse) els.reweaveResponse.textContent = "";
    setAppState("idle");
    applyLumoLiteRuntimeView();
  }

  function cacheElements() {
    els.screenMain = $("screen-main");
    els.capsuleDock = $("capsule-dock");
    els.capsuleStrip = $("capsule-strip");
    els.capsuleCount = $("capsule-count");
    els.taskBay = $("task-bay");
    els.usedCapsuleDock = $("used-capsule-dock");
    els.generationInputNote = $("generation-input-note");
    els.usedCount = $("used-count");
    els.taskInput = $("task-input");
    els.btnGenerate = $("btn-generate");
    els.reweaveResponse = $("reweave-response");
    els.generatedTree = $("generated-tree");
    els.generatedPreview = $("generated-preview");
    els.workflowStatus = $("workflow-status");
    els.genCapsulesUsed = $("gen-capsules-used");
    els.reader = $("capsule-reader");
    els.historyPopover = $("history-popover");
    els.sourcesPopover = $("sources-popover");
    els.backdrop = $("backdrop");
    els.readerConnector = $("reader-connector");
    els.generatedPackage = $("generated-package");
    els.previewPackageActions = $("preview-package-actions");
    els.previewPackageViewer = $("preview-package-viewer");
    els.previewViewerBody = $("preview-viewer-body");
    els.previewViewerTitle = $("preview-viewer-title");
    els.previewViewerActions = $("preview-viewer-actions");
    els.btnLumoArtifacts = $("btn-lumo-artifacts");
    els.lumoArtifactsPopover = $("lumo-artifacts-popover");
    els.lumoArtifactsBody = $("lumo-artifacts-body");
    els.runtimeSidecarMode = $("runtime-sidecar-mode");
    els.runtimeSidecarSource = $("runtime-sidecar-source");
    els.runtimeSidecarStatus = $("runtime-sidecar-status");
    updateLocalModelToggle();
  }

  function shortName(name) {
    if (!name) return name;
    if (name.length <= 18) return name;
    return name.slice(0, 17) + "…";
  }

  function getVisibleCapsules() {
    return (data.capsules || []).slice(0, CAPSULES_VISIBLE);
  }

  function capsuleSourceLabel(cap) {
    return capsuleReader.sourceLabel ? capsuleReader.sourceLabel(cap) : "";
  }

  function renderCapsuleStrip() {
    if (!els.capsuleCount || !els.capsuleStrip) return;
    els.capsuleCount.textContent = String((data.capsules || []).length);
    els.capsuleStrip.innerHTML = "";
    getVisibleCapsules().forEach(function (cap) {
      var btn = document.createElement("button");
      var inactive = !isCapsuleGenerateEligible(cap);
      btn.type = "button";
      btn.className =
        "capsule-cartridge" +
        (cap.id === selectedCapsuleId ? " selected" : "") +
        (inactive ? " cartridge-inactive" : "") +
        (isMetadataCapsule(cap) ? " cartridge-metadata" : "");
      btn.dataset.capsuleId = cap.id;
      btn.dataset.capsuleType = cap.type;
      btn.dataset.source = capsuleSourceLabel(cap);
      btn.dataset.capsuleSerial = getCapsuleSerial(cap);
      btn.setAttribute("role", "listitem");
      btn.setAttribute("aria-label", cap.name + " (" + cap.type + ")");
      btn.setAttribute("aria-pressed", cap.id === selectedCapsuleId ? "true" : "false");
      var metaBadge = isMetadataCapsule(cap)
        ? '<span class="cartridge-meta-badge">META</span>'
        : "";
      var statusBadge =
        cap.status && cap.status !== "active" && cap.status !== "ready"
          ? '<span class="cartridge-status-badge">' + escapeHtml(cap.status) + "</span>"
          : "";
      btn.innerHTML =
        '<span class="cartridge-notch" aria-hidden="true"></span>' +
        '<span class="cartridge-seam" aria-hidden="true"></span>' +
        '<span class="cartridge-pattern" aria-hidden="true"></span>' +
        metaBadge +
        statusBadge +
        '<span class="cartridge-face">' +
        '<span class="cartridge-icon">' + escapeHtml(cap.icon) + "</span>" +
        '<span class="cartridge-name">' + escapeHtml(shortName(cap.name)) + "</span>" +
        '<span class="cartridge-type">' + escapeHtml(cap.type) + "</span>" +
        "</span>" +
        '<span class="cartridge-serial" aria-hidden="true">' +
        escapeHtml(getCapsuleSerial(cap)) +
        "</span>";
      btn.addEventListener("click", function () {
        selectCapsule(cap.id);
      });
      els.capsuleStrip.appendChild(btn);
    });
  }

  function findCapsule(id) {
    return (data.capsules || []).find(function (c) {
      return c.id === id;
    });
  }

  function selectCapsule(id) {
    selectedCapsuleId = id;
    renderCapsuleStrip();
    var cap = findCapsule(id);
    if (!cap) return;
    showCapsuleReader(cap);
    setAppState("selected");
  }

  function showCapsuleReader(cap) {
    clearReaderContentPanel();
    setRuntimeSidecarVisible(false);
    var readerIcon = $("reader-icon");
    var readerName = $("reader-name");
    var readerType = $("reader-type");
    var readerSource = $("reader-source");
    var readerTags = $("reader-tags");
    var readerRole = $("reader-role");
    var readerPreview = $("reader-preview");
    if (!readerIcon || !readerName || !readerType || !readerSource || !readerTags || !readerRole || !readerPreview) return;
    readerIcon.textContent = cap.icon;
    readerName.textContent = cap.name;
    readerType.textContent = cap.type;
    readerSource.textContent = t("fromSource") + " " + capsuleSourceLabel(cap);
    var tagBits = capsuleReader.tagBits ? capsuleReader.tagBits(cap) : (cap.tags || []).slice();
    readerTags.textContent = t("tagsPrefix") + " " + tagBits.join(" · ");
    readerRole.textContent = t("rolePrefix") + " " + (cap.role || "");
    readerPreview.textContent = capsuleReader.previewText
      ? capsuleReader.previewText(cap)
      : (cap.preview || []).join("\n");
    var actions = document.querySelector(".reader-actions");
    if (actions) {
      var useBtn = $("btn-use-in-task");
      if (useBtn) {
        var eligible = isCapsuleGenerateEligible(cap);
        useBtn.disabled = !eligible;
        useBtn.textContent = eligible ? t("useInTask") : t("readOnly");
      }
      var openBtn = $("btn-open-capsule");
      if (openBtn) openBtn.classList.toggle("hidden", cap.origin === "lumo_lite_capsule_warehouse");
      var existingStatus = actions.querySelector(".reader-status-actions");
      if (existingStatus) existingStatus.remove();
      var existingEnrich = actions.querySelector(".reader-enrich-actions");
      if (existingEnrich) existingEnrich.remove();
      var existingView = actions.querySelector(".reader-view-content-actions");
      if (existingView) existingView.remove();
      if (
        hasDesktopBridge() &&
        cap.id &&
        isMetadataCapsule(cap) &&
        isCapsuleManageEligible(cap) &&
        !(cap.content_enrichment && cap.content_enrichment.status === "enriched")
      ) {
        var enrichWrap = document.createElement("div");
        enrichWrap.className = "reader-enrich-actions";
        var enrichBtn = document.createElement("button");
        enrichBtn.type = "button";
        enrichBtn.className = "btn-ghost btn-capsule-enrich";
        enrichBtn.textContent = t("enrichContent");
        enrichBtn.addEventListener("click", function (e) {
          e.preventDefault();
          e.stopPropagation();
          handleEnrichCapsuleContent(cap.id);
        });
        enrichWrap.appendChild(enrichBtn);
        actions.appendChild(enrichWrap);
      } else if (
        hasDesktopBridge() &&
        cap.id &&
        isCapsuleManageEligible(cap) &&
        cap.content_enrichment &&
        cap.content_enrichment.status === "enriched"
      ) {
        var viewWrap = document.createElement("div");
        viewWrap.className = "reader-view-content-actions";
        var viewBtn = document.createElement("button");
        viewBtn.type = "button";
        viewBtn.className = "btn-ghost btn-capsule-view-content";
        viewBtn.textContent = t("viewContent");
        viewBtn.addEventListener("click", function (e) {
          e.preventDefault();
          e.stopPropagation();
          handleViewCapsuleContent(cap.id);
        });
        viewWrap.appendChild(viewBtn);
        actions.appendChild(viewWrap);
      }
      if (hasDesktopBridge() && cap.id && isCapsuleManageEligible(cap)) {
        var statusWrap = document.createElement("div");
        statusWrap.className = "reader-status-actions";
        ["disabled", "deprecated"].forEach(function (status) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.className = "btn-ghost btn-capsule-status";
          btn.textContent = status === "disabled" ? "Disable" : "Deprecate";
          btn.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            handleUpdateCapsuleStatus(cap.id, status);
          });
          statusWrap.appendChild(btn);
        });
        actions.appendChild(statusWrap);
      }
    }
    els.reader.classList.remove("hidden");
    els.reader.classList.add("is-open");
    els.reader.setAttribute("data-capsule-id", cap.id);
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        positionReaderNearCapsule(cap.id);
      });
    });
  }

  function positionReaderNearCapsule(id) {
    var chip = els.capsuleStrip.querySelector('[data-capsule-id="' + id + '"]');
    var bay = els.taskBay;
    if (!bay) return;

    var bayRect = bay.getBoundingClientRect();
    var chipRect = chip ? chip.getBoundingClientRect() : bayRect;
    var readerW = 248;
    var gap = 14;
    var top = Math.max(72, chipRect.top - 8);
    var left = bayRect.right + gap;

    if (left + readerW > window.innerWidth - 16) {
      left = Math.max(16, chipRect.right + gap);
      top = chipRect.top;
    }

    els.reader.style.top = top + "px";
    els.reader.style.left = left + "px";
    els.reader.style.right = "auto";

    if (els.readerConnector && chip) {
      var readerRect = els.reader.getBoundingClientRect();
      var path = els.readerConnector.querySelector("path");
      if (path) {
        var x1 = chipRect.right;
        var y1 = chipRect.top + chipRect.height * 0.5;
        var x2 = readerRect.left + 2;
        var y2 = readerRect.top + 28;
        var midX = (x1 + x2) * 0.5;
        path.setAttribute(
          "d",
          "M" + x1 + " " + y1 + " C " + midX + " " + y1 + ", " + midX + " " + y2 + ", " + x2 + " " + y2
        );
        els.readerConnector.classList.remove("hidden");
      }
    }
  }

  function hideCapsuleReader() {
    clearReaderContentPanel();
    setRuntimeSidecarVisible(true);
    els.reader.classList.add("hidden");
    els.reader.classList.remove("is-open");
    els.reader.removeAttribute("data-capsule-id");
    if (els.readerConnector) els.readerConnector.classList.add("hidden");
    syncAppState();
  }

  function setRuntimeSidecarVisible(visible) {
    var sidecar = document.querySelector(".runtime-sidecar");
    if (sidecar) sidecar.style.visibility = visible ? "" : "hidden";
  }

  function setRuntimeSidecarAvailable(available) {
    var sidecar = document.querySelector(".runtime-sidecar");
    var machine = document.querySelector(".machine-core");
    if (sidecar) sidecar.classList.toggle("runtime-sidecar-unavailable", !available);
    if (machine) machine.classList.toggle("sidecar-collapsed", !available);
  }

  function renderUsedChips() {
    els.usedCount.textContent = String(usedCapsuleIds.length);
    if (usedCapsuleIds.length === 0) {
      els.usedCapsuleDock.innerHTML =
        '<span class="used-placeholder">' + escapeHtml(t("usedPlaceholder")) + "</span>";
      if (els.generationInputNote) els.generationInputNote.textContent = t("generationAuto");
      return;
    }
    els.usedCapsuleDock.innerHTML = "";
    usedCapsuleIds.forEach(function (id) {
      var cap = findCapsule(id);
      if (!cap) return;
      var chip = document.createElement("span");
      chip.className = "reuse-chip";
      chip.dataset.capsuleId = id;
      chip.title = cap.name;
      chip.innerHTML =
        '<span class="reuse-chip-serial">' +
        escapeHtml(getCapsuleSerial(cap)) +
        "</span>" +
        '<span class="reuse-chip-name">' +
        escapeHtml(shortName(cap.name)) +
        "</span>";
      els.usedCapsuleDock.appendChild(chip);
    });
    if (els.generationInputNote) {
      els.generationInputNote.textContent = formatText(usedCapsuleSelectionMode === "auto_match" ? "generationResolved" : "generationManual", {
        count: usedCapsuleIds.length,
      });
    }
    updateEnrichedContentToggle();
  }

  function renderGeneratedPackage(showPreview) {
    var pkg = data.generatedPackage || { folder: "Current Runtime", files: [] };
    var folder = pkg.folder || "new_project/";
    var folderParts = String(folder).split(/[/\\]/).filter(Boolean);
    var folderLabel = folderParts.length ? folderParts[folderParts.length - 1] + "/" : folder;
    var files = pkg.files || [];
    var visibleFiles = userFacingFiles(files);
    if (!visibleFiles.length) visibleFiles = files;
    els.generatedTree.innerHTML = renderers.renderFileTree
      ? renderers.renderFileTree(folderLabel, visibleFiles, escapeHtml)
      : '<div class="folder">' + escapeHtml(folderLabel) + "</div>";
    els.generatedPreview.classList.remove("hidden");
    if (els.generatedPackage) {
      els.generatedPackage.classList.remove("runtime-read-only");
      els.generatedPackage.classList.toggle("is-ready", !!showPreview);
    }
    var count = usedCapsuleIds.length;
    els.genCapsulesUsed.innerHTML =
      '<span class="meta-icon" aria-hidden="true">◫</span> ' + count + " " + t("capsulesUsed");
    if (data.lunaPack && data.lunaPack.pack_id && els.genCapsulesUsed) {
      els.genCapsulesUsed.innerHTML +=
        ' · <span class="luna-pack-note" title="' +
        escapeHtml(data.lunaPack.pack_id) +
        '">' +
        escapeHtml(t("lunaPackIndexed")) +
        "</span>";
    }
    if (data.contentAwareGenerate && data.contentAwareGenerate.enabled && els.genCapsulesUsed) {
      var sn = data.contentAwareGenerate.snippetsUsed || 0;
      els.genCapsulesUsed.innerHTML +=
        ' · <span class="content-aware-note">' +
        escapeHtml(t("contentAwarePreview")) +
        " · " +
        escapeHtml(t("snippets")) +
        " " +
        sn +
        "</span>";
    }
    updatePreviewPackageActions(!!showPreview);
    var openFolder = $("btn-open-folder");
    if (openFolder) {
      openFolder.classList.toggle("hidden", isLumoLiteReadOnly() || !lastPreviewPath);
    }
    applyLumoLiteRuntimeView();
  }

  function updatePreviewPackageActions(show) {
    if (!els.previewPackageActions) return;
    var visible = !!(show && hasDesktopBridge() && (!isLumoLiteReadOnly() || canBuildTaskPackPreview()));
    els.previewPackageActions.classList.toggle("hidden", !visible);
  }

  function closePreviewPackageViewer() {
    if (els.previewPackageViewer) els.previewPackageViewer.classList.add("hidden");
    currentPreviewPackageId = "";
    previewViewerMode = "view";
    updatePreviewViewerExportActions(false);
  }

  function renderLumoLiteArtifacts(payload) {
    if (!els.lumoArtifactsBody) return;
    var artifacts = payload && Array.isArray(payload.artifacts) ? payload.artifacts : lumoLiteArtifacts;
    lumoLiteArtifacts = artifacts.slice();
    els.lumoArtifactsBody.innerHTML = artifactRenderers.renderArtifactList
      ? artifactRenderers.renderArtifactList(artifacts, shortExportPath, escapeHtml)
      : "";
  }

  function renderLumoLiteArtifactDetail(payload) {
    if (!els.lumoArtifactsBody || !payload || !payload.ok) return;
    els.lumoArtifactsBody.innerHTML = artifactRenderers.renderArtifactDetail
      ? artifactRenderers.renderArtifactDetail(payload, escapeHtml)
      : "";
  }

  function openLumoArtifactsPopover() {
    if (!els.lumoArtifactsPopover) return;
    els.lumoArtifactsPopover.classList.remove("hidden");
    if (hasDesktopBridge() && desktopBridge && typeof desktopBridge.list_lumo_lite_artifacts === "function") {
      bridgeCall("list_lumo_lite_artifacts").then(function (raw) {
        var result = parseBridgeJson(raw);
        if (result && result.ok) renderLumoLiteArtifacts(result);
        else renderLumoLiteArtifacts({ artifacts: lumoLiteArtifacts });
      });
      return;
    }
    renderLumoLiteArtifacts({ artifacts: lumoLiteArtifacts });
  }

  function handleLumoArtifactAction(target) {
    if (!target) return;
    var viewBtn = target.closest(".btn-artifact-view");
    var copyBtn = target.closest(".btn-artifact-copy");
    var backBtn = target.closest(".btn-artifacts-back");
    if (backBtn) {
      renderLumoLiteArtifacts({ artifacts: lumoLiteArtifacts });
      return;
    }
    if (copyBtn) {
      var path = copyBtn.getAttribute("data-artifact-path") || "";
      if (navigator.clipboard && path) navigator.clipboard.writeText(path);
      if (els.reweaveResponse) els.reweaveResponse.textContent = t("artifactCopied");
      return;
    }
    if (viewBtn && hasDesktopBridge()) {
      bridgeCall("get_lumo_lite_artifact", viewBtn.getAttribute("data-artifact-id") || "").then(function (raw) {
        var result = parseBridgeJson(raw);
        if (result && result.ok) renderLumoLiteArtifactDetail(result);
      });
      return;
    }
  }

  function updatePreviewViewerExportActions(show) {
    if (!els.previewViewerActions) return;
    els.previewViewerActions.classList.toggle("hidden", !show);
  }

  function shortExportPath(path) {
    if (!path) return "";
    var parts = String(path).split(/[/\\]/);
    if (parts.length <= 2) return path;
    return "…/" + parts.slice(-2).join("/");
  }

  function openPreviewPackageViewer(title) {
    if (!els.previewPackageViewer) return;
    if (els.previewViewerTitle) els.previewViewerTitle.textContent = title || "Preview package";
    els.previewPackageViewer.classList.remove("hidden");
  }

  function renderSafetyBadges(safety) {
    safety = safety || {};
    var badges = [];
    if (safety.source_folder_read_at_view_time === false) badges.push("no source read");
    if (safety.source_folder_written === false) badges.push("no source write");
    if (safety.llm_called === false) badges.push("no LLM");
    if (safety.dispatch_called === false) badges.push("no dispatch");
    return badges.map(function (b) {
      return '<span class="preview-safety-badge">' + escapeHtml(b) + "</span>";
    }).join("");
  }

  function renderPreviewViewerPayload(payload) {
    if (!els.previewViewerBody || !payload || !payload.ok) return;
    previewViewerMode = "view";
    var pkg = payload.package || {};
    currentPreviewPackageId = pkg.id || "";
    updatePreviewViewerExportActions(!!(hasDesktopBridge() && currentPreviewPackageId && !isLumoLiteReadOnly()));
    var cag = (payload.provenance && payload.provenance.content_aware_generate) || {};
    var luna = (payload.provenance && payload.provenance.luna) || {};
    var snippets = payload.snippetsUsed || {};
    var exports = payload.exports || [];
    var html = "";
    html += '<p class="preview-viewer-mode"><strong>Mode:</strong> ' + escapeHtml(pkg.mode || "metadata_only") + "</p>";
    if (pkg.created_at) {
      html += '<p class="preview-viewer-meta">' + escapeHtml(pkg.created_at) + "</p>";
    }
    html += '<p class="preview-viewer-label">Files</p><ul class="preview-viewer-list">';
    (pkg.files || []).forEach(function (f) {
      html += "<li>" + escapeHtml(f) + "</li>";
    });
    html += "</ul>";
    html += '<p class="preview-viewer-label">Capsules used (' + (payload.capsulesUsed || []).length + ")</p>";
    html += '<ul class="preview-viewer-list">';
    (payload.capsulesUsed || []).slice(0, 6).forEach(function (cap) {
      html += "<li>" + escapeHtml(cap.name || cap.capsule_id || cap.id || "capsule") + "</li>";
    });
    html += "</ul>";
    html += '<p class="preview-viewer-label">Snippets used</p>';
    if (snippets.enabled) {
      html += '<p class="preview-viewer-meta">' + (snippets.count || 0) + " manifest entries</p>";
      html += '<ul class="preview-viewer-list">';
      (snippets.items || []).slice(0, 4).forEach(function (sn) {
        html += "<li>" + escapeHtml((sn.relative_path || "file") + " · " + (sn.excerpt_chars || 0) + " chars") + "</li>";
      });
      html += "</ul>";
    } else {
      html += '<p class="preview-viewer-meta">Not used</p>';
    }
    html += '<p class="preview-viewer-label">Provenance</p>';
    html += '<p class="preview-viewer-meta">Content-aware: ' + (cag.enabled ? "enabled" : "off") + "</p>";
    if (luna && luna.pack_id) {
      html += '<p class="preview-viewer-meta">Luna pack: ' + escapeHtml(String(luna.pack_id)) + "</p>";
    } else if (luna && luna.ok === false) {
      html += '<p class="preview-viewer-meta">Luna pack: failed</p>';
    } else {
      html += '<p class="preview-viewer-meta">Luna pack: —</p>';
    }
    if (exports.length) {
      html += '<p class="preview-viewer-label">Exports</p>';
      html += '<ul class="preview-viewer-list">';
      exports.slice(0, 3).forEach(function (ex) {
        html +=
          "<li>" +
          escapeHtml((ex.mode || "export") + " · " + shortExportPath(ex.export_path)) +
          "</li>";
      });
      html += "</ul>";
    }
    html += '<div class="preview-safety-badges">' + renderSafetyBadges(payload.safety) + "</div>";
    els.previewViewerBody.innerHTML = html;
  }

  function renderPreviewCompareResult(result) {
    if (!els.previewViewerBody || !result || !result.ok) return;
    previewViewerMode = "compare";
    currentPreviewPackageId = "";
    updatePreviewViewerExportActions(false);
    var diff = result.diff || {};
    var html = "";
    html += '<p class="preview-viewer-mode"><strong>Compare</strong></p>';
    html += '<p class="preview-viewer-meta">' + escapeHtml(result.left.id) + " → " + escapeHtml(result.right.id) + "</p>";
    html += '<p class="preview-viewer-meta">' + escapeHtml(result.left.mode) + " → " + escapeHtml(result.right.mode) + "</p>";
    if ((diff.files_added || []).length) {
      html += '<p class="preview-viewer-label">Files added</p><ul class="preview-viewer-list">';
      diff.files_added.forEach(function (f) {
        html += "<li>" + escapeHtml(f) + "</li>";
      });
      html += "</ul>";
    }
    if ((diff.files_removed || []).length) {
      html += '<p class="preview-viewer-label">Files removed</p><ul class="preview-viewer-list">';
      diff.files_removed.forEach(function (f) {
        html += "<li>" + escapeHtml(f) + "</li>";
      });
      html += "</ul>";
    }
    if (diff.content_aware_changed) {
      html += '<p class="preview-viewer-meta content-aware-note">Content-aware changed</p>';
    }
    html += '<p class="preview-viewer-meta">Snippets Δ ' + (diff.snippets_used_delta || 0) + " · Capsules Δ " + (diff.capsules_used_delta || 0) + "</p>";
    if (diff.luna_pack_changed) {
      html += '<p class="preview-viewer-meta">Luna pack reference changed</p>';
    }
    html += '<p class="preview-viewer-meta">Metadata compare only — no code diff</p>';
    els.previewViewerBody.innerHTML = html;
  }

  function handleViewPreviewPackage() {
    if (!hasDesktopBridge()) return;
    bridgeCall("get_latest_preview_package").then(function (raw) {
      var result = parseBridgeJson(raw);
      if (!result || !result.ok) {
        if (els.reweaveResponse) {
          els.reweaveResponse.textContent = (result && result.error) || t("noPreviewPackage");
        }
        return;
      }
      renderPreviewViewerPayload(result);
      openPreviewPackageViewer("Preview package");
    });
  }

  function handleComparePreviewPackages() {
    if (!hasDesktopBridge()) return;
    bridgeCall("compare_preview_packages", JSON.stringify({})).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (!result || !result.ok) {
        if (els.reweaveResponse) {
          els.reweaveResponse.textContent = (result && result.error) || t("noPreviousPackage");
        }
        return;
      }
      renderPreviewCompareResult(result);
      openPreviewPackageViewer("Compare last");
    });
  }

  function handleExportPreviewPackage(mode) {
    if (!hasDesktopBridge() || !currentPreviewPackageId || isLumoLiteReadOnly()) return;
    var bridgeMethod =
      typeof desktopBridge.choose_export_folder_and_export === "function"
        ? "choose_export_folder_and_export"
        : "export_preview_package";
    var payload = {
      packageIdOrPath: currentPreviewPackageId,
      mode: mode || "zip",
    };
    bridgeCall(bridgeMethod, JSON.stringify(payload)).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (result && result.cancelled) return;
      if (result && result.ok && els.reweaveResponse) {
        els.reweaveResponse.textContent = t("exported") + " · " + shortExportPath(result.export_path);
        bridgeCall("get_preview_package", currentPreviewPackageId).then(function (viewRaw) {
          var viewResult = parseBridgeJson(viewRaw);
          if (viewResult && viewResult.ok) renderPreviewViewerPayload(viewResult);
        });
        return;
      }
      if (els.reweaveResponse) {
        els.reweaveResponse.textContent = (result && result.error) || "Export failed";
      }
    });
  }

  function renderHistory(extra) {
    var list = $("history-list");
    list.innerHTML = "";
    var items = (data.history || []).slice();
    if (extra) items.unshift(extra);
    if (items.length === 0) {
      var empty = document.createElement("li");
      empty.className = "history-empty";
      empty.textContent = isLumoLiteReadOnly() ? t("noHistoryReadOnly") : t("noHistory");
      list.appendChild(empty);
      return;
    }
    items.forEach(function (item) {
      var li = document.createElement("li");
      li.innerHTML =
        '<span class="hist-title">' + escapeHtml(item.title) + "</span>" +
        '<span class="hist-meta">' +
        escapeHtml(formatText("historyMeta", { count: item.capsulesUsed, note: item.note })) +
        "</span>";
      list.appendChild(li);
    });
  }

  function renderSources() {
    var count = $("sources-count");
    var list = $("sources-list");
    if (!count || !list) return;
    count.textContent = String((data.sourceBoxes || []).length);
    list.innerHTML = "";
    (data.sourceBoxes || []).forEach(function (src) {
      var li = document.createElement("li");
      var left = document.createElement("span");
      left.textContent = src.label;

      var right = document.createElement("span");
      right.className = "source-status";

      var scan = src.scan_status || "not_scanned";
      if (hasDesktopBridge()) {
        if (preparingSourceIds[src.id] || scanningSourceIds[src.id] || verifyingSourceIds[src.id] || previewingSourceIds[src.id] || reviewingSourceIds[src.id]) {
          right.textContent = sourceScanLabel(src);
        } else if (scan === "not_scanned" && desktopCapability("canScanSourceBox")) {
          var scanBtn = document.createElement("button");
          scanBtn.type = "button";
          scanBtn.className = "btn-ghost btn-source-scan";
          scanBtn.textContent = t("scan");
          scanBtn.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            handleScanSource(src.id);
          });
          right.appendChild(scanBtn);
        } else if (src.draft_status === "drafted" && src.warehouse_status !== "promoted" && desktopCapability("canPromoteDrafts")) {
          var storeBtn = document.createElement("button");
          storeBtn.type = "button";
          storeBtn.className = "btn-ghost btn-source-scan";
          storeBtn.textContent = t("store");
          storeBtn.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            handleStoreSource(src.id);
          });
          right.appendChild(storeBtn);
        } else if (scan === "scanned" && src.warehouse_status !== "promoted" && desktopCapability("canDraftCapsules")) {
          var prepBtn = document.createElement("button");
          prepBtn.type = "button";
          prepBtn.className = "btn-ghost btn-source-scan";
          prepBtn.textContent = t("prepare");
          prepBtn.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            handlePrepareSource(src.id);
          });
          right.appendChild(prepBtn);
        } else {
          var lunaReuse = data.lunaReuseBySource && data.lunaReuseBySource[src.id];
          var verification = data.verificationBySource && data.verificationBySource[src.id];
          if (lunaReuse && lunaReuse.count > 0 && !verification && !isLumoLiteReadOnly()) {
            var verifyBtn = document.createElement("button");
            verifyBtn.type = "button";
            verifyBtn.className = "btn-ghost btn-source-scan";
            verifyBtn.textContent = t("verify");
            verifyBtn.addEventListener("click", function (e) {
              e.preventDefault();
              e.stopPropagation();
              handleVerifySource(src.id);
            });
            right.appendChild(verifyBtn);
          } else if (verification) {
            var governance = data.governancePreviewBySource && data.governancePreviewBySource[src.id];
            if (!governance && !isLumoLiteReadOnly()) {
              var previewBtn = document.createElement("button");
              previewBtn.type = "button";
              previewBtn.className = "btn-ghost btn-source-scan";
              previewBtn.textContent = t("preview");
              previewBtn.addEventListener("click", function (e) {
                e.preventDefault();
                e.stopPropagation();
                handleGovernancePreview(src.id);
              });
              right.appendChild(previewBtn);
            } else {
              var reviewQueue = data.reviewQueueBySource && data.reviewQueueBySource[src.id];
              if (!reviewQueue && !isLumoLiteReadOnly()) {
                var reviewBtn = document.createElement("button");
                reviewBtn.type = "button";
                reviewBtn.className = "btn-ghost btn-source-scan";
                reviewBtn.textContent = t("review");
                reviewBtn.addEventListener("click", function (e) {
                  e.preventDefault();
                  e.stopPropagation();
                  handleCreateReviewQueue(src.id);
                });
                right.appendChild(reviewBtn);
              } else {
                var s = reviewQueue.summary || {};
                var promotedN = 0;
                if (Array.isArray(reviewQueue.items)) {
                  reviewQueue.items.forEach(function (item) {
                    if (item && item.promoted) promotedN += 1;
                  });
                }
                if (data.promotedCountBySource && data.promotedCountBySource[src.id]) {
                  promotedN = Math.max(promotedN, data.promotedCountBySource[src.id]);
                }
                right.textContent =
                  t("review") +
                  ": " +
                  t("pending") +
                  " " +
                  (s.pending || 0) +
                  " / " +
                  t("approved") +
                  " " +
                  (s.approved || 0) +
                  " / " +
                  t("rejected") +
                  " " +
                  (s.rejected || 0) +
                  " / " +
                  t("deferred") +
                  " " +
                  (s.deferred || 0) +
                  (promotedN ? " · " + t("promoted") + " " + promotedN : "");
                appendReviewMiniPanel(li, src.id, reviewQueue);
              }
            }
          } else {
            right.textContent = sourceScanLabel(src);
          }
        }
      } else {
        right.textContent = src.status || t("bound");
      }

      li.appendChild(left);
      li.appendChild(right);
      list.appendChild(li);
    });
  }

  function bindMainEvents() {
    if (mainEventsBound) return;
    mainEventsBound = true;

    $("btn-generate").addEventListener("click", runGenerate);
    var enrichedCheckbox = $("use-enriched-content");
    if (enrichedCheckbox) {
      enrichedCheckbox.addEventListener("change", function () {
        useEnrichedContentPreview = !!enrichedCheckbox.checked;
      });
    }
    var localModelCheckbox = $("use-local-model");
    if (localModelCheckbox) {
      localModelCheckbox.addEventListener("change", function () {
        useBoundedLocalModel = !!localModelCheckbox.checked;
        setLocalModelStatus(useBoundedLocalModel ? "localModelReady" : "localModelOff");
      });
    }
    els.taskInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        runGenerate();
      }
    });

    $("btn-use-in-task").addEventListener("click", function () {
      if (!selectedCapsuleId || usedCapsuleIds.indexOf(selectedCapsuleId) !== -1) return;
      var cap = findCapsule(selectedCapsuleId);
      if (!cap) return;
      if (!isCapsuleGenerateEligible(cap)) {
        els.reweaveResponse.textContent = t("capsuleReadOnlyMessage");
        return;
      }
      var capEl = ensureCapsuleElement(selectedCapsuleId);
      if (!capEl) return;
      setAppState("invoking");
      capEl.classList.add("scan-match");
      emitReuseTrace(capEl, function () {
        if (capEl.parentNode) capEl.classList.remove("scan-match");
        dockCapsule(selectedCapsuleId, true);
        syncAppState();
      });
    });

    $("reader-close").addEventListener("click", hideCapsuleReader);

    $("btn-history").addEventListener("click", function (e) {
      e.stopPropagation();
      togglePopover("history");
    });

    $("btn-sources").addEventListener("click", function (e) {
      e.stopPropagation();
      togglePopover("sources");
    });
    if (els.btnLumoArtifacts) {
      els.btnLumoArtifacts.addEventListener("click", function (e) {
        e.stopPropagation();
        togglePopover("lumo-artifacts");
      });
    }
    if (els.lumoArtifactsBody) {
      els.lumoArtifactsBody.addEventListener("click", function (e) {
        handleLumoArtifactAction(e.target);
      });
    }

    document.querySelectorAll(".popover-close[data-close]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        closeAllPopovers();
      });
    });

    els.backdrop.addEventListener("click", closeAllPopovers);

    document.addEventListener("click", function (e) {
      if (
        !els.reader.classList.contains("hidden") &&
        !els.reader.contains(e.target) &&
        !e.target.closest(".capsule-cartridge")
      ) {
        hideCapsuleReader();
      }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (els.reader && !els.reader.classList.contains("hidden")) hideCapsuleReader();
      closeAllPopovers();
    });

    var addSourceBtn = document.querySelector(".btn-add-source");
    if (addSourceBtn) {
      addSourceBtn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        handleAddSource();
      });
      syncSourceControls();
    }

    $("btn-open-folder").addEventListener("click", function () {
      if (isLumoLiteReadOnly()) {
        els.reweaveResponse.textContent = t("runtimeReadOnlyMessage");
        return;
      }
      if (hasDesktopBridge() && lastPreviewPath) {
        bridgeCall("open_preview_folder", lastPreviewPath).then(function (raw) {
          var result = parseBridgeJson(raw);
          if (result && result.ok) {
            els.reweaveResponse.textContent = t("openFolder");
          } else {
            els.reweaveResponse.textContent = t("openFolderMock");
          }
        });
        return;
      }
      els.reweaveResponse.textContent = t("openFolderMock");
    });

    var btnViewPackage = $("btn-view-package");
    if (btnViewPackage) {
      btnViewPackage.addEventListener("click", function (e) {
        e.preventDefault();
        handleViewPreviewPackage();
      });
    }
    var btnCompareLast = $("btn-compare-last");
    if (btnCompareLast) {
      btnCompareLast.addEventListener("click", function (e) {
        e.preventDefault();
        handleComparePreviewPackages();
      });
    }
    var previewViewerClose = $("preview-viewer-close");
    if (previewViewerClose) {
      previewViewerClose.addEventListener("click", function (e) {
        e.preventDefault();
        closePreviewPackageViewer();
      });
    }
    var btnExportZip = $("btn-export-zip");
    if (btnExportZip) {
      btnExportZip.addEventListener("click", function (e) {
        e.preventDefault();
        handleExportPreviewPackage("zip");
      });
    }
    var btnExportCopy = $("btn-export-copy");
    if (btnExportCopy) {
      btnExportCopy.addEventListener("click", function (e) {
        e.preventDefault();
        handleExportPreviewPackage("copy");
      });
    }

    var langBtn = $("btn-lang");
    if (langBtn) langBtn.addEventListener("click", toggleLocale);

    window.addEventListener("resize", function () {
      if (selectedCapsuleId && !els.reader.classList.contains("hidden")) {
        positionReaderNearCapsule(selectedCapsuleId);
      }
    });
  }

  function togglePopover(which) {
    var historyOpen = !els.historyPopover.classList.contains("hidden");
    var sourcesOpen = !els.sourcesPopover.classList.contains("hidden");
    var artifactsOpen = els.lumoArtifactsPopover && !els.lumoArtifactsPopover.classList.contains("hidden");
    if (els.reader && !els.reader.classList.contains("hidden")) hideCapsuleReader();
    closeAllPopovers();
    if (which === "history" && !historyOpen) {
      els.historyPopover.classList.remove("hidden");
      els.backdrop.classList.remove("hidden");
      $("btn-history").setAttribute("aria-expanded", "true");
    } else if (which === "sources" && !sourcesOpen) {
      els.sourcesPopover.classList.remove("hidden");
      els.backdrop.classList.remove("hidden");
      $("btn-sources").setAttribute("aria-expanded", "true");
    } else if (which === "lumo-artifacts" && !artifactsOpen) {
      openLumoArtifactsPopover();
      els.backdrop.classList.remove("hidden");
      if (els.btnLumoArtifacts) els.btnLumoArtifacts.setAttribute("aria-expanded", "true");
    }
  }

  function closeAllPopovers() {
    els.historyPopover.classList.add("hidden");
    els.sourcesPopover.classList.add("hidden");
    if (els.lumoArtifactsPopover) els.lumoArtifactsPopover.classList.add("hidden");
    els.backdrop.classList.add("hidden");
    $("btn-history").setAttribute("aria-expanded", "false");
    $("btn-sources").setAttribute("aria-expanded", "false");
    if (els.btnLumoArtifacts) els.btnLumoArtifacts.setAttribute("aria-expanded", "false");
  }

  function ensureCapsuleElement(id) {
    var chipEl = els.capsuleStrip.querySelector('[data-capsule-id="' + id + '"]');
    if (chipEl) return chipEl;

    var cap = findCapsule(id);
    if (!cap) return null;

    var visible = getVisibleCapsules();
    var onScreen = visible.some(function (c) {
      return c.id === id;
    });
    if (!onScreen) return null;

    return els.capsuleStrip.querySelector('[data-capsule-id="' + id + '"]');
  }

  function runGenerate() {
    if (isGenerating) return;
    if (!desktopCapability("canGeneratePreview")) {
      els.reweaveResponse.textContent = t("runtimeReadOnlyMessage");
      return;
    }
    var text = els.taskInput.value.trim() || data.sampleTask || t("newTask");
    usedCapsuleSelectionMode = usedCapsuleSelectionMode === "manual" && usedCapsuleIds.length > 0 ? "manual" : "auto_match";
    var ids = usedCapsuleSelectionMode === "manual" ? usedCapsuleIds.slice() : [];
    if (!ids.length && !canBuildTaskPackPreview()) {
      els.reweaveResponse.textContent = t("selecting");
      return;
    }

    notifyDesktopGenerate(text, ids);
    if (useBoundedLocalModel) setLocalModelStatus("localModelRunning");

    isGenerating = true;
    setAppState("invoking");
    els.btnGenerate.disabled = true;
    usedCapsuleIds = [];
    renderUsedChips();
    els.reweaveResponse.textContent = t("selecting");
    if (els.taskBay) els.taskBay.classList.add("is-invoking");

    var dockFrame = document.querySelector(".capsule-window-frame");
    if (dockFrame) dockFrame.classList.add("dock-scanning");

    function finishBatch() {
      renderCapsuleStrip();
      if (dockFrame) dockFrame.classList.remove("dock-scanning");
      if (els.taskBay) els.taskBay.classList.remove("is-invoking");
      finishGenerate(text, usedCapsuleIds.length);
    }

    function processNext(index) {
      if (index >= ids.length) {
        finishBatch();
        return;
      }
      invokeCapsule(ids[index], function () {
        setTimeout(function () {
          processNext(index + 1);
        }, 120);
      });
    }

    setTimeout(function () {
      processNext(0);
    }, 420);
  }

  function invokeCapsule(id, done) {
    var cap = findCapsule(id);
    if (!cap) {
      done();
      return;
    }

    var chipEl = ensureCapsuleElement(id);
    if (!chipEl) {
      dockCapsule(id, false);
      done();
      return;
    }

    chipEl.classList.add("scan-match");
    setTimeout(function () {
      var liveEl = els.capsuleStrip.querySelector('[data-capsule-id="' + id + '"]') || chipEl;
      emitReuseTrace(liveEl, function () {
        if (liveEl.parentNode) liveEl.classList.remove("scan-match");
        dockCapsule(id, false);
        done();
      });
    }, 200);
  }

  function emitReuseTrace(fromEl, callback) {
    if (prefersReducedMotion()) {
      callback();
      return;
    }
    var fromRect = fromEl.getBoundingClientRect();
    var dockRect = els.usedCapsuleDock.getBoundingClientRect();
    var slotIndex = usedCapsuleIds.length;
    var targetX = dockRect.left + 10 + slotIndex * 72;
    var targetY = dockRect.top + dockRect.height * 0.5;
    var startX = fromRect.left + fromRect.width * 0.5;
    var startY = fromRect.bottom - 2;
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    var path = document.createElementNS(svg.namespaceURI, "path");
    var midY = Math.min(startY + 36, targetY);
    svg.setAttribute("class", "reuse-trace-svg");
    path.setAttribute("pathLength", "1");
    path.setAttribute(
      "d",
      "M" + startX + " " + startY + " C " + startX + " " + midY + ", " + targetX + " " + midY + ", " + targetX + " " + targetY
    );
    svg.appendChild(path);
    document.body.appendChild(svg);

    setTimeout(function () {
      svg.remove();
      callback();
    }, 300);
  }

  function dockCapsule(id, single) {
    var cap = findCapsule(id);
    if (!isCapsuleGenerateEligible(cap)) {
      return;
    }
    if (usedCapsuleIds.indexOf(id) === -1) {
      usedCapsuleIds.push(id);
    }
    usedCapsuleSelectionMode = "manual";
    renderUsedChips();
    if (single) {
      var cap = findCapsule(id);
      if (cap) {
        els.reweaveResponse.textContent =
          getCapsuleSerial(cap) +
          " " +
          cap.name +
          " " +
          t("docked") +
          " " +
          t("generationManual").replace("{count}", String(usedCapsuleIds.length));
      }
    }
  }

  function finishGenerate(taskText, count, localeOnly) {
    function blockReadyRender(message) {
      isGenerating = false;
      pendingGeneratePromise = null;
      if (useBoundedLocalModel) setLocalModelStatus("localModelFallback");
      if (els.taskBay) els.taskBay.classList.remove("is-invoking");
      if (isLumoLiteReadOnly()) applyLumoLiteRuntimeView();
      if (els.btnGenerate) els.btnGenerate.disabled = !canBuildTaskPackPreview();
      if (els.reweaveResponse) els.reweaveResponse.textContent = message;
      setAppState("error");
    }

    function finalize() {
      renderGeneratedPackage(true);
      if (els.generatedPackage && !prefersReducedMotion()) {
        els.generatedPackage.classList.remove("result-reveal");
        void els.generatedPackage.offsetWidth;
        els.generatedPackage.classList.add("result-reveal");
        setTimeout(function () {
          els.generatedPackage.classList.remove("result-reveal");
        }, 300);
      }
      els.reweaveResponse.textContent = previewAcceptanceText(lastPreviewAcceptance) || formatText("readyResponse", { count: count });
      if (!localeOnly) {
        renderHistory({
          title: taskText.length > 28 ? taskText.slice(0, 28) + "…" : taskText,
          capsulesUsed: count,
          note: lastPreviewPath ? t("localPreview") : t("previewPackage"),
        });
      }
      isGenerating = false;
      els.btnGenerate.disabled = false;
      setAppState("ready");
      pendingGeneratePromise = null;
    }

    if (pendingGeneratePromise) {
      pendingGeneratePromise.then(function (raw) {
        var result = parseBridgeJson(raw);
        if ((isLumoLiteReadOnly() && !canBuildTaskPackPreview()) || !result || result.ok === false) {
          blockReadyRender(
            result && result.previewAcceptance
              ? previewAcceptanceText(result.previewAcceptance)
              : (isLumoLiteReadOnly() ? t("taskPackUnavailable") : t("generationFailed"))
          );
          return;
        }
        applyGenerateResult(result);
        count = usedCapsuleIds.length;
        finalize();
      }).catch(function () {
        blockReadyRender(t("generationFailed"));
      });
      return;
    }
    if (isLumoLiteReadOnly() && !canBuildTaskPackPreview()) {
      blockReadyRender(t("runtimeReadOnlyMessage"));
      return;
    }
    finalize();
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function getIntegrationState() {
    return {
      appState: appState,
      selectedCapsuleId: selectedCapsuleId,
      usedCapsuleIds: usedCapsuleIds.slice(),
      taskText: els.taskInput ? els.taskInput.value : "",
      isGenerating: isGenerating,
      bridge: {
        available: hasDesktopBridge(),
        ready: bridgeReady,
        shell: desktopShellState,
        previewPath: lastPreviewPath || null,
      },
    };
  }

  window.ReweavePrototype = {
    getState: getIntegrationState,
    setAppState: setAppState,
  };

  function boot() {
    initWelcome();
    loadMockData(function (err) {
      if (err) {
        console.error(err);
        $("btn-select-folder").textContent = t("loadFailed");
        return;
      }
      applyLocale();
      initDesktopBridge(function () {
        var params = new URLSearchParams(window.location.search);
        var skipWelcome =
          params.get("main") === "1" ||
          !!(desktopShellState && desktopShellState.skipWelcome && !isLumoLiteReadOnly());
        if (skipWelcome) {
          initMain();
        } else {
          syncWelcomeSourceBoxMode();
        }
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
