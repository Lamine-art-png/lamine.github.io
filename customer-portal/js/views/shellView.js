import { escapeHtml } from "../components/dom.js";
import { badge } from "../components/ui.js";

export const navItems = [["command-center", "Command"],["farm-explorer", "Sources"],["reports", "Reports"],["integrations", "Integrations"],["audit-log", "Audit"],["settings", "Settings"]];

export function renderShell(state, content) {
  const workspace = state.session.workspace;
  const provenance = "This workspace uses representative records and live-ready API paths for evaluation.";
  return `<div class="portal-layout enterprise-shell">
    <aside class="sidebar">
      <div class="brand-lockup"><img src="./assets/agro-ai-logo.png" alt="AGRO-AI" class="brand-logo" /><div><div class="brand">AGRO-AI</div><p>Water Command Center</p></div></div>
      <nav class="nav-list" aria-label="Portal navigation">${navItems.map(([id,label]) => `<button class="nav-item ${state.activeView===id?"active":""}" data-view="${id}" type="button">${label}</button>`).join("")}</nav>
      <div class="sidebar-note">Operations user</div>
    </aside>
    <main class="portal-main">
      <header class="portal-header command-header">
        <div><h1>Alpha Vineyard · Water Command Center</h1><p class="status-line">Pilot workspace · Mixed sources · Evidence chain active · Backend intelligence online</p></div>
        <div class="header-actions">${badge("Pilot data","warning")}<span class="provenance-pill" title="${escapeHtml(provenance)}">i</span><button id="exit-session" class="button ghost" type="button">Exit</button></div>
      </header>
      ${content}
    </main>
  </div>`;
}
