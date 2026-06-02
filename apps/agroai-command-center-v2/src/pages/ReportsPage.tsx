import { useCommandStore } from "../state/commandStore";
import { Card, Metric } from "../components/PagePrimitives";
export function ReportsPage() { const report = useCommandStore((s) => s.report); return <main className="page"><h1>Reports</h1><Card title="Operational report"><Metric label="Farm" value={report.farm}/><Metric label="Recommendation" value={report.recommendation}/><Metric label="Evidence" value={report.evidenceCompleteness}/><Metric label="Verification" value={report.verification}/></Card></main>; }
