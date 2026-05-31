import { escapeHtml } from "../components/dom.js";

const readiness = {
  percentage: 59,
  nextAction: "Attach manual reading evidence for the June SV-WELL-02 telemetry gap.",
  deadline: "GEARS readiness deadline: February 1, 2027",
};

function section(title, body) {
  return `<section class="portal-card compliance-card"><h2>${escapeHtml(title)}</h2>${body}</section>`;
}

export function renderCompliance(state) {
  return `<div class="view-stack compliance-view">
    <section class="hero-panel compliance-hero">
      <div>
        <p class="eyebrow">California Compliance Pack v0.1</p>
        <h2>Readiness is ${readiness.percentage}% — action required</h2>
        <p>${escapeHtml(readiness.nextAction)}</p>
      </div>
      <div class="hero-actions">
        <button class="button primary" data-action="export-compliance-json" type="button">Prepare JSON package</button>
        <button class="button ghost" data-action="export-compliance-csv" type="button">Export CSV</button>
      </div>
    </section>
    <div class="grid two-columns">
      ${section("Readiness summary", `<div class="metric-row"><span>GEARS</span><strong>Blocked</strong></div><div class="metric-row"><span>SGMA GSA</span><strong>Warnings</strong></div><p class="muted">Evidence package only — no direct filing or legal compliance guarantee.</p>`)}
      ${section("Jurisdiction and reporting period", `<p>Sonoma County · Santa Rosa Plain Subbasin · Santa Rosa Plain GSA</p><p>Reporting year 2026 · ${escapeHtml(readiness.deadline)}</p>`)}
      ${section("Water-budget status", `<p><strong class="danger-text">Projected -2.4 AF</strong> remaining by year end.</p><p>Allocation 42.0 AF · Extraction 31.1 AF · Remaining 10.9 AF</p>`)}
      ${section("Recommendation-to-application reconciliation", `<p>rec-sv-0514 → approval → schedule → WiseConn command → applied event → measured extraction.</p><p>Variance: 0.32 AF / 10.32% (calculated).</p>`)}
      ${section("Well and meter health", `<p>SV-WELL-01 meter calibration current.</p><p class="warning-text">SV-WELL-02 calibration date 2024-11-01 is stale.</p>`)}
      ${section("Missing evidence and anomalies", `<ul><li>Manual reading evidence needed for June telemetry gap.</li><li>Application variance requires reviewer note.</li></ul>`)}
      ${section("Upcoming deadlines", `<ul><li>GEARS: 2027-02-01</li><li>SGMA GSA annual-readiness: 2027-04-01</li></ul>`)}
      ${section("Export package controls", `<p>Exports include provenance, truth labels, assumptions, missing-data flags, and methodology.</p><button class="button secondary" data-action="export-compliance-pdf" type="button">Prepare PDF package</button>`)}
    </div>
    ${section("Audit trail", `<ol><li>Fixture loaded — system — 2026-07-01</li><li>Readiness checked — water compliance reviewer — 2026-07-15</li></ol>`)}
    <p class="compliance-disclaimer">AGRO-AI prepares reporting-readiness evidence only. It does not provide legal advice, certify measurement methods, guarantee compliance, file with regulators, or imply regulator endorsement.</p>
  </div>`;
}
