import fs from "node:fs";
import path from "node:path";
import { request, type FullConfig } from "@playwright/test";
import { ARTIFACTS, E2E, FX, assertNotMainStack } from "./env";

/** Fails fast, with a pointer to stack.ps1, when the throwaway stack is not up, migrated and seeded. */
export default async function globalSetup(_config: FullConfig): Promise<void> {
  assertNotMainStack(E2E.baseURL);
  assertNotMainStack(E2E.dbUrl);
  fs.mkdirSync(ARTIFACTS, { recursive: true });
  // The live-Ask ledger is kept across runs on purpose; delete artifacts/ask-budget.json to reset the budget.
  fs.rmSync(path.join(ARTIFACTS, "a11y", "summary.json"), { force: true });

  const api = await request.newContext({ baseURL: E2E.baseURL, ignoreHTTPSErrors: true });
  try {
    const ready = await api.get("/api/health/ready").catch((e: Error) => {
      throw new Error(`${E2E.baseURL} is not reachable (${e.message}). Start it with: powershell -File web/e2e/stack.ps1 up`);
    });
    if (!ready.ok()) throw new Error(`${E2E.baseURL}/api/health/ready returned ${ready.status()}: ${await ready.text()}`);
    const items: { title: string }[] = await (await api.get("/api/visitor/items")).json();
    const missing = [FX.essay, FX.lecture, FX.proceedings, FX.manuscript, FX.photo, FX.audio, FX.video]
      .filter((f) => !items.some((i) => i.title.includes(f)));
    if (missing.length) {
      throw new Error(`Seeded fixtures missing on ${E2E.baseURL}: ${missing.join("; ")}. Run: powershell -File web/e2e/stack.ps1 seed`);
    }
    const art = await api.get("/api/visitor/constitution/41");
    if (!art.ok()) throw new Error(`Article 41 fixture link missing (HTTP ${art.status()}). Run stack.ps1 seed.`);
  } finally {
    await api.dispose();
  }
}
