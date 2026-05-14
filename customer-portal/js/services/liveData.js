function asArray(payload) {
  return Array.isArray(payload) ? payload : [];
}

export async function loadLiveSnapshot(api, state) {
  const [authRes, farmsRes, talgilStatusRes, talgilSensorsRes] = await Promise.all([
    api.getAuth(),
    api.getFarms(),
    api.getTalgilStatus(),
    api.getTalgilSensorsLatest(),
  ]);

  state.live.auth = authRes;
  state.live.farms = farmsRes.ok ? asArray(farmsRes.data) : [];
  state.live.zonesByFarm = new Map();

  await Promise.all(
    state.live.farms.map(async (farm) => {
      const zonesRes = await api.getZones(farm.id);
      state.live.zonesByFarm.set(String(farm.id), zonesRes.ok ? asArray(zonesRes.data) : []);
    })
  );

  const wiseConnZones = [...state.live.zonesByFarm.values()].flat().length;
  state.live.integrations = [
    {
      id: "wiseconn-live",
      name: "WiseConn",
      description: "Live WiseConn runtime used for farm, zone, irrigation, and recommendation context.",
      status: authRes.ok && authRes.data?.authenticated ? "Live" : "Configured / auth status unavailable",
      farmsOrTargets: `${state.live.farms.length} farms`,
      zonesOrSensors: `${wiseConnZones} zones`,
      lastChecked: new Date().toISOString(),
      limitation: authRes.ok ? "Live status returned by API; customer authentication is separate from controller runtime auth." : `Status check limited: ${authRes.error}`,
    },
    {
      id: "talgil-live",
      name: "Talgil",
      description: "Live Talgil runtime status and sensor catalog endpoints when tenant context is configured.",
      status: talgilStatusRes.ok ? "Live" : "Configured / tenant context required",
      farmsOrTargets: talgilStatusRes.ok ? `${talgilStatusRes.data?.integration ? 1 : 0} targets` : "Tenant-scoped",
      zonesOrSensors: talgilSensorsRes.ok ? `${asArray(talgilSensorsRes.data?.sensors || talgilSensorsRes.data).length} sensors` : "Sensor status unavailable",
      lastChecked: new Date().toISOString(),
      limitation: talgilStatusRes.ok ? "Runtime status is live; portal does not store provider credentials." : `Status check limited: ${talgilStatusRes.error}`,
    },
  ];

  if (!state.live.selectedFarmId && state.live.farms.length) {
    state.live.selectedFarmId = String(state.live.farms[0].id);
  }

  return { authRes, farmsRes, talgilStatusRes, talgilSensorsRes };
}

export async function generateWiseConnRecommendation(api, state, overrides) {
  state.live.recommendationLoading = true;
  state.live.recommendationError = "";
  const zoneId = window.AGROAI_PORTAL_CONFIG?.liveWiseConnZoneId || "162803";
  const response = await api.recommendLiveWiseConn(zoneId, overrides);
  state.live.recommendationLoading = false;

  if (response.ok) {
    state.live.recommendation = response.data;
    return response;
  }

  state.live.recommendationError = response.error || "Live recommendation request failed.";
  return response;
}
