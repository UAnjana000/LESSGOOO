import fs from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { test as base, expect, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";
import { apiContext, catalog, createPublishedItem, findItem, marker, type ItemCard } from "./helpers/api";
import { ARTIFACTS, E2E } from "./env";

/** The task allows at most 5 live answer-model calls for the whole run. Every visitor Ask POST counts. */
export const ASK_BUDGET = 5;
const ASK_LEDGER = path.join(ARTIFACTS, "ask-budget.json");

function recordAsk(title: string): number {
  const ledger: { calls: { test: string; at: string }[] } = fs.existsSync(ASK_LEDGER)
    ? JSON.parse(fs.readFileSync(ASK_LEDGER, "utf8"))
    : { calls: [] };
  ledger.calls.push({ test: title, at: new Date().toISOString() });
  fs.mkdirSync(ARTIFACTS, { recursive: true });
  fs.writeFileSync(ASK_LEDGER, JSON.stringify(ledger, null, 1));
  return ledger.calls.length;
}

export class Catalog {
  constructor(readonly items: ItemCard[]) {}
  get(titleFragment: string): ItemCard {
    return findItem(this.items, titleFragment);
  }
}

export async function loginStaff(page: Page): Promise<void> {
  await page.goto("/staff/login");
  await page.getByLabel("Email").fill(E2E.admin.email);
  await page.getByLabel("Password").fill(E2E.admin.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible();
}

export interface AxeSummary {
  route: string;
  violations: { id: string; impact: string | null; help: string; nodes: number; targets: string[] }[];
}

/**
 * Runs axe (WCAG 2.0/2.1/2.2 A and AA rules) on the current page, attaches the full result, and appends a
 * one-line-per-rule summary to artifacts/a11y/summary.json for the report.
 */
export async function axeScan(page: Page, testInfo: TestInfo, route: string): Promise<AxeSummary> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  await testInfo.attach(`axe-${route.replace(/[^a-z0-9]+/gi, "_")}.json`, {
    body: JSON.stringify(results.violations, null, 1), contentType: "application/json",
  });
  const summary: AxeSummary = {
    route,
    violations: results.violations.map((v) => ({
      id: v.id, impact: v.impact ?? null, help: v.help, nodes: v.nodes.length,
      targets: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
    })),
  };
  const dir = path.join(ARTIFACTS, "a11y");
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, "summary.json");
  const all: AxeSummary[] = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : [];
  fs.writeFileSync(file, JSON.stringify([...all.filter((s) => s.route !== route), summary], null, 1));
  return summary;
}

export interface BoxedPassage { itemId: number; title: string; page: number; passageId: number; text: string; created: boolean }

async function findBoxedPassage(api: APIRequestContext, items: ItemCard[]): Promise<Omit<BoxedPassage, "created"> | null> {
  for (const it of items.filter((i) => ["printed_scan", "manuscript"].includes(i.item_type))) {
    const d = await (await api.get(`/api/visitor/items/${it.id}`)).json();
    for (const pg of d.pages ?? []) {
      const p = (pg.passages ?? []).find((x: { bboxes?: unknown[]; text: string }) => (x.bboxes?.length ?? 0) > 0 && x.text.split(/\s+/).length >= 8);
      if (p) return { itemId: it.id, title: it.title, page: pg.sequence, passageId: p.id, text: p.text };
    }
  }
  return null;
}

type WorkerFixtures = { api: APIRequestContext; fx: Catalog; boxed: BoxedPassage };
type TestFixtures = { askGuard: void };

export const test = base.extend<TestFixtures, WorkerFixtures>({
  api: [async ({}, use) => {
    const ctx = await apiContext();
    await use(ctx);
    await ctx.dispose();
  }, { scope: "worker" }],
  fx: [async ({ api }, use) => {
    await use(new Catalog(await catalog(api)));
  }, { scope: "worker" }],
  // A published passage with word boxes on its scan. Boxes exist only where the approved text still equals
  // the OCR text; seeded fixtures were corrected to ground truth, so one capture may need publishing first.
  boxed: [async ({ api }, use) => {
    let found = await findBoxedPassage(api, await catalog(api));
    let created = false;
    if (!found) {
      await createPublishedItem(api, `E2E capture ${marker()}: Letter to the Library Board (synthetic fixture)`);
      found = await findBoxedPassage(api, await catalog(api));
      created = true;
    }
    if (!found) throw new Error("No published passage has word boxes, even after publishing a fresh OCR capture.");
    await use({ ...found, created });
  }, { scope: "worker", timeout: 480_000 }],
  askGuard: [async ({ context }, use, testInfo) => {
    // Only count Ask POSTs that can reach a live answer model. Offline clicks never leave the kiosk;
    // project "model-down" points generation at a closed port.
    const live = testInfo.project.name !== "model-down"
      && !testInfo.titlePath.some((p) => /offline/i.test(p));
    let total = 0;
    context.on("request", (req) => {
      if (live && req.method() === "POST" && new URL(req.url()).pathname === "/api/visitor/ask") {
        total = recordAsk(testInfo.titlePath.join(" > "));
      }
    });
    await use();
    if (live) {
      expect(total, `live Ask budget (${ASK_BUDGET} calls for the whole run, see artifacts/ask-budget.json)`).toBeLessThanOrEqual(ASK_BUDGET);
    }
  }, { auto: true }],
});

export { expect };
