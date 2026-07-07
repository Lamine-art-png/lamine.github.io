const MODEL = "@cf/meta/m2m100-1.2b";
const MAX_PARALLEL = 2;
const CALL_TIMEOUT_MS = 10_000;
const MAX_ATTEMPTS = 3;
const PLACEHOLDER_RE = /\{[A-Za-z_][A-Za-z0-9_]*\}/g;
const PROTECTED_SPLIT_RE = /(\{[A-Za-z_][A-Za-z0-9_]*\}|https?:\/\/[^\s]+|AGRO-AI)/g;

export type AiRunner = {
  run(model: string, input: unknown): Promise<unknown>;
};

function placeholderSignature(value: string): string[] {
  return (value.match(PLACEHOLDER_RE) || []).sort();
}

export function validCatalog(source: Record<string, string>, candidate: unknown): candidate is Record<string, string> {
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return false;
  const translated = candidate as Record<string, unknown>;
  const sourceKeys = Object.keys(source).sort();
  const translatedKeys = Object.keys(translated).sort();
  if (sourceKeys.length !== translatedKeys.length || sourceKeys.some((key, index) => key !== translatedKeys[index])) return false;
  return sourceKeys.every((key) => {
    const value = translated[key];
    return typeof value === "string" && value.trim().length > 0 &&
      JSON.stringify(placeholderSignature(value)) === JSON.stringify(placeholderSignature(source[key]));
  });
}

function translatedText(result: unknown): string {
  if (!result || typeof result !== "object") return "";
  const body = result as Record<string, unknown>;
  if (typeof body.translated_text === "string") return body.translated_text.trim();
  const nested = body.result;
  if (nested && typeof nested === "object" && typeof (nested as Record<string, unknown>).translated_text === "string") {
    return String((nested as Record<string, unknown>).translated_text).trim();
  }
  return "";
}

async function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error("workers_ai_translation_timeout")), timeoutMs);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function shouldTranslate(segment: string): boolean {
  return /[A-Za-z]/.test(segment) && segment.trim().length > 0;
}

async function translateSegment(ai: AiRunner, targetLocale: string, segment: string): Promise<string> {
  if (!shouldTranslate(segment)) return segment;
  let lastError: unknown = new Error("workers_ai_translation_unavailable");

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    try {
      const result = await withTimeout(
        ai.run(MODEL, {
          text: segment,
          source_lang: "en",
          target_lang: targetLocale,
        }),
        CALL_TIMEOUT_MS,
      );
      const value = translatedText(result);
      if (!value) throw new Error("workers_ai_empty_translation");
      const leading = segment.match(/^\s*/)?.[0] || "";
      const trailing = segment.match(/\s*$/)?.[0] || "";
      return `${leading}${value}${trailing}`;
    } catch (error) {
      lastError = error;
      if (attempt < MAX_ATTEMPTS) await delay(200 * attempt);
    }
  }

  throw lastError;
}

async function translateValue(ai: AiRunner, targetLocale: string, value: string): Promise<string> {
  const parts = value.split(PROTECTED_SPLIT_RE);
  const translated = await Promise.all(parts.map((part) => {
    if (!part || part === "AGRO-AI" || /^\{[A-Za-z_][A-Za-z0-9_]*\}$/.test(part) || /^https?:\/\//.test(part)) {
      return Promise.resolve(part);
    }
    return translateSegment(ai, targetLocale, part);
  }));
  return translated.join("");
}

export async function translateCatalog(
  ai: AiRunner,
  locale: string,
  source: Record<string, string>,
  _languageName = locale,
): Promise<Record<string, string>> {
  const targetLocale = locale.split("-", 1)[0].toLowerCase();
  const entries = Object.entries(source);
  const output: Record<string, string> = {};
  let cursor = 0;

  async function worker(): Promise<void> {
    while (true) {
      const index = cursor++;
      if (index >= entries.length) return;
      const [key, value] = entries[index];
      output[key] = await translateValue(ai, targetLocale, value);
    }
  }

  const workers = Array.from({ length: Math.min(MAX_PARALLEL, Math.max(1, entries.length)) }, () => worker());
  await Promise.all(workers);
  if (!validCatalog(source, output)) throw new Error("workers_ai_catalog_reconciliation_failed");
  return output;
}

export async function catalogSha256(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map((item) => item.toString(16).padStart(2, "0")).join("");
}

export const workersAiModel = MODEL;
export const workersAiChunkSize = MAX_PARALLEL;
