(function () {
  "use strict";

  var data = null;
  var selectedCapsuleId = null;
  var usedCapsuleIds = [];
  var appState = "idle";
  var CAPSULES_VISIBLE = 5;
  var AUTO_SELECT_COUNT = 3;
  var isGenerating = false;
  var mainEventsBound = false;
  var locale = localStorage.getItem("reweave_locale") || "zh";

  var STR = {
    zh: {
      privacy: "All local. Nothing leaves your machine.",
      history: "History",
      taskPlaceholder: "描述你要重新织出的工具或页面...",
      usedPlaceholder: "选中的胶囊将停靠在这里",
      generationAuto: "未手动选择时会自动匹配胶囊。",
      generationManual: "Generation input: {count} selected. Generate will use exactly these capsules.",
      selecting: "Reweave 正在挑选胶囊…",
      readyResponse: "Reweave 使用了 {count} 个胶囊，并已准备本地预览包。",
      docked: "已停靠到任务区。",
      openFolder: "已在 Finder 中打开本地预览文件夹。",
      openFolderMock: "仅本地预览 — 打开文件夹为模拟操作。",
      useInTask: "Use in task",
      openCapsule: "Open capsule",
      capsulesUsed: "个胶囊已使用",
      readerLabel: "Capsule Reader",
      fromSource: "from",
      tagsPrefix: "tags",
      rolePrefix: "role",
    },
    en: {
      privacy: "All local. Nothing leaves your machine.",
      history: "History",
      taskPlaceholder: "Describe the tool or page to reweave...",
      usedPlaceholder: "Selected capsules dock here",
      generationAuto: "Generate will auto-pick capsules if none are selected.",
      generationManual: "Generation input: {count} selected. Generate will use exactly these capsules.",
      selecting: "Reweave is selecting capsules…",
      readyResponse: "Reweave used {count} capsules and prepared a local preview package.",
      docked: "docked for this task.",
      openFolder: "Opened local preview folder.",
      openFolderMock: "Local preview only — folder open is mocked.",
      useInTask: "Use in task",
      openCapsule: "Open capsule",
      capsulesUsed: "capsules used",
      readerLabel: "Capsule Reader",
      fromSource: "from",
      tagsPrefix: "tags",
      rolePrefix: "role",
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
  var currentPreviewPackageId = "";
  var previewViewerMode = "view";
  var lumoLiteArtifacts = [];

  function $(id) {
    return document.getElementById(id);
  }

  function parseBridgeJson(raw) {
    if (!raw) return null;
    if (typeof raw === "object") return raw;
    try {
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function hasDesktopBridge() {
    return !!(desktopBridge && typeof desktopBridge.choose_source_folder === "function");
  }

  function desktopCapability(name) {
    if (!desktopShellState) return false;
    if (Object.prototype.hasOwnProperty.call(desktopShellState, name)) {
      return desktopShellState[name] === true;
    }
    return false;
  }

  function isLumoLiteReadOnly() {
    return !!(
      (desktopShellState &&
        (desktopShellState.engine === "lumo_lite" ||
          desktopShellState.backend === "lumo_lite" ||
          desktopShellState.lumoLiteMode)) ||
      (data && data.lumoLiteMode)
    );
  }

  function isLumoLiteState(state) {
    return !!(state && (state.engine === "lumo_lite" || state.backend === "lumo_lite" || state.lumoLiteMode));
  }

  function canBuildTaskPackPreview() {
    return isLumoLiteReadOnly() && desktopCapability("canGeneratePreview");
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
    data.lumoLiteMode = "read_only_runtime_artifact_viewer";
    data.lumoLiteRuntimeSummary = {
      line: "Current Runtime / read-only",
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
    bindBtn.textContent = "Bind Source Box";
    bindBtn.disabled = !canBind;
    bindBtn.setAttribute("aria-disabled", canBind ? "false" : "true");
    bindBtn.title = canBind ? "" : "Source Box binding is not enabled.";
    if (note) {
      note.textContent = readOnly
        ? "Bind locally, scan read-only, no source writes."
        : "Choose a source folder to clean into capsules.";
    }
    if (runtimeBtn) runtimeBtn.classList.toggle("hidden", !readOnly);
  }

  function getLumoLiteRuntimeSummary() {
    if (desktopShellState && desktopShellState.lumoLiteRuntimeSummary) {
      return desktopShellState.lumoLiteRuntimeSummary;
    }
    return data && data.lumoLiteRuntimeSummary ? data.lumoLiteRuntimeSummary : null;
  }

  function applyLumoLiteRuntimeView() {
    if (!isLumoLiteReadOnly() || !els.taskInput) return;
    var summary = getLumoLiteRuntimeSummary() || {};
    var taskPackPreview = canBuildTaskPackPreview();
    var hasTaskPackPreview =
      taskPackPreview &&
      !!lastPreviewPath &&
      data.generatedPackage &&
      Array.isArray(data.generatedPackage.files) &&
      data.generatedPackage.files.indexOf("task_pack.json") >= 0;
    var capsulesUsed = Number(summary.capsules_used || 0);
    var traceText = summary.trace_available ? "Trace available" : "Trace unavailable";
    var previewText = hasTaskPackPreview ? "Task Pack preview ready" : summary.preview_ready ? "Preview ready" : "Preview not ready";
    var responseText = summary.product_capability_line || summary.line || summary.acceptance_line || "Current Runtime / read-only";
    var sourceWrites = summary.source_project_write_count;
    if (sourceWrites === undefined || sourceWrites === null || sourceWrites === "") sourceWrites = "unknown";

    if (!taskPackPreview) els.taskInput.value = "";
    els.taskInput.placeholder = taskPackPreview ? "Describe a small Task Pack preview..." : "Current Runtime / read-only";
    els.taskInput.disabled = !taskPackPreview;
    if (els.btnGenerate) {
      els.btnGenerate.disabled = !taskPackPreview;
      els.btnGenerate.setAttribute("aria-disabled", taskPackPreview ? "false" : "true");
      els.btnGenerate.title = taskPackPreview ? "Build Task Pack preview" : "Current Runtime is read-only";
      els.btnGenerate.classList.toggle("hidden", !taskPackPreview);
    }
    if (els.generatedPackage) {
      els.generatedPackage.classList.toggle("runtime-read-only", !hasTaskPackPreview);
    }
    var title = document.querySelector(".generated-title");
    if (title) title.textContent = hasTaskPackPreview ? "Task Pack Preview" : "Current Runtime";
    if (els.generatedTree && !hasTaskPackPreview) {
      els.generatedTree.innerHTML =
        '<div class="folder">Runtime artifacts</div>' +
        '<div class="file highlight">frontend_runtime_state.json</div>' +
        '<div class="file highlight-subtle">capsules_used / trace receipts</div>';
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
          ? capsulesUsed + " capsules linked to this runtime"
          : "No capsule usage reported by current runtime";
      els.usedCapsuleDock.innerHTML =
        '<span class="used-placeholder runtime-used-note">' + escapeHtml(usedText) + "</span>";
    }
    if (els.genCapsulesUsed && !hasTaskPackPreview) {
      els.genCapsulesUsed.innerHTML =
        '<span class="meta-icon" aria-hidden="true">◫</span> Capsules used: ' + capsulesUsed;
    }
    var metaLines = document.querySelectorAll(".generated-meta .meta-line");
    if (metaLines[1]) metaLines[1].innerHTML = '<span class="meta-icon" aria-hidden="true">◎</span> ' + previewText;
    if (metaLines[2]) metaLines[2].innerHTML = '<span class="meta-icon" aria-hidden="true">⛓</span> ' + traceText;
    if (els.runtimeSidecarMode) els.runtimeSidecarMode.textContent = "read-only";
    if (els.runtimeSidecarSource) {
      els.runtimeSidecarSource.textContent = summary.acceptance_line || "Capsule state and trace receipts";
    }
    if (els.runtimeSidecarStatus) {
      els.runtimeSidecarStatus.textContent =
        "source writes: " +
        sourceWrites +
        "\ntrace: " +
        (summary.trace_available ? "ready" : "unavailable") +
        "\npreview: " +
        (summary.preview_ready ? "ready" : "not ready") +
        "\ncapsules: " +
        capsulesUsed;
    }
    if (els.previewPackageActions) els.previewPackageActions.classList.add("hidden");
    var openFolder = $("btn-open-folder");
    if (openFolder) openFolder.classList.add("hidden");
    if (els.reweaveResponse) els.reweaveResponse.textContent = responseText;
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
    var entry = {
      id: source.id,
      label: source.label,
      path: source.path,
      status: source.status || "bound",
      scan_status: source.scan_status || "not_scanned",
      draft_status: source.draft_status || "not_drafted",
      warehouse_status: source.warehouse_status || "",
      last_scanned_at: source.last_scanned_at,
      last_drafted_at: source.last_drafted_at,
      last_promoted_at: source.last_promoted_at,
      promoted_capsule_count: source.promoted_capsule_count,
      last_error: source.last_error,
    };
    if (idx >= 0) {
      data.sourceBoxes[idx] = entry;
    } else {
      data.sourceBoxes.push(entry);
    }
  }

  function normalizeDockCapsule(c) {
    if (!c) return null;
    var src = c.source;
    var sourceLabel = typeof src === "string" ? src : (src && src.label) || "";
    var sourceId = c.source_id || (src && src.source_id) || "";
    return {
      id: c.id,
      name: c.name,
      type: c.type,
      serial: c.serial,
      icon: c.icon || "◫",
      source: sourceLabel,
      source_id: sourceId,
      source_box: typeof src === "object" && src ? src : c.source_box || null,
      tags: c.tags || [],
      role: c.role || "",
      preview: c.preview || [],
      status: c.status || "active",
      origin: c.origin,
      risk: c.risk,
      content_mode: c.content_mode,
      lumo_lite_receipt: c.lumo_lite_receipt,
      lineage: c.lineage,
      snippet: c.snippet,
      content_enrichment: c.content_enrichment,
      content_risk: c.content_risk,
    };
  }

  function isMetadataCapsule(cap) {
    return !!(
      cap &&
      (cap.content_mode === "metadata_snippet" ||
        cap.content_mode === "metadata_only" ||
        cap.risk === "metadata_only_promoted" ||
        cap.origin === "lumo_lite_capsule_warehouse" ||
        cap.origin === "manual_promote")
    );
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
        return {
          id: s.id,
          label: s.label,
          path: s.path,
          status: s.status || "bound",
          scan_status: s.scan_status || "not_scanned",
          draft_status: s.draft_status || "not_drafted",
          warehouse_status: s.warehouse_status || "",
          last_scanned_at: s.last_scanned_at,
          last_drafted_at: s.last_drafted_at,
          last_promoted_at: s.last_promoted_at,
          promoted_capsule_count: s.promoted_capsule_count,
          last_error: s.last_error,
        };
      });
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
      if (els.reweaveResponse) els.reweaveResponse.textContent = "Lumo Lite state is read-only.";
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
      warnBtn.textContent = "Warnings " + warnings.length;
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
        tBadge.textContent = "truncated";
        badges.appendChild(tBadge);
      }
      if (snip.redacted) {
        var rBadge = document.createElement("span");
        rBadge.className = "reader-snippet-badge reader-snippet-badge-redacted";
        rBadge.textContent = "redacted";
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
          btn.textContent = decision === "approved" ? "Approve" : decision === "rejected" ? "Reject" : "Defer";
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
          promoteBtn.textContent = "Promote";
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
        tag.textContent = item.promoted ? "Promoted" : item.decision;
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
    if (preparingSourceIds[src.id]) return "Preparing...";
    if (scanningSourceIds[src.id]) return "Scanning...";
    if (verifyingSourceIds[src.id]) return "Verifying...";
    if (previewingSourceIds[src.id]) return "Previewing...";
    if (reviewingSourceIds[src.id]) return "Reviewing...";
    if (src.status === "read_only" || src.scan_status === "read_only") return "Read-only";
    if (src.warehouse_status === "promoted") {
      var n = src.promoted_capsule_count;
      var base = n ? n + " capsules" : "Ready";
      if (data.lunaReuseBySource && data.lunaReuseBySource[src.id]) {
        return base + " · Suggested by Luna";
      }
      return base;
    }
    var scan = src.scan_status || "not_scanned";
    if (scan === "scanned") return "Scanned";
    if (scan === "failed") return "Failed";
    return "Not scanned";
  }

  function getGenerateCandidateIds() {
    if (usedCapsuleIds.length > 0) return usedCapsuleIds.slice();
    var text = els.taskInput ? els.taskInput.value.trim() : "";
    return resolveGenerateIds(text || (data && data.sampleTask) || "New tool");
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

  function notifyDesktopGenerate(text, ids) {
    if (!hasDesktopBridge()) {
      pendingGeneratePromise = null;
      return Promise.resolve(null);
    }
    var payload = {
      taskText: text,
      capsuleIds: ids,
      capsules: ids.map(findCapsule).filter(Boolean),
      selectionMode: usedCapsuleIds.length > 0 ? "manual" : "auto_match",
      useEnrichedContent: !!(useEnrichedContentPreview && anyEnrichedInIds(ids)),
      sourceBoxes: (data.sourceBoxes || []).map(function (s) {
        return { id: s.id, label: s.label, path: s.path || "", status: s.status };
      }),
    };
    pendingGeneratePromise = bridgeCall("notify_generate", JSON.stringify(payload));
    return pendingGeneratePromise;
  }

  function applyGenerateResult(result) {
    if (!result || !result.ok) return;
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
    if (cap && cap.serial) return cap.serial;
    if (!cap || !cap.id) return "00";
    var h = 0;
    for (var i = 0; i < cap.id.length; i += 1) {
      h = (h * 31 + cap.id.charCodeAt(i)) % 997;
    }
    return ("0" + h.toString(16)).slice(-2).toUpperCase();
  }

  function applyLocale() {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var key = el.getAttribute("data-i18n");
      if (key && t(key)) el.textContent = t(key);
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
          ? t("generationManual").replace("{count}", String(usedCapsuleIds.length))
          : t("generationAuto");
    }
    var useBtn = $("btn-use-in-task");
    if (useBtn) useBtn.textContent = t("useInTask");
    var openCapBtn = $("btn-open-capsule");
    if (openCapBtn) openCapBtn.textContent = t("openCapsule");
    var readerLabel = document.querySelector(".reader-slot-label");
    if (readerLabel) readerLabel.textContent = t("readerLabel").toUpperCase();
    applyLumoLiteRuntimeView();
  }

  function toggleLocale() {
    locale = locale === "zh" ? "en" : "zh";
    localStorage.setItem("reweave_locale", locale);
    applyLocale();
    renderUsedChips();
    if (appState === "ready" && usedCapsuleIds.length > 0) {
      finishGenerate(els.taskInput.value.trim() || data.sampleTask || "New tool", usedCapsuleIds.length, true);
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
    if (data.sampleTask) {
      els.taskInput.value = data.sampleTask;
    }
    els.reweaveResponse.textContent = "";
    setAppState("idle");
    applyLumoLiteRuntimeView();
    openFirstLumoLiteCapsule();
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
  }

  function shortName(name) {
    if (!name) return name;
    if (name.length <= 14) return name;
    return name.slice(0, 13) + "…";
  }

  function getVisibleCapsules() {
    return (data.capsules || []).slice(0, CAPSULES_VISIBLE);
  }

  function capsuleSourceLabel(cap) {
    if (!cap) return "";
    if (typeof cap.source === "string" && cap.source) return cap.source;
    if (cap.source_box && cap.source_box.label) return cap.source_box.label;
    return cap.source_id || "";
  }

  function renderCapsuleStrip() {
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
    $("reader-icon").textContent = cap.icon;
    $("reader-name").textContent = cap.name;
    $("reader-type").textContent = cap.type;
    $("reader-source").textContent = t("fromSource") + " " + capsuleSourceLabel(cap);
    var tagBits = (cap.tags || []).slice();
    if (isMetadataCapsule(cap)) tagBits.unshift("metadata-only");
    if (cap.origin === "manual_promote") tagBits.unshift("manual promote");
    if (cap.origin === "lumo_lite_capsule_warehouse") tagBits.unshift("read-only receipt");
    $("reader-tags").textContent = t("tagsPrefix") + " " + tagBits.join(" · ");
    $("reader-role").textContent = t("rolePrefix") + " " + (cap.role || "");
    var previewLines = [];
    var isLumoLiteReceipt = cap.origin === "lumo_lite_capsule_warehouse";
    if (isMetadataCapsule(cap)) {
      if (cap.risk) previewLines.push("risk: " + cap.risk);
      if (cap.content_mode) previewLines.push("content_mode: " + cap.content_mode);
      if (cap.status && cap.status !== "active") previewLines.push("status: " + cap.status);
      if (cap.content_enrichment && cap.content_enrichment.status === "enriched") {
        previewLines.push(
          "Content preview available · Snippets " + (cap.content_enrichment.snippet_count || 0)
        );
      }
      if (cap.lumo_lite_receipt && typeof cap.lumo_lite_receipt === "object") {
        previewLines.push("lumo_lite_receipt:");
        ["warehouse_status", "invocation_status", "assembly_status", "reason", "trace_path"].forEach(function (key) {
          var val = cap.lumo_lite_receipt[key];
          if (val != null && val !== "") previewLines.push("  " + key + ": " + val);
        });
        (cap.lumo_lite_receipt.evidence_package_paths || []).slice(0, 3).forEach(function (path) {
          previewLines.push("  evidence: " + path);
        });
        (cap.lumo_lite_receipt.blocked_reasons || []).slice(0, 3).forEach(function (reason) {
          previewLines.push("  blocked: " + reason);
        });
      }
      if (!isLumoLiteReceipt && cap.lineage && typeof cap.lineage === "object") {
        previewLines.push("lineage:");
        Object.keys(cap.lineage).forEach(function (key) {
          var val = cap.lineage[key];
          if (val != null && val !== "") previewLines.push("  " + key + ": " + val);
        });
      }
      if (cap.snippet && cap.snippet.description) {
        previewLines.push("", String(cap.snippet.description));
      }
    }
    var bodyPreview = (cap.preview || []).join("\n");
    if (previewLines.length) {
      if (bodyPreview && !isLumoLiteReceipt) previewLines.push("", bodyPreview);
      $("reader-preview").textContent = previewLines.join("\n");
    } else {
      $("reader-preview").textContent = bodyPreview;
    }
    var actions = document.querySelector(".reader-actions");
    if (actions) {
      var useBtn = $("btn-use-in-task");
      if (useBtn) {
        var eligible = isCapsuleGenerateEligible(cap);
        useBtn.disabled = !eligible;
        useBtn.textContent = eligible ? t("useInTask") : "Read-only";
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
        enrichBtn.textContent = "Enrich content";
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
        viewBtn.textContent = "View content";
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

  function openFirstLumoLiteCapsule() {
    if (!isLumoLiteReadOnly() || selectedCapsuleId || !data.capsules.length || !els.reader) return;
    requestAnimationFrame(function () {
      selectCapsule(data.capsules[0].id);
    });
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
      els.generationInputNote.textContent = t("generationManual").replace(
        "{count}",
        String(usedCapsuleIds.length)
      );
    }
    updateEnrichedContentToggle();
  }

  function renderGeneratedPackage(showPreview) {
    var pkg = data.generatedPackage || { folder: "Current Runtime", files: [] };
    var folder = pkg.folder || "new_project/";
    var files = pkg.files || [];
    var html = '<div class="folder">' + escapeHtml(folder) + "</div>";
    files.forEach(function (f) {
      var cls = "file";
      if (f === "capsules_used.json") cls += " highlight";
      else if (f === "snippets_used.json") cls += " highlight";
      else if (f === "provenance.json") cls += " highlight-subtle";
      html += '<div class="' + cls + '">' + escapeHtml(f) + "</div>";
    });
    els.generatedTree.innerHTML = html;
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
        '">Luna pack indexed</span>';
    }
    if (data.contentAwareGenerate && data.contentAwareGenerate.enabled && els.genCapsulesUsed) {
      var sn = data.contentAwareGenerate.snippetsUsed || 0;
      els.genCapsulesUsed.innerHTML +=
        ' · <span class="content-aware-note">Content-aware preview · Snippets ' +
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
    if (!artifacts.length) {
      els.lumoArtifactsBody.innerHTML = '<p class="preview-viewer-meta">No Lumo Lite artifacts in runtime state.</p>';
      return;
    }
    var html = '<p class="preview-viewer-mode"><strong>Read-only local artifacts</strong></p>';
    html += '<ul class="preview-viewer-list lumo-artifact-list">';
    artifacts.forEach(function (item) {
      var status = item.exists ? (item.is_dir ? "folder" : "file") : "missing";
      html +=
        '<li data-artifact-id="' +
        escapeHtml(item.id) +
        '">' +
        '<span class="lumo-artifact-title">' +
        escapeHtml(item.label || item.basename || item.kind) +
        "</span>" +
        '<span class="preview-viewer-meta">' +
        escapeHtml(item.kind + " · " + status) +
        "</span>" +
        '<code class="lumo-artifact-path">' +
        escapeHtml(shortExportPath(item.path || "")) +
        "</code>" +
        '<div class="lumo-artifact-actions">' +
        '<button type="button" class="btn-ghost btn-artifact-view" data-artifact-id="' +
        escapeHtml(item.id) +
        '">View</button>' +
        '<button type="button" class="btn-ghost btn-artifact-copy" data-artifact-path="' +
        escapeHtml(item.path || "") +
        '">Copy path</button>' +
        "</div>" +
        "</li>";
    });
    html += "</ul>";
    els.lumoArtifactsBody.innerHTML = html;
  }

  function renderLumoLiteArtifactDetail(payload) {
    if (!els.lumoArtifactsBody || !payload || !payload.ok) return;
    var item = payload.artifact || {};
    var html = '<p class="preview-viewer-mode"><strong>' + escapeHtml(item.label || item.basename || "Artifact") + "</strong></p>";
    html += '<p class="preview-viewer-meta">' + escapeHtml((item.kind || "artifact") + " · " + (item.exists ? "exists" : "missing")) + "</p>";
    html += '<p class="preview-viewer-meta">' + escapeHtml(item.path || "") + "</p>";
    if (Array.isArray(item.directory_entries) && item.directory_entries.length) {
      html += '<p class="preview-viewer-label">Directory</p><ul class="preview-viewer-list">';
      item.directory_entries.slice(0, 20).forEach(function (entry) {
        html += "<li>" + escapeHtml(entry.kind + " · " + entry.name) + "</li>";
      });
      html += "</ul>";
    }
    if (item.json_preview) {
      html += '<p class="preview-viewer-label">JSON preview</p><pre class="lumo-artifact-preview">' + escapeHtml(JSON.stringify(item.json_preview, null, 2).slice(0, 4000)) + "</pre>";
    } else if (item.text_preview) {
      html += '<p class="preview-viewer-label">Text preview</p><pre class="lumo-artifact-preview">' + escapeHtml(String(item.text_preview).slice(0, 4000)) + "</pre>";
    }
    html += '<p class="preview-viewer-meta">Read-only · no apply · no promote · no dispatch</p>';
    html += '<button type="button" class="btn-ghost btn-artifacts-back">Back to artifacts</button>';
    els.lumoArtifactsBody.innerHTML = html;
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
      if (els.reweaveResponse) els.reweaveResponse.textContent = "Artifact path copied.";
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
          els.reweaveResponse.textContent = (result && result.error) || "No preview package";
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
          els.reweaveResponse.textContent = (result && result.error) || "No previous package";
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
        els.reweaveResponse.textContent = "Exported · " + shortExportPath(result.export_path);
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
      empty.textContent = isLumoLiteReadOnly() ? "No local generation history in read-only mode" : "No history yet";
      list.appendChild(empty);
      return;
    }
    items.forEach(function (item) {
      var li = document.createElement("li");
      li.innerHTML =
        '<span class="hist-title">' + escapeHtml(item.title) + "</span>" +
        '<span class="hist-meta">used ' + item.capsulesUsed + " capsules · " + escapeHtml(item.note) + "</span>";
      list.appendChild(li);
    });
  }

  function renderSources() {
    $("sources-count").textContent = String((data.sourceBoxes || []).length);
    var list = $("sources-list");
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
          scanBtn.textContent = "Scan";
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
          storeBtn.textContent = "Store";
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
          prepBtn.textContent = "Prepare";
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
            verifyBtn.textContent = "Verify";
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
              previewBtn.textContent = "Preview";
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
                reviewBtn.textContent = "Review";
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
                  "Review: Pending " +
                  (s.pending || 0) +
                  " / Approved " +
                  (s.approved || 0) +
                  " / Rejected " +
                  (s.rejected || 0) +
                  " / Deferred " +
                  (s.deferred || 0) +
                  (promotedN ? " · Promoted " + promotedN : "");
                appendReviewMiniPanel(li, src.id, reviewQueue);
              }
            }
          } else {
            right.textContent = sourceScanLabel(src);
          }
        }
      } else {
        right.textContent = src.status || "bound";
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
        els.reweaveResponse.textContent = "Lumo Lite capsule is read-only.";
        return;
      }
      var capEl = ensureCapsuleElement(selectedCapsuleId);
      if (!capEl) return;
      setAppState("invoking");
      capEl.classList.add("scan-match");
      emitReuseTrace(capEl, cap, function () {
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
        els.reweaveResponse.textContent = "Current Runtime is read-only.";
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

  function resolveGenerateIds(taskText) {
    var pool = Array.isArray(data.generateCapsuleIds) ? data.generateCapsuleIds.slice() : [];
    if (!pool.length && Array.isArray(data.capsules) && data.capsules.length) {
      pool = data.capsules.filter(isCapsuleGenerateEligible).map(function (c) {
        return c.id;
      });
    }
    if (!pool.length) return [];

    var task = (taskText || "").toLowerCase();
    var scored = pool.map(function (id) {
      var cap = findCapsule(id);
      if (!cap || !isCapsuleGenerateEligible(cap)) return { id: id, score: -1 };
      var hay = (cap.name + " " + cap.type + " " + (cap.tags || []).join(" ") + " " + cap.role).toLowerCase();
      var score = 0;
      if (task.indexOf("报价") >= 0 && (hay.indexOf("quote") >= 0 || hay.indexOf("client") >= 0)) score += 3;
      if (task.indexOf("客户") >= 0 && hay.indexOf("client") >= 0) score += 2;
      if (task.indexOf("表单") >= 0 && hay.indexOf("form") >= 0) score += 2;
      if (task.indexOf("表格") >= 0 && hay.indexOf("table") >= 0) score += 2;
      if (task.indexOf("导出") >= 0 && hay.indexOf("export") >= 0) score += 2;
      if (task.indexOf("保存") >= 0 && hay.indexOf("save") >= 0) score += 2;
      if (task.indexOf("工具") >= 0 && (hay.indexOf("form") >= 0 || hay.indexOf("logic") >= 0)) score += 1;
      return { id: id, score: score };
    });

    scored.sort(function (a, b) {
      return b.score - a.score;
    });

    var matched = scored.filter(function (s) {
      return s.score > 0;
    });
    if (matched.length > 0) {
      return matched.slice(0, AUTO_SELECT_COUNT).map(function (s) {
        return s.id;
      });
    }
    return pool.slice(0, AUTO_SELECT_COUNT);
  }

  function runGenerate() {
    if (isGenerating) return;
    if (!desktopCapability("canGeneratePreview")) {
      els.reweaveResponse.textContent = "Lumo Lite state is read-only.";
      return;
    }
    var text = els.taskInput.value.trim() || data.sampleTask || "New tool";
    var ids =
      usedCapsuleIds.length > 0 ? usedCapsuleIds.slice() : resolveGenerateIds(text);
    if (!ids.length && !canBuildTaskPackPreview()) {
      els.reweaveResponse.textContent = t("selecting");
      return;
    }

    notifyDesktopGenerate(text, ids);

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
      emitReuseTrace(liveEl, cap, function () {
        if (liveEl.parentNode) liveEl.classList.remove("scan-match");
        dockCapsule(id, false);
        done();
      });
    }, 200);
  }

  function emitReuseTrace(fromEl, cap, callback) {
    var fromRect = fromEl.getBoundingClientRect();
    var dockRect = els.usedCapsuleDock.getBoundingClientRect();
    var slotIndex = usedCapsuleIds.length;
    var targetX = dockRect.left + 10 + slotIndex * 72;
    var targetY = dockRect.top + dockRect.height * 0.5;
    var startX = fromRect.left + fromRect.width * 0.5;
    var startY = fromRect.bottom - 2;
    var dx = targetX - startX;
    var dy = targetY - startY;

    var token = document.createElement("span");
    token.className = "reuse-token-fly";
    token.textContent = getCapsuleSerial(cap);
    token.style.left = startX - 6 + "px";
    token.style.top = startY - 5 + "px";
    token.style.setProperty("--dx", dx + "px");
    token.style.setProperty("--dy", dy + "px");
    document.body.appendChild(token);

    requestAnimationFrame(function () {
      token.classList.add("is-traveling");
    });

    setTimeout(function () {
      token.remove();
      callback();
    }, 280);
  }

  function dockCapsule(id, single) {
    var cap = findCapsule(id);
    if (!isCapsuleGenerateEligible(cap)) {
      return;
    }
    if (usedCapsuleIds.indexOf(id) === -1) {
      usedCapsuleIds.push(id);
    }
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
      if (els.taskBay) els.taskBay.classList.remove("is-invoking");
      if (els.btnGenerate) els.btnGenerate.disabled = true;
      if (els.reweaveResponse) els.reweaveResponse.textContent = message;
      if (isLumoLiteReadOnly()) applyLumoLiteRuntimeView();
    }

    function finalize() {
      renderGeneratedPackage(true);
      els.reweaveResponse.textContent = t("readyResponse").replace("{count}", String(count));
      if (!localeOnly) {
        renderHistory({
          title: taskText.length > 28 ? taskText.slice(0, 28) + "…" : taskText,
          capsulesUsed: count,
          note: lastPreviewPath ? "local preview" : "preview package",
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
          blockReadyRender(isLumoLiteReadOnly() ? "Task Pack preview unavailable." : "Preview generation failed.");
          return;
        }
        applyGenerateResult(result);
        finalize();
      }).catch(function () {
        blockReadyRender("Preview generation failed.");
      });
      return;
    }
    if (isLumoLiteReadOnly() && !canBuildTaskPackPreview()) {
      blockReadyRender("Current Runtime is read-only.");
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
        $("btn-select-folder").textContent = "Load mock-data.json failed (use a local server or file://)";
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
