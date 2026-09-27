import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { expect, request, type APIRequestContext } from "@playwright/test";
import { E2E, REPO_ROOT } from "../env";

export type Json = Record<string, any>;

export interface ItemCard {
  id: number;
  title: string;
  item_type: string;
  collection: string;
  date_text: string | null;
  subjects: string[];
  people: string[];
  places: string[];
  is_fixture: boolean;
  online_only: boolean;
  photo: { caption: string; credit: string | null; image_file_id: number | null } | null;
}

export async function apiContext(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: E2E.baseURL, ignoreHTTPSErrors: true });
}

export async function staffToken(api: APIRequestContext): Promise<string> {
  const r = await api.post("/api/staff/login", { data: { email: E2E.admin.email, password: E2E.admin.password } });
  expect(r.status(), "staff login for test setup").toBe(200);
  return (await r.json()).token as string;
}

export async function catalog(api: APIRequestContext): Promise<ItemCard[]> {
  const r = await api.get("/api/visitor/items");
  expect(r.ok(), "visitor catalog").toBeTruthy();
  return r.json();
}

export function findItem(items: ItemCard[], titleFragment: string): ItemCard {
  const it = items.find((i) => i.title.includes(titleFragment));
  if (!it) throw new Error(`Seeded fixture "${titleFragment}" is not published on this stack. Run stack.ps1 seed.`);
  return it;
}

// ---------------------------------------------------------------- unique capture files

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/**
 * The fixture capture page with a PNG tEXt chunk carrying `marker`. Pixels are unchanged, so it passes the
 * same OCR route, but the SHA-256 differs and intake does not reject it as a duplicate.
 */
export function uniquePng(marker: string): Buffer {
  const src = fs.readFileSync(path.join(REPO_ROOT, "fixtures", "capture-demo-page.png"));
  const iend = src.length - 12;
  if (src.subarray(iend + 4, iend + 8).toString("latin1") !== "IEND") throw new Error("unexpected PNG layout");
  const data = Buffer.from(`Comment\0e2e ${marker}`, "latin1");
  const type = Buffer.from("tEXt", "latin1");
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([type, data])));
  return Buffer.concat([src.subarray(0, iend), len, type, data, crc, src.subarray(iend)]);
}

export const marker = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

// ---------------------------------------------------------------- staff setup through the API

async function poll<T>(fn: () => Promise<T>, done: (v: T) => boolean, timeoutMs: number, what: string): Promise<T> {
  const until = Date.now() + timeoutMs;
  let last: T = await fn();
  while (!done(last)) {
    if (Date.now() > until) throw new Error(`Timed out after ${timeoutMs / 1000}s waiting for ${what}: ${JSON.stringify(last).slice(0, 400)}`);
    await new Promise((r) => setTimeout(r, 3000));
    last = await fn();
  }
  return last;
}

export async function staffItem(api: APIRequestContext, token: string, id: number): Promise<Json> {
  const r = await api.get(`/api/staff/items/${id}`, { headers: { Authorization: `Bearer ${token}` } });
  expect(r.ok(), `staff item ${id}`).toBeTruthy();
  return r.json();
}

export async function waitForIngestion(api: APIRequestContext, token: string, id: number, timeoutMs = 360_000): Promise<Json> {
  return poll(() => staffItem(api, token, id),
    (it) => it.pages.length > 0 && it.pages.every((p: Json) => !["pending", "processing"].includes(p.status)),
    timeoutMs, `ingestion of item ${id}`);
}

export async function waitForState(api: APIRequestContext, token: string, id: number, state: string, timeoutMs = 240_000): Promise<Json> {
  return poll(() => staffItem(api, token, id), (it) => it.state === state, timeoutMs, `item ${id} to reach ${state}`);
}

export async function intake(api: APIRequestContext, token: string, title: string, files: Buffer[]): Promise<number> {
  const meta = {
    title, item_type: "printed_scan", collection: "writings", doc_class: "printed", languages: ["en"],
    rights_source_key: "fx-open", capture: { device: "capture-station-1", operator: "e2e-suite" },
  };
  const form = new FormData();
  form.append("metadata", JSON.stringify(meta));
  files.forEach((f, i) => form.append("files", new Blob([new Uint8Array(f)], { type: "image/png" }), `page-${i + 1}.png`));
  const r = await api.post("/api/staff/intake", { headers: { Authorization: `Bearer ${token}` }, multipart: form });
  expect(r.status(), `intake: ${await r.text()}`).toBe(200);
  return (await r.json()).item_id as number;
}

/** Intake, sample-check, review and publish one synthetic page through the staff API (as smoke_test.py does). */
export async function createPublishedItem(api: APIRequestContext, title: string): Promise<number> {
  const token = await staffToken(api);
  const auth = { Authorization: `Bearer ${token}` };
  const id = await intake(api, token, title, [uniquePng(marker())]);
  let item = await waitForIngestion(api, token, id);
  for (const b of item.batches ?? []) {
    if (b.status !== "open") continue;
    const r = await api.post(`/api/staff/batches/${b.id}/decide`, {
      headers: auth,
      data: { passed: true, reason: "e2e setup sample checked", sample_checks: Object.fromEntries(b.sample.map((pid: number) => [String(pid), { ok: true }])) },
    });
    expect(r.ok(), `batch decide: ${await r.text()}`).toBeTruthy();
  }
  item = await staffItem(api, token, id);
  for (const p of item.pages) {
    if (p.status === "approved") continue;
    const detail = await (await api.get(`/api/staff/pages/${p.id}`, { headers: auth })).json();
    const text = (detail.sarvam ?? detail.local ?? {}).text ?? "";
    const r = await api.post(`/api/staff/pages/${p.id}/review`, {
      headers: auth, data: { action: text ? "approve" : "correct", text: text || title },
    });
    expect(r.ok(), `page review: ${await r.text()}`).toBeTruthy();
  }
  const pub = await api.post(`/api/staff/items/${id}/publish`, { headers: auth });
  expect(pub.ok(), `publish: ${await pub.text()}`).toBeTruthy();
  await waitForState(api, token, id, "published");
  return id;
}

export async function saveDraftSummary(api: APIRequestContext, itemId: number, text: string): Promise<void> {
  const token = await staffToken(api);
  const r = await api.post(`/api/staff/items/${itemId}/summary`, {
    headers: { Authorization: `Bearer ${token}` }, data: { language: "en", text },
  });
  expect(r.ok(), `draft summary: ${await r.text()}`).toBeTruthy();
}

// ---------------------------------------------------------------- database (e2e stack only)

/**
 * Moves a QR list's expiry into the past. There is no API for this (links expire after 24 h), so the test
 * writes to the throwaway e2e database directly. It refuses the demo stack's port.
 */
export function expireCollection(token: string): void {
  if (/:55432\b/.test(E2E.dbUrl) || !/:56432\b/.test(E2E.dbUrl)) {
    throw new Error(`Refusing to write to ${E2E.dbUrl.replace(/:[^:@/]+@/, ":***@")}: only the ambedkar-e2e database (port 56432) may be edited.`);
  }
  const script = [
    "import sys, psycopg",
    "with psycopg.connect(sys.argv[1]) as c:",
    "    n = c.execute(\"UPDATE qr_collection SET expires_at = now() - interval '1 hour' WHERE token = %s\", (sys.argv[2],)).rowcount",
    "    print(n)",
  ].join("\n");
  const out = execFileSync(E2E.python, ["-c", script, E2E.dbUrl, token], { encoding: "utf8", timeout: 60_000 }).trim();
  if (out !== "1") throw new Error(`expected to expire one QR list, updated ${out}`);
}
