import { Link } from "react-router";
import { Bell, CreditCard, Database, Globe2, Lock, PlugZap, ShieldCheck, SlidersHorizontal, Users } from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { LanguageSelector } from "./LanguageSelector";
import { BG, BORDER, GREEN, MUTED, PortalButton, SURFACE, TEXT } from "./portalUi";

function Card({ title, description, icon: Icon, children }: { title: string; description?: string; icon: any; children?: React.ReactNode }) {
  return (
    <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl" style={{ background: "#EEF8E8", color: GREEN }}><Icon className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1">
          <h2 className="text-[17px] font-semibold" style={{ color: TEXT }}>{title}</h2>
          {description ? <p className="mt-1 text-[13px] leading-6" style={{ color: MUTED }}>{description}</p> : null}
          {children ? <div className="mt-4">{children}</div> : null}
        </div>
      </div>
    </section>
  );
}

function Row({ label, value, action }: { label: string; value: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-5 border-t py-3 text-[13px]" style={{ borderColor: BORDER }}>
      <div>
        <div className="font-medium" style={{ color: TEXT }}>{label}</div>
        <div className="mt-0.5" style={{ color: MUTED }}>{value}</div>
      </div>
      {action}
    </div>
  );
}

export function SettingsPage() {
  const { currentOrganization, currentWorkspace, user } = useAuth();
  const plan = currentOrganization?.plan || "free";

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: GREEN }}>Workspace controls</div>
            <h1 className="mt-2 text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Settings</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-7" style={{ color: MUTED }}>Control language, subscription, workspace identity, data, integrations, notifications, security posture, and operating preferences from one place.</p>
          </div>
          <Link to="/billing"><PortalButton>Manage subscription</PortalButton></Link>
        </div>
      </header>

      <main className="grid gap-5 px-8 py-6 lg:grid-cols-2" style={{ maxWidth: 1240 }}>
        <Card icon={Globe2} title="Language & region" description="Choose the portal language. AGRO-AI also sends this preference into Ask AGRO-AI so responses can follow the selected language when possible.">
          <div className="max-w-[360px]"><LanguageSelector /></div>
          <p className="mt-3 text-[12px] leading-5" style={{ color: MUTED }}>Right-to-left layout is enabled automatically for Arabic, Hebrew, Persian, and Urdu.</p>
        </Card>

        <Card icon={CreditCard} title="Subscription & billing" description="Review plan, upgrade, billing portal, and commercial rollout options.">
          <Row label="Current plan" value={plan} action={<Link to="/pricing"><PortalButton variant="secondary">Change plan</PortalButton></Link>} />
          <Row label="Billing" value="Checkout, invoices, and subscription status" action={<Link to="/billing"><PortalButton variant="secondary">Open billing</PortalButton></Link>} />
        </Card>

        <Card icon={SlidersHorizontal} title="Workspace identity" description="The operating identity used across reports, evidence, field tasks, and customer packets.">
          <Row label="Workspace" value={currentWorkspace?.name || "Evaluation workspace"} />
          <Row label="Organization" value={currentOrganization?.name || "Organization"} />
          <Row label="User" value={user?.email || user?.name || "Current user"} />
        </Card>

        <Card icon={PlugZap} title="Integrations & controllers" description="Connect field systems, evidence sources, and controller gateways from the platform.">
          <Row label="Connectors" value="WiseConn, Talgil, Universal Controller Gateway, uploads, document sources" action={<Link to="/integrations"><PortalButton variant="secondary">Open connectors</PortalButton></Link>} />
          <Row label="Controller execution" value="Readiness-gated. Physical writes require mapping, budget, approval, audit log, and readback." />
        </Card>

        <Card icon={Bell} title="Notifications" description="Prepare how AGRO-AI should surface operating events. Email delivery is already used by report/email workflows when configured.">
          <Row label="Report delivery" value="Email report to account address from Ask AGRO-AI or Report Factory" />
          <Row label="Field alerts" value="Prepared for water-risk, missing-evidence, controller-readiness, and compliance alerts" />
        </Card>

        <Card icon={ShieldCheck} title="Security & access" description="Keep the workspace ready for serious operators, agencies, lenders, insurers, and enterprise customers.">
          <Row label="Account security" value="Email verification, 2FA request, and secure session controls" action={<Link to="/security"><PortalButton variant="secondary">Open security</PortalButton></Link>} />
          <Row label="Team access" value="Invite users and assign roles when the workspace is on Team, Network, or Enterprise" action={<Link to="/team"><PortalButton variant="secondary">Open team</PortalButton></Link>} />
        </Card>

        <Card icon={Database} title="Data & evidence" description="Control the records AGRO-AI uses before it makes recommendations or produces reports.">
          <Row label="Evidence library" value="Uploaded records, connector imports, parsed files, and report-ready evidence" action={<Link to="/evidence"><PortalButton variant="secondary">Review evidence</PortalButton></Link>} />
          <Row label="Data provenance" value="Measured, uploaded, inferred, missing, and sample data stay separated in reports." />
        </Card>

        <Card icon={Lock} title="Operating safety" description="The agent can do digital work, but physical field/control execution must remain approval-gated.">
          <Row label="Agent actions" value="Tasks and report actions can execute digitally. Controller actions require approval and readiness checks." />
          <Row label="Audit trail" value="Operator actions, approval packets, evidence changes, and generated reports are prepared for audit logging." action={<Link to="/audit"><PortalButton variant="secondary">Open audit</PortalButton></Link>} />
        </Card>

        <Card icon={Users} title="Support & requests" description="Every support, onboarding, integration, or sales request can be tracked from the workspace.">
          <Row label="Support" value="Ask for help, report issues, request onboarding, or request an integration" action={<Link to="/support"><PortalButton variant="secondary">Open support</PortalButton></Link>} />
          <Row label="Admin requests" value="Owners/admins can review inbound requests and status" action={<Link to="/admin/requests"><PortalButton variant="secondary">Open requests</PortalButton></Link>} />
        </Card>
      </main>
    </div>
  );
}
