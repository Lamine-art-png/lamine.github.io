import { test, expect } from "@playwright/test";

// These run across all four configured viewport projects
// (1440, 1280, 1024, 390), so each assertion is checked at every breakpoint.
test.describe("Responsive layout", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Open evaluation workspace" }).click();
    await page.waitForSelector(".command-page");
  });

  test("no horizontal overflow at the document level", async ({ page }) => {
    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1);
  });

  test("verified decision stays at a readable width", async ({ page }) => {
    const box = await page.locator(".decision").boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(260);
  });

  test("source metadata cells do not overlap", async ({ page }) => {
    // First data row (skip the header row).
    const cells = page.locator(".source-row").nth(1).locator("[role='cell']");
    const count = await cells.count();
    const boxes = [];
    for (let i = 0; i < count; i++) {
      const box = await cells.nth(i).boundingBox();
      if (box) boxes.push(box);
    }
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const horizontal = Math.min(boxes[i].x + boxes[i].width, boxes[j].x + boxes[j].width) - Math.max(boxes[i].x, boxes[j].x);
        const vertical = Math.min(boxes[i].y + boxes[i].height, boxes[j].y + boxes[j].height) - Math.max(boxes[i].y, boxes[j].y);
        expect(horizontal <= 1 || vertical <= 1).toBeTruthy();
      }
    }
  });

  test("operational values never wrap one character per line", async ({ page }) => {
    // Sample a set of value cells; none should collapse to a sliver.
    const values = page.locator(".decision .value");
    const n = Math.min(await values.count(), 6);
    for (let i = 0; i < n; i++) {
      const box = await values.nth(i).boundingBox();
      if (box) expect(box.width).toBeGreaterThan(40);
    }
  });
});
