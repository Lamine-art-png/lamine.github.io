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
  // Command Center already returns operator_tasks and audit_events. Keep first
  // paint to one authoritative request instead of rebuilding the same heavy
  // field context three times in parallel.
  const centerState = usePortalResource<Row>(useCallback(() => apiClient.fieldOps.commandCenter(workspaceId), [workspaceId]));
  const center = centerState.data || {};
  const queue = arr<Row>(center.field_queue);
  const tasks = arr<Row>(center.operator_tasks);
  const missing = arr<Row>(center.missing_evidence);
  const reportsReady = arr<Row>(center.reports_ready);
  const audit = arr<Row>(center.audit_events);
  const priority = center.today_priority || {};
  const autonomy = center.autonomy || {};
  const pendingApprovals = arr<Row>(autonomy.pending_approvals);
  const pendingVerification = arr<Row>(autonomy.pending_verification);
  const procedures = arr<Row>(autonomy.procedures);
  const recentRuns = arr<Row>(autonomy.recent_runs);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [updateText, setUpdateText] = useState("");
  const [eventType, setEventType] = useState("operator_note");
  const [fieldName, setFieldName] = useState("");
  const [block, setBlock] = useState("");
  const [crop, setCrop] = useState("");
  const [procedureName, setProcedureName] = useState("");
  const [procedureEventType, setProcedureEventType] = useState("issue");
  const [procedureSeverity, setProcedureSeverity] = useState("medium");
  const [procedureAutonomy, setProcedureAutonomy] = useState("4");
  const openTasks = useMemo(() => tasks.filter((task) => task.status !== "done").length, [tasks]);
  const fieldsNeedAttention = useMemo(() => queue.filter((row) => row.priority === "high" || row.status === "needs_attention").length, [queue]);

  async function refreshAll() { await centerState.refresh(); }
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
  async function setTaskStatus(taskId: string, status: string, evidenceIds: string[] = []) {
    setBusy(taskId);
    setMessage("");
    try {
      await apiClient.fieldOps.updateTaskStatus(taskId, {
        status: status as any,
        workspace_id: workspaceId,
        evidence_ids: evidenceIds,
      });
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not update task.");
    } finally {
      setBusy("");
    }
  }

  async function approveAndExecute(action: Row) {
    const actionId = String(action.id || "");
    const runId = String(action.run_id || "");
    if (!actionId || !runId) return;
    setBusy(actionId);
    setMessage("");
    try {
      const scope = action.workspace_id ? { workspace_id: String(action.workspace_id) } : {};
      await apiClient.autonomy.approveAction(runId, actionId, scope);
      await apiClient.autonomy.executeAction(runId, actionId, scope);
      setMessage("Autonomous action approved and execution recorded.");
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not approve autonomous action.");
    } finally {
      setBusy("");
    }
  }

  async function rejectAutonomyAction(action: Row) {
    const actionId = String(action.id || "");
    const runId = String(action.run_id || "");
    if (!actionId || !runId) return;
    setBusy(actionId);
    setMessage("");
    try {
      const scope = action.workspace_id ? { workspace_id: String(action.workspace_id) } : {};
      await apiClient.autonomy.rejectAction(runId, actionId, scope);
      setMessage("Autonomous action rejected.");
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not reject autonomous action.");
    } finally {
      setBusy("");
    }
  }

  async function createFieldProcedure() {
    if (!procedureName.trim()) return;
    setBusy("procedure-create");
    setMessage("");
    try {
      const created = await apiClient.autonomy.createProcedure({
        workspace_id: workspaceId,
        name: procedureName.trim(),
        domain: "field_intelligence",
        autonomy_level: Number(procedureAutonomy),
        trigger_type: "field_observation",
        definition: {
          when: {
            event_types: [procedureEventType],
            minimum_severity: procedureSeverity,
          },
        },
      }) as Row;
      await apiClient.autonomy.setProcedureStatus(String(created.id), {
        workspace_id: workspaceId,
        status: "active",
      });
      setProcedureName("");
      setMessage("Procedure created and activated.");
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create Procedure.");
    } finally {
      setBusy("");
    }
  }

  async function setProcedureStatus(procedure: Row, nextStatus: "active" | "disabled") {
    setBusy(String(procedure.id || ""));
    setMessage("");
    try {
      await apiClient.autonomy.setProcedureStatus(String(procedure.id), {
        workspace_id: procedure.workspace_id || undefined,
        status: nextStatus,
      });
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not update Procedure.");
    } finally {
      setBusy("");
    }
  }
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

        <section className="grid grid-cols-1 gap-4 xl:grid-cols-[1.15fr_0.85fr] xl:gap-5">
          <Panel title="Autonomous Operations">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <MiniMetric label="Autonomous Completion Rate" value={`${Number(autonomy.autonomous_completion_rate || 0).toFixed(1)}%`} />
              <MiniMetric label="Active workflows" value={String(autonomy.active_runs || 0)} />
              <MiniMetric label="Verified zero-touch" value={String(autonomy.zero_touch_successes || 0)} />
              <MiniMetric label="Human-assisted" value={String(autonomy.human_assisted_successes || 0)} />
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-2">
              <div>
                <div className="mb-2 text-[12px] font-semibold" style={{ color: TEXT }}>Waiting for approval</div>
                <div className="space-y-2">
                  {pendingApprovals.length ? pendingApprovals.map((action) => (
                    <AutonomyActionCard
                      key={String(action.id)}
                      action={action}
                      busy={busy}
                      onApprove={approveAndExecute}
                      onReject={rejectAutonomyAction}
                    />
                  )) : <InlineState title="No approval-gated actions are waiting." />}
                </div>
              </div>
              <div>
                <div className="mb-2 text-[12px] font-semibold" style={{ color: TEXT }}>Waiting for verification</div>
                <div className="space-y-2">
                  {pendingVerification.length ? pendingVerification.slice(0, 6).map((action) => (
                    <div key={String(action.id)} className="rounded-xl p-3" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge label="Verification required" tone="warn" />
                        <StatusBadge label={clean(action.risk_level, "low")} />
                      </div>
                      <div className="mt-2 break-words text-[13px] font-semibold" style={{ color: TEXT }}>
                        {clean((action.payload || {}).title || action.action_type)}
                      </div>
                      <div className="mt-1 text-[11px]" style={{ color: MUTED }}>{clean(action.procedure_name || action.source_type)}</div>
                    </div>
                  )) : <InlineState title="No executed actions are waiting for proof." />}
                </div>
              </div>
            </div>

            <div className="mt-5">
              <div className="mb-2 text-[12px] font-semibold" style={{ color: TEXT }}>Recent autonomous work</div>
              <div className="space-y-2">
                {recentRuns.length ? recentRuns.slice(0, 5).map((run) => (
                  <div key={String(run.id)} className="flex flex-col gap-2 rounded-xl p-3 sm:flex-row sm:items-center sm:justify-between" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                    <div className="min-w-0">
                      <div className="break-words text-[12px] font-semibold" style={{ color: TEXT }}>{clean((run.result || {}).procedure_name || run.workflow_type)}</div>
                      <div className="mt-1 text-[11px]" style={{ color: MUTED }}>{clean(run.source_type)} · {clean(run.current_step)}</div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <StatusBadge label={clean(run.status)} tone={tone(String(run.status || ""))} />
                      <StatusBadge label={`A${Number(run.autonomy_level || 0)}`} />
                    </div>
                  </div>
                )) : <InlineState title="No autonomous workflows yet." />}
              </div>
            </div>
          </Panel>

          <Panel title="Procedures">
            <div className="mb-4 rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
              <div className="text-[13px] font-semibold" style={{ color: TEXT }}>Teach AGRO-AI</div>
              <p className="mt-1 text-[12px] leading-relaxed" style={{ color: MUTED }}>Field Intelligence procedures watch completed observations and dispatch safe work under policy.</p>
              <div className="mt-3 space-y-3">
                <Input label="Procedure name" value={procedureName} onChange={setProcedureName} />
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <Select label="Event type" value={procedureEventType} onChange={setProcedureEventType} options={["issue", "observation", "irrigation_event", "meter_reading", "equipment", "pest_disease", "compliance_note", "operator_note"]} />
                  <Select label="Minimum severity" value={procedureSeverity} onChange={setProcedureSeverity} options={["low", "medium", "high", "critical"]} />
                  <Select label="Autonomy level" value={procedureAutonomy} onChange={setProcedureAutonomy} options={["2", "3", "4"]} />
                </div>
                <PortalButton onClick={createFieldProcedure} disabled={!procedureName.trim() || busy === "procedure-create"}>
                  {busy === "procedure-create" ? "Creating…" : "Create & activate"}
                </PortalButton>
              </div>
            </div>
            <div className="space-y-2">
              {procedures.length ? procedures.map((procedure) => (
                <div key={String(procedure.id)} className="rounded-xl p-3" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="break-words text-[13px] font-semibold" style={{ color: TEXT }}>{clean(procedure.name)}</div>
                      <div className="mt-1 text-[11px]" style={{ color: MUTED }}>{titleCase(clean(procedure.domain, ""))} · A{Number(procedure.autonomy_level || 0)} · v{Number(procedure.version || 1)}</div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <StatusBadge label={clean(procedure.status)} tone={procedure.status === "active" ? "good" : "neutral"} />
                      {procedure.status === "active"
                        ? <PortalButton variant="secondary" onClick={() => setProcedureStatus(procedure, "disabled")} disabled={busy === procedure.id}>Disable</PortalButton>
                        : <PortalButton variant="secondary" onClick={() => setProcedureStatus(procedure, "active")} disabled={busy === procedure.id}>Activate</PortalButton>}
                    </div>
                  </div>
                </div>
              )) : <InlineState title="No procedures configured yet." />}
            </div>
          </Panel>
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

function TaskCard({ task, busy, onStatus }: { task: Row; busy: string; onStatus: (id: string, status: string, evidenceIds?: string[]) => void }) {
  const [proofOpen, setProofOpen] = useState(false);
  const [proofLoading, setProofLoading] = useState(false);
  const [proofOptions, setProofOptions] = useState<Row[]>([]);
  const [proofId, setProofId] = useState("");
  const [proofError, setProofError] = useState("");

  async function completeTask() {
    if (!task.requires_verification) {
      onStatus(String(task.id), "done");
      return;
    }
    if (!proofOpen) {
      setProofOpen(true);
      setProofLoading(true);
      setProofError("");
      try {
        const response = await apiClient.evidence.list() as Row;
        const accepted = new Set(["verified", "accepted", "validated", "complete", "good", "ok", "usable", "live"]);
        const rows = arr<Row>(response.evidence).filter((row) => {
          const sameWorkspace = !task.workspace_id || String(row.workspace_id || "") === String(task.workspace_id);
          return sameWorkspace && accepted.has(String(row.quality_status || "").toLowerCase());
        });
        setProofOptions(rows);
        if (rows[0]?.id) setProofId(String(rows[0].id));
      } catch (error) {
        setProofError(error instanceof Error ? error.message : "Could not load evidence.");
      } finally {
        setProofLoading(false);
      }
      return;
    }
    if (proofId) onStatus(String(task.id), "done", [proofId]);
  }

  return (
    <article className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <StatusBadge label={clean(task.priority, "medium")} tone={task.priority === "high" ? "warn" : "neutral"} />
        <StatusBadge label={clean(task.status, "open")} tone={tone(String(task.status || "open"))} />
        {task.requires_verification ? <StatusBadge label="Verification required" tone="warn" /> : null}
      </div>
      <div className="break-words text-[14px] font-semibold" style={{ color: TEXT }}>{clean(task.title)}</div>
      <div className="mt-1 break-words text-[12px] leading-relaxed" style={{ color: MUTED }}>{clean(task.why)}</div>
      <List items={lines(task.instructions)} />
      <Chips items={lines(task.evidence_required || task.missing_evidence)} empty="No required evidence listed." />
      {proofOpen && task.requires_verification ? (
        <div className="mt-3 rounded-xl p-3" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <label className="text-[12px]" style={{ color: MUTED }}>Verification evidence
            <select
              aria-label="Verification evidence"
              value={proofId}
              onChange={(event) => setProofId(event.target.value)}
              className="mt-1 h-10 w-full rounded-lg px-3 text-[13px] outline-none"
              style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}
            >
              <option value="">Select evidence</option>
              {proofOptions.map((row) => <option key={String(row.id)} value={String(row.id)}>{clean(row.title || row.summary || row.id)}</option>)}
            </select>
          </label>
          {proofLoading ? <div className="mt-2 text-[11px]" style={{ color: MUTED }}>Load evidence</div> : null}
          {!proofLoading && !proofOptions.length ? (
            <div className="mt-2">
              <div className="text-[11px]" style={{ color: MUTED }}>No eligible evidence is available in this workspace.</div>
              <PortalButton variant="secondary" onClick={() => window.location.assign("/evidence")}>Upload evidence</PortalButton>
            </div>
          ) : null}
          {proofError ? <div className="mt-2 text-[11px]" style={{ color: MUTED }}>{proofError}</div> : null}
        </div>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2">
        <PortalButton variant="secondary" onClick={() => onStatus(String(task.id), "open")} disabled={busy === task.id}>Reopen</PortalButton>
        <PortalButton variant="secondary" onClick={() => onStatus(String(task.id), "in_progress")} disabled={busy === task.id}>Start</PortalButton>
        <PortalButton variant="secondary" onClick={completeTask} disabled={busy === task.id || (proofOpen && task.requires_verification && !proofId)}>
          {proofOpen && task.requires_verification ? "Verify & complete" : "Done"}
        </PortalButton>
      </div>
    </article>
  );
}

function AutonomyActionCard({ action, busy, onApprove, onReject }: { action: Row; busy: string; onApprove: (action: Row) => void; onReject: (action: Row) => void }) {
  return (
    <div className="rounded-xl p-3" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge label="Waiting for approval" tone="warn" />
        <StatusBadge label={clean(action.risk_level, "medium")} />
      </div>
      <div className="mt-2 break-words text-[13px] font-semibold" style={{ color: TEXT }}>{clean((action.payload || {}).title || action.action_type)}</div>
      <div className="mt-1 break-words text-[11px]" style={{ color: MUTED }}>{clean((action.payload || {}).description || action.procedure_name)}</div>
      <div className="mt-3 flex flex-wrap gap-2">
        <PortalButton onClick={() => onApprove(action)} disabled={busy === action.id}>Approve & execute</PortalButton>
        <PortalButton variant="secondary" onClick={() => onReject(action)} disabled={busy === action.id}>Reject</PortalButton>
      </div>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl p-3" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: MUTED }}>{label}</div><div className="mt-1 text-[20px] font-semibold" style={{ color: TEXT }}>{value}</div></div>;
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
