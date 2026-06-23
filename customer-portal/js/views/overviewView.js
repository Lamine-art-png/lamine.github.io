import { escapeHtml, formatDate } from "../components/dom.js";
import { metricCard } from "../components/ui.js";
import { demoAgent, isAssuranceEvaluationMode, passportPackage } from "./assuranceView.js";

function activePackage(state) {
  return passportPackage(state);
}

function readinessModel(state) {
  const pkg = activePackage(state);
  return state.assurance.readiness || pkg.readiness || {};
}

function actionQueue(state) {
  const readiness = readinessModel(state);
  const run = state.agent.activeRun;
  const proposed = state.agent.proposedActions?.length ? state.agent.proposedActions : run?.proposed_actions || [];
  const missing = readiness.missing_evidence || [];
  const actions = [
    ...missing.slice(0, 3).map((item) => ({
      title: item.requirement_key || "Attach missing proof",
      type: "Missing proof",
      priority: item.severity || "required",
      detail: `${item.section_type || "proof"} needs ${(item.needed_evidence_types || []).join(", ") || "evidence"}`,
      action: "Attach records",
    })),
    ...proposed.slice(0, 2).map((item) => ({
      title: item.title || item.action_type || "Recommended action",
      type: item.requires_human_approval ? "Approval required" : "Recommended action",
      priority: item.requires_human_approval ? "review" : "ready",
      detail: item.rationale || "Evidence-backed workflow step.",
      action: item.requires_human_approval ? "Review action" : "Run workflow",
    })),
  ];
  if (actions.length) return actions;
  return [{ title: "Open Assurance Passport", type: "Next best action", priority: "needs_review", detail: "Create or select a passport before proof packages can be prepared.", action: "Open Assurance" }];
}

function evidenceRows(state) {
  const pkg = activePackage(state);
  if (!isAssuranceEvaluationMode(state) && !state.assurance.activePassportId && !state.assurance.activePassport?.passport) {
    return [];
  }
  const uploaded = state.demoRuntime.analysis?.artifacts || [];
  return [
    ...(pkg.evidence || []).map((item) => ({
      name: item.filename || item.file_ref || item.evidence_type,
      domain: item.proof_domain || "proof",
      status: item.review_status || "pending_review",
      source: item.source_system || "workspace",
      created: item.created_at || "",
    })),
    ...uploaded.map((item) => ({
      name: item.filename || "Uploaded record",
      domain: "workbench_upload",
      status: item.parse_status || item.status || "accepted",
      source: "Workbench upload",
      created: item.created_at || "",
    })),
  ].slice(0, 5);
}

export function renderOverview(state) {
  const isEvaluation = isAssuranceEvaluationMode(state);
  const pkg = activePackage(state);
  const passport = pkg.passport || {};
  const readiness = readinessModel(state);
  const agent = state.agent.activeRun?.result || (isEvaluation ? demoAgent : {});
  const runtime = state.demoRuntime;
  const liveNoPassport = !isEvaluation && !state.assurance.activePassportId && !state.assurance.activePassport?.passport;
  const actions = actionQueue(state);
  const evidence = evidenceRows(state);
  const openActions = actions.length;
  const missingProof = (readiness.missing_evidence || []).length;
  const agentRuns = state.agent.activeRun || state.agent.activeRunId ? 1 : 0;
  const recentExports = state.assurance.latestExport || runtime.reportSnapshots?.length ? 1 : 0;

  return `<section class="page-stack overview-page">
    <section class="enterprise-hero">
      <div>
        <p class="eyebrow">Enterprise OS Overview</p>
        <h2>${escapeHtml(passport.farm_name || runtime.activeFarm?.name || "Workspace")}</h2>
        <p>${escapeHtml(liveNoPassport ? "Backend auth required for live Assurance APIs. No demo passport was loaded." : "Intake, analysis, findings, action queue, approval, and export in one evidence-backed operating surface.")}</p>
      </div>
      <dl class="hero-status-grid">
        <div><dt>Environment</dt><dd>${escapeHtml(isEvaluation ? "Evaluation workspace · not live · not certified" : "Live mode · backend auth required")}</dd></div>
        <div><dt>API status</dt><dd>${escapeHtml(isEvaluation ? "Evaluation data loaded" : state.session.authNotice || "Backend auth required")}</dd></div>
        <div><dt>Operating mode</dt><dd>${escapeHtml(runtime.intakeMode || "source selection pending")}</dd></div>
      </dl>
    </section>

    ${liveNoPassport ? '<section class="premium-empty-state live-assurance-empty"><h3>Create or connect a live Assurance Passport</h3><p>Backend auth required for live Assurance APIs. No demo passport was loaded.</p><button class="button primary" data-view="assurance" type="button">Open Assurance</button></section>' : ""}

    <section class="enterprise-metric-row">
      ${metricCard("Assurance readiness", `${readiness.readiness_score ?? "—"}%`, readiness.status || "needs_review")}
      ${metricCard("Open actions", String(openActions), "Action queue")}
      ${metricCard("Missing proof", String(missingProof), "Reviewer evaluation blockers")}
      ${metricCard("Agent runs", String(agentRuns), state.agent.activeRun?.status || "needs_review")}
      ${metricCard("Recent exports", String(recentExports), state.assurance.latestExport?.status || "proof packs")}
    </section>

    <section class="grid two-col enterprise-split">
      <article class="panel">
        <div class="panel-head"><p class="eyebrow">Action Queue</p><h3>Highest-priority work</h3></div>
        <div class="enterprise-list">
          ${actions.map((item) => `<div class="enterprise-list-row">
            <span class="status-chip subtle">${escapeHtml(item.type)}</span>
            <div><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.detail)}</p></div>
            <em>${escapeHtml(item.action)}</em>
          </div>`).join("")}
        </div>
      </article>
      <article class="panel">
        <div class="panel-head"><p class="eyebrow">Agent Activity</p><h3>What AGRO-AI sees now</h3></div>
        <dl class="setup-brief">
          <div><dt>Latest run</dt><dd>${escapeHtml(state.agent.activeRun?.id || state.agent.activeRunId || "No live run yet")}</dd></div>
          <div><dt>Status</dt><dd>${escapeHtml(state.agent.activeRun?.status || "needs_review")}</dd></div>
          <div><dt>Latest finding</dt><dd>${escapeHtml(agent.risk_flags?.[0]?.summary || agent.summary || "No finding loaded")}</dd></div>
          <div><dt>Next best action</dt><dd>${escapeHtml(agent.next_best_action?.title || actions[0]?.title || "Refresh readiness")}</dd></div>
        </dl>
      </article>
    </section>

    <section class="grid two-col enterprise-split">
      <article class="panel">
        <div class="panel-head"><p class="eyebrow">Operational Health</p><h3>Water Command status</h3></div>
        <dl class="setup-brief">
          <div><dt>Recommendation</dt><dd>${escapeHtml(runtime.activeRecommendation?.action || runtime.analysis?.backendResult?.recommendation?.decision || "Run analysis to generate a decision")}</dd></div>
          <div><dt>Execution verification</dt><dd>${escapeHtml(runtime.operatingChain?.at?.(-1)?.status || "Verification pending")}</dd></div>
          <div><dt>Anomalies</dt><dd>${escapeHtml(runtime.analysis?.backendError || "No unresolved operational anomaly loaded")}</dd></div>
        </dl>
      </article>
      <article class="panel">
        <div class="panel-head"><p class="eyebrow">Recent Evidence / Reports</p><h3>Proof package inputs</h3></div>
        <div class="table-wrap"><table class="data-table compact"><thead><tr><th>Record</th><th>Domain</th><th>Status</th><th>Source</th><th>Created</th></tr></thead><tbody>
          ${evidence.length ? evidence.map((item) => `<tr><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.domain)}</td><td>${escapeHtml(item.status)}</td><td>${escapeHtml(item.source)}</td><td>${escapeHtml(item.created ? formatDate(item.created) : "unavailable")}</td></tr>`).join("") : '<tr><td colspan="5">No evidence loaded yet.</td></tr>'}
        </tbody></table></div>
      </article>
    </section>
  </section>`;
}
