import { ReactNode, useEffect, useMemo, useState } from "react";
import { ArrowRight, Check, Lock, X } from "lucide-react";
import { apiClient } from "../api/client";

export const COMMERCIAL_BOUNDARY_EVENT = "agroai:commercial-boundary";

export type CommercialBoundaryDetail = {
  status?: number;
  code?: string;
  feature?: string;
  feature_state?: string;
  metric?: string;
  used?: number;
  reserved?: number;
  limit?: number;
  remaining?: number;
  recommended_plan?: string;
  message?: string;
  source?: string;
};

type PlanId = "free" | "professional" | "team" | "network" | "enterprise";
const ORDER: PlanId[] = ["free", "professional", "team", "network", "enterprise"];
const PLAN: Record<PlanId, { name: string; price: string; bullets: string[] }> = {
  free: { name: "Free", price: "$0", bullets: ["1 workspace", "25 AGRO-AI actions/month", "10 evidence uploads/month"] },
  professional: { name: "Professional", price: "$299/mo", bullets: ["5 workspaces and 3 seats", "500 AGRO-AI actions/month", "Reports, PDFs and live connectors"] },
  team: { name: "Team", price: "$799/mo", bullets: ["25 workspaces and 10 seats", "2,500 AGRO-AI actions/month", "Shared evidence, roles and approvals"] },
  network: { name: "Network", price: "$1,500/mo", bullets: ["50 workspaces and 25 seats", "10,000 AGRO-AI actions/month", "Cross-workspace rollups and network reporting"] },
  enterprise: { name: "Enterprise", price: "Custom", bullets: ["Contract-configured capacity", "Custom integrations and governance", "Dedicated rollout and security review"] },
};

const FEATURE_TITLE: Record<string, string> = {
  "reports.generate": "Unlock commercial reports",
  "reports.pdf_export": "Unlock PDF exports",
  "reports.email_delivery": "Unlock report delivery",
  "connectors.live": "Connect live operating systems",
  "connectors.oauth_documents": "Connect approved document sources",
  "connectors.custom_integration": "Scope an enterprise integration",
  "team.invite": "Add your operating team",
  "admin.requests": "Unlock the request inbox",
  "agents.execute_safe": "Unlock agent execution",
  "agents.execute_approval_gated": "Unlock approval-gated agents",
  "intelligence.deep_analysis": "Unlock deeper analysis",
};

function canonicalPlan(value: unknown): PlanId {
  const raw = String(value || "free").toLowerCase();
  const aliases: Record<string, PlanId> = { pilot: "free", pro: "professional", waterops: "professional", assurance_audit: "professional", assurance: "team" };
  const candidate = aliases[raw] || raw;
  return ORDER.includes(candidate as PlanId) ? candidate as PlanId : "free";
}

function nextPlan(value: PlanId) {
  return ORDER[Math.min(ORDER.indexOf(value) + 1, ORDER.length - 1)];
}

function usagePercent(detail: CommercialBoundaryDetail) {
  const used = Number(detail.used || 0) + Number(detail.reserved || 0);
  const limit = Number(detail.limit || 0);
  return limit ? Math.min(100, Math.round((used / limit) * 100)) : 100;
}

export function openCommercialBoundary(detail: CommercialBoundaryDetail) {
  window.dispatchEvent(new CustomEvent(COMMERCIAL_BOUNDARY_EVENT, { detail }));
}

export function CommercialBoundaryHost({ children }: { children: ReactNode }) {
  const [detail, setDetail] = useState<CommercialBoundaryDetail | null>(null);
  const [currentPlan, setCurrentPlan] = useState<PlanId>("free");

  useEffect(() => {
    const handler = (event: Event) => {
      setDetail((event as CustomEvent<CommercialBoundaryDetail>).detail || {});
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

  const isQuota = detail?.status === 429 || detail?.code === "quota_exceeded";
  const title = isQuota ? "You’ve reached this plan limit" : detail?.feature && FEATURE_TITLE[detail.feature] ? FEATURE_TITLE[detail.feature] : detail?.code === "subscription_inactive" ? "Restore commercial access" : "Upgrade to continue";
  const body = detail?.message || (isQuota ? "Your current commercial quota is exhausted for this period. Upgrade to keep operating without waiting for the reset." : "This capability is not included in the organization’s current commercial state.");
  const href = `/pricing?upgrade=${target}${detail?.feature ? `&feature=${encodeURIComponent(detail.feature)}` : ""}${detail?.metric ? `&metric=${encodeURIComponent(detail.metric)}` : ""}`;

  return <>
    {children}
    {detail ? <div className="fixed inset-0 z-[120] flex items-center justify-center bg-[#061D15]/80 px-4 py-8 backdrop-blur-[2px]" role="dialog" aria-modal="true" aria-label={title}>
      <div className="relative w-full max-w-[880px] overflow-hidden rounded-[26px] border border-white/10 bg-[#FFFDF8] shadow-[0_32px_120px_rgba(0,0,0,0.42)]">
        <button type="button" onClick={() => setDetail(null)} aria-label="Close upgrade message" className="absolute right-4 top-4 z-10 flex h-9 w-9 items-center justify-center rounded-full border border-[#D6DDD0] bg-white text-[#65736A]"><X className="h-4 w-4" /></button>
        <div className="grid md:grid-cols-[0.92fr_1.08fr]">
          <section className="flex flex-col justify-between bg-[#0D2B1E] p-7 text-white md:p-9">
            <div>
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#DDEB8F] text-[#10231B]"><Lock className="h-5 w-5" /></div>
              <div className="mt-6 text-[11px] font-semibold uppercase tracking-[0.2em] text-white/50">AGRO-AI access</div>
              <h2 className="mt-3 text-[30px] font-semibold leading-tight tracking-tight">{title}</h2>
              <p className="mt-4 text-[14px] leading-7 text-white/70">{body}</p>
            </div>
            {isQuota ? <div className="mt-8 rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="flex items-center justify-between text-[12px]"><span className="capitalize text-white/60">{(detail.metric || "plan usage").replaceAll("_", " ")}</span><span className="font-semibold">{Number(detail.used || 0) + Number(detail.reserved || 0)} / {detail.limit ?? "—"}</span></div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-[#DDEB8F]" style={{ width: `${usagePercent(detail)}%` }} /></div>
              <div className="mt-2 text-[11px] text-white/45">Usage is enforced on the backend and resets with the commercial period.</div>
            </div> : null}
          </section>
          <section className="p-6 md:p-8">
            <div className="grid gap-4 sm:grid-cols-2"><PlanCard id={currentPlan} label="Current plan" /><PlanCard id={target} label="Recommended" highlighted /></div>
            <div className="mt-6 rounded-2xl border border-[#D6DDD0] bg-[#F6F4EE] p-4">
              <div className="text-[12px] font-semibold text-[#10231B]">Why you’re seeing this</div>
              <p className="mt-2 text-[12px] leading-6 text-[#65736A]">{detail.feature ? `Capability: ${detail.feature}. ` : ""}{detail.metric ? `Limit: ${detail.metric}. ` : ""}AGRO-AI enforces commercial capabilities and quotas on the server, not only in the interface.</p>
            </div>
            <div className="mt-6 flex flex-wrap gap-3"><a href={href} className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#0D2B1E] px-5 text-[13px] font-semibold text-white">{target === "enterprise" ? "Talk to sales" : `Upgrade to ${PLAN[target].name}`}<ArrowRight className="h-4 w-4" /></a><button type="button" onClick={() => setDetail(null)} className="h-11 rounded-xl border border-[#D6DDD0] bg-white px-5 text-[13px] font-semibold text-[#10231B]">Not now</button></div>
          </section>
        </div>
      </div>
    </div> : null}
  </>;
}

function PlanCard({ id, label, highlighted = false }: { id: PlanId; label: string; highlighted?: boolean }) {
  const plan = PLAN[id];
  return <article className="rounded-2xl p-4" style={{ background: highlighted ? "#EEF8E8" : "#F6F4EE", border: `1px solid ${highlighted ? "#A7CFAF" : "#D6DDD0"}` }}>
    <div className="text-[10px] font-semibold uppercase tracking-[0.16em]" style={{ color: highlighted ? "#1F7350" : "#7A877F" }}>{label}</div>
    <div className="mt-2 flex items-baseline justify-between gap-3"><h3 className="text-[18px] font-semibold text-[#10231B]">{plan.name}</h3><span className="text-[12px] font-semibold text-[#2D6A4F]">{plan.price}</span></div>
    <div className="mt-4 space-y-2">{plan.bullets.map((bullet) => <div key={bullet} className="flex gap-2 text-[11px] leading-5 text-[#65736A]"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#2D6A4F]" /><span>{bullet}</span></div>)}</div>
  </article>;
}
