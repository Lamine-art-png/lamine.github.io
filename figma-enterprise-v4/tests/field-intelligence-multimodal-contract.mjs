import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const component = fs.readFileSync(path.join(root, "src/app/components/FieldIntelligenceV2.tsx"), "utf8");
const map = fs.readFileSync(path.join(root, "src/app/fieldIntelligence/FieldMapV2.tsx"), "utf8");
const routes = fs.readFileSync(path.join(root, "src/app/routes.tsx"), "utf8");

assert.match(routes, /FieldIntelligenceV2/);
assert.match(component, /SpeechRecognition|webkitSpeechRecognition/);
assert.match(component, /capture="environment"/);
assert.match(component, /optimizeFieldImage/);
assert.match(component, /navigator\.geolocation/);
assert.match(component, /processingActive \? 2200 : 12000/);
assert.match(component, /structured\.vision/);
assert.match(component, /MediaViewer/);
assert.match(component, /createTask/);
assert.match(component, /href="\/intelligence"/);
assert.match(map, /tiles\.openfreemap\.org\/styles\/liberty/);
assert.match(map, /GeolocateControl/);
assert.match(map, /fi-observations/);

console.log("field-intelligence-multimodal-contract: ok");
