import { demoFarms, demoWorkspace } from "../demoData.js";
import { table } from "../components/ui.js";

export function renderFarmExplorer(state) {
  const isDemo = state.session.mode === "demo";
  const rows = isDemo
    ? demoFarms.flatMap((farm) =>
        farm.zones.map((zone) => [demoWorkspace.name, farm.name, zone.name, zone.controllerSource, zone.crop, zone.soil, zone.dataQuality, zone.recommendation, zone.verificationStatus])
      )
    : state.live.farms.flatMap((farm) => {
        const zones = state.live.zonesByFarm.get(String(farm.id)) || [];
        return zones.map((zone) => ["Live Customer Workspace", farm.name || farm.id, zone.name || zone.id, "Live WiseConn data", "Manual context required", "Manual context required", "Live endpoint dependent", "Use Intelligence screen", "Verification pending"]);
      });

  return `<div class="screen-stack"><section class="panel-card"><div class="section-heading"><p class="eyebrow">Farm Explorer</p><h2>${
    isDemo ? "Demo farms and zones" : "Live WiseConn farms and zones"
  }</h2><p>${isDemo ? "This view is embedded demo data." : "This view uses available live WiseConn farm and zone endpoints."}</p></div>${table(
    ["Organization", "Farm", "Zone", "Controller provider", "Crop", "Soil", "Data quality", "Latest recommendation", "Verification status"],
    rows,
    "No farms available",
    "Live farms will appear after the runtime returns farm context."
  )}</section></div>`;
}
