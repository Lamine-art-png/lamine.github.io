export type AnyRecord = Record<string, any>;
export type ChatFileImport = {
  id: string;
  file: File;
  filename: string;
  size_bytes: number;
  content_type: string;
  status: "queued" | "uploading" | "imported" | "failed";
  error?: string;
  uploadResponse?: AnyRecord;
};
export type ConversationSummary = {
  id: string;
  title: string;
  workspace_id?: string;
  status?: string;
  preview?: string;
  message_count?: number;
  created_at?: string;
  updated_at?: string;
  messages?: AnyRecord[];
};

export const LOCAL_THREADS_KEY = "agroai_intelligence_threads_v2";
export const PROMPT_KEYS = [
  "intelligence.prompt.data",
  "intelligence.prompt.checklist",
  "intelligence.prompt.missingEvidence",
  "intelligence.prompt.report",
] as const;

export function asArray(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
export function safeText(value: unknown, fallback = ""): string {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return fallback;
    if (trimmed.startsWith("{") && (trimmed.includes("\"answer\"") || trimmed.includes("\"summary\""))) {
      try { const parsed = JSON.parse(trimmed); return safeText(parsed.answer || parsed.summary || parsed.message, fallback); }
      catch { return fallback || trimmed; }
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

export function localScope(workspaceId?: string) { return `${LOCAL_THREADS_KEY}:${workspaceId || "default"}`; }
export function readLocalThreads(workspaceId?: string): ConversationSummary[] {
  try { const parsed = JSON.parse(window.localStorage.getItem(localScope(workspaceId)) || "[]"); return Array.isArray(parsed) ? parsed : []; }
  catch { return []; }
}
export function writeLocalThreads(workspaceId: string | undefined, rows: ConversationSummary[]) {
  try { window.localStorage.setItem(localScope(workspaceId), JSON.stringify(rows.slice(0, 80))); }
  catch { /* Best effort cache. */ }
}
export function titleFromPrompt(prompt: string, fallback: string) {
  const clean = prompt.replace(/\s+/g, " ").trim();
  if (!clean) return fallback;
  return clean.slice(0, 64) + (clean.length > 64 ? "…" : "");
}
export function fileTypeLabel(file: File) {
  const lower = file.name.toLowerCase();
  if (lower.endsWith(".csv")) return "CSV";
  if (lower.endsWith(".xlsx") || lower.endsWith(".xls")) return "Spreadsheet";
  if (lower.endsWith(".pdf")) return "PDF";
  if (lower.endsWith(".txt") || lower.endsWith(".md")) return "Text";
  if (lower.endsWith(".json") || lower.endsWith(".geojson")) return "JSON";
  return file.type || "File";
}
export function uploadMetadata(item: ChatFileImport) {
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
export function normalizeAssistantResponse(response: unknown): string {
  const payload = response && typeof response === "object" ? response as AnyRecord : {};
  const result = payload.result && typeof payload.result === "object" ? payload.result as AnyRecord : {};
  return safeText(result.answer || result.summary || payload.answer || payload.summary || payload.content || result.executive_summary, "");
}
export function isLanguageGenerationFailed(response: AnyRecord) {
  const status = String(response.status || response.model_status || response.result?.status || response.result?.error || "");
  return status.includes("language_generation_failed");
}
export function isReportIntent(text: string) {
  const normalized = text.toLowerCase();
  return ["report", "pdf", "document", "packet", "brief", "memo", "analysis", "export"].some((term) => normalized.includes(term));
}
export function shouldAutoEmailReport(text: string) {
  const normalized = text.toLowerCase();
  return ["email", "send", "mail"].some((term) => normalized.includes(term)) && isReportIntent(normalized);
}
export function buildReportTitle(question: string) {
  const clean = question.replace(/\s+/g, " ").trim().toLowerCase();
  if (clean.includes("customer")) return "AGRO-AI Customer-Ready Operating Report";
  if (clean.includes("compliance")) return "AGRO-AI Compliance Evidence Report";
  if (clean.includes("water")) return "AGRO-AI Water Use Intelligence Report";
  return "AGRO-AI Operating Report";
}
export function reportFilename(title: string) {
  const safe = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") || "agroai-report";
  return `${safe}.pdf`;
}
export function mapServerMessage(row: AnyRecord): AnyRecord {
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
export function shouldUseLegacyRoute(error: unknown) {
  const status = Number((error as AnyRecord)?.status || 0);
  return status === 404 || status === 405;
}
