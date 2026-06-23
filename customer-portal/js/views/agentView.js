import { escapeHtml } from "../components/dom.js";
import { demoAgent } from "./assuranceView.js";

const timeline = ["Ingest", "Normalize", "Classify", "Reconcile", "Detect missing proof", "Propose actions", "Prepare export", "Human review"];

export function renderAgent(state) {
  const run = state.agent.activeRun;
  const result = run?.result || demoAgent;
  const isEvaluation = state.session.mode === "demo";
  return `<section class="page-stack agent-page">
    <section class="hero-panel">
      <div>
        <p class="eyebrow">${isEvaluation ? "Evaluation workspace · deterministic agent" : "Agent workflow"}</p>
        <h2>AGRO-AI is reviewing the workspace.</h2>
        <p>Workflow: ${escapeHtml(run?.workflow_type || "assurance_audit")} · Passport/session: ${escapeHtml(run?.passport_id || state.assurance.activePassportId || "demo-passport-alpha-vineyard")} · Status: ${escapeHtml(run?.status || "needs_review")}</p>
      </div>
      <button class="button primary" data-action="run-assurance-agent" type="button">Run AGRO-AI Agent</button>
    </section>
    <section class="panel">
      <div class="panel-head"><p class="eyebrow">Agent Workflow Timeline</p><h3>Operating brain</h3></div>
      <div class="timeline-row">${timeline.map((step, index) => `<span class="status-chip ${index < 6 ? "" : "subtle"}">${escapeHtml(step)}</span>`).join("")}</div>
    </section>
    <section class="grid two-col">
      <article class="panel">
        <div class="panel-head"><p class="eyebrow">Findings</p><h3>Evidence-backed observations</h3></div>
        ${(result.findings || [{ summary: result.summary, severity: "needs_review", confidence: result.confidence || 0.8 }]).map((finding) => `<div class="finding-card"><strong>${escapeHtml(finding.summary)}</strong><p>Severity: ${escapeHtml(finding.severity || "info")} · Confidence: ${escapeHtml(String(finding.confidence ?? "unavailable"))}</p><p>Evidence reference: ${escapeHtml((finding.evidence_reference || finding.grounded_by || []).join(", ") || "not available")}</p></div>`).join("")}
      </article>
      <article class="panel">
        <div class="panel-head"><p class="eyebrow">Proposed Actions</p><h3>Automation with review gates</h3></div>
        ${(run?.proposed_actions || result.recommended_actions || []).map((action) => `<div class="action-card"><strong>${escapeHtml(action.title || action.action_type)}</strong><p>${escapeHtml(action.rationale || "Evidence-backed workflow step.")}</p><p>Can automate: ${action.requires_human_approval ? "No, approval required" : "Yes"}</p>${action.requires_human_approval ? `<button class="button secondary compact" data-action="approve-agent-action" data-run-id="${escapeHtml(run?.id || "")}" data-action-id="${escapeHtml(action.id || "")}" type="button">Approve</button><button class="button ghost compact" data-action="reject-agent-action" data-run-id="${escapeHtml(run?.id || "")}" data-action-id="${escapeHtml(action.id || "")}" type="button">Reject</button>` : ""}</div>`).join("") || "<p>No proposed actions available.</p>"}
      </article>
    </section>
    <section class="panel">
      <div class="panel-head"><p class="eyebrow">Agent Chat / Instruction Box</p><h3>Deterministic instructions</h3></div>
      <div class="action-grid">
        <button class="button secondary" data-action="agent-question" data-question="What is missing?" type="button">What is missing?</button>
        <button class="button secondary" data-action="agent-question" data-question="Prepare buyer proof pack" type="button">Prepare buyer proof pack</button>
        <button class="button secondary" data-action="agent-question" data-question="Generate lender risk summary" type="button">Generate lender risk summary</button>
        <button class="button secondary" data-action="agent-question" data-question="What can be automated?" type="button">What can be automated?</button>
      </div>
      <p class="muted">Open-ended LLM chat is unavailable unless a backend LLM provider is configured. These controls use deterministic agent runs or local evaluation responses.</p>
    </section>
  </section>`;
}

