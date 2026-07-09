(function () {
  "use strict";

  function parseBridgeJson(raw) {
    if (!raw) return null;
    if (typeof raw === "object") return raw;
    try {
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function desktopCapability(state, name) {
    if (!state) return false;
    if (Object.prototype.hasOwnProperty.call(state, name)) {
      return state[name] === true;
    }
    return false;
  }

  function isLumoLiteState(state) {
    return !!(state && (state.engine === "lumo_lite" || state.backend === "lumo_lite" || state.lumoLiteMode));
  }

  function isLumoLiteReadOnly(state, fallbackData) {
    return !!(isLumoLiteState(state) || (fallbackData && fallbackData.lumoLiteMode));
  }

  function canBuildTaskPackPreview(state, fallbackData) {
    return isLumoLiteReadOnly(state, fallbackData) && desktopCapability(state, "canGeneratePreview");
  }

  window.ReweaveBridgeHelpers = {
    parseBridgeJson: parseBridgeJson,
    desktopCapability: desktopCapability,
    isLumoLiteState: isLumoLiteState,
    isLumoLiteReadOnly: isLumoLiteReadOnly,
    canBuildTaskPackPreview: canBuildTaskPackPreview,
  };
})();
