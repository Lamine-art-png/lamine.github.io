from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


RATE_LIMITER = '''"""Tenant/user rate limits for near-real-time Field Intelligence analysis."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.core.config import settings

_WINDOWS = (("minute", 4, 60), ("hour", 60, 3600))
_MEMORY: dict[str, tuple[int, int]] = {}
_MEMORY_LOCK = threading.Lock()

_REDIS_SCRIPT = """
local allowed = 1
local remaining = nil
local retry_after = 0
for i = 1, #KEYS do
  local offset = 1 + ((i - 1) * 2)
  local limit = tonumber(ARGV[offset])
  local ttl = tonumber(ARGV[offset + 1])
  local used = tonumber(redis.call('INCR', KEYS[i]))
  if used == 1 then redis.call('EXPIRE', KEYS[i], ttl) end
  local left = limit - used
  if remaining == nil or left < remaining then remaining = left end
  if used > limit then
    allowed = 0
    local key_ttl = tonumber(redis.call('TTL', KEYS[i]))
    if key_ttl > retry_after then retry_after = key_ttl end
  end
end
if remaining == nil or remaining < 0 then remaining = 0 end
if allowed == 0 and retry_after < 1 then retry_after = 1 end
return {allowed, remaining, retry_after}
"""


@dataclass(frozen=True)
class FieldLiveRateDecision:
    allowed: bool
    remaining: int
    retry_after: int
    backend: str


@lru_cache(maxsize=2)
def _redis_client(url: str) -> Any:
    import redis

    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
        health_check_interval=30,
    )


def _subject(organization_id: str, user_id: str) -> str:
    raw = f"{organization_id}:{user_id}"
    return raw.replace(" ", "_").replace("/", "_")[:240]


def _memory_check(subject: str) -> FieldLiveRateDecision:
    now = int(time.time())
    allowed = True
    remaining: int | None = None
    retry_after = 0
    with _MEMORY_LOCK:
        for name, limit, seconds in _WINDOWS:
            window_start = now - (now % seconds)
            reset = window_start + seconds
            key = f"{subject}:{name}:{window_start}"
            used, _ = _MEMORY.get(key, (0, reset))
            used += 1
            _MEMORY[key] = (used, reset)
            left = limit - used
            remaining = left if remaining is None else min(remaining, left)
            if used > limit:
                allowed = False
                retry_after = max(retry_after, reset - now)
        if len(_MEMORY) > 5000:
            expired = [key for key, (_, reset) in _MEMORY.items() if reset <= now]
            for key in expired[:2500]:
                _MEMORY.pop(key, None)
    return FieldLiveRateDecision(allowed, max(0, remaining or 0), max(1, retry_after) if not allowed else 0, "memory")


def check_field_live_analysis_limit(organization_id: str, user_id: str) -> FieldLiveRateDecision:
    subject = _subject(str(organization_id), str(user_id))
    url = str(getattr(settings, "REDIS_URL", "") or "").strip()
    if url:
        now = int(time.time())
        keys: list[str] = []
        args: list[int] = []
        for name, limit, seconds in _WINDOWS:
            window_start = now - (now % seconds)
            keys.append(f"agroai:field-live:v1:{subject}:{name}:{window_start}")
            args.extend([limit, seconds + 5])
        try:
            result = _redis_client(url).eval(_REDIS_SCRIPT, len(keys), *keys, *args)
            return FieldLiveRateDecision(
                allowed=bool(int(result[0])),
                remaining=max(0, int(result[1])),
                retry_after=max(0, int(result[2])),
                backend="redis",
            )
        except Exception:  # noqa: BLE001 - bounded in-process fallback remains protective
            pass
    return _memory_check(subject)
'''
(ROOT / "agroai_api/app/services/field_live_rate_limit.py").write_text(RATE_LIMITER, encoding="utf-8")

ROUTE = "agroai_api/app/api/v1/field_intelligence.py"
replace_once(ROUTE, "from datetime import datetime\n", "from datetime import datetime, timezone\n")
replace_once(ROUTE, "from sqlalchemy.orm import Session\n", "from sqlalchemy.orm import Session\nfrom starlette.concurrency import run_in_threadpool\n")
replace_once(
    ROUTE,
    "from app.services import field_intelligence as svc\n",
    "from app.services import field_intelligence as svc\nfrom app.services.field_live_rate_limit import check_field_live_analysis_limit\nfrom app.services.field_vision import analyze_field_images\n",
)
replace_once(
    ROUTE,
    "class SyncBatchRequest(BaseModel):\n    captures: list[SyncCaptureItem] = Field(min_length=1)\n\n\nPATCH_STATUSES",
    '''class SyncBatchRequest(BaseModel):
    captures: list[SyncCaptureItem] = Field(min_length=1)


_LIVE_FRAME_MAX_BYTES = 1_500_000
_LIVE_FRAME_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _valid_live_frame(payload: bytes, content_type: str) -> bool:
    if content_type == "image/jpeg":
        return payload.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return payload.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"
    return False


@router.post("/live-analysis")
async def live_field_analysis(
    request: Request,
    file: UploadFile = File(...),
    workspace_id: str | None = Form(default=None, max_length=_MAX_NAME),
    field_name: str | None = Form(default=None, max_length=_MAX_NAME),
    crop: str | None = Form(default=None, max_length=_MAX_NAME),
    note_text: str | None = Form(default=None, max_length=1600),
    frame_timestamp_seconds: float | None = Form(default=None, ge=0, le=900),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    """Analyze one sampled video frame without persisting it.

    This is deliberately near-real-time rather than continuous video inference:
    the durable uploaded recording remains the authoritative evidence, while the
    sampled response is preliminary guidance that always requires review.
    """
    organization_id = svc.require_org(ctx)
    if workspace_id:
        svc.authorize_workspace_action(db, ctx, workspace_id)

    decision = check_field_live_analysis_limit(organization_id, ctx.user.id)
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "field_live_analysis_rate_limited",
                "message": "Live analysis is temporarily rate limited. The recording continues and will be fully analyzed after upload.",
            },
            headers={"Retry-After": str(decision.retry_after)},
        )

    declared = (request.headers.get("content-length") or "").strip()
    if declared.isdigit() and int(declared) > _LIVE_FRAME_MAX_BYTES + 100_000:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Live frame exceeds size limit")

    content_type = str(file.content_type or "").lower().split(";")[0].strip()
    if content_type not in _LIVE_FRAME_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported live frame type")
    payload = await file.read(_LIVE_FRAME_MAX_BYTES + 1)
    await file.close()
    if not payload or len(payload) > _LIVE_FRAME_MAX_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Live frame exceeds size limit")
    if not _valid_live_frame(payload, content_type):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Live frame content is invalid")

    context = {
        "field_name": field_name,
        "crop": crop,
        "note_text": note_text,
        "media_kind": "live_video_frame",
        "frame_timestamp_seconds": frame_timestamp_seconds,
    }
    result = await run_in_threadpool(analyze_field_images, [(payload, content_type, context)], context)
    if not result.succeeded:
        return {
            "status": "unavailable",
            "preliminary": True,
            "durable": False,
            "error": result.error or "live_vision_unavailable",
            "retryable": bool(result.retryable),
            "rate_limit_remaining": decision.remaining,
        }
    return {
        "status": "ok",
        "preliminary": True,
        "durable": False,
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "provider": result.provider,
        "model": result.model,
        "analysis": result.analysis,
        "human_review_required": True,
        "rate_limit_remaining": decision.remaining,
    }


PATCH_STATUSES''',
)
replace_once(
    "agroai_api/app/services/field_intelligence_vision_extension.py",
    '''        else:
            observation.status = "needs_review"
            svc._audit(
''',
    '''        else:
            if result.retryable:
                observation.status = "processing"
                raise RuntimeError(f"vision_retryable_failure:{result.error or 'provider'}")
            observation.status = "needs_review"
            svc._audit(
''',
)

EDGE = "cloudflare/edge-gateway/src/edge-main-v3.ts"
replace_once(
    EDGE,
    '''  const image = Array.from(decodeBase64(payload.image));
  const candidates = model === FIELD_VISION_PRIMARY_MODEL
    ? [FIELD_VISION_PRIMARY_MODEL, FIELD_VISION_FALLBACK_MODEL]
    : [model];
  for (const candidate of candidates) {
    try {
      const result = await env.AI.run(candidate, { image, prompt, max_tokens: 1400 });
      return json({
''',
    '''  const imageBytes = Array.from(decodeBase64(payload.image));
  const imageDataUri = `data:${contentType};base64,${payload.image}`;
  const candidates = model === FIELD_VISION_PRIMARY_MODEL
    ? [FIELD_VISION_PRIMARY_MODEL, FIELD_VISION_FALLBACK_MODEL]
    : [model];
  for (const candidate of candidates) {
    try {
      const result = candidate === FIELD_VISION_PRIMARY_MODEL
        ? await env.AI.run(FIELD_VISION_PRIMARY_MODEL, { image: imageDataUri, prompt, max_tokens: 1400, temperature: 0.1 })
        : await env.AI.run(FIELD_VISION_FALLBACK_MODEL, { image: imageBytes, prompt, max_tokens: 1400 });
      return json({
''',
)

CLIENT = "figma-enterprise-v4/src/app/api/client.ts"
replace_once(
    CLIENT,
    '''  } catch (cause) {
    const error = new Error("Backend unavailable. Retry.") as ApiError;
''',
    '''  } catch (cause) {
    if (cause && typeof cause === "object" && "name" in cause && cause.name === "AbortError") throw cause;
    const error = new Error("Backend unavailable. Retry.") as ApiError;
''',
)
replace_once(
    CLIENT,
    '''function uploadFieldAsset<T>(captureId: string, fields: Record<string, string>, file: File): Promise<T> {
  const form = new FormData();
  Object.entries(fields).forEach(([key, value]) => form.append(key, value));
  form.append("file", file);
  return request<T>(`/v1/field-intelligence/captures/${encodeURIComponent(captureId)}/assets`, { method: "POST", body: form });
}
''',
    '''function uploadFieldAsset<T>(captureId: string, fields: Record<string, string>, file: File): Promise<T> {
  const form = new FormData();
  Object.entries(fields).forEach(([key, value]) => form.append(key, value));
  form.append("file", file);
  return request<T>(`/v1/field-intelligence/captures/${encodeURIComponent(captureId)}/assets`, { method: "POST", body: form });
}

function analyzeLiveFieldFrame<T>(fields: Record<string, string>, file: File, signal?: AbortSignal): Promise<T> {
  const form = new FormData();
  Object.entries(fields).forEach(([key, value]) => { if (value) form.append(key, value); });
  form.append("file", file);
  return request<T>("/v1/field-intelligence/live-analysis", { method: "POST", body: form, signal });
}
''',
)
replace_once(
    CLIENT,
    '''    uploadAsset: (captureId: string, fields: Record<string, string>, file: File) => uploadFieldAsset(captureId, fields, file),
''',
    '''    uploadAsset: (captureId: string, fields: Record<string, string>, file: File) => uploadFieldAsset(captureId, fields, file),
    liveAnalyze: (fields: Record<string, string>, file: File, signal?: AbortSignal) => analyzeLiveFieldFrame(fields, file, signal),
''',
)

COMPONENT = "figma-enterprise-v4/src/app/components/FieldIntelligenceV2.tsx"
replace_once(
    COMPONENT,
    "const MAX_RECORDING_SECONDS = 900;\n",
    "const MAX_RECORDING_SECONDS = 900;\nconst LIVE_VISION_INTERVAL_MS = 20_000;\nconst LIVE_VISION_FIRST_SAMPLE_MS = 3_500;\nconst LIVE_VISION_MAX_SIDE = 768;\n",
)
replace_once(
    COMPONENT,
    '''  const [videoElapsed, setVideoElapsed] = useState(0);
  const [liveTranscript, setLiveTranscript] = useState("");
''',
    '''  const [videoElapsed, setVideoElapsed] = useState(0);
  const [liveVision, setLiveVision] = useState<Record<string, any> | null>(null);
  const [liveVisionState, setLiveVisionState] = useState<"idle" | "sampling" | "ready" | "unavailable">("idle");
  const [liveTranscript, setLiveTranscript] = useState("");
''',
)
replace_once(
    COMPONENT,
    '''  const videoTimerRef = useRef<number | null>(null);
  const videoElapsedRef = useRef(0);
''',
    '''  const videoTimerRef = useRef<number | null>(null);
  const videoElapsedRef = useRef(0);
  const liveVisionTimerRef = useRef<number | null>(null);
  const liveVisionFirstTimerRef = useRef<number | null>(null);
  const liveVisionBusyRef = useRef(false);
  const liveVisionAbortRef = useRef<AbortController | null>(null);
  const liveVisionSessionRef = useRef(0);
  const liveTranscriptRef = useRef("");
  const liveVisionContextRef = useRef({ workspaceId: workspaceId as string | undefined, fieldName: "", crop: "", note: "" });
''',
)
replace_once(
    COMPONENT,
    '''  const clearVideoTimer = useCallback(() => {
    if (videoTimerRef.current !== null) window.clearInterval(videoTimerRef.current);
    videoTimerRef.current = null;
  }, []);
''',
    '''  const clearVideoTimer = useCallback(() => {
    if (videoTimerRef.current !== null) window.clearInterval(videoTimerRef.current);
    videoTimerRef.current = null;
  }, []);

  const clearLiveVisionSampling = useCallback(() => {
    liveVisionSessionRef.current += 1;
    if (liveVisionTimerRef.current !== null) window.clearInterval(liveVisionTimerRef.current);
    if (liveVisionFirstTimerRef.current !== null) window.clearTimeout(liveVisionFirstTimerRef.current);
    liveVisionTimerRef.current = null;
    liveVisionFirstTimerRef.current = null;
    liveVisionAbortRef.current?.abort();
    liveVisionAbortRef.current = null;
    liveVisionBusyRef.current = false;
  }, []);
''',
)
replace_once(
    COMPONENT,
    '''  useEffect(() => () => {
    clearTimer();
    clearVideoTimer();
''',
    '''  useEffect(() => {
    liveTranscriptRef.current = `${liveTranscript} ${interimTranscript}`.trim();
  }, [interimTranscript, liveTranscript]);

  useEffect(() => {
    liveVisionContextRef.current = { workspaceId, fieldName, crop, note };
  }, [crop, fieldName, note, workspaceId]);

  useEffect(() => () => {
    clearTimer();
    clearVideoTimer();
    clearLiveVisionSampling();
''',
)
replace_once(
    COMPONENT,
    '''  }, [audioUrl, clearTimer, clearVideoTimer, releaseStream, releaseVideoStream, stopRecognition, walkVideoUrl]);
''',
    '''  }, [audioUrl, clearLiveVisionSampling, clearTimer, clearVideoTimer, releaseStream, releaseVideoStream, stopRecognition, walkVideoUrl]);
''',
)
insert_live_functions = '''

  const captureLiveVisionFrame = useCallback(async () => {
    if (liveVisionBusyRef.current || !navigator.onLine) return;
    const video = videoPreviewRef.current;
    if (!video || video.readyState < 2 || video.videoWidth < 1 || video.videoHeight < 1) return;
    const session = liveVisionSessionRef.current;
    const scale = Math.min(1, LIVE_VISION_MAX_SIDE / Math.max(video.videoWidth, video.videoHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) return;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.68));
    if (!blob || blob.size > 1_500_000 || session !== liveVisionSessionRef.current) return;

    liveVisionBusyRef.current = true;
    setLiveVisionState("sampling");
    const controller = new AbortController();
    liveVisionAbortRef.current = controller;
    const current = liveVisionContextRef.current;
    const spokenContext = [current.note, liveTranscriptRef.current].filter(Boolean).join(" ").slice(0, 1600);
    try {
      const response: any = await apiClient.fieldIntelligence.liveAnalyze({
        workspace_id: current.workspaceId || "",
        field_name: current.fieldName.trim(),
        crop: current.crop.trim(),
        note_text: spokenContext,
        frame_timestamp_seconds: String(videoElapsedRef.current),
      }, new File([blob], `live-field-${Date.now()}.jpg`, { type: "image/jpeg" }), controller.signal);
      if (session !== liveVisionSessionRef.current) return;
      if (response?.status === "ok" && response?.analysis) {
        setLiveVision(response.analysis);
        setLiveVisionState("ready");
      } else {
        setLiveVisionState("unavailable");
      }
    } catch (error: any) {
      if (error?.name !== "AbortError" && session === liveVisionSessionRef.current) setLiveVisionState("unavailable");
    } finally {
      if (session === liveVisionSessionRef.current) {
        liveVisionBusyRef.current = false;
        liveVisionAbortRef.current = null;
      }
    }
  }, []);

  const startLiveVisionSampling = useCallback(() => {
    clearLiveVisionSampling();
    setLiveVision(null);
    setLiveVisionState("sampling");
    liveVisionFirstTimerRef.current = window.setTimeout(() => void captureLiveVisionFrame(), LIVE_VISION_FIRST_SAMPLE_MS);
    liveVisionTimerRef.current = window.setInterval(() => void captureLiveVisionFrame(), LIVE_VISION_INTERVAL_MS);
  }, [captureLiveVisionFrame, clearLiveVisionSampling]);
'''
replace_once(
    COMPONENT,
    '''  }, [captureLocation, clearTimer, releaseStream, setRecordedAudio, startRecognition, stopRecognition, stopRecording, t]);



  const stopWalkVideo''',
    '''  }, [captureLocation, clearTimer, releaseStream, setRecordedAudio, startRecognition, stopRecognition, stopRecording, t]);
''' + insert_live_functions + '''

  const stopWalkVideo''',
)
replace_once(
    COMPONENT,
    '''    if (!recorder || recorder.state === "inactive") {
      clearVideoTimer(); stopRecognition(); releaseVideoStream(); setVideoRecording(false); return;
''',
    '''    clearLiveVisionSampling();
    if (!recorder || recorder.state === "inactive") {
      clearVideoTimer(); stopRecognition(); releaseVideoStream(); setVideoRecording(false); return;
''',
)
replace_once(
    COMPONENT,
    '''  }, [clearVideoTimer, releaseVideoStream, stopRecognition]);

  const startWalkVideo''',
    '''  }, [clearLiveVisionSampling, clearVideoTimer, releaseVideoStream, stopRecognition]);

  const startWalkVideo''',
)
replace_once(
    COMPONENT,
    '''    setLiveTranscript("");
    setInterimTranscript("");
    setRecordedVideo(null);
''',
    '''    setLiveTranscript("");
    setInterimTranscript("");
    liveTranscriptRef.current = "";
    setRecordedVideo(null);
    setLiveVision(null);
    setLiveVisionState("sampling");
''',
)
replace_once(
    COMPONENT,
    '''        clearVideoTimer();
        stopRecognition();
''',
    '''        clearLiveVisionSampling();
        clearVideoTimer();
        stopRecognition();
''',
)
replace_once(
    COMPONENT,
    '''      setVideoElapsed(0);
      videoTimerRef.current = window.setInterval(() => {
''',
    '''      setVideoElapsed(0);
      startLiveVisionSampling();
      videoTimerRef.current = window.setInterval(() => {
''',
)
replace_once(
    COMPONENT,
    '''  }, [captureLocation, clearVideoTimer, releaseVideoStream, setRecordedVideo, startRecognition, stopRecognition, stopWalkVideo, t]);
''',
    '''  }, [captureLocation, clearLiveVisionSampling, clearVideoTimer, releaseVideoStream, setRecordedVideo, startLiveVisionSampling, startRecognition, stopRecognition, stopWalkVideo, t]);
''',
)
replace_once(
    COMPONENT,
    '''    setLiveTranscript(""); setInterimTranscript(""); setReviewing(false); setRecordedAudio(null); setRecordedVideo(null);
    setElapsed(0); setVideoElapsed(0);
  }, [setRecordedAudio, setRecordedVideo]);
''',
    '''    clearLiveVisionSampling();
    liveTranscriptRef.current = "";
    setLiveTranscript(""); setInterimTranscript(""); setReviewing(false); setRecordedAudio(null); setRecordedVideo(null);
    setLiveVision(null); setLiveVisionState("idle"); setElapsed(0); setVideoElapsed(0);
  }, [clearLiveVisionSampling, setRecordedAudio, setRecordedVideo]);
''',
)
replace_once(
    COMPONENT,
    '''        <button type="button" onClick={() => recording ? void stopRecording() : void startRecording()}
          className="inline-flex min-h-[48px] items-center gap-2 rounded-xl px-4 text-[14px] font-semibold text-white"
''',
    '''        <button type="button" disabled={videoRecording} onClick={() => recording ? void stopRecording() : void startRecording()}
          className="inline-flex min-h-[48px] items-center gap-2 rounded-xl px-4 text-[14px] font-semibold text-white disabled:opacity-40"
''',
)
replace_once(
    COMPONENT,
    '''        <div className="flex items-center justify-between bg-[#10231B] px-3 py-2 text-[12px] font-semibold text-white">
          <span>{t("fieldIntel.walkRecording")} {Math.floor(videoElapsed / 60)}:{String(videoElapsed % 60).padStart(2, "0")}</span>
          <span>{location ? t("fieldIntel.locationCaptured") : t("fieldIntel.captureLocation")}</span>
        </div>
      </div>}
''',
    '''        <div className="flex items-center justify-between bg-[#10231B] px-3 py-2 text-[12px] font-semibold text-white">
          <span>{t("fieldIntel.walkRecording")} {Math.floor(videoElapsed / 60)}:{String(videoElapsed % 60).padStart(2, "0")}</span>
          <span>{location ? t("fieldIntel.locationCaptured") : t("fieldIntel.captureLocation")}</span>
        </div>
        <div className="border-t border-white/10 bg-[#F1F8F4] p-3 text-[#10231B]">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#2D6A4F]"><Sparkles className="h-4 w-4" />{t("fieldIntel.liveVisionTitle")}</div>
            <div className="flex items-center gap-1 text-[11px] text-[#65736A]">
              {liveVisionState === "sampling" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {liveVisionState === "sampling" ? t("fieldIntel.liveVisionAnalyzing") : liveVisionState === "unavailable" ? t("fieldIntel.liveVisionUnavailable") : t("fieldIntel.liveVisionPreliminary")}
            </div>
          </div>
          {liveVision?.summary && <p className="mt-2 text-[13px] font-medium leading-5">{liveVision.summary}</p>}
          {Array.isArray(liveVision?.visible_facts) && liveVision.visible_facts.length > 0 && <div className="mt-2 text-[12px]"><span className="font-semibold">{t("fieldIntel.visibleFacts")}:</span> {liveVision.visible_facts.slice(0, 3).map((item: any) => item?.label).filter(Boolean).join(" · ")}</div>}
          {Array.isArray(liveVision?.hypotheses) && liveVision.hypotheses.length > 0 && <div className="mt-1 text-[12px]"><span className="font-semibold">{t("fieldIntel.hypotheses")}:</span> {liveVision.hypotheses.slice(0, 2).map((item: any) => item?.label).filter(Boolean).join(" · ")}</div>}
          <p className="mt-2 text-[11px] leading-4 text-[#65736A]">{t("fieldIntel.liveVisionVerify")}</p>
        </div>
      </div>}
''',
)

I18N = "figma-enterprise-v4/src/app/i18n.ts"
replace_once(
    I18N,
    '''  "fieldIntel.videoDenied": "Camera or microphone permission was denied.",
''',
    '''  "fieldIntel.videoDenied": "Camera or microphone permission was denied.",
  "fieldIntel.liveVisionTitle": "Live field analysis",
  "fieldIntel.liveVisionPreliminary": "Preliminary",
  "fieldIntel.liveVisionAnalyzing": "Analyzing sampled frame",
  "fieldIntel.liveVisionUnavailable": "Live analysis unavailable",
  "fieldIntel.liveVisionVerify": "Sampled visual guidance only. The saved video and transcript are analyzed after upload; confirm diagnoses and any chemical or safety conclusion with records, sensors, or qualified inspection.",
  "fieldIntel.visibleFacts": "Visible facts",
  "fieldIntel.hypotheses": "Possible conditions",
''',
)
replace_once(
    I18N,
    '''  "fieldIntel.videoDenied": "L’autorisation de la caméra ou du microphone a été refusée.",
''',
    '''  "fieldIntel.videoDenied": "L’autorisation de la caméra ou du microphone a été refusée.",
  "fieldIntel.liveVisionTitle": "Analyse terrain en direct",
  "fieldIntel.liveVisionPreliminary": "Préliminaire",
  "fieldIntel.liveVisionAnalyzing": "Analyse de l’image échantillonnée",
  "fieldIntel.liveVisionUnavailable": "Analyse en direct indisponible",
  "fieldIntel.liveVisionVerify": "Indications visuelles échantillonnées uniquement. La vidéo et la transcription enregistrées sont analysées après l’envoi ; confirmez tout diagnostic et toute conclusion chimique ou de sécurité avec des registres, des capteurs ou une inspection qualifiée.",
  "fieldIntel.visibleFacts": "Faits visibles",
  "fieldIntel.hypotheses": "Conditions possibles",
''',
)

TEST = "figma-enterprise-v4/tests/field-intelligence-multimodal-contract.mjs"
replace_once(
    TEST,
    '''assert.match(component, /transcriptPreview/);
''',
    '''assert.match(component, /transcriptPreview/);
assert.match(component, /LIVE_VISION_INTERVAL_MS = 20_000/);
assert.match(component, /captureLiveVisionFrame/);
assert.match(component, /fieldIntelligence\.liveAnalyze/);
assert.match(component, /liveVision\.visible_facts/);
''',
)

BACKEND_TEST = "agroai_api/tests/test_field_intelligence_multimodal_v3.py"
replace_once(
    BACKEND_TEST,
    '''    edge = (ROOT.parent / "cloudflare/edge-gateway/src/edge-main-v3.ts").read_text()
''',
    '''    edge = (ROOT.parent / "cloudflare/edge-gateway/src/edge-main-v3.ts").read_text()
    routes = (ROOT / "app/api/v1/field_intelligence.py").read_text()
    live_limiter = (ROOT / "app/services/field_live_rate_limit.py").read_text()
''',
)
replace_once(
    BACKEND_TEST,
    '''    assert "degraded" in edge
''',
    '''    assert "degraded" in edge
    assert "imageDataUri" in edge
    assert '@router.post("/live-analysis")' in routes
    assert "_LIVE_FRAME_MAX_BYTES = 1_500_000" in routes
    assert "check_field_live_analysis_limit" in routes
    assert '("minute", 4, 60)' in live_limiter
    assert '("hour", 60, 3600)' in live_limiter
    assert "vision_retryable_failure" in extension
''',
)

print("Field Intelligence near-real-time v3 patch applied")
