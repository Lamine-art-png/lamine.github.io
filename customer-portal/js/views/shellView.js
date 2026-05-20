import { escapeHtml } from "../components/dom.js";
import { badge } from "../components/ui.js";

export const navItems = [
  ["command-center", "Water Command Center"],
  ["farm-explorer", "Farms"],
  ["reports", "Reports"],
  ["integrations", "Integrations"],
];

export const secondaryNavItems = [
  ["audit-log", "Audit Log"],
  ["settings", "Settings"],
];

function navButton(state, id, label) {
  return `<button class="nav-item ${state.activeView === id ? "active" : ""}" data-view="${id}" type="button">${label}</button>`;
}

export function renderShell(state, content) {
  const workspace = state.session.workspace;
  const isEvaluation = state.session.mode === "demo";
  return `<div class="portal-layout">
    <aside class="sidebar">
      <div class="brand-lockup">
        <img src="./assets/agro-ai-logo.png" alt="AGRO-AI" class="brand-logo" />
        <div><div class="brand">AGRO-AI</div><p>Enterprise Portal</p></div>
      </div>
      <div class="nav-section-label">Main</div><nav class="nav-list" aria-label="Portal navigation">${navItems.map(([id, label]) => navButton(state, id, label)).join("")}</nav>
      <div class="nav-section-label secondary-label">Secondary</div><nav class="nav-list secondary-nav" aria-label="Secondary navigation">${secondaryNavItems.map(([id, label]) => navButton(state, id, label)).join("")}</nav>
      <div class="sidebar-footer"><div class="sidebar-mode"><span>Mode: ${escapeHtml(isEvaluation ? "Evaluation mode" : "Live / Auth-ready")}</span><strong>${escapeHtml(isEvaluation ? "Alpha Vineyard workspace" : workspace?.name || "Customer Workspace")}</strong></div><div class="sidebar-note">${escapeHtml(workspace?.label || state.session.authNotice)}</div></div>
    </aside>
    <main class="portal-main">
      <header class="portal-header">
        <div><p class="eyebrow">Workspace</p><h1>${escapeHtml(workspace?.name || "Customer Workspace")}</h1></div>
        <div class="header-actions">
          ${badge(isEvaluation ? "Evaluation mode" : "Live / Auth-ready", isEvaluation ? "warning" : "success")}
          ${badge(workspace?.source || "Manual", "neutral")}
          <a class="help-link" href="mailto:support@agroai-pilot.com">Help</a>
          <div class="profile-menu">${escapeHtml(state.session.userEmail || "Profile")}</div>
          <button id="exit-session" class="button ghost" type="button">Exit</button>
        </div>
      </header>
      <section class="session-notice ${isEvaluation ? "evaluation" : "live"}">${escapeHtml(state.session.authNotice)}</section>
      ${!isEvaluation ? '<section class="org-selector-placeholder"><strong>Workspace access selector</strong><span>Backend authentication will populate authorized organizations here after real login.</span></section>' : ""}
      ${content}
    </main>
  </div>`;
}
