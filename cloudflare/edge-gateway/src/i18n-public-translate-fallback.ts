import { validCatalog } from "./i18n-translation-engine-v3";

const TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/single";
const TIMEOUT_MS = 10_000;
const MAX_PARALLEL = 4;
const MAX_ATTEMPTS = 2;
const PROTECTED_SPLIT_RE = /(\{[A-Za-z_][A-Za-z0-9_]*\}|https?:\/\/[^\s]+|AGRO-AI)/g;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function shouldTranslate(value: string): boolean {
  return /[A-Za-z]/.test(value) && value.trim().length > 0;
}

function translatedText(payload: unknown): string {
  if (!Array.isArray(payload) || !Array.isArray(payload[0])) return "";
  return payload[0]
    .map((segment) => Array.isArray(segment) && typeof segment[0] === "string" ? segment[0] : "")
    .join("")
    .trim();
}

async function translateSegment(targetLocale: string, segment: string): Promise<string> {
  if (!shouldTranslate(segment)) return segment;
  let lastError: unknown = new Error("public_translation_unavailable");

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const url = new URL(TRANSLATE_ENDPOINT);
      url.searchParams.set("client", "gtx");
      url.searchParams.set("sl", "en");
      url.searchParams.set("tl", targetLocale);
      url.searchParams.set("dt", "t");
      url.searchParams.set("q", segment);
      const response = await fetch(url.toString(), {
        method: "GET",
        headers: { accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`public_translation_http_${response.status}`);
      const value = translatedText(await response.json());
      if (!value) throw new Error("public_translation_empty");
      const leading = segment.match(/^\s*/)?.[0] || "";
      const trailing = segment.match(/\s*$/)?.[0] || "";
      return `${leading}${value}${trailing}`;
    } catch (error) {
      lastError = error;
      if (attempt < MAX_ATTEMPTS) await delay(150 * attempt);
    } finally {
      clearTimeout(timer);
    }
  }

  throw lastError;
}

async function translateValue(targetLocale: string, value: string): Promise<string> {
  const parts = value.split(PROTECTED_SPLIT_RE);
  const translated = await Promise.all(parts.map((part) => {
    if (!part || part === "AGRO-AI" || /^\{[A-Za-z_][A-Za-z0-9_]*\}$/.test(part) || /^https?:\/\//.test(part)) {
      return Promise.resolve(part);
    }
    return translateSegment(targetLocale, part);
  }));
  return translated.join("");
}

export async function translateWithPublicFallback(
  locale: string,
  source: Record<string, string>,
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
      output[key] = await translateValue(targetLocale, value);
    }
  }

  await Promise.all(Array.from({ length: Math.min(MAX_PARALLEL, Math.max(1, entries.length)) }, () => worker()));
  if (!validCatalog(source, output)) throw new Error("public_translation_catalog_reconciliation_failed");
  return output;
}

export const publicTranslationProvider = "public_translation_fallback";
