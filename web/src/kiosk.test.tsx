import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "./App";
import { SessionProvider } from "./state";
import { IDLE_WARNING_MS } from "./components/Shell";
import { isKiosk } from "./kiosk";
import { fakeFetch } from "./__fixtures__/visitor";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

const fs = (await import(/* @vite-ignore */ "node:" + "fs")) as { readFileSync(path: string, encoding: "utf8"): string };
const cwd = (globalThis as unknown as { process: { cwd(): string } }).process.cwd();
const read = (rel: string) => fs.readFileSync(`${cwd}/${rel}`, "utf8");

let root: Root | null = null;
let host: HTMLElement | null = null;

beforeAll(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, onchange: null, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;
  const proto = HTMLDialogElement.prototype;
  if (typeof proto.showModal !== "function") proto.showModal = function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
  if (typeof proto.close !== "function") proto.close = function (this: HTMLDialogElement) { this.removeAttribute("open"); };
  Element.prototype.scrollIntoView ??= () => {};
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
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
  delete document.documentElement.dataset.kiosk;
});

const advance = async (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
const stored = () => JSON.parse(sessionStorage.getItem("archive-visit") ?? "{}") as { basket: unknown[]; askHistory: unknown[]; sessionId: string };

async function mount(path: string) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  await act(async () => root!.render(<SessionProvider><RouterProvider router={router} /></SessionProvider>));
  await advance(0);
  await advance(0);
  return router;
}

describe("/kiosk dock", () => {
  it("ends the visit after the idle warning and wakes without activating what is underneath", async () => {
    sessionStorage.setItem("archive-visit", JSON.stringify({
      lang: "en", textScale: 1, contrast: false, sessionId: "before",
      askHistory: [{ question: "q", answer: "a" }],
      basket: [{ item_id: 1, title: "Annihilation of Caste", passage_id: 11, page: 1, citation: "c" }],
    }));
    await mount("/kiosk");
    const warning = () => document.querySelector<HTMLDialogElement>("dialog.idle-warning")!;
    expect(stored().basket).toHaveLength(1);

    await advance(120_000 - IDLE_WARNING_MS - 1000);
    expect(warning().open).toBe(false);
    await advance(1500);
    expect(warning().open).toBe(true);

    await advance(IDLE_WARNING_MS + 500);
    expect(warning().open).toBe(false);
    expect(stored().basket).toHaveLength(0);
    expect(stored().askHistory).toHaveLength(0);
    expect(stored().sessionId).not.toBe("before");
    const overlay = document.querySelector<HTMLElement>(".kiosk-attract-overlay")!;
    expect(overlay).not.toBeNull();

    // The waking tap is swallowed by the overlay.
    const down = new MouseEvent("pointerdown", { bubbles: true, cancelable: true });
    overlay.dispatchEvent(down);
    expect(down.defaultPrevented).toBe(true);
    const reachedPage = vi.fn();
    document.querySelector(".kiosk-main-stage")!.addEventListener("click", reachedPage);
    await act(async () => { overlay.querySelector<HTMLElement>("button")!.click(); });
    expect(reachedPage).not.toHaveBeenCalled();
    expect(document.querySelector(".kiosk-attract-overlay")).toBeNull();
  });

  it("has no staff PIN in the bundle sources", () => {
    const src = read("src/pages/Kiosk.tsx");
    expect(src).not.toMatch(/1956|"admin"|pin ===/);
    expect(src).not.toMatch(/type="password"/);
  });
});

describe("kiosk mode lockdown", () => {
  it("marks the document, blocks the context menu and keeps links in the app", async () => {
    localStorage.setItem("archive-kiosk-mode", "1");
    const router = await mount("/");
    expect(document.documentElement.dataset.kiosk).toBe("1");

    const menu = new MouseEvent("contextmenu", { bubbles: true, cancelable: true });
    document.body.dispatchEvent(menu);
    expect(menu.defaultPrevented).toBe(true);

    const link = (href: string) => {
      const a = document.createElement("a");
      a.href = href;
      a.target = "_blank";
      host!.append(a);
      return a;
    };
    const other = new MouseEvent("click", { bubbles: true, cancelable: true });
    link("https://example.org/x").dispatchEvent(other);
    expect(other.defaultPrevented).toBe(true);

    const same = new MouseEvent("click", { bubbles: true, cancelable: true });
    await act(async () => { link("/c/abc123").dispatchEvent(same); });
    expect(same.defaultPrevented).toBe(true);
    expect(router.state.location.pathname).toBe("/c/abc123");

  });

  it("does nothing outside kiosk mode", async () => {
    await mount("/");
    expect(document.documentElement.dataset.kiosk).toBeUndefined();
    const menu = new MouseEvent("contextmenu", { bubbles: true, cancelable: true });
    document.body.dispatchEvent(menu);
    expect(menu.defaultPrevented).toBe(false);
  });
});

describe("isKiosk and storage", () => {
  it("does not throw when storage is blocked", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(isKiosk()).toBe(false);
    spy.mockRestore();
  });
});

describe("service worker registration branch", () => {
  it("registers only for kiosks and cleans up otherwise", () => {
    const main = read("src/main.tsx");
    expect(main).toMatch(/if \(isKiosk\(\)\) void startExhibit\(\);\s*else cleanupServiceWorkers\(\);/);
    const sw = read("src/sw.ts");
    expect(sw).toContain("precacheAndRoute(self.__WB_MANIFEST)");
    expect(sw).toContain("/api/visitor/ask");
    expect(sw).toContain("/api/staff");
  });
});
