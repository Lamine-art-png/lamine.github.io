import { apiClient } from "./client";

const uploadStateEvent = "agroai:upload-state";
const batchSummaryKey = "agroai:last-evidence-upload-batch";

export type EvidenceUploadReceipt = {
  status?: string;
  phase?: string;
  job_id?: string;
  filename?: string;
  rows_parsed?: number;
  evidence_records_created?: number;
  processing_pending?: boolean;
  durable_stored?: boolean;
  warnings?: string[];
  queue_publication?: { published?: number; failed?: number };
  [key: string]: unknown;
};

export type EvidenceUploadFailure = {
  filename: string;
  message: string;
};

export type EvidenceUploadBatchResult = {
  total: number;
  stored: number;
  processing: number;
  failed: number;
  receipts: EvidenceUploadReceipt[];
  failures: EvidenceUploadFailure[];
  warnings: string[];
};

type BatchProgress = {
  total: number;
  completed: number;
  stored: number;
  failed: number;
  filename: string;
};

type BatchOptions = {
  concurrency?: number;
  onProgress?: (progress: BatchProgress) => void;
};

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function providerForUpload(file: File) {
  return file.name.toLowerCase().endsWith(".csv") ? "manual_csv" : "chat_upload";
}

function dispatchUploadState(detail: Record<string, unknown>) {
  window.dispatchEvent(new CustomEvent(uploadStateEvent, { detail }));
}

function normalizedWarnings(receipt: Record<string, unknown>): string[] {
  const warnings = Array.isArray(receipt.warnings)
    ? receipt.warnings.map((warning) => String(warning)).filter(Boolean)
    : [];
  const publication = objectValue(receipt.queue_publication);
  const failed = Number(publication.failed || 0);
  const published = Number(publication.published || 0);
  if (failed > 0 && published === 0) {
    warnings.push("The file is securely stored, but background queue delivery is delayed. AGRO-AI will retry automatically.");
  }
  return warnings;
}

export async function stageEvidenceFile(file: File, workspaceId?: string): Promise<EvidenceUploadReceipt> {
  const provider = providerForUpload(file);
  const query = new URLSearchParams({ provider });
  if (workspaceId) query.set("workspace_id", workspaceId);
  const form = new FormData();
  form.append("file", file);

  dispatchUploadState({
    phase: "uploading",
    filename: file.name,
    provider,
    message: `Securely storing ${file.name}...`,
  });

  try {
    const response = await apiClient.request<Record<string, unknown>>(
      `/v1/evidence/upload?${query.toString()}`,
      { method: "POST", body: form },
    );
    const warnings = normalizedWarnings(response);
    const processingPending = Boolean(response.processing_pending || response.job_id);
    const receipt: EvidenceUploadReceipt = {
      ...response,
      filename: file.name,
      warnings,
      durable_stored: response.durable_stored !== false,
      processing_pending: processingPending,
    };
    dispatchUploadState({
      phase: processingPending ? "stored" : "complete",
      filename: file.name,
      provider,
      job_id: receipt.job_id,
      message: processingPending
        ? `${file.name} is securely stored. AGRO-AI is processing it in the background.`
        : `${file.name} is stored, processed, and ready.`,
    });
    return receipt;
  } catch (error) {
    const message = error instanceof Error ? error.message : "Upload failed.";
    dispatchUploadState({ phase: "failed", filename: file.name, provider, message });
    throw error;
  }
}

export async function uploadEvidenceBatch(
  files: File[],
  workspaceId?: string,
  options: BatchOptions = {},
): Promise<EvidenceUploadBatchResult> {
  const total = files.length;
  if (!total) {
    return { total: 0, stored: 0, processing: 0, failed: 0, receipts: [], failures: [], warnings: [] };
  }

  const receipts: EvidenceUploadReceipt[] = [];
  const failures: EvidenceUploadFailure[] = [];
  const warnings: string[] = [];
  const concurrency = Math.max(1, Math.min(options.concurrency || 4, 6, total));
  let cursor = 0;
  let completed = 0;
  let stored = 0;

  async function worker() {
    while (true) {
      const index = cursor;
      cursor += 1;
      if (index >= total) return;
      const file = files[index];
      try {
        const receipt = await stageEvidenceFile(file, workspaceId);
        receipts.push(receipt);
        stored += 1;
        warnings.push(...(receipt.warnings || []));
      } catch (error) {
        failures.push({
          filename: file.name,
          message: error instanceof Error ? error.message : "Upload failed.",
        });
      } finally {
        completed += 1;
        options.onProgress?.({
          total,
          completed,
          stored,
          failed: failures.length,
          filename: file.name,
        });
      }
    }
  }

  await Promise.all(Array.from({ length: concurrency }, () => worker()));
  const processing = receipts.filter((receipt) => receipt.processing_pending).length;
  return {
    total,
    stored,
    processing,
    failed: failures.length,
    receipts,
    failures,
    warnings: Array.from(new Set(warnings)),
  };
}

export function persistEvidenceUploadBatch(result: EvidenceUploadBatchResult) {
  try {
    sessionStorage.setItem(batchSummaryKey, JSON.stringify({ ...result, receipts: [], saved_at: new Date().toISOString() }));
  } catch {
    // Upload completion must not fail because browser storage is unavailable.
  }
}

export function consumeEvidenceUploadBatch(): EvidenceUploadBatchResult | null {
  try {
    const raw = sessionStorage.getItem(batchSummaryKey);
    if (!raw) return null;
    sessionStorage.removeItem(batchSummaryKey);
    const parsed = JSON.parse(raw) as EvidenceUploadBatchResult;
    return parsed && typeof parsed.total === "number" ? parsed : null;
  } catch {
    return null;
  }
}
