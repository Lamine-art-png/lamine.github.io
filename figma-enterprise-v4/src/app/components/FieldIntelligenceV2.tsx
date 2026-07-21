import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Activity, AlertTriangle, Camera, CheckCircle2, Cloud, CloudOff, ImagePlus,
  Loader2, MapPin, Mic, Navigation, Paperclip, RefreshCw, Search, Sparkles,
  Square, Trash2, X,
} from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { useLocale } from "../hooks/useLocale";
import { apiClient } from "../api/client";
import { fieldApi } from "../fieldIntelligence/fieldApi";
import {
  allCaptures, configureIdentity, deleteUnsyncedRecord, flushQueue, getLastSyncedAt,
  indexedDbAvailable, newCaptureId, pendingCount, putAsset, putCapture, retryRecord,
  subscribe, type CaptureRecord, type SyncState,
} from "../fieldIntelligence/offlineQueue";
import { FieldMapV2 } from "../fieldIntelligence/FieldMapV2";
import { MediaViewer } from "../fieldIntelligence/MediaViewer";

const SEVERITIES = ["info", "low", "medium", "high", "critical"] as const;
const EVENT_TYPES = [
  "observation", "irrigation_event", "issue", "meter_reading",
  "pest_disease", "equipment", "compliance_note", "operator_note",
] as const;
const SYNC_STATES: SyncState[] = ["draft", "queued", "syncing", "processing", "synced", "failed", "conflict", "manual_recovery"];
const MAX_RECORDING_SECONDS = 900;
type Observation = Record<string, any>;
type LocationFix = { lat: number; lon: number; acc: number };

const MAX_VISION_UPLOAD_BYTES = 7_500_000;

async function optimizeFieldImage(file: File): Promise<File> {
  if (!file.type.startsWith("image/") || file.size <= MAX_VISION_UPLOAD_BYTES) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const maxSide = 2200;
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) { bitmap.close(); return file; }
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.86));
    if (!blob || blob.size >= file.size) return file;
    const base = file.name.replace(/\.[^.]+$/, "") || "field-photo";
    return new File([blob], `${base}-optimized.jpg`, { type: "image/jpeg", lastModified: file.lastModified });
  } catch {
    return file;
  }
}

function stateLabel(t: (key: string) => string, status?: string) {
  if (!status) return t("fieldIntel.state.processing");
  if (status === "staged") return t("fieldIntel.state.queued");
  if (status === "completed" || status === "acknowledged") return t("fieldIntel.state.synced");
  if (status === "needs_review") return t("fieldIntel.needsReview");
  return t(`fieldIntel.state.${status}`);
}

function pipelineStep(status: string | undefined, hasTranscript: boolean, hasVision: boolean) {
  if (status === "failed") return 0;
  if (status === "staged") return 1;
  if (status === "processing" && !hasTranscript) return 2;
  if (status === "processing" && hasTranscript && !hasVision) return 3;
  return 4;
}

export function FieldIntelligenceV2() {
  const { t } = useLocale();
  const { entitlements, currentWorkspace, workspaces, currentOrganization, user } = useAuth() as any;
  const workspaceId: string | undefined = currentWorkspace?.id || workspaces?.[0]?.id;
  const [online, setOnline] = useState(typeof navigator === "undefined" ? true : navigator.onLine);
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

  useEffect(() => {
    configureIdentity(currentOrganization?.id || null, user?.id || null);
  }, [currentOrganization?.id, user?.id]);

  const capabilityEnabled = useMemo(() => {
    const caps = (entitlements?.capabilities || {}) as Record<string, unknown>;
    const value = caps["field_intelligence.capture"];
    return value === undefined || value === true || value === "enabled" || value === "preview";
  }, [entitlements]);

  const refreshLocal = useCallback(async () => {
    if (!indexedDbAvailable()) return;
    setLocals(await allCaptures());
    setPending(await pendingCount());
    setLastSync(await getLastSyncedAt());
  }, []);

  const loadObservations = useCallback(async () => {
    try {
      const response: any = await apiClient.fieldIntelligence.observations(
        workspaceId ? `workspace_id=${encodeURIComponent(workspaceId)}` : undefined,
      );
      const next = response?.observations || [];
      setObservations(next);
      setSelected((current) => current ? next.find((item: Observation) => item.id === current.id) || current : null);
    } catch {
      // Local queue remains usable while offline.
    }
  }, [workspaceId]);

  const doFlush = useCallback(async () => {
    if (!indexedDbAvailable()) return;
    await flushQueue(fieldApi);
    await Promise.all([refreshLocal(), loadObservations()]);
  }, [refreshLocal, loadObservations]);

  useEffect(() => { void refreshLocal(); void loadObservations(); }, [refreshLocal, loadObservations]);
  useEffect(() => subscribe(() => { void refreshLocal(); }), [refreshLocal]);

  useEffect(() => {
    const goOnline = () => { setOnline(true); void doFlush(); };
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, [doFlush]);

  const processingActive = pending > 0 || observations.some((obs) => ["staged", "processing"].includes(String(obs.status || "")));
  useEffect(() => {
    if (!online) return;
    const interval = window.setInterval(() => {
      if (processingActive) {
        void doFlush();
      } else {
        void loadObservations();
      }
    }, processingActive ? 2200 : 12000);
    return () => window.clearInterval(interval);
  }, [online, processingActive, doFlush, loadObservations]);

  if (!capabilityEnabled) {
    return (
      <div className="min-h-full bg-[#F6F4EE] px-5 py-8">
        <div className="mx-auto max-w-xl rounded-2xl border border-[#D6DDD0] bg-white p-8 text-center">
          <Sparkles className="mx-auto h-9 w-9 text-[#2D6A4F]" />
          <h1 className="mt-3 text-[22px] font-semibold text-[#10231B]">{t("fieldIntel.title")}</h1>
          <p className="mt-2 text-[14px] text-[#65736A]">{t("fieldIntel.locked")}</p>
          <a href="/pricing" className="mt-5 inline-flex rounded-lg bg-[#0D2B1E] px-4 py-2 text-[13px] font-semibold text-white">{t("fieldIntel.upgrade")}</a>
        </div>
      </div>
    );
  }

  const filteredObservations = observations.filter((obs) => {
    if (severityFilter && obs.severity !== severityFilter) return false;
    if (!query) return true;
    const haystack = `${obs.summary || ""} ${obs.transcript || ""} ${obs.field_name || ""} ${JSON.stringify(obs.structured || {})}`.toLowerCase();
    return haystack.includes(query.toLowerCase());
  });
  const filteredLocals = locals.filter((record) => !stateFilter || record.syncState === stateFilter);

  return (
    <div className="min-h-full bg-[#F6F4EE] px-4 py-5 md:px-6 md:py-6">
      <header className="rounded-2xl border border-[#D6DDD0] bg-[#10231B] p-5 text-white shadow-[0_20px_60px_rgba(16,35,27,0.16)]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[#92C7A9]">{t("fieldIntel.eyebrow")}</div>
            <h1 className="mt-1 text-[28px] font-semibold tracking-tight">{t("fieldIntel.title")}</h1>
            <p className="mt-2 max-w-3xl text-[13px] leading-6 text-[#D8E4DD]">{t("fieldIntel.subtitle")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded-full bg-white/10 px-3 py-1 text-[12px] font-semibold">
              {online ? <Cloud className="h-4 w-4" /> : <CloudOff className="h-4 w-4" />}
              {online ? t("fieldIntel.online") : t("fieldIntel.offline")}
            </span>
            <span className="rounded-full bg-white/10 px-3 py-1 text-[12px]">{t("fieldIntel.pending")}: {pending}</span>
            <button type="button" onClick={() => void doFlush()} className="inline-flex min-h-[40px] items-center gap-2 rounded-lg bg-white px-3 text-[13px] font-semibold text-[#10231B]">
              <RefreshCw className={`h-4 w-4 ${processingActive ? "animate-spin" : ""}`} /> {t("fieldIntel.syncNow")}
            </button>
          </div>
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-4">
          <Capability icon={<Mic className="h-4 w-4" />} title={t("fieldIntel.record")} detail={t("fieldIntel.transcript")} />
          <Capability icon={<Camera className="h-4 w-4" />} title={t("fieldIntel.photoEvidence")} detail={t("fieldIntel.correlation")} />
          <Capability icon={<Navigation className="h-4 w-4" />} title={t("fieldIntel.captureLocation")} detail={t("fieldIntel.map")} />
          <Capability icon={<Sparkles className="h-4 w-4" />} title={t("askAgroAi")} detail={t("fieldIntel.recommended")} />
        </div>
      </header>

      {banner && <div role="status" className="mt-3 rounded-xl border border-[#BFD8C9] bg-[#EDF7F1] px-4 py-3 text-[13px] font-medium text-[#1B5E3F]">{banner}</div>}

      <div className="mt-4 grid gap-4 xl:grid-cols-[430px_minmax(0,1fr)]">
        <SmartComposer
          t={t}
          workspaceId={workspaceId}
          onSaved={async (message: string) => {
            setBanner(message);
            setView("timeline");
            await refreshLocal();
            if (navigator.onLine) await doFlush();
          }}
        />

        <section className="min-w-0 rounded-2xl border border-[#D6DDD0] bg-white p-4 shadow-[0_14px_40px_rgba(16,35,27,0.06)]">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div className="relative min-w-[180px] flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#9AA79E]" />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("fieldIntel.searchPlaceholder")}
                className="w-full rounded-lg border border-[#D6DDD0] py-2 pl-9 pr-3 text-[13px]" />
            </div>
            <select value={severityFilter} onChange={(event) => setSeverityFilter(event.target.value)}
              className="rounded-lg border border-[#D6DDD0] px-2 py-2 text-[13px]" aria-label={t("fieldIntel.filterSeverity")}>
              <option value="">{t("fieldIntel.all")}</option>
              {SEVERITIES.map((value) => <option key={value} value={value}>{t(`fieldIntel.sev.${value}`)}</option>)}
            </select>
            <select value={stateFilter} onChange={(event) => setStateFilter(event.target.value)}
              className="rounded-lg border border-[#D6DDD0] px-2 py-2 text-[13px]" aria-label={t("fieldIntel.filterState")}>
              <option value="">{t("fieldIntel.all")}</option>
              {SYNC_STATES.map((value) => <option key={value} value={value}>{t(`fieldIntel.state.${value}`)}</option>)}
            </select>
            <div className="inline-flex overflow-hidden rounded-lg border border-[#D6DDD0]">
              {(["timeline", "map"] as const).map((mode) => (
                <button key={mode} type="button" onClick={() => setView(mode)}
                  className="min-h-[40px] px-3 text-[13px] font-semibold"
                  style={{ background: view === mode ? "#0D2B1E" : "#FFFFFF", color: view === mode ? "#FFFFFF" : "#10231B" }}>
                  {mode === "timeline" ? t("fieldIntel.timeline") : t("fieldIntel.map")}
                </button>
              ))}
            </div>
          </div>

          {view === "map" ? (
            <FieldMapV2 t={t} observations={filteredObservations} workspaceId={workspaceId}
              selectedId={selected?.id || null} onSelect={(observation: Observation) => setSelected(observation)} />
          ) : (
            <ObservationTimeline
              t={t}
              locals={filteredLocals}
              observations={filteredObservations}
              onSelect={setSelected}
              onRetry={async (id: string) => { await retryRecord(fieldApi, id); await doFlush(); }}
              onDelete={async (id: string) => {
                if (window.confirm(t("fieldIntel.confirmDelete"))) {
                  await deleteUnsyncedRecord(id);
                  await refreshLocal();
                }
              }}
            />
          )}
        </section>
      </div>

      {selected && <ObservationDrawer t={t} observation={selected} onClose={() => setSelected(null)}
        onReload={async () => { await loadObservations(); }} />}
    </div>
  );
}

function Capability({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
    <div className="flex items-center gap-2 text-[12px] font-semibold">{icon}{title}</div>
    <div className="mt-1 text-[11px] text-[#BFD0C7]">{detail}</div>
  </div>;
}

function SmartComposer({ t, workspaceId, onSaved }: any) {
  const [note, setNote] = useState("");
  const [fieldName, setFieldName] = useState("");
  const [blockName, setBlockName] = useState("");
  const [crop, setCrop] = useState("");
  const [eventType, setEventType] = useState("observation");
  const [severity, setSeverity] = useState("info");
  const [assignee, setAssignee] = useState("");
  const [attachments, setAttachments] = useState<File[]>([]);
  const [location, setLocation] = useState<LocationFix | null>(null);
  const [locError, setLocError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [micError, setMicError] = useState<string | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [liveTranscript, setLiveTranscript] = useState("");
  const [interimTranscript, setInterimTranscript] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recognitionRef = useRef<any>(null);
  const chunksRef = useRef<Blob[]>([]);
  const stopWaitersRef = useRef<Array<() => void>>([]);
  const timerRef = useRef<number | null>(null);
  const elapsedRef = useRef(0);

  const imagePreviews = useMemo(() => attachments.filter((file) => file.type.startsWith("image/"))
    .map((file) => ({ file, url: URL.createObjectURL(file) })), [attachments]);
  useEffect(() => () => { imagePreviews.forEach((preview) => URL.revokeObjectURL(preview.url)); }, [imagePreviews]);

  const releaseStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const stopRecognition = useCallback(() => {
    try { recognitionRef.current?.stop(); } catch { /* already stopped */ }
    recognitionRef.current = null;
    setInterimTranscript("");
  }, []);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    timerRef.current = null;
  }, []);

  useEffect(() => () => {
    clearTimer();
    stopRecognition();
    releaseStream();
    if (audioUrl) URL.revokeObjectURL(audioUrl);
  }, [audioUrl, clearTimer, releaseStream, stopRecognition]);

  const captureLocation = useCallback((silent = false) => {
    if (!navigator.geolocation) {
      if (!silent) setLocError(t("fieldIntel.locationDenied"));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocation({ lat: position.coords.latitude, lon: position.coords.longitude, acc: position.coords.accuracy });
        setLocError(null);
      },
      () => { if (!silent) setLocError(t("fieldIntel.locationDenied")); },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 15000 },
    );
  }, [t]);

  const startRecognition = useCallback(() => {
    const Recognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!Recognition) return;
    try {
      const recognition = new Recognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = document.documentElement.lang || navigator.language || "en-US";
      recognition.onresult = (event: any) => {
        let interim = "";
        let finalText = "";
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const text = String(event.results[index][0]?.transcript || "");
          if (event.results[index].isFinal) finalText += text;
          else interim += text;
        }
        if (finalText.trim()) setLiveTranscript((current) => `${current} ${finalText}`.trim());
        setInterimTranscript(interim);
      };
      recognition.onerror = () => setInterimTranscript("");
      recognitionRef.current = recognition;
      recognition.start();
    } catch {
      recognitionRef.current = null;
    }
  }, []);

  const setRecordedAudio = useCallback((file: File | null) => {
    setAudioFile(file);
    setAudioUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return file ? URL.createObjectURL(file) : null;
    });
  }, []);

  const stopRecording = useCallback(async () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      clearTimer(); stopRecognition(); releaseStream(); setRecording(false); return;
    }
    await new Promise<void>((resolve) => {
      stopWaitersRef.current.push(resolve);
      try { recorder.stop(); } catch { resolve(); }
    });
  }, [clearTimer, releaseStream, stopRecognition]);

  const startRecording = useCallback(async () => {
    setMicError(null);
    setReviewing(false);
    setLiveTranscript("");
    setInterimTranscript("");
    captureLocation(true);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setMicError(t("fieldIntel.micUnsupported"));
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      releaseStream();
      streamRef.current = stream;
      const preferred = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((kind) => MediaRecorder.isTypeSupported(kind));
      const recorder = new MediaRecorder(stream, preferred ? { mimeType: preferred } : undefined);
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (event) => { if (event.data.size > 0) chunksRef.current.push(event.data); };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        const extension = (recorder.mimeType || "").includes("mp4") ? "m4a" : "webm";
        if (blob.size > 0) setRecordedAudio(new File([blob], `field-note-${Date.now()}.${extension}`, { type: blob.type }));
        clearTimer();
        stopRecognition();
        releaseStream();
        setRecording(false);
        stopWaitersRef.current.splice(0).forEach((resolve) => resolve());
      };
      recorder.start(1000);
      startRecognition();
      setRecording(true);
      elapsedRef.current = 0;
      setElapsed(0);
      timerRef.current = window.setInterval(() => {
        elapsedRef.current += 1;
        setElapsed(elapsedRef.current);
        if (elapsedRef.current >= MAX_RECORDING_SECONDS) void stopRecording();
      }, 1000);
    } catch (error: any) {
      releaseStream();
      setMicError(error?.name === "NotAllowedError" ? t("fieldIntel.micDenied") : t("fieldIntel.micUnsupported"));
    }
  }, [captureLocation, clearTimer, releaseStream, setRecordedAudio, startRecognition, stopRecognition, stopRecording, t]);

  const addFiles = useCallback(async (files: File[]) => {
    if (!files.length) return;
    captureLocation(true);
    const optimized = await Promise.all(files.slice(0, 24).map(optimizeFieldImage));
    setAttachments((current) => [...current, ...optimized].slice(0, 24));
  }, [captureLocation]);

  const reset = useCallback(() => {
    setNote(""); setFieldName(""); setBlockName(""); setCrop(""); setEventType("observation");
    setSeverity("info"); setAssignee(""); setAttachments([]); setLocation(null); setLocError(null);
    setLiveTranscript(""); setInterimTranscript(""); setReviewing(false); setRecordedAudio(null); setElapsed(0);
  }, [setRecordedAudio]);

  const queueCapture = useCallback(async () => {
    const clientCaptureId = newCaptureId();
    const audioAsset = audioFile ? {
      id: `${clientCaptureId}-audio`, clientCaptureId, kind: "audio" as const,
      contentType: audioFile.type || "audio/webm", filename: audioFile.name,
      durationSeconds: elapsed, blob: audioFile, uploaded: false,
    } : null;
    const fileAssets = attachments.map((file, index) => ({
      id: `${clientCaptureId}-asset-${index}`, clientCaptureId,
      kind: (file.type.startsWith("image/") ? "photo" : file.type.startsWith("video/") ? "video" : file.type.startsWith("audio/") ? "audio" : "file") as "photo" | "video" | "audio" | "file",
      contentType: file.type || "application/octet-stream", filename: file.name, blob: file, uploaded: false,
    }));
    const assets = [...(audioAsset ? [audioAsset] : []), ...fileAssets];
    const transcriptPreview = liveTranscript.trim();
    const record: CaptureRecord = {
      clientCaptureId,
      idempotencyKey: `fi-${clientCaptureId}`,
      createdAt: Date.now(),
      workspaceId,
      captureSource: audioFile ? "voice" : "typed",
      // Browser live captions are an operator aid. The durable audio remains the
      // authoritative source; captions also provide useful context if the device
      // is offline or server transcription is delayed.
      noteText: note.trim() || transcriptPreview || undefined,
      fieldName: fieldName.trim() || undefined,
      blockName: blockName.trim() || undefined,
      crop: crop.trim() || undefined,
      eventType,
      severity,
      assignee: assignee.trim() || undefined,
      occurredAt: new Date().toISOString(),
      latitude: location?.lat ?? null,
      longitude: location?.lon ?? null,
      locationAccuracyM: location?.acc ?? null,
      assetManifest: assets.map((asset) => ({ client_asset_id: asset.id, kind: asset.kind, content_type: asset.contentType })),
      syncState: "queued",
      retryCount: 0,
    };
    await putCapture(record);
    for (const asset of assets) await putAsset(asset);
    reset();
    await onSaved(t("fieldIntel.saved"));
  }, [assignee, attachments, audioFile, blockName, crop, elapsed, eventType, fieldName, liveTranscript, location, note, onSaved, reset, severity, t, workspaceId]);

  if (reviewing) {
    return (
      <section className="rounded-2xl border border-[#D6DDD0] bg-white p-4 shadow-[0_14px_40px_rgba(16,35,27,0.06)]">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#2D6A4F]">{t("fieldIntel.reviewTitle")}</div>
            <p className="mt-1 text-[12px] text-[#65736A]">{t("fieldIntel.reviewHint")}</p>
          </div>
          <button type="button" onClick={() => setReviewing(false)} className="rounded-lg border border-[#D6DDD0] p-2"><X className="h-4 w-4" /></button>
        </div>
        {audioUrl && <audio controls src={audioUrl} className="mt-4 w-full" aria-label={t("fieldIntel.audioPlayer")} />}
        {liveTranscript && <div className="mt-3 rounded-xl border border-[#BFD8C9] bg-[#F1F8F4] p-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#2D6A4F]">{t("fieldIntel.transcript")}</div>
          <textarea value={liveTranscript} onChange={(event) => setLiveTranscript(event.target.value)} rows={4}
            className="mt-2 w-full resize-none rounded-lg border border-[#D6DDD0] bg-white px-3 py-2 text-[13px]" />
        </div>}
        {imagePreviews.length > 0 && <div className="mt-3 grid grid-cols-3 gap-2">
          {imagePreviews.map((preview) => <img key={preview.url} src={preview.url} alt={t("fieldIntel.photoEvidence")} className="aspect-square w-full rounded-lg object-cover" />)}
        </div>}
        <div className="mt-4 grid grid-cols-2 gap-2">
          <button type="button" onClick={() => setReviewing(false)} className="min-h-[44px] rounded-lg border border-[#D6DDD0] text-[13px] font-semibold">{t("fieldIntel.backToEdit")}</button>
          <button type="button" onClick={() => void queueCapture()} className="min-h-[44px] rounded-lg bg-[#0D2B1E] text-[13px] font-semibold text-white">{t("fieldIntel.confirmQueue")}</button>
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-2xl border border-[#D6DDD0] bg-white p-4 shadow-[0_14px_40px_rgba(16,35,27,0.06)]">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#2D6A4F]">{t("fieldIntel.compose")}</div>
          <div className="mt-1 flex items-center gap-2 text-[12px] text-[#65736A]">
            <Activity className="h-4 w-4 text-[#2D6A4F]" /> {recording ? `${t("fieldIntel.recording")} ${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}` : t("fieldIntel.recordingReady")}
          </div>
        </div>
        <button type="button" onClick={() => recording ? void stopRecording() : void startRecording()}
          className="inline-flex min-h-[48px] items-center gap-2 rounded-xl px-4 text-[14px] font-semibold text-white"
          style={{ background: recording ? "#B23B2E" : "#0D2B1E" }}>
          {recording ? <Square className="h-4 w-4 fill-current" /> : <Mic className="h-4 w-4" />}
          {recording ? t("fieldIntel.stop") : t("fieldIntel.record")}
        </button>
      </div>

      {(recording || liveTranscript || interimTranscript) && <div className="mt-3 rounded-xl border border-[#BFD8C9] bg-[#F1F8F4] p-3">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#2D6A4F]">
          <Sparkles className="h-4 w-4" /> {t("fieldIntel.transcript")}
        </div>
        <p className="mt-2 min-h-[44px] text-[13px] leading-6 text-[#10231B]">
          {liveTranscript} <span className="text-[#819188]">{interimTranscript}</span>
        </p>
      </div>}
      {audioUrl && !recording && <div className="mt-3 flex items-center gap-2 rounded-xl border border-[#D6DDD0] p-2">
        <audio controls src={audioUrl} className="min-w-0 flex-1" />
        <button type="button" onClick={() => setRecordedAudio(null)} className="rounded-lg border border-[#D6DDD0] p-2 text-[#B23B2E]"><Trash2 className="h-4 w-4" /></button>
      </div>}
      {micError && <p className="mt-2 flex items-center gap-1 text-[12px] text-[#B23B2E]"><AlertTriangle className="h-4 w-4" />{micError}</p>}

      <textarea value={note} onChange={(event) => setNote(event.target.value)} rows={4}
        placeholder={t("fieldIntel.notePlaceholder")} className="mt-3 w-full resize-none rounded-xl border border-[#D6DDD0] px-3 py-3 text-[13px]" />

      <div className="mt-3 grid grid-cols-2 gap-2">
        <Field value={fieldName} onChange={setFieldName} label={t("fieldIntel.field")} />
        <Field value={blockName} onChange={setBlockName} label={t("fieldIntel.block")} />
        <Field value={crop} onChange={setCrop} label={t("fieldIntel.crop")} />
        <Field value={assignee} onChange={setAssignee} label={t("fieldIntel.assignee")} />
        <select value={eventType} onChange={(event) => setEventType(event.target.value)} className="rounded-lg border border-[#D6DDD0] px-3 py-2 text-[13px]">
          {EVENT_TYPES.map((value) => <option key={value} value={value}>{t(`fieldIntel.evt.${value}`)}</option>)}
        </select>
        <select value={severity} onChange={(event) => setSeverity(event.target.value)} className="rounded-lg border border-[#D6DDD0] px-3 py-2 text-[13px]">
          {SEVERITIES.map((value) => <option key={value} value={value}>{t(`fieldIntel.sev.${value}`)}</option>)}
        </select>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2">
        <label className="flex min-h-[74px] cursor-pointer flex-col items-center justify-center rounded-xl border border-[#D6DDD0] bg-[#FBFAF6] text-[12px] font-semibold text-[#10231B]">
          <Camera className="mb-1 h-5 w-5 text-[#2D6A4F]" /> {t("fieldIntel.photoEvidence")}
          <input type="file" accept="image/*" capture="environment" className="hidden"
            onChange={(event) => { void addFiles(Array.from(event.target.files || [])); event.currentTarget.value = ""; }} />
        </label>
        <label className="flex min-h-[74px] cursor-pointer flex-col items-center justify-center rounded-xl border border-[#D6DDD0] bg-[#FBFAF6] text-[12px] font-semibold text-[#10231B]">
          <ImagePlus className="mb-1 h-5 w-5 text-[#2D6A4F]" /> {t("fieldIntel.attach")}
          <input type="file" multiple accept="image/*,video/*,audio/*,application/pdf" className="hidden"
            onChange={(event) => { void addFiles(Array.from(event.target.files || [])); event.currentTarget.value = ""; }} />
        </label>
        <button type="button" onClick={() => captureLocation(false)}
          className="flex min-h-[74px] flex-col items-center justify-center rounded-xl border border-[#D6DDD0] bg-[#FBFAF6] text-[12px] font-semibold text-[#10231B]">
          <MapPin className="mb-1 h-5 w-5 text-[#2D6A4F]" /> {location ? t("fieldIntel.locationCaptured") : t("fieldIntel.captureLocation")}
        </button>
      </div>

      {location && <p className="mt-2 flex items-center gap-1 text-[12px] text-[#1B5E3F]"><Navigation className="h-4 w-4" />{location.lat.toFixed(5)}, {location.lon.toFixed(5)} · {t("fieldIntel.accuracy")}: {Math.round(location.acc)}m</p>}
      {locError && <p className="mt-2 text-[12px] text-[#B23B2E]">{locError}</p>}

      {imagePreviews.length > 0 && <div className="mt-3 grid grid-cols-3 gap-2">
        {imagePreviews.map((preview, index) => <div key={preview.url} className="relative">
          <img src={preview.url} alt={t("fieldIntel.photoEvidence")} className="aspect-square w-full rounded-lg object-cover" />
          <button type="button" onClick={() => setAttachments((current) => current.filter((_, itemIndex) => itemIndex !== attachments.indexOf(preview.file)))}
            className="absolute right-1 top-1 rounded-full bg-black/70 p-1 text-white"><X className="h-3 w-3" /></button>
          {index === 0 && <span className="absolute bottom-1 left-1 rounded bg-[#10231B]/85 px-2 py-0.5 text-[10px] font-semibold text-white">{t("askAgroAi")}</span>}
        </div>)}
      </div>}

      <button type="button" onClick={async () => {
        if (recording) await stopRecording();
        setReviewing(true);
      }} disabled={!note.trim() && !audioFile && attachments.length === 0}
        className="mt-4 inline-flex min-h-[50px] w-full items-center justify-center gap-2 rounded-xl bg-[#0D2B1E] px-4 text-[14px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">
        <Sparkles className="h-4 w-4" /> {t("fieldIntel.reviewAndSave")}
      </button>
    </section>
  );
}

function Field({ value, onChange, label }: { value: string; onChange: (value: string) => void; label: string }) {
  return <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={label}
    aria-label={label} className="rounded-lg border border-[#D6DDD0] px-3 py-2 text-[13px]" />;
}

function ObservationTimeline({ t, locals, observations, onSelect, onRetry, onDelete }: any) {
  if (!locals.length && !observations.length) return <p className="py-12 text-center text-[13px] text-[#65736A]">{t("fieldIntel.noObservations")}</p>;
  return <div className="space-y-2">
    {locals.filter((record: CaptureRecord) => record.syncState !== "synced").map((record: CaptureRecord) => (
      <div key={record.clientCaptureId} className="rounded-xl border border-dashed border-[#BFD0C7] bg-[#F7FAF8] p-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="inline-flex items-center gap-2 rounded-full bg-[#E7F3EC] px-2 py-1 text-[11px] font-semibold text-[#1B5E3F]">
              <Loader2 className="h-3 w-3 animate-spin" /> {stateLabel(t, record.syncState)}
            </div>
            <p className="mt-2 truncate text-[13px] text-[#10231B]">{record.noteText || t("fieldIntel.voiceCapture")}</p>
            {record.lastError && <p className="mt-1 text-[11px] text-[#B23B2E]">{record.lastError}</p>}
          </div>
          <div className="flex gap-1">
            <button type="button" onClick={() => onRetry(record.clientCaptureId)} className="rounded-lg border border-[#D6DDD0] p-2"><RefreshCw className="h-4 w-4" /></button>
            <button type="button" onClick={() => onDelete(record.clientCaptureId)} className="rounded-lg border border-[#D6DDD0] p-2 text-[#B23B2E]"><Trash2 className="h-4 w-4" /></button>
          </div>
        </div>
      </div>
    ))}
    {observations.map((observation: Observation) => {
      const structured = observation.structured || {};
      const vision = structured.vision || {};
      const hasVision = Boolean(vision.summary || vision.observations?.length);
      const step = pipelineStep(observation.status, Boolean(observation.transcript), hasVision);
      return <button key={observation.id} type="button" onClick={() => onSelect(observation)}
        className="w-full rounded-xl border border-[#D6DDD0] bg-white p-4 text-left transition hover:border-[#2D6A4F] hover:shadow-[0_10px_30px_rgba(16,35,27,0.08)]">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: severityColor(observation.severity) }} />
              <span className="text-[13px] font-semibold text-[#10231B]">{observation.field_name || t("fieldIntel.unassignedField")}</span>
              <span className="rounded-full bg-[#F1F4F0] px-2 py-0.5 text-[10px] font-semibold text-[#65736A]">{stateLabel(t, observation.status)}</span>
              {hasVision && <span className="inline-flex items-center gap-1 rounded-full bg-[#E9F1FF] px-2 py-0.5 text-[10px] font-semibold text-[#315C9B]"><Camera className="h-3 w-3" />{t("askAgroAi")}</span>}
            </div>
            <p className="mt-2 line-clamp-2 text-[13px] leading-6 text-[#3B4A41]">{observation.summary || observation.transcript || "—"}</p>
          </div>
          <span className="shrink-0 text-[11px] text-[#9AA79E]">{observation.occurred_at ? new Date(observation.occurred_at).toLocaleString() : ""}</span>
        </div>
        <div className="mt-3 grid grid-cols-4 gap-1">
          {[1, 2, 3, 4].map((value) => <span key={value} className="h-1.5 rounded-full" style={{ background: value <= step ? "#2D6A4F" : "#E2E7E1" }} />)}
        </div>
        <div className="mt-2 flex items-center justify-between text-[11px] text-[#65736A]">
          <span>{t("fieldIntel.confidence")}: {Math.round((observation.confidence || 0) * 100)}%</span>
          <span>{(observation.assets || []).length} {t("fieldIntel.attachments")}</span>
        </div>
      </button>;
    })}
  </div>;
}

function ObservationDrawer({ t, observation, onClose, onReload }: any) {
  const [busy, setBusy] = useState(false);
  const [corrected, setCorrected] = useState(observation.corrected_transcript || observation.transcript || "");
  const [editing, setEditing] = useState(false);
  const structured = observation.structured || {};
  const vision = structured.vision || {};
  const correlation = observation.correlation || {};

  const saveCorrection = async () => {
    setBusy(true);
    try {
      await apiClient.fieldIntelligence.patchObservation(observation.id, { corrected_transcript: corrected });
      setEditing(false);
      await onReload();
    } finally { setBusy(false); }
  };

  const createTask = async () => {
    setBusy(true);
    try { await apiClient.fieldIntelligence.createTask(observation.id, {}); await onReload(); }
    finally { setBusy(false); }
  };

  return <div className="fixed inset-0 z-[120] flex justify-end bg-black/35" role="dialog" aria-modal="true" onClick={onClose}>
    <aside className="h-full w-full max-w-xl overflow-y-auto bg-white p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#2D6A4F]">{t("fieldIntel.title")}</div>
          <h2 className="mt-1 text-[22px] font-semibold text-[#10231B]">{observation.field_name || t("fieldIntel.unassignedField")}</h2>
        </div>
        <button type="button" onClick={onClose} className="rounded-lg border border-[#D6DDD0] p-2"><X className="h-4 w-4" /></button>
      </div>

      <DrawerSection title={t("fieldIntel.summary")}>
        <p className="text-[14px] leading-7 text-[#3B4A41]">{observation.summary || "—"}</p>
        <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
          <span className="rounded-full bg-[#F1F4F0] px-2 py-1">{t("fieldIntel.confidence")}: {Math.round((observation.confidence || 0) * 100)}%</span>
          <span className="rounded-full bg-[#F1F4F0] px-2 py-1">{stateLabel(t, observation.status)}</span>
        </div>
      </DrawerSection>

      {Array.isArray(observation.assets) && observation.assets.length > 0 && <DrawerSection title={t("fieldIntel.media")}>
        <MediaViewer t={t} assets={observation.assets} transcript={observation.corrected_transcript || observation.transcript || null} />
      </DrawerSection>}

      {(vision.summary || vision.observations?.length) && <DrawerSection title={t("fieldIntel.correlation")}>
        <div className="rounded-xl border border-[#BFD8C9] bg-[#F1F8F4] p-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-[#1B5E3F]"><Camera className="h-4 w-4" />{t("fieldIntel.photoEvidence")} + {t("askAgroAi")}</div>
          <p className="mt-2 text-[13px] leading-6 text-[#3B4A41]">{vision.summary || "—"}</p>
          {Array.isArray(vision.observations) && <ul className="mt-2 space-y-1 text-[12px] text-[#3B4A41]">
            {vision.observations.map((item: string, index: number) => <li key={index}>• {item}</li>)}
          </ul>}
          {Array.isArray(vision.uncertainties) && vision.uncertainties.length > 0 && <p className="mt-2 flex gap-1 text-[11px] text-[#B26B00]"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />{vision.uncertainties.join(", ")}</p>}
        </div>
      </DrawerSection>}

      <DrawerSection title={t("fieldIntel.transcript")}>
        {editing ? <>
          <textarea value={corrected} onChange={(event) => setCorrected(event.target.value)} rows={5}
            className="w-full rounded-lg border border-[#D6DDD0] px-3 py-2 text-[13px]" />
          <div className="mt-2 flex gap-2">
            <button type="button" disabled={busy} onClick={() => void saveCorrection()} className="rounded-lg bg-[#0D2B1E] px-3 py-2 text-[12px] font-semibold text-white">{t("fieldIntel.save")}</button>
            <button type="button" onClick={() => setEditing(false)} className="rounded-lg border border-[#D6DDD0] px-3 py-2 text-[12px]">{t("fieldIntel.cancel")}</button>
          </div>
        </> : <>
          <p className="text-[13px] leading-6 text-[#3B4A41]">{observation.corrected_transcript || observation.transcript || "—"}</p>
          <button type="button" onClick={() => setEditing(true)} className="mt-2 text-[12px] font-semibold text-[#2D6A4F]">{t("fieldIntel.correctTranscript")}</button>
        </>}
      </DrawerSection>

      <DrawerSection title={t("fieldIntel.recommended")}>
        <p className="text-[13px] leading-6 text-[#3B4A41]">{observation.recommended_action || vision.recommended_follow_up || "—"}</p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <button type="button" disabled={busy} onClick={() => void createTask()} className="inline-flex min-h-[42px] items-center justify-center gap-2 rounded-lg bg-[#0D2B1E] px-3 text-[12px] font-semibold text-white">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}{t("fieldIntel.createTask")}
          </button>
          <a href="/intelligence" className="inline-flex min-h-[42px] items-center justify-center gap-2 rounded-lg border border-[#D6DDD0] px-3 text-[12px] font-semibold text-[#10231B]">
            <Sparkles className="h-4 w-4" />{t("askAgroAi")}
          </a>
        </div>
      </DrawerSection>

      <DrawerSection title={t("fieldIntel.correlation")}>
        <p className="text-[13px] leading-6 text-[#3B4A41]">{correlation.explanation || t("fieldIntel.noCorrelation")}</p>
      </DrawerSection>

      {observation.location?.latitude != null && observation.location?.longitude != null && <DrawerSection title={t("fieldIntel.map")}>
        <div className="flex items-center gap-2 rounded-xl border border-[#D6DDD0] bg-[#FBFAF6] p-3 text-[13px] text-[#10231B]">
          <MapPin className="h-4 w-4 text-[#2D6A4F]" />{Number(observation.location.latitude).toFixed(5)}, {Number(observation.location.longitude).toFixed(5)}
        </div>
      </DrawerSection>}
    </aside>
  </div>;
}

function DrawerSection({ title, children }: { title: string; children: ReactNode }) {
  return <section className="mt-5 border-t border-[#EEE9DE] pt-4">
    <h3 className="text-[11px] font-semibold uppercase tracking-[0.15em] text-[#2D6A4F]">{title}</h3>
    <div className="mt-2">{children}</div>
  </section>;
}

function severityColor(severity?: string) {
  return ({ info: "#5B7FA3", low: "#4F8A68", medium: "#B8872D", high: "#C45D35", critical: "#A33232" } as Record<string, string>)[severity || "info"] || "#5B7FA3";
}
