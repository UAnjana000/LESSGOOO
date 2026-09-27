import type { APIRequestContext, Page } from "@playwright/test";
import { test, expect } from "../fixtures";

interface Manifest { items: { item_id: number }[]; lease_hours: number; lease_expires_at: string }
type TimelineEvent = { items: { id: number; title: string }[] };

/**
 * Waits until the service worker controls the page and has finished an exhibit sync. The worker caches
 * every item before it writes the signed manifest, so a stored manifest means the set is complete.
 */
async function waitForExhibit(page: Page): Promise<Manifest> {
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => true));
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller)),
    { message: "service worker controls the page", timeout: 30_000 }).toBe(true);
  await expect.poll(() => page.evaluate(async () => Boolean(await (await caches.open("exhibit-meta")).match("/__exhibit/manifest"))),
    { message: "signed exhibit manifest stored", timeout: 120_000, intervals: [1000, 2000, 5000] }).toBe(true);
  return page.evaluate(async () => (await (await (await caches.open("exhibit-meta")).match("/__exhibit/manifest"))!.json()).payload);
}

/** A timeline item that the exhibit set holds (online-only items are never cached). */
async function cachedTimelineItem(page: Page, api: APIRequestContext, m: Manifest) {
  const timeline: TimelineEvent[] = await (await api.get("/api/visitor/timeline")).json();
  const target = timeline.flatMap((e) => e.items).find((i) => m.items.some((x) => x.item_id === i.id));
  expect(target, "a timeline item is in the kiosk exhibit set").toBeTruthy();
  const cached = await page.evaluate(async (id) => {
    for (const n of (await caches.keys()).filter((k) => k.startsWith("exhibit-v"))) {
      if (await (await caches.open(n)).match(`/api/visitor/items/${id}`)) return true;
    }
    return false;
  }, target!.id);
  expect(cached, `item ${target!.id} is stored in the exhibit cache`).toBe(true);
  return target!;
}

test.describe("Offline kiosk", () => {
  test.describe.configure({ timeout: 180_000 });

  test("cached exhibit items open offline; Ask shows it needs a connection", async ({ page, context, api }) => {
    await page.goto("/?kiosk=1");
    const target = await cachedTimelineItem(page, api, await waitForExhibit(page));

    await context.setOffline(true);
    try {
      await page.getByRole("navigation", { name: "Main menu" }).getByRole("link", { name: "Timeline" }).click();
      await expect(page.getByRole("status").filter({ hasText: "Offline: showing items saved on this screen." })).toBeVisible();
      await expect(page.locator("ol.timeline > li").first()).toBeVisible();
      await page.locator(`ol.timeline a[href="/item/${target.id}"]`).first().click();
      await expect(page.getByRole("heading", { level: 1, name: target.title })).toBeVisible();
      await expect(page.locator(".banner.offline").first()).toBeVisible();
      await expect(page.getByRole("region", { name: "Approved text" }).locator(".passage").first()).toBeVisible();

      await page.getByRole("navigation", { name: "Main menu" }).getByRole("link", { name: "Ask (AI)" }).click();
      await expect(page.getByText("Asking needs a connection. Search and reading still work from saved items.").first()).toBeVisible();
      await page.getByRole("textbox", { name: "Ask the AI a question about the archive" }).fill("What did the reading room committee report?");
      await page.getByRole("button", { name: "Ask with AI", exact: true }).click();
      await expect(page.locator("article.answer .notice")).toHaveText("Asking needs a connection. Search and reading still work from saved items.");
      await expect(page.locator("article.answer .chip.ai")).toHaveCount(0);
    } finally {
      await context.setOffline(false);
    }
  });

  test("reloading a saved item's address while offline still opens it", async ({ page, context, api }) => {
    await page.goto("/?kiosk=1");
    const target = await cachedTimelineItem(page, api, await waitForExhibit(page));
    await page.goto(`/item/${target.id}`);
    await expect(page.getByRole("heading", { level: 1, name: target.title })).toBeVisible();
    await context.setOffline(true);
    try {
      await page.reload();
      await expect(page.getByRole("heading", { level: 1, name: target.title })).toBeVisible();
    } finally {
      await context.setOffline(false);
    }
  });

  test("after the lease runs out the kiosk shows the expired-cache notice", async ({ page, context }) => {
    await page.goto("/?kiosk=1");
    const manifest = await waitForExhibit(page);
    await context.setOffline(true);
    try {
      // The page checks the lease against its own clock: move it past lease_expires_at, then reopen from the precache.
      await page.clock.setFixedTime(Date.parse(manifest.lease_expires_at) + 60 * 60_000);
      await page.goto("/");
      await expect(page.getByRole("status").filter({ hasText: "Saved items have expired on this screen. Reconnect to the archive server to refresh them." }))
        .toBeVisible({ timeout: 30_000 });
    } finally {
      await context.setOffline(false);
    }
  });
});
