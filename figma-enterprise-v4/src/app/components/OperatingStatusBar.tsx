import { useCallback, useState } from "react";
import { apiClient } from "../api/client";
import { usePortalResource } from "../hooks/usePortalResource";
import { BORDER, PortalButton, StatusBadge, SURFACE, TEXT, MUTED } from "./portalUi";

type AnyRecord = Record<string, any>;

function asArray(value: unknown): AnyRecord[] {
  return Array.isArray(value) ? (value as AnyRecord[]) : [];
}

function value(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

export function OperatingStatusBar() {
  const [running, setRunning] = useState(false);
  const briefState = usePortalResource<AnyRecord>(useCallback(() => apiClient.intelligence.brief(), []));
  const brief = briefState.data || {};
  const workspace = (brief.workspace || {}) as AnyRecord;
  const field = (brief.field_state || {}) as AnyRecord;
  const telemetry = (brief.telemetry_status || {}) as AnyRecord;
  const water = (brief.water_status || {}) as AnyRecord;
  const assurance = (brief.assurance_status || {}) as AnyRecord;
  const integrations = asArray(brief.integration_status);

  const missingConnectorCount = integrations.filter((item) => {
    const status = String(item.status || "");
    return status.includes("missing") || status.includes("required") || status.includes("not_configured");
  }).length;

  async function runDecision() {
    setRunning(true);
    try {
      await apiClient.intelligence.action({
        action: "irrigation_plan",
        payload: {
          surface: "global_status_bar",
          workspace_id: workspace.id,
          block_id: field.block_id,
        },
      });
      await briefState.refresh();
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="sticky top-0 z-20 px-6 py-3" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <StatusBadge label={brief.mode === "live" ? "Live" : "Demo mode"} tone={brief.mode === "live" ? "good" : "warn"} />
          <div className="min-w-0">
            <div className="truncate text-[13px] font-semibold" style={{ color: TEXT }}>
              {value(workspace.name, "Workspace")} · {value(field.name || field.crop_type, "Field")}
            </div>
            <div className="truncate text-[11px]" style={{ color: MUTED }}>
              {value(telemetry.record_count, 0)} records · {missingConnectorCount} connectors pending · Water {value(water.used_pct, "—")}% · Assurance {value(assurance.score, "—")}%
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <PortalButton variant="secondary" onClick={() => window.location.assign("/intelligence")}>
            Ask AGRO-AI
          </PortalButton>
          <PortalButton onClick={runDecision} disabled={running}>
            {running ? "Running…" : "Run decision"}
          </PortalButton>
        </div>
      </div>
    </div>
  );
}
