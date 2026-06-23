import { escapeHtml } from "../components/dom.js";
import { getWorkspaceScenarios, workspaceScenarios } from "../services/demoRuntime.js";

const complianceEnabled = () => Boolean(window.AGROAI_PORTAL_CONFIG?.CALIFORNIA_COMPLIANCE_PACK_ENABLED);

export const navItems = [
  ["overview", "Overview"],
  ["command-center", "Operations"],
  ["assurance", "Assurance"],
  ["evidence", "Evidence"],
  ["reports", "Reports"],
  ["agent", "Agents"],
];

export const secondaryNavItems = [
  ["integrations", "Integrations"],
  ["farm-explorer", "Sources"],
  ["audit-log", "Audit"],
  ["settings", "Admin"],
];

function navButton(state, id, label) {
  return `<button class="nav-item ${state.activeView === id ? "active" : ""}" data-view="${id}" type="button">${label}</button>`;
}

function initials(name = "Operations user") {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("");
}

function workspaceSwitcher(runtime) {
  const current = runtime?.workspaceScenarioId || "alpha-vineyard";
  const options = getWorkspaceScenarios()
    .map((scenario) => `<option value="${escapeHtml(scenario.id)}" ${scenario.id === current ? "selected" : ""}>${escapeHtml(scenario.name)}</option>`)
    .join("");
  return `<label class="workspace-switcher" title="Switch evaluation workspace"><span class="visually-hidden">Evaluation workspace</span><select id="workspace-scenario-select">${options}</select></label>`;
}

const viewTitles = {
  overview: ["Overview", "Executive command center for operations, proof coverage, agent work, and exports."],
  "command-center": ["Operations", "Water Command, source reconciliation, execution verification, and operating anomalies."],
  assurance: ["Assurance", "Passport-centered proof workflow for reviewer evaluation."],
  evidence: ["Evidence", "Evidence vault, uploaded records, extracted facts, and proof linkage."],
  reports: ["Reports", "Audit-ready evidence packages, executive exports, and proof packs."],
  agent: ["Agents", "Agentic workflow automation with human approval gates."],
  integrations: ["Admin", "Integration setup, source health, and environment readiness."],
  "farm-explorer": ["Sources", "Farm, block, controller, and source context."],
  "audit-log": ["Audit Trail", "Workspace events, decisions, approvals, and review status."],
  settings: ["Admin", "Workspace settings and operating controls."],
  compliance: ["Compliance", "Legacy compliance pack area, gated by feature flag."],
};

function environmentLabel(state) {
  if (state.session.mode === "demo" || state.assurance.demoMode === true) return "Evaluation · not live · not certified";
  return "Live / backend auth required";
}

function apiStatus(state) {
  if (state.session.mode === "demo") return "Evaluation data";
  return state.session.authNotice || "Backend auth required";
}

function agentRail(state, scenarioName) {
  const run = state.agent.activeRun;
  const finding = state.agent.findings?.[0] || run?.result?.risk_flags?.[0] || run?.result?.findings?.[0];
  const proposed = state.agent.proposedActions || run?.proposed_actions || [];
  const approvals = proposed.filter((action) => action.requires_human_approval).length;
  const nextAction = run?.result?.next_best_action?.title || proposed[0]?.title || (state.assurance.activePassportId ? "Refresh readiness" : "Open Assurance Passport");
  const context = state.assurance.activePassportId || state.demoRuntime?.activeFarm?.name || scenarioName;

  return `<aside class="agent-rail" aria-label="AGRO-AI operational rail">
    <div class="agent-rail-head">
      <div><p class="eyebrow">AGRO-AI Rail</p><h2>Operational control layer</h2></div>
      <span class="status-chip subtle">${escapeHtml(environmentLabel(state))}</span>
    </div>
    <dl class="agent-rail-list">
      <div><dt>Current context</dt><dd>${escapeHtml(context || "Workspace context pending")}</dd></div>
      <div><dt>Latest finding</dt><dd>${escapeHtml(finding?.summary || "No live finding loaded. Evaluation data is labeled when used.")}</dd></div>
      <div><dt>Next best action</dt><dd>${escapeHtml(nextAction)}</dd></div>
      <div><dt>Pending approvals</dt><dd>${escapeHtml(String(approvals))}</dd></div>
      <div><dt>Automation status</dt><dd>${escapeHtml(run?.status || "needs_review")}</dd></div>
      <div><dt>Recent agent run</dt><dd>${escapeHtml(run?.id || state.agent.activeRunId || "No run yet")}</dd></div>
    </dl>
    <button class="button primary wide" data-action="run-assurance-agent" type="button">Run Agent</button>
  </aside>`;
}

export function renderShell(state, content) {
  const workspace = state.session.workspace;
  const isEvaluation = state.session.mode === "demo" || state.assurance.demoMode === true;
  const runtime = state.demoRuntime;
  const scenarioName = workspaceScenarios[runtime?.workspaceScenarioId]?.name || "Alpha Vineyard";
  const userName = state.session.userName || "Operations user";
  const freshness = runtime?.institutionalKpis?.freshness || "Updated 2 min ago";
  const [title, subtitle] = viewTitles[state.activeView] || viewTitles.overview;
  const envLabel = environmentLabel(state);

  return `<div class="portal-layout">
    <aside class="sidebar">
      <div class="brand-lockup">
        <img src="./assets/agro-ai-logo.png" alt="AGRO-AI" class="brand-logo" />
        <div><div class="brand">AGRO-AI</div><p>Enterprise Operating System</p></div>
      </div>
      <div class="nav-section-label">Operating system</div><nav class="nav-list" aria-label="Portal navigation">${[...navItems, ...(complianceEnabled() ? [["compliance", "Compliance"]] : [])].map(([id, label]) => navButton(state, id, label)).join("")}</nav>
      <div class="nav-section-label secondary-label">Admin</div><nav class="nav-list secondary-nav" aria-label="Secondary navigation">${secondaryNavItems.map(([id, label]) => navButton(state, id, label)).join("")}</nav>
      <div class="sidebar-footer"><div class="sidebar-mode"><span>${escapeHtml(envLabel)}</span><strong>${escapeHtml(isEvaluation ? scenarioName : workspace?.name || "Customer Workspace")}</strong></div><div class="sidebar-note">${escapeHtml(isEvaluation ? "Representative records only. Reviewer evaluation required before external use." : workspace?.label || state.session.authNotice)}</div></div>
    </aside>
    <main class="portal-main">
      <header class="portal-header">
        <div class="header-titleblock">
          <div class="header-title-row">
            <h1>${escapeHtml(title)}</h1>
            ${isEvaluation ? workspaceSwitcher(runtime) : ""}
            <span class="provenance-badge" title="Evaluation records are not live and are not certification.">${escapeHtml(envLabel)}</span>
          </div>
          <p class="header-subtitle">${escapeHtml(subtitle)}</p>
          <p class="header-status-row">${escapeHtml(isEvaluation ? scenarioName : workspace?.name || "Customer Workspace")}<span>·</span>${escapeHtml(apiStatus(state))}<span>·</span>Evidence-backed workflow<span>·</span>${escapeHtml(freshness)}</p>
        </div>
        <div class="header-toolbar">
          <div class="toolbar-status" aria-label="Workspace status">
            <span class="status-chip">${escapeHtml(isEvaluation ? "Evaluation workspace" : "Live mode")}</span>
            <span class="status-chip">${escapeHtml(isEvaluation ? "Not live" : "Auth required")}</span>
            <span class="status-chip subtle">${escapeHtml(freshness)}</span>
          </div>
          <button class="button primary compact" data-action="run-assurance-agent" type="button">Run Agent</button>
          <details class="overflow-menu">
            <summary aria-label="More options" title="More options">⋯</summary>
            <div class="menu-panel">
              <button class="menu-item" data-action="workspace-details" type="button">Workspace details</button>
              <a class="menu-item" href="mailto:support@agroai-pilot.com?subject=AGRO-AI%20Water%20Command%20Center">Help</a>
            </div>
          </details>
          <details class="user-menu">
            <summary aria-label="Account menu"><span class="avatar">${escapeHtml(initials(userName))}</span></summary>
            <div class="menu-panel">
              <div class="menu-identity"><strong>${escapeHtml(userName)}</strong><span>Evaluation workspace</span></div>
              <button class="menu-item" data-action="workspace-details" type="button">Workspace details</button>
              <a class="menu-item" href="mailto:support@agroai-pilot.com?subject=AGRO-AI%20Water%20Command%20Center">Help</a>
              <button id="exit-session" class="menu-item danger" type="button">Exit workspace</button>
            </div>
          </details>
        </div>
      </header>
      <div class="workspace-canvas">
        <div class="workspace-content">${content}</div>
        ${agentRail(state, scenarioName)}
      </div>
    </main>
  </div>`;
}
