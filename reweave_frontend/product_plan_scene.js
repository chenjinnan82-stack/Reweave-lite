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
      acceptanceRows: [{ input: "", expected: "" }],
      acceptanceShape: null,
      candidate: null,
      candidateToken: "",
      fileIndex: 0,
      fileMode: "content",
      filePayload: null,
      fileError: "",
      actionResult: "",
      error: "",
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
            entry: "产品",
            back: "返回",
            kicker: "本地产品流程",
            title: "创建产品",
            statusCompose: "描述目标",
            statusWorking: "正在准备",
            statusQuestions: "等待选择",
            statusReview: "审阅计划",
            statusCandidate: "候选可审阅",
            statusFailed: "已停止",
            composeTitle: "你想构建什么产品？",
            goalLabel: "产品目标",
            goalPlaceholder: "描述产品、用户和最重要的结果",
            createPlan: "生成计划",
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
            failedTitle: "这一步未能完成",
            failedCopy: "系统已安全停止，没有写入正式产品或用户项目。",
            retry: "重新开始",
            capability: "复用能力",
            gap: "能力缺口",
            acceptance: "验收意图",
            wave: "交付阶段",
            requirement: "需求",
            reviewError: "请完整填写关键结果后再继续。",
            unsupported: "当前计划无法用这一版简化验收表单生成候选。",
            chooseAnswer: "请回答所有阻塞问题。",
            cancelled: "已取消",
            noPreview: "候选尚未达到可预览状态。",
            noPlanner: "产品规划尚未就绪",
            fileUnavailable: "这个文件暂时无法显示，但产品仍可预览或保存。",
            implementationSummary: "隔离生成；正式产品、使用记录和用户项目均未写入。",
          }
        : {
            entry: "Product",
            back: "Back",
            kicker: "LOCAL PRODUCT WORKFLOW",
            title: "Create a product",
            statusCompose: "Describe goal",
            statusWorking: "Preparing",
            statusQuestions: "Decision needed",
            statusReview: "Review plan",
            statusCandidate: "Candidate ready",
            statusFailed: "Stopped",
            composeTitle: "What do you want to build?",
            goalLabel: "Product goal",
            goalPlaceholder: "Describe the product, its users, and the key outcome",
            createPlan: "Create plan",
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
            failedTitle: "This step could not be completed",
            failedCopy: "Reweave stopped safely. No formal product or user project was written.",
            retry: "Start again",
            capability: "Reusable capability",
            gap: "Capability gap",
            acceptance: "Acceptance",
            wave: "Delivery stage",
            requirement: "Requirement",
            reviewError: "Complete every key outcome before continuing.",
            unsupported: "This plan cannot use the simplified acceptance form in this release.",
            chooseAnswer: "Answer every blocking question.",
            cancelled: "Cancelled",
            noPreview: "The candidate is not ready for preview.",
            noPlanner: "Product planning is not ready",
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
    }

    function renderPlan() {
      var plan = currentPlan();
      clear(els.sections);
      if (!plan) return;
      setText("product-review-goal", state.goal || plan.goal);
      setText("product-review-title", plan.product_name);
      (plan.sections || []).forEach(function (section) {
        var group = element("section", "product-plan-section");
        var heading = element("h2", "", sectionTitle(section.section_id));
        group.appendChild(heading);
        (section.work_items || []).forEach(function (item) {
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
          (item.capsule_bindings || []).forEach(function (binding) {
            article.appendChild(
              element(
                "p",
                "product-plan-capability",
                copy().capability + " · " + binding.display_name
              )
            );
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
          group.appendChild(article);
        });
        els.sections.appendChild(group);
      });
      renderAcceptanceRows();
      renderParameterOffer();
    }

    function renderAcceptanceRows() {
      clear(els.acceptanceCases);
      state.acceptanceRows.forEach(function (row, index) {
        var current = element("div", "product-acceptance-row");
        var inputLabel = element("label", "");
        inputLabel.appendChild(element("span", "", copy().input));
        var input = document.createElement("input");
        input.type = "text";
        input.inputMode = "decimal";
        input.value = row.input;
        input.dataset.acceptanceIndex = String(index);
        input.dataset.acceptanceField = "input";
        inputLabel.appendChild(input);
        var expectedLabel = element("label", "");
        expectedLabel.appendChild(element("span", "", copy().expected));
        var expected = document.createElement("input");
        expected.type = "text";
        expected.inputMode = "decimal";
        expected.value = row.expected;
        expected.dataset.acceptanceIndex = String(index);
        expected.dataset.acceptanceField = "expected";
        expectedLabel.appendChild(expected);
        current.appendChild(inputLabel);
        current.appendChild(expectedLabel);
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
      els.candidateValidation.appendChild(
        element("p", "product-candidate-validation-line", "✓ " + copy().validation)
      );
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

    function render() {
      var c = copy();
      setText("btn-open-product-plan", c.entry);
      setText("btn-product-plan-back", c.back);
      setText("product-plan-kicker", c.kicker);
      setText("product-plan-title", c.title);
      setText("product-plan-compose-title", c.composeTitle);
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
      setText("btn-preview-product-candidate", c.preview);
      setText("btn-save-product-candidate", c.save);
      setText("product-plan-failed-title", c.failedTitle);
      setText("product-plan-failed-copy", c.failedCopy);
      setText("btn-retry-product-flow", c.retry);
      if (els.goal) {
        els.goal.placeholder = c.goalPlaceholder;
        if (document.activeElement !== els.goal) els.goal.value = state.goal;
      }
      var canPlan = !host.canPlanProduct || host.canPlanProduct();
      if (els.entry) {
        els.entry.disabled = !canPlan;
        els.entry.title = canPlan ? "" : c.noPlanner;
      }
      if (els.submitGoal) {
        els.submitGoal.disabled = !canPlan;
        els.submitGoal.title = canPlan ? "" : c.noPlanner;
      }
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
      showView("product-candidate-review", state.view === "candidate");
      showView("product-plan-failed", state.view === "failed");

      var status = {
        compose: c.statusCompose,
        progress: c.statusWorking,
        questions: c.statusQuestions,
        review: c.statusReview,
        candidate: c.statusCandidate,
        failed: c.statusFailed,
      }[state.view];
      setText("product-plan-status", status);
      if (state.view === "questions") renderQuestions();
      if (state.view === "review") renderPlan();
      if (state.view === "candidate") renderCandidate();
    }

    function updateWorkspace(workspace) {
      if (!workspace || typeof workspace !== "object") {
        fail("product_plan_workspace_failed");
        return;
      }
      state.workspace = workspace;
      state.planToken = String(workspace.plan_token || state.planToken || "");
      state.goal = String(workspace.goal || state.goal || "");
      if (workspace.status === "needs_clarification") {
        state.view = "questions";
      } else if (workspace.status === "plan_review") {
        state.view = "review";
        prepareAcceptanceShape();
      } else if (workspace.status === "confirmed") {
        restoreConfirmedCandidate();
        return;
      } else if (workspace.status === "failed") {
        fail("product_plan_failed");
        return;
      } else {
        fail("product_plan_interrupted");
        return;
      }
      render();
    }

    function submitGoal() {
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
      state.acceptanceRows = [{ input: "", expected: "" }];
      state.acceptanceShape = null;
      state.candidate = null;
      state.candidateToken = "";
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
      var computation = null;
      var interaction = null;
      var requirementIds = [];
      (plan.sections || []).forEach(function (section) {
        (section.work_items || []).forEach(function (item) {
          (item.capsule_bindings || []).forEach(function (binding) {
            if (binding.capability_kind === "computation") {
              computation = computation || binding;
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
      if (!computation) {
        state.acceptanceShape = null;
        render();
        return;
      }
      var requests = [
        call("get_capsule_detail", { capsule_id: computation.capsule_id }),
      ];
      if (interaction) {
        requests.push(
          call("get_capsule_detail", { capsule_id: interaction.capsule_id })
        );
      }
      Promise.all(requests).then(function (details) {
        var computationVersion = exactVersion(details[0], computation.version_id);
        var interactionVersion = interaction
          ? exactVersion(details[1], interaction.version_id)
          : null;
        var computationInput =
          computationVersion &&
          (computationVersion.input_contract_json ||
            computationVersion.input_contract);
        var computationOutput =
          computationVersion &&
          (computationVersion.output_contract_json ||
            computationVersion.output_contract);
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
          : computationInput;
        var inputKeys =
          runtimeInput &&
          runtimeInput.type === "object" &&
          Array.isArray(runtimeInput.required)
            ? runtimeInput.required.slice()
            : [];
        var outputKeys =
          computationOutput &&
          computationOutput.type === "object" &&
          Array.isArray(computationOutput.required)
            ? computationOutput.required.slice()
            : [];
        if (
          !computationInput ||
          inputKeys.length !== 1 ||
          outputKeys.length !== 1 ||
          !runtimeInput.properties ||
          !computationOutput.properties
        ) {
          state.acceptanceShape = null;
        } else {
          state.acceptanceShape = {
            inputKey: inputKeys[0],
            inputContract: runtimeInput.properties[inputKeys[0]],
            outputKey: outputKeys[0],
            outputContract: computationOutput.properties[outputKeys[0]],
            requirementIds: requirementIds.slice().sort(),
          };
        }
        if (state.view === "review") render();
      });
    }

    function parseValue(text, contract) {
      var value = String(text || "").trim();
      if (!value) throw new Error("empty");
      if (contract && contract.type === "integer") {
        if (!/^-?\d+$/.test(value)) throw new Error("integer");
        return Number(value);
      }
      if (contract && contract.type === "number") {
        var number = Number(value);
        if (!Number.isFinite(number)) throw new Error("number");
        return number;
      }
      if (contract && contract.type === "boolean") {
        if (value === "true") return true;
        if (value === "false") return false;
        throw new Error("boolean");
      }
      if (!contract || contract.type === "string") return value;
      throw new Error("unsupported");
    }

    function acceptanceCases() {
      var shape = state.acceptanceShape;
      if (!shape || !shape.requirementIds.length) return null;
      try {
        return state.acceptanceRows.map(function (row) {
          var input = {};
          var output = {};
          input[shape.inputKey] = parseValue(row.input, shape.inputContract);
          output[shape.outputKey] = parseValue(
            row.expected,
            shape.outputContract
          );
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

    function confirmAndGenerate() {
      var cases = acceptanceCases();
      if (!cases) {
        els.reviewError.classList.remove("hidden");
        setText(
          "product-plan-review-error",
          state.acceptanceShape ? copy().reviewError : copy().unsupported
        );
        return;
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
          return;
        }
        request.parameter_confirmation = parameter;
      }
      state.view = "progress";
      render();
      call("confirm_product_plan", request)
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
          return startCandidate(acceptance.data.canonical_digest);
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
            var input = Object.values(item.input || {})[0];
            var expected = Object.values(item.expected_output || {})[0];
            return { input: String(input), expected: String(expected) };
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
              : $("product-review-title");
          if (target) target.focus();
        }, 0);
      }
    }

    function leaveScene() {
      state.active = false;
      host.showScreen("screen-main");
      window.setTimeout(function () {
        if (els.entry) els.entry.focus();
      }, 0);
    }

    function cacheElements() {
      els.entry = $("btn-open-product-plan");
      els.screen = $("screen-product-plan");
      els.stage = $("product-plan-stage");
      els.goal = $("product-plan-goal");
      els.submitGoal = $("btn-submit-product-goal");
      els.cancelRun = $("btn-cancel-product-plan");
      els.questionForm = $("product-plan-question-form");
      els.sections = $("product-plan-sections");
      els.acceptanceCases = $("product-acceptance-cases");
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
    }

    function bind() {
      if (bound) return;
      cacheElements();
      if (!els.entry || !els.screen) return;
      bound = true;
      els.entry.addEventListener("click", enterScene);
      $("btn-product-plan-back").addEventListener("click", leaveScene);
      $("btn-submit-product-goal").addEventListener("click", submitGoal);
      els.goal.addEventListener("keydown", function (event) {
        if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
          submitGoal();
        }
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
      els.acceptanceCases.addEventListener("input", function (event) {
        var index = Number(event.target.dataset.acceptanceIndex);
        var field = event.target.dataset.acceptanceField;
        if (
          Number.isInteger(index) &&
          state.acceptanceRows[index] &&
          (field === "input" || field === "expected")
        ) {
          state.acceptanceRows[index][field] = event.target.value;
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
        state.acceptanceRows.push({ input: "", expected: "" });
        renderAcceptanceRows();
      });
      els.parameterConfirmation.addEventListener("input", function (event) {
        var index = Number(event.target.dataset.parameterIndex);
        if (Number.isInteger(index)) {
          var raw = String(event.target.value || "");
          state.parameterValues[index] = /^-?\d+$/.test(raw)
            ? Number(raw)
            : undefined;
        }
      });
      $("btn-confirm-and-generate").addEventListener(
        "click",
        confirmAndGenerate
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
      getState: getState,
      consumeWarehouseReturn: function () { return false; },
    };
  }

  window.ReweaveProductPlanScene = { create: create };
})();
