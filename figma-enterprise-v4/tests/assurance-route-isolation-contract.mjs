import assert from "node:assert/strict";
import fs from "node:fs";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const routes = read("../src/app/routes.tsx");
const layout = read("../src/app/components/MainLayout.tsx");
const recovery = read("../src/app/components/AssuranceRouteRecovery.tsx");
const assurance = read("../src/app/components/Assurance.tsx");

assert.match(routes, /import \{ AssuranceRouteRecovery \} from "\.\/components\/AssuranceRouteRecovery"/);
assert.match(routes, /const assuranceRouteRecovery = <AssuranceRouteRecovery \/>/);
assert.match(routes, /path: "assurance"[\s\S]*lazy:[\s\S]*errorElement: assuranceRouteRecovery/);
assert.match(routes, /Component: MainLayout[\s\S]*children:[\s\S]*operationRoutes/);
assert.match(layout, /<Outlet \/>/, "the shared shell must own the child outlet");
assert.match(recovery, /data-assurance-route-recovery/);
assert.match(recovery, /portal shell and every other operating route remain available/i);
assert.match(assurance, /data-assurance-v2/);
assert.doesNotMatch(assurance, /window\.location\.href\s*=|Navigate to="\/"/, "Assurance failure must not redirect or replace the portal");

console.log("Assurance route isolation contract passed");
