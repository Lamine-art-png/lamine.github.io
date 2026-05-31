import { actions, SCENARIO_OPTIONS, useCommandStore } from "../state/commandStore";
import type { ScenarioId } from "../state/commandStore";

export function WorkspaceSwitcher() {
  const scenarioId = useCommandStore((s) => s.scenarioId);
  return (
    <label className="workspace-switcher" title="Switch evaluation workspace">
      <span className="visually-hidden">Evaluation workspace</span>
      <select
        aria-label="Evaluation workspace"
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
  );
}
