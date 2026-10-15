// Crop Intelligence route-to-backend contract: cheap release regression, not an authenticated staging test.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const read = (relativePath) => readFileSync(new URL(relativePath, "file://" + root), "utf8");
const routes = read("src/app/routes.tsx");
const nav = read("src/app/components/MainLayout.tsx");
const page = read("src/app/components/CropIntelligence.tsx");
const client = read("src/app/api/client.ts");
const backend = read("../agroai_api/app/api/v1/field_intelligence.py");
const detection = read("../agroai_api/app/services/crop_model_registry.py");

assert.match(routes, /path: "crop-intelligence", lazy: lazyComponent\(\(\) => import\("\.\/components\/CropIntelligence"\), "CropIntelligence"\)/);
assert.match(nav, /path: "\/crop-intelligence"/);
assert.match(page, /export function CropIntelligence\(/);
assert.match(page, /currentWorkspaceAllowed/);
assert.match(page, /activeScopeRef\.current !== requestScope/, "stale async calculator results must be rejected after scope changes");
assert.match(page, /setEstimate\(null\)/, "previous scoped estimate must be cleared");
assert.match(page, /setHarvest\(null\)/, "previous scoped harvest must be cleared");
assert.match(page, /setMaturity\(null\)/, "previous scoped maturity must be cleared");
assert.match(page, /population < counts\.length/, "sample population cannot be smaller than the sample count");
assert.match(page, /include_market_proposal: Boolean\(production\.area && production\.weight\)/, "manual sampling can propose market yield without a detector calibration");
assert.doesNotMatch(page, /include_market_proposal: Boolean\([^\n]*production\.detection/, "manual market proposal must not require detection calibration");
assert.match(page, /count_source: "manual_count"/, "manual evidence provenance must be explicit");
assert.match(page, /fieldCropCondition\(fieldId, workspaceId\)/);
assert.match(page, /observations\("workspace_id=" \+ encodeURIComponent\(workspaceId\)/);
assert.match(page, /apiClient\.fieldIntelligence\.cropProfiles\(/);
assert.match(page, /apiClient\.fieldIntelligence\.productionEstimate\(/);
assert.match(page, /apiClient\.fieldIntelligence\.harvestWindow\(/);
assert.match(page, /apiClient\.fieldIntelligence\.maturityStages\(/);
assert.match(page, /No automatic changes are made to Market Intelligence/);
assert.doesNotMatch(page, /apiClient\.post\(["']\/v1\/market-intelligence/);
assert.doesNotMatch(page, /marketIntelligence\.apply/);
assert.match(page, /Unvalidated crop profile/);
assert.match(page, /Results require human review before operational decisions/);
for (const route of ["harvest-window", "production-estimate", "maturity-stages"]) {
  assert.match(client, new RegExp("crop-intelligence/" + route));
  const escaped = route.replaceAll("-", "\\-");
  assert.match(backend, new RegExp('@router.post\\("/crop-intelligence/' + escaped + '"'));
}
assert.match(backend, /dependencies=\[Depends\(enforce_paid_crop_intelligence\), Depends\(enforce_json_body_limit\)\]/);
assert.match(detection, /VERIFIED_EVALUATIONS[^\n]*= \(\)/);
console.log("Crop Intelligence route, API, access, and review-only contracts pass.");
