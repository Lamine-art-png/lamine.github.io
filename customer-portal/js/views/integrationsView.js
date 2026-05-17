import { demoProviders } from "../demoData.js";
import { integrationCard, onboardingProviderCard } from "../components/ui.js";

export function renderIntegrations(state) {
  const isDemo = state.session.mode === "demo";
  const integrations = isDemo ? demoProviders : state.live.integrations;
  return `<div class="screen-stack">
    <section class="panel-card"><div class="section-heading"><p class="eyebrow">Integrations</p><h2>Connected controller environments</h2><p>WiseConn and Talgil are shown with customer-safe runtime status, what AGRO-AI reads, what AGRO-AI generates, and current limitations.</p></div><div class="integration-grid">${integrations
      .map(integrationCard)
      .join("")}</div></section>
    <section class="panel-card"><div class="section-heading"><p class="eyebrow">Provider Onboarding</p><h2>Connect provider environments</h2><p id="credential-note">Secure credential storage requires backend credential endpoints. This portal does not store real provider credentials in browser localStorage.</p></div><div class="provider-onboarding-grid">${[
      "WiseConn",
      "Talgil",
    ]
      .map(onboardingProviderCard)
      .join("")}</div></section>
    <section class="panel-card"><div class="section-heading"><p class="eyebrow">Activation Flow</p><h2>From provider access to intelligence</h2></div><div class="onboarding-steps">
      <article><span>1</span><h3>Select provider</h3><p>Choose WiseConn or Talgil for the customer environment.</p></article>
      <article><span>2</span><h3>Enter credentials or API key</h3><p>Secure backend credential storage is required before production credential submission.</p></article>
      <article><span>3</span><h3>Test connection</h3><p>Use runtime health/status endpoints to confirm provider reachability.</p></article>
      <article><span>4</span><h3>Sync farms/controllers</h3><p>Normalize farms, targets, zones, sensors, and irrigation events into AGRO-AI context.</p></article>
      <article><span>5</span><h3>Activate intelligence</h3><p>Enable recommendations, execution tracking, verification, and reports.</p></article>
    </div><div class="secure-message">Secure credential storage requires backend credential endpoints.</div></section>
  </div>`;
}
