import { escapeHtml, formatDate } from "../components/dom.js";
import { isAssuranceEvaluationMode, passportPackage } from "./assuranceView.js";

function activePackage(state) {
  return passportPackage(state);
}

function evidenceRecords(state) {
  const pkg = activePackage(state);
  if (!isAssuranceEvaluationMode(state) && !state.assurance.activePassportId && !state.assurance.activePassport?.passport) {
    return [];
  }
  const uploaded = state.demoRuntime.analysis?.artifacts || [];
  return [
    ...(pkg.evidence || []).map((row) => ({
      evidence_type: row.evidence_type || "evidence",
      filename: row.filename || row.file_ref || "metadata",
      proof_domain: row.proof_domain || "proof",
      linked_passport: pkg.passport?.id || state.assurance.activePassportId || "unlinked",
      confidence: row.confidence || "needs review",
      review_status: row.review_status || "pending_review",
      issue: row.issue || "Reviewer evaluation required",
      source_system: row.source_system || "workspace",
      checksum: row.checksum || "not provided",
      created_at: row.created_at || "",
    })),
    ...uploaded.map((row) => ({
      evidence_type: row.source_type || row.detected_type || "uploaded_record",
      filename: row.filename || "uploaded file",
      proof_domain: row.proof_domain || "unclassified",
      linked_passport: state.assurance.activePassportId || "not linked",
      confidence: row.confidence || "classification pending",
      review_status: row.parse_status || row.status || "accepted",
      issue: row.warning || row.warnings?.join("; ") || "Link to proof domain",
      source_system: "Workbench upload",
      checksum: row.checksum || row.artifact_id || "not provided",
      created_at: row.created_at || "",
    })),
  ];
}

function extractedFacts(records) {
  return records.slice(0, 6).map((row) => ({
    fact: row.evidence_type.replaceAll("_", " "),
    source: row.filename,
    domain: row.proof_domain,
    review: row.review_status,
  }));
}

export function renderEvidence(state) {
  const isEvaluation = isAssuranceEvaluationMode(state);
  const liveNoPassport = !isEvaluation && !state.assurance.activePassportId && !state.assurance.activePassport?.passport;
  const records = evidenceRecords(state);
  const facts = extractedFacts(records);

  return `<section class="page-stack evidence-page">
    <section class="enterprise-hero">
      <div>
        <p class="eyebrow">Evidence Intelligence</p>
        <h2>Evidence Vault</h2>
        <p>${escapeHtml(liveNoPassport ? "Backend auth required for live Assurance APIs. No demo passport was loaded." : "Uploaded files, extracted facts, proof linkage, review state, and audit references in one workspace.")}</p>
      </div>
      <div class="hero-actions">
        <span class="status-chip subtle">${escapeHtml(isEvaluation ? "Evaluation data · not live" : "Backend auth required")}</span>
        <button class="button primary" data-action="open-source-drawer" type="button">Attach records</button>
      </div>
    </section>

    ${liveNoPassport ? '<section class="premium-empty-state live-assurance-empty"><h3>Create or connect a live Assurance Passport</h3><p>Backend auth required for live Assurance APIs. No demo passport was loaded.</p><button class="button primary" data-view="assurance" type="button">Open Assurance</button></section>' : ""}

    <section class="panel">
      <div class="panel-head"><p class="eyebrow">Evidence Vault Table</p><h3>Records prepared for proof packages</h3></div>
      <div class="table-wrap"><table class="data-table"><thead><tr><th>Evidence type</th><th>Uploaded file</th><th>Linked passport</th><th>Proof domain</th><th>Confidence / review state</th><th>Unresolved issues</th><th>Source system</th><th>Checksum / audit ref</th></tr></thead><tbody>
        ${records.length ? records.map((row) => `<tr>
          <td>${escapeHtml(row.evidence_type)}</td>
          <td>${escapeHtml(row.filename)}</td>
          <td>${escapeHtml(row.linked_passport)}</td>
          <td>${escapeHtml(row.proof_domain)}</td>
          <td>${escapeHtml(row.confidence)} · ${escapeHtml(row.review_status)}</td>
          <td>${escapeHtml(row.issue)}</td>
          <td>${escapeHtml(row.source_system)}</td>
          <td>${escapeHtml(row.checksum)}</td>
        </tr>`).join("") : '<tr><td colspan="8">No evidence records loaded. Attach records to begin proof linkage.</td></tr>'}
      </tbody></table></div>
    </section>

    <section class="grid two-col enterprise-split">
      <article class="panel">
        <div class="panel-head"><p class="eyebrow">Extracted Facts</p><h3>Detected record types</h3></div>
        <div class="enterprise-list">
          ${facts.length ? facts.map((fact) => `<div class="enterprise-list-row"><span class="status-chip">${escapeHtml(fact.domain)}</span><div><strong>${escapeHtml(fact.fact)}</strong><p>${escapeHtml(fact.source)} · ${escapeHtml(fact.review)}</p></div><em>needs review</em></div>`).join("") : '<p class="muted">No extracted facts available yet.</p>'}
        </div>
      </article>
      <article class="panel">
        <div class="panel-head"><p class="eyebrow">Audit Reference</p><h3>Review-safe provenance</h3></div>
        <dl class="setup-brief">
          <div><dt>Workspace status</dt><dd>${escapeHtml(isEvaluation ? "Evaluation workspace · no live source claim" : state.session.authNotice || "Backend auth required")}</dd></div>
          <div><dt>Records loaded</dt><dd>${escapeHtml(String(records.length))}</dd></div>
          <div><dt>Latest record</dt><dd>${escapeHtml(records[0]?.created_at ? formatDate(records[0].created_at) : "unavailable")}</dd></div>
          <div><dt>External use</dt><dd>Reviewer evaluation required before using a proof package outside the workspace.</dd></div>
        </dl>
      </article>
    </section>
  </section>`;
}
