import { test, expect } from "../fixtures";

test.describe("Timeline, stories, connections and signage", () => {
  test("timeline lists dated events that open their items", async ({ page, api }) => {
    const events: { titles: Record<string, string>; items: { id: number }[] }[] = await (await api.get("/api/visitor/timeline")).json();
    expect(events.length).toBeGreaterThan(0);
    await page.goto("/");
    await page.getByRole("navigation", { name: "Main menu" }).getByRole("link", { name: "Timeline" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Timeline" })).toBeVisible();
    const rows = page.locator("ol.timeline > li");
    await expect(rows).toHaveCount(events.length);
    await expect(rows.first().locator(".date")).not.toBeEmpty();
    await expect(rows.first().getByRole("heading", { level: 2, name: events[0].titles.en })).toBeVisible();
    const withItem = rows.filter({ has: page.locator('a[href^="/item/"]') }).first();
    await withItem.locator('a[href^="/item/"]').first().click();
    await expect(page).toHaveURL(/\/item\/\d+/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });

  test("story page shows captioned blocks with citations", async ({ page }) => {
    await page.goto("/stories");
    await expect(page.getByRole("heading", { level: 1, name: "Stories" })).toBeVisible();
    await page.locator('a.story-card[href="/stories/samarpur-reading-rooms"]').click();
    await expect(page).toHaveURL(/\/stories\/samarpur-reading-rooms$/);
    const blocks = page.locator("section.story-block");
    await expect(blocks.first()).toBeVisible();
    expect(await blocks.count()).toBeGreaterThan(1);
    await expect(blocks.first().locator(".cite")).toContainText("Cite as:");
    await blocks.first().getByRole("link", { name: "Open" }).click();
    await expect(page).toHaveURL(/\/item\/\d+/);
  });

  test("connections: choosing a name shows its links and the items that support them", async ({ page }) => {
    await page.goto("/map");
    await expect(page.getByRole("heading", { level: 1, name: "Connections" })).toBeVisible();
    const names = page.getByRole("region", { name: "All names on the map" });
    const person = names.getByRole("group", { name: "Person" }).getByRole("button").first();
    const label = (await person.innerText()).trim();
    await person.click();
    await expect(person).toHaveAttribute("aria-pressed", "true");
    const aside = page.locator("aside.sheet");
    await expect(aside.getByRole("heading", { level: 2, name: label })).toBeVisible();
    await expect(aside.getByRole("heading", { level: 3, name: "Connected to" })).toBeVisible();
    await expect(aside.getByRole("heading", { level: 3, name: "Supported by" })).toBeVisible();
    await expect(aside.locator("ul > li").first()).toBeVisible();
    const evidence = aside.locator('a[href^="/item/"]').first();
    await expect(evidence).toBeVisible();
    await evidence.click();
    await expect(page).toHaveURL(/\/item\/\d+/);
  });

  test("/display rotates approved slides unattended", async ({ page, api }) => {
    const sig = await (await api.get("/api/visitor/signage")).json();
    const total = (sig.story?.blocks.length ?? 0) + sig.timeline.length;
    expect(total).toBeGreaterThan(1);
    await page.clock.install();
    await page.goto("/display");
    await expect(page.getByRole("heading", { level: 1, name: "Dr. B. R. Ambedkar Digital Heritage Archive" })).toBeVisible();
    const counter = page.locator("main.signage footer span").nth(1);
    await expect(counter).toHaveText(`1 / ${total}`);
    const first = await page.locator(".slide").innerText();
    await page.clock.runFor(sig.slide_seconds * 1000 + 100);
    await expect(counter).toHaveText(`2 / ${total}`);
    await expect(page.locator(".slide")).not.toHaveText(first);
    await page.clock.runFor((total - 1) * sig.slide_seconds * 1000);
    await expect(counter).toHaveText(`1 / ${total}`);
    await expect(page.locator("main.signage footer span").first()).toContainText("Demonstration content");
    // Unattended screen: no controls to press.
    await expect(page.getByRole("button")).toHaveCount(0);
    await expect(page.getByRole("link")).toHaveCount(0);
  });
});
