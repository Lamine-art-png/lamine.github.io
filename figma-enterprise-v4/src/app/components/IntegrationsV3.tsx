import { useCallback, useMemo, useState, type ReactNode } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { openCommercialBoundary } from "./CommercialBoundaryHost";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";
import { UnifiedAgConnectorFlow } from "./UnifiedAgConnectorFlow";
import talgilLogo from "../../imports/talgil-logo-hq.png";
import wiseconnLogo from "../../imports/wiseconn-logo-hq.png";

type AnyRecord = Record<string, any>;
type ConnectorType = "controller" | "files" | "account" | "data_provider" | "custom_api";
type AuthPattern = "oauth" | "service_account" | "manual_upload" | "provider_api" | "enterprise_api";

const PLAN_ORDER = ["free", "professional", "team", "network", "enterprise"] as const;
type PlanId = typeof PLAN_ORDER[number];

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

type Profile = {
  title: string;
  subtitle: string;
  type: ConnectorType;
  description: string;
  authPattern: AuthPattern;
  action: string;
  logoUrl?: string;
  logoAsset?: string;
  logoFallback: string;
  logoBg: string;
  logoColor: string;
  supportsUpload?: boolean;
};

const UNIFIED_AG = new Set(["wiseconn", "talgil", "openet"]);
const TYPE_ORDER: ConnectorType[] = ["controller", "files", "account", "data_provider", "custom_api"];
const TYPE_LABEL: Record<ConnectorType, string> = { controller: "Controllers", files: "Files", account: "Accounts", data_provider: "Data providers", custom_api: "Custom APIs" };
const ACTIVE_STATUSES = new Set(["connected", "synced", "syncing", "rate_limited", "degraded"]);

const PROFILES: Record<string, Profile> = {
  wiseconn: { title: "WiseConn", subtitle: "Irrigation & telemetry", type: "controller", description: "Connect a WiseConn account, discover farms, choose scope, and sync controller evidence automatically.", authPattern: "provider_api", action: "Connect WiseConn", logoAsset: wiseconnLogo, logoFallback: "W", logoBg: "#ECFDF5", logoColor: "#047857" },
  talgil: { title: "Talgil", subtitle: "Controllers & irrigation", type: "controller", description: "Connect a Talgil account, discover controllers, choose scope, and sync operational evidence.", authPattern: "provider_api", action: "Connect Talgil", logoAsset: talgilLogo, logoFallback: "T", logoBg: "#EFF6FF", logoColor: "#1D4ED8" },
  manual_csv: { title: "Files", subtitle: "CSV, PDF, spreadsheets", type: "files", description: "Attach exports, logs, reports, and fragmented customer evidence.", authPattern: "manual_upload", action: "Upload files", logoFallback: "↥", logoBg: "#F8FAFC", logoColor: "#334155", supportsUpload: true },
  gmail: { title: "Gmail", subtitle: "Email context + reports", type: "account", description: "Authorize approved operational email context and attachments.", authPattern: "oauth", action: "Continue with Google", logoUrl: "https://www.google.com/s2/favicons?domain=mail.google.com&sz=128", logoFallback: "M", logoBg: "#FEF2F2", logoColor: "#DC2626" },
  outlook: { title: "Outlook", subtitle: "Microsoft email context", type: "account", description: "Authorize Microsoft 365 operational emails and attachments.", authPattern: "oauth", action: "Continue with Microsoft", logoUrl: "https://www.google.com/s2/favicons?domain=outlook.office.com&sz=128", logoFallback: "O", logoBg: "#EFF6FF", logoColor: "#2563EB" },
  google_drive: { title: "Google Drive", subtitle: "Documents + folders", type: "account", description: "Authorize folders containing PDFs, spreadsheets, maps, and water reports.", authPattern: "oauth", action: "Continue with Google", logoUrl: "https://www.google.com/s2/favicons?domain=drive.google.com&sz=128", logoFallback: "D", logoBg: "#ECFDF5", logoColor: "#16A34A" },
  dropbox: { title: "Dropbox", subtitle: "Files + folders", type: "account", description: "Authorize selected Dropbox folders and evidence files.", authPattern: "oauth", action: "Continue with Dropbox", logoUrl: "https://www.google.com/s2/favicons?domain=dropbox.com&sz=128", logoFallback: "Db", logoBg: "#EFF6FF", logoColor: "#0061FF" },
  box: { title: "Box", subtitle: "Enterprise files", type: "account", description: "Authorize enterprise folders, audit packets, PDFs, and spreadsheets.", authPattern: "oauth", action: "Continue with Box", logoUrl: "https://www.google.com/s2/favicons?domain=box.com&sz=128", logoFallback: "Bx", logoBg: "#EFF6FF", logoColor: "#0061D5" },
  slack: { title: "Slack", subtitle: "Operations context", type: "account", description: "Authorize approved operations-channel context and files.", authPattern: "oauth", action: "Continue with Slack", logoUrl: "https://www.google.com/s2/favicons?domain=slack.com&sz=128", logoFallback: "S", logoBg: "#FDF2F8", logoColor: "#611F69" },
  salesforce: { title: "Salesforce", subtitle: "Customer operations", type: "account", description: "Authorize accounts, contacts, cases, and customer-success context.", authPattern: "oauth", action: "Continue with Salesforce", logoUrl: "https://www.google.com/s2/favicons?domain=salesforce.com&sz=128", logoFallback: "SF", logoBg: "#EFF6FF", logoColor: "#0B5CAB" },
  john_deere: { title: "John Deere Operations Center", subtitle: "Fields, operations & equipment context", type: "account", description: "Authorize an Operations Center account and sync approved read-only farm structure, field operations, equipment reference, agronomic context, and organization settings. Work Plans are kept outside this phase until separately approved.", authPattern: "oauth", action: "Connect Operations Center", logoUrl: "https://www.google.com/s2/favicons?domain=deere.com&sz=128", logoFallback: "JD", logoBg: "#FFFDE7", logoColor: "#367C2B" },
  google_earth_engine: { title: "Google Earth Engine", subtitle: "Geospatial project", type: "data_provider", description: "Verify configured geospatial project and service-account readiness.", authPattern: "service_account", action: "Verify service account", logoUrl: "https://www.google.com/s2/favicons?domain=earthengine.google.com&sz=128", logoFallback: "GEE", logoBg: "#ECFDF5", logoColor: "#047857" },
  weather: { title: "Weather", subtitle: "Forecasts + station data", type: "data_provider", description: "Connect weather providers or import local station files.", authPattern: "provider_api", action: "Set up weather", logoFallback: "☀", logoBg: "#FFFBEB", logoColor: "#B45309", supportsUpload: true },
  openet: { title: "OpenET", subtitle: "Satellite ET & water use", type: "data_provider", description: "Add OpenET ET estimates by AGRO-AI fields, uploaded boundaries, or OpenET field IDs.", authPattern: "provider_api", action: "Add OpenET data", logoUrl: "https://www.google.com/s2/favicons?domain=openetdata.org&sz=128", logoFallback: "ET", logoBg: "#EEF2FF", logoColor: "#4338CA" },
  custom_api: { title: "Data Provider API", subtitle: "Existing systems", type: "custom_api", description: "Connect farm, agency, ERP, telemetry, or water-accounting systems.", authPattern: "enterprise_api", action: "Create access request", logoFallback: "API", logoBg: "#FDF2F8", logoColor: "#BE185D" },
};

function profileFor(id: string, connector?: Connector): Profile {
  return PROFILES[id] || { title: connector?.name || id, subtitle: connector?.category || "Connector", type: "custom_api", description: connector?.promise || "Connect this source to AGRO-AI.", authPattern: "enterprise_api", action: "Connect", logoFallback: id.slice(0, 2).toUpperCase(), logoBg: "#F8FAFC", logoColor: "#334155", supportsUpload: Boolean(connector?.upload_supported) };
}
function asArray(value: unknown): AnyRecord[] { return Array.isArray(value) ? value as AnyRecord[] : []; }
function cleanStatus(status: string) { if (["connected", "ready", "test_passed"].includes(status)) return "connected"; if (status === "synced") return "synced"; if (status === "oauth_pending") return "authorizing"; if (["not_configured", "needs_credentials", "coming_soon"].includes(status)) return "available"; return (status || "available").replaceAll("_", " "); }
function statusTone(status: string): "neutral" | "good" | "warn" | "locked" { if (["connected", "synced", "ready"].includes(status)) return "good"; if (["authorizing", "discovering", "syncing", "action_required", "reconnect_required", "rate_limited", "degraded"].includes(status)) return "warn"; return "neutral"; }
function canonicalPlan(value: unknown): PlanId { const raw = String(value || "free").toLowerCase(); const aliases: Record<string, PlanId> = { pilot: "free", pro: "professional", waterops: "professional", assurance_audit: "professional", assurance: "team", internal: "enterprise" }; const next = aliases[raw] || raw; return PLAN_ORDER.includes(next as PlanId) ? next as PlanId : "free"; }
function fallbackRequired(provider: string): PlanId { if (["manual_csv", "chat_upload"].includes(provider)) return "free"; if (provider === "custom_api") return "network"; if (["universal_controller", "salesforce", "google_earth_engine"].includes(provider)) return "enterprise"; return "professional"; }
function requiredPlan(connector: Connector): PlanId { const raw = connector.required_plan && connector.required_plan !== "internal" ? connector.required_plan : fallbackRequired(connector.id); return canonicalPlan(raw); }
function planName(value: PlanId) { return value === "enterprise" ? "Enterprise" : value === "network" ? "Network" : value === "team" ? "Team" : value === "professional" ? "Professional" : "Free"; }
function featureFor(provider: string) { if (["manual_csv", "chat_upload"].includes(provider)) return "connectors.manual_upload"; if (["gmail", "outlook", "google_drive", "dropbox", "box", "slack", "john_deere"].includes(provider)) return "connectors.oauth_documents"; if (provider === "custom_api") return "connectors.custom_api"; if (["universal_controller", "salesforce", "google_earth_engine"].includes(provider)) return "connectors.custom_integration"; return "connectors.live"; }
function connectorUpgradeMessage(profile: Profile, needed: PlanId) {
  return `Unlock ${profile.title}: ${profile.description} Without ${profile.title} connected, this source stays outside AGRO-AI and your team relies more on manual imports, stale snapshots, and disconnected handoffs. Upgrade to ${planName(needed)} to connect ${profile.title} and bring ${profile.subtitle.toLowerCase()} into the operating workflow.`;
}

export function IntegrationsV3() {
  const { currentOrganization, currentWorkspace } = useAuth();
  const catalogState = usePortalResource<AnyRecord>(useCallback(() => apiClient.connectorHub.catalog(), []));
  const connectionsState = usePortalResource<AnyRecord>(useCallback(() => apiClient.connectorHub.connections(), []));
  const [selected, setSelected] = useState<Connector | null>(null);
  const [connection, setConnection] = useState<AnyRecord | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [search, setSearch] = useState("");
  const [activeType, setActiveType] = useState<ConnectorType | "all">("all");

  const catalog = useMemo(() => asArray(catalogState.data?.connectors) as Connector[], [catalogState.data]);
  const connections = asArray(connectionsState.data?.connections);
  const plan = canonicalPlan(currentOrganization?.plan);
  const cards = useMemo(() => {
    const byId = new Map(catalog.map((item) => [item.id, item]));
    Object.keys(PROFILES).forEach((id) => { if (!byId.has(id)) { const profile = PROFILES[id]; byId.set(id, { id, name: profile.title, category: TYPE_LABEL[profile.type], status: "available", required_plan: fallbackRequired(id), connection_methods: [], imports: [], used_by: [], promise: profile.description, upload_supported: profile.supportsUpload }); } });
    return Array.from(byId.values());
  }, [catalog]);
  const visibleCards = useMemo(() => {
    const q = search.trim().toLowerCase();
    return cards.filter((item) => activeType === "all" || profileFor(item.id, item).type === activeType).filter((item) => { if (!q) return true; const profile = profileFor(item.id, item); return [profile.title, profile.subtitle, profile.description, item.name, item.category, ...(item.imports || [])].join(" ").toLowerCase().includes(q); }).sort((a, b) => TYPE_ORDER.indexOf(profileFor(a.id, a).type) - TYPE_ORDER.indexOf(profileFor(b.id, b).type) || profileFor(a.id, a).title.localeCompare(profileFor(b.id, b).title));
  }, [cards, search, activeType]);

  async function refresh() { await Promise.all([catalogState.refresh(), connectionsState.refresh()]); }
  function openConnector(connector: Connector) {
    const needed = requiredPlan(connector);
    if (PLAN_ORDER.indexOf(plan) < PLAN_ORDER.indexOf(needed)) {
      const profile = profileFor(connector.id, connector);
      openCommercialBoundary({ status: 402, code: "upgrade_required", feature: featureFor(connector.id), recommended_plan: needed, conversion_context: connectorUpgradeMessage(profile, needed), source: "connectors_v3" });
      return;
    }
    const existing = connections.find((row) => row.provider === connector.id) || connector.connection || null;
    setSelected(connector); setConnection(existing); setMessage("");
  }

  async function launchGeneric() {
    if (!selected) return;
    const profile = profileFor(selected.id, selected);
    if (profile.authPattern === "manual_upload") { setMessage("Choose a file below to import evidence."); return; }
    setBusy("launch"); setMessage("");
    try {
      if (profile.authPattern === "oauth" || profile.authPattern === "service_account") {
        const result = await apiClient.post("/v1/connectors/launch/start", { provider: selected.id, workspace_id: currentWorkspace?.id, redirect_url: "https://api.agroai-pilot.com/v1/connectors/oauth/callback", metadata: { surface: "connector_hub_v3" } }) as AnyRecord;
        setConnection(result.connection || connection);
        if (result.auth_url) window.location.assign(result.auth_url);
        else setMessage(result.message || `${profile.title} setup state recorded.`);
      } else {
        const result = await apiClient.post("/v1/connectors/launch/access-request", { provider: selected.id, workspace_id: currentWorkspace?.id, display_name: profile.title, metadata: { surface: "connector_hub_v3" } }) as AnyRecord;
        setConnection(result.connection || null);
        setMessage(`${profile.title} setup request recorded.`);
      }
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Connection failed."); }
    finally { setBusy(""); }
  }

  async function syncSelected() {
    if (!connection?.id) return;
    setBusy("sync"); setMessage("");
    try {
      const result = await apiClient.post(`/v1/connectors/provider-sync/${connection.id}/sync`, {}) as AnyRecord;
      setConnection(result.connection || connection);
      setMessage(result.deduplicated ? "A sync is already queued or running." : "Sync queued. AGRO-AI will ingest the authorized Operations Center context through the durable worker path.");
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Sync could not be queued."); }
    finally { setBusy(""); }
  }

  async function disconnectSelected() {
    if (!connection?.id) return;
    setBusy("disconnect"); setMessage("");
    try {
      const result = await apiClient.post(`/v1/connectors/provider-sync/${connection.id}/disconnect`, {}) as AnyRecord;
      setConnection(result.connection || null);
      setMessage("Operations Center disconnected and locally stored connector credentials revoked.");
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Disconnect failed."); }
    finally { setBusy(""); }
  }

  async function uploadFile(file?: File) {
    if (!file || !selected) return;
    setBusy("upload"); setMessage("");
    try { const result = await apiClient.evidence.upload(file, selected.id, currentWorkspace?.id) as AnyRecord; setConnection(result.connection || connection); setMessage(`Imported ${String(result.evidence_records_created ?? 0)} evidence records from ${file.name}.`); await refresh(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Upload failed."); }
    finally { setBusy(""); }
  }

  const selectedProfile = selected ? profileFor(selected.id, selected) : null;
  const selectedRawStatus = String(connection?.status || selected?.connection?.status || selected?.status || "available");
  const deereManaged = selected?.id === "john_deere" && Boolean(connection?.id) && ACTIVE_STATUSES.has(selectedRawStatus);

  return <div className="min-h-screen" style={{ background: BG }}>
    <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}><div className="flex items-start justify-between gap-6"><div><div className="flex items-center gap-2 mb-3"><StatusBadge label="Integration Hub" tone="good" /><StatusBadge label={`${planName(plan)} plan`} /></div><h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Connectors</h1><p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>Authorize, choose scope, sync, done. Provider complexity stays behind AGRO-AI.</p><p className="mt-2 max-w-4xl text-[11px] leading-relaxed" style={{ color: MUTED }}>File imports share one monthly quota: 15 on Free, 500 on Professional, 2,500 on Team, 10,000 on Network. Weather and OpenET start on Professional; standard Custom API starts on Network; bespoke integrations require Enterprise.</p></div><PortalButton variant="secondary" onClick={refresh}>Refresh</PortalButton></div></header>
    <main className="px-8 py-6 space-y-6" style={{ maxWidth: 1320 }}>
      {catalogState.error ? <InlineState title={catalogState.error} /> : null}{message ? <InlineState title={message} /> : null}
      <section className="grid grid-cols-4 gap-4"><Metric label="Connectors" value={String(cards.length)} /><Metric label="Active sources" value={String(connections.filter((row) => ["connected", "synced", "syncing"].includes(String(row.status))).length)} /><Metric label="Self-serve AgTech" value="3" /><Metric label="Lifecycle" value="Unified v3" /></section>
      <section className="rounded-2xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="flex flex-wrap items-center gap-2 mb-4"><button onClick={() => setActiveType("all")} className="rounded-full px-3 py-2 text-[12px]" style={pillStyle(activeType === "all")}>All</button>{TYPE_ORDER.map((type) => <button key={type} onClick={() => setActiveType(type)} className="rounded-full px-3 py-2 text-[12px]" style={pillStyle(activeType === type)}>{TYPE_LABEL[type]}</button>)}</div><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search John Deere, WiseConn, Talgil, OpenET, Google, Microsoft..." className="h-11 w-full rounded-xl px-4 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} /></section>
      <section className="grid grid-cols-3 gap-4">{visibleCards.map((connector) => { const profile = profileFor(connector.id, connector); const live = connections.find((row) => row.provider === connector.id) || connector.connection; const rawStatus = String(live?.status || connector.status || "available"); const needed = requiredPlan(connector); const locked = PLAN_ORDER.indexOf(plan) < PLAN_ORDER.indexOf(needed); return <article key={connector.id} data-provider-id={connector.id} className="rounded-2xl p-5 flex flex-col min-h-[250px]" style={{ background: SURFACE, border: `1px solid ${locked ? "#A7CFAF" : BORDER}` }}><div className="flex items-start justify-between gap-3 mb-4"><div className="flex items-center gap-3"><ConnectorLogo profile={profile} /><div><div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>{TYPE_LABEL[profile.type]}</div><h3 className="text-[16px] font-semibold" style={{ color: TEXT }}>{profile.title}</h3></div></div><StatusBadge label={locked ? `${planName(needed)} unlocks` : cleanStatus(rawStatus)} tone={locked ? "locked" : statusTone(rawStatus)} /></div><p className="text-[12px] leading-relaxed mb-2" style={{ color: MUTED }}>{profile.subtitle}</p><p className="text-[12px] leading-relaxed mb-4 flex-1" style={{ color: MUTED }}>{profile.description}</p><div className="flex flex-wrap gap-1.5 mb-4"><Chip>{TYPE_LABEL[profile.type]}</Chip>{locked ? <Chip>🔒 {planName(needed)}</Chip> : UNIFIED_AG.has(connector.id) ? <Chip>self-serve v3</Chip> : <Chip>{profile.authPattern === "oauth" ? "OAuth consent" : profile.authPattern.replaceAll("_", " ")}</Chip>}</div><button type="button" onClick={() => openConnector({ ...connector, connection: live })} className="h-10 rounded-lg text-[12px] font-semibold" style={{ background: "#16533C", color: "white" }}>{locked ? `Upgrade to ${planName(needed)}` : live ? "Manage connection" : profile.action}</button></article>; })}</section>
    </main>
    {selected && selectedProfile ? <div className="fixed inset-0 z-50"><button className="absolute inset-0 bg-black/30" onClick={() => setSelected(null)} aria-label="Close connector setup" /><aside className="absolute right-0 top-0 h-full w-[740px] max-w-[96vw] overflow-y-auto shadow-2xl" style={{ background: SURFACE }}><div className="px-6 py-5" style={{ borderBottom: `1px solid ${BORDER}` }}><div className="flex items-start justify-between gap-4"><div className="flex items-center gap-4"><ConnectorLogo profile={selectedProfile} large /><div><div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>{TYPE_LABEL[selectedProfile.type]}</div><h2 className="text-[22px] font-semibold" style={{ color: TEXT }}>{selectedProfile.action}</h2><p className="mt-2 text-[13px] leading-relaxed max-w-[520px]" style={{ color: MUTED }}>{selectedProfile.description}</p></div></div><StatusBadge label={cleanStatus(selectedRawStatus)} tone={statusTone(selectedRawStatus)} /></div></div><div className="p-6 space-y-5">{UNIFIED_AG.has(selected.id) ? <UnifiedAgConnectorFlow provider={selected.id as "wiseconn" | "talgil" | "openet"} workspaceId={currentWorkspace?.id} connection={connection} onConnection={setConnection} onMessage={setMessage} onRefresh={refresh} /> : <><Panel title="Connection"><p className="text-[12px] leading-relaxed mb-4" style={{ color: MUTED }}>{selectedProfile.description}</p>{deereManaged ? <div className="grid grid-cols-3 gap-2"><PortalButton onClick={syncSelected} disabled={busy === "sync"}>{busy === "sync" ? "Queueing..." : "Sync now"}</PortalButton><PortalButton variant="secondary" onClick={launchGeneric} disabled={busy === "launch"}>{busy === "launch" ? "Working..." : "Reauthorize"}</PortalButton><PortalButton variant="secondary" onClick={disconnectSelected} disabled={busy === "disconnect"}>{busy === "disconnect" ? "Disconnecting..." : "Disconnect"}</PortalButton></div> : <PortalButton onClick={launchGeneric} disabled={busy === "launch"}>{busy === "launch" ? "Working..." : selectedProfile.action}</PortalButton>}</Panel>{selectedProfile.supportsUpload ? <Panel title="Import instead"><UploadArea onUpload={uploadFile} busy={busy} /></Panel> : null}<Panel title="Connection state"><Info label="Provider" value={selectedProfile.title} /><Info label="Connection ID" value={String(connection?.id || "—")} /><Info label="Status" value={cleanStatus(selectedRawStatus)} /><Info label="Last sync" value={String(connection?.last_sync_at || "—")} /></Panel></>}<Panel title="Next"><div className="grid grid-cols-3 gap-2"><PortalButton variant="secondary" onClick={() => window.location.assign("/sources")}>Sources</PortalButton><PortalButton variant="secondary" onClick={() => window.location.assign("/evidence")}>Evidence</PortalButton><PortalButton variant="secondary" onClick={() => window.location.assign("/intelligence")}>Ask AGRO-AI</PortalButton></div></Panel></div></aside></div> : null}
  </div>;
}

function UploadArea({ onUpload, busy }: { onUpload: (file?: File) => void; busy: string }) { return <label className="block rounded-2xl p-5 cursor-pointer" style={{ background: SURFACE, border: `1px dashed ${BORDER}` }}><div className="text-[15px] font-semibold mb-1" style={{ color: TEXT }}>Attach a source file</div><div className="text-[12px] leading-relaxed mb-4" style={{ color: MUTED }}>CSV, JSON, TXT, or PDF. AGRO-AI will parse and cite usable records.</div><input type="file" accept=".csv,.json,.txt,.pdf" onChange={(event) => onUpload(event.target.files?.[0])} className="text-[12px]" disabled={busy === "upload"} /></label>; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>{label}</div><div className="text-[28px] font-semibold" style={{ color: TEXT }}>{value}</div></div>; }
function Panel({ title, children }: { title: string; children: ReactNode }) { return <section className="rounded-2xl p-5" style={{ background: BG, border: `1px solid ${BORDER}` }}><h3 className="text-[14px] font-semibold mb-4" style={{ color: TEXT }}>{title}</h3>{children}</section>; }
function Info({ label, value }: { label: string; value: string }) { return <div className="flex justify-between gap-4 py-1 text-[12px]"><span style={{ color: MUTED }}>{label}</span><span className="font-medium text-right" style={{ color: TEXT }}>{value}</span></div>; }
function Chip({ children }: { children: ReactNode }) { return <span className="rounded-full px-2 py-1 text-[10px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>{children}</span>; }
function ConnectorLogo({ profile, large = false }: { profile: Profile; large?: boolean }) { const size = large ? 52 : 44; return <div className="rounded-xl flex items-center justify-center overflow-hidden shrink-0" style={{ width: size, height: size, background: profile.logoBg, border: `1px solid ${BORDER}` }}>{profile.logoAsset || profile.logoUrl ? <img src={profile.logoAsset || profile.logoUrl} alt={`${profile.title} logo`} className="max-h-full max-w-full object-contain" /> : <span className="font-semibold" style={{ color: profile.logoColor }}>{profile.logoFallback}</span>}</div>; }
function pillStyle(active: boolean) { return active ? { background: "#063D2C", color: "white", border: "1px solid #063D2C" } : { background: SURFACE, color: MUTED, border: `1px solid ${BORDER}` }; }
