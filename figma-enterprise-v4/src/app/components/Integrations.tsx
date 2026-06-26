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
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");

  const catalog = useMemo(() => asArray(catalogState.data?.connectors) as Connector[], [catalogState.data]);
  const connections = asArray(connectionsState.data?.connections);
  const plan = String(currentOrganization?.plan || "free").toLowerCase();

  async function refresh() {
    await Promise.all([catalogState.refresh(), connectionsState.refresh()]);
  }

  async function openConnector(connector: Connector) {
    setSelected(connector);
    setUploadResult(null);
    setMessage("");
    setBusy(connector.id);

    try {
      const result = await apiClient.connectorHub.start({
        provider: connector.id as any,
        method: connector.connection_methods?.[0] || "export_upload",
        workspace_id: currentWorkspace?.id,
        metadata: { surface: "connector_hub" },
      }) as AnyRecord;

      setConnection(result.connection || connector.connection || null);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not start connector setup.");
    } finally {
      setBusy("");
    }
  }

  async function testCurrent() {
    if (!connection?.id) return;

    setBusy("test");
    setMessage("");

    try {
      const result = await apiClient.connectorHub.test(connection.id) as AnyRecord;
      setConnection(result.connection || connection);
      setMessage(result.message || "Connection tested.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Connection test failed.");
    } finally {
      setBusy("");
    }
  }

  async function syncCurrent() {
    if (!connection?.id) return;

    setBusy("sync");
    setMessage("");

    try {
      const result = await apiClient.connectorHub.sync(connection.id) as AnyRecord;
      setConnection(result.connection || connection);
      setMessage(`${pretty(result.evidence_records, "0")} evidence records available from this connector.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Sync failed.");
    } finally {
      setBusy("");
    }
  }

  async function uploadFile(file?: File) {
    if (!file || !connection?.id) return;

    setBusy("upload");
    setMessage("");
    setUploadResult(null);

    try {
      const result = await apiClient.connectorHub.upload(connection.id, file) as AnyRecord;
      setUploadResult(result);
      setConnection(result.connection || connection);
      setMessage(`Imported ${pretty(result.evidence_records_created, "0")} evidence records from ${file.name}.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <StatusBadge label="Connector Hub" tone="good" />
              <StatusBadge label={`${plan} plan`} />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Connectors</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Set up sources, upload exports, parse evidence, test readiness, and feed Ask AGRO-AI with real operating context.
            </p>
          </div>
          <PortalButton variant="secondary" onClick={refresh}>Refresh</PortalButton>
        </div>
      </header>

      <div className="px-8 py-6 space-y-6" style={{ maxWidth: 1280 }}>
        {catalogState.error ? <InlineState title={catalogState.error} /> : null}
        {message ? <InlineState title={message} /> : null}

        <section className="grid grid-cols-4 gap-4">
          <Metric label="Catalog connectors" value={String(catalog.length)} />
          <Metric label="Created connections" value={String(connections.length)} />
          <Metric label="Upload-capable" value={String(catalog.filter((item) => item.upload_supported).length)} />
          <Metric label="Live-sync policy" value="Honest" />
        </section>

        <section className="grid grid-cols-3 gap-4">
          {catalog.map((connector) => {
            const live = connections.find((row) => row.provider === connector.id) || connector.connection;
            const status = String(live?.status || connector.status);
            return (
              <article key={connector.id} className="rounded-2xl p-5 flex flex-col min-h-[280px]" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
                <div className="flex items-start justify-between gap-3 mb-4">
                  <div>
                    <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>{connector.category}</div>
                    <h3 className="text-[17px] font-semibold" style={{ color: TEXT }}>{connector.name}</h3>
                  </div>
                  <StatusBadge label={status} tone={statusTone(status)} />
                </div>

                <p className="text-[12px] leading-relaxed mb-4 flex-1" style={{ color: MUTED }}>{connector.promise}</p>

                <div className="space-y-1 mb-4">
                  {(connector.imports || []).slice(0, 5).map((item) => (
                    <div key={item} className="text-[11px]" style={{ color: MUTED }}>• {item}</div>
                  ))}
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

      {selected ? (
        <div className="fixed inset-0 z-50">
          <button className="absolute inset-0 bg-black/30" onClick={() => setSelected(null)} aria-label="Close connector setup" />
          <aside className="absolute right-0 top-0 h-full w-[620px] max-w-[96vw] overflow-y-auto shadow-2xl" style={{ background: SURFACE }}>
            <div className="px-6 py-5" style={{ borderBottom: `1px solid ${BORDER}` }}>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>{selected.category}</div>
                  <h2 className="text-xl font-semibold" style={{ color: TEXT }}>{selected.name}</h2>
                  <p className="mt-2 text-[13px] leading-relaxed" style={{ color: MUTED }}>{selected.promise}</p>
                </div>
                <StatusBadge label={String(connection?.status || selected.status)} tone={statusTone(String(connection?.status || selected.status))} />
              </div>
            </div>

            <div className="p-6 space-y-5">
              <Panel title="Connection state">
                <Info label="Provider" value={selected.id} />
                <Info label="Connection ID" value={pretty(connection?.id)} />
                <Info label="Mode" value={pretty(connection?.mode)} />
                <Info label="Live sync" value={connection?.live_sync_enabled ? "Enabled" : "Not enabled; export upload works now"} />
                <Info label="Last error" value={pretty(connection?.last_error)} />
              </Panel>

              <Panel title="Upload evidence/export">
                {selected.upload_supported ? (
                  <div className="space-y-3">
                    <input
                      type="file"
                      accept=".csv,.json,.txt,.pdf"
                      onChange={(event) => uploadFile(event.target.files?.[0])}
                      className="text-[12px]"
                      style={{ color: TEXT }}
                    />
                    <p className="text-[12px] leading-relaxed" style={{ color: MUTED }}>
                      CSV/JSON/TXT uploads parse immediately. PDF text is accepted with limited extraction. WiseConn and Talgil can be useful through export uploads before live API credentials exist.
                    </p>
                  </div>
                ) : (
                  <InlineState title="This connector requires provider authorization before ingestion." />
                )}
              </Panel>

              {uploadResult ? (
                <Panel title="Latest upload">
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

              <Panel title="Operational steps">
                {["Test readiness", "Upload source/export", "Review mapping", "Sync evidence", "Ask AGRO-AI", "Generate report"].map((step, index) => (
                  <div key={step} className="flex gap-3 py-2">
                    <div className="h-6 w-6 rounded-full flex items-center justify-center text-[11px] font-semibold" style={{ background: BG, color: TEXT, border: `1px solid ${BORDER}` }}>{index + 1}</div>
                    <div className="text-[13px] leading-relaxed" style={{ color: MUTED }}>{step}</div>
                  </div>
                ))}
              </Panel>

              <div className="flex flex-wrap gap-2">
                <PortalButton disabled={!connection?.id || busy === "test"} onClick={testCurrent}>
                  {busy === "test" ? "Testing…" : "Test readiness"}
                </PortalButton>
                <PortalButton disabled={!connection?.id || busy === "sync"} variant="secondary" onClick={syncCurrent}>
                  {busy === "sync" ? "Syncing…" : "Sync evidence"}
                </PortalButton>
                <PortalButton variant="secondary" onClick={() => window.location.assign("/evidence")}>Open Evidence</PortalButton>
                <PortalButton variant="secondary" onClick={() => window.location.assign("/intelligence")}>Ask AGRO-AI</PortalButton>
              </div>
            </div>
          </aside>
        </div>
      ) : null}
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
    <span className="rounded-full px-3 py-1 text-[11px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: TEXT }}>
      {children}
    </span>
  );
}
