import { demoFarms, demoWorkspace } from "../demoData.js";
import { table } from "../components/ui.js";
import { escapeHtml } from "../components/dom.js";

export function renderFarmExplorer(state) {
  const isDemo = state.session.mode === "demo";
  const runtime = state.demoRuntime;
  const rows = isDemo
    ? demoFarms.flatMap((farm) =>
        farm.zones.map((zone) => [demoWorkspace.name, farm.name, zone.name, zone.controllerSource, zone.crop, zone.soil, zone.dataQuality, zone.recommendation, zone.verificationStatus])
      )
    : state.live.farms.flatMap((farm) => {
        const zones = state.live.zonesByFarm.get(String(farm.id)) || [];
        return zones.map((zone) => ["Live Customer Workspace", farm.name || farm.id, zone.name || zone.id, "Live WiseConn data", "Manual context required", "Manual context required", "Live endpoint dependent", "Use Intelligence screen", "Verification pending"]);
      });

  const selectors = isDemo
    ? `<section class="panel-card runtime-selector"><div class="section-heading"><p class="eyebrow">Active field context</p><h2>${escapeHtml(runtime.activeFarm.name)} · ${escapeHtml(runtime.activeZone.name)}</h2><p>Select the farm and block used across Water Command Center, Reports, Integrations, and Audit Log.</p></div><div class="selector-grid"><label>Farm<select id="farm-select-runtime">${demoFarms.map((farm) => `<option value="${escapeHtml(farm.id)}" ${farm.id === runtime.activeFarm.id ? "selected" : ""}>${escapeHtml(farm.name)}</option>`).join("")}</select></label><label>Zone / block<select id="zone-select-runtime">${runtime.activeFarm.zones.map((zone) => `<option value="${escapeHtml(zone.id)}" ${zone.id === runtime.activeZone.id ? "selected" : ""}>${escapeHtml(zone.name)}</option>`).join("")}</select></label></div></section>`
    : "";

  return `<div class="screen-stack">${selectors}<section class="panel-card"><div class="section-heading"><p class="eyebrow">Farm Explorer</p><h2>${
    isDemo ? "Evaluation farms and zones" : "Live WiseConn farms and zones"
  }</h2><p>${isDemo ? "Selected farm and zone drive the evaluation runtime and sample package context." : "This view uses available live WiseConn farm and zone endpoints."}</p></div>${table(
    ["Organization", "Farm", "Zone", "Controller provider", "Crop", "Soil", "Data quality", "Latest recommendation", "Verification status"],
    rows,
    "No farms available",
    "Live farms will appear after the runtime returns farm context."
  )}</section></div>`;
}
