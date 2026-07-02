import { useEffect, useMemo, useState } from "react";
import { Check, ShieldCheck } from "lucide-react";
import { apiClient, ProductCheckoutPayload } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { currentLocale, t } from "../i18n";
import { LanguageSelector } from "./LanguageSelector";
import { BG, BORDER, GREEN, MUTED, SURFACE, TEXT } from "./portalUi";

type BillingPeriod = "monthly" | "annual";
type PlanId = "free" | "professional" | "team" | "network" | "enterprise";

type Plan = {
  id: PlanId;
  name: string;
  public_price_monthly: string;
  public_price_annual: string;
  recommended_buyer: string;
  included_limits?: Record<string, string>;
  features: string[];
  annual_savings_badge?: string | null;
  is_custom_pricing?: boolean;
};

const FALLBACK_PLANS: Plan[] = [
  {
    id: "free",
    name: "Free",
    public_price_monthly: "$0/month",
    public_price_annual: "$0/year",
    recommended_buyer: "For pilots and small teams testing AGRO-AI.",
    included_limits: { users: "1 user", workspaces: "1 workspace", uploads: "10 evidence uploads/month" },
    features: ["Basic field updates", "Basic readiness view", "Basic support request"],
  },
  {
    id: "professional",
    name: "Professional",
    public_price_monthly: "$299/month",
    public_price_annual: "$2,990/year",
    recommended_buyer: "For commercial farms, advisors, and operators running field operations.",
    included_limits: { users: "3 seats included", workspaces: "5 workspaces", uploads: "500 evidence uploads/month" },
    features: ["Water risk briefs", "Operator checklists", "Report and PDF generation", "Compliance packet drafts", "Standard support"],
    annual_savings_badge: "Save 17% annually",
  },
  {
    id: "team",
    name: "Team",
    public_price_monthly: "$799/month",
    public_price_annual: "$7,990/year",
    recommended_buyer: "For advisory teams, farm management teams, and multi-site operators.",
    included_limits: { users: "10 seats included", workspaces: "25 workspaces", uploads: "2,500 evidence uploads/month" },
    features: ["Team member invites", "Role controls", "Shared evidence library", "Admin request inbox", "Connector workflows"],
    annual_savings_badge: "Most popular",
  },
  {
    id: "network",
    name: "Network",
    public_price_monthly: "$1,500/month",
    public_price_annual: "$15,000/year",
    recommended_buyer: "For grower networks, water districts, exporters, lenders, insurers, and multi-farm programs.",
    included_limits: { users: "25 seats included", workspaces: "50 workspaces or sites", acres: "50,000 managed acres included" },
    features: ["Network dashboard", "Multi-workspace reporting", "Compliance and evidence rollups", "Partner reporting", "Priority onboarding"],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    public_price_monthly: "Contact sales",
    public_price_annual: "Contact sales",
    recommended_buyer: "For agencies, lenders, insurers, food companies, and national-scale networks.",
    included_limits: { users: "Custom seats", workspaces: "Custom workspaces", uploads: "Custom upload volume" },
    features: ["SSO/SAML planning", "Audit logs", "Custom integrations", "Dedicated onboarding", "Security review"],
    is_custom_pricing: true,
  },
];

const COMPARISON = [
  ["Users", "1", "3", "10", "25", "Custom"],
  ["Workspaces", "1", "5", "25", "50", "Custom"],
  ["PDF reports", "Sample", "Yes", "Advanced", "Rollups", "Custom"],
  ["Evidence uploads", "Limited", "500/mo", "2,500/mo", "10,000/mo", "Custom"],
  ["Controller gateway", "—", "Readiness", "Ops-ready", "Advanced", "Custom"],
  ["Support", "Basic", "Standard", "Priority", "Priority rollout", "Dedicated"],
];

function planPrice(plan: Plan, period: BillingPeriod) {
  return period === "annual" ? plan.public_price_annual : plan.public_price_monthly;
}

function mergePlans(remote: Plan[] | undefined) {
  if (!remote?.length) return FALLBACK_PLANS;
  const byId = new Map<PlanId, Plan>();
  for (const plan of FALLBACK_PLANS) byId.set(plan.id, plan);
  for (const plan of remote) byId.set(plan.id, { ...byId.get(plan.id), ...plan });
  return FALLBACK_PLANS.map((plan) => byId.get(plan.id) || plan);
}

export function PricingPage() {
  const { isAuthenticated } = useAuth();
  const [billingPeriod, setBillingPeriod] = useState<BillingPeriod>("monthly");
  const [remotePlans, setRemotePlans] = useState<Plan[] | undefined>();
  const [busyPlan, setBusyPlan] = useState("");
  const [message, setMessage] = useState("");
  const [locale, setLocale] = useState(currentLocale());

  useEffect(() => {
    let mounted = true;
    apiClient.product.plans()
      .then((response: any) => { if (mounted && Array.isArray(response?.plans)) setRemotePlans(response.plans); })
      .catch(() => null);
    const listener = (() => setLocale(currentLocale())) as EventListener;
    window.addEventListener("agroai:locale-change", listener);
    return () => {
      mounted = false;
      window.removeEventListener("agroai:locale-change", listener);
    };
  }, []);

  const plans = useMemo(() => mergePlans(remotePlans), [remotePlans]);

  async function choosePlan(plan: Plan) {
    setMessage("");
    setBusyPlan(plan.id);
    try {
      if (plan.id === "free") {
        if (!isAuthenticated) {
          localStorage.setItem("agroai_selected_plan", "free");
          window.location.href = "/?mode=register";
          return;
        }
        setMessage("Free workspace is already available on your account.");
        return;
      }

      if (plan.id === "enterprise") {
        await apiClient.sales.contact({
          category: "sales",
          type: "upgrade",
          subject: "Enterprise pricing request",
          message: "Customer requested Enterprise pricing from the pricing page.",
          source_page: "pricing",
        });
        setMessage("Enterprise request received. Sales follow-up was created.");
        return;
      }

      if (!isAuthenticated) {
        localStorage.setItem("agroai_selected_plan", plan.id);
        localStorage.setItem("agroai_selected_billing_period", billingPeriod);
        setMessage(`Create an account first, then Stripe checkout will open for ${plan.name}.`);
        window.location.href = "/?mode=register";
        return;
      }

      const response = await apiClient.billing.checkout({ plan_id: plan.id, billing_period: billingPeriod } as ProductCheckoutPayload) as Record<string, unknown>;
      if (typeof response.checkout_url === "string" && response.checkout_url) {
        window.location.assign(response.checkout_url);
        return;
      }
      setMessage(String(response.message || "Upgrade request received. Stripe checkout was not returned by the backend."));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not start checkout. Please try again.");
    } finally {
      setBusyPlan("");
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <main className="mx-auto max-w-[1180px] px-5 py-10 md:px-8">
        <section className="rounded-[28px] px-6 py-9 md:px-10 md:py-12" style={{ background: "#0D2B1E", color: "white" }}>
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div>
              <div className="text-[12px] font-semibold uppercase tracking-[0.22em]" style={{ color: "rgba(255,255,255,0.64)" }}>AGRO-AI Pricing</div>
              <h1 className="mt-5 max-w-3xl text-[40px] font-semibold leading-[1.04] tracking-tight md:text-[54px]">{t("pricingTitle", locale)}</h1>
              <p className="mt-5 max-w-2xl text-[15px] leading-7" style={{ color: "rgba(255,255,255,0.72)" }}>{t("pricingSubtitle", locale)}</p>
            </div>
            <LanguageSelector dark />
          </div>
          <div className="mt-8 flex flex-wrap items-center justify-between gap-4">
            <div className="inline-flex rounded-full bg-white/10 p-1">
              {(["monthly", "annual"] as const).map((period) => (
                <button key={period} type="button" onClick={() => setBillingPeriod(period)} className="rounded-full px-4 py-2 text-[13px] font-medium capitalize" style={{ background: billingPeriod === period ? "white" : "transparent", color: billingPeriod === period ? "#0D2B1E" : "white" }}>
                  {period}
                </button>
              ))}
            </div>
            <div className="text-[12px]" style={{ color: "rgba(255,255,255,0.62)" }}>Annual plans include rollout savings.</div>
          </div>
        </section>

        {message ? (
          <div className="mt-6 rounded-xl px-4 py-3 text-[13px]" style={{ background: "#FFFBEB", color: "#92400E", border: "1px solid #FCD34D" }}>{message}</div>
        ) : null}

        <section className="mt-7 grid gap-4 lg:grid-cols-5">
          {plans.map((plan) => {
            const highlighted = plan.id === "team";
            const limits = Object.values(plan.included_limits || {}).slice(0, 3);
            const paidSelfServe = ["professional", "team", "network"].includes(plan.id);
            const label = plan.id === "free" ? "Start free" : plan.id === "enterprise" ? "Talk to sales" : paidSelfServe ? `Pay ${billingPeriod}` : plan.name;
            return (
              <article key={plan.id} className="flex min-h-[430px] flex-col rounded-[22px] p-5" style={{ background: highlighted ? "#0D2B1E" : SURFACE, border: `1px solid ${highlighted ? "#0D2B1E" : BORDER}`, boxShadow: highlighted ? "0 20px 70px rgba(13,43,30,0.18)" : "0 12px 38px rgba(16,35,27,0.06)" }}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-[21px] font-semibold" style={{ color: highlighted ? "white" : TEXT }}>{plan.name}</h2>
                    <p className="mt-2 min-h-[76px] text-[12px] leading-5" style={{ color: highlighted ? "rgba(255,255,255,0.68)" : MUTED }}>{plan.recommended_buyer}</p>
                  </div>
                  {plan.annual_savings_badge ? <span className="rounded-md px-2 py-1 text-[10px] font-semibold" style={{ background: "#DCFCE7", color: "#15803D" }}>{plan.annual_savings_badge}</span> : null}
                </div>
                <div className="mt-4 text-[30px] font-semibold" style={{ color: highlighted ? "white" : TEXT }}>{planPrice(plan, billingPeriod)}</div>
                <div className="mt-4 space-y-2 text-[12px]" style={{ color: highlighted ? "rgba(255,255,255,0.82)" : TEXT }}>
                  {limits.map((limit) => <div key={limit} className="flex gap-2"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0" /> <span>{limit}</span></div>)}
                </div>
                <div className="mt-5 space-y-2">
                  {plan.features.slice(0, 5).map((feature) => <div key={feature} className="flex gap-2 text-[12px] leading-5" style={{ color: highlighted ? "rgba(255,255,255,0.82)" : TEXT }}><Check className="mt-0.5 h-3.5 w-3.5 shrink-0" /> <span>{feature}</span></div>)}
                </div>
                <div className="mt-auto pt-6">
                  <button type="button" disabled={busyPlan === plan.id} onClick={() => choosePlan(plan)} className="h-11 w-full rounded-xl text-[13px] font-semibold disabled:opacity-60" style={{ background: highlighted ? "white" : "#0D2B1E", color: highlighted ? "#0D2B1E" : "white" }}>
                    {busyPlan === plan.id ? "Opening Stripe..." : label}
                  </button>
                </div>
              </article>
            );
          })}
        </section>

        <section className="mt-10 rounded-[24px] p-5 md:p-7" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="mb-5 flex items-center gap-2">
            <ShieldCheck className="h-5 w-5" style={{ color: GREEN }} />
            <h2 className="text-[24px] font-semibold" style={{ color: TEXT }}>Compare plans</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-[13px]">
              <thead>
                <tr style={{ color: MUTED }}>
                  <th className="py-3 text-left font-medium">Capability</th>
                  {plans.map((plan) => <th key={plan.id} className="py-3 text-center font-medium">{plan.name}</th>)}
                </tr>
              </thead>
              <tbody>
                {COMPARISON.map((row) => (
                  <tr key={row[0]} style={{ borderTop: `1px solid ${BORDER}` }}>
                    {row.map((cell, index) => <td key={`${row[0]}-${index}`} className={`px-3 py-4 ${index ? "text-center" : "font-medium"}`} style={{ color: TEXT }}>{cell}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}
