import { useCommandStore } from "../state/commandStore";
import { Card } from "../components/PagePrimitives";
export function IntegrationsPage() { const backend = useCommandStore((s) => s.backend); return <main className="page"><h1>Integrations</h1><div className="grid"><Card title="WiseConn"><p>Live-source wiring preserved through backend Workbench calls.</p></Card><Card title="Talgil"><p>Runtime diagnostics remain backend-owned.</p></Card><Card title="Backend health"><p>{backend.detail}</p></Card></div></main>; }
