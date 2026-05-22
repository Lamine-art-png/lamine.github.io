(function initPortalConfig() {
  const injectedApiBase = typeof window.AGROAI_API_BASE === "string"
    ? window.AGROAI_API_BASE.trim()
    : "";
  const injectedEdgeApiBase = typeof window.AGROAI_EDGE_API_BASE === "string"
    ? window.AGROAI_EDGE_API_BASE.trim()
    : "";
  const localPreview = ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname);
  const apiBase = injectedApiBase || (localPreview ? "http://127.0.0.1:8000" : "https://api.agroai-pilot.com");

  window.AGROAI_PORTAL_CONFIG = {
    apiBase,
    edgeApiBase: injectedEdgeApiBase || (localPreview ? "https://api.agroai-pilot.com" : apiBase),
    portalDomain: "https://app.agroai-pilot.com",
    liveWiseConnZoneId: "162803",
  };
})();
