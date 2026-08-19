(function () {
  "use strict";

  var SECTION_TITLES = {
    frontend: { zh: "前端", en: "Frontend" },
    backend: { zh: "后端", en: "Backend" },
    data: { zh: "数据", en: "Data" },
    infrastructure: { zh: "基础设施", en: "Infrastructure" },
  };

  function create(host) {
    var state = {
      active: false,
      loaded: false,
      view: "compose",
      goal: "",
      workspace: null,
      planToken: "",
      runId: "",
      runKind: "",
      parameterOffer: null,
      parameterValues: [],
      acceptanceRows: [{ input: {}, expected: {} }],
      acceptanceShape: null,
      candidate: null,
      candidateToken: "",
      fileIndex: 0,
      fileMode: "content",
      filePayload: null,
      fileError: "",
      actionResult: "",
      error: "",
      sectionIndex: -1,
      reviewScroll: 0,
      sectionFocusId: "",
      modelPickerOpen: false,
      modelLoading: false,
      models: [],
      modelIndex: -1,
      modelMessage: "",
      modelError: "",
      selectedModel: null,
      warehouseReturnPending: false,
      warehouseReturnFocusId: "",
      warehouseReturnScroll: 0,
      gapDrafts: {},
      acceptanceSuggestionDigest: "",
      handoffError: "",
      handoffMessage: "",
    };
    var bound = false;
    var els = {};

    function $(id) {
      return document.getElementById(id);
    }

    function isZh() {
      return !host.getLocale || host.getLocale() === "zh";
    }

    function copy() {
      return isZh()
        ? {
            entry: "返回产品构建",
            back: "兼容工具",
            kicker: "本地产品流程",
            title: "创建产品",
            productNav: "构建产品",
            targetNav: "目标接入",
            warehouseNav: "胶囊库",
            ingestionNav: "来源入库",
            language: "切换语言",
            statusCompose: "描述目标",
            statusWorking: "正在准备",
            statusQuestions: "等待选择",
            statusReview: "审阅计划",
            statusCandidate: "候选可审阅",
            statusFailed: "已停止",
            evidenceLabel: "交付进度",
            evidenceGoal: "目标",
            evidencePlan: "计划",
            evidenceVerify: "验证",
            evidenceSave: "保存",
            composeTitle: "你想构建什么产品？",
            composeCopy: "先说明产品为谁解决什么问题，以及最重要的结果。",
            goalLabel: "产品目标",
            goalPlaceholder: "描述产品、用户和最重要的结果",
            createPlan: "形成产品计划",
            plannerLabel: "本地规划模型",
            plannerConfigured: "已验证",
            plannerMissing: "需要选择规划模型",
            plannerUnavailable: "产品规划当前不可用",
            plannerConfigure: "更改",
            plannerChoose: "选择模型",
            plannerSelectLabel: "规划模型",
            plannerRefresh: "刷新模型",
            plannerUse: "验证并使用",
            plannerLoading: "正在读取本机模型…",
            plannerVerifying: "正在验证模型身份与输出契约…",
            plannerReady: "规划模型已就绪。",
            plannerNoModels: "未找到符合本地规划规则的模型。",
            plannerOllamaUnavailable: "未检测到本地模型服务。启动后再刷新。",
            plannerDigestChanged: "模型 digest 已变化，请刷新后重新选择。",
            plannerTooLarge: "该模型不符合本地规划参数上限。",
            plannerMoeUnsupported: "当前规划角色不接受混合专家模型。",
            plannerProbeFailed: "模型契约探针未通过，请选择其他模型。",
            plannerFailed: "无法验证该模型；产品目标尚未提交。",
            planningTitle: "正在整理产品计划",
            planningCopy: "Reweave 正在梳理需求、可复用能力和真实缺口。",
            cancel: "取消",
            questionsTitle: "还需要一个决定",
            questionsCopy: "这些选择会改变产品结果，请明确选择后继续。",
            custom: "自定义答案",
            continue: "继续",
            keyOutcomes: "关键结果",
            outcomesCopy: "确认 1–3 个简单例子。系统会在产品运行后逐项核对。",
            input: "输入",
            expected: "应得到",
            addOutcome: "添加一行",
            confirmGenerate: "确认并生成",
            confirmAgent: "确认并交给 Agent",
            handoffTitle: "交给开发 Agent",
            handoffActive: "此计划已授权给 Agent，Reweave 不会自动生成候选。",
            handoffCopied: "完整绑定请求已复制一次。",
            handoffWarning: "只可写入 Reweave 梭子的 stdin，不要粘贴到聊天 Prompt。",
            handoffRevoke: "撤销 Agent 授权",
            handoffRevoked: "Agent 授权已撤销。下一步仍需由你明确选择。",
            handoffReissue: "重新签发",
            handoffDirect: "由 Reweave 继续生成",
            handoffStale: "计划或正式能力事实已变化；旧授权不可继续使用。",
            handoffConflict: "Agent 授权记录不一致，系统已失败关闭。",
            handoffClipboardFailed: "agent_handoff_clipboard_failed",
            handoffIssueFailed: "agent_handoff_create_failed",
            handoffRevokeFailed: "agent_handoff_revoke_failed",
            parameterCopy: "还需确认一个不会由页面或模型改写的固定值。",
            candidateReady: "产品候选已通过运行与关键结果验证。",
            preview: "预览产品",
            save: "保存产品",
            saved: "产品已保存",
            alreadySaved: "同一产品已经保存在该位置",
            opened: "预览窗口已打开",
            files: "文件",
            content: "内容",
            changes: "变化",
            details: "实现详情",
            validation: "运行正常 · 关键结果通过",
            runtimeCheck: "运行状态",
            runtimePassed: "隔离运行已通过",
            goalCheck: "关键结果",
            goalPassed: "用户确认的验收例已通过",
            failedTitle: "这一步未能完成",
            failedCopy: "系统已安全停止，没有写入正式产品或用户项目。",
            gapTargetUnmatched:
              "当前正式能力及可补齐缺口均不符合本次目标，Reweave 已停止规划，未创建正式 capability gap。",
            retry: "重新开始",
            capability: "复用能力",
            gap: "能力缺口",
            acceptance: "验收意图",
            wave: "交付阶段",
            requirement: "需求",
            sectionOpen: "查看章节",
            sectionBack: "返回计划总览",
            sectionWork: "项工作",
            sectionCapabilities: "个复用能力",
            sectionGaps: "个能力缺口",
            sectionNoGaps: "无已识别的工作项缺口",
            sectionNotApplicable: "本产品不需要这一独立层",
            viewInWarehouse: "在胶囊库查看",
            gapProven: "系统已证明的能力边界",
            gapInput: "正式输入",
            gapOutput: "正式输出",
            gapPosition: "串联位置",
            gapAdapter: "预计捕获协议",
            gapBehavior: "确认能力行为",
            gapBehaviorPlaceholder: "说明该 computation 如何把正式输入转换为正式输出",
            gapCases: "能力验收例",
            gapAddCase: "添加验收例",
            gapReason: "暂缓说明／拒绝原因",
            gapAuthorize: "授权创建能力",
            gapDefer: "暂缓",
            gapReject: "拒绝",
            gapDecisionCurrent: "当前决定",
            gapDecisionHistory: "历史回执",
            gapSupersedes: "取代",
            gapDecisionAuthorize: "已授权",
            gapDecisionDefer: "已暂缓",
            gapDecisionReject: "已拒绝",
            gapDecisionSaved: "决定已保存。",
            gapDecisionInvalid: "请填写行为，并完整提供 1–3 个契约合法验收例。",
            gapPrepareSourceProposal: "授权并生成能力提案",
            gapSourceProposalDisclosure:
              "将分别调用一次本地源码提案模型和当前胶囊监督模型；失败后不会自动重试。",
            gapSourceProposalRunning: "正在处理能力提案",
            gapSourceProposalCancel: "取消本次运行",
            gapSourceProposalReview: "审阅待发布能力",
            gapSourceProposalLocked: "授权已锁定，等待源码提案模型调用授权",
            gapSourceProposalZeroWrite: "本次不会写入正式仓库。",
            gapSourceProposalNoSource: "尚未生成源码。",
            gapSourceProposalNoReview: "尚未进入安全检查或发布。",
            gapSourceProposalError: "源码提案授权未能安全锁定。",
            gapBlockGenerate: "计划仍有正式能力缺口，不能确认并生成。",
            gapUnavailable: "当前缺口不能由确定性边界安全投影。",
            gapStale: "正式能力目录已经变化，请重新审阅计划。",
            gapAmbiguous: "存在多个合法缺口位置，系统已失败关闭。",
            replanReady: "新增正式能力已可用",
            replanAction: "使用新增能力重新规划（运行一次规划事务）",
            replanOpen: "打开重新规划结果",
            replanStarted: "已创建唯一的后续计划工作区。",
            replanStale: "正式目录或规划模型已变化，不能再次创建后续工作区。",
            replanAmbiguous: "无法唯一确定新增能力对应的完整组合。",
            replanConflict: "后续计划回执不完整或不一致，系统已失败关闭。",
            slotOnly: "唯一 computation 节点",
            slotBefore: "现有 computation 之前",
            slotAfter: "现有 computation 之后",
            reviewError: "请完整填写关键结果后再继续。",
            unsupported: "当前计划无法用这一版简化验收表单生成候选。",
            chooseAnswer: "请回答所有阻塞问题。",
            cancelled: "已取消",
            noPreview: "候选尚未达到可预览状态。",
            noPlanner: "产品规划尚未就绪",
            goalRequired: "请先描述产品目标",
            fileUnavailable: "这个文件暂时无法显示，但产品仍可预览或保存。",
            implementationSummary: "隔离生成；正式产品、使用记录和用户项目均未写入。",
          }
        : {
            entry: "Return to product builder",
            back: "Compatibility tools",
            kicker: "LOCAL PRODUCT WORKFLOW",
            title: "Create a product",
            productNav: "Build product",
            targetNav: "Target integration",
            warehouseNav: "Capsule library",
            ingestionNav: "Source intake",
            language: "Switch language",
            statusCompose: "Describe goal",
            statusWorking: "Preparing",
            statusQuestions: "Decision needed",
            statusReview: "Review plan",
            statusCandidate: "Candidate ready",
            statusFailed: "Stopped",
            evidenceLabel: "Delivery progress",
            evidenceGoal: "Goal",
            evidencePlan: "Plan",
            evidenceVerify: "Verify",
            evidenceSave: "Save",
            composeTitle: "What do you want to build?",
            composeCopy: "Start with who the product is for, the problem it solves, and the outcome that matters.",
            goalLabel: "Product goal",
            goalPlaceholder: "Describe the product, its users, and the key outcome",
            createPlan: "Form product plan",
            plannerLabel: "Local planning model",
            plannerConfigured: "Verified",
            plannerMissing: "Choose a planning model",
            plannerUnavailable: "Product planning is unavailable",
            plannerConfigure: "Change",
            plannerChoose: "Choose model",
            plannerSelectLabel: "Planning model",
            plannerRefresh: "Refresh models",
            plannerUse: "Verify and use",
            plannerLoading: "Reading local models…",
            plannerVerifying: "Verifying model identity and output contract…",
            plannerReady: "The planning model is ready.",
            plannerNoModels: "No model meets the local planning rules.",
            plannerOllamaUnavailable: "The local model service is unavailable. Start it, then refresh.",
            plannerDigestChanged: "The model digest changed. Refresh and select it again.",
            plannerTooLarge: "This model exceeds the local planning parameter limit.",
            plannerMoeUnsupported: "Mixture-of-experts models are not accepted for this role.",
            plannerProbeFailed: "The model contract probe failed. Choose another model.",
            plannerFailed: "The model could not be verified. The product goal was not submitted.",
            planningTitle: "Preparing your product plan",
            planningCopy: "Reweave is organizing requirements, reusable capabilities, and real gaps.",
            cancel: "Cancel",
            questionsTitle: "One decision is still needed",
            questionsCopy: "These choices change the product outcome. Choose explicitly to continue.",
            custom: "Custom answer",
            continue: "Continue",
            keyOutcomes: "Key outcomes",
            outcomesCopy: "Confirm 1–3 simple examples. Reweave checks each after the product runs.",
            input: "Input",
            expected: "Should produce",
            addOutcome: "Add outcome",
            confirmGenerate: "Confirm and generate",
            confirmAgent: "Confirm and hand to Agent",
            handoffTitle: "Hand off to a developer Agent",
            handoffActive: "This plan is authorized for an Agent. Reweave will not start a candidate automatically.",
            handoffCopied: "The complete bind request was copied once.",
            handoffWarning: "Write it only to the Reweave shuttle stdin. Never paste it into a chat prompt.",
            handoffRevoke: "Revoke Agent authorization",
            handoffRevoked: "Agent authorization is revoked. Choose the next delivery path explicitly.",
            handoffReissue: "Issue again",
            handoffDirect: "Continue in Reweave",
            handoffStale: "The plan or formal capability facts changed; the old authorization cannot be used.",
            handoffConflict: "Agent authorization records conflict. Reweave failed closed.",
            handoffClipboardFailed: "agent_handoff_clipboard_failed",
            handoffIssueFailed: "agent_handoff_create_failed",
            handoffRevokeFailed: "agent_handoff_revoke_failed",
            parameterCopy: "Confirm one fixed value that neither the page nor the model can change.",
            candidateReady: "The product candidate passed runtime and key-outcome validation.",
            preview: "Preview product",
            save: "Save product",
            saved: "Product saved",
            alreadySaved: "The same product is already saved there",
            opened: "Preview window opened",
            files: "Files",
            content: "Content",
            changes: "Changes",
            details: "Implementation details",
            validation: "Runtime passed · Key outcomes passed",
            runtimeCheck: "Runtime",
            runtimePassed: "Isolated runtime passed",
            goalCheck: "Key outcomes",
            goalPassed: "User-confirmed cases passed",
            failedTitle: "This step could not be completed",
            failedCopy: "Reweave stopped safely. No formal product or user project was written.",
            gapTargetUnmatched:
              "The current formal capabilities and fillable gaps do not match this goal. Reweave stopped planning and did not create a formal capability gap.",
            retry: "Start again",
            capability: "Reusable capability",
            gap: "Capability gap",
            acceptance: "Acceptance",
            wave: "Delivery stage",
            requirement: "Requirement",
            sectionOpen: "Review section",
            sectionBack: "Back to plan overview",
            sectionWork: "work items",
            sectionCapabilities: "reusable capabilities",
            sectionGaps: "capability gaps",
            sectionNoGaps: "no identified work-item gaps",
            sectionNotApplicable: "This product does not need this independent layer",
            viewInWarehouse: "View in capsule library",
            gapProven: "System-proven capability boundary",
            gapInput: "Formal input",
            gapOutput: "Formal output",
            gapPosition: "Serial position",
            gapAdapter: "Expected capture protocol",
            gapBehavior: "Confirm capability behavior",
            gapBehaviorPlaceholder: "Describe how this computation transforms the formal input into the formal output",
            gapCases: "Capability acceptance cases",
            gapAddCase: "Add acceptance case",
            gapReason: "Deferral note / rejection reason",
            gapAuthorize: "Authorize capability creation",
            gapDefer: "Defer",
            gapReject: "Reject",
            gapDecisionCurrent: "Current decision",
            gapDecisionHistory: "Receipt history",
            gapSupersedes: "supersedes",
            gapDecisionAuthorize: "Authorized",
            gapDecisionDefer: "Deferred",
            gapDecisionReject: "Rejected",
            gapDecisionSaved: "Decision saved.",
            gapDecisionInvalid: "Provide the behavior and 1–3 complete contract-valid acceptance cases.",
            gapPrepareSourceProposal: "Authorize and generate capability",
            gapSourceProposalDisclosure:
              "This calls the local source-proposal model and current capsule supervisor once each. Failures are not retried.",
            gapSourceProposalRunning: "Processing capability proposal",
            gapSourceProposalCancel: "Cancel this run",
            gapSourceProposalReview: "Review capability for publication",
            gapSourceProposalLocked: "Authorization locked; waiting for source-proposal model approval",
            gapSourceProposalZeroWrite: "The formal warehouse will not be written.",
            gapSourceProposalNoSource: "No source has been generated.",
            gapSourceProposalNoReview: "Safety review and publication have not started.",
            gapSourceProposalError: "The source-proposal authorization could not be locked safely.",
            gapBlockGenerate: "The plan still has a formal capability gap and cannot be confirmed.",
            gapUnavailable: "This gap has no safe deterministic boundary.",
            gapStale: "The formal capability catalog changed. Review the plan again.",
            gapAmbiguous: "More than one legal gap boundary exists. Reweave failed closed.",
            replanReady: "The new formal capability is available",
            replanAction: "Replan with the new capability (one planning transaction)",
            replanOpen: "Open replanned workspace",
            replanStarted: "The unique successor planning workspace was created.",
            replanStale: "The formal catalog or planning model changed. No second workspace can be created.",
            replanAmbiguous: "The complete composition for this new capability is not unique.",
            replanConflict: "The replan receipt is missing or inconsistent. Reweave failed closed.",
            slotOnly: "Only computation node",
            slotBefore: "Before the existing computation",
            slotAfter: "After the existing computation",
            reviewError: "Complete every key outcome before continuing.",
            unsupported: "This plan cannot use the simplified acceptance form in this release.",
            chooseAnswer: "Answer every blocking question.",
            cancelled: "Cancelled",
            noPreview: "The candidate is not ready for preview.",
            noPlanner: "Product planning is not ready",
            goalRequired: "Describe the product goal first",
            fileUnavailable: "This file cannot be shown, but the product can still be previewed or saved.",
            implementationSummary: "Generated in isolation; formal products, usage records, and user projects were not written.",
          };
    }

    function setText(id, value) {
      var element = $(id);
      if (element) element.textContent = String(value || "");
    }

    function call(method, payload) {
      if (!host.call) return Promise.resolve(null);
      return host.call(method, payload || {});
    }

    function errorCode(result, fallback) {
      var error = result && result.error;
      return error && typeof error.code === "string" ? error.code : fallback;
    }

    function fail(code) {
      state.error = String(code || "product_flow_failed");
      state.view = "failed";
      state.runId = "";
      state.runKind = "";
      render();
      window.setTimeout(function () {
        if (els.failedTitle) els.failedTitle.focus();
      }, 0);
    }

    function taskData(result) {
      if (!result || result.ok !== true || !result.data) return null;
      return result.data;
    }

    function pollRun(method, runId) {
      return new Promise(function (resolve, reject) {
        function poll() {
          call(method, { run_id: runId }).then(function (result) {
            var task = taskData(result);
            if (!task) {
              reject(errorCode(result, "product_run_unavailable"));
              return;
            }
            if (task.status === "queued" || task.status === "running") {
              window.setTimeout(poll, 120);
              return;
            }
            if (
              task.status === "completed" &&
              task.data &&
              task.data.ok === true
            ) {
              resolve(task.data.data);
              return;
            }
            reject(
              (task.error && task.error.code) ||
                errorCode(task.data, "product_run_failed")
            );
          });
        }
        poll();
      });
    }

    function startRun(startMethod, pollMethod, payload, kind) {
      state.view = "progress";
      state.runKind = kind;
      state.error = "";
      render();
      return call(startMethod, payload)
        .then(function (started) {
          if (!started || started.ok !== true || !started.run_id) {
            throw errorCode(started, kind + "_start_failed");
          }
          state.runId = started.run_id;
          return pollRun(pollMethod, state.runId);
        })
        .finally(function () {
          state.runId = "";
          state.runKind = "";
        });
    }

    function currentPlan() {
      return state.workspace && state.workspace.plan;
    }

    function sectionTitle(sectionId) {
      var item = SECTION_TITLES[sectionId];
      return item ? item[isZh() ? "zh" : "en"] : String(sectionId || "");
    }

    function planningAvailable() {
      if (host.canOpenProduct) return host.canOpenProduct() === true;
      var planning = host.getPlanningState ? host.getPlanningState() : null;
      return !!(planning && planning.available === true);
    }

    function selectedPlanningModel() {
      if (state.selectedModel) return state.selectedModel;
      var planning = host.getPlanningState ? host.getPlanningState() : null;
      return planning && planning.selected_model
        ? planning.selected_model
        : null;
    }

    function shortDigest(value) {
      var digest = String(value || "");
      return digest ? digest.slice(0, 8) : "";
    }

    function modelErrorText(code) {
      var c = copy();
      return {
        ollama_unavailable: c.plannerOllamaUnavailable,
        product_planning_model_not_available: c.plannerDigestChanged,
        product_planning_model_digest_changed: c.plannerDigestChanged,
        product_planning_model_too_large: c.plannerTooLarge,
        product_planning_model_moe_not_allowed: c.plannerMoeUnsupported,
        product_planning_model_probe_failed: c.plannerProbeFailed,
      }[String(code || "")] || c.plannerFailed;
    }

    function clear(element) {
      if (element) element.textContent = "";
    }

    function element(tag, className, text) {
      var node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = String(text);
      return node;
    }

    function showView(id, active) {
      var node = $(id);
      if (node) node.classList.toggle("hidden", !active);
    }

    function renderModelSetup() {
      var c = copy();
      var available = planningAvailable();
      var selected = selectedPlanningModel();
      var status = available
        ? selected
          ? c.plannerConfigured
          : c.plannerMissing
        : c.plannerUnavailable;
      setText("product-planner-label", c.plannerLabel);
      setText("product-planner-status", status);
      setText(
        "product-planner-detail",
        selected
          ? [
              String(selected.name || ""),
              String(selected.parameter_size || ""),
              shortDigest(selected.digest),
            ]
              .filter(Boolean)
              .join(" · ")
          : ""
      );
      setText(
        "btn-product-planner-configure",
        selected ? c.plannerConfigure : c.plannerChoose
      );
      setText("product-planner-select-label", c.plannerSelectLabel);
      setText("btn-product-planner-refresh", c.plannerRefresh);
      setText("btn-product-planner-use", c.plannerUse);
      els.modelConfigure.disabled = !available || state.modelLoading;
      els.modelConfigure.setAttribute(
        "aria-expanded",
        state.modelPickerOpen ? "true" : "false"
      );
      els.modelPicker.classList.toggle("hidden", !state.modelPickerOpen);
      clear(els.modelSelect);
      var placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = c.plannerChoose;
      els.modelSelect.appendChild(placeholder);
      state.models.forEach(function (model, index) {
        var option = document.createElement("option");
        option.value = String(index);
        option.disabled = model.eligible_small_model !== true;
        option.textContent = [
          String(model.name || ""),
          String(model.parameter_size || ""),
          model.eligible_small_model === true
            ? ""
            : String(model.eligibility_reason || ""),
        ]
          .filter(Boolean)
          .join(" · ");
        els.modelSelect.appendChild(option);
      });
      els.modelSelect.value =
        state.modelIndex >= 0 ? String(state.modelIndex) : "";
      els.modelSelect.disabled = state.modelLoading || !state.models.length;
      els.modelRefresh.disabled = state.modelLoading;
      var chosen =
        state.modelIndex >= 0 ? state.models[state.modelIndex] : null;
      els.modelUse.disabled =
        state.modelLoading || !chosen || chosen.eligible_small_model !== true;
      els.modelMessage.classList.toggle("is-error", !!state.modelError);
      els.modelMessage.textContent = state.modelLoading
        ? state.modelMessage || c.plannerLoading
        : state.modelError
        ? modelErrorText(state.modelError)
        : state.modelMessage;
    }

    function loadPlanningModels() {
      if (state.modelLoading || !planningAvailable()) return;
      state.modelPickerOpen = true;
      state.modelLoading = true;
      state.modelIndex = -1;
      state.modelMessage = copy().plannerLoading;
      state.modelError = "";
      renderModelSetup();
      call("list_product_planning_models", {})
        .then(function (started) {
          if (!started || started.ok !== true || !started.run_id) {
            throw errorCode(started, "product_plan_list_models_failed");
          }
          return pollRun("get_product_plan_run", started.run_id);
        })
        .then(function (result) {
          state.models =
            result && Array.isArray(result.models) ? result.models : [];
          state.modelMessage = state.models.some(function (model) {
            return model.eligible_small_model === true;
          })
            ? ""
            : copy().plannerNoModels;
        })
        .catch(function (code) {
          state.models = [];
          state.modelError = String(code || "product_plan_list_models_failed");
        })
        .finally(function () {
          state.modelLoading = false;
          render();
        });
    }

    function selectPlanningModel() {
      var model =
        state.modelIndex >= 0 ? state.models[state.modelIndex] : null;
      if (
        state.modelLoading ||
        !model ||
        model.eligible_small_model !== true
      ) {
        return;
      }
      state.modelLoading = true;
      state.modelMessage = copy().plannerVerifying;
      state.modelError = "";
      renderModelSetup();
      call("select_product_planning_model", {
        name: model.name,
        digest: model.digest,
      })
        .then(function (started) {
          if (!started || started.ok !== true || !started.run_id) {
            throw errorCode(started, "product_planning_model_required");
          }
          return pollRun("get_product_plan_run", started.run_id);
        })
        .then(function (result) {
          if (!result || !result.model) {
            throw "product_planning_model_probe_failed";
          }
          state.selectedModel = result.model;
          if (host.setSelectedPlanningModel) {
            host.setSelectedPlanningModel(result.model);
          }
          state.modelPickerOpen = false;
          state.modelMessage = copy().plannerReady;
          state.models = [];
          state.modelIndex = -1;
        })
        .catch(function (code) {
          state.modelError = String(
            code || "product_planning_model_probe_failed"
          );
        })
        .finally(function () {
          state.modelLoading = false;
          render();
          if (selectedPlanningModel()) els.goal.focus();
        });
    }

    function renderQuestions() {
      clear(els.questionForm);
      var questionSet = state.workspace && state.workspace.question_set;
      var questions =
        questionSet && Array.isArray(questionSet.questions)
          ? questionSet.questions
          : [];
      questions.forEach(function (question, questionIndex) {
        var fieldset = element("fieldset", "product-question");
        var legend = element("legend", "", question.prompt);
        fieldset.appendChild(legend);
        question.options.forEach(function (option, optionIndex) {
          var label = element("label", "product-question-option");
          var input = document.createElement("input");
          input.type = "radio";
          input.name = "product-question-" + questionIndex;
          input.value = String(optionIndex);
          var text = element("span", "");
          text.appendChild(element("strong", "", option.label));
          text.appendChild(element("small", "", option.impact));
          label.appendChild(input);
          label.appendChild(text);
          fieldset.appendChild(label);
        });
        if (question.allow_custom === true) {
          var customLabel = element("label", "product-question-option");
          var customRadio = document.createElement("input");
          customRadio.type = "radio";
          customRadio.name = "product-question-" + questionIndex;
          customRadio.value = "custom";
          var customInput = document.createElement("input");
          customInput.type = "text";
          customInput.className = "product-question-custom";
          customInput.placeholder = copy().custom;
          customInput.dataset.questionIndex = String(questionIndex);
          customInput.addEventListener("focus", function () {
            customRadio.checked = true;
          });
          customLabel.appendChild(customRadio);
          customLabel.appendChild(customInput);
          fieldset.appendChild(customLabel);
        }
        els.questionForm.appendChild(fieldset);
      });
      updateQuestionAction();
    }

    function updateGoalAction() {
      if (!els.submitGoal) return;
      var canPlan = planningAvailable() && !!selectedPlanningModel();
      var hasGoal = !!String((els.goal && els.goal.value) || "").trim();
      els.submitGoal.disabled = !canPlan || !hasGoal;
      els.submitGoal.title = !canPlan
        ? copy().noPlanner
        : hasGoal
        ? ""
        : copy().goalRequired;
    }

    function updateQuestionAction() {
      var button = $("btn-submit-product-answers");
      if (!button) return;
      button.disabled = !collectAnswers();
      button.title = button.disabled ? copy().chooseAnswer : "";
    }

    function planGaps() {
      var plan = currentPlan();
      if (!plan || !Array.isArray(plan.sections)) return [];
      return plan.sections.reduce(function (result, section) {
        return result.concat(Array.isArray(section.gaps) ? section.gaps : []);
      }, []);
    }

    function gapView(gapId) {
      var gaps =
        state.workspace && Array.isArray(state.workspace.capability_gaps)
          ? state.workspace.capability_gaps
          : [];
      return gaps.find(function (item) {
        return item.gap_id === gapId;
      }) || null;
    }

    function gapDraft(view) {
      var digest =
        view && view.projection ? view.projection.projection_digest : "";
      var existing = state.gapDrafts[view.gap_id];
      if (existing && existing.projectionDigest === digest) return existing;
      var draft = {
        projectionDigest: digest,
        behavior: "",
        reason: "",
        cases: [{ input: {}, expected_output: {} }],
        error: "",
        errorCode: "",
        message: "",
        runStage: "",
        runStatus: "",
        submitting: false,
      };
      state.gapDrafts[view.gap_id] = draft;
      return draft;
    }

    function contractFields(contract) {
      var properties =
        contract && contract.properties && typeof contract.properties === "object"
          ? contract.properties
          : {};
      return Object.keys(properties)
        .sort()
        .map(function (name) {
          return { name: name, contract: properties[name] };
        });
    }

    function contractFieldText(field) {
      var contract = field.contract || {};
      var range =
        Number.isInteger(contract.minimum) && Number.isInteger(contract.maximum)
          ? " · " + contract.minimum + "…" + contract.maximum
          : "";
      var values =
        Array.isArray(contract.enum) && contract.enum.length
          ? " · " + contract.enum.join(" / ")
          : "";
      return (
        field.name + " · " + String(contract.type || "") + range + values
      );
    }

    function parseGapInteger(value, contract) {
      var text = String(value === undefined ? "" : value).trim();
      if (!/^-?\d+$/.test(text)) throw new Error("integer");
      var number = Number(text);
      if (
        !Number.isSafeInteger(number) ||
        (Number.isInteger(contract.minimum) && number < contract.minimum) ||
        (Number.isInteger(contract.maximum) && number > contract.maximum)
      ) {
        throw new Error("range");
      }
      return number;
    }

    function parseGapValue(value, contract) {
      if (contract && contract.type === "integer") {
        return parseGapInteger(value, contract);
      }
      if (contract && contract.type === "boolean") {
        if (value === true || value === "true") return true;
        if (value === false || value === "false") return false;
        throw new Error("boolean");
      }
      if (
        contract &&
        contract.type === "string" &&
        Array.isArray(contract.enum)
      ) {
        var text = String(value === undefined ? "" : value);
        if (contract.enum.indexOf(text) === -1) throw new Error("enum");
        return text;
      }
      throw new Error("unsupported");
    }

    function gapAcceptanceCases(view, draft) {
      var projection = view.projection;
      var inputFields = contractFields(projection.input_contract);
      var outputFields = contractFields(projection.output_contract);
      if (!draft.behavior.trim() || !draft.cases.length) return null;
      try {
        return draft.cases.map(function (row) {
          var input = {};
          var expected = {};
          inputFields.forEach(function (field) {
            input[field.name] = parseGapValue(
              row.input[field.name],
              field.contract
            );
          });
          outputFields.forEach(function (field) {
            expected[field.name] = parseGapValue(
              row.expected_output[field.name],
              field.contract
            );
          });
          return { input: input, expected_output: expected };
        });
      } catch (_error) {
        return null;
      }
    }

    function gapStatusText(status) {
      var c = copy();
      if (status === "capability_gap_projection_stale") return c.gapStale;
      if (
        status === "capability_gap_boundary_ambiguous" ||
        status === "capability_gap_plan_count_unsupported"
      ) {
        return c.gapAmbiguous;
      }
      return c.gapUnavailable;
    }

    function decisionText(decision) {
      var c = copy();
      return {
        authorize: c.gapDecisionAuthorize,
        defer: c.gapDecisionDefer,
        reject: c.gapDecisionReject,
      }[decision] || String(decision || "");
    }

    function submitGapDecision(view, draft, decision) {
      var cases = decision === "authorize"
        ? gapAcceptanceCases(view, draft)
        : [];
      if (
        (decision === "authorize" && !cases) ||
        (decision === "reject" && !draft.reason.trim())
      ) {
        draft.error = copy().gapDecisionInvalid;
        renderSectionDetail();
        return;
      }
      var plan = currentPlan();
      var current = view.current_decision;
      draft.error = "";
      draft.message = "";
      draft.submitting = true;
      renderSectionDetail();
      call("record_product_capability_gap_decision", {
        plan_token: state.planToken,
        plan_digest: plan.canonical_digest,
        projection_digest: view.projection.projection_digest,
        expected_previous_decision_digest: current
          ? current.canonical_digest
          : null,
        decision: decision,
        behavior_intent:
          decision === "authorize" ? draft.behavior.trim() : null,
        reason:
          decision === "reject"
            ? draft.reason.trim()
            : decision === "defer" && draft.reason.trim()
            ? draft.reason.trim()
            : null,
        acceptance_cases: cases,
      })
        .then(function (result) {
          if (!result || result.ok !== true) {
            throw errorCode(result, "capability_gap_decision_failed");
          }
          state.workspace = result.data;
          draft.submitting = false;
          draft.message = copy().gapDecisionSaved;
          renderSectionDetail();
        })
        .catch(function (code) {
          draft.submitting = false;
          draft.error =
            String(code || "") === "capability_gap_projection_stale"
              ? copy().gapStale
              : copy().gapDecisionInvalid;
          renderSectionDetail();
        });
    }

    function refreshCurrentWorkspace(options) {
      var sectionIndex = state.sectionIndex;
      var scroll = els.stage ? els.stage.scrollTop : 0;
      var focusId = options && options.focusId;
      return call("get_product_plan_workspace", {
        plan_token: state.planToken,
      }).then(function (result) {
        if (!result || result.ok !== true) {
          throw errorCode(result, "product_plan_workspace_failed");
        }
        updateWorkspace(result.data);
        if (
          sectionIndex >= 0 &&
          state.view === "review" &&
          currentPlan() &&
          currentPlan().sections[sectionIndex]
        ) {
          state.sectionIndex = sectionIndex;
          state.view = "section";
          render();
          if (els.stage) els.stage.scrollTop = scroll;
        }
        window.setTimeout(function () {
          var target = focusId ? $(focusId) : null;
          if (target) target.focus();
        }, 0);
        return result.data;
      });
    }

    function pollSourceProposalRun(runId, view, draft) {
      return new Promise(function (resolve, reject) {
        function poll() {
          call("get_intake_run", { run_id: runId }).then(function (result) {
            var run = taskData(result);
            if (!run) {
              reject(errorCode(result, "capability_source_proposal_run_failed"));
              return;
            }
            draft.message =
              copy().gapSourceProposalRunning + " · " + String(run.stage || "");
            draft.runStage = String(run.stage || "");
            draft.runStatus = String(run.status || "");
            draft.errorCode = String(run.error_code || "");
            draft.submitting = run.status === "pending" || run.status === "running";
            renderSectionDetail();
            if (draft.submitting) {
              window.setTimeout(poll, 180);
              return;
            }
            if (run.status === "review_required") {
              resolve(run);
              return;
            }
            reject(run.error_code || "capability_source_proposal_run_failed");
          });
        }
        poll();
      });
    }

    function openSourceProposalReview(view, run, focusId) {
      if (!host.openIngestion || !run || !run.review_id) return;
      state.active = false;
      host.openIngestion({
        station: "review",
        review_id: run.review_id,
        plan_token: state.planToken,
        projection_digest: view.projection.projection_digest,
        return_focus_id: focusId || "",
      });
    }

    function authorizeAndRunSourceProposal(view, draft) {
      var plan = currentPlan();
      var alreadyAuthorized =
        view.current_decision &&
        view.current_decision.decision === "authorize";
      var cases = alreadyAuthorized ? [] : gapAcceptanceCases(view, draft);
      if (!plan || (!alreadyAuthorized && !cases)) {
        draft.error = copy().gapDecisionInvalid;
        renderSectionDetail();
        return;
      }
      draft.error = "";
      draft.errorCode = "";
      draft.message = "";
      draft.runStage = "";
      draft.runStatus = "";
      draft.submitting = true;
      renderSectionDetail();
      var chain = Promise.resolve(state.workspace);
      if (!alreadyAuthorized) {
        chain = call("record_product_capability_gap_decision", {
          plan_token: state.planToken,
          plan_digest: plan.canonical_digest,
          projection_digest: view.projection.projection_digest,
          expected_previous_decision_digest: view.current_decision
            ? view.current_decision.canonical_digest
            : null,
          decision: "authorize",
          behavior_intent: draft.behavior.trim(),
          reason: null,
          acceptance_cases: cases,
        }).then(function (result) {
          if (!result || result.ok !== true) {
            throw errorCode(result, "capability_gap_decision_failed");
          }
          state.workspace = result.data;
          return result.data;
        });
      }
      chain
        .then(function () {
          view = gapView(view.gap_id);
          if (!view) throw "capability_gap_projection_stale";
          if (view.source_proposal_authorization) return state.workspace;
          return call("prepare_product_capability_source_proposal", {
            plan_token: state.planToken,
            plan_digest: plan.canonical_digest,
            projection_digest: view.projection.projection_digest,
            authorize_decision_digest:
              view.current_decision.canonical_digest,
          }).then(function (result) {
            if (!result || result.ok !== true) {
              throw errorCode(
                result,
                "capability_source_proposal_authorization_failed"
              );
            }
            state.workspace = result.data;
            return result.data;
          });
        })
        .then(function () {
          view = gapView(view.gap_id);
          var authorization = view.source_proposal_authorization;
          return call("start_product_capability_source_proposal", {
            plan_token: state.planToken,
            plan_digest: plan.canonical_digest,
            projection_digest: view.projection.projection_digest,
            authorization_digest: authorization.authorization_digest,
          });
        })
        .then(function (started) {
          if (!started || started.ok !== true || !started.run_id) {
            throw errorCode(
              started,
              "capability_source_proposal_run_failed"
            );
          }
          draft.runStage = "source_proposal";
          draft.runStatus =
            started.status === "queued"
              ? "pending"
              : String(started.status || "pending");
          renderSectionDetail();
          state.runId = started.run_id;
          state.runKind = "source_proposal";
          return pollSourceProposalRun(started.run_id, view, draft);
        })
        .then(function (run) {
          draft.submitting = false;
          state.runId = "";
          state.runKind = "";
          return refreshCurrentWorkspace({
            focusId: "btn-review-source-proposal-" + view.gap_id,
          }).then(function () {
            view = gapView(view.gap_id) || view;
            openSourceProposalReview(
              view,
              run,
              "btn-review-source-proposal-" + view.gap_id
            );
          });
        })
        .catch(function (code) {
          state.runId = "";
          state.runKind = "";
          draft.submitting = false;
          draft.runStatus = "failed";
          draft.runStage = "";
          draft.errorCode = String(
            code || "capability_source_proposal_run_failed"
          );
          draft.error =
            String(code || "") === "capability_gap_projection_stale"
              ? copy().gapStale
              : copy().gapSourceProposalError;
          renderSectionDetail();
        });
    }

    function replanStatusText(status) {
      var c = copy();
      if (status === "capability_replan_handoff_stale") return c.replanStale;
      if (status === "capability_replan_ambiguous") return c.replanAmbiguous;
      if (status === "capability_replan_handoff_conflict") return c.replanConflict;
      return c.gapUnavailable;
    }

    function openReplanWorkspace(planToken) {
      call("get_product_plan_workspace", { plan_token: planToken })
        .then(function (result) {
          if (!result || result.ok !== true) {
            throw errorCode(result, "capability_replan_handoff_conflict");
          }
          updateWorkspace(result.data);
        })
        .catch(function (code) {
          fail(code);
        });
    }

    function startCapabilityReplan(replan) {
      var plan = currentPlan();
      if (!plan || !replan || replan.status !== "available") return;
      startRun(
        "start_product_capability_replan",
        "get_product_plan_run",
        {
          plan_token: state.planToken,
          plan_digest: plan.canonical_digest,
          projection_digest: replan.projection_digest,
        },
        "replan"
      )
        .then(updateWorkspace)
        .catch(function (code) {
          replan.status = String(code || "capability_replan_handoff_conflict");
          state.view = "section";
          render();
        });
    }

    function renderCapabilityReplan(gap) {
      var replan = state.workspace && state.workspace.capability_replan;
      if (!replan || replan.source_gap_id !== gap.gap_id) return null;
      var c = copy();
      var panel = element("div", "product-gap-status");
      panel.dataset.capabilityReplanStatus = String(replan.status || "");
      panel.setAttribute("aria-live", "polite");
      if (replan.status === "available") {
        panel.appendChild(element("strong", "", c.replanReady));
      } else if (replan.status === "started") {
        panel.appendChild(element("strong", "", c.replanStarted));
      } else {
        panel.classList.add("is-error");
        panel.appendChild(
          element("strong", "", replanStatusText(replan.status))
        );
      }
      if (Array.isArray(replan.role_order) && replan.role_order.length) {
        panel.appendChild(document.createElement("br"));
        panel.appendChild(
          element("span", "product-gap-mono", replan.role_order.join(" → "))
        );
      }
      if (replan.status === "available") {
        var start = element("button", "btn-primary", c.replanAction);
        start.type = "button";
        start.dataset.action = "start-capability-replan";
        start.addEventListener("click", function () {
          startCapabilityReplan(replan);
        });
        panel.appendChild(document.createElement("br"));
        panel.appendChild(start);
      } else if (
        replan.status === "started" &&
        replan.successor_plan_token
      ) {
        var open = element("button", "btn-secondary", c.replanOpen);
        open.type = "button";
        open.dataset.action = "open-capability-replan";
        open.addEventListener("click", function () {
          openReplanWorkspace(replan.successor_plan_token);
        });
        panel.appendChild(document.createElement("br"));
        panel.appendChild(open);
      }
      return panel;
    }

    function updateReviewAction() {
      var hasGaps = planGaps().length > 0;
      var cases = acceptanceCases();
      var parameterReady =
        !state.parameterOffer || !!parameterConfirmation();
      ["btn-confirm-and-generate", "btn-confirm-and-agent"].forEach(function (
        id
      ) {
        var button = $(id);
        if (!button) return;
        button.disabled = hasGaps || !cases || !parameterReady;
        button.title = button.disabled
          ? hasGaps
            ? copy().gapBlockGenerate
            : state.acceptanceShape
            ? copy().reviewError
            : copy().unsupported
          : "";
      });
      if (els.acceptance) {
        els.acceptance.classList.toggle("hidden", hasGaps);
      }
    }

    function renderWorkItem(item, itemIndex) {
      var article = element("article", "product-plan-work-item");
      article.appendChild(element("h3", "", item.title));
      article.appendChild(element("p", "", item.description));
      var meta = element("dl", "product-plan-work-item-meta");
      if (item.acceptance_intent) {
        meta.appendChild(element("dt", "", copy().acceptance));
        meta.appendChild(element("dd", "", item.acceptance_intent));
      }
      if (item.delivery_wave) {
        meta.appendChild(element("dt", "", copy().wave));
        meta.appendChild(element("dd", "", item.delivery_wave));
      }
      article.appendChild(meta);
      (item.capsule_bindings || []).forEach(function (binding, bindingIndex) {
        var row = element("div", "product-plan-capability product-plan-capability-link");
        row.appendChild(
          element("span", "", copy().capability + " · " + binding.display_name)
        );
        var button = element("button", "product-plan-text-action", copy().viewInWarehouse);
        button.type = "button";
        button.id = [
          "product-plan-capsule-source",
          state.sectionIndex,
          itemIndex,
          bindingIndex,
        ].join("-");
        button.addEventListener("click", function () {
          enterWarehouse(binding, button);
        });
        row.appendChild(button);
        article.appendChild(row);
      });
      if (item.gap_reason) {
        article.appendChild(
          element(
            "p",
            "product-plan-gap",
            copy().gap + " · " + item.gap_reason
          )
        );
      }
      return article;
    }

    function renderGapContract(title, contract) {
      var group = element("div", "product-gap-contract");
      group.appendChild(element("strong", "", title));
      var list = element("ul", "");
      contractFields(contract).forEach(function (field) {
        list.appendChild(element("li", "", contractFieldText(field)));
      });
      group.appendChild(list);
      return group;
    }

    function gapAcceptanceControl(contract, value) {
      if (contract.type === "boolean" || Array.isArray(contract.enum)) {
        var select = document.createElement("select");
        var values =
          contract.type === "boolean"
            ? ["true", "false"]
            : contract.enum.slice();
        select.appendChild(new Option("", ""));
        values.forEach(function (item) {
          select.appendChild(new Option(String(item), String(item)));
        });
        select.value = value === undefined ? "" : String(value);
        return select;
      }
      var input = document.createElement("input");
      input.type = "number";
      input.step = "1";
      if (Number.isInteger(contract.minimum)) {
        input.min = String(contract.minimum);
      }
      if (Number.isInteger(contract.maximum)) {
        input.max = String(contract.maximum);
      }
      input.value = value === undefined ? "" : String(value);
      return input;
    }

    function renderGapAcceptance(view, draft) {
      var c = copy();
      var projection = view.projection;
      var wrap = element("div", "product-gap-cases");
      wrap.appendChild(element("h4", "", c.gapCases));
      draft.cases.forEach(function (row, rowIndex) {
        var current = element("div", "product-gap-case");
        current.appendChild(
          element("span", "product-gap-case-index", String(rowIndex + 1))
        );
        contractFields(projection.input_contract).forEach(function (field) {
          var label = element("label", "");
          label.appendChild(element("span", "", c.input + " · " + field.name));
          var input = gapAcceptanceControl(
            field.contract,
            row.input[field.name]
          );
          input.addEventListener("input", function () {
            row.input[field.name] = input.value;
            if (projection.passthrough_fields.indexOf(field.name) !== -1) {
              row.expected_output[field.name] = input.value;
              current
                .querySelectorAll("[data-gap-output-field]")
                .forEach(function (node) {
                  if (node.dataset.gapOutputField === field.name) {
                    node.value = input.value;
                  }
                });
            }
          });
          label.appendChild(input);
          current.appendChild(label);
        });
        contractFields(projection.output_contract).forEach(function (field) {
          var label = element("label", "");
          label.appendChild(
            element("span", "", c.expected + " · " + field.name)
          );
          var output = gapAcceptanceControl(
            field.contract,
            row.expected_output[field.name]
          );
          output.readOnly =
            projection.passthrough_fields.indexOf(field.name) !== -1;
          output.dataset.gapOutputField = field.name;
          output.addEventListener("input", function () {
            row.expected_output[field.name] = output.value;
          });
          label.appendChild(output);
          current.appendChild(label);
        });
        if (draft.cases.length > 1) {
          var remove = element("button", "product-plan-text-action", "×");
          remove.type = "button";
          remove.setAttribute(
            "aria-label",
            isZh() ? "删除这一验收例" : "Remove acceptance case"
          );
          remove.addEventListener("click", function () {
            draft.cases.splice(rowIndex, 1);
            renderSectionDetail();
          });
          current.appendChild(remove);
        }
        wrap.appendChild(current);
      });
      var add = element("button", "product-plan-text-action", c.gapAddCase);
      add.type = "button";
      add.disabled = draft.cases.length >= 3;
      add.addEventListener("click", function () {
        if (draft.cases.length >= 3) return;
        draft.cases.push({ input: {}, expected_output: {} });
        renderSectionDetail();
      });
      wrap.appendChild(add);
      return wrap;
    }

    function renderCapabilityGap(gap) {
      var c = copy();
      var view = gapView(gap.gap_id);
      var panel = element("article", "product-capability-gap");
      panel.dataset.gapId = gap.gap_id;
      panel.appendChild(element("p", "product-gap-kicker", c.gap));
      panel.appendChild(element("h3", "", gap.title));
      panel.appendChild(element("p", "product-gap-reason", gap.reason));
      var replan = renderCapabilityReplan(gap);
      if (replan) {
        panel.appendChild(replan);
        return panel;
      }
      if (!view || view.status !== "available" || !view.projection) {
        var unavailable = element(
          "p",
          "product-gap-status is-error",
          gapStatusText(view && view.status)
        );
        unavailable.setAttribute("role", "status");
        panel.appendChild(unavailable);
        return panel;
      }

      var projection = view.projection;
      var draft = gapDraft(view);
      var evidence = element("div", "product-gap-evidence");
      evidence.appendChild(element("strong", "", c.gapProven));
      evidence.appendChild(
        element(
          "span",
          "",
          projection.capability_group_display_name +
            " · " +
            projection.capability_key
        )
      );
      evidence.appendChild(
        element(
          "span",
          "",
          c.gapPosition +
            " · " +
            {
              only_computation: c.slotOnly,
              before_existing_computation: c.slotBefore,
              after_existing_computation: c.slotAfter,
            }[projection.slot]
        )
      );
      evidence.appendChild(
        element(
          "span",
          "product-gap-mono",
          c.gapAdapter + " · " + projection.adapter_contract_version
        )
      );
      var contracts = element("div", "product-gap-contracts");
      contracts.appendChild(
        renderGapContract(c.gapInput, projection.input_contract)
      );
      contracts.appendChild(
        renderGapContract(c.gapOutput, projection.output_contract)
      );
      var proof = element("div", "product-gap-proof");
      proof.appendChild(evidence);
      proof.appendChild(contracts);
      panel.appendChild(proof);

      if (view.current_decision) {
        var current = element("p", "product-gap-current");
        current.appendChild(
          element(
            "strong",
            "",
            c.gapDecisionCurrent +
              " · " +
              decisionText(view.current_decision.decision)
          )
        );
        current.appendChild(
          element(
            "span",
            "product-gap-mono",
            c.gapDecisionHistory +
              " · " +
              String(view.decision_history.length) +
              " · " +
              shortDigest(view.current_decision.canonical_digest)
          )
        );
        panel.appendChild(current);
        var history = element("details", "product-gap-history");
        history.appendChild(
          element(
            "summary",
            "",
            c.gapDecisionHistory + " · " + String(view.decision_history.length)
          )
        );
        var historyList = element("ol", "");
        view.decision_history.forEach(function (row) {
          historyList.appendChild(
            element(
              "li",
              "",
              [
                "#" + String(row.sequence),
                decisionText(row.decision),
                shortDigest(row.canonical_digest),
                row.previous_decision_digest
                  ? c.gapSupersedes +
                    " " +
                    shortDigest(row.previous_decision_digest)
                  : "",
              ]
                .filter(Boolean)
                .join(" · ")
            )
          );
        });
        history.appendChild(historyList);
        panel.appendChild(history);
      }

      if (view.source_proposal_authorization) {
        var run = view.source_proposal_run;
        var runStatus = run ? run.status : draft.runStatus;
        var runStage = run ? run.stage : draft.runStage;
        var locked = element("div", "product-gap-status");
        locked.dataset.sourceProposalStatus = runStatus || "locked";
        locked.setAttribute("aria-live", "polite");
        locked.appendChild(
          element(
            "strong",
            "",
            runStatus === "pending" || runStatus === "running"
              ? c.gapSourceProposalRunning + " · " + String(runStage || "")
              : c.gapSourceProposalLocked
          )
        );
        locked.appendChild(document.createTextNode(" · "));
        locked.appendChild(
          element(
            "span",
            "product-gap-mono",
            shortDigest(
              view.source_proposal_authorization.authorization_digest
            )
          )
        );
        locked.appendChild(document.createElement("br"));
        locked.appendChild(element("span", "", c.gapSourceProposalZeroWrite));
        locked.appendChild(document.createElement("br"));
        locked.appendChild(
          element("span", "", c.gapSourceProposalDisclosure)
        );
        panel.appendChild(locked);
        if (!run) {
          var start = element(
            "button",
            "btn-primary",
            c.gapPrepareSourceProposal
          );
          start.type = "button";
          start.dataset.action = "start-capability-source-proposal";
          start.disabled = draft.submitting;
          start.addEventListener("click", function () {
            authorizeAndRunSourceProposal(view, draft);
          });
          panel.appendChild(start);
        } else if (run.status === "pending" || run.status === "running") {
          var cancel = element(
            "button",
            "btn-secondary",
            c.gapSourceProposalCancel
          );
          cancel.type = "button";
          cancel.addEventListener("click", function () {
            call("cancel_intake_run", { run_id: run.run_id });
          });
          panel.appendChild(cancel);
        } else if (run.status === "review_required") {
          var outcome = run.review_outcome;
          if (outcome && outcome.status === "rejected") {
            panel.appendChild(
              element(
                "p",
                "product-gap-status is-error",
                c.gapDecisionReject
              )
            );
          } else {
            var review = element(
              "button",
              "btn-primary",
              c.gapSourceProposalReview
            );
            review.type = "button";
            review.id = "btn-review-source-proposal-" + view.gap_id;
            review.addEventListener("click", function () {
              openSourceProposalReview(view, run, review.id);
            });
            panel.appendChild(review);
          }
        } else {
          panel.appendChild(
            element(
              "p",
              "product-gap-status is-error",
              run.error_code || c.gapSourceProposalError
            )
          );
        }
        if (draft.error || draft.message) {
          var runMessage = element(
            "p",
            "product-gap-status" + (draft.error ? " is-error" : ""),
            [
              draft.error || draft.message,
              draft.errorCode || "",
            ].filter(Boolean).join(" · ")
          );
          if (draft.errorCode) {
            runMessage.dataset.sourceProposalErrorCode = draft.errorCode;
          }
          runMessage.setAttribute("aria-live", "polite");
          panel.appendChild(runMessage);
        }
        return panel;
      }

      var behaviorLabel = element("label", "product-gap-field");
      behaviorLabel.appendChild(element("span", "", c.gapBehavior));
      var behavior = document.createElement("textarea");
      behavior.rows = 2;
      behavior.maxLength = 1000;
      behavior.placeholder = c.gapBehaviorPlaceholder;
      behavior.value = draft.behavior;
      behavior.addEventListener("input", function () {
        draft.behavior = behavior.value;
      });
      behaviorLabel.appendChild(behavior);
      panel.appendChild(behaviorLabel);
      panel.appendChild(renderGapAcceptance(view, draft));

      var reject;
      var reasonLabel = element("label", "product-gap-field");
      reasonLabel.appendChild(element("span", "", c.gapReason));
      var reason = document.createElement("input");
      reason.type = "text";
      reason.maxLength = 500;
      reason.value = draft.reason;
      reason.addEventListener("input", function () {
        draft.reason = reason.value;
        if (reject) reject.disabled = draft.submitting || !draft.reason.trim();
      });
      reasonLabel.appendChild(reason);
      panel.appendChild(reasonLabel);

      var actions = element("div", "product-gap-actions");
      var authorize = element(
        "button",
        "btn-primary",
        c.gapPrepareSourceProposal
      );
      authorize.type = "button";
      authorize.disabled = draft.submitting;
      authorize.addEventListener("click", function () {
        authorizeAndRunSourceProposal(view, draft);
      });
      var defer = element("button", "btn-secondary", c.gapDefer);
      defer.type = "button";
      defer.disabled = draft.submitting;
      defer.addEventListener("click", function () {
        submitGapDecision(view, draft, "defer");
      });
      reject = element("button", "product-plan-text-action", c.gapReject);
      reject.type = "button";
      reject.disabled = draft.submitting || !draft.reason.trim();
      reject.addEventListener("click", function () {
        submitGapDecision(view, draft, "reject");
      });
      actions.appendChild(authorize);
      actions.appendChild(defer);
      actions.appendChild(reject);
      panel.appendChild(actions);
      var status = element(
        "p",
        "product-gap-status" + (draft.error ? " is-error" : ""),
        draft.error || draft.message
      );
      status.setAttribute("aria-live", "polite");
      panel.appendChild(status);
      return panel;
    }

    function sectionCounts(section) {
      var workItems = Array.isArray(section.work_items)
        ? section.work_items
        : [];
      var capabilities = 0;
      var gaps = 0;
      workItems.forEach(function (item) {
        capabilities += Array.isArray(item.capsule_bindings)
          ? item.capsule_bindings.length
          : 0;
        if (item.gap_reason) gaps += 1;
      });
      if (Array.isArray(section.gaps)) gaps = section.gaps.length;
      return {
        work: workItems.length,
        capabilities: capabilities,
        gaps: gaps,
      };
    }

    function renderPlan() {
      var plan = currentPlan();
      clear(els.sections);
      if (!plan) return;
      setText("product-review-goal", state.goal || plan.goal);
      setText("product-review-title", plan.product_name);
      (plan.sections || []).forEach(function (section, index) {
        var notApplicable = section.applicability === "not_applicable";
        var counts = sectionCounts(section);
        var group = element("section", "product-plan-section");
        var button = element(
          notApplicable ? "div" : "button",
          "product-plan-section-button"
        );
        if (!notApplicable) {
          button.type = "button";
          button.dataset.sectionIndex = String(index);
          button.id = "product-plan-section-" + String(index);
          button.setAttribute(
            "aria-label",
            copy().sectionOpen + " · " + sectionTitle(section.section_id)
          );
        }
        var heading = element("h2", "", sectionTitle(section.section_id));
        var summary = element(
          "span",
          "product-plan-section-summary",
          notApplicable
            ? section.summary || copy().sectionNotApplicable
            : [
                String(counts.work) + " " + copy().sectionWork,
                String(counts.capabilities) + " " + copy().sectionCapabilities,
                counts.gaps
                  ? String(counts.gaps) + " " + copy().sectionGaps
                  : copy().sectionNoGaps,
              ].join(" · ")
        );
        var arrow = element(
          "span",
          "product-plan-section-arrow",
          notApplicable ? "—" : "→"
        );
        arrow.setAttribute("aria-hidden", "true");
        button.appendChild(heading);
        button.appendChild(summary);
        button.appendChild(arrow);
        group.appendChild(button);
        els.sections.appendChild(group);
      });
      renderAcceptanceRows();
      renderParameterOffer();
    }

    function renderSectionDetail() {
      var plan = currentPlan();
      var sections = plan && Array.isArray(plan.sections) ? plan.sections : [];
      var section = sections[state.sectionIndex];
      clear(els.sectionBody);
      setText("btn-product-plan-section-back", copy().sectionBack);
      if (!plan || !section) {
        state.view = "review";
        state.sectionIndex = -1;
        render();
        return;
      }
      setText("product-plan-section-path", plan.product_name);
      setText(
        "product-plan-section-title",
        sectionTitle(section.section_id)
      );
      (section.work_items || []).forEach(function (item, itemIndex) {
        els.sectionBody.appendChild(renderWorkItem(item, itemIndex));
      });
      (section.gaps || []).forEach(function (gap) {
        els.sectionBody.appendChild(renderCapabilityGap(gap));
      });
    }

    function openSection(index, trigger) {
      var plan = currentPlan();
      var sections = plan && Array.isArray(plan.sections) ? plan.sections : [];
      if (!sections[index] || sections[index].applicability === "not_applicable") {
        return;
      }
      state.reviewScroll = els.stage.scrollTop;
      state.sectionFocusId = trigger && trigger.id ? trigger.id : "";
      state.sectionIndex = index;
      state.view = "section";
      render();
      els.stage.scrollTop = 0;
      window.setTimeout(function () {
        els.sectionTitle.focus();
      }, 0);
    }

    function closeSection() {
      state.view = "review";
      var focusId = state.sectionFocusId;
      var scroll = state.reviewScroll;
      state.sectionIndex = -1;
      render();
      window.setTimeout(function () {
        els.stage.scrollTop = scroll;
        var target = focusId ? $(focusId) : els.reviewTitle;
        if (target) target.focus();
      }, 0);
    }

    function renderAcceptanceRows() {
      clear(els.acceptanceCases);
      state.acceptanceRows.forEach(function (row, index) {
        var current = element("div", "product-acceptance-row");
        var shape = state.acceptanceShape;
        var inputFields =
          shape && shape.inputFields.length
            ? shape.inputFields
            : [{ key: "", contract: null }];
        var outputFields =
          shape && shape.outputFields.length
            ? shape.outputFields
            : [{ key: "", contract: null }];
        [
          {
            name: "input",
            title: copy().input,
            fields: inputFields,
          },
          {
            name: "expected",
            title: copy().expected,
            fields: outputFields,
          },
        ].forEach(function (group) {
          var container = element("div", "");
          group.fields.forEach(function (field) {
            var label = element("label", "");
            var title =
              group.fields.length > 1 && field.key
                ? group.title + " · " + field.key.replace(/_/g, " ")
                : group.title;
            label.appendChild(element("span", "", title));
            var input = document.createElement("input");
            input.type = "text";
            input.inputMode =
              field.contract && field.contract.type === "integer"
                ? "numeric"
                : field.contract && field.contract.type === "decimal"
                ? "decimal"
                : "text";
            var values = row[group.name] || {};
            input.value =
              values[field.key] === undefined
                ? ""
                : String(values[field.key]);
            input.dataset.acceptanceIndex = String(index);
            input.dataset.acceptanceField = group.name;
            input.dataset.acceptanceKey = field.key;
            label.appendChild(input);
            container.appendChild(label);
          });
          current.appendChild(container);
        });
        if (state.acceptanceRows.length > 1) {
          var remove = element("button", "product-plan-text-action", "×");
          remove.type = "button";
          remove.dataset.removeAcceptanceIndex = String(index);
          remove.setAttribute("aria-label", isZh() ? "删除这一行" : "Remove outcome");
          current.appendChild(remove);
        }
        els.acceptanceCases.appendChild(current);
      });
      els.addAcceptance.disabled = state.acceptanceRows.length >= 3;
      updateReviewAction();
    }

    function renderParameterOffer() {
      clear(els.parameterConfirmation);
      var offer = state.parameterOffer;
      var bindings = offer && Array.isArray(offer.bindings) ? offer.bindings : [];
      els.parameterConfirmation.classList.toggle("hidden", bindings.length === 0);
      if (!bindings.length) return;
      els.parameterConfirmation.appendChild(
        element("p", "", copy().parameterCopy)
      );
      bindings.forEach(function (binding, index) {
        var label = element("label", "");
        label.appendChild(
          element(
            "span",
            "",
            String(binding.input_field || "").replace(/_/g, " ")
          )
        );
        var input = document.createElement("input");
        input.type = "number";
        input.step = "1";
        var contract = binding.value_contract || {};
        if (contract.minimum !== undefined) input.min = String(contract.minimum);
        if (contract.maximum !== undefined) input.max = String(contract.maximum);
        input.value =
          state.parameterValues[index] === undefined
            ? ""
            : String(state.parameterValues[index]);
        input.dataset.parameterIndex = String(index);
        label.appendChild(input);
        els.parameterConfirmation.appendChild(label);
      });
      updateReviewAction();
    }

    function renderCandidate() {
      var candidate = state.candidate;
      if (!candidate) return;
      var plan = currentPlan();
      setText("product-candidate-state", copy().statusCandidate);
      setText(
        "product-candidate-title",
        (plan && plan.product_name) || copy().title
      );
      setText("product-candidate-summary", copy().candidateReady);
      clear(els.candidateValidation);
      var acceptance = candidate.acceptance || {};
      [
        {
          label: copy().runtimeCheck,
          detail:
            acceptance.runtime_operational === "passed"
              ? copy().runtimePassed
              : copy().validation,
        },
        {
          label: copy().goalCheck,
          detail:
            acceptance.product_goal_conformance === "passed"
              ? copy().goalPassed
              : copy().validation,
        },
      ].forEach(function (item) {
        var line = element("p", "product-candidate-validation-line");
        line.appendChild(element("span", "product-candidate-validation-mark", "✓"));
        line.appendChild(element("strong", "", item.label));
        line.appendChild(element("span", "", item.detail));
        els.candidateValidation.appendChild(line);
      });
      setText("product-candidate-action-result", state.actionResult);
      setText(
        "product-candidate-files-summary",
        copy().files + " · " + String((candidate.files || []).length)
      );
      setText("btn-product-file-content", copy().content);
      setText("btn-product-file-diff", copy().changes);
      setText("product-candidate-details-summary", copy().details);
      clear(els.candidateDetails);
      els.candidateDetails.appendChild(
        element("p", "", copy().implementationSummary)
      );
      var capabilities = [];
      (plan.sections || []).forEach(function (section) {
        (section.work_items || []).forEach(function (item) {
          (item.capsule_bindings || []).forEach(function (binding) {
            if (capabilities.indexOf(binding.display_name) === -1) {
              capabilities.push(binding.display_name);
            }
          });
        });
      });
      if (capabilities.length) {
        els.candidateDetails.appendChild(
          element("p", "", copy().capability + " · " + capabilities.join("、"))
        );
      }
      clear(els.candidateFileList);
      (candidate.files || []).forEach(function (file, index) {
        var button = element("button", "product-candidate-file", file.path);
        button.type = "button";
        button.dataset.fileIndex = String(index);
        button.setAttribute("aria-current", index === state.fileIndex ? "true" : "false");
        els.candidateFileList.appendChild(button);
      });
      renderFilePayload();
    }

    function renderEvidenceThread() {
      var c = copy();
      var steps = [
        { id: "product-evidence-goal", label: "product-evidence-goal-label", text: c.evidenceGoal },
        { id: "product-evidence-plan", label: "product-evidence-plan-label", text: c.evidencePlan },
        { id: "product-evidence-verify", label: "product-evidence-verify-label", text: c.evidenceVerify },
        { id: "product-evidence-save", label: "product-evidence-save-label", text: c.evidenceSave },
      ];
      var current = 0;
      if (state.view === "progress") current = state.runKind === "candidate" ? 2 : 1;
      if (
        state.view === "questions" ||
        state.view === "review" ||
        state.view === "section"
      ) {
        current = 1;
      }
      if (state.view === "handoff") current = 2;
      if (state.view === "candidate") current = 3;
      var saved =
        state.view === "candidate" &&
        (state.actionResult === c.saved || state.actionResult === c.alreadySaved);
      var thread = $("product-evidence-thread");
      if (thread) thread.setAttribute("aria-label", c.evidenceLabel);
      steps.forEach(function (step, index) {
        var item = $(step.id);
        setText(step.label, step.text);
        if (!item) return;
        var complete = index < current || (index === 3 && saved);
        item.classList.toggle("is-complete", complete);
        item.classList.toggle("is-current", index === current && !saved);
        if (index === current && !saved) item.setAttribute("aria-current", "step");
        else item.removeAttribute("aria-current");
      });
    }

    function renderFilePayload() {
      els.fileContent.setAttribute(
        "aria-selected",
        state.fileMode === "content" ? "true" : "false"
      );
      els.fileDiff.setAttribute(
        "aria-selected",
        state.fileMode === "diff" ? "true" : "false"
      );
      var payload = state.filePayload;
      if (!payload) {
        els.candidateFileBody.textContent = state.fileError
          ? copy().fileUnavailable
          : "";
        return;
      }
      els.candidateFileBody.textContent =
        state.fileMode === "diff"
          ? payload.text_diff || ""
          : payload.encoding === "utf-8"
          ? payload.content
          : isZh()
          ? "二进制文件"
          : "Binary file";
    }

    function agentHandoff() {
      var value = state.workspace && state.workspace.agent_handoff;
      return value && value.schema_version === "agent_handoff_status.v1"
        ? value
        : {
            schema_version: "agent_handoff_status.v1",
            status: "none",
            created_at: null,
            revoked_at: null,
          };
    }

    function renderAgentHandoff() {
      var c = copy();
      var status = agentHandoff().status;
      setText("product-agent-handoff-title", c.handoffTitle);
      setText("product-agent-handoff-warning", c.handoffWarning);
      setText(
        "product-agent-handoff-status",
        state.handoffMessage ||
          (status === "active"
            ? c.handoffActive
            : status === "revoked"
            ? c.handoffRevoked
            : status === "stale"
            ? c.handoffStale
            : c.handoffConflict)
      );
      var error = $("product-agent-handoff-error");
      if (error) {
        error.classList.toggle("hidden", !state.handoffError);
        error.textContent = state.handoffError;
      }
      var reissue = $("btn-reissue-agent-handoff");
      var direct = $("btn-direct-after-handoff");
      var revoke = $("btn-revoke-agent-handoff");
      if (reissue) reissue.classList.toggle("hidden", status !== "revoked");
      if (direct) direct.classList.toggle("hidden", status !== "revoked");
      if (revoke) {
        revoke.classList.toggle(
          "hidden",
          !["active", "stale", "conflict"].includes(status)
        );
      }
    }

    function render() {
      var c = copy();
      setText("btn-open-product-plan", c.entry);
      setText("btn-product-plan-back", c.back);
      setText("btn-product-nav", c.productNav);
      setText("btn-open-target", c.targetNav);
      setText("btn-product-open-warehouse", c.warehouseNav);
      setText("btn-product-open-ingestion", c.ingestionNav);
      setText("btn-product-lang", isZh() ? "中 / EN" : "EN / 中");
      var productLanguage = $("btn-product-lang");
      if (productLanguage) {
        productLanguage.setAttribute("aria-label", c.language);
        productLanguage.title = c.language;
      }
      setText("product-plan-kicker", c.kicker);
      setText("product-plan-title", c.title);
      setText("product-plan-compose-title", c.composeTitle);
      setText("product-plan-compose-copy", c.composeCopy);
      setText("product-plan-goal-label", c.goalLabel);
      setText("btn-submit-product-goal", c.createPlan);
      setText("product-plan-progress-title", c.planningTitle);
      setText("product-plan-progress-copy", c.planningCopy);
      setText("btn-cancel-product-plan", c.cancel);
      setText("product-plan-questions-title", c.questionsTitle);
      setText("product-plan-questions-copy", c.questionsCopy);
      setText("btn-submit-product-answers", c.continue);
      setText("product-acceptance-title", c.keyOutcomes);
      setText("product-acceptance-copy", c.outcomesCopy);
      setText("btn-add-product-acceptance-case", c.addOutcome);
      setText("btn-confirm-and-generate", c.confirmGenerate);
      setText("btn-confirm-and-agent", c.confirmAgent);
      setText("btn-reissue-agent-handoff", c.handoffReissue);
      setText("btn-direct-after-handoff", c.handoffDirect);
      setText("btn-revoke-agent-handoff", c.handoffRevoke);
      setText("btn-preview-product-candidate", c.preview);
      setText("btn-save-product-candidate", c.save);
      setText("product-plan-failed-title", c.failedTitle);
      setText(
        "product-plan-failed-copy",
        state.error === "product_plan_capability_gap_target_unmatched"
          ? c.gapTargetUnmatched
          : c.failedCopy
      );
      setText("btn-retry-product-flow", c.retry);
      setText("btn-product-plan-section-back", c.sectionBack);
      if (els.goal) {
        els.goal.placeholder = c.goalPlaceholder;
        if (document.activeElement !== els.goal) els.goal.value = state.goal;
      }
      var canOpen = planningAvailable();
      if (els.entry) {
        els.entry.disabled = !canOpen;
        els.entry.title = canOpen ? "" : c.noPlanner;
      }
      updateGoalAction();
      renderModelSetup();
      if (els.cancelRun) {
        els.cancelRun.classList.toggle(
          "hidden",
          state.view === "progress" && state.runKind === "candidate"
        );
      }

      showView("product-plan-compose", state.view === "compose");
      showView("product-plan-progress", state.view === "progress");
      showView("product-plan-questions", state.view === "questions");
      showView("product-plan-review", state.view === "review");
      showView("product-plan-section-review", state.view === "section");
      showView("product-agent-handoff", state.view === "handoff");
      showView("product-candidate-review", state.view === "candidate");
      showView("product-plan-failed", state.view === "failed");

      var status = {
        compose: c.statusCompose,
        progress: c.statusWorking,
        questions: c.statusQuestions,
        review: c.statusReview,
        section: c.statusReview,
        handoff: c.statusReview,
        candidate: c.statusCandidate,
        failed: c.statusFailed,
      }[state.view];
      setText("product-plan-status", status);
      renderEvidenceThread();
      if (state.view === "questions") renderQuestions();
      if (state.view === "review") renderPlan();
      if (state.view === "section") renderSectionDetail();
      if (state.view === "handoff") renderAgentHandoff();
      if (state.view === "candidate") renderCandidate();
    }

    function applyReplanAcceptanceSuggestions(workspace) {
      var replan = workspace.capability_replan;
      var suggestions =
        replan && Array.isArray(replan.acceptance_suggestions)
          ? replan.acceptance_suggestions
          : [];
      if (
        !replan ||
        replan.status !== "started" ||
        replan.successor_plan_token !== workspace.plan_token ||
        !replan.handoff_digest ||
        state.acceptanceSuggestionDigest === replan.handoff_digest ||
        !suggestions.length
      ) {
        return;
      }
      var rows = suggestions.map(function (item) {
        var inputKeys = Object.keys(item.input || {});
        var outputKeys = Object.keys(item.expected_output || {});
        if (!inputKeys.length || !outputKeys.length) return null;
        var input = {};
        var expected = {};
        inputKeys.forEach(function (key) {
          input[key] = String(item.input[key]);
        });
        outputKeys.forEach(function (key) {
          expected[key] = String(item.expected_output[key]);
        });
        return {
          input: input,
          expected: expected,
        };
      });
      if (rows.every(Boolean)) {
        state.acceptanceRows = rows;
        state.acceptanceSuggestionDigest = replan.handoff_digest;
      }
    }

    function updateWorkspace(workspace) {
      if (!workspace || typeof workspace !== "object") {
        fail("product_plan_workspace_failed");
        return;
      }
      state.workspace = workspace;
      state.planToken = String(workspace.plan_token || state.planToken || "");
      state.goal = String(workspace.goal || state.goal || "");
      state.sectionIndex = -1;
      state.sectionFocusId = "";
      if (workspace.status === "needs_clarification") {
        state.view = "questions";
      } else if (workspace.status === "plan_review") {
        state.view = "review";
        applyReplanAcceptanceSuggestions(workspace);
        prepareAcceptanceShape();
      } else if (workspace.status === "confirmed") {
        if (
          workspace.agent_handoff &&
          workspace.agent_handoff.schema_version ===
            "agent_handoff_status.v1" &&
          workspace.agent_handoff.status !== "none"
        ) {
          state.view = "handoff";
          render();
          return;
        }
        restoreConfirmedCandidate();
        return;
      } else if (workspace.status === "failed") {
        fail(
          workspace.failure_code ||
            (workspace.developer_evidence &&
              workspace.developer_evidence.failure_code) ||
            "product_plan_failed"
        );
        return;
      } else {
        fail("product_plan_interrupted");
        return;
      }
      render();
    }

    function submitGoal() {
      if (!planningAvailable() || !selectedPlanningModel()) {
        state.modelPickerOpen = true;
        render();
        els.modelConfigure.focus();
        return;
      }
      var goal = String(els.goal.value || "").trim();
      if (!goal) {
        els.goal.focus();
        return;
      }
      state.goal = goal;
      state.workspace = null;
      state.planToken = "";
      state.parameterOffer = null;
      state.parameterValues = [];
      state.acceptanceRows = [{ input: {}, expected: {} }];
      state.acceptanceShape = null;
      state.candidate = null;
      state.candidateToken = "";
      state.sectionIndex = -1;
      state.sectionFocusId = "";
      state.gapDrafts = {};
      state.acceptanceSuggestionDigest = "";
      state.handoffError = "";
      state.handoffMessage = "";
      startRun(
        "start_product_plan",
        "get_product_plan_run",
        { goal: goal },
        "plan"
      )
        .then(updateWorkspace)
        .catch(fail);
    }

    function collectAnswers() {
      var questionSet = state.workspace && state.workspace.question_set;
      var questions = questionSet && questionSet.questions;
      if (!Array.isArray(questions)) return null;
      var answers = [];
      for (var index = 0; index < questions.length; index += 1) {
        var selected = els.questionForm.querySelector(
          'input[name="product-question-' + index + '"]:checked'
        );
        if (!selected) return null;
        if (selected.value === "custom") {
          var custom = els.questionForm.querySelector(
            '[data-question-index="' + index + '"]'
          );
          var value = String((custom && custom.value) || "").trim();
          if (!value) return null;
          answers.push({
            question_id: questions[index].question_id,
            source: "custom",
            value: value,
          });
        } else {
          var option = questions[index].options[Number(selected.value)];
          if (!option) return null;
          answers.push({
            question_id: questions[index].question_id,
            source: "option",
            value: option.option_id,
          });
        }
      }
      return answers;
    }

    function submitAnswers() {
      var answers = collectAnswers();
      if (!answers) {
        setText("product-plan-questions-copy", copy().chooseAnswer);
        return;
      }
      var questionSet = state.workspace.question_set;
      startRun(
        "submit_product_plan_answers",
        "get_product_plan_run",
        {
          plan_token: state.planToken,
          question_set_digest: questionSet.digest,
          answers: answers,
        },
        "answers"
      )
        .then(updateWorkspace)
        .catch(fail);
    }

    function exactVersion(detail, versionId) {
      var data = detail && detail.ok === true ? detail.data : null;
      var versions = data && Array.isArray(data.versions) ? data.versions : [];
      return (
        versions.find(function (version) {
          return version.version_id === versionId;
        }) || null
      );
    }

    function prepareAcceptanceShape() {
      var plan = currentPlan();
      if (!plan) return;
      var computations = [];
      var interaction = null;
      var requirementIds = [];
      (plan.sections || []).forEach(function (section) {
        (section.work_items || []).forEach(function (item) {
          (item.capsule_bindings || []).forEach(function (binding) {
            if (binding.capability_kind === "computation") {
              computations.push({ binding: binding, item: item });
              (item.requirement_ids || []).forEach(function (id) {
                if (requirementIds.indexOf(id) === -1) requirementIds.push(id);
              });
            }
            if (binding.capability_kind === "interaction") {
              interaction = interaction || binding;
            }
          });
        });
      });
      var computationIds = computations.map(function (entry) {
        return entry.item.work_item_id;
      });
      var rootComputations = computations.filter(function (entry) {
        return !(entry.item.depends_on || []).some(function (dependencyId) {
          return computationIds.indexOf(dependencyId) !== -1;
        });
      });
      var terminalComputations = computations.filter(function (entry) {
        return !computations.some(function (other) {
          return (other.item.depends_on || []).indexOf(entry.item.work_item_id) !== -1;
        });
      });
      if (
        rootComputations.length !== 1 ||
        terminalComputations.length !== 1
      ) {
        state.acceptanceShape = null;
        render();
        return;
      }
      var rootComputation = rootComputations[0].binding;
      var terminalComputation = terminalComputations[0].binding;
      var requests = [
        call("get_capsule_detail", {
          capsule_id: terminalComputation.capsule_id,
        }),
      ];
      if (interaction) {
        requests.push(
          call("get_capsule_detail", { capsule_id: interaction.capsule_id })
        );
      } else if (rootComputation.capsule_id !== terminalComputation.capsule_id) {
        requests.push(
          call("get_capsule_detail", { capsule_id: rootComputation.capsule_id })
        );
      }
      Promise.all(requests).then(function (details) {
        var terminalVersion = exactVersion(
          details[0],
          terminalComputation.version_id
        );
        var interactionVersion = interaction
          ? exactVersion(details[1], interaction.version_id)
          : null;
        var rootVersion = interaction
          ? null
          : rootComputation.capsule_id === terminalComputation.capsule_id
            ? terminalVersion
            : exactVersion(details[1], rootComputation.version_id);
        var rootInput =
          rootVersion &&
          (rootVersion.input_contract_json || rootVersion.input_contract);
        var computationOutput =
          terminalVersion &&
          (terminalVersion.output_contract_json ||
            terminalVersion.output_contract);
        var interactionOutput =
          interactionVersion &&
          (interactionVersion.output_contract_json ||
            interactionVersion.output_contract);
        var events =
          interactionOutput &&
          interactionOutput.schema === "event_outputs.v1" &&
          interactionOutput.events;
        var eventNames = events && Object.keys(events);
        var runtimeInput = interaction
          ? eventNames && eventNames.length === 1
            ? events[eventNames[0]]
            : null
          : rootInput;
        var inputKeys =
          runtimeInput &&
          runtimeInput.type === "object" &&
          Array.isArray(runtimeInput.required)
            ? runtimeInput.required.slice().sort()
            : [];
        var outputKeys =
          computationOutput &&
          computationOutput.type === "object" &&
          Array.isArray(computationOutput.required)
            ? computationOutput.required.slice().sort()
            : [];
        if (
          !runtimeInput ||
          !inputKeys.length ||
          !outputKeys.length ||
          !runtimeInput.properties ||
          !computationOutput.properties ||
          inputKeys.some(function (key) {
            return !acceptanceScalarSupported(runtimeInput.properties[key]);
          }) ||
          outputKeys.some(function (key) {
            return !acceptanceScalarSupported(
              computationOutput.properties[key]
            );
          })
        ) {
          state.acceptanceShape = null;
        } else {
          state.acceptanceShape = {
            inputFields: inputKeys.map(function (key) {
              return {
                key: key,
                contract: runtimeInput.properties[key],
              };
            }),
            outputFields: outputKeys.map(function (key) {
              return {
                key: key,
                contract: computationOutput.properties[key],
              };
            }),
            requirementIds: requirementIds.slice().sort(),
          };
        }
        if (state.view === "review") render();
      });
    }

    function canonicalDecimal(text) {
      var value = String(text).trim();
      if (!/^-?\d+(?:\.\d+)?$/.test(value)) throw new Error("decimal");
      var negative = value.charAt(0) === "-";
      var unsigned = negative ? value.slice(1) : value;
      var pieces = unsigned.split(".");
      var integer = pieces[0].replace(/^0+(?=\d)/, "");
      var fraction = (pieces[1] || "").replace(/0+$/, "");
      if (integer.length > 18) throw new Error("decimal");
      if (negative && /^0+$/.test(integer) && !/[1-9]/.test(fraction)) {
        throw new Error("decimal");
      }
      var canonical = integer + (fraction ? "." + fraction : "");
      return negative ? "-" + canonical : canonical;
    }

    function compareDecimals(left, right) {
      var leftNegative = left.charAt(0) === "-";
      var rightNegative = right.charAt(0) === "-";
      if (leftNegative !== rightNegative) return leftNegative ? -1 : 1;
      var leftParts = (leftNegative ? left.slice(1) : left).split(".");
      var rightParts = (rightNegative ? right.slice(1) : right).split(".");
      var magnitude = 0;
      if (leftParts[0].length !== rightParts[0].length) {
        magnitude = leftParts[0].length < rightParts[0].length ? -1 : 1;
      } else if (leftParts[0] !== rightParts[0]) {
        magnitude = leftParts[0] < rightParts[0] ? -1 : 1;
      } else {
        var width = Math.max(
          (leftParts[1] || "").length,
          (rightParts[1] || "").length
        );
        var leftFraction = (leftParts[1] || "").padEnd(width, "0");
        var rightFraction = (rightParts[1] || "").padEnd(width, "0");
        magnitude =
          leftFraction === rightFraction
            ? 0
            : leftFraction < rightFraction
            ? -1
            : 1;
      }
      return leftNegative ? -magnitude : magnitude;
    }

    function acceptanceScalarSupported(contract) {
      if (!contract || typeof contract !== "object") return false;
      if (contract.type === "boolean") return true;
      if (contract.type === "integer") {
        return (
          Number.isSafeInteger(contract.minimum) &&
          Number.isSafeInteger(contract.maximum) &&
          contract.minimum <= contract.maximum &&
          (!("enum" in contract) ||
            (Array.isArray(contract.enum) &&
              contract.enum.every(Number.isSafeInteger)))
        );
      }
      if (contract.type === "string") {
        return (
          Number.isInteger(contract.min_length) &&
          Number.isInteger(contract.max_length) &&
          contract.min_length >= 0 &&
          contract.min_length <= contract.max_length &&
          contract.max_length <= 10000 &&
          (!("enum" in contract) ||
            (Array.isArray(contract.enum) &&
              contract.enum.every(function (item) {
                return typeof item === "string";
              })))
        );
      }
      if (contract.type !== "decimal") return false;
      try {
        return (
          Number.isInteger(contract.max_scale) &&
          contract.max_scale >= 0 &&
          contract.max_scale <= 18 &&
          canonicalDecimal(contract.minimum) === contract.minimum &&
          canonicalDecimal(contract.maximum) === contract.maximum &&
          compareDecimals(contract.minimum, contract.maximum) <= 0 &&
          (!("enum" in contract) ||
            (Array.isArray(contract.enum) &&
              contract.enum.every(function (item) {
                return canonicalDecimal(item) === item;
              })))
        );
      } catch (_error) {
        return false;
      }
    }

    function parseValue(text, contract) {
      var raw = text === undefined || text === null ? "" : String(text);
      if (!acceptanceScalarSupported(contract)) throw new Error("unsupported");
      if (contract.type === "integer") {
        var value = raw.trim();
        if (!/^-?\d+$/.test(value)) throw new Error("integer");
        var integer = Number(value);
        if (
          !Number.isSafeInteger(integer) ||
          integer < contract.minimum ||
          integer > contract.maximum ||
          (Array.isArray(contract.enum) &&
            contract.enum.indexOf(integer) === -1)
        ) {
          throw new Error("range");
        }
        return integer;
      }
      if (contract.type === "decimal") {
        var decimal = canonicalDecimal(raw);
        var scale = decimal.includes(".")
          ? decimal.length - decimal.indexOf(".") - 1
          : 0;
        if (
          scale > contract.max_scale ||
          compareDecimals(decimal, contract.minimum) < 0 ||
          compareDecimals(decimal, contract.maximum) > 0 ||
          (Array.isArray(contract.enum) &&
            contract.enum.indexOf(decimal) === -1)
        ) {
          throw new Error("decimal");
        }
        return decimal;
      }
      if (contract.type === "boolean") {
        if (raw === "true") return true;
        if (raw === "false") return false;
        throw new Error("boolean");
      }
      if (
        raw.length < contract.min_length ||
        raw.length > contract.max_length ||
        (Array.isArray(contract.enum) && contract.enum.indexOf(raw) === -1)
      ) {
        throw new Error("string");
      }
      return raw;
    }

    function acceptanceCases() {
      var shape = state.acceptanceShape;
      if (!shape || !shape.requirementIds.length) return null;
      try {
        return state.acceptanceRows.map(function (row) {
          var input = {};
          var output = {};
          shape.inputFields.forEach(function (field) {
            input[field.key] = parseValue(
              (row.input || {})[field.key],
              field.contract
            );
          });
          shape.outputFields.forEach(function (field) {
            output[field.key] = parseValue(
              (row.expected || {})[field.key],
              field.contract
            );
          });
          return {
            requirement_ids: shape.requirementIds.slice(),
            input: input,
            expected_output: output,
          };
        });
      } catch (_error) {
        return null;
      }
    }

    function parameterConfirmation() {
      var offer = state.parameterOffer;
      if (!offer) return null;
      var values = [];
      for (var index = 0; index < offer.bindings.length; index += 1) {
        var binding = offer.bindings[index];
        var value = state.parameterValues[index];
        if (!Number.isInteger(value)) return null;
        values.push({ binding_id: binding.binding_id, value: value });
      }
      return {
        schema_version: "parameterized_execution_confirmation.v1",
        offer_digest: offer.offer_digest,
        values: values,
      };
    }

    function startCandidate(acceptanceDigest) {
      var plan = currentPlan();
      return startRun(
        "start_confirmed_product_candidate",
        "get_product_candidate_run",
        {
          plan_token: state.planToken,
          plan_digest: plan.canonical_digest,
          acceptance_confirmation_digest: acceptanceDigest,
        },
        "candidate"
      ).then(function (candidate) {
        state.candidate = candidate;
        state.candidateToken = candidate.candidate_token;
        state.view = "candidate";
        state.fileIndex = 0;
        state.fileMode = "content";
        state.filePayload = null;
        state.fileError = "";
        state.actionResult = "";
        render();
        readCandidateFile(0).catch(function () {
          state.filePayload = null;
          state.fileError = "product_candidate_file_read_failed";
          renderCandidate();
        });
        return candidate;
      });
    }

    function confirmPlanAndAcceptance() {
      if (planGaps().length) {
        els.reviewError.classList.remove("hidden");
        setText("product-plan-review-error", copy().gapBlockGenerate);
        return Promise.resolve(null);
      }
      var cases = acceptanceCases();
      if (!cases) {
        els.reviewError.classList.remove("hidden");
        setText(
          "product-plan-review-error",
          state.acceptanceShape ? copy().reviewError : copy().unsupported
        );
        return Promise.resolve(null);
      }
      els.reviewError.classList.add("hidden");
      var plan = currentPlan();
      var request = {
        plan_token: state.planToken,
        plan_digest: plan.canonical_digest,
        reviewed_plan: plan,
      };
      if (state.parameterOffer) {
        var parameter = parameterConfirmation();
        if (!parameter) {
          els.reviewError.classList.remove("hidden");
          setText("product-plan-review-error", copy().reviewError);
          return Promise.resolve(null);
        }
        request.parameter_confirmation = parameter;
      }
      state.view = "progress";
      render();
      return call("confirm_product_plan", request)
        .then(function (confirmed) {
          if (
            confirmed &&
            confirmed.ok === false &&
            errorCode(confirmed, "") === "parameter_confirmation_required" &&
            confirmed.data &&
            confirmed.data.parameter_offer
          ) {
            state.parameterOffer = confirmed.data.parameter_offer;
            state.parameterValues = state.parameterOffer.bindings.map(function () {
              return undefined;
            });
            state.view = "review";
            render();
            window.setTimeout(function () {
              var input = els.parameterConfirmation.querySelector("input");
              if (input) input.focus();
            }, 0);
            return null;
          }
          if (!confirmed || confirmed.ok !== true) {
            throw errorCode(confirmed, "product_plan_confirmation_failed");
          }
          state.workspace = confirmed.data;
          return call("confirm_product_candidate_acceptance", {
            plan_token: state.planToken,
            plan_digest: plan.canonical_digest,
            acceptance_cases: cases,
          });
        })
        .then(function (acceptance) {
          if (acceptance === null) return null;
          if (!acceptance || acceptance.ok !== true) {
            throw errorCode(
              acceptance,
              "candidate_acceptance_confirmation_failed"
            );
          }
          return acceptance.data;
        });
    }

    function confirmAndGenerate() {
      confirmPlanAndAcceptance()
        .then(function (acceptance) {
          return acceptance
            ? startCandidate(acceptance.canonical_digest)
            : null;
        })
        .catch(fail);
    }

    function showAgentHandoffError(code) {
      var value = String(code || copy().handoffIssueFailed);
      state.handoffError = value;
      state.handoffMessage = "";
      var status = agentHandoff().status;
      state.view = status === "none" ? "review" : "handoff";
      if (state.view === "review") {
        els.reviewError.classList.remove("hidden");
        setText("product-plan-review-error", value);
      }
      render();
      window.setTimeout(function () {
        var target =
          state.view === "handoff"
            ? $("product-agent-handoff-title")
            : $("btn-confirm-and-agent");
        if (target) target.focus();
      }, 0);
    }

    function refreshAgentHandoff(code) {
      return call("get_product_plan_workspace", {
        plan_token: state.planToken,
      }).then(function (result) {
        if (!result || result.ok !== true) {
          throw errorCode(result, code);
        }
        if (
          code &&
          result.data &&
          result.data.agent_handoff &&
          result.data.agent_handoff.status === "none"
        ) {
          state.workspace = result.data;
          state.view = "review";
          showAgentHandoffError(code);
          return result.data;
        }
        updateWorkspace(result.data);
        if (code) showAgentHandoffError(code);
        return result.data;
      });
    }

    function issueAgentHandoff() {
      state.handoffError = "";
      state.handoffMessage = "";
      return call("copy_local_agent_handoff_binding", {
        plan_token: state.planToken,
      })
        .then(function (result) {
          if (!result || result.ok !== true || !result.data) {
            throw errorCode(result, copy().handoffIssueFailed);
          }
          var createdAt = result.data.created_at || null;
          state.workspace.agent_handoff = {
            schema_version: "agent_handoff_status.v1",
            status: "active",
            created_at: createdAt,
            revoked_at: null,
          };
          state.handoffMessage = copy().handoffCopied;
          state.view = "handoff";
          render();
          window.setTimeout(function () {
            var title = $("product-agent-handoff-title");
            if (title) title.focus();
          }, 0);
        })
        .catch(function (code) {
          return refreshAgentHandoff(String(code || "")).catch(function () {
            showAgentHandoffError(code);
          });
        });
    }

    function confirmAndHandOff() {
      confirmPlanAndAcceptance()
        .then(function (acceptance) {
          return acceptance ? issueAgentHandoff() : null;
        })
        .catch(showAgentHandoffError);
    }

    function revokeAgentHandoff() {
      state.handoffError = "";
      call("revoke_local_agent_handoff", {
        plan_token: state.planToken,
      })
        .then(function (result) {
          if (!result || result.ok !== true) {
            throw errorCode(result, copy().handoffRevokeFailed);
          }
          return refreshAgentHandoff("");
        })
        .catch(showAgentHandoffError);
    }

    function startDirectAfterHandoff() {
      state.view = "progress";
      render();
      call("get_confirmed_product_plan", { plan_token: state.planToken })
        .then(function (restored) {
          var acceptance =
            restored &&
            restored.ok === true &&
            restored.data &&
            restored.data.candidate_acceptance;
          if (!acceptance || acceptance.confirmed !== true) {
            throw errorCode(restored, "product_plan_workspace_failed");
          }
          return startCandidate(acceptance.confirmation_digest);
        })
        .catch(fail);
    }

    function restoreConfirmedCandidate() {
      state.view = "progress";
      render();
      call("get_confirmed_product_plan", { plan_token: state.planToken })
        .then(function (restored) {
          if (!restored || restored.ok !== true) {
            throw errorCode(restored, "product_plan_workspace_failed");
          }
          var data = restored.data;
          if (
            !data.candidate_acceptance ||
            data.candidate_acceptance.confirmed !== true
          ) {
            state.view = "review";
            prepareAcceptanceShape();
            render();
            return null;
          }
          state.acceptanceRows = data.candidate_acceptance.cases.map(function (
            item
          ) {
            var input = {};
            var expected = {};
            Object.keys(item.input || {}).forEach(function (key) {
              input[key] = String(item.input[key]);
            });
            Object.keys(item.expected_output || {}).forEach(function (key) {
              expected[key] = String(item.expected_output[key]);
            });
            return { input: input, expected: expected };
          });
          return startCandidate(
            data.candidate_acceptance.confirmation_digest
          );
        })
        .catch(fail);
    }

    function readCandidateFile(index) {
      var files = state.candidate && state.candidate.files;
      if (!Array.isArray(files) || !files[index]) return Promise.resolve();
      state.fileIndex = index;
      state.fileError = "";
      return call("read_product_candidate_file", {
        candidate_token: state.candidateToken,
        relative_path: files[index].path,
      }).then(function (result) {
        if (!result || result.ok !== true) {
          throw errorCode(result, "product_candidate_file_read_failed");
        }
        state.filePayload = result.data;
        if (state.view === "candidate") renderCandidate();
      });
    }

    function previewCandidate() {
      if (!state.candidate || state.candidate.status !== "review_ready") {
        state.actionResult = copy().noPreview;
        renderCandidate();
        return;
      }
      call("preview_product_candidate", {
        candidate_token: state.candidateToken,
      }).then(function (result) {
        state.actionResult =
          result && result.ok === true ? copy().opened : copy().noPreview;
        renderCandidate();
      });
    }

    function saveCandidate() {
      call("choose_product_candidate_export_folder", {
        plan_token: state.planToken,
        candidate_token: state.candidateToken,
      }).then(function (result) {
        if (result && result.cancelled === true) return;
        var data = result && result.ok === true ? result.data : null;
        if (data && data.status === "saved") {
          state.actionResult = copy().saved;
        } else if (data && data.status === "already_saved") {
          state.actionResult = copy().alreadySaved;
        } else {
          state.actionResult = copy().failedCopy;
        }
        renderCandidate();
      });
    }

    function restoreLatest() {
      var planning = host.getPlanningState ? host.getPlanningState() : null;
      var workspaces =
        planning && Array.isArray(planning.workspaces)
          ? planning.workspaces.slice()
          : [];
      workspaces.sort(function (left, right) {
        return String(right.updated_at || "").localeCompare(
          String(left.updated_at || "")
        );
      });
      if (!workspaces.length) {
        state.view = "compose";
        render();
        return;
      }
      state.view = "progress";
      render();
      state.planToken = workspaces[0].plan_token;
      call("get_product_plan_workspace", { plan_token: state.planToken })
        .then(function (result) {
          if (!result || result.ok !== true) {
            throw errorCode(result, "product_plan_workspace_failed");
          }
          updateWorkspace(result.data);
        })
        .catch(fail);
    }

    function enterScene() {
      state.active = true;
      state.warehouseReturnPending = false;
      host.showScreen("screen-product-plan");
      render();
      if (!state.loaded) {
        state.loaded = true;
        restoreLatest();
      } else {
        window.setTimeout(function () {
          var target =
            state.view === "compose"
              ? els.goal
              : state.view === "candidate"
              ? els.candidateTitle
              : state.view === "handoff"
              ? $("product-agent-handoff-title")
              : $("product-review-title");
          if (target) target.focus();
        }, 0);
      }
    }

    function leaveScene() {
      state.active = false;
      state.warehouseReturnPending = false;
      host.showScreen("screen-main");
      window.setTimeout(function () {
        if (els.entry) els.entry.focus();
      }, 0);
    }

    function enterWarehouse(binding, trigger) {
      if (!host.openWarehouse) return;
      state.warehouseReturnPending = true;
      state.warehouseReturnFocusId = trigger && trigger.id ? trigger.id : "";
      state.warehouseReturnScroll = els.stage ? els.stage.scrollTop : 0;
      state.active = false;
      host.openWarehouse(binding ? {
        capsule_id: String(binding.capsule_id || ""),
        version_id: String(binding.version_id || ""),
        canonical_hash: String(binding.canonical_hash || ""),
      } : null);
    }

    function consumeWarehouseReturn() {
      if (!state.warehouseReturnPending) return false;
      state.warehouseReturnPending = false;
      state.active = true;
      render();
      window.setTimeout(function () {
        if (els.stage) els.stage.scrollTop = state.warehouseReturnScroll;
        var target = state.warehouseReturnFocusId ? $(state.warehouseReturnFocusId) : els.sectionTitle;
        if (target) target.focus();
      }, 0);
      return true;
    }

    function resumeScene() {
      state.active = true;
      host.showScreen("screen-product-plan");
      render();
    }

    function cacheElements() {
      els.entry = $("btn-open-product-plan");
      els.screen = $("screen-product-plan");
      els.stage = $("product-plan-stage");
      els.reviewTitle = $("product-review-title");
      els.sectionTitle = $("product-plan-section-title");
      els.sectionBody = $("product-plan-section-body");
      els.goal = $("product-plan-goal");
      els.submitGoal = $("btn-submit-product-goal");
      els.cancelRun = $("btn-cancel-product-plan");
      els.questionForm = $("product-plan-question-form");
      els.sections = $("product-plan-sections");
      els.acceptanceCases = $("product-acceptance-cases");
      els.acceptance = els.acceptanceCases
        ? els.acceptanceCases.closest(".product-acceptance")
        : null;
      els.addAcceptance = $("btn-add-product-acceptance-case");
      els.parameterConfirmation = $("product-parameter-confirmation");
      els.reviewError = $("product-plan-review-error");
      els.failedTitle = $("product-plan-failed-title");
      els.candidateTitle = $("product-candidate-title");
      els.candidateValidation = $("product-candidate-validation");
      els.candidateFileList = $("product-candidate-file-list");
      els.candidateFileBody = $("product-candidate-file-body");
      els.fileContent = $("btn-product-file-content");
      els.fileDiff = $("btn-product-file-diff");
      els.candidateDetails = $("product-candidate-details-body");
      els.modelConfigure = $("btn-product-planner-configure");
      els.modelPicker = $("product-planner-picker");
      els.modelSelect = $("product-planner-select");
      els.modelRefresh = $("btn-product-planner-refresh");
      els.modelUse = $("btn-product-planner-use");
      els.modelMessage = $("product-planner-message");
    }

    function bind() {
      if (bound) return;
      cacheElements();
      if (!els.entry || !els.screen) return;
      bound = true;
      els.entry.addEventListener("click", enterScene);
      $("btn-product-plan-back").addEventListener("click", leaveScene);
      $("btn-open-target").addEventListener("click", function () {
        state.active = false;
      });
      $("btn-product-open-warehouse").addEventListener(
        "click",
        function () { enterWarehouse(null, this); }
      );
      $("btn-product-open-ingestion").addEventListener("click", function () {
        if (host.openIngestion) host.openIngestion();
      });
      $("btn-product-lang").addEventListener("click", function () {
        if (host.toggleLocale) host.toggleLocale();
      });
      $("btn-submit-product-goal").addEventListener("click", submitGoal);
      els.modelConfigure.addEventListener("click", function () {
        state.modelPickerOpen = !state.modelPickerOpen;
        state.modelError = "";
        state.modelMessage = "";
        render();
        if (state.modelPickerOpen && !state.models.length) {
          loadPlanningModels();
        }
      });
      els.modelRefresh.addEventListener("click", loadPlanningModels);
      els.modelSelect.addEventListener("change", function () {
        var value = String(els.modelSelect.value || "");
        state.modelIndex = value === "" ? -1 : Number(value);
        state.modelError = "";
        state.modelMessage = "";
        renderModelSetup();
      });
      els.modelUse.addEventListener("click", selectPlanningModel);
      els.goal.addEventListener("keydown", function (event) {
        if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
          submitGoal();
        }
      });
      els.goal.addEventListener("input", function () {
        state.goal = els.goal.value;
        updateGoalAction();
      });
      $("btn-cancel-product-plan").addEventListener("click", function () {
        if (state.runId && state.runKind !== "candidate") {
          call("cancel_product_plan_run", { run_id: state.runId });
        }
        state.view = "compose";
        state.runId = "";
        render();
      });
      $("btn-submit-product-answers").addEventListener("click", submitAnswers);
      els.questionForm.addEventListener("input", updateQuestionAction);
      els.questionForm.addEventListener("change", updateQuestionAction);
      els.sections.addEventListener("click", function (event) {
        var button = event.target.closest("[data-section-index]");
        if (!button) return;
        openSection(Number(button.dataset.sectionIndex), button);
      });
      $("btn-product-plan-section-back").addEventListener(
        "click",
        closeSection
      );
      els.acceptanceCases.addEventListener("input", function (event) {
        var index = Number(event.target.dataset.acceptanceIndex);
        var field = event.target.dataset.acceptanceField;
        var key = event.target.dataset.acceptanceKey;
        if (
          Number.isInteger(index) &&
          state.acceptanceRows[index] &&
          (field === "input" || field === "expected") &&
          typeof key === "string"
        ) {
          state.acceptanceRows[index][field][key] = event.target.value;
          updateReviewAction();
        }
      });
      els.acceptanceCases.addEventListener("click", function (event) {
        var raw = event.target.dataset.removeAcceptanceIndex;
        if (raw === undefined) return;
        state.acceptanceRows.splice(Number(raw), 1);
        renderAcceptanceRows();
      });
      els.addAcceptance.addEventListener("click", function () {
        if (state.acceptanceRows.length >= 3) return;
        state.acceptanceRows.push({ input: {}, expected: {} });
        renderAcceptanceRows();
      });
      els.parameterConfirmation.addEventListener("input", function (event) {
        var index = Number(event.target.dataset.parameterIndex);
        if (Number.isInteger(index)) {
          var raw = String(event.target.value || "");
          state.parameterValues[index] = /^-?\d+$/.test(raw)
            ? Number(raw)
            : undefined;
          updateReviewAction();
        }
      });
      $("btn-confirm-and-generate").addEventListener(
        "click",
        confirmAndGenerate
      );
      $("btn-confirm-and-agent").addEventListener(
        "click",
        confirmAndHandOff
      );
      $("btn-reissue-agent-handoff").addEventListener(
        "click",
        issueAgentHandoff
      );
      $("btn-direct-after-handoff").addEventListener(
        "click",
        startDirectAfterHandoff
      );
      $("btn-revoke-agent-handoff").addEventListener(
        "click",
        revokeAgentHandoff
      );
      $("btn-preview-product-candidate").addEventListener(
        "click",
        previewCandidate
      );
      $("btn-save-product-candidate").addEventListener("click", saveCandidate);
      els.candidateFileList.addEventListener("click", function (event) {
        var button = event.target.closest("[data-file-index]");
        if (!button) return;
        readCandidateFile(Number(button.dataset.fileIndex)).catch(fail);
      });
      els.fileContent.addEventListener("click", function () {
        state.fileMode = "content";
        renderFilePayload();
      });
      els.fileDiff.addEventListener("click", function () {
        state.fileMode = "diff";
        renderFilePayload();
      });
      $("btn-retry-product-flow").addEventListener("click", function () {
        state.view = "compose";
        state.error = "";
        render();
        window.setTimeout(function () {
          els.goal.focus();
          els.goal.select();
        }, 0);
      });
      document.addEventListener("keydown", function (event) {
        if (!state.active || event.key !== "Escape") return;
        if (state.view === "progress") return;
        if (document.querySelector(".popover:not(.hidden)")) return;
        if (state.view === "section") {
          closeSection();
          return;
        }
        leaveScene();
      });
      render();
    }

    function sync() {
      render();
    }

    function getState() {
      return {
        active: state.active,
        view: state.view,
        has_goal: !!state.goal,
        has_plan: !!currentPlan(),
        question_count:
          state.workspace &&
          state.workspace.question_set &&
          Array.isArray(state.workspace.question_set.questions)
            ? state.workspace.question_set.questions.length
            : 0,
        acceptance_case_count: state.acceptanceRows.length,
        acceptance_supported: !!state.acceptanceShape,
        capability_gap_count: planGaps().length,
        agent_handoff_status: agentHandoff().status,
        planning_model_selected: !!selectedPlanningModel(),
        section_open: state.view === "section",
        candidate_status: state.candidate ? state.candidate.status : null,
        candidate_file_count:
          state.candidate && Array.isArray(state.candidate.files)
            ? state.candidate.files.length
            : 0,
      };
    }

    return {
      bind: bind,
      sync: sync,
      open: enterScene,
      getState: getState,
      consumeWarehouseReturn: consumeWarehouseReturn,
      resume: resumeScene,
      refreshCurrentWorkspace: refreshCurrentWorkspace,
    };
  }

  window.ReweaveProductPlanScene = { create: create };
})();
