import { useRef, useState } from "react";
import { actions, useCommandStore } from "../state/commandStore";
import { ENDPOINTS } from "../api/client";
import { IntegrationSetupDrawer, buildSetupBrief } from "./IntegrationSetupDrawer";
import { StatusBadge } from "./StatusBadge";
import { ProviderStatusList } from "./ProviderStatusList";

type Tab = "connected" | "upload" | "api" | "partner";

const TABS: { id: Tab; label: string }[] = [
  { id: "connected", label: "Connected systems" },
  { id: "upload", label: "Upload records" },
  { id: "api", label: "API access" },
  { id: "partner", label: "Partner feeds" },
];

const PARTNER = [
  { name: "Weather provider", note: "Demand signals (ETo, rainfall) from a weather provider." },
  { name: "Earth observation layer", note: "Canopy stress and vegetation indices as a representative layer." },
  { name: "Agronomic feed", note: "Third-party agronomic context for reconciliation." },
  { name: "Custom partner feed", note: "Bring a custom partner signal into the decision pipeline." },
];

export function SourceDrawer() {
  const [tab, setTab] = useState<Tab>("connected");
  const [briefProvider, setBriefProvider] = useState<string | null>(null);
  const uploaded = useCommandStore((s) => s.uploaded);
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <>
      <div className="drawer-scrim" onClick={(e) => e.target === e.currentTarget && actions.closeDrawer()}>
        <aside className="drawer" role="dialog" aria-modal="true" aria-label="Connect irrigation data">
          <div className="drawer-head">
            <div>
              <p className="eyebrow">Source intelligence</p>
              <h2>Connect irrigation data</h2>
            </div>
            <button className="btn ghost compact" onClick={() => actions.closeDrawer()}>
              Close
            </button>
          </div>

          <div className="drawer-tabs" role="tablist">
            {TABS.map((t) => (
              <button key={t.id} role="tab" aria-selected={tab === t.id} className={`drawer-tab ${tab === t.id ? "active" : ""}`} onClick={() => setTab(t.id)}>
                {t.label}
              </button>
            ))}
          </div>

          <div className="drawer-body">
            {tab === "connected" && (
              <div className="drawer-list">
                <ProviderStatusList compact />
                <button className="btn compact" onClick={() => setBriefProvider("Provider runtime")}>
                  Request integration setup
                </button>
              </div>
            )}

            {tab === "upload" && (
              <div className="drawer-upload">
                <p className="muted">Accepted: CSV, XLSX, JSON, TXT.</p>
                <label
                  className="dropzone"
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    const f = e.dataTransfer.files?.[0];
                    if (f) actions.uploadRecords(f);
                  }}
                >
                  <input
                    ref={fileRef}
                    type="file"
                    className="visually-hidden"
                    accept=".csv,.json,.txt,.xlsx,text/csv,application/json,text/plain"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) actions.uploadRecords(f);
                    }}
                  />
                  <strong>Drop a file or browse</strong>
                  <span className="muted">Records are processed through the Workbench upload route.</span>
                </label>
                {uploaded && (
                  <dl className="brief-def">
                    <div>
                      <dt>Uploaded file</dt>
                      <dd className="identifier">{uploaded.name}</dd>
                    </div>
                    <div>
                      <dt>Detected source type</dt>
                      <dd>{uploaded.detectedType}</dd>
                    </div>
                    <div>
                      <dt>Parse status</dt>
                      <dd>{uploaded.parseStatus}</dd>
                    </div>
                    <div>
                      <dt>Rows detected</dt>
                      <dd>{uploaded.rows}</dd>
                    </div>
                    <div>
                      <dt>Fields mapped</dt>
                      <dd>{uploaded.fields}</dd>
                    </div>
                    <div>
                      <dt>Warnings</dt>
                      <dd>{uploaded.warnings}</dd>
                    </div>
                  </dl>
                )}
              </div>
            )}

            {tab === "api" && (
              <dl className="brief-def">
                <div>
                  <dt>Ingestion endpoint</dt>
                  <dd>
                    <code className="identifier">POST {ENDPOINTS.upload("{session_id}")}</code>
                  </dd>
                </div>
                <div>
                  <dt>Authentication</dt>
                  <dd>Server-side credential vault required. Keys are never stored in the browser.</dd>
                </div>
                <div>
                  <dt>Accepted payload categories</dt>
                  <dd>Controller events, weather, soil moisture, flow meter, field notes, crop profile, earth observation.</dd>
                </div>
                <div>
                  <dt>Schema</dt>
                  <dd>
                    <code className="identifier">GET {ENDPOINTS.schema}</code>
                  </dd>
                </div>
                <div className="drawer-actions">
                  <button className="btn compact" onClick={() => navigator.clipboard?.writeText(buildSetupBrief("API ingestion"))}>
                    Copy API setup brief
                  </button>
                </div>
              </dl>
            )}

            {tab === "partner" && (
              <div className="drawer-list">
                {PARTNER.map((p) => (
                  <article className="drawer-item" key={p.name}>
                    <div className="drawer-item-head">
                      <h4>{p.name}</h4>
                      <StatusBadge label="Authorization required" tone="warn" />
                    </div>
                    <p className="muted">{p.note}</p>
                  </article>
                ))}
                <p className="muted">Partner feed authorization required for production use.</p>
              </div>
            )}
          </div>
        </aside>
      </div>
      {briefProvider && <IntegrationSetupDrawer provider={briefProvider} onClose={() => setBriefProvider(null)} />}
    </>
  );
}
