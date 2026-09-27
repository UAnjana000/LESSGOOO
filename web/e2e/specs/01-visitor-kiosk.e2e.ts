import { test, expect } from "../fixtures";
import { FX } from "../env";

test.describe("Visitor on a kiosk", () => {
  test("home → keyword search → result → reader shows scan beside text, cited passage marked", async ({ page, fx }) => {
    const essay = fx.get(FX.essay);
    await page.goto("/?kiosk=1");
    await expect(page.getByRole("heading", { level: 1, name: "Dr. B. R. Ambedkar Digital Heritage Archive" })).toBeVisible();
    await expect(page.getByText(/^Demonstration content:/)).toBeVisible();

    await page.getByRole("searchbox", { name: "Search the archive" }).fill("reading room mill shifts");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page).toHaveURL(/\/search\?q=reading/);
    await expect(page.getByRole("status").filter({ hasText: /\d+ results/ })).toBeVisible();

    const result = page.locator("li.result").filter({ has: page.getByRole("link", { name: essay.title }) }).first();
    await expect(result).toBeVisible();
    await result.getByRole("link", { name: "Open" }).click();

    await expect(page).toHaveURL(new RegExp(`/item/${essay.id}\\?.*passage=\\d+`));
    await expect(page.getByRole("heading", { level: 1, name: essay.title })).toBeVisible();
    const scan = page.getByRole("group", { name: new RegExp(`^Original scan: .*Page \\d+`) });
    const text = page.getByRole("region", { name: "Approved text" });
    await expect(scan).toBeVisible();
    await expect(text).toBeVisible();

    // Side by side at kiosk width: the scan pane starts left of the text pane on the same row.
    const [s, t] = [await scan.boundingBox(), await text.boundingBox()];
    expect(s && t, "scan and text panes are laid out").toBeTruthy();
    expect(s!.x + s!.width).toBeLessThanOrEqual(t!.x + 2);
    expect(Math.abs(s!.y - t!.y)).toBeLessThan(200);

    await expect(text.locator(".passage.target")).toHaveCount(1);
  });

  test("search result opens the reader with the cited region outlined on the scan", async ({ page, boxed }) => {
    const query = boxed.text.split(/\s+/).slice(0, 8).join(" ");
    await page.goto("/search");
    await page.getByRole("searchbox", { name: "Search the archive" }).fill(query);
    await page.getByRole("button", { name: "Search", exact: true }).click();
    const open = page.locator(`li.result a.btn[href*="/item/${boxed.itemId}"][href*="passage=${boxed.passageId}"]`);
    await expect(open, `search for "${query}" lists passage ${boxed.passageId}`).toBeVisible();
    await open.click();
    const scan = page.getByRole("group", { name: /^Original scan: .*, Page .+$/ });
    await expect(scan).toBeVisible();
    await expect(page.getByRole("region", { name: "Approved text" }).locator(".passage.target")).toHaveCount(1);
    // ScanViewer draws each word box of the cited passage as a brass-bordered overlay on the image.
    await expect(scan.locator('.osd div[style*="201, 162, 74"]').first()).toBeAttached({ timeout: 20_000 });
  });

  test("Hindi query finds Hindi material", async ({ page, fx }) => {
    const pamphlet = fx.get(FX.pamphletHi);
    await page.goto("/");
    await page.getByRole("searchbox", { name: "Search the archive" }).fill("सार्वजनिक वाचनालय");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: /\d+ results/ })).toBeVisible();
    const hit = page.locator("li.result").filter({ has: page.getByRole("link", { name: pamphlet.title }) }).first();
    await expect(hit).toBeVisible();
    await expect(hit.locator('.meta span[lang="hi"]')).toHaveText("हिन्दी");
    await expect(hit.locator('blockquote[lang="hi"]')).toBeVisible();
  });

  test("label chips: reviewed transcription on a scan, reviewed translation tab", async ({ page, fx }) => {
    const lecture = fx.get(FX.lecture);
    await page.goto(`/item/${lecture.id}`);
    await expect(page.getByRole("heading", { level: 2, name: "Reviewed transcription" })).toBeVisible();
    await expect(page.locator(".chip", { hasText: /^Reviewed transcription$/ }).first()).toBeVisible();

    const essay = fx.get(FX.essay);
    await page.goto(`/item/${essay.id}`);
    await page.getByRole("button", { name: "हिन्दी" }).click();
    const reviewedTab = page.getByRole("tab", { name: "समीक्षित अनुवाद" });
    await expect(reviewedTab).toBeVisible();
    await reviewedTab.click();
    await expect(reviewedTab).toHaveAttribute("aria-selected", "true");
    await expect(page.locator('.passage[lang="hi"]').first()).toBeVisible();
    await expect(page.locator(".chip", { hasText: "समीक्षित अनुवाद" }).first()).toBeVisible();
  });

  test("machine translation chip reads 'Machine translation — not reviewed'", async ({ page, fx, api }) => {
    const config = await (await api.get("/api/visitor/config")).json();
    test.skip(!config.machine_translation.available,
      "Machine translation needs Sarvam; the e2e stack has no Sarvam key (no live Sarvam calls from tests).");
    const lecture = fx.get(FX.lecture);
    await page.goto(`/item/${lecture.id}`);
    await page.getByRole("button", { name: "हिन्दी" }).click();
    await page.getByRole("button", { name: /Machine-translate|मशीन/ }).first().click();
    await expect(page.locator(".chip.mt").first()).toBeVisible();
  });

  test("language switch EN → HI → MR relabels the interface", async ({ page }) => {
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "Main menu" });
    await expect(nav.getByRole("link", { name: "Search" })).toBeVisible();

    await page.getByRole("button", { name: "हिन्दी" }).click();
    await expect(page.getByRole("button", { name: "हिन्दी" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("html")).toHaveAttribute("lang", "hi");
    await expect(page.getByRole("link", { name: "खोजें" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: "डॉ. बी. आर. आंबेडकर डिजिटल विरासत अभिलेखागार" })).toBeVisible();

    await page.getByRole("button", { name: "मराठी" }).click();
    await expect(page.locator("html")).toHaveAttribute("lang", "mr");
    await expect(page.getByRole("link", { name: "शोधा" })).toBeVisible();

    await page.getByRole("button", { name: "English" }).click();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
  });

  test("text size cycles and high contrast toggles", async ({ page }) => {
    await page.goto("/");
    const size = page.getByRole("button", { name: /^Text size: \d+%$/ });
    await expect(size).toHaveAccessibleName("Text size: 100%");
    const before = await page.locator("h1").evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    await size.click();
    await expect(size).toHaveAccessibleName("Text size: 115%");
    await expect.poll(() => page.locator("h1").evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThan(before);
    await size.click();
    await expect(size).toHaveAccessibleName("Text size: 130%");
    await size.click();
    await expect(size).toHaveAccessibleName("Text size: 100%");

    const contrast = page.getByRole("button", { name: "High contrast" });
    await expect(contrast).toHaveAttribute("aria-pressed", "false");
    const bg = await page.locator("body").evaluate((el) => getComputedStyle(el).backgroundColor);
    await contrast.click();
    await expect(contrast).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("html")).toHaveAttribute("data-contrast", "high");
    await expect.poll(() => page.locator("body").evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe(bg);
    await contrast.click();
    await expect(contrast).toHaveAttribute("aria-pressed", "false");
  });

  test("kiosk idle: warning after inactivity, then the attract screen, and Finish clears the list", async ({ page, fx }) => {
    await page.clock.install();
    const essay = fx.get(FX.essay);
    await page.goto(`/item/${essay.id}?kiosk=1`);
    await page.getByRole("button", { name: "Add to my list" }).first().click();
    await expect(page.getByRole("link", { name: /My list/ })).toContainText("1");

    await page.clock.fastForward("01:31");
    await expect(page.getByRole("dialog", { name: "Are you still there?" })).toBeVisible();
    await page.clock.fastForward("00:31");
    const attract = page.getByRole("button", { name: /Touch to explore the archive/ });
    await expect(attract).toBeVisible();
    await expect(page).toHaveURL(/\/$/);
    await attract.click();
    await expect(page.getByRole("link", { name: /My list/ })).not.toContainText("1");

    await page.getByRole("button", { name: "Finish" }).click();
    await expect(page.getByRole("dialog", { name: "Finish your visit?" })).toBeVisible();
    await page.getByRole("button", { name: "Yes, finish" }).click();
    await expect(page.getByRole("dialog", { name: "Finish your visit?" })).toBeHidden();
  });
});
