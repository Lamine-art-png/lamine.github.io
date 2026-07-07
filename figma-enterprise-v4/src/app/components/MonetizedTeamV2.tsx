import { MouseEvent as ReactMouseEvent } from "react";
import { Lock } from "lucide-react";
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

  function openWall() {
    openCommercialBoundary({
      status: 402,
      code: "upgrade_required",
      feature: "team.invite",
      recommended_plan: "team",
      message: "Team unlocks direct invitations, role controls, shared operating access, and approval workflows.",
      source: "team",
    });
  }

  function capture(event: ReactMouseEvent<HTMLDivElement>) {
    if (!locked) return;
    const button = (event.target as HTMLElement).closest("button");
    if (!button || !/request invite|send invitation/i.test(button.textContent || "")) return;
    event.preventDefault();
    event.stopPropagation();
    openWall();
  }

  return <div onClickCapture={capture}>
    {locked ? <div className="mx-8 mt-6 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[#CFE1CB] bg-[#F0F7EE] p-5 text-[#1F5A43]"><div className="flex items-start gap-3"><div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#DDEB8F] text-[#10231B]"><Lock className="h-4 w-4" /></div><div><div className="text-[13px] font-semibold">Direct collaboration starts on Team</div><p className="mt-1 max-w-2xl text-[11px] leading-5 opacity-80">Unlock direct invitations, role controls, shared evidence, approvals, and 10 included seats.</p></div></div><button type="button" onClick={openWall} className="h-10 rounded-xl bg-[#0D2B1E] px-4 text-[12px] font-semibold text-white">Compare Team access</button></div> : null}
    <TeamPage />
  </div>;
}
