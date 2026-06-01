import { API_BASE } from "../api/client";
import { ProviderStatusList } from "../components/ProviderStatusList";
import { BackendBadge } from "../components/StatusBadge";
import { useCommandStore } from "../state/commandStore";

export function SettingsPage() {
  const backend = useCommandStore((s) => s.backend);
  return (
    <div className="stack">
      <section className="card panel">
        <p className="eyebrow">Settings</p>
        <h2>Workspace and backend</h2>
        <dl className="brief-def">
          <div>
            <dt>Environment</dt>
            <dd>Evaluation workspace · representative data</dd>
          </div>
          <div>
            <dt>API base</dt>
            <dd>
              <code className="identifier">{API_BASE}</code>
            </dd>
          </div>
          <div>
            <dt>Backend status</dt>
            <dd>
              <BackendBadge status={backend.status} detail={backend.detail} />
            </dd>
          </div>
          <div>
            <dt>Backend detail</dt>
            <dd className="value">{backend.detail}</dd>
          </div>
        </dl>
      </section>

      <section className="card panel">
        <p className="eyebrow">Provider runtime</p>
        <h2>Dynamic integration status</h2>
        <ProviderStatusList />
      </section>

      <section className="card panel">
        <p className="eyebrow">Known limitations</p>
        <h2>Evaluation transparency</h2>
        <ul className="limitations">
          <li>Workbench sessions are evaluation session storage only (in-memory); tenant persistence is future work.</li>
          <li>Production authentication, credential vault, and tenant provisioning are server-side follow-ups.</li>
          <li>Representative recommendations are evaluation fallbacks and are labelled as such.</li>
          <li>Live recommendations degrade safely when provider telemetry is unavailable.</li>
        </ul>
      </section>
    </div>
  );
}
