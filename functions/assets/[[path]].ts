interface Env {
  ASSETS: { fetch(request: Request): Promise<Response> };
}

// Hashed build assets are served with `immutable, max-age=1y` (public/_headers).
// Without this Function, a request for an asset that is not in the current
// deployment (a lazy chunk retired by a newer release, or one not yet
// propagated) falls through to the SPA shell: an HTML document returned as
// "JavaScript" and cached immutably, which permanently breaks that chunk URL
// in the customer's browser. A missing asset must be an honest, uncached 404
// so the portal's release recovery can load the current build instead.
export const onRequest: PagesFunction<Env> = async (context) => {
  const response = await context.env.ASSETS.fetch(context.request);
  const contentType = response.headers.get("content-type") || "";
  if (response.ok && !/text\/html/i.test(contentType)) return response;
  if (response.status === 304) return response;
  return new Response("AGRO-AI asset not found in the current release", {
    status: 404,
    headers: {
      "cache-control": "no-store",
      "content-type": "text/plain; charset=utf-8",
      "x-content-type-options": "nosniff",
      "x-agroai-asset": "missing",
    },
  });
};
