import { useCallback, useState } from "react";
import { apiClient } from "../api/client";
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
  const briefState = usePortalResource<AnyRecord>(useCallback(() => apiClient.intelligence.brief(), []));
  const [result, setResult] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const brief = briefState.data || {};
  const summary = brief.evidence_summary || {};

  async function runDecision() {
    setLoading(true);
    setMessage("");

    try {
      const response = await apiClient.intelligence.action({
        action: "irrigation_plan",
        payload: { surface: "decisions_page" },
      }) as AnyRecord;
      setResult(response);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Decision run failed.");
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
              <StatusBadge label="Decisions" tone="good" />
              <StatusBadge label={brief.mode === "live" ? "Live" : "Evidence-gated"} tone={brief.mode === "live" ? "good" : "warn"} />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Decisions</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Generate irrigation and water operations decisions only from available evidence. If evidence is weak, AGRO-AI must say what is missing.
            </p>
          </div>
          <PortalButton onClick={runDecision} disabled={loading}>{loading ? "Running…" : "Run decision"}</PortalButton>
        </div>
      </header>

      <main className="px-8 py-6 space-y-5" style={{ maxWidth: 1220 }}>
        {briefState.error ? <InlineState title={briefState.error} /> : null}
        {message ? <InlineState title={message} /> : null}

        <section className="grid grid-cols-4 gap-4">
          <Metric label="Evidence records" value={text(summary.evidence_count || brief.assurance_status?.evidence_count, "0")} />
          <Metric label="Water used" value={`${text(brief.water_status?.used_pct, "—")}%`} />
          <Metric label="Assurance" value={`${text(brief.assurance_status?.score, "0")}%`} />
          <Metric label="Mode" value={text(brief.mode, "demo")} />
        </section>

        <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex items-center justify-between gap-4 mb-4">
            <h2 className="text-[20px] font-semibold" style={{ color: TEXT }}>Current decision output</h2>
            <StatusBadge label={result ? result.status || "completed" : "not run"} tone={result ? "good" : "neutral"} />
          </div>

          {!result ? <InlineState title="No decision run yet." detail="Run a decision after uploading controller, ET/weather, or field evidence." /> : null}

          {result ? (
            <div className="space-y-4">
              <div className="rounded-xl p-5 text-[14px] leading-relaxed" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                {text(result.summary || result.recommendation || result.raw?.recommendation || "Decision completed.")}
              </div>
              <List title="Findings" items={asArray(result.findings || result.raw?.evidence_used)} />
              <List title="Recommendations" items={asArray(result.recommendations || result.raw?.recommendations)} />
              <List title="Missing data" items={asArray(result.missing_data)} />
              <List title="Next actions" items={asArray(result.next_actions)} />
              <List title="Citations" items={asArray(result.citations)} />
            </div>
          ) : null}
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

function List({ title, items }: { title: string; items: unknown[] }) {
  if (!items.length) return null;

  return (
    <div className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>{title}</div>
      <div className="space-y-2">
        {items.map((item, index) => <div key={index} className="text-[13px] leading-relaxed" style={{ color: TEXT }}>• {text(item)}</div>)}
      </div>
    </div>
  );
}
