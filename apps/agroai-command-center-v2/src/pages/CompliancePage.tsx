import { useEffect, useMemo, useState } from "react";
import { createComplianceExport, downloadComplianceExport, loadComplianceWorkspace, saveBlob, type ComplianceExportMetadata } from "../api/complianceClient";

const DISCLAIMER = "AGRO-AI prepares reporting-readiness evidence only. It does not provide legal advice, certify measurement methods, guarantee compliance, file with regulators, or imply regulator endorsement.";

type AnyRecord = Record<string, any>;

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="card compliance-card"><h2>{title}</h2>{children}</section>;
}

export default function CompliancePage() {
  const [state, setState] = useState<{ loading: boolean; error: string; data: AnyRecord | null; exportError: string; lastExport: ComplianceExportMetadata | null }>({ loading: true, error: "", data: null, exportError: "", lastExport: null });

  useEffect(() => {
    let active = true;
    loadComplianceWorkspace()
      .then((data) => active && setState((prev) => ({ ...prev, loading: false, data, error: "" })))
      .catch((error) => active && setState((prev) => ({ ...prev, loading: false, error: error.message || "Compliance API unavailable" })));
    return () => { active = false; };
  }, []);

  const status = (state.data?.status || {}) as AnyRecord;
  const readiness = (state.data?.readiness || status.readiness || {}) as AnyRecord;
  const jurisdiction = (status.jurisdictions || readiness.upcoming_deadlines || [])[0] || {};
  const deadlineItems = status.jurisdictions || readiness.upcoming_deadlines || [];
  const warnings = readiness.warnings || [];
  const anomalies = readiness.unresolved_anomalies || [];

  const meterHealth = useMemo(() => {
    const stale = warnings.filter((warning: AnyRecord) => warning.code === "stale_calibration").length;
    return `${stale} stale calibration warning${stale === 1 ? "" : "s"}`;
  }, [warnings]);

  async function exportPackage(exportType: string) {
    setState((prev) => ({ ...prev, exportError: "" }));
    try {
      const metadata = await createComplianceExport(exportType, readiness.workflow_type);
      const download = await downloadComplianceExport(metadata.id);
      saveBlob(download.blob, download.fileName);
      setState((prev) => ({ ...prev, lastExport: metadata, exportError: "" }));
    } catch (error: any) {
      setState((prev) => ({ ...prev, exportError: error.message || "Export failed" }));
    }
  }

  if (state.loading) return <main className="page compliance-page"><p>Loading compliance readiness from the AGRO-AI API…</p></main>;
  if (state.error) return <main className="page compliance-page"><h1>Compliance</h1><p className="warning">Compliance API unavailable: {state.error}</p><p>{DISCLAIMER}</p></main>;

  return <main className="page compliance-page">
    <header className="hero compliance-hero">
      <p className="eyebrow">Compliance</p>
      <h1>{readiness.readiness_percentage ?? "—"}% · {readiness.readiness_status || "unknown"}</h1>
      <p>{readiness.next_required_action || "No next action returned by the compliance API."}</p>
      <div className="actions compliance-actions">
        {["json", "csv", "xlsx", "pdf"].map((type) => <button key={type} type="button" onClick={() => exportPackage(type)}>Export {type.toUpperCase()}</button>)}
      </div>
      {state.exportError ? <p className="warning">{state.exportError}</p> : null}
      {state.lastExport ? <p className="muted">Latest export: {state.lastExport.file_name} · {state.lastExport.checksum_sha256}</p> : null}
    </header>
    <div className="grid compliance-grid">
      <Card title="Jurisdiction and reporting period"><p>{jurisdiction.country_code || "—"} · {jurisdiction.admin_area_1 || jurisdiction.state || "—"} · {jurisdiction.admin_area_2 || jurisdiction.county || "—"}</p><p>{jurisdiction.authority_name || jurisdiction.gsa || "No authority returned"}</p><p>{jurisdiction.workflow_type || readiness.workflow_type || "No workflow returned"} · {jurisdiction.reporting_year || "—"}</p></Card>
      <Card title="Water-budget status"><p>{(state.data?.waterBudgets || []).length} budget record(s)</p><p>{warnings.filter((warning: AnyRecord) => warning.code === "water_budget_threshold_alert").length} threshold warning(s)</p></Card>
      <Card title="Recommendation-to-application reconciliation"><p>{(state.data?.reconciliation || []).length} reconciliation chain record(s)</p></Card>
      <Card title="Well and meter health"><p>{(state.data?.meters || []).length} meter record(s)</p><p>{meterHealth}</p></Card>
      <Card title="Missing evidence"><ul>{(readiness.missing_evidence || []).map((item: string) => <li key={item}>{item}</li>)}{!(readiness.missing_evidence || []).length ? <li>No missing evidence returned.</li> : null}</ul></Card>
      <Card title="Anomalies"><ul>{anomalies.map((item: AnyRecord) => <li key={`${item.code}-${item.reconciliation_id}`}>{item.code}: {item.variance_pct}</li>)}{!anomalies.length ? <li>No unresolved anomalies returned.</li> : null}</ul></Card>
      <Card title="Deadlines"><ul>{deadlineItems.map((item: AnyRecord) => <li key={item.id || item.workflow_type}>{item.workflow_type}: {item.reporting_deadline}</li>)}{!deadlineItems.length ? <li>No deadlines returned.</li> : null}</ul></Card>
      <Card title="Audit trail"><ul>{(state.data?.auditLog || []).map((item: AnyRecord) => <li key={item.id}>{item.timestamp}: {item.event}</li>)}{!(state.data?.auditLog || []).length ? <li>No audit entries returned.</li> : null}</ul></Card>
    </div>
    <p className="compliance-disclaimer">{status.disclaimer || DISCLAIMER}</p>
  </main>;
}
