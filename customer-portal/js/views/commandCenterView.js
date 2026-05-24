import { escapeHtml } from "../components/dom.js";

const FALLBACK = {
  decision: "Irrigate 42 min tonight",
  start: "21:00 PT",
  depth: "12 mm net",
  confidence: "86 percent",
  evidence: "92 percent",
  savings: "27 percent",
};

function sourceRows(runtime) {
  const backend = runtime.analysis.backendResult;
  const dataSources = backend?.data_sources || [];
  const findKind = (k) => dataSources.find((s) => s.source_kind === k);
  return [
    ["Controller history", findKind("controller_logs")],
    ["Weather demand", findKind("weather")],
    ["Soil moisture", findKind("soil_moisture")],
    ["Flow meter", findKind("irrigation_records")],
    ["Field observation", findKind("field_notes")],
    ["Earth observation layer", null],
  ];
}

export function renderCommandCenter(state) {
  const runtime = state.demoRuntime;
  const b = runtime.analysis.backendResult;
  const rec = b?.recommendation || {};
  const recon = b?.reconciliation || {};
  const report = b?.report_summary || runtime.reportSnapshots?.[0] || {};
  const decision = rec.decision || FALLBACK.decision;
  return `<div class="command-surface">
<section class="summary-strip panel-card">
<div><label>Water decision</label><strong>${escapeHtml(decision)}</strong></div>
<div><label>Confidence</label><strong>${escapeHtml(String(recon.confidence_score ? `${Math.round(recon.confidence_score*100)} percent` : FALLBACK.confidence))}</strong></div>
<div><label>Evidence completeness</label><strong>${escapeHtml(recon.evidence_completeness || FALLBACK.evidence)}</strong></div>
<div><label>Estimated water savings</label><strong>${escapeHtml(FALLBACK.savings)}</strong></div>
</section>

<section class="ops-canvas">
<article class="panel-card source-intelligence"><h3>Source intelligence</h3><div class="source-mode"><button class="button ${runtime.intakeMode==='connected'?'primary':'secondary'}" data-action="mode-connected">Connected source</button><button class="button ${runtime.intakeMode==='uploaded'?'primary':'secondary'}" data-action="mode-upload">Upload records</button><button class="button ${runtime.intakeMode==='pilot'?'primary':'secondary'}" data-action="mode-pilot">Pilot data package</button></div><input id="workbench-upload-input" type="file" accept=".csv,.json,.txt,.xlsx" />
${sourceRows(runtime).map(([label,src])=>`<div class="source-row"><div><strong>${label}</strong><p>${src?`${src.rows} records processed`:'Awaiting source signal'}</p></div><span>${src?src.source_kind:'Not included in current analysis'}</span></div>`).join('')}
<p class="muted">Earth observation sample layer included for partner evaluation. Live partner feeds require connector authorization.</p>
</article>
<article class="panel-card intelligence-processing"><h3>Intelligence processing</h3><div class="intelligence-grid">${runtime.analysis.steps.map((s,i)=>`<div class="stage ${s.status}"><span>${i+1}</span><div><strong>${escapeHtml(s.label.replace('AI',''))}</strong><p>${escapeHtml(s.detail)}</p></div></div>`).join('')}</div><button class="button primary" data-action="run-ai-analysis" ${runtime.analysis.running?'disabled':''}>${runtime.analysis.running?'Processing…':'Run intelligence analysis'}</button></article>
<article class="panel-card decision-panel"><h3>Verified water decision</h3><h2>${escapeHtml(decision)}</h2><p>Start ${escapeHtml(rec.start || FALLBACK.start)} · Apply ${escapeHtml(String(rec.depth_mm ? `${rec.depth_mm} mm net` : FALLBACK.depth))}</p><ul><li>Crop: Cabernet Sauvignon</li><li>Block: Block A North</li><li>Driver: ETo 6.4 mm and 38 percent deficit at 30 cm</li><li>Confidence: ${escapeHtml(String(recon.confidence_label || FALLBACK.confidence))}</li><li>Verification: required</li></ul><div class="runtime-actions"><button class="button secondary" data-action="schedule">Approve schedule</button><button class="button secondary" data-action="mark-applied">Confirm applied water</button><button class="button secondary" data-action="add-observation">Add field observation</button><button class="button secondary" data-action="verify">Verify outcome</button><button class="button secondary" data-action="open-report">Open report</button></div></article>
</section>

<section class="evidence-area two-column">
<article class="panel-card"><h3>Reconciliation</h3><div class="table-wrap"><table class="data-table"><thead><tr><th>Source</th><th>Signal</th><th>Interpretation</th><th>Status</th></tr></thead><tbody>${(runtime.reconciliationRows||[]).map((r)=>`<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td></tr>`).join('')}</tbody></table></div></article>
<article class="panel-card"><h3>Executive report preview</h3><p>Farm: ${escapeHtml(report.farm || 'Alpha Vineyard')}</p><p>Block: ${escapeHtml(report.block || 'Block A North')}</p><p>Recommendation: ${escapeHtml(report.recommendation || decision)}</p><p>Applied water: ${escapeHtml(report.appliedAction || 'Awaiting source signal')}</p><p>Verification status: ${escapeHtml(report.verificationStatus || 'Verification required')}</p><div class="runtime-actions"><button class="button secondary" data-action="preview-report">Preview report</button><button class="button secondary" data-action="export-csv">Export CSV</button><button class="button secondary" data-action="print-report">Print report</button></div></article>
</section></div>`;
}
