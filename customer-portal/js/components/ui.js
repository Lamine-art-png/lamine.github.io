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

  return `<section class="panel-card chain-card"><div class="section-heading"><p class="eyebrow">Operating Chain</p><h2>Recommendation to verified outcome</h2></div><div class="chain-grid">${steps
    .map(
      (step) => `<article class="chain-step ${statusClass(step.status)}"><div class="step-top"><span>${escapeHtml(step.label)}</span>${badge(
        step.status || "Pending",
        statusClass(step.status)
      )}</div><p class="step-time">${escapeHtml(formatDate(step.timestamp))}</p><p><strong>Owner:</strong> ${escapeHtml(
        step.owner || "AGRO-AI"
      )}</p><p><strong>Evidence / next action:</strong> ${escapeHtml(step.evidence || fallbackActions[step.label] || "Awaiting next action")}</p></article>`
    )
    .join("")}</div></section>`;
}

export function integrationCard(integration) {
  return `<article class="integration-card"><div class="integration-head"><div><h3>${escapeHtml(integration.name)}</h3><p>${escapeHtml(
    integration.description
  )}</p></div>${badge(integration.status, statusClass(integration.status))}</div><dl class="definition-grid"><div><dt>Farms / targets</dt><dd>${escapeHtml(
    integration.farmsOrTargets
  )}</dd></div><div><dt>Zones / sensors</dt><dd>${escapeHtml(integration.zonesOrSensors)}</dd></div><div><dt>Last checked</dt><dd>${escapeHtml(
    formatDate(integration.lastChecked)
  )}</dd></div></dl><p class="limitation-note">${escapeHtml(integration.limitation)}</p></article>`;
}

export function reportCard(report) {
  return `<article class="report-card"><div><p class="eyebrow">Executive Report</p><h3>${escapeHtml(report.name)}</h3><p>${escapeHtml(report.description)}</p></div><dl class="definition-grid"><div><dt>Status</dt><dd>${escapeHtml(
    report.status
  )}</dd></div><div><dt>Coverage</dt><dd>${escapeHtml(report.coverage)}</dd></div><div><dt>Last generated</dt><dd>${escapeHtml(
    report.lastGenerated || "Report generation is coming online for this deployment."
  )}</dd></div></dl><button class="button secondary" type="button">${escapeHtml(report.action)}</button></article>`;
}

export function technicalTrace(trace = {}) {
  return `<details class="technical-trace"><summary>Technical Trace</summary><div class="trace-grid"><div><h4>Source</h4><ul>${listItems([
    `Source: ${formatValue(trace.source)}`,
    `Source entity ID: ${formatValue(trace.sourceEntityId)}`,
    `Context origin: ${formatValue(trace.contextOrigin)}`,
    `Controller provider: ${formatValue(trace.controllerProvider)}`,
  ])}</ul></div><div><h4>Inputs</h4><ul>${listItems([...(trace.liveInputsUsed || []), ...(trace.manualOverridesUsed || []).map((item) => `Override: ${item}`)])}</ul></div><div><h4>Telemetry & warnings</h4><ul>${listItems([...(trace.telemetryUsed || []), ...(trace.warnings || []).map((item) => `Warning: ${item}`)])}</ul></div></div></details>`;
}
