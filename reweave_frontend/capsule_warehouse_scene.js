(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var WORLD_WIDTH = 1200;
  var WORLD_HEIGHT = 760;

  function create(host) {
    var state = {
      active: false,
      view: "overview",
      projectKey: "",
      capsuleId: "",
      query: "",
      scale: 1,
      x: 0,
      y: 0,
      codeScale: 1,
      developerMode: false,
      entryFocusId: "",
      pendingFocusKey: "",
      overviewSnapshot: null,
      projectSnapshot: null,
      searchSnapshot: null,
    };
    var details = {};
    var coreCodeCache = {};
    var requestRevision = 0;
    var coreCodeRequestRevision = 0;
    var bound = false;
    var panning = null;
    var els = {};

    function $(id) {
      return document.getElementById(id);
    }

    function text(key) {
      return host.t ? host.t(key) : key;
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
        result[id] = displayName && !looksAbsolutePath(displayName) ? displayName : id;
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

    function addCapsuleToGroup(map, key, label, evidenceStatus, projectId, cap) {
      if (!map[key]) {
        map[key] = {
          key: key,
          projectId: evidenceStatus === "formal_exact_version_source" ? String(projectId || "") : "",
          label: label,
          evidenceStatus: evidenceStatus,
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
        if (sources.length) {
          sources.forEach(function (source) {
            var key = "project:" + source.project_id;
            addCapsuleToGroup(
              map,
              key,
              labels[source.project_id] || source.project_id,
              "formal_exact_version_source",
              source.project_id,
              cap
            );
          });
          return;
        }
        var sourceId = String(cap.source_id || "");
        var label = sourceLabel(cap);
        if (sourceId) {
          addCapsuleToGroup(
            map,
            "source:" + sourceId,
            labels[sourceId] || label || sourceId,
            "missing_exact_version_source_relation",
            "",
            cap
          );
        } else if (label) {
          addCapsuleToGroup(map, "label:" + label, label, "missing_formal_source_identity", "", cap);
        }
      });
      return Object.keys(map).map(function (key) {
        map[key].capsules.sort(function (left, right) {
          return String(left.name || capsuleId(left)).localeCompare(String(right.name || capsuleId(right)));
        });
        return map[key];
      }).sort(function (left, right) {
        return left.label.localeCompare(right.label);
      });
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

    function overviewPosition(group, index) {
      var angle = ((stableHash(group.key) % 360) + index * 137.5) * Math.PI / 180;
      var radius = 190 + (index % 3) * 75;
      return {
        x: WORLD_WIDTH / 2 + Math.cos(angle) * radius,
        y: WORLD_HEIGHT / 2 + Math.sin(angle) * radius * 0.72,
      };
    }

    function capsulePosition(group, cap, index) {
      var angle = ((stableHash(group.key + ":" + capsuleId(cap)) % 90) + index * 137.5) * Math.PI / 180;
      var radius = 170 + (index % 2) * 68;
      return {
        x: WORLD_WIDTH / 2 + Math.cos(angle) * radius,
        y: WORLD_HEIGHT / 2 + Math.sin(angle) * radius * 0.76,
      };
    }

    function currentGroup(groups) {
      return groups.find(function (group) { return group.key === state.projectKey; }) || null;
    }

    function viewSnapshot() {
      return {
        view: state.view,
        projectKey: state.projectKey,
        capsuleId: state.capsuleId,
        scale: state.scale,
        x: state.x,
        y: state.y,
        focusKey: activeNodeKey(),
      };
    }

    function restoreSnapshot(snapshot) {
      if (!snapshot) return;
      state.view = snapshot.view;
      state.projectKey = snapshot.projectKey;
      state.capsuleId = snapshot.capsuleId;
      state.scale = snapshot.scale;
      state.x = snapshot.x;
      state.y = snapshot.y;
      state.pendingFocusKey = snapshot.focusKey || "";
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

    function applyCanvasTransform() {
      if (!els.world) return;
      els.world.style.transform =
        "translate(" + state.x.toFixed(1) + "px, " + state.y.toFixed(1) + "px) scale(" + state.scale.toFixed(3) + ")";
      if (els.zoomValue) els.zoomValue.textContent = Math.round(state.scale * 100) + "%";
    }

    function setCanvasScale(next, clientX, clientY) {
      var previous = state.scale;
      next = clamp(next, 0.55, 2);
      if (next === previous) return;
      if (els.canvas && Number.isFinite(clientX) && Number.isFinite(clientY)) {
        var rect = els.canvas.getBoundingClientRect();
        var px = clientX - (rect.left + rect.width / 2);
        var py = clientY - (rect.top + rect.height / 2);
        var ratio = next / previous;
        state.x = px - (px - state.x) * ratio;
        state.y = py - (py - state.y) * ratio;
      }
      state.scale = next;
      applyCanvasTransform();
    }

    function resetCanvas() {
      state.scale = 1;
      state.x = 0;
      state.y = 0;
      applyCanvasTransform();
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
        group.label.toLocaleLowerCase().indexOf(query) >= 0 ||
        group.capsules.some(function (cap) { return capsuleMatches(cap, query); })
      );
    }

    function appendLine(from, to, matched) {
      var line = document.createElementNS(SVG_NS, "line");
      line.setAttribute("x1", String(from.x));
      line.setAttribute("y1", String(from.y));
      line.setAttribute("x2", String(to.x));
      line.setAttribute("y2", String(to.y));
      line.setAttribute("class", "warehouse-source-link" + (matched ? " is-match" : ""));
      els.links.appendChild(line);
    }

    function hasFormalSourceFact(group, cap) {
      if (!group || group.evidenceStatus !== "formal_exact_version_source") return false;
      return exactProjectSources(cap).some(function (source) {
        return group.projectId === source.project_id && group.key === "project:" + source.project_id;
      });
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

    function createNode(options) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "warehouse-node";
      if (options.center) button.classList.add("is-center");
      if (options.matched) button.classList.add("is-match");
      if (options.dimmed) button.classList.add("is-dimmed");
      button.style.left = options.position.x + "px";
      button.style.top = options.position.y + "px";
      button.dataset.nodeKey = options.nodeKey;
      if (options.projectKey) button.dataset.projectKey = options.projectKey;
      if (options.capsuleId) button.dataset.capsuleId = options.capsuleId;
      button.setAttribute("aria-label", options.label);

      var glyph = document.createElement("span");
      glyph.className = "warehouse-node-glyph";
      glyph.setAttribute("aria-hidden", "true");
      glyph.textContent = options.kind === "project" ? "◆" : "◫";
      button.appendChild(glyph);

      var label = document.createElement("span");
      label.className = "warehouse-node-label";
      label.textContent = options.label;
      if (options.note) {
        var note = document.createElement("span");
        note.className = "warehouse-node-note";
        note.textContent = options.note;
        label.appendChild(note);
      }
      button.appendChild(label);
      button.addEventListener("click", options.activate);
      button.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        event.stopPropagation();
        options.activate();
      });
      els.nodes.appendChild(button);
      return button;
    }

    function focusPendingNode() {
      if (!state.pendingFocusKey) return;
      var key = state.pendingFocusKey;
      state.pendingFocusKey = "";
      window.setTimeout(function () {
        var nodes = els.nodes ? els.nodes.querySelectorAll("[data-node-key]") : [];
        for (var i = 0; i < nodes.length; i += 1) {
          if (String(nodes[i].dataset.nodeKey || "") === key) {
            nodes[i].focus();
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
      els.links.replaceChildren();
      var query = queryText();

      var emptyKey = "";
      if (!formalCapsules().length) emptyKey = "noFormalCapsules";
      else if (!groups.length && detailsLoading()) emptyKey = "warehouseLoadingRelations";
      else if (!groups.length) emptyKey = "noFormalSourceIdentity";
      els.empty.classList.toggle("hidden", !emptyKey);
      els.empty.textContent = emptyKey ? text(emptyKey) : "";

      if (state.view === "overview") {
        els.breadcrumb.textContent = text("sourceProjectOverview") + " · " + groups.length;
        groups.forEach(function (item, index) {
          var matched = groupMatches(item, query);
          createNode({
            kind: "project",
            nodeKey: "project:" + item.key,
            projectKey: item.key,
            label: item.label,
            note: item.evidenceStatus === "formal_exact_version_source"
              ? ""
              : text("insufficientSourceEvidence"),
            position: overviewPosition(item, index),
            matched: matched,
            dimmed: !!query && !matched,
            activate: function () { enterProject(item.key); },
          });
        });
      } else if (group) {
        els.breadcrumb.textContent = text("sourceProjectOverview") + " / " + group.label;
        var groupMatched = group.label.toLocaleLowerCase().indexOf(query) >= 0;
        createNode({
          kind: "project",
          nodeKey: "project:" + group.key,
          projectKey: group.key,
          label: group.label,
          note: group.evidenceStatus === "formal_exact_version_source"
            ? ""
            : text("insufficientSourceEvidence"),
          position: { x: WORLD_WIDTH / 2, y: WORLD_HEIGHT / 2 },
          center: true,
          matched: !!query && groupMatched,
          dimmed: false,
          activate: function () {},
        });
        group.capsules.forEach(function (cap, index) {
          var position = capsulePosition(group, cap, index);
          var matched = capsuleMatches(cap, query);
          if (hasFormalSourceFact(group, cap)) appendLine(
            { x: WORLD_WIDTH / 2, y: WORLD_HEIGHT / 2 },
            position,
            !!query && (groupMatched || matched)
          );
          createNode({
            kind: "capsule",
            nodeKey: "capsule:" + capsuleId(cap),
            projectKey: group.key,
            capsuleId: capsuleId(cap),
            label: String(cap.name || capsuleId(cap)),
            position: position,
            matched: matched,
            dimmed: !!query && !matched && !groupMatched,
            activate: function () { openCapsule(group, cap); },
          });
        });
      }
      applyCanvasTransform();
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
        : group.evidenceStatus === "missing_formal_source_identity"
          ? "missing_formal_source_identity"
          : "missing_exact_version_source_relation";
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
      els.codePath.textContent = group.label + " / " + String(cap.name || capsuleId(cap));
      els.codeTitle.textContent = String(cap.name || capsuleId(cap));
      var codeElement = els.coreCode.querySelector("code");
      var coreProjection = currentCoreCodeProjection(group, cap);
      codeElement.textContent = coreProjection ? coreProjection.core_code.content : "";
      els.coreCode.classList.toggle("hidden", !coreProjection);
      els.coreCodeEmpty.classList.toggle("hidden", !!coreProjection);
      els.codeDeveloperMode.checked = state.developerMode;
      els.developerDetails.classList.toggle("hidden", !state.developerMode);
      els.developerEvidence.textContent = state.developerMode
        ? JSON.stringify(developerProjection(group, cap), null, 2)
        : "";
      applyCodeScale();
      if (!coreProjection) ensureCoreCodeProjection(group, cap);
    }

    function updateIngestionEntry() {
      var emptyBrowser = state.view !== "code" && sourceGroups().length === 0;
      var codeDeveloper = state.view === "code" && state.developerMode;
      els.ingestionEntry.classList.toggle("hidden", !emptyBrowser && !codeDeveloper);
    }

    function render() {
      if (!bound || !state.active) return;
      var codeView = state.view === "code";
      els.browserView.classList.toggle("hidden", codeView);
      els.codeView.classList.toggle("hidden", !codeView);
      els.searchWrap.classList.toggle("hidden", codeView);
      els.canvasZoom.classList.toggle("hidden", codeView);
      if (codeView) renderCode();
      else renderBrowser();
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

    function enterScene() {
      var active = document.activeElement;
      state.entryFocusId = active && active.id ? active.id : "btn-capsule-warehouse";
      state.active = true;
      state.view = "overview";
      state.projectKey = "";
      state.capsuleId = "";
      state.query = "";
      state.searchSnapshot = null;
      state.pendingFocusKey = "";
      resetCanvas();
      if (els.query) els.query.value = "";
      host.showScreen("screen-capsule-warehouse");
      render();
      ensureDetails();
      window.setTimeout(function () {
        var first = els.nodes.querySelector("[data-node-key]");
        if (first) first.focus();
        else els.canvas.focus();
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
      state.view = "project";
      state.projectKey = key;
      state.capsuleId = "";
      state.scale = 1;
      state.x = 0;
      state.y = 0;
      state.pendingFocusKey = "project:" + key;
      render();
    }

    function openCapsule(group, cap) {
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
        var capsuleFocus = "capsule:" + state.capsuleId;
        restoreSnapshot(state.projectSnapshot);
        state.view = "project";
        state.pendingFocusKey = capsuleFocus;
        render();
        return;
      }
      if (state.view === "project") {
        if (state.query && state.searchSnapshot) {
          clearSearch();
          return;
        }
        var projectFocus = "project:" + state.projectKey;
        restoreSnapshot(state.overviewSnapshot);
        state.view = "overview";
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

    function centerPosition(position, scale) {
      state.scale = scale;
      state.x = -(position.x - WORLD_WIDTH / 2) * scale;
      state.y = -(position.y - WORLD_HEIGHT / 2) * scale;
    }

    function activateSearch() {
      var query = queryText();
      if (!query) return;
      var groups = sourceGroups();
      var projectIndex = groups.findIndex(function (group) {
        return group.label.toLocaleLowerCase().indexOf(query) >= 0;
      });
      if (projectIndex >= 0) {
        var project = groups[projectIndex];
        if (state.view === "overview") centerPosition(overviewPosition(project, projectIndex), 1.35);
        else if (state.projectKey !== project.key) {
          state.view = "project";
          state.projectKey = project.key;
          centerPosition({ x: WORLD_WIDTH / 2, y: WORLD_HEIGHT / 2 }, 1.15);
        }
        state.pendingFocusKey = "project:" + project.key;
        render();
        return;
      }
      for (var i = 0; i < groups.length; i += 1) {
        var capIndex = groups[i].capsules.findIndex(function (cap) { return capsuleMatches(cap, query); });
        if (capIndex < 0) continue;
        state.view = "project";
        state.projectKey = groups[i].key;
        centerPosition(capsulePosition(groups[i], groups[i].capsules[capIndex], capIndex), 1.35);
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
      els.canvasZoom = document.querySelector(".warehouse-scene-zoom");
      els.zoomOut = $("btn-warehouse-zoom-out");
      els.zoomIn = $("btn-warehouse-zoom-in");
      els.zoomReset = $("btn-warehouse-zoom-reset");
      els.zoomValue = $("warehouse-zoom-value");
      els.browserView = $("warehouse-browser-view");
      els.breadcrumb = $("warehouse-scene-breadcrumb");
      els.canvas = $("warehouse-scene-canvas");
      els.world = $("warehouse-scene-world");
      els.links = $("warehouse-scene-links");
      els.nodes = $("warehouse-scene-nodes");
      els.empty = $("warehouse-scene-empty");
      els.codeView = $("warehouse-code-view");
      els.codePath = $("warehouse-code-path");
      els.codeTitle = $("warehouse-code-title");
      els.codeDeveloperMode = $("warehouse-code-developer-mode");
      els.codeZoomOut = $("btn-warehouse-code-zoom-out");
      els.codeZoomIn = $("btn-warehouse-code-zoom-in");
      els.codeZoomReset = $("btn-warehouse-code-zoom-reset");
      els.codeZoomValue = $("warehouse-code-zoom-value");
      els.coreCode = $("warehouse-core-code");
      els.coreCodeEmpty = $("warehouse-core-code-empty");
      els.developerDetails = $("warehouse-developer-details");
      els.developerEvidence = $("warehouse-developer-evidence");
      els.ingestionEntry = $("btn-open-capsule-ingestion");
    }

    function handleCanvasKeydown(event) {
      var step = event.shiftKey ? 80 : 34;
      if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "+", "=", "-", "0"].indexOf(event.key) < 0) return;
      event.preventDefault();
      if (event.key === "ArrowLeft") state.x += step;
      else if (event.key === "ArrowRight") state.x -= step;
      else if (event.key === "ArrowUp") state.y += step;
      else if (event.key === "ArrowDown") state.y -= step;
      else if (event.key === "+" || event.key === "=") setCanvasScale(state.scale + 0.15);
      else if (event.key === "-") setCanvasScale(state.scale - 0.15);
      else resetCanvas();
      applyCanvasTransform();
    }

    function handleDocumentKeydown(event) {
      if (!state.active) return;
      var management = $("capsule-warehouse-popover");
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
        enterScene();
      });
      els.back.addEventListener("click", goBack);
      els.query.addEventListener("input", function () { updateSearch(els.query.value); });
      els.query.addEventListener("keydown", function (event) {
        if (event.key !== "Enter") return;
        event.preventDefault();
        activateSearch();
      });
      els.zoomOut.addEventListener("click", function () { setCanvasScale(state.scale - 0.15); });
      els.zoomIn.addEventListener("click", function () { setCanvasScale(state.scale + 0.15); });
      els.zoomReset.addEventListener("click", resetCanvas);
      els.canvas.addEventListener("wheel", function (event) {
        event.preventDefault();
        setCanvasScale(state.scale + (event.deltaY < 0 ? 0.1 : -0.1), event.clientX, event.clientY);
      }, { passive: false });
      els.canvas.addEventListener("keydown", handleCanvasKeydown);
      els.canvas.addEventListener("pointerdown", function (event) {
        if (event.button !== 0 || (event.target.closest && event.target.closest(".warehouse-node"))) return;
        panning = { clientX: event.clientX, clientY: event.clientY, x: state.x, y: state.y };
        els.canvas.classList.add("is-panning");
        els.canvas.setPointerCapture(event.pointerId);
      });
      els.canvas.addEventListener("pointermove", function (event) {
        if (!panning) return;
        state.x = panning.x + event.clientX - panning.clientX;
        state.y = panning.y + event.clientY - panning.clientY;
        applyCanvasTransform();
      });
      function endPan() {
        panning = null;
        els.canvas.classList.remove("is-panning");
      }
      els.canvas.addEventListener("pointerup", endPan);
      els.canvas.addEventListener("pointercancel", endPan);
      els.codeDeveloperMode.addEventListener("change", function () {
        state.developerMode = els.codeDeveloperMode.checked === true;
        render();
      });
      els.codeZoomOut.addEventListener("click", function () { setCodeScale(state.codeScale - 0.1); });
      els.codeZoomIn.addEventListener("click", function () { setCodeScale(state.codeScale + 0.1); });
      els.codeZoomReset.addEventListener("click", function () { setCodeScale(1); });
      els.ingestionEntry.addEventListener("click", function (event) {
        event.stopPropagation();
        if (host.openManagement) host.openManagement();
      });
      document.addEventListener("keydown", handleDocumentKeydown);
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
        canvas: { scale: state.scale, x: state.x, y: state.y },
        code_scale: state.codeScale,
        developer_mode: state.developerMode,
        formal_capsule_count: formalCapsules().length,
        source_group_count: groups.length,
        source_relations_loading: detailsLoading(),
        verified_core_code: !!(group && cap && currentCoreCodeProjection(group, cap)),
        focused_node: activeNodeKey() || null,
      };
    }

    return {
      bind: bind,
      sync: sync,
      getState: getState,
    };
  }

  window.ReweaveCapsuleWarehouseScene = {
    create: create,
  };
})();
