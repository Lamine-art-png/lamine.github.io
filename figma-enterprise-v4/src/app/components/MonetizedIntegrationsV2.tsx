import { MouseEvent as ReactMouseEvent, useCallback, useEffect, useMemo, useRef } from "react";
import { Lock } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { openCommercialBoundary } from "./CommercialBoundaryHost";
import { Integrations } from "./Integrations";

const ORDER = ["free", "professional", "team", "network", "enterprise"] as const;
type PlanId = typeof ORDER[number];
type Catalog = { connectors?: { id: string; name: string }[] };

const FALLBACK: Record<string, string> = {
  WiseConn: "wiseconn", Talgil: "talgil", Files: "manual_csv", Gmail: "gmail", Outlook: "outlook",
  "Google Drive": "google_drive", Dropbox: "dropbox", Box: "box", Slack: "slack", Salesforce: "salesforce",
  "Google Earth Engine": "google_earth_engine", "Custom API": "custom_api", "Weather / Forecast": "weather", "OpenET / ET data": "openet",
};

function plan(value: unknown): PlanId {
  const raw = String(value || "free").toLowerCase();
  const aliases: Record<string, PlanId> = { pilot: "free", pro: "professional", waterops: "professional", assurance_audit: "professional", assurance: "team" };
  const next = aliases[raw] || raw;
  return ORDER.includes(next as PlanId) ? next as PlanId : "free";
}

function required(provider: string): PlanId {
  if (["manual_csv", "chat_upload"].includes(provider)) return "free";
  if (["universal_controller", "salesforce", "google_earth_engine", "custom_api"].includes(provider)) return "enterprise";
  return "professional";
}

function feature(provider: string) {
  if (["gmail", "outlook", "google_drive", "dropbox", "box", "slack"].includes(provider)) return "connectors.oauth_documents";
  if (["universal_controller", "salesforce", "google_earth_engine", "custom_api"].includes(provider)) return "connectors.custom_integration";
  return "connectors.live";
}

export function MonetizedIntegrationsV2() {
  const { currentOrganization } = useAuth();
  const current = plan(currentOrganization?.plan);
  const catalog = usePortalResource<Catalog>(useCallback(() => apiClient.connectorHub.catalog(), []));
  const rootRef = useRef<HTMLDivElement | null>(null);

  const byTitle = useMemo(() => {
    const map = new Map(Object.entries(FALLBACK));
    for (const item of catalog.data?.connectors || []) map.set(item.name, item.id);
    return map;
  }, [catalog.data]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    const annotate = () => {
      root.querySelectorAll<HTMLElement>("article").forEach((article) => {
        const title = article.querySelector("h3")?.textContent?.trim();
        const provider = title ? byTitle.get(title) : undefined;
        if (!provider) return;
        const needed = required(provider);
        const locked = ORDER.indexOf(current) < ORDER.indexOf(needed);
        const button = article.querySelector<HTMLButtonElement>("button");
        const badge = article.querySelector<HTMLElement>("[data-agroai-lock-badge]");

        if (!locked) {
          delete article.dataset.agroaiCommercialLocked;
          delete article.dataset.agroaiProvider;
          delete article.dataset.agroaiRequiredPlan;
          badge?.remove();
          if (button?.dataset.agroaiOriginalLabel) {
            if (button.textContent !== button.dataset.agroaiOriginalLabel) button.textContent = button.dataset.agroaiOriginalLabel;
            delete button.dataset.agroaiOriginalLabel;
          }
          return;
        }

        article.dataset.agroaiCommercialLocked = "true";
        article.dataset.agroaiProvider = provider;
        article.dataset.agroaiRequiredPlan = needed;
        if (!button) return;
        if (!button.dataset.agroaiOriginalLabel) button.dataset.agroaiOriginalLabel = button.textContent || "Connect";
        const label = `Upgrade to ${needed === "enterprise" ? "Enterprise" : "Professional"}`;
        if (button.textContent !== label) button.textContent = label;
        if (!badge) {
          const lock = document.createElement("div");
          lock.dataset.agroaiLockBadge = "true";
          lock.textContent = `🔒 ${needed === "enterprise" ? "Enterprise" : "Professional"} required`;
          lock.style.cssText = "margin:0 0 10px;padding:8px 10px;border-radius:9px;background:#F0F7EE;border:1px solid #CFE1CB;color:#1F5A43;font-size:11px;font-weight:600;text-align:center;";
          button.parentElement?.insertBefore(lock, button);
        }
      });
    };

    annotate();
    const timers = [0, 120, 350, 800, 1600].map((delay) => window.setTimeout(annotate, delay));
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [byTitle, current]);

  function capture(event: ReactMouseEvent<HTMLDivElement>) {
    const button = (event.target as HTMLElement).closest("button");
    const article = button?.closest<HTMLElement>("article[data-agroai-commercial-locked='true']");
    if (!article) return;
    event.preventDefault();
    event.stopPropagation();
    const provider = article.dataset.agroaiProvider || "connector";
    const target = article.dataset.agroaiRequiredPlan || "professional";
    openCommercialBoundary({ status: 402, code: "upgrade_required", feature: feature(provider), recommended_plan: target, message: `${target === "enterprise" ? "Enterprise" : "Professional"} is required to connect ${article.querySelector("h3")?.textContent || "this source"}.`, source: "connectors" });
  }

  return <div ref={rootRef} onClickCapture={capture}>
    <div className="mx-8 mt-6 flex items-start gap-3 rounded-2xl border border-[#CFE1CB] bg-[#F0F7EE] px-4 py-3 text-[#1F5A43]"><Lock className="mt-0.5 h-4 w-4 shrink-0" /><div><div className="text-[12px] font-semibold">Connector access follows your commercial plan</div><div className="mt-1 text-[11px] leading-5 opacity-80">Locked sources show the exact required tier before authorization starts. Manual evidence upload remains available on Free.</div></div></div>
    <Integrations />
  </div>;
}
