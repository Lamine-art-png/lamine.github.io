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
  const runtime = state.demoRuntime;
  const selectedFarm = runtime?.activeFarm;
  const selectedZone = runtime?.activeZone;
  const zones = demoFarms.flatMap((farm) => farm.zones.map((zone) => ({ ...zone, farm: farm.name })));
  const liveZones = [...state.live.zonesByFarm.values()].flat();
  const recommendation = isDemo ? runtime.activeRecommendation || runtime.scenario.recommendation : state.live.recommendation;
  const chain = isDemo ? runtime.operatingChain : liveChainFromState(state);
  const decision = recommendation?.decision || recommendation?.water_decision || recommendation?.recommendation || "Generate a live recommendation to populate the decision card.";
  const confidence = recommendation?.confidence || recommendation?.confidence_score || "Data source pending";
  const dataQuality = recommendation?.dataQuality || recommendation?.data_quality || "Awaiting telemetry";
  const demoRows = zones.map((zone) => [zone.farm, zone.name, zone.controllerSource, zone.recommendation, zone.verificationStatus]);
  const liveRows = liveZones.slice(0, 8).map((zone) => ["Live WiseConn", zone.name || zone.id, "WiseConn", "Use Intelligence screen to generate", "Verification pending"]);

  return `<div class="screen-stack">
    ${isDemo ? demoGuideCard() : ""}
    ${isDemo ? `<section class="panel-card runtime-controls"><div class="section-heading"><p class="eyebrow">AGRO-AI Demo Flow</p><h2>Run the operating journey</h2><p>Scenario: ${escapeHtml(runtime.scenario.name)} · Next action: ${escapeHtml(runtime.operatingChain.find((step) => step.status !== "Complete")?.label || "Open report")}</p></div><div class="guide-steps">${[
      ["Review connected environment", "Current", "Confirm selected farm, block, and provider context."],
      ["Generate recommendation", runtime.activeRecommendation ? "Complete" : "Next", "Create the water decision and explanation."],
      ["Schedule irrigation", runtime.operatingChain[1]?.status || "Pending", "Move from recommendation to planned action."],
      ["Confirm applied water", runtime.operatingChain[2]?.status || "Pending", "Capture applied-water evidence."],
      ["Add field observation", runtime.operatingChain[3]?.status || "Pending", "Record field feedback."],
      ["Verify outcome", runtime.operatingChain[4]?.status || "Pending", "Close the proof loop."],
      ["Open report", runtime.reportSnapshots?.length ? "Complete" : "Pending", "Preview, print, or export the result."],
    ].map((step) => `<article><strong>${escapeHtml(step[0])}</strong><span>${escapeHtml(step[1])}</span><p>${escapeHtml(step[2])}</p></article>`).join("")}</div><div class="runtime-actions"><button class="button secondary" data-action="reset-demo" type="button">Reset Demo</button><button class="button secondary" data-action="start-guide" type="button">Start Guided Demo</button><button class="button primary" data-action="next-step" type="button">Next Step</button></div><label>Scenario<select id="scenario-select">${["dry_day", "rain_wait", "partial_telemetry", "mismatch", "verified_success"].map((id) => `<option value="${id}" ${runtime.scenario.id === id ? "selected" : ""}>${escapeHtml({dry_day:"Dry day, irrigation recommended", rain_wait:"Rain forecast, wait recommended", partial_telemetry:"Partial telemetry, confidence reduced", mismatch:"Planned vs applied mismatch", verified_success:"Verification completed successfully"}[id])}</option>`).join("")}</select></label></section>` : ""}
    <section class="hero-panel">
      <div><p class="eyebrow">Water Command Center</p><h2>${escapeHtml(decision)}</h2><p>${escapeHtml(
        isDemo ? "Demo workspace — simulated data clearly labeled for sales and partner walkthroughs." : "Live WiseConn environment available. Generate a live recommendation for zone 162803 from the Intelligence screen."
      )}</p></div>
      <div class="hero-metrics command-kpis">${metricCard("Farm / block", isDemo ? `${selectedFarm.name} · ${selectedZone.name}` : "WiseConn zone 162803")}${metricCard(
        "Controller source",
        isDemo ? selectedZone.controllerSource : "Live WiseConn"
      )}${metricCard("Today’s decision", decision)}${metricCard("Confidence", confidence)}${metricCard("Data quality", dataQuality)}${metricCard("Verification state", chain[4]?.status || "Verification pending")}</div>
    </section>
    ${recommendationProofCard(recommendation || {}, {
      label: isDemo ? "Today’s demo recommendation" : "Live recommendation proof",
      modeBadge: isDemo ? "Demo data" : state.live.recommendation ? "Live API output" : "Data source pending",
      badgeTone: isDemo ? "warning" : state.live.recommendation ? "success" : "neutral",
      actions: isDemo ? true : "live-disabled",
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
      sourceEntityId: isDemo ? selectedZone.id : "WiseConn zone 162803",
      contextOrigin: isDemo ? "Demo runtime state" : "Live WiseConn recommendation endpoint",
      controllerProvider: isDemo ? selectedZone.controllerSource : "WiseConn",
      liveInputsUsed: isDemo ? recommendation.liveInputsUsed || [] : ["WiseConn zone 162803", "Live context endpoint when available"],
      manualOverridesUsed: isDemo ? recommendation.manualOverridesUsed || [] : [],
      telemetryUsed: isDemo ? ["Demo irrigation history", "Demo weather profile"] : ["Live WiseConn context"],
      warnings: isDemo ? recommendation.missingInputs || [] : [state.live.recommendationError].filter(Boolean),
    })}
  </div>`;
}
