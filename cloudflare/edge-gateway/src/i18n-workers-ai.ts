const MODEL = "@cf/zai-org/glm-4.7-flash";
const PLACEHOLDER_RE = /\{[A-Za-z_][A-Za-z0-9_]*\}/g;
const CHUNK_SIZE = 36;
const MAX_PARALLEL = 4;

export type AiRunner = {
  run(model: string, input: unknown): Promise<unknown>;
};

function stripFences(value: string): string {
  return value.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "").trim();
}

function aiText(result: unknown): string {
  if (!result || typeof result !== "object") return "";
  const body = result as Record<string, unknown>;
  if (typeof body.response === "string") return body.response;
  const nested = body.result;
  if (nested && typeof nested === "object" && typeof (nested as Record<string, unknown>).response === "string") {
    return String((nested as Record<string, unknown>).response);
  }
  const choices = body.choices;
  if (Array.isArray(choices)) {
    const first = choices[0] as Record<string, unknown> | undefined;
    const message = first?.message as Record<string, unknown> | undefined;
    if (typeof message?.content === "string") return message.content;
  }
  return "";
}

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

async function translateChunk(ai: AiRunner, locale: string, source: Record<string, string>): Promise<Record<string, string>> {
  const messages = [
    {
      role: "system",
      content: `Translate every JSON string value from English into locale ${locale}. Return one JSON object only. Preserve every key exactly. Preserve placeholders in braces exactly. Preserve AGRO-AI, product names, URLs, units, numbers, and Markdown syntax. Translate naturally and concisely.`,
    },
    { role: "user", content: JSON.stringify(source) },
  ];
  let result = await ai.run(MODEL, { messages, temperature: 0, max_completion_tokens: 4096 });
  let raw = stripFences(aiText(result));
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { parsed = null; }
  if (!validCatalog(source, parsed)) {
    result = await ai.run(MODEL, {
      messages: [
        ...messages,
        { role: "assistant", content: raw },
        { role: "user", content: "Repair the answer. Return JSON only with exactly the original keys, non-empty translated values, and unchanged placeholders." },
      ],
      temperature: 0,
      max_completion_tokens: 4096,
    });
    raw = stripFences(aiText(result));
    try { parsed = JSON.parse(raw); } catch { parsed = null; }
  }
  if (!validCatalog(source, parsed)) throw new Error("workers_ai_invalid_catalog");
  return parsed;
}

export async function translateCatalog(ai: AiRunner, locale: string, source: Record<string, string>): Promise<Record<string, string>> {
  const entries = Object.entries(source);
  const chunks: Record<string, string>[] = [];
  for (let index = 0; index < entries.length; index += CHUNK_SIZE) {
    chunks.push(Object.fromEntries(entries.slice(index, index + CHUNK_SIZE)));
  }
  const output: Record<string, string> = {};
  for (let index = 0; index < chunks.length; index += MAX_PARALLEL) {
    const results = await Promise.all(chunks.slice(index, index + MAX_PARALLEL).map((chunk) => translateChunk(ai, locale, chunk)));
    for (const result of results) Object.assign(output, result);
  }
  if (!validCatalog(source, output)) throw new Error("workers_ai_catalog_reconciliation_failed");
  return output;
}

export async function catalogSha256(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map((item) => item.toString(16).padStart(2, "0")).join("");
}

export const workersAiModel = MODEL;
export const workersAiChunkSize = CHUNK_SIZE;
