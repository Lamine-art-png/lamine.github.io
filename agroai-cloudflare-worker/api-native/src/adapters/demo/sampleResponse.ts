import { buildDemoEarthDailyInput } from "../earthdaily/demoAdapter";

export function buildPrecomputedSampleResponse() {
  const earthdaily_raw_input = buildDemoEarthDailyInput();
  return {
    earthdaily_raw_input,
    normalized_signal_pack: null,
    decision_output: null,
    ai_review: {
      skipped: true,
      reason: "Precomputed response is completed after normalization, decision, and reporting modules are loaded.",
    },
    report_object: null,
    audit_trace: [],
    integration_metadata: {
      provider: "earthdaily",
      mode: "demo",
      source: "agroai-demo-fixture",
      sample_response_version: "earthdaily-demo-v0",
    },
  };
}

