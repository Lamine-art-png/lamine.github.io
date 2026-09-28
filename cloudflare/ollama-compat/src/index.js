import { translateWithPublicFallback } from "../../edge-gateway/src/i18n-public-translate-fallback";

const TRANSLATION_MODEL = "@cf/meta/m2m100-1.2b";
const TRANSLATION_PARALLELISM = 4;
const PROTECTED_SPLIT_RE = /(\{[A-Za-z_][A-Za-z0-9_]*\}|https?:\/\/[^\s]+|AGRO-AI)/g;

function translationRequest(messages) {
  const joined = messages.map((item) => String(item?.content || "")).join("\n");
  const locale = joined.match(/Translate every JSON string value into .*?\(([A-Za-z0-9_-]+)\)/i);
  const question = joined.match(/QUESTION:\s*(\{[^\n]+\})/i);
  if (!locale || !question) return null;
  try {
    const source = JSON.parse(question[1]);
    if (!source || typeof source !== "object" || Array.isArray(source)) return null;
    return { locale: locale[1].replace("_", "-"), source };
  } catch {
    return null;
  }
}

function authorized(request, env) {
  const expected = String(env.ORIGIN_TOKEN || "").trim();
  if (!expected) return true;
  const supplied = String(request.headers.get("authorization") || "").trim();
  return supplied === `Bearer ${expected}`;
}

function timeoutAfter(milliseconds, label) {
  return new Promise((_, reject) => {
    setTimeout(() => reject(new Error(`${label}_timeout`)), milliseconds);
  });
}

function modelText(value) {
  if (typeof value === "string") return value;
  if (value == null) return "";
  if (Array.isArray(value)) {
    const parts = value.map(modelText).filter(Boolean);
    return parts.join("\n");
  }
  if (typeof value === "object") {
    for (const key of ["content", "text", "response", "output_text", "message", "result"]) {
      if (key in value) {
        const nested = modelText(value[key]);
        if (nested) return nested;
      }
    }
    try { return JSON.stringify(value); } catch { return ""; }
  }
  return String(value);
}

function translatedText(value) {
  if (!value || typeof value !== "object") return "";
  if (typeof value.translated_text === "string") return value.translated_text.trim();
  if (value.result && typeof value.result === "object" && typeof value.result.translated_text === "string") {
    return String(value.result.translated_text).trim();
  }
  return "";
}

async function runModel(env, model, input, timeoutMs) {
  const startedAt = Date.now();
  const result = await Promise.race([
    env.AI.run(model, input),
    timeoutAfter(timeoutMs, model),
  ]);
  const raw = modelText(
    result?.response ??
      result?.result?.response ??
      result?.choices?.[0]?.message?.content ??
      result,
  ).trim();
  return {
    raw,
    model,
    latency_ms: Date.now() - startedAt,
  };
}

async function runWithFallback(env, input) {
  const primary = String(env.MODEL || "@cf/zai-org/glm-4.7-flash").trim();
  const fallback = String(env.FALLBACK_MODEL || "@cf/meta/llama-3.1-8b-instruct-fast").trim();
  const primaryTimeout = Math.max(3000, Number(env.MODEL_TIMEOUT_MS || 12000));
  const fallbackTimeout = Math.max(5000, Number(env.FALLBACK_TIMEOUT_MS || 22000));
  const failures = [];

  try {
    const result = await runModel(env, primary, input, primaryTimeout);
    if (result.raw) return { ...result, fallback_used: false };
    failures.push(`${primary}:empty`);
  } catch (error) {
    failures.push(`${primary}:${String(error?.message || error)}`);
  }

  if (!fallback || fallback === primary) {
    throw new Error(`edge_models_failed:${failures.join("|")}`);
  }

  try {
    const result = await runModel(env, fallback, input, fallbackTimeout);
    if (result.raw) return { ...result, fallback_used: true, failures };
    failures.push(`${fallback}:empty`);
  } catch (error) {
    failures.push(`${fallback}:${String(error?.message || error)}`);
  }

  throw new Error(`edge_models_failed:${failures.join("|")}`);
}

function shouldTranslate(segment) {
  return /[A-Za-z]/.test(segment) && segment.trim().length > 0;
}

async function translateSegment(env, locale, segment) {
  if (!shouldTranslate(segment)) return segment;
  const target = locale.split("-", 1)[0].toLowerCase();
  const result = await Promise.race([
    env.AI.run(TRANSLATION_MODEL, {
      text: segment,
      source_lang: "en",
      target_lang: target,
    }),
    timeoutAfter(15000, TRANSLATION_MODEL),
  ]);
  const translated = translatedText(result);
  if (!translated) throw new Error(`translation_empty:${target}`);
  const leading = segment.match(/^\s*/)?.[0] || "";
  const trailing = segment.match(/\s*$/)?.[0] || "";
  return `${leading}${translated}${trailing}`;
}

async function translateValue(env, locale, value) {
  const parts = String(value).split(PROTECTED_SPLIT_RE);
  const translated = [];
  for (const part of parts) {
    if (!part || part === "AGRO-AI" || /^\{[A-Za-z_][A-Za-z0-9_]*\}$/.test(part) || /^https?:\/\//.test(part)) {
      translated.push(part);
    } else {
      translated.push(await translateSegment(env, locale, part));
    }
  }
  return translated.join("");
}

async function translateCatalog(env, locale, source) {
  const entries = Object.entries(source);
  const output = {};
  let cursor = 0;
  async function worker() {
    while (true) {
      const index = cursor++;
      if (index >= entries.length) return;
      const [key, value] = entries[index];
      output[key] = await translateValue(env, locale, value);
    }
  }
  await Promise.all(Array.from(
    { length: Math.min(TRANSLATION_PARALLELISM, Math.max(1, entries.length)) },
    () => worker(),
  ));
  return output;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return Response.json({
        status: "ok",
        provider: "cloudflare-workers-ai",
        model: TRANSLATION_MODEL,
        chat_model: env.MODEL || null,
        fallback_model: env.FALLBACK_MODEL || null,
      });
    }
    if (request.method !== "POST" || url.pathname !== "/api/chat") {
      return Response.json({ error: "not_found" }, { status: 404 });
    }
    if (!authorized(request, env)) {
      return Response.json({ error: "unauthorized" }, { status: 401 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return Response.json({ error: "invalid_json" }, { status: 400 });
    }

    const incoming = Array.isArray(body.messages) ? body.messages : [];
    if (!incoming.length) {
      return Response.json({ error: "messages_required" }, { status: 422 });
    }

    const translation = translationRequest(incoming);
    if (translation) {
      const startedAt = Date.now();
      try {
        let catalog;
        let provider = "public_translation_provider_chain_v4";
        let model = "public-translation";
        let fallbackUsed = false;
        try {
          catalog = await translateWithPublicFallback(translation.locale, translation.source);
        } catch (publicError) {
          console.warn("public_translation_failed", String(publicError?.message || publicError));
          catalog = await translateCatalog(env, translation.locale, translation.source);
          provider = "cloudflare-workers-ai";
          model = TRANSLATION_MODEL;
          fallbackUsed = true;
        }
        const content = JSON.stringify(catalog);
        return Response.json({
          provider,
          model,
          requested_model: body.model ?? null,
          fallback_used: fallbackUsed,
          latency_ms: Date.now() - startedAt,
          translation_mode: true,
          message: { role: "assistant", content },
          response: content,
          done: true,
        });
      } catch (error) {
        console.error("edge_translation_failed", String(error?.message || error));
        return Response.json(
          { error: "edge_translation_unavailable", provider: "localization-authoring" },
          { status: 503 },
        );
      }
    }

    const input = {
      messages: incoming,
      temperature: Number(body.options?.temperature ?? 0.2),
      max_tokens: Math.max(16, Math.min(Number(body.options?.num_predict ?? 1200), 2200)),
    };

    let inference;
    try {
      inference = await runWithFallback(env, input);
    } catch (error) {
      console.error("edge_inference_failed", String(error?.message || error));
      return Response.json(
        { error: "edge_inference_unavailable", provider: "cloudflare-workers-ai" },
        { status: 503 },
      );
    }

    const content = JSON.stringify({ answer: inference.raw });
    return Response.json({
      provider: "cloudflare-workers-ai",
      model: inference.model,
      requested_model: body.model ?? null,
      fallback_used: Boolean(inference.fallback_used),
      latency_ms: inference.latency_ms,
      translation_mode: false,
      message: { role: "assistant", content },
      response: content,
      done: true,
    });
  },
};
