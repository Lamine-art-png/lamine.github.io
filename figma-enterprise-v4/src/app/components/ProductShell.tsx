import { ReactNode, useCallback, useMemo, useState } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, GREEN, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type Plan = {
  id: "free" | "professional" | "network";
  name: string;
  public_price_monthly: string;
  public_price_annual: string;
  recommended_buyer: string;
  included_limits: Record<string, string>;
  features: string[];
  support_level: string;
  cta_label: string;
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
  payment_provider_configured: boolean;
};

type ShellResponse = {
  user?: { name?: string; email?: string };
  workspace?: { name?: string; mode?: string };
  plan?: Plan;
  support?: { options?: { id: string; label: string; type: string }[] };
};

const faq = [
  ["What counts as a workspace?", "A workspace is the farm, site, or operating scope where AGRO-AI organizes field activity, evidence, reports, and connected systems."],
  ["Can I start free?", "Yes. Free is built for pilot use with limited uploads, limited AGRO-AI runs, basic field updates, and basic reports."],
  ["Do you support annual billing?", "Yes. Professional is available monthly or annually. Network is scoped annually or monthly with the AGRO-AI team."],
  ["Do you support water agencies and grower networks?", "Yes. Network is designed for multi-farm dashboards, supplier workflows, role controls, APIs, and customer success."],
  ["Can AGRO-AI connect to existing field systems?", "Yes. Connector access is included on paid plans, with custom integrations available when systems need special handling."],
  ["Is my data used to train models?", "Customer evidence is used to power your workspace experience. AGRO-AI should not treat your private field records as public training data."],
  ["How do integrations work?", "Connected systems bring files, emails, controller data, or evidence into the workspace so the field operating loop can act on it."],
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
      <main className="px-8 py-6 space-y-5" style={{ maxWidth: 1180 }}>{children}</main>
    </div>
  );
}

function Panel({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-lg p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="flex items-center justify-between gap-4 mb-4">
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
      <span className="font-medium text-right" style={{ color: TEXT }}>{safe(value)}</span>
    </div>
  );
}

function PlanCard({ plan, billingPeriod, onSelect }: { plan: Plan; billingPeriod: "monthly" | "annual"; onSelect: (plan: Plan) => void }) {
  const price = billingPeriod === "annual" ? plan.public_price_annual : plan.public_price_monthly;
  return (
    <section className="rounded-lg p-6 flex flex-col min-h-[420px]" style={{ background: SURFACE, border: `1px solid ${plan.id === "professional" ? GREEN : BORDER}` }}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-[22px] font-semibold" style={{ color: TEXT }}>{plan.name}</h2>
          <p className="mt-2 text-[13px] leading-relaxed" style={{ color: MUTED }}>{plan.recommended_buyer}</p>
        </div>
        {plan.id === "professional" ? <StatusBadge label="Popular" tone="good" /> : null}
      </div>
      <div className="mt-6 text-[30px] font-semibold" style={{ color: TEXT }}>{price}</div>
      <div className="mt-5 space-y-2">
        {plan.features.map((feature) => (
          <div key={feature} className="text-[13px] leading-relaxed" style={{ color: TEXT }}>- {feature}</div>
        ))}
      </div>
      <div className="mt-5 space-y-2 text-[12px]" style={{ color: MUTED }}>
        {Object.values(plan.included_limits).map((limit) => <div key={limit}>{limit}</div>)}
      </div>
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
      const response = await apiClient.billing.checkout({ plan_id: plan.id, billing_period: billingPeriod }) as Record<string, unknown>;
      setMessage(safe(response.message, "Upgrade flow is ready."));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upgrade flow is ready. Live billing setup is required before checkout.");
    }
  };

  return (
    <Page title="Pricing" subtitle="Choose the AGRO-AI plan that matches the operating room you need to run.">
      <div className="inline-flex rounded-lg p-1" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
        {(["monthly", "annual"] as const).map((period) => (
          <button
            key={period}
            type="button"
            onClick={() => setBillingPeriod(period)}
            className="px-4 py-2 rounded-md text-[13px] font-medium capitalize"
            style={{ background: billingPeriod === period ? GREEN : "transparent", color: billingPeriod === period ? "white" : TEXT }}
          >
            {period}
          </button>
        ))}
      </div>

      {message ? <div className="rounded-lg px-4 py-3 text-[13px]" style={{ background: "#FFFBEB", color: "#92400E", border: "1px solid #FCD34D" }}>{message}</div> : null}

      <div className="grid gap-5 lg:grid-cols-3">
        {(plansState.data?.plans || []).map((plan) => (
          <PlanCard key={plan.id} plan={plan} billingPeriod={billingPeriod} onSelect={selectPlan} />
        ))}
      </div>

      <Panel title="Services">
        <div className="grid gap-4 md:grid-cols-3">
          {(plansState.data?.service_add_ons || []).map((service) => (
            <div key={service.id} className="rounded-lg p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
              <div className="font-semibold text-[14px]" style={{ color: TEXT }}>{service.name}</div>
              <div className="mt-2 text-[13px] font-medium" style={{ color: GREEN }}>{service.price}</div>
              <p className="mt-2 text-[12px] leading-relaxed" style={{ color: MUTED }}>{service.description}</p>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="FAQ">
        <div className="grid gap-4 md:grid-cols-2">
          {faq.map(([question, answer]) => (
            <div key={question}>
              <div className="font-semibold text-[13px]" style={{ color: TEXT }}>{question}</div>
              <p className="mt-1 text-[12px] leading-relaxed" style={{ color: MUTED }}>{answer}</p>
            </div>
          ))}
        </div>
      </Panel>
    </Page>
  );
}

export function ProfilePage() {
  const profileState = usePortalResource<Record<string, unknown>>(useCallback(() => apiClient.account.profile(), []));
  const profile = profileState.data || {};
  const user = (profile.user || {}) as Record<string, unknown>;
  const workspace = (profile.workspace || {}) as Record<string, unknown>;
  const plan = (profile.plan || {}) as Record<string, unknown>;
  return (
    <Page title="Profile" subtitle="Your account, workspace, and plan at a glance.">
      <Panel title="Account">
        <Row label="Name" value={user.name} />
        <Row label="Email" value={user.email} />
        <Row label="Role" value={profile.role} />
        <Row label="Workspace" value={workspace.name} />
        <Row label="Plan" value={plan.name} />
        <Row label="Account status" value={profile.account_status} />
      </Panel>
    </Page>
  );
}

export function BillingPage() {
  const billingState = usePortalResource<BillingSummary>(useCallback(() => apiClient.billing.summary(), []));
  const [billingPeriod, setBillingPeriod] = useState<"monthly" | "annual">("monthly");
  const [message, setMessage] = useState("");
  const billing = billingState.data;
  const usage = billing?.usage_summary || {};

  const upgrade = async (plan: Plan) => {
    const response = await apiClient.billing.checkout({ plan_id: plan.id, billing_period: billingPeriod }) as Record<string, unknown>;
    setMessage(safe(response.message));
  };

  return (
    <Page title="Billing" subtitle="Manage plan, usage, upgrades, and services.">
      {message ? <div className="rounded-lg px-4 py-3 text-[13px]" style={{ background: "#FFFBEB", color: "#92400E", border: "1px solid #FCD34D" }}>{message}</div> : null}
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Current plan">
          <Row label="Plan" value={billing?.current_plan?.name} />
          <Row label="Status" value={billing?.billing_status} />
          <Row label="Monthly price" value={billing?.monthly_price} />
          <Row label="Annual price" value={billing?.annual_price} />
          <Row label="Live billing" value={billing?.payment_provider_configured ? "Configured" : "Setup required"} />
        </Panel>
        <Panel title="Usage summary">
          <Row label="Uploads" value={usage.uploads} />
          <Row label="AGRO-AI runs" value={usage.ai_runs} />
          <Row label="Reports" value={usage.reports} />
          <Row label="Field updates" value={usage.field_updates} />
        </Panel>
      </div>
      <Panel title="Upgrade options" action={
        <div className="inline-flex rounded-lg p-1" style={{ background: BG, border: `1px solid ${BORDER}` }}>
          {(["monthly", "annual"] as const).map((period) => (
            <button key={period} type="button" onClick={() => setBillingPeriod(period)} className="px-3 py-1.5 rounded-md text-[12px] font-medium capitalize" style={{ background: billingPeriod === period ? GREEN : "transparent", color: billingPeriod === period ? "white" : TEXT }}>{period}</button>
          ))}
        </div>
      }>
        <div className="grid gap-4 md:grid-cols-2">
          {(billing?.upgrade_options || []).map((plan) => (
            <div key={plan.id} className="rounded-lg p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
              <div className="font-semibold" style={{ color: TEXT }}>{plan.name}</div>
              <div className="mt-1 text-[13px]" style={{ color: MUTED }}>{billingPeriod === "annual" ? plan.public_price_annual : plan.public_price_monthly}</div>
              <PortalButton onClick={() => upgrade(plan)}>{plan.cta_label}</PortalButton>
            </div>
          ))}
        </div>
      </Panel>
    </Page>
  );
}

export function SecurityPage() {
  const securityState = usePortalResource<Record<string, unknown>>(useCallback(() => apiClient.account.security(), []));
  const [message, setMessage] = useState("");
  const security = securityState.data || {};

  const requestVerification = async () => {
    const response = await apiClient.account.requestEmailVerification() as Record<string, unknown>;
    setMessage(safe(response.message));
  };
  const startTwoFactor = async () => {
    const response = await apiClient.account.startTwoFactor() as Record<string, unknown>;
    setMessage(safe(response.message));
  };

  return (
    <Page title="Security" subtitle="Keep account access ready for production operations.">
      {message ? <div className="rounded-lg px-4 py-3 text-[13px]" style={{ background: "#FFFBEB", color: "#92400E", border: "1px solid #FCD34D" }}>{message}</div> : null}
      <Panel title="Verification">
        <Row label="Email verification" value={security.email_verified ? "Verified" : "Not verified"} />
        <Row label="Two-factor verification" value={security.two_factor_enabled ? "Enabled" : "Not enabled"} />
        <div className="flex gap-3 pt-4">
          <PortalButton onClick={requestVerification}>Send verification email</PortalButton>
          <PortalButton variant="secondary" onClick={startTwoFactor}>Set up 2FA</PortalButton>
        </div>
      </Panel>
      <Panel title="Sessions">
        <Row label="Login methods" value={Array.isArray(security.login_methods) ? security.login_methods.join(", ") : "password"} />
        <Row label="Active sessions" value={Array.isArray(security.active_sessions) && security.active_sessions.length ? security.active_sessions.length : "Session table not configured"} />
      </Panel>
    </Page>
  );
}

export function SupportPage() {
  const supportState = usePortalResource<Record<string, unknown>>(useCallback(() => apiClient.support.options(), []));
  const { currentWorkspace } = useAuth();
  const [category, setCategory] = useState<"support" | "integration" | "issue" | "onboarding" | "sales">("support");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState("");
  const options = ((supportState.data?.options || []) as { id: string; label: string; type: string }[]);

  const submit = async () => {
    const response = await apiClient.support.ticket({ category, subject, message, workspace_id: currentWorkspace?.id }) as Record<string, unknown>;
    setResult(safe(response.message));
    setSubject("");
    setMessage("");
  };

  return (
    <Page title="Support" subtitle="Get help, request integrations, report issues, or plan a Network rollout.">
      {result ? <div className="rounded-lg px-4 py-3 text-[13px]" style={{ background: "#F0FDF4", color: "#15803D", border: "1px solid #BBF7D0" }}>{result}</div> : null}
      <div className="grid gap-5 lg:grid-cols-[1fr_1.2fr]">
        <Panel title="Options">
          <div className="space-y-3">
            {options.map((option) => (
              <button key={option.id} type="button" onClick={() => setCategory(option.type as typeof category)} className="w-full rounded-lg p-4 text-left" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                <div className="font-semibold text-[13px]" style={{ color: TEXT }}>{option.label}</div>
                <div className="mt-1 text-[12px]" style={{ color: MUTED }}>{option.type}</div>
              </button>
            ))}
          </div>
        </Panel>
        <Panel title="Create request">
          <div className="space-y-3">
            <select value={category} onChange={(event) => setCategory(event.target.value as typeof category)} className="w-full rounded-lg px-3 py-2 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
              <option value="support">Contact support</option>
              <option value="integration">Request integration</option>
              <option value="issue">Report issue</option>
              <option value="onboarding">Book onboarding call</option>
              <option value="sales">Contact sales for Network</option>
            </select>
            <input value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="Subject" className="w-full rounded-lg px-3 py-2 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
            <textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="What do you need?" className="min-h-[140px] w-full rounded-lg px-3 py-2 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
            <PortalButton disabled={!subject.trim() || !message.trim()} onClick={submit}>Send request</PortalButton>
          </div>
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
  const shellState = usePortalResource<ShellResponse>(useCallback(() => apiClient.product.shell(), []));
  return (
    <Page title="Team" subtitle="Invite and role controls are prepared for workspace collaboration.">
      <Panel title="Current user">
        <Row label="Name" value={shellState.data?.user?.name} />
        <Row label="Email" value={shellState.data?.user?.email} />
        <Row label="Workspace" value={shellState.data?.workspace?.name} />
      </Panel>
      <Panel title="Role controls">
        <p className="text-[13px] leading-relaxed" style={{ color: MUTED }}>
          Team invitations and role administration are ready for workspace collaboration setup. Current access remains scoped to authenticated workspace members.
        </p>
      </Panel>
    </Page>
  );
}

export function OnboardingPage() {
  const goals = useMemo(() => [
    "Manage water risk",
    "Generate compliance packet",
    "Organize field evidence",
    "Track operator tasks",
    "Connect field systems",
    "Prepare owner/lender report",
  ], []);
  return (
    <Page title="Onboarding" subtitle="A short path from account setup to Command Center.">
      <div className="grid gap-4 md:grid-cols-5">
        {["Create workspace", "Choose role", "Choose first goal", "Add first source", "Open Command Center"].map((step, index) => (
          <div key={step} className="rounded-lg p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="text-[11px] font-semibold" style={{ color: GREEN }}>Step {index + 1}</div>
            <div className="mt-2 font-semibold text-[14px]" style={{ color: TEXT }}>{step}</div>
          </div>
        ))}
      </div>
      <Panel title="First goals">
        <div className="grid gap-3 md:grid-cols-3">
          {goals.map((goal) => <div key={goal} className="rounded-lg px-4 py-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>{goal}</div>)}
        </div>
      </Panel>
    </Page>
  );
}
