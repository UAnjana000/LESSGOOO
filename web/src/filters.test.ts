import { describe, expect, it } from "vitest";
import { browsePath, facetLink, hasFilters, MAX_QUERY, searchPath } from "./filters";

const p = (s: string) => new URLSearchParams(s);

describe("searchPath", () => {
  it("returns null when there is no query", () => {
    expect(searchPath(p("collection=debates"))).toBeNull();
    expect(searchPath(p("q=%20%20"))).toBeNull();
  });

  it("carries the query and every search filter", () => {
    const got = new URLSearchParams(searchPath(p("q=caste&collection=writings&item_type=photograph&lang=hi&date_from=1930-01-01&date_to=1950-12-31&subject=Education&person=B.%20R.%20Ambedkar&place=Mahad"))!.split("?")[1]);
    expect(Object.fromEntries(got)).toEqual({
      q: "caste", collection: "writings", item_type: "photograph", lang: "hi",
      date_from: "1930-01-01", date_to: "1950-12-31", subject: "Education", person: "B. R. Ambedkar", place: "Mahad",
    });
  });

  it("drops empty and unknown parameters", () => {
    expect(searchPath(p("q=tank&collection=&page=3&kiosk=1"))).toBe("/api/visitor/search?q=tank");
  });

  it("trims the query and clamps it to the length the API accepts", () => {
    expect(searchPath(p("q=%20%20tank%20"))).toBe("/api/visitor/search?q=tank");
    const q = new URLSearchParams(searchPath(p(`q=${"a".repeat(MAX_QUERY + 50)}`))!.split("?")[1]).get("q")!;
    expect(q).toHaveLength(MAX_QUERY);
  });
});

describe("browsePath", () => {
  it("lists every visible item when no filter is set", () => {
    expect(browsePath(p(""))).toBe("/api/visitor/items");
  });

  it("maps the visitor language filter to the items endpoint's language parameter", () => {
    expect(browsePath(p("lang=mr"))).toBe("/api/visitor/items?language=mr");
  });

  it("passes type, subject, person and place and skips date filters", () => {
    const got = new URLSearchParams(browsePath(p("collection=photographs&item_type=photograph&subject=Satyagraha&person=Savita%20Ambedkar&place=Mahad&date_from=1927-01-01"))!.split("?")[1]);
    expect(Object.fromEntries(got)).toEqual({ collection: "photographs", item_type: "photograph", subject: "Satyagraha", person: "Savita Ambedkar", place: "Mahad" });
  });
});

describe("facetLink", () => {
  it("builds an encoded browse link for a subject, person or place", () => {
    expect(facetLink("person", "B. R. Ambedkar")).toBe("/search?person=B.+R.+Ambedkar");
    expect(facetLink("place", "Mahad & Nagpur")).toBe("/search?place=Mahad+%26+Nagpur");
  });
});

describe("hasFilters", () => {
  it("is true only when a filter other than the query is set", () => {
    expect(hasFilters(p("q=tank"))).toBe(false);
    expect(hasFilters(p("q=tank&subject="))).toBe(false);
    expect(hasFilters(p("subject=Education"))).toBe(true);
  });
});
