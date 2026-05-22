import type { Env } from "../cloudflare/env";
import type { LLMReportPayload } from "../../schemas/report";
import { parseStrictJsonPayload } from "./jsonGuard";
import { buildReportPrompt, type LLMReportInput } from "./prompt";

const ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages";

export async function generateLlmReportPayload(
  env: Pick<Env, "AGROAI_LLM_API_KEY" | "AGROAI_LLM_MODEL">,
  input: LLMReportInput,
): Promise<LLMReportPayload | null> {
  if (!env.AGROAI_LLM_API_KEY) return null;

  try {
    const response = await fetch(ANTHROPIC_MESSAGES_URL, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": env.AGROAI_LLM_API_KEY,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: env.AGROAI_LLM_MODEL || "claude-sonnet-4-6",
        max_tokens: 900,
        temperature: 0,
        messages: [
          {
            role: "user",
            content: buildReportPrompt(input),
          },
        ],
      }),
    });

    if (!response.ok) return null;
    const payload = await response.json() as { content?: Array<{ type?: string; text?: string }> };
    const text = payload.content?.find((part) => part.type === "text")?.text;
    return text ? parseStrictJsonPayload(text) : null;
  } catch (_error) {
    return null;
  }
}

