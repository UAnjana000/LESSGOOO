import type { Page } from "@playwright/test";
import { test, expect, axeScan, type Catalog } from "../fixtures";
import { FX } from "../env";

interface Route {
  name: string;
  path: (fx: Catalog, extra: { token: string }) => string;
  ready: (page: Page) => Promise<void>;
  before?: (page: Page) => Promise<void>;
}

const h1 = (page: Page) => expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();

const ROUTES: Route[] = [
  { name: "home", path: () => "/", ready: async (p) => { await h1(p); await expect(p.locator("ul.drawers li").first()).toBeVisible(); } },
  { name: "home (high contrast, 130% text)", path: () => "/", ready: h1, before: async (p) => {
    await p.getByRole("button", { name: "High contrast" }).click();
    const size = p.getByRole("button", { name: /^Text size/ });
    await size.click();
    await size.click();
  } },
  { name: "home (Hindi)", path: () => "/", ready: h1, before: async (p) => { await p.getByRole("button", { name: "हिन्दी" }).click(); } },
  { name: "search results", path: () => "/search?q=reading%20room", ready: async (p) => { await expect(p.getByRole("status").filter({ hasText: /results/ })).toBeVisible(); } },
  { name: "browse photographs", path: () => "/search?collection=photographs", ready: async (p) => { await expect(p.locator("li.result").first()).toBeVisible(); } },
  { name: "reader: essay with translation", path: (fx) => `/item/${fx.get(FX.essay).id}`, ready: async (p) => { await expect(p.getByRole("region", { name: "Approved text" })).toBeVisible(); } },
  { name: "reader: debate with Constitution link", path: (fx) => `/item/${fx.get(FX.proceedings).id}`, ready: async (p) => { await expect(p.getByRole("region", { name: "Approved text" })).toBeVisible(); } },
  { name: "reader: photograph", path: (fx) => `/item/${fx.get(FX.photo).id}`, ready: async (p) => { await expect(p.locator("dl.facts").first()).toBeVisible(); } },
  { name: "reader: audio", path: (fx) => `/item/${fx.get(FX.audio).id}`, ready: async (p) => { await expect(p.getByRole("region", { name: "Reviewed transcript" })).toBeVisible(); } },
  { name: "reader: video", path: (fx) => `/item/${fx.get(FX.video).id}`, ready: async (p) => { await expect(p.getByRole("region", { name: "Reviewed transcript" })).toBeVisible(); } },
  { name: "ask", path: () => "/ask", ready: h1 },
  { name: "timeline", path: () => "/timeline", ready: async (p) => { await expect(p.locator("ol.timeline > li").first()).toBeVisible(); } },
  { name: "stories", path: () => "/stories", ready: async (p) => { await expect(p.locator("a.story-card").first()).toBeVisible(); } },
  { name: "story", path: () => "/stories/samarpur-reading-rooms", ready: async (p) => { await expect(p.locator("section.story-block").first()).toBeVisible(); } },
  { name: "connections", path: () => "/map", ready: async (p) => { await expect(p.getByRole("region", { name: "All names on the map" })).toBeVisible(); } },
  { name: "connections (name chosen)", path: () => "/map", ready: async (p) => { await expect(p.locator("aside h2")).toBeVisible(); }, before: async (p) => {
    await p.getByRole("region", { name: "All names on the map" }).getByRole("button").first().click();
  } },
  { name: "constitution index", path: () => "/constitution", ready: async (p) => { await expect(p.locator("li.result").first()).toBeVisible(); } },
  { name: "constitution article", path: () => "/constitution/41", ready: async (p) => { await expect(p.locator("li.result").first()).toBeVisible(); } },
  { name: "my list with QR", path: (fx) => `/item/${fx.get(FX.lecture).id}`, ready: async (p) => { await expect(p.getByRole("img", { name: "QR code for your saved list" })).toBeVisible(); }, before: async (p) => {
    await p.locator(".reader-head").getByRole("button", { name: "Add to my list" }).click();
    await p.getByRole("link", { name: /My list/ }).click();
    await p.getByRole("button", { name: "Get a QR code for my list" }).click();
  } },
  { name: "shared list on a phone", path: (_fx, x) => `/c/${x.token}`, ready: async (p) => { await expect(p.locator("li.result").first()).toBeVisible(); } },
  { name: "signage display", path: () => "/display", ready: async (p) => { await expect(p.locator(".slide")).toBeVisible(); } },
];

test.describe("Accessibility (axe, WCAG 2.2 AA rules)", () => {
  let token = "";
  test.beforeAll(async ({ api }) => {
    const items: { id: number; title: string }[] = await (await api.get("/api/visitor/items")).json();
    const essay = items.find((i) => i.title.includes(FX.essay))!;
    const r = await api.post("/api/visitor/collections", { data: { entries: [{ item_id: essay.id }], language: "en" } });
    expect(r.ok()).toBeTruthy();
    token = (await r.json()).token;
  });

  for (const route of ROUTES) {
    test(route.name, async ({ page, fx }, testInfo) => {
      if (route.name === "shared list on a phone") await page.setViewportSize({ width: 412, height: 915 });
      await page.goto(route.path(fx, { token }));
      await route.before?.(page);
      await route.ready(page);
      await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => undefined);
      const summary = await axeScan(page, testInfo, route.name);
      const blocking = summary.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      for (const v of summary.violations) {
        testInfo.annotations.push({ type: `axe ${v.impact}`, description: `${v.id}: ${v.help} (${v.nodes} nodes) ${v.targets.join(" | ")}` });
      }
      expect(blocking.map((v) => `${v.impact} ${v.id}: ${v.help} [${v.targets.join(" | ")}]`), `serious or critical axe violations on ${route.name}`).toEqual([]);
    });
  }
});
