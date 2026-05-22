export interface EarthDailyStatusEnv {
  EARTHDAILY_CLIENT_ID?: string;
  EARTHDAILY_SECRET?: string;
  EARTHDAILY_AUTH_URL?: string;
  EARTHDAILY_API_URL?: string;
  DEMO_MODE?: string;
  LIVE_EARTHDAILY_ENABLED?: string;
}

export function handleEarthDailyStatus(env: EarthDailyStatusEnv) {
  const credentialsConfigured = Boolean(
    env.EARTHDAILY_CLIENT_ID &&
      env.EARTHDAILY_SECRET &&
      env.EARTHDAILY_AUTH_URL &&
      env.EARTHDAILY_API_URL,
  );
  const liveEnabled = env.LIVE_EARTHDAILY_ENABLED === "true";
  const demoMode = env.DEMO_MODE !== "false";
  const liveReady = liveEnabled && credentialsConfigured;

  return {
    credentials_configured: credentialsConfigured,
    live_enabled: liveEnabled,
    demo_mode: demoMode,
    live_ready: liveReady,
    data_products: [
      "STAC imagery",
      "NDVI",
      "NDRE",
      "EVI",
      "NDMI",
      "LAI",
      "biomass",
      "weather",
      "ET forecast",
      "anomaly",
      "change detection",
      "field boundary",
    ],
    ...(liveReady ? {} : { reason: liveEnabled ? "EarthDaily credentials are incomplete." : "Live EarthDaily mode is disabled." }),
  };
}

