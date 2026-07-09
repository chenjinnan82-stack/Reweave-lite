(function () {
  "use strict";

  function renderArtifactList(items, shortPath, escapeHtml) {
    items = Array.isArray(items) ? items : [];
    if (!items.length) {
      return '<p class="preview-viewer-meta">No Lumo Lite artifacts in runtime state.</p>';
    }
    var html = '<p class="preview-viewer-mode"><strong>Read-only local artifacts</strong></p>';
    html += '<ul class="preview-viewer-list lumo-artifact-list">';
    items.forEach(function (item) {
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
        escapeHtml(shortPath(item.path || "")) +
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
    return html;
  }

  function renderArtifactDetail(payload, escapeHtml) {
    if (!payload || !payload.ok) return "";
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
    return html;
  }

  window.ReweaveArtifacts = {
    renderArtifactList: renderArtifactList,
    renderArtifactDetail: renderArtifactDetail,
  };
})();
