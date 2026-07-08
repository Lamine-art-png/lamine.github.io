import { useCallback, useState } from "react";
import { apiClient, ReportFactoryPayload } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;

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

function operationalReadiness(summary: AnyRecord) {
  const score = Number(summary.readiness_score || 0);
  if (score >= 70) return "Ready";
  if (score >= 35) return "In review";
  return "Needs data";
}

function evidenceBasis(summary: AnyRecord) {
  if (Number(summary.evidence_count || 0) > 0) return "Available";
  return "Missing";
}

function reportTypeForDecision(mode: string): ReportFactoryPayload["report_type"] {
  if (mode === "compliance_packet") return "compliance_packet";
  if (mode === "water_risk") return "water_use_summary";
  if (mode === "manager_priority") return "executive_brief";
  return "grower_recommendation";
}

export function Operations() {
  const { currentWorkspace } = useAuth();
  const briefState = usePortalResource<AnyRecord>(useCallback(() => apiClient.intelligence.brief(), []));
  const evidenceState = usePortalResource<AnyRecord>(useCallback(() => apiClient.evidence.summary(), []));
  const [result, setResult] = useState<AnyRecord | null>(null);
  const [report, setReport] = useState<AnyRecord | null>(null);
  const [reportRequest, setReportRequest] = useState<ReportFactoryPayload | null>(null);
  const [decisionMode, setDecisionMode] = useState("operator_today");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const brief = briefState.data || {};
  const summary = evidenceState.data || brief.evidence_summary || {};
  const hasEvidence = Number(summary.evidence_count || 0) > 0;

  async function runDecision(mode = decisionMode) {
    setDecisionMode(mode);
    setLoading(true);
    setMessage("");

    try {
      const response = await apiClient.intelligence.run({
        task: "decision_workbench",
        question: `Generate an operator-ready ${mode} decision using current tenant evidence only.`,
        workspace_id: currentWorkspace?.id,
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
      await Promise.all([briefState.refresh(), evidenceState.refresh()]);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Decision run failed.");
    } finally {
      setLoading(false);
    }
  }

  async function ensureReport() {
    const payload: ReportFactoryPayload = {
      report_type: reportTypeForDecision(decisionMode),
      workspace_id: currentWorkspace?.id,
      audience: decisionMode === "operator_today" ? "operator" : decisionMode === "compliance_packet" ? "agency" : "owner",
    };
    const response = await apiClient.reportFactory.generate(payload) as AnyRecord;
    setReport(response.report || response);
    setReportRequest(payload);
    return payload;
  }

  async function generateReport() {
    setLoading(true);
    setMessage("");
    try {
      await ensureReport();
      setMessage("Structured report preview ready.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Report generation failed.");
    } finally {
      setLoading(false);
    }
  }

  async function generatePdf() {
    setLoading(true);
    setMessage("");
    try {
      const payload = reportRequest || await ensureReport();
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
    <div className="min-h-full" style={{ background: BG }}>
      <header className="px-4 py-5 sm:px-8 sm:py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <StatusBadge label="Operating status" tone="good" />
              <StatusBadge label={hasEvidence ? "Evidence base available" : "Needs evidence"} tone={hasEvidence ? "good" : "warn"} />
            </div>
            <h1 className="text-[26px] font-semibold tracking-tight sm:text-[30px]" style={{ color: TEXT }}>Decisions</h1>
            <p className="mt-2 max-w-3xl text-[13px] leading-relaxed sm:text-[14px]" style={{ color: MUTED }}>
              Turn workspace evidence into operator action, water risk review, compliance preparation, and manager-ready field priorities.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 sm:flex-nowrap">
            <PortalButton variant="secondary" onClick={() => window.location.assign("/integrations")}>Add evidence</PortalButton>
            <PortalButton onClick={() => runDecision()} disabled={loading}>{loading ? "Running…" : "Run decision"}</PortalButton>
          </div>
        </div>
      </header>

      <main className="space-y-4 px-4 py-4 sm:space-y-5 sm:px-8 sm:py-6" style={{ maxWidth: 1220 }}>
        {briefState.error ? <InlineState title={briefState.error} /> : null}
        {evidenceState.error ? <InlineState title={evidenceState.error} /> : null}
        {message ? <InlineState title={message} /> : null}

        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
          <Metric label="Operating status" value={result?.customer_status_label || "Ready"} />
          <Metric label="Active issues" value={String(asArray(result?.risk_flags || result?.risks).length)} />
          <Metric label="Evidence basis" value={evidenceBasis(summary)} />
          <Metric label="Workspace readiness" value={operationalReadiness(summary)} />
        </section>

        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <DecisionCard title="Today's priority" active={decisionMode === "operator_today"} onClick={() => runDecision("operator_today")} />
          <DecisionCard title="Water risk" active={decisionMode === "water_risk"} onClick={() => runDecision("water_risk")} />
          <DecisionCard title="Compliance packet" active={decisionMode === "compliance_packet"} onClick={() => runDecision("compliance_packet")} />
          <DecisionCard title="Manager brief" active={decisionMode === "manager_priority"} onClick={() => runDecision("manager_priority")} />
        </section>

        {!hasEvidence ? <InlineState title="The workspace still needs evidence." detail="Upload recent controller exports, field notes, ET, flow, or soil records so the next decision can move from setup guidance into operations." /> : null}

        <section className="rounded-2xl p-4 sm:p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between lg:gap-4">
            <h2 className="text-[18px] font-semibold sm:text-[20px]" style={{ color: TEXT }}>Decision output</h2>
            <div className="flex flex-wrap gap-2">
              <StatusBadge label={result?.customer_status_label || "Ready"} tone={result?.customer_status === "ready" ? "good" : result?.customer_status === "action_required" ? "warn" : "neutral"} />
              <StatusBadge label={`Confidence: ${text(result?.confidence, "low")}`} />
              <PortalButton variant="secondary" onClick={generateReport} disabled={loading}>{loading ? "Working…" : "Generate report"}</PortalButton>
              <PortalButton variant="secondary" onClick={generatePdf} disabled={loading}>{loading ? "Working…" : "Generate PDF"}</PortalButton>
            </div>
          </div>

          {!result ? (
            <InlineState title="Choose a decision card to run the current workspace." detail="AGRO-AI will return the action, why it matters, the risk level, evidence used, and what still needs confirmation." />
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-3 lg:gap-4">
                <Panel title="Recommended action" body={text(result.recommendation || result.answer || result.summary, "Decision completed.")} />
                <Panel title="Why it matters" body={text(result.why || result.summary, "Operational rationale captured.")} />
                <Panel title="Risk level" body={text((asArray(result.risks || result.risk_flags)[0]) || result.risk_level, "Under review")} />
              </div>
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 lg:gap-4">
                <List title="Operator checklist" items={asArray(result.next_actions || result.operator_instructions)} />
                <List title="Missing information" items={asArray(result.what_is_missing || result.missing_data || result.missing_evidence)} />
              </div>
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 lg:gap-4">
                <List title="Evidence used" items={asArray(result.what_i_used || result.evidence_used)} />
                <List title="Operational warnings" items={asArray(result.verification?.risk_flags || result.risk_flags)} />
              </div>
            </div>
          )}
        </section>

        {report ? (
          <section className="rounded-2xl p-4 sm:p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <h2 className="mb-4 break-words text-[18px] font-semibold sm:text-[20px]" style={{ color: TEXT }}>{report.title || "Structured report preview"}</h2>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 lg:gap-4">
              <List title="Key findings" items={asArray(report.key_findings)} />
              <List title="Next actions" items={asArray(report.recommended_next_actions)} />
              <List title="Missing evidence" items={asArray(report.missing_evidence)} />
              <List title="Evidence appendix" items={asArray(report.evidence_appendix)} />
            </div>
          </section>
        ) : null}
      </main>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <section className="rounded-xl p-4 sm:p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="mb-2 text-[9px] font-semibold uppercase tracking-widest sm:text-[10px]" style={{ color: MUTED }}>{label}</div><div className="break-words text-[20px] font-semibold sm:text-[24px]" style={{ color: TEXT }}>{value}</div></section>;
}

function DecisionCard({ title, active, onClick }: { title: string; active: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="min-w-0 rounded-xl p-3 text-left transition-colors sm:p-4" style={{ background: active ? "#0D2B1E" : SURFACE, border: `1px solid ${active ? "#0D2B1E" : BORDER}`, color: active ? "white" : TEXT }}>
      <div className="break-words text-[12px] font-semibold sm:text-[13px]">{title}</div>
      <div className="mt-1 hidden text-[11px] sm:block" style={{ color: active ? "rgba(255,255,255,0.62)" : MUTED }}>Run current workspace decision</div>
    </button>
  );
}

function Panel({ title, body }: { title: string; body: string }) {
  return <div className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="mb-3 text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{title}</div><div className="break-words text-[13px] leading-relaxed" style={{ color: TEXT }}>{body}</div></div>;
}

function List({ title, items }: { title: string; items: unknown[] }) {
  if (!items.length) return null;
  return <div className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="mb-3 text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{title}</div><div className="space-y-2">{items.map((item, index) => <div key={index} className="break-words text-[13px] leading-relaxed" style={{ color: TEXT }}>• {text(item)}</div>)}</div></div>;
}
