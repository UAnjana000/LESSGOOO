import { test, expect } from "../fixtures";

// Project "model-down" only (npm run test:e2e:model-down), after `stack.ps1 llm-down` has restarted the
// api with an unreachable answer model. Retrieval is real; only generation fails. The question is not asked anywhere
// else, so no cached answer can mask the failure.
const QUESTION = "Why did the Assembly decide that reading should stay free?";

test("answer-model failure shows an error and the closest passages to read", async ({ page }) => {
  test.setTimeout(150_000);
  await page.goto("/ask");
  await page.getByRole("textbox", { name: "Ask a question about the archive" }).fill(QUESTION);
  const response = page.waitForResponse((r) => r.url().endsWith("/api/visitor/ask") && r.request().method() === "POST", { timeout: 120_000 });
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const body = await (await response).json();
  expect(body.outcome, "backend outcome when generation fails").toBe("error");
  expect(body.citations.length, "closest passages returned with the error").toBeGreaterThan(0);

  const answer = page.locator("article.answer");
  await expect(answer.locator(".notice.bad")).toHaveText("Something went wrong loading this. Try again.");
  await expect(answer.locator(".chip.ai")).toHaveCount(0);
  await expect(answer.locator("p.sentence")).toHaveCount(0);
  const related = answer.getByRole("region", { name: "Related material you can read" });
  await expect(related.getByRole("listitem").first()).toBeVisible();
  await expect(related.getByRole("link", { name: "Open" }).first()).toHaveAttribute("href", /^\/item\/\d+/);
});
