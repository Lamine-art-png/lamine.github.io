import {
  ArrowLeft,
  ArrowRight,
  Check,
  CreditCard,
  ExternalLink,
  Loader2,
  ReceiptText,
  ShieldCheck,
  Sparkles,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";
import logoImg from "../../imports/agro-ai-logo-1.png";
import { API_BASE_URL, apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { ImageWithFallback } from "./figma/ImageWithFallback";


type Plan = {
  identifier: "developer" | "scale";
  name: string;
  monthlyPriceCents: number;
  includedCredits: number;
  overagePricePerThousandCents: number;
  projects: number;
  serviceAccounts: number;
  webhooks: number;
  requestLogRetentionDays: number;
  support: string;
};

type Subscription = {
  id?: string;
  status?: string;
  plan?: string | null;
  billing_interval?: string | null;
  current_period_end?: string | null;
  grace_ends_at?: string | null;
  cancel_at_period_end?: boolean;
};

type BillingPayload = {
  subscription?: Subscription;
  portal_billing_is_separate?: boolean;
};

const tokenKey = "agroai_access_token";

const PLANS: Plan[] = [
  {
    identifier: "developer",
    name: "Developer",
    monthlyPriceCents: 14_900,
    includedCredits: 250_000,
    overagePricePerThousandCents: 75,
    projects: 3,
    serviceAccounts: 5,
    webhooks: 3,
    requestLogRetentionDays: 30,
    support: "Email technical support",
  },
  {
    identifier: "scale",
    name: "Scale",
    monthlyPriceCents: 74_900,
    includedCredits: 2_000_000,
    overagePricePerThousandCents: 35,
    projects: 10,
    serviceAccounts: 20,
    webhooks: 20,
    requestLogRetentionDays: 90,
    support: "Priority technical support",
  },
];

function platformPath(path: string) {
  return window.location.hostname.toLowerCase() === "platform.agroai-pilot.com"
    ? path
    : `/platform${path}`;
}

function money(cents: number) {
  const amount = cents / 100;
  const fractions = Number.isInteger(amount) ? 0 : 2;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: fractions,
    maximumFractionDigits: fractions,
  }).format(amount);
}

function count(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function date(value?: string | null) {
  if (!value) return "Not available";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(parsed);
}

function errorMessage(cause: unknown, fallback: string) {
  return cause instanceof Error && cause.message.trim() ? cause.message : fallback;
}

async function parseResponse(response: Response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return response.json();
  const text = await response.text();
  return text ? { message: text } : {};
}

async function authenticatedPost(
  path: string,
  payload?: unknown,
  idempotencyKey?: string,
) {
  const token = localStorage.getItem(tokenKey);
  const headers = new Headers({ "Content-Type": "application/json" });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers,
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const body = await parseResponse(response);
  if (!response.ok) {
    const record = body && typeof body === "object" ? body as Record<string, unknown> : {};
    const detail = record.detail;
    const nested = detail && typeof detail === "object" ? detail as Record<string, unknown> : {};
    const message = typeof nested.code === "string"
      ? nested.code.replaceAll("_", " ")
      : typeof detail === "string"
        ? detail
        : typeof record.message === "string"
          ? record.message
          : `Billing request failed with status ${response.status}`;
    throw new Error(message);
  }
  return body && typeof body === "object" ? body as Record<string, unknown> : {};
}

function planFeatures(plan: Plan) {
  return [
    `${count(plan.includedCredits)} API credits included each month`,
    `${count(plan.projects)} projects`,
    `${count(plan.serviceAccounts)} service accounts`,
    `${count(plan.webhooks)} webhook endpoints`,
    `${count(plan.requestLogRetentionDays)}-day request log retention`,
    plan.support,
  ];
}

function statusClass(status?: string) {
  const normalized = String(status || "").toLowerCase();
  if (["active", "trialing", "free"].includes(normalized)) {
    return "border-[#BAD4B2] bg-[#F1F8ED] text-[#285A35]";
  }
  if (["past_due", "unpaid"].includes(normalized)) {
    return "border-[#E6C992] bg-[#FFF8E7] text-[#765615]";
  }
  return "border-[#D8DED3] bg-[#F5F7F3] text-[#5C6960]";
}

export function PlatformBillingPage() {
  const { currentOrganization, user, logout } = useAuth();
  const [billing, setBilling] = useState<BillingPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const result = await apiClient.get<BillingPayload>("/v1/platform/developer/billing");
      setBilling(result);
    } catch (cause) {
      setError(errorMessage(cause, "Platform API billing is not available yet."));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const subscription = billing?.subscription;
  const hasSubscription = Boolean(
    subscription?.status && subscription.status !== "none",
  );
  const activePlan = String(subscription?.plan || "");

  const checkout = async (plan: Plan) => {
    setWorking(plan.identifier);
    setError("");
    try {
      const key = typeof crypto !== "undefined" && "randomUUID" in crypto
        ? `platform-checkout-${crypto.randomUUID()}`
        : `platform-checkout-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const result = await authenticatedPost(
        "/v1/platform/developer/billing/checkout",
        { plan: plan.identifier, billing_interval: "monthly" },
        key,
      );
      const checkoutUrl = String(result.checkout_url || "");
      if (!checkoutUrl.startsWith("https://checkout.stripe.com/")) {
        throw new Error("Stripe Checkout did not return a valid secure payment URL.");
      }
      window.location.assign(checkoutUrl);
    } catch (cause) {
      setError(errorMessage(cause, "Stripe Checkout could not be opened."));
      setWorking("");
    }
  };

  const manage = async () => {
    setWorking("portal");
    setError("");
    try {
      const result = await authenticatedPost(
        "/v1/platform/developer/billing/portal",
      );
      const portalUrl = String(result.portal_url || "");
      if (!portalUrl.startsWith("https://billing.stripe.com/")) {
        throw new Error("Stripe did not return a valid billing portal URL.");
      }
      window.location.assign(portalUrl);
    } catch (cause) {
      setError(errorMessage(cause, "The Stripe billing portal could not be opened."));
      setWorking("");
    }
  };

  return (
    <div className="min-h-screen bg-[#F3F1E9] text-[#10231B]">
      <header className="border-b border-[#D8DED3] bg-[#FFFDF8]">
        <div className="mx-auto flex h-[76px] max-w-[1280px] items-center justify-between px-5 md:px-8">
          <a href={platformPath("/home")} className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center overflow-hidden rounded-xl bg-[#173B2B] shadow-[0_8px_24px_rgba(16,47,34,.18)]">
              <ImageWithFallback src={logoImg} alt="AGRO-AI" className="h-full w-full object-contain" />
            </div>
            <div>
              <div className="text-[14px] font-semibold">AGRO-AI</div>
              <div className="text-[11px] text-[#75827A]">Platform API Billing</div>
            </div>
          </a>
          <div className="flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <div className="text-[11px] font-semibold">{currentOrganization?.name || "AGRO-AI organization"}</div>
              <div className="text-[10px] text-[#7A877F]">{user?.email || "Verified account"}</div>
            </div>
            <button onClick={() => void logout()} className="rounded-xl border border-[#D3DBD1] bg-white px-3 py-2 text-[11px] font-semibold text-[#314C3D]">Sign out</button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1180px] px-5 py-8 md:px-8 md:py-12">
        <a href={platformPath("/home")} className="inline-flex items-center gap-2 text-[12px] font-semibold text-[#315D46]"><ArrowLeft className="h-4 w-4" /> Back to API console</a>
        <div className="mt-7 max-w-3xl">
          <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#4E725D]">Usage-based infrastructure</div>
          <h1 className="mt-3 text-[38px] font-semibold tracking-[-0.045em] md:text-[48px]">Choose the capacity your product needs.</h1>
          <p className="mt-4 max-w-2xl text-[14px] leading-7 text-[#65736A]">Every plan includes monthly API credits. Additional usage is measured by durable server events and added to the same Stripe invoice at the published rate.</p>
        </div>

        {error ? <div role="alert" className="mt-6 rounded-xl border border-[#E4B9AE] bg-[#FFF2EE] px-4 py-3 text-[12px] leading-6 text-[#823628]">{error}</div> : null}

        {loading ? <div className="mt-8 flex min-h-[320px] items-center justify-center rounded-2xl border border-[#D8DED3] bg-[#FFFDF8]"><Loader2 className="h-6 w-6 animate-spin text-[#315D46]" /></div> : null}

        {!loading && hasSubscription ? (
          <section className="mt-8 overflow-hidden rounded-[24px] border border-[#CAD8C5] bg-[#FFFDF8] shadow-[0_24px_70px_rgba(16,47,34,.08)]">
            <div className="grid lg:grid-cols-[1.1fr_.9fr]">
              <div className="p-7 md:p-9">
                <div className="flex flex-wrap items-center gap-3">
                  <span className={`rounded-full border px-3 py-1 text-[10px] font-bold uppercase tracking-[.12em] ${statusClass(subscription?.status)}`}>{subscription?.status}</span>
                  <span className="text-[11px] text-[#6C7A71]">{subscription?.billing_interval || "subscription"}</span>
                </div>
                <h2 className="mt-5 text-[30px] font-semibold tracking-[-0.035em]">{activePlan ? `${activePlan[0].toUpperCase()}${activePlan.slice(1)} plan` : "Platform API subscription"}</h2>
                <p className="mt-3 text-[13px] leading-7 text-[#65736A]">Your API subscription is separate from the Enterprise Portal. Stripe manages the payment method, invoices, tax details, and cancellation controls.</p>
                <div className="mt-7 flex flex-wrap gap-3">
                  <button onClick={() => void manage()} disabled={working === "portal"} className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#102F22] px-4 text-[12px] font-semibold text-white disabled:opacity-50">{working === "portal" ? <Loader2 className="h-4 w-4 animate-spin" /> : <CreditCard className="h-4 w-4" />} Manage billing</button>
                  <a href={platformPath("/usage")} className="inline-flex h-11 items-center gap-2 rounded-xl border border-[#D3DBD1] bg-white px-4 text-[12px] font-semibold text-[#183427]">Review usage <ArrowRight className="h-4 w-4" /></a>
                </div>
              </div>
              <div className="border-t border-[#DDE3D9] bg-[#F6F7F3] p-7 lg:border-l lg:border-t-0 md:p-9">
                <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-1">
                  <div><div className="text-[10px] font-bold uppercase tracking-[.15em] text-[#708078]">Current period ends</div><div className="mt-2 text-[17px] font-semibold">{date(subscription?.current_period_end)}</div></div>
                  <div><div className="text-[10px] font-bold uppercase tracking-[.15em] text-[#708078]">Renewal</div><div className="mt-2 text-[17px] font-semibold">{subscription?.cancel_at_period_end ? "Cancels at period end" : "Automatic"}</div></div>
                  {subscription?.grace_ends_at ? <div><div className="text-[10px] font-bold uppercase tracking-[.15em] text-[#9A6518]">Payment grace ends</div><div className="mt-2 text-[17px] font-semibold text-[#765615]">{date(subscription.grace_ends_at)}</div></div> : null}
                </div>
              </div>
            </div>
          </section>
        ) : null}

        {!loading && !hasSubscription ? (
          <div className="mt-8 grid gap-5 lg:grid-cols-2">
            {PLANS.map((plan) => {
              const featured = plan.identifier === "scale";
              return (
                <section key={plan.identifier} className={`relative overflow-hidden rounded-[24px] border bg-[#FFFDF8] p-7 shadow-[0_20px_60px_rgba(16,47,34,.07)] md:p-8 ${featured ? "border-[#8FB36D]" : "border-[#D8DED3]"}`}>
                  {featured ? <div className="absolute right-0 top-0 rounded-bl-xl bg-[#DCEF8B] px-3 py-2 text-[9px] font-bold uppercase tracking-[.14em] text-[#173325]">For production scale</div> : null}
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#EDF4E8] text-[#315D46]">{featured ? <Zap className="h-5 w-5" /> : <Sparkles className="h-5 w-5" />}</div>
                  <h2 className="mt-6 text-[26px] font-semibold tracking-[-0.035em]">{plan.name}</h2>
                  <div className="mt-4 flex items-end gap-2"><div className="text-[40px] font-semibold tracking-[-0.05em]">{money(plan.monthlyPriceCents)}</div><div className="pb-2 text-[11px] text-[#75827A]">/ month</div></div>
                  <div className="mt-4 rounded-xl border border-[#DCE4D7] bg-[#F7F9F5] px-4 py-3 text-[11px] leading-6 text-[#5D6D63]"><span className="font-semibold text-[#315D46]">{count(plan.includedCredits)} credits included.</span> {money(plan.overagePricePerThousandCents)} per 1,000 additional credits.</div>
                  <ul className="mt-6 space-y-3">{planFeatures(plan).map((feature) => <li key={feature} className="flex gap-3 text-[12px] leading-6 text-[#52635A]"><span className="mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-[#DDEBCF] text-[#315D46]"><Check className="h-2.5 w-2.5" /></span>{feature}</li>)}</ul>
                  <button onClick={() => void checkout(plan)} disabled={Boolean(working)} className={`mt-7 inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl text-[12px] font-semibold transition disabled:opacity-50 ${featured ? "bg-[#102F22] text-white hover:bg-[#17432F]" : "border border-[#B9CAB5] bg-white text-[#183427] hover:bg-[#F4F8F0]"}`}>{working === plan.identifier ? <Loader2 className="h-4 w-4 animate-spin" /> : <CreditCard className="h-4 w-4" />} Continue to secure checkout</button>
                </section>
              );
            })}
          </div>
        ) : null}

        <section className="mt-8 grid gap-4 md:grid-cols-3">
          <div className="rounded-2xl border border-[#D8DED3] bg-[#FFFDF8] p-5"><ShieldCheck className="h-5 w-5 text-[#315D46]" /><h3 className="mt-4 text-[14px] font-semibold">Server-authoritative pricing</h3><p className="mt-2 text-[11px] leading-6 text-[#6A776F]">Price IDs and usage records never come from browser input.</p></div>
          <div className="rounded-2xl border border-[#D8DED3] bg-[#FFFDF8] p-5"><CreditCard className="h-5 w-5 text-[#315D46]" /><h3 className="mt-4 text-[14px] font-semibold">Payments handled by Stripe</h3><p className="mt-2 text-[11px] leading-6 text-[#6A776F]">Payment details are entered on Stripe-hosted Checkout and managed in Stripe’s portal.</p></div>
          <div className="rounded-2xl border border-[#D8DED3] bg-[#FFFDF8] p-5"><ReceiptText className="h-5 w-5 text-[#315D46]" /><h3 className="mt-4 text-[14px] font-semibold">Durable usage ledger</h3><p className="mt-2 text-[11px] leading-6 text-[#6A776F]">Meter exports are idempotent and reconciled against Stripe before invoicing.</p></div>
        </section>

        <footer className="mt-10 flex flex-col gap-3 border-t border-[#D5DCD0] py-6 text-[10px] text-[#78857D] sm:flex-row sm:items-center sm:justify-between">
          <span>© 2026 AGRO-AI. Platform API billing.</span>
          <div className="flex gap-4"><a href="https://agroai-pilot.com/terms-of-service" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1">Terms <ExternalLink className="h-3 w-3" /></a><a href="https://agroai-pilot.com/privacy-policy" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1">Privacy <ExternalLink className="h-3 w-3" /></a></div>
        </footer>
      </main>
    </div>
  );
}
