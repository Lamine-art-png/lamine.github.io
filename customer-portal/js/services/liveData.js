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
  const talgilTargets = talgilStatusRes.ok && talgilStatusRes.data?.integration ? 1 : 0;
  const talgilSensors = talgilSensorsRes.ok ? asArray(talgilSensorsRes.data?.sensors || talgilSensorsRes.data).length : 0;
  state.live.integrations = [
    {
      id: "wiseconn-live",
      name: "WiseConn",
      description: "Live WiseConn environment available for farm, zone, irrigation, and recommendation context.",
      status: authRes.ok && authRes.data?.authenticated ? "Connected source live" : "Data source pending",
      connectionHealth: authRes.ok ? "Live WiseConn environment available" : "Awaiting telemetry",
      farmsOrTargets: `${state.live.farms.length} farms`,
      zonesOrSensors: `${wiseConnZones} zones`,
      reads: "Farms, zones, irrigation history, and live context",
      generates: "Recommendations, execution tasks, and verification evidence",
      lastChecked: new Date().toISOString(),
      limitation: authRes.ok ? "Customer portal auth is separate from controller runtime auth." : "Data source pending while the runtime status check completes.",
    },
    {
      id: "talgil-live",
      name: "Talgil",
      description: "Live Talgil runtime status and sensor catalog endpoints when tenant context is configured.",
      status: talgilStatusRes.ok ? "Connected source live" : "Data source pending",
      connectionHealth: talgilStatusRes.ok && talgilTargets === 0 ? "Talgil runtime is reachable. No production targets are currently selected for this workspace." : talgilStatusRes.ok ? "Connected source live" : "Awaiting telemetry",
      farmsOrTargets: talgilStatusRes.ok ? `${talgilTargets} targets` : "No targets selected",
      zonesOrSensors: talgilSensorsRes.ok ? `${talgilSensors} sensors` : "Awaiting telemetry",
      reads: "Controller targets, sensor catalog, telemetry, and event context",
      generates: "Normalized context for recommendations, reports, and verification workflows",
      lastChecked: new Date().toISOString(),
      limitation: talgilStatusRes.ok && talgilTargets === 0 ? "Talgil runtime is reachable. No production targets are currently selected for this workspace." : "Portal does not store provider credentials; secure backend credential endpoints are required.",
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
