import { useState } from "react";
import { IntegrationSetupDrawer } from "../components/IntegrationSetupDrawer";
import { ProviderStatusList } from "../components/ProviderStatusList";

const STEPS = [
  ["Choose source type", "Connected system, uploaded records, or API ingestion."],
  ["Connect provider or upload records", "Connect a controller, upload records, or copy the API setup brief."],
  ["Map farm and block entities", "Map provider IDs to AGRO-AI farm, block, crop, soil, and irrigation entities."],
  ["Validate coverage", "Confirm controller, weather, soil, flow, observation, and partner coverage."],
  ["Run first analysis", "Run the decision pipeline against the connected or uploaded source."],
  ["Review decision", "Review the verified water decision and the evidence chain."],
  ["Export report", "Preview, export CSV, or print the executive report."],
];

export function IntegrationsPage() {
  const [provider, setProvider] = useState<string | null>(null);
  return (
    <div className="stack">
      <section className="card panel">
        <p className="eyebrow">Self-serve setup</p>
        <h2>From source to executive report</h2>
        <p className="muted">
          A guided enterprise workflow. Production provisioning completes only when credentials are stored server-side through
          the credential vault.
        </p>
        <ol className="stepper">
          {STEPS.map(([title, detail], i) => (
            <li className="step" key={title}>
              <span className="step-index">{i + 1}</span>
              <div>
                <h3>{title}</h3>
                <p className="muted">{detail}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="card panel">
        <p className="eyebrow">Provider onboarding</p>
        <h2>Connect provider environments</h2>
        <ProviderStatusList />
        <button className="btn compact" onClick={() => setProvider("Provider runtime")}>
          Request integration setup
        </button>
        <p className="muted secure-note">
          Secure credential storage requires backend credential endpoints. This portal never stores provider credentials in
          browser storage.
        </p>
      </section>

      {provider && <IntegrationSetupDrawer provider={provider} onClose={() => setProvider(null)} />}
    </div>
  );
}
