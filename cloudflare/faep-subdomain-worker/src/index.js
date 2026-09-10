import faepWorker from "../../faep-intake-worker/src/index.js";

const MARKETING_ORIGIN = "https://agroai-pilot.com";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Keep the public link extremely simple: https://faep.agroai-pilot.com
    if (url.pathname === "/" || url.pathname === "") {
      url.pathname = "/faep";
      request = new Request(url.toString(), request);
    }

    // The FAEP page uses the existing canonical AGRO-AI website logo asset.
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
