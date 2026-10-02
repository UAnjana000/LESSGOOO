import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "./App";
import { AddToList } from "./components/Bits";
import { citationTail, clipSnippet } from "./basket";
import { BASKET_MAX, SessionProvider, type BasketEntry } from "./state";
import { card, fakeFetch } from "./__fixtures__/visitor";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

vi.setConfig({ testTimeout: 30_000 });

const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));

const block = (extra: Record<string, unknown>) => ({
  item: card(5, "Photograph of the Chavdar tank"),
  captions: { en: "The Chavdar tank at Mahad." },
  passage: null,
  citation: "Photo archive, 1930s",
  deep_link: "/item/5",
  ...extra,
});

const STORY = {
  slug: "mahad",
  titles: { en: "The Mahad Satyagraha" },
  blocks: [
    block({ year: "", chapter_title: {} }),
    block({ year: "1930", chapter_title: { en: "The march" } }),
    block({ chapter_title: { hi: "" } }),
  ],
  narration_file_ids: {},
  narration_label: "Synthetic narration",
};

let root: Root | null = null;
let host: HTMLElement | null = null;

beforeAll(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, onchange: null, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;
});

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
    if (url.endsWith("/api/visitor/stories/mahad")) return json(STORY);
    return fakeFetch(input, init);
  }));
  sessionStorage.clear();
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  host?.remove();
  host = null;
  vi.unstubAllGlobals();
});

async function flush(times = 5) {
  for (let i = 0; i < times; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

async function until(check: () => boolean, what: string) {
  for (let i = 0; i < 200; i++) {
    if (check()) return;
    await flush(2);
    await new Promise((r) => setTimeout(r, 10));
  }
  throw new Error(`Timed out waiting for ${what}`);
}

function visit(opts: { lang?: string; basket?: Partial<BasketEntry>[] }) {
  sessionStorage.setItem("archive-visit", JSON.stringify({
    lang: opts.lang ?? "en", textScale: 1, contrast: false, askHistory: [], sessionId: "test", basket: opts.basket ?? [],
  }));
}

async function mount(path: string, ready: string, opts: { lang?: string; basket?: Partial<BasketEntry>[] } = {}) {
  visit(opts);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  await act(async () => root!.render(<SessionProvider><RouterProvider router={router} /></SessionProvider>));
  await until(() => document.querySelector(ready) !== null, `${ready} on ${path}`);
  await flush(3);
}

const click = (el: Element | null | undefined) => act(async () => { (el as HTMLElement).click(); });
const byText = (sel: string, text: string) => [...document.querySelectorAll<HTMLElement>(sel)].find((e) => e.textContent?.includes(text));

describe("stories", () => {
  it("shows no Milestone Year pill when the story gives no year, and never invents one", async () => {
    await mount("/stories/mahad", ".exhibition-stage");
    expect(document.querySelector(".milestone-badge")).toBeNull();
    expect(document.body.textContent).not.toContain("1927");
    await click(byText("button", "Reading"));
    await until(() => !!document.querySelector(".longform-reading-layout"), "reading mode");
    const pills = [...document.querySelectorAll(".milestone-badge")].map((e) => e.textContent);
    expect(pills).toEqual(["Milestone Year: 1930"]);
  });

  it("falls back to the English title, then to Chapter N, in the contents list", async () => {
    await mount("/stories/mahad", ".exhibition-stage");
    await click(byText("button", "Reading"));
    await until(() => !!document.querySelector(".toc-list"), "contents");
    const toc = [...document.querySelectorAll(".toc-link")].map((e) => e.textContent);
    expect(toc).toEqual(["1. Chapter 1", "2. The march", "3. Chapter 3"]);
  });

  it("uses the English title when the chapter has none in the visitor's language", async () => {
    await mount("/stories/mahad", ".exhibition-stage", { lang: "hi" });
    await click(document.querySelectorAll(".chapter-dot")[1]);
    expect(document.querySelector(".exhibition-chapter-title")?.textContent).toBe("The march");
  });

  it("says so when narration will be in English", async () => {
    await mount("/stories/mahad", ".exhibition-stage", { lang: "hi" });
    expect(document.querySelector(".narration-lang-note")?.textContent).toContain("अंग्रेज़ी");
  });
});

describe("saved list", () => {
  const entries: Partial<BasketEntry>[] = [
    { item_id: 1, title: "Annihilation of Caste", passage_id: 11, page: 1, citation: "Annihilation of Caste, 1936, p. 3", snippet: "The first passage snippet." },
    { item_id: 1, title: "Annihilation of Caste", passage_id: 12, page: 2, citation: "Annihilation of Caste, 1936, p. 9", snippet: "A different second snippet." },
  ];

  it("tells entries from one item apart and does not repeat the title in the citation", async () => {
    await mount("/list", ".basket-list", { basket: entries });
    const rows = [...document.querySelectorAll(".basket-entry")].map((r) => r.textContent ?? "");
    expect(rows[0]).toContain("The first passage snippet.");
    expect(rows[1]).toContain("A different second snippet.");
    expect(rows[0]).toContain("1936, p. 3");
    expect(document.querySelector(".basket-entry .cite")?.textContent).toBe("1936, p. 3");
  });

  it("moves entries up and down", async () => {
    await mount("/list", ".basket-list", { basket: entries });
    const titles = () => [...document.querySelectorAll(".basket-entry .basket-snippet")].map((e) => e.textContent);
    await click(document.querySelectorAll(".basket-entry")[1].querySelectorAll(".basket-move")[0]);
    expect(titles()).toEqual(["A different second snippet.", "The first passage snippet."]);
    await click(document.querySelectorAll(".basket-entry")[0].querySelectorAll(".basket-move")[1]);
    expect(titles()).toEqual(["The first passage snippet.", "A different second snippet."]);
  });

  it("clears the list only after confirming", async () => {
    await mount("/list", ".basket-list", { basket: entries });
    await click(byText(".basket-actions-bar button", "Clear list"));
    expect(document.querySelectorAll(".basket-entry")).toHaveLength(2);
    expect(document.querySelector(".basket-clear-confirm")?.textContent).toContain("Remove all 2 items");
    await click(byText(".basket-clear-confirm button", "Keep list"));
    expect(document.querySelectorAll(".basket-entry")).toHaveLength(2);
    await click(byText(".basket-actions-bar button", "Clear list"));
    await click(byText(".basket-clear-confirm button", "Clear list"));
    expect(document.querySelector(".empty-state")).not.toBeNull();
  });

  it("refuses the 31st entry with a visible message instead of dropping the oldest", async () => {
    const full = Array.from({ length: BASKET_MAX }, (_, i) => ({ item_id: 100 + i, title: `Item ${i}`, citation: `Item ${i}` }));
    visit({ basket: full });
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    const extra: BasketEntry = { item_id: 999, title: "One too many", citation: "One too many" };
    await act(async () => root!.render(<SessionProvider><AddToList entry={extra} /></SessionProvider>));
    await click(document.querySelector("button"));
    expect(document.querySelector("[role=alert]")?.textContent).toContain("Your list is full (30 items)");
    const stored = JSON.parse(sessionStorage.getItem("archive-visit") ?? "{}") as { basket: { item_id: number }[] };
    expect(stored.basket).toHaveLength(BASKET_MAX);
    expect(stored.basket[0].item_id).toBe(100);
    expect(stored.basket.some((b) => b.item_id === 999)).toBe(false);
  });

  it("helpers: citationTail and clipSnippet", () => {
    expect(citationTail("Title", "Title, 1936, p. 3")).toBe("1936, p. 3");
    expect(citationTail("Title", "Title")).toBe("");
    expect(citationTail("Title", "Other source")).toBe("Other source");
    expect(clipSnippet("word ".repeat(80)).length).toBeLessThanOrEqual(160);
  });
});

describe("timeline toolbar", () => {
  it("shows just the count and plain toggle labels", async () => {
    await mount("/timeline", ".timeline-toolbar");
    expect(document.querySelector(".timeline-stats")?.textContent).toBe("2 items");
    const labels = [...document.querySelectorAll(".timeline-zoom-btn")].map((b) => b.textContent);
    expect(labels).toEqual(["Overview", "All events"]);
  });
});

describe("connections panel", () => {
  it("shows the hint only with nothing selected and the name once after selecting", async () => {
    await mount("/map", "[data-node-id]");
    const panel = () => document.querySelector(".map-inspector-panel")!;
    expect(panel().textContent).toContain("Choose a name on the map");
    await click(byText(".suggested-entities button", "Ambedkar"));
    expect(panel().textContent).not.toContain("Choose a name on the map");
    expect(panel().textContent).not.toContain("Click any node");
    expect([...panel().querySelectorAll("h2, h3")].filter((h) => h.textContent === "B. R. Ambedkar")).toHaveLength(1);
  });
});

describe("constitution empty state", () => {
  it("offers next steps", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
      if (url.endsWith("/api/visitor/constitution")) return json([]);
      return fakeFetch(input, init);
    }));
    await mount("/constitution", ".constitution-empty");
    const hrefs = [...document.querySelectorAll(".constitution-empty a")].map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/search?q=constitution", "/search?collection=debates"]);
  });
});
