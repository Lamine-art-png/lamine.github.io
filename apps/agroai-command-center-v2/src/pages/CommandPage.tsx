import { ExecutiveStrip } from "../components/ExecutiveStrip";
import { SourceIntelligence } from "../components/SourceIntelligence";
import { DecisionPipeline } from "../components/DecisionPipeline";
import { AnalysisTrace } from "../components/AnalysisTrace";
import { VerifiedDecision } from "../components/VerifiedDecision";
import { EvidenceChain } from "../components/EvidenceChain";
import { ReconciliationTable } from "../components/ReconciliationTable";
import { ExecutiveReportPreview } from "../components/ExecutiveReportPreview";

export function CommandPage() {
  return (
    <div className="command-page">
      {/* Executive strip — today's key metrics */}
      <ExecutiveStrip />

      {/* Primary workspace — source intelligence + verified decision */}
      <div className="command-grid">
        <div className="command-main">
          <SourceIntelligence />
        </div>
        <div className="command-rail">
          <VerifiedDecision />
        </div>
      </div>

      {/* Supporting workspace — processing, evidence chain, report */}
      <div className="command-support">
        <div className="command-support-left">
          <DecisionPipeline />
          <ReconciliationTable />
        </div>
        <div className="command-support-right">
          <EvidenceChain />
          <ExecutiveReportPreview />
        </div>
      </div>

      {/* Technical trace — collapsed by default */}
      <AnalysisTrace />
    </div>
  );
}
