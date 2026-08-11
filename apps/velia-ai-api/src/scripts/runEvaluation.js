import "dotenv/config";
import { scenarios, runFixtureEvaluation } from "../ai/evaluationHarness.js";

const results = runFixtureEvaluation();
const passed = results.filter((r) => r.passed);
const failed = results.filter((r) => !r.passed);

console.log(`\nVelia Evaluation Harness — ${scenarios.length} fixtures\n${"─".repeat(60)}`);
for (const r of results) {
  const mark = r.passed ? "PASS" : "FAIL";
  const checks = Object.entries(r.checks).filter(([, v]) => !v).map(([k]) => k);
  console.log(`  [${mark}] ${r.id.padEnd(36)} action=${r.action}  conf=${r.confidenceScore.toFixed(3)}${checks.length ? `  FAILED: ${checks.join(", ")}` : ""}`);
}

console.log(`\n${"─".repeat(60)}`);
console.log(`  Passed : ${passed.length}/${results.length}`);
console.log(`  Failed : ${failed.length}/${results.length}`);

if (failed.length > 0) {
  console.error("\nFailed scenarios:");
  for (const r of failed) console.error(`  - ${r.id}: ${Object.entries(r.checks).filter(([, v]) => !v).map(([k]) => k).join(", ")}`);
  process.exit(1);
}
console.log("\nAll evaluation fixtures passed.");
