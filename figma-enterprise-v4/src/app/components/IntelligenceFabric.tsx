import { useCallback, useState } from "react";
import { apiClient } from "../api/client";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, GREEN, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;

function asArray(value: unknown): AnyRecord[] {
  return Array.isArray(value) ? (value as AnyRecord[]) : [];
}

function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    if (typeof item === "string") return item;
    if (item && typeof item === "object") {
      const record = item as AnyRecord;
      return record.label || record.name || record.next_step || record.id || JSON.stringify(record);
    }
    return String(item);
  });
}

function metric(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

export function IntelligenceFabric() {
  const loadBrief = useCallback(() => apiClient.intelligence.brief(), []);
  const briefState = usePortalResource<AnyRecord>(loadBrief);
  const brief = briefState.data || {};
  const [actionResult, setActionResult] = useState<AnyRecord | null>(null);
  const [runningAction, setRunningAction] = useState("");

  const integrations = asArray(brief.integration_status);
  const risks = textList(brief.risks).slice(0, 3);
  const nextActions = textList(brief.next_actions).slice(0, 4);
  const missing = textList(brief.missing_data).slice(0, 4);
  const workspace = (brief.workspace || {}) as AnyRecord;
  const fieldState = (brief.field_state || {}) as AnyRecord;
  const water = (brief.water_status || {}) as AnyRecord;
  const telemetry = (brief.telemetry_status || {}) as AnyRecord;
  const assurance = (brief.assurance_status || {}) as AnyRecord;

  async function run(action: "field_diagnosis" | "irrigation_plan" | "assurance_packet" | "evidence_gap_analysis" | "integration_diagnosis" | "report_draft") {
    setRunningAction(action);
    setActionResult(null);
    try {
      const result = await apiClient.intelligence.action({
        action,
        payload: {
          source: "platform_brain_panel",
          workspace_id: workspace.id,
          block_id: fieldState.block_id,
        },
      });
      setActionResult(result as AnyRecord);
      await briefState.refresh();
    } finally {
      setRunningAction("");
    }
  }

  return (
    <section className="px-6 pt-5 pb-4" style={{ background: BG, borderBottom: `1px solid ${BORDER}` }}>
      <div className="rounded-2xl overflow-hidden" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
        <div className="px-6 py-4 flex items-center justify-between" style={{ borderBottom: `1px solid ${BORDER}` }}>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <h2 className="text-[15px] font-semibold" style={{ color: TEXT }}>AGRO-AI Intelligence Fabric</h2>
              <StatusBadge label={brief.mode === "live" ? "Operational context" : "Workspace in review"} tone={brief.mode === "live" ? "good" : "warn"} />
              <StatusBadge label="Shared intelligence layer" tone="good" />
            </div>
            <p className="text-[12px]" style={{ color: MUTED }}>
              One evidence layer powering WaterOps, Assurance, Evidence, Reports, Agents, and Integrations.
            </p>
          </div>
          <div className="flex gap-2">
            <PortalButton variant="secondary" onClick={briefState.refresh}>Refresh</PortalButton>
            <PortalButton onClick={() => run("field_diagnosis")} disabled={Boolean(runningAction)}>
              {runningAction === "field_diagnosis" ? "Running…" : "Run diagnosis"}
            </PortalButton>
          </div>
        </div>

        {briefState.error ? (
          <div className="p-5">
            <InlineState title="Intelligence brief unavailable" detail={briefState.error} />
          </div>
        ) : (
          <div className="p-5 space-y-4">
            <div className="grid grid-cols-5 gap-3">
              <BrainMetric label="Workspace" value={metric(workspace.name || workspace.id, briefState.isLoading ? "Loading…" : "—")} sub={metric([workspace.crop, workspace.region].filter(Boolean).join(" · "), "Field context")} />
              <BrainMetric label="Field" value={metric(fieldState.name || fieldState.crop_type)} sub={metric(fieldState.soil_type, "Soil pending")} />
              <BrainMetric label="Water used" value={water.used_pct !== undefined && water.used_pct !== null ? `${water.used_pct}%` : "—"} sub={metric(water.status, "Budget status")} />
              <BrainMetric label="Telemetry" value={metric(telemetry.record_count, "0")} sub={metric(telemetry.quality, "Quality")} />
              <BrainMetric label="Assurance" value={assurance.score !== undefined ? `${assurance.score}%` : "—"} sub={metric(assurance.status, "Readiness")} />
            </div>

            <div className="grid gap-4" style={{ gridTemplateColumns: "1.2fr 1fr 1fr" }}>
              <Panel title="Source readiness">
                <div className="space-y-2">
                  {integrations.slice(0, 4).map((item, index) => (
                    <div key={`${item.name || "source"}-${index}`} className="flex items-start justify-between gap-3 rounded-lg px-3 py-2" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                      <div>
                        <div className="text-[12px] font-semibold" style={{ color: TEXT }}>{item.name || "Source"}</div>
                        <div className="text-[11px] leading-relaxed" style={{ color: MUTED }}>{item.next_step || "No next step returned"}</div>
                      </div>
                      <StatusBadge label={item.status || "unknown"} tone={item.status === "available" || item.status === "connected" ? "good" : "warn"} />
                    </div>
                  ))}
                </div>
              </Panel>

              <Panel title="Top risks">
                {risks.length ? (
                  <ul className="space-y-2">
                    {risks.map((risk) => <li key={risk} className="text-[12px] leading-relaxed" style={{ color: MUTED }}>• {risk}</li>)}
                  </ul>
                ) : (
                  <InlineState title="No major risk flags returned" />
                )}
              </Panel>

              <Panel title="Next actions">
                <div className="space-y-2">
                  {(nextActions.length ? nextActions : missing).map((action) => (
                    <div key={action} className="text-[12px] leading-relaxed" style={{ color: MUTED }}>→ {action}</div>
                  ))}
                </div>
              </Panel>
            </div>

            <div className="flex flex-wrap gap-2">
              <PortalButton variant="secondary" onClick={() => run("irrigation_plan")} disabled={Boolean(runningAction)}>Irrigation plan</PortalButton>
              <PortalButton variant="secondary" onClick={() => run("assurance_packet")} disabled={Boolean(runningAction)}>Assurance packet</PortalButton>
              <PortalButton variant="secondary" onClick={() => run("evidence_gap_analysis")} disabled={Boolean(runningAction)}>Evidence gaps</PortalButton>
              <PortalButton variant="secondary" onClick={() => run("integration_diagnosis")} disabled={Boolean(runningAction)}>Integration diagnosis</PortalButton>
              <PortalButton variant="secondary" onClick={() => run("report_draft")} disabled={Boolean(runningAction)}>Report draft</PortalButton>
            </div>

            {actionResult ? (
              <div className="rounded-xl p-4" style={{ background: "#0D2B1E", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div className="flex items-center justify-between mb-2">
                  <div className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.45)" }}>
                    Action result · {actionResult.action}
                  </div>
                  <StatusBadge label={actionResult.status === "completed" ? "Ready" : "Action required"} tone={actionResult.status === "completed" ? "good" : "warn"} />
                </div>
                <div className="text-[13px] leading-relaxed" style={{ color: "rgba(255,255,255,0.82)" }}>
                  {actionResult.summary || "Action completed."}
                </div>
                {textList(actionResult.next_actions).length ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {textList(actionResult.next_actions).slice(0, 4).map((item) => (
                      <span key={item} className="px-2.5 py-1 rounded text-[11px]" style={{ background: "rgba(255,255,255,0.08)", color: "rgba(255,255,255,0.72)" }}>
                        {item}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}

function BrainMetric({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>{label}</div>
      <div className="text-[18px] font-semibold leading-tight mb-1" style={{ color: TEXT }}>{value}</div>
      <div className="text-[11px]" style={{ color: MUTED }}>{sub}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>{title}</div>
      {children}
    </div>
  );
}
