import { createTerrisFieldEvent } from "./fieldLedger.js";

export const TERRIS_TASK_TYPES = [
  "approve_irrigation",
  "inspect_field",
  "verify_application",
  "collect_missing_data",
  "inspect_pump",
  "record_fertigation",
  "attach_evidence",
  "review_anomaly",
];

export function createFieldTask(input) {
  if (!TERRIS_TASK_TYPES.includes(input.taskType)) throw new Error(`Unsupported task type: ${input.taskType}`);
  return {
    id: input.id || `task-${Date.now()}`,
    title: input.title,
    module: input.module,
    taskType: input.taskType,
    priority: input.priority || "medium",
    farmId: input.farmId || "local-farm",
    fieldId: input.fieldId,
    blockId: input.blockId || null,
    relatedRef: input.relatedRef || null,
    assignee: input.assignee || null,
    dueAt: input.dueAt || null,
    status: input.status || "open",
    completionNotes: input.completionNotes || "",
    attachments: input.attachments || [],
    provenance: input.provenance || { source: "system" },
    offlineSyncState: input.offlineSyncState || "synced",
  };
}

export function completeFieldTask(task, completion = {}) {
  return {
    ...task,
    status: "completed",
    completionNotes: completion.notes || task.completionNotes || "",
    attachments: [...(task.attachments || []), ...(completion.attachments || [])],
    completedAt: completion.completedAt || new Date().toISOString(),
    offlineSyncState: completion.offline ? "queued" : task.offlineSyncState,
  };
}

export function taskEvent(task, completed = false) {
  return createTerrisFieldEvent({
    eventType: completed ? "task_completed" : "task_created",
    module: "ops",
    fieldId: task.fieldId,
    blockId: task.blockId,
    sourceRecordId: task.id,
    sourceMode: "system",
    truthLabel: "reported",
    occurredAt: completed ? task.completedAt : undefined,
    payload: task,
    limitations: completed ? ["Task completion is not agronomic verification."] : [],
  });
}
