import { ReactNode, useEffect, useMemo, useState } from "react";
import { ArrowRight, Check, Lock, X } from "lucide-react";
import { useAuth } from "../auth/AuthProvider";

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

type PlanView = {
  id: PlanId;
  name: string;
  price: string;
  bullets: string[];
};

const PLAN_ORDER: PlanId[] = ["free", "professional", "team", "network", "enterprise"];
const PLANS: Record<PlanId, PlanView> = {
  free: { id: "free", name: "Free", price: "$0", bullets: ["1 workspace", "25 AGRO-AI actions/month", "10 evidence uploads/month"] },
  professional: { id: "professional", name: "Professional", price: "$299/mo", bullets: ["5 workspaces and 3 seats", "500 AGRO-AI actions/month", "Reports, PDFs and live connectors"] },
  team: { id: "team", name: "Team", price: "$799/mo", bullets: ["25 workspaces and 10 seats", "2,500 AGRO-AI actions/month", "Shared evidence, roles and approvals"] },
  network: { id: "network", name: "Network", price: "$1,500/mo", bullets: ["50 workspaces and 25 seats", "10,000 AGRO-AI actions/month", "Cross-workspace rollups and network reporting"] },
  enterprise: { id: "enterprise", name: "Enterprise", price: "Custom", bullets: ["Contract-configured capacity", "Custom integrations and governance", "Dedicated rollout and security review"] },
};

const FEATURE_COPY: Record<string, { title: string; body: string }> = {
  "reports.generate": { title: "Unlock commercial reports", body: "Generate evidence-backed operating reports from the active workspace." },
  "reports.pdf_export": { title: "Unlock PDF exports", body: "Export document-ready reports and share them outside the portal." },
  "reports.email_delivery": { title: "Unlock report delivery", body: "Send approved reports through connected delivery workflows." },
  "connectors.live": { title: "Connect live operating systems", body: "Bring controller, weather and operational data into one evidence workspace." },
  "connectors.oauth_documents": { title: "Connect approved document sources", body: "Authorize Gmail, Drive, Dropbox, Box, Slack and other document context." },
  "connectors.custom_integration": { title: "Scope an enterprise integration", body: "Connect contract-specific provider, ERP, geospatial or custom API systems." },
  "team.invite": { title: "Add your operating team", body: "Invite teammates and coordinate work with role-aware access." },
  "admin.requests": { title: "Unlock the request inbox", body: "Track support, onboarding, integration and upgrade requests in one place." },
  "agents.execute_safe": { title: "Unlock agent execution", body: "Run commercially authorized agent work with quota accounting and safety controls." },
  "agents.execute_approval_gated": { title: "Unlock approval-gated agents", body: "Coordinate higher-risk actions behind explicit approval boundaries." },
  "intelligence.deep_analysis": { title: "Unlock deeper analysis", body: "Use larger context, more evidence sources and a higher reasoning budget." },
};

function canonicalPlan(value: unknown): PlanId {
  const normalized = String(value || "free").toLowerCase();
  const aliases: Record<string, PlanId> = { pilot: "free", pro: "professional", waterops: "professional", assurance_audit: "professional", assurance: "team" };
  const candidate = aliases[normalized] || normalized;
  return PLAN_ORDER.includes(candidate as PlanId) ? candidate as PlanId : "free";
}

function nextPlan(plan: PlanId): PlanId {
  const index = PLAN_ORDER.indexOf(plan);
  return PLAN_ORDER[Math.min(index + 1, PLAN_ORDER.length - 1)];
}

function targetPlan(detail: CommercialBoundaryDetail, current: PlanId): PlanId {
  const requested = canonicalPlan(detail.recommended_plan);
  if (detail.recommended_plan && PLAN_ORDER.indexOf(requested) > PLAN_ORDER.indexOf(current)) return requested;
  if (detail.code === "quota_exceeded" || detail.status === 429) return nextPlan(current);
  if (PLAN_ORDER.indexOf(requested) > PLAN_ORDER.indexOf(current)) return requested;
  return current === "enterprise" ? "enterprise" : nextPlan(current);
}

function boundaryCopy(detail: CommercialBoundaryDetail) {
  if (detail.code === "quota_exceeded" || detail.status === 429) {
    return {
      title: "You’ve reached this plan limit",
      body: detail.message || "Your current commercial quota is exhausted for this billing period. Upgrade to keep operating without waiting for the reset.",
    };
  }
  const feature = detail.feature ? FEATURE_COPY[detail.feature] : undefined;
  return feature || {
    title: detail.code === "subscription_inactive" ? "Restore commercial access" : "Upgrade to continue",
    body: detail.message || "This capability is not included in the organization’s current commercial state.",
  };
}

function usagePercent(detail: CommercialBoundaryDetail) {
  const used = Number(detail.used || 0) + Number(detail.reserved || 0);
  const limit = Number(detail.limit || 0);
  if (!limit) return 100;
  return Math.min(100, Math.max(0, Math.round((used / limit) * 100)));
}

export function openCommercialBoundary(detail: CommercialBoundaryDetail) {
  window.dispatchEvent(new CustomEvent(COMMERCIAL_BOUNDARY_EVENT, { detail }));
}

export function CommercialBoundary({ children }: { children: ReactNode }) {
  const { currentOrganization } = useAuth();
  const [detail, setDetail] = useState<CommercialBoundaryDetail | null>(null);

  useEffect(() => {
    const handler = (event: Event) => setDetail((event as CustomEvent<CommercialBoundaryDetail>).detail || {});
    window.addEventListener(COMMERCIAL_BOUNDARY_EVENT, handler);
    return () => window.removeEventListener(COMMERCIAL_BOUNDARY_EVENT, handler);
  }, []);

  const currentPlan = canonicalPlan(currentOrganization?.plan);
  const recommendedPlan = useMemo(() => detail ? targetPlan(detail, currentPlan) : nextPlan(currentPlan), [detail, currentPlan]);
  const copy = detail ? boundaryCopy(detail) : null;
  const isQuota = detail?.code === "quota_exceeded" || detail?.status === 429;
  const upgradeHref = `/pricing?upgrade=${recommendedPlan}${detail?.feature ? `&feature=${encodeURIComponent(detail.feature)}` : ""}${detail?.metric ? `&metric=${encodeURIComponent(detail.metric)}` : ""}`;

  return (
    <>
      {children}
      {detail && copy ? (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-[#061D15]/80 px-4 py-8 backdrop-blur-[2px]" role="dialog" aria-modal="true" aria-label={copy.title}>
          <div className="relative w-full max-w-[860px] overflow-hidden rounded-[26px] border border-white/10 bg-[#FFFDF8] shadow-[0_32px_120px_rgba(0,0,0,0.42)]">
            <button type="button" onClick={() => setDetail(null)} aria-label="Close upgrade message" className="absolute right-4 top-4 z-10 flex h-9 w-9 items-center justify-center rounded-full border border-[#D6DDD0] bg-white text-[#65736A] hover:bg-[#F6F4EE]">
              <X className="h-4 w-4" />
            </button>

            <div className="grid md:grid-cols-[0.9fr_1.1fr]">
              <section className="flex flex-col justify-between bg-[#0D2B1E] p-7 text-white md:p-9">
                <div>
                  <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#DDEB8F] text-[#10231B]">
                    <Lock className="h-5 w-5" />
                  </div>
                  <div className="mt-6 text-[11px] font-semibold uppercase tracking-[0.2em] text-white/50">AGRO-AI access</div>
                  <h2 className="mt-3 text-[29px] font-semibold leading-tight tracking-tight">{copy.title}</h2>
                  <p className="mt-4 text-[14px] leading-7 text-white/68">{copy.body}</p>
                </div>

                {isQuota ? (
                  <div className="mt-8 rounded-2xl border border-white/10 bg-white/5 p-4">
                    <div className="flex items-center justify-between text-[12px]">
                      <span className="text-white/60">{detail.metric ? detail.metric.replaceAll("_", " ") : "Plan usage"}</span>
                      <span className="font-semibold text-white">{Number(detail.used || 0) + Number(detail.reserved || 0)} / {detail.limit ?? "—"}</span>
                    </div>
                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
                      <div className="h-full rounded-full bg-[#DDEB8F]" style={{ width: `${usagePercent(detail)}%` }} />
                    </div>
                    <div className="mt-2 text-[11px] text-white/46">Usage is enforced server-side and resets with the commercial billing period.</div>
                  </div>
                ) : null}
              </section>

              <section className="p-6 md:p-8">
                <div className="grid gap-4 sm:grid-cols-2">
                  <PlanCard plan={PLANS[currentPlan]} label="Current plan" muted />
                  <PlanCard plan={PLANS[recommendedPlan]} label="Recommended" highlighted />
                </div>

                <div className="mt-6 rounded-2xl border border-[#D6DDD0] bg-[#F6F4EE] p-4">
                  <div className="text-[12px] font-semibold text-[#10231B]">Why you’re seeing this</div>
                  <div className="mt-2 text-[12px] leading-6 text-[#65736A]">
                    {detail.feature ? `Capability: ${detail.feature}. ` : ""}
                    {detail.metric ? `Limit: ${detail.metric}. ` : ""}
                    {detail.code === "subscription_inactive" ? "The selected paid plan is not currently in an active commercial state." : "AGRO-AI enforces plan capabilities and quotas on the backend, not only in the interface."}
                  </div>
                </div>

                <div className="mt-6 flex flex-wrap items-center gap-3">
                  <a href={upgradeHref} className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#0D2B1E] px-5 text-[13px] font-semibold text-white hover:bg-[#16533C]">
                    {recommendedPlan === "enterprise" ? "Talk to sales" : `Upgrade to ${PLANS[recommendedPlan].name}`}
                    <ArrowRight className="h-4 w-4" />
                  </a>
                  <button type="button" onClick={() => setDetail(null)} className="h-11 rounded-xl border border-[#D6DDD0] bg-white px-5 text-[13px] font-semibold text-[#10231B] hover:bg-[#F6F4EE]">
                    Not now
                  </button>
                </div>
              </section>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

function PlanCard({ plan, label, muted = false, highlighted = false }: { plan: PlanView; label: string; muted?: boolean; highlighted?: boolean }) {
  return (
    <article className="rounded-2xl p-4" style={{ background: highlighted ? "#EEF8E8" : muted ? "#F6F4EE" : "white", border: `1px solid ${highlighted ? "#A7CFAF" : "#D6DDD0"}` }}>
      <div className="text-[10px] font-semibold uppercase tracking-[0.16em]" style={{ color: highlighted ? "#1F7350" : "#7A877F" }}>{label}</div>
      <div className="mt-2 flex items-baseline justify-between gap-3">
        <h3 className="text-[18px] font-semibold text-[#10231B]">{plan.name}</h3>
        <span className="text-[12px] font-semibold text-[#2D6A4F]">{plan.price}</span>
      </div>
      <div className="mt-4 space-y-2">
        {plan.bullets.map((bullet) => <div key={bullet} className="flex gap-2 text-[11px] leading-5 text-[#65736A]"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#2D6A4F]" /><span>{bullet}</span></div>)}
      </div>
    </article>
  );
}
