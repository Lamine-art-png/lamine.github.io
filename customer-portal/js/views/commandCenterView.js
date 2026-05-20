import { escapeHtml, formatValue } from "../components/dom.js";

function fmtStep(step, idx) {
  const delta = typeof step.confidenceDelta === "number" ? `<span class="stream-delta">${step.confidenceDelta > 0 ? "+" : ""}${step.confidenceDelta.toFixed(2)}</span>` : "";
  return `<li class="analysis-step ${escapeHtml(step.status || "pending")}">
    <span class="step-index">${idx + 1}</span>
    <div><strong>${escapeHtml(step.title || step.label)}</strong><p>${escapeHtml(step.detail || "Awaiting Workbench Engine trace")}</p></div>
    <span class="step-state">${escapeHtml(step.statusLabel || step.status || "Pending")}</span>${delta}
  </li>`;
}

function pills(labels) {
  return labels.map((label, index) => `<span class="badge ${index === 3 ? "success" : "neutral"}">${escapeHtml(label)}</span>`).join("");
}

function modeCard({ mode, active, title, detail, rows, action, actionLabel }) {
  return `<article class="intake-card ${active ? "active" : ""}">
    <div><span class="mode-dot"></span><h4>${escapeHtml(title)}</h4><p>${escapeHtml(detail)}</p></div>
    <ul>${rows.map((row) => `<li>${escapeHtml(row)}</li>`).join("")}</ul>
    <button class="button ${active ? "primary" : "secondary"}" data-action="${escapeHtml(action)}" type="button">${escapeHtml(actionLabel)}</button>
  </article>`;
}

function artifactList(runtime) {
  const artifacts = runtime.analysis.artifacts || [];
  if (!artifacts.length) return "No uploaded artifacts yet";
  return artifacts.map((artifact) => `${artifact.filename} (${artifact.rows_detected || artifact.rows || 0} rows · ${artifact.source_kind || "source"})`).join("; ");
}

function sourceSummary(result) {
  const summary = result?.data_sources;
  if (!summary) return ["Files: pending", "Rows parsed: pending", "Source kinds: pending"];
  return [
    `Files: ${summary.file_count}`,
    `Rows parsed: ${summary.rows_parsed}`,
    `Source kinds: ${(summary.source_kinds_detected || []).join(", ")}`,
  ];
}

function signalSummary(result) {
  const summary = result?.signal_summary || {};
  return [
    ["Controller events", summary.controller_events_read],
    ["Weather records", summary.weather_records_read],
    ["Soil readings", summary.soil_readings_read],
    ["Field notes", summary.field_notes_parsed],
    ["Flow-meter records", summary.flow_meter_records_read],
    ["Crop profiles", summary.crop_profile_loaded],
    ["Earth observation rows", summary.satellite_observations_read],
  ];
}

function recommendationBlock(runtime) {
  const rec = runtime.activeRecommendation;
  const ready = runtime.analysis.status === "complete" && rec;
  if (!ready) {
    return `<article class="recommendation-main muted-block"><h4>Waiting for intelligence analysis</h4><p>Select an intake mode, then run the Workbench Engine to produce action, timing, depth, confidence, limitations, and verification requirements.</p></article>`;
  }
  const drivers = rec.keyDrivers || rec.key_drivers || [];
  return `<article class="recommendation-main">
    <div class="recommendation-head"><div><h4>${escapeHtml(rec.action || rec.decision)}</h4><p>${escapeHtml(rec.sourceTraceSummary || "Decision reasoning produced by the Workbench Engine.")}</p></div><span class="badge success">${escapeHtml(rec.confidence || "Confidence ready")}</span></div>
    <div class="metric-row command-metrics">
      <span>Duration: ${escapeHtml(rec.duration || "See result")}</span>
      <span>Depth: ${escapeHtml(rec.depth || "See result")}</span>
      <span>Start: ${escapeHtml(rec.start_time || rec.timing || "See result")}</span>
      <span>Data quality: ${escapeHtml(rec.dataQuality || rec.confidence_label || "Evidence scored")}</span>
    </div>
    <div class="recommendation-detail-grid">
      <div><h5>Key drivers</h5><ul>${drivers.map((driver) => `<li>${escapeHtml(driver)}</li>`).join("")}</ul></div>
      <div><h5>Limitations</h5><p>${escapeHtml(formatValue(rec.limitations || rec.missingInputs, "No material limitation reported"))}</p></div>
      <div><h5>Verification requirement</h5><p>${escapeHtml(rec.verification_requirement || rec.verificationPlan || "Verify after controller execution and field observation.")}</p></div>
    </div>
  </article>`;
}

function traceDetails(result) {
  if (!result) return "";
  const context = result.normalized_context || {};
  const report = result.report_summary || {};
  return `<details class="technical-trace command-trace"><summary>Advanced Technical Trace</summary>
    <div class="trace-grid">
      <div><h4>Normalized Context</h4><ul>
        <li>Farm: ${escapeHtml(context.farm || "pending")}</li>
        <li>Block: ${escapeHtml(context.block || "pending")}</li>
        <li>Crop: ${escapeHtml(context.crop || "pending")}</li>
        <li>Soil: ${escapeHtml(context.soil || "pending")}</li>
        <li>Irrigation: ${escapeHtml(context.irrigation_method || "pending")}</li>
      </ul></div>
      <div><h4>Data Sources</h4><ul>${sourceSummary(result).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>
      <div><h4>Report Artifact</h4><ul>
        <li>Evidence completeness: ${escapeHtml(report.evidence_completeness || "pending")}</li>
        <li>Applied variance: ${escapeHtml(report.applied_variance || "pending")}</li>
        <li>Compliance posture: ${escapeHtml(report.compliance_posture || "pending")}</li>
      </ul></div>
    </div>
  </details>`;
}

export function renderCommandCenter(state) {
  const runtime = state.demoRuntime;
  const result = runtime.analysis.backendResult;
  const ready = runtime.analysis.status === "complete";
  const chain = runtime.operatingChain;
  const snapshot = runtime.reportSnapshots?.[0];
  const intakeMode = runtime.intakeMode;
  const connectedActive = intakeMode === "connected";
  const uploadActive = intakeMode === "upload";
  const sampleActive = intakeMode === "sample" || intakeMode === "uploaded";

  return `<div class="workbench-flow water-command-center">
    <section class="panel-card workspace-header-card command-hero">
      <div>
        <p class="eyebrow">Alpha Vineyard · Water Command Center</p>
        <h2>Scattered irrigation data becomes a verified water decision.</h2>
        <p>AGRO-AI reads controller history, weather, soil context, field observations, and uploaded records to produce recommendations, reconciliation, verification, and reporting.</p>
      </div>
      <div class="header-badges">${pills(["Evaluation mode", "Mixed sources", "Evidence chain active", "Backend intelligence online"])}</div>
    </section>

    <section class="panel-card command-section">
      <div class="section-heading numbered-heading"><span>01</span><div><h3>Source intake</h3><p>Choose the evidence path the Workbench Engine should analyze.</p></div></div>
      <div class="intake-grid">
        ${modeCard({
          mode: "connected",
          active: connectedActive,
          title: "Connected field",
          detail: "Uses live Workbench analysis when provider access is available.",
          rows: ["POST /v1/workbench/analyze-live", "Default source: wiseconn", "Default entity_id: 162803"],
          action: "use-connected-field",
          actionLabel: "Use connected field",
        })}
        <article class="intake-card ${uploadActive ? "active" : ""}">
          <div><span class="mode-dot"></span><h4>Upload records</h4><p>Upload CSV, JSON, TXT, or XLSX field records for session analysis.</p></div>
          <ul><li>POST /v1/workbench/sessions/{session_id}/upload</li><li>POST /v1/workbench/sessions/{session_id}/analyze</li><li>${escapeHtml(artifactList(runtime))}</li></ul>
          <input id="workbench-upload-input" type="file" accept=".csv,.json,.txt,.xlsx" />
          <button class="button ${uploadActive ? "primary" : "secondary"}" data-action="use-upload-records" type="button">Use uploaded records</button>
        </article>
        ${modeCard({
          mode: "sample",
          active: sampleActive,
          title: "Sample data package",
          detail: "Loads the expanded Workbench sample package through the backend.",
          rows: ["Controller events, weather, soil, field notes", "Flow meter, crop profile, water costs", "Earth observation sample layer"],
          action: "load-sample-data-package",
          actionLabel: "Use sample data package",
        })}
      </div>
      <div class="runtime-actions intake-actions">
        <button class="button secondary" data-action="download-sample-package" type="button">Download sample CSV package</button>
        <button class="button secondary" data-action="view-accepted-fields" type="button">View accepted fields</button>
        <button class="button secondary" data-action="view-analysis-schema" type="button">View analysis schema</button>
      </div>
      <p class="muted">Selected intake: ${escapeHtml(runtime.intakeModeLabel)}</p>
    </section>

    <section class="panel-card command-section intelligence-stream-card ${runtime.analysis.running ? "stream-running" : ""}">
      <div class="section-heading numbered-heading"><span>02</span><div><h3>Intelligence stream</h3><p>Sources move through normalization, reconciliation, decisioning, and verification planning.</p></div></div>
      <div class="intelligence-stream" aria-label="AGRO-AI intelligence stream">
        <div class="stream-track">
          ${["Sources", "Normalize", "Reconcile", "Decide", "Verify"].map((node, index) => `<div class="stream-node node-${index + 1}"><span></span><strong>${node}</strong></div>`).join("")}
          <i class="particle p1"></i><i class="particle p2"></i><i class="particle p3"></i><i class="droplet d1"></i><i class="droplet d2"></i>
        </div>
      </div>
      <div class="stream-readout">
        <ul class="analysis-list">${runtime.analysis.steps.map(fmtStep).join("")}</ul>
        <aside class="source-summary"><h4>Source signal summary</h4>${signalSummary(result).map(([label, value]) => `<p><span>${escapeHtml(label)}</span><strong>${escapeHtml(value ?? "pending")}</strong></p>`).join("")}</aside>
      </div>
      <div class="runtime-actions">
        <button class="button primary" data-action="run-ai-analysis" ${runtime.analysis.running || !runtime.intakeMode ? "disabled" : ""} type="button">${runtime.analysis.running ? "Analyzing..." : "Run intelligence analysis"}</button>
        <p class="muted">${escapeHtml(runtime.analysis.statusLabel)}</p>
      </div>
    </section>

    <section class="panel-card command-section">
      <div class="section-heading numbered-heading"><span>03</span><div><h3>Recommendation</h3><p>The Decision Engine returns action, timing, depth, confidence, drivers, limitations, and verification requirement.</p></div></div>
      ${recommendationBlock(runtime)}
      <div class="runtime-actions"><button class="button secondary" data-action="schedule" ${!ready ? "disabled" : ""} type="button">Schedule recommendation</button><button class="button secondary" data-action="mark-applied" ${!ready ? "disabled" : ""} type="button">Mark as applied</button><button class="button secondary" data-action="add-observation" ${!ready ? "disabled" : ""} type="button">Add observation</button><button class="button secondary" data-action="verify" ${!ready ? "disabled" : ""} type="button">Verify outcome</button></div>
    </section>

    <section class="panel-card command-section">
      <div class="section-heading numbered-heading"><span>04</span><div><h3>Reconciliation and verification</h3><p>Source Reconciliation shows how the engine resolved field evidence before the Verification Chain moves forward.</p></div></div>
      <div class="two-column reconciliation-verification-grid">
        <div class="table-wrap"><table class="data-table"><thead><tr><th>Source</th><th>Signal</th><th>Interpretation</th><th>Status</th></tr></thead><tbody>${runtime.reconciliationRows.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
        <div class="verification-chain">${chain.map((step) => `<div class="chain-line"><strong>${escapeHtml(step.label)}</strong><span>${escapeHtml(step.status)}</span><small>${escapeHtml(step.timestamp || "pending")} · ${escapeHtml(step.owner)}</small><p>${escapeHtml(step.evidence)}</p></div>`).join("")}</div>
      </div>
    </section>

    <section class="panel-card command-section">
      <div class="section-heading numbered-heading"><span>05</span><div><h3>Report preview</h3><p>Report Center receives the same evidence package used by the recommendation and verification chain.</p></div></div>
      <div class="report-preview-object">
        <p>Farm: ${escapeHtml(snapshot?.farm || "Alpha Vineyard")} · Block: ${escapeHtml(snapshot?.block || "Block A North")} · Crop: ${escapeHtml(snapshot?.crop || "Cabernet Sauvignon")}</p>
        <p>Recommendation: ${escapeHtml(snapshot?.recommendation || "Awaiting analysis")}</p>
        <p>Evidence completeness: ${escapeHtml(snapshot?.evidenceCompleteness || result?.reconciliation?.evidence_completeness || "pending")} · Compliance posture: ${escapeHtml(snapshot?.compliancePosture || result?.report_summary?.compliance_posture || "pending")}</p>
      </div>
      <div class="runtime-actions"><button class="button secondary" data-action="preview-report" type="button">Preview report</button><button class="button secondary" data-action="export-csv" ${snapshot ? "" : "disabled"} type="button">Export CSV</button><button class="button secondary" data-action="print-report" type="button">Print report</button></div>
    </section>

    <section class="panel-card command-section decision-reasoning">
      <div class="section-heading"><p class="eyebrow">Decision reasoning</p><h3>From scattered data to verified action</h3><p>The Intelligence Engine exposes the verification path behind the recommendation instead of presenting a static card.</p></div>
      <div class="metric-row">${sourceSummary(result).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}<span>Confidence: ${escapeHtml(result?.reconciliation?.confidence_score ?? "pending")}</span></div>
      ${traceDetails(result)}
    </section>
  </div>`;
}
