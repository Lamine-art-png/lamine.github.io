import { validCatalog, type AiRunner } from "./i18n-translation-engine-v3";

export const fallbackModel = "@cf/meta/llama-3.1-8b-instruct-fast";

function textOf(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const body = value as Record<string, unknown>;
  if (typeof body.response === "string") return body.response;
  const result = body.result;
  if (result && typeof result === "object" && typeof (result as Record<string, unknown>).response === "string") {
    return String((result as Record<string, unknown>).response);
  }
  return "";
}

function jsonOf(source: Record<string, string>, value: unknown): Record<string, string> | null {
  const raw = textOf(value).trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { return null; }
  return validCatalog(source, parsed) ? parsed : null;
}

export async function translateFallback(ai: AiRunner, source: Record<string, string>): Promise<Record<string, string>> {
  const messages = [
    { role: "system", content: "Translate every JSON string value from English into Telugu. Return JSON only. Preserve every key and every placeholder exactly." },
    { role: "user", content: JSON.stringify(source) },
  ];
  const result = await ai.run(fallbackModel, { messages, temperature: 0, max_tokens: 4096 });
  const catalog = jsonOf(source, result);
  if (!catalog) throw new Error("locale_fallback_invalid_catalog");
  return catalog;
}
