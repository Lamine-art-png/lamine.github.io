import { demoAgroAiExplainer, demoAiDecisionPipeline, demoChain, demoFarms, demoInstitutionalKpis, demoReconciliationRows, demoRecommendation, demoTransformation } from "../demoData.js";
import { escapeHtml } from "../components/dom.js";
import { agroAiExplainer, aiDecisionPipeline, intelligenceTransformationPanel, metricCard, operatingChain, recommendationProofCard, reconciliationSummary, roiComplianceStrip, table, technicalTrace } from "../components/ui.js";

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
  return `<section class="panel-card demo-guide"><div class="section-heading"><p class="eyebrow">Decision Readout</p><h2>How to read the workspace</h2><p>Use this narrative to connect source signals, recommendation, execution, verification, and reporting.</p></div><div class="demo-guide-grid">${steps
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
  const institutionalKpis = isDemo ? runtime.institutionalKpis || demoInstitutionalKpis : {
    waterSavedYtd: "Awaiting live ROI",
    waterSavingsRate: "Live baseline pending",
    dollarValueAvoided: "Awaiting live value",
    pricingAssumption: "backend ROI endpoint",
    compliancePosture: "Auth-ready",
    evidenceCompleteness: "Live evidence pending",
    portfolioCoverage: liveZones.length ? `Live WiseConn / ${liveZones.length} zones` : "Live workspace pending",
    freshness: "Updated when live ROI endpoint is enabled",
    assumptionLabel: "Live ROI endpoint pending",
  };
  const chain = isDemo ? runtime.operatingChain : liveChainFromState(state);
  const decision = recommendation?.decision || recommendation?.water_decision || recommendation?.recommendation || "Generate a live recommendation to populate the decision card.";
  const confidence = recommendation?.confidence || recommendation?.confidence_score || "Recommendation ready";
  const dataQuality = recommendation?.dataQuality || recommendation?.data_quality || "AI context assembled";
  const livePipeline = [
    { stage: "01", title: "Ingest available signals", status: "Connected source live", items: ["WiseConn zone 162803", "Manual overrides in memory", "Weather/context endpoint when available"], explanation: "Live mode uses available connected source data and does not claim unavailable provider targets." },
    { stage: "02", title: "Normalize field context", status: "Target selection pending", items: ["Authorized workspace", "Zone context", "Optional crop and soil overrides"], explanation: "Backend organization selection will expand live customer context after auth endpoints are enabled." },
    { stage: "03", title: "Reconcile sources", status: state.live.recommendation ? "Reconciled" : "Data source pending", items: ["WiseConn context", "Override checks", "Warnings surfaced safely"], explanation: "AGRO-AI reconciles live inputs returned by the API before showing a recommendation." },
    { stage: "04", title: "Generate decision", status: state.live.recommendation ? "Recommendation ready" : "Target selection pending", items: ["Run Live WiseConn Recommendation", "Review output", "Plan verification"], explanation: "Live execution capture still requires backend execution endpoints." },
  ];
  const liveTransformation = {
    rawSignals: ["WiseConn zone context", "Optional in-memory overrides", "Live API warnings"],
    reconciliation: ["normalize returned fields", "surface missing inputs", "preserve source trace"],
    cleanAction: state.live.recommendation ? ["Live recommendation output", "Review schedule", "Verification required"] : ["Run live recommendation", "Review AGRO-AI output", "Plan verification"],
  };
  const liveReconciliationRows = [
    ["WiseConn", "Zone 162803 context", state.live.recommendation ? "Live recommendation returned" : "Live recommendation not yet requested", state.live.recommendation ? "Matched" : "Pending target"],
    ["Talgil", "Runtime status only; no selected production targets", "Available integration, no target selected", "Pending target"],
    ["Manual overrides", "Optional crop, soil, ETo, rain, observation", "Kept in memory for recommendation call", "Matched"],
    ["AGRO-AI reconciled view", state.live.recommendation ? "Recommendation output available" : "Awaiting live recommendation", state.live.recommendation ? "Decision ready with verification required" : "Run live API call to generate", state.live.recommendation ? "Verified" : "Pending target"],
  ];
  const pipeline = isDemo ? runtime.aiDecisionPipeline || demoAiDecisionPipeline : livePipeline;
  const transformation = isDemo ? runtime.intelligenceTransformation || demoTransformation : liveTransformation;
  const reconciliationRows = isDemo ? runtime.reconciliationRows || demoReconciliationRows : liveReconciliationRows;
  const explainerItems = isDemo ? runtime.agroAiExplainer || demoAgroAiExplainer : demoAgroAiExplainer;
  const demoRows = zones.map((zone) => [zone.farm, zone.name, zone.controllerSource, zone.recommendation, zone.verificationStatus]);
  const liveRows = liveZones.slice(0, 8).map((zone) => ["Live WiseConn", zone.name || zone.id, "WiseConn", "Use Intelligence screen to generate", "Verification pending"]);

  return `<div class="screen-stack">
    ${roiComplianceStrip(institutionalKpis, { isDemo })}
    ${aiDecisionPipeline(pipeline)}
    <div class="command-insight-grid">${agroAiExplainer(explainerItems)}${intelligenceTransformationPanel(transformation)}</div>
    ${reconciliationSummary(reconciliationRows)}
    ${isDemo ? demoGuideCard() : ""}
    ${isDemo ? `<section class="panel-card runtime-controls"><div class="section-heading"><p class="eyebrow">Operating Journey</p><h2>Run the operating journey</h2><p>Scenario: ${escapeHtml(runtime.scenario.name)} · Next action: ${escapeHtml(runtime.operatingChain.find((step) => step.status !== "Complete")?.label || "Open report")}</p></div><div class="guide-steps">${[
      ["Review connected environment", "Current", "Confirm selected farm, block, and provider context."],
      ["Generate recommendation", runtime.activeRecommendation ? "Complete" : "Next", "Generate the block-level recommendation and confidence readout."],
      ["Schedule irrigation", runtime.operatingChain[1]?.status || "Pending", "Move from recommendation ready to scheduled action."],
      ["Confirm applied water", runtime.operatingChain[2]?.status || "Pending", "Capture applied-water evidence."],
      ["Add field observation", runtime.operatingChain[3]?.status || "Pending", "Record field feedback."],
      ["Verify outcome", runtime.operatingChain[4]?.status || "Pending", "Close the verification evidence loop."],
      ["Open report", runtime.reportSnapshots?.length ? "Complete" : "Pending", "Preview, print, or export the result."],
    ].map((step) => `<article><strong>${escapeHtml(step[0])}</strong><span>${escapeHtml(step[1])}</span><p>${escapeHtml(step[2])}</p></article>`).join("")}</div><div class="runtime-actions"><button class="button secondary" data-action="reset-demo" type="button">Reset Demo</button><button class="button secondary" data-action="start-guide" type="button">Start Guided Demo</button><button class="button primary" data-action="next-step" type="button">Next Step</button></div><label>Scenario<select id="scenario-select">${["dry_day", "rain_wait", "partial_telemetry", "mismatch", "verified_success"].map((id) => `<option value="${id}" ${runtime.scenario.id === id ? "selected" : ""}>${escapeHtml({dry_day:"Dry day, irrigation recommended", rain_wait:"Rain forecast, wait recommended", partial_telemetry:"Partial telemetry, confidence reduced", mismatch:"Planned vs applied mismatch", verified_success:"Verification completed successfully"}[id])}</option>`).join("")}</select></label></section>` : ""}
    <section class="hero-panel">
      <div><p class="eyebrow">Water Command Center</p><h2>${escapeHtml(decision)}</h2><p>${escapeHtml(
        isDemo ? "AI context assembled from controller, weather, soil, and field signals for a verified irrigation decision." : "Live WiseConn environment available. Generate a live recommendation for zone 162803 from the Intelligence screen."
      )}</p></div>
      <div class="hero-metrics command-kpis">${metricCard("Farm / block", isDemo ? `${selectedFarm.name} · ${selectedZone.name}` : "WiseConn zone 162803")}${metricCard(
        "Controller source",
        isDemo ? selectedZone.controllerSource : "Live WiseConn"
      )}${metricCard("Today’s decision", decision)}${metricCard("Confidence", confidence)}${metricCard("Data quality", dataQuality)}${metricCard("Verification state", chain[4]?.status || "Verification pending")}</div>
    </section>
    ${recommendationProofCard(recommendation || {}, {
      label: isDemo ? "Today’s recommendation" : "Live recommendation proof",
      modeBadge: isDemo ? "Demo-mode assumptions" : state.live.recommendation ? "Live API output" : "Recommendation ready",
      badgeTone: isDemo ? "warning" : state.live.recommendation ? "success" : "neutral",
      actions: isDemo ? true : "live-disabled",
    })}
    ${operatingChain(chain)}
    <section class="panel-card"><div class="section-heading"><p class="eyebrow">Workspace Activity</p><h2>${isDemo ? "Recent activity across portfolio" : "Live WiseConn operating view"}</h2></div>${table(
      ["Farm", "Zone", "Controller", "Latest recommendation", "Verification"],
      isDemo ? demoRows : liveRows,
      "No operating rows available",
      "Live farm and zone data will appear when the runtime returns farm context."
    )}</section>
    ${technicalTrace({
      source: isDemo ? "Embedded tenant workspace" : "Live API",
      sourceEntityId: isDemo ? selectedZone.id : "WiseConn zone 162803",
      contextOrigin: isDemo ? "AI context assembled" : "Live WiseConn recommendation endpoint",
      controllerProvider: isDemo ? selectedZone.controllerSource : "WiseConn",
      liveInputsUsed: isDemo ? recommendation.liveInputsUsed || [] : ["WiseConn zone 162803", "Live context endpoint when available"],
      manualOverridesUsed: isDemo ? recommendation.manualOverridesUsed || [] : [],
      telemetryUsed: isDemo ? ["Controller irrigation history", "Weather demand profile"] : ["Live WiseConn context"],
      warnings: isDemo ? recommendation.missingInputs || [] : [state.live.recommendationError].filter(Boolean),
    })}
  </div>`;
}
