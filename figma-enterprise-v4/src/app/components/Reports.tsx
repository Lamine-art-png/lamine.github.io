import { useCallback, useState } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { arrayFromUnknown, canUseEntitlement, usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type Report = { id?: string; title?: string; name?: string; status?: string; description?: string };

export function Reports() {
  const { currentOrganization, currentWorkspace, entitlements } = useAuth();
  const [exportMessage, setExportMessage] = useState("");
  const reports = usePortalResource<unknown>(useCallback(() => apiClient.reports.list(), []));
  const rows = arrayFromUnknown<Report>(reports.data, ["reports", "items", "data"]);
  const canExport = canUseEntitlement(entitlements, ["report_exports", "reports", "can_export_reports"]);

  async function exportReport(report?: Report) {
    setExportMessage("");
    if (!canExport) {
      setExportMessage("Report export requires paid plan.");
      return;
    }
    try {
      await apiClient.reports.export({ report_id: report?.id, workspace_id: currentWorkspace?.id });
      setExportMessage("Report export requested.");
    } catch (error) {
      setExportMessage(error instanceof Error ? error.message : "Report generation backend not connected yet.");
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="h-[72px] px-8 flex items-center justify-between" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div>
          <div className="text-[13px] font-semibold" style={{ color: TEXT }}>{currentWorkspace?.name || "Reports workspace"}</div>
          <div className="text-[11px]" style={{ color: MUTED }}>{currentOrganization?.name || "Organization"}</div>
        </div>
        <StatusBadge label={canExport ? "Export enabled" : "Report export requires paid plan"} tone={canExport ? "good" : "locked"} />
      </header>

      <div className="px-8 py-6 space-y-5" style={{ maxWidth: 1220 }}>
        <div>
          <h1 className="text-[28px] font-semibold mb-1" style={{ color: TEXT }}>Reports</h1>
          <p className="text-[13px]" style={{ color: MUTED }}>Live report records and export access for this workspace.</p>
        </div>

        {!canExport ? <InlineState title="Report export requires paid plan." /> : null}
        {reports.isLoading ? <InlineState title="Loading reports" /> : null}
        {reports.isUnavailable ? <InlineState title="Report generation backend not connected yet." detail="Report cards remain unavailable until a live reports endpoint is available." /> : null}
        {!reports.isUnavailable && reports.error ? <InlineState title={reports.error} /> : null}
        {exportMessage ? <InlineState title={exportMessage} /> : null}

        <div className="grid grid-cols-2 gap-4">
          {rows.length ? rows.map((report, index) => (
            <article key={report.id || index} className="rounded-xl p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              <div className="flex items-start justify-between gap-4 mb-3">
                <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>{report.title || report.name || "Report"}</h3>
                <StatusBadge label={report.status || "draft"} />
              </div>
              <p className="text-[13px] leading-relaxed mb-4" style={{ color: MUTED }}>{report.description || "Description not returned by backend."}</p>
              <PortalButton disabled={!canExport || reports.isUnavailable} onClick={() => exportReport(report)}>
                {canExport ? "Export" : "Report export requires paid plan"}
              </PortalButton>
            </article>
          )) : (
            <article className="rounded-xl p-6 col-span-2" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              <InlineState title="No live reports returned." detail={reports.isUnavailable ? "Report generation backend not connected yet." : "Report cards will appear after the backend returns report records."} />
            </article>
          )}
        </div>
      </div>
    </div>
  );
}
