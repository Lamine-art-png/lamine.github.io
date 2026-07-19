interface Env {
  ASSETS: { fetch(request: Request): Promise<Response> };
  PLATFORM_API_MARKETING_ENABLED?: string;
}

export const onRequest: PagesFunction<Env> = async (context) => {
  if (String(context.env.PLATFORM_API_MARKETING_ENABLED || "").toLowerCase() !== "true") {
    return new Response("Not found", {
      status: 404,
      headers: {
        "cache-control": "no-store",
        "content-type": "text/plain; charset=utf-8",
        "x-robots-tag": "noindex, nofollow",
      },
    });
  }
  const url = new URL(context.request.url);
  url.pathname = "/platform-api/index.html";
  const response = await context.env.ASSETS.fetch(new Request(url, context.request));
  const headers = new Headers(response.headers);
  headers.set("x-content-type-options", "nosniff");
  headers.set("referrer-policy", "strict-origin-when-cross-origin");
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
};
