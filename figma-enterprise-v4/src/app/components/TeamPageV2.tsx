import { useCallback, useState } from "react";
import { Lock, Users } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { openCommercialBoundary } from "./CommercialBoundaryHost";
import { BG, BORDER, MUTED, PortalButton, SURFACE, TEXT } from "./portalUi";

type ShellResponse = {
  user?: { name?: string; email?: string };
  workspace?: { name?: string };
  plan?: { id?: string; name?: string };
};

type Member = { id: string; name?: string; email?: string; role?: string };
type Invitation = { id: string; email: string; status: string; role?: string };

const ORDER = ["free", "professional", "team", "network", "enterprise"];

function canonicalPlan(value: unknown) {
  const raw = String(value || "free").toLowerCase();
  const aliases: Record<string, string> = { pilot: "free", pro: "professional", waterops: "professional", assurance_audit: "professional", assurance: "team" };
  return aliases[raw] || raw;
}

function value(value: unknown, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function Row({ label, value: rowValue }: { label: string; value: unknown }) {
  return <div className="flex items-center justify-between gap-6 border-t py-3 text-[13px]" style={{ borderColor: BORDER }}><span style={{ color: MUTED }}>{label}</span><span className="text-right font-medium" style={{ color: TEXT }}>{value(rowValue)}</span></div>;
}

function Panel({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return <section className="rounded-xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="mb-4 flex items-center justify-between gap-4"><h2 className="text-[18px] font-semibold" style={{ color: TEXT }}>{title}</h2>{action}</div>{children}</section>;
}

export function TeamPageV2() {
  const { currentOrganization, currentWorkspace } = useAuth();
  const shellState = usePortalResource<ShellResponse>(useCallback(() => apiClient.product.shell(), []));
  const membersState = usePortalResource<{ members: Member[] }>(useCallback(() => apiClient.team.members(), []));
  const invitationsState = usePortalResource<{ invitations: Invitation[] }>(useCallback(() => apiClient.team.invitations(), []));
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"owner" | "admin" | "manager" | "operator" | "viewer">("operator");
  const [message, setMessage] = useState("");

  const currentPlan = canonicalPlan(currentOrganization?.plan || shellState.data?.plan?.id);
  const canInvite = ORDER.indexOf(currentPlan) >= ORDER.indexOf("team");

  function openTeamWall() {
    openCommercialBoundary({
      status: 402,
      code: "upgrade_required",
      feature: "team.invite",
      recommended_plan: "team",
      message: "Team unlocks direct invitations, role controls, shared operating access, and approval workflows for multi-user field operations.",
      source: "team",
    });
  }

  async function sendInvite() {
    if (!inviteEmail.trim()) return;
    if (!canInvite) {
      openTeamWall();
      return;
    }
    try {
      const response = await apiClient.team.invite({ email: inviteEmail.trim(), role: inviteRole }) as Record<string, unknown>;
      setMessage(String(response.message || "Invitation sent."));
      setInviteEmail("");
      await invitationsState.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Invitation could not be sent.");
    }
  }

  return <div className="min-h-screen" style={{ background: BG }}>
    <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
      <div className="flex items-start justify-between gap-6"><div><div className="mb-3 flex items-center gap-2"><Users className="h-5 w-5 text-[#2D6A4F]" /><span className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[#2D6A4F]">Team operations</span></div><h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Team</h1><p className="mt-2 max-w-3xl text-[14px] leading-7" style={{ color: MUTED }}>Invite teammates, assign operational roles, and coordinate shared evidence and approvals from one workspace.</p></div></div>
    </header>

    <main className="space-y-5 px-8 py-6" style={{ maxWidth: 1240 }}>
      {message ? <div className="rounded-lg border border-[#BBF7D0] bg-[#F0FDF4] px-4 py-3 text-[13px] text-[#15803D]">{message}</div> : null}
      {!canInvite ? <section className="rounded-2xl border border-[#CFE1CB] bg-[#F0F7EE] p-5">
        <div className="flex flex-wrap items-center justify-between gap-4"><div className="flex items-start gap-3"><div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#DDEB8F] text-[#10231B]"><Lock className="h-4 w-4" /></div><div><div className="text-[14px] font-semibold text-[#10231B]">Direct collaboration starts on Team</div><p className="mt-1 max-w-2xl text-[12px] leading-6 text-[#65736A]">Keep the workflow visible, but upgrade when you are ready for direct invitations, 10 included seats, role controls, shared evidence, and approvals.</p></div></div><PortalButton onClick={openTeamWall}>Compare Team access</PortalButton></div>
      </section> : null}

      <Panel title="Current access">
        <Row label="Name" value={shellState.data?.user?.name} />
        <Row label="Email" value={shellState.data?.user?.email} />
        <Row label="Workspace" value={shellState.data?.workspace?.name} />
        <Row label="Plan" value={shellState.data?.plan?.name || currentPlan} />
      </Panel>

      <Panel title="Invite teammate" action={<PortalButton disabled={!inviteEmail.trim()} onClick={sendInvite}>{canInvite ? "Send invitation" : "Unlock Team invites"}</PortalButton>}>
        <div className="grid gap-4 md:grid-cols-[1fr_220px]">
          <label className="text-[12px]" style={{ color: MUTED }}>Email<input value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} placeholder="teammate@company.com" /></label>
          <label className="text-[12px]" style={{ color: MUTED }}>Role<select value={inviteRole} onChange={(event) => setInviteRole(event.target.value as typeof inviteRole)} className="mt-1 h-10 w-full rounded-lg px-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}><option value="owner">Owner</option><option value="admin">Admin</option><option value="manager">Manager</option><option value="operator">Operator</option><option value="viewer">Viewer</option></select></label>
        </div>
      </Panel>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Members"><div className="space-y-2">{(membersState.data?.members || []).map((member) => <Row key={member.id} label={value(member.name || member.email)} value={member.role} />)}{membersState.error ? <p className="text-[13px]" style={{ color: MUTED }}>{membersState.error}</p> : null}{!membersState.data?.members?.length ? <p className="text-[13px]" style={{ color: MUTED }}>No team members loaded yet.</p> : null}</div></Panel>
        <Panel title="Invitations"><div className="space-y-2">{(invitationsState.data?.invitations || []).map((row) => <Row key={row.id} label={row.email} value={row.status} />)}{invitationsState.error ? <p className="text-[13px]" style={{ color: MUTED }}>{invitationsState.error}</p> : null}{!invitationsState.data?.invitations?.length ? <p className="text-[13px]" style={{ color: MUTED }}>No invitations yet.</p> : null}</div></Panel>
      </div>
    </main>
  </div>;
}
