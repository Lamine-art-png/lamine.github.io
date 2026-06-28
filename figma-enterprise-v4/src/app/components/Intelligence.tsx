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
  farmer: ["What should I do today?", "Am I overwatering this block?", "Explain the recommendation in simple language."],
  farmland_manager: ["Which blocks need attention first?", "Where is our evidence weak?", "What should my operator do today?"],
  water_agency: ["What evidence supports this water use claim?", "What is missing for a compliance review?", "Generate an assurance packet."],
  lender: ["Summarize operational water risk.", "What data improves underwriting confidence?", "Show evidence quality by source."],
  government: ["Summarize program-level readiness.", "What data is missing across participants?", "Create a field evidence packet."],
  consultant: ["Draft a client-facing water operations summary.", "Identify data gaps before the next farm visit.", "Prepare an irrigation decision explanation."],
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

export function Intelligence() {
  const { currentWorkspace } = useAuth();
  const briefState = usePortalResource<AnyRecord>(useCallback(() => apiClient.intelligence.brief(), []));
  const statusState = usePortalResource<AnyRecord>(useCallback(() => apiClient.ai.status(), []));
  const [mode, setMode] = useState("farmland_manager");
  const [question, setQuestion] = useState("What should I do today?");
  const [format, setFormat] = useState("answer");
  const [loading, setLoading] = useState(false);
  const [reporting, setReporting] = useState(false);
  const [result, setResult] = useState<AnyRecord | null>(null);
  const [report, setReport] = useState<AnyRecord | null>(null);
  const [reportRequest, setReportRequest] = useState<ReportFactoryPayload | null>(null);
  const [error, setError] = useState("");

  const prompts = useMemo(() => PROMPTS[mode] || PROMPTS.farmland_manager, [mode]);
  const brief = briefState.data || {};
  const modelStatus = statusState.data || {};
  const summary = result?.evidence_summary || brief.evidence_summary || {};

  function reportTypeForPrompt(prompt: string): ReportFactoryPayload["report_type"] {
    const lower = prompt.toLowerCase();
    if (lower.includes("compliance") || lower.includes("assurance")) return "compliance_packet";
    if (lower.includes("exception") || lower.includes("risk")) return "exception_report";
    if (lower.includes("grower") || lower.includes("operator") || lower.includes("what should i do")) return "grower_recommendation";
    if (lower.includes("water use") || lower.includes("irrigation") || lower.includes("et")) return "water_use_summary";
    return "executive_brief";
  }

  async function ask(prompt = question) {
    const clean = prompt.trim();
    if (!clean) return;

    setQuestion(clean);
    setLoading(true);
    setError("");
    setReport(null);

    try {
      const response = await apiClient.intelligence.ask({
        question: clean,
        workspace_id: currentWorkspace?.id,
        customer_mode: mode,
        output_format: format,
      }) as AnyRecord;
      setResult({
        ...(response.result || response),
        model_status: response.model_status,
        model: response.model,
        provider: response.provider,
        confidence: response.confidence,
        sample_mode: response.sample_mode,
        evidence_summary: response.evidence_summary,
        citations: response.citations,
        verification: response.verification,
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

  async function downloadArtifact() {
    if (!reportRequest) return;
    const blob = await apiClient.reportFactory.pdf(reportRequest);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `agro-ai-${reportRequest.report_type}.pdf`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-8" style={{ background: "#0D2B1E", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
        <div className="max-w-5xl">
            <div className="flex items-center gap-2 mb-4">
            <StatusBadge label={result?.sample_mode || brief.sample_mode ? "Evaluation sample" : brief.mode === "live" ? "Live brain" : "Evidence-grounded"} tone={result?.sample_mode || brief.sample_mode ? "warn" : "good"} />
            <StatusBadge label={`${summary.readiness_score ?? 0}% readiness`} tone={(summary.readiness_score || 0) > 50 ? "good" : "warn"} />
          </div>
          <h1 className="text-[34px] font-semibold tracking-tight" style={{ color: "white" }}>Ask AGRO-AI</h1>
          <p className="mt-3 max-w-3xl text-[14px] leading-relaxed" style={{ color: "rgba(255,255,255,0.68)" }}>
            Ask questions over imported evidence, connector readiness, missing data, water risk, and reportable proof.
          </p>
        </div>
      </header>

      <main className="px-8 py-7 space-y-6" style={{ maxWidth: 1180 }}>
        {error ? <InlineState title={error} /> : null}
        {briefState.error ? <InlineState title={briefState.error} /> : null}
        {statusState.error ? <InlineState title={statusState.error} /> : null}

        <section className="grid gap-5" style={{ gridTemplateColumns: "1.45fr 0.55fr" }}>
          <div className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="grid grid-cols-2 gap-3 mb-4">
              <label className="text-[12px]" style={{ color: MUTED }}>
                Customer mode
                <select value={mode} onChange={(event) => setMode(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                  {MODES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                </select>
              </label>

              <label className="text-[12px]" style={{ color: MUTED }}>
                Output
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
              placeholder="Ask AGRO-AI what to do, what is missing, what changed, or what to report."
            />

            <div className="mt-4 flex flex-wrap gap-2">
              <PortalButton onClick={() => ask()} disabled={loading}>{loading ? "Thinking…" : "Ask AGRO-AI"}</PortalButton>
              <PortalButton variant="secondary" onClick={() => generateReport()} disabled={reporting}>{reporting ? "Generating…" : "Generate PDF report"}</PortalButton>
              <PortalButton variant="secondary" onClick={() => window.location.assign("/integrations")}>Improve with connectors</PortalButton>
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
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>Current context</div>
            <Info label="Workspace" value={text(currentWorkspace?.name || brief.workspace?.name, "Workspace")} />
            <Info label="Mode" value={text(result?.mode || brief.mode, "demo")} />
            <Info label="Sample mode" value={result?.sample_mode || brief.sample_mode ? "Evaluation sample" : "Customer evidence"} />
            <Info label="Model status" value={text(result?.model_status || (modelStatus.fallback_active ? "fallback" : modelStatus.configured ? "live" : "offline"))} />
            <Info label="Provider" value={text(result?.provider || modelStatus.provider, "offline")} />
            <Info label="Model" value={text(result?.model || modelStatus.model, "Not configured")} />
            <Info label="Evidence records" value={text(summary.evidence_count, "0")} />
            <Info label="Source files" value={text(summary.source_count, "0")} />
            <Info label="Readiness" value={`${text(summary.readiness_score, "0")}%`} />
          </div>
        </section>

        <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex items-center justify-between gap-4 mb-4">
            <h2 className="text-[20px] font-semibold" style={{ color: TEXT }}>AGRO-AI answer</h2>
            <div className="flex gap-2">
              {result?.sample_mode ? <StatusBadge label="Evaluation sample" tone="warn" /> : null}
              <StatusBadge label={loading ? "Thinking" : result ? "Generated" : "Ready"} tone={result ? "good" : "neutral"} />
            </div>
          </div>

          {!result && !loading ? <InlineState title="Ask a question above." detail="The response will show answer, evidence used, missing data, risks, next actions, and citations." /> : null}
          {loading ? <InlineState title="AGRO-AI is reading the current evidence context…" /> : null}

          {result ? (
            <div className="space-y-4">
              <div className="rounded-xl p-5 whitespace-pre-wrap text-[14px] leading-relaxed" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                {text(result.answer || result.summary || result.message, "AGRO-AI completed the request.")}
              </div>

              <div className="grid grid-cols-4 gap-3">
                <Info label="Model status" value={text(result.model_status)} />
                <Info label="Selected model" value={text(result.model, "Not configured")} />
                <Info label="Confidence" value={text(result.confidence, "low")} />
                <Info label="Verification" value={text(result.verification?.status, "partial")} />
              </div>
              <List title="Verification warnings" items={asArray(result.verification?.risk_flags)} />
              <List title="Evidence used" items={asArray(result.what_i_used || result.evidence_used)} />
              <List title="Missing data" items={asArray(result.what_is_missing || result.missing_data)} />
              <List title="Risks / uncertainty" items={asArray(result.risks || result.risk_flags)} />
              <List title="Next actions" items={asArray(result.next_actions)} />
              <List title="Citations" items={asArray(result.citations)} />
            </div>
          ) : null}
        </section>

        {report ? (
          <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="flex items-center justify-between gap-4 mb-4">
              <div>
                <h2 className="text-[20px] font-semibold" style={{ color: TEXT }}>{report.title || "Structured report"}</h2>
                <p className="mt-1 text-[12px]" style={{ color: MUTED }}>{reportRequest ? "Structured report ready — PDF export enabled" : "Structured report ready — PDF export not yet enabled"}</p>
              </div>
              <PortalButton onClick={downloadArtifact} disabled={!reportRequest}>Download PDF</PortalButton>
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

function Info({ label, value }: { label: string; value: string }) {
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
