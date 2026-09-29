import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "./App";
import { ApiError } from "./api";
import { ErrorState } from "./components/Bits";
import { SessionProvider } from "./state";
import { fakeFetch } from "./__fixtures__/visitor";
import { STRINGS } from "./i18n";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

const en = STRINGS.en;
let root: Root | null = null;
let host: HTMLElement | null = null;

beforeAll(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, onchange: null, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;
  Element.prototype.scrollIntoView ??= () => {};
});

beforeEach(() => {
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

async function render(node: React.ReactNode) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root!.render(<SessionProvider>{node}</SessionProvider>));
}

const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const settle = async () => {
  for (let i = 0; i < 20; i++) await tick();
};
/** Waits until `done` holds (the router and its data load over several turns). */
const until = async (done: () => boolean) => {
  for (let i = 0; i < 200 && !done(); i++) await tick();
};

/** What the service worker answers when the archive server is unreachable. */
const swOffline = (status: number) =>
  ({ ok: false, status, statusText: "", headers: new Headers({ "content-type": "application/json", "x-archive-offline": "1" }), json: async () => ({ detail: "offline" }) }) as unknown as Response;

describe("error notices tell visitors when the screen is offline", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn(fakeFetch)));

  it.each([
    ["an item this screen may not keep offline", new ApiError(404, "x", true), en.onlineOnly, true],
    ["no saved copy", new ApiError(503, "offline", true), en.offlineBanner, true],
    ["the server unreachable", new ApiError(0, "offline", true), en.offlineBanner, true],
    ["a missing item online", new ApiError(404, "x"), en.notAvailable, false],
    ["an invalid item address", new ApiError(422, "x"), en.notAvailable, false],
    ["a server error", new ApiError(500, "x"), en.errorGeneric, true],
  ])("%s", async (_, error, message, canRetry) => {
    await render(<ErrorState error={error} retry={() => {}} />);
    expect(document.querySelector(".notice p")?.textContent).toBe(message);
    expect(document.querySelector(".notice button") !== null).toBe(canRetry);
  });
});

describe("offline banner and recovery", () => {
  async function mount(path: string) {
    const router = createMemoryRouter(routes, { initialEntries: [path] });
    await render(<RouterProvider router={router} />);
    await settle();
  }

  it("shows the offline banner when the archive server cannot be reached, even with a network", async () => {
    expect(navigator.onLine).toBe(true);
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await mount("/");
    await until(() => document.querySelector(".banner.offline") !== null);
    expect(document.querySelector(".banner.offline")?.textContent).toBe(en.offlineBanner);

    vi.stubGlobal("fetch", vi.fn(fakeFetch));
    await act(async () => { window.dispatchEvent(new Event("online")); });
    await until(() => document.querySelector(".banner.offline") === null);
    expect(document.querySelector(".banner.offline")).toBeNull();
  });

  it("explains an online-only item offline and loads it again when the connection returns", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => (String(input).includes("/items/") ? swOffline(404) : fakeFetch(input, init))));
    await mount("/item/1");
    await until(() => document.querySelector(".notice.bad") !== null);
    expect(document.querySelector(".notice.bad p")?.textContent).toBe(en.onlineOnly);
    expect(document.querySelector(".notice.bad button")?.textContent).toBe(en.retry);
    expect(document.querySelector(".banner.offline")).not.toBeNull();

    vi.stubGlobal("fetch", vi.fn(fakeFetch));
    await act(async () => { window.dispatchEvent(new Event("online")); });
    await until(() => document.querySelector(".notice.bad") === null && document.querySelector(".banner.offline") === null);
    expect(document.querySelector(".notice.bad")).toBeNull();
    expect(document.querySelector(".banner.offline")).toBeNull();
  });
});
