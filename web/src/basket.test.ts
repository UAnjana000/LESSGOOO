import { describe, expect, it } from "vitest";
import { basketLink } from "./basket";

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
