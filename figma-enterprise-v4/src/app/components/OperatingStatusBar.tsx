import { useCallback, useState } from "react";
import { Brain } from "lucide-react";
import { apiClient } from "../api/client";
import { usePortalCopy } from "../hooks/usePortalCopy";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;
const STATUSBAR_SHARED_COPY = ["Connector", "unknown", "available", "connected"] as const;

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

function value(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

export function OperatingStatusBar() {
  const { tx, tf } = usePortalCopy(["statusbar"], STATUSBAR_SHARED_COPY);
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState("");
  const [result, setResult] = useState<AnyRecord | null>(null);
  const briefState = usePortalResource<AnyRecord>(useCallback(() => apiClient.intelligence.brief(), []));
  const brief = briefState.data || {};
  const workspace = (brief.workspace || {}) as AnyRecord;
  const field = (brief.field_state || {}) as AnyRecord;
  const telemetry = (brief.telemetry_status || {}) as AnyRecord;
  const water = (brief.water_status || {}) as AnyRecord;
  const assurance = (brief.assurance_status || {}) as AnyRecord;
  const integrations = asArray(brief.integration_status);
  const missing = textList(brief.missing_data);
  const risks = textList(brief.risks);
  const nextActions = textList(brief.next_actions);

  const missingCredentialCount = integrations.filter((item) =>
    String(item.status || "").includes("missing") || String(item.status || "").includes("required")
  ).length;

  async function run(action: "field_diagnosis" | "irrigation_plan" | "assurance_packet" | "evidence_gap_analysis" | "integration_diagnosis" | "report_draft") {
    setRunning(action);
    setResult(null);
    try {
      const response = await apiClient.intelligence.action({
        action,
        payload: {
          surface: "operating_status_bar",
          workspace_id: workspace.id,
          block_id: field.block_id,
        },
      });
      setResult(response as AnyRecord);
      setOpen(true);
      await briefState.refresh();
    } finally {
      setRunning("");
    }
  }

  return (
    <>
      <div className="sticky top-0 z-20 px-3 py-2.5 sm:px-6 sm:py-3" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex min-w-0 items-center justify-between gap-2 sm:gap-4">
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="flex min-w-0 flex-1 items-center gap-2 text-left sm:gap-3"
          >
            <StatusBadge label={tx(brief.mode === "live" ? "Live operations" : "Evaluation sample")} tone={brief.mode === "live" ? "good" : "warn"} />
            <span className="max-w-[40vw] truncate text-[12px] font-medium sm:hidden" style={{ color: TEXT }}>
              {value(workspace.name, tx("Workspace"))}
            </span>
            <span className="hidden truncate text-[13px] font-medium sm:inline" style={{ color: TEXT }}>
              {tf("{workspace} · {field} · {telemetry} telemetry records · {connectors} connectors need setup", {
                workspace: value(workspace.name, tx("Workspace")),
                field: value(field.name || field.crop_type, tx("Field")),
                telemetry: value(telemetry.record_count, 0),
                connectors: missingCredentialCount,
              })}
            </span>
            <span className="hidden lg:inline text-[12px]" style={{ color: MUTED }}>
              {tf("Water {water}% · Assurance {assurance}%", {
                water: value(water.used_pct, "—"),
                assurance: value(assurance.score, "—"),
              })}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setOpen(true)}
            className="flex h-9 flex-shrink-0 items-center gap-1.5 rounded-lg px-3 text-[12px] font-semibold sm:hidden"
            style={{ border: `1px solid ${BORDER}`, color: TEXT, background: BG }}
            aria-label={tx("Open brain")}
          >
            <Brain className="h-4 w-4" />
            Brain
          </button>

          <div className="hidden items-center gap-2 sm:flex">
            <PortalButton variant="secondary" onClick={() => setOpen(true)}>{tx("Open brain")}</PortalButton>
            <PortalButton onClick={() => run("irrigation_plan")} disabled={Boolean(running)}>
              {running === "irrigation_plan" ? tx("Running…") : tx("Run decision")}
            </PortalButton>
          </div>
        </div>
      </div>

      {open ? (
        <div className="fixed inset-0 z-50">
          <button className="absolute inset-0 bg-black/30" onClick={() => setOpen(false)} aria-label={tx("Close intelligence drawer")} />
          <aside className="absolute right-0 top-0 h-full w-full overflow-y-auto shadow-2xl sm:w-[560px] sm:max-w-[96vw]" style={{ background: SURFACE, paddingTop: "env(safe-area-inset-top)", paddingBottom: "env(safe-area-inset-bottom)" }}>
            <div className="sticky top-0 z-10 flex items-start justify-between gap-3 px-4 py-4 sm:gap-4 sm:px-6 sm:py-5" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
              <div className="min-w-0">
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{tx("Operating intelligence")}</div>
                <h2 className="text-lg font-semibold sm:text-xl" style={{ color: TEXT }}>{tx("AGRO-AI brain")}</h2>
                <p className="mt-1 text-[12px] leading-relaxed" style={{ color: MUTED }}>
                  {tx("One evidence layer powering decisions, reports, assurance, connectors, and Ask AGRO-AI.")}
                </p>
              </div>
              <button className="flex-shrink-0 rounded-lg px-3 py-2 text-[12px]" style={{ border: `1px solid ${BORDER}`, color: TEXT }} onClick={() => setOpen(false)}>
                {tx("Close")}
              </button>
            </div>

            <div className="space-y-4 p-4 sm:space-y-5 sm:p-6">
              {briefState.error ? <InlineState title={tx("Brain unavailable")} detail={briefState.error} /> : null}

              <div className="grid grid-cols-1 gap-3 min-[390px]:grid-cols-2">
                <Metric label={tx("Workspace")} value={value(workspace.name)} sub={value(workspace.region, tx("Region pending"))} />
                <Metric label={tx("Field")} value={value(field.name || field.crop_type)} sub={value(field.soil_type, tx("Soil pending"))} />
                <Metric label={tx("Telemetry")} value={String(value(telemetry.record_count, 0))} sub={value(telemetry.quality, tx("Quality pending"))} />
                <Metric label={tx("Assurance")} value={assurance.score !== undefined ? `${assurance.score}%` : "—"} sub={value(assurance.status, tx("Readiness pending"))} />
              </div>

              <Panel title={tx("Connectors")}>
                <div className="space-y-2">
                  {integrations.map((item, index) => (
                    <div key={`${item.name || "connector"}-${index}`} className="flex items-start justify-between gap-3 rounded-lg px-3 py-2" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                      <div className="min-w-0">
                        <div className="truncate text-[12px] font-semibold" style={{ color: TEXT }}>{item.name || tx("Connector")}</div>
                        <div className="text-[11px] leading-relaxed" style={{ color: MUTED }}>{tx(String(item.next_step || "Setup pending"))}</div>
                      </div>
                      <StatusBadge label={tx(String(item.status || "unknown"))} tone={item.status === "available" || item.status === "connected" ? "good" : "warn"} />
                    </div>
                  ))}
                </div>
              </Panel>

              <Panel title={tx("Risks")}>
                {(risks.length ? risks : [tx("No major risk flags returned.")]).slice(0, 5).map((item) => (
                  <div key={item} className="mb-2 text-[12px] leading-relaxed" style={{ color: MUTED }}>• {item}</div>
                ))}
              </Panel>

              <Panel title={tx("Next best actions")}>
                {(nextActions.length ? nextActions : missing).slice(0, 5).map((item) => (
                  <div key={item} className="mb-2 text-[12px] leading-relaxed" style={{ color: MUTED }}>→ {item}</div>
                ))}
              </Panel>

              <div className="grid grid-cols-1 gap-2 min-[390px]:grid-cols-2">
                <PortalButton variant="secondary" onClick={() => run("field_diagnosis")} disabled={Boolean(running)}>{tx("Field diagnosis")}</PortalButton>
                <PortalButton variant="secondary" onClick={() => run("assurance_packet")} disabled={Boolean(running)}>{tx("Assurance packet")}</PortalButton>
                <PortalButton variant="secondary" onClick={() => run("evidence_gap_analysis")} disabled={Boolean(running)}>{tx("Evidence gaps")}</PortalButton>
                <PortalButton variant="secondary" onClick={() => run("report_draft")} disabled={Boolean(running)}>{tx("Report draft")}</PortalButton>
              </div>

              {result ? (
                <div className="rounded-xl p-4" style={{ background: "#0D2B1E", color: "white" }}>
                  <div className="mb-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "rgba(255,255,255,0.45)" }}>
                    {tf("Action result · {action}", { action: String(result.action || "") })}
                  </div>
                  <div className="text-[13px] leading-relaxed" style={{ color: "rgba(255,255,255,0.82)" }}>
                    {result.summary || tx("Action completed.")}
                  </div>
                </div>
              ) : null}
            </div>
          </aside>
        </div>
      ) : null}
    </>
  );
}

function Metric({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{label}</div>
      <div className="text-[18px] font-semibold leading-tight" style={{ color: TEXT }}>{value}</div>
      <div className="mt-1 text-[11px]" style={{ color: MUTED }}>{sub}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="mb-3 text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{title}</div>
      {children}
    </section>
  );
}
