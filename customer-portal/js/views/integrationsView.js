import { demoProviders } from "../demoData.js";
import { integrationCard, onboardingProviderCard } from "../components/ui.js";

const SELF_SERVE_STEPS = [
  ["Choose source type", "Connected system, uploaded records, or API ingestion."],
  ["Connect provider, upload files, or use API", "Open Add or manage sources to connect a controller, upload records, or copy the API setup brief."],
  ["Map farm and block entities", "Map provider IDs to AGRO-AI farm, block, crop, soil, and irrigation entities."],
  ["Validate source coverage", "Confirm controller, weather, soil, flow, observation, and partner coverage."],
  ["Run first intelligence analysis", "Run the decision pipeline against the connected or uploaded source."],
  ["Review decision and evidence", "Review the verified water decision and the evidence chain."],
  ["Export executive report", "Preview, export CSV, or print the executive report."],
];

function stepper() {
  return `<section class="panel-card"><div class="section-heading"><p class="eyebrow">Self-serve setup</p><h2>From source to executive report</h2><p>A guided enterprise workflow. Production provisioning completes only when credentials are stored server-side through the credential vault.</p></div>
    <ol class="self-serve-stepper">${SELF_SERVE_STEPS.map(([title, detail], index) => `<li class="self-serve-step"><span class="step-index">${index + 1}</span><div><h3>${title}</h3><p>${detail}</p></div></li>`).join("")}</ol>
  </section>`;
}

export function renderIntegrations(state) {
  const isDemo = state.session.mode === "demo";
  const integrations = isDemo ? demoProviders : state.live.integrations;
  return `<div class="screen-stack">
    ${stepper()}
    <section class="panel-card"><div class="section-heading"><p class="eyebrow">Integrations</p><h2>Connected controller environments</h2><p>WiseConn and Talgil are shown with customer-safe runtime status, what AGRO-AI reads, what AGRO-AI generates, and current limitations. No live telemetry is claimed until production targets are connected.</p></div><div class="integration-grid">${integrations
      .map(integrationCard)
      .join("")}</div></section>
    <section class="panel-card"><div class="section-heading"><p class="eyebrow">Provider onboarding</p><h2>Connect provider environments</h2><p id="credential-note">Secure credential storage requires backend credential endpoints. This portal does not store real provider credentials in browser storage.</p></div><div class="provider-onboarding-grid">${[
      "WiseConn",
      "Talgil",
    ]
      .map(onboardingProviderCard)
      .join("")}</div><div class="secure-message">For any source requiring backend provisioning, request the integration setup brief — it documents the workspace, provider, credential vault requirement, tenant provisioning requirement, farm and block mapping requirement, security note, and operational next step.</div></section>
  </div>`;
}
