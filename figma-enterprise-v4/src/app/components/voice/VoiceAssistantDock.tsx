import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Loader2, Mic, MicOff, PhoneOff, Settings2, ShieldCheck, Volume2, X } from "lucide-react";
import { API_BASE_URL } from "../../api/client";
import { useAuth } from "../../auth/AuthProvider";
import { useLocale } from "../../hooks/useLocale";

type Surface = "ask" | "field";
type VoiceState = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "degraded" | "error";
type VoiceRow = { id: string; role: "user" | "assistant"; content: string; createdAt: number };
type ToolEnvelope = { callId: string; name: string; arguments: Record<string, any> };
type FieldAgentContext = Record<string, any>;
type FieldAgentActionDetail = {
  type: string;
  payload?: Record<string, any>;
  resolve: (value: unknown) => void;
  reject: (reason?: unknown) => void;
};

type Props = {
  surface: Surface;
  onExchange?: (userText: string, assistantText: string) => void | Promise<void>;
};

const VOICES = [
  ["marin", "Marin"], ["cedar", "Cedar"], ["coral", "Coral"], ["ash", "Ash"],
  ["sage", "Sage"], ["nova", "Nova"], ["onyx", "Onyx"], ["verse", "Verse"],
] as const;
const LANGUAGE_KEY = "agroai_voice_language_v1";
const VOICE_KEY = "agroai_voice_voice_v1";
const REASONING_KEY = "agroai_voice_reasoning_v1";

function token() { return window.localStorage.getItem("agroai_access_token") || ""; }
function uid(prefix: string) { return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`; }
function cleanText(value: unknown) { return String(value || "").replace(/\s+/g, " ").trim(); }

async function apiGet(path: string): Promise<any> {
  const headers = new Headers();
  const access = token();
  if (access) headers.set("Authorization", `Bearer ${access}`);
  const response = await fetch(`${API_BASE_URL}${path}`, { headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(String(data?.detail || data?.message || `Voice request failed (${response.status})`));
  return data;
}

async function apiPost(path: string, body: unknown): Promise<any> {
  const headers = new Headers({ "Content-Type": "application/json" });
  const access = token();
  if (access) headers.set("Authorization", `Bearer ${access}`);
  const response = await fetch(`${API_BASE_URL}${path}`, { method: "POST", headers, body: JSON.stringify(body) });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json().catch(() => ({})) : await response.text();
  if (!response.ok) {
    const message = typeof data === "string" ? data : data?.detail || data?.message || `Voice request failed (${response.status})`;
    throw new Error(String(message));
  }
  return data;
}

export function VoiceAssistantDock({ surface, onExchange }: Props) {
  const { currentWorkspace } = useAuth() as any;
  const { normalizedLocale } = useLocale();
  const workspaceId = currentWorkspace?.id as string | undefined;
  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [state, setState] = useState<VoiceState>("idle");
  const [muted, setMuted] = useState(false);
  const [error, setError] = useState("");
  const [rows, setRows] = useState<VoiceRow[]>([]);
  const [interim, setInterim] = useState("");
  const [pendingExecution, setPendingExecution] = useState<ToolEnvelope | null>(null);
  const [voice, setVoice] = useState(() => localStorage.getItem(VOICE_KEY) || "marin");
  const [language, setLanguage] = useState(() => localStorage.getItem(LANGUAGE_KEY) || "auto");
  const [reasoning, setReasoning] = useState(() => localStorage.getItem(REASONING_KEY) || "standard");
  const [transport, setTransport] = useState<"realtime" | "fallback">("realtime");
  const [fallbackRecording, setFallbackRecording] = useState(false);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const rowsRef = useRef<VoiceRow[]>([]);
  const pendingUserRef = useRef("");
  const mountedRef = useRef(true);
  const fallbackRecorderRef = useRef<MediaRecorder | null>(null);
  const fallbackChunksRef = useRef<Blob[]>([]);
  const fallbackTimerRef = useRef<number | null>(null);
  const fieldContextRef = useRef<FieldAgentContext>({});

  useEffect(() => { rowsRef.current = rows; }, [rows]);
  useEffect(() => () => { mountedRef.current = false; }, []);
  useEffect(() => {
    localStorage.setItem(VOICE_KEY, voice);
    localStorage.setItem(LANGUAGE_KEY, language);
    localStorage.setItem(REASONING_KEY, reasoning);
  }, [voice, language, reasoning]);


  useEffect(() => {
    if (surface !== "field") return;
    const onFieldContext = (event: Event) => {
      const detail = (event as CustomEvent<FieldAgentContext>).detail;
      if (detail && typeof detail === "object") fieldContextRef.current = detail;
    };
    window.addEventListener("agroai:field-context", onFieldContext);
    window.dispatchEvent(new CustomEvent("agroai:field-context-request"));
    return () => window.removeEventListener("agroai:field-context", onFieldContext);
  }, [surface]);

  const requestFieldAction = useCallback((type: string, payload: Record<string, any> = {}) => (
    new Promise<unknown>((resolve, reject) => {
      let settled = false;
      const timer = window.setTimeout(() => {
        if (settled) return;
        settled = true;
        reject(new Error("Field Intelligence did not accept the voice action"));
      }, 12_000);
      const finish = (value: unknown, error?: unknown) => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        if (error) reject(error);
        else resolve(value);
      };
      const detail: FieldAgentActionDetail = {
        type,
        payload,
        resolve: (value) => finish(value),
        reject: (reason) => finish(undefined, reason || new Error("Field action failed")),
      };
      window.dispatchEvent(new CustomEvent("agroai:field-agent-action", { detail }));
    })
  ), []);

  const label = useMemo(() => {
    if (state === "connecting") return "Connecting";
    if (state === "thinking") return "Thinking";
    if (state === "speaking") return "Speaking";
    if (state === "degraded") return "Connection unstable";
    if (state === "error") return "Voice unavailable";
    if (state === "listening") return muted ? "Muted" : "Listening";
    if (transport === "fallback" && state === "idle") return "Voice ready";
    return surface === "field" ? "Live AGRO-AI" : "Voice";
  }, [state, muted, surface, transport]);

  const appendRow = useCallback((role: VoiceRow["role"], content: string) => {
    const clean = cleanText(content);
    if (!clean) return;
    setRows((current) => [...current.slice(-39), { id: uid(role), role, content: clean, createdAt: Date.now() }]);
  }, []);

  const sendEvent = useCallback((payload: Record<string, any>) => {
    const dc = dcRef.current;
    if (!dc || dc.readyState !== "open") throw new Error("Voice data channel is not ready");
    dc.send(JSON.stringify(payload));
  }, []);

  const finishTool = useCallback(async (tool: ToolEnvelope, output: unknown) => {
    sendEvent({
      type: "conversation.item.create",
      item: { type: "function_call_output", call_id: tool.callId, output: JSON.stringify(output) },
    });
    sendEvent({ type: "response.create" });
  }, [sendEvent]);

  const runTool = useCallback(async (tool: ToolEnvelope) => {
    if (surface === "field" && tool.name === "get_field_context") {
      setState("thinking");
      await finishTool(tool, {
        status: "ok",
        context: fieldContextRef.current,
        durable: false,
        source: "field_intelligence_browser",
      });
      return;
    }
    if (surface === "field" && tool.name === "update_field_draft") {
      setState("thinking");
      try {
        const output = await requestFieldAction("update_draft", tool.arguments);
        await finishTool(tool, output);
      } catch (err) {
        await finishTool(tool, { status: "error", message: err instanceof Error ? err.message : "Field draft update failed" });
      }
      return;
    }
    if (surface === "field" && tool.name === "capture_field_location") {
      setState("thinking");
      try {
        const output = await requestFieldAction("capture_location", tool.arguments);
        await finishTool(tool, output);
      } catch (err) {
        await finishTool(tool, { status: "error", message: err instanceof Error ? err.message : "Location capture failed" });
      }
      return;
    }
    if (
      tool.name === "execute_aep_action"
      || (surface === "field" && ["save_field_observation", "create_field_task"].includes(tool.name))
    ) {
      setPendingExecution(tool);
      setState("thinking");
      return;
    }
    setState("thinking");
    const history = rowsRef.current.slice(-12).map((row) => ({ role: row.role, content: row.content }));
    try {
      const output = await apiPost("/v1/voice/tool", {
        name: tool.name,
        surface,
        arguments: tool.arguments,
        workspace_id: workspaceId,
        language: language === "auto" ? normalizedLocale || "auto" : language,
        history,
      });
      await finishTool(tool, output);
    } catch (err) {
      await finishTool(tool, { status: "error", message: err instanceof Error ? err.message : "Tool failed" });
    }
  }, [finishTool, language, normalizedLocale, requestFieldAction, surface, workspaceId]);

  const handleEvent = useCallback((raw: string) => {
    let event: any;
    try { event = JSON.parse(raw); } catch { return; }
    const type = String(event?.type || "");

    if (type === "input_audio_buffer.speech_started") {
      setState("listening"); setInterim("");
      return;
    }
    if (type === "input_audio_buffer.speech_stopped") { setState("thinking"); return; }
    if (type === "response.created") { setState("thinking"); return; }
    if (type === "response.output_audio.delta" || type === "response.audio.delta") { setState("speaking"); return; }

    if (type === "conversation.item.input_audio_transcription.delta") {
      setInterim((current) => current + String(event.delta || ""));
      return;
    }
    if (type === "conversation.item.input_audio_transcription.completed") {
      const transcript = cleanText(event.transcript || event.text || interim);
      setInterim("");
      if (transcript) { pendingUserRef.current = transcript; appendRow("user", transcript); }
      return;
    }
    if (type === "response.output_audio_transcript.delta" || type === "response.audio_transcript.delta") {
      setInterim((current) => current + String(event.delta || ""));
      return;
    }
    if (type === "response.output_audio_transcript.done" || type === "response.audio_transcript.done") {
      const transcript = cleanText(event.transcript || event.text || interim);
      setInterim("");
      if (transcript) {
        appendRow("assistant", transcript);
        const userText = pendingUserRef.current;
        pendingUserRef.current = "";
        if (userText && onExchange) Promise.resolve(onExchange(userText, transcript)).catch(() => null);
      }
      setState("listening");
      return;
    }
    if (type === "response.function_call_arguments.done") {
      let args: Record<string, any> = {};
      try { args = JSON.parse(event.arguments || "{}"); } catch { args = {}; }
      void runTool({ callId: String(event.call_id || event.item_id || ""), name: String(event.name || ""), arguments: args });
      return;
    }
    if (type === "error") {
      setError(cleanText(event?.error?.message || event?.message || "Realtime voice error"));
      setState("error");
    }
  }, [appendRow, interim, onExchange, runTool]);

  const disconnect = useCallback(() => {
    try { dcRef.current?.close(); } catch { /* noop */ }
    dcRef.current = null;
    try { pcRef.current?.close(); } catch { /* noop */ }
    pcRef.current = null;
    try {
      if (fallbackRecorderRef.current) {
        fallbackRecorderRef.current.onstop = null;
        if (fallbackRecorderRef.current.state !== "inactive") fallbackRecorderRef.current.stop();
      }
    } catch { /* noop */ }
    fallbackRecorderRef.current = null;
    fallbackChunksRef.current = [];
    if (fallbackTimerRef.current) window.clearTimeout(fallbackTimerRef.current);
    fallbackTimerRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (audioRef.current) { audioRef.current.pause(); audioRef.current.srcObject = null; }
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    setFallbackRecording(false);
    setMuted(false); setPendingExecution(null); setInterim(""); setState("idle");
  }, []);

  useEffect(() => () => disconnect(), [disconnect]);

  const connect = useCallback(async () => {
    if (state !== "idle" && state !== "error" && state !== "degraded") return;
    setError(""); setOpen(true); setState("connecting");
    try {
      const health = await apiGet("/v1/voice/health");
      if (!health?.realtime_enabled) {
        setTransport("fallback");
        setState("idle");
        return;
      }
      setTransport("realtime");
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (!mountedRef.current) { stream.getTracks().forEach((track) => track.stop()); return; }
      streamRef.current = stream;
      const pc = new RTCPeerConnection();
      pcRef.current = pc;
      const remoteAudio = new Audio();
      remoteAudio.autoplay = true;
      audioRef.current = remoteAudio;
      pc.ontrack = (event) => {
        remoteAudio.srcObject = event.streams[0];
        void remoteAudio.play().catch(() => null);
      };
      pc.onconnectionstatechange = () => {
        if (["failed", "disconnected"].includes(pc.connectionState)) setState("degraded");
        if (pc.connectionState === "connected") setState("listening");
      };
      const channel = pc.createDataChannel("oai-events");
      dcRef.current = channel;
      channel.onmessage = (event) => handleEvent(String(event.data || ""));
      channel.onerror = () => { setError("Realtime control channel failed."); setState("degraded"); };
      stream.getAudioTracks().forEach((track) => pc.addTrack(track, stream));

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      const headers = new Headers({ "Content-Type": "application/json" });
      const access = token();
      if (access) headers.set("Authorization", `Bearer ${access}`);
      const response = await fetch(`${API_BASE_URL}/v1/voice/realtime-call`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          sdp: offer.sdp,
          workspace_id: workspaceId,
          surface,
          voice,
          language: language === "auto" ? "auto" : language,
          reasoning_mode: reasoning,
        }),
      });
      const answer = await response.text();
      if (!response.ok) {
        let message = answer;
        try { message = JSON.parse(answer)?.detail || answer; } catch { /* text response */ }
        throw new Error(message || `Realtime session failed (${response.status})`);
      }
      await pc.setRemoteDescription({ type: "answer", sdp: answer });
      setState("listening");
    } catch (err) {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      try { pcRef.current?.close(); } catch { /* noop */ }
      pcRef.current = null;
      setError(err instanceof Error ? err.message : "Could not start realtime voice");
      setState("error");
    }
  }, [handleEvent, language, reasoning, state, surface, voice, workspaceId]);

  const speakFallback = useCallback((text: string) => new Promise<void>((resolve) => {
    if (!("speechSynthesis" in window) || typeof SpeechSynthesisUtterance === "undefined") {
      resolve();
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    const requestedLanguage = language === "auto" ? (normalizedLocale || "en") : language;
    utterance.lang = requestedLanguage;
    const voices = window.speechSynthesis.getVoices();
    const languagePrefix = requestedLanguage.toLowerCase().split("-")[0];
    const matching = voices.find((candidate) => candidate.lang.toLowerCase().startsWith(languagePrefix));
    if (matching) utterance.voice = matching;
    utterance.rate = 1.0;
    utterance.onend = () => resolve();
    utterance.onerror = () => resolve();
    window.speechSynthesis.speak(utterance);
  }), [language, normalizedLocale]);

  const runFallbackTextTurn = useCallback(async (userTextInput: string) => {
    const userText = cleanText(userTextInput);
    if (!userText) {
      setFallbackRecording(false);
      setState("idle");
      return;
    }
    setState("thinking");
    setError("");
    try {
      appendRow("user", userText);
      const requestedLanguage = language === "auto" ? (normalizedLocale || "auto") : language;
      const history = [...rowsRef.current, { id: uid("user"), role: "user" as const, content: userText, createdAt: Date.now() }]
        .slice(-12)
        .map((row) => ({ role: row.role, content: row.content }));
      const result = await apiPost("/v1/voice/tool", {
        name: "ask_agro_ai",
        surface,
        arguments: { question: userText, reasoning_mode: reasoning },
        workspace_id: workspaceId,
        language: requestedLanguage,
        history,
      });
      const assistantText = cleanText(result?.answer || result?.summary);
      if (!assistantText) throw new Error("AGRO-AI did not return a spoken answer");
      appendRow("assistant", assistantText);
      if (onExchange) await onExchange(userText, assistantText);
      setState("speaking");
      await speakFallback(assistantText);
      setState("idle");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Voice conversation failed");
      setState("error");
    } finally {
      setFallbackRecording(false);
      setInterim("");
    }
  }, [appendRow, language, normalizedLocale, onExchange, reasoning, speakFallback, surface, workspaceId]);

  const runFallbackTurn = useCallback(async (blob: Blob, mimeType: string) => {
    setState("thinking");
    setError("");
    try {
      const form = new FormData();
      const extension = mimeType.includes("mp4") ? "m4a" : mimeType.includes("ogg") ? "ogg" : "webm";
      form.append("file", new File([blob], `agro-ai-voice-turn-${Date.now()}.${extension}`, { type: mimeType || "audio/webm" }));
      const requestedLanguage = language === "auto" ? (normalizedLocale || "auto") : language;
      if (requestedLanguage && requestedLanguage !== "auto") form.append("language", requestedLanguage);
      form.append("surface", surface);
      const headers = new Headers();
      const access = token();
      if (access) headers.set("Authorization", `Bearer ${access}`);
      const transcriptionResponse = await fetch(`${API_BASE_URL}/v1/voice/transcribe`, {
        method: "POST", headers, body: form,
      });
      const transcription = await transcriptionResponse.json().catch(() => ({}));
      if (!transcriptionResponse.ok) throw new Error(String(transcription?.detail || "Voice transcription failed"));
      const userText = cleanText(transcription?.transcript);
      if (!userText) throw new Error("No speech was detected");
      await runFallbackTextTurn(userText);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Voice conversation failed");
      setState("error");
    } finally {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      setFallbackRecording(false);
    }
  }, [language, normalizedLocale, runFallbackTextTurn, surface]);

  const stopFallbackRecording = useCallback(() => {
    if (fallbackTimerRef.current) window.clearTimeout(fallbackTimerRef.current);
    fallbackTimerRef.current = null;
    const recorder = fallbackRecorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    try { recorder.stop(); } catch { setFallbackRecording(false); setState("idle"); }
  }, []);

  const startFallbackRecording = useCallback(async () => {
    if (fallbackRecording || state === "thinking" || state === "speaking") return;
    setError("");
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
        throw new Error("Voice recording is not supported in this browser");
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;
      const preferred = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]
        .find((kind) => MediaRecorder.isTypeSupported(kind));
      const recorder = new MediaRecorder(stream, preferred ? { mimeType: preferred } : undefined);
      fallbackRecorderRef.current = recorder;
      fallbackChunksRef.current = [];
      recorder.ondataavailable = (event) => { if (event.data.size > 0) fallbackChunksRef.current.push(event.data); };
      recorder.onstop = () => {
        const blob = new Blob(fallbackChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        fallbackRecorderRef.current = null;
        fallbackChunksRef.current = [];
        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        if (!blob.size) { setFallbackRecording(false); setState("idle"); return; }
        void runFallbackTurn(blob, blob.type || "audio/webm");
      };
      recorder.start(500);
      setFallbackRecording(true);
      setState("listening");
      fallbackTimerRef.current = window.setTimeout(stopFallbackRecording, 60_000);
    } catch (err) {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      setFallbackRecording(false);
      setError(err instanceof Error ? err.message : "Could not access the microphone");
      setState("error");
    }
  }, [fallbackRecording, runFallbackTurn, state, stopFallbackRecording]);

  useEffect(() => {
    const openVoice = (event: Event) => {
      const requested = (event as CustomEvent<{ surface?: Surface }>).detail?.surface;
      if (requested && requested !== surface) return;
      setOpen(true);
      void connect();
    };
    window.addEventListener("agroai:voice-open", openVoice);
    return () => window.removeEventListener("agroai:voice-open", openVoice);
  }, [connect, surface]);

  const toggleMute = useCallback(() => {
    const track = streamRef.current?.getAudioTracks()[0];
    if (!track) return;
    const next = !muted;
    track.enabled = !next;
    setMuted(next);
  }, [muted]);

  const confirmExecution = useCallback(async () => {
    const tool = pendingExecution;
    if (!tool) return;
    setPendingExecution(null); setState("thinking");
    try {
      if (surface === "field" && tool.name === "save_field_observation") {
        const output = await requestFieldAction("save_observation", tool.arguments);
        await finishTool(tool, output);
        return;
      }
      const output = await apiPost("/v1/voice/tool", {
        name: tool.name === "create_field_task" ? "create_field_task" : "execute_aep_action",
        surface,
        arguments: tool.arguments,
        workspace_id: workspaceId,
        language: language === "auto" ? normalizedLocale || "auto" : language,
        history: rowsRef.current.slice(-12).map((row) => ({ role: row.role, content: row.content })),
      });
      await finishTool(tool, output);
    } catch (err) {
      await finishTool(tool, { status: "error", message: err instanceof Error ? err.message : "Execution failed" });
    }
  }, [finishTool, language, normalizedLocale, pendingExecution, requestFieldAction, surface, workspaceId]);

  const cancelExecution = useCallback(async () => {
    const tool = pendingExecution;
    if (!tool) return;
    setPendingExecution(null);
    await finishTool(tool, { status: "cancelled_by_user", executed: false });
  }, [finishTool, pendingExecution]);

  return <>
    {!open && (
      <button type="button" onClick={() => void connect()}
        className="fixed bottom-6 right-6 z-[80] inline-flex min-h-[48px] items-center gap-2 rounded-full bg-[#10231B] px-5 text-[13px] font-semibold text-white shadow-[0_18px_50px_rgba(16,35,27,0.28)] hover:bg-[#17392A]"
        aria-label={surface === "field" ? "Start Live AGRO-AI" : "Start AGRO-AI voice"}>
        <Mic className="h-4 w-4" /> {surface === "field" ? "Live AGRO-AI" : "Voice"}
      </button>
    )}

    {open && (
      <aside className="fixed bottom-5 right-5 z-[90] w-[min(420px,calc(100vw-24px))] overflow-hidden rounded-[22px] border border-[#CAD6CE] bg-[#FFFDF8] shadow-[0_28px_80px_rgba(16,35,27,0.28)]" aria-label="AGRO-AI realtime voice">
        <div className="bg-[#10231B] px-4 py-4 text-white">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#92C7A9]">AGRO-AI realtime</div>
              <div className="mt-1 flex items-center gap-2 text-[17px] font-semibold">
                {state === "connecting" || state === "thinking" ? <Loader2 className="h-4 w-4 animate-spin" /> : state === "speaking" ? <Volume2 className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                {label}
              </div>
              <div className="mt-1 text-[11px] text-[#C8D8CF]">{surface === "field" ? "Field Intelligence · live conversation" : "Ask AGRO-AI · voice + tools"}</div>
            </div>
            <div className="flex gap-1">
              <button type="button" onClick={() => setSettingsOpen((value) => !value)} className="rounded-lg p-2 hover:bg-white/10" aria-label="Voice settings"><Settings2 className="h-4 w-4" /></button>
              <button type="button" onClick={() => { disconnect(); setOpen(false); }} className="rounded-lg p-2 hover:bg-white/10" aria-label="Close voice"><X className="h-4 w-4" /></button>
            </div>
          </div>
        </div>

        {settingsOpen && (
          <div className="grid grid-cols-3 gap-2 border-b border-[#D6DDD0] bg-[#F2F5F0] p-3">
            <label className="text-[10px] font-semibold uppercase tracking-wide text-[#65736A]">Voice
              <select value={voice} onChange={(event) => setVoice(event.target.value)} disabled={state !== "idle" && state !== "error"}
                className="mt-1 w-full rounded-lg border border-[#CBD6CE] bg-white px-2 py-2 text-[12px] font-medium normal-case tracking-normal text-[#10231B]">
                {VOICES.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
              </select>
            </label>
            <label className="text-[10px] font-semibold uppercase tracking-wide text-[#65736A]">Language
              <select value={language} onChange={(event) => setLanguage(event.target.value)}
                className="mt-1 w-full rounded-lg border border-[#CBD6CE] bg-white px-2 py-2 text-[12px] font-medium normal-case tracking-normal text-[#10231B]">
                <option value="auto">Auto</option><option value="en">English</option><option value="fr">Français</option><option value="es">Español</option><option value="pt">Português</option><option value="wo">Wolof</option>
              </select>
            </label>
            <label className="text-[10px] font-semibold uppercase tracking-wide text-[#65736A]">Reasoning
              <select value={reasoning} onChange={(event) => setReasoning(event.target.value)}
                className="mt-1 w-full rounded-lg border border-[#CBD6CE] bg-white px-2 py-2 text-[12px] font-medium normal-case tracking-normal text-[#10231B]">
                <option value="quick">Quick</option><option value="standard">Standard</option><option value="deep">Deep</option>
              </select>
            </label>
          </div>
        )}

        <div className="max-h-[310px] min-h-[170px] overflow-y-auto px-4 py-3">
          {!rows.length && !interim && <div className="flex h-[145px] flex-col items-center justify-center text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[#E7F3EC] text-[#1B5E3F]"><Mic className="h-5 w-5" /></div>
            <div className="mt-3 text-[13px] font-semibold text-[#10231B]">Speak naturally</div>
            <div className="mt-1 max-w-[280px] text-[12px] leading-5 text-[#65736A]">Ask about the operation, field evidence, or request an AEP action. You can interrupt AGRO-AI while it is speaking.</div>
          </div>}
          <div className="space-y-3">
            {rows.slice(-10).map((row) => <div key={row.id} className={row.role === "user" ? "ml-8" : "mr-8"}>
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[#819087]">{row.role === "user" ? "You" : "AGRO-AI"}</div>
              <div className={`rounded-xl px-3 py-2 text-[12px] leading-5 ${row.role === "user" ? "bg-[#10231B] text-white" : "border border-[#D6DDD0] bg-white text-[#263A30]"}`}>{row.content}</div>
            </div>)}
            {interim && <div className="rounded-xl border border-dashed border-[#AFC7B9] bg-[#F3F8F5] px-3 py-2 text-[12px] leading-5 text-[#536158]">{interim}</div>}
          </div>
        </div>

        {pendingExecution && (
          <div className="border-t border-[#E2D6BC] bg-[#FFF8E8] p-3">
            <div className="flex items-start gap-2">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-[#805C13]" />
              <div className="min-w-0 flex-1">
                <div className="text-[12px] font-semibold text-[#5A4314]">{surface === "field" ? "Confirm field action" : "Confirm AEP action"}</div>
                <div className="mt-1 text-[11px] leading-4 text-[#766236]">{cleanText(pendingExecution.arguments.summary) || cleanText(pendingExecution.arguments.title) || cleanText(pendingExecution.arguments.action_type) || pendingExecution.name.replaceAll("_", " ")}</div>
                <div className="mt-2 flex gap-2">
                  <button type="button" onClick={() => void confirmExecution()} className="inline-flex items-center gap-1 rounded-lg bg-[#10231B] px-3 py-1.5 text-[11px] font-semibold text-white"><Check className="h-3.5 w-3.5" /> Confirm</button>
                  <button type="button" onClick={() => void cancelExecution()} className="rounded-lg border border-[#D6C69F] bg-white px-3 py-1.5 text-[11px] font-semibold text-[#5A4314]">Cancel</button>
                </div>
              </div>
            </div>
          </div>
        )}

        {transport === "fallback" && !error && <div className="border-t border-[#D7E3DA] bg-[#F3F8F5] px-4 py-2 text-[11px] leading-4 text-[#536158]">Conversational voice is active in resilient mode. Tap the microphone, speak, then tap stop; AGRO-AI will answer aloud. Premium realtime activates automatically when the realtime provider is configured.</div>}
        {error && <div className="border-t border-[#E6C6C1] bg-[#FFF2EF] px-4 py-2 text-[11px] text-[#A33C2F]">{error}</div>}
        {state === "degraded" && surface === "field" && <div className="border-t border-[#E2D6BC] bg-[#FFF8E8] px-4 py-2 text-[11px] text-[#6B562B]">Connection is unstable. Use Field Capture if you need guaranteed offline recording; existing capture sync remains available.</div>}

        <div className="flex items-center justify-between border-t border-[#D6DDD0] bg-white px-3 py-3">
          <div className="inline-flex items-center gap-1.5 text-[10px] font-medium text-[#65736A]"><ShieldCheck className="h-3.5 w-3.5 text-[#2D6A4F]" /> Tenant-scoped · approvals enforced</div>
          <div className="flex gap-2">
            {transport === "fallback" ? (
              <>
                <button
                  type="button"
                  onClick={() => fallbackRecording ? stopFallbackRecording() : void startFallbackRecording()}
                  disabled={state === "thinking" || state === "speaking"}
                  className={`inline-flex min-h-[38px] items-center gap-2 rounded-full px-4 text-[12px] font-semibold text-white disabled:opacity-50 ${fallbackRecording ? "bg-[#B33D30]" : "bg-[#10231B]"}`}
                >
                  {fallbackRecording ? <PhoneOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                  {fallbackRecording ? "Stop" : state === "thinking" ? "Thinking" : state === "speaking" ? "Speaking" : "Speak"}
                </button>
                <button type="button" onClick={disconnect} className="flex h-9 w-9 items-center justify-center rounded-full border border-[#D6DDD0] bg-white text-[#10231B]" aria-label="End voice session"><X className="h-4 w-4" /></button>
              </>
            ) : (state === "idle" || state === "error" || state === "degraded") ? (
              <button type="button" onClick={() => void connect()} className="inline-flex min-h-[38px] items-center gap-2 rounded-full bg-[#10231B] px-4 text-[12px] font-semibold text-white"><Mic className="h-4 w-4" /> Start</button>
            ) : <>
              <button type="button" onClick={toggleMute} className="flex h-9 w-9 items-center justify-center rounded-full border border-[#D6DDD0] bg-white text-[#10231B]" aria-label={muted ? "Unmute" : "Mute"}>{muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}</button>
              <button type="button" onClick={disconnect} className="flex h-9 w-9 items-center justify-center rounded-full bg-[#B33D30] text-white" aria-label="End voice session"><PhoneOff className="h-4 w-4" /></button>
            </>}
          </div>
        </div>
      </aside>
    )}
  </>;
}
