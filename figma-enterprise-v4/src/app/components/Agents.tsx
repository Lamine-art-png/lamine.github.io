import { useCallback, useState } from "react";
import { ArrowRight } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { arrayFromUnknown, usePortalResource } from "../hooks/usePortalResource";
import { openCommercialBoundary } from "./CommercialBoundaryHost";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type AgentRun = { id?: string; task?: string; status?: string; created_at?: string; summary?: string };

function capabilityEnabled(entitlements: Record<string, unknown>, key: string) {
  const capabilities = entitlements.capabilities;
  if (capabilities && typeof capabilities === "object" && !Array.isArray(capabilities)) {
    const value = (capabilities as Record<string, unknown>)[key];
    return value === true || value === "enabled" || value === "preview";
  }
  return entitlements[key] === true;
}

export function Agents() {
  const { currentOrganization, currentWorkspace, entitlements } = useAuth();
  const [runMessage, setRunMessage] = useState("");
  const [runningTask, setRunningTask] = useState("");
  const runs = usePortalResource<unknown>(useCallback(() => apiClient.agents.list(), []));
  const rows = arrayFromUnknown<AgentRun>(runs.data, ["runs", "items", "data"]);
  const canRunAgent = capabilityEnabled(entitlements, "agents.execute_safe");

  function showUpgrade() {
    openCommercialBoundary({ status: 402, code: "upgrade_required", feature: "agents.execute_safe", recommended_plan: "professional", message: "Agent execution is included in Professional and above.", source: "agents" });
  }

  async function runAgent(task: string) {
    setRunMessage("");
    if (!canRunAgent) { showUpgrade(); return; }
    try {
      setRunningTask(task);
      const result = await apiClient.agents.run({ task, workspace_id: currentWorkspace?.id }) as { status?: string; demo_fallback?: boolean };
      setRunMessage(result.status === "unavailable" || result.demo_fallback ? "Agent run returned in safe mode." : "Agent run returned.");
      await runs.refresh();
    } catch (error) {
      setRunMessage(error instanceof Error ? error.message : "Agent orchestration endpoint not connected yet.");
    } finally {
      setRunningTask("");
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="h-[72px] px-8 flex items-center justify-between" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div><div className="text-[13px] font-semibold" style={{ color: TEXT }}>{currentWorkspace?.name || "Agent workspace"}</div><div className="text-[11px]" style={{ color: MUTED }}>{currentOrganization?.name || "Organization"}</div></div>
        {canRunAgent ? <PortalButton disabled={runs.isUnavailable} onClick={() => runAgent("gap_analysis")}>{runs.isUnavailable ? "Agent orchestration endpoint not connected yet" : "Run Agent"}</PortalButton> : <PortalButton onClick={showUpgrade}>Upgrade to run agents <ArrowRight className="h-4 w-4" /></PortalButton>}
      </header>

      <div className="px-8 py-6 space-y-5" style={{ maxWidth: 1220 }}>
        <div><h1 className="text-[28px] font-semibold mb-1" style={{ color: TEXT }}>Agents</h1><p className="text-[13px]" style={{ color: MUTED }}>Commercially controlled agent runs for the active workspace.</p></div>
        {!canRunAgent ? <button type="button" onClick={showUpgrade} className="w-full text-left"><InlineState title="Agent execution requires Professional or above." detail="Open the upgrade path to unlock safe agent execution and plan-specific run capacity." /></button> : null}
        {runs.isLoading ? <InlineState title="Loading agent runs" /> : null}
        {runningTask ? <InlineState title={`Running ${runningTask.replaceAll("_", " ")}`} /> : null}
        {runs.isUnavailable ? <InlineState title="Agent orchestration endpoint not connected yet." /> : null}
        {!runs.isUnavailable && runs.error ? <InlineState title={runs.error} /> : null}
        {runMessage ? <InlineState title={runMessage} /> : null}

        <div className="grid gap-5" style={{ gridTemplateColumns: "3fr 2fr" }}>
          <section className="rounded-xl overflow-hidden" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}><div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>Recent runs</div><h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>Agent run history</h3></div>
            <div className="p-6 space-y-3">{rows.length ? rows.map((run, index) => <div key={run.id || index} className="flex items-center justify-between rounded-lg px-4 py-3" style={{ background: BG, border: `1px solid ${BORDER}` }}><div><div className="text-[13px] font-medium" style={{ color: TEXT }}>{run.task || "Agent run"}</div><div className="text-[11px]" style={{ color: MUTED }}>{run.summary || run.created_at || "No summary returned"}</div></div><StatusBadge label={run.status || "queued"} /></div>) : <InlineState title="No recent agent runs returned." detail={runs.isUnavailable ? "Agent orchestration endpoint not connected yet." : "Runs will appear after the backend returns run records."} />}</div>
          </section>

          <section className="rounded-xl overflow-hidden" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}><div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>Actions</div><h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>Agent actions</h3></div>
            <div className="grid gap-3 p-5">{["gap_analysis", "proof_draft", "readiness_refresh", "irrigation_recommendation", "integration_diagnosis"].map((task) => <button key={task} type="button" disabled={runs.isUnavailable || Boolean(runningTask)} onClick={() => canRunAgent ? runAgent(task) : showUpgrade()} className="text-left rounded-xl p-4 transition-colors disabled:cursor-not-allowed disabled:opacity-60" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="text-[13px] font-semibold mb-1" style={{ color: TEXT }}>{task.replaceAll("_", " ")}</div><div className="text-[11px] leading-relaxed" style={{ color: MUTED }}>{!canRunAgent ? "Professional required — click to upgrade." : runningTask === task ? "Running against live AI gateway." : runs.isUnavailable ? "Agent orchestration endpoint not connected yet." : "Send this action to the live agent endpoint."}</div></button>)}</div>
          </section>
        </div>
      </div>
    </div>
  );
}
