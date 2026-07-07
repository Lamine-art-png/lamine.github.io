export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return Response.json({ status: "ok", provider: "cloudflare-workers-ai" });
    }
    if (request.method !== "POST" || url.pathname !== "/api/chat") {
      return Response.json({ error: "not_found" }, { status: 404 });
    }
    const body = await request.json();
    const result = await env.AI.run(env.MODEL, {
      messages: Array.isArray(body.messages) ? body.messages : [],
      temperature: Number(body.options?.temperature ?? 0.2),
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
