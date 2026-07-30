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
local now = tonumber(ARGV[1])
local allowed = 1
local remaining = nil
local retry_after = 0
for i = 1, #KEYS do
  local offset = 2 + ((i - 1) * 2)
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
        args: list[int] = [now]
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
replace_once(
    ROUTE,
    "from sqlalchemy.orm import Session\n",
    "from sqlalchemy.orm import Session\nfrom starlette.concurrency import run_in_threadpool\n",
)
replace_once(
    ROUTE,
    "from app.services import field_intelligence as svc\n",
    "from app.services import field_intelligence as svc\n"
    "from app.services.field_live_rate_limit import check_field_live_analysis_limit\n"
    "from app.services.field_vision import analyze_field_images\n",
)
replace_once(
    ROUTE,
    "class SyncBatchRequest(BaseModel):\n    captures: list[SyncCaptureItem] = Field(min_length=1)\n\n\nPATCH_STATUSES",
    '''class SyncBatchRequest(BaseModel):\n    captures: list[SyncCaptureItem] = Field(min_length=1)\n\n\n_LIVE_FRAME_MAX_BYTES = 1_500_000\n_LIVE_FRAME_TYPES = {"image/jpeg", "image/png", "image/webp"}\n\n\ndef _valid_live_frame(payload: bytes, content_type: str) -> bool:\n    if content_type == "image/jpeg":\n        return payload.startswith(b"\\xff\\xd8\\xff")\n    if content_type == "image/png":\n        return payload.startswith(b"\\x89PNG\\r\\n\\x1a\\n")\n    if content_type == "image/webp":\n        return len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"\n    return False\n\n\n@router.post("/live-analysis")\nasync def live_field_analysis(\n    request: Request,\n    file: UploadFile = File(...),\n    workspace_id: str | None = Form(default=None, max_length=_MAX_NAME),\n    field_name: str | None = Form(default=None, max_length=_MAX_NAME),\n    crop: str | None = Form(default=None, max_length=_MAX_NAME),\n    note_text: str | None = Form(default=None, max_length=1600),\n    frame_timestamp_seconds: float | None = Form(default=None, ge=0, le=MAX_RECORDING_SECONDS if "MAX_RECORDING_SECONDS" in globals() else 900),\n    ctx: AuthContext = Depends(get_auth_context),\n    db: Session = Depends(get_db),\n) -> dict:\n    """Analyze one sampled video frame without persisting it.\n\n    This is deliberately near-real-time rather than continuous video inference:\n    the durable uploaded recording remains the authoritative evidence, while the\n    sampled response is preliminary guidance that always requires review.\n    """\n    organization_id = svc.require_org(ctx)\n    if workspace_id:\n        svc.authorize_workspace_action(db, ctx, workspace_id)\n\n    decision = check_field_live_analysis_limit(organization_id, ctx.user.id)\n    if not decision.allowed:\n        raise HTTPException(\n            status_code=status.HTTP_429_TOO_MANY_REQUESTS,\n            detail={\n                "code": "field_live_analysis_rate_limited",\n                "message": "Live analysis is temporarily rate limited. The recording continues and will be fully analyzed after upload.",\n            },\n            headers={"Retry-After": str(decision.retry_after)},\n        )\n\n    declared = (request.headers.get("content-length") or "").strip()\n    if declared.isdigit() and int(declared) > _LIVE_FRAME_MAX_BYTES + 100_000:\n        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Live frame exceeds size limit")\n\n    content_type = str(file.content_type or "").lower().split(";")[0].strip()\n    if content_type not in _LIVE_FRAME_TYPES:\n        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported live frame type")\n    payload = await file.read(_LIVE_FRAME_MAX_BYTES + 1)\n    await file.close()\n    if not payload or len(payload) > _LIVE_FRAME_MAX_BYTES:\n        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Live frame exceeds size limit")\n    if not _valid_live_frame(payload, content_type):\n        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Live frame content is invalid")\n\n    context = {\n        "field_name": field_name,\n        "crop": crop,\n        "note_text": note_text,\n        "media_kind": "live_video_frame",\n        "frame_timestamp_seconds": frame_timestamp_seconds,\n    }\n    result = await run_in_threadpool(analyze_field_images, [(payload, content_type, context)], context)\n    if not result.succeeded:\n        return {\n            "status": "unavailable",\n            "preliminary": True,\n            "durable": False,\n            "error": result.error or "live_vision_unavailable",\n            "retryable": bool(result.retryable),\n            "rate_limit_remaining": decision.remaining,\n        }\n    return {\n        "status": "ok",\n        "preliminary": True,\n        "durable": False,\n        "sampled_at": datetime.now(timezone.utc).isoformat(),\n        "provider": result.provider,\n        "model": result.model,\n        "analysis": result.analysis,\n        "human_review_required": True,\n        "rate_limit_remaining": decision.remaining,\n    }\n\n\nPATCH_STATUSES''',
)
# Keep retryable provider failures durable instead of silently converting them to review-only.
replace_once(
    "agroai_api/app/services/field_intelligence_vision_extension.py",
    '''        else:\n            observation.status = "needs_review"\n            svc._audit(\n''',
    '''        else:\n            if result.retryable:\n                observation.status = "processing"\n                raise RuntimeError(f"vision_retryable_failure:{result.error or 'provider'}")\n            observation.status = "needs_review"\n            svc._audit(\n''',
)

CLIENT = "figma-enterprise-v4/src/app/api/client.ts"
replace_once(
    CLIENT,
    '''  } catch (cause) {\n    const error = new Error("Backend unavailable. Retry.") as ApiError;\n''',
    '''  } catch (cause) {\n    if (cause && typeof cause === "object" && "name" in cause && cause.name === "AbortError") throw cause;\n    const error = new Error("Backend unavailable. Retry.") as ApiError;\n''',
)
replace_once(
    CLIENT,
    '''function uploadFieldAsset<T>(captureId: string, fields: Record<string, string>, file: File): Promise<T> {\n  const form = new FormData();\n  Object.entries(fields).forEach(([key, value]) => form.append(key, value));\n  form.append("file", file);\n  return request<T>(`/v1/field-intelligence/captures/${encodeURIComponent(captureId)}/assets`, { method: "POST", body: form });\n}\n''',
    '''function uploadFieldAsset<T>(captureId: string, fields: Record<string, string>, file: File): Promise<T> {\n  const form = new FormData();\n  Object.entries(fields).forEach(([key, value]) => form.append(key, value));\n  form.append("file", file);\n  return request<T>(`/v1/field-intelligence/captures/${encodeURIComponent(captureId)}/assets`, { method: "POST", body: form });\n}\n\nfunction analyzeLiveFieldFrame<T>(fields: Record<string, string>, file: File, signal?: AbortSignal): Promise<T> {\n  const form = new FormData();\n  Object.entries(fields).forEach(([key, value]) => { if (value) form.append(key, value); });\n  form.append("file", file);\n  return request<T>("/v1/field-intelligence/live-analysis", { method: "POST", body: form, signal });\n}\n''',
)
replace_once(
    CLIENT,
    '''    uploadAsset: (captureId: string, fields: Record<string, string>, file: File) => uploadFieldAsset(captureId, fields, file),\n''',
    '''    uploadAsset: (captureId: string, fields: Record<string, string>, file: File) => uploadFieldAsset(captureId, fields, file),\n    liveAnalyze: (fields: Record<string, string>, file: File, signal?: AbortSignal) => analyzeLiveFieldFrame(fields, file, signal),\n''',
)

COMPONENT = "figma-enterprise-v4/src/app/components/FieldIntelligenceV2.tsx"
replace_once(
    COMPONENT,
    "const MAX_RECORDING_SECONDS = 900;\n",
    "const MAX_RECORDING_SECONDS = 900;\nconst LIVE_VISION_INTERVAL_MS = 20_000;\nconst LIVE_VISION_FIRST_SAMPLE_MS = 3_500;\nconst LIVE_VISION_MAX_SIDE = 768;\n",
)
replace_once(
    COMPONENT,
    '''  const [videoElapsed, setVideoElapsed] = useState(0);\n  const [liveTranscript, setLiveTranscript] = useState("");\n''',
    '''  const [videoElapsed, setVideoElapsed] = useState(0);\n  const [liveVision, setLiveVision] = useState<Record<string, any> | null>(null);\n  const [liveVisionState, setLiveVisionState] = useState<"idle" | "sampling" | "ready" | "unavailable">("idle");\n  const [liveTranscript, setLiveTranscript] = useState("");\n''',
)
replace_once(
    COMPONENT,
    '''  const videoTimerRef = useRef<number | null>(null);\n  const videoElapsedRef = useRef(0);\n''',
    '''  const videoTimerRef = useRef<number | null>(null);\n  const videoElapsedRef = useRef(0);\n  const liveVisionTimerRef = useRef<number | null>(null);\n  const liveVisionFirstTimerRef = useRef<number | null>(null);\n  const liveVisionBusyRef = useRef(false);\n  const liveVisionAbortRef = useRef<AbortController | null>(null);\n  const liveVisionSessionRef = useRef(0);\n  const liveTranscriptRef = useRef("");\n  const liveVisionContextRef = useRef({ workspaceId: workspaceId as string | undefined, fieldName: "", crop: "", note: "" });\n''',
)
replace_once(
    COMPONENT,
    '''  const clearVideoTimer = useCallback(() => {\n    if (videoTimerRef.current !== null) window.clearInterval(videoTimerRef.current);\n    videoTimerRef.current = null;\n  }, []);\n''',
    '''  const clearVideoTimer = useCallback(() => {\n    if (videoTimerRef.current !== null) window.clearInterval(videoTimerRef.current);\n    videoTimerRef.current = null;\n  }, []);\n\n  const clearLiveVisionSampling = useCallback(() => {\n    liveVisionSessionRef.current += 1;\n    if (liveVisionTimerRef.current !== null) window.clearInterval(liveVisionTimerRef.current);\n    if (liveVisionFirstTimerRef.current !== null) window.clearTimeout(liveVisionFirstTimerRef.current);\n    liveVisionTimerRef.current = null;\n    liveVisionFirstTimerRef.current = null;\n    liveVisionAbortRef.current?.abort();\n    liveVisionAbortRef.current = null;\n    liveVisionBusyRef.current = false;\n  }, []);\n''',
)
replace_once(
    COMPONENT,
    '''  useEffect(() => () => {\n    clearTimer();\n    clearVideoTimer();\n''',
    '''  useEffect(() => {\n    liveTranscriptRef.current = `${liveTranscript} ${interimTranscript}`.trim();\n  }, [interimTranscript, liveTranscript]);\n\n  useEffect(() => {\n    liveVisionContextRef.current = { workspaceId, fieldName, crop, note };\n  }, [crop, fieldName, note, workspaceId]);\n\n  useEffect(() => () => {\n    clearTimer();\n    clearVideoTimer();\n    clearLiveVisionSampling();\n''',
)
replace_once(
    COMPONENT,
    '''  }, [audioUrl, clearTimer, clearVideoTimer, releaseStream, releaseVideoStream, stopRecognition, walkVideoUrl]);\n''',
    '''  }, [audioUrl, clearLiveVisionSampling, clearTimer, clearVideoTimer, releaseStream, releaseVideoStream, stopRecognition, walkVideoUrl]);\n''',
)
insert_live_functions = '''\n\n  const captureLiveVisionFrame = useCallback(async () => {\n    if (liveVisionBusyRef.current || !navigator.onLine) return;\n    const video = videoPreviewRef.current;\n    if (!video || video.readyState < 2 || video.videoWidth < 1 || video.videoHeight < 1) return;\n    const session = liveVisionSessionRef.current;\n    const scale = Math.min(1, LIVE_VISION_MAX_SIDE / Math.max(video.videoWidth, video.videoHeight));\n    const canvas = document.createElement("canvas");\n    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));\n    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));\n    const context = canvas.getContext("2d", { alpha: false });\n    if (!context) return;\n    context.drawImage(video, 0, 0, canvas.width, canvas.height);\n    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.68));\n    if (!blob || blob.size > 1_500_000 || session !== liveVisionSessionRef.current) return;\n\n    liveVisionBusyRef.current = true;\n    setLiveVisionState("sampling");\n    const controller = new AbortController();\n    liveVisionAbortRef.current = controller;\n    const current = liveVisionContextRef.current;\n    const spokenContext = [current.note, liveTranscriptRef.current].filter(Boolean).join(" ").slice(0, 1600);\n    try {\n      const response: any = await apiClient.fieldIntelligence.liveAnalyze({\n        workspace_id: current.workspaceId || "",\n        field_name: current.fieldName.trim(),\n        crop: current.crop.trim(),\n        note_text: spokenContext,\n        frame_timestamp_seconds: String(videoElapsedRef.current),\n      }, new File([blob], `live-field-${Date.now()}.jpg`, { type: "image/jpeg" }), controller.signal);\n      if (session !== liveVisionSessionRef.current) return;\n      if (response?.status === "ok" && response?.analysis) {\n        setLiveVision(response.analysis);\n        setLiveVisionState("ready");\n      } else {\n        setLiveVisionState("unavailable");\n      }\n    } catch (error: any) {\n      if (error?.name !== "AbortError" && session === liveVisionSessionRef.current) setLiveVisionState("unavailable");\n    } finally {\n      if (session === liveVisionSessionRef.current) {\n        liveVisionBusyRef.current = false;\n        liveVisionAbortRef.current = null;\n      }\n    }\n  }, []);\n\n  const startLiveVisionSampling = useCallback(() => {\n    clearLiveVisionSampling();\n    setLiveVision(null);\n    setLiveVisionState("sampling");\n    liveVisionFirstTimerRef.current = window.setTimeout(() => void captureLiveVisionFrame(), LIVE_VISION_FIRST_SAMPLE_MS);\n    liveVisionTimerRef.current = window.setInterval(() => void captureLiveVisionFrame(), LIVE_VISION_INTERVAL_MS);\n  }, [captureLiveVisionFrame, clearLiveVisionSampling]);\n'''
replace_once(
    COMPONENT,
    '''  }, [captureLocation, clearTimer, releaseStream, setRecordedAudio, startRecognition, stopRecognition, stopRecording, t]);\n\n\n\n  const stopWalkVideo''',
    '''  }, [captureLocation, clearTimer, releaseStream, setRecordedAudio, startRecognition, stopRecognition, stopRecording, t]);\n''' + insert_live_functions + '''\n\n  const stopWalkVideo''',
)
replace_once(
    COMPONENT,
    '''    if (!recorder || recorder.state === "inactive") {\n      clearVideoTimer(); stopRecognition(); releaseVideoStream(); setVideoRecording(false); return;\n''',
    '''    clearLiveVisionSampling();\n    if (!recorder || recorder.state === "inactive") {\n      clearVideoTimer(); stopRecognition(); releaseVideoStream(); setVideoRecording(false); return;\n''',
)
replace_once(
    COMPONENT,
    '''  }, [clearVideoTimer, releaseVideoStream, stopRecognition]);\n\n  const startWalkVideo''',
    '''  }, [clearLiveVisionSampling, clearVideoTimer, releaseVideoStream, stopRecognition]);\n\n  const startWalkVideo''',
)
replace_once(
    COMPONENT,
    '''    setLiveTranscript("");\n    setInterimTranscript("");\n    setRecordedVideo(null);\n''',
    '''    setLiveTranscript("");\n    setInterimTranscript("");\n    liveTranscriptRef.current = "";\n    setRecordedVideo(null);\n    setLiveVision(null);\n    setLiveVisionState("sampling");\n''',
)
replace_once(
    COMPONENT,
    '''        clearVideoTimer();\n        stopRecognition();\n''',
    '''        clearLiveVisionSampling();\n        clearVideoTimer();\n        stopRecognition();\n''',
)
replace_once(
    COMPONENT,
    '''      setVideoElapsed(0);\n      videoTimerRef.current = window.setInterval(() => {\n''',
    '''      setVideoElapsed(0);\n      startLiveVisionSampling();\n      videoTimerRef.current = window.setInterval(() => {\n''',
)
replace_once(
    COMPONENT,
    '''  }, [captureLocation, clearVideoTimer, releaseVideoStream, setRecordedVideo, startRecognition, stopRecognition, stopWalkVideo, t]);\n''',
    '''  }, [captureLocation, clearLiveVisionSampling, clearVideoTimer, releaseVideoStream, setRecordedVideo, startLiveVisionSampling, startRecognition, stopRecognition, stopWalkVideo, t]);\n''',
)
replace_once(
    COMPONENT,
    '''    setLiveTranscript(""); setInterimTranscript(""); setReviewing(false); setRecordedAudio(null); setRecordedVideo(null);\n    setElapsed(0); setVideoElapsed(0);\n  }, [setRecordedAudio, setRecordedVideo]);\n''',
    '''    clearLiveVisionSampling();\n    liveTranscriptRef.current = "";\n    setLiveTranscript(""); setInterimTranscript(""); setReviewing(false); setRecordedAudio(null); setRecordedVideo(null);\n    setLiveVision(null); setLiveVisionState("idle"); setElapsed(0); setVideoElapsed(0);\n  }, [clearLiveVisionSampling, setRecordedAudio, setRecordedVideo]);\n''',
)
replace_once(
    COMPONENT,
    '''        <button type="button" onClick={() => recording ? void stopRecording() : void startRecording()}\n          className="inline-flex min-h-[48px] items-center gap-2 rounded-xl px-4 text-[14px] font-semibold text-white"\n''',
    '''        <button type="button" disabled={videoRecording} onClick={() => recording ? void stopRecording() : void startRecording()}\n          className="inline-flex min-h-[48px] items-center gap-2 rounded-xl px-4 text-[14px] font-semibold text-white disabled:opacity-40"\n''',
)
replace_once(
    COMPONENT,
    '''        <div className="flex items-center justify-between bg-[#10231B] px-3 py-2 text-[12px] font-semibold text-white">\n          <span>{t("fieldIntel.walkRecording")} {Math.floor(videoElapsed / 60)}:{String(videoElapsed % 60).padStart(2, "0")}</span>\n          <span>{location ? t("fieldIntel.locationCaptured") : t("fieldIntel.captureLocation")}</span>\n        </div>\n      </div>}\n''',
    '''        <div className="flex items-center justify-between bg-[#10231B] px-3 py-2 text-[12px] font-semibold text-white">\n          <span>{t("fieldIntel.walkRecording")} {Math.floor(videoElapsed / 60)}:{String(videoElapsed % 60).padStart(2, "0")}</span>\n          <span>{location ? t("fieldIntel.locationCaptured") : t("fieldIntel.captureLocation")}</span>\n        </div>\n        <div className="border-t border-white/10 bg-[#F1F8F4] p-3 text-[#10231B]">\n          <div className="flex items-center justify-between gap-3">\n            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#2D6A4F]"><Sparkles className="h-4 w-4" />{t("fieldIntel.liveVisionTitle")}</div>\n            <div className="flex items-center gap-1 text-[11px] text-[#65736A]">\n              {liveVisionState === "sampling" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}\n              {liveVisionState === "sampling" ? t("fieldIntel.liveVisionAnalyzing") : liveVisionState === "unavailable" ? t("fieldIntel.liveVisionUnavailable") : t("fieldIntel.liveVisionPreliminary")}\n            </div>\n          </div>\n          {liveVision?.summary && <p className="mt-2 text-[13px] font-medium leading-5">{liveVision.summary}</p>}\n          {Array.isArray(liveVision?.visible_facts) && liveVision.visible_facts.length > 0 && <div className="mt-2 text-[12px]"><span className="font-semibold">{t("fieldIntel.visibleFacts")}:</span> {liveVision.visible_facts.slice(0, 3).map((item: any) => item?.label).filter(Boolean).join(" · ")}</div>}\n          {Array.isArray(liveVision?.hypotheses) && liveVision.hypotheses.length > 0 && <div className="mt-1 text-[12px]"><span className="font-semibold">{t("fieldIntel.hypotheses")}:</span> {liveVision.hypotheses.slice(0, 2).map((item: any) => item?.label).filter(Boolean).join(" · ")}</div>}\n          <p className="mt-2 text-[11px] leading-4 text-[#65736A]">{t("fieldIntel.liveVisionVerify")}</p>\n        </div>\n      </div>}\n''',
)

I18N = "figma-enterprise-v4/src/app/i18n.ts"
replace_once(
    I18N,
    '''  "fieldIntel.videoDenied": "Camera or microphone permission was denied.",\n''',
    '''  "fieldIntel.videoDenied": "Camera or microphone permission was denied.",\n  "fieldIntel.liveVisionTitle": "Live field analysis",\n  "fieldIntel.liveVisionPreliminary": "Preliminary",\n  "fieldIntel.liveVisionAnalyzing": "Analyzing sampled frame",\n  "fieldIntel.liveVisionUnavailable": "Live analysis unavailable",\n  "fieldIntel.liveVisionVerify": "Sampled visual guidance only. The saved video and transcript are analyzed after upload; confirm diagnoses and any chemical or safety conclusion with records, sensors, or qualified inspection.",\n  "fieldIntel.visibleFacts": "Visible facts",\n  "fieldIntel.hypotheses": "Possible conditions",\n''',
)
replace_once(
    I18N,
    '''  "fieldIntel.videoDenied": "L’autorisation de la caméra ou du microphone a été refusée.",\n''',
    '''  "fieldIntel.videoDenied": "L’autorisation de la caméra ou du microphone a été refusée.",\n  "fieldIntel.liveVisionTitle": "Analyse terrain en direct",\n  "fieldIntel.liveVisionPreliminary": "Préliminaire",\n  "fieldIntel.liveVisionAnalyzing": "Analyse de l’image échantillonnée",\n  "fieldIntel.liveVisionUnavailable": "Analyse en direct indisponible",\n  "fieldIntel.liveVisionVerify": "Indications visuelles échantillonnées uniquement. La vidéo et la transcription enregistrées sont analysées après l’envoi ; confirmez tout diagnostic et toute conclusion chimique ou de sécurité avec des registres, des capteurs ou une inspection qualifiée.",\n  "fieldIntel.visibleFacts": "Faits visibles",\n  "fieldIntel.hypotheses": "Conditions possibles",\n''',
)

TEST = "figma-enterprise-v4/tests/field-intelligence-multimodal-contract.mjs"
replace_once(
    TEST,
    '''assert.match(component, /transcriptPreview/);\n''',
    '''assert.match(component, /transcriptPreview/);\nassert.match(component, /LIVE_VISION_INTERVAL_MS = 20_000/);\nassert.match(component, /captureLiveVisionFrame/);\nassert.match(component, /fieldIntelligence\.liveAnalyze/);\nassert.match(component, /liveVision\.visible_facts/);\n''',
)

BACKEND_TEST = "agroai_api/tests/test_field_intelligence_multimodal_v3.py"
replace_once(
    BACKEND_TEST,
    '''    edge = (ROOT.parent / "cloudflare/edge-gateway/src/edge-main-v3.ts").read_text()\n''',
    '''    edge = (ROOT.parent / "cloudflare/edge-gateway/src/edge-main-v3.ts").read_text()\n    routes = (ROOT / "app/api/v1/field_intelligence.py").read_text()\n    live_limiter = (ROOT / "app/services/field_live_rate_limit.py").read_text()\n''',
)
replace_once(
    BACKEND_TEST,
    '''    assert "degraded" in edge\n''',
    '''    assert "degraded" in edge\n    assert '@router.post("/live-analysis")' in routes\n    assert "_LIVE_FRAME_MAX_BYTES = 1_500_000" in routes\n    assert "check_field_live_analysis_limit" in routes\n    assert '("minute", 4, 60)' in live_limiter\n    assert '("hour", 60, 3600)' in live_limiter\n    assert "vision_retryable_failure" in extension\n''',
)

print("Field Intelligence near-real-time v3 patch applied")
