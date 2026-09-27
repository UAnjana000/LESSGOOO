import axe from "axe-core";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "./App";
import { SessionProvider } from "./state";
import { CitationLink } from "./components/Bits";
import { IDLE_WARNING_MS } from "./components/Shell";
import { fakeFetch } from "./__fixtures__/visitor";
import type { Lang } from "./i18n";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

// Each case renders a full route and runs axe; slow CI machines need more than the 5 s default.
vi.setConfig({ testTimeout: 60_000 });

// Vitest replaces CSS imports (even ?raw) with an empty string, so the sheet is read from disk.
const fs = (await import(/* @vite-ignore */ "node:" + "fs")) as { existsSync(path: string): boolean; readFileSync(path: string, encoding: "utf8"): string };
const cwd = (globalThis as unknown as { process: { cwd(): string } }).process.cwd();
const cssPath = [`${cwd}/src/styles.css`, `${cwd}/web/src/styles.css`].find((p) => fs.existsSync(p))!;
const css = fs.readFileSync(cssPath, "utf8");

const STYLE_ID = "app-styles";
let root: Root | null = null;
let host: HTMLElement | null = null;

beforeAll(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  // Font @imports resolve through the bundler, not the test DOM.
  style.textContent = css.replace(/^@import[^;]+;/gm, "");
  document.head.append(style);
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, onchange: null, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;
  const proto = HTMLDialogElement.prototype;
  if (typeof proto.showModal !== "function") proto.showModal = function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
  if (typeof proto.close !== "function") proto.close = function (this: HTMLDialogElement) { this.removeAttribute("open"); };
  Element.prototype.scrollIntoView ??= () => {};
  HTMLMediaElement.prototype.load = () => {};
});

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(fakeFetch));
  sessionStorage.clear();
  localStorage.clear();
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  host?.remove();
  host = null;
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function flush(times = 5) {
  for (let i = 0; i < times; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

async function until(check: () => boolean, what: string) {
  for (let i = 0; i < 200; i++) {
    if (check()) return;
    await flush(1);
  }
  throw new Error(`Timed out waiting for ${what}`);
}

function visit(opts: { lang?: Lang; basket?: boolean } = {}) {
  if (!opts.lang && !opts.basket) return;
  sessionStorage.setItem("archive-visit", JSON.stringify({
    lang: opts.lang ?? "en",
    textScale: 1,
    contrast: false,
    askHistory: [],
    sessionId: "test",
    basket: opts.basket ? [{ item_id: 1, title: "Annihilation of Caste", passage_id: 11, page: 1, citation: "Annihilation of Caste, 1936, p. 3" }] : [],
  }));
}

async function mount(path: string, ready: string, opts: { lang?: Lang; basket?: boolean } = {}) {
  visit(opts);
  host = document.createElement("div");
  host.id = "root";
  document.body.append(host);
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  root = createRoot(host);
  await act(async () => root!.render(<SessionProvider><RouterProvider router={router} /></SessionProvider>));
  await until(() => document.querySelector(ready) !== null, `${ready} on ${path}`);
  await flush(3);
  return router;
}

async function axeViolations(): Promise<string[]> {
  const res = await axe.run(document, {
    // jsdom has no layout, so contrast is checked from the design tokens below instead.
    rules: { "color-contrast": { enabled: false } },
    resultTypes: ["violations"],
  });
  return res.violations.map((v) => `${v.id}: ${v.help} — ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

const INTERACTIVE = "a[href], button, input:not([type=hidden]), select, textarea, [role=tab], [tabindex]:not([tabindex='-1'])";

/** Controls whose styled minimum box is under 48 × 48 px (spec §5 kiosk targets). */
function smallTargets(scope: ParentNode = document): string[] {
  const out: string[] = [];
  for (const el of scope.querySelectorAll<HTMLElement>(INTERACTIVE)) {
    if (el.closest(".visually-hidden, dialog:not([open]), [inert]")) continue;
    const cs = getComputedStyle(el);
    const name = `${el.tagName.toLowerCase()}.${el.className || "-"} “${(el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 30)}”`;
    const minH = Math.max(parseFloat(cs.minHeight) || 0, parseFloat(cs.height) || 0);
    // jsdom reports form controls as inline; browsers render them inline-block, which honours min-height.
    const replaced = ["BUTTON", "INPUT", "SELECT", "TEXTAREA"].includes(el.tagName);
    if (cs.display === "inline" && !replaced) out.push(`${name}: display inline ignores min-height`);
    else if (minH < 48) out.push(`${name}: min-height ${cs.minHeight || "unset"}`);
    const label = (el.textContent ?? "").trim();
    if (label.length <= 3 && el.tagName !== "INPUT" && el.tagName !== "SELECT" && el.tagName !== "TEXTAREA") {
      const minW = Math.max(parseFloat(cs.minWidth) || 0, parseFloat(cs.width) || 0);
      if (minW < 48) out.push(`${name}: min-width ${cs.minWidth || "unset"}`);
    }
  }
  return out;
}

const KIOSK_ROUTES: [string, string, { lang?: Lang; basket?: boolean }?][] = [
  ["/", ".drawers"],
  ["/search?q=caste", ".results .result"],
  ["/search?collection=photographs", ".results .result"],
  ["/ask?q=What%20is%20caste%3F", ".answer .cite-link"],
  ["/item/1", ".segments"],
  ["/item/1", "[role=tab]", { lang: "hi" }],
  ["/item/99", ".notice.bad"],
  ["/constitution", ".results .result"],
  ["/constitution/17", ".results .result"],
  ["/timeline", ".timeline li"],
  ["/stories", ".story-card"],
  ["/stories/mahad", ".story-block"],
  ["/map", ".chip-link"],
  ["/list", ".results .result", { basket: true }],
  ["/list", ".empty-state"],
];

const LANGS_UNDER_TEST: Lang[] = ["en", "hi", "mr"];
// Cases pinned to a language (the fixture's reviewed Hindi translation) run only in that language.
const inLang = (lang: Lang) =>
  KIOSK_ROUTES.filter(([, , opts]) => !opts?.lang || opts.lang === lang).map(([path, ready, opts]) => [path, ready, { ...opts, lang }] as const);

describe.each(LANGS_UNDER_TEST)("visitor routes in %s pass axe (WCAG 2.2 A/AA rules that work without layout)", (lang) => {
  it.each(inLang(lang))("%s", async (path, ready, opts) => {
    await mount(path, ready, opts);
    expect(document.documentElement.lang).toBe(lang);
    expect(await axeViolations()).toEqual([]);
  });
});

const STAFF_USER = { email: "reviewer@example.org", name: "Reviewer", roles: ["reviewer", "curator"], languages: ["en", "hi", "mr"] };
const STAFF_API: Record<string, unknown> = {
  "/api/staff/me": STAFF_USER,
  "/api/staff/stats": { items_by_state: { published: 3 }, pages_by_status: { approved: 5 }, pages_by_route: { local: 5 }, answers: [{ outcome: "answered", count: 2, tokens_in: 900, tokens_out: 120, cost_usd: 0.001, avg_latency_ms: 850 }], cache_hits: 1 },
  "/api/staff/settings/status": { environment: "test", sarvam_configured: false, llm_configured: false, trace_backend: "none", gate_config: "gate.json", sufficiency_threshold: 0.5, sufficiency_threshold_version: "v1" },
  "/api/staff/review/queue": { pages: [{ id: 7, item_title: "Test item", label: "3", status: "needs_full_review", ocr_route: "local", priority: 1 }], batches: [], segments: [], photos: [], translations: [], derivatives: [], ready_to_publish: [] },
  "/api/staff/rights": [{ id: 1, source_key: "test-src", title: "Test source", rights_holder: "Archive", display_permission: "allowed", training_permission: "unknown", external_processing: "not_allowed", discovery_only: false }],
};

function staffFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = typeof input === "string" ? input : input instanceof URL ? input.pathname + input.search : input.url;
  const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
  if (path in STAFF_API) return Promise.resolve(new Response(JSON.stringify(STAFF_API[path]), { status: 200, headers: { "Content-Type": "application/json" } }));
  return fakeFetch(input, init);
}

describe.each(LANGS_UNDER_TEST)("archivist workspace in %s passes axe and uses the chosen language", (lang) => {
  const STAFF_ROUTES: [string, string, boolean][] = [
    ["/staff/login", "form input[type=email]", false],
    ["/staff", ".staff-top nav a", true],
    ["/staff/review", "table.grid", true],
    ["/staff/rights", "table.grid", true],
  ];
  it.each(STAFF_ROUTES)("%s", async (path, ready, signedIn) => {
    vi.stubGlobal("fetch", vi.fn(staffFetch));
    if (signedIn) sessionStorage.setItem("archive-staff-token", "test-token");
    await mount(path, ready, { lang });
    expect(document.documentElement.lang).toBe(lang);
    expect(await axeViolations()).toEqual([]);
    expect(smallTargets(document.querySelector(".staff-top") ?? document.createElement("div"))).toEqual([]);
    if (lang !== "en") expect(document.querySelector("h1")?.textContent).toMatch(/[\u0900-\u097F]/);
  });
});

describe("phone list and signage pass axe", () => {
  it.each([
    ["/c/abc", ".results .result"],
    ["/display", ".slide"],
  ] as const)("%s (phone list and signage)", async (path, ready) => {
    await mount(path, ready);
    expect(await axeViolations()).toEqual([]);
  });
});

describe("explore views with nothing curated yet", () => {
  const EMPTY: Record<string, unknown> = { "/api/visitor/timeline": [], "/api/visitor/stories": [], "/api/visitor/map": { nodes: [], edges: [] } };
  const emptyFetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.pathname + input.search : input.url;
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    if (path in EMPTY) return Promise.resolve(new Response(JSON.stringify(EMPTY[path]), { status: 200, headers: { "Content-Type": "application/json" } }));
    return fakeFetch(input, init);
  };
  it.each([
    ["/timeline", "No timeline events"],
    ["/stories", "No stories"],
    ["/map", "No connections"],
  ] as const)("%s says so instead of rendering a blank page", async (path, text) => {
    vi.stubGlobal("fetch", vi.fn(emptyFetch));
    await mount(path, ".empty-state");
    expect(document.querySelector(".empty-state")?.textContent).toContain(text);
    expect(document.querySelector(".map-wrap")).toBeNull();
    expect(await axeViolations()).toEqual([]);
  });
});

describe.each(LANGS_UNDER_TEST)("kiosk touch targets in %s are at least 48 × 48 px", (lang) => {
  it.each(inLang(lang))("%s", async (path, ready, opts) => {
    await mount(path, ready, opts);
    expect(smallTargets()).toEqual([]);
  });
});

describe("CitationLink", () => {
  it("is a 48 × 48 px target with a spoken name, even inside running text", async () => {
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => root!.render(<SessionProvider><p className="sentence">Caste is a state of mind.<CitationLink n={2} targetId="src-11" /></p></SessionProvider>));
    const a = host.querySelector<HTMLAnchorElement>("a.cite-link")!;
    expect(a.getAttribute("href")).toBe("#src-11");
    expect(a.getAttribute("aria-label")).toBe("Source 2");
    const cs = getComputedStyle(a);
    expect(cs.display).not.toBe("inline");
    expect(parseFloat(cs.minWidth)).toBeGreaterThanOrEqual(48);
    expect(parseFloat(cs.minHeight)).toBeGreaterThanOrEqual(48);
  });

  it("links every answer sentence to a numbered source that can take focus", async () => {
    await mount("/ask?q=What%20is%20caste%3F", ".answer .cite-link");
    const links = [...document.querySelectorAll<HTMLAnchorElement>(".answer .cite-link")];
    expect(links.map((a) => a.getAttribute("aria-label"))).toEqual(["Source 1", "Source 1", "Source 2"]);
    for (const a of links) {
      const target = document.getElementById(a.hash.slice(1));
      expect(target?.tagName).toBe("LI");
      expect(target?.tabIndex).toBe(-1);
    }
    expect(document.querySelector(".answer .chip.ai")?.textContent).toBe("AI-generated answer from archive sources");
  });
});

describe("language of parts", () => {
  it("sets html lang and marks archive text in another language", async () => {
    await mount("/item/1", "[role=tab]", { lang: "hi" });
    expect(document.documentElement.lang).toBe("hi");
    expect(document.querySelector("h1 span")?.getAttribute("lang")).toBe("en");
    const tab = document.getElementById("tab-original")!;
    expect(tab.textContent).toBe("स्रोत पाठ");
    expect(tab.hasAttribute("lang")).toBe(false);
    expect(document.querySelector(".chips .chip[lang='en']")).toBeNull();
    expect(document.title).toContain("Annihilation of Caste");
  });

  it("follows the ARIA tabs pattern for original and reviewed text", async () => {
    await mount("/item/1", "[role=tab]", { lang: "hi" });
    const [orig, rev] = [document.getElementById("tab-original")!, document.getElementById("tab-reviewed")!];
    expect(orig.getAttribute("aria-selected")).toBe("true");
    expect(rev.tabIndex).toBe(-1);
    await act(async () => { orig.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })); });
    expect(rev.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(rev);
    expect(document.getElementById("text-panel")?.getAttribute("aria-labelledby")).toBe("tab-reviewed");
  });
});

describe("item reader previous and next page arrows", () => {
  const prev = () => document.querySelector<HTMLButtonElement>(".step-btn.prev")!;
  const next = () => document.querySelector<HTMLButtonElement>(".step-btn.next")!;
  const current = () => document.querySelector(".pager [aria-current=true]")?.textContent;
  const press = (key: string, target: EventTarget = document.body) =>
    act(async () => { target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true })); });

  it("steps between the first and last page the item has, updating the page query", async () => {
    const router = await mount("/item/1", ".step-btn");
    expect(current()).toBe("Page 3");
    expect(prev().disabled).toBe(true);
    expect(next().disabled).toBe(false);
    expect(prev().textContent).toBe("Previous page");
    expect(next().textContent).toBe("Next page");

    next().focus();
    await act(async () => next().click());
    expect(current()).toBe("Page 4");
    expect(router.state.location.search).toBe("?page=2");
    expect(next().disabled).toBe(true);
    expect(prev().disabled).toBe(false);
    expect(document.activeElement).toBe(prev());

    await act(async () => prev().click());
    expect(current()).toBe("Page 3");
    expect(prev().disabled).toBe(true);
    expect(document.activeElement).toBe(next());
  });

  it("follows the left and right arrow keys unless focus is in a field or the text tabs", async () => {
    const router = await mount("/item/1", ".step-btn", { lang: "hi" });
    await press("ArrowRight", document.getElementById("tab-original")!);
    expect(router.state.location.search).toBe("");

    await press("ArrowRight");
    expect(router.state.location.search).toBe("?page=2");
    await press("ArrowRight");
    expect(router.state.location.search).toBe("?page=2");

    const field = document.createElement("input");
    document.body.append(field);
    await press("ArrowLeft", field);
    expect(router.state.location.search).toBe("?page=2");
    field.remove();

    await press("ArrowLeft");
    expect(router.state.location.search).toBe("?page=1");
  });

  it.each([["hi", "पिछला पृष्ठ", "अगला पृष्ठ"], ["mr", "मागील पान", "पुढील पान"]] as const)("names the arrows in %s", async (lang, p, n) => {
    await mount("/item/1", ".step-btn", { lang });
    expect(prev().textContent).toBe(p);
    expect(next().textContent).toBe(n);
  });
});

describe("kiosk idle reset (WCAG 2.2.1)", () => {
  const warning = () => document.querySelector<HTMLDialogElement>("dialog.idle-warning")!;
  const advance = async (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

  it("warns 30 s ahead, lets any action extend the visit, then resets to the attract screen", async () => {
    localStorage.setItem("archive-kiosk-mode", "1");
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    const router = createMemoryRouter(routes, { initialEntries: ["/"] });
    await act(async () => root!.render(<SessionProvider><RouterProvider router={router} /></SessionProvider>));
    await advance(0);
    await advance(0);

    const idleMs = 120_000;
    await advance(idleMs - IDLE_WARNING_MS - 1000);
    expect(warning().open).toBe(false);
    await advance(1500);
    expect(warning().open).toBe(true);
    expect(warning().getAttribute("aria-labelledby")).toBe("idle-title");
    expect(document.getElementById("idle-body")?.textContent).toContain("30");

    // A screen-reader activation fires only a click.
    const stay = warning().querySelector("button")!;
    await act(async () => { stay.click(); });
    expect(warning().open).toBe(false);
    await advance(IDLE_WARNING_MS + 1000);
    expect(document.querySelector(".attract")).toBeNull();

    // Focus moving (screen-reader navigation) also counts as activity.
    await advance(50_000);
    await act(async () => { document.querySelector<HTMLElement>(".rail .toggle")!.focus(); });
    await advance(10_000);
    expect(warning().open).toBe(false);

    await advance(idleMs + 1000);
    expect(document.querySelector(".attract")).not.toBeNull();
    expect(document.getElementById("main")?.hasAttribute("inert")).toBe(true);
    expect(document.querySelector(".rail")?.hasAttribute("inert")).toBe(true);
    expect(document.activeElement?.classList.contains("attract")).toBe(true);
  });
});

describe("design token contrast (WCAG 1.4.3 text, 1.4.11 focus and field boundaries)", () => {
  const block = (sel: RegExp) => Object.fromEntries([...(css.match(sel)?.[1] ?? "").matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2]]));
  const base = block(/:root \{([\s\S]*?)\n\}/);
  const high = { ...base, ...block(/:root\[data-contrast="high"\] \{([\s\S]*?)\n\}/) };
  const lum = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a: string, b: string) => {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  };
  // [foreground, background, minimum]; names are CSS variables, #hex values are literal colours in styles.css.
  const PAIRS: [string, string, number][] = [
    ["ink", "paper", 4.5], ["ink", "sheet", 4.5], ["ink-2", "paper", 4.5], ["ink-2", "sheet", 4.5], ["ink-2", "indigo-soft", 4.5],
    ["indigo", "paper", 4.5], ["indigo", "sheet", 4.5], ["indigo", "indigo-soft", 4.5], ["#ffffff", "indigo", 4.5], ["#ffffff", "indigo-deep", 4.5],
    ["brass-ink", "brass-wash", 4.5], ["brass-ink", "sheet", 4.5], ["danger", "sheet", 4.5], ["ok", "sheet", 4.5], ["ink", "brass", 4.5],
    ["#dfe4f3", "indigo", 4.5], ["#dfe4f3", "indigo-deep", 4.5], ["#a9b3d6", "indigo-deep", 4.5], ["brass", "indigo-deep", 4.5],
    ["focus-ring", "paper", 3], ["focus-ring", "sheet", 3], ["focus", "indigo", 3], ["focus", "indigo-deep", 3],
    ["field", "sheet", 3], ["field", "paper", 3],
  ];
  it.each([["default", base], ["high contrast", high]] as const)("%s theme", (_, vars) => {
    const colour = (v: string) => (v.startsWith("#") ? v : vars[v]);
    const failures = PAIRS.map(([fg, bg, min]) => ({ fg, bg, min, r: ratio(colour(fg), colour(bg)) })).filter((p) => !(p.r >= p.min));
    expect(failures.map((f) => `${f.fg} on ${f.bg}: ${f.r.toFixed(2)} < ${f.min}`)).toEqual([]);
  });
});
