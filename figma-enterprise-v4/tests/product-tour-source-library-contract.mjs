import assert from "node:assert/strict";
import fs from "node:fs";

const tour = fs.readFileSync(new URL("../src/app/components/ProductTour.tsx", import.meta.url), "utf8");
const routes = fs.readFileSync(new URL("../src/app/routes.tsx", import.meta.url), "utf8");
const evidence = fs.readFileSync(new URL("../src/app/components/Evidence.tsx", import.meta.url), "utf8");
const sources = fs.readFileSync(new URL("../src/app/components/Sources.tsx", import.meta.url), "utf8");

assert.match(tour, /product_tour_v2/);
assert.match(tour, /useNavigate/);
assert.match(tour, /route:\s*"\/field-queue"/);
assert.match(tour, /route:\s*"\/tasks"/);
assert.match(tour, /route:\s*"\/operations"/);
assert.match(tour, /route:\s*"\/evidence"/);
assert.match(tour, /route:\s*"\/integrations"/);
assert.match(tour, /route:\s*"\/intelligence"/);
assert.match(tour, /route:\s*"\/readiness"/);
assert.match(tour, /route:\s*"\/exceptions"/);
assert.match(tour, /route:\s*"\/sources"/);
assert.match(tour, /resolveTarget\(step\)/);
assert.doesNotMatch(tour, /target:\s*"command-center"/);

assert.match(routes, /index:\s*true,\s*lazy:\s*lazyComponent\(\(\)\s*=>\s*import\("\.\/components\/Overview"\)/);
assert.match(evidence, /\/v1\/source-library/);
assert.match(evidence, /data-tour="evidence-source-library"/);
assert.match(evidence, /currentWorkspace/);
assert.match(sources, /\/v1\/source-library/);
assert.match(sources, /data-tour="source-library-table"/);
assert.doesNotMatch(sources, /Manage connected data sources and telemetry feeds\./);

console.log("Route-aware product tour and source library contract passed.");
