import { useAuth } from "../auth/AuthProvider";
import { BG, BORDER, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

function safe(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

export function Admin() {
  const { user, currentOrganization, currentWorkspace } = useAuth();

  const plan = safe(currentOrganization?.plan, "Free");
  const role = safe(currentOrganization?.role, "Owner");
  const workspace = safe(currentWorkspace?.name, "Demo workspace");
  const org = safe(currentOrganization?.name, "AGRO-AI workspace");

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <StatusBadge label="Settings" />
              <StatusBadge label={`${plan} plan`} tone={String(plan).toLowerCase() === "free" ? "warn" : "good"} />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Settings</h1>
            <p className="mt-2 max-w-2xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Manage workspace access, plan status, billing readiness, and operational configuration.
            </p>
          </div>

          <PortalButton onClick={() => window.location.assign("/integrations")}>
            Set up connectors
          </PortalButton>
        </div>
      </header>

      <main className="px-8 py-6 space-y-5" style={{ maxWidth: 1100 }}>
        <section className="grid grid-cols-3 gap-5">
          <Card title="Organization" rows={[
            ["Name", org],
            ["User", safe(user?.email, "Authenticated user")],
            ["Role", role],
          ]} />

          <Card title="Workspace" rows={[
            ["Active workspace", workspace],
            ["Mode", "Demo / evaluation"],
            ["Live sync", "Not enabled"],
          ]} />

          <Card title="Plan" rows={[
            ["Current plan", plan],
            ["Billing", "Not connected"],
            ["Upgrade path", "Pilot → Pro → Enterprise"],
          ]} />
        </section>

        <section className="rounded-2xl p-6" style={{ background: "#0D2B1E", border: "1px solid rgba(255,255,255,0.08)" }}>
          <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: "rgba(155,216,75,0.65)" }}>
            What matters next
          </div>
          <h2 className="text-[22px] font-semibold mb-2" style={{ color: "white" }}>
            Connect one real source before adding more dashboards.
          </h2>
          <p className="text-[13px] leading-relaxed max-w-3xl" style={{ color: "rgba(255,255,255,0.68)" }}>
            The product becomes valuable when WiseConn, Talgil, weather, ET, or uploaded evidence flows into the same decision layer. Until then, the portal must clearly label demo data and avoid fake live claims.
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
