import type { DecisionOutput } from "./decision";

export interface EvidenceTableRow {
  signal: string;
  value: string;
  interpretation: string;
}

export interface RiskTableRow {
  flag: string;
  status: boolean;
  interpretation: string;
}

export interface ReportObject {
  report_id: string;
  decision_id: string;
  title: string;
  field_summary: string;
  recommendation_summary: string;
  evidence_table: EvidenceTableRow[];
  risk_table: RiskTableRow[];
  water_savings_estimate: string;
  before_after_comparison: {
    baseline: string;
    recommended: string;
    difference: string;
  };
  next_actions: string[];
  pdf_ready_sections: {
    executive_summary: string;
    advisor_note: string;
    grower_message: string;
    technical_appendix: string;
  };
  api_payload_reference: {
    decision_id: string;
    field_id: string;
    endpoint: string;
  };
  audit_reference: {
    decision_id: string;
    audit_endpoint: string;
  };
}

export interface LLMReportPayload {
  executive_summary: string;
  decision_explanation: string;
  risk_interpretation: string;
  recommended_next_actions: string[];
  limitations: string;
  commercial_demo_narrative: string;
}

export function emptyReportFromDecision(decision: DecisionOutput): ReportObject {
  return {
    report_id: crypto.randomUUID(),
    decision_id: decision.decision_id,
    title: `AGRO-AI Irrigation Decision Report - ${decision.field_id}`,
    field_summary: decision.field_id,
    recommendation_summary: decision.rationale.executive_summary,
    evidence_table: [],
    risk_table: [],
    water_savings_estimate: decision.reporting.projected_water_savings,
    before_after_comparison: {
      baseline: "Baseline schedule not supplied.",
      recommended: decision.reporting.operational_note,
      difference: decision.reporting.projected_water_savings,
    },
    next_actions: [],
    pdf_ready_sections: {
      executive_summary: decision.rationale.executive_summary,
      advisor_note: decision.reporting.advisor_note,
      grower_message: decision.reporting.grower_facing_message,
      technical_appendix: decision.rationale.agronomic_reasoning,
    },
    api_payload_reference: {
      decision_id: decision.decision_id,
      field_id: decision.field_id,
      endpoint: `/api/v1/decisions/${decision.decision_id}`,
    },
    audit_reference: {
      decision_id: decision.decision_id,
      audit_endpoint: `/api/v1/decisions/${decision.decision_id}/audit`,
    },
  };
}

