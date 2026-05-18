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

function workspaceTitle(state) {
  if (state.session.mode === "demo" && state.activeView === "command-center") return "Alpha Vineyard · Command Center";
  return state.session.workspace?.name || "Customer Workspace";
}

function sessionBanner(isDemo, authNotice) {
  if (isDemo) {
    const dismissed = typeof sessionStorage !== "undefined" && sessionStorage.getItem("agroai-demo-telemetry-banner-dismissed") === "true";
    if (dismissed) return "";
    return `<section class="session-notice demo" role="status"><span>Demo mode · simulated telemetry</span><button class="notice-dismiss" onclick="sessionStorage.setItem('agroai-demo-telemetry-banner-dismissed','true'); this.closest('.session-notice')?.remove();" type="button" aria-label="Dismiss simulated telemetry notice">Dismiss</button></section>`;
  }

  return `<section class="session-notice live">${escapeHtml(authNotice)}</section>`;
}

export function renderShell(state, content) {
  const workspace = state.session.workspace;
  const isDemo = state.session.mode === "demo";
  const userLabel = isDemo ? "Signed-in workspace user" : state.session.userEmail || "Profile";
  return `<div class="portal-layout">
    <aside class="sidebar">
      <div class="brand-lockup">
        <img src="./assets/agro-ai-logo.png" alt="AGRO-AI" class="brand-logo" />
        <div><div class="brand">AGRO-AI</div><p>Enterprise Portal</p></div>
      </div>
      <nav class="nav-list" aria-label="Portal navigation">${navItems
        .map(([id, label]) => `<button class="nav-item ${state.activeView === id ? "active" : ""}" data-view="${id}" type="button">${label}</button>`)
        .join("")}</nav>
      <div class="sidebar-footer"><div class="sidebar-mode"><span>Workspace</span>${badge(isDemo ? "Pilot tenant" : "Live / Auth-ready", isDemo ? "neutral" : "success")}</div><div class="sidebar-note">${escapeHtml(isDemo ? "Institutional operating workspace with isolated simulated telemetry." : workspace?.label || state.session.authNotice)}</div></div>
    </aside>
    <main class="portal-main">
      <header class="portal-header">
        <div><p class="eyebrow">Workspace</p><h1>${escapeHtml(workspaceTitle(state))}</h1></div>
        <div class="header-actions">
          ${isDemo ? badge("Mode: Demo", "warning") : badge("Live / Auth-ready", "success")}
          ${badge(workspace?.source || "Manual", "neutral")}
          <a class="help-link" href="mailto:support@agroai-pilot.com">Help</a>
          <div class="profile-menu">${escapeHtml(userLabel)}</div>
          <button id="exit-session" class="button ghost" type="button">Exit</button>
        </div>
      </header>
      ${sessionBanner(isDemo, state.session.authNotice)}
      ${!isDemo ? '<section class="org-selector-placeholder"><strong>Workspace access selector</strong><span>Backend authentication will populate authorized organizations here after real login.</span></section>' : ''}
      ${content}
    </main>
  </div>`;
}
