import { KeyboardEvent, useCallback, useEffect, useMemo, useState } from "react";
import { FileText, Plus } from "lucide-react";
import { apiClient, ReportFactoryPayload } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, MUTED, PortalButton, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function reportTypeForPrompt(prompt: string): ReportFactoryPayload["report_type"] {
  const lower = prompt.toLowerCase();
  if (lower.includes("compliance") || lower.includes("packet")) return "compliance_packet";
  if (lower.includes("water")) return "water_use_summary";
  if (lower.includes("exception") || lower.includes("risk")) return "exception_report";
  if (lower.includes("operator") || lower.includes("grower") || lower.includes("checklist")) return "grower_recommendation";
  return "executive_brief";
}

function text(value: unknown) {
  if (value === null || value === undefined || value === "") return "Not available";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return "Not available";
  }
}

function lastAssistant(messages: AnyRecord[]) {
  return [...messages].reverse().find((message) => message.role === "assistant") || null;
}

function shouldShowReportActions(message: AnyRecord | null) {
  const intent = asArray(message?.artifacts)[0] as AnyRecord | undefined;
  return ["owner_report", "compliance_packet"].includes(String(intent?.intent || ""));
}

function DetailList({ title, items }: { title: string; items: unknown[] }) {
  const [open, setOpen] = useState(false);
  if (!items.length) return null;
  return (
    <div className="rounded-xl" style={{ border: `1px solid ${BORDER}`, background: BG }}>
      <button type="button" onClick={() => setOpen((value) => !value)} className="w-full px-4 py-3 text-left text-[12px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>
        {title}
      </button>
      {open ? (
        <div className="space-y-2 px-4 pb-4">
          {items.map((item, index) => <div key={`${title}-${index}`} className="text-[13px] leading-6" style={{ color: TEXT }}>{text(item)}</div>)}
        </div>
      ) : null}
    </div>
  );
}

export function Intelligence() {
  const { currentWorkspace } = useAuth();
  const conversationState = usePortalResource<{ conversations: AnyRecord[] }>(useCallback(() => apiClient.conversations.list(), []));
  const [conversationId, setConversationId] = useState("");
  const [messages, setMessages] = useState<AnyRecord[]>([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [reportMessage, setReportMessage] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(true);

  const conversations = conversationState.data?.conversations || [];
  const assistant = useMemo(() => lastAssistant(messages), [messages]);

  async function loadConversation(id: string) {
    setConversationId(id);
    const response = await apiClient.conversations.get(id) as AnyRecord;
    setMessages(asArray(response.messages) as AnyRecord[]);
    setShowSuggestions(false);
  }

  useEffect(() => {
    if (!conversationId && conversations[0]?.id) {
      loadConversation(conversations[0].id).catch(() => null);
    }
  }, [conversationId, conversations]);

  async function newChat() {
    setConversationId("");
    setMessages([]);
    setQuestion("");
    setReportMessage("");
    setShowSuggestions(true);
  }

  async function send(prompt = question) {
    const clean = prompt.trim();
    if (!clean) return;
    setQuestion("");
    setLoading(true);
    setError("");
    setReportMessage("");
    setShowSuggestions(false);
    try {
      if (!conversationId) {
        const response = await apiClient.conversations.create({ title: clean.slice(0, 80), message: clean, workspace_id: currentWorkspace?.id }) as AnyRecord;
        setConversationId(response.conversation.id);
        setMessages(asArray(response.messages) as AnyRecord[]);
        await conversationState.refresh();
      } else {
        const response = await apiClient.conversations.message(conversationId, { content: clean }) as AnyRecord;
        setMessages((current) => [...current, { role: "user", content: clean }, response.message]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "AGRO-AI could not complete the request.");
    } finally {
      setLoading(false);
    }
  }

  async function generateReport(download = false) {
    const source = assistant?.content || question || "Draft an owner update.";
    const payload: ReportFactoryPayload = {
      report_type: reportTypeForPrompt(source),
      workspace_id: currentWorkspace?.id,
      audience: "owner",
    };
    try {
      if (download) {
        const blob = await apiClient.reportFactory.pdf(payload);
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `agro-ai-${payload.report_type}.pdf`;
        link.click();
        URL.revokeObjectURL(url);
        setReportMessage("PDF downloaded.");
        return;
      }
      await apiClient.reportFactory.generate(payload);
      setReportMessage("Structured report ready.");
    } catch {
      setReportMessage(download ? "Structured report ready - PDF export not yet enabled." : "Structured report could not be prepared.");
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
              <button key={conversation.id} onClick={() => loadConversation(conversation.id)} className="w-full rounded-xl px-3 py-3 text-left text-[12px]" style={{ background: conversationId === conversation.id ? BG : "transparent", border: `1px solid ${BORDER}`, color: TEXT }}>
                {conversation.title}
              </button>
            ))}
          </div>
        </aside>

        <section className="flex min-h-[78vh] flex-col rounded-xl" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="border-b px-6 py-5" style={{ borderColor: BORDER }}>
            <h1 className="text-[26px] font-semibold tracking-tight" style={{ color: TEXT }}>Ask AGRO-AI</h1>
            <p className="mt-2 text-[14px] leading-6" style={{ color: MUTED }}>What can AGRO-AI help you operate today?</p>
            <p className="text-[13px] leading-6" style={{ color: MUTED }}>Ask about water risk, field priorities, missing evidence, compliance packets, or owner-ready reports.</p>
          </div>

          <div className="flex-1 space-y-4 overflow-auto px-6 py-6">
            {messages.map((message, index) => (
              <div key={message.id || index} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className="max-w-[78%] rounded-2xl px-4 py-3 text-[14px] leading-7 whitespace-pre-wrap" style={{ background: message.role === "user" ? "#10231B" : BG, color: message.role === "user" ? "white" : TEXT, border: `1px solid ${message.role === "user" ? "#10231B" : BORDER}` }}>
                  {message.content}
                </div>
              </div>
            ))}

            {!messages.length && showSuggestions ? (
              <div className="grid gap-3 md:grid-cols-2">
                {[
                  "What needs attention today?",
                  "Generate a water risk brief.",
                  "What evidence is missing?",
                  "Prepare a compliance packet.",
                ].map((prompt) => (
                  <button key={prompt} type="button" onClick={() => send(prompt)} className="rounded-xl px-4 py-4 text-left text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                    {prompt}
                  </button>
                ))}
              </div>
            ) : null}

            {loading ? <div className="text-[13px]" style={{ color: MUTED }}>AGRO-AI is preparing the response.</div> : null}
            {error ? <div className="text-[13px]" style={{ color: "#A4492F" }}>{error}</div> : null}
            {reportMessage ? <div className="text-[13px]" style={{ color: "#2F6B44" }}>{reportMessage}</div> : null}

            {assistant ? (
              <div className="space-y-3">
                <DetailList title="Recommended actions" items={asArray(assistant.recommended_actions)} />
                <DetailList title="Missing evidence" items={asArray(assistant.missing_data)} />
                <DetailList title="Evidence used" items={asArray(assistant.citations)} />
              </div>
            ) : null}
          </div>

          <div className="border-t px-6 py-5" style={{ borderColor: BORDER }}>
            <div className="rounded-2xl px-4 py-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
              <textarea value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={onKeyDown} rows={3} placeholder="Ask AGRO-AI" className="w-full resize-none border-0 bg-transparent text-[14px] outline-none" style={{ color: TEXT }} />
              <div className="mt-4 flex items-center justify-between gap-3">
                <div className="text-[12px]" style={{ color: MUTED }}>Enter to send. Shift + Enter for a new line.</div>
                <div className="flex gap-2">
                  {shouldShowReportActions(assistant) ? (
                    <>
                      <PortalButton variant="secondary" onClick={() => generateReport(false)}>
                        <FileText className="h-4 w-4" />
                        Generate report
                      </PortalButton>
                      <PortalButton variant="secondary" onClick={() => generateReport(true)}>Download PDF</PortalButton>
                    </>
                  ) : null}
                  <PortalButton onClick={() => send()} disabled={loading}>Send</PortalButton>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
