import { demoAuditLog } from "../demoData.js";
import { formatDate } from "../components/dom.js";
import { table } from "../components/ui.js";

export function renderAuditLog(state) {
  const liveEvents = [
    { time: new Date().toISOString(), actor: "Portal", event: "user logged in", source: "Auth-ready scaffold", detail: "Customer login requires backend auth before production use." },
    { time: new Date().toISOString(), actor: "Integration service", event: "environment connected", source: "WiseConn runtime", detail: state.live.auth?.ok ? "WiseConn status endpoint returned." : "WiseConn status check limited." },
    { time: new Date().toISOString(), actor: "Integration service", event: "environment connected", source: "Talgil runtime", detail: state.live.integrations.find((item) => item.name === "Talgil")?.status || "Talgil status check pending." },
    { time: new Date().toISOString(), actor: "Intelligence Engine", event: "recommendation generated", source: "WiseConn zone 162803", detail: state.live.recommendation ? "Live recommendation generated." : "Awaiting live recommendation request." },
  ];
  const events = state.session.mode === "demo" ? demoAuditLog : liveEvents;
  return `<div class="screen-stack"><section class="panel-card"><div class="section-heading"><p class="eyebrow">Audit Log</p><h2>Operational evidence trail</h2><p>Demo events and live session events are shown as an enterprise audit preview. Persisted customer audit history requires backend administration endpoints.</p></div>${table(
    ["Time", "Actor", "Event", "Source", "Detail"],
    events.map((event) => [formatDate(event.time), event.actor, event.event, event.source, event.detail]),
    "No audit events",
    "Audit events will appear when a session has activity."
  )}</section></div>`;
}
