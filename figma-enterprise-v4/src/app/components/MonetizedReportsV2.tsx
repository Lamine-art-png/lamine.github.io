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
        ? "Professional turns AGRO-AI output into exportable, document-ready work your team can actually deliver."
        : "Professional turns live evidence into reusable reports, decision briefs, compliance drafts, and PDF-ready output.",
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
