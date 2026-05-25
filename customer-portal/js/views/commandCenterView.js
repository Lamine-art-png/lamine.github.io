import { escapeHtml } from "../components/dom.js";
import { metricCard } from "../components/ui.js";

const PROCESS_STAGES = ["Sources", "Normalize", "Reconcile", "Decide", "Verify"];

function statusBadge(status) {
  const tone = /matched|verified|ready/i.test(status) ? "success" : /pending|required/i.test(status) ? "warning" : "neutral";
  return `<span class="badge ${tone}">${escapeHtml(status)}</span>`;
}

function executiveSummaryStrip() {
  return `<section class="command-summary-strip" aria-label="Executive water decision summary">
    ${metricCard("Water decision", "Irrigate 42 min tonight", "Primary recommendation ready")}
    ${metricCard("Confidence", "86%", "Decision confidence score")}
    ${metricCard("Evidence completeness", "92%", "Cross-source reconciliation coverage")}
    ${metricCard("Estimated water savings", "27%", "Assumption vs historical baseline")}
  </section>`;
}

function sourceIntelligencePanel() {
  const rows = [
    ["Controller history", "Matched", "1,248", "Last irrigation event: 36 min", "+0.22"],
    ["Weather demand", "Matched", "336", "ETo 6.4 mm, rain 0 mm", "+0.18"],
    ["Soil moisture", "Matched", "412", "38% deficit at 30 cm", "+0.17"],
    ["Flow meter", "Matched", "298", "Actual flow within 8% of plan", "+0.11"],
    ["Field observation", "Matched", "26", "Mild afternoon stress", "+0.09"],
    ["Earth observation layer", "Matched", "84", "Elevated canopy stress index", "+0.09"],
  ];

  return `<section class="command-section-block source-intelligence">
    <div class="section-headline"><p class="eyebrow">Source Intelligence</p><h2>Evidence inputs and confidence contribution</h2></div>
    <div class="source-stack">
      ${rows
        .map(
          ([source, status, records, signal, contribution]) => `<article class="source-row">
            <div class="source-row-main"><h3>${escapeHtml(source)}</h3><p>${escapeHtml(signal)}</p></div>
            <div class="source-row-meta"><span><strong>Status</strong>${statusBadge(status)}</span><span><strong>Records processed</strong><em>${escapeHtml(records)}</em></span><span><strong>Confidence contribution</strong><em>${escapeHtml(contribution)}</em></span></div>
          </article>`,
        )
        .join("")}
    </div>
  </section>`;
}

function intelligenceProcessingPanel(runtime) {
  return `<section class="command-section-block processing-surface ${runtime.analysis.running ? "running" : ""}">
    <div class="section-headline"><p class="eyebrow">Intelligence Processing</p><h2>Sources → Normalize → Reconcile → Decide → Verify</h2></div>
    <div class="processing-track" aria-label="Intelligence processing stages">
      <div class="processing-grid"></div>
      ${PROCESS_STAGES.map((stage, index) => `<div class="processing-stage stage-${index + 1}"><span class="signal-node"></span><strong>${stage}</strong></div>`).join("")}
      <span class="water-pulse" aria-hidden="true"></span>
    </div>
    <p class="muted">${escapeHtml(runtime.analysis.statusLabel || "Intelligence state available")}</p>
  </section>`;
}

function decisionPanel(runtime) {
  const ready = runtime.analysis.status === "complete";
  return `<section class="command-section-block decision-panel-enterprise">
    <div class="section-headline"><p class="eyebrow">Decision Panel</p><h2>Irrigate 42 min tonight</h2></div>
    <div class="decision-primary">
      <p><strong>Start</strong><span>21:00 PT</span></p>
      <p><strong>Apply</strong><span>12 mm net</span></p>
    </div>
    <dl class="decision-context">
      <div><dt>Crop</dt><dd>Cabernet Sauvignon</dd></div>
      <div><dt>Block</dt><dd>Block A North</dd></div>
      <div><dt>Driver</dt><dd>ETo 6.4 mm and 38% deficit at 30 cm</dd></div>
      <div><dt>Confidence</dt><dd>86%</dd></div>
      <div><dt>Verification</dt><dd>Required</dd></div>
    </dl>
    <div class="decision-actions">
      <button class="button primary" data-action="schedule" ${!ready ? "disabled" : ""} type="button">Approve schedule</button>
      <button class="button secondary" data-action="mark-applied" ${!ready ? "disabled" : ""} type="button">Confirm applied water</button>
      <button class="button secondary" data-action="add-observation" ${!ready ? "disabled" : ""} type="button">Add field observation</button>
      <button class="button secondary" data-action="verify" ${!ready ? "disabled" : ""} type="button">Verify outcome</button>
      <button class="button secondary" data-action="open-report" type="button">Open report</button>
    </div>
  </section>`;
}

function reconciliationAndVerification(runtime) {
  const chain = runtime.operatingChain || [];
  const rows = [
    ["WiseConn", "Last irrigation event: 36 min", "Valid recent controller event", "Matched"],
    ["Talgil", "Runtime reachable, no selected production targets", "Available integration, target selection pending", "Pending target"],
    ["Weather", "ETo 6.4 mm, rain 0 mm", "High water demand", "Matched"],
    ["Flow meter", "Actual flow within 8% of scheduled plan", "Applied water consistent", "Matched"],
    ["Field observation", "Mild afternoon stress", "Supports irrigation recommendation", "Matched"],
    ["Earth observation layer", "Elevated canopy stress index", "Supports water demand signal", "Matched"],
  ];

  return `<section class="command-section-block reconciliation-panel">
    <div class="section-headline"><p class="eyebrow">Reconciliation and Verification</p><h2>Cross-source interpretation and execution proof</h2></div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>Source</th><th>Signal</th><th>Interpretation</th><th>Status</th></tr></thead><tbody>
      ${rows.map((row) => `<tr>${row.map((cell, idx) => `<td>${idx === 3 ? statusBadge(cell) : escapeHtml(cell)}</td>`).join("")}</tr>`).join("")}
    </tbody></table></div>
    <div class="verification-chain-enterprise">
      ${(chain.length ? chain : [
        { label: "Recommended", status: "Recommendation ready" },
        { label: "Scheduled", status: "Pending" },
        { label: "Applied", status: "Pending" },
        { label: "Observed", status: "Pending" },
        { label: "Verified", status: "Pending" },
      ]).map((step) => `<div class="chain-step"><strong>${escapeHtml(step.label)}</strong><span>${escapeHtml(step.status)}</span></div>`).join("")}
    </div>
  </section>`;
}

function reportPreview(runtime) {
  const snapshot = runtime.reportSnapshots?.[0];
  return `<section class="command-section-block report-preview-enterprise">
    <div class="section-headline"><p class="eyebrow">Report Preview</p><h2>Executive-ready irrigation intelligence summary</h2></div>
    <table class="data-table compact"><tbody>
      <tr><th>Farm</th><td>${escapeHtml(snapshot?.farm || "Alpha Vineyard")}</td><th>Block</th><td>${escapeHtml(snapshot?.block || "Block A North")}</td></tr>
      <tr><th>Recommendation</th><td>${escapeHtml(snapshot?.recommendation || "Irrigate 42 min tonight")}</td><th>Planned water</th><td>12 mm net</td></tr>
      <tr><th>Applied water</th><td>${escapeHtml(snapshot?.appliedAction || "Pending confirmation")}</td><th>Variance</th><td>Within 8%</td></tr>
      <tr><th>Evidence completeness</th><td>${escapeHtml(snapshot?.evidenceCompleteness || "92%")}</td><th>Water savings assumption</th><td>${escapeHtml(snapshot?.waterEfficiencyNote || "27% reduction vs baseline")}</td></tr>
      <tr><th>Verification status</th><td colspan="3">${escapeHtml(snapshot?.verificationStatus || "Verification required")}</td></tr>
    </tbody></table>
  </section>`;
}

export function renderCommandCenter(state) {
  const runtime = state.demoRuntime;
  return `<div class="water-command-center enterprise-command-surface">
    ${executiveSummaryStrip()}
    ${sourceIntelligencePanel()}
    ${intelligenceProcessingPanel(runtime)}
    ${decisionPanel(runtime)}
    ${reconciliationAndVerification(runtime)}
    ${reportPreview(runtime)}
  </div>`;
}
