import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Mic, MicOff, PhoneOff, Radio, Volume2, WifiOff } from "lucide-react";
import {
  AepRealtimeVoiceClient,
  callVoiceTool,
  type VoiceHistoryItem,
  type VoiceState,
  type VoiceSurface,
} from "./realtimeVoiceClient";

type Props = {
  surface: VoiceSurface;
  workspaceId?: string;
  fieldId?: string;
  fieldName?: string;
  crop?: string;
  language?: string;
  history?: VoiceHistoryItem[];
  conversationId?: string;
  onExchange?: (userText: string, assistantText: string, metadata?: Record<string, unknown>) => void | Promise<void>;
  compact?: boolean;
};

const VOICES = [
  { id: "ash", label: "Ash" },
  { id: "alloy", label: "Alloy" },
  { id: "coral", label: "Coral" },
  { id: "sage", label: "Sage" },
  { id: "marin", label: "Marin" },
  { id: "cedar", label: "Cedar" },
] as const;

const DETAIL = [
  { id: "brief", label: "Brief" },
  { id: "normal", label: "Normal" },
  { id: "detailed", label: "Detailed" },
] as const;

const VOICE_KEY = "agroai_voice_preference_v1";
const DETAIL_KEY = "agroai_voice_detail_v1";

function initialStored(key: string, fallback: string) {
  if (typeof window === "undefined") return fallback;
  return window.localStorage.getItem(key) || fallback;
}

function stateLabel(state: VoiceState) {
  if (state === "connecting") return "Connecting";
  if (state === "listening") return "Listening";
  if (state === "thinking") return "Thinking";
  if (state === "speaking") return "Speaking";
  if (state === "error") return "Connection issue";
  return "Ready";
}

export function VoiceCallPanel({
  surface,
  workspaceId,
  fieldId,
  fieldName,
  crop,
  language = "auto",
  history = [],
  conversationId,
  onExchange,
  compact = false,
}: Props) {
  const [state, setState] = useState<VoiceState>("idle");
  const [muted, setMuted] = useState(false);
  const [voice, setVoice] = useState(() => initialStored(VOICE_KEY, "ash"));
  const [detail, setDetail] = useState<"brief" | "normal" | "detailed">(
    () => initialStored(DETAIL_KEY, "normal") as "brief" | "normal" | "detailed",
  );
  const [userTranscript, setUserTranscript] = useState("");
  const [assistantTranscript, setAssistantTranscript] = useState("");
  const [error, setError] = useState("");
  const clientRef = useRef<AepRealtimeVoiceClient | null>(null);
  const onExchangeRef = useRef(onExchange);
  const baseHistoryRef = useRef<VoiceHistoryItem[]>([]);
  const sessionHistoryRef = useRef<VoiceHistoryItem[]>([]);

  onExchangeRef.current = onExchange;

  const active = !["idle", "error"].includes(state);
  const online = typeof navigator === "undefined" ? true : navigator.onLine;
  const title = surface === "field_intelligence" ? "Live AGRO-AI" : "Voice with AGRO-AI";
  const subtitle = surface === "field_intelligence"
    ? "Talk with AGRO-AI while you work. Field capture remains available offline."
    : "Speak naturally. AGRO-AI can reason over the same workspace and conversation.";

  const normalizedHistory = useMemo(
    () => history
      .filter((item) => (item.role === "user" || item.role === "assistant") && String(item.content || "").trim())
      .slice(-12)
      .map((item) => ({ role: item.role, content: String(item.content).slice(0, 2200) })),
    [history],
  );

  useEffect(() => {
    baseHistoryRef.current = normalizedHistory;
  }, [normalizedHistory]);

  useEffect(() => () => {
    clientRef.current?.stop();
    clientRef.current = null;
  }, []);

  function buildCallbacks() {
    return {
      onState: (next: VoiceState) => setState(next),
      onUserTranscript: (text: string, final: boolean) => {
        if (final) {
          setUserTranscript(text);
          setAssistantTranscript("");
        } else if (text.trim()) {
          setUserTranscript((current) => current ? current + text : text);
        }
      },
      onAssistantTranscript: (text: string) => setAssistantTranscript(text),
      onError: (message: string) => setError(message),
      onToolCall: async (call: { name: string; arguments: Record<string, unknown> }) => {
        return callVoiceTool(call, {
          workspaceId,
          fieldId,
          language,
          history: [...baseHistoryRef.current, ...sessionHistoryRef.current].slice(-12),
        });
      },
      onExchange: async (userText: string, assistantText: string) => {
        sessionHistoryRef.current = [
          ...sessionHistoryRef.current,
          { role: "user" as const, content: userText },
          { role: "assistant" as const, content: assistantText },
        ].slice(-12);
        await onExchangeRef.current?.(userText, assistantText, {
          source: "realtime_voice",
          voice,
          response_detail: detail,
          surface,
        });
      },
    };
  }

  async function start() {
    if (active) return;
    setError("");
    setUserTranscript("");
    setAssistantTranscript("");
    setMuted(false);
    sessionHistoryRef.current = [];
    window.localStorage.setItem(VOICE_KEY, voice);
    window.localStorage.setItem(DETAIL_KEY, detail);

    const client = new AepRealtimeVoiceClient(buildCallbacks());
    clientRef.current = client;
    await client.start({
      surface,
      workspaceId,
      fieldId,
      fieldName,
      crop,
      conversationId,
      language,
      voice,
      responseDetail: detail,
      history: normalizedHistory,
    });
  }

  function end() {
    clientRef.current?.stop();
    clientRef.current = null;
    setMuted(false);
    setError("");
    setState("idle");
  }

  function toggleMute() {
    const next = !muted;
    setMuted(next);
    clientRef.current?.mute(next);
  }

  const waveform = (
    <div className="flex h-7 items-center justify-center gap-[3px]" aria-hidden>
      {[0, 1, 2, 3, 4, 5, 6].map((index) => (
        <span
          key={index}
          className={`w-[3px] rounded-full bg-[#7EC99D] ${state === "listening" || state === "speaking" ? "animate-pulse" : ""}`}
          style={{ height: `${10 + ((index * 7) % 16)}px`, animationDelay: `${index * 80}ms` }}
        />
      ))}
    </div>
  );

  if (!active) {
    return (
      <div
        className={`rounded-2xl border border-[#C8D8CE] bg-[#F7FBF8] ${compact ? "p-3" : "p-4"}`}
        data-agroai-voice-surface={surface}
      >
        <div className="flex flex-col gap-3 min-[520px]:flex-row min-[520px]:items-center min-[520px]:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[13px] font-semibold text-[#10231B]">
              <Radio className="h-4 w-4 text-[#2D6A4F]" />
              {title}
            </div>
            {!compact && <p className="mt-1 text-[12px] leading-5 text-[#65736A]">{subtitle}</p>}
            {error && <p className="mt-1 text-[12px] text-[#991B1B]">{error}</p>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={voice}
              onChange={(event) => setVoice(event.target.value)}
              className="h-10 rounded-lg border border-[#D6DDD0] bg-white px-2 text-[12px] font-medium text-[#10231B]"
              aria-label="Voice"
            >
              {VOICES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
            <select
              value={detail}
              onChange={(event) => setDetail(event.target.value as "brief" | "normal" | "detailed")}
              className="h-10 rounded-lg border border-[#D6DDD0] bg-white px-2 text-[12px] font-medium text-[#10231B]"
              aria-label="Spoken response detail"
            >
              {DETAIL.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
            <button
              type="button"
              onClick={() => void start()}
              disabled={!online || state === "connecting"}
              className="inline-flex h-10 items-center gap-2 rounded-lg bg-[#0D2B1E] px-3 text-[12px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {!online ? <WifiOff className="h-4 w-4" /> : state === "connecting" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mic className="h-4 w-4" />}
              {!online ? "Offline" : state === "connecting" ? "Connecting" : "Start voice"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="overflow-hidden rounded-2xl border border-[#315646] bg-[#10231B] text-white shadow-[0_16px_42px_rgba(16,35,27,0.18)]"
      data-agroai-voice-surface={surface}
    >
      <div className="flex flex-col items-center px-4 py-5 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-white/10">
          {state === "thinking"
            ? <Loader2 className="h-5 w-5 animate-spin text-[#A8D6B9]" />
            : state === "speaking"
              ? <Volume2 className="h-5 w-5 text-[#A8D6B9]" />
              : <Mic className="h-5 w-5 text-[#A8D6B9]" />}
        </div>
        <div className="mt-2 text-[15px] font-semibold">{stateLabel(state)}</div>
        <div className="mt-1 text-[11px] text-white/55">{voice} · {language === "auto" ? "Auto language" : language}</div>
        <div className="mt-2">{waveform}</div>
      </div>

      {(userTranscript || assistantTranscript) && (
        <div className="border-t border-white/10 px-4 py-3">
          {userTranscript && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/45">You</div>
              <p className="mt-1 line-clamp-3 text-[12px] leading-5 text-white/75">{userTranscript}</p>
            </div>
          )}
          {assistantTranscript && (
            <div className={userTranscript ? "mt-3" : ""}>
              <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#92C7A9]">AGRO-AI</div>
              <p className="mt-1 line-clamp-4 text-[12px] leading-5 text-white">{assistantTranscript}</p>
            </div>
          )}
        </div>
      )}

      <div className="flex items-center justify-center gap-3 border-t border-white/10 px-4 py-3">
        <button
          type="button"
          onClick={toggleMute}
          className="inline-flex h-10 items-center gap-2 rounded-full border border-white/15 bg-white/5 px-4 text-[12px] font-semibold"
        >
          {muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
          {muted ? "Unmute" : "Mute"}
        </button>
        <button
          type="button"
          onClick={end}
          className="inline-flex h-10 items-center gap-2 rounded-full bg-[#B23B2E] px-4 text-[12px] font-semibold text-white"
        >
          <PhoneOff className="h-4 w-4" />
          End
        </button>
      </div>
    </div>
  );
}
