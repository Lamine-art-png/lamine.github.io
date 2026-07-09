import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

const layout = read("src/app/components/MainLayout.tsx");
const host = read("src/app/components/CommercialBoundaryHostLocalized.tsx");
const viewModel = read("src/app/components/commercialBoundaryViewModel.ts");
const reports = read("src/app/components/MonetizedReportsV2.tsx");
const team = read("src/app/components/MonetizedTeamV2.tsx");
const requests = read("src/app/components/MonetizedRequestsV2.tsx");
const ask = read("src/app/components/MonetizedIntelligenceV2.tsx");
const routes = read("src/app/routes.tsx");
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
assert(host.includes('target === "enterprise"') && host.includes("https://agroai-pilot.com/book-a-demo"), "Enterprise paywall CTAs must route to the public demo-booking page.");
assert(!host.includes("/pricing?upgrade="), "Self-serve paywall CTAs must never bounce customers to Pricing instead of checkout.");
assert(host.includes("apiClient.billing.checkout({ plan_id: target, billing_period: billingPeriod })"), "Self-serve paywalls must call the authoritative checkout endpoint directly.");
assert(host.includes("window.location.assign(checkoutUrl)"), "Successful paywall checkout must navigate to the Stripe checkout URL returned by the backend.");
assert(host.includes('window.localStorage.getItem(BILLING_PERIOD_STORAGE_KEY) === "annual"'), "Paywalls must preserve the customer billing-period preference used by Pricing.");
assert(host.includes('detail.code === "subscription_inactive"') && host.includes("return currentPlan"), "Inactive paid subscriptions must restore the current paid tier instead of forcing an unrelated next-tier upgrade.");

assert(reports.includes('source: "reports"') && reports.includes('recommended_plan: "professional"'), "Reports must open the rich Professional comparison wall.");
assert(team.includes('source: "team"') && team.includes('recommended_plan: "team"'), "Team must open the rich Team comparison wall.");
assert(requests.includes('source: "requests"') && requests.includes('recommended_plan: "team"'), "Requests must open the rich Team comparison wall.");

assert(routes.includes('import("./components/MonetizedIntelligenceV2")') && routes.includes('"MonetizedIntelligenceV2"'), "The Ask AGRO-AI route must mount the monetized boundary, not the raw Intelligence component.");
assert(ask.includes('feature: "intelligence.ask"'), "Ask AGRO-AI must open the exact intelligence.ask commercial boundary.");
assert(ask.includes('recommended_plan: "professional"'), "Ask AGRO-AI must recommend Professional as the first paid tier.");
assert(ask.includes('if (!locked) return <Intelligence />;'), "Only entitled customers may mount the expensive Ask AGRO-AI component.");
assert(layout.includes('"intelligence.ask"') && layout.includes('locked: !canAskAgroAi, upgradeTo: "professional"'), "Ask AGRO-AI must visibly show a Professional lock in portal navigation.");
assert(viewModel.includes('"intelligence.ask": "intelligence.title"'), "The shared commercial modal must label the Ask AGRO-AI capability explicitly.");
assert(!viewModel.includes('bullets: ["commercialBoundary.plan.free.bullet1", "commercialBoundary.plan.free.bullet2"'), "The shared Free plan card must never advertise the retired 25-action AI allowance.");

assert(pricing.includes('["professional", "team", "network"].includes(plan.id)'), "Professional, Team, and Network must all carry annual savings treatment.");
assert(pricing.includes("Professional, Team, and Network save 17% on annual billing."), "Pricing header must explain the 17% annual saving across self-serve paid tiers.");
assert(pricing.includes('if (plan.id === "enterprise") { window.location.assign(DEMO_BOOKING_URL); return; }'), "Enterprise pricing must bypass Stripe and route directly to demo booking.");
assert(pricing.includes("https://agroai-pilot.com/book-a-demo"), "Enterprise pricing must use the canonical public demo-booking URL.");
assert(!pricing.includes('if (plan.id === "enterprise") { await apiClient.sales.contact'), "Enterprise pricing must not stop at a dead-end contact request state.");
assert(!pricing.includes('"25 AGRO-AI actions/month", "2 Deep analysis previews/month"'), "Free pricing must never advertise model inference or Deep-analysis previews.");
assert(pricing.includes('["Ask AGRO-AI", "Locked", "Included", "Included", "Included", "Included"]'), "Pricing comparison must show Ask AGRO-AI locked on Free and included from Professional onward.");
assert(pricing.includes('["AGRO-AI actions", "Locked", "500/mo"'), "Free must have no AGRO-AI action allowance in the pricing comparison.");
assert(pricing.includes('["Deep analysis", "Locked", "25/mo"'), "Free must have no Deep-analysis preview allowance in the pricing comparison.");

assert(integrations.includes("connectorUpgradeMessage"), "Connector paywalls must use provider-specific conversion copy.");
assert(integrations.includes("profile.title") && integrations.includes("profile.description"), "Connector paywall copy must name and explain the exact connector.");
assert(integrations.includes('tf("{plan} unlocks"'), "Locked connector badges must use localized unlock language, not danger-style required language.");
assert(!integrations.includes('`${planName(needed)} required`'), "Locked connector badges must never return raw required-plan danger language.");

console.log("paywall refinements v4 contract passed");
