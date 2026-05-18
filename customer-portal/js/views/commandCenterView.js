import { demoFarms } from "../demoData.js";
import { escapeHtml } from "../components/dom.js";
import { metricCard, operatingChain, recommendationProofCard, table, technicalTrace } from "../components/ui.js";

function liveChainFromState(state) {
  const now = state.live.recommendation ? new Date().toISOString() : "";
  return [
    { label: "Recommended", status: state.live.recommendation ? "Complete" : "Data source pending", timestamp: now, owner: "AGRO-AI Intelligence Engine", evidence: state.live.recommendation ? "Live recommendation generated for WiseConn zone 162803." : "Generate live recommendation." },
    { label: "Scheduled", status: "Awaiting schedule", timestamp: "", owner: "Irrigation Manager", evidence: "Awaiting schedule" },
    { label: "Applied", status: "Awaiting controller execution", timestamp: "", owner: "Controller Runtime", evidence: "Awaiting controller execution" },
    { label: "Observed", status: "Awaiting field observation", timestamp: "", owner: "Field Team", evidence: "Awaiting field observation" },
    { label: "Verified", status: "Verification pending", timestamp: "", owner: "AGRO-AI Verification", evidence: "Verification pending" },
  ];
}

function commandCenterOnboarding() {
  const isDismissed = typeof sessionStorage !== "undefined" && sessionStorage.getItem("agroai-command-center-onboarding-dismissed") === "true";
  if (isDismissed) return "";

  const dismiss = "sessionStorage.setItem('agroai-command-center-onboarding-dismissed','true'); this.closest('.workspace-onboarding')?.remove();";
  return `<section class="workspace-onboarding" role="dialog" aria-labelledby="workspace-onboarding-title"><div><p class="eyebrow">Workspace orientation</p><h2 id="workspace-onboarding-title">How to read this workspace</h2><ul><li>Connected controller environment</li><li>Block-level recommendation</li><li>Scheduled and applied water</li><li>Field observation</li><li>Verification and report</li></ul></div><div class="onboarding-actions"><button class="button primary" data-action="start-guide" onclick="${dismiss}" type="button">Start walkthrough</button><button class="button secondary" onclick="${dismiss}" type="button">Don’t show again</button></div></section>`;
}

function sanitizeWorkspaceCopy(value) {
  return String(value ?? "")
    .replace(/WiseConn demo connection/g, "WiseConn pilot connection")
    .replace(/Talgil demo connection/g, "Talgil pilot connection")
    .replace(/demo controller window/g, "controller window")
    .replace(/Demo irrigation history/g, "Irrigation history")
    .replace(/Demo weather profile/g, "Weather profile")
    .replace(/Demo runtime state/g, "Workspace runtime state")
    .replace(/Embedded demo tenant/g, "Embedded tenant workspace");
}

function sanitizedRecommendation(recommendation = {}) {
  const copy = { ...recommendation };
  ["sourceTraceSummary", "source_trace_summary", "trace_summary", "executionTask", "execution_task", "task", "verificationPlan", "verification_plan"].forEach((key) => {
    if (copy[key]) copy[key] = sanitizeWorkspaceCopy(copy[key]);
  });
  ["keyDrivers", "key_drivers", "drivers", "reasons", "liveInputsUsed", "live_inputs_used", "inputs_used", "manualOverridesUsed", "manual_overrides_used", "overrides_used", "missingInputs"].forEach((key) => {
    if (Array.isArray(copy[key])) copy[key] = copy[key].map(sanitizeWorkspaceCopy);
  });
  return copy;
}

function operatingJourney(runtime) {
  const currentIndex = runtime.operatingChain.findIndex((step) => step.status !== "Complete");
  const activeIndex = currentIndex === -1 ? 5 : currentIndex;
  const steps = [
    ["Environment", "Current"],
    ["Recommendation", runtime.activeRecommendation ? "Complete" : activeIndex === 0 ? "Current" : "Pending"],
    ["Schedule", runtime.operatingChain[1]?.status || "Pending"],
    ["Applied water", runtime.operatingChain[2]?.status || "Pending"],
    ["Observation", runtime.operatingChain[3]?.status || "Pending"],
    ["Verification", runtime.operatingChain[4]?.status || "Pending"],
    ["Report", runtime.reportSnapshots?.length ? "Complete" : "Pending"],
  ];

  return `<section class="panel-card runtime-controls"><div class="section-heading"><p class="eyebrow">Operating Journey</p><h2>Today’s operating journey</h2><p>Scenario: ${escapeHtml(runtime.scenario.name)} · Current stage: ${escapeHtml(steps[Math.min(activeIndex + 1, steps.length - 1)]?.[0] || "Report")}</p></div><div class="guide-steps progress-strip" aria-label="Operating journey progress">${steps
    .map((step, index) => `<article class="${step[1] === "Complete" ? "complete" : index === activeIndex + 1 ? "current" : ""}"><span>${index + 1}</span><strong>${escapeHtml(step[0])}</strong><small>${escapeHtml(step[1])}</small></article>`)
    .join("")}</div><label class="scenario-picker">Scenario<select id="scenario-select">${["dry_day", "rain_wait", "partial_telemetry", "mismatch", "verified_success"].map((id) => `<option value="${id}" ${runtime.scenario.id === id ? "selected" : ""}>${escapeHtml({dry_day:"Dry day, irrigation recommended", rain_wait:"Rain forecast, wait recommended", partial_telemetry:"Partial telemetry, confidence reduced", mismatch:"Planned vs applied mismatch", verified_success:"Verification completed successfully"}[id])}</option>`).join("")}</select></label></section>`;
}

export function renderCommandCenter(state) {
  const isDemo = state.session.mode === "demo";
  const runtime = state.demoRuntime;
  const selectedFarm = runtime?.activeFarm;
  const selectedZone = runtime?.activeZone;
  const zones = demoFarms.flatMap((farm) => farm.zones.map((zone) => ({ ...zone, farm: farm.name })));
  const liveZones = [...state.live.zonesByFarm.values()].flat();
  const rawRecommendation = isDemo ? runtime.activeRecommendation || runtime.scenario.recommendation : state.live.recommendation;
  const recommendation = isDemo ? sanitizedRecommendation(rawRecommendation) : rawRecommendation;
  const chain = isDemo ? runtime.operatingChain.map((step) => ({ ...step, evidence: sanitizeWorkspaceCopy(step.evidence), owner: sanitizeWorkspaceCopy(step.owner) })) : liveChainFromState(state);
  const decision = recommendation?.decision || recommendation?.water_decision || recommendation?.recommendation || "Generate a live recommendation to populate the decision card.";
  const confidence = recommendation?.confidence || recommendation?.confidence_score || "Data source pending";
  const dataQuality = recommendation?.dataQuality || recommendation?.data_quality || "Awaiting telemetry";
  const demoRows = zones.map((zone) => [zone.farm, zone.name, sanitizeWorkspaceCopy(zone.controllerSource), zone.recommendation, zone.verificationStatus]);
  const liveRows = liveZones.slice(0, 8).map((zone) => ["Live WiseConn", zone.name || zone.id, "WiseConn", "Use Intelligence screen to generate", "Verification pending"]);

  return `<div class="screen-stack command-center-screen">
    ${isDemo ? commandCenterOnboarding() : ""}
    ${isDemo ? operatingJourney(runtime) : ""}
    <section class="hero-panel">
      <div><p class="eyebrow">Water Command Center</p><h2>${escapeHtml(decision)}</h2><p>${escapeHtml(
        isDemo ? "Recommendation, execution, and verification for connected irrigation environments." : "Live WiseConn environment available. Generate a live recommendation for zone 162803 from the Intelligence screen."
      )}</p></div>
      <div class="hero-metrics command-kpis">${metricCard("Farm / block", isDemo ? `${selectedFarm.name} · ${selectedZone.name}` : "WiseConn zone 162803")}${metricCard(
        "Controller source",
        isDemo ? sanitizeWorkspaceCopy(selectedZone.controllerSource) : "Live WiseConn"
      )}${metricCard("Today’s decision", decision)}${metricCard("Confidence", confidence)}${metricCard("Data quality", dataQuality)}${metricCard("Verification state", chain[4]?.status || "Verification pending")}</div>
    </section>
    ${recommendationProofCard(recommendation || {}, {
      label: isDemo ? "Today’s recommendation" : "Live recommendation proof",
      modeBadge: isDemo ? "Pilot telemetry" : state.live.recommendation ? "Live API output" : "Data source pending",
      badgeTone: isDemo ? "neutral" : state.live.recommendation ? "success" : "neutral",
      actions: isDemo ? true : "live-disabled",
    })}
    ${operatingChain(chain)}
    <section class="panel-card"><div class="section-heading"><p class="eyebrow">Workspace Activity</p><h2>${isDemo ? "Recent activity across portfolio" : "Live WiseConn operating view"}</h2></div>${table(
      ["Farm", "Zone", "Controller", "Latest recommendation", "Verification"],
      isDemo ? demoRows : liveRows,
      "No operating rows available",
      "Live farm and zone data will appear when the runtime returns farm context."
    )}</section>
    ${technicalTrace({
      source: isDemo ? "Embedded tenant workspace" : "Live API",
      sourceEntityId: isDemo ? selectedZone.id : "WiseConn zone 162803",
      contextOrigin: isDemo ? "Workspace runtime state" : "Live WiseConn recommendation endpoint",
      controllerProvider: isDemo ? sanitizeWorkspaceCopy(selectedZone.controllerSource) : "WiseConn",
      liveInputsUsed: isDemo ? recommendation.liveInputsUsed || [] : ["WiseConn zone 162803", "Live context endpoint when available"],
      manualOverridesUsed: isDemo ? recommendation.manualOverridesUsed || [] : [],
      telemetryUsed: isDemo ? ["Irrigation history", "Weather profile"] : ["Live WiseConn context"],
      warnings: isDemo ? recommendation.missingInputs || [] : [state.live.recommendationError].filter(Boolean),
    })}
  </div>`;
}
