import type { Page } from "@playwright/test";
import { test, expect } from "../fixtures";
import { FX } from "../env";
import { catalog, findItem, type ItemCard } from "../helpers/api";

const titlesOnPage = (page: Page) =>
  page.locator("ul.results > li.result h2 a").allInnerTexts().then((t) => t.map((s) => s.trim()).sort());

const expected = (items: ItemCard[], keep: (i: ItemCard) => boolean) => items.filter(keep).map((i) => i.title).sort();

/** A filter select inside the search filters. Its accessible name is the label plus the selected option. */
const filter = (page: Page, label: string) =>
  page.locator("fieldset.filters").getByRole("combobox", { name: new RegExp(`^${label}\\b`) });

// Other specs publish and withdraw items, so each test reads the live catalog rather than the worker cache.
test.describe("Facets and filters", () => {
  test("browse by subject, person and place tags", async ({ page, api }) => {
    const items = await catalog(api);
    const cases = [
      { label: "Subject", param: "subject", value: "Reading rooms", key: "subjects" },
      { label: "Person", param: "person", value: "Member Rao (fictional)", key: "people" },
      { label: "Place", param: "place", value: "Samarpur (fictional)", key: "places" },
    ] as const;
    for (const c of cases) {
      const want = expected(items, (i) => i[c.key].includes(c.value));
      expect(want.length, `seeded items tagged ${c.value}`).toBeGreaterThan(0);
      await page.goto("/search");
      await filter(page, c.label).selectOption(c.value);
      await expect(page).toHaveURL(new RegExp(`[?&]${c.param}=`));
      await expect.poll(() => titlesOnPage(page), { message: `${c.label} = ${c.value}` }).toEqual(want);
      await page.getByRole("button", { name: "Clear filters" }).click();
      await expect.poll(() => titlesOnPage(page)).toEqual(items.map((i) => i.title).sort());
    }
  });

  test("a tag chip in the reader opens the filtered list", async ({ page, api }) => {
    const items = await catalog(api);
    const proceedings = findItem(items, FX.proceedings);
    const tag = proceedings.people[0];
    expect(tag, "the proceedings fixture has a person tag").toBeTruthy();
    await page.goto(`/item/${proceedings.id}`);
    await page.getByRole("region", { name: "Where this comes from" }).getByRole("link", { name: tag, exact: true }).click();
    await expect(page).toHaveURL(/[?&]person=/);
    await expect(filter(page, "Person")).toHaveValue(tag);
    await expect.poll(() => titlesOnPage(page)).toEqual(expected(items, (i) => i.people.includes(tag)));
  });

  test("date range narrows search results to that period", async ({ page, api }) => {
    const items = await catalog(api);
    const proceedings = findItem(items, FX.proceedings);
    await page.goto("/search?q=library%20board");
    await expect(page.getByRole("status").filter({ hasText: /\d+ results/ })).toBeVisible();
    await page.getByLabel("From date").fill("1927-01-01");
    await page.getByLabel("To date").fill("1927-12-31");
    await expect(page).toHaveURL(/date_from=1927-01-01/);
    await expect(page).toHaveURL(/date_to=1927-12-31/);
    await expect(page.getByRole("status").filter({ hasText: /\d+ results/ })).toBeVisible();
    const dates = new Map(items.map((i) => [i.title, i.date_text ?? "(no date)"]));
    const hits = (await page.locator("ul.results > li.result h2 a").allInnerTexts()).map((h) => h.trim());
    expect(hits).toContain(proceedings.title);
    for (const h of hits) expect(dates.get(h) ?? "(not in catalog)", `"${h}" is dated within 1927`).toMatch(/1927/);
  });

  test("collection, type and language filters combine", async ({ page, api }) => {
    const items = await catalog(api);
    await page.goto("/search");
    await filter(page, "Collections").selectOption("speeches");
    await expect.poll(() => titlesOnPage(page)).toEqual(expected(items, (i) => i.collection === "speeches"));
    await filter(page, "Type").selectOption("printed_scan");
    await expect.poll(() => titlesOnPage(page)).toEqual(expected(items, (i) => i.collection === "speeches" && i.item_type === "printed_scan"));
    await filter(page, "Language").selectOption("hi");
    await expect(page.getByText("No published items in this collection yet.")).toBeVisible();
  });
});
