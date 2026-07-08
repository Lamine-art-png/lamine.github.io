import { useCallback, useMemo, useState } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { arrayFromUnknown, usePortalResource } from "../hooks/usePortalResource";
import { usePortalCopy } from "../hooks/usePortalCopy";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type EvidenceItem = {
  id?: string;
  data_source_id?: string;
  title?: string;
  name?: string;
  source?: string;
  evidence_type?: string;
  domain?: string;
  quality_status?: string;
  status?: string;
  confidence?: string | number;
  summary?: string;
  citation_label?: string;
  occurred_at?: string;
  created_at?: string;
};

type SourceItem = {
  id: string;
  job_id?: string;
  pending?: boolean;
  filename?: string;
  provider?: string;
  source_type?: string;
  status?: string;
  processing_status?: string;
  rows_parsed?: number;
  evidence_count?: number;
  durable_stored?: boolean;
  intelligence_ready?: boolean;
  warning_count?: number;
  created_at?: string;
};

type Summary = {
  evidence_count?: number;
  source_count?: number;
  uploaded_files?: number;
  processing_count?: number;
  readiness_score?: number;
  readiness_level?: string;
  missing_data?: string[];
  by_type?: Record<string, number>;
  by_provider?: Record<string, number>;
  last_import_at?: string;
};

type UploadResult = {
  status?: string;
  rows_parsed?: number;
  evidence_records_created?: number;
  warnings?: string[];
  filename?: string;
  data_source_id?: string;
  processing_pending?: boolean;
};

function queryString(workspaceId?: string) {
  return workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
}

function sourceTone(source: SourceItem): "neutral" | "good" | "warn" {
  if (["failed", "cancelled"].includes(String(source.processing_status || ""))) return "warn";
  if (source.intelligence_ready) return "good";
  return "neutral";
}

export function Evidence() {
  const { currentWorkspace } = useAuth();
  const workspaceId = currentWorkspace?.id;
  const { tf } = usePortalCopy(["evidence", "sources", "shared"]);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState("");
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);

  const evidence = usePortalResource<unknown>(useCallback(() => apiClient.evidence.list(), []));
  const sourcesState = usePortalResource<unknown>(useCallback(() => apiClient.get(`/v1/source-library${queryString(workspaceId)}`), [workspaceId]));
  const summaryState = usePortalResource<Summary>(useCallback(() => apiClient.get(`/v1/source-library/summary${queryString(workspaceId)}`), [workspaceId]));
  const rows = arrayFromUnknown<EvidenceItem>(evidence.data, ["records", "evidence", "items", "data"]);
  const sources = arrayFromUnknown<SourceItem>(sourcesState.data, ["sources", "data_sources", "items", "data"]);
  const summary = summaryState.data || {};
  const sourceById = useMemo(() => new Map(sources.filter((source) => !source.pending).map((source) => [source.id, source])), [sources]);

  async function refresh() {
    await Promise.all([evidence.refresh(), sourcesState.refresh(), summaryState.refresh()]);
  }

  async function uploadFiles(files?: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    setUploadMessage("");
    setUploadResult(null);

    try {
      let totalRows = 0;
      let totalEvidence = 0;
      const warnings: string[] = [];
      let lastSourceId = "";
      let processingPending = false;

      for (const file of Array.from(files)) {
        const result = await apiClient.evidence.upload(file, undefined, workspaceId) as UploadResult;
        totalRows += Number(result.rows_parsed || 0);
        totalEvidence += Number(result.evidence_records_created || 0);
        warnings.push(...(result.warnings || []));
        lastSourceId = result.data_source_id || lastSourceId;
        processingPending = Boolean(result.processing_pending) || processingPending;
      }

      setUploadResult({
        status: processingPending ? "processing" : "uploaded",
        rows_parsed: totalRows,
        evidence_records_created: totalEvidence,
        warnings,
        data_source_id: lastSourceId,
        processing_pending: processingPending,
      });
      setUploadMessage(
        processingPending
          ? tf("Uploaded {files} file(s). Secure storage is complete and processing is still running.", { files: files.length })
          : tf("Uploaded {files} file(s). Created {evidence} evidence records from {rows} parsed rows.", { files: files.length, evidence: totalEvidence, rows: totalRows }),
      );
      await refresh();
    } catch (error) {
      setUploadMessage(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }} data-tour="evidence-page">
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <StatusBadge label="Evidence Store" tone="good" />
              <StatusBadge label={tf("{score}% readiness", { score: summary.readiness_score ?? 0 })} tone={(summary.readiness_score || 0) > 50 ? "good" : "warn"} />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Evidence</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Uploaded source files stay visible here. AGRO-AI organizes each source, derives evidence records when possible, and keeps provenance linked back to the original file.
            </p>
          </div>
          <div className="flex gap-2">
            <PortalButton variant="secondary" onClick={refresh}>Refresh</PortalButton>
            <PortalButton onClick={() => window.location.assign("/integrations")}>Open Connectors</PortalButton>
          </div>
        </div>
      </header>

      <div className="px-8 py-6 space-y-5" style={{ maxWidth: 1220 }}>
        <section className="rounded-2xl p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex items-start justify-between gap-5">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>Fast upload</div>
              <h2 className="text-[18px] font-semibold mb-2" style={{ color: TEXT }}>Drop fragmented customer files here first.</h2>
              <p className="text-[13px] leading-relaxed max-w-2xl" style={{ color: MUTED }}>
                AGRO-AI stores the source, tracks processing, parses supported content, links derived evidence, and makes available source context usable by workspace intelligence.
              </p>
            </div>

            <label className="min-w-[260px] rounded-2xl p-5 cursor-pointer text-center" style={{ background: BG, border: `1px dashed ${BORDER}` }}>
              <div className="text-[14px] font-semibold mb-1" style={{ color: TEXT }}>
                {uploading ? "Uploading…" : "Choose files"}
              </div>
              <div className="text-[11px] mb-3" style={{ color: MUTED }}>CSV, JSON, TXT, PDF</div>
              <input
                type="file"
                multiple
                accept=".csv,.json,.txt,.pdf"
                disabled={uploading}
                onChange={(event) => uploadFiles(event.target.files)}
                className="text-[11px] max-w-[220px]"
                style={{ color: MUTED }}
              />
            </label>
          </div>

          {uploadMessage ? (
            <div className="mt-4">
              <InlineState title={uploadMessage} detail={(uploadResult?.warnings || []).join("; ") || undefined} />
            </div>
          ) : null}
        </section>

        {evidence.isLoading || sourcesState.isLoading ? <InlineState title="Loading evidence" /> : null}
        {evidence.error ? <InlineState title={evidence.error} /> : null}
        {sourcesState.error ? <InlineState title={sourcesState.error} /> : null}
        {summaryState.error ? <InlineState title={summaryState.error} /> : null}

        <section className="grid grid-cols-4 gap-4">
          <Metric label="Evidence records" value={String(summary.evidence_count ?? rows.length)} />
          <Metric label="Source files" value={String(summary.source_count ?? sources.length)} />
          <Metric label="Readiness" value={`${summary.readiness_score ?? 0}%`} />
          <Metric label="Evidence types" value={String(Object.keys(summary.by_type || {}).length)} />
        </section>

        <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }} data-tour="evidence-source-library">
          <div className="flex items-center justify-between gap-4 mb-4">
            <div>
              <h2 className="text-[18px] font-semibold" style={{ color: TEXT }}>Uploaded source files</h2>
              <p className="mt-1 text-[12px]" style={{ color: MUTED }}>Your original uploads remain organized as sources; evidence records below stay linked to them.</p>
            </div>
            <PortalButton variant="secondary" onClick={() => window.location.assign("/sources")}>Open source library</PortalButton>
          </div>
          <div className="space-y-2">
            {sources.length ? sources.slice(0, 8).map((source) => (
              <article key={source.id} className="grid items-center gap-4 rounded-xl px-4 py-3" style={{ gridTemplateColumns: "1.6fr 0.8fr 0.7fr 0.7fr auto", background: BG, border: `1px solid ${BORDER}` }}>
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-semibold" style={{ color: TEXT }}>{source.filename || "Untitled source"}</div>
                  <div className="mt-1 text-[11px]" style={{ color: MUTED }}>{source.provider || "manual"} · {source.source_type || "file"}</div>
                </div>
                <span className="text-[12px]" style={{ color: MUTED }}>{source.rows_parsed || 0} rows</span>
                <span className="text-[12px]" style={{ color: MUTED }}>{source.evidence_count || 0} evidence</span>
                <StatusBadge label={source.intelligence_ready ? "Intelligence ready" : (source.processing_status || source.status || "stored")} tone={sourceTone(source)} />
                {source.pending ? (
                  <span className="text-[12px] font-semibold" style={{ color: MUTED }}>Processing</span>
                ) : (
                  <button type="button" onClick={() => window.location.assign(`/sources?source=${encodeURIComponent(source.id)}`)} className="text-[12px] font-semibold" style={{ color: "#16533C" }}>View</button>
                )}
              </article>
            )) : <InlineState title="No uploaded source files yet." detail="Upload a file above or use Connectors. The original source will appear here after secure storage." />}
          </div>
        </section>

        {(summary.missing_data || []).length ? (
          <section className="rounded-xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>Missing data</div>
            <div className="grid grid-cols-2 gap-2">
              {(summary.missing_data || []).map((item) => (
                <div key={item} className="rounded-lg px-4 py-3 text-[13px]" style={{ background: BG, color: MUTED }}>{item}</div>
              ))}
            </div>
          </section>
        ) : null}

        <section className="rounded-xl overflow-hidden" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="grid px-6 py-2.5 gap-4" style={{ gridTemplateColumns: "1.4fr 1fr 1fr 1fr auto", borderBottom: `1px solid ${BORDER}`, background: BG }}>
            {["Evidence", "Type", "Source", "Time", "Quality"].map((header) => (
              <span key={header} className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{header}</span>
            ))}
          </div>

          {rows.length ? rows.map((row, index) => {
            const source = row.data_source_id ? sourceById.get(row.data_source_id) : undefined;
            return (
              <div key={row.id || index} className="grid px-6 py-4 gap-4 items-center" style={{ gridTemplateColumns: "1.4fr 1fr 1fr 1fr auto", borderTop: index > 0 ? `1px solid ${BORDER}` : "none" }}>
                <div>
                  <div className="text-[13px] font-semibold" style={{ color: TEXT }}>{row.title || row.name || "Evidence item"}</div>
                  <div className="text-[11px] leading-relaxed mt-1" style={{ color: MUTED }}>{row.summary || "No summary returned."}</div>
                </div>
                <span className="text-[12px]" style={{ color: MUTED }}>{row.evidence_type || row.domain || "unknown"}</span>
                <span className="text-[12px]" style={{ color: MUTED }}>{source?.filename || row.citation_label || row.source || "source"}</span>
                <span className="text-[12px]" style={{ color: MUTED }}>{row.occurred_at || row.created_at ? new Date(row.occurred_at || row.created_at || "").toLocaleString() : "No timestamp"}</span>
                <StatusBadge label={row.quality_status || row.status || "usable"} tone={(row.quality_status || row.status) === "usable" ? "good" : "warn"} />
              </div>
            );
          }) : (
            <div className="p-6">
              <InlineState title="No derived evidence records yet." detail="A source file can still be securely stored even when it produces no structured evidence rows. Check Uploaded source files above." />
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <section className="rounded-xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>{label}</div>
      <div className="text-[24px] font-semibold" style={{ color: TEXT }}>{value}</div>
    </section>
  );
}
