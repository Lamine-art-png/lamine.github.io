import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronUp, Download, RefreshCw, Search, Users } from "lucide-react";
import { apiClient, ApiError, PlatformAdminCustomerFilters } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

const ACCESS_APPEALS_LABEL = "Access appeals";

function safe(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

export function Admin() {
  const { currentOrganization, entitlements, platformAdmin } = useAuth();
  const canAccessAdminRequests = Boolean(entitlements.can_access_admin_requests);

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="mb-3 flex items-center gap-2">
              <StatusBadge label="Admin" tone="neutral" />
              <StatusBadge label="Workspace controls" tone="good" />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Administration</h1>
            <p className="mt-2 max-w-2xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Coordinate workspace operations, routing, and escalation from one clean administrative surface.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {platformAdmin ? <PortalButton onClick={() => window.location.assign("/admin/customers")}>Customer accounts</PortalButton> : null}
{platformAdmin ? <PortalButton variant="secondary" onClick={() => window.location.assign("/admin/access-appeals")}>{ACCESS_APPEALS_LABEL}</PortalButton> : null}
            <PortalButton variant="secondary" onClick={() => window.location.assign("/admin/system")}>Open System Health</PortalButton>
          </div>
        </div>
      </header>

      <main className="space-y-5 px-8 py-6" style={{ maxWidth: 1100 }}>
        <section className="grid grid-cols-3 gap-5">
          <Card title="Organization" rows={[
            ["Organization", safe(currentOrganization?.name, "AGRO-AI")],
            ["Plan", safe(currentOrganization?.plan, "free")],
            ["Status", safe(currentOrganization?.subscription_status, "inactive")],
          ]} />
          <Card title="Team operations" rows={[
            ["Invites", Boolean(entitlements.can_invite_team) ? "Available" : "Upgrade to Team"],
            ["Admin requests", canAccessAdminRequests ? "Available" : "Upgrade to Team"],
            ["Network rollups", Boolean(entitlements.can_access_network_rollups) ? "Available" : "Upgrade to Network"],
          ]} />
          <Card title="Support" rows={[
            ["Support level", safe(entitlements.support_level, "basic")],
            ["Security", Boolean(entitlements.can_access_enterprise_security) ? "Enterprise controls" : "Standard controls"],
            ["Workspace routing", "Organization scoped"],
          ]} />
        </section>

        <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="mb-4 text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>Administrative focus</div>
          <div className="grid gap-4 md:grid-cols-2">
            {[
              "Build trusted reports from real field proof.",
              "Coordinate field teams, water risk, compliance evidence, and executive reporting.",
              "Turn agricultural evidence into decisions.",
              "Operate fields, evidence, water risk, and reports from one secure workspace.",
            ].map((line) => (
              <div key={line} className="rounded-xl p-4 text-[13px] leading-6" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                {line}
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

type CustomerOrganization = {
  id: string;
  name: string;
  role: string;
  plan: string;
  subscription_status: string;
  workspace_count: number;
};

type CustomerAccount = {
  id: string;
  name?: string | null;
  email: string;
  created_at?: string | null;
  last_login_at?: string | null;
  is_active: boolean;
  verification_status: string;
  account_status: string;
  access_restriction_reason?: string | null;
  access_restricted_at?: string | null;
  email_verified_at?: string | null;
  organizations: CustomerOrganization[];
  organization_count: number;
  activity: { event_count: number; quantity: number; last_activity_at?: string | null };
};

type CustomerDirectoryResponse = {
  overview: {
    total_accounts: number;
    verified_accounts: number;
    unverified_accounts: number;
    active_accounts: number;
    accounts_that_signed_in: number;
    registrations_7d: number;
    registrations_30d: number;
    total_organizations: number;
    paid_organizations: number;
    total_workspaces: number;
    organizations_by_plan: Record<string, number>;
  };
  customers: CustomerAccount[];
  pagination: { offset: number; limit: number; filtered_count: number; has_more: boolean };
  generated_at: string;
};

function displayDate(value?: string | null) {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function downloadBlob(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

export function CustomerAccountsPage() {
  const [search, setSearch] = useState("");
  const [verification, setVerification] = useState<"all" | "verified" | "unverified">("all");
  const [active, setActive] = useState<"all" | "active" | "inactive">("all");
  const [plan, setPlan] = useState("");
  const [sort, setSort] = useState<"newest" | "oldest" | "recent_login">("newest");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<CustomerDirectoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const limit = 50;

  const filters: PlatformAdminCustomerFilters = { search: search.trim() || undefined, verification, active, plan: plan || undefined, sort, limit, offset };

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await apiClient.platformAdmin.customers(filters) as CustomerDirectoryResponse;
      setData(response);
    } catch (cause) {
      const apiError = cause as ApiError;
      setError(apiError.status === 403 ? "This directory is restricted to verified AGRO-AI platform administrators." : apiError.message || "Customer accounts could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [search, verification, active, plan, sort, offset]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), search ? 300 : 0);
    return () => window.clearTimeout(timer);
  }, [load, search]);

  const exportCsv = async () => {
    setExporting(true);
    setError("");
    try {
      const blob = await apiClient.platformAdmin.exportCustomers({ search: search.trim() || undefined, verification, active, plan: plan || undefined, sort });
      downloadBlob(blob, `agroai-customers-${new Date().toISOString().slice(0, 10)}.csv`);
    } catch (cause) {
      setError((cause as Error).message || "Customer export could not be generated.");
    } finally {
      setExporting(false);
    }
  };

  const overview = data?.overview;
  const pagination = data?.pagination;

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-4 py-6 md:px-8 md:py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <StatusBadge label="Founder view" tone="good" />
              <StatusBadge label="Server-authorized" tone="neutral" />
            </div>
            <h1 className="text-[28px] font-semibold tracking-tight md:text-[32px]" style={{ color: TEXT }}>Customer accounts</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              See who registered, which accounts verified, when customers last signed in, their organizations, plans, workspaces, and platform activity.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <PortalButton variant="secondary" onClick={() => void load()}><RefreshCw className="h-4 w-4" /> Refresh</PortalButton>
            <PortalButton onClick={() => void exportCsv()} disabled={exporting}><Download className="h-4 w-4" /> {exporting ? "Preparing…" : "Export CSV"}</PortalButton>
          </div>
        </div>
      </header>

      <main className="space-y-5 px-4 py-5 md:px-8 md:py-6" style={{ maxWidth: 1480 }}>
        {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-800">{error}</div> : null}

        <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <MetricCard label="Total accounts" value={overview?.total_accounts} detail={`${overview?.registrations_7d ?? 0} joined in 7 days`} />
          <MetricCard label="Verified" value={overview?.verified_accounts} detail={`${overview?.unverified_accounts ?? 0} awaiting verification`} />
          <MetricCard label="Signed in" value={overview?.accounts_that_signed_in} detail="Accounts with at least one login" />
          <MetricCard label="Organizations" value={overview?.total_organizations} detail={`${overview?.paid_organizations ?? 0} paid organizations`} />
          <MetricCard label="Workspaces" value={overview?.total_workspaces} detail={`${overview?.registrations_30d ?? 0} accounts joined in 30 days`} />
        </section>

        <section className="rounded-2xl p-4 md:p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[minmax(260px,1fr)_180px_160px_160px_170px]">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4" style={{ color: MUTED }} />
              <input value={search} onChange={(event) => { setSearch(event.target.value); setOffset(0); }} placeholder="Search email, name, or organization" className="h-10 w-full rounded-lg border bg-white pl-10 pr-3 text-[13px] outline-none" style={{ borderColor: BORDER, color: TEXT }} />
            </label>
            <FilterSelect value={verification} onChange={(value) => { setVerification(value as typeof verification); setOffset(0); }} options={[["all", "All verification"], ["verified", "Verified"], ["unverified", "Unverified"]]} />
            <FilterSelect value={active} onChange={(value) => { setActive(value as typeof active); setOffset(0); }} options={[["all", "All accounts"], ["active", "Active"], ["inactive", "Inactive"]]} />
            <FilterSelect value={plan} onChange={(value) => { setPlan(value); setOffset(0); }} options={[["", "All plans"], ["free", "Free"], ["professional", "Professional"], ["team", "Team"], ["network", "Network"], ["enterprise", "Enterprise"]]} />
            <FilterSelect value={sort} onChange={(value) => { setSort(value as typeof sort); setOffset(0); }} options={[["newest", "Newest first"], ["oldest", "Oldest first"], ["recent_login", "Recent login"]]} />
          </div>
        </section>

        <section className="overflow-hidden rounded-2xl" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex items-center justify-between gap-4 border-b px-4 py-4 md:px-5" style={{ borderColor: BORDER }}>
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4" style={{ color: MUTED }} />
              <span className="text-[13px] font-semibold" style={{ color: TEXT }}>{pagination?.filtered_count ?? 0} matching accounts</span>
            </div>
            <span className="text-[11px]" style={{ color: MUTED }}>{data?.generated_at ? `Updated ${displayDate(data.generated_at)}` : ""}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1120px] border-collapse text-left">
              <thead>
                <tr style={{ background: BG }}>
                  {['Customer', 'Registered', 'Verification', 'Access', 'Last login', 'Organization', 'Plan', 'Workspaces', 'Activity'].map((label) => <th key={label} className="border-b px-4 py-3 text-[10px] font-semibold uppercase tracking-wider" style={{ borderColor: BORDER, color: MUTED }}>{label}</th>)}
                </tr>
              </thead>
              <tbody>
                {loading ? <tr><td colSpan={9} className="px-4 py-12 text-center text-[13px]" style={{ color: MUTED }}>Loading customer accounts…</td></tr> : null}
                {!loading && !data?.customers.length ? <tr><td colSpan={9} className="px-4 py-12 text-center text-[13px]" style={{ color: MUTED }}>No accounts match these filters.</td></tr> : null}
                {!loading ? data?.customers.map((customer) => {
                  const primary = customer.organizations[0];
                  return (
                    <tr key={customer.id} className="border-b last:border-b-0" style={{ borderColor: BORDER }}>
                      <td className="px-4 py-4"><div className="text-[13px] font-semibold" style={{ color: TEXT }}>{customer.name || "Unnamed account"}</div><div className="mt-1 text-[12px]" style={{ color: MUTED }}>{customer.email}</div></td>
                      <td className="px-4 py-4 text-[12px]" style={{ color: TEXT }}>{displayDate(customer.created_at)}</td>
                      <td className="px-4 py-4"><StatusBadge label={customer.verification_status === "verified" ? "Verified" : "Unverified"} tone={customer.verification_status === "verified" ? "good" : "warning"} /></td>
                      <td className="px-4 py-4"><StatusBadge label={customer.account_status === "active" ? "Active" : customer.account_status.replaceAll("_", " ")} tone={customer.account_status === "active" ? "good" : "warning"} /></td>
                      <td className="px-4 py-4 text-[12px]" style={{ color: TEXT }}>{displayDate(customer.last_login_at)}</td>
                      <td className="px-4 py-4"><div className="text-[12px] font-semibold" style={{ color: TEXT }}>{primary?.name || "No organization"}</div>{customer.organization_count > 1 ? <div className="mt-1 text-[11px]" style={{ color: MUTED }}>+{customer.organization_count - 1} more</div> : null}</td>
                      <td className="px-4 py-4"><div className="text-[12px] font-semibold capitalize" style={{ color: TEXT }}>{primary?.plan || "—"}</div><div className="mt-1 text-[11px] capitalize" style={{ color: MUTED }}>{primary?.subscription_status || "—"}</div></td>
                      <td className="px-4 py-4 text-[12px] font-semibold" style={{ color: TEXT }}>{customer.organizations.reduce((sum, org) => sum + Number(org.workspace_count || 0), 0)}</td>
                      <td className="px-4 py-4"><div className="text-[12px] font-semibold" style={{ color: TEXT }}>{customer.activity.event_count} events</div><div className="mt-1 text-[11px]" style={{ color: MUTED }}>{customer.activity.last_activity_at ? displayDate(customer.activity.last_activity_at) : "No recorded usage"}</div></td>
                    </tr>
                  );
                }) : null}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between gap-4 px-4 py-4 md:px-5">
            <span className="text-[11px]" style={{ color: MUTED }}>{pagination ? `Showing ${pagination.filtered_count ? pagination.offset + 1 : 0}–${Math.min(pagination.offset + pagination.limit, pagination.filtered_count)} of ${pagination.filtered_count}` : ""}</span>
            <div className="flex gap-2">
              <PortalButton variant="secondary" disabled={!pagination || pagination.offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</PortalButton>
              <PortalButton variant="secondary" disabled={!pagination?.has_more || loading} onClick={() => setOffset(offset + limit)}>Next</PortalButton>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

function MetricCard({ label, value, detail }: { label: string; value?: number; detail: string }) {
  return <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{label}</div><div className="mt-3 text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>{value ?? "—"}</div><div className="mt-2 text-[11px] leading-5" style={{ color: MUTED }}>{detail}</div></section>;
}

function FilterSelect({ value, onChange, options }: { value: string; onChange: (value: string) => void; options: [string, string][] }) {
  return <select value={value} onChange={(event) => onChange(event.target.value)} className="h-10 w-full rounded-lg border bg-white px-3 text-[13px] outline-none" style={{ borderColor: BORDER, color: TEXT }}>{options.map(([optionValue, label]) => <option key={optionValue || "all-plans"} value={optionValue}>{label}</option>)}</select>;
}

export function SystemHealthPage() {
  const state = usePortalResource<Record<string, unknown>>(useCallback(() => apiClient.adminRequests.system(), []));
  const [open, setOpen] = useState(false);
  const data = state.data || {};
  const technical = (data.technical_details || {}) as Record<string, unknown>;

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="mb-3 flex items-center gap-2">
              <StatusBadge label="System Health" tone="good" />
              <StatusBadge label="Owner or admin only" tone="neutral" />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>System Health</h1>
            <p className="mt-2 max-w-2xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Review release status, service readiness, and production setup without exposing technical runtime language in the main customer workspace.
            </p>
          </div>
          <PortalButton variant="secondary" onClick={state.refresh}>Refresh</PortalButton>
        </div>
      </header>

      <main className="space-y-5 px-8 py-6" style={{ maxWidth: 1100 }}>
        <section className="grid grid-cols-2 gap-5 md:grid-cols-3">
          <Card title="Core services" rows={[["API", safe(data.api)], ["Intelligence", safe(data.intelligence)], ["Billing", safe(data.billing)]]} />
          <Card title="Delivery" rows={[["Email delivery", safe(data.email_delivery)], ["Frontend release", safe(data.frontend_release)], ["Backend release", safe(data.backend_release)]]} />
          <Card title="Observability" rows={[["Last checked", safe(data.last_checked_at)], ["Status endpoint", state.error ? state.error : "Healthy"], ["Workspace access", "Owner and admin scoped"]]} />
        </section>

        <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <button type="button" onClick={() => setOpen((value) => !value)} className="flex w-full items-center justify-between text-left">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>Technical details</div>
              <div className="mt-2 text-[18px] font-semibold" style={{ color: TEXT }}>Advanced system context</div>
            </div>
            {open ? <ChevronUp className="h-4 w-4" style={{ color: MUTED }} /> : <ChevronDown className="h-4 w-4" style={{ color: MUTED }} />}
          </button>

          {open ? (
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <Card title="Intelligence" rows={[["Provider", safe(technical.provider)], ["Model", safe(technical.model)], ["Fallback", safe(technical.fallback)]]} />
              <Card title="Environment" rows={[["API URL", safe(technical.api_url)], ["App URL", safe(technical.app_url)], ["Missing env", Array.isArray(technical.env_names) && technical.env_names.length ? technical.env_names.join(", ") : "None"]]} />
            </div>
          ) : null}
        </section>
      </main>
    </div>
  );
}

function Card({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="mb-4 text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{title}</div>
      <div className="space-y-3">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-4 text-[13px]">
            <span style={{ color: MUTED }}>{label}</span>
            <span className="text-right font-semibold" style={{ color: TEXT }}>{value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
