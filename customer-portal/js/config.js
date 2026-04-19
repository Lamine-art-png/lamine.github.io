(function initPortalConfig() {
  const params = new URLSearchParams(window.location.search);
  const queryApiBase = params.get("apiBase");
  const storedApiBase = window.localStorage.getItem("AGROAI_API_BASE");
  const injectedApiBase = window.AGROAI_API_BASE;

  const apiBase =
    queryApiBase ||
    storedApiBase ||
    injectedApiBase ||
    "https://api.agroai-pilot.com";

  window.AGROAI_PORTAL_CONFIG = {
    apiBase,
  };
})();
