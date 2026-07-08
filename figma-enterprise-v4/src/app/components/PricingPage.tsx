import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { Check, ShieldCheck } from "lucide-react";
import { apiClient, ProductCheckoutPayload } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { useLocale } from "../hooks/useLocale";
import { usePortalCopy } from "../hooks/usePortalCopy";
import { BG, BORDER, GREEN, MUTED, SURFACE, TEXT } from "./portalUi";

type BillingPeriod = "monthly" | "annual";
type PlanId = "free" | "professional" | "team" | "network" | "enterprise";
type Plan = { id: PlanId; name: string; public_price_monthly: string; public_price_annual: string; recommended_buyer: string; included_limits?: Record<string, string>; features: string[]; annual_savings_badge?: string | null; is_custom_pricing?: boolean };
type Copy = (value: string) => string;

const DEMO_BOOKING_URL = "https://agroai-pilot.com/book-a-demo";

const FALLBACK_PLANS: Plan[] = [
  { id: "free", name: "Free", public_price_monthly: "$0/month", public_price_annual: "$0/year", recommended_buyer: "For pilots and small teams testing AGRO-AI.", included_limits: { users: "1 user", workspaces: "1 workspace", uploads: "15 evidence/file imports per month" }, features: ["Basic field updates", "Basic readiness view"] },
  { id: "professional", name: "Professional", public_price_monthly: "$299/month", public_price_annual: "$2,990/year", recommended_buyer: "For commercial farms, advisors, and operators running field operations.", included_limits: { users: "3 seats included", workspaces: "5 workspaces", uploads: "500 evidence/file imports per month" }, features: ["500 AGRO-AI actions/month", "25 Deep analyses/month", "Report and PDF generation", "Weather and OpenET context", "Standard live connectors"] },
  { id: "team", name: "Team", public_price_monthly: "$799/month", public_price_annual: "$7,990/year", recommended_buyer: "For advisory teams, farm management teams, and multi-site operators.", included_limits: { users: "10 seats included", workspaces: "25 workspaces", uploads: "2,500 evidence/file imports per month" }, features: ["2,500 AGRO-AI actions/month", "150 Deep analyses/month", "Team member invites", "Role controls", "Shared evidence and approvals"] },
  { id: "network", name: "Network", public_price_monthly: "$1,500/month", public_price_annual: "$15,000/year", recommended_buyer: "For grower networks, water districts, exporters, lenders, insurers, and multi-farm programs.", included_limits: { users: "25 seats included", workspaces: "50 workspaces or sites", uploads: "10,000 evidence/file imports per month" }, features: ["10,000 AGRO-AI actions/month", "750 Deep analyses/month", "Network dashboards and rollups", "Standard Custom API access", "Priority onboarding"] },
  { id: "enterprise", name: "Enterprise", public_price_monthly: "Contact sales", public_price_annual: "Contact sales", recommended_buyer: "For agencies, lenders, insurers, food companies, and national-scale networks.", included_limits: { users: "Custom seats", workspaces: "Custom workspaces", uploads: "Contract-configured import volume" }, features: ["Contract-configured AI capacity", "SSO/SAML planning", "Audit logs", "Bespoke custom integrations", "Dedicated onboarding"], is_custom_pricing: true },
];

const COMPARISON = [
  ["Users", "1", "3", "10", "25", "Custom"],
  ["Workspaces", "1", "5", "25", "50", "Custom"],
  ["Ask AGRO-AI", "Locked", "Included", "Included", "Included", "Included"],
  ["AGRO-AI actions", "Locked", "500/mo", "2,500/mo", "10,000/mo", "Contract"],
  ["Deep analysis", "Locked", "25/mo", "150/mo", "750/mo", "Contract"],
  ["Evidence file imports", "15/mo shared", "500/mo shared", "2,500/mo shared", "10,000/mo shared", "Contract volume"],
  ["PDF reports", "Locked", "Yes", "Advanced", "Rollups", "Custom"],
  ["Weather / Forecast", "Locked", "Included", "Included", "Included", "Included"],
  ["OpenET / ET context", "Locked", "Included", "Included", "Included", "Included"],
  ["Standard Custom API", "Locked", "Locked", "Locked", "Included", "Contract scoped"],
  ["Bespoke integrations", "Locked", "Locked", "Locked", "Locked", "Contract"],
  ["Team invites", "Locked", "Locked", "Yes", "Yes", "Custom"],
  ["Admin requests", "Locked", "Locked", "Yes", "Yes", "Custom"],
  ["Network rollups", "Locked", "Locked", "Locked", "Yes", "Custom"],
  ["Support", "Basic", "Standard", "Priority", "Priority rollout", "Dedicated"],
];

const REQUIRED_PLAN_COPY: Record<string, string> = {
  professional: "Professional unlocks reports, Weather, OpenET, live connectors, 500 AGRO-AI actions, and 25 Deep analyses each month.",
  team: "Team unlocks direct invitations, role controls, shared evidence, approvals, 2,500 AGRO-AI actions, and 150 Deep analyses each month.",
  network: "Network unlocks standard Custom API access, multi-workspace rollups, 10,000 AGRO-AI actions, and 750 Deep analyses each month.",
  enterprise: "Enterprise adds bespoke integrations, custom security, SSO, governance review, and contract-configured AI capacity.",
};

function planPrice(plan: Plan, period: BillingPeriod) { return period === "annual" ? plan.public_price_annual : plan.public_price_monthly; }
function mergePlans(remote: Plan[] | undefined) { if (!remote?.length) return FALLBACK_PLANS; const byId = new Map<PlanId, Plan>(); for (const plan of FALLBACK_PLANS) byId.set(plan.id, plan); for (const plan of remote) byId.set(plan.id, { ...byId.get(plan.id), ...plan, features: byId.get(plan.id)?.features || plan.features } as Plan); return FALLBACK_PLANS.map((plan) => byId.get(plan.id) || plan); }
function isPlanId(value: string | null): value is PlanId { return ["free", "professional", "team", "network", "enterprise"].includes(String(value)); }
function fallbackPlanName(id: string | undefined): string { return id === "professional" ? "Professional" : id === "team" ? "Team" : id === "network" ? "Network" : id === "enterprise" ? "Enterprise" : "Free"; }

function PriceDisplay({ value, highlighted, tx }: { value: string; highlighted: boolean; tx: Copy }) {
  const match = value.match(/^(\$[\d,]+)(\/(?:month|year))$/);
  if (!match) return <div className="mt-4 break-words text-[28px] font-semibold leading-tight" style={{ color: highlighted ? "white" : TEXT }}>{tx(value)}</div>;
  const unit = match[2].slice(1);
  return <div className="mt-4 flex min-w-0 flex-wrap items-baseline gap-x-1" style={{ color: highlighted ? "white" : TEXT }}><span className="min-w-0 text-[30px] font-semibold tracking-tight">{match[1]}</span><span className="whitespace-nowrap text-[11px] font-semibold opacity-70">/{tx(unit)}</span></div>;
}

function CardBadge({ plan, requestedUpgrade, billingPeriod, highlighted, tx }: { plan: Plan; requestedUpgrade?: PlanId; billingPeriod: BillingPeriod; highlighted: boolean; tx: Copy }) {
  const annualSaver = ["professional", "team", "network"].includes(plan.id);
  const labels: string[] = [];
  if (annualSaver) labels.push(billingPeriod === "annual" ? "Save 17% annually" : "Annual saves 17%");
  if (plan.id === "team" && !requestedUpgrade) labels.push("Most popular");
  if (plan.id === requestedUpgrade) labels.push("Recommended for this feature");
  if (!labels.length) return null;
  return <div className="mt-3 flex min-h-[26px] flex-wrap gap-2">{labels.map((label) => <span key={label} className="inline-flex max-w-full rounded-full px-2.5 py-1 text-[10px] font-semibold leading-4" style={{ background: highlighted ? "rgba(221,235,143,0.18)" : "#F0F7EE", color: highlighted ? "#E8F4B5" : "#1F5A43", border: highlighted ? "1px solid rgba(221,235,143,0.30)" : "1px solid #CFE1CB" }}>{tx(label)}</span>)}</div>;
}

export function PricingPage() {
  const { isAuthenticated, currentOrganization } = useAuth();
  const { t } = useLocale();
  const { tx, tf } = usePortalCopy(["pricing", "shared"]);
  const [params] = useSearchParams();
  const requestedUpgrade = isPlanId(params.get("upgrade")) ? params.get("upgrade") as PlanId : undefined;
  const [billingPeriod, setBillingPeriod] = useState<BillingPeriod>((localStorage.getItem("agroai_selected_billing_period") as BillingPeriod) || "monthly");
  const [remotePlans, setRemotePlans] = useState<Plan[] | undefined>();
  const [busyPlan, setBusyPlan] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => { let mounted = true; apiClient.product.plans().then((response: any) => { if (mounted && Array.isArray(response?.plans)) setRemotePlans(response.plans); }).catch(() => null); return () => { mounted = false; }; }, []);
  const plans = useMemo(() => mergePlans(remotePlans), [remotePlans]);

  async function choosePlan(plan: Plan) {
    setMessage(""); setBusyPlan(plan.id);
    try {
      if (plan.id === "free") { if (!isAuthenticated) { localStorage.setItem("agroai_selected_plan", "free"); window.location.href = "/?mode=register"; return; } setMessage(tx("Free workspace is already available on your account.")); return; }
      if (plan.id === "enterprise") { window.location.assign(DEMO_BOOKING_URL); return; }
      if (!isAuthenticated) { localStorage.setItem("agroai_selected_plan", plan.id); localStorage.setItem("agroai_selected_billing_period", billingPeriod); setMessage(tf("Create an account first, then Stripe checkout will open for {plan}.", { plan: tx(plan.name) })); window.location.href = "/?mode=register"; return; }
      const response = await apiClient.billing.checkout({ plan_id: plan.id, billing_period: billingPeriod } as ProductCheckoutPayload) as Record<string, unknown>;
      if (typeof response.checkout_url === "string" && response.checkout_url) { window.location.assign(response.checkout_url); return; }
      setMessage(String(response.message || tx("Upgrade request received. Stripe checkout was not returned by the backend.")));
    } catch (error) { setMessage(error instanceof Error ? error.message : tx("Could not start checkout. Please try again.")); }
    finally { setBusyPlan(""); }
  }

  return <div className="min-h-screen" style={{ background: BG }}>
    <main className="mx-auto max-w-[1180px] px-5 py-10 md:px-8">
      <section className="rounded-[28px] px-6 py-9 md:px-10 md:py-12" style={{ background: "#0D2B1E", color: "white" }}>
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div><div className="text-[12px] font-semibold uppercase tracking-[0.22em]" style={{ color: "rgba(255,255,255,0.64)" }}>{tx("AGRO-AI Pricing")}</div><h1 className="mt-5 max-w-3xl text-[40px] font-semibold leading-[1.04] tracking-tight md:text-[54px]">{t("pricingTitle")}</h1><p className="mt-5 max-w-2xl text-[15px] leading-7" style={{ color: "rgba(255,255,255,0.72)" }}>{t("pricingSubtitle")}</p></div>
          <div className="rounded-2xl p-4 text-[12px] leading-5" style={{ background: "rgba(255,255,255,0.10)", color: "rgba(255,255,255,0.78)", border: "1px solid rgba(255,255,255,0.14)" }}><div className="font-semibold text-white">{tx("Current plan")}</div><div className="mt-1 capitalize">{tx(fallbackPlanName(currentOrganization?.plan))}</div></div>
        </div>
        <div className="mt-8 flex flex-wrap items-center justify-between gap-4"><div className="inline-flex rounded-full bg-white/10 p-1">{(["monthly", "annual"] as const).map((period) => <button key={period} type="button" onClick={() => { setBillingPeriod(period); localStorage.setItem("agroai_selected_billing_period", period); }} className="rounded-full px-4 py-2 text-[13px] font-medium capitalize" style={{ background: billingPeriod === period ? "white" : "transparent", color: billingPeriod === period ? "#0D2B1E" : "white" }}>{tx(period)}</button>)}</div><div className="text-[12px]" style={{ color: "rgba(255,255,255,0.62)" }}>{tx("Professional, Team, and Network save 17% on annual billing.")}</div></div>
      </section>

      {requestedUpgrade ? <div className="mt-6 rounded-xl px-4 py-3 text-[13px]" style={{ background: "#F0F7EE", color: "#1F5A43", border: "1px solid #CFE1CB" }}><strong>{tx("Recommended upgrade:")}</strong> {tx(REQUIRED_PLAN_COPY[requestedUpgrade] || REQUIRED_PLAN_COPY.professional)}</div> : null}
      {message ? <div className="mt-6 rounded-xl px-4 py-3 text-[13px]" style={{ background: "#FFFBEB", color: "#92400E", border: "1px solid #FCD34D" }}>{message}</div> : null}

      <section className="mt-7 grid gap-4 lg:grid-cols-5">
        {plans.map((plan) => {
          const highlighted = requestedUpgrade ? plan.id === requestedUpgrade : plan.id === "team";
          const limits = Object.values(plan.included_limits || {}).slice(0, 3);
          const paidSelfServe = ["professional", "team", "network"].includes(plan.id);
          const label = plan.id === "free" ? "Start free" : plan.id === "enterprise" ? "Talk to sales" : paidSelfServe ? (billingPeriod === "annual" ? "Pay annual" : "Pay monthly") : plan.name;
          return <article key={plan.id} className="flex min-w-0 min-h-[500px] flex-col overflow-hidden rounded-[22px] p-5" style={{ background: highlighted ? "#0D2B1E" : SURFACE, border: `1px solid ${highlighted ? "#0D2B1E" : BORDER}`, boxShadow: highlighted ? "0 20px 70px rgba(13,43,30,0.18)" : "0 12px 38px rgba(16,35,27,0.06)" }}>
            <div className="min-w-0"><h2 className="text-[21px] font-semibold" style={{ color: highlighted ? "white" : TEXT }}>{tx(plan.name)}</h2><CardBadge plan={plan} requestedUpgrade={requestedUpgrade} billingPeriod={billingPeriod} highlighted={highlighted} tx={tx} /><p className="mt-3 min-h-[92px] text-[12px] leading-5" style={{ color: highlighted ? "rgba(255,255,255,0.68)" : MUTED }}>{tx(plan.recommended_buyer)}</p></div>
            <PriceDisplay value={planPrice(plan, billingPeriod)} highlighted={highlighted} tx={tx} />
            <div className="mt-4 space-y-2 text-[12px]" style={{ color: highlighted ? "rgba(255,255,255,0.82)" : TEXT }}>{limits.map((limit) => <div key={limit} className="flex gap-2"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span>{tx(limit)}</span></div>)}</div>
            <div className="mt-5 space-y-2">{plan.features.slice(0, 5).map((feature) => <div key={feature} className="flex gap-2 text-[12px] leading-5" style={{ color: highlighted ? "rgba(255,255,255,0.82)" : TEXT }}><Check className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span>{tx(feature)}</span></div>)}</div>
            <div className="mt-auto pt-6"><button type="button" disabled={busyPlan === plan.id} onClick={() => choosePlan(plan)} className="h-11 w-full rounded-xl text-[13px] font-semibold disabled:opacity-60" style={{ background: highlighted ? "white" : "#0D2B1E", color: highlighted ? "#0D2B1E" : "white" }}>{busyPlan === plan.id ? tx("Opening Stripe...") : tx(label)}</button></div>
          </article>;
        })}
      </section>

      <section className="mt-10 rounded-[24px] p-5 md:p-7" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
        <div className="mb-5 flex items-center gap-2"><ShieldCheck className="h-5 w-5" style={{ color: GREEN }} /><h2 className="text-[24px] font-semibold" style={{ color: TEXT }}>{tx("Compare plans")}</h2></div>
        <div className="overflow-x-auto"><table className="w-full min-w-[900px] border-collapse text-[13px]"><thead><tr style={{ color: MUTED }}><th className="py-3 text-left font-medium">{tx("Capability")}</th>{plans.map((plan) => <th key={plan.id} className="py-3 text-center font-medium">{tx(plan.name)}</th>)}</tr></thead><tbody>{COMPARISON.map((row) => <tr key={row[0]} style={{ borderTop: `1px solid ${BORDER}` }}>{row.map((cell, index) => <td key={`${row[0]}-${index}`} className={`px-3 py-4 ${index ? "text-center" : "font-medium"}`} style={{ color: TEXT }}>{tx(cell)}</td>)}</tr>)}</tbody></table></div>
      </section>
    </main>
  </div>;
}
