import { useCallback, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

function safe(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

export function Admin() {
  const { currentOrganization, entitlements } = useAuth();
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
          <PortalButton onClick={() => window.location.assign("/admin/system")}>Open System Health</PortalButton>
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
