import { existsSync, readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

// Post-deployment proof in a real browser against the production custom domain.
const PORTAL = process.env.AGROAI_PRODUCTION_URL;
const SHA = process.env.AGROAI_EXPECTED_SHA;
const PREVIOUS_INDEX = process.env.AGROAI_PREVIOUS_INDEX;

test.skip(!PORTAL || !SHA, "requires AGROAI_PRODUCTION_URL and AGROAI_EXPECTED_SHA");

async function running(page) {
  return page.evaluate(() => window.__agroaiRelease?.running || document.querySelector('meta[name="agroai-build"]')?.content || null);
}

test("a fresh browser receives exactly the deployed release; API responses never enter the service-worker cache", async ({ browser }) => {
  const context = await browser.newContext({ locale: "pt-BR" });
  const page = await context.newPage();
  await page.goto(`${PORTAL}/?lang=pt-BR`);
  await page.waitForFunction(() => Boolean(window.__agroaiRelease), null, { timeout: 30_000 });
  expect(await running(page)).toBe(SHA);
  await page.waitForFunction(() => navigator.serviceWorker?.controller !== null, null, { timeout: 30_000 }).catch(() => undefined);
  await page.reload();
  await page.waitForFunction(() => Boolean(window.__agroaiRelease), null, { timeout: 30_000 });
  expect(await running(page)).toBe(SHA);
  const state = await page.evaluate(async () => {
    const urls = [];
    const names = await caches.keys();
    for (const name of names) {
      for (const request of await (await caches.open(name)).keys()) urls.push(new URL(request.url).pathname);
    }
    return { names, urls, controlled: Boolean(navigator.serviceWorker?.controller) };
  });
  expect(state.controlled).toBe(true);
  expect(state.urls.filter((path) => path.startsWith("/v1/"))).toEqual([]);
  expect(state.names.filter((name) => name.startsWith("agroai-shell-production-"))).toEqual([`agroai-shell-production-${SHA}`]);
  await context.close();
});

test("a browser holding the previous release's shell converges to the deployed release by itself", async ({ browser }) => {
  const previous = PREVIOUS_INDEX && existsSync(PREVIOUS_INDEX) ? readFileSync(PREVIOUS_INDEX, "utf8") : "";
  const previousBuild = previous.match(/<meta name="agroai-build" content="([^"]+)"/)?.[1];
  test.skip(!previousBuild || previousBuild === SHA, "previous release predates release identity or equals this release");
  const context = await browser.newContext();
  await context.addInitScript(() => {
    if (!sessionStorage.getItem("seeded")) {
      sessionStorage.setItem("seeded", "1");
      localStorage.setItem("agroai_locale_v1", "pt-BR");
    }
  });
  let servedStale = false;
  await context.route(`${PORTAL}/`, async (route) => {
    if (servedStale || route.request().resourceType() !== "document") return route.continue();
    servedStale = true;
    await route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: previous, headers: { "cache-control": "no-store" } });
  });
  const page = await context.newPage();
  await page.goto(`${PORTAL}/`);
  await expect.poll(() => running(page).catch(() => null), { timeout: 45_000 }).toBe(SHA);
  expect(servedStale).toBe(true);
  expect(await page.evaluate(() => localStorage.getItem("agroai_locale_v1"))).toBe("pt-BR");
  await context.close();
});
