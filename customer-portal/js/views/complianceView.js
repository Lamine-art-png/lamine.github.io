import { escapeHtml } from "../components/dom.js";

function section(title, body) {
  return `<section class="portal-card compliance-card"><h2>${escapeHtml(title)}</h2>${body}</section>`;
}

function list(items = [], renderItem = (item) => item) {
  if (!items.length) return "<p class=\"muted\">None reported by the API.</p>";
  return `<ul>${items.map((item) => `<li>${renderItem(item)}</li>`).join("")}</ul>`;
}

export function renderCompliance(state) {
  const compliance = state.compliance || {};
  if (compliance.loading) {
    return `<div class="view-stack compliance-view">${section("Compliance loading", "<p>Loading API-backed compliance status…</p>")}</div>`;
  }
  if (compliance.error || !compliance.status) {
    return `<div class="view-stack compliance-view">${section("Compliance unavailable", `<p>Closed by default. ${escapeHtml(compliance.error || "API-backed compliance status has not loaded.")}</p><p class="muted">No representative compliance values are displayed until the API responds.</p>`)}</div>`;
  }

  const status = compliance.status;
  const readiness = status.readiness || {};
  const pack = status.rule_pack || {};
  const demoLabel = status.demo_mode ? `<p class="warning-text">Non-production demo fixture data. Do not use for regulatory filing.</p>` : "";
  const deadlines = readiness.upcoming_deadlines || [];
  const budgets = status.water_budgets || [];
  const reconciliation = status.reconciliation_summary || [];

  return `<div class="view-stack compliance-view">
    <section class="hero-panel compliance-hero">
      <div>
        <p class="eyebrow">${escapeHtml(pack.jurisdiction || "Compliance")} · ${escapeHtml(pack.status || "status unknown")}</p>
        <h2>Readiness is ${escapeHtml(String(readiness.readiness_percentage ?? "—"))}% — ${escapeHtml(readiness.readiness_status || "unavailable")}</h2>
        <p>${escapeHtml(readiness.next_required_action || "API-backed readiness is unavailable.")}</p>
        ${demoLabel}
      </div>
      <div class="hero-actions">
        <button class="button primary" data-action="export-compliance-json" type="button">Prepare JSON metadata</button>
      </div>
    </section>
    <div class="grid two-columns">
      ${section("Readiness summary", `<div class="metric-row"><span>Workflow</span><strong>${escapeHtml(readiness.workflow_type || pack.workflow_type || "—")}</strong></div><div class="metric-row"><span>Status</span><strong>${escapeHtml(readiness.readiness_status || "—")}</strong></div><p class="muted">Evidence package only — no direct filing or legal compliance guarantee.</p>`)}
      ${section("Jurisdiction and reporting period", list(deadlines, (item) => `${escapeHtml(item.county || item.state || item.country || "Jurisdiction")} · ${escapeHtml(item.reporting_year || "period unknown")} · deadline ${escapeHtml(item.reporting_deadline || "not supplied")}`))}
      ${section("Water-budget status", list(budgets, (item) => `${escapeHtml(item.water_source || "water source")} · remaining ${escapeHtml(String(item.remaining_balance_af ?? "—"))} AF · ${escapeHtml(item.threshold_status || "unchecked")}`))}
      ${section("Warnings", list(readiness.warnings || [], (item) => `${escapeHtml(item.code || "warning")} ${item.meter_id ? `· ${escapeHtml(item.meter_id)}` : ""}`))}
      ${section("Recommendation-to-application reconciliation", list(reconciliation, (item) => `${escapeHtml(item.recommendation_id || item.id || "ledger row")} · variance ${escapeHtml(String(item.variance_af ?? "—"))} AF · ${escapeHtml(String(item.variance_pct ?? "—"))}%`))}
      ${section("Missing evidence", list(readiness.missing_evidence || []))}
      ${section("Export package controls", `<p>JSON export metadata is persisted by the API. Secure stored downloads are not claimed while object storage is disabled.</p>`)}
    </div>
    <p class="compliance-disclaimer">${escapeHtml(readiness.disclaimer || "AGRO-AI prepares reporting-readiness evidence only. It does not provide legal advice, certify measurement methods, guarantee compliance, file with regulators, or imply regulator endorsement.")}</p>
  </div>`;
}
