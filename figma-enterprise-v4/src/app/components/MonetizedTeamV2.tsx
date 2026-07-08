import { MouseEvent as ReactMouseEvent, useEffect, useRef } from "react";
import { useAuth } from "../auth/AuthProvider";
import { openCommercialBoundary } from "./CommercialBoundaryHost";
import { TeamPage } from "./ProductShell";

const ORDER = ["free", "professional", "team", "network", "enterprise"];

function plan(value: unknown) {
  const raw = String(value || "free").toLowerCase();
  const aliases: Record<string, string> = { pilot: "free", pro: "professional", waterops: "professional", assurance_audit: "professional", assurance: "team" };
  return aliases[raw] || raw;
}

export function MonetizedTeamV2() {
  const { currentOrganization } = useAuth();
  const current = plan(currentOrganization?.plan);
  const locked = ORDER.indexOf(current) < ORDER.indexOf("team");
  const opened = useRef(false);

  function openWall() {
    openCommercialBoundary({
      status: 402,
      code: "upgrade_required",
      feature: "team.invite",
      recommended_plan: "team",
      message: "Team turns individual AGRO-AI work into coordinated operations with invitations, roles, shared evidence, and approvals.",
      source: "team",
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
    const interactive = (event.target as HTMLElement).closest("button, a, input, select");
    if (!interactive) return;
    event.preventDefault();
    event.stopPropagation();
    openWall();
  }

  return <div onClickCapture={capture}><TeamPage /></div>;
}
