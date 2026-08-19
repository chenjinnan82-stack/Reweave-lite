(function () {
  "use strict";

  function create(host) {
    var state = {
      active: false,
      view: "overview",
      projectKey: "",
      capsuleId: "",
      query: "",
      codeScale: 1,
      developerMode: false,
      entryFocusId: "",
      pendingFocusKey: "",
      overviewSnapshot: null,
      projectSnapshot: null,
      searchSnapshot: null,
      planContext: null,
      contextStatus: "",
      contextResolved: false,
      contextComplete: false,
      pendingScrollTop: null,
      singleSourceAutoExpanded: false,
      singleSourceUserCollapsed: false,
    };
    var details = {};
    var coreCodeCache = {};
    var requestRevision = 0;
    var coreCodeRequestRevision = 0;
    var bound = false;
    var els = {};

    function $(id) {
      return document.getElementById(id);
    }

    function text(key) {
      return host.t ? host.t(key) : key;
    }

    function formatText(key, values) {
      return Object.keys(values || {}).reduce(function (result, name) {
        return result.replace(new RegExp("\\{" + name + "\\}", "g"), String(values[name]));
      }, text(key));
    }

    function capsuleId(cap) {
      return String((cap && (cap.capsule_id || cap.id)) || "");
    }

    function formalCapsules() {
      var capsules = host.getCapsules ? host.getCapsules() : [];
      return (Array.isArray(capsules) ? capsules : []).filter(function (cap) {
        return cap && cap.formal_version === true && String(cap.status || "active") === "active";
      });
    }

    function projectLabels() {
      var result = {};
      var projects = host.getProjects ? host.getProjects() : [];
      (Array.isArray(projects) ? projects : []).forEach(function (project) {
        var id = String((project && project.project_id) || "");
        if (!id) return;
        var displayName = String(project.display_name || "");
        result[id] = displayName && !looksAbsolutePath(displayName) ? displayName : "";
      });
      return result;
    }

    function sourceLabel(cap) {
      var label = host.capsuleReader && host.capsuleReader.sourceLabel
        ? String(host.capsuleReader.sourceLabel(cap) || "")
        : String((cap && cap.source) || "");
      return looksAbsolutePath(label) ? "" : label;
    }

    function looksAbsolutePath(value) {
      var textValue = String(value || "").trim();
      return (
        /^\//.test(textValue) ||
        /^[a-zA-Z]:[\\/]/.test(textValue) ||
        /^\\\\/.test(textValue) ||
        /file:\/\//i.test(textValue) ||
        /^~[\\/]/.test(textValue) ||
        /(^|[\s"'(=:])\/(Users|home|private|tmp|var|Volumes)\//.test(textValue) ||
        /(^|[\s"'(=:])[a-zA-Z]:[\\/]/.test(textValue)
      );
    }

    function safeRelativePath(value) {
      var path = String(value || "").trim();
      if (!path || looksAbsolutePath(path)) return "";
      if (path.split(/[\\/]/).some(function (part) { return part === ".."; })) return "";
      return path;
    }

    function safeJavascriptPath(value) {
      if (typeof value !== "string" || value !== value.trim()) return "";
      if (!value || /[\u0000-\u001f\u007f]/.test(value) || value.indexOf("\\") >= 0) return "";
      if (looksAbsolutePath(value)) return "";
      if (value.split("/").some(function (part) { return !part || part === "." || part === ".."; })) return "";
      return /\.(?:js|mjs)$/i.test(value) ? value : "";
    }

    function hasExactKeys(value, expected) {
      if (!value || typeof value !== "object" || Array.isArray(value)) return false;
      return Object.keys(value).sort().join("\n") === expected.slice().sort().join("\n");
    }

    function safeValue(value, depth) {
      if (depth > 5) return "[nested value omitted]";
      if (typeof value === "string") {
        return looksAbsolutePath(value) ? "[absolute path redacted]" : value;
      }
      if (typeof value === "number" || typeof value === "boolean" || value === null) return value;
      if (Array.isArray(value)) {
        return value.slice(0, 40).map(function (item) { return safeValue(item, depth + 1); });
      }
      if (!value || typeof value !== "object") return null;
      var result = {};
      Object.keys(value).sort().forEach(function (key) {
        if (/^(after_content|html_text|css_text|javascript_modules_json|raw|current_path)$/i.test(key)) return;
        result[key] = safeValue(value[key], depth + 1);
      });
      return result;
    }

    function projectDetail(cap, raw) {
      raw = raw && typeof raw === "object" ? raw : {};
      var versions = Array.isArray(raw.versions) ? raw.versions : [];
      var versionId = String(cap.version_id || "");
      var selectedVersion = versionId ? versions.find(function (version) {
        return String(version.version_id || "") === versionId;
      }) : null;
      if (!selectedVersion) {
        return { exact_version: false, sources: [], version: {}, status_events: [] };
      }
      var sources = (Array.isArray(raw.sources) ? raw.sources : []).filter(function (source) {
        return String(source.version_id || "") === versionId;
      }).map(function (source) {
        return {
          version_id: String(source.version_id || ""),
          project_id: String(source.project_id || ""),
          source_identity: String(source.source_identity || ""),
          source_kind: String(source.source_kind || ""),
          source_relpath: safeRelativePath(source.source_relpath),
          relationship: String(source.relationship || ""),
        };
      });
      var version = {
        version_id: String(selectedVersion.version_id || ""),
        canonical_hash: /^[0-9a-f]{64}$/.test(String(selectedVersion.canonical_hash || ""))
          ? String(selectedVersion.canonical_hash)
          : "",
        version_number: selectedVersion.version_number == null ? null : Number(selectedVersion.version_number),
        extraction_contract_version: String(selectedVersion.extraction_contract_version || ""),
        activation: safeValue(selectedVersion.activation_json || null, 0),
        input_contract: safeValue(selectedVersion.input_contract_json || null, 0),
        output_contract: safeValue(selectedVersion.output_contract_json || null, 0),
        error_contract: safeValue(selectedVersion.error_contract_json || null, 0),
        runtime_allowlist: safeValue(selectedVersion.runtime_allowlist_json || null, 0),
        dom_scope: safeValue(selectedVersion.dom_scope_json || null, 0),
        usage_scope: safeValue(selectedVersion.usage_scope_json || null, 0),
        validation_contract_version: String(selectedVersion.validation_contract_version || ""),
        validation: safeValue(selectedVersion.validation_result_json || null, 0),
        supervision: safeValue(selectedVersion.supervision_result_json || null, 0),
      };
      var events = (Array.isArray(raw.status_events) ? raw.status_events : []).filter(function (event) {
        return String(event.version_id || "") === versionId;
      }).slice(0, 20).map(function (event) {
        return {
          event_type: String(event.event_type || ""),
          from_status: String(event.from_status || ""),
          to_status: String(event.to_status || ""),
          version_id: String(event.version_id || ""),
          reason_code: String(event.reason_code || ""),
          created_at: String(event.created_at || ""),
        };
      });
      return { exact_version: true, sources: sources, version: version, status_events: events };
    }

    function exactProjectSources(cap) {
      var cached = details[capsuleId(cap)];
      if (
        !cached ||
        cached.versionId !== String(cap.version_id || "") ||
        !cached.value ||
        cached.value.exact_version !== true
      ) return [];
      return cached.value.sources.filter(function (source) {
        return (
          source.source_kind === "project" &&
          !!source.project_id &&
          source.source_identity === "project:" + source.project_id
        );
      });
    }

    function addCapsuleToGroup(map, key, label, evidenceStatus, projectId, cap, reasonKey) {
      if (!map[key]) {
        map[key] = {
          key: key,
          projectId: evidenceStatus === "formal_exact_version_source" ? String(projectId || "") : "",
          label: label,
          evidenceStatus: evidenceStatus,
          reasonKey: reasonKey || "",
          capsules: [],
        };
      }
      if (!map[key].capsules.some(function (item) { return capsuleId(item) === capsuleId(cap); })) {
        map[key].capsules.push(cap);
      }
    }

    function sourceGroups() {
      var labels = projectLabels();
      var map = {};
      formalCapsules().forEach(function (cap) {
        var sources = exactProjectSources(cap);
        if (sources.length === 1) {
          var source = sources[0];
          var key = "project:" + source.project_id;
          addCapsuleToGroup(
            map,
            key,
            labels[source.project_id] || text("sourceProject"),
            "formal_exact_version_source",
            source.project_id,
            cap,
            ""
          );
          return;
        }
        var sourceId = String(cap.source_id || "");
        var label = sourceLabel(cap);
        var reasonKey = sources.length > 1
          ? "multipleExactSources"
          : sourceId || label
            ? "missingExactSource"
            : "missingFormalSource";
        addCapsuleToGroup(
          map,
          "unresolved:" + capsuleId(cap),
          labels[sourceId] || label || text("sourceProject"),
          "source_evidence_insufficient",
          "",
          cap,
          reasonKey
        );
      });
      var groups = Object.keys(map).map(function (key) {
        map[key].capsules.sort(function (left, right) {
          return String(left.name || capsuleId(left)).localeCompare(String(right.name || capsuleId(right)));
        });
        return map[key];
      }).sort(function (left, right) {
        return left.label.localeCompare(right.label) || left.key.localeCompare(right.key);
      });
      var counts = {};
      groups.forEach(function (group) { counts[group.label] = (counts[group.label] || 0) + 1; });
      groups.forEach(function (group) {
        group.fingerprint = ("000000" + stableHash(group.key).toString(16)).slice(-6);
        group.displayLabel = group.label + (counts[group.label] > 1 ? " · " + group.fingerprint : "");
      });
      return groups;
    }

    function stableHash(value) {
      var hash = 2166136261;
      var input = String(value || "");
      for (var i = 0; i < input.length; i += 1) {
        hash ^= input.charCodeAt(i);
        hash = Math.imul(hash, 16777619);
      }
      return hash >>> 0;
    }

    function currentGroup(groups) {
      return groups.find(function (group) { return group.key === state.projectKey; }) || null;
    }

    function viewSnapshot() {
      return {
        view: state.view,
        projectKey: state.projectKey,
        capsuleId: state.capsuleId,
        focusKey: activeNodeKey(),
        scrollTop: els.canvas ? els.canvas.scrollTop : 0,
      };
    }

    function restoreSnapshot(snapshot) {
      if (!snapshot) return;
      state.view = snapshot.view;
      state.projectKey = snapshot.projectKey;
      state.capsuleId = snapshot.capsuleId;
      state.pendingFocusKey = snapshot.focusKey || "";
      state.pendingScrollTop = Number(snapshot.scrollTop || 0);
    }

    function activeNodeKey() {
      var active = document.activeElement;
      return active && active.dataset ? String(active.dataset.nodeKey || "") : "";
    }

    function detailsLoading() {
      return Object.keys(details).some(function (key) { return details[key].loading === true; });
    }

    function clamp(value, minimum, maximum) {
      return Math.min(maximum, Math.max(minimum, value));
    }

    function queryText() {
      return state.query.trim().toLocaleLowerCase();
    }

    function capsuleMatches(cap, query) {
      if (!query) return false;
      return (
        String(cap.name || "").toLocaleLowerCase().indexOf(query) >= 0 ||
        capsuleId(cap).toLocaleLowerCase().indexOf(query) >= 0
      );
    }

    function groupMatches(group, query) {
      if (!query) return false;
      return (
        group.displayLabel.toLocaleLowerCase().indexOf(query) >= 0 ||
        group.capsules.some(function (cap) { return capsuleMatches(cap, query); })
      );
    }

    function hasFormalSourceFact(group, cap) {
      if (!group || group.evidenceStatus !== "formal_exact_version_source") return false;
      var sources = exactProjectSources(cap);
      return sources.length === 1 &&
        group.projectId === sources[0].project_id &&
        group.key === "project:" + sources[0].project_id;
    }

    function sourcePathFor(group, cap) {
      if (!hasFormalSourceFact(group, cap)) return "";
      var sources = exactProjectSources(cap);
      return sources.length === 1 ? safeRelativePath(sources[0].source_relpath) : "";
    }

    function coreCodeIdentity(group, cap) {
      if (!hasFormalSourceFact(group, cap)) return null;
      var identity = {
        capsuleId: capsuleId(cap),
        versionId: String(cap.version_id || ""),
        projectId: String(group.projectId || ""),
      };
      if (!identity.capsuleId || !identity.versionId || !identity.projectId) return null;
      identity.key = JSON.stringify([identity.capsuleId, identity.versionId, identity.projectId]);
      return identity;
    }

    function exactEntryModule(cap) {
      var cached = details[capsuleId(cap)];
      var version = cached && cached.value && cached.value.exact_version === true
        ? cached.value.version
        : null;
      var activation = version && version.activation;
      return safeJavascriptPath(activation && activation.entry_module);
    }

    function capsuleCanonicalHash(cap) {
      var cached = details[capsuleId(cap)];
      var fromDetail = cached && cached.value && cached.value.version
        ? String(cached.value.version.canonical_hash || "")
        : "";
      return fromDetail || String(cap.canonical_hash || "");
    }

    function capsuleValidationPassed(cap) {
      var cached = details[capsuleId(cap)];
      var validation = cached && cached.value && cached.value.exact_version === true
        ? cached.value.version.validation
        : null;
      return !!(validation && validation.status === "passed");
    }

    function validateCoreCodeProjection(raw, group, cap) {
      var identity = coreCodeIdentity(group, cap);
      var digest = /^[0-9a-f]{64}$/;
      if (
        !identity ||
        !hasExactKeys(raw, [
          "schema_version", "capsule_id", "version_id", "project_id",
          "source_identity", "canonical_hash", "capability_kind", "validation", "core_code",
        ]) ||
        raw.schema_version !== "capsule_core_code_projection.v1" ||
        raw.capsule_id !== identity.capsuleId ||
        raw.version_id !== identity.versionId ||
        raw.project_id !== identity.projectId ||
        raw.source_identity !== "project:" + identity.projectId ||
        typeof raw.canonical_hash !== "string" ||
        !digest.test(raw.canonical_hash) ||
        raw.canonical_hash !== capsuleCanonicalHash(cap) ||
        ["presentation", "interaction", "computation"].indexOf(raw.capability_kind) < 0 ||
        raw.capability_kind !== String(cap.type || "")
      ) return null;
      if (
        !hasExactKeys(raw.validation, [
          "contract_version", "schema_version", "status", "acceptance_scope",
        ]) ||
        [
          raw.validation.contract_version,
          raw.validation.schema_version,
          raw.validation.acceptance_scope,
        ].some(function (value) { return typeof value !== "string" || !value; }) ||
        raw.validation.status !== "passed"
      ) return null;
      if (
        !hasExactKeys(raw.core_code, ["kind", "logical_path", "language", "content", "sha256"]) ||
        raw.core_code.kind !== "javascript_entry_module" ||
        raw.core_code.language !== "javascript" ||
        typeof raw.core_code.content !== "string" ||
        !raw.core_code.content ||
        typeof raw.core_code.sha256 !== "string" ||
        !digest.test(raw.core_code.sha256) ||
        !safeJavascriptPath(raw.core_code.logical_path) ||
        safeJavascriptPath(raw.core_code.logical_path) !== exactEntryModule(cap)
      ) return null;
      return {
        schema_version: raw.schema_version,
        capsule_id: raw.capsule_id,
        version_id: raw.version_id,
        project_id: raw.project_id,
        source_identity: raw.source_identity,
        canonical_hash: raw.canonical_hash,
        capability_kind: raw.capability_kind,
        validation: {
          contract_version: raw.validation.contract_version,
          schema_version: raw.validation.schema_version,
          status: raw.validation.status,
          acceptance_scope: raw.validation.acceptance_scope,
        },
        core_code: {
          kind: raw.core_code.kind,
          logical_path: raw.core_code.logical_path,
          language: raw.core_code.language,
          content: raw.core_code.content,
          sha256: raw.core_code.sha256,
        },
      };
    }

    function currentCoreCodeProjection(group, cap) {
      var identity = coreCodeIdentity(group, cap);
      var cached = identity ? coreCodeCache[identity.key] : null;
      return cached && cached.status === "ready" &&
        cached.requestRevision === coreCodeRequestRevision ? cached.value : null;
    }

    function invalidatePendingCoreCodeRequests() {
      coreCodeRequestRevision += 1;
      Object.keys(coreCodeCache).forEach(function (key) {
        if (coreCodeCache[key].status === "loading") delete coreCodeCache[key];
      });
    }

    function invalidateCoreCodeForCapsule(id) {
      invalidatePendingCoreCodeRequests();
      Object.keys(coreCodeCache).forEach(function (key) {
        if (coreCodeCache[key].capsuleId === id) delete coreCodeCache[key];
      });
    }

    function ensureCoreCodeProjection(group, cap) {
      var identity = coreCodeIdentity(group, cap);
      if (!identity || !host.readCapsuleCoreCode) return;
      if (
        coreCodeCache[identity.key] &&
        coreCodeCache[identity.key].requestRevision === coreCodeRequestRevision
      ) return;
      delete coreCodeCache[identity.key];
      var revision = ++coreCodeRequestRevision;
      coreCodeCache[identity.key] = {
        capsuleId: identity.capsuleId,
        status: "loading",
        requestRevision: revision,
        value: null,
      };
      Promise.resolve(host.readCapsuleCoreCode(
        identity.capsuleId, identity.versionId, identity.projectId
      )).then(function (raw) {
        var cached = coreCodeCache[identity.key];
        var groups = sourceGroups();
        var currentGroupValue = currentGroup(groups);
        var currentCap = selectedCapsule(currentGroupValue);
        var currentIdentity = currentCap ? coreCodeIdentity(currentGroupValue, currentCap) : null;
        if (
          !cached || cached.requestRevision !== revision || revision !== coreCodeRequestRevision ||
          !state.active || state.view !== "code" || !currentIdentity || currentIdentity.key !== identity.key
        ) {
          if (cached && cached.requestRevision === revision) delete coreCodeCache[identity.key];
          return;
        }
        var projection = validateCoreCodeProjection(raw, currentGroupValue, currentCap);
        coreCodeCache[identity.key] = {
          capsuleId: identity.capsuleId,
          status: projection ? "ready" : "failed",
          requestRevision: revision,
          value: projection,
        };
        render();
      }).catch(function () {
        var cached = coreCodeCache[identity.key];
        if (!cached || cached.requestRevision !== revision || revision !== coreCodeRequestRevision) return;
        coreCodeCache[identity.key] = {
          capsuleId: identity.capsuleId,
          status: "failed",
          requestRevision: revision,
          value: null,
        };
        render();
      });
    }

    function capabilityName(kind) {
      return text({
        presentation: "presentationCapability",
        interaction: "interactionCapability",
        computation: "computationCapability",
      }[kind] || kind);
    }

    function capabilityCounts(group) {
      var counts = { presentation: 0, interaction: 0, computation: 0 };
      group.capsules.forEach(function (cap) {
        var kind = String(cap.type || "");
        if (Object.prototype.hasOwnProperty.call(counts, kind)) counts[kind] += 1;
      });
      return counts;
    }

    function capabilityMark(kind) {
      var mark = document.createElement("i");
      mark.className = "warehouse-capsule-core is-" + kind;
      mark.setAttribute("aria-hidden", "true");
      return mark;
    }

    function domToken(value) {
      return String(value || "").replace(/[^a-zA-Z0-9_-]/g, "_");
    }

    function detailVersion(cap) {
      var cached = details[capsuleId(cap)];
      return cached && cached.value && cached.value.exact_version === true
        ? cached.value.version || {}
        : null;
    }

    function shortVersionId(value) {
      var versionId = String(value || "");
      return versionId.length > 15 ? versionId.slice(0, 12) + "…" : versionId;
    }

    function readableVersion(cap) {
      var version = detailVersion(cap);
      var versionNumber = version && Number.isFinite(Number(version.version_number))
        ? "v" + String(Number(version.version_number))
        : "";
      var versionId = shortVersionId(cap.version_id);
      return [versionNumber, versionId].filter(Boolean).join(" · ");
    }

    function contractFields(contract) {
      if (!contract || typeof contract !== "object" || Array.isArray(contract)) return [];
      var properties = contract.properties;
      if (!properties || typeof properties !== "object" || Array.isArray(properties)) return [];
      return Object.keys(properties).sort();
    }

    function contractEventNames(contract) {
      if (!contract || typeof contract !== "object" || Array.isArray(contract)) return [];
      var events = contract.events;
      if (!events || typeof events !== "object" || Array.isArray(events)) return [];
      return Object.keys(events).sort().map(function (name) {
        var fields = contractFields(events[name]);
        return name + "(" + fields.join(", ") + ")";
      });
    }

    function contractRows(cap) {
      var version = detailVersion(cap);
      if (!version) {
        return [{
          label: text("contractStatus"),
          value: details[capsuleId(cap)] && details[capsuleId(cap)].loading
            ? text("warehouseLoadingRelations")
            : text("contractUnavailable"),
        }];
      }
      var activation = version.activation && typeof version.activation === "object"
        ? version.activation
        : {};
      var rows = [{
        label: text("contractEntrypoint"),
        value: String(activation.entrypoint || "—"),
      }];
      var kind = String(cap.type || "");
      if (kind === "interaction") {
        var events = contractEventNames(version.output_contract);
        rows.push({
          label: text("contractProduces"),
          value: events.length ? events.join(" · ") : text("contractNoOutput"),
        });
      } else {
        var inputs = contractFields(version.input_contract);
        var outputs = contractFields(version.output_contract);
        rows.push({
          label: text("contractReceives"),
          value: inputs.length ? inputs.join(", ") : text("contractNoInput"),
        });
        rows.push({
          label: text("contractProduces"),
          value: outputs.length ? outputs.join(", ") : text("contractNoOutput"),
        });
      }
      return rows;
    }

    function createSourceKnot() {
      var namespace = "http://www.w3.org/2000/svg";
      var knot = document.createElementNS(namespace, "svg");
      knot.setAttribute("viewBox", "0 0 28 28");
      knot.setAttribute("aria-hidden", "true");
      knot.setAttribute("focusable", "false");
      knot.setAttribute("class", "warehouse-source-knot");
      [
        "M3 7C8 7 11 10 16 10C20 10 22 8 25 8",
        "M4 13C9 13 11 16 16 16C20 16 22 13 25 13",
        "M3 20C8 19 12 21 17 21C20 21 22 19 24 18",
        "M8 3C9 9 13 13 18 17C20 19 21 23 21 25",
        "M4 24C9 20 11 17 13 13C15 9 18 6 24 4",
      ].forEach(function (shape) {
        var path = document.createElementNS(namespace, "path");
        path.setAttribute("d", shape);
        knot.appendChild(path);
      });
      return knot;
    }

    function sourceReason(group) {
      return group && group.reasonKey ? text(group.reasonKey) : text("sourceFactInsufficient");
    }

    function createSourceToggle(group, options) {
      var counts = capabilityCounts(group);
      var button = document.createElement("button");
      button.type = "button";
      button.className = "warehouse-node warehouse-source-toggle";
      if (options.matched) button.classList.add("is-match");
      if (options.dimmed) button.classList.add("is-dimmed");
      if (options.open) button.classList.add("is-open");
      button.dataset.nodeKind = "project";
      button.dataset.nodeKey = "project:" + group.key;
      button.dataset.projectKey = group.key;
      button.dataset.sourceFingerprint = group.fingerprint;
      button.setAttribute("aria-expanded", options.open ? "true" : "false");
      button.setAttribute("aria-controls", "warehouse-source-body-" + domToken(group.key));
      button.setAttribute("aria-label", [
        group.displayLabel,
        formatText("formalCapsuleCount", { count: group.capsules.length }),
        capabilityName("presentation") + " " + counts.presentation,
        capabilityName("interaction") + " " + counts.interaction,
        capabilityName("computation") + " " + counts.computation,
      ].join(" · "));

      button.appendChild(createSourceKnot());
      var identity = document.createElement("span");
      identity.className = "warehouse-source-identity";
      var label = document.createElement("strong");
      label.className = "warehouse-node-label";
      label.textContent = group.displayLabel;
      identity.appendChild(label);
      var proof = document.createElement("span");
      proof.className = "warehouse-source-proof";
      proof.textContent = text("sourceVerifiedShort");
      identity.appendChild(proof);
      button.appendChild(identity);
      var total = document.createElement("span");
      total.className = "warehouse-source-total";
      total.textContent = formatText("formalCapsuleCount", { count: group.capsules.length });
      button.appendChild(total);
      var composition = document.createElement("span");
      composition.className = "warehouse-source-composition";
      ["presentation", "interaction", "computation"].forEach(function (kind) {
        var item = document.createElement("span");
        item.dataset.capabilityKind = kind;
        var kindLabel = document.createElement("em");
        kindLabel.textContent = capabilityName(kind);
        item.appendChild(kindLabel);
        var value = document.createElement("b");
        value.textContent = String(counts[kind]);
        item.appendChild(value);
        composition.appendChild(item);
      });
      button.appendChild(composition);
      var disclosure = document.createElement("span");
      disclosure.className = "warehouse-source-disclosure";
      disclosure.setAttribute("aria-hidden", "true");
      button.appendChild(disclosure);
      button.addEventListener("click", options.activate);
      return button;
    }

    function appendContractRow(list, row) {
      var term = document.createElement("dt");
      term.textContent = row.label;
      var description = document.createElement("dd");
      description.textContent = row.value || "—";
      list.appendChild(term);
      list.appendChild(description);
    }

    function createCapsuleContract(cap, panelId, open) {
      var panel = document.createElement("section");
      panel.id = panelId;
      panel.className = "warehouse-capsule-contract";
      panel.hidden = !open;
      panel.setAttribute("aria-label", text("formalContract"));
      if (!open) return panel;
      var list = document.createElement("dl");
      contractRows(cap).forEach(function (row) { appendContractRow(list, row); });
      panel.appendChild(list);
      var version = detailVersion(cap);
      var identity = document.createElement("p");
      identity.className = "warehouse-contract-identity";
      var versionId = document.createElement("code");
      versionId.textContent = String(cap.version_id || "—");
      identity.appendChild(versionId);
      var hash = document.createElement("code");
      hash.textContent = version && version.canonical_hash
        ? String(version.canonical_hash)
        : text("evidenceUnavailable");
      identity.appendChild(hash);
      panel.appendChild(identity);
      return panel;
    }

    function createCapsuleUnit(group, cap, options) {
      var kind = String(cap.type || "unknown");
      var labelText = String(cap.name || capsuleId(cap));
      var open = state.projectKey === group.key && state.capsuleId === capsuleId(cap);
      var panelId = "warehouse-contract-" + domToken(group.key + "-" + capsuleId(cap));
      var unit = document.createElement("article");
      unit.className = "warehouse-capsule-unit";
      if (open) unit.classList.add("is-open");
      if (options.matched) unit.classList.add("is-match");
      if (options.dimmed) unit.classList.add("is-dimmed");
      if (options.context) unit.classList.add("is-context");
      if (options.evidenceKind === "error") unit.classList.add("is-error");
      unit.dataset.capabilityKind = kind;
      unit.dataset.evidenceThread = options.evidenceKind;

      var button = document.createElement("button");
      button.type = "button";
      button.className = "warehouse-node warehouse-capsule-seal";
      button.dataset.nodeKind = "capsule";
      button.dataset.capabilityKind = kind;
      button.dataset.nodeKey = "capsule:" + capsuleId(cap);
      button.dataset.capsuleId = capsuleId(cap);
      button.setAttribute("aria-expanded", open ? "true" : "false");
      button.setAttribute("aria-controls", panelId);
      button.setAttribute("aria-label", [
        capabilityName(kind),
        labelText,
        readableVersion(cap),
        String(cap.status || "active"),
        capsuleValidationPassed(cap) ? text("validationPassedShort") : text("validationIncompleteShort"),
      ].filter(Boolean).join(" · "));

      var kindSide = document.createElement("span");
      kindSide.className = "warehouse-capsule-kind";
      kindSide.appendChild(capabilityMark(kind));
      var kindLabel = document.createElement("span");
      kindLabel.textContent = capabilityName(kind);
      kindSide.appendChild(kindLabel);
      button.appendChild(kindSide);

      var identity = document.createElement("span");
      identity.className = "warehouse-capsule-identity";
      var name = document.createElement("strong");
      name.textContent = labelText;
      identity.appendChild(name);
      var meta = document.createElement("p");
      var version = document.createElement("span");
      version.textContent = readableVersion(cap) || text("exactVersion");
      version.title = String(cap.version_id || "");
      var status = document.createElement("span");
      status.textContent = String(cap.status || "active");
      var validation = document.createElement("span");
      validation.className = capsuleValidationPassed(cap) ? "is-valid" : "is-invalid";
      validation.textContent = capsuleValidationPassed(cap)
        ? text("validationPassedShort")
        : text("validationIncompleteShort");
      meta.appendChild(version);
      meta.appendChild(status);
      meta.appendChild(validation);
      identity.appendChild(meta);
      button.appendChild(identity);
      button.addEventListener("click", function () { toggleCapsule(group, cap); });
      unit.appendChild(button);
      unit.appendChild(createCapsuleContract(cap, panelId, open));

      var sourceSlot = document.createElement("div");
      sourceSlot.className = "warehouse-source-slot";
      sourceSlot.dataset.evidenceThread = options.evidenceKind;
      var point = document.createElement("span");
      point.className = "warehouse-weave-point";
      point.setAttribute("aria-hidden", "true");
      sourceSlot.appendChild(point);
      var sourcePath = sourcePathFor(group, cap);
      if (sourcePath) {
        var pathButton = document.createElement("button");
        pathButton.type = "button";
        pathButton.className = "warehouse-source-path";
        pathButton.dataset.nodeKey = "path:" + capsuleId(cap);
        pathButton.textContent = sourcePath;
        pathButton.title = sourcePath;
        pathButton.setAttribute("aria-label", formatText("viewVerifiedCodePath", { path: sourcePath }));
        pathButton.addEventListener("click", function () { openCode(group, cap, pathButton); });
        sourceSlot.appendChild(pathButton);
      } else {
        var reason = document.createElement("span");
        reason.className = "warehouse-source-reason";
        reason.textContent = sourceReason(group);
        sourceSlot.appendChild(reason);
      }
      unit.appendChild(sourceSlot);
      return unit;
    }

    function createCapsuleRack(group, query, matchCount) {
      var rack = document.createElement("div");
      rack.id = "warehouse-source-body-" + domToken(group.key);
      rack.className = "warehouse-capsule-rack-grid";
      ["presentation", "interaction", "computation"].forEach(function (kind) {
        var lane = document.createElement("section");
        lane.className = "warehouse-capability-lane";
        lane.dataset.capabilityKind = kind;
        var heading = document.createElement("h3");
        heading.appendChild(capabilityMark(kind));
        var headingText = document.createElement("span");
        headingText.textContent = capabilityName(kind);
        heading.appendChild(headingText);
        lane.appendChild(heading);
        var laneCapsules = group.capsules.filter(function (cap) {
          return String(cap.type || "") === kind;
        });
        if (!laneCapsules.length) {
          var empty = document.createElement("p");
          empty.className = "warehouse-lane-empty";
          empty.textContent = formatText("emptyCapabilityLane", { kind: capabilityName(kind) });
          lane.appendChild(empty);
        }
        laneCapsules.forEach(function (cap) {
          var matched = capsuleMatches(cap, query);
          var evidenceKind = !hasFormalSourceFact(group, cap) || !capsuleValidationPassed(cap)
            ? "error"
            : contextMatchesCap(group, cap)
              ? "formal"
              : "verified";
          lane.appendChild(createCapsuleUnit(group, cap, {
            matched: matched,
            dimmed: !!query && matchCount > 0 && !matched &&
              group.displayLabel.toLocaleLowerCase().indexOf(query) < 0,
            context: contextMatchesCap(group, cap),
            evidenceKind: evidenceKind,
          }));
        });
        rack.appendChild(lane);
      });
      return rack;
    }

    function renderSourceAccordion(group, query, matchCount) {
      var open = state.view === "project" && state.projectKey === group.key;
      var shell = document.createElement("section");
      shell.className = "warehouse-source-accordion";
      if (open) shell.classList.add("is-open");
      if (groupMatches(group, query)) shell.classList.add("is-match");
      if (!!query && matchCount > 0 && !groupMatches(group, query)) shell.classList.add("is-dimmed");
      shell.dataset.sourceFingerprint = group.fingerprint;
      shell.appendChild(createSourceToggle(group, {
        matched: groupMatches(group, query),
        dimmed: !!query && matchCount > 0 && !groupMatches(group, query),
        open: open,
        activate: function () {
          if (open) closeProject(group.key);
          else enterProject(group.key);
        },
      }));
      var rack = createCapsuleRack(group, query, matchCount);
      rack.hidden = !open;
      shell.appendChild(rack);
      els.nodes.appendChild(shell);
    }

    function renderUnresolvedGroup(group, query, matchCount) {
      var shell = document.createElement("section");
      shell.className = "warehouse-unresolved-entry";
      shell.dataset.projectKey = group.key;
      var reason = document.createElement("p");
      reason.className = "warehouse-unresolved-reason";
      reason.textContent = sourceReason(group);
      shell.appendChild(reason);
      var cap = group.capsules[0];
      if (cap) {
        shell.appendChild(createCapsuleUnit(group, cap, {
          matched: capsuleMatches(cap, query),
          dimmed: !!query && matchCount > 0 && !capsuleMatches(cap, query),
          context: false,
          evidenceKind: "error",
        }));
      }
      els.unresolvedNodes.appendChild(shell);
    }

    function showFact(title, meta, evidenceKind) {
      if (!els.factStrip) return;
      els.factTitle.textContent = String(title || "");
      els.factMeta.textContent = String(meta || "");
      els.factStrip.classList.toggle("hidden", !title);
      els.factStrip.dataset.evidenceThread = evidenceKind || "";
    }

    function searchMatchCount(groups, query) {
      if (!query) return 0;
      var count = 0;
      groups.forEach(function (group) {
        if (group.displayLabel.toLocaleLowerCase().indexOf(query) >= 0) count += 1;
        group.capsules.forEach(function (cap) {
          if (capsuleMatches(cap, query)) count += 1;
        });
      });
      return count;
    }

    function contextMatchesCap(group, cap) {
      var context = state.planContext;
      return !!(
        state.contextResolved &&
        context &&
        group &&
        group.projectId &&
        capsuleId(cap) === context.capsule_id &&
        String(cap.version_id || "") === context.version_id
      );
    }

    function focusPendingNode() {
      if (!state.pendingFocusKey && state.pendingScrollTop == null) return;
      var key = state.pendingFocusKey;
      state.pendingFocusKey = "";
      window.setTimeout(function () {
        if (state.pendingScrollTop != null && els.canvas) {
          els.canvas.scrollTop = state.pendingScrollTop;
          state.pendingScrollTop = null;
        }
        if (!key) return;
        var nodes = els.world ? els.world.querySelectorAll("[data-node-key]") : [];
        if (key === "__first__" && nodes.length) {
          nodes[0].focus({ preventScroll: true });
          nodes[0].scrollIntoView({ block: "nearest", inline: "nearest" });
          return;
        }
        if (key === "__first__") {
          state.pendingFocusKey = key;
          return;
        }
        for (var i = 0; i < nodes.length; i += 1) {
          if (String(nodes[i].dataset.nodeKey || "") === key) {
            nodes[i].focus({ preventScroll: true });
            nodes[i].scrollIntoView({ block: "nearest", inline: "nearest" });
            return;
          }
        }
        if (els.canvas) els.canvas.focus();
      }, 0);
    }

    function renderBrowser() {
      var groups = sourceGroups();
      var group = currentGroup(groups);
      if (state.view === "project" && !group) {
        state.view = "overview";
        state.projectKey = "";
        state.capsuleId = "";
      }
      els.nodes.replaceChildren();
      els.unresolvedNodes.replaceChildren();
      els.browserView.classList.toggle("is-project-view", state.view === "project");
      els.unresolvedShelf.classList.add("hidden");
      var query = queryText();
      var matchCount = searchMatchCount(groups, query);
      var exactGroups = groups.filter(function (item) {
        return item.evidenceStatus === "formal_exact_version_source";
      });
      if (
        state.view === "overview" &&
        !state.planContext &&
        !state.query &&
        !state.singleSourceAutoExpanded &&
        !state.singleSourceUserCollapsed &&
        !detailsLoading() &&
        groups.length === 1 &&
        exactGroups.length === 1
      ) {
        state.view = "project";
        state.projectKey = exactGroups[0].key;
        state.singleSourceAutoExpanded = true;
        group = exactGroups[0];
        els.browserView.classList.add("is-project-view");
      }
      if (els.sourceCount) {
        els.sourceCount.textContent = formatText("formalSourceCount", { count: exactGroups.length });
      }
      if (els.searchStatus) {
        els.searchStatus.textContent = query
          ? (matchCount ? formatText("searchResultCount", { count: matchCount }) : text("searchNoResults"))
          : "";
      }
      if (els.contextStatus) {
        els.contextStatus.textContent = state.contextStatus ? text(state.contextStatus) : "";
        els.contextStatus.classList.toggle("hidden", !state.contextStatus);
        els.contextStatus.classList.toggle("is-error", state.contextStatus === "planContextMissing");
      }
      showFact("", "");

      var emptyKey = "";
      if (!formalCapsules().length) emptyKey = "noFormalCapsules";
      else if (!groups.length && detailsLoading()) emptyKey = "warehouseLoadingRelations";
      else if (!groups.length) emptyKey = "noFormalSourceIdentity";
      els.empty.classList.toggle("hidden", !emptyKey);
      els.empty.textContent = emptyKey ? text(emptyKey) : "";
      els.breadcrumb.textContent = group && group.evidenceStatus === "formal_exact_version_source"
        ? text("sourceProject") + " / " + group.displayLabel
        : "";
      exactGroups.forEach(function (item) {
        renderSourceAccordion(item, query, matchCount);
      });
      var unresolvedGroups = groups.filter(function (item) {
        return item.evidenceStatus !== "formal_exact_version_source";
      });
      unresolvedGroups.forEach(function (item) {
        renderUnresolvedGroup(item, query, matchCount);
      });
      els.unresolvedShelf.classList.toggle("hidden", unresolvedGroups.length === 0);
      focusPendingNode();
    }

    function selectedCapsule(group) {
      if (!group) return null;
      return group.capsules.find(function (cap) { return capsuleId(cap) === state.capsuleId; }) || null;
    }

    function developerProjection(group, cap) {
      var cached = details[capsuleId(cap)];
      var detail = cached && cached.value ? cached.value : { sources: [], version: {}, status_events: [] };
      var formalSource = hasFormalSourceFact(group, cap);
      var coreProjection = currentCoreCodeProjection(group, cap);
      var sourceStatus = formalSource
        ? "formal_exact_version_source"
        : group.reasonKey || "source_evidence_insufficient";
      return {
        capsule: {
          capsule_id: capsuleId(cap),
          version_id: String(cap.version_id || detail.version.version_id || ""),
          capability_kind: String(cap.type || ""),
          status: String(cap.status || ""),
        },
        source: {
          project_id: formalSource ? group.projectId : null,
          source_identity_status: sourceStatus,
          relationships: formalSource ? exactProjectSources(cap).filter(function (source) {
            return source.project_id === group.projectId;
          }) : [],
        },
        version: detail.version,
        status_events: detail.status_events,
        core_code_projection: coreProjection ? {
          schema_version: coreProjection.schema_version,
          logical_path: coreProjection.core_code.logical_path,
          sha256: coreProjection.core_code.sha256,
          canonical_hash: coreProjection.canonical_hash,
          validation: coreProjection.validation,
        } : null,
      };
    }

    function applyCodeScale() {
      if (els.coreCode) els.coreCode.style.fontSize = (14 * state.codeScale).toFixed(1) + "px";
      if (els.codeZoomValue) els.codeZoomValue.textContent = Math.round(state.codeScale * 100) + "%";
    }

    function setCodeScale(next) {
      state.codeScale = clamp(next, 0.75, 1.65);
      applyCodeScale();
    }

    function evidenceRow(label, value, kind) {
      var row = document.createElement("div");
      row.className = "warehouse-evidence-row";
      row.dataset.evidenceKind = kind;
      var heading = document.createElement("h3");
      heading.textContent = label;
      var content = document.createElement("p");
      content.textContent = value || "—";
      row.appendChild(heading);
      row.appendChild(content);
      return row;
    }

    function renderEvidenceSummary(group, cap, projection) {
      els.evidenceSummary.replaceChildren(
        evidenceRow(
          text("evidenceIdentity"),
          [
            capabilityName(String(cap.type || "")),
            capsuleId(cap),
            String(cap.version_id || ""),
            String(cap.status || ""),
          ].filter(Boolean).join(" · "),
          "identity"
        ),
        evidenceRow(
          text("evidenceSource"),
          hasFormalSourceFact(group, cap)
            ? [group.displayLabel, sourcePathFor(group, cap)].filter(Boolean).join(" · ")
            : sourceReason(group),
          "source"
        ),
        evidenceRow(
          text("evidenceContracts"),
          contractRows(cap).map(function (row) {
            return row.label + ": " + row.value;
          }).join(" · "),
          "contracts"
        ),
        evidenceRow(
          text("evidenceValidation"),
          projection
            ? projection.validation.status + " · " + projection.validation.acceptance_scope
            : text("evidenceUnavailable"),
          "validation"
        ),
        evidenceRow(
          text("evidenceEntry"),
          projection ? projection.core_code.logical_path + " · " + projection.core_code.sha256.slice(0, 12) : "—",
          "entry"
        )
      );
    }

    function renderProofThread() {
      var groups = sourceGroups();
      var group = currentGroup(groups);
      var cap = selectedCapsule(group);
      var projection = group && cap ? currentCoreCodeProjection(group, cap) : null;
      var validationPassed = !!(cap && capsuleValidationPassed(cap));
      var identity = group && cap ? coreCodeIdentity(group, cap) : null;
      var cachedCode = identity ? coreCodeCache[identity.key] : null;
      els.evidenceSource.textContent = group ? group.displayLabel : String(groups.length);
      els.evidenceCapsule.textContent = cap
        ? capabilityName(String(cap.type || "")) + " · " + String(cap.name || capsuleId(cap))
        : "";
      var versionId = cap ? String(cap.version_id || "") : "";
      els.evidenceVersion.textContent = cap ? readableVersion(cap) : "";
      els.evidenceVersion.title = versionId;
      els.evidenceValidation.textContent = cap
        ? (projection || (state.view !== "code" && validationPassed)
          ? text("evidenceAvailable")
          : cachedCode && cachedCode.status === "loading"
            ? text("warehouseLoadingRelations")
            : text("evidenceUnavailable"))
        : "";
      els.codeProof.classList.toggle("is-formal-context", state.contextResolved);
      els.codeProof.classList.toggle(
        "is-error",
        state.contextStatus === "planContextMissing" ||
          (state.view === "code" && cap && (
            !identity || (cachedCode && cachedCode.status === "failed")
          ))
      );
    }

    function renderCode() {
      var groups = sourceGroups();
      var group = currentGroup(groups);
      var cap = selectedCapsule(group);
      if (!group || !cap) {
        state.view = group ? "project" : "overview";
        state.capsuleId = "";
        render();
        return;
      }
      var sourcePath = sourcePathFor(group, cap);
      els.codePath.textContent = [group.displayLabel, sourcePath].filter(Boolean).join(" / ");
      els.codeTitle.textContent = String(cap.name || capsuleId(cap));
      var codeElement = els.coreCode.querySelector("code");
      var coreProjection = currentCoreCodeProjection(group, cap);
      codeElement.textContent = coreProjection ? coreProjection.core_code.content : "";
      els.coreCode.classList.toggle("hidden", !coreProjection);
      els.coreCodeEmpty.classList.toggle("hidden", !!coreProjection);
      var identity = coreCodeIdentity(group, cap);
      var cachedCode = identity ? coreCodeCache[identity.key] : null;
      els.coreCodeEmpty.textContent = !identity
        ? text("insufficientSourceEvidence")
        : cachedCode && cachedCode.status === "loading"
          ? text("warehouseLoadingRelations")
          : text("noVerifiedCoreCode");
      els.codeKind.textContent = capabilityName(String(cap.type || ""));
      els.codeVersion.textContent = readableVersion(cap);
      els.codeVersion.title = String(cap.version_id || "");
      els.codeStatus.textContent = String(cap.status || "");
      els.codeValidation.textContent = coreProjection ? text("evidenceAvailable") : text("evidenceUnavailable");
      els.codeProof.classList.toggle("is-verified", !!coreProjection);
      els.codeDeveloperMode.checked = state.developerMode;
      els.developerDetails.classList.toggle("hidden", !state.developerMode);
      renderEvidenceSummary(group, cap, coreProjection);
      els.developerEvidence.textContent = state.developerMode
        ? JSON.stringify(developerProjection(group, cap), null, 2)
        : "";
      if (!state.developerMode) els.rawEvidence.removeAttribute("open");
      applyCodeScale();
      if (!coreProjection) ensureCoreCodeProjection(group, cap);
    }

    function updateIngestionEntry() {
      els.ingestionEntry.classList.remove("hidden");
    }

    function render() {
      if (!bound || !state.active) return;
      resolvePlanContext();
      var targetAvailable = host.targetAvailable ? host.targetAvailable() : false;
      els.targetNav.classList.toggle("hidden", !targetAvailable);
      els.targetNav.disabled = !targetAvailable;
      els.language.textContent = host.getLocale && host.getLocale() === "en" ? "EN / 中" : "中 / EN";
      var codeView = state.view === "code";
      els.browserView.classList.toggle("hidden", codeView);
      els.codeView.classList.toggle("hidden", !codeView);
      els.codeView.classList.toggle("is-evidence-mode", codeView && state.developerMode);
      els.searchWrap.classList.toggle("hidden", codeView);
      if (codeView) renderCode();
      else renderBrowser();
      renderProofThread();
      updateIngestionEntry();
    }

    function requestDetail(cap) {
      var id = capsuleId(cap);
      var versionId = String(cap.version_id || "");
      invalidateCoreCodeForCapsule(id);
      var revision = ++requestRevision;
      details[id] = { versionId: versionId, loading: true, value: null, requestRevision: revision };
      Promise.resolve(host.readCapsuleDetail ? host.readCapsuleDetail(id) : null).then(function (raw) {
        if (!details[id] || details[id].requestRevision !== revision) return;
        details[id] = {
          versionId: versionId,
          loading: false,
          value: projectDetail(cap, raw),
          requestRevision: revision,
        };
        render();
      }).catch(function () {
        if (!details[id] || details[id].requestRevision !== revision) return;
        details[id] = {
          versionId: versionId,
          loading: false,
          value: projectDetail(cap, null),
          requestRevision: revision,
        };
        render();
      });
    }

    function ensureDetails() {
      var capsules = formalCapsules();
      var live = {};
      capsules.forEach(function (cap) {
        var id = capsuleId(cap);
        var versionId = String(cap.version_id || "");
        live[id] = true;
        if (!id) return;
        if (details[id] && details[id].versionId === versionId) return;
        requestDetail(cap);
      });
      Object.keys(details).forEach(function (id) {
        if (!live[id]) delete details[id];
      });
    }

    function resolvePlanContext() {
      var context = state.planContext;
      var ready = formalCapsules().every(function (cap) {
        var cached = details[capsuleId(cap)];
        return cached && cached.loading !== true && cached.versionId === String(cap.version_id || "");
      });
      if (!context || state.contextComplete || !ready) return;
      state.contextComplete = true;
      var cap = formalCapsules().find(function (item) {
        return (
          capsuleId(item) === context.capsule_id &&
          String(item.version_id || "") === context.version_id &&
          capsuleCanonicalHash(item) === context.canonical_hash
        );
      });
      var sources = cap ? exactProjectSources(cap) : [];
      if (!cap || sources.length !== 1) {
        state.contextResolved = false;
        state.contextStatus = "planContextMissing";
        return;
      }
      var groupKey = "project:" + sources[0].project_id;
      var group = sourceGroups().find(function (item) { return item.key === groupKey; });
      if (!group || !hasFormalSourceFact(group, cap)) {
        state.contextResolved = false;
        state.contextStatus = "planContextMissing";
        return;
      }
      state.contextResolved = true;
      state.contextStatus = "planContextResolved";
      state.view = "project";
      state.projectKey = groupKey;
      state.capsuleId = capsuleId(cap);
      state.pendingFocusKey = "capsule:" + capsuleId(cap);
    }

    function enterScene(context) {
      var active = document.activeElement;
      state.entryFocusId = active && active.id ? active.id : "btn-capsule-warehouse";
      state.active = true;
      state.view = "overview";
      state.projectKey = "";
      state.capsuleId = "";
      state.query = "";
      state.overviewSnapshot = null;
      state.projectSnapshot = null;
      state.searchSnapshot = null;
      state.pendingFocusKey = "";
      state.planContext = context && typeof context === "object" ? {
        capsule_id: String(context.capsule_id || ""),
        version_id: String(context.version_id || ""),
        canonical_hash: String(context.canonical_hash || ""),
      } : null;
      state.contextStatus = "";
      state.contextResolved = false;
      state.contextComplete = false;
      state.pendingScrollTop = null;
      state.singleSourceAutoExpanded = false;
      state.singleSourceUserCollapsed = false;
      if (els.query) els.query.value = "";
      host.showScreen("screen-capsule-warehouse");
      if (els.screen) els.screen.scrollTop = 0;
      window.scrollTo(0, 0);
      if (host.transition) host.transition("warehouse");
      render();
      ensureDetails();
      window.setTimeout(function () {
        if (state.planContext) return;
        var first = els.world.querySelector("[data-node-key]");
        if (first) first.focus();
        else if (detailsLoading()) state.pendingFocusKey = "__first__";
        else els.canvas.focus();
      }, 0);
    }

    function resumeScene() {
      state.active = true;
      host.showScreen("screen-capsule-warehouse");
      render();
      window.setTimeout(function () {
        var key = activeNodeKey();
        if (key) return;
        var preferred = state.view === "code"
          ? els.codeTitle
          : els.world.querySelector("[data-node-key]") || els.canvas;
        if (preferred) preferred.focus();
      }, 0);
    }

    function leaveScene() {
      invalidatePendingCoreCodeRequests();
      state.active = false;
      host.showScreen("screen-main");
      if (host.syncAppState) host.syncAppState();
      window.setTimeout(function () {
        var target = $(state.entryFocusId) || $("btn-capsule-warehouse");
        if (target) target.focus();
      }, 0);
    }

    function enterProject(key) {
      if (state.view === "overview") state.overviewSnapshot = viewSnapshot();
      var group = sourceGroups().find(function (item) { return item.key === key; });
      state.view = "project";
      state.projectKey = key;
      state.capsuleId = "";
      state.pendingFocusKey = group ? "project:" + group.key : "";
      render();
    }

    function closeProject(key) {
      state.view = "overview";
      state.projectKey = "";
      state.capsuleId = "";
      state.singleSourceUserCollapsed = true;
      state.pendingFocusKey = "project:" + key;
      render();
    }

    function toggleCapsule(group, cap) {
      state.view = "project";
      state.projectKey = group.key;
      state.capsuleId = state.capsuleId === capsuleId(cap) ? "" : capsuleId(cap);
      state.pendingFocusKey = "capsule:" + capsuleId(cap);
      render();
    }

    function openCode(group, cap) {
      if (!sourcePathFor(group, cap) || !coreCodeIdentity(group, cap)) return;
      invalidatePendingCoreCodeRequests();
      state.projectSnapshot = viewSnapshot();
      state.view = "code";
      state.projectKey = group.key;
      state.capsuleId = capsuleId(cap);
      render();
      window.setTimeout(function () { els.codeTitle.focus(); }, 0);
    }

    function goBack() {
      if (state.view === "code") {
        invalidatePendingCoreCodeRequests();
        restoreSnapshot(state.projectSnapshot);
        state.view = "project";
        render();
        return;
      }
      if (state.view === "project") {
        if (state.planContext) {
          leaveScene();
          return;
        }
        if (state.query && state.searchSnapshot) {
          clearSearch();
          return;
        }
        var projectFocus = "project:" + state.projectKey;
        restoreSnapshot(state.overviewSnapshot);
        state.view = "overview";
        state.singleSourceUserCollapsed = true;
        state.pendingFocusKey = projectFocus;
        render();
        return;
      }
      leaveScene();
    }

    function clearSearch() {
      state.query = "";
      if (els.query) els.query.value = "";
      if (state.searchSnapshot) restoreSnapshot(state.searchSnapshot);
      state.searchSnapshot = null;
      render();
    }

    function updateSearch(value) {
      var next = String(value || "");
      if (!state.query && next) state.searchSnapshot = viewSnapshot();
      state.query = next;
      if (!next && state.searchSnapshot) {
        restoreSnapshot(state.searchSnapshot);
        state.searchSnapshot = null;
      }
      render();
    }

    function activateSearch() {
      var query = queryText();
      if (!query) return;
      var groups = sourceGroups();
      var project = groups.find(function (group) {
        return group.displayLabel.toLocaleLowerCase().indexOf(query) >= 0;
      });
      if (project) {
        state.view = "project";
        state.projectKey = project.key;
        state.capsuleId = "";
        state.pendingFocusKey = "project:" + project.key;
        render();
        return;
      }
      for (var i = 0; i < groups.length; i += 1) {
        var capIndex = groups[i].capsules.findIndex(function (cap) { return capsuleMatches(cap, query); });
        if (capIndex < 0) continue;
        state.view = "project";
        state.projectKey = groups[i].key;
        state.capsuleId = capsuleId(groups[i].capsules[capIndex]);
        state.pendingFocusKey = "capsule:" + capsuleId(groups[i].capsules[capIndex]);
        render();
        return;
      }
    }

    function cacheElements() {
      els.entry = $("btn-capsule-warehouse");
      els.screen = $("screen-capsule-warehouse");
      els.back = $("btn-warehouse-scene-back");
      els.searchWrap = document.querySelector(".warehouse-scene-search");
      els.query = $("warehouse-scene-query");
      els.searchStatus = $("warehouse-search-status");
      els.sourceCount = $("warehouse-source-count");
      els.browserView = $("warehouse-browser-view");
      els.breadcrumb = $("warehouse-scene-breadcrumb");
      els.contextStatus = $("warehouse-context-status");
      els.canvas = $("warehouse-scene-canvas");
      els.world = $("warehouse-scene-world");
      els.nodes = $("warehouse-scene-nodes");
      els.unresolvedShelf = $("warehouse-unresolved-shelf");
      els.unresolvedNodes = $("warehouse-unresolved-nodes");
      els.empty = $("warehouse-scene-empty");
      els.factStrip = $("warehouse-fact-strip");
      els.factTitle = $("warehouse-fact-title");
      els.factMeta = $("warehouse-fact-meta");
      els.codeProof = $("warehouse-code-proof");
      els.evidenceSource = $("warehouse-evidence-source");
      els.evidenceCapsule = $("warehouse-evidence-capsule");
      els.evidenceVersion = $("warehouse-evidence-version");
      els.evidenceValidation = $("warehouse-evidence-validation");
      els.codeView = $("warehouse-code-view");
      els.codePath = $("warehouse-code-path");
      els.codeTitle = $("warehouse-code-title");
      els.codeKind = $("warehouse-code-kind");
      els.codeVersion = $("warehouse-code-version");
      els.codeStatus = $("warehouse-code-status");
      els.codeValidation = $("warehouse-code-validation");
      els.codeDeveloperMode = $("warehouse-code-developer-mode");
      els.codeZoomOut = $("btn-warehouse-code-zoom-out");
      els.codeZoomIn = $("btn-warehouse-code-zoom-in");
      els.codeZoomReset = $("btn-warehouse-code-zoom-reset");
      els.codeZoomValue = $("warehouse-code-zoom-value");
      els.coreCode = $("warehouse-core-code");
      els.coreCodeEmpty = $("warehouse-core-code-empty");
      els.developerDetails = $("warehouse-developer-details");
      els.evidenceSummary = $("warehouse-evidence-summary");
      els.rawEvidence = $("warehouse-raw-evidence");
      els.developerEvidence = $("warehouse-developer-evidence");
      els.ingestionEntry = $("btn-open-capsule-ingestion");
      els.productNav = $("btn-warehouse-product-nav");
      els.targetNav = $("btn-warehouse-target-nav");
      els.compatNav = $("btn-warehouse-compat-nav");
      els.language = $("btn-warehouse-lang");
    }

    function handleDocumentKeydown(event) {
      if (!state.active) return;
      var management = $("screen-capsule-ingestion");
      if (management && !management.classList.contains("hidden")) return;
      if (state.view === "code" && (event.metaKey || event.ctrlKey)) {
        if (event.key === "+" || event.key === "=") {
          event.preventDefault();
          setCodeScale(state.codeScale + 0.1);
        } else if (event.key === "-") {
          event.preventDefault();
          setCodeScale(state.codeScale - 0.1);
        } else if (event.key === "0") {
          event.preventDefault();
          setCodeScale(1);
        }
      }
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      goBack();
    }

    function bind() {
      if (bound) return;
      cacheElements();
      if (!els.entry || !els.screen) return;
      bound = true;
      els.entry.addEventListener("click", function (event) {
        event.preventDefault();
        enterScene(null);
      });
      els.back.addEventListener("click", goBack);
      els.query.addEventListener("input", function () { updateSearch(els.query.value); });
      els.query.addEventListener("keydown", function (event) {
        if (event.key !== "Enter") return;
        event.preventDefault();
        activateSearch();
      });
      els.codeDeveloperMode.addEventListener("change", function () {
        state.developerMode = els.codeDeveloperMode.checked === true;
        render();
      });
      els.codeZoomOut.addEventListener("click", function () { setCodeScale(state.codeScale - 0.1); });
      els.codeZoomIn.addEventListener("click", function () { setCodeScale(state.codeScale + 0.1); });
      els.codeZoomReset.addEventListener("click", function () { setCodeScale(1); });
      els.ingestionEntry.addEventListener("click", function (event) {
        event.stopPropagation();
        if (host.openManagement) host.openManagement(currentSpecimenContext());
      });
      els.productNav.addEventListener("click", function () {
        invalidatePendingCoreCodeRequests();
        state.active = false;
        if (host.openProduct) host.openProduct();
      });
      els.targetNav.addEventListener("click", function () {
        invalidatePendingCoreCodeRequests();
        state.active = false;
        if (host.openTarget) host.openTarget();
      });
      els.compatNav.addEventListener("click", function () {
        invalidatePendingCoreCodeRequests();
        state.active = false;
        if (host.openCompatibility) host.openCompatibility();
      });
      els.language.addEventListener("click", function () {
        if (host.toggleLocale) host.toggleLocale();
      });
      document.addEventListener("keydown", handleDocumentKeydown);
    }

    function suspendScene() {
      invalidatePendingCoreCodeRequests();
      state.active = false;
    }

    function sync() {
      var live = {};
      formalCapsules().forEach(function (cap) {
        live[capsuleId(cap)] = String(cap.version_id || "");
      });
      Object.keys(details).forEach(function (id) {
        if (!(id in live) || details[id].versionId !== live[id]) {
          delete details[id];
          invalidateCoreCodeForCapsule(id);
        }
      });
      if (!state.active) return;
      if (state.view === "code") invalidatePendingCoreCodeRequests();
      render();
      ensureDetails();
    }

    function getState() {
      var groups = sourceGroups();
      var group = currentGroup(groups);
      var cap = selectedCapsule(group);
      return {
        active: state.active,
        view: state.view,
        project_id: group && group.evidenceStatus === "formal_exact_version_source"
          ? group.projectId || null
          : null,
        project_key: group ? group.key : null,
        capsule_id: cap ? capsuleId(cap) : null,
        query: state.query,
        code_scale: state.codeScale,
        developer_mode: state.developerMode,
        formal_capsule_count: formalCapsules().length,
        source_group_count: groups.length,
        source_relations_loading: detailsLoading(),
        verified_core_code: !!(group && cap && currentCoreCodeProjection(group, cap)),
        search_match_count: searchMatchCount(groups, queryText()),
        plan_context_status: state.contextStatus || null,
        focused_node: activeNodeKey() || null,
      };
    }

    function currentSpecimenContext() {
      var groups = sourceGroups();
      var group = currentGroup(groups);
      if (!group || state.view === "overview") return null;
      var cap = selectedCapsule(group);
      var counts = capabilityCounts(group);
      return {
        project_id: group.projectId || null,
        project_key: group.key,
        display_name: group.displayLabel,
        exact_source: group.evidenceStatus === "formal_exact_version_source",
        formal_capsule_count: group.capsules.length,
        capsule_counts: counts,
        capsule_id: cap ? capsuleId(cap) : null,
        capsule_name: cap ? String(cap.name || capsuleId(cap)) : null,
        capability_kind: cap ? String(cap.type || "") : null,
        version_id: cap ? String(cap.version_id || "") : null,
        canonical_hash: cap ? capsuleCanonicalHash(cap) : null,
      };
    }

    return {
      bind: bind,
      sync: sync,
      getState: getState,
      open: enterScene,
      resume: resumeScene,
      suspend: suspendScene,
    };
  }

  window.ReweaveCapsuleWarehouseScene = {
    create: create,
  };
})();
