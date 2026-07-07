import { useMemo, useState } from "react";
import { unifiedConnectors, type UnifiedAgProvider, type UnifiedResource } from "../api/unifiedConnectors";
import { BG, BORDER, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;

type Props = {
  provider: UnifiedAgProvider;
  workspaceId?: string;
  connection: AnyRecord | null;
  onConnection: (connection: AnyRecord | null) => void;
  onMessage: (message: string) => void;
  onRefresh: () => Promise<void> | void;
};

const PROVIDER_COPY: Record<UnifiedAgProvider, { credential: string; helper: string; action: string }> = {
  wiseconn: {
    credential: "WiseConn access token / API key",
    helper: "Paste the customer-authorized WiseConn credential once. AGRO-AI encrypts it immediately, verifies the account, and discovers farms.",
    action: "Connect WiseConn",
  },
  talgil: {
    credential: "Talgil API access key",
    helper: "Paste the Talgil credential authorized for this customer account. AGRO-AI verifies access and discovers controllers without exposing vendor setup details.",
    action: "Connect Talgil",
  },
  openet: {
    credential: "OpenET API key",
    helper: "Paste an OpenET API key once. AGRO-AI verifies the OpenET account, encrypts the key, and lets you choose field scope.",
    action: "Add OpenET data",
  },
};

function lifecycleTone(status: string): "neutral" | "good" | "warn" | "locked" {
  if (["connected", "synced"].includes(status)) return "good";
  if (["authorizing", "discovering", "syncing", "rate_limited", "degraded", "action_required", "reconnect_required"].includes(status)) return "warn";
  return "neutral";
}

export function UnifiedAgConnectorFlow({ provider, workspaceId, connection, onConnection, onMessage, onRefresh }: Props) {
  const copy = PROVIDER_COPY[provider];
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState("");
  const [resources, setResources] = useState<UnifiedResource[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [openETMode, setOpenETMode] = useState<"agroai_fields" | "upload_boundaries" | "openet_field_ids">("agroai_fields");
  const [fieldIdsText, setFieldIdsText] = useState("");
  const [geometryText, setGeometryText] = useState("");
  const status = String(connection?.status || "available");
  const connectionId = String(connection?.id || "");
  const allSelected = resources.length > 0 && selectedIds.length === resources.length;
  const parsedFieldIds = useMemo(() => fieldIdsText.split(/[\s,]+/).map((value) => value.trim()).filter(Boolean), [fieldIdsText]);

  async function connect() {
    if (!apiKey.trim()) {
      onMessage(`${copy.credential} is required.`);
      return;
    }
    setBusy("connect");
    onMessage("");
    try {
      const result = await unifiedConnectors.connect({ provider, workspace_id: workspaceId, api_key: apiKey.trim() }) as AnyRecord;
      onConnection(result.connection || null);
      setResources(Array.isArray(result.resources) ? result.resources : []);
      setApiKey("");
      onMessage(provider === "openet" ? "OpenET account verified. Choose how AGRO-AI should scope fields." : `${copy.action} complete. Choose what to sync.`);
      await onRefresh();
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "Connection failed.");
    } finally {
      setBusy("");
    }
  }

  async function discover() {
    if (!connectionId) return;
    setBusy("discover");
    onMessage("");
    try {
      const result = await unifiedConnectors.discovery(connectionId) as AnyRecord;
      setResources(Array.isArray(result.resources) ? result.resources : []);
      onConnection(result.connection || connection);
      onMessage(`Discovered ${Number(result.count || 0)} ${provider === "talgil" ? "controllers" : provider === "wiseconn" ? "farms" : "OpenET fields"}.`);
      await onRefresh();
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "Discovery failed.");
    } finally {
      setBusy("");
    }
  }

  async function saveSelection() {
    if (!connectionId) return;
    setBusy("select");
    onMessage("");
    try {
      if (provider === "openet") {
        if (openETMode === "openet_field_ids") {
          if (!parsedFieldIds.length) throw new Error("Enter at least one OpenET field ID.");
          await unifiedConnectors.select(connectionId, { scope_mode: "openet_field_ids", field_ids: parsedFieldIds, resource_ids: parsedFieldIds });
        } else if (openETMode === "agroai_fields") {
          await unifiedConnectors.select(connectionId, { scope_mode: "agroai_fields" });
        } else {
          const geometry = geometryText.split(/[\s,]+/).map(Number).filter((value) => Number.isFinite(value));
          if (geometry.length < 6) throw new Error("Enter a valid longitude/latitude polygon or upload a GeoJSON boundary file.");
          await unifiedConnectors.select(connectionId, { scope_mode: "geometry", geometry });
        }
      } else {
        if (!selectedIds.length && resources.length) throw new Error("Choose at least one resource to sync.");
        await unifiedConnectors.select(connectionId, { scope_mode: "provider_resources", resource_ids: selectedIds });
      }
      onMessage("Scope saved. Start sync when ready.");
      await onRefresh();
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "Could not save scope.");
    } finally {
      setBusy("");
    }
  }

  async function uploadBoundary(file?: File) {
    if (!file || !connectionId) return;
    setBusy("boundary");
    onMessage("");
    try {
      const uploaded = await unifiedConnectors.uploadOpenETBoundary(connectionId, file) as AnyRecord;
      onConnection(uploaded.connection || connection);
      const discovered = await unifiedConnectors.discovery(connectionId) as AnyRecord;
      setResources(Array.isArray(discovered.resources) ? discovered.resources : []);
      onConnection(discovered.connection || uploaded.connection || connection);
      onMessage(`Boundary uploaded. ${Number(discovered.count || 0)} matching OpenET fields discovered.`);
      await onRefresh();
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "Boundary upload failed.");
    } finally {
      setBusy("");
    }
  }

  async function sync() {
    if (!connectionId) return;
    setBusy("sync");
    onMessage("");
    try {
      const result = await unifiedConnectors.sync(connectionId) as AnyRecord;
      onConnection(result.connection || connection);
      onMessage(result.deduplicated ? "A sync is already running for this connection." : "Sync queued on the durable connector worker plane.");
      await onRefresh();
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "Could not start sync.");
    } finally {
      setBusy("");
    }
  }

  async function refreshStatus() {
    if (!connectionId) return;
    setBusy("status");
    try {
      const result = await unifiedConnectors.status(connectionId) as AnyRecord;
      onConnection(result.connection || connection);
      onMessage(`Connection state: ${String(result.state || result.connection?.status || "unknown").replaceAll("_", " ")}.`);
      await onRefresh();
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "Could not refresh status.");
    } finally {
      setBusy("");
    }
  }

  async function disconnect() {
    if (!connectionId) return;
    setBusy("disconnect");
    try {
      const result = await unifiedConnectors.disconnect(connectionId) as AnyRecord;
      onConnection(result.connection || null);
      setResources([]);
      setSelectedIds([]);
      onMessage("Disconnected. The encrypted customer credential was revoked locally.");
      await onRefresh();
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "Disconnect failed.");
    } finally {
      setBusy("");
    }
  }

  if (!connectionId || ["available", "action_required", "reconnect_required", "failed"].includes(status)) {
    return <div className="space-y-4"><div className="rounded-xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="flex items-center justify-between gap-3 mb-3"><div className="text-[14px] font-semibold" style={{ color: TEXT }}>{copy.action}</div><StatusBadge label={status.replaceAll("_", " ")} tone={lifecycleTone(status)} /></div>
      <p className="text-[12px] leading-relaxed mb-4" style={{ color: MUTED }}>{copy.helper}</p>
      <label className="block text-[12px]" style={{ color: MUTED }}>{copy.credential}<input value={apiKey} onChange={(event) => setApiKey(event.target.value)} type="password" autoComplete="off" placeholder="••••••••••••••••" className="mt-1 h-11 w-full rounded-lg px-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} /></label>
      <div className="mt-4"><PortalButton onClick={connect} disabled={busy === "connect"}>{busy === "connect" ? "Verifying..." : copy.action}</PortalButton></div>
      <p className="mt-3 text-[11px] leading-relaxed" style={{ color: MUTED }}>The credential is sent only to AGRO-AI's authenticated backend, encrypted into the tenant-scoped connector vault, and never returned to the browser. Provider destinations are fixed server-side.</p>
    </div></div>;
  }

  return <div className="space-y-4">
    <div className="rounded-xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="flex items-center justify-between gap-3"><div><div className="text-[13px] font-semibold" style={{ color: TEXT }}>Account verified</div><div className="text-[11px] mt-1" style={{ color: MUTED }}>Connection {connectionId.slice(0, 8)}…</div></div><StatusBadge label={status.replaceAll("_", " ")} tone={lifecycleTone(status)} /></div></div>

    {provider !== "openet" ? <div className="rounded-xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="flex items-center justify-between gap-3 mb-3"><div className="text-[13px] font-semibold" style={{ color: TEXT }}>{provider === "wiseconn" ? "Choose farms" : "Choose controllers"}</div><PortalButton variant="secondary" onClick={discover} disabled={busy === "discover"}>{busy === "discover" ? "Discovering..." : "Refresh discovery"}</PortalButton></div>
      {!resources.length ? <p className="text-[12px]" style={{ color: MUTED }}>No resources loaded yet. Run discovery.</p> : <div className="space-y-2 max-h-72 overflow-y-auto">{resources.map((resource) => <label key={resource.id} className="flex items-center gap-3 rounded-lg px-3 py-2 cursor-pointer" style={{ background: BG, border: `1px solid ${BORDER}` }}><input type="checkbox" checked={selectedIds.includes(resource.id)} onChange={(event) => setSelectedIds(event.target.checked ? [...selectedIds, resource.id] : selectedIds.filter((id) => id !== resource.id))} /><span className="text-[12px] font-medium" style={{ color: TEXT }}>{resource.name}</span><span className="ml-auto text-[10px]" style={{ color: MUTED }}>{resource.id}</span></label>)}</div>}
      {resources.length ? <div className="mt-3 flex items-center gap-2"><PortalButton variant="secondary" onClick={() => setSelectedIds(allSelected ? [] : resources.map((resource) => resource.id))}>{allSelected ? "Clear all" : "Select all"}</PortalButton><PortalButton onClick={saveSelection} disabled={busy === "select"}>{busy === "select" ? "Saving..." : "Save scope"}</PortalButton></div> : null}
    </div> : <div className="rounded-xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="text-[13px] font-semibold mb-3" style={{ color: TEXT }}>Choose fields</div>
      <div className="space-y-2">
        <Choice active={openETMode === "agroai_fields"} title="Use my AGRO-AI fields" detail="Resolve OpenET scope from explicit OpenET IDs or usable field geometry already attached to this workspace." onClick={() => setOpenETMode("agroai_fields")} />
        <Choice active={openETMode === "upload_boundaries"} title="Upload boundaries" detail="Upload GeoJSON into OpenET's temporary boundary asset flow, then discover matching fields." onClick={() => setOpenETMode("upload_boundaries")} />
        <Choice active={openETMode === "openet_field_ids"} title="Select OpenET field IDs" detail="Use one or more OpenET geodatabase field identifiers." onClick={() => setOpenETMode("openet_field_ids")} />
      </div>
      {openETMode === "upload_boundaries" ? <div className="mt-4 space-y-3"><label className="block rounded-xl p-4 cursor-pointer" style={{ background: BG, border: `1px dashed ${BORDER}` }}><div className="text-[12px] font-medium" style={{ color: TEXT }}>Upload GeoJSON boundaries</div><input type="file" accept=".geojson,.json,application/geo+json" className="mt-3 text-[12px]" onChange={(event) => uploadBoundary(event.target.files?.[0])} /></label><div className="text-[11px]" style={{ color: MUTED }}>Or paste a longitude/latitude polygon:</div><textarea value={geometryText} onChange={(event) => setGeometryText(event.target.value)} placeholder="-121.67, 38.61, -121.67, 38.65, ..." className="min-h-24 w-full rounded-lg p-3 text-[12px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} /></div> : null}
      {openETMode === "openet_field_ids" ? <textarea value={fieldIdsText} onChange={(event) => setFieldIdsText(event.target.value)} placeholder="Enter field IDs separated by commas or spaces" className="mt-4 min-h-24 w-full rounded-lg p-3 text-[12px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} /> : null}
      <div className="mt-4 flex gap-2"><PortalButton onClick={saveSelection} disabled={busy === "select" || busy === "boundary"}>{busy === "select" ? "Saving..." : busy === "boundary" ? "Uploading..." : "Continue"}</PortalButton><PortalButton variant="secondary" onClick={discover} disabled={busy === "discover"}>{busy === "discover" ? "Finding fields..." : "Discover matching fields"}</PortalButton></div>
      {resources.length ? <div className="mt-4 rounded-lg p-3" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="text-[11px] font-semibold mb-2" style={{ color: TEXT }}>{resources.length} OpenET fields found</div><div className="flex flex-wrap gap-1.5">{resources.slice(0, 40).map((resource) => <span key={resource.id} className="rounded-full px-2 py-1 text-[10px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: MUTED }}>{resource.name}</span>)}</div></div> : null}
    </div>}

    <div className="rounded-xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="text-[13px] font-semibold mb-2" style={{ color: TEXT }}>Sync</div>
      <p className="text-[12px] leading-relaxed mb-4" style={{ color: MUTED }}>Runs on AGRO-AI's durable connector queue with retries, tenant-scoped credentials, idempotent evidence persistence, and sync cursors.</p>
      <div className="flex flex-wrap gap-2"><PortalButton onClick={sync} disabled={busy === "sync"}>{busy === "sync" ? "Queueing..." : "Start sync"}</PortalButton><PortalButton variant="secondary" onClick={refreshStatus} disabled={busy === "status"}>{busy === "status" ? "Refreshing..." : "Refresh status"}</PortalButton><PortalButton variant="secondary" onClick={disconnect} disabled={busy === "disconnect"}>{busy === "disconnect" ? "Disconnecting..." : "Disconnect"}</PortalButton></div>
    </div>
  </div>;
}

function Choice({ active, title, detail, onClick }: { active: boolean; title: string; detail: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className="w-full rounded-xl p-3 text-left" style={{ background: active ? "#ECFDF5" : BG, border: `1px solid ${active ? "#16A36A" : BORDER}` }}><div className="flex items-center gap-2"><span className="h-4 w-4 rounded-full flex items-center justify-center" style={{ border: `1px solid ${active ? "#0F7A55" : BORDER}` }}>{active ? <span className="h-2 w-2 rounded-full" style={{ background: "#0F7A55" }} /> : null}</span><span className="text-[12px] font-semibold" style={{ color: TEXT }}>{title}</span></div><div className="mt-1 pl-6 text-[11px] leading-relaxed" style={{ color: MUTED }}>{detail}</div></button>;
}
