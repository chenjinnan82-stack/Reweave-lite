(function () {
  "use strict";

  function normalizeCapsule(c) {
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
      formal_version: c.formal_version === undefined ? null : c.formal_version,
      generation_eligible: c.generation_eligible === true,
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

  function sourceLabel(cap) {
    if (!cap) return "";
    if (typeof cap.source === "string" && cap.source) return cap.source;
    if (cap.source_box && cap.source_box.label) return cap.source_box.label;
    return cap.source_id || "";
  }

  function serial(cap) {
    if (cap && cap.serial) return cap.serial;
    if (!cap || !cap.id) return "00";
    var h = 0;
    for (var i = 0; i < cap.id.length; i += 1) {
      h = (h * 31 + cap.id.charCodeAt(i)) % 997;
    }
    return ("0" + h.toString(16)).slice(-2).toUpperCase();
  }

  function tagBits(cap) {
    var tags = (cap && cap.tags ? cap.tags : []).slice();
    if (isMetadataCapsule(cap)) tags.unshift("metadata-only");
    if (cap && cap.origin === "manual_promote") tags.unshift("manual promote");
    if (cap && cap.origin === "lumo_lite_capsule_warehouse") tags.unshift("read-only receipt");
    return tags;
  }

  function previewText(cap) {
    var lines = [];
    var isLumoLiteReceipt = cap && cap.origin === "lumo_lite_capsule_warehouse";
    if (isMetadataCapsule(cap)) {
      if (cap.risk) lines.push("risk: " + cap.risk);
      if (cap.content_mode) lines.push("content_mode: " + cap.content_mode);
      if (cap.status && cap.status !== "active") lines.push("status: " + cap.status);
      if (cap.content_enrichment && cap.content_enrichment.status === "enriched") {
        lines.push("Content preview available · Snippets " + (cap.content_enrichment.snippet_count || 0));
      }
      if (cap.lumo_lite_receipt && typeof cap.lumo_lite_receipt === "object") {
        lines.push("lumo_lite_receipt:");
        ["warehouse_status", "invocation_status", "assembly_status", "reason", "trace_path"].forEach(function (key) {
          var val = cap.lumo_lite_receipt[key];
          if (val != null && val !== "") lines.push("  " + key + ": " + val);
        });
        (cap.lumo_lite_receipt.evidence_package_paths || []).slice(0, 3).forEach(function (path) {
          lines.push("  evidence: " + path);
        });
        (cap.lumo_lite_receipt.blocked_reasons || []).slice(0, 3).forEach(function (reason) {
          lines.push("  blocked: " + reason);
        });
      }
      if (!isLumoLiteReceipt && cap.lineage && typeof cap.lineage === "object") {
        lines.push("lineage:");
        Object.keys(cap.lineage).forEach(function (key) {
          var val = cap.lineage[key];
          if (val != null && val !== "") lines.push("  " + key + ": " + val);
        });
      }
      if (cap.snippet && cap.snippet.description) lines.push("", String(cap.snippet.description));
    }
    var body = ((cap && cap.preview) || []).join("\n");
    if (lines.length) {
      if (body && !isLumoLiteReceipt) lines.push("", body);
      return lines.join("\n");
    }
    return body;
  }

  window.ReweaveCapsuleReader = {
    normalizeCapsule: normalizeCapsule,
    isMetadataCapsule: isMetadataCapsule,
    sourceLabel: sourceLabel,
    serial: serial,
    tagBits: tagBits,
    previewText: previewText,
  };
})();
