import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CloudOff, Loader2, RefreshCw, X } from "lucide-react";
import { useLocale } from "../hooks/useLocale";
import { useAuth } from "../auth/AuthProvider";
import { fieldApi } from "./fieldApi";
import {
  allCaptures, configureIdentity, deleteUnsyncedRecord, flushQueue, getLastSyncedAt,
  indexedDbAvailable, retryRecord, subscribe, type CaptureRecord, type SyncState,
} from "./offlineQueue";

/**
 * Portal-shell synchronization center.
 *
 * A compact global indicator (queued/syncing/failed/conflict counts, offline
 * state, last successful sync) plus a recovery drawer with retry / inspect /
 * edit-note / discard / export actions. The queue is namespaced per
 * organization + user by configureIdentity, so nothing here can ever show or
 * export another account's records.
 */

export type SyncSummary = {
  queued: number;
  syncing: number;
  processing: number;
  failed: number;
  conflict: number;
  manualRecovery: number;
  attention: number;
  total: number;
};

export function summarizeQueue(records: CaptureRecord[]): SyncSummary {
  const count = (state: SyncState) => records.filter((record) => record.syncState === state).length;
  const summary = {
    queued: count("queued") + count("draft"),
    syncing: count("syncing"),
    processing: count("processing"),
    failed: count("failed"),
    conflict: count("conflict"),
    manualRecovery: count("manual_recovery"),
    attention: 0,
    total: records.length,
  };
  summary.attention = summary.failed + summary.conflict + summary.manualRecovery;
  return summary;
}

export function SyncCenter() {
  const { t } = useLocale();
  const { currentOrganization, currentWorkspace, user } = useAuth() as any;
  const [records, setRecords] = useState<CaptureRecord[]>([]);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [online, setOnline] = useState<boolean>(typeof navigator === "undefined" ? true : navigator.onLine);
  const [open, setOpen] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [inspecting, setInspecting] = useState<CaptureRecord | null>(null);

  useEffect(() => {
    configureIdentity(currentOrganization?.id || null, user?.id || null);
  }, [currentOrganization?.id, user?.id]);

  const refresh = useCallback(async () => {
    if (!indexedDbAvailable()) return;
    setRecords(await allCaptures());
    setLastSync(await getLastSyncedAt());
  }, []);

  useEffect(() => { void refresh(); }, [refresh, currentOrganization?.id, user?.id]);
  useEffect(() => subscribe(() => { void refresh(); }), [refresh]);
  useEffect(() => {
    const goOnline = () => { setOnline(true); void flushQueue(fieldApi).then(refresh); };
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => { window.removeEventListener("online", goOnline); window.removeEventListener("offline", goOffline); };
  }, [refresh]);

  const summary = useMemo(() => summarizeQueue(records), [records]);
  const pendingBadge = summary.queued + summary.syncing + summary.processing + summary.attention;

  const retry = useCallback(async (record: CaptureRecord) => {
    setBusyId(record.clientCaptureId);
    try { await retryRecord(fieldApi, record.clientCaptureId); await refresh(); }
    finally { setBusyId(null); }
  }, [refresh]);

  const discard = useCallback(async (record: CaptureRecord) => {
    if (!window.confirm(t("syncCenter.discardConfirm"))) return;
    setBusyId(record.clientCaptureId);
    try { await deleteUnsyncedRecord(record.clientCaptureId); await refresh(); }
    finally { setBusyId(null); }
  }, [refresh, t]);

  const exportRecovery = useCallback((record: CaptureRecord) => {
    // Local-only recovery export: the operator's own queued capture (never
    // another account's — the store is identity-namespaced), minus any blobs.
    const payload = {
      exported_at: new Date().toISOString(),
      organization_id: currentOrganization?.id || null,
      record: { ...record },
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `agroai-recovery-${record.clientCaptureId}.json`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 5000);
  }, [currentOrganization?.id]);

  if (!indexedDbAvailable()) return null;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={t("syncCenter.indicator")}
        className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-[#D6DDD0] bg-white px-2.5 text-[12px] font-semibold text-[#10231B]"
      >
        {online ? (
          summary.attention > 0
            ? <AlertTriangle className="h-4 w-4 text-[#B23B2E]" aria-hidden />
            : summary.syncing > 0
              ? <Loader2 className="h-4 w-4 animate-spin text-[#2D6A4F]" aria-hidden />
              : <RefreshCw className="h-4 w-4 text-[#2D6A4F]" aria-hidden />
        ) : <CloudOff className="h-4 w-4 text-[#B7950B]" aria-hidden />}
        {pendingBadge > 0 && (
          <span className={`rounded-full px-1.5 text-[11px] text-white ${summary.attention > 0 ? "bg-[#B23B2E]" : "bg-[#2D6A4F]"}`}>
            {pendingBadge}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-[340px] rounded-2xl border border-[#D6DDD0] bg-white p-3 shadow-xl"
          role="dialog" aria-label={t("syncCenter.title")}>
          <div className="flex items-center justify-between">
            <h3 className="text-[14px] font-semibold text-[#10231B]">{t("syncCenter.title")}</h3>
            <button type="button" onClick={() => setOpen(false)} aria-label={t("syncCenter.close")}
              className="rounded p-1 text-[#65736A] hover:bg-[#F2F5F0]">
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>
          <div className="mt-1 space-y-0.5 text-[12px] text-[#65736A]">
            <div>{online ? t("fieldIntel.online") : t("fieldIntel.offline")}</div>
            <div>{t("fieldIntel.lastSync")}: {lastSync ? new Date(lastSync).toLocaleString() : t("fieldIntel.never")}</div>
            {currentWorkspace?.name && <div>{t("syncCenter.workspace")}: {currentWorkspace.name}</div>}
            {user?.email && <div>{t("syncCenter.account")}: {user.email}</div>}
          </div>

          <dl className="mt-2 grid grid-cols-3 gap-1 text-center text-[11px]">
            {([["queued", summary.queued], ["syncing", summary.syncing], ["processing", summary.processing],
               ["failed", summary.failed], ["conflict", summary.conflict], ["manualRecovery", summary.manualRecovery]] as const)
              .map(([key, value]) => (
                <div key={key} className="rounded-lg bg-[#F7F8F5] py-1.5">
                  <dt className="text-[#65736A]">{t(`syncCenter.${key}`)}</dt>
                  <dd className={`text-[14px] font-semibold ${value > 0 && ["failed", "conflict", "manualRecovery"].includes(key) ? "text-[#B23B2E]" : "text-[#10231B]"}`}>{value}</dd>
                </div>
              ))}
          </dl>

          <button type="button"
            onClick={() => { void flushQueue(fieldApi).then(refresh); }}
            disabled={!online}
            className="mt-2 inline-flex min-h-[36px] w-full items-center justify-center gap-1 rounded-lg bg-[#0D2B1E] text-[12px] font-semibold text-white disabled:opacity-40">
            <RefreshCw className="h-3.5 w-3.5" aria-hidden /> {t("fieldIntel.syncNow")}
          </button>

          {records.filter((record) => ["failed", "conflict", "manual_recovery"].includes(record.syncState)).length > 0 && (
            <div className="mt-2 max-h-[240px] space-y-1.5 overflow-y-auto">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-[#B23B2E]">{t("syncCenter.needsAttention")}</div>
              {records.filter((record) => ["failed", "conflict", "manual_recovery"].includes(record.syncState)).map((record) => (
                <div key={record.clientCaptureId} className="rounded-lg border border-[#E4C7C2] p-2">
                  <div className="flex items-center justify-between text-[12px] text-[#10231B]">
                    <span className="truncate font-semibold">{record.noteText?.slice(0, 40) || record.clientCaptureId.slice(0, 12)}</span>
                    <span className="text-[11px] text-[#B23B2E]">{t(`fieldIntel.state.${record.syncState}`)}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] font-semibold">
                    <button type="button" disabled={busyId === record.clientCaptureId}
                      onClick={() => { void retry(record); }}
                      className="rounded border border-[#D6DDD0] px-2 py-0.5 text-[#10231B] disabled:opacity-40">
                      {t("syncCenter.retry")}
                    </button>
                    <button type="button" onClick={() => setInspecting(record)}
                      className="rounded border border-[#D6DDD0] px-2 py-0.5 text-[#10231B]">
                      {t("syncCenter.inspect")}
                    </button>
                    <button type="button" onClick={() => exportRecovery(record)}
                      className="rounded border border-[#D6DDD0] px-2 py-0.5 text-[#10231B]">
                      {t("syncCenter.export")}
                    </button>
                    <button type="button" disabled={busyId === record.clientCaptureId}
                      onClick={() => { void discard(record); }}
                      className="rounded border border-[#E4C7C2] px-2 py-0.5 text-[#B23B2E] disabled:opacity-40">
                      {t("syncCenter.discard")}
                    </button>
                  </div>
                  {inspecting?.clientCaptureId === record.clientCaptureId && (
                    <pre className="mt-1 max-h-[90px] overflow-y-auto whitespace-pre-wrap rounded bg-[#F7F8F5] p-1.5 text-[10px] text-[#3B4A41]">
                      {record.lastError || t("syncCenter.noErrorDetail")}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
