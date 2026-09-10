import faepWorker from "../../faep-intake-worker/src/index.js";

const OFFICIAL_AGROAI_LOGO = "https://raw.githubusercontent.com/Lamine-art-png/lamine.github.io/main/customer-portal/assets/agro-ai-logo.png";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Keep the public link extremely simple: https://faep.agroai-pilot.com
    if (url.pathname === "/" || url.pathname === "") {
      url.pathname = "/faep";
      request = new Request(url.toString(), request);
    }

    // Always serve the current official dark-green AGRO-AI logo on the FAEP form.
    // The embedded FAEP HTML still requests the legacy asset path, so intercept it
    // here and return the canonical brand asset instead of the retired logo.
    if (url.pathname.startsWith("/attached_assets/")) {
      const headers = new Headers(request.headers);
      headers.delete("host");
      return fetch(new Request(OFFICIAL_AGROAI_LOGO, {
        method: request.method,
        headers,
        redirect: "follow",
      }));
    }

    return faepWorker.fetch(request, env, ctx);
  },
};
