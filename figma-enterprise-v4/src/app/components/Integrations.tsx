import { useCallback, useMemo, useState, type ReactNode } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";
import talgilLogo from "../../imports/talgil-logo-hq.png";
import wiseconnLogo from "../../imports/wiseconn-logo-hq.png";

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

type ConnectorType = "controller" | "files" | "account" | "data_provider" | "custom_api";

type ConnectorProfile = {
  id: string;
  title: string;
  subtitle: string;
  type: ConnectorType;
  logoUrl?: string;
  logoAsset?: string;
  logoFallback: string;
  logoBg: string;
  logoColor: string;
  cardDescription: string;
  drawerTitle: string;
  drawerDescription: string;
  primaryAction: string;
  method: string;
  fields: { key: string; label: string; placeholder: string; secret?: boolean; type?: string }[];
  supportsUpload: boolean;
  uploadLabel?: string;
  sampleFile?: {
    filename: string;
    body: string;
  };
};

const PROFILES: Record<string, ConnectorProfile> = {
  wiseconn: {
    id: "wiseconn",
    title: "WiseConn",
    subtitle: "Irrigation controller",
    type: "controller",
    logoAsset: wiseconnLogo,
    logoFallback: "W",
    logoBg: "#ECFDF5",
    logoColor: "#047857",
    cardDescription: "Connect a WiseConn environment or upload controller exports for immediate evidence ingestion.",
    drawerTitle: "Connect WiseConn",
    drawerDescription: "Add the customer’s WiseConn access details or upload a controller export. The upload path works immediately; live sync requires valid API access.",
    primaryAction: "Save WiseConn connection",
    method: "api_credentials",
    supportsUpload: true,
    uploadLabel: "Upload WiseConn export",
    fields: [
      { key: "environment_name", label: "Environment name", placeholder: "North Ranch WiseConn" },
      { key: "account_url", label: "WiseConn URL / environment", placeholder: "https://..." },
      { key: "username", label: "Username / email", placeholder: "operations@farm.com" },
      { key: "credential_ref", label: "API key or credential reference", placeholder: "Paste API key or secure reference", secret: true },
    ],
    sampleFile: {
      filename: "wiseconn-export-sample.csv",
      body:
        "timestamp,field,block,crop,flow_gpm,duration_minutes,water_gallons,valve_state,note\n" +
        "2026-06-26 06:00:00,North Ranch,Block A,Almonds,420,45,18900,on,Morning irrigation completed\n" +
        "2026-06-26 08:30:00,North Ranch,Block B,Almonds,390,35,13650,off,Shorter irrigation due to wet soil\n",
    },
  },
  talgil: {
    id: "talgil",
    title: "Talgil",
    subtitle: "Irrigation controller",
    type: "controller",
    logoAsset: talgilLogo,
    logoFallback: "T",
    logoBg: "#EFF6FF",
    logoColor: "#1D4ED8",
    cardDescription: "Connect Talgil controller programs, zones, valve events, flow readings, and irrigation logs.",
    drawerTitle: "Connect Talgil",
    drawerDescription: "Add the Talgil environment details or upload program/controller exports. AGRO-AI will normalize events into evidence records.",
    primaryAction: "Save Talgil connection",
    method: "api_credentials",
    supportsUpload: true,
    uploadLabel: "Upload Talgil export",
    fields: [
      { key: "environment_name", label: "Environment name", placeholder: "South Ranch Talgil" },
      { key: "account_url", label: "Talgil URL / environment", placeholder: "https://..." },
      { key: "username", label: "Username / email", placeholder: "operator@farm.com" },
      { key: "credential_ref", label: "API key or credential reference", placeholder: "Paste API key or secure reference", secret: true },
    ],
    sampleFile: {
      filename: "talgil-export-sample.csv",
      body:
        "timestamp,field,block,crop,flow_gpm,duration_minutes,water_gallons,valve_state,note\n" +
        "2026-06-26 05:45:00,South Ranch,Zone 12,Pistachios,510,50,25500,on,Talgil program A completed\n" +
        "2026-06-26 07:20:00,South Ranch,Zone 14,Pistachios,475,30,14250,off,Program stopped after pressure alert\n",
    },
  },
  manual_csv: {
    id: "manual_csv",
    title: "Files",
    subtitle: "CSV, PDF, spreadsheets",
    type: "files",
    logoFallback: "↥",
    logoBg: "#F8FAFC",
    logoColor: "#334155",
    cardDescription: "Upload CSV, PDF, spreadsheet exports, field logs, compliance documents, and messy customer files.",
    drawerTitle: "Upload files",
    drawerDescription: "Attach files here. AGRO-AI parses what it can, stores the source, and turns each usable row or note into evidence.",
    primaryAction: "Upload files",
    method: "manual_upload",
    supportsUpload: true,
    uploadLabel: "Upload CSV, JSON, TXT, or PDF",
    fields: [
      { key: "source_label", label: "Source label", placeholder: "June irrigation records" },
    ],
    sampleFile: {
      filename: "agro-ai-file-sample.csv",
      body:
        "timestamp,field,block,crop,flow_gpm,duration_minutes,water_gallons,note\n" +
        "2026-06-26 06:00:00,North Ranch,Block A,Almonds,420,45,18900,Morning irrigation completed\n" +
        "2026-06-26 08:30:00,North Ranch,Block B,Almonds,390,35,13650,Shorter irrigation due to wet soil\n",
    },
  },
  gmail: {
    id: "gmail",
    title: "Gmail",
    subtitle: "Email context + reports",
    type: "account",
    logoUrl: "https://www.google.com/s2/favicons?domain=mail.google.com&sz=128",
    logoFallback: "M",
    logoBg: "#FEF2F2",
    logoColor: "#DC2626",
    cardDescription: "Connect Gmail so AGRO-AI can read approved field context, attachments, and send reports when requested.",
    drawerTitle: "Connect Gmail",
    drawerDescription: "Connect the customer’s Gmail account. AGRO-AI can use approved email context, analyze attachments, and optionally send reports.",
    primaryAction: "Connect Gmail",
    method: "oauth",
    supportsUpload: false,
    fields: [
      { key: "account_email", label: "Gmail account", placeholder: "operations@farm.com", type: "email" },
      { key: "scope_note", label: "Context to use", placeholder: "Irrigation reports, water agency emails, field attachments" },
    ],
  },
  outlook: {
    id: "outlook",
    title: "Outlook",
    subtitle: "Microsoft email context",
    type: "account",
    logoUrl: "https://www.google.com/s2/favicons?domain=outlook.office.com&sz=128",
    logoFallback: "O",
    logoBg: "#EFF6FF",
    logoColor: "#2563EB",
    cardDescription: "Connect Outlook for operational emails, attachments, and report delivery.",
    drawerTitle: "Connect Outlook",
    drawerDescription: "Connect the customer’s Microsoft account. AGRO-AI can use approved email context and send reports when requested.",
    primaryAction: "Connect Outlook",
    method: "oauth",
    supportsUpload: false,
    fields: [
      { key: "account_email", label: "Outlook account", placeholder: "operations@farm.com", type: "email" },
      { key: "scope_note", label: "Context to use", placeholder: "Reports, attachments, grower communications" },
    ],
  },
  google_drive: {
    id: "google_drive",
    title: "Google Drive",
    subtitle: "Documents + folders",
    type: "account",
    logoUrl: "https://www.google.com/s2/favicons?domain=drive.google.com&sz=128",
    logoFallback: "D",
    logoBg: "#ECFDF5",
    logoColor: "#16A34A",
    cardDescription: "Connect Drive folders containing PDFs, spreadsheets, water reports, maps, and field records.",
    drawerTitle: "Connect Google Drive",
    drawerDescription: "Connect Drive and select the folders AGRO-AI should use as context. Production will use Google OAuth and a folder picker.",
    primaryAction: "Connect Drive",
    method: "oauth",
    supportsUpload: false,
    fields: [
      { key: "folder_hint", label: "Folder or context hint", placeholder: "Water reports / irrigation exports / compliance docs" },
    ],
  },
  weather: {
    id: "weather",
    title: "Weather",
    subtitle: "Forecasts + station data",
    type: "data_provider",
    logoFallback: "☀",
    logoBg: "#FFFBEB",
    logoColor: "#B45309",
    cardDescription: "Connect weather providers or upload local weather station exports.",
    drawerTitle: "Connect weather data",
    drawerDescription: "Connect an existing weather provider, station export, or forecast API. AGRO-AI uses this for irrigation timing and risk.",
    primaryAction: "Save weather provider",
    method: "api_credentials",
    supportsUpload: true,
    uploadLabel: "Upload weather file",
    fields: [
      { key: "provider_name", label: "Provider", placeholder: "NOAA, Tomorrow.io, OpenWeather, local station" },
      { key: "location_or_station", label: "Location / station ID", placeholder: "Station ID, coordinates, or farm location" },
      { key: "credential_ref", label: "API key or credential reference", placeholder: "Paste API key or secure reference", secret: true },
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
    id: "openet",
    title: "OpenET",
    subtitle: "ET + water use",
    type: "data_provider",
    logoUrl: "https://www.google.com/s2/favicons?domain=openetdata.org&sz=128",
    logoFallback: "ET",
    logoBg: "#EEF2FF",
    logoColor: "#4338CA",
    cardDescription: "Connect ET data for field-level water accounting, evapotranspiration, and assurance reports.",
    drawerTitle: "Connect OpenET / ET data",
    drawerDescription: "Connect OpenET or upload ET exports. This gives AGRO-AI stronger context for water use and crop demand.",
    primaryAction: "Save ET provider",
    method: "api_credentials",
    supportsUpload: true,
    uploadLabel: "Upload ET file",
    fields: [
      { key: "provider_name", label: "Provider", placeholder: "OpenET or ET provider" },
      { key: "field_boundary_ref", label: "Field boundary / parcel reference", placeholder: "Parcel ID, field ID, or geometry reference" },
      { key: "credential_ref", label: "API key or credential reference", placeholder: "Paste API key or secure reference", secret: true },
    ],
    sampleFile: {
      filename: "openet-sample.csv",
      body:
        "timestamp,field,block,crop,et,eto,note\n" +
        "2026-06-26,North Ranch,Block A,Almonds,0.22,0.28,Daily ET estimate\n" +
        "2026-06-26,North Ranch,Block B,Almonds,0.19,0.28,Lower ET due to canopy variance\n",
    },
  },
  custom_api: {
    id: "custom_api",
    title: "Data Provider API",
    subtitle: "Existing systems",
    type: "custom_api",
    logoFallback: "API",
    logoBg: "#FDF2F8",
    logoColor: "#BE185D",
    cardDescription: "Connect an existing farm, agency, ERP, telemetry, or water accounting data provider.",
    drawerTitle: "Connect existing data provider",
    drawerDescription: "Use this for any system the customer already uses. Add the provider name, base URL, and credential reference. AGRO-AI will treat it as a source hub.",
    primaryAction: "Connect data provider",
    method: "custom_api",
    supportsUpload: false,
    fields: [
      { key: "provider_name", label: "Provider name", placeholder: "Ranch Systems, WiseConn partner API, agency portal, ERP, telemetry vendor" },
      { key: "base_url", label: "Provider URL", placeholder: "https://api.provider.com or portal URL" },
      { key: "auth_type", label: "Access method", placeholder: "API key, OAuth, SFTP, webhook, database, manual export" },
      { key: "credential_ref", label: "Credential reference", placeholder: "Paste API key or secure reference", secret: true },
    ],
  },
};

const TYPE_ORDER: ConnectorType[] = ["controller", "files", "account", "data_provider", "custom_api"];

const TYPE_LABEL: Record<ConnectorType, string> = {
  controller: "Controllers",
  files: "Files",
  account: "Accounts",
  data_provider: "Data providers",
  custom_api: "Custom APIs",
};

function profileFor(id: string, connector?: Connector): ConnectorProfile {
  return PROFILES[id] || {
    id,
    title: connector?.name || id,
    subtitle: "Connector",
    type: "custom_api",
    logoFallback: id.slice(0, 2).toUpperCase(),
    logoBg: "#F8FAFC",
    logoColor: "#334155",
    cardDescription: connector?.promise || "Connect this source to AGRO-AI.",
    drawerTitle: `Connect ${connector?.name || id}`,
    drawerDescription: "Add this provider so AGRO-AI can use it as operational context.",
    primaryAction: "Connect",
    method: "custom_api",
    supportsUpload: Boolean(connector?.upload_supported),
    fields: [
      { key: "provider_name", label: "Provider name", placeholder: connector?.name || id },
      { key: "credential_ref", label: "Credential reference", placeholder: "API key or secure reference", secret: true },
    ],
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
  if (["ready", "synced", "test_passed", "upload_ready", "connected"].includes(status)) return "good";
  if (["coming_soon", "enterprise"].includes(status)) return "neutral";
  if (status.includes("missing") || status.includes("needs") || status.includes("not_configured") || status.includes("mapping")) return "warn";
  return "neutral";
}

function cleanStatus(status: string) {
  if (["test_passed", "ready", "connected"].includes(status)) return "connected";
  if (status === "synced") return "synced";
  if (status === "coming_soon") return "available";
  if (status === "needs_credentials") return "needs access";
  if (status === "not_configured") return "not connected";
  return status.replaceAll("_", " ");
}

export function Integrations() {
  const { currentOrganization, currentWorkspace } = useAuth();
  const catalogState = usePortalResource<AnyRecord>(useCallback(() => apiClient.connectorHub.catalog(), []));
  const connectionsState = usePortalResource<AnyRecord>(useCallback(() => apiClient.connectorHub.connections(), []));
  const [selected, setSelected] = useState<Connector | null>(null);
  const [connection, setConnection] = useState<AnyRecord | null>(null);
  const [config, setConfig] = useState<Record<string, string>>({});
  const [uploadResult, setUploadResult] = useState<AnyRecord | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [search, setSearch] = useState("");
  const [activeType, setActiveType] = useState<ConnectorType | "all">("all");

  const catalog = useMemo(() => asArray(catalogState.data?.connectors) as Connector[], [catalogState.data]);
  const connections = asArray(connectionsState.data?.connections);
  const plan = String(currentOrganization?.plan || "internal").toLowerCase();

  const cards = useMemo(() => {
    const byId = new Map(catalog.map((item) => [item.id, item]));
    Object.keys(PROFILES).forEach((id) => {
      if (!byId.has(id)) {
        byId.set(id, {
          id,
          name: PROFILES[id].title,
          category: TYPE_LABEL[PROFILES[id].type],
          status: "available",
          required_plan: "internal",
          connection_methods: [PROFILES[id].method],
          imports: [],
          used_by: [],
          promise: PROFILES[id].cardDescription,
          upload_supported: PROFILES[id].supportsUpload,
        });
      }
    });

    return Array.from(byId.values());
  }, [catalog]);

  const visibleCards = useMemo(() => {
    const q = search.trim().toLowerCase();

    return cards
      .filter((item) => activeType === "all" || profileFor(item.id, item).type === activeType)
      .filter((item) => {
        if (!q) return true;
        const profile = profileFor(item.id, item);
        return [
          profile.title,
          profile.subtitle,
          profile.cardDescription,
          profile.drawerDescription,
          item.name,
          item.category,
          ...(item.imports || []),
        ].join(" ").toLowerCase().includes(q);
      })
      .sort((a, b) => {
        const pa = profileFor(a.id, a);
        const pb = profileFor(b.id, b);
        return TYPE_ORDER.indexOf(pa.type) - TYPE_ORDER.indexOf(pb.type) || pa.title.localeCompare(pb.title);
      });
  }, [cards, search, activeType]);

  async function refresh() {
    await Promise.all([catalogState.refresh(), connectionsState.refresh()]);
  }

  async function startConnection(connector: Connector) {
    const profile = profileFor(connector.id, connector);
    const result = await apiClient.connectorHub.start({
      provider: connector.id as any,
      method: profile.method,
      workspace_id: currentWorkspace?.id,
      metadata: {
        surface: "simple_connector_hub",
        connector_type: profile.type,
      },
    }) as AnyRecord;

    return result.connection || connector.connection || null;
  }

  async function openConnector(connector: Connector) {
    const existing = connections.find((row) => row.provider === connector.id) || connector.connection || null;

    setSelected(connector);
    setConnection(existing);
    setUploadResult(null);
    setConfig({});
    setMessage("");
    setBusy(connector.id);

    try {
      const next = existing || await startConnection(connector);
      setConnection(next);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not open connector.");
    } finally {
      setBusy("");
    }
  }

  async function ensureConnection() {
    if (!selected) throw new Error("No connector selected.");
    if (connection?.id) return connection;
    const next = await startConnection(selected);
    setConnection(next);
    return next;
  }


  async function startOAuthConnector() {
    if (!selected) return;
    const profile = profileFor(selected.id, selected);
    setBusy("oauth");
    setMessage("");

    try {
      const activeConnection = await ensureConnection();
      const result = await apiClient.connectorHub.oauthStart({
        provider: selected.id,
        workspace_id: currentWorkspace?.id,
        redirect_url: `${window.location.origin}/integrations/oauth/callback`,
        metadata: {
          connector_type: profile.type,
          account_hint: config.account_email || "",
          scope_note: config.scope_note || config.folder_hint || "",
        },
      }) as AnyRecord;

      setConnection(result.connection || activeConnection);

      if (result.auth_url) {
        setMessage(`${profile.title} OAuth is ready. Redirecting to provider authorization.`);
        window.location.assign(result.auth_url);
      } else {
        setMessage(result.message || `${profile.title} OAuth is not configured yet.`);
      }

      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not start OAuth.");
    } finally {
      setBusy("");
    }
  }

  async function saveConnector(status = "test_passed") {
    if (!selected) return;

    const profile = profileFor(selected.id, selected);
    setBusy("save");
    setMessage("");

    if (profile.method === "oauth") {
      await startOAuthConnector();
      return;
    }

    try {
      const activeConnection = await ensureConnection();
      const credentialRef =
        config.credential_ref ||
        config.api_key ||
        config.account_email ||
        config.provider_name ||
        `${selected.id}_internal_connection`;

      const safeConfig: Record<string, string> = {};
      for (const [key, value] of Object.entries(config)) {
        if (/secret|token|password|api_key|credential|key/i.test(key)) {
          safeConfig[key] = value ? "submitted_to_backend_sanitizer" : "";
        } else {
          safeConfig[key] = value;
        }
      }

      const result = await apiClient.connectorHub.update(activeConnection.id, {
        status,
        credentials_ref: String(credentialRef),
        config: {
          ...safeConfig,
          connector_type: profile.type,
          provider_label: profile.title,
          internal_testing: true,
        },
      }) as AnyRecord;

      setConnection(result.connection || activeConnection);
      setMessage(`${profile.title} connected for internal testing.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save connector.");
    } finally {
      setBusy("");
    }
  }

  async function testConnector() {
    setBusy("test");
    setMessage("");

    try {
      const activeConnection = await ensureConnection();
      const result = await apiClient.connectorHub.test(activeConnection.id) as AnyRecord;
      setConnection(result.connection || activeConnection);
      setMessage(result.message || "Connector tested.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Connection test failed.");
    } finally {
      setBusy("");
    }
  }

  async function syncConnector() {
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
    const sample = profileFor(selected.id, selected).sampleFile;
    if (!sample) return;

    const file = new File([sample.body], sample.filename, { type: "text/csv" });
    await uploadFile(file);
  }

  const selectedProfile = selected ? profileFor(selected.id, selected) : null;
  const selectedStatus = cleanStatus(String(connection?.status || selected?.connection?.status || selected?.status || "not_configured"));

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <StatusBadge label="Integration Hub" tone="good" />
              <StatusBadge label={`${plan} testing`} />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Connectors</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Bring every customer system into one AGRO-AI hub: controllers, files, email, Drive, weather, ET, and existing data providers.
            </p>
          </div>
          <PortalButton variant="secondary" onClick={refresh}>Refresh</PortalButton>
        </div>
      </header>

      <main className="px-8 py-6 space-y-6" style={{ maxWidth: 1320 }}>
        {catalogState.error ? <InlineState title={catalogState.error} /> : null}
        {message ? <InlineState title={message} /> : null}

        <section className="grid grid-cols-4 gap-4">
          <Metric label="Connectors" value={String(cards.length)} />
          <Metric label="Connected" value={String(connections.filter((row) => ["ready", "test_passed", "synced"].includes(row.status)).length)} />
          <Metric label="Upload sources" value={String(cards.filter((item) => profileFor(item.id, item).supportsUpload).length)} />
          <Metric label="Hub status" value="Internal" />
        </section>

        <section className="rounded-2xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <button onClick={() => setActiveType("all")} className="rounded-full px-3 py-2 text-[12px]" style={pillStyle(activeType === "all")}>All</button>
            {TYPE_ORDER.map((type) => (
              <button key={type} onClick={() => setActiveType(type)} className="rounded-full px-3 py-2 text-[12px]" style={pillStyle(activeType === type)}>
                {TYPE_LABEL[type]}
              </button>
            ))}
          </div>

          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search WiseConn, Gmail, PDFs, weather, APIs..."
            className="h-11 w-full rounded-xl px-4 text-[13px] outline-none"
            style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}
          />
        </section>

        <section className="grid grid-cols-3 gap-4">
          {visibleCards.map((connector) => {
            const profile = profileFor(connector.id, connector);
            const live = connections.find((row) => row.provider === connector.id) || connector.connection;
            const status = cleanStatus(String(live?.status || connector.status || "not_configured"));

            return (
              <article
                key={connector.id}
                className="rounded-2xl p-5 flex flex-col min-h-[246px]"
                style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
              >
                <div className="flex items-start justify-between gap-3 mb-4">
                  <div className="flex items-center gap-3">
                    <ConnectorLogo profile={profile} />
                    <div>
                      <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>
                        {TYPE_LABEL[profile.type]}
                      </div>
                      <h3 className="text-[16px] font-semibold" style={{ color: TEXT }}>{profile.title}</h3>
                    </div>
                  </div>
                  <StatusBadge label={status} tone={statusTone(String(live?.status || connector.status || ""))} />
                </div>

                <p className="text-[12px] leading-relaxed mb-2" style={{ color: MUTED }}>{profile.subtitle}</p>
                <p className="text-[12px] leading-relaxed mb-4 flex-1" style={{ color: MUTED }}>{profile.cardDescription}</p>

                <div className="flex flex-wrap gap-1.5 mb-4">
                  <Chip>{TYPE_LABEL[profile.type]}</Chip>
                  {profile.supportsUpload ? <Chip>file upload</Chip> : null}
                  {profile.method === "oauth" ? <Chip>account connect</Chip> : null}
                  {profile.method === "api_credentials" ? <Chip>API access</Chip> : null}
                </div>

                <button
                  type="button"
                  onClick={() => openConnector({ ...connector, connection: live })}
                  className="h-10 rounded-lg text-[12px] font-semibold"
                  style={{ background: "#16533C", color: "white" }}
                >
                  {busy === connector.id ? "Opening..." : live ? "Manage connection" : "Connect"}
                </button>
              </article>
            );
          })}
        </section>
      </main>

      {selected && selectedProfile ? (
        <div className="fixed inset-0 z-50">
          <button className="absolute inset-0 bg-black/30" onClick={() => setSelected(null)} aria-label="Close connector setup" />

          <aside className="absolute right-0 top-0 h-full w-[700px] max-w-[96vw] overflow-y-auto shadow-2xl" style={{ background: SURFACE }}>
            <div className="px-6 py-5" style={{ borderBottom: `1px solid ${BORDER}` }}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-4">
                  <ConnectorLogo profile={selectedProfile} large />
                  <div>
                    <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>
                      {TYPE_LABEL[selectedProfile.type]}
                    </div>
                    <h2 className="text-[22px] font-semibold" style={{ color: TEXT }}>{selectedProfile.drawerTitle}</h2>
                    <p className="mt-2 text-[13px] leading-relaxed max-w-[500px]" style={{ color: MUTED }}>
                      {selectedProfile.drawerDescription}
                    </p>
                  </div>
                </div>
                <StatusBadge label={selectedStatus} tone={statusTone(String(connection?.status || ""))} />
              </div>
            </div>

            <div className="p-6 space-y-5">
              <Panel title="Simple setup">
                <ConnectorForm
                  profile={selectedProfile}
                  config={config}
                  setConfig={setConfig}
                  busy={busy}
                  onSave={() => saveConnector("test_passed")}
                  onTest={testConnector}
                />
              </Panel>

              {selectedProfile.supportsUpload ? (
                <Panel title={selectedProfile.type === "files" ? "Attach files" : "Optional file upload"}>
                  <UploadArea
                    label={selectedProfile.uploadLabel || "Upload file"}
                    onUpload={uploadFile}
                    onSample={selectedProfile.sampleFile ? uploadSample : undefined}
                    busy={busy}
                  />
                </Panel>
              ) : null}

              {selectedProfile.type === "account" ? (
                <Panel title="What AGRO-AI can do with this account">
                  <Capability text="Read approved operational context and attachments." />
                  <Capability text="Use emails and documents as evidence for portal analysis." />
                  <Capability text="Send generated reports only when the user asks." />
                  <Capability text="Keep all email behavior permission-based, not automatic spam." />
                </Panel>
              ) : null}

              {selectedProfile.type === "custom_api" ? (
                <Panel title="Existing systems this can cover">
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      "Ranch Systems",
                      "Telemetry APIs",
                      "Agency portals",
                      "ERP exports",
                      "SFTP drops",
                      "District databases",
                      "Farm management software",
                      "Custom webhooks",
                    ].map((item) => <Capability key={item} text={item} />)}
                  </div>
                </Panel>
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

              <Panel title="Connection state">
                <Info label="Provider" value={selectedProfile.title} />
                <Info label="Connection ID" value={pretty(connection?.id)} />
                <Info label="Mode" value={pretty(connection?.mode || selectedProfile.method)} />
                <Info label="Status" value={selectedStatus} />
                <Info label="Last sync" value={pretty(connection?.last_sync_at)} />
              </Panel>

              <Panel title="Next">
                <div className="grid grid-cols-3 gap-2">
                  <PortalButton variant="secondary" onClick={() => syncConnector()} disabled={busy === "sync"}>
                    {busy === "sync" ? "Syncing..." : "Sync"}
                  </PortalButton>
                  <PortalButton variant="secondary" onClick={() => window.location.assign("/evidence")}>Evidence</PortalButton>
                  <PortalButton variant="secondary" onClick={() => window.location.assign("/intelligence")}>Ask AGRO-AI</PortalButton>
                </div>
              </Panel>
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  );
}

function ConnectorForm({
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
    <div>
      {profile.fields.length ? (
        <div className="space-y-3">
          {profile.fields.map((field) => (
            <label key={field.key} className="block text-[12px]" style={{ color: MUTED }}>
              {field.label}
              <input
                value={config[field.key] || ""}
                type={field.secret ? "password" : field.type || "text"}
                placeholder={field.placeholder}
                onChange={(event) => setConfig({ ...config, [field.key]: event.target.value })}
                className="mt-1 h-10 w-full rounded-lg px-3 text-[13px] outline-none"
                style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: TEXT }}
              />
            </label>
          ))}
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        <PortalButton onClick={onSave} disabled={busy === "save"}>
          {busy === "save" || busy === "oauth" ? "Working..." : profile.primaryAction}
        </PortalButton>
        <PortalButton variant="secondary" onClick={onTest} disabled={busy === "test"}>
          {busy === "test" ? "Testing..." : "Test"}
        </PortalButton>
      </div>

      <p className="text-[12px] leading-relaxed mt-3" style={{ color: MUTED }}>
        Credentials should move to secure vault storage before production rollout. Internal mode stores only enough configuration to test the workflow.
      </p>
    </div>
  );
}

function UploadArea({
  label,
  onUpload,
  onSample,
  busy,
}: {
  label: string;
  onUpload: (file?: File) => void;
  onSample?: () => void;
  busy: string;
}) {
  return (
    <div>
      <label className="block rounded-2xl p-5 cursor-pointer" style={{ background: SURFACE, border: `1px dashed ${BORDER}` }}>
        <div className="text-[15px] font-semibold mb-1" style={{ color: TEXT }}>{label}</div>
        <div className="text-[12px] leading-relaxed mb-4" style={{ color: MUTED }}>
          Attach CSV, JSON, TXT, or PDF files. AGRO-AI will parse, store, and cite what it can use.
        </div>
        <input
          type="file"
          accept=".csv,.json,.txt,.pdf"
          onChange={(event) => onUpload(event.target.files?.[0])}
          className="text-[12px]"
          style={{ color: TEXT }}
        />
      </label>

      <div className="mt-3 flex gap-2">
        {onSample ? (
          <PortalButton variant="secondary" onClick={onSample} disabled={busy === "upload"}>
            {busy === "upload" ? "Uploading..." : "Use sample file"}
          </PortalButton>
        ) : null}
      </div>
    </div>
  );
}

function Capability({ text }: { text: string }) {
  return (
    <div className="rounded-lg px-3 py-2 text-[12px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: MUTED }}>
      {text}
    </div>
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
  const size = large ? 56 : 42;
  const imgSrc = profile.logoAsset || profile.logoUrl;

  return (
    <div
      className="rounded-xl flex items-center justify-center font-bold shadow-sm overflow-hidden"
      style={{
        width: size,
        height: size,
        minWidth: size,
        background: profile.logoBg,
        color: profile.logoColor,
        border: `1px solid ${BORDER}`,
      }}
      aria-label={`${profile.title} logo`}
    >
      {imgSrc ? (
        <img
          src={imgSrc}
          alt=""
          className="h-[62%] w-[62%] object-contain"
          onError={(event) => {
            event.currentTarget.style.display = "none";
            const next = event.currentTarget.nextElementSibling as HTMLElement | null;
            if (next) next.style.display = "inline";
          }}
        />
      ) : null}
      <span style={{ display: imgSrc ? "none" : "inline", fontSize: large ? 16 : 13, letterSpacing: "-0.02em" }}>
        {profile.logoFallback}
      </span>
    </div>
  );
}

function pillStyle(active: boolean) {
  return active
    ? { background: "#0D2B1E", color: "white", border: "1px solid #0D2B1E" }
    : { background: BG, color: MUTED, border: `1px solid ${BORDER}` };
}
