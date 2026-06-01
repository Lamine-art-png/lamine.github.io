import { useCommandStore } from "../state/commandStore";

function fmt(ts: string): string {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString();
}

export function AuditPage() {
  const audit = useCommandStore((s) => s.audit);
  return (
    <div className="stack">
      <section className="card panel">
        <p className="eyebrow">Audit</p>
        <h2>Workspace activity</h2>
        <div className="table-scroll">
          <table className="recon-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Event</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((e, i) => (
                <tr key={`${e.time}-${i}`}>
                  <td className="value">{fmt(e.time)}</td>
                  <td className="value">{e.actor}</td>
                  <td className="value">{e.event}</td>
                  <td className="value">{e.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
