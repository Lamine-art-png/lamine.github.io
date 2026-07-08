import { useCallback, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type Row = Record<string, any>;
function arr<T = Row>(value: unknown): T[] { return Array.isArray(value) ? value as T[] : []; }
function titleCase(value: string) { return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()); }
function clean(value: unknown, fallback = "—"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (["string", "number", "boolean"].includes(typeof value)) return String(value).replaceAll("_", " ");
  if (Array.isArray(value)) return value.map((item) => clean(item, "")).filter(Boolean).join("; ") || fallback;
  if (typeof value === "object") {
    const row = value as Row;
    const preferred = row.title || row.summary || row.name || row.label || row.field_name || row.field || row.block || row.status || row.message || row.note || row.description || row.why || row.recommended_action || row.value;
    if (preferred) return clean(preferred, fallback);
    return Object.entries(row).filter(([, v]) => v !== null && v !== undefined && v !== "" && typeof v !== "object").slice(0, 3).map(([k, v]) => `${titleCase(k)}: ${String(v).replaceAll("_", " ")}`).join(" · ") || fallback;
  }
  return fallback;
}
function lines(value: unknown): string[] { return arr(value).map((item) => clean(item, "")).filter(Boolean); }
function tone(status: string): "neutral" | "good" | "warn" | "locked" { if (["ready", "monitoring", "done", "completed", "synced"].includes(status)) return "good"; if (["needs_attention", "blocked", "missing_evidence", "needs_review"].includes(status)) return "warn"; return "neutral"; }

export function Overview() {
  const { currentWorkspace } = useAuth();
  const workspaceId = currentWorkspace?.id;
  const centerState = usePortalResource<Row>(useCallback(() => apiClient.fieldOps.commandCenter(workspaceId), [workspaceId]));
  const tasksState = usePortalResource<Row>(useCallback(() => apiClient.fieldOps.tasks(workspaceId), [workspaceId]));
  const auditState = usePortalResource<Row>(useCallback(() => apiClient.fieldOps.auditTrail(workspaceId), [workspaceId]));
  const center = centerState.data || {};
  const queue = arr<Row>(center.field_queue);
  const tasks = arr<Row>(tasksState.data?.tasks || center.operator_tasks);
  const missing = arr<Row>(center.missing_evidence);
  const reportsReady = arr<Row>(center.reports_ready);
  const audit = arr<Row>(auditState.data?.events || center.audit_events);
  const priority = center.today_priority || {};
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [updateText, setUpdateText] = useState("");
  const [eventType, setEventType] = useState("operator_note");
  const [fieldName, setFieldName] = useState("");
  const [block, setBlock] = useState("");
  const [crop, setCrop] = useState("");
  const openTasks = useMemo(() => tasks.filter((task) => task.status !== "done").length, [tasks]);
  const fieldsNeedAttention = useMemo(() => queue.filter((row) => row.priority === "high" || row.status === "needs_attention").length, [queue]);

  async function refreshAll() { await Promise.all([centerState.refresh(), tasksState.refresh(), auditState.refresh()]); }
  async function createTask(item: Row) {
    setBusy(clean(item.field_id || item.field_name, "task"));
    setMessage("");
    try {
      await apiClient.fieldOps.createTask({
        title: clean(item.next_operator_task || `Review ${clean(item.field_name, "field")}`),
        field: clean(item.field_name, ""),
        priority: item.priority || "medium",
        why: clean(item.recommended_action || item.issue || "Field requires attention."),
        instructions: [clean(item.recommended_action || "Review the field and collect missing evidence.")],
        evidence_required: lines(item.missing_evidence),
        created_from: "missing_evidence",
        workspace_id: workspaceId,
      });
      setMessage("Operator task created.");
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create task.");
    } finally {
      setBusy("");
    }
  }
  async function setTaskStatus(taskId: string, status: string) { setBusy(taskId); try { await apiClient.fieldOps.updateTaskStatus(taskId, { status: status as any, workspace_id: workspaceId }); await refreshAll(); } finally { setBusy(""); } }
  async function addUpdate() {
    if (!updateText.trim()) return;
    setBusy("field-update");
    setMessage("");
    try {
      await apiClient.fieldOps.fieldUpdate({ field_name: fieldName || undefined, block: block || undefined, crop: crop || undefined, update_text: updateText, event_type: eventType as any, workspace_id: workspaceId });
      setUpdateText("");
      setMessage("Field update recorded.");
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not record field update.");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="min-h-full" style={{ background: BG }}>
      <header className="px-4 py-5 sm:px-8 sm:py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <StatusBadge label={clean(center.operating_status, "monitoring")} tone={tone(String(center.operating_status || "monitoring"))} />
              <StatusBadge label={fieldsNeedAttention ? `${fieldsNeedAttention} fields need attention` : "Ready for review"} tone={fieldsNeedAttention ? "warn" : "good"} />
            </div>
            <h1 className="text-[26px] font-semibold tracking-tight sm:text-[30px]" style={{ color: TEXT }}>Command Center</h1>
            <p className="mt-2 max-w-3xl text-[13px] leading-relaxed sm:text-[14px]" style={{ color: MUTED }}>Field queue, tasks, evidence gaps, reports, and audit follow-through in one operating room.</p>
          </div>
          <div className="flex-shrink-0"><PortalButton variant="secondary" onClick={refreshAll}>Refresh</PortalButton></div>
        </div>
      </header>

      <main className="space-y-4 px-4 py-4 sm:space-y-5 sm:px-8 sm:py-6" style={{ maxWidth: 1280 }}>
        {centerState.error ? <InlineState title="Command Center unavailable" detail={centerState.error} /> : null}
        {message ? <InlineState title={message} /> : null}

        <section className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 xl:grid-cols-5 xl:gap-4">
          <Metric label="Today’s priority" value={clean(priority.field || priority.title, "Monitor workspace")} detail={clean(priority.risk, "low")} />
          <Metric label="Operating status" value={clean(center.operating_status, "monitoring")} detail={clean(priority.reason, "Field operations are under review.")} />
          <Metric label="Fields needing attention" value={String(fieldsNeedAttention)} detail={clean(priority.recommended_action, "Review field queue")} />
          <Metric label="Open tasks" value={String(openTasks)} detail="Track work in progress" />
          <Metric label="Reports ready" value={String(reportsReady.length)} detail="Daily handoff available" />
        </section>

        <section className="grid grid-cols-1 gap-4 xl:grid-cols-[1.2fr_0.8fr] xl:gap-5">
          <Panel title="Field Queue">
            <div className="space-y-3">{queue.length ? queue.map((item, index) => <QueueCard key={index} item={item} busy={busy} onTask={createTask} />) : <InlineState title="No field queue items yet." detail="Add a field update or connect evidence to populate today’s queue." />}</div>
          </Panel>
          <Panel title="Operator Tasks">
            <div className="space-y-3">{tasks.length ? tasks.map((task, index) => <TaskCard key={task.id || index} task={task} busy={busy} onStatus={setTaskStatus} />) : <InlineState title="No operator tasks yet." detail="Field exceptions and missing evidence will create tasks here." />}</div>
          </Panel>
        </section>

        <section className="grid grid-cols-1 gap-4 xl:grid-cols-2 xl:gap-5">
          <Panel title="Field Update Intake">
            <div className="space-y-3">
              <textarea value={updateText} onChange={(event) => setUpdateText(event.target.value)} rows={5} placeholder="Tell AGRO-AI what happened in the field…" className="w-full resize-none rounded-xl px-4 py-4 text-[14px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Input label="Field" value={fieldName} onChange={setFieldName} />
                <Input label="Block" value={block} onChange={setBlock} />
                <Input label="Crop" value={crop} onChange={setCrop} />
                <Select label="Event type" value={eventType} onChange={setEventType} options={["operator_note", "observation", "meter_reading", "irrigation_event", "issue", "photo_note", "compliance_note"]} />
              </div>
              <PortalButton onClick={addUpdate} disabled={busy === "field-update"}>{busy === "field-update" ? "Adding…" : "Add field update"}</PortalButton>
            </div>
          </Panel>
          <Panel title="Missing Evidence">
            <div className="space-y-3">
              {missing.length ? missing.map((item, index) => (
                <div key={index} className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                  <div className="break-words text-[14px] font-semibold" style={{ color: TEXT }}>{clean(item.item)}</div>
                  <div className="mt-1 break-words text-[12px]" style={{ color: MUTED }}>{clean(item.why_it_matters)}</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <PortalButton variant="secondary" onClick={() => window.location.assign("/evidence")}>Upload file</PortalButton>
                    <PortalButton variant="secondary" onClick={() => window.location.assign("/integrations")}>Connect source</PortalButton>
                    <PortalButton variant="secondary" onClick={() => createTask({ field_name: "Workspace", next_operator_task: `Collect ${clean(item.item)}`, recommended_action: clean(item.why_it_matters), priority: "medium", missing_evidence: [item.item] })}>Assign task</PortalButton>
                  </div>
                </div>
              )) : <InlineState title="Core evidence is available." detail="No blocking evidence gaps are listed right now." />}
            </div>
          </Panel>
        </section>

        <Panel title="Audit Trail">
          <div className="grid gap-3 md:grid-cols-2">
            {audit.length ? audit.slice(0, 8).map((item, index) => (
              <div key={index} className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0 break-words text-[13px] font-semibold" style={{ color: TEXT }}>{clean(item.title)}</div><StatusBadge label={clean(item.event_type)} /></div>
                <div className="mt-1 break-words text-[12px]" style={{ color: MUTED }}>{clean(item.detail)}</div>
                <div className="mt-1 text-[11px]" style={{ color: MUTED }}>{clean(item.timestamp, "recent")}</div>
              </div>
            )) : <InlineState title="No audit events yet." detail="Uploads, field updates, tasks, decisions, and reports will appear here." />}
          </div>
        </Panel>
      </main>
    </div>
  );
}

function QueueCard({ item, busy, onTask }: { item: Row; busy: string; onTask: (item: Row) => void }) {
  const key = clean(item.field_id || item.field_name, "task");
  return (
    <article className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2"><StatusBadge label={clean(item.priority, "medium")} tone={item.priority === "high" ? "warn" : "neutral"} /><StatusBadge label={clean(item.status, "ready")} tone={tone(String(item.status || "ready"))} /></div>
          <h2 className="break-words text-[16px] font-semibold" style={{ color: TEXT }}>{clean(item.field_name, "Field")}</h2>
          <p className="mt-1 break-words text-[13px] leading-relaxed" style={{ color: MUTED }}>{clean(item.issue, "No issue described yet.")}</p>
          <Info label="Recommended action" value={clean(item.recommended_action)} />
          <Info label="Latest signal" value={clean(item.latest_signal)} />
          <Chips items={lines(item.missing_evidence)} empty="No missing evidence listed." />
        </div>
        <div className="flex-shrink-0"><PortalButton variant="secondary" onClick={() => onTask(item)} disabled={busy === key}>{busy === key ? "Creating…" : "Create task"}</PortalButton></div>
      </div>
    </article>
  );
}

function TaskCard({ task, busy, onStatus }: { task: Row; busy: string; onStatus: (id: string, status: string) => void }) {
  return (
    <article className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="mb-2 flex flex-wrap items-center gap-2"><StatusBadge label={clean(task.priority, "medium")} tone={task.priority === "high" ? "warn" : "neutral"} /><StatusBadge label={clean(task.status, "open")} tone={tone(String(task.status || "open"))} /></div>
      <div className="break-words text-[14px] font-semibold" style={{ color: TEXT }}>{clean(task.title)}</div>
      <div className="mt-1 break-words text-[12px] leading-relaxed" style={{ color: MUTED }}>{clean(task.why)}</div>
      <List items={lines(task.instructions)} />
      <Chips items={lines(task.evidence_required || task.missing_evidence)} empty="No required evidence listed." />
      <div className="mt-3 flex flex-wrap gap-2">{[["open", "Reopen"], ["in_progress", "Start"], ["done", "Done"]].map(([status, label]) => <PortalButton key={status} variant="secondary" onClick={() => onStatus(String(task.id), status)} disabled={busy === task.id}>{label}</PortalButton>)}</div>
    </article>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <section className="rounded-2xl p-4 sm:p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="mb-2 text-[9px] font-semibold uppercase tracking-widest sm:text-[10px]" style={{ color: MUTED }}>{label}</div><div className="break-words text-[21px] font-semibold sm:text-[24px]" style={{ color: TEXT }}>{value}</div><div className="mt-1 break-words text-[11px] sm:text-[12px]" style={{ color: MUTED }}>{detail}</div></section>;
}
function Panel({ title, children }: { title: string; children: ReactNode }) { return <section className="rounded-2xl p-4 sm:p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><h2 className="mb-4 text-[15px] font-semibold" style={{ color: TEXT }}>{title}</h2>{children}</section>; }
function Info({ label, value }: { label: string; value: string }) { if (!value || value === "—") return null; return <div className="mt-2 break-words text-[12px]" style={{ color: MUTED }}><strong style={{ color: TEXT }}>{label}: </strong>{value}</div>; }
function Chips({ items, empty }: { items: string[]; empty: string }) { if (!items.length) return <div className="mt-3 text-[12px]" style={{ color: MUTED }}>{empty}</div>; return <div className="mt-3 flex flex-wrap gap-2">{items.map((item) => <span key={item} className="max-w-full break-words rounded-full px-3 py-1 text-[11px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: TEXT }}>{item}</span>)}</div>; }
function List({ items }: { items: string[] }) { if (!items.length) return null; return <div className="mt-2 space-y-1">{items.map((item, index) => <div key={index} className="break-words text-[12px] leading-relaxed" style={{ color: MUTED }}>• {item}</div>)}</div>; }
function Input({ label, value, onChange }: { label: string; value: string; onChange: (next: string) => void }) { return <label className="text-[12px]" style={{ color: MUTED }}>{label}<input value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 h-11 w-full rounded-lg px-3 text-[16px] outline-none sm:h-10 sm:text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} /></label>; }
function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (next: string) => void; options: string[] }) { return <label className="text-[12px]" style={{ color: MUTED }}>{label}<select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 h-11 w-full rounded-lg px-3 text-[16px] outline-none sm:h-10 sm:text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>{options.map((option) => <option key={option} value={option}>{titleCase(option)}</option>)}</select></label>; }
