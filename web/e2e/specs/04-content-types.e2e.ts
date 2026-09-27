import { test, expect } from "../fixtures";
import { FX } from "../env";
import { marker, saveDraftSummary } from "../helpers/api";

const PHOTO_CAPTION = "Readers at a reading room in the fictional town of Samarpur, around 1925. Synthetic illustration generated for testing; not a historical photograph.";

test.describe("Photos, manuscripts and summaries", () => {
  test("photographs collection shows reviewed captions and credits", async ({ page, fx }) => {
    const photo = fx.get(FX.photo);
    await page.goto("/");
    await page.getByRole("link", { name: /Photographs/ }).click();
    await expect(page).toHaveURL(/collection=photographs/);
    await expect(page.getByRole("heading", { level: 1, name: "Photographs" })).toBeVisible();
    const card = page.locator("li.result").filter({ has: page.getByRole("link", { name: photo.title }) });
    await expect(card.getByRole("img", { name: PHOTO_CAPTION })).toBeVisible();
    await expect(card.locator(".card-caption")).toHaveText(PHOTO_CAPTION);
    await expect(card.getByText(/^Credit: /)).toBeVisible();

    await card.getByRole("link", { name: photo.title }).click();
    const facts = page.locator("dl.facts").first();
    await expect(facts.locator("dt", { hasText: /^Caption$/ })).toBeVisible();
    await expect(facts.locator("dd").first()).toHaveText(PHOTO_CAPTION);
    await expect(facts.locator("dt", { hasText: /^Place$/ })).toBeVisible();
    await expect(facts.locator("dt", { hasText: /^Rights$/ })).toBeVisible();
    await expect(page.locator(".chip", { hasText: /^Reviewed caption$/ }).first()).toBeVisible();
  });

  test("manuscript shows its scan with a reviewed transcription", async ({ page, fx }) => {
    const ms = fx.get(FX.manuscript);
    await page.goto("/search?collection=manuscripts");
    await page.getByRole("link", { name: ms.title }).click();
    await expect(page.getByRole("heading", { level: 1, name: ms.title })).toBeVisible();
    await expect(page.getByRole("group", { name: /^Original scan: / })).toBeVisible();
    const text = page.getByRole("region", { name: "Approved text" });
    await expect(text.getByRole("heading", { level: 2, name: "Reviewed transcription" })).toBeVisible();
    await expect(text.locator(".passage").first()).not.toBeEmpty();
    await expect(page.locator(".reader-head .meta")).toContainText("3 March 1927");
  });

  test("a reviewed summary is shown; a draft summary is not", async ({ page, fx, api }) => {
    const essay = fx.get(FX.essay);
    await page.goto(`/item/${essay.id}`);
    const summary = page.getByRole("region", { name: "Summary" });
    await expect(summary).toBeVisible();
    await expect(summary.locator(".chip")).toHaveText("Reviewed summary");
    await expect(summary).toContainText("first reading room opened in 1921");

    // A staff draft on an item with no approved summary must stay invisible to visitors.
    const ms = fx.get(FX.manuscript);
    const draft = `E2E draft summary ${marker()} that visitors must never see.`;
    await saveDraftSummary(api, ms.id, draft);
    await page.goto(`/item/${ms.id}`);
    await expect(page.getByRole("heading", { level: 1, name: ms.title })).toBeVisible();
    await expect(page.getByRole("region", { name: "Summary" })).toHaveCount(0);
    await expect(page.getByText(draft)).toHaveCount(0);
    const detail = await (await api.get(`/api/visitor/items/${ms.id}`)).json();
    expect(JSON.stringify(detail)).not.toContain(draft);
  });
});
