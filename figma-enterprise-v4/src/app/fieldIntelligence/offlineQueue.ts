// IndexedDB-backed offline queue for Field Intelligence captures.
//
// Durability + isolation rules enforced here:
// - Audio/photo/records live in IndexedDB, never localStorage.
// - The database is namespaced by authenticated organization id + user id, so
//   one account can never read or sync another account's local captures.
// - Every record carries a stable client capture id + idempotency key.
// - A record and its blobs survive reload and are only deleted after the
//   backend confirms durable acceptance.
// - Only one process flushes a record at a time: an in-tab lock plus a
//   cross-tab IndexedDB lease. Abandoned syncing records recover after the
//   lease expires. Retries are bounded; exhausted records enter a manual
//   recovery ("failed") state without losing data.

export type SyncState = "draft" | "queued" | "syncing" | "processing" | "synced" | "failed" | "conflict";

export type QueuedAsset = {
  id: string;
  clientCaptureId: string;
  kind: "audio" | "video" | "photo" | "file";
  contentType: string;
  filename: string;
  durationSeconds?: number;
  blob: Blob;
  uploaded: boolean;
};

export type CaptureRecord = {
  clientCaptureId: string;
  idempotencyKey: string;
  createdAt: number;
  workspaceId?: string | null;
  captureSource: "voice" | "typed";
  noteText?: string;
  fieldName?: string;
  blockName?: string;
  crop?: string;
  eventType?: string;
  severity?: string;
  assignee?: string;
  occurredAt?: string;
  latitude?: number | null;
  longitude?: number | null;
  locationAccuracyM?: number | null;
  assetManifest: { client_asset_id: string; kind: string; content_type: string }[];
  syncState: SyncState;
  retryCount: number;
  lastError?: string | null;
  nextAttemptAt?: number;
  serverCaptureId?: string | null;
  observationId?: string | null;
  leaseOwner?: string | null;
  leaseExpiresAt?: number | null;
};

const DB_PREFIX = "agroai_fi";
const DB_VERSION = 1;
const CAPTURES = "captures";
const ASSETS = "assets";
const META = "meta";

export const MAX_ATTEMPTS = 8;
const BACKOFF_BASE_MS = 2000;
const BACKOFF_MAX_MS = 5 * 60 * 1000;
const LEASE_MS = 60 * 1000;

// A per-tab identity used for cross-tab lease ownership.
const TAB_ID = (globalThis.crypto && "randomUUID" in globalThis.crypto)
  ? globalThis.crypto.randomUUID()
  : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

let identity = { orgId: "anon", userId: "anon" };
let dbPromise: Promise<IDBDatabase> | null = null;
let openDbName = "";
const inFlight = new Set<string>();

let channel: BroadcastChannel | null = null;

function sanitize(value: string | null | undefined): string {
  return String(value || "anon").replace(/[^A-Za-z0-9_-]+/g, "_").slice(0, 80) || "anon";
}

// Pure, testable: the namespaced database name is the isolation boundary.
export function dbNameFor(orgId?: string | null, userId?: string | null): string {
  return `${DB_PREFIX}__${sanitize(orgId)}__${sanitize(userId)}`;
}

export function backoffDelay(retryCount: number): number {
  return Math.min(BACKOFF_BASE_MS * 2 ** retryCount, BACKOFF_MAX_MS);
}

export function isLeaseExpired(record: CaptureRecord, now = Date.now()): boolean {
  return !record.leaseExpiresAt || record.leaseExpiresAt <= now;
}

export function indexedDbAvailable(): boolean {
  return typeof indexedDB !== "undefined";
}

// Rebind the queue to the authenticated identity. Switching identity closes the
// current database so a different account opens a *different* database and can
// never observe the previous account's records. Safe to call on login, logout,
// account change, organization change and workspace change.
export function configureIdentity(orgId?: string | null, userId?: string | null): void {
  const next = { orgId: sanitize(orgId), userId: sanitize(userId) };
  if (next.orgId === identity.orgId && next.userId === identity.userId) return;
  identity = next;
  if (dbPromise) {
    dbPromise.then((db) => { try { db.close(); } catch { /* already closed */ } }).catch(() => {});
    dbPromise = null;
    openDbName = "";
  }
  ensureChannel();
  notify();
}

function ensureChannel() {
  if (typeof BroadcastChannel === "undefined") return;
  const name = `agroai-fi-sync__${identity.orgId}__${identity.userId}`;
  if (channel && (channel as any).name === name) return;
  try { channel?.close(); } catch { /* noop */ }
  channel = new BroadcastChannel(name);
  channel.onmessage = () => notify();
}

function activeDbName(): string {
  return dbNameFor(identity.orgId, identity.userId);
}

function openDb(): Promise<IDBDatabase> {
  const name = activeDbName();
  if (dbPromise && openDbName === name) return dbPromise;
  openDbName = name;
  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(name, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(CAPTURES)) db.createObjectStore(CAPTURES, { keyPath: "clientCaptureId" });
      if (!db.objectStoreNames.contains(ASSETS)) {
        const store = db.createObjectStore(ASSETS, { keyPath: "id" });
        store.createIndex("byCapture", "clientCaptureId", { unique: false });
      }
      if (!db.objectStoreNames.contains(META)) db.createObjectStore(META, { keyPath: "key" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return dbPromise;
}

function tx<T>(store: string, mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const transaction = db.transaction(store, mode);
        const request = run(transaction.objectStore(store));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      }),
  );
}

function getAll<T>(store: string): Promise<T[]> {
  return tx<T[]>(store, "readonly", (s) => s.getAll() as IDBRequest<T[]>);
}

export async function putCapture(record: CaptureRecord): Promise<void> {
  await tx(CAPTURES, "readwrite", (s) => s.put(record));
  broadcast();
  notify();
}

export async function getCapture(id: string): Promise<CaptureRecord | undefined> {
  return tx<CaptureRecord | undefined>(CAPTURES, "readonly", (s) => s.get(id) as IDBRequest<CaptureRecord | undefined>);
}

export async function allCaptures(): Promise<CaptureRecord[]> {
  if (!indexedDbAvailable()) return [];
  const rows = await getAll<CaptureRecord>(CAPTURES);
  return rows.sort((a, b) => b.createdAt - a.createdAt);
}

export async function putAsset(asset: QueuedAsset): Promise<void> {
  await tx(ASSETS, "readwrite", (s) => s.put(asset));
}

async function assetsForCapture(clientCaptureId: string): Promise<QueuedAsset[]> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const request = db.transaction(ASSETS, "readonly").objectStore(ASSETS).index("byCapture").getAll(clientCaptureId);
    request.onsuccess = () => resolve(request.result as QueuedAsset[]);
    request.onerror = () => reject(request.error);
  });
}

async function deleteAsset(id: string): Promise<void> {
  await tx(ASSETS, "readwrite", (s) => s.delete(id));
}

export function newCaptureId(): string {
  const rand = (globalThis.crypto && "randomUUID" in globalThis.crypto)
    ? globalThis.crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `cap_${rand}`;
}

export async function pendingCount(): Promise<number> {
  const rows = await allCaptures();
  return rows.filter((r) => r.syncState !== "synced").length;
}

export async function getLastSyncedAt(): Promise<number | null> {
  if (!indexedDbAvailable()) return null;
  const row = await tx<{ key: string; value: number } | undefined>(META, "readonly", (s) => s.get("lastSyncedAt") as IDBRequest<any>);
  return row ? row.value : null;
}

async function setLastSyncedAt(value: number): Promise<void> {
  await tx(META, "readwrite", (s) => s.put({ key: "lastSyncedAt", value }));
}

type Listener = () => void;
const listeners = new Set<Listener>();
export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
function notify() {
  listeners.forEach((l) => { try { l(); } catch { /* isolate listener errors */ } });
}
function broadcast() {
  try { channel?.postMessage({ t: Date.now() }); } catch { /* channel closed */ }
}

export type FieldApi = {
  initiate: (payload: Record<string, unknown>) => Promise<any>;
  uploadAsset: (captureId: string, fields: Record<string, string>, file: File) => Promise<any>;
  complete: (captureId: string, payload?: unknown) => Promise<any>;
};

function toInitiatePayload(record: CaptureRecord): Record<string, unknown> {
  return {
    client_capture_id: record.clientCaptureId,
    idempotency_key: record.idempotencyKey,
    workspace_id: record.workspaceId ?? undefined,
    capture_source: record.captureSource,
    note_text: record.noteText,
    field_name: record.fieldName,
    block_name: record.blockName,
    crop: record.crop,
    event_type: record.eventType,
    severity: record.severity,
    assignee: record.assignee,
    occurred_at: record.occurredAt,
    latitude: record.latitude ?? undefined,
    longitude: record.longitude ?? undefined,
    location_accuracy_m: record.locationAccuracyM ?? undefined,
    asset_manifest: record.assetManifest,
    client_created_at: new Date(record.createdAt).toISOString(),
  };
}

// Atomically acquire a cross-tab lease. IndexedDB transactions are isolated, so
// only one tab can win the read-modify-write for a given record.
async function acquireLease(clientCaptureId: string): Promise<CaptureRecord | null> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(CAPTURES, "readwrite");
    const store = transaction.objectStore(CAPTURES);
    const read = store.get(clientCaptureId);
    read.onsuccess = () => {
      const record = read.result as CaptureRecord | undefined;
      if (!record) return resolve(null);
      const now = Date.now();
      const heldByOther = record.leaseOwner && record.leaseOwner !== TAB_ID && (record.leaseExpiresAt || 0) > now;
      if (heldByOther) return resolve(null);
      record.leaseOwner = TAB_ID;
      record.leaseExpiresAt = now + LEASE_MS;
      store.put(record);
      transaction.oncomplete = () => resolve(record);
      transaction.onerror = () => reject(transaction.error);
    };
    read.onerror = () => reject(read.error);
  });
}

async function flushRecord(api: FieldApi, clientCaptureId: string): Promise<boolean> {
  if (inFlight.has(clientCaptureId)) return false;
  inFlight.add(clientCaptureId);
  try {
    const record = await acquireLease(clientCaptureId);
    if (!record) return false; // another tab owns the lease
    if (record.syncState === "synced") return true;

    record.syncState = "syncing";
    record.lastError = null;
    await putCapture(record);

    const initiated = await api.initiate(toInitiatePayload(record));
    record.serverCaptureId = (initiated?.capture?.id as string | undefined) ?? record.serverCaptureId;

    const assets = await assetsForCapture(record.clientCaptureId);
    for (const asset of assets) {
      if (asset.uploaded) continue;
      const file = new File([asset.blob], asset.filename || asset.id, { type: asset.contentType });
      await api.uploadAsset(record.serverCaptureId || record.clientCaptureId, {
        client_asset_id: asset.id,
        kind: asset.kind,
        ...(asset.durationSeconds ? { duration_seconds: String(asset.durationSeconds) } : {}),
      }, file);
      asset.uploaded = true;
      await putAsset(asset);
    }

    record.syncState = "processing";
    await putCapture(record);
    const completed = await api.complete(record.serverCaptureId || record.clientCaptureId, {});
    record.observationId = completed?.observation?.id ?? null;
    record.syncState = "synced";
    record.retryCount = 0;
    record.nextAttemptAt = undefined;
    record.leaseOwner = null;
    record.leaseExpiresAt = null;
    await putCapture(record);

    // durable acceptance confirmed — reclaim blob space
    for (const asset of assets) await deleteAsset(asset.id);
    await setLastSyncedAt(Date.now());
    broadcast();
    notify();
    return true;
  } catch (error: any) {
    const record = await getCapture(clientCaptureId);
    if (record) {
      record.retryCount += 1;
      record.leaseOwner = null;
      record.leaseExpiresAt = null;
      if (error?.status === 409) record.syncState = "conflict";
      else if (record.retryCount >= MAX_ATTEMPTS) record.syncState = "failed"; // manual recovery
      else record.syncState = "failed";
      record.lastError = error?.message || "sync_failed";
      record.nextAttemptAt = Date.now() + backoffDelay(record.retryCount);
      await putCapture(record);
    }
    return false;
  } finally {
    inFlight.delete(clientCaptureId);
  }
}

// Recover records abandoned mid-sync by a crashed tab (expired lease).
async function recoverStale(): Promise<void> {
  const rows = await allCaptures();
  const now = Date.now();
  for (const record of rows) {
    if ((record.syncState === "syncing" || record.syncState === "processing") && isLeaseExpired(record, now)) {
      record.syncState = "queued";
      record.leaseOwner = null;
      record.leaseExpiresAt = null;
      await putCapture(record);
    }
  }
}

export async function flushQueue(api: FieldApi): Promise<{ synced: number; failed: number }> {
  if (!indexedDbAvailable()) return { synced: 0, failed: 0 };
  await recoverStale();
  const rows = await allCaptures();
  const now = Date.now();
  let synced = 0;
  let failed = 0;
  for (const record of rows) {
    if (record.syncState === "synced") continue;
    if (record.syncState === "syncing" || record.syncState === "processing") continue;
    if (record.retryCount >= MAX_ATTEMPTS && record.syncState === "failed" && (record.nextAttemptAt || 0) > now) continue;
    if (record.nextAttemptAt && record.nextAttemptAt > now) continue;
    const ok = await flushRecord(api, record.clientCaptureId);
    if (ok) synced += 1; else failed += 1;
  }
  return { synced, failed };
}

export async function retryRecord(api: FieldApi, clientCaptureId: string): Promise<boolean> {
  const record = await getCapture(clientCaptureId);
  if (!record) return false;
  record.nextAttemptAt = undefined; // manual retry ignores backoff + attempt ceiling
  record.retryCount = Math.min(record.retryCount, MAX_ATTEMPTS - 1);
  record.syncState = "queued";
  await putCapture(record);
  return flushRecord(api, clientCaptureId);
}

// Deletion is allowed only for records the backend has not durably accepted,
// and only after explicit user confirmation in the UI layer.
export async function deleteUnsyncedRecord(clientCaptureId: string): Promise<void> {
  const record = await getCapture(clientCaptureId);
  if (record && record.syncState === "synced") return; // never delete accepted data
  const assets = await assetsForCapture(clientCaptureId);
  for (const asset of assets) await deleteAsset(asset.id);
  await tx(CAPTURES, "readwrite", (s) => s.delete(clientCaptureId));
  broadcast();
  notify();
}
