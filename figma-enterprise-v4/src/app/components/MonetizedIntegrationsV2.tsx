import { MouseEvent as ReactMouseEvent, useCallback, useEffect, useMemo, useRef } from "react";
import { Lock } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { openCommercialBoundary } from "./CommercialBoundaryHost";
import { Integrations } from "./Integrations";

const ORDER = ["free", "professional", "team", "network", "enterprise"] as const;
type PlanId = typeof ORDER[number];
type Catalog = { connectors?: { id: string; name: string; required_plan?: string }[] };
type ConnectorAccess = { provider: string; requiredPlan: PlanId };
type CommercialSummary = { quota_rows?: { metric?: string; used?: number; reserved?: number; limit?: number | null }[] };

const FALLBACK: Record<string, string> = {
  WiseConn: "wiseconn", Talgil: "talgil", Files: "manual_csv", "Chat file import": "chat_upload",
  Gmail: "gmail", Outlook: "outlook", "Google Drive": "google_drive", Dropbox: "dropbox", Box: "box",
  Slack: "slack", Salesforce: "salesforce", "Google Earth Engine": "google_earth_engine", "Custom API": "custom_api",
  "Weather / Forecast": "weather", "OpenET / ET data": "openet",
};

const IMPORT_LIMITS: Record<PlanId, number | null> = {
  free: 15,
  professional: 500,
  team: 2500,
  network: 10000,
  enterprise: null,
};

function plan(value: unknown): PlanId {
  const raw = String(value || "free").toLowerCase();
  const aliases: Record<string, PlanId> = { pilot: "free", pro: "professional", waterops: "professional", assurance_audit: "professional", assurance: "team" };
  const next = aliases[raw] || raw;
  return ORDER.includes(next as PlanId) ? next as PlanId : "free";
}

function fallbackRequired(provider: string): PlanId {
  if (["manual_csv", "chat_upload"].includes(provider)) return "free";
  if (provider === "custom_api") return "network";
  if (["universal_controller", "salesforce", "google_earth_engine"].includes(provider)) return "enterprise";
  return "professional";
}

function feature(provider: string) {
  if (["manual_csv", "chat_upload"].includes(provider)) return "connectors.manual_upload";
  if (["gmail", "outlook", "google_drive", "dropbox", "box", "slack"].includes(provider)) return "connectors.oauth_documents";
  if (provider === "custom_api") return "connectors.custom_api";
  if (["universal_controller", "salesforce", "google_earth_engine"].includes(provider)) return "connectors.custom_integration";
  return "connectors.live";
}

function planName(id: string) {
  return id === "enterprise" ? "Enterprise" : id === "network" ? "Network" : id === "team" ? "Team" : "Professional";
}

export function MonetizedIntegrationsV2() {
  const { currentOrganization } = useAuth();
  const current = plan(currentOrganization?.plan);
  const catalog = usePortalResource<Catalog>(useCallback(() => apiClient.connectorHub.catalog(), []));
  const commercial = usePortalResource<CommercialSummary>(useCallback(() => apiClient.billing.commercialSummary(), []));
  const rootRef = useRef<HTMLDivElement | null>(null);

  const evidenceUsage = useMemo(() => (commercial.data?.quota_rows || []).find((row) => row.metric === "evidence_upload"), [commercial.data]);
  const importQuotaText = useMemo(() => {
    const used = Number(evidenceUsage?.used || 0) + Number(evidenceUsage?.reserved || 0);
    const limit = evidenceUsage?.limit ?? IMPORT_LIMITS[current];
    if (limit === null || limit === undefined) return "Evidence imports: contract-configured volume";
    return `Evidence imports: ${used} / ${limit.toLocaleString()} this period`;
  }, [current, evidenceUsage]);

  const accessByTitle = useMemo(() => {
    const map = new Map<string, ConnectorAccess>();
    for (const [title, provider] of Object.entries(FALLBACK)) map.set(title, { provider, requiredPlan: fallbackRequired(provider) });
    for (const item of catalog.data?.connectors || []) {
      map.set(item.name, { provider: item.id, requiredPlan: item.required_plan ? plan(item.required_plan) : fallbackRequired(item.id) });
    }
    return map;
  }, [catalog.data]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const annotate = () => {
      root.querySelectorAll<HTMLElement>("article").forEach((article) => {
        const title = article.querySelector("h3")?.textContent?.trim();
        const access = title ? accessByTitle.get(title) : undefined;
        if (!access) return;
        const { provider, requiredPlan: needed } = access;
        const locked = ORDER.indexOf(current) < ORDER.indexOf(needed);
        const button = article.querySelector<HTMLButtonElement>("button");
        const lockBadge = article.querySelector<HTMLElement>("[data-agroai-lock-badge]");
        const quotaBadge = article.querySelector<HTMLElement>("[data-agroai-import-quota]");
        const isFileImport = ["manual_csv", "chat_upload"].includes(provider);

        if (isFileImport) {
          const badge = quotaBadge || document.createElement("div");
          badge.dataset.agroaiImportQuota = "true";
          badge.textContent = importQuotaText;
          badge.style.cssText = "margin:0 0 10px;padding:8px 10px;border-radius:9px;background:#FFF8DF;border:1px solid #E9D99A;color:#6B5A16;font-size:11px;font-weight:600;text-align:center;";
          if (!quotaBadge && button) button.parentElement?.insertBefore(badge, button);
        } else quotaBadge?.remove();

        if (!locked) {
          delete article.dataset.agroaiCommercialLocked;
          delete article.dataset.agroaiProvider;
          delete article.dataset.agroaiRequiredPlan;
          lockBadge?.remove();
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
        const label = `Upgrade to ${planName(needed)}`;
        if (button.textContent !== label) button.textContent = label;
        if (!lockBadge) {
          const lock = document.createElement("div");
          lock.dataset.agroaiLockBadge = "true";
          lock.textContent = `🔒 ${planName(needed)} required`;
          lock.style.cssText = "margin:0 0 10px;padding:8px 10px;border-radius:9px;background:#F0F7EE;border:1px solid #CFE1CB;color:#1F5A43;font-size:11px;font-weight:600;text-align:center;";
          button.parentElement?.insertBefore(lock, button);
        }
      });
    };
    annotate();
    const timers = [0, 120, 350, 800, 1600].map((delay) => window.setTimeout(annotate, delay));
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [accessByTitle, current, importQuotaText]);

  function capture(event: ReactMouseEvent<HTMLDivElement>) {
    const button = (event.target as HTMLElement).closest("button");
    const article = button?.closest<HTMLElement>("article[data-agroai-commercial-locked='true']");
    if (!article) return;
    event.preventDefault();
    event.stopPropagation();
    const provider = article.dataset.agroaiProvider || "connector";
    const target = article.dataset.agroaiRequiredPlan || "professional";
    openCommercialBoundary({ status: 402, code: "upgrade_required", feature: feature(provider), recommended_plan: target, message: `${planName(target)} is required to connect ${article.querySelector("h3")?.textContent || "this source"}.`, source: "connectors" });
  }

  return <div ref={rootRef} onClickCapture={capture}>
    <div className="mx-8 mt-6 flex items-start gap-3 rounded-2xl border border-[#CFE1CB] bg-[#F0F7EE] px-4 py-3 text-[#1F5A43]"><Lock className="mt-0.5 h-4 w-4 shrink-0" /><div><div className="text-[12px] font-semibold">Connector access follows your commercial plan</div><div className="mt-1 text-[11px] leading-5 opacity-80">Manual and chat file imports share one evidence quota: 15/month on Free, 500 on Professional, 2,500 on Team, and 10,000 on Network. Weather and OpenET start at Professional; standard Custom API access starts at Network; bespoke integrations require Enterprise.</div></div></div>
    <Integrations />
  </div>;
}
