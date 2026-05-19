(function initPortalConfig() {
  const injectedApiBase = typeof window.AGROAI_API_BASE === "string"
    ? window.AGROAI_API_BASE.trim()
    : "";
  const apiBase = injectedApiBase || "https://api.agroai-pilot.com";

  window.AGROAI_PORTAL_CONFIG = {
    apiBase,
    portalDomain: "https://app.agroai-pilot.com",
    liveWiseConnZoneId: "162803",
  };
})();
