import { useCommandStore } from "../state/commandStore";
export function AuditPage() { const audit = useCommandStore((s) => s.audit); return <main className="page"><h1>Audit</h1><div className="card"><ul>{audit.map((a) => <li key={`${a.time}-${a.event}`}><strong>{a.event}</strong> — {a.detail} <span>{a.time}</span></li>)}</ul></div></main>; }
