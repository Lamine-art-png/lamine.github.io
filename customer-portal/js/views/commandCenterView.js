import { escapeHtml } from "../components/dom.js";

function fmtStep(step, idx){
  return `<li class="analysis-step ${step.status}"><span class="step-index">${idx+1}</span><div><strong>${escapeHtml(step.label)}</strong><p>${escapeHtml(step.detail||"")}</p></div><span class="step-state">${escapeHtml(step.statusLabel)}</span></li>`;
}

export function renderCommandCenter(state) {
  const runtime = state.demoRuntime;
  const rec = runtime.activeRecommendation;
  const ready = runtime.analysis.status === "complete";
  const chain = runtime.operatingChain;
  const snapshot = runtime.reportSnapshots?.[0];
  return `<div class="workbench-flow">
  <section class="panel-card workspace-header-card"><div><p class="eyebrow">Alpha Vineyard · AI Workbench</p><h2>AGRO-AI turns scattered irrigation data into verified water decisions.</h2></div><div class="header-badges"><span class="badge neutral">Mode: Demo</span><span class="badge neutral">Source: Mixed</span><span class="badge success">Status: Evidence chain active</span></div></section>

  <section class="panel-card"><h3>1. Data Intake</h3><p>Connect live controller environments or upload field records for AGRO-AI analysis.</p>
  <div class="two-column intake-grid"><article class="intake-card"><h4>Connected field context</h4><ul><li>WiseConn controller history</li><li>Talgil runtime reachable</li><li>Weather and ETo</li><li>Crop and soil profile</li><li>Field observation</li></ul><button class="button secondary" data-action="use-connected-field">Use connected field</button></article>
  <article class="intake-card"><h4>Upload data package</h4><ul><li>controller_events.csv</li><li>weather_summary.csv</li><li>soil_moisture.csv</li><li>field_notes.txt</li></ul><button class="button secondary" data-action="load-demo-data-package">Load demo data package</button><small>Demo intake simulation. Production upload requires backend ingestion endpoint.</small></article></div>
  <p class="muted">Selected intake: ${escapeHtml(runtime.intakeModeLabel)}</p></section>

  <section class="panel-card"><h3>2. AI Analysis</h3><p>AGRO-AI normalizes messy inputs, reconciles source conflicts, and prepares a block-level recommendation.</p>
  <ul class="analysis-list">${runtime.analysis.steps.map(fmtStep).join("")}</ul>
  <button class="button primary" data-action="run-ai-analysis" ${runtime.analysis.running||!runtime.intakeMode?"disabled":""}>${runtime.analysis.running?"Analyzing…":"Run AI analysis"}</button>
  <p class="muted">${escapeHtml(runtime.analysis.statusLabel)}</p>
  <div class="three-column transform"><article><h4>Raw inputs</h4><ul><li>Controller logs</li><li>Sensor exports</li><li>ETo and rain forecast</li><li>Field observation notes</li><li>Crop and soil profile</li></ul></article><article><h4>AGRO-AI reasoning</h4><ul><li>Units normalized</li><li>Time windows aligned</li><li>Source conflicts checked</li><li>Confidence scored</li><li>Planned vs applied reconciled</li></ul></article><article><h4>Clean output</h4><ul><li>Irrigate 42 min tonight</li><li>Apply 12 mm net</li><li>Start 21:00 PT</li><li>Confidence 86%</li><li>Verification required</li></ul></article></div></section>

  <section class="panel-card"><h3>3. Recommendation</h3><article class="recommendation-main ${ready?"":"muted-block"}"><h4>${ready?"Irrigate 42 min tonight · start 21:00 PT":"Waiting for analysis"}</h4><p>12 mm net across Block A North · responding to ETo 6.4 mm and 38% deficit at 30 cm.</p><div class="metric-row"><span>Duration: 42 min</span><span>Depth: 12 mm net</span><span>Start: 21:00 PT</span><span>Confidence: 86%</span><span>Data quality: Verified telemetry</span></div><p>Execution task: Schedule in controller and verify observed response.</p></article>
  <div class="runtime-actions"><button class="button secondary" data-action="schedule" ${!ready?"disabled":""}>Schedule recommendation</button><button class="button secondary" data-action="mark-applied" ${!ready?"disabled":""}>Mark as applied</button><button class="button secondary" data-action="add-observation" ${!ready?"disabled":""}>Add observation</button><button class="button secondary" data-action="verify" ${!ready?"disabled":""}>Verify outcome</button></div></section>

  <section class="panel-card"><h3>4. Reconciliation and Verification</h3><div class="two-column"><div class="table-wrap"><table class="data-table"><thead><tr><th>Source</th><th>Signal</th><th>AGRO-AI interpretation</th><th>Status</th></tr></thead><tbody>${runtime.reconciliationRows.map((r)=>`<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td></tr>`).join("")}</tbody></table></div><div>${chain.map((s)=>`<div class="chain-line"><strong>${s.label}</strong><span>${s.status}</span><small>${s.timestamp||"pending"} · ${s.owner}</small><p>${s.evidence}</p></div>`).join("")}</div></div></section>

  <section class="panel-card"><h3>5. Report Preview</h3><p>Executive report preview</p><div class="report-card"><p>Farm: Alpha Vineyard · Block: Block A North · Crop: Cabernet Sauvignon</p><p>Recommendation: 42 min tonight, 12 mm net</p><p>Verification status: ${chain[4].status}</p></div><div class="runtime-actions"><button class="button secondary" data-action="preview-report">Preview report</button><button class="button secondary" data-action="export-csv" ${snapshot?"":"disabled"}>Export CSV</button><button class="button secondary" data-action="print-report">Print report</button></div></section>

  <section class="panel-card"><h3>AI reasoning summary</h3><p>AGRO-AI detected high water demand from ETo, confirmed recent controller history, checked applied-water evidence, and generated a verified irrigation recommendation with an execution and observation plan.</p><div class="metric-row"><span>Inputs used: 7</span><span>Conflicts resolved: 1</span><span>Confidence: 86%</span><span>Verification required: Yes</span></div></section>
  </div>`;
}
