import { validCatalog } from "./i18n-translation-engine-v3";

const GOOGLE_TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/single";
const MYMEMORY_TRANSLATE_ENDPOINT = "https://api.mymemory.translated.net/get";
const LINGVA_TRANSLATE_ENDPOINT = "https://lingva.ml/api/v1";
const TIMEOUT_MS = 3_500;
const MAX_CONCURRENT_PROVIDER_REQUESTS = 6;
const GOOGLE_BATCH_MAX_CHARS = 1_900;
const MYMEMORY_BATCH_MAX_CHARS = 360;
const LINGVA_BATCH_MAX_CHARS = 1_900;
const PROTECTED_SPLIT_RE = /(\{[A-Za-z_][A-Za-z0-9_]*\}|https?:\/\/[^\s]+|AGRO-AI)/g;

type SourceEntry = [string, string];
type EncodedBatch = {
  text: string;
  keys: string[];
  protectedValues: string[];
};

class ProviderHttpError extends Error {
  readonly status: number;

  constructor(provider: string, status: number) {
    super(`${provider}_http_${status}`);
    this.status = status;
  }
}

let activeProviderRequests = 0;
const providerWaiters: Array<() => void> = [];

async function acquireProviderSlot(): Promise<() => void> {
  if (activeProviderRequests >= MAX_CONCURRENT_PROVIDER_REQUESTS) {
    await new Promise<void>((resolve) => providerWaiters.push(resolve));
  }
  activeProviderRequests += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    activeProviderRequests = Math.max(0, activeProviderRequests - 1);
    providerWaiters.shift()?.();
  };
}

async function fetchJsonOnce(provider: string, input: string): Promise<unknown> {
  const release = await acquireProviderSlot();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(`${provider}_timeout`), TIMEOUT_MS);
  try {
    const response = await fetch(input, {
      method: "GET",
      headers: { accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) throw new ProviderHttpError(provider, response.status);
    return await response.json();
  } finally {
    clearTimeout(timer);
    release();
  }
}

function googleTranslatedText(payload: unknown): string {
  if (!Array.isArray(payload) || !Array.isArray(payload[0])) return "";
  return payload[0]
    .map((segment) => Array.isArray(segment) && typeof segment[0] === "string" ? segment[0] : "")
    .join("")
    .trim();
}

function decodeHtmlEntities(value: string): string {
  return value
    .replace(/&quot;/g, "\"")
    .replace(/&#39;|&#x27;/gi, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

function myMemoryTranslatedText(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "";
  const data = payload as { responseData?: { translatedText?: unknown }; responseStatus?: unknown };
  const status = Number(data.responseStatus ?? 200);
  if (Number.isFinite(status) && status >= 400) return "";
  const value = data.responseData?.translatedText;
  return typeof value === "string" ? decodeHtmlEntities(value).trim() : "";
}

function lingvaTranslatedText(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "";
  const value = (payload as { translation?: unknown }).translation;
  return typeof value === "string" ? value.trim() : "";
}

function itemMarker(index: number): string {
  return `<<<AGROAI_ITEM_${String(index).padStart(4, "0")}>>>`;
}

function keepMarker(index: number): string {
  return `<<<AGROAI_KEEP_${String(index).padStart(4, "0")}>>>`;
}

function normalizeMarkers(value: string): string {
  return value
    .replace(/<\s*<\s*<\s*AGROAI_(ITEM|KEEP)_(\d{4})\s*>\s*>\s*>/g, "<<<AGROAI_$1_$2>>>")
    .replace(/＜\s*＜\s*＜\s*AGROAI_(ITEM|KEEP)_(\d{4})\s*＞\s*＞\s*＞/g, "<<<AGROAI_$1_$2>>>");
}

function encodeBatch(entries: SourceEntry[]): EncodedBatch {
  const protectedValues: string[] = [];
  const encoded = entries.map(([, value], index) => {
    const protectedValue = value.replace(PROTECTED_SPLIT_RE, (token) => {
      const marker = keepMarker(protectedValues.length);
      protectedValues.push(token);
      return marker;
    });
    return `${itemMarker(index)}\n${protectedValue}`;
  });
  return { text: encoded.join("\n"), keys: entries.map(([key]) => key), protectedValues };
}

function decodeBatch(translatedText: string, encoded: EncodedBatch): Record<string, string> {
  const normalized = normalizeMarkers(translatedText);
  const output: Record<string, string> = {};

  for (let index = 0; index < encoded.keys.length; index += 1) {
    const startMarker = itemMarker(index);
    const start = normalized.indexOf(startMarker);
    if (start < 0) throw new Error(`public_translation_missing_item_marker_${index}`);
    const contentStart = start + startMarker.length;
    const nextMarker = index + 1 < encoded.keys.length ? itemMarker(index + 1) : "";
    const end = nextMarker ? normalized.indexOf(nextMarker, contentStart) : normalized.length;
    if (end < contentStart) throw new Error(`public_translation_missing_item_boundary_${index}`);

    let value = normalized.slice(contentStart, end).trim();
    for (let keepIndex = 0; keepIndex < encoded.protectedValues.length; keepIndex += 1) {
      value = value.split(keepMarker(keepIndex)).join(encoded.protectedValues[keepIndex]);
    }
    if (/<<<AGROAI_KEEP_\d{4}>>>/.test(value)) throw new Error(`public_translation_unrestored_token_${index}`);
    if (!value) throw new Error(`public_translation_empty_item_${index}`);
    output[encoded.keys[index]] = value;
  }

  return output;
}

function packEntries(entries: SourceEntry[], maxChars: number): SourceEntry[][] {
  const packs: SourceEntry[][] = [];
  let current: SourceEntry[] = [];
  let currentChars = 0;

  for (const entry of entries) {
    const estimated = entry[1].length + 40;
    if (current.length > 0 && currentChars + estimated > maxChars) {
      packs.push(current);
      current = [];
      currentChars = 0;
    }
    current.push(entry);
    currentChars += estimated;
  }
  if (current.length > 0) packs.push(current);
  return packs;
}

function googleTargetLocale(locale: string): string {
  const root = locale.split("-", 1)[0].toLowerCase();
  if (root === "zh") return "zh-CN";
  return root;
}

async function googleTranslateText(targetLocale: string, text: string): Promise<string> {
  const url = new URL(GOOGLE_TRANSLATE_ENDPOINT);
  url.searchParams.set("client", "gtx");
  url.searchParams.set("sl", "en");
  url.searchParams.set("tl", googleTargetLocale(targetLocale));
  url.searchParams.set("dt", "t");
  url.searchParams.set("q", text);
  const value = googleTranslatedText(await fetchJsonOnce("google_public_translation", url.toString()));
  if (!value) throw new Error("google_public_translation_empty");
  return value;
}

async function myMemoryTranslateText(targetLocale: string, text: string): Promise<string> {
  const url = new URL(MYMEMORY_TRANSLATE_ENDPOINT);
  url.searchParams.set("q", text);
  url.searchParams.set("langpair", `en|${targetLocale.split("-", 1)[0].toLowerCase()}`);
  const value = myMemoryTranslatedText(await fetchJsonOnce("mymemory_public_translation", url.toString()));
  if (!value) throw new Error("mymemory_public_translation_empty");
  return value;
}

async function lingvaTranslateText(targetLocale: string, text: string): Promise<string> {
  const target = targetLocale.split("-", 1)[0].toLowerCase();
  const url = `${LINGVA_TRANSLATE_ENDPOINT}/en/${encodeURIComponent(target)}/${encodeURIComponent(text)}`;
  const value = lingvaTranslatedText(await fetchJsonOnce("lingva_public_translation", url));
  if (!value) throw new Error("lingva_public_translation_empty");
  return value;
}

async function translatePack(
  targetLocale: string,
  pack: SourceEntry[],
  provider: (targetLocale: string, text: string) => Promise<string>,
): Promise<Record<string, string>> {
  const encoded = encodeBatch(pack);
  return decodeBatch(await provider(targetLocale, encoded.text), encoded);
}

async function translateThroughProvider(
  targetLocale: string,
  entries: SourceEntry[],
  maxChars: number,
  provider: (targetLocale: string, text: string) => Promise<string>,
): Promise<Record<string, string>> {
  const output: Record<string, string> = {};
  for (const pack of packEntries(entries, maxChars)) {
    Object.assign(output, await translatePack(targetLocale, pack, provider));
  }
  return output;
}

export async function translateWithPublicFallback(
  locale: string,
  source: Record<string, string>,
): Promise<Record<string, string>> {
  const targetLocale = locale.split("-", 1)[0].toLowerCase();
  const entries = Object.entries(source);
  const failures: string[] = [];
  const myMemoryFitsOneRequest = packEntries(entries, MYMEMORY_BATCH_MAX_CHARS).length === 1;

  const attempts: Array<{
    name: string;
    maxChars: number;
    provider: (targetLocale: string, text: string) => Promise<string>;
  }> = [
    { name: "google", maxChars: GOOGLE_BATCH_MAX_CHARS, provider: googleTranslateText },
    { name: "lingva", maxChars: LINGVA_BATCH_MAX_CHARS, provider: lingvaTranslateText },
    ...(myMemoryFitsOneRequest
      ? [{ name: "mymemory", maxChars: MYMEMORY_BATCH_MAX_CHARS, provider: myMemoryTranslateText }]
      : []),
  ];

  for (const attempt of attempts) {
    try {
      const output = await translateThroughProvider(targetLocale, entries, attempt.maxChars, attempt.provider);
      if (!validCatalog(source, output)) throw new Error(`${attempt.name}_translation_catalog_reconciliation_failed`);
      return output;
    } catch (error) {
      failures.push(`${attempt.name}=${String(error).replace(/\s+/g, " ").slice(0, 500)}`);
    }
  }

  throw new Error(`public_translation_provider_chain_exhausted: ${failures.join("; ")}`);
}

export const publicTranslationProvider = "public_translation_provider_chain_v4";
