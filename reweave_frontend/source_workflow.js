(function () {
  "use strict";

  function normalizeSource(source) {
    if (!source || !source.id) return null;
    return {
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
  }

  function sourceScanLabel(src, state) {
    state = state || {};
    if (state.preparing) return "Preparing...";
    if (state.scanning) return "Scanning...";
    if (state.verifying) return "Verifying...";
    if (state.previewing) return "Previewing...";
    if (state.reviewing) return "Reviewing...";
    if (src.status === "read_only" || src.scan_status === "read_only") return "Read-only";
    if (src.warehouse_status === "promoted") {
      var n = src.promoted_capsule_count;
      var base = n ? n + " capsules" : "Ready";
      return state.lunaReuse ? base + " · Suggested by Luna" : base;
    }
    var scan = src.scan_status || "not_scanned";
    if (scan === "scanned") return "Scanned";
    if (scan === "failed") return "Failed";
    return "Not scanned";
  }

  window.ReweaveSourceWorkflow = {
    normalizeSource: normalizeSource,
    sourceScanLabel: sourceScanLabel,
  };
})();
