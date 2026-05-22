import type { Env } from "../../lib/cloudflare/env";
import { generateLlmReportPayload } from "../../lib/llm/client";
import type { DecisionOutput } from "../../schemas/decision";
import type { LLMReportPayload, ReportObject } from "../../schemas/report";
import type { NormalizedSignalPack } from "../../schemas/signals";

export interface ReportBuildResult {
  decision_output: DecisionOutput;
  report_object: ReportObject;
  ai_review: {
    used_llm: boolean;
    model: string | null;
    fallback_used: boolean;
    objective: string;
  };
}

export async function buildReportObject(
  decision: DecisionOutput,
  pack: NormalizedSignalPack | null,
  env: Pick<Env, "AGROAI_LLM_API_KEY" | "AGROAI_LLM_MODEL">,
): Promise<ReportBuildResult> {
  const objective = "advisor_summary";
  const llmPayload = pack
    ? await generateLlmReportPayload(env, {
      normalized_signal_pack: pack,
      decision_output: decision,
      risk_flags: decision.risk_flags,
      confidence: decision.confidence,
      report_objective: objective,
      audience: "advisor",
    })
    : null;
  const payload = llmPayload ?? deterministicReportPayload(decision, pack);
  const decisionWithProse = applyReportPayload(decision, payload);

  return {
    decision_output: decisionWithProse,
    report_object: assembleReportObject(decisionWithProse, pack, payload),
    ai_review: {
      used_llm: Boolean(llmPayload),
      model: llmPayload ? env.AGROAI_LLM_MODEL || "claude-sonnet-4-6" : null,
      fallback_used: !llmPayload,
      objective,
    },
  };
}

export function deterministicReportPayload(decision: DecisionOutput, pack: NormalizedSignalPack | null): LLMReportPayload {
  const action = decision.recommendation.action.replace("_", " ");
  const priority = decision.recommendation.priority;
  const fieldName = pack?.spatial_context.field_name ?? decision.field_id;
  const riskNames = Object.entries(decision.risk_flags).filter(([, active]) => active).map(([name]) => name.replaceAll("_", " "));
  const moisture = pack?.confidence_inputs.component_scores.moisture_stress_score ?? 0;
  const et = pack?.confidence_inputs.component_scores.et_pressure_score ?? 0;

  return {
    executive_summary: `AGRO-AI recommends ${action} for ${fieldName} with ${priority} priority and ${decision.confidence.level} confidence.`,
    decision_explanation: `The deterministic engine weighed moisture stress (${moisture.toFixed(2)}), ET pressure (${et.toFixed(2)}), vegetation trend, anomaly severity, and weather risk. The recommendation preserves the computed timing and volume from the rules engine.`,
    risk_interpretation: riskNames.length ? `Active risks: ${riskNames.join(", ")}.` : "No material risk flags were triggered.",
    recommended_next_actions: nextActions(decision),
    limitations: decision.confidence.limitations.join(" ") || "No material limitation reported by the deterministic confidence scorer.",
    commercial_demo_narrative: "EarthDaily supplies the observation layer; AGRO-AI converts it into an irrigation decision, audit trace, and report-ready advisory output.",
  };
}

function applyReportPayload(decision: DecisionOutput, payload: LLMReportPayload): DecisionOutput {
  return {
    ...decision,
    rationale: {
      ...decision.rationale,
      executive_summary: payload.executive_summary,
      agronomic_reasoning: payload.decision_explanation,
      water_balance_reasoning: payload.decision_explanation,
      anomaly_reasoning: payload.risk_interpretation,
    },
    reporting: {
      ...decision.reporting,
      operational_note: payload.recommended_next_actions[0] ?? "Review the recommendation window and field constraints before execution.",
      advisor_note: payload.decision_explanation,
      grower_facing_message: payload.commercial_demo_narrative,
      compliance_note: `${decision.reporting.compliance_note} ${payload.limitations}`.trim(),
    },
  };
}

function assembleReportObject(decision: DecisionOutput, pack: NormalizedSignalPack | null, payload: LLMReportPayload): ReportObject {
  const endpoint = `/api/v1/decisions/${decision.decision_id}`;
  return {
    report_id: crypto.randomUUID(),
    decision_id: decision.decision_id,
    title: `AGRO-AI x EarthDaily Irrigation Decision - ${pack?.spatial_context.field_name ?? decision.field_id}`,
    field_summary: pack
      ? `${pack.spatial_context.field_name}; ${pack.crop_context.crop_type}; ${pack.crop_context.acreage} acres; ${pack.crop_context.region}.`
      : `Field ${decision.field_id}.`,
    recommendation_summary: payload.executive_summary,
    evidence_table: evidenceRows(decision, pack),
    risk_table: Object.entries(decision.risk_flags).map(([flag, status]) => ({
      flag,
      status,
      interpretation: status ? "Triggered by deterministic threshold." : "Below threshold.",
    })),
    water_savings_estimate: decision.reporting.projected_water_savings,
    before_after_comparison: {
      baseline: "Calendar or manual review workflow.",
      recommended: `${decision.recommendation.action} during ${decision.recommendation.recommended_window_start} to ${decision.recommendation.recommended_window_end}.`,
      difference: decision.reporting.projected_water_savings,
    },
    next_actions: payload.recommended_next_actions,
    pdf_ready_sections: {
      executive_summary: payload.executive_summary,
      advisor_note: decision.reporting.advisor_note,
      grower_message: decision.reporting.grower_facing_message,
      technical_appendix: payload.decision_explanation,
    },
    api_payload_reference: {
      decision_id: decision.decision_id,
      field_id: decision.field_id,
      endpoint,
    },
    audit_reference: {
      decision_id: decision.decision_id,
      audit_endpoint: `${endpoint}/audit`,
    },
  };
}

function evidenceRows(decision: DecisionOutput, pack: NormalizedSignalPack | null) {
  if (!pack) {
    return decision.rationale.signal_evidence.map((signal) => ({
      signal,
      value: "available",
      interpretation: "Provided by decision output.",
    }));
  }
  const scores = pack.confidence_inputs.component_scores;
  return [
    ["Moisture stress", scores.moisture_stress_score, "Higher means drier rootzone or larger depletion."],
    ["ET pressure", scores.et_pressure_score, "Higher means forecast demand exceeds rainfall relief."],
    ["Vegetation stress", scores.vegetation_stress_score, "Higher means declining vegetation or low NDMI."],
    ["Anomaly severity", scores.anomaly_severity, "Higher means hotspot or change detection is material."],
    ["Weather risk", scores.weather_risk_score, "Higher means heat, wind, and no-rain risk."],
    ["Data quality", scores.data_quality_score, "Higher means clearer and fresher inputs."],
  ].map(([signal, value, interpretation]) => ({
    signal: String(signal),
    value: typeof value === "number" ? value.toFixed(3) : String(value),
    interpretation: String(interpretation),
  }));
}

function nextActions(decision: DecisionOutput): string[] {
  if (decision.recommendation.action === "irrigate") {
    return [
      `Schedule ${decision.recommendation.estimated_duration} ${decision.recommendation.estimated_duration_unit} in the recommended window.`,
      "Inspect the hotspot area after irrigation for persistent moisture stress.",
      "Record actual applied water for the next decision cycle.",
    ];
  }
  if (decision.recommendation.action === "investigate" || decision.recommendation.action === "manual_review") {
    return [
      "Review flagged data quality or conflicting field signals.",
      "Confirm field observations before changing irrigation execution.",
      "Refresh EarthDaily and weather inputs before issuing a final action.",
    ];
  }
  return [
    "Continue monitoring ET, NDMI, and rootzone depletion.",
    "Re-run the workflow when the next EarthDaily scene or weather update arrives.",
    "Keep actual applied water records current.",
  ];
}

