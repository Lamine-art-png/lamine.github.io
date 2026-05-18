import { escapeHtml } from "../components/dom.js";
import { badge } from "../components/ui.js";

export const navItems = [
  ["command-center", "Command Center"],
  ["farm-explorer", "Farm Explorer"],
  ["intelligence", "Intelligence"],
  ["verification", "Verification"],
  ["reports", "Reports"],
  ["integrations", "Integrations"],
  ["audit-log", "Audit Log"],
  ["settings", "Settings"],
];

export function renderShell(state, content) {
  const workspace = state.session.workspace;
  const isDemo = state.session.mode === "demo";
  return `<div class="portal-layout">
    <aside class="sidebar">
      <div class="brand-lockup">
        <img src="./assets/agro-ai-logo.png" alt="AGRO-AI" class="brand-logo" />
        <div><div class="brand">AGRO-AI</div><p>Enterprise Portal</p></div>
      </div>
      <nav class="nav-list" aria-label="Portal navigation">${navItems
        .map(([id, label]) => `<button class="nav-item ${state.activeView === id ? "active" : ""}" data-view="${id}" type="button">${label}</button>`)
        .join("")}</nav>
      <div class="sidebar-footer"><div class="sidebar-mode"><span>${escapeHtml(isDemo ? "Mode" : "Access")}</span>${badge(isDemo ? "Demo Environment" : "Live / Auth-ready", isDemo ? "warning" : "success")}</div><div class="sidebar-note">${escapeHtml(workspace?.label || state.session.authNotice)}</div></div>
    </aside>
    <main class="portal-main">
      <header class="portal-header">
        <div><p class="eyebrow">Workspace</p><h1>${escapeHtml(workspace?.name || "Customer Workspace")}</h1></div>
        <div class="header-actions">
          ${badge(isDemo ? "Demo Environment" : "Live / Auth-ready", isDemo ? "warning" : "success")}
          ${badge(workspace?.source || "Manual", "neutral")}
          <a class="help-link" href="mailto:support@agroai-pilot.com">Help</a>
          <div class="profile-menu">${escapeHtml(state.session.userEmail || "Profile")}</div>
          <button id="exit-session" class="button ghost" type="button">Exit</button>
        </div>
      </header>
      <section class="session-notice ${isDemo ? "demo" : "live"}">${escapeHtml(state.session.authNotice)}</section>
      ${!isDemo ? '<section class="org-selector-placeholder"><strong>Workspace access selector</strong><span>Backend authentication will populate authorized organizations here after real login.</span></section>' : ''}
      ${content}
    </main>
  </div>`;
}
