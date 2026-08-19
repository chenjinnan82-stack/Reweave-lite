(function () {
  "use strict";

  function create(host) {
    var els = {};
    var eventsBound = false;
    var targetWorkflow = {
      targetPath: "",
      displayName: "",
      profile: null,
      capsuleIds: [],
      patch: null,
      confirmation: null,
      developerMode: false,
      profileRevision: 0,
      patchRevision: 0,
      lastError: null,
    };

    function $(id) {
      return document.getElementById(id);
    }

    function parseBridgeJson(raw) {
      return host.parseBridgeJson(raw);
    }

    function bridgeCall(method, arg) {
      return host.bridgeCall(method, arg);
    }

    function hasTargetBridge() {
      var bridge = host.getBridge();
      return !!(
        bridge &&
        typeof bridge.choose_static_web_target === "function" &&
        typeof bridge.analyze_static_web_target === "function" &&
        typeof bridge.generate_static_web_patch === "function"
      );
    }

    function isCapsuleGenerateEligible(capsule) {
      return host.isCapsuleGenerateEligible(capsule);
    }

    function formalSelectionError(ids, requireDomRole) {
      return host.formalSelectionError(ids, requireDomRole);
    }

    function t(key) {
      return host.t(key);
    }

    function formatText(key, values) {
      return host.formatText(key, values);
    }

    function showScreen(id) {
      host.showScreen(id);
    }

    function syncAppState() {
      host.syncAppState();
    }

    function toggleLocale() {
      host.toggleLocale();
    }
    function targetChecksPassed(checks) {
      return (
        Array.isArray(checks) &&
        checks.length > 0 &&
        checks.every(function (check) {
          return check && targetDisplayString(check.name) && check.passed === true;
        })
      );
    }

    function targetSha256(value) {
      return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
    }

    function targetLogicalPath(value) {
      return (
        typeof value === "string" &&
        value.length > 0 &&
        value.charAt(0) !== "/" &&
        value.indexOf("\\") === -1 &&
        value.indexOf("%") === -1 &&
        !/[\x00-\x1f\x7f]/.test(value) &&
        value.split("/").every(function (part) {
          return part && part !== "." && part !== "..";
        })
      );
    }

    function targetExactObject(value, keys) {
      return !!(
        value &&
        typeof value === "object" &&
        !Array.isArray(value) &&
        Object.keys(value).length === keys.length &&
        keys.every(function (key) {
          return Object.prototype.hasOwnProperty.call(value, key);
        })
      );
    }

    function targetDisplayString(value) {
      return !!(
        typeof value === "string" &&
        value &&
        (!targetWorkflow.targetPath || value.indexOf(targetWorkflow.targetPath) === -1)
      );
    }

    function isSafeTargetProfile(profile) {
      var permissions = profile && profile.permissions;
      var files = profile && profile.files;
      var resources = profile && profile.resources;
      var javascript = profile && profile.javascript;
      var filePaths = {};
      var filesSafe =
        Array.isArray(files) &&
        files.length > 0 &&
        files.every(function (file) {
          var safe = !!(
            targetExactObject(file, ["path", "kind", "size_bytes", "sha256"]) &&
            targetLogicalPath(file.path) &&
            ["text", "binary"].indexOf(file.kind) !== -1 &&
            Number.isFinite(file.size_bytes) &&
            file.size_bytes >= 0 &&
            targetSha256(file.sha256) &&
            !filePaths[file.path]
          );
          if (safe) filePaths[file.path] = true;
          return safe;
        });
      var resourcesSafe =
        Array.isArray(resources) &&
        resources.every(function (resource) {
          return !!(
            targetExactObject(resource, ["from_path", "kind", "path"]) &&
            resource.from_path === profile.entry_path &&
            ["asset", "stylesheet", "javascript"].indexOf(resource.kind) !== -1 &&
            targetLogicalPath(resource.path) &&
            filePaths[resource.path]
          );
        });
      var javascriptSafe = !!(
        targetExactObject(javascript, [
          "schema_version",
          "entry_modules",
          "reachable_module_count",
          "graph_sha256",
        ]) &&
        javascript.schema_version === "source_graph.v1" &&
        Array.isArray(javascript.entry_modules) &&
        javascript.entry_modules.every(function (path) {
          return targetLogicalPath(path) && filePaths[path];
        }) &&
        Number.isInteger(javascript.reachable_module_count) &&
        javascript.reachable_module_count >= javascript.entry_modules.length &&
        (javascript.reachable_module_count === 0
          ? javascript.graph_sha256 === null
          : targetSha256(javascript.graph_sha256))
      );
      return !!(
        targetExactObject(profile, [
          "schema_version",
          "target_kind",
          "entry_path",
          "snapshot_sha256",
          "files",
          "resources",
          "javascript",
          "checks",
          "permissions",
          "source_unchanged",
        ]) &&
        profile.schema_version === "static_web_target_profile.v1" &&
        profile.target_kind === "static_web" &&
        targetLogicalPath(profile.entry_path) &&
        targetSha256(profile.snapshot_sha256) &&
        profile.source_unchanged === true &&
        filesSafe &&
        filePaths[profile.entry_path] &&
        resourcesSafe &&
        javascriptSafe &&
        targetChecksPassed(profile.checks) &&
        profile.checks.every(function (check) {
          return targetExactObject(check, ["name", "passed"]);
        }) &&
        targetExactObject(permissions, [
          "target_read",
          "target_write",
          "apply",
          "commit",
          "store_write",
          "network_access",
          "model_call",
        ]) &&
        permissions.target_read === true &&
        permissions.target_write === false &&
        permissions.apply === false &&
        permissions.commit === false &&
        permissions.store_write === false &&
        permissions.network_access === false &&
        permissions.model_call === false
      );
    }

    function isSafeTargetPatch(patch) {
      var profile = targetWorkflow.profile;
      var target = patch && patch.target;
      var authorization = patch && patch.authorization;
      var weavePlan = patch && patch.weave_plan;
      var evidence = patch && patch.evidence;
      var composer = patch && patch.composer;
      if (
        !targetExactObject(patch, [
          "schema_version",
          "status",
          "plan_id",
          "strategy",
          "target",
          "authorization",
          "weave_plan",
          "composer",
          "changes",
          "text_unified_diff",
          "evidence",
        ]) ||
        patch.schema_version !== "static_web_target_patch.v1" ||
        patch.status !== "ready_for_review" ||
        patch.strategy !== "static_web_iframe_embed.v1" ||
        !/^[A-Za-z0-9_.-]{1,128}$/.test(patch.plan_id || "") ||
        !isSafeTargetProfile(profile) ||
        !targetExactObject(target, ["entry_path", "snapshot_sha256", "profile"]) ||
        !isSafeTargetProfile(target.profile) ||
        target.snapshot_sha256 !== profile.snapshot_sha256 ||
        target.profile.snapshot_sha256 !== profile.snapshot_sha256 ||
        target.entry_path !== profile.entry_path ||
        !targetExactObject(authorization, [
          "mode",
          "target_snapshot_sha256",
          "usage_scope",
          "usage_scope_match",
          "target_project_write",
          "apply",
          "commit",
        ]) ||
        authorization.mode !== "review_patch_only" ||
        authorization.target_snapshot_sha256 !== profile.snapshot_sha256 ||
        !targetExactObject(authorization.usage_scope, ["kind"]) ||
        authorization.usage_scope.kind !== "general" ||
        authorization.usage_scope_match !== true ||
        authorization.target_project_write !== false ||
        authorization.apply !== false ||
        authorization.commit !== false ||
        !targetExactObject(weavePlan, [
          "schema_version",
          "plan_id",
          "adapter_version",
          "task",
          "capsules",
          "affected_files",
          "validation_steps",
          "failure_policy",
        ]) ||
        weavePlan.schema_version !== "static_web_weave_plan.v1" ||
        weavePlan.plan_id !== patch.plan_id ||
        weavePlan.adapter_version !== patch.strategy ||
        !targetDisplayString(weavePlan.task) ||
        weavePlan.task !== (els.targetTask ? els.targetTask.value.trim() : "") ||
        !Array.isArray(weavePlan.capsules) ||
        !Array.isArray(weavePlan.affected_files) ||
        !Array.isArray(weavePlan.validation_steps) ||
        weavePlan.failure_policy !== "stop_without_target_write" ||
        !targetExactObject(composer, [
          "composer_version",
          "connections",
          "provenance",
          "output_mapping",
        ]) ||
        !targetDisplayString(composer.composer_version) ||
        !Array.isArray(composer.connections) ||
        !composer.provenance ||
        typeof composer.provenance !== "object" ||
        Array.isArray(composer.provenance) ||
        !Array.isArray(composer.output_mapping) ||
        !targetExactObject(evidence, [
          "schema_version",
          "status",
          "checks",
          "target_project_write",
          "product_store_write",
          "usage_registration_write",
        ]) ||
        evidence.schema_version !== "static_web_target_patch_evidence.v1" ||
        evidence.status !== "passed" ||
        evidence.target_project_write !== false ||
        evidence.product_store_write !== false ||
        evidence.usage_registration_write !== false ||
        !targetChecksPassed(evidence.checks) ||
        !evidence.checks.every(function (check) {
          return targetExactObject(check, ["name", "passed"]);
        }) ||
        !Array.isArray(patch.changes) ||
        patch.changes.length === 0 ||
        !targetDisplayString(patch.text_unified_diff)
      ) {
        return false;
      }
      var changesSafe = patch.changes.every(function (change) {
        if (
          !targetExactObject(change, [
            "path",
            "operation",
            "ori" + "gin",
            "before_sha256",
            "after_sha256",
            "size_bytes",
            "content_encoding",
            "after_content",
            "diff",
          ]) ||
          !targetLogicalPath(change.path) ||
          ["add", "modify"].indexOf(change.operation) === -1 ||
          !targetSha256(change.after_sha256) ||
          !Number.isFinite(change.size_bytes) ||
          change.size_bytes < 0 ||
          ["utf-8", "base64"].indexOf(change.content_encoding) === -1
        ) {
          return false;
        }
        if (change.before_sha256 !== null && !targetSha256(change.before_sha256)) return false;
        return change.content_encoding === "utf-8"
          ? targetDisplayString(change.diff)
          : change.diff === null;
      });
      if (!changesSafe) return false;
      var selectedCapsules = targetWorkflow.capsuleIds.slice().sort();
      var patchCapsules = weavePlan.capsules.map(function (capsule) {
        return capsule && typeof capsule.capsule_id === "string" ? capsule.capsule_id : "";
      }).sort();
      return (
        selectedCapsules.join("\n") === patchCapsules.join("\n") &&
        weavePlan.affected_files.length === patch.changes.length &&
        weavePlan.affected_files.every(function (file, index) {
          return !!(
            targetExactObject(file, ["path", "operation"]) &&
            file.path === patch.changes[index].path &&
            file.operation === patch.changes[index].operation
          );
        }) &&
        weavePlan.validation_steps.every(targetDisplayString) &&
        weavePlan.capsules.every(function (capsule) {
          return !!(
            targetExactObject(capsule, [
              "capsule_id",
              "version_id",
              "canonical_hash",
              "capability_key",
              "role_key",
              "variant_key",
              "capability_kind",
              "usage_scope",
            ]) &&
            targetDisplayString(capsule.capsule_id) &&
            targetDisplayString(capsule.version_id) &&
            targetSha256(capsule.canonical_hash) &&
            targetDisplayString(capsule.capability_key) &&
            targetDisplayString(capsule.role_key) &&
            targetDisplayString(capsule.variant_key) &&
            ["presentation", "interaction", "computation"].indexOf(capsule.capability_kind) !== -1 &&
            targetExactObject(capsule.usage_scope, ["kind"]) &&
            capsule.usage_scope.kind === "general"
          );
        }) &&
        composer.connections.every(function (connection) {
          return !!(
            targetExactObject(connection, ["from_version_id", "output", "to_version_id", "input"]) &&
            targetDisplayString(connection.from_version_id) &&
            targetDisplayString(connection.output) &&
            targetDisplayString(connection.to_version_id) &&
            targetDisplayString(connection.input)
          );
        }) &&
        composer.output_mapping.every(function (mapping) {
          return !!(
            targetExactObject(mapping, ["composer_path", "target_path", "sha256"]) &&
            targetLogicalPath(mapping.composer_path) &&
            targetLogicalPath(mapping.target_path) &&
            targetSha256(mapping.sha256)
          );
        })
      );
    }

    function deriveTargetStage() {
      if (targetWorkflow.confirmation) return "confirmed";
      if (isSafeTargetPatch(targetWorkflow.patch)) return "review";
      if (isSafeTargetProfile(targetWorkflow.profile)) return "compose";
      return "select";
    }

    function setPanelHidden(node, hidden) {
      if (!node) return;
      if (hidden) node.setAttribute("hidden", "");
      else node.removeAttribute("hidden");
    }

    function applyTargetStagePresentation() {
      if (!els.screenTarget) return;
      var stage = deriveTargetStage();
      els.screenTarget.setAttribute("data-target-stage", stage);

      setPanelHidden(els.targetPanelSelect, stage !== "select");
      setPanelHidden(els.targetSummarySelect, stage === "select");
      setPanelHidden(els.targetPanelCompose, stage !== "compose");
      setPanelHidden(els.targetSummaryCompose, !(stage === "review" || stage === "confirmed"));
      setPanelHidden(els.targetReview, stage !== "review");
      setPanelHidden(els.targetPanelConfirmed, stage !== "confirmed");

      if (els.targetSelectSummaryTitle) {
        els.targetSelectSummaryTitle.textContent = targetWorkflow.displayName
          ? formatText("targetSelected", { name: targetWorkflow.displayName })
          : t("noTargetSelected");
      }
      if (els.targetSelectSummaryCopy) {
        var entry = els.targetEntryRelpath ? els.targetEntryRelpath.value.trim() : "";
        if (isSafeTargetProfile(targetWorkflow.profile) && entry) {
          els.targetSelectSummaryCopy.textContent = formatText("targetSelectSummary", {
            entry: entry,
          });
        } else if (entry) {
          els.targetSelectSummaryCopy.textContent = formatText("targetEntryPendingSummary", {
            entry: entry,
          });
        } else {
          els.targetSelectSummaryCopy.textContent = t("targetEntryRequired");
        }
      }
      if (els.targetComposeSummaryTitle) {
        els.targetComposeSummaryTitle.textContent = t("composePatch");
      }
      if (els.targetComposeSummaryCopy) {
        var task = els.targetTask ? els.targetTask.value.trim() : "";
        var capsuleCount = targetWorkflow.capsuleIds.length;
        if (!task) {
          els.targetComposeSummaryCopy.textContent = t("targetTask");
        } else if (capsuleCount === 1) {
          els.targetComposeSummaryCopy.textContent = formatText("targetComposeSummaryOne", {
            task: task,
          });
        } else {
          els.targetComposeSummaryCopy.textContent = formatText("targetComposeSummary", {
            count: String(capsuleCount),
            task: task,
          });
        }
      }
    }

    function invalidateTargetConfirmation() {
      targetWorkflow.confirmation = null;
      if (els.targetConfirmationReceipt) els.targetConfirmationReceipt.textContent = "";
    }

    function resetTargetPatch() {
      targetWorkflow.patchRevision += 1;
      targetWorkflow.patch = null;
      invalidateTargetConfirmation();
      if (targetWorkflow.lastError && targetWorkflow.lastError.kind === "patch") {
        targetWorkflow.lastError = null;
      }
      if (els.targetPatchStatus) {
        els.targetPatchStatus.textContent = "";
        clearTargetStatusError(els.targetPatchStatus);
      }
      if (els.targetRejectionEvidence) {
        els.targetRejectionEvidence.textContent = "";
        els.targetRejectionEvidence.classList.add("hidden");
      }
      if (els.targetReview) setPanelHidden(els.targetReview, true);
    }

    function resetTargetProfile() {
      targetWorkflow.profileRevision += 1;
      targetWorkflow.profile = null;
      resetTargetPatch();
      if (targetWorkflow.lastError && targetWorkflow.lastError.kind === "analysis") {
        targetWorkflow.lastError = null;
      }
      if (els.targetAnalysisStatus) {
        els.targetAnalysisStatus.textContent = "";
        clearTargetStatusError(els.targetAnalysisStatus);
      }
      clearTargetEntryInvalid();
      if (els.targetProfileSummary) els.targetProfileSummary.classList.add("hidden");
      if (els.targetProfileDeveloper) {
        els.targetProfileDeveloper.textContent = "";
      }
    }

    function renderTargetDeveloperMode() {
      if (!els.screenTarget) return;
      els.screenTarget.classList.toggle("developer-mode", targetWorkflow.developerMode);
      if (els.targetDeveloperMode) els.targetDeveloperMode.checked = targetWorkflow.developerMode;
      document.querySelectorAll("#screen-target details.target-developer-details").forEach(function (node) {
        if (!targetWorkflow.developerMode) node.removeAttribute("open");
      });
    }

    function renderTargetSelection() {
      if (!els.targetSelectedName) return;
      els.targetSelectedName.textContent = targetWorkflow.displayName
        ? formatText("targetSelected", { name: targetWorkflow.displayName })
        : t("noTargetSelected");
    }

    function targetEligibleCapsules() {
      return host.getCapsules().filter(function (cap) {
        return cap && cap.formal_version === true && isCapsuleGenerateEligible(cap);
      });
    }

    function renderTargetCapsules() {
      if (!els.targetCapsuleCards) return;
      var capsules = targetEligibleCapsules();
      var allowedIds = capsules.map(function (cap) {
        return cap.id;
      });
      var previousIds = targetWorkflow.capsuleIds.slice();
      targetWorkflow.capsuleIds = targetWorkflow.capsuleIds.filter(function (id) {
        return allowedIds.indexOf(id) !== -1;
      });
      if (previousIds.join("\n") !== targetWorkflow.capsuleIds.join("\n")) {
        resetTargetPatch();
      }
      els.targetCapsuleCards.textContent = "";
      if (!capsules.length) {
        var empty = document.createElement("p");
        empty.className = "target-empty";
        empty.textContent = t("targetNoCapsules");
        els.targetCapsuleCards.appendChild(empty);
        return;
      }
      capsules.forEach(function (cap) {
        var label = document.createElement("label");
        var checked = targetWorkflow.capsuleIds.indexOf(cap.id) !== -1;
        label.className = "target-capsule-card" + (checked ? " selected" : "");
        label.setAttribute("role", "listitem");

        var checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = checked;
        checkbox.value = cap.id;

        var body = document.createElement("span");
        body.className = "target-capsule-body";
        var name = document.createElement("strong");
        name.textContent = cap.name || cap.id;
        var meta = document.createElement("span");
        meta.className = "target-capsule-meta";
        meta.textContent = String(cap.type || cap.role || "capsule");
        var identity = document.createElement("span");
        identity.className = "target-capsule-meta target-developer-only";
        identity.textContent = String(cap.capsule_id || cap.id) + " · " + String(cap.version_id || "");
        body.appendChild(name);
        body.appendChild(meta);
        body.appendChild(identity);
        label.appendChild(checkbox);
        label.appendChild(body);

        checkbox.addEventListener("change", function () {
          var next = targetWorkflow.capsuleIds.slice();
          var index = next.indexOf(cap.id);
          if (checkbox.checked && index === -1) next.push(cap.id);
          if (!checkbox.checked && index !== -1) next.splice(index, 1);
          if (next.length > 3 || formalSelectionError(next, false)) {
            if (els.targetPatchStatus) els.targetPatchStatus.textContent = t("targetCapsuleRequired");
            renderTargetCapsules();
            syncTargetActions();
            return;
          }
          targetWorkflow.capsuleIds = next;
          resetTargetPatch();
          renderTargetCapsules();
          syncTargetActions();
        });
        els.targetCapsuleCards.appendChild(label);
      });
    }

    function appendTargetMetric(container, textValue) {
      var metric = document.createElement("span");
      metric.textContent = textValue;
      container.appendChild(metric);
    }

    function targetProfileDeveloperEvidence(profile) {
      return {
        schema_version: profile.schema_version,
        entry_path: profile.entry_path,
        snapshot_sha256: profile.snapshot_sha256,
        files: profile.files.map(function (file) {
          return {
            path: file.path,
            kind: file.kind,
            size_bytes: file.size_bytes,
            sha256: file.sha256,
          };
        }),
        resources: profile.resources.map(function (resource) {
          return {
            from_path: resource.from_path,
            kind: resource.kind,
            path: resource.path,
          };
        }),
        javascript: {
          schema_version: profile.javascript.schema_version,
          entry_modules: profile.javascript.entry_modules.slice(),
          reachable_module_count: profile.javascript.reachable_module_count,
          graph_sha256: profile.javascript.graph_sha256,
        },
        checks: profile.checks.map(function (check) {
          return { name: check.name, passed: check.passed };
        }),
        permissions: {
          target_read: profile.permissions.target_read,
          target_write: profile.permissions.target_write,
          apply: profile.permissions.apply,
          commit: profile.permissions.commit,
          store_write: profile.permissions.store_write,
          network_access: profile.permissions.network_access,
          model_call: profile.permissions.model_call,
        },
        source_unchanged: profile.source_unchanged,
      };
    }

    function renderTargetProfile() {
      if (!els.targetProfileSummary || !els.targetProfileDeveloper) return;
      var profile = targetWorkflow.profile;
      if (!profile) {
        els.targetProfileSummary.classList.add("hidden");
        els.targetProfileDeveloper.textContent = "";
        renderTargetDeveloperMode();
        return;
      }
      var checks = profile.checks || [];
      var passed = checks.filter(function (check) {
        return check.passed === true;
      }).length;
      els.targetProfileSummary.textContent = "";
      appendTargetMetric(els.targetProfileSummary, formatText("targetFileCount", { count: profile.files.length }));
      appendTargetMetric(els.targetProfileSummary, formatText("targetResourceCount", { count: profile.resources.length }));
      appendTargetMetric(els.targetProfileSummary, formatText("targetChecksPassed", { passed: passed, count: checks.length }));
      appendTargetMetric(els.targetProfileSummary, t("targetSourceUnchanged"));
      els.targetProfileSummary.classList.remove("hidden");
      els.targetProfileDeveloper.textContent = JSON.stringify(targetProfileDeveloperEvidence(profile), null, 2);
      if (els.targetAnalysisStatus) els.targetAnalysisStatus.textContent = t("targetProfileReady");
      renderTargetDeveloperMode();
    }

    function targetPatchDeveloperEvidence(patch) {
      return {
        schema_version: patch.schema_version,
        status: patch.status,
        plan_id: patch.plan_id,
        strategy: patch.strategy,
        target: {
          entry_path: patch.target.entry_path,
          snapshot_sha256: patch.target.snapshot_sha256,
        },
        authorization: {
          mode: patch.authorization.mode,
          target_snapshot_sha256: patch.authorization.target_snapshot_sha256,
          usage_scope: { kind: patch.authorization.usage_scope.kind },
          usage_scope_match: patch.authorization.usage_scope_match,
          target_project_write: patch.authorization.target_project_write,
          apply: patch.authorization.apply,
          commit: patch.authorization.commit,
        },
        weave_plan: {
          schema_version: patch.weave_plan.schema_version,
          plan_id: patch.weave_plan.plan_id,
          adapter_version: patch.weave_plan.adapter_version,
          task: patch.weave_plan.task,
          capsules: patch.weave_plan.capsules.map(function (capsule) {
            return {
              capsule_id: capsule.capsule_id,
              version_id: capsule.version_id,
              canonical_hash: capsule.canonical_hash,
              capability_key: capsule.capability_key,
              role_key: capsule.role_key,
              variant_key: capsule.variant_key,
              capability_kind: capsule.capability_kind,
              usage_scope: { kind: capsule.usage_scope.kind },
            };
          }),
          affected_files: patch.weave_plan.affected_files.map(function (file) {
            return { path: file.path, operation: file.operation };
          }),
          validation_steps: patch.weave_plan.validation_steps.slice(),
          failure_policy: patch.weave_plan.failure_policy,
        },
        composer: {
          composer_version: patch.composer.composer_version,
          connections: patch.composer.connections.map(function (connection) {
            return {
              from_version_id: connection.from_version_id,
              output: connection.output,
              to_version_id: connection.to_version_id,
              input: connection.input,
            };
          }),
          output_mapping: patch.composer.output_mapping.map(function (mapping) {
            return {
              composer_path: mapping.composer_path,
              target_path: mapping.target_path,
              sha256: mapping.sha256,
            };
          }),
        },
        evidence: {
          schema_version: patch.evidence.schema_version,
          status: patch.evidence.status,
          checks: patch.evidence.checks.map(function (check) {
            return { name: check.name, passed: check.passed };
          }),
          target_project_write: patch.evidence.target_project_write,
          product_store_write: patch.evidence.product_store_write,
          usage_registration_write: patch.evidence.usage_registration_write,
        },
        changes: patch.changes.map(function (change) {
          return {
            path: change.path,
            operation: change.operation,
            before_sha256: change.before_sha256,
            after_sha256: change.after_sha256,
            size_bytes: change.size_bytes,
            content_encoding: change.content_encoding,
          };
        }),
      };
    }

    function renderTargetPatch() {
      if (!els.targetFileDiffs || !els.targetEvidenceSummary) return;
      var patch = targetWorkflow.patch;
      if (!patch) {
        els.targetFileDiffs.textContent = "";
        els.targetEvidenceSummary.textContent = "";
        if (els.targetPatchDeveloper) els.targetPatchDeveloper.textContent = "";
        return;
      }
      var evidenceChecks = patch.evidence.checks;
      if (els.targetReviewBadge) els.targetReviewBadge.textContent = t("targetWriteZero");
      els.targetEvidenceSummary.textContent = "";
      appendTargetMetric(els.targetEvidenceSummary, formatText("targetFileCount", { count: patch.changes.length }));
      appendTargetMetric(
        els.targetEvidenceSummary,
        formatText("targetChecksPassed", { passed: evidenceChecks.length, count: evidenceChecks.length })
      );
      appendTargetMetric(els.targetEvidenceSummary, t("targetSourceUnchanged"));
      els.targetFileDiffs.textContent = "";
      patch.changes.forEach(function (change) {
        var file = document.createElement("article");
        file.className = "target-file-diff";
        var heading = document.createElement("h3");
        heading.textContent = change.operation.toUpperCase() + " · " + change.path;
        var meta = document.createElement("p");
        meta.className = "target-diff-meta";
        meta.textContent =
          change.content_encoding +
          " · " +
          String(change.size_bytes) +
          " bytes · sha256 " +
          change.after_sha256;
        file.appendChild(heading);
        file.appendChild(meta);
        if (change.content_encoding === "utf-8") {
          var label = document.createElement("p");
          label.className = "target-diff-label";
          label.textContent = t("targetTextDiff");
          var diff = document.createElement("pre");
          diff.className = "target-diff-code";
          diff.textContent = change.diff;
          file.appendChild(label);
          file.appendChild(diff);
        } else {
          var binary = document.createElement("p");
          binary.className = "target-binary-note";
          binary.textContent = t("targetBinaryDiff");
          file.appendChild(binary);
        }
        els.targetFileDiffs.appendChild(file);
      });
      if (els.targetPatchDeveloper) {
        els.targetPatchDeveloper.textContent = JSON.stringify(targetPatchDeveloperEvidence(patch), null, 2);
      }
      if (els.targetPatchStatus) els.targetPatchStatus.textContent = t("targetPatchReady");
      if (els.targetConfirmationReceipt) {
        els.targetConfirmationReceipt.textContent = targetWorkflow.confirmation
          ? formatText("targetConfirmed", { plan: targetWorkflow.confirmation.planId })
          : "";
      }
    }

    function clearTargetStatusError(status) {
      if (!status) return;
      var wasError = status.classList.contains("is-error");
      status.classList.remove("is-error");
      status.removeAttribute("role");
      status.setAttribute("aria-live", "polite");
      if (wasError) status.textContent = "";
    }

    function clearTargetEntryInvalid() {
      if (!els.targetEntryRelpath) return;
      els.targetEntryRelpath.removeAttribute("aria-invalid");
      els.targetEntryRelpath.classList.remove("is-invalid");
    }

    function markTargetEntryInvalid(code) {
      if (!els.targetEntryRelpath) return;
      if (code === "entry_not_found") {
        els.targetEntryRelpath.setAttribute("aria-invalid", "true");
        els.targetEntryRelpath.classList.add("is-invalid");
        return;
      }
      clearTargetEntryInvalid();
    }

    function targetErrorUserCopy(kind, code) {
      var prefix = kind === "analysis" ? "targetAnalysis" : "targetPatch";
      var reasonKey = prefix + "Error_" + code;
      var recoveryKey = prefix + "Recovery_" + code;
      var reason = t(reasonKey);
      if (reason === reasonKey) {
        reason = formatText(kind === "analysis" ? "targetProfileRejected" : "targetPatchRejected", {
          code: code,
        });
      }
      var recovery = t(recoveryKey);
      if (recovery === recoveryKey) {
        recovery = t(prefix + "RecoveryGeneric");
      }
      return { reason: reason, recovery: recovery };
    }

    function applyTargetStatusError(kind, code) {
      var status = kind === "analysis" ? els.targetAnalysisStatus : els.targetPatchStatus;
      if (!status) return;
      var copy = targetErrorUserCopy(kind, code);
      status.textContent = "";
      var reason = document.createElement("span");
      reason.className = "target-status-reason";
      reason.textContent = copy.reason;
      var recovery = document.createElement("span");
      recovery.className = "target-status-recovery";
      recovery.textContent = copy.recovery;
      status.appendChild(reason);
      status.appendChild(recovery);
      status.classList.add("is-error");
      status.setAttribute("role", "alert");
      status.setAttribute("aria-live", "assertive");
      if (kind === "analysis") markTargetEntryInvalid(code);
      else clearTargetEntryInvalid();
    }

    function renderTargetError(kind, result) {
      var error = result && result.error && typeof result.error === "object" ? result.error : {};
      var code =
        typeof error.code === "string" && /^[a-z][a-z0-9_]{1,95}$/.test(error.code)
          ? error.code
          : "invalid_response";
      var rawEvidence = error.evidence && typeof error.evidence === "object" ? error.evidence : {};
      var evidence = { status: "rejected", code: code };
      ["phase", "reason", "tag", "attribute", "scheme"].forEach(function (key) {
        var value = rawEvidence[key];
        if (typeof value === "string" && /^[a-z][a-z0-9_.-]{0,95}$/.test(value)) evidence[key] = value;
      });
      if (targetLogicalPath(rawEvidence.logical_path)) evidence.logical_path = rawEvidence.logical_path;
      targetWorkflow.lastError = { kind: kind, code: code, evidence: evidence };
      applyTargetStatusError(kind, code);
      if (els.targetRejectionEvidence) {
        els.targetRejectionEvidence.textContent = JSON.stringify(evidence, null, 2);
      }
      renderTargetDeveloperMode();
    }

    function renderTargetLastError() {
      if (!targetWorkflow.lastError) {
        clearTargetStatusError(els.targetAnalysisStatus);
        clearTargetStatusError(els.targetPatchStatus);
        clearTargetEntryInvalid();
        return;
      }
      if (targetWorkflow.lastError.kind === "analysis") {
        clearTargetStatusError(els.targetPatchStatus);
      } else {
        clearTargetStatusError(els.targetAnalysisStatus);
        clearTargetEntryInvalid();
      }
      applyTargetStatusError(targetWorkflow.lastError.kind, targetWorkflow.lastError.code);
      if (els.targetRejectionEvidence && targetWorkflow.lastError.evidence) {
        els.targetRejectionEvidence.textContent = JSON.stringify(
          targetWorkflow.lastError.evidence,
          null,
          2
        );
      }
    }

    function syncTargetActions() {
      var available = hasTargetBridge();
      if (els.btnOpenTarget) {
        els.btnOpenTarget.disabled = !available;
        els.btnOpenTarget.classList.toggle("hidden", !available);
        els.btnOpenTarget.setAttribute("aria-disabled", available ? "false" : "true");
      }
      if (els.btnSelectTarget) els.btnSelectTarget.disabled = !available;
      var entry = els.targetEntryRelpath ? els.targetEntryRelpath.value.trim() : "";
      if (els.btnAnalyzeTarget) {
        els.btnAnalyzeTarget.disabled = !available || !targetWorkflow.targetPath || !entry;
      }
      var task = els.targetTask ? els.targetTask.value.trim() : "";
      var selectionValid =
        targetWorkflow.capsuleIds.length > 0 &&
        !formalSelectionError(targetWorkflow.capsuleIds, true);
      if (els.btnGenerateTargetPatch) {
        els.btnGenerateTargetPatch.disabled = !(
          available &&
          isSafeTargetProfile(targetWorkflow.profile) &&
          task &&
          task.length <= 500 &&
          selectionValid
        );
      }
      if (els.btnConfirmTargetPatch) {
        els.btnConfirmTargetPatch.disabled =
          !isSafeTargetPatch(targetWorkflow.patch) || !!targetWorkflow.confirmation;
      }
    }

    function renderTargetWorkflow() {
      if (!els.screenTarget) return;
      renderTargetSelection();
      renderTargetCapsules();
      renderTargetProfile();
      renderTargetPatch();
      renderTargetDeveloperMode();
      renderTargetLastError();
      applyTargetStagePresentation();
      syncTargetActions();
    }

    function initTargetIntegration() {
      if (!hasTargetBridge()) {
        syncTargetActions();
        return;
      }
      showScreen("screen-target");
      renderTargetWorkflow();
    }

    function openTargetCompatTools() {
      if (host.openCompatTools) {
        host.openCompatTools();
        return;
      }
      showScreen("screen-main");
      syncAppState();
    }

    function bindTargetEvents() {
      if (els.btnOpenTarget) els.btnOpenTarget.addEventListener("click", initTargetIntegration);
      var targetBack = $("btn-target-back");
      if (targetBack) targetBack.addEventListener("click", showStandaloneProduct);
      if (els.btnSelectTarget) els.btnSelectTarget.addEventListener("click", handleChooseStaticWebTarget);
      if (els.btnAnalyzeTarget) els.btnAnalyzeTarget.addEventListener("click", handleAnalyzeStaticWebTarget);
      if (els.btnGenerateTargetPatch) els.btnGenerateTargetPatch.addEventListener("click", handleGenerateStaticWebPatch);
      if (els.btnConfirmTargetPatch) els.btnConfirmTargetPatch.addEventListener("click", handleConfirmTargetPatch);
      if (els.btnTargetOpenWarehouse) {
        els.btnTargetOpenWarehouse.addEventListener("click", function () {
          if (host.openWarehouse) host.openWarehouse(null);
        });
      }
      if (els.btnTargetOpenIngestion) {
        els.btnTargetOpenIngestion.addEventListener("click", function () {
          if (host.openIngestion) host.openIngestion();
        });
      }
      if (els.btnTargetOpenCompat) {
        els.btnTargetOpenCompat.addEventListener("click", openTargetCompatTools);
      }
      if (els.targetEntryRelpath) {
        els.targetEntryRelpath.addEventListener("input", function () {
          resetTargetProfile();
          renderTargetWorkflow();
        });
      }
      if (els.targetTask) {
        els.targetTask.addEventListener("input", function () {
          resetTargetPatch();
          renderTargetWorkflow();
        });
      }
      if (els.targetDeveloperMode) {
        els.targetDeveloperMode.addEventListener("change", function () {
          targetWorkflow.developerMode = !!els.targetDeveloperMode.checked;
          invalidateTargetConfirmation();
          renderTargetWorkflow();
        });
      }
      var targetLang = $("btn-target-lang");
      if (targetLang) targetLang.addEventListener("click", toggleLocale);
    }

    function cacheElements() {
      els.screenTarget = $("screen-target");
      els.btnOpenTarget = $("btn-open-target");
      els.btnSelectTarget = $("btn-select-target");
      els.btnAnalyzeTarget = $("btn-analyze-target");
      els.targetSelectedName = $("target-selected-name");
      els.targetEntryRelpath = $("target-entry-relpath");
      els.targetAnalysisStatus = $("target-analysis-status");
      els.targetProfileSummary = $("target-profile-summary");
      els.targetProfileDeveloper = $("target-profile-developer");
      els.targetTask = $("target-task");
      els.targetCapsuleCards = $("target-capsule-cards");
      els.btnGenerateTargetPatch = $("btn-generate-target-patch");
      els.targetPatchStatus = $("target-patch-status");
      els.targetRejectionEvidence = $("target-rejection-evidence");
      els.targetReview = $("target-review");
      els.targetReviewBadge = $("target-review-badge");
      els.targetEvidenceSummary = $("target-evidence-summary");
      els.targetFileDiffs = $("target-file-diffs");
      els.targetPatchDeveloper = $("target-patch-developer");
      els.targetDeveloperMode = $("target-developer-mode");
      els.btnConfirmTargetPatch = $("btn-confirm-target-patch");
      els.targetConfirmationReceipt = $("target-confirmation-receipt");
      els.targetPanelSelect = document.querySelector('#screen-target [data-target-panel="select"]');
      els.targetPanelCompose = document.querySelector('#screen-target [data-target-panel="compose"]');
      els.targetPanelConfirmed = document.querySelector('#screen-target [data-target-panel="confirmed"]');
      els.targetSummarySelect = document.querySelector('#screen-target [data-target-summary="select"]');
      els.targetSummaryCompose = document.querySelector('#screen-target [data-target-summary="compose"]');
      els.targetSelectSummaryTitle = $("target-select-summary-title");
      els.targetSelectSummaryCopy = $("target-select-summary-copy");
      els.targetComposeSummaryTitle = $("target-compose-summary-title");
      els.targetComposeSummaryCopy = $("target-compose-summary-copy");
      els.btnTargetOpenWarehouse = $("btn-target-open-warehouse");
      els.btnTargetOpenIngestion = $("btn-target-open-ingestion");
      els.btnTargetOpenCompat = $("btn-target-open-compat");
    }

    function bind() {
      cacheElements();
      if (eventsBound) return;
      eventsBound = true;
      bindTargetEvents();
    }

    function sync() {
      cacheElements();
      var targetLang = $("btn-target-lang");
      if (targetLang) {
        targetLang.textContent = host.getLocale() === "zh" ? "中·EN" : "EN·中";
      }
      renderTargetWorkflow();
    }

    function getState() {
      return {
        available: hasTargetBridge(),
        profileReady: isSafeTargetProfile(targetWorkflow.profile),
        patchReady: isSafeTargetPatch(targetWorkflow.patch),
        planId: targetWorkflow.patch ? targetWorkflow.patch.plan_id : null,
        confirmed: !!targetWorkflow.confirmation,
        stage: deriveTargetStage(),
        developerMode: !!targetWorkflow.developerMode,
      };
    }

    function handleChooseStaticWebTarget() {
      if (!hasTargetBridge()) return;
      bridgeCall("choose_static_web_target").then(function (raw) {
        var result = parseBridgeJson(raw);
        if (result && result.cancelled) return;
        if (
          !result ||
          result.ok !== true ||
          typeof result.target_path !== "string" ||
          !result.target_path ||
          typeof result.display_name !== "string" ||
          !result.display_name.trim() ||
          result.display_name.length > 120 ||
          /[\\/\x00-\x1f\x7f]/.test(result.display_name)
        ) {
          resetTargetProfile();
          renderTargetError("analysis", result);
          renderTargetWorkflow();
          return;
        }
        targetWorkflow.targetPath = result.target_path;
        targetWorkflow.displayName = result.display_name.trim();
        resetTargetProfile();
        renderTargetWorkflow();
      });
    }

    function handleAnalyzeStaticWebTarget() {
      var entry = els.targetEntryRelpath ? els.targetEntryRelpath.value.trim() : "";
      if (!hasTargetBridge() || !targetWorkflow.targetPath || !entry) {
        if (els.targetAnalysisStatus) els.targetAnalysisStatus.textContent = t("targetEntryRequired");
        return;
      }
      resetTargetProfile();
      var requestRevision = targetWorkflow.profileRevision;
      if (els.targetAnalysisStatus) els.targetAnalysisStatus.textContent = t("targetAnalyzing");
      clearTargetStatusError(els.targetAnalysisStatus);
      applyTargetStagePresentation();
      var payload = {
        target_path: targetWorkflow.targetPath,
        entry_relpath: entry,
      };
      bridgeCall("analyze_static_web_target", JSON.stringify(payload)).then(function (raw) {
        if (requestRevision !== targetWorkflow.profileRevision) return;
        var result = parseBridgeJson(raw);
        if (!result || result.ok !== true || !isSafeTargetProfile(result.data)) {
          renderTargetError(
            "analysis",
            result && result.ok === true
              ? { ok: false, error: { code: "frontend_contract_rejected", evidence: { status: "rejected", code: "frontend_contract_rejected" } } }
              : result
          );
          renderTargetWorkflow();
          return;
        }
        targetWorkflow.profile = result.data;
        targetWorkflow.lastError = null;
        renderTargetWorkflow();
      });
    }

    function handleGenerateStaticWebPatch() {
      var entry = els.targetEntryRelpath ? els.targetEntryRelpath.value.trim() : "";
      var task = els.targetTask ? els.targetTask.value.trim() : "";
      if (!task) {
        if (els.targetPatchStatus) els.targetPatchStatus.textContent = t("targetTaskRequired");
        return;
      }
      if (
        !hasTargetBridge() ||
        !isSafeTargetProfile(targetWorkflow.profile) ||
        !targetWorkflow.capsuleIds.length ||
        formalSelectionError(targetWorkflow.capsuleIds, true)
      ) {
        if (els.targetPatchStatus) els.targetPatchStatus.textContent = t("targetCapsuleRequired");
        return;
      }
      resetTargetPatch();
      var requestRevision = targetWorkflow.patchRevision;
      if (els.targetPatchStatus) els.targetPatchStatus.textContent = t("targetPatchGenerating");
      clearTargetStatusError(els.targetPatchStatus);
      applyTargetStagePresentation();
      syncTargetActions();
      var payload = {
        target_path: targetWorkflow.targetPath,
        entry_relpath: entry,
        task: task,
        capsule_ids: targetWorkflow.capsuleIds.slice(),
        selection_mode: "manual",
        authorization: {
          mode: "review_patch_only",
          target_snapshot_sha256: targetWorkflow.profile.snapshot_sha256,
        },
      };
      bridgeCall("generate_static_web_patch", JSON.stringify(payload)).then(function (raw) {
        if (requestRevision !== targetWorkflow.patchRevision) return;
        var result = parseBridgeJson(raw);
        if (!result || result.ok !== true || !isSafeTargetPatch(result.data)) {
          renderTargetError(
            "patch",
            result && result.ok === true
              ? { ok: false, error: { code: "frontend_contract_rejected", evidence: { status: "rejected", code: "frontend_contract_rejected" } } }
              : result
          );
          renderTargetWorkflow();
          return;
        }
        targetWorkflow.patch = result.data;
        targetWorkflow.lastError = null;
        renderTargetWorkflow();
      });
    }

    function handleConfirmTargetPatch() {
      if (!isSafeTargetPatch(targetWorkflow.patch)) return;
      targetWorkflow.confirmation = {
        planId: targetWorkflow.patch.plan_id,
        snapshotSha256: targetWorkflow.profile.snapshot_sha256,
      };
      renderTargetWorkflow();
    }

    function showStandaloneProduct() {
      if (host.openProduct) {
        host.openProduct();
      } else {
        showScreen("screen-main");
        syncAppState();
      }
    }

    return {
      bind: bind,
      sync: sync,
      getState: getState,
    };
  }

  window.ReweaveTargetWorkflow = {
    create: create,
  };
})();
