import { storage } from "./storage.js";

const QK = "queue";

let backendSyncEnabled = false;
let transport = null;

export const syncService = {
  configure(options = {}) {
    backendSyncEnabled = Boolean(options.backendSyncEnabled);
    transport = typeof options.transport === "function" ? options.transport : null;
  },
  queueAction(action) {
    const q = storage.get(QK, []);
    const idempotencyKey = action.idempotencyKey || (action.kind && action.payload?.id ? `${action.kind}:${action.payload.id}` : null);
    if (idempotencyKey && q.some((item) => item.idempotencyKey === idempotencyKey)) return q.length;
    const queuedAt = new Date().toISOString();
    q.push({ ...action, idempotencyKey, localQueueId: action.localQueueId || `queue-${queuedAt}-${Math.random().toString(36).slice(2, 10)}`, queuedAt });
    storage.set(QK, q);
    return q.length;
  },
  getQueue() {
    return storage.get(QK, []);
  },
  async flushQueue() {
    const q = this.getQueue();
    if (!navigator.onLine) return { flushed: 0, pending: q.length, backendSyncEnabled, reason: "offline" };
    if (!backendSyncEnabled || !transport) {
      return { flushed: 0, pending: q.length, backendSyncEnabled: false, reason: "backend_sync_not_enabled" };
    }
    try {
      const result = await transport(q);
      const acknowledgedIds = new Set(result?.acknowledgedIds || []);
      const remaining = q.filter((action) => !acknowledgedIds.has(action.localQueueId || action.id || action.queuedAt));
      const flushed = q.length - remaining.length;
      storage.set(QK, remaining);
      if (flushed > 0) storage.set("lastSyncAt", new Date().toISOString());
      return { flushed, pending: remaining.length, backendSyncEnabled: true, reason: flushed ? "acknowledged" : "no_acknowledgements" };
    } catch {
      return { flushed: 0, pending: q.length, backendSyncEnabled: true, reason: "transport_error" };
    }
  },
  status() {
    const pending = this.getQueue().length;
    const lastSyncAt = storage.get("lastSyncAt", null);
    let state = "local_only";
    if (!navigator.onLine) state = "offline";
    else if (pending) state = "local_pending";
    else if (backendSyncEnabled && lastSyncAt) state = "synced_remote";
    return {
      isOnline: navigator.onLine,
      pending,
      state,
      backendSyncEnabled,
      lastSyncAt,
    };
  },
};
