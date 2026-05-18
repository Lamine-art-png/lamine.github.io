(function initPortalConfig() {
  const injectedApiBase = window.AGROAI_API_BASE;
  const apiBase = injectedApiBase || "https://api.agroai-pilot.com";

  window.AGROAI_PORTAL_CONFIG = {
    apiBase,
    portalDomain: "https://app.agroai-pilot.com",
    liveWiseConnZoneId: "162803",
  };
})();
