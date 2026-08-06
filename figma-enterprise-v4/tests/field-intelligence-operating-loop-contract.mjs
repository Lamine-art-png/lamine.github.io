import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const runtime = fs.readFileSync(path.join(root, "src/app/fieldIntelligence/operatingLoopRuntime.ts"), "utf8");
const main = fs.readFileSync(path.join(root, "src/main.tsx"), "utf8");

assert.match(main, /import\("\.\/app\/fieldIntelligence\/operatingLoopRuntime"\)/);
assert.match(main, /after the portal has rendered/);
assert.doesNotMatch(runtime, /FieldIntelligenceV2/);
assert.match(runtime, /field_observation_id/);
assert.match(runtime, /source_observation_id/);
assert.match(runtime, /uploaded_evidence/);
assert.match(runtime, /linkedObservationEvidence/);
assert.match(runtime, /TASK_READY_EVENT/);
assert.match(runtime, /\/tasks\?task_id=/);
assert.match(runtime, /\/intelligence\?field_observation_id=/);
assert.match(runtime, /One observation\. One operating loop\./);
assert.match(runtime, /Capture/);
assert.match(runtime, /Understand/);
assert.match(runtime, /Decide/);
assert.match(runtime, /Act/);
assert.match(runtime, /MutationObserver/);
assert.match(runtime, /catch \(error\)[\s\S]+never be capable of taking down the portal shell/);

console.log("field-intelligence-operating-loop-contract: ok");
