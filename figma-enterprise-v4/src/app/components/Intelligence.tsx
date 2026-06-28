import { useCallback, useMemo, useState } from "react";
import { apiClient, ReportFactoryPayload } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;

const MODES = [
  ["farmer", "Farmer"],
  ["farmland_manager", "Farmland Manager"],
  ["water_agency", "Water Agency"],
  ["lender", "Lender / Insurer"],
  ["government", "Government Program"],
  ["consultant", "Consultant"],
];

const PROMPTS: Record<string, string[]> = {
  farmer: ["What should I do today?", "Am I overwatering this block?", "Draft a grower checklist."],
  farmland_manager: ["Which blocks need attention first?", "What should my operator do today?", "What evidence is still missing?"],
  water_agency: ["What supports this water use claim?", "What is missing for a compliance review?", "Generate a compliance report."],
  lender: ["Summarize operational water risk.", "Which issues need executive attention?", "Prepare an executive brief."],
  government: ["Summarize readiness across this workspace.", "What data gaps block review?", "Generate a field evidence packet."],
  consultant: ["Draft a client-ready operations summary.", "Explain the current water risk.", "Generate a report for the next visit."],
};

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return fallback;
  }
}

function readinessLabel(summary: AnyRecord) {
  const score = Number(summary.readiness_score || 0);
  if (score >= 70) return "Ready";
  if (score >= 35) return "In review";
  return "Needs data";
}

function evidenceQuality(summary: AnyRecord) {
  const score = Number(summary.readiness_score || 0);
  if (score >= 70) return "Strong";
  if (score >= 35) return "Partial";
  return "Missing";
}

function nextBestStep(summary: AnyRecord) {
  const missing = asArray(summary.missing_source_types).map(String);
  if (missing.length) return "Connect sources";
  if (Number(summary.evidence_count || 0) === 0) return "Upload files";
  return "Run decision";
}

function reportTypeForPrompt(prompt: string): ReportFactoryPayload["report_type"] {
  const lower = prompt.toLowerCase();
  if (lower.includes("compliance") || lower.includes("assurance")) return "compliance_packet";
  if (lower.includes("exception") || lower.includes("risk")) return "exception_report";
  if (lower.includes("grower") || lower.includes("operator") || lower.includes("what should i do")) return "grower_recommendation";
  if (lower.includes("water use") || lower.includes("irrigation") || lower.includes("et")) return "water_use_summary";
  return "executive_brief";
}

function resultAnswer(result: AnyRecord | null) {
  if (!result) return "AGRO-AI completed the request.";
  return text(result.answer || result.summary || result.message, "AGRO-AI completed the request.");
}

export function Intelligence() {
  const { currentWorkspace } = useAuth();
  const briefState = usePortalResource<AnyRecord>(useCallback(() => apiClient.intelligence.brief(), []));
  const [mode, setMode] = useState("farmland_manager");
  const [question, setQuestion] = useState("What should I do today?");
  const [format, setFormat] = useState("answer");
  const [loading, setLoading] = useState(false);
  const [reporting, setReporting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [result, setResult] = useState<AnyRecord | null>(null);
  const [report, setReport] = useState<AnyRecord | null>(null);
  const [reportRequest, setReportRequest] = useState<ReportFactoryPayload | null>(null);
  const [error, setError] = useState("");

  const prompts = useMemo(() => PROMPTS[mode] || PROMPTS.farmland_manager, [mode]);
  const brief = briefState.data || {};
  const summary = result?.evidence_summary || brief.evidence_summary || {};

  async function ask(prompt = question) {
    const clean = prompt.trim();
    if (!clean) return;

    setQuestion(clean);
    setLoading(true);
    setError("");

    try {
      const response = await apiClient.intelligence.ask({
        question: clean,
        workspace_id: currentWorkspace?.id,
        customer_mode: mode,
        output_format: format,
      }) as AnyRecord;
      setResult({
        ...(response.result || response),
        customer_status: response.customer_status,
        customer_status_label: response.customer_status_label,
        confidence: response.confidence,
        evidence_summary: response.evidence_summary,
        citations: response.citations,
        verification: response.verification,
        missing_data: response.missing_data,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ask AGRO-AI failed.");
    } finally {
      setLoading(false);
    }
  }

  async function generateReport() {
    setReporting(true);
    setError("");

    try {
      const payload: ReportFactoryPayload = {
        report_type: reportTypeForPrompt(question),
        workspace_id: currentWorkspace?.id,
        audience: mode === "farmer" ? "grower" : mode === "water_agency" ? "agency" : "owner",
      };
      const response = await apiClient.reportFactory.generate(payload) as AnyRecord;
      setReport(response.report || response);
      setReportRequest(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Report generation failed.");
    } finally {
      setReporting(false);
    }
  }

  async function downloadPdf() {
    setDownloading(true);
    setError("");
    let payload = reportRequest;

    try {
      if (!payload) {
        payload = {
          report_type: reportTypeForPrompt(question),
          workspace_id: currentWorkspace?.id,
          audience: mode === "farmer" ? "grower" : mode === "water_agency" ? "agency" : "owner",
        };
        const response = await apiClient.reportFactory.generate(payload) as AnyRecord;
        setReport(response.report || response);
        setReportRequest(payload);
      }

      const blob = await apiClient.reportFactory.pdf(payload);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `agro-ai-${payload.report_type}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError("Report preview ready. PDF export needs retry.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-8" style={{ background: "#0D2B1E", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
        <div className="max-w-5xl">
          <div className="flex items-center gap-2 mb-4">
            <StatusBadge label={result?.customer_status_label || "Ready"} tone={result?.customer_status === "ready" ? "good" : result?.customer_status === "action_required" ? "warn" : "neutral"} />
            <StatusBadge label={`Workspace readiness: ${readinessLabel(summary)}`} tone={readinessLabel(summary) === "Ready" ? "good" : "warn"} />
          </div>
          <h1 className="text-[34px] font-semibold tracking-tight" style={{ color: "white" }}>Ask AGRO-AI</h1>
          <p className="mt-3 max-w-3xl text-[14px] leading-relaxed" style={{ color: "rgba(255,255,255,0.68)" }}>
            Ask for field priorities, water risk explanation, operator checklists, missing evidence, or a report-ready summary.
          </p>
        </div>
      </header>

      <main className="px-8 py-7 space-y-6" style={{ maxWidth: 1180 }}>
        {error ? <InlineState title={error} /> : null}
        {briefState.error ? <InlineState title={briefState.error} /> : null}

        <section className="grid gap-5" style={{ gridTemplateColumns: "1.45fr 0.55fr" }}>
          <div className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="grid grid-cols-2 gap-3 mb-4">
              <label className="text-[12px]" style={{ color: MUTED }}>
                Audience
                <select value={mode} onChange={(event) => setMode(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                  {MODES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                </select>
              </label>

              <label className="text-[12px]" style={{ color: MUTED }}>
                Response
                <select value={format} onChange={(event) => setFormat(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                  <option value="answer">Answer</option>
                  <option value="decision">Decision</option>
                  <option value="report">Report brief</option>
                  <option value="checklist">Checklist</option>
                </select>
              </label>
            </div>

            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={6}
              className="w-full resize-none rounded-xl px-4 py-4 text-[14px] outline-none"
              style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}
              placeholder="Ask what needs attention, what evidence is missing, what action to take, or what report to generate."
            />

            <div className="mt-4 flex flex-wrap gap-2">
              <PortalButton onClick={() => ask()} disabled={loading}>{loading ? "Working…" : "Ask AGRO-AI"}</PortalButton>
              <PortalButton variant="secondary" onClick={generateReport} disabled={reporting}>{reporting ? "Generating…" : "Generate report"}</PortalButton>
              <PortalButton variant="secondary" onClick={downloadPdf} disabled={downloading}>{downloading ? "Preparing…" : "Download PDF"}</PortalButton>
            </div>

            <div className="mt-5 flex flex-wrap gap-2">
              {prompts.map((item) => (
                <button key={item} type="button" onClick={() => ask(item)} className="rounded-full px-3 py-2 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                  {item}
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>What AGRO-AI can do</div>
            <List title="Capabilities" items={[
              "Prioritize fields",
              "Explain water risk",
              "Draft operator checklist",
              "Generate compliance report",
              "Identify missing evidence",
            ]} />
            <div className="mt-4">
              <ReadinessRow label="Data readiness" value={readinessLabel(summary)} />
              <ReadinessRow label="Evidence quality" value={evidenceQuality(summary)} />
              <ReadinessRow label="Next best step" value={nextBestStep(summary)} />
            </div>
          </div>
        </section>

        <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex items-center justify-between gap-4 mb-4">
            <h2 className="text-[20px] font-semibold" style={{ color: TEXT }}>AGRO-AI answer</h2>
            <div className="flex gap-2">
              <StatusBadge label={loading ? "Working" : result?.customer_status_label || "Ready"} tone={result?.customer_status === "ready" ? "good" : result?.customer_status === "action_required" ? "warn" : "neutral"} />
              <StatusBadge label={`Confidence: ${text(result?.confidence, "low")}`} />
            </div>
          </div>

          {!result && !loading ? <InlineState title="Ask a question above." detail="The response will show what needs attention, what evidence supports it, what is missing, and what to do next." /> : null}
          {loading ? <InlineState title="AGRO-AI is reading the current evidence context…" /> : null}

          {result ? (
            <div className="space-y-4">
              <div className="rounded-xl p-5 whitespace-pre-wrap text-[14px] leading-relaxed" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                {resultAnswer(result)}
              </div>

              <div className="grid grid-cols-2 gap-4">
                <List title="Recommended next actions" items={asArray(result.next_actions || result.recommendations)} />
                <List title="Missing information" items={asArray(result.what_is_missing || result.missing_data)} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <List title="Evidence used" items={asArray(result.what_i_used || result.evidence_used || result.available_data)} />
                <List title="Confidence notes" items={asArray(result.verification?.risk_flags)} />
              </div>

              <div className="flex flex-wrap gap-2">
                <PortalButton variant="secondary" onClick={generateReport} disabled={reporting}>{reporting ? "Generating…" : "Generate report"}</PortalButton>
                <PortalButton variant="secondary" onClick={downloadPdf} disabled={downloading}>{downloading ? "Preparing…" : "Download PDF"}</PortalButton>
              </div>
            </div>
          ) : null}
        </section>

        {report ? (
          <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="flex items-center justify-between gap-4 mb-4">
              <div>
                <h2 className="text-[20px] font-semibold" style={{ color: TEXT }}>{report.title || "Structured report"}</h2>
                <p className="mt-1 text-[12px]" style={{ color: MUTED }}>Structured report preview ready.</p>
              </div>
              <PortalButton onClick={downloadPdf} disabled={downloading}>{downloading ? "Preparing…" : "Download PDF"}</PortalButton>
            </div>
            <div className="space-y-4">
              <div className="rounded-xl p-4 text-[13px] leading-relaxed" style={{ background: BG, color: TEXT, border: `1px solid ${BORDER}` }}>{text(report.executive_summary)}</div>
              <div className="grid grid-cols-2 gap-4">
                <List title="Key findings" items={asArray(report.key_findings)} />
                <List title="Missing evidence" items={asArray(report.missing_evidence)} />
                <List title="Decisions" items={asArray(report.decisions)} />
                <List title="Evidence appendix" items={asArray(report.evidence_appendix)} />
              </div>
            </div>
          </section>
        ) : null}
      </main>
    </div>
  );
}

function ReadinessRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b py-3 last:border-b-0" style={{ borderColor: BORDER }}>
      <span className="text-[12px]" style={{ color: MUTED }}>{label}</span>
      <span className="text-[12px] font-semibold text-right" style={{ color: TEXT }}>{value}</span>
    </div>
  );
}

function List({ title, items }: { title: string; items: unknown[] }) {
  if (!items.length) return null;

  return (
    <div className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>{title}</div>
      <div className="space-y-2">
        {items.map((item, index) => (
          <div key={index} className="text-[13px] leading-relaxed" style={{ color: TEXT }}>• {text(item)}</div>
        ))}
      </div>
    </div>
  );
}
