import { test, expect } from "../fixtures";
import { FX } from "../env";

test("Constitution article lists its curated debate passages and opens the original", async ({ page, fx }) => {
  const proceedings = fx.get(FX.proceedings);
  await page.goto("/");
  await page.getByRole("navigation", { name: "Main menu" }).getByRole("link", { name: "Constitution" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "The Constitution in the debates" })).toBeVisible();
  const row = page.locator("li.result").filter({ has: page.getByRole("link", { name: "Article 41", exact: true }) });
  await expect(row.locator(".chip", { hasText: /\d+ debate passages/ })).toBeVisible();
  await row.getByRole("link", { name: "Article 41", exact: true }).click();

  await expect(page).toHaveURL(/\/constitution\/41$/);
  await expect(page.getByRole("heading", { level: 1, name: /^Article 41/ })).toBeVisible();
  await expect(page.getByText("Archive staff chose each link between an article and a debate passage.", { exact: false })).toBeVisible();
  const entry = page.locator("li.result").filter({ has: page.getByRole("link", { name: proceedings.title }) }).first();
  await expect(entry).toBeVisible();
  await expect(entry.locator("blockquote")).not.toBeEmpty();
  await expect(entry).toContainText("Curator's note:");
  await expect(entry).toContainText("Synthetic demonstration link on a fictional debate; not a historical claim.");

  await entry.getByRole("link", { name: "Open original" }).click();
  await expect(page).toHaveURL(new RegExp(`/item/${proceedings.id}\\?`));
  await expect(page.getByRole("heading", { level: 1, name: proceedings.title })).toBeVisible();
  await expect(page.getByRole("region", { name: "Approved text" }).locator(".passage.target")).toHaveCount(1);
  await expect(page.getByRole("link", { name: /^Article 41/ }).first()).toBeVisible();
});
