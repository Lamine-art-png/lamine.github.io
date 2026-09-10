import faepWorker from "./index.js";

const MARKETING_ORIGIN = "https://agroai-pilot.com";

// Dedicated, no-index Portuguese intake experience for the Sistema FAEP delegation.
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Public campaign URL: https://faep.agroai-pilot.com
    if (url.pathname === "/" || url.pathname === "") {
      url.pathname = "/faep";
      request = new Request(url.toString(), request);
    }

    // Reuse the canonical AGRO-AI logo asset already served by the marketing site.
    if (url.pathname.startsWith("/attached_assets/")) {
      const assetUrl = new URL(url.pathname + url.search, MARKETING_ORIGIN);
      const headers = new Headers(request.headers);
      headers.delete("host");
      return fetch(new Request(assetUrl, {
        method: request.method,
        headers,
        redirect: "follow",
      }));
    }

    return faepWorker.fetch(request, env, ctx);
  },
};
