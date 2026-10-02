import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "./App";
import { SessionProvider } from "./state";
import { fakeFetch } from "./__fixtures__/visitor";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

vi.setConfig({ testTimeout: 30_000 });

const LONG = "The Society for the Promotion of Education of the Depressed Classes";
const MAP = {
  nodes: [
    { id: 1, type: "person", labels: { en: "B. R. Ambedkar" }, description: null, item_ids: [1], items: [{ id: 1, title: "Annihilation of Caste" }] },
    { id: 2, type: "organisation", labels: { en: LONG }, description: null, item_ids: [], items: [] },
    { id: 3, type: "mystery_kind", labels: { en: "Odd one" }, description: null, item_ids: [], items: [] },
  ],
  edges: [{ id: 1, from: 1, to: 2, relation: "spoke_at" }],
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
    if (url.endsWith("/api/visitor/map")) {
      return Promise.resolve(new Response(JSON.stringify(MAP), { status: 200, headers: { "Content-Type": "application/json" } }));
    }
    return fakeFetch(input, init);
  }));
  sessionStorage.clear();
  localStorage.clear();
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  host?.remove();
  host = null;
  vi.unstubAllGlobals();
});

async function mountMap() {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const router = createMemoryRouter(routes, { initialEntries: ["/map"] });
  await act(async () => root!.render(<SessionProvider><RouterProvider router={router} /></SessionProvider>));
  for (let i = 0; i < 200 && !document.querySelector("[data-node-id]"); i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  expect(document.querySelector("[data-node-id]")).not.toBeNull();
}

const node = (id: number) => document.querySelector<SVGGElement>(`[data-node-id="${id}"]`)!;
const fire = (el: Element, type: string, x = 10, y = 10) => act(async () => { el.dispatchEvent(new MouseEvent(type, { bubbles: true, clientX: x, clientY: y })); });
const wrap = () => document.querySelector(".heritage-canvas-wrap")!;
const inspectorTitle = () => document.querySelector(".inspector-entity-title")?.textContent;

async function tap(id: number) {
  await fire(node(id), "pointerdown");
  await fire(wrap(), "pointerup");
}

describe("knowledge map graph", () => {
  it("a single tap selects a node once and does not toggle it back off", async () => {
    await mountMap();
    await tap(1);
    expect(inspectorTitle()).toBe("B. R. Ambedkar");
    expect(node(1).getAttribute("aria-pressed")).toBe("true");
    // the click browsers send after a tap must not flip the selection
    await fire(node(1), "click");
    expect(inspectorTitle()).toBe("B. R. Ambedkar");
  });

  it("a drag does not select", async () => {
    await mountMap();
    await fire(node(1), "pointerdown");
    await fire(wrap(), "pointermove", 80, 60);
    await fire(wrap(), "pointerup", 80, 60);
    expect(inspectorTitle()).toBeUndefined();
  });

  it("nodes are keyboard buttons: Enter selects", async () => {
    await mountMap();
    const n = node(1);
    expect(n.getAttribute("role")).toBe("button");
    expect(n.getAttribute("tabindex")).toBe("0");
    expect(n.getAttribute("aria-label")).toBe("B. R. Ambedkar, Person");
    await act(async () => { n.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
    expect(inspectorTitle()).toBe("B. R. Ambedkar");
  });

  it("truncates long node labels and keeps the full text as a title", async () => {
    await mountMap();
    const text = node(2).querySelector("text")!;
    expect(text.textContent).toContain("…");
    expect(text.querySelector("title")?.textContent).toBe(LONG);
    const shown = [...text.childNodes].filter((c) => c.nodeType === 3).map((c) => c.textContent).join("");
    expect(shown.length).toBeLessThanOrEqual(24);
  });

  it("never renders a raw i18n key for an unknown node type or relation", async () => {
    await mountMap();
    expect(node(3).getAttribute("aria-label")).toBe("Odd one, Mystery kind");
    await tap(1);
    expect(document.body.textContent).not.toMatch(/node_mystery|rel_spoke/);
    expect(document.querySelector(".heritage-edge-label text")?.textContent).toBe("spoke at");
    expect(document.querySelector(".relation-tag")?.textContent).toBe("spoke at");
  });

  it("shows the one-line intro and evidence titles from the map response", async () => {
    await mountMap();
    expect(document.querySelector(".map-intro")?.textContent).toContain("Tap a name");
    await tap(1);
    expect(document.querySelector(".evidence-text")?.textContent).toBe("Annihilation of Caste");
  });
});
