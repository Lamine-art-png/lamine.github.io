import { useState } from "react";
import { IntegrationSetupDrawer } from "../components/IntegrationSetupDrawer";
import { StatusBadge } from "../components/StatusBadge";

interface SystemRow {
  name: string;
  type: "controller" | "partner";
  state: "Live" | "Configured" | "Limited" | "Unavailable" | "Setup required" | "Target selection required";
  lastChecked: string;
  records: string;
  targets: string;
  limitations: string[];
  nextAction: string;
}

const CONNECTED_SYSTEMS: SystemRow[] = [
  {
    name: "WiseConn",
    type: "controller",
    state: "Limited",
    lastChecked: "Checked on workspace open",
    records: "Evaluation connector available",
    targets: "Target selection required",
    limitations: [
      "Provider credentials must be provisioned server-side for production access",
      "Live telemetry requires authorized farm and block mapping",
    ],
    nextAction: "Provision WiseConn credentials via enterprise onboarding",
  },
  {
    name: "Talgil",
    type: "controller",
    state: "Limited",
    lastChecked: "Checked on workspace open",
    records: "Runtime reachable",
    targets: "Target selection required",
    limitations: [
      "Production target selection requires authorized farm mapping",
      "API credentials must be stored server-side before live irrigation commands",
    ],
    nextAction: "Complete Talgil farm mapping via enterprise onboarding",
  },
];

const PARTNER_FEEDS: SystemRow[] = [
  {
    name: "Weather",
    type: "partner",
    state: "Configured",
    lastChecked: "Checked on workspace open",
    records: "ETo and precipitation forecast available",
    targets: "Regional — block-level requires farm mapping",
    limitations: [
      "Block-level weather requires geo-referenced farm coordinates",
    ],
    nextAction: "Add farm coordinates to improve weather resolution",
  },
  {
    name: "Earth observation",
    type: "partner",
    state: "Limited",
    lastChecked: "Checked on workspace open",
    records: "Sample layer available for evaluation",
    targets: "Block boundary mapping required for production",
    limitations: [
      "Earth observation requires block boundary polygons for production use",
      "Sample layer is representative — not field-specific",
    ],
    nextAction: "Provide block boundary polygons to enable production earth observation",
  },
  {
    name: "Agronomic context",
    type: "partner",
    state: "Configured",
    lastChecked: "Checked on workspace open",
    records: "Calibrated v0.2 defaults available",
    targets: "Farm-specific calibration pending",
    limitations: [
      "Current calibration uses transparent v0.2 defaults",
      "Farm-specific calibration replaces defaults during production onboarding",
    ],
    nextAction: "Complete farm-specific calibration during production onboarding",
  },
];

function stateTone(state: SystemRow["state"]): "ok" | "warn" | "danger" | "neutral" {
  if (state === "Live" || state === "Configured") return "ok";
  if (state === "Limited" || state === "Target selection required") return "warn";
  if (state === "Unavailable") return "danger";
  return "neutral";
}

function SystemCard({ row, onSetup }: { row: SystemRow; onSetup: (name: string) => void }) {
  return (
    <div className="integration-row">
      <div className="integration-row-head">
        <div className="integration-name-block">
          <strong className="integration-name">{row.name}</strong>
          <StatusBadge label={row.state} tone={stateTone(row.state)} />
        </div>
        <button className="btn ghost compact" onClick={() => onSetup(row.name)}>
          Setup brief
        </button>
      </div>
      <div className="integration-meta">
        <div>
          <p className="integration-meta-label">Last checked</p>
          <p className="integration-meta-value muted">{row.lastChecked}</p>
        </div>
        <div>
          <p className="integration-meta-label">Records available</p>
          <p className="integration-meta-value muted">{row.records}</p>
        </div>
        <div>
          <p className="integration-meta-label">Targets</p>
          <p className="integration-meta-value muted">{row.targets}</p>
        </div>
      </div>
      {row.limitations.length > 0 && (
        <ul className="integration-limitations">
          {row.limitations.map((l) => (
            <li key={l} className="muted">{l}</li>
          ))}
        </ul>
      )}
      <p className="integration-next-action">
        <strong>Next action:</strong> {row.nextAction}
      </p>
    </div>
  );
}

const SETUP_STEPS = [
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
      {/* Connected systems */}
      <section className="card panel">
        <p className="eyebrow">Connected systems</p>
        <h2>Controller integrations</h2>
        <p className="muted" style={{ marginBottom: "var(--s-4)" }}>
          Irrigation controllers connected through the evaluation workspace. Production provisioning
          completes only when credentials are stored server-side through the credential vault.
        </p>
        <div className="integration-list">
          {CONNECTED_SYSTEMS.map((row) => (
            <SystemCard key={row.name} row={row} onSetup={setProvider} />
          ))}
        </div>
      </section>

      {/* Partner feeds */}
      <section className="card panel">
        <p className="eyebrow">Partner feeds</p>
        <h2>Weather, earth observation, and agronomic context</h2>
        <p className="muted" style={{ marginBottom: "var(--s-4)" }}>
          External data feeds that enrich source intelligence. Each feed has explicit state and limitations.
        </p>
        <div className="integration-list">
          {PARTNER_FEEDS.map((row) => (
            <SystemCard key={row.name} row={row} onSetup={setProvider} />
          ))}
        </div>
      </section>

      {/* Setup workflow */}
      <section className="card panel">
        <p className="eyebrow">Integration workflow</p>
        <h2>From source to executive report</h2>
        <ol className="stepper">
          {SETUP_STEPS.map(([title, detail], i) => (
            <li className="step" key={title}>
              <span className="step-index">{i + 1}</span>
              <div>
                <h3>{title}</h3>
                <p className="muted">{detail}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="muted secure-note" style={{ marginTop: "var(--s-4)" }}>
          Secure credential storage requires backend credential endpoints. This portal never stores
          provider credentials in browser storage.
        </p>
      </section>

      {provider && <IntegrationSetupDrawer provider={provider} onClose={() => setProvider(null)} />}
    </div>
  );
}
