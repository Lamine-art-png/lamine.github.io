import { demoProviders } from "../demoData.js";
import { integrationCard } from "../components/ui.js";

export function renderIntegrations(state) {
  const isDemo = state.session.mode === "demo";
  const integrations = isDemo ? demoProviders : state.live.integrations;
  return `<div class="screen-stack">
    <section class="panel-card"><div class="section-heading"><p class="eyebrow">Integrations</p><h2>Connect controller environments</h2><p>Provider credentials must be exchanged through secure backend endpoints. This static portal does not store real credentials in browser localStorage.</p></div><div class="integration-grid">${integrations
      .map(integrationCard)
      .join("")}</div></section>
    <section class="panel-card"><div class="section-heading"><p class="eyebrow">Onboarding Flow</p><h2>Activate a provider environment</h2></div><div class="onboarding-steps">
      <article><span>1</span><h3>Select provider</h3><p>Choose WiseConn or Talgil for the customer environment.</p></article>
      <article><span>2</span><h3>Enter credentials or API key</h3><p>Secure backend credential storage is required; secrets are never persisted by this browser UI.</p></article>
      <article><span>3</span><h3>Test connection</h3><p>Use runtime health/status endpoints to confirm provider reachability.</p></article>
      <article><span>4</span><h3>Sync farms/controllers</h3><p>Normalize farms, targets, zones, sensors, and irrigation events into AGRO-AI context.</p></article>
      <article><span>5</span><h3>Activate intelligence</h3><p>Enable recommendations, execution tracking, and verification workflows.</p></article>
    </div><div class="secure-message">Secure backend credential endpoint required before production credential submission.</div></section>
  </div>`;
}
