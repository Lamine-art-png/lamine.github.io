import { storage } from "./storage.js";

const QK = "queue";

export const syncService = {
  queueAction(action) {
    const q = storage.get(QK, []);
    q.push({ ...action, queuedAt: new Date().toISOString() });
    storage.set(QK, q);
    return q.length;
  },
  getQueue() {
    return storage.get(QK, []);
  },
  async flushQueue() {
    if (!navigator.onLine) return { flushed: 0 };
    const q = this.getQueue();
    storage.set(QK, []);
    storage.set("lastSyncAt", new Date().toISOString());
    return { flushed: q.length };
  },
  status() {
    const pending = this.getQueue().length;
    return {
      isOnline: navigator.onLine,
      pending,
      state: !navigator.onLine ? "offline" : pending ? "pending" : "synced",
      lastSyncAt: storage.get("lastSyncAt", null),
    };
  },
};
