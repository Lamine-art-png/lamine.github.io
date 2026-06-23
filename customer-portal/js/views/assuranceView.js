import { escapeHtml } from "../components/dom.js";

export const demoAssurance = {
  passport: {
    id: "demo-passport-alpha-vineyard",
    farm_name: "Alpha Vineyard",
    farm_location: "Evaluation workspace",
    crop: "Wine grapes",
    season: "2026",
    reporting_period: "2026",
    status: "missing_proof",
    rule_pack_ids: ["waterops_generic_v0_1", "buyer_input_records_v0_1", "farm_finance_risk_pack_v0_1"],
  },
  readiness: {
    readiness_score: 62,
    risk_level: "medium",
    status: "missing_proof",
    missing_evidence: [
      { requirement_key: "water_measurement_available", section_type: "water_proof", severity: "required", needed_evidence_types: ["water_measurement"] },
      { requirement_key: "farm_boundary_reference", section_type: "farm_summary", severity: "required", needed_evidence_types: ["farm_boundary"] },
      { requirement_key: "lot_traceability_events", section_type: "traceability_proof", severity: "required", needed_evidence_types: ["traceability_record"] },
      { requirement_key: "input_application_records", section_type: "input_proof", severity: "required", needed_evidence_types: ["input_application_record"] },
    ],
    proof_counts: { water_budget: 1, risk_context: 1 },
    scope: { readiness_package_only: true, authority_submission: false, live_source_complete: false },
  },
  evidence: [
    { evidence_type: "controller_events", proof_domain: "water_proof", filename: "controller_events.csv", source_system: "workbench_upload", truth_label: "reported", review_status: "pending_review", checksum: "demo", created_at: "2026-06-22T00:00:00" },
    { evidence_type: "weather_context", proof_domain: "water_proof", filename: "weather.csv", source_system: "evaluation_workspace", truth_label: "reported", review_status: "pending_review", checksum: "demo", created_at: "2026-06-22T00:00:00" },
    { evidence_type: "crop_profile", proof_domain: "farm_summary", filename: "crop_profile.csv", source_system: "evaluation_workspace", truth_label: "reported", review_status: "pending_review", checksum: "demo", created_at: "2026-06-22T00:00:00" },
  ],
  input_applications: [],
  harvest_lots: [],
  traceability_events: [],
};

export const demoAgent = {
  summary: "AGRO-AI can classify uploaded records, attach evidence, refresh readiness, and prepare a review packet. Human approval is required before external use.",
  proof_present: ["controller_events.csv", "weather.csv", "crop_profile.csv"],
  missing_proof: demoAssurance.readiness.missing_evidence,
  risk_flags: [{ summary: "Readiness remains incomplete until missing proof is attached.", severity: "needs_review" }],
  next_best_action: { title: "Attach water measurement proof" },
  automation_plan: ["Classify uploaded records", "Attach evidence metadata", "Refresh readiness", "Prepare review packet"],
  needs_approval: ["External use", "Submission language", "Any certification or legal status change"],
};

function passportPackage(state) {
  const active = state.assurance.activePassport;
  if (active?.passport) return active;
  return demoAssurance;
}

function statusChip(value) {
  return `<span class="status-chip">${escapeHtml(value || "unavailable")}</span>`;
}

function tableRows(rows, empty, mapper) {
  return rows?.length ? rows.map(mapper).join("") : `<tr><td colspan="8">${escapeHtml(empty)}</td></tr>`;
}

export function renderAssurance(state) {
  const isEvaluation = state.session.mode === "demo";
  const pkg = passportPackage(state);
  const passport = pkg.passport;
  const readiness = state.assurance.readiness || pkg.readiness || {};
  const evidence = pkg.evidence || [];
  const agent = state.agent.activeRun?.result || demoAgent;
  const authNote = state.session.mode === "live" ? `<p class="alert">Backend auth required for live Assurance APIs. No tenant API key is stored in the browser.</p>` : "";

  return `<section class="page-stack assurance-page">
    <section class="hero-panel">
      <div>
        <p class="eyebrow">${isEvaluation ? "Evaluation workspace · not live · not certified" : "Assurance OS"}</p>
        <h2>Assurance Passport</h2>
        <p>${escapeHtml(passport.farm_name || "Farm unavailable")} · ${escapeHtml(passport.crop || "Crop unavailable")} · ${escapeHtml(passport.season || "Season unavailable")} · ${escapeHtml(passport.reporting_period || "Period unavailable")}</p>
        ${authNote}
      </div>
      <div class="score-stack">
        <strong>${escapeHtml(String(readiness.readiness_score ?? "—"))}%</strong>
        <span>audit readiness</span>
        ${statusChip(readiness.status || passport.status)}
        ${statusChip(`risk: ${readiness.risk_level || "unavailable"}`)}
      </div>
    </section>

    <div class="chip-row">${(passport.rule_pack_ids || []).map((pack) => statusChip(pack)).join("")}</div>

    <section class="grid two-col">
      <article class="panel">
        <div class="panel-head"><p class="eyebrow">AI Agent Panel</p><h3>What AGRO-AI sees</h3></div>
        <dl class="setup-brief">
          <div><dt>Proof present</dt><dd>${escapeHtml((agent.proof_present || evidence.map((row) => row.filename || row.evidence_type)).join(", ") || "Unavailable")}</dd></div>
          <div><dt>Proof missing</dt><dd>${escapeHtml((agent.missing_proof || readiness.missing_evidence || []).map((row) => row.requirement_key).join(", ") || "No missing checklist proof detected")}</dd></div>
          <div><dt>Risk created</dt><dd>${escapeHtml((agent.risk_flags || []).map((row) => row.summary).join("; ") || "No additional risk flags detected")}</dd></div>
          <div><dt>Next best action</dt><dd>${escapeHtml(agent.next_best_action?.title || "Refresh readiness")}</dd></div>
          <div><dt>Can automate now</dt><dd>${escapeHtml((agent.automation_plan || []).map((row) => row.title || row).join(", ") || "Refresh readiness")}</dd></div>
          <div><dt>Needs human approval</dt><dd>${escapeHtml((agent.needs_approval || ["External use", "submission language"]).join(", "))}</dd></div>
        </dl>
      </article>
      <article class="panel">
        <div class="panel-head"><p class="eyebrow">Actions</p><h3>Proof workflow</h3></div>
        <div class="action-grid">
          <button class="button primary" data-action="run-assurance-agent" type="button">Run AGRO-AI Agent</button>
          <button class="button secondary" data-action="open-source-drawer" type="button">Attach records</button>
          <button class="button secondary" data-action="add-input-record-note" type="button">Add input record</button>
          <button class="button secondary" data-action="add-harvest-lot-note" type="button">Add harvest lot</button>
          <button class="button secondary" data-action="add-traceability-note" type="button">Add traceability event</button>
          <button class="button secondary" data-action="refresh-assurance-readiness" type="button">Refresh readiness</button>
          <button class="button primary" data-action="generate-assurance-pdf" type="button">Generate Assurance PDF</button>
        </div>
      </article>
    </section>

    <section class="panel">
      <div class="panel-head"><p class="eyebrow">Missing Proof Queue</p><h3>Reviewer evaluation blockers</h3></div>
      <table class="data-table"><thead><tr><th>Requirement</th><th>Domain</th><th>Severity</th><th>Needed evidence</th><th>Suggested action</th><th>Status</th></tr></thead><tbody>
        ${tableRows(readiness.missing_evidence || [], "No missing checklist proof detected.", (row) => `<tr><td>${escapeHtml(row.requirement_key)}</td><td>${escapeHtml(row.section_type)}</td><td>${escapeHtml(row.severity)}</td><td>${escapeHtml((row.needed_evidence_types || []).join(", "))}</td><td>Attach evidence or request document</td><td>needs review</td></tr>`)}
      </tbody></table>
    </section>

    <section class="panel">
      <div class="panel-head"><p class="eyebrow">Evidence Vault</p><h3>Evidence-backed records</h3></div>
      <table class="data-table"><thead><tr><th>Evidence type</th><th>Proof domain</th><th>Filename</th><th>Source system</th><th>Truth label</th><th>Review status</th><th>Checksum</th><th>Created</th></tr></thead><tbody>
        ${tableRows(evidence, "No evidence attached.", (row) => `<tr><td>${escapeHtml(row.evidence_type)}</td><td>${escapeHtml(row.proof_domain)}</td><td>${escapeHtml(row.filename || row.file_ref || "metadata")}</td><td>${escapeHtml(row.source_system)}</td><td>${escapeHtml(row.truth_label)}</td><td>${escapeHtml(row.review_status)}</td><td>${escapeHtml(row.checksum || "not provided")}</td><td>${escapeHtml(row.created_at || "unavailable")}</td></tr>`)}
      </tbody></table>
    </section>

    <section class="grid three-col">
      <article class="panel"><h3>Water Proof</h3><p>Wells, meters, water budgets, and measurements are counted only when scoped to this passport.</p><strong>${escapeHtml(readiness.status || "unavailable")}</strong></article>
      <article class="panel"><h3>Input Proof</h3><p>Input applications: ${escapeHtml(String((pkg.input_applications || []).length))}. Pesticide and fertilizer details remain needs review when not provided.</p></article>
      <article class="panel"><h3>Traceability Proof</h3><p>Harvest lots: ${escapeHtml(String((pkg.harvest_lots || []).length))}; events: ${escapeHtml(String((pkg.traceability_events || []).length))}. Buyer/export readiness requires reviewer evaluation.</p></article>
    </section>
  </section>`;
}

