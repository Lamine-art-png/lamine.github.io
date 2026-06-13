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
  const selectedFarm = useCommandStore((s) => s.selectedFarm);
  const selectedBlock = useCommandStore((s) => s.selectedBlock);
  const availableFarms = useCommandStore((s) => s.availableFarms);
  const availableBlocksByFarm = useCommandStore((s) => s.availableBlocksByFarm);
  const scopeDefaulted = useCommandStore((s) => s.scopeDefaulted);
  const scopeDefaultedFarm = useCommandStore((s) => s.scopeDefaultedFarm);
  const scopeDefaultedBlock = useCommandStore((s) => s.scopeDefaultedBlock);
  const scopeSelectionPending = useCommandStore((s) => s.scopeSelectionPending);
  const packageAwaitingAnalysis = useCommandStore((s) => s.packageAwaitingAnalysis);
  const resultStale = useCommandStore((s) => s.resultStale);
  const [menuOpen, setMenuOpen] = useState(false);

  const farmName = displayFarmName;
  const currentScenarioLabel = SCENARIO_OPTIONS.find((s) => s.id === scenarioId)?.name ?? "Validated operating block";
  const evidenceDone = evidence.filter((s) => s.status === "Complete").length;
  const evidenceTotal = evidence.length;
  const emptyPackage =
    packageAwaitingAnalysis ||
    (resultStale && recommendationOrigin === "insufficient_context" && displayFarmName === "No package loaded");
  const sourceState = emptyPackage
    ? "Awaiting source package"
    : resultStale || scopeSelectionPending
    ? "Prior result stale"
    : analysisPhase === "complete"
    ? "Sources reconciled"
    : "Analyzing sources";
  const sourceTone = emptyPackage || resultStale || scopeSelectionPending
    ? "warn"
    : analysisPhase === "complete"
    ? "ok"
    : "warn";
  const provenance = getProvenanceBadge(analysisMode, recommendationOrigin);

  // Show scope selectors whenever the backend has provided customer-safe available scopes.
  // Hide only for a true local offline representative fallback (representationOrigin_fallback with no backend scopes).
  const showScopeSelectors = availableFarms.length > 0 && recommendationOrigin !== "representative_fallback";
  // Block selector only enabled after farm is selected. Never flatten blocks across farms before selection.
  const availableBlocks = selectedFarm ? (availableBlocksByFarm[selectedFarm] ?? []) : [];

  function handleFarmChange(farm: string) {
    actions.setSelectedFarm(farm || null);
  }

  function handleBlockChange(block: string) {
    actions.setSelectedBlock(block || null);
    // Immediately trigger re-analysis when a block is selected.
    if (block) {
      void actions.reanalyzeSelectedScope();
    }
  }

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

        {showScopeSelectors && (
          <div className="scope-selector-row" aria-label="Farm and block scope selection">
            <label className="scope-selector" title="Select farm">
              <span className="scope-selector-label">Farm</span>
              <select
                aria-label="Select farm"
                value={selectedFarm ?? ""}
                onChange={(e) => handleFarmChange(e.target.value)}
              >
                <option value="">{scopeDefaulted ? "Defaulted (no selection)" : "Select farm…"}</option>
                {availableFarms.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
            </label>
            <label className="scope-selector" title="Select block">
              <span className="scope-selector-label">Block</span>
              <select
                aria-label="Select block"
                value={selectedBlock ?? ""}
                onChange={(e) => handleBlockChange(e.target.value)}
                disabled={!selectedFarm || availableBlocks.length === 0}
              >
                <option value="">
                  {selectedFarm ? "Select block…" : "Select farm first"}
                </option>
                {availableBlocks.map((b) => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
            </label>
            {scopeDefaulted && !selectedFarm && (
              <span className="scope-default-disclosure" role="note">
                {scopeDefaultedFarm && scopeDefaultedBlock
                  ? `Analysis defaulted to ${scopeDefaultedFarm} / ${scopeDefaultedBlock}. Select farm and block for precise analysis.`
                  : "Analysis defaulted to first available scope. Select farm and block for precise analysis."}
              </span>
            )}
            {scopeSelectionPending && selectedFarm && (
              <span className="scope-default-disclosure scope-pending-note" role="alert">
                Prior decision is stale. Select a block and analyze to update.
              </span>
            )}
          </div>
        )}

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
          {selectedFarm && selectedBlock && !scopeSelectionPending && (
            <StatusBadge label={`Scope: ${selectedFarm} / ${selectedBlock}`} tone="ok" />
          )}
          {scopeSelectionPending && (
            <StatusBadge label="Scope selection pending — select block to analyze" tone="warn" />
          )}
        </div>
      </div>
    </header>
  );
}
