import "dotenv/config";
import { modelRouter } from "../../ai/modelRouter.js";

const provider = modelRouter.embeddingProvider();
if (provider.mode !== "live") {
  console.error(`SMOKE FAIL: No live embedding provider configured. Set EMBEDDING_PROVIDER and the corresponding API key in .env.`);
  console.error(`  EMBEDDING_PROVIDER=${process.env.EMBEDDING_PROVIDER || "(not set)"}`);
  process.exit(1);
}
console.log(`Provider: ${provider.name}  model: ${provider.model}  mode: ${provider.mode}`);

const testTexts = [
  "Irrigation decision for tomato field with loam soil",
  "Frost risk reduces water demand in citrus groves",
  "Sandy soil drains quickly and needs more frequent irrigation",
];

for (const text of testTexts) {
  const start = Date.now();
  let vector;
  try {
    vector = await provider.embed(text);
  } catch (err) {
    console.error(`SMOKE FAIL: Embedding error: ${err.message}`);
    process.exit(1);
  }
  const latencyMs = Date.now() - start;

  if (!Array.isArray(vector) || vector.length === 0) {
    console.error(`SMOKE FAIL: Empty or invalid embedding returned for: "${text}"`);
    process.exit(1);
  }
  const norm = Math.sqrt(vector.reduce((s, v) => s + v * v, 0));
  console.log(`  dims=${vector.length}  norm=${norm.toFixed(4)}  latency=${latencyMs}ms  text="${text.slice(0, 40)}"`);
}
console.log("Embedding smoke test passed.");
