import { useCallback, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type Row = Record<string, any>;

function arr<T = Row>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function titleCase(value: string) {
  return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function clean(value: unknown, fallback = "—"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (["string", "number", "boolean"].includes(typeof value)) return String(value).replaceAll("_", " ");
  if (Array.isArray(value)) return value.map((item) => clean(item, "")).filter(Boolean).join("; ") || fallback;
  if (typeof value === "object") {
    const row = value as Row;
    const preferred = row.title || row.summary || row.name || row.label || row.field_name || row.field || row.block || row.status || row.message || row.note || row.description || row.why || row.recommended_action || row.signal || row.value;
    if (preferred) return clean(preferred, fallback);
    return Object.entries(row)
      .filter(([, v]) => v !== null && v !== undefined && v !== "" && typeof v !== "object")
      .slice(0, 3)
      .map(([k, v]) => titleCase(k) + ": " + String(v).replaceAll("_", " "))
      .join(" · ") || fallback;
  }
  return fallback;
}

function lines(value: unknown): string[] {
  return arr(value).map((item) => clean(item, "")).filter(Boolean);
}

function tone(status: string): "neutral" | "good" | "warn" | "locked" {
  if (["ready", "monitoring", "done", "completed", "synced", "low"].includes(status)) return "good";
  if (["needs_attention", "blocked", "missing_evidence", "needs_review", "high"].includes(status)) return "warn";
  return "neutral";
}

function go(path: string) {
  window.location.assign(path);
}

export function Overview() {
  const { currentWorkspace } = useAuth();
  const workspaceId = currentWorkspace?.id;

  // One authoritative Command Center request keeps the first paint fast and
  // prevents the same field context from being rebuilt in parallel.
  const centerState = usePortalResource<Row>(
    useCallback(() => apiClient.fieldOps.commandCenter(workspaceId), [workspaceId]),
  );

  const center = centerState.data || {};
  const queue = arr<Row>(center.field_queue);
  const tasks = arr<Row>(center.operator_tasks);
  const missing = arr<Row>(center.missing_evidence);
  const reportsReady = arr<Row>(center.reports_ready);
  const recentSignals = arr<Row>(center.recent_signals);
  const priority = center.today_priority || {};

  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [updateText, setUpdateText] = useState("");

  const activeTasks = useMemo(
    () => tasks.filter((task) => String(task.status || "open") !== "done"),
    [tasks],
  );

  const attentionQueue = useMemo(
    () => queue.filter((row) => row.priority === "high" || row.status === "needs_attention" || row.status === "missing_evidence"),
    [queue],
  );

  const queueForDisplay = attentionQueue.length ? attentionQueue.slice(0, 4) : queue.slice(0, 3);
  const primaryQueueItem = queueForDisplay[0] || queue[0] || {};
  const fieldsNeedAttention = attentionQueue.length;
  const openTasks = activeTasks.length;

  const primaryTask = useMemo(() => {
    const priorityTitle = clean(priority.title, "");
    const priorityField = clean(priority.field, "");
    return activeTasks.find((task) => (
      (priorityTitle && clean(task.title, "") === priorityTitle)
      || (priorityField && clean(task.field, "") === priorityField)
    )) || activeTasks[0];
  }, [activeTasks, priority]);

  const primaryTitle = clean(
    priority.title || priority.field || primaryQueueItem.issue,
    "Operations are stable",
  );
  const primaryField = clean(priority.field || primaryQueueItem.field_name, "");
  const primaryRisk = clean(priority.risk || primaryQueueItem.priority, "low");
  const primaryReason = clean(
    priority.reason || primaryQueueItem.issue,
    fieldsNeedAttention ? "A field needs operator review." : "No urgent field exceptions are waiting.",
  );
  const primaryAction = clean(
    priority.recommended_action || primaryQueueItem.recommended_action,
    fieldsNeedAttention ? "Review the highest-priority field." : "Keep monitoring live operations.",
  );

  async function refreshAll() {
    await centerState.refresh();
  }

  async function createTask(item: Row) {
    const itemKey = clean(item.field_id || item.field_name, "task");
    setBusy(itemKey);
    setMessage("");
    try {
      await apiClient.fieldOps.createTask({
        title: clean(item.next_operator_task || ("Review " + clean(item.field_name, "field"))),
        field: clean(item.field_name, ""),
        priority: item.priority || "medium",
        why: clean(item.recommended_action || item.issue || "Field requires attention."),
        instructions: [clean(item.recommended_action || "Review the field and collect missing evidence.")],
        evidence_required: lines(item.missing_evidence),
        created_from: "missing_evidence",
        workspace_id: workspaceId,
      });
      setMessage("Task created and added to active work.");
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create task.");
    } finally {
      setBusy("");
    }
  }

  async function setTaskStatus(taskId: string, status: "open" | "in_progress" | "done") {
    setBusy(taskId);
    setMessage("");
    try {
      await apiClient.fieldOps.updateTaskStatus(taskId, { status, workspace_id: workspaceId });
      setMessage(status === "done" ? "Task completed." : "Task moved into active work.");
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not update task.");
    } finally {
      setBusy("");
    }
  }

  async function recordUpdate() {
    const text = updateText.trim();
    if (!text) return;

    setBusy("field-message");
    setMessage("");
    try {
      const result = await apiClient.fieldOps.fieldMessage({
        message: text,
        sender_role: "operator",
        channel: "portal",
        workspace_id: workspaceId,
      });
      const row = result as Row;
      const createdTasks = arr<Row>(row.created_tasks).length;
      const feedback = [
        clean(row.understood_summary, "Update recorded."),
        createdTasks ? String(createdTasks) + (createdTasks === 1 ? " follow-up task created." : " follow-up tasks created.") : "",
        clean(row.recommended_next_action, ""),
      ].filter(Boolean).join(" ");
      setUpdateText("");
      setMessage(feedback);
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not record field update.");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="min-h-full" style={{ background: BG }}>
      <header className="px-4 py-5 sm:px-8 sm:py-7" style={{ background: SURFACE, borderBottom: "1px solid " + BORDER }}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <StatusBadge
                label={clean(center.operating_status, "monitoring")}
                tone={tone(String(center.operating_status || "monitoring"))}
              />
              <StatusBadge
                label={fieldsNeedAttention ? String(fieldsNeedAttention) + " need attention" : "No urgent exceptions"}
                tone={fieldsNeedAttention ? "warn" : "good"}
              />
            </div>
            <h1 className="text-[26px] font-semibold tracking-tight sm:text-[30px]" style={{ color: TEXT }}>
              Command Center
            </h1>
            <p className="mt-2 max-w-3xl text-[13px] leading-relaxed sm:text-[14px]" style={{ color: MUTED }}>
              See what needs attention, understand why, and move the next action forward.
            </p>
          </div>
          <div className="flex-shrink-0">
            <PortalButton variant="secondary" onClick={refreshAll}>Refresh</PortalButton>
          </div>
        </div>
      </header>

      <main className="space-y-4 px-4 py-4 sm:space-y-5 sm:px-8 sm:py-6" style={{ maxWidth: 1280 }}>
        {centerState.error ? <InlineState title="Command Center unavailable" detail={centerState.error} /> : null}
        {message ? <InlineState title={message} /> : null}

        <section className="grid grid-cols-1 gap-4 xl:grid-cols-[1.55fr_0.75fr] xl:gap-5">
          <section className="rounded-2xl p-5 sm:p-6" style={{ background: SURFACE, border: "1px solid " + BORDER }}>
            <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: MUTED }}>
                  Now
                </div>
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  {primaryField ? <StatusBadge label={primaryField} /> : null}
                  <StatusBadge label={primaryRisk} tone={tone(primaryRisk)} />
                </div>
                <h2 className="max-w-3xl break-words text-[22px] font-semibold leading-tight sm:text-[26px]" style={{ color: TEXT }}>
                  {primaryTitle}
                </h2>
                <p className="mt-3 max-w-3xl break-words text-[13px] leading-relaxed sm:text-[14px]" style={{ color: MUTED }}>
                  {primaryReason}
                </p>
                <div className="mt-4 rounded-xl p-4" style={{ background: BG, border: "1px solid " + BORDER }}>
                  <div className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>Next best action</div>
                  <div className="mt-1 break-words text-[14px] font-semibold leading-relaxed" style={{ color: TEXT }}>
                    {primaryAction}
                  </div>
                </div>
              </div>
              <div className="flex flex-shrink-0 flex-wrap gap-2 sm:max-w-[210px] sm:justify-end">
                <PortalButton onClick={() => go(primaryTask ? "/tasks" : "/field-queue")}>
                  {primaryTask ? "Continue task" : "Review priority"}
                </PortalButton>
                <PortalButton variant="secondary" onClick={() => go("/intelligence")}>Ask AGRO-AI</PortalButton>
              </div>
            </div>
          </section>

          <section className="grid grid-cols-2 gap-3">
            <Metric label="Attention" value={String(fieldsNeedAttention)} detail="Fields" />
            <Metric label="Active work" value={String(openTasks)} detail="Open tasks" />
            <Metric label="Evidence gaps" value={String(missing.length)} detail="Missing items" />
            <Metric label="Reports ready" value={String(reportsReady.length)} detail="Available now" />
          </section>
        </section>

        <section className="grid grid-cols-1 gap-4 xl:grid-cols-[1.2fr_0.8fr] xl:gap-5">
          <Panel
            title="Needs attention"
            action={<PortalButton variant="secondary" onClick={() => go("/field-queue")}>View full queue</PortalButton>}
          >
            <div className="space-y-3">
              {queueForDisplay.length ? queueForDisplay.map((item, index) => {
                const hasActiveTask = activeTasks.some((task) => clean(task.field, "") === clean(item.field_name, ""));
                return (
                  <QueueCard
                    key={item.field_id || item.field_name || index}
                    item={item}
                    busy={busy}
                    hasActiveTask={hasActiveTask}
                    onTask={createTask}
                  />
                );
              }) : <InlineState title="Nothing needs attention right now." detail="New exceptions, evidence gaps, or field updates will surface here." />}
            </div>
          </Panel>

          <Panel
            title="Active work"
            action={<PortalButton variant="secondary" onClick={() => go("/tasks")}>View all tasks</PortalButton>}
          >
            <div className="space-y-3">
              {activeTasks.length ? activeTasks.slice(0, 4).map((task, index) => (
                <TaskCard
                  key={task.id || index}
                  task={task}
                  busy={busy}
                  onStatus={setTaskStatus}
                />
              )) : <InlineState title="No active tasks." detail="When AGRO-AI detects follow-up work, it will appear here." />}
            </div>
          </Panel>
        </section>

        <section className="grid grid-cols-1 gap-4 xl:grid-cols-2 xl:gap-5">
          <Panel title="Quick field update">
            <p className="mb-3 text-[12px] leading-relaxed" style={{ color: MUTED }}>
              Write it the way it happened. AGRO-AI will extract field context and create follow-up work when needed.
            </p>
            <textarea
              value={updateText}
              onChange={(event) => setUpdateText(event.target.value)}
              rows={4}
              placeholder="Example: North 12 had low pressure after the morning irrigation. Check the filter and verify flow before the next set."
              className="w-full resize-none rounded-xl px-4 py-4 text-[14px] outline-none"
              style={{ background: BG, border: "1px solid " + BORDER, color: TEXT }}
            />
            <div className="mt-3 flex flex-wrap gap-2">
              <PortalButton onClick={recordUpdate} disabled={busy === "field-message" || !updateText.trim()}>
                {busy === "field-message" ? "Understanding…" : "Record update"}
              </PortalButton>
              <PortalButton variant="secondary" onClick={() => go("/field-intelligence")}>Open Field Intelligence</PortalButton>
            </div>
          </Panel>

          <Panel
            title="Recent signals"
            action={<PortalButton variant="secondary" onClick={() => go("/evidence")}>Open evidence</PortalButton>}
          >
            <div className="space-y-2">
              {recentSignals.length ? recentSignals.slice(0, 5).map((item, index) => (
                <SignalRow key={index} item={item} />
              )) : <InlineState title="No recent signals yet." detail="Connected sources and field updates will appear here as operating context." />}
            </div>
          </Panel>
        </section>
      </main>
    </div>
  );
}

function QueueCard({
  item,
  busy,
  hasActiveTask,
  onTask,
}: {
  item: Row;
  busy: string;
  hasActiveTask: boolean;
  onTask: (item: Row) => void;
}) {
  const itemKey = clean(item.field_id || item.field_name, "task");
  const evidence = lines(item.missing_evidence);

  return (
    <article className="rounded-xl p-4" style={{ background: BG, border: "1px solid " + BORDER }}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <StatusBadge label={clean(item.priority, "medium")} tone={tone(String(item.priority || "medium"))} />
            <StatusBadge label={clean(item.status, "ready")} tone={tone(String(item.status || "ready"))} />
          </div>
          <h3 className="break-words text-[15px] font-semibold" style={{ color: TEXT }}>
            {clean(item.field_name, "Field")}
          </h3>
          <p className="mt-1 break-words text-[13px] leading-relaxed" style={{ color: MUTED }}>
            {clean(item.issue, "No issue described yet.")}
          </p>
          <Info label="Next" value={clean(item.recommended_action, "")} />
          <Info label="Latest signal" value={clean(item.latest_signal, "")} />
          {evidence.length ? (
            <div className="mt-3 text-[11px]" style={{ color: MUTED }}>
              {String(evidence.length)} evidence {evidence.length === 1 ? "gap" : "gaps"} · {evidence.slice(0, 2).join(" · ")}
            </div>
          ) : null}
        </div>
        <div className="flex-shrink-0">
          {hasActiveTask ? (
            <PortalButton variant="secondary" onClick={() => go("/tasks")}>Open task</PortalButton>
          ) : (
            <PortalButton variant="secondary" onClick={() => onTask(item)} disabled={busy === itemKey}>
              {busy === itemKey ? "Creating…" : "Create task"}
            </PortalButton>
          )}
        </div>
      </div>
    </article>
  );
}

function TaskCard({
  task,
  busy,
  onStatus,
}: {
  task: Row;
  busy: string;
  onStatus: (id: string, status: "open" | "in_progress" | "done") => void;
}) {
  const taskId = String(task.id || "");
  const status = String(task.status || "open");
  const canStart = status === "open";
  const canComplete = status === "in_progress";

  return (
    <article className="rounded-xl p-4" style={{ background: BG, border: "1px solid " + BORDER }}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <StatusBadge label={clean(task.priority, "medium")} tone={tone(String(task.priority || "medium"))} />
        <StatusBadge label={clean(status)} tone={tone(status)} />
      </div>
      <div className="break-words text-[14px] font-semibold" style={{ color: TEXT }}>{clean(task.title)}</div>
      <div className="mt-1 break-words text-[12px] leading-relaxed" style={{ color: MUTED }}>{clean(task.why)}</div>
      <div className="mt-3">
        {canStart ? (
          <PortalButton variant="secondary" onClick={() => onStatus(taskId, "in_progress")} disabled={busy === taskId}>
            {busy === taskId ? "Starting…" : "Start"}
          </PortalButton>
        ) : canComplete ? (
          <PortalButton variant="secondary" onClick={() => onStatus(taskId, "done")} disabled={busy === taskId}>
            {busy === taskId ? "Updating…" : "Mark done"}
          </PortalButton>
        ) : (
          <PortalButton variant="secondary" onClick={() => go("/tasks")}>Review task</PortalButton>
        )}
      </div>
    </article>
  );
}

function SignalRow({ item }: { item: Row }) {
  const label = clean(item.signal || item.title || item.summary || item.message);
  const field = clean(item.field || item.field_name, "");
  const detail = clean(item.detail || item.value || item.status || item.source, "");

  return (
    <div className="rounded-xl p-3.5" style={{ background: BG, border: "1px solid " + BORDER }}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 break-words text-[13px] font-semibold" style={{ color: TEXT }}>{label}</div>
        {field ? <StatusBadge label={field} /> : null}
      </div>
      {detail ? <div className="mt-1 break-words text-[11px] leading-relaxed" style={{ color: MUTED }}>{detail}</div> : null}
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <section className="rounded-2xl p-4" style={{ background: SURFACE, border: "1px solid " + BORDER }}>
      <div className="text-[9px] font-semibold uppercase tracking-widest sm:text-[10px]" style={{ color: MUTED }}>{label}</div>
      <div className="mt-2 break-words text-[22px] font-semibold sm:text-[24px]" style={{ color: TEXT }}>{value}</div>
      <div className="mt-1 break-words text-[11px]" style={{ color: MUTED }}>{detail}</div>
    </section>
  );
}

function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl p-4 sm:p-5" style={{ background: SURFACE, border: "1px solid " + BORDER }}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold" style={{ color: TEXT }}>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  if (!value || value === "—") return null;
  return (
    <div className="mt-2 break-words text-[12px]" style={{ color: MUTED }}>
      <strong style={{ color: TEXT }}>{label}: </strong>{value}
    </div>
  );
}
