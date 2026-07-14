import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { AlertTriangle, Trash2, Upload, X } from "lucide-react";
import { apiClient } from "../api/client";
import { uploadEvidenceBatch } from "../api/evidenceBatchUpload";
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

function openSource(source: SourceItem) {
  if (source.pending) return;
  window.location.assign(`/sources?source=${encodeURIComponent(source.id)}`);
}

export function Sources() {
  const { currentWorkspace, currentOrganization } = useAuth();
  const workspaceId = currentWorkspace?.id;
  const { tx } = usePortalCopy(["sources", "shared"]);
  const selectedId = new URLSearchParams(window.location.search).get("source") || "";
  const sourcesState = usePortalResource<unknown>(useCallback(() => apiClient.get(`/v1/source-library${queryString(workspaceId)}`), [workspaceId]));
  const detailState = usePortalResource<SourceDetail>(useCallback(() => selectedId ? apiClient.get(`/v1/source-library/${encodeURIComponent(selectedId)}`) : Promise.resolve({}), [selectedId]));
  const sources = arrayFromUnknown<SourceItem>(sourcesState.data, ["sources", "data_sources", "items", "data"]);
  const selected = detailState.data?.source;
  const intelligenceReady = useMemo(() => sources.filter((source) => source.intelligence_ready).length, [sources]);
  const processingCount = useMemo(() => sources.filter((source) => ["queued", "retrying", "running"].includes(String(source.processing_status || ""))).length, [sources]);
  const role = String(currentOrganization?.role || "viewer");
  const canManageSources = ["owner", "admin", "manager", "operator"].includes(role);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState("");
  const [uploadWarnings, setUploadWarnings] = useState<string[]>([]);
  const [deleteCandidate, setDeleteCandidate] = useState<SourceItem | null>(null);
  const [deletingId, setDeletingId] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [dragging, setDragging] = useState(false);

  const refreshSources = useCallback(async (silent = false) => {
    await Promise.all([
      sourcesState.refresh({ silent }),
      selectedId ? detailState.refresh({ silent }) : Promise.resolve(),
    ]);
  }, [detailState.refresh, selectedId, sourcesState.refresh]);

  useEffect(() => {
    if (!workspaceId || processingCount <= 0) return;
    const timer = window.setInterval(() => { void refreshSources(true); }, 2_500);
    return () => window.clearInterval(timer);
  }, [processingCount, refreshSources, workspaceId]);

  async function uploadFiles(files: File[]) {
    if (!files.length || uploading || !canManageSources) return;
    setUploading(true);
    setUploadWarnings([]);
    setActionMessage("");
    setUploadMessage(`Securely storing 0 of ${files.length} files…`);
    try {
      const result = await uploadEvidenceBatch(files, workspaceId, {
        concurrency: 4,
        onProgress: ({ total, completed, stored, failed }) => {
          const failureNote = failed ? ` · ${failed} failed` : "";
          setUploadMessage(`Securely stored ${stored} of ${total} files · ${completed} completed${failureNote}`);
        },
      });
      const failures = result.failures.map((failure) => `${failure.filename}: ${failure.message}`);
      setUploadWarnings([...result.warnings, ...failures]);
      if (result.failed) {
        setUploadMessage(`${result.stored} of ${result.total} files were securely stored. ${result.failed} failed and can be selected again.`);
      } else {
        setUploadMessage(`All ${result.total} files are securely stored. You can upload another batch now while AGRO-AI processes these files.`);
      }
      await refreshSources();
    } catch (error) {
      setUploadMessage(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function handleDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragging(false);
    if (!canManageSources || uploading) return;
    void uploadFiles(Array.from(event.dataTransfer.files || []));
  }

  async function confirmDelete() {
    if (!deleteCandidate || deletingId) return;
    const candidate = deleteCandidate;
    setDeletingId(candidate.id);
    setActionMessage("");
    try {
      const result = await apiClient.request<{ filename?: string; evidence_deleted?: number }>(
        `/v1/source-library/${encodeURIComponent(candidate.id)}`,
        { method: "DELETE" },
      );
      setDeleteCandidate(null);
      setActionMessage(`${result.filename || candidate.filename || "File"} was deleted with ${Number(result.evidence_deleted || 0)} linked evidence record(s).`);
      if (selectedId === candidate.id) {
        window.location.assign("/sources");
        return;
      }
      await refreshSources();
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : "The file could not be deleted.");
    } finally {
      setDeletingId("");
    }
  }

  return (
    <div className="min-h-full" style={{ background: BG }} data-tour="sources-page">
      <header className="px-4 py-5 sm:px-8 sm:py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <StatusBadge label={`${sources.length} sources`} tone="good" />
              <StatusBadge label={`${intelligenceReady} intelligence ready`} tone={intelligenceReady ? "good" : "neutral"} />
            </div>
            <h1 className="text-[26px] font-semibold tracking-tight sm:text-[30px]" style={{ color: TEXT }}>{tx("Sources")}</h1>
            <p className="mt-2 max-w-3xl text-[13px] leading-relaxed sm:text-[14px]" style={{ color: MUTED }}>
              Your organized source library. Add more files whenever you need them, review processing, and remove files that no longer belong in this operation.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 sm:flex-nowrap">
            <PortalButton variant="secondary" onClick={() => refreshSources()}>{tx("Refresh")}</PortalButton>
            {canManageSources ? <PortalButton onClick={() => fileInputRef.current?.click()}>Upload files</PortalButton> : null}
            <PortalButton variant="secondary" onClick={() => window.location.assign("/integrations")}>Connect system</PortalButton>
          </div>
        </div>
      </header>

      <main className="space-y-4 px-4 py-4 sm:space-y-5 sm:px-8 sm:py-6" style={{ maxWidth: 1280 }}>
        {canManageSources ? (
          <section
            className="rounded-2xl p-5 sm:p-6"
            style={{ background: dragging ? "#F0F8E9" : SURFACE, border: `1px ${dragging ? "solid #77A861" : "dashed #AAB8AE"}` }}
            onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
            onDrop={handleDrop}
            data-repeat-source-upload
          >
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex min-w-0 items-start gap-4">
                <span className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl" style={{ background: "#EAF5E1", color: "#245F3E" }}><Upload className="h-5 w-5" /></span>
                <div className="min-w-0">
                  <h2 className="text-[17px] font-semibold" style={{ color: TEXT }}>Add more files anytime</h2>
                  <p className="mt-1 max-w-3xl text-[12px] leading-6" style={{ color: MUTED }}>
                    Drop another batch here or choose files. New uploads are added to this operation; they do not replace the files already stored.
                  </p>
                  <div className="mt-2 text-[11px]" style={{ color: MUTED }}>CSV, JSON, TXT, PDF · multiple files supported · repeat as often as needed</div>
                </div>
              </div>
              <PortalButton disabled={uploading} onClick={() => fileInputRef.current?.click()}>{uploading ? "Uploading…" : sources.length ? "Upload more files" : "Choose files"}</PortalButton>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".csv,.json,.txt,.pdf"
              className="sr-only"
              disabled={uploading}
              onChange={(event) => { void uploadFiles(Array.from(event.currentTarget.files || [])); }}
              data-source-repeat-file-input
            />
            {uploadMessage ? <div className="mt-4"><InlineState title={uploadMessage} detail={uploadWarnings.join("; ") || undefined} /></div> : null}
          </section>
        ) : (
          <InlineState title="Read-only source access" detail="Ask an operator, manager, admin, or owner to upload or delete files." />
        )}

        {actionMessage ? <InlineState title={actionMessage} /> : null}
        {sourcesState.isLoading ? <InlineState title="Loading sources" /> : null}
        {sourcesState.error ? <InlineState title={sourcesState.error} /> : null}

        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
          <Metric label="Source files" value={String(sources.length)} />
          <Metric label="Intelligence ready" value={String(intelligenceReady)} />
          <Metric label="Evidence linked" value={String(sources.reduce((sum, source) => sum + Number(source.evidence_count || 0), 0))} />
          <Metric label="Processing" value={String(processingCount)} />
        </section>

        {deleteCandidate ? (
          <section className="rounded-2xl p-4 sm:p-5" style={{ background: "#FFF8ED", border: "1px solid #E7C98B" }} role="alertdialog" aria-label="Confirm file deletion">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex min-w-0 items-start gap-3">
                <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0" style={{ color: "#9A6511" }} />
                <div>
                  <h2 className="text-[15px] font-semibold" style={{ color: TEXT }}>Delete {deleteCandidate.filename || "this file"}?</h2>
                  <p className="mt-1 text-[12px] leading-5" style={{ color: MUTED }}>
                    This permanently removes the stored file and its derived evidence from this operation. Existing reports and past chat answers are not rewritten.
                  </p>
                </div>
              </div>
              <div className="flex flex-shrink-0 gap-2">
                <PortalButton variant="secondary" disabled={Boolean(deletingId)} onClick={() => setDeleteCandidate(null)}><X className="mr-2 inline h-4 w-4" />Cancel</PortalButton>
                <PortalButton disabled={Boolean(deletingId)} onClick={() => void confirmDelete()}><Trash2 className="mr-2 inline h-4 w-4" />{deletingId ? "Deleting…" : deleteCandidate.pending ? "Cancel & delete" : "Delete permanently"}</PortalButton>
              </div>
            </div>
          </section>
        ) : null}

        {selectedId ? (
          <section className="rounded-2xl p-4 sm:p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>Selected source</div>
                <h2 className="mt-2 break-words text-[18px] font-semibold sm:text-[20px]" style={{ color: TEXT }}>{selected?.filename || "Loading source…"}</h2>
              </div>
              <div className="flex flex-shrink-0 items-center gap-3">
                {selected && canManageSources ? <button type="button" onClick={() => setDeleteCandidate(selected)} className="text-[12px] font-semibold" style={{ color: "#A12A2A" }}>Delete</button> : null}
                <button type="button" onClick={() => window.location.assign("/sources")} className="text-[12px] font-semibold" style={{ color: "#16533C" }}>Close</button>
              </div>
            </div>
            {detailState.error ? <div className="mt-4"><InlineState title={detailState.error} /></div> : null}
            {selected ? (
              <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-[0.8fr_1.2fr] lg:gap-5">
                <div className="grid grid-cols-1 gap-2 min-[420px]:grid-cols-2 lg:block lg:space-y-3">
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
                <div className="min-w-0 space-y-4">
                  <div className="min-w-0 rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                    <div className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>Content preview</div>
                    <pre className="mt-3 max-h-[260px] max-w-full overflow-auto whitespace-pre-wrap break-words text-[12px] leading-6" style={{ color: TEXT }}>{selected.content_excerpt || "No text preview is available. The source record and linked evidence remain visible."}</pre>
                  </div>
                  <div>
                    <div className="mb-2 text-[11px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>Linked evidence</div>
                    <div className="space-y-2">
                      {(detailState.data?.evidence || []).slice(0, 8).map((item, index) => (
                        <article key={item.id || index} className="rounded-xl p-3" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                          <div className="break-words text-[13px] font-semibold" style={{ color: TEXT }}>{item.title || "Evidence record"}</div>
                          <div className="mt-1 break-words text-[11px] leading-5" style={{ color: MUTED }}>{item.summary || "No summary"}</div>
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

        <section className="overflow-hidden rounded-2xl" style={{ background: SURFACE, border: `1px solid ${BORDER}` }} data-tour="source-library-table">
          <div className="hidden md:block">
            <div className="grid gap-4 px-6 py-3" style={{ gridTemplateColumns: "1.6fr 0.8fr 0.8fr 0.7fr 0.8fr auto", background: BG, borderBottom: `1px solid ${BORDER}` }}>
              {["Source", "Provider", "Processing", "Evidence", "Intelligence", "Actions"].map((label) => <span key={label} className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{label}</span>)}
            </div>
            {sources.length ? sources.map((source, index) => (
              <article key={source.id} className="grid items-center gap-4 px-6 py-4" style={{ gridTemplateColumns: "1.6fr 0.8fr 0.8fr 0.7fr 0.8fr auto", borderTop: index ? `1px solid ${BORDER}` : "none" }}>
                <SourceName source={source} />
                <span className="text-[12px]" style={{ color: MUTED }}>{source.provider || "manual"}</span>
                <StatusBadge label={source.processing_status || source.status || "stored"} tone={statusTone(source)} />
                <span className="text-[12px]" style={{ color: MUTED }}>{source.evidence_count || 0}</span>
                <StatusBadge label={source.intelligence_ready ? "Ready" : "Pending"} tone={source.intelligence_ready ? "good" : "neutral"} />
                <div className="flex items-center justify-end gap-3">
                  {source.pending ? <span className="text-[12px] font-semibold" style={{ color: MUTED }}>Processing</span> : <button type="button" onClick={() => openSource(source)} className="text-[12px] font-semibold" style={{ color: "#16533C" }}>View</button>}
                  {canManageSources ? <button type="button" onClick={() => setDeleteCandidate(source)} className="text-[12px] font-semibold" style={{ color: "#A12A2A" }}>{source.pending ? "Cancel" : "Delete"}</button> : null}
                </div>
              </article>
            )) : <div className="p-6"><InlineState title="No sources yet." detail="Upload one or many files above, then return anytime to add another batch." /></div>}
          </div>

          <div className="divide-y md:hidden" style={{ borderColor: BORDER }}>
            {sources.length ? sources.map((source) => (
              <article key={source.id} className="p-4" onClick={() => openSource(source)}>
                <div className="flex items-start justify-between gap-3">
                  <SourceName source={source} />
                  <StatusBadge label={source.processing_status || source.status || "stored"} tone={statusTone(source)} />
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]" style={{ color: MUTED }}>
                  <MobileDatum label="Provider" value={source.provider || "manual"} />
                  <MobileDatum label="Evidence" value={String(source.evidence_count || 0)} />
                  <MobileDatum label="Rows parsed" value={String(source.rows_parsed || 0)} />
                  <MobileDatum label="Intelligence" value={source.intelligence_ready ? "Ready" : "Pending"} />
                </div>
                <div className="mt-3 flex items-center justify-between gap-3">
                  <span className="text-[11px]" style={{ color: MUTED }}>{source.created_at ? new Date(source.created_at).toLocaleString() : "time pending"}</span>
                  <div className="flex items-center gap-3">
                    <span className="text-[12px] font-semibold" style={{ color: source.pending ? MUTED : "#16533C" }}>{source.pending ? "Processing" : "View"}</span>
                    {canManageSources ? <button type="button" onClick={(event) => { event.stopPropagation(); setDeleteCandidate(source); }} className="text-[12px] font-semibold" style={{ color: "#A12A2A" }}>{source.pending ? "Cancel" : "Delete"}</button> : null}
                  </div>
                </div>
              </article>
            )) : <div className="p-4"><InlineState title="No sources yet." detail="Upload one or many files above, then return anytime to add another batch." /></div>}
          </div>
        </section>
      </main>
    </div>
  );
}

function SourceName({ source }: { source: SourceItem }) {
  return (
    <div className="min-w-0">
      <div className="break-words text-[13px] font-semibold" style={{ color: TEXT }}>{source.filename || "Untitled source"}</div>
      <div className="mt-1 text-[11px]" style={{ color: MUTED }}>{source.source_type || "file"} · {source.rows_parsed || 0} rows</div>
    </div>
  );
}

function MobileDatum({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg px-3 py-2" style={{ background: BG }}>
      <div className="text-[9px] font-semibold uppercase tracking-wider" style={{ color: MUTED }}>{label}</div>
      <div className="mt-1 break-words text-[12px] font-medium" style={{ color: TEXT }}>{value}</div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <section className="rounded-xl p-4 sm:p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="text-[9px] font-semibold uppercase tracking-widest sm:text-[10px]" style={{ color: MUTED }}>{label}</div><div className="mt-2 text-[22px] font-semibold sm:text-[24px]" style={{ color: TEXT }}>{value}</div></section>;
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl px-4 py-3" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{label}</div><div className="mt-1 break-words text-[13px]" style={{ color: TEXT }}>{value}</div></div>;
}
