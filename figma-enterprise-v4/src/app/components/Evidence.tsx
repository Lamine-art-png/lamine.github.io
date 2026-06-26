import { useCallback } from "react";
import { apiClient } from "../api/client";
import { arrayFromUnknown, usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type EvidenceItem = {
  id?: string;
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
};

type Summary = {
  evidence_count?: number;
  source_count?: number;
  readiness_score?: number;
  missing_data?: string[];
  by_type?: Record<string, number>;
};

export function Evidence() {
  const evidence = usePortalResource<unknown>(useCallback(() => apiClient.evidence.list(), []));
  const summaryState = usePortalResource<Summary>(useCallback(() => apiClient.evidence.summary(), []));
  const rows = arrayFromUnknown<EvidenceItem>(evidence.data, ["records", "evidence", "items", "data"]);
  const summary = summaryState.data || {};

  async function refresh() {
    await Promise.all([evidence.refresh(), summaryState.refresh()]);
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <StatusBadge label="Evidence Store" tone="good" />
              <StatusBadge label={`${summary.readiness_score ?? 0}% readiness`} tone={(summary.readiness_score || 0) > 50 ? "good" : "warn"} />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Evidence</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Imported controller, telemetry, weather, ET, document, and field records. AGRO-AI uses these records as citations for answers, decisions, and reports.
            </p>
          </div>
          <div className="flex gap-2">
            <PortalButton variant="secondary" onClick={refresh}>Refresh</PortalButton>
            <PortalButton onClick={() => window.location.assign("/integrations")}>Upload evidence</PortalButton>
          </div>
        </div>
      </header>

      <div className="px-8 py-6 space-y-5" style={{ maxWidth: 1220 }}>
        {evidence.isLoading ? <InlineState title="Loading evidence" /> : null}
        {evidence.error ? <InlineState title={evidence.error} /> : null}
        {summaryState.error ? <InlineState title={summaryState.error} /> : null}

        <section className="grid grid-cols-4 gap-4">
          <Metric label="Evidence records" value={String(summary.evidence_count ?? rows.length)} />
          <Metric label="Source files" value={String(summary.source_count ?? 0)} />
          <Metric label="Readiness" value={`${summary.readiness_score ?? 0}%`} />
          <Metric label="Evidence types" value={String(Object.keys(summary.by_type || {}).length)} />
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

          {rows.length ? rows.map((row, index) => (
            <div key={row.id || index} className="grid px-6 py-4 gap-4 items-center" style={{ gridTemplateColumns: "1.4fr 1fr 1fr 1fr auto", borderTop: index > 0 ? `1px solid ${BORDER}` : "none" }}>
              <div>
                <div className="text-[13px] font-semibold" style={{ color: TEXT }}>{row.title || row.name || "Evidence item"}</div>
                <div className="text-[11px] leading-relaxed mt-1" style={{ color: MUTED }}>{row.summary || "No summary returned."}</div>
              </div>
              <span className="text-[12px]" style={{ color: MUTED }}>{row.evidence_type || row.domain || "unknown"}</span>
              <span className="text-[12px]" style={{ color: MUTED }}>{row.citation_label || row.source || "source"}</span>
              <span className="text-[12px]" style={{ color: MUTED }}>{row.occurred_at ? new Date(row.occurred_at).toLocaleString() : "No timestamp"}</span>
              <StatusBadge label={row.quality_status || row.status || "usable"} tone={(row.quality_status || row.status) === "usable" ? "good" : "warn"} />
            </div>
          )) : (
            <div className="p-6">
              <InlineState title="No imported evidence yet." detail="Open Connectors, create a WiseConn/Talgil/manual upload setup, and upload an export to generate citation-ready records." />
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
