import { ChangeEvent, KeyboardEvent, useCallback, useEffect, useState } from "react";
import { Paperclip, Plus, X } from "lucide-react";
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
          return row.label || row.title || row.name || row.summary || row.recommendation || row.next_step || row.why || text(row);
        }
        return text(item);
      })
      .filter(Boolean);
  }
  return [text(value)].filter(Boolean);
}

function section(label: string, value: unknown) {
  const rows = lines(value);
  if (!rows.length) return "";
  return `${label}\n${rows.map((row) => `• ${row}`).join("\n")}`;
}

function operationalAnswer(response: AnyRecord) {
  const result = response.result && typeof response.result === "object" ? response.result : response;
  const direct = result.answer || result.summary || result.executive_summary || response.output || response.message || result.content;
  const primary = text(direct).trim();
  const sections = [
    primary,
    section("What I checked", result.work_completed),
    section("Evidence used", result.evidence_used || result.available_data || result.key_findings || result.field_summary),
    section("What is missing", result.missing_evidence || result.missing_data || response.missing_data),
    section("Operating plan", result.operating_plan || result.agent_plan || result.recommendations || result.recommended_next_actions || result.operator_instructions),
    section("Next steps", result.next_actions || result.operator_tasks),
    section("Risks to watch", result.risk_flags || result.risks || result.reviewer_notes),
  ].filter(Boolean);

  return sections.length
    ? sections.join("\n\n")
    : "I received the request, but the operating engine did not return enough usable detail. Add field, sensor, ET/weather, document, or operator evidence and I can turn it into a decision brief, report, checklist, or evidence plan.";
}

function cleanHistory(messages: AnyRecord[]) {
  return messages
    .slice(-12)
    .map((message) => ({ role: message.role === "user" ? "user" : "assistant", content: text(message.content).slice(0, 2200) }))
    .filter((message) => message.content.trim());
}

async function uploadEvidenceFiles(files: File[], workspaceId?: string) {
  const uploads: AnyRecord[] = [];
  for (const file of files) {
    const response = await apiClient.evidence.upload(file, "manual_csv", workspaceId) as AnyRecord;
    uploads.push({
      filename: file.name,
      size_bytes: file.size,
      content_type: file.type || "application/octet-stream",
      status: response.status,
      rows_parsed: response.rows_parsed,
      columns: response.columns,
      evidence_records_created: response.evidence_records_created,
      evidence_preview: response.evidence_preview,
      warnings: response.warnings,
      data_source: response.data_source,
    });
  }
  return uploads;
}

async function runOperatingBrain(question: string, workspaceId?: string, history: AnyRecord[] = [], uploadedEvidence: AnyRecord[] = []) {
  try {
    const response = await apiClient.post("/v1/intelligence/brain/run", {
      question,
      workspace_id: workspaceId,
      audience: "operator",
      history: cleanHistory(history),
      uploaded_evidence: uploadedEvidence,
    }) as AnyRecord;
    return { role: "assistant", content: operationalAnswer(response), meta: response };
  } catch (primaryError) {
    try {
      const response = await apiClient.intelligence.run({
        task: "chat",
        question,
        workspace_id: workspaceId,
        audience: "operator",
      }) as AnyRecord;
      return { role: "assistant", content: operationalAnswer(response), meta: response };
    } catch {
      try {
        const response = await apiClient.ai.chat({ message: question, workspace_id: workspaceId }) as AnyRecord;
        return { role: "assistant", content: operationalAnswer(response), meta: response };
      } catch {
        throw primaryError;
      }
    }
  }
}

export function Intelligence() {
  const { currentWorkspace } = useAuth();
  const conversationState = usePortalResource<{ conversations: AnyRecord[] }>(useCallback(() => apiClient.conversations.list(), []));
  const [conversationId, setConversationId] = useState("");
  const [messages, setMessages] = useState<AnyRecord[]>([]);
  const [question, setQuestion] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
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
    setSelectedFiles([]);
    setError("");
  }

  function onFilesSelected(event: ChangeEvent<HTMLInputElement>) {
    setSelectedFiles((current) => [...current, ...Array.from(event.target.files || [])]);
    event.target.value = "";
  }

  function removeFile(index: number) {
    setSelectedFiles((current) => current.filter((_file, itemIndex) => itemIndex !== index));
  }

  async function persistChat(userText: string, assistantText: string) {
    try {
      if (!conversationId) {
        const response = await apiClient.conversations.create({
          title: userText.slice(0, 80),
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
    if ((!clean && !selectedFiles.length) || loading) return;

    const filesForRun = selectedFiles;
    const userText = clean || "Analyze the attached evidence and tell me what work should be done next.";
    const attachmentNote = filesForRun.length ? `\n\nAttached evidence: ${filesForRun.map((file) => file.name).join(", ")}` : "";
    const userMessage = { role: "user", content: `${userText}${attachmentNote}` };
    const history = messages;

    setQuestion("");
    setLoading(true);
    setUploading(Boolean(filesForRun.length));
    setError("");
    setMessages((current) => [...current, userMessage]);

    try {
      const uploadedEvidence = filesForRun.length ? await uploadEvidenceFiles(filesForRun, currentWorkspace?.id) : [];
      setUploading(false);
      const assistantMessage = await runOperatingBrain(userText, currentWorkspace?.id, history, uploadedEvidence);
      setMessages((current) => [...current, assistantMessage]);
      persistChat(userText, assistantMessage.content).catch(() => null);
      setSelectedFiles([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "AGRO-AI could not complete the request.");
    } finally {
      setUploading(false);
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
            <div className="mb-3 inline-flex items-center rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-widest" style={{ background: BG, color: GREEN, border: `1px solid ${BORDER}` }}>
              AGRO-AI Brain
            </div>
            <h1 className="text-[26px] font-semibold tracking-tight" style={{ color: TEXT }}>Ask AGRO-AI</h1>
            <p className="mt-2 max-w-[820px] text-[14px] leading-6" style={{ color: MUTED }}>
              Use this like an operating room for agriculture work: upload evidence, inspect scattered context, find gaps, organize field priorities, draft reports, prepare packets, and turn messy workspace data into action.
            </p>
          </div>

          <div className="flex-1 space-y-4 overflow-auto px-6 py-6">
            {!messages.length ? (
              <div className="mx-auto mt-20 max-w-[660px] text-center">
                <h2 className="text-[24px] font-semibold" style={{ color: TEXT }}>What should AGRO-AI work through?</h2>
                <p className="mt-3 text-[14px] leading-7" style={{ color: MUTED }}>
                  Start with a field, report, compliance requirement, customer account, irrigation decision, evidence gap, or messy dataset. The workspace context and uploaded files stay attached in the background.
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

            {loading ? <div className="text-[13px]" style={{ color: MUTED }}>{uploading ? "Uploading evidence before AGRO-AI reads it." : "AGRO-AI is reading evidence, history, and workspace context."}</div> : null}
            {error ? <div className="text-[13px]" style={{ color: "#A4492F" }}>{error}</div> : null}
          </div>

          <div className="border-t px-6 py-5" style={{ borderColor: BORDER }}>
            <div className="rounded-2xl px-4 py-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={onKeyDown}
                rows={3}
                placeholder="Message AGRO-AI or attach evidence"
                className="w-full resize-none border-0 bg-transparent text-[14px] outline-none"
                style={{ color: TEXT }}
              />
              {selectedFiles.length ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {selectedFiles.map((file, index) => (
                    <span key={`${file.name}-${index}`} className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-[12px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: TEXT }}>
                      {file.name}
                      <button type="button" onClick={() => removeFile(index)} aria-label={`Remove ${file.name}`}>
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="mt-4 flex items-center justify-between gap-3">
                <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2 text-[12px] font-semibold" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: TEXT }}>
                  <Paperclip className="h-4 w-4" />
                  Attach evidence
                  <input type="file" multiple accept=".csv,.xlsx,.xls,.pdf,.txt,.json,.geojson,.kml,.zip" onChange={onFilesSelected} className="hidden" />
                </label>
                <div className="flex items-center gap-3">
                  <div className="text-[12px]" style={{ color: MUTED }}>Enter to send. Shift + Enter for a new line.</div>
                  <PortalButton onClick={() => send()} disabled={loading}>{uploading ? "Uploading" : "Send"}</PortalButton>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
