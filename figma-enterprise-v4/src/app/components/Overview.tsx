import { useCallback, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;

function asArray<T = AnyRecord>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
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

function toneForStatus(status: string): "neutral" | "good" | "warn" | "locked" {
  if (status === "ready" || status === "monitoring") return "good";
  if (status === "done") return "good";
  if (status === "needs_attention" || status === "blocked" || status === "missing_evidence") return "warn";
  return "neutral";
}

export function Overview() {
  const { currentWorkspace } = useAuth();
  const workspaceId = currentWorkspace?.id;
  const centerState = usePortalResource<AnyRecord>(useCallback(() => apiClient.fieldOps.commandCenter(workspaceId), [workspaceId]));
  const tasksState = usePortalResource<AnyRecord>(useCallback(() => apiClient.fieldOps.tasks(workspaceId), [workspaceId]));
  const auditState = usePortalResource<AnyRecord>(useCallback(() => apiClient.fieldOps.auditTrail(workspaceId), [workspaceId]));

  const center = centerState.data || {};
  const tasks = asArray<AnyRecord>(tasksState.data?.tasks || center.operator_tasks);
  const queue = asArray<AnyRecord>(center.field_queue);
  const missing = asArray<AnyRecord>(center.missing_evidence);
  const reportsReady = asArray<AnyRecord>(center.reports_ready);
  const audit = asArray<AnyRecord>(auditState.data?.events || center.audit_events);

  const [updateText, setUpdateText] = useState("");
  const [eventType, setEventType] = useState("operator_note");
  const [fieldName, setFieldName] = useState("");
  const [block, setBlock] = useState("");
  const [crop, setCrop] = useState("");
  const [waterGallons, setWaterGallons] = useState("");
  const [flowGpm, setFlowGpm] = useState("");
  const [durationMinutes, setDurationMinutes] = useState("");
  const [reportAudience, setReportAudience] = useState("manager");
  const [reportScope, setReportScope] = useState("today");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [updateResult, setUpdateResult] = useState<AnyRecord | null>(null);
  const [reportResult, setReportResult] = useState<AnyRecord | null>(null);

  const openTasks = useMemo(() => tasks.filter((task) => task.status !== "done").length, [tasks]);
  const fieldsNeedAttention = useMemo(() => queue.filter((row) => row.priority === "high" || row.status === "needs_attention").length, [queue]);
  const priority = center.today_priority || {};

  async function refreshAll() {
    await Promise.all([centerState.refresh(), tasksState.refresh(), auditState.refresh()]);
  }

  async function createTaskFromQueue(item: AnyRecord) {
    setBusy(item.field_id || item.field_name || "task");
    setMessage("");
    try {
      await apiClient.fieldOps.createTask({
        title: item.next_operator_task || `Review ${item.field_name}`,
        field: item.field_name,
        priority: item.priority || "medium",
        why: item.recommended_action || item.issue || "Field requires attention.",
        instructions: [item.recommended_action || "Review the field and collect missing evidence."],
        evidence_required: asArray(item.missing_evidence).map(String),
        created_from: "missing_evidence",
        workspace_id: workspaceId,
      });
      setMessage("Operator task created.");
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create operator task.");
    } finally {
      setBusy("");
    }
  }

  async function updateTaskStatus(taskId: string, status: "open" | "in_progress" | "blocked" | "done" | "needs_review") {
    setBusy(taskId);
    setMessage("");
    try {
      await apiClient.fieldOps.updateTaskStatus(taskId, { status, workspace_id: workspaceId });
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not update task status.");
    } finally {
      setBusy("");
    }
  }

  async function addFieldUpdate() {
    if (!updateText.trim()) return;
    setBusy("field-update");
    setMessage("");
    try {
      const result = await apiClient.fieldOps.fieldUpdate({
        field_name: fieldName || undefined,
        block: block || undefined,
        crop: crop || undefined,
        update_text: updateText,
        event_type: eventType as any,
        water_gallons: waterGallons ? Number(waterGallons) : undefined,
        flow_gpm: flowGpm ? Number(flowGpm) : undefined,
        duration_minutes: durationMinutes ? Number(durationMinutes) : undefined,
        workspace_id: workspaceId,
      }) as AnyRecord;
      setUpdateResult(result);
      setMessage("Field update recorded.");
      setUpdateText("");
      setWaterGallons("");
      setFlowGpm("");
      setDurationMinutes("");
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not record field update.");
    } finally {
      setBusy("");
    }
  }

  async function autopilotReport() {
    setBusy("autopilot");
    setMessage("");
    try {
      const result = await apiClient.fieldOps.autopilotReport({
        audience: reportAudience as any,
        scope: reportScope as any,
        workspace_id: workspaceId,
      }) as AnyRecord;
      setReportResult(result);
      setMessage("Report ready.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not generate report.");
    } finally {
      setBusy("");
    }
  }

  async function downloadPdf() {
    if (!reportResult?.pdf_request) return;
    setBusy("pdf");
    setMessage("");
    try {
      const blob = await apiClient.reportFactory.pdf(reportResult.pdf_request);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `agro-ai-${reportResult.pdf_request.report_type}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setMessage("Report ready. PDF export needs retry.");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <StatusBadge label={text(center.operating_status, "monitoring").replaceAll("_", " ")} tone={toneForStatus(String(center.operating_status || "monitoring"))} />
              <StatusBadge label={fieldsNeedAttention ? `${fieldsNeedAttention} fields need attention` : "Ready for review"} tone={fieldsNeedAttention ? "warn" : "good"} />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Command Center</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              The daily operating room for field signals, operator tasks, missing evidence, decisions, reports, and audit-ready follow-through.
            </p>
          </div>
          <div className="flex gap-2">
            <PortalButton variant="secondary" onClick={refreshAll}>Refresh</PortalButton>
            <PortalButton onClick={autopilotReport} disabled={busy === "autopilot"}>{busy === "autopilot" ? "Preparing…" : "Generate report"}</PortalButton>
          </div>
        </div>
      </header>

      <main className="px-8 py-6 space-y-5" style={{ maxWidth: 1280 }}>
        {centerState.error ? <InlineState title="Command Center unavailable" detail={centerState.error} /> : null}
        {tasksState.error ? <InlineState title={tasksState.error} /> : null}
        {auditState.error ? <InlineState title={auditState.error} /> : null}
        {message ? <InlineState title={message} /> : null}

        <section className="grid grid-cols-5 gap-4">
          <Metric label="Today’s priority" value={text(priority.field || priority.title, "Monitor workspace")} detail={text(priority.risk, "low")} />
          <Metric label="Operating status" value={text(center.operating_status, "monitoring").replaceAll("_", " ")} detail={text(priority.reason, "Field operations are under review.")} />
          <Metric label="Fields needing attention" value={String(fieldsNeedAttention)} detail={text(priority.recommended_action, "Review field queue")} />
          <Metric label="Open operator tasks" value={String(openTasks)} detail="Track work in progress" />
          <Metric label="Reports ready" value={String(reportsReady.length)} detail="Daily handoff available" />
        </section>

        <section className="grid gap-5" style={{ gridTemplateColumns: "1.2fr 0.8fr" }}>
          <Panel title="Field Queue">
            <div className="space-y-3">
              {queue.length ? queue.map((item) => (
                <article key={text(item.field_id || item.field_name)} className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <StatusBadge label={text(item.priority, "medium")} tone={item.priority === "high" ? "warn" : "neutral"} />
                        <StatusBadge label={text(item.status, "ready").replaceAll("_", " ")} tone={toneForStatus(String(item.status || "ready"))} />
                      </div>
                      <h2 className="text-[16px] font-semibold" style={{ color: TEXT }}>{text(item.field_name, "Field")}</h2>
                      <p className="mt-1 text-[13px]" style={{ color: MUTED }}>{text(item.issue)}</p>
                      <p className="mt-2 text-[12px]" style={{ color: MUTED }}>Recommended action: {text(item.recommended_action)}</p>
                      <p className="mt-1 text-[12px]" style={{ color: MUTED }}>Latest signal: {text(item.latest_signal)}</p>
                      <ChipRow items={asArray(item.missing_evidence).map(String)} empty="No missing evidence listed." />
                    </div>
                    <div className="flex flex-col gap-2">
                      <PortalButton variant="secondary" onClick={() => createTaskFromQueue(item)} disabled={busy === (item.field_id || item.field_name)}>{busy === (item.field_id || item.field_name) ? "Creating…" : "Create task"}</PortalButton>
                      <PortalButton variant="secondary" onClick={autopilotReport}>Generate report</PortalButton>
                    </div>
                  </div>
                </article>
              )) : <InlineState title="No field queue items yet." detail="Add a field update or connect evidence to populate today’s queue." />}
            </div>
          </Panel>

          <Panel title="Operator Tasks">
            <div className="space-y-3">
              {tasks.length ? tasks.map((task) => (
                <article key={task.id} className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <StatusBadge label={text(task.priority, "medium")} tone={task.priority === "high" ? "warn" : "neutral"} />
                        <StatusBadge label={text(task.status, "open").replaceAll("_", " ")} tone={toneForStatus(String(task.status || "open"))} />
                      </div>
                      <div className="text-[14px] font-semibold" style={{ color: TEXT }}>{text(task.title)}</div>
                      <div className="mt-1 text-[12px]" style={{ color: MUTED }}>{text(task.why)}</div>
                      <List items={asArray(task.instructions)} />
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {["open", "in_progress", "done"].map((status) => (
                      <PortalButton key={status} variant="secondary" onClick={() => updateTaskStatus(String(task.id), status as any)} disabled={busy === task.id}>
                        {status === "in_progress" ? "Start" : status === "done" ? "Done" : "Reopen"}
                      </PortalButton>
                    ))}
                  </div>
                </article>
              )) : <InlineState title="No operator tasks yet." detail="Missing evidence and field exceptions will create tasks here." />}
            </div>
          </Panel>
        </section>

        <section className="grid gap-5" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Panel title="Field Update Intake">
            <div className="space-y-3">
              <textarea
                value={updateText}
                onChange={(event) => setUpdateText(event.target.value)}
                rows={5}
                placeholder="Tell AGRO-AI what happened in the field…"
                className="w-full resize-none rounded-xl px-4 py-4 text-[14px] outline-none"
                style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}
              />
              <div className="grid grid-cols-3 gap-3">
                <Input label="Field" value={fieldName} onChange={setFieldName} />
                <Input label="Block" value={block} onChange={setBlock} />
                <Input label="Crop" value={crop} onChange={setCrop} />
                <Select label="Event type" value={eventType} onChange={setEventType} options={["operator_note", "observation", "meter_reading", "irrigation_event", "issue", "photo_note", "compliance_note"]} />
                <Input label="Water gallons" value={waterGallons} onChange={setWaterGallons} />
                <Input label="Flow GPM" value={flowGpm} onChange={setFlowGpm} />
                <Input label="Duration minutes" value={durationMinutes} onChange={setDurationMinutes} />
              </div>
              <PortalButton onClick={addFieldUpdate} disabled={busy === "field-update"}>{busy === "field-update" ? "Adding…" : "Add field update"}</PortalButton>
              {updateResult ? (
                <div className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                  <div className="text-[13px] font-semibold" style={{ color: TEXT }}>{text(updateResult.understood_summary)}</div>
                  <List items={asArray(updateResult.created_evidence).map((row) => row.title || row.id)} />
                  <div className="mt-2 text-[12px]" style={{ color: MUTED }}>Next action: {text(updateResult.recommended_next_action)}</div>
                </div>
              ) : null}
            </div>
          </Panel>

          <Panel title="Missing Evidence">
            <div className="space-y-3">
              {missing.length ? missing.map((item, index) => (
                <div key={`${item.item}-${index}`} className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                  <div className="text-[14px] font-semibold" style={{ color: TEXT }}>{text(item.item)}</div>
                  <div className="mt-1 text-[12px]" style={{ color: MUTED }}>{text(item.why_it_matters)}</div>
                  <div className="mt-3 flex gap-2">
                    <PortalButton variant="secondary" onClick={() => window.location.assign("/evidence")}>Upload file</PortalButton>
                    <PortalButton variant="secondary" onClick={() => window.location.assign("/integrations")}>Connect source</PortalButton>
                    <PortalButton variant="secondary" onClick={() => createTaskFromQueue({ field_name: "Workspace", next_operator_task: `Collect ${item.item}`, recommended_action: item.why_it_matters, priority: "medium", missing_evidence: [item.item] })}>Assign task</PortalButton>
                  </div>
                </div>
              )) : <InlineState title="Core evidence is available." detail="No blocking evidence gaps are listed right now." />}
            </div>
          </Panel>
        </section>

        <section className="grid gap-5" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Panel title="Autopilot Report">
            <div className="grid grid-cols-2 gap-3">
              <Select label="Audience" value={reportAudience} onChange={setReportAudience} options={["operator", "manager", "owner", "agency", "lender", "grower"]} />
              <Select label="Scope" value={reportScope} onChange={setReportScope} options={["today", "weekly", "field", "compliance", "exceptions"]} />
            </div>
            <div className="mt-4 flex gap-2">
              <PortalButton onClick={autopilotReport} disabled={busy === "autopilot"}>{busy === "autopilot" ? "Generating…" : "Generate report"}</PortalButton>
              <PortalButton variant="secondary" onClick={downloadPdf} disabled={!reportResult?.pdf_request || busy === "pdf"}>{busy === "pdf" ? "Preparing…" : "Download PDF"}</PortalButton>
            </div>
            {reportResult?.report ? (
              <div className="mt-4 rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                <div className="text-[15px] font-semibold" style={{ color: TEXT }}>{text(reportResult.report.title)}</div>
                <div className="mt-2 text-[13px] leading-relaxed" style={{ color: MUTED }}>{text(reportResult.report.executive_summary)}</div>
              </div>
            ) : null}
          </Panel>

          <Panel title="Audit Trail">
            <div className="space-y-3">
              {audit.length ? audit.slice(0, 8).map((item, index) => (
                <div key={`${item.event_type}-${index}`} className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-[13px] font-semibold" style={{ color: TEXT }}>{text(item.title)}</div>
                    <StatusBadge label={text(item.event_type).replaceAll("_", " ")} />
                  </div>
                  <div className="mt-1 text-[12px]" style={{ color: MUTED }}>{text(item.detail)}</div>
                  <div className="mt-1 text-[11px]" style={{ color: MUTED }}>{text(item.timestamp, "recent")}</div>
                </div>
              )) : <InlineState title="No audit events yet." detail="Uploads, field updates, tasks, decisions, and reports will appear here." />}
            </div>
          </Panel>
        </section>
      </main>
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>{label}</div>
      <div className="text-[24px] font-semibold" style={{ color: TEXT }}>{value}</div>
      <div className="mt-1 text-[12px]" style={{ color: MUTED }}>{detail}</div>
    </section>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <h2 className="text-[15px] font-semibold mb-4" style={{ color: TEXT }}>{title}</h2>
      {children}
    </section>
  );
}

function ChipRow({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <div className="mt-3 text-[12px]" style={{ color: MUTED }}>{empty}</div>;
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {items.map((item) => (
        <span key={item} className="rounded-full px-3 py-1 text-[11px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: TEXT }}>
          {item}
        </span>
      ))}
    </div>
  );
}

function List({ items }: { items: unknown[] }) {
  const rows = items.map((item) => text(item)).filter(Boolean);
  if (!rows.length) return null;
  return (
    <div className="mt-2 space-y-1">
      {rows.map((item, index) => (
        <div key={index} className="text-[12px] leading-relaxed" style={{ color: MUTED }}>• {item}</div>
      ))}
    </div>
  );
}

function Input({ label, value, onChange }: { label: string; value: string; onChange: (next: string) => void }) {
  return (
    <label className="text-[12px]" style={{ color: MUTED }}>
      {label}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 h-10 w-full rounded-lg px-3 text-[13px] outline-none"
        style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}
      />
    </label>
  );
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (next: string) => void; options: string[] }) {
  return (
    <label className="text-[12px]" style={{ color: MUTED }}>
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
        {options.map((option) => <option key={option} value={option}>{option.replaceAll("_", " ")}</option>)}
      </select>
    </label>
  );
}
