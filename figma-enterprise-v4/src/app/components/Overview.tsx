import { useCallback, useState } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

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

function v(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

export function Overview() {
  const { user, currentOrganization } = useAuth();
  const briefState = usePortalResource<AnyRecord>(useCallback(() => apiClient.intelligence.brief(), []));
  const brief = briefState.data || {};
  const [running, setRunning] = useState("");
  const [result, setResult] = useState<AnyRecord | null>(null);

  const workspace = (brief.workspace || {}) as AnyRecord;
  const field = (brief.field_state || {}) as AnyRecord;
  const water = (brief.water_status || {}) as AnyRecord;
  const telemetry = (brief.telemetry_status || {}) as AnyRecord;
  const assurance = (brief.assurance_status || {}) as AnyRecord;
  const integrations = asArray(brief.integration_status);
  const risks = textList(brief.risks);
  const nextActions = textList(brief.next_actions);
  const recommendation = asArray(brief.recommendations)[0] || {};

  async function run(action: "field_diagnosis" | "irrigation_plan" | "assurance_packet" | "report_draft") {
    setRunning(action);
    setResult(null);
    try {
      const response = await apiClient.intelligence.action({
        action,
        payload: { surface: "command_center", workspace_id: workspace.id, block_id: field.block_id },
      });
      setResult(response as AnyRecord);
      await briefState.refresh();
    } finally {
      setRunning("");
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <StatusBadge label={brief.mode === "live" ? "Live mode" : "Evaluation sample"} tone={brief.mode === "live" ? "good" : "warn"} />
              <StatusBadge label={`${currentOrganization?.plan || "free"} plan`} />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>
              Command Center
            </h1>
            <p className="mt-2 max-w-2xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Connect your farm systems. AGRO-AI turns fragmented water, sensor, weather, controller, and document evidence into decisions, proof, and reports.
            </p>
          </div>
          <div className="flex gap-2">
            <PortalButton variant="secondary" onClick={briefState.refresh}>Refresh</PortalButton>
            <PortalButton onClick={() => run("irrigation_plan")} disabled={Boolean(running)}>
              {running === "irrigation_plan" ? "Running…" : "Run today’s decision"}
            </PortalButton>
          </div>
        </div>
      </header>

      <div className="px-8 py-6 space-y-5" style={{ maxWidth: 1240 }}>
        {briefState.error ? <InlineState title="Command Center unavailable" detail={briefState.error} /> : null}

        <section className="grid gap-5" style={{ gridTemplateColumns: "1.35fr 0.65fr" }}>
          <div className="rounded-2xl p-7" style={{ background: "#0D2B1E", border: "1px solid rgba(255,255,255,0.06)" }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: "rgba(155,216,75,0.65)" }}>
              Today’s operating decision
            </div>
            <h2 className="text-[24px] font-semibold leading-snug mb-3" style={{ color: "white" }}>
              {recommendation.duration_min
                ? `Run ${v(field.name || field.crop_type, "the block")} for ${recommendation.duration_min} minutes.`
                : "Connect live data or use evaluation context to generate today’s decision."}
            </h2>
            <p className="text-[13px] leading-relaxed max-w-3xl" style={{ color: "rgba(255,255,255,0.68)" }}>
              {recommendation.explanations?.[0] || "AGRO-AI will explain what it used, what is missing, and what the operator should do next."}
            </p>
            <div className="grid grid-cols-4 gap-3 mt-6">
              <DarkMetric label="Confidence" value={v(recommendation.confidence, "pending")} />
              <DarkMetric label="Water used" value={water.used_pct !== undefined ? `${water.used_pct}%` : "—"} />
              <DarkMetric label="Telemetry" value={v(telemetry.record_count, "0")} />
              <DarkMetric label="Assurance" value={assurance.score !== undefined ? `${assurance.score}%` : "—"} />
            </div>
          </div>

          <div className="rounded-2xl p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>Workspace</div>
            <div className="space-y-3">
              <InfoRow label="Operator" value={user?.email || "Authenticated user"} />
              <InfoRow label="Workspace" value={v(workspace.name)} />
              <InfoRow label="Field" value={v(field.name || field.crop_type)} />
              <InfoRow label="Region" value={v(workspace.region)} />
              <InfoRow label="Mode" value={brief.mode === "live" ? "Live operations" : "Evaluation sample only"} />
            </div>
          </div>
        </section>

        <section className="grid grid-cols-3 gap-5">
          <ServiceCard title="Connect" headline="Bring every source into one evidence layer." items={integrations.slice(0, 4).map((item) => `${item.name}: ${item.status}`)} cta="Open Connectors" />
          <ServiceCard title="Decide" headline="Generate water decisions from field evidence." items={["Irrigation plan", "Risk diagnosis", "Operator next action", "Confidence + missing data"]} cta="Open Decisions" />
          <ServiceCard title="Prove" headline="Turn decisions into reports and assurance packets." items={["Citations", "Evidence gaps", "Reviewer-safe language", "Export-ready reports"]} cta="Open Reports" />
        </section>

        <section className="grid gap-5" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Panel title="Top risks">
            {(risks.length ? risks : ["No major risks returned."]).slice(0, 5).map((risk) => (
              <div key={risk} className="rounded-lg px-4 py-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>
                {risk}
              </div>
            ))}
          </Panel>

          <Panel title="Next best actions">
            {(nextActions.length ? nextActions : ["Connect a live source", "Upload recent telemetry", "Generate a decision"]).slice(0, 5).map((action) => (
              <div key={action} className="rounded-lg px-4 py-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>
                {action}
              </div>
            ))}
          </Panel>
        </section>

        <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex flex-wrap gap-2">
            <PortalButton variant="secondary" onClick={() => run("field_diagnosis")} disabled={Boolean(running)}>Run field diagnosis</PortalButton>
            <PortalButton variant="secondary" onClick={() => run("irrigation_plan")} disabled={Boolean(running)}>Run irrigation plan</PortalButton>
            <PortalButton variant="secondary" onClick={() => run("assurance_packet")} disabled={Boolean(running)}>Prepare assurance packet</PortalButton>
            <PortalButton variant="secondary" onClick={() => run("report_draft")} disabled={Boolean(running)}>Draft report</PortalButton>
          </div>
          {result ? (
            <div className="mt-4 rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
              <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>Latest action · {result.action}</div>
              <div className="text-[13px] leading-relaxed" style={{ color: TEXT }}>{result.summary || "Action completed."}</div>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}

function DarkMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl p-4" style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.08)" }}>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: "rgba(255,255,255,0.42)" }}>{label}</div>
      <div className="text-[18px] font-semibold" style={{ color: "white" }}>{value}</div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 text-[13px]">
      <span style={{ color: MUTED }}>{label}</span>
      <span className="font-medium text-right" style={{ color: TEXT }}>{value}</span>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl p-5 space-y-2" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>{title}</div>
      {children}
    </section>
  );
}

function ServiceCard({ title, headline, items, cta }: { title: string; headline: string; items: string[]; cta: string }) {
  return (
    <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>{title}</div>
      <h3 className="text-[17px] font-semibold leading-snug mb-4" style={{ color: TEXT }}>{headline}</h3>
      <div className="space-y-2 mb-5">
        {items.slice(0, 4).map((item) => (
          <div key={item} className="text-[12px] leading-relaxed" style={{ color: MUTED }}>• {item}</div>
        ))}
      </div>
      <div className="text-[12px] font-semibold" style={{ color: "#16533C" }}>{cta} →</div>
    </section>
  );
}
