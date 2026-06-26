import { useCallback, useState } from "react";
import { apiClient } from "../api/client";
import { arrayFromUnknown, usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type Report = {
  id?: string;
  title?: string;
  filename?: string;
  artifact_type?: string;
  content_type?: string;
  created_at?: string;
  metadata_json?: Record<string, unknown>;
};

export function Reports() {
  const reports = usePortalResource<unknown>(useCallback(() => apiClient.reports.list(), []));
  const rows = arrayFromUnknown<Report>(reports.data, ["reports", "items", "artifacts", "data"]);
  const [reportType, setReportType] = useState("evidence_summary");
  const [format, setFormat] = useState<"markdown" | "pdf">("pdf");
  const [message, setMessage] = useState("");
  const [preview, setPreview] = useState("");
  const [artifact, setArtifact] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);

  async function generate() {
    setLoading(true);
    setMessage("");
    setPreview("");

    try {
      const result = await apiClient.reports.generate({ report_type: reportType, format }) as any;
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
              Generate customer-ready evidence summaries, water decision reports, assurance packets, and risk packets from imported evidence.
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
              <InlineState title="No generated reports yet." detail="Generate the first evidence summary or water decision report above." />
            </article>
          )}
        </section>
      </main>
    </div>
  );
}
