import { demoChain, demoFarms, demoRecommendation } from "../demoData.js";
import { escapeHtml } from "../components/dom.js";
import { metricCard, operatingChain, recommendationProofCard, table, technicalTrace } from "../components/ui.js";

function liveChainFromState(state) {
  const now = state.live.recommendation ? new Date().toISOString() : "";
  return [
    { label: "Recommended", status: state.live.recommendation ? "Complete" : "Data source pending", timestamp: now, owner: "AGRO-AI Intelligence Engine", evidence: state.live.recommendation ? "Live recommendation generated for WiseConn zone 162803." : "Generate live recommendation." },
    { label: "Scheduled", status: "Awaiting schedule", timestamp: "", owner: "Irrigation Manager", evidence: "Awaiting schedule" },
    { label: "Applied", status: "Awaiting controller execution", timestamp: "", owner: "Controller Runtime", evidence: "Awaiting controller execution" },
    { label: "Observed", status: "Awaiting field observation", timestamp: "", owner: "Field Team", evidence: "Awaiting field observation" },
    { label: "Verified", status: "Verification pending", timestamp: "", owner: "AGRO-AI Verification", evidence: "Verification pending" },
  ];
}

function demoGuideCard() {
  const steps = [
    "Connected controller environments",
    "Farm and zone context",
    "Today’s water recommendation",
    "Execution task",
    "Verification chain",
    "Reporting layer",
  ];
  return `<section class="panel-card demo-guide"><div class="section-heading"><p class="eyebrow">Demo Brief</p><h2>What this workspace is showing</h2><p>Use this guided narrative on customer, partner, and investor calls.</p></div><div class="demo-guide-grid">${steps
    .map((step, index) => `<article><span>${index + 1}</span><p>${escapeHtml(step)}</p></article>`)
    .join("")}</div></section>`;
}

export function renderCommandCenter(state) {
  const isDemo = state.session.mode === "demo";
  const zones = demoFarms.flatMap((farm) => farm.zones.map((zone) => ({ ...zone, farm: farm.name })));
  const liveZones = [...state.live.zonesByFarm.values()].flat();
  const recommendation = isDemo ? demoRecommendation : state.live.recommendation;
  const chain = isDemo ? demoChain : liveChainFromState(state);
  const decision = recommendation?.decision || recommendation?.water_decision || recommendation?.recommendation || "Generate a live recommendation to populate the decision card.";
  const confidence = recommendation?.confidence || recommendation?.confidence_score || "Data source pending";
  const dataQuality = recommendation?.dataQuality || recommendation?.data_quality || "Awaiting telemetry";
  const demoRows = zones.map((zone) => [zone.farm, zone.name, zone.controllerSource, zone.recommendation, zone.verificationStatus]);
  const liveRows = liveZones.slice(0, 8).map((zone) => ["Live WiseConn", zone.name || zone.id, "WiseConn", "Use Intelligence screen to generate", "Verification pending"]);

  return `<div class="screen-stack">
    ${isDemo ? demoGuideCard() : ""}
    <section class="hero-panel">
      <div><p class="eyebrow">Water Command Center</p><h2>${escapeHtml(decision)}</h2><p>${escapeHtml(
        isDemo ? "Demo workspace — simulated data clearly labeled for sales and partner walkthroughs." : "Live WiseConn environment available. Generate a live recommendation for zone 162803 from the Intelligence screen."
      )}</p></div>
      <div class="hero-metrics command-kpis">${metricCard("Today’s decision", decision)}${metricCard("Confidence", confidence)}${metricCard("Data quality", dataQuality)}${metricCard(
        "Source status",
        isDemo ? "Demo source active" : "Connected source live"
      )}${metricCard("Verification state", isDemo ? "Verification pending" : state.live.recommendation ? "Verification pending" : "Data source pending")}</div>
    </section>
    ${recommendationProofCard(recommendation || {}, {
      label: isDemo ? "Today’s demo recommendation" : "Live recommendation proof",
      modeBadge: isDemo ? "Demo data" : state.live.recommendation ? "Live API output" : "Data source pending",
      badgeTone: isDemo ? "warning" : state.live.recommendation ? "success" : "neutral",
    })}
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
