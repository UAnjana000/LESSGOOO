import { devices } from "@playwright/test";
import { test, expect, loginStaff } from "../fixtures";
import { E2E, FX } from "../env";
import { createPublishedItem, expireCollection, marker } from "../helpers/api";

test("compile a list, open its QR link on a phone, withdrawal and expiry reach the shared list", async ({ page, browser, fx, api }) => {
  test.setTimeout(600_000);
  const essay = fx.get(FX.essay);
  const title = `E2E withdraw-me ${marker()}: Letter to the Library Board (synthetic fixture)`;
  const doomedId = await createPublishedItem(api, title);

  // Kiosk visitor adds a passage from a fixture and the whole of the fresh item.
  await page.goto(`/item/${essay.id}`);
  await page.getByRole("region", { name: "Approved text" }).getByRole("button", { name: "Add to my list" }).first().click();
  await page.goto(`/item/${doomedId}`);
  await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
  await page.locator(".reader-head").getByRole("button", { name: "Add to my list" }).click();
  await expect(page.locator(".reader-head").getByRole("button", { name: "In my list" })).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("link", { name: /My list/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "My list" })).toBeVisible();
  await expect(page.locator("ul.results > li.result")).toHaveCount(2);
  const created = page.waitForResponse((r) => r.url().endsWith("/api/visitor/collections") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Get a QR code for my list" }).click();
  const col = await (await created).json();
  await expect(page.getByRole("img", { name: "QR code for your saved list" })).toBeVisible();
  await expect(page.locator(".qr svg")).toBeVisible();
  await expect(page.getByText(/The link works for 24 hours/)).toBeVisible();
  expect(col.url, "the QR encodes a link on this archive").toBe(`${E2E.baseURL}/c/${col.token}`);

  // Visitor's phone: a separate browser context with a phone viewport and no kiosk state.
  const phoneCtx = await browser.newContext({ ...devices["Pixel 7"], ignoreHTTPSErrors: true });
  const phone = await phoneCtx.newPage();
  const staffCtx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 900 } });
  const staff = await staffCtx.newPage();
  try {
    await phone.goto(col.url);
    await expect(phone.getByRole("heading", { level: 1, name: "Your saved list" })).toBeVisible();
    const entries = phone.locator("ul.results > li.result");
    await expect(entries).toHaveCount(2);
    await expect(entries.filter({ hasText: essay.title })).toHaveCount(1);
    await expect(entries.filter({ hasText: title })).toHaveCount(1);
    // Read-only: nothing on the shared page can change the list or reach the kiosk's tools.
    await expect(phone.getByRole("button", { name: /Remove|Add to my list|In my list/ })).toHaveCount(0);
    await expect(phone.getByRole("textbox")).toHaveCount(0);
    await expect(phone.getByRole("searchbox")).toHaveCount(0);
    await expect(phone.getByRole("navigation", { name: "Main menu" })).toHaveCount(0);
    await expect(phone.getByRole("button", { name: /^(Finish|High contrast|Text size)/ })).toHaveCount(0);
    const width = await phone.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
    expect(width, "no horizontal scrolling on the phone").toBeTruthy();

    // Staff withdraws the fresh item.
    await loginStaff(staff);
    await staff.goto(`/staff/items/${doomedId}`);
    await expect(staff.getByText("state: published")).toBeVisible();
    await staff.getByLabel("Withdrawal reason").fill("e2e: rights holder asked for removal");
    await staff.getByRole("button", { name: "Withdraw" }).click();
    await expect(staff.getByRole("status").filter({ hasText: "Withdrawn: removed from search, Ask, QR links and kiosk manifests." })).toBeVisible();

    await phone.reload();
    await expect(phone.getByText("1 items are no longer available and were removed.")).toBeVisible();
    await expect(entries).toHaveCount(1);
    await expect(entries.filter({ hasText: title })).toHaveCount(0);
    await expect(entries.filter({ hasText: essay.title })).toHaveCount(1);

    // Expired link: refused, with the visitor-facing explanation.
    expireCollection(col.token);
    await phone.reload();
    await expect(phone.getByText("This link has expired. Links from the archive screen work for 24 hours.")).toBeVisible();
    await expect(entries).toHaveCount(0);
    expect((await api.get(`/api/visitor/collections/${col.token}`)).status()).toBe(410);
  } finally {
    await phoneCtx.close();
    await staffCtx.close();
  }
});
