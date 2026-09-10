import faepWorker from "./index.js";

const OFFICIAL_LOGO_URL = "https://agroai-pilot.com/images/agroai-logo-dark-green.png";
const OFFICIAL_LOGO_PATH = "/brand/agroai-logo-dark-green-v20260910.png";
const LEGACY_LOGO_PATH = "/attached_assets/Copy of AGRO-AI (1)_1763408301972.png";

async function serveOfficialLogo(request) {
  const upstream = await fetch(OFFICIAL_LOGO_URL, {
    redirect: "follow",
    headers: { accept: "image/png,image/*;q=0.8,*/*;q=0.5" },
  });

  if (!upstream.ok) {
    return new Response("Logo unavailable", {
      status: 502,
      headers: { "cache-control": "no-store" },
    });
  }

  const headers = new Headers();
  headers.set("content-type", upstream.headers.get("content-type") || "image/png");
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("x-content-type-options", "nosniff");
  headers.set("x-agroai-logo-source", "website-dark-green");

  return new Response(request.method === "HEAD" ? null : upstream.body, {
    status: 200,
    headers,
  });
}

function patchFaepHtml(response) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("text/html")) return response;

  return response.text().then((html) => {
    const logoSrc = `${OFFICIAL_LOGO_PATH}?v=20260910-1`;
    const patched = html
      .replaceAll(LEGACY_LOGO_PATH, logoSrc)
      .replaceAll("/images/agroai-logo-dark-green.png", logoSrc);

    const headers = new Headers(response.headers);
    headers.set("cache-control", "no-store, max-age=0");
    headers.set("x-agroai-logo-version", "dark-green-20260910-1");

    return new Response(patched, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
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

    // Use a new, versioned browser path so no previously cached green/yellow logo can survive.
    if (url.pathname === OFFICIAL_LOGO_PATH || url.pathname === LEGACY_LOGO_PATH) {
      return serveOfficialLogo(request);
    }

    const response = await faepWorker.fetch(request, env, ctx);
    return patchFaepHtml(response);
  },
};
