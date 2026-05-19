import { demoFarms } from "../demoData.js";
import { operatingChain, table } from "../components/ui.js";

export function renderVerification(state) {
  const isDemo = state.session.mode === "demo";
  const runtime = state.demoRuntime;
  const rows = isDemo
    ? [[
        runtime.activeFarm.name,
        runtime.activeZone.name,
        runtime.operatingChain[1]?.evidence || "Awaiting schedule",
        runtime.operatingChain[2]?.evidence || "Awaiting controller execution",
        runtime.operatingChain[3]?.evidence || "Awaiting field observation",
        runtime.operatingChain[4]?.status || "Verification pending",
        runtime.activeZone.warning,
      ], ...demoFarms.flatMap((farm) => farm.zones.filter((zone) => zone.id !== runtime.activeZone.id).map((zone) => [farm.name, zone.name, zone.scheduledStatus, zone.appliedStatus, zone.observedOutcome, zone.verificationStatus, zone.warning]))]
    : [["Live WiseConn", window.AGROAI_PORTAL_CONFIG?.liveWiseConnZoneId || "162803", "Awaiting schedule", "Awaiting controller execution", "Awaiting field observation", "Verification pending", "Generate live recommendation first."]];
  const chain = isDemo
    ? runtime.operatingChain
    : [
        { label: "Recommended", status: state.live.recommendation ? "Complete" : "Pending", timestamp: "", owner: "AGRO-AI Intelligence Engine", evidence: state.live.recommendation ? "Live recommendation generated." : "Generate recommendation." },
        { label: "Scheduled", status: "Awaiting schedule", owner: "Irrigation Manager", evidence: "Awaiting schedule" },
        { label: "Applied", status: "Awaiting controller execution", owner: "Controller Runtime", evidence: "Awaiting controller execution" },
        { label: "Observed", status: "Awaiting field observation", owner: "Field Team", evidence: "Awaiting field observation" },
        { label: "Verified", status: "Verification pending", owner: "AGRO-AI Verification", evidence: "Verification pending" },
      ];
  return `<div class="screen-stack">${operatingChain(chain)}<section class="panel-card"><div class="section-heading"><p class="eyebrow">Verification</p><h2>Evidence and next actions</h2><p>AGRO-AI tracks whether the recommendation was scheduled, applied, observed, and verified.</p></div>${isDemo ? '<div class="runtime-actions"><button class="button secondary" data-action="schedule" type="button">Schedule</button><button class="button secondary" data-action="mark-applied" type="button">Mark applied</button><button class="button secondary" data-action="add-observation" type="button">Add observation</button><button class="button primary" data-action="verify" type="button">Verify outcome</button></div>' : ""}${table(
    ["Farm", "Zone", "Scheduled", "Applied", "Observed", "Verified", "Warning"],
    rows,
    "No verification rows",
    "Verification rows appear as decisions move through the operating chain."
  )}</section></div>`;
}
