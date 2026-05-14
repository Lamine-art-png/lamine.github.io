import { demoChain, demoFarms, demoRecommendation } from "../demoData.js";
import { escapeHtml } from "../components/dom.js";
import { metricCard, operatingChain, table, technicalTrace } from "../components/ui.js";

function liveChainFromState(state) {
  const now = state.live.recommendation ? new Date().toISOString() : "";
  return [
    { label: "Recommended", status: state.live.recommendation ? "Complete" : "Pending", timestamp: now, owner: "AGRO-AI Intelligence Engine", evidence: state.live.recommendation ? "Live recommendation generated for WiseConn zone 162803." : "Generate live recommendation." },
    { label: "Scheduled", status: "Awaiting schedule", timestamp: "", owner: "Irrigation Manager", evidence: "Awaiting schedule" },
    { label: "Applied", status: "Awaiting controller execution", timestamp: "", owner: "Controller Runtime", evidence: "Awaiting controller execution" },
    { label: "Observed", status: "Awaiting field observation", timestamp: "", owner: "Field Team", evidence: "Awaiting field observation" },
    { label: "Verified", status: "Verification pending", timestamp: "", owner: "AGRO-AI Verification", evidence: "Verification pending" },
  ];
}

export function renderCommandCenter(state) {
  const isDemo = state.session.mode === "demo";
  const zones = demoFarms.flatMap((farm) => farm.zones.map((zone) => ({ ...zone, farm: farm.name })));
  const liveZones = [...state.live.zonesByFarm.values()].flat();
  const recommendation = isDemo ? demoRecommendation : state.live.recommendation;
  const chain = isDemo ? demoChain : liveChainFromState(state);

  const decision = recommendation?.decision || recommendation?.water_decision || recommendation?.recommendation || "Generate a live recommendation to populate the decision card.";
  const confidence = recommendation?.confidence || recommendation?.confidence_score || "—";
  const dataQuality = recommendation?.dataQuality || recommendation?.data_quality || "Live context dependent";

  const demoRows = zones.map((zone) => [zone.farm, zone.name, zone.controllerSource, zone.recommendation, zone.verificationStatus]);
  const liveRows = liveZones.slice(0, 8).map((zone) => ["Live WiseConn", zone.name || zone.id, "WiseConn", "Use Intelligence screen to generate", "Verification pending"]);

  return `<div class="screen-stack">
    <section class="hero-panel">
      <div><p class="eyebrow">Water Command Center</p><h2>${escapeHtml(decision)}</h2><p>${escapeHtml(
        isDemo ? demoRecommendation.sourceTraceSummary : "Live command view uses available WiseConn endpoints and the live intelligence endpoint for zone 162803."
      )}</p></div>
      <div class="hero-metrics">${metricCard("Confidence", confidence)}${metricCard("Data quality", dataQuality)}${metricCard(
        "Controller source",
        isDemo ? "Mixed demo" : "Live WiseConn"
      )}</div>
    </section>
    ${operatingChain(chain)}
    <section class="panel-card"><div class="section-heading"><p class="eyebrow">Workspace Activity</p><h2>${isDemo ? "Demo tenant operating view" : "Live WiseConn operating view"}</h2></div>${table(
      ["Farm", "Zone", "Controller", "Latest recommendation", "Verification"],
      isDemo ? demoRows : liveRows,
      "No operating rows available",
      "Live farm and zone data will appear when the runtime returns farm context."
    )}</section>
    ${technicalTrace({
      source: isDemo ? "Embedded demo tenant" : "Live API",
      sourceEntityId: isDemo ? "demo-agroai-workspace" : "WiseConn zone 162803",
      contextOrigin: isDemo ? "Demo data" : "Live WiseConn recommendation endpoint",
      controllerProvider: isDemo ? "WiseConn + Talgil demo" : "WiseConn",
      liveInputsUsed: isDemo ? demoRecommendation.liveInputsUsed : ["WiseConn zone 162803", "Live context endpoint when available"],
      manualOverridesUsed: isDemo ? demoRecommendation.manualOverridesUsed : [],
      telemetryUsed: isDemo ? ["Demo irrigation history", "Demo weather profile"] : ["Live WiseConn context"],
      warnings: isDemo ? demoRecommendation.missingInputs : [state.live.recommendationError].filter(Boolean),
    })}
  </div>`;
}
