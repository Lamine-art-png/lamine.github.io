import { ReactNode, useCallback, useState } from "react";
import { Lock, Mail, ShieldCheck, Users } from "lucide-react";
import { apiClient, ProductCheckoutPayload, SupportTicketPayload } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, GREEN, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type PlanId = "free" | "professional" | "team" | "network" | "enterprise";

type Plan = {
  id: PlanId;
  name: string;
  public_price_monthly: string;
  public_price_annual: string;
  recommended_buyer: string;
  included_limits?: Record<string, string>;
  features: string[];
  locked_features?: string[];
  support_level?: string;
  cta_label: string;
  annual_savings_badge?: string | null;
  is_custom_pricing?: boolean;
};

type ProductPlans = {
  plans: Plan[];
  service_add_ons: { id: string; name: string; price: string; description: string }[];
};

type BillingSummary = {
  current_plan?: Plan;
  billing_status?: string;
  monthly_price?: string;
  annual_price?: string;
  usage_summary?: Record<string, unknown>;
  upgrade_options?: Plan[];
  service_add_ons?: { id: string; name: string; price: string; description: string }[];
  annual_savings?: string;
  entitlements?: Record<string, unknown>;
};

type AdminRequest = {
  id: string;
  type: string;
  priority?: "low" | "medium" | "high" | "urgent";
  company?: string;
  subject?: string;
  requester?: string;
  status?: "received" | "triaged" | "in_progress" | "waiting_on_customer" | "closed";
  created_at?: string;
  source_page?: string;
  message?: string;
};

type ShellResponse = {
  user?: { id?: string; name?: string; email?: string };
  organization?: { id?: string; name?: string };
  workspace?: { id?: string; name?: string };
  plan?: { id?: string; name?: string };
};

const faq = [
  ["What is AGRO-AI built for?", "AGRO-AI helps farms, water agencies, advisors, lenders, insurers, and agricultural networks operate from one secure evidence workspace."],
  ["What does Free include?", "Free is for evaluation. It includes one workspace, one user, limited uploads, sample reports, and basic readiness."],
  ["When do I move to Professional?", "Professional is for commercial farms and advisors that need reports, PDF output, evidence imports, operator tasks, and standard connectors."],
  ["When do I need Team?", "Team is for operating groups that need shared workspaces, role controls, controller readiness, field ops, and audit trails."],
  ["Who is Network for?", "Network is built for grower networks, water districts, exporters, lenders, insurers, and multi-farm programs."],
  ["What happens above Network?", "Enterprise is for custom integrations, security review, SSO/SAML planning, dedicated rollout, custom SLAs, and program-specific reporting."],
];

const LOCAL_PRODUCT_PLANS: ProductPlans = {
  plans: [
    {
      id: "free",
      name: "Free",
      public_price_monthly: "$0/mo",
      public_price_annual: "$0/yr",
      recommended_buyer: "Evaluation workspaces and small pilot teams getting organized.",
      included_limits: { seats: "1 user", workspaces: "1 evaluation workspace", ai: "Limited AGRO-AI messages" },
      features: ["Basic readiness view", "Manual evidence upload", "Sample report workflow", "Starter field context"],
      locked_features: ["Advanced connectors", "Report email delivery", "Controller readiness", "Team seats"],
      support_level: "Self-guided setup",
      cta_label: "Start free",
      is_custom_pricing: false,
    },
    {
      id: "professional",
      name: "Professional",
      public_price_monthly: "$299/mo",
      public_price_annual: "$2,990/yr",
      recommended_buyer: "Growers and operators ready to run AGRO-AI reports and field intelligence in one workspace.",
      included_limits: { seats: "3 users", workspaces: "3 workspaces", reports: "PDF-ready reports" },
      features: ["AGRO-AI reports", "Evidence imports", "Operator tasks", "Email report delivery", "Standard connector workflows"],
      support_level: "Standard support",
      cta_label: "Upgrade",
      annual_savings_badge: "2 months free",
      is_custom_pricing: false,
    },
    {
      id: "team",
      name: "Team",
      public_price_monthly: "$799/mo",
      public_price_annual: "$7,990/yr",
      recommended_buyer: "Operations teams coordinating field tasks, controller readiness, reports, approvals, and shared evidence.",
      included_limits: { seats: "10 users", workspaces: "10 workspaces", roles: "Role controls" },
      features: ["Shared evidence library", "Controller readiness", "Field operations", "Compliance reporting", "Priority support"],
      support_level: "Priority support",
      cta_label: "Upgrade",
      annual_savings_badge: "Team rollout savings",
      is_custom_pricing: false,
    },
    {
      id: "network",
      name: "Network",
      public_price_monthly: "$1,500/mo",
      public_price_annual: "$15,000/yr",
      recommended_buyer: "Water agencies, grower networks, exporters, lenders, insurers, and multi-site programs.",
      included_limits: { scope: "Multi-site", seats: "25 users", rollups: "Network reporting" },
      features: ["Multi-workspace rollups", "Customer/account reporting", "Advanced integrations", "Program dashboards", "Rollout support"],
      support_level: "Priority rollout",
      cta_label: "Talk to sales",
      annual_savings_badge: "Program pricing",
      is_custom_pricing: false,
    },
    {
      id: "enterprise",
      name: "Enterprise",
      public_price_monthly: "Custom",
      public_price_annual: "Custom",
      recommended_buyer: "Organizations needing governance review, custom controller/API integrations, security process, and dedicated support.",
      included_limits: { seats: "Custom seats", data: "Custom data scope", security: "Security review" },
      features: ["Custom integrations", "SSO/SAML planning", "Enterprise support", "Security review", "Custom SLAs"],
      support_level: "Enterprise success",
      cta_label: "Talk to sales",
      is_custom_pricing: true,
    },
  ],
  service_add_ons: [
    { id: "onboarding", name: "Onboarding & rollout", price: "Scoped", description: "Workspace launch, first evidence review, connector planning, operating workflows, and user enablement." },
    { id: "custom_integration", name: "Custom integrations", price: "Scoped", description: "Provider-specific controller, ERP, district, sensor, or compliance-system integration work." },
    { id: "security_review", name: "Enterprise security review", price: "Scoped", description: "Security documentation, access review, deployment architecture, and governance support." },
  ],
};

const COMPARISON_ROWS = [
  { group: "Workspace", label: "Users", free: "1", professional: "3", team: "10", network: "25", enterprise: "Custom" },
  { group: "Workspace", label: "Workspaces", free: "1", professional: "3", team: "10", network: "Multi-site", enterprise: "Custom" },
  { group: "AI & Reports", label: "AGRO-AI messages", free: "Limited", professional: "Commercial", team: "Team", network: "Network", enterprise: "Custom" },
  { group: "AI & Reports", label: "PDF reports", free: "Sample", professional: "✓", team: "✓", network: "Rollups", enterprise: "Custom" },
  { group: "Controller & Field Ops", label: "Field tasks", free: "—", professional: "✓", team: "✓", network: "✓", enterprise: "✓" },
  { group: "Controller & Field Ops", label: "Controller gateway", free: "—", professional: "Readiness", team: "Readiness + ops", network: "Advanced", enterprise: "Custom" },
  { group: "Compliance", label: "Compliance packets", free: "—", professional: "Drafts", team: "✓", network: "Rollups", enterprise: "Custom" },
  { group: "Integrations", label: "Evidence imports", free: "Limited", professional: "✓", team: "✓", network: "Advanced", enterprise: "Custom" },
  { group: "Support", label: "Support level", free: "Self-guided", professional: "Standard", team: "Priority", network: "Rollout", enterprise: "Dedicated" },
];

function productPlansWithFallback(remote?: ProductPlans | null): ProductPlans {
  const byId = new Map<string, Plan>();
  for (const plan of LOCAL_PRODUCT_PLANS.plans) byId.set(plan.id, plan);
  for (const plan of remote?.plans || []) byId.set(plan.id, { ...byId.get(plan.id), ...plan } as Plan);
  return {
    plans: LOCAL_PRODUCT_PLANS.plans.map((plan) => byId.get(plan.id) || plan),
    service_add_ons: remote?.service_add_ons?.length ? remote.service_add_ons : LOCAL_PRODUCT_PLANS.service_add_ons,
  };
}

function safe(value: unknown, fallback = "Not available") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function Page({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>{title}</h1>
        {subtitle ? <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>{subtitle}</p> : null}
      </header>
      <main className="space-y-5 px-8 py-6" style={{ maxWidth: 1240 }}>{children}</main>
    </div>
  );
}

function Panel({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="mb-4 flex items-center justify-between gap-4">
        <h2 className="text-[18px] font-semibold" style={{ color: TEXT }}>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Row({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex items-center justify-between gap-6 border-t py-3 text-[13px]" style={{ borderColor: BORDER }}>
      <span style={{ color: MUTED }}>{label}</span>
      <span className="text-right font-medium" style={{ color: TEXT }}>{safe(value)}</span>
    </div>
  );
}

function Banner({ message, tone = "good" }: { message: string; tone?: "good" | "warn" }) {
  const good = tone === "good";
  return (
    <div className="rounded-lg px-4 py-3 text-[13px]" style={{ background: good ? "#F0FDF4" : "#FFFBEB", color: good ? "#15803D" : "#92400E", border: good ? "1px solid #BBF7D0" : "1px solid #FCD34D" }}>
      {message}
    </div>
  );
}

function FaqItem({ question, answer }: { question: string; answer: string }) {
  const [open, setOpen] = useState(false);
  return (
    <button type="button" onClick={() => setOpen((value) => !value)} className="w-full rounded-xl px-4 py-3 text-left" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="flex items-center justify-between gap-4">
        <span className="text-[14px] font-semibold" style={{ color: TEXT }}>{question}</span>
        <span className="text-[18px]" style={{ color: MUTED }}>{open ? "−" : "+"}</span>
      </div>
      {open ? <p className="mt-3 text-[13px] leading-6" style={{ color: MUTED }}>{answer}</p> : null}
    </button>
  );
}

function UpgradeModal({ title, body, cta, onClose, onConfirm }: { title: string; body: string; cta: string; onClose: () => void; onConfirm: () => void }) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/35 px-4">
      <div className="w-full max-w-[420px] rounded-2xl p-6" style={{ background: "#FFFDF8", border: `1px solid ${BORDER}` }}>
        <div className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-widest" style={{ color: GREEN }}>
          <Lock className="h-4 w-4" />
          Upgrade required
        </div>
        <h3 className="mt-3 text-[22px] font-semibold" style={{ color: TEXT }}>{title}</h3>
        <p className="mt-3 text-[14px] leading-7" style={{ color: MUTED }}>{body}</p>
        <div className="mt-5 flex gap-3">
          <PortalButton onClick={onConfirm}>{cta}</PortalButton>
          <PortalButton variant="secondary" onClick={onClose}>Close</PortalButton>
        </div>
      </div>
    </div>
  );
}

function PlanCard({ plan, billingPeriod, onSelect }: { plan: Plan; billingPeriod: "monthly" | "annual"; onSelect: (plan: Plan) => void }) {
  const price = billingPeriod === "annual" ? plan.public_price_annual : plan.public_price_monthly;
  const highlighted = plan.id === "team";
  const limits = Object.values(plan.included_limits || {}).slice(0, 3);
  const features = (plan.features || []).slice(0, 4);

  return (
    <section className="flex min-h-[430px] w-[260px] shrink-0 flex-col rounded-[22px] p-5 md:w-auto" style={{ background: highlighted ? "#0D2B1E" : SURFACE, border: `1px solid ${highlighted ? "#0D2B1E" : BORDER}`, boxShadow: highlighted ? "0 20px 70px rgba(13,43,30,0.18)" : "0 12px 38px rgba(16,35,27,0.06)" }}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[21px] font-semibold" style={{ color: highlighted ? "white" : TEXT }}>{plan.name}</h2>
          <p className="mt-2 min-h-[54px] text-[12px] leading-5" style={{ color: highlighted ? "rgba(255,255,255,0.68)" : MUTED }}>{plan.recommended_buyer}</p>
        </div>
        {highlighted ? <StatusBadge label="Most popular" tone="good" /> : plan.annual_savings_badge ? <StatusBadge label={plan.annual_savings_badge} tone="good" /> : null}
      </div>
      <div className="mt-5 text-[30px] font-semibold" style={{ color: highlighted ? "white" : TEXT }}>{price}</div>
      <div className="mt-4 space-y-2 text-[12px]" style={{ color: highlighted ? "rgba(255,255,255,0.82)" : TEXT }}>
        {limits.map((limit) => <div key={limit} className="truncate">✓ {limit}</div>)}
      </div>
      <div className="mt-5 space-y-2">
        {features.map((feature) => <div key={feature} className="text-[12px] leading-5" style={{ color: highlighted ? "rgba(255,255,255,0.82)" : TEXT }}>✓ {feature}</div>)}
      </div>
      <div className="mt-auto pt-6">
        <button type="button" onClick={() => onSelect(plan)} className="h-11 w-full rounded-xl text-[13px] font-semibold" style={{ background: highlighted ? "white" : "#0D2B1E", color: highlighted ? "#0D2B1E" : "white" }}>
          {plan.id === "free" ? "Start free" : plan.id === "enterprise" || plan.id === "network" ? "Talk to sales" : "Upgrade"}
        </button>
      </div>
    </section>
  );
}

export function PricingPage() {
  const plansState = usePortalResource<ProductPlans>(useCallback(() => apiClient.product.plans(), []));
  const [billingPeriod, setBillingPeriod] = useState<"monthly" | "annual">("monthly");
  const [message, setMessage] = useState("");
  const productPlans = productPlansWithFallback(plansState.data);
  const usingLocalFallback = !plansState.data?.plans?.length || Boolean(plansState.error);

  const selectPlan = async (plan: Plan) => {
    setMessage("");
    try {
      const hasSession = Boolean(localStorage.getItem("agroai_access_token"));
      if (!hasSession && plan.id === "free") {
        setMessage("Create your account to start free.");
        window.history.replaceState(null, "", "/?mode=register");
        return;
      }
      if (!hasSession || plan.id === "network" || plan.id === "enterprise" || plan.id === "team") {
        const response = await apiClient.sales.contact({
          category: "sales",
          type: plan.id === "network" ? "network_plan" : "upgrade",
          subject: `${plan.name} plan request`,
          message: `Customer requested ${plan.name} pricing follow-up from pricing page.`,
          source_page: "pricing",
        }) as Record<string, unknown>;
        setMessage(`${safe(response.message, "Request received.")} ${response.request_id ? `Request ${response.request_id}` : ""}`.trim());
        return;
      }
      const response = await apiClient.billing.checkout({ plan_id: plan.id, billing_period: billingPeriod } as ProductCheckoutPayload) as Record<string, unknown>;
      if (typeof response.checkout_url === "string") {
        window.location.assign(response.checkout_url);
        return;
      }
      setMessage(`${safe(response.message, "Upgrade request received.")} ${response.request_id ? `Request ${response.request_id}` : ""}`.trim());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upgrade request received.");
    }
  };

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <main className="mx-auto max-w-[1180px] px-5 py-10 md:px-8">
        <section className="rounded-[28px] px-6 py-9 md:px-10 md:py-12" style={{ background: "#0D2B1E", color: "white" }}>
          <div className="text-[12px] font-semibold uppercase tracking-[0.22em]" style={{ color: "rgba(255,255,255,0.64)" }}>AGRO-AI Pricing</div>
          <div className="mt-5 grid gap-8 lg:grid-cols-[1fr_auto] lg:items-end">
            <div>
              <h1 className="max-w-3xl text-[40px] font-semibold leading-[1.04] tracking-tight md:text-[54px]">Choose the operating layer for your farm intelligence.</h1>
              <p className="mt-5 max-w-2xl text-[15px] leading-7" style={{ color: "rgba(255,255,255,0.72)" }}>Start with a workspace, then scale into reports, controller readiness, field operations, compliance, and network reporting.</p>
            </div>
            <div>
              <div className="inline-flex rounded-full bg-white/10 p-1">
                {(["monthly", "annual"] as const).map((period) => (
                  <button key={period} type="button" onClick={() => setBillingPeriod(period)} className="rounded-full px-4 py-2 text-[13px] font-medium capitalize" style={{ background: billingPeriod === period ? "white" : "transparent", color: billingPeriod === period ? "#0D2B1E" : "white" }}>
                    {period}
                  </button>
                ))}
              </div>
              <div className="mt-2 text-[12px]" style={{ color: "rgba(255,255,255,0.62)" }}>Annual plans include rollout savings.</div>
            </div>
          </div>
        </section>

        <div className="mt-6 space-y-3">
          {message ? <Banner tone="warn" message={message} /> : null}
          {usingLocalFallback ? <Banner tone="warn" message="Using launch-safe local pricing while live plan details refresh." /> : null}
        </div>

        <section className="mt-7 overflow-x-auto pb-2">
          <div className="grid min-w-[1040px] grid-cols-5 gap-4">
            {productPlans.plans.map((plan) => <PlanCard key={plan.id} plan={plan} billingPeriod={billingPeriod} onSelect={selectPlan} />)}
          </div>
        </section>

        <section className="mt-10 rounded-[24px] p-5 md:p-7" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
            <div>
              <h2 className="text-[24px] font-semibold" style={{ color: TEXT }}>Compare plans</h2>
              <p className="mt-2 text-[13px]" style={{ color: MUTED }}>Grouped by the operating capabilities enterprise buyers ask about first.</p>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] border-collapse text-[13px]">
              <thead>
                <tr style={{ color: MUTED }}>
                  <th className="py-3 text-left font-medium">Capability</th>
                  {productPlans.plans.map((plan) => <th key={plan.id} className="py-3 text-center font-medium">{plan.name}</th>)}
                </tr>
              </thead>
              <tbody>
                {COMPARISON_ROWS.map((row, index) => {
                  const previous = COMPARISON_ROWS[index - 1];
                  return (
                    <tr key={`${row.group}-${row.label}`} style={{ borderTop: `1px solid ${BORDER}` }}>
                      <td className="py-4">
                        {previous?.group !== row.group ? <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest" style={{ color: GREEN }}>{row.group}</div> : null}
                        <div className="font-medium" style={{ color: TEXT }}>{row.label}</div>
                      </td>
                      {productPlans.plans.map((plan) => <td key={plan.id} className="px-3 py-4 text-center" style={{ color: TEXT }}>{safe((row as Record<string, string>)[plan.id], "—")}</td>)}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section className="mt-8 grid gap-4 md:grid-cols-3">
          {productPlans.service_add_ons.map((item) => (
            <article key={item.id} className="rounded-[20px] p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              <div className="text-[12px] font-semibold uppercase tracking-widest" style={{ color: GREEN }}>Service add-on</div>
              <h3 className="mt-3 text-[18px] font-semibold" style={{ color: TEXT }}>{item.name}</h3>
              <div className="mt-2 text-[13px] font-medium" style={{ color: MUTED }}>{item.price}</div>
              <p className="mt-3 text-[13px] leading-6" style={{ color: MUTED }}>{item.description}</p>
            </article>
          ))}
        </section>

        <section className="mt-8 rounded-[24px] p-5 md:p-7" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <h2 className="text-[24px] font-semibold" style={{ color: TEXT }}>Questions before launch</h2>
          <div className="mt-5 grid gap-3 md:grid-cols-2">
            {faq.map(([question, answer]) => <FaqItem key={question} question={question} answer={answer} />)}
          </div>
        </section>
      </main>
    </div>
  );
}

export function ProfilePage() {
  const profileState = usePortalResource<Record<string, unknown>>(useCallback(() => apiClient.account.profile(), []));
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const profile = profileState.data || {};
  const user = (profile.user || {}) as Record<string, unknown>;
  const organization = (profile.organization || {}) as Record<string, unknown>;
  const workspace = (profile.workspace || {}) as Record<string, unknown>;
  const plan = (profile.plan || {}) as Record<string, unknown>;

  const save = async () => {
    const response = await apiClient.account.updateProfile({ name: name || user.name }) as Record<string, unknown>;
    setMessage("Profile updated.");
    setName(String(((response.user || {}) as Record<string, unknown>).name || ""));
    await profileState.refresh();
  };

  return (
    <Page title="Profile" subtitle="Manage your personal profile, organization identity, and workspace context.">
      {message ? <Banner message={message} /> : null}
      {profileState.error ? <Banner tone="warn" message={profileState.error} /> : null}
      <Panel title="Personal profile" action={<PortalButton onClick={save}>Save profile</PortalButton>}>
        <label className="mb-4 block text-[12px]" style={{ color: MUTED }}>
          Name
          <input value={name || String(user.name || "")} onChange={(event) => setName(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
        </label>
        <Row label="Email" value={user.email} />
        <Row label="Organization" value={organization.name} />
        <Row label="Role" value={profile.role} />
      </Panel>
      <Panel title="Workspace">
        <Row label="Workspace" value={workspace.name} />
        <Row label="Mode" value={workspace.mode === "live" ? "Live operations" : "Evaluation workspace"} />
      </Panel>
      <Panel title="Plan">
        <Row label="Plan" value={plan.name} />
      </Panel>
    </Page>
  );
}

export function BillingPage() {
  const summaryState = usePortalResource<BillingSummary>(useCallback(() => apiClient.billing.summary(), []));
  const [message, setMessage] = useState("");
  const [checkoutPeriod, setCheckoutPeriod] = useState<"monthly" | "annual">("monthly");
  const summary = summaryState.data;

  const upgrade = async (plan: Plan) => {
    try {
      const response = await apiClient.billing.checkout({ plan_id: plan.id, billing_period: checkoutPeriod } as ProductCheckoutPayload) as Record<string, unknown>;
      if (typeof response.checkout_url === "string") {
        window.location.assign(response.checkout_url);
        return;
      }
      setMessage(String(response.message || "Upgrade request received."));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upgrade request received.");
    }
  };

  return (
    <Page title="Billing" subtitle="Review your current plan, usage, and upgrade paths.">
      {message ? <Banner message={message} /> : null}
      {summaryState.error ? <Banner tone="warn" message={summaryState.error} /> : null}
      <div className="grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
        <Panel title="Current plan">
          <Row label="Plan" value={summary?.current_plan?.name} />
          <Row label="Billing status" value={summary?.billing_status} />
          <Row label="Monthly price" value={summary?.monthly_price} />
          <Row label="Annual price" value={summary?.annual_price} />
          <Row label="Annual savings" value={summary?.annual_savings} />
        </Panel>
        <Panel title="Usage">
          <Row label="Evidence uploads" value={summary?.usage_summary?.uploads} />
          <Row label="AGRO-AI messages" value={summary?.usage_summary?.agro_ai_runs} />
          <Row label="Reports" value={summary?.usage_summary?.reports} />
          <Row label="Field updates" value={summary?.usage_summary?.field_updates} />
        </Panel>
      </div>
      <Panel title="Upgrade options">
        <div className="mb-4 inline-flex rounded-lg p-1" style={{ background: BG, border: `1px solid ${BORDER}` }}>
          {(["monthly", "annual"] as const).map((period) => (
            <button key={period} type="button" onClick={() => setCheckoutPeriod(period)} className="rounded-md px-3 py-2 text-[12px] font-medium capitalize" style={{ background: checkoutPeriod === period ? GREEN : "transparent", color: checkoutPeriod === period ? "white" : TEXT }}>
              {period}
            </button>
          ))}
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {(summary?.upgrade_options || []).map((plan) => (
            <div key={plan.id} className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
              <div className="font-semibold text-[16px]" style={{ color: TEXT }}>{plan.name}</div>
              <div className="mt-1 text-[13px]" style={{ color: MUTED }}>{checkoutPeriod === "annual" ? plan.public_price_annual : plan.public_price_monthly}</div>
              <div className="mt-3 text-[13px] leading-6" style={{ color: TEXT }}>{plan.recommended_buyer}</div>
              <div className="mt-4"><PortalButton onClick={() => upgrade(plan)}>{plan.cta_label}</PortalButton></div>
            </div>
          ))}
          {!summary?.upgrade_options?.length ? <p className="text-[13px]" style={{ color: MUTED }}>No upgrade options returned yet.</p> : null}
        </div>
      </Panel>
      <Panel title="Add-ons">
        <div className="grid gap-4 md:grid-cols-3">
          {(summary?.service_add_ons || []).map((service) => (
            <div key={service.id} className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
              <div className="font-semibold text-[14px]" style={{ color: TEXT }}>{service.name}</div>
              <div className="mt-2 text-[13px] font-medium" style={{ color: GREEN }}>{service.price}</div>
              <p className="mt-2 text-[12px] leading-6" style={{ color: MUTED }}>{service.description}</p>
            </div>
          ))}
        </div>
      </Panel>
    </Page>
  );
}

export function SecurityPage() {
  const securityState = usePortalResource<Record<string, unknown>>(useCallback(() => apiClient.account.security(), []));
  const { verification, requestVerification } = useAuth();
  const [message, setMessage] = useState("");
  const data = securityState.data || {};
  const emailVerification = (data.email_verification || {}) as Record<string, unknown>;
  const twoFactor = (data.two_factor || {}) as Record<string, unknown>;

  const resend = async () => {
    const nextMessage = await requestVerification(verification?.email);
    setMessage(nextMessage);
  };

  const requestTwoFactor = async () => {
    const response = await apiClient.account.startTwoFactor() as Record<string, unknown>;
    setMessage(String(response.message || "Two-factor setup request received."));
  };

  return (
    <Page title="Security" subtitle="Protect workspace access and route verification or additional controls professionally.">
      {message ? <Banner message={message} /> : null}
      {securityState.error ? <Banner tone="warn" message={securityState.error} /> : null}
      <div className="grid gap-5 md:grid-cols-2">
        <Panel title="Email verification" action={<PortalButton onClick={resend}>{safe(emailVerification.action_label, "Resend verification email")}</PortalButton>}>
          <ShieldCheck className="mb-3 h-5 w-5" style={{ color: GREEN }} />
          <Row label="Status" value={emailVerification.customer_label} />
          <Row label="Verification state" value={verification?.status || emailVerification.status} />
        </Panel>
        <Panel title="Two-factor access" action={<PortalButton variant="secondary" onClick={requestTwoFactor}>{safe(twoFactor.action_label, "Request two-factor setup")}</PortalButton>}>
          <ShieldCheck className="mb-3 h-5 w-5" style={{ color: GREEN }} />
          <Row label="Status" value={twoFactor.customer_label} />
          <Row label="Availability" value="Available on request" />
        </Panel>
      </div>
    </Page>
  );
}

export function SupportPage() {
  const [form, setForm] = useState<SupportTicketPayload>({ category: "support", subject: "", message: "", source_page: "support" });
  const [message, setMessage] = useState("");

  const submit = async () => {
    const response = await apiClient.support.ticket(form) as Record<string, unknown>;
    setMessage(String(response.message || "Thanks — your request was received."));
    setForm({ category: "support", subject: "", message: "", source_page: "support" });
  };

  return (
    <Page title="Support" subtitle="Request onboarding, integration help, operational support, or report review from the AGRO-AI team.">
      {message ? <Banner message={message} /> : null}
      <Panel title="Contact support" action={<PortalButton onClick={submit} disabled={!form.subject.trim() || !form.message.trim()}>Send request</PortalButton>}>
        <div className="grid gap-4 md:grid-cols-2">
          <label className="text-[12px]" style={{ color: MUTED }}>
            Request type
            <select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value as SupportTicketPayload["category"] })} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
              <option value="support">Support</option>
              <option value="integration">Integration</option>
              <option value="issue">Issue</option>
              <option value="onboarding">Onboarding</option>
              <option value="sales">Sales</option>
            </select>
          </label>
          <label className="text-[12px]" style={{ color: MUTED }}>
            Subject
            <input value={form.subject} onChange={(event) => setForm({ ...form, subject: event.target.value })} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
          </label>
        </div>
        <label className="mt-4 block text-[12px]" style={{ color: MUTED }}>
          Message
          <textarea value={form.message} onChange={(event) => setForm({ ...form, message: event.target.value })} rows={5} className="mt-1 w-full rounded-lg px-3 py-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
        </label>
      </Panel>
    </Page>
  );
}

export function AdminRequestsPage() {
  const [tab, setTab] = useState("all");
  const [selected, setSelected] = useState<AdminRequest | null>(null);
  const requestState = usePortalResource<{ requests: AdminRequest[] }>(useCallback(() => apiClient.adminRequests.list(tab === "all" ? undefined : tab), [tab]));
  const requests = requestState.data?.requests || [];
  const tabs = [["all", "All"], ["support", "Support"], ["sales", "Sales"], ["integration", "Integrations"], ["onboarding", "Onboarding"], ["bug", "Bugs"], ["upgrade", "Upgrade requests"]];

  const updateStatus = async (statusValue: NonNullable<AdminRequest["status"]>) => {
    if (!selected?.id) return;
    const response = await apiClient.adminRequests.update(selected.id, { status: statusValue }) as { request?: AdminRequest };
    setSelected(response.request || { ...selected, status: statusValue });
    await requestState.refresh();
  };

  return (
    <Page title="Requests" subtitle="Review tracked support, onboarding, integration, upgrade, and sales requests for your organization.">
      <div className="flex flex-wrap gap-2">
        {tabs.map(([id, label]) => <button key={id} type="button" onClick={() => setTab(id)} className="rounded-lg px-3 py-2 text-[12px]" style={{ background: tab === id ? GREEN : SURFACE, color: tab === id ? "white" : TEXT, border: `1px solid ${BORDER}` }}>{label}</button>)}
      </div>
      {requestState.error ? <Banner tone="warn" message={requestState.error} /> : null}
      <div className="grid gap-5 lg:grid-cols-[0.95fr_1.05fr]">
        <Panel title="Inbox">
          <div className="space-y-3">
            {requests.map((row) => (
              <button key={row.id} type="button" onClick={() => setSelected(row)} className="w-full rounded-xl px-4 py-3 text-left" style={{ background: selected?.id === row.id ? "#EEF8E8" : BG, border: `1px solid ${BORDER}` }}>
                <div className="flex items-center justify-between gap-3">
                  <div className="font-semibold text-[13px]" style={{ color: TEXT }}>{safe(row.subject)}</div>
                  <StatusBadge label={safe(row.status)} tone="neutral" />
                </div>
                <div className="mt-1 text-[12px]" style={{ color: MUTED }}>{safe(row.type)} • {safe(row.requester)}</div>
              </button>
            ))}
            {!requests.length ? <p className="text-[13px]" style={{ color: MUTED }}>No requests yet.</p> : null}
          </div>
        </Panel>
        <Panel title="Request detail" action={selected ? <PortalButton variant="secondary" onClick={() => updateStatus("closed")}>Close request</PortalButton> : null}>
          {selected ? (
            <div className="space-y-3">
              <Row label="Subject" value={selected.subject} />
              <Row label="Type" value={selected.type} />
              <Row label="Requester" value={selected.requester} />
              <Row label="Status" value={selected.status} />
              <Row label="Priority" value={selected.priority} />
              <Row label="Source" value={selected.source_page} />
              <p className="rounded-lg p-4 text-[13px] leading-6" style={{ background: BG, color: TEXT, border: `1px solid ${BORDER}` }}>{safe(selected.message, "No message provided.")}</p>
            </div>
          ) : <p className="text-[13px]" style={{ color: MUTED }}>Select a request to review its details.</p>}
        </Panel>
      </div>
    </Page>
  );
}

export function TeamPage() {
  const shellState = usePortalResource<ShellResponse>(useCallback(() => apiClient.product.shell(), []));
  const membersState = usePortalResource<{ members: { id: string; name?: string; email?: string; role?: string }[] }>(useCallback(() => apiClient.team.members(), []));
  const invitationsState = usePortalResource<{ invitations: { id: string; email: string; status: string; role?: string }[] }>(useCallback(() => apiClient.team.invitations(), []));
  const { currentWorkspace } = useAuth();
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"owner" | "admin" | "manager" | "operator" | "viewer">("operator");
  const [message, setMessage] = useState("");
  const [upgradeOpen, setUpgradeOpen] = useState(false);
  const canInvite = ["team", "network", "enterprise"].includes(String(shellState.data?.plan?.id || ""));

  const startTeamUpgrade = async () => {
    setUpgradeOpen(false);
    const response = await apiClient.sales.contact({
      category: "sales",
      subject: "Team plan request",
      message: "Customer requested Team plan access from the Team page.",
      workspace_id: currentWorkspace?.id,
      source_page: "team",
    }) as Record<string, unknown>;
    setMessage(String(response.message || "Team upgrade request received."));
  };

  const sendInvite = async () => {
    if (!inviteEmail.trim()) return;
    try {
      if (canInvite) {
        const response = await apiClient.team.invite({ email: inviteEmail.trim(), role: inviteRole }) as Record<string, unknown>;
        setMessage(String(response.message || "Invitation sent."));
        await invitationsState.refresh();
      } else {
        const response = await apiClient.support.ticket({
          category: "support",
          subject: "Team invitation request",
          message: `Please invite ${inviteEmail} as ${inviteRole}.`,
          workspace_id: currentWorkspace?.id,
          source_page: "team",
        }) as Record<string, unknown>;
        setMessage(`${safe(response.message, "Team invitation request received.")} ${response.request_id ? `Request ${response.request_id}` : ""}`.trim());
      }
      setInviteEmail("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Team invitation request received.");
    }
  };

  return (
    <Page title="Team" subtitle="Invite and role controls are prepared for workspace collaboration.">
      {message ? <Banner message={message} /> : null}
      {shellState.error ? <Banner tone="warn" message={shellState.error} /> : null}
      <Panel title="Current user">
        <Row label="Name" value={shellState.data?.user?.name} />
        <Row label="Email" value={shellState.data?.user?.email} />
        <Row label="Workspace" value={shellState.data?.workspace?.name} />
        <Row label="Plan" value={shellState.data?.plan?.name} />
      </Panel>
      <Panel title="Invite teammate" action={<PortalButton disabled={!inviteEmail.trim()} onClick={sendInvite}>{canInvite ? "Send invitation" : "Request invite"}</PortalButton>}>
        <div className="grid gap-4 md:grid-cols-[1fr_220px]">
          <label className="text-[12px]" style={{ color: MUTED }}>
            Email
            <input value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} placeholder="teammate@company.com" />
          </label>
          <label className="text-[12px]" style={{ color: MUTED }}>
            Role
            <select value={inviteRole} onChange={(event) => setInviteRole(event.target.value as typeof inviteRole)} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
              <option value="owner">Owner</option>
              <option value="admin">Admin</option>
              <option value="manager">Manager</option>
              <option value="operator">Operator</option>
              <option value="viewer">Viewer</option>
            </select>
          </label>
        </div>
        {!canInvite ? (
          <div className="mt-4 rounded-lg p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
            <div className="flex items-start gap-3">
              <Lock className="mt-1 h-5 w-5" style={{ color: GREEN }} />
              <p className="text-[13px] leading-6" style={{ color: MUTED }}>Direct team invitations are included in Team, Network, and Enterprise. Free/Professional workspaces can submit an invite request.</p>
            </div>
          </div>
        ) : null}
      </Panel>
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Members">
          <div className="space-y-2">
            {(membersState.data?.members || []).map((member) => <Row key={member.id} label={safe(member.name || member.email)} value={member.role} />)}
            {membersState.error ? <p className="text-[13px]" style={{ color: MUTED }}>{membersState.error}</p> : null}
            {!membersState.data?.members?.length ? <p className="text-[13px]" style={{ color: MUTED }}>No team members loaded yet.</p> : null}
          </div>
        </Panel>
        <Panel title="Invitations">
          <div className="space-y-2">
            {(invitationsState.data?.invitations || []).map((row) => <Row key={row.id} label={row.email} value={row.status} />)}
            {invitationsState.error ? <p className="text-[13px]" style={{ color: MUTED }}>{invitationsState.error}</p> : null}
            {!invitationsState.data?.invitations?.length ? <p className="text-[13px]" style={{ color: MUTED }}>No invitations yet.</p> : null}
          </div>
        </Panel>
      </div>
      {upgradeOpen ? <UpgradeModal title="Upgrade to Team" body="Team invitations and role controls are included in the Team plan." cta="Upgrade to Team" onClose={() => setUpgradeOpen(false)} onConfirm={startTeamUpgrade} /> : null}
    </Page>
  );
}

export function OnboardingPage() {
  const state = usePortalResource<{ onboarding: Record<string, unknown> }>(useCallback(() => apiClient.onboarding.state(), []));
  const [message, setMessage] = useState("");
  const onboarding = state.data?.onboarding || {};

  const updateStep = async (step: string) => {
    await apiClient.onboarding.update({ current_step: step, completed_steps: [step] });
    setMessage("Onboarding updated.");
    await state.refresh();
  };

  const complete = async () => {
    const response = await apiClient.onboarding.complete() as Record<string, unknown>;
    setMessage(String(response.message || "Your workspace is ready."));
    await state.refresh();
  };

  return (
    <Page title="Onboarding" subtitle="Set up the operating context AGRO-AI needs before it can help your team move faster.">
      {message ? <Banner message={message} /> : null}
      {state.error ? <Banner tone="warn" message={state.error} /> : null}
      <Panel title="Workspace setup" action={<PortalButton onClick={complete}>Complete onboarding</PortalButton>}>
        <Row label="Current step" value={onboarding.current_step} />
        <Row label="Selected plan" value={onboarding.selected_plan} />
        <Row label="Organization type" value={onboarding.organization_type} />
        <Row label="Primary goal" value={onboarding.primary_goal} />
        <div className="mt-4 flex flex-wrap gap-2">
          {["organization", "scope", "plan", "start_operating"].map((step) => <PortalButton key={step} variant="secondary" onClick={() => updateStep(step)}>{step.replace("_", " ")}</PortalButton>)}
        </div>
      </Panel>
    </Page>
  );
}

export function WorkspaceSettingsPage() {
  return (
    <Page title="Settings" subtitle="Workspace configuration and operating preferences for AGRO-AI.">
      <Panel title="Workspace settings">
        <div className="flex items-start gap-3">
          <Users className="mt-1 h-5 w-5" style={{ color: GREEN }} />
          <p className="text-[13px] leading-6" style={{ color: MUTED }}>Workspace-level configuration is prepared for sources, team roles, notifications, and operating preferences.</p>
        </div>
      </Panel>
      <Panel title="Secure workspace access">
        <div className="flex items-start gap-3">
          <Mail className="mt-1 h-5 w-5" style={{ color: GREEN }} />
          <p className="text-[13px] leading-6" style={{ color: MUTED }}>Verified accounts and role-aware access keep the portal focused on serious agricultural operators and partners.</p>
        </div>
      </Panel>
    </Page>
  );
}
