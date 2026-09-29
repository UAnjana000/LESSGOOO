import { describe, expect, it } from "vitest";
import type { PageView } from "./api";
import { basketLink, itemCitation } from "./basket";

describe("basketLink", () => {
  it("links an item-only entry to the item", () => {
    expect(basketLink({ item_id: 7, title: "T", citation: "T" })).toBe("/item/7");
  });

  it("links a page entry to that page", () => {
    expect(basketLink({ item_id: 7, title: "T", page: 3, citation: "T, p. 3" })).toBe("/item/7?page=3");
  });

  it("links a passage entry to its page and passage", () => {
    expect(basketLink({ item_id: 7, title: "T", page: 3, passage_id: 41, citation: "T" })).toBe("/item/7?page=3&passage=41");
  });

  it("links a recording segment with the start time so the player seeks", () => {
    expect(basketLink({ item_id: 9, title: "R", start_ms: 12500, passage_id: 88, citation: "R, at 0:12" })).toBe("/item/9?t=12500&passage=88");
  });

  it("keeps a segment that starts at zero milliseconds", () => {
    expect(basketLink({ item_id: 9, title: "R", start_ms: 0, citation: "R, at 0:00" })).toBe("/item/9?t=0");
  });

  it("ignores null values restored from saved sessions", () => {
    const restored = JSON.parse('{"item_id": 5, "title": "T", "page": null, "start_ms": null, "passage_id": 2, "citation": "T"}');
    expect(basketLink(restored)).toBe("/item/5?passage=2");
  });
});

describe("itemCitation", () => {
  const page = (citation: string) => ({ citation }) as PageView;

  it("drops the page from the first page's citation", () => {
    const title = "Reply to the debate (Writings and Speeches, Vol. 13, pp. 1206-1218)";
    expect(itemCitation({ title, edition: "Third reprint, 2020", volume: "13", pages: [page(`${title}, Third reprint, 2020, Vol. 13, p. 1206`)] }))
      .toBe(`${title}, Third reprint, 2020, Vol. 13`);
  });

  it("builds the citation from title, edition and volume when the item has no pages", () => {
    expect(itemCitation({ title: "Speech at Nagpur", edition: null, volume: "17", pages: [] })).toBe("Speech at Nagpur, Vol. 17");
  });
});
