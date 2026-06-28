import { KeyboardEvent, useEffect, useMemo, useState } from "react";
import { apiClient, ReportFactoryPayload } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { BG, BORDER, InlineState, MUTED, PortalButton, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;
type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string;
  recommended_actions?: { id: string; label: string; action?: string }[];
  missing_data?: unknown[];
  evidence_used?: unknown[];
  artifacts?: unknown[];
};
type Conversation = { id: string; title: string; messages?: ChatMessage[] };

const suggestions = [
  "What needs attention today?",
  "Generate a water risk brief.",
  "What evidence is missing?",
  "Create an operator checklist.",
  "Prepare a compliance packet.",
];

function text(value: unknown, fallback = "") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try { return JSON.stringify(value); } catch { return fallback; }
}

function reportTypeForPrompt(prompt: string): ReportFactoryPayload["report_type"] {
  const lower = prompt.toLowerCase();
  if (lower.includes("compliance") || lower.includes("assurance") || lower.includes("packet")) return "compliance_packet";
  if (lower.includes("exception") || lower.includes("risk")) return "exception_report";
  if (lower.includes("grower") || lower.includes("operator") || lower.includes("checklist")) return "grower_recommendation";
  if (lower.includes("water use") || lower.includes("irrigation") || lower.includes("et")) return "water_use_summary";
  return "executive_brief";
}

function customerAnswer(response: AnyRecord) {
  const result = response.result || response;
  return text(result.answer || result.summary || result.executive_summary || result.message, "AGRO-AI completed the request.");
}

export function Intelligence() {
  const { currentWorkspace } = useAuth();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [audience, setAudience] = useState("manager");
  const [output, setOutput] = useState("answer");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [reportPayload, setReportPayload] = useState<ReportFactoryPayload | null>(null);

  const sortedConversations = useMemo(() => conversations.slice(0, 8), [conversations]);

  async function refreshConversations() {
    try {
      const response = await apiClient.request<AnyRecord>("/v1/conversations");
      setConversations(response.conversations || []);
    } catch {
      setConversations([]);
    }
  }

  async function newChat() {
    setError("");
    const response = await apiClient.request<AnyRecord>("/v1/conversations", { method: "POST", body: JSON.stringify({ title: "New AGRO-AI chat" }) });
    const conversation = response.conversation as Conversation;
    setConversationId(conversation.id);
    setMessages([]);
    await refreshConversations();
  }

  async function openConversation(id: string) {
    const response = await apiClient.request<AnyRecord>(`/v1/conversations/${encodeURIComponent(id)}`);
    setConversationId(id);
    setMessages(response.conversation?.messages || []);
  }

  useEffect(() => { refreshConversations(); }, []);

  async function sendMessage(prompt = input) {
    const clean = prompt.trim();
    if (!clean || loading) return;
    setInput("");
    setLoading(true);
    setError("");

    let activeConversationId = conversationId;
    try {
      if (!activeConversationId) {
        const response = await apiClient.request<AnyRecord>("/v1/conversations", { method: "POST", body: JSON.stringify({ title: clean.slice(0, 80) }) });
        activeConversationId = response.conversation.id;
        setConversationId(activeConversationId);
      }

      const userMessage: ChatMessage = { id: `local_${Date.now()}`, role: "user", content: clean };
      setMessages((current) => [...current, userMessage]);

      const isReport = /report|pdf|brief|packet|summary/i.test(clean) || output === "report";
      if (isReport) {
        const payload: ReportFactoryPayload = {
          report_type: reportTypeForPrompt(clean),
          workspace_id: currentWorkspace?.id,
          audience: audience === "agency" ? "agency" : audience === "operator" ? "operator" : "owner",
        };
        const report = await apiClient.reportFactory.generate(payload) as AnyRecord;
        setReportPayload(payload);
        const content = text(report.report?.executive_summary || report.report?.title || "Report preview is ready.");
        const assistant: ChatMessage = {
          id: `assistant_${Date.now()}`,
          role: "assistant",
          content,
          recommended_actions: [
            { id: "download_pdf", label: "Download PDF", action: "pdf" },
            { id: "save_report", label: "Save to Reports", action: "report" },
          ],
          missing_data: report.report?.missing_evidence || [],
          evidence_used: report.report?.evidence_appendix || [],
        };
        setMessages((current) => [...current, assistant]);
        await apiClient.request(`/v1/conversations/${encodeURIComponent(activeConversationId)}/messages`, { method: "POST", body: JSON.stringify({ content: clean, audience, output }) });
      } else {
        const response = await apiClient.intelligence.ask({ question: clean, workspace_id: currentWorkspace?.id, customer_mode: audience, output_format: output }) as AnyRecord;
        const result = response.result || response;
        const assistant: ChatMessage = {
          id: `assistant_${Date.now()}`,
          role: "assistant",
          content: customerAnswer(response),
          recommended_actions: (result.next_actions || result.recommendations || []).map((item: unknown, index: number) => ({ id: `action_${index}`, label: text(item, "Review action") })),
          missing_data: result.what_is_missing || result.missing_data || [],
          evidence_used: result.what_i_used || result.evidence_used || [],
        };
        setMessages((current) => [...current, assistant]);
        await apiClient.request(`/v1/conversations/${encodeURIComponent(activeConversationId)}/messages`, { method: "POST", body: JSON.stringify({ content: clean, audience, output }) });
      }
      await refreshConversations();
    } catch (err) {
      setError(err instanceof Error ? err.message : "AGRO-AI could not complete the request.");
    } finally {
      setLoading(false);
    }
  }

  async function downloadPdf() {
    if (!reportPayload) return;
    const blob = await apiClient.reportFactory.pdf(reportPayload);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `agro-ai-${reportPayload.report_type}.pdf`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  }

  return (
    <div className="flex h-[calc(100vh-0px)]" style={{ background: BG }}>
      <aside className="hidden w-[260px] border-r lg:block" style={{ background: SURFACE, borderColor: BORDER }}>
        <div className="p-4 border-b" style={{ borderColor: BORDER }}>
          <button type="button" onClick={newChat} className="h-10 w-full rounded-xl text-[13px] font-semibold" style={{ background: "#050505", color: "white" }}>New chat</button>
        </div>
        <div className="p-3 space-y-1 overflow-y-auto">
          {sortedConversations.map((conversation) => (
            <button key={conversation.id} type="button" onClick={() => openConversation(conversation.id)} className="w-full truncate rounded-lg px-3 py-2 text-left text-[13px]" style={{ background: conversation.id === conversationId ? BG : "transparent", color: TEXT }}>
              {conversation.title || "AGRO-AI chat"}
            </button>
          ))}
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="px-8 py-6 border-b" style={{ background: SURFACE, borderColor: BORDER }}>
          <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Ask AGRO-AI</h1>
          <p className="mt-2 max-w-3xl text-[14px]" style={{ color: MUTED }}>Ask about field priorities, missing evidence, operator tasks, water risk, compliance packets, or reports.</p>
        </header>

        <section className="flex-1 overflow-y-auto px-8 py-6">
          <div className="mx-auto max-w-4xl space-y-4">
            {error ? <InlineState title={error} /> : null}
            {!messages.length ? (
              <div className="rounded-2xl p-8 text-center" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
                <div className="text-[22px] font-semibold" style={{ color: TEXT }}>What should AGRO-AI help you run?</div>
                <p className="mt-2 text-[14px]" style={{ color: MUTED }}>Start with a question or choose a prompt below.</p>
                <div className="mt-6 flex flex-wrap justify-center gap-2">{suggestions.map((item) => <button key={item} type="button" onClick={() => sendMessage(item)} className="rounded-full px-4 py-2 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>{item}</button>)}</div>
              </div>
            ) : null}

            {messages.map((message) => (
              <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className="max-w-[78%] rounded-2xl px-5 py-4 text-[14px] leading-relaxed" style={{ background: message.role === "user" ? "#0D2B1E" : SURFACE, color: message.role === "user" ? "white" : TEXT, border: message.role === "user" ? "none" : `1px solid ${BORDER}` }}>
                  <div className="whitespace-pre-wrap">{message.content}</div>
                  {message.role === "assistant" && message.recommended_actions?.length ? <div className="mt-4 flex flex-wrap gap-2">{message.recommended_actions.map((action) => <button key={action.id} type="button" onClick={action.action === "pdf" ? downloadPdf : undefined} className="rounded-full px-3 py-1.5 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>{action.label}</button>)}</div> : null}
                  {message.role === "assistant" && message.missing_data?.length ? <div className="mt-4 text-[12px]" style={{ color: MUTED }}><strong>Missing information:</strong> {message.missing_data.map(text).join(", ")}</div> : null}
                </div>
              </div>
            ))}
            {loading ? <InlineState title="AGRO-AI is working…" detail="Reading workspace context and preparing a useful answer." /> : null}
          </div>
        </section>

        <footer className="border-t px-8 py-4" style={{ background: SURFACE, borderColor: BORDER }}>
          <div className="mx-auto max-w-4xl">
            <div className="mb-3 flex flex-wrap gap-3">
              <select value={audience} onChange={(event) => setAudience(event.target.value)} className="h-9 rounded-lg px-3 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                <option value="operator">Operator</option><option value="manager">Manager</option><option value="owner">Owner</option><option value="agency">Agency</option><option value="lender">Lender</option>
              </select>
              <select value={output} onChange={(event) => setOutput(event.target.value)} className="h-9 rounded-lg px-3 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                <option value="answer">Answer</option><option value="report">Report</option><option value="checklist">Checklist</option><option value="email_draft">Email draft</option>
              </select>
            </div>
            <div className="flex gap-3 rounded-2xl p-2" style={{ background: BG, border: `1px solid ${BORDER}` }}>
              <textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={onKeyDown} rows={1} placeholder="Message AGRO-AI…" className="min-h-[44px] flex-1 resize-none bg-transparent px-3 py-3 text-[14px] outline-none" style={{ color: TEXT }} />
              <button type="button" onClick={() => sendMessage()} disabled={loading || !input.trim()} className="h-11 rounded-xl px-5 text-[13px] font-semibold disabled:opacity-50" style={{ background: "#050505", color: "white" }}>Send</button>
            </div>
          </div>
        </footer>
      </main>
    </div>
  );
}
