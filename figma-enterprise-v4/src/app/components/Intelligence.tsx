import { KeyboardEvent, useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, GREEN, MUTED, PortalButton, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "";
  }
}

function lines(value: unknown): string[] {
  if (!value) return [];
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const row = item as AnyRecord;
          return row.label || row.title || row.name || row.summary || row.next_step || text(row);
        }
        return text(item);
      })
      .filter(Boolean);
  }
  return [text(value)].filter(Boolean);
}

function block(label: string, value: unknown) {
  const rows = lines(value);
  if (!rows.length) return "";
  return `${label}:\n${rows.map((row) => `• ${row}`).join("\n")}`;
}

function operationalAnswer(response: AnyRecord) {
  const result = response.result && typeof response.result === "object" ? response.result : response;
  const direct = result.executive_summary || result.summary || result.answer || response.output || response.message || result.content;
  const sections = [
    direct ? `Summary:\n${text(direct)}` : "",
    block("Evidence used", result.evidence_used || result.available_data || result.key_findings || result.field_summary),
    block("Missing evidence", result.missing_evidence || result.missing_data || response.missing_data),
    block("Recommendations", result.recommendations || result.recommended_next_actions || result.operator_instructions),
    block("Next actions", result.next_actions || result.operator_tasks),
    block("Risk flags", result.risk_flags || result.risks || result.reviewer_notes),
  ].filter(Boolean);

  const footer = [
    result.confidence || response.confidence ? `Confidence: ${result.confidence || response.confidence}` : "",
    response.model_status || response.status ? `Engine status: ${response.model_status || response.status}` : "",
    response.provider || response.model ? `Runtime: ${[response.provider, response.model].filter(Boolean).join(" / ")}` : "",
  ].filter(Boolean);

  return sections.length
    ? [...sections, footer.join(" · ")].filter(Boolean).join("\n\n")
    : "AGRO-AI received the request, but the operating engine did not return a structured answer yet. Add field, sensor, ET/weather, document, or operator evidence so the engine can produce a stronger decision brief.";
}

async function runOperatingBrain(question: string, workspaceId?: string) {
  try {
    const response = await apiClient.intelligence.run({ task: "chat", question, workspace_id: workspaceId }) as AnyRecord;
    return { role: "assistant", content: operationalAnswer(response), engine: response.provider || "intelligence", meta: response };
  } catch (primaryError) {
    try {
      const response = await apiClient.ai.chat({ message: question, workspace_id: workspaceId }) as AnyRecord;
      return { role: "assistant", content: operationalAnswer(response), engine: response.provider || "ai", meta: response };
    } catch {
      throw primaryError;
    }
  }
}

export function Intelligence() {
  const { currentWorkspace } = useAuth();
  const conversationState = usePortalResource<{ conversations: AnyRecord[] }>(useCallback(() => apiClient.conversations.list(), []));
  const [conversationId, setConversationId] = useState("");
  const [messages, setMessages] = useState<AnyRecord[]>([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const conversations = conversationState.data?.conversations || [];

  const loadConversation = useCallback(async (id: string) => {
    setConversationId(id);
    setError("");
    const response = await apiClient.conversations.get(id) as AnyRecord;
    setMessages(asArray(response.messages) as AnyRecord[]);
  }, []);

  useEffect(() => {
    if (!conversationId && conversations[0]?.id && messages.length === 0) {
      loadConversation(String(conversations[0].id)).catch(() => null);
    }
  }, [conversationId, conversations, loadConversation, messages.length]);

  async function newChat() {
    setConversationId("");
    setMessages([]);
    setQuestion("");
    setError("");
  }

  async function persistChat(userText: string, assistantText: string) {
    try {
      if (!conversationId) {
        const response = await apiClient.conversations.create({
          title: userText.slice(0, 80),
          message: userText,
          workspace_id: currentWorkspace?.id,
        }) as AnyRecord;
        const nextId = String(response.conversation?.id || "");
        if (nextId) setConversationId(nextId);
        await conversationState.refresh().catch(() => null);
      } else {
        await apiClient.conversations.message(conversationId, { content: userText, output: assistantText }).catch(() => null);
      }
    } catch {
      return;
    }
  }

  async function send(prompt = question) {
    const clean = prompt.trim();
    if (!clean || loading) return;

    const userMessage = { role: "user", content: clean };
    setQuestion("");
    setLoading(true);
    setError("");
    setMessages((current) => [...current, userMessage]);

    try {
      const assistantMessage = await runOperatingBrain(clean, currentWorkspace?.id);
      setMessages((current) => [...current, assistantMessage]);
      persistChat(clean, assistantMessage.content).catch(() => null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "AGRO-AI could not complete the request.");
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send().catch(() => null);
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <main className="grid gap-5 px-8 py-7" style={{ gridTemplateColumns: "280px minmax(0, 1fr)", maxWidth: 1320 }}>
        <aside className="rounded-xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <PortalButton onClick={newChat}>
            <Plus className="h-4 w-4" />
            New chat
          </PortalButton>
          <div className="mt-5 text-[11px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>History</div>
          <div className="mt-3 space-y-2">
            {conversations.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                onClick={() => loadConversation(String(conversation.id))}
                className="w-full rounded-xl px-3 py-3 text-left text-[12px]"
                style={{ background: conversationId === conversation.id ? BG : "transparent", border: `1px solid ${BORDER}`, color: TEXT }}
              >
                {conversation.title || "Untitled chat"}
              </button>
            ))}
            {!conversations.length ? <p className="text-[12px] leading-6" style={{ color: MUTED }}>No previous chats yet.</p> : null}
          </div>
        </aside>

        <section className="flex min-h-[78vh] flex-col rounded-xl" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="border-b px-6 py-5" style={{ borderColor: BORDER }}>
            <div className="mb-3 grid gap-3 md:grid-cols-4">
              {["AI engine: live", "Data ingestion: ready", "Evidence pipeline: ready", "Reports: plan-gated"].map((item) => (
                <div key={item} className="rounded-lg px-3 py-2 text-[12px] font-medium" style={{ background: BG, color: TEXT, border: `1px solid ${BORDER}` }}>
                  <span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ background: GREEN }} />
                  {item}
                </div>
              ))}
            </div>
            <h1 className="text-[26px] font-semibold tracking-tight" style={{ color: TEXT }}>Ask AGRO-AI</h1>
            <p className="mt-2 text-[14px] leading-6" style={{ color: MUTED }}>
              Ask for decision summaries, missing evidence, field priorities, water risk, compliance packets, or owner-ready reports. AGRO-AI will use connected workspace context when available and tell you what evidence is missing when it is not.
            </p>
          </div>

          <div className="flex-1 space-y-4 overflow-auto px-6 py-6">
            {!messages.length ? (
              <div className="mx-auto mt-20 max-w-[640px] text-center">
                <h2 className="text-[24px] font-semibold" style={{ color: TEXT }}>What should AGRO-AI help you operate?</h2>
                <p className="mt-3 text-[14px] leading-7" style={{ color: MUTED }}>
                  Start with a field, report, compliance requirement, irrigation decision, or evidence gap. The workspace context stays attached in the background.
                </p>
              </div>
            ) : null}

            {messages.map((message, index) => (
              <div key={message.id || index} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className="max-w-[78%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-[14px] leading-7"
                  style={{
                    background: message.role === "user" ? "#10231B" : BG,
                    color: message.role === "user" ? "white" : TEXT,
                    border: `1px solid ${message.role === "user" ? "#10231B" : BORDER}`,
                  }}
                >
                  {text(message.content)}
                  {message.role === "assistant" && message.engine ? (
                    <div className="mt-3 border-t pt-2 text-[11px]" style={{ borderColor: BORDER, color: MUTED }}>
                      Runtime: {message.engine}
                    </div>
                  ) : null}
                </div>
              </div>
            ))}

            {loading ? <div className="text-[13px]" style={{ color: MUTED }}>AGRO-AI is reading the workspace evidence and preparing the response.</div> : null}
            {error ? <div className="text-[13px]" style={{ color: "#A4492F" }}>{error}</div> : null}
          </div>

          <div className="border-t px-6 py-5" style={{ borderColor: BORDER }}>
            <div className="rounded-2xl px-4 py-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={onKeyDown}
                rows={3}
                placeholder="Message AGRO-AI"
                className="w-full resize-none border-0 bg-transparent text-[14px] outline-none"
                style={{ color: TEXT }}
              />
              <div className="mt-4 flex items-center justify-between gap-3">
                <div className="text-[12px]" style={{ color: MUTED }}>Enter to send. Shift + Enter for a new line.</div>
                <PortalButton onClick={() => send()} disabled={loading}>Send</PortalButton>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
