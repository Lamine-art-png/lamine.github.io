import { escapeHtml } from "../components/dom.js";
import { badge, bar, jsonDetails, list, panel, skeletonRows } from "../components/earthdailyPanels/index.js";

function unwrap(envelope) {
  return envelope?.data || envelope || {};
}

function workflow(state) {
  return unwrap(state.earthdaily.workflow);
}

function modeBadge(state) {
  const status = unwrap(state.earthdaily.providerStatus);
  const live = status.live_enabled && status.live_ready;
  return badge(live ? "live" : "demo", live ? "success" : "warning");
}

function fieldCard(state) {
  const data = workflow(state);
  const raw = data.earthdaily_raw_input;
  const field = raw?.field || unwrap(state.earthdaily.sampleField);
  const freshness = raw?.metadata?.data_freshness || field?.freshness || "pending";
  return `<article class="earthdaily-field-card">
    <h4>${escapeHtml(field?.field_name || "Madera Almonds Block 12")}</h4>
    <dl class="definition-grid">
      <div><dt>Crop</dt><dd>${escapeHtml(field?.crop_type || "almonds")}</dd></div>
      <div><dt>Acreage</dt><dd>${escapeHtml(field?.acreage || "120.4")}</dd></div>
      <div><dt>Region</dt><dd>${escapeHtml(field?.region || "Madera County, California")}</dd></div>
      <div><dt>Freshness</dt><dd>${escapeHtml(freshness)}</dd></div>
    </dl>
    ${modeBadge(state)}
  </article>`;
}

function scatteredPanel(state) {
  if (state.earthdaily.loading) return skeletonRows(8);
  const raw = workflow(state).earthdaily_raw_input;
  if (!raw) return `<div class="empty-state"><h3>EarthDaily source package</h3><p>Imagery, index time series, weather, anomaly, soil moisture, and quality flags will populate after the workflow run.</p></div>`;
  return `<div class="earthdaily-signal-grid">
    <article><h4>Field boundary</h4><p>${escapeHtml(raw.field.geometry.type)} · ${raw.field.geometry.coordinates[0]?.length || 0} vertices</p></article>
    <article><h4>STAC items</h4>${list(raw.imagery.stac_items.map((item) => `${item.collection} · ${item.id}`))}</article>
    <article><h4>Vegetation time series</h4><div class="mini-chart">${raw.time_series.ndvi.slice(-12).map((p) => `<i style="height:${Math.round(p.value * 60)}px"></i>`).join("")}</div></article>
    <article><h4>NDMI moisture signal</h4><p>${escapeHtml(raw.imagery.vegetation_indices.ndmi_mean)}</p></article>
    <article><h4>ET forecast</h4><div class="mini-chart">${raw.weather.et_forecast.map((p) => `<i style="height:${Math.round(p.value * 8)}px"></i>`).join("")}</div></article>
    <article><h4>Weather strip</h4>${list(raw.weather.temperature_max.map((p) => `${p.date}: ${p.value}C`))}</article>
    <article><h4>Anomaly events</h4>${list(raw.agronomic_events.hotspot_alerts.map((a) => `${a.type}: ${a.severity}`))}</article>
    <article><h4>Soil moisture</h4><p>Rootzone ${escapeHtml(raw.water_context.soil_moisture_rootzone)} · depletion ${escapeHtml(raw.water_context.estimated_depletion)} mm</p></article>
    <article><h4>Data quality</h4>${list(raw.metadata.quality_flags)}</article>
  </div>`;
}

function normalizationPanel(state) {
  if (state.earthdaily.loading) return skeletonRows(6);
  const pack = workflow(state).normalized_signal_pack;
  if (!pack) return `<div class="empty-state"><h3>Normalized signal pack</h3><p>Component scores will appear after AGRO-AI normalizes the provider payload.</p></div>`;
  const scores = pack.confidence_inputs.component_scores;
  const rows = [
    ["Moisture stress", pack.water_context.estimated_depletion_mm, scores.moisture_stress_score],
    ["ET pressure", pack.weather_context.et_forecast_7d_mm, scores.et_pressure_score],
    ["Vegetation stress", pack.vegetation_context.ndmi_level, scores.vegetation_stress_score],
    ["Anomaly severity", pack.anomaly_context.max_anomaly_severity, scores.anomaly_severity],
    ["Weather risk", pack.weather_context.heat_days_7d, scores.weather_risk_score],
    ["Data quality", pack.data_quality.score, scores.data_quality_score],
  ];
  return `<div class="two-column">
    <div class="table-wrap"><table class="data-table"><thead><tr><th>Raw</th><th>Normalized</th><th>Score</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${escapeHtml(row[0])}</td><td>${escapeHtml(row[1])}</td><td>${escapeHtml(row[2])}</td></tr>`).join("")}</tbody></table></div>
    <div class="earthdaily-bars">${rows.map((row) => bar(String(row[0]), Number(row[2]))).join("")}</div>
  </div>`;
}

function decisionPanel(state) {
  if (state.earthdaily.loading) return skeletonRows(7);
  const decision = workflow(state).decision_output;
  if (!decision) return `<div class="empty-state"><h3>Decision output</h3><p>Action, timing, volume, confidence, risks, and reasoning return from the deployed Worker.</p></div>`;
  const rec = decision.recommendation;
  const risks = Object.entries(decision.risk_flags).filter(([, active]) => active).map(([name]) => badge(name.replaceAll("_", " "), name.includes("stress") || name.includes("risk") ? "warning" : "danger")).join("");
  return `<div class="earthdaily-decision">
    <div class="recommendation-head"><div><h4>${escapeHtml(rec.action)}</h4><p>${escapeHtml(decision.rationale.executive_summary)}</p></div>${badge(rec.priority, rec.priority === "high" || rec.priority === "critical" ? "danger" : "warning")}</div>
    <div class="metric-row command-metrics"><span>Window: ${escapeHtml(rec.recommended_window_start)} to ${escapeHtml(rec.recommended_window_end)}</span><span>Volume: ${escapeHtml(rec.recommended_volume)} ${escapeHtml(rec.recommended_volume_unit)}</span><span>Duration: ${escapeHtml(rec.estimated_duration)} ${escapeHtml(rec.estimated_duration_unit)}</span></div>
    ${bar(`Confidence · ${decision.confidence.level}`, decision.confidence.score)}
    <div class="risk-chip-row">${risks || badge("no active risk flags", "success")}</div>
    <div class="two-column"><div><h4>Reasoning</h4>${list(decision.rationale.signal_evidence.slice(0, 6))}</div><div><h4>Next action</h4><button class="button secondary" type="button">Review field execution plan</button></div></div>
  </div>`;
}

function reportPanel(state) {
  if (state.earthdaily.loading) return skeletonRows(5);
  const data = workflow(state);
  const report = data.report_object;
  const decision = data.decision_output;
  if (!report || !decision) return `<div class="empty-state"><h3>Report-ready output</h3><p>Executive, advisor, grower, savings, compliance, and audit references will populate after the workflow completes.</p></div>`;
  return `<div class="report-preview-object">
    <p>${escapeHtml(report.pdf_ready_sections.executive_summary)}</p>
    <p>Advisor: ${escapeHtml(decision.reporting.advisor_note)}</p>
    <p>Grower: ${escapeHtml(decision.reporting.grower_facing_message)}</p>
    <p>Savings: ${escapeHtml(report.water_savings_estimate)}</p>
    <p>Compliance: ${escapeHtml(decision.reporting.compliance_note)}</p>
    <p>Audit: ${escapeHtml(report.audit_reference.audit_endpoint)}</p>
  </div>`;
}

function apiPanel(state) {
  if (state.earthdaily.loading) return skeletonRows(4);
  const data = workflow(state);
  if (!data.decision_output) return `<div class="empty-state"><h3>API trace</h3><p>Envelope, endpoint, request ID, provider trace, and decision ID will appear after the run.</p></div>`;
  return `<div class="earthdaily-api-panel">
    <div class="metric-row"><span>Endpoint: /api/v1/partners/earthdaily/end-to-end</span><span>HTTP: ${escapeHtml(state.earthdaily.httpStatus || 200)}</span><span>request_id: ${escapeHtml(state.earthdaily.requestId || data.integration_metadata?.request_id)}</span><span>decision_id: ${escapeHtml(data.decision_output.decision_id)}</span></div>
    ${jsonDetails("EarthDaily raw input", data.earthdaily_raw_input)}
    ${jsonDetails("Normalized signal pack", data.normalized_signal_pack)}
    ${jsonDetails("Decision output", data.decision_output)}
    ${jsonDetails("Report object", data.report_object)}
  </div>`;
}

function deploymentPanel() {
  return `<div class="deployment-map">
    ${["Sandbox account/feed", "API access path", "Update cadence", "Preferred output: STAC + JSON", "Technical owner"].map((item, index) => `<article><span>${index + 1}</span><strong>${escapeHtml(item)}</strong></article>`).join("")}
  </div>`;
}

export function renderEarthDaily(state) {
  const error = state.earthdaily.error
    ? `<section class="panel-card earthdaily-error"><h3>${escapeHtml(state.earthdaily.error)}</h3><button class="button secondary" data-action="run-earthdaily-workflow" type="button">Retry</button></section>`
    : "";

  return `<div class="workbench-flow earthdaily-workflow">
    <section class="panel-card workspace-header-card command-hero earthdaily-hero">
      <div><p class="eyebrow">EarthDaily x AGRO-AI</p><h2>EarthDaily data in. AGRO-AI decisions out. Customer workflow ready.</h2></div>
      <div class="header-badges">${modeBadge(state)}${badge(state.earthdaily.fallbackUsed ? "sample fallback" : "edge API", state.earthdaily.fallbackUsed ? "warning" : "success")}</div>
      <div class="runtime-actions"><button class="button primary" data-action="run-earthdaily-workflow" ${state.earthdaily.loading ? "disabled" : ""} type="button">${state.earthdaily.loading ? "Running..." : "Run EarthDaily -> AGRO-AI Decision Workflow"}</button></div>
    </section>
    ${error}
    ${panel(1, "Executive landing", `<p>EarthDaily supplies agricultural data infrastructure. AGRO-AI turns it into recommendation, timing, volume, confidence, risk flags, reasoning, and report-ready output.</p>`)}
    ${panel(2, "Field selection", fieldCard(state))}
    ${panel(3, "Scattered data panel", scatteredPanel(state))}
    ${panel(4, "Normalization panel", normalizationPanel(state))}
    ${panel(5, "Decision panel", decisionPanel(state))}
    ${panel(6, "Report panel", reportPanel(state))}
    ${panel(7, "API panel", apiPanel(state))}
    ${panel(8, "Deployment mapping", deploymentPanel())}
  </div>`;
}

