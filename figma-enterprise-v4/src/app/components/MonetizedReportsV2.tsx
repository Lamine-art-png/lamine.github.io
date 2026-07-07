import { MouseEvent as ReactMouseEvent } from "react";
import { FileText, Lock } from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { openCommercialBoundary } from "./CommercialBoundaryHost";
import { Reports } from "./Reports";

const ORDER = ["free", "professional", "team", "network", "enterprise"];

function canonicalPlan(value: unknown) {
  const raw = String(value || "free").toLowerCase();
  const aliases: Record<string, string> = { pilot: "free", pro: "professional", waterops: "professional", assurance_audit: "professional", assurance: "team" };
  return aliases[raw] || raw;
}

export function MonetizedReportsV2() {
  const { currentOrganization } = useAuth();
  const currentPlan = canonicalPlan(currentOrganization?.plan);
  const canUseReports = ORDER.indexOf(currentPlan) >= ORDER.indexOf("professional");

  function capture(event: ReactMouseEvent<HTMLDivElement>) {
    if (canUseReports) return;
    const button = (event.target as HTMLElement).closest("button");
    if (!button) return;
    const label = button.textContent?.trim() || "";
    if (label === "Refresh") return;

    event.preventDefault();
    event.stopPropagation();
    const isExport = /download|pdf/i.test(label);
    openCommercialBoundary({
      status: 402,
      code: "upgrade_required",
      feature: isExport ? "reports.pdf_export" : "reports.generate",
      recommended_plan: "professional",
      message: isExport
        ? "Professional unlocks PDF exports and document-ready report delivery from the current evidence workspace."
        : "Professional unlocks evidence summaries, operating briefs, compliance drafts, and commercial report generation.",
      source: "reports",
    });
  }

  return <div onClickCapture={capture}>
    {!canUseReports ? <div className="mx-8 mt-6 rounded-2xl border border-[#CFE1CB] bg-[#F0F7EE] p-5 text-[#1F5A43]">
      <div className="flex flex-wrap items-center justify-between gap-4"><div className="flex items-start gap-3"><div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#DDEB8F] text-[#10231B]"><Lock className="h-4 w-4" /></div><div><div className="flex items-center gap-2 text-[12px] font-semibold"><FileText className="h-4 w-4" />Commercial reporting starts on Professional</div><p className="mt-1 max-w-3xl text-[11px] leading-5 opacity-80">Explore the report workflow, then unlock generation, PDF export, compliance drafts, and delivery with the full contextual upgrade path.</p></div></div><button type="button" onClick={() => openCommercialBoundary({ status: 402, code: "upgrade_required", feature: "reports.generate", recommended_plan: "professional", message: "Professional unlocks commercial report generation, PDF exports, compliance drafts, and report delivery.", source: "reports" })} className="h-10 rounded-xl bg-[#0D2B1E] px-4 text-[12px] font-semibold text-white">Compare Professional access</button></div>
    </div> : null}
    <Reports />
  </div>;
}
