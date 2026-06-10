import { useEffect, useState } from "react";
import { complianceEnabled, loadComplianceStatus, type ComplianceStatus } from "../api/complianceClient";
import "../styles/compliance.css";

export function CompliancePage() {
  const [status, setStatus] = useState<ComplianceStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<"idle" | "loading" | "ready" | "error">("idle");

  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    loadComplianceStatus()
      .then((payload) => {
        if (!cancelled) {
          setStatus(payload);
          setError(null);
          setPhase("ready");
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message);
          setPhase("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="page compliance-page">
      <section className="hero-panel compliance-hero">
        <p className="eyebrow">API-backed compliance kernel</p>
        <h1>Compliance readiness</h1>
        <p>
          This workspace fails closed unless compliance is explicitly enabled and a labeled non-production demo token is configured.
          Production browser tenant API keys are not supported.
        </p>
      </section>

      {!complianceEnabled && (
        <section className="panel compliance-warning">
          <h2>Compliance disabled</h2>
          <p>The compliance feature flag is off for this build.</p>
        </section>
      )}

      {phase === "loading" && <section className="panel">Loading compliance status from the API…</section>}

      {phase === "error" && (
        <section className="panel compliance-warning">
          <h2>Closed by default</h2>
          <p>{error}</p>
        </section>
      )}

      {status && (
        <section className="panel compliance-grid">
          <div>
            <p className="metric-label">Rule pack</p>
            <h2>{status.rule_pack?.jurisdiction ?? "Unknown"}</h2>
            <p>{status.rule_pack?.status}</p>
          </div>
          <div>
            <p className="metric-label">Readiness</p>
            <h2>{status.readiness?.readiness_percentage ?? 0}%</h2>
            <p>{status.readiness?.readiness_status}</p>
          </div>
          <div>
            <p className="metric-label">External validation</p>
            <h2>{status.rule_pack?.external_validation ? "Validated" : "Pending"}</h2>
            <p>Direct regulatory filing remains out of scope.</p>
          </div>
          <div className="compliance-span">
            <p className="metric-label">Disclaimer</p>
            <p>{status.readiness?.disclaimer}</p>
          </div>
        </section>
      )}
    </main>
  );
}
