import { useCallback, useMemo } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { arrayFromUnknown, usePortalResource } from "../hooks/usePortalResource";
import { usePortalCopy } from "../hooks/usePortalCopy";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type SourceItem = {
  id: string;
  job_id?: string;
  pending?: boolean;
  filename?: string;
  provider?: string;
  source_type?: string;
  content_type?: string;
  status?: string;
  processing_status?: string;
  rows_parsed?: number;
  evidence_count?: number;
  mapping_count?: number;
  warning_count?: number;
  warnings?: string[];
  size_bytes?: number;
  checksum_verified?: boolean;
  durable_stored?: boolean;
  intelligence_ready?: boolean;
  created_at?: string;
  job_completed_at?: string;
};

type SourceDetail = {
  source?: SourceItem & { content_excerpt?: string; parsed_rows_preview?: Record<string, unknown>[] };
  evidence?: Array<{ id?: string; title?: string; summary?: string; type?: string; quality_status?: string; citation_label?: string }>;
};

function queryString(workspaceId?: string) {
  return workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
}

function statusTone(source: SourceItem): "neutral" | "good" | "warn" {
  if (["failed", "cancelled"].includes(String(source.processing_status || ""))) return "warn";
  if (source.intelligence_ready) return "good";
  return "neutral";
}

function formatBytes(value?: number) {
  const bytes = Number(value || 0);
  if (!bytes) return "—";
  if (bytes < 1_024) return `${bytes} B`;
  if (bytes < 1_048_576) return `${(bytes / 1_024).toFixed(1)} KB`;
  return `${(bytes / 1_048_576).toFixed(1)} MB`;
}

export function Sources() {
  const { currentWorkspace } = useAuth();
  const workspaceId = currentWorkspace?.id;
  const { tx } = usePortalCopy(["sources", "shared"]);
  const selectedId = new URLSearchParams(window.location.search).get("source") || "";
  const sourcesState = usePortalResource<unknown>(useCallback(() => apiClient.get(`/v1/source-library${queryString(workspaceId)}`), [workspaceId]));
  const detailState = usePortalResource<SourceDetail>(useCallback(() => selectedId ? apiClient.get(`/v1/source-library/${encodeURIComponent(selectedId)}`) : Promise.resolve({}), [selectedId]));
  const sources = arrayFromUnknown<SourceItem>(sourcesState.data, ["sources", "data_sources", "items", "data"]);
  const selected = detailState.data?.source;
  const intelligenceReady = useMemo(() => sources.filter((source) => source.intelligence_ready).length, [sources]);

  return (
    <div className="min-h-screen" style={{ background: BG }} data-tour="sources-page">
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="mb-3 flex items-center gap-2">
              <StatusBadge label={`${sources.length} sources`} tone="good" />
              <StatusBadge label={`${intelligenceReady} intelligence ready`} tone={intelligenceReady ? "good" : "neutral"} />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>{tx("Sources")}</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Your organized source library. Uploaded files remain visible with provider, processing state, evidence links, and intelligence readiness.
            </p>
          </div>
          <div className="flex gap-2">
            <PortalButton variant="secondary" onClick={() => sourcesState.refresh()}>{tx("Refresh")}</PortalButton>
            <PortalButton onClick={() => window.location.assign("/integrations")}>{tx("Add Source")}</PortalButton>
          </div>
        </div>
      </header>

      <main className="px-8 py-6 space-y-5" style={{ maxWidth: 1280 }}>
        {sourcesState.isLoading ? <InlineState title="Loading sources" /> : null}
        {sourcesState.error ? <InlineState title={sourcesState.error} /> : null}

        <section className="grid grid-cols-4 gap-4">
          <Metric label="Source files" value={String(sources.length)} />
          <Metric label="Intelligence ready" value={String(intelligenceReady)} />
          <Metric label="Evidence linked" value={String(sources.reduce((sum, source) => sum + Number(source.evidence_count || 0), 0))} />
          <Metric label="Processing" value={String(sources.filter((source) => ["queued", "retrying", "running"].includes(String(source.processing_status || ""))).length)} />
        </section>

        {selectedId ? (
          <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>Selected source</div>
                <h2 className="mt-2 text-[20px] font-semibold" style={{ color: TEXT }}>{selected?.filename || "Loading source…"}</h2>
              </div>
              <button type="button" onClick={() => window.location.assign("/sources")} className="text-[12px] font-semibold" style={{ color: "#16533C" }}>Close</button>
            </div>
            {detailState.error ? <div className="mt-4"><InlineState title={detailState.error} /></div> : null}
            {selected ? (
              <div className="mt-5 grid gap-5" style={{ gridTemplateColumns: "0.8fr 1.2fr" }}>
                <div className="space-y-3">
                  <Info label="Provider" value={selected.provider || "manual"} />
                  <Info label="Type" value={selected.source_type || "file"} />
                  <Info label="Processing" value={selected.processing_status || selected.status || "stored"} />
                  <Info label="Rows parsed" value={String(selected.rows_parsed || 0)} />
                  <Info label="Evidence linked" value={String(selected.evidence_count || 0)} />
                  <Info label="Size" value={formatBytes(selected.size_bytes)} />
                  <Info label="Durable storage" value={selected.durable_stored ? "Confirmed" : "Stored source record"} />
                  <Info label="Checksum" value={selected.checksum_verified ? "Verified" : "Not reported"} />
                  <Info label="Intelligence" value={selected.intelligence_ready ? "Available to AGRO-AI context" : "Awaiting usable content or evidence"} />
                </div>
                <div className="space-y-4">
                  <div className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                    <div className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>Content preview</div>
                    <pre className="mt-3 max-h-[260px] overflow-auto whitespace-pre-wrap text-[12px] leading-6" style={{ color: TEXT }}>{selected.content_excerpt || "No text preview is available. The source record and linked evidence remain visible."}</pre>
                  </div>
                  <div>
                    <div className="mb-2 text-[11px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>Linked evidence</div>
                    <div className="space-y-2">
                      {(detailState.data?.evidence || []).slice(0, 8).map((item, index) => (
                        <article key={item.id || index} className="rounded-xl p-3" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                          <div className="text-[13px] font-semibold" style={{ color: TEXT }}>{item.title || "Evidence record"}</div>
                          <div className="mt-1 text-[11px] leading-5" style={{ color: MUTED }}>{item.summary || "No summary"}</div>
                        </article>
                      ))}
                      {(detailState.data?.evidence || []).length === 0 ? <InlineState title="No derived evidence rows yet." detail="The original source can still remain stored and available for intelligence context when usable text is present." /> : null}
                    </div>
                  </div>
                </div>
              </div>
            ) : null}
          </section>
        ) : null}

        <section className="rounded-2xl overflow-hidden" style={{ background: SURFACE, border: `1px solid ${BORDER}` }} data-tour="source-library-table">
          <div className="grid gap-4 px-6 py-3" style={{ gridTemplateColumns: "1.6fr 0.8fr 0.8fr 0.7fr 0.8fr auto", background: BG, borderBottom: `1px solid ${BORDER}` }}>
            {["Source", "Provider", "Processing", "Evidence", "Intelligence", ""].map((label, index) => <span key={`${label}-${index}`} className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{label}</span>)}
          </div>
          {sources.length ? sources.map((source, index) => (
            <article key={source.id} className="grid items-center gap-4 px-6 py-4" style={{ gridTemplateColumns: "1.6fr 0.8fr 0.8fr 0.7fr 0.8fr auto", borderTop: index ? `1px solid ${BORDER}` : "none" }}>
              <div className="min-w-0">
                <div className="truncate text-[13px] font-semibold" style={{ color: TEXT }}>{source.filename || "Untitled source"}</div>
                <div className="mt-1 text-[11px]" style={{ color: MUTED }}>{source.source_type || "file"} · {source.rows_parsed || 0} rows · {source.created_at ? new Date(source.created_at).toLocaleString() : "time pending"}</div>
              </div>
              <span className="text-[12px]" style={{ color: MUTED }}>{source.provider || "manual"}</span>
              <StatusBadge label={source.processing_status || source.status || "stored"} tone={statusTone(source)} />
              <span className="text-[12px]" style={{ color: MUTED }}>{source.evidence_count || 0}</span>
              <StatusBadge label={source.intelligence_ready ? "Ready" : "Pending"} tone={source.intelligence_ready ? "good" : "neutral"} />
              {source.pending ? (
                <span className="text-[12px] font-semibold" style={{ color: MUTED }}>Processing</span>
              ) : (
                <button type="button" onClick={() => window.location.assign(`/sources?source=${encodeURIComponent(source.id)}`)} className="text-[12px] font-semibold" style={{ color: "#16533C" }}>View</button>
              )}
            </article>
          )) : <div className="p-6"><InlineState title="No sources yet." detail="Upload a file from Evidence or connect a system from Connectors. Stored sources will appear here." /></div>}
        </section>
      </main>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <section className="rounded-xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{label}</div><div className="mt-2 text-[24px] font-semibold" style={{ color: TEXT }}>{value}</div></section>;
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl px-4 py-3" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{label}</div><div className="mt-1 text-[13px]" style={{ color: TEXT }}>{value}</div></div>;
}
