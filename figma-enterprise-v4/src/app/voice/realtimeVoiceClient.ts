import { API_BASE_URL } from "../api/client";

export type VoiceSurface = "ask_agro_ai" | "field_intelligence";
export type VoiceState = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "error";

export type VoiceHistoryItem = { role: "user" | "assistant"; content: string };

export type RealtimeVoiceOptions = {
  surface: VoiceSurface;
  workspaceId?: string;
  fieldId?: string;
  fieldName?: string;
  crop?: string;
  conversationId?: string;
  language?: string;
  voice?: string;
  responseDetail?: "brief" | "normal" | "detailed";
  history?: VoiceHistoryItem[];
};

export type VoiceToolCall = {
  name: string;
  arguments: Record<string, unknown>;
};

export type RealtimeVoiceCallbacks = {
  onState?: (state: VoiceState) => void;
  onUserTranscript?: (text: string, final: boolean) => void;
  onAssistantTranscript?: (text: string, final: boolean) => void;
  onExchange?: (userText: string, assistantText: string) => void | Promise<void>;
  onToolCall?: (call: VoiceToolCall) => Promise<unknown>;
  onError?: (message: string) => void;
};

function accessToken() {
  return window.localStorage.getItem("agroai_access_token") || "";
}

async function waitForIceGathering(pc: RTCPeerConnection, timeoutMs = 4500) {
  if (pc.iceGatheringState === "complete") return;
  await new Promise<void>((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      pc.removeEventListener("icegatheringstatechange", handle);
      resolve();
    };
    const handle = () => {
      if (pc.iceGatheringState === "complete") finish();
    };
    const timer = window.setTimeout(finish, timeoutMs);
    pc.addEventListener("icegatheringstatechange", handle);
  });
}

function safeJson(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : {};
  } catch {
    return {};
  }
}

function cleanTranscript(value: unknown) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

export class AepRealtimeVoiceClient {
  private pc: RTCPeerConnection | null = null;
  private channel: RTCDataChannel | null = null;
  private localStream: MediaStream | null = null;
  private remoteAudio: HTMLAudioElement | null = null;
  private callbacks: RealtimeVoiceCallbacks;
  private state: VoiceState = "idle";
  private currentAssistantTranscript = "";
  private latestUserTranscript = "";
  private lastCommittedPair = "";
  private pendingToolCalls = 0;
  private responseHasFunctionCall = false;
  private stopped = false;

  constructor(callbacks: RealtimeVoiceCallbacks) {
    this.callbacks = callbacks;
  }

  setCallbacks(callbacks: RealtimeVoiceCallbacks) {
    this.callbacks = callbacks;
  }

  getState() {
    return this.state;
  }

  private setState(state: VoiceState) {
    this.state = state;
    this.callbacks.onState?.(state);
  }

  private fail(message: string) {
    this.setState("error");
    this.callbacks.onError?.(message);
  }

  async start(options: RealtimeVoiceOptions) {
    if (this.pc) return;
    this.stopped = false;
    this.setState("connecting");

    if (!navigator.mediaDevices?.getUserMedia || typeof RTCPeerConnection === "undefined") {
      this.fail("This browser does not support live voice.");
      return;
    }

    if (!navigator.onLine) {
      this.fail("Live voice needs a network connection. Field capture still works offline.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
      if (this.stopped) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      this.localStream = stream;

      const pc = new RTCPeerConnection();
      this.pc = pc;
      stream.getAudioTracks().forEach((track) => pc.addTrack(track, stream));

      const audio = document.createElement("audio");
      audio.autoplay = true;
      audio.setAttribute("playsinline", "");
      this.remoteAudio = audio;

      pc.addEventListener("track", (event) => {
        const remote = event.streams[0];
        if (remote) {
          audio.srcObject = remote;
          void audio.play().catch(() => null);
        }
      });

      pc.addEventListener("connectionstatechange", () => {
        if (this.stopped) return;
        if (pc.connectionState === "connected" && this.state === "connecting") {
          this.setState("listening");
        } else if (["failed", "closed"].includes(pc.connectionState)) {
          this.fail("The live voice connection ended.");
        }
      });

      const channel = pc.createDataChannel("oai-events");
      this.channel = channel;
      channel.addEventListener("message", (event) => this.handleEvent(event.data));
      channel.addEventListener("close", () => {
        if (!this.stopped && this.state !== "idle") this.fail("The live voice session ended.");
      });

      const offer = await pc.createOffer({ offerToReceiveAudio: true });
      await pc.setLocalDescription(offer);
      await waitForIceGathering(pc);
      const localSdp = pc.localDescription?.sdp;
      if (!localSdp) throw new Error("Could not create the live voice connection.");

      const token = accessToken();
      const response = await fetch(`${API_BASE_URL}/v1/voice/realtime/call`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/sdp",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          sdp: localSdp,
          surface: options.surface,
          workspace_id: options.workspaceId,
          field_id: options.fieldId,
          field_name: options.fieldName,
          crop: options.crop,
          conversation_id: options.conversationId,
          language: options.language || "auto",
          voice: options.voice || "ash",
          response_detail: options.responseDetail || "normal",
          history: (options.history || []).slice(-12).map((item) => ({
            role: item.role,
            content: cleanTranscript(item.content).slice(0, 2200),
          })).filter((item) => item.content),
        }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({})) as any;
        const detail = body?.detail?.message || body?.detail || "Live AGRO-AI voice could not start.";
        throw new Error(String(detail));
      }

      const answerSdp = await response.text();
      if (!answerSdp.trim()) throw new Error("The live voice service returned an empty connection.");
      await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });

      if (channel.readyState === "open") {
        this.setState("listening");
      } else {
        await new Promise<void>((resolve, reject) => {
          const timer = window.setTimeout(() => reject(new Error("Live voice connection timed out.")), 8000);
          const opened = () => {
            window.clearTimeout(timer);
            channel.removeEventListener("open", opened);
            resolve();
          };
          channel.addEventListener("open", opened);
        });
        this.setState("listening");
      }
    } catch (error) {
      this.stop();
      const message = error instanceof Error ? error.message : "Live AGRO-AI voice could not start.";
      this.fail(message);
    }
  }

  mute(muted: boolean) {
    this.localStream?.getAudioTracks().forEach((track) => {
      track.enabled = !muted;
    });
  }

  isMuted() {
    return this.localStream?.getAudioTracks().every((track) => !track.enabled) ?? false;
  }

  stop() {
    this.stopped = true;
    try { this.channel?.close(); } catch { /* already closed */ }
    try { this.pc?.close(); } catch { /* already closed */ }
    this.localStream?.getTracks().forEach((track) => track.stop());
    if (this.remoteAudio) {
      this.remoteAudio.pause();
      this.remoteAudio.srcObject = null;
    }
    this.channel = null;
    this.pc = null;
    this.localStream = null;
    this.remoteAudio = null;
    this.pendingToolCalls = 0;
    this.responseHasFunctionCall = false;
    this.currentAssistantTranscript = "";
    this.latestUserTranscript = "";
    this.lastCommittedPair = "";
    this.setState("idle");
  }

  private sendEvent(payload: Record<string, unknown>) {
    if (this.channel?.readyState !== "open") return;
    this.channel.send(JSON.stringify(payload));
  }

  private async runTool(item: Record<string, any>) {
    const name = String(item.name || "");
    const callId = String(item.call_id || "");
    if (!callId) return;
    this.pendingToolCalls += 1;
    this.responseHasFunctionCall = true;
    this.setState("thinking");

    let output: unknown;
    try {
      if (!name || !this.callbacks.onToolCall) {
        output = { status: "error", error: "tool_not_available" };
      } else {
        output = await this.callbacks.onToolCall({
          name,
          arguments: safeJson(String(item.arguments || "{}")),
        });
      }
    } catch (error) {
      output = {
        status: "error",
        error: error instanceof Error ? error.message : "tool_execution_failed",
      };
    } finally {
      this.pendingToolCalls = Math.max(0, this.pendingToolCalls - 1);
    }

    this.sendEvent({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: callId,
        output: JSON.stringify(output ?? {}),
      },
    });
    this.sendEvent({ type: "response.create" });
  }

  private commitExchangeIfReady() {
    if (this.pendingToolCalls > 0 || this.responseHasFunctionCall) return;
    const user = cleanTranscript(this.latestUserTranscript);
    const assistant = cleanTranscript(this.currentAssistantTranscript);
    if (!user || !assistant) return;
    const pair = `${user}\n---\n${assistant}`;
    if (pair === this.lastCommittedPair) return;
    this.lastCommittedPair = pair;
    void this.callbacks.onExchange?.(user, assistant);
  }

  private handleEvent(raw: unknown) {
    let event: Record<string, any>;
    try {
      event = typeof raw === "string" ? JSON.parse(raw) : raw as Record<string, any>;
    } catch {
      return;
    }
    if (!event || typeof event !== "object") return;

    const type = String(event.type || "");

    if (type === "input_audio_buffer.speech_started") {
      this.currentAssistantTranscript = "";
      this.responseHasFunctionCall = false;
      this.setState("listening");
      return;
    }

    if (type === "input_audio_buffer.speech_stopped") {
      this.setState("thinking");
      return;
    }

    if (
      type === "conversation.item.input_audio_transcription.delta" ||
      type === "input_audio_transcription.delta"
    ) {
      const delta = String(event.delta || "");
      if (delta) this.callbacks.onUserTranscript?.(delta, false);
      return;
    }

    if (
      type === "conversation.item.input_audio_transcription.completed" ||
      type === "input_audio_transcription.completed"
    ) {
      const transcript = cleanTranscript(event.transcript);
      if (transcript) {
        this.latestUserTranscript = transcript;
        this.callbacks.onUserTranscript?.(transcript, true);
      }
      return;
    }

    if (type === "response.created" || type === "response.in_progress") {
      this.setState("thinking");
      return;
    }

    if (
      type === "response.output_audio_transcript.delta" ||
      type === "response.audio_transcript.delta"
    ) {
      const delta = String(event.delta || "");
      if (delta) {
        this.currentAssistantTranscript += delta;
        this.setState("speaking");
        this.callbacks.onAssistantTranscript?.(this.currentAssistantTranscript, false);
      }
      return;
    }

    if (
      type === "response.output_audio_transcript.done" ||
      type === "response.audio_transcript.done"
    ) {
      const transcript = cleanTranscript(event.transcript || this.currentAssistantTranscript);
      if (transcript) {
        this.currentAssistantTranscript = transcript;
        this.callbacks.onAssistantTranscript?.(transcript, true);
      }
      return;
    }

    if (type === "response.output_audio.delta" || type === "response.audio.delta") {
      this.setState("speaking");
      return;
    }

    if (type === "response.output_item.done") {
      const item = event.item as Record<string, any> | undefined;
      if (item?.type === "function_call") {
        void this.runTool(item);
      }
      return;
    }

    if (type === "response.done") {
      if (this.responseHasFunctionCall) {
        // A completed response containing a function call is only the tool
        // hand-off. The actual spoken answer arrives in the next response.
        if (this.pendingToolCalls === 0) this.responseHasFunctionCall = false;
      } else {
        this.commitExchangeIfReady();
        this.setState("listening");
      }
      return;
    }

    if (type === "error") {
      const message = String(event.error?.message || event.message || "Live voice encountered an error.");
      this.fail(message);
    }
  }
}

async function postVoiceTool(path: string, body: Record<string, unknown>) {
  const token = accessToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({})) as any;
  if (!response.ok) {
    throw new Error(String(data?.detail?.message || data?.detail || "AGRO-AI voice tool failed."));
  }
  return data;
}

export async function callVoiceTool(
  call: VoiceToolCall,
  options: {
    workspaceId?: string;
    fieldId?: string;
    language?: string;
    history?: VoiceHistoryItem[];
  },
) {
  if (call.name === "ask_agro_ai") {
    const question = cleanTranscript(call.arguments.question);
    if (!question) return { status: "error", error: "empty_question" };

    const requestedMode = String(call.arguments.reasoning_mode || "standard");
    const reasoningMode = ["quick", "standard", "deep"].includes(requestedMode)
      ? requestedMode
      : "standard";

    return postVoiceTool("/v1/voice/tools/ask-agro-ai", {
      question,
      workspace_id: options.workspaceId,
      field_id: options.fieldId,
      preferred_language: options.language || "auto",
      reasoning_mode: reasoningMode,
      history: (options.history || []).slice(-12),
    });
  }

  if (call.name === "plan_aep_action") {
    const instruction = cleanTranscript(call.arguments.instruction);
    if (!instruction) return { status: "error", error: "empty_instruction" };
    return postVoiceTool("/v1/voice/tools/plan-action", {
      instruction,
      workspace_id: options.workspaceId,
      answer: cleanTranscript(call.arguments.answer_context),
    });
  }

  if (call.name === "execute_aep_action") {
    const actionType = String(call.arguments.action_type || "");
    const payload = call.arguments.payload && typeof call.arguments.payload === "object"
      ? call.arguments.payload as Record<string, unknown>
      : {};
    if (!actionType) return { status: "error", error: "missing_action_type" };
    return postVoiceTool("/v1/voice/tools/execute-action", {
      action_type: actionType,
      workspace_id: options.workspaceId,
      payload,
    });
  }

  return { status: "error", error: "unsupported_tool" };
}
