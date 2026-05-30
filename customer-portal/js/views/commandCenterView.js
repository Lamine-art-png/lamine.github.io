import { escapeHtml, formatDate } from "../components/dom.js";
import { metricCard } from "../components/ui.js";

const PROCESS_STAGES = ["Sources", "Normalize", "Reconcile", "Decide", "Verify"];

const FALLBACK_RECONCILIATION_ROWS = [
  ["Controller history", "Last irrigation event: 36 min", "Valid recent controller event", "Matched"],
  ["Weather demand", "ETo 6.4 mm, rain 0 mm", "High water demand", "Matched"],
  ["Soil moisture", "38 percent deficit at 30 cm", "Root-zone deficit supports irrigation", "Matched"],
  ["Flow meter", "Actual flow within 8 percent of plan", "Applied water consistent", "Matched"],
  ["Field observation", "Mild afternoon stress", "Supports irrigation recommendation", "Matched"],
  ["Earth observation layer", "Elevated canopy stress index", "Supports water demand signal", "Matched"],
  ["Talgil", "Runtime reachable, no selected production target", "Integration available, target selection pending", "Pending target"],
];

function statusBadge(status = "Pending") {
  const tone = /matched|verified|ready|complete|connected|accepted|online/i.test(status)
    ? "success"
    : /pending|required|review|unavailable/i.test(status)
      ? "warning"
      : "neutral";
  return `<span class="badge ${tone}">${escapeHtml(status)}</span>`;
}

function backendResult(runtime) {
  return runtime.analysis?.backendResult || null;
}

function firstSnapshot(runtime) {
  return runtime.reportSnapshots?.[0] || null;
}

function percentValue(value, fallback) {
  if (typeof value === "number") return value <= 1 ? `${Math.round(value * 100)}%` : `${Math.round(value)}%`;
  if (typeof value === "string" && value.trim()) return value;
  return fallback;
}

function decisionModel(runtime) {
  const backend = backendResult(runtime);
  const summary = backend?.report_summary || {};
  const rec = runtime.activeRecommendation || backend?.recommendation || {};
  const snapshot = firstSnapshot(runtime);
  const drivers = rec.keyDrivers || rec.key_drivers || summary.key_drivers || [];
  const driver = Array.isArray(drivers) && drivers.length ? drivers[0] : "ETo 6.4 mm and 38 percent root-zone deficit";
  return {
    action: rec.action || rec.decision || summary.recommendation || snapshot?.recommendation || "Irrigate 42 min tonight",
    start: rec.timing || rec.start_time || rec.start || summary.start_time || "21:00 PT",
    plannedWater: rec.depth || summary.planned_water || snapshot?.plannedWater || "12 mm net",
    confidence: percentValue(rec.confidence || summary.confidence || snapshot?.confidence, "86%"),
    evidence: percentValue(rec.dataQuality || summary.evidence_completeness || backend?.reconciliation?.evidence_completeness || snapshot?.evidenceCompleteness, "92%"),
    savings: percentValue(summary.water_savings_percent || snapshot?.waterSavingsRate || runtime.institutionalKpis?.waterSavingsRate, "27%"),
    crop: rec.crop || summary.crop || snapshot?.crop || runtime.activeZone?.crop || "Cabernet Sauvignon",
    block: rec.block || summary.block || snapshot?.block || runtime.activeZone?.name || "Block A North",
    driver,
    verification: rec.verificationPlan || rec.verification_requirement || summary.verification_status || snapshot?.verificationStatus || "Required",
  };
}

function executiveSummaryStrip(runtime) {
  const decision = decisionModel(runtime);
  return `<section class="command-summary-strip" aria-label="Executive water decision summary">
    ${metricCard("Current decision", decision.action, runtime.analysis?.status === "complete" ? "Decision ready" : "Run analysis to verify")}
    ${metricCard("Confidence", decision.confidence, "Decision confidence score")}
    ${metricCard("Evidence completeness", decision.evidence, "Cross-source reconciliation coverage")}
    ${metricCard("Estimated water savings", decision.savings, "Assumption vs historical baseline")}
  </section>`;
}

function sourceRows(runtime) {
  const backend = backendResult(runtime);
  const signals = backend?.signal_summary || {};
  const source = runtime.sourceState || {};
  const uploaded = source.uploadedFileName || runtime.analysis?.artifacts?.at?.(-1)?.filename;
  const rows = [
    ["Controller history", runtime.intakeMode === "connected" ? "Connected source" : "Matched", "1,248", signals.controller_history || "Last irrigation event: 36 min", "+0.22"],
    ["Weather demand", "Matched", "336", signals.weather_demand || "ETo 6.4 mm, rain 0 mm", "+0.18"],
    ["Soil moisture", "Matched", "412", signals.soil_moisture || "38 percent deficit at 30 cm", "+0.17"],
    ["Flow meter", "Matched", "298", signals.flow_meter || "Actual flow within 8 percent of plan", "+0.11"],
    ["Field observation", "Matched", "26", signals.field_observation || "Mild afternoon stress", "+0.09"],
    ["Earth observation layer", "Matched", "84", signals.earth_observation || signals.satellite_stress || "Elevated canopy stress index", "+0.09"],
    ["Uploaded records", uploaded ? "Accepted" : "Pending", uploaded ? "1 file" : "0", uploaded || "Awaiting CSV, Excel, JSON, TXT, or notes", uploaded ? "+0.12" : "Pending"],
  ];

  if (Array.isArray(backend?.data_sources) && backend.data_sources.length) {
    backend.data_sources.slice(0, 3).forEach((item) => {
      if (typeof item === "string") return;
      rows.push([
        item.name || item.source || "Backend source",
        item.status || "Matched",
        String(item.records_processed || item.records || "Available"),
        item.latest_signal || item.signal || "Backend source included in analysis",
        item.confidence_contribution || item.contribution || "Included",
      ]);
    });
  }
  return rows;
}

function sourceLayer(runtime) {
  return `<section class="command-section-block source-intelligence">
    <div class="section-headline command-section-heading">
      <div><p class="eyebrow">Source intelligence</p><h2>Signals used to understand field conditions.</h2></div>
      <button class="button ghost compact" data-action="open-source-drawer" type="button">Add or manage sources</button>
    </div>
    <div class="source-stack">
      ${sourceRows(runtime)
        .map(
          ([source, status, records, signal, contribution]) => `<article class="source-row">
            <div class="source-row-main"><h3>${escapeHtml(source)}</h3><p>${escapeHtml(signal)}</p></div>
            <div class="source-row-meta"><span><strong>Status</strong>${statusBadge(status)}</span><span><strong>Records</strong><em>${escapeHtml(records)}</em></span><span><strong>Contribution</strong><em>${escapeHtml(contribution)}</em></span></div>
          </article>`,
        )
        .join("")}
    </div>
  </section>`;
}

function stageState(runtime, stage, index) {
  const step = runtime.analysis?.steps?.find((item) => (item.title || item.label || "").toLowerCase() === stage.toLowerCase()) || runtime.analysis?.steps?.[index];
  if (runtime.analysis?.status === "complete") return "complete";
  if (!runtime.intakeMode) return "pending";
  if (runtime.analysis?.running) return step?.status === "complete" ? "complete" : step?.status === "running" || index === 0 ? "active" : "pending";
  return index === 0 ? "complete" : "pending";
}

function runButtonModel(runtime) {
  if (!runtime.intakeMode) return { disabled: true, label: "Select a source to begin" };
  if (runtime.analysis?.running) return { disabled: true, label: "Analyzing source records…" };
  if (runtime.analysis?.status === "complete") return { disabled: false, label: "Refresh intelligence" };
  return { disabled: false, label: "Run intelligence analysis" };
}

function analysisTrace(runtime) {
  const steps = runtime.analysis?.steps?.length ? runtime.analysis.steps : [];
  if (!steps.length) return "";
  const stamp = runtime.activeRecommendation?.generatedAt || "";
  return `<details class="analysis-trace">
    <summary>Analysis trace</summary>
    <p class="trace-note">Structured operational sequence. Source records are normalized, reconciled, scored, and prepared for verification.</p>
    <div class="trace-rows">
      ${steps
        .map((step) => `<div class="trace-row">
          <div class="trace-row-head"><strong>${escapeHtml(step.title || step.label || "Step")}</strong>${statusBadge(step.statusLabel || (step.status === "complete" ? "Complete" : "Pending"))}</div>
          <p>${escapeHtml(step.detail || "Source reconciliation step")}</p>
          <div class="trace-row-meta"><span>Records processed: ${escapeHtml(String(step.objectsProcessed ?? 0))}</span><span>${escapeHtml(step.status === "complete" && stamp ? formatDate(stamp) : "—")}</span></div>
        </div>`)
        .join("")}
    </div>
  </details>`;
}

function intelligenceProcessingPanel(runtime) {
  const running = Boolean(runtime.analysis?.running);
  const run = runButtonModel(runtime);
  const statusText = runtime.analysis?.backendError || runtime.analysis?.statusLabel || (runtime.intakeMode ? "Source selected" : "Waiting for source");
  return `<section class="command-section-block processing-surface ${running ? "running" : ""}">
    <div class="section-headline command-section-heading">
      <div>
        <p class="eyebrow">Decision pipeline</p>
        <h2>Source normalization, reconciliation, confidence scoring, and verification preparation.</h2>
      </div>
      <button class="button primary command-run-button" data-action="run-ai-analysis" ${run.disabled ? "disabled" : ""} type="button">${escapeHtml(run.label)}</button>
    </div>
    <div class="processing-track" aria-label="Decision pipeline stages">
      <div class="processing-grid"></div>
      ${PROCESS_STAGES.map((stage, index) => {
        const stage_state = stageState(runtime, stage, index);
        return `<div class="processing-stage stage-${stage_state}"><span class="signal-node"></span><strong>${escapeHtml(stage)}</strong><small>${escapeHtml(stage_state === "active" ? "Active" : stage_state === "complete" ? "Complete" : "Pending")}</small></div>`;
      }).join("")}
      <span class="water-pulse" aria-hidden="true"></span>
    </div>
    <p class="processing-status ${runtime.analysis?.backendError ? "warning-text" : ""}">${escapeHtml(statusText)}</p>
    ${analysisTrace(runtime)}
  </section>`;
}

function decisionPanel(runtime) {
  const ready = runtime.analysis?.status === "complete";
  const decision = decisionModel(runtime);
  return `<section class="command-section-block decision-panel-enterprise">
    <div class="section-headline"><p class="eyebrow">Verified water decision</p><h2>${escapeHtml(decision.action)}</h2></div>
    <div class="decision-hero">
      <span>Start ${escapeHtml(decision.start)} · Apply ${escapeHtml(decision.plannedWater)}</span>
    </div>
    <dl class="decision-context">
      <div><dt>Crop</dt><dd>${escapeHtml(decision.crop)}</dd></div>
      <div><dt>Block</dt><dd>${escapeHtml(decision.block)}</dd></div>
      <div><dt>Driver</dt><dd>${escapeHtml(decision.driver)}</dd></div>
      <div><dt>Confidence</dt><dd>${escapeHtml(decision.confidence)}</dd></div>
      <div><dt>Evidence completeness</dt><dd>${escapeHtml(decision.evidence)}</dd></div>
      <div><dt>Verification</dt><dd>${escapeHtml(decision.verification)}</dd></div>
    </dl>
    <div class="decision-actions">
      <button class="button primary" data-action="schedule" ${!ready ? "disabled" : ""} title="${ready ? "Approve the schedule" : "Run intelligence analysis to enable scheduling"}" type="button">Approve schedule</button>
      <button class="button secondary" data-action="mark-applied" ${!ready ? "disabled" : ""} type="button">Confirm applied water</button>
      <button class="button secondary" data-action="add-observation" ${!ready ? "disabled" : ""} type="button">Add field observation</button>
      <button class="button secondary" data-action="verify" ${!ready ? "disabled" : ""} type="button">Verify outcome</button>
      <button class="button secondary" data-action="open-report" type="button">Open report</button>
    </div>
    ${!ready ? '<p class="muted decision-hint">Run intelligence analysis to enable schedule, applied water, observation, and verification actions.</p>' : ""}
  </section>`;
}

function reconciliationRows(runtime) {
  const backend = backendResult(runtime);
  const rows = Array.isArray(backend?.reconciliation)
    ? backend.reconciliation
    : backend?.reconciliation?.rows || backend?.reconciliation?.source_reconciliation || runtime.reconciliationRows || FALLBACK_RECONCILIATION_ROWS;
  return rows.length ? rows : FALLBACK_RECONCILIATION_ROWS;
}

function evidenceChain(runtime) {
  const chain = runtime.operatingChain?.length ? runtime.operatingChain : [
    { label: "Recommended", status: "Pending", timestamp: "", owner: "AGRO-AI Intelligence Engine", evidence: "Recommendation pending" },
    { label: "Scheduled", status: "Pending", timestamp: "", owner: "Operations user", evidence: "Schedule pending" },
    { label: "Applied", status: "Pending", timestamp: "", owner: "Operations user", evidence: "Applied water pending" },
    { label: "Observed", status: "Pending", timestamp: "", owner: "Operations user", evidence: "Field observation pending" },
    { label: "Verified", status: "Pending", timestamp: "", owner: "AGRO-AI Verification", evidence: "Verification pending" },
  ];
  return `<section class="command-section-block evidence-chain-panel">
    <div class="section-headline"><p class="eyebrow">Evidence chain</p><h2>Recommendation through verified outcome</h2></div>
    <div class="verification-chain-enterprise">
      ${chain.map((step) => `<div class="chain-step">
        <strong>${escapeHtml(step.label)}</strong>
        ${statusBadge(step.status)}
        <span>${escapeHtml(step.timestamp ? formatDate(step.timestamp) : "Pending")}</span>
        <em>${escapeHtml(step.owner || "Operations user")}</em>
        <p>${escapeHtml(step.evidence || "Evidence pending")}</p>
      </div>`).join("")}
    </div>
  </section>`;
}

function sourceReconciliation(runtime) {
  return `<section class="command-section-block reconciliation-panel">
    <div class="section-headline"><p class="eyebrow">Source reconciliation</p><h2>How source signals resolve into one decision</h2></div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>Source</th><th>Signal</th><th>Interpretation</th><th>Status</th></tr></thead><tbody>
      ${reconciliationRows(runtime).map((row) => {
        const cells = Array.isArray(row)
          ? row
          : [row.source || row.name, row.signal || row.value, row.interpretation || row.summary, row.status || row.state];
        return `<tr>${cells.slice(0, 4).map((cell, idx) => `<td>${idx === 3 ? statusBadge(cell) : escapeHtml(cell || "")}</td>`).join("")}</tr>`;
      }).join("")}
    </tbody></table></div>
  </section>`;
}

function reportPreview(runtime) {
  const snapshot = firstSnapshot(runtime);
  const decision = decisionModel(runtime);
  const backend = backendResult(runtime);
  const summary = backend?.report_summary || {};
  const rows = [
    ["Farm", snapshot?.farm || summary.farm || runtime.activeFarm?.name || "Alpha Vineyard"],
    ["Block", snapshot?.block || summary.block || decision.block],
    ["Recommendation", snapshot?.recommendation || decision.action],
    ["Planned water", snapshot?.plannedWater || summary.planned_water || decision.plannedWater],
    ["Applied water", snapshot?.appliedAction || summary.applied_water || "Pending confirmation"],
    ["Variance", snapshot?.variance || summary.variance || "Within 8 percent"],
    ["Evidence completeness", snapshot?.evidenceCompleteness || decision.evidence],
    ["Estimated water savings", `${decision.savings} vs historical baseline`],
    ["Verification status", snapshot?.verificationStatus || decision.verification],
  ];
  return `<section class="command-section-block report-preview-enterprise">
    <div class="section-headline command-section-heading">
      <div><p class="eyebrow">Executive report preview</p><h2>Export-ready decision record</h2></div>
      <div class="report-actions">
        <button class="button secondary" data-action="preview-report" type="button">Preview report</button>
        <button class="button secondary" data-action="export-csv" type="button">Export CSV</button>
        <button class="button secondary" data-action="print-report" type="button">Print report</button>
      </div>
    </div>
    <table class="data-table compact"><tbody>
      ${rows.map(([label, value]) => `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(value)}</td></tr>`).join("")}
    </tbody></table>
  </section>`;
}

export function renderCommandCenter(state) {
  const runtime = state.demoRuntime;
  return `<div class="water-command-center enterprise-command-surface">
    ${executiveSummaryStrip(runtime)}
    <div class="command-canvas">
      ${sourceLayer(runtime)}
      ${intelligenceProcessingPanel(runtime)}
      ${decisionPanel(runtime)}
    </div>
    ${sourceReconciliation(runtime)}
    ${evidenceChain(runtime)}
    ${reportPreview(runtime)}
  </div>`;
}
