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
      <ExecutiveStrip />

      <div className="command-grid">
        <div className="command-main">
          <SourceIntelligence />
          <DecisionPipeline />
          <AnalysisTrace />
        </div>
        <div className="command-rail">
          <VerifiedDecision />
          <EvidenceChain />
        </div>
      </div>

      <div className="command-foot">
        <ReconciliationTable />
        <ExecutiveReportPreview />
      </div>
    </div>
  );
}
