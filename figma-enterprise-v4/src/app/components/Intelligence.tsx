import { useCallback, useEffect, useMemo, useState } from "react";
import { apiClient, ReportFactoryPayload } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;

const PROMPTS = [
  "What needs attention today?",
  "Generate a water risk brief.",
  "What evidence is missing?",
  "Create an operator checklist.",
  "Prepare a compliance packet.",
  "Draft an owner update.",
];

const AUDIENCES = ["operator", "manager", "owner", "agency", "lender"];
const OUTPUTS = ["answer", "report", "checklist", "email draft"];

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = "Not available") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return fallback;
  }
}

function reportTypeForPrompt(prompt: string): ReportFactoryPayload["report_type"] {
  const lower = prompt.toLowerCase();
  if (lower.includes("compliance") || lower.includes("packet")) return "compliance_packet";
  if (lower.includes("water")) return "water_use_summary";
  if (lower.includes("exception") || lower.includes("risk")) return "exception_report";
  if (lower.includes("operator") || lower.includes("grower") || lower.includes("checklist")) return "grower_recommendation";
  return "executive_brief";
}

function lastAssistant(messages: AnyRecord[]) {
  return [...messages].reverse().find((message) => message.role === "assistant") || null;
}

function actionsFrom(message: AnyRecord | null): AnyRecord[] {
  const first = asArray(message?.artifacts)[0] as AnyRecord | undefined;
  return asArray(first?.actions) as AnyRecord[];
}

function normalizeAssistantResponse(response: unknown): AnyRecord {
  const payload = response && typeof response === "object" ? (response as AnyRecord) : {};
  const result = payload.result && typeof payload.result === "object" ? payload.result as AnyRecord : {};
  const summary =
    result.answer ||
    result.summary ||
    payload.answer ||
    payload.summary ||
    payload.content ||
    "AGRO-AI prepared a workspace response.";
  const sections = [
    ["Decision summary", summary],
    ["Evidence used", asArray(payload.citations || result.citations || result.evidence_used).map(text).join("\n")],
    ["Missing evidence", asArray(payload.missing_data || result.missing_data).map(text).join("\n")],
    ["Risks and confidence", [payload.confidence || result.confidence, ...(asArray(payload.verification?.warnings || result.warnings))].filter(Boolean).map(text).join("\n")],
    ["Recommended next action", asArray(result.recommended_next_actions || payload.recommended_actions || result.actions).map(text).join("\n")],
  ].filter(([, value]) => String(value || "").trim());

  return {
    id: `assistant-${Date.now()}`,
    role: "assistant",
    content: sections.map(([title, value]) => `${title}\n${value}`).join("\n\n"),
    citations: asArray(payload.citations || result.citations),
    missing_data: asArray(payload.missing_data || result.missing_data),
    recommended_actions: asArray(result.recommended_next_actions || payload.recommended_actions || result.actions),
    model_status: payload.model_status || result.model_status || payload.status,
    model: payload.model || result.model,
    confidence: payload.confidence || result.confidence,
    verification: payload.verification || result.verification,
  };
}

function List({ title, items, empty = "None yet." }: { title: string; items: unknown[]; empty?: string }) {
  return (
    <div className="rounded-lg p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="text-[11px] font-semibold uppercase mb-3" style={{ color: MUTED }}>{title}</div>
      <div className="space-y-2">
        {items.length ? items.map((item, index) => <div key={`${title}-${index}`} className="text-[13px] leading-relaxed" style={{ color: TEXT }}>{text(item)}</div>) : <div className="text-[13px]" style={{ color: MUTED }}>{empty}</div>}
      </div>
    </div>
  );
}

export function Intelligence() {
  const { currentWorkspace } = useAuth();
  const conversationState = usePortalResource<{ conversations: AnyRecord[] }>(useCallback(() => apiClient.conversations.list(), []));
  const [conversationId, setConversationId] = useState<string>("");
  const [messages, setMessages] = useState<AnyRecord[]>([]);
  const [question, setQuestion] = useState("What needs attention today?");
  const [audience, setAudience] = useState("manager");
  const [output, setOutput] = useState("answer");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [reportMessage, setReportMessage] = useState("");

  const conversations = conversationState.data?.conversations || [];
  const assistant = useMemo(() => lastAssistant(messages), [messages]);
  const artifactActions = actionsFrom(assistant);

  async function loadConversation(id: string) {
    setConversationId(id);
    const response = await apiClient.conversations.get(id) as AnyRecord;
    setMessages(asArray(response.messages) as AnyRecord[]);
  }

  useEffect(() => {
    if (!conversationId && conversations[0]?.id) {
      loadConversation(conversations[0].id).catch(() => null);
    }
  }, [conversationId, conversations]);

  async function newChat() {
    setConversationId("");
    setMessages([]);
    setQuestion("What needs attention today?");
    setReportMessage("");
  }

  async function send(prompt = question) {
    const clean = prompt.trim();
    if (!clean) return;
    setQuestion("");
    setLoading(true);
    setError("");
    setReportMessage("");
    setMessages((current) => [...current, { id: `user-${Date.now()}`, role: "user", content: clean }]);
    try {
      const response = await apiClient.intelligence.run({
        task: "chat",
        question: clean,
        workspace_id: currentWorkspace?.id,
        audience,
      }) as AnyRecord;
      setMessages((current) => [...current, normalizeAssistantResponse(response)]);
    } catch (err) {
      try {
        const response = await apiClient.ai.chat({ task: "chat", message: clean, workspace_id: currentWorkspace?.id }) as AnyRecord;
        setMessages((current) => [...current, normalizeAssistantResponse(response)]);
      } catch {
        try {
          if (!conversationId) {
            const response = await apiClient.conversations.create({ title: clean.slice(0, 80), message: clean, workspace_id: currentWorkspace?.id }) as AnyRecord;
            setConversationId(response.conversation.id);
            setMessages(asArray(response.messages) as AnyRecord[]);
            await conversationState.refresh();
          } else {
            const response = await apiClient.conversations.message(conversationId, { content: clean, audience, output }) as AnyRecord;
            setMessages((current) => [...current, response.message]);
          }
        } catch (fallbackError) {
          setError(fallbackError instanceof Error ? fallbackError.message : err instanceof Error ? err.message : "AGRO-AI could not complete the request.");
        }
      }
    } finally {
      setLoading(false);
    }
  }

  async function generateReport(download = false) {
    const source = assistant?.content || question || "Draft an owner update.";
    const payload: ReportFactoryPayload = {
      report_type: reportTypeForPrompt(source),
      workspace_id: currentWorkspace?.id,
      audience: audience === "operator" ? "operator" : audience === "agency" ? "agency" : audience === "lender" ? "lender" : "owner",
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
      setReportMessage(download ? "Structured report ready - PDF export needs retry." : "Report request could not be completed.");
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-8" style={{ background: "#0D2B1E", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
        <div className="max-w-5xl">
          <StatusBadge label="Workspace intelligence" tone="good" />
          <h1 className="mt-4 text-[34px] font-semibold tracking-tight" style={{ color: "white" }}>Ask AGRO-AI</h1>
          <p className="mt-3 max-w-3xl text-[14px] leading-relaxed" style={{ color: "rgba(255,255,255,0.68)" }}>
            Ask for field priorities, water risk, evidence gaps, operator checklists, compliance packets, or owner updates.
          </p>
        </div>
      </header>

      <main className="grid gap-5 px-8 py-7" style={{ gridTemplateColumns: "280px minmax(0, 1fr)", maxWidth: 1280 }}>
        <aside className="rounded-lg p-4 h-fit" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <PortalButton onClick={newChat}>New chat</PortalButton>
          <div className="mt-5 text-[11px] font-semibold uppercase" style={{ color: MUTED }}>History</div>
          <div className="mt-3 space-y-2">
            {conversations.map((conversation) => (
              <button key={conversation.id} onClick={() => loadConversation(conversation.id)} className="w-full rounded-lg px-3 py-2 text-left text-[12px]" style={{ background: conversationId === conversation.id ? BG : "transparent", border: `1px solid ${BORDER}`, color: TEXT }}>
                {conversation.title}
              </button>
            ))}
            {!conversations.length ? <div className="text-[12px]" style={{ color: MUTED }}>No conversations yet.</div> : null}
          </div>
        </aside>

        <section className="space-y-5">
          {error ? <InlineState title={error} /> : null}
          {reportMessage ? <InlineState title={reportMessage} /> : null}

          <div className="rounded-lg p-5 min-h-[420px]" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="space-y-4">
              {messages.map((message, index) => (
                <div key={message.id || index} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div className="max-w-[78%] rounded-lg px-4 py-3 text-[14px] leading-relaxed whitespace-pre-wrap" style={{ background: message.role === "user" ? "#0D2B1E" : BG, color: message.role === "user" ? "white" : TEXT, border: `1px solid ${message.role === "user" ? "#0D2B1E" : BORDER}` }}>
                    {message.content}
                  </div>
                </div>
              ))}
              {loading ? <InlineState title="AGRO-AI is preparing the response." /> : null}
              {!messages.length && !loading ? <InlineState title="Start with a suggested prompt or ask your own question." /> : null}
            </div>
          </div>

          {assistant ? (
            <div className="grid gap-4 md:grid-cols-3">
              <List title="Recommended actions" items={asArray(assistant.recommended_actions)} />
              <List title="Missing information" items={asArray(assistant.missing_data)} />
              <List title="Citations and status" items={[assistant.model_status ? `Model status: ${assistant.model_status}` : "", assistant.model ? `Model: ${assistant.model}` : "", assistant.confidence ? `Confidence: ${assistant.confidence}` : "", ...asArray(assistant.citations).map(text), ...artifactActions.map((action) => action.label || action.type)].filter(Boolean)} />
            </div>
          ) : null}

          <div className="rounded-lg p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="mb-4 flex flex-wrap gap-2">
              {PROMPTS.map((prompt) => (
                <button key={prompt} type="button" onClick={() => send(prompt)} className="rounded-full px-3 py-2 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>{prompt}</button>
              ))}
            </div>
            <div className="grid gap-3 md:grid-cols-[1fr_160px_160px]">
              <textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={2} placeholder="Ask AGRO-AI..." className="resize-none rounded-lg px-4 py-3 text-[14px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
              <select value={audience} onChange={(event) => setAudience(event.target.value)} className="h-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>{AUDIENCES.map((item) => <option key={item}>{item}</option>)}</select>
              <select value={output} onChange={(event) => setOutput(event.target.value)} className="h-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>{OUTPUTS.map((item) => <option key={item}>{item}</option>)}</select>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <PortalButton onClick={() => send()} disabled={loading}>{loading ? "Working" : "Send"}</PortalButton>
              <PortalButton variant="secondary" onClick={() => generateReport(false)}>Generate report</PortalButton>
              <PortalButton variant="secondary" onClick={() => generateReport(true)}>Download PDF</PortalButton>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
