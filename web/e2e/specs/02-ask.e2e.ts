import { test, expect } from "../fixtures";
import { FX, SPEC_ANSWER_LABEL } from "../env";

// Live answer-model calls (gpt-4o-mini from the repo .env). Two questions here; the whole run allows five.
const ANSWERABLE = "According to the lecture on education, why should mothers learn to read?";
const OFF_TOPIC = "What is the recipe for a chocolate cake?";

test.describe("Ask the archive", () => {
  test.describe.configure({ timeout: 150_000 });

  test("answerable question: labelled AI answer whose citations open the reader at the cited page", async ({ page, fx }) => {
    const lecture = fx.get(FX.lecture);
    await page.goto("/ask");
    await expect(page.getByRole("heading", { level: 1, name: "Ask the archive" })).toBeVisible();
    await page.getByRole("textbox", { name: "Ask a question about the archive" }).fill(ANSWERABLE);
    const response = page.waitForResponse((r) => r.url().endsWith("/api/visitor/ask") && r.request().method() === "POST", { timeout: 120_000 });
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    const body = await (await response).json();
    expect(body.outcome, `Ask outcome (message: ${body.message ?? "none"})`).toBe("answered");

    const answer = page.locator("article.answer");
    await expect(answer.getByRole("heading", { level: 2, name: ANSWERABLE })).toBeVisible();
    await expect(answer.locator(".chip.ai")).toHaveText(SPEC_ANSWER_LABEL);
    await expect(answer.locator("p.sentence").first()).toBeVisible();
    // Every sentence carries at least one numbered citation link.
    const sentences = answer.locator("p.sentence");
    for (let i = 0; i < (await sentences.count()); i++) {
      await expect(sentences.nth(i).getByRole("link", { name: /^Source \d+$/ }).first()).toBeVisible();
    }

    const sources = answer.getByRole("region", { name: "Sources" });
    await expect(sources.getByRole("listitem").first()).toBeVisible();
    const fromLecture = sources.getByRole("listitem").filter({ hasText: lecture.title }).first();
    await expect(fromLecture, "the education lecture is among the sources").toBeVisible();
    const open = fromLecture.getByRole("link", { name: "Open" });
    const href = await open.getAttribute("href");
    expect(href).toMatch(new RegExp(`^/item/${lecture.id}\\?.*passage=\\d+`));
    await open.click();
    await expect(page).toHaveURL(new RegExp(`/item/${lecture.id}\\?`));
    await expect(page.getByRole("heading", { level: 1, name: lecture.title })).toBeVisible();
    const pageNo = new URL(href!, "https://x").searchParams.get("page");
    if (pageNo) await expect(page.getByRole("group", { name: new RegExp(`Page ${pageNo}$`) })).toBeVisible();
    await expect(page.getByRole("region", { name: "Approved text" }).locator(".passage.target")).toHaveCount(1);
  });

  test("off-topic question abstains instead of answering", async ({ page }) => {
    await page.goto("/ask");
    await page.getByRole("textbox", { name: "Ask a question about the archive" }).fill(OFF_TOPIC);
    const response = page.waitForResponse((r) => r.url().endsWith("/api/visitor/ask") && r.request().method() === "POST", { timeout: 120_000 });
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    const body = await (await response).json();
    expect(["insufficient", "refused", "rejected_input"]).toContain(body.outcome);

    const answer = page.locator("article.answer");
    await expect(answer.getByRole("heading", { level: 2, name: OFF_TOPIC })).toBeVisible();
    await expect(answer.locator(".chip.ai")).toHaveCount(0);
    await expect(answer.locator("p.sentence")).toHaveCount(0);
    if (body.outcome === "insufficient") {
      await expect(answer.locator(".notice")).toContainText(/does not contain enough/);
    } else {
      await expect(answer.locator(".chip", { hasText: "Refused" })).toBeVisible();
    }
  });
});
