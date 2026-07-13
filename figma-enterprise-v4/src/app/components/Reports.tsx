import { useCallback, useMemo, useState } from "react";
import { apiClient, ReportFactoryPayload } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { arrayFromUnknown, usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type Report = {
  id?: string;
  workspace_id?: string;
  title?: string;
  filename?: string;
  artifact_type?: string;
  content_type?: string;
  created_at?: string;
  metadata_json?: Record<string, unknown>;
};

function text(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return fallback;
  }
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function Reports() {
  const { currentWorkspace } = useAuth();
  const workspaceId = currentWorkspace?.id;
  const reports = usePortalResource<unknown>(useCallback(() => apiClient.reports.list(), []));
  const allRows = arrayFromUnknown<Report>(reports.data, ["reports", "items", "artifacts", "data"]);
  const rows = useMemo(
    () => workspaceId ? allRows.filter((report) => report.workspace_id === workspaceId) : [],
    [allRows, workspaceId],
  );
  const [reportType, setReportType] = useState("evidence_summary");
  const [format, setFormat] = useState<"markdown" | "pdf">("pdf");
  const [message, setMessage] = useState("");
  const [preview, setPreview] = useState("");
  const [factoryPreview, setFactoryPreview] = useState<any>(null);
  const [factoryType, setFactoryType] = useState<ReportFactoryPayload["report_type"]>("executive_brief");
  const [factoryAudience, setFactoryAudience] = useState<ReportFactoryPayload["audience"]>("owner");
  const [artifact, setArtifact] = useState<Report | null>(null);
  const [factoryRequest, setFactoryRequest] = useState<ReportFactoryPayload | null>(null);
  const [loading, setLoading] = useState(false);

  async function generate() {
    setLoading(true);
    setMessage("");
    setPreview("");

    try {
      const result = await apiClient.reports.generate({ report_type: reportType, format, workspace_id: workspaceId }) as any;
      setArtifact(result.artifact || null);
      setPreview(result.preview || "");
      setMessage("Report generated.");
      await reports.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Report generation failed.");
    } finally {
      setLoading(false);
    }
  }

  async function download(id?: string) {
    if (!id) return;
    const blob = await apiClient.artifacts.download(id);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = artifact?.filename || "agro-ai-report";
    link.click();
    URL.revokeObjectURL(url);
  }

  async function generateFactoryPreview() {
    setLoading(true);
    setMessage("");

    try {
      const payload: ReportFactoryPayload = { report_type: factoryType, audience: factoryAudience, workspace_id: workspaceId };
      const result = await apiClient.reportFactory.generate(payload) as any;
      setFactoryPreview(result.report || null);
      setFactoryRequest(payload);
      setMessage("Report factory preview generated.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Report factory failed.");
    } finally {
      setLoading(false);
    }
  }

  async function downloadFactoryPdf() {
    setLoading(true);
    setMessage("");

    try {
      const payload: ReportFactoryPayload = factoryRequest || { report_type: factoryType, audience: factoryAudience, workspace_id: workspaceId };
      if (!factoryRequest) {
        const result = await apiClient.reportFactory.generate(payload) as any;
        setFactoryPreview(result.report || null);
        setFactoryRequest(payload);
      }
      const blob = await apiClient.reportFactory.pdf(payload);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `agro-ai-${payload.report_type}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setMessage("Report preview ready. PDF export needs retry.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <StatusBadge label="Reports" tone="good" />
              <StatusBadge label={`${rows.length} artifacts`} />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Reports</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Generate document-ready evidence summaries, executive briefs, compliance packets, and operator-facing water reports from the current workspace.
            </p>
          </div>
          <PortalButton variant="secondary" onClick={() => reports.refresh()}>Refresh</PortalButton>
        </div>
      </header>

      <main className="px-8 py-6 space-y-5" style={{ maxWidth: 1220 }}>
        {reports.error ? <InlineState title={reports.error} /> : null}
        {message ? <InlineState title={message} /> : null}

        <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="grid grid-cols-3 gap-3">
            <label className="text-[12px]" style={{ color: MUTED }}>
              Report type
              <select value={reportType} onChange={(event) => setReportType(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                <option value="evidence_summary">Evidence summary</option>
                <option value="water_decision">Water decision</option>
                <option value="assurance_packet">Assurance packet</option>
                <option value="water_agency_packet">Water agency packet</option>
                <option value="lender_risk_packet">Lender risk packet</option>
                <option value="farmer_summary">Farmer summary</option>
              </select>
            </label>

            <label className="text-[12px]" style={{ color: MUTED }}>
              Format
              <select value={format} onChange={(event) => setFormat(event.target.value as "markdown" | "pdf")} className="mt-1 h-10 w-full rounded-lg px-3 outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                <option value="pdf">PDF</option>
                <option value="markdown">Markdown</option>
              </select>
            </label>

            <div className="flex items-end">
              <PortalButton onClick={generate} disabled={loading}>{loading ? "Generating…" : "Generate report"}</PortalButton>
            </div>
          </div>
        </section>

        {preview ? (
          <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="flex items-center justify-between gap-4 mb-4">
              <h2 className="text-[20px] font-semibold" style={{ color: TEXT }}>{artifact?.title || "Report preview"}</h2>
              <PortalButton onClick={() => download(artifact?.id)}>Download</PortalButton>
            </div>
            <pre className="max-h-[420px] overflow-auto rounded-xl p-4 text-[12px] whitespace-pre-wrap" style={{ background: BG, color: TEXT, border: `1px solid ${BORDER}` }}>{preview}</pre>
          </section>
        ) : null}

        <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex items-start justify-between gap-5 mb-4">
            <div>
              <h2 className="text-[20px] font-semibold" style={{ color: TEXT }}>Report Factory</h2>
              <p className="mt-2 text-[13px] leading-relaxed" style={{ color: MUTED }}>
                Build a structured operating report with audience-aware language, evidence-backed findings, missing information, and next actions.
              </p>
            </div>
            <div className="flex gap-2">
              <PortalButton onClick={generateFactoryPreview} disabled={loading}>{loading ? "Generating…" : "Generate preview"}</PortalButton>
              <PortalButton variant="secondary" onClick={downloadFactoryPdf} disabled={loading}>{loading ? "Preparing…" : "Download PDF"}</PortalButton>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <label className="text-[12px]" style={{ color: MUTED }}>
              Factory report
              <select value={factoryType} onChange={(event) => setFactoryType(event.target.value as ReportFactoryPayload["report_type"])} className="mt-1 h-10 w-full rounded-lg px-3 outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                <option value="water_use_summary">Water use summary</option>
                <option value="compliance_packet">Compliance packet</option>
                <option value="exception_report">Exception report</option>
                <option value="executive_brief">Executive brief</option>
                <option value="grower_recommendation">Grower recommendation</option>
              </select>
            </label>
            <label className="text-[12px]" style={{ color: MUTED }}>
              Audience
              <select value={factoryAudience} onChange={(event) => setFactoryAudience(event.target.value as ReportFactoryPayload["audience"])} className="mt-1 h-10 w-full rounded-lg px-3 outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                <option value="operator">Operator</option>
                <option value="owner">Owner</option>
                <option value="agency">Agency</option>
                <option value="lender">Lender</option>
                <option value="investor">Investor</option>
                <option value="grower">Grower</option>
              </select>
            </label>
          </div>
          {factoryPreview ? (
            <div className="mt-5 rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
              <div className="flex items-center justify-between gap-4">
                <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>{factoryPreview.title}</h3>
                <StatusBadge label="Preview ready" tone="good" />
              </div>
              <p className="mt-2 text-[13px] leading-relaxed" style={{ color: MUTED }}>{factoryPreview.executive_summary}</p>
              <div className="mt-4 grid grid-cols-2 gap-4">
                <PreviewList title="Key findings" items={factoryPreview.key_findings || []} />
                <PreviewList title="Recommended next actions" items={factoryPreview.recommended_next_actions || []} />
              </div>
              <div className="mt-4 grid grid-cols-2 gap-4">
                <PreviewList title="Missing evidence" items={factoryPreview.missing_evidence || []} />
                <PreviewList title="Evidence appendix" items={factoryPreview.evidence_appendix || []} />
              </div>
            </div>
          ) : null}
        </section>

        <section className="grid grid-cols-2 gap-4">
          {rows.length ? rows.map((report, index) => (
            <article key={report.id || index} className="rounded-xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              <div className="flex items-start justify-between gap-4 mb-3">
                <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>{report.title || report.filename || "Generated report"}</h3>
                <StatusBadge label={report.artifact_type || "artifact"} />
              </div>
              <p className="text-[12px] mb-4" style={{ color: MUTED }}>{report.filename || report.content_type || "Report artifact"}</p>
              <PortalButton variant="secondary" onClick={() => download(report.id)}>Download</PortalButton>
            </article>
          )) : (
            <article className="rounded-xl p-6 col-span-2" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              <InlineState title="No generated reports yet." detail="Generate the first evidence summary or operating brief above." />
            </article>
          )}
        </section>
      </main>
    </div>
  );
}

function PreviewList({ title, items }: { title: string; items: unknown[] }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>{title}</div>
      <div className="space-y-1">
        {items.length ? items.map((item, index) => <div key={index} className="text-[12px] leading-relaxed" style={{ color: TEXT }}>• {text(item)}</div>) : <div className="text-[12px]" style={{ color: MUTED }}>None listed.</div>}
      </div>
    </div>
  );
}
