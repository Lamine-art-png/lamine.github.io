import { useCallback, useMemo, useState, type ReactNode } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;

type Connector = {
  id: string;
  name: string;
  category: string;
  status: string;
  required_plan: string;
  connection_methods: string[];
  imports: string[];
  used_by: string[];
  promise: string;
  upload_supported?: boolean;
  connection?: AnyRecord | null;
};

type ConnectorProfile = {
  label: string;
  short: string;
  logoText: string;
  logoStyle: {
    background: string;
    color: string;
    border?: string;
  };
  setupKind: "controller" | "upload" | "oauth" | "api_upload" | "custom_api";
  primaryMethod: string;
  headline: string;
  description: string;
  primaryButton: string;
  secondaryNote: string;
  configFields: { key: string; label: string; placeholder: string; secret?: boolean }[];
  sampleFile?: {
    filename: string;
    body: string;
  };
};

const PROFILES: Record<string, ConnectorProfile> = {
  wiseconn: {
    label: "WiseConn",
    short: "Controller exports first. Live API later.",
    logoText: "W",
    logoStyle: { background: "#ECFDF5", color: "#047857", border: "1px solid #A7F3D0" },
    setupKind: "controller",
    primaryMethod: "export_upload",
    headline: "Connect WiseConn",
    description:
      "Start with a WiseConn CSV/export upload. This makes the connector useful immediately without waiting for live API credentials.",
    primaryButton: "Upload WiseConn export",
    secondaryNote:
      "Live API sync will require WiseConn account credentials/API access. Export upload is the fastest working path for customers.",
    configFields: [
      { key: "account_label", label: "Account / customer name", placeholder: "North Ranch WiseConn" },
      { key: "controller_id", label: "Controller or site ID", placeholder: "Optional controller/site ID" },
      { key: "api_key_ref", label: "API key reference", placeholder: "Optional vault/reference only", secret: true },
    ],
    sampleFile: {
      filename: "wiseconn-sample-export.csv",
      body:
        "timestamp,field,block,crop,flow_gpm,duration_minutes,water_gallons,valve_state,note\n" +
        "2026-06-26 06:00:00,North Ranch,Block A,Almonds,420,45,18900,on,Morning irrigation completed\n" +
        "2026-06-26 08:30:00,North Ranch,Block B,Almonds,390,35,13650,off,Shorter irrigation due to wet soil\n",
    },
  },
  talgil: {
    label: "Talgil",
    short: "Program logs and controller exports.",
    logoText: "T",
    logoStyle: { background: "#EFF6FF", color: "#1D4ED8", border: "1px solid #BFDBFE" },
    setupKind: "controller",
    primaryMethod: "export_upload",
    headline: "Connect Talgil",
    description:
      "Upload Talgil controller/program exports first. AGRO-AI will normalize irrigation events, zones, runtime, and flow readings.",
    primaryButton: "Upload Talgil export",
    secondaryNote:
      "Live Talgil sync needs provider credentials/API access. The export path should work immediately for implementation calls.",
    configFields: [
      { key: "account_label", label: "Account / customer name", placeholder: "Talgil customer account" },
      { key: "controller_id", label: "Controller or program ID", placeholder: "Optional controller/program ID" },
      { key: "api_key_ref", label: "API key reference", placeholder: "Optional vault/reference only", secret: true },
    ],
    sampleFile: {
      filename: "talgil-sample-export.csv",
      body:
        "timestamp,field,block,crop,flow_gpm,duration_minutes,water_gallons,valve_state,note\n" +
        "2026-06-26 05:45:00,South Ranch,Zone 12,Pistachios,510,50,25500,on,Talgil program A completed\n" +
        "2026-06-26 07:20:00,South Ranch,Zone 14,Pistachios,475,30,14250,off,Program stopped after pressure alert\n",
    },
  },
  manual_csv: {
    label: "CSV / PDF / Spreadsheet",
    short: "Manual evidence upload.",
    logoText: "CSV",
    logoStyle: { background: "#F8FAFC", color: "#334155", border: "1px solid #CBD5E1" },
    setupKind: "upload",
    primaryMethod: "manual_upload",
    headline: "Upload evidence",
    description:
      "Upload CSV, JSON, TXT, or PDF text exports. Every row becomes evidence AGRO-AI can cite in answers and reports.",
    primaryButton: "Upload file",
    secondaryNote: "Best for field logs, water budgets, ET exports, compliance notes, and messy customer records.",
    configFields: [
      { key: "source_label", label: "Source label", placeholder: "June irrigation logs" },
    ],
    sampleFile: {
      filename: "agro-ai-manual-sample.csv",
      body:
        "timestamp,field,block,crop,flow_gpm,duration_minutes,water_gallons,note\n" +
        "2026-06-26 06:00:00,North Ranch,Block A,Almonds,420,45,18900,Morning irrigation completed\n" +
        "2026-06-26 08:30:00,North Ranch,Block B,Almonds,390,35,13650,Shorter irrigation due to wet soil\n",
    },
  },
  weather: {
    label: "Weather / Forecast",
    short: "Weather API or weather CSV.",
    logoText: "☀",
    logoStyle: { background: "#FFFBEB", color: "#B45309", border: "1px solid #FDE68A" },
    setupKind: "api_upload",
    primaryMethod: "manual_upload",
    headline: "Connect weather data",
    description:
      "Use an API key when available, or upload weather/forecast exports. AGRO-AI uses this for irrigation risk and timing.",
    primaryButton: "Upload weather file",
    secondaryNote: "For live weather, save an API key reference. For internal testing, upload a weather CSV.",
    configFields: [
      { key: "provider", label: "Weather provider", placeholder: "OpenWeather, Tomorrow.io, NOAA, local station" },
      { key: "station_id", label: "Station / location ID", placeholder: "Optional station or location" },
      { key: "api_key_ref", label: "API key reference", placeholder: "Optional vault/reference only", secret: true },
    ],
    sampleFile: {
      filename: "weather-sample.csv",
      body:
        "timestamp,field,temperature,rainfall,humidity,note\n" +
        "2026-06-26 06:00:00,North Ranch,72,0,41,Dry morning\n" +
        "2026-06-26 14:00:00,North Ranch,91,0,28,High afternoon evaporative demand\n",
    },
  },
  openet: {
    label: "OpenET / ET data",
    short: "ET API or ET export.",
    logoText: "ET",
    logoStyle: { background: "#EEF2FF", color: "#4338CA", border: "1px solid #C7D2FE" },
    setupKind: "api_upload",
    primaryMethod: "manual_upload",
    headline: "Connect ET data",
    description:
      "Add ET context through OpenET/API credentials or uploaded ET exports. This improves water accounting and recommendations.",
    primaryButton: "Upload ET file",
    secondaryNote: "Live OpenET needs API access. Uploading exports works immediately for pilots and demos.",
    configFields: [
      { key: "provider", label: "ET provider", placeholder: "OpenET" },
      { key: "field_boundary_ref", label: "Field boundary reference", placeholder: "Optional parcel/field boundary ID" },
      { key: "api_key_ref", label: "API key reference", placeholder: "Optional vault/reference only", secret: true },
    ],
    sampleFile: {
      filename: "openet-sample.csv",
      body:
        "timestamp,field,block,crop,et,eto,note\n" +
        "2026-06-26,North Ranch,Block A,Almonds,0.22,0.28,Daily ET estimate\n" +
        "2026-06-26,North Ranch,Block B,Almonds,0.19,0.28,Lower ET due to canopy variance\n",
    },
  },
  gmail: {
    label: "Gmail",
    short: "Connect account. Pull evidence later.",
    logoText: "M",
    logoStyle: { background: "#FEF2F2", color: "#DC2626", border: "1px solid #FECACA" },
    setupKind: "oauth",
    primaryMethod: "oauth",
    headline: "Connect Gmail",
    description:
      "The customer should only need one action: connect Gmail. Then AGRO-AI can read selected reports, attachments, and operational emails after OAuth is enabled.",
    primaryButton: "Connect Gmail",
    secondaryNote: "Internal mode prepares the connection. Production requires Google OAuth credentials and scopes.",
    configFields: [
      { key: "account_label", label: "Account label", placeholder: "operations@customer.com" },
    ],
  },
  outlook: {
    label: "Outlook",
    short: "Connect Microsoft account.",
    logoText: "O",
    logoStyle: { background: "#EFF6FF", color: "#2563EB", border: "1px solid #BFDBFE" },
    setupKind: "oauth",
    primaryMethod: "oauth",
    headline: "Connect Outlook",
    description:
      "The customer should connect Outlook once. AGRO-AI can later use approved attachments, reports, and operational messages as evidence.",
    primaryButton: "Connect Outlook",
    secondaryNote: "Internal mode prepares the connection. Production requires Microsoft OAuth configuration.",
    configFields: [
      { key: "account_label", label: "Account label", placeholder: "operations@customer.com" },
    ],
  },
  google_drive: {
    label: "Google Drive",
    short: "Connect Drive folders.",
    logoText: "D",
    logoStyle: { background: "#ECFDF5", color: "#16A34A", border: "1px solid #BBF7D0" },
    setupKind: "oauth",
    primaryMethod: "oauth",
    headline: "Connect Google Drive",
    description:
      "The customer should connect Drive and select a folder. AGRO-AI can later ingest PDFs, spreadsheets, reports, and evidence packets.",
    primaryButton: "Connect Drive",
    secondaryNote: "Internal mode prepares the connection. Production requires Google Drive OAuth and folder picker.",
    configFields: [
      { key: "folder_hint", label: "Folder hint", placeholder: "Water reports / irrigation exports" },
    ],
  },
  custom_api: {
    label: "Custom API",
    short: "Enterprise API source.",
    logoText: "{ }",
    logoStyle: { background: "#FDF2F8", color: "#BE185D", border: "1px solid #FBCFE8" },
    setupKind: "custom_api",
    primaryMethod: "custom_api",
    headline: "Connect custom API",
    description:
      "For districts, agribusinesses, agencies, and enterprise customers with their own operational API.",
    primaryButton: "Save API connection",
    secondaryNote: "Store endpoint and credential reference. Provider-specific sync can be implemented after schema review.",
    configFields: [
      { key: "base_url", label: "Base URL", placeholder: "https://api.customer.com/water" },
      { key: "auth_type", label: "Auth type", placeholder: "Bearer token, API key, OAuth, signed request" },
      { key: "credential_ref", label: "Credential reference", placeholder: "Vault/reference only", secret: true },
    ],
  },
};

function profileFor(id: string): ConnectorProfile {
  return PROFILES[id] || {
    label: id,
    short: "Connector",
    logoText: id.slice(0, 2).toUpperCase(),
    logoStyle: { background: "#F8FAFC", color: "#334155", border: "1px solid #CBD5E1" },
    setupKind: "upload",
    primaryMethod: "manual_upload",
    headline: `Connect ${id}`,
    description: "Set up this source and bring its data into AGRO-AI evidence.",
    primaryButton: "Set up",
    secondaryNote: "Configuration depends on provider capabilities.",
    configFields: [],
  };
}

function asArray(value: unknown): AnyRecord[] {
  return Array.isArray(value) ? (value as AnyRecord[]) : [];
}

function pretty(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return fallback;
  }
}

function statusTone(status: string): "neutral" | "good" | "warn" | "locked" {
  if (["ready", "synced", "test_passed", "upload_ready"].includes(status)) return "good";
  if (["coming_soon", "enterprise"].includes(status)) return "locked";
  if (status.includes("missing") || status.includes("needs") || status.includes("not_configured") || status.includes("mapping")) return "warn";
  return "neutral";
}

export function Integrations() {
  const { currentOrganization, currentWorkspace } = useAuth();
  const catalogState = usePortalResource<AnyRecord>(useCallback(() => apiClient.connectorHub.catalog(), []));
  const connectionsState = usePortalResource<AnyRecord>(useCallback(() => apiClient.connectorHub.connections(), []));
  const [selected, setSelected] = useState<Connector | null>(null);
  const [connection, setConnection] = useState<AnyRecord | null>(null);
  const [uploadResult, setUploadResult] = useState<AnyRecord | null>(null);
  const [config, setConfig] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [search, setSearch] = useState("");

  const catalog = useMemo(() => asArray(catalogState.data?.connectors) as Connector[], [catalogState.data]);
  const connections = asArray(connectionsState.data?.connections);
  const plan = String(currentOrganization?.plan || "internal").toLowerCase();

  const visibleCatalog = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return catalog;
    return catalog.filter((item) => {
      const profile = profileFor(item.id);
      return [
        item.name,
        item.category,
        item.status,
        item.promise,
        profile.label,
        profile.short,
        ...(item.imports || []),
      ].join(" ").toLowerCase().includes(q);
    });
  }, [catalog, search]);

  async function refresh() {
    await Promise.all([catalogState.refresh(), connectionsState.refresh()]);
  }

  async function startConnection(connector: Connector, method?: string) {
    const profile = profileFor(connector.id);
    const result = await apiClient.connectorHub.start({
      provider: connector.id as any,
      method: method || profile.primaryMethod,
      workspace_id: currentWorkspace?.id,
      metadata: { surface: "connector_hub_v2", setup_kind: profile.setupKind },
    }) as AnyRecord;

    return result.connection || connector.connection || null;
  }

  async function openConnector(connector: Connector) {
    const existing = connections.find((row) => row.provider === connector.id) || connector.connection || null;
    const profile = profileFor(connector.id);

    setSelected(connector);
    setConnection(existing);
    setUploadResult(null);
    setMessage("");
    setConfig({});
    setBusy(connector.id);

    try {
      const nextConnection = await startConnection(connector, profile.primaryMethod);
      setConnection(nextConnection);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not start connector setup.");
    } finally {
      setBusy("");
    }
  }

  async function ensureConnection() {
    if (!selected) throw new Error("No connector selected.");
    if (connection?.id) return connection;
    const nextConnection = await startConnection(selected);
    setConnection(nextConnection);
    return nextConnection;
  }

  async function uploadFile(file?: File) {
    if (!file) return;

    setBusy("upload");
    setMessage("");
    setUploadResult(null);

    try {
      const activeConnection = await ensureConnection();
      const result = await apiClient.connectorHub.upload(activeConnection.id, file) as AnyRecord;
      setUploadResult(result);
      setConnection(result.connection || activeConnection);
      setMessage(`Imported ${pretty(result.evidence_records_created, "0")} evidence records from ${file.name}.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setBusy("");
    }
  }

  async function uploadSample() {
    if (!selected) return;
    const sample = profileFor(selected.id).sampleFile;
    if (!sample) return;

    const file = new File([sample.body], sample.filename, { type: "text/csv" });
    await uploadFile(file);
  }

  async function testCurrent() {
    setBusy("test");
    setMessage("");

    try {
      const activeConnection = await ensureConnection();
      const result = await apiClient.connectorHub.test(activeConnection.id) as AnyRecord;
      setConnection(result.connection || activeConnection);
      setMessage(result.message || "Connection tested.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Connection test failed.");
    } finally {
      setBusy("");
    }
  }

  async function syncCurrent() {
    setBusy("sync");
    setMessage("");

    try {
      const activeConnection = await ensureConnection();
      const result = await apiClient.connectorHub.sync(activeConnection.id) as AnyRecord;
      setConnection(result.connection || activeConnection);
      setMessage(`${pretty(result.evidence_records, "0")} evidence records available from this connector.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Sync failed.");
    } finally {
      setBusy("");
    }
  }

  async function saveConfiguration(status = "test_passed", credentialsRef?: string) {
    setBusy("save");
    setMessage("");

    try {
      const activeConnection = await ensureConnection();
      const result = await apiClient.connectorHub.update(activeConnection.id, {
        status,
        credentials_ref: credentialsRef || activeConnection.credentials_ref || `${activeConnection.provider}_internal_config`,
        config: {
          ...config,
          setup_kind: selected ? profileFor(selected.id).setupKind : "unknown",
          saved_from: "connector_hub_v2",
        },
      }) as AnyRecord;

      setConnection(result.connection || activeConnection);
      setMessage("Connection configuration saved.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save configuration.");
    } finally {
      setBusy("");
    }
  }

  async function connectOAuth() {
    if (!selected) return;
    const profile = profileFor(selected.id);

    setBusy("oauth");
    setMessage("");

    try {
      const activeConnection = await ensureConnection();
      const result = await apiClient.connectorHub.update(activeConnection.id, {
        status: "test_passed",
        credentials_ref: `${selected.id}_oauth_internal_ready`,
        config: {
          ...config,
          auth_method: "oauth",
          oauth_status: "prepared_for_internal_testing",
          production_note: "Replace this with provider OAuth redirect when client credentials are configured.",
        },
      }) as AnyRecord;

      setConnection(result.connection || activeConnection);
      setMessage(`${profile.label} connection prepared. Production OAuth can replace this one-click internal connection.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "OAuth setup failed.");
    } finally {
      setBusy("");
    }
  }

  const selectedProfile = selected ? profileFor(selected.id) : null;
  const selectedStatus = String(connection?.status || selected?.connection?.status || selected?.status || "not_configured");

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <StatusBadge label="Connector Directory" tone="good" />
              <StatusBadge label={`${plan} mode`} />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Connectors</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Connect each source with the simplest path for that system: controller export upload, one-click account connection, API key reference, or custom endpoint.
            </p>
          </div>
          <PortalButton variant="secondary" onClick={refresh}>Refresh</PortalButton>
        </div>
      </header>

      <div className="px-8 py-6 space-y-6" style={{ maxWidth: 1280 }}>
        {catalogState.error ? <InlineState title={catalogState.error} /> : null}
        {message ? <InlineState title={message} /> : null}

        <section className="grid grid-cols-4 gap-4">
          <Metric label="Available connectors" value={String(catalog.length)} />
          <Metric label="Created connections" value={String(connections.length)} />
          <Metric label="Upload paths" value={String(catalog.filter((item) => item.upload_supported).length)} />
          <Metric label="Internal gates" value="Unlocked" />
        </section>

        <div className="flex items-center justify-between gap-4">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search connectors..."
            className="h-11 flex-1 rounded-xl px-4 text-[13px] outline-none"
            style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: TEXT }}
          />
          <div className="text-[12px]" style={{ color: MUTED }}>
            {visibleCatalog.length} shown
          </div>
        </div>

        <section className="grid grid-cols-3 gap-4">
          {visibleCatalog.map((connector) => {
            const live = connections.find((row) => row.provider === connector.id) || connector.connection;
            const status = String(live?.status || connector.status);
            const profile = profileFor(connector.id);

            return (
              <article key={connector.id} className="rounded-2xl p-5 flex flex-col min-h-[292px]" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
                <div className="flex items-start justify-between gap-3 mb-4">
                  <div className="flex items-center gap-3">
                    <ConnectorLogo profile={profile} />
                    <div>
                      <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>{connector.category || profile.setupKind}</div>
                      <h3 className="text-[16px] font-semibold" style={{ color: TEXT }}>{profile.label}</h3>
                    </div>
                  </div>
                  <StatusBadge label={status} tone={statusTone(status)} />
                </div>

                <p className="text-[12px] leading-relaxed mb-3" style={{ color: MUTED }}>{profile.short}</p>
                <p className="text-[12px] leading-relaxed mb-4 flex-1" style={{ color: MUTED }}>{profile.description}</p>

                <div className="flex flex-wrap gap-1.5 mb-4">
                  {connector.upload_supported ? <Chip>upload</Chip> : null}
                  {profile.setupKind === "oauth" ? <Chip>OAuth</Chip> : null}
                  {profile.setupKind === "controller" ? <Chip>controller</Chip> : null}
                  {profile.setupKind === "api_upload" ? <Chip>API / upload</Chip> : null}
                  {profile.setupKind === "custom_api" ? <Chip>enterprise</Chip> : null}
                </div>

                <button
                  type="button"
                  onClick={() => openConnector({ ...connector, connection: live })}
                  className="h-10 rounded-lg text-[12px] font-semibold"
                  style={{ background: "#16533C", color: "white" }}
                >
                  {busy === connector.id ? "Opening…" : live ? "Manage" : "Set up"}
                </button>
              </article>
            );
          })}
        </section>
      </div>

      {selected && selectedProfile ? (
        <div className="fixed inset-0 z-50">
          <button className="absolute inset-0 bg-black/30" onClick={() => setSelected(null)} aria-label="Close connector setup" />

          <aside className="absolute right-0 top-0 h-full w-[680px] max-w-[96vw] overflow-y-auto shadow-2xl" style={{ background: SURFACE }}>
            <div className="px-6 py-5" style={{ borderBottom: `1px solid ${BORDER}` }}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-4">
                  <ConnectorLogo profile={selectedProfile} large />
                  <div>
                    <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>{selectedProfile.setupKind.replace("_", " ")}</div>
                    <h2 className="text-[22px] font-semibold" style={{ color: TEXT }}>{selectedProfile.headline}</h2>
                    <p className="mt-2 text-[13px] leading-relaxed max-w-[460px]" style={{ color: MUTED }}>{selectedProfile.description}</p>
                  </div>
                </div>
                <StatusBadge label={selectedStatus} tone={statusTone(selectedStatus)} />
              </div>
            </div>

            <div className="p-6 space-y-5">
              <Panel title="Connection">
                <Info label="Provider" value={selectedProfile.label} />
                <Info label="Connection ID" value={pretty(connection?.id)} />
                <Info label="Mode" value={pretty(connection?.mode || selectedProfile.primaryMethod)} />
                <Info label="Status" value={selectedStatus} />
                <Info label="Live sync" value={connection?.live_sync_enabled ? "Enabled" : "Not enabled yet"} />
              </Panel>

              {selectedProfile.setupKind === "controller" ? (
                <ControllerSetup
                  profile={selectedProfile}
                  config={config}
                  setConfig={setConfig}
                  busy={busy}
                  onUpload={uploadFile}
                  onSample={uploadSample}
                  onSave={() => saveConfiguration("test_passed")}
                  onTest={testCurrent}
                  onSync={syncCurrent}
                />
              ) : null}

              {selectedProfile.setupKind === "upload" ? (
                <UploadSetup
                  profile={selectedProfile}
                  busy={busy}
                  onUpload={uploadFile}
                  onSample={uploadSample}
                  onSync={syncCurrent}
                />
              ) : null}

              {selectedProfile.setupKind === "api_upload" ? (
                <ApiUploadSetup
                  profile={selectedProfile}
                  config={config}
                  setConfig={setConfig}
                  busy={busy}
                  onUpload={uploadFile}
                  onSample={uploadSample}
                  onSave={() => saveConfiguration("test_passed")}
                  onTest={testCurrent}
                  onSync={syncCurrent}
                />
              ) : null}

              {selectedProfile.setupKind === "oauth" ? (
                <OAuthSetup
                  profile={selectedProfile}
                  config={config}
                  setConfig={setConfig}
                  busy={busy}
                  onConnect={connectOAuth}
                  onTest={testCurrent}
                />
              ) : null}

              {selectedProfile.setupKind === "custom_api" ? (
                <CustomApiSetup
                  profile={selectedProfile}
                  config={config}
                  setConfig={setConfig}
                  busy={busy}
                  onSave={() => saveConfiguration("test_passed")}
                  onTest={testCurrent}
                />
              ) : null}

              {uploadResult ? (
                <Panel title="Latest import">
                  <Info label="Rows parsed" value={pretty(uploadResult.rows_parsed)} />
                  <Info label="Evidence records" value={pretty(uploadResult.evidence_records_created)} />
                  <Info label="Warnings" value={(uploadResult.warnings || []).join("; ") || "None"} />

                  <div className="mt-3 flex flex-wrap gap-2">
                    {Object.entries(uploadResult.mapping_suggestions || {}).slice(0, 14).map(([source, target]) => (
                      <Chip key={source}>{source} → {String(target)}</Chip>
                    ))}
                  </div>
                </Panel>
              ) : null}

              <Panel title="After connection">
                <div className="grid grid-cols-3 gap-2">
                  <PortalButton variant="secondary" onClick={() => window.location.assign("/evidence")}>Open Evidence</PortalButton>
                  <PortalButton variant="secondary" onClick={() => window.location.assign("/intelligence")}>Ask AGRO-AI</PortalButton>
                  <PortalButton variant="secondary" onClick={() => window.location.assign("/reports")}>Generate Report</PortalButton>
                </div>
              </Panel>
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  );
}

function ControllerSetup({
  profile,
  config,
  setConfig,
  busy,
  onUpload,
  onSample,
  onSave,
  onTest,
  onSync,
}: {
  profile: ConnectorProfile;
  config: Record<string, string>;
  setConfig: (next: Record<string, string>) => void;
  busy: string;
  onUpload: (file?: File) => void;
  onSample: () => void;
  onSave: () => void;
  onTest: () => void;
  onSync: () => void;
}) {
  return (
    <>
      <Panel title="Recommended path">
        <div className="rounded-xl p-4 mb-4" style={{ background: "#F0FDF4", border: "1px solid #BBF7D0" }}>
          <div className="text-[13px] font-semibold mb-1" style={{ color: "#15803D" }}>1. Upload controller export</div>
          <div className="text-[12px] leading-relaxed" style={{ color: "#166534" }}>
            This works now. It is the fastest way to get WiseConn/Talgil data into AGRO-AI without waiting for live API credentials.
          </div>
        </div>

        <FileInput label={profile.primaryButton} onUpload={onUpload} />

        <div className="mt-3 flex flex-wrap gap-2">
          {profile.sampleFile ? <PortalButton variant="secondary" onClick={onSample} disabled={busy === "upload"}>{busy === "upload" ? "Uploading…" : "Use sample export"}</PortalButton> : null}
          <PortalButton variant="secondary" onClick={onSync} disabled={busy === "sync"}>{busy === "sync" ? "Syncing…" : "Sync evidence"}</PortalButton>
        </div>
      </Panel>

      <Panel title="Optional live API configuration">
        <ConfigFields fields={profile.configFields} config={config} setConfig={setConfig} />
        <p className="text-[12px] leading-relaxed mt-3 mb-3" style={{ color: MUTED }}>{profile.secondaryNote}</p>
        <div className="flex gap-2">
          <PortalButton onClick={onSave} disabled={busy === "save"}>{busy === "save" ? "Saving…" : "Save API info"}</PortalButton>
          <PortalButton variant="secondary" onClick={onTest} disabled={busy === "test"}>{busy === "test" ? "Testing…" : "Test readiness"}</PortalButton>
        </div>
      </Panel>
    </>
  );
}

function UploadSetup({
  profile,
  busy,
  onUpload,
  onSample,
  onSync,
}: {
  profile: ConnectorProfile;
  busy: string;
  onUpload: (file?: File) => void;
  onSample: () => void;
  onSync: () => void;
}) {
  return (
    <Panel title="Upload source">
      <FileInput label={profile.primaryButton} onUpload={onUpload} />
      <p className="text-[12px] leading-relaxed mt-3 mb-3" style={{ color: MUTED }}>{profile.secondaryNote}</p>
      <div className="flex gap-2">
        {profile.sampleFile ? <PortalButton variant="secondary" onClick={onSample} disabled={busy === "upload"}>{busy === "upload" ? "Uploading…" : "Use sample file"}</PortalButton> : null}
        <PortalButton variant="secondary" onClick={onSync} disabled={busy === "sync"}>{busy === "sync" ? "Syncing…" : "Sync evidence"}</PortalButton>
      </div>
    </Panel>
  );
}

function ApiUploadSetup({
  profile,
  config,
  setConfig,
  busy,
  onUpload,
  onSample,
  onSave,
  onTest,
  onSync,
}: {
  profile: ConnectorProfile;
  config: Record<string, string>;
  setConfig: (next: Record<string, string>) => void;
  busy: string;
  onUpload: (file?: File) => void;
  onSample: () => void;
  onSave: () => void;
  onTest: () => void;
  onSync: () => void;
}) {
  return (
    <>
      <Panel title="Simple path">
        <FileInput label={profile.primaryButton} onUpload={onUpload} />
        <div className="mt-3 flex gap-2">
          {profile.sampleFile ? <PortalButton variant="secondary" onClick={onSample} disabled={busy === "upload"}>{busy === "upload" ? "Uploading…" : "Use sample file"}</PortalButton> : null}
          <PortalButton variant="secondary" onClick={onSync} disabled={busy === "sync"}>{busy === "sync" ? "Syncing…" : "Sync evidence"}</PortalButton>
        </div>
      </Panel>

      <Panel title="API configuration">
        <ConfigFields fields={profile.configFields} config={config} setConfig={setConfig} />
        <p className="text-[12px] leading-relaxed mt-3 mb-3" style={{ color: MUTED }}>{profile.secondaryNote}</p>
        <div className="flex gap-2">
          <PortalButton onClick={onSave} disabled={busy === "save"}>{busy === "save" ? "Saving…" : "Save API info"}</PortalButton>
          <PortalButton variant="secondary" onClick={onTest} disabled={busy === "test"}>{busy === "test" ? "Testing…" : "Test readiness"}</PortalButton>
        </div>
      </Panel>
    </>
  );
}

function OAuthSetup({
  profile,
  config,
  setConfig,
  busy,
  onConnect,
  onTest,
}: {
  profile: ConnectorProfile;
  config: Record<string, string>;
  setConfig: (next: Record<string, string>) => void;
  busy: string;
  onConnect: () => void;
  onTest: () => void;
}) {
  return (
    <Panel title="Connect account">
      <div className="rounded-xl p-4 mb-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
        <div className="text-[13px] font-semibold mb-1" style={{ color: TEXT }}>One-click connection</div>
        <div className="text-[12px] leading-relaxed" style={{ color: MUTED }}>
          For customers, this should be one click. Internal testing prepares the connector record now. Production OAuth will replace this with the provider redirect.
        </div>
      </div>

      <ConfigFields fields={profile.configFields} config={config} setConfig={setConfig} />

      <div className="mt-4 flex gap-2">
        <PortalButton onClick={onConnect} disabled={busy === "oauth"}>{busy === "oauth" ? "Connecting…" : profile.primaryButton}</PortalButton>
        <PortalButton variant="secondary" onClick={onTest} disabled={busy === "test"}>{busy === "test" ? "Testing…" : "Test readiness"}</PortalButton>
      </div>

      <p className="text-[12px] leading-relaxed mt-3" style={{ color: MUTED }}>{profile.secondaryNote}</p>
    </Panel>
  );
}

function CustomApiSetup({
  profile,
  config,
  setConfig,
  busy,
  onSave,
  onTest,
}: {
  profile: ConnectorProfile;
  config: Record<string, string>;
  setConfig: (next: Record<string, string>) => void;
  busy: string;
  onSave: () => void;
  onTest: () => void;
}) {
  return (
    <Panel title="Custom API">
      <ConfigFields fields={profile.configFields} config={config} setConfig={setConfig} />
      <p className="text-[12px] leading-relaxed mt-3 mb-3" style={{ color: MUTED }}>{profile.secondaryNote}</p>
      <div className="flex gap-2">
        <PortalButton onClick={onSave} disabled={busy === "save"}>{busy === "save" ? "Saving…" : profile.primaryButton}</PortalButton>
        <PortalButton variant="secondary" onClick={onTest} disabled={busy === "test"}>{busy === "test" ? "Testing…" : "Test readiness"}</PortalButton>
      </div>
    </Panel>
  );
}

function ConfigFields({
  fields,
  config,
  setConfig,
}: {
  fields: ConnectorProfile["configFields"];
  config: Record<string, string>;
  setConfig: (next: Record<string, string>) => void;
}) {
  if (!fields.length) return null;

  return (
    <div className="space-y-3">
      {fields.map((field) => (
        <label key={field.key} className="block text-[12px]" style={{ color: MUTED }}>
          {field.label}
          <input
            value={config[field.key] || ""}
            type={field.secret ? "password" : "text"}
            placeholder={field.placeholder}
            onChange={(event) => setConfig({ ...config, [field.key]: event.target.value })}
            className="mt-1 h-10 w-full rounded-lg px-3 text-[13px] outline-none"
            style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: TEXT }}
          />
        </label>
      ))}
    </div>
  );
}

function FileInput({ label, onUpload }: { label: string; onUpload: (file?: File) => void }) {
  return (
    <label className="block rounded-xl p-4 cursor-pointer" style={{ background: SURFACE, border: `1px dashed ${BORDER}` }}>
      <div className="text-[13px] font-semibold mb-1" style={{ color: TEXT }}>{label}</div>
      <div className="text-[12px] leading-relaxed mb-3" style={{ color: MUTED }}>
        Choose a CSV, JSON, TXT, or PDF text file.
      </div>
      <input
        type="file"
        accept=".csv,.json,.txt,.pdf"
        onChange={(event) => onUpload(event.target.files?.[0])}
        className="text-[12px]"
        style={{ color: TEXT }}
      />
    </label>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>{label}</div>
      <div className="text-[24px] font-semibold" style={{ color: TEXT }}>{value}</div>
    </section>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>{title}</div>
      {children}
    </section>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 py-2 text-[12px]">
      <span style={{ color: MUTED }}>{label}</span>
      <span className="font-semibold text-right" style={{ color: TEXT }}>{value}</span>
    </div>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full px-2.5 py-1 text-[10px] font-medium" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>
      {children}
    </span>
  );
}

function ConnectorLogo({ profile, large = false }: { profile: ConnectorProfile; large?: boolean }) {
  const size = large ? 54 : 42;

  return (
    <div
      className="rounded-xl flex items-center justify-center font-bold shadow-sm"
      style={{
        width: size,
        height: size,
        minWidth: size,
        ...profile.logoStyle,
      }}
      aria-label={`${profile.label} logo`}
    >
      <span style={{ fontSize: large ? 18 : 14, letterSpacing: "-0.02em" }}>{profile.logoText}</span>
    </div>
  );
}
