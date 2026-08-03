from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, *, label: str, flags: int = 0) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one regex match, found {count}")
    return updated


# ---------------------------------------------------------------------------
# Portal: camera-first mobile capture, lifecycle-safe preview, multilingual live
# captions and faster sampled vision.
# ---------------------------------------------------------------------------
component_path = "figma-enterprise-v4/src/app/components/FieldIntelligenceV2.tsx"
component = read(component_path)

component = replace_once(
    component,
    'const LIVE_VISION_INTERVAL_MS = 20_000;\nconst LIVE_VISION_FIRST_SAMPLE_MS = 3_500;\nconst LIVE_VISION_MAX_SIDE = 768;',
    'const LIVE_VISION_INTERVAL_MS = 8_000;\nconst LIVE_VISION_FIRST_SAMPLE_MS = 2_000;\nconst LIVE_VISION_MAX_SIDE = 768;\nconst LIVE_SPEECH_CHUNK_MS = 11_000;\nconst LIVE_SPEECH_RESTART_MS = 250;',
    label="live cadence constants",
)

component = replace_once(
    component,
    '  const { t } = useLocale();',
    '  const { t, effectiveLocale } = useLocale();',
    label="locale hook",
)

component = replace_once(
    component,
    '          workspaceId={workspaceId}\n          onSaved={async (message: string) => {',
    '          workspaceId={workspaceId}\n          language={effectiveLocale}\n          onSaved={async (message: string) => {',
    label="composer language prop",
)

component = replace_once(
    component,
    'function SmartComposer({ t, workspaceId, onSaved }: any) {',
    'function SmartComposer({ t, workspaceId, language, onSaved }: any) {',
    label="composer signature",
)

component = replace_once(
    component,
    '  const [videoRecording, setVideoRecording] = useState(false);\n  const [videoElapsed, setVideoElapsed] = useState(0);',
    '''  const [videoRecording, setVideoRecording] = useState(false);
  const [videoPreparing, setVideoPreparing] = useState(false);
  const [videoPreviewReady, setVideoPreviewReady] = useState(false);
  const [videoPreviewError, setVideoPreviewError] = useState<string | null>(null);
  const [videoElapsed, setVideoElapsed] = useState(0);
  const [liveSpeechState, setLiveSpeechState] = useState<"idle" | "listening" | "transcribing" | "ready" | "unavailable">("idle");''',
    label="video states",
)

component = replace_once(
    component,
    '  const videoPreviewRef = useRef<HTMLVideoElement | null>(null);\n  const videoChunksRef = useRef<Blob[]>([]);',
    '''  const videoPreviewRef = useRef<HTMLVideoElement | null>(null);
  const videoChunksRef = useRef<Blob[]>([]);
  const recognitionShouldRunRef = useRef(false);
  const liveSpeechRecorderRef = useRef<MediaRecorder | null>(null);
  const liveSpeechStreamRef = useRef<MediaStream | null>(null);
  const liveSpeechChunksRef = useRef<Blob[]>([]);
  const liveSpeechTimerRef = useRef<number | null>(null);
  const liveSpeechRestartRef = useRef<number | null>(null);
  const liveSpeechBusyRef = useRef(false);
  const liveSpeechSessionRef = useRef(0);''',
    label="video refs",
)

component = replace_once(
    component,
    '  const liveVisionContextRef = useRef({ workspaceId: workspaceId as string | undefined, fieldName: "", crop: "", note: "" });',
    '  const liveVisionContextRef = useRef({ workspaceId: workspaceId as string | undefined, fieldName: "", crop: "", note: "", language: String(language || "en") });',
    label="live vision context ref",
)

component = replace_once(
    component,
    '''  const stopRecognition = useCallback(() => {
    try { recognitionRef.current?.stop(); } catch { /* already stopped */ }
    recognitionRef.current = null;
    setInterimTranscript("");
  }, []);''',
    '''  const stopRecognition = useCallback(() => {
    recognitionShouldRunRef.current = false;
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    try { recognition?.stop(); } catch { /* already stopped */ }
    setInterimTranscript("");
  }, []);''',
    label="stop recognition",
)

component = replace_once(
    component,
    '''  const releaseVideoStream = useCallback(() => {
    videoStreamRef.current?.getTracks().forEach((track) => track.stop());
    videoStreamRef.current = null;
    if (videoPreviewRef.current) videoPreviewRef.current.srcObject = null;
  }, []);''',
    '''  const releaseVideoStream = useCallback(() => {
    videoStreamRef.current?.getTracks().forEach((track) => track.stop());
    videoStreamRef.current = null;
    if (videoPreviewRef.current) {
      try { videoPreviewRef.current.pause(); } catch { /* no-op */ }
      videoPreviewRef.current.srcObject = null;
    }
    setVideoPreviewReady(false);
  }, []);''',
    label="release video stream",
)

component = replace_once(
    component,
    '''  useEffect(() => {
    liveVisionContextRef.current = { workspaceId, fieldName, crop, note };
  }, [crop, fieldName, note, workspaceId]);''',
    '''  useEffect(() => {
    liveVisionContextRef.current = { workspaceId, fieldName, crop, note, language: String(language || "en") };
  }, [crop, fieldName, language, note, workspaceId]);''',
    label="live context effect",
)

old_recognition = '''  const startRecognition = useCallback(() => {
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
  }, []);'''

new_recognition = '''  const appendTranscriptSegment = useCallback((segment: string) => {
    const clean = String(segment || "").replace(/\\s+/g, " ").trim();
    if (!clean) return;
    setLiveTranscript((current) => {
      const existing = current.replace(/\\s+/g, " ").trim();
      if (!existing) return clean;
      const lowerExisting = existing.toLocaleLowerCase();
      const lowerClean = clean.toLocaleLowerCase();
      if (lowerExisting.endsWith(lowerClean) || lowerExisting.includes(lowerClean)) return existing;
      const tail = existing.split(/\\s+/).slice(-10).join(" ").toLocaleLowerCase();
      if (tail && lowerClean.startsWith(tail)) {
        const tailWords = tail.split(/\\s+/).length;
        return `${existing} ${clean.split(/\\s+/).slice(tailWords).join(" ")}`.trim();
      }
      return `${existing} ${clean}`.trim();
    });
  }, []);

  const startRecognition = useCallback((requestedLanguage?: string) => {
    const Recognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!Recognition) {
      setLiveSpeechState("listening");
      return;
    }
    recognitionShouldRunRef.current = true;
    const launch = () => {
      if (!recognitionShouldRunRef.current || recognitionRef.current) return;
      try {
        const recognition = new Recognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.maxAlternatives = 1;
        recognition.lang = requestedLanguage || document.documentElement.lang || navigator.language || "en-US";
        recognition.onresult = (event: any) => {
          let interim = "";
          let finalText = "";
          for (let index = event.resultIndex; index < event.results.length; index += 1) {
            const text = String(event.results[index][0]?.transcript || "");
            if (event.results[index].isFinal) finalText += text;
            else interim += text;
          }
          if (finalText.trim()) appendTranscriptSegment(finalText);
          setInterimTranscript(interim);
          setLiveSpeechState("ready");
        };
        recognition.onerror = (event: any) => {
          setInterimTranscript("");
          const code = String(event?.error || "");
          if (["not-allowed", "service-not-allowed", "audio-capture"].includes(code)) {
            recognitionShouldRunRef.current = false;
          }
        };
        recognition.onend = () => {
          recognitionRef.current = null;
          setInterimTranscript("");
          if (recognitionShouldRunRef.current) window.setTimeout(launch, 300);
        };
        recognitionRef.current = recognition;
        recognition.start();
        setLiveSpeechState("listening");
      } catch {
        recognitionRef.current = null;
      }
    };
    launch();
  }, [appendTranscriptSegment]);'''

component = replace_once(component, old_recognition, new_recognition, label="recognition lifecycle")

marker = '''  const clearLiveVisionSampling = useCallback(() => {
    liveVisionSessionRef.current += 1;
    if (liveVisionTimerRef.current !== null) window.clearInterval(liveVisionTimerRef.current);
    if (liveVisionFirstTimerRef.current !== null) window.clearTimeout(liveVisionFirstTimerRef.current);
    liveVisionTimerRef.current = null;
    liveVisionFirstTimerRef.current = null;
    liveVisionAbortRef.current?.abort();
    liveVisionAbortRef.current = null;
    liveVisionBusyRef.current = false;
  }, []);'''

speech_helpers = marker + '''

  const stopLiveSpeechSampling = useCallback(() => {
    liveSpeechSessionRef.current += 1;
    if (liveSpeechTimerRef.current !== null) window.clearTimeout(liveSpeechTimerRef.current);
    if (liveSpeechRestartRef.current !== null) window.clearTimeout(liveSpeechRestartRef.current);
    liveSpeechTimerRef.current = null;
    liveSpeechRestartRef.current = null;
    const recorder = liveSpeechRecorderRef.current;
    liveSpeechRecorderRef.current = null;
    try {
      if (recorder && recorder.state !== "inactive") recorder.stop();
    } catch { /* recorder already stopped */ }
    liveSpeechStreamRef.current?.getTracks().forEach((track) => track.stop());
    liveSpeechStreamRef.current = null;
    liveSpeechChunksRef.current = [];
    liveSpeechBusyRef.current = false;
    setLiveSpeechState("idle");
  }, []);

  const startLiveSpeechSampling = useCallback((sourceStream: MediaStream) => {
    stopLiveSpeechSampling();
    const session = liveSpeechSessionRef.current;
    const tracks = sourceStream.getAudioTracks().map((track) => track.clone());
    if (!tracks.length || typeof MediaRecorder === "undefined") {
      setLiveSpeechState("unavailable");
      return;
    }
    const speechStream = new MediaStream(tracks);
    liveSpeechStreamRef.current = speechStream;

    const beginCycle = () => {
      if (session !== liveSpeechSessionRef.current || !speechStream.active) return;
      try {
        const preferred = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"]
          .find((kind) => MediaRecorder.isTypeSupported(kind));
        const recorder = new MediaRecorder(speechStream, preferred ? { mimeType: preferred } : undefined);
        liveSpeechRecorderRef.current = recorder;
        liveSpeechChunksRef.current = [];
        recorder.ondataavailable = (event) => {
          if (event.data.size > 0) liveSpeechChunksRef.current.push(event.data);
        };
        recorder.onstop = () => {
          if (session !== liveSpeechSessionRef.current) return;
          const blob = new Blob(liveSpeechChunksRef.current, { type: recorder.mimeType || "audio/webm" });
          liveSpeechChunksRef.current = [];
          if (blob.size > 0 && navigator.onLine && !liveSpeechBusyRef.current) {
            liveSpeechBusyRef.current = true;
            setLiveSpeechState("transcribing");
            const extension = (recorder.mimeType || "").includes("mp4") ? "m4a" : "webm";
            void apiClient.fieldIntelligence.liveTranscribe(
              { language: String(language || "en") },
              new File([blob], `live-speech-${Date.now()}.${extension}`, { type: blob.type }),
            ).then((response: any) => {
              if (session !== liveSpeechSessionRef.current) return;
              if (response?.status === "ok" && response?.transcript) {
                appendTranscriptSegment(String(response.transcript));
                setLiveSpeechState("ready");
              } else {
                setLiveSpeechState("unavailable");
              }
            }).catch(() => {
              if (session === liveSpeechSessionRef.current) setLiveSpeechState("unavailable");
            }).finally(() => {
              liveSpeechBusyRef.current = false;
            });
          }
          if (session === liveSpeechSessionRef.current) {
            liveSpeechRestartRef.current = window.setTimeout(beginCycle, LIVE_SPEECH_RESTART_MS);
          }
        };
        recorder.start(750);
        setLiveSpeechState("listening");
        liveSpeechTimerRef.current = window.setTimeout(() => {
          try {
            if (recorder.state !== "inactive") recorder.stop();
          } catch { /* recorder already stopped */ }
        }, LIVE_SPEECH_CHUNK_MS);
      } catch {
        setLiveSpeechState("unavailable");
      }
    };
    beginCycle();
  }, [appendTranscriptSegment, language, stopLiveSpeechSampling]);

  const resumeVideoPreview = useCallback(async () => {
    const video = videoPreviewRef.current;
    const stream = videoStreamRef.current;
    if (!video || !stream) return;
    try {
      if (video.srcObject !== stream) video.srcObject = stream;
      await video.play();
      setVideoPreviewReady(true);
      setVideoPreviewError(null);
    } catch {
      setVideoPreviewReady(false);
      setVideoPreviewError(t("fieldIntel.previewTap"));
    }
  }, [t]);

  useEffect(() => {
    if (!(videoPreparing || videoRecording)) return;
    const video = videoPreviewRef.current;
    const stream = videoStreamRef.current;
    if (!video || !stream) return;
    if (video.srcObject !== stream) video.srcObject = stream;
    const ready = () => {
      setVideoPreviewReady(video.videoWidth > 0 && video.videoHeight > 0);
      setVideoPreviewError(null);
    };
    video.addEventListener("loadedmetadata", ready);
    video.addEventListener("playing", ready);
    void video.play().then(ready).catch(() => setVideoPreviewError(t("fieldIntel.previewTap")));
    return () => {
      video.removeEventListener("loadedmetadata", ready);
      video.removeEventListener("playing", ready);
    };
  }, [t, videoPreparing, videoRecording]);'''

component = replace_once(component, marker, speech_helpers, label="speech helpers insertion")

component = replace_once(
    component,
    '''    clearLiveVisionSampling();
    stopRecognition();
    releaseStream();
    releaseVideoStream();''',
    '''    clearLiveVisionSampling();
    stopLiveSpeechSampling();
    stopRecognition();
    releaseStream();
    releaseVideoStream();''',
    label="unmount speech cleanup",
)
component = replace_once(
    component,
    '  }, [audioUrl, clearLiveVisionSampling, clearTimer, clearVideoTimer, releaseStream, releaseVideoStream, stopRecognition, walkVideoUrl]);',
    '  }, [audioUrl, clearLiveVisionSampling, clearTimer, clearVideoTimer, releaseStream, releaseVideoStream, stopLiveSpeechSampling, stopRecognition, walkVideoUrl]);',
    label="cleanup dependencies",
)

component = component.replace('      startRecognition();', '      startRecognition(String(language || "en"));')
if component.count('startRecognition(String(language || "en"));') != 2:
    raise RuntimeError("expected audio and video recognition starts")

component = replace_once(
    component,
    '''  const stopRecording = useCallback(async () => {
    const recorder = recorderRef.current;''',
    '''  const stopRecording = useCallback(async () => {
    const recorder = recorderRef.current;
    stopLiveSpeechSampling();''',
    label="stop audio live speech",
)
component = replace_once(
    component,
    '  }, [clearTimer, releaseStream, stopRecognition]);',
    '  }, [clearTimer, releaseStream, stopLiveSpeechSampling, stopRecognition]);',
    label="stop audio dependencies",
)
component = replace_once(
    component,
    '''      recorder.start(1000);
      startRecognition(String(language || "en"));
      setRecording(true);''',
    '''      recorder.start(750);
      startRecognition(String(language || "en"));
      startLiveSpeechSampling(stream);
      setRecording(true);''',
    label="start audio speech fallback",
)
component = replace_once(
    component,
    '  }, [captureLocation, clearTimer, releaseStream, setRecordedAudio, startRecognition, stopRecognition, stopRecording, t]);',
    '  }, [captureLocation, clearTimer, language, releaseStream, setRecordedAudio, startLiveSpeechSampling, startRecognition, stopRecognition, stopRecording, t]);',
    label="start audio dependencies",
)

component = replace_once(
    component,
    '''        note_text: spokenContext,
        frame_timestamp_seconds: String(videoElapsedRef.current),''',
    '''        note_text: spokenContext,
        language: current.language,
        frame_timestamp_seconds: String(videoElapsedRef.current),''',
    label="live vision language",
)

component = replace_once(
    component,
    '''  const stopWalkVideo = useCallback(async () => {
    const recorder = videoRecorderRef.current;
    clearLiveVisionSampling();''',
    '''  const stopWalkVideo = useCallback(async () => {
    const recorder = videoRecorderRef.current;
    clearLiveVisionSampling();
    stopLiveSpeechSampling();''',
    label="stop walk speech",
)
component = replace_once(
    component,
    '  }, [clearLiveVisionSampling, clearVideoTimer, releaseVideoStream, stopRecognition]);',
    '  }, [clearLiveVisionSampling, clearVideoTimer, releaseVideoStream, stopLiveSpeechSampling, stopRecognition]);',
    label="stop walk dependencies",
)

component = replace_once(
    component,
    '''  const startWalkVideo = useCallback(async () => {
    setMicError(null);
    setReviewing(false);''',
    '''  const startWalkVideo = useCallback(async () => {
    setMicError(null);
    setVideoPreparing(true);
    setVideoPreviewReady(false);
    setVideoPreviewError(null);
    setReviewing(false);''',
    label="start video preparation",
)

component = replace_once(
    component,
    '''      releaseVideoStream();
      videoStreamRef.current = stream;
      if (videoPreviewRef.current) {
        videoPreviewRef.current.srcObject = stream;
        await videoPreviewRef.current.play().catch(() => undefined);
      }
      const preferred = [''',
    '''      releaseVideoStream();
      videoStreamRef.current = stream;
      const preferred = [''',
    label="remove premature preview attach",
)

component = replace_once(
    component,
    '''        releaseVideoStream();
        setVideoRecording(false);
        videoStopWaitersRef.current.splice(0).forEach((resolve) => resolve());''',
    '''        releaseVideoStream();
        setVideoRecording(false);
        setVideoPreparing(false);
        setVideoPreviewError(null);
        videoStopWaitersRef.current.splice(0).forEach((resolve) => resolve());''',
    label="video stop state",
)

component = replace_once(
    component,
    '''      recorder.start(1000);
      startRecognition(String(language || "en"));
      setVideoRecording(true);
      videoElapsedRef.current = 0;''',
    '''      recorder.start(750);
      setVideoRecording(true);
      setVideoPreparing(false);
      startRecognition(String(language || "en"));
      startLiveSpeechSampling(stream);
      videoElapsedRef.current = 0;''',
    label="start smooth video",
)

component = replace_once(
    component,
    '''    } catch (error: any) {
      releaseVideoStream();
      setMicError(error?.name === "NotAllowedError" ? t("fieldIntel.videoDenied") : t("fieldIntel.videoUnsupported"));
    }
  }, [captureLocation, clearLiveVisionSampling, clearVideoTimer, releaseVideoStream, setRecordedVideo, startLiveVisionSampling, startRecognition, stopRecognition, stopWalkVideo, t]);''',
    '''    } catch (error: any) {
      releaseVideoStream();
      setVideoPreparing(false);
      setVideoPreviewReady(false);
      setMicError(error?.name === "NotAllowedError" ? t("fieldIntel.videoDenied") : t("fieldIntel.videoUnsupported"));
    }
  }, [captureLocation, clearLiveVisionSampling, clearVideoTimer, language, releaseVideoStream, setRecordedVideo, startLiveSpeechSampling, startLiveVisionSampling, startRecognition, stopRecognition, stopWalkVideo, t]);''',
    label="start video catch dependencies",
)

component = replace_once(
    component,
    '''    setLiveTranscript(""); setInterimTranscript(""); setReviewing(false); setRecordedAudio(null); setRecordedVideo(null);
    setLiveVision(null); setLiveVisionState("idle"); setElapsed(0); setVideoElapsed(0);''',
    '''    setLiveTranscript(""); setInterimTranscript(""); setReviewing(false); setRecordedAudio(null); setRecordedVideo(null);
    setLiveVision(null); setLiveVisionState("idle"); setLiveSpeechState("idle");
    setVideoPreparing(false); setVideoPreviewReady(false); setVideoPreviewError(null);
    setElapsed(0); setVideoElapsed(0);''',
    label="reset live state",
)

component = replace_once(
    component,
    '      language: document.documentElement.lang || navigator.language || "en",',
    '      language: String(language || document.documentElement.lang || navigator.language || "en"),',
    label="durable language",
)
component = replace_once(
    component,
    '  }, [assignee, attachments, audioFile, blockName, crop, elapsed, eventType, fieldName, liveTranscript, location, note, onSaved, reset, severity, t, walkVideoFile, workspaceId]);',
    '  }, [assignee, attachments, audioFile, blockName, crop, elapsed, eventType, fieldName, language, liveTranscript, location, note, onSaved, reset, severity, t, walkVideoFile, workspaceId]);',
    label="queue language dependency",
)

old_video_ui_pattern = r'''      \{videoRecording && <div className="mt-3 overflow-hidden rounded-xl border border-\[#BFD8C9\] bg-black">.*?      </div>\}
      \{walkVideoUrl && !videoRecording'''

new_video_ui = '''      {(videoPreparing || videoRecording) && <div className="fixed inset-0 z-[80] flex flex-col bg-black md:static md:mt-3 md:overflow-hidden md:rounded-xl md:border md:border-[#BFD8C9]">
        <div className="relative min-h-0 flex-1 overflow-hidden bg-black md:aspect-video md:max-h-[540px]">
          <video
            ref={videoPreviewRef}
            muted
            playsInline
            autoPlay
            onLoadedMetadata={() => void resumeVideoPreview()}
            onPlaying={() => { setVideoPreviewReady(true); setVideoPreviewError(null); }}
            className={`h-full w-full object-cover transition-opacity duration-200 ${videoPreviewReady ? "opacity-100" : "opacity-0"}`}
          />
          {!videoPreviewReady && <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[#07110D] px-6 text-center text-white">
            <Loader2 className="h-8 w-8 animate-spin text-[#92C7A9]" />
            <div className="text-[14px] font-semibold">{t("fieldIntel.cameraStarting")}</div>
            {videoPreviewError && <button type="button" onClick={() => void resumeVideoPreview()} className="rounded-full border border-white/30 bg-white/10 px-4 py-2 text-[12px] font-semibold">{t("fieldIntel.previewTap")}</button>}
          </div>}
          <div className="pointer-events-none absolute inset-x-0 top-0 flex items-center justify-between bg-gradient-to-b from-black/70 to-transparent p-4 text-white">
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-red-500" />
              <span className="text-[12px] font-bold uppercase tracking-[0.14em]">{t("fieldIntel.live")}</span>
            </div>
            <div className="rounded-full bg-black/45 px-3 py-1 text-[12px] font-semibold">
              {Math.floor(videoElapsed / 60)}:{String(videoElapsed % 60).padStart(2, "0")} · {String(language || "en").toUpperCase()}
            </div>
          </div>
          {(liveTranscript || interimTranscript) && <div className="pointer-events-none absolute inset-x-3 bottom-24 rounded-2xl bg-black/65 px-4 py-3 text-center text-[15px] font-medium leading-6 text-white backdrop-blur-sm md:bottom-5">
            {liveTranscript.split(/\\s+/).slice(-28).join(" ")} <span className="text-white/65">{interimTranscript}</span>
          </div>}
          {liveVision?.summary && <div className="pointer-events-none absolute inset-x-3 bottom-3 hidden rounded-2xl border border-white/15 bg-[#10231B]/88 p-3 text-white backdrop-blur-md md:block">
            <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#92C7A9]">{t("fieldIntel.liveVisionTitle")}</div>
            <p className="mt-1 line-clamp-2 text-[12px] leading-5">{liveVision.summary}</p>
          </div>}
        </div>
        <div className="border-t border-white/10 bg-[#10231B] px-4 pb-[max(16px,env(safe-area-inset-bottom))] pt-3 text-white">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#92C7A9]">
                <Sparkles className="h-4 w-4" /> {t("fieldIntel.liveVisionTitle")}
                {liveVisionState === "sampling" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              </div>
              {liveVision?.summary
                ? <p className="mt-1 line-clamp-2 text-[12px] leading-5 text-white/90">{liveVision.summary}</p>
                : <p className="mt-1 text-[12px] text-white/65">{liveVisionState === "unavailable" ? t("fieldIntel.liveVisionUnavailable") : t("fieldIntel.liveVisionAnalyzing")}</p>}
              <div className="mt-1 text-[10px] text-white/50">{t("fieldIntel.transcript")}: {liveSpeechState === "transcribing" ? t("fieldIntel.liveSpeechChecking") : t("fieldIntel.liveSpeechActive")}</div>
            </div>
            <button type="button" onClick={() => void stopWalkVideo()} className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full border-4 border-white bg-red-600 shadow-lg" aria-label={t("fieldIntel.stopWalkVideo")}>
              <Square className="h-5 w-5 fill-current text-white" />
            </button>
          </div>
          {Array.isArray(liveVision?.visible_facts) && liveVision.visible_facts.length > 0 && <div className="mt-2 text-[11px] text-white/80"><span className="font-semibold text-white">{t("fieldIntel.visibleFacts")}:</span> {liveVision.visible_facts.slice(0, 2).map((item: any) => item?.label).filter(Boolean).join(" · ")}</div>}
          {Array.isArray(liveVision?.hypotheses) && liveVision.hypotheses.length > 0 && <div className="mt-1 text-[11px] text-white/70"><span className="font-semibold text-white">{t("fieldIntel.hypotheses")}:</span> {liveVision.hypotheses.slice(0, 2).map((item: any) => item?.label).filter(Boolean).join(" · ")}</div>}
        </div>
      </div>}
      {walkVideoUrl && !videoRecording'''

component = regex_once(
    component,
    old_video_ui_pattern,
    new_video_ui,
    label="camera-first video UI",
    flags=re.S,
)

component = replace_once(
    component,
    '      <button type="button" disabled={recording} onClick={() => videoRecording ? void stopWalkVideo() : void startWalkVideo()}',
    '      <button type="button" disabled={recording || videoPreparing} onClick={() => videoRecording ? void stopWalkVideo() : void startWalkVideo()}',
    label="video button preparing state",
)

write(component_path, component)


# ---------------------------------------------------------------------------
# Portal API client: ephemeral live speech transport.
# ---------------------------------------------------------------------------
client_path = "figma-enterprise-v4/src/app/api/client.ts"
client = read(client_path)
client = replace_once(
    client,
    '''function analyzeLiveFieldFrame<T>(fields: Record<string, string>, file: File, signal?: AbortSignal): Promise<T> {
  const form = new FormData();
  Object.entries(fields).forEach(([key, value]) => { if (value) form.append(key, value); });
  form.append("file", file);
  return request<T>("/v1/field-intelligence/live-analysis", { method: "POST", body: form, signal });
}''',
    '''function analyzeLiveFieldFrame<T>(fields: Record<string, string>, file: File, signal?: AbortSignal): Promise<T> {
  const form = new FormData();
  Object.entries(fields).forEach(([key, value]) => { if (value) form.append(key, value); });
  form.append("file", file);
  return request<T>("/v1/field-intelligence/live-analysis", { method: "POST", body: form, signal });
}

function transcribeLiveFieldSpeech<T>(fields: Record<string, string>, file: File, signal?: AbortSignal): Promise<T> {
  const form = new FormData();
  Object.entries(fields).forEach(([key, value]) => { if (value) form.append(key, value); });
  form.append("file", file);
  return request<T>("/v1/field-intelligence/live-transcription", { method: "POST", body: form, signal });
}''',
    label="live speech client helper",
)
client = replace_once(
    client,
    '    liveAnalyze: (fields: Record<string, string>, file: File, signal?: AbortSignal) => analyzeLiveFieldFrame(fields, file, signal),',
    '    liveAnalyze: (fields: Record<string, string>, file: File, signal?: AbortSignal) => analyzeLiveFieldFrame(fields, file, signal),\n    liveTranscribe: (fields: Record<string, string>, file: File, signal?: AbortSignal) => transcribeLiveFieldSpeech(fields, file, signal),',
    label="live speech API method",
)
write(client_path, client)


# ---------------------------------------------------------------------------
# Backend: separate rate-limit channels and ephemeral live multilingual speech.
# ---------------------------------------------------------------------------
limiter_path = "agroai_api/app/services/field_live_rate_limit.py"
limiter = read(limiter_path)
limiter = replace_once(
    limiter,
    '_WINDOWS = (("minute", 4, 60), ("hour", 60, 3600))',
    '''_CHANNEL_WINDOWS = {
    "vision": (("minute", 8, 60), ("hour", 240, 3600)),
    "speech": (("minute", 6, 60), ("hour", 180, 3600)),
}''',
    label="channel windows",
)
limiter = replace_once(
    limiter,
    'def _memory_check(subject: str) -> FieldLiveRateDecision:\n',
    'def _memory_check(subject: str, windows: tuple[tuple[str, int, int], ...]) -> FieldLiveRateDecision:\n',
    label="memory signature",
)
limiter = replace_once(limiter, '        for name, limit, seconds in _WINDOWS:', '        for name, limit, seconds in windows:', label="memory windows")
limiter = replace_once(
    limiter,
    '''def check_field_live_analysis_limit(organization_id: str, user_id: str) -> FieldLiveRateDecision:
    subject = _subject(str(organization_id), str(user_id))
    url = str(getattr(settings, "REDIS_URL", "") or "").strip()''',
    '''def check_field_live_analysis_limit(
    organization_id: str, user_id: str, *, channel: str = "vision"
) -> FieldLiveRateDecision:
    normalized_channel = channel if channel in _CHANNEL_WINDOWS else "vision"
    windows = _CHANNEL_WINDOWS[normalized_channel]
    subject = f"{normalized_channel}:{_subject(str(organization_id), str(user_id))}"
    url = str(getattr(settings, "REDIS_URL", "") or "").strip()''',
    label="rate limiter signature",
)
limiter = replace_once(limiter, '        for name, limit, seconds in _WINDOWS:', '        for name, limit, seconds in windows:', label="redis windows")
limiter = replace_once(limiter, '    return _memory_check(subject)', '    return _memory_check(subject, windows)', label="memory invocation")
write(limiter_path, limiter)

route_path = "agroai_api/app/api/v1/field_intelligence.py"
routes = read(route_path)
routes = replace_once(
    routes,
    'from app.services.field_live_rate_limit import check_field_live_analysis_limit\nfrom app.services.field_vision import analyze_field_images',
    'from app.services.field_live_rate_limit import check_field_live_analysis_limit\nfrom app.services.field_transcription import transcribe_audio\nfrom app.services.field_vision import analyze_field_images',
    label="transcription import",
)
routes = replace_once(
    routes,
    '_LIVE_FRAME_MAX_BYTES = 1_500_000\n_LIVE_FRAME_TYPES = {"image/jpeg", "image/png", "image/webp"}',
    '''_LIVE_FRAME_MAX_BYTES = 1_500_000
_LIVE_FRAME_TYPES = {"image/jpeg", "image/png", "image/webp"}
_LIVE_AUDIO_MAX_BYTES = 4_000_000
_LIVE_AUDIO_TYPES = {
    "audio/webm", "audio/ogg", "audio/mpeg", "audio/mp4", "audio/wav",
    "audio/x-wav", "audio/flac", "video/webm", "video/mp4",
}
_LANGUAGE_HINT = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")


def _normalized_language(value: str | None) -> str | None:
    candidate = str(value or "").strip()[:16]
    return candidate if candidate and _LANGUAGE_HINT.fullmatch(candidate) else None''',
    label="live audio constants",
)
routes = replace_once(
    routes,
    '    note_text: str | None = Form(default=None, max_length=1600),\n    frame_timestamp_seconds: float | None = Form(default=None, ge=0, le=900),',
    '    note_text: str | None = Form(default=None, max_length=1600),\n    language: str | None = Form(default=None, max_length=16),\n    frame_timestamp_seconds: float | None = Form(default=None, ge=0, le=900),',
    label="live vision language form",
)
routes = replace_once(
    routes,
    '    decision = check_field_live_analysis_limit(organization_id, ctx.user.id)',
    '    decision = check_field_live_analysis_limit(organization_id, ctx.user.id, channel="vision")',
    label="vision rate channel",
)
routes = replace_once(
    routes,
    '''        "note_text": note_text,
        "media_kind": "live_video_frame",''',
    '''        "note_text": note_text,
        "language": _normalized_language(language) or "en",
        "media_kind": "live_video_frame",''',
    label="vision context language",
)

live_transcription_endpoint = r'''

@router.post("/live-transcription")
async def live_field_transcription(
    request: Request,
    file: UploadFile = File(...),
    language: str | None = Form(default=None, max_length=16),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    # Transcribe one short, non-persisted audio segment during recording.
    # Browser speech recognition remains the lowest-latency caption source when
    # available. This endpoint provides a multilingual server fallback and
    # correction lane. The chunk is bounded, processed in memory, and discarded.
    # The durable uploaded recording remains the authoritative evidence.
    organization_id = svc.require_org(ctx)
    decision = check_field_live_analysis_limit(
        organization_id, ctx.user.id, channel="speech"
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "field_live_transcription_rate_limited",
                "message": "Live captions are temporarily rate limited. Recording continues and the full upload will still be transcribed.",
            },
            headers={"Retry-After": str(decision.retry_after)},
        )

    declared = (request.headers.get("content-length") or "").strip()
    if declared.isdigit() and int(declared) > _LIVE_AUDIO_MAX_BYTES + 100_000:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Live speech segment exceeds size limit",
        )
    content_type = str(file.content_type or "").lower().split(";")[0].strip()
    if content_type not in _LIVE_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported live speech media type",
        )
    payload = await file.read(_LIVE_AUDIO_MAX_BYTES + 1)
    await file.close()
    if not payload or len(payload) > _LIVE_AUDIO_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Live speech segment exceeds size limit",
        )

    result = await run_in_threadpool(
        transcribe_audio,
        audio=payload,
        content_type=content_type,
        language=_normalized_language(language),
        note_text=None,
    )
    if not result.succeeded:
        return {
            "status": "unavailable",
            "preliminary": True,
            "durable": False,
            "error": result.error or "live_transcription_unavailable",
            "retryable": bool(result.retryable),
            "language": result.language or _normalized_language(language),
            "rate_limit_remaining": decision.remaining,
        }
    return {
        "status": "ok",
        "preliminary": True,
        "durable": False,
        "transcript": result.transcript,
        "language": result.language or _normalized_language(language),
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "rate_limit_remaining": decision.remaining,
    }
'''

routes = replace_once(
    routes,
    '\n\nPATCH_STATUSES = ("needs_review", "acknowledged", "completed")',
    live_transcription_endpoint + '\n\nPATCH_STATUSES = ("needs_review", "acknowledged", "completed")',
    label="live transcription endpoint",
)
write(route_path, routes)


# ---------------------------------------------------------------------------
# Vision output language: preserve machine-stable keys/enums, localize every
# customer-facing string in live and durable analysis.
# ---------------------------------------------------------------------------
vision_path = "agroai_api/app/services/field_vision.py"
vision = read(vision_path)
vision = replace_once(
    vision,
    '''    media_kind = str(context.get("media_kind") or "photo")[:80]
    frame_time = context.get("frame_timestamp_seconds")''',
    '''    media_kind = str(context.get("media_kind") or "photo")[:80]
    target_language = str(context.get("language") or "en").strip()[:16] or "en"
    frame_time = context.get("frame_timestamp_seconds")''',
    label="vision target language",
)
vision = replace_once(
    vision,
    '''Context: field={field}; crop={crop}; operator_note={note or "none"}{frame_label}.

Return JSON only with this exact shape:''',
    '''Context: field={field}; crop={crop}; operator_note={note or "none"}{frame_label}.
Output language: {target_language}. Write every human-readable string value
(summary, labels, evidence, verification, observations, possible issues,
recommended follow-up, and uncertainties) in that language. Keep JSON keys and
the documented enum values exactly as written so the application contract stays stable.

Return JSON only with this exact shape:''',
    label="vision language prompt",
)
vision = replace_once(
    vision,
    '''        return FieldVisionResult(
            provider="cloudflare_workers_ai", status="completed", model=actual_model,
            latency_ms=latency, analysis=_bounded_analysis(_json_from_text(text)),
        )''',
    '''        analysis = _bounded_analysis(_json_from_text(text))
        analysis["language"] = str(context.get("language") or "en").strip()[:16] or "en"
        return FieldVisionResult(
            provider="cloudflare_workers_ai", status="completed", model=actual_model,
            latency_ms=latency, analysis=analysis,
        )''',
    label="vision response language",
)
vision = replace_once(
    vision,
    '''        "human_review_required": True,
    }''',
    '''        "human_review_required": True,
        "language": str(context.get("language") or "en").strip()[:16] or "en",
    }''',
    label="vision aggregate language",
)
write(vision_path, vision)

extension_path = "agroai_api/app/services/field_intelligence_vision_extension.py"
extension = read(extension_path)
extension = replace_once(
    extension,
    '''    def process_with_vision(db, job, *, heartbeat=None):
        job_input = dict(job.input_json or {})''',
    '''    def process_with_vision(db, job, *, heartbeat=None):
        job_input = dict(job.input_json or {})
        output_language = str(job_input.get("language") or "en").strip()[:16] or "en"''',
    label="durable vision language",
)
extension = replace_once(
    extension,
    '''                "note_text": _source_text(observation, session),
                "media_kind": "mixed_field_evidence",''',
    '''                "note_text": _source_text(observation, session),
                "language": output_language,
                "media_kind": "mixed_field_evidence",''',
    label="durable vision context",
)
extension = replace_once(
    extension,
    '''            model=result.model,
            latency_ms=result.latency_ms,''',
    '''            model=result.model,
            language=output_language,
            latency_ms=result.latency_ms,''',
    label="vision run language",
)
extension = replace_once(
    extension,
    '''            "vision_human_review_required": True,
        })''',
    '''            "vision_human_review_required": True,
            "vision_language": output_language,
        })''',
    label="vision provenance language",
)
write(extension_path, extension)


# ---------------------------------------------------------------------------
# Durable text extraction: language parity is core product behavior. Non-English
# captures may use model extraction even when the optional English fast-path
# entitlement is absent, while preserving deterministic fallback truthfully.
# ---------------------------------------------------------------------------
service_path = "agroai_api/app/services/field_intelligence.py"
service = read(service_path)
service = replace_once(
    service,
    '''    _org = db.get(_Organization, observation.tenant_id)
    _allow_model = bool(_org) and _resolve_ents(db, _org).enabled("field_intelligence.model_extraction")
    extraction = extract_observation(''',
    '''    _org = db.get(_Organization, observation.tenant_id)
    language_family = str(language or "en").split("-", 1)[0].lower()
    # Multilingual parity is part of Field Intelligence itself, not an English-
    # only premium. Non-English captures may use the configured model path even
    # when the optional model-extraction entitlement is absent.
    _allow_model = bool(_org) and (
        _resolve_ents(db, _org).enabled("field_intelligence.model_extraction")
        or language_family != "en"
    )
    extraction = extract_observation(''',
    label="multilingual extraction entitlement",
)
service = replace_once(
    service,
    '''        allow_model=_allow_model,
    )''',
    '''        allow_model=_allow_model,
        output_language=language,
    )''',
    label="extraction output language",
)
service = replace_once(
    service,
    '''        "transcription_status": tr.status,
        "correlation_schema_version": correlation.get("schema_version"),''',
    '''        "transcription_status": tr.status,
        "language": tr.language or language,
        "correlation_schema_version": correlation.get("schema_version"),''',
    label="language provenance",
)
write(service_path, service)

extract_path = "agroai_api/app/services/field_observation_extraction.py"
extract = read(extract_path)
extract = replace_once(
    extract,
    '''def _model_extract(
    text: str,
    *,
    field_hint: str | None,''',
    '''def _model_extract(
    text: str,
    *,
    output_language: str | None,
    field_hint: str | None,''',
    label="model extract language signature",
)
extract = replace_once(
    extract,
    '''        "The observation may be in any language; keep summary in the source language. "
        "NEVER invent numbers, names, fields, times or measurements that are not explicitly in the text. "''',
    '''        f"The observation may be in any language. Write all human-readable output strings in "
        f"{output_language or 'the source language'}, while keeping schema keys and enum values stable. "
        "NEVER invent numbers, names, fields, times or measurements that are not explicitly in the text. "''',
    label="model extraction language prompt",
)
extract = replace_once(
    extract,
    '''    allow_model: bool = True,
) -> FieldObservationExtraction:''',
    '''    allow_model: bool = True,
    output_language: str | None = None,
) -> FieldObservationExtraction:''',
    label="public extraction language signature",
)
extract = replace_once(
    extract,
    '''        result = _model_extract(
            text,
            field_hint=field_hint,''',
    '''        result = _model_extract(
            text,
            output_language=output_language,
            field_hint=field_hint,''',
    label="model extraction language invocation",
)
write(extract_path, extract)


# ---------------------------------------------------------------------------
# Static English/French keys; all other enabled portal locales hydrate the same
# keys through the existing authenticated dynamic catalog.
# ---------------------------------------------------------------------------
i18n_path = "figma-enterprise-v4/src/app/i18n.ts"
i18n = read(i18n_path)
i18n = replace_once(
    i18n,
    '''  "fieldIntel.videoDenied": "Camera or microphone permission was denied.",
  "fieldIntel.liveVisionTitle": "Live field analysis",''',
    '''  "fieldIntel.videoDenied": "Camera or microphone permission was denied.",
  "fieldIntel.cameraStarting": "Starting live camera…",
  "fieldIntel.previewTap": "Tap to resume the camera preview",
  "fieldIntel.live": "Live",
  "fieldIntel.liveSpeechActive": "Live multilingual captions active",
  "fieldIntel.liveSpeechChecking": "Checking captions with server transcription",
  "fieldIntel.liveVisionTitle": "Live field analysis",''',
    label="English live camera keys",
)
i18n = replace_once(
    i18n,
    '''  "fieldIntel.videoDenied": "L’autorisation de la caméra ou du microphone a été refusée.",
  "fieldIntel.liveVisionTitle": "Analyse terrain en direct",''',
    '''  "fieldIntel.videoDenied": "L’autorisation de la caméra ou du microphone a été refusée.",
  "fieldIntel.cameraStarting": "Démarrage de la caméra en direct…",
  "fieldIntel.previewTap": "Touchez pour reprendre l’aperçu de la caméra",
  "fieldIntel.live": "En direct",
  "fieldIntel.liveSpeechActive": "Sous-titres multilingues en direct actifs",
  "fieldIntel.liveSpeechChecking": "Vérification des sous-titres par transcription serveur",
  "fieldIntel.liveVisionTitle": "Analyse terrain en direct",''',
    label="French live camera keys",
)
write(i18n_path, i18n)


# ---------------------------------------------------------------------------
# Contracts: prove lifecycle-safe preview, multilingual propagation, speech
# fallback, channel limits and localized vision.
# ---------------------------------------------------------------------------
portal_contract_path = "figma-enterprise-v4/tests/field-intelligence-multimodal-contract.mjs"
portal_contract = read(portal_contract_path)
portal_contract = replace_once(
    portal_contract,
    'assert.match(component, /LIVE_VISION_INTERVAL_MS = 20_000/);',
    '''assert.match(component, /LIVE_VISION_INTERVAL_MS = 8_000/);
assert.match(component, /LIVE_SPEECH_CHUNK_MS = 11_000/);
assert.match(component, /effectiveLocale/);
assert.match(component, /video\\.srcObject = stream/);
assert.match(component, /videoPreviewReady/);
assert.match(component, /fixed inset-0 z-\\[80\\]/);
assert.match(component, /liveTranscribe/);
assert.match(component, /language: current\\.language/);
assert.match(component, /language: String\\(language/);''',
    label="portal multimodal assertions",
)
client_assert_marker = 'const queue = fs.readFileSync(path.join(root, "src/app/fieldIntelligence/offlineQueue.ts"), "utf8");'
portal_contract = replace_once(
    portal_contract,
    client_assert_marker,
    client_assert_marker + '\nconst client = fs.readFileSync(path.join(root, "src/app/api/client.ts"), "utf8");\nconst locales = JSON.parse(fs.readFileSync(path.resolve(root, "../shared/supported-locales.json"), "utf8"));',
    label="portal client contract inputs",
)
portal_contract = replace_once(
    portal_contract,
    'assert.match(queue, /corrected_transcript: record\\.transcriptPreview/);',
    '''assert.match(queue, /corrected_transcript: record\\.transcriptPreview/);
assert.match(client, /field-intelligence\\/live-transcription/);
assert.ok(locales.enabledUiLocales.length >= 60, "Field Intelligence must follow every enabled portal locale, not a small hardcoded language list");''',
    label="portal speech contract assertions",
)
write(portal_contract_path, portal_contract)

source_test_path = "agroai_api/tests/test_field_intelligence_multimodal_v3.py"
source_test = read(source_test_path)
source_test = replace_once(
    source_test,
    '''    assert '@router.post("/live-analysis")' in routes
    assert "_LIVE_FRAME_MAX_BYTES = 1_500_000" in routes
    assert "check_field_live_analysis_limit" in routes
    assert '("minute", 4, 60)' in live_limiter
    assert '("hour", 60, 3600)' in live_limiter
    assert "vision_retryable_failure" in extension''',
    '''    assert '@router.post("/live-analysis")' in routes
    assert '@router.post("/live-transcription")' in routes
    assert "_LIVE_FRAME_MAX_BYTES = 1_500_000" in routes
    assert "_LIVE_AUDIO_MAX_BYTES = 4_000_000" in routes
    assert "transcribe_audio" in routes
    assert 'channel="vision"' in routes
    assert 'channel="speech"' in routes
    assert '"vision": (("minute", 8, 60), ("hour", 240, 3600))' in live_limiter
    assert '"speech": (("minute", 6, 60), ("hour", 180, 3600))' in live_limiter
    assert "output_language" in extension
    assert "vision_language" in extension
    assert "vision_retryable_failure" in extension''',
    label="backend multimodal assertions",
)
write(source_test_path, source_test)

vision_test_path = "agroai_api/tests/unit/test_field_vision.py"
vision_test = read(vision_test_path)
vision_test += '''


def test_prompt_localizes_human_strings_but_preserves_contract():
    prompt = vision._prompt({
        "field_name": "Talhão Norte",
        "crop": "milho",
        "note_text": "As folhas parecem secas",
        "language": "pt",
    })
    assert "Output language: pt" in prompt
    assert "human-readable string value" in prompt
    assert '"severity": "info|low|medium|high|critical"' in prompt
'''
write(vision_test_path, vision_test)

rate_test_path = "agroai_api/tests/unit/test_field_live_rate_limit_channels.py"
write(rate_test_path, '''from app.services import field_live_rate_limit as limiter


def test_live_rate_limit_channels_are_isolated(monkeypatch):
    monkeypatch.setattr(limiter.settings, "REDIS_URL", "")
    limiter._MEMORY.clear()
    vision = [
        limiter.check_field_live_analysis_limit("org", "user", channel="vision")
        for _ in range(8)
    ]
    assert all(item.allowed for item in vision)
    assert not limiter.check_field_live_analysis_limit("org", "user", channel="vision").allowed

    speech = [
        limiter.check_field_live_analysis_limit("org", "user", channel="speech")
        for _ in range(6)
    ]
    assert all(item.allowed for item in speech)
    assert not limiter.check_field_live_analysis_limit("org", "user", channel="speech").allowed
''')

print("Field Intelligence mobile live v4 patch applied.")
