import { ReactNode, useEffect, useMemo, useState } from "react";
import { ArrowRight, Check, Lock, X } from "lucide-react";
import { apiClient } from "../api/client";
import { useLocale } from "../hooks/useLocale";
import { usePortalCopy } from "../hooks/usePortalCopy";
import { formatTranslation } from "../i18n";
import {
  CAPABILITY_KEY,
  FEATURE_TITLE_KEY,
  METRIC_KEY,
  ORDER,
  PLAN,
  canonicalPlan,
  isCommercialQuota,
  nextPlan,
  shouldShowCommercialBoundary,
  usagePercent,
  type CommercialBoundaryDetail,
  type PlanId,
} from "./commercialBoundaryViewModel";

export const COMMERCIAL_BOUNDARY_EVENT = "agroai:commercial-boundary";
export type { CommercialBoundaryDetail } from "./commercialBoundaryViewModel";

const DEMO_BOOKING_URL = "https://agroai-pilot.com/book-a-demo";

type Translate = (key: string) => string;
type Copy = (value: string) => string;

function metricLabel(metric: string | undefined, t: Translate) {
  if (!metric) return t("commercialBoundary.planUsage");
  return t(METRIC_KEY[String(metric).trim().toLowerCase()] || "commercialBoundary.planLimit");
}

function capabilityLabel(feature: string | undefined, t: Translate) {
  if (!feature) return "";
  return t(CAPABILITY_KEY[feature] || "commercialBoundary.restrictedCapability");
}

function unlockCopyKey(detail: CommercialBoundaryDetail) {
  if (isCommercialQuota(detail)) return "commercialBoundary.unlock.quota";
  if (["reports.generate", "reports.pdf_export", "reports.email_delivery"].includes(String(detail.feature || ""))) return "commercialBoundary.unlock.reports";
  if (detail.feature === "connectors.custom_api") return "commercialBoundary.unlock.connectorsCustomApi";
  if (detail.feature === "connectors.custom_integration") return "commercialBoundary.unlock.connectorsCustomIntegration";
  if (["connectors.live", "connectors.oauth_documents"].includes(String(detail.feature || ""))) return "commercialBoundary.unlock.connectorsLive";
  if (detail.feature === "team.invite") return "commercialBoundary.unlock.team";
  if (detail.feature === "admin.requests") return "commercialBoundary.unlock.requests";
  if (detail.feature === "intelligence.deep_analysis") return "commercialBoundary.unlock.deepAnalysis";
  return "";
}

function reasonText(detail: CommercialBoundaryDetail, t: Translate, tx: Copy) {
  if (["connectors_v3", "reports", "team", "requests"].includes(String(detail.source || "")) && detail.conversion_context?.trim()) {
    return tx(detail.conversion_context.trim());
  }
  const key = unlockCopyKey(detail);
  if (key) return t(key);
  const feature = capabilityLabel(detail.feature, t);
  const metric = detail.metric ? metricLabel(detail.metric, t) : "";
  if (feature && metric) return formatTranslation(t("commercialBoundary.reasonFeatureMetric"), { feature, metric });
  if (feature) return formatTranslation(t("commercialBoundary.reasonFeature"), { feature });
  if (metric) return formatTranslation(t("commercialBoundary.reasonMetric"), { metric });
  return t("commercialBoundary.reason");
}

function planPrice(id: PlanId, t: Translate) {
  const plan = PLAN[id];
  if (plan.customPrice) return t("commercialBoundary.customPrice");
  if (id === "free") return plan.priceAmount || "$0";
  return `${plan.priceAmount || ""}${t("commercialBoundary.perMonth")}`;
}

function CompactPlanPrice({ id, t }: { id: PlanId; t: Translate }) {
  const value = planPrice(id, t);
  const match = value.match(/^(\$[\d,]+)(\/(?:month|mois))$/i);
  if (!match) return <span className="max-w-full break-words text-right text-[11px] font-semibold leading-4 text-[#2D6A4F]">{value}</span>;
  return <span className="flex min-w-0 max-w-full flex-wrap items-baseline justify-end gap-x-1 text-[#2D6A4F]">
    <span className="text-[12px] font-semibold leading-4">{match[1]}</span>
    <span className="whitespace-nowrap text-[9px] font-semibold leading-4 opacity-80">{match[2]}</span>
  </span>;
}

export function openCommercialBoundary(detail: CommercialBoundaryDetail) {
  window.dispatchEvent(new CustomEvent(COMMERCIAL_BOUNDARY_EVENT, { detail }));
}

export function CommercialBoundaryHost({ children }: { children: ReactNode }) {
  const [detail, setDetail] = useState<CommercialBoundaryDetail | null>(null);
  const [currentPlan, setCurrentPlan] = useState<PlanId>("free");

  useEffect(() => {
    const handler = (event: Event) => {
      const next = (event as CustomEvent<CommercialBoundaryDetail>).detail || {};
      if (!shouldShowCommercialBoundary(next)) return;
      setDetail(next);
      apiClient.account.me().then((response: any) => setCurrentPlan(canonicalPlan(response?.plan?.id || response?.organization?.plan))).catch(() => null);
    };
    window.addEventListener(COMMERCIAL_BOUNDARY_EVENT, handler);
    return () => window.removeEventListener(COMMERCIAL_BOUNDARY_EVENT, handler);
  }, []);

  const target = useMemo(() => {
    if (!detail) return nextPlan(currentPlan);
    const requested = detail.recommended_plan ? canonicalPlan(detail.recommended_plan) : null;
    if (requested && ORDER.indexOf(requested) > ORDER.indexOf(currentPlan)) return requested;
    return currentPlan === "enterprise" ? "enterprise" : nextPlan(currentPlan);
  }, [detail, currentPlan]);

  return <>
    {children}
    {detail ? <CommercialBoundaryDialog detail={detail} currentPlan={currentPlan} target={target} onClose={() => setDetail(null)} /> : null}
  </>;
}

function CommercialBoundaryDialog({
  detail,
  currentPlan,
  target,
  onClose,
}: {
  detail: CommercialBoundaryDetail;
  currentPlan: PlanId;
  target: PlanId;
  onClose: () => void;
}) {
  const { t } = useLocale();
  const { tx } = usePortalCopy(["paywall", "shared"]);
  const isQuota = isCommercialQuota(detail);
  const featureTitleKey = detail.feature ? FEATURE_TITLE_KEY[detail.feature] : undefined;
  const title = isQuota
    ? t("commercialBoundary.title.quota")
    : featureTitleKey
      ? t(featureTitleKey)
      : detail.code === "subscription_inactive"
        ? t("commercialBoundary.title.restore")
        : t("commercialBoundary.title.upgrade");
  const body = isQuota ? t("commercialBoundary.body.quota") : t("commercialBoundary.body.unavailable");
  const href = target === "enterprise"
    ? DEMO_BOOKING_URL
    : `/pricing?upgrade=${target}${detail.feature ? `&feature=${encodeURIComponent(detail.feature)}` : ""}${detail.metric ? `&metric=${encodeURIComponent(detail.metric)}` : ""}`;
  const targetName = t(PLAN[target].nameKey);
  const primaryAction = target === "enterprise"
    ? t("commercialBoundary.talkToSales")
    : formatTranslation(t("commercialBoundary.upgradeTo"), { plan: targetName });

  return <div className="fixed inset-0 z-[120] flex items-center justify-center bg-[#061D15]/80 px-4 py-8 backdrop-blur-[2px]" role="dialog" aria-modal="true" aria-label={title}>
    <div className="relative w-full max-w-[880px] overflow-hidden rounded-[26px] border border-white/10 bg-[#FFFDF8] shadow-[0_32px_120px_rgba(0,0,0,0.42)]">
      <button type="button" onClick={onClose} aria-label={t("commercialBoundary.close")} className="absolute right-4 top-4 z-10 flex h-9 w-9 items-center justify-center rounded-full border border-[#D6DDD0] bg-white text-[#65736A]"><X className="h-4 w-4" /></button>
      <div className="grid md:grid-cols-[0.92fr_1.08fr]">
        <section className="flex flex-col justify-between bg-[#0D2B1E] p-7 text-white md:p-9">
          <div>
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#DDEB8F] text-[#10231B]"><Lock className="h-5 w-5" /></div>
            <div className="mt-6 text-[11px] font-semibold uppercase tracking-[0.2em] text-white/50">{t("commercialBoundary.accessEyebrow")}</div>
            <h2 className="mt-3 text-[30px] font-semibold leading-tight tracking-tight">{title}</h2>
            <p className="mt-4 text-[14px] leading-7 text-white/70">{body}</p>
          </div>
          {isQuota ? <div className="mt-8 rounded-2xl border border-white/10 bg-white/5 p-4">
            <div className="flex items-center justify-between text-[12px]"><span className="text-white/60">{metricLabel(detail.metric, t)}</span><span className="font-semibold">{Number(detail.used || 0) + Number(detail.reserved || 0)} / {detail.limit ?? "—"}</span></div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-[#DDEB8F]" style={{ width: `${usagePercent(detail)}%` }} /></div>
            <div className="mt-2 text-[11px] text-white/45">{t("commercialBoundary.quotaReset")}</div>
          </div> : null}
        </section>
        <section className="min-w-0 p-6 md:p-8">
          <div className="grid min-w-0 gap-4 sm:grid-cols-2"><PlanCard id={currentPlan} label={t("commercialBoundary.currentPlan")} t={t} /><PlanCard id={target} label={t("commercialBoundary.recommended")} highlighted t={t} /></div>
          <div className="mt-6 rounded-2xl border border-[#CFE1CB] bg-[#F0F7EE] p-4">
            <div className="text-[12px] font-semibold text-[#10231B]">{t("commercialBoundary.why")}</div>
            <p className="mt-2 text-[12px] leading-6 text-[#4F675B]">{reasonText(detail, t, tx)}</p>
          </div>
          <div className="mt-6 flex flex-wrap gap-3"><a href={href} className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#0D2B1E] px-5 text-[13px] font-semibold text-white">{primaryAction}<ArrowRight className="h-4 w-4" /></a><button type="button" onClick={onClose} className="h-11 rounded-xl border border-[#D6DDD0] bg-white px-5 text-[13px] font-semibold text-[#10231B]">{t("commercialBoundary.notNow")}</button></div>
        </section>
      </div>
    </div>
  </div>;
}

function PlanCard({ id, label, highlighted = false, t }: { id: PlanId; label: string; highlighted?: boolean; t: Translate }) {
  const plan = PLAN[id];
  return <article className="min-w-0 overflow-hidden rounded-2xl p-4" style={{ background: highlighted ? "#EEF8E8" : "#F6F4EE", border: `1px solid ${highlighted ? "#A7CFAF" : "#D6DDD0"}` }}>
    <div className="text-[10px] font-semibold uppercase tracking-[0.16em]" style={{ color: highlighted ? "#1F7350" : "#7A877F" }}>{label}</div>
    <div className="mt-2 grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2"><h3 className="min-w-0 whitespace-nowrap text-[15px] font-semibold leading-6 tracking-[-0.015em] text-[#10231B]">{t(plan.nameKey)}</h3><CompactPlanPrice id={id} t={t} /></div>
    <div className="mt-4 space-y-2">{plan.bullets.map((key) => <div key={key} className="flex min-w-0 gap-2 text-[11px] leading-5 text-[#65736A]"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#2D6A4F]" /><span className="min-w-0 break-words">{t(key)}</span></div>)}</div>
  </article>;
}

const COMMERCIAL_BOUNDARY_LITERAL_INVENTORY = [
  { label: "AGRO-AI access" },
  { label: "Usage is enforced on the backend and resets with the commercial period." },
  { label: "Current plan" },
  { label: "Recommended" },
  { label: "What you unlock" },
  { label: "Not now" },
  { label: "Close upgrade message" },
  { label: "Free" },
  { label: "Professional" },
  { label: "Team" },
  { label: "Network" },
  { label: "Enterprise" },
] as const;
void COMMERCIAL_BOUNDARY_LITERAL_INVENTORY;
