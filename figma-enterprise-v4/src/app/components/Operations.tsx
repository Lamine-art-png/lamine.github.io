import { useCallback, useState } from "react";
import { apiClient } from "../api/client";
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

export function Operations() {
  const { currentWorkspace } = useAuth();
  const briefState = usePortalResource<AnyRecord>(useCallback(() => apiClient.intelligence.brief(), []));
  const evidenceState = usePortalResource<AnyRecord>(useCallback(() => apiClient.evidence.summary(), []));
  const statusState = usePortalResource<AnyRecord>(useCallback(() => apiClient.ai.status(), []));
  const [result, setResult] = useState<AnyRecord | null>(null);
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
      const runMode =
        mode === "compliance_packet"
          ? "compliance"
          : mode === "water_risk"
            ? "irrigation"
            : mode === "manager_priority"
              ? "field"
              : "daily";
      const response = await apiClient.decisions.runWorkbench({
        workspace_id: currentWorkspace?.id,
        mode: runMode,
      }) as AnyRecord;
      if (statusState.data?.configured) {
        const modelResponse = await apiClient.intelligence.run({
          task: "decision_workbench",
          question: `Generate an operator-ready ${mode} decision using current tenant evidence only.`,
          workspace_id: currentWorkspace?.id,
        }) as AnyRecord;
        setResult(modelResponse.result || modelResponse);
      } else {
        setResult((response.decisions || [])[0] || response);
      }
      await Promise.all([briefState.refresh(), evidenceState.refresh()]);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Decision run failed.");
    } finally {
      setLoading(false);
    }
  }

  async function generatePdf() {
    setLoading(true);
    setMessage("");

    try {
      const response = await apiClient.reports.generate({
        report_type: "water_decision",
        workspace_id: currentWorkspace?.id,
        format: "pdf",
      }) as AnyRecord;

      const artifactId = response?.artifact?.id;
      if (artifactId) {
        const blob = await apiClient.artifacts.download(artifactId);
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = response.artifact.filename || "agro-ai-water-decision.pdf";
        link.click();
        URL.revokeObjectURL(url);
      }

      setMessage("Water decision PDF generated.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "PDF generation failed.");
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
              <StatusBadge label="Decision Engine" tone="good" />
              <StatusBadge label={hasEvidence ? "Evidence available" : "Needs evidence"} tone={hasEvidence ? "good" : "warn"} />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Decisions</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Turn uploaded controller, telemetry, ET/weather, and field evidence into operator decisions, risk briefs, and exportable water decision reports.
            </p>
          </div>

          <div className="flex gap-2">
            <PortalButton variant="secondary" onClick={() => window.location.assign("/integrations")}>Add evidence</PortalButton>
            <PortalButton onClick={() => runDecision()} disabled={loading}>{loading ? "Running…" : "Run decision"}</PortalButton>
          </div>
        </div>
      </header>

      <main className="px-8 py-6 space-y-5" style={{ maxWidth: 1220 }}>
        {briefState.error ? <InlineState title={briefState.error} /> : null}
        {evidenceState.error ? <InlineState title={evidenceState.error} /> : null}
        {statusState.error ? <InlineState title={statusState.error} /> : null}
        {message ? <InlineState title={message} /> : null}

        <section className="grid grid-cols-4 gap-4">
          <Metric label="Evidence records" value={text(summary.evidence_count, "0")} />
          <Metric label="Source files" value={text(summary.source_count, "0")} />
          <Metric label="Readiness" value={`${text(summary.readiness_score, "0")}%`} />
          <Metric label="Mode" value={text(result?.mode || brief.mode, "internal")} />
        </section>

        <section className="grid grid-cols-4 gap-3">
          <DecisionCard title="Operator today" active={decisionMode === "operator_today"} onClick={() => runDecision("operator_today")} />
          <DecisionCard title="Water risk" active={decisionMode === "water_risk"} onClick={() => runDecision("water_risk")} />
          <DecisionCard title="Compliance packet" active={decisionMode === "compliance_packet"} onClick={() => runDecision("compliance_packet")} />
          <DecisionCard title="Manager priority" active={decisionMode === "manager_priority"} onClick={() => runDecision("manager_priority")} />
        </section>

        {!hasEvidence ? (
          <InlineState
            title="No imported evidence yet."
            detail="Upload a controller export, CSV, JSON, TXT, or PDF text file first. Decisions will still explain what is missing, but they should not pretend to be operational."
          />
        ) : null}

        <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex items-center justify-between gap-4 mb-4">
            <h2 className="text-[20px] font-semibold" style={{ color: TEXT }}>Decision output</h2>
            <div className="flex gap-2">
              <StatusBadge label={text(result?.model_status || (statusState.data?.configured ? "live" : "fallback"))} tone={result?.model_status === "live" ? "good" : "warn"} />
              <StatusBadge label={result ? result.confidence || "generated" : "not run"} tone={result ? "good" : "neutral"} />
              <PortalButton variant="secondary" onClick={generatePdf} disabled={loading}>{loading ? "Working…" : "Generate PDF"}</PortalButton>
            </div>
          </div>

          {!result ? (
            <InlineState title="No decision run yet." detail="Choose a decision mode above or click Run decision." />
          ) : (
            <div className="space-y-4">
              <div className="rounded-xl p-5 text-[14px] leading-relaxed whitespace-pre-wrap" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                {text(result.recommendation || result.answer || result.summary || result.message, "Decision completed.")}
                {result.why ? `\n\n${text(result.why)}` : ""}
              </div>

              <List title="Evidence used" items={asArray(result.what_i_used || result.evidence_used)} />
              <List title="Missing data" items={asArray(result.what_is_missing || result.missing_data || result.missing_evidence)} />
              <List title="Verification warnings" items={asArray(result.verification?.risk_flags)} />
              <List title="Risks / uncertainty" items={asArray(result.risks || result.risk_flags || [result.risk_level].filter(Boolean))} />
              <List title="Next actions" items={asArray(result.next_actions || result.operator_instructions)} />
              <List title="Citations" items={asArray(result.citations)} />
            </div>
          )}
        </section>
      </main>
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

function DecisionCard({ title, active, onClick }: { title: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-xl p-4 text-left transition-colors"
      style={{
        background: active ? "#0D2B1E" : SURFACE,
        border: `1px solid ${active ? "#0D2B1E" : BORDER}`,
        color: active ? "white" : TEXT,
      }}
    >
      <div className="text-[13px] font-semibold">{title}</div>
      <div className="text-[11px] mt-1" style={{ color: active ? "rgba(255,255,255,0.62)" : MUTED }}>
        Generate grounded decision
      </div>
    </button>
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
