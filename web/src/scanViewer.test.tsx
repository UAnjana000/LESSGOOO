import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

type Handler = () => void;
const viewers: { opened: unknown[]; handlers: Record<string, Handler[]>; destroyed: boolean }[] = [];

vi.mock("openseadragon", () => ({
  default: () => {
    const v = { opened: [] as unknown[], handlers: {} as Record<string, Handler[]>, destroyed: false };
    viewers.push(v);
    return {
      open: (src: unknown) => v.opened.push(src),
      addHandler: (name: string, fn: Handler) => (v.handlers[name] ??= []).push(fn),
      addOnceHandler: (name: string, fn: Handler) => (v.handlers[name] ??= []).push(fn),
      destroy: () => { v.destroyed = true; },
      clearOverlays() {},
      world: { getItemAt: () => null },
      viewport: { zoomBy() {}, applyConstraints() {}, goHome() {} },
    };
  },
}));

import { ScanViewer } from "./components/ScanViewer";
import { SessionProvider } from "./state";
import { fakeFetch } from "./__fixtures__/visitor";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

let root: Root | null = null;
let host: HTMLElement | null = null;

beforeAll(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, onchange: null, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;
});

beforeEach(() => {
  viewers.length = 0;
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  host?.remove();
  vi.unstubAllGlobals();
});

const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

async function mount(info: Response | Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    String(input).includes("/iiif/") ? Promise.resolve(info) : fakeFetch(input, init)));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root!.render(<SessionProvider><ScanViewer iiif="/iiif/38/info.json" fileId={38} label="scan" /></SessionProvider>));
  for (let i = 0; i < 5; i++) await tick();
  return viewers[viewers.length - 1];
}

const INFO = { "@context": "http://iiif.io/api/image/3/context.json", id: "https://api.example.org/iiif/38", type: "ImageService3", width: 1190, height: 1684 };

describe("ScanViewer", () => {
  it("loads tiles from where info.json was fetched, not from the host the server names", async () => {
    const v = await mount(new Response(JSON.stringify(INFO), { status: 200 }));
    expect(v.opened).toHaveLength(1);
    const src = v.opened[0] as { id: string; width: number };
    expect(src.id).toBe(`${window.location.origin}/iiif/38`);
    expect(src.width).toBe(1190);
  });

  it("shows the delivery image when tiles fail to load", async () => {
    const v = await mount(new Response(JSON.stringify(INFO), { status: 200 }));
    await act(async () => v.handlers["tile-load-failed"].forEach((fn) => fn()));
    await act(async () => v.handlers["tile-load-failed"].forEach((fn) => fn()));
    expect(v.opened).toHaveLength(2);
    expect(v.opened[1]).toMatchObject({ type: "image" });
    expect(String((v.opened[1] as { url: string }).url)).toContain("/api/visitor/files/38");
  });

  it("full screen covers the window where the Fullscreen API is missing, and Esc or the button leaves it", async () => {
    await mount(new Response(JSON.stringify(INFO), { status: 200 }));
    const wrap = () => document.querySelector<HTMLElement>(".osd-wrap")!;
    const button = () => document.querySelector<HTMLButtonElement>(".osd-full")!;
    expect(button().getAttribute("aria-pressed")).toBe("false");
    await act(async () => button().click());
    expect(wrap().classList.contains("full-window")).toBe(true);
    expect(button().getAttribute("aria-pressed")).toBe("true");
    expect(document.body.classList.contains("scan-fullwindow-open")).toBe(true);
    await act(async () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
    expect(wrap().classList.contains("full-window")).toBe(false);
    expect(document.body.classList.contains("scan-fullwindow-open")).toBe(false);
    await act(async () => button().click());
    await act(async () => button().click());
    expect(wrap().classList.contains("is-full")).toBe(false);
  });

  it("uses the browser's Fullscreen API on the viewer when it exists", async () => {
    const requested: Element[] = [];
    Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: true });
    HTMLElement.prototype.requestFullscreen = function (this: HTMLElement) {
      requested.push(this);
      Object.defineProperty(document, "fullscreenElement", { configurable: true, value: this });
      document.dispatchEvent(new Event("fullscreenchange"));
      return Promise.resolve();
    };
    try {
      await mount(new Response(JSON.stringify(INFO), { status: 200 }));
      await act(async () => document.querySelector<HTMLButtonElement>(".osd-full")!.click());
      expect(requested).toEqual([document.querySelector(".osd-wrap")]);
      expect(document.querySelector(".osd-wrap")!.classList.contains("is-full")).toBe(true);
    } finally {
      delete (HTMLElement.prototype as Partial<HTMLElement>).requestFullscreen;
      Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: false });
      Object.defineProperty(document, "fullscreenElement", { configurable: true, value: null });
    }
  });

  it("shows the delivery image when info.json is not available", async () => {
    const v = await mount(new Response("<!doctype html>", { status: 404 }));
    expect(v.opened).toEqual([expect.objectContaining({ type: "image" })]);
  });
});
