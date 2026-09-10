import faepWorker from "./index.js";

const OFFICIAL_LOGO_URL = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/customer-portal/assets/agro-ai-logo.png";

async function serveOfficialLogo(request) {
  const upstream = await fetch(OFFICIAL_LOGO_URL, { redirect: "follow" });

  if (!upstream.ok) {
    return new Response("Logo unavailable", {
      status: 502,
      headers: { "cache-control": "no-store" },
    });
  }

  const headers = new Headers(upstream.headers);
  headers.set("content-type", "image/png");
  headers.set("cache-control", "public, max-age=86400, s-maxage=86400");
  headers.set("x-content-type-options", "nosniff");

  return new Response(request.method === "HEAD" ? null : upstream.body, {
    status: 200,
    headers,
  });
}

// Dedicated, no-index Portuguese intake experience for the Sistema FAEP delegation.
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Public campaign URL: https://faep.agroai-pilot.com
    if (url.pathname === "/" || url.pathname === "") {
      url.pathname = "/faep";
      request = new Request(url.toString(), request);
    }

    // Serve the current official dark-green AGRO-AI logo from the canonical repository asset.
    // This avoids depending on the marketing site's asset routing from the FAEP subdomain.
    if (url.pathname.startsWith("/attached_assets/")) {
      return serveOfficialLogo(request);
    }

    return faepWorker.fetch(request, env, ctx);
  },
};
