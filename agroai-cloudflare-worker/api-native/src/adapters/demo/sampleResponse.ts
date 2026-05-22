import { runDecisionEngine } from "../../core/decision/engine";
import { normalizeEarthDailyInput } from "../../core/normalization/normalize";
import { buildReportObject } from "../../core/reporting/report";
import { hashEarthDailyInput } from "../../lib/audit/hash";
import { buildDemoEarthDailyInput } from "../earthdaily/demoAdapter";

export async function buildPrecomputedSampleResponse() {
  const earthdaily_raw_input = buildDemoEarthDailyInput();
  const normalized_signal_pack = normalizeEarthDailyInput(earthdaily_raw_input);
  normalized_signal_pack.signal_pack_id = "sample-signal-pack-earthdaily-demo";
  const inputHash = await hashEarthDailyInput(earthdaily_raw_input);
  const decision = runDecisionEngine({
    signalPack: normalized_signal_pack,
    inputHash,
    createdAt: "2026-05-22T15:00:00-07:00",
  });
  decision.decision_id = "sample-decision-earthdaily-demo";
  const report = await buildReportObject(decision, normalized_signal_pack, {});
  report.report_object.report_id = "sample-report-earthdaily-demo";

  return {
    earthdaily_raw_input,
    normalized_signal_pack,
    decision_output: report.decision_output,
    ai_review: report.ai_review,
    report_object: report.report_object,
    audit_trace: [],
    integration_metadata: {
      provider: "earthdaily",
      mode: "demo",
      source: "agroai-demo-fixture",
      sample_response_version: "earthdaily-demo-v1",
    },
  };
}
