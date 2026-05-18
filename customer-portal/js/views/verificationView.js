import { demoChain, demoFarms } from "../demoData.js";
import { operatingChain, table } from "../components/ui.js";

export function renderVerification(state) {
  const isDemo = state.session.mode === "demo";
  const rows = isDemo
    ? demoFarms.flatMap((farm) => farm.zones.map((zone) => [farm.name, zone.name, zone.scheduledStatus, zone.appliedStatus, zone.observedOutcome, zone.verificationStatus, zone.warning]))
    : [["Live WiseConn", window.AGROAI_PORTAL_CONFIG?.liveWiseConnZoneId || "162803", "Awaiting schedule", "Awaiting controller execution", "Awaiting field observation", "Verification pending", "Generate live recommendation first."]];
  const chain = isDemo
    ? demoChain
    : [
        { label: "Recommended", status: state.live.recommendation ? "Complete" : "Pending", timestamp: "", owner: "AGRO-AI Intelligence Engine", evidence: state.live.recommendation ? "Live recommendation generated." : "Generate recommendation." },
        { label: "Scheduled", status: "Awaiting schedule", owner: "Irrigation Manager", evidence: "Awaiting schedule" },
        { label: "Applied", status: "Awaiting controller execution", owner: "Controller Runtime", evidence: "Awaiting controller execution" },
        { label: "Observed", status: "Awaiting field observation", owner: "Field Team", evidence: "Awaiting field observation" },
        { label: "Verified", status: "Verification pending", owner: "AGRO-AI Verification", evidence: "Verification pending" },
      ];
  return `<div class="screen-stack">${operatingChain(chain)}<section class="panel-card"><div class="section-heading"><p class="eyebrow">Verification</p><h2>Evidence and next actions</h2></div>${table(
    ["Farm", "Zone", "Scheduled", "Applied", "Observed", "Verified", "Warning"],
    rows,
    "No verification rows",
    "Verification rows appear as decisions move through the operating chain."
  )}</section></div>`;
}
