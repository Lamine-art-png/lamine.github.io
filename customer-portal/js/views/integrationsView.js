import { demoProviders } from "../demoData.js";
import { integrationCard } from "../components/ui.js";

export function renderIntegrations(state) {
  const integrations = state.session.mode === "demo" ? demoProviders : state.live.integrations;
  const brief = `Integration setup brief\nWorkspace: Alpha Vineyard\nProvider: WiseConn or Talgil\nRequired backend services: Connector runtime, ingestion orchestration, verification event pipeline\nCredential vault requirement: Backend-managed vault and key rotation\nTenant provisioning requirement: Workspace, role, and policy provisioning\nFarm and block mapping requirement: Canonical farm/block/source mapping\nSecurity note: Browser does not store provider credentials\nOperational next step: Run backend onboarding with integration owner`; 
  return `<div class="screen-stack">
    <section class="panel-card"><h2>Integrations</h2><div class="integration-grid">${integrations.map(integrationCard).join("")}</div></section>
    <section class="panel-card"><h2>Provider onboarding</h2><button class="button primary" data-action="open-setup-brief" data-brief="${brief.replace(/"/g, '&quot;')}">Request backend setup</button></section>
    <aside id="setup-brief-drawer" class="setup-drawer hidden"><div class="setup-drawer-inner"><h3>Integration setup brief</h3><pre id="setup-brief-text">${brief}</pre><div class="runtime-actions"><button class="button secondary" data-action="copy-setup-brief">Copy brief</button><button class="button secondary" data-action="download-setup-brief">Download brief</button><button class="button ghost" data-action="close-setup-brief">Close</button></div></div></aside>
  </div>`;
}
