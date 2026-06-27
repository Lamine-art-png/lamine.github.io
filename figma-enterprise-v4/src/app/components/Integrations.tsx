import { useCallback, useMemo, useState } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";
import talgilLogo from "../../imports/talgil-logo-hq.png";
import wiseconnLogo from "../../imports/wiseconn-logo-hq.png";

type AnyRecord = Record<string, any>;
type ConnectorType = "controller" | "files" | "account" | "data_provider" | "custom_api";

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

type ConnectorField = { key: string; label: string; placeholder: string; secret?: boolean; type?: string };

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
  method: "oauth" | "api_credentials" | "manual_upload" | "custom_api";
  authPattern: "oauth" | "provider_api" | "manual_upload" | "enterprise_api" | "service_account";
  fields: ConnectorField[];
  permissions: string[];
  dataObjects: string[];
  launchSteps: string[];
  supportsUpload: boolean;
  uploadLabel?: string;
  sampleFile?: { filename: string; body: string };
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
    cardDescription: "Authorize a WiseConn environment or upload controller exports for immediate evidence ingestion.",
    drawerTitle: "Connect WiseConn",
    drawerDescription: "Customers should feel like they are granting AGRO-AI access to an existing WiseConn environment, not configuring a science project.",
    primaryAction: "Request WiseConn access",
    method: "api_credentials",
    authPattern: "provider_api",
    supportsUpload: true,
    uploadLabel: "Upload WiseConn export",
    permissions: ["Read zones and controller events", "Read flow, runtime, and valve history", "Normalize irrigation logs into evidence"],
    dataObjects: ["zones", "controller events", "flow readings", "irrigation history", "valve state"],
    launchSteps: ["Customer identifies WiseConn environment", "AGRO-AI stores a secure credential reference", "Scheduled sync imports controller evidence", "Reports and decisions cite the imported source"],
    fields: [
      { key: "environment_name", label: "Environment name", placeholder: "North Ranch WiseConn" },
      { key: "environment_url", label: "WiseConn URL / environment", placeholder: "https://..." },
      { key: "account_hint", label: "Owner / operator email", placeholder: "operations@farm.com", type: "email" },
      { key: "field_scope", label: "Fields / ranches to authorize", placeholder: "North Ranch, Block A-B, almonds" },
      { key: "credential_ref", label: "Credential reference", placeholder: "API key or secure vault reference", secret: true },
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
    cardDescription: "Authorize Talgil controller programs, zones, valve events, flow readings, and irrigation logs.",
    drawerTitle: "Connect Talgil",
    drawerDescription: "A clean access flow for Talgil controller context: environment, scope, credential reference, sync trail.",
    primaryAction: "Request Talgil access",
    method: "api_credentials",
    authPattern: "provider_api",
    supportsUpload: true,
    uploadLabel: "Upload Talgil export",
    permissions: ["Read programs, valves, zones, and flow events", "Read controller state and irrigation history", "Normalize controller records into evidence"],
    dataObjects: ["programs", "zones", "valve state", "flow readings", "irrigation events"],
    launchSteps: ["Customer authorizes Talgil environment", "Credential reference is stored", "Sync job imports controller records", "Evidence is available to Ask AGRO-AI and reports"],
    fields: [
      { key: "environment_name", label: "Environment name", placeholder: "South Ranch Talgil" },
      { key: "environment_url", label: "Talgil URL / environment", placeholder: "https://..." },
      { key: "account_hint", label: "Owner / operator email", placeholder: "operator@farm.com", type: "email" },
      { key: "field_scope", label: "Fields / zones to authorize", placeholder: "Zone 12-14, pistachios" },
      { key: "credential_ref", label: "Credential reference", placeholder: "API key or secure vault reference", secret: true },
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
    cardDescription: "Attach CSV, PDF, spreadsheet exports, field logs, compliance documents, and messy customer files.",
    drawerTitle: "Upload files",
    drawerDescription: "File upload is the immediate bridge while live integrations are being authorized.",
    primaryAction: "Upload files",
    method: "manual_upload",
    authPattern: "manual_upload",
    supportsUpload: true,
    uploadLabel: "Upload CSV, JSON, TXT, or PDF",
    permissions: ["Store uploaded source", "Parse rows and text", "Create citation-ready evidence"],
    dataObjects: ["CSV rows", "PDF text", "operator notes", "field logs"],
    launchSteps: ["Attach file", "Parse and map fields", "Create evidence records", "Use evidence in intelligence work"],
    fields: [{ key: "source_label", label: "Source label", placeholder: "June irrigation records" }],
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
    cardDescription: "Authorize Gmail so AGRO-AI can use approved field context, attachments, and reports.",
    drawerTitle: "Authorize Gmail",
    drawerDescription: "The launch path is a consent screen: customer grants access, AGRO-AI reads approved operational context, and all evidence stays cited.",
    primaryAction: "Continue with Google",
    method: "oauth",
    authPattern: "oauth",
    supportsUpload: false,
    permissions: ["View approved operational emails", "Read relevant attachments and reports", "Prepare report drafts when requested"],
    dataObjects: ["messages", "threads", "attachments", "sender context", "timestamps"],
    launchSteps: ["Customer clicks Continue with Google", "Provider consent screen opens", "AGRO-AI receives callback", "Server exchanges code and stores provider token reference"],
    fields: [
      { key: "account_hint", label: "Gmail account", placeholder: "operations@farm.com", type: "email" },
      { key: "field_scope", label: "Context to use", placeholder: "Irrigation reports, water agency emails, field attachments" },
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
    cardDescription: "Authorize Outlook for operational emails, attachments, and report delivery.",
    drawerTitle: "Authorize Outlook",
    drawerDescription: "A Microsoft consent flow for approved customer email context and attachments.",
    primaryAction: "Continue with Microsoft",
    method: "oauth",
    authPattern: "oauth",
    supportsUpload: false,
    permissions: ["View approved operational emails", "Read attachments and reports", "Prepare report drafts when requested"],
    dataObjects: ["messages", "attachments", "mail folders", "sender context"],
    launchSteps: ["Customer clicks Continue with Microsoft", "Consent screen opens", "AGRO-AI receives callback", "Server stores provider token reference"],
    fields: [
      { key: "account_hint", label: "Outlook account", placeholder: "operations@farm.com", type: "email" },
      { key: "field_scope", label: "Context to use", placeholder: "Reports, attachments, grower communications" },
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
    cardDescription: "Authorize Drive folders containing PDFs, spreadsheets, water reports, maps, and field records.",
    drawerTitle: "Authorize Google Drive",
    drawerDescription: "Drive should feel like selecting a trusted context source, not uploading one file at a time.",
    primaryAction: "Continue with Google",
    method: "oauth",
    authPattern: "oauth",
    supportsUpload: false,
    permissions: ["View approved folders and files", "Read PDFs, spreadsheets, maps, and reports", "Create citation-ready document evidence"],
    dataObjects: ["folders", "documents", "spreadsheets", "PDFs", "file metadata"],
    launchSteps: ["Customer clicks Continue with Google", "Consent screen opens", "Folder context is selected", "Documents are indexed as evidence"],
    fields: [{ key: "field_scope", label: "Folder or context hint", placeholder: "Water reports / irrigation exports / compliance docs" }],
  },
  dropbox: {
    id: "dropbox",
    title: "Dropbox",
    subtitle: "Files + folders",
    type: "account",
    logoUrl: "https://www.google.com/s2/favicons?domain=dropbox.com&sz=128",
    logoFallback: "Db",
    logoBg: "#EFF6FF",
    logoColor: "#0061FF",
    cardDescription: "Authorize Dropbox folders containing field evidence, PDFs, spreadsheets, and grower records.",
    drawerTitle: "Authorize Dropbox",
    drawerDescription: "A Dropbox consent flow for approved customer folders and files. AGRO-AI stores cited file context, not raw secrets.",
    primaryAction: "Continue with Dropbox",
    method: "oauth",
    authPattern: "oauth",
    supportsUpload: false,
    permissions: ["View approved Dropbox folders", "Read selected files and metadata", "Create citation-ready document evidence"],
    dataObjects: ["folders", "files", "PDFs", "spreadsheets", "file metadata"],
    launchSteps: ["Customer clicks Continue with Dropbox", "Dropbox consent screen opens", "AGRO-AI receives callback", "Server exchanges code and stores provider token reference"],
    fields: [{ key: "field_scope", label: "Folder or context hint", placeholder: "Irrigation exports / assurance evidence / field reports" }],
  },
  box: {
    id: "box",
    title: "Box",
    subtitle: "Enterprise files",
    type: "account",
    logoUrl: "https://www.google.com/s2/favicons?domain=box.com&sz=128",
    logoFallback: "Bx",
    logoBg: "#EFF6FF",
    logoColor: "#0061D5",
    cardDescription: "Authorize Box folders for enterprise documents, audit packets, PDFs, and spreadsheets.",
    drawerTitle: "Authorize Box",
    drawerDescription: "Box follows the same consent-first pattern: approved folders become cited evidence, and token exchange stays server-side.",
    primaryAction: "Continue with Box",
    method: "oauth",
    authPattern: "oauth",
    supportsUpload: false,
    permissions: ["View approved Box folders", "Read selected documents and metadata", "Create citation-ready enterprise file evidence"],
    dataObjects: ["folders", "files", "PDFs", "spreadsheets", "enterprise metadata"],
    launchSteps: ["Customer clicks Continue with Box", "Box consent screen opens", "AGRO-AI receives callback", "Server exchanges code and stores provider token reference"],
    fields: [{ key: "field_scope", label: "Folder or context hint", placeholder: "Audit packets / water reports / customer evidence" }],
  },
  slack: {
    id: "slack",
    title: "Slack",
    subtitle: "Operations context",
    type: "account",
    logoUrl: "https://www.google.com/s2/favicons?domain=slack.com&sz=128",
    logoFallback: "S",
    logoBg: "#FDF2F8",
    logoColor: "#611F69",
    cardDescription: "Authorize Slack for approved operations-channel context, files, and field handoffs.",
    drawerTitle: "Authorize Slack",
    drawerDescription: "Slack context is labeled as operational evidence and should never be shown as connected until provider consent succeeds.",
    primaryAction: "Continue with Slack",
    method: "oauth",
    authPattern: "oauth",
    supportsUpload: false,
    permissions: ["View approved channel metadata", "Read selected files and operational messages", "Create cited handoff context"],
    dataObjects: ["channels", "messages", "files", "operator handoffs"],
    launchSteps: ["Customer clicks Continue with Slack", "Slack consent screen opens", "AGRO-AI receives callback", "Server exchanges code and stores provider token reference"],
    fields: [{ key: "field_scope", label: "Channel / context hint", placeholder: "#field-ops, irrigation handoffs, files" }],
  },
  salesforce: {
    id: "salesforce",
    title: "Salesforce",
    subtitle: "Customer operations",
    type: "account",
    logoUrl: "https://www.google.com/s2/favicons?domain=salesforce.com&sz=128",
    logoFallback: "SF",
    logoBg: "#EFF6FF",
    logoColor: "#0B5CAB",
    cardDescription: "Authorize Salesforce customer context for accounts, cases, and enterprise assurance workflows.",
    drawerTitle: "Authorize Salesforce",
    drawerDescription: "Salesforce context supports customer-success and assurance workflows after provider consent and server-side token exchange.",
    primaryAction: "Continue with Salesforce",
    method: "oauth",
    authPattern: "oauth",
    supportsUpload: false,
    permissions: ["Read approved account context", "Read cases and customer notes", "Use context in reports and assurance workflows"],
    dataObjects: ["accounts", "contacts", "cases", "opportunities", "customer notes"],
    launchSteps: ["Customer clicks Continue with Salesforce", "Salesforce consent screen opens", "AGRO-AI receives callback", "Server exchanges code and stores provider token reference"],
    fields: [{ key: "account_hint", label: "Salesforce user / org hint", placeholder: "customer-success@company.com", type: "email" }],
  },
  google_earth_engine: {
    id: "google_earth_engine",
    title: "Google Earth Engine",
    subtitle: "Geospatial project",
    type: "data_provider",
    logoUrl: "https://www.google.com/s2/favicons?domain=earthengine.google.com&sz=128",
    logoFallback: "GEE",
    logoBg: "#ECFDF5",
    logoColor: "#047857",
    cardDescription: "Verify Earth Engine project and service-account readiness for remote-sensing context.",
    drawerTitle: "Verify Google Earth Engine",
    drawerDescription: "Earth Engine uses project/service-account configuration, not customer OAuth consent. The portal reports readiness without exposing env values.",
    primaryAction: "Verify service account",
    method: "api_credentials",
    authPattern: "service_account",
    supportsUpload: false,
    permissions: ["Use configured Earth Engine project", "Read approved geospatial assets", "Bring remote-sensing context into reports"],
    dataObjects: ["project assets", "imagery layers", "ET/geospatial context", "field boundary references"],
    launchSteps: ["Platform sets project ID", "Platform sets service-account JSON", "Backend verifies env readiness", "Geospatial context can be cited in intelligence outputs"],
    fields: [{ key: "field_scope", label: "Project / asset scope note", placeholder: "Earth Engine project, field assets, geospatial layers" }],
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
    drawerDescription: "Weather can come from API credentials, station feeds, or exports. AGRO-AI uses it for timing and risk.",
    primaryAction: "Connect weather provider",
    method: "api_credentials",
    authPattern: "provider_api",
    supportsUpload: true,
    uploadLabel: "Upload weather file",
    permissions: ["Read weather stations and forecasts", "Use rainfall, temperature, humidity, and forecast context", "Bring weather risk into decisions"],
    dataObjects: ["forecast", "station data", "rainfall", "temperature", "humidity"],
    launchSteps: ["Customer selects provider", "AGRO-AI stores provider access reference", "Weather context syncs or imports", "Decisions use weather risk"],
    fields: [
      { key: "provider_name", label: "Provider", placeholder: "NOAA, Tomorrow.io, OpenWeather, local station" },
      { key: "environment_url", label: "Provider URL / station", placeholder: "Station ID, coordinates, or API URL" },
      { key: "field_scope", label: "Fields / locations", placeholder: "North Ranch coordinates or station area" },
      { key: "credential_ref", label: "Credential reference", placeholder: "API key or secure reference", secret: true },
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
    drawerDescription: "OpenET should become a field-level water context source with boundary scope, provider access, and cited outputs.",
    primaryAction: "Connect OpenET access",
    method: "api_credentials",
    authPattern: "provider_api",
    supportsUpload: true,
    uploadLabel: "Upload ET file",
    permissions: ["Read ET and ET0 for approved fields", "Use field boundary references", "Bring ET context into decisions and reports"],
    dataObjects: ["ET", "ET0", "field boundary references", "water-use estimates"],
    launchSteps: ["Customer identifies field boundary scope", "AGRO-AI stores provider access reference", "ET data imports by field", "Reports cite ET context"],
    fields: [
      { key: "provider_name", label: "Provider", placeholder: "OpenET or ET provider" },
      { key: "field_scope", label: "Field boundary / parcel reference", placeholder: "Parcel ID, field ID, or geometry reference" },
      { key: "credential_ref", label: "Credential reference", placeholder: "API key or secure reference", secret: true },
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
    cardDescription: "Connect existing farm, agency, ERP, telemetry, or water accounting systems.",
    drawerTitle: "Connect existing data provider",
    drawerDescription: "A launch-ready access request for any customer system we do not have a native connector for yet.",
    primaryAction: "Create data access request",
    method: "custom_api",
    authPattern: "enterprise_api",
    supportsUpload: false,
    permissions: ["Read approved provider endpoints or exports", "Normalize vendor data into evidence", "Keep every import auditable"],
    dataObjects: ["vendor API records", "SFTP drops", "district records", "ERP exports", "telemetry"],
    launchSteps: ["Define provider and access method", "Store credential reference", "Map endpoint/export contract", "Create scheduled import job"],
    fields: [
      { key: "provider_name", label: "Provider name", placeholder: "Ranch Systems, district portal, ERP, telemetry vendor" },
      { key: "environment_url", label: "Provider URL", placeholder: "https://api.provider.com or portal URL" },
      { key: "auth_type", label: "Access method", placeholder: "API key, OAuth, SFTP, webhook, database, manual export" },
      { key: "credential_ref", label: "Credential reference", placeholder: "API key or secure reference", secret: true },
    ],
  },
};

const TYPE_ORDER: ConnectorType[] = ["controller", "files", "account", "data_provider", "custom_api"];
const TYPE_LABEL: Record<ConnectorType, string> = { controller: "Controllers", files: "Files", account: "Accounts", data_provider: "Data providers", custom_api: "Custom APIs" };

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
    primaryAction: "Create data access request",
    method: "custom_api",
    authPattern: "enterprise_api",
    supportsUpload: Boolean(connector?.upload_supported),
    permissions: ["Read approved provider data", "Normalize records into evidence", "Cite the source in reports"],
    dataObjects: connector?.imports || [],
    launchSteps: ["Define access", "Store credential reference", "Map records", "Import evidence"],
    fields: [
      { key: "provider_name", label: "Provider name", placeholder: connector?.name || id },
      { key: "credential_ref", label: "Credential reference", placeholder: "API key or secure reference", secret: true },
    ],
  };
}

function asArray(value: unknown): AnyRecord[] { return Array.isArray(value) ? (value as AnyRecord[]) : []; }
function pretty(value: unknown, fallback = "—") { if (value === null || value === undefined || value === "") return fallback; if (["string", "number", "boolean"].includes(typeof value)) return String(value); try { return JSON.stringify(value); } catch { return fallback; } }
function statusTone(status: string): "neutral" | "good" | "warn" | "locked" { if (["ready", "synced", "test_passed", "upload_ready", "connected", "oauth_ready", "provider_access_ready", "access_requested"].includes(status)) return "good"; if (status.includes("missing") || status.includes("needs") || status.includes("not_configured") || status.includes("mapping") || status.includes("setup")) return "warn"; return "neutral"; }
function cleanStatus(status: string) { if (["test_passed", "ready", "connected"].includes(status)) return "connected"; if (status === "synced") return "synced"; if (status === "oauth_ready") return "ready to authorize"; if (status === "provider_access_ready") return "provider ready"; if (status === "access_requested") return "access requested"; if (status === "platform_setup_required") return "platform setup"; if (status === "coming_soon") return "available"; if (status === "needs_credentials") return "needs access"; if (status === "not_configured") return "not connected"; return status.replaceAll("_", " "); }

export function Integrations() {
  const { currentOrganization, currentWorkspace } = useAuth();
  const catalogState = usePortalResource<AnyRecord>(useCallback(() => apiClient.connectorHub.catalog(), []));
  const connectionsState = usePortalResource<AnyRecord>(useCallback(() => apiClient.connectorHub.connections(), []));
  const [selected, setSelected] = useState<Connector | null>(null);
  const [connection, setConnection] = useState<AnyRecord | null>(null);
  const [config, setConfig] = useState<Record<string, string>>({});
  const [uploadResult, setUploadResult] = useState<AnyRecord | null>(null);
  const [launchResult, setLaunchResult] = useState<AnyRecord | null>(null);
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
      if (!byId.has(id)) byId.set(id, { id, name: PROFILES[id].title, category: TYPE_LABEL[PROFILES[id].type], status: "available", required_plan: "internal", connection_methods: [PROFILES[id].method], imports: [], used_by: [], promise: PROFILES[id].cardDescription, upload_supported: PROFILES[id].supportsUpload });
    });
    return Array.from(byId.values());
  }, [catalog]);

  const visibleCards = useMemo(() => {
    const q = search.trim().toLowerCase();
    return cards.filter((item) => activeType === "all" || profileFor(item.id, item).type === activeType).filter((item) => {
      if (!q) return true;
      const profile = profileFor(item.id, item);
      return [profile.title, profile.subtitle, profile.cardDescription, profile.drawerDescription, item.name, item.category, ...(item.imports || [])].join(" ").toLowerCase().includes(q);
    }).sort((a, b) => TYPE_ORDER.indexOf(profileFor(a.id, a).type) - TYPE_ORDER.indexOf(profileFor(b.id, b).type) || profileFor(a.id, a).title.localeCompare(profileFor(b.id, b).title));
  }, [cards, search, activeType]);

  async function refresh() { await Promise.all([catalogState.refresh(), connectionsState.refresh()]); }

  async function startConnection(connector: Connector) {
    const profile = profileFor(connector.id, connector);
    const result = await apiClient.connectorHub.start({ provider: connector.id as any, method: profile.method, workspace_id: currentWorkspace?.id, metadata: { surface: "connector_hub", connector_type: profile.type } }) as AnyRecord;
    return result.connection || connector.connection || null;
  }

  async function openConnector(connector: Connector) {
    const existing = connections.find((row) => row.provider === connector.id) || connector.connection || null;
    setSelected(connector); setConnection(existing); setUploadResult(null); setLaunchResult(null); setConfig({}); setMessage(""); setBusy(connector.id);
    try { const next = existing || await startConnection(connector); setConnection(next); await refresh(); } catch (error) { setMessage(error instanceof Error ? error.message : "Could not open connector."); } finally { setBusy(""); }
  }

  async function launchAuthorization() {
    if (!selected) return;
    const profile = profileFor(selected.id, selected);
    setBusy("launch"); setMessage(""); setLaunchResult(null);
    try {
      const payload = { provider: selected.id, workspace_id: currentWorkspace?.id, redirect_url: "https://api.agroai-pilot.com/v1/connectors/oauth/callback", account_hint: config.account_hint || config.account_email || "", field_scope: config.field_scope || config.scope_note || config.folder_hint || "", access_note: config.access_note || "", metadata: { connector_type: profile.type, provider_label: profile.title, environment_url: config.environment_url || config.account_url || "" } };
      const result = await apiClient.post("/v1/connectors/launch/start", payload) as AnyRecord;
      setLaunchResult(result); setConnection(result.connection || connection);
      if (result.auth_url) { setMessage(`${profile.title} authorization is ready. Redirecting to provider consent.`); window.location.assign(result.auth_url); }
      else { setMessage(result.message || `${profile.title} launch path recorded. Platform/provider access is the next setup step.`); }
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Launch authorization failed."); } finally { setBusy(""); }
  }

  async function saveConnector() {
    if (!selected) return;
    const profile = profileFor(selected.id, selected);
    if (profile.authPattern === "oauth" || profile.authPattern === "service_account") { await launchAuthorization(); return; }
    if (profile.authPattern === "manual_upload") { setMessage("Use the upload area below to attach evidence files."); return; }
    setBusy("save"); setMessage(""); setLaunchResult(null);
    try {
      const result = await apiClient.post("/v1/connectors/launch/access-request", { provider: selected.id, workspace_id: currentWorkspace?.id, display_name: profile.title, account_hint: config.account_hint || config.username || "", environment_url: config.environment_url || config.account_url || config.base_url || "", field_scope: config.field_scope || "", credential_ref: config.credential_ref || "", metadata: { ...config, connector_type: profile.type, provider_label: profile.title } }) as AnyRecord;
      setLaunchResult(result); setConnection(result.connection || null); setMessage(`${profile.title} access request is recorded. Use sample/upload now, then add production credentials when ready.`); await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not create provider access request."); } finally { setBusy(""); }
  }

  async function uploadFile(file?: File) {
    if (!file || !selected) return;
    setBusy("upload"); setMessage(""); setUploadResult(null);
    try { const result = await apiClient.evidence.upload(file, selected.id, currentWorkspace?.id) as AnyRecord; setUploadResult(result); setConnection(result.connection || connection); setMessage(`Imported ${pretty(result.evidence_records_created, "0")} evidence records from ${file.name}.`); await refresh(); } catch (error) { setMessage(error instanceof Error ? error.message : "Upload failed."); } finally { setBusy(""); }
  }

  async function uploadSample() { if (!selected) return; const sample = profileFor(selected.id, selected).sampleFile; if (!sample) return; await uploadFile(new File([sample.body], sample.filename, { type: "text/csv" })); }

  const selectedProfile = selected ? profileFor(selected.id, selected) : null;
  const selectedStatus = cleanStatus(String(connection?.status || selected?.connection?.status || selected?.status || "not_configured"));

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-3"><StatusBadge label="Integration Hub" tone="good" /><StatusBadge label={`${plan} testing`} /></div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Connectors</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>Bring every customer system into one AGRO-AI hub: controllers, files, email, Drive, weather, ET, and existing data providers.</p>
          </div>
          <PortalButton variant="secondary" onClick={refresh}>Refresh</PortalButton>
        </div>
      </header>

      <main className="px-8 py-6 space-y-6" style={{ maxWidth: 1320 }}>
        {catalogState.error ? <InlineState title={catalogState.error} /> : null}
        {message ? <InlineState title={message} /> : null}
        <section className="grid grid-cols-4 gap-4"><Metric label="Connectors" value={String(cards.length)} /><Metric label="Active sources" value={String(connections.length)} /><Metric label="Upload sources" value={String(cards.filter((item) => profileFor(item.id, item).supportsUpload).length)} /><Metric label="Launch path" value="Embedded" /></section>
        <section className="rounded-2xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex flex-wrap items-center gap-2 mb-4"><button onClick={() => setActiveType("all")} className="rounded-full px-3 py-2 text-[12px]" style={pillStyle(activeType === "all")}>All</button>{TYPE_ORDER.map((type) => <button key={type} onClick={() => setActiveType(type)} className="rounded-full px-3 py-2 text-[12px]" style={pillStyle(activeType === type)}>{TYPE_LABEL[type]}</button>)}</div>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search WiseConn, Gmail, OpenET, APIs..." className="h-11 w-full rounded-xl px-4 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
        </section>
        <section className="grid grid-cols-3 gap-4">
          {visibleCards.map((connector) => {
            const profile = profileFor(connector.id, connector); const live = connections.find((row) => row.provider === connector.id) || connector.connection; const status = cleanStatus(String(live?.status || connector.status || "not_configured"));
            return <article key={connector.id} className="rounded-2xl p-5 flex flex-col min-h-[258px]" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              <div className="flex items-start justify-between gap-3 mb-4"><div className="flex items-center gap-3"><ConnectorLogo profile={profile} /><div><div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>{TYPE_LABEL[profile.type]}</div><h3 className="text-[16px] font-semibold" style={{ color: TEXT }}>{profile.title}</h3></div></div><StatusBadge label={status} tone={statusTone(String(live?.status || connector.status || ""))} /></div>
              <p className="text-[12px] leading-relaxed mb-2" style={{ color: MUTED }}>{profile.subtitle}</p><p className="text-[12px] leading-relaxed mb-4 flex-1" style={{ color: MUTED }}>{profile.cardDescription}</p>
              <div className="flex flex-wrap gap-1.5 mb-4"><Chip>{TYPE_LABEL[profile.type]}</Chip><Chip>{profile.authPattern === "oauth" ? "OAuth consent" : profile.authPattern === "service_account" ? "service account" : profile.authPattern === "manual_upload" ? "file upload" : "provider access"}</Chip>{profile.supportsUpload ? <Chip>upload now</Chip> : null}</div>
              <button type="button" onClick={() => openConnector({ ...connector, connection: live })} className="h-10 rounded-lg text-[12px] font-semibold" style={{ background: "#16533C", color: "white" }}>{busy === connector.id ? "Opening..." : live ? "Manage connection" : "Connect"}</button>
            </article>;
          })}
        </section>
      </main>

      {selected && selectedProfile ? <div className="fixed inset-0 z-50"><button className="absolute inset-0 bg-black/30" onClick={() => setSelected(null)} aria-label="Close connector setup" />
        <aside className="absolute right-0 top-0 h-full w-[740px] max-w-[96vw] overflow-y-auto shadow-2xl" style={{ background: SURFACE }}>
          <div className="px-6 py-5" style={{ borderBottom: `1px solid ${BORDER}` }}><div className="flex items-start justify-between gap-4"><div className="flex items-center gap-4"><ConnectorLogo profile={selectedProfile} large /><div><div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>{TYPE_LABEL[selectedProfile.type]}</div><h2 className="text-[22px] font-semibold" style={{ color: TEXT }}>{selectedProfile.drawerTitle}</h2><p className="mt-2 text-[13px] leading-relaxed max-w-[520px]" style={{ color: MUTED }}>{selectedProfile.drawerDescription}</p></div></div><StatusBadge label={selectedStatus} tone={statusTone(String(connection?.status || ""))} /></div></div>
          <div className="p-6 space-y-5">
            <Panel title="Launch-grade authorization path"><LaunchPath profile={selectedProfile} /></Panel>
            <Panel title="Customer access setup"><ConnectorForm profile={selectedProfile} config={config} setConfig={setConfig} busy={busy} onSave={saveConnector} /></Panel>
            {selectedProfile.supportsUpload ? <Panel title={selectedProfile.type === "files" ? "Attach files" : "Bridge with file export while access is approved"}><UploadArea label={selectedProfile.uploadLabel || "Upload file"} onUpload={uploadFile} onSample={selectedProfile.sampleFile ? uploadSample : undefined} busy={busy} /></Panel> : null}
            {launchResult ? <Panel title="Authorization result"><Info label="Status" value={pretty(launchResult.status)} /><Info label="Provider" value={pretty(launchResult.manifest?.label || selectedProfile.title)} /><Info label="Next step" value={pretty(launchResult.manifest?.production_next || launchResult.message)} /></Panel> : null}
            {uploadResult ? <Panel title="Latest import"><Info label="Rows parsed" value={pretty(uploadResult.rows_parsed)} /><Info label="Evidence records" value={pretty(uploadResult.evidence_records_created)} /><Info label="Warnings" value={(uploadResult.warnings || []).join("; ") || "None"} /><div className="mt-3 flex flex-wrap gap-2">{Object.entries(uploadResult.mapping_suggestions || {}).slice(0, 14).map(([source, target]) => <Chip key={source}>{source} → {String(target)}</Chip>)}</div></Panel> : null}
            <Panel title="Connection state"><Info label="Provider" value={selectedProfile.title} /><Info label="Connection ID" value={pretty(connection?.id)} /><Info label="Mode" value={pretty(connection?.mode || selectedProfile.method)} /><Info label="Status" value={selectedStatus} /><Info label="Last sync" value={pretty(connection?.last_sync_at)} /></Panel>
            <Panel title="Next"><div className="grid grid-cols-3 gap-2"><PortalButton variant="secondary" onClick={() => window.location.assign("/sources")}>Sources</PortalButton><PortalButton variant="secondary" onClick={() => window.location.assign("/evidence")}>Evidence</PortalButton><PortalButton variant="secondary" onClick={() => window.location.assign("/intelligence")}>Ask AGRO-AI</PortalButton></div></Panel>
          </div>
        </aside>
      </div> : null}
    </div>
  );
}

function LaunchPath({ profile }: { profile: ConnectorProfile }) { return <div className="space-y-4"><div className="grid grid-cols-2 gap-3"><div><div className="text-[10px] uppercase tracking-widest font-semibold mb-2" style={{ color: MUTED }}>Customer permissions</div><div className="space-y-2">{profile.permissions.map((item) => <Capability key={item} text={item} />)}</div></div><div><div className="text-[10px] uppercase tracking-widest font-semibold mb-2" style={{ color: MUTED }}>Data AGRO-AI can use</div><div className="space-y-2">{profile.dataObjects.map((item) => <Capability key={item} text={item} />)}</div></div></div><div className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="text-[10px] uppercase tracking-widest font-semibold mb-2" style={{ color: MUTED }}>Flow embedded for launch</div><ol className="space-y-1 text-[12px]" style={{ color: MUTED }}>{profile.launchSteps.map((step, index) => <li key={step}>{index + 1}. {step}</li>)}</ol></div></div>; }

function ConnectorForm({ profile, config, setConfig, busy, onSave }: { profile: ConnectorProfile; config: Record<string, string>; setConfig: (next: Record<string, string>) => void; busy: string; onSave: () => void }) { return <div>{profile.fields.length ? <div className="space-y-3">{profile.fields.map((field) => <label key={field.key} className="block text-[12px]" style={{ color: MUTED }}>{field.label}<input value={config[field.key] || ""} type={field.secret ? "password" : field.type || "text"} placeholder={field.placeholder} onChange={(event) => setConfig({ ...config, [field.key]: event.target.value })} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px] outline-none" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: TEXT }} /></label>)}</div> : null}<div className="mt-4 flex flex-wrap gap-2"><PortalButton onClick={onSave} disabled={busy === "save" || busy === "launch"}>{busy === "save" || busy === "launch" ? "Working..." : profile.primaryAction}</PortalButton></div><p className="text-[12px] leading-relaxed mt-3" style={{ color: MUTED }}>AGRO-AI stores a credential reference and an auditable connection record. Provider token exchange and live sync activate when provider credentials are configured in production.</p></div>; }
function UploadArea({ label, onUpload, onSample, busy }: { label: string; onUpload: (file?: File) => void; onSample?: () => void; busy: string }) { return <div><label className="block rounded-2xl p-5 cursor-pointer" style={{ background: SURFACE, border: `1px dashed ${BORDER}` }}><div className="text-[15px] font-semibold mb-1" style={{ color: TEXT }}>{label}</div><div className="text-[12px] leading-relaxed mb-4" style={{ color: MUTED }}>Attach CSV, JSON, TXT, or PDF files. AGRO-AI will parse, store, and cite what it can use.</div><input type="file" accept=".csv,.json,.txt,.pdf" onChange={(event) => onUpload(event.target.files?.[0])} className="text-[12px]" style={{ color: TEXT }} /></label><div className="mt-3 flex gap-2">{onSample ? <PortalButton variant="secondary" onClick={onSample} disabled={busy === "upload"}>{busy === "upload" ? "Uploading..." : "Use sample file"}</PortalButton> : null}</div></div>; }
function Capability({ text }: { text: string }) { return <div className="rounded-lg px-3 py-2 text-[12px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: MUTED }}>{text}</div>; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>{label}</div><div className="text-[28px] font-semibold" style={{ color: TEXT }}>{value}</div></div>; }
function Panel({ title, children }: { title: string; children: React.ReactNode }) { return <section className="rounded-2xl p-5" style={{ background: BG, border: `1px solid ${BORDER}` }}><h3 className="text-[14px] font-semibold mb-4" style={{ color: TEXT }}>{title}</h3>{children}</section>; }
function Info({ label, value }: { label: string; value: string }) { return <div className="flex justify-between gap-4 py-1 text-[12px]"><span style={{ color: MUTED }}>{label}</span><span className="font-medium text-right" style={{ color: TEXT }}>{value}</span></div>; }
function Chip({ children }: { children: React.ReactNode }) { return <span className="rounded-full px-2 py-1 text-[10px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>{children}</span>; }
function ConnectorLogo({ profile, large = false }: { profile: ConnectorProfile; large?: boolean }) { const size = large ? 52 : 44; return <div className="rounded-xl flex items-center justify-center overflow-hidden shrink-0" style={{ width: size, height: size, background: profile.logoBg, border: `1px solid ${BORDER}` }}>{profile.logoAsset || profile.logoUrl ? <img src={profile.logoAsset || profile.logoUrl} alt={`${profile.title} logo`} className="max-h-full max-w-full object-contain" /> : <span className="font-semibold" style={{ color: profile.logoColor }}>{profile.logoFallback}</span>}</div>; }
function pillStyle(active: boolean) { return active ? { background: "#063D2C", color: "white", border: "1px solid #063D2C" } : { background: SURFACE, color: MUTED, border: `1px solid ${BORDER}` }; }
