import { createRoot } from "react-dom/client";
import "./app/commercialBoundaryConversionLabels";
import { CommercialBoundaryHost } from "./app/components/CommercialBoundaryHost";
import "./styles/index.css";

const standalonePlatformHost = window.location.hostname.toLowerCase() === "platform.agroai-pilot.com";
const runtimeProductName = standalonePlatformHost ? "AGRO-AI Platform API" : "AGRO-AI Enterprise Portal";
const runtimeSurfaceName = standalonePlatformHost ? "developer platform" : "portal";
const automaticRecoveryKey = "agroai_frontend_cache_recovery_attempted";

// Stable, eagerly-loaded runtime identity for production smoke verification.
// Product/source contract tests validate the actual UI separately; this marker
// prevents release proof from depending on how Vite happens to split/minify UI
// copy into lazy chunks. It contains no credential or customer information.
const standalonePlatformRuntimeIdentity = [
  "platform.agroai-pilot.com",
  "Build on AGRO-AI.",
  "Verified developers can activate bounded TEST access after accepting the current developer agreements.",
  "Permanent API keys never enter browser JavaScript.",
].join(" | ");
if (standalonePlatformHost) {
  document.documentElement.dataset.agroaiPlatformRuntimeIdentity = standalonePlatformRuntimeIdentity;
}

document.title = runtimeProductName;
const manifestLink = document.querySelector<HTMLLinkElement>('link[rel="manifest"]');
if (standalonePlatformHost && manifestLink) manifestLink.href = "/platform.webmanifest";

function isStaleFrontendAssetError(message: string): boolean {
  const htmlAsJavaScript = /text\/html/i.test(message)
    && /(javascript|module)/i.test(message)
    && /(mime|expected)/i.test(message);
  const retiredAsset = /AGRO-AI frontend asset unavailable/i.test(message)
    || /Failed to fetch dynamically imported module/i.test(message);
  return htmlAsJavaScript || retiredAsset;
}

async function repairFrontendRuntime(clearSession = false) {
  if (clearSession) window.localStorage.removeItem("agroai_access_token");

  if ("caches" in window) {
    const names = await window.caches.keys();
    await Promise.all(
      names
        .filter((name) => name.startsWith("agroai-shell-"))
        .map((name) => window.caches.delete(name)),
    );
  }

  if ("serviceWorker" in navigator) {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registrations.map((registration) => registration.unregister()));
  }

  const recoveryUrl = new URL("/", window.location.origin);
  recoveryUrl.searchParams.set("frontend_recovery", Date.now().toString());
  window.location.replace(recoveryUrl.toString());
}

function renderBootFailure(message: string) {
  const root = document.getElementById("root");
  if (!root) return;
  root.innerHTML = `
    <div style="min-height:100vh;background:#F6F4EE;color:#10231B;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:48px 24px;box-sizing:border-box;">
      <div style="max-width:760px;margin:0 auto;background:#FFFDF8;border:1px solid #D6DDD0;border-radius:24px;padding:32px;box-sizing:border-box;box-shadow:0 20px 60px rgba(16,35,27,.08);">
        <div style="font-size:12px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;color:#2D6A4F;">${runtimeProductName}</div>
        <h1 style="margin:12px 0 0;font-size:30px;line-height:1.15;">Frontend recovery mode</h1>
        <p style="margin:12px 0 0;color:#65736A;font-size:14px;line-height:1.7;">The ${runtimeSurfaceName} JavaScript failed during boot. This is usually caused by an outdated browser cache after a deployment.</p>
        <pre style="margin-top:18px;white-space:pre-wrap;word-break:break-word;background:#F6F4EE;border:1px solid #E2D8C8;border-radius:14px;padding:14px;color:#7A2E0E;font-size:12px;line-height:1.5;">${message.replace(/[&<>'"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[ch] || ch))}</pre>
        <button id="agroai-repair-frontend" style="margin-top:20px;background:#10231B;color:white;border:0;border-radius:10px;padding:10px 14px;font-size:13px;font-weight:600;cursor:pointer;">Repair browser cache and reload</button>
      </div>
    </div>
  `;
  document.getElementById("agroai-repair-frontend")?.addEventListener("click", async (event) => {
    const button = event.currentTarget as HTMLButtonElement;
    button.disabled = true;
    button.textContent = "Repairing…";
    try {
      await repairFrontendRuntime(false);
    } catch {
      window.localStorage.removeItem("agroai_access_token");
      window.location.href = "/?frontend_recovery=fallback";
    }
  });
}

function bootFailure(error: unknown) {
  const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error || "Unknown frontend boot error");

  if (isStaleFrontendAssetError(message)
      && window.sessionStorage.getItem(automaticRecoveryKey) !== "true") {
    window.sessionStorage.setItem(automaticRecoveryKey, "true");
    void repairFrontendRuntime(false).catch(() => renderBootFailure(message));
    return;
  }

  renderBootFailure(message);
}

const deploymentEnvironment = String(import.meta.env.VITE_DEPLOYMENT_ENVIRONMENT || "").trim();
if ("serviceWorker" in navigator && !import.meta.env.DEV
    && ["production", "staging"].includes(deploymentEnvironment)) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register(`/sw.js?env=${deploymentEnvironment}`, {
      updateViaCache: "none",
    }).then((registration) => {
      void registration.update().catch(() => undefined);
      registration.addEventListener("updatefound", () => {
        const worker = registration.installing;
        worker?.addEventListener("statechange", () => {
          if (worker.state === "installed" && navigator.serviceWorker.controller) {
            window.dispatchEvent(new CustomEvent("agroai:sw-update", { detail: { registration } }));
          }
        });
      });
    }).catch(() => undefined);
  });
}

const rootEl = document.getElementById("root");
if (!rootEl) {
  bootFailure(new Error("Missing #root element"));
} else {
  import("./app/App.tsx")
    .then(({ default: App }) => {
      window.sessionStorage.removeItem(automaticRecoveryKey);
      createRoot(rootEl).render(<CommercialBoundaryHost><App /></CommercialBoundaryHost>);

      const fieldContextIsNative = window.location.pathname === "/intelligence"
        && new URLSearchParams(window.location.search || "").has("field_observation_id");

      // Field Intelligence remains isolated from portal startup. On the native
      // contextual Intelligence route, React owns the entire linked-observation
      // flow so the older auto-send bridges stay out and cannot double-submit.
      if (!fieldContextIsNative) {
        void import("./app/fieldIntelligence/directWorkflowRuntime")
          .then(() => import("./app/fieldIntelligence/operatingLoopRuntime"))
          .then(() => import("./app/fieldIntelligence/operatingLoopContextGuard"))
          .catch((error) => console.error("AGRO-AI Field Intelligence operating loop failed to load", error));
      }
    })
    .catch(bootFailure);
}