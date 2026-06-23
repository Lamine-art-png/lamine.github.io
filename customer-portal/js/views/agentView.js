import { escapeHtml } from "../components/dom.js";
import { demoAgent } from "./assuranceView.js";

const timeline = ["Ingest", "Normalize", "Classify", "Reconcile", "Detect missing proof", "Propose actions", "Prepare export", "Human review"];

export function renderAgent(state) {
  const run = state.agent.activeRun;
  const result = run?.result || demoAgent;
  const isEvaluation = state.session.mode === "demo" || state.assurance.demoMode === true;
  const proposed = run?.proposed_actions || result.recommended_actions || [];
  const findings = result.findings || [{ summary: result.summary, severity: "needs_review", confidence: result.confidence || 0.8 }];
  return `<section class="page-stack agent-page">
    <section class="enterprise-hero">
      <div>
        <p class="eyebrow">${isEvaluation ? "Evaluation workspace · deterministic agent · not live" : "Agent workflow"}</p>
        <h2>Agent Mission Control</h2>
        <p>Workflow: ${escapeHtml(run?.workflow_type || "assurance_audit")} · Passport/session: ${escapeHtml(run?.passport_id || state.assurance.activePassportId || "demo-passport-alpha-vineyard")} · Status: ${escapeHtml(run?.status || "needs_review")}</p>
      </div>
      <dl class="hero-status-grid">
        <div><dt>Groundedness</dt><dd>${escapeHtml(findings[0]?.evidence_reference ? "Grounded by evidence reference" : "Evidence reference needs review")}</dd></div>
        <div><dt>Confidence</dt><dd>${escapeHtml(String(findings[0]?.confidence ?? "needs review"))}</dd></div>
        <div><dt>Human gate</dt><dd>Approval required before external use</dd></div>
      </dl>
      <button class="button primary" data-action="run-assurance-agent" type="button">Run AGRO-AI Agent</button>
    </section>
    <section class="panel">
      <div class="panel-head"><p class="eyebrow">Agent Workflow Timeline</p><h3>Operating brain</h3></div>
      <div class="timeline-row">${timeline.map((step, index) => `<span class="timeline-step ${index < 6 ? "complete" : "pending"}">${escapeHtml(step)}</span>`).join("")}</div>
    </section>
    <section class="grid two-col">
      <article class="panel">
        <div class="panel-head"><p class="eyebrow">Findings</p><h3>Evidence-backed observations</h3></div>
        ${findings.map((finding) => `<div class="finding-card"><strong>${escapeHtml(finding.summary)}</strong><p>Severity: ${escapeHtml(finding.severity || "info")} · Confidence: ${escapeHtml(String(finding.confidence ?? "unavailable"))}</p><p>Evidence reference: ${escapeHtml((finding.evidence_reference || finding.grounded_by || []).join(", ") || "not available")}</p></div>`).join("")}
      </article>
      <article class="panel">
        <div class="panel-head"><p class="eyebrow">Proposed Actions</p><h3>Automation with review gates</h3></div>
        ${proposed.map((action) => `<div class="action-card"><strong>${escapeHtml(action.title || action.action_type)}</strong><p>${escapeHtml(action.rationale || "Evidence-backed workflow step.")}</p><p>${action.requires_human_approval ? "Approval required" : "Can automate with configured backend workflow"}</p>${action.requires_human_approval ? `<button class="button secondary compact" data-action="approve-agent-action" data-run-id="${escapeHtml(run?.id || "")}" data-action-id="${escapeHtml(action.id || "")}" type="button">Approve</button><button class="button ghost compact" data-action="reject-agent-action" data-run-id="${escapeHtml(run?.id || "")}" data-action-id="${escapeHtml(action.id || "")}" type="button">Reject</button>` : ""}</div>`).join("") || "<p>No proposed actions available.</p>"}
      </article>
    </section>
    <section class="panel">
      <div class="panel-head"><p class="eyebrow">Instruction Box</p><h3>Deterministic commands</h3></div>
      <div class="action-grid">
        <button class="button secondary" data-action="agent-question" data-question="What is missing?" type="button">What is missing?</button>
        <button class="button secondary" data-action="agent-question" data-question="Prepare buyer proof pack" type="button">Prepare buyer proof pack</button>
        <button class="button secondary" data-action="agent-question" data-question="Generate lender risk summary" type="button">Generate lender risk summary</button>
        <button class="button secondary" data-action="agent-question" data-question="What can be automated?" type="button">What can be automated?</button>
      </div>
      <p class="muted">Open-ended LLM chat is unavailable unless a backend LLM provider is configured. These controls use deterministic agent runs or local evaluation responses.</p>
    </section>
    <section class="panel">
      <div class="panel-head"><p class="eyebrow">Run Log</p><h3>Audit trail</h3></div>
      <div class="table-wrap"><table class="data-table compact"><thead><tr><th>Step</th><th>Status</th><th>Reference</th></tr></thead><tbody>
        ${timeline.map((step, index) => `<tr><td>${escapeHtml(step)}</td><td>${escapeHtml(index < 6 ? "ready" : "needs_review")}</td><td>${escapeHtml(run?.id || "evaluation-run")}</td></tr>`).join("")}
      </tbody></table></div>
    </section>
  </section>`;
}
