import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { Download, FileText, Mail, MessageSquare, Plus, Search, Send, Trash2, UploadCloud, X } from "lucide-react";
import { API_BASE_URL, apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { currentLocale } from "../i18n";
import { LanguageSelector } from "./LanguageSelector";
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

type ConversationSummary = {
  id: string;
  title: string;
  workspace_id?: string;
  status?: string;
  preview?: string;
  message_count?: number;
  created_at?: string;
  updated_at?: string;
};

const LOCAL_THREADS_KEY = "agroai_intelligence_threads_v2";

const PROMPTS = [
  "What should I do with my data?",
  "Create an operator checklist.",
  "What evidence is missing?",
  "Generate a customer-ready report.",
];

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function safeText(value: unknown, fallback = ""): string {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return fallback;
    if (trimmed.startsWith("{") && (trimmed.includes("\"answer\"") || trimmed.includes("\"summary\""))) {
      try {
        const parsed = JSON.parse(trimmed);
        return safeText(parsed.answer || parsed.summary || parsed.message, fallback);
      } catch {
        return fallback || trimmed;
      }
    }
    return trimmed;
  }
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (typeof value === "object") {
    const row = value as AnyRecord;
    return safeText(row.answer || row.summary || row.message || row.content || row.executive_summary, fallback);
  }
  return fallback;
}

function localScope(workspaceId?: string) {
  return `${LOCAL_THREADS_KEY}:${workspaceId || "default"}`;
}

function readLocalThreads(workspaceId?: string): ConversationSummary[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(localScope(workspaceId)) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeLocalThreads(workspaceId: string | undefined, rows: ConversationSummary[]) {
  try {
    window.localStorage.setItem(localScope(workspaceId), JSON.stringify(rows.slice(0, 80)));
  } catch {
    // Best effort cache.
  }
}

function titleFromPrompt(prompt: string) {
  const clean = prompt.replace(/\s+/g, " ").trim();
  if (!clean) return "New chat";
  return clean.slice(0, 64) + (clean.length > 64 ? "…" : "");
}

function fileTypeLabel(file: File) {
  const lower = file.name.toLowerCase();
  if (lower.endsWith(".csv")) return "CSV";
  if (lower.endsWith(".xlsx") || lower.endsWith(".xls")) return "Spreadsheet";
  if (lower.endsWith(".pdf")) return "PDF";
  if (lower.endsWith(".txt") || lower.endsWith(".md")) return "Text";
  if (lower.endsWith(".json") || lower.endsWith(".geojson")) return "JSON";
  return file.type || "File";
}

function uploadMetadata(item: ChatFileImport) {
  const response = item.uploadResponse || {};
  const source = response.data_source || {};
  const job = response.job || {};
  const output = job.output_json || {};
  const preview = asArray(response.evidence_preview)[0] as AnyRecord | undefined;
  return {
    filename: item.filename,
    file_type: source.source_type || fileTypeLabel(item.file),
    size_bytes: item.size_bytes,
    content_type: item.content_type,
    import_status: item.status,
    rows_parsed: response.rows_parsed ?? output.rows_parsed,
    columns: response.columns || output.columns || source.metadata_json?.columns || [],
    parsed_preview: preview?.summary || preview?.title || source.raw_text?.slice?.(0, 900),
    warnings: response.warnings || output.warnings || [],
    data_source_id: source.id,
  };
}

function normalizeAssistantResponse(response: unknown): string {
  const payload = response && typeof response === "object" ? (response as AnyRecord) : {};
  const result = payload.result && typeof payload.result === "object" ? payload.result as AnyRecord : {};
  return safeText(result.answer || result.summary || payload.answer || payload.summary || payload.content || result.executive_summary, "I can help. Give me a field, file, irrigation question, compliance packet, or customer report request.");
}

function isReportIntent(text: string) {
  const normalized = text.toLowerCase();
  return ["report", "pdf", "document", "packet", "brief", "memo", "analysis", "export"].some((term) => normalized.includes(term));
}

function shouldAutoEmailReport(text: string) {
  const normalized = text.toLowerCase();
  return ["email", "send", "mail"].some((term) => normalized.includes(term)) && isReportIntent(normalized);
}

function buildReportTitle(question: string) {
  const clean = question.replace(/\s+/g, " ").trim().toLowerCase();
  if (clean.includes("customer")) return "AGRO-AI Customer-Ready Operating Report";
  if (clean.includes("compliance")) return "AGRO-AI Compliance Evidence Report";
  if (clean.includes("water")) return "AGRO-AI Water Use Intelligence Report";
  return "AGRO-AI Operating Report";
}

function reportFilename(title: string) {
  const safe = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") || "agroai-report";
  return `${safe}.pdf`;
}

function mapServerMessage(row: AnyRecord): AnyRecord {
  const metadata = row.metadata_json || row.artifacts_json || {};
  return {
    id: row.id,
    role: row.role,
    content: row.content,
    created_at: row.created_at,
    question: row.question || metadata.question,
    uploaded_evidence: row.uploaded_evidence || metadata.uploaded_evidence || [],
    artifact: row.artifact || metadata.artifact || null,
    agentic_actions: row.agentic_actions || metadata.agentic_actions || [],
    model_status: row.model_status || metadata.model_status,
  };
}

function actionRiskLabel(action: AnyRecord) {
  if (action.approval_required) return "Approval required";
  if (action.risk_level === "low") return "Ready";
  return `${safeText(action.risk_level, "medium")} risk`;
}

async function createReportPdf(payload: AnyRecord): Promise<Blob> {
  const token = window.localStorage.getItem("agroai_access_token");
  const headers = new Headers({ "Content-Type": "application/json" });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}/v1/intelligence/chat/report-pdf`, { method: "POST", headers, body: JSON.stringify(payload) });
  if (!response.ok) throw new Error((await response.text().catch(() => "")) || `Report export failed with status ${response.status}`);
  return response.blob();
}

async function emailReportPdf(payload: AnyRecord): Promise<AnyRecord> {
  const token = window.localStorage.getItem("agroai_access_token");
  const headers = new Headers({ "Content-Type": "application/json" });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}/v1/intelligence/chat/report-email`, { method: "POST", headers, body: JSON.stringify(payload) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.status === "not_sent") throw new Error(String(data?.delivery?.reason || data?.detail || `Report email failed with status ${response.status}`));
  return data;
}

async function planAgenticActions(payload: AnyRecord): Promise<AnyRecord[]> {
  try {
    const response = await apiClient.post("/v1/agents/actions/plan", payload) as AnyRecord;
    return Array.isArray(response.actions) ? response.actions : [];
  } catch {
    return [];
  }
}

async function executeAgenticAction(payload: AnyRecord): Promise<AnyRecord> {
  return apiClient.post("/v1/agents/actions/execute", payload) as Promise<AnyRecord>;
}

export function Intelligence() {
  const { currentWorkspace } = useAuth();
  const [messages, setMessages] = useState<AnyRecord[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState("");
  const [conversationSearch, setConversationSearch] = useState("");
  const [historyStatus, setHistoryStatus] = useState<"loading" | "server" | "local">("loading");
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [reportBusyId, setReportBusyId] = useState("");
  const [reportEmailBusyId, setReportEmailBusyId] = useState("");
  const [actionBusyId, setActionBusyId] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [fileImports, setFileImports] = useState<ChatFileImport[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const hasUploading = fileImports.some((item) => item.status === "uploading");
  const hasFailed = fileImports.some((item) => item.status === "failed");

  const filteredConversations = useMemo(() => {
    const search = conversationSearch.trim().toLowerCase();
    if (!search) return conversations;
    return conversations.filter((row) => `${row.title || ""} ${row.preview || ""}`.toLowerCase().includes(search));
  }, [conversations, conversationSearch]);

  async function refreshConversations() {
    setHistoryStatus("loading");
    try {
      const suffix = currentWorkspace?.id ? `?workspace_id=${encodeURIComponent(currentWorkspace.id)}` : "";
      const response = await apiClient.get(`/v1/intelligence/brain/conversations${suffix}`) as AnyRecord;
      setConversations(Array.isArray(response.conversations) ? response.conversations : []);
      setHistoryStatus("server");
    } catch {
      setConversations(readLocalThreads(currentWorkspace?.id));
      setHistoryStatus("local");
    }
  }

  useEffect(() => {
    setMessages([]);
    setActiveConversationId("");
    setFileImports([]);
    refreshConversations().catch(() => null);
  }, [currentWorkspace?.id]);

  function persistLocalThread(threadId: string, rows: AnyRecord[], title?: string) {
    const now = new Date().toISOString();
    const current = readLocalThreads(currentWorkspace?.id);
    const existing = current.find((row) => row.id === threadId) as AnyRecord | undefined;
    const nextThread = {
      id: threadId,
      title: title || existing?.title || titleFromPrompt(rows.find((row) => row.role === "user")?.content || "New chat"),
      workspace_id: currentWorkspace?.id,
      preview: safeText(rows[rows.length - 1]?.content).slice(0, 180),
      message_count: rows.length,
      created_at: existing?.created_at || now,
      updated_at: now,
      status: "local",
      messages: rows,
    } as AnyRecord;
    const next = [nextThread, ...current.filter((row) => row.id !== threadId)].slice(0, 80) as ConversationSummary[];
    writeLocalThreads(currentWorkspace?.id, next);
    setConversations(next);
  }

  function remember(rows: AnyRecord[]) {
    setMessages(rows);
    if (activeConversationId && (historyStatus !== "server" || activeConversationId.startsWith("local-"))) persistLocalThread(activeConversationId, rows);
  }

  async function createConversationIfNeeded(firstPrompt: string): Promise<string> {
    if (activeConversationId) return activeConversationId;
    if (historyStatus === "server") {
      try {
        const created = await apiClient.post("/v1/intelligence/brain/conversations", { title: titleFromPrompt(firstPrompt), workspace_id: currentWorkspace?.id, message: firstPrompt }) as AnyRecord;
        const conversation = created.conversation || created;
        const id = String(conversation.id || "");
        if (id) {
          setActiveConversationId(id);
          setConversations((current) => [conversation as ConversationSummary, ...current.filter((row) => row.id !== id)]);
          return id;
        }
      } catch {
        setHistoryStatus("local");
      }
    }
    const localId = `local-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setActiveConversationId(localId);
    persistLocalThread(localId, [], titleFromPrompt(firstPrompt));
    return localId;
  }

  async function loadConversation(conversationId: string) {
    setError("");
    setNotice("");
    setActiveConversationId(conversationId);
    if (conversationId.startsWith("local-") || historyStatus !== "server") {
      const row = readLocalThreads(currentWorkspace?.id).find((item: AnyRecord) => item.id === conversationId) as AnyRecord | undefined;
      setMessages(Array.isArray(row?.messages) ? row.messages : []);
      return;
    }
    try {
      const response = await apiClient.get(`/v1/intelligence/brain/conversations/${encodeURIComponent(conversationId)}`) as AnyRecord;
      setMessages(Array.isArray(response.messages) ? response.messages.map(mapServerMessage) : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load that chat.");
    }
  }

  async function deleteConversation(conversationId: string) {
    if (!conversationId) return;
    setError("");
    try {
      if (conversationId.startsWith("local-") || historyStatus !== "server") {
        const next = readLocalThreads(currentWorkspace?.id).filter((row) => row.id !== conversationId);
        writeLocalThreads(currentWorkspace?.id, next);
        setConversations(next);
      } else {
        await apiClient.remove(`/v1/intelligence/brain/conversations/${encodeURIComponent(conversationId)}`);
        await refreshConversations();
      }
      if (activeConversationId === conversationId) {
        setActiveConversationId("");
        setMessages([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete that chat.");
    }
  }

  function newChat() {
    setActiveConversationId("");
    setMessages([]);
    setQuestion("");
    setFileImports([]);
    setError("");
    setNotice("");
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
      updateImport(item.id, { status: "failed", error: err instanceof Error ? err.message : "Import failed" });
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
    return Promise.all(queued.map((item) => uploadFileImport(item)));
  }

  async function persistExchange(conversationId: string, content: string, output: string, metadata: AnyRecord, localRows: AnyRecord[]) {
    if (!conversationId || conversationId.startsWith("local-") || historyStatus !== "server") {
      persistLocalThread(conversationId || `local-${Date.now()}`, localRows, titleFromPrompt(content));
      return;
    }
    try {
      const response = await apiClient.post(`/v1/intelligence/brain/conversations/${encodeURIComponent(conversationId)}/messages`, { content, output, metadata }) as AnyRecord;
      if (response.conversation) {
        const updated = response.conversation as ConversationSummary;
        setConversations((current) => [updated, ...current.filter((row) => row.id !== updated.id)]);
      } else {
        await refreshConversations();
      }
    } catch {
      setHistoryStatus("local");
      persistLocalThread(conversationId, localRows, titleFromPrompt(content));
    }
  }

  function artifactFor(message: AnyRecord) {
    return message.artifact || { title: buildReportTitle(message.question || "AGRO-AI report"), question: message.question || "AGRO-AI report", answer: safeText(message.content), uploaded_evidence: message.uploaded_evidence || [] };
  }

  async function downloadReportFor(message: AnyRecord) {
    const artifact = artifactFor(message);
    const busyId = String(message.id || Date.now());
    setReportBusyId(busyId);
    setError("");
    setNotice("");
    try {
      const blob = await createReportPdf(artifact);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = reportFilename(String(artifact.title || "AGRO-AI Operating Report"));
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1200);
    } catch (err) {
      setError(err instanceof Error ? err.message : "AGRO-AI could not export the PDF report.");
    } finally {
      setReportBusyId("");
    }
  }

  async function emailReportFor(message: AnyRecord) {
    const artifact = artifactFor(message);
    const busyId = String(message.id || Date.now());
    setReportEmailBusyId(busyId);
    setError("");
    setNotice("");
    try {
      const result = await emailReportPdf(artifact);
      setNotice(`Report emailed to ${result.recipient || "your account email"}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "AGRO-AI could not email the PDF report.");
    } finally {
      setReportEmailBusyId("");
    }
  }

  async function runAction(message: AnyRecord, action: AnyRecord) {
    const actionId = String(action.id || `${message.id}-${action.action_type}`);
    setActionBusyId(actionId);
    setError("");
    setNotice("");
    try {
      const result = await executeAgenticAction({ action_type: action.action_type, workspace_id: currentWorkspace?.id, payload: action.payload || {}, approval_confirmed: Boolean(action.approval_required) });
      const next = messages.map((row) => String(row.id) === String(message.id) ? { ...row, agentic_actions: (row.agentic_actions || []).map((item: AnyRecord) => String(item.id) === actionId ? { ...item, execution_result: result, status: result.status || item.status } : item) } : row);
      remember(next);
      const created = result.created_task || result.created_approval_task;
      setNotice(created?.title ? `Action completed: ${created.title}` : `Action completed: ${safeText(result.action_type || action.action_type)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "AGRO-AI could not execute this action.");
    } finally {
      setActionBusyId("");
    }
  }

  async function send(prompt = question) {
    const clean = prompt.trim() || (fileImports.length ? "Summarize the files I imported." : "");
    if (!clean || loading || hasUploading || hasFailed) return;
    setQuestion("");
    setError("");
    setNotice("");
    setLoading(true);
    const conversationId = await createConversationIfNeeded(clean);
    const userMessage = { id: `user-${Date.now()}`, role: "user", content: clean };
    const withUser = [...messages, userMessage];
    setMessages(withUser);
    try {
      const importedBeforeSend = fileImports.filter((item) => item.status === "imported");
      const newlyImported = await ensureQueuedUploads();
      const evidence = [...importedBeforeSend, ...newlyImported].map(uploadMetadata);
      const history = withUser.filter((row) => row.role === "user" || row.role === "assistant").slice(-10).map((row) => ({ role: row.role, content: safeText(row.content).slice(0, 1800) }));
      const request = { task: isReportIntent(clean) ? "report_factory" as const : "chat" as const, question: clean, workspace_id: currentWorkspace?.id, audience: "operator", history, uploaded_evidence: evidence, preferred_language: currentLocale() } as AnyRecord;
      const response = await apiClient.intelligence.brainRun(request).catch(() => apiClient.intelligence.run(request)) as AnyRecord;
      const assistantText = normalizeAssistantResponse(response);
      const modelStatus = String(response.model_status || response.status || "");
      const degraded = modelStatus.includes("fallback") || modelStatus.includes("unavailable") || assistantText.toLowerCase().includes("could not reach a live model provider");
      const artifact = isReportIntent(clean) ? { kind: "pdf", title: buildReportTitle(clean), question: clean, answer: assistantText, uploaded_evidence: evidence } : null;
      let actions: AnyRecord[] = [];
      if (!degraded && /\b(task|checklist|follow[- ]?up|email|send|approval|action)\b/i.test(clean)) {
        actions = await planAgenticActions({ instruction: clean, workspace_id: currentWorkspace?.id, answer: assistantText, uploaded_evidence: evidence, audience: "operator" });
      }
      if (artifact && shouldAutoEmailReport(clean)) {
        const emailAction = actions.find((item) => item.action_type === "email_report_to_user" && !item.approval_required);
        if (emailAction) {
          try {
            const result = await executeAgenticAction({ action_type: emailAction.action_type, workspace_id: currentWorkspace?.id, payload: { ...emailAction.payload, ...artifact }, approval_confirmed: false });
            actions = actions.map((item) => item.id === emailAction.id ? { ...item, execution_result: result, status: result.status || "executed" } : item);
            if (result.status === "executed") setNotice(`Report emailed to ${result.recipient || "your account email"}.`);
          } catch {
            // Keep manual report buttons available.
          }
        }
      }
      const assistantMessage = { id: `assistant-${Date.now()}`, role: "assistant", content: assistantText, question: clean, uploaded_evidence: evidence, artifact, agentic_actions: actions, model_status: modelStatus };
      const nextRows = [...withUser, assistantMessage];
      setMessages(nextRows);
      const metadata = { question: clean, uploaded_evidence: evidence, artifact, agentic_actions: actions, model_status: modelStatus };
      await persistExchange(conversationId, clean, assistantText, metadata, nextRows);
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
      <main className="grid min-h-screen" style={{ gridTemplateColumns: sidebarOpen ? "300px minmax(0, 1fr)" : "minmax(0, 1fr)" }}>
        {sidebarOpen ? (
          <aside className="flex min-h-screen flex-col border-r p-4" style={{ background: SURFACE, borderColor: BORDER }}>
            <div className="flex items-center justify-between gap-3">
              <div className="text-[12px] font-semibold" style={{ color: TEXT }}>Ask AGRO-AI</div>
              <button type="button" onClick={() => setSidebarOpen(false)} className="rounded-lg p-2" style={{ border: `1px solid ${BORDER}`, color: MUTED }} title="Close sidebar"><X size={15} /></button>
            </div>
            <button type="button" onClick={newChat} className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-[12px] font-medium" style={{ background: "#0D2B1E", color: "white" }}><Plus size={14} /> New chat</button>
            <label className="mt-4 flex items-center gap-2 rounded-lg px-3 py-2" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>
              <Search size={14} />
              <input value={conversationSearch} onChange={(event) => setConversationSearch(event.target.value)} placeholder="Search chats" className="w-full bg-transparent text-[12px] outline-none" style={{ color: TEXT }} />
            </label>
            <div className="mt-5 text-[11px] font-semibold uppercase" style={{ color: MUTED }}>History</div>
            <div className="mt-3 flex-1 space-y-2 overflow-y-auto pr-1">
              {filteredConversations.map((row) => {
                const active = row.id === activeConversationId;
                return (
                  <div key={row.id} className="group flex gap-2">
                    <button type="button" onClick={() => loadConversation(row.id)} className="min-w-0 flex-1 rounded-xl px-3 py-3 text-left" style={{ background: active ? "#EEF8E8" : BG, border: `1px solid ${active ? "rgba(13,43,30,0.32)" : BORDER}` }}>
                      <div className="flex items-center gap-2"><MessageSquare size={13} style={{ color: active ? "#0D2B1E" : MUTED }} /><div className="truncate text-[12px] font-semibold" style={{ color: TEXT }}>{row.title || "New chat"}</div></div>
                      {row.preview ? <div className="mt-1 line-clamp-2 text-[11px] leading-4" style={{ color: MUTED }}>{row.preview}</div> : null}
                    </button>
                    <button type="button" onClick={() => deleteConversation(row.id)} className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-lg group-hover:flex" style={{ border: `1px solid ${BORDER}`, color: MUTED }} title="Delete chat"><Trash2 size={14} /></button>
                  </div>
                );
              })}
              {!filteredConversations.length ? <div className="rounded-lg p-3 text-[12px] leading-relaxed" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>{historyStatus === "loading" ? "Loading chats…" : "No saved chats yet."}</div> : null}
            </div>
            <div className="mt-4"><LanguageSelector compact /></div>
          </aside>
        ) : null}

        <section className="flex min-w-0 flex-col">
          <header className="px-8 py-6" style={{ background: "#0D2B1E", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="inline-flex rounded-full px-3 py-1 text-[11px] font-semibold" style={{ background: "rgba(255,255,255,0.12)", color: "white" }}>Workspace intelligence</div>
                <h1 className="mt-3 text-[28px] font-semibold tracking-tight" style={{ color: "white" }}>Ask AGRO-AI</h1>
                <p className="mt-2 max-w-2xl text-[13px] leading-relaxed" style={{ color: "rgba(255,255,255,0.68)" }}>Ask, import files, generate reports, create field tasks, record field updates, and prepare approval-gated operations.</p>
              </div>
              {!sidebarOpen ? <button type="button" onClick={() => setSidebarOpen(true)} className="rounded-lg px-3 py-2 text-[12px] font-medium" style={{ background: "rgba(255,255,255,0.12)", color: "white" }}><span className="inline-flex items-center gap-2"><FileText size={15} /> History</span></button> : null}
            </div>
          </header>

          <div className="flex-1 overflow-y-auto px-6 py-7">
            <div className="mx-auto max-w-[900px] space-y-5">
              {error ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: "#991B1B" }}>{error}</div> : null}
              {notice ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: "#0D2B1E" }}>{notice}</div> : null}
              {!messages.length && !loading ? (
                <section className="rounded-xl p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
                  <div className="text-[12px] font-semibold uppercase" style={{ color: MUTED }}>Start a workspace thread</div>
                  <h2 className="mt-3 text-[24px] font-semibold" style={{ color: TEXT }}>Ask a question or import files.</h2>
                  <p className="mt-2 max-w-2xl text-[14px] leading-relaxed" style={{ color: MUTED }}>AGRO-AI can save threads, reload past work, and move from answer to action: reports, email delivery, field tasks, field evidence, and approval-gated controller work.</p>
                  <div className="mt-5 flex flex-wrap gap-2">{PROMPTS.map((prompt) => <button key={prompt} type="button" onClick={() => send(prompt)} className="rounded-full px-3 py-2 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>{prompt}</button>)}</div>
                </section>
              ) : null}

              {messages.map((message, index) => {
                const actions = Array.isArray(message.agentic_actions) ? message.agentic_actions : [];
                return (
                  <div key={message.id || index} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                    <article className={message.role === "user" ? "max-w-[72%]" : "w-full max-w-[820px]"}>
                      <div className="rounded-2xl px-5 py-4 text-[15px] leading-7 whitespace-pre-wrap" style={{ background: message.role === "user" ? "#0D2B1E" : SURFACE, color: message.role === "user" ? "white" : TEXT, border: `1px solid ${message.role === "user" ? "#0D2B1E" : BORDER}` }}>
                        {safeText(message.content)}
                        {message.role === "assistant" && message.artifact ? (
                          <div className="mt-4 flex flex-wrap gap-2 whitespace-normal">
                            <button type="button" onClick={() => downloadReportFor(message)} disabled={reportBusyId === String(message.id || index)} className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-semibold disabled:opacity-60" style={{ background: "#0D2B1E", color: "white" }}>{reportBusyId === String(message.id || index) ? <FileText size={15} /> : <Download size={15} />}{reportBusyId === String(message.id || index) ? "Preparing PDF…" : "Download PDF"}</button>
                            <button type="button" onClick={() => emailReportFor(message)} disabled={reportEmailBusyId === String(message.id || index)} className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-semibold disabled:opacity-60" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}><Mail size={15} />{reportEmailBusyId === String(message.id || index) ? "Sending…" : "Email to me"}</button>
                          </div>
                        ) : null}
                        {message.role === "assistant" && actions.length ? (
                          <div className="mt-4 space-y-2 whitespace-normal">
                            {actions.map((action: AnyRecord) => {
                              const actionId = String(action.id || `${message.id}-${action.action_type}`);
                              const executed = action.execution_result || ["executed", "approval_recorded"].includes(String(action.status));
                              return (
                                <div key={actionId} className="rounded-xl p-3" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                                  <div className="flex items-start justify-between gap-3">
                                    <div>
                                      <div className="text-[13px] font-semibold" style={{ color: TEXT }}>{safeText(action.title || action.action_type)}</div>
                                      <div className="mt-1 text-[12px] leading-relaxed" style={{ color: MUTED }}>{safeText(action.description)}</div>
                                      <div className="mt-2 text-[11px] font-semibold" style={{ color: action.approval_required ? "#92400E" : "#0D2B1E" }}>{actionRiskLabel(action)}</div>
                                    </div>
                                    <button type="button" onClick={() => runAction(message, action)} disabled={executed || actionBusyId === actionId} className="shrink-0 rounded-lg px-3 py-2 text-[12px] font-semibold disabled:opacity-50" style={{ background: action.approval_required ? "#92400E" : "#0D2B1E", color: "white" }}>{executed ? "Done" : actionBusyId === actionId ? "Working…" : action.approval_required ? "Create approval" : "Do it"}</button>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        ) : null}
                      </div>
                    </article>
                  </div>
                );
              })}
              {loading ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: MUTED }}>Preparing the answer…</div> : null}
            </div>
          </div>

          <footer className="px-6 pb-6">
            <div className="mx-auto max-w-[900px] rounded-2xl p-4 shadow-[0_18px_60px_rgba(16,35,27,0.08)]" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              {fileImports.length ? <div className="mb-3 flex flex-wrap gap-2">{fileImports.map((item) => <div key={item.id} className="flex items-center gap-2 rounded-full px-3 py-2 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}><span className="max-w-[180px] truncate font-medium">{item.filename}</span><span style={{ color: item.status === "failed" ? "#991B1B" : MUTED }}>{item.status === "queued" ? "Queued" : item.status === "uploading" ? "Uploading…" : item.status === "imported" ? "Imported" : "Failed"}</span><button type="button" onClick={() => setFileImports((current) => current.filter((row) => row.id !== item.id))} title="Remove"><X size={13} /></button></div>)}</div> : null}
              {hasFailed ? <div className="mb-3 text-[12px]" style={{ color: "#991B1B" }}>One file failed to import. Remove it before sending.</div> : null}
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
