import test from 'node:test';
import assert from 'node:assert/strict';
import { syncService } from '../js/services/sync.js';

global.localStorage = {
  _m:new Map(),
  getItem(k){return this._m.has(k)?this._m.get(k):null;},
  setItem(k,v){this._m.set(k,v);},
  removeItem(k){this._m.delete(k);},
};
Object.defineProperty(global, 'navigator', { value: { onLine: true }, configurable: true });

test('flush preserves local queue when backend sync is not enabled', async () => {
  localStorage._m.clear();
  syncService.configure({ backendSyncEnabled: false });
  syncService.queueAction({ kind:'test' });
  assert.equal(syncService.getQueue().length, 1);
  const out = await syncService.flushQueue();
  assert.deepEqual(out, {
    flushed: 0,
    pending: 1,
    backendSyncEnabled: false,
    reason: 'backend_sync_not_enabled',
  });
  assert.equal(syncService.getQueue().length, 1);
  assert.equal(syncService.status().state, 'local_pending');
  assert.equal(syncService.status().lastSyncAt, null);
});

test('flush removes only remotely acknowledged actions when transport is enabled', async () => {
  localStorage._m.clear();
  syncService.queueAction({ kind:'keep' });
  syncService.queueAction({ kind:'send' });
  const queued = syncService.getQueue();
  syncService.configure({
    backendSyncEnabled: true,
    transport: async () => ({ acknowledgedIds: [queued[1].localQueueId] }),
  });
  const out = await syncService.flushQueue();
  assert.equal(out.flushed, 1);
  assert.equal(out.pending, 1);
  assert.equal(syncService.getQueue()[0].kind, 'keep');
  assert.ok(syncService.status().lastSyncAt);
  syncService.configure({ backendSyncEnabled: false });
});
