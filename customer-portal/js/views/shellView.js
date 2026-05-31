import { escapeHtml } from "../components/dom.js";
import { getWorkspaceScenarios, workspaceScenarios } from "../services/demoRuntime.js";

const complianceEnabled = () => Boolean(window.AGROAI_PORTAL_CONFIG?.CALIFORNIA_COMPLIANCE_PACK_ENABLED);

export const navItems = [
  ["command-center", "Command"],
  ["farm-explorer", "Sources"],
  ["reports", "Reports"],
  ["integrations", "Integrations"],
];

export const secondaryNavItems = [
  ["audit-log", "Audit"],
  ["settings", "Settings"],
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

export function renderShell(state, content) {
  const workspace = state.session.workspace;
  const isEvaluation = state.session.mode === "demo";
  const runtime = state.demoRuntime;
  const scenarioName = workspaceScenarios[runtime?.workspaceScenarioId]?.name || "Alpha Vineyard";
  const userName = state.session.userName || "Operations user";
  const freshness = runtime?.institutionalKpis?.freshness || "Updated 2 min ago";

  return `<div class="portal-layout">
    <aside class="sidebar">
      <div class="brand-lockup">
        <img src="./assets/agro-ai-logo.png" alt="AGRO-AI" class="brand-logo" />
        <div><div class="brand">AGRO-AI</div><p>Water Command Center</p></div>
      </div>
      <div class="nav-section-label">Primary</div><nav class="nav-list" aria-label="Portal navigation">${[...navItems, ...(complianceEnabled() ? [["compliance", "Compliance"]] : [])].map(([id, label]) => navButton(state, id, label)).join("")}</nav>
      <div class="nav-section-label secondary-label">Secondary</div><nav class="nav-list secondary-nav" aria-label="Secondary navigation">${secondaryNavItems.map(([id, label]) => navButton(state, id, label)).join("")}</nav>
      <div class="sidebar-footer"><div class="sidebar-mode"><span>${escapeHtml(isEvaluation ? "Evaluation workspace" : "Live / Auth-ready")}</span><strong>${escapeHtml(isEvaluation ? scenarioName : workspace?.name || "Customer Workspace")}</strong></div><div class="sidebar-note">${escapeHtml(isEvaluation ? "Representative records until production targets are connected." : workspace?.label || state.session.authNotice)}</div></div>
    </aside>
    <main class="portal-main">
      <header class="portal-header">
        <div class="header-titleblock">
          <div class="header-title-row">
            <h1>${escapeHtml(isEvaluation ? scenarioName : workspace?.name || "Customer Workspace")} · Water Command Center</h1>
            ${isEvaluation ? workspaceSwitcher(runtime) : ""}
            <span class="provenance-badge" title="Representative records are used until production targets are connected.">Representative data</span>
          </div>
          <p class="header-subtitle">Scattered irrigation data becomes a verified water decision.</p>
          <p class="header-status-row">Evaluation workspace<span>·</span>Mixed sources<span>·</span>Evidence chain active<span>·</span>Backend intelligence online</p>
        </div>
        <div class="header-toolbar">
          <div class="toolbar-status" aria-label="Workspace status">
            <span class="status-chip">Evaluation workspace</span>
            <span class="status-chip">Mixed sources</span>
            <span class="status-chip subtle">${escapeHtml(freshness)}</span>
          </div>
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
      ${content}
    </main>
  </div>`;
}
