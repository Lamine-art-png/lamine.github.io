import { MouseEvent as ReactMouseEvent } from "react";
import { FileText, Lock } from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { openCommercialBoundary } from "./CommercialBoundaryHost";
import { Reports } from "./Reports";

const ORDER = ["free", "professional", "team", "network", "enterprise"];
function plan(value: unknown) {
  const raw = String(value || "free").toLowerCase();
  const aliases: Record<string, string> = { pilot: "free", pro: "professional", waterops: "professional", assurance_audit: "professional", assurance: "team" };
  return aliases[raw] || raw;
}

export function MonetizedReportsV2() {
  const { currentOrganization } = useAuth();
  const locked = ORDER.indexOf(plan(currentOrganization?.plan)) < ORDER.indexOf("professional");

  function openWall(exportAction = false) {
    openCommercialBoundary({
      status: 402,
      code: "upgrade_required",
      feature: exportAction ? "reports.pdf_export" : "reports.generate",
      recommended_plan: "professional",
      message: exportAction
        ? "Professional unlocks PDF exports and document-ready report delivery."
        : "Professional unlocks evidence summaries, operating briefs, compliance drafts, and commercial report generation.",
      source: "reports",
    });
  }

  function capture(event: ReactMouseEvent<HTMLDivElement>) {
    if (!locked) return;
    const button = (event.target as HTMLElement).closest("button");
    if (!button) return;
    const label = button.textContent?.trim() || "";
    if (label === "Refresh") return;
    event.preventDefault();
    event.stopPropagation();
    openWall(/download|pdf/i.test(label));
  }

  return <div onClickCapture={capture}>
    {locked ? <div className="mx-8 mt-6 rounded-2xl border border-[#CFE1CB] bg-[#F0F7EE] p-5 text-[#1F5A43]"><div className="flex flex-wrap items-center justify-between gap-4"><div className="flex items-start gap-3"><div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#DDEB8F] text-[#10231B]"><Lock className="h-4 w-4" /></div><div><div className="flex items-center gap-2 text-[12px] font-semibold"><FileText className="h-4 w-4" />Commercial reporting starts on Professional</div><p className="mt-1 max-w-3xl text-[11px] leading-5 opacity-80">Explore the workflow, then unlock generation, PDF export, compliance drafts, and delivery.</p></div></div><button type="button" onClick={() => openWall(false)} className="h-10 rounded-xl bg-[#0D2B1E] px-4 text-[12px] font-semibold text-white">Compare Professional access</button></div></div> : null}
    <Reports />
  </div>;
}
