import { MouseEvent as ReactMouseEvent, useCallback, useEffect, useMemo, useRef } from "react";
import { Lock } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { openCommercialBoundary } from "./CommercialBoundaryHost";
import { Integrations } from "./Integrations";

const ORDER = ["free", "professional", "team", "network", "enterprise"] as const;
type PlanId = typeof ORDER[number];
type Connector = { id: string; name: string; required_plan?: string };

type Catalog = { connectors?: Connector[] };

const TITLE_TO_PROVIDER: Record<string, string> = {
  WiseConn: "wiseconn",
  Talgil: "talgil",
  Files: "manual_csv",
  Gmail: "gmail",
  Outlook: "outlook",
  "Google Drive": "google_drive",
  Dropbox: "dropbox",
  Box: "box",
  Slack: "slack",
  Salesforce: "salesforce",
  "Google Earth Engine": "google_earth_engine",
  "Custom API": "custom_api",
  "Weather / Forecast": "weather",
  "OpenET / ET data": "openet",
};

function canonicalPlan(value: unknown): PlanId {
  const raw = String(value || "free").toLowerCase();
  const aliases: Record<string, PlanId> = { pilot: "free", pro: "professional", waterops: "professional", assurance_audit: "professional", assurance: "team" };
  const candidate = aliases[raw] || raw;
  return ORDER.includes(candidate as PlanId) ? candidate as PlanId : "free";
}

function requiredPlan(provider: string): PlanId {
  if (["manual_csv", "chat_upload"].includes(provider)) return "free";
  if (["universal_controller", "salesforce", "google_earth_engine", "custom_api"].includes(provider)) return "enterprise";
  return "professional";
}

function featureFor(provider: string) {
  if (["gmail", "outlook", "google_drive", "dropbox", "box", "slack"].includes(provider)) return "connectors.oauth_documents";
  if (["universal_controller", "salesforce", "google_earth_engine", "custom_api"].includes(provider)) return "connectors.custom_integration";
  return "connectors.live";
}

function isLocked(current: PlanId, required: PlanId) { return ORDER.indexOf(current) < ORDER.indexOf(required); }

export function MonetizedIntegrations() {
  const { currentOrganization } = useAuth();
  const currentPlan = canonicalPlan(currentOrganization?.plan);
  const catalog = usePortalResource<Catalog>(useCallback(() => apiClient.connectorHub.catalog(), []));
  const rootRef = useRef<HTMLDivElement | null>(null);

  const providerByTitle = useMemo(() => {
    const map = new Map<string, string>(Object.entries(TITLE_TO_PROVIDER));
    for (const item of catalog.data?.connectors || []) map.set(item.name, item.id);
    return map;
  }, [catalog.data]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    const annotate = () => {
      root.querySelectorAll<HTMLElement>("article").forEach((article) => {
        const title = article.querySelector("h3")?.textContent?.trim();
        if (!title) return;
        const provider = providerByTitle.get(title);
        if (!provider) return;
        const required = requiredPlan(provider);
        const locked = isLocked(currentPlan, required);
        const button = article.querySelector<HTMLButtonElement>("button");
        const existing = article.querySelector<HTMLElement>("[data-agroai-commercial-lock-badge]");

        if (locked) {
          article.dataset.agroaiCommercialLocked = "true";
          article.dataset.agroaiProvider = provider;
          article.dataset.agroaiRequiredPlan = required;
          article.style.boxShadow = "inset 0 0 0 1px rgba(45,106,79,0.12)";
          if (button) {
            if (!button.dataset.agroaiOriginalLabel) button.dataset.agroaiOriginalLabel = button.textContent || "Connect";
            button.textContent = `Upgrade to ${required === "enterprise" ? "Enterprise" : "Professional"}`;
            button.style.background = "#0D2B1E";
          }
          if (!existing && button) {
            const badge = document.createElement("div");
            badge.dataset.agroaiCommercialLockBadge = "true";
            badge.textContent = `🔒 ${required === "enterprise" ? "Enterprise" : "Professional"} required`;
            badge.style.cssText = "margin:0 0 10px;padding:8px 10px;border-radius:9px;background:#F0F7EE;border:1px solid #CFE1CB;color:#1F5A43;font-size:11px;font-weight:600;text-align:center;";
            button.parentElement?.insertBefore(badge, button);
          }
        } else {
          delete article.dataset.agroaiCommercialLocked;
          delete article.dataset.agroaiProvider;
          delete article.dataset.agroaiRequiredPlan;
          article.style.boxShadow = "";
          existing?.remove();
          if (button?.dataset.agroaiOriginalLabel) {
            button.textContent = button.dataset.agroaiOriginalLabel;
            delete button.dataset.agroaiOriginalLabel;
            button.style.background = "";
          }
        }
      });
    };

    annotate();
    const observer = new MutationObserver(annotate);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [currentPlan, providerByTitle]);

  function capture(event: ReactMouseEvent<HTMLDivElement>) {
    const target = event.target as HTMLElement;
    const button = target.closest("button");
    const article = button?.closest<HTMLElement>("article[data-agroai-commercial-locked='true']");
    if (!article) return;
    event.preventDefault();
    event.stopPropagation();
    const provider = article.dataset.agroaiProvider || "connector";
    const recommended = article.dataset.agroaiRequiredPlan || "professional";
    openCommercialBoundary({ status: 402, code: "upgrade_required", feature: featureFor(provider), recommended_plan: recommended, message: `${recommended === "enterprise" ? "Enterprise" : "Professional"} is required to connect ${article.querySelector("h3")?.textContent || "this source"}.`, source: "connectors" });
  }

  return <div ref={rootRef} onClickCapture={capture}>
    <div className="mx-8 mt-6 flex items-start gap-3 rounded-2xl border border-[#CFE1CB] bg-[#F0F7EE] px-4 py-3 text-[#1F5A43]">
      <Lock className="mt-0.5 h-4 w-4 shrink-0" />
      <div><div className="text-[12px] font-semibold">Connector access follows your commercial plan</div><div className="mt-1 text-[11px] leading-5 opacity-80">Locked sources show the exact required tier before authorization starts. Manual evidence upload remains available on Free.</div></div>
    </div>
    <Integrations />
  </div>;
}
