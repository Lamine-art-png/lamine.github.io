import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, CheckCircle2, Cloud, CloudOff, Loader2, MapPin, Mic, Paperclip,
  RefreshCw, Search, Square, Trash2, Radio,
} from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { useLocale } from "../hooks/useLocale";
import { apiClient } from "../api/client";
import { fieldApi } from "../fieldIntelligence/fieldApi";
import {
  allCaptures, configureIdentity, deleteUnsyncedRecord, flushQueue, getLastSyncedAt, indexedDbAvailable,
  newCaptureId, pendingCount, putAsset, putCapture, retryRecord, subscribe,
  type CaptureRecord, type SyncState,
} from "../fieldIntelligence/offlineQueue";

const SEVERITIES = ["info", "low", "medium", "high", "critical"] as const;
const EVENT_TYPES = [
  "observation", "irrigation_event", "issue", "meter_reading",
  "pest_disease", "equipment", "compliance_note", "operator_note",
] as const;
const SYNC_STATES: SyncState[] = ["draft", "queued", "syncing", "processing", "synced", "failed", "conflict"];

type Observation = Record<string, any>;

export function FieldIntelligence() {
  const { t } = useLocale();
  const { entitlements, currentWorkspace, workspaces, currentOrganization, user } = useAuth() as any;
  const workspaceId: string | undefined = currentWorkspace?.id || workspaces?.[0]?.id;

  // Namespace the offline queue by authenticated org + user so one account can
  // never read or sync another account's local captures. Re-runs on login,
  // logout, account/org change.
  useEffect(() => {
    configureIdentity(currentOrganization?.id || null, user?.id || null);
  }, [currentOrganization?.id, user?.id]);

  const capabilityEnabled = useMemo(() => {
    const caps = (entitlements?.capabilities || {}) as Record<string, unknown>;
    if (!caps || typeof caps !== "object") return true;
    const value = caps["field_intelligence.capture"];
    return value === undefined ? true : value === true || value === "enabled" || value === "preview";
  }, [entitlements]);

  const [online, setOnline] = useState<boolean>(typeof navigator === "undefined" ? true : navigator.onLine);
  const [pending, setPending] = useState(0);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [locals, setLocals] = useState<CaptureRecord[]>([]);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [view, setView] = useState<"timeline" | "map">("timeline");
  const [selected, setSelected] = useState<Observation | null>(null);
  const [query, setQuery] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [stateFilter, setStateFilter] = useState("");
  const [banner, setBanner] = useState<string | null>(null);

  const refreshLocal = useCallback(async () => {
    if (!indexedDbAvailable()) return;
    setLocals(await allCaptures());
    setPending(await pendingCount());
    setLastSync(await getLastSyncedAt());
  }, []);

  const loadObservations = useCallback(async () => {
    try {
      const res: any = await apiClient.fieldIntelligence.observations(
        workspaceId ? `workspace_id=${encodeURIComponent(workspaceId)}` : undefined,
      );
      setObservations(res?.observations || []);
    } catch {
      // offline / unauthorized — timeline still shows local records
    }
  }, [workspaceId]);

  const doFlush = useCallback(async () => {
    if (!indexedDbAvailable()) return;
    await flushQueue(fieldApi);
    await refreshLocal();
    await loadObservations();
  }, [refreshLocal, loadObservations]);

  useEffect(() => { refreshLocal(); loadObservations(); }, [refreshLocal, loadObservations]);
  useEffect(() => subscribe(() => { refreshLocal(); }), [refreshLocal]);

  useEffect(() => {
    const goOnline = () => { setOnline(true); doFlush(); };
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    const timer = window.setInterval(() => { if (navigator.onLine) doFlush(); }, 30000);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
      window.clearInterval(timer);
    };
  }, [doFlush]);

  if (!capabilityEnabled) {
    return (
      <div className="min-h-full px-5 py-6" style={{ background: "#F6F4EE" }}>
        <div className="mx-auto max-w-xl rounded-2xl border border-[#D6DDD0] bg-white p-8 text-center">
          <Radio className="mx-auto mb-3 h-8 w-8 text-[#2D6A4F]" aria-hidden />
          <h1 className="text-[22px] font-semibold text-[#10231B]">{t("fieldIntel.title")}</h1>
          <p className="mt-2 text-[14px] text-[#65736A]">{t("fieldIntel.locked")}</p>
          <a href="/pricing" className="mt-5 inline-block rounded-lg bg-[#0D2B1E] px-4 py-2 text-[13px] font-semibold text-white">
            {t("fieldIntel.upgrade")}
          </a>
        </div>
      </div>
    );
  }

  const filteredObs = observations.filter((obs) => {
    if (severityFilter && obs.severity !== severityFilter) return false;
    if (query) {
      const hay = `${obs.summary || ""} ${obs.transcript || ""} ${obs.field_name || ""}`.toLowerCase();
      if (!hay.includes(query.toLowerCase())) return false;
    }
    return true;
  });
  const filteredLocals = locals.filter((r) => (stateFilter ? r.syncState === stateFilter : true));

  return (
    <div className="min-h-full px-4 py-5 md:px-6 md:py-6" style={{ background: "#F6F4EE" }}>
      <ShellHeader
        t={t} online={online} pending={pending} lastSync={lastSync}
        onSync={doFlush} view={view} onView={setView}
      />

      {banner && (
        <div role="status" className="mt-3 rounded-lg border border-[#D6DDD0] bg-[#FFFDF8] px-4 py-2 text-[13px] text-[#10231B]">
          {banner}
        </div>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <Composer t={t} workspaceId={workspaceId} onSaved={async (msg) => { setBanner(msg); await refreshLocal(); if (navigator.onLine) await doFlush(); }} />

        <section className="rounded-2xl border border-[#D6DDD0] bg-white p-4">
          <FilterBar
            t={t} query={query} setQuery={setQuery}
            severityFilter={severityFilter} setSeverityFilter={setSeverityFilter}
            stateFilter={stateFilter} setStateFilter={setStateFilter}
          />
          {view === "map" ? (
            <MapView t={t} observations={filteredObs} />
          ) : (
            <Timeline
              t={t}
              locals={filteredLocals}
              observations={filteredObs}
              onRetry={async (id) => { await retryRecord(fieldApi, id); await refreshLocal(); await loadObservations(); }}
              onDelete={async (id) => { if (window.confirm(t("fieldIntel.confirmDelete"))) { await deleteUnsyncedRecord(id); await refreshLocal(); } }}
              onSelect={setSelected}
            />
          )}
        </section>
      </div>

      {selected && (
        <ObservationDetail
          t={t} observation={selected} onClose={() => setSelected(null)}
          onReload={async () => { await loadObservations(); }}
        />
      )}
    </div>
  );
}

function ShellHeader({ t, online, pending, lastSync, onSync, view, onView }: any) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#2D6A4F]">{t("fieldIntel.eyebrow")}</div>
        <h1 className="mt-1 text-[26px] font-semibold tracking-tight text-[#10231B]">{t("fieldIntel.title")}</h1>
        <p className="mt-1 max-w-2xl text-[13px] text-[#65736A]">{t("fieldIntel.subtitle")}</p>
      </div>
      <div className="flex items-center gap-3">
        <span
          className="inline-flex items-center gap-1 rounded-full px-3 py-1 text-[12px] font-semibold"
          style={{ background: online ? "#E7F3EC" : "#FBEAE7", color: online ? "#1B5E3F" : "#B23B2E" }}
          role="status"
          aria-live="polite"
        >
          {online ? <Cloud className="h-4 w-4" aria-hidden /> : <CloudOff className="h-4 w-4" aria-hidden />}
          {online ? t("fieldIntel.online") : t("fieldIntel.offline")}
        </span>
        <span className="text-[12px] text-[#65736A]">
          {t("fieldIntel.pending")}: <strong className="text-[#10231B]">{pending}</strong>
        </span>
        <span className="hidden text-[12px] text-[#65736A] sm:inline">
          {t("fieldIntel.lastSync")}: {lastSync ? new Date(lastSync).toLocaleTimeString() : t("fieldIntel.never")}
        </span>
        <button
          type="button" onClick={onSync}
          className="inline-flex min-h-[40px] items-center gap-1 rounded-lg border border-[#D6DDD0] bg-white px-3 text-[13px] font-semibold text-[#10231B]"
          aria-label={t("fieldIntel.syncNow")}
        >
          <RefreshCw className="h-4 w-4" aria-hidden /> {t("fieldIntel.syncNow")}
        </button>
        <div className="inline-flex overflow-hidden rounded-lg border border-[#D6DDD0]">
          {(["timeline", "map"] as const).map((mode) => (
            <button
              key={mode} type="button" onClick={() => onView(mode)}
              className="min-h-[40px] px-3 text-[13px] font-semibold"
              style={{ background: view === mode ? "#0D2B1E" : "#FFFFFF", color: view === mode ? "#FFFFFF" : "#10231B" }}
            >
              {mode === "timeline" ? t("fieldIntel.timeline") : t("fieldIntel.map")}
            </button>
          ))}
        </div>
      </div>
    </header>
  );
}

function Composer({ t, workspaceId, onSaved }: any) {
  const [note, setNote] = useState("");
  const [fieldName, setFieldName] = useState("");
  const [blockName, setBlockName] = useState("");
  const [crop, setCrop] = useState("");
  const [eventType, setEventType] = useState("observation");
  const [severity, setSeverity] = useState("info");
  const [assignee, setAssignee] = useState("");
  const [attachments, setAttachments] = useState<File[]>([]);
  const [location, setLocation] = useState<{ lat: number; lon: number; acc: number } | null>(null);
  const [locError, setLocError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [micError, setMicError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioRef = useRef<File | null>(null);
  const timerRef = useRef<number | null>(null);

  const micSupported = typeof window !== "undefined" && typeof (window as any).MediaRecorder !== "undefined"
    && !!navigator?.mediaDevices?.getUserMedia;

  const startRecording = useCallback(async () => {
    setMicError(null);
    if (!micSupported) { setMicError(t("fieldIntel.micUnsupported")); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        audioRef.current = new File([blob], `capture-${Date.now()}.webm`, { type: blob.type });
        stream.getTracks().forEach((track) => track.stop());
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
      setElapsed(0);
      timerRef.current = window.setInterval(() => setElapsed((v) => v + 1), 1000);
    } catch {
      setMicError(t("fieldIntel.micDenied"));
    }
  }, [micSupported, t]);

  const stopRecording = useCallback(() => {
    recorderRef.current?.stop();
    if (timerRef.current) window.clearInterval(timerRef.current);
    setRecording(false);
  }, []);

  const captureLocation = useCallback(() => {
    setLocError(null);
    if (!navigator?.geolocation) { setLocError(t("fieldIntel.locationDenied")); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => setLocation({ lat: pos.coords.latitude, lon: pos.coords.longitude, acc: pos.coords.accuracy }),
      () => setLocError(t("fieldIntel.locationDenied")),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }, [t]);

  const submit = useCallback(async () => {
    if (!note.trim() && !audioRef.current) return;
    const clientCaptureId = newCaptureId();
    const assetManifest: { client_asset_id: string; kind: string; content_type: string }[] = [];
    const assetBlobs: { id: string; kind: "audio" | "photo" | "video" | "file"; file: File; duration?: number }[] = [];

    if (audioRef.current) {
      const id = `${clientCaptureId}_audio`;
      assetManifest.push({ client_asset_id: id, kind: "audio", content_type: audioRef.current.type });
      assetBlobs.push({ id, kind: "audio", file: audioRef.current, duration: elapsed || undefined });
    }
    attachments.forEach((file, index) => {
      const id = `${clientCaptureId}_att${index}`;
      const kind = file.type.startsWith("image/") ? "photo" : file.type.startsWith("video/") ? "video" : "file";
      assetManifest.push({ client_asset_id: id, kind, content_type: file.type });
      assetBlobs.push({ id, kind, file });
    });

    const record: CaptureRecord = {
      clientCaptureId,
      idempotencyKey: clientCaptureId,
      createdAt: Date.now(),
      workspaceId,
      captureSource: audioRef.current ? "voice" : "typed",
      noteText: note.trim() || undefined,
      fieldName: fieldName || undefined,
      blockName: blockName || undefined,
      crop: crop || undefined,
      eventType,
      severity,
      assignee: assignee || undefined,
      occurredAt: new Date().toISOString(),
      latitude: location?.lat ?? null,
      longitude: location?.lon ?? null,
      locationAccuracyM: location?.acc ?? null,
      assetManifest,
      syncState: "queued",
      retryCount: 0,
    };
    await putCapture(record);
    for (const asset of assetBlobs) {
      await putAsset({
        id: asset.id, clientCaptureId, kind: asset.kind, contentType: asset.file.type,
        filename: asset.file.name, durationSeconds: asset.duration, blob: asset.file, uploaded: false,
      });
    }
    // reset composer
    setNote(""); setAttachments([]); setLocation(null); audioRef.current = null; setElapsed(0);
    setFieldName(""); setBlockName(""); setCrop(""); setSeverity("info"); setEventType("observation"); setAssignee("");
    onSaved(t("fieldIntel.saved"));
  }, [note, attachments, elapsed, workspaceId, fieldName, blockName, crop, eventType, severity, assignee, location, onSaved, t]);

  return (
    <section className="rounded-2xl border border-[#D6DDD0] bg-white p-4">
      <h2 className="text-[15px] font-semibold text-[#10231B]">{t("fieldIntel.compose")}</h2>

      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          onClick={recording ? stopRecording : startRecording}
          className="inline-flex min-h-[52px] min-w-[52px] items-center justify-center gap-2 rounded-xl px-4 text-[14px] font-semibold text-white"
          style={{ background: recording ? "#B23B2E" : "#0D2B1E" }}
          aria-pressed={recording}
          aria-label={recording ? t("fieldIntel.stop") : t("fieldIntel.record")}
        >
          {recording ? <Square className="h-5 w-5" aria-hidden /> : <Mic className="h-5 w-5" aria-hidden />}
          {recording ? t("fieldIntel.stop") : t("fieldIntel.record")}
        </button>
        {recording && (
          <span role="status" aria-live="assertive" className="text-[13px] font-semibold text-[#B23B2E]">
            {t("fieldIntel.recording")} {formatElapsed(elapsed)}
          </span>
        )}
      </div>
      {micError && <p className="mt-2 text-[12px] text-[#B23B2E]">{micError}</p>}

      <label className="mt-3 block text-[12px] font-semibold text-[#65736A]" htmlFor="fi-note">{t("fieldIntel.typedNote")}</label>
      <textarea
        id="fi-note" value={note} onChange={(e) => setNote(e.target.value)} rows={3}
        placeholder={t("fieldIntel.notePlaceholder")}
        className="mt-1 w-full rounded-lg border border-[#D6DDD0] px-3 py-2 text-[14px]"
      />

      <div className="mt-3 grid grid-cols-2 gap-2">
        <TextField id="fi-field" label={t("fieldIntel.field")} value={fieldName} onChange={setFieldName} />
        <TextField id="fi-block" label={t("fieldIntel.block")} value={blockName} onChange={setBlockName} />
        <TextField id="fi-crop" label={t("fieldIntel.crop")} value={crop} onChange={setCrop} />
        <TextField id="fi-assignee" label={t("fieldIntel.assignee")} value={assignee} onChange={setAssignee} />
        <SelectField id="fi-event" label={t("fieldIntel.eventType")} value={eventType} onChange={setEventType}
          options={EVENT_TYPES.map((v) => ({ value: v, label: t(`fieldIntel.evt.${v}`) }))} />
        <SelectField id="fi-sev" label={t("fieldIntel.severity")} value={severity} onChange={setSeverity}
          options={SEVERITIES.map((v) => ({ value: v, label: t(`fieldIntel.sev.${v}`) }))} />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" onClick={captureLocation}
          className="inline-flex min-h-[40px] items-center gap-1 rounded-lg border border-[#D6DDD0] px-3 text-[13px] font-semibold text-[#10231B]">
          <MapPin className="h-4 w-4" aria-hidden /> {t("fieldIntel.captureLocation")}
        </button>
        <label className="inline-flex min-h-[40px] cursor-pointer items-center gap-1 rounded-lg border border-[#D6DDD0] px-3 text-[13px] font-semibold text-[#10231B]">
          <Paperclip className="h-4 w-4" aria-hidden /> {t("fieldIntel.attach")}
          <input type="file" multiple className="hidden"
            onChange={(e) => setAttachments(Array.from(e.target.files || []))}
            accept="image/*,video/*,audio/*,application/pdf" />
        </label>
        {location && (
          <span className="text-[12px] text-[#1B5E3F]">
            {t("fieldIntel.locationCaptured")} ({t("fieldIntel.accuracy")}: {Math.round(location.acc)}m)
          </span>
        )}
        {attachments.length > 0 && (
          <span className="text-[12px] text-[#65736A]">{attachments.length} {t("fieldIntel.attachments")}</span>
        )}
      </div>
      {locError && <p className="mt-2 text-[12px] text-[#B23B2E]">{locError}</p>}

      <button type="button" onClick={submit}
        className="mt-4 inline-flex min-h-[48px] w-full items-center justify-center rounded-xl bg-[#0D2B1E] px-4 text-[14px] font-semibold text-white">
        {t("fieldIntel.saveOffline")}
      </button>
    </section>
  );
}

function FilterBar({ t, query, setQuery, severityFilter, setSeverityFilter, stateFilter, setStateFilter }: any) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <div className="relative flex-1 min-w-[160px]">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-[#9AA79E]" aria-hidden />
        <input value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder={t("fieldIntel.searchPlaceholder")} aria-label={t("fieldIntel.searchPlaceholder")}
          className="w-full rounded-lg border border-[#D6DDD0] py-2 pl-8 pr-3 text-[13px]" />
      </div>
      <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}
        aria-label={t("fieldIntel.filterSeverity")} className="rounded-lg border border-[#D6DDD0] px-2 py-2 text-[13px]">
        <option value="">{t("fieldIntel.all")}</option>
        {SEVERITIES.map((v) => <option key={v} value={v}>{t(`fieldIntel.sev.${v}`)}</option>)}
      </select>
      <select value={stateFilter} onChange={(e) => setStateFilter(e.target.value)}
        aria-label={t("fieldIntel.filterState")} className="rounded-lg border border-[#D6DDD0] px-2 py-2 text-[13px]">
        <option value="">{t("fieldIntel.all")}</option>
        {SYNC_STATES.map((v) => <option key={v} value={v}>{t(`fieldIntel.state.${v}`)}</option>)}
      </select>
    </div>
  );
}

function Timeline({ t, locals, observations, onRetry, onDelete, onSelect }: any) {
  if (locals.length === 0 && observations.length === 0) {
    return <p className="py-10 text-center text-[13px] text-[#65736A]">{t("fieldIntel.noObservations")}</p>;
  }
  return (
    <ul className="space-y-2">
      {locals.filter((r: CaptureRecord) => r.syncState !== "synced").map((record: CaptureRecord) => (
        <li key={record.clientCaptureId} className="rounded-xl border border-dashed border-[#D6DDD0] bg-[#FBFAF6] p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <StateChip t={t} state={record.syncState} />
              <p className="mt-1 truncate text-[13px] text-[#10231B]">{record.noteText || t("fieldIntel.voiceCapture")}</p>
              {record.lastError && <p className="text-[11px] text-[#B23B2E]">{record.lastError}</p>}
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <button type="button" onClick={() => onRetry(record.clientCaptureId)} aria-label={t("fieldIntel.retry")}
                className="inline-flex min-h-[36px] min-w-[36px] items-center justify-center rounded-lg border border-[#D6DDD0]">
                <RefreshCw className="h-4 w-4" aria-hidden />
              </button>
              <button type="button" onClick={() => onDelete(record.clientCaptureId)} aria-label={t("fieldIntel.delete")}
                className="inline-flex min-h-[36px] min-w-[36px] items-center justify-center rounded-lg border border-[#D6DDD0] text-[#B23B2E]">
                <Trash2 className="h-4 w-4" aria-hidden />
              </button>
            </div>
          </div>
        </li>
      ))}
      {observations.map((obs: Observation) => (
        <li key={obs.id}>
          <button type="button" onClick={() => onSelect(obs)}
            className="w-full rounded-xl border border-[#D6DDD0] bg-white p-3 text-left hover:border-[#2D6A4F]">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <SeverityDot severity={obs.severity} />
                <span className="text-[13px] font-semibold text-[#10231B]">{obs.field_name || t("fieldIntel.unassignedField")}</span>
                <span className="text-[11px] text-[#65736A]">{obs.event_type ? t(`fieldIntel.evt.${obs.event_type}`) : ""}</span>
              </div>
              <span className="text-[11px] text-[#9AA79E]">{obs.occurred_at ? new Date(obs.occurred_at).toLocaleString() : ""}</span>
            </div>
            <p className="mt-1 line-clamp-2 text-[13px] text-[#3B4A41]">{obs.summary || obs.corrected_transcript || obs.transcript}</p>
            <div className="mt-1 flex items-center gap-3 text-[11px] text-[#65736A]">
              <span>{t("fieldIntel.confidence")}: {Math.round((obs.confidence || 0) * 100)}%</span>
              {obs.status === "needs_review" && <span className="text-[#B26B00]">{t("fieldIntel.needsReview")}</span>}
              {(obs.task_ids || []).length > 0 && <span>{(obs.task_ids || []).length} {t("fieldIntel.tasks")}</span>}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function MapView({ t, observations }: any) {
  const points = observations.filter((o: Observation) => o.location);
  return (
    <div className="rounded-xl border border-[#D6DDD0] bg-[#F2F5F0] p-4">
      <div className="flex items-center gap-2 text-[13px] font-semibold text-[#10231B]">
        <MapPin className="h-4 w-4" aria-hidden /> {t("fieldIntel.mapFallback")}
      </div>
      {points.length === 0 ? (
        <p className="mt-3 text-[13px] text-[#65736A]">{t("fieldIntel.noGeolocated")}</p>
      ) : (
        <ul className="mt-3 space-y-1">
          {points.map((o: Observation) => (
            <li key={o.id} className="flex items-center gap-2 text-[12px] text-[#3B4A41]">
              <SeverityDot severity={o.severity} />
              <span>{o.field_name || t("fieldIntel.unassignedField")}</span>
              <span className="text-[#9AA79E]">{o.location.latitude.toFixed(4)}, {o.location.longitude.toFixed(4)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ObservationDetail({ t, observation, onClose, onReload }: any) {
  const [correcting, setCorrecting] = useState(false);
  const [corrected, setCorrected] = useState(observation.corrected_transcript || observation.transcript || "");
  const [busy, setBusy] = useState(false);
  const correlation = observation.correlation || {};

  const saveCorrection = async () => {
    setBusy(true);
    try {
      await apiClient.fieldIntelligence.patchObservation(observation.id, { corrected_transcript: corrected });
      setCorrecting(false);
      await onReload();
    } finally { setBusy(false); }
  };
  const createTask = async () => {
    setBusy(true);
    try { await apiClient.fieldIntelligence.createTask(observation.id, {}); await onReload(); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-[120] flex justify-end bg-black/30" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="h-full w-full max-w-lg overflow-y-auto bg-white p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="text-[18px] font-semibold text-[#10231B]">{observation.field_name || t("fieldIntel.unassignedField")}</h2>
          <button type="button" onClick={onClose} className="rounded-lg border border-[#D6DDD0] px-3 py-1 text-[13px]">{t("fieldIntel.close")}</button>
        </div>

        <Section title={t("fieldIntel.transcript")}>
          {correcting ? (
            <>
              <textarea value={corrected} onChange={(e) => setCorrected(e.target.value)} rows={3}
                className="w-full rounded-lg border border-[#D6DDD0] px-3 py-2 text-[13px]" aria-label={t("fieldIntel.correctTranscript")} />
              <div className="mt-2 flex gap-2">
                <button type="button" disabled={busy} onClick={saveCorrection} className="rounded-lg bg-[#0D2B1E] px-3 py-1 text-[13px] font-semibold text-white">{t("fieldIntel.save")}</button>
                <button type="button" onClick={() => setCorrecting(false)} className="rounded-lg border border-[#D6DDD0] px-3 py-1 text-[13px]">{t("fieldIntel.cancel")}</button>
              </div>
            </>
          ) : (
            <>
              <p className="text-[13px] text-[#3B4A41]">{observation.corrected_transcript || observation.transcript || observation.summary || "—"}</p>
              <button type="button" onClick={() => setCorrecting(true)} className="mt-1 text-[12px] font-semibold text-[#2D6A4F]">{t("fieldIntel.correctTranscript")}</button>
            </>
          )}
        </Section>

        <Section title={t("fieldIntel.summary")}>
          <p className="text-[13px] text-[#3B4A41]">{observation.summary || "—"}</p>
          <p className="mt-1 text-[12px] text-[#65736A]">{t("fieldIntel.confidence")}: {Math.round((observation.confidence || 0) * 100)}%</p>
          {(observation.uncertain_fields || []).length > 0 && (
            <p className="mt-1 flex items-center gap-1 text-[12px] text-[#B26B00]">
              <AlertTriangle className="h-3 w-3" aria-hidden /> {t("fieldIntel.uncertain")}: {(observation.uncertain_fields || []).join(", ")}
            </p>
          )}
        </Section>

        <Section title={t("fieldIntel.recommended")}>
          <p className="text-[13px] text-[#3B4A41]">{observation.recommended_action || "—"}</p>
          <button type="button" disabled={busy} onClick={createTask} className="mt-2 inline-flex items-center gap-1 rounded-lg bg-[#0D2B1E] px-3 py-1 text-[13px] font-semibold text-white">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <CheckCircle2 className="h-4 w-4" aria-hidden />} {t("fieldIntel.createTask")}
          </button>
        </Section>

        <Section title={t("fieldIntel.correlation")}>
          <p className="text-[13px] text-[#3B4A41]">{correlation.explanation || t("fieldIntel.noCorrelation")}</p>
          {correlation.source_providers && (
            <p className="mt-1 text-[12px] text-[#65736A]">{t("fieldIntel.sources")}: {(correlation.source_providers || []).join(", ") || "—"}</p>
          )}
        </Section>

        <Section title={t("fieldIntel.provenance")}>
          <ul className="text-[12px] text-[#65736A]">
            {Object.entries(observation.provenance || {}).map(([key, value]) => (
              <li key={key}>{key}: {String(value)}</li>
            ))}
          </ul>
        </Section>

        <Section title={t("fieldIntel.audit")}>
          <ul className="space-y-1 text-[12px] text-[#65736A]">
            {(observation.audit_history || []).map((event: any, index: number) => (
              <li key={index}>{event.action} — {event.at}</li>
            ))}
          </ul>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: any) {
  return (
    <section className="mt-4 border-t border-[#EEE9DE] pt-3">
      <h3 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-[#2D6A4F]">{title}</h3>
      <div className="mt-1">{children}</div>
    </section>
  );
}

function TextField({ id, label, value, onChange }: any) {
  return (
    <div>
      <label htmlFor={id} className="block text-[11px] font-semibold text-[#65736A]">{label}</label>
      <input id={id} value={value} onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg border border-[#D6DDD0] px-2 py-2 text-[13px]" />
    </div>
  );
}

function SelectField({ id, label, value, onChange, options }: any) {
  return (
    <div>
      <label htmlFor={id} className="block text-[11px] font-semibold text-[#65736A]">{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg border border-[#D6DDD0] px-2 py-2 text-[13px]">
        {options.map((opt: any) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
      </select>
    </div>
  );
}

function StateChip({ t, state }: { t: any; state: SyncState }) {
  const colors: Record<SyncState, string> = {
    draft: "#65736A", queued: "#2D6A4F", syncing: "#B26B00", processing: "#B26B00",
    synced: "#1B5E3F", failed: "#B23B2E", conflict: "#B23B2E",
  };
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold"
      style={{ background: "#F2F5F0", color: colors[state] }}>
      {(state === "syncing" || state === "processing") && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
      {t(`fieldIntel.state.${state}`)}
    </span>
  );
}

function SeverityDot({ severity }: { severity?: string }) {
  const colors: Record<string, string> = {
    info: "#2D6A4F", low: "#5B8C5A", medium: "#B26B00", high: "#D9534F", critical: "#B23B2E",
  };
  return <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: colors[severity || "info"] || "#2D6A4F" }} aria-hidden />;
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60).toString().padStart(2, "0");
  const s = (seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}
