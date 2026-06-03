import { useState } from "react";
import { actions, useCommandStore, SCENARIO_OPTIONS, getProvenanceBadge } from "../state/commandStore";
import type { ScenarioId } from "../state/commandStore";
import { BackendBadge, StatusBadge } from "./StatusBadge";

export function Header() {
  const scenarioId = useCommandStore((s) => s.scenarioId);
  const backend = useCommandStore((s) => s.backend);
  const analysisPhase = useCommandStore((s) => s.analysisPhase);
  const analysisMode = useCommandStore((s) => s.analysisMode);
  const recommendationOrigin = useCommandStore((s) => s.recommendationOrigin);
  const evidence = useCommandStore((s) => s.evidence);
  const displayFarmName = useCommandStore((s) => s.displayFarmName);
  const [menuOpen, setMenuOpen] = useState(false);

  const farmName = displayFarmName;
  const currentScenarioLabel = SCENARIO_OPTIONS.find((s) => s.id === scenarioId)?.name ?? "Validated operating block";
  const evidenceDone = evidence.filter((s) => s.status === "Complete").length;
  const evidenceTotal = evidence.length;
  const sourceState = analysisPhase === "complete" ? "Sources reconciled" : "Analyzing sources";
  const sourceTone = analysisPhase === "complete" ? "ok" : "warn";
  const provenance = getProvenanceBadge(analysisMode, recommendationOrigin);

  return (
    <header className="app-header">
      <div className="header-titleblock">
        <div className="header-top-row">
          <div className="header-farm-row">
            <h1 className="header-farm value">{farmName} · Water Command Center</h1>
            <div className="scenario-selector-wrap">
              <label className="scenario-selector" title="Switch evaluation scenario">
                <span className="visually-hidden">Evaluation scenario</span>
                <select
                  aria-label="Evaluation scenario"
                  value={scenarioId}
                  onChange={(e) => actions.switchScenario(e.target.value as ScenarioId)}
                >
                  {SCENARIO_OPTIONS.map((opt) => (
                    <option key={opt.id} value={opt.id}>
                      {opt.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          <div className="header-toolbar">
            <button className="btn compact" onClick={() => actions.startWalkthrough()}>
              Start guided walkthrough
            </button>
            <details className="user-menu" open={menuOpen} onToggle={(e) => setMenuOpen((e.target as HTMLDetailsElement).open)}>
              <summary aria-label="Account menu">
                <span className="avatar">OU</span>
              </summary>
              <div className="menu-panel" role="menu">
                <div className="menu-identity">
                  <strong>Operations user</strong>
                  <span>Evaluation workspace</span>
                </div>
                <a className="menu-item" href="mailto:support@agroai-pilot.com?subject=AGRO-AI%20Water%20Command%20Center">
                  Help
                </a>
              </div>
            </details>
          </div>
        </div>

        <p className="header-subtitle header-scenario-label">
          {currentScenarioLabel} · Scattered irrigation data becomes a verified water decision.
        </p>

        <div className="status-row" aria-label="Workspace status">
          <BackendBadge status={backend.status} detail={backend.detail} />
          <StatusBadge label={provenance.label} tone={provenance.tone} />
          <StatusBadge label={sourceState} tone={sourceTone} />
          <StatusBadge
            label={`Evidence chain ${evidenceDone}/${evidenceTotal}`}
            tone={evidenceDone === evidenceTotal ? "ok" : "neutral"}
          />
          {scenarioId === "incomplete-evidence" && (
            <StatusBadge label="Evidence review mode" tone="warn" />
          )}
        </div>
      </div>
    </header>
  );
}
