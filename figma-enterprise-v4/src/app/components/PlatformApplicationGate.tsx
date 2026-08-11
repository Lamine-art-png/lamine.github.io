import {
  ArrowRight,
  Building2,
  Check,
  Code2,
  ExternalLink,
  FileCheck2,
  Loader2,
  LockKeyhole,
  RefreshCw,
  Send,
  ShieldCheck,
} from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";

type Row = Record<string, any>;
type Application = {
  id: string;
  status: string;
  requested_environment?: string;
  submitted_at?: string;
  created_at?: string;
  decision_reason?: string;
};
type FormState = {
  website: string;
  company: string;
  product: string;
  useCase: string;
  users: string;
  operations: string;
  monthlyVolume: string;
  dataVolume: string;
  providers: string;
  geography: string;
  securityContact: string;
  technicalContact: string;
  support: string;
};

const TERMINAL_STATUSES = new Set(["rejected", "withdrawn", "expired"]);
const emptyForm: FormState = {
  website: "",
  company: "",
  product: "",
  useCase: "",
  users: "",
  operations: "fields.read, observations.read, recommendations.create",
  monthlyVolume: "",
  dataVolume: "",
  providers: "",
  geography: "",
  securityContact: "",
  technicalContact: "",
  support: "documentation",
};
const inputClass =
  "h-11 w-full rounded-xl border border-[#D3DBD1] bg-white px-3 text-[13px] text-[#10231B] outline-none transition placeholder:text-[#98A39C] focus:border-[#6C987A] focus:ring-4 focus:ring-[#DCEADB]";
const textareaClass =
  "min-h-[108px] w-full resize-y rounded-xl border border-[#D3DBD1] bg-white px-3 py-3 text-[13px] leading-6 text-[#10231B] outline-none transition placeholder:text-[#98A39C] focus:border-[#6C987A] focus:ring-4 focus:ring-[#DCEADB]";

function object(value: unknown): Row {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Row) : {};
}
function values(value: string) {
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}
function date(value?: string) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}
function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-2 block text-[10px] font-bold uppercase tracking-[0.13em] text-[#53665A]">{label}</span>
      {children}
      {hint ? <span className="mt-2 block text-[10px] leading-5 text-[#7A867E]">{hint}</span> : null}
    </label>
  );
}
function Pill({ status }: { status: string }) {
  const ok = status === "approved";
  const pending = ["submitted", "under_review", "needs_information"].includes(status);
  return (
    <span
      className={`rounded-full border px-2.5 py-1 text-[10px] font-bold capitalize ${
        ok
          ? "border-[#B8D3AF] bg-[#F0F8EB] text-[#285A35]"
          : pending
            ? "border-[#E4D6A8] bg-[#FFF9E8] text-[#7B5A13]"
            : "border-[#E4B9AE] bg-[#FFF2EE] text-[#8A3528]"
      }`}
    >
      {status.replaceAll("_", " ")}
    </span>
  );
}

function RoleGate({
  organizationName,
  role,
  logout,
}: {
  organizationName: string;
  role: string;
  logout: () => Promise<void>;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#EEEADF] px-4 py-10 text-[#10231B]">
      <div className="w-full max-w-[620px] overflow-hidden rounded-[28px] border border-[#D4DCCF] bg-[#FFFDF8] shadow-[0_30px_100px_rgba(16,35,27,.12)]">
        <div className="bg-[#082218] px-7 py-8 text-white">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#173B2B] text-[#DCEF8B]">
              <Code2 className="h-5 w-5" />
            </div>
            <div>
              <div className="text-[15px] font-semibold">AGRO-AI</div>
              <div className="text-[11px] text-white/50">Platform API</div>
            </div>
          </div>
        </div>
        <div className="px-7 py-8">
          <div className="inline-flex items-center gap-2 rounded-full border border-[#D4DFCF] bg-[#F4F8F1] px-3 py-1.5 text-[10px] font-bold uppercase tracking-[.16em] text-[#315D46]">
            <LockKeyhole className="h-3.5 w-3.5" /> Platform security
          </div>
          <h1 className="mt-5 text-[30px] font-semibold tracking-[-.035em]">Owner or admin approval required</h1>
          <div className="mt-5 rounded-2xl border border-[#D5DFD1] bg-[#F6F9F3] p-4">
            <div className="text-[11px] font-semibold text-[#244735]">{organizationName}</div>
            <div className="mt-1 text-[10px] capitalize text-[#718078]">{role || "member"}</div>
          </div>
          <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
            <a href="/" className="text-[10px] font-semibold text-[#315D46]">
              Return home
            </a>
            <button
              onClick={() => void logout()}
              className="inline-flex h-10 items-center justify-center rounded-xl bg-[#102F22] px-4 text-[11px] font-semibold text-white"
            >
              Log out
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusView({
  application,
  refresh,
  loading,
}: {
  application: Application;
  refresh: () => Promise<void>;
  loading: boolean;
}) {
  const approved = application.status === "approved";
  const needsInfo = application.status === "needs_information";
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const steps = [
    [true, "Organization verified"],
    [true, "Application submitted"],
    [["under_review", "needs_information", "approved", "rejected"].includes(application.status), "Technical review"],
    [approved, "Bounded test enrollment"],
  ] as const;

  const submitAdditionalInformation = async (event: FormEvent) => {
    event.preventDefault();
    if (notes.trim().length < 10) return;
    setSubmitting(true);
    setError("");
    try {
      await apiClient.post(
        `/v1/platform/applications/${encodeURIComponent(application.id)}/additional-information`,
        { notes: notes.trim(), document_references: [] },
      );
      setNotes("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Additional information could not be submitted.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F3F1E9] px-4 py-10 text-[#10231B] md:px-8">
      <div className="mx-auto max-w-[1080px]">
        <div className="mb-5 flex items-center justify-between">
          <a href="https://agroai-pilot.com/platform-api" className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#102F22] text-[#DCEF8B]">
              <Code2 className="h-5 w-5" />
            </div>
            <div>
              <div className="text-[14px] font-semibold">AGRO-AI</div>
              <div className="text-[11px] text-[#728078]">Platform API</div>
            </div>
          </a>
          <button
            onClick={() => void refresh()}
            className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#D2DAD0] bg-white px-4 text-[11px] font-semibold"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>
        <div className="grid overflow-hidden rounded-[28px] border border-[#D4DCCF] bg-[#FFFDF8] shadow-[0_30px_100px_rgba(16,35,27,.12)] lg:grid-cols-[.86fr_1.14fr]">
          <section className="relative overflow-hidden bg-[#082218] px-8 py-10 text-white">
            <div
              className="absolute inset-0 opacity-30"
              style={{
                backgroundImage:
                  "radial-gradient(circle at 12% 8%,rgba(205,239,139,.34),transparent 30%),linear-gradient(rgba(255,255,255,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.05) 1px,transparent 1px)",
                backgroundSize: "auto,32px 32px,32px 32px",
              }}
            />
            <div className="relative">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[10px] font-bold uppercase tracking-[.16em] text-[#DCEF8B]">
                <LockKeyhole className="h-3.5 w-3.5" /> Controlled access
              </div>
              <h1 className="mt-8 text-[36px] font-semibold leading-[1.04] tracking-[-.04em]">
                Application {application.status.replaceAll("_", " ")}.
              </h1>
              <p className="mt-5 text-[13px] leading-7 text-white/65">
                Test access is reviewed. Live projects, billing, providers, and physical actions remain separate explicit gates.
              </p>
              <div className="mt-8 rounded-2xl border border-white/10 bg-white/5 p-4">
                <div className="text-[9px] font-bold uppercase tracking-[.16em] text-white/35">Application ID</div>
                <div className="mt-2 break-all font-mono text-[10px] text-white/70">{application.id}</div>
                <div className="mt-4 flex gap-2">
                  <Pill status={application.status} />
                  <span className="text-[10px] text-white/40">{application.requested_environment || "test"}</span>
                </div>
              </div>
            </div>
          </section>
          <section className="px-8 py-10">
            <div className="text-[10px] font-bold uppercase tracking-[.17em] text-[#4D745C]">Review progress</div>
            <h2 className="mt-2 text-[27px] font-semibold tracking-[-.03em]">A deliberate path to test access.</h2>
            <div className="mt-7 space-y-3">
              {steps.map(([done, label], index) => (
                <div key={label} className="flex items-center gap-3 rounded-xl border border-[#E0E5DC] bg-white px-4 py-3">
                  <span
                    className={`flex h-7 w-7 items-center justify-center rounded-full ${
                      done ? "bg-[#DDEBCF] text-[#315D46]" : "bg-[#EEF1EC] text-[#8A958E]"
                    }`}
                  >
                    {done ? <Check className="h-3.5 w-3.5" /> : index + 1}
                  </span>
                  <span className="text-[12px] font-semibold">{label}</span>
                </div>
              ))}
            </div>
            <p className="mt-5 text-[11px] text-[#718078]">
              Received {date(application.submitted_at || application.created_at)}
            </p>
            {application.decision_reason ? (
              <div className="mt-5 rounded-2xl border border-[#D5DFD1] bg-[#F6F9F3] p-4">
                <div className="text-[10px] font-bold uppercase tracking-[.14em] text-[#4D745C]">Review notes</div>
                <p className="mt-2 text-[11px] leading-6 text-[#5F6F65]">{application.decision_reason}</p>
              </div>
            ) : null}
            {needsInfo ? (
              <form onSubmit={submitAdditionalInformation} className="mt-6 rounded-2xl border border-[#C8D7C3] bg-[#F5F9F2] p-4">
                <div className="text-[11px] font-semibold text-[#244735]">Provide additional information</div>
                <p className="mt-1 text-[10px] leading-5 text-[#66756C]">
                  Submit the requested technical or commercial context through the audited application record.
                </p>
                <textarea
                  className={`${textareaClass} mt-3 bg-white`}
                  required
                  minLength={10}
                  maxLength={4000}
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  placeholder="Describe the additional information and any changes to your integration plan."
                />
                {error ? <div role="alert" className="mt-3 text-[11px] text-[#823628]">{error}</div> : null}
                <button
                  disabled={submitting || notes.trim().length < 10}
                  className="mt-3 inline-flex h-10 items-center gap-2 rounded-xl bg-[#315C83] px-4 text-[11px] font-semibold text-white disabled:opacity-45"
                >
                  {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Submit information
                </button>
              </form>
            ) : null}
            {approved ? (
              <button
                onClick={() => window.location.reload()}
                className="mt-6 inline-flex h-10 items-center gap-2 rounded-xl bg-[#102F22] px-4 text-[11px] font-semibold text-white"
              >
                Open developer console <ArrowRight className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </section>
        </div>
      </div>
    </div>
  );
}

export function PlatformApplicationGate() {
  const { user, currentOrganization, logout } = useAuth();
  const organizationRole = String(currentOrganization?.role || "").trim().toLowerCase();
  const canManageApplication = ["owner", "admin"].includes(organizationRole);
  const [applications, setApplications] = useState<Application[]>([]);
  const [form, setForm] = useState<FormState>(() => ({
    ...emptyForm,
    securityContact: user?.email || "",
    technicalContact: user?.email || "",
  }));
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [available, setAvailable] = useState(true);
  const [error, setError] = useState("");
  const active = useMemo(
    () => applications.find((item) => !TERMINAL_STATUSES.has(item.status)),
    [applications],
  );
  const latestTerminal = useMemo(
    () => applications.find((item) => TERMINAL_STATUSES.has(item.status)),
    [applications],
  );

  const refresh = async () => {
    setLoading(true);
    setError("");
    if (!canManageApplication) { setLoading(false); setApplications([]); setAvailable(false); setError(""); return; }
    try {
      const result = object(await apiClient.get("/v1/platform/applications"));
      setApplications(Array.isArray(result.applications) ? result.applications : []);
      setAvailable(true);
    } catch (cause: any) {
      if (cause?.status === 404) {
        setAvailable(false);
        setApplications([]);
      } else {
        setError(cause instanceof Error ? cause.message : "Application state could not be loaded.");
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, [canManageApplication]);
  useEffect(
    () =>
      setForm((current) => ({
        ...current,
        securityContact: current.securityContact || user?.email || "",
        technicalContact: current.technicalContact || user?.email || "",
      })),
    [user?.email],
  );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canManageApplication) return; setSubmitting(true);
    setError("");
    try {
      await apiClient.post("/v1/platform/applications", {
        application_type: "developer_beta",
        organization_website: form.website.trim(),
        corporate_email: user?.email,
        company_description: form.company.trim(),
        intended_product: form.product.trim(),
        use_case: form.useCase.trim(),
        target_users: form.users.trim(),
        expected_api_operations: values(form.operations),
        expected_monthly_volume: form.monthlyVolume.trim(),
        expected_data_volume: form.dataVolume.trim(),
        requested_environment: "test",
        required_providers: values(form.providers),
        geography: values(form.geography),
        security_contact: form.securityContact.trim(),
        technical_contact: form.technicalContact.trim(),
        billing_contact: null,
        requested_support: form.support,
        terms_version: "not_enforced_private_beta",
        privacy_version: "not_enforced_private_beta",
        document_references: [],
        bot_field: "",
      });
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Application could not be submitted.");
    } finally {
      setSubmitting(false);
    }
  };

  if (!canManageApplication) return <RoleGate organizationName={currentOrganization?.name || "AGRO-AI organization"} role={organizationRole} logout={logout} />;
  if (loading && !applications.length) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F3F1E9]">
        <Loader2 className="h-5 w-5 animate-spin text-[#315D46]" />
        <span className="ml-3 text-[12px] font-semibold">Loading Platform access…</span>
      </div>
    );
  }
  if (active) return <StatusView application={active} refresh={refresh} loading={loading} />;

  return (
    <div className="min-h-screen bg-[#EEEADF] text-[#10231B]">
      <div className="grid min-h-screen xl:grid-cols-[.78fr_1.22fr]">
        <section className="relative overflow-hidden bg-[#071F16] px-7 py-9 text-white md:px-11 xl:sticky xl:top-0 xl:h-screen">
          <div
            className="absolute inset-0 opacity-35"
            style={{
              backgroundImage:
                "radial-gradient(circle at 16% 12%,rgba(205,239,139,.32),transparent 29%),linear-gradient(rgba(255,255,255,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.05) 1px,transparent 1px)",
              backgroundSize: "auto,36px 36px,36px 36px",
            }}
          />
          <div className="relative flex h-full flex-col justify-between">
            <div className="flex items-center justify-between">
              <a href="https://agroai-pilot.com/platform-api" className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#173B2B] text-[#DCEF8B]">
                  <Code2 className="h-5 w-5" />
                </div>
                <div>
                  <div className="text-[15px] font-semibold">AGRO-AI</div>
                  <div className="text-[11px] text-white/42">Platform API</div>
                </div>
              </a>
              <button
                onClick={() => void logout()}
                className="rounded-xl border border-white/10 px-3 py-2 text-[10px] font-semibold text-white/55"
              >
                Log out
              </button>
            </div>
            <div className="max-w-xl py-14">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[10px] font-bold uppercase tracking-[.17em] text-[#DCEF8B]">
                <ShieldCheck className="h-3.5 w-3.5" /> Developer private beta
              </div>
              <h1 className="mt-6 text-[44px] font-semibold leading-[1.02] tracking-[-.045em] md:text-[54px]">
                Build agricultural intelligence into your product.
              </h1>
              <p className="mt-6 text-[14px] leading-7 text-white/65">
                Request bounded test access to real API contracts, isolated projects, scoped machine identities, deterministic field data, recommendations, reports, usage, and logs.
              </p>
              <div className="mt-8 grid gap-3 sm:grid-cols-2">
                {[
                  [Building2, "Verified organizations"],
                  [Code2, "Curated API contract"],
                  [LockKeyhole, "Test-first access"],
                  [FileCheck2, "Reviewed production"],
                ].map(([Icon, label]) => (
                  <div key={String(label)} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <Icon className="h-4 w-4 text-[#DCEF8B]" />
                    <div className="mt-3 text-[11px] font-semibold">{String(label)}</div>
                  </div>
                ))}
              </div>
            </div>
            <div className="text-[10px] leading-5 text-white/35">
              Application approval never grants automatic live access or physical execution.
            </div>
          </div>
        </section>
        <main className="px-4 py-7 md:px-8 xl:px-11">
          <div className="mx-auto max-w-[850px] rounded-[28px] border border-black/10 bg-[#FFFDF8] p-6 shadow-[0_28px_90px_rgba(16,35,27,.11)] md:p-8">
            <div className="border-b border-[#E0E5DC] pb-6">
              <div className="text-[10px] font-bold uppercase tracking-[.18em] text-[#4D745C]">Platform enrollment</div>
              <h2 className="mt-2 text-[29px] font-semibold tracking-[-.035em]">Request test access.</h2>
              <p className="mt-2 text-[12px] leading-6 text-[#65736A]">
                Signed in to <strong className="text-[#244735]">{currentOrganization?.name || "AGRO-AI organization"}</strong>. API enrollment is reviewed separately from account verification.
              </p>
            </div>
            {latestTerminal ? (
              <div className="mt-6 rounded-2xl border border-[#D5DFD1] bg-[#F6F9F3] p-4">
                <div className="flex items-center gap-2">
                  <Pill status={latestTerminal.status} />
                  <span className="text-[10px] text-[#718078]">
                    Previous application · {date(latestTerminal.submitted_at || latestTerminal.created_at)}
                  </span>
                </div>
                <p className="mt-3 text-[11px] leading-6 text-[#5F6F65]">
                  You can submit a new corrected application. The prior record remains available for audit.
                </p>
              </div>
            ) : null}
            {!available ? (
              <div className="mt-6 rounded-2xl border border-[#E3D5A8] bg-[#FFF9E8] p-5 text-[11px] leading-6 text-[#705518]">
                Applications are not enabled in this environment. The product remains fail-closed and no access was granted.
              </div>
            ) : null}
            {error ? (
              <div role="alert" className="mt-6 rounded-2xl border border-[#E4B9AE] bg-[#FFF2EE] p-4 text-[11px] text-[#823628]">
                {error}
              </div>
            ) : null}
            {available ? (
              <form onSubmit={submit} className="mt-7 space-y-5">
                <div className="grid gap-5 md:grid-cols-2">
                  <Field label="Organization website">
                    <input
                      className={inputClass}
                      type="url"
                      required
                      value={form.website}
                      onChange={(event) => setForm({ ...form, website: event.target.value })}
                      placeholder="https://company.com"
                    />
                  </Field>
                  <Field label="Corporate email">
                    <input className={`${inputClass} bg-[#F5F7F3]`} type="email" readOnly value={user?.email || ""} />
                  </Field>
                </div>
                <Field label="Organization and technical capability">
                  <textarea className={textareaClass} required minLength={20} value={form.company} onChange={(event) => setForm({ ...form, company: event.target.value })} />
                </Field>
                <Field label="Product you intend to build">
                  <textarea className={textareaClass} required minLength={10} value={form.product} onChange={(event) => setForm({ ...form, product: event.target.value })} />
                </Field>
                <Field label="Concrete agricultural use case">
                  <textarea className={textareaClass} required minLength={10} value={form.useCase} onChange={(event) => setForm({ ...form, useCase: event.target.value })} />
                </Field>
                <div className="grid gap-5 md:grid-cols-2">
                  <Field label="Target users"><input className={inputClass} required value={form.users} onChange={(event) => setForm({ ...form, users: event.target.value })} /></Field>
                  <Field label="Expected API operations"><input className={inputClass} required value={form.operations} onChange={(event) => setForm({ ...form, operations: event.target.value })} /></Field>
                  <Field label="Expected monthly volume"><input className={inputClass} required value={form.monthlyVolume} onChange={(event) => setForm({ ...form, monthlyVolume: event.target.value })} placeholder="100,000 requests" /></Field>
                  <Field label="Expected data volume"><input className={inputClass} required value={form.dataVolume} onChange={(event) => setForm({ ...form, dataVolume: event.target.value })} placeholder="20 GB" /></Field>
                  <Field label="Required providers" hint="Optional; partner-contract gates remain enforced."><input className={inputClass} value={form.providers} onChange={(event) => setForm({ ...form, providers: event.target.value })} /></Field>
                  <Field label="Geography"><input className={inputClass} value={form.geography} onChange={(event) => setForm({ ...form, geography: event.target.value })} /></Field>
                  <Field label="Security contact"><input className={inputClass} type="email" required value={form.securityContact} onChange={(event) => setForm({ ...form, securityContact: event.target.value })} /></Field>
                  <Field label="Technical contact"><input className={inputClass} type="email" required value={form.technicalContact} onChange={(event) => setForm({ ...form, technicalContact: event.target.value })} /></Field>
                </div>
                <Field label="Requested support">
                  <select className={inputClass} value={form.support} onChange={(event) => setForm({ ...form, support: event.target.value })}>
                    <option value="documentation">Documentation</option>
                    <option value="implementation_review">Implementation review</option>
                    <option value="strategic_partner_support">Strategic partner support</option>
                  </select>
                </Field>
                <div className="rounded-2xl border border-[#D5DFD1] bg-[#F6F9F3] p-4 text-[10px] leading-5 text-[#68776E]">
                  Submission creates a review record only. It does not create projects, issue keys, activate billing, accept draft legal documents, enable providers, grant live access, or authorize physical actions.
                </div>
                <div className="flex flex-col-reverse gap-3 border-t border-[#E0E5DC] pt-5 sm:flex-row sm:items-center sm:justify-between">
                  <a href="https://agroai-pilot.com/platform-api/docs/" className="inline-flex items-center gap-2 text-[10px] font-semibold text-[#315D46]">
                    Review documentation <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                  <button disabled={submitting} className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-[#102F22] px-5 text-[11px] font-semibold text-white disabled:opacity-45">
                    {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Submit application
                  </button>
                </div>
              </form>
            ) : null}
          </div>
        </main>
      </div>
    </div>
  );
}
