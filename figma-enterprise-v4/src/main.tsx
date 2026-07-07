import { createRoot } from "react-dom/client";
import { CommercialBoundaryHost } from "./app/components/CommercialBoundaryHost";
import "./styles/index.css";

function bootFailure(error: unknown) {
  const root = document.getElementById("root");
  const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error || "Unknown frontend boot error");
  if (!root) return;
  root.innerHTML = `
    <div style="min-height:100vh;background:#F6F4EE;color:#10231B;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:48px 24px;box-sizing:border-box;">
      <div style="max-width:760px;margin:0 auto;background:#FFFDF8;border:1px solid #D6DDD0;border-radius:24px;padding:32px;box-shadow:0 20px 60px rgba(16,35,27,.08);">
        <div style="font-size:12px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;color:#2D6A4F;">AGRO-AI Enterprise Portal</div>
        <h1 style="margin:12px 0 0;font-size:30px;line-height:1.15;">Frontend recovery mode</h1>
        <p style="margin:12px 0 0;color:#65736A;font-size:14px;line-height:1.7;">The portal JavaScript failed during boot, so AGRO-AI displayed this recovery screen instead of a blank page.</p>
        <pre style="margin-top:18px;white-space:pre-wrap;word-break:break-word;background:#F6F4EE;border:1px solid #E2D8C8;border-radius:14px;padding:14px;color:#7A2E0E;font-size:12px;line-height:1.5;">${message.replace(/[&<>'"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[ch] || ch))}</pre>
        <button id="agroai-clear-session" style="margin-top:20px;background:#10231B;color:white;border:0;border-radius:10px;padding:10px 14px;font-size:13px;font-weight:600;cursor:pointer;">Clear session and reload</button>
      </div>
    </div>
  `;
  document.getElementById("agroai-clear-session")?.addEventListener("click", () => {
    window.localStorage.removeItem("agroai_access_token");
    window.location.href = "/";
  });
}

const rootEl = document.getElementById("root");
if (!rootEl) {
  bootFailure(new Error("Missing #root element"));
} else {
  import("./app/App.tsx")
    .then(({ default: App }) => {
      createRoot(rootEl).render(<CommercialBoundaryHost><App /></CommercialBoundaryHost>);
    })
    .catch(bootFailure);
}
