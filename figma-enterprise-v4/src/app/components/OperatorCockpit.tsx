import { useCallback, useState } from "react";
import type React from "react";
import { apiClient, ReportFactoryPayload, WorkbenchRunPayload } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { arrayFromUnknown, usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;

function value(input: unknown, fallback = "—") {
  if (input === null || input === undefined || input === "") return fallback;
  if (typeof input === "string" || typeof input === "number" || typeof input === "boolean") return String(input);
  return JSON.stringify(input);
}

function useWorkspaceId() {
  const { currentWorkspace } = useAuth();
  return currentWorkspace?.id;
}

export function Readiness() {
  const workspaceId = useWorkspaceId();
  const state = usePortalResource<AnyRecord>(useCallback(() => apiClient.readiness.summary(workspaceId), [workspaceId]));
  const summary = state.data || {};
  const connectorHealth = arrayFromUnknown<AnyRecord>(summary.connector_health, []);
  const breakdown = arrayFromUnknown<AnyRecord>(summary.provider_breakdown, []);

  return (
    <PageShell
      badge="Operating Readiness"
      title="Readiness"
      detail="Daily source coverage, connector health, evidence volume, and missing operating context."
      action={<PortalButton variant="secondary" onClick={state.refresh}>Refresh</PortalButton>}
    >
      {state.error ? <InlineState title={state.error} /> : null}
      <section className="grid grid-cols-4 gap-4">
        <Metric label="Readiness" value={`${value(summary.readiness_score, 0)}%`} />
        <Metric label="Level" value={value(summary.readiness_level, "blocked")} />
        <Metric label="Sources" value={value(summary.data_sources, 0)} />
        <Metric label="Evidence" value={value(summary.evidence_records, 0)} />
      </section>

      {summary.sample_mode ? <InlineState title="Sample mode" detail="This workspace has no operational evidence yet. Connect or upload data before sending reports or approving field actions." /> : null}

      <section className="grid grid-cols-[1.1fr_0.9fr] gap-4">
        <Panel title="Missing Source Types">
          <ChipList items={arrayFromUnknown(summary.missing_source_types, [])} empty="No required source gaps detected." />
        </Panel>
        <Panel title="Recommended Next Steps">
          <List items={arrayFromUnknown(summary.recommendations, [])} />
        </Panel>
      </section>

      <section className="grid grid-cols-2 gap-4">
        <Panel title="Connector Health">
          <div className="space-y-3">
            {connectorHealth.length ? connectorHealth.map((row) => (
              <div key={row.provider} className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-[14px] font-semibold" style={{ color: TEXT }}>{value(row.display_name || row.provider)}</div>
                    <p className="mt-1 text-[12px] leading-relaxed" style={{ color: MUTED }}>{value(row.reason)}</p>
                  </div>
                  <StatusBadge label={value(row.health)} tone={row.health === "healthy" ? "good" : "warn"} />
                </div>
                <div className="mt-3 text-[12px]" style={{ color: MUTED }}>{value(row.next_action)}</div>
              </div>
            )) : <InlineState title="No connectors recorded yet." />}
          </div>
        </Panel>
        <Panel title="Provider Breakdown">
          <div className="space-y-2">
            {breakdown.length ? breakdown.map((row) => (
              <div key={row.provider} className="grid grid-cols-4 gap-2 rounded-lg px-3 py-2 text-[12px]" style={{ background: BG, color: TEXT }}>
                <span className="font-semibold">{value(row.provider)}</span>
                <span>{value(row.connections, 0)} connections</span>
                <span>{value(row.data_sources, 0)} sources</span>
                <span>{value(row.evidence_records, 0)} records</span>
              </div>
            )) : <InlineState title="No provider activity yet." />}
          </div>
        </Panel>
      </section>
    </PageShell>
  );
}

export function Fields() {
  const workspaceId = useWorkspaceId();
  const state = usePortalResource<AnyRecord>(useCallback(() => apiClient.fields.intelligence(workspaceId), [workspaceId]));
  const fields = arrayFromUnknown<AnyRecord>(state.data?.fields, []);
  const [selected, setSelected] = useState<AnyRecord | null>(null);

  return (
    <PageShell badge="Field Intelligence" title="Fields" detail="Field/block risk, evidence coverage, confidence, and next operator action." action={<PortalButton variant="secondary" onClick={state.refresh}>Refresh</PortalButton>}>
      {state.error ? <InlineState title={state.error} /> : null}
      {state.data?.sample_mode ? <InlineState title="No field evidence yet." detail="The field view is showing a safe sample placeholder until data is uploaded or connected." /> : null}
      <section className="grid grid-cols-3 gap-4">
        {fields.map((field) => (
          <button key={field.field_id} type="button" onClick={() => setSelected(field)} className="rounded-2xl p-5 text-left" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-[17px] font-semibold" style={{ color: TEXT }}>{value(field.field_name)}</h2>
                <p className="mt-1 text-[12px]" style={{ color: MUTED }}>{value(field.crop)} · {arrayFromUnknown(field.blocks, []).join(", ") || "Block pending"}</p>
              </div>
              <StatusBadge label={`${Math.round(Number(field.confidence || 0) * 100)}%`} tone={Number(field.confidence || 0) > 0.55 ? "good" : "warn"} />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2">
              <Mini label="Evidence" value={value(field.evidence_count, 0)} />
              <Mini label="Providers" value={String(arrayFromUnknown(field.connected_providers, []).length)} />
            </div>
            <div className="mt-4">
              <ChipList items={arrayFromUnknown(field.missing_data, [])} empty="Core field data present." />
            </div>
            <p className="mt-4 text-[12px] leading-relaxed" style={{ color: MUTED }}>{value(field.next_best_action)}</p>
          </button>
        ))}
      </section>
      {selected ? <DetailDrawer title={value(selected.field_name)} onClose={() => setSelected(null)} record={selected} /> : null}
    </PageShell>
  );
}

export function Exceptions() {
  const workspaceId = useWorkspaceId();
  const state = usePortalResource<AnyRecord>(useCallback(() => apiClient.exceptions.list(workspaceId), [workspaceId]));
  const rows = arrayFromUnknown<AnyRecord>(state.data?.exceptions, []);
  const [severity, setSeverity] = useState("all");
  const visible = severity === "all" ? rows : rows.filter((row) => row.severity === severity);

  return (
    <PageShell badge="Exception Queue" title="Exceptions" detail="Ranked connector, data quality, field risk, compliance, and reporting issues." action={<PortalButton variant="secondary" onClick={state.refresh}>Refresh</PortalButton>}>
      {state.error ? <InlineState title={state.error} /> : null}
      <div className="flex flex-wrap gap-2">
        {["all", "critical", "high", "medium", "low"].map((item) => (
          <button key={item} type="button" onClick={() => setSeverity(item)} className="h-9 rounded-lg px-3 text-[12px] font-medium" style={{ background: severity === item ? "#0D2B1E" : SURFACE, border: `1px solid ${BORDER}`, color: severity === item ? "white" : TEXT }}>
            {item}
          </button>
        ))}
      </div>
      <section className="space-y-3">
        {visible.length ? visible.map((row) => (
          <article key={row.id} className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <StatusBadge label={value(row.severity)} tone={row.severity === "low" ? "neutral" : "warn"} />
                  <StatusBadge label={value(row.category)} />
                </div>
                <h2 className="text-[17px] font-semibold" style={{ color: TEXT }}>{value(row.title)}</h2>
                <p className="mt-2 text-[13px] leading-relaxed" style={{ color: MUTED }}>{value(row.explanation)}</p>
                <p className="mt-3 text-[12px]" style={{ color: MUTED }}>{value(row.recommended_action)}</p>
              </div>
              <div className="flex flex-wrap justify-end gap-2">
                <PortalButton variant="secondary">Review</PortalButton>
                <PortalButton variant="secondary" onClick={() => window.location.assign("/integrations")}>Connector</PortalButton>
                <PortalButton variant="secondary" onClick={() => window.location.assign("/evidence")}>Evidence</PortalButton>
                <PortalButton onClick={() => window.location.assign("/reports")}>Report</PortalButton>
              </div>
            </div>
          </article>
        )) : <InlineState title="No exceptions for this filter." />}
      </section>
    </PageShell>
  );
}

export function DecisionWorkbench() {
  const workspaceId = useWorkspaceId();
  const state = usePortalResource<AnyRecord>(useCallback(() => apiClient.decisions.workbench(workspaceId), [workspaceId]));
  const [mode, setMode] = useState<WorkbenchRunPayload["mode"]>("daily");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const decisions = arrayFromUnknown<AnyRecord>(state.data?.decisions, []);

  async function run() {
    setBusy(true);
    setMessage("");
    try {
      await apiClient.decisions.runWorkbench({ workspace_id: workspaceId, mode });
      await state.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Decision workbench failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageShell badge="Decision Workbench" title="Decision Workbench" detail="Evidence-backed recommendations, missing evidence, impact, and operator instructions." action={<PortalButton onClick={run} disabled={busy}>{busy ? "Running..." : "Run workbench"}</PortalButton>}>
      {state.error ? <InlineState title={state.error} /> : null}
      {message ? <InlineState title={message} /> : null}
      <select value={mode} onChange={(event) => setMode(event.target.value as WorkbenchRunPayload["mode"])} className="h-10 w-[240px] rounded-lg px-3 text-[13px] outline-none" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: TEXT }}>
        <option value="daily">Daily</option>
        <option value="field">Field</option>
        <option value="compliance">Compliance</option>
        <option value="irrigation">Irrigation</option>
      </select>
      <section className="space-y-4">
        {decisions.length ? decisions.map((decision) => (
          <DecisionPanel key={decision.id} decision={decision} />
        )) : <InlineState title="No decisions generated yet." />}
      </section>
    </PageShell>
  );
}

export function ReportFactory() {
  const workspaceId = useWorkspaceId();
  const [reportType, setReportType] = useState<ReportFactoryPayload["report_type"]>("executive_brief");
  const [audience, setAudience] = useState<ReportFactoryPayload["audience"]>("owner");
  const [report, setReport] = useState<AnyRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function generate() {
    setBusy(true);
    setMessage("");
    try {
      const response = await apiClient.reportFactory.generate({ workspace_id: workspaceId, report_type: reportType, audience }) as AnyRecord;
      setReport(response.report || null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Report factory failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageShell badge="Report Factory" title="Report Factory" detail="Structured report preview from readiness, field intelligence, exceptions, decisions, and evidence appendix." action={<PortalButton onClick={generate} disabled={busy}>{busy ? "Generating..." : "Generate preview"}</PortalButton>}>
      {message ? <InlineState title={message} /> : null}
      <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
        <div className="grid grid-cols-3 gap-3">
          <Select label="Report type" value={reportType} onChange={(next) => setReportType(next as ReportFactoryPayload["report_type"])} options={["water_use_summary", "compliance_packet", "exception_report", "executive_brief", "grower_recommendation"]} />
          <Select label="Audience" value={audience || "owner"} onChange={(next) => setAudience(next as ReportFactoryPayload["audience"])} options={["operator", "owner", "agency", "lender", "investor", "grower"]} />
          <div className="flex items-end"><PortalButton variant="secondary" onClick={() => window.location.assign("/reports")}>Existing Reports</PortalButton></div>
        </div>
      </section>
      {report ? (
        <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <h2 className="text-[20px] font-semibold" style={{ color: TEXT }}>{value(report.title)}</h2>
              <p className="mt-2 text-[13px] leading-relaxed" style={{ color: MUTED }}>{value(report.executive_summary)}</p>
            </div>
            <StatusBadge label={value(report.report_type)} tone="good" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Panel title="Key Findings"><List items={arrayFromUnknown(report.key_findings, [])} /></Panel>
            <Panel title="Missing Evidence"><ChipList items={arrayFromUnknown(report.missing_evidence, [])} empty="No missing evidence listed." /></Panel>
            <Panel title="Exceptions"><List items={arrayFromUnknown(report.exceptions, []).map((row) => row.title || row.id)} /></Panel>
            <Panel title="Next Actions"><List items={arrayFromUnknown(report.recommended_next_actions, [])} /></Panel>
          </div>
        </section>
      ) : <InlineState title="No report preview generated yet." />}
    </PageShell>
  );
}

function DecisionPanel({ decision }: { decision: AnyRecord }) {
  const [status, setStatus] = useState(value(decision.approval_status, "needs_review"));
  return (
    <article className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <StatusBadge label={value(decision.risk_level)} tone={decision.risk_level === "low" ? "good" : "warn"} />
            <StatusBadge label={`${Math.round(Number(decision.confidence || 0) * 100)}% confidence`} />
            <StatusBadge label={status} />
          </div>
          <h2 className="text-[18px] font-semibold" style={{ color: TEXT }}>{value(decision.recommendation)}</h2>
          <p className="mt-2 text-[13px] leading-relaxed" style={{ color: MUTED }}>{value(decision.why)}</p>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          {["Approve", "Reject", "Request more evidence", "Mark executed"].map((label) => (
            <PortalButton key={label} variant="secondary" onClick={() => setStatus(label.toLowerCase().replaceAll(" ", "_"))}>{label}</PortalButton>
          ))}
        </div>
      </div>
      <div className="mt-5 grid grid-cols-3 gap-4">
        <Panel title="Evidence Used"><List items={arrayFromUnknown(decision.evidence_used, []).map((row) => row.title || row.label || row)} /></Panel>
        <Panel title="Missing Evidence"><ChipList items={arrayFromUnknown(decision.missing_evidence, [])} empty="No missing evidence listed." /></Panel>
        <Panel title="Operator Instructions"><List items={arrayFromUnknown(decision.operator_instructions, [])} /></Panel>
      </div>
    </article>
  );
}

function PageShell({ badge, title, detail, action, children }: { badge: string; title: string; detail: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="mb-3"><StatusBadge label={badge} tone="good" /></div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>{title}</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>{detail}</p>
          </div>
          {action}
        </div>
      </header>
      <main className="px-8 py-6 space-y-5" style={{ maxWidth: 1280 }}>{children}</main>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><h2 className="text-[14px] font-semibold mb-4" style={{ color: TEXT }}>{title}</h2>{children}</section>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>{label}</div><div className="text-[28px] font-semibold" style={{ color: TEXT }}>{value}</div></section>;
}

function Mini({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg px-3 py-2" style={{ background: BG }}><div className="text-[10px]" style={{ color: MUTED }}>{label}</div><div className="text-[14px] font-semibold" style={{ color: TEXT }}>{value}</div></div>;
}

function ChipList({ items, empty }: { items: unknown[]; empty: string }) {
  const list = items.map((item) => value(item)).filter(Boolean);
  if (!list.length) return <div className="text-[13px]" style={{ color: MUTED }}>{empty}</div>;
  return <div className="flex flex-wrap gap-2">{list.map((item) => <span key={item} className="rounded-full px-3 py-1 text-[11px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>{item}</span>)}</div>;
}

function List({ items }: { items: unknown[] }) {
  const list = items.map((item) => value(item)).filter(Boolean);
  if (!list.length) return <div className="text-[13px]" style={{ color: MUTED }}>None listed.</div>;
  return <div className="space-y-2">{list.map((item, index) => <div key={index} className="text-[13px] leading-relaxed" style={{ color: TEXT }}>• {item}</div>)}</div>;
}

function Select({ label, value: selectedValue, options, onChange }: { label: string; value: string; options: string[]; onChange: (next: string) => void }) {
  return (
    <label className="text-[12px]" style={{ color: MUTED }}>
      {label}
      <select value={selectedValue} onChange={(event) => onChange(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
        {options.map((option) => <option key={option} value={option}>{option.replaceAll("_", " ")}</option>)}
      </select>
    </label>
  );
}

function DetailDrawer({ title, record, onClose }: { title: string; record: AnyRecord; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 flex justify-end" style={{ background: "rgba(6,29,21,0.24)" }}>
      <aside className="h-full w-[460px] overflow-auto p-6" style={{ background: SURFACE, borderLeft: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-semibold" style={{ color: TEXT }}>{title}</h2>
            <p className="mt-1 text-[13px]" style={{ color: MUTED }}>{value(record.crop)} · confidence {Math.round(Number(record.confidence || 0) * 100)}%</p>
          </div>
          <PortalButton variant="secondary" onClick={onClose}>Close</PortalButton>
        </div>
        <div className="mt-6 space-y-4">
          <Panel title="Risk Flags"><List items={arrayFromUnknown(record.risk_flags, []).map((row) => row.title || row.type)} /></Panel>
          <Panel title="Missing Data"><ChipList items={arrayFromUnknown(record.missing_data, [])} empty="No missing field data listed." /></Panel>
          <Panel title="Connected Providers"><ChipList items={arrayFromUnknown(record.connected_providers, [])} empty="No providers connected." /></Panel>
          <Panel title="Next Best Action"><p className="text-[13px] leading-relaxed" style={{ color: TEXT }}>{value(record.next_best_action)}</p></Panel>
        </div>
      </aside>
    </div>
  );
}
