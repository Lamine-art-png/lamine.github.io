// IndexedDB-backed offline queue for Field Intelligence captures.
//
// Durability rules enforced here:
// - Audio/photo/records live in IndexedDB, never localStorage.
// - Every record carries a stable client capture id + idempotency key.
// - A record and its blobs survive reload and are only deleted after the
//   backend confirms durable acceptance.
// - Only one flush runs per record at a time (in-memory lock + `syncing` state).
// - Replaying the same idempotency key never creates duplicates (server-enforced,
//   client cooperates by reusing the same ids).

export type SyncState = "draft" | "queued" | "syncing" | "processing" | "synced" | "failed" | "conflict";

export type QueuedAsset = {
  id: string; // client asset id (stable)
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
};

const DB_NAME = "agroai_field_intelligence";
const DB_VERSION = 1;
const CAPTURES = "captures";
const ASSETS = "assets";
const META = "meta";

let dbPromise: Promise<IDBDatabase> | null = null;
const inFlight = new Set<string>(); // per-record flush lock (single tab)
const BACKOFF_BASE_MS = 2000;
const BACKOFF_MAX_MS = 5 * 60 * 1000;

export function indexedDbAvailable(): boolean {
  return typeof indexedDB !== "undefined";
}

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(CAPTURES)) {
        db.createObjectStore(CAPTURES, { keyPath: "clientCaptureId" });
      }
      if (!db.objectStoreNames.contains(ASSETS)) {
        const store = db.createObjectStore(ASSETS, { keyPath: "id" });
        store.createIndex("byCapture", "clientCaptureId", { unique: false });
      }
      if (!db.objectStoreNames.contains(META)) {
        db.createObjectStore(META, { keyPath: "key" });
      }
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
  notify();
}

export async function getCapture(id: string): Promise<CaptureRecord | undefined> {
  return tx<CaptureRecord | undefined>(CAPTURES, "readonly", (s) => s.get(id) as IDBRequest<CaptureRecord | undefined>);
}

export async function allCaptures(): Promise<CaptureRecord[]> {
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
  const row = await tx<{ key: string; value: number } | undefined>(META, "readonly", (s) => s.get("lastSyncedAt") as IDBRequest<{ key: string; value: number } | undefined>);
  return row ? row.value : null;
}

async function setLastSyncedAt(value: number): Promise<void> {
  await tx(META, "readwrite", (s) => s.put({ key: "lastSyncedAt", value }));
}

// ---- change notification so the shell can show pending count + last sync ----
type Listener = () => void;
const listeners = new Set<Listener>();
export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
function notify() {
  listeners.forEach((l) => {
    try { l(); } catch { /* listener errors must not break the queue */ }
  });
}

export type FieldApi = {
  initiate: (payload: Record<string, unknown>) => Promise<any>;
  uploadAsset: (captureId: string, fields: Record<string, string>, file: File) => Promise<any>;
  complete: (captureId: string, payload?: unknown) => Promise<any>;
};

function backoffDelay(retryCount: number): number {
  return Math.min(BACKOFF_BASE_MS * 2 ** retryCount, BACKOFF_MAX_MS);
}

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

// Flush a single record end-to-end. Returns true on durable acceptance.
async function flushRecord(api: FieldApi, record: CaptureRecord): Promise<boolean> {
  if (inFlight.has(record.clientCaptureId)) return false;
  inFlight.add(record.clientCaptureId);
  try {
    record.syncState = "syncing";
    record.lastError = null;
    await putCapture(record);

    // 1) initiate (idempotent — safe to replay)
    const initiated = await api.initiate(toInitiatePayload(record));
    const serverCaptureId = initiated?.capture?.id as string | undefined;
    record.serverCaptureId = serverCaptureId ?? record.serverCaptureId;

    // 2) upload not-yet-uploaded assets (dedup is server-enforced)
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

    // 3) complete (idempotent — returns existing observation on replay)
    record.syncState = "processing";
    await putCapture(record);
    const completed = await api.complete(record.serverCaptureId || record.clientCaptureId, {});
    record.observationId = completed?.observation?.id ?? null;
    record.syncState = "synced";
    record.retryCount = 0;
    record.nextAttemptAt = undefined;
    await putCapture(record);

    // durable acceptance confirmed — now safe to reclaim blob space
    for (const asset of assets) await deleteAsset(asset.id);
    await setLastSyncedAt(Date.now());
    notify();
    return true;
  } catch (error: any) {
    record.retryCount += 1;
    record.syncState = error?.status === 409 ? "conflict" : "failed";
    record.lastError = error?.message || "sync_failed";
    record.nextAttemptAt = Date.now() + backoffDelay(record.retryCount);
    await putCapture(record);
    return false;
  } finally {
    inFlight.delete(record.clientCaptureId);
  }
}

// Flush all eligible records. Partial failure never loses failed records.
export async function flushQueue(api: FieldApi): Promise<{ synced: number; failed: number }> {
  const rows = await allCaptures();
  const now = Date.now();
  let synced = 0;
  let failed = 0;
  for (const record of rows) {
    if (record.syncState === "synced") continue;
    if (record.syncState === "syncing" || record.syncState === "processing") continue;
    if (record.nextAttemptAt && record.nextAttemptAt > now) continue;
    const ok = await flushRecord(api, record);
    if (ok) synced += 1; else failed += 1;
  }
  return { synced, failed };
}

export async function retryRecord(api: FieldApi, clientCaptureId: string): Promise<boolean> {
  const record = await getCapture(clientCaptureId);
  if (!record) return false;
  record.nextAttemptAt = undefined; // manual retry ignores backoff window
  await putCapture(record);
  return flushRecord(api, record);
}

// Delete only allowed for records the backend has not yet durably accepted, and
// only after explicit user confirmation in the UI layer.
export async function deleteUnsyncedRecord(clientCaptureId: string): Promise<void> {
  const assets = await assetsForCapture(clientCaptureId);
  for (const asset of assets) await deleteAsset(asset.id);
  await tx(CAPTURES, "readwrite", (s) => s.delete(clientCaptureId));
  notify();
}
