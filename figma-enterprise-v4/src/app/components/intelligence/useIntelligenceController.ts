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
  decisionDetailsFromResponse,
  isLanguageGenerationFailed,
  isReportIntent,
  mapServerMessage,
  normalizeAssistantResponse,
  readLocalThreads,
  reportFilename,
  safeText,
  titleFromPrompt,
  uploadMetadata,
  writeLocalThreads,
} from "./intelligenceSupport";

function localizedRequestError(error: unknown, fallback: string) {
  const candidate = error && typeof error === "object" ? error as { code?: unknown; message?: unknown } : {};
  const code = String(candidate.code || "");
  if (["upstream_unavailable", "network_unavailable", "request_timeout"].includes(code)) return fallback;
  const message = typeof candidate.message === "string" ? candidate.message.trim() : "";
  if (!message || /<!doctype html|<html|cloudflare|bad gateway|service unavailable/i.test(message)) return fallback;
  return message;
}

export type IntelligenceDependencies = {
  createReportPdf: (payload: AnyRecord) => Promise<Blob>;
  emailReportPdf: (payload: AnyRecord) => Promise<AnyRecord>;
  downloadAgentArtifact: (artifact: AnyRecord) => Promise<Blob>;
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
  const [artifactBusyId, setArtifactBusyId] = useState("");
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
  async function downloadGeneratedArtifact(action: AnyRecord) {
    const artifact = action?.execution_result?.artifact;
    if (!artifact?.download_url) return;
    const id = String(artifact.id || artifact.filename || Date.now());
    setArtifactBusyId(id);
    setError("");
    try {
      const blob = await deps.downloadAgentArtifact(artifact);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = String(artifact.filename || "agro-ai-artifact");
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1200);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("intelligence.actionExecuteFailed"));
    } finally {
      setArtifactBusyId("");
    }
  }

  async function runAction(message: AnyRecord, action: AnyRecord) {
    const actionId = String(action.id || `${message.id}-${action.action_type}`);
    setActionBusyId(actionId); setError("");
    try {
      const result = await deps.executeAction({
        action_type: action.action_type,
        workspace_id: currentWorkspace?.id,
        payload: action.payload || {},
        approval_confirmed: Boolean(action.approval_required),
        plan_token: action.plan_token,
      });
      const next = messages.map((row) => String(row.id) === String(message.id) ? {
        ...row,
        agentic_actions: (row.agentic_actions || []).map((item: AnyRecord) => String(item.id) === actionId ? { ...item, execution_result: result, status: result.status || item.status } : item),
      } : row);
      remember(next);
      const created = result.created_task || result.created_approval_task || result.created_workspace || result.updated_workspace;
      const changedWorkspace = result.created_workspace || result.updated_workspace;
      if (changedWorkspace?.id) {
        window.dispatchEvent(new CustomEvent("agroai:workspace-agent-change", {
          detail: { workspace_id: changedWorkspace.id, action_type: action.action_type },
        }));
      }
      setNotice(formatTranslation(t("intelligence.actionCompleted"), { title: created?.title || created?.name || safeText(result.action_type || action.action_type) }));
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

      const preActionResults = new Map<string, AnyRecord>();
      let sourceRefreshNote = "";
      let analysisWorkspaceId = currentWorkspace?.id;
      const actionFirstTypes = new Set(["create_operation", "update_operation", "sync_connected_sources"]);
      try {
        const preActions = await deps.planActions({
          instruction: clean,
          workspace_id: currentWorkspace?.id,
          answer: "",
          uploaded_evidence: evidence,
          audience: "operator",
          history,
        });
        for (const action of preActions) {
          if (!actionFirstTypes.has(String(action.action_type || ""))) continue;
          if (!action?.auto_execute || action?.approval_required || String(action?.status || "") !== "ready") continue;
          const payload = action.action_type === "sync_connected_sources"
            ? { ...(action.payload || {}), wait_for_completion: true, wait_seconds: 18 }
            : action.payload || {};
          const result = await deps.executeAction({
            action_type: action.action_type,
            workspace_id: analysisWorkspaceId,
            payload,
            approval_confirmed: false,
            plan_token: action.plan_token,
          });
          preActionResults.set(String(action.action_type), result);
          const changedWorkspace = result?.created_workspace || result?.updated_workspace;
          if (changedWorkspace?.id) {
            analysisWorkspaceId = changedWorkspace.id;
            window.dispatchEvent(new CustomEvent("agroai:workspace-agent-change", {
              detail: { workspace_id: changedWorkspace.id, action_type: action.action_type },
            }));
          }
          if (action.action_type === "sync_connected_sources") {
            sourceRefreshNote = safeText(result?.sync?.message);
          }
        }
      } catch (preActionError) {
        sourceRefreshNote = preActionError instanceof Error ? preActionError.message : "";
      }

      const actionResultNotes = Array.from(preActionResults.entries()).map(([actionType, result]) => {
        const workspace = result?.created_workspace || result?.updated_workspace;
        if (workspace?.name) return `${actionType}: completed for "${safeText(workspace.name)}"${workspace.region ? ` in ${safeText(workspace.region)}` : ""}.`;
        if (result?.sync?.message) return `${actionType}: ${safeText(result.sync.message)}`;
        return `${actionType}: ${safeText(result?.status || "completed")}`;
      });
      const runtimeNotes = [sourceRefreshNote, ...actionResultNotes].filter(Boolean).join("\n");
      const groundedQuestion = runtimeNotes
        ? `${clean}\n\nAGRO-AI trusted runtime work completed before analysis:\n${runtimeNotes}`
        : clean;
      const request = { task: isReportIntent(clean) ? "report_factory" as const : "chat" as const, question: groundedQuestion, workspace_id: analysisWorkspaceId, audience: "operator", history, uploaded_evidence: evidence, preferred_language: normalizedLocale } as AnyRecord;
      const response = await deps.runIntelligence(request);
      if (isLanguageGenerationFailed(response)) {
        setMessages(withUser);
        if (conversationId.startsWith("local-") || historyStatus !== "server") persistLocalThread(conversationId, withUser, titleFromPrompt(clean, t("intelligence.newChat")));
        setFailedPrompt(clean);
        setError(t("intelligence.languageGenerationFailed"));
        return;
      }
      const assistantText = normalizeAssistantResponse(response);
      const decisionDetails = decisionDetailsFromResponse(response);
      const modelStatus = String(response.model_status || response.status || "");
      if (modelStatus.includes("unavailable") || !assistantText) {
        setMessages(withUser);
        if (conversationId.startsWith("local-") || historyStatus !== "server") persistLocalThread(conversationId, withUser, titleFromPrompt(clean, t("intelligence.newChat")));
        setFailedPrompt(clean);
        setError(t("intelligence.retryState"));
        return;
      }
      const artifact = isReportIntent(clean) ? { kind: "pdf", title: buildReportTitle(clean), question: clean, answer: assistantText, uploaded_evidence: evidence } : null;
      let actions: AnyRecord[] = await deps.planActions({
        instruction: clean,
        workspace_id: analysisWorkspaceId,
        answer: assistantText,
        uploaded_evidence: evidence,
        audience: "operator",
        history,
        analysis_context: response?.result && typeof response.result === "object" ? response.result : {},
      });
      actions = actions.map((action) => {
        const preResult = preActionResults.get(String(action.action_type || ""));
        return preResult
          ? { ...action, execution_result: preResult, status: preResult.status || action.status, auto_execute: false }
          : action;
      });

      const completedTitles: string[] = [];
      let executionWorkspaceId = analysisWorkspaceId;
      for (const action of actions) {
        if (!action?.auto_execute || action?.approval_required || String(action?.status || "") !== "ready") continue;
        try {
          const result = await deps.executeAction({
            action_type: action.action_type,
            workspace_id: executionWorkspaceId,
            payload: action.payload || {},
            approval_confirmed: false,
            plan_token: action.plan_token,
          });
          action.execution_result = result;
          action.status = result.status || "executed";
          if (result.status === "executed") {
            completedTitles.push(safeText(action.title || action.action_type));
            const changedWorkspace = result.created_workspace || result.updated_workspace;
            if (changedWorkspace?.id) {
              executionWorkspaceId = changedWorkspace.id;
              window.dispatchEvent(new CustomEvent("agroai:workspace-agent-change", {
                detail: { workspace_id: changedWorkspace.id, action_type: action.action_type },
              }));
            }
          }
        } catch (executionError) {
          action.execution_error = executionError instanceof Error ? executionError.message : t("intelligence.actionExecuteFailed");
        }
      }
      actions = [...actions];
      if (completedTitles.length) {
        setNotice(completedTitles.length === 1
          ? `${completedTitles[0]} completed.`
          : `${completedTitles.length} requested actions completed.`);
      }
      const assistantMessage = { id: `assistant-${Date.now()}`, role: "assistant", content: assistantText, question: clean, uploaded_evidence: evidence, artifact, agentic_actions: actions, decision_details: decisionDetails, model_status: modelStatus };
      const nextRows = [...withUser, assistantMessage];
      setMessages(nextRows);
      await persistExchange(conversationId, clean, assistantText, { question: clean, uploaded_evidence: evidence, artifact, agentic_actions: actions, decision_details: decisionDetails, model_status: modelStatus }, nextRows);
      setFileImports([]);
    } catch (err) {
      setMessages(withUser);
      if (conversationId.startsWith("local-") || historyStatus !== "server") persistLocalThread(conversationId, withUser, titleFromPrompt(clean, t("intelligence.newChat")));
      setFailedPrompt(clean);
      setError(localizedRequestError(err, t("intelligence.retryState")));
    } finally { setLoading(false); }
  }

  async function ingestVoiceExchange(userText: string, assistantText: string) {
    const cleanUser = safeText(userText).trim();
    const cleanAssistant = safeText(assistantText).trim();
    if (!cleanUser || !cleanAssistant) return;
    const conversationId = await createConversationIfNeeded(cleanUser);
    const userMessage = { id: `voice-user-${Date.now()}`, role: "user", content: cleanUser, input_mode: "voice" };
    const assistantMessage = {
      id: `voice-assistant-${Date.now()}`,
      role: "assistant",
      content: cleanAssistant,
      question: cleanUser,
      input_mode: "voice",
      model_status: "voice",
    };
    const nextRows = [...messages, userMessage, assistantMessage];
    setMessages(nextRows);
    await persistExchange(
      conversationId,
      cleanUser,
      cleanAssistant,
      { question: cleanUser, input_mode: "voice", model_status: "voice" },
      nextRows,
    );
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
    artifactBusyId,
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
    downloadGeneratedArtifact,
    send,
    ingestVoiceExchange,
    onKeyDown,
    sendDisabled: loading || hasUploading || hasFailed || (!question.trim() && !fileImports.length),
  };
}
