import { demoRecommendation } from "../demoData.js";
import { escapeHtml, formatValue } from "../components/dom.js";
import { badge, metricCard, technicalTrace } from "../components/ui.js";

function extractRecommendation(result, isDemo) {
  if (isDemo) return demoRecommendation;
  if (!result) return null;
  return {
    decision: result.decision || result.water_decision || result.recommendation || result.action || "Live recommendation returned",
    timing: result.timing || result.start_time || result.recommended_start || "See source trace",
    duration: result.duration || result.duration_minutes || result.duration_min || result.irrigation_minutes || "See recommendation details",
    depth: result.depth || result.depth_mm || result.recommended_depth_mm || "See recommendation details",
    confidence: result.confidence || result.confidence_score || "—",
    dataQuality: result.data_quality || result.dataQuality || "Live context dependent",
    keyDrivers: result.key_drivers || result.drivers || result.reasons || [],
    sourceTraceSummary: result.source_trace_summary || result.trace_summary || "Live recommendation assembled by AGRO-AI Intelligence Engine.",
    liveInputsUsed: result.live_inputs_used || result.inputs_used || [],
    manualOverridesUsed: result.manual_overrides_used || result.overrides_used || [],
    missingInputs: result.missing_inputs || result.warnings || [],
    executionTask: result.execution_task || result.task || "Schedule review required before controller execution.",
    verificationPlan: result.verification_plan || "Verify controller-applied event and request field observation.",
  };
}

export function renderIntelligence(state) {
  const isDemo = state.session.mode === "demo";
  const rec = extractRecommendation(state.live.recommendation, isDemo);
  const zoneId = window.AGROAI_PORTAL_CONFIG?.liveWiseConnZoneId || "162803";

  const decisionPanel = rec
    ? `<section class="decision-panel"><div><p class="eyebrow">Water Decision</p><h2>${escapeHtml(rec.decision)}</h2><p>${escapeHtml(rec.sourceTraceSummary)}</p></div><div class="hero-metrics">${metricCard(
        "Timing",
        rec.timing
      )}${metricCard("Duration", rec.duration)}${metricCard("Depth", rec.depth)}${metricCard("Confidence", rec.confidence)}${metricCard(
        "Data quality",
        rec.dataQuality
      )}</div><div class="two-column"><article><h3>Key drivers</h3><ul>${(rec.keyDrivers || [])
        .map((item) => `<li>${escapeHtml(item)}</li>`)
        .join("") || '<li class="muted">No drivers returned yet.</li>'}</ul></article><article><h3>Execution task</h3><p>${escapeHtml(
        rec.executionTask
      )}</p><h3>Verification plan</h3><p>${escapeHtml(rec.verificationPlan)}</p></article></div></section>`
    : `<section class="decision-panel empty"><p class="eyebrow">Live Intelligence</p><h2>Generate a live WiseConn recommendation</h2><p>Live mode calls POST /v1/intelligence/recommend/live/wiseconn/${escapeHtml(
        zoneId
      )}. Optional overrides stay in-memory and are not stored in browser localStorage.</p></section>`;

  return `<div class="screen-stack">
    <section class="panel-card"><div class="section-heading"><p class="eyebrow">Intelligence Engine</p><h2>${
      isDemo ? "Demo recommendation context" : `Live WiseConn recommendation for zone ${escapeHtml(zoneId)}`
    }</h2></div>
      ${isDemo ? badge("Demo data", "warning") : badge("Live endpoint", "success")}
      ${!isDemo ? `<form id="live-recommendation-form" class="override-grid">
        <label>Crop type<input name="crop_type" type="text" placeholder="e.g. almonds" /></label>
        <label>Soil type<input name="soil_type" type="text" placeholder="e.g. silt loam" /></label>
        <label>Irrigation method<input name="irrigation_method" type="text" placeholder="e.g. drip" /></label>
        <label>ETo<input name="eto" type="number" step="0.01" placeholder="mm/day" /></label>
        <label>Rain forecast<input name="rain_forecast" type="number" step="0.01" placeholder="mm" /></label>
        <label>Field observation<textarea name="field_observation" placeholder="Optional field note"></textarea></label>
        <button class="button primary" type="submit">Generate live recommendation</button>
      </form>` : ""}
      ${state.live.recommendationLoading ? '<p class="loading-text">Generating live recommendation…</p>' : ""}
      ${state.live.recommendationError ? `<p class="error-text">${escapeHtml(state.live.recommendationError)}</p>` : ""}
    </section>
    ${decisionPanel}
    <section class="panel-card"><div class="section-heading"><p class="eyebrow">Inputs</p><h2>Context used by the decision</h2></div><div class="three-column"><article><h3>Live inputs used</h3><p>${escapeHtml(
      formatValue(rec?.liveInputsUsed)
    )}</p></article><article><h3>Manual overrides used</h3><p>${escapeHtml(formatValue(rec?.manualOverridesUsed))}</p></article><article><h3>Missing inputs</h3><p>${escapeHtml(
      formatValue(rec?.missingInputs)
    )}</p></article></div></section>
    ${technicalTrace({
      source: isDemo ? "Demo recommendation" : "POST live WiseConn recommendation",
      sourceEntityId: isDemo ? "block-a-north" : zoneId,
      contextOrigin: isDemo ? "Embedded demo context" : "Live context endpoints + manual overrides",
      controllerProvider: isDemo ? "WiseConn demo connection" : "WiseConn",
      liveInputsUsed: rec?.liveInputsUsed || [],
      manualOverridesUsed: rec?.manualOverridesUsed || [],
      telemetryUsed: ["Controller runtime", "Weather/context normalization"],
      warnings: rec?.missingInputs || [],
    })}
  </div>`;
}
