import { demoAiDecisionPipeline, demoChain, demoRecommendation } from "../demoData.js";
import { escapeHtml, formatValue } from "../components/dom.js";
import { aiDecisionPipeline, badge, operatingChain, recommendationProofCard, technicalTrace } from "../components/ui.js";

function extractRecommendation(result, isDemo) {
  if (isDemo) return result || demoRecommendation;
  if (!result) return null;
  return {
    decision: result.decision || result.water_decision || result.recommendation || result.action || "Live recommendation returned",
    timing: result.timing || result.start_time || result.recommended_start || "See source trace",
    duration: result.duration || result.duration_minutes || result.duration_min || result.irrigation_minutes || "See recommendation details",
    depth: result.depth || result.depth_mm || result.recommended_depth_mm || "See recommendation details",
    confidence: result.confidence || result.confidence_score || "Data source pending",
    dataQuality: result.data_quality || result.dataQuality || "Live context dependent",
    keyDrivers: result.key_drivers || result.drivers || result.reasons || [],
    sourceTraceSummary: result.source_trace_summary || result.trace_summary || "Live recommendation assembled by AGRO-AI Intelligence Engine.",
    liveInputsUsed: result.live_inputs_used || result.inputs_used || [],
    manualOverridesUsed: result.manual_overrides_used || result.overrides_used || [],
    missingInputs: result.missing_inputs || result.warnings || [],
    executionTask: result.execution_task || result.task || "Schedule review required before controller execution.",
    verificationPlan: result.verification_plan || "Verification required after controller execution and field observation.",
  };
}

function liveChain(state) {
  return [
    { label: "Recommended", status: state.live.recommendation ? "Complete" : "Data source pending", timestamp: state.live.recommendation ? new Date().toISOString() : "", owner: "AGRO-AI Intelligence Engine", evidence: state.live.recommendation ? "Live recommendation generated from WiseConn context." : "Generate live recommendation." },
    { label: "Scheduled", status: "Awaiting schedule", owner: "Irrigation Manager", evidence: "Awaiting schedule" },
    { label: "Applied", status: "Awaiting controller execution", owner: "Controller Runtime", evidence: "Awaiting controller execution" },
    { label: "Observed", status: "Awaiting field observation", owner: "Field Team", evidence: "Awaiting field observation" },
    { label: "Verified", status: "Verification pending", owner: "AGRO-AI Verification", evidence: "Verification pending" },
  ];
}

export function renderIntelligence(state) {
  const isDemo = state.session.mode === "demo";
  const runtime = state.demoRuntime;
  const rec = extractRecommendation(isDemo ? runtime.activeRecommendation || runtime.scenario.recommendation : state.live.recommendation, isDemo);
  const zoneId = window.AGROAI_PORTAL_CONFIG?.liveWiseConnZoneId || "162803";
  const emptyLive = `<section class="decision-panel empty"><p class="eyebrow">Live Intelligence</p><h2>Generate a live WiseConn recommendation</h2><p>Live mode calls POST /v1/intelligence/recommend/live/wiseconn/${escapeHtml(
    zoneId
  )}. Optional overrides stay in-memory and are not stored in browser localStorage.</p></section>`;

  return `<div class="screen-stack">
    <section class="panel-card intelligence-engine-card"><div class="section-heading"><p class="eyebrow">Intelligence Engine</p><h2>Intelligence Engine</h2><p>Live context, normalization, reconciliation, recommendation, and verification planning.</p><p class="muted">${
      isDemo ? `${runtime.activeFarm.name} · ${runtime.activeZone.name} · Scenario: ${escapeHtml(runtime.scenario.name)}` : `Live WiseConn API call target: zone ${escapeHtml(zoneId)}`
    }</p></div>
      <div class="runtime-actions">${isDemo ? `${badge("Demo-mode assumptions", "warning")} <button class="button primary" data-action="generate-demo-recommendation" type="button">Run AI analysis</button>` : `${badge("Connected source live", "success")} <span class="muted">Run Live WiseConn Recommendation calls POST /v1/intelligence/recommend/live/wiseconn/${escapeHtml(zoneId)}.</span>`}</div>
      ${!isDemo ? `<form id="live-recommendation-form" class="override-grid">
        <label>Crop type<input name="crop_type" type="text" placeholder="e.g. almonds" /></label>
        <label>Soil type<input name="soil_type" type="text" placeholder="e.g. silt loam" /></label>
        <label>Irrigation method<input name="irrigation_method" type="text" placeholder="e.g. drip" /></label>
        <label>ETo<input name="eto" type="number" step="0.01" placeholder="mm/day" /></label>
        <label>Rain forecast<input name="rain_forecast" type="number" step="0.01" placeholder="mm" /></label>
        <label>Field observation<textarea name="field_observation" placeholder="Optional field note"></textarea></label>
        <button class="button primary" type="submit">Run Live WiseConn Recommendation</button>
      </form>` : ""}
      ${state.live.recommendationLoading ? '<p class="loading-text">Generating live recommendation…</p>' : ""}
      ${state.live.recommendationError ? `<p class="error-text">${escapeHtml(state.live.recommendationError)}</p>` : ""}
    </section>
    ${aiDecisionPipeline(demoAiDecisionPipeline, { compact: true })}
    ${rec ? recommendationProofCard(rec, { label: isDemo ? "Recommendation proof" : "Live recommendation proof", modeBadge: isDemo ? "Demo-mode assumptions" : "Live API output", badgeTone: isDemo ? "warning" : "success", actions: isDemo ? true : "live-disabled" }) : emptyLive}
    ${operatingChain(isDemo ? runtime.operatingChain : liveChain(state))}
    <section class="panel-card"><div class="section-heading"><p class="eyebrow">Inputs</p><h2>Context used by the decision</h2></div><div class="three-column"><article><h3>Live inputs used</h3><p>${escapeHtml(
      formatValue(rec?.liveInputsUsed, "Source reconciliation pending")
    )}</p></article><article><h3>Manual overrides used</h3><p>${escapeHtml(formatValue(rec?.manualOverridesUsed, "None provided"))}</p></article><article><h3>Missing inputs</h3><p>${escapeHtml(
      formatValue(rec?.missingInputs, "None reported")
    )}</p></article></div></section>
    ${technicalTrace({
      source: isDemo ? "Recommendation proof" : "POST live WiseConn recommendation",
      sourceEntityId: isDemo ? runtime.activeZone.id : zoneId,
      contextOrigin: isDemo ? "AI context assembled" : "Live context endpoints + manual overrides",
      controllerProvider: isDemo ? runtime.activeZone.controllerSource : "WiseConn",
      liveInputsUsed: rec?.liveInputsUsed || [],
      manualOverridesUsed: rec?.manualOverridesUsed || [],
      telemetryUsed: ["Controller runtime", "Weather/context normalization"],
      warnings: rec?.missingInputs || [],
    })}
  </div>`;
}
