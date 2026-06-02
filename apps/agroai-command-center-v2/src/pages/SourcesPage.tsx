import { useCommandStore } from "../state/commandStore";
import { Card } from "../components/PagePrimitives";
export function SourcesPage() { const sources = useCommandStore((s) => s.sources); return <main className="page"><h1>Sources</h1><div className="grid">{sources.map((s) => <Card key={s.source} title={s.source}><p>{s.latestSignal}</p><p>{s.records} records · {s.status}</p></Card>)}</div></main>; }
