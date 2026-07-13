import { useCallback, useMemo, useState } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { arrayFromUnknown, usePortalResource } from "../hooks/usePortalResource";
import { usePortalCopy } from "../hooks/usePortalCopy";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type EvidenceItem = {
  id?: string;
  workspace_id?: string;
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
  const allRows = arrayFromUnknown<EvidenceItem>(evidence.data, ["records", "evidence", "items", "data"]);
  const rows = useMemo(
    () => workspaceId ? allRows.filter((row) => row.workspace_id === workspaceId) : [],
    [allRows, workspaceId],
  );
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
    <div className="min-h-full" style={{ background: BG }} data-tour="evidence-page">
      <header className="px-4 py-5 sm:px-8 sm:py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <StatusBadge label="Evidence Store" tone="good" />
              <StatusBadge label={tf("{score}% readiness", { score: summary.readiness_score ?? 0 })} tone={(summary.readiness_score || 0) > 50 ? "good" : "warn"} />
            </div>
            <h1 className="text-[26px] font-semibold tracking-tight sm:text-[30px]" style={{ color: TEXT }}>Evidence</h1>
            <p className="mt-2 max-w-3xl text-[13px] leading-relaxed sm:text-[14px]" style={{ color: MUTED }}>
              Uploaded source files stay visible here. AGRO-AI organizes each source, derives evidence records when possible, and keeps provenance linked back to the original file.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 sm:flex-nowrap">
            <PortalButton variant="secondary" onClick={refresh}>Refresh</PortalButton>
            <PortalButton onClick={() => window.location.assign("/integrations")}>Open Connectors</PortalButton>
          </div>
        </div>
      </header>

      <div className="space-y-4 px-4 py-4 sm:space-y-5 sm:px-8 sm:py-6" style={{ maxWidth: 1220 }}>
        <section className="rounded-2xl p-4 sm:p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-5">
            <div className="min-w-0">
              <div className="mb-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>Fast upload</div>
              <h2 className="mb-2 text-[17px] font-semibold sm:text-[18px]" style={{ color: TEXT }}>Drop fragmented customer files here first.</h2>
              <p className="max-w-2xl text-[13px] leading-relaxed" style={{ color: MUTED }}>
                AGRO-AI stores the source, tracks processing, parses supported content, links derived evidence, and makes available source context usable by workspace intelligence.
              </p>
            </div>

            <label className="w-full cursor-pointer rounded-2xl p-4 text-center sm:w-auto sm:min-w-[260px] sm:p-5" style={{ background: BG, border: `1px dashed ${BORDER}` }}>
              <div className="mb-1 text-[14px] font-semibold" style={{ color: TEXT }}>
                {uploading ? "Uploading…" : "Choose files"}
              </div>
              <div className="mb-3 text-[11px]" style={{ color: MUTED }}>CSV, JSON, TXT, PDF</div>
              <input
                type="file"
                multiple
                accept=".csv,.json,.txt,.pdf"
                disabled={uploading}
                onChange={(event) => uploadFiles(event.target.files)}
                className="max-w-full text-[11px] sm:max-w-[220px]"
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

        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
          <Metric label="Evidence records" value={String(summary.evidence_count ?? rows.length)} />
          <Metric label="Source files" value={String(summary.source_count ?? sources.length)} />
          <Metric label="Readiness" value={`${summary.readiness_score ?? 0}%`} />
          <Metric label="Evidence types" value={String(Object.keys(summary.by_type || {}).length)} />
        </section>

        <section className="rounded-2xl p-4 sm:p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }} data-tour="evidence-source-library">
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
            <div className="min-w-0">
              <h2 className="text-[17px] font-semibold sm:text-[18px]" style={{ color: TEXT }}>Uploaded source files</h2>
              <p className="mt-1 text-[12px] leading-relaxed" style={{ color: MUTED }}>Your original uploads remain organized as sources; evidence records below stay linked to them.</p>
            </div>
            <div className="flex-shrink-0"><PortalButton variant="secondary" onClick={() => window.location.assign("/sources")}>Open source library</PortalButton></div>
          </div>
          <div className="space-y-2">
            {sources.length ? sources.slice(0, 8).map((source) => (
              <article key={source.id} className="rounded-xl p-3 sm:p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="break-words text-[13px] font-semibold" style={{ color: TEXT }}>{source.filename || "Untitled source"}</div>
                    <div className="mt-1 text-[11px]" style={{ color: MUTED }}>{source.provider || "manual"} · {source.source_type || "file"}</div>
                  </div>
                  <StatusBadge label={source.intelligence_ready ? "Intelligence ready" : (source.processing_status || source.status || "stored")} tone={sourceTone(source)} />
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px]" style={{ color: MUTED }}>
                  <span>{source.rows_parsed || 0} rows</span>
                  <span>{source.evidence_count || 0} evidence</span>
                  {source.pending ? (
                    <span className="font-semibold">Processing</span>
                  ) : (
                    <button type="button" onClick={() => window.location.assign(`/sources?source=${encodeURIComponent(source.id)}`)} className="font-semibold" style={{ color: "#16533C" }}>View</button>
                  )}
                </div>
              </article>
            )) : <InlineState title="No uploaded source files yet." detail="Upload a file above or use Connectors. The original source will appear here after secure storage." />}
          </div>
        </section>

        {(summary.missing_data || []).length ? (
          <section className="rounded-xl p-4 sm:p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="mb-3 text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>Missing data</div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {(summary.missing_data || []).map((item) => (
                <div key={item} className="rounded-lg px-4 py-3 text-[13px]" style={{ background: BG, color: MUTED }}>{item}</div>
              ))}
            </div>
          </section>
        ) : null}

        <section className="overflow-hidden rounded-xl" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="hidden md:block">
            <div className="grid gap-4 px-6 py-2.5" style={{ gridTemplateColumns: "1.4fr 1fr 1fr 1fr auto", borderBottom: `1px solid ${BORDER}`, background: BG }}>
              {["Evidence", "Type", "Source", "Time", "Quality"].map((header) => (
                <span key={header} className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{header}</span>
              ))}
            </div>
            {rows.length ? rows.map((row, index) => {
              const source = row.data_source_id ? sourceById.get(row.data_source_id) : undefined;
              return (
                <div key={row.id || index} className="grid items-center gap-4 px-6 py-4" style={{ gridTemplateColumns: "1.4fr 1fr 1fr 1fr auto", borderTop: index > 0 ? `1px solid ${BORDER}` : "none" }}>
                  <EvidencePrimary row={row} />
                  <span className="text-[12px]" style={{ color: MUTED }}>{row.evidence_type || row.domain || "unknown"}</span>
                  <span className="text-[12px]" style={{ color: MUTED }}>{source?.filename || row.citation_label || row.source || "source"}</span>
                  <span className="text-[12px]" style={{ color: MUTED }}>{row.occurred_at || row.created_at ? new Date(row.occurred_at || row.created_at || "").toLocaleString() : "No timestamp"}</span>
                  <StatusBadge label={row.quality_status || row.status || "usable"} tone={(row.quality_status || row.status) === "usable" ? "good" : "warn"} />
                </div>
              );
            }) : <div className="p-6"><InlineState title="No derived evidence records yet." detail="A source file can still be securely stored even when it produces no structured evidence rows. Check Uploaded source files above." /></div>}
          </div>

          <div className="divide-y md:hidden" style={{ borderColor: BORDER }}>
            {rows.length ? rows.map((row, index) => {
              const source = row.data_source_id ? sourceById.get(row.data_source_id) : undefined;
              return (
                <article key={row.id || index} className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <EvidencePrimary row={row} />
                    <StatusBadge label={row.quality_status || row.status || "usable"} tone={(row.quality_status || row.status) === "usable" ? "good" : "warn"} />
                  </div>
                  <div className="mt-3 grid grid-cols-1 gap-2 min-[420px]:grid-cols-2">
                    <MobileDatum label="Type" value={row.evidence_type || row.domain || "unknown"} />
                    <MobileDatum label="Source" value={source?.filename || row.citation_label || row.source || "source"} />
                  </div>
                  <div className="mt-3 text-[11px]" style={{ color: MUTED }}>{row.occurred_at || row.created_at ? new Date(row.occurred_at || row.created_at || "").toLocaleString() : "No timestamp"}</div>
                </article>
              );
            }) : <div className="p-4"><InlineState title="No derived evidence records yet." detail="A source file can still be securely stored even when it produces no structured evidence rows. Check Uploaded source files above." /></div>}
          </div>
        </section>
      </div>
    </div>
  );
}

function EvidencePrimary({ row }: { row: EvidenceItem }) {
  return (
    <div className="min-w-0">
      <div className="break-words text-[13px] font-semibold" style={{ color: TEXT }}>{row.title || row.name || "Evidence item"}</div>
      <div className="mt-1 break-words text-[11px] leading-relaxed" style={{ color: MUTED }}>{row.summary || "No summary returned."}</div>
    </div>
  );
}

function MobileDatum({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg px-3 py-2" style={{ background: BG }}>
      <div className="text-[9px] font-semibold uppercase tracking-wider" style={{ color: MUTED }}>{label}</div>
      <div className="mt-1 break-words text-[12px]" style={{ color: TEXT }}>{value}</div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <section className="rounded-xl p-4 sm:p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="mb-2 text-[9px] font-semibold uppercase tracking-widest sm:text-[10px]" style={{ color: MUTED }}>{label}</div>
      <div className="text-[22px] font-semibold sm:text-[24px]" style={{ color: TEXT }}>{value}</div>
    </section>
  );
}
