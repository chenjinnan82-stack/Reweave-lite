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
    var zh = state.locale === "zh";
    if (state.preparing) return zh ? "准备中…" : "Preparing…";
    if (state.scanning) return zh ? "扫描中…" : "Scanning…";
    if (state.verifying) return zh ? "验证中…" : "Verifying…";
    if (state.previewing) return zh ? "预览中…" : "Previewing…";
    if (state.reviewing) return zh ? "复核中…" : "Reviewing…";
    if (src.status === "read_only" || src.scan_status === "read_only") return zh ? "只读" : "Read-only";
    if (src.warehouse_status === "promoted") {
      var n = src.promoted_capsule_count;
      var base = n ? n + (zh ? " 个胶囊" : " capsules") : zh ? "就绪" : "Ready";
      return state.lunaReuse ? base + (zh ? " · Luna 建议" : " · Suggested by Luna") : base;
    }
    var scan = src.scan_status || "not_scanned";
    if (scan === "scanned") return zh ? "已扫描" : "Scanned";
    if (scan === "failed") return zh ? "失败" : "Failed";
    return zh ? "未扫描" : "Not scanned";
  }

  window.ReweaveSourceWorkflow = {
    normalizeSource: normalizeSource,
    sourceScanLabel: sourceScanLabel,
  };
})();
