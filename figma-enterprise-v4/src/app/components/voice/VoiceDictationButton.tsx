import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Mic, Square } from "lucide-react";
import { API_BASE_URL } from "../../api/client";
import { useLocale } from "../../hooks/useLocale";

type Props = {
  disabled?: boolean;
  onTranscript: (text: string) => void;
  className?: string;
};

function accessToken() {
  return window.localStorage.getItem("agroai_access_token") || "";
}

function preferredMimeType() {
  if (typeof MediaRecorder === "undefined") return "";
  return [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
  ].find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

export function openAgroAiVoice(surface: "ask" | "field" = "ask") {
  window.dispatchEvent(new CustomEvent("agroai:voice-open", { detail: { surface } }));
}

export function VoiceDictationButton({ disabled = false, onTranscript, className = "" }: Props) {
  const { normalizedLocale } = useLocale();
  const [phase, setPhase] = useState<"idle" | "recording" | "transcribing" | "error">("idle");
  const [error, setError] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);

  const cleanup = useCallback(() => {
    if (timerRef.current) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
    chunksRef.current = [];
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const transcribe = useCallback(async (blob: Blob, mimeType: string) => {
    setPhase("transcribing");
    setError("");
    try {
      const form = new FormData();
      const extension = mimeType.includes("mp4") ? "m4a" : mimeType.includes("ogg") ? "ogg" : "webm";
      form.append("file", new File([blob], `ask-agro-ai-dictation-${Date.now()}.${extension}`, { type: mimeType || "audio/webm" }));
      if (normalizedLocale) form.append("language", normalizedLocale);
      form.append("surface", "ask");
      const headers = new Headers();
      const token = accessToken();
      if (token) headers.set("Authorization", `Bearer ${token}`);
      const response = await fetch(`${API_BASE_URL}/v1/voice/transcribe`, {
        method: "POST",
        headers,
        body: form,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(String(data?.detail || "Voice dictation is unavailable"));
      const transcript = String(data?.transcript || "").trim();
      if (!transcript) throw new Error("No speech was detected");
      onTranscript(transcript);
      setPhase("idle");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Voice dictation failed");
      setPhase("error");
      window.setTimeout(() => setPhase("idle"), 2600);
    }
  }, [normalizedLocale, onTranscript]);

  const stop = useCallback(() => {
    if (timerRef.current) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    try { recorder.stop(); } catch { cleanup(); setPhase("idle"); }
  }, [cleanup]);

  const start = useCallback(async () => {
    if (disabled || phase === "transcribing") return;
    if (phase === "recording") {
      stop();
      return;
    }
    setError("");
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
        throw new Error("Voice recording is not supported in this browser");
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;
      const mimeType = preferredMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        cleanup();
        if (!blob.size) {
          setPhase("idle");
          return;
        }
        void transcribe(blob, blob.type || "audio/webm");
      };
      recorder.start(500);
      setPhase("recording");
      timerRef.current = window.setTimeout(stop, 45_000);
    } catch (err) {
      cleanup();
      setError(err instanceof Error ? err.message : "Could not access the microphone");
      setPhase("error");
      window.setTimeout(() => setPhase("idle"), 2600);
    }
  }, [cleanup, disabled, phase, stop, transcribe]);

  const title = phase === "recording"
    ? "Stop dictation"
    : phase === "transcribing"
      ? "Transcribing voice"
      : error || "Dictate into Ask AGRO-AI";

  return (
    <button
      type="button"
      onClick={() => void start()}
      disabled={disabled || phase === "transcribing"}
      title={title}
      aria-label={title}
      className={`inline-flex h-[48px] w-[48px] flex-shrink-0 items-center justify-center rounded-lg border transition-colors disabled:opacity-50 ${className}`}
      style={{
        borderColor: phase === "recording" ? "#B23B2E" : "#CAD6CE",
        background: phase === "recording" ? "#FFF1EF" : "#FFFFFF",
        color: phase === "recording" ? "#B23B2E" : "#16533C",
      }}
    >
      {phase === "transcribing"
        ? <Loader2 className="h-[18px] w-[18px] animate-spin" />
        : phase === "recording"
          ? <Square className="h-[16px] w-[16px] fill-current" />
          : <Mic className="h-[18px] w-[18px]" />}
    </button>
  );
}
