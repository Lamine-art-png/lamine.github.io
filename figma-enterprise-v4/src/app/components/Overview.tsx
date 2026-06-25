import { useCallback } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { arrayFromUnknown, canUseEntitlement, usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, GREEN, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type Workspace = { id?: string; name?: string; crop?: string; region?: string; status?: string };
type AgentRun = { id?: string; status?: string };
type EvidenceItem = { id?: string };

export function Overview() {
  const { user, currentOrganization, currentWorkspace, entitlements, refreshMe } = useAuth();
  const loadWorkspaces = useCallback(() => apiClient.workspaces.list(), []);
  const loadEvidence = useCallback(() => apiClient.evidence.list(), []);
  const loadAgents = useCallback(() => apiClient.agents.list(), []);
  const workspaces = usePortalResource<unknown>(loadWorkspaces);
  const evidence = usePortalResource<unknown>(loadEvidence);
  const agents = usePortalResource<unknown>(loadAgents);
  const workspaceRows = arrayFromUnknown<Workspace>(workspaces.data, ["workspaces", "items", "data"]);
  const evidenceRows = arrayFromUnknown<EvidenceItem>(evidence.data, ["evidence", "items", "data"]);
  const agentRows = arrayFromUnknown<AgentRun>(agents.data, ["runs", "items", "data"]);
  const canRunAgent = canUseEntitlement(entitlements, ["agent_runs", "agents", "can_run_agents"]);
  const canExport = canUseEntitlement(entitlements, ["report_exports", "reports", "can_export_reports"]);

  async function refreshWorkspace() {
    await Promise.all([refreshMe(), workspaces.refresh(), evidence.refresh(), agents.refresh()]);
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="h-[72px] px-8 flex items-center justify-between" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div>
          <div className="text-[13px] font-semibold" style={{ color: TEXT }}>
            {currentWorkspace?.name || currentOrganization?.name || "Workspace"}
          </div>
          <div className="text-[11px]" style={{ color: MUTED }}>
            {user?.email || "Authenticated session"}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge label="Live backend connected" tone="good" />
          <StatusBadge label={`${currentOrganization?.plan || "free"} plan`} />
          <PortalButton onClick={refreshWorkspace} variant="secondary">Refresh workspace</PortalButton>
          <PortalButton disabled={!canRunAgent}>
            {canRunAgent ? "Run Agent" : "Agent runs require paid plan"}
          </PortalButton>
        </div>
      </header>

      <div className="px-8 py-6 space-y-5" style={{ maxWidth: 1220 }}>
        <div className="grid gap-5" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <section className="rounded-xl p-7" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>
              AGRO-AI Enterprise Portal
            </div>
            <h2 className="text-[22px] font-semibold leading-snug mb-2" style={{ color: TEXT }}>
              Operational overview
            </h2>
            <p className="text-[13px] leading-relaxed mb-6" style={{ color: MUTED }}>
              Live account scope, workspace availability, evidence, reports, and agent access for this organization.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <MiniMetric label="Organization" value={currentOrganization?.name || "Unavailable"} />
              <MiniMetric label="Subscription" value={currentOrganization?.subscription_status || "inactive"} />
              <MiniMetric label="Workspace" value={currentWorkspace?.name || workspaceRows[0]?.name || "No live workspace data yet"} />
              <MiniMetric label="Role" value={currentOrganization?.role || "member"} />
            </div>
          </section>

          <section className="rounded-xl p-7" style={{ background: "#0D2B1E", border: "1px solid rgba(255,255,255,0.06)" }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: "rgba(155,216,75,0.65)" }}>
              Entitlement state
            </div>
            <h3 className="text-[16px] font-semibold leading-snug mb-2" style={{ color: "white" }}>
              {currentOrganization?.plan === "free" ? "Free plan limits paid workflows." : "Paid workflows are available when subscription is active."}
            </h3>
            <div className="space-y-3 mt-5">
              <DarkRow label="Agent runs" value={canRunAgent ? "Available" : "Requires paid plan"} />
              <DarkRow label="Report export" value={canExport ? "Available" : "Report export requires paid plan"} />
              <DarkRow label="Plan" value={currentOrganization?.plan || "free"} />
              <DarkRow label="Status" value={currentOrganization?.subscription_status || "inactive"} />
            </div>
          </section>
        </div>

        <div className="grid grid-cols-4 gap-4">
          <Metric label="Workspaces" value={workspaces.isLoading ? "…" : String(workspaceRows.length)} sub={workspaces.isUnavailable ? "Workspace route unavailable" : "Live workspace records"} />
          <Metric label="Evidence items" value={evidence.isLoading ? "…" : String(evidenceRows.length)} sub={evidence.isUnavailable ? "Evidence backend not connected yet" : "Live evidence records"} />
          <Metric label="Agent runs" value={agents.isLoading ? "…" : String(agentRows.length)} sub={agents.isUnavailable ? "Agent orchestration endpoint not connected yet" : "Recent live runs"} />
          <Metric label="Reports" value={canExport ? "Enabled" : "Locked"} sub={canExport ? "Export entitlement available" : "Report export requires paid plan"} />
        </div>

        {workspaces.error && workspaces.isUnavailable ? (
          <InlineState title="No live workspace data yet" detail="Create or connect a live workspace to populate operational views." />
        ) : workspaces.error ? (
          <InlineState title={workspaces.error} />
        ) : null}

        <section className="rounded-xl overflow-hidden" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>Workspace queue</div>
            <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>Live workspace status</h3>
          </div>
          <div className="p-6">
            {workspaceRows.length ? (
              <div className="grid gap-3">
                {workspaceRows.map((workspace, index) => (
                  <div key={workspace.id || index} className="flex items-center justify-between rounded-lg px-4 py-3" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                    <div>
                      <div className="text-[13px] font-medium" style={{ color: TEXT }}>{workspace.name || "Workspace"}</div>
                      <div className="text-[11px]" style={{ color: MUTED }}>{[workspace.crop, workspace.region].filter(Boolean).join(" · ") || "No crop or region returned"}</div>
                    </div>
                    <StatusBadge label={workspace.status || "evaluation"} />
                  </div>
                ))}
              </div>
            ) : (
              <InlineState title="No live workspace data yet" detail="Workspace metrics will appear after the backend returns workspace records." />
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="text-[11px] font-medium mb-1" style={{ color: MUTED }}>{label}</div>
      <div className="text-[13px] font-semibold" style={{ color: TEXT }}>{value}</div>
    </div>
  );
}

function Metric({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="text-[11px] font-medium mb-2.5" style={{ color: MUTED }}>{label}</div>
      <div className="text-[30px] font-semibold leading-none mb-2" style={{ color: TEXT }}>{value}</div>
      <div className="text-[11px]" style={{ color: MUTED }}>{sub}</div>
    </div>
  );
}

function DarkRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-4 items-start">
      <span className="text-[11px] font-medium flex-shrink-0 pt-px" style={{ color: "rgba(255,255,255,0.35)", width: 108 }}>{label}</span>
      <span className="text-[12px]" style={{ color: "rgba(255,255,255,0.7)" }}>{value}</span>
    </div>
  );
}
