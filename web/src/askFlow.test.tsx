import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "./App";
import type { AskResult } from "./api";
import { SessionProvider } from "./state";
import { fakeFetch } from "./__fixtures__/visitor";
import { STRINGS } from "./i18n";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

vi.setConfig({ testTimeout: 30_000 });

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
  sessionStorage.setItem("archive-visit", JSON.stringify({ lang: "en", textScale: 1, contrast: false, askHistory: [], sessionId: "visitor-1", basket: [] }));
});

afterEach(async () => {
  await unmount();
  vi.unstubAllGlobals();
});

async function unmount() {
  await act(async () => root?.unmount());
  root = null;
  host?.remove();
  host = null;
}

const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

async function waitFor(check: () => boolean, what: string) {
  for (let i = 0; i < 200 && !check(); i++) await tick();
  expect(check(), what).toBe(true);
}

async function mount(path: string, ready: string) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  await act(async () => root!.render(<SessionProvider><RouterProvider router={router} /></SessionProvider>));
  await waitFor(() => !!document.querySelector(ready), `${ready} on ${path}`);
}

const text = (sel: string) => document.querySelector(sel)?.textContent ?? "";
const box = () => document.querySelector<HTMLTextAreaElement>("#ask-q")!;
const visit = () => JSON.parse(sessionStorage.getItem("archive-visit") ?? "{}");

function type(value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
  setter.call(box(), value);
  box().dispatchEvent(new Event("input", { bubbles: true }));
}

const enter = () => box().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function answerFixture(): Promise<AskResult> {
  return (await fakeFetch("/api/visitor/ask", { method: "POST" })).json();
}

/** fetch whose Ask replies wait until the test releases them; everything else is the normal fixture. */
function heldAsk() {
  const asks: { init: RequestInit; release: (r: Response) => void }[] = [];
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST" && String(input).endsWith("/api/visitor/ask")) {
      return new Promise<Response>((resolve) => asks.push({ init, release: resolve }));
    }
    return fakeFetch(input, init);
  }));
  return asks;
}

function askWith(...replies: (() => Response | Promise<Response>)[]) {
  const bodies: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST" && String(input).endsWith("/api/visitor/ask")) {
      bodies.push(JSON.parse(String(init.body)));
      return replies[Math.min(bodies.length, replies.length) - 1]();
    }
    return fakeFetch(input, init);
  }));
  return bodies;
}

describe("Ask requests", () => {
  it("a double Enter sends one question, not two paid requests", async () => {
    const asks = heldAsk();
    await mount("/ask", "#ask-q");
    await act(async () => type("What is caste?"));
    await act(async () => {
      enter();
      enter();
    });
    expect(asks).toHaveLength(1);
    await act(async () => asks[0].release(json(200, await answerFixture())));
    await waitFor(() => !!document.querySelector(".answer .cite-link"), "answer shown");
    expect(asks).toHaveLength(1);
  });

  it("an answer arriving after Finish never reaches the next visitor", async () => {
    const asks = heldAsk();
    await mount("/ask", "#ask-q");
    await act(async () => type("What did I ask about my family?"));
    await act(async () => enter());
    expect(asks).toHaveLength(1);
    const confirm = [...document.querySelectorAll<HTMLButtonElement>("dialog button")].find((b) => b.textContent === STRINGS.en.finishConfirm)!;
    await act(async () => confirm.click());
    expect(asks[0].init.signal?.aborted).toBe(true);
    await act(async () => asks[0].release(json(200, await answerFixture())));
    await tick();
    const after = visit();
    expect(after.sessionId).not.toBe("visitor-1");
    expect(after.askHistory).toEqual([]);
    expect(after.askLast ?? null).toBeNull();
  });

  it("a 503 is an error with Try again, not 'needs a connection', and the question is kept", async () => {
    const bodies = askWith(() => json(503, { detail: "busy" }), async () => json(200, await answerFixture()));
    await mount("/ask", "#ask-q");
    await act(async () => type("What is caste?"));
    await act(async () => enter());
    await waitFor(() => text(".answer").includes(STRINGS.en.errorGeneric), "error shown");
    expect(text(".answer")).not.toContain(STRINGS.en.askOffline);
    expect(box().value).toBe("What is caste?");
    const retry = [...document.querySelectorAll<HTMLButtonElement>(".answer button")].find((b) => b.textContent === STRINGS.en.retry)!;
    await act(async () => retry.click());
    await waitFor(() => !!document.querySelector(".answer .cite-link"), "answer after retry");
    expect(bodies.map((b) => (b as { question: string }).question)).toEqual(["What is caste?", "What is caste?"]);
    expect(box().value).toBe("");
  });

  it("a lost connection says Ask needs a connection and offers Try again", async () => {
    askWith(() => Promise.reject(new TypeError("Failed to fetch")));
    await mount("/ask", "#ask-q");
    await act(async () => type("What is caste?"));
    await act(async () => enter());
    await waitFor(() => text(".answer").includes(STRINGS.en.askOffline), "offline shown");
    expect(text(".answer")).toContain(STRINGS.en.retry);
  });

  it("text typed while waiting survives the answer", async () => {
    const asks = heldAsk();
    await mount("/ask", "#ask-q");
    await act(async () => type("What is caste?"));
    await act(async () => enter());
    await act(async () => type("And what about"));
    await act(async () => asks[0].release(json(200, await answerFixture())));
    await waitFor(() => !!document.querySelector(".answer .cite-link"), "answer shown");
    expect(box().value).toBe("And what about");
  });

  it("a too-long question says so instead of 'Refused', and ?q= is cut to 500 characters", async () => {
    const bodies = askWith(() => json(200, {
      outcome: "rejected_input", reason: "too_long", language: "en", label: null, sentences: [], citations: [],
      message: "This question is too long. Please shorten it to 500 characters or fewer and ask again.",
      paraphrase_only: false, retried_retrieval: false,
    }));
    await mount(`/ask?q=${"a".repeat(700)}`, ".answer .chip");
    expect(text(".answer .chip")).toBe(STRINGS.en.askTooLong);
    expect(text(".answer")).not.toContain(STRINGS.en.askRefused);
    expect((bodies[0] as { question: string }).question).toHaveLength(500);
  });
});

describe("Ask beyond the archive", () => {
  it("a background answer is labelled as not from archive sources, has no citation marks, and links archive items", async () => {
    const answer = await answerFixture();
    askWith(() => json(200, {
      ...answer, outcome: "background", label: "AI general background, not from archive sources", checks: null,
      message: "The archive's own documents do not answer this directly.",
      sentences: [{ text: "Dr. Ambedkar chaired the Drafting Committee.", citations: [] }],
    }));
    await mount("/ask?q=Who%20chaired%20the%20drafting%20committee%3F", ".answer .chip.background");
    expect(text(".answer .chip.background")).toBe(STRINGS.en.askBackgroundLabel);
    expect(text(".answer")).toContain("Dr. Ambedkar chaired the Drafting Committee.");
    expect(text(".answer")).toContain(STRINGS.en.askBackgroundNote);
    expect(text(".answer")).not.toContain(STRINGS.en.askLabel);
    expect(document.querySelector(".answer .cite-link")).toBeNull();
    expect(text(".answer summary")).toContain(STRINGS.en.askExploreArchive);
    expect(visit().askHistory).toHaveLength(1);
  });

  it("an off-topic question offers suggested questions that ask on click", async () => {
    const bodies = askWith(
      () => json(200, { outcome: "off_topic", language: "en", label: null, message: "x", sentences: [], citations: [], paraphrase_only: false, retried_retrieval: false }),
      async () => json(200, await answerFixture()),
    );
    await mount("/ask?q=Who%20won%20the%20cricket%20match%3F", ".ask-suggestions button");
    expect(text(".answer")).toContain(STRINGS.en.askOffTopic);
    const first = document.querySelector<HTMLButtonElement>(".ask-suggestions button")!;
    expect(first.textContent).toBe(STRINGS.en.askSuggest1);
    await act(async () => first.click());
    await waitFor(() => !!document.querySelector(".answer .cite-link"), "answer to the suggestion");
    expect((bodies[1] as { question: string }).question).toBe(STRINGS.en.askSuggest1);
  });

  it("a server-side answer failure says the answer service did not respond", async () => {
    askWith(() => json(200, { outcome: "error", language: "en", label: null, message: "The answer service did not respond.", sentences: [], citations: [], paraphrase_only: false, retried_retrieval: false }));
    await mount("/ask?q=What%20is%20caste%3F", ".answer .notice");
    expect(text(".answer .notice")).toBe(STRINGS.en.askServiceError);
  });
});

describe("Ask answer notes and memory", () => {
  it("the 'citations and quotes were checked' note needs the server's check result", async () => {
    const answer = await answerFixture();
    askWith(() => json(200, answer));
    await mount("/ask?q=What%20is%20caste%3F", ".answer .cite-link");
    expect(text(".answer")).not.toContain(STRINGS.en.claimNote);
    await unmount();
    askWith(() => json(200, { ...answer, checks: { citations_ok: true, quotes: 1, quotes_verified: 1 } }));
    await mount("/ask?q=What%20is%20it%3F", ".answer .cite-link");
    expect(text(".answer")).toContain(STRINGS.en.claimNote);
  });

  it("going back to Ask shows the last answer again without asking again", async () => {
    const bodies = askWith(async () => json(200, await answerFixture()));
    await mount("/ask?q=What%20is%20caste%3F", ".answer .cite-link");
    await unmount();
    await mount("/ask", "#ask-q");
    await waitFor(() => !!document.querySelector(".answer .cite-link"), "restored answer");
    expect(text(".answer h2")).toBe("What is caste?");
    expect(bodies).toHaveLength(1);
  });
});
