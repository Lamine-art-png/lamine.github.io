import { actions } from "../state/commandStore";
import { SourceIntelligence } from "../components/SourceIntelligence";

export function SourcesPage() {
  return (
    <div className="stack">
      <section className="card panel">
        <div className="panel-head">
          <div>
            <p className="eyebrow">Sources</p>
            <h2>Connected systems, uploaded records, and partner signals</h2>
          </div>
          <button className="btn primary compact" onClick={() => actions.openDrawer()}>
            Add or manage sources
          </button>
        </div>
        <p className="muted">
          Source setup opens in a focused drawer: connect a controller, upload records through the Workbench route, review API
          access, or authorize partner feeds. Representative records remain active until production targets are connected.
        </p>
      </section>
      <SourceIntelligence />
    </div>
  );
}
