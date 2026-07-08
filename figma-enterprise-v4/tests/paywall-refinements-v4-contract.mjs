import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

const layout = read("src/app/components/MainLayout.tsx");
const host = read("src/app/components/CommercialBoundaryHostLocalized.tsx");
const reports = read("src/app/components/MonetizedReportsV2.tsx");
const team = read("src/app/components/MonetizedTeamV2.tsx");
const requests = read("src/app/components/MonetizedRequestsV2.tsx");
const pricing = read("src/app/components/PricingPage.tsx");
const integrations = read("src/app/components/IntegrationsV3.tsx");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(!layout.includes("/pricing?upgrade="), "Locked section navigation must route to the real section so its contextual paywall can open.");
assert(layout.includes('to={item.path}'), "Locked navigation must preserve the section route.");

assert(host.includes("CompactPlanPrice"), "Commercial modal must split compact plan pricing to prevent suffix overflow.");
assert(host.includes("flex-wrap items-baseline"), "Commercial plan price must be wrap-safe.");
assert(host.includes("whitespace-nowrap text-[15px]"), "Commercial plan names must stay on one line across every shared paywall.");
assert(host.includes('detail.source || ""'), "Commercial wall must honor contextual section/provider sources.");

assert(reports.includes('source: "reports"') && reports.includes('recommended_plan: "professional"'), "Reports must open the rich Professional comparison wall.");
assert(team.includes('source: "team"') && team.includes('recommended_plan: "team"'), "Team must open the rich Team comparison wall.");
assert(requests.includes('source: "requests"') && requests.includes('recommended_plan: "team"'), "Requests must open the rich Team comparison wall.");

assert(pricing.includes('["professional", "team", "network"].includes(plan.id)'), "Professional, Team, and Network must all carry annual savings treatment.");
assert(pricing.includes("Professional, Team, and Network save 17% on annual billing."), "Pricing header must explain the 17% annual saving across self-serve paid tiers.");

assert(integrations.includes("connectorUpgradeMessage"), "Connector paywalls must use provider-specific conversion copy.");
assert(integrations.includes("profile.title") && integrations.includes("profile.description"), "Connector paywall copy must name and explain the exact connector.");
assert(integrations.includes('tf("{plan} unlocks"'), "Locked connector badges must use localized unlock language, not danger-style required language.");
assert(!integrations.includes('`${planName(needed)} required`'), "Locked connector badges must never return raw required-plan danger language.");

console.log("paywall refinements v4 contract passed");
