import { escapeHtml, formatDate, formatValue, listItems, statusClass } from "./dom.js";

export function badge(label, tone = "neutral") {
  return `<span class="badge ${tone}">${escapeHtml(label)}</span>`;
}

export function metricCard(label, value, detail = "") {
  return `<article class="metric-card"><p class="metric-value">${escapeHtml(value)}</p><p class="metric-label">${escapeHtml(label)}</p>${detail ? `<p class="metric-detail">${escapeHtml(detail)}</p>` : ""}</article>`;
}

export function emptyState(title, detail) {
  return `<section class="empty-state"><h3>${escapeHtml(title)}</h3><p>${escapeHtml(detail)}</p></section>`;
}

export function table(headers, rows, emptyTitle = "No data", emptyDetail = "Nothing has been returned yet.") {
  if (!rows.length) return emptyState(emptyTitle, emptyDetail);
  return `<div class="table-wrap"><table class="data-table"><thead><tr>${headers
    .map((header) => `<th>${escapeHtml(header)}</th>`)
    .join("")}</tr></thead><tbody>${rows
    .map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(formatValue(cell))}</td>`).join("")}</tr>`)
    .join("")}</tbody></table></div>`;
}

export function operatingChain(steps = []) {
  const fallbackActions = {
    Recommended: "Generate water decision",
    Scheduled: "Awaiting schedule",
    Applied: "Awaiting controller execution",
    Observed: "Awaiting field observation",
    Verified: "Verification pending",
  };

  return `<section class="panel-card chain-card"><div class="section-heading"><p class="eyebrow">Operating Chain</p><h2>Recommended → Scheduled → Applied → Observed → Verified</h2><p>AGRO-AI tracks the recommendation through execution evidence and verification, not just the initial suggestion.</p></div><div class="chain-grid">${steps
    .map(
      (step, index) => `<article class="chain-step ${statusClass(step.status)}"><div class="step-number">${index + 1}</div><div class="step-top"><span>${escapeHtml(step.label)}</span>${badge(
        step.status || "Pending",
        statusClass(step.status)
      )}</div><p class="step-time">${escapeHtml(formatDate(step.timestamp))}</p><p><strong>Owner:</strong> ${escapeHtml(
        step.owner || "AGRO-AI"
      )}</p><p><strong>Evidence / next action:</strong> ${escapeHtml(step.evidence || fallbackActions[step.label] || "Awaiting next action")}</p></article>`
    )
    .join("")}</div></section>`;
}

export function recommendationProofCard(recommendation = {}, options = {}) {
  const label = options.label || "Recommendation proof";
  const modeBadge = options.modeBadge || "Demo data";
  const decision = recommendation.decision || recommendation.water_decision || recommendation.recommendation || recommendation.action || "Data source pending";
  const depth = recommendation.depth || recommendation.depth_mm || recommendation.recommended_depth_mm || "Awaiting telemetry";
  const duration = recommendation.duration || recommendation.duration_minutes || recommendation.duration_min || recommendation.irrigation_minutes || "Awaiting telemetry";
  const timing = recommendation.timing || recommendation.start_time || recommendation.recommended_start || "Awaiting telemetry";
  const confidence = recommendation.confidence || recommendation.confidence_score || "Data source pending";
  const dataQuality = recommendation.dataQuality || recommendation.data_quality || "Data source pending";
  const keyDrivers = recommendation.keyDrivers || recommendation.key_drivers || recommendation.drivers || recommendation.reasons || [];
  const liveInputs = recommendation.liveInputsUsed || recommendation.live_inputs_used || recommendation.inputs_used || [];
  const overrides = recommendation.manualOverridesUsed || recommendation.manual_overrides_used || recommendation.overrides_used || [];
  const verification = recommendation.verificationPlan || recommendation.verification_plan || "Verification required after controller execution and field observation.";

  return `<section class="decision-panel recommendation-proof"><div class="proof-head"><div><p class="eyebrow">${escapeHtml(label)}</p><h2>${escapeHtml(decision)}</h2></div>${badge(modeBadge, options.badgeTone || "warning")}</div><div class="hero-metrics proof-metrics">${metricCard(
    "Recommended depth",
    depth
  )}${metricCard("Recommended duration", duration)}${metricCard("Timing", timing)}${metricCard("Confidence", confidence)}${metricCard("Data quality", dataQuality)}</div><div class="three-column proof-lists"><article><h3>Key drivers</h3><ul>${listItems(
    keyDrivers
  )}</ul></article><article><h3>Live inputs used</h3><ul>${listItems(liveInputs)}</ul><h3>Manual overrides used</h3><ul>${listItems(overrides)}</ul></article><article><h3>Verification required</h3><p>${escapeHtml(
    verification
  )}</p></article></div></section>`;
}

export function integrationCard(integration) {
  return `<article class="integration-card"><div class="integration-head"><div><h3>${escapeHtml(integration.name)}</h3><p>${escapeHtml(
    integration.description
  )}</p></div>${badge(integration.status, statusClass(integration.status))}</div><dl class="definition-grid"><div><dt>Connection health</dt><dd>${escapeHtml(
    integration.connectionHealth || integration.status
  )}</dd></div><div><dt>Latest check</dt><dd>${escapeHtml(formatDate(integration.lastChecked))}</dd></div><div><dt>Farms / targets</dt><dd>${escapeHtml(
    integration.farmsOrTargets
  )}</dd></div><div><dt>Zones / sensors</dt><dd>${escapeHtml(integration.zonesOrSensors)}</dd></div><div><dt>AGRO-AI reads</dt><dd>${escapeHtml(
    integration.reads || "Controller, telemetry, and context signals"
  )}</dd></div><div><dt>AGRO-AI generates</dt><dd>${escapeHtml(integration.generates || "Recommendations, tasks, and verification evidence")}</dd></div></dl><p class="limitation-note"><strong>Current limitation:</strong> ${escapeHtml(
    integration.limitation
  )}</p></article>`;
}

export function onboardingProviderCard(provider) {
  return `<article class="provider-onboarding-card"><p class="eyebrow">Provider onboarding</p><h3>Connect ${escapeHtml(provider)}</h3><p>Prepare ${escapeHtml(
    provider
  )} credentials, test runtime health, sync farms/controllers, and activate intelligence once secure backend credential endpoints are available.</p><button class="button secondary" type="button" aria-describedby="credential-note" disabled title="Secure backend credential endpoint required">Request backend setup</button></article>`;
}

export function reportCard(report) {
  return `<article class="report-card"><div><p class="eyebrow">Executive Report</p><h3>${escapeHtml(report.name)}</h3><p>${escapeHtml(report.purpose || report.description)}</p></div><dl class="definition-grid"><div><dt>Coverage</dt><dd>${escapeHtml(
    report.coverage
  )}</dd></div><div><dt>Status</dt><dd>${escapeHtml(report.status)}</dd></div><div><dt>Last generated</dt><dd>${escapeHtml(
    report.lastGenerated || "Report generation is coming online for this deployment."
  )}</dd></div></dl><button class="button secondary" type="button" disabled title="${escapeHtml(report.status)}">${escapeHtml(report.action)}</button></article>`;
}

export function technicalTrace(trace = {}) {
  return `<details class="technical-trace"><summary>Technical Trace</summary><div class="trace-grid"><div><h4>Source</h4><ul>${listItems([
    `Source: ${formatValue(trace.source)}`,
    `Source entity ID: ${formatValue(trace.sourceEntityId)}`,
    `Context origin: ${formatValue(trace.contextOrigin)}`,
    `Controller provider: ${formatValue(trace.controllerProvider)}`,
  ])}</ul></div><div><h4>Inputs</h4><ul>${listItems([...(trace.liveInputsUsed || []), ...(trace.manualOverridesUsed || []).map((item) => `Override: ${item}`)])}</ul></div><div><h4>Telemetry & warnings</h4><ul>${listItems([...(trace.telemetryUsed || []), ...(trace.warnings || []).map((item) => `Warning: ${item}`)])}</ul></div></div></details>`;
}
