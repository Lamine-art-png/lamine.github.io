import { KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, PanelLeftClose, PanelLeftOpen, RotateCcw, Send, Trash2, UploadCloud, X } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, MUTED, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;

type ChatFileImport = {
  id: string;
  file: File;
  filename: string;
  size_bytes: number;
  content_type: string;
  status: "queued" | "uploading" | "imported" | "failed";
  error?: string;
  uploadResponse?: AnyRecord;
};

const PROMPTS = [
  "Generate a customer-ready report from this workspace.",
  "What have you been checking?",
  "Which fields need attention and why?",
  "What evidence is still missing?",
  "Create an operator checklist.",
  "Draft an owner update.",
];

const SIDEBAR_KEY = "agroai_chat_sidebar_collapsed";
const MEMORY_KEY = "agroai_chat_memory_v2";

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function tryJson(value: string): AnyRecord | null {
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as AnyRecord : null;
  } catch {
    return null;
  }
}

function rescueJsonField(value: string, key: string) {
  const match = value.match(new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)`, "s"));
  if (!match) return "";
  try {
    return JSON.parse(`"${match[1]}"`);
  } catch {
    return match[1].replace(/\\n/g, "\n").replace(/\\"/g, "\"").trim();
  }
}

function humanText(value: unknown, fallback = ""): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed || trimmed === "structured model JSON" || trimmed === "structured model JSON object") return fallback;
    const parsed = tryJson(trimmed);
    if (parsed) return humanText(parsed.answer || parsed.summary || parsed.message || parsed.content || "", fallback);
    if (trimmed.startsWith("{") || (trimmed.includes("{") && (trimmed.includes("\"summary\"") || trimmed.includes("\"answer\"")))) {
      return rescueJsonField(trimmed, "answer") || rescueJsonField(trimmed, "summary") || fallback;
    }
    return trimmed.replaceAll("structured model JSON object", "").replaceAll("structured model JSON", "").trim() || fallback;
  }
  if (typeof value === "object") {
    const row = value as AnyRecord;
    return humanText(row.answer || row.summary || row.message || row.content || row.recommendation || row.next_step || row.why || "", fallback);
  }
  return fallback;
}

function readableLabel(value: unknown) {
  const raw = humanText(value, "").trim();
  const replacements: Record<string, string> = {
    compliance_water_accounting: "compliance water accounting data",
    field_intelligence: "field intelligence records",
    readiness_summary: "readiness summary",
    "live WiseConn credentials": "WiseConn connection",
    "live Talgil credentials": "Talgil connection",
    "confirmed live telemetry stream": "confirmed live telemetry",
  };
  return replacements[raw] || raw.replaceAll("_", " ");
}

function cleanHistory(rows: AnyRecord[]) {
  return rows
    .filter((row) => row.role === "user" || row.role === "assistant")
    .slice(-8)
    .map((row) => ({ role: row.role === "assistant" ? "assistant" : "user", content: humanText(row.content).slice(0, 1400) }))
    .filter((row) => row.content.trim());
}

function memoryScope(workspaceId?: string) {
  return `${MEMORY_KEY}:${workspaceId || "default"}`;
}

function readMemory(workspaceId?: string): Record<string, AnyRecord[]> {
  try {
    return JSON.parse(localStorage.getItem(memoryScope(workspaceId)) || "{}");
  } catch {
    return {};
  }
}

function writeConversationMemory(workspaceId: string | undefined, conversationId: string, rows: AnyRecord[]) {
  const memory = readMemory(workspaceId);
  memory[conversationId] = rows.map((row) => ({
    id: row.id,
    role: row.role,
    content: humanText(row.content),
    details: row.details,
    showDetails: row.showDetails,
    saved_at: new Date().toISOString(),
  })).slice(-40);
  localStorage.setItem(memoryScope(workspaceId), JSON.stringify(memory));
}

function fileTypeLabel(file: File) {
  const lower = file.name.toLowerCase();
  if (lower.endsWith(".csv")) return "CSV";
  if (lower.endsWith(".xlsx") || lower.endsWith(".xls")) return "Spreadsheet";
  if (lower.endsWith(".pdf")) return "PDF";
  if (lower.endsWith(".txt") || lower.endsWith(".md")) return "Text";
  if (lower.endsWith(".json") || lower.endsWith(".geojson")) return "JSON";
  if (lower.endsWith(".kml")) return "Geospatial";
  if (lower.endsWith(".zip")) return "Archive";
  return file.type || "File";
}

function uploadMetadata(item: ChatFileImport) {
  const response = item.uploadResponse || {};
  const source = response.data_source || {};
  const job = response.job || {};
  const output = job.output_json || {};
  const rows = response.rows_parsed ?? output.rows_parsed;
  const columns = response.columns || output.columns || source.metadata_json?.columns || [];
  const preview = asArray(response.evidence_preview)[0] as AnyRecord | undefined;
  return {
    filename: item.filename,
    file_type: source.source_type || fileTypeLabel(item.file),
    size_bytes: item.size_bytes,
    content_type: item.content_type,
    import_status: item.status,
    rows_parsed: rows,
    columns,
    parsed_preview: preview?.summary || preview?.title || source.raw_text?.slice?.(0, 900),
    raw_text_preview: source.raw_text?.slice?.(0, 900),
    warnings: response.warnings || output.warnings || [],
    data_source_id: source.id,
  };
}

function shouldShowDetails(question: string, details: AnyRecord) {
  const q = question.toLowerCase();
  if (q.includes("missing") || q.includes("evidence") || q.includes("why")) return true;
  if (q.includes("how much water") || q.includes("irrigat") || q.includes("compliance") || q.includes("diagnose") || q.includes("report")) {
    return asArray(details.missing).length > 0 || asArray(details.risks).length > 0;
  }
  return false;
}

function normalizeAssistantResponse(response: unknown, question: string): AnyRecord {
  const payload = response && typeof response === "object" ? (response as AnyRecord) : {};
  const result = payload.result && typeof payload.result === "object" ? payload.result as AnyRecord : {};
  const answer = humanText(result.answer || result.summary || payload.answer || payload.summary || payload.content || result.executive_summary, "I can help. Ask about a field, file, irrigation decision, compliance packet, or customer account.");
  const details = {
    missing: asArray(result.missing_evidence || result.missing_data || payload.missing_data).map(readableLabel).filter(Boolean),
    risks: asArray(result.risk_flags || result.risks || payload.verification?.risk_flags).map(readableLabel).filter(Boolean),
    next: asArray(result.next_actions || result.recommendations || result.recommended_next_actions).map(readableLabel).filter(Boolean),
    citations: asArray(payload.citations || result.citations),
  };
  return { id: `assistant-${Date.now()}`, role: "assistant", content: answer, details, showDetails: shouldShowDetails(question, details) };
}

function DetailDisclosure({ details, defaultOpen = false }: { details: AnyRecord; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const rows = [
    ["What may limit this answer", asArray(details.missing)],
    ["Recommended follow-up", asArray(details.next)],
    ["Citations", asArray(details.citations).map((item) => (item && typeof item === "object" ? (item as AnyRecord).title || (item as AnyRecord).source_type : item))],
  ].filter(([, items]) => (items as unknown[]).length);
  if (!rows.length) return null;
  return (
    <div className="mt-3">
      <button type="button" onClick={() => setOpen(!open)} className="inline-flex items-center gap-1 text-[12px] font-medium" style={{ color: MUTED }}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        Why this answer may be limited
      </button>
      {open ? (
        <div className="mt-2 rounded-lg p-3 text-[12px] leading-relaxed" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: MUTED }}>
          {rows.map(([title, items]) => (
            <div key={title as string} className="mb-2 last:mb-0">
              <div className="font-semibold" style={{ color: TEXT }}>{title as string}</div>
              {(items as unknown[]).slice(0, 5).map((item, index) => <div key={index}>- {readableLabel(item)}</div>)}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function InlineState({ title }: { title: string }) {
  return <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: MUTED }}>{title}</div>;
}

export function Intelligence() {
  const { currentWorkspace } = useAuth();
  const conversationState = usePortalResource<{ conversations: AnyRecord[] }>(useCallback(() => apiClient.conversations.list(), []));
  const [conversationId, setConversationId] = useState("");
  const [messages, setMessages] = useState<AnyRecord[]>([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingCopy, setLoadingCopy] = useState("Preparing answer...");
  const [error, setError] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem(SIDEBAR_KEY) === "true");
  const [fileImports, setFileImports] = useState<ChatFileImport[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const conversations = conversationState.data?.conversations || [];
  const hasUploading = fileImports.some((item) => item.status === "uploading");
  const hasFailed = fileImports.some((item) => item.status === "failed");

  useEffect(() => localStorage.setItem(SIDEBAR_KEY, sidebarCollapsed ? "true" : "false"), [sidebarCollapsed]);

  const loadConversation = useCallback(async (id: string) => {
    setConversationId(id);
    setError("");
    const localRows = readMemory(currentWorkspace?.id)[id];
    if (localRows?.length) {
      setMessages(localRows);
      return;
    }
    const response = await apiClient.conversations.get(id) as AnyRecord;
    setMessages(asArray(response.messages).map((message) => ({ ...(message as AnyRecord), content: humanText((message as AnyRecord).content) })) as AnyRecord[]);
  }, [currentWorkspace?.id]);

  useEffect(() => {
    if (!conversationId && conversations[0]?.id && messages.length === 0) loadConversation(String(conversations[0].id)).catch(() => null);
  }, [conversationId, conversations, loadConversation, messages.length]);

  async function newChat() {
    setConversationId("");
    setMessages([]);
    setQuestion("");
    setError("");
    setFileImports([]);
  }

  async function deleteConversation(id: string) {
    const memory = readMemory(currentWorkspace?.id);
    delete memory[id];
    localStorage.setItem(memoryScope(currentWorkspace?.id), JSON.stringify(memory));
    await apiClient.conversations.delete(id).catch(() => null);
    if (conversationId === id) await newChat();
    await conversationState.refresh().catch(() => null);
  }

  function updateImport(id: string, patch: Partial<ChatFileImport>) {
    setFileImports((current) => current.map((item) => item.id === id ? { ...item, ...patch } : item));
  }

  async function uploadFileImport(item: ChatFileImport) {
    updateImport(item.id, { status: "uploading", error: "" });
    try {
      const response = await apiClient.evidence.upload(item.file, undefined, currentWorkspace?.id) as AnyRecord;
      const imported = { ...item, status: "imported" as const, uploadResponse: response, error: "" };
      updateImport(item.id, { status: "imported", uploadResponse: response, error: "" });
      return imported;
    } catch (err) {
      updateImport(item.id, { status: "failed", error: err instanceof Error ? err.message : "Import failed." });
      throw err;
    }
  }

  function onFilesSelected(files: FileList | null) {
    const next = Array.from(files || []).map((file) => ({ id: `${file.name}-${file.size}-${Date.now()}-${Math.random().toString(16).slice(2)}`, file, filename: file.name, size_bytes: file.size, content_type: file.type || "application/octet-stream", status: "queued" as const }));
    if (!next.length) return;
    setFileImports((current) => [...current, ...next]);
    next.forEach((item) => uploadFileImport(item).catch(() => null));
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function ensureQueuedUploads() {
    const queued = fileImports.filter((item) => item.status === "queued");
    if (!queued.length) return [];
    setLoadingCopy("Importing files...");
    return Promise.all(queued.map((item) => uploadFileImport(item)));
  }

  async function persistChat(userText: string, assistantText: string, rows: AnyRecord[]) {
    try {
      let activeId = conversationId;
      if (!activeId) {
        const response = await apiClient.conversations.create({ title: userText.slice(0, 80), workspace_id: currentWorkspace?.id }) as AnyRecord;
        activeId = String(response.conversation?.id || response.id || "");
        if (activeId) setConversationId(activeId);
      }
      if (activeId) {
        writeConversationMemory(currentWorkspace?.id, activeId, rows);
        await apiClient.post(`/v1/intelligence/chat/conversations/${encodeURIComponent(activeId)}/messages`, { content: userText, output: assistantText }).catch(() => null);
      }
      await conversationState.refresh().catch(() => null);
    } catch {
      return;
    }
  }

  async function send(prompt = question) {
    const clean = prompt.trim() || (fileImports.length ? "Summarize the files I imported." : "");
    if (!clean || hasUploading || hasFailed || loading) return;
    setQuestion("");
    setLoading(true);
    setLoadingCopy(fileImports.some((item) => item.status === "queued") ? "Importing files..." : "Reading your request...");
    setError("");
    const userMessage = { id: `user-${Date.now()}`, role: "user", content: clean };
    setMessages((current) => [...current, userMessage]);
    try {
      const importedBeforeSend = fileImports.filter((item) => item.status === "imported");
      const newlyImported = await ensureQueuedUploads();
      const imported = [...importedBeforeSend, ...newlyImported];
      const evidence = imported.map(uploadMetadata);
      const history = cleanHistory([...messages, userMessage]);
      setLoadingCopy("Preparing answer...");
      const request = { task: "chat" as const, question: clean, workspace_id: currentWorkspace?.id, audience: "operator", history, uploaded_evidence: evidence };
      const response = await apiClient.intelligence.brainRun(request).catch(() => apiClient.intelligence.run(request)) as AnyRecord;
      const assistantMessage = normalizeAssistantResponse(response, clean);
      const nextRows = [...messages, userMessage, assistantMessage];
      setMessages(nextRows);
      await persistChat(clean, humanText(assistantMessage.content), nextRows);
      setFileImports([]);
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

  const sendDisabled = loading || hasUploading || hasFailed || (!question.trim() && !fileImports.length);

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <main className="grid min-h-screen" style={{ gridTemplateColumns: sidebarCollapsed ? "72px minmax(0, 1fr)" : "300px minmax(0, 1fr)" }}>
        <aside className="border-r p-4 transition-all" style={{ background: SURFACE, borderColor: BORDER }}>
          <div className="flex items-center justify-between gap-2">
            {!sidebarCollapsed ? <div className="text-[12px] font-semibold" style={{ color: TEXT }}>Ask AGRO-AI</div> : null}
            <button type="button" className="rounded-lg p-2" style={{ border: `1px solid ${BORDER}`, color: TEXT }} onClick={() => setSidebarCollapsed(!sidebarCollapsed)} title={sidebarCollapsed ? "Expand history" : "Collapse history"}>{sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}</button>
          </div>
          <button type="button" onClick={newChat} className="mt-4 w-full rounded-lg px-3 py-2 text-[12px] font-medium" style={{ background: "#0D2B1E", color: "white" }}>{sidebarCollapsed ? "+" : "New chat"}</button>
          {!sidebarCollapsed ? (
            <>
              <div className="mt-6 text-[11px] font-semibold uppercase" style={{ color: MUTED }}>History</div>
              <div className="mt-3 space-y-2">
                {conversations.map((conversation) => (
                  <div key={conversation.id} className="group rounded-lg p-2" style={{ background: conversationId === String(conversation.id) ? BG : "transparent", border: `1px solid ${BORDER}` }}>
                    <button type="button" onClick={() => loadConversation(String(conversation.id))} className="w-full text-left">
                      <div className="truncate text-[13px] font-medium" style={{ color: TEXT }}>{conversation.title || "Conversation"}</div>
                      <div className="mt-1 text-[11px]" style={{ color: MUTED }}>{conversation.updated_at ? new Date(conversation.updated_at).toLocaleDateString() : "Recent"}</div>
                    </button>
                    <button type="button" onClick={() => deleteConversation(String(conversation.id))} className="mt-2 inline-flex items-center gap-1 text-[11px]" style={{ color: MUTED }}><Trash2 size={12} /> Delete</button>
                  </div>
                ))}
                {!conversations.length ? <div className="text-[12px]" style={{ color: MUTED }}>No conversations yet.</div> : null}
              </div>
            </>
          ) : null}
        </aside>

        <section className="flex min-w-0 flex-col">
          <header className="px-8 py-6" style={{ background: "#0D2B1E", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
            <div className="inline-flex rounded-full px-3 py-1 text-[11px] font-semibold" style={{ background: "rgba(255,255,255,0.12)", color: "white" }}>Workspace intelligence</div>
            <h1 className="mt-3 text-[28px] font-semibold tracking-tight" style={{ color: "white" }}>Ask AGRO-AI</h1>
            <p className="mt-2 max-w-2xl text-[13px] leading-relaxed" style={{ color: "rgba(255,255,255,0.68)" }}>Ask operational questions, import files, and turn workspace context into clear next steps.</p>
          </header>

          <div className="flex-1 overflow-y-auto px-6 py-7">
            <div className="mx-auto max-w-[900px] space-y-5">
              {error ? <InlineState title={error} /> : null}
              {!messages.length && !loading ? (
                <section className="rounded-xl p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
                  <div className="text-[12px] font-semibold uppercase" style={{ color: MUTED }}>Start a workspace thread</div>
                  <h2 className="mt-3 text-[24px] font-semibold" style={{ color: TEXT }}>Ask a question or import files.</h2>
                  <p className="mt-2 max-w-2xl text-[14px] leading-relaxed" style={{ color: MUTED }}>AGRO-AI can summarize uploaded records, explain field priorities, draft operator checklists, and identify what is needed before a defensible recommendation.</p>
                  <div className="mt-5 flex flex-wrap gap-2">{PROMPTS.map((prompt) => <button key={prompt} type="button" onClick={() => send(prompt)} className="rounded-full px-3 py-2 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>{prompt}</button>)}</div>
                </section>
              ) : null}
              {messages.map((message, index) => (
                <div key={message.id || index} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                  <article className={message.role === "user" ? "max-w-[72%]" : "w-full max-w-[820px]"}>
                    <div className="rounded-2xl px-5 py-4 text-[15px] leading-7 whitespace-pre-wrap" style={{ background: message.role === "user" ? "#0D2B1E" : SURFACE, color: message.role === "user" ? "white" : TEXT, border: `1px solid ${message.role === "user" ? "#0D2B1E" : BORDER}` }}>{humanText(message.content)}</div>
                    {message.role === "assistant" && message.showDetails ? <DetailDisclosure details={message.details || {}} /> : null}
                  </article>
                </div>
              ))}
              {loading ? <InlineState title={loadingCopy} /> : null}
            </div>
          </div>

          <footer className="px-6 pb-6">
            <div className="mx-auto max-w-[900px] rounded-2xl p-4 shadow-[0_18px_60px_rgba(16,35,27,0.08)]" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              {fileImports.length ? <div className="mb-3 flex flex-wrap gap-2">{fileImports.map((item) => <div key={item.id} className="flex items-center gap-2 rounded-full px-3 py-2 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}><span className="max-w-[180px] truncate font-medium">{item.filename}</span><span style={{ color: item.status === "failed" ? "#991B1B" : MUTED }}>{item.status === "queued" ? "Queued" : item.status === "uploading" ? "Uploading..." : item.status === "imported" ? "Imported" : "Failed"}</span>{item.status === "failed" ? <button type="button" onClick={() => uploadFileImport(item).catch(() => null)} title="Retry"><RotateCcw size={13} /></button> : null}<button type="button" onClick={() => setFileImports((current) => current.filter((row) => row.id !== item.id))} title="Remove"><X size={13} /></button></div>)}</div> : null}
              {hasFailed ? <div className="mb-3 text-[12px]" style={{ color: "#991B1B" }}>One file failed to import. Retry or remove it before sending.</div> : null}
              <div className="flex gap-3">
                <button type="button" onClick={() => fileInputRef.current?.click()} className="inline-flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-medium" style={{ border: `1px solid ${BORDER}`, color: TEXT }}><UploadCloud size={15} /> Import files</button>
                <input ref={fileInputRef} type="file" multiple className="hidden" accept=".csv,.xlsx,.xls,.pdf,.txt,.md,.json,.geojson,.kml,.zip" onChange={(event) => onFilesSelected(event.target.files)} />
                <textarea value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={onKeyDown} rows={2} placeholder="Ask AGRO-AI or import files" className="min-h-[48px] flex-1 resize-none rounded-lg px-4 py-3 text-[14px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
                <button type="button" disabled={sendDisabled} onClick={() => send()} className="inline-flex h-[48px] w-[52px] shrink-0 items-center justify-center rounded-lg disabled:opacity-50" style={{ background: "#0D2B1E", color: "white" }} title="Send"><Send size={18} /></button>
              </div>
              <div className="mt-3 text-[11px]" style={{ color: MUTED }}>Enter to send. Shift + Enter for a new line.</div>
            </div>
          </footer>
        </section>
      </main>
    </div>
  );
}
