function translationMessages(messages) {
  const joined = messages.map((item) => String(item?.content || "")).join("\n");
  const locale = joined.match(/Translate every JSON string value into .*?\(([A-Za-z0-9_-]+)\)/i);
  const question = joined.match(/QUESTION:\s*(\{[^\n]+\})/i);
  if (!locale || !question) return null;
  try {
    const source = JSON.parse(question[1]);
    if (!source || typeof source !== "object" || Array.isArray(source)) return null;
    return [
      {
        role: "system",
        content:
          `Translate every JSON string value from English into locale ${locale[1]}. ` +
          "Return one JSON object only. Preserve every key and every placeholder in braces exactly. " +
          "Translate naturally and concisely. Do not add explanations.",
      },
      { role: "user", content: JSON.stringify(source) },
    ];
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

async function runModel(env, model, input, timeoutMs) {
  const startedAt = Date.now();
  const result = await Promise.race([
    env.AI.run(model, input),
    timeoutAfter(timeoutMs, model),
  ]);
  const raw = String(
    result?.response ??
      result?.result?.response ??
      result?.choices?.[0]?.message?.content ??
      "",
  ).trim();
  return {
    raw,
    model,
    latency_ms: Date.now() - startedAt,
  };
}

async function runWithFallback(env, input) {
  const primary = String(env.MODEL || "@cf/meta/llama-3.1-8b-instruct-fast").trim();
  const fallback = String(env.FALLBACK_MODEL || "@cf/qwen/qwen3-30b-a3b-fp8").trim();
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return Response.json({
        status: "ok",
        provider: "cloudflare-workers-ai",
        model: env.MODEL,
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

    const translated = translationMessages(incoming);
    const input = {
      messages: translated || incoming,
      temperature: translated ? 0 : Number(body.options?.temperature ?? 0.2),
      max_tokens: Math.max(16, Math.min(Number(body.options?.num_predict ?? 1200), 2200)),
    };

    let inference;
    try {
      inference = await runWithFallback(env, input);
    } catch (error) {
      console.error("edge_inference_failed", String(error?.message || error));
      return Response.json(
        {
          error: "edge_inference_unavailable",
          provider: "cloudflare-workers-ai",
        },
        { status: 503 },
      );
    }

    const content = translated
      ? inference.raw
      : JSON.stringify({ answer: inference.raw });

    return Response.json({
      provider: "cloudflare-workers-ai",
      model: inference.model,
      requested_model: body.model ?? null,
      fallback_used: Boolean(inference.fallback_used),
      latency_ms: inference.latency_ms,
      translation_mode: Boolean(translated),
      message: { role: "assistant", content },
      response: content,
      done: true,
    });
  },
};
