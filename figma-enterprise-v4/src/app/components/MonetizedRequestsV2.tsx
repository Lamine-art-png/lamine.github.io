import { MouseEvent as ReactMouseEvent, useEffect, useRef } from "react";
import { useAuth } from "../auth/AuthProvider";
import { openCommercialBoundary } from "./CommercialBoundaryHost";
import { AdminRequestsPage } from "./ProductShell";

const ORDER = ["free", "professional", "team", "network", "enterprise"];

function plan(value: unknown) {
  const raw = String(value || "free").toLowerCase();
  const aliases: Record<string, string> = { pilot: "free", pro: "professional", waterops: "professional", assurance_audit: "professional", assurance: "team" };
  return aliases[raw] || raw;
}

export function MonetizedRequestsV2() {
  const { currentOrganization } = useAuth();
  const locked = ORDER.indexOf(plan(currentOrganization?.plan)) < ORDER.indexOf("team");
  const opened = useRef(false);

  function openWall() {
    openCommercialBoundary({
      status: 402,
      code: "upgrade_required",
      feature: "admin.requests",
      recommended_plan: "team",
      message: "Team gives operators one tracked request inbox for support, onboarding, integrations, upgrades, ownership, and follow-through. Stay below Team and important requests remain scattered across email and ad hoc follow-ups, making delays, duplicate work, and missed handoffs much more likely.",
      source: "requests",
    });
  }

  useEffect(() => {
    if (!locked || opened.current) return;
    opened.current = true;
    const timer = window.setTimeout(openWall, 80);
    return () => window.clearTimeout(timer);
  }, [locked]);

  function capture(event: ReactMouseEvent<HTMLDivElement>) {
    if (!locked) return;
    const interactive = (event.target as HTMLElement).closest("button, a, input, select, textarea");
    if (!interactive) return;
    event.preventDefault();
    event.stopPropagation();
    openWall();
  }

  return <div onClickCapture={capture}><AdminRequestsPage /></div>;
}
