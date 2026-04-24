import { storageService } from "./storageService.js";

const QUEUE_KEY = "queued_actions";

export const syncService = {
  getSyncStatus() {
    const pending = this.getQueue().length;
    const isOnline = navigator.onLine;
    return {
      isOnline,
      pendingActions: pending,
      lastSyncAt: storageService.get("last_sync", null),
      status: !isOnline ? "offline" : pending ? "pending" : "synced",
    };
  },
  enqueue(action) {
    const queue = this.getQueue();
    queue.push({ ...action, queuedAt: new Date().toISOString() });
    storageService.set(QUEUE_KEY, queue);
  },
  getQueue() {
    return storageService.get(QUEUE_KEY, []);
  },
  async syncQueuedActions() {
    if (!navigator.onLine) return { synced: 0 };
    const queue = this.getQueue();
    storageService.set(QUEUE_KEY, []);
    storageService.set("last_sync", new Date().toISOString());
    return { synced: queue.length };
  },
};
