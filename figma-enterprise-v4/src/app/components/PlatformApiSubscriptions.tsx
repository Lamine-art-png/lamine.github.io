import { useEffect, useState } from "react";
import { apiClient } from "../api/client";

type ApiOffer = {
  identifier: string;
  name: string;
  monthly_price_cents: number | null;
  annual_price_cents: number | null;
  included_credits: number | null;
  overage_price_per_1000_cents: number | null;
  status: string;
};
type ApiSubscription = { status: string; plan: string | null; billing_interval?: string };
type ApiBilling = { subscription?: ApiSubscription };
type CheckoutReadiness = { eligible: boolean; code: string };
type CheckoutResult = { checkout_url?: string };
type PortalResult = { portal_url?: string };

function price(cents: number | null | undefined): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", maximumFractionDigits: 0,
  }).format((cents ?? 0) / 100);
}

function secureStripeUrl(raw: string, permitted: string[]): string {
  const url = new URL(raw);
  if (url.protocol !== "https:" || !permitted.includes(url.hostname)) {
    throw new Error("Checkout could not be started. Please try again.");
  }
  return url.href;
}

export function PlatformApiSubscriptions({ canPurchase, hasLiveEnrollment }: { canPurchase: boolean; hasLiveEnrollment: boolean }) {
  const [plans, setPlans] = useState<ApiOffer[]>([]);
  const [subscription, setSubscription] = useState<ApiSubscription | null>(null);
  const [period, setPeriod] = useState<"monthly" | "annual">("monthly");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [catalogReady, setCatalogReady] = useState(false);
  const [checkoutEligible, setCheckoutEligible] = useState(false);
  const [portalAvailable, setPortalAvailable] = useState(false);
  const [refreshed, setRefreshed] = useState(0);
  const checkoutReturned = new URLSearchParams(window.location.search).get("checkout") === "success";

  useEffect(() => {
    let mounted = true;
    async function load() {
      // A pricing/catalog outage must never hide an existing customer's
      // Stripe billing-recovery controls.
      setError("");
      setCheckoutEligible(false);
      setPortalAvailable(false);
      if (canPurchase) {
        try {
          const billing = await apiClient.get<ApiBilling>("/v1/platform/developer/billing");
          if (mounted) {
            setSubscription(billing.subscription || null);
            setPortalAvailable(Boolean(billing.subscription && ["active", "trialing", "past_due", "grace", "enterprise_contract"].includes(billing.subscription.status)));
          }
        } catch (cause) {
          if (mounted) setError(cause instanceof Error ? cause.message : "Could not load billing status. Retry.");
        }
      }
      try {
        const result = await apiClient.get<{ plans: ApiOffer[] }>("/v1/platform/pricing");
        if (mounted) {
          setPlans((result.plans || []).filter((offer) => ["developer", "scale"].includes(offer.identifier)));
          setCatalogReady(true);
        }
      } catch (cause) {
        if (mounted) setError(cause instanceof Error ? cause.message : "Pricing is temporarily unavailable. Retry.");
      }
      if (canPurchase && hasLiveEnrollment) {
        try {
          const eligibility = await apiClient.get<CheckoutReadiness>("/v1/platform/developer/billing/checkout-readiness");
          if (mounted) setCheckoutEligible(Boolean(eligibility.eligible));
        } catch {
          if (mounted) setCheckoutEligible(false);
        }
      }
    }
    void load();
    return () => { mounted = false; };
  }, [canPurchase, hasLiveEnrollment, refreshed]);

  async function purchase(plan: "developer" | "scale") {
    if (busy || !canPurchase || !hasLiveEnrollment || !checkoutEligible || ["active", "trialing", "past_due", "grace", "enterprise_contract"].includes(subscription?.status || "")) return;
    setBusy(plan);
    setError("");
    try {
      const idempotency = typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : "api-checkout-" + Date.now().toString(36);
      const result = await apiClient.request<CheckoutResult>("/v1/platform/developer/billing/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotency },
        body: JSON.stringify({ plan, billing_interval: period }),
      });
      window.location.assign(secureStripeUrl(String(result.checkout_url || ""), ["checkout.stripe.com"]));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start checkout. Please try again.");
      setBusy("");
    }
  }

  async function manage() {
    setBusy("manage");
    setError("");
    try {
      const result = await apiClient.post<PortalResult>("/v1/platform/developer/billing/portal", {});
      window.location.assign(secureStripeUrl(String(result.portal_url || ""), ["billing.stripe.com"]));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Billing portal is not available yet.");
      setBusy("");
    }
  }

  const subscribed = ["active", "trialing", "past_due", "grace", "enterprise_contract"].includes(subscription?.status || "");
  const canManageBilling = portalAvailable;
  return (
    <section className="rounded-2xl border border-[#D8DED3] bg-white p-5 shadow-sm md:p-7">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-[0.15em] text-[#477553]">AGRO-AI Platform API</div>
          <h2 className="mt-2 text-[23px] font-semibold text-[#10231B]">Developer and Scale subscriptions</h2>
          <p className="mt-2 max-w-xl text-[13px] leading-6 text-[#65736A]">
            Stripe subscriptions with included API credits and metered overages. Live projects and external integrations still require production access approval.
          </p>
        </div>
        <div role="group" aria-label="Billing interval" className="flex rounded-xl border border-[#D6DDD0] bg-[#F4F7F1] p-1">
          <button type="button" aria-pressed={period === "monthly"} onClick={() => setPeriod("monthly")} className={"rounded-lg px-3 py-2 text-[12px] font-semibold " + (period === "monthly" ? "bg-white text-[#10231B] shadow-sm" : "text-[#617264]")}>Monthly</button>
          <button type="button" aria-pressed={period === "annual"} onClick={() => setPeriod("annual")} className={"rounded-lg px-3 py-2 text-[12px] font-semibold " + (period === "annual" ? "bg-white text-[#10231B] shadow-sm" : "text-[#617264]")}>Annual</button>
        </div>
      </div>
      {checkoutReturned && <p role="status" className="mt-4 rounded-xl bg-[#F1F8F4] p-3 text-[12px] text-[#315D46]">Returned from Checkout. Subscription access begins only after Stripe confirms payment.</p>}
      {error && <p role="alert" className="mt-4 rounded-xl bg-[#FFF1EA] p-3 text-[12px] text-[#823628]">{error}</p>}
      {canManageBilling && (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-[#C7D9C1] bg-[#F1F8ED] p-4">
          <span className="text-[13px] font-semibold text-[#244835]"><span>Subscription:</span> {subscription?.plan || "Platform API"} · {subscription?.status}</span>
          <button type="button" disabled={Boolean(busy)} onClick={() => void manage()} className="rounded-lg bg-[#102F22] px-3 py-2 text-[12px] font-semibold text-white disabled:opacity-50">Manage in Stripe</button>
        </div>
      )}
      {(!canPurchase || !hasLiveEnrollment) && <p className="mt-4 rounded-xl border border-[#E4D6A8] bg-[#FFF9E8] p-3 text-[12px] leading-5 text-[#7B5A13]">Subscriptions require an approved Platform API enrollment. Continue using prepaid Intelligence, or request production access before purchasing a Developer or Scale plan.</p>}
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        {plans.map((offer) => {
          const amount = period === "annual" ? offer.annual_price_cents : offer.monthly_price_cents;
          const allowed = canPurchase && hasLiveEnrollment && checkoutEligible && catalogReady && !subscribed && !busy && !portalAvailable;
          return <div key={offer.identifier} className="flex flex-col rounded-xl border border-[#D5DFD4] bg-[#FCFDFB] p-5">
            <div className="text-[16px] font-semibold text-[#10231B]">{offer.name}</div>
            <div className="mt-3 text-[28px] font-semibold text-[#10231B]">{price(amount)}<span className="ml-1 text-[12px] font-medium text-[#748078]">/{period === "annual" ? "year" : "month"}</span></div>
            <div className="mt-3 space-y-1 text-[12px] leading-5 text-[#53665A]">
              <p>{Number(offer.included_credits || 0).toLocaleString()} <span>included credits</span></p>
              <p>{price(offer.overage_price_per_1000_cents)} <span>per 1,000 additional credits</span></p>
            </div>
            <button type="button" disabled={!allowed} onClick={() => void purchase(offer.identifier as "developer" | "scale")} className="mt-5 min-h-[44px] rounded-xl bg-[#102F22] px-4 text-[12px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-45">
              {busy === offer.identifier ? <span>Opening Stripe…</span> : subscribed ? <span>Current subscription managed above</span> : allowed ? <span>Continue to Stripe checkout</span> : <span>Production access required</span>}
            </button>
          </div>;
        })}
      </div>
      {canPurchase && <button type="button" onClick={() => setRefreshed((count) => count + 1)} className="mt-4 text-[12px] font-semibold text-[#315D46] underline">Refresh billing status</button>}
    </section>
  );
}
