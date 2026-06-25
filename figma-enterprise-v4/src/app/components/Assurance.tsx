import { useCallback, useState } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { arrayFromUnknown, canUseEntitlement, usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type ProofGap = { requirement?: string; domain?: string; reason?: string; status?: string };

export function Assurance() {
  const { currentOrganization, currentWorkspace, entitlements } = useAuth();
  const [agentMessage, setAgentMessage] = useState("");
  const [isAiLoading, setIsAiLoading] = useState(false);
  const readiness = usePortalResource<unknown>(useCallback(() => apiClient.assurance.readiness(), []));
  const passport = usePortalResource<unknown>(useCallback(() => apiClient.assurance.passport(), []));
  const gaps = arrayFromUnknown<ProofGap>(readiness.data, ["gaps", "missing_proof", "items"]);
  const canRunAgent = canUseEntitlement(entitlements, ["agent_runs", "agents", "can_run_agents"]);

  async function runAgent() {
    setAgentMessage("");
    setIsAiLoading(true);
    try {
      const result = await apiClient.ai.assuranceReview({
        workspace_id: currentWorkspace?.id,
        inputs: { source: "assurance" },
      }) as { status?: string; demo_fallback?: boolean; output?: unknown };
      setAgentMessage(result.status === "unavailable" || result.demo_fallback ? "AI provider unavailable." : "Assurance review returned.");
    } catch (error) {
      setAgentMessage(error instanceof Error ? error.message : "AI assurance endpoint unavailable.");
    } finally {
      setIsAiLoading(false);
    }
  }

  const hasPassport = Boolean(passport.data && !passport.isUnavailable);

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="h-[72px] px-8 flex items-center justify-between" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div>
          <div className="text-[13px] font-semibold" style={{ color: TEXT }}>{currentWorkspace?.name || "Assurance workspace"}</div>
          <div className="text-[11px]" style={{ color: MUTED }}>{currentOrganization?.name || "Organization"}</div>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge label={hasPassport ? "Live passport" : "No live passport"} tone={hasPassport ? "good" : "warn"} />
          <PortalButton disabled={!canRunAgent || readiness.isUnavailable || isAiLoading} onClick={runAgent}>
            {!canRunAgent ? "Agent runs require paid plan" : isAiLoading ? "Reviewing" : readiness.isUnavailable ? "Assurance route unavailable" : "AI Review"}
          </PortalButton>
        </div>
      </header>

      <div className="px-8 py-6 space-y-5" style={{ maxWidth: 1220 }}>
        <div>
          <h1 className="text-[28px] font-semibold mb-1" style={{ color: TEXT }}>Assurance</h1>
          <p className="text-[13px]" style={{ color: MUTED }}>Live assurance readiness and passport state for the active workspace.</p>
        </div>

        {passport.isLoading || readiness.isLoading ? <InlineState title="Loading assurance state" /> : null}
        {isAiLoading ? <InlineState title="Loading AI assurance review" /> : null}
        {passport.isUnavailable ? (
          <InlineState
            title="No live assurance passport connected yet."
            detail="Create or connect a live Assurance Passport to unlock proof workflows."
          />
        ) : passport.error ? (
          <InlineState title={passport.error} />
        ) : null}
        {agentMessage ? <InlineState title={agentMessage} /> : null}

        <div className="grid grid-cols-4 gap-4">
          <Metric label="Readiness" value={readiness.data && typeof readiness.data === "object" && "readiness" in readiness.data ? `${String((readiness.data as Record<string, unknown>).readiness)}%` : "Unavailable"} />
          <Metric label="Missing proof" value={String(gaps.length)} />
          <Metric label="Passport" value={hasPassport ? "Connected" : "Not connected"} />
          <Metric label="Reviewer gate" value="Required" />
        </div>

        <section className="rounded-xl overflow-hidden" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>Gap analysis</div>
            <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>Live missing proof queue</h3>
          </div>
          <div className="p-6">
            {gaps.length ? (
              <div className="grid gap-3">
                {gaps.map((gap, index) => (
                  <div key={index} className="grid gap-4 px-4 py-3 rounded-lg items-center" style={{ gridTemplateColumns: "1.5fr 1fr 2fr auto", background: BG, border: `1px solid ${BORDER}` }}>
                    <span className="text-[13px] font-medium" style={{ color: TEXT }}>{gap.requirement || "Proof requirement"}</span>
                    <span className="text-[12px]" style={{ color: MUTED }}>{gap.domain || "Domain unavailable"}</span>
                    <span className="text-[12px]" style={{ color: MUTED }}>{gap.reason || "Reason not returned"}</span>
                    <StatusBadge label={gap.status || "missing"} tone="warn" />
                  </div>
                ))}
              </div>
            ) : (
              <InlineState title="No live assurance passport connected yet." detail="Create or connect a live Assurance Passport to unlock proof workflows." />
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="text-[11px] font-medium mb-2.5" style={{ color: MUTED }}>{label}</div>
      <div className="text-[26px] font-semibold leading-none" style={{ color: TEXT }}>{value}</div>
    </div>
  );
}
