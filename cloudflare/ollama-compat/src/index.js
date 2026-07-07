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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return Response.json({ status: "ok", provider: "cloudflare-workers-ai", model: env.MODEL });
    }
    if (request.method !== "POST" || url.pathname !== "/api/chat") {
      return Response.json({ error: "not_found" }, { status: 404 });
    }
    const body = await request.json();
    const incoming = Array.isArray(body.messages) ? body.messages : [];
    const translated = translationMessages(incoming);
    const result = await env.AI.run(env.MODEL, {
      messages: translated || incoming,
      temperature: translated ? 0 : Number(body.options?.temperature ?? 0.2),
      max_tokens: Number(body.options?.num_predict ?? 1600),
    });
    const raw = String(result?.response ?? result?.result?.response ?? "").trim();
    if (!raw) return Response.json({ error: "empty_ai_response" }, { status: 503 });
    const content = JSON.stringify({ answer: raw });
    return Response.json({
      model: body.model ?? env.MODEL,
      message: { role: "assistant", content },
      response: content,
      done: true,
    });
  },
};
