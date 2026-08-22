import assert from "node:assert/strict";
import fs from "node:fs";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const routes = read("../src/app/routes.tsx");
const layout = read("../src/app/components/MainLayout.tsx");
const recovery = read("../src/app/components/AssuranceRouteRecovery.tsx");
const assurance = read("../src/app/components/Assurance.tsx");
const apiClient = read("../src/app/api/client.ts");

assert.match(routes, /import \{ AssuranceRouteRecovery \} from "\.\/components\/AssuranceRouteRecovery"/);
assert.match(routes, /const assuranceRouteRecovery = <AssuranceRouteRecovery \/>/);
assert.match(routes, /path: "assurance"[\s\S]*lazy:[\s\S]*errorElement: assuranceRouteRecovery/);
assert.match(routes, /Component: MainLayout[\s\S]*children:[\s\S]*operationRoutes/);
assert.match(layout, /<Outlet \/>/, "the shared shell must own the child outlet");
assert.match(recovery, /data-assurance-route-recovery/);
assert.match(recovery, /portal shell and every other operating route remain available/i);
assert.match(assurance, /data-assurance-v2/);
assert.doesNotMatch(assurance, /window\.location\.href\s*=|Navigate to="\/"/, "Assurance failure must not redirect or replace the portal");
assert.doesNotMatch(assurance, /content_base64|window\.atob/, "modern proof packages must use authenticated server-side download");
assert.match(apiClient, /packages\/\$\{encodeURIComponent\(packageId\)\}\/download/);
assert.match(apiClient, /agent\/runs/);
assert.match(apiClient, /agent\/runs`, \{ idempotency_key: idempotencyKey \}/);
assert.match(assurance, /packageRequest = useRef/);
assert.match(assurance, /agentRequest = useRef/);
assert.match(assurance, /idempotency_key: packageRequest\.current\.key/);
assert.match(assurance, /Human review remains authoritative/);

console.log("Assurance route isolation contract passed");
