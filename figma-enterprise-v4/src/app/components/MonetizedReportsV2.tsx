import { MouseEvent as ReactMouseEvent, useEffect, useRef } from "react";
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
  const opened = useRef(false);

  function openWall(exportAction = false) {
    openCommercialBoundary({
      status: 402,
      code: "upgrade_required",
      feature: exportAction ? "reports.pdf_export" : "reports.generate",
      recommended_plan: "professional",
      message: exportAction
        ? "Professional turns your AGRO-AI work into polished, exportable PDFs your team can deliver to growers, partners, auditors, and decision-makers. Stay on Free and the final packaging, delivery, and repeatable reporting work remains manual."
        : "Professional turns live evidence into reusable decision briefs, compliance drafts, operating reports, and PDF-ready output. Stay on Free and your team keeps rebuilding summaries by hand, formatting documents outside AGRO-AI, and losing time between evidence and action.",
      source: "reports",
    });
  }

  useEffect(() => {
    if (!locked || opened.current) return;
    opened.current = true;
    const timer = window.setTimeout(() => openWall(false), 80);
    return () => window.clearTimeout(timer);
  }, [locked]);

  function capture(event: ReactMouseEvent<HTMLDivElement>) {
    if (!locked) return;
    const button = (event.target as HTMLElement).closest("button");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    openWall(/download|pdf/i.test(button.textContent || ""));
  }

  return <div onClickCapture={capture}><Reports /></div>;
}
