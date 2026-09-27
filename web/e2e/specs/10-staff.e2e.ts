import type { BrowserContext, Locator, Page } from "@playwright/test";
import { test, expect, loginStaff } from "../fixtures";
import { marker, staffToken, uniquePng, waitForIngestion, type Json } from "../helpers/api";

// One synthetic two-page capture goes through the whole archivist workflow, in order.
test.describe("Archivist workspace", () => {
  test.describe.configure({ mode: "serial", timeout: 420_000 });

  const m = marker();
  const title = `E2E staff capture ${m}: Letter to the Library Board (synthetic fixture)`;
  const articleNo = `${100 + Math.floor(Math.random() * 900)}${String.fromCharCode(65 + Math.floor(Math.random() * 26))}Z`;
  let ctx: BrowserContext;
  let page: Page;
  let itemId = 0;
  let passageId = 0;
  let passageLink = "";

  const status = (text: string | RegExp) => page.getByRole("status").filter({ hasText: text });
  const openItem = async () => {
    await page.goto(`/staff/items/${itemId}`);
    await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
  };

  test.beforeAll(async ({ browser }) => {
    ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1000 } });
    page = await ctx.newPage();
  });
  test.afterAll(async () => {
    await ctx?.close();
  });

  test("sign in and see the dashboard", async () => {
    await loginStaff(page);
    await expect(page.getByRole("navigation", { name: "Staff" })).toBeVisible();
    await expect(page.getByText("Not configured: failed pages stay pending")).toBeVisible();
  });

  test("intake a synthetic two-page capture", async () => {
    await page.getByRole("navigation", { name: "Staff" }).getByRole("link", { name: "Intake" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Intake" })).toBeVisible();
    await page.getByLabel("Title").fill(title);
    await page.getByLabel("Rights register entry").selectOption("fx-open");
    await page.getByLabel("Item type").selectOption("printed_scan");
    await page.getByLabel("Document class (sets the OCR route)").selectOption("printed");
    await page.getByLabel("Collection").selectOption("writings");
    await page.getByLabel("Access").selectOption("public");
    await page.getByLabel("Languages (comma separated: en, hi, mr)").fill("en");
    await page.getByLabel("Operator").fill("e2e-suite");
    await page.getByLabel("Files").setInputFiles([
      { name: `capture-${m}-1.png`, mimeType: "image/png", buffer: uniquePng(`${m}-1`) },
      { name: `capture-${m}-2.png`, mimeType: "image/png", buffer: uniquePng(`${m}-2`) },
    ]);
    await page.getByRole("button", { name: "Store and queue ingestion" }).click();
    await expect(status("Stored. Ingestion job queued.")).toBeVisible({ timeout: 60_000 });
    const link = page.getByRole("link", { name: /^#\d+$/ });
    itemId = Number((await link.innerText()).slice(1));
    expect(itemId).toBeGreaterThan(0);
    const stored = page.getByRole("table", { name: "Stored files" });
    await expect(stored.getByRole("row")).toHaveCount(3);
    await expect(stored).not.toContainText("duplicate");
  });

  test("sample check: failing the batch sends every page to full review", async ({ api }) => {
    const token = await staffToken(api);
    const item = await waitForIngestion(api, token, itemId);
    const open = (item.batches ?? []).find((b: Json) => b.status === "open");
    test.info().annotations.push({ type: "pages after ingestion", description: item.pages.map((p: Json) => `${p.sequence}:${p.status}/${p.ocr_route}`).join(", ") });
    expect(open, "both pages passed the OCR gate and were grouped into a sample-check batch").toBeTruthy();

    await page.getByRole("navigation", { name: "Staff" }).getByRole("link", { name: "Review queue" }).click();
    const row = page.locator("p").filter({ hasText: `(item ${itemId},` });
    await row.getByRole("link", { name: "Check sample" }).click();
    await expect(page.getByRole("heading", { level: 1, name: `Batch ${open.id}` })).toBeVisible();
    await page.getByRole("button", { name: "Fail batch" }).click();
    await expect(status("Batch failed: every page moves to full review.")).toBeVisible();
    await openItem();
    const pages = page.getByRole("table", { name: "Pages of this item" });
    await expect(pages.getByRole("row").filter({ hasText: "needs_full_review" })).toHaveCount(2);
  });

  test("page review: approve page 1 as read, correct page 2", async () => {
    await openItem();
    const pages = page.getByRole("table", { name: "Pages of this item" });

    await pages.getByRole("row").nth(1).getByRole("link", { name: "Open" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Page 1" })).toBeVisible();
    const scan1 = page.getByRole("img", { name: "Scan of page 1" });
    await expect(scan1).toBeVisible();
    expect(await scan1.evaluate((img: HTMLImageElement) => img.naturalWidth), "the scan decodes as an image").toBeGreaterThan(0);
    const text1 = page.getByLabel("Text to approve");
    await expect(text1).not.toHaveValue("");
    await page.getByRole("checkbox", { name: /I compared this text with the original scan word for word/ }).check();
    await page.getByRole("button", { name: "Approve this text" }).click();
    await expect(status("Page decision recorded: Approve. Recorded quote verification. Showing the next page in the review queue.")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: "Page 2" }), "moves on to the next queued page of the same item").toBeVisible();

    const text2 = page.getByLabel("Text to approve");
    await expect(text2).not.toHaveValue("");
    await text2.fill(`${await text2.inputValue()}\nCorrected by the archivist (${m}).`);
    const page2Url = page.url();
    await page.getByRole("button", { name: "Approve this text" }).click();
    await expect(status(/^Page decision recorded: Correct\./)).toBeVisible();
    expect(page.url(), "leaves the reviewed page").not.toBe(page2Url);

    await openItem();
    await pages.getByRole("row").nth(1).getByRole("link", { name: "Open" }).click();
    await expect(page.getByText("status: approved")).toBeVisible();
    await expect(page.getByText("quote-verified", { exact: true })).toBeVisible();
    await expect(page.getByRole("table", { name: "Review decisions" }).getByRole("row").filter({ hasText: "verify_quote" })).toBeVisible();

    await openItem();
    await pages.getByRole("row").nth(2).getByRole("link", { name: "Open" }).click();
    await expect(page.getByText("status: approved")).toBeVisible();
    await expect(page.getByText("not quote-verified", { exact: true }), "no comparison was confirmed for page 2").toBeVisible();
    await expect(page.getByRole("table", { name: "Review decisions" }).getByRole("row").filter({ hasText: "correct" }).first()).toBeVisible();
  });

  test("Sarvam-vs-local diff can be reviewed when a fixture has one", async ({ api }) => {
    const ready = await (await api.get("/api/health/ready")).json();
    test.skip(!ready.sarvam_configured,
      "The e2e stack has no Sarvam key (no live Sarvam calls from tests), so no local-vs-Sarvam OCR diff exists.");
    const token = await staffToken(api);
    const auth = { Authorization: `Bearer ${token}` };
    const items: Json[] = await (await api.get("/api/staff/items", { headers: auth })).json();
    let diffPage: Json | null = null;
    for (const it of items) {
      const r = await api.get(`/api/staff/items/${it.id}`, { headers: auth });
      if (!r.ok()) continue;
      const detail = await r.json();
      for (const p of detail.pages ?? []) {
        const pd: Json = await (await api.get(`/api/staff/pages/${p.id}`, { headers: auth })).json();
        if (Array.isArray(pd.diff) && pd.diff.length > 0 && pd.status !== "approved") { diffPage = pd; break; }
      }
      if (diffPage) break;
    }
    test.skip(!diffPage, "No page on this stack has both a local and a Sarvam OCR result.");
    await page.goto(`/staff/pages/${diffPage!.id}`);
    await expect(page.getByRole("heading", { level: 3, name: "Local OCR compared with Sarvam" })).toBeVisible();
    await page.getByRole("button", { name: "Approve this text" }).click();
    await expect(page.getByText("status: approved")).toBeVisible();
  });

  test("publish: staged version switched in atomically", async () => {
    await openItem();
    await expect(page.getByText("All review gates passed.")).toBeVisible();
    await page.getByRole("button", { name: "Publish", exact: true }).click();
    await expect(status("Publication queued.")).toBeVisible();
    await expect.poll(async () => {
      await page.reload();
      return page.locator(".chip", { hasText: /^state: / }).first().innerText();
    }, { message: "item reaches published", timeout: 300_000, intervals: [3000, 5000, 5000, 10_000] }).toBe("state: published");
    await expect(page.locator(".chip", { hasText: /^version / }).first()).toHaveText("version 1");
    await page.getByRole("link", { name: "Open visitor view" }).click();
    await expect(page).toHaveURL(new RegExp(`/item/${itemId}$`));
    await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
    await page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: "Page 2" }).click();
    await expect(page.getByRole("region", { name: "Approved text" })).toContainText(`Corrected by the archivist (${m}).`);
  });

  test("edit descriptive metadata tags; visitors see them", async ({ api }) => {
    await openItem();
    const version = Number((await page.locator(".chip", { hasText: /^metadata version / }).innerText()).replace(/\D+/g, ""));
    await page.getByLabel("Subjects (comma separated)").fill(`Libraries, E2E subject ${m}`);
    await page.getByLabel("People (comma separated)").fill(`E2E person ${m} (fictional)`);
    await page.getByLabel("Places (comma separated)").fill("Samarpur (fictional)");
    await page.getByLabel("Reason for this change (recorded in the history and audit log)").fill(`e2e tagging ${m}`);
    await page.getByRole("button", { name: "Save metadata" }).click();
    await expect(status("Descriptive metadata saved.")).toBeVisible();
    await expect(page.locator(".chip", { hasText: /^metadata version / })).toHaveText(`metadata version ${version + 1}`);
    await page.getByText("Change history").click();
    await expect(page.getByRole("table", { name: "Metadata change history" }).getByRole("row").filter({ hasText: `e2e tagging ${m}` })).toBeVisible();

    const facets = await (await api.get("/api/visitor/facets")).json();
    expect(facets.subjects).toContain(`E2E subject ${m}`);
    const visitor = await ctx.newPage();
    await visitor.goto(`/item/${itemId}`);
    const prov = visitor.getByRole("region", { name: "Where this comes from" });
    await expect(prov.getByRole("link", { name: `E2E subject ${m}` })).toBeVisible();
    await expect(prov.getByRole("link", { name: `E2E person ${m} (fictional)` })).toBeVisible();
    await visitor.close();
  });

  test("add a curated Constitution link; it appears on the article page", async () => {
    await openItem();
    await page.getByText("Article not in the list? Add it").click();
    await page.getByLabel("Article number").fill(articleNo);
    await page.getByLabel("English title").fill(`E2E test article ${m}`);
    await page.getByRole("button", { name: "Add article" }).click();
    await expect(status(`Article ${articleNo} added.`)).toBeVisible();

    await page.getByRole("combobox", { name: /^Passage/ }).selectOption({ index: 1 });
    await expect(page.getByRole("combobox", { name: /^Article/ })).toHaveValue(articleNo);
    await page.getByLabel("Note for visitors (optional)").fill(`E2E curator note ${m}`);
    await page.getByRole("button", { name: "Add a link" }).click();
    await expect(status(`Linked to Article ${articleNo}. Visitors see it on the Constitution page.`)).toBeVisible();
    await expect(page.getByRole("table", { name: "Constitution links for this item" })).toContainText(`Article ${articleNo}`);

    const visitor = await ctx.newPage();
    await visitor.goto(`/constitution/${articleNo}`);
    await expect(visitor.getByRole("heading", { level: 1, name: new RegExp(`^Article ${articleNo}`) })).toBeVisible();
    const entry = visitor.locator("li.result").filter({ has: visitor.getByRole("link", { name: title }) });
    await expect(entry).toContainText(`E2E curator note ${m}`);
    await visitor.close();
  });

  test("approve a summary: hidden while draft, shown once approved", async ({ api }) => {
    const text = `E2E reviewed summary ${m}: a synthetic letter asking the library board to publish its new books.`;
    await openItem();
    await page.getByLabel("Summary text (leave empty to ask the model for a draft)").fill(text);
    await page.getByRole("button", { name: "Save human draft" }).click();
    await expect(status("Human draft saved. Approve it below to show it to visitors.")).toBeVisible();
    const block = page.locator("div.stack").filter({ has: page.getByText(text, { exact: true }) }).last();
    await expect(block.locator(".chip", { hasText: /^draft$/ })).toBeVisible();
    await expect(block.getByText("not visible to visitors")).toBeVisible();
    expect(JSON.stringify(await (await api.get(`/api/visitor/items/${itemId}`)).json())).not.toContain(text);

    await block.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(status("Approved. Visitors now see it labelled “Reviewed summary”.")).toBeVisible();
    const visitor = await ctx.newPage();
    await visitor.goto(`/item/${itemId}`);
    const summary = visitor.getByRole("region", { name: "Summary" });
    await expect(summary).toContainText(text);
    await expect(summary.locator(".chip")).toHaveText("Reviewed summary");
    await visitor.close();
  });

  test("withdraw: the item disappears for visitors", async ({ api }) => {
    const published = await (await api.get(`/api/visitor/items/${itemId}`)).json();
    passageId = published.pages[0].passages[0].id;
    passageLink = `/item/${itemId}?page=${published.pages[0].sequence}&passage=${passageId}`;

    await openItem();
    await page.getByLabel("Withdrawal reason").fill(`e2e withdrawal ${m}`);
    await page.getByRole("button", { name: "Withdraw" }).click();
    await expect(status("Withdrawn: removed from search, Ask, QR links and kiosk manifests. The preservation master is kept.")).toBeVisible();
    await expect(page.locator(".chip", { hasText: /^state: / }).first()).toHaveText("state: withdrawn");
    expect((await api.get(`/api/visitor/items/${itemId}`)).status()).toBe(410);
    expect((await api.get(`/api/visitor/passages/${passageId}`)).status()).toBe(410);
    const visitor = await ctx.newPage();
    await visitor.goto(passageLink);
    await expect(visitor.getByRole("alert")).toContainText("This item has been withdrawn from the public archive.");
    await visitor.close();
  });

  test("audit log records the workflow and the hash chain verifies", async () => {
    await page.getByRole("navigation", { name: "Staff" }).getByRole("link", { name: "Audit log" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Audit log" })).toBeVisible();
    const rows = page.getByRole("table", { name: "Audit events" }).getByRole("row");
    await expect(rows.nth(1)).toBeVisible();
    const onItem = (action: string) => rows.filter({ hasText: action }).filter({ hasText: `archival_item ${itemId}` });
    await expect(onItem("item.intake")).toHaveCount(1);
    await expect(onItem("item.metadata.update").first()).toBeVisible();
    await expect(onItem("publish.switch")).toHaveCount(1);
    await expect(onItem("item.withdraw").first()).toBeVisible();
    // Staging is recorded on the item version before the switch.
    const staged = rows.filter({ hasText: "publish.stage" }).filter({ hasText: `"item_id":${itemId}` });
    await expect(staged).toHaveCount(1);
    const idOf = async (row: Locator) => Number(await row.locator("td").first().innerText());
    expect(await idOf(staged), "stage precedes switch").toBeLessThan(await idOf(onItem("publish.switch")));
    await expect(rows.filter({ hasText: "review.correct" }).first()).toBeVisible();
    await expect(rows.filter({ hasText: "constitution.link.add" }).filter({ hasText: `"item_id":${itemId}` })).toHaveCount(1);
    await expect(rows.filter({ hasText: "summary.draft" }).first()).toBeVisible();

    await page.getByRole("button", { name: "Verify hash chain" }).click();
    await expect(page.getByText(/^Hash chain intact across \d+ events\.$/)).toBeVisible();
  });

  test("restore a withdrawn item: the same passage link works again", async ({ api }) => {
    expect(passageId, "the withdraw test recorded a passage link").toBeGreaterThan(0);
    await openItem();
    await expect(page.locator(".chip", { hasText: /^state: / }).first()).toHaveText("state: withdrawn");
    expect((await api.get(`/api/visitor/passages/${passageId}`)).status(), "still gone while withdrawn").toBe(410);

    await page.getByLabel("Restore reason").fill(`e2e restore ${m}`);
    await page.getByRole("button", { name: "Restore", exact: true }).click();
    await expect(status("Restored: the same published version is visible again, with the same passage and file links.")).toBeVisible();
    await expect(page.locator(".chip", { hasText: /^state: / }).first()).toHaveText("state: published");

    expect((await api.get(`/api/visitor/items/${itemId}`)).status()).toBe(200);
    const again = await api.get(`/api/visitor/passages/${passageId}`);
    expect(again.status()).toBe(200);
    expect((await again.json()).passage_id).toBe(passageId);
    const visitor = await ctx.newPage();
    await visitor.goto(passageLink);
    await expect(visitor.getByRole("heading", { level: 1, name: title })).toBeVisible();
    await expect(visitor.locator(".passage.target")).toBeVisible();
    await visitor.close();
  });
});
