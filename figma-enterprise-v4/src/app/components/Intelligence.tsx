import { KeyboardEvent, useEffect, useRef, useState } from "react";
import { Download, FileText, Send, UploadCloud, X } from "lucide-react";
import { API_BASE_URL, apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
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

const MEMORY_KEY = "agroai_intelligence_recovery_memory_v1";

const PROMPTS = [
  "What have you been checking?",
  "Generate a customer-ready report from this workspace.",
  "What evidence is missing?",
  "Create an operator checklist.",
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

function memoryScope(workspaceId?: string) {
  return `${MEMORY_KEY}:${workspaceId || "default"}`;
}

function readMemory(workspaceId?: string): AnyRecord[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(memoryScope(workspaceId)) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeMemory(workspaceId: string | undefined, rows: AnyRecord[]) {
  try {
    window.localStorage.setItem(memoryScope(workspaceId), JSON.stringify(rows.slice(-60)));
  } catch {
    // Local memory is best-effort. The page must never crash because storage failed.
  }
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
    warnings: response.warnings || output.warnings || [],
    data_source_id: source.id,
  };
}

function normalizeAssistantResponse(response: unknown): string {
  const payload = response && typeof response === "object" ? (response as AnyRecord) : {};
  const result = payload.result && typeof payload.result === "object" ? payload.result as AnyRecord : {};
  return safeText(
    result.answer || result.summary || payload.answer || payload.summary || payload.content || result.executive_summary,
    "I can help. Give me a field, file, irrigation question, compliance packet, or customer report request."
  );
}

function isReportIntent(text: string) {
  const normalized = text.toLowerCase();
  return ["report", "pdf", "document", "packet", "brief", "memo", "analysis", "export"].some((term) => normalized.includes(term));
}

function buildReportTitle(question: string) {
  const clean = question.replace(/\s+/g, " ").trim();
  if (!clean) return "AGRO-AI Operating Report";
  if (clean.toLowerCase().includes("customer")) return "AGRO-AI Customer-Ready Operating Report";
  if (clean.toLowerCase().includes("compliance")) return "AGRO-AI Compliance Evidence Report";
  if (clean.toLowerCase().includes("water")) return "AGRO-AI Water Use Intelligence Report";
  return "AGRO-AI Operating Report";
}

function reportFilename(title: string) {
  const safe = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") || "agroai-report";
  return `${safe}.pdf`;
}

async function createReportPdf(payload: AnyRecord): Promise<Blob> {
  const token = window.localStorage.getItem("agroai_access_token");
  const headers = new Headers({ "Content-Type": "application/json" });
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE_URL}/v1/intelligence/chat/report-pdf`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `Report export failed with status ${response.status}`);
  }

  return response.blob();
}

export function Intelligence() {
  const { currentWorkspace } = useAuth();
  const [messages, setMessages] = useState<AnyRecord[]>([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [reportBusyId, setReportBusyId] = useState("");
  const [error, setError] = useState("");
  const [fileImports, setFileImports] = useState<ChatFileImport[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const hasUploading = fileImports.some((item) => item.status === "uploading");
  const hasFailed = fileImports.some((item) => item.status === "failed");

  useEffect(() => {
    setMessages(readMemory(currentWorkspace?.id));
  }, [currentWorkspace?.id]);

  function remember(rows: AnyRecord[]) {
    setMessages(rows);
    writeMemory(currentWorkspace?.id, rows);
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

  async function persistExchange(content: string, output: string) {
    try {
      const created = await apiClient.conversations.create({
        title: content.slice(0, 90) || "Ask AGRO-AI",
        workspace_id: currentWorkspace?.id,
      }) as AnyRecord;
      const conversationId = created.conversation?.id || created.id || created.conversation_id;
      if (conversationId) {
        await apiClient.post(`/v1/intelligence/chat/conversations/${encodeURIComponent(String(conversationId))}/messages`, {
          content,
          output,
        });
      }
    } catch {
      // Server memory is best-effort for now. Local recovery memory already keeps the chat from disappearing on reload.
    }
  }

  async function downloadReportFor(message: AnyRecord) {
    const artifact = message.artifact || {
      title: buildReportTitle(message.question || "AGRO-AI report"),
      question: message.question || "AGRO-AI report",
      answer: safeText(message.content),
      uploaded_evidence: message.uploaded_evidence || [],
    };
    const busyId = String(message.id || Date.now());
    setReportBusyId(busyId);
    setError("");
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

  async function send(prompt = question) {
    const clean = prompt.trim() || (fileImports.length ? "Summarize the files I imported." : "");
    if (!clean || loading || hasUploading || hasFailed) return;
    setQuestion("");
    setError("");
    setLoading(true);
    const userMessage = { id: `user-${Date.now()}`, role: "user", content: clean };
    const withUser = [...messages, userMessage];
    remember(withUser);

    try {
      const importedBeforeSend = fileImports.filter((item) => item.status === "imported");
      const newlyImported = await ensureQueuedUploads();
      const evidence = [...importedBeforeSend, ...newlyImported].map(uploadMetadata);
      const history = withUser
        .filter((row) => row.role === "user" || row.role === "assistant")
        .slice(-8)
        .map((row) => ({ role: row.role, content: safeText(row.content).slice(0, 1800) }));
      const request = {
        task: isReportIntent(clean) ? "report_factory" as const : "chat" as const,
        question: clean,
        workspace_id: currentWorkspace?.id,
        audience: "operator",
        history,
        uploaded_evidence: evidence,
      };
      const response = await apiClient.intelligence.brainRun(request).catch(() => apiClient.intelligence.run(request)) as AnyRecord;
      const assistantText = normalizeAssistantResponse(response);
      const assistantMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: assistantText,
        question: clean,
        uploaded_evidence: evidence,
        artifact: isReportIntent(clean)
          ? {
              kind: "pdf",
              title: buildReportTitle(clean),
              question: clean,
              answer: assistantText,
              uploaded_evidence: evidence,
            }
          : null,
      };
      const nextRows = [...withUser, assistantMessage];
      remember(nextRows);
      persistExchange(clean, assistantText).catch(() => null);
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
      <main className="grid min-h-screen" style={{ gridTemplateColumns: sidebarOpen ? "280px minmax(0, 1fr)" : "minmax(0, 1fr)" }}>
        {sidebarOpen ? (
          <aside className="border-r p-4" style={{ background: SURFACE, borderColor: BORDER }}>
            <div className="flex items-center justify-between gap-3">
              <div className="text-[12px] font-semibold" style={{ color: TEXT }}>Ask AGRO-AI</div>
              <button type="button" onClick={() => setSidebarOpen(false)} className="rounded-lg p-2" style={{ border: `1px solid ${BORDER}`, color: MUTED }} title="Close sidebar">
                <X size={15} />
              </button>
            </div>
            <button type="button" onClick={() => remember([])} className="mt-4 w-full rounded-lg px-3 py-2 text-[12px] font-medium" style={{ background: "#0D2B1E", color: "white" }}>
              New chat
            </button>
            <div className="mt-6 text-[11px] font-semibold uppercase" style={{ color: MUTED }}>Memory</div>
            <div className="mt-3 rounded-lg p-3 text-[12px] leading-relaxed" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>
              {messages.length ? `${messages.length} messages saved for this workspace on this device.` : "No saved messages yet."}
            </div>
            <div className="mt-3 rounded-lg p-3 text-[12px] leading-relaxed" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>
              Report Factory is active for report, PDF, brief, memo, packet, and analysis requests.
            </div>
          </aside>
        ) : null}

        <section className="flex min-w-0 flex-col">
          <header className="px-8 py-6" style={{ background: "#0D2B1E", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="inline-flex rounded-full px-3 py-1 text-[11px] font-semibold" style={{ background: "rgba(255,255,255,0.12)", color: "white" }}>Workspace intelligence</div>
                <h1 className="mt-3 text-[28px] font-semibold tracking-tight" style={{ color: "white" }}>Ask AGRO-AI</h1>
                <p className="mt-2 max-w-2xl text-[13px] leading-relaxed" style={{ color: "rgba(255,255,255,0.68)" }}>
                  Ask operational questions, import files, and turn workspace context into reports, checklists, and next steps.
                </p>
              </div>
              {!sidebarOpen ? (
                <button type="button" onClick={() => setSidebarOpen(true)} className="rounded-lg px-3 py-2 text-[12px] font-medium" style={{ background: "rgba(255,255,255,0.12)", color: "white" }}>
                  <span className="inline-flex items-center gap-2"><FileText size={15} /> History</span>
                </button>
              ) : null}
            </div>
          </header>

          <div className="flex-1 overflow-y-auto px-6 py-7">
            <div className="mx-auto max-w-[900px] space-y-5">
              {error ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: "#991B1B" }}>{error}</div> : null}
              {!messages.length && !loading ? (
                <section className="rounded-xl p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
                  <div className="text-[12px] font-semibold uppercase" style={{ color: MUTED }}>Start a workspace thread</div>
                  <h2 className="mt-3 text-[24px] font-semibold" style={{ color: TEXT }}>Ask a question or import files.</h2>
                  <p className="mt-2 max-w-2xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
                    AGRO-AI can summarize uploaded records, explain field priorities, draft operator checklists, and create PDF report packets from the answer.
                  </p>
                  <div className="mt-5 flex flex-wrap gap-2">
                    {PROMPTS.map((prompt) => (
                      <button key={prompt} type="button" onClick={() => send(prompt)} className="rounded-full px-3 py-2 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>{prompt}</button>
                    ))}
                  </div>
                </section>
              ) : null}

              {messages.map((message, index) => (
                <div key={message.id || index} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                  <article className={message.role === "user" ? "max-w-[72%]" : "w-full max-w-[820px]"}>
                    <div className="rounded-2xl px-5 py-4 text-[15px] leading-7 whitespace-pre-wrap" style={{ background: message.role === "user" ? "#0D2B1E" : SURFACE, color: message.role === "user" ? "white" : TEXT, border: `1px solid ${message.role === "user" ? "#0D2B1E" : BORDER}` }}>
                      {safeText(message.content)}
                      {message.role === "assistant" && message.artifact ? (
                        <div className="mt-4 flex flex-wrap gap-2 whitespace-normal">
                          <button type="button" onClick={() => downloadReportFor(message)} disabled={reportBusyId === String(message.id || index)} className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-semibold disabled:opacity-60" style={{ background: "#0D2B1E", color: "white" }}>
                            {reportBusyId === String(message.id || index) ? <FileText size={15} /> : <Download size={15} />}
                            {reportBusyId === String(message.id || index) ? "Preparing PDF..." : "Download PDF report"}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </article>
                </div>
              ))}
              {loading ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: MUTED }}>Reading the evidence and preparing the answer...</div> : null}
            </div>
          </div>

          <footer className="px-6 pb-6">
            <div className="mx-auto max-w-[900px] rounded-2xl p-4 shadow-[0_18px_60px_rgba(16,35,27,0.08)]" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              {fileImports.length ? (
                <div className="mb-3 flex flex-wrap gap-2">
                  {fileImports.map((item) => (
                    <div key={item.id} className="flex items-center gap-2 rounded-full px-3 py-2 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                      <span className="max-w-[180px] truncate font-medium">{item.filename}</span>
                      <span style={{ color: item.status === "failed" ? "#991B1B" : MUTED }}>{item.status === "queued" ? "Queued" : item.status === "uploading" ? "Uploading..." : item.status === "imported" ? "Imported" : "Failed"}</span>
                      <button type="button" onClick={() => setFileImports((current) => current.filter((row) => row.id !== item.id))} title="Remove"><X size={13} /></button>
                    </div>
                  ))}
                </div>
              ) : null}
              {hasFailed ? <div className="mb-3 text-[12px]" style={{ color: "#991B1B" }}>One file failed to import. Remove it before sending.</div> : null}
              <div className="flex gap-3">
                <button type="button" onClick={() => fileInputRef.current?.click()} className="inline-flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-medium" style={{ border: `1px solid ${BORDER}`, color: TEXT }}>
                  <UploadCloud size={15} /> Import files
                </button>
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
