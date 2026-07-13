(function () {
  "use strict";

  function taskPackStatusFromFiles(files, qualityGate) {
    files = Array.isArray(files) ? files : [];
    var hasIntent = files.indexOf("task_intent.json") >= 0;
    var hasPlan = files.indexOf("task_plan.json") >= 0;
    var hasGate = files.indexOf("quality_gate.json") >= 0;
    if (hasIntent && hasPlan && hasGate && qualityGate && qualityGate.status === "passed") {
      return "Intent ready · Plan ready · Quality gate passed · Source writes 0";
    }
    if (hasIntent && hasPlan && hasGate && qualityGate && qualityGate.status === "failed") {
      return "Intent ready · Plan ready · Quality gate failed · Source writes 0";
    }
    if (hasIntent && hasPlan && hasGate) return "Intent ready · Plan ready · Quality report available · Source writes 0";
    if (files.indexOf("task_pack.json") >= 0) {
      return "Task Pack ready · Source writes 0";
    }
    return "View provenance";
  }

  function fileClass(name) {
    if (name === "task_intent.json") return "file highlight";
    if (name === "task_plan.json") return "file highlight";
    if (name === "quality_gate.json") return "file highlight";
    if (name === "capsules_used.json") return "file highlight";
    if (name === "snippets_used.json") return "file highlight";
    if (name === "provenance.json") return "file highlight-subtle";
    return "file";
  }

  function renderFileTree(folder, files, escapeHtml) {
    var html = '<div class="folder">' + escapeHtml(folder || "new_project/") + "</div>";
    (Array.isArray(files) ? files : []).forEach(function (name) {
      html += '<div class="' + fileClass(name) + '">' + escapeHtml(name) + "</div>";
    });
    return html;
  }

  window.ReweaveRenderers = {
    taskPackStatusFromFiles: taskPackStatusFromFiles,
    renderFileTree: renderFileTree,
  };
})();
