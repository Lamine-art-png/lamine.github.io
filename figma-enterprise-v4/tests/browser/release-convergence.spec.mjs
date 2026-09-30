import { expect, test } from "@playwright/test";

// Real-browser release convergence against tests/release-harness/server.mjs,
// which serves two genuinely different production builds (A and B) with the
// production cache policy. "Deploying" switches the live release in place.
const HARNESS = process.env.AGROAI_RELEASE_HARNESS;
const A = process.env.AGROAI_RELEASE_A;
const B = process.env.AGROAI_RELEASE_B;

test.skip(!HARNESS || !A || !B, "requires the release harness (AGROAI_RELEASE_HARNESS, AGROAI_RELEASE_A, AGROAI_RELEASE_B)");
test.describe.configure({ mode: "serial", timeout: 90_000 });

const TOKEN = `qa.${Buffer.from(JSON.stringify({ sub: "u-release", org_id: "o-release", exp: Math.floor(Date.now() / 1000) + 86400 })).toString("base64url")}.sig`;

async function deploy(release, shell) {
  const url = new URL("/__harness/deploy", HARNESS);
  url.searchParams.set("release", release === A ? "A" : "B");
  if (shell) url.searchParams.set("shell", shell === A ? "A" : "B");
  const response = await fetch(url);
  expect(response.ok).toBe(true);
}

async function events() {
  return (await fetch(new URL("/__harness/events", HARNESS))).json();
}

async function running(page) {
  // A page that is mid-reload (converging) has no execution context yet.
  return page.evaluate(() => window.__agroaiRelease?.running || document.querySelector('meta[name="agroai-build"]')?.content || null).catch(() => null);
}

async function newCustomer(browser, { signedIn = true, locale = "pt-BR", restrictedStorage = false } = {}) {
  const context = await browser.newContext();
  await context.addInitScript(({ token, signedIn, locale, restrictedStorage }) => {
    window.__AGROAI_RELEASE_TEST__ = { minCheckIntervalMs: 0, guardBackoffMs: 3000 };
    if (restrictedStorage) {
      for (const name of ["localStorage", "sessionStorage"]) {
        Object.defineProperty(window, name, { configurable: true, get() { throw new DOMException("denied", "SecurityError"); } });
      }
      return;
    }
    if (!sessionStorage.getItem("seeded")) {
      sessionStorage.setItem("seeded", "1");
      if (signedIn) localStorage.setItem("agroai_access_token", token);
      localStorage.setItem("agroai_locale_v1", locale);
    }
  }, { token: TOKEN, signedIn, locale, restrictedStorage });
  return context;
}

async function expectRunning(page, build, timeout = 20_000) {
  try {
    await expect.poll(() => running(page), { timeout }).toBe(build);
  } catch (error) {
    const state = await page.evaluate(() => ({
      running: window.__agroaiRelease?.running,
      pending: window.__agroaiRelease?.pending(),
      latest: window.__agroaiRelease?.latest(),
      blockedBy: window.__agroaiRelease?.unsafeReason(),
      visibility: document.visibilityState,
      active: document.activeElement?.tagName,
      path: location.pathname,
    })).catch((cause) => ({ unavailable: String(cause) }));
    throw new Error(`${error.message}\nrelease state: ${JSON.stringify(state)}`);
  }
}

async function setVisibility(page, state) {
  // A page that is already reloading into the new release has nothing to hide/show.
  await page.evaluate((next) => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => next });
    Object.defineProperty(document, "hidden", { configurable: true, get: () => next === "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  }, state).catch((error) => {
    if (!/Execution context was destroyed|navigation/i.test(String(error))) throw error;
  });
}

async function openPortal(context, path = "/") {
  const page = await context.newPage();
  await page.goto(new URL(path, HARNESS).toString());
  await page.waitForFunction(() => Boolean(window.__agroaiRelease), null, { timeout: 20_000 });
  return page;
}

async function returnToTab(page) {
  await setVisibility(page, "hidden");
  await setVisibility(page, "visible");
}

test.beforeEach(async () => {
  await deploy(A);
});

test("a fresh browser gets the current release; the service worker never caches /v1", async ({ browser }) => {
  const context = await newCustomer(browser);
  const page = await openPortal(context);
  expect(await running(page)).toBe(A);
  await page.waitForFunction(() => navigator.serviceWorker?.controller !== null, null, { timeout: 20_000 }).catch(() => undefined);
  await page.reload();
  await page.waitForFunction(() => Boolean(window.__agroaiRelease));
  const cached = await page.evaluate(async () => {
    const urls = [];
    for (const name of await caches.keys()) {
      for (const request of await (await caches.open(name)).keys()) urls.push(new URL(request.url).pathname);
    }
    return { names: await caches.keys(), urls };
  });
  expect(cached.urls.some((path) => path.startsWith("/v1/"))).toBe(false);
  expect(cached.names.every((name) => name.endsWith(A) || !name.startsWith("agroai-shell-"))).toBe(true);

  const builds = await (await fetch(new URL("/__harness/client-builds", HARNESS))).json();
  expect(builds.some((row) => row.build === A)).toBe(true);
  await context.close();

  await deploy(B);
  const next = await newCustomer(browser);
  const nextPage = await openPortal(next);
  expect(await running(nextPage)).toBe(B);
  await next.close();
});

test("a returning browser with the old service worker and cache opens the new release", async ({ browser }) => {
  const context = await newCustomer(browser);
  const page = await openPortal(context);
  await page.waitForFunction(() => navigator.serviceWorker?.controller !== null, null, { timeout: 20_000 });
  await page.close();

  await deploy(B);
  const again = await openPortal(context);
  await expect.poll(() => running(again), { timeout: 20_000 }).toBe(B);
  await expect.poll(async () => again.evaluate(async () => (await caches.keys()).filter((name) => name.startsWith("agroai-shell-"))), { timeout: 20_000 })
    .toEqual([expect.stringMatching(new RegExp(`${B}$`))]);
  expect(await again.evaluate(() => localStorage.getItem("agroai_access_token"))).toBe(TOKEN);
  await context.close();
});

test("an open tab converges when the customer returns, keeping session and Portuguese", async ({ browser }) => {
  const context = await newCustomer(browser, { locale: "pt-BR" });
  const page = await openPortal(context);
  expect(await running(page)).toBe(A);
  await deploy(B);
  await returnToTab(page);
  await expect.poll(() => running(page), { timeout: 20_000 }).toBe(B);
  expect(await page.evaluate(() => localStorage.getItem("agroai_access_token"))).toBe(TOKEN);
  expect(await page.evaluate(() => localStorage.getItem("agroai_locale_v1"))).toBe("pt-BR");
  await expect.poll(() => page.evaluate(() => document.documentElement.lang).catch(() => ""), { timeout: 10_000 }).toMatch(/^pt/);
  // Diagnostics are sent with sendBeacon (asynchronous, fire-and-forget).
  await expect.poll(async () => (await events()).some((row) => row.event === "stale_build_detected" && row.running_build === A && row.latest_build === B), { timeout: 10_000 }).toBe(true);
  await expect.poll(async () => (await events()).some((row) => row.event === "recovery_succeeded" && row.running_build === B), { timeout: 10_000 }).toBe(true);
  expect(JSON.stringify(await events())).not.toContain(TOKEN);
  await context.close();
});

test("unsaved input is never discarded: convergence waits for the next navigation", async ({ browser }) => {
  const context = await newCustomer(browser, { signedIn: false, locale: "en" });
  const page = await openPortal(context, "/");
  const email = page.getByLabel("Email").first();
  await email.fill("grower@example.com");
  await deploy(B);
  await returnToTab(page);
  await page.waitForTimeout(2500);
  expect(await running(page)).toBe(A);
  await expect(email).toHaveValue("grower@example.com");
  expect(await page.evaluate(() => window.__agroaiRelease.pending())).toBe(B);

  await page.evaluate(() => window.history.pushState({}, "", "/pricing"));
  await expect.poll(() => running(page), { timeout: 20_000 }).toBe(B);
  expect(new URL(page.url()).pathname).toBe("/pricing");
  await context.close();
});

test("two open tabs converge once each, without a reload storm", async ({ browser }) => {
  const context = await newCustomer(browser);
  const first = await openPortal(context);
  const second = await openPortal(context);
  let secondLoads = 0;
  second.on("load", () => { secondLoads += 1; });
  await deploy(B);
  await returnToTab(first);
  await expect.poll(() => running(first), { timeout: 20_000 }).toBe(B);
  // The second tab learns of B from the first (broadcast) or from B's
  // service worker claiming it. A background tab applies it immediately; a
  // visible one waits for a safe point such as being hidden.
  await expect.poll(async () => (await running(second)) === B || await second.evaluate(() => window.__agroaiRelease.pending()).catch(() => null) === B, { timeout: 15_000 }).toBe(true);
  if ((await running(second)) !== B) await setVisibility(second, "hidden");
  await expectRunning(second, B);
  await second.waitForTimeout(3000);
  expect(secondLoads).toBe(1);
  await context.close();
});

test("a retired lazy route chunk loads the current release instead of a broken module", async ({ browser }) => {
  const context = await newCustomer(browser);
  const page = await openPortal(context, "/");
  await deploy(B); // A's hashed chunks are now retired (404)
  await page.evaluate(() => {
    window.history.pushState({}, "", "/settings");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect.poll(() => running(page), { timeout: 20_000 }).toBe(B);
  expect(new URL(page.url()).pathname).toBe("/settings");
  await expect(page.getByText("This workspace module is not available yet.")).toHaveCount(0);
  await context.close();
});

test("a rollback converges browsers on the newer release back to the previous one", async ({ browser }) => {
  await deploy(B);
  const context = await newCustomer(browser);
  const page = await openPortal(context);
  expect(await running(page)).toBe(B);
  await deploy(A);
  await returnToTab(page);
  await expect.poll(() => running(page), { timeout: 20_000 }).toBe(A);
  await context.close();
});

async function outage(on) {
  const response = await fetch(new URL(`/__harness/outage?on=${on ? 1 : 0}`, HARNESS));
  expect(response.ok).toBe(true);
}

test("offline during a release: no error screen, converges after reconnecting", async ({ browser }) => {
  const context = await newCustomer(browser);
  const page = await openPortal(context);
  await outage(true); // connections drop, as on a lost network
  try {
    await deploy(B);
    await returnToTab(page);
    await page.waitForTimeout(1500);
    expect(await running(page)).toBe(A);
    expect(await page.evaluate(() => window.__agroaiRelease.pending())).toBeNull();
    await expect(page.getByText("Frontend recovery mode")).toHaveCount(0);
  } finally {
    await outage(false);
  }
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  // Reconnecting detects B; a background tab applies it at once, a visible
  // one at the next safe point (here: the customer returning to the tab).
  await expect.poll(async () => (await running(page)) === B || await page.evaluate(() => window.__agroaiRelease.pending()).catch(() => null) === B, { timeout: 10_000 }).toBe(true);
  if ((await running(page)) !== B) await returnToTab(page);
  await expectRunning(page, B);
  await expect(page.getByText("Frontend recovery mode")).toHaveCount(0);
  await context.close();
});

test("partial propagation cannot cause a reload loop", async ({ browser }) => {
  const context = await newCustomer(browser);
  const page = await openPortal(context);
  let loads = 0;
  page.on("load", () => { loads += 1; });
  await deploy(B, A); // deployment.json says B, but the edge still serves A's shell
  await returnToTab(page);
  await page.waitForTimeout(8000);
  expect(loads).toBeLessThanOrEqual(2);
  expect(await running(page)).toBe(A);
  await expect(page.getByText("Frontend recovery mode")).toHaveCount(0);
  await expect.poll(async () => (await events()).some((row) => row.event === "reload_loop_prevented"), { timeout: 10_000 }).toBe(true);

  await deploy(B); // propagation completes
  await page.waitForTimeout(3500); // past the loop guard's backoff
  await returnToTab(page);
  await expect.poll(() => running(page), { timeout: 20_000 }).toBe(B);
  await context.close();
});

test("restricted (Safari private) storage still boots and converges", async ({ browser }) => {
  const context = await newCustomer(browser, { restrictedStorage: true });
  const page = await openPortal(context);
  expect(await running(page)).toBe(A);
  await deploy(B);
  await returnToTab(page);
  await expect.poll(() => running(page), { timeout: 20_000 }).toBe(B);
  await context.close();
});
