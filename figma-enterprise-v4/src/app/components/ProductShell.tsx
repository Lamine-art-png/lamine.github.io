import { ReactNode, useCallback, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Lock, Mail, ShieldCheck, Users } from "lucide-react";
import { apiClient, ProductCheckoutPayload, SupportTicketPayload, TeamInvitationPayload } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, GREEN, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type Plan = {
  id: "free" | "professional" | "team" | "network" | "enterprise";
  name: string;
  public_price_monthly: string;
  public_price_annual: string;
  recommended_buyer: string;
  included_limits: Record<string, string>;
  features: string[];
  locked_features?: string[];
  support_level: string;
  cta_label: string;
  annual_savings_badge?: string | null;
  is_custom_pricing: boolean;
};

type ProductPlans = {
  plans: Plan[];
  service_add_ons: { id: string; name: string; price: string; description: string }[];
};

type BillingSummary = {
  current_plan: Plan;
  billing_status: string;
  monthly_price: string;
  annual_price: string;
  usage_summary: Record<string, unknown>;
  upgrade_options: Plan[];
  service_add_ons: { id: string; name: string; price: string; description: string }[];
  annual_savings?: string;
  entitlements?: Record<string, unknown>;
};

type ShellResponse = {
  user?: { name?: string; email?: string };
  workspace?: { name?: string; mode?: string };
  organization?: { name?: string; status?: string };
  plan?: Plan;
  entitlements?: Record<string, unknown>;
  usage?: Record<string, unknown>;
};

type TeamMembersResponse = {
  members: { id: string; name?: string; email?: string; role?: string }[];
};

type TeamInvitationsResponse = {
  invitations: { id: string; email: string; role: string; status: string; created_at?: string }[];
};

const faq = [
  ["What is AGRO-AI built for?", "AGRO-AI helps farms, water agencies, advisors, lenders, insurers, and agricultural networks operate from one secure evidence workspace."],
  ["What does Free include?", "Free is for pilots and early testing. It includes one workspace, one user, limited uploads, limited AGRO-AI messages, and basic readiness."],
  ["When do I move to Professional?", "Professional is the step up when you need report generation, PDF output, connectors, water risk briefs, and regular operating use."],
  ["When do I need Team?", "Team is the right fit when multiple operators, advisors, or managers need shared evidence, role controls, and invite workflows."],
  ["Who is Network for?", "Network is built for grower networks, water districts, exporters, lenders, insurers, and multi-farm programs."],
  ["What happens above Network?", "Larger deployments move to Enterprise for custom seats, governance, security review, and tailored reporting."],
];

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
      <main className="space-y-5 px-8 py-6" style={{ maxWidth: 1180 }}>{children}</main>
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
  const highlighted = plan.id === "professional";
  return (
    <section className="flex min-h-[520px] flex-col rounded-[20px] p-6" style={{ background: SURFACE, border: `1px solid ${highlighted ? GREEN : BORDER}`, boxShadow: highlighted ? "0 12px 50px rgba(28,89,55,0.08)" : "none" }}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-[24px] font-semibold" style={{ color: TEXT }}>{plan.name}</h2>
          <p className="mt-2 text-[13px] leading-6" style={{ color: MUTED }}>{plan.recommended_buyer}</p>
        </div>
        {plan.annual_savings_badge ? <StatusBadge label={plan.annual_savings_badge} tone="good" /> : null}
      </div>
      <div className="mt-6 text-[34px] font-semibold" style={{ color: TEXT }}>{price}</div>
      <div className="mt-5 space-y-2 text-[13px]" style={{ color: TEXT }}>
        {Object.values(plan.included_limits).map((limit) => <div key={limit}>{limit}</div>)}
      </div>
      <div className="mt-6 space-y-2">
        {plan.features.map((feature) => (
          <div key={feature} className="text-[13px] leading-6" style={{ color: TEXT }}>{feature}</div>
        ))}
      </div>
      {plan.locked_features?.length ? (
        <div className="mt-6 rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
          <div className="mb-2 text-[11px] font-semibold uppercase" style={{ color: MUTED }}>Locked on this tier</div>
          <div className="space-y-2">
            {plan.locked_features.map((feature) => (
              <div key={feature} className="flex items-center gap-2 text-[12px]" style={{ color: MUTED }}>
                <Lock className="h-3.5 w-3.5" />
                {feature}
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <div className="mt-auto pt-6">
        <PortalButton onClick={() => onSelect(plan)}>{plan.cta_label}</PortalButton>
      </div>
    </section>
  );
}

export function PricingPage() {
  const plansState = usePortalResource<ProductPlans>(useCallback(() => apiClient.product.plans(), []));
  const [billingPeriod, setBillingPeriod] = useState<"monthly" | "annual">("monthly");
  const [message, setMessage] = useState("");

  const selectPlan = async (plan: Plan) => {
    setMessage("");
    try {
      const hasSession = Boolean(localStorage.getItem("agroai_access_token"));
      if (!hasSession && plan.id === "free") {
        setMessage("Create your account to start free.");
        return;
      }
      if (!hasSession && (plan.id === "network" || plan.id === "enterprise")) {
        const response = await apiClient.sales.contact({
          type: "sales",
          subject: `${plan.name} pricing request`,
          message: `Customer requested ${plan.name} pricing follow-up from public pricing.`,
          source_page: "pricing",
        }) as Record<string, unknown>;
        setMessage(String(response.message || "Sales request received."));
        return;
      }
      const response = await apiClient.billing.checkout({ plan_id: plan.id, billing_period: billingPeriod } satisfies ProductCheckoutPayload) as Record<string, unknown>;
      if (typeof response.checkout_url === "string") {
        window.location.assign(response.checkout_url);
        return;
      }
      setMessage(String(response.message || "Upgrade request received."));
      setMessage(`${safe(response.message, "Upgrade request received.")} ${response.request_id ? `Request ${response.request_id}` : ""}`.trim());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upgrade request received.");
    }
  };

  return (
    <Page title="AGRO-AI pricing" subtitle="A new kind of agricultural intelligence is here. Scale from pilot workspaces to operating teams, grower networks, and enterprise programs.">
      <div className="inline-flex rounded-xl p-1" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
    <Page title="AGRO-AI pricing" subtitle="Start with a field operating workspace. Scale to networks, agencies, and multi-farm organizations.">
      <div className="inline-flex rounded-lg p-1" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
        {(["monthly", "annual"] as const).map((period) => (
          <button key={period} type="button" onClick={() => setBillingPeriod(period)} className="rounded-lg px-4 py-2 text-[13px] font-medium capitalize" style={{ background: billingPeriod === period ? GREEN : "transparent", color: billingPeriod === period ? "white" : TEXT }}>
            {period}
          </button>
        ))}
      </div>
      {message ? <div className="rounded-lg border border-[#D8E5CB] bg-[#F8FBF3] px-4 py-3 text-[13px]" style={{ color: "#385544" }}>{message}</div> : null}
      <div className="grid gap-5 xl:grid-cols-5">
        {(plansState.data?.plans || []).map((plan) => <PlanCard key={plan.id} plan={plan} billingPeriod={billingPeriod} onSelect={selectPlan} />)}
      </div>
      <Panel title="Frequently asked questions">
        <div className="space-y-3">
          {faq.map(([question, answer]) => <FaqItem key={question} question={question} answer={answer} />)}
        </div>
      </Panel>
    </Page>
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
    await apiClient.account.updateProfile({ name: name || user.name });
    setMessage("Profile updated.");
    const response = await apiClient.account.updateProfile({ name: name || user.name }) as Record<string, unknown>;
    setMessage("Profile updated.");
    setName(String(((response.user || {}) as Record<string, unknown>).name || ""));
    await profileState.refresh();
  };

  return (
    <Page title="Profile" subtitle="Manage your personal profile, organization identity, and workspace context.">
      {message ? <Banner tone="good" message={message} /> : null}
      <Panel title="Personal profile" action={<PortalButton onClick={save}>Save profile</PortalButton>}>
        <label className="mb-4 block text-[12px]" style={{ color: MUTED }}>
          Name
          <input value={name || String(user.name || "")} onChange={(event) => setName(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
        </label>
        <Row label="Email" value={user.email} />
        <Row label="Organization" value={organization.name} />
    <Page title="Profile" subtitle="Manage your account, organization, workspace, plan, security, and requests.">
      {message ? <div className="rounded-lg px-4 py-3 text-[13px]" style={{ background: "#F0FDF4", color: "#15803D", border: "1px solid #BBF7D0" }}>{message}</div> : null}
      <Panel title="Personal profile" action={<PortalButton onClick={save}>Save profile</PortalButton>}>
        <label className="block text-[12px] mb-4" style={{ color: MUTED }}>
          Name
          <input value={name || String(user.name || "")} onChange={(event) => setName(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
        </label>
        <Row label="Name" value={user.name} />
        <Row label="Email" value={user.email} />
      </Panel>
      <Panel title="Organization">
        <Row label="Company" value={organization.name} />
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

  const requestUpgrade = async (planId: ProductCheckoutPayload["plan_id"]) => {
    try {
      const response = await apiClient.billing.checkout({ plan_id: planId, billing_period: checkoutPeriod }) as Record<string, unknown>;
      if (typeof response.checkout_url === "string") {
        window.location.assign(response.checkout_url);
        return;
      }
      setMessage(String(response.message || "Upgrade request received. AGRO-AI will follow up."));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upgrade request received.");
    }
  };

  return (
    <Page title="Billing" subtitle="Review your current plan, usage, and upgrade paths without exposing internal billing setup details.">
      {message ? <Banner tone="good" message={message} /> : null}
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
              <div className="mt-4">
                <PortalButton onClick={() => requestUpgrade(plan.id)}>{plan.cta_label}</PortalButton>
              </div>
            </div>
          ))}
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
      <Panel title="Invoices">
        <p className="text-[13px]" style={{ color: MUTED }}>
          Invoices will appear here when live billing has started.
        </p>
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
      {message ? <Banner tone="good" message={message} /> : null}
      <div className="grid gap-5 md:grid-cols-2">
        <Panel title="Email verification" action={<PortalButton onClick={resend}>{safe(emailVerification.action_label, "Resend verification email")}</PortalButton>}>
          <Row label="Status" value={emailVerification.customer_label} />
          <Row label="Verification state" value={verification?.status || emailVerification.status} />
        </Panel>
        <Panel title="Two-factor access" action={<PortalButton variant="secondary" onClick={requestTwoFactor}>{safe(twoFactor.action_label, "Request two-factor setup")}</PortalButton>}>
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
    setMessage(String(response.message || "Thanks - your request was received."));
    setForm({ category: "support", subject: "", message: "", source_page: "support" });
  };

  return (
    <Page title="Support" subtitle="Request onboarding, integration help, operational support, or report review from the AGRO-AI team.">
      {message ? <Banner tone="good" message={message} /> : null}
      <Panel title="Contact support" action={<PortalButton onClick={submit}>Send request</PortalButton>}>
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
  const state = usePortalResource<{ requests: Record<string, unknown>[] }>(useCallback(() => apiClient.adminRequests.list(), []));
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);

  return (
    <Page title="Requests" subtitle="Review tracked support, onboarding, integration, upgrade, and sales requests for your organization.">
      <div className="grid gap-5 lg:grid-cols-[0.92fr_1.08fr]">
        <Panel title="Inbox">
          <div className="space-y-3">
            {(state.data?.requests || []).map((row) => (
              <button key={String(row.id)} type="button" onClick={() => setSelected(row)} className="w-full rounded-xl px-4 py-3 text-left" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                <div className="flex items-center justify-between gap-3">
                  <div className="font-semibold text-[13px]" style={{ color: TEXT }}>{safe(row.subject)}</div>
                  <StatusBadge label={safe(row.status)} tone="neutral" />
                </div>
                <div className="mt-1 text-[12px]" style={{ color: MUTED }}>{safe(row.type)} • {safe(row.requester)}</div>
              </button>
            ))}
          </div>
        </Panel>
        <Panel title="Request detail">
          {selected ? (
            <div className="space-y-3">
              <Row label="Subject" value={selected.subject} />
              <Row label="Type" value={selected.type} />
              <Row label="Requester" value={selected.requester} />
              <Row label="Status" value={selected.status} />
              <Row label="Priority" value={selected.priority} />
            </div>
          ) : (
            <p className="text-[13px]" style={{ color: MUTED }}>Select a request to review its details.</p>
          )}
        </Panel>
      </div>
    </Page>
  );
}

type AdminRequest = {
  id: string;
  type: string;
  priority: "low" | "medium" | "high" | "urgent";
  company?: string;
  subject: string;
  requester?: string;
  status: "received" | "triaged" | "in_progress" | "waiting_on_customer" | "closed";
  created_at?: string;
  source_page?: string;
  message?: string;
};

export function AdminRequestsPage() {
  const [tab, setTab] = useState("all");
  const [selected, setSelected] = useState<AdminRequest | null>(null);
  const requestState = usePortalResource<{ requests: AdminRequest[] }>(
    useCallback(() => apiClient.adminRequests.list(tab === "all" ? undefined : tab), [tab]),
  );
  const requests = requestState.data?.requests || [];
  const tabs = [
    ["all", "All"],
    ["support", "Support"],
    ["sales", "Sales"],
    ["integration", "Integrations"],
    ["onboarding", "Onboarding"],
    ["bug", "Bugs"],
    ["upgrade", "Upgrade requests"],
  ];

  const update = async (request: AdminRequest, status: AdminRequest["status"]) => {
    await apiClient.adminRequests.update(request.id, { status });
    setSelected({ ...request, status });
    await requestState.refresh();
  };

  return (
    <Page title="Requests" subtitle="Track support, sales, onboarding, integrations, bugs, and upgrade requests.">
      <div className="flex flex-wrap gap-2">
        {tabs.map(([value, label]) => (
          <button key={value} type="button" onClick={() => setTab(value)} className="rounded-lg px-3 py-2 text-[12px] font-medium" style={{ background: tab === value ? GREEN : SURFACE, color: tab === value ? "white" : TEXT, border: `1px solid ${BORDER}` }}>{label}</button>
        ))}
      </div>
      <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
        <section className="rounded-lg overflow-hidden" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="grid grid-cols-[110px_90px_1fr_150px_120px_120px] gap-3 px-4 py-3 text-[11px] font-semibold uppercase" style={{ color: MUTED, borderBottom: `1px solid ${BORDER}` }}>
            <span>Type</span><span>Priority</span><span>Subject</span><span>Requester</span><span>Status</span><span>Created</span>
          </div>
          {requests.map((request) => (
            <button key={request.id} type="button" onClick={() => setSelected(request)} className="grid w-full grid-cols-[110px_90px_1fr_150px_120px_120px] gap-3 px-4 py-3 text-left text-[12px]" style={{ color: TEXT, borderBottom: `1px solid ${BORDER}` }}>
              <span>{request.type}</span>
              <span>{request.priority}</span>
              <span className="font-medium">{request.subject}</span>
              <span>{request.requester || request.company || "Customer"}</span>
              <span>{request.status.replaceAll("_", " ")}</span>
              <span>{request.created_at ? new Date(request.created_at).toLocaleDateString() : "Today"}</span>
            </button>
          ))}
          {!requests.length ? <div className="p-6 text-[13px]" style={{ color: MUTED }}>No requests in this view.</div> : null}
        </section>
        <Panel title="Request detail">
          {selected ? (
            <div className="space-y-3 text-[13px]">
              <Row label="Type" value={selected.type} />
              <Row label="Company" value={selected.company} />
              <Row label="Requester" value={selected.requester} />
              <Row label="Source" value={selected.source_page} />
              <p className="leading-relaxed" style={{ color: MUTED }}>{selected.message}</p>
              <div className="flex flex-wrap gap-2 pt-3">
                {(["triaged", "in_progress", "waiting_on_customer", "closed"] as const).map((status) => (
                  <PortalButton key={status} variant="secondary" onClick={() => update(selected, status)}>{status.replaceAll("_", " ")}</PortalButton>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-[13px]" style={{ color: MUTED }}>Select a request to review and update status.</p>
          )}
        </Panel>
      </div>
    </Page>
  );
}

export function WorkspaceSettingsPage() {
  const shellState = usePortalResource<ShellResponse>(useCallback(() => apiClient.product.shell(), []));
  return (
    <Page title="Workspace settings" subtitle="Manage the operating workspace that powers Command Center.">
      <Panel title="Workspace">
        <Row label="Name" value={shellState.data?.workspace?.name} />
        <Row label="Mode" value={shellState.data?.workspace?.mode === "live" ? "Live operations" : "Evaluation workspace"} />
        <Row label="Plan" value={shellState.data?.plan?.name} />
      </Panel>
    </Page>
  );
}

export function TeamPage() {
  const { entitlements } = useAuth();
  const membersState = usePortalResource<TeamMembersResponse>(useCallback(() => apiClient.team.members(), []));
  const invitationsState = usePortalResource<TeamInvitationsResponse>(useCallback(() => apiClient.team.invitations(), []), { enabled: Boolean(entitlements.can_invite_team) });
  const [modalOpen, setModalOpen] = useState(false);
  const [invite, setInvite] = useState<TeamInvitationPayload>({ email: "", role: "viewer" });
  const [message, setMessage] = useState("");
  const [upgradeOpen, setUpgradeOpen] = useState(false);

  const submitInvite = async () => {
    try {
      const response = await apiClient.team.invite(invite) as Record<string, unknown>;
      setMessage(String(response.message || "Invitation created."));
      setModalOpen(false);
      setInvite({ email: "", role: "viewer" });
      await invitationsState.refresh();
    } catch (error) {
      if (error instanceof Error && (error as { status?: number }).status === 402) {
        setUpgradeOpen(true);
        return;
      }
      setMessage(error instanceof Error ? error.message : "Invitation could not be created.");
    }
  };

  if (!entitlements.can_invite_team) {
    return (
      <Page title="Team" subtitle="Coordinate field teams, water risk, compliance evidence, and executive reporting.">
        {upgradeOpen ? <UpgradeModal title="Team invitations are available on the Team plan." body="Invite workflows, role controls, and shared team administration are included in Team." cta="Upgrade to Team" onClose={() => setUpgradeOpen(false)} onConfirm={() => window.location.assign("/pricing")} /> : null}
        <Panel title="Team feature locked">
          <div className="flex items-start gap-4 rounded-xl p-5" style={{ background: BG, border: `1px solid ${BORDER}` }}>
            <Users className="mt-1 h-5 w-5" style={{ color: GREEN }} />
            <div>
              <div className="text-[16px] font-semibold" style={{ color: TEXT }}>Team invitations are available on the Team plan.</div>
              <p className="mt-2 text-[13px] leading-6" style={{ color: MUTED }}>Upgrade to unlock member invites, role controls, and a shared evidence library for operators and managers.</p>
              <div className="mt-4">
                <PortalButton onClick={() => setUpgradeOpen(true)}>Upgrade to Team</PortalButton>
              </div>
            </div>
          </div>
        </Panel>
      </Page>
    );
  }

  return (
    <Page title="Team" subtitle="Invite members, manage collaboration, and keep workspace access aligned with your operating team.">
      {message ? <Banner tone="good" message={message} /> : null}
      <div className="grid gap-5 lg:grid-cols-[1fr_1fr]">
        <Panel title="Members" action={<PortalButton onClick={() => setModalOpen(true)}>Invite member</PortalButton>}>
          <div className="space-y-3">
            {(membersState.data?.members || []).map((member) => (
              <div key={member.id} className="rounded-xl px-4 py-3" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                <div className="font-semibold text-[13px]" style={{ color: TEXT }}>{safe(member.name, member.email)}</div>
                <div className="mt-1 text-[12px]" style={{ color: MUTED }}>{safe(member.email)} • {safe(member.role)}</div>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Pending invites">
          <div className="space-y-3">
            {(invitationsState.data?.invitations || []).map((invitation) => (
              <div key={invitation.id} className="rounded-xl px-4 py-3" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                <div className="font-semibold text-[13px]" style={{ color: TEXT }}>{invitation.email}</div>
                <div className="mt-1 text-[12px]" style={{ color: MUTED }}>{invitation.role} • {invitation.status}</div>
              </div>
            ))}
            {!invitationsState.data?.invitations?.length ? <div className="text-[13px]" style={{ color: MUTED }}>No pending invitations.</div> : null}
          </div>
        </Panel>
      </div>

      {modalOpen ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/35 px-4">
          <div className="w-full max-w-[420px] rounded-2xl p-6" style={{ background: "#FFFDF8", border: `1px solid ${BORDER}` }}>
            <div className="mb-4 text-[20px] font-semibold" style={{ color: TEXT }}>Invite team member</div>
            <label className="block text-[12px]" style={{ color: MUTED }}>
              Email
              <input value={invite.email} onChange={(event) => setInvite({ ...invite, email: event.target.value })} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
            </label>
            <label className="mt-4 block text-[12px]" style={{ color: MUTED }}>
              Role
              <select value={invite.role} onChange={(event) => setInvite({ ...invite, role: event.target.value as TeamInvitationPayload["role"] })} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                <option value="owner">Owner</option>
                <option value="admin">Admin</option>
                <option value="manager">Manager</option>
                <option value="operator">Operator</option>
                <option value="viewer">Viewer</option>
              </select>
            </label>
            <div className="mt-5 flex gap-3">
              <PortalButton onClick={submitInvite}>Send invite</PortalButton>
              <PortalButton variant="secondary" onClick={() => setModalOpen(false)}>Cancel</PortalButton>
            </div>
          </div>
        </div>
      ) : null}
    </Page>
  );
}

export function OnboardingPage() {
  const onboardingState = usePortalResource<Record<string, unknown>>(useCallback(() => apiClient.onboarding.state(), []));
  const [selectedPlan, setSelectedPlan] = useState("free");
  const [organizationType, setOrganizationType] = useState("Farm / grower");
  const [acresOrSites, setAcresOrSites] = useState("");
  const [primaryGoal, setPrimaryGoal] = useState("Water risk");
  const [message, setMessage] = useState("");

  const save = async () => {
    await apiClient.onboarding.update({
      current_step: "start_operating",
      selected_plan: selectedPlan,
      organization_type: organizationType,
      acres_or_sites: acresOrSites,
      primary_goal: primaryGoal,
      completed_steps: ["account", "organization", "scope", "plan"],
    });
    const response = await apiClient.onboarding.complete() as Record<string, unknown>;
    setMessage(safe(response.message));
    await onboardingState.refresh();
  };

  return (
    <Page title="Onboarding" subtitle="Turn agricultural evidence into decisions, reports, and operating clarity.">
      {message ? <Banner tone="good" message={message} /> : null}
      <Panel title="Workspace setup" action={<PortalButton onClick={save}>Start operating</PortalButton>}>
        <div className="grid gap-4 md:grid-cols-2">
          <InputField label="Organization type">
            <select value={organizationType} onChange={(event) => setOrganizationType(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
              <option>Farm / grower</option>
              <option>Water agency / district</option>
              <option>Advisor / consultant</option>
              <option>Agricultural network</option>
              <option>Other</option>
            </select>
          </InputField>
          <InputField label="Acres, sites, or farms managed">
            <input value={acresOrSites} onChange={(event) => setAcresOrSites(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
          </InputField>
          <InputField label="Primary operating goal">
            <select value={primaryGoal} onChange={(event) => setPrimaryGoal(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
              <option>Water risk</option>
              <option>Compliance reporting</option>
              <option>Evidence management</option>
              <option>Executive reporting</option>
            </select>
          </InputField>
          <InputField label="Plan">
            <select value={selectedPlan} onChange={(event) => setSelectedPlan(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
              <option value="free">Free</option>
              <option value="professional">Professional</option>
              <option value="team">Team</option>
              <option value="network">Network</option>
            </select>
          </InputField>
        </div>
      </Panel>
    </Page>
  );
}

function Banner({ tone, message }: { tone: "good" | "warn"; message: string }) {
  return (
    <div className="rounded-lg px-4 py-3 text-[13px]" style={{ background: tone === "good" ? "#F0FDF4" : "#FFFBEB", color: tone === "good" ? "#15803D" : "#92400E", border: tone === "good" ? "1px solid #BBF7D0" : "1px solid #FCD34D" }}>
      {message}
    </div>
  );
}

function FaqItem({ question, answer }: { question: string; answer: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl" style={{ border: `1px solid ${BORDER}`, background: BG }}>
      <button type="button" onClick={() => setOpen((value) => !value)} className="flex w-full items-center justify-between px-4 py-4 text-left">
        <span className="text-[14px] font-semibold" style={{ color: TEXT }}>{question}</span>
        {open ? <ChevronUp className="h-4 w-4" style={{ color: MUTED }} /> : <ChevronDown className="h-4 w-4" style={{ color: MUTED }} />}
      </button>
      {open ? <div className="px-4 pb-4 text-[13px] leading-6" style={{ color: MUTED }}>{answer}</div> : null}
    </div>
  );
}

function InputField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="text-[12px]" style={{ color: MUTED }}>
      {label}
      {children}
    </label>
  );
}
