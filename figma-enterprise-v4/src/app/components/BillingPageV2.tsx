import { useCallback, useState } from "react";
import { ArrowRight, CreditCard, RefreshCw } from "lucide-react";
import { apiClient, ProductCheckoutPayload } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, GREEN, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type PlanId = ProductCheckoutPayload["plan_id"];
type Plan = { id: PlanId; name: string; public_price_monthly: string; public_price_annual: string; recommended_buyer: string };
type QuotaRow = { metric: string; label: string; used: number; reserved: number; limit: number | null; remaining: number | null; percent_used: number | null; recommended_plan: PlanId };
type CommercialSummary = { current_plan: Plan; plan_id: PlanId; billing_status: string; subscription_source?: string; current_period_start?: string | null; current_period_end?: string | null; cancel_at_period_end?: boolean; quota_rows: QuotaRow[]; upgrade_options: Plan[]; can_manage_billing?: boolean };

function dateLabel(value?: string | null) {
  if (!value) return "Not scheduled";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function used(row: QuotaRow) { return Number(row.used || 0) + Number(row.reserved || 0); }
function pct(row: QuotaRow) { return row.limit === null ? 0 : row.limit ? Math.min(100, Math.round((used(row) / row.limit) * 100)) : 100; }
function barColor(row: QuotaRow) { const p = pct(row); return p >= 100 ? "#B42318" : p >= 80 ? "#B7791F" : GREEN; }

export function BillingPageV2() {
  const { currentOrganization } = useAuth();
  const state = usePortalResource<CommercialSummary>(useCallback(() => apiClient.billing.commercialSummary(), []));
  const [period, setPeriod] = useState<"monthly" | "annual">("monthly");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const summary = state.data;

  async function upgrade(plan: Plan) {
    setBusy(plan.id); setMessage("");
    try {
      if (plan.id === "enterprise") {
        const result = await apiClient.sales.contact({ category: "sales", type: "upgrade", subject: "Enterprise pricing request", message: "Customer requested Enterprise rollout from Billing.", source_page: "billing" }) as Record<string, unknown>;
        setMessage(String(result.message || "Enterprise request received."));
        return;
      }
      const result = await apiClient.billing.checkout({ plan_id: plan.id, billing_period: period }) as Record<string, unknown>;
      if (typeof result.checkout_url === "string" && result.checkout_url) window.location.assign(result.checkout_url);
      else setMessage(String(result.message || "Upgrade request received."));
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not start checkout."); }
    finally { setBusy(""); }
  }

  async function manageBilling() {
    if (!currentOrganization?.id) return;
    setBusy("portal"); setMessage("");
    try {
      const result = await apiClient.billing.createPortalSession({ organization_id: currentOrganization.id }) as Record<string, unknown>;
      if (typeof result.portal_url === "string" && result.portal_url) window.location.assign(result.portal_url);
      else setMessage("Billing portal is not available yet.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not open billing portal."); }
    finally { setBusy(""); }
  }

  return <div className="min-h-screen" style={{ background: BG }}>
    <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div><div className="mb-3 flex gap-2"><StatusBadge label="Commercial control" tone="good" /><StatusBadge label={summary?.billing_status || "loading"} /></div><h1 className="text-[30px] font-semibold" style={{ color: TEXT }}>Billing & usage</h1><p className="mt-2 max-w-3xl text-[14px] leading-7" style={{ color: MUTED }}>Exact plan limits, period usage and remaining capacity enforced by AGRO-AI.</p></div>
        <div className="flex gap-2">{summary?.can_manage_billing && currentOrganization?.id ? <PortalButton variant="secondary" onClick={manageBilling} disabled={busy === "portal"}><CreditCard className="h-4 w-4" /> Manage billing</PortalButton> : null}<PortalButton variant="secondary" onClick={() => state.refresh()}><RefreshCw className="h-4 w-4" /> Refresh</PortalButton></div>
      </div>
    </header>

    <main className="space-y-6 px-8 py-6" style={{ maxWidth: 1280 }}>
      {state.error ? <Notice warn>{state.error}</Notice> : null}{message ? <Notice>{message}</Notice> : null}
      <section className="grid gap-4 md:grid-cols-4">
        <Metric label="Current plan" value={summary?.current_plan?.name || "—"} detail={summary?.current_plan ? (period === "annual" ? summary.current_plan.public_price_annual : summary.current_plan.public_price_monthly) : "Loading"} />
        <Metric label="Billing state" value={summary?.billing_status || "—"} detail={summary?.subscription_source ? `Source: ${summary.subscription_source}` : "Commercial state"} />
        <Metric label="Period start" value={dateLabel(summary?.current_period_start)} detail="Usage window" />
        <Metric label="Period reset" value={dateLabel(summary?.current_period_end)} detail={summary?.cancel_at_period_end ? "Cancels at period end" : "Quota reset"} />
      </section>

      <section className="rounded-[24px] p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
        <h2 className="text-[22px] font-semibold" style={{ color: TEXT }}>Exact plan capacity</h2><p className="mt-2 text-[13px]" style={{ color: MUTED }}>Used plus reserved work is compared with the active commercial limit. Reserved work prevents concurrent over-consumption.</p>
        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{(summary?.quota_rows || []).map((row) => <Quota key={row.metric} row={row} currentPlan={summary?.plan_id || "free"} />)}</div>
      </section>

      <section className="rounded-[24px] p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
        <div className="flex flex-wrap items-center justify-between gap-4"><div><h2 className="text-[22px] font-semibold" style={{ color: TEXT }}>Upgrade capacity</h2><p className="mt-2 text-[13px]" style={{ color: MUTED }}>Checkout delegates to the authoritative subscription path.</p></div><div className="inline-flex rounded-lg p-1" style={{ background: BG, border: `1px solid ${BORDER}` }}>{(["monthly", "annual"] as const).map((value) => <button key={value} onClick={() => setPeriod(value)} className="rounded-md px-3 py-2 text-[12px] capitalize" style={{ background: period === value ? GREEN : "transparent", color: period === value ? "white" : TEXT }}>{value}</button>)}</div></div>
        <div className="mt-5 grid gap-4 md:grid-cols-3">{(summary?.upgrade_options || []).map((plan) => <article key={plan.id} className="flex min-h-[210px] flex-col rounded-2xl p-5" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="text-[17px] font-semibold" style={{ color: TEXT }}>{plan.name}</div><div className="mt-1 text-[13px] font-semibold" style={{ color: GREEN }}>{period === "annual" ? plan.public_price_annual : plan.public_price_monthly}</div><p className="mt-4 text-[12px] leading-6" style={{ color: MUTED }}>{plan.recommended_buyer}</p><div className="mt-auto pt-5"><PortalButton onClick={() => upgrade(plan)} disabled={busy === plan.id}>{busy === plan.id ? "Opening…" : plan.id === "enterprise" ? "Talk to sales" : `Upgrade to ${plan.name}`} <ArrowRight className="h-4 w-4" /></PortalButton></div></article>)}</div>
      </section>
    </main>
  </div>;
}

function Quota({ row, currentPlan }: { row: QuotaRow; currentPlan: PlanId }) {
  const value = used(row); const p = pct(row); const exhausted = row.limit !== null && value >= Number(row.limit);
  return <article className="rounded-2xl p-4" style={{ background: BG, border: `1px solid ${exhausted ? "#F4B4AE" : BORDER}` }}><div className="flex justify-between gap-3"><div><div className="text-[13px] font-semibold" style={{ color: TEXT }}>{row.label}</div><div className="mt-1 text-[11px]" style={{ color: MUTED }}>{row.metric.replaceAll("_", " ")}</div></div><StatusBadge label={exhausted ? "Limit reached" : p >= 80 ? "Near limit" : "Available"} tone={exhausted || p >= 80 ? "warn" : "good"} /></div><div className="mt-4 flex items-end justify-between"><div className="text-[24px] font-semibold" style={{ color: TEXT }}>{value}<span className="text-[13px]" style={{ color: MUTED }}> / {row.limit === null ? "Contract" : row.limit}</span></div><div className="text-[11px]" style={{ color: MUTED }}>{row.remaining === null ? "Contract capacity" : `${row.remaining} remaining`}</div></div><div className="mt-3 h-2 overflow-hidden rounded-full bg-[#E5EAE4]">{row.limit !== null ? <div className="h-full rounded-full" style={{ width: `${p}%`, background: barColor(row) }} /> : null}</div>{row.reserved ? <div className="mt-2 text-[10px]" style={{ color: MUTED }}>{row.reserved} reserved by in-flight work</div> : null}{(exhausted || p >= 80) && row.recommended_plan !== currentPlan ? <a className="mt-3 inline-flex items-center gap-1 text-[11px] font-semibold" style={{ color: GREEN }} href={`/pricing?upgrade=${row.recommended_plan}&metric=${encodeURIComponent(row.metric)}`}>Increase capacity <ArrowRight className="h-3 w-3" /></a> : null}</article>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) { return <article className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="text-[11px] uppercase tracking-wider" style={{ color: MUTED }}>{label}</div><div className="mt-2 text-[20px] font-semibold capitalize" style={{ color: TEXT }}>{value}</div><div className="mt-1 text-[11px]" style={{ color: MUTED }}>{detail}</div></article>; }
function Notice({ children, warn = false }: { children: React.ReactNode; warn?: boolean }) { return <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: warn ? "#FFFBEB" : "#F0FDF4", color: warn ? "#92400E" : "#15803D", border: warn ? "1px solid #FCD34D" : "1px solid #BBF7D0" }}>{children}</div>; }
