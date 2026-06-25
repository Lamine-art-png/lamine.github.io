<<<<<<< ours
import { useCallback } from "react";
=======
import { useCallback, useState } from "react";
>>>>>>> theirs
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { arrayFromUnknown, usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type EvidenceItem = {
  id?: string;
  name?: string;
  filename?: string;
  source?: string;
  domain?: string;
  status?: string;
  confidence?: string | number;
};

export function Evidence() {
  const { currentOrganization, currentWorkspace } = useAuth();
<<<<<<< ours
  const evidence = usePortalResource<unknown>(useCallback(() => apiClient.evidence.list(), []));
  const rows = arrayFromUnknown<EvidenceItem>(evidence.data, ["evidence", "items", "data", "records"]);

=======
  const [aiMessage, setAiMessage] = useState("");
  const [isAiLoading, setIsAiLoading] = useState(false);
  const evidence = usePortalResource<unknown>(useCallback(() => apiClient.evidence.list(), []));
  const rows = arrayFromUnknown<EvidenceItem>(evidence.data, ["evidence", "items", "data", "records"]);

  async function reviewEvidence() {
    setAiMessage("");
    setIsAiLoading(true);
    try {
      const result = await apiClient.ai.assuranceReview({
        workspace_id: currentWorkspace?.id,
        inputs: { source: "evidence" },
      }) as { status?: string; demo_fallback?: boolean };
      setAiMessage(result.status === "unavailable" || result.demo_fallback ? "AI provider unavailable." : "Evidence review returned.");
    } catch (error) {
      setAiMessage(error instanceof Error ? error.message : "AI evidence review endpoint unavailable.");
    } finally {
      setIsAiLoading(false);
    }
  }

>>>>>>> theirs
  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="h-[72px] px-8 flex items-center justify-between" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div>
          <div className="text-[13px] font-semibold" style={{ color: TEXT }}>{currentWorkspace?.name || "Evidence workspace"}</div>
          <div className="text-[11px]" style={{ color: MUTED }}>{currentOrganization?.name || "Organization"}</div>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge label={evidence.isUnavailable ? "Backend route unavailable" : "Live evidence"} tone={evidence.isUnavailable ? "warn" : "good"} />
<<<<<<< ours
=======
          <PortalButton disabled={isAiLoading || evidence.isUnavailable} onClick={reviewEvidence}>{isAiLoading ? "Reviewing" : "AI Review"}</PortalButton>
>>>>>>> theirs
          <PortalButton disabled>Upload route not connected yet</PortalButton>
        </div>
      </header>

      <div className="px-8 py-6 space-y-5" style={{ maxWidth: 1220 }}>
        <div>
          <h1 className="text-[28px] font-semibold mb-1" style={{ color: TEXT }}>Evidence</h1>
          <p className="text-[13px]" style={{ color: MUTED }}>Live evidence records returned by the backend. Missing routes render as unavailable, not as sample proof.</p>
        </div>

        {evidence.isLoading ? <InlineState title="Loading evidence" /> : null}
<<<<<<< ours
=======
        {isAiLoading ? <InlineState title="Loading AI evidence review" /> : null}
        {aiMessage ? <InlineState title={aiMessage} /> : null}
>>>>>>> theirs
        {evidence.isUnavailable ? <InlineState title="Evidence backend route not connected yet." detail="Evidence rows will appear after a live evidence list endpoint is available." /> : null}
        {!evidence.isUnavailable && evidence.error ? <InlineState title={evidence.error} /> : null}

        <section className="rounded-xl overflow-hidden" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>Evidence vault</div>
            <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>Field records and source files</h3>
          </div>
          <div className="grid px-6 py-2.5 gap-4" style={{ gridTemplateColumns: "1.3fr 1.2fr 1fr auto auto", borderBottom: `1px solid ${BORDER}`, background: BG }}>
            {["Evidence", "Source", "Proof domain", "Status", "Confidence"].map((header) => (
              <span key={header} className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{header}</span>
            ))}
          </div>
          {rows.length ? (
            rows.map((row, index) => (
              <div key={row.id || index} className="grid px-6 py-4 gap-4 items-center" style={{ gridTemplateColumns: "1.3fr 1.2fr 1fr auto auto", borderTop: index > 0 ? `1px solid ${BORDER}` : "none" }}>
                <span className="text-[13px] font-medium" style={{ color: TEXT }}>{row.name || "Evidence item"}</span>
                <span className="text-[12px]" style={{ color: MUTED }}>{row.filename || row.source || "Source not returned"}</span>
                <span className="text-[12px]" style={{ color: MUTED }}>{row.domain || "Domain unavailable"}</span>
                <StatusBadge label={row.status || "received"} tone={row.status === "verified" ? "good" : "neutral"} />
                <span className="text-[12px] font-medium" style={{ color: TEXT }}>{row.confidence === undefined ? "Unavailable" : String(row.confidence)}</span>
              </div>
            ))
          ) : (
            <div className="p-6">
              <InlineState title="No evidence records returned." detail="Proof source, domain, status, and confidence will appear only when live evidence exists." />
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
