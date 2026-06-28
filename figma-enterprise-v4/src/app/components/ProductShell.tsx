import { ReactNode, useCallback, useMemo, useState } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, GREEN, MUTED, PortalButton, SURFACE, TEXT } from "./portalUi";

type Plan = {
  id: "free" | "professional" | "network";
  name: string;
  public_price_monthly: string;
  public_price_annual: string;
  annual_savings_label?: string;
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

type SalesForm = {
  name: string;
  email: string;
  company: string;
  role: string;
  organization_type: string;
  acres_or_sites: string;
  main_goal: string;
  message: string;
  preferred_contact_method: string;
};

const faq = [
  ["What counts as a workspace?", "A workspace is the farm, site, district, or operating scope where AGRO-AI organizes field activity, evidence, connected systems, tasks, and reports."],
  ["Can I start free?", "Yes. Free is built for pilot use with limited uploads, limited AGRO-AI runs, basic field updates, and basic reports."],
  ["What is included in Professional?", "Professional includes the field operating loop, core WaterOps and assurance workflows, connector access, report previews, PDF exports, and support for commercial farms and advisors."],
  ["Who is Network for?", "Network is for multi-farm groups, water agencies, exporters, lenders, insurers, and enterprise buyers that need role controls, APIs, scaled reporting, and rollout support."],
  ["Do you support annual billing?", "Yes. Professional can be paid monthly or annually. Annual Professional pricing is designed to save roughly 17%. Network plans are scoped with the AGRO-AI team."],
  ["Can AGRO-AI connect to existing field systems?", "Yes. AGRO-AI is designed to connect files, email, cloud drives, controller exports, ET/weather sources, and custom provider APIs."],
  ["Do you support WiseConn, Talgil, OpenET, Google Drive, Outlook, Gmail, Dropbox, Slack, and Salesforce?", "The connector layer is built for these systems. Some live syncs require customer-approved credentials or provider access before production use."],
  ["Can AGRO-AI generate reports and PDFs?", "Yes. AGRO-AI can generate structured report previews and PDF exports from the available evidence context."],
  ["Is my data used to train models?", "Customer evidence powers your workspace experience. AGRO-AI should not treat private field records as public training data."],
  ["How does AGRO-AI handle customer evidence?", "Evidence is organized inside your workspace, connected to fields, tasks, reports, and decisions, and used to support operational recommendations."],
  ["Can water agencies or grower networks use AGRO-AI?", "Yes. Network is designed for multi-farm oversight, compliance workflows, supplier evidence, dashboards, and operating reports."],
  ["Can I request a custom integration?", "Yes. Use Support or Contact Sales to request a custom integration. AGRO-AI stores the request and routes it for follow-up."],
  ["What happens if I need onboarding help?", "You can request onboarding from the Support or Onboarding page. The request is stored in your workspace and visible to AGRO-AI admins."],
  ["How secure is my data?", "AGRO-AI uses workspace-scoped access and keeps technical setup details out of normal user screens. Enterprise security controls can be added for Network customers."],
  ["Can I cancel or change plans?", "Free can continue as a pilot. Professional and Network changes are handled through billing or the AGRO-AI team until payment automation is fully configured."],
];

function safe(value: unknown, fallback = "Not available") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function Page({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-8" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <h1 className="text-[32px] font-semibold tracking-tight" style={{ color: TEXT }}>{title}</h1>
        {subtitle ? <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>{subtitle}</p> : null}
      </header>
      <main className="px-8 py-7 space-y-6" style={{ maxWidth: 1220 }}>{children}</main>
    </div>
  );
}

function Panel({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-2xl p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="flex items-center justify-between gap-4 mb-5">
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

function Field({ label, value, onChange, type = "text", placeholder }: { label: string; value: string; onChange: (value: string) => void; type?: string; placeholder?: string }) {
  return (
    <label className="block text-[12px] font-medium" style={{ color: MUTED }}>
      {label}
      <input value={value} type={type} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="mt-1 h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
    </label>
  );
}

function SelectField({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: string[] }) {
  return (
    <label className="block text-[12px] font-medium" style={{ color: MUTED }}>
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function ContactSalesForm({ defaultGoal = "Water risk" }: { defaultGoal?: string }) {
  const [form, setForm] = useState<SalesForm>({ name: "", email: "", company: "", role: "", organization_type: "Farm / grower", acres_or_sites: "", main_goal: defaultGoal, message: "", preferred_contact_method: "Email" });
  const [status, setStatus] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const update = (key: keyof SalesForm, value: string) => setForm((current) => ({ ...current, [key]: value }));

  const submit = async () => {
    setSubmitting(true);
    setStatus("");
    try {
      const response = await apiClient.request<Record<string, unknown>>("/v1/sales/contact", { method: "POST", body: JSON.stringify(form) });
      setStatus(safe(response.message, "Thanks — your request was received."));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not submit request.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      {status ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: "#F0FDF4", border: "1px solid #BBF7D0", color: "#15803D" }}>{status}</div> : null}
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Name" value={form.name} onChange={(value) => update("name", value)} />
        <Field label="Work email" value={form.email} onChange={(value) => update("email", value)} type="email" />
        <Field label="Company" value={form.company} onChange={(value) => update("company", value)} />
        <Field label="Role" value={form.role} onChange={(value) => update("role", value)} />
        <SelectField label="Organization type" value={form.organization_type} onChange={(value) => update("organization_type", value)} options={["Farm / grower", "Farmland manager", "Water agency / district", "Lender / insurer", "Food / sustainability buyer", "Advisor / consultant", "Other"]} />
        <Field label="Acres / farms / sites managed" value={form.acres_or_sites} onChange={(value) => update("acres_or_sites", value)} />
        <SelectField label="Main goal" value={form.main_goal} onChange={(value) => update("main_goal", value)} options={["Water risk", "Compliance reporting", "Field operations", "Evidence organization", "Integrations", "Network rollout"]} />
        <SelectField label="Preferred contact" value={form.preferred_contact_method} onChange={(value) => update("preferred_contact_method", value)} options={["Email", "Phone", "LinkedIn", "Video call"]} />
      </div>
      <textarea value={form.message} onChange={(event) => update("message", event.target.value)} placeholder="Tell us what you want AGRO-AI to help you run." className="min-h-[120px] w-full rounded-xl px-3 py-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
      <PortalButton disabled={submitting || !form.name || !form.email || !form.company || !form.message} onClick={submit}>{submitting ? "Sending…" : "Contact sales"}</PortalButton>
    </div>
  );
}

function PlanCard({ plan, billingPeriod, onSelect }: { plan: Plan; billingPeriod: "monthly" | "annual"; onSelect: (plan: Plan) => void }) {
  const price = billingPeriod === "annual" ? plan.public_price_annual : plan.public_price_monthly;
  return (
    <section className="rounded-2xl p-6 flex flex-col min-h-[470px]" style={{ background: SURFACE, border: `1px solid ${plan.id === "professional" ? GREEN : BORDER}` }}>
      <div>
        <h2 className="text-[24px] font-semibold tracking-tight" style={{ color: TEXT }}>{plan.name}</h2>
        <p className="mt-2 text-[13px] leading-relaxed min-h-[56px]" style={{ color: MUTED }}>{plan.recommended_buyer}</p>
      </div>
      <div className="mt-6">
        <div className="text-[36px] font-semibold tracking-tight" style={{ color: TEXT }}>{price}</div>
        {plan.annual_savings_label ? <div className="mt-1 text-[12px] font-medium" style={{ color: GREEN }}>{plan.annual_savings_label}</div> : null}
      </div>
      <button type="button" onClick={() => onSelect(plan)} className="mt-6 h-11 w-full rounded-full text-[13px] font-semibold" style={{ background: "#050505", color: "white" }}>{plan.cta_label}</button>
      <div className="mt-6 border-t pt-5 space-y-3" style={{ borderColor: BORDER }}>
        {plan.features.map((feature) => <div key={feature} className="text-[13px] leading-relaxed" style={{ color: TEXT }}>✓ {feature}</div>)}
      </div>
      <div className="mt-auto pt-5 space-y-2 text-[12px]" style={{ color: MUTED }}>
        {Object.values(plan.included_limits).map((limit) => <div key={limit}>{limit}</div>)}
      </div>
    </section>
  );
}

function FAQAccordion() {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <Panel title="FAQ">
      <div className="divide-y" style={{ borderColor: BORDER }}>
        {faq.map(([question, answer], index) => (
          <div key={question} className="py-4">
            <button type="button" onClick={() => setOpen(open === index ? null : index)} className="flex w-full items-center justify-between gap-4 text-left">
              <span className="text-[15px] font-semibold" style={{ color: TEXT }}>{question}</span>
              <span className="text-[22px]" style={{ color: MUTED }}>{open === index ? "−" : "+"}</span>
            </button>
            {open === index ? <p className="mt-2 max-w-3xl text-[13px] leading-relaxed" style={{ color: MUTED }}>{answer}</p> : null}
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function PricingPage() {
  const plansState = usePortalResource<ProductPlans>(useCallback(() => apiClient.product.plans(), []));
  const [billingPeriod, setBillingPeriod] = useState<"monthly" | "annual">("monthly");
  const [message, setMessage] = useState("");
  const [showSales, setShowSales] = useState(false);

  const selectPlan = async (plan: Plan) => {
    setMessage("");
    if (plan.id === "network") {
      setShowSales(true);
      return;
    }
    try {
      const response = await apiClient.billing.checkout({ plan_id: plan.id, billing_period: billingPeriod }) as Record<string, unknown>;
      setMessage(safe(response.message, "Upgrade request received."));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upgrade request received.");
    }
  };

  return (
    <Page title="Pricing" subtitle="Choose how much of the field operating room you want AGRO-AI to run for you.">
      <div className="flex items-center justify-between gap-4">
        <div className="inline-flex rounded-full p-1" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          {(["monthly", "annual"] as const).map((period) => (
            <button key={period} type="button" onClick={() => setBillingPeriod(period)} className="px-5 py-2 rounded-full text-[13px] font-medium capitalize" style={{ background: billingPeriod === period ? "#050505" : "transparent", color: billingPeriod === period ? "white" : TEXT }}>
              {period === "annual" ? "Annual · save 17%" : "Monthly"}
            </button>
          ))}
        </div>
      </div>
      {message ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: "#F0FDF4", color: "#15803D", border: "1px solid #BBF7D0" }}>{message}</div> : null}
      <div className="grid gap-6 lg:grid-cols-3">{(plansState.data?.plans || []).map((plan) => <PlanCard key={plan.id} plan={plan} billingPeriod={billingPeriod} onSelect={selectPlan} />)}</div>
      {showSales ? <Panel title="Contact sales"><ContactSalesForm defaultGoal="Network rollout" /></Panel> : null}
      <Panel title="Implementation services">
        <div className="grid gap-4 md:grid-cols-3">{(plansState.data?.service_add_ons || []).map((service) => <div key={service.id} className="rounded-xl p-5" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="font-semibold text-[14px]" style={{ color: TEXT }}>{service.name}</div><div className="mt-2 text-[13px] font-medium" style={{ color: GREEN }}>{service.price}</div><p className="mt-2 text-[12px] leading-relaxed" style={{ color: MUTED }}>{service.description}</p></div>)}</div>
      </Panel>
      <FAQAccordion />
    </Page>
  );
}

export function ProfilePage() {
  const profileState = usePortalResource<Record<string, unknown>>(useCallback(() => apiClient.account.profile(), []));
  const profile = profileState.data || {};
  const user = (profile.user || {}) as Record<string, unknown>;
  const workspace = (profile.workspace || {}) as Record<string, unknown>;
  const plan = (profile.plan || {}) as Record<string, unknown>;
  return <Page title="Profile" subtitle="Your account, workspace, and plan."><Panel title="Account"><Row label="Name" value={user.name} /><Row label="Email" value={user.email} /><Row label="Role" value={profile.role} /><Row label="Workspace" value={workspace.name} /><Row label="Plan" value={plan.name} /><Row label="Account status" value={profile.account_status} /></Panel></Page>;
}

export function BillingPage() {
  const billingState = usePortalResource<BillingSummary>(useCallback(() => apiClient.billing.summary(), []));
  const [billingPeriod, setBillingPeriod] = useState<"monthly" | "annual">("monthly");
  const [message, setMessage] = useState("");
  const billing = billingState.data;
  const usage = billing?.usage_summary || {};
  const upgrade = async (plan: Plan) => {
    const response = await apiClient.billing.checkout({ plan_id: plan.id, billing_period: billingPeriod }) as Record<string, unknown>;
    setMessage(safe(response.message, "Request received."));
  };
  return (
    <Page title="Billing" subtitle="Manage plan, usage, upgrades, and implementation services.">
      {message ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: "#F0FDF4", color: "#15803D", border: "1px solid #BBF7D0" }}>{message}</div> : null}
      <div className="grid gap-5 lg:grid-cols-2"><Panel title="Current plan"><Row label="Plan" value={billing?.current_plan?.name} /><Row label="Status" value={billing?.billing_status} /><Row label="Monthly price" value={billing?.monthly_price} /><Row label="Annual price" value={billing?.annual_price} /></Panel><Panel title="Usage summary"><Row label="Uploads" value={usage.uploads} /><Row label="AGRO-AI runs" value={usage.ai_runs} /><Row label="Reports" value={usage.reports} /><Row label="Field updates" value={usage.field_updates} /></Panel></div>
      <Panel title="Upgrade options" action={<div className="inline-flex rounded-full p-1" style={{ background: BG, border: `1px solid ${BORDER}` }}>{(["monthly", "annual"] as const).map((period) => <button key={period} type="button" onClick={() => setBillingPeriod(period)} className="px-3 py-1.5 rounded-full text-[12px] font-medium capitalize" style={{ background: billingPeriod === period ? GREEN : "transparent", color: billingPeriod === period ? "white" : TEXT }}>{period === "annual" ? "Annual · save 17%" : "Monthly"}</button>)}</div>}>
        <div className="grid gap-4 md:grid-cols-2">{(billing?.upgrade_options || []).map((plan) => <div key={plan.id} className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="font-semibold" style={{ color: TEXT }}>{plan.name}</div><div className="mt-1 text-[13px]" style={{ color: MUTED }}>{billingPeriod === "annual" ? plan.public_price_annual : plan.public_price_monthly}</div><PortalButton onClick={() => upgrade(plan)}>{plan.cta_label}</PortalButton></div>)}</div>
      </Panel>
    </Page>
  );
}

export function SecurityPage() {
  const securityState = usePortalResource<Record<string, unknown>>(useCallback(() => apiClient.account.security(), []));
  const [message, setMessage] = useState("");
  const security = securityState.data || {};
  const requestVerification = async () => setMessage(safe((await apiClient.account.requestEmailVerification() as Record<string, unknown>).message, "Verification request received."));
  const startTwoFactor = async () => setMessage(safe((await apiClient.account.startTwoFactor() as Record<string, unknown>).message, "Two-factor setup request received."));
  return <Page title="Security" subtitle="Keep account access ready for production operations.">{message ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: "#F0FDF4", color: "#15803D", border: "1px solid #BBF7D0" }}>{message}</div> : null}<Panel title="Verification"><Row label="Email verification" value={security.email_verified ? "Verified" : "Not verified"} /><Row label="Two-factor verification" value={security.two_factor_enabled ? "Enabled" : "Not enabled"} /><div className="flex gap-3 pt-4"><PortalButton onClick={requestVerification}>Send verification email</PortalButton><PortalButton variant="secondary" onClick={startTwoFactor}>Set up 2FA</PortalButton></div></Panel><Panel title="Sessions"><Row label="Login methods" value={Array.isArray(security.login_methods) ? security.login_methods.join(", ") : "password"} /><Row label="Active sessions" value={Array.isArray(security.active_sessions) && security.active_sessions.length ? security.active_sessions.length : "Current session"} /></Panel></Page>;
}

export function SupportPage() {
  const supportState = usePortalResource<Record<string, unknown>>(useCallback(() => apiClient.support.options(), []));
  const { currentWorkspace } = useAuth();
  const [category, setCategory] = useState<"support" | "integration" | "issue" | "bug" | "onboarding" | "sales" | "network_plan">("support");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState("");
  const options = ((supportState.data?.options || []) as { id: string; label: string; type: string }[]);
  const submit = async () => {
    const response = await apiClient.request<Record<string, unknown>>("/v1/support/ticket", { method: "POST", body: JSON.stringify({ category, subject, message, workspace_id: currentWorkspace?.id, source_page: "support" }) });
    setResult(safe(response.message, "Thanks — your request was received."));
    setSubject("");
    setMessage("");
  };
  return (
    <Page title="Support" subtitle="Contact support, request integrations, report issues, book onboarding, or plan a Network rollout.">
      {result ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: "#F0FDF4", color: "#15803D", border: "1px solid #BBF7D0" }}>{result}</div> : null}
      <div className="grid gap-6 lg:grid-cols-[0.8fr_1.2fr]">
        <Panel title="How can we help?">
          <div className="space-y-3">{options.map((option) => <button key={option.id} type="button" onClick={() => setCategory(option.type as typeof category)} className="w-full rounded-xl p-4 text-left" style={{ background: category === option.type ? "#EAF6EF" : BG, border: `1px solid ${BORDER}` }}><div className="font-semibold text-[13px]" style={{ color: TEXT }}>{option.label}</div><div className="mt-1 text-[12px]" style={{ color: MUTED }}>{option.type === "sales" ? "Talk to AGRO-AI about scope and pricing" : "Create a workspace request"}</div></button>)}</div>
        </Panel>
        <Panel title={category === "sales" || category === "network_plan" ? "Contact sales" : "Create request"}>{category === "sales" || category === "network_plan" ? <ContactSalesForm defaultGoal="Network rollout" /> : <div className="space-y-3"><select value={category} onChange={(event) => setCategory(event.target.value as typeof category)} className="w-full rounded-xl px-3 py-2 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}><option value="support">Contact support</option><option value="integration">Request integration</option><option value="bug">Report issue</option><option value="onboarding">Book onboarding</option><option value="sales">Contact sales</option></select><input value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="Subject" className="w-full rounded-xl px-3 py-2 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} /><textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="What do you need?" className="min-h-[150px] w-full rounded-xl px-3 py-2 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} /><PortalButton disabled={!subject.trim() || !message.trim()} onClick={submit}>Send request</PortalButton></div>}</Panel>
      </div>
    </Page>
  );
}

export function WorkspaceSettingsPage() {
  const shellState = usePortalResource<ShellResponse>(useCallback(() => apiClient.product.shell(), []));
  return <Page title="Workspace settings" subtitle="Manage the operating workspace that powers Command Center."><Panel title="Workspace"><Row label="Name" value={shellState.data?.workspace?.name} /><Row label="Mode" value={shellState.data?.workspace?.mode === "live" ? "Live operations" : "Evaluation workspace"} /><Row label="Plan" value={shellState.data?.plan?.name} /></Panel></Page>;
}

export function TeamPage() {
  const shellState = usePortalResource<ShellResponse>(useCallback(() => apiClient.product.shell(), []));
  return <Page title="Team" subtitle="Invite and role controls are prepared for workspace collaboration."><Panel title="Current user"><Row label="Name" value={shellState.data?.user?.name} /><Row label="Email" value={shellState.data?.user?.email} /><Row label="Workspace" value={shellState.data?.workspace?.name} /></Panel><Panel title="Role controls"><p className="text-[13px] leading-relaxed" style={{ color: MUTED }}>Team invitations and role administration are ready for workspace collaboration setup. Current access remains scoped to authenticated workspace members.</p></Panel></Page>;
}

export function OnboardingPage() {
  const [goal, setGoal] = useState("Manage water risk");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState("");
  const goals = useMemo(() => ["Manage water risk", "Generate compliance packet", "Organize field evidence", "Track operator tasks", "Connect field systems", "Prepare owner/lender report"], []);
  const requestOnboarding = async () => {
    const response = await apiClient.request<Record<string, unknown>>("/v1/onboarding/request", { method: "POST", body: JSON.stringify({ goal, message }) });
    setResult(safe(response.message, "Onboarding request received."));
  };
  return <Page title="Onboarding" subtitle="A short path from account setup to Command Center.">{result ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: "#F0FDF4", color: "#15803D", border: "1px solid #BBF7D0" }}>{result}</div> : null}<div className="grid gap-4 md:grid-cols-5">{["Create workspace", "Choose role", "Choose first goal", "Add first source", "Open Command Center"].map((step, index) => <div key={step} className="rounded-xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="text-[11px] font-semibold" style={{ color: GREEN }}>Step {index + 1}</div><div className="mt-2 font-semibold text-[14px]" style={{ color: TEXT }}>{step}</div></div>)}</div><Panel title="First goal"><div className="grid gap-3 md:grid-cols-3">{goals.map((item) => <button key={item} type="button" onClick={() => setGoal(item)} className="rounded-xl px-4 py-3 text-left text-[13px]" style={{ background: goal === item ? "#EAF6EF" : BG, border: `1px solid ${BORDER}`, color: TEXT }}>{item}</button>)}</div><textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Tell us what you need help setting up." className="mt-4 min-h-[110px] w-full rounded-xl px-3 py-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} /><div className="mt-4"><PortalButton onClick={requestOnboarding}>Request onboarding help</PortalButton></div></Panel></Page>;
}
