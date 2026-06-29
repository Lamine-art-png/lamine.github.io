import { KeyboardEvent, useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, MUTED, PortalButton, SURFACE, TEXT } from "./portalUi";

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
    if (!conversationId && conversations[0]?.id) {
      loadConversation(String(conversations[0].id)).catch(() => null);
    }
  }, [conversationId, conversations, loadConversation]);

  async function newChat() {
    setConversationId("");
    setMessages([]);
    setQuestion("");
    setError("");
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
      if (!conversationId) {
        const response = await apiClient.conversations.create({
          title: clean.slice(0, 80),
          message: clean,
          workspace_id: currentWorkspace?.id,
        }) as AnyRecord;
        setConversationId(String(response.conversation?.id || ""));
        setMessages(asArray(response.messages) as AnyRecord[]);
        await conversationState.refresh();
      } else {
        const response = await apiClient.conversations.message(conversationId, { content: clean }) as AnyRecord;
        setMessages((current) => [...current, response.message || { role: "assistant", content: text(response) }]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "AGRO-AI could not complete the request.");
      setMessages((current) => current.filter((message) => message !== userMessage));
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
            <h1 className="text-[26px] font-semibold tracking-tight" style={{ color: TEXT }}>Ask AGRO-AI</h1>
            <p className="mt-2 text-[14px] leading-6" style={{ color: MUTED }}>
              Ask AGRO-AI about water risk, field priorities, missing evidence, compliance packets, or owner-ready reports.
            </p>
          </div>

          <div className="flex-1 space-y-4 overflow-auto px-6 py-6">
            {!messages.length ? (
              <div className="mx-auto mt-20 max-w-[560px] text-center">
                <h2 className="text-[24px] font-semibold" style={{ color: TEXT }}>What should AGRO-AI help you operate?</h2>
                <p className="mt-3 text-[14px] leading-7" style={{ color: MUTED }}>
                  Start a clean conversation. The workspace context stays attached in the background.
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
                </div>
              </div>
            ))}

            {loading ? <div className="text-[13px]" style={{ color: MUTED }}>AGRO-AI is preparing the response.</div> : null}
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
