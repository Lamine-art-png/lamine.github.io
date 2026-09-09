import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const view = fs.readFileSync(path.join(root, "src/app/components/intelligence/IntelligenceView.tsx"), "utf8");
const controller = fs.readFileSync(path.join(root, "src/app/components/intelligence/useIntelligenceController.ts"), "utf8");

assert.match(view, /ArtifactPreviewInline/);
assert.match(view, /ArtifactPreviewModal/);
assert.match(view, /SlidePreview/);
assert.match(view, /DocumentPreview/);
assert.match(view, /generatedArtifact\?\.preview/);
assert.match(view, /preview\.slides/);
assert.match(view, /preview\.sections/);
assert.match(controller, /plan_token: action\.plan_token/);
assert.match(controller, /analysis_context:/);
assert.match(controller, /actionFirstTypes/);
assert.match(controller, /create_operation/);
assert.match(controller, /update_operation/);

console.log("Agentic artifact preview contract passed.");
