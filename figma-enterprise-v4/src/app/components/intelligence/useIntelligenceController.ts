import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "../../auth/AuthProvider";
import { formatTranslation } from "../../i18n";
import { useLocale } from "../../hooks/useLocale";
import {
  AnyRecord,
  ChatFileImport,
  ConversationSummary,
  PROMPT_KEYS,
  buildReportTitle,
  isLanguageGenerationFailed,
  isReportIntent,
  mapServerMessage,
  normalizeAssistantResponse,
  readLocalThreads,
  reportFilename,
  safeText,
  shouldAutoEmailReport,
  titleFromPrompt,
  uploadMetadata,
  writeLocalThreads,
} from "./intelligenceSupport";

export type IntelligenceDependencies = {
  createReportPdf: (payload: AnyRecord) => Promise<Blob>;
  emailReportPdf: (payload: AnyRecord) => Promise<AnyRecord>;
  listConversations: (workspaceId?: string) => Promise<AnyRecord>;
  createConversation: (payload: AnyRecord) => Promise<AnyRecord>;
  getConversation: (conversationId: string) => Promise<AnyRecord>;
  deleteConversation: (conversationId: string) => Promise<unknown>;
  persistExchange: (conversationId: string, payload: AnyRecord) => Promise<AnyRecord>;
  runIntelligence: (request: AnyRecord) => Promise<AnyRecord>;
  uploadEvidence: (file: File, workspaceId?: string) => Promise<AnyRecord>;
  planActions: (payload: AnyRecord) => Promise<AnyRecord[]>;
  executeAction: (payload: AnyRecord) => Promise<AnyRecord>;
};

export function useIntelligenceController(deps: IntelligenceDependencies) {
  const { createReportPdf, emailReportPdf } = deps;
  const { currentWorkspace } = useAuth();
  const { t, normalizedLocale } = useLocale();
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
  const [failedPrompt, setFailedPrompt] = useState("");
  const [fileImports, setFileImports] = useState<ChatFileImport[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const hasUploading = fileImports.some((item) => item.status === "uploading");
  const hasFailed = fileImports.some((item) => item.status === "failed");
  const prompts = useMemo(() => PROMPT_KEYS.map((key) => t(key)), [normalizedLocale]);
  const filteredConversations = useMemo(() => {
    const search = conversationSearch.trim().toLowerCase();
    if (!search) return conversations;
    return conversations.filter((row) => `${row.title || ""} ${row.preview || ""}`.toLowerCase().includes(search));
  }, [conversations, conversationSearch]);

  function riskLabel(action: AnyRecord) {
    if (action.approval_required) return t("intelligence.approvalRequired");
    if (action.risk_level === "low") return t("intelligence.riskReady");
    return formatTranslation(t("intelligence.riskLabel"), { level: safeText(action.risk_level, "medium") });
  }

  async function refreshConversations() {
    setHistoryStatus("loading");
    try {
      const response = await deps.listConversations(currentWorkspace?.id);
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
    setFailedPrompt("");
    refreshConversations().catch(() => null);
  }, [currentWorkspace?.id]);

  function persistLocalThread(threadId: string, rows: AnyRecord[], title?: string) {
    const now = new Date().toISOString();
    const current = readLocalThreads(currentWorkspace?.id);
    const existing = current.find((row) => row.id === threadId) as AnyRecord | undefined;
    const fallback = t("intelligence.newChat");
    const nextThread = {
      id: threadId,
      title: title || existing?.title || titleFromPrompt(rows.find((row) => row.role === "user")?.content || fallback, fallback),
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
        const created = await deps.createConversation({
          title: titleFromPrompt(firstPrompt, t("intelligence.newChat")),
          workspace_id: currentWorkspace?.id,
          message: firstPrompt,
        });
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
    persistLocalThread(localId, [], titleFromPrompt(firstPrompt, t("intelligence.newChat")));
    return localId;
  }

  async function loadConversation(conversationId: string) {
    setError(""); setNotice(""); setFailedPrompt(""); setActiveConversationId(conversationId);
    if (conversationId.startsWith("local-") || historyStatus !== "server") {
      const row = readLocalThreads(currentWorkspace?.id).find((item: AnyRecord) => item.id === conversationId) as AnyRecord | undefined;
      setMessages(Array.isArray(row?.messages) ? row.messages : []);
      return;
    }
    try {
      const response = await deps.getConversation(conversationId);
      setMessages(Array.isArray(response.messages) ? response.messages.map(mapServerMessage) : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("intelligence.retryState"));
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
        await deps.deleteConversation(conversationId);
        await refreshConversations();
      }
      if (activeConversationId === conversationId) { setActiveConversationId(""); setMessages([]); }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("intelligence.retryState"));
    }
  }

  function newChat() {
    setActiveConversationId(""); setMessages([]); setQuestion(""); setFileImports([]); setError(""); setNotice(""); setFailedPrompt("");
  }
  function updateImport(id: string, patch: Partial<ChatFileImport>) {
    setFileImports((current) => current.map((item) => item.id === id ? { ...item, ...patch } : item));
  }
  async function uploadFileImport(item: ChatFileImport) {
    updateImport(item.id, { status: "uploading", error: "" });
    try {
      const response = await deps.uploadEvidence(item.file, currentWorkspace?.id);
      const imported = { ...item, status: "imported" as const, uploadResponse: response, error: "" };
      updateImport(item.id, { status: "imported", uploadResponse: response, error: "" });
      return imported;
    } catch (err) {
      updateImport(item.id, { status: "failed", error: err instanceof Error ? err.message : t("intelligence.importFailed") });
      throw err;
    }
  }
  function onFilesSelected(files: FileList | null) {
    const next = Array.from(files || []).map((file) => ({
      id: `${file.name}-${file.size}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      file,
      filename: file.name,
      size_bytes: file.size,
      content_type: file.type || "application/octet-stream",
      status: "queued" as const,
    }));
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
      persistLocalThread(conversationId || `local-${Date.now()}`, localRows, titleFromPrompt(content, t("intelligence.newChat")));
      return;
    }
    try {
      const response = await deps.persistExchange(conversationId, { content, output, metadata });
      if (response.conversation) {
        const updated = response.conversation as ConversationSummary;
        setConversations((current) => [updated, ...current.filter((row) => row.id !== updated.id)]);
      } else {
        await refreshConversations();
      }
    } catch {
      setHistoryStatus("local");
      persistLocalThread(conversationId, localRows, titleFromPrompt(content, t("intelligence.newChat")));
    }
  }
  function artifactFor(message: AnyRecord) {
    return message.artifact || {
      title: buildReportTitle(message.question || "AGRO-AI report"),
      question: message.question || "AGRO-AI report",
      answer: safeText(message.content),
      uploaded_evidence: message.uploaded_evidence || [],
    };
  }
  async function downloadReportFor(message: AnyRecord) {
    const artifact = artifactFor(message);
    const busyId = String(message.id || Date.now());
    setReportBusyId(busyId); setError("");
    try {
      const blob = await createReportPdf(artifact);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = reportFilename(String(artifact.title || "AGRO-AI Operating Report"));
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1200);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("intelligence.pdfExportFailed"));
    } finally { setReportBusyId(""); }
  }
  async function emailReportFor(message: AnyRecord) {
    const artifact = artifactFor(message);
    const busyId = String(message.id || Date.now());
    setReportEmailBusyId(busyId); setError("");
    try {
      const result = await emailReportPdf(artifact);
      setNotice(formatTranslation(t("intelligence.reportEmailed"), { recipient: result.recipient || t("intelligence.accountEmail") }));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("intelligence.pdfEmailFailed"));
    } finally { setReportEmailBusyId(""); }
  }
  async function runAction(message: AnyRecord, action: AnyRecord) {
    const actionId = String(action.id || `${message.id}-${action.action_type}`);
    setActionBusyId(actionId); setError("");
    try {
      const result = await deps.executeAction({ action_type: action.action_type, workspace_id: currentWorkspace?.id, payload: action.payload || {}, approval_confirmed: Boolean(action.approval_required) });
      const next = messages.map((row) => String(row.id) === String(message.id) ? {
        ...row,
        agentic_actions: (row.agentic_actions || []).map((item: AnyRecord) => String(item.id) === actionId ? { ...item, execution_result: result, status: result.status || item.status } : item),
      } : row);
      remember(next);
      const created = result.created_task || result.created_approval_task;
      setNotice(formatTranslation(t("intelligence.actionCompleted"), { title: created?.title || safeText(result.action_type || action.action_type) }));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("intelligence.actionExecuteFailed"));
    } finally { setActionBusyId(""); }
  }

  async function send(prompt = question, options: { retry?: boolean } = {}) {
    const clean = prompt.trim() || (fileImports.length ? t("intelligence.summarizeImportedFiles") : "");
    if (!clean || loading || hasUploading || hasFailed) return;
    setQuestion(""); setError(""); setNotice(""); setFailedPrompt(""); setLoading(true);
    const conversationId = await createConversationIfNeeded(clean);
    const priorRows = messages;
    const last = priorRows[priorRows.length - 1];
    const reuseLastUser = Boolean(options.retry && last?.role === "user" && safeText(last.content) === clean);
    const userMessage = reuseLastUser ? last : { id: `user-${Date.now()}`, role: "user", content: clean };
    const withUser = reuseLastUser ? priorRows : [...priorRows, userMessage];
    setMessages(withUser);
    try {
      const importedBeforeSend = fileImports.filter((item) => item.status === "imported");
      const newlyImported = await ensureQueuedUploads();
      const evidence = [...importedBeforeSend, ...newlyImported].map(uploadMetadata);
      const history = priorRows.filter((row) => row.role === "user" || row.role === "assistant").slice(-12).map((row) => ({ role: row.role, content: safeText(row.content).slice(0, 2200) }));
      const request = { task: isReportIntent(clean) ? "report_factory" as const : "chat" as const, question: clean, workspace_id: currentWorkspace?.id, audience: "operator", history, uploaded_evidence: evidence, preferred_language: normalizedLocale } as AnyRecord;
      const response = await deps.runIntelligence(request);
      if (isLanguageGenerationFailed(response)) {
        setMessages(withUser);
        if (conversationId.startsWith("local-") || historyStatus !== "server") persistLocalThread(conversationId, withUser, titleFromPrompt(clean, t("intelligence.newChat")));
        setFailedPrompt(clean);
        setError(t("intelligence.languageGenerationFailed"));
        return;
      }
      const assistantText = normalizeAssistantResponse(response);
      const modelStatus = String(response.model_status || response.status || "");
      if (modelStatus.includes("unavailable") || !assistantText) {
        setMessages(withUser);
        if (conversationId.startsWith("local-") || historyStatus !== "server") persistLocalThread(conversationId, withUser, titleFromPrompt(clean, t("intelligence.newChat")));
        setFailedPrompt(clean);
        setError(t("intelligence.retryState"));
        return;
      }
      const artifact = isReportIntent(clean) ? { kind: "pdf", title: buildReportTitle(clean), question: clean, answer: assistantText, uploaded_evidence: evidence } : null;
      let actions: AnyRecord[] = [];
      if (/\b(task|checklist|follow[- ]?up|email|send|approval|action)\b/i.test(clean)) {
        actions = await deps.planActions({ instruction: clean, workspace_id: currentWorkspace?.id, answer: assistantText, uploaded_evidence: evidence, audience: "operator" });
      }
      if (artifact && shouldAutoEmailReport(clean)) {
        const emailAction = actions.find((item) => item.action_type === "email_report_to_user" && !item.approval_required);
        if (emailAction) {
          try {
            const result = await deps.executeAction({ action_type: emailAction.action_type, workspace_id: currentWorkspace?.id, payload: { ...emailAction.payload, ...artifact }, approval_confirmed: false });
            actions = actions.map((item) => item.id === emailAction.id ? { ...item, execution_result: result, status: result.status || "executed" } : item);
            if (result.status === "executed") setNotice(formatTranslation(t("intelligence.reportEmailed"), { recipient: result.recipient || t("intelligence.accountEmail") }));
          } catch { /* Manual report actions remain available. */ }
        }
      }
      const assistantMessage = { id: `assistant-${Date.now()}`, role: "assistant", content: assistantText, question: clean, uploaded_evidence: evidence, artifact, agentic_actions: actions, model_status: modelStatus };
      const nextRows = [...withUser, assistantMessage];
      setMessages(nextRows);
      await persistExchange(conversationId, clean, assistantText, { question: clean, uploaded_evidence: evidence, artifact, agentic_actions: actions, model_status: modelStatus }, nextRows);
      setFileImports([]);
    } catch (err) {
      setMessages(withUser);
      if (conversationId.startsWith("local-") || historyStatus !== "server") persistLocalThread(conversationId, withUser, titleFromPrompt(clean, t("intelligence.newChat")));
      setFailedPrompt(clean);
      setError(err instanceof Error ? err.message : t("intelligence.retryState"));
    } finally { setLoading(false); }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send(event.currentTarget.value).catch(() => null);
    }
  }

  return {
    t,
    messages,
    filteredConversations,
    activeConversationId,
    conversationSearch,
    setConversationSearch,
    historyStatus,
    question,
    setQuestion,
    loading,
    reportBusyId,
    reportEmailBusyId,
    actionBusyId,
    notice,
    error,
    failedPrompt,
    fileImports,
    setFileImports,
    sidebarOpen,
    setSidebarOpen,
    fileInputRef,
    hasFailed,
    prompts,
    riskLabel,
    loadConversation,
    deleteConversation,
    newChat,
    onFilesSelected,
    downloadReportFor,
    emailReportFor,
    runAction,
    send,
    onKeyDown,
    sendDisabled: loading || hasUploading || hasFailed || (!question.trim() && !fileImports.length),
  };
}
