import test from 'node:test';
import assert from 'node:assert/strict';
import { syncService } from '../js/services/sync.js';

global.localStorage = {
  _m:new Map(),
  getItem(k){return this._m.has(k)?this._m.get(k):null;},
  setItem(k,v){this._m.set(k,v);},
};
Object.defineProperty(global, 'navigator', { value: { onLine: true }, configurable: true });

test('offline queued action and flush', async () => {
  syncService.queueAction({ kind:'test' });
  assert.equal(syncService.getQueue().length, 1);
  const out = await syncService.flushQueue();
  assert.equal(out.flushed, 1);
  assert.equal(syncService.getQueue().length, 0);
});
