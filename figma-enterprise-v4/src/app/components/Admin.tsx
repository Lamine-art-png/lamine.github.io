import { useCallback } from "react";
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
  const { user, currentOrganization, currentWorkspace } = useAuth();
  const aiState = usePortalResource<Record<string, unknown>>(useCallback(() => apiClient.ai.status(), []));
  const systemState = usePortalResource<Record<string, unknown>>(useCallback(() => apiClient.adminRequests.system(), []));
  const ai = aiState.data || {};
  const system = systemState.data || {};
  const cloudflare = (system.cloudflare || {}) as Record<string, unknown>;

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <StatusBadge label="Admin" tone="neutral" />
              <StatusBadge label="Workspace controls" tone="good" />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>System Administration</h1>
            <p className="mt-2 max-w-2xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Manage workspace configuration, connected systems, billing readiness, and administrative controls.
            </p>
          </div>
          <PortalButton onClick={() => window.location.assign("/integrations")}>Set up connectors</PortalButton>
        </div>
      </header>

      <main className="px-8 py-6 space-y-5" style={{ maxWidth: 1100 }}>
        <section className="grid grid-cols-3 gap-5">
          <Card title="Organization" rows={[
            ["Name", safe(currentOrganization?.name, "AGRO-AI")],
            ["User", safe(user?.email, "Authenticated user")],
            ["Plan", safe(currentOrganization?.plan, "free")],
          ]} />

          <Card title="Workspace" rows={[
            ["Active workspace", safe(currentWorkspace?.name, "Workspace")],
            ["Mode", safe(currentWorkspace?.status || currentWorkspace?.evaluation_status, "Evaluation")],
            ["Live sync", "Credential-gated"],
          ]} />

          <Card title="Feature gates" rows={[
            ["Connectors", "Unlocked"],
            ["Reports", "Unlocked"],
            ["Ask AGRO-AI", "Unlocked"],
          ]} />
        </section>

        <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>Intelligence backend</div>
              <h2 className="text-[20px] font-semibold" style={{ color: TEXT }}>Model runtime</h2>
            </div>
            <PortalButton variant="secondary" onClick={aiState.refresh}>Refresh</PortalButton>
          </div>
          <div className="grid grid-cols-3 gap-5">
            <Card title="Status" rows={[
              ["Configured", safe(ai.configured, "false")],
              ["Provider", safe(ai.provider, "offline")],
              ["Mode", safe(ai.mode, "offline")],
            ]} />
            <Card title="Model" rows={[
              ["Model", safe(ai.model, "Not configured")],
              ["Fallback active", safe(ai.fallback_active, "true")],
              ["Base URL", safe(ai.base_url_present, "false")],
            ]} />
            <Card title="Missing env" rows={[
              ["Required values", Array.isArray(ai.missing_env) && ai.missing_env.length ? String(ai.missing_env.join(", ")) : "None"],
              ["Verification", aiState.error ? aiState.error : "Status endpoint healthy"],
              ["Action", "Test from Intelligence panel"],
            ]} />
          </div>
        </section>

        <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>Deployment</div>
              <h2 className="text-[20px] font-semibold" style={{ color: TEXT }}>Cloudflare and API build state</h2>
            </div>
            <PortalButton variant="secondary" onClick={systemState.refresh}>Refresh</PortalButton>
          </div>
          <div className="grid grid-cols-3 gap-5">
            <Card title="Frontend" rows={[
              ["Build root", safe(cloudflare.build_root, "figma-enterprise-v4")],
              ["Build command", safe(cloudflare.build_command, "npm run build")],
              ["Output", safe(cloudflare.output_directory, "dist")],
            ]} />
            <Card title="Release" rows={[
              ["Production branch", safe(cloudflare.production_branch, "main")],
              ["Build version", safe(system.build_version, "local")],
              ["API URL env", safe(system.api_url_env, "VITE_API_BASE_URL")],
            ]} />
            <Card title="Backend" rows={[
              ["API base", safe(system.api_base_url, "Configured by environment")],
              ["System endpoint", systemState.error ? systemState.error : "Healthy"],
              ["Billing", "Admin-visible only"],
            ]} />
          </div>
        </section>

        <section className="rounded-2xl p-6" style={{ background: "#0D2B1E", border: "1px solid rgba(255,255,255,0.08)" }}>
          <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: "rgba(155,216,75,0.65)" }}>
            Internal rule
          </div>
          <h2 className="text-[22px] font-semibold mb-2" style={{ color: "white" }}>
            Keep the operating room accountable.
          </h2>
          <p className="text-[13px] leading-relaxed max-w-3xl" style={{ color: "rgba(255,255,255,0.68)" }}>
            Every connector, evidence record, decision, report, and field update should remain tied to the active workspace and organization.
          </p>
        </section>
      </main>
    </div>
  );
}

function Card({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-4" style={{ color: MUTED }}>{title}</div>
      <div className="space-y-3">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-4 text-[13px]">
            <span style={{ color: MUTED }}>{label}</span>
            <span className="font-semibold text-right" style={{ color: TEXT }}>{value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
