import { escapeHtml } from "../components/dom.js";

function section(title, body) {
  return `<section class="portal-card compliance-card"><h2>${escapeHtml(title)}</h2>${body}</section>`;
}

function downloadLastExport(exportPackage) {
  if (!exportPackage?.content_base64) return "";
  return `<p class="muted">Latest export: ${escapeHtml(exportPackage.file_name)} · ${escapeHtml(String(exportPackage.content_bytes || 0))} bytes</p>`;
}

export function renderCompliance(state) {
  const compliance = state.compliance || {};
  const status = compliance.status || {};
  const readiness = status.readiness || {};
  const org = status.organization || {};
  const jurisdictions = status.jurisdictions || readiness.upcoming_deadlines || [];
  const jurisdiction = jurisdictions[0] || {};
  const budgets = readiness.water_budgets || [];
  const loading = compliance.loading ? `<p class="muted">Loading live compliance readiness…</p>` : "";
  const error = compliance.error ? `<p class="warning-text">${escapeHtml(compliance.error)}</p>` : "";
  const nextAction = readiness.next_required_action || "Load the compliance API to identify the next required action.";
  const readinessPercentage = readiness.readiness_percentage ?? "—";
  const readinessStatus = readiness.readiness_status || "unknown";
  return `<div class="view-stack compliance-view">
    <section class="hero-panel compliance-hero">
      <div>
        <p class="eyebrow">California Compliance Pack v0.1 · Global Kernel v2</p>
        <h2>Readiness is ${escapeHtml(String(readinessPercentage))}% — ${escapeHtml(readinessStatus)}</h2>
        <p>${escapeHtml(nextAction)}</p>
        ${loading}${error}
      </div>
      <div class="hero-actions">
        <button class="button primary" data-action="export-compliance-json" type="button">Prepare JSON package</button>
        <button class="button ghost" data-action="export-compliance-csv" type="button">Export CSV</button>
        <button class="button ghost" data-action="export-compliance-xlsx" type="button">Export XLSX</button>
      </div>
    </section>
    <div class="grid two-columns">
      ${section("Readiness summary", `<div class="metric-row"><span>Workflow</span><strong>${escapeHtml(readiness.workflow_type || "GEARS readiness")}</strong></div><div class="metric-row"><span>Status</span><strong>${escapeHtml(readinessStatus)}</strong></div><p class="muted">Evidence package only — no direct filing or legal compliance guarantee.</p>`)}
      ${section("Jurisdiction and reporting period", `<p>${escapeHtml(org.name || "Sierra Verde Vineyard LLC")}</p><p>${escapeHtml(jurisdiction.county || "Sonoma")} · ${escapeHtml(jurisdiction.subbasin || "Santa Rosa Plain Subbasin")} · ${escapeHtml(jurisdiction.gsa || jurisdiction.authority_name || "Santa Rosa Plain GSA")}</p><p>Reporting year ${escapeHtml(String(jurisdiction.reporting_year || 2026))} · deadline ${escapeHtml(jurisdiction.reporting_deadline || "2027-02-01")}</p>`)}
      ${section("Water-budget status", `<p><strong class="danger-text">Threshold alerts are API-calculated.</strong></p><p>${escapeHtml((readiness.warnings || []).filter((w) => w.code === "water_budget_threshold_alert").length)} active budget warning(s).</p>`)}
      ${section("Recommendation-to-application reconciliation", `<p>Recommendation → approval → schedule → controller command → applied event → measured extraction.</p><p>${escapeHtml((readiness.unresolved_anomalies || []).length)} unresolved variance/anomaly item(s).</p>`)}
      ${section("Well and meter health", `<p>${escapeHtml((readiness.warnings || []).filter((w) => w.code === "stale_calibration").length)} stale calibration warning(s).</p><p>Truth labels are preserved in the measurement ledger.</p>`)}
      ${section("Missing evidence and anomalies", `<ul>${(readiness.missing_evidence || ["No API data loaded yet."]).map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>`)}
      ${section("Upcoming deadlines", `<ul>${jurisdictions.map((item) => `<li>${escapeHtml(item.workflow_type)}: ${escapeHtml(item.reporting_deadline)}</li>`).join("") || "<li>No deadline loaded.</li>"}</ul>`)}
      ${section("Export package controls", `<p>Exports include provenance, truth labels, assumptions, missing-data flags, and methodology.</p><button class="button secondary" data-action="export-compliance-pdf" type="button">Prepare PDF package</button>${downloadLastExport(compliance.lastExport)}`)}
    </div>
    ${section("Audit trail", `<p>Audit events are loaded from <code>/v1/compliance/audit-log</code> in live workspaces.</p>`)}
    <p class="compliance-disclaimer">${escapeHtml(status.disclaimer || "AGRO-AI prepares reporting-readiness evidence only. It does not provide legal advice, certify measurement methods, guarantee compliance, file with regulators, or imply regulator endorsement.")}</p>
  </div>`;
}
